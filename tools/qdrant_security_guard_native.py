"""Owned non-superuser operator and synthetic SQL guard fixtures."""
from __future__ import annotations

from contextlib import asynccontextmanager
import secrets

from qdrant_authority_schema import catalog_queries
from qdrant_publication_native import PublicationDatabase,bind_scope
from qdrant_publication_schema import insert_sql,seed_records
from qdrant_security_lock_cases import _writer,_security_change,_snapshot
from qdrant_writer_cases import writer_input,OWNER_TOKEN

OPERATOR='security_guard_fixture_operator'
NAMES=('guard','commit','post_wait','abort','lost')


async def rows(connection,statement,params=()):
    return await (await connection.execute(statement,params,prepare=False)).fetchall()


class SecurityGuardDatabase(PublicationDatabase):
    """Bootstrap only the fresh fixture; the migration itself uses its own login."""
    async def __aenter__(self):
        await super().__aenter__()
        try:
            await self._bootstrap_operator()
        except BaseException:
            await self._close()
            raise
        return self

    async def _bootstrap_operator(self):
        from psycopg import sql
        before=await rows(self.admin,catalog_queries()[0])
        password=secrets.token_hex(32)
        async with self.admin.transaction():
            await self.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS '
                'NOCREATEDB CREATEROLE NOREPLICATION NOINHERIT').format(sql.Identifier(OPERATOR),sql.Literal(password)))
            await self.admin.execute(sql.SQL('ALTER SCHEMA cragkit_qdrant OWNER TO {}').format(sql.Identifier(OPERATOR)))
            tables=await rows(self.admin,"SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' ORDER BY c.relname")
            for (name,) in tables:
                await self.admin.execute(sql.SQL('ALTER TABLE {} OWNER TO {}').format(sql.Identifier('cragkit_qdrant',name),sql.Identifier(OPERATOR)))
            domains=await rows(self.admin,"SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace "
                "WHERE n.nspname='cragkit_qdrant' AND t.typtype='d' ORDER BY t.typname")
            for (name,) in domains:
                await self.admin.execute(sql.SQL('ALTER DOMAIN {} OWNER TO {}').format(sql.Identifier('cragkit_qdrant',name),sql.Identifier(OPERATOR)))
            functions=await rows(self.admin,"SELECT p.proname,pg_get_function_identity_arguments(p.oid) FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='cragkit_qdrant' ORDER BY p.proname")
            for name,arguments in functions:
                # Arguments come only from the freshly installed, checked catalog.
                await self.admin.execute(sql.SQL('ALTER FUNCTION {}('+arguments+') OWNER TO {}').format(
                    sql.Identifier('cragkit_qdrant',name),sql.Identifier(OPERATOR)))
        self._operator_config=self.fixture.reader_config(OPERATOR,password)
        if await rows(self.admin,catalog_queries()[0])!=before:
            raise RuntimeError('guard_operator_changed_original_catalog')
        async with self.operator_connection() as connection:
            checked=await rows(connection,"SELECT current_user=session_user,r.rolcanlogin,r.rolcreaterole,"
                "NOT(r.rolsuper OR r.rolbypassrls OR r.rolcreatedb OR r.rolreplication),"
                "n.nspowner=r.oid,NOT EXISTS(SELECT 1 FROM pg_class c WHERE c.relnamespace=n.oid "
                "AND c.relkind='r' AND c.relowner<>r.oid) FROM pg_roles r CROSS JOIN pg_namespace n "
                "WHERE r.rolname=current_user AND n.nspname='cragkit_qdrant'")
            if checked!=[(True,True,True,True,True,True)]:
                raise RuntimeError('guard_operator_profile')

    @asynccontextmanager
    async def operator_connection(self):
        connection=await self._connect(self._operator_config)
        try:
            yield connection
        finally:
            await connection.close()


def guard_inputs(name):
    from cragkit._qdrant_contract import point_id
    from cragkit._qdrant_manifest import encode_manifest,encode_stage_intent
    value=writer_input()
    stage=value['stage'];manifest=stage['manifest'];document='doc-security-guard-'+name
    manifest['document_id']=document;stage['intent']['document_id']=document
    ids={}
    for member in manifest['members']:
        member['point_id']=point_id(['cragkit.qdrant.point.v1',manifest['backend_namespace'],
            manifest['physical_collection'],manifest['collection_incarnation'],manifest['tenant_id'],manifest['collection'],
            document,manifest['revision_id'],manifest['generation_id'],member['chunk_id'],
            manifest['dense_profile']['profile_id'],manifest['sparse_profile']['profile_id']])
        ids[member['chunk_id']]=member['point_id']
    encoded=encode_manifest(manifest,stage['canonical_text'])
    stage['intent']['manifest_sha256']=encoded.sha256
    for point in value['expected_points']:
        point['payload']['document_id']=document;point['id']=ids[point['payload']['chunk_id']]
    records=seed_records()
    for kind in ('document','intent','revision','generation'):records[kind]['document_id']=document
    for kind in ('members','claims','replays'):
        for row in records[kind]:row['document_id']=document;row['point_id']=ids[row['chunk_id']]
    intent=encode_stage_intent(stage['intent'])
    records['intent'].update(manifest_bytes=encoded.encoded_bytes,manifest_sha256=encoded.sha256,
        payload_bytes=intent.encoded_bytes,payload_sha256=intent.sha256)
    return value,records


async def seed_guard_documents(database):
    """Use accepted three-profile writer APIs before installing the new profile."""
    import asyncio
    from cragkit._qdrant_writer import prepare_stage,security_projection_data
    from cragkit.contracts import TrustedScope
    datasets={}
    base=writer_input()
    baseline_records=seed_records()
    async with database.connection('supervisor') as connection:
        async with connection.transaction():
            await bind_scope(connection,baseline_records)
            await connection.execute(insert_sql('backend_instances',baseline_records['backend']))
    writer,resource=await _writer(database,base)
    deadline=asyncio.get_running_loop().time()+90
    try:
        for name in NAMES:
            inputs,records=guard_inputs(name)
            scope=TrustedScope.model_validate(inputs['scope'])
            manifest=inputs['stage']['manifest']
            owner=dict(scope=scope,collection=manifest['collection'],document_id=manifest['document_id'],
                intent_id=inputs['stage']['intent']['intent_id'],owner_token=OWNER_TOKEN)
            await writer.stage(prepare_stage(inputs['stage']),scope,owner_token=OWNER_TOKEN,deadline=deadline)
            await writer.admit_publication(owner,deadline=deadline)
            dispatch='security-guard-'+name+'-unknown'
            await writer.reserve_dispatch(owner,dict(dispatch_id=dispatch,sequence=1,
                credential_generation='synthetic-sql-retired-credential-1',operation='complete_point_upsert',
                point_ids=[member['point_id'] for member in manifest['members']]),deadline=deadline)
            await writer.mark_dispatched(owner,dispatch,deadline=deadline)
            await writer.mark_unknown(owner,dispatch,deadline=deadline)
            change=_security_change(inputs,'guard-security-auth-2-'+name,'auth-1',1,'auth-2')
            await writer.apply_security(change,scope,owner_token=OWNER_TOKEN,deadline=deadline)
            current=TrustedScope.model_validate(dict(inputs['scope'],authorization_revision='auth-2'))
            await writer.admit_publication(dict(owner,scope=current),deadline=deadline)
            projection=await writer.project_security(dict(owner,scope=current,intent_id=change['intent_id']),deadline=deadline)
            data=security_projection_data(projection,writer)
            args=(inputs['instance_id'],inputs['config']['backend_namespace'],'storage-fixture','supervisor-fixture',
                'security-guard-sql-recovery',2,manifest['tenant_id'],manifest['collection'],manifest['document_id'],
                owner['intent_id'],OWNER_TOKEN,change['intent_id'],data['intent_sha256'],data['active_generation_id'],
                data['authorization_revision'],data['mutation_epoch'],list(data['principal_ids']),list(data['grant_ids']),
                data['language'],data['kind'],data['tag'],data['tombstoned'])
            datasets[name]=dict(arguments=args,inputs=inputs,records=records,dispatch_id=dispatch,
                scope=current.model_dump(mode='json'))
    finally:
        await writer.close();await resource.close()
    async with database.connection('supervisor') as connection:
        async with connection.transaction():
            await bind_scope(connection,baseline_records)
            await connection.execute("UPDATE cragkit_qdrant.backend_instances SET state='recovery_blocked',epoch=2,"
                "recovery_id='security-guard-sql-recovery' WHERE instance_id=%s",(base['instance_id'],))
            for dataset in datasets.values():
                args=dataset['arguments']
                await connection.execute('UPDATE cragkit_qdrant.document_owners SET backend_epoch=2 '
                    'WHERE tenant_id=%s AND collection=%s AND document_id=%s AND intent_id=%s AND owner_token=%s',
                    (args[6],args[7],args[8],args[9],args[10]))
    return datasets


async def metadata_snapshot(admin):
    value=await rows(admin,"SELECT encode(sha256(convert_to(jsonb_build_object("
        "'roles',(SELECT jsonb_agg(to_jsonb(r) ORDER BY rolname) FROM pg_roles r),"
        "'members',(SELECT coalesce(jsonb_agg(to_jsonb(m) ORDER BY roleid,member,grantor),'[]'::jsonb) FROM pg_auth_members m),"
        "'defaults',(SELECT coalesce(jsonb_agg(to_jsonb(a) ORDER BY oid),'[]'::jsonb) FROM pg_default_acl a),"
        "'namespace',(SELECT to_jsonb(n) FROM pg_namespace n WHERE nspname='cragkit_qdrant'),"
        "'owners',(SELECT jsonb_agg(jsonb_build_array(c.relname,c.relowner) ORDER BY c.relname) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant'),"
        "'history',(SELECT jsonb_agg(jsonb_build_array(version,checksum_sha256) ORDER BY version) FROM cragkit_qdrant.schema_migrations)"
        ")::text,'UTF8')),'hex')")
    return value[0][0],await rows(admin,catalog_queries()[0])


async def install_guard(database):
    from qdrant_security_guard_schema import migration
    source=migration()
    baseline=await metadata_snapshot(database.admin)
    # Execute the complete DDL, then force rollback after ownership transfer.
    async with database.operator_connection() as operator:
        await operator.execute('BEGIN ISOLATION LEVEL READ COMMITTED')
        try:
            await operator.execute(source.sql,prepare=False)
            present=await rows(operator,"SELECT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "JOIN pg_roles r ON r.oid=p.proowner WHERE n.nspname='cragkit_qdrant' AND p.proname='lock_current_security' "
                "AND r.rolname='cragkit_qdrant_security_guard')")
            if present!=[(True,)]:raise RuntimeError('guard_rollback_not_after_transfer')
            await operator.execute('INSERT INTO cragkit_qdrant.schema_migrations(version,checksum_sha256) VALUES(%s,%s)',(source.version,source.checksum))
        finally:
            await operator.execute('ROLLBACK')
    if await metadata_snapshot(database.admin)!=baseline:
        raise RuntimeError('guard_install_rollback_changed_baseline')
    # A preexisting cluster role is refused, preserved and dropped only by its fixture owner.
    await database.admin.execute('CREATE ROLE cragkit_qdrant_security_guard NOLOGIN NOSUPERUSER NOBYPASSRLS')
    try:
        before=await metadata_snapshot(database.admin)
        async with database.operator_connection() as operator:
            await operator.execute('BEGIN ISOLATION LEVEL READ COMMITTED')
            rejected=False
            try:
                await operator.execute(source.sql,prepare=False)
            except Exception as error:
                if getattr(error,'sqlstate',None)!='22023':raise
                rejected=True
            finally:await operator.execute('ROLLBACK')
            if not rejected:raise RuntimeError('guard_adopted_preexisting_role')
        if await metadata_snapshot(database.admin)!=before:
            raise RuntimeError('guard_preexisting_role_changed')
    finally:
        await database.admin.execute('DROP ROLE cragkit_qdrant_security_guard')
    async with database.operator_connection() as operator:
        async with operator.transaction():
            await operator.execute(source.sql,prepare=False)
            await operator.execute('INSERT INTO cragkit_qdrant.schema_migrations(version,checksum_sha256) VALUES(%s,%s)',(source.version,source.checksum))
    return source
