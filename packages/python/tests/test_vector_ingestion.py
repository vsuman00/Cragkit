"""Synthetic VG-r1 staging checks; no provider, database, or model service."""
import asyncio
import copy
import json

import pytest

import cragkit.ingestion as lexical
import cragkit.vector_ingestion as implementation
from cragkit.embeddings import EmbeddingAdapter, EmbeddingLimits, FAKE_PROFILE
from cragkit.errors import (DeadlineExceeded, EmbeddingProfileMismatch, IndexNotReady,
    IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability)
from test_ingestion import Connection as LexicalConnection, Cursor, Resource, allow_write
from cragkit.contracts import parse_scope


class Connection(LexicalConnection):
    def __init__(self):
        super().__init__()
        self.profile = [(FAKE_PROFILE.profile_id, FAKE_PROFILE.provider, FAKE_PROFILE.model,
            FAKE_PROFILE.dimensions, FAKE_PROFILE.tokenizer, FAKE_PROFILE.normalization,
            'chunk_vectors_fake_1536')]
        self.capability = [(True,)]
        self.vector_job = []
        self.vector_generation = []
        self.vector_revision = []
        self.manifest = []
        self.vectors = {}
        self.grants = [(True,)]
        self.missing_override = None
        self.counts_override = None
        self.vector_count_override = None

    def transaction(self, *, force_rollback=False):
        parent = super().transaction(force_rollback=force_rollback)
        connection = self
        class Transaction:
            async def __aenter__(self):
                self.before = copy.deepcopy((connection.vector_job, connection.vector_generation,
                    connection.vector_revision, connection.manifest, connection.vectors))
                return await parent.__aenter__()
            async def __aexit__(self, kind, value, traceback):
                result = await parent.__aexit__(kind, value, traceback)
                if kind is not None:
                    (connection.vector_job, connection.vector_generation, connection.vector_revision,
                        connection.manifest, connection.vectors) = self.before
                return result
        return Transaction()

    async def execute(self, query, params=None):
        responses = {
            implementation._VECTOR_CAPABILITY_SQL: self.capability,
            implementation._SETUP_HISTORY_SQL: list(implementation.EXPECTED_VECTOR_HISTORY),
            implementation._PROFILE_SQL: self.profile,
            implementation._VECTOR_JOB_SQL: self.vector_job,
            implementation._VECTOR_GENERATION_SQL: self.vector_generation,
            implementation._VECTOR_REVISION_SQL: self.vector_revision,
            implementation._MANIFEST_SQL: self.manifest,
            implementation._GRANTS_SQL: self.grants,
            implementation._MISSING_SQL: self.missing_override if self.missing_override is not None else
                [(row[0],) for row in self.manifest if row[0] not in self.vectors],
            implementation._VECTOR_COUNTS_SQL: self.vector_count_override if self.vector_count_override is not None else [(len(self.vectors),)],
            lexical._COUNTS_SQL: self.counts_override if self.counts_override is not None else [(len(self.manifest), len(self.manifest))],
        }
        if query in responses:
            self.calls.append((query, params))
            return Cursor(responses[query])
        result = await super().execute(query, params)
        if query.lstrip().startswith('INSERT INTO cragkit.ingestion_jobs'):
            self.vector_job = [(params[4], params[5], 'running', params[2], 1)]
        if query.lstrip().startswith('INSERT INTO cragkit.document_revisions'):
            self.vector_revision = [(params[4], params[7], params[5], params[8], params[6])]
        if query.lstrip().startswith('INSERT INTO cragkit.index_generations'):
            self.vector_generation = [(params[3], 'staging', params[-1], FAKE_PROFILE.profile_id, params[5], 'native_fts.v1')]
        if query == lexical._CHUNKS_SQL:
            self.manifest = [(row['chunk_id'], row['ordinal'], row['start_byte'], row['end_byte'],
                row['text'], row['text_sha256'], row['metadata']) for row in json.loads(params[-1])]
        if query == implementation._VECTOR_INSERT_SQL:
            for row in json.loads(params[-1]):
                self.vectors[row['chunk_id']] = row['embedding']
        if query.lstrip().startswith('UPDATE cragkit.ingestion_jobs') and 'attempt_count' in query:
            old = self.vector_job[0]
            self.vector_job = [(*old[:4], old[4] + 1)]
        return result


def scope(**changes):
    values = dict(tenant_id='tenant', principal_id='principal', authorization_revision='auth', grant_ids=['unassigned-group'])
    values.update(changes)
    return parse_scope(values)


class Counter:
    name = 'fake-byte-v1'
    def count(self, text): return len(text.encode('utf-8'))


class Transport:
    def __init__(self, connection, resource):
        self.connection = connection
        self.resource = resource
        self.calls = []
        self.change = None
        self.failure_at = None
        self.block = False
        self.entered = asyncio.Event()
    async def __call__(self, body, *, deadline, max_response_bytes):
        assert self.resource.leased == self.resource.returned
        assert self.connection.info.transaction_status == 0
        payload = json.loads(body)
        self.calls.append(payload)
        if self.failure_at == len(self.calls): raise RuntimeError('private transport secret')
        if self.block:
            self.entered.set()
            await asyncio.Event().wait()
        data = [{'index': index, 'embedding': [1.0] + [0.0] * 1535}
            for index in range(len(payload['input']))]
        response = {'model': FAKE_PROFILE.model, 'data': data}
        if self.change is not None: self.change(response)
        return json.dumps(response).encode()


def fixture(*, authorize=allow_write, limits=None, **options):
    connection = Connection()
    resource = Resource(connection)
    transport = Transport(connection, resource)
    adapter = EmbeddingAdapter(transport, Counter(), limits=limits)
    indexer = implementation.PostgresVectorIndexer(resource, authorize_write=authorize,
        embedder=adapter, **options)
    return connection, resource, transport, indexer


async def stage(indexer, source='synthetic source', **changes):
    arguments = dict(collection='collection', document_id='document', intent_id='intent',
        source_locator='synthetic:source', scope=scope(), deadline=asyncio.get_running_loop().time()+2)
    arguments.update(changes)
    return await indexer.stage(source, **arguments)


def test_staging_commits_vectors_without_readiness_or_pointer_publication():
    async def run():
        connection, resource, transport, indexer = fixture()
        receipt = await stage(indexer)
        assert receipt.embedding_profile == FAKE_PROFILE.profile_id
        assert receipt.provider_calls == 1 and len(receipt.usage) == 1
        assert receipt.usage[0].cost_usd == 0 and receipt.chunk_count == 1
        assert connection.vectors and connection.vector_generation[0][1] == 'staging'
        assert not connection.published
        assert all("SET status='ready'" not in query for query, _ in connection.calls)
        assert resource.leased == resource.returned and connection.info.transaction_status == 0
        scope_index = next(index for index,(query,_) in enumerate(connection.calls)
            if "set_config('cragkit.tenant_id'" in query)
        job_index = next(index for index,(query,_) in enumerate(connection.calls)
            if query == implementation._VECTOR_JOB_SQL)
        assert scope_index < job_index
        assert transport.calls[0]['input'] == ['synthetic source']
    asyncio.run(run())


def test_running_identical_intent_resumes_only_missing_vectors():
    async def run():
        connection, resource, transport, indexer = fixture(limits=EmbeddingLimits(max_items=1))
        transport.failure_at = 2
        source = 'first\n\nsecond\n\nthird'
        options = {'target_bytes': 6}
        with pytest.raises(ProviderUnavailable): await stage(indexer, source, canonical_options=options)
        assert len(connection.vectors) == 1 and not connection.published
        first = transport.calls[0]['input']
        transport.failure_at = None
        result = await stage(indexer, source, canonical_options=options)
        assert len(connection.vectors) == result.chunk_count == 3
        assert all(call['input'] != first for call in transport.calls[2:])
        assert result.provider_calls == 2 and len(result.usage) == 2
        assert resource.leased == resource.returned
    asyncio.run(run())


def test_same_staged_intent_requires_no_more_provider_calls_and_changed_source_rejects():
    async def run():
        connection, _, transport, indexer = fixture()
        first = await stage(indexer)
        second = await stage(indexer)
        assert first.generation_id == second.generation_id and len(transport.calls) == 1
        assert second.provider_calls == 0 and second.usage == ()
        with pytest.raises(InvalidRequest): await stage(indexer, 'changed source')
        assert len(transport.calls) == 1 and not connection.published
    asyncio.run(run())


@pytest.mark.parametrize('mutate,kind', [
    (lambda response: response.update(model='other-model'), EmbeddingProfileMismatch),
    (lambda response: response.update(data=[]), ProviderUnavailable),
    (lambda response: response['data'][0].update(embedding=[1.0]), EmbeddingProfileMismatch),
    (lambda response: response['data'][0]['embedding'].__setitem__(0, 2.0), ProviderUnavailable),
    (lambda response: response['data'].append(response['data'][0]), ProviderUnavailable),
])
def test_invalid_provider_batch_never_writes_vectors(mutate,kind):
    async def run():
        connection, resource, transport, indexer = fixture()
        transport.change = mutate
        with pytest.raises(kind): await stage(indexer)
        assert not connection.vectors and not connection.published
        assert resource.leased == resource.returned
    asyncio.run(run())


@pytest.mark.parametrize('field,value', [('capability',[(False,)]),('profile',[]),
    ('profile',[(FAKE_PROFILE.profile_id,'fake','other-model',1536,'fake-byte-v1','l2','chunk_vectors_fake_1536')])])
def test_capability_and_exact_profile_fail_before_provider(field, value):
    async def run():
        connection, resource, transport, indexer = fixture()
        setattr(connection, field, value)
        with pytest.raises(UnsupportedCapability): await stage(indexer)
        assert not transport.calls and not connection.published
        assert resource.leased == resource.returned
    asyncio.run(run())


def test_authorizer_denies_before_database_provider_or_canonicalization():
    async def deny(*args): return False
    async def run():
        connection, resource, transport, indexer = fixture(authorize=deny)
        with pytest.raises(UnauthorizedScope):
            await stage(indexer, canonical_options={'token_counter': lambda text: pytest.fail('parsed unauthorized input')})
        assert resource.leased == 0 and not connection.calls and not transport.calls
    asyncio.run(run())


@pytest.mark.parametrize('column,value', [(0,'foreign-chunk'),(2,99),(4,'corrupt private text'),(5,'bad-digest')])
def test_resume_rejects_corrupted_persisted_manifest_before_provider(column,value):
    async def run():
        connection, _, transport, indexer = fixture()
        await stage(indexer)
        connection.vectors.clear()
        row = list(connection.manifest[0]); row[column] = value; connection.manifest[0] = tuple(row)
        with pytest.raises(IntegrityViolation): await stage(indexer)
        assert len(transport.calls) == 1 and not connection.published
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['cancel','deadline'])
def test_provider_cancellation_or_deadline_releases_admission_and_resources(mode):
    async def run():
        connection, resource, transport, indexer = fixture()
        transport.block = True
        task = asyncio.create_task(stage(indexer, deadline=asyncio.get_running_loop().time()+(.03 if mode=='deadline' else 2)))
        await transport.entered.wait()
        if mode == 'cancel': task.cancel()
        with pytest.raises(asyncio.CancelledError if mode=='cancel' else DeadlineExceeded): await task
        assert resource.leased == resource.returned and not connection.vectors and not connection.published
        transport.block = False
        await stage(indexer)
        assert connection.vectors
    asyncio.run(run())


def test_inflight_indexer_has_no_waiting_queue():
    async def run():
        connection, _, transport, indexer = fixture()
        transport.block = True
        task = asyncio.create_task(stage(indexer))
        await transport.entered.wait()
        with pytest.raises(IndexNotReady): await stage(indexer)
        assert len(transport.calls) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert not connection.published
    asyncio.run(run())


@pytest.mark.parametrize('option,value', [('max_batches',0),('max_batches',129),('max_batches',True),
    ('max_attempts',0),('max_attempts',9),('max_attempts',True)])
def test_indexer_bounds_can_only_be_reduced(option,value):
    with pytest.raises(InvalidRequest): fixture(**{option:value})


def test_batch_limit_rejects_entire_workload_before_database_and_provider():
    async def run():
        connection, resource, transport, indexer = fixture(limits=EmbeddingLimits(max_items=1),max_batches=1)
        with pytest.raises(InvalidRequest):
            await stage(indexer,'first\n\nsecond',canonical_options={'target_bytes':6})
        assert resource.leased == 0 and not connection.calls and not transport.calls
    asyncio.run(run())


def test_resume_attempt_limit_does_not_retry_provider():
    async def run():
        connection, _, transport, indexer = fixture(max_attempts=1)
        transport.failure_at = 1
        with pytest.raises(ProviderUnavailable): await stage(indexer)
        transport.failure_at = None
        with pytest.raises(IndexNotReady): await stage(indexer)
        assert len(transport.calls) == 1 and not connection.vectors
    asyncio.run(run())


def test_colliding_document_ids_in_different_tenants_have_distinct_generation_identity():
    async def run():
        left, _, _, first = fixture()
        right, _, _, second = fixture()
        a = await stage(first)
        b = await stage(second,scope=scope(tenant_id='other-tenant'))
        assert a.generation_id != b.generation_id and a.revision_id != b.revision_id
        assert a.payload_sha256 != b.payload_sha256
        for connection,tenant in [(left,'tenant'),(right,'other-tenant')]:
            for query,params in connection.calls:
                if query in (implementation._MISSING_SQL,implementation._MANIFEST_SQL,
                    implementation._VECTOR_JOB_SQL,implementation._VECTOR_INSERT_SQL):
                    assert params[0] == tenant
    asyncio.run(run())


def test_current_document_revocation_or_tombstone_prevents_resume_provider():
    async def run():
        for document in [[('old',True,'auth')],[('old',False,'revoked')]]:
            connection, _, transport, indexer = fixture()
            await stage(indexer)
            connection.vectors.clear()
            connection.document = document
            with pytest.raises(UnauthorizedScope): await stage(indexer)
            assert len(transport.calls) == 1 and not connection.vectors
    asyncio.run(run())


def test_succeeded_intent_replay_verifies_ready_manifest_without_provider():
    async def run():
        connection, _, transport, indexer = fixture()
        receipt = await stage(indexer)
        job = connection.vector_job[0]
        connection.vector_job = [(job[0],job[1],'succeeded',job[3],job[4])]
        generation = connection.vector_generation[0]
        connection.vector_generation = [(generation[0],'ready',*generation[2:])]
        connection.document = [(receipt.generation_id,False,'auth')]
        replay = await stage(indexer)
        assert replay.replayed and replay.provider_calls == 0 and replay.usage == ()
        assert len(transport.calls) == 1
        connection.vector_count_override = [(0,)]
        with pytest.raises(IntegrityViolation): await stage(indexer)
        assert len(transport.calls) == 1
    asyncio.run(run())


def test_unprovisioned_openai_profile_is_rejected_without_provider_or_database():
    from cragkit.embeddings import OPENAI_PROFILE
    connection = Connection(); resource = Resource(connection)
    transport = Transport(connection,resource)
    counter = Counter(); counter.name = OPENAI_PROFILE.tokenizer
    adapter = EmbeddingAdapter(transport,counter,profile=OPENAI_PROFILE)
    with pytest.raises(UnsupportedCapability):
        implementation.PostgresVectorIndexer(resource,authorize_write=allow_write,embedder=adapter)
    assert not connection.calls and not transport.calls and resource.leased == 0


@pytest.mark.parametrize('limits', [EmbeddingLimits(max_batch_bytes=8),EmbeddingLimits(max_batch_tokens=8)])
def test_batching_respects_bytes_and_tokens_independently_of_item_limit(limits):
    async def run():
        connection, _, transport, indexer = fixture(limits=limits)
        result = await stage(indexer,'first\n\nsecond',canonical_options={'target_bytes':6})
        assert result.chunk_count == 2 and len(transport.calls) == 2
        assert all(len(call['input']) == 1 for call in transport.calls)
        assert len(connection.vectors) == 2
    asyncio.run(run())


def test_newer_active_pointer_blocks_running_resume_before_provider():
    async def run():
        connection, resource, transport, indexer = fixture()
        await stage(indexer)
        connection.document = [('newer-generation',False,'auth')]
        connection.vectors.clear()
        with pytest.raises(IndexNotReady): await stage(indexer)
        assert len(transport.calls) == 1 and not connection.vectors
        assert resource.leased == resource.returned
    asyncio.run(run())


def test_running_resume_with_zero_attempt_count_fails_before_provider():
    async def run():
        connection, resource, transport, indexer = fixture()
        await stage(indexer)
        job = connection.vector_job[0]
        connection.vector_job = [(*job[:4],0)]
        connection.vectors.clear()
        with pytest.raises(IndexNotReady): await stage(indexer)
        assert len(transport.calls) == 1 and not connection.vectors
        assert resource.leased == resource.returned
    asyncio.run(run())


def test_newly_unsafe_vector_role_rejects_resume_before_provider_or_writes():
    async def run():
        connection, resource, transport, indexer = fixture()
        await stage(indexer)
        connection.vectors = {}
        before = copy.deepcopy((connection.vector_job, connection.vector_generation,
                                connection.vector_revision, connection.manifest))
        calls = len(transport.calls)
        # The native harness separately proves schema CREATE and ledger UPDATE
        # make this catalog capability false for a real restricted LOGIN.
        connection.capability = [(False,)]
        with pytest.raises(UnsupportedCapability):
            await stage(indexer)
        assert len(transport.calls) == calls
        assert not connection.vectors and not connection.published
        assert (connection.vector_job, connection.vector_generation,
                connection.vector_revision, connection.manifest) == before
        assert resource.leased == resource.returned
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['cancel', 'deadline'])
def test_interruption_after_committed_batch_preserves_old_pointer_and_resumes_missing(mode):
    async def run():
        connection, resource, transport, indexer = fixture(limits=EmbeddingLimits(max_items=1))
        connection.document = [('old-generation', False, 'auth')]
        connection.created_document = False
        source = 'first\n\nsecond'
        options = dict(canonical_options={'target_bytes': 6}, expected_generation_id='old-generation')

        def block_next(response):
            if len(transport.calls) == 1:
                transport.block = True

        transport.change = block_next
        task = asyncio.create_task(stage(
            indexer, source, **options,
            deadline=asyncio.get_running_loop().time() + (.05 if mode == 'deadline' else 2),
        ))
        async with asyncio.timeout(1):
            await transport.entered.wait()
        assert len(connection.vectors) == 1
        if mode == 'cancel':
            task.cancel()
        with pytest.raises(asyncio.CancelledError if mode == 'cancel' else DeadlineExceeded):
            await task
        assert connection.document == [('old-generation', False, 'auth')]
        assert connection.vector_generation[0][1] == 'staging'
        assert resource.leased == resource.returned and not connection.published
        transport.block = False
        transport.change = None
        result = await stage(indexer, source, **options)
        assert result.provider_calls == 1 and len(connection.vectors) == 2
        assert connection.document == [('old-generation', False, 'auth')]
    asyncio.run(run())
