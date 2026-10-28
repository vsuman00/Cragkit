"""Authority-only manager contracts with borrowed native writer spies."""
import asyncio
from pathlib import Path
from uuid import UUID

import pytest

import cragkit._qdrant_security as implementation
from cragkit._postgres_pool import PoolConfig, PoolResource
from cragkit._qdrant_security import QdrantSecurityManager
from cragkit._qdrant_writer import PostgresQdrantWriter
from cragkit.contracts import Limits
from cragkit.errors import (DeadlineExceeded, IndexNotReady, InvalidRequest,
                           ProviderUnavailable, UnauthorizedScope)
from cragkit.execution import BudgetExhausted, ExecutionLedger
from test_qdrant_manifest import security_record
from test_qdrant_writer import config, ctx, run_async


def deadline():
    return asyncio.get_running_loop().time()+5


def ledger(*, attempts=1, limit=None):
    return ExecutionLedger(Limits(deadline_ms=5000,max_attempts=attempts,max_provider_calls=0),
                           deadline=deadline() if limit is None else limit)


def setup(monkeypatch, callback=None):
    resource = PoolResource(PoolConfig(host='localhost',dbname='fixture',user='writer',
        sslrootcert=Path('/fixture/ca'),passfile=Path('/fixture/pass')))
    writer = PostgresQdrantWriter(resource,config(),'security-fixture')
    seen = dict(initialize=0,apply=[],authorize=[],closed=[])
    async def initialize(*,deadline):
        seen['initialize'] += 1
    async def apply(record,scope,*,owner_token,deadline):
        seen['apply'].append((record,scope,owner_token,deadline))
        return dict(state='authority_committed',revision_id=None,generation_id=None,
                    authority_committed=True,replica_complete=False,purge_complete=False)
    async def authorize(scope,collection,document):
        seen['authorize'].append((scope,collection,document))
        return True if callback is None else await callback(scope,collection,document)
    async def borrowed_close():
        seen['closed'].append(True)
    monkeypatch.setattr(writer,'initialize',initialize)
    monkeypatch.setattr(writer,'apply_security',apply)
    monkeypatch.setattr(writer,'close',borrowed_close)
    monkeypatch.setattr(resource,'close',borrowed_close)
    return QdrantSecurityManager(writer,authorize),writer,seen


@pytest.mark.parametrize('action',['update_authorization','tombstone'])
@run_async
async def test_independent_authority_manager_has_closed_result_and_borrows_resources(monkeypatch,action):
    manager,writer,seen = setup(monkeypatch)
    assert seen['initialize'] == 0 and seen['apply'] == []
    # A separate native publication writer may already own physical work.
    # This manager receives only its independent authority writer.
    async def forbidden(*args,**kwargs):
        raise AssertionError('physical control must not be consulted')
    monkeypatch.setattr(writer,'manager_snapshot',forbidden)
    monkeypatch.setattr(writer,'acquire_owner',forbidden)
    await manager.initialize(deadline=deadline())
    change = security_record(action=action)
    change['authorization']['tombstoned'] = action == 'tombstone'
    book = ledger()
    result = await getattr(manager,action)(change,ctx()['scope'],book,deadline=deadline())
    assert dict(result) == dict(intent_id='acl-2',operation=action,state='authority_committed',
        revision_id=None,generation_id=None,authority_committed=True,replica_complete=False,
        published=False,purge_complete=False)
    assert str(UUID(seen['apply'][0][2])) == seen['apply'][0][2]
    usage = book.snapshot()
    assert (usage['attempts'],usage['provider_calls'],usage['candidates'],usage['pending']) == (1,0,0,0)
    await manager.close()
    assert seen['closed'] == []
    with pytest.raises(ProviderUnavailable):
        await manager.update_authorization(security_record(),ctx()['scope'],ledger(),deadline=deadline())


@run_async
async def test_snapshot_precedes_callback_and_preserves_original_trusted_revision(monkeypatch):
    entered,release = asyncio.Event(),asyncio.Event()
    async def callback(*args):
        entered.set()
        await release.wait()
        return True
    manager,writer,seen = setup(monkeypatch,callback)
    await manager.initialize(deadline=deadline())
    change,scope = security_record(),ctx()['scope']
    task = asyncio.create_task(manager.update_authorization(change,scope,ledger(),deadline=deadline()))
    await entered.wait()
    change['authorization']['principal_ids'].clear()
    change['document_id'] = 'other'
    scope['authorization_revision'] = 'auth-forged'
    release.set()
    await task
    record,trusted,_,_ = seen['apply'][0]
    assert record['document_id'] == 'doc-1' and record['authorization']['principal_ids']
    assert trusted.authorization_revision == 'auth-1'
    assert seen['authorize'][0][1:] == ('docs','doc-1')


@pytest.mark.parametrize('failure',['action','tenant','scope','record','ledger','budget','not_ready'])
@run_async
async def test_invalid_admission_never_calls_authorizer_or_writer(monkeypatch,failure):
    manager,writer,seen = setup(monkeypatch)
    if failure != 'not_ready':
        await manager.initialize(deadline=deadline())
    change,scope,book = security_record(),ctx()['scope'],ledger()
    error = InvalidRequest
    if failure == 'action':
        change['action'] = 'tombstone'
        change['authorization']['tombstoned'] = True
    elif failure == 'tenant':
        scope['tenant_id'] = 'other';error = UnauthorizedScope
    elif failure == 'scope':scope['unexpected'] = True
    elif failure == 'record':change['unexpected'] = True
    elif failure == 'ledger':book = object()
    elif failure == 'budget':
        reservation = book.reserve(attempts=1);book.dispatch(reservation);book.reconcile(reservation)
        error = BudgetExhausted
    else:error = IndexNotReady
    with pytest.raises(error):
        await manager.update_authorization(change,scope,book,deadline=deadline())
    assert seen['authorize'] == [] and seen['apply'] == []


@pytest.mark.parametrize('allowed,error',[(False,UnauthorizedScope),(1,InvalidRequest),(None,InvalidRequest)])
@run_async
async def test_callback_requires_actual_boolean(monkeypatch,allowed,error):
    async def callback(*args):return allowed
    manager,writer,seen = setup(monkeypatch,callback)
    await manager.initialize(deadline=deadline())
    with pytest.raises(error):
        await manager.update_authorization(security_record(),ctx()['scope'],ledger(),deadline=deadline())
    assert seen['apply'] == []


@run_async
async def test_private_callback_failure_is_redacted(monkeypatch):
    async def callback(*args):raise RuntimeError('PRIVATE_SOURCE_AND_CREDENTIAL')
    manager,writer,seen = setup(monkeypatch,callback)
    await manager.initialize(deadline=deadline())
    with pytest.raises(ProviderUnavailable) as error:
        await manager.update_authorization(security_record(),ctx()['scope'],ledger(),deadline=deadline())
    assert 'PRIVATE' not in str(error.value) and seen['apply'] == []


@run_async
async def test_synchronous_callback_result_cannot_authorize_sql(monkeypatch):
    manager,writer,seen = setup(monkeypatch)
    manager._authorize_write = lambda *args: True
    await manager.initialize(deadline=deadline())
    with pytest.raises(InvalidRequest):
        await manager.update_authorization(security_record(),ctx()['scope'],ledger(),deadline=deadline())
    assert seen['apply'] == []


@pytest.mark.parametrize('cancel_kind',['caller','deadline','close'])
@run_async
async def test_suppressed_cancellation_never_authorizes_write_and_overlap_has_no_queue(monkeypatch,cancel_kind):
    entered,cancelled,release = asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def callback(*args):
        entered.set()
        try:await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
            return True
    monkeypatch.setattr(implementation,'_CLEANUP_SECONDS',.02)
    manager,writer,seen = setup(monkeypatch,callback)
    await manager.initialize(deadline=deadline())
    book = ledger(limit=asyncio.get_running_loop().time()+.02) if cancel_kind == 'deadline' else ledger()
    task = asyncio.create_task(manager.update_authorization(security_record(),ctx()['scope'],book,deadline=deadline()))
    await entered.wait()
    with pytest.raises(ProviderUnavailable):
        await manager.update_authorization(security_record(),ctx()['scope'],ledger(),deadline=deadline())
    close = None
    if cancel_kind == 'caller':task.cancel()
    elif cancel_kind == 'close':close = asyncio.create_task(manager.close())
    await cancelled.wait()
    if cancel_kind == 'close':
        with pytest.raises(ProviderUnavailable):await close
    else:
        with pytest.raises(asyncio.CancelledError if cancel_kind == 'caller' else DeadlineExceeded):await task
    assert manager._active is not None and seen['apply'] == []
    release.set()
    active = manager._active
    await asyncio.gather(active,return_exceptions=True)
    if cancel_kind == 'close':
        await asyncio.gather(task,return_exceptions=True)
    await asyncio.sleep(0)
    assert manager._active is None and seen['apply'] == [] and seen['closed'] == []


@run_async
async def test_historical_flags_are_preserved_and_each_retry_reauthorizes(monkeypatch):
    manager,writer,seen = setup(monkeypatch)
    await manager.initialize(deadline=deadline())
    async def historical(*args,**kwargs):
        return dict(state='complete',revision_id=None,generation_id=None,authority_committed=True,
                    replica_complete=True,purge_complete=False)
    monkeypatch.setattr(writer,'apply_security',historical)
    for _ in range(2):
        result = await manager.update_authorization(security_record(),ctx()['scope'],ledger(),deadline=deadline())
        assert result['replica_complete'] and not result['published'] and not result['purge_complete']
    assert len(seen['authorize']) == 2


def test_constructor_requires_exact_native_writer_and_callback(monkeypatch):
    with pytest.raises(InvalidRequest):QdrantSecurityManager(object(),lambda *args:True)
    manager,writer,seen = setup(monkeypatch)
    with pytest.raises(InvalidRequest):QdrantSecurityManager(writer,None)
    assert seen['initialize'] == 0
