"""Label-free bounded native retrieval evaluation; provider execution is explicit."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from functools import cmp_to_key
from hashlib import sha256
import json
from pathlib import Path
import re
import time

from cragkit._identifiers import extract_identifiers
from cragkit._postgres_pool import PoolConfig, PoolResource
from cragkit.contracts import parse_request, parse_result, parse_scope
from cragkit.contracts._validation import identity, native_json, scalar
from cragkit.context import Cl100kCounter
from cragkit.corrective import CorrectiveRetriever
from cragkit.embeddings import EmbeddingAdapter, EmbeddingPolicy, FAKE_PROFILE, OPENAI_PROFILE
from cragkit.errors import CragkitError, InvalidRequest
from cragkit.planning import PlannerAdapter
from cragkit.postgres_corrective import PostgresCorrectiveBackend
from cragkit.reranking import RerankingAdapter, RerankProfile
from cragkit.retrieval import PostgresRetriever
from cragkit.vector_ingestion import PostgresVectorIndexer
from provider_adapters import OpenAIEmbeddingTransport, CohereRerankTransport

MODES = ('lexical', 'dense', 'hybrid', 'reranked_hybrid', 'corrective')
_LIMITS = dict(deadline_ms=25000, max_candidates=15, max_attempts=3, max_subqueries=3,
               max_provider_calls=8, max_context_tokens=20000)
_OUTPUT = dict(renderer='cragkit.context.v2', tokenizer='cl100k_base', counting_mode='strict',
               envelope_reserve_tokens=256)
_WORKER_SECONDS = 900


class EvaluationExecutionError(ValueError):
    """Fixed worker diagnostics, never source or configuration details."""


def _compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _scope(tenant):
    return parse_scope(dict(tenant_id=tenant, principal_id='v6-evaluation',
                            authorization_revision='v6-auth-r1', grant_ids=[]))


def _text(value, maximum):
    if type(value) is not str or not value or len(value) > maximum:
        raise ValueError()
    raw = value.encode('utf-8')
    if len(raw) > maximum:
        raise ValueError()
    return raw


def validate_packet(packet):
    failed = False
    try:
        if (type(packet) is not dict or set(packet) != {'revision', 'documents', 'queries'}
                or packet['revision'] != 'EVX-r1' or type(packet['documents']) is not list
                or not 1 <= len(packet['documents']) <= 32 or type(packet['queries']) is not list
                or not 1 <= len(packet['queries']) <= 30):
            raise ValueError()
        seen, active, locations, size = set(), {}, set(), 0
        for document in packet['documents']:
            if type(document) is not dict or set(document) != {'tenant_id', 'collection', 'document_id', 'revision_id', 'active', 'text', 'canonical_sha256'}:
                raise ValueError()
            for field in ('tenant_id', 'document_id', 'revision_id'):
                identity(document[field])
            _scope(document['tenant_id'])
            parse_request(dict(query='validation', collection=document['collection']))
            if type(document['active']) is not bool:
                raise ValueError()
            raw = _text(document['text'], 65536)
            if document['canonical_sha256'] != sha256(raw).hexdigest():
                raise ValueError()
            key = tuple(document[field] for field in ('tenant_id', 'collection', 'document_id', 'revision_id'))
            if key in seen:
                raise ValueError()
            seen.add(key)
            active[key[:3]] = active.get(key[:3], 0) + int(document['active'])
            locations.add(key[:2])
            size += len(raw)
        if any(count != 1 for count in active.values()):
            raise ValueError()
        ids = set()
        for query in packet['queries']:
            if type(query) is not dict or set(query) != {'question_id', 'tenant_id', 'collection', 'query', 'required_filters'}:
                raise ValueError()
            if type(query['required_filters']) is not list:
                raise ValueError()
            identity(query['question_id'])
            _scope(query['tenant_id'])
            if query['question_id'] in ids or (query['tenant_id'], query['collection']) not in locations:
                raise ValueError()
            ids.add(query['question_id'])
            size += len(_text(query['query'], 8192))
            parse_request(dict(query=query['query'], collection=query['collection'], required_filters=query['required_filters']))
        if size > 1048576:
            raise ValueError()
        native_json(packet)
        snapshot = json.loads(_compact(packet))
    except Exception:
        failed = True
    if failed:
        raise EvaluationExecutionError('invalid_evaluation_packet')
    return snapshot


def document_order(document):
    return (*(document[field].encode('utf-8') for field in ('tenant_id', 'collection', 'document_id')),
            int(document['active']), document['revision_id'].encode('utf-8'))


def translate_filters(filters, receipts, tenant_id, collection):
    aliases = {}
    for receipt in receipts:
        if (receipt['tenant_id'], receipt['collection']) == (tenant_id, collection):
            aliases.setdefault(receipt['logical_revision_id'], set()).add(receipt['revision_id'])
    def membership(values):
        translated, seen = [], set()
        for value in values:
            matches = aliases.get(value, {value}) if type(value) is str else [scalar(value)]
            for native in matches:
                key = ('string' if type(native) is str else 'boolean' if type(native) is bool else 'number', native)
                if key not in seen:
                    translated.append(native)
                    seen.add(key)
        def compare(left, right):
            a, b = ((left.encode('utf-8'), right.encode('utf-8'))
                    if type(left) is str and type(right) is str else (_compact(left), _compact(right)))
            return (a > b) - (a < b)
        translated.sort(key=cmp_to_key(compare))
        leaves = [dict(op='in', field='revision_id', values=translated[start:start+32])
                  for start in range(0, len(translated), 32)]
        return leaves[0] if len(leaves) == 1 else dict(op='or', filters=leaves)
    def translate(item):
        if item['op'] in ('and', 'or'):
            return dict(op=item['op'], filters=[translate(child) for child in item['filters']])
        if item['op'] == 'not':
            return dict(op='not', filter=translate(item['filter']))
        if item.get('field') == 'revision_id':
            if item['op'] in ('eq', 'ne') and type(item['value']) is str:
                matched = membership([item['value']])
                return matched if item['op'] == 'eq' else dict(op='not', filter=matched)
            if item['op'] == 'in':
                return membership(item['values'])
        return json.loads(_compact(item))
    return [translate(item) for item in filters]


def query_variants(query):
    variants, seen = [], {query}
    normalized = re.sub(r'[ \t\r\n\f\v]+', ' ', query).strip(' \t\r\n\f\v')
    identifiers = ' '.join(extract_identifiers(query))
    for name, value in (('normalized', normalized), ('identifiers', identifiers)):
        if value and value not in seen:
            variants.append(dict(facet_id='query-intent', variant_id=name, query=value))
            seen.add(value)
    return variants


class _Resource(PoolResource):
    def __init__(self, config):
        super().__init__(config)
        self.active = 0
    @asynccontextmanager
    async def lease(self, *, deadline):
        async with super().lease(deadline=deadline) as connection:
            self.active += 1
            try:
                yield connection
            finally:
                self.active -= 1


class _Counter:
    def __init__(self, counter=None):
        self.name = 'cl100k_base' if counter is not None else 'fake-byte-v1'
        self._counter = counter
    def count(self, text):
        return self._counter.count(text) if self._counter is not None else len(text.encode('utf-8'))


def _config(value):
    failed = False
    try:
        data = value.model_dump() if type(value) is PoolConfig else dict(value)
        data['sslrootcert'], data['passfile'] = Path(data['sslrootcert']), Path(data['passfile'])
        data['max_size'] = 1
        result = PoolConfig.model_validate(data)
    except Exception:
        failed = True
    if failed:
        raise EvaluationExecutionError('invalid_evaluation_configuration')
    return result


async def run_evaluation(packet, *, reader_config, writer_config, tokenizer_path, kind='mechanics', send=None):
    packet = validate_packet(packet)
    if type(kind) is not str or kind not in ('mechanics', 'provider') or (kind == 'mechanics' and send is not None) or (kind == 'provider' and not callable(send)):
        raise EvaluationExecutionError('invalid_evaluation_configuration')
    reader, writer = _Resource(_config(reader_config)), _Resource(_config(writer_config))
    counter = None
    rows, receipts, failure = [], [], None
    try:
        async with asyncio.timeout(_WORKER_SECONDS):
            counter = Cl100kCounter.from_file(tokenizer_path)
            profile = FAKE_PROFILE if kind == 'mechanics' else OPENAI_PROFILE
            def no_lease():
                if reader.active or writer.active:
                    raise InvalidRequest()
            async def fake_embed(body, *, deadline, max_response_bytes):
                no_lease()
                value = json.loads(body)
                return _compact(dict(model=FAKE_PROFILE.model,
                    data=[dict(index=index, embedding=[1.0]+[0.0]*1535) for index in range(len(value['input']))],
                    usage=dict(prompt_tokens=0, total_tokens=0)))
            async def fake_rank(body, *, deadline, max_response_bytes):
                no_lease()
                value = json.loads(body)
                return _compact([dict(candidate_id=item['candidate_id'], raw_score=1/(index+1))
                                 for index, item in enumerate(value['candidates'])])
            if kind == 'mechanics':
                embedder = EmbeddingAdapter(fake_embed, _Counter())
                reranker = RerankingAdapter(fake_rank)
            else:
                embedding_transport, rank_transport = OpenAIEmbeddingTransport(send), CohereRerankTransport(send)
                async def embedded(body, **options):
                    no_lease()
                    return await embedding_transport(body, **options)
                async def ranked(body, **options):
                    no_lease()
                    return await rank_transport(body, **options)
                embedder = EmbeddingAdapter(embedded, _Counter(counter), profile=profile,
                    policy=EmbeddingPolicy(allow_live=True, max_cost_usd=.01, usd_per_million_tokens=.02))
                reranker = RerankingAdapter(ranked, allow_live=True, profile=RerankProfile(
                    profile_id='cohere_v5fast_evaluation_v1', provider='cohere', model='rerank-v5.0-fast',
                    model_revision='mutable_alias:rerank-v5.0-fast', score_kind='relevance_score',
                    score_direction='higher_is_better', preprocessing_revision='utf8-evaluation-r1', truncation_policy='reject'))
            identities = {(d['tenant_id'], d['collection'], d['document_id']) for d in packet['documents']}
            async def authorize(scope, collection, document):
                return scope == _scope(scope.tenant_id) and (scope.tenant_id, collection, document) in identities
            indexer = PostgresVectorIndexer(writer, authorize_write=authorize, embedder=embedder, embedding_profile=profile)
            await writer.open()
            previous, native_ids = {}, set()
            for document in sorted(packet['documents'], key=document_order):
                key = tuple(document[field] for field in ('tenant_id', 'collection', 'document_id'))
                digest = sha256(_compact([*key, document['revision_id']])).hexdigest()
                receipt = await indexer.ingest(document['text'], collection=document['collection'],
                    document_id=document['document_id'], intent_id='eval-'+digest, source_locator='evaluation:'+digest,
                    scope=_scope(document['tenant_id']), deadline=asyncio.get_running_loop().time()+25,
                    expected_generation_id=previous.get(key), canonical_options=dict(target_bytes=2048,max_chunk_bytes=4096))
                if receipt.canonical_sha256 != document['canonical_sha256'] or (*key, receipt.revision_id) in native_ids:
                    raise InvalidRequest()
                native_ids.add((*key, receipt.revision_id))
                previous[key] = receipt.generation_id
                receipts.append(dict(tenant_id=key[0], collection=key[1], document_id=key[2],
                    logical_revision_id=document['revision_id'], revision_id=receipt.revision_id,
                    generation_id=receipt.generation_id, canonical_sha256=receipt.canonical_sha256,
                    embedding_profile=receipt.embedding_profile, active=document['active']))
            await writer.close()
            await reader.open()
            async def plan(payload, *, deadline):
                no_lease()
                selected = [dict(facet_id=item['facet_id'], variant_id=item['variant_id']) for item in payload['variants']
                            if item['facet_id'] in payload['missing_facets']][:payload['max_subqueries']-1]
                return dict(plan=dict(queries=selected), usage=dict(input_tokens=0, output_tokens=0, cost_usd=0))
            for query in packet['queries']:
                filters = translate_filters(query['required_filters'], receipts, query['tenant_id'], query['collection'])
                for mode in MODES:
                    started = time.perf_counter()
                    try:
                        request = parse_request(dict(request_id='eval-'+sha256(_compact([query['question_id'],mode])).hexdigest(),
                            query=query['query'], collection=query['collection'], required_filters=filters,
                            limits=dict(_LIMITS), output_profile=dict(_OUTPUT)))
                        scope = _scope(query['tenant_id'])
                        if mode == 'corrective':
                            backend = PostgresCorrectiveBackend(reader, mode='hybrid', embedder=embedder,
                                embedding_profile=profile, reranker=reranker)
                            target = CorrectiveRetriever(backend, variants=query_variants(query['query']),
                                planner=PlannerAdapter(plan,cost_upper_usd=0), counter=counter, max_retries=0, batch_size=15)
                            result = (await target.retrieve(request, scope=scope, deadline=asyncio.get_running_loop().time()+25))['result']
                        else:
                            options = dict(evidence_options=dict(counter=counter))
                            if mode == 'reranked_hybrid':
                                options['evidence_options']['reranker'] = reranker
                            if mode != 'lexical':
                                options.update(embedder=embedder, embedding_profile=profile)
                            target = PostgresRetriever(reader, mode='hybrid' if mode == 'reranked_hybrid' else mode, **options)
                            result = await target.retrieve(request, scope=scope, deadline=asyncio.get_running_loop().time()+25)
                            result = result.model_dump(mode='json')
                        result = parse_result(result).model_dump(mode='json')
                    except CragkitError as error:
                        result = dict(operational_failure=True, error_code=error.code)
                    except Exception:
                        result = dict(operational_failure=True, error_code='evaluation_execution_failed')
                    rows.append(dict(question_id=query['question_id'], mode=mode, result=result,
                                     latency_ms=(time.perf_counter()-started)*1000))
    except BaseException as error:
        failure = error
    finally:
        cleanup = asyncio.gather(reader.close(), writer.close(), return_exceptions=True)
        while True:
            try:
                closed = await asyncio.shield(cleanup)
                break
            except asyncio.CancelledError as error:
                failure = error
        counter = None
    if failure is not None:
        if isinstance(failure, asyncio.CancelledError):
            raise failure
        raise EvaluationExecutionError('evaluation_execution_failed')
    if any(isinstance(error, BaseException) for error in closed):
        raise EvaluationExecutionError('evaluation_cleanup_failed')
    return dict(revision='EVX-r1', runtime='python', kind=kind, receipts=receipts, rows=rows, cleanup_verified=True)
