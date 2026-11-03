"""LCR-r1 keyed state and transaction failures; no databases or native services."""
import asyncio
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest
from psycopg.pq import TransactionStatus

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import repair_legacy_lexical_config as repair


@pytest.fixture
def snapshot():
    lexical = {}
    for document, config in (('a', 'simple'), ('b', 'simple'), ('c', 'pg_catalog.simple')):
        key = ('tenant', 'collection', document, 'revision', 'generation', 'chunk')
        lexical[key] = dict(zip(repair.LEXICAL_KEYS, key), language_config=config,
            search_vector="'fixture':1", identifier_tokens=['FIXTURE-1'])
    return ({
        'cragkit.chunk_lexical': lexical,
        'cragkit.documents': {('tenant', 'collection', 'a'): dict(document_id='a',
            active_generation_id='generation', authorization_revision='2', tombstoned=True)},
        'cragkit.document_revisions': {('a', 'revision'): dict(canonical_text='Synthetic source.', canonical_sha256='a'*64)},
        'cragkit.chunks': {('a', 'chunk'): dict(text='Synthetic source.', start_byte=0, end_byte=17)},
        'cragkit.document_grants': {('a', 'grant'): dict(principal_id='allowed', authorization_revision='2')},
        'cragkit.chunk_vectors_fake_1536': {('a', 'chunk'): dict(embedding=[1., 0.])},
        'cragkit.embedding_profiles': {('fake',): dict(dimensions=1536, tokenizer='fake-byte-v1')},
        'cragkit.migration_history': {('0002',): dict(checksum='b'*64, applied_at='2026-01-01T00:00:00+00:00')},
        'cragkit_vector.setup_history': {('0002',): dict(checksum='c'*64, applied_at='2026-01-01T00:00:00+00:00')},
    }, dict(policies=[dict(using='tenant-bound')], acl=['restricted-reader'],
        functions=[dict(body='original', strict=False)], triggers=['original']))


def canonicalized(value):
    result = deepcopy(value)
    for row in result[0]['cragkit.chunk_lexical'].values():
        if row['language_config'] == 'simple': row['language_config'] = 'pg_catalog.simple'
    return result


def test_mixed_aliases_repair_only_config_and_check_never_mutates(snapshot):
    original = deepcopy(snapshot)
    assert repair.verify_delta(snapshot, deepcopy(snapshot), apply=False) == 2
    assert repair.verify_delta(snapshot, canonicalized(snapshot), apply=True) == 2
    assert snapshot == original
    with pytest.raises(repair.RepairError, match='lexical_repair_state_changed'):
        repair.verify_delta(snapshot, canonicalized(snapshot), apply=False)


@pytest.mark.parametrize('change', ['source', 'span', 'active_generation', 'grant', 'authorization',
    'tombstone', 'vector', 'profile', 'lexical_vector', 'identifier', 'history_checksum',
    'history_timestamp', 'setup_history', 'row_removed', 'row_added', 'keys_swapped',
    'canonical_to_alias', 'alias_left', 'policy', 'acl', 'function', 'trigger'])
def test_any_undeclared_state_change_refuses(snapshot, change):
    after = canonicalized(snapshot)
    tables, metadata = after
    first = lambda table: next(iter(tables[table].values()))
    if change == 'source': first('cragkit.document_revisions')['canonical_text'] = 'Changed'
    if change == 'span': first('cragkit.chunks')['end_byte'] = 16
    if change == 'active_generation': first('cragkit.documents')['active_generation_id'] = 'other'
    if change == 'grant': first('cragkit.document_grants')['principal_id'] = 'revoked'
    if change == 'authorization': first('cragkit.documents')['authorization_revision'] = '1'
    if change == 'tombstone': first('cragkit.documents')['tombstoned'] = False
    if change == 'vector': first('cragkit.chunk_vectors_fake_1536')['embedding'] = [0., 1.]
    if change == 'profile': first('cragkit.embedding_profiles')['dimensions'] = 768
    if change == 'lexical_vector': first('cragkit.chunk_lexical')['search_vector'] = "'different':1"
    if change == 'identifier': first('cragkit.chunk_lexical')['identifier_tokens'] = []
    if change == 'history_checksum': first('cragkit.migration_history')['checksum'] = 'd'*64
    if change == 'history_timestamp': first('cragkit.migration_history')['applied_at'] = 'changed'
    if change == 'setup_history': first('cragkit_vector.setup_history')['checksum'] = 'd'*64
    lexical = tables['cragkit.chunk_lexical']
    keys = list(lexical)
    if change == 'row_removed': del lexical[keys[0]]
    if change == 'row_added': lexical[('unexpected',)] = deepcopy(lexical[keys[0]])
    if change == 'keys_swapped': lexical[keys[0]], lexical[keys[1]] = lexical[keys[1]], lexical[keys[0]]
    if change == 'canonical_to_alias': lexical[keys[2]]['language_config'] = 'simple'
    if change == 'alias_left': lexical[keys[0]]['language_config'] = 'simple'
    if change == 'policy': metadata['policies'][0]['using'] = 'true'
    if change == 'acl': metadata['acl'].append('PUBLIC')
    if change == 'function': metadata['functions'][0]['strict'] = True
    if change == 'trigger': metadata['triggers'] = []
    with pytest.raises(repair.RepairError, match='lexical_repair_state_changed'):
        repair.verify_delta(snapshot, after, apply=True)


def test_digest_is_order_independent_but_retains_identity_and_history(snapshot):
    tables, metadata = snapshot
    reordered = ({name: dict(reversed(list(rows.items()))) for name, rows in reversed(list(tables.items()))},
        dict(reversed(list(metadata.items()))))
    assert repair.state_digest(snapshot) == repair.state_digest(reordered)
    modified = deepcopy(snapshot)
    next(iter(modified[0]['cragkit.migration_history'].values()))['applied_at'] = 'new'
    assert repair.state_digest(snapshot) != repair.state_digest(modified)
    assert repair.state_digest(snapshot) != repair.state_digest(canonicalized(snapshot))


class Connection:
    def __init__(self, snapshot=None, *, commit_failure=False):
        self.info = type('Info', (), dict(transaction_status=TransactionStatus.IDLE,
            host='127.0.0.1', port=5432))()
        self.snapshot = deepcopy(snapshot)
        self.events = []
        self.commit_failure = commit_failure

    def transaction(self):
        parent = self
        class Transaction:
            async def __aenter__(self):
                parent.events.append('begin')
                self.original = deepcopy(parent.snapshot)
                parent.info.transaction_status = TransactionStatus.INTRANS
            async def __aexit__(self, kind, value, traceback):
                parent.info.transaction_status = TransactionStatus.IDLE
                if kind is not None:
                    parent.events.append('rollback')
                    parent.snapshot = self.original
                elif parent.commit_failure:
                    parent.events.append('commit_failed')
                    parent.snapshot = self.original
                    raise RuntimeError('synthetic-private-commit-diagnostic')
                else:
                    parent.events.append('commit')
                return False
        return Transaction()

    async def execute(self, statement, parameters=None):
        self.events.append('update')
        count = sum(row['language_config'] == 'simple'
            for row in self.snapshot[0]['cragkit.chunk_lexical'].values())
        self.snapshot = canonicalized(self.snapshot)
        return type('Cursor', (), dict(rowcount=count))()


@pytest.fixture
def pipeline(monkeypatch):
    monkeypatch.setattr(repair, 'artifacts', lambda: ('fixed-reviewed-update', {}, {}))
    async def locked(connection, **options):
        connection.events.append('locks_and_guards')
        return list(connection.snapshot[0])
    async def observed(connection, tables): return deepcopy(connection.snapshot)
    async def validated(connection): connection.events.append('row_validation')
    monkeypatch.setattr(repair, 'lock_and_validate', locked)
    monkeypatch.setattr(repair, 'state_snapshot', observed)
    monkeypatch.setattr(repair, 'validate_rows', validated)


@pytest.mark.parametrize('apply', [False, True])
def test_receipt_is_committed_only_after_own_transaction_succeeds(snapshot, pipeline, apply):
    connection = Connection(snapshot)
    result = asyncio.run(repair.repair(connection, expected_database='fixture', expected_owner='owner', apply=apply))
    assert result['commit_state'] == 'committed'
    assert result['state'] == ('repaired' if apply else 'repair_required')
    assert result['required_rows'] == 2 and result['changed_rows'] == (2 if apply else 0)
    assert result['target_sha256'] == repair.target_fingerprint(connection,
        expected_database='fixture', expected_owner='owner')
    assert connection.events[0] == 'begin' and connection.events[-1] == 'commit'
    assert connection.events.count('update') == int(apply)
    assert connection.snapshot == (canonicalized(snapshot) if apply else snapshot)


def test_canonical_retry_is_idempotent(snapshot, pipeline):
    connection = Connection(canonicalized(snapshot))
    result = asyncio.run(repair.repair(connection, expected_database='fixture', expected_owner='owner', apply=True))
    assert result['state'] == 'already_canonical'
    assert result['changed_rows'] == result['required_rows'] == 0
    assert 'update' not in connection.events


def test_outer_transaction_receipt_stays_pending(snapshot, pipeline):
    connection = Connection(snapshot)
    connection.info.transaction_status = TransactionStatus.INTRANS
    result = asyncio.run(repair.repair_in_transaction(connection, expected_database='fixture', expected_owner='owner', apply=True))
    assert result['commit_state'] == 'pending'
    assert not {'begin', 'commit'} & set(connection.events)


def test_commit_failure_cannot_issue_committed_receipt(snapshot, pipeline):
    connection = Connection(snapshot, commit_failure=True)
    with pytest.raises(RuntimeError):
        asyncio.run(repair.repair(connection, expected_database='fixture', expected_owner='owner', apply=True))
    assert connection.events[-1] == 'commit_failed'
    assert 'commit' not in connection.events
    assert connection.snapshot == snapshot


def test_unexpected_trigger_side_effect_rolls_back_repair(snapshot, pipeline):
    connection = Connection(snapshot)
    update = connection.execute
    async def corrupt(statement, parameters=None):
        cursor = await update(statement, parameters)
        next(iter(connection.snapshot[0]['cragkit.documents'].values()))['authorization_revision'] = '1'
        return cursor
    connection.execute = corrupt
    with pytest.raises(repair.RepairError, match='lexical_repair_state_changed'):
        asyncio.run(repair.repair(connection, expected_database='fixture', expected_owner='owner', apply=True))
    assert connection.events[-1] == 'rollback'
    assert connection.snapshot == snapshot


def test_update_count_disagreement_rolls_back_repair(snapshot, pipeline):
    connection = Connection(snapshot)
    update = connection.execute
    async def wrong_count(statement, parameters=None):
        cursor = await update(statement, parameters)
        cursor.rowcount += 1
        return cursor
    connection.execute = wrong_count
    with pytest.raises(repair.RepairError, match='lexical_repair_update_count_invalid'):
        asyncio.run(repair.repair(connection, expected_database='fixture', expected_owner='owner', apply=True))
    assert connection.events[-1] == 'rollback'
    assert connection.snapshot == snapshot


def test_writer_lock_refusal_rolls_back_without_update(snapshot, monkeypatch):
    from psycopg.errors import LockNotAvailable
    connection = Connection(snapshot)
    async def blocked(*args, **kwargs): raise LockNotAvailable('synthetic-private-lock-diagnostic')
    monkeypatch.setattr(repair, 'artifacts', lambda: ('fixed-reviewed-update', {}, {}))
    monkeypatch.setattr(repair, 'lock_and_validate', blocked)
    with pytest.raises(LockNotAvailable):
        asyncio.run(repair.repair(connection, expected_database='fixture', expected_owner='owner', apply=True))
    assert connection.events == ['begin', 'rollback']
    assert connection.snapshot == snapshot


@pytest.mark.parametrize('status', [TransactionStatus.INTRANS, TransactionStatus.INERROR, TransactionStatus.ACTIVE])
def test_own_transaction_requires_idle_connection(status):
    connection = Connection()
    connection.info.transaction_status = status
    with pytest.raises(repair.RepairError, match='lexical_repair_idle_required'):
        asyncio.run(repair.repair(connection, expected_database='fixture', expected_owner='owner'))
    assert connection.events == []


@pytest.mark.parametrize('apply', [0, 1, None, 'apply'])
def test_invalid_mode_cannot_enter_mutation_path(apply):
    connection = Connection()
    connection.info.transaction_status = TransactionStatus.INTRANS
    with pytest.raises(repair.RepairError, match='lexical_repair_mode_invalid'):
        asyncio.run(repair.repair_in_transaction(connection, expected_database='fixture', expected_owner='owner', apply=apply))
    assert connection.events == []


def test_nested_entrypoint_requires_an_open_transaction():
    with pytest.raises(repair.RepairError, match='lexical_repair_transaction_required'):
        asyncio.run(repair.repair_in_transaction(Connection(), expected_database='fixture', expected_owner='owner'))


@pytest.mark.parametrize('target', [('other_database', 'owner', 'owner'), ('fixture', 'other_owner', 'other_owner'),
    ('fixture', 'owner', 'different_session_user'), ('fixture', 'owner', 'owner')])
def test_wrong_target_or_unverified_tls_refuses_before_locks(monkeypatch, target):
    connection = Connection()
    connection.pgconn = type('PGConn', (), dict(ssl_in_use=target != ('fixture', 'owner', 'owner')))()
    async def fetched(*args, **kwargs): return [target]
    monkeypatch.setattr(repair, 'fetch', fetched)
    with pytest.raises(repair.RepairError, match='lexical_repair_target_invalid'):
        asyncio.run(repair.lock_and_validate(connection, expected_database='fixture', expected_owner='owner', catalog={}, functions={}))
    assert connection.events == []


@pytest.mark.parametrize('bound', ['rows', 'bytes', 'combined_rows', 'catalog_bytes'])
def test_snapshot_bounds_refuse_before_payload_allocation(monkeypatch, bound):
    allocations = []
    async def fetched(connection, statement, parameters=None):
        if statement.startswith('SELECT count(*)'):
            if 'FROM cragkit.documents ' in statement:
                return [(repair.MAX_ROWS + 1 if bound == 'rows' else repair.MAX_ROWS if bound == 'combined_rows' else 0,
                         repair.MAX_BYTES + 1 if bound == 'bytes' else 0)]
            return [(1 if bound == 'combined_rows' else 0, repair.MAX_BYTES + 1 if bound == 'catalog_bytes' else 0)]
        if statement.startswith('SELECT to_jsonb'):
            return []
        allocations.append(statement)
        return [({},)]
    monkeypatch.setattr(repair, 'fetch', fetched)
    with pytest.raises(repair.RepairError, match='lexical_repair_bound_exceeded'):
        asyncio.run(repair.state_snapshot(object(), ['cragkit.documents']))
    assert allocations == []


def test_snapshot_rejects_duplicate_document_identity(monkeypatch):
    row = dict(tenant_id='tenant', collection_id='collection', document_id='same')
    async def fetched(connection, statement, parameters=None):
        return [(2, 100)] if statement.startswith('SELECT count(*)') else [(row,), (dict(row),)]
    monkeypatch.setattr(repair, 'fetch', fetched)
    with pytest.raises(repair.RepairError, match='lexical_repair_ambiguous_key'):
        asyncio.run(repair.state_snapshot(object(), ['cragkit.documents']))


@pytest.mark.parametrize('optional,history,code', [
    ((True, True, False), repair.SETUP_IDENTITIES[:1], 'lexical_repair_setup_only_unsupported'),
    ((True, False, False), (), 'lexical_repair_optional_storage_unmanaged'),
    ((False, True, False), (), 'lexical_repair_optional_storage_unmanaged'),
    ((False, False, True), (), 'lexical_repair_optional_storage_unmanaged'),
    ((True, True, True), (('unknown', 'a'*64),), 'lexical_repair_history_invalid'),
])
def test_optional_storage_cannot_masquerade_as_supported_target(monkeypatch, optional, history, code):
    connection = Connection()
    connection.pgconn = type('PGConn', (), dict(ssl_in_use=True))()
    async def executed(statement, parameters=None): connection.events.append('setup')
    connection.execute = executed
    async def fetched(connection, statement, parameters=None):
        if 'current_database()' in statement: return [('fixture', 'owner', 'owner')]
        if 'to_regnamespace' in statement: return [optional]
        if 'setup_history' in statement: return list(history)
        raise AssertionError('Unsupported target must refuse before inspecting application data')
    monkeypatch.setattr(repair, 'fetch', fetched)
    with pytest.raises(repair.RepairError, match=code):
        asyncio.run(repair.lock_and_validate(connection, expected_database='fixture', expected_owner='owner', catalog={}, functions={}))


def test_hardened_lexical_only_target_never_requires_optional_storage(monkeypatch):
    connection = Connection()
    connection.pgconn = type('PGConn', (), dict(ssl_in_use=True))()
    tables = sorted('cragkit.'+name for name in repair.KEYS if name != 'embedding_profiles')
    async def executed(statement, parameters=None): connection.events.append('administrative_guard')
    connection.execute = executed
    async def fetched(connection, statement, parameters=None):
        if 'current_database()' in statement: return [('fixture', 'owner', 'owner')]
        if 'to_regnamespace' in statement: return [(False, False, False)]
        if 'setup_history' in statement or 'embedding_profiles' in statement:
            raise AssertionError('Base-only target cannot depend on optional storage')
        if "n.nspname||'.'||c.relname" in statement: return [(name,) for name in tables]
        if 'FROM cragkit.migration_history' in statement: return list(repair.EXPECTED_HISTORY)
        if statement == repair._CATALOG_SQL: return [(True,)]
        if 'pg_get_userbyid(nspowner)' in statement: return [('cragkit', 'owner')]
        if 'SELECT relkind,relrowsecurity' in statement: return [('r', True, False, 'owner')]
        if 'aclexplode' in statement: return [(0,)]
        if 'SELECT attname FROM pg_attribute' in statement:
            name = parameters[0].split('.')[1]
            return [(entry.split(':')[0],) for entry in repair._TABLE_COLUMNS[name].split()]
        if 'a.attname,a.attnotnull' in statement:
            defaults = {'language_config': "'pg_catalog.simple'::text", 'identifier_tokens': 'ARRAY[]::cragkit.identity_text[]'}
            return [(entry.split(':')[0], True, '', '', defaults.get(entry.split(':')[0]))
                for entry in repair._TABLE_COLUMNS['chunk_lexical'].split()]
        raise AssertionError('Unexpected optional storage query')
    async def triggers(*args, **kwargs): connection.events.append('trigger_guards')
    monkeypatch.setattr(repair, 'fetch', fetched)
    monkeypatch.setattr(repair, 'validate_triggers', triggers)
    result = asyncio.run(repair.lock_and_validate(connection, expected_database='fixture', expected_owner='owner', catalog={}, functions={}))
    assert result == tables and len(result) == 9
    assert 'trigger_guards' in connection.events


def test_changed_maintenance_artifact_is_refused_without_echoing_bytes(monkeypatch):
    monkeypatch.setattr(repair, '_regular_bytes', lambda *args: b'synthetic-private-sql-payload')
    with pytest.raises(repair.RepairError) as error:
        repair.artifacts()
    assert str(error.value) == 'lexical_repair_artifact_drift'
    assert 'synthetic-private' not in str(error.value)


@pytest.mark.parametrize('change', ['missing', 'extra', 'disabled', 'body', 'owner', 'strict',
    'leakproof', 'parallel', 'return_type', 'security_definer', 'arguments'])
def test_affected_trigger_or_function_drift_is_refused_before_data_access(monkeypatch, change):
    row = ['canonical_lexical_vector', 'refresh_lexical_vector', 23, 'O', 0, '', True,
        None, None, False, 'v', 'plpgsql', ['search_path=pg_catalog'], 'frozen-body',
        'owner', True, False, False, 'u', 'f', False, True, 0, None, None, None, 100., 0., True]
    index_value = {'disabled': (3, 'D'), 'body': (13, 'changed-body'), 'owner': (14, 'other'),
        'strict': (16, True), 'leakproof': (17, True), 'parallel': (18, 's'),
        'return_type': (21, False), 'security_definer': (9, True), 'arguments': (22, 1)}
    if change in index_value:
        index, value = index_value[change]
        row[index] = value
    observed = [] if change == 'missing' else [tuple(row)] * (2 if change == 'extra' else 1)
    async def fetched(connection, statement, parameters=None):
        assert parameters == ('cragkit.chunk_lexical',), 'Drift must refuse before reading another table'
        return observed
    monkeypatch.setattr(repair, 'fetch', fetched)
    with pytest.raises(repair.RepairError, match='lexical_repair_trigger_invalid'):
        asyncio.run(repair.validate_triggers(object(), {'refresh_lexical_vector': 'frozen-body'}, 'owner'))


@pytest.mark.parametrize('tamper', [None, 'missing_text_cast', 'not_null', 'wrong_type',
    'wrong_dimensions', 'extra_check'])
def test_pg17_check_expression_round_trip_is_exact(monkeypatch, tamper):
    functions = {function: 'frozen-body-' + function
        for triggers in repair.TRIGGERS.values() for _, function, _ in triggers}
    expressions = [
        '(array_position(identifier_tokens, (NULL::text)::cragkit.identity_text) IS NULL)',
        '((array_ndims(identifier_tokens) IS NULL) OR (array_ndims(identifier_tokens) = 1))',
    ]
    if tamper == 'missing_text_cast': expressions[0] = expressions[0].replace('NULL::text', 'NULL')
    if tamper == 'not_null': expressions[0] = expressions[0].replace('IS NULL', 'IS NOT NULL')
    if tamper == 'wrong_type': expressions[0] = expressions[0].replace('cragkit.identity_text', 'text')
    if tamper == 'wrong_dimensions': expressions[1] = expressions[1].replace('= 1', '= 2')
    if tamper == 'extra_check': expressions.append('true')
    async def fetched(connection, statement, parameters=None):
        if parameters is not None:
            table = parameters[0].split('.')[1]
            output = []
            for name, function, kind in sorted(repair.TRIGGERS[table]):
                output.append((name, function, kind, 'O', 0,
                    '11' if function == 'refresh_chunk_lexical' else '', True, None, None,
                    False, 'v', 'plpgsql', ['search_path=pg_catalog'], functions[function],
                    'owner', True, False, False, 'u', 'f', False, True, 0, None, None, None, 100., 0., True))
            return output
        if 'SELECT pg_get_expr(conbin,conrelid)' in statement:
            return [(expression,) for expression in expressions]
        if 'count(*)=4' in statement:
            return [(True, True, True, True)]
        return [(0,)]
    monkeypatch.setattr(repair, 'fetch', fetched)
    if tamper is None:
        asyncio.run(repair.validate_triggers(object(), functions, 'owner'))
    else:
        with pytest.raises(repair.RepairError, match='lexical_repair_catalog_invalid'):
            asyncio.run(repair.validate_triggers(object(), functions, 'owner'))


def test_target_fingerprint_binds_only_noncredential_connection_fields():
    class Info:
        host, port = '127.0.0.1', 5432
        @property
        def dsn(self): raise AssertionError('DSN must never be read')
        @property
        def password(self): raise AssertionError('Password must never be read')
        def get_parameters(self): raise AssertionError('Bulk connection parameters must never be read')
    connection = type('Connection', (), dict(info=Info()))()
    expected = dict(host='127.0.0.1', port=5432, database='fixture', owner='owner')
    observed = repair.target_fingerprint(connection, expected_database='fixture', expected_owner='owner')
    assert observed == sha256(repair.canonical(expected)).hexdigest()
    for field, value in [('host', '127.0.0.2'), ('port', 5433)]:
        original = getattr(connection.info, field)
        setattr(connection.info, field, value)
        assert repair.target_fingerprint(connection, expected_database='fixture', expected_owner='owner') != observed
        setattr(connection.info, field, original)
    assert repair.target_fingerprint(connection, expected_database='another', expected_owner='owner') != observed
    assert repair.target_fingerprint(connection, expected_database='fixture', expected_owner='another') != observed


@pytest.mark.parametrize('host,port,database,owner', [
    ('', 5432, 'fixture', 'owner'), (None, 5432, 'fixture', 'owner'),
    ('x'*1025, 5432, 'fixture', 'owner'), ('\u20b9'*342, 5432, 'fixture', 'owner'),
    ('127.0.0.1', 0, 'fixture', 'owner'), ('127.0.0.1', 65536, 'fixture', 'owner'),
    ('127.0.0.1', True, 'fixture', 'owner'), ('127.0.0.1', '5432', 'fixture', 'owner'),
    ('127.0.0.1', 5432, None, 'owner'), ('127.0.0.1', 5432, 'fixture', False),
])
def test_target_fingerprint_rejects_invalid_scalar_metadata(host, port, database, owner):
    connection = type('Connection', (), dict(info=type('Info', (), dict(host=host, port=port))()))()
    with pytest.raises(repair.RepairError):
        repair.target_fingerprint(connection, expected_database=database, expected_owner=owner)


def cli_pipeline(monkeypatch, operation):
    import check_python_postgres
    import check_postgres_profile_storage
    configuration = {'fixture_configuration': True}
    class Connection:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
    async def connect(value):
        assert value is configuration
        return Connection()
    monkeypatch.setattr(check_python_postgres, 'load_config', lambda path: configuration)
    monkeypatch.setattr(check_postgres_profile_storage, 'connect', connect)
    monkeypatch.setattr(repair, 'repair', operation)


@pytest.fixture
def private_config(tmp_path):
    path = tmp_path/'operator-config.json'
    path.write_text('{"fixture_configuration":true}\n')
    path.chmod(0o600)
    return str(path)


@pytest.mark.parametrize('mode,state,exit_status', [('--check', 'repair_required', 2),
    ('--check', 'already_canonical', 0), ('--apply', 'repaired', 0),
    ('--apply', 'already_canonical', 0)])
def test_cli_distinguishes_pending_repair_from_readiness(monkeypatch, capsys, private_config, mode, state, exit_status):
    async def operation(connection, **options):
        assert options == dict(expected_database='fixture', expected_owner='owner', apply=mode == '--apply')
        return dict(revision='LCR-r1', state=state, commit_state='committed')
    cli_pipeline(monkeypatch, operation)
    result = repair.main([mode, '--config', private_config,
        '--expected-database', 'fixture', '--expected-owner', 'owner', '--confirm-dedicated-target'])
    output = capsys.readouterr()
    assert result == exit_status
    assert json.loads(output.out) == dict(revision='LCR-r1', state=state, commit_state='committed')
    assert output.err == ''


@pytest.mark.parametrize('typed', [False, True])
def test_cli_failure_is_fixed_and_never_echoes_database_exception(monkeypatch, capsys, private_config, typed):
    called = []
    async def operation(connection, **options):
        called.append(True)
        if typed: raise repair.RepairError('lexical_repair_catalog_invalid')
        raise RuntimeError('synthetic-private-database-diagnostic')
    cli_pipeline(monkeypatch, operation)
    result = repair.main(['--check', '--config', private_config,
        '--expected-database', 'fixture', '--expected-owner', 'owner', '--confirm-dedicated-target'])
    output = capsys.readouterr()
    assert result == 1
    assert json.loads(output.out) == dict(revision='LCR-r1', state='failed',
        code='lexical_repair_catalog_invalid' if typed else 'lexical_repair_failed')
    assert called == [True]
    assert 'synthetic-private' not in output.out + output.err
