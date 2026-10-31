"""Bounded native profile mechanics; no real-provider inference or credentials in output."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys
import traceback

from cragkit._postgres_pool import PoolConfig, PoolResource
from cragkit.contracts import parse_request, parse_scope
from cragkit.embeddings import EmbeddingAdapter, EmbeddingPolicy, FAKE_PROFILE, OPENAI_PROFILE
from cragkit.errors import CragkitError
from cragkit.execution import ExecutionLedger
from cragkit.postgres_corrective import PostgresCorrectiveBackend
from cragkit.retrieval import PostgresRetriever
from cragkit.vector_ingestion import PostgresVectorIndexer

SOURCE = 'Profile mechanics preserve exact source evidence.'
COLLECTION = 'profile-checks'
DOCUMENT = 'profile-document'
INTENT = 'profile-intent'
LOCATOR = 'fixture:profile'
QUERY = 'Profile mechanics'
SCOPE = dict(tenant_id='profile-tenant', collection=COLLECTION,
             principal_id='profile-reader', grant_ids=['profile-grant'], authorization_revision='1')
CHECKS = ['fake_stage_publish_replay', 'fake_dense_source', 'fake_hybrid_source',
          'tenant_scope_negative', 'principal_scope_negative', 'required_filter_negative',
          'openai_default_refusal', 'openai_retrieval_dispatch_boundary',
          'openai_indexer_dispatch_boundary', 'openai_corrective_accounting']


class ProfileCaseError(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise ProfileCaseError(code)


class MeteredResource(PoolResource):
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


class Counter:
    def __init__(self, live):
        self.name = 'cl100k_base' if live else 'fake-byte-v1'
        self.live = live

    def count(self, text):
        return 1 if self.live else len(text.encode('utf-8'))


def configuration(value):
    require(type(value) is dict and 'password' not in value, 'invalid_configuration')
    data = dict(value)
    data['sslrootcert'], data['passfile'] = Path(data['sslrootcert']), Path(data['passfile'])
    data['max_size'], data['max_waiting'] = 1, 1
    return PoolConfig.model_validate(data)


def deadline():
    return asyncio.get_running_loop().time() + 25


def evidence_view(result):
    return [dict(document_id=item.document_id, revision_id=item.revision_id,
                 source_sha256=item.source_sha256, text_sha256=item.text_sha256,
                 start_byte=item.start_byte, end_byte=item.end_byte)
            for item in result.evidence]


async def run_cases(value):
    require(type(value) is dict and set(value) == {'reader_config', 'writer_config', 'storage'}, 'invalid_input')
    storage = value['storage']
    require(storage in ('legacy', 'upgraded'), 'invalid_storage')
    reader = MeteredResource(configuration(value['reader_config']))
    writer = MeteredResource(configuration(value['writer_config']))
    resources = (reader, writer)
    checks, observations = [], []
    scope = parse_scope({key: item for key, item in SCOPE.items() if key != 'collection'})
    request = parse_request(dict(query=QUERY, collection=COLLECTION))

    def embedder(*, live=False):
        calls = []
        async def transport(body, *, deadline, max_response_bytes):
            require(not any(resource.active for resource in resources), 'model_lease_overlap')
            calls.append(True)
            if live:
                # Deliberately no vector result: never persist synthetic OpenAI rows.
                raise RuntimeError('injected_provider_unavailable')
            payload = json.loads(body)
            count = sum(len(text.encode('utf-8')) for text in payload['input'])
            return json.dumps(dict(model=FAKE_PROFILE.model,
                data=[dict(index=index, embedding=[1.] + [0.]*1535) for index in range(len(payload['input']))],
                usage=dict(prompt_tokens=count, total_tokens=count))).encode()
        options = dict(profile=OPENAI_PROFILE,
            policy=EmbeddingPolicy(allow_live=True, max_cost_usd=.01, usd_per_million_tokens=.02)) if live else {}
        return EmbeddingAdapter(transport, Counter(live), **options), calls

    async def authorize(bound, collection, document):
        return bound == scope and collection == COLLECTION and document in (DOCUMENT, 'profile-openai-document')

    def arguments(document=DOCUMENT, intent=INTENT):
        return dict(collection=COLLECTION, document_id=document, intent_id=intent,
                    source_locator=LOCATOR, scope=scope, deadline=deadline())

    async def error_code(operation):
        try:
            await operation()
        except CragkitError as error:
            return error.code
        raise ProfileCaseError('expected_refusal')

    async def no_release(target, selected_request, selected_scope):
        try:
            result = await target.retrieve(selected_request, scope=selected_scope, deadline=deadline())
        except CragkitError as error:
            require(error.code in ('unsupported_capability', 'unauthorized_scope'), 'unexpected_scope_refusal')
        else:
            require(not result.evidence, 'scope_evidence_leak')

    try:
        await reader.open()
        await writer.open()
        fake, _ = embedder()
        indexer = PostgresVectorIndexer(writer, authorize_write=authorize, embedder=fake)
        staged = await indexer.stage(SOURCE, **arguments())
        published = await indexer.publish(SOURCE, **arguments())
        replay = await indexer.stage(SOURCE, **arguments())
        require(staged.generation_id == published.generation_id == replay.generation_id
                and replay.replayed and replay.provider_calls == 0 and published.embedding_profile == FAKE_PROFILE.profile_id,
                'fake_replay_identity')
        checks.append(CHECKS[0])
        observations.append(dict(case='fake_identity', document_id=DOCUMENT,
            revision_id=published.revision_id, generation_id=published.generation_id,
            embedding_profile=published.embedding_profile, replayed=True))
        for mode in ('dense', 'hybrid'):
            adapter, _ = embedder()
            target = PostgresRetriever(reader, mode=mode, embedder=adapter)
            result = await target.retrieve(request, scope=scope, deadline=deadline())
            require(len(result.evidence) == 1 and result.evidence[0].text == SOURCE
                    and result.evidence[0].document_id == DOCUMENT and result.execution == 'complete'
                    and result.usage.provider_calls == 1 and result.usage.cost_kind == 'known'
                    and result.usage.cost_usd == 0, 'fake_native_source')
            checks.append('fake_' + mode + '_source')
            observations.append(dict(case='fake_' + mode, evidence=evidence_view(result),
                provider_calls=result.usage.provider_calls, cost_kind=result.usage.cost_kind,
                cost_usd=result.usage.cost_usd))
        negative_adapter, _ = embedder()
        target = PostgresRetriever(reader, mode='dense', embedder=negative_adapter)
        await no_release(target, request, scope.model_copy(update={'tenant_id': 'profile-other-tenant'}))
        checks.append(CHECKS[3])
        await no_release(target, request, parse_scope(dict(tenant_id=scope.tenant_id,
            principal_id='profile-outsider', grant_ids=[], authorization_revision='1')))
        checks.append(CHECKS[4])
        filtered = parse_request(dict(query=QUERY, collection=COLLECTION,
            required_filters=[dict(op='eq', field='document_id', value='absent-profile-document')]))
        await no_release(target, filtered, scope)
        checks.append(CHECKS[5])
        adapter, calls = embedder(live=True)
        async def default_refusal():
            target = PostgresRetriever(reader, mode='dense', embedder=adapter)
            await target.retrieve(request, scope=scope, deadline=deadline())
        require(await error_code(default_refusal) == 'embedding_profile_mismatch' and not calls,
                'default_profile_disclosure')
        checks.append(CHECKS[6])
        expected_error = 'unsupported_capability' if storage == 'legacy' else 'provider_unavailable'
        expected_calls = int(storage == 'upgraded')
        adapter, calls = embedder(live=True)
        target = PostgresRetriever(reader, mode='dense', embedder=adapter, embedding_profile=OPENAI_PROFILE)
        code = await error_code(lambda: target.retrieve(request, scope=scope, deadline=deadline()))
        require(code == expected_error and len(calls) == expected_calls, 'retrieval_dispatch_boundary')
        checks.append(CHECKS[7])
        observations.append(dict(case='openai_retrieval', error_code=code, transport_calls=len(calls)))
        adapter, calls = embedder(live=True)
        live_indexer = PostgresVectorIndexer(writer, authorize_write=authorize, embedder=adapter,
                                             embedding_profile=OPENAI_PROFILE)
        code = await error_code(lambda: live_indexer.stage(SOURCE,
            **arguments('profile-openai-document', 'profile-openai-intent')))
        require(code == expected_error and len(calls) == expected_calls, 'indexer_dispatch_boundary')
        checks.append(CHECKS[8])
        observations.append(dict(case='openai_indexer', error_code=code, transport_calls=len(calls)))
        adapter, calls = embedder(live=True)
        backend = PostgresCorrectiveBackend(reader, mode='dense', embedder=adapter, embedding_profile=OPENAI_PROFILE)
        end = deadline()
        ledger = ExecutionLedger(request.limits, deadline=end)
        code = await error_code(lambda: backend.search(request, scope=scope, deadline=end, limit=4, ledger=ledger))
        usage = ledger.snapshot()
        require(code == expected_error and len(calls) == usage['provider_calls'] == expected_calls
                and usage['pending'] == 0 and usage['cost_kind'] == ('unknown' if expected_calls else 'known'),
                'corrective_dispatch_accounting')
        checks.append(CHECKS[9])
        observations.append(dict(case='openai_corrective', error_code=code, transport_calls=len(calls),
            provider_calls=usage['provider_calls'], input_tokens=usage['input_tokens'],
            output_tokens=usage['output_tokens'], cost_usd=usage['cost_usd'], cost_kind=usage['cost_kind']))
        require(checks == CHECKS, 'incomplete_cases')
    except BaseException as error:
        error.failed_check = CHECKS[min(len(checks), len(CHECKS) - 1)]
        raise
    finally:
        closed = await asyncio.gather(*(resource.close() for resource in resources), return_exceptions=True)
        require(not any(isinstance(result, BaseException) for result in closed)
                and not any(resource.active for resource in resources), 'resource_cleanup_failed')
    return dict(runtime='python', storage=storage, checks=checks, observations=observations,
                cleanup_verified=True, live_inference=False)


def main():
    try:
        raw = sys.stdin.buffer.read(1048577)
        require(len(raw) <= 1048576, 'input_limit')
        value = json.loads(raw)
        async def bounded():
            async with asyncio.timeout(120):
                return await run_cases(value)
        result = asyncio.run(bounded())
        code = 0
    except BaseException as error:
        result = dict(runtime='python', state='failed', error_code='native_profile_case_failed',
                      cleanup_verified=False, live_inference=False,
                      error_type=type(error).__name__)
        root = Path(__file__).resolve().parents[1]
        frames = [frame for frame in traceback.extract_tb(error.__traceback__)
                  if Path(frame.filename).resolve().is_relative_to(root)]
        result['frames'] = [dict(module=Path(frame.filename).name, line=frame.lineno,
                                 function=frame.name) for frame in frames[-4:]]
        failed_check = getattr(error, 'failed_check', None)
        if failed_check in CHECKS:
            result['failed_check'] = failed_check
        if isinstance(error, ProfileCaseError):
            result['failure_code'] = str(error)
        elif isinstance(error, CragkitError):
            result['failure_code'] = error.code
        code = 1
    print(json.dumps(result, allow_nan=False, separators=(',', ':')))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
