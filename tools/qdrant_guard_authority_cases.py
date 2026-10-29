"""Actual native reader profile admission and grant drift; no source publication."""
from __future__ import annotations

from copy import deepcopy
import json

CHECKS=(
    'four_migration_reader_admission_with_exact_guard_shape',
    'unpublished_scoped_read_returns_no_source_bytes',
    'committed_sensitive_guard_grant_refused_before_source_sql',
    'guard_owner_login_drift_refused_before_source_sql',
    'fifth_history_row_refused_after_initialization',
    'extra_definer_refused_without_legacy_fallback',
    'permission_and_catalog_restoration_allows_safe_source_read',
    'borrowed_resources_close_and_no_provider_activity',
)
ERRORS=('InvalidRequest','UnsupportedCapability','UnauthorizedScope','ProviderUnavailable','IntegrityViolation',
        'DeadlineExceeded','CancelledError','AbortError','internal','cleanup_failed')


def failure_observation(value):
    if (type(value) is not dict or value.get('ok') is not False or type(value.get('step')) is not int
            or not 0<=value['step']<=len(CHECKS) or type(value.get('error')) is not str or value['error'] not in ERRORS):
        raise RuntimeError('guard_authority_native_failure_shape')
    if value['error']=='cleanup_failed':
        if set(value)!={'ok','step','error','primary','cleanup'} or type(value['cleanup']) is not list or not 1<=len(value['cleanup'])<=8:
            raise RuntimeError('guard_authority_native_failure_shape')
        if value['primary'] is not None and (type(value['primary']) is not str or value['primary'] not in ERRORS or value['primary']=='cleanup_failed'):
            raise RuntimeError('guard_authority_native_failure_shape')
        for record in value['cleanup']:
            if (type(record) is not dict or set(record)!={'operation','outcome'}
                    or type(record['operation']) is not str or record['operation'] not in ('catalog_restore','reader_pool_close','operator_pool_close','factory_pool_close')
                    or type(record['outcome']) is not str or record['outcome'] not in ERRORS):
                raise RuntimeError('guard_authority_native_failure_shape')
    elif set(value)!={'ok','step','error'}:
        raise RuntimeError('guard_authority_native_failure_shape')
    return json.loads(json.dumps(value))


class NativeGuardAuthorityFailure(RuntimeError):
    def __init__(self,observation):
        super().__init__('guard_authority_native_case_failed')
        self.observation=failure_observation(observation)


def authority_inputs(dataset):
    inputs=dataset['inputs']
    point=deepcopy(inputs['expected_points'][0])
    point['payload']['authorization_revision']='auth-2'
    return dict(config=deepcopy(inputs['config']),scope=deepcopy(dataset['scope']),
        request=dict(query='synthetic profile four source lookup',collection=dataset['scope'].get('collection',inputs['stage']['manifest']['collection']),required_filters=[]),
        nomination=dict(point_id=point['id'],branch='dense',score=.75,score_kind='cosine_similarity',
            score_direction='higher_is_better',verification='UNVERIFIED',payload=point['payload']))


async def python_guard_authority_cases(value):
    import asyncio
    from pathlib import Path
    from cragkit._postgres_pool import PoolConfig,PoolResource,_owned_pool
    from cragkit._qdrant_authority import PostgresQdrantAuthority
    from cragkit._qdrant_contract import parse_model,QdrantConfig
    from cragkit._qdrant_source import validate_nomination
    from cragkit.contracts import RetrievalRequest,TrustedScope
    from cragkit.errors import UnsupportedCapability

    raw=dict(value['reader_config'])
    for key in ('sslrootcert','passfile'):raw[key]=Path(raw[key])
    configuration=PoolConfig.model_validate(raw)
    if configuration.max_size!=1:raise RuntimeError('guard_authority_reader_client_ceiling')
    counter=dict(source=0,denied=0)
    class Connection:
        def __init__(self,actual):self.actual=actual
        def __getattr__(self,name):return getattr(self.actual,name)
        async def execute(self,statement,params=None,**options):
            if type(statement) is str and 'JOIN cragkit_qdrant.members m' in statement:counter['source']+=1
            return await self.actual.execute(statement,params,**options)
    class Pool:
        def __init__(self,config):self.actual=_owned_pool(config)
        def __getattr__(self,name):return getattr(self.actual,name)
        async def getconn(self,**options):return Connection(await self.actual.getconn(**options))
        async def putconn(self,connection):await self.actual.putconn(connection.actual)
    resource=PoolResource(configuration,factory=Pool)
    authority=PostgresQdrantAuthority(resource)
    inputs=value['inputs']
    request=parse_model(RetrievalRequest,inputs['request']);scope=parse_model(TrustedScope,inputs['scope'])
    config=parse_model(QdrantConfig,inputs['config'])
    nomination=validate_nomination(inputs['nomination'],request,scope,config)
    deadline=asyncio.get_running_loop().time()+120
    checks=[];operator=None;primary=None;restore=None
    async def read():return await authority.read(nomination,request,scope,config,retained=False,max_source_bytes=32768,deadline=deadline)
    async def safe_read():
        before=counter['source']
        if await read()!=[] or counter['source']!=before+1:
            raise RuntimeError('guard_authority_unpublished_source_result')
    async def denied():
        before=counter['source']
        try:await read()
        except UnsupportedCapability:pass
        else:raise RuntimeError('guard_authority_drift_accepted')
        if counter['source']!=before:
            counter['denied']+=counter['source']-before
            raise RuntimeError('guard_authority_drift_reached_source_sql')
    try:
        import psycopg
        op=value['operator_config']
        operator=await psycopg.AsyncConnection.connect(host=op['host'],port=op['port'],dbname=op['dbname'],
            user=op['user'],passfile=op['passfile'],sslrootcert=op['sslrootcert'],sslmode='verify-full',
            connect_timeout=5,autocommit=True,options='-c statement_timeout=10000 -c lock_timeout=1000')
        if not operator.pgconn.ssl_in_use:raise RuntimeError('guard_authority_operator_tls_required')
        await resource.open();await authority.initialize(deadline=deadline);checks.append(CHECKS[0])
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
        if resource._state!='open':raise RuntimeError('guard_authority_closed_borrowed_resource')
        await resource.close()
        checks.append(CHECKS[7])
        return dict(runtime='python',checks=checks,proof_scope='profile4_authority_admission_only',
            source_queries=counter['source'],denied_source_queries=counter['denied'])
    except BaseException as error:
        primary=error
        name=type(error).__name__
        failure=NativeGuardAuthorityFailure(dict(ok=False,step=len(checks),error=name if name in ERRORS else 'internal'))
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
        await cleanup("reader_pool_close",resource.close)
        if failures:
            label=type(primary).__name__ if primary is not None else None
            raise NativeGuardAuthorityFailure(dict(ok=False,step=len(checks),error='cleanup_failed',
                primary=label if label in ERRORS else 'internal' if label else None,cleanup=failures)) from None
