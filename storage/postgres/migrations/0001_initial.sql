DO $migration$
BEGIN
    IF current_setting('server_encoding') <> 'UTF8' THEN
        RAISE EXCEPTION 'cragkit requires a UTF8 database' USING ERRCODE = '22023';
    END IF;
END
$migration$;

CREATE SCHEMA IF NOT EXISTS cragkit;
REVOKE ALL ON SCHEMA cragkit FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA cragkit REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA cragkit REVOKE ALL ON FUNCTIONS FROM PUBLIC;

CREATE DOMAIN cragkit.identity_text AS text COLLATE pg_catalog."C"
    CHECK (octet_length(VALUE) BETWEEN 1 AND 256
        AND btrim(VALUE, E' \t\r\n\f\013') <> '');
CREATE DOMAIN cragkit.collection_text AS text COLLATE pg_catalog."C"
    CHECK (octet_length(VALUE) BETWEEN 1 AND 128
        AND btrim(VALUE, E' \t\r\n\f\013') <> '');
CREATE DOMAIN cragkit.sha256_hex AS text COLLATE pg_catalog."C"
    CHECK (octet_length(VALUE) = 64 AND VALUE !~ '[^0-9a-f]');
CREATE DOMAIN cragkit.safe_count AS bigint
    CHECK (VALUE BETWEEN 0 AND 9007199254740991);

CREATE TABLE cragkit.collections (
    tenant_id cragkit.identity_text NOT NULL,
    collection_id cragkit.collection_text NOT NULL,
    schema_version text NOT NULL DEFAULT '0.1' CHECK (schema_version = '0.1'),
    active_profile cragkit.identity_text NOT NULL DEFAULT 'native_fts.v1',
    policy_metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(policy_metadata) = 'object'),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, collection_id)
);

CREATE TABLE cragkit.documents (
    tenant_id cragkit.identity_text NOT NULL,
    collection_id cragkit.collection_text NOT NULL,
    document_id cragkit.identity_text NOT NULL,
    active_generation_id cragkit.identity_text,
    tombstoned boolean NOT NULL DEFAULT false,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    authorization_revision cragkit.identity_text NOT NULL DEFAULT '0',
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, collection_id, document_id),
    FOREIGN KEY (tenant_id, collection_id)
        REFERENCES cragkit.collections (tenant_id, collection_id) ON DELETE CASCADE
);

CREATE TABLE cragkit.document_revisions (
    tenant_id cragkit.identity_text NOT NULL,
    collection_id cragkit.collection_text NOT NULL,
    document_id cragkit.identity_text NOT NULL,
    revision_id cragkit.identity_text NOT NULL,
    source_sha256 cragkit.sha256_hex NOT NULL,
    source_locator cragkit.identity_text NOT NULL,
    canonical_text text NOT NULL CHECK (octet_length(canonical_text) > 0),
    canonical_sha256 cragkit.sha256_hex NOT NULL,
    parser_id cragkit.identity_text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, collection_id, document_id, revision_id),
    FOREIGN KEY (tenant_id, collection_id, document_id)
        REFERENCES cragkit.documents (tenant_id, collection_id, document_id) ON DELETE CASCADE,
    CHECK (canonical_sha256 = encode(sha256(convert_to(canonical_text, 'UTF8')), 'hex'))
);

CREATE FUNCTION cragkit.reject_revision_update() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
BEGIN
    RAISE EXCEPTION 'cragkit revisions are immutable' USING ERRCODE = '23514';
END
$function$;
CREATE TRIGGER immutable_document_revision
    BEFORE UPDATE ON cragkit.document_revisions
    FOR EACH ROW EXECUTE FUNCTION cragkit.reject_revision_update();

CREATE TABLE cragkit.index_generations (
    tenant_id cragkit.identity_text NOT NULL,
    collection_id cragkit.collection_text NOT NULL,
    document_id cragkit.identity_text NOT NULL,
    revision_id cragkit.identity_text NOT NULL,
    generation_id cragkit.identity_text NOT NULL,
    chunker_profile cragkit.identity_text NOT NULL,
    lexical_profile cragkit.identity_text NOT NULL,
    embedding_profile cragkit.identity_text,
    status text NOT NULL DEFAULT 'staging' CHECK (status IN ('staging', 'ready', 'failed')),
    expected_chunk_count integer NOT NULL CHECK (expected_chunk_count > 0),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, collection_id, document_id, generation_id),
    UNIQUE (tenant_id, collection_id, document_id, revision_id, generation_id),
    FOREIGN KEY (tenant_id, collection_id, document_id, revision_id)
        REFERENCES cragkit.document_revisions (tenant_id, collection_id, document_id, revision_id)
        ON DELETE CASCADE
);
ALTER TABLE cragkit.documents ADD CONSTRAINT documents_active_generation_fk
    FOREIGN KEY (tenant_id, collection_id, document_id, active_generation_id)
    REFERENCES cragkit.index_generations (tenant_id, collection_id, document_id, generation_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE cragkit.chunks (
    tenant_id cragkit.identity_text NOT NULL,
    collection_id cragkit.collection_text NOT NULL,
    document_id cragkit.identity_text NOT NULL,
    revision_id cragkit.identity_text NOT NULL,
    generation_id cragkit.identity_text NOT NULL,
    chunk_id cragkit.identity_text NOT NULL,
    parent_chunk_id cragkit.identity_text,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    start_byte cragkit.safe_count NOT NULL,
    end_byte cragkit.safe_count NOT NULL,
    text text NOT NULL CHECK (octet_length(text) > 0),
    text_sha256 cragkit.sha256_hex NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    PRIMARY KEY (tenant_id, collection_id, document_id, revision_id, generation_id, chunk_id),
    UNIQUE (tenant_id, collection_id, document_id, generation_id, ordinal),
    FOREIGN KEY (tenant_id, collection_id, document_id, revision_id, generation_id)
        REFERENCES cragkit.index_generations (tenant_id, collection_id, document_id, revision_id, generation_id)
        ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, collection_id, document_id, revision_id, generation_id, parent_chunk_id)
        REFERENCES cragkit.chunks (tenant_id, collection_id, document_id, revision_id, generation_id, chunk_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (end_byte > start_byte AND end_byte - start_byte = octet_length(convert_to(text, 'UTF8'))),
    CHECK (text_sha256 = encode(sha256(convert_to(text, 'UTF8')), 'hex')),
    CHECK (parent_chunk_id IS NULL OR parent_chunk_id <> chunk_id)
);

CREATE FUNCTION cragkit.validate_chunk_span() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
DECLARE
    canonical_bytes bytea;
BEGIN
    SELECT convert_to(revision.canonical_text, 'UTF8') INTO canonical_bytes
    FROM cragkit.document_revisions AS revision
    WHERE revision.tenant_id = NEW.tenant_id AND revision.collection_id = NEW.collection_id
        AND revision.document_id = NEW.document_id AND revision.revision_id = NEW.revision_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'cragkit chunk revision is absent' USING ERRCODE = '23503';
    END IF;
    IF NEW.start_byte IS NULL OR NEW.end_byte IS NULL
        OR NEW.start_byte < 0 OR NEW.end_byte <= NEW.start_byte
        OR NEW.end_byte > octet_length(canonical_bytes) THEN
        RAISE EXCEPTION 'cragkit chunk span is invalid' USING ERRCODE = '23514';
    END IF;
    IF substring(canonical_bytes FROM NEW.start_byte::integer + 1
            FOR (NEW.end_byte - NEW.start_byte)::integer) <> convert_to(NEW.text, 'UTF8') THEN
        RAISE EXCEPTION 'cragkit chunk differs from canonical bytes' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER canonical_chunk_span
    BEFORE INSERT OR UPDATE ON cragkit.chunks
    FOR EACH ROW EXECUTE FUNCTION cragkit.validate_chunk_span();

CREATE TABLE cragkit.chunk_lexical (
    tenant_id cragkit.identity_text NOT NULL,
    collection_id cragkit.collection_text NOT NULL,
    document_id cragkit.identity_text NOT NULL,
    revision_id cragkit.identity_text NOT NULL,
    generation_id cragkit.identity_text NOT NULL,
    chunk_id cragkit.identity_text NOT NULL,
    language_config regconfig NOT NULL DEFAULT 'pg_catalog.simple'::regconfig,
    search_vector tsvector NOT NULL,
    identifier_tokens cragkit.identity_text[] NOT NULL DEFAULT ARRAY[]::cragkit.identity_text[],
    PRIMARY KEY (tenant_id, collection_id, document_id, revision_id, generation_id, chunk_id),
    FOREIGN KEY (tenant_id, collection_id, document_id, revision_id, generation_id, chunk_id)
        REFERENCES cragkit.chunks (tenant_id, collection_id, document_id, revision_id, generation_id, chunk_id)
        ON DELETE CASCADE,
    CHECK (array_position(identifier_tokens, NULL) IS NULL),
    CHECK (array_ndims(identifier_tokens) IS NULL OR array_ndims(identifier_tokens) = 1)
);
CREATE INDEX chunk_lexical_search_gin ON cragkit.chunk_lexical USING gin (search_vector);
CREATE INDEX chunk_lexical_identifiers_gin ON cragkit.chunk_lexical USING gin (identifier_tokens);

CREATE FUNCTION cragkit.refresh_lexical_vector() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
DECLARE
    chunk_text text;
BEGIN
    SELECT chunk.text INTO chunk_text FROM cragkit.chunks AS chunk
    WHERE chunk.tenant_id = NEW.tenant_id AND chunk.collection_id = NEW.collection_id
        AND chunk.document_id = NEW.document_id AND chunk.revision_id = NEW.revision_id
        AND chunk.generation_id = NEW.generation_id AND chunk.chunk_id = NEW.chunk_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'cragkit lexical chunk is absent' USING ERRCODE = '23503';
    END IF;
    NEW.search_vector := to_tsvector(NEW.language_config, chunk_text);
    RETURN NEW;
END
$function$;
CREATE TRIGGER canonical_lexical_vector
    BEFORE INSERT OR UPDATE ON cragkit.chunk_lexical
    FOR EACH ROW EXECUTE FUNCTION cragkit.refresh_lexical_vector();

CREATE FUNCTION cragkit.refresh_chunk_lexical() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
BEGIN
    UPDATE cragkit.chunk_lexical
    SET search_vector = to_tsvector(language_config, NEW.text)
    WHERE tenant_id = NEW.tenant_id AND collection_id = NEW.collection_id
        AND document_id = NEW.document_id AND revision_id = NEW.revision_id
        AND generation_id = NEW.generation_id AND chunk_id = NEW.chunk_id;
    RETURN NEW;
END
$function$;
CREATE TRIGGER changed_chunk_lexical_vector
    AFTER UPDATE OF text ON cragkit.chunks
    FOR EACH ROW EXECUTE FUNCTION cragkit.refresh_chunk_lexical();

CREATE TABLE cragkit.document_grants (
    tenant_id cragkit.identity_text NOT NULL,
    collection_id cragkit.collection_text NOT NULL,
    document_id cragkit.identity_text NOT NULL,
    grant_id cragkit.identity_text NOT NULL,
    principal_id cragkit.identity_text,
    authorization_revision cragkit.identity_text NOT NULL DEFAULT '0',
    PRIMARY KEY (tenant_id, collection_id, document_id, grant_id),
    FOREIGN KEY (tenant_id, collection_id, document_id)
        REFERENCES cragkit.documents (tenant_id, collection_id, document_id) ON DELETE CASCADE
);
CREATE INDEX document_grants_scope_idx ON cragkit.document_grants (tenant_id, collection_id, grant_id, document_id);

CREATE TABLE cragkit.ingestion_jobs (
    tenant_id cragkit.identity_text NOT NULL,
    collection_id cragkit.collection_text NOT NULL,
    document_id cragkit.identity_text NOT NULL,
    intent_id cragkit.identity_text NOT NULL,
    payload_sha256 cragkit.sha256_hex NOT NULL,
    generation_id cragkit.identity_text,
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'running', 'succeeded', 'failed')),
    attempt_count cragkit.safe_count NOT NULL DEFAULT 0,
    last_error_code text CHECK (last_error_code IN ('invalid_request', 'unauthorized_scope',
        'unsupported_capability', 'index_not_ready', 'embedding_profile_mismatch',
        'provider_unavailable', 'deadline_exceeded', 'context_budget_too_small', 'integrity_violation')),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, collection_id, intent_id),
    FOREIGN KEY (tenant_id, collection_id, document_id)
        REFERENCES cragkit.documents (tenant_id, collection_id, document_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, collection_id, document_id, generation_id)
        REFERENCES cragkit.index_generations (tenant_id, collection_id, document_id, generation_id)
        DEFERRABLE INITIALLY DEFERRED
);

ALTER TABLE cragkit.collections ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit.document_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit.index_generations ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit.chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit.chunk_lexical ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit.document_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit.ingestion_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON ALL TABLES IN SCHEMA cragkit FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA cragkit FROM PUBLIC;
REVOKE ALL ON DOMAIN cragkit.identity_text, cragkit.collection_text,
    cragkit.sha256_hex, cragkit.safe_count FROM PUBLIC;
