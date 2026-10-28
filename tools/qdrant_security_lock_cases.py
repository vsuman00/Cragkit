"""Actual disposable PostgreSQL lock counterexample; no physical recovery proof."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import re
import secrets

from qdrant_authority_schema import catalog_queries
from qdrant_publication_native import bind_scope
from qdrant_publication_schema import insert_sql, seed_records
from qdrant_writer_cases import OWNER_TOKEN, writer_input

CHECKS = (
    'native_writer_unknown_stage_and_authority_revocation_committed',
    'restricted_supervisor_backend_owner_locked_before_writer_guard',
    'actual_supervisor_commit_wait_observed_at_fixture_barrier',
    'original_writer_backend_ended_while_supervisor_commit_waited',
    'replacement_authority_committed_before_supervisor_commit_release',
    'released_supervisor_commit_preserves_durable_journal_and_new_authority',
    'retained_writer_lock_blocks_replacement_until_explicit_release',
    'immutable_history_catalog_and_owned_fixture_cleanup_verified',
)
ERRORS = ('DeadlineExceeded','CancelledError','ProviderUnavailable','IntegrityViolation','InvalidRequest',
          'UnauthorizedScope','UnsupportedCapability','internal','cleanup_failed')
_SCHEMA = 'cragkit_security_lock_fixture'
_DOC = 'tenant_id=%s AND collection=%s AND document_id=%s'


class NativeSecurityLockFailure(RuntimeError):
    def __init__(self, observation):
        if (type(observation) is not dict or not {'ok','step','error'} <= set(observation)
                or observation['ok'] is not False or type(observation['step']) is not int
                or not 0 <= observation['step'] <= len(CHECKS) or type(observation['error']) is not str
                or observation['error'] not in ERRORS):
            raise ValueError('security_lock_failure_shape')
        if observation['error'] == 'cleanup_failed':
            if (set(observation) != {'ok','step','error','primary'} or observation['primary'] is not None
                    and (type(observation['primary']) is not str or observation['primary'] not in ERRORS
                         or observation['primary'] == 'cleanup_failed')):
                raise ValueError('security_lock_failure_shape')
        elif set(observation) != {'ok','step','error'}:
            raise ValueError('security_lock_failure_shape')
        super().__init__('security_lock_native_case_failed')
        self.observation = dict(observation)


async def _rows(connection, statement, params=()):
    return await (await connection.execute(statement,params,prepare=False)).fetchall()


async def _wait_observation(admin, statement, params, *, deadline, pending=None):
    while asyncio.get_running_loop().time() < deadline:
        if pending is not None and pending.done():
            raise RuntimeError('security_lock_operation_finished_before_observation')
        if await _rows(admin,statement,params) == [(True,)]:
            if pending is not None and pending.done():
                raise RuntimeError('security_lock_operation_finished_before_observation')
            return
        await asyncio.sleep(.01)
    raise RuntimeError('security_lock_observation_deadline')


async def _writer(database, inputs):
    from cragkit._postgres_pool import PoolConfig, PoolResource
    from cragkit._qdrant_writer import PostgresQdrantWriter
    raw = database.config('writer')
    for key in ('sslrootcert','passfile'):raw[key] = Path(raw[key])
    configuration = PoolConfig.model_validate(raw)
    if configuration.max_size != 1:
        raise RuntimeError('security_lock_writer_client_ceiling')
    resource = PoolResource(configuration)
    writer = PostgresQdrantWriter(resource,inputs['config'],inputs['instance_id'])
    try:
        await resource.open()
        await writer.initialize(deadline=asyncio.get_running_loop().time()+10)
    except BaseException:
        await resource.close()
        raise
    return writer,resource


def _security_change(inputs, intent_id, expected_revision, expected_epoch, new_revision):
    authorization = deepcopy(inputs['stage']['intent']['initial_authorization'])
    authorization['authorization_revision'] = new_revision
    if new_revision in ('auth-3','auth-4'):
        authorization.update(principal_ids=[],grant_ids=[],language=None,kind=None,tag=new_revision)
    target = {key:inputs['stage']['intent'][key] for key in ('tenant_id','collection','document_id')}
    return dict(target,action='update_authorization',intent_id=intent_id,
        expected_authorization_revision=expected_revision,expected_mutation_epoch=expected_epoch,
        authorization=authorization)


async def _snapshot(admin, inputs):
    target = tuple(inputs['stage']['intent'][key] for key in ('tenant_id','collection','document_id'))
    parts,params = [],[]
    for table in ('document_revisions','generations','members','point_claims','vector_replays','preparations','preparation_attestations'):
        parts.extend(("'"+table+"'",'(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY to_jsonb(r)::text),\'[]\'::jsonb) '
            'FROM cragkit_qdrant.'+table+' r WHERE '+_DOC+')'))
        params.extend(target)
    parts.extend(("'denied_intent'",'(SELECT to_jsonb(i) FROM cragkit_qdrant.publication_intents i WHERE '+_DOC+' AND intent_id=%s)'))
    params.extend((*target,inputs['stage']['intent']['intent_id']))
    values = await _rows(admin,"SELECT encode(sha256(convert_to(jsonb_build_object("+','.join(parts)+")::text,'UTF8')),'hex')",tuple(params))
    if len(values) != 1 or len(values[0]) != 1 or type(values[0][0]) is not str or re.fullmatch('[0-9a-f]{64}',values[0][0]) is None:
        raise RuntimeError('security_lock_snapshot_shape')
    return values[0][0]


async def _connect(database, kind):
    connection = await database._connect(database.config(kind))
    try:
        if await _rows(connection,'SELECT current_user=session_user, '
                'NOT rolsuper AND NOT rolbypassrls AND NOT rolcreaterole AND NOT rolcreatedb '
                'AND NOT rolreplication FROM pg_roles WHERE rolname=current_user') != [(True,True)]:
            raise RuntimeError('security_lock_restricted_login')
    except BaseException:
        await connection.close()
        raise
    return connection


async def _install_barrier(admin, supervisor_login, key):
    from psycopg import sql
    if type(key) is not int or not 1 <= key < 2147483647:raise ValueError('security_lock_fixture_key')
    async with admin.transaction():
        await admin.execute('CREATE SCHEMA '+_SCHEMA)
        await admin.execute('REVOKE ALL ON SCHEMA '+_SCHEMA+' FROM PUBLIC')
        await admin.execute(sql.SQL('GRANT USAGE ON SCHEMA '+_SCHEMA+' TO {}').format(sql.Identifier(supervisor_login)))
        await admin.execute('CREATE TABLE '+_SCHEMA+'.commit_barrier(lock_key bigint NOT NULL CHECK(lock_key='+str(key)+'))')
        await admin.execute('CREATE FUNCTION '+_SCHEMA+'.wait_at_commit() RETURNS trigger LANGUAGE plpgsql '
            'SECURITY DEFINER SET search_path=pg_catalog AS $barrier$ BEGIN '
            'PERFORM pg_catalog.pg_advisory_xact_lock('+str(key)+'); RETURN NEW; END $barrier$',prepare=False)
        await admin.execute('REVOKE ALL ON FUNCTION '+_SCHEMA+'.wait_at_commit() FROM PUBLIC')
        await admin.execute('CREATE CONSTRAINT TRIGGER wait_at_commit AFTER INSERT ON '+_SCHEMA+'.commit_barrier '
            'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION '+_SCHEMA+'.wait_at_commit()')
        await admin.execute(sql.SQL('GRANT INSERT ON '+_SCHEMA+'.commit_barrier TO {}').format(sql.Identifier(supervisor_login)))


async def run_security_lock_cases(database):
    """Use actual native writers and submitted COMMIT; the caller owns the server."""
    from cragkit._qdrant_writer import prepare_stage
    from cragkit.contracts import TrustedScope
    inputs,records = writer_input(),seed_records()
    target = tuple(inputs['stage']['intent'][key] for key in ('tenant_id','collection','document_id'))
    owner = dict(scope=TrustedScope.model_validate(inputs['scope']),collection=target[1],document_id=target[2],
        intent_id=inputs['stage']['intent']['intent_id'],owner_token=OWNER_TOKEN)
    admin = database.admin
    if admin is None or not database.with_attestations:
        raise NativeSecurityLockFailure(dict(ok=False,step=0,error='InvalidRequest'))
    deadline = asyncio.get_running_loop().time()+60
    checks = []
    original_writer = original_resource = replacement = replacement_resource = guard = supervisor = None
    commit_task = authority_task = None
    barrier_owned = False
    barrier_installed = False
    pids = set()
    key = secrets.randbelow(2147483646)+1
    dispatch_id = 'security-lock-retired-unknown'
    completion = sha256(b'G2d0 SQL-only synthetic settlement; no receipt or HTTP ACK').hexdigest()
    primary = None
    cleanup_failed = False
    baseline = catalog = None

    def scope(revision):return TrustedScope.model_validate(dict(inputs['scope'],authorization_revision=revision))
    async def require_current(connection,revision,epoch,*,locked=False):
        rows = await _rows(connection,'SELECT authorization_revision,mutation_epoch,principal_ids,grant_ids,language,kind,tag,tombstoned,active_generation_id '
            'FROM cragkit_qdrant.documents WHERE '+_DOC+(' FOR UPDATE' if locked else ''),target)
        desired = _security_change(inputs,'guard-only',revision,epoch,revision)['authorization']
        expected = (revision,epoch,desired['principal_ids'],desired['grant_ids'],desired['language'],desired['kind'],desired['tag'],False,None)
        if rows != [expected]:raise RuntimeError('security_lock_exact_current_tuple')
    async def current_guard(connection,revision,epoch):
        await connection.execute('BEGIN ISOLATION LEVEL READ COMMITTED')
        await connection.execute("SET LOCAL idle_in_transaction_session_timeout='15000ms'")
        await bind_scope(connection,records,authorization_revision=revision,owner_token=OWNER_TOKEN)
        await require_current(connection,revision,epoch,locked=True)
    wait_commit = ("SELECT EXISTS(SELECT 1 FROM pg_stat_activity a JOIN pg_locks l ON l.pid=a.pid "
        "WHERE a.pid=%s AND a.query='COMMIT' AND a.state='active' AND a.wait_event_type='Lock' "
        "AND a.wait_event='advisory' AND l.locktype='advisory' AND NOT l.granted "
        'AND l.classid=0 AND l.objid=%s AND l.objsubid=1)')
    async def guard_close():
        nonlocal guard
        if guard is not None:
            await guard.close()
            guard = None
    async def writer_close():
        nonlocal replacement,replacement_resource
        if replacement is not None:
            await replacement.close();replacement = None
        if replacement_resource is not None:
            await replacement_resource.close();replacement_resource = None

    try:
        async with asyncio.timeout_at(deadline):
            catalog = await _rows(admin,catalog_queries()[0])
            supervisor = await _connect(database,'supervisor');pids.add(supervisor.info.backend_pid)
            async with supervisor.transaction():
                await bind_scope(supervisor,records)
                await supervisor.execute(insert_sql('backend_instances',records['backend']))
            await supervisor.close();supervisor = None
            original_writer,original_resource = await _writer(database,inputs)
            await original_writer.stage(prepare_stage(inputs['stage']),owner['scope'],owner_token=OWNER_TOKEN,deadline=deadline)
            admitted = await original_writer.admit_publication(owner,deadline=deadline)
            if admitted['intent']['state'] != 'writing':raise RuntimeError('security_lock_stage_admission')
            await original_writer.reserve_dispatch(owner,dict(dispatch_id=dispatch_id,sequence=1,
                credential_generation='synthetic-sql-retired-credential-1',operation='complete_point_upsert',
                point_ids=[member['point_id'] for member in inputs['stage']['manifest']['members']]),deadline=deadline)
            await original_writer.mark_dispatched(owner,dispatch_id,deadline=deadline)
            await original_writer.mark_unknown(owner,dispatch_id,deadline=deadline)
            await original_writer.apply_security(_security_change(inputs,'security-lock-auth-2','auth-1',1,'auth-2'),
                scope('auth-1'),owner_token=OWNER_TOKEN,deadline=deadline)
            denied = await original_writer.admit_publication(dict(owner,scope=scope('auth-2')),deadline=deadline)
            if denied['intent']['state'] != 'denied':raise RuntimeError('security_lock_old_stage_not_denied')
            baseline = await _snapshot(admin,inputs)
            await original_writer.close();original_writer = None
            await original_resource.close();original_resource = None
            checks.append(CHECKS[0])

            await _install_barrier(admin,database.config('supervisor')['user'],key);barrier_installed = True
            if await _rows(admin,catalog_queries()[0]) != catalog:raise RuntimeError('security_lock_fixture_changed_production_catalog')
            await admin.execute('SELECT pg_advisory_lock(%s)',(key,));barrier_owned = True
            supervisor = await _connect(database,'supervisor');pids.add(supervisor.info.backend_pid)
            sup_pid = supervisor.info.backend_pid
            await supervisor.execute('BEGIN ISOLATION LEVEL READ COMMITTED')
            await supervisor.execute("SET LOCAL lock_timeout='5000ms'")
            await supervisor.execute("SET LOCAL statement_timeout='10000ms'")
            await bind_scope(supervisor,records,authorization_revision='auth-2')
            await supervisor.execute("UPDATE cragkit_qdrant.backend_instances SET state='recovery_blocked',epoch=2,recovery_id='security-lock-synthetic-recovery' WHERE instance_id=%s",(inputs['instance_id'],))
            await supervisor.execute('UPDATE cragkit_qdrant.document_owners SET backend_epoch=2 WHERE '+_DOC,target)
            guard = await _connect(database,'writer');pids.add(guard.info.backend_pid);guard_pid = guard.info.backend_pid
            await current_guard(guard,'auth-2',2)
            checks.append(CHECKS[1])
            await supervisor.execute("UPDATE cragkit_qdrant.dispatch_journal SET state='settled',completion_sha256=%s WHERE "+_DOC+
                " AND intent_id=%s AND dispatch_id=%s AND state='unknown'",(completion,*target,owner['intent_id'],dispatch_id))
            await supervisor.execute('INSERT INTO '+_SCHEMA+'.commit_barrier(lock_key) VALUES(%s)',(key,))
            commit_task = asyncio.create_task(supervisor.execute('COMMIT'))
            await _wait_observation(admin,wait_commit,(sup_pid,key),deadline=min(deadline,asyncio.get_running_loop().time()+2),pending=commit_task)
            checks.append(CHECKS[2])
            await guard_close()
            await _wait_observation(admin,'SELECT NOT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=%s)',(guard_pid,),
                deadline=min(deadline,asyncio.get_running_loop().time()+2))
            await _wait_observation(admin,wait_commit,(sup_pid,key),deadline=min(deadline,asyncio.get_running_loop().time()+1),pending=commit_task)
            checks.append(CHECKS[3])

            replacement,replacement_resource = await _writer(database,inputs)
            result = await replacement.apply_security(_security_change(inputs,'security-lock-auth-3','auth-2',2,'auth-3'),
                scope('auth-2'),owner_token=OWNER_TOKEN,deadline=deadline)
            if not result['authority_committed']:raise RuntimeError('security_lock_replacement_authority_missing')
            await require_current(admin,'auth-3',3)
            await _wait_observation(admin,wait_commit,(sup_pid,key),deadline=min(deadline,asyncio.get_running_loop().time()+1),pending=commit_task)
            checks.append(CHECKS[4])
            await admin.execute('SELECT pg_advisory_unlock(%s)',(key,));barrier_owned = False
            await asyncio.wait_for(asyncio.shield(commit_task),min(5,deadline-asyncio.get_running_loop().time()))
            commit_task = None
            if await _rows(admin,'SELECT state,completion_sha256 FROM cragkit_qdrant.dispatch_journal WHERE '+_DOC+' AND intent_id=%s AND dispatch_id=%s',
                    (*target,owner['intent_id'],dispatch_id)) != [('settled',completion)]:raise RuntimeError('security_lock_settlement_not_durable')
            await require_current(admin,'auth-3',3)
            checks.append(CHECKS[5])
            await supervisor.close();supervisor = None
            await writer_close()

            guard = await _connect(database,'writer');pids.add(guard.info.backend_pid);retained_guard_pid = guard.info.backend_pid
            await current_guard(guard,'auth-3',3)
            replacement,replacement_resource = await _writer(database,inputs)
            async with replacement_resource.lease(deadline=deadline) as connection:
                async with connection.transaction():
                    replacement_pid = (await _rows(connection,'SELECT pg_backend_pid()'))[0][0];pids.add(replacement_pid)
            authority_task = asyncio.create_task(replacement.apply_security(
                _security_change(inputs,'security-lock-auth-4','auth-3',3,'auth-4'),scope('auth-3'),owner_token=OWNER_TOKEN,deadline=deadline))
            await _wait_observation(admin,"SELECT EXISTS(SELECT 1 FROM pg_stat_activity a JOIN pg_locks l ON l.pid=a.pid WHERE a.pid=%s "
                "AND a.wait_event_type='Lock' AND NOT l.granted AND l.locktype IN ('transactionid','tuple') "
                'AND %s=ANY(pg_blocking_pids(a.pid)))',(replacement_pid,retained_guard_pid),
                deadline=min(deadline,asyncio.get_running_loop().time()+2),pending=authority_task)
            await guard.execute('ROLLBACK');await guard_close()
            result = await asyncio.wait_for(asyncio.shield(authority_task),min(5,deadline-asyncio.get_running_loop().time()))
            authority_task = None
            if not result['authority_committed']:
                raise RuntimeError('security_lock_retained_guard_control_failed')
            await require_current(admin,'auth-4',4)
            checks.append(CHECKS[6])
            await writer_close()
            if await _snapshot(admin,inputs) != baseline:raise RuntimeError('security_lock_immutable_history_changed')
    except BaseException as error:
        primary = error
    finally:
        cleanup_deadline = asyncio.get_running_loop().time()+12
        async def cleanup(operation):
            nonlocal cleanup_failed
            try:
                remaining = cleanup_deadline-asyncio.get_running_loop().time()
                if remaining <= 0:raise TimeoutError()
                await asyncio.wait_for(operation(),min(3,remaining))
            except BaseException:cleanup_failed = True
        if barrier_owned:
            await cleanup(lambda:admin.execute('SELECT pg_advisory_unlock(%s)',(key,)))
        for pending in (authority_task,commit_task):
            if pending is not None:
                async def drain(selected=pending):
                    if not selected.done():selected.cancel()
                    await asyncio.gather(selected,return_exceptions=True)
                await cleanup(drain)
        await cleanup(guard_close)
        if supervisor is not None:await cleanup(supervisor.close)
        await cleanup(writer_close)
        if original_writer is not None:await cleanup(original_writer.close)
        if original_resource is not None:await cleanup(original_resource.close)
        # Installation is transactional; only a committed, task-owned namespace is dropped.
        if barrier_installed:await cleanup(lambda:admin.execute('DROP SCHEMA IF EXISTS '+_SCHEMA+' CASCADE'))
        if catalog is not None:
            async def unchanged_catalog():
                if await _rows(admin,catalog_queries()[0]) != catalog:raise RuntimeError('security_lock_catalog_changed')
            await cleanup(unchanged_catalog)
        if pids:
            await cleanup(lambda:_wait_observation(admin,'SELECT NOT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=ANY(%s::int[]))',
                (list(pids),),deadline=cleanup_deadline))
        if baseline is not None:
            async def unchanged_history():
                if await _snapshot(admin,inputs) != baseline:raise RuntimeError('security_lock_immutable_history_changed')
            await cleanup(unchanged_history)
    name = None if primary is None else ('DeadlineExceeded' if isinstance(primary,TimeoutError) else type(primary).__name__)
    label = name if name in ERRORS and name != 'cleanup_failed' else ('internal' if name is not None else None)
    if cleanup_failed:
        raise NativeSecurityLockFailure(dict(ok=False,step=len(checks),error='cleanup_failed',primary=label)) from None
    if primary is not None:
        raise NativeSecurityLockFailure(dict(ok=False,step=len(checks),error=label)) from None
    checks.append(CHECKS[7])
    return checks
