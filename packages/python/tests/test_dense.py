import asyncio
from hashlib import sha256
import json
from pathlib import Path

import pytest

import cragkit._postgres_session as implementation
from cragkit._postgres_session import DenseCandidate, PostgresSession
from cragkit.embeddings import EmbeddingBatch, EmbeddingUsage, FAKE_PROFILE, OPENAI_PROFILE
from cragkit.errors import DeadlineExceeded, EmbeddingProfileMismatch, IntegrityViolation, InvalidRequest, UnsupportedCapability
from cragkit.vector_ingestion import EXPECTED_VECTOR_HISTORY, _PROFILE_SQL, _SETUP_HISTORY_SQL, _VECTOR_CAPABILITY_SQL
from test_postgres_session import Connection, Cursor, Resource, request, scope


DIGEST = sha256(b'text').hexdigest()
ROW = ('tenant-a', 'engineering', 'document', 'revision', 'generation', 'chunk', 0, 4, DIGEST, 0.0, FAKE_PROFILE.profile_id, 'native_fts.v1')


def batch(**changes):
    values = dict(profile=FAKE_PROFILE, vectors=((1.0,) + (0.0,) * 1535,),
                  usage=EmbeddingUsage(prompt_tokens=1, total_tokens=1, cost_usd=0.0, cost_kind='known'), synthetic=True)
    values.update(changes)
    return EmbeddingBatch(**values)


class DenseConnection(Connection):
    def __init__(self):
        super().__init__()
        self.dense = [ROW]
        self.capability = [(True,)]
        self.setup = list(EXPECTED_VECTOR_HISTORY)
        p = FAKE_PROFILE
        self.profiles = [(p.profile_id, p.provider, p.model, p.dimensions, p.tokenizer, p.normalization, 'chunk_vectors_fake_1536')]
        self.source = [(*ROW[:6], DIGEST, 4, 'text', 0, 4, 4, 'text', DIGEST, 'fixture', 'native_fts.v1', True)]

    async def execute(self, query, params=None):
        if query in (_VECTOR_CAPABILITY_SQL, _SETUP_HISTORY_SQL, _PROFILE_SQL):
            self.calls.append((query, params))
            return Cursor({_VECTOR_CAPABILITY_SQL: self.capability, _SETUP_HISTORY_SQL: self.setup, _PROFILE_SQL: self.profiles}[query])
        if query.startswith(implementation._DENSE_SQL.split('{predicate}')[0]):
            self.calls.append((query, params))
            self.block_started.set()
            if self.block is not None:
                await self.block.wait()
            return Cursor(self.dense)
        if query.startswith(implementation._SOURCE_SQL.split('{predicate}')[0]):
            self.calls.append((query, params))
            return Cursor(self.source)
        return await super().execute(query, params)


def test_canonical_sql_and_scoped_parameters_and_source_projection():
    assert implementation._DENSE_SQL.strip() == (Path(__file__).resolve().parents[3] / 'storage/postgres/queries/dense_candidates.sql').read_text().strip()
    async def scenario():
        connection = DenseConnection()
        async with PostgresSession(Resource(connection)).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time() + 2) as handle:
            candidates = await handle.dense_candidates(batch(), limit=1)
            candidate, = candidates
            assert candidate.score == 0 and candidate.score_direction == 'lower_is_better'
            assert candidate.score_kind == 'cosine_distance'
            sql, params = next(call for call in connection.calls if call[0].startswith(implementation._DENSE_SQL.split('{predicate}')[0]))
            assert json.loads(params[0]) == list(batch().vectors[0])
            assert params[1:] == (FAKE_PROFILE.profile_id, 'tenant-a', 'engineering', 'auth-r1', 'auth-r1', 'principal-a', ['read'], 1)
            fetched = await handle.fetch_evidence(candidate, max_source_bytes=100)
            assert fetched.state == 'verified'
            connection.source = []
            assert (await handle.fetch_evidence(candidate, max_source_bytes=100)).state == 'unavailable'
    asyncio.run(scenario())


@pytest.mark.parametrize('changes,error', [
    ({'vectors': ()}, InvalidRequest), ({'vectors': ((1.0,) * 1536,) * 2}, InvalidRequest),
    ({'vectors': ((1.0,),)}, EmbeddingProfileMismatch),
    ({'vectors': ((float('nan'),) + (0.0,) * 1535,)}, InvalidRequest),
    ({'vectors': ((0.0,) * 1536,)}, InvalidRequest),
    ({'vectors': ((2.0,) + (0.0,) * 1535,)}, InvalidRequest),
    ({'synthetic': False}, InvalidRequest),
    ({'profile': OPENAI_PROFILE, 'synthetic': False}, EmbeddingProfileMismatch),
])
def test_invalid_query_rejected_before_dense_io(changes, error):
    async def scenario():
        c = DenseConnection()
        async with PostgresSession(Resource(c)).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time()+2) as h:
            before = len(c.calls)
            with pytest.raises(error):
                await h.dense_candidates(batch(**changes))
            assert len(c.calls) == before
    asyncio.run(scenario())


@pytest.mark.parametrize('field,value,error', [
    ('capability', [(False,)], UnsupportedCapability), ('setup', [], UnsupportedCapability),
    ('profiles', [], UnsupportedCapability), ('dense', [ROW, ROW], IntegrityViolation),
    ('dense', [ROW[:-1]], IntegrityViolation),
    ('dense', [(*ROW[:9], -1.0, *ROW[10:])], IntegrityViolation),
    ('dense', [(*ROW[:9], 2.1, *ROW[10:])], IntegrityViolation),
    ('dense', [('other', *ROW[1:])], IntegrityViolation),
    ('dense', [(*ROW[:10], 'wrong', ROW[-1])], UnsupportedCapability),
])
def test_capability_and_rows_fail_closed(field, value, error):
    async def scenario():
        c = DenseConnection(); setattr(c, field, value)
        async with PostgresSession(Resource(c)).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time()+2) as h:
            with pytest.raises(error):
                await h.dense_candidates(batch(), limit=1)
    asyncio.run(scenario())


@pytest.mark.parametrize('metadata', [{'score': 3.0}, {'embedding_profile': 'forged'}, {'score_kind': 'confidence'}, {'score_direction': 'higher_is_better'}])
def test_constructed_dense_metadata_cannot_bypass_source_validation(metadata):
    async def scenario():
        c = DenseConnection()
        async with PostgresSession(Resource(c)).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time()+2) as h:
            candidate, = await h.dense_candidates(batch())
            forged = DenseCandidate.model_construct(**(candidate.model_dump() | metadata))
            before = len(c.calls)
            with pytest.raises(InvalidRequest):
                await h.fetch_evidence(forged, max_source_bytes=100)
            assert len(c.calls) == before
    asyncio.run(scenario())


def test_subtypes_unknown_fields_and_forged_batches_rejected():
    class Extended(DenseCandidate):
        unknown: str = 'unexpected'
    class ExtendedBatch(EmbeddingBatch):
        unknown: str = 'unexpected'
    async def scenario():
        c = DenseConnection()
        async with PostgresSession(Resource(c)).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time()+2) as h:
            candidate, = await h.dense_candidates(batch())
            before = len(c.calls)
            for forged in (Extended(**candidate.model_dump()),):
                with pytest.raises(InvalidRequest):
                    await h.fetch_evidence(forged, max_source_bytes=100)
            for forged in (ExtendedBatch(**batch().model_dump()), EmbeddingBatch.model_construct(**(batch().model_dump() | {'vectors': ((True,) * 1536,)}))):
                with pytest.raises(InvalidRequest):
                    await h.dense_candidates(forged)
            assert len(c.calls) == before
    asyncio.run(scenario())


def test_task_expiration_and_deadline_guards():
    async def scenario():
        c = DenseConnection()
        async with PostgresSession(Resource(c)).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time()+2) as h:
            with pytest.raises(InvalidRequest):
                await asyncio.create_task(h.dense_candidates(batch()))
            old = h._deadline; h._deadline = 0
            with pytest.raises(DeadlineExceeded):
                await h.dense_candidates(batch())
            h._deadline = old
        with pytest.raises(InvalidRequest):
            await h.dense_candidates(batch())
    asyncio.run(scenario())


def test_cancellation_rolls_back_and_connection_can_be_reused():
    async def scenario():
        c = DenseConnection(); resource = Resource(c); c.block = asyncio.Event()
        async def operation():
            async with PostgresSession(resource).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time()+2) as h:
                await h.dense_candidates(batch())
        task = asyncio.create_task(operation())
        await c.block_started.wait(); task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert c.rolled_back == resource.returned == 1
        c.block = None
        async with PostgresSession(resource).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time()+2) as h:
            assert len(await h.dense_candidates(batch())) == 1
        assert c.rolled_back == resource.returned == 2
    asyncio.run(scenario())


@pytest.mark.parametrize('limit', [True, 0, 1001, 1.5])
def test_bad_limits_do_not_dispatch(limit):
    async def scenario():
        c = DenseConnection()
        async with PostgresSession(Resource(c)).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time()+2) as h:
            before = len(c.calls)
            with pytest.raises(InvalidRequest):
                await h.dense_candidates(batch(), limit=limit)
            assert len(c.calls) == before
    asyncio.run(scenario())


def test_duplicate_identity_fails_below_requested_limit():
    async def scenario():
        c = DenseConnection(); c.dense = [ROW, ROW]
        async with PostgresSession(Resource(c)).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time()+2) as h:
            with pytest.raises(IntegrityViolation):
                await h.dense_candidates(batch(), limit=2)
    asyncio.run(scenario())


def test_batch_snapshot_survives_caller_mutation_during_capability_io():
    async def scenario():
        original = batch()
        class MutatingConnection(DenseConnection):
            async def execute(self, query, params=None):
                if query == _VECTOR_CAPABILITY_SQL:
                    object.__setattr__(original, 'vectors', ((-1.0,) + (0.0,) * 1535,))
                return await super().execute(query, params)
        c = MutatingConnection()
        async with PostgresSession(Resource(c)).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time()+2) as h:
            await h.dense_candidates(original)
        params = next(params for sql, params in c.calls if sql.startswith(implementation._DENSE_SQL.split('{predicate}')[0]))
        assert json.loads(params[0])[0] == 1.0
    asyncio.run(scenario())


def test_filters_precede_effective_limit_and_lexical_still_works():
    async def scenario():
        c = DenseConnection()
        filters = [{'field': 'document_id', 'op': 'eq', 'value': 'document'}]
        async with PostgresSession(Resource(c)).transaction(request(filters), scope=scope(), deadline=asyncio.get_running_loop().time()+2) as h:
            await h.dense_candidates(batch(), limit=1000)
            await h.lexical_candidates(limit=1)
            _, params = next(call for call in c.calls if call[0].startswith(implementation._DENSE_SQL.split('{predicate}')[0]))
            assert params[-2] == 'document'
            assert params[-1] == min(1000, request().limits.max_candidates)
            assert any(sql.startswith(implementation._LEXICAL_SQL.split('{predicate}')[0]) for sql, _ in c.calls)
    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['boolean_calls', 'nan_cost', 'infinite_cost', 'unsafe_prompt_tokens', 'unsafe_total_tokens'])
def test_malformed_batch_usage_and_call_count_fail_before_dense_io(kind):
    async def scenario():
        valid = batch()
        if kind == 'boolean_calls':
            supplied = EmbeddingBatch.model_construct(**{**valid.model_dump(), 'provider_calls': True})
        elif kind.startswith('unsafe_'):
            usage = valid.usage.model_copy(update={kind.removeprefix('unsafe_'): 9_007_199_254_740_992})
            supplied = valid.model_copy(update={'usage': usage})
        else:
            usage = valid.usage.model_copy(update={'cost_usd': float('nan') if kind == 'nan_cost' else float('inf')})
            supplied = valid.model_copy(update={'usage': usage})
        c = DenseConnection()
        async with PostgresSession(Resource(c)).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time()+2) as handle:
            before = len(c.calls)
            with pytest.raises(InvalidRequest):
                await handle.dense_candidates(supplied)
            assert len(c.calls) == before
    asyncio.run(scenario())
