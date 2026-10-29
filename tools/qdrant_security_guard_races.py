"""Actual same-transaction guard races; synthetic SQL settlement only."""
from __future__ import annotations

import asyncio
from hashlib import sha256
import json
import secrets

from qdrant_publication_native import bind_scope
from qdrant_security_lock_cases import (_connect, _install_barrier, _rows,
    _security_change, _wait_observation, _SCHEMA)
from qdrant_writer_cases import OWNER_TOKEN

RACE_CHECKS = (
    'supervisor_commit_barrier_retains_current_security_lock',
    'unrelated_writer_loss_cannot_release_supervisor_guard',
    'replacement_authority_commits_only_after_supervisor_commit',
    'post_wait_guard_rejects_fresh_authority_change',
    'supervisor_rollback_preserves_unknown_journal_and_releases_writer',
    'supervisor_connection_loss_keeps_atomic_commit_order',
)
ERRORS = ('DeadlineExceeded', 'CancelledError', 'ProviderUnavailable', 'IntegrityViolation',
    'InvalidRequest', 'UnauthorizedScope', 'UnsupportedCapability', 'internal', 'cleanup_failed')
_DOC = 'tenant_id=%s AND collection=%s AND document_id=%s'
GUARD_SQL = 'SELECT cragkit_qdrant.lock_current_security('+','.join(['%s']*22)+')'
_WAIT_COMMIT = ("SELECT EXISTS(SELECT 1 FROM pg_stat_activity a JOIN pg_locks l ON l.pid=a.pid "
    "WHERE a.pid=%s AND a.query='COMMIT' AND a.state='active' AND a.wait_event_type='Lock' "
    "AND a.wait_event='advisory' AND l.locktype='advisory' AND NOT l.granted "
    'AND l.classid=0 AND l.objid=%s AND l.objsubid=1)')
_WAIT_WRITER = ("SELECT EXISTS(SELECT 1 FROM pg_stat_activity a JOIN pg_locks l ON l.pid=a.pid "
    "WHERE a.pid=%s AND a.wait_event_type='Lock' AND NOT l.granted "
    "AND l.locktype IN ('transactionid','tuple') AND %s=ANY(pg_blocking_pids(a.pid)))")
_COMPLETION = sha256(b'SG-r1 SQL-only synthetic settlement; no receipt or HTTP acknowledgment').hexdigest()


class NativeSecurityGuardRaceFailure(RuntimeError):
    def __init__(self, observation):
        if (type(observation) is not dict or observation.get('ok') is not False
                or type(observation.get('step')) is not int or not 0 <= observation['step'] <= len(RACE_CHECKS)
                or type(observation.get('error')) is not str or observation['error'] not in ERRORS):
            raise ValueError('security_guard_race_failure_shape')
        if observation['error'] == 'cleanup_failed':
            if (set(observation) != {'ok','step','error','primary'} or observation['primary'] is not None
                    and (type(observation['primary']) is not str or observation['primary'] not in ERRORS
                        or observation['primary'] == 'cleanup_failed')):
                raise ValueError('security_guard_race_failure_shape')
        elif set(observation) != {'ok','step','error'}:
            raise ValueError('security_guard_race_failure_shape')
        super().__init__('security_guard_native_race_failed')
        self.observation = dict(observation)


def _validate_datasets(datasets):
    if type(datasets) is not dict or set(datasets) != {'commit','post_wait','abort','lost'}:
        raise ValueError('security_guard_race_datasets')
    targets = set()
    for value in datasets.values():
        if (type(value) is not dict or set(value) != {'arguments','inputs','records','dispatch_id','scope'}
                or type(value['arguments']) is not tuple or len(value['arguments']) != 22
                or type(value['inputs']) is not dict or type(value['records']) is not dict
                or type(value['scope']) is not dict or type(value['dispatch_id']) is not str
                or not 1 <= len(value['dispatch_id']) <= 256):
            raise ValueError('security_guard_race_dataset')
        target = tuple(value['arguments'][6:9])
        intent = value['inputs']['stage']['intent']
        if (target != tuple(intent[key] for key in ('tenant_id','collection','document_id'))
                or value['arguments'][9] != intent['intent_id']
                or value['arguments'][14:16] != ('auth-2',2)
                or value['scope'].get('authorization_revision') != 'auth-2'
                or target in targets):
            raise ValueError('security_guard_race_binding')
        targets.add(target)


def _authority_record(dataset):
    from cragkit._qdrant_manifest import encode_security_intent
    record = _security_change(dataset['inputs'], 'guard-race-auth-3-'+dataset['arguments'][8], 'auth-2', 2, 'auth-3')
    encoded = encode_security_intent(record)
    return record, encoded


async def _begin(connection):
    await connection.execute('BEGIN ISOLATION LEVEL READ COMMITTED')
    await connection.execute("SET LOCAL lock_timeout='10000ms'")
    await connection.execute("SET LOCAL statement_timeout='15000ms'")
    await connection.execute("SET LOCAL idle_in_transaction_session_timeout='15000ms'")
    await connection.execute("SET LOCAL client_connection_check_interval='100ms'")


async def _authority(connection, dataset, *, commit=True):
    """Use the writer's canonical security SQL sequence under its actual login."""
    record, encoded = _authority_record(dataset)
    desired = record['authorization']
    target = tuple(dataset['arguments'][6:9])
    await _begin(connection)
    scope = dataset['scope']
    await bind_scope(connection, dataset['records'], intent_id=record['intent_id'], owner_token=OWNER_TOKEN,
        authorization_revision='auth-2', principal_id=scope['principal_id'],
        grant_ids=json.dumps(scope['grant_ids'],separators=(',',':')))
    await connection.execute('INSERT INTO cragkit_qdrant.publication_intents '
        '(tenant_id,collection,document_id,intent_id,instance_id,action,payload_bytes,payload_sha256,'
        'expected_authorization_revision,expected_mutation_epoch) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (*target,record['intent_id'],dataset['arguments'][0],record['action'],encoded.encoded_bytes,
            encoded.sha256,'auth-2',2))
    rows = await _rows(connection,'SELECT authorization_revision,mutation_epoch,tombstoned '
        'FROM cragkit_qdrant.documents WHERE '+_DOC+' FOR UPDATE',target)
    if rows != [('auth-2',2,False)]:
        raise RuntimeError('security_guard_race_authority_fence')
    updated = await _rows(connection,'UPDATE cragkit_qdrant.documents SET authorization_revision=%s,mutation_epoch=%s,'
        'principal_ids=%s,grant_ids=%s,language=%s,kind=%s,tag=%s,tombstoned=%s WHERE '+_DOC+
        ' AND authorization_revision=%s AND mutation_epoch=%s RETURNING document_id',
        (desired['authorization_revision'],3,desired['principal_ids'],desired['grant_ids'],desired['language'],
            desired['kind'],desired['tag'],desired['tombstoned'],*target,'auth-2',2))
    if updated != [(target[2],)]:
        raise RuntimeError('security_guard_race_authority_update')
    await connection.execute("UPDATE cragkit_qdrant.publication_intents SET state='authority_committed',authority_committed=true "
        'WHERE '+_DOC+' AND intent_id=%s',(*target,record['intent_id']))
    if commit:
        await connection.execute('COMMIT')


async def run_guard_races(database, datasets):
    """Borrow one admin; open at most two restricted runtime clients at once."""
    try:
        _validate_datasets(datasets)
    except (ValueError,KeyError,TypeError):
        raise NativeSecurityGuardRaceFailure(dict(ok=False,step=0,error='InvalidRequest')) from None
    admin = database.admin
    if admin is None:
        raise NativeSecurityGuardRaceFailure(dict(ok=False,step=0,error='InvalidRequest'))
    deadline = asyncio.get_running_loop().time()+90
    checks, clients, tasks, pids = [], [], [], set()
    installed = held = False
    primary = None
    cleanup_failed = False
    key = secrets.randbelow(2147483646)+1

    async def connect(kind):
        connection = await _connect(database,kind)
        clients.append(connection);pids.add(connection.info.backend_pid)
        return connection
    async def close(connection):
        if connection in clients:
            await connection.close();clients.remove(connection)
    async def observe(sql,params,pending=None):
        await _wait_observation(admin,sql,params,deadline=min(deadline,asyncio.get_running_loop().time()+3),pending=pending)
    async def guard(connection,data):
        await _begin(connection)
        await bind_scope(connection,data['records'],authorization_revision='auth-2')
        arguments=list(data['arguments'])
        arguments[16],arguments[17]=list(arguments[16]),list(arguments[17])
        await connection.execute(GUARD_SQL,tuple(arguments))
    async def settle(connection,data):
        rows = await _rows(connection,"UPDATE cragkit_qdrant.dispatch_journal SET state='settled',completion_sha256=%s "
            'WHERE '+_DOC+" AND intent_id=%s AND dispatch_id=%s AND state='unknown' RETURNING dispatch_id",
            (_COMPLETION,*data['arguments'][6:9],data['arguments'][9],data['dispatch_id']))
        if rows != [(data['dispatch_id'],)]:
            raise RuntimeError('security_guard_race_synthetic_settlement')
    async def journal(data):
        return await _rows(admin,'SELECT state,completion_sha256 FROM cragkit_qdrant.dispatch_journal WHERE '+_DOC+
            ' AND intent_id=%s AND dispatch_id=%s',(*data['arguments'][6:9],data['arguments'][9],data['dispatch_id']))
    async def authority_state(data,revision,epoch):
        if revision=='auth-3':
            record,_=_authority_record(data)
            desired=record['authorization']
            metadata=(desired['principal_ids'],desired['grant_ids'],desired['language'],desired['kind'],desired['tag'],desired['tombstoned'])
        else:
            metadata=(list(data['arguments'][16]),list(data['arguments'][17]),*data['arguments'][18:22])
        if await _rows(admin,'SELECT authorization_revision,mutation_epoch,principal_ids,grant_ids,language,kind,tag,tombstoned,'
                'active_generation_id FROM cragkit_qdrant.documents WHERE '+_DOC,
                tuple(data['arguments'][6:9])) != [(revision,epoch,*metadata,data['arguments'][13])]:
            raise RuntimeError('security_guard_race_authority_state')
        if revision=='auth-3' and await _rows(admin,'SELECT state,authority_committed,replica_complete,purge_complete '
                'FROM cragkit_qdrant.publication_intents WHERE '+_DOC+' AND intent_id=%s',
                (*data['arguments'][6:9],record['intent_id'])) != [('authority_committed',True,False,False)]:
            raise RuntimeError('security_guard_race_authority_flags')
    def spawn(coroutine):
        task = asyncio.create_task(coroutine);tasks.append(task);return task
    async def finish(task):
        await asyncio.wait_for(asyncio.shield(task),min(5,deadline-asyncio.get_running_loop().time()))
    async def barrier(connection):
        nonlocal held
        await admin.execute('SELECT pg_advisory_lock(%s)',(key,));held=True
        await connection.execute('INSERT INTO '+_SCHEMA+'.commit_barrier(lock_key) VALUES(%s)',(key,))
    async def release():
        nonlocal held
        if await _rows(admin,'SELECT pg_advisory_unlock(%s)',(key,)) != [(True,)]:
            raise RuntimeError('security_guard_race_barrier_release')
        held=False

    try:
        async with asyncio.timeout_at(deadline):
            await _install_barrier(admin,database.config('supervisor')['user'],key);installed=True
            data=datasets['commit']
            supervisor=await connect('supervisor');sup_pid=supervisor.info.backend_pid
            await guard(supervisor,data);await settle(supervisor,data);await barrier(supervisor)
            commit=spawn(supervisor.execute('COMMIT'))
            await observe(_WAIT_COMMIT,(sup_pid,key),commit)
            writer=await connect('writer');writer_pid=writer.info.backend_pid
            authority=spawn(_authority(writer,data))
            await observe(_WAIT_WRITER,(writer_pid,sup_pid),authority)
            await authority_state(data,'auth-2',2)
            checks.append(RACE_CHECKS[0])
            await close(writer)
            # A deliberately closed driver may report an error; inspect backend exit separately.
            await asyncio.gather(authority,return_exceptions=True)
            await observe('SELECT NOT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=%s)',(writer_pid,))
            await observe(_WAIT_COMMIT,(sup_pid,key),commit)
            replacement=await connect('writer');replacement_pid=replacement.info.backend_pid
            authority=spawn(_authority(replacement,data))
            await observe(_WAIT_WRITER,(replacement_pid,sup_pid),authority)
            checks.append(RACE_CHECKS[1])
            await release();await finish(commit);await finish(authority)
            if await journal(data) != [('settled',_COMPLETION)]:
                raise RuntimeError('security_guard_race_committed_journal')
            await authority_state(data,'auth-3',3)
            checks.append(RACE_CHECKS[2])
            await close(replacement);await close(supervisor)

            data=datasets['post_wait']
            writer=await connect('writer');writer_pid=writer.info.backend_pid
            await _authority(writer,data,commit=False)
            supervisor=await connect('supervisor');sup_pid=supervisor.info.backend_pid
            guarded=spawn(guard(supervisor,data))
            await observe(_WAIT_WRITER,(sup_pid,writer_pid),guarded)
            await writer.execute('COMMIT')
            try:
                await finish(guarded)
            except BaseException as error:
                if getattr(error,'sqlstate',None) != '23514':
                    raise
            else:
                raise RuntimeError('security_guard_race_stale_guard_accepted')
            await supervisor.execute('ROLLBACK')
            if await journal(data) != [('unknown',None)]:
                raise RuntimeError('security_guard_race_post_wait_changed_journal')
            await authority_state(data,'auth-3',3)
            checks.append(RACE_CHECKS[3])
            await close(writer);await close(supervisor)

            data=datasets['abort']
            supervisor=await connect('supervisor');sup_pid=supervisor.info.backend_pid
            await guard(supervisor,data);await settle(supervisor,data)
            writer=await connect('writer');authority=spawn(_authority(writer,data))
            await observe(_WAIT_WRITER,(writer.info.backend_pid,sup_pid),authority)
            await supervisor.execute('ROLLBACK');await finish(authority)
            if await journal(data) != [('unknown',None)]:
                raise RuntimeError('security_guard_race_abort_changed_journal')
            await authority_state(data,'auth-3',3)
            checks.append(RACE_CHECKS[4])
            await close(writer);await close(supervisor)

            data=datasets['lost']
            supervisor=await connect('supervisor');sup_pid=supervisor.info.backend_pid
            await guard(supervisor,data);await settle(supervisor,data);await barrier(supervisor)
            commit=spawn(supervisor.execute('COMMIT'))
            await observe(_WAIT_COMMIT,(sup_pid,key),commit)
            writer=await connect('writer');authority=spawn(_authority(writer,data))
            await observe(_WAIT_WRITER,(writer.info.backend_pid,sup_pid),authority)
            await close(supervisor)
            # Closing a socket is not evidence of server transaction termination.
            # Observe either retained lock custody or actual backend disappearance.
            lost_branch=None
            observation_deadline=min(deadline,asyncio.get_running_loop().time()+3)
            while asyncio.get_running_loop().time()<observation_deadline:
                alive=await _rows(admin,'SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=%s)',(sup_pid,))
                if alive==[(False,)]:
                    lost_branch='ended';break
                if alive!=[(True,)]:raise RuntimeError('security_guard_race_backend_observation')
                state=await _rows(admin,'SELECT authorization_revision,mutation_epoch,'+_WAIT_WRITER[len('SELECT '):]+
                    ' FROM cragkit_qdrant.documents WHERE '+_DOC,
                    (writer.info.backend_pid,sup_pid,*data['arguments'][6:9]))
                if state==[('auth-2',2,True)]:
                    lost_branch='held';break
                if state==[('auth-3',3,False)] and await _rows(admin,_WAIT_COMMIT,(sup_pid,key))==[(True,)]:
                    raise RuntimeError('security_guard_race_authority_before_atomic_end')
                await asyncio.sleep(.01)
            if lost_branch is None:raise RuntimeError('security_guard_race_lost_observation_deadline')
            if lost_branch=='ended':
                await finish(authority)
                if await journal(data)!=[('unknown',None)]:
                    raise RuntimeError('security_guard_race_disconnected_commit_before_release')
                await authority_state(data,'auth-3',3)
            await release();await asyncio.gather(commit,return_exceptions=True);await finish(authority)
            await observe('SELECT NOT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=%s)',(sup_pid,))
            if await journal(data) not in ([('settled',_COMPLETION)],[('unknown',None)]):
                raise RuntimeError('security_guard_race_lost_commit_not_atomic')
            await authority_state(data,'auth-3',3)
            checks.append(RACE_CHECKS[5])
            await close(writer)
    except BaseException as error:
        primary=error
    finally:
        cleanup_deadline=asyncio.get_running_loop().time()+12
        async def cleanup(operation):
            nonlocal cleanup_failed
            try:
                remaining=cleanup_deadline-asyncio.get_running_loop().time()
                if remaining<=0:raise TimeoutError()
                await asyncio.wait_for(operation(),min(3,remaining))
            except BaseException:
                cleanup_failed=True
        if held:
            await cleanup(release)
        for connection in list(clients):
            await cleanup(lambda selected=connection:close(selected))
        async def drain():
            for task in tasks:
                if not task.done():task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
        await cleanup(drain)
        if pids:
            await cleanup(lambda:_wait_observation(admin,'SELECT NOT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=ANY(%s::int[]))',
                (list(pids),),deadline=cleanup_deadline))
        if installed:
            await cleanup(lambda:admin.execute('DROP SCHEMA IF EXISTS '+_SCHEMA+' CASCADE'))
    name=None if primary is None else ('DeadlineExceeded' if isinstance(primary,TimeoutError) else type(primary).__name__)
    label=name if name in ERRORS and name!='cleanup_failed' else ('internal' if name is not None else None)
    if cleanup_failed:
        failure=NativeSecurityGuardRaceFailure(dict(ok=False,step=len(checks),error='cleanup_failed',primary=label))
        failure.primary=primary
        raise failure from None
    if primary is not None:
        failure=NativeSecurityGuardRaceFailure(dict(ok=False,step=len(checks),error=label))
        failure.primary=primary
        raise failure from None
    return checks
