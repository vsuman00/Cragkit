-- Optional B-r1 storage; applied explicitly after 0001_pgvector, never by lexical startup.
CREATE TABLE cragkit.embedding_profiles (
    profile_id cragkit.identity_text PRIMARY KEY,
    provider cragkit.identity_text NOT NULL,
    model cragkit.identity_text NOT NULL,
    dimensions integer NOT NULL,
    tokenizer cragkit.identity_text NOT NULL,
    normalization cragkit.identity_text NOT NULL,
    storage_table cragkit.identity_text NOT NULL UNIQUE,
    CHECK (profile_id = 'fake_embedding_1536_v1'
        AND provider = 'fake' AND model = 'fake_embedding_model_v1'
        AND dimensions = 1536 AND tokenizer = 'fake-byte-v1'
        AND normalization = 'l2' AND storage_table = 'chunk_vectors_fake_1536')
);

CREATE FUNCTION cragkit.reject_embedding_profile_change() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
BEGIN
    RAISE EXCEPTION 'cragkit embedding profiles are immutable' USING ERRCODE = '23514';
END
$function$;
CREATE TRIGGER immutable_embedding_profile
    BEFORE UPDATE OR DELETE ON cragkit.embedding_profiles
    FOR EACH ROW EXECUTE FUNCTION cragkit.reject_embedding_profile_change();

INSERT INTO cragkit.embedding_profiles
    (profile_id, provider, model, dimensions, tokenizer, normalization, storage_table)
VALUES ('fake_embedding_1536_v1', 'fake', 'fake_embedding_model_v1', 1536,
    'fake-byte-v1', 'l2', 'chunk_vectors_fake_1536');

ALTER TABLE cragkit.index_generations ADD CONSTRAINT index_generations_vector_identity_key
    UNIQUE (tenant_id, collection_id, document_id, revision_id, generation_id, embedding_profile);

CREATE TABLE cragkit.chunk_vectors_fake_1536 (
    tenant_id cragkit.identity_text NOT NULL,
    collection_id cragkit.collection_text NOT NULL,
    document_id cragkit.identity_text NOT NULL,
    revision_id cragkit.identity_text NOT NULL,
    generation_id cragkit.identity_text NOT NULL,
    chunk_id cragkit.identity_text NOT NULL,
    embedding_profile cragkit.identity_text NOT NULL
        CHECK (embedding_profile = 'fake_embedding_1536_v1'),
    embedding cragkit_vector.vector(1536) NOT NULL,
    PRIMARY KEY (tenant_id, collection_id, document_id, revision_id, generation_id, chunk_id),
    FOREIGN KEY (embedding_profile) REFERENCES cragkit.embedding_profiles (profile_id),
    FOREIGN KEY (tenant_id, collection_id, document_id, revision_id, generation_id, chunk_id)
        REFERENCES cragkit.chunks
            (tenant_id, collection_id, document_id, revision_id, generation_id, chunk_id)
        ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, collection_id, document_id, revision_id, generation_id, embedding_profile)
        REFERENCES cragkit.index_generations
            (tenant_id, collection_id, document_id, revision_id, generation_id, embedding_profile)
        ON DELETE CASCADE,
    CHECK (abs(cragkit_vector.vector_norm(embedding) - 1.0) <= 0.001)
);

ALTER TABLE cragkit.embedding_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit.chunk_vectors_fake_1536 ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE cragkit.embedding_profiles, cragkit.chunk_vectors_fake_1536 FROM PUBLIC;
REVOKE ALL ON FUNCTION cragkit.reject_embedding_profile_change() FROM PUBLIC;
