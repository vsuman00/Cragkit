"""Committed recovery state-machine doubles; actual PG/Qdrant runs are separate."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from functools import wraps
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

import cragkit._qdrant_recovery as implementation
from cragkit._postgres_pool import PoolConfig, PoolResource
from cragkit._qdrant_reconciliation import (
    ExpectedProjection, QdrantReconciliationVerifier, ReconciliationReceipt, _RECEIPTS,
)
from cragkit._qdrant_recovery import PostgresQdrantRecovery, recovery_components, settlement_data
from cragkit._qdrant_supervisor import ManagedQdrantSupervisor, _Proof
from cragkit._qdrant_writer import PostgresQdrantWriter
from cragkit._qdrant_writer_contract import context
from cragkit.errors import (
    IndexNotReady, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope,
    UnsupportedCapability,
)
from test_qdrant_writer import FIXTURE, config, ctx


def run_async(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


async def dispatch_fixture(monkeypatch,tmp_path):
    """In-memory supervisor SQL/HTTP doubles; no physical fencing evidence."""
    import json
    from test_qdrant_writer import recovery_plan_writer
    from cragkit._qdrant_reconciliation import projection_data
    writer,supervisor,proof,projection,handle,document,physical,intent=await recovery_plan_writer(monkeypatch,tmp_path)
    resource=PoolResource(writer.resource.config)
    verifier=QdrantReconciliationVerifier(writer,supervisor)
    owner=PostgresQdrantRecovery(resource,config(),supervisor,verifier)
    owner._ready=True;owner._identity=MappingProxyType({key:physical[key] for key in ('instance_id','storage_identity','supervisor_id')})
    source=projection_data(projection,writer);journals={};members={}
    state={'sql':False,'puts':0,'reservations':0,'unknown':False,'ack_loss':False,'commit_losses':0}
    original_transport=ManagedQdrantSupervisor.transport_for.__get__(supervisor)
    monkeypatch.setattr(supervisor,'transport_for',original_transport)
    async def http(key,method,path,body,deadline,maximum,transport):
        assert not state['sql']
        if method=='PUT':
            state['puts']+=1
            incoming=json.loads(body)['points']
            merged={point['id']:point for point in handle.points};merged.update({point['id']:point for point in incoming})
            handle.points=list(merged.values())
            if state['unknown']:raise ProviderUnavailable()
            return 200,b'{"status":"ok","result":{"status":"completed"}}'
        return 200,await handle.request(method,path,body=body,deadline=deadline,max_response_bytes=maximum)
    monkeypatch.setattr(supervisor,'_http',http)
    async def blocked(connection,binding):
        assert dict(binding)==physical
        return dict(state='recovery_blocked',epoch=2,recovery_id=physical['recovery_id'])
    async def read_owner(connection,target):return ('instance-1',target.intent_id,target.owner_token,2)
    monkeypatch.setattr(owner,'_blocked',blocked);monkeypatch.setattr(owner,'_owner',read_owner)
    async def query(connection,sql,params=()):
        if sql.startswith('SELECT 1 FROM cragkit_qdrant.dispatch_journal'):return [(1,)] if state.get('foreign') else []
        if sql.startswith('SELECT action,state,manifest_sha256'):
            return [('stage',intent['state'],source['manifest_sha256'],source['revision_id'],source['generation_id'],
                source['authorization_revision'],source['mutation_epoch'],source['active_generation_id'],'instance-1')]
        if sql.startswith('SELECT dispatch_id,instance_id,sequence'):
            return [(key,row[9],row[0],row[1],row[2],row[3],row[4],row[5],row[7],row[8],row[6]) for key,row in journals.items()]
        if sql.startswith('SELECT dispatch_id,backend_namespace'):
            return [(key,config()['backend_namespace'],config()['physical_collection'],config()['collection_incarnation'],point)
                for key,points in members.items() for point in points]
        if sql.startswith('SELECT point_id::text FROM cragkit_qdrant.point_claims'):
            selected=params[3] if 'ANY' in sql else source['point_ids']
            return [(point,) for point in sorted(selected)]
        if sql.startswith('SELECT sequence,owner_token::text'):
            return [journals[params[-1]]] if params[-1] in journals else []
        if sql.startswith('SELECT point_id::text,backend_namespace'):
            return [(point,config()['backend_namespace'],config()['physical_collection'],config()['collection_incarnation'])
                for point in sorted(members.get(params[-1],[]))]
        if sql.startswith('SELECT completion_sha256'):
            return [(journals[params[-1]][8],)]
        raise AssertionError('Unexpected restricted dispatch SQL')
    monkeypatch.setattr(owner,'_query',query)
    class Connection:
        async def execute(self,sql,params):
            if sql.startswith('INSERT INTO cragkit_qdrant.dispatch_journal'):
                key=params[4];state['reservations']+=1
                if state.get('body_error'):raise ProviderUnavailable()
                journals[key]=(params[6],params[7],params[8],params[9],params[10],params[11],params[13],'reserved',None,params[5])
            elif sql.startswith('INSERT INTO cragkit_qdrant.dispatch_points'):
                members.setdefault(params[4],[]).append(params[-1])
            elif sql.startswith('UPDATE cragkit_qdrant.dispatch_journal'):
                row=list(journals[params[-1]]);row[7]=params[0];row[8]=params[1];journals[params[-1]]=tuple(row)
            else:raise AssertionError('Unexpected dispatch mutation')
    async def transaction(deadline,action):
        assert not state['sql'];state['sql']=True
        try:result=await action(Connection())
        finally:state['sql']=False
        if state['ack_loss'] and state['reservations'] and not state['commit_losses']:
            state['commit_losses']+=1;raise implementation._CommitUnknown()
        return result
    monkeypatch.setattr(owner,'_transaction',transaction)
    async def authorize(scope,collection,document_id):
        assert not state['sql'];return True
    return owner,proof,handle,state,journals,members,authorize,source


@pytest.mark.parametrize('missing',[0,1,2])
@run_async
async def test_recovery_dispatch_upserts_only_missing_original_claims(monkeypatch,tmp_path,missing):
    owner,proof,handle,state,journals,members,authorize,source=await dispatch_fixture(monkeypatch,tmp_path)
    handle.points=handle.points[missing:]
    result=await owner.dispatch_stage_recovery(proof,ctx(),authorize,deadline=asyncio.get_running_loop().time()+5)
    assert dict(result)=={'batches':int(missing>0),'points':missing}
    assert state['puts']==int(missing>0) and state['reservations']==int(missing>0)
    assert all(row[7]=='settled' and row[5] is True for row in journals.values())
    assert set(point for values in members.values() for point in values)==set(source['point_ids'][:missing])
    assert owner.supervisor._gate is False and owner._scoped_control is None


@run_async
async def test_recovery_dispatch_commit_ack_loss_confirms_without_http_resend(monkeypatch,tmp_path):
    owner,proof,handle,state,journals,_,authorize,_=await dispatch_fixture(monkeypatch,tmp_path)
    handle.points=[];state['ack_loss']=True
    result=await owner.dispatch_stage_recovery(proof,ctx(),authorize,deadline=asyncio.get_running_loop().time()+5)
    assert result['points']==2 and state['commit_losses']==1 and state['reservations']==1 and state['puts']==1
    assert all(row[7]=='settled' for row in journals.values())


@run_async
async def test_recovery_dispatch_unknown_send_stays_pending_and_cannot_retry_same_proof(monkeypatch,tmp_path):
    owner,proof,handle,state,journals,_,authorize,_=await dispatch_fixture(monkeypatch,tmp_path)
    handle.points=[];state['unknown']=True;deadline=asyncio.get_running_loop().time()+5
    with pytest.raises(ProviderUnavailable):await owner.dispatch_stage_recovery(proof,ctx(),authorize,deadline=deadline)
    assert state['puts']==1 and all(row[7]=='dispatched' for row in journals.values())
    state['unknown']=False
    with pytest.raises(ProviderUnavailable):await owner.dispatch_stage_recovery(proof,ctx(),authorize,deadline=deadline)
    assert state['puts']==1


@pytest.mark.parametrize('fault',['vector','denial','cancel'])
@run_async
async def test_recovery_dispatch_never_repairs_corruption_or_latched_callback_denial(monkeypatch,tmp_path,fault):
    owner,proof,handle,state,journals,_,authorize,_=await dispatch_fixture(monkeypatch,tmp_path)
    if fault=='vector':handle.points[0]['vector']['dense'][0]=-1
    else:handle.points=[]
    async def refused(*args):
        if fault=='cancel':
            task=asyncio.current_task();task.cancel()
            try:await asyncio.sleep(0)
            except asyncio.CancelledError:pass
            return True
        return False
    error=IntegrityViolation if fault=='vector' else asyncio.CancelledError if fault=='cancel' else UnauthorizedScope
    with pytest.raises(error):
        await owner.dispatch_stage_recovery(proof,ctx(),authorize if fault=='vector' else refused,deadline=asyncio.get_running_loop().time()+5)
    assert not journals and state['puts']==0 and state['reservations']==0


@run_async
async def test_recovery_dispatch_authorization_is_task_lifetime_and_issuer_bound(monkeypatch,tmp_path):
    owner,proof,handle,state,_,_,authorize,_=await dispatch_fixture(monkeypatch,tmp_path)
    handle.points=[];captured=[];original=owner._writer.project_recovery_dispatch
    async def capture(token,value,ids,*,deadline):
        captured.append(token)
        data=implementation.recovery_dispatch_authorization(token,owner._writer,deadline=deadline)
        assert data['context'].intent_id==ctx()['intent_id']
        with pytest.raises(InvalidRequest):implementation.recovery_dispatch_authorization(token,object(),deadline=deadline)
        with pytest.raises(InvalidRequest):implementation.recovery_dispatch_authorization(token,owner._writer,deadline=deadline+1)
        async def inherited():
            with pytest.raises(InvalidRequest):implementation.recovery_dispatch_authorization(token,owner._writer,deadline=deadline)
        await asyncio.create_task(inherited())
        return await original(token,value,ids,deadline=deadline)
    monkeypatch.setattr(owner._writer,'project_recovery_dispatch',capture)
    deadline=asyncio.get_running_loop().time()+5
    await owner.dispatch_stage_recovery(proof,ctx(),authorize,deadline=deadline)
    for token in captured:
        with pytest.raises(InvalidRequest):implementation.recovery_dispatch_authorization(token,owner._writer,deadline=deadline)
    with pytest.raises(InvalidRequest):implementation.recovery_dispatch_authorization(implementation._RecoveryDispatchAuthorization(),owner._writer,deadline=deadline)


@pytest.mark.parametrize('fault',['foreign','body_error'])
@run_async
async def test_recovery_dispatch_foreign_document_operation_and_body_failure_never_retry(monkeypatch,tmp_path,fault):
    owner,proof,handle,state,journals,_,authorize,_=await dispatch_fixture(monkeypatch,tmp_path)
    handle.points=[];state[fault]=True
    with pytest.raises(ProviderUnavailable):
        await owner.dispatch_stage_recovery(proof,ctx(),authorize,deadline=asyncio.get_running_loop().time()+5)
    assert state['puts']==0 and not journals
    assert state['reservations']==(1 if fault=='body_error' else 0)


@pytest.mark.parametrize('missing',[False,True])
@run_async
async def test_recovery_dispatch_sequence_exhaustion_does_not_mutate_or_hide_complete_readback(monkeypatch,tmp_path,missing):
    owner,proof,handle,state,journals,members,authorize,source=await dispatch_fixture(monkeypatch,tmp_path)
    for number in range(1,257):
        key='old-'+str(number)
        journals[key]=(number,ctx()['owner_token'],1,'credential-1','complete_point_upsert',False,'0'*64,'settled','0'*64,'instance-1')
        members[key]=[source['point_ids'][0]]
    if missing:handle.points=[]
    deadline=asyncio.get_running_loop().time()+5
    if missing:
        with pytest.raises(ProviderUnavailable):await owner.dispatch_stage_recovery(proof,ctx(),authorize,deadline=deadline)
    else:assert dict(await owner.dispatch_stage_recovery(proof,ctx(),authorize,deadline=deadline))=={'batches':0,'points':0}
    assert state['puts']==0 and state['reservations']==0


def test_recovery_components_returns_exact_original_verifier_without_io(monkeypatch, tmp_path):
    recovery, supervisor, database, _ = setup(monkeypatch, tmp_path)
    expected = recovery.verifier
    original_writer = recovery._writer
    assert recovery_components(recovery, original_writer, supervisor, config()) is expected
    assert recovery_components(recovery, original_writer, supervisor, recovery.config) is expected
    assert not recovery._ready and database.events == [] and database.connections == []


def test_recovery_components_rejects_copies_subclasses_and_wrong_graph(monkeypatch, tmp_path):
    recovery, supervisor, database, _ = setup(monkeypatch, tmp_path)
    writer = recovery._writer

    class Child(PostgresQdrantRecovery):
        pass

    child = Child(recovery.resource, config(), supervisor, recovery.verifier)
    for value in ({}, object(), copy_recovery(recovery),
                  object.__new__(PostgresQdrantRecovery), child):
        with pytest.raises(InvalidRequest):
            recovery_components(value, writer, supervisor, config())
    other_writer = PostgresQdrantWriter(writer.resource, config(), 'instance-1')
    other_supervisor = ManagedQdrantSupervisor(Path('/fixture/qdrant'), tmp_path / 'other',
                                              'instance-1', config())
    for expected_writer, expected_supervisor in ((other_writer, supervisor), (writer, other_supervisor)):
        with pytest.raises(InvalidRequest):
            recovery_components(recovery, expected_writer, expected_supervisor, config())
    assert database.events == [] and database.connections == []


def copy_recovery(value):
    from copy import copy
    return copy(value)


def test_recovery_components_config_shape_and_full_descriptor_identity(monkeypatch, tmp_path):
    recovery, supervisor, database, _ = setup(monkeypatch, tmp_path)
    with pytest.raises(InvalidRequest):
        recovery_components(recovery, recovery._writer, supervisor, {'unknown': True})
    changed = config()
    changed['physical_collection'] = 'different_collection'
    with pytest.raises(UnsupportedCapability):
        recovery_components(recovery, recovery._writer, supervisor, changed)
    mismatched = PostgresQdrantRecovery(recovery.resource, changed, supervisor, recovery.verifier)
    with pytest.raises(UnsupportedCapability):
        recovery_components(mismatched, recovery._writer, supervisor, changed)
    assert database.events == [] and database.connections == []


@pytest.mark.parametrize('field', ['resource', 'config', 'supervisor', 'verifier', '_writer'])
@run_async
async def test_recovery_constructor_drift_rejected_before_control_or_sql(monkeypatch, tmp_path, field):
    recovery, supervisor, database, _ = setup(monkeypatch, tmp_path)
    original_writer = recovery._writer
    original_resource = recovery.resource
    if field == 'resource':
        replacement = PoolResource(original_resource.config)
    elif field == 'config':
        replacement = recovery.config.model_copy()
    elif field == 'supervisor':
        replacement = ManagedQdrantSupervisor(Path('/fixture/qdrant'), tmp_path / 'other',
                                             'instance-1', config())
    elif field == 'verifier':
        replacement = QdrantReconciliationVerifier(original_writer, supervisor)
    else:
        replacement = PostgresQdrantWriter(original_writer.resource, config(), 'instance-1')
    setattr(recovery, field, replacement)
    with pytest.raises(InvalidRequest):
        recovery_components(recovery, original_writer, supervisor, config())
    with pytest.raises(InvalidRequest):
        await recovery.initialize(deadline=asyncio.get_running_loop().time() + 5)
    assert database.events == [] and database.connections == []
    assert original_resource._state == 'new' and not original_resource._driver_closed


@pytest.mark.parametrize('field', ['writer', 'supervisor'])
@run_async
async def test_original_verifier_public_binding_drift_is_not_accepted(monkeypatch, tmp_path, field):
    recovery, supervisor, database, _ = setup(monkeypatch, tmp_path)
    writer = recovery._writer
    setattr(recovery.verifier, field, object())
    with pytest.raises(InvalidRequest):
        recovery_components(recovery, writer, supervisor, config())
    with pytest.raises(InvalidRequest):
        await recovery.initialize(deadline=asyncio.get_running_loop().time() + 5)
    assert database.events == [] and database.connections == []


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def fetchall(self):
        return self.rows


class Database:
    def __init__(self):
        self.backend = None
        self.owner = dict(instance_id='instance-1', intent_id='intent-2',
                          owner_token=ctx()['owner_token'], backend_epoch=1)
        self.journals = [dict(dispatch_id='dispatch-old', credential_generation='credential-1',
            operation='complete_point_upsert', owner_token=ctx()['owner_token'], backend_epoch=1,
            instance_id='instance-1', state='unknown', completion_sha256=None, foreign=False)]
        self.points = {'dispatch-old': [FIXTURE['members'][0]['point_id']]}
        self.calls = []
        self.events = []
        self.connections = []
        self.active_leases = 0
        self.role = True
        self.history = list(implementation.EXPECTED_PUBLICATION_HISTORY)
        self.fingerprint = implementation.EXPECTED_PUBLICATION_CATALOG_FINGERPRINT
        self.catalog = [(True,)]
        self.guard_owner = [(True,)]
        self.metadata = {}
        self.guard_hook = None
        self.guard_error = None
        self.guard_rows = [(True,)]
        self.drop_next_commit = False
        self.after_lost_commit = None
        self.block_query = None
        self.block_updates = 0
        self.open_updates = 0
        self.rollback_entered = None
        self.rollback_gate = None
        self.physical_entered = None
        self.physical_pause = None
        self.physical_callback = None
        self.finish_callback = None
        self.control_state = {'active': None, 'facades': []}


class Connection:
    def __init__(self, database):
        self.db = database
        self.info = SimpleNamespace(transaction_status=0)
        self.closed = False

    def transaction(self):
        connection = self
        class Transaction:
            async def __aenter__(self):
                self.snapshot = deepcopy((connection.db.backend, connection.db.owner,
                                          connection.db.journals))
                self.members=deepcopy(getattr(connection.db,'security_members',None))
                connection.info.transaction_status = 2

            async def __aexit__(self, kind, error, traceback):
                if kind is not None:
                    if connection.db.rollback_entered is not None:
                        connection.db.rollback_entered.set()
                    if connection.db.rollback_gate is not None:
                        await connection.db.rollback_gate.wait()
                    connection.db.backend, connection.db.owner, connection.db.journals = self.snapshot
                    if self.members is not None:connection.db.security_members=self.members
                    connection.db.events.append('rollback')
                else:
                    connection.db.events.append('commit')
                    if connection.db.drop_next_commit:
                        connection.db.drop_next_commit = False
                        if connection.db.after_lost_commit is not None:
                            connection.db.after_lost_commit()
                        raise RuntimeError('PRIVATE_LOST_COMMIT_ACK')
                connection.info.transaction_status = 0
        return Transaction()

    async def execute(self, sql, params=None):
        db = self.db
        db.calls.append((sql, params))
        if sql=='SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ ONLY':self.readonly=True
        if (getattr(self,'readonly',False) and getattr(db,'cancel_confirmation_setup',False)
                and sql=='SET LOCAL search_path=pg_catalog'):
            asyncio.current_task().cancel()
        if sql.startswith('SET ') or 'set_config(' in sql:
            return Cursor([])
        if db.block_query is not None:
            await db.block_query.wait()
        if sql in db.metadata:return Cursor(db.metadata[sql])
        if sql in (implementation._SUPERVISOR_ROLE_SQL,implementation._SUPERVISOR_SECURITY_GUARD_ROLE_SQL):
            return Cursor([(db.role,)])
        if sql == implementation._HISTORY_SQL:
            return Cursor(db.history)
        if sql in (implementation._PUBLICATION_CATALOG_SQL,implementation._ATTESTATION_CATALOG_SQL,
                   implementation._SECURITY_GUARD_CATALOG_SQL):
            return Cursor(db.catalog)
        if sql == implementation._SECURITY_GUARD_OWNER_SQL:return Cursor(db.guard_owner)
        if sql == implementation._CATALOG_FINGERPRINT_SQL:
            return Cursor([(db.fingerprint,)])
        if sql.startswith('SELECT true FROM cragkit_qdrant.lock_current_security('):
            db.events.append('security_guard')
            if db.guard_hook is not None:await db.guard_hook(self,params)
            if db.guard_error is not None:raise db.guard_error
            return Cursor(db.guard_rows)
        if sql.startswith('SELECT instance_id FROM cragkit_qdrant.backend_instances'):
            return Cursor([] if db.backend is None else [('instance-1',)])
        if sql.startswith('INSERT INTO cragkit_qdrant.backend_instances'):
            db.backend = dict(zip(('instance_id', 'backend_namespace', 'storage_identity',
                                  'supervisor_id'), params, strict=True))
            db.backend.update(epoch=1, state='open', recovery_id=None)
            return Cursor([])
        if sql.startswith('SELECT backend_namespace,storage_identity'):
            return Cursor([] if db.backend is None else [tuple(
                db.backend[field] for field in implementation._BACKEND_FIELDS)])
        if sql.startswith('UPDATE cragkit_qdrant.backend_instances'):
            if "state='recovery_blocked'" in sql:
                db.backend.update(epoch=params[0], recovery_id=params[1], state='recovery_blocked')
                db.block_updates += 1
            else:
                db.backend.update(state='open', recovery_id=None)
                db.open_updates += 1
            return Cursor([])
        if sql.startswith('SELECT instance_id,intent_id,owner_token::text,backend_epoch'):
            return Cursor([tuple(db.owner[field] for field in
                ('instance_id', 'intent_id', 'owner_token', 'backend_epoch'))])
        if sql.startswith('UPDATE cragkit_qdrant.document_owners'):
            db.owner['backend_epoch'] = params[0]
            return Cursor([])
        if sql.startswith('SELECT action,manifest_sha256,revision_id,generation_id'):
            return Cursor([('stage', FIXTURE['intent']['manifest_sha256'], 'rev-2', 'gen-2')])
        if sql.startswith('SELECT action,instance_id,manifest_sha256,revision_id,generation_id'):
            return Cursor([db.security_stage])
        if sql.startswith('SELECT action,state,manifest_sha256,revision_id,generation_id,expected_authorization_revision'):
            return Cursor([db.security_owner_intent])
        if sql.startswith('SELECT action,payload_sha256,authority_committed,instance_id'):
            return Cursor([db.security_fence])
        if sql.startswith('SELECT dispatch_id,instance_id,sequence,owner_token::text,backend_epoch,credential_generation,operation,recovery,state'):
            return Cursor([tuple(row[field] for field in ('dispatch_id','instance_id','sequence','owner_token','backend_epoch',
                'credential_generation','operation','recovery','state','completion_sha256','request_sha256')) for row in db.journals if not row['foreign']])
        if sql.startswith('SELECT point_id::text FROM cragkit_qdrant.point_claims'):
            selected=params[3] if 'ANY' in sql else db.security_claims
            return Cursor([(point,) for point in sorted(selected) if point in db.security_claims])
        if sql.startswith('SELECT sequence,owner_token::text,backend_epoch,credential_generation,operation,recovery,request_sha256,state,completion_sha256,instance_id'):
            return Cursor([tuple(row[field] for field in ('sequence','owner_token','backend_epoch','credential_generation','operation','recovery',
                'request_sha256','state','completion_sha256','instance_id')) for row in db.journals if row['dispatch_id']==params[-1]])
        if sql.startswith('SELECT point_id::text,backend_namespace,physical_collection,collection_incarnation'):
            return Cursor(sorted((row[4],row[1],row[2],row[3]) for row in db.security_members if row[0]==params[-1]))
        if sql.startswith('INSERT INTO cragkit_qdrant.dispatch_journal'):
            if getattr(db,'drop_dispatch_commit',False):
                db.drop_next_commit=True;db.drop_dispatch_commit=False
            db.journals.append(dict(dispatch_id=params[4],instance_id=params[5],sequence=params[6],owner_token=params[7],
                backend_epoch=params[8],credential_generation=params[9],operation=params[10],recovery=params[11],request_sha256=params[13],
                state='reserved',completion_sha256=None,foreign=False))
            return Cursor([])
        if sql.startswith('INSERT INTO cragkit_qdrant.dispatch_points'):
            db.security_members.append((params[4],params[5],params[6],params[7],params[8]));return Cursor([])
        if sql.startswith('SELECT completion_sha256 FROM cragkit_qdrant.dispatch_journal'):
            return Cursor([(row['completion_sha256'],) for row in db.journals if row['dispatch_id']==params[-1]])
        if sql.startswith('SELECT dispatch_id FROM cragkit_qdrant.dispatch_journal') and 'credential_generation=%s' in sql:
            return Cursor([(row['dispatch_id'],) for row in db.journals if not row['foreign']
                and row['credential_generation']==params[4] and row['dispatch_id']!=params[5] and row['state']!='settled'][:1])
        if sql.startswith('SELECT 1 FROM cragkit_qdrant.dispatch_journal'):
            return Cursor([(1,)] if any(row['foreign'] and row['state']!='settled' for row in db.journals) else [])
        if sql.startswith('SELECT '+implementation._SECURITY_JOURNAL_COLUMNS):
            if 'ANY' in sql and getattr(db,'confirmation_hook',None) is not None:
                await db.confirmation_hook(self)
            selected=[row for row in db.journals if not row['foreign'] and ('ANY' not in sql or row['dispatch_id'] in params[-1])]
            return Cursor([tuple(row[field] for field in ('dispatch_id','instance_id','sequence','owner_token','backend_epoch',
                'credential_generation','operation','recovery','request_sha256','created_xid','state','completion_sha256')) for row in selected])
        if sql.startswith('SELECT '+implementation._SECURITY_MEMBER_COLUMNS):
            return Cursor([row for row in db.security_members if 'ANY' not in sql or row[0] in params[-1]])
        if sql.startswith('SELECT dispatch_id,credential_generation'):
            return Cursor([tuple(row[field] for field in ('dispatch_id', 'credential_generation',
                'operation', 'owner_token', 'backend_epoch', 'instance_id')) for row in db.journals
                if not row['foreign'] and row['state'] != 'settled'])
        if sql.startswith('SELECT dispatch_id,point_id::text'):
            return Cursor([(dispatch, point, FIXTURE['physical']['backend_namespace'],
                FIXTURE['physical']['physical_collection'], FIXTURE['physical']['collection_incarnation'])
                for dispatch in params[-1] for point in db.points.get(dispatch, [])])
        if sql.startswith('UPDATE cragkit_qdrant.dispatch_journal'):
            if getattr(db,'failed_update',None)==params[-1]:return Cursor([])
            found = [row for row in db.journals if row['dispatch_id'] == params[-1]
                     and row['state'] != 'settled']
            for row in found:
                row.update(state=params[0] if sql.startswith('UPDATE cragkit_qdrant.dispatch_journal SET state=%s') else 'settled',
                           completion_sha256=params[1] if sql.startswith('UPDATE cragkit_qdrant.dispatch_journal SET state=%s') else params[0])
            return Cursor([(row['dispatch_id'],) for row in found])
        if sql.startswith('SELECT dispatch_id,state,completion_sha256'):
            return Cursor([(row['dispatch_id'], row['state'], row['completion_sha256'])
                for row in db.journals if row['dispatch_id'] in params[-1]])
        if sql.startswith('SELECT dispatch_id FROM cragkit_qdrant.dispatch_journal'):
            return Cursor([(row['dispatch_id'],) for row in db.journals
                if row['state'] != 'settled'][:1])
        raise AssertionError('Unexpected SQL')

    async def close(self):
        self.closed = True
        self.info.transaction_status = 4


def setup(monkeypatch, tmp_path):
    database = Database()
    pool_config = PoolConfig(host='localhost', dbname='fixture', user='fixture',
        sslrootcert=Path('/fixture/ca'), passfile=Path('/fixture/pass'), max_size=1)
    sup_resource = PoolResource(pool_config)
    writer_resource = PoolResource(pool_config)
    @asynccontextmanager
    async def lease(self, *, deadline):
        if not database.connections or database.connections[-1].closed:
            database.connections.append(Connection(database))
        database.active_leases += 1
        try:
            yield database.connections[-1]
        finally:
            database.active_leases -= 1
    monkeypatch.setattr(PoolResource, 'lease', lease)
    writer = PostgresQdrantWriter(writer_resource, config(), 'instance-1')
    supervisor = ManagedQdrantSupervisor(Path('/fixture/qdrant'), tmp_path/'controller',
                                         'instance-1', config())
    supervisor._initialized = True
    supervisor._owned = (1, 2)
    supervisor._epoch = 1
    supervisor._key = 'PRIVATE_KEY'
    supervisor._credential_generation = 'credential-1'
    supervisor._gate = True
    supervisor._storage_id = 'storage-1'
    supervisor._supervisor_id = 'supervisor-1'
    supervisor._process = SimpleNamespace(returncode=None)
    monkeypatch.setattr(supervisor, '_assert_owner', lambda: None)
    verifier = QdrantReconciliationVerifier(writer, supervisor)
    async def validate(projection, *, deadline):
        assert database.active_leases == 0
        database.events.append('fresh_projection')
    monkeypatch.setattr(writer, 'validate_projection', validate)
    async def physical_recovery(request, *, deadline):
        assert database.active_leases == 0
        assert database.backend['state'] == 'recovery_blocked'
        assert database.backend['epoch'] == request['new_epoch']
        assert database.events[-1] == 'commit'
        if database.physical_entered is not None:
            database.physical_entered.set()
        if database.physical_pause is not None:
            await database.physical_pause.wait()
        database.events.append('physical_fence')
        supervisor._epoch = request['new_epoch']
        supervisor._gate = False
        supervisor._sealed = False
        supervisor._barrier = None
        supervisor._barriers.clear()
        supervisor._proofs.clear()
        supervisor._credential_generation = 'credential-' + str(database.events.count('physical_fence')+1)
        proof = _Proof()
        physical = {**request, 'instance_id': 'instance-1', 'storage_identity': 'storage-1',
            'supervisor_id': 'supervisor-1', 'credential_generation': supervisor._credential_generation}
        supervisor._proofs[proof] = physical
        supervisor._recovery = {**request, 'proof': proof}
        return proof
    database.physical_callback = physical_recovery
    original_block = supervisor.block_ordinary
    original_seal = supervisor.seal_recovery
    database.finish_callback = supervisor.finish_recovery
    state = database.control_state
    class ScopedControl:
        def __init__(self, token):
            self.token = token

        def check(self):
            if state['active'] is not self.token:
                raise ProviderUnavailable()

        def block_ordinary(self):
            self.check()
            original_block()

        async def recover(self, request, *, deadline):
            self.check()
            return await database.physical_callback(request, deadline=deadline)

        async def seal_recovery(self, proof, *, deadline):
            self.check()
            return await original_seal(proof, deadline=deadline)

        def finish_recovery(self, barrier, token, *, deadline):
            self.check()
            database.finish_callback(barrier, token, deadline=deadline)

    @asynccontextmanager
    async def control_session():
        if state['active'] is not None:
            raise ProviderUnavailable()
        token = object()
        scoped = ScopedControl(token)
        state['active'] = token
        state['facades'].append(scoped)
        database.events.append('scope_acquire')
        try:
            yield scoped
        finally:
            state['active'] = None
            database.events.append('scope_release')

    def raw_block():
        if state['active'] is not None:
            raise ProviderUnavailable()
        original_block()

    async def raw_recover(request, *, deadline):
        if state['active'] is not None:
            raise ProviderUnavailable()
        return await database.physical_callback(request, deadline=deadline)

    async def raw_seal(proof, *, deadline):
        if state['active'] is not None:
            raise ProviderUnavailable()
        return await original_seal(proof, deadline=deadline)

    def raw_finish(barrier, token, *, deadline):
        if state['active'] is not None:
            raise ProviderUnavailable()
        database.finish_callback(barrier, token, deadline=deadline)

    monkeypatch.setattr(supervisor, 'control_session', control_session, raising=False)
    monkeypatch.setattr(supervisor, 'block_ordinary', raw_block)
    monkeypatch.setattr(supervisor, 'recover', raw_recover)
    monkeypatch.setattr(supervisor, 'seal_recovery', raw_seal)
    monkeypatch.setattr(supervisor, 'finish_recovery', raw_finish)
    control = PostgresQdrantRecovery(sup_resource, config(), supervisor, verifier)
    def receipt(proof):
        value = ReconciliationReceipt()
        data = MappingProxyType({'context': context(ctx()), 'projection': ExpectedProjection(),
            'physical_binding': supervisor.recovery_binding(proof),
            'manifest_sha256': FIXTURE['intent']['manifest_sha256'], 'revision_id': 'rev-2',
            'generation_id': 'gen-2', 'point_ids': tuple(row['point_id'] for row in FIXTURE['members']),
            'readback_sha256': 'a'*64})
        _RECEIPTS[value] = (verifier, proof, data)
        return value
    return control, supervisor, database, receipt


@run_async
async def test_durable_block_physical_fence_retired_settlement_and_private_open(monkeypatch, tmp_path):
    control, supervisor, db, receipt = setup(monkeypatch, tmp_path)
    deadline = asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    proof = await control.recover('recovery-1', deadline=deadline)
    assert db.events.index('commit') < db.events.index('physical_fence')
    owner = await control.advance_owner(proof, ctx(), deadline=deadline)
    assert owner['owner_token'] == ctx()['owner_token'] and owner['backend_epoch'] == 2
    assert set(owner) == {'owner_token', 'backend_epoch'}
    result = await control.settle_retired(proof, receipt(proof), deadline=deadline)
    assert result == {'settled_count': 1} and db.journals[0]['state'] == 'settled'
    assert 'fresh_projection' in db.events
    assert await control.reopen(proof, deadline=deadline) == {'state': 'open', 'epoch': 2}
    assert db.backend['state'] == 'open' and supervisor._gate and not supervisor._sealed
    assert db.active_leases == 0


def schema_profile(db, profile):
    db.history=list({2:implementation.EXPECTED_PUBLICATION_HISTORY,
                     3:implementation.EXPECTED_ATTESTATION_HISTORY,
                     4:implementation.EXPECTED_SECURITY_GUARD_HISTORY}[profile])
    db.fingerprint={2:implementation.EXPECTED_PUBLICATION_CATALOG_FINGERPRINT,
                    3:implementation.EXPECTED_ATTESTATION_CATALOG_FINGERPRINT,
                    4:implementation.EXPECTED_SECURITY_GUARD_CATALOG_FINGERPRINT}[profile]


def test_profile4_supervisor_role_is_exactly_the_legacy_map_plus_one_guard_execute():
    addition="p.oid IS NOT DISTINCT FROM to_regprocedure('"+implementation._SECURITY_GUARD_SIGNATURE+"') OR\n   "
    assert implementation._SUPERVISOR_SECURITY_GUARD_ROLE_SQL.count(addition)==1
    assert implementation._SUPERVISOR_SECURITY_GUARD_ROLE_SQL.replace(addition,'')==implementation._SUPERVISOR_ROLE_SQL
    assert 'lock_current_security' not in implementation._SUPERVISOR_ROLE_SQL


@pytest.mark.parametrize('profile',[2,3,4])
@run_async
async def test_exact_recovery_profiles_preserve_retired_settlement_and_resource_lifetime(monkeypatch,tmp_path,profile):
    control, supervisor, db, receipt = setup(monkeypatch,tmp_path)
    schema_profile(db,profile)
    deadline=asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    assert control._schema_profile==profile and control._ready
    proof=await control.recover('recovery-1',deadline=deadline)
    db.calls.clear()
    await control.advance_owner(proof,ctx(),deadline=deadline)
    calls=[sql for sql,_ in db.calls]
    binding=next(index for index,sql in enumerate(calls) if "set_config('cragkit_qdrant.backend_instance_id'" in sql)
    assert calls.index(implementation._HISTORY_SQL)<binding
    role=implementation._SUPERVISOR_SECURITY_GUARD_ROLE_SQL if profile==4 else implementation._SUPERVISOR_ROLE_SQL
    assert calls.index(role)<binding
    if profile==4:
        for metadata in (implementation._SECURITY_GUARD_CATALOG_SQL,
                         implementation._CATALOG_FINGERPRINT_SQL,implementation._SECURITY_GUARD_OWNER_SQL):
            assert calls.index(metadata)<calls.index(role)
    assert not any(sql.startswith('SELECT cragkit_qdrant.lock_current_security(') for sql in calls)
    assert await control.settle_retired(proof,receipt(proof),deadline=deadline)=={'settled_count':1}
    assert db.active_leases==0 and control._scoped_control is None


@pytest.mark.parametrize('drift',['owner','login','fifth','body','definer','downgrade','role'])
@run_async
async def test_profile4_metadata_drift_blocks_owner_advance_before_backend_binding_then_restores(monkeypatch,tmp_path,drift):
    control, supervisor, db, _ = setup(monkeypatch,tmp_path)
    schema_profile(db,4);deadline=asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    proof=await control.recover('recovery-1',deadline=deadline)
    before=deepcopy(db.owner)
    if drift=='owner':db.guard_owner=[(False,)]
    elif drift in ('login','definer'):db.catalog=[(False,)]
    elif drift=='fifth':db.history.append(('0005_unknown','a'*64))
    elif drift=='body':db.fingerprint='b'*64
    elif drift=='downgrade':schema_profile(db,3)
    else:db.role=False
    db.calls.clear()
    with pytest.raises(UnauthorizedScope if drift=='role' else UnsupportedCapability):
        await control.advance_owner(proof,ctx(),deadline=deadline)
    assert db.owner==before
    assert all("set_config('cragkit_qdrant.backend_instance_id'" not in sql
               and not sql.startswith('UPDATE ') for sql,_ in db.calls)
    if drift=='definer':
        assert implementation._SUPERVISOR_SECURITY_GUARD_ROLE_SQL not in [sql for sql,_ in db.calls]
    schema_profile(db,4);db.catalog=db.guard_owner=[(True,)];db.role=True
    assert (await control.advance_owner(proof,ctx(),deadline=deadline))['backend_epoch']==2
    assert db.active_leases==0


@pytest.mark.parametrize('initial',[2,3])
@run_async
async def test_live_upgrade_is_explicit_and_failed_reinitialization_never_downgrades_four(monkeypatch,tmp_path,initial):
    control, supervisor, db, _ = setup(monkeypatch,tmp_path)
    schema_profile(db,initial);deadline=asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    schema_profile(db,4)
    with pytest.raises(UnsupportedCapability):await control.recover('recovery-1',deadline=deadline)
    assert db.block_updates==0 and 'physical_fence' not in db.events
    await control.initialize(deadline=deadline)
    assert control._schema_profile==4
    schema_profile(db,3)
    with pytest.raises(UnsupportedCapability):await control.initialize(deadline=deadline)
    assert not control._ready
    with pytest.raises(IndexNotReady):await control.recover('recovery-1',deadline=deadline)
    schema_profile(db,4)
    await control.initialize(deadline=deadline)
    assert control._ready and control._schema_profile==4


@pytest.mark.parametrize('query,rows',[
    ('_SECURITY_GUARD_OWNER_SQL',[(1,)]), ('_SECURITY_GUARD_OWNER_SQL',[]),
    ('_SECURITY_GUARD_OWNER_SQL',[[True]]), ('_SECURITY_GUARD_CATALOG_SQL',[(True,),(True,)]),
    ('_SECURITY_GUARD_CATALOG_SQL',[(1,)]),
    ('_CATALOG_FINGERPRINT_SQL',[(implementation.EXPECTED_SECURITY_GUARD_CATALOG_FINGERPRINT.encode(),)]),
    ('_HISTORY_SQL',list(implementation.EXPECTED_SECURITY_GUARD_HISTORY)+[('0005_extra','a'*64)]),
])
@run_async
async def test_profile4_malformed_metadata_fails_before_binding_or_registration(monkeypatch,tmp_path,query,rows):
    control,supervisor,db,_=setup(monkeypatch,tmp_path)
    schema_profile(db,4);db.metadata[getattr(implementation,query)]=rows
    with pytest.raises(UnsupportedCapability):
        await control.initialize(deadline=asyncio.get_running_loop().time()+5)
    assert not control._ready and db.backend is None
    assert all("set_config('cragkit_qdrant.backend_instance_id'" not in sql for sql,_ in db.calls)


@run_async
async def test_profile4_initialization_lost_commit_confirms_once_without_second_insert(monkeypatch,tmp_path):
    control,supervisor,db,_=setup(monkeypatch,tmp_path)
    schema_profile(db,4);db.drop_next_commit=True
    await control.initialize(deadline=asyncio.get_running_loop().time()+5)
    assert control._ready and control._schema_profile==4
    assert sum(sql.startswith('INSERT INTO cragkit_qdrant.backend_instances') for sql,_ in db.calls)==1
    assert sum(sql==implementation._SECURITY_GUARD_OWNER_SQL for sql,_ in db.calls)==2
    assert all(connection.closed or connection.info.transaction_status==0 for connection in db.connections)


@run_async
async def test_lost_initialization_commit_cannot_change_profile_before_confirmation_binding(monkeypatch,tmp_path):
    control,supervisor,db,_=setup(monkeypatch,tmp_path)
    schema_profile(db,3);db.drop_next_commit=True
    db.after_lost_commit=lambda:schema_profile(db,4)
    with pytest.raises(UnsupportedCapability):
        await control.initialize(deadline=asyncio.get_running_loop().time()+5)
    assert not control._ready
    assert sum(sql.startswith('INSERT INTO cragkit_qdrant.backend_instances') for sql,_ in db.calls)==1
    assert sum("set_config('cragkit_qdrant.backend_instance_id'" in sql for sql,_ in db.calls)==1
    assert sum(sql==implementation._HISTORY_SQL for sql,_ in db.calls)==2


async def guarded_fixture(monkeypatch,tmp_path):
    """Genuine nominal proof/receipt registries over explicit SQL/HTTP doubles."""
    from test_qdrant_security_verification import setup as security_setup
    import cragkit._qdrant_writer as writer_module
    security_verifier,writer,supervisor,proof,owner,target,state,writer_connections,handle = await security_setup(monkeypatch,tmp_path)
    db=Database();schema_profile(db,4)
    db.backend=dict(backend_namespace=config()['backend_namespace'],storage_identity='storage-1',
                    supervisor_id='supervisor-1',epoch=2,state='recovery_blocked',recovery_id='fixture-recovery')
    db.owner=dict(instance_id='instance-1',intent_id=owner['intent_id'],owner_token=owner['owner_token'],backend_epoch=2)
    resource=PoolResource(writer.resource.config)
    recovery=PostgresQdrantRecovery(resource,config(),supervisor,QdrantReconciliationVerifier(writer,supervisor))
    recovery._ready=True;recovery._schema_profile=4;recovery._security_guard_admitted=True
    recovery._identity=MappingProxyType(dict(instance_id='instance-1',storage_identity='storage-1',supervisor_id='supervisor-1'))
    writer._schema_profile=4;writer._security_guard_admitted=True
    state['allow_nonlocking']=True
    original_lease=PoolResource.lease
    @asynccontextmanager
    async def lease(self,*,deadline):
        if self is writer.resource:
            async with original_lease(self,deadline=deadline) as connection:
                connection.history=list(writer_module.EXPECTED_SECURITY_GUARD_HISTORY)
                connection.hash=writer_module.EXPECTED_SECURITY_GUARD_CATALOG_FINGERPRINT
                yield connection
        elif self is resource:
            connection=Connection(db);db.connections.append(connection);db.active_leases+=1
            try:yield connection
            finally:db.active_leases-=1
        else:raise AssertionError('unregistered fixture resource')
    monkeypatch.setattr(PoolResource,'lease',lease)
    return recovery,security_verifier,writer,supervisor,proof,owner,target,state,db,writer_connections


@run_async
async def test_guarded_driver_uses_exact_sql_receipt_and_full_nonlocking_graph(monkeypatch,tmp_path):
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=await guarded_fixture(monkeypatch,tmp_path)
    captures=[];original=implementation.validate_guarded_security_projection
    async def inspect(actual_writer,token,projection,*,deadline):
        bound=implementation.security_guard_binding(token,actual_writer,projection,deadline=deadline)
        assert set(bound)=={'context','owner_context','document'} and set(bound['document'])==set(implementation._DOCUMENT_FIELDS)
        with pytest.raises(TypeError):bound['document']['mutation_epoch']=99
        assert bound['owner_context'].intent_id==owner['intent_id']
        with pytest.raises(InvalidRequest):implementation.security_guard_binding(token,object(),projection,deadline=deadline)
        with pytest.raises(InvalidRequest):implementation.security_guard_binding(token,actual_writer,object(),deadline=deadline)
        with pytest.raises(InvalidRequest):implementation.security_guard_binding(token,actual_writer,projection,deadline=deadline+1)
        async def wrong_task():
            with pytest.raises(InvalidRequest):implementation.security_guard_binding(token,actual_writer,projection,deadline=deadline)
        await asyncio.create_task(wrong_task())
        captures.append((token,projection))
        await original(actual_writer,token,projection,deadline=deadline)
    monkeypatch.setattr(implementation,'validate_guarded_security_projection',inspect)
    before=len(state['loads'])
    assert await implementation.validate_security_guarded(recovery,verifier,proof,owner,target,
        deadline=asyncio.get_running_loop().time()+5) is None
    assert len(state['loads'])==before+9  # Three generations, initial/final locked read + guarded read.
    assert state['document_locks'][-3:]==[True,True,False]
    statements=[(sql,args) for sql,args in db.calls if sql.startswith('SELECT true FROM ')]
    assert len(statements)==1
    sql,args=statements[0]
    assert sql=='SELECT true FROM cragkit_qdrant.lock_current_security('+','.join(['%s']*22)+')'
    assert len(args)==22 and args[:6]==('instance-1',config()['backend_namespace'],'storage-1','supervisor-1','fixture-recovery',2)
    assert args[6:12]==('tenant-a','docs','doc-1',owner['intent_id'],owner['owner_token'],target['intent_id'])
    assert args[14:18]==('auth-2',2,list(state['document']['principal_ids']),list(state['document']['grant_ids']))
    assert not any(sql.startswith(('INSERT ','UPDATE ','DELETE ')) for sql,_ in db.calls)
    assert recovery._active is None and recovery._guard_scope is None and recovery._guard_transaction is None
    assert writer._active is None and not writer._closed and not supervisor._closed
    token,projection=captures[0]
    with pytest.raises((InvalidRequest,ProviderUnavailable)):
        implementation.security_guard_binding(token,writer,projection,deadline=asyncio.get_running_loop().time()+1)


@pytest.mark.parametrize('code,error',[('42501',UnauthorizedScope),('22023',UnsupportedCapability),
    ('23514',UnauthorizedScope),('08006',ProviderUnavailable)])
@run_async
async def test_only_actual_guard_invocation_maps_native_sqlstates(monkeypatch,tmp_path,code,error):
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=await guarded_fixture(monkeypatch,tmp_path)
    failure=RuntimeError('PRIVATE SQL CONNECTION');failure.sqlstate=code;db.guard_error=failure
    with pytest.raises(error) as caught:
        await implementation.validate_security_guarded(recovery,verifier,proof,owner,target,
            deadline=asyncio.get_running_loop().time()+5)
    assert 'PRIVATE' not in str(caught.value)
    assert state['document_locks'][-2:]==[True,True]
    assert db.events==['security_guard','rollback'] and db.active_leases==0


@pytest.mark.parametrize('fault',['ack','raw_claim','raw_replay','loader_corrupt','authority','connection_loss'])
@run_async
async def test_guarded_full_graph_refuses_late_corruption_and_connection_loss(monkeypatch,tmp_path,fault):
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=await guarded_fixture(monkeypatch,tmp_path)
    async def corrupt(connection,args):
        if fault=='ack':db.guard_rows=[(1,)]
        elif fault=='raw_claim':state['claims'].append(state['claims'][0])
        elif fault=='raw_replay':state['replays'].pop()
        elif fault=='loader_corrupt':state['graph_error']=True
        elif fault=='authority':state['document']['mutation_epoch']+=1
        else:connection.info.transaction_status=4
    db.guard_hook=corrupt
    expected=ProviderUnavailable if fault=='connection_loss' else UnauthorizedScope if fault=='authority' else IntegrityViolation
    with pytest.raises(expected):
        await implementation.validate_security_guarded(recovery,verifier,proof,owner,target,
            deadline=asyncio.get_running_loop().time()+5)
    assert 'commit' not in db.events and recovery._guard_scope is None


@run_async
async def test_driver_rejects_wrong_scope_profile_and_unregistered_dependencies_before_io(monkeypatch,tmp_path):
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=await guarded_fixture(monkeypatch,tmp_path)
    before=len(connections)
    wrong=deepcopy(owner);wrong['scope']['authorization_revision']='other'
    for actual,security_verifier,old,current in [(object(),verifier,owner,target),(recovery,object(),owner,target),
        (recovery,verifier,wrong,target),(recovery,verifier,target,target)]:
        with pytest.raises(InvalidRequest):
            await implementation.validate_security_guarded(actual,security_verifier,proof,old,current,
                deadline=asyncio.get_running_loop().time()+5)
    recovery._schema_profile=3
    with pytest.raises(UnsupportedCapability):
        await implementation.validate_security_guarded(recovery,verifier,proof,owner,target,
            deadline=asyncio.get_running_loop().time()+5)
    assert db.calls==[] and len(connections)==before


@run_async
async def test_cancellation_on_guard_ack_never_admits_writer_or_commit(monkeypatch,tmp_path):
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=await guarded_fixture(monkeypatch,tmp_path)
    async def cancelled(connection,args):asyncio.current_task().cancel()
    db.guard_hook=cancelled
    with pytest.raises(asyncio.CancelledError):
        await implementation.validate_security_guarded(recovery,verifier,proof,owner,target,
            deadline=asyncio.get_running_loop().time()+5)
    assert state['document_locks'][-2:]==[True,True]
    assert 'commit' not in db.events and recovery._active is None and writer._active is None


@run_async
async def test_cancelled_noncooperative_graph_retains_actual_control_and_writer_ownership(monkeypatch,tmp_path):
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=await guarded_fixture(monkeypatch,tmp_path)
    recovery.resource.config=recovery.resource.config.model_copy(update={'release_timeout':.02})
    entered=asyncio.Event();release=asyncio.Event();cancelled=asyncio.Event()
    original=writer._security_graph
    async def delayed(connection,current,document):
        if not state['document_locks'][-1]:
            entered.set()
            while not release.is_set():
                try:await release.wait()
                except asyncio.CancelledError:cancelled.set()
        return await original(connection,current,document)
    monkeypatch.setattr(writer,'_security_graph',delayed)
    task=asyncio.create_task(implementation.validate_security_guarded(recovery,verifier,proof,owner,target,
        deadline=asyncio.get_running_loop().time()+5))
    await entered.wait();inner=recovery._active;guarded_connection=connections[-1]
    task.cancel();await cancelled.wait()
    with pytest.raises(asyncio.CancelledError):await task
    assert recovery._active is inner and writer._active is inner and recovery._scoped_control is not None
    assert recovery._closed and writer._closed
    with pytest.raises(ProviderUnavailable):
        async with supervisor.control_session():pytest.fail('active facade released early')
    with pytest.raises(ProviderUnavailable):await writer.inspect(target,deadline=asyncio.get_running_loop().time()+1)
    with pytest.raises(ProviderUnavailable):await recovery.close()
    release.set();await asyncio.gather(inner,return_exceptions=True)
    assert recovery._active is None and writer._active is None and recovery._guard_scope is None
    assert 'commit' not in db.events and guarded_connection.commits==0


async def settlement_fixture(monkeypatch,tmp_path):
    from cragkit._qdrant_writer_contract import stage_data
    values=await guarded_fixture(monkeypatch,tmp_path)
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=values
    graphs=[stage_data(plan) for plan in state['plans'].values()]
    first=graphs[0]
    db.security_stage=('stage','instance-1',first.manifest_encoding.sha256,
                       first.manifest.revision_id,first.manifest.generation_id)
    original_ids=tuple(member.point_id for member in first.manifest.members)
    all_ids=tuple(member.point_id for graph in graphs for member in graph.manifest.members)
    db.journals=[];db.security_members=[]
    for index,(kind,recovery_flag,points) in enumerate([
        ('reserved',False,original_ids),('unknown',True,all_ids),('dispatched',True,all_ids[:1]),
        ('settled',False,original_ids[:1])]):
        identity=f'security-old-{index}'
        db.journals.append(dict(dispatch_id=identity,instance_id='instance-1',sequence=index+1,
            owner_token=owner['owner_token'],backend_epoch=1,credential_generation='credential-2' if kind=='settled' else 'credential-1',
            operation='complete_point_upsert',recovery=recovery_flag,request_sha256=f'{index+1:064x}',
            created_xid=str(100+index),state=kind,completion_sha256='d'*64 if kind=='settled' else None,foreign=False))
        db.security_members.extend((identity,writer.config.backend_namespace,writer.config.physical_collection,
                                   writer.config.collection_incarnation,point) for point in points)
    return values


@run_async
async def test_security_settlement_reuses_guard_and_preserves_historical_completion_on_repeat(monkeypatch,tmp_path):
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=await settlement_fixture(monkeypatch,tmp_path)
    headers=deepcopy(db.journals);owner_before=deepcopy(db.owner);authority=deepcopy(state['document'])
    limit=asyncio.get_running_loop().time()+5
    result=await implementation.settle_security_guarded(recovery,verifier,proof,owner,target,deadline=limit)
    assert result=={'settled_count':3}
    with pytest.raises(TypeError):result['settled_count']=4
    completions=[row['completion_sha256'] for row in db.journals]
    assert len(set(completions[:3]))==1 and completions[3]=='d'*64
    assert all(row['state']=='settled' for row in db.journals)
    assert all({k:v for k,v in actual.items() if k not in ('state','completion_sha256')}==
               {k:v for k,v in original.items() if k not in ('state','completion_sha256')}
               for actual,original in zip(db.journals,headers,strict=True))
    assert await implementation.settle_security_guarded(recovery,verifier,proof,owner,target,deadline=limit)=={'settled_count':0}
    assert [row['completion_sha256'] for row in db.journals]==completions
    assert db.owner==owner_before and state['document']==authority and db.open_updates==0
    assert sum(sql.startswith('UPDATE cragkit_qdrant.dispatch_journal') for sql,_ in db.calls)==3
    assert db.active_leases==0 and recovery._active is None and supervisor._control_token is None


@pytest.mark.parametrize('fault,error',[
    ('current',ProviderUnavailable),('foreign',ProviderUnavailable),('missing',IntegrityViolation),
    ('duplicate_member',IntegrityViolation),('ordinary_other_generation',IntegrityViolation),
    ('physical',IntegrityViolation),('header_owner',IntegrityViolation),('sequence',IntegrityViolation),
    ('request',IntegrityViolation),('xid',IntegrityViolation),('operation',UnsupportedCapability),
    ('completion',IntegrityViolation),('overflow_headers',IntegrityViolation),('overflow_members',IntegrityViolation),
])
@run_async
async def test_security_settlement_validates_all_headers_and_raw_members_before_updates(monkeypatch,tmp_path,fault,error):
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=await settlement_fixture(monkeypatch,tmp_path)
    if fault=='current':db.journals[1]['credential_generation']='credential-2'
    elif fault=='foreign':db.journals.append({**db.journals[0],'dispatch_id':'foreign','foreign':True})
    elif fault=='missing':db.security_members=[row for row in db.security_members if row[0]!=db.journals[1]['dispatch_id']]
    elif fault=='duplicate_member':db.security_members.append(db.security_members[0])
    elif fault=='ordinary_other_generation':
        db.security_members[0]=(*db.security_members[0][:4],db.security_members[4][4])
    elif fault=='physical':db.security_members[0]=(db.security_members[0][0],'wrong',*db.security_members[0][2:])
    elif fault=='header_owner':db.journals[1]['owner_token']=target['owner_token']
    elif fault=='sequence':db.journals[1]['sequence']=True
    elif fault=='request':db.journals[1]['request_sha256']='not-a-digest'
    elif fault=='xid':db.journals[1]['created_xid']='001'
    elif fault=='operation':db.journals[1]['operation']='set_security_payload'
    elif fault=='completion':db.journals[1]['completion_sha256']='f'*64
    elif fault=='overflow_headers':db.journals*=65
    else:db.security_members=[db.security_members[0]]*2049
    before=deepcopy(db.journals)
    with pytest.raises(error):
        await implementation.settle_security_guarded(recovery,verifier,proof,owner,target,
            deadline=asyncio.get_running_loop().time()+5)
    assert db.journals==before
    assert all(not sql.startswith('UPDATE cragkit_qdrant.dispatch_journal') for sql,_ in db.calls)
    assert 'commit' not in db.events


@run_async
async def test_security_settlement_partial_update_failure_rolls_back_whole_exact_set(monkeypatch,tmp_path):
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=await settlement_fixture(monkeypatch,tmp_path)
    before=deepcopy(db.journals);db.failed_update=db.journals[1]['dispatch_id']
    with pytest.raises(IntegrityViolation):
        await implementation.settle_security_guarded(recovery,verifier,proof,owner,target,
            deadline=asyncio.get_running_loop().time()+5)
    assert db.journals==before and 'commit' not in db.events
    assert sum(sql.startswith('UPDATE cragkit_qdrant.dispatch_journal') for sql,_ in db.calls)==2


@run_async
async def test_security_settlement_lost_commit_confirms_exact_history_after_authority_changes(monkeypatch,tmp_path):
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=await settlement_fixture(monkeypatch,tmp_path)
    db.drop_next_commit=True
    def advanced():state['document'].update(authorization_revision='auth-after-commit',mutation_epoch=3)
    db.after_lost_commit=advanced
    assert await implementation.settle_security_guarded(recovery,verifier,proof,owner,target,
        deadline=asyncio.get_running_loop().time()+5)=={'settled_count':3}
    assert sum(sql.startswith('UPDATE cragkit_qdrant.dispatch_journal') for sql,_ in db.calls)==3
    assert sum(sql.startswith('SELECT true FROM cragkit_qdrant.lock_current_security(') for sql,_ in db.calls)==1
    assert len(state['document_locks'][-3:])==3 and state['document_locks'][-3:]==[True,True,False]
    readonly=next(index for index,(sql,_) in enumerate(db.calls) if sql.endswith('READ COMMITTED READ ONLY'))
    assert all('FOR UPDATE' not in sql and not sql.startswith(('UPDATE ','INSERT ','DELETE ')) for sql,_ in db.calls[readonly:])
    assert all('dispatch_id=ANY' in sql for sql,_ in db.calls[readonly:] if 'FROM cragkit_qdrant.dispatch_' in sql)
    assert recovery._security_confirmation is None and db.active_leases==0


@pytest.mark.parametrize('fault',['missing','partial','header','membership','digest'])
@run_async
async def test_lost_commit_confirmation_contradictions_do_not_replay_mutation(monkeypatch,tmp_path,fault):
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=await settlement_fixture(monkeypatch,tmp_path)
    db.drop_next_commit=True
    def changed():
        if fault=='missing':db.journals.pop(0)
        elif fault=='partial':db.journals[0].update(state='unknown',completion_sha256=None)
        elif fault=='header':db.journals[0]['request_sha256']='e'*64
        elif fault=='membership':db.security_members.pop(0)
        else:db.journals[0]['completion_sha256']='e'*64
    db.after_lost_commit=changed
    with pytest.raises(ProviderUnavailable):
        await implementation.settle_security_guarded(recovery,verifier,proof,owner,target,
            deadline=asyncio.get_running_loop().time()+5)
    assert sum(sql.startswith('UPDATE cragkit_qdrant.dispatch_journal') for sql,_ in db.calls)==3
    assert sum(sql.startswith('SELECT true FROM cragkit_qdrant.lock_current_security(') for sql,_ in db.calls)==1


@run_async
async def test_cancelled_confirmation_retains_real_control_until_actual_read_drains(monkeypatch,tmp_path):
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=await settlement_fixture(monkeypatch,tmp_path)
    recovery.resource.config=recovery.resource.config.model_copy(update={'release_timeout':.02})
    entered=asyncio.Event();release=asyncio.Event();cancelled=asyncio.Event();db.drop_next_commit=True
    async def held(connection):
        entered.set()
        while not release.is_set():
            try:await release.wait()
            except asyncio.CancelledError:cancelled.set()
    db.confirmation_hook=held
    task=asyncio.create_task(implementation.settle_security_guarded(recovery,verifier,proof,owner,target,
        deadline=asyncio.get_running_loop().time()+5))
    await entered.wait();inner=recovery._active;task.cancel();await cancelled.wait()
    with pytest.raises(asyncio.CancelledError):await task
    assert recovery._active is inner and recovery._scoped_control is not None and recovery._closed
    async def raw_control():
        async with supervisor.control_session():pytest.fail('confirmation control escaped')
    with pytest.raises(ProviderUnavailable):await raw_control()
    assert db.events.count('commit')==1  # The uncertain original commit, never a late confirmation.
    release.set();await asyncio.gather(inner,return_exceptions=True)
    assert recovery._active is None and recovery._security_confirmation is None
    assert db.events.count('commit')==1


@run_async
async def test_confirmation_setup_cancellation_submits_no_following_query_or_commit(monkeypatch,tmp_path):
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=await settlement_fixture(monkeypatch,tmp_path)
    db.drop_next_commit=True;db.cancel_confirmation_setup=True
    with pytest.raises(asyncio.CancelledError):
        await implementation.settle_security_guarded(recovery,verifier,proof,owner,target,
            deadline=asyncio.get_running_loop().time()+5)
    readonly=next(index for index,(sql,_) in enumerate(db.calls) if sql.endswith('READ COMMITTED READ ONLY'))
    assert [sql for sql,_ in db.calls[readonly:]]==[
        'SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ ONLY','SET LOCAL search_path=pg_catalog']
    assert db.events.count('commit')==1 and recovery._security_confirmation is None


async def security_dispatch_fixture(monkeypatch,tmp_path):
    import json
    from test_qdrant_reconciliation import Handle
    from cragkit._qdrant_writer_contract import stage_data
    from cragkit._qdrant_writer import security_projection_data
    values=await guarded_fixture(monkeypatch,tmp_path)
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=values
    projection=await writer.project_security(target,deadline=asyncio.get_running_loop().time()+5)
    source=security_projection_data(projection,writer)
    graph=stage_data(next(iter(state['plans'].values())))
    state['dispatch_backend']=(writer.config.backend_namespace,'storage-1','supervisor-1',2,'recovery_blocked','fixture-recovery')
    state['dispatch_owner']=(owner['owner_token'],owner['intent_id'],2,'instance-1')
    state['dispatch_stage']=('stage',graph.manifest_encoding.sha256,graph.manifest.revision_id,graph.manifest.generation_id,'instance-1')
    db.security_owner_intent=('stage','denied',graph.manifest_encoding.sha256,graph.manifest.revision_id,graph.manifest.generation_id,
                              'auth-1',1,None,'instance-1')
    db.security_fence=('update_authorization',source['intent_sha256'],True,'instance-1')
    db.security_claims=source['point_ids'];db.journals=[];db.security_members=[]
    handle=Handle([dict(id=point.point_id,payload=point.payload.model_dump(mode='json'),
        vector=dict(dense=list(point.dense.values),sparse=dict(indices=list(point.sparse.indices),values=list(point.sparse.values))))
        for point in source['points']])
    events=dict(puts=[],loss=False,advance=False,callbacks=0)
    async def http(key,method,path,body,limit,maximum,transport):
        assert db.active_leases==0
        if method=='PUT':
            points=json.loads(body)['points'];events['puts'].append(points)
            merged={point['id']:point for point in handle.points};merged.update({point['id']:point for point in points})
            handle.points=list(merged.values())
            if events['advance']:state['document']['authorization_revision']='superseded'
            if events['loss']:raise ProviderUnavailable()
            return 200,b'{"status":"ok","result":{"status":"completed"}}'
        return 200,await handle.request(method,path,body=body,deadline=limit,max_response_bytes=maximum)
    monkeypatch.setattr(supervisor,'_http',http)
    async def authorize(scope,collection,document):
        assert db.active_leases==0;events['callbacks']+=1;return True
    return values,source,handle,events,authorize


@pytest.mark.parametrize('mode',['missing','stale','mixed','noop'])
@run_async
async def test_security_dispatch_replays_only_sorted_missing_or_stale_current_points(monkeypatch,tmp_path,mode):
    values,source,handle,events,authorize=await security_dispatch_fixture(monkeypatch,tmp_path)
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=values
    ids=source['point_ids'];selected=[]
    if mode in ('missing','mixed'):
        handle.points=[point for point in handle.points if point['id']!=ids[0]];selected.append(ids[0])
    if mode in ('stale','mixed'):
        point=next(point for point in handle.points if point['id']==ids[-1]);point['payload']['authorization_revision']='auth-1';selected.append(ids[-1])
    result=await implementation.dispatch_security_recovery(recovery,proof,owner,target,authorize,
        deadline=asyncio.get_running_loop().time()+5)
    assert result==dict(batches=int(bool(selected)),points=len(selected))
    assert [point['id'] for batch in events['puts'] for point in batch]==sorted(selected)
    assert all(point['payload']['authorization_revision']=='auth-2' for batch in events['puts'] for point in batch)
    assert all(row['state']=='settled' and row['recovery'] is True for row in db.journals)
    assert len(db.journals)==int(bool(selected)) and db.owner['intent_id']==owner['intent_id']
    assert state['document']['authorization_revision']=='auth-2' and db.open_updates==0
    assert recovery._active is None and writer._active is None and supervisor._control_token is None


@pytest.mark.parametrize('fault,error',[('foreign',ProviderUnavailable),('current',ProviderUnavailable),
    ('slots',ProviderUnavailable),('budget',ProviderUnavailable),('corrupt',IntegrityViolation),
    ('extra',IntegrityViolation),('authorize_bool',InvalidRequest),('authorize_false',UnauthorizedScope)])
@run_async
async def test_security_dispatch_refusals_preserve_uncertainty_before_writes(monkeypatch,tmp_path,fault,error):
    from cragkit._qdrant_security_readback import SecurityReadbackBudget,_BUDGETS
    values,source,handle,events,authorize=await security_dispatch_fixture(monkeypatch,tmp_path)
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=values
    budget=None
    if fault in ('foreign','current','slots'):
        row=dict(dispatch_id='prior',instance_id='instance-1',sequence=256 if fault=='slots' else 1,
            owner_token=owner['owner_token'],backend_epoch=1,credential_generation='credential-2' if fault=='current' else 'credential-1',
            operation='complete_point_upsert',recovery=True,state='unknown',completion_sha256=None,request_sha256='a'*64,foreign=fault=='foreign')
        db.journals.append(row)
        db.security_members=[('prior',writer.config.backend_namespace,writer.config.physical_collection,writer.config.collection_incarnation,source['point_ids'][0])]
        handle.points=[]
    elif fault=='budget':budget=SecurityReadbackBudget();_BUDGETS[budget]=(8388608,0)
    elif fault=='corrupt':handle.points[0]['vector']['dense']=[-value for value in handle.points[0]['vector']['dense']]
    elif fault=='extra':
        extra=deepcopy(handle.points[0]);extra['id']='11111111-1111-5111-8111-111111111111';handle.points.append(extra)
    else:
        async def authorize(*args):return 1 if fault=='authorize_bool' else False
    before=deepcopy(db.journals)
    with pytest.raises(error):
        await implementation.dispatch_security_recovery(recovery,proof,owner,target,authorize,
            deadline=asyncio.get_running_loop().time()+5,budget=budget)
    assert db.journals==before and events['puts']==[]


@pytest.mark.parametrize('fault',['sql_ack','http_ack','authority'])
@run_async
async def test_security_dispatch_ack_loss_and_authority_races_never_replay_http(monkeypatch,tmp_path,fault):
    values,source,handle,events,authorize=await security_dispatch_fixture(monkeypatch,tmp_path)
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=values
    handle.points=[]
    db.drop_dispatch_commit=fault=='sql_ack';events['loss']=fault=='http_ack';events['advance']=fault=='authority'
    operation=implementation.dispatch_security_recovery(recovery,proof,owner,target,authorize,deadline=asyncio.get_running_loop().time()+5)
    if fault=='sql_ack':assert await operation==dict(batches=1,points=6)
    else:
        with pytest.raises(ProviderUnavailable if fault=='http_ack' else UnauthorizedScope):await operation
    assert len(events['puts'])==1 and len(db.journals)==1
    assert db.journals[0]['state']==('settled' if fault=='sql_ack' else 'unknown' if fault=='http_ack' else 'dispatched')
    assert (db.journals[0]['completion_sha256'] is not None)==(fault=='sql_ack')


@run_async
async def test_security_dispatch_authorizations_and_plans_are_nominal_and_expire(monkeypatch,tmp_path):
    import cragkit._qdrant_writer as writer_module
    values,source,handle,events,authorize=await security_dispatch_fixture(monkeypatch,tmp_path)
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=values
    handle.points=[];captured=[];original=writer.project_security_dispatch
    async def project(auth,ids,*,deadline):
        plan=await original(auth,ids,deadline=deadline);captured.append((auth,plan))
        with pytest.raises(InvalidRequest):writer_module.security_dispatch_plan_data(plan,object(),writer,deadline=deadline)
        with pytest.raises(InvalidRequest):writer_module.security_dispatch_plan_data(writer_module._RecoveryDispatchPlan(),auth,writer,deadline=deadline)
        return plan
    monkeypatch.setattr(writer,'project_security_dispatch',project)
    await implementation.dispatch_security_recovery(recovery,proof,owner,target,authorize,deadline=asyncio.get_running_loop().time()+5)
    auth,plan=captured[0]
    with pytest.raises(InvalidRequest):implementation.security_dispatch_authorization(auth,writer,deadline=asyncio.get_running_loop().time()+1)
    with pytest.raises(InvalidRequest):writer_module.security_dispatch_plan_data(plan,auth,writer,deadline=asyncio.get_running_loop().time()+1)


@run_async
async def test_security_dispatch_initial_source_cancellation_retains_actual_owner_until_drain(monkeypatch,tmp_path):
    values,source,handle,events,authorize=await security_dispatch_fixture(monkeypatch,tmp_path)
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=values
    recovery.resource.config=recovery.resource.config.model_copy(update={'release_timeout':.02})
    entered=asyncio.Event();release=asyncio.Event();cancelled=asyncio.Event();original=writer._document
    async def held(connection,value,**options):
        entered.set()
        while not release.is_set():
            try:await release.wait()
            except asyncio.CancelledError:cancelled.set()
        return await original(connection,value,**options)
    monkeypatch.setattr(writer,'_document',held)
    task=asyncio.create_task(implementation.dispatch_security_recovery(recovery,proof,owner,target,authorize,
        deadline=asyncio.get_running_loop().time()+5))
    await entered.wait();inner=recovery._active;task.cancel();await cancelled.wait()
    with pytest.raises(asyncio.CancelledError):await task
    assert recovery._active is inner and writer._active is inner and recovery._scoped_control is not None
    assert recovery._closed and writer._closed and db.journals==[]
    release.set();await asyncio.gather(inner,return_exceptions=True)
    assert recovery._active is None and writer._active is None and events['puts']==[]


@run_async
async def test_current_generation_refusal_is_atomic_until_same_identity_refence(monkeypatch, tmp_path):
    control, supervisor, db, receipt = setup(monkeypatch, tmp_path)
    deadline = asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    first = await control.recover('recovery-1', deadline=deadline)
    await control.advance_owner(first, ctx(), deadline=deadline)
    db.journals.append({**db.journals[0], 'dispatch_id': 'current',
                        'credential_generation': supervisor._credential_generation})
    db.points['current'] = [FIXTURE['members'][1]['point_id']]
    with pytest.raises(ProviderUnavailable):
        await control.settle_retired(first, receipt(first), deadline=deadline)
    assert all(row['state'] == 'unknown' for row in db.journals)
    second = await control.recover('recovery-1', deadline=deadline)
    assert db.backend['epoch'] == 2 and db.block_updates == 1
    with pytest.raises(UnsupportedCapability):supervisor.recovery_binding(first)
    assert await control.settle_retired(second, receipt(second), deadline=deadline) == {'settled_count': 2}


@run_async
async def test_foreign_pending_metadata_blocks_reopen_without_source_access(monkeypatch, tmp_path):
    control, supervisor, db, receipt = setup(monkeypatch, tmp_path)
    deadline = asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    proof = await control.recover('recovery-1', deadline=deadline)
    await control.advance_owner(proof, ctx(), deadline=deadline)
    await control.settle_retired(proof, receipt(proof), deadline=deadline)
    db.journals.append({**db.journals[0], 'dispatch_id': 'foreign', 'foreign': True, 'state': 'unknown'})
    with pytest.raises(ProviderUnavailable):await control.reopen(proof, deadline=deadline)
    assert supervisor._sealed and not supervisor._gate and db.backend['state'] == 'recovery_blocked'
    assert db.open_updates == 0
    db.journals[-1]['state'] = 'settled'
    assert await control.reopen(proof, deadline=deadline) == {'state': 'open', 'epoch': 2}


@pytest.mark.parametrize('stage', ['block', 'owner', 'settle', 'reopen'])
@run_async
async def test_lost_commit_ack_reconciles_same_identity_without_replaying_dml(monkeypatch, tmp_path, stage):
    control, supervisor, db, receipt = setup(monkeypatch, tmp_path)
    deadline = asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    db.drop_next_commit = stage == 'block'
    proof = await control.recover('recovery-1', deadline=deadline)
    db.drop_next_commit = stage == 'owner'
    await control.advance_owner(proof, ctx(), deadline=deadline)
    db.drop_next_commit = stage == 'settle'
    await control.settle_retired(proof, receipt(proof), deadline=deadline)
    db.drop_next_commit = stage == 'reopen'
    await control.reopen(proof, deadline=deadline)
    assert db.block_updates == 1 and db.open_updates == 1 and supervisor._gate
    assert len(db.connections) >= 2 and db.connections[0].closed
    updates = [sql for sql, _ in db.calls if sql.startswith('UPDATE cragkit_qdrant.dispatch_journal')]
    assert len(updates) == 1


@run_async
async def test_forged_receipt_and_changed_owner_do_not_settle(monkeypatch, tmp_path):
    control, _, db, receipt = setup(monkeypatch, tmp_path)
    deadline = asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    proof = await control.recover('recovery-1', deadline=deadline)
    with pytest.raises(InvalidRequest):await control.settle_retired(proof, {}, deadline=deadline)
    db.owner['owner_token'] = '22222222-2222-4222-8222-222222222222'
    with pytest.raises(ProviderUnavailable):await control.advance_owner(proof, ctx(), deadline=deadline)
    assert db.journals[0]['state'] == 'unknown'


@pytest.mark.parametrize('fault', ['empty', 'foreign', 'duplicate', 'over8', 'operation'])
@run_async
async def test_journal_point_sets_are_complete_owned_and_supported_before_updates(monkeypatch, tmp_path, fault):
    control, _, db, receipt = setup(monkeypatch, tmp_path)
    deadline = asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    proof = await control.recover('recovery-1', deadline=deadline)
    await control.advance_owner(proof, ctx(), deadline=deadline)
    if fault == 'empty':db.points['dispatch-old'] = []
    elif fault == 'foreign':db.points['dispatch-old'] = ['ffffffff-ffff-4fff-8fff-ffffffffffff']
    elif fault == 'duplicate':db.points['dispatch-old'] *= 2
    elif fault == 'over8':db.points['dispatch-old'] *= 9
    else:db.journals[0]['operation'] = 'delete_points'
    expected = UnsupportedCapability if fault == 'operation' else IntegrityViolation
    with pytest.raises(expected):await control.settle_retired(proof, receipt(proof), deadline=deadline)
    assert db.journals[0]['state'] == 'unknown'


@run_async
async def test_bad_recovery_identity_does_not_close_healthy_admission(monkeypatch, tmp_path):
    control, supervisor, db, _ = setup(monkeypatch, tmp_path)
    deadline = asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    before = len(db.calls)
    with pytest.raises(InvalidRequest):await control.recover('', deadline=deadline)
    assert supervisor._gate and len(db.calls) == before


@run_async
async def test_private_sql_token_cannot_be_copied_cross_bound_or_reused(monkeypatch, tmp_path):
    control, supervisor, db, _ = setup(monkeypatch, tmp_path)
    deadline = asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    proof = await control.recover('recovery-1', deadline=deadline)
    db.journals[0]['state'] = 'settled'
    captured = []
    def capture(barrier, token, *, deadline):captured.append((barrier, token))
    db.finish_callback = capture
    await control.reopen(proof, deadline=deadline)
    barrier, token = captured[0]
    with pytest.raises(UnsupportedCapability):settlement_data({}, supervisor, barrier)
    with pytest.raises(UnsupportedCapability):settlement_data(token, object(), barrier)
    with pytest.raises(UnsupportedCapability):settlement_data(token, supervisor, object())
    assert settlement_data(token, supervisor, barrier)['new_epoch'] == 2
    with pytest.raises(UnsupportedCapability):settlement_data(token, supervisor, barrier)


@run_async
async def test_fresh_role_drift_blocks_before_sql_or_physical_recovery(monkeypatch, tmp_path):
    control, supervisor, db, _ = setup(monkeypatch, tmp_path)
    deadline = asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    db.role = False
    with pytest.raises(UnauthorizedScope):await control.recover('recovery-1', deadline=deadline)
    assert db.backend['state'] == 'open' and not supervisor._gate
    assert 'physical_fence' not in db.events


@run_async
async def test_cancelled_work_rolls_back_without_closing_borrowed_dependencies(monkeypatch, tmp_path):
    control, supervisor, db, _ = setup(monkeypatch, tmp_path)
    await control.initialize(deadline=asyncio.get_running_loop().time()+5)
    db.block_query = asyncio.Event()
    async def forbidden_close():raise AssertionError('borrowed dependency closed')
    monkeypatch.setattr(supervisor, 'close', forbidden_close)
    task = asyncio.create_task(control.recover('recovery-1', deadline=asyncio.get_running_loop().time()+5))
    await asyncio.sleep(0)
    await control.close()
    with pytest.raises(asyncio.CancelledError):await task
    assert db.backend['state'] == 'open' and not supervisor._gate
    assert db.active_leases == 0


def test_constructor_requires_exact_nominal_dependencies_without_io(monkeypatch, tmp_path):
    control, supervisor, _, _ = setup(monkeypatch, tmp_path)
    def forbidden():raise AssertionError('constructor I/O')
    monkeypatch.setattr(supervisor, 'control_binding', forbidden)
    PostgresQdrantRecovery(control.resource, config(), supervisor, control.verifier)
    with pytest.raises(InvalidRequest):PostgresQdrantRecovery(object(), config(), supervisor, control.verifier)


@pytest.mark.parametrize('code,expected', [
    ('42704', UnsupportedCapability), ('3F000', UnsupportedCapability),
    ('23502', IntegrityViolation), ('08006', ProviderUnavailable),
])
def test_recovery_specific_sql_errors_are_classified_and_redacted(code, expected):
    class DatabaseError(Exception):
        sqlstate = code
    async def check():
        result = implementation._error(DatabaseError('PRIVATE_DATABASE'),
                                       asyncio.get_running_loop().time()+1)
        assert type(result) is expected and 'PRIVATE' not in str(result)
    asyncio.run(check())


@pytest.mark.parametrize('state', ['open', 'blocked_before_fence', 'blocked_after_fence',
                                   'blocked_failed_fence', 'sealed_open'])
@run_async
async def test_initialize_accepts_only_compatible_local_and_durable_states(monkeypatch, tmp_path, state):
    control, supervisor, db, _ = setup(monkeypatch, tmp_path)
    deadline = asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    if state != 'open':
        db.backend.update(epoch=2, state='recovery_blocked', recovery_id='recovery-1')
    if state in ('blocked_after_fence', 'sealed_open'):
        supervisor._epoch = 2
        supervisor._recovery = {'recovery_id': 'recovery-1', 'old_epoch': 1, 'new_epoch': 2}
    if state == 'blocked_failed_fence':
        supervisor._recovery = {'recovery_id': 'recovery-1', 'old_epoch': 1, 'new_epoch': 2}
        supervisor._process.returncode = 1
    if state == 'sealed_open':
        supervisor._sealed = True
        supervisor._gate = False
        db.backend.update(state='open', recovery_id=None)
    restarted = PostgresQdrantRecovery(control.resource, config(), supervisor, control.verifier)
    await restarted.initialize(deadline=deadline)
    assert restarted._ready
    if db.backend['state'] == 'recovery_blocked':
        assert not supervisor._gate


@pytest.mark.parametrize('fault', ['open_epoch', 'blocked_epoch', 'blocked_id', 'unsealed_open', 'sealed_old_epoch'])
@run_async
async def test_initialize_refuses_unknown_epoch_or_recovery_combinations(monkeypatch, tmp_path, fault):
    control, supervisor, db, _ = setup(monkeypatch, tmp_path)
    deadline = asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    if fault == 'open_epoch':
        db.backend['epoch'] = 2
    elif fault == 'blocked_epoch':
        db.backend.update(epoch=1, state='recovery_blocked', recovery_id='recovery-1')
    else:
        supervisor._epoch = 2
        supervisor._recovery = {'recovery_id': 'recovery-1', 'old_epoch': 1, 'new_epoch': 2}
        if fault == 'blocked_id':
            db.backend.update(epoch=2, state='recovery_blocked', recovery_id='other-recovery')
        else:
            db.backend['epoch'] = 2
            if fault == 'sealed_old_epoch':
                supervisor._epoch = 1
                supervisor._sealed = True
    restarted = PostgresQdrantRecovery(control.resource, config(), supervisor, control.verifier)
    with pytest.raises(ProviderUnavailable):await restarted.initialize(deadline=deadline)
    assert not restarted._ready


@run_async
async def test_blocked_current_epoch_without_local_recovery_cannot_fence(monkeypatch, tmp_path):
    control, supervisor, db, _ = setup(monkeypatch, tmp_path)
    deadline=asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    db.backend.update(epoch=2,state='recovery_blocked',recovery_id='recovery-1')
    supervisor._epoch=2
    with pytest.raises(ProviderUnavailable):
        await control.recover('recovery-1',deadline=deadline)
    assert 'physical_fence' not in db.events


@pytest.mark.parametrize('fault', ['epoch', 'recovery', 'sealed', 'dead'])
@run_async
async def test_new_registration_requires_first_live_unsealed_controller(monkeypatch, tmp_path, fault):
    control, supervisor, db, _ = setup(monkeypatch, tmp_path)
    if fault == 'epoch':supervisor._epoch = 2
    elif fault == 'recovery':
        supervisor._recovery = {'recovery_id': 'recovery-1', 'old_epoch': 1, 'new_epoch': 2}
    elif fault == 'sealed':supervisor._sealed = True
    else:supervisor._process.returncode = 1
    with pytest.raises(ProviderUnavailable):
        await control.initialize(deadline=asyncio.get_running_loop().time()+5)
    assert db.backend is None


@run_async
async def test_other_known_recovery_id_is_rejected_before_sql_or_gate_change(monkeypatch, tmp_path):
    control, supervisor, db, _ = setup(monkeypatch, tmp_path)
    deadline = asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    supervisor._recovery = {'recovery_id': 'current', 'old_epoch': 1, 'new_epoch': 2}
    before = len(db.calls)
    gate = supervisor._gate
    with pytest.raises(ProviderUnavailable):await control.recover('different', deadline=deadline)
    assert len(db.calls) == before and supervisor._gate is gate


@run_async
async def test_returned_physical_proof_must_match_committed_instance_and_request(monkeypatch, tmp_path):
    control, supervisor, db, _ = setup(monkeypatch, tmp_path)
    deadline = asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    original = db.physical_callback
    async def wrong_physical(request, *, deadline):
        proof = await original(request, deadline=deadline)
        supervisor._proofs[proof]['storage_identity'] = 'foreign-storage'
        return proof
    db.physical_callback = wrong_physical
    with pytest.raises(IntegrityViolation):await control.recover('recovery-1', deadline=deadline)
    assert db.backend['state'] == 'recovery_blocked' and not supervisor._gate


@run_async
async def test_configured_namespace_mismatch_is_unsupported_before_checkout(monkeypatch, tmp_path):
    control, supervisor, db, _ = setup(monkeypatch, tmp_path)
    mismatched = PostgresQdrantRecovery(control.resource, {**config(), 'backend_namespace': 'other'},
                                       supervisor, control.verifier)
    with pytest.raises(UnsupportedCapability):
        await mismatched.initialize(deadline=asyncio.get_running_loop().time()+5)
    assert not db.calls and db.backend is None and supervisor._gate


@run_async
async def test_shared_supervisor_scope_blocks_reopen_during_another_coordinators_fence(monkeypatch, tmp_path):
    control, supervisor, db, _ = setup(monkeypatch, tmp_path)
    deadline = asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    proof = await control.recover('recovery-1', deadline=deadline)
    competitor = PostgresQdrantRecovery(control.resource, config(), supervisor, control.verifier)
    await competitor.initialize(deadline=deadline)
    db.physical_entered = asyncio.Event()
    db.physical_pause = asyncio.Event()
    pending = asyncio.create_task(competitor.recover('recovery-1', deadline=deadline))
    await db.physical_entered.wait()
    before = len(db.calls)
    assert db.active_leases == 0 and db.backend['state'] == 'recovery_blocked'
    with pytest.raises(ProviderUnavailable):await control.reopen(proof, deadline=deadline)
    restarted = PostgresQdrantRecovery(control.resource, config(), supervisor, control.verifier)
    with pytest.raises(ProviderUnavailable):await restarted.initialize(deadline=deadline)
    request = {'recovery_id': 'recovery-1', 'old_epoch': 1, 'new_epoch': 2}
    with pytest.raises(ProviderUnavailable):await supervisor.recover(request, deadline=deadline)
    with pytest.raises(ProviderUnavailable):
        await asyncio.create_task(supervisor.recover(request, deadline=deadline))
    assert len(db.calls) == before and db.open_updates == 0 and not supervisor._sealed
    db.physical_pause.set()
    replacement = await pending
    assert replacement is not proof and not supervisor._gate
    assert db.control_state['active'] is None
    assert competitor._scoped_control is None and control._scoped_control is None
    await restarted.initialize(deadline=deadline)
    assert restarted._ready


@run_async
async def test_cancellation_keeps_shared_scope_until_sql_cleanup_unwinds(monkeypatch, tmp_path):
    control, supervisor, db, _ = setup(monkeypatch, tmp_path)
    deadline = asyncio.get_running_loop().time()+5
    await control.initialize(deadline=deadline)
    competitor = PostgresQdrantRecovery(control.resource, config(), supervisor, control.verifier)
    db.block_query = asyncio.Event()
    db.rollback_entered = asyncio.Event()
    db.rollback_gate = asyncio.Event()
    pending = asyncio.create_task(control.recover('recovery-1', deadline=deadline))
    await asyncio.sleep(0)
    closing = asyncio.create_task(control.close())
    await db.rollback_entered.wait()
    facade = db.control_state['facades'][-1]
    assert db.control_state['active'] is not None and db.active_leases == 1
    assert not pending.done() and not closing.done()
    before = len(db.calls)
    with pytest.raises(ProviderUnavailable):await competitor.initialize(deadline=deadline)
    assert len(db.calls) == before
    db.block_query = None
    db.rollback_gate.set()
    await closing
    with pytest.raises(asyncio.CancelledError):await pending
    assert db.control_state['active'] is None and db.active_leases == 0
    assert control._scoped_control is None
    with pytest.raises(ProviderUnavailable):facade.block_ordinary()
    await competitor.initialize(deadline=deadline)
    assert competitor._ready and not supervisor._gate


@run_async
async def test_invalid_reinitialization_deadline_preserves_admitted_profile_without_sql(monkeypatch,tmp_path):
    control,supervisor,db,_=setup(monkeypatch,tmp_path)
    await control.initialize(deadline=asyncio.get_running_loop().time()+5)
    before=len(db.calls)
    with pytest.raises(InvalidRequest):await control.initialize(deadline=float('nan'))
    assert control._ready and control._schema_profile==2 and len(db.calls)==before


@pytest.mark.parametrize('foreign',[True,False])
@run_async
async def test_security_dispatch_late_other_uncertainty_blocks_ack_settlement(monkeypatch,tmp_path,foreign):
    values,source,handle,events,authorize=await security_dispatch_fixture(monkeypatch,tmp_path)
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=values
    handle.points=[];original=supervisor._http
    async def injected(*args,**kwargs):
        result=await original(*args,**kwargs)
        if args[1]=='PUT':
            row=deepcopy(db.journals[0]);row.update(dispatch_id='late-other',sequence=2,foreign=foreign,state='unknown',completion_sha256=None)
            db.journals.append(row)
        return result
    monkeypatch.setattr(supervisor,'_http',injected)
    with pytest.raises(ProviderUnavailable):
        await implementation.dispatch_security_recovery(recovery,proof,owner,target,authorize,deadline=asyncio.get_running_loop().time()+5)
    assert len(events['puts'])==1 and db.journals[0]['state']=='dispatched'
    assert all(row['completion_sha256'] is None for row in db.journals)


@run_async
async def test_security_dispatch_rereads_sequence_before_reserving_a_batch(monkeypatch,tmp_path):
    values,source,handle,events,authorize=await security_dispatch_fixture(monkeypatch,tmp_path)
    recovery,verifier,writer,supervisor,proof,owner,target,state,db,connections=values
    handle.points=[];calls=0
    async def raced(*args):
        nonlocal calls
        calls+=1
        if calls==2:
            db.journals.append(dict(dispatch_id='late-retired',instance_id='instance-1',sequence=1,
                owner_token=owner['owner_token'],backend_epoch=1,credential_generation='credential-1',operation='complete_point_upsert',
                recovery=True,state='settled',completion_sha256='b'*64,request_sha256='a'*64,foreign=False))
            db.security_members.append(('late-retired',writer.config.backend_namespace,writer.config.physical_collection,
                writer.config.collection_incarnation,source['point_ids'][0]))
        return True
    with pytest.raises(ProviderUnavailable):
        await implementation.dispatch_security_recovery(recovery,proof,owner,target,raced,deadline=asyncio.get_running_loop().time()+5)
    assert not events['puts'] and len(db.journals)==1 and db.journals[0]['dispatch_id']=='late-retired'
