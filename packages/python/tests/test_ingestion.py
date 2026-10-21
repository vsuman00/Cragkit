import asyncio
from contextlib import asynccontextmanager
import copy
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

import cragkit.ingestion as implementation
from cragkit.ingestion import PostgresIndexer
from cragkit.contracts import parse_scope
from cragkit.errors import DeadlineExceeded, IndexNotReady, InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability, IntegrityViolation


class Cursor:
    def __init__(self, rows): self.rows = rows
    async def fetchall(self): return self.rows


class DriverError(Exception):
    def __init__(self, state='XX000'):
        super().__init__('private-source-provider-password')
        self.sqlstate = state


class Connection:
    def __init__(self):
        self.info = SimpleNamespace(transaction_status=0)
        self.calls = []
        self.gucs = None
        self.started = self.committed = self.rolled_back = self.closed = 0
        self.role = [(True,)]
        self.catalog = [(True,)]
        self.history = list(implementation.EXPECTED_HISTORY)
        self.job = []
        self.document = []
        self.collection = [('0.1', 'native_fts.v1')]
        self.revision = []
        self.generation = []
        self.counts = [(1, 1)]
        self.created_document = True
        self.staged = []
        self.published = []
        self.failure = None
        self.rollback_bad = False
        self.rollback_block = None
        self.ready_rows = [(1,)]
        self.commit_error = None
        self.commit_block = False
        self.block_query = None
        self.block_entered = asyncio.Event()
        self.block_release = asyncio.Event()

    def transaction(self, *, force_rollback=False):
        assert force_rollback is False
        connection = self
        class Transaction:
            async def __aenter__(self):
                self.before = copy.deepcopy((connection.staged, connection.published, connection.gucs, connection.document, connection.revision, connection.generation))
                connection.info.transaction_status = 2
                connection.started += 1
            async def __aexit__(self, kind, value, traceback):
                if connection.rollback_block is not None:
                    await connection.rollback_block.wait()
                if kind is None:
                    if connection.commit_block:
                        await asyncio.Event().wait()
                    if connection.commit_error is not None:
                        raise connection.commit_error
                    connection.committed += 1
                else:
                    (connection.staged, connection.published, connection.gucs, connection.document, connection.revision, connection.generation) = self.before
                    connection.rolled_back += 1
                connection.gucs = self.before[2]
                connection.info.transaction_status = 3 if connection.rollback_bad else 0
        return Transaction()

    async def execute(self, query, params=None):
        self.calls.append((query, params))
        if self.failure is not None and self.failure[0] in query:
            raise self.failure[1]
        if self.block_query is not None and self.block_query in query:
            self.block_entered.set()
            await self.block_release.wait()
        if query == implementation._WRITER_ROLE_SQL: return Cursor(self.role)
        if query == implementation._CATALOG_SQL: return Cursor(self.catalog)
        if query == implementation._HISTORY_SQL: return Cursor(self.history)
        if query == implementation._JOB_SQL: return Cursor(self.job)
        if query == implementation._DOCUMENT_LOCK_SQL: return Cursor(self.document)
        if query == implementation._COLLECTION_SQL: return Cursor(self.collection)
        if query == implementation._REVISION_SQL: return Cursor(self.revision)
        if query == implementation._GENERATION_SQL: return Cursor(self.generation)
        if query == implementation._COUNTS_SQL: return Cursor(self.counts)
        if "set_config('cragkit.tenant_id'" in query:
            self.gucs = tuple(params)
        stripped = query.lstrip()
        if stripped.startswith(('INSERT ', 'UPDATE ')):
            self.staged.append((query, copy.deepcopy(params)))
            if stripped.startswith('UPDATE cragkit.index_generations'):
                return Cursor(self.ready_rows)
            if stripped.startswith('UPDATE cragkit.documents'):
                self.published.append(copy.deepcopy(params))
            if stripped.startswith('INSERT INTO cragkit.documents'):
                if self.created_document:
                    self.document = [(None, False, params[3])]
                return Cursor([('document',)] if self.created_document else [])
            if stripped.startswith('INSERT INTO cragkit.document_revisions'):
                self.revision = [(params[4], params[7], params[5], params[8])]
            return Cursor([(1,)])
        return Cursor([])

    async def close(self): self.closed += 1


class Resource:
    def __init__(self, connection):
        self.connection = connection
        self.config = SimpleNamespace(release_timeout=0.05)
        self.leased = self.returned = 0
    @asynccontextmanager
    async def lease(self, *, deadline):
        self.leased += 1
        try:
            yield self.connection
        finally:
            self.returned += 1


def scope(**changes):
    return parse_scope(dict(tenant_id='tenant', principal_id='principal', authorization_revision='auth', grant_ids=['unassigned-group'], **changes))


async def allow_write(scope, collection, document_id):
    return True


def fixture():
    connection = Connection()
    resource = Resource(connection)
    return connection, resource, PostgresIndexer(resource, authorize_write=allow_write)


async def ingest(indexer, source='synthetic source', **changes):
    arguments = dict(collection='collection', document_id='document', intent_id='intent', source_locator='synthetic:source',
                     scope=scope(), deadline=asyncio.get_running_loop().time() + 1)
    arguments.update(changes)
    return await indexer.ingest(source, **arguments)


def test_import_has_no_optional_driver_or_io(tmp_path):
    import subprocess
    import sys
    script = '''
import sys
class Deny:
 def find_spec(self,fullname,*args):
  if fullname in ('psycopg','psycopg_pool'): raise AssertionError('optional driver imported')
sys.meta_path.insert(0,Deny())
def audit(event,args):
 if event.startswith(('socket.','subprocess.')): raise AssertionError('network/process')
 if event=='open' and (isinstance(args[1],str) and any(c in args[1] for c in 'wax+')): raise AssertionError('write')
sys.addaudithook(audit)
import cragkit.ingestion
'''
    result = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ''


def test_new_ingestion_commits_scoped_writes_and_immutable_receipt():
    async def run():
        connection, resource, indexer = fixture()
        result = await ingest(indexer)
        assert result.tenant_id == 'tenant' and result.collection == 'collection'
        assert result.document_id == 'document' and result.intent_id == 'intent'
        assert result.chunk_count == 1 and result.replayed is False
        assert len(result.payload_sha256) == len(result.revision_id) == len(result.generation_id) == 64
        assert connection.started == connection.committed == 1 and connection.rolled_back == 0
        assert connection.info.transaction_status == 0 and connection.gucs is None
        assert resource.leased == resource.returned == 1 and connection.published
        with pytest.raises(Exception): result.replayed = True
        for query, params in connection.staged:
            assert params is not None and 'synthetic source' not in query
        grants = [(query, params) for query, params in connection.staged if 'document_grants' in query]
        assert len(grants) == 1 and 'unassigned-group' not in repr(grants)
    asyncio.run(run())


@pytest.mark.parametrize('changes', [dict(collection=''),dict(document_id=''),dict(intent_id=''),dict(source_locator=''),dict(metadata={'invalid':float('nan')}),dict(metadata={'invalid':object()}),dict(canonical_options={'target_bytes':0})])
def test_invalid_boundaries_reject_before_lease(changes):
    async def run():
        connection, resource, indexer = fixture()
        with pytest.raises(InvalidRequest): await ingest(indexer, **changes)
        assert resource.leased == 0 and connection.calls == []
    asyncio.run(run())


@pytest.mark.parametrize('field,value,kind', [('role',[(False,)],UnauthorizedScope),('catalog',[(False,)],UnsupportedCapability),('history',[],UnsupportedCapability),('collection',[('0.1','other')],UnsupportedCapability)])
def test_schema_and_writer_role_fail_closed(field,value,kind):
    async def run():
        connection, resource, indexer = fixture();setattr(connection,field,value)
        with pytest.raises(kind): await ingest(indexer)
        assert connection.committed == 0 and connection.rolled_back == 1
        assert connection.staged == [] and connection.published == [] and resource.returned == 1
    asyncio.run(run())


def test_prepublication_hook_failure_preserves_original_exception_and_storage():
    async def run():
        connection, resource, indexer = fixture();sentinel=RuntimeError('caller sentinel')
        async def fail():
            assert connection.staged and not connection.published
            raise sentinel
        with pytest.raises(RuntimeError) as caught: await ingest(indexer,before_publish=fail)
        assert caught.value is sentinel and connection.staged == [] and connection.published == []
        assert connection.rolled_back == 1 and connection.committed == 0 and resource.returned == 1
    asyncio.run(run())


def test_tombstone_auth_revision_and_generation_comparison_reject():
    async def run():
        for document, kind in [([('active',True,'auth')],UnauthorizedScope),([('active',False,'other')],UnauthorizedScope),([('active',False,'auth')],IndexNotReady)]:
            connection, resource, indexer=fixture();connection.document=document;connection.created_document=False
            with pytest.raises(kind): await ingest(indexer,expected_generation_id='stale')
            assert not connection.committed and connection.staged == [] and resource.returned == 1
    asyncio.run(run())


def test_nonidle_caller_connection_is_untouched():
    async def run():
        connection, resource, indexer=fixture();connection.info.transaction_status=2
        with pytest.raises(InvalidRequest): await ingest(indexer)
        assert connection.calls == [] and connection.started == 0 and resource.returned == 1
    asyncio.run(run())


@pytest.mark.parametrize('state,kind',[('57014',DeadlineExceeded),('42501',UnauthorizedScope),('42P01',UnsupportedCapability),('XX000',ProviderUnavailable)])
def test_driver_errors_are_typed_redacted_and_rolled_back(state,kind):
    async def run():
        connection, resource, indexer=fixture();connection.failure=('INSERT INTO cragkit.index_generations',DriverError(state))
        with pytest.raises(kind) as caught:await ingest(indexer)
        assert 'private' not in str(caught.value) and caught.value.__cause__ is None
        assert connection.staged == [] and connection.rolled_back == 1 and resource.returned == 1
    asyncio.run(run())


def test_cancelled_prepublication_work_rolls_back_and_resource_is_reusable():
    async def run():
        connection, resource, indexer=fixture();entered=asyncio.Event()
        async def wait():entered.set();await asyncio.Event().wait()
        task=asyncio.create_task(ingest(indexer,before_publish=wait))
        await asyncio.wait_for(entered.wait(),1);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert connection.staged == [] and connection.rolled_back == 1 and connection.info.transaction_status == 0
        assert (await ingest(indexer)).replayed is False and resource.leased == resource.returned == 2
    asyncio.run(run())


def test_absolute_deadline_covers_prepublication_and_late_body_completion():
    async def run():
        for stall in (False,True):
            connection, resource, indexer=fixture()
            async def stop():
                if stall:
                    until=time.monotonic()+0.03
                    while time.monotonic()<until:pass
                else:await asyncio.Event().wait()
            with pytest.raises(DeadlineExceeded):await ingest(indexer,deadline=asyncio.get_running_loop().time()+0.02,before_publish=stop)
            assert connection.staged == [] and connection.rolled_back == 1 and resource.returned == 1
    asyncio.run(run())


def test_same_payload_replay_verifies_generation_without_writes_or_cas():
    async def run():
        connection, resource, indexer=fixture();first=await ingest(indexer)
        connection.calls=[];connection.staged=[];connection.published=[]
        connection.job=[(first.payload_sha256,first.generation_id,'succeeded','document')]
        connection.document=[('newer-active-generation',False,'auth')]
        connection.generation=[(first.revision_id,'ready',first.chunk_count)]
        replay=await ingest(indexer)
        assert replay.replayed is True and replay.generation_id==first.generation_id and replay.revision_id==first.revision_id
        assert connection.staged==[] and connection.published==[]
        assert resource.leased==resource.returned==2
    asyncio.run(run())


@pytest.mark.parametrize('job',[[('0'*64,'generation','succeeded','document')],[('0'*64,'generation','succeeded','different-document')]])
def test_changed_payload_or_document_under_intent_rejects_atomically(job):
    async def run():
        connection,resource,indexer=fixture();connection.job=job
        with pytest.raises(InvalidRequest):await ingest(indexer)
        assert connection.staged==[] and connection.published==[] and connection.rolled_back==1
    asyncio.run(run())


def test_replay_corrupt_generation_or_counts_is_not_success():
    async def run():
        for corrupt in ('state','generation','counts'):
            connection,resource,indexer=fixture();first=await ingest(indexer)
            connection.job=[(first.payload_sha256,first.generation_id,'succeeded','document')]
            connection.generation=[(first.revision_id,'ready',first.chunk_count)]
            if corrupt=='state':connection.job=[(first.payload_sha256,first.generation_id,'running','document')]
            if corrupt=='generation':connection.generation=[(first.revision_id,'staging',first.chunk_count)]
            if corrupt=='counts':connection.counts=[(0,0)]
            with pytest.raises((IndexNotReady,IntegrityViolation)):await ingest(indexer)
    asyncio.run(run())


def test_json_metadata_is_snapshotted_and_rejects_cycles_depth_and_nonfinite():
    async def run():
        for invalid in ([float('inf')], [float('nan')], {'private':'\ud800'}, {'private':'\0'}):
            connection,resource,indexer=fixture()
            with pytest.raises(InvalidRequest):await ingest(indexer,metadata={'nested':invalid})
            assert resource.leased==0
        cycle={};cycle['self']=cycle
        connection,resource,indexer=fixture()
        with pytest.raises(InvalidRequest):await ingest(indexer,metadata=cycle)
        assert resource.leased==0
    asyncio.run(run())


def test_rollback_nonidle_postcondition_discards_uncertain_connection():
    async def run():
        connection,resource,indexer=fixture();connection.rollback_bad=True
        with pytest.raises(ProviderUnavailable):await ingest(indexer)
        assert connection.closed==1 and resource.returned==1
    asyncio.run(run())


@pytest.mark.parametrize('allowed', [False, None, 1, 'yes'])
def test_write_authorization_requires_exact_true_before_parsing_or_lease(allowed):
    async def run():
        connection, resource, _ = fixture()
        calls = []
        async def authorize(bound_scope, collection, document_id):
            calls.append((bound_scope, collection, document_id))
            return allowed
        indexer = PostgresIndexer(resource, authorize_write=authorize)
        with pytest.raises(UnauthorizedScope):
            await ingest(indexer, source='not parsed', canonical_options={'token_counter': lambda text: pytest.fail('unauthorized parsing')})
        assert len(calls) == 1 and calls[0] == (scope(), 'collection', 'document')
        assert resource.leased == 0 and connection.calls == []
    asyncio.run(run())


def test_write_authorization_deadline_and_cancellation_prevent_lease():
    async def run():
        connection, resource, _ = fixture()
        entered = asyncio.Event()
        async def authorize(bound_scope, collection, document_id):
            entered.set()
            await asyncio.Event().wait()
        indexer = PostgresIndexer(resource, authorize_write=authorize)
        with pytest.raises(DeadlineExceeded):
            await ingest(indexer, deadline=asyncio.get_running_loop().time() + 0.01)
        task = asyncio.create_task(ingest(indexer))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert resource.leased == 0 and connection.calls == []
    asyncio.run(run())


def test_metadata_shared_tlv_hash_oracle():
    import json
    cases = json.loads((Path(__file__).resolve().parents[3] / 'contracts/fixtures/ingestion.json').read_text())
    for case in cases['metadata_cases']:
        serialized, digest = implementation._metadata(case['value'])
        assert digest == case['sha256'], case['id']
        assert json.loads(serialized) == case['value']


@pytest.mark.parametrize('block', [False, True])
def test_commit_failure_discards_connection_without_claiming_no_publication(block):
    async def run():
        connection, resource, indexer = fixture()
        connection.commit_block = block
        connection.commit_error = DriverError()
        with pytest.raises(DeadlineExceeded if block else ProviderUnavailable) as caught:
            await ingest(indexer, deadline=asyncio.get_running_loop().time() + 0.02)
        assert 'private' not in str(caught.value)
        assert connection.closed == 1 and resource.returned == 1
        # A missing COMMIT acknowledgement cannot establish whether the server committed.
        assert connection.rolled_back == 0
    asyncio.run(run())


def test_begin_and_setup_driver_failures_are_redacted():
    async def run():
        connection, resource, indexer = fixture()
        connection.failure = ('SET LOCAL search_path', DriverError())
        with pytest.raises(ProviderUnavailable) as caught:
            await ingest(indexer)
        assert caught.value.__cause__ is None and 'private' not in str(caught.value)
        assert connection.rolled_back == 1 and resource.returned == 1
    asyncio.run(run())


def test_shared_identifier_oracle_matches_python():
    import json
    from cragkit.canonical import CanonicalDocument
    root = Path(__file__).resolve().parents[3]
    fixtures = json.loads((root / 'contracts/fixtures/ingestion.json').read_text())
    canonical = json.loads((root / 'contracts/fixtures/canonical.json').read_text())['cases']
    for case in fixtures['identifier_cases']:
        document = next(item['expected'] for item in canonical if item['id'] == case['canonical_case'])
        document = CanonicalDocument.model_validate_json(json.dumps(document))
        metadata = next(item for item in fixtures['metadata_cases'] if item['id'] == case['metadata_case'])
        actual = implementation._identifiers(document, parse_scope(case['scope']), case['collection'],
            case['document_id'], case['intent_id'], case['source_locator'], metadata['sha256'], case['expected_generation_id'])
        assert list(actual) == case['expected'], case['id']


def test_missing_ready_publication_barrier_cannot_publish_document():
    async def run():
        connection, resource, indexer = fixture()
        connection.ready_rows = []
        with pytest.raises(IntegrityViolation):
            await ingest(indexer)
        assert connection.committed == 0 and connection.rolled_back == 1
        assert connection.published == [] and connection.staged == []
    asyncio.run(run())
