-- B-r1 synthetic administrative probes. All fixture rows roll back.
BEGIN;
SET LOCAL search_path = pg_catalog;
SET LOCAL statement_timeout = '30s';
SET LOCAL lock_timeout = '5s';
SET LOCAL idle_in_transaction_session_timeout = '30s';
SELECT pg_advisory_xact_lock(1129464148, 1);
LOCK TABLE cragkit.collections, cragkit.documents, cragkit.document_revisions,
    cragkit.index_generations, cragkit.chunks, cragkit.chunk_lexical,
    cragkit.embedding_profiles, cragkit.chunk_vectors_fake_1536 IN ACCESS EXCLUSIVE MODE;
DO $inventory$
BEGIN
    IF EXISTS (SELECT 1 FROM cragkit.collections)
        OR EXISTS (SELECT 1 FROM cragkit.chunk_vectors_fake_1536) THEN
        RAISE EXCEPTION 'vector_probe_requires_empty_application_tables';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM cragkit.embedding_profiles
        WHERE profile_id='fake_embedding_1536_v1' AND provider='fake'
            AND model='fake_embedding_model_v1' AND dimensions=1536
            AND tokenizer='fake-byte-v1' AND normalization='l2'
            AND storage_table='chunk_vectors_fake_1536') THEN
        RAISE EXCEPTION 'vector_profile_identity_mismatch';
    END IF;
END
$inventory$;
INSERT INTO cragkit.collections (tenant_id,collection_id)
VALUES ('vector-probe-a','docs'),('vector-probe-b','docs'),('vector-probe-a','other');
INSERT INTO cragkit.documents (tenant_id,collection_id,document_id)
SELECT tenant_id,collection_id,'shared' FROM cragkit.collections;
INSERT INTO cragkit.document_revisions
    (tenant_id,collection_id,document_id,revision_id,source_sha256,source_locator,
     canonical_text,canonical_sha256,parser_id)
SELECT tenant_id,collection_id,'shared','shared-rev',repeat('a',64),'synthetic:vector',
    'ab',encode(sha256(convert_to('ab','UTF8')),'hex'),'synthetic.v1'
FROM cragkit.collections;
INSERT INTO cragkit.index_generations
    (tenant_id,collection_id,document_id,revision_id,generation_id,chunker_profile,
     lexical_profile,embedding_profile,expected_chunk_count)
SELECT tenant_id,collection_id,'shared','shared-rev','shared-gen','synthetic.v1',
    'native_fts.v1','fake_embedding_1536_v1',2 FROM cragkit.collections;
INSERT INTO cragkit.chunks
    (tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,ordinal,
     start_byte,end_byte,text,text_sha256)
SELECT tenant_id,collection_id,'shared','shared-rev','shared-gen','shared-chunk',0,
    0,1,'a',encode(sha256(convert_to('a','UTF8')),'hex') FROM cragkit.collections;
INSERT INTO cragkit.chunks
    (tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,ordinal,
     start_byte,end_byte,text,text_sha256)
VALUES ('vector-probe-b','docs','shared','shared-rev','shared-gen','only-b',1,
    1,2,'b',encode(sha256(convert_to('b','UTF8')),'hex'));
INSERT INTO cragkit.chunk_vectors_fake_1536
    (tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,embedding_profile,embedding)
SELECT tenant_id,collection_id,'shared','shared-rev','shared-gen','shared-chunk',
    'fake_embedding_1536_v1', ('[1,' || repeat('0,',1534) || '0]')::cragkit_vector.vector
FROM cragkit.collections;
DO $invariants$
DECLARE
    unit_vector cragkit_vector.vector := ('[1,' || repeat('0,',1534) || '0]')::cragkit_vector.vector;
    invalid_vector text;
BEGIN
    IF (SELECT count(*) FROM cragkit.chunk_vectors_fake_1536) <> 3 THEN
        RAISE EXCEPTION 'scoped_colliding_vector_ids_failed';
    END IF;
    IF EXISTS (SELECT 1 FROM cragkit.documents WHERE active_generation_id IS NOT NULL)
        OR EXISTS (SELECT 1 FROM cragkit.index_generations WHERE status <> 'staging') THEN
        RAISE EXCEPTION 'vector_insert_published_staging_generation';
    END IF;
    -- Counts remain incomplete: native publication must reject this shape.
    IF EXISTS (SELECT 1 FROM cragkit.index_generations AS g WHERE
        (SELECT count(*) FROM cragkit.chunk_vectors_fake_1536 AS v
         WHERE (v.tenant_id,v.collection_id,v.document_id,v.revision_id,v.generation_id,v.embedding_profile)
             = (g.tenant_id,g.collection_id,g.document_id,g.revision_id,g.generation_id,g.embedding_profile))
        = g.expected_chunk_count) THEN
        RAISE EXCEPTION 'missing_vector_count_not_observable';
    END IF;
    BEGIN
        INSERT INTO cragkit.chunk_vectors_fake_1536
            (tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,embedding_profile,embedding)
        VALUES ('vector-probe-a','docs','shared','shared-rev','shared-gen','shared-chunk',
            'fake_embedding_1536_v1',unit_vector);
        RAISE EXCEPTION 'duplicate_vector_chunk_accepted';
    EXCEPTION WHEN unique_violation THEN NULL; END;
    BEGIN
        UPDATE cragkit.chunk_vectors_fake_1536 SET revision_id='missing-revision';
        RAISE EXCEPTION 'wrong_vector_revision_accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    BEGIN
        UPDATE cragkit.chunk_vectors_fake_1536 SET generation_id='missing-generation';
        RAISE EXCEPTION 'wrong_vector_generation_accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    UPDATE cragkit.chunk_vectors_fake_1536 SET embedding=
        ('[1.0005,' || repeat('0,',1534) || '0]')::cragkit_vector.vector;
    UPDATE cragkit.chunk_vectors_fake_1536 SET embedding=unit_vector;
    BEGIN
        UPDATE cragkit.embedding_profiles SET model='same-dim-wrong-model'
            WHERE profile_id='fake_embedding_1536_v1';
        RAISE EXCEPTION 'mutable_same_dimension_profile_identity';
    EXCEPTION WHEN check_violation THEN NULL; END;
    BEGIN
        DELETE FROM cragkit.embedding_profiles WHERE profile_id='fake_embedding_1536_v1';
        RAISE EXCEPTION 'profile_identity_deleted';
    EXCEPTION WHEN check_violation THEN NULL; END;
    BEGIN
        UPDATE cragkit.chunk_vectors_fake_1536 SET embedding_profile='openai_te3small_1536_r1';
        RAISE EXCEPTION 'same_dimension_wrong_profile_accepted';
    EXCEPTION WHEN check_violation OR foreign_key_violation THEN NULL; END;
    BEGIN
        INSERT INTO cragkit.chunk_vectors_fake_1536
            (tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,embedding_profile,embedding)
        VALUES ('vector-probe-a','docs','shared','shared-rev','shared-gen','only-b',
            'fake_embedding_1536_v1',unit_vector);
        RAISE EXCEPTION 'cross_tenant_chunk_reference_accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    BEGIN
        INSERT INTO cragkit.chunk_vectors_fake_1536
            (tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,embedding_profile,embedding)
        VALUES ('vector-probe-a','other','shared','shared-rev','shared-gen','only-b',
            'fake_embedding_1536_v1',unit_vector);
        RAISE EXCEPTION 'cross_collection_chunk_reference_accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    BEGIN
        UPDATE cragkit.index_generations SET embedding_profile=NULL
            WHERE tenant_id='vector-probe-a' AND collection_id='docs';
        RAISE EXCEPTION 'generation_profile_detached_from_vectors';
    EXCEPTION WHEN foreign_key_violation OR check_violation THEN NULL; END;
    BEGIN
        INSERT INTO cragkit.index_generations
            (tenant_id,collection_id,document_id,revision_id,generation_id,chunker_profile,
             lexical_profile,embedding_profile,expected_chunk_count)
        VALUES ('vector-probe-a','docs','shared','shared-rev','wrong-profile-gen',
            'synthetic.v1','native_fts.v1','openai_te3small_1536_r1',1);
        INSERT INTO cragkit.chunks
            (tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,ordinal,
             start_byte,end_byte,text,text_sha256)
        VALUES ('vector-probe-a','docs','shared','shared-rev','wrong-profile-gen','shared-chunk',
            0,0,1,'a',encode(sha256(convert_to('a','UTF8')),'hex'));
        INSERT INTO cragkit.chunk_vectors_fake_1536
            (tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,embedding_profile,embedding)
        VALUES ('vector-probe-a','docs','shared','shared-rev','wrong-profile-gen','shared-chunk',
            'fake_embedding_1536_v1',unit_vector);
        RAISE EXCEPTION 'same_dimension_generation_profile_mismatch_accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    BEGIN
        UPDATE cragkit.chunk_vectors_fake_1536 SET embedding='[1,0]'::cragkit_vector.vector;
        RAISE EXCEPTION 'wrong_vector_dimension_accepted';
    EXCEPTION WHEN data_exception THEN NULL; END;
    FOREACH invalid_vector IN ARRAY ARRAY[
        '[0,' || repeat('0,',1534) || '0]',
        '[2,' || repeat('0,',1534) || '0]'] LOOP
        BEGIN
            UPDATE cragkit.chunk_vectors_fake_1536 SET embedding=invalid_vector::cragkit_vector.vector;
            RAISE EXCEPTION 'non_unit_vector_accepted';
        EXCEPTION WHEN check_violation THEN NULL; END;
    END LOOP;
    FOREACH invalid_vector IN ARRAY ARRAY[
        '[NaN,' || repeat('0,',1534) || '0]',
        '[Infinity,' || repeat('0,',1534) || '0]',
        '[-Infinity,' || repeat('0,',1534) || '0]'] LOOP
        BEGIN
            UPDATE cragkit.chunk_vectors_fake_1536 SET embedding=invalid_vector::cragkit_vector.vector;
            RAISE EXCEPTION 'nonfinite_vector_accepted';
        EXCEPTION WHEN data_exception OR check_violation THEN NULL; END;
    END LOOP;
END
$invariants$;
SAVEPOINT interrupted_vector_batch;
INSERT INTO cragkit.chunk_vectors_fake_1536
    (tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,embedding_profile,embedding)
VALUES ('vector-probe-b','docs','shared','shared-rev','shared-gen','only-b',
    'fake_embedding_1536_v1',('[0,1,' || repeat('0,',1533) || '0]')::cragkit_vector.vector);
DO $complete_count$
BEGIN
    IF (SELECT count(*) FROM cragkit.chunk_vectors_fake_1536
        WHERE tenant_id='vector-probe-b' AND collection_id='docs') <> 2 THEN
        RAISE EXCEPTION 'complete_vector_count_not_observable';
    END IF;
END
$complete_count$;
ROLLBACK TO SAVEPOINT interrupted_vector_batch;
DO $interrupted$
BEGIN
    IF (SELECT count(*) FROM cragkit.chunk_vectors_fake_1536) <> 3
        OR EXISTS (SELECT 1 FROM cragkit.documents WHERE active_generation_id IS NOT NULL) THEN
        RAISE EXCEPTION 'interrupted_batch_changed_vectors_or_pointer';
    END IF;
END
$interrupted$;
ROLLBACK;
DO $cleanup$
BEGIN
    IF EXISTS (SELECT 1 FROM cragkit.collections)
        OR EXISTS (SELECT 1 FROM cragkit.chunk_vectors_fake_1536) THEN
        RAISE EXCEPTION 'vector_probe_rollback_left_fixture_rows';
    END IF;
END
$cleanup$;
SELECT 'cragkit_vector_storage_ok';
