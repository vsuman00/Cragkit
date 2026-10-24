"""Native HY-r1 acceptance and frozen development-only synthetic ablation."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'evaluation/runners'))
from synthetic_vectors import encode
from v2_metrics import aggregate, score_question


class HybridCheckError(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise HybridCheckError(code)


def normalized(result):
    value = deepcopy(result)
    for stage in value['usage']['stage_durations']:
        stage['duration_ms'] = 0
    return value


async def run(config, fixture, admin, *, typescript=False, neon=False):
    from psycopg import sql
    from cragkit._postgres_pool import PoolResource
    from cragkit._postgres_session import PostgresSession, _query
    from cragkit.contracts import parse_request, parse_scope
    from cragkit.embeddings import EmbeddingAdapter, FAKE_PROFILE
    from cragkit.errors import CragkitError
    from cragkit.retrieval import PostgresRetriever
    from cragkit.vector_ingestion import PostgresVectorIndexer

    spec = json.loads((ROOT / 'contracts/fixtures/hybrid.json').read_text())
    manifest_bytes = (ROOT / 'evaluation/corpus/manifest.json').read_bytes()
    labels_bytes = (ROOT / 'evaluation/questions/dev.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    labels = json.loads(labels_bytes)
    require(labels['human_review']['state'] == 'approved', 'labels_not_approved')
    documents = [item for item in manifest['documents'] if item['split'] == 'development']
    wanted = set(spec['evaluation']['question_ids'])
    questions = [item for item in labels['questions'] if item['question_id'] in wanted]
    require(len(questions) == len(wanted) == 6, 'evaluation_selection_changed')
    scopes = [parse_scope(value) for value in fixture['scopes']]
    scoped = dict(zip(('tenant-a', 'tenant-b'), scopes, strict=True))
    collection = fixture['collection']
    resource = PoolResource(config.model_copy(update={'max_size': 1}))
    loop = asyncio.get_running_loop()
    checks, cases, receipts = [], [], {}
    active = {}
    stage = 'seed'

    class Counter:
        name = 'fake-byte-v1'
        def count(self, text): return len(text.encode('utf-8'))

    async def transport(body, *, deadline, max_response_bytes):
        value = json.loads(body)
        return json.dumps(dict(model=FAKE_PROFILE.model,
            data=[dict(index=index, embedding=encode(text)) for index, text in enumerate(value['input'])],
            usage=dict(prompt_tokens=sum(len(text.encode('utf-8')) for text in value['input']),
                       total_tokens=sum(len(text.encode('utf-8')) for text in value['input'])))).encode()

    def embedder(): return EmbeddingAdapter(transport, Counter())
    async def allowed(scope, target, document):
        return scope in scopes and target == collection and document in {item['document_id'] for item in documents}
    async def command(statement, parameters=None):
        async with asyncio.timeout(8): return await admin.execute(statement, parameters)

    def request(question, mode):
        filters = deepcopy(question['required_filters'])
        for condition in filters:
            if condition['field'] == 'revision_id':
                candidates = [r for key, r in receipts.items() if key[0] == question['tenant_id']
                              and key[2] == condition['value']
                              and all(f['field'] != 'document_id' or key[1] == f['value'] for f in filters)]
                require(len(candidates) == 1, 'revision_filter_ambiguous')
                condition['value'] = candidates[0]['revision_id']
        return parse_request(dict(request_id='v2-eval-'+question['question_id']+'-'+mode,
            query=question['query'], collection=collection, required_filters=filters,
            limits=dict(max_candidates=spec['evaluation']['max_candidates'],
                        max_context_tokens=spec['evaluation']['max_context_tokens'])))

    def retriever(mode, *, degraded=False):
        return PostgresRetriever(resource) if mode == 'lexical' else PostgresRetriever(
            resource, mode=mode, embedder=embedder(), allow_degraded=degraded)

    async def fault(entry):
        base = PostgresSession(resource)
        target = retriever('hybrid', degraded=entry['allow_degraded'])
        parsed = parse_request(dict(query='ERR-17', collection=collection,
                                   required_filters=[dict(field='document_id', op='eq', value='retry-policy')]))
        class FaultSession:
            @asynccontextmanager
            async def transaction(self, *args, **kwargs):
                async with base.transaction(*args, **kwargs) as handle:
                    if not hasattr(self, 'selected'):
                        self.selected = True
                        marker = config.user + '_hybrid'
                        snapshot = await _query(handle._connection,
                            "SELECT set_config('cragkit.hybrid_probe',%s,true),pg_current_snapshot()::text",
                            (marker,), loop.time()+8)
                        for family in ('dense','lexical','identifier'):
                            if family == entry['family']: continue
                            original = getattr(handle, family+'_candidates')
                            async def guarded(*args, _original=original, **kwargs):
                                current = await _query(handle._connection,
                                    "SELECT current_setting('cragkit.hybrid_probe',true),pg_current_snapshot()::text",
                                    None, loop.time()+8)
                                require(current == snapshot, 'branch_snapshot_or_transaction_changed')
                                return await _original(*args, **kwargs)
                            setattr(handle, family+'_candidates', guarded)
                        async def fail(*args, **kwargs):
                            # Real PostgreSQL statement failure, recovered only by SAVEPOINT rollback.
                            await _query(handle._connection, 'SELECT 1/0', None, loop.time()+8)
                            raise HybridCheckError('fault_not_raised')
                        setattr(handle, entry['family']+'_candidates', fail)
                    yield handle
        target._session = FaultSession()
        try:
            result = await target.retrieve(parsed, scope=scopes[0], deadline=loop.time()+20)
        except CragkitError as error:
            require(entry.get('expected_error') == error.code, 'fault_wrong_error')
        else:
            require(result.execution == entry.get('expected_execution') and bool(result.evidence), 'fault_not_degraded')
            require(any(item.stage == entry['family']+'_failed_provider_unavailable' for item in result.usage.stage_durations), 'fault_diagnostic_missing')
            require(all(item.document_id == 'retry-policy' for item in result.evidence), 'fault_filter_broadened')
        checks.append('python_'+entry['id'].replace('-', '_'))

    writes = ('collections','documents','document_revisions','index_generations','chunks','chunk_lexical','document_grants','ingestion_jobs','chunk_vectors_fake_1536')
    try:
        await resource.open()
        indexer = PostgresVectorIndexer(resource, authorize_write=allowed, embedder=embedder())
        for item in documents:
            key = (item['tenant_id'], item['document_id'])
            source = (ROOT / 'evaluation/corpus' / item['path']).read_bytes()
            require(sha256(source).hexdigest() == item['canonical_sha256'], 'source_digest_changed')
            receipt = await indexer.ingest(source, collection=collection, document_id=item['document_id'],
                intent_id='eval-'+item['tenant_id']+'-'+item['document_id']+'-'+item['revision_id'],
                source_locator='synthetic:v2-evaluation', scope=scoped[item['tenant_id']],
                deadline=loop.time()+30, expected_generation_id=active.get(key), canonical_options=dict(target_bytes=2048, max_chunk_bytes=4096))
            receipts[(*key, item['revision_id'])] = receipt.model_dump(mode='json')
            active[key] = receipt.generation_id
        for table in writes:
            await command(sql.SQL('REVOKE INSERT,UPDATE ON cragkit.{} FROM {}').format(sql.Identifier(table),sql.Identifier(config.user)))
        stage = 'faults'
        for entry in spec['fault_cases']: await fault(entry)
        stage = 'source_reauthorization'
        target = retriever('hybrid')
        base = PostgresSession(resource)
        class SourceBoundary:
            count = 0
            @asynccontextmanager
            async def transaction(self, *args, **kwargs):
                self.count += 1
                if self.count == 2:
                    await command('UPDATE cragkit.documents SET tombstoned=true WHERE tenant_id=%s AND collection_id=%s AND document_id=%s',
                                  (scopes[0].tenant_id,collection,'retry-policy'))
                async with base.transaction(*args, **kwargs) as handle: yield handle
        target._session = SourceBoundary()
        try:
            result = await target.retrieve(parse_request(dict(query='ERR-17',collection=collection,
                required_filters=[dict(field='document_id',op='eq',value='retry-policy')])),scope=scopes[0],deadline=loop.time()+25)
            require(not result.evidence and result.status=='insufficient'
                    and any(item.code=='stale_evidence' for item in result.limitations),'hybrid_source_reauthorization')
        finally:
            await command('UPDATE cragkit.documents SET tombstoned=false WHERE tenant_id=%s AND collection_id=%s AND document_id=%s',
                          (scopes[0].tenant_id,collection,'retry-policy'))
        checks.append('python_hybrid_fresh_source_tombstone_denied')
        stage = 'evaluation'
        scores = {mode: [] for mode in spec['evaluation']['modes']}
        records = []
        reverse = {(tenant, value['document_id'], value['revision_id']): logical
                   for (tenant, doc, logical), value in receipts.items()}
        for question in questions:
            for mode in spec['evaluation']['modes']:
                parsed = request(question, mode)
                started = time.perf_counter()
                result = await retriever(mode).retrieve(parsed, scope=scoped[question['tenant_id']], deadline=loop.time()+25)
                duration = (time.perf_counter()-started)*1000
                value = result.model_dump(mode='json')
                evidence = [dict(document_id=e.document_id,
                    revision_id=reverse[(question['tenant_id'],e.document_id,e.revision_id)],
                    start_byte=e.start_byte,end_byte=e.end_byte) for e in result.evidence]
                metric = score_question(question, evidence, k=spec['evaluation']['k'])
                scores[mode].append(metric)
                records.append(dict(mode=mode, metrics=metric, ranked=[(e['document_id'],e['revision_id']) for e in evidence], latency_ms=duration))
                cases.append(dict(mode=mode, request=parsed.model_dump(mode='json'), scope=scoped[question['tenant_id']].model_dump(mode='json'), expected=normalized(value)))
        checks.append('python_development_ablation_18_requests_verified_sources')
        if typescript:
            await resource.close()
            child = await run_node(config, dict(**fixture,cases=cases,fault_cases=spec['fault_cases'],neon=neon), admin)
            checks.extend(child['checks'])
        else: child = dict(latency_ms={})
        summary = {mode: dict(aggregate(scores[mode]),
                    latency_ms=dict(python_median=statistics.median([row['latency_ms'] for row in records if row['mode']==mode]),
                                    node_median=statistics.median(child['latency_ms'][mode]) if typescript else None),
                    model_cost_usd=0, model_cost_kind='known') for mode in scores}
        return dict(state='passed', revision='HY-r1', checks=checks, maximum_connections=2, cleanup_verified=True,
            evaluation=dict(kind='synthetic_mechanics_only', encoder=spec['evaluation']['synthetic_encoder'],
                manifest_sha256=sha256(manifest_bytes).hexdigest(), development_labels_sha256=sha256(labels_bytes).hexdigest(),
                question_ids=spec['evaluation']['question_ids'], k=spec['evaluation']['k'],
                max_candidates=spec['evaluation']['max_candidates'], modes=summary, records=records,
                limitations=['small_fixed_development_sample','synthetic_embeddings_not_model_quality',
                             'historical_revision_candidate_search_active_only','hosting_cost_unmeasured','held_out_not_evaluated']))
    except CragkitError as error:
        raise HybridCheckError(stage+'_'+error.code) from None
    finally:
        await resource.close()


async def run_node(config, fixture, admin):
    process = None
    key = (fixture['scopes'][0]['tenant_id'],fixture['collection'],'retry-policy')
    async def tombstone(enabled):
        async with asyncio.timeout(8):
            await admin.execute('UPDATE cragkit.documents SET tombstoned=%s WHERE tenant_id=%s AND collection_id=%s AND document_id=%s',
                                (enabled,*key))
    try:
        with tempfile.TemporaryDirectory(prefix='cragkit-hybrid-node-') as directory:
            paths = [Path(directory)/name for name in ('runtime.json','fixture.json')]
            for path, value in zip(paths,(config.model_dump(mode='json'),fixture),strict=True):
                descriptor = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(descriptor,'w') as stream: json.dump(value,stream)
            process = await asyncio.create_subprocess_exec('node',str(Path(__file__).with_name('check_typescript_hybrid.mjs')),
                '--allow-hybrid-checks',*(str(path) for path in paths),stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,limit=65536)
            result = None
            async with asyncio.timeout(240):
                while line := await process.stdout.readline():
                    value=json.loads(line)
                    if value.get('type')=='owner':
                        require(value.get('action')=='tombstone' and type(value.get('enabled')) is bool,'invalid_owner_action')
                        await tombstone(value['enabled'])
                        process.stdin.write(b'{"ok":true}\n')
                        await process.stdin.drain()
                    else:
                        require(result is None and value.get('state')=='passed','node_hybrid_failed')
                        result=value
                require(await process.wait()==0 and result is not None,'node_hybrid_failed')
            return result
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await asyncio.wait_for(process.wait(),5)
        await tombstone(False)
