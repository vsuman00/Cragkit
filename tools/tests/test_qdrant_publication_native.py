"""Publication fixture boundaries without starting a server or reading secrets."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qdrant_publication_native as native
from qdrant_publication_schema import seed_records
from qdrant_writer_cases import writer_input
from runtime_diagnostics import CleanupFailure


class Connection:
    def __init__(self):
        self.commands = []
        self.events = []
        self.close_error = None

    @asynccontextmanager
    async def transaction(self):
        self.events.append('begin')
        yield
        self.events.append('commit')

    async def execute(self, query, params=None, **options):
        self.commands.append((str(query), params, options))
        self.events.append('query')
        return self

    async def fetchall(self):
        fingerprint = json.loads((native.ROOT / 'contracts/fixtures/qdrant_publication_catalog.json').read_text())['catalog_fingerprint']
        return [(fingerprint,)]

    async def close(self):
        self.events.append('close')
        if self.close_error:
            raise self.close_error


class Fixture:
    def __init__(self):
        self.created = []

    def reader_config(self, name, password):
        self.created.append((name, len(password)))
        return {'user': name, 'passfile': '/private/synthetic-passfile'}


def test_constructor_has_no_io_and_configuration_is_explicit():
    fixture = Fixture()
    database = native.PublicationDatabase(fixture)
    assert database.admin is None and fixture.created == []
    assert repr(database) == 'PublicationDatabase()'
    with pytest.raises(RuntimeError, match='publication_fixture_role'):
        database.config('writer')


def test_source_history_precedes_publication_and_catalog_is_checked_after_commit():
    pytest.importorskip('psycopg')
    database = native.PublicationDatabase(Fixture())
    database.admin = connection = Connection()
    asyncio.run(database._install())
    source_history = next(index for index, (_, params, _) in enumerate(connection.commands)
        if params and params[0] == '0001_authority')
    publication = next(index for index, (query, _, _) in enumerate(connection.commands)
        if 'CREATE TABLE cragkit_qdrant.backend_instances' in query)
    assert source_history < publication
    assert connection.events[-3:] == ['commit', 'query', 'query']
    assert len(database.fixture.created) == 3
    assert all(length == 64 for _, length in database.fixture.created)
    config = database.config('writer')
    config['user'] = 'forged'
    assert database.config('writer')['user'] == native.LOGIN_ROLES['writer']
    assert database.checks == ['committed_exact_publication_schema', 'dedicated_login_roles_provisioned']


def test_scope_is_parameterized_and_unknown_settings_fail_before_query():
    connection = Connection()
    records = seed_records()
    asyncio.run(native.bind_scope(connection, records))
    assert len(connection.commands) == 9
    assert all(query == 'SELECT set_config(%s,%s,true)' and params[0].startswith('cragkit_qdrant.')
        for query, params, _ in connection.commands)
    connection.commands.clear()
    with pytest.raises(ValueError, match='publication_fixture_setting'):
        asyncio.run(native.bind_scope(connection, records, unknown='unsafe'))
    assert connection.commands == []


def test_close_is_idempotent_and_preserves_primary_when_cleanup_fails():
    database = native.PublicationDatabase(Fixture())
    database.admin = connection = Connection()
    primary = RuntimeError('primary synthetic failure')
    connection.close_error = RuntimeError('private synthetic cleanup detail')
    with pytest.raises(CleanupFailure) as caught:
        asyncio.run(database._close(primary))
    assert database.admin is None
    assert caught.value.to_dict()['primary']['category'] == 'operation'
    assert caught.value.to_dict()['primary']['operation'] == 'primary'
    assert 'private synthetic' not in str(caught.value)
    asyncio.run(database._close())
    assert connection.events == ['close']


def test_committed_catalog_mismatch_is_not_accepted():
    pytest.importorskip('psycopg')
    database = native.PublicationDatabase(Fixture())
    database.admin = connection = Connection()
    async def wrong():
        return [('0' * 64,)]
    connection.fetchall = wrong
    with pytest.raises(RuntimeError, match='publication_fixture_committed_catalog_mismatch'):
        asyncio.run(database._install())
    assert database.checks == []


def test_tls_failure_close_is_bounded_and_combined_failure_stays_redacted(monkeypatch):
    psycopg = pytest.importorskip('psycopg')
    from types import SimpleNamespace
    connection = Connection()
    connection.pgconn = SimpleNamespace(ssl_in_use=False)
    connection.close_error = RuntimeError('private close detail')
    async def connect(**kwargs):
        assert kwargs['sslmode'] == 'verify-full' and kwargs['autocommit'] is True
        return connection
    monkeypatch.setattr(psycopg.AsyncConnection, 'connect', connect)
    config = dict(host='127.0.0.1', port=5432, dbname='postgres', user='synthetic',
        passfile='/private/synthetic', sslrootcert='/private/synthetic-ca')
    with pytest.raises(CleanupFailure) as caught:
        asyncio.run(native.PublicationDatabase._connect(config))
    diagnostic = caught.value.to_dict()
    assert diagnostic['primary']['operation'] == 'primary'
    assert diagnostic['cleanup'][0]['operation'] == 'admin_close'
    assert 'private' not in str(caught.value)


def test_native_writer_input_binds_exact_manifest_and_creation_without_model_calls():
    from cragkit._qdrant_manifest import encode_manifest, encode_stage_intent
    value = writer_input()
    stage = value['stage']
    manifest = encode_manifest(stage['manifest'], stage['canonical_text'])
    assert manifest.sha256 == stage['intent']['manifest_sha256']
    assert stage['intent']['expected_active_generation_id'] is None
    assert stage['intent']['initial_authorization']['tombstoned'] is False
    assert stage['intent']['expected_mutation_epoch'] == 1
    assert len(stage['dense_vectors']) == len(stage['sparse_vectors']) == 2
    assert all(len(vector) == 1536 for vector in stage['dense_vectors'])
    assert encode_stage_intent(stage['intent']).value[-1][-1] == 'false'
    assert value['config']['dense_profile']['provider'] == 'fake'


def test_child_output_reads_to_eof_and_rejects_later_overflow():
    from check_qdrant_writer import read_bounded
    class Stream:
        def __init__(self, chunks): self.chunks = list(chunks)
        async def read(self, maximum):
            if not self.chunks: return b''
            chunk = self.chunks.pop(0)
            assert len(chunk) <= maximum
            return chunk
    assert asyncio.run(read_bounded(Stream([b'{"ok":true}', b'\ntrailing']), 30)) == b'{"ok":true}\ntrailing'
    with pytest.raises(RuntimeError, match='writer_child_output_exceeded'):
        asyncio.run(read_bounded(Stream([b'1234', b'56']), 5))


def test_child_failure_envelope_preserves_only_closed_primary_and_cleanup_labels():
    from check_qdrant_writer import failure_observation
    value = dict(ok=False, phase='dispatch', error='cleanup_failed', primary='IntegrityViolation',
        cleanup=[dict(operation='writer_close', outcome='ProviderUnavailable')])
    observed = failure_observation(value)
    value['cleanup'].clear()
    assert observed['cleanup'][0]['operation'] == 'writer_close'
    for malformed in [dict(ok=False, phase='private query text', error='internal'),
                      dict(ok=False, phase='stage', error='internal', detail='private driver message'),
                      dict(ok=False, phase='stage', error='cleanup_failed', primary='internal', cleanup=[]),
                      dict(ok=False, phase='stage', error='cleanup_failed', primary='private',
                        cleanup=[dict(operation='writer_close', outcome='internal')])]:
        with pytest.raises(RuntimeError, match='writer_node_failure_shape'):
            failure_observation(malformed)


def test_attestation_upgrade_is_explicit_additive_and_checks_committed_catalog():
    pytest.importorskip('psycopg')
    database = native.PublicationDatabase(Fixture(), with_attestations=True)
    database.admin = connection = Connection()
    async def current_catalog():
        value=json.loads((native.ROOT / 'contracts/fixtures/qdrant_attestation_catalog.json').read_text())
        return [(value['catalog_fingerprint'],)]
    connection.fetchall=current_catalog
    asyncio.run(database._install())
    history=[params[0] for _,params,_ in connection.commands if params and str(params[0]).startswith('000')]
    assert history==['0001_authority','0002_publication','0003_preparation_attestations']
    assert connection.events[-3:]==['commit','query','query']
    with pytest.raises(ValueError,match='publication_fixture_profile'):
        native.PublicationDatabase(Fixture(),with_attestations='yes')


def test_writer_failure_diagnostics_do_not_overwrite_an_unowned_artifacts_directory(tmp_path,monkeypatch,capsys):
    import check_qdrant_writer as writer_parent
    directory=tmp_path/'existing'
    directory.mkdir()
    diagnostic=directory/'failure-locations.json'
    diagnostic.write_text('user-owned')
    starts=[]
    def forbidden_fixture(*args,**kwargs):
        starts.append(True)
        raise AssertionError('unexpected fixture construction')
    monkeypatch.setattr(writer_parent,'PostgresSourceFixture',forbidden_fixture)
    assert writer_parent.main(['--postgres-bin','/unused','--artifacts-dir',str(directory),'--allow-local-processes'])==1
    assert json.loads(capsys.readouterr().out)['ok'] is False
    assert diagnostic.read_text()=='user-owned'
    assert list(directory.iterdir())==[diagnostic] and starts==[]
