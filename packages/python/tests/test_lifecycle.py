import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import traceback

import pytest
from pydantic import ValidationError

import cragkit.lifecycle as implementation
from cragkit.ingestion import _DOCUMENT_LOCK_SQL, _LOCK_SQL, _WRITER_ROLE_SQL
from cragkit._postgres_session import _CATALOG_SQL, _HISTORY_SQL, _SCOPE_SQL, EXPECTED_HISTORY
from cragkit.contracts import parse_scope
from cragkit.errors import (DeadlineExceeded, IndexNotReady, IntegrityViolation, InvalidRequest,
                            ProviderUnavailable, UnauthorizedScope, UnsupportedCapability)
from cragkit.lifecycle import PostgresLifecycle


CREATED = '2026-10-22 00:00:00.123456+00'


def initial():
    return {'active': 'generation', 'tombstoned': False, 'auth': 'auth',
            'metadata': {'private': 'kept before purge'}, 'created': CREATED,
            'children': {'revisions': 2, 'generations': 2, 'chunks': 3, 'lexical': 3, 'grants': 1, 'jobs': 2}}


class Cursor:
    def __init__(self, rows): self.rows = rows
    async def fetchall(self): return self.rows


class Connection:
    def __init__(self):
        self.doc = initial(); self.info = SimpleNamespace(transaction_status=0)
        self.calls = []; self.commits = self.rollbacks = self.closed = 0
        self.scope = None; self.role = self.catalog = self.purge_catalog = True
        self.failure_sql = None; self.failure = None; self.block_sql = None
        self.entered = asyncio.Event(); self.rollback_bad = False; self.commit_error = None
        self.tombstone_rows = [(1,)]; self.delete_rows = None; self.insert_rows = [(1,)]
    def transaction(self, *, force_rollback=False):
        assert not force_rollback
        connection = self
        class Transaction:
            async def __aenter__(self):
                self.before = deepcopy(connection.doc); connection.info.transaction_status = 2
            async def __aexit__(self, kind, error, tb):
                connection.scope = None
                if error is None:
                    if connection.commit_error: raise connection.commit_error
                    connection.commits += 1
                else:
                    connection.doc = self.before; connection.rollbacks += 1
                connection.info.transaction_status = 2 if connection.rollback_bad else 0
        return Transaction()
    async def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if sql == self.failure_sql: raise self.failure
        if sql == self.block_sql:
            self.entered.set(); await asyncio.Event().wait()
        if sql in (_WRITER_ROLE_SQL, implementation._PURGER_ROLE_SQL): return Cursor([(self.role,)])
        if sql == _CATALOG_SQL: return Cursor([(self.catalog,)])
        if sql == implementation._PURGE_CATALOG_SQL: return Cursor([(self.purge_catalog,)])
        if sql == _HISTORY_SQL: return Cursor(list(EXPECTED_HISTORY))
        if sql == _SCOPE_SQL: self.scope = params; return Cursor([])
        if sql == _DOCUMENT_LOCK_SQL:
            return Cursor([] if self.doc is None else [(self.doc['active'], self.doc['tombstoned'], self.doc['auth'])])
        if sql == implementation._TOMBSTONE_SQL:
            self.doc['tombstoned'] = True
            return Cursor(self.tombstone_rows)
        if sql == implementation._PURGE_DELETE_SQL:
            created = self.doc['created']; self.doc = None
            return Cursor(self.delete_rows if self.delete_rows is not None else [(created,)])
        if sql == implementation._PURGE_INSERT_SQL:
            self.doc = {'active': None, 'tombstoned': True, 'auth': params[3], 'metadata': {},
                        'created': params[4], 'children': {key: 0 for key in initial()['children']}}
            return Cursor(self.insert_rows)
        return Cursor([])
    async def close(self): self.closed += 1


class Resource:
    def __init__(self):
        self.connection = Connection(); self.config = SimpleNamespace(release_timeout=0.03)
        self.leased = self.returned = 0
    @asynccontextmanager
    async def lease(self, *, deadline):
        self.leased += 1
        try: yield self.connection
        finally: self.returned += 1


def scope(**changes):
    return parse_scope({'tenant_id': 'tenant', 'principal_id': 'principal',
                        'authorization_revision': 'auth', 'grant_ids': ['group'], **changes})


async def allow(*args): return True


def args(**changes):
    return {'collection': 'docs', 'document_id': 'document', 'expected_generation_id': 'generation',
            'scope': scope(), 'deadline': asyncio.get_running_loop().time() + 1, **changes}


def test_tombstone_preserves_content_pointer_and_metadata_then_repeats_without_mutation():
    async def scenario():
        resource = Resource(); lifecycle = PostgresLifecycle(resource, authorize_lifecycle=allow)
        before = deepcopy(resource.connection.doc)
        receipt = await lifecycle.tombstone(**args())
        assert receipt.model_dump(mode='json') == {'tenant_id': 'tenant', 'collection': 'docs',
            'document_id': 'document', 'state': 'tombstoned', 'active_generation_id': 'generation', 'changed': True}
        assert resource.connection.doc == {**before, 'tombstoned': True}
        with pytest.raises(ValidationError): receipt.changed = False
        again = await lifecycle.tombstone(**args())
        assert again.changed is False
        assert sum(sql == implementation._TOMBSTONE_SQL for sql, _ in resource.connection.calls) == 1
        assert resource.connection.commits == resource.returned == 2
        assert resource.connection.scope is None
    asyncio.run(scenario())


def test_purge_replaces_parent_preserves_exact_creation_time_and_prevents_resurrection():
    async def scenario():
        resource = Resource(); resource.connection.doc['tombstoned'] = True
        lifecycle = PostgresLifecycle(resource, authorize_lifecycle=allow)
        receipt = await lifecycle.purge_tombstoned(**args())
        assert receipt.state == 'purged' and receipt.changed and receipt.active_generation_id is None
        assert resource.connection.doc == {'active': None, 'tombstoned': True, 'auth': 'auth',
            'metadata': {}, 'created': CREATED, 'children': {key: 0 for key in initial()['children']}}
        with pytest.raises(IndexNotReady): await lifecycle.purge_tombstoned(**args())
        again = await lifecycle.purge_tombstoned(**args(expected_generation_id=None))
        assert again.changed is True and again.active_generation_id is None
        assert (await lifecycle.tombstone(**args(expected_generation_id=None))).changed is False
        assert 'created_at::text' in implementation._PURGE_DELETE_SQL
        assert '%s::timestamptz' in implementation._PURGE_INSERT_SQL
    asyncio.run(scenario())


@pytest.mark.parametrize('result', [False, None, 0, 1, 'true'])
def test_denied_callback_never_acquires_connection(result):
    async def scenario():
        resource = Resource()
        async def denied(*_): return result
        lifecycle = PostgresLifecycle(resource, authorize_lifecycle=denied)
        with pytest.raises(UnauthorizedScope): await lifecycle.tombstone(**args())
        assert resource.leased == 0
    asyncio.run(scenario())


def test_callback_sees_frozen_snapshot_and_explicit_operation():
    async def scenario():
        resource = Resource(); entered = asyncio.Event(); resume = asyncio.Event(); seen = []
        original = scope()
        async def authorize(bound, collection, document, operation):
            seen.append((bound, collection, document, operation)); entered.set(); await resume.wait(); return True
        lifecycle = PostgresLifecycle(resource, authorize_lifecycle=authorize)
        task = asyncio.create_task(lifecycle.tombstone(**args(scope=original)))
        await entered.wait(); object.__setattr__(original, 'tenant_id', 'mutated'); resume.set()
        receipt = await task
        assert receipt.tenant_id == seen[0][0].tenant_id == 'tenant'
        assert seen[0][1:] == ('docs', 'document', 'tombstone')
        assert next(params for sql, params in resource.connection.calls if sql == _LOCK_SQL) == ('["cragkit.document.v1","tenant","docs","document"]',)
    asyncio.run(scenario())


@pytest.mark.parametrize('changes', [{'collection': 'x' * 129}, {'document_id': '\0'},
    {'expected_generation_id': ''}, {'scope': {'tenant_id': 'foreign'}}, {'deadline': float('inf')}])
def test_malformed_boundary_fails_before_callback_or_lease(changes):
    async def scenario():
        resource = Resource(); called = []
        async def authorize(*_): called.append(True); return True
        lifecycle = PostgresLifecycle(resource, authorize_lifecycle=authorize)
        with pytest.raises(InvalidRequest): await lifecycle.tombstone(**args(**changes))
        assert not called and resource.leased == 0
    asyncio.run(scenario())


@pytest.mark.parametrize('change,error', [({'active': 'newer'}, IndexNotReady),
    ({'auth': 'new-auth'}, UnauthorizedScope), ({'tombstoned': 'yes'}, IntegrityViolation),
    ({'active': ''}, IntegrityViolation)])
def test_locked_row_cas_authorization_and_shape_fail_closed(change, error):
    async def scenario():
        resource = Resource(); resource.connection.doc.update(change)
        lifecycle = PostgresLifecycle(resource, authorize_lifecycle=allow)
        with pytest.raises(error): await lifecycle.tombstone(**args())
        assert resource.connection.rollbacks == 1 and resource.connection.commits == 0
    asyncio.run(scenario())


def test_missing_document_and_live_purge_do_not_mutate():
    async def scenario():
        resource = Resource(); lifecycle = PostgresLifecycle(resource, authorize_lifecycle=allow)
        with pytest.raises(InvalidRequest): await lifecycle.purge_tombstoned(**args())
        resource.connection.doc = None
        with pytest.raises(UnauthorizedScope): await lifecycle.tombstone(**args())
    asyncio.run(scenario())


@pytest.mark.parametrize('mutation', ['tombstone', 'delete', 'insert'])
def test_invisible_or_duplicate_mutation_return_rolls_back_parent_and_children(mutation):
    async def scenario():
        resource = Resource(); lifecycle = PostgresLifecycle(resource, authorize_lifecycle=allow)
        if mutation != 'tombstone': resource.connection.doc['tombstoned'] = True
        before = deepcopy(resource.connection.doc)
        if mutation == 'tombstone': resource.connection.tombstone_rows = []
        elif mutation == 'delete': resource.connection.delete_rows = []
        else: resource.connection.insert_rows = [(1,), (1,)]
        with pytest.raises(IntegrityViolation):
            await (lifecycle.tombstone if mutation == 'tombstone' else lifecycle.purge_tombstoned)(**args())
        assert resource.connection.doc == before and resource.connection.rollbacks == 1
    asyncio.run(scenario())


def test_purge_insert_error_restores_deleted_parent_and_sources_with_redacted_error():
    async def scenario():
        resource = Resource(); resource.connection.doc['tombstoned'] = True
        before = deepcopy(resource.connection.doc)
        resource.connection.failure_sql = implementation._PURGE_INSERT_SQL
        resource.connection.failure = RuntimeError('private-deleted-source')
        lifecycle = PostgresLifecycle(resource, authorize_lifecycle=allow)
        with pytest.raises(ProviderUnavailable) as caught: await lifecycle.purge_tombstoned(**args())
        assert 'private-deleted-source' not in ''.join(traceback.format_exception(caught.value))
        assert resource.connection.doc == before and resource.connection.rollbacks == 1
    asyncio.run(scenario())


def test_callback_deadline_and_cancelled_mutation_release_without_publication():
    async def scenario():
        resource = Resource()
        async def wait(*_): await asyncio.Event().wait()
        lifecycle = PostgresLifecycle(resource, authorize_lifecycle=wait)
        with pytest.raises(DeadlineExceeded):
            await lifecycle.tombstone(**args(deadline=asyncio.get_running_loop().time() + 0.01))
        assert resource.leased == 0
        lifecycle = PostgresLifecycle(resource, authorize_lifecycle=allow)
        before = deepcopy(resource.connection.doc); resource.connection.block_sql = implementation._TOMBSTONE_SQL
        task = asyncio.create_task(lifecycle.tombstone(**args()))
        await resource.connection.entered.wait(); task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert resource.connection.doc == before and resource.connection.rollbacks == resource.returned == 1
    asyncio.run(scenario())


def test_unsafe_role_and_invalid_schema_are_not_treated_as_missing_document():
    async def scenario():
        for attribute, error in [('role', UnauthorizedScope), ('catalog', UnsupportedCapability)]:
            resource = Resource(); setattr(resource.connection, attribute, False)
            with pytest.raises(error):
                await PostgresLifecycle(resource, authorize_lifecycle=allow).tombstone(**args())
    asyncio.run(scenario())


def test_purger_guard_does_not_weaken_ingestion_guard():
    assert "OR has_table_privilege(current_user,c.oid,'DELETE')" in _WRITER_ROLE_SQL
    assert "c.relname<>'documents'" in implementation._PURGER_ROLE_SQL
    assert "has_table_privilege(current_user,c.oid,'TRUNCATE')" in implementation._PURGER_ROLE_SQL


def test_shared_lifecycle_cases():
    packet = json.loads((Path(__file__).resolve().parents[3] / 'contracts/fixtures/lifecycle.json').read_text())
    async def scenario(case):
        resource = Resource()
        row = case['row']
        if row is None: resource.connection.doc = None
        else: resource.connection.doc.update(active=row[0], tombstoned=row[1], auth=row[2])
        lifecycle = PostgresLifecycle(resource, authorize_lifecycle=allow)
        operation = lifecycle.tombstone if case['operation'] == 'tombstone' else lifecycle.purge_tombstoned
        options = args(collection='collection', expected_generation_id=case['expected_generation_id'])
        if 'error' in case:
            with pytest.raises(Exception) as caught: await operation(**options)
            assert caught.value.code == case['error'], case['name']
        else:
            assert (await operation(**options)).model_dump(mode='json') == case['expected'], case['name']
    for case in packet['cases']: asyncio.run(scenario(case))


def test_missing_purge_cascade_guard_rolls_back_without_deleting():
    async def scenario():
        resource = Resource(); resource.connection.doc['tombstoned'] = True
        before = deepcopy(resource.connection.doc)
        resource.connection.purge_catalog = False
        with pytest.raises(UnsupportedCapability):
            await PostgresLifecycle(resource, authorize_lifecycle=allow).purge_tombstoned(**args())
        assert resource.connection.doc == before
        assert not any(sql == implementation._PURGE_DELETE_SQL for sql, _ in resource.connection.calls)
    asyncio.run(scenario())


def test_lifecycle_import_needs_no_driver_network_process_or_file_writes():
    import subprocess
    import sys

    script = """
import sys
class DenyDrivers:
    def find_spec(self, name, *args):
        if name in ('psycopg', 'psycopg_pool'):
            raise AssertionError('optional driver imported')
sys.meta_path.insert(0, DenyDrivers())
def audit(event, args):
    if event.startswith(('socket.', 'subprocess.')):
        raise AssertionError('network or process')
    if event == 'open' and isinstance(args[1], str) and any(flag in args[1] for flag in 'wax+'):
        raise AssertionError('file write')
sys.addaudithook(audit)
import cragkit.lifecycle
"""
    process = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, text=True, timeout=5)
    assert process.returncode == 0, process.stderr
    assert process.stdout == ''


def test_optional_vector_purge_catalog_keeps_exact_scoped_cascade_guards():
    # Structural regression only; the native lifecycle fixture checks actual
    # optional vector cascades and an unexpected incoming foreign key.
    query = ' '.join(implementation._PURGE_CATALOG_SQL.split())
    assert 'SELECT * FROM base_expected UNION ALL' in query
    assert 'WHERE EXISTS (SELECT 1 FROM known_vector_storage)' in query
    assert "('chunk_vectors_fake_1536','chunks',ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id']" in query
    assert "('chunk_vectors_fake_1536','index_generations',ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','embedding_profile']" in query
    assert '(SELECT count(*) FROM actual)=(SELECT count(*) FROM expected)' in query
    assert "a.child_schema='cragkit'" in query
    assert 'a.child_columns=e.child_columns AND a.parent_columns=e.parent_columns' in query
    assert 'a.delete_action=e.delete_action AND a.convalidated' in query
    assert "WHERE relkind<>'r' OR NOT relrowsecurity" in query
    assert "'chunks','chunk_vectors_fake_1536','document_grants','ingestion_jobs','chunk_lexical')" in query
    assert "t.tgenabled NOT IN ('O','A')" in query
