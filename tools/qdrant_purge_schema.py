"""QP-r1 metadata and real PostgreSQL probes; no Qdrant absence is established."""
from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path
import re

from qdrant_authority_schema import ROOT, literal
from qdrant_publication_schema import DELIMITER, PublicationMigration, insert_sql, rejected_sql
from runtime_diagnostics import CleanupFailure

MIGRATION = ROOT/'storage/qdrant/postgres/migrations/0005_security_owners_and_erasure.sql'
PURGER_ROLE = 'cragkit_qdrant_purger'
ARGUMENTS = ('p_instance_id','p_backend_namespace','p_storage_identity','p_supervisor_id','p_backend_epoch',
    'p_physical_collection','p_collection_incarnation','p_tenant_id','p_collection','p_document_id',
    'p_purge_intent_id','p_purge_payload_sha256','p_owner_token','p_tombstone_payload_sha256',
    'p_authorization_revision','p_mutation_epoch','p_inventory_bytes','p_inventory_sha256','p_policy_id',
    'p_absence_sha256')
TYPES = ('text','text','text','text','bigint','text','text','text','text','text','text','text','uuid',
    'text','text','bigint','bytea','text','text','text')
SIGNATURE = 'cragkit_qdrant.erase_purged_document('+','.join(TYPES)+')'
POLICY = 'erase_managed_source_and_replay_v1'
BODY_COLUMNS = {'document_revisions': ('canonical_utf8',), 'members': ('excerpt_utf8',),
    'vector_replays': ('dense_blob','sparse_blob'), 'dispatch_journal': ('request_bytes',)}
TARGET = 'tenant_id=%s AND collection=%s AND document_id=%s'
CHECKS = (
    'exact_purger_signature_owner_attributes_and_role',
    'minimum_effective_purger_permissions_and_force_rls',
    'restricted_writer_login_only_no_admin_supervisor_reader_or_set_role',
    'malformed_arguments_and_inventory_rejected_without_mutation',
    'changed_target_backend_owner_and_binding_rejected_without_mutation',
    'all_pending_target_journal_states_refuse_erasure',
    'intermediate_nulling_failure_rolls_back_every_body_marker_record_and_flag',
    'authorized_sql_erasure_and_historical_exact_retry_metadata_only',
    'retained_metadata_immutable_body_restore_and_new_body_insert_denied',
    'unsafe_effective_purger_grant_rejected_and_restored',
)


def _top_level_sql(source):
    """Remove quoted bodies/comments before checking operator transaction ownership."""
    result = []
    index = 0
    while index < len(source):
        if source.startswith('--', index):
            end = source.find('\n', index)
            index = len(source) if end < 0 else end
            result.append(' ')
        elif source.startswith('/*', index):
            depth = 1; index += 2
            while depth and index < len(source):
                if source.startswith('/*', index):depth += 1; index += 2
                elif source.startswith('*/', index):depth -= 1; index += 2
                else:index += 1
            if depth:raise ValueError('purge_migration_sql_quoting')
            result.append(' ')
        elif source[index] in "'\"":
            quote = source[index]; index += 1
            while index < len(source):
                if source[index] == quote:
                    index += 1
                    if index < len(source) and source[index] == quote:index += 1; continue
                    break
                if source[index] == '\\' and quote == "'":index += 1
                index += 1
            else:raise ValueError('purge_migration_sql_quoting')
            result.append(' literal ')
        elif source[index] == '$' and (match := re.match(r'\$(?:[A-Za-z_][A-Za-z_0-9]*)?\$',source[index:])):
            delimiter = match[0]
            end = source.find(delimiter,index+len(delimiter))
            if end < 0:raise ValueError('purge_migration_sql_quoting')
            if re.search(r'\b(?:AS|DO)\s*$', ''.join(result),re.I):
                body = _top_level_sql(source[index+len(delimiter):end])
                if re.search(r'\b(?:COMMIT|ROLLBACK|ABORT|START\s+TRANSACTION|PREPARE\s+TRANSACTION)\b',body,re.I):
                    raise ValueError('purge_transaction_boundary')
            index = end+len(delimiter);result.append(' literal ')
        else:result.append(source[index]);index += 1
    return ''.join(result)


def migration(path: Path = MIGRATION) -> PublicationMigration:
    """Load bounded exact bytes without applying DDL or recording checksum history."""
    if path.name != MIGRATION.name:raise ValueError('purge_migration_identity')
    with path.open('rb') as stream:raw = stream.read(1048577)
    if not 1 <= len(raw) <= 1048576:raise ValueError('purge_migration_size')
    source = raw.decode('utf-8')
    if '\r' in source or '\0' in source or source.startswith('\ufeff'):
        raise ValueError('purge_migration_encoding')
    if DELIMITER in source:raise ValueError('purge_probe_delimiter')
    visible = _top_level_sql(source)
    if '\\' in visible or re.search(r'(?is)(?:^|;)\s*(?:BEGIN|COMMIT|END|ROLLBACK|ABORT|START\s+TRANSACTION|PREPARE\s+TRANSACTION)\b',visible):
        raise ValueError('purge_transaction_boundary')
    return PublicationMigration(path.stem,sha256(raw).hexdigest(),source)


def erase_statement(arguments):
    if type(arguments) not in (list,tuple) or len(arguments) != 20:
        raise ValueError('purge_argument_shape')
    return 'SELECT cragkit_qdrant.erase_purged_document('+','.join(
        literal(value)+'::'+kind for value,kind in zip(arguments,TYPES,strict=True))+')'


async def _execute(connection,statement,params=None):
    return await connection.execute(statement,params,prepare=False)


async def _rows(connection,statement,params=None):
    return await (await _execute(connection,statement,params)).fetchall()


@asynccontextmanager
async def _case(connection):
    await _execute(connection,'SAVEPOINT qa_purge_probe')
    primary = None
    try:yield
    except BaseException as error:primary = error;raise
    finally:
        failures = []
        for statement in ('ROLLBACK TO SAVEPOINT qa_purge_probe','RELEASE SAVEPOINT qa_purge_probe'):
            try:await _execute(connection,statement)
            except BaseException as error:failures.append(('fixture_transaction',error))
        if failures:raise CleanupFailure(failures,primary=primary,stage='fixture_setup') from None


def _profile_queries():
    function = literal(SIGNATURE)+'::regprocedure'
    role = literal(PURGER_ROLE)+'::regrole'
    bodies = ' AND '.join("NOT pg_catalog.has_column_privilege("+role+",'cragkit_qdrant."+table+"','"+column+"','SELECT')"
        for table,columns in BODY_COLUMNS.items() for column in columns)
    return (
        "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_language l ON l.oid=p.prolang "
        "WHERE p.oid="+function+" AND l.lanname='plpgsql' AND p.prorettype='boolean'::regtype AND p.pronargs=20 "
        "AND p.prosecdef AND NOT p.proisstrict AND NOT p.proleakproof AND p.provolatile='v' AND p.proparallel='u' "
        "AND p.proowner="+role+" AND p.proconfig=ARRAY['search_path=pg_catalog','row_security=on']::text[]) "
        "AND EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE oid="+role+
        " AND NOT(rolcanlogin OR rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole OR rolreplication OR rolinherit))",
        'SELECT '+bodies+" AND NOT pg_catalog.has_schema_privilege("+role+",'cragkit_qdrant','CREATE') "
        "AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members WHERE member="+role+") "
        "AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND c.relname<>'schema_migrations' "
        "AND NOT(c.relrowsecurity AND c.relforcerowsecurity)) "
        "AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p CROSS JOIN LATERAL pg_catalog.aclexplode(p.proacl) a "
        "WHERE p.oid="+function+" AND (a.grantee NOT IN ("+role+",'cragkit_qdrant_writer'::regrole) "
        "OR a.grantor<>"+role+" OR (a.grantee='cragkit_qdrant_writer'::regrole AND a.is_grantable)))",
    )


async def _bind(connection,args):
    # Scope selectors do not confer authority; the real login and fixed SQL helper do.
    settings = dict(backend_instance_id=args[0],tenant_id=args[7],collection=args[8],
        writer_document_id=args[9],writer_intent_id=args[10],writer_owner_token=args[12],
        authorization_revision=args[14],principal_id='reader-a',grant_ids='["grant-a"]')
    for key,value in settings.items():
        await _execute(connection,'SELECT set_config(%s,%s,true)',('cragkit_qdrant.'+key,value))


async def _stage_selector(connection,args):
    stages = await _rows(connection,'SELECT intent_id FROM cragkit_qdrant.publication_intents WHERE '+TARGET+
        " AND action='stage' ORDER BY convert_to(intent_id,'UTF8') LIMIT 2",args[7:10])
    if len(stages)!=1:raise ValueError('purge_probe_requires_one_stage_fixture')
    return stages[0][0]


async def _intent_selector(connection,value):
    await _execute(connection,"SELECT set_config('cragkit_qdrant.writer_intent_id',%s,true)",(value,))


async def _snapshot(connection,args,*,immutable=False):
    """Retain only hashes/counts of synthetic rows, including all erased flags."""
    result = [];stage = await _stage_selector(connection,args)
    for table in ('documents',*BODY_COLUMNS,'generations','point_claims','dispatch_points',
                  'publication_intents','document_owners','purge_erasures'):
        if immutable and table=='purge_erasures':continue
        removed = ()
        if immutable:
            removed = (*BODY_COLUMNS.get(table,()),'content_erased') if table in BODY_COLUMNS else (
                ('content_unavailable',) if table=='documents' else
                ('state','authority_committed','replica_complete','purge_complete') if table=='publication_intents' else ())
        expression = 'to_jsonb(r)'+('-ARRAY['+','.join(literal(name) for name in removed)+']::text[]' if removed else '')
        await _intent_selector(connection,stage if table in ('document_revisions','members','generations') else args[10])
        try:
            value = await _rows(connection,"SELECT count(*),encode(sha256(convert_to(coalesce("
                'jsonb_agg('+expression+' ORDER BY ('+expression+")::text),'[]'::jsonb)::text,'UTF8')),'hex') "
                'FROM cragkit_qdrant.'+table+' r WHERE '+TARGET,args[7:10])
        finally:await _intent_selector(connection,args[10])
        if len(value)!=1 or len(value[0])!=2:raise RuntimeError('purge_snapshot_shape')
        result.append((table,*value[0]))
    return tuple(result)


async def _erased(connection,args):
    stage = await _stage_selector(connection,args)
    for table,columns in BODY_COLUMNS.items():
        condition = 'content_erased AND '+' AND '.join(column+' IS NULL' for column in columns)
        await _intent_selector(connection,stage if table in ('document_revisions','members') else args[10])
        try:
            if await _rows(connection,'SELECT coalesce(bool_and('+condition+'),false) FROM cragkit_qdrant.'+
                table+' WHERE '+TARGET,args[7:10]) != [(True,)]:raise RuntimeError('purge_retained_body')
        finally:await _intent_selector(connection,args[10])
    query = 'SELECT content_unavailable FROM cragkit_qdrant.documents WHERE '+TARGET
    if await _rows(connection,query,args[7:10]) != [(True,)]:raise RuntimeError('purge_document_marker')
    query = ('SELECT state,authority_committed,replica_complete,purge_complete FROM cragkit_qdrant.publication_intents WHERE '+
        TARGET+' AND intent_id=%s')
    if await _rows(connection,query,(*args[7:10],args[10])) != [('complete',True,True,True)]:
        raise RuntimeError('purge_terminal_flags')
    columns = ('instance_id','backend_namespace','storage_identity','supervisor_id','backend_epoch',
        'physical_collection','collection_incarnation','purge_intent_id','purge_payload_sha256','owner_token',
        'tombstone_payload_sha256','authorization_revision','mutation_epoch','inventory_sha256','policy_id','absence_sha256')
    indices = (0,1,2,3,4,5,6,10,11,12,13,14,15,17,18,19)
    query = 'SELECT '+','.join(column+'::text' for column in columns)+',erasure_sha256 FROM cragkit_qdrant.purge_erasures WHERE '+TARGET+' AND purge_intent_id=%s'
    rows = await _rows(connection,query,(*args[7:10],args[10]))
    if len(rows)!=1 or rows[0][:-1]!=tuple(str(args[index]) for index in indices) or re.fullmatch('[0-9a-f]{64}',rows[0][-1]) is None:
        raise RuntimeError('purge_erasure_metadata')


async def _reject(connection,statement,state):
    await _execute(connection,rejected_sql(statement.rstrip(';')+';',state))


async def _pending_cases(connection,args,records,statement):
    claims = records['claims'][:8]
    if not claims:raise ValueError('purge_fixture_claims_required')
    common = dict(zip(('tenant_id','collection','document_id'),args[7:10],strict=True))
    for state in ('reserved','dispatched','unknown'):
        async with _case(connection):
            sequence = (await _rows(connection,'SELECT coalesce(max(sequence),0)+1 FROM cragkit_qdrant.dispatch_journal WHERE '+
                TARGET+' AND intent_id=%s',(*args[7:10],args[10])))[0][0]
            request = b'{"synthetic":"sql-only-purge-pending-probe"}'
            journal = dict(common,intent_id=args[10],dispatch_id='purge-sql-probe-'+state,instance_id=args[0],
                sequence=sequence,owner_token=args[12],backend_epoch=args[4],credential_generation='synthetic-current-sql-credential',
                operation='delete_points',request_bytes=request,request_sha256=sha256(request).hexdigest())
            await _execute(connection,insert_sql('dispatch_journal',journal))
            for claim in claims:
                point = dict(common,intent_id=args[10],dispatch_id=journal['dispatch_id'],
                    **{name:claim[name] for name in ('backend_namespace','physical_collection','collection_incarnation','point_id')})
                await _execute(connection,insert_sql('dispatch_points',point))
            if state!='reserved':
                await _execute(connection,'UPDATE cragkit_qdrant.dispatch_journal SET state=%s WHERE '+TARGET+
                    ' AND intent_id=%s AND dispatch_id=%s',(state,*args[7:10],args[10],journal['dispatch_id']))
            before = await _snapshot(connection,args)
            await _reject(connection,statement,'23514')
            if await _snapshot(connection,args)!=before:raise RuntimeError('purge_pending_mutated_content')


async def run_sql_probes(database,fixture):
    """Exercise a committed synthetic purge fixture through actual PostgreSQL roles.

    ``fixture`` contains exact twenty ``arguments`` and seed-compatible ``records``.
    The root-owned bootstrap supplies an open backend, current committed purge owner,
    retained source/member/replay/request bodies and only settled target journals.
    All business DML rolls back. Two explicitly committed administrative faults are
    restored in finally blocks. Supplied absence digests are synthetic SQL inputs.
    """
    if type(fixture) is not dict or set(fixture)!={'arguments','records'}:
        raise ValueError('purge_fixture_shape')
    args = tuple(fixture['arguments']);statement = erase_statement(args)
    records = fixture['records'];admin = database.admin
    if admin is None:raise ValueError('purge_admin_required')
    checks = []
    for index,query in enumerate(_profile_queries()):
        if await _rows(admin,query)!=[(True,)]:raise RuntimeError('purge_structural_profile')
        checks.append(CHECKS[index])
    baseline = await _snapshot(admin,args)
    for kind in ('supervisor','reader'):
        async with database.connection(kind) as connection:
            async with connection.transaction(force_rollback=True):
                await _bind(connection,args);await _reject(connection,statement,'42501')
    async with admin.transaction(force_rollback=True):
        await _bind(admin,args);await _reject(admin,statement,'42501')
        async with _case(admin):
            await _execute(admin,'SET LOCAL ROLE cragkit_qdrant_writer')
            await _reject(admin,statement,'42501')
        async with _case(admin):
            await _execute(admin,'SET LOCAL ROLE '+PURGER_ROLE)
            await _reject(admin,statement,'42501')
            for table,columns in BODY_COLUMNS.items():
                for column in columns:
                    await _reject(admin,'SELECT '+column+' FROM cragkit_qdrant.'+table,'42501')
            if await _rows(admin,'SELECT content_unavailable FROM cragkit_qdrant.documents WHERE '+
                TARGET+' FOR UPDATE',args[7:10]) != [(False,)]:raise RuntimeError('purge_metadata_lock_missing')
            await _reject(admin,'UPDATE cragkit_qdrant.documents SET authorization_revision='+literal('forged'),'42501')
    checks.append(CHECKS[2])
    async with database.connection('writer') as connection:
        async with connection.transaction(force_rollback=True):
            await _bind(connection,args)
            variants = []
            for index in range(20):
                changed = list(args);changed[index]=None;variants.append(changed)
            for index,value in ((4,0),(15,-1),(4,9007199254740992),(11,'A'*64),
                (16,b'\xff'),(16,b'x'*262145),(17,'A'*64),(18,'retain-vectors-only'),(19,'not-a-digest')):
                changed=list(args);changed[index]=value;variants.append(changed)
            for changed in variants:
                await _reject(connection,erase_statement(changed),'22023')
            for index,value in ((0,'foreign-instance'),(7,'foreign-tenant'),(8,'foreign-collection'),
                (9,'foreign-document'),(10,'foreign-purge'),(12,'00000000-0000-4000-8000-000000000099')):
                changed=list(args);changed[index]=value
                await _reject(connection,erase_statement(changed),'22023')
            checks.append(CHECKS[3])
            for index,value in ((0,'foreign-instance'),(1,'foreign-namespace'),(2,'foreign-storage'),
                (3,'foreign-supervisor'),(4,args[4]+1),(5,'foreign_collection'),(6,'foreign-incarnation'),
                (7,'foreign-tenant'),(8,'foreign-collection'),(9,'foreign-document'),(10,'foreign-purge'),
                (11,'0'*64),(12,'00000000-0000-4000-8000-000000000099'),(13,'0'*64),
                (14,'foreign-authorization'),(15,args[15]+1),(16,b'[]'),(17,'0'*64)):
                changed=list(args);changed[index]=value
                # Even a matching editable selector cannot confer durable authority.
                await _bind(connection,changed)
                try:await _reject(connection,erase_statement(changed),'23514')
                finally:await _bind(connection,args)
            changed=list(args);changed[16]=b'[]';changed[17]=sha256(b'[]').hexdigest()
            await _reject(connection,erase_statement(changed),'23514')
            checks.append(CHECKS[4])
            if await _snapshot(connection,args)!=baseline:raise RuntimeError('purge_preflight_mutated_content')
            await _pending_cases(connection,args,records,statement)
            checks.append(CHECKS[5])
    await _rollback_fault(database,args,statement,baseline)
    checks.append(CHECKS[6])
    async with database.connection('writer') as connection:
        async with connection.transaction(force_rollback=True):
            await _bind(connection,args)
            immutable = await _snapshot(connection,args,immutable=True)
            if await _rows(connection,statement)!=[(True,)]:raise RuntimeError('purge_first_result')
            await _erased(connection,args)
            if await _snapshot(connection,args,immutable=True)!=immutable:raise RuntimeError('purge_retained_metadata_changed')
            erased = await _snapshot(connection,args)
            if await _rows(connection,statement)!=[(True,)]:raise RuntimeError('purge_historical_result')
            if await _snapshot(connection,args)!=erased:raise RuntimeError('purge_historical_retry_mutated')
            checks.append(CHECKS[7])
            for table,columns in BODY_COLUMNS.items():
                restore_state = '23514' if table=='dispatch_journal' else '42501'
                await _reject(connection,'UPDATE cragkit_qdrant.'+table+' SET '+columns[0]+"=decode('61','hex') WHERE "+
                    ' AND '.join(name+'='+literal(value) for name,value in zip(('tenant_id','collection','document_id'),args[7:10],strict=True)),restore_state)
                await _reject(connection,'UPDATE cragkit_qdrant.'+table+' SET content_erased=false',restore_state)
                await _reject(connection,'DELETE FROM cragkit_qdrant.'+table,'42501')
            await _reject(connection,'UPDATE cragkit_qdrant.documents SET content_unavailable=false','23514')
            await _reject(connection,'UPDATE cragkit_qdrant.purge_erasures SET absence_sha256='+literal('0'*64),'42501')
            await _reject(connection,insert_sql('document_revisions',records['revision']),'23514')
            checks.append(CHECKS[8])
    if await _snapshot(admin,args)!=baseline:raise RuntimeError('purge_business_rollback_changed_fixture')
    await _permission_fault(database,args,statement)
    checks.append(CHECKS[9])
    return checks


async def _permission_fault(database,args,statement):
    admin = database.admin;granted = False;primary = None
    try:
        async with admin.transaction():
            await _execute(admin,'GRANT SELECT(canonical_utf8) ON cragkit_qdrant.document_revisions TO '+PURGER_ROLE)
        granted = True
        async with database.connection('writer') as connection:
            async with connection.transaction(force_rollback=True):
                await _bind(connection,args);await _reject(connection,statement,'22023')
    except BaseException as error:primary=error;raise
    finally:
        if granted:
            try:
                async with admin.transaction():
                    await _execute(admin,'REVOKE SELECT(canonical_utf8) ON cragkit_qdrant.document_revisions FROM '+PURGER_ROLE)
            except BaseException as error:raise CleanupFailure([('privilege_revoke',error)],primary=primary,stage='fixture_setup') from None
    if await _rows(admin,_profile_queries()[1])!=[(True,)]:raise RuntimeError('purge_privilege_fault_not_restored')


async def _rollback_fault(database,args,statement,baseline):
    """A committed BEFORE-row trigger aborts after preceding tables were nulled."""
    admin = database.admin;installed = False;primary = None
    try:
        async with admin.transaction():
            await _execute(admin,"CREATE FUNCTION cragkit_qdrant.qa_purge_intermediate_failure() RETURNS trigger LANGUAGE plpgsql "
                "SET search_path=pg_catalog AS $fault$ BEGIN "
                "IF NOT (SELECT coalesce(bool_and(content_erased),false) FROM cragkit_qdrant.document_revisions "
                "WHERE tenant_id=NEW.tenant_id AND collection=NEW.collection AND document_id=NEW.document_id) "
                "OR NOT (SELECT coalesce(bool_and(content_erased),false) FROM cragkit_qdrant.members "
                "WHERE tenant_id=NEW.tenant_id AND collection=NEW.collection AND document_id=NEW.document_id) "
                "OR NOT (SELECT coalesce(bool_and(content_erased),false) FROM cragkit_qdrant.vector_replays "
                "WHERE tenant_id=NEW.tenant_id AND collection=NEW.collection AND document_id=NEW.document_id) "
                "THEN RAISE EXCEPTION 'synthetic fault ordering' USING ERRCODE='QP002'; END IF; "
                "RAISE EXCEPTION 'synthetic purge fault' USING ERRCODE='QP001'; END $fault$")
            await _execute(admin,'REVOKE ALL ON FUNCTION cragkit_qdrant.qa_purge_intermediate_failure() FROM PUBLIC')
            await _execute(admin,'CREATE TRIGGER qa_purge_intermediate_failure BEFORE UPDATE ON cragkit_qdrant.dispatch_journal '
                'FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.qa_purge_intermediate_failure()')
        installed = True
        async with database.connection('writer') as connection:
            async with connection.transaction(force_rollback=True):
                await _bind(connection,args);await _reject(connection,statement,'QP001')
                if await _snapshot(connection,args)!=baseline:raise RuntimeError('purge_intermediate_failure_not_atomic')
    except BaseException as error:primary=error;raise
    finally:
        if installed:
            try:
                async with admin.transaction():
                    await _execute(admin,'DROP TRIGGER qa_purge_intermediate_failure ON cragkit_qdrant.dispatch_journal')
                    await _execute(admin,'DROP FUNCTION cragkit_qdrant.qa_purge_intermediate_failure()')
            except BaseException as error:raise CleanupFailure([('schema_restore',error)],primary=primary,stage='fixture_setup') from None


async def run_historical_confirmation(database,fixture):
    """Commit one synthetic SQL erasure, then confirm retained metadata read-only.

    Call after ``run_sql_probes`` on the same dedicated fixture. This deliberately
    leaves the target erased until fixture teardown. The fresh login never invokes
    the erasure helper, reconstructs erased content, or issues a mutation/HTTP call.
    """
    if type(fixture) is not dict or set(fixture)!={'arguments','records'}:
        raise ValueError('purge_fixture_shape')
    args = tuple(fixture['arguments']);statement = erase_statement(args)
    async with database.connection('writer') as connection:
        async with connection.transaction():
            await _bind(connection,args)
            immutable = await _snapshot(connection,args,immutable=True)
            if await _rows(connection,statement)!=[(True,)]:raise RuntimeError('purge_committed_result')
            await _erased(connection,args)
            if await _snapshot(connection,args,immutable=True)!=immutable:
                raise RuntimeError('purge_committed_metadata_changed')
            committed = await _snapshot(connection,args)
    # A separate native login and explicitly read-only transaction make blind
    # function/DML replay impossible in this historical-confirmation lease.
    async with database.connection('writer') as connection:
        async with connection.transaction(force_rollback=True):
            await _execute(connection,'SET TRANSACTION READ ONLY')
            await _bind(connection,args)
            await _erased(connection,args)
            if await _snapshot(connection,args)!=committed:
                raise RuntimeError('purge_fresh_historical_metadata_changed')
    return ['committed_sql_erasure_fresh_login_read_only_retained_metadata_confirmation']
