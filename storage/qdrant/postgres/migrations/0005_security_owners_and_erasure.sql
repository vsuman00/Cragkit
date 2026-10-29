-- QP-r1: explicit operator transaction; the wrapper records this file's checksum.
DO $migration$
DECLARE operator_id oid;
BEGIN
 SELECT r.oid INTO operator_id FROM pg_catalog.pg_roles r JOIN pg_catalog.pg_namespace n
 ON n.nspowner=r.oid AND n.nspname='cragkit_qdrant'
 WHERE r.rolname=current_user AND current_user=session_user AND r.rolcanlogin AND r.rolcreaterole
 AND NOT r.rolsuper AND NOT r.rolbypassrls;
 IF operator_id IS NULL OR pg_catalog.current_setting('role',true)<>'none'
 OR pg_catalog.current_setting('server_version_num')::integer NOT BETWEEN 170000 AND 179999
 OR pg_catalog.current_setting('server_encoding')<>'UTF8'
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND c.relowner<>operator_id)
 OR pg_catalog.pg_has_role(operator_id,'cragkit_qdrant_writer','MEMBER')
 OR pg_catalog.pg_has_role(operator_id,'cragkit_qdrant_supervisor','MEMBER')
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_roles r WHERE NOT r.rolsuper
 AND (pg_catalog.pg_has_role(r.oid,'cragkit_qdrant_writer','MEMBER') OR pg_catalog.pg_has_role(r.oid,'cragkit_qdrant_supervisor','MEMBER'))
 AND pg_catalog.pg_has_role(r.oid,operator_id,'MEMBER'))
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='cragkit_qdrant_purger')
 OR (SELECT count(*) FROM cragkit_qdrant.schema_migrations)<>4
 OR NOT EXISTS(SELECT 1 FROM cragkit_qdrant.schema_migrations WHERE version='0001_authority' AND checksum_sha256='3d75cd46eb32a10864f1097a7494b01f9759150911a7cd9a1e6aab60105c1f1a')
 OR NOT EXISTS(SELECT 1 FROM cragkit_qdrant.schema_migrations WHERE version='0002_publication' AND checksum_sha256='386fe01d0d03e35ac35c21bce598b21bff2c5ad510e9cdf0a6fbe56f359b6661')
 OR NOT EXISTS(SELECT 1 FROM cragkit_qdrant.schema_migrations WHERE version='0003_preparation_attestations' AND checksum_sha256='8c6791cd0fd65ff09758c068ebc90a895a4ac21d9713512486d3daf9cb7c8433')
 OR NOT EXISTS(SELECT 1 FROM cragkit_qdrant.schema_migrations WHERE version='0004_security_settlement_guard' AND checksum_sha256='44b666cb47f3bb51ac8c5f6eb05fe8aea9138a9c603ab2fa427bdd807255be0b') THEN
 RAISE EXCEPTION 'unsupported managed erasure operator or history' USING ERRCODE='22023'; END IF;
 PERFORM pg_catalog.set_config('createrole_self_grant','',true);
END
$migration$;

CREATE ROLE cragkit_qdrant_purger NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT NOCREATEDB NOCREATEROLE NOREPLICATION;
GRANT cragkit_qdrant_purger TO CURRENT_USER WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
GRANT USAGE,CREATE ON SCHEMA cragkit_qdrant TO cragkit_qdrant_purger;

ALTER TABLE cragkit_qdrant.documents ADD COLUMN content_unavailable boolean NOT NULL DEFAULT false;
ALTER TABLE cragkit_qdrant.document_revisions ADD COLUMN content_erased boolean NOT NULL DEFAULT false,
 ADD COLUMN canonical_original_bytes bigint, ALTER COLUMN canonical_utf8 DROP NOT NULL;
ALTER TABLE cragkit_qdrant.members ADD COLUMN content_erased boolean NOT NULL DEFAULT false,
 ADD COLUMN excerpt_original_bytes bigint, ALTER COLUMN excerpt_utf8 DROP NOT NULL;
ALTER TABLE cragkit_qdrant.vector_replays ADD COLUMN content_erased boolean NOT NULL DEFAULT false,
 ADD COLUMN dense_original_bytes bigint, ADD COLUMN sparse_original_bytes bigint, ALTER COLUMN dense_blob DROP NOT NULL;
ALTER TABLE cragkit_qdrant.dispatch_journal ADD COLUMN content_erased boolean NOT NULL DEFAULT false,
 ADD COLUMN request_original_bytes bigint, ALTER COLUMN request_bytes DROP NOT NULL;

-- Existing rows are backfilled only in this explicit operator migration.
DROP TRIGGER immutable_revision ON cragkit_qdrant.document_revisions;
DROP TRIGGER immutable_member ON cragkit_qdrant.members;
DROP TRIGGER vector_replay_guard ON cragkit_qdrant.vector_replays;
DROP TRIGGER publication_dispatch_guard ON cragkit_qdrant.dispatch_journal;
CREATE POLICY migration_erasure_backfill ON cragkit_qdrant.document_revisions FOR ALL TO CURRENT_USER USING(true) WITH CHECK(true);
CREATE POLICY migration_erasure_backfill ON cragkit_qdrant.members FOR ALL TO CURRENT_USER USING(true) WITH CHECK(true);
CREATE POLICY migration_erasure_backfill ON cragkit_qdrant.vector_replays FOR ALL TO CURRENT_USER USING(true) WITH CHECK(true);
CREATE POLICY migration_erasure_backfill ON cragkit_qdrant.dispatch_journal FOR ALL TO CURRENT_USER USING(true) WITH CHECK(true);
UPDATE cragkit_qdrant.document_revisions SET canonical_original_bytes=pg_catalog.octet_length(canonical_utf8);
UPDATE cragkit_qdrant.members SET excerpt_original_bytes=pg_catalog.octet_length(excerpt_utf8);
UPDATE cragkit_qdrant.vector_replays SET dense_original_bytes=pg_catalog.octet_length(dense_blob),sparse_original_bytes=pg_catalog.octet_length(sparse_blob);
UPDATE cragkit_qdrant.dispatch_journal SET request_original_bytes=pg_catalog.octet_length(request_bytes);
DROP POLICY migration_erasure_backfill ON cragkit_qdrant.document_revisions;
DROP POLICY migration_erasure_backfill ON cragkit_qdrant.members;
DROP POLICY migration_erasure_backfill ON cragkit_qdrant.vector_replays;
DROP POLICY migration_erasure_backfill ON cragkit_qdrant.dispatch_journal;
ALTER TABLE cragkit_qdrant.document_revisions ALTER COLUMN canonical_original_bytes SET NOT NULL,
 ADD CONSTRAINT revision_erasure_shape CHECK(canonical_original_bytes BETWEEN 1 AND 16777216 AND
 ((content_erased AND canonical_utf8 IS NULL) OR (NOT content_erased AND canonical_utf8 IS NOT NULL AND canonical_original_bytes=pg_catalog.octet_length(canonical_utf8))));
ALTER TABLE cragkit_qdrant.members ALTER COLUMN excerpt_original_bytes SET NOT NULL,
 ADD CONSTRAINT member_erasure_shape CHECK(excerpt_original_bytes BETWEEN 1 AND 32768 AND excerpt_original_bytes=end_byte-start_byte AND
 ((content_erased AND excerpt_utf8 IS NULL) OR (NOT content_erased AND excerpt_utf8 IS NOT NULL AND excerpt_original_bytes=pg_catalog.octet_length(excerpt_utf8))));
-- Sparse absence is immutable metadata, separate from erased formerly present bytes.
DO $migration$
DECLARE constraint_name text;
BEGIN
 SELECT conname INTO STRICT constraint_name FROM pg_catalog.pg_constraint
 WHERE conrelid='cragkit_qdrant.vector_replays'::pg_catalog.regclass AND contype='c'
 AND pg_catalog.pg_get_constraintdef(oid) LIKE '%(sparse_blob IS NULL) = (sparse_blob_sha256 IS NULL)%';
 EXECUTE pg_catalog.format('ALTER TABLE cragkit_qdrant.vector_replays DROP CONSTRAINT %I',constraint_name);
END
$migration$;
ALTER TABLE cragkit_qdrant.vector_replays ALTER COLUMN dense_original_bytes SET NOT NULL,
 ADD CONSTRAINT replay_sparse_original_shape CHECK((sparse_original_bytes IS NULL)=(sparse_blob_sha256 IS NULL)),
 ADD CONSTRAINT replay_erasure_shape CHECK(dense_original_bytes=12326
 AND ((sparse_original_bytes IS NULL AND sparse_blob_sha256 IS NULL) OR
 (sparse_original_bytes BETWEEN 51 AND 231 AND sparse_blob_sha256 IS NOT NULL))
 AND ((content_erased AND dense_blob IS NULL AND sparse_blob IS NULL) OR
 (NOT content_erased AND dense_blob IS NOT NULL AND pg_catalog.octet_length(dense_blob)=dense_original_bytes
 AND ((sparse_original_bytes IS NULL AND sparse_blob IS NULL) OR (sparse_original_bytes IS NOT NULL AND sparse_blob IS NOT NULL AND pg_catalog.octet_length(sparse_blob)=sparse_original_bytes)))));
ALTER TABLE cragkit_qdrant.dispatch_journal ALTER COLUMN request_original_bytes SET NOT NULL,
 ADD CONSTRAINT journal_erasure_shape CHECK(request_original_bytes BETWEEN 1 AND 1048576 AND
 ((content_erased AND request_bytes IS NULL) OR (NOT content_erased AND request_bytes IS NOT NULL AND request_original_bytes=pg_catalog.octet_length(request_bytes))));

CREATE TABLE cragkit_qdrant.purge_erasures(
 tenant_id cragkit_qdrant.identity_text NOT NULL, collection cragkit_qdrant.collection_text NOT NULL,
 document_id cragkit_qdrant.identity_text NOT NULL, purge_intent_id cragkit_qdrant.identity_text NOT NULL,
 instance_id cragkit_qdrant.identity_text NOT NULL, backend_namespace cragkit_qdrant.identity_text NOT NULL,
 storage_identity cragkit_qdrant.identity_text NOT NULL, supervisor_id cragkit_qdrant.identity_text NOT NULL,
 backend_epoch cragkit_qdrant.safe_count NOT NULL CHECK(backend_epoch>0),
 physical_collection text COLLATE pg_catalog."C" NOT NULL CHECK(physical_collection ~ '^[A-Za-z][A-Za-z0-9_-]{0,63}$'),
 collection_incarnation cragkit_qdrant.identity_text NOT NULL, owner_token uuid NOT NULL,
 purge_payload_sha256 cragkit_qdrant.sha256_hex NOT NULL, tombstone_payload_sha256 cragkit_qdrant.sha256_hex NOT NULL,
 authorization_revision cragkit_qdrant.identity_text NOT NULL, mutation_epoch cragkit_qdrant.safe_count NOT NULL CHECK(mutation_epoch>0),
 inventory_sha256 cragkit_qdrant.sha256_hex NOT NULL, policy_id text COLLATE pg_catalog."C" NOT NULL CHECK(policy_id='erase_managed_source_and_replay_v1'),
 absence_sha256 cragkit_qdrant.sha256_hex NOT NULL, erasure_sha256 cragkit_qdrant.sha256_hex NOT NULL,
 PRIMARY KEY(tenant_id,collection,document_id,purge_intent_id),
 FOREIGN KEY(tenant_id,collection,document_id,purge_intent_id) REFERENCES cragkit_qdrant.publication_intents(tenant_id,collection,document_id,intent_id)
);
ALTER TABLE cragkit_qdrant.purge_erasures ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit_qdrant.purge_erasures FORCE ROW LEVEL SECURITY;
REVOKE ALL ON cragkit_qdrant.purge_erasures FROM PUBLIC;
GRANT SELECT ON cragkit_qdrant.purge_erasures TO cragkit_qdrant_writer;
CREATE POLICY writer_erasure_read ON cragkit_qdrant.purge_erasures FOR SELECT TO cragkit_qdrant_writer
 USING(cragkit_qdrant.writer_scope(tenant_id,collection,document_id));
CREATE TRIGGER immutable_erasure BEFORE UPDATE OR DELETE ON cragkit_qdrant.purge_erasures
 FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.reject_immutable_update();

GRANT SELECT(instance_id,backend_namespace,storage_identity,supervisor_id,epoch,state,recovery_id),UPDATE(epoch)
 ON cragkit_qdrant.backend_instances TO cragkit_qdrant_purger;
GRANT SELECT(tenant_id,collection,document_id,instance_id,intent_id,owner_token,backend_epoch),UPDATE(backend_epoch)
 ON cragkit_qdrant.document_owners TO cragkit_qdrant_purger;
GRANT SELECT(tenant_id,collection,document_id,authorization_revision,mutation_epoch,tombstoned,content_unavailable),UPDATE(content_unavailable)
 ON cragkit_qdrant.documents TO cragkit_qdrant_purger;
GRANT SELECT(tenant_id,collection,document_id,intent_id,instance_id,action,payload_bytes,payload_sha256,manifest_bytes,manifest_sha256,
 revision_id,generation_id,expected_authorization_revision,expected_mutation_epoch,state,authority_committed,replica_complete,purge_complete),
 UPDATE(state,authority_committed,replica_complete,purge_complete) ON cragkit_qdrant.publication_intents TO cragkit_qdrant_purger;
GRANT SELECT(tenant_id,collection,document_id,revision_id,content_erased,canonical_original_bytes),UPDATE(canonical_utf8,content_erased)
 ON cragkit_qdrant.document_revisions TO cragkit_qdrant_purger;
GRANT SELECT(tenant_id,collection,document_id,revision_id,generation_id,backend_namespace,physical_collection,collection_incarnation,ever_published)
 ON cragkit_qdrant.generations TO cragkit_qdrant_purger;
GRANT SELECT(tenant_id,collection,document_id,content_erased,excerpt_original_bytes),UPDATE(excerpt_utf8,content_erased)
 ON cragkit_qdrant.members TO cragkit_qdrant_purger;
GRANT SELECT(tenant_id,collection,document_id,instance_id,backend_namespace,physical_collection,collection_incarnation,point_id,revision_id,generation_id)
 ON cragkit_qdrant.point_claims TO cragkit_qdrant_purger;
GRANT SELECT(tenant_id,collection,document_id,content_erased,dense_original_bytes,sparse_original_bytes),UPDATE(dense_blob,sparse_blob,content_erased)
 ON cragkit_qdrant.vector_replays TO cragkit_qdrant_purger;
GRANT SELECT(tenant_id,collection,document_id,state,content_erased,request_original_bytes),UPDATE(request_bytes,content_erased)
 ON cragkit_qdrant.dispatch_journal TO cragkit_qdrant_purger;
GRANT SELECT,INSERT ON cragkit_qdrant.purge_erasures TO cragkit_qdrant_purger;
GRANT EXECUTE ON FUNCTION cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean),cragkit_qdrant.scope_grants(),cragkit_qdrant.valid_identity_array(text[])
 TO cragkit_qdrant_purger;

DO $policies$
DECLARE table_name text; scope_sql text := '(tenant_id=current_setting(''cragkit_qdrant.tenant_id'',true) AND collection=current_setting(''cragkit_qdrant.collection'',true) AND document_id=current_setting(''cragkit_qdrant.writer_document_id'',true))';
BEGIN
 CREATE POLICY purger_backend_read ON cragkit_qdrant.backend_instances FOR SELECT TO cragkit_qdrant_purger USING(instance_id=current_setting('cragkit_qdrant.backend_instance_id',true));
 CREATE POLICY purger_backend_lock ON cragkit_qdrant.backend_instances FOR UPDATE TO cragkit_qdrant_purger USING(instance_id=current_setting('cragkit_qdrant.backend_instance_id',true)) WITH CHECK(false);
 FOREACH table_name IN ARRAY ARRAY['document_owners','documents','publication_intents','document_revisions','generations','members','point_claims','vector_replays','dispatch_journal','purge_erasures'] LOOP
 EXECUTE pg_catalog.format('CREATE POLICY purger_read ON cragkit_qdrant.%I FOR SELECT TO cragkit_qdrant_purger USING (%s)',table_name,scope_sql);
 IF table_name IN ('document_owners','documents','publication_intents','document_revisions','members','vector_replays','dispatch_journal') THEN
 EXECUTE pg_catalog.format('CREATE POLICY purger_update ON cragkit_qdrant.%I FOR UPDATE TO cragkit_qdrant_purger USING (%s) WITH CHECK (%s)',table_name,scope_sql,CASE WHEN table_name='document_owners' THEN 'false' ELSE scope_sql END);
 END IF;
 END LOOP;
 EXECUTE pg_catalog.format('CREATE POLICY purger_insert ON cragkit_qdrant.purge_erasures FOR INSERT TO cragkit_qdrant_purger WITH CHECK (%s)',scope_sql);
END
$policies$;

-- Operational dispatch insertion needs only the permanent marker and a row lock.
GRANT EXECUTE ON FUNCTION cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean) TO cragkit_qdrant_supervisor;
GRANT SELECT(tenant_id,collection,document_id,content_unavailable),UPDATE(content_unavailable)
 ON cragkit_qdrant.documents TO cragkit_qdrant_supervisor;
CREATE POLICY supervisor_content_read ON cragkit_qdrant.documents FOR SELECT TO cragkit_qdrant_supervisor
 USING(EXISTS(SELECT 1 FROM cragkit_qdrant.document_owners o WHERE o.tenant_id=documents.tenant_id AND o.collection=documents.collection
 AND o.document_id=documents.document_id AND o.instance_id=current_setting('cragkit_qdrant.backend_instance_id',true)));
CREATE POLICY supervisor_content_lock ON cragkit_qdrant.documents FOR UPDATE TO cragkit_qdrant_supervisor
 USING(EXISTS(SELECT 1 FROM cragkit_qdrant.document_owners o WHERE o.tenant_id=documents.tenant_id AND o.collection=documents.collection
 AND o.document_id=documents.document_id AND o.instance_id=current_setting('cragkit_qdrant.backend_instance_id',true))) WITH CHECK(false);

CREATE FUNCTION cragkit_qdrant.guard_managed_body_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $function$
DECLARE unavailable boolean;
BEGIN
 SELECT content_unavailable INTO unavailable FROM cragkit_qdrant.documents
 WHERE tenant_id=NEW.tenant_id AND collection=NEW.collection AND document_id=NEW.document_id FOR SHARE;
 IF NOT FOUND OR unavailable OR NEW.content_erased THEN
 RAISE EXCEPTION 'managed content unavailable' USING ERRCODE='23514'; END IF;
 CASE TG_TABLE_NAME
 WHEN 'document_revisions' THEN NEW.canonical_original_bytes:=pg_catalog.octet_length(NEW.canonical_utf8);
 WHEN 'members' THEN NEW.excerpt_original_bytes:=pg_catalog.octet_length(NEW.excerpt_utf8);
 WHEN 'vector_replays' THEN NEW.dense_original_bytes:=pg_catalog.octet_length(NEW.dense_blob); NEW.sparse_original_bytes:=pg_catalog.octet_length(NEW.sparse_blob);
 WHEN 'dispatch_journal' THEN NEW.request_original_bytes:=pg_catalog.octet_length(NEW.request_bytes);
 ELSE RAISE EXCEPTION 'unsupported managed content table' USING ERRCODE='23514'; END CASE;
 RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION cragkit_qdrant.guard_managed_body_insert() FROM PUBLIC;
CREATE TRIGGER z_managed_body_insert BEFORE INSERT ON cragkit_qdrant.document_revisions FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.guard_managed_body_insert();
CREATE TRIGGER z_managed_body_insert BEFORE INSERT ON cragkit_qdrant.members FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.guard_managed_body_insert();
CREATE TRIGGER z_managed_body_insert BEFORE INSERT ON cragkit_qdrant.vector_replays FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.guard_managed_body_insert();
CREATE TRIGGER z_managed_body_insert BEFORE INSERT ON cragkit_qdrant.dispatch_journal FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.guard_managed_body_insert();

CREATE FUNCTION cragkit_qdrant.guard_managed_body_erasure() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $function$
DECLARE columns text[];
BEGIN
 columns:=CASE TG_TABLE_NAME WHEN 'document_revisions' THEN ARRAY['canonical_utf8','content_erased']
 WHEN 'members' THEN ARRAY['excerpt_utf8','content_erased'] WHEN 'vector_replays' THEN ARRAY['dense_blob','sparse_blob','content_erased']
 WHEN 'dispatch_journal' THEN ARRAY['request_bytes','content_erased'] END;
 IF current_user<>'cragkit_qdrant_purger' OR columns IS NULL OR TG_OP<>'UPDATE'
 OR OLD.content_erased OR NOT NEW.content_erased
 OR (pg_catalog.to_jsonb(NEW)-columns) IS DISTINCT FROM (pg_catalog.to_jsonb(OLD)-columns) THEN
 RAISE EXCEPTION 'immutable managed content' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION cragkit_qdrant.guard_managed_body_erasure() FROM PUBLIC;
CREATE TRIGGER immutable_revision BEFORE UPDATE ON cragkit_qdrant.document_revisions FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.guard_managed_body_erasure();
CREATE TRIGGER immutable_member BEFORE UPDATE ON cragkit_qdrant.members FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.guard_managed_body_erasure();

CREATE OR REPLACE FUNCTION cragkit_qdrant.guard_vector_replay() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
DECLARE
    absent_sparse boolean;
BEGIN
    IF TG_OP='UPDATE' AND current_user='cragkit_qdrant_purger' THEN
        IF OLD.content_erased OR NOT NEW.content_erased
           OR (pg_catalog.to_jsonb(NEW)-ARRAY['dense_blob','sparse_blob','content_erased']) IS DISTINCT FROM
              (pg_catalog.to_jsonb(OLD)-ARRAY['dense_blob','sparse_blob','content_erased']) THEN
            RAISE EXCEPTION 'immutable managed content' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END IF;
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

CREATE OR REPLACE FUNCTION cragkit_qdrant.guard_dispatch() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
DECLARE
    owner_intent text;
    intent_state text;
    control_epoch bigint;
    recovering_settlement boolean := false;
BEGIN
    IF TG_OP='UPDATE' AND current_user='cragkit_qdrant_purger' THEN
        IF OLD.content_erased OR NOT NEW.content_erased
           OR (pg_catalog.to_jsonb(NEW)-ARRAY['request_bytes','content_erased']) IS DISTINCT FROM
              (pg_catalog.to_jsonb(OLD)-ARRAY['request_bytes','content_erased']) THEN
            RAISE EXCEPTION 'immutable managed content' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END IF;
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

CREATE OR REPLACE FUNCTION cragkit_qdrant.guard_document_update() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
BEGIN
    IF NEW.content_unavailable IS DISTINCT FROM OLD.content_unavailable THEN
        IF current_user<>'cragkit_qdrant_purger' OR OLD.content_unavailable OR NOT NEW.content_unavailable
           OR NOT OLD.tombstoned OR (pg_catalog.to_jsonb(NEW)-'content_unavailable') IS DISTINCT FROM
              (pg_catalog.to_jsonb(OLD)-'content_unavailable') THEN
            RAISE EXCEPTION 'immutable source availability' USING ERRCODE='23514';
        END IF;
    END IF;
    IF ROW(NEW.tenant_id, NEW.collection, NEW.document_id, NEW.created_at)
        IS DISTINCT FROM ROW(OLD.tenant_id, OLD.collection, OLD.document_id, OLD.created_at)
        OR (OLD.tombstoned AND NOT NEW.tombstoned) OR NEW.mutation_epoch < OLD.mutation_epoch THEN
        RAISE EXCEPTION 'immutable document identity or tombstone' USING ERRCODE = '23514';
    END IF;
    IF ROW(NEW.principal_ids, NEW.grant_ids, NEW.language, NEW.kind, NEW.tag, NEW.tombstoned, NEW.authorization_revision)
        IS DISTINCT FROM ROW(OLD.principal_ids, OLD.grant_ids, OLD.language, OLD.kind, OLD.tag, OLD.tombstoned, OLD.authorization_revision)
        AND NEW.mutation_epoch <= OLD.mutation_epoch THEN
        RAISE EXCEPTION 'authority change requires a newer mutation epoch' USING ERRCODE = '23514';
    END IF;
    IF ROW(NEW.principal_ids, NEW.grant_ids, NEW.language, NEW.kind, NEW.tag, NEW.tombstoned)
        IS DISTINCT FROM ROW(OLD.principal_ids, OLD.grant_ids, OLD.language, OLD.kind, OLD.tag, OLD.tombstoned)
        AND NEW.authorization_revision = OLD.authorization_revision THEN
        RAISE EXCEPTION 'authority change requires a new revision' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;

CREATE OR REPLACE FUNCTION cragkit_qdrant.guard_publication_intent() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
BEGIN
    IF TG_OP='UPDATE' AND NEW.action='purge' AND
       ROW(NEW.authority_committed,NEW.replica_complete,NEW.purge_complete) IS DISTINCT FROM
       ROW(OLD.authority_committed,OLD.replica_complete,OLD.purge_complete)
       AND (NEW.replica_complete OR NEW.purge_complete) AND current_user<>'cragkit_qdrant_purger' THEN
        RAISE EXCEPTION 'managed purge requires erasure capability' USING ERRCODE='23514';
    END IF;
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

GRANT CREATE ON SCHEMA cragkit_qdrant TO cragkit_qdrant_security_guard;
SET LOCAL ROLE cragkit_qdrant_security_guard;
CREATE OR REPLACE FUNCTION cragkit_qdrant.lock_current_security(
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
              OR (c.relname='documents' AND a.attname IN ('tenant_id','collection','document_id','content_unavailable'))
              OR (c.relname='publication_intents' AND a.attname IN ('tenant_id','collection','document_id','intent_id','instance_id','action','payload_sha256','manifest_sha256','revision_id','generation_id','expected_active_generation_id','expected_authorization_revision','expected_mutation_epoch','state','authority_committed','replica_complete','purge_complete'))
              OR (c.relname='dispatch_journal' AND a.attname IN ('tenant_id','collection','document_id','intent_id','dispatch_id','instance_id','sequence','owner_token','backend_epoch','credential_generation','operation','recovery','request_sha256','state','completion_sha256','created_xid'))
            WHEN privilege='INSERT' THEN c.relname IN ('backend_instances','dispatch_journal','dispatch_points')
            WHEN privilege='UPDATE' THEN c.relname='backend_instances'
              OR (c.relname='documents' AND a.attname='content_unavailable')
              OR (c.relname='document_owners' AND a.attname='backend_epoch')
              OR (c.relname='dispatch_journal' AND a.attname IN ('state','completion_sha256')) ELSE false END)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname='cragkit_qdrant' AND pg_catalog.has_function_privilege(caller_id,p.oid,'EXECUTE') IS DISTINCT FROM
          (p.oid=function_id OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean)')
           OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.valid_identity_array(text[])')
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
           WHERE n.nspname='cragkit_qdrant' AND p.prosecdef AND p.oid NOT IN (function_id,pg_catalog.to_regprocedure('cragkit_qdrant.erase_purged_document(text,text,text,text,bigint,text,text,text,text,text,text,text,uuid,text,text,bigint,bytea,text,text,text)')))
       OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_proc WHERE oid=pg_catalog.to_regprocedure('cragkit_qdrant.erase_purged_document(text,text,text,text,bigint,text,text,text,text,text,text,text,uuid,text,text,bigint,bytea,text,text,text)') AND proowner='cragkit_qdrant_purger'::pg_catalog.regrole AND prosecdef AND provolatile='v' AND proparallel='u' AND NOT proisstrict AND NOT proleakproof AND proconfig=ARRAY['search_path=pg_catalog','row_security=on']::text[])
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
        AND document_id=p_document_id AND intent_id=p_owner_intent_id AND instance_id=p_instance_id
        AND (action='stage' OR (action IN ('update_authorization','tombstone') AND authority_committed))) THEN
        RAISE EXCEPTION 'security guard mismatch' USING ERRCODE='23514';
    END IF;
    SELECT action,payload_sha256,expected_mutation_epoch,authority_committed INTO security_row FROM cragkit_qdrant.publication_intents
      WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id
        AND intent_id=p_security_intent_id AND instance_id=p_instance_id;
    IF NOT FOUND OR security_row.action NOT IN ('update_authorization','tombstone')
       OR NOT security_row.authority_committed OR security_row.payload_sha256 IS DISTINCT FROM p_security_payload_sha256
       OR security_row.expected_mutation_epoch IS DISTINCT FROM p_mutation_epoch-1
       OR (security_row.action='tombstone' AND NOT p_tombstoned) THEN
        RAISE EXCEPTION 'security guard mismatch' USING ERRCODE='23514';
    END IF;
END
$guard$;

RESET ROLE;
REVOKE CREATE ON SCHEMA cragkit_qdrant FROM cragkit_qdrant_security_guard;

CREATE FUNCTION cragkit_qdrant.erase_purged_document(
 p_instance_id text,p_backend_namespace text,p_storage_identity text,p_supervisor_id text,p_backend_epoch bigint,
 p_physical_collection text,p_collection_incarnation text,p_tenant_id text,p_collection text,p_document_id text,
 p_purge_intent_id text,p_purge_payload_sha256 text,p_owner_token uuid,p_tombstone_payload_sha256 text,
 p_authorization_revision text,p_mutation_epoch bigint,p_inventory_bytes bytea,p_inventory_sha256 text,
 p_policy_id text,p_absence_sha256 text
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT
SET search_path=pg_catalog SET row_security=on AS $erase$
DECLARE
 caller_id oid; purger_id oid; operator_id oid; writer_id oid; function_id oid;
 value text; backend_row record; owner_row record; document_row record; purge_row record;
 erasure_row record; expected_inventory jsonb; inventory_groups jsonb; canonical_payload bytea;
 terminal_sha256 text; journal_count bigint; source_bytes bigint; replay_bytes bigint; request_bytes_count bigint;
BEGIN
 SELECT oid INTO caller_id FROM pg_catalog.pg_roles WHERE rolname=session_user;
 SELECT oid INTO purger_id FROM pg_catalog.pg_roles WHERE rolname='cragkit_qdrant_purger';
 SELECT oid INTO writer_id FROM pg_catalog.pg_roles WHERE rolname='cragkit_qdrant_writer';
 SELECT nspowner INTO operator_id FROM pg_catalog.pg_namespace WHERE nspname='cragkit_qdrant';
 function_id:=pg_catalog.to_regprocedure('cragkit_qdrant.erase_purged_document(text,text,text,text,bigint,text,text,text,text,text,text,text,uuid,text,text,bigint,bytea,text,text,text)');
 IF pg_catalog.current_setting('role',true) IS DISTINCT FROM 'none'
 OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE oid=caller_id AND rolcanlogin
 AND NOT(rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication))
 OR NOT pg_catalog.pg_has_role(caller_id,writer_id,'USAGE')
 OR pg_catalog.pg_has_role(caller_id,'cragkit_qdrant_supervisor','MEMBER')
 OR pg_catalog.pg_has_role(caller_id,purger_id,'MEMBER')
 OR pg_catalog.pg_has_role(caller_id,'cragkit_qdrant_security_guard','MEMBER')
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_roles r WHERE pg_catalog.pg_has_role(caller_id,r.oid,'MEMBER')
 AND r.oid NOT IN (caller_id,writer_id))
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_database WHERE pg_catalog.pg_has_role(caller_id,datdba,'MEMBER'))
 OR NOT pg_catalog.has_schema_privilege(caller_id,'cragkit_qdrant','USAGE')
 OR pg_catalog.has_schema_privilege(caller_id,'cragkit_qdrant','CREATE')
 OR pg_catalog.pg_has_role(caller_id,operator_id,'MEMBER')
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='cragkit_qdrant' AND pg_catalog.pg_has_role(caller_id,c.relowner,'MEMBER'))
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='cragkit_qdrant' AND pg_catalog.pg_has_role(caller_id,p.proowner,'MEMBER'))
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
 WHERE n.nspname='cragkit_qdrant' AND pg_catalog.pg_has_role(caller_id,t.typowner,'MEMBER')) THEN
 RAISE EXCEPTION 'managed erasure caller rejected' USING ERRCODE='42501'; END IF;
 IF current_user<>'cragkit_qdrant_purger'
 OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE oid=purger_id AND NOT
 (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication OR rolinherit))
 OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE oid=operator_id AND rolcreaterole AND NOT rolsuper AND NOT rolbypassrls)
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members WHERE member=purger_id)
 OR (SELECT count(*) FROM pg_catalog.pg_auth_members WHERE roleid=purger_id)<>2
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m WHERE roleid=purger_id AND NOT
 (member=operator_id AND NOT inherit_option AND ((grantor=10 AND admin_option AND NOT set_option)
 OR (grantor=operator_id AND NOT admin_option AND set_option))))
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_roles r WHERE NOT r.rolsuper
 AND (pg_catalog.pg_has_role(r.oid,writer_id,'MEMBER') OR pg_catalog.pg_has_role(r.oid,'cragkit_qdrant_supervisor','MEMBER'))
 AND pg_catalog.pg_has_role(r.oid,operator_id,'MEMBER'))
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspowner=purger_id)
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_class WHERE relowner=purger_id)
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_type WHERE typowner=purger_id)
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_database WHERE datdba=purger_id)
 OR (SELECT count(*) FROM pg_catalog.pg_proc WHERE proowner=purger_id)<>1
 OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_proc WHERE oid=function_id AND proowner=purger_id AND prosecdef
 AND provolatile='v' AND proparallel='u' AND NOT proisstrict AND NOT proleakproof
 AND proconfig=ARRAY['search_path=pg_catalog','row_security=on']::text[])
 OR pg_catalog.has_schema_privilege(purger_id,'cragkit_qdrant','CREATE')
 OR NOT pg_catalog.has_schema_privilege(purger_id,'cragkit_qdrant','USAGE')
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND (c.relowner<>operator_id OR
 (c.relname<>'schema_migrations' AND NOT(c.relrowsecurity AND c.relforcerowsecurity))))
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='cragkit_qdrant' AND p.prosecdef AND p.oid NOT IN (function_id,
 pg_catalog.to_regprocedure('cragkit_qdrant.lock_current_security(text,text,text,text,text,bigint,text,text,text,text,uuid,text,text,text,text,bigint,text[],text[],text,text,text,boolean)')))
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p CROSS JOIN LATERAL pg_catalog.aclexplode(p.proacl) a
 WHERE p.oid=function_id AND (a.grantee NOT IN (purger_id,writer_id) OR a.grantor<>purger_id
 OR a.privilege_type<>'EXECUTE' OR (a.grantee=writer_id AND a.is_grantable)))
 OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p CROSS JOIN LATERAL pg_catalog.aclexplode(p.proacl) a
 WHERE p.oid=function_id AND a.grantee=writer_id AND a.privilege_type='EXECUTE' AND NOT a.is_grantable) THEN
 RAISE EXCEPTION 'managed erasure profile rejected' USING ERRCODE='22023'; END IF;

 IF EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 CROSS JOIN pg_catalog.unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) privilege
 WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND
 pg_catalog.has_table_privilege(purger_id,c.oid,privilege) IS DISTINCT FROM
 (c.relname='purge_erasures' AND privilege IN ('SELECT','INSERT')))
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
 JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 CROSS JOIN pg_catalog.unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) privilege
 WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
 AND pg_catalog.has_column_privilege(purger_id,c.oid,a.attnum,privilege) IS DISTINCT FROM CASE
 WHEN privilege='SELECT' THEN c.relname='purge_erasures' OR (c.relname='backend_instances' AND a.attname IN ('instance_id','backend_namespace','storage_identity','supervisor_id','epoch','state','recovery_id'))
 OR (c.relname='document_owners' AND a.attname IN ('tenant_id','collection','document_id','instance_id','intent_id','owner_token','backend_epoch'))
 OR (c.relname='documents' AND a.attname IN ('tenant_id','collection','document_id','authorization_revision','mutation_epoch','tombstoned','content_unavailable'))
 OR (c.relname='publication_intents' AND a.attname IN ('tenant_id','collection','document_id','intent_id','instance_id','action','payload_bytes','payload_sha256','manifest_bytes','manifest_sha256','revision_id','generation_id','expected_authorization_revision','expected_mutation_epoch','state','authority_committed','replica_complete','purge_complete'))
 OR (c.relname='document_revisions' AND a.attname IN ('tenant_id','collection','document_id','revision_id','content_erased','canonical_original_bytes'))
 OR (c.relname='generations' AND a.attname IN ('tenant_id','collection','document_id','revision_id','generation_id','backend_namespace','physical_collection','collection_incarnation','ever_published'))
 OR (c.relname='members' AND a.attname IN ('tenant_id','collection','document_id','content_erased','excerpt_original_bytes'))
 OR (c.relname='point_claims' AND a.attname IN ('tenant_id','collection','document_id','instance_id','backend_namespace','physical_collection','collection_incarnation','point_id','revision_id','generation_id'))
 OR (c.relname='vector_replays' AND a.attname IN ('tenant_id','collection','document_id','content_erased','dense_original_bytes','sparse_original_bytes'))
 OR (c.relname='dispatch_journal' AND a.attname IN ('tenant_id','collection','document_id','state','content_erased','request_original_bytes'))
 WHEN privilege='INSERT' THEN c.relname='purge_erasures'
 WHEN privilege='UPDATE' THEN (c.relname='backend_instances' AND a.attname IN ('epoch'))
 OR (c.relname='document_owners' AND a.attname IN ('backend_epoch'))
 OR (c.relname='documents' AND a.attname IN ('content_unavailable'))
 OR (c.relname='publication_intents' AND a.attname IN ('state','authority_committed','replica_complete','purge_complete'))
 OR (c.relname='document_revisions' AND a.attname IN ('canonical_utf8','content_erased'))
 OR (c.relname='members' AND a.attname IN ('excerpt_utf8','content_erased'))
 OR (c.relname='vector_replays' AND a.attname IN ('dense_blob','sparse_blob','content_erased'))
 OR (c.relname='dispatch_journal' AND a.attname IN ('request_bytes','content_erased'))
 ELSE false END)
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='cragkit_qdrant' AND pg_catalog.has_function_privilege(purger_id,p.oid,'EXECUTE') IS DISTINCT FROM
 (p.oid=function_id OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean)')
 OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.scope_grants()')
 OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.valid_identity_array(text[])'))) THEN
 RAISE EXCEPTION 'managed erasure ACL rejected' USING ERRCODE='22023'; END IF;

 -- Effective caller ACLs must still be the original restricted writer profile.
 IF EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 CROSS JOIN pg_catalog.unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) privilege
 WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND
 pg_catalog.has_table_privilege(caller_id,c.oid,privilege) IS DISTINCT FROM CASE
 WHEN privilege='SELECT' THEN true
 WHEN privilege='INSERT' THEN c.relname IN ('documents','generations','publication_intents','document_owners','dispatch_journal',
 'document_revisions','members','point_claims','vector_replays','dispatch_points','preparations','preparation_attestations')
 WHEN privilege='UPDATE' THEN c.relname IN ('documents','generations','publication_intents','document_owners','dispatch_journal')
 ELSE false END)
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
 JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 CROSS JOIN pg_catalog.unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) privilege
 WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
 AND pg_catalog.has_column_privilege(caller_id,c.oid,a.attnum,privilege) IS DISTINCT FROM CASE
 WHEN privilege='SELECT' THEN true
 WHEN privilege='INSERT' THEN c.relname IN ('documents','generations','publication_intents','document_owners','dispatch_journal',
 'document_revisions','members','point_claims','vector_replays','dispatch_points','preparations','preparation_attestations')
 WHEN privilege='UPDATE' THEN c.relname IN ('documents','generations','publication_intents','document_owners','dispatch_journal')
 OR (c.relname='members' AND a.attname='point_id') OR (c.relname='backend_instances' AND a.attname='epoch')
 ELSE false END)
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='cragkit_qdrant' AND pg_catalog.has_function_privilege(caller_id,p.oid,'EXECUTE') IS DISTINCT FROM
 (p.oid=function_id OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean)')
 OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.scope_grants()') OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.valid_identity_array(text[])')
 OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.writer_scope(text,text,text)')
 OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.bound_stage(text,text,text,text,text)')
 OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.supervisor_instance(text)')
 OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.lock_publication_owner(text,text,text,text,uuid,bigint,boolean)')
 OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.assert_publication(text,text,text,text)'))) THEN
 RAISE EXCEPTION 'managed erasure writer ACL rejected' USING ERRCODE='42501'; END IF;
 IF pg_catalog.current_setting('transaction_isolation')<>'read committed'
 OR p_instance_id IS DISTINCT FROM pg_catalog.current_setting('cragkit_qdrant.backend_instance_id',true)
 OR p_tenant_id IS DISTINCT FROM pg_catalog.current_setting('cragkit_qdrant.tenant_id',true)
 OR p_collection IS DISTINCT FROM pg_catalog.current_setting('cragkit_qdrant.collection',true)
 OR p_document_id IS DISTINCT FROM pg_catalog.current_setting('cragkit_qdrant.writer_document_id',true)
 OR p_purge_intent_id IS DISTINCT FROM pg_catalog.current_setting('cragkit_qdrant.writer_intent_id',true)
 OR p_owner_token IS NULL OR p_owner_token::text IS DISTINCT FROM pg_catalog.current_setting('cragkit_qdrant.writer_owner_token',true)
 OR p_backend_epoch IS NULL OR p_backend_epoch NOT BETWEEN 1 AND 9007199254740991
 OR p_mutation_epoch IS NULL OR p_mutation_epoch NOT BETWEEN 1 AND 9007199254740991
 OR p_policy_id IS DISTINCT FROM 'erase_managed_source_and_replay_v1'
 OR p_inventory_bytes IS NULL OR pg_catalog.octet_length(p_inventory_bytes) NOT BETWEEN 1 AND 262144
 OR p_collection IS NULL OR pg_catalog.octet_length(p_collection) NOT BETWEEN 1 AND 128
 OR pg_catalog.btrim(p_collection,E' \t\r\n\f\013')=''
 OR p_physical_collection IS NULL OR p_physical_collection !~ '^[A-Za-z][A-Za-z0-9_-]{0,63}$' THEN
 RAISE EXCEPTION 'invalid managed erasure input' USING ERRCODE='22023'; END IF;
 FOREACH value IN ARRAY ARRAY[p_instance_id,p_backend_namespace,p_storage_identity,p_supervisor_id,p_collection_incarnation,
 p_tenant_id,p_document_id,p_purge_intent_id,p_authorization_revision] LOOP
 IF value IS NULL OR pg_catalog.octet_length(value) NOT BETWEEN 1 AND 256 OR pg_catalog.btrim(value,E' \t\r\n\f\013')='' THEN
 RAISE EXCEPTION 'invalid managed erasure input' USING ERRCODE='22023'; END IF; END LOOP;
 FOREACH value IN ARRAY ARRAY[p_purge_payload_sha256,p_tombstone_payload_sha256,p_inventory_sha256,p_absence_sha256] LOOP
 IF value IS NULL OR value !~ '^[0-9a-f]{64}$' THEN
 RAISE EXCEPTION 'invalid managed erasure input' USING ERRCODE='22023'; END IF; END LOOP;
 BEGIN
 expected_inventory:=pg_catalog.convert_from(p_inventory_bytes,'UTF8')::jsonb;
 EXCEPTION WHEN character_not_in_repertoire OR invalid_text_representation OR untranslatable_character THEN
 RAISE EXCEPTION 'invalid managed erasure inventory' USING ERRCODE='22023'; END;
 IF pg_catalog.encode(pg_catalog.sha256(p_inventory_bytes),'hex') IS DISTINCT FROM p_inventory_sha256 THEN
 RAISE EXCEPTION 'managed erasure inventory digest mismatch' USING ERRCODE='23514'; END IF;

 -- Lock order matches every native owner operation. Separate reads follow waits.
 PERFORM instance_id FROM cragkit_qdrant.backend_instances WHERE instance_id=p_instance_id FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'managed erasure binding mismatch' USING ERRCODE='23514'; END IF;
 PERFORM owner_token FROM cragkit_qdrant.document_owners WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'managed erasure binding mismatch' USING ERRCODE='23514'; END IF;
 PERFORM document_id FROM cragkit_qdrant.documents WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'managed erasure binding mismatch' USING ERRCODE='23514'; END IF;
 SELECT backend_namespace,storage_identity,supervisor_id,epoch,state,recovery_id INTO backend_row FROM cragkit_qdrant.backend_instances WHERE instance_id=p_instance_id;
 SELECT instance_id,intent_id,owner_token,backend_epoch INTO owner_row FROM cragkit_qdrant.document_owners WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id;
 SELECT authorization_revision,mutation_epoch,tombstoned,content_unavailable INTO document_row FROM cragkit_qdrant.documents WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id;
 SELECT instance_id,action,payload_bytes,payload_sha256,expected_authorization_revision,expected_mutation_epoch,state,authority_committed,replica_complete,purge_complete
 INTO purge_row FROM cragkit_qdrant.publication_intents WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id AND intent_id=p_purge_intent_id;
 IF NOT FOUND OR ROW(purge_row.instance_id,purge_row.action,purge_row.payload_sha256,purge_row.expected_authorization_revision,purge_row.expected_mutation_epoch,purge_row.authority_committed)
 IS DISTINCT FROM ROW(p_instance_id,'purge'::text,p_purge_payload_sha256,p_authorization_revision,p_mutation_epoch,true) THEN
 RAISE EXCEPTION 'managed erasure purge binding mismatch' USING ERRCODE='23514'; END IF;
 SELECT pg_catalog.convert_to('['||pg_catalog.string_agg(pg_catalog.to_json(item)::text,',' ORDER BY ordinal)||']','UTF8')
 INTO canonical_payload FROM pg_catalog.unnest(ARRAY['cragkit.qdrant.intent.v1','purge',p_purge_intent_id,p_tenant_id,p_collection,p_document_id,
 p_tombstone_payload_sha256,p_authorization_revision,p_mutation_epoch::text]) WITH ORDINALITY AS fields(item,ordinal);
 IF purge_row.payload_bytes IS DISTINCT FROM canonical_payload OR pg_catalog.encode(pg_catalog.sha256(canonical_payload),'hex') IS DISTINCT FROM p_purge_payload_sha256 THEN
 RAISE EXCEPTION 'managed erasure purge payload mismatch' USING ERRCODE='23514'; END IF;

 -- The overflow witness is retained: 4097 headers can never certify 4096.
 SELECT count(*) INTO journal_count FROM (SELECT state FROM cragkit_qdrant.dispatch_journal
 WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id LIMIT 4097) headers;
 IF journal_count>4096 OR (SELECT count(*) FROM cragkit_qdrant.generations WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id)>64
 OR (SELECT count(*) FROM cragkit_qdrant.point_claims WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id)>2048 THEN
 RAISE EXCEPTION 'managed erasure resource bound' USING ERRCODE='23514'; END IF;
 SELECT COALESCE(sum(canonical_original_bytes),0) INTO source_bytes FROM cragkit_qdrant.document_revisions WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id;
 SELECT source_bytes+COALESCE(sum(pg_catalog.octet_length(manifest_bytes)),0) INTO source_bytes FROM cragkit_qdrant.publication_intents WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id;
 SELECT COALESCE(sum(dense_original_bytes+COALESCE(sparse_original_bytes,0)),0) INTO replay_bytes FROM cragkit_qdrant.vector_replays WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id;
 SELECT COALESCE(sum(request_original_bytes),0) INTO request_bytes_count FROM cragkit_qdrant.dispatch_journal WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id;
 IF source_bytes>67108864 OR replay_bytes>33554432 OR request_bytes_count>67108864 THEN
 RAISE EXCEPTION 'managed erasure resource bound' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM cragkit_qdrant.point_claims WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id
 AND ROW(instance_id,backend_namespace,physical_collection,collection_incarnation) IS DISTINCT FROM ROW(p_instance_id,p_backend_namespace,p_physical_collection,p_collection_incarnation))
 OR EXISTS(SELECT 1 FROM cragkit_qdrant.point_claims WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id
 GROUP BY revision_id,generation_id HAVING count(*)>64)
 OR EXISTS(SELECT 1 FROM cragkit_qdrant.point_claims c WHERE c.tenant_id=p_tenant_id AND c.collection=p_collection AND c.document_id=p_document_id
 AND NOT EXISTS(SELECT 1 FROM cragkit_qdrant.publication_intents i WHERE i.tenant_id=c.tenant_id AND i.collection=c.collection AND i.document_id=c.document_id
 AND i.revision_id=c.revision_id AND i.generation_id=c.generation_id AND i.action='stage' AND i.instance_id=p_instance_id)) THEN
 RAISE EXCEPTION 'managed erasure claimed inventory mismatch' USING ERRCODE='23514'; END IF;
 SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(grouped.revision_id,grouped.generation_id,
 (SELECT i.manifest_sha256 FROM cragkit_qdrant.publication_intents i WHERE i.tenant_id=p_tenant_id AND i.collection=p_collection AND i.document_id=p_document_id
 AND i.revision_id=grouped.revision_id AND i.generation_id=grouped.generation_id AND i.action='stage'
 ORDER BY pg_catalog.convert_to(i.intent_id,'UTF8') LIMIT 1),grouped.point_ids)
 ORDER BY pg_catalog.convert_to(grouped.revision_id,'UTF8'),pg_catalog.convert_to(grouped.generation_id,'UTF8')),'[]'::jsonb)
 INTO inventory_groups FROM (SELECT revision_id,generation_id,pg_catalog.jsonb_agg(point_id::text ORDER BY pg_catalog.convert_to(point_id::text,'UTF8')) point_ids
 FROM cragkit_qdrant.point_claims WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id GROUP BY revision_id,generation_id) grouped;
 IF expected_inventory IS DISTINCT FROM pg_catalog.jsonb_build_array('cragkit.qdrant.security-inventory.v1',p_backend_namespace,p_physical_collection,p_collection_incarnation,
 p_tenant_id,p_collection,p_document_id,p_instance_id,inventory_groups) THEN
 RAISE EXCEPTION 'managed erasure claimed inventory mismatch' USING ERRCODE='23514'; END IF;
 -- This digest deliberately names PostgreSQL jsonb text, not the SDK compact codec.
 terminal_sha256:=pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.jsonb_build_array(
 'cragkit.qdrant.erasure.pg-jsonb-text.v1',p_instance_id,p_backend_namespace,p_storage_identity,p_supervisor_id,p_backend_epoch::text,
 p_physical_collection,p_collection_incarnation,p_tenant_id,p_collection,p_document_id,p_purge_intent_id,p_purge_payload_sha256,p_owner_token::text,
 p_tombstone_payload_sha256,p_authorization_revision,p_mutation_epoch::text,p_inventory_sha256,p_policy_id,p_absence_sha256,
 source_bytes::text,replay_bytes::text,request_bytes_count::text,journal_count::text)::text,'UTF8')),'hex');
 SELECT * INTO erasure_row FROM cragkit_qdrant.purge_erasures WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id AND purge_intent_id=p_purge_intent_id;
 IF FOUND THEN
 IF erasure_row.erasure_sha256 IS DISTINCT FROM terminal_sha256 OR NOT document_row.content_unavailable
 OR purge_row.state<>'complete' OR NOT(purge_row.authority_committed AND purge_row.replica_complete AND purge_row.purge_complete)
 OR EXISTS(SELECT 1 FROM cragkit_qdrant.document_revisions WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id AND NOT content_erased)
 OR EXISTS(SELECT 1 FROM cragkit_qdrant.members WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id AND NOT content_erased)
 OR EXISTS(SELECT 1 FROM cragkit_qdrant.vector_replays WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id AND NOT content_erased)
 OR EXISTS(SELECT 1 FROM cragkit_qdrant.dispatch_journal WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id AND NOT content_erased) THEN
 RAISE EXCEPTION 'managed erasure historical mismatch' USING ERRCODE='23514'; END IF;
 RETURN true;
 END IF;
 IF ROW(backend_row.backend_namespace,backend_row.storage_identity,backend_row.supervisor_id,backend_row.epoch,backend_row.state,backend_row.recovery_id)
 IS DISTINCT FROM ROW(p_backend_namespace,p_storage_identity,p_supervisor_id,p_backend_epoch,'open'::text,NULL::text)
 OR ROW(owner_row.instance_id,owner_row.intent_id,owner_row.owner_token,owner_row.backend_epoch)
 IS DISTINCT FROM ROW(p_instance_id,p_purge_intent_id,p_owner_token,p_backend_epoch)
 OR ROW(document_row.authorization_revision,document_row.mutation_epoch,document_row.tombstoned,document_row.content_unavailable)
 IS DISTINCT FROM ROW(p_authorization_revision,p_mutation_epoch,true,false)
 OR purge_row.state NOT IN ('authority_committed','writing') OR purge_row.replica_complete OR purge_row.purge_complete
 OR NOT EXISTS(SELECT 1 FROM cragkit_qdrant.publication_intents i WHERE i.tenant_id=p_tenant_id AND i.collection=p_collection AND i.document_id=p_document_id
 AND i.action='tombstone' AND i.instance_id=p_instance_id AND i.payload_sha256=p_tombstone_payload_sha256 AND i.authority_committed
 AND i.expected_mutation_epoch=p_mutation_epoch-1
 AND (pg_catalog.convert_from(i.payload_bytes,'UTF8')::jsonb)->8->>0=p_authorization_revision
 AND (pg_catalog.convert_from(i.payload_bytes,'UTF8')::jsonb)->8->>6='true')
 OR EXISTS(SELECT 1 FROM cragkit_qdrant.dispatch_journal WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id AND state<>'settled') THEN
 RAISE EXCEPTION 'managed erasure current binding mismatch' USING ERRCODE='23514'; END IF;

 UPDATE cragkit_qdrant.document_revisions SET canonical_utf8=NULL,content_erased=true WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id AND NOT content_erased;
 UPDATE cragkit_qdrant.members SET excerpt_utf8=NULL,content_erased=true WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id AND NOT content_erased;
 UPDATE cragkit_qdrant.vector_replays SET dense_blob=NULL,sparse_blob=NULL,content_erased=true WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id AND NOT content_erased;
 UPDATE cragkit_qdrant.dispatch_journal SET request_bytes=NULL,content_erased=true WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id AND NOT content_erased;
 UPDATE cragkit_qdrant.documents SET content_unavailable=true WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id;
 IF EXISTS(SELECT 1 FROM cragkit_qdrant.document_revisions WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id AND NOT content_erased)
 OR EXISTS(SELECT 1 FROM cragkit_qdrant.members WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id AND NOT content_erased)
 OR EXISTS(SELECT 1 FROM cragkit_qdrant.vector_replays WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id AND NOT content_erased)
 OR EXISTS(SELECT 1 FROM cragkit_qdrant.dispatch_journal WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id AND NOT content_erased) THEN
 RAISE EXCEPTION 'managed erasure incomplete' USING ERRCODE='23514'; END IF;
 INSERT INTO cragkit_qdrant.purge_erasures(tenant_id,collection,document_id,purge_intent_id,instance_id,backend_namespace,storage_identity,supervisor_id,backend_epoch,
 physical_collection,collection_incarnation,owner_token,purge_payload_sha256,tombstone_payload_sha256,authorization_revision,mutation_epoch,inventory_sha256,policy_id,absence_sha256,erasure_sha256)
 VALUES(p_tenant_id,p_collection,p_document_id,p_purge_intent_id,p_instance_id,p_backend_namespace,p_storage_identity,p_supervisor_id,p_backend_epoch,
 p_physical_collection,p_collection_incarnation,p_owner_token,p_purge_payload_sha256,p_tombstone_payload_sha256,p_authorization_revision,p_mutation_epoch,p_inventory_sha256,p_policy_id,p_absence_sha256,terminal_sha256);
 UPDATE cragkit_qdrant.publication_intents SET state='complete',authority_committed=true,replica_complete=true,purge_complete=true
 WHERE tenant_id=p_tenant_id AND collection=p_collection AND document_id=p_document_id AND intent_id=p_purge_intent_id;
 RETURN true;
END
$erase$;
REVOKE ALL ON FUNCTION cragkit_qdrant.erase_purged_document(text,text,text,text,bigint,text,text,text,text,text,text,text,uuid,text,text,bigint,bytea,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cragkit_qdrant.erase_purged_document(text,text,text,text,bigint,text,text,text,text,text,text,text,uuid,text,text,bigint,bytea,text,text,text) TO cragkit_qdrant_writer;
ALTER FUNCTION cragkit_qdrant.erase_purged_document(text,text,text,text,bigint,text,text,text,text,text,text,text,uuid,text,text,bigint,bytea,text,text,text) OWNER TO cragkit_qdrant_purger;
REVOKE CREATE ON SCHEMA cragkit_qdrant FROM cragkit_qdrant_purger;
