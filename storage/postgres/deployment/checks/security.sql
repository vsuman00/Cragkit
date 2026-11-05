-- Administrative security assertions and temporary nonowner probe; all probe changes roll back.
BEGIN;
SET LOCAL search_path = pg_catalog;
SET LOCAL statement_timeout = '30s';
SET LOCAL lock_timeout = '5s';
SET LOCAL idle_in_transaction_session_timeout = '30s';
SELECT pg_advisory_xact_lock(1129464148, 1);

DO $inventory$
DECLARE
    api record;
    item record;
    schema_id oid;
    table_count integer;
    vector_schema_id oid;
    creator record;
    vector_table_count integer;
BEGIN
    SELECT oid INTO STRICT schema_id FROM pg_namespace WHERE nspname = 'cragkit';
    SELECT count(*) INTO table_count FROM pg_class
        WHERE relnamespace = schema_id AND relkind = 'r';
    SELECT count(*) INTO vector_table_count FROM pg_class
        WHERE relnamespace = schema_id AND relkind = 'r'
            AND relname IN ('embedding_profiles', 'chunk_vectors_fake_1536');
    IF vector_table_count NOT IN (0, 2)
        OR table_count <> 9 + vector_table_count THEN
        RAISE EXCEPTION 'unexpected cragkit table inventory';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class WHERE relnamespace = schema_id
        AND (relkind NOT IN ('r', 'i', 'S', 't') OR (relkind = 'r' AND NOT relrowsecurity))) THEN
        RAISE EXCEPTION 'unexpected relation or missing RLS';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_policy policy JOIN pg_class relation ON relation.oid = policy.polrelid
        WHERE relation.relnamespace = schema_id) THEN
        RAISE EXCEPTION 'unexpected cragkit row policy';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_proc WHERE pronamespace = schema_id AND prosecdef) THEN
        RAISE EXCEPTION 'unexpected cragkit SECURITY DEFINER function';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_namespace n,
        LATERAL aclexplode(coalesce(n.nspacl, acldefault('n', n.nspowner))) acl
        WHERE n.oid = schema_id AND acl.grantee = 0)
        OR EXISTS (SELECT 1 FROM pg_class relation,
            LATERAL aclexplode(coalesce(relation.relacl,
                acldefault(CASE WHEN relation.relkind = 'S' THEN 'S'::"char" ELSE 'r'::"char" END,
                    relation.relowner))) acl
            WHERE relation.relnamespace = schema_id AND relation.relkind IN ('r', 'S') AND acl.grantee = 0)
        OR EXISTS (SELECT 1 FROM pg_proc routine,
            LATERAL aclexplode(coalesce(routine.proacl, acldefault('f', routine.proowner))) acl
            WHERE routine.pronamespace = schema_id AND acl.grantee = 0)
        OR EXISTS (SELECT 1 FROM pg_type domain_type,
            LATERAL aclexplode(coalesce(domain_type.typacl, acldefault('T', domain_type.typowner))) acl
            WHERE domain_type.typnamespace = schema_id AND domain_type.typtype = 'd' AND acl.grantee = 0) THEN
        RAISE EXCEPTION 'PUBLIC retains cragkit object privileges';
    END IF;
    FOR api IN SELECT oid, rolname, rolsuper, rolcreaterole, rolcreatedb FROM pg_roles
        WHERE rolname IN ('anon', 'authenticated', 'service_role') LOOP
        IF api.rolsuper OR api.rolcreaterole OR api.rolcreatedb THEN
            RAISE EXCEPTION 'API role has unexpected administrative attributes';
        END IF;
        IF has_schema_privilege(api.oid, schema_id, 'USAGE,CREATE') THEN
            RAISE EXCEPTION 'API role can reach cragkit schema';
        END IF;
        FOR item IN SELECT nspowner AS owner FROM pg_namespace WHERE oid = schema_id
            UNION SELECT relowner FROM pg_class WHERE relnamespace = schema_id
            UNION SELECT proowner FROM pg_proc WHERE pronamespace = schema_id
            UNION SELECT typowner FROM pg_type WHERE typnamespace = schema_id AND typtype = 'd' LOOP
            IF pg_has_role(api.oid, item.owner, 'USAGE') OR pg_has_role(api.oid, item.owner, 'SET') THEN
                RAISE EXCEPTION 'API role can assume a cragkit owner';
            END IF;
        END LOOP;
        FOR item IN SELECT oid, relkind FROM pg_class WHERE relnamespace = schema_id LOOP
            IF item.relkind = 'r' AND (
                has_table_privilege(api.oid, item.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                OR has_any_column_privilege(api.oid, item.oid, 'SELECT,INSERT,UPDATE,REFERENCES')) THEN
                RAISE EXCEPTION 'API role retains cragkit table privileges';
            ELSIF item.relkind = 'S' AND has_sequence_privilege(api.oid, item.oid, 'USAGE,SELECT,UPDATE') THEN
                RAISE EXCEPTION 'API role retains cragkit sequence privileges';
            END IF;
        END LOOP;
        IF EXISTS (SELECT 1 FROM pg_proc WHERE pronamespace = schema_id
            AND has_function_privilege(api.oid, oid, 'EXECUTE')) THEN
            RAISE EXCEPTION 'API role retains cragkit function privileges';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_type WHERE typnamespace = schema_id AND typtype = 'd'
            AND has_type_privilege(api.oid, oid, 'USAGE')) THEN
            RAISE EXCEPTION 'API role retains cragkit domain privileges';
        END IF;
    END LOOP;
    -- A schema-local REVOKE cannot remove an implicit/global PUBLIC default.
    -- Check both effective global defaults and additive schema-local grants for
    -- application object creators. Platform extension owners are checked below.
    FOR creator IN
        SELECT nspowner AS owner FROM pg_namespace WHERE nspname IN ('cragkit','cragkit_vector')
        UNION SELECT relowner FROM pg_class WHERE relnamespace = schema_id AND relkind = 'r'
        UNION SELECT proowner FROM pg_proc WHERE pronamespace = schema_id
        UNION SELECT typowner FROM pg_type WHERE typnamespace = schema_id AND typtype = 'd'
    LOOP
        IF EXISTS (
            SELECT 1 FROM (VALUES ('f'::"char"), ('T'::"char")) kind(object_type)
            LEFT JOIN pg_default_acl defaults ON defaults.defaclrole = creator.owner
                AND defaults.defaclnamespace = 0 AND defaults.defaclobjtype = kind.object_type
            CROSS JOIN LATERAL aclexplode(coalesce(defaults.defaclacl,
                acldefault(kind.object_type, creator.owner))) acl
            WHERE acl.grantee = 0 OR acl.grantee IN (
                SELECT oid FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role'))
        ) OR EXISTS (
            SELECT 1 FROM pg_default_acl defaults
            CROSS JOIN LATERAL aclexplode(defaults.defaclacl) acl
            WHERE defaults.defaclrole = creator.owner
                AND (defaults.defaclnamespace = 0 OR defaults.defaclnamespace IN (
                    SELECT oid FROM pg_namespace WHERE nspname IN ('cragkit','cragkit_vector')))
                AND (acl.grantee = 0 OR acl.grantee IN (
                    SELECT oid FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role')))
        ) THEN
            RAISE EXCEPTION 'unsafe application creator default privileges';
        END IF;
    END LOOP;

    SELECT oid INTO vector_schema_id FROM pg_namespace WHERE nspname = 'cragkit_vector';
    IF vector_schema_id IS NULL AND vector_table_count <> 0 THEN
        RAISE EXCEPTION 'vector storage requires private extension schema';
    END IF;
    IF vector_schema_id IS NOT NULL THEN
        IF NOT EXISTS (SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
            WHERE e.extname='vector' AND e.extversion='0.8.0' AND n.oid=vector_schema_id
                AND e.extowner=n.nspowner)
            OR NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.oid=vector_schema_id AND c.relname='setup_history' AND c.relkind='r'
                    AND c.relrowsecurity AND c.relowner=n.nspowner)
            OR EXISTS (SELECT 1 FROM pg_policy policy JOIN pg_class c ON c.oid=policy.polrelid
                WHERE c.relnamespace=vector_schema_id)
            OR EXISTS (SELECT 1 FROM pg_proc WHERE pronamespace=vector_schema_id AND prosecdef)
        THEN RAISE EXCEPTION 'unsafe vector extension or setup ledger'; END IF;
        -- Only extension primitives and the administrator's setup ledger belong here.
        IF EXISTS (SELECT 1 FROM pg_class c WHERE c.relnamespace=vector_schema_id
            AND c.oid<>'cragkit_vector.setup_history'::regclass
            AND NOT (c.relkind='i' AND EXISTS (SELECT 1 FROM pg_index i
                WHERE i.indexrelid=c.oid AND i.indrelid='cragkit_vector.setup_history'::regclass)))
            OR EXISTS (SELECT 1 FROM pg_proc p WHERE p.pronamespace=vector_schema_id
                AND NOT EXISTS (SELECT 1 FROM pg_depend d JOIN pg_extension e ON e.oid=d.refobjid
                    WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid
                        AND d.refclassid='pg_extension'::regclass AND d.deptype='e' AND e.extname='vector'))
            OR EXISTS (SELECT 1 FROM pg_type t WHERE t.typnamespace=vector_schema_id
                AND NOT (t.typtype='c' AND t.typrelid='cragkit_vector.setup_history'::regclass)
                AND NOT (t.typtype='b' AND t.typname IN ('vector','halfvec','sparsevec')
                    AND EXISTS (SELECT 1 FROM pg_depend d JOIN pg_extension e ON e.oid=d.refobjid
                        WHERE d.classid='pg_type'::regclass AND d.objid=t.oid
                            AND d.refclassid='pg_extension'::regclass AND d.deptype='e' AND e.extname='vector'))
                AND NOT (t.typelem<>0 AND EXISTS (SELECT 1 FROM pg_type element
                    WHERE element.oid=t.typelem AND element.typnamespace=vector_schema_id
                        AND ((element.typtype='c' AND element.typrelid='cragkit_vector.setup_history'::regclass)
                            OR (element.typtype='b' AND element.typname IN ('vector','halfvec','sparsevec')
                                AND EXISTS (SELECT 1 FROM pg_depend d JOIN pg_extension e ON e.oid=d.refobjid
                                    WHERE d.classid='pg_type'::regclass AND d.objid=element.oid
                                        AND d.refclassid='pg_extension'::regclass AND d.deptype='e' AND e.extname='vector'))))))
        THEN RAISE EXCEPTION 'unexpected vector object inventory'; END IF;
        IF EXISTS (SELECT 1 FROM pg_namespace n,
            LATERAL aclexplode(coalesce(n.nspacl,acldefault('n',n.nspowner))) acl
            WHERE n.oid=vector_schema_id AND acl.grantee<>n.nspowner)
            OR EXISTS (SELECT 1 FROM pg_class c,
                LATERAL aclexplode(coalesce(c.relacl,
                    acldefault(CASE WHEN c.relkind='S' THEN 'S'::"char" ELSE 'r'::"char" END,c.relowner))) acl
                WHERE c.relnamespace=vector_schema_id AND c.relkind IN ('r','S') AND acl.grantee<>c.relowner)
            OR EXISTS (SELECT 1 FROM pg_type t,
                LATERAL aclexplode(coalesce(t.typacl,acldefault('T',t.typowner))) acl
                WHERE t.typnamespace=vector_schema_id AND t.typname IN ('vector','halfvec','sparsevec')
                    AND acl.grantee<>t.typowner
                    AND NOT (coalesce(current_setting('cragkit.security_vector_profile',true),'strict')='neon-managed'
                        AND acl.grantee=0 AND acl.privilege_type='USAGE' AND NOT acl.is_grantable
                        AND t.typtype='b'
                        AND EXISTS (SELECT 1 FROM pg_roles r WHERE r.oid=t.typowner AND r.rolname='cloud_admin')
                        AND EXISTS (SELECT 1 FROM pg_depend d JOIN pg_extension e ON e.oid=d.refobjid
                            WHERE d.classid='pg_type'::regclass AND d.objid=t.oid
                                AND d.refclassid='pg_extension'::regclass AND d.deptype='e' AND e.extname='vector')))
        THEN RAISE EXCEPTION 'unexpected vector schema table or type privileges'; END IF;
        IF EXISTS (SELECT 1 FROM pg_proc p,
            LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) acl
            WHERE p.pronamespace=vector_schema_id AND acl.grantee<>p.proowner
                AND NOT (coalesce(current_setting('cragkit.security_vector_profile',true),'strict')='neon-managed'
                    AND acl.grantee=0 AND acl.privilege_type='EXECUTE' AND NOT acl.is_grantable
                    AND EXISTS (SELECT 1 FROM pg_roles r WHERE r.oid=p.proowner AND r.rolname='cloud_admin')
                    AND EXISTS (SELECT 1 FROM pg_depend d JOIN pg_extension e ON e.oid=d.refobjid
                        WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid
                            AND d.refclassid='pg_extension'::regclass AND d.deptype='e' AND e.extname='vector')))
        THEN RAISE EXCEPTION 'unexpected vector function privileges'; END IF;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cragkit_security_probe') THEN
        RAISE EXCEPTION 'security probe role already exists';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM cragkit.migration_history) THEN
        RAISE EXCEPTION 'security probe requires a populated migration ledger';
    END IF;
END
$inventory$;

SELECT count(*) AS checked_api_roles FROM pg_roles
    WHERE rolname IN ('anon', 'authenticated', 'service_role');

INSERT INTO cragkit.collections (tenant_id, collection_id)
    VALUES ('cragkit-security-probe', 'security-probe');
CREATE ROLE cragkit_security_probe NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
DO $membership$
BEGIN
    EXECUTE format('GRANT cragkit_security_probe TO %I WITH SET TRUE', current_user);
END
$membership$;
GRANT USAGE ON SCHEMA cragkit TO cragkit_security_probe;
GRANT USAGE ON DOMAIN cragkit.identity_text, cragkit.collection_text TO cragkit_security_probe;
GRANT SELECT ON cragkit.collections, cragkit.documents, cragkit.document_revisions,
    cragkit.index_generations, cragkit.chunks, cragkit.chunk_lexical,
    cragkit.document_grants, cragkit.ingestion_jobs, cragkit.migration_history TO cragkit_security_probe;
GRANT INSERT ON cragkit.collections TO cragkit_security_probe;
DO $vector_grants$
BEGIN
    IF to_regclass('cragkit.embedding_profiles') IS NOT NULL THEN
        GRANT SELECT ON cragkit.embedding_profiles, cragkit.chunk_vectors_fake_1536
            TO cragkit_security_probe;
    END IF;
END
$vector_grants$;
SET LOCAL ROLE cragkit_security_probe;

DO $probe$
DECLARE
    table_name text;
    visible_rows bigint;
BEGIN
    IF current_user <> 'cragkit_security_probe' OR EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = current_user AND (rolsuper OR rolbypassrls OR rolcanlogin)
    ) THEN
        RAISE EXCEPTION 'invalid nonowner probe role';
    END IF;
    FOREACH table_name IN ARRAY ARRAY['collections', 'documents', 'document_revisions',
        'index_generations', 'chunks', 'chunk_lexical', 'document_grants', 'ingestion_jobs', 'migration_history'] LOOP
        EXECUTE format('SELECT count(*) FROM cragkit.%I', table_name) INTO visible_rows;
        IF visible_rows <> 0 THEN
            RAISE EXCEPTION 'default deny exposed rows';
        END IF;
    END LOOP;
    IF to_regclass('cragkit.embedding_profiles') IS NOT NULL THEN
        EXECUTE 'SELECT count(*) FROM cragkit.embedding_profiles' INTO visible_rows;
        IF visible_rows <> 0 THEN
            RAISE EXCEPTION 'default deny exposed embedding profile rows';
        END IF;
        EXECUTE 'SELECT count(*) FROM cragkit.chunk_vectors_fake_1536' INTO visible_rows;
        IF visible_rows <> 0 THEN
            RAISE EXCEPTION 'default deny exposed vector rows';
        END IF;
    END IF;
    BEGIN
        INSERT INTO cragkit.collections (tenant_id, collection_id)
            VALUES ('cragkit-security-probe', 'denied-insert');
        RAISE EXCEPTION 'default deny allowed an insert';
    EXCEPTION WHEN insufficient_privilege THEN
        NULL;
    END;
END
$probe$;

ROLLBACK;
SELECT 'cragkit_security_probe_ok';
