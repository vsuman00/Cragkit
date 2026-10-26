-- Explicit additive managed-publication profile. The administrator records the
-- actual artifact checksum in schema_migrations in the same install transaction.
DO $migration$
DECLARE
    capability text;
    role_id oid;
BEGIN
    IF current_setting('server_version_num')::integer NOT BETWEEN 170000 AND 179999 THEN
        RAISE EXCEPTION 'unsupported publication database profile' USING ERRCODE = '22023';
    END IF;
    IF (SELECT count(*) FROM cragkit_qdrant.schema_migrations) <> 1 OR NOT EXISTS (
        SELECT 1 FROM cragkit_qdrant.schema_migrations
        WHERE version = '0001_authority'
          AND checksum_sha256 = '3d75cd46eb32a10864f1097a7494b01f9759150911a7cd9a1e6aab60105c1f1a'
    ) THEN
        RAISE EXCEPTION 'unsupported authority history' USING ERRCODE = '22023';
    END IF;
    FOREACH capability IN ARRAY ARRAY['cragkit_qdrant_writer', 'cragkit_qdrant_supervisor'] LOOP
        SELECT oid INTO role_id FROM pg_catalog.pg_roles
        WHERE rolname = capability AND NOT rolcanlogin AND NOT rolsuper
            AND NOT rolbypassrls AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication;
        IF role_id IS NULL OR EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members WHERE member = role_id)
            OR EXISTS (SELECT 1 FROM pg_catalog.pg_namespace WHERE nspowner = role_id)
            OR EXISTS (SELECT 1 FROM pg_catalog.pg_class WHERE relowner = role_id)
            OR EXISTS (SELECT 1 FROM pg_catalog.pg_proc WHERE proowner = role_id)
            OR EXISTS (SELECT 1 FROM pg_catalog.pg_type WHERE typowner = role_id)
            OR EXISTS (SELECT 1 FROM pg_catalog.pg_database WHERE datdba = role_id) THEN
            RAISE EXCEPTION 'unsafe or absent publication capability role' USING ERRCODE = '22023';
        END IF;
    END LOOP;
END
$migration$;

ALTER TABLE cragkit_qdrant.generations ADD CONSTRAINT managed_generation_member_limit
    CHECK (expected_member_count BETWEEN 1 AND 64);
DO $migration$
BEGIN
    IF EXISTS (SELECT 1 FROM cragkit_qdrant.members
        GROUP BY tenant_id, collection, document_id, generation_id HAVING count(*) > 64) THEN
        RAISE EXCEPTION 'existing generation exceeds managed member limit' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (SELECT 1 FROM cragkit_qdrant.generations AS generation
        JOIN cragkit_qdrant.documents AS document USING (tenant_id,collection,document_id)
        WHERE generation.published AND generation.generation_id IS DISTINCT FROM document.active_generation_id)
        OR EXISTS (SELECT 1 FROM cragkit_qdrant.documents AS document
            WHERE document.active_generation_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM cragkit_qdrant.generations AS generation
                WHERE generation.tenant_id = document.tenant_id AND generation.collection = document.collection
                    AND generation.document_id = document.document_id
                    AND generation.generation_id = document.active_generation_id AND generation.published)) THEN
        RAISE EXCEPTION 'existing publication flags disagree' USING ERRCODE = '23514';
    END IF;
END
$migration$;

CREATE TABLE cragkit_qdrant.backend_instances (
    instance_id cragkit_qdrant.identity_text PRIMARY KEY,
    backend_namespace cragkit_qdrant.identity_text NOT NULL UNIQUE,
    storage_identity cragkit_qdrant.identity_text NOT NULL,
    supervisor_id cragkit_qdrant.identity_text NOT NULL,
    epoch cragkit_qdrant.safe_count NOT NULL DEFAULT 1 CHECK (epoch > 0),
    state text COLLATE pg_catalog."C" NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'recovery_blocked')),
    recovery_id cragkit_qdrant.identity_text,
    CHECK ((state = 'recovery_blocked') = (recovery_id IS NOT NULL))
);

CREATE TABLE cragkit_qdrant.publication_intents (
    tenant_id cragkit_qdrant.identity_text NOT NULL,
    collection cragkit_qdrant.collection_text NOT NULL,
    document_id cragkit_qdrant.identity_text NOT NULL,
    intent_id cragkit_qdrant.identity_text NOT NULL,
    instance_id cragkit_qdrant.identity_text NOT NULL REFERENCES cragkit_qdrant.backend_instances,
    action text COLLATE pg_catalog."C" NOT NULL CHECK (action IN ('stage', 'update_authorization', 'tombstone', 'purge')),
    payload_bytes bytea NOT NULL CHECK (octet_length(payload_bytes) BETWEEN 1 AND 1048576),
    payload_sha256 cragkit_qdrant.sha256_hex NOT NULL CHECK (payload_sha256 = encode(sha256(payload_bytes), 'hex')),
    manifest_bytes bytea CHECK (octet_length(manifest_bytes) BETWEEN 1 AND 1048576),
    manifest_sha256 cragkit_qdrant.sha256_hex,
    revision_id cragkit_qdrant.identity_text,
    generation_id cragkit_qdrant.identity_text,
    expected_active_generation_id cragkit_qdrant.identity_text,
    expected_authorization_revision cragkit_qdrant.identity_text NOT NULL,
    expected_mutation_epoch cragkit_qdrant.safe_count NOT NULL,
    state text COLLATE pg_catalog."C" NOT NULL DEFAULT 'staged'
        CHECK (state IN ('staged', 'writing', 'prepared', 'published', 'conflict', 'denied', 'authority_committed', 'complete')),
    authority_committed boolean NOT NULL DEFAULT false,
    replica_complete boolean NOT NULL DEFAULT false,
    purge_complete boolean NOT NULL DEFAULT false,
    PRIMARY KEY (tenant_id, collection, document_id, intent_id),
    FOREIGN KEY (tenant_id, collection, document_id) REFERENCES cragkit_qdrant.documents
        DEFERRABLE INITIALLY DEFERRED,
    CHECK ((action = 'stage' AND manifest_bytes IS NOT NULL AND manifest_sha256 IS NOT NULL
        AND revision_id IS NOT NULL AND generation_id IS NOT NULL)
        OR (action <> 'stage' AND manifest_bytes IS NULL AND manifest_sha256 IS NULL
            AND revision_id IS NULL AND generation_id IS NULL AND expected_active_generation_id IS NULL)),
    CHECK (manifest_bytes IS NULL OR manifest_sha256 = encode(sha256(manifest_bytes), 'hex')),
    CHECK (NOT purge_complete OR (action = 'purge' AND replica_complete AND authority_committed)),
    CHECK (NOT replica_complete OR authority_committed)
);

CREATE TABLE cragkit_qdrant.document_owners (
    tenant_id cragkit_qdrant.identity_text NOT NULL,
    collection cragkit_qdrant.collection_text NOT NULL,
    document_id cragkit_qdrant.identity_text NOT NULL,
    instance_id cragkit_qdrant.identity_text NOT NULL REFERENCES cragkit_qdrant.backend_instances,
    intent_id cragkit_qdrant.identity_text NOT NULL,
    owner_token uuid NOT NULL,
    backend_epoch cragkit_qdrant.safe_count NOT NULL CHECK (backend_epoch > 0),
    PRIMARY KEY (tenant_id, collection, document_id),
    FOREIGN KEY (tenant_id, collection, document_id, intent_id)
        REFERENCES cragkit_qdrant.publication_intents DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE cragkit_qdrant.point_claims (
    backend_namespace cragkit_qdrant.identity_text NOT NULL,
    physical_collection text COLLATE pg_catalog."C" NOT NULL CHECK (physical_collection ~ '^[A-Za-z][A-Za-z0-9_-]{0,63}$'),
    collection_incarnation cragkit_qdrant.identity_text NOT NULL,
    point_id uuid NOT NULL,
    instance_id cragkit_qdrant.identity_text NOT NULL REFERENCES cragkit_qdrant.backend_instances,
    tenant_id cragkit_qdrant.identity_text NOT NULL,
    collection cragkit_qdrant.collection_text NOT NULL,
    document_id cragkit_qdrant.identity_text NOT NULL,
    revision_id cragkit_qdrant.identity_text NOT NULL,
    generation_id cragkit_qdrant.identity_text NOT NULL,
    chunk_id cragkit_qdrant.identity_text NOT NULL,
    source_sha256 cragkit_qdrant.sha256_hex NOT NULL,
    text_sha256 cragkit_qdrant.sha256_hex NOT NULL,
    start_byte cragkit_qdrant.safe_count NOT NULL,
    end_byte cragkit_qdrant.safe_count NOT NULL CHECK (end_byte > start_byte AND end_byte - start_byte <= 32768),
    dense_profile jsonb NOT NULL,
    sparse_profile jsonb,
    dense_input_sha256 cragkit_qdrant.sha256_hex NOT NULL,
    sparse_input_sha256 cragkit_qdrant.sha256_hex,
    PRIMARY KEY (backend_namespace, physical_collection, collection_incarnation, point_id),
    UNIQUE (tenant_id, collection, document_id, revision_id, generation_id, chunk_id,
        backend_namespace, physical_collection, collection_incarnation, point_id),
    FOREIGN KEY (tenant_id, collection, document_id) REFERENCES cragkit_qdrant.documents,
    CHECK ((sparse_profile IS NULL) = (sparse_input_sha256 IS NULL))
);

CREATE TABLE cragkit_qdrant.vector_replays (
    tenant_id cragkit_qdrant.identity_text NOT NULL,
    collection cragkit_qdrant.collection_text NOT NULL,
    document_id cragkit_qdrant.identity_text NOT NULL,
    revision_id cragkit_qdrant.identity_text NOT NULL,
    generation_id cragkit_qdrant.identity_text NOT NULL,
    chunk_id cragkit_qdrant.identity_text NOT NULL,
    backend_namespace cragkit_qdrant.identity_text NOT NULL,
    physical_collection text COLLATE pg_catalog."C" NOT NULL,
    collection_incarnation cragkit_qdrant.identity_text NOT NULL,
    point_id uuid NOT NULL,
    dense_blob bytea NOT NULL CHECK (octet_length(dense_blob) = 12326),
    dense_blob_sha256 cragkit_qdrant.sha256_hex NOT NULL CHECK (dense_blob_sha256 = encode(sha256(dense_blob), 'hex')),
    sparse_blob bytea CHECK (octet_length(sparse_blob) BETWEEN 51 AND 231),
    sparse_blob_sha256 cragkit_qdrant.sha256_hex,
    PRIMARY KEY (tenant_id, collection, document_id, revision_id, generation_id, chunk_id),
    FOREIGN KEY (tenant_id, collection, document_id, revision_id, generation_id, chunk_id,
        backend_namespace, physical_collection, collection_incarnation, point_id)
        REFERENCES cragkit_qdrant.point_claims (tenant_id, collection, document_id, revision_id,
            generation_id, chunk_id, backend_namespace, physical_collection, collection_incarnation, point_id),
    CHECK ((sparse_blob IS NULL) = (sparse_blob_sha256 IS NULL)),
    CHECK (sparse_blob IS NULL OR sparse_blob_sha256 = encode(sha256(sparse_blob), 'hex'))
);

CREATE TABLE cragkit_qdrant.dispatch_journal (
    tenant_id cragkit_qdrant.identity_text NOT NULL,
    collection cragkit_qdrant.collection_text NOT NULL,
    document_id cragkit_qdrant.identity_text NOT NULL,
    intent_id cragkit_qdrant.identity_text NOT NULL,
    dispatch_id cragkit_qdrant.identity_text NOT NULL,
    instance_id cragkit_qdrant.identity_text NOT NULL REFERENCES cragkit_qdrant.backend_instances,
    sequence integer NOT NULL CHECK (sequence BETWEEN 1 AND 256),
    owner_token uuid NOT NULL,
    backend_epoch cragkit_qdrant.safe_count NOT NULL,
    credential_generation cragkit_qdrant.identity_text NOT NULL,
    operation text COLLATE pg_catalog."C" NOT NULL CHECK (operation IN ('complete_point_upsert', 'delete_points')),
    recovery boolean NOT NULL DEFAULT false,
    request_bytes bytea NOT NULL CHECK (octet_length(request_bytes) BETWEEN 1 AND 1048576),
    request_sha256 cragkit_qdrant.sha256_hex NOT NULL CHECK (request_sha256 = encode(sha256(request_bytes), 'hex')),
    state text COLLATE pg_catalog."C" NOT NULL DEFAULT 'reserved' CHECK (state IN ('reserved', 'dispatched', 'settled', 'unknown')),
    completion_sha256 cragkit_qdrant.sha256_hex,
    created_xid xid8 NOT NULL DEFAULT pg_current_xact_id(),
    PRIMARY KEY (tenant_id, collection, document_id, intent_id, dispatch_id),
    UNIQUE (tenant_id, collection, document_id, intent_id, sequence),
    FOREIGN KEY (tenant_id, collection, document_id, intent_id) REFERENCES cragkit_qdrant.publication_intents,
    CHECK ((state = 'settled') = (completion_sha256 IS NOT NULL))
);

CREATE TABLE cragkit_qdrant.dispatch_points (
    tenant_id cragkit_qdrant.identity_text NOT NULL,
    collection cragkit_qdrant.collection_text NOT NULL,
    document_id cragkit_qdrant.identity_text NOT NULL,
    intent_id cragkit_qdrant.identity_text NOT NULL,
    dispatch_id cragkit_qdrant.identity_text NOT NULL,
    backend_namespace cragkit_qdrant.identity_text NOT NULL,
    physical_collection text COLLATE pg_catalog."C" NOT NULL,
    collection_incarnation cragkit_qdrant.identity_text NOT NULL,
    point_id uuid NOT NULL,
    PRIMARY KEY (tenant_id, collection, document_id, intent_id, dispatch_id, point_id),
    FOREIGN KEY (tenant_id, collection, document_id, intent_id, dispatch_id) REFERENCES cragkit_qdrant.dispatch_journal,
    FOREIGN KEY (backend_namespace, physical_collection, collection_incarnation, point_id) REFERENCES cragkit_qdrant.point_claims
);

CREATE TABLE cragkit_qdrant.preparations (
    tenant_id cragkit_qdrant.identity_text NOT NULL,
    collection cragkit_qdrant.collection_text NOT NULL,
    document_id cragkit_qdrant.identity_text NOT NULL,
    intent_id cragkit_qdrant.identity_text NOT NULL,
    instance_id cragkit_qdrant.identity_text NOT NULL REFERENCES cragkit_qdrant.backend_instances,
    owner_token uuid NOT NULL,
    backend_epoch cragkit_qdrant.safe_count NOT NULL,
    authorization_revision cragkit_qdrant.identity_text NOT NULL,
    mutation_epoch cragkit_qdrant.safe_count NOT NULL,
    manifest_sha256 cragkit_qdrant.sha256_hex NOT NULL,
    readback_sha256 cragkit_qdrant.sha256_hex NOT NULL,
    PRIMARY KEY (tenant_id, collection, document_id, intent_id),
    FOREIGN KEY (tenant_id, collection, document_id, intent_id) REFERENCES cragkit_qdrant.publication_intents
);

-- Scope functions do not query documents: intents -> scope is acyclic, and
-- content policies may then query intents without documents/intents recursion.
CREATE FUNCTION cragkit_qdrant.writer_scope(row_tenant text, row_collection text, row_document text)
RETURNS boolean LANGUAGE sql STABLE SET search_path = pg_catalog AS $function$
    SELECT current_setting('transaction_isolation') = 'read committed'
        AND row_tenant = current_setting('cragkit_qdrant.tenant_id', true)
        AND row_collection = current_setting('cragkit_qdrant.collection', true)
        AND row_document = current_setting('cragkit_qdrant.writer_document_id', true)
        AND octet_length(current_setting('cragkit_qdrant.principal_id', true)) BETWEEN 1 AND 256
        AND btrim(current_setting('cragkit_qdrant.principal_id', true), E' \t\r\n\f\013') <> ''
        AND cragkit_qdrant.scope_grants() IS NOT NULL
        AND octet_length(current_setting('cragkit_qdrant.authorization_revision', true)) BETWEEN 1 AND 256
        AND btrim(current_setting('cragkit_qdrant.authorization_revision', true), E' \t\r\n\f\013') <> ''
        AND octet_length(current_setting('cragkit_qdrant.writer_intent_id', true)) BETWEEN 1 AND 256
        AND btrim(current_setting('cragkit_qdrant.writer_intent_id', true), E' \t\r\n\f\013') <> ''
        AND octet_length(current_setting('cragkit_qdrant.backend_instance_id', true)) BETWEEN 1 AND 256
        AND btrim(current_setting('cragkit_qdrant.backend_instance_id', true), E' \t\r\n\f\013') <> ''
        AND octet_length(current_setting('cragkit_qdrant.writer_owner_token', true)) = 36
        AND current_setting('cragkit_qdrant.writer_owner_token', true)
            ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
$function$;

CREATE FUNCTION cragkit_qdrant.bound_stage(row_tenant text, row_collection text, row_document text,
    row_revision text, row_generation text) RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog AS $function$
    SELECT cragkit_qdrant.writer_scope(row_tenant, row_collection, row_document) AND EXISTS (
        SELECT 1 FROM cragkit_qdrant.publication_intents AS intent
        WHERE intent.tenant_id = row_tenant AND intent.collection = row_collection
            AND intent.document_id = row_document
            AND intent.intent_id = current_setting('cragkit_qdrant.writer_intent_id', true)
            AND intent.instance_id = current_setting('cragkit_qdrant.backend_instance_id', true)
            AND intent.action = 'stage' AND intent.revision_id = row_revision
            AND (row_generation IS NULL OR intent.generation_id = row_generation))
$function$;

CREATE FUNCTION cragkit_qdrant.supervisor_instance(row_instance text) RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog AS $function$
    SELECT current_setting('transaction_isolation') = 'read committed'
        AND row_instance = current_setting('cragkit_qdrant.backend_instance_id', true)
$function$;

-- Column grants, not RLS, keep operational supervisors away from sensitive bytes.
GRANT USAGE ON SCHEMA cragkit_qdrant TO cragkit_qdrant_writer, cragkit_qdrant_supervisor;
GRANT SELECT ON cragkit_qdrant.schema_migrations TO cragkit_qdrant_writer, cragkit_qdrant_supervisor;
GRANT EXECUTE ON FUNCTION cragkit_qdrant.valid_identity_array(text[]), cragkit_qdrant.scope_grants(),
    cragkit_qdrant.writer_scope(text,text,text), cragkit_qdrant.bound_stage(text,text,text,text,text),
    cragkit_qdrant.supervisor_instance(text) TO cragkit_qdrant_writer, cragkit_qdrant_supervisor;
GRANT EXECUTE ON FUNCTION cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean)
    TO cragkit_qdrant_writer;
GRANT SELECT, INSERT, UPDATE ON cragkit_qdrant.documents, cragkit_qdrant.generations,
    cragkit_qdrant.publication_intents, cragkit_qdrant.document_owners, cragkit_qdrant.dispatch_journal
    TO cragkit_qdrant_writer;
GRANT SELECT, INSERT ON cragkit_qdrant.document_revisions, cragkit_qdrant.members,
    cragkit_qdrant.point_claims, cragkit_qdrant.vector_replays,
    cragkit_qdrant.dispatch_points, cragkit_qdrant.preparations TO cragkit_qdrant_writer;
GRANT UPDATE(point_id) ON cragkit_qdrant.members TO cragkit_qdrant_writer;
GRANT SELECT, INSERT, UPDATE ON cragkit_qdrant.backend_instances TO cragkit_qdrant_supervisor;
-- A locking SELECT needs UPDATE privilege; the backend trigger forbids writer changes.
GRANT SELECT, UPDATE(epoch) ON cragkit_qdrant.backend_instances TO cragkit_qdrant_writer;
GRANT SELECT (tenant_id,collection,document_id,intent_id,instance_id,action,payload_sha256,
    manifest_sha256,revision_id,generation_id,expected_active_generation_id,
    expected_authorization_revision,expected_mutation_epoch,state,authority_committed,
    replica_complete,purge_complete) ON cragkit_qdrant.publication_intents TO cragkit_qdrant_supervisor;
GRANT SELECT, UPDATE(backend_epoch) ON cragkit_qdrant.document_owners TO cragkit_qdrant_supervisor;
GRANT SELECT ON cragkit_qdrant.point_claims, cragkit_qdrant.dispatch_points,
    cragkit_qdrant.preparations TO cragkit_qdrant_supervisor;
GRANT SELECT (tenant_id,collection,document_id,intent_id,dispatch_id,instance_id,sequence,
    owner_token,backend_epoch,credential_generation,operation,recovery,request_sha256,state,completion_sha256,created_xid),
    INSERT, UPDATE(state,completion_sha256) ON cragkit_qdrant.dispatch_journal TO cragkit_qdrant_supervisor;
GRANT INSERT ON cragkit_qdrant.dispatch_points TO cragkit_qdrant_supervisor;

DO $policies$
DECLARE
    table_name text;
    scoped text := 'cragkit_qdrant.writer_scope(tenant_id,collection,document_id)';
BEGIN
    FOREACH table_name IN ARRAY ARRAY['publication_intents','document_owners','point_claims',
        'vector_replays','dispatch_journal','dispatch_points','preparations'] LOOP
        EXECUTE format('ALTER TABLE cragkit_qdrant.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE cragkit_qdrant.%I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format('CREATE POLICY writer_read ON cragkit_qdrant.%I FOR SELECT TO cragkit_qdrant_writer USING (%s)', table_name, scoped);
        EXECUTE format('CREATE POLICY writer_insert ON cragkit_qdrant.%I FOR INSERT TO cragkit_qdrant_writer WITH CHECK (%s)', table_name, scoped);
        IF table_name IN ('publication_intents','document_owners','dispatch_journal') THEN
            EXECUTE format('CREATE POLICY writer_update ON cragkit_qdrant.%I FOR UPDATE TO cragkit_qdrant_writer USING (%s) WITH CHECK (%s)', table_name, scoped, scoped);
        END IF;
        IF table_name NOT IN ('vector_replays', 'dispatch_points') THEN
            EXECUTE format('CREATE POLICY supervisor_read ON cragkit_qdrant.%I FOR SELECT TO cragkit_qdrant_supervisor USING (cragkit_qdrant.supervisor_instance(instance_id))', table_name);
        END IF;
    END LOOP;
END
$policies$;

-- dispatch_points has no independent instance: bind it through its journal.
CREATE POLICY supervisor_read ON cragkit_qdrant.dispatch_points FOR SELECT TO cragkit_qdrant_supervisor
    USING (EXISTS (SELECT 1 FROM cragkit_qdrant.dispatch_journal AS journal
        WHERE journal.tenant_id = dispatch_points.tenant_id AND journal.collection = dispatch_points.collection
            AND journal.document_id = dispatch_points.document_id AND journal.intent_id = dispatch_points.intent_id
            AND journal.dispatch_id = dispatch_points.dispatch_id));
ALTER TABLE cragkit_qdrant.backend_instances ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit_qdrant.backend_instances FORCE ROW LEVEL SECURITY;
CREATE POLICY supervisor_control ON cragkit_qdrant.backend_instances FOR ALL TO cragkit_qdrant_supervisor
    USING (cragkit_qdrant.supervisor_instance(instance_id)) WITH CHECK (cragkit_qdrant.supervisor_instance(instance_id));
CREATE POLICY writer_instance_read ON cragkit_qdrant.backend_instances FOR SELECT TO cragkit_qdrant_writer
    USING (instance_id = current_setting('cragkit_qdrant.backend_instance_id', true));
CREATE POLICY writer_instance_lock ON cragkit_qdrant.backend_instances FOR UPDATE TO cragkit_qdrant_writer
    USING (instance_id = current_setting('cragkit_qdrant.backend_instance_id', true))
    WITH CHECK (instance_id = current_setting('cragkit_qdrant.backend_instance_id', true));
CREATE POLICY supervisor_owner_epoch ON cragkit_qdrant.document_owners FOR UPDATE TO cragkit_qdrant_supervisor
    USING (cragkit_qdrant.supervisor_instance(instance_id)) WITH CHECK (cragkit_qdrant.supervisor_instance(instance_id));
CREATE POLICY supervisor_dispatch_insert ON cragkit_qdrant.dispatch_journal FOR INSERT TO cragkit_qdrant_supervisor
    WITH CHECK (cragkit_qdrant.supervisor_instance(instance_id) AND recovery);
CREATE POLICY supervisor_dispatch_update ON cragkit_qdrant.dispatch_journal FOR UPDATE TO cragkit_qdrant_supervisor
    USING (cragkit_qdrant.supervisor_instance(instance_id)) WITH CHECK (cragkit_qdrant.supervisor_instance(instance_id));
CREATE POLICY supervisor_point_insert ON cragkit_qdrant.dispatch_points FOR INSERT TO cragkit_qdrant_supervisor
    WITH CHECK (EXISTS (SELECT 1 FROM cragkit_qdrant.dispatch_journal AS journal
        WHERE journal.tenant_id = dispatch_points.tenant_id AND journal.collection = dispatch_points.collection
            AND journal.document_id = dispatch_points.document_id AND journal.intent_id = dispatch_points.intent_id
            AND journal.dispatch_id = dispatch_points.dispatch_id AND journal.recovery));

CREATE POLICY writer_document_read ON cragkit_qdrant.documents FOR SELECT TO cragkit_qdrant_writer
    USING (cragkit_qdrant.writer_scope(tenant_id,collection,document_id));
CREATE POLICY writer_document_bound ON cragkit_qdrant.documents AS RESTRICTIVE FOR SELECT TO cragkit_qdrant_writer
    USING (cragkit_qdrant.writer_scope(tenant_id,collection,document_id));
CREATE POLICY writer_document_insert ON cragkit_qdrant.documents FOR INSERT TO cragkit_qdrant_writer
    WITH CHECK (cragkit_qdrant.writer_scope(tenant_id,collection,document_id));
CREATE POLICY writer_document_update ON cragkit_qdrant.documents FOR UPDATE TO cragkit_qdrant_writer
    USING (cragkit_qdrant.writer_scope(tenant_id,collection,document_id))
    WITH CHECK (cragkit_qdrant.writer_scope(tenant_id,collection,document_id));
CREATE POLICY writer_revision_read ON cragkit_qdrant.document_revisions FOR SELECT TO cragkit_qdrant_writer
    USING (cragkit_qdrant.bound_stage(tenant_id,collection,document_id,revision_id,NULL));
CREATE POLICY writer_revision_bound ON cragkit_qdrant.document_revisions AS RESTRICTIVE FOR SELECT TO cragkit_qdrant_writer
    USING (cragkit_qdrant.bound_stage(tenant_id,collection,document_id,revision_id,NULL));
CREATE POLICY writer_revision_insert ON cragkit_qdrant.document_revisions FOR INSERT TO cragkit_qdrant_writer
    WITH CHECK (cragkit_qdrant.bound_stage(tenant_id,collection,document_id,revision_id,NULL));
CREATE POLICY writer_generation_read ON cragkit_qdrant.generations FOR SELECT TO cragkit_qdrant_writer
    USING ((ever_published AND cragkit_qdrant.writer_scope(tenant_id,collection,document_id))
        OR cragkit_qdrant.bound_stage(tenant_id,collection,document_id,revision_id,generation_id));
CREATE POLICY writer_generation_bound ON cragkit_qdrant.generations AS RESTRICTIVE FOR SELECT TO cragkit_qdrant_writer
    USING ((ever_published AND cragkit_qdrant.writer_scope(tenant_id,collection,document_id))
        OR cragkit_qdrant.bound_stage(tenant_id,collection,document_id,revision_id,generation_id));
CREATE POLICY writer_generation_insert ON cragkit_qdrant.generations FOR INSERT TO cragkit_qdrant_writer
    WITH CHECK (NOT published AND NOT ever_published
        AND cragkit_qdrant.bound_stage(tenant_id,collection,document_id,revision_id,generation_id));
CREATE POLICY writer_generation_update ON cragkit_qdrant.generations FOR UPDATE TO cragkit_qdrant_writer
    USING (cragkit_qdrant.writer_scope(tenant_id,collection,document_id))
    WITH CHECK (cragkit_qdrant.writer_scope(tenant_id,collection,document_id));
CREATE POLICY writer_member_read ON cragkit_qdrant.members FOR SELECT TO cragkit_qdrant_writer
    USING (cragkit_qdrant.bound_stage(tenant_id,collection,document_id,revision_id,generation_id));
CREATE POLICY writer_member_bound ON cragkit_qdrant.members AS RESTRICTIVE FOR SELECT TO cragkit_qdrant_writer
    USING (cragkit_qdrant.bound_stage(tenant_id,collection,document_id,revision_id,generation_id));
CREATE POLICY writer_member_insert ON cragkit_qdrant.members FOR INSERT TO cragkit_qdrant_writer
    WITH CHECK (cragkit_qdrant.bound_stage(tenant_id,collection,document_id,revision_id,generation_id));
CREATE POLICY writer_member_lock ON cragkit_qdrant.members FOR UPDATE TO cragkit_qdrant_writer
    USING (cragkit_qdrant.bound_stage(tenant_id,collection,document_id,revision_id,generation_id))
    WITH CHECK (cragkit_qdrant.bound_stage(tenant_id,collection,document_id,revision_id,generation_id));

REVOKE ALL ON cragkit_qdrant.backend_instances, cragkit_qdrant.publication_intents,
    cragkit_qdrant.document_owners, cragkit_qdrant.point_claims, cragkit_qdrant.vector_replays,
    cragkit_qdrant.dispatch_journal, cragkit_qdrant.dispatch_points, cragkit_qdrant.preparations FROM PUBLIC;
REVOKE ALL ON FUNCTION cragkit_qdrant.writer_scope(text,text,text), cragkit_qdrant.bound_stage(text,text,text,text,text),
    cragkit_qdrant.supervisor_instance(text) FROM PUBLIC;

CREATE FUNCTION cragkit_qdrant.lock_publication_owner(row_tenant text, row_collection text,
    row_document text, row_instance text, row_token uuid, row_epoch bigint, recovering boolean)
RETURNS void LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
DECLARE
    backend record;
    owner_row record;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'managed writes require read committed' USING ERRCODE = '23514';
    END IF;
    -- Lock first, then read in separate statements after any lock wait. All
    -- competing admissions use this same backend -> owner order.
    PERFORM 1 FROM cragkit_qdrant.backend_instances WHERE instance_id = row_instance FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'publication instance absent' USING ERRCODE = '23514'; END IF;
    PERFORM 1 FROM cragkit_qdrant.document_owners WHERE tenant_id = row_tenant
        AND collection = row_collection AND document_id = row_document FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'publication owner absent' USING ERRCODE = '23514'; END IF;
    SELECT epoch, state INTO backend FROM cragkit_qdrant.backend_instances WHERE instance_id = row_instance;
    SELECT instance_id, owner_token, backend_epoch, intent_id INTO owner_row
    FROM cragkit_qdrant.document_owners WHERE tenant_id = row_tenant
        AND collection = row_collection AND document_id = row_document;
    IF owner_row.instance_id IS DISTINCT FROM row_instance OR owner_row.owner_token IS DISTINCT FROM row_token
        OR backend.epoch IS DISTINCT FROM row_epoch THEN
        RAISE EXCEPTION 'stale publication owner or epoch' USING ERRCODE = '23514';
    END IF;
    IF recovering THEN
        IF NOT pg_has_role(current_user, 'cragkit_qdrant_supervisor', 'MEMBER')
            OR backend.state <> 'recovery_blocked' THEN
            RAISE EXCEPTION 'recovery capability required' USING ERRCODE = '23514';
        END IF;
    ELSIF backend.state <> 'open' OR owner_row.backend_epoch IS DISTINCT FROM row_epoch THEN
        RAISE EXCEPTION 'publication instance blocked' USING ERRCODE = '23514';
    END IF;
END
$function$;
REVOKE ALL ON FUNCTION cragkit_qdrant.lock_publication_owner(text,text,text,text,uuid,bigint,boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cragkit_qdrant.lock_publication_owner(text,text,text,text,uuid,bigint,boolean)
    TO cragkit_qdrant_writer, cragkit_qdrant_supervisor;

CREATE FUNCTION cragkit_qdrant.guard_backend_instance() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'managed writes require read committed' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' OR NOT pg_has_role(current_user, 'cragkit_qdrant_supervisor', 'MEMBER') THEN
        RAISE EXCEPTION 'exclusive supervisor required' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.epoch <> 1 OR NEW.state <> 'open' THEN
            RAISE EXCEPTION 'invalid initial instance' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF ROW(NEW.instance_id,NEW.backend_namespace,NEW.storage_identity,NEW.supervisor_id)
        IS DISTINCT FROM ROW(OLD.instance_id,OLD.backend_namespace,OLD.storage_identity,OLD.supervisor_id) THEN
        RAISE EXCEPTION 'immutable instance identity' USING ERRCODE = '23514';
    END IF;
    IF OLD.state = 'open' AND NEW.state = 'recovery_blocked' THEN
        IF NEW.epoch <> OLD.epoch + 1 THEN
            RAISE EXCEPTION 'recovery must advance epoch' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.epoch <> OLD.epoch OR (OLD.state = 'recovery_blocked'
        AND NEW.state = 'recovery_blocked' AND NEW.recovery_id IS DISTINCT FROM OLD.recovery_id) THEN
        RAISE EXCEPTION 'invalid recovery transition' USING ERRCODE = '23514';
    END IF;
    IF OLD.state = 'recovery_blocked' AND NEW.state = 'open' AND EXISTS (
        SELECT 1 FROM cragkit_qdrant.dispatch_journal
        WHERE instance_id = OLD.instance_id AND state <> 'settled') THEN
        RAISE EXCEPTION 'instance has unresolved dispatch' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER publication_backend_guard BEFORE INSERT OR UPDATE OR DELETE ON cragkit_qdrant.backend_instances
    FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.guard_backend_instance();

CREATE FUNCTION cragkit_qdrant.guard_publication_intent() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'managed writes require read committed' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'durable publication intent' USING ERRCODE = '23514';
    END IF;
    IF NEW.intent_id IS DISTINCT FROM current_setting('cragkit_qdrant.writer_intent_id', true)
        OR NEW.instance_id IS DISTINCT FROM current_setting('cragkit_qdrant.backend_instance_id', true) THEN
        RAISE EXCEPTION 'intent context mismatch' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.state <> 'staged' OR NEW.authority_committed OR NEW.replica_complete OR NEW.purge_complete THEN
            RAISE EXCEPTION 'invalid initial intent state' USING ERRCODE = '23514';
        END IF;
    ELSE
        IF (to_jsonb(NEW) - ARRAY['state','authority_committed','replica_complete','purge_complete'])
            IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['state','authority_committed','replica_complete','purge_complete'])
            OR (OLD.authority_committed AND NOT NEW.authority_committed)
            OR (OLD.replica_complete AND NOT NEW.replica_complete) OR (OLD.purge_complete AND NOT NEW.purge_complete)
            OR (OLD.state IN ('published','complete','conflict','denied') AND NEW IS DISTINCT FROM OLD)
            OR (NEW.state IS DISTINCT FROM OLD.state AND NOT (
                (OLD.state = 'staged' AND NEW.state IN ('writing','authority_committed','conflict','denied'))
                OR (OLD.state = 'writing' AND NEW.state IN ('prepared','authority_committed','complete','conflict','denied'))
                OR (OLD.state = 'prepared' AND NEW.state IN ('published','conflict','denied'))
                OR (OLD.state = 'authority_committed' AND NEW.state IN ('writing','complete')))) THEN
            RAISE EXCEPTION 'immutable intent or invalid transition' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF (NEW.action = 'stage' AND NEW.state IN ('authority_committed','complete'))
        OR (NEW.action <> 'stage' AND NEW.state IN ('prepared','published'))
        OR (NEW.state = 'published' AND NOT (NEW.authority_committed AND NEW.replica_complete))
        OR (NEW.state = 'complete' AND NOT (NEW.authority_committed AND NEW.replica_complete)) THEN
        RAISE EXCEPTION 'intent action outcome mismatch' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER publication_intent_guard BEFORE INSERT OR UPDATE OR DELETE ON cragkit_qdrant.publication_intents
    FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.guard_publication_intent();

CREATE FUNCTION cragkit_qdrant.guard_document_owner() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
DECLARE
    backend record;
    recovering boolean;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'managed writes require read committed' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'durable document owner' USING ERRCODE = '23514'; END IF;
    PERFORM 1 FROM cragkit_qdrant.backend_instances WHERE instance_id = NEW.instance_id FOR SHARE;
    SELECT epoch,state INTO backend FROM cragkit_qdrant.backend_instances WHERE instance_id = NEW.instance_id;
    IF NOT FOUND OR NEW.backend_epoch IS DISTINCT FROM backend.epoch THEN
        RAISE EXCEPTION 'invalid owner instance epoch' USING ERRCODE = '23514';
    END IF;
    recovering := pg_has_role(current_user, 'cragkit_qdrant_supervisor', 'MEMBER') AND backend.state = 'recovery_blocked';
    IF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.tenant_id,NEW.collection,NEW.document_id,NEW.instance_id)
            IS DISTINCT FROM ROW(OLD.tenant_id,OLD.collection,OLD.document_id,OLD.instance_id) THEN
            RAISE EXCEPTION 'immutable owner target' USING ERRCODE = '23514';
        END IF;
        IF recovering AND ROW(NEW.owner_token,NEW.intent_id) IS NOT DISTINCT FROM ROW(OLD.owner_token,OLD.intent_id) THEN
            RETURN NEW;
        END IF;
        IF EXISTS (SELECT 1 FROM cragkit_qdrant.dispatch_journal WHERE tenant_id = OLD.tenant_id
            AND collection = OLD.collection AND document_id = OLD.document_id AND state <> 'settled') THEN
            RAISE EXCEPTION 'unresolved predecessor dispatch' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF backend.state <> 'open' OR NEW.owner_token::text IS DISTINCT FROM current_setting('cragkit_qdrant.writer_owner_token',true)
        OR NEW.intent_id IS DISTINCT FROM current_setting('cragkit_qdrant.writer_intent_id',true) THEN
        RAISE EXCEPTION 'owner context or admission blocked' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM cragkit_qdrant.publication_intents WHERE tenant_id = NEW.tenant_id
        AND collection = NEW.collection AND document_id = NEW.document_id AND intent_id = NEW.intent_id
        AND instance_id = NEW.instance_id AND state NOT IN ('published','complete','denied','conflict')) THEN
        RAISE EXCEPTION 'owner intent mismatch' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER publication_owner_guard BEFORE INSERT OR UPDATE OR DELETE ON cragkit_qdrant.document_owners
    FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.guard_document_owner();

CREATE FUNCTION cragkit_qdrant.guard_point_claim() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
DECLARE
    member_row record;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'managed writes require read committed' USING ERRCODE = '23514';
    END IF;
    IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'immutable physical claim' USING ERRCODE = '23514'; END IF;
    SELECT member.point_id, member.source_sha256, member.text_sha256, member.start_byte, member.end_byte,
        generation.backend_namespace,generation.physical_collection,generation.collection_incarnation,
        generation.dense_profile,generation.sparse_profile INTO member_row
    FROM cragkit_qdrant.members AS member JOIN cragkit_qdrant.generations AS generation
        USING (tenant_id,collection,document_id,revision_id,generation_id)
    WHERE member.tenant_id = NEW.tenant_id AND member.collection = NEW.collection
        AND member.document_id = NEW.document_id AND member.revision_id = NEW.revision_id
        AND member.generation_id = NEW.generation_id AND member.chunk_id = NEW.chunk_id FOR KEY SHARE OF member,generation;
    IF NOT FOUND OR ROW(NEW.point_id,NEW.source_sha256,NEW.text_sha256,NEW.start_byte,NEW.end_byte,
        NEW.backend_namespace,NEW.physical_collection,NEW.collection_incarnation,NEW.dense_profile,NEW.sparse_profile)
        IS DISTINCT FROM ROW(member_row.point_id,member_row.source_sha256,member_row.text_sha256,
        member_row.start_byte,member_row.end_byte,member_row.backend_namespace,member_row.physical_collection,
        member_row.collection_incarnation,member_row.dense_profile,member_row.sparse_profile)
        OR NOT cragkit_qdrant.bound_stage(NEW.tenant_id,NEW.collection,NEW.document_id,NEW.revision_id,NEW.generation_id)
        OR NOT EXISTS (SELECT 1 FROM cragkit_qdrant.backend_instances WHERE instance_id = NEW.instance_id
            AND backend_namespace = NEW.backend_namespace) THEN
        RAISE EXCEPTION 'physical claim owner mismatch' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER physical_claim_guard BEFORE INSERT OR UPDATE OR DELETE ON cragkit_qdrant.point_claims
    FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.guard_point_claim();

CREATE FUNCTION cragkit_qdrant.guard_vector_replay() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
DECLARE
    absent_sparse boolean;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'managed writes require read committed' USING ERRCODE = '23514';
    END IF;
    IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'immutable vector replay' USING ERRCODE = '23514'; END IF;
    SELECT sparse_profile IS NULL INTO absent_sparse FROM cragkit_qdrant.point_claims
    WHERE backend_namespace = NEW.backend_namespace AND physical_collection = NEW.physical_collection
        AND collection_incarnation = NEW.collection_incarnation AND point_id = NEW.point_id
        AND tenant_id = NEW.tenant_id AND collection = NEW.collection AND document_id = NEW.document_id
        AND revision_id = NEW.revision_id AND generation_id = NEW.generation_id AND chunk_id = NEW.chunk_id;
    IF NOT FOUND OR absent_sparse IS DISTINCT FROM (NEW.sparse_blob IS NULL)
        OR NOT cragkit_qdrant.bound_stage(NEW.tenant_id,NEW.collection,NEW.document_id,NEW.revision_id,NEW.generation_id) THEN
        RAISE EXCEPTION 'vector replay claim mismatch' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER vector_replay_guard BEFORE INSERT OR UPDATE OR DELETE ON cragkit_qdrant.vector_replays
    FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.guard_vector_replay();

CREATE FUNCTION cragkit_qdrant.guard_dispatch() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
DECLARE
    owner_intent text;
    intent_state text;
    control_epoch bigint;
    recovering_settlement boolean := false;
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'durable dispatch journal' USING ERRCODE = '23514'; END IF;
    IF TG_OP = 'UPDATE' AND pg_has_role(current_user,'cragkit_qdrant_supervisor','MEMBER') THEN
        SELECT epoch, state = 'recovery_blocked' INTO control_epoch, recovering_settlement
        FROM cragkit_qdrant.backend_instances WHERE instance_id = NEW.instance_id;
    END IF;
    PERFORM cragkit_qdrant.lock_publication_owner(NEW.tenant_id,NEW.collection,NEW.document_id,
        NEW.instance_id,NEW.owner_token,CASE WHEN recovering_settlement THEN control_epoch ELSE NEW.backend_epoch END,
        NEW.recovery OR recovering_settlement);
    SELECT intent_id INTO owner_intent FROM cragkit_qdrant.document_owners WHERE tenant_id = NEW.tenant_id
        AND collection = NEW.collection AND document_id = NEW.document_id;
    IF owner_intent IS DISTINCT FROM NEW.intent_id THEN
        RAISE EXCEPTION 'dispatch owner intent mismatch' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        SELECT state INTO intent_state FROM cragkit_qdrant.publication_intents WHERE tenant_id = NEW.tenant_id
            AND collection = NEW.collection AND document_id = NEW.document_id AND intent_id = NEW.intent_id;
        IF NEW.state <> 'reserved' OR NEW.created_xid IS DISTINCT FROM pg_current_xact_id()
            OR (NOT NEW.recovery AND intent_state <> 'writing')
            OR (NOT NEW.recovery AND (NEW.owner_token::text IS DISTINCT FROM current_setting('cragkit_qdrant.writer_owner_token',true)
                OR NEW.intent_id IS DISTINCT FROM current_setting('cragkit_qdrant.writer_intent_id',true)))
            OR (NOT NEW.recovery AND EXISTS (SELECT 1 FROM cragkit_qdrant.dispatch_journal
                WHERE tenant_id = NEW.tenant_id AND collection = NEW.collection
                    AND document_id = NEW.document_id AND state <> 'settled')) THEN
            RAISE EXCEPTION 'dispatch admission rejected' USING ERRCODE = '23514';
        END IF;
    ELSE
        IF (to_jsonb(NEW) - ARRAY['state','completion_sha256'])
            IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['state','completion_sha256'])
            OR (OLD.state = 'settled' AND NEW IS DISTINCT FROM OLD)
            OR (NEW.state IS DISTINCT FROM OLD.state AND NOT (
                (OLD.state = 'reserved' AND NEW.state IN ('dispatched','unknown','settled'))
                OR (OLD.state = 'dispatched' AND NEW.state IN ('unknown','settled'))
                OR (OLD.state = 'unknown' AND NEW.state = 'settled'
                    AND pg_has_role(current_user,'cragkit_qdrant_supervisor','MEMBER')))) THEN
            RAISE EXCEPTION 'immutable dispatch or invalid settlement' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER publication_dispatch_guard BEFORE INSERT OR UPDATE OR DELETE ON cragkit_qdrant.dispatch_journal
    FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.guard_dispatch();

CREATE FUNCTION cragkit_qdrant.guard_dispatch_point() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
DECLARE
    journal record;
BEGIN
    IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'immutable dispatch point' USING ERRCODE = '23514'; END IF;
    SELECT instance_id,owner_token,backend_epoch,recovery,state,created_xid INTO journal
    FROM cragkit_qdrant.dispatch_journal WHERE tenant_id = NEW.tenant_id AND collection = NEW.collection
        AND document_id = NEW.document_id AND intent_id = NEW.intent_id AND dispatch_id = NEW.dispatch_id FOR UPDATE;
    IF NOT FOUND OR journal.state <> 'reserved' OR journal.created_xid IS DISTINCT FROM pg_current_xact_id() OR NOT EXISTS (
        SELECT 1 FROM cragkit_qdrant.point_claims WHERE backend_namespace = NEW.backend_namespace
            AND physical_collection = NEW.physical_collection AND collection_incarnation = NEW.collection_incarnation
            AND point_id = NEW.point_id AND tenant_id = NEW.tenant_id AND collection = NEW.collection
            AND document_id = NEW.document_id AND instance_id = journal.instance_id) THEN
        RAISE EXCEPTION 'dispatch point owner mismatch' USING ERRCODE = '23514';
    END IF;
    IF (SELECT count(*) FROM cragkit_qdrant.dispatch_points WHERE tenant_id = NEW.tenant_id
        AND collection = NEW.collection AND document_id = NEW.document_id AND intent_id = NEW.intent_id
        AND dispatch_id = NEW.dispatch_id) >= 8 THEN
        RAISE EXCEPTION 'dispatch point bound exceeded' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER publication_dispatch_point_guard BEFORE INSERT OR UPDATE OR DELETE ON cragkit_qdrant.dispatch_points
    FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.guard_dispatch_point();

CREATE FUNCTION cragkit_qdrant.guard_preparation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
DECLARE
    document_row record;
    intent_row record;
    expected_count integer;
BEGIN
    IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'immutable preparation' USING ERRCODE = '23514'; END IF;
    PERFORM cragkit_qdrant.lock_publication_owner(NEW.tenant_id,NEW.collection,NEW.document_id,
        NEW.instance_id,NEW.owner_token,NEW.backend_epoch,false);
    SELECT intent_id INTO intent_row FROM cragkit_qdrant.document_owners WHERE tenant_id = NEW.tenant_id
        AND collection = NEW.collection AND document_id = NEW.document_id;
    IF intent_row.intent_id IS DISTINCT FROM NEW.intent_id
        OR NEW.owner_token::text IS DISTINCT FROM current_setting('cragkit_qdrant.writer_owner_token',true) THEN
        RAISE EXCEPTION 'preparation owner context mismatch' USING ERRCODE = '23514';
    END IF;
    SELECT active_generation_id,authorization_revision,mutation_epoch,tombstoned INTO document_row
    FROM cragkit_qdrant.documents WHERE tenant_id = NEW.tenant_id AND collection = NEW.collection
        AND document_id = NEW.document_id;
    SELECT action,state,manifest_sha256,expected_active_generation_id,expected_authorization_revision,
        expected_mutation_epoch,revision_id,generation_id INTO intent_row
    FROM cragkit_qdrant.publication_intents WHERE tenant_id = NEW.tenant_id AND collection = NEW.collection
        AND document_id = NEW.document_id AND intent_id = NEW.intent_id;
    IF NOT FOUND OR intent_row.action <> 'stage' OR intent_row.state <> 'writing'
        OR document_row.tombstoned OR NEW.manifest_sha256 IS DISTINCT FROM intent_row.manifest_sha256
        OR ROW(document_row.active_generation_id,document_row.authorization_revision,document_row.mutation_epoch)
            IS DISTINCT FROM ROW(intent_row.expected_active_generation_id,intent_row.expected_authorization_revision,intent_row.expected_mutation_epoch)
        OR ROW(NEW.authorization_revision,NEW.mutation_epoch)
            IS DISTINCT FROM ROW(document_row.authorization_revision,document_row.mutation_epoch)
        OR EXISTS (SELECT 1 FROM cragkit_qdrant.dispatch_journal WHERE tenant_id = NEW.tenant_id
            AND collection = NEW.collection AND document_id = NEW.document_id AND state <> 'settled') THEN
        RAISE EXCEPTION 'preparation intent or security fence mismatch' USING ERRCODE = '23514';
    END IF;
    SELECT expected_member_count INTO expected_count FROM cragkit_qdrant.generations
    WHERE tenant_id = NEW.tenant_id AND collection = NEW.collection AND document_id = NEW.document_id
        AND revision_id = intent_row.revision_id AND generation_id = intent_row.generation_id;
    IF NOT FOUND OR expected_count <> (SELECT count(*) FROM cragkit_qdrant.members
        WHERE tenant_id = NEW.tenant_id AND collection = NEW.collection AND document_id = NEW.document_id
            AND revision_id = intent_row.revision_id AND generation_id = intent_row.generation_id)
        OR expected_count <> (SELECT count(*) FROM cragkit_qdrant.point_claims
            WHERE tenant_id = NEW.tenant_id AND collection = NEW.collection AND document_id = NEW.document_id
                AND revision_id = intent_row.revision_id AND generation_id = intent_row.generation_id)
        OR expected_count <> (SELECT count(*) FROM cragkit_qdrant.vector_replays
            WHERE tenant_id = NEW.tenant_id AND collection = NEW.collection AND document_id = NEW.document_id
                AND revision_id = intent_row.revision_id AND generation_id = intent_row.generation_id) THEN
        RAISE EXCEPTION 'incomplete preparation membership' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER publication_preparation_guard BEFORE INSERT OR UPDATE OR DELETE ON cragkit_qdrant.preparations
    FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.guard_preparation();

CREATE FUNCTION cragkit_qdrant.assert_publication(row_tenant text,row_collection text,row_document text,
    prior_active text) RETURNS void LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
DECLARE
    owner_row record;
    document_row record;
    intent_row record;
    prepared record;
BEGIN
    SELECT instance_id,owner_token,backend_epoch,intent_id INTO owner_row FROM cragkit_qdrant.document_owners
    WHERE tenant_id = row_tenant AND collection = row_collection AND document_id = row_document;
    IF NOT FOUND THEN RAISE EXCEPTION 'publication owner absent' USING ERRCODE = '23514'; END IF;
    PERFORM cragkit_qdrant.lock_publication_owner(row_tenant,row_collection,row_document,
        owner_row.instance_id,owner_row.owner_token,owner_row.backend_epoch,false);
    -- Fresh reads follow both locks; the first owner lookup only locates keys.
    SELECT instance_id,owner_token,backend_epoch,intent_id INTO owner_row FROM cragkit_qdrant.document_owners
    WHERE tenant_id = row_tenant AND collection = row_collection AND document_id = row_document;
    SELECT active_generation_id,authorization_revision,mutation_epoch,tombstoned INTO document_row
    FROM cragkit_qdrant.documents WHERE tenant_id = row_tenant AND collection = row_collection AND document_id = row_document;
    SELECT intent_id,action,state,manifest_sha256,expected_active_generation_id,expected_authorization_revision,
        expected_mutation_epoch,generation_id,authority_committed,replica_complete,instance_id INTO intent_row
    FROM cragkit_qdrant.publication_intents WHERE tenant_id = row_tenant AND collection = row_collection
        AND document_id = row_document AND intent_id = owner_row.intent_id;
    SELECT owner_token,backend_epoch,authorization_revision,mutation_epoch,manifest_sha256,instance_id INTO prepared
    FROM cragkit_qdrant.preparations WHERE tenant_id = row_tenant AND collection = row_collection
        AND document_id = row_document AND intent_id = owner_row.intent_id;
    IF NOT FOUND OR intent_row.action <> 'stage' OR intent_row.state <> 'published'
        OR NOT intent_row.authority_committed OR NOT intent_row.replica_complete OR document_row.tombstoned
        OR intent_row.expected_active_generation_id IS DISTINCT FROM prior_active
        OR intent_row.generation_id IS DISTINCT FROM document_row.active_generation_id
        OR owner_row.intent_id IS DISTINCT FROM current_setting('cragkit_qdrant.writer_intent_id',true)
        OR owner_row.owner_token::text IS DISTINCT FROM current_setting('cragkit_qdrant.writer_owner_token',true)
        OR ROW(prepared.owner_token,prepared.backend_epoch,prepared.instance_id,prepared.manifest_sha256,
            prepared.authorization_revision,prepared.mutation_epoch)
            IS DISTINCT FROM ROW(owner_row.owner_token,owner_row.backend_epoch,owner_row.instance_id,
                intent_row.manifest_sha256,document_row.authorization_revision,document_row.mutation_epoch)
        OR ROW(intent_row.expected_authorization_revision,intent_row.expected_mutation_epoch)
            IS DISTINCT FROM ROW(document_row.authorization_revision,document_row.mutation_epoch)
        OR EXISTS (SELECT 1 FROM cragkit_qdrant.dispatch_journal WHERE tenant_id = row_tenant
            AND collection = row_collection AND document_id = row_document AND state <> 'settled')
        OR NOT EXISTS (SELECT 1 FROM cragkit_qdrant.generations WHERE tenant_id = row_tenant
            AND collection = row_collection AND document_id = row_document
            AND generation_id = intent_row.generation_id AND published AND ever_published)
        OR EXISTS (SELECT 1 FROM cragkit_qdrant.generations WHERE tenant_id = row_tenant
            AND collection = row_collection AND document_id = row_document
            AND generation_id <> intent_row.generation_id AND published) THEN
        RAISE EXCEPTION 'atomic publication facts disagree' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (SELECT 1 FROM cragkit_qdrant.generations AS generation
        WHERE generation.tenant_id = row_tenant AND generation.collection = row_collection
            AND generation.document_id = row_document AND generation.generation_id = intent_row.generation_id
            AND (generation.expected_member_count <> (SELECT count(*) FROM cragkit_qdrant.members AS member
                WHERE member.tenant_id = row_tenant AND member.collection = row_collection
                    AND member.document_id = row_document AND member.generation_id = intent_row.generation_id)
                OR generation.expected_member_count <> (SELECT count(*) FROM cragkit_qdrant.point_claims AS claim
                    WHERE claim.tenant_id = row_tenant AND claim.collection = row_collection
                        AND claim.document_id = row_document AND claim.generation_id = intent_row.generation_id)
                OR generation.expected_member_count <> (SELECT count(*) FROM cragkit_qdrant.vector_replays AS replay
                    WHERE replay.tenant_id = row_tenant AND replay.collection = row_collection
                        AND replay.document_id = row_document AND replay.generation_id = intent_row.generation_id))) THEN
        RAISE EXCEPTION 'publication membership changed after preparation' USING ERRCODE = '23514';
    END IF;
END
$function$;
REVOKE ALL ON FUNCTION cragkit_qdrant.assert_publication(text,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cragkit_qdrant.assert_publication(text,text,text,text) TO cragkit_qdrant_writer;

CREATE FUNCTION cragkit_qdrant.check_publication_commit() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
DECLARE
    prior_active text;
BEGIN
    IF TG_TABLE_NAME = 'documents' THEN
        IF NEW.active_generation_id IS NOT DISTINCT FROM OLD.active_generation_id THEN RETURN NULL; END IF;
        prior_active := OLD.active_generation_id;
    ELSIF TG_TABLE_NAME = 'generations' THEN
        IF NOT NEW.published AND NOT NEW.ever_published THEN RETURN NULL; END IF;
        IF TG_OP = 'UPDATE' AND ROW(NEW.published,NEW.ever_published)
            IS NOT DISTINCT FROM ROW(OLD.published,OLD.ever_published) THEN RETURN NULL; END IF;
        SELECT expected_active_generation_id INTO prior_active FROM cragkit_qdrant.publication_intents
        WHERE tenant_id = NEW.tenant_id AND collection = NEW.collection AND document_id = NEW.document_id
            AND intent_id = current_setting('cragkit_qdrant.writer_intent_id',true);
    ELSE
        IF NEW.state NOT IN ('prepared','published') THEN RETURN NULL; END IF;
        IF NEW.state = 'prepared' THEN
            IF NOT EXISTS (SELECT 1 FROM cragkit_qdrant.preparations WHERE tenant_id = NEW.tenant_id
                AND collection = NEW.collection AND document_id = NEW.document_id AND intent_id = NEW.intent_id) THEN
                RAISE EXCEPTION 'prepared intent lacks preparation' USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END IF;
        prior_active := NEW.expected_active_generation_id;
    END IF;
    PERFORM cragkit_qdrant.assert_publication(NEW.tenant_id,NEW.collection,NEW.document_id,prior_active);
    RETURN NULL;
END
$function$;
CREATE CONSTRAINT TRIGGER publication_document_commit AFTER UPDATE ON cragkit_qdrant.documents
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.check_publication_commit();
CREATE CONSTRAINT TRIGGER publication_generation_commit AFTER INSERT OR UPDATE ON cragkit_qdrant.generations
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.check_publication_commit();
CREATE CONSTRAINT TRIGGER publication_intent_commit AFTER INSERT OR UPDATE ON cragkit_qdrant.publication_intents
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.check_publication_commit();

CREATE FUNCTION cragkit_qdrant.check_dispatch_commit() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM cragkit_qdrant.dispatch_points WHERE tenant_id = NEW.tenant_id
        AND collection = NEW.collection AND document_id = NEW.document_id
        AND intent_id = NEW.intent_id AND dispatch_id = NEW.dispatch_id) THEN
        RAISE EXCEPTION 'dispatch lacks claimed point set' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END
$function$;
CREATE CONSTRAINT TRIGGER publication_dispatch_commit AFTER INSERT ON cragkit_qdrant.dispatch_journal
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.check_dispatch_commit();

CREATE FUNCTION cragkit_qdrant.limit_managed_members() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'managed writes require read committed' USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM cragkit_qdrant.generations WHERE tenant_id = NEW.tenant_id
        AND collection = NEW.collection AND document_id = NEW.document_id
        AND generation_id = NEW.generation_id FOR UPDATE;
    IF EXISTS (SELECT 1 FROM cragkit_qdrant.generations WHERE tenant_id = NEW.tenant_id
        AND collection = NEW.collection AND document_id = NEW.document_id
        AND generation_id = NEW.generation_id AND ever_published) THEN
        RAISE EXCEPTION 'published membership is immutable' USING ERRCODE = '23514';
    END IF;
    IF (SELECT count(*) FROM cragkit_qdrant.members WHERE tenant_id = NEW.tenant_id
        AND collection = NEW.collection AND document_id = NEW.document_id
        AND generation_id = NEW.generation_id) > 64 THEN
        RAISE EXCEPTION 'managed member limit exceeded' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END
$function$;
CREATE TRIGGER publication_member_limit AFTER INSERT ON cragkit_qdrant.members
    FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.limit_managed_members();

CREATE FUNCTION cragkit_qdrant.guard_initial_document() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'managed writes require read committed' USING ERRCODE = '23514';
    END IF;
    IF NEW.active_generation_id IS NOT NULL THEN
        RAISE EXCEPTION 'new document must start unpublished' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER publication_initial_document BEFORE INSERT ON cragkit_qdrant.documents
    FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.guard_initial_document();

-- Do not rely on 0001's creator-specific default privileges for a later owner.
REVOKE ALL ON FUNCTION cragkit_qdrant.guard_backend_instance(), cragkit_qdrant.guard_publication_intent(),
    cragkit_qdrant.guard_document_owner(), cragkit_qdrant.guard_point_claim(), cragkit_qdrant.guard_vector_replay(),
    cragkit_qdrant.guard_dispatch(), cragkit_qdrant.guard_dispatch_point(), cragkit_qdrant.guard_preparation(),
    cragkit_qdrant.check_publication_commit(), cragkit_qdrant.check_dispatch_commit(),
    cragkit_qdrant.limit_managed_members(), cragkit_qdrant.guard_initial_document() FROM PUBLIC;
