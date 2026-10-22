-- Optional administrative setup; never part of lexical migrations or runtime startup.
CREATE SCHEMA cragkit_vector;
REVOKE ALL ON SCHEMA cragkit_vector FROM PUBLIC;
CREATE EXTENSION vector WITH SCHEMA cragkit_vector VERSION '0.8.0';
-- Revoke primitive privileges only when the installer has effective ownership.
-- Neon platform-owned primitives retain their ACLs under the explicit managed profile.
DO $cragkit_vector_acl$
DECLARE item record;
BEGIN
    FOR item IN SELECT p.oid::regprocedure AS signature FROM pg_proc p
        JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='cragkit_vector' AND pg_has_role(current_user,p.proowner,'USAGE')
    LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', item.signature);
    END LOOP;
    FOR item IN SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
        WHERE n.nspname='cragkit_vector' AND t.typname IN ('vector','halfvec','sparsevec')
        AND pg_has_role(current_user,t.typowner,'USAGE')
    LOOP
        EXECUTE format('REVOKE ALL ON TYPE cragkit_vector.%I FROM PUBLIC', item.typname);
    END LOOP;
END
$cragkit_vector_acl$;
-- Defaults apply to this installer in the dedicated database, across schemas.
-- PostgreSQL cannot subtract global PUBLIC defaults with per-schema REVOKE.
ALTER DEFAULT PRIVILEGES REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES REVOKE ALL ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES REVOKE ALL ON TYPES FROM PUBLIC;
