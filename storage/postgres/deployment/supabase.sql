-- Explicit deployment hardening; preserves the checksummed initial migration.
BEGIN;
SET LOCAL search_path = pg_catalog;
SET LOCAL statement_timeout = '30s';
SET LOCAL lock_timeout = '5s';
SET LOCAL idle_in_transaction_session_timeout = '30s';
SELECT pg_advisory_xact_lock(1129464148, 1);

DO $hardening$
DECLARE
    target text;
    recipient text;
BEGIN
    IF to_regclass('cragkit.migration_history') IS NULL THEN
        RAISE EXCEPTION 'cragkit migration history is required';
    END IF;
    FOREACH target IN ARRAY ARRAY['PUBLIC', 'anon', 'authenticated', 'service_role'] LOOP
        IF target <> 'PUBLIC' AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = target) THEN
            CONTINUE;
        END IF;
        recipient := CASE WHEN target = 'PUBLIC' THEN 'PUBLIC' ELSE quote_ident(target) END;
        EXECUTE format('REVOKE ALL ON SCHEMA cragkit FROM %s', recipient);
        EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA cragkit FROM %s', recipient);
        EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA cragkit FROM %s', recipient);
        EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA cragkit FROM %s', recipient);
        EXECUTE format('REVOKE ALL ON DOMAIN cragkit.identity_text, cragkit.collection_text,
            cragkit.sha256_hex, cragkit.safe_count FROM %s', recipient);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA cragkit REVOKE ALL ON TABLES FROM %s', recipient);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA cragkit REVOKE ALL ON SEQUENCES FROM %s', recipient);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA cragkit REVOKE ALL ON FUNCTIONS FROM %s', recipient);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA cragkit REVOKE ALL ON TYPES FROM %s', recipient);
    END LOOP;
END
$hardening$;

ALTER TABLE cragkit.collections ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit.document_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit.index_generations ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit.chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit.chunk_lexical ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit.document_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit.ingestion_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE cragkit.migration_history ENABLE ROW LEVEL SECURITY;

COMMIT;
SELECT 'cragkit_supabase_hardening_ok';
