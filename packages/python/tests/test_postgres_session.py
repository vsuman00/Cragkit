import asyncio
from contextlib import asynccontextmanager
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import traceback
import time

import pytest

import cragkit._postgres_session as implementation
from cragkit._postgres_filters import compile_filters
from cragkit._postgres_session import PostgresSession
from cragkit.contracts import parse_request, parse_scope
from cragkit.errors import DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability


class Cursor:
    def __init__(self, rows): self.rows = rows
    async def fetchall(self): return self.rows


class DriverError(Exception):
    def __init__(self, state=None):
        super().__init__('private-query-and-credential')
        self.sqlstate = state


class Connection:
    def __init__(self):
        self.info = SimpleNamespace(transaction_status=0)
        self.calls = []
        self.gucs = {}
        self.started = self.rolled_back = self.closed = 0
        self.role = [(True,)]
        self.catalog = [(True,)]
        self.history = list(implementation.EXPECTED_HISTORY)
        self.collection = [('0.1', 'native_fts.v1')]
        self.documents = [('document', 'revision', 'native_fts.v1')]
        self.block = None
        self.block_started = asyncio.Event()
        self.failure = None
        self.rollback_block = None

    def transaction(self, *, force_rollback=False):
        assert force_rollback is True
        connection = self
        class Transaction:
            async def __aenter__(self):
                self.before = dict(connection.gucs)
                connection.info.transaction_status = 2
                connection.started += 1
            async def __aexit__(self, *args):
                if connection.rollback_block is not None:
                    await connection.rollback_block.wait()
                connection.gucs = self.before
                connection.info.transaction_status = 0
                connection.rolled_back += 1
        return Transaction()

    async def execute(self, query, params=None):
        self.calls.append((query, params))
        if self.failure is not None and query not in (
            'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY', 'SET LOCAL search_path = pg_catalog'
        ) and 'statement_timeout' not in query:
            raise self.failure
        if query == implementation._ROLE_SQL: return Cursor(self.role)
        if query == implementation._CATALOG_SQL: return Cursor(self.catalog)
        if query == implementation._HISTORY_SQL: return Cursor(self.history)
        if query == implementation._COLLECTION_SQL: return Cursor(self.collection)
        if query == implementation._SCOPE_SQL:
            self.gucs = dict(zip(('tenant', 'principal', 'revision', 'grants'), params))
            return Cursor([])
        if 'FROM cragkit.documents d' in query:
            self.block_started.set()
            if self.block is not None:
                await self.block.wait()
            return Cursor(self.documents)
        return Cursor([])

    async def close(self): self.closed += 1


class Resource:
    def __init__(self, connection):
        self.connection = connection
        self.config = SimpleNamespace(release_timeout=0.02)
        self.leased = self.returned = 0
    @asynccontextmanager
    async def lease(self, *, deadline):
        self.leased += 1
        try: yield self.connection
        finally: self.returned += 1


def scope(tenant='tenant-a', principal='principal-a', grants=('read',)):
    return parse_scope({'tenant_id': tenant, 'principal_id': principal,
                        'authorization_revision': 'auth-r1', 'grant_ids': list(grants)})


def request(filters=None, **extra):
    return parse_request({'query': 'private query', 'collection': 'engineering',
                          'required_filters': filters or [], **extra})


def test_validation_is_explicit_and_uses_a_rollback_readonly_transaction():
    async def scenario():
        connection = Connection(); resource = Resource(connection)
        session = PostgresSession(resource)
        assert not connection.calls and resource.leased == 0
        await session.validate(deadline=asyncio.get_running_loop().time() + 1)
        assert connection.started == connection.rolled_back == resource.returned == 1
        assert connection.info.transaction_status == 0
        assert connection.calls[0][0] == 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'
        assert connection.calls[1][0] == 'SET LOCAL search_path = pg_catalog'
    asyncio.run(scenario())


@pytest.mark.parametrize('field,value,error', [
    ('role', [(False,)], UnauthorizedScope), ('catalog', [(False,)], UnsupportedCapability),
    ('history', [], UnsupportedCapability), ('history', [('0001_initial', '0' * 64)], UnsupportedCapability),
    ('history', list(implementation.EXPECTED_HISTORY) + [('unknown', '0' * 64)], UnsupportedCapability),
    ('role', [{'safe': True}], UnsupportedCapability),
])
def test_unsafe_roles_schema_drift_or_invalid_cursor_shape_fail_closed(field, value, error):
    async def scenario():
        connection = Connection(); setattr(connection, field, value)
        resource = Resource(connection)
        with pytest.raises(error):
            await PostgresSession(resource).validate(deadline=asyncio.get_running_loop().time() + 1)
        assert connection.rolled_back == 1 and resource.returned == 1
    asyncio.run(scenario())


def test_existing_borrowed_transaction_is_rejected_without_rollback_or_queries():
    async def scenario():
        connection = Connection(); connection.info.transaction_status = 2
        resource = Resource(connection)
        with pytest.raises(InvalidRequest):
            await PostgresSession(resource).validate(deadline=asyncio.get_running_loop().time() + 1)
        assert not connection.calls and connection.rolled_back == 0
        assert resource.returned == 1 and connection.info.transaction_status == 2
    asyncio.run(scenario())


def test_scope_is_bound_separately_parameterized_and_reset_on_pool_reuse():
    async def scenario():
        connection = Connection(); resource = Resource(connection); session = PostgresSession(resource)
        for trusted in (scope(), scope('tenant-b', 'principal-b', ('other',)), scope()):
            async with session.transaction(request(), scope=trusted, deadline=asyncio.get_running_loop().time() + 1) as handle:
                assert connection.gucs['tenant'] == trusted.tenant_id
                assert connection.gucs['principal'] == trusted.principal_id
                assert json.loads(connection.gucs['grants']) == list(trusted.grant_ids)
                assert await handle.visible_documents() == (('document', 'revision'),)
                sql, params = [entry for entry in connection.calls if 'FROM cragkit.documents d' in entry[0]][-1]
                assert params[:5] == (trusted.tenant_id, 'engineering', 'auth-r1', 'auth-r1', trusted.principal_id)
                assert params[5] == list(trusted.grant_ids)
                assert trusted.principal_id not in sql and trusted.tenant_id not in sql
                assert 'x.principal_id=%s' in sql and 'x.principal_id IS NULL' in sql
            assert connection.gucs == {} and connection.info.transaction_status == 0
        assert connection.rolled_back == 3 and resource.returned == 3
    asyncio.run(scenario())


def test_no_scope_in_request_or_unvalidated_scope_objects_are_accepted():
    async def scenario():
        resource = Resource(Connection()); session = PostgresSession(resource)
        for bad_request, bad_scope in ((request(), {'tenant_id': 'foreign'}), ({'query': 'x'}, scope())):
            with pytest.raises(InvalidRequest):
                async with session.transaction(bad_request, scope=bad_scope, deadline=asyncio.get_running_loop().time() + 1):
                    pytest.fail('Unvalidated boundary entered')
        assert resource.leased == 0
    asyncio.run(scenario())


def test_filters_never_interpolate_values_and_keep_nested_boolean_structure():
    value = "literal' OR TRUE --"
    parsed = request([{'op': 'and', 'filters': [
        {'op': 'eq', 'field': 'document_id', 'value': value},
        {'op': 'not', 'filter': {'op': 'in', 'field': 'revision_id', 'values': ['r1', 'r2']}},
        {'op': 'ne', 'field': 'document_id', 'value': 'excluded'},
    ]}])
    sql, params = compile_filters(parsed.required_filters)
    assert value not in sql and 'excluded' not in sql and 'r1' not in sql
    assert params == (value, ['r1', 'r2'], 'excluded')
    assert ' AND ' in sql and 'NOT ' in sql and 'ANY(%s::text[])' in sql
    assert 'COALESCE' in sql


@pytest.mark.parametrize('filter_value', [
    {'op': 'eq', 'field': 'language', 'value': 'en'},
    {'op': 'eq', 'field': 'kind', 'value': 'memo'},
    {'op': 'eq', 'field': 'tag', 'value': 'private'},
    {'op': 'eq', 'field': 'document_id', 'value': 7},
    {'op': 'in', 'field': 'revision_id', 'values': ['r1', False]},
    {'op': 'gt', 'field': 'document_id', 'value': 1},
])
def test_unsupported_filters_fail_before_any_lease(filter_value):
    async def scenario():
        resource = Resource(Connection())
        with pytest.raises(UnsupportedCapability):
            async with PostgresSession(resource).transaction(request([filter_value]), scope=scope(), deadline=asyncio.get_running_loop().time() + 1):
                pytest.fail('Unsupported filter entered')
        assert resource.leased == 0
    asyncio.run(scenario())


def test_fixed_queries_bind_filters_candidate_cap_and_statement_timeout():
    async def scenario():
        connection = Connection(); session = PostgresSession(Resource(connection))
        parsed = request([{'op': 'eq', 'field': 'revision_id', 'value': 'literal-r'}], limits={'max_candidates': 2})
        async with session.transaction(parsed, scope=scope(), deadline=asyncio.get_running_loop().time() + 1) as handle:
            await handle.visible_documents(limit=9)
        sql, params = [entry for entry in connection.calls if 'FROM cragkit.documents d' in entry[0]][-1]
        assert params[-2:] == ('literal-r', 2) and 'literal-r' not in sql
        timeouts = [int(params[0]) for sql, params in connection.calls if 'statement_timeout' in sql]
        assert timeouts and all(1 <= value <= 1000 for value in timeouts)
        assert all(later <= earlier for earlier, later in zip(timeouts, timeouts[1:]))
    asyncio.run(scenario())


def test_handle_cannot_escape_its_transaction_or_be_shared_across_tasks():
    async def scenario():
        connection = Connection(); session = PostgresSession(Resource(connection))
        async with session.transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time() + 1) as handle:
            async def foreign_task():
                with pytest.raises(InvalidRequest): await handle.visible_documents()
            await asyncio.create_task(foreign_task())
            for invalid in (True, 0, 1001):
                with pytest.raises(InvalidRequest): await handle.visible_documents(limit=invalid)
        with pytest.raises(InvalidRequest): await handle.visible_documents()
    asyncio.run(scenario())


def test_body_exception_identity_and_cancel_are_preserved_and_scope_is_reset():
    async def scenario():
        connection = Connection(); resource = Resource(connection); session = PostgresSession(resource)
        sentinel = RuntimeError('caller body sentinel')
        with pytest.raises(RuntimeError) as caught:
            async with session.transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time() + 1): raise sentinel
        assert caught.value is sentinel and connection.gucs == {}
        connection.block = asyncio.Event()
        async def blocked():
            async with session.transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time() + 1) as handle:
                await handle.visible_documents()
        task = asyncio.create_task(blocked())
        await connection.block_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert connection.gucs == {} and connection.rolled_back == resource.returned == 2
    asyncio.run(scenario())


@pytest.mark.parametrize('state,error', [('57014', DeadlineExceeded), *[(state, IntegrityViolation) for state in ('23502','23503','23505','23514','23P01')], ('42501', UnauthorizedScope),
    ('42P01', UnsupportedCapability), ('42703', UnsupportedCapability), (None, ProviderUnavailable)])
def test_driver_failures_are_typed_redacted_and_rolled_back(state, error):
    async def scenario():
        connection = Connection(); connection.failure = DriverError(state)
        resource = Resource(connection)
        with pytest.raises(error) as caught:
            await PostgresSession(resource).validate(deadline=asyncio.get_running_loop().time() + 1)
        assert 'private-query-and-credential' not in ''.join(traceback.format_exception(caught.value))
        assert caught.value.__cause__ is None
        assert connection.rolled_back == resource.returned == 1
    asyncio.run(scenario())


def test_absolute_and_request_deadlines_bound_statement_and_body():
    async def scenario():
        connection = Connection(); resource = Resource(connection); session = PostgresSession(resource)
        for parsed, deadline in ((request(), asyncio.get_running_loop().time() + 0.02),
                                 (request(limits={'deadline_ms': 20}), asyncio.get_running_loop().time() + 1)):
            connection.block = asyncio.Event(); connection.block_started.clear()
            with pytest.raises(DeadlineExceeded):
                async with session.transaction(parsed, scope=scope(), deadline=deadline) as handle:
                    await handle.visible_documents()
            assert connection.gucs == {} and connection.info.transaction_status == 0
        with pytest.raises(DeadlineExceeded):
            async with session.transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time() + 0.01):
                await asyncio.Event().wait()
        assert resource.returned == 3
    asyncio.run(scenario())


def test_rollback_hang_closes_connection_and_reports_safe_failure():
    async def scenario():
        connection = Connection(); connection.rollback_block = asyncio.Event()
        resource = Resource(connection)
        with pytest.raises(ProviderUnavailable):
            await asyncio.wait_for(PostgresSession(resource).validate(deadline=asyncio.get_running_loop().time() + 1), 0.2)
        assert connection.closed == 1 and resource.returned == 1
    asyncio.run(scenario())


def test_malformed_deadline_is_rejected_before_lease():
    async def scenario():
        resource = Resource(Connection()); session = PostgresSession(resource)
        for value in (True, None, float('nan'), float('inf'), 10**1000):
            with pytest.raises(InvalidRequest): await session.validate(deadline=value)
        with pytest.raises(DeadlineExceeded): await session.validate(deadline=asyncio.get_running_loop().time() - 1)
        assert resource.leased == 0
    asyncio.run(scenario())


def harness_module():
    path = Path(__file__).resolve().parents[3] / 'tools/check_python_postgres.py'
    spec = importlib.util.spec_from_file_location('runtime_harness', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_harness_config_requires_private_regular_file_and_does_not_disclose_values(tmp_path):
    module = harness_module()
    path = tmp_path / 'private.json'
    value = {'host': 'synthetic.invalid', 'sslrootcert': '/private/fake-ca', 'passfile': '/private/fake-password'}
    path.write_text(json.dumps(value)); path.chmod(0o644)
    with pytest.raises(module.RuntimeCheckError, match='permissions'): module.load_config(path)
    path.chmod(0o600)
    loaded = module.load_config(path)
    assert loaded['max_size'] == 1 and loaded['sslrootcert'] == Path('/private/fake-ca')
    link = tmp_path / 'link.json'; link.symlink_to(path)
    with pytest.raises(module.RuntimeCheckError, match='permissions'): module.load_config(link)
    assert module.pgpass_field('synthetic:colon\\slash') == 'synthetic\\:colon\\\\slash'


def test_harness_refuses_before_optional_import_or_config_read_without_authorization(monkeypatch, capsys):
    module = harness_module()
    monkeypatch.setattr('sys.argv', ['check_python_postgres.py', '--config', '/absent/config'])
    def forbidden(*args, **kwargs): pytest.fail('Unauthorized harness read configuration')
    monkeypatch.setattr(module, 'load_config', forbidden)
    assert module.main() == 2
    assert capsys.readouterr().out == 'Runtime checks require explicit test-write authorization.\n'


def test_failed_transaction_entry_closes_uncertain_connection_without_exit():
    async def scenario():
        connection = Connection(); resource = Resource(connection)
        class FailedEntry:
            async def __aenter__(self):
                connection.info.transaction_status = 2
                raise DriverError()
            async def __aexit__(self, *args):
                pytest.fail('Exit called for unentered transaction')
        connection.transaction = lambda **kwargs: FailedEntry()
        with pytest.raises(ProviderUnavailable) as caught:
            await PostgresSession(resource).validate(deadline=asyncio.get_running_loop().time() + 1)
        assert connection.closed == 1 and resource.returned == 1
        assert 'private-query-and-credential' not in ''.join(traceback.format_exception(caught.value))
    asyncio.run(scenario())


def test_forged_model_serialization_is_rejected_before_checkout():
    async def scenario():
        resource = Resource(Connection()); session = PostgresSession(resource)
        forged_request = type(request()).model_construct(query=object(), collection='engineering')
        forged_scope = type(scope()).model_construct(tenant_id=object(), principal_id='p', authorization_revision='r', grant_ids=())
        for value, trusted in ((forged_request, scope()), (request(), forged_scope)):
            with pytest.raises(InvalidRequest):
                async with session.transaction(value, scope=trusted, deadline=asyncio.get_running_loop().time() + 1):
                    pytest.fail('Forged model reached transaction')
        assert resource.leased == 0
    asyncio.run(scenario())


def test_collection_profile_mismatch_rejects_and_resets_scope():
    async def scenario():
        connection = Connection(); connection.collection = [('0.1', 'other-profile')]
        resource = Resource(connection)
        with pytest.raises(UnsupportedCapability):
            async with PostgresSession(resource).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time() + 1):
                pytest.fail('Unsupported profile entered body')
        assert connection.gucs == {} and resource.returned == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('stall', ['driver', 'body'])
def test_late_result_or_body_stall_cannot_escape_absolute_deadline(stall):
    async def scenario():
        connection = Connection(); resource = Resource(connection)
        if stall == 'driver':
            original = connection.execute
            async def late(query, params=None):
                if 'FROM cragkit.documents d' in query:
                    time.sleep(0.035)
                return await original(query, params)
            connection.execute = late
        with pytest.raises(DeadlineExceeded):
            async with PostgresSession(resource).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time() + 0.02) as handle:
                if stall == 'driver': await handle.visible_documents()
                else: time.sleep(0.035)
        assert connection.gucs == {} and resource.returned == 1
    asyncio.run(scenario())


def test_caller_exception_keeps_explicit_cause_after_rollback():
    async def scenario():
        connection = Connection(); resource = Resource(connection)
        cause = ValueError('caller cause')
        sentinel = RuntimeError('caller error')
        sentinel.__cause__ = cause
        with pytest.raises(RuntimeError) as caught:
            async with PostgresSession(resource).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time() + 1): raise sentinel
        assert caught.value is sentinel and caught.value.__cause__ is cause
        assert connection.gucs == {}
    asyncio.run(scenario())


def test_huge_pool_deadline_fails_before_using_borrowed_driver():
    from cragkit._postgres_pool import PoolResource
    async def scenario():
        resource = PoolResource(SimpleNamespace(), pool=object())
        with pytest.raises(InvalidRequest):
            async with resource.lease(deadline=10**1000): pytest.fail('Huge deadline entered')
    asyncio.run(scenario())


def test_active_generation_profile_mismatch_is_not_silently_hidden():
    async def scenario():
        connection = Connection(); connection.documents = [('document', 'revision', 'other-profile')]
        resource = Resource(connection)
        with pytest.raises(UnsupportedCapability):
            async with PostgresSession(resource).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time() + 1) as handle:
                await handle.visible_documents()
        assert connection.gucs == {} and resource.returned == 1
    asyncio.run(scenario())


def test_driver_suppressed_rollback_failure_discards_nonidle_connection():
    async def scenario():
        connection = Connection(); resource = Resource(connection)
        original = connection.transaction
        def transaction(**kwargs):
            context = original(**kwargs)
            async def suppressed_exit(*args):
                connection.info.transaction_status = 3
                return None
            context.__class__.__aexit__ = suppressed_exit
            return context
        connection.transaction = transaction
        with pytest.raises(ProviderUnavailable):
            await PostgresSession(resource).validate(deadline=asyncio.get_running_loop().time() + 1)
        assert connection.closed == 1 and resource.returned == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('changes,scope_changes', [
    ({'query': 'bad\0query'}, {}), ({'collection': 'bad\0collection'}, {}),
    ({}, {'tenant_id': 'bad\0tenant'}), ({}, {'principal_id': 'bad\0principal'}),
    ({}, {'authorization_revision': 'bad\0revision'}), ({}, {'grant_ids': ['bad\0grant']}),
    ({'required_filters': [{'op': 'eq', 'field': 'document_id', 'value': 'bad\0id'}]}, {}),
    ({'required_filters': [{'op': 'in', 'field': 'revision_id', 'values': ['bad\0id']}]}, {}),
    ({'required_filters': [{'op': 'not', 'filter': {'op': 'eq', 'field': 'document_id', 'value': 'bad\0id'}}]}, {}),
])
def test_postgres_nul_boundaries_reject_before_lease_without_changing_wire_contract(changes, scope_changes):
    async def run():
        connection = Connection()
        resource = Resource(connection)
        session = PostgresSession(resource)
        bound_scope = parse_scope({**scope().model_dump(mode='json'), **scope_changes})
        parsed = parse_request({'query': 'synthetic', 'collection': 'engineering', **changes})
        with pytest.raises(InvalidRequest):
            async with session.transaction(parsed, scope=bound_scope, deadline=asyncio.get_running_loop().time() + 1):
                pytest.fail('invalid input leased a connection')
        assert resource.leased == 0 and connection.calls == []
    asyncio.run(run())
