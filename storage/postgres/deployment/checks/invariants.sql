-- Synthetic administrative checks only. Requires empty application tables; always rolls back.
BEGIN;
SET LOCAL search_path = pg_catalog;
SET LOCAL statement_timeout = '30s';
SET LOCAL lock_timeout = '5s';
SET LOCAL idle_in_transaction_session_timeout = '30s';
SELECT pg_advisory_xact_lock(1129464148, 1);
LOCK TABLE cragkit.collections, cragkit.documents, cragkit.document_revisions,
    cragkit.index_generations, cragkit.chunks, cragkit.chunk_lexical,
    cragkit.document_grants, cragkit.ingestion_jobs IN ACCESS EXCLUSIVE MODE;
DO $probe$ BEGIN
    IF EXISTS (SELECT 1 FROM cragkit.collections
        UNION ALL SELECT 1 FROM cragkit.documents
        UNION ALL SELECT 1 FROM cragkit.document_revisions
        UNION ALL SELECT 1 FROM cragkit.index_generations
        UNION ALL SELECT 1 FROM cragkit.chunks
        UNION ALL SELECT 1 FROM cragkit.chunk_lexical
        UNION ALL SELECT 1 FROM cragkit.document_grants
        UNION ALL SELECT 1 FROM cragkit.ingestion_jobs) THEN
        RAISE EXCEPTION 'integration_requires_empty_application_tables';
    END IF;
END $probe$;
INSERT INTO cragkit.collections(tenant_id,collection_id) VALUES ('probe-a','docs'),('probe-b','docs'),('probe-a','other');
INSERT INTO cragkit.documents(tenant_id,collection_id,document_id) VALUES ('probe-a','docs','doc-a'),('probe-b','docs','doc-b');
INSERT INTO cragkit.document_revisions(tenant_id,collection_id,document_id,revision_id,source_sha256,source_locator,canonical_text,canonical_sha256,parser_id)
SELECT tenant_id,'docs',document_id,revision_id,encode(sha256(convert_to('Café 🙂','UTF8')),'hex'),'synthetic:probe','Café 🙂',encode(sha256(convert_to('Café 🙂','UTF8')),'hex'),'probe.v1'
FROM (VALUES ('probe-a','doc-a','rev-a'),('probe-b','doc-b','rev-b')) AS t(tenant_id,document_id,revision_id);
INSERT INTO cragkit.index_generations(tenant_id,collection_id,document_id,revision_id,generation_id,chunker_profile,lexical_profile,expected_chunk_count)
VALUES ('probe-a','docs','doc-a','rev-a','gen-a','probe.v1','native_fts.v1',1),('probe-b','docs','doc-b','rev-b','gen-b','probe.v1','native_fts.v1',1);
INSERT INTO cragkit.chunks(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,ordinal,start_byte,end_byte,text,text_sha256)
SELECT tenant_id,'docs',document_id,revision_id,generation_id,chunk_id,0,0,octet_length('Café 🙂'),'Café 🙂',encode(sha256(convert_to('Café 🙂','UTF8')),'hex')
FROM (VALUES ('probe-a','doc-a','rev-a','gen-a','chunk-a'),('probe-b','doc-b','rev-b','gen-b','chunk-b')) AS t(tenant_id,document_id,revision_id,generation_id,chunk_id);
INSERT INTO cragkit.chunk_lexical(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,search_vector,identifier_tokens)
VALUES ('probe-a','docs','doc-a','rev-a','gen-a','chunk-a',to_tsvector('pg_catalog.simple','Café 🙂'),ARRAY['ERR-17']);
INSERT INTO cragkit.document_grants(tenant_id,collection_id,document_id,grant_id) VALUES ('probe-a','docs','doc-a','read');
DO $probe$ BEGIN
    PERFORM 'v'::cragkit.identity_text;
    PERFORM repeat('🙂',64)::cragkit.identity_text;
    PERFORM repeat('🙂',32)::cragkit.collection_text;
    BEGIN
        PERFORM chr(11)::cragkit.identity_text;
        RAISE EXCEPTION 'vertical_tab_identity_accepted';
    EXCEPTION WHEN check_violation THEN NULL; END;
    BEGIN
        PERFORM repeat('🙂',65)::cragkit.identity_text;
        RAISE EXCEPTION 'identity_utf8_overflow_accepted';
    EXCEPTION WHEN check_violation THEN NULL; END;
    BEGIN
        PERFORM repeat('🙂',33)::cragkit.collection_text;
        RAISE EXCEPTION 'collection_utf8_overflow_accepted';
    EXCEPTION WHEN check_violation THEN NULL; END;
    BEGIN
        INSERT INTO cragkit.documents(tenant_id,collection_id,document_id) VALUES ('missing-tenant','docs','bad');
        RAISE EXCEPTION 'unscoped_collection_accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    BEGIN
        INSERT INTO cragkit.document_revisions(tenant_id,collection_id,document_id,revision_id,source_sha256,source_locator,canonical_text,canonical_sha256,parser_id)
        VALUES ('probe-a','docs','doc-b','bad',repeat('a',64),'synthetic','valid',encode(sha256(convert_to('valid','UTF8')),'hex'),'probe');
        RAISE EXCEPTION 'unscoped_revision_document_accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    BEGIN
        INSERT INTO cragkit.chunks(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,ordinal,start_byte,end_byte,text,text_sha256)
        VALUES ('probe-a','docs','doc-a','rev-a','gen-b','bad',1,0,octet_length('Café 🙂'),'Café 🙂',encode(sha256(convert_to('Café 🙂','UTF8')),'hex'));
        RAISE EXCEPTION 'unscoped_chunk_generation_accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    BEGIN
        INSERT INTO cragkit.index_generations(tenant_id,collection_id,document_id,revision_id,generation_id,chunker_profile,lexical_profile,expected_chunk_count)
        VALUES ('probe-a','docs','doc-a','rev-b','bad','probe','probe',1);
        RAISE EXCEPTION 'cross_tenant_revision_accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    BEGIN
        INSERT INTO cragkit.document_grants(tenant_id,collection_id,document_id,grant_id) VALUES ('probe-a','docs','doc-b','bad');
        RAISE EXCEPTION 'cross_tenant_grant_document_accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    BEGIN
        INSERT INTO cragkit.document_grants(tenant_id,collection_id,document_id,grant_id) VALUES ('probe-a','other','doc-a','bad');
        RAISE EXCEPTION 'cross_collection_reference_accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    BEGIN
        INSERT INTO cragkit.chunk_lexical(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,search_vector)
        VALUES ('probe-a','docs','doc-a','rev-a','gen-a','chunk-b','');
        RAISE EXCEPTION 'cross_tenant_chunk_accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    BEGIN
        UPDATE cragkit.documents SET active_generation_id='gen-b' WHERE tenant_id='probe-a';
        SET CONSTRAINTS ALL IMMEDIATE;
        RAISE EXCEPTION 'cross_tenant_active_generation_accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    BEGIN
        INSERT INTO cragkit.ingestion_jobs(tenant_id,collection_id,document_id,intent_id,payload_sha256,generation_id)
        VALUES ('probe-a','docs','doc-a','bad',repeat('a',64),'gen-b');
        SET CONSTRAINTS ALL IMMEDIATE;
        RAISE EXCEPTION 'cross_tenant_job_generation_accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    BEGIN
        UPDATE cragkit.chunks SET parent_chunk_id='chunk-b' WHERE tenant_id='probe-a';
        SET CONSTRAINTS ALL IMMEDIATE;
        RAISE EXCEPTION 'cross_tenant_parent_chunk_accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    BEGIN
        INSERT INTO cragkit.document_revisions(tenant_id,collection_id,document_id,revision_id,source_sha256,source_locator,canonical_text,canonical_sha256,parser_id)
        VALUES ('probe-a','docs','doc-a','bad-digest',repeat('a',64),'synthetic:bad-digest','Café 🙂',repeat('0',64),'probe');
        RAISE EXCEPTION 'incorrect_canonical_digest_accepted';
    EXCEPTION WHEN check_violation THEN NULL; END;
    BEGIN
        UPDATE cragkit.chunks SET text_sha256=repeat('0',64) WHERE tenant_id='probe-a';
        RAISE EXCEPTION 'incorrect_chunk_digest_accepted';
    EXCEPTION WHEN check_violation THEN NULL; END;
    BEGIN
        UPDATE cragkit.document_revisions SET source_locator='changed' WHERE tenant_id='probe-a';
        RAISE EXCEPTION 'revision_update_accepted';
    EXCEPTION WHEN check_violation THEN NULL; END;
    BEGIN
        UPDATE cragkit.chunks SET text='wrong',end_byte=5,text_sha256=encode(sha256(convert_to('wrong','UTF8')),'hex') WHERE tenant_id='probe-a';
        RAISE EXCEPTION 'incorrect_canonical_span_accepted';
    EXCEPTION WHEN check_violation THEN NULL; END;
END $probe$;
-- Repeated logical IDs are valid when their tenant/collection scope differs.
INSERT INTO cragkit.documents(tenant_id,collection_id,document_id)
VALUES ('probe-a','docs','shared'),('probe-b','docs','shared'),('probe-a','other','shared');
INSERT INTO cragkit.document_revisions(tenant_id,collection_id,document_id,revision_id,source_sha256,source_locator,canonical_text,canonical_sha256,parser_id)
SELECT tenant_id,collection_id,'shared','shared-rev',encode(sha256(convert_to('Café 🙂','UTF8')),'hex'),
    'synthetic:scope','Café 🙂',encode(sha256(convert_to('Café 🙂','UTF8')),'hex'),'probe.v1'
FROM cragkit.documents WHERE document_id='shared';
INSERT INTO cragkit.index_generations(tenant_id,collection_id,document_id,revision_id,generation_id,chunker_profile,lexical_profile,expected_chunk_count)
SELECT tenant_id,collection_id,'shared','shared-rev','shared-gen','probe.v1','native_fts.v1',1
FROM cragkit.documents WHERE document_id='shared';
INSERT INTO cragkit.chunks(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,ordinal,start_byte,end_byte,text,text_sha256)
SELECT tenant_id,collection_id,'shared','shared-rev','shared-gen','shared-chunk',0,0,10,'Café 🙂',
    encode(sha256(convert_to('Café 🙂','UTF8')),'hex')
FROM cragkit.documents WHERE document_id='shared';
INSERT INTO cragkit.chunk_lexical(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,language_config,search_vector)
SELECT tenant_id,collection_id,'shared','shared-rev','shared-gen','shared-chunk','pg_catalog.simple','forged'::tsvector
FROM cragkit.documents WHERE document_id='shared';
INSERT INTO cragkit.document_grants(tenant_id,collection_id,document_id,grant_id)
SELECT tenant_id,collection_id,'shared','read' FROM cragkit.documents WHERE document_id='shared';
INSERT INTO cragkit.ingestion_jobs(tenant_id,collection_id,document_id,intent_id,payload_sha256,generation_id)
SELECT tenant_id,collection_id,'shared','shared-intent',repeat('a',64),'shared-gen'
FROM cragkit.documents WHERE document_id='shared';
UPDATE cragkit.documents SET active_generation_id='shared-gen' WHERE document_id='shared';
SET CONSTRAINTS ALL IMMEDIATE;
DO $probe$ BEGIN
    IF (SELECT count(*) FROM cragkit.chunks WHERE chunk_id='shared-chunk') <> 3 THEN
        RAISE EXCEPTION 'repeated_scoped_identifiers_failed';
    END IF;
    IF EXISTS (SELECT 1 FROM cragkit.chunk_lexical WHERE document_id='shared'
        AND search_vector <> to_tsvector(language_config::regconfig,'Café 🙂')) THEN
        RAISE EXCEPTION 'forged_lexical_vector_not_replaced';
    END IF;
END $probe$;
UPDATE cragkit.chunk_lexical SET search_vector='forged'::tsvector WHERE document_id='shared';
DO $probe$ BEGIN
    IF EXISTS (SELECT 1 FROM cragkit.chunk_lexical WHERE document_id='shared'
        AND search_vector <> to_tsvector(language_config::regconfig,'Café 🙂')) THEN
        RAISE EXCEPTION 'lexical_vector_update_not_replaced';
    END IF;
END $probe$;
UPDATE cragkit.chunks SET start_byte=6,end_byte=10,text='🙂',
    text_sha256=encode(sha256(convert_to('🙂','UTF8')),'hex') WHERE document_id='shared';
DO $probe$ BEGIN
    IF EXISTS (SELECT 1 FROM cragkit.chunk_lexical WHERE document_id='shared'
        AND (search_vector <> to_tsvector(language_config::regconfig,'🙂')
            OR search_vector = to_tsvector(language_config::regconfig,'Café 🙂'))) THEN
        RAISE EXCEPTION 'chunk_text_change_did_not_refresh_lexical_vector';
    END IF;
END $probe$;
-- Text configuration names must remain valid and changing them must rebuild the vector.
INSERT INTO cragkit.document_revisions(tenant_id,collection_id,document_id,revision_id,source_sha256,source_locator,canonical_text,canonical_sha256,parser_id)
VALUES ('probe-a','docs','shared','config-rev',
    encode(sha256(convert_to('Running workers jumped.','UTF8')),'hex'),'synthetic:config',
    'Running workers jumped.',encode(sha256(convert_to('Running workers jumped.','UTF8')),'hex'),'probe.v1');
INSERT INTO cragkit.index_generations(tenant_id,collection_id,document_id,revision_id,generation_id,chunker_profile,lexical_profile,expected_chunk_count)
VALUES ('probe-a','docs','shared','config-rev','config-gen','probe.v1','native_fts.v1',1);
INSERT INTO cragkit.chunks(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,ordinal,start_byte,end_byte,text,text_sha256)
VALUES ('probe-a','docs','shared','config-rev','config-gen','config-chunk',0,0,
    octet_length('Running workers jumped.'),'Running workers jumped.',
    encode(sha256(convert_to('Running workers jumped.','UTF8')),'hex'));
INSERT INTO cragkit.chunk_lexical(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,language_config,search_vector)
VALUES ('probe-a','docs','shared','config-rev','config-gen','config-chunk','pg_catalog.simple','forged');
UPDATE cragkit.chunk_lexical SET language_config='pg_catalog.english' WHERE chunk_id='config-chunk';
DO $probe$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM cragkit.chunk_lexical WHERE chunk_id='config-chunk'
        AND language_config='pg_catalog.english'
        AND search_vector=to_tsvector('pg_catalog.english'::regconfig,'Running workers jumped.')
        AND search_vector<>to_tsvector('pg_catalog.simple'::regconfig,'Running workers jumped.')) THEN
        RAISE EXCEPTION 'configuration_change_did_not_rebuild_lexical_vector';
    END IF;
    BEGIN
        UPDATE cragkit.chunk_lexical SET language_config='cragkit_missing_configuration'
            WHERE chunk_id='config-chunk';
        RAISE EXCEPTION 'missing_configuration_name_accepted';
    EXCEPTION WHEN undefined_object THEN NULL; END;
    BEGIN
        UPDATE cragkit.chunk_lexical SET language_config=NULL WHERE chunk_id='config-chunk';
        RAISE EXCEPTION 'null_configuration_name_accepted';
    EXCEPTION WHEN not_null_violation THEN NULL; END;
END $probe$;
DELETE FROM cragkit.documents WHERE document_id='shared';
SET CONSTRAINTS ALL IMMEDIATE;
DO $probe$ BEGIN
    IF EXISTS (SELECT 1 FROM cragkit.documents WHERE document_id='shared'
        UNION ALL SELECT 1 FROM cragkit.document_revisions WHERE document_id='shared'
        UNION ALL SELECT 1 FROM cragkit.index_generations WHERE document_id='shared'
        UNION ALL SELECT 1 FROM cragkit.chunks WHERE document_id='shared'
        UNION ALL SELECT 1 FROM cragkit.chunk_lexical WHERE document_id='shared'
        UNION ALL SELECT 1 FROM cragkit.document_grants WHERE document_id='shared'
        UNION ALL SELECT 1 FROM cragkit.ingestion_jobs WHERE document_id='shared') THEN
        RAISE EXCEPTION 'document_purge_left_descendants';
    END IF;
END $probe$;
SAVEPOINT rollback_probe;
INSERT INTO cragkit.ingestion_jobs(tenant_id,collection_id,document_id,intent_id,payload_sha256,attempt_count)
VALUES ('probe-a','docs','doc-a','rolled-back',repeat('b',64),11);
DO $probe$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM cragkit.ingestion_jobs WHERE attempt_count=11) THEN RAISE EXCEPTION 'attempt_eleven_rejected'; END IF;
    BEGIN
        UPDATE cragkit.ingestion_jobs SET attempt_count=-1;
        RAISE EXCEPTION 'negative_attempt_accepted';
    EXCEPTION WHEN check_violation THEN NULL; END;
END $probe$;
ROLLBACK TO SAVEPOINT rollback_probe;
DO $probe$ BEGIN
    IF EXISTS (SELECT 1 FROM cragkit.ingestion_jobs) THEN RAISE EXCEPTION 'savepoint_rollback_failed'; END IF;
END $probe$;
ROLLBACK;
DO $probe$ BEGIN
    IF EXISTS (SELECT 1 FROM cragkit.collections
        UNION ALL SELECT 1 FROM cragkit.documents
        UNION ALL SELECT 1 FROM cragkit.document_revisions
        UNION ALL SELECT 1 FROM cragkit.index_generations
        UNION ALL SELECT 1 FROM cragkit.chunks
        UNION ALL SELECT 1 FROM cragkit.chunk_lexical
        UNION ALL SELECT 1 FROM cragkit.document_grants
        UNION ALL SELECT 1 FROM cragkit.ingestion_jobs) THEN
        RAISE EXCEPTION 'integration_rollback_left_data';
    END IF;
END $probe$;
SELECT 'cragkit_migration_ok';
