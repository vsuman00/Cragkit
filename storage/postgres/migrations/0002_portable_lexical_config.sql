SET LOCAL search_path = pg_catalog;

ALTER TABLE cragkit.chunk_lexical ALTER COLUMN language_config DROP DEFAULT;
ALTER TABLE cragkit.chunk_lexical ALTER COLUMN language_config TYPE text
    USING language_config::text;
ALTER TABLE cragkit.chunk_lexical ALTER COLUMN language_config SET DEFAULT 'pg_catalog.simple';

CREATE OR REPLACE FUNCTION cragkit.refresh_lexical_vector() RETURNS trigger
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
    NEW.search_vector := to_tsvector(NEW.language_config::regconfig, chunk_text);
    RETURN NEW;
END
$function$;

CREATE OR REPLACE FUNCTION cragkit.refresh_chunk_lexical() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
BEGIN
    UPDATE cragkit.chunk_lexical
    SET search_vector = to_tsvector(language_config::regconfig, NEW.text)
    WHERE tenant_id = NEW.tenant_id AND collection_id = NEW.collection_id
        AND document_id = NEW.document_id AND revision_id = NEW.revision_id
        AND generation_id = NEW.generation_id AND chunk_id = NEW.chunk_id;
    RETURN NEW;
END
$function$;

CREATE INDEX chunks_parent_scope_idx ON cragkit.chunks
    (tenant_id, collection_id, document_id, revision_id, generation_id, parent_chunk_id);
CREATE INDEX documents_active_generation_scope_idx ON cragkit.documents
    (tenant_id, collection_id, document_id, active_generation_id);
CREATE INDEX ingestion_jobs_generation_scope_idx ON cragkit.ingestion_jobs
    (tenant_id, collection_id, document_id, generation_id);
