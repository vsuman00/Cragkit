"""SG-r2 migration metadata and restricted SQL acceptance with restored faults."""
from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path
import re

from qdrant_authority_schema import ROOT, literal
from qdrant_publication_schema import PublicationMigration, DELIMITER, rejected_sql
from runtime_diagnostics import CleanupFailure

MIGRATION = ROOT/'storage/qdrant/postgres/migrations/0004_security_settlement_guard.sql'
ARGUMENTS = ('p_instance_id','p_backend_namespace','p_storage_identity','p_supervisor_id','p_recovery_id',
    'p_backend_epoch','p_tenant_id','p_collection','p_document_id','p_owner_intent_id','p_owner_token',
    'p_security_intent_id','p_security_payload_sha256','p_active_generation_id','p_authorization_revision',
    'p_mutation_epoch','p_principal_ids','p_grant_ids','p_language','p_kind','p_tag','p_tombstoned')
TYPES = ('text','text','text','text','text','bigint','text','text','text','text','uuid','text','text','text','text',
         'bigint','text[]','text[]','text','text','text','boolean')
SIGNATURE = 'cragkit_qdrant.lock_current_security('+','.join(TYPES)+')'
GUARD_ROLE = 'cragkit_qdrant_security_guard'
POLICIES = ('security_guard_backend_select','security_guard_backend_update','security_guard_owner_select',
    'security_guard_owner_update','security_guard_document_select','security_guard_document_update','security_guard_intent_select')
CHECKS = (
    'exact_guard_signature_attributes_and_dedicated_owner',
    'trusted_operator_bootstrap_and_self_set_memberships_only',
    'minimum_effective_column_privileges_and_no_sensitive_reads',
    'seven_guard_only_force_rls_policies_update_check_false',
    'direct_restricted_supervisor_calls_void_guard',
    'supervisor_document_source_request_vector_select_denied',
    'writer_reader_admin_and_set_role_callers_rejected',
    'required_null_count_hash_metadata_and_acl_bounds_rejected',
    'exact_backend_owner_security_and_current_tuple_mismatches_rejected',
    'non_read_committed_and_wrong_instance_selector_rejected',
    'guard_role_can_lock_but_cannot_update_or_read_secrets',
    'unsafe_extra_guard_grant_rejected_and_rolled_back',
)


def migration(path: Path = MIGRATION) -> PublicationMigration:
    if path.name != MIGRATION.name:
        raise ValueError('security_guard_migration_identity')
    with path.open('rb') as stream:raw = stream.read(1048577)
    if not 1 <= len(raw) <= 1048576:raise ValueError('security_guard_migration_size')
    source = raw.decode('utf-8')
    if '\r' in source or re.search(r'(?mi)^\s*(?:COMMIT|ROLLBACK|BEGIN\s*;|\\)',source):
        raise ValueError('security_guard_transaction_boundary')
    if DELIMITER in source:raise ValueError('security_guard_probe_delimiter')
    return PublicationMigration(path.stem,sha256(raw).hexdigest(),source)


def guard_statement(arguments):
    if type(arguments) not in (list,tuple) or len(arguments) != len(ARGUMENTS):
        raise ValueError('security_guard_argument_shape')
    values = []
    for value,kind in zip(arguments,TYPES,strict=True):
        if kind == 'text[]' and type(value) in (list,tuple):
            if len(value)>65 or any(item is not None and type(item) is not str for item in value):
                raise ValueError('security_guard_array_shape')
            encoded = 'ARRAY['+','.join(literal(item) for item in value)+']'
        else:encoded = literal(value)
        values.append(encoded+'::'+kind)
    return 'SELECT cragkit_qdrant.lock_current_security('+','.join(values)+')'


async def _execute(connection, statement, params=None):
    return await connection.execute(statement,params,prepare=False)


async def _rows(connection, statement, params=None):
    return await (await _execute(connection,statement,params)).fetchall()


@asynccontextmanager
async def _case(connection):
    await _execute(connection,'SAVEPOINT qa_security_guard_probe')
    primary = None
    try:yield
    except BaseException as error:
        primary = error
        raise
    finally:
        failures = []
        for operation,statement in (('fixture_transaction','ROLLBACK TO SAVEPOINT qa_security_guard_probe'),
                                    ('fixture_transaction','RELEASE SAVEPOINT qa_security_guard_probe')):
            try:await _execute(connection,statement)
            except BaseException as error:failures.append((operation,error))
        if failures:raise CleanupFailure(failures,primary=primary,stage='fixture_setup') from None


def _profile_queries():
    function = literal(SIGNATURE)+'::regprocedure'
    guard = literal(GUARD_ROLE)+'::regrole'
    return (
        "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_language l ON l.oid=p.prolang "
        "WHERE p.oid="+function+" AND l.lanname='plpgsql' AND p.prorettype='void'::regtype AND p.pronargs=22 "
        "AND p.prosecdef AND NOT p.proisstrict AND NOT p.proleakproof AND p.provolatile='v' AND p.proparallel='u' "
        "AND p.proowner="+guard+" AND p.proconfig=ARRAY['search_path=pg_catalog','row_security=on']::text[])",
        "SELECT (SELECT count(*)=2 FROM pg_catalog.pg_auth_members WHERE roleid="+guard+") AND NOT EXISTS("
        "SELECT 1 FROM pg_catalog.pg_auth_members m CROSS JOIN pg_catalog.pg_namespace n WHERE m.roleid="+guard+
        " AND n.nspname='cragkit_qdrant' AND NOT(m.member=n.nspowner AND NOT m.inherit_option AND "
        "((m.grantor=10 AND m.admin_option AND NOT m.set_option) OR (m.grantor=n.nspowner AND NOT m.admin_option AND m.set_option)))) "
        "AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members WHERE member="+guard+") "
        "AND EXISTS(SELECT 1 FROM pg_catalog.pg_roles r WHERE r.oid="+guard+
        " AND NOT(r.rolcanlogin OR r.rolsuper OR r.rolbypassrls OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolinherit)) "
        "AND NOT pg_catalog.has_schema_privilege("+guard+",'cragkit_qdrant','CREATE')",
        "SELECT NOT pg_catalog.has_table_privilege("+guard+",'cragkit_qdrant.documents','SELECT') "
        "AND pg_catalog.has_column_privilege("+guard+",'cragkit_qdrant.documents','authorization_revision','SELECT') "
        "AND pg_catalog.has_column_privilege("+guard+",'cragkit_qdrant.documents','mutation_epoch','UPDATE') "
        "AND NOT pg_catalog.has_column_privilege("+guard+",'cragkit_qdrant.document_revisions','canonical_utf8','SELECT') "
        "AND NOT pg_catalog.has_column_privilege("+guard+",'cragkit_qdrant.vector_replays','dense_blob','SELECT') "
        "AND NOT pg_catalog.has_column_privilege("+guard+",'cragkit_qdrant.dispatch_journal','request_bytes','SELECT') "
        "AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_proc f JOIN pg_catalog.pg_namespace n ON n.oid=f.pronamespace "
        "WHERE n.nspname='cragkit_qdrant' AND pg_catalog.has_function_privilege("+guard+",f.oid,'EXECUTE') IS DISTINCT FROM "
        "(f.oid="+function+" OR f.oid=pg_catalog.to_regprocedure('cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean)') "
        "OR f.oid=pg_catalog.to_regprocedure('cragkit_qdrant.scope_grants()') "
        "OR f.oid=pg_catalog.to_regprocedure('cragkit_qdrant.valid_identity_array(text[])'))) "
        "AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p CROSS JOIN LATERAL pg_catalog.aclexplode(p.proacl) a "
        "WHERE p.oid="+function+" AND (a.grantee NOT IN ("+guard+",'cragkit_qdrant_supervisor'::regrole) "
        "OR a.grantor<>"+guard+" OR (a.grantee='cragkit_qdrant_supervisor'::regrole AND a.is_grantable)))",
        "SELECT (SELECT count(*)=7 FROM pg_catalog.pg_policy WHERE polroles=ARRAY["+guard+"]::oid[]) "
        "AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_policy p WHERE "+guard+"=ANY(p.polroles) "
        "AND (p.polroles<>ARRAY["+guard+"]::oid[] OR NOT p.polpermissive OR p.polqual IS NULL "
        "OR (p.polcmd='w' AND pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid) IS DISTINCT FROM 'false'))) "
        "AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND c.relname<>'schema_migrations' AND NOT(c.relrowsecurity AND c.relforcerowsecurity))",
    )


async def run_sql_probes(database, arguments):
    """After operator installation, test actual roles under mandatory rollback."""
    arguments = tuple(arguments) if type(arguments) in (list,tuple) else arguments
    statement = guard_statement(arguments)
    admin = database.admin
    if admin is None:raise ValueError('security_guard_admin_required')
    checks = []
    for index,query in enumerate(_profile_queries()):
        if await _rows(admin,query) != [(True,)]:raise RuntimeError('security_guard_structural_profile')
        checks.append(CHECKS[index])

    async def selected(connection):
        await _execute(connection,"SELECT set_config('cragkit_qdrant.backend_instance_id',%s,true)",(arguments[0],))
    async def reject(connection,query,code):
        await _execute(connection,rejected_sql(query.rstrip(';')+';',code))
    async with database.connection('supervisor') as connection:
        async with connection.transaction(force_rollback=True):
            await selected(connection)
            async with _case(connection):
                result = await _rows(connection,statement)
                if len(result)!=1 or len(result[0])!=1 or result[0][0] not in (None,''):
                    raise RuntimeError('security_guard_void_result')
            checks.append(CHECKS[4])
            for table,column in (('documents','authorization_revision'),('document_revisions','canonical_utf8'),
                                 ('dispatch_journal','request_bytes'),('vector_replays','dense_blob')):
                await reject(connection,'SELECT '+column+' FROM cragkit_qdrant.'+table,'42501')
            checks.append(CHECKS[5])

    for kind in ('writer','reader'):
        async with database.connection(kind) as connection:
            async with connection.transaction(force_rollback=True):
                await selected(connection)
                await reject(connection,statement,'42501')
    async with admin.transaction(force_rollback=True):
        await selected(admin)
        await reject(admin,statement,'42501')
        async with _case(admin):
            await _execute(admin,'SET LOCAL ROLE cragkit_qdrant_supervisor')
            await reject(admin,statement,'42501')
    checks.append(CHECKS[6])

    async with database.connection('supervisor') as connection:
        async with connection.transaction(force_rollback=True):
            await selected(connection)
            nullable = {13,18,19,20}
            variants = []
            for index in range(22):
                if index not in nullable:
                    value = list(arguments);value[index] = None;variants.append(tuple(value))
            for index,value in ((5,0),(15,0),(12,'A'*64),(18,'x'*1025),(16,['x','x']),(17,['z','a']),
                                (16,[None]),(17,['x']*65)):
                changed = list(arguments);changed[index] = value;variants.append(tuple(changed))
            for changed in variants:await reject(connection,guard_statement(changed),'22023')
            # Bound lower dimensions and lower array bounds explicitly, including empty arrays.
            for expression in ("'[0:0]={x}'::text[]","ARRAY[['x'],['y']]::text[]"):
                pieces = []
                for index,(value,kind) in enumerate(zip(arguments,TYPES,strict=True)):
                    if index == 16:pieces.append(expression)
                    elif kind=='text[]':pieces.append(('ARRAY['+','.join(literal(item) for item in value)+']::text[]') if value is not None else 'NULL::text[]')
                    else:pieces.append(literal(value)+'::'+kind)
                await reject(connection,'SELECT cragkit_qdrant.lock_current_security('+','.join(pieces)+')','22023')
            checks.append(CHECKS[7])
            for index,value in ((1,'wrong-namespace'),(2,'wrong-storage'),(3,'wrong-supervisor'),(4,'wrong-recovery'),
                (5,arguments[5]+1),(9,'wrong-owner'),(10,'00000000-0000-4000-8000-000000000099'),
                (11,arguments[9]),(12,'0'*64),(13,'wrong-active'),(14,'wrong-authorization'),(15,arguments[15]+1),
                (16,['other-principal']),(17,['other-grant']),(21,not arguments[21])):
                changed = list(arguments);changed[index] = value
                await reject(connection,guard_statement(changed),'23514')
            checks.append(CHECKS[8])
            async with _case(connection):
                await _execute(connection,"SELECT set_config('cragkit_qdrant.backend_instance_id','foreign-instance',true)")
                await reject(connection,statement,'22023')
    async with database.connection('supervisor') as connection:
        async with connection.transaction(force_rollback=True):
            await _execute(connection,'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            await selected(connection)
            await reject(connection,statement,'22023')
    checks.append(CHECKS[9])

    async with admin.transaction(force_rollback=True):
        await selected(admin)
        async with _case(admin):
            await _execute(admin,'SET LOCAL ROLE '+GUARD_ROLE)
            if len(await _rows(admin,'SELECT mutation_epoch FROM cragkit_qdrant.documents WHERE tenant_id=%s AND collection=%s AND document_id=%s FOR UPDATE',arguments[6:9])) != 1:
                raise RuntimeError('security_guard_rls_lock_missing')
            await reject(admin,'UPDATE cragkit_qdrant.documents SET mutation_epoch=mutation_epoch+1','42501')
            for table,column in (('document_revisions','canonical_utf8'),('vector_replays','dense_blob'),('dispatch_journal','request_bytes')):
                await reject(admin,'SELECT '+column+' FROM cragkit_qdrant.'+table,'42501')
    checks.append(CHECKS[10])
    primary = None
    granted = False
    try:
        # A distinct login must observe a real committed unsafe grant, not an uncommitted administrative fault.
        async with admin.transaction():
            await _execute(admin,'GRANT SELECT(canonical_utf8) ON cragkit_qdrant.document_revisions TO '+GUARD_ROLE)
        granted = True
        async with database.connection('supervisor') as connection:
            async with connection.transaction(force_rollback=True):
                await selected(connection)
                await reject(connection,statement,'22023')
    except BaseException as error:
        primary = error
        raise
    finally:
        if granted:
            try:
                async with admin.transaction():
                    await _execute(admin,'REVOKE SELECT(canonical_utf8) ON cragkit_qdrant.document_revisions FROM '+GUARD_ROLE)
            except BaseException as error:
                raise CleanupFailure([('privilege_revoke',error)],primary=primary,stage='fixture_setup') from None
    if await _rows(admin,_profile_queries()[2]) != [(True,)]:raise RuntimeError('security_guard_privilege_rollback')
    checks.append(CHECKS[11])
    return checks
