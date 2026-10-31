"""PGO-r1 mechanical profile admission; no native DB or real-model inference."""
import asyncio
import time

import pytest

from cragkit import _postgres_profiles as profiles
from cragkit.embeddings import EmbeddingAdapter, EmbeddingPolicy, FAKE_PROFILE, OPENAI_PROFILE
from cragkit.errors import EmbeddingProfileMismatch, UnsupportedCapability
from cragkit.vector_ingestion import PostgresVectorIndexer, _VECTOR_CAPABILITY_SQL
from test_ingestion import allow_write
from test_vector_ingestion import Connection, Resource, scope, fixture, stage


class OpenAICounter:
    name = 'cl100k_base'
    def count(self, value):
        return len(value.encode())


def openai_adapter(calls):
    async def transport(*args, **kwargs):
        calls.append(True)
        raise AssertionError('no real-model dispatch permitted')
    return EmbeddingAdapter(transport, OpenAICounter(), profile=OPENAI_PROFILE,
        policy=EmbeddingPolicy(allow_live=True, max_cost_usd=.01, usd_per_million_tokens=.02))


def test_closed_profiles_and_exact_storage_admission():
    async def run():
        for profile in (FAKE_PROFILE, OPENAI_PROFILE):
            assert profiles.snapshot_profile(profile) == profile
        for history, profile, accepted in (
            (profiles.LEGACY_VECTOR_HISTORY, FAKE_PROFILE, True),
            (profiles.LEGACY_VECTOR_HISTORY, OPENAI_PROFILE, False),
            (profiles.OPENAI_VECTOR_HISTORY, FAKE_PROFILE, True),
            (profiles.OPENAI_VECTOR_HISTORY, OPENAI_PROFILE, True),
            ((*profiles.OPENAI_VECTOR_HISTORY, ('unknown','hash')), FAKE_PROFILE, False)):
            async def query(sql):
                if sql == profiles.SETUP_HISTORY_SQL:
                    return list(history)
                if sql == profiles.PROFILE_SQL:
                    return profiles.profile_rows(history == profiles.OPENAI_VECTOR_HISTORY)
                return [(True,)]
            if accepted:
                await profiles.validate_profile_storage(query, profile, _VECTOR_CAPABILITY_SQL)
            else:
                with pytest.raises(UnsupportedCapability):
                    await profiles.validate_profile_storage(query, profile, _VECTOR_CAPABILITY_SQL)
    asyncio.run(run())


@pytest.mark.parametrize('drift', ['registry_missing','registry_extra','history_hash','table'])
def test_upgraded_drift_fails_closed(drift):
    async def run():
        async def query(sql):
            if sql == profiles.SETUP_HISTORY_SQL:
                rows = list(profiles.OPENAI_VECTOR_HISTORY)
                if drift == 'history_hash':
                    rows[-1] = (rows[-1][0], 'wrong')
                return rows
            if sql == profiles.PROFILE_SQL:
                rows = profiles.profile_rows(True)
                if drift == 'registry_missing':
                    return rows[:1]
                if drift == 'registry_extra':
                    rows.append(rows[-1])
                return rows
            return [(False,)] if drift == 'table' and sql == profiles.OPENAI_TABLE_SQL else [(True,)]
        with pytest.raises(UnsupportedCapability):
            await profiles.validate_profile_storage(query, OPENAI_PROFILE, _VECTOR_CAPABILITY_SQL)
    asyncio.run(run())


def test_default_mismatch_refuses_before_resource_io():
    calls = []
    adapter = openai_adapter(calls)
    with pytest.raises(UnsupportedCapability):
        PostgresVectorIndexer(object(), authorize_write=allow_write, embedder=adapter)
    assert calls == []


def test_explicit_openai_legacy_storage_refuses_before_disclosure():
    async def run():
        calls = []
        connection = Connection()
        resource = Resource(connection)
        indexer = PostgresVectorIndexer(resource, authorize_write=allow_write,
            embedder=openai_adapter(calls), embedding_profile=OPENAI_PROFILE)
        with pytest.raises(UnsupportedCapability):
            await stage(indexer)
        assert calls == [] and not connection.vectors
        assert resource.leased == resource.returned
    asyncio.run(run())


def test_selected_profile_changes_generation_without_changing_source_revision():
    async def run():
        _, resource, _, fake = fixture()
        real = PostgresVectorIndexer(resource, authorize_write=allow_write,
            embedder=openai_adapter([]), embedding_profile=OPENAI_PROFILE)
        kwargs = dict(collection='collection', document_id='document', intent_id='intent',
            source_locator='synthetic:source', scope=scope(), deadline=time.monotonic()+10,
            expected_generation_id=None, metadata=None, format='text/plain', canonical_options=None)
        a = await fake._prepare('tiny source', **kwargs)
        b = await real._prepare('tiny source', **kwargs)
        assert a.receipt.revision_id == b.receipt.revision_id
        assert a.receipt.payload_sha256 != b.receipt.payload_sha256
        assert a.receipt.generation_id != b.receipt.generation_id
        assert b.receipt.embedding_profile == OPENAI_PROFILE.profile_id
    asyncio.run(run())


def test_openai_batch_profile_and_synthetic_flags_are_independent_checks():
    from cragkit.embeddings import EmbeddingBatch, EmbeddingUsage
    from cragkit.errors import IntegrityViolation
    indexer = PostgresVectorIndexer(object(), authorize_write=allow_write,
        embedder=openai_adapter([]), embedding_profile=OPENAI_PROFILE)
    # In-memory unit fixture only: never published as genuine OpenAI inference.
    batch = EmbeddingBatch(profile=OPENAI_PROFILE, vectors=((1.,) + (0.,)*1535,),
        usage=EmbeddingUsage(prompt_tokens=None, total_tokens=None, cost_usd=None, cost_kind='unknown'),
        synthetic=False)
    indexer._validate_batch(batch, 1)
    with pytest.raises(IntegrityViolation):
        indexer._validate_batch(batch.model_copy(update={'synthetic': True}), 1)
    with pytest.raises(EmbeddingProfileMismatch):
        indexer._validate_batch(batch.model_copy(update={'profile': FAKE_PROFILE}), 1)
    with pytest.raises(IntegrityViolation):
        indexer._validate_batch(batch.model_copy(update={'provider_calls': True}), 1)


@pytest.mark.parametrize('write,permissions', [(False, set()), (True, {'SELECT'}), (True, {'SELECT','INSERT'}), (True, {'SELECT','UPDATE'})])
def test_upgraded_selected_privileges_fail_before_model(write, permissions):
    async def run():
        async def query(sql):
            if sql == profiles.SETUP_HISTORY_SQL:
                return list(profiles.OPENAI_VECTOR_HISTORY)
            if sql == profiles.PROFILE_SQL:
                return profiles.profile_rows(True)
            if sql.startswith('SELECT has_table_privilege'):
                assert 'chunk_vectors_openai_te3small_1536' in sql
                required = {'SELECT','INSERT','UPDATE'} if write else {'SELECT'}
                assert ("'INSERT'" in sql and "'UPDATE'" in sql) == write
                return [(required <= permissions,)]
            return [(True,)]
        with pytest.raises(UnsupportedCapability):
            await profiles.validate_profile_storage(query, OPENAI_PROFILE, _VECTOR_CAPABILITY_SQL, write=write)
    asyncio.run(run())


def test_upgraded_fake_requires_no_unselected_openai_privileges_and_legacy_is_unchanged():
    async def run():
        for upgraded in (False, True):
            privilege_queries = []
            async def query(sql):
                if sql == profiles.SETUP_HISTORY_SQL:
                    return list(profiles.OPENAI_VECTOR_HISTORY if upgraded else profiles.LEGACY_VECTOR_HISTORY)
                if sql == profiles.PROFILE_SQL:
                    return profiles.profile_rows(upgraded)
                if sql.startswith('SELECT has_table_privilege'):
                    privilege_queries.append(sql)
                    assert 'chunk_vectors_fake_1536' in sql
                    assert 'chunk_vectors_openai_te3small_1536' not in sql
                    assert "'INSERT'" in sql and "'UPDATE'" in sql and "'INSERT,UPDATE'" not in sql
                return [(True,)]
            await profiles.validate_profile_storage(query, FAKE_PROFILE, _VECTOR_CAPABILITY_SQL, write=True)
            assert len(privilege_queries) == int(upgraded)
    asyncio.run(run())
