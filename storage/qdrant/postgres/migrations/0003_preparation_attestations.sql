-- Explicit additive current-epoch attestations. The administrator records this
-- artifact's actual checksum in schema_migrations in the same transaction.
DO $migration$
BEGIN
    IF current_setting('server_version_num')::integer NOT BETWEEN 170000 AND 179999 THEN
        RAISE EXCEPTION 'unsupported attestation database profile' USING ERRCODE = '22023';
    END IF;
    IF (SELECT count(*) FROM cragkit_qdrant.schema_migrations) <> 2 OR NOT EXISTS (
        SELECT 1 FROM cragkit_qdrant.schema_migrations WHERE version = '0001_authority'
            AND checksum_sha256 = '3d75cd46eb32a10864f1097a7494b01f9759150911a7cd9a1e6aab60105c1f1a'
    ) OR NOT EXISTS (
        SELECT 1 FROM cragkit_qdrant.schema_migrations WHERE version = '0002_publication'
            AND checksum_sha256 = '386fe01d0d03e35ac35c21bce598b21bff2c5ad510e9cdf0a6fbe56f359b6661'
    ) THEN
        RAISE EXCEPTION 'unsupported publication history' USING ERRCODE = '22023';
    END IF;
END
$migration$;

CREATE TABLE cragkit_qdrant.preparation_attestations (
    tenant_id cragkit_qdrant.identity_text NOT NULL,
    collection cragkit_qdrant.collection_text NOT NULL,
    document_id cragkit_qdrant.identity_text NOT NULL,
    intent_id cragkit_qdrant.identity_text NOT NULL,
    instance_id cragkit_qdrant.identity_text NOT NULL REFERENCES cragkit_qdrant.backend_instances,
    owner_token uuid NOT NULL,
    backend_epoch cragkit_qdrant.safe_count NOT NULL CHECK (backend_epoch > 0),
    authorization_revision cragkit_qdrant.identity_text NOT NULL,
    mutation_epoch cragkit_qdrant.safe_count NOT NULL,
    manifest_sha256 cragkit_qdrant.sha256_hex NOT NULL,
    expected_active_generation_id cragkit_qdrant.identity_text,
    credential_generation cragkit_qdrant.identity_text NOT NULL,
    verification_id cragkit_qdrant.identity_text NOT NULL,
    readback_sha256 cragkit_qdrant.sha256_hex NOT NULL,
    PRIMARY KEY (tenant_id, collection, document_id, intent_id, backend_epoch, owner_token),
    FOREIGN KEY (tenant_id, collection, document_id, intent_id)
        REFERENCES cragkit_qdrant.preparations (tenant_id, collection, document_id, intent_id)
);
ALTER TABLE cragkit_qdrant.preparation_attestations ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit_qdrant.preparation_attestations FORCE ROW LEVEL SECURITY;
CREATE POLICY writer_attestation_read ON cragkit_qdrant.preparation_attestations
    FOR SELECT TO cragkit_qdrant_writer USING (
        cragkit_qdrant.writer_scope(tenant_id,collection,document_id)
        AND intent_id = current_setting('cragkit_qdrant.writer_intent_id',true)
        AND instance_id = current_setting('cragkit_qdrant.backend_instance_id',true));
CREATE POLICY writer_attestation_insert ON cragkit_qdrant.preparation_attestations
    FOR INSERT TO cragkit_qdrant_writer WITH CHECK (
        cragkit_qdrant.writer_scope(tenant_id,collection,document_id)
        AND intent_id = current_setting('cragkit_qdrant.writer_intent_id',true)
        AND instance_id = current_setting('cragkit_qdrant.backend_instance_id',true));
REVOKE ALL ON cragkit_qdrant.preparation_attestations FROM PUBLIC, cragkit_qdrant_writer, cragkit_qdrant_supervisor;
GRANT SELECT, INSERT ON cragkit_qdrant.preparation_attestations TO cragkit_qdrant_writer;

CREATE FUNCTION cragkit_qdrant.guard_preparation_attestation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
DECLARE
    owner_row record;
    document_row record;
    intent_row record;
    original record;
    generation_row record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'immutable preparation attestation' USING ERRCODE = '23514';
    END IF;
    PERFORM cragkit_qdrant.lock_publication_owner(NEW.tenant_id,NEW.collection,NEW.document_id,
        NEW.instance_id,NEW.owner_token,NEW.backend_epoch,false);
    -- Extend the shared backend -> owner lock order with the document lock.
    -- Every authoritative value below is reread after all lock waits.
    PERFORM 1 FROM cragkit_qdrant.documents WHERE tenant_id = NEW.tenant_id
        AND collection = NEW.collection AND document_id = NEW.document_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'attestation document absent' USING ERRCODE = '23514';
    END IF;
    SELECT instance_id,owner_token,backend_epoch,intent_id INTO owner_row
    FROM cragkit_qdrant.document_owners WHERE tenant_id = NEW.tenant_id
        AND collection = NEW.collection AND document_id = NEW.document_id;
    SELECT active_generation_id,authorization_revision,mutation_epoch,tombstoned INTO document_row
    FROM cragkit_qdrant.documents WHERE tenant_id = NEW.tenant_id
        AND collection = NEW.collection AND document_id = NEW.document_id;
    SELECT action,state,manifest_sha256,expected_active_generation_id,expected_authorization_revision,
        expected_mutation_epoch,revision_id,generation_id,instance_id
    INTO intent_row FROM cragkit_qdrant.publication_intents WHERE tenant_id = NEW.tenant_id
        AND collection = NEW.collection AND document_id = NEW.document_id AND intent_id = NEW.intent_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'attestation intent absent' USING ERRCODE = '23514';
    END IF;
    SELECT instance_id,owner_token,backend_epoch,authorization_revision,mutation_epoch,manifest_sha256
    INTO original FROM cragkit_qdrant.preparations WHERE tenant_id = NEW.tenant_id
        AND collection = NEW.collection AND document_id = NEW.document_id AND intent_id = NEW.intent_id;
    IF NOT FOUND OR cragkit_qdrant.writer_scope(NEW.tenant_id,NEW.collection,NEW.document_id) IS DISTINCT FROM true
        OR NEW.intent_id IS DISTINCT FROM current_setting('cragkit_qdrant.writer_intent_id',true)
        OR NEW.instance_id IS DISTINCT FROM current_setting('cragkit_qdrant.backend_instance_id',true)
        OR NEW.owner_token::text IS DISTINCT FROM current_setting('cragkit_qdrant.writer_owner_token',true)
        OR ROW(owner_row.instance_id,owner_row.owner_token,owner_row.backend_epoch,owner_row.intent_id)
            IS DISTINCT FROM ROW(NEW.instance_id,NEW.owner_token,NEW.backend_epoch,NEW.intent_id)
        OR intent_row.action <> 'stage' OR intent_row.state <> 'prepared'
        OR document_row.tombstoned OR NEW.backend_epoch <= original.backend_epoch
        OR ROW(original.instance_id,original.manifest_sha256,original.authorization_revision,original.mutation_epoch)
            IS DISTINCT FROM ROW(NEW.instance_id,NEW.manifest_sha256,NEW.authorization_revision,NEW.mutation_epoch)
        OR ROW(intent_row.instance_id,intent_row.manifest_sha256,intent_row.expected_authorization_revision,
            intent_row.expected_mutation_epoch,intent_row.expected_active_generation_id)
            IS DISTINCT FROM ROW(NEW.instance_id,NEW.manifest_sha256,NEW.authorization_revision,
                NEW.mutation_epoch,NEW.expected_active_generation_id)
        OR ROW(document_row.active_generation_id,document_row.authorization_revision,document_row.mutation_epoch)
            IS DISTINCT FROM ROW(NEW.expected_active_generation_id,NEW.authorization_revision,NEW.mutation_epoch)
        OR EXISTS (SELECT 1 FROM cragkit_qdrant.dispatch_journal WHERE tenant_id = NEW.tenant_id
            AND collection = NEW.collection AND document_id = NEW.document_id AND state <> 'settled') THEN
        RAISE EXCEPTION 'attestation intent or current fence mismatch' USING ERRCODE = '23514';
    END IF;
    SELECT expected_member_count,backend_namespace,physical_collection,collection_incarnation,
        dense_profile,sparse_profile INTO generation_row FROM cragkit_qdrant.generations
    WHERE tenant_id = NEW.tenant_id AND collection = NEW.collection AND document_id = NEW.document_id
        AND revision_id = intent_row.revision_id AND generation_id = intent_row.generation_id;
    IF NOT FOUND OR generation_row.expected_member_count NOT BETWEEN 1 AND 64
        OR generation_row.expected_member_count <> (SELECT count(*) FROM cragkit_qdrant.members
            WHERE tenant_id = NEW.tenant_id AND collection = NEW.collection AND document_id = NEW.document_id
                AND revision_id = intent_row.revision_id AND generation_id = intent_row.generation_id)
        OR generation_row.expected_member_count <> (SELECT count(*) FROM cragkit_qdrant.point_claims
            WHERE tenant_id = NEW.tenant_id AND collection = NEW.collection AND document_id = NEW.document_id
                AND revision_id = intent_row.revision_id AND generation_id = intent_row.generation_id)
        OR generation_row.expected_member_count <> (SELECT count(*) FROM cragkit_qdrant.vector_replays
            WHERE tenant_id = NEW.tenant_id AND collection = NEW.collection AND document_id = NEW.document_id
                AND revision_id = intent_row.revision_id AND generation_id = intent_row.generation_id)
        OR EXISTS (SELECT 1 FROM cragkit_qdrant.members AS member
            LEFT JOIN cragkit_qdrant.point_claims AS claim
                USING (tenant_id,collection,document_id,revision_id,generation_id,chunk_id)
            LEFT JOIN cragkit_qdrant.vector_replays AS replay
                ON replay.tenant_id = member.tenant_id AND replay.collection = member.collection
                AND replay.document_id = member.document_id AND replay.revision_id = member.revision_id
                AND replay.generation_id = member.generation_id AND replay.chunk_id = member.chunk_id
            WHERE member.tenant_id = NEW.tenant_id AND member.collection = NEW.collection
                AND member.document_id = NEW.document_id AND member.revision_id = intent_row.revision_id
                AND member.generation_id = intent_row.generation_id
                AND (claim.point_id IS NULL OR replay.point_id IS NULL
                    OR ROW(claim.instance_id,claim.point_id,claim.source_sha256,claim.text_sha256,
                        claim.start_byte,claim.end_byte,claim.backend_namespace,claim.physical_collection,
                        claim.collection_incarnation,claim.dense_profile,claim.sparse_profile)
                        IS DISTINCT FROM ROW(NEW.instance_id,member.point_id,member.source_sha256,
                            member.text_sha256,member.start_byte,member.end_byte,generation_row.backend_namespace,
                            generation_row.physical_collection,generation_row.collection_incarnation,
                            generation_row.dense_profile,generation_row.sparse_profile)
                    OR ROW(replay.point_id,replay.backend_namespace,replay.physical_collection,replay.collection_incarnation)
                        IS DISTINCT FROM ROW(member.point_id,generation_row.backend_namespace,
                            generation_row.physical_collection,generation_row.collection_incarnation))) THEN
        RAISE EXCEPTION 'incomplete attestation membership' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER publication_preparation_attestation_guard
    BEFORE INSERT OR UPDATE OR DELETE ON cragkit_qdrant.preparation_attestations
    FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.guard_preparation_attestation();
REVOKE ALL ON FUNCTION cragkit_qdrant.guard_preparation_attestation()
    FROM PUBLIC, cragkit_qdrant_writer, cragkit_qdrant_supervisor;

CREATE OR REPLACE FUNCTION cragkit_qdrant.assert_publication(row_tenant text,row_collection text,row_document text,
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
    PERFORM 1 FROM cragkit_qdrant.documents WHERE tenant_id = row_tenant
        AND collection = row_collection AND document_id = row_document FOR UPDATE;
    -- Fresh reads follow all three locks; the first owner lookup only locates keys.
    SELECT instance_id,owner_token,backend_epoch,intent_id INTO owner_row FROM cragkit_qdrant.document_owners
    WHERE tenant_id = row_tenant AND collection = row_collection AND document_id = row_document;
    SELECT active_generation_id,authorization_revision,mutation_epoch,tombstoned INTO document_row
    FROM cragkit_qdrant.documents WHERE tenant_id = row_tenant AND collection = row_collection AND document_id = row_document;
    SELECT intent_id,action,state,manifest_sha256,expected_active_generation_id,expected_authorization_revision,
        expected_mutation_epoch,generation_id,authority_committed,replica_complete,instance_id INTO intent_row
    FROM cragkit_qdrant.publication_intents WHERE tenant_id = row_tenant AND collection = row_collection
        AND document_id = row_document AND intent_id = owner_row.intent_id;
    -- Exactly one original preparation anchors both alternatives. The attestation
    -- key is the current owner/epoch, never an ordered/latest row selection.
    SELECT selected.owner_token,selected.backend_epoch,selected.authorization_revision,
        selected.mutation_epoch,selected.manifest_sha256,selected.instance_id INTO prepared
    FROM cragkit_qdrant.preparations AS original
    CROSS JOIN LATERAL (
        SELECT original.owner_token,original.backend_epoch,original.authorization_revision,
            original.mutation_epoch,original.manifest_sha256,original.instance_id
        WHERE ROW(original.owner_token,original.backend_epoch,original.instance_id,original.manifest_sha256,
            original.authorization_revision,original.mutation_epoch)
            IS NOT DISTINCT FROM ROW(owner_row.owner_token,owner_row.backend_epoch,owner_row.instance_id,
                intent_row.manifest_sha256,document_row.authorization_revision,document_row.mutation_epoch)
        UNION ALL
        SELECT attestation.owner_token,attestation.backend_epoch,attestation.authorization_revision,
            attestation.mutation_epoch,attestation.manifest_sha256,attestation.instance_id
        FROM cragkit_qdrant.preparation_attestations AS attestation
        WHERE attestation.tenant_id = row_tenant AND attestation.collection = row_collection
            AND attestation.document_id = row_document AND attestation.intent_id = owner_row.intent_id
            AND attestation.backend_epoch = owner_row.backend_epoch AND attestation.owner_token = owner_row.owner_token
            AND attestation.backend_epoch > original.backend_epoch
            AND attestation.expected_active_generation_id IS NOT DISTINCT FROM intent_row.expected_active_generation_id
            AND ROW(attestation.instance_id,attestation.manifest_sha256,attestation.authorization_revision,attestation.mutation_epoch)
                IS NOT DISTINCT FROM ROW(original.instance_id,original.manifest_sha256,original.authorization_revision,original.mutation_epoch)
    ) AS selected
    WHERE original.tenant_id = row_tenant AND original.collection = row_collection
        AND original.document_id = row_document AND original.intent_id = owner_row.intent_id;
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
