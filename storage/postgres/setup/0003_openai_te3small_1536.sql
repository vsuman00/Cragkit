-- Explicit PGO-r1 profile upgrade; old setup artifacts and lexical history stay immutable.
ALTER TABLE cragkit.embedding_profiles DROP CONSTRAINT embedding_profiles_check;
ALTER TABLE cragkit.embedding_profiles ADD CONSTRAINT embedding_profiles_supported_profile_check
CHECK (
    (profile_id = 'fake_embedding_1536_v1' AND provider = 'fake'
        AND model = 'fake_embedding_model_v1' AND dimensions = 1536
        AND tokenizer = 'fake-byte-v1' AND normalization = 'l2'
        AND storage_table = 'chunk_vectors_fake_1536')
    OR
    (profile_id = 'openai_te3small_1536_r1' AND provider = 'openai'
        AND model = 'text-embedding-3-small' AND dimensions = 1536
        AND tokenizer = 'cl100k_base' AND normalization = 'l2'
        AND storage_table = 'chunk_vectors_openai_te3small_1536')
);

INSERT INTO cragkit.embedding_profiles
    (profile_id, provider, model, dimensions, tokenizer, normalization, storage_table)
VALUES ('openai_te3small_1536_r1', 'openai', 'text-embedding-3-small', 1536,
    'cl100k_base', 'l2', 'chunk_vectors_openai_te3small_1536');

CREATE TABLE cragkit.chunk_vectors_openai_te3small_1536 (
    tenant_id cragkit.identity_text NOT NULL,
    collection_id cragkit.collection_text NOT NULL,
    document_id cragkit.identity_text NOT NULL,
    revision_id cragkit.identity_text NOT NULL,
    generation_id cragkit.identity_text NOT NULL,
    chunk_id cragkit.identity_text NOT NULL,
    embedding_profile cragkit.identity_text NOT NULL
        CHECK (embedding_profile = 'openai_te3small_1536_r1'),
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

ALTER TABLE cragkit.chunk_vectors_openai_te3small_1536 ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE cragkit.chunk_vectors_openai_te3small_1536 FROM PUBLIC;
