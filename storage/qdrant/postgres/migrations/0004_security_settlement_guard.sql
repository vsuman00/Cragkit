-- SG-r2: the operator wrapper owns transaction boundaries and checksum history.
DO $migration$
DECLARE
    operator_id oid;
BEGIN
    SELECT r.oid INTO operator_id FROM pg_catalog.pg_roles r
    JOIN pg_catalog.pg_namespace n ON n.nspowner=r.oid AND n.nspname='cragkit_qdrant'
    WHERE r.rolname=current_user AND current_user=session_user AND r.rolcanlogin
      AND r.rolcreaterole AND NOT r.rolsuper AND NOT r.rolbypassrls;
    IF operator_id IS NULL OR pg_catalog.current_setting('role',true)<>'none'
       OR pg_catalog.current_setting('server_version_num')::integer NOT BETWEEN 170000 AND 179999
       OR pg_catalog.current_setting('server_encoding')<>'UTF8'
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                 WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND c.relowner<>operator_id)
       OR pg_catalog.pg_has_role(operator_id,'cragkit_qdrant_writer','MEMBER')
       OR pg_catalog.pg_has_role(operator_id,'cragkit_qdrant_supervisor','MEMBER')
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_roles r WHERE NOT r.rolsuper AND
           (pg_catalog.pg_has_role(r.oid,'cragkit_qdrant_writer','MEMBER')
            OR pg_catalog.pg_has_role(r.oid,'cragkit_qdrant_supervisor','MEMBER'))
           AND pg_catalog.pg_has_role(r.oid,operator_id,'MEMBER')) THEN
        RAISE EXCEPTION 'unsupported security guard operator' USING ERRCODE='22023';
    END IF;
    IF (SELECT count(*) FROM cragkit_qdrant.schema_migrations)<>3
       OR NOT EXISTS(SELECT 1 FROM cragkit_qdrant.schema_migrations WHERE version='0001_authority'
          AND checksum_sha256='3d75cd46eb32a10864f1097a7494b01f9759150911a7cd9a1e6aab60105c1f1a')
       OR NOT EXISTS(SELECT 1 FROM cragkit_qdrant.schema_migrations WHERE version='0002_publication'
          AND checksum_sha256='386fe01d0d03e35ac35c21bce598b21bff2c5ad510e9cdf0a6fbe56f359b6661')
       OR NOT EXISTS(SELECT 1 FROM cragkit_qdrant.schema_migrations WHERE version='0003_preparation_attestations'
          AND checksum_sha256='8c6791cd0fd65ff09758c068ebc90a895a4ac21d9713512486d3daf9cb7c8433')
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='cragkit_qdrant_security_guard') THEN
        RAISE EXCEPTION 'unsupported security guard history or role' USING ERRCODE='22023';
    END IF;
    PERFORM pg_catalog.set_config('createrole_self_grant','',true);
END
$migration$;

CREATE ROLE cragkit_qdrant_security_guard NOLOGIN NOSUPERUSER NOBYPASSRLS
    NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
GRANT cragkit_qdrant_security_guard TO CURRENT_USER WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
GRANT USAGE, CREATE ON SCHEMA cragkit_qdrant TO cragkit_qdrant_security_guard;

GRANT SELECT(instance_id,backend_namespace,storage_identity,supervisor_id,epoch,state,recovery_id), UPDATE(epoch)
    ON cragkit_qdrant.backend_instances TO cragkit_qdrant_security_guard;
GRANT SELECT(tenant_id,collection,document_id,instance_id,intent_id,owner_token,backend_epoch), UPDATE(backend_epoch)
    ON cragkit_qdrant.document_owners TO cragkit_qdrant_security_guard;
GRANT SELECT(tenant_id,collection,document_id,active_generation_id,authorization_revision,mutation_epoch,
    principal_ids,grant_ids,language,kind,tag,tombstoned), UPDATE(mutation_epoch)
    ON cragkit_qdrant.documents TO cragkit_qdrant_security_guard;
GRANT SELECT(tenant_id,collection,document_id,intent_id,instance_id,action,payload_sha256,expected_mutation_epoch,authority_committed)
    ON cragkit_qdrant.publication_intents TO cragkit_qdrant_security_guard;
-- SG-r2: existing PUBLIC document RLS evaluates this read-only dependency chain.
GRANT EXECUTE ON FUNCTION cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean),
    cragkit_qdrant.scope_grants(), cragkit_qdrant.valid_identity_array(text[])
    TO cragkit_qdrant_security_guard;

CREATE POLICY security_guard_backend_select ON cragkit_qdrant.backend_instances FOR SELECT TO cragkit_qdrant_security_guard
    USING(instance_id=pg_catalog.current_setting('cragkit_qdrant.backend_instance_id',true));
CREATE POLICY security_guard_backend_update ON cragkit_qdrant.backend_instances FOR UPDATE TO cragkit_qdrant_security_guard
    USING(instance_id=pg_catalog.current_setting('cragkit_qdrant.backend_instance_id',true)) WITH CHECK(false);
CREATE POLICY security_guard_owner_select ON cragkit_qdrant.document_owners FOR SELECT TO cragkit_qdrant_security_guard
    USING(instance_id=pg_catalog.current_setting('cragkit_qdrant.backend_instance_id',true));
CREATE POLICY security_guard_owner_update ON cragkit_qdrant.document_owners FOR UPDATE TO cragkit_qdrant_security_guard
    USING(instance_id=pg_catalog.current_setting('cragkit_qdrant.backend_instance_id',true)) WITH CHECK(false);
CREATE POLICY security_guard_document_select ON cragkit_qdrant.documents FOR SELECT TO cragkit_qdrant_security_guard
    USING(EXISTS(SELECT 1 FROM cragkit_qdrant.document_owners o WHERE o.tenant_id=documents.tenant_id
        AND o.collection=documents.collection AND o.document_id=documents.document_id
        AND o.instance_id=pg_catalog.current_setting('cragkit_qdrant.backend_instance_id',true)));
CREATE POLICY security_guard_document_update ON cragkit_qdrant.documents FOR UPDATE TO cragkit_qdrant_security_guard
    USING(EXISTS(SELECT 1 FROM cragkit_qdrant.document_owners o WHERE o.tenant_id=documents.tenant_id
        AND o.collection=documents.collection AND o.document_id=documents.document_id
        AND o.instance_id=pg_catalog.current_setting('cragkit_qdrant.backend_instance_id',true))) WITH CHECK(false);
CREATE POLICY security_guard_intent_select ON cragkit_qdrant.publication_intents FOR SELECT TO cragkit_qdrant_security_guard
    USING(instance_id=pg_catalog.current_setting('cragkit_qdrant.backend_instance_id',true));

CREATE FUNCTION cragkit_qdrant.lock_current_security(
    p_instance_id text, p_backend_namespace text, p_storage_identity text, p_supervisor_id text,
    p_recovery_id text, p_backend_epoch bigint, p_tenant_id text, p_collection text,
    p_document_id text, p_owner_intent_id text, p_owner_token uuid, p_security_intent_id text,
    p_security_payload_sha256 text, p_active_generation_id text, p_authorization_revision text,
    p_mutation_epoch bigint, p_principal_ids text[], p_grant_ids text[],
    p_language text, p_kind text, p_tag text, p_tombstoned boolean
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT
SET search_path=pg_catalog SET row_security=on AS $guard$
DECLARE
    caller_id oid;
    guard_id oid;
    supervisor_role_id oid;
    operator_id oid;
    function_id oid;
    identity_value text;
    acl_value text[];
    backend_row record;
    owner_row record;
    document_row record;
    security_row record;
BEGIN
    SELECT oid INTO caller_id FROM pg_catalog.pg_roles WHERE rolname=session_user;
    SELECT oid INTO guard_id FROM pg_catalog.pg_roles WHERE rolname='cragkit_qdrant_security_guard';
    SELECT oid INTO supervisor_role_id FROM pg_catalog.pg_roles WHERE rolname='cragkit_qdrant_supervisor';
    SELECT nspowner INTO operator_id FROM pg_catalog.pg_namespace WHERE nspname='cragkit_qdrant';
    function_id:=pg_catalog.to_regprocedure('cragkit_qdrant.lock_current_security(text,text,text,text,text,bigint,text,text,text,text,uuid,text,text,text,text,bigint,text[],text[],text,text,text,boolean)');

    IF pg_catalog.current_setting('role',true) IS DISTINCT FROM 'none'
       OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE oid=caller_id AND rolcanlogin
           AND NOT(rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication))
       OR NOT pg_catalog.pg_has_role(caller_id,supervisor_role_id,'USAGE')
       OR pg_catalog.pg_has_role(caller_id,'cragkit_qdrant_writer','MEMBER')
       OR pg_catalog.pg_has_role(caller_id,guard_id,'MEMBER')
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_roles r WHERE pg_catalog.pg_has_role(caller_id,r.oid,'MEMBER')
           AND (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication
                OR r.rolname IN ('pg_read_all_data','pg_write_all_data','pg_read_server_files','pg_write_server_files','pg_execute_server_program')))
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_database d WHERE pg_catalog.pg_has_role(caller_id,d.datdba,'MEMBER'))
       OR NOT pg_catalog.has_schema_privilege(caller_id,'cragkit_qdrant','USAGE')
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_namespace n WHERE n.nspname='cragkit_qdrant'
           AND (pg_catalog.pg_has_role(caller_id,n.nspowner,'MEMBER') OR pg_catalog.has_schema_privilege(caller_id,n.oid,'CREATE')))
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname='cragkit_qdrant' AND pg_catalog.pg_has_role(caller_id,c.relowner,'MEMBER'))
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
           WHERE n.nspname='cragkit_qdrant' AND pg_catalog.pg_has_role(caller_id,p.proowner,'MEMBER'))
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
           WHERE n.nspname='cragkit_qdrant' AND pg_catalog.pg_has_role(caller_id,t.typowner,'MEMBER'))
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
          CROSS JOIN pg_catalog.unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) privilege
          WHERE n.nspname='cragkit_qdrant' AND c.relkind='r'
          AND pg_catalog.has_table_privilege(caller_id,c.oid,privilege) IS DISTINCT FROM CASE
            WHEN privilege='SELECT' THEN c.relname IN ('schema_migrations','backend_instances','document_owners','point_claims','dispatch_points','preparations')
            WHEN privilege='INSERT' THEN c.relname IN ('backend_instances','dispatch_journal','dispatch_points')
            WHEN privilege='UPDATE' THEN c.relname='backend_instances' ELSE false END)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
          JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
          CROSS JOIN pg_catalog.unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) privilege
          WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
          AND pg_catalog.has_column_privilege(caller_id,c.oid,a.attnum,privilege) IS DISTINCT FROM CASE
            WHEN privilege='SELECT' THEN c.relname IN ('schema_migrations','backend_instances','document_owners','point_claims','dispatch_points','preparations')
              OR (c.relname='publication_intents' AND a.attname IN ('tenant_id','collection','document_id','intent_id','instance_id','action','payload_sha256','manifest_sha256','revision_id','generation_id','expected_active_generation_id','expected_authorization_revision','expected_mutation_epoch','state','authority_committed','replica_complete','purge_complete'))
              OR (c.relname='dispatch_journal' AND a.attname IN ('tenant_id','collection','document_id','intent_id','dispatch_id','instance_id','sequence','owner_token','backend_epoch','credential_generation','operation','recovery','request_sha256','state','completion_sha256','created_xid'))
            WHEN privilege='INSERT' THEN c.relname IN ('backend_instances','dispatch_journal','dispatch_points')
            WHEN privilege='UPDATE' THEN c.relname='backend_instances'
              OR (c.relname='document_owners' AND a.attname='backend_epoch')
              OR (c.relname='dispatch_journal' AND a.attname IN ('state','completion_sha256')) ELSE false END)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname='cragkit_qdrant' AND pg_catalog.has_function_privilege(caller_id,p.oid,'EXECUTE') IS DISTINCT FROM
          (p.oid=function_id OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.valid_identity_array(text[])')
           OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.scope_grants()')
           OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.writer_scope(text,text,text)')
           OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.bound_stage(text,text,text,text,text)')
           OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.supervisor_instance(text)')
           OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.lock_publication_owner(text,text,text,text,uuid,bigint,boolean)'))) THEN
        RAISE EXCEPTION 'security guard caller rejected' USING ERRCODE='42501';
    END IF;

    IF current_user<>'cragkit_qdrant_security_guard'
       OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE oid=guard_id AND NOT
           (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication OR rolinherit))
       OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE oid=supervisor_role_id AND NOT
           (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication OR rolinherit))
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members WHERE member IN (guard_id,supervisor_role_id))
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspowner=supervisor_role_id)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_class WHERE relowner=supervisor_role_id)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc WHERE proowner=supervisor_role_id)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_type WHERE typowner=supervisor_role_id)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_database WHERE datdba=supervisor_role_id)
       OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE oid=operator_id AND rolcreaterole AND NOT rolsuper AND NOT rolbypassrls)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.roleid=guard_id AND NOT
           (m.member=operator_id AND NOT m.inherit_option AND
             ((m.grantor=10 AND m.admin_option AND NOT m.set_option)
              OR (m.grantor=operator_id AND NOT m.admin_option AND m.set_option))))
       OR (SELECT count(*) FROM pg_catalog.pg_auth_members WHERE roleid=guard_id)<>2
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_roles r WHERE NOT r.rolsuper AND
           (pg_catalog.pg_has_role(r.oid,supervisor_role_id,'MEMBER') OR pg_catalog.pg_has_role(r.oid,'cragkit_qdrant_writer','MEMBER'))
           AND pg_catalog.pg_has_role(r.oid,operator_id,'MEMBER'))
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspowner=guard_id)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND c.relowner<>operator_id)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_class WHERE relowner=guard_id)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_type WHERE typowner=guard_id)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_database WHERE datdba=guard_id)
       OR (SELECT count(*) FROM pg_catalog.pg_proc WHERE proowner=guard_id)<>1
       OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_proc WHERE oid=function_id AND proowner=guard_id AND prosecdef
           AND provolatile='v' AND proparallel='u' AND NOT proisstrict AND NOT proleakproof
           AND proconfig=ARRAY['search_path=pg_catalog','row_security=on']::text[])
       OR pg_catalog.has_schema_privilege(guard_id,'cragkit_qdrant','CREATE')
       OR NOT pg_catalog.has_schema_privilege(guard_id,'cragkit_qdrant','USAGE')
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND c.relname<>'schema_migrations'
             AND NOT(c.relrowsecurity AND c.relforcerowsecurity))
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
           WHERE n.nspname='cragkit_qdrant' AND p.prosecdef AND p.oid<>function_id)
       OR (SELECT count(*) FROM pg_catalog.pg_policy WHERE guard_id=ANY(polroles))<>7
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_policy WHERE guard_id=ANY(polroles) AND
          (polroles<>ARRAY[guard_id]::oid[] OR NOT polpermissive OR polqual IS NULL
           OR polname NOT IN ('security_guard_backend_select','security_guard_backend_update','security_guard_owner_select',
                             'security_guard_owner_update','security_guard_document_select','security_guard_document_update','security_guard_intent_select')
           OR polcmd NOT IN ('r','w') OR (polcmd='w' AND pg_catalog.pg_get_expr(polwithcheck,polrelid) IS DISTINCT FROM 'false'))) THEN
        RAISE EXCEPTION 'security guard profile rejected' USING ERRCODE='22023';
    END IF;

    -- Effective ACL checks include table grants, inherited grants and PUBLIC.
    IF EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN pg_catalog.unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) privilege
        WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND pg_catalog.has_table_privilege(guard_id,c.oid,privilege))
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN pg_catalog.unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) privilege
        WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
        AND pg_catalog.has_column_privilege(guard_id,c.oid,a.attnum,privilege) IS DISTINCT FROM CASE
          WHEN privilege='SELECT' THEN
            (c.relname='backend_instances' AND a.attname IN ('instance_id','backend_namespace','storage_identity','supervisor_id','epoch','state','recovery_id'))
            OR (c.relname='document_owners' AND a.attname IN ('tenant_id','collection','document_id','instance_id','intent_id','owner_token','backend_epoch'))
            OR (c.relname='documents' AND a.attname IN ('tenant_id','collection','document_id','active_generation_id','authorization_revision','mutation_epoch','principal_ids','grant_ids','language','kind','tag','tombstoned'))
            OR (c.relname='publication_intents' AND a.attname IN ('tenant_id','collection','document_id','intent_id','instance_id','action','payload_sha256','expected_mutation_epoch','authority_committed'))
          WHEN privilege='UPDATE' THEN (c.relname='backend_instances' AND a.attname='epoch')
            OR (c.relname='document_owners' AND a.attname='backend_epoch') OR (c.relname='documents' AND a.attname='mutation_epoch')
          ELSE false END)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname='cragkit_qdrant' AND pg_catalog.has_function_privilege(guard_id,p.oid,'EXECUTE') IS DISTINCT FROM
            (p.oid=function_id OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean)')
             OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.scope_grants()')
             OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.valid_identity_array(text[])')))
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p CROSS JOIN LATERAL pg_catalog.aclexplode(p.proacl) a
          WHERE p.oid=function_id AND (a.grantee NOT IN (guard_id,supervisor_role_id) OR a.grantor<>guard_id
            OR a.privilege_type<>'EXECUTE' OR (a.grantee=supervisor_role_id AND a.is_grantable)))
       OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p CROSS JOIN LATERAL pg_catalog.aclexplode(p.proacl) a
          WHERE p.oid=function_id AND a.grantee=supervisor_role_id AND a.privilege_type='EXECUTE' AND NOT a.is_grantable) THEN
        RAISE EXCEPTION 'security guard ACL rejected' USING ERRCODE='22023';
    END IF;

    IF pg_catalog.current_setting('transaction_isolation')<>'read committed'
       OR p_instance_id IS DISTINCT FROM pg_catalog.current_setting('cragkit_qdrant.backend_instance_id',true)
       OR p_owner_token IS NULL OR p_tombstoned IS NULL
       OR p_security_payload_sha256 IS NULL OR p_security_payload_sha256 !~ '^[0-9a-f]{64}$'
       OR p_backend_epoch IS NULL OR p_backend_epoch NOT BETWEEN 1 AND 9007199254740991
       OR p_mutation_epoch IS NULL OR p_mutation_epoch NOT BETWEEN 1 AND 9007199254740991 THEN
        RAISE EXCEPTION 'invalid security guard input' USING ERRCODE='22023';
    END IF;
    FOREACH identity_value IN ARRAY ARRAY[p_instance_id,p_backend_namespace,p_storage_identity,p_supervisor_id,
        p_recovery_id,p_tenant_id,p_document_id,p_owner_intent_id,p_security_intent_id,p_authorization_revision] LOOP
        IF identity_value IS NULL OR pg_catalog.octet_length(identity_value) NOT BETWEEN 1 AND 256
           OR pg_catalog.btrim(identity_value,E' \t\r\n\f\013')='' THEN
            RAISE EXCEPTION 'invalid security guard input' USING ERRCODE='22023';
        END IF;
    END LOOP;
    IF p_collection IS NULL OR pg_catalog.octet_length(p_collection) NOT BETWEEN 1 AND 128
       OR pg_catalog.btrim(p_collection,E' \t\r\n\f\013')=''
       OR (p_active_generation_id IS NOT NULL AND (pg_catalog.octet_length(p_active_generation_id) NOT BETWEEN 1 AND 256
           OR pg_catalog.btrim(p_active_generation_id,E' \t\r\n\f\013')=''))
       OR EXISTS(SELECT 1 FROM pg_catalog.unnest(ARRAY[p_language,p_kind,p_tag]) value WHERE pg_catalog.octet_length(value)>1024) THEN
        RAISE EXCEPTION 'invalid security guard input' USING ERRCODE='22023';
    END IF;
    FOREACH identity_value IN ARRAY ARRAY['principal','grant'] LOOP
        acl_value:=CASE WHEN identity_value='principal' THEN p_principal_ids ELSE p_grant_ids END;
        IF acl_value IS NULL OR pg_catalog.cardinality(acl_value)>64
           OR (pg_catalog.cardinality(acl_value)>0 AND (pg_catalog.array_ndims(acl_value)<>1 OR pg_catalog.array_lower(acl_value,1)<>1))
           OR EXISTS(SELECT 1 FROM pg_catalog.unnest(acl_value) member WHERE member IS NULL
              OR pg_catalog.octet_length(member) NOT BETWEEN 1 AND 256 OR pg_catalog.btrim(member,E' \t\r\n\f\013')='')
           OR (SELECT count(DISTINCT pg_catalog.convert_to(member,'UTF8')) FROM pg_catalog.unnest(acl_value) member)<>pg_catalog.cardinality(acl_value)
           OR acl_value IS DISTINCT FROM COALESCE((SELECT pg_catalog.array_agg(member ORDER BY pg_catalog.convert_to(member,'UTF8'))
              FROM pg_catalog.unnest(acl_value) member),ARRAY[]::text[]) THEN
            RAISE EXCEPTION 'invalid security guard input' USING ERRCODE='22023';
        END IF;
    END LOOP;

    PERFORM instance_id FROM cragkit_qdrant.backend_instances WHERE instance_id=p_instance_id FOR SHARE;
    SELECT backend_namespace,storage_identity,supervisor_id,epoch,state,recovery_id INTO backend_row
      FROM cragkit_qdrant.backend_instances WHERE instance_id=p_instance_id;
    IF NOT FOUND OR ROW(backend_row.backend_namespace,backend_row.storage_identity,backend_row.supervisor_id,
        backend_row.epoch,backend_row.state,backend_row.recovery_id) IS DISTINCT FROM
        ROW(p_backend_namespace,p_storage_identity,p_supervisor_id,p_backend_epoch,'recovery_blocked'::text,p_recovery_id) THEN
        RAISE EXCEPTION 'security guard mismatch' USING ERRCODE='23514';
    END IF;
    PERFORM owner_token FROM cragkit_qdrant.document_owners WHERE tenant_id=p_tenant_id AND collection=p_collection
      AND document_id=p_document_id FOR UPDATE;
    SELECT instance_id,intent_id,owner_token,backend_epoch INTO owner_row FROM cragkit_qdrant.document_owners
      WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id;
    IF NOT FOUND OR ROW(owner_row.instance_id,owner_row.intent_id,owner_row.owner_token,owner_row.backend_epoch)
       IS DISTINCT FROM ROW(p_instance_id,p_owner_intent_id,p_owner_token,p_backend_epoch) THEN
        RAISE EXCEPTION 'security guard mismatch' USING ERRCODE='23514';
    END IF;
    PERFORM document_id FROM cragkit_qdrant.documents WHERE tenant_id=p_tenant_id AND collection=p_collection
      AND document_id=p_document_id FOR UPDATE;
    -- Reread after the document wait; never retain a pre-wait authority snapshot.
    SELECT backend_namespace,storage_identity,supervisor_id,epoch,state,recovery_id INTO backend_row
      FROM cragkit_qdrant.backend_instances WHERE instance_id=p_instance_id;
    IF NOT FOUND OR ROW(backend_row.backend_namespace,backend_row.storage_identity,backend_row.supervisor_id,
        backend_row.epoch,backend_row.state,backend_row.recovery_id) IS DISTINCT FROM
        ROW(p_backend_namespace,p_storage_identity,p_supervisor_id,p_backend_epoch,'recovery_blocked'::text,p_recovery_id) THEN
        RAISE EXCEPTION 'security guard mismatch' USING ERRCODE='23514';
    END IF;
    SELECT instance_id,intent_id,owner_token,backend_epoch INTO owner_row FROM cragkit_qdrant.document_owners
      WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id;
    IF NOT FOUND OR ROW(owner_row.instance_id,owner_row.intent_id,owner_row.owner_token,owner_row.backend_epoch)
       IS DISTINCT FROM ROW(p_instance_id,p_owner_intent_id,p_owner_token,p_backend_epoch) THEN
        RAISE EXCEPTION 'security guard mismatch' USING ERRCODE='23514';
    END IF;
    SELECT active_generation_id,authorization_revision,mutation_epoch,principal_ids,grant_ids,language,kind,tag,tombstoned
      INTO document_row FROM cragkit_qdrant.documents WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id;
    IF NOT FOUND OR ROW(document_row.active_generation_id,document_row.authorization_revision,document_row.mutation_epoch,
       document_row.principal_ids,document_row.grant_ids,document_row.language,document_row.kind,document_row.tag,document_row.tombstoned)
       IS DISTINCT FROM ROW(p_active_generation_id,p_authorization_revision,p_mutation_epoch,p_principal_ids,p_grant_ids,p_language,p_kind,p_tag,p_tombstoned) THEN
        RAISE EXCEPTION 'security guard mismatch' USING ERRCODE='23514';
    END IF;
    IF NOT EXISTS(SELECT 1 FROM cragkit_qdrant.publication_intents WHERE tenant_id=p_tenant_id AND collection=p_collection
        AND document_id=p_document_id AND intent_id=p_owner_intent_id AND instance_id=p_instance_id AND action='stage') THEN
        RAISE EXCEPTION 'security guard mismatch' USING ERRCODE='23514';
    END IF;
    SELECT action,payload_sha256,expected_mutation_epoch,authority_committed INTO security_row FROM cragkit_qdrant.publication_intents
      WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id
        AND intent_id=p_security_intent_id AND instance_id=p_instance_id;
    IF NOT FOUND OR p_security_intent_id=p_owner_intent_id OR security_row.action NOT IN ('update_authorization','tombstone')
       OR NOT security_row.authority_committed OR security_row.payload_sha256 IS DISTINCT FROM p_security_payload_sha256
       OR security_row.expected_mutation_epoch IS DISTINCT FROM p_mutation_epoch-1
       OR (security_row.action='tombstone' AND NOT p_tombstoned) THEN
        RAISE EXCEPTION 'security guard mismatch' USING ERRCODE='23514';
    END IF;
END
$guard$;

REVOKE ALL ON FUNCTION cragkit_qdrant.lock_current_security(text,text,text,text,text,bigint,text,text,text,text,uuid,text,text,text,text,bigint,text[],text[],text,text,text,boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cragkit_qdrant.lock_current_security(text,text,text,text,text,bigint,text,text,text,text,uuid,text,text,text,text,bigint,text[],text[],text,text,text,boolean) TO cragkit_qdrant_supervisor;
ALTER FUNCTION cragkit_qdrant.lock_current_security(text,text,text,text,text,bigint,text,text,text,text,uuid,text,text,text,text,bigint,text[],text[],text,text,text,boolean) OWNER TO cragkit_qdrant_security_guard;
REVOKE CREATE ON SCHEMA cragkit_qdrant FROM cragkit_qdrant_security_guard;
