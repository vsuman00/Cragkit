-- Source-only PostgreSQL 17 authority. The explicit administrator wrapper owns
-- transaction boundaries and records this file's actual SHA-256 in history.
DO $migration$
BEGIN
    IF current_setting('server_version_num')::integer < 170000
        OR current_setting('server_version_num')::integer >= 180000
        OR current_setting('server_encoding') <> 'UTF8' THEN
        RAISE EXCEPTION 'unsupported authority database profile' USING ERRCODE = '22023';
    END IF;
END
$migration$;

-- No IF NOT EXISTS: a preexisting namespace is a compatibility/ownership decision.
CREATE SCHEMA cragkit_qdrant;
REVOKE ALL ON SCHEMA cragkit_qdrant FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA cragkit_qdrant REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA cragkit_qdrant REVOKE ALL ON FUNCTIONS FROM PUBLIC;

CREATE DOMAIN cragkit_qdrant.identity_text AS text COLLATE pg_catalog."C"
    CHECK (octet_length(VALUE) BETWEEN 1 AND 256
        AND btrim(VALUE, E' \t\r\n\f\013') <> '');
CREATE DOMAIN cragkit_qdrant.collection_text AS text COLLATE pg_catalog."C"
    CHECK (octet_length(VALUE) BETWEEN 1 AND 128
        AND btrim(VALUE, E' \t\r\n\f\013') <> '');
CREATE DOMAIN cragkit_qdrant.sha256_hex AS text COLLATE pg_catalog."C"
    CHECK (VALUE ~ '^[0-9a-f]{64}$');
CREATE DOMAIN cragkit_qdrant.safe_count AS bigint
    CHECK (VALUE BETWEEN 0 AND 9007199254740991);

CREATE TABLE cragkit_qdrant.schema_migrations (
    version cragkit_qdrant.identity_text PRIMARY KEY,
    checksum_sha256 cragkit_qdrant.sha256_hex NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE FUNCTION cragkit_qdrant.valid_identity_array(value text[]) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $function$
    SELECT value IS NOT NULL AND cardinality(value) <= 64
        AND (cardinality(value) = 0 OR array_ndims(value) = 1)
        AND NOT EXISTS (
            SELECT 1 FROM unnest(value) AS member
            WHERE member IS NULL OR octet_length(member) NOT BETWEEN 1 AND 256
                OR btrim(member, E' \t\r\n\f\013') = ''
        )
$function$;

CREATE TABLE cragkit_qdrant.documents (
    tenant_id cragkit_qdrant.identity_text NOT NULL,
    collection cragkit_qdrant.collection_text NOT NULL,
    document_id cragkit_qdrant.identity_text NOT NULL,
    active_generation_id cragkit_qdrant.identity_text,
    principal_ids text[] COLLATE pg_catalog."C" NOT NULL DEFAULT '{}'::text[] CHECK (cragkit_qdrant.valid_identity_array(principal_ids)),
    grant_ids text[] COLLATE pg_catalog."C" NOT NULL DEFAULT '{}'::text[] CHECK (cragkit_qdrant.valid_identity_array(grant_ids)),
    authorization_revision cragkit_qdrant.identity_text NOT NULL,
    mutation_epoch cragkit_qdrant.safe_count NOT NULL DEFAULT 0,
    language text COLLATE pg_catalog."C" CHECK (language IS NULL OR octet_length(language) <= 1024),
    kind text COLLATE pg_catalog."C" CHECK (kind IS NULL OR octet_length(kind) <= 1024),
    tag text COLLATE pg_catalog."C" CHECK (tag IS NULL OR octet_length(tag) <= 1024),
    tombstoned boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, collection, document_id)
);

CREATE TABLE cragkit_qdrant.document_revisions (
    tenant_id cragkit_qdrant.identity_text NOT NULL,
    collection cragkit_qdrant.collection_text NOT NULL,
    document_id cragkit_qdrant.identity_text NOT NULL,
    revision_id cragkit_qdrant.identity_text NOT NULL,
    canonical_utf8 bytea NOT NULL CHECK (octet_length(canonical_utf8) BETWEEN 1 AND 16777216),
    source_sha256 cragkit_qdrant.sha256_hex NOT NULL,
    source_locator text COLLATE pg_catalog."C" NOT NULL CHECK (octet_length(source_locator) BETWEEN 1 AND 256
        AND btrim(source_locator, E' \t\r\n\f\013') <> ''),
    parser_id cragkit_qdrant.identity_text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, collection, document_id, revision_id),
    FOREIGN KEY (tenant_id, collection, document_id)
        REFERENCES cragkit_qdrant.documents (tenant_id, collection, document_id) ON DELETE CASCADE,
    CHECK (source_sha256 = encode(sha256(canonical_utf8), 'hex'))
);

CREATE TABLE cragkit_qdrant.generations (
    tenant_id cragkit_qdrant.identity_text NOT NULL,
    collection cragkit_qdrant.collection_text NOT NULL,
    document_id cragkit_qdrant.identity_text NOT NULL,
    revision_id cragkit_qdrant.identity_text NOT NULL,
    generation_id cragkit_qdrant.identity_text NOT NULL,
    backend_namespace cragkit_qdrant.identity_text NOT NULL,
    physical_collection text COLLATE pg_catalog."C" NOT NULL CHECK (physical_collection ~ '^[A-Za-z][A-Za-z0-9_-]{0,63}$'),
    collection_incarnation cragkit_qdrant.identity_text NOT NULL,
    chunker_profile cragkit_qdrant.identity_text NOT NULL,
    dense_profile_id cragkit_qdrant.identity_text NOT NULL,
    sparse_profile_id text COLLATE pg_catalog."C" NOT NULL,
    dense_profile jsonb NOT NULL,
    sparse_profile jsonb,
    expected_member_count integer NOT NULL CHECK (expected_member_count > 0),
    published boolean NOT NULL DEFAULT false,
    ever_published boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, collection, document_id, generation_id),
    UNIQUE (tenant_id, collection, document_id, revision_id, generation_id),
    FOREIGN KEY (tenant_id, collection, document_id, revision_id)
        REFERENCES cragkit_qdrant.document_revisions (tenant_id, collection, document_id, revision_id) ON DELETE CASCADE,
    CHECK (dense_profile IN (
        '{"profile_id":"fake_embedding_1536_v1","provider":"fake","model":"fake_embedding_model_v1","dimensions":1536,"tokenizer":"fake-byte-v1","normalization":"l2"}'::jsonb,
        '{"profile_id":"openai_te3small_1536_r1","provider":"openai","model":"text-embedding-3-small","dimensions":1536,"tokenizer":"cl100k_base","normalization":"l2"}'::jsonb)),
    CHECK (dense_profile_id = dense_profile->>'profile_id'),
    CHECK ((sparse_profile IS NULL AND sparse_profile_id = '') OR (
        sparse_profile IS NOT NULL AND dense_profile_id = 'fake_embedding_1536_v1' AND sparse_profile_id = 'fake_manual_sparse_v1'
        AND sparse_profile = '{"profile_id":"fake_manual_sparse_v1","encoder":"caller_supplied_fixture","model":"none","revision":"1","vocabulary":"fixture_uint32_v1","preprocessing":"none","weighting":"caller_supplied","corpus_statistics_revision":"none"}'::jsonb)),
    CHECK (NOT published OR ever_published)
);

ALTER TABLE cragkit_qdrant.documents ADD CONSTRAINT documents_active_generation_fk
    FOREIGN KEY (tenant_id, collection, document_id, active_generation_id)
    REFERENCES cragkit_qdrant.generations (tenant_id, collection, document_id, generation_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE cragkit_qdrant.members (
    tenant_id cragkit_qdrant.identity_text NOT NULL,
    collection cragkit_qdrant.collection_text NOT NULL,
    document_id cragkit_qdrant.identity_text NOT NULL,
    revision_id cragkit_qdrant.identity_text NOT NULL,
    generation_id cragkit_qdrant.identity_text NOT NULL,
    chunk_id cragkit_qdrant.identity_text NOT NULL,
    point_id uuid NOT NULL,
    start_byte cragkit_qdrant.safe_count NOT NULL,
    end_byte cragkit_qdrant.safe_count NOT NULL,
    source_sha256 cragkit_qdrant.sha256_hex NOT NULL,
    text_sha256 cragkit_qdrant.sha256_hex NOT NULL,
    excerpt_utf8 bytea NOT NULL CHECK (octet_length(excerpt_utf8) BETWEEN 1 AND 32768),
    PRIMARY KEY (tenant_id, collection, document_id, revision_id, generation_id, chunk_id),
    UNIQUE (tenant_id, collection, document_id, generation_id, point_id),
    FOREIGN KEY (tenant_id, collection, document_id, revision_id, generation_id)
        REFERENCES cragkit_qdrant.generations (tenant_id, collection, document_id, revision_id, generation_id)
        ON DELETE CASCADE,
    CHECK (end_byte > start_byte AND end_byte - start_byte = octet_length(excerpt_utf8)),
    CHECK (text_sha256 = encode(sha256(excerpt_utf8), 'hex')),
    CHECK ((get_byte(uuid_send(point_id), 6) >> 4) = 5
        AND (get_byte(uuid_send(point_id), 8) & 192) = 128)
);

CREATE FUNCTION cragkit_qdrant.reject_immutable_update() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
BEGIN
    RAISE EXCEPTION 'immutable authority row' USING ERRCODE = '23514';
END
$function$;
CREATE TRIGGER immutable_revision BEFORE UPDATE ON cragkit_qdrant.document_revisions
    FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.reject_immutable_update();
CREATE TRIGGER immutable_member BEFORE UPDATE ON cragkit_qdrant.members
    FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.reject_immutable_update();

CREATE FUNCTION cragkit_qdrant.guard_document_update() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
BEGIN
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
CREATE TRIGGER document_authority_update BEFORE UPDATE ON cragkit_qdrant.documents
    FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.guard_document_update();

CREATE FUNCTION cragkit_qdrant.guard_generation_update() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
BEGIN
    IF (to_jsonb(NEW) - ARRAY['published','ever_published'])
        IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['published','ever_published'])
        OR (OLD.ever_published AND NOT NEW.ever_published) THEN
        RAISE EXCEPTION 'immutable generation identity or publication history' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER generation_identity_update BEFORE UPDATE ON cragkit_qdrant.generations
    FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.guard_generation_update();

CREATE FUNCTION cragkit_qdrant.validate_member_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
DECLARE
    canonical_bytes bytea;
    canonical_digest text;
    published_before boolean;
BEGIN
    SELECT revision.canonical_utf8, revision.source_sha256, generation.ever_published
        INTO canonical_bytes, canonical_digest, published_before
    FROM cragkit_qdrant.document_revisions AS revision
    JOIN cragkit_qdrant.generations AS generation
        USING (tenant_id, collection, document_id, revision_id)
    WHERE generation.tenant_id = NEW.tenant_id AND generation.collection = NEW.collection
        AND generation.document_id = NEW.document_id AND generation.revision_id = NEW.revision_id
        AND generation.generation_id = NEW.generation_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'authority member parent is absent' USING ERRCODE = '23503';
    END IF;
    IF published_before OR NEW.start_byte IS NULL OR NEW.end_byte IS NULL
        OR NEW.start_byte < 0 OR NEW.end_byte <= NEW.start_byte
        OR NEW.end_byte > octet_length(canonical_bytes)
        OR NEW.source_sha256 IS DISTINCT FROM canonical_digest THEN
        RAISE EXCEPTION 'authority member identity or span is invalid' USING ERRCODE = '23514';
    END IF;
    IF substring(canonical_bytes FROM NEW.start_byte::integer + 1
            FOR (NEW.end_byte - NEW.start_byte)::integer) IS DISTINCT FROM NEW.excerpt_utf8 THEN
        RAISE EXCEPTION 'authority member differs from canonical bytes' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER canonical_member_insert BEFORE INSERT ON cragkit_qdrant.members
    FOR EACH ROW EXECUTE FUNCTION cragkit_qdrant.validate_member_insert();

-- Session settings are bound by trusted application code in a short transaction.
-- These functions neither authenticate arbitrary callers nor expose source bytes.
CREATE FUNCTION cragkit_qdrant.scope_grants() RETURNS text[]
LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $function$
DECLARE
    encoded text;
    parsed jsonb;
    result text[];
BEGIN
    encoded := current_setting('cragkit_qdrant.grant_ids', true);
    IF encoded IS NULL OR octet_length(encoded) > 131072 THEN RETURN NULL; END IF;
    BEGIN
        parsed := encoded::jsonb;
    EXCEPTION WHEN invalid_text_representation OR untranslatable_character
        OR numeric_value_out_of_range OR program_limit_exceeded THEN
        RETURN NULL;
    END;
    IF jsonb_typeof(parsed) <> 'array' THEN RETURN NULL; END IF;
    IF jsonb_array_length(parsed) > 64 THEN RETURN NULL; END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(parsed) AS item WHERE jsonb_typeof(item) <> 'string') THEN
        RETURN NULL;
    END IF;
    SELECT COALESCE(array_agg(value), '{}'::text[]) INTO result FROM jsonb_array_elements_text(parsed);
    IF NOT cragkit_qdrant.valid_identity_array(result) THEN RETURN NULL; END IF;
    RETURN result;
END
$function$;

CREATE FUNCTION cragkit_qdrant.scope_visible(
    row_tenant text, row_collection text, row_principals text[], row_grants text[],
    row_authorization_revision text, row_tombstoned boolean) RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog AS $function$
    SELECT NOT row_tombstoned
        AND row_tenant = current_setting('cragkit_qdrant.tenant_id', true)
        AND row_collection = current_setting('cragkit_qdrant.collection', true)
        AND row_authorization_revision = current_setting('cragkit_qdrant.authorization_revision', true)
        AND octet_length(current_setting('cragkit_qdrant.principal_id', true)) BETWEEN 1 AND 256
        AND btrim(current_setting('cragkit_qdrant.principal_id', true), E' \t\r\n\f\013') <> ''
        AND cragkit_qdrant.scope_grants() IS NOT NULL
        AND (current_setting('cragkit_qdrant.principal_id', true) = ANY(row_principals)
            OR row_grants && cragkit_qdrant.scope_grants())
$function$;

ALTER TABLE cragkit_qdrant.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit_qdrant.documents FORCE ROW LEVEL SECURITY;
ALTER TABLE cragkit_qdrant.document_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit_qdrant.document_revisions FORCE ROW LEVEL SECURITY;
ALTER TABLE cragkit_qdrant.generations ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit_qdrant.generations FORCE ROW LEVEL SECURITY;
ALTER TABLE cragkit_qdrant.members ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit_qdrant.members FORCE ROW LEVEL SECURITY;

CREATE POLICY scoped_document_read ON cragkit_qdrant.documents FOR SELECT TO PUBLIC
    USING (cragkit_qdrant.scope_visible(tenant_id, collection, principal_ids, grant_ids,
                                      authorization_revision, tombstoned));
CREATE POLICY scoped_generation_read ON cragkit_qdrant.generations FOR SELECT TO PUBLIC
    USING (ever_published AND EXISTS (
        SELECT 1 FROM cragkit_qdrant.documents AS document
        WHERE document.tenant_id = generations.tenant_id AND document.collection = generations.collection
            AND document.document_id = generations.document_id));
CREATE POLICY scoped_revision_read ON cragkit_qdrant.document_revisions FOR SELECT TO PUBLIC
    USING (EXISTS (
        SELECT 1 FROM cragkit_qdrant.generations AS generation
        WHERE generation.tenant_id = document_revisions.tenant_id
            AND generation.collection = document_revisions.collection
            AND generation.document_id = document_revisions.document_id
            AND generation.revision_id = document_revisions.revision_id AND generation.ever_published));
CREATE POLICY scoped_member_read ON cragkit_qdrant.members FOR SELECT TO PUBLIC
    USING (EXISTS (
        SELECT 1 FROM cragkit_qdrant.generations AS generation
        WHERE generation.tenant_id = members.tenant_id AND generation.collection = members.collection
            AND generation.document_id = members.document_id AND generation.revision_id = members.revision_id
            AND generation.generation_id = members.generation_id AND generation.ever_published));

REVOKE ALL ON ALL TABLES IN SCHEMA cragkit_qdrant FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA cragkit_qdrant FROM PUBLIC;
