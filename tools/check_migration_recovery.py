"""MRR-r1 explicit disposable upgrade/interruption/downgrade rehearsal; no providers."""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from check_postgres import migrations, migration_script
from check_postgres_profiles import profile_upgrade_script
from check_postgres_profile_storage import connect, refused, runtime_admission
from check_recorded_compatibility import NPM, WHEEL, package_files, product_paths
from evaluation_runtime import _regular_bytes
from check_qdrant_writer import read_bounded
from measure_default_resources import pressure_guard
from measure_native_resources import child
from postgres_vector_fixture import V6PostgresFixture
from run_release_evaluation import save

TENANT, COLLECTION = 'migration-tenant', 'migration-checks'
LEXICAL_SOURCE = 'Migration recovery preserves canonical source.'
VECTOR_SOURCE = 'Migration vector recovery preserves source.'
IDENTIFIER_SOURCE = 'Migration recovery identifier ERR_RECOVERY_42 remains exact.'
SCOPE = dict(tenant_id=TENANT, principal_id='migration-reader', grant_ids=['migration-grant'], authorization_revision='1')
OLD_ARTIFACTS = ROOT/'artifacts/V5/V5-08/full-core-frameworks/core'
OLD_WHEEL = OLD_ARTIFACTS/'python/cragkit-0.0.0-py3-none-any.whl'
OLD_NPM = OLD_ARTIFACTS/'npm/cragkit-0.0.0.tgz'
OLD_WHEEL_SHA = '42b6958b6239db2184f9fa814b88c16c9832d0e05886c198795a60febb3b224f'
OLD_NPM_SHA = 'f169baf931ba36492dd3c2be104f2f3aab105b811fb6e305f257b70b34a2bfe0'
OLD_ACCEPTANCE_SHA = '5893c532e2f152235f21a8df9522573655efa1022546bcce96969fe7cfae0895'
PHASE = 'arguments'


def require(value):
    if not value:
        raise RuntimeError('migration_recovery_invalid')


def safe_function_signature(error):
    """Recognize only fixed catalog function/type names from an undefined-function diagnostic."""
    if getattr(error,'sqlstate',None)!='42883':
        return None
    message=getattr(getattr(error,'diag',None),'message_primary',None)
    if type(message) is not str:
        return None
    matched=re.fullmatch(r'function ([a-z_][a-z0-9_.]*)\(([^()]*)\) does not exist',message)
    if matched is None:
        return None
    function=matched[1]
    parts=function.split('.')
    functions={'tsvector_send','tsvectorsend','vector_send','to_tsvector','to_jsonb','jsonb_agg',
        'jsonb_build_array','jsonb_build_object','octet_length','pg_get_functiondef','pg_get_expr',
        'pg_get_constraintdef','pg_get_triggerdef','to_regclass','to_regtype','to_regnamespace',
        'to_regprocedure','format_type','sha256','convert_to','substring','encode','array_position',
        'array_ndims','aclexplode','acldefault','pg_get_userbyid','pg_advisory_xact_lock'}
    types={'tsvector','cragkit_vector.vector','vector','text','unknown','bytea','regconfig','oid',
        'name','integer','bigint','smallint','character','"char"','int2vector','regtype','regclass',
        'anyelement','anyarray','jsonb','json','record','text[]','integer[]','cragkit.identity_text',
        'cragkit.identity_text[]','character varying','double precision','boolean','timestamp with time zone'}
    arguments=[] if not matched[2] else [part.strip() for part in matched[2].split(',')]
    if parts[-1] not in functions or len(parts)>2 or len(parts)==2 and parts[0] not in ('pg_catalog','cragkit_vector'):
        return None
    if any(argument not in types for argument in arguments):
        return None
    return dict(function=function,argument_types=arguments)


def safe_diagnostic(error):
    allowed = {'RuntimeError','ValueError','TypeError','KeyError','AttributeError','AssertionError',
        'Error','DatabaseError','OperationalError','ProgrammingError','IntegrityError',
        'UndefinedTable','UndefinedColumn','UndefinedFunction','InvalidTextRepresentation',
        'UniqueViolation','ForeignKeyViolation','CheckViolation','InsufficientPrivilege',
        'InFailedSqlTransaction','QueryCanceled','AdminShutdown','RepairError','ResourceCheckError'}
    category = type(error).__name__
    state = getattr(error,'sqlstate',None)
    diagnostic = dict(exception_type=category if category in allowed else 'OtherError',
        sqlstate=state if type(state) is str and re.fullmatch('[A-Z0-9]{5}',state) else None)
    repair_codes={'lexical_repair_'+suffix for suffix in ('invalid','artifact_drift','target_invalid',
        'history_invalid','catalog_invalid','owner_invalid','trigger_invalid','bound_exceeded',
        'ambiguous_key','state_changed','alias_invalid','vector_invalid','profile_invalid',
        'transaction_required','mode_invalid','update_count_invalid','idle_required',
        'optional_storage_unmanaged','setup_only_unsupported')}
    if category=='RepairError' and str(error) in repair_codes:
        diagnostic['operator_code']=str(error)
    if category=='ResourceCheckError' and str(error) in ('resource_pressure_unknown',
            'resource_pressure_stop','resource_swapping_stop'):
        diagnostic['resource_code']=str(error)
    signature=safe_function_signature(error)
    if signature is not None:
        diagnostic['function_signature']=signature
    trace, frame = error.__traceback__, None
    while trace is not None:
        code = trace.tb_frame.f_code
        if Path(code.co_filename).resolve() in (Path(__file__).resolve(),ROOT/'tools/repair_legacy_lexical_config.py') and code.co_name not in ('require','fetch'):
            frame = dict(file=Path(code.co_filename).name,function=code.co_name,line=trace.tb_lineno)
        trace = trace.tb_next
    diagnostic['code_frame'] = frame
    return diagnostic


async def lexical_configurations(admin):
    async with admin.transaction():
        await admin.execute('SET LOCAL search_path=pg_catalog')
        rows = await (await admin.execute("SELECT DISTINCT language_config::text, language_config::regconfig='pg_catalog.simple'::regconfig FROM cragkit.chunk_lexical ORDER BY 1")).fetchall()
    return [dict(value=value,resolves_to_pg_catalog_simple=equivalent,
        matches_reader_spelling=value=='pg_catalog.simple') for value,equivalent in rows]


def pause_before_commit(script):
    """Retain the pinned runner; insert one bounded observation window after DDL."""
    require(script.count('\nCOMMIT;') == 1 and 'pg_sleep(' not in script)
    return script.replace('\nCOMMIT;', '\nSELECT pg_sleep(20);\nCOMMIT;')


async def snapshot(admin, *, vector=False):
    tables = ['migration_history', 'collections', 'documents', 'document_revisions',
        'index_generations', 'chunks', 'chunk_lexical', 'document_grants', 'ingestion_jobs']
    if vector:
        tables += ['chunk_vectors_fake_1536']
    result = {}
    for table in tables:
        row = await (await admin.execute(f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb)::text FROM cragkit.{table} t")).fetchone()
        result[table] = sha256(row[0].encode()).hexdigest()
    ledger = await (await admin.execute("SELECT jsonb_agg(jsonb_build_array(version,checksum,applied_at) ORDER BY version) FROM cragkit.migration_history")).fetchone()
    result['lexical_ledger'] = ledger[0]
    if vector:
        for name, where in (('setup_history', ''), ('legacy_setup_history', " WHERE version IN ('0001_pgvector','0002_vector_profiles')")):
            row = await (await admin.execute("SELECT coalesce(jsonb_agg(jsonb_build_array(version,checksum,applied_at) ORDER BY version),'[]'::jsonb)::text FROM cragkit_vector.setup_history"+where)).fetchone()
            result[name] = sha256(row[0].encode()).hexdigest()
    return result


async def seed_lexical(admin):
    from cragkit._identifiers import extract_identifiers
    async with admin.transaction():
        await admin.execute('INSERT INTO cragkit.collections(tenant_id,collection_id) VALUES (%s,%s)',(TENANT,COLLECTION))
        for prefix,source in (('lexical',LEXICAL_SOURCE),('identifier',IDENTIFIER_SOURCE)):
            identity=(TENANT,COLLECTION,prefix+'-document')
            revision,generation,chunk=(prefix+'-'+kind for kind in ('revision','generation','chunk'))
            digest=sha256(source.encode()).hexdigest()
            await admin.execute("INSERT INTO cragkit.documents(tenant_id,collection_id,document_id,authorization_revision) VALUES (%s,%s,%s,'1')",identity)
            await admin.execute("INSERT INTO cragkit.document_revisions(tenant_id,collection_id,document_id,revision_id,source_sha256,source_locator,canonical_text,canonical_sha256,parser_id) VALUES (%s,%s,%s,%s,%s,'fixture:migration',%s,%s,'fixture.v1')",(*identity,revision,digest,source,digest))
            await admin.execute("INSERT INTO cragkit.index_generations(tenant_id,collection_id,document_id,revision_id,generation_id,chunker_profile,lexical_profile,expected_chunk_count,status) VALUES (%s,%s,%s,%s,%s,'fixture.v1','native_fts.v1',1,'ready')",(*identity,revision,generation))
            await admin.execute("INSERT INTO cragkit.chunks(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,ordinal,start_byte,end_byte,text,text_sha256) VALUES (%s,%s,%s,%s,%s,%s,0,0,%s,%s,%s)",(*identity,revision,generation,chunk,len(source.encode()),source,digest))
            await admin.execute("INSERT INTO cragkit.chunk_lexical(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,search_vector,identifier_tokens) VALUES (%s,%s,%s,%s,%s,%s,''::tsvector,%s::cragkit.identity_text[])",(*identity,revision,generation,chunk,list(extract_identifiers(source))))
            await admin.execute("INSERT INTO cragkit.document_grants(tenant_id,collection_id,document_id,grant_id,principal_id,authorization_revision) VALUES (%s,%s,%s,'migration-grant','migration-reader','1')",identity)
            await admin.execute("UPDATE cragkit.documents SET active_generation_id=%s WHERE tenant_id=%s AND collection_id=%s AND document_id=%s",(generation,*identity))


async def seed_vector(roles):
    from cragkit._postgres_pool import PoolConfig, PoolResource
    from cragkit.contracts import parse_scope
    from cragkit.embeddings import EmbeddingAdapter, FAKE_PROFILE
    from cragkit.vector_ingestion import PostgresVectorIndexer
    class Counter:
        name = 'fake-byte-v1'
        def count(self, text):
            return len(text.encode())
    async def transport(body, *, deadline, max_response_bytes):
        value = json.loads(body)
        tokens = sum(len(text.encode()) for text in value['input'])
        return json.dumps(dict(model=FAKE_PROFILE.model, data=[dict(index=i,embedding=[1.]+[0.]*1535)
            for i in range(len(value['input']))], usage=dict(prompt_tokens=tokens,total_tokens=tokens))).encode()
    scope = parse_scope(SCOPE)
    async def authorize(candidate, collection, document):
        return candidate == scope and collection == COLLECTION and document == 'vector-document'
    configuration = dict(roles.writer)
    for field in ('sslrootcert','passfile'):
        configuration[field] = Path(configuration[field])
    writer = PoolResource(PoolConfig.model_validate(configuration))
    await writer.open()
    try:
        return await PostgresVectorIndexer(writer, authorize_write=authorize,
            embedder=EmbeddingAdapter(transport,Counter())).ingest(VECTOR_SOURCE,
                collection=COLLECTION,document_id='vector-document',intent_id='migration-vector-intent',
                source_locator='fixture:migration-vector',scope=scope,deadline=asyncio.get_running_loop().time()+20)
    finally:
        await writer.close()


async def terminate_upgrade(config, observer):
    """Only terminate the native backend created and observed by this function."""
    import psycopg
    worker = await connect(config)
    task = None
    try:
        pid = worker.info.backend_pid
        task = asyncio.create_task(worker.execute(pause_before_commit(profile_upgrade_script(apply=True))))
        deadline = asyncio.get_running_loop().time()+5
        while True:
            row = await (await observer.execute("SELECT state,wait_event FROM pg_stat_activity WHERE pid=%s", (pid,))).fetchone()
            if row == ('active','PgSleep'):
                break
            if task.done():
                await task
                require(False)
            require(asyncio.get_running_loop().time() < deadline)
            await asyncio.sleep(.02)
        require(await (await observer.execute('SELECT pg_terminate_backend(%s)',(pid,))).fetchone() == (True,))
        try:
            await asyncio.wait_for(task,5)
        except psycopg.OperationalError:
            require(worker.closed)
        else:
            require(False)
        return dict(observed_after_writes=True, wait_event='PgSleep', backend_terminated=True)
    finally:
        if task is not None and not task.done():
            await observer.execute('SELECT pg_terminate_backend(%s)',(worker.info.backend_pid,))
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        await worker.close()


def validate_package(value,runtime,*,expected_version,upgraded,unmodified=False):
    require(expected_version in ('0.0.0','1.0.0rc1','1.0.0-rc.1'))
    require(value == dict(runtime=runtime, version=expected_version, installed_bytes_verified=True,
        lexical='unsupported_capability' if unmodified else 'complete',
        identifier='unsupported_capability' if unmodified else 'complete',
        dense='unsupported_capability' if upgraded and expected_version=='0.0.0' else 'complete'))


def validate_old(value,runtime,*,upgraded,unmodified=False):
    validate_package(value,runtime,expected_version='0.0.0',upgraded=upgraded,unmodified=unmodified)


async def package_admission(args, reader, *, upgraded, expected_sources, unmodified=False):
    require(sha256(_regular_bytes(OLD_WHEEL,16*1024*1024)).hexdigest() == OLD_WHEEL_SHA
        and sha256(_regular_bytes(OLD_NPM,16*1024*1024)).hexdigest() == OLD_NPM_SHA
        and sha256(_regular_bytes(OLD_ARTIFACTS/'acceptance.json',4*1024*1024)).hexdigest() == OLD_ACCEPTANCE_SHA)
    common = dict(reader_config=reader,collection=COLLECTION,scope=SCOPE,expected_sources=expected_sources)
    bundle=ROOT/'artifacts/V6/hosted-candidate-0c7c568'
    metadata=json.loads(_regular_bytes(ROOT/'artifacts/V6/ci-bundle-audit.json',4*1024*1024))
    current_products=product_paths(bundle,metadata,ROOT/'artifacts/V6/hosted-candidate-0c7c568.zip')
    result=dict(current_products=current_products)
    for name,python,node_root,wheel,npm in (
        ('historical',args.old_python,args.old_node_root,OLD_WHEEL,OLD_NPM),
        ('current',Path(sys.executable),args.sdk_root,bundle/WHEEL,bundle/NPM)):
        result[name]=[]
        for runtime in ('python','node'):
            expected_version='0.0.0' if name=='historical' else '1.0.0rc1' if runtime=='python' else '1.0.0-rc.1'
            files=package_files(wheel,'cragkit/',wheel=True) if runtime=='python' else package_files(npm,'package/dist/')
            argv=[str(python),'-I','-B',str(ROOT/'tools/migration_package_probe.py')] if runtime=='python' else [shutil.which('node'),str(ROOT/'tools/migration_package_probe.mjs'),str(node_root.resolve())]
            value=await child(argv,{**common,'files':files,'expected_version':expected_version},timeout=45)
            validate_package(value,runtime,expected_version=expected_version,upgraded=upgraded,unmodified=unmodified)
            result[name].append(value)
    return result


def guard_pressure(records,output,phase):
    global PHASE
    PHASE='pressure_'+phase
    try:
        pressure_guard(records)
    except Exception as error:
        code=str(error) if str(error) in ('resource_pressure_unknown','resource_pressure_stop',
            'resource_swapping_stop') else 'resource_check_failed'
        save(output/'pressure-stop.json',dict(state='stopped',phase=phase,code=code,prior_observations=records))
        raise
    save(output/('pressure-'+str(len(records)).zfill(2)+'.json'),dict(phase=phase,observation=records[-1]))


async def operator_cli(config,target,mode,expected_returncode):
    arguments=[sys.executable,'-I','-B',str(ROOT/'tools/repair_legacy_lexical_config.py'),
        '--'+mode,'--config',str(config),'--expected-database',target['expected_database'],
        '--expected-owner',target['expected_owner'],'--confirm-dedicated-target']
    environment={name:os.environ[name] for name in ('PATH','LANG','LC_ALL','LC_CTYPE','TMPDIR','TZ') if name in os.environ}
    process=await asyncio.create_subprocess_exec(*arguments,stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=environment)
    jobs=[asyncio.create_task(read_bounded(process.stdout,131072)),
        asyncio.create_task(read_bounded(process.stderr,16384))]
    try:
        async with asyncio.timeout(30):
            raw,errors=await asyncio.gather(*jobs)
            await process.wait()
        require(process.returncode==expected_returncode and not errors)
        receipt=json.loads(raw)
        require(receipt['commit_state']=='committed')
        return dict(returncode=process.returncode,receipt=receipt)
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(),5)
            except TimeoutError:
                process.kill();await asyncio.wait_for(process.wait(),5)
        for job in jobs:
            if not job.done():job.cancel()
        await asyncio.gather(*jobs,return_exceptions=True)


def listener_closed(address):
    try:
        connection=socket.create_connection(address,timeout=.2)
    except ConnectionRefusedError:
        return
    connection.close()
    require(False)


async def repair_target(admin):
    row=await (await admin.execute('SELECT current_database(),current_user')).fetchone()
    return dict(expected_database=row[0],expected_owner=row[1])


async def lexical_only_repair(args):
    global PHASE
    from repair_legacy_lexical_config import repair
    with V6PostgresFixture(args.prepared_postgres_bin,args.output/'lexical-only') as fixture:
        address=fixture.config['host'],fixture.config['port']
        async with await connect(fixture.config) as admin:
            sequence=migrations(ROOT/'storage/postgres/migrations')
            await admin.execute(migration_script(sequence[:1],apply=True))
            await seed_lexical(admin)
            await admin.execute(migration_script(sequence,apply=True))
            await admin.execute((ROOT/'storage/postgres/deployment/neon.sql').read_text())
            target=await repair_target(admin)
            PHASE='lexical_only_check'
            check=await repair(admin,**target)
            require(check['state']=='repair_required' and check['changed_rows']==0
                and check['before_sha256']==check['after_sha256'])
            save(args.output/'lexical-only-check.json',check)
            config=args.output/'lexical-only/operator-config.json'
            save(config,fixture.config)
            try:
                PHASE='operator_cli_pending_check'
                pending=await operator_cli(config,target,'check',2)
                require(pending['receipt']['state']=='repair_required' and pending['receipt']['changed_rows']==0)
                PHASE='operator_cli_apply'
                cli_apply=await operator_cli(config,target,'apply',0)
                applied=cli_apply['receipt']
                require(applied['state']=='repaired' and applied['changed_rows']==2)
                PHASE='operator_cli_canonical_check'
                canonical=await operator_cli(config,target,'check',0)
                require(canonical['receipt']['state']=='already_canonical' and canonical['receipt']['changed_rows']==0)
            finally:
                config.unlink()
            save(args.output/'lexical-only-apply.json',applied)
            PHASE='lexical_only_idempotence'
            repeated=await repair(admin,**target,apply=True)
            require(repeated['state']=='already_canonical' and repeated['changed_rows']==0
                and repeated['before_sha256']==applied['after_sha256']==repeated['after_sha256'])
            require(await (await admin.execute("SELECT to_regnamespace('cragkit_vector') IS NULL")).fetchone()==(True,))
    listener_closed(address)
    result=dict(check=check,apply=applied,idempotent=repeated,
        cli_check_apply_check=[pending,cli_apply,canonical],private_config_removed=True,
        optional_storage_created=False,cleanup_verified=True)
    save(args.output/'lexical-only-repair.json',result)
    return result


async def interrupt_repair(config,observer,target):
    import psycopg
    from repair_legacy_lexical_config import repair_in_transaction
    worker=await connect(config)
    pending=[]
    async def run_worker():
        async with worker.transaction():
            pending.append(await repair_in_transaction(worker,**target,apply=True))
            require(pending[-1]['commit_state']=='pending')
            await worker.execute('SELECT pg_sleep(20)')
    task=asyncio.create_task(run_worker())
    pid=worker.info.backend_pid
    try:
        deadline=asyncio.get_running_loop().time()+5
        while True:
            row=await (await observer.execute('SELECT state,wait_event FROM pg_stat_activity WHERE pid=%s',(pid,))).fetchone()
            if row==('active','PgSleep'):
                break
            if task.done():
                await task
                require(False)
            require(asyncio.get_running_loop().time()<deadline)
            await asyncio.sleep(.02)
        require(await (await observer.execute('SELECT pg_terminate_backend(%s)',(pid,))).fetchone()==(True,))
        try:
            await asyncio.wait_for(task,5)
        except psycopg.OperationalError:
            require(worker.closed)
        else:
            require(False)
        require(len(pending)==1 and pending[0]['changed_rows']==2)
        return dict(observed_after_validated_update=True,wait_event='PgSleep',backend_terminated=True,
            receipt_commit_state=pending[0]['commit_state'])
    finally:
        if not task.done():
            await observer.execute('SELECT pg_terminate_backend(%s)',(pid,))
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        await worker.close()


async def repair_cases(fixture,admin,output):
    global PHASE
    import psycopg
    from repair_legacy_lexical_config import RepairError, repair, repair_in_transaction
    target=await repair_target(admin)
    before=await snapshot(admin,vector=True)
    PHASE='operator_check'
    check=await repair(admin,**target)
    require(check['state']=='repair_required' and check['required_rows']==2 and check['changed_rows']==0
        and check['before_sha256']==check['after_sha256'])
    save(output/'operator-check.json',check)
    checks=['check_reports_required_without_mutation']
    PHASE='operator_wrong_target'
    try:
        await repair(admin,**{**target,'expected_database':'not-the-fixture'})
    except RepairError as error:
        require(str(error)=='lexical_repair_target_invalid')
    else:
        require(False)
    checks.append('wrong_target_refused')
    mutations=(
        ('history',("UPDATE cragkit.migration_history SET checksum=repeat('a',64)",),'lexical_repair_history_invalid'),
        ('unknown_setup',("INSERT INTO cragkit_vector.setup_history(version,checksum) VALUES('0004_probe',repeat('a',64))",),'lexical_repair_history_invalid'),
        ('column_default',("ALTER TABLE cragkit.chunk_lexical ALTER COLUMN language_config SET DEFAULT 'simple'",),'lexical_repair_catalog_invalid'),
        ('generation_profile',("UPDATE cragkit.index_generations SET lexical_profile='unsupported' WHERE document_id='lexical-document'",),'lexical_repair_vector_invalid'),
        ('configuration',("UPDATE cragkit.chunk_lexical SET language_config='pg_catalog.english' WHERE document_id='lexical-document'",),'lexical_repair_vector_invalid'),
        ('vector',("ALTER TABLE cragkit.chunk_lexical DISABLE TRIGGER canonical_lexical_vector",
            "UPDATE cragkit.chunk_lexical SET search_vector=to_tsvector('pg_catalog.simple','corruption') WHERE document_id='lexical-document'",
            "ALTER TABLE cragkit.chunk_lexical ENABLE TRIGGER canonical_lexical_vector"),'lexical_repair_vector_invalid'),
        ('disabled_trigger',("ALTER TABLE cragkit.chunk_lexical DISABLE TRIGGER canonical_lexical_vector",),'lexical_repair_trigger_invalid'),
        ('replaced_function',("CREATE OR REPLACE FUNCTION cragkit.refresh_lexical_vector() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS 'BEGIN RETURN NEW; END'",),'lexical_repair_trigger_invalid'),
        ('extra_trigger',("CREATE TRIGGER extra_probe BEFORE UPDATE ON cragkit.chunk_lexical FOR EACH ROW EXECUTE FUNCTION cragkit.refresh_lexical_vector()",),'lexical_repair_trigger_invalid'),
    )
    for name,statements,code in mutations:
        PHASE='operator_probe_'+name
        async with admin.transaction(force_rollback=True):
            for statement in statements:
                await admin.execute(statement)
            drifted=await snapshot(admin,vector=True)
            try:
                await repair_in_transaction(admin,**target,apply=True)
            except RepairError as error:
                require(str(error)==code)
            else:
                require(False)
            require(await snapshot(admin,vector=True)==drifted)
        require(await snapshot(admin,vector=True)==before)
        checks.append(name+'_refused_without_repair')
        save(output/('operator-probe-'+name+'.json'),dict(state='passed',refusal_code=code,
            fixture_changes_rolled_back=True))
    PHASE='operator_writer_lock'
    async with await connect(fixture.config) as blocker:
        async with blocker.transaction():
            await blocker.execute('LOCK TABLE cragkit.chunk_lexical IN ROW EXCLUSIVE MODE')
            try:
                await repair(admin,**target,apply=True)
            except psycopg.Error as error:
                require(error.sqlstate=='55P03')
            else:
                require(False)
    require(await snapshot(admin,vector=True)==before)
    checks.append('writer_lock_refused_with_bounded_timeout')
    save(output/'operator-writer-lock.json',dict(state='passed',sqlstate='55P03',fixture_changes_rolled_back=True))
    PHASE='operator_interrupted_apply'
    interruption=await interrupt_repair(fixture.config,admin,target)
    require(await snapshot(admin,vector=True)==before)
    checks.append('native_interrupted_repair_preserves_uncommitted_alias_state')
    save(output/'operator-interruption.json',interruption)
    PHASE='operator_successful_retry'
    applied=await repair(admin,**target,apply=True)
    require(applied['state']=='repaired' and applied['changed_rows']==2 and applied['commit_state']=='committed')
    save(output/'operator-apply.json',applied)
    PHASE='operator_idempotence'
    repeated=await repair(admin,**target,apply=True)
    require(repeated['state']=='already_canonical' and repeated['changed_rows']==0
        and repeated['before_sha256']==applied['after_sha256']==repeated['after_sha256'])
    checks.append('explicit_retry_repairs_mixed_rows_and_is_idempotent')
    result=dict(checks=checks,check=check,apply=applied,idempotent=repeated,interruption=interruption)
    save(output/'operator-repair.json',result)
    return result


async def run(args):
    global PHASE
    require(sys.flags.isolated and sys.dont_write_bytecode)
    require(not any(os.environ.get(k) for k in ('PYTHONPATH','PYTHONHOME','NODE_PATH','NODE_OPTIONS')))
    require(Path(sys.prefix).resolve() == (args.sdk_root.resolve().parent/'python/.venv').resolve())
    args.output.mkdir(mode=0o700)
    checks, compatibility, pressures = [], {}, []
    guard_pressure(pressures,args.output,'before_lexical_fixture')
    PHASE='lexical_only_repair'
    lexical_only=await lexical_only_repair(args)
    guard_pressure(pressures,args.output,'after_lexical_fixture')
    guard_pressure(pressures,args.output,'before_full_fixture')
    PHASE = 'fixture'
    with V6PostgresFixture(args.prepared_postgres_bin,args.output/'postgres') as fixture:
        address = fixture.config['host'],fixture.config['port']
        async with await connect(fixture.config) as admin:
            PHASE = 'lexical_initial_apply'
            sequence = migrations(ROOT/'storage/postgres/migrations')
            await admin.execute(migration_script(sequence[:1],apply=True))
            PHASE = 'lexical_seed'
            await seed_lexical(admin)
            PHASE = 'lexical_snapshot_before'
            before = await snapshot(admin)
            before_configurations = await lexical_configurations(admin)
            PHASE = 'lexical_upgrade_apply'
            await admin.execute(migration_script(sequence,apply=True))
            PHASE = 'lexical_snapshot_compare'
            after = await snapshot(admin)
            lexical_type = await (await admin.execute("SELECT format_type(atttypid,atttypmod) FROM pg_attribute WHERE attrelid='cragkit.chunk_lexical'::regclass AND attname='language_config'")).fetchone()
            save(args.output/'lexical-upgrade-observation.json', dict(
                revision='MRR-r1', state='observed', column_type=lexical_type[0],
                before_configurations=before_configurations,
                configurations=await lexical_configurations(admin),
                before_sha256={key:value for key,value in before.items() if key!='lexical_ledger'},
                after_sha256={key:value for key,value in after.items() if key!='lexical_ledger'},
                prior_migration_rows_and_timestamps_preserved=after['lexical_ledger'][:1]==before['lexical_ledger'],
                fixture_normalized=False))
            require(all(after[k] == v for k,v in before.items() if k not in ('migration_history','lexical_ledger'))
                and after['lexical_ledger'][:1] == before['lexical_ledger'] and len(after['lexical_ledger'])==2)
            PHASE = 'lexical_type_check'
            require(lexical_type == ('text',))
            PHASE = 'lexical_readonly_check'
            await admin.execute(migration_script(sequence,apply=False))
            require(await snapshot(admin) == after)
            checks.append('lexical_0001_to_0002_preserves_source_active_generation_and_prior_timestamp')
        guard_pressure(pressures,args.output,'after_lexical_upgrade')
        PHASE = 'fake_vector_setup'
        roles = await fixture.provision(tenants=(TENANT,),collections=(COLLECTION,))
        vector_receipt=await seed_vector(roles)
        expected_sources={name:dict(text=text,sha256=sha256(text.encode()).hexdigest(),revision_id=revision)
            for name,text,revision in (
                ('lexical-document',LEXICAL_SOURCE,'lexical-revision'),
                ('identifier-document',IDENTIFIER_SOURCE,'identifier-revision'),
                ('vector-document',VECTOR_SOURCE,vector_receipt.revision_id))}
        guard_pressure(pressures,args.output,'after_vector_setup')
        async with await connect(fixture.config) as admin:
            before = await snapshot(admin,vector=True)
            require(await (await admin.execute('SELECT count(*) FROM cragkit.chunk_vectors_fake_1536')).fetchone() == (1,))
            PHASE = 'package_admission_before'
            unmodified=await package_admission(args,roles.reader,upgraded=False,
                expected_sources=expected_sources,unmodified=True)
            compatibility['unmodified_0002']=dict(state='failed_unmodified_upgrade',observations=unmodified)
            save(args.output/'unmodified-upgrade-observation.json',compatibility['unmodified_0002'])
            guard_pressure(pressures,args.output,'before_operator_repair')
            PHASE='explicit_operator_repair'
            operator_repair=await repair_cases(fixture,admin,args.output)
            guard_pressure(pressures,args.output,'after_operator_repair')
            PHASE='package_admission_after_repair'
            compatibility['after_repair_before_profile_0003']=await package_admission(args,roles.reader,
                upgraded=False,expected_sources=expected_sources)
            save(args.output/'repaired-package-observation.json',compatibility['after_repair_before_profile_0003'])
            before=await snapshot(admin,vector=True)
            PHASE = 'backend_interruption'
            interruption = await terminate_upgrade(fixture.config,admin)
            require(await snapshot(admin,vector=True) == before)
            require(await (await admin.execute("SELECT to_regclass('cragkit.chunk_vectors_openai_te3small_1536') IS NULL")).fetchone() == (True,))
            checks.append('observed_native_backend_termination_preserves_prior_committed_state')
            await runtime_admission(roles.reader,live=False,accepted=True)
            guard_pressure(pressures,args.output,'before_profile_upgrade')
            PHASE = 'profile_upgrade'
            await admin.execute(profile_upgrade_script(apply=True))
            after = await snapshot(admin,vector=True)
            require(all(after[k] == v for k,v in before.items() if k!='setup_history'))
            await admin.execute(profile_upgrade_script(apply=False))
            await admin.execute(profile_upgrade_script(apply=True))
            require(await snapshot(admin,vector=True) == after)
            checks.append('profile_upgrade_readonly_and_idempotence_preserve_prior_rows_and_timestamps')
            PHASE='operator_setup3_check'
            from repair_legacy_lexical_config import repair
            profile_target=await repair_target(admin)
            upgraded_operator_check=await repair(admin,**profile_target)
            require(upgraded_operator_check['state']=='already_canonical'
                and upgraded_operator_check['changed_rows']==0
                and upgraded_operator_check['before_sha256']==upgraded_operator_check['after_sha256'])
            save(args.output/'operator-setup3-check.json',upgraded_operator_check)
            checks.append('operator_setup3_check_only_noop')
            await runtime_admission(roles.reader,live=False,accepted=True)
            PHASE = 'package_admission_after_profile'
            compatibility['after_profile_0003'] = await package_admission(args,roles.reader,upgraded=True,
                expected_sources=expected_sources)
            save(args.output/'upgraded-package-observation.json',compatibility['after_profile_0003'])
            checks.append('both_products_lexical_identifier_exact_current_dense_works_old_dense_refuses')
            guard_pressure(pressures,args.output,'after_profile_checks')
            PHASE = 'history_drift'
            await admin.execute("INSERT INTO cragkit_vector.setup_history(version,checksum) VALUES ('0004_rehearsal_unknown',repeat('a',64))")
            drifted = await snapshot(admin,vector=True)
            await refused(admin,profile_upgrade_script(apply=True))
            require(await snapshot(admin,vector=True) == drifted)
            checks.append('unknown_history_refused_without_deleting_or_repairing_ledger')
    PHASE = 'cleanup'
    listener_closed(address)
    guard_pressure(pressures,args.output,'after_full_fixture')
    result = dict(revision='MRR-r2',lane='upgrade_with_required_operator_repair',state='passed',checks=checks,
        unmodified_upgrade_accepted=False,required_operator_repair=operator_repair,lexical_only_repair=lexical_only,
        interruption=interruption,package_compatibility=compatibility,
        upgraded_operator_check=upgraded_operator_check,pressure=pressures,
        old_artifacts=dict(wheel_sha256=OLD_WHEEL_SHA,npm_sha256=OLD_NPM_SHA,
            acceptance_sha256=OLD_ACCEPTANCE_SHA),
        migration_artifacts={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest()
            for area in ('migrations','setup') for p in sorted((ROOT/'storage/postgres'/area).glob('*.sql'))},
        upgraded_snapshot=after,production_rollback_eligible=False,live_provider_calls=0,cleanup_verified=True)
    save(args.output/'results.json',result)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('old-python','old-node-root','sdk-root','prepared-postgres-bin','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--allow-local-processes',action='store_true',required=True)
    try:
        result=asyncio.run(run(parser.parse_args(argv)))
        print(json.dumps(dict(revision=result['revision'],state=result['state'],checks=len(result['checks']))))
        return 0
    except Exception as error:
        print(json.dumps(dict(revision='MRR-r2',state='failed',phase=PHASE,
            code='migration_recovery_invalid',**safe_diagnostic(error))))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
