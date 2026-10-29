"""Actual native writer profile admission; no guard call or physical settlement."""
from __future__ import annotations

from qdrant_guard_authority_cases import ERRORS
import json

CHECKS=(
 'four_migration_writer_admission_with_exact_guard_shape',
 'current_security_projection_preserves_complete_claims',
 'committed_sensitive_guard_grant_refused_before_business_sql',
 'guard_owner_login_drift_refused_before_business_sql',
 'fifth_history_row_refused_after_initialization',
 'extra_definer_refused_without_legacy_fallback',
 'permission_and_catalog_restoration_allows_safe_projection',
 'borrowed_resources_close_and_no_provider_activity',
)


def failure_observation(value):
    if (type(value) is not dict or value.get('ok') is not False or type(value.get('step')) is not int
            or not 0<=value['step']<=len(CHECKS) or type(value.get('error')) is not str or value['error'] not in ERRORS):
        raise RuntimeError('guard_writer_native_failure_shape')
    if value['error']=='cleanup_failed':
        if set(value)!={'ok','step','error','primary','cleanup'} or type(value['cleanup']) is not list or not 1<=len(value['cleanup'])<=8:
            raise RuntimeError('guard_writer_native_failure_shape')
        if value['primary'] is not None and (type(value['primary']) is not str or value['primary'] not in ERRORS or value['primary']=='cleanup_failed'):
            raise RuntimeError('guard_writer_native_failure_shape')
        for record in value['cleanup']:
            if (type(record) is not dict or set(record)!={'operation','outcome'}
                    or type(record['operation']) is not str or record['operation'] not in ('catalog_restore','writer_pool_close','operator_pool_close','factory_pool_close','writer_close')
                    or type(record['outcome']) is not str or record['outcome'] not in ERRORS):
                raise RuntimeError('guard_writer_native_failure_shape')
    elif set(value)!={'ok','step','error'}:
        raise RuntimeError('guard_writer_native_failure_shape')
    return json.loads(json.dumps(value))


class NativeGuardWriterFailure(RuntimeError):
    def __init__(self,observation):
        super().__init__('guard_writer_native_case_failed')
        self.observation=failure_observation(observation)


def writer_inputs(dataset):
    args=dataset['arguments'];inputs=dataset['inputs']
    return dict(config=inputs['config'],instance_id=inputs['instance_id'],
        context=dict(scope=dataset['scope'],collection=args[7],document_id=args[8],intent_id=args[11],owner_token=args[10]),
        point_ids=sorted(point['id'] for point in inputs['expected_points']),intent_sha256=args[12])


async def python_guard_writer_cases(value):
    import asyncio
    from pathlib import Path
    from cragkit._postgres_pool import PoolConfig,PoolResource,_owned_pool
    from cragkit._qdrant_writer import PostgresQdrantWriter,security_projection_data
    from cragkit.errors import UnsupportedCapability

    raw=dict(value['writer_config'])
    for key in ('sslrootcert','passfile'):raw[key]=Path(raw[key])
    configuration=PoolConfig.model_validate(raw)
    if configuration.max_size!=1:raise RuntimeError('guard_writer_client_ceiling')
    counter=dict(scope=0,denied=0)
    class Connection:
        def __init__(self,actual):self.actual=actual
        def __getattr__(self,name):return getattr(self.actual,name)
        async def execute(self,statement,params=None,**options):
            if type(statement) is str and "set_config('cragkit_qdrant.writer_document_id'" in statement:counter['scope']+=1
            return await self.actual.execute(statement,params,**options)
    class Pool:
        def __init__(self,config):self.actual=_owned_pool(config)
        def __getattr__(self,name):return getattr(self.actual,name)
        async def getconn(self,**options):return Connection(await self.actual.getconn(**options))
        async def putconn(self,connection):await self.actual.putconn(connection.actual)
    resource=PoolResource(configuration,factory=Pool)
    inputs=value['inputs']
    writer=PostgresQdrantWriter(resource,inputs['config'],inputs['instance_id'])
    deadline=asyncio.get_running_loop().time()+120
    checks=[];operator=None;primary=None;restore=None
    baseline=None
    async def read():
        return security_projection_data(await writer.project_security(inputs['context'],deadline=deadline),writer)
    async def safe_read():
        nonlocal baseline
        before=counter['scope'];data=await read()
        if (counter['scope']!=before+1 or list(data['point_ids'])!=inputs['point_ids']
                or data['intent_sha256']!=inputs['intent_sha256'] or data['authorization_revision']!='auth-2'
                or data['mutation_epoch']!=2 or len(data['points'])!=2):
            raise RuntimeError('guard_writer_projection_result')
        if baseline is not None and baseline!=data['inventory_sha256']:
            raise RuntimeError('guard_writer_inventory_changed')
        baseline=data['inventory_sha256']
    async def denied():
        before=counter['scope']
        try:await read()
        except UnsupportedCapability:pass
        else:raise RuntimeError('guard_writer_drift_accepted')
        if counter['scope']!=before:
            counter['denied']+=counter['scope']-before
            raise RuntimeError('guard_writer_drift_reached_business_sql')
    try:
        import psycopg
        op=value['operator_config']
        operator=await psycopg.AsyncConnection.connect(host=op['host'],port=op['port'],dbname=op['dbname'],
            user=op['user'],passfile=op['passfile'],sslrootcert=op['sslrootcert'],sslmode='verify-full',
            connect_timeout=5,autocommit=True,options='-c statement_timeout=10000 -c lock_timeout=1000')
        if not operator.pgconn.ssl_in_use:raise RuntimeError('guard_writer_operator_tls_required')
        await resource.open();await writer.initialize(deadline=deadline);checks.append(CHECKS[0])
        await safe_read();checks.append(CHECKS[1])
        mutations=(
            ('GRANT SELECT(canonical_utf8) ON cragkit_qdrant.document_revisions TO cragkit_qdrant_security_guard',
             'REVOKE SELECT(canonical_utf8) ON cragkit_qdrant.document_revisions FROM cragkit_qdrant_security_guard'),
            ('ALTER ROLE cragkit_qdrant_security_guard LOGIN','ALTER ROLE cragkit_qdrant_security_guard NOLOGIN'),
            ("INSERT INTO cragkit_qdrant.schema_migrations(version,checksum_sha256) VALUES('9999_native_guard_admission_probe',repeat('0',64))",
             "DELETE FROM cragkit_qdrant.schema_migrations WHERE version='9999_native_guard_admission_probe'"),
            ("CREATE FUNCTION cragkit_qdrant.native_guard_admission_probe() RETURNS boolean LANGUAGE sql SECURITY DEFINER AS 'SELECT true'",
             'DROP FUNCTION cragkit_qdrant.native_guard_admission_probe()'),
        )
        for index,(apply,undo) in enumerate(mutations):
            await operator.execute(apply);restore=undo
            await denied();checks.append(CHECKS[index+2])
            await operator.execute(undo);restore=None
            await safe_read()
        await safe_read()
        checks.append(CHECKS[6])
        if resource._state!='open':raise RuntimeError('guard_writer_closed_borrowed_resource')
        await writer.close()
        async with resource.lease(deadline=deadline) as connection:
            async with connection.transaction():
                if await (await connection.execute('SELECT 1')).fetchall()!=[(1,)]:
                    raise RuntimeError('guard_writer_borrowed_lifetime')
        await resource.close()
        checks.append(CHECKS[7])
        return dict(runtime='python',checks=checks,proof_scope='profile4_writer_admission_only',
            scope_queries=counter['scope'],denied_scope_queries=counter['denied'])
    except BaseException as error:
        primary=error
        name=type(error).__name__
        failure=NativeGuardWriterFailure(dict(ok=False,step=len(checks),error=name if name in ERRORS else 'internal'))
        failure.primary=error
        raise failure from None
    finally:
        failures=[]
        cleanup_deadline=asyncio.get_running_loop().time()+12
        async def cleanup(operation,action):
            try:
                remaining=min(5,cleanup_deadline-asyncio.get_running_loop().time())
                if remaining<=0:raise TimeoutError()
                await asyncio.wait_for(action(),remaining)
            except BaseException as error:
                name=type(error).__name__
                failures.append(dict(operation=operation,outcome=name if name in ERRORS else "internal"))
        if restore is not None and operator is not None:
            await cleanup("catalog_restore",lambda:operator.execute(restore))
        if operator is not None:await cleanup("operator_pool_close",operator.close)
        await cleanup("writer_close",writer.close)
        await cleanup("writer_pool_close",resource.close)
        if failures:
            label=type(primary).__name__ if primary is not None else None
            raise NativeGuardWriterFailure(dict(ok=False,step=len(checks),error='cleanup_failed',
                primary=label if label in ERRORS else 'internal' if label else None,cleanup=failures)) from None
