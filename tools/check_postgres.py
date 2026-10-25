"""Explicit administrative PostgreSQL migration checks; never imported by the libraries."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
LOCK = 'pg_advisory_xact_lock(1129464148, 1)'


class PostgresCheckError(RuntimeError):
    pass


class VectorCompatibilityError(PostgresCheckError):
    """The explicit vector capability is absent or incompatible."""


def vector_compatibility_error(sqlstate: str | None) -> VectorCompatibilityError | None:
    code = {'CV001': 'vector_capability_missing', 'CV002': 'vector_capability_unsupported',
            'CV003': 'vector_version_unavailable'}.get(sqlstate or '')
    return VectorCompatibilityError(code) if code else None


@dataclass(frozen=True)
class Migration:
    version: str
    checksum: str
    sql: str


def migrations(directory: Path) -> list[Migration]:
    result = []
    paths = sorted(directory.glob('*.sql'))
    if not paths:
        raise PostgresCheckError('no_migrations')
    for index, path in enumerate(paths, 1):
        if not re.fullmatch(rf'{index:04d}_[a-z0-9_]+\.sql', path.name):
            raise PostgresCheckError('migration_sequence')
        data = path.read_bytes()
        sql = data.decode('utf-8')
        if re.search(r'(?m)^\s*\\', sql) or '$cragkit_runner$' in sql:
            raise PostgresCheckError('unsafe_migration_script')
        result.append(Migration(path.stem, hashlib.sha256(data).hexdigest(), sql))
    return result


def connection_environment(environment: Mapping[str, str], *, confirmed: bool,
                           local_socket: Path | None = None) -> dict[str, str]:
    if not confirmed:
        raise PostgresCheckError('dedicated_target_confirmation_required')
    result = dict(environment)
    if result.get('PGSERVICE') or result.get('PGSERVICEFILE') or result.get('PGHOSTADDR'):
        raise PostgresCheckError('connection_redirection_forbidden')
    if not all(re.fullmatch(r'[A-Za-z0-9_.@-]+', result.get(key, '')) for key in ('PGDATABASE', 'PGUSER')):
        raise PostgresCheckError('scalar_database_and_user_required')
    if local_socket is not None:
        if not local_socket.is_absolute() or not local_socket.is_dir() or result.get('PGHOST') != str(local_socket):
            raise PostgresCheckError('explicit_unix_socket_required')
        if result.get('PGHOSTADDR') or result.get('PGSERVICE'):
            raise PostgresCheckError('ambiguous_local_target')
        if not all(result.get(key) for key in ('PGDATABASE', 'PGUSER')):
            raise PostgresCheckError('libpq_target_required')
        result['PGSSLMODE'] = 'disable'
    else:
        if not re.fullmatch(r'[A-Za-z0-9.-]+', result.get('PGHOST', '')):
            raise PostgresCheckError('scalar_remote_host_required')
        cert = result.get('PGSSLROOTCERT')
        if result.get('PGSSLMODE') != 'verify-full' or not cert or not Path(cert).is_file():
            raise PostgresCheckError('certificate_verification_required')
        result['PGSSLMODE'] = 'verify-full'
    result['PGCONNECT_TIMEOUT'] = '10'
    result['PGOPTIONS'] = '-c statement_timeout=30000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=30000'
    result['PGAPPNAME'] = 'cragkit-explicit-migrations'
    return result


def migration_script(items: list[Migration], *, apply: bool) -> str:
    if not items:
        raise PostgresCheckError('no_migrations')
    expected = ',\n'.join(f"('{item.version}', '{item.checksum}')" for item in items)
    # Each check and application shares one transaction and advisory lock.
    chunks = ['BEGIN;', "SET LOCAL search_path = pg_catalog;", "SET LOCAL statement_timeout = '30s';",
              "SET LOCAL lock_timeout = '5s';", "SET LOCAL idle_in_transaction_session_timeout = '30s';",
              f'SELECT {LOCK};']
    if not apply:
        chunks.insert(1, 'SET TRANSACTION READ ONLY;')
    if apply:
        chunks.append('''DO $cragkit_runner$ BEGIN
IF to_regclass('cragkit.migration_history') IS NULL AND EXISTS (
 SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit'
 UNION ALL SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='cragkit'
) THEN RAISE EXCEPTION 'unmanaged_schema'; END IF;
END $cragkit_runner$;
CREATE SCHEMA IF NOT EXISTS cragkit;
REVOKE ALL ON SCHEMA cragkit FROM PUBLIC;
CREATE TABLE IF NOT EXISTS cragkit.migration_history (
 version text PRIMARY KEY,
 checksum text NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
 applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
REVOKE ALL ON TABLE cragkit.migration_history FROM PUBLIC;''')
    else:
        chunks.append("DO $cragkit_runner$ BEGIN IF to_regclass('cragkit.migration_history') IS NULL THEN RAISE EXCEPTION 'missing_history'; END IF; END $cragkit_runner$;")
    chunks.append(f'''DO $cragkit_runner$ BEGIN
IF EXISTS (
 WITH expected(version, checksum) AS (VALUES {expected})
 SELECT 1 FROM cragkit.migration_history h LEFT JOIN expected e USING(version)
 WHERE e.version IS NULL OR e.checksum <> h.checksum
) THEN RAISE EXCEPTION 'migration_history_drift'; END IF;
IF EXISTS (
 WITH expected(version, checksum) AS (VALUES {expected}), ordered AS (
 SELECT version, row_number() OVER (ORDER BY version) AS ordinal FROM expected)
 SELECT 1 FROM ordered o JOIN cragkit.migration_history h USING(version)
 WHERE o.ordinal > (SELECT count(*) FROM cragkit.migration_history)
) THEN RAISE EXCEPTION 'migration_history_gap'; END IF;
END $cragkit_runner$;''')
    if apply:
        for item in items:
            chunks.append(f'''DO $cragkit_runner$ BEGIN
IF NOT EXISTS (SELECT 1 FROM cragkit.migration_history WHERE version='{item.version}') THEN
{item.sql}
INSERT INTO cragkit.migration_history(version,checksum) VALUES ('{item.version}','{item.checksum}');
END IF;
END $cragkit_runner$;''')
    else:
        chunks.append(f"DO $cragkit_runner$ BEGIN IF (SELECT count(*) FROM cragkit.migration_history) <> {len(items)} THEN RAISE EXCEPTION 'pending_migrations'; END IF; END $cragkit_runner$;")
    chunks.extend(['COMMIT;', "SELECT 'cragkit_migration_ok';"])
    return '\n'.join(chunks)


VECTOR_SETUP_DIRECTORY = ROOT / 'storage/postgres/setup'
VECTOR_INSPECTION_PREFIX = 'cragkit_vector_inspection:'


def vector_inspection_script() -> str:
    """Inspect catalogs without requiring or changing vector capability."""
    return """BEGIN READ ONLY;
SET LOCAL search_path = pg_catalog;
SET LOCAL statement_timeout = '30s';
SET LOCAL lock_timeout = '5s';
SELECT 'cragkit_vector_inspection:' || json_build_object(
 'database', current_database(), 'user', current_user,
 'server_version', current_setting('server_version'),
 'available_version', (SELECT default_version FROM pg_available_extensions WHERE name='vector'),
 'installed_version', (SELECT extversion FROM pg_extension WHERE extname='vector'),
 'installed_schema', (SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector')
)::text;
COMMIT;
SELECT 'cragkit_vector_inspection_ok';"""


def parse_vector_inspection(lines: list[str], *, database: str, user: str) -> dict[str, str | None]:
    observations = [line[len(VECTOR_INSPECTION_PREFIX):] for line in lines if line.startswith(VECTOR_INSPECTION_PREFIX)]
    try:
        if len(observations) != 1:
            raise ValueError
        value = json.loads(observations[0])
        keys = {'database', 'user', 'server_version', 'available_version', 'installed_version', 'installed_schema'}
        if not isinstance(value, dict) or set(value) != keys:
            raise ValueError
        if any(not isinstance(value[key], str) for key in ('database', 'user', 'server_version')):
            raise ValueError
        if any(value[key] is not None and not isinstance(value[key], str) for key in keys):
            raise ValueError
        if value['database'] != database or value['user'] != user:
            raise PostgresCheckError('database_target_identity_mismatch')
        return value
    except (ValueError, TypeError):
        raise PostgresCheckError('vector_inspection_invalid') from None


def vector_setup_script(item: Migration, *, apply: bool,
                        allow_managed_primitives: bool = False,
                        storage: Migration | None = None) -> str:
    """Use a separate checksummed ledger; lexical migration history is immutable."""
    if not re.fullmatch(r'0001_[a-z0-9_]+', item.version) or not re.fullmatch(r'[0-9a-f]{64}', item.checksum):
        raise PostgresCheckError('invalid_vector_setup_identity')
    if re.search(r'(?m)^\s*\\', item.sql) or '$cragkit_runner$' in item.sql:
        raise PostgresCheckError('unsafe_migration_script')
    expected = [(item.version, item.checksum)]
    if storage is not None:
        if storage.version != '0002_vector_profiles' or not re.fullmatch(r'[0-9a-f]{64}', storage.checksum):
            raise PostgresCheckError('invalid_vector_storage_identity')
        expected.append((storage.version, storage.checksum))
    expected_sql = ','.join(f"('{version}','{checksum}')" for version, checksum in expected)
    capability = """IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector') THEN
 RAISE EXCEPTION USING ERRCODE='CV001', MESSAGE='vector_capability_missing';
END IF;
IF NOT EXISTS (SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
 WHERE e.extname='vector' AND e.extversion='0.8.0' AND n.nspname='cragkit_vector')
 OR EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='cragkit_vector' AND p.prosecdef) THEN
 RAISE EXCEPTION USING ERRCODE='CV002', MESSAGE='vector_capability_unsupported';
END IF;
IF NOT EXISTS (
 SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
 JOIN pg_depend td ON td.classid='pg_type'::regclass AND td.objid=t.oid AND td.deptype='e'
 JOIN pg_extension e ON e.oid=td.refobjid AND td.refclassid='pg_extension'::regclass
 WHERE n.nspname='cragkit_vector' AND t.typname='vector' AND t.typtype='b' AND e.extname='vector'
 AND EXISTS (
  SELECT 1 FROM pg_proc p JOIN pg_depend pd ON pd.classid='pg_proc'::regclass AND pd.objid=p.oid AND pd.deptype='e'
  WHERE p.pronamespace=n.oid AND p.proname='vector_dims' AND p.pronargs=1 AND p.proargtypes[0]=t.oid
  AND p.prorettype='int4'::regtype AND pd.refclassid='pg_extension'::regclass AND pd.refobjid=e.oid)
) THEN RAISE EXCEPTION USING ERRCODE='CV002', MESSAGE='vector_capability_unsupported'; END IF;"""
    primitive_checks = """IF EXISTS (
 SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 CROSS JOIN LATERAL aclexplode(coalesce(p.proacl, acldefault('f',p.proowner))) a
 WHERE n.nspname='cragkit_vector' AND a.grantee=0
 UNION ALL
 SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
 CROSS JOIN LATERAL aclexplode(coalesce(t.typacl, acldefault('T',t.typowner))) a
 WHERE n.nspname='cragkit_vector' AND t.typname IN ('vector','halfvec','sparsevec') AND a.grantee=0
) THEN RAISE EXCEPTION USING ERRCODE='CV002', MESSAGE='vector_capability_unsupported'; END IF;"""
    if allow_managed_primitives:
        # Explicit Neon profile: platform-owned primitives remain a computational surface.
        primitive_checks = """IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector' AND extowner=current_user::regrole)
 OR (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
  WHERE n.nspname='cragkit_vector' AND t.typname IN ('vector','halfvec','sparsevec') AND t.typtype='b')<>3
 OR EXISTS (
  SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='cragkit_vector' AND (p.prosecdef OR
   NOT EXISTS (SELECT 1 FROM pg_roles r WHERE r.oid=p.proowner AND r.rolname='cloud_admin') OR
   NOT EXISTS (SELECT 1 FROM pg_depend d JOIN pg_extension e ON e.oid=d.refobjid
    WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.refclassid='pg_extension'::regclass
    AND d.deptype='e' AND e.extname='vector')))
 OR EXISTS (
  SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
  WHERE n.nspname='cragkit_vector' AND t.typelem=0
  AND NOT (t.typtype='c' AND t.typrelid='cragkit_vector.setup_history'::regclass)
  AND (t.typname NOT IN ('vector','halfvec','sparsevec') OR t.typtype<>'b' OR
   NOT EXISTS (SELECT 1 FROM pg_roles r WHERE r.oid=t.typowner AND r.rolname='cloud_admin') OR
   NOT EXISTS (SELECT 1 FROM pg_depend d JOIN pg_extension e ON e.oid=d.refobjid
    WHERE d.classid='pg_type'::regclass AND d.objid=t.oid AND d.refclassid='pg_extension'::regclass
    AND d.deptype='e' AND e.extname='vector')))
 OR EXISTS (
  SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  CROSS JOIN LATERAL aclexplode(coalesce(p.proacl, acldefault('f',p.proowner))) a
  WHERE n.nspname='cragkit_vector' AND a.grantee NOT IN (0,p.proowner)
  UNION ALL
  SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
  CROSS JOIN LATERAL aclexplode(coalesce(t.typacl, acldefault('T',t.typowner))) a
  WHERE n.nspname='cragkit_vector' AND t.typname IN ('vector','halfvec','sparsevec') AND a.grantee NOT IN (0,t.typowner))
 THEN RAISE EXCEPTION USING ERRCODE='CV002', MESSAGE='vector_capability_unsupported'; END IF;"""
    chunks = ['BEGIN;', "SET LOCAL search_path = pg_catalog;", "SET LOCAL statement_timeout = '30s';",
              "SET LOCAL lock_timeout = '5s';", "SET LOCAL idle_in_transaction_session_timeout = '30s';", f'SELECT {LOCK};']
    if not apply:
        chunks.insert(1, 'SET TRANSACTION READ ONLY;')
    chunks.append("""DO $cragkit_runner$ BEGIN
IF to_regclass('cragkit.migration_history') IS NULL THEN RAISE EXCEPTION 'missing_history'; END IF;
END $cragkit_runner$;
CREATE TEMP TABLE cragkit_lexical_history_before ON COMMIT DROP AS
 SELECT version, checksum, applied_at FROM cragkit.migration_history;""" if apply else
                  "DO $cragkit_runner$ BEGIN IF to_regclass('cragkit.migration_history') IS NULL THEN RAISE EXCEPTION 'missing_history'; END IF; END $cragkit_runner$;")
    if apply:
        chunks.append(f"""DO $cragkit_runner$ BEGIN
IF EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector') THEN
 {capability}
 IF to_regclass('cragkit_vector.setup_history') IS NULL THEN RAISE EXCEPTION 'unmanaged_vector_schema'; END IF;
ELSIF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname='cragkit_vector') THEN
 RAISE EXCEPTION 'unmanaged_vector_schema';
ELSE
 IF NOT EXISTS (SELECT 1 FROM pg_available_extension_versions WHERE name='vector' AND version='0.8.0') THEN
  RAISE EXCEPTION USING ERRCODE='CV003', MESSAGE='vector_version_unavailable';
 END IF;
 {item.sql}
 CREATE TABLE cragkit_vector.setup_history (
  version text PRIMARY KEY, checksum text NOT NULL CHECK (checksum ~ '^[0-9a-f]{{64}}$'),
  applied_at timestamptz NOT NULL DEFAULT clock_timestamp());
 REVOKE ALL ON TABLE cragkit_vector.setup_history FROM PUBLIC;
 ALTER TABLE cragkit_vector.setup_history ENABLE ROW LEVEL SECURITY;
 INSERT INTO cragkit_vector.setup_history(version, checksum) VALUES ('{item.version}', '{item.checksum}');
END IF;
END $cragkit_runner$;""")
    chunks.append(f"""DO $cragkit_runner$ BEGIN
{capability}
IF NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='cragkit_vector' AND c.relname='setup_history' AND c.relkind='r' AND c.relrowsecurity) THEN
 RAISE EXCEPTION USING ERRCODE='CV002', MESSAGE='vector_capability_unsupported'; END IF;
IF NOT EXISTS (SELECT 1 FROM pg_namespace n WHERE n.nspname='cragkit_vector' AND n.nspowner=current_user::regrole)
 OR EXISTS (SELECT 1 FROM pg_class c WHERE c.oid='cragkit_vector.setup_history'::regclass AND c.relowner<>current_user::regrole)
 OR EXISTS (SELECT 1 FROM pg_policy WHERE polrelid='cragkit_vector.setup_history'::regclass)
 OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='cragkit_vector' AND c.oid<>'cragkit_vector.setup_history'::regclass
  AND NOT (c.relkind='i' AND EXISTS (SELECT 1 FROM pg_index i WHERE i.indexrelid=c.oid AND i.indrelid='cragkit_vector.setup_history'::regclass)))
 THEN RAISE EXCEPTION USING ERRCODE='CV002', MESSAGE='vector_capability_unsupported'; END IF;
IF (SELECT count(*) FROM pg_default_acl d
 WHERE d.defaclnamespace=0 AND d.defaclrole=current_user::regrole AND d.defaclobjtype IN ('f','T'))<>2
 OR EXISTS (
 SELECT 1 FROM pg_namespace n CROSS JOIN LATERAL aclexplode(coalesce(n.nspacl, acldefault('n',n.nspowner))) a
 WHERE n.nspname='cragkit_vector' AND a.grantee<>n.nspowner
 UNION ALL
 SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 CROSS JOIN LATERAL aclexplode(coalesce(c.relacl, acldefault('r',c.relowner))) a
 WHERE n.nspname='cragkit_vector' AND c.relname='setup_history' AND a.grantee<>c.relowner
 UNION ALL
 SELECT 1 FROM pg_default_acl d
 CROSS JOIN LATERAL aclexplode(d.defaclacl) a
 WHERE (d.defaclnamespace=0 OR d.defaclnamespace=to_regnamespace('cragkit_vector')) AND d.defaclrole=current_user::regrole AND a.grantee<>d.defaclrole
) THEN RAISE EXCEPTION USING ERRCODE='CV002', MESSAGE='vector_capability_unsupported'; END IF;
{primitive_checks}
IF (SELECT count(*) FROM cragkit_vector.setup_history) NOT BETWEEN 1 AND {len(expected)} OR EXISTS (
 WITH expected(version,checksum) AS (VALUES {expected_sql})
 SELECT 1 FROM cragkit_vector.setup_history h LEFT JOIN expected e USING(version)
 WHERE e.version IS NULL OR e.checksum<>h.checksum) OR NOT EXISTS (
 SELECT 1 FROM cragkit_vector.setup_history WHERE version='{item.version}' AND checksum='{item.checksum}') THEN
 RAISE EXCEPTION 'vector_setup_history_drift';
END IF;
END $cragkit_runner$;""")
    if apply:
        chunks.append("""DO $cragkit_runner$ BEGIN
IF EXISTS ((SELECT version,checksum,applied_at FROM cragkit.migration_history EXCEPT SELECT * FROM pg_temp.cragkit_lexical_history_before)
 UNION ALL (SELECT * FROM pg_temp.cragkit_lexical_history_before EXCEPT SELECT version,checksum,applied_at FROM cragkit.migration_history)) THEN
 RAISE EXCEPTION 'lexical_history_changed'; END IF;
END $cragkit_runner$;""")
    chunks.extend(['COMMIT;', "SELECT 'cragkit_vector_ok';"])
    return '\n'.join(chunks)


def vector_storage_script(item: Migration, *, apply: bool) -> str:
    """Apply the optional second setup artifact under the existing ledger and lock."""
    if item.version != '0002_vector_profiles' or not re.fullmatch(r'[0-9a-f]{64}', item.checksum):
        raise PostgresCheckError('invalid_vector_storage_identity')
    if re.search(r'(?m)^\s*\\', item.sql) or '$cragkit_runner$' in item.sql:
        raise PostgresCheckError('unsafe_migration_script')
    chunks = ['BEGIN;', "SET LOCAL search_path = pg_catalog;", "SET LOCAL statement_timeout = '30s';",
              "SET LOCAL lock_timeout = '5s';", "SET LOCAL idle_in_transaction_session_timeout = '30s';",
              f'SELECT {LOCK};']
    if not apply:
        chunks.insert(1, 'SET TRANSACTION READ ONLY;')
    chunks.append("DO $cragkit_runner$ BEGIN IF to_regclass('cragkit_vector.setup_history') IS NULL THEN RAISE EXCEPTION 'missing_vector_setup_history'; END IF; END $cragkit_runner$;")
    if apply:
        chunks.append(f"""DO $cragkit_runner$ BEGIN
IF NOT EXISTS (SELECT 1 FROM cragkit_vector.setup_history WHERE version='{item.version}') THEN
 {item.sql}
 INSERT INTO cragkit_vector.setup_history(version,checksum) VALUES ('{item.version}','{item.checksum}');
END IF;
END $cragkit_runner$;""")
    chunks.append(f"""DO $cragkit_runner$ BEGIN
IF NOT EXISTS (SELECT 1 FROM cragkit_vector.setup_history WHERE version='{item.version}' AND checksum='{item.checksum}') THEN
 RAISE EXCEPTION USING ERRCODE='CV002', MESSAGE='vector_storage_history_missing_or_drift'; END IF;
IF to_regclass('cragkit.embedding_profiles') IS NULL OR to_regclass('cragkit.chunk_vectors_fake_1536') IS NULL THEN
 RAISE EXCEPTION USING ERRCODE='CV001', MESSAGE='vector_storage_missing'; END IF;
END $cragkit_runner$;""")
    chunks.extend(['COMMIT;', "SELECT 'cragkit_vector_storage_ok';"])
    return '\n'.join(chunks)


def execute(script: str, environment: Mapping[str, str], *, executable: str = 'psql',
            marker: str = 'cragkit_migration_ok') -> list[str]:
    if environment.get('PGSSLMODE') == 'verify-full':
        script = "DO $cragkit_transport$ BEGIN IF inet_server_addr() IS NULL OR NOT coalesce((SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()), false) THEN RAISE EXCEPTION 'verified_remote_transport_required'; END IF; END $cragkit_transport$;\n" + script
    command = [executable, '-X', '--no-password', '--quiet', '--tuples-only', '--no-align',
               '--set', 'ON_ERROR_STOP=1', '--set', 'VERBOSITY=sqlstate', '--file', '-']
    try:
        result = subprocess.run(command, input=script, env=dict(environment), capture_output=True,
                                text=True, timeout=120, check=False)
    except subprocess.TimeoutExpired:
        raise PostgresCheckError('database_process_timeout') from None
    except OSError:
        raise PostgresCheckError('psql_unavailable') from None
    if result.returncode != 0:
        states = re.findall(r'(?m)^(?:psql:[^\n]*?)?ERROR:\s+(CV00[123])\s*$', result.stderr)
        compatibility = vector_compatibility_error(states[0] if len(states) == 1 else None)
        if compatibility is not None:
            raise compatibility
        raise PostgresCheckError('database_check_failed')
    lines = result.stdout.splitlines()
    if marker not in lines:
        raise PostgresCheckError('database_check_incomplete')
    return lines


def security_script(*, allow_managed_primitives: bool = False) -> str:
    """Validate deployment security independently of migration success."""
    script = (ROOT / 'storage/postgres/tests/security.sql').read_text(encoding='utf-8')
    profile = 'neon-managed' if allow_managed_primitives else 'strict'
    return script.replace('BEGIN;', f"BEGIN;\nSET LOCAL cragkit.security_vector_profile = '{profile}';", 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--apply', action='store_true')
    action.add_argument('--check', action='store_true')
    parser.add_argument('--confirm-dedicated-target', action='store_true')
    parser.add_argument('--local-socket', type=Path)
    parser.add_argument('--integration', action='store_true')
    parser.add_argument('--security', action='store_true')
    parser.add_argument('--allow-test-writes', action='store_true')
    parser.add_argument('--vector', action='store_true')
    parser.add_argument('--vector-storage', action='store_true')
    parser.add_argument('--install-vector', action='store_true')
    parser.add_argument('--allow-managed-vector-primitives', action='store_true')
    args = parser.parse_args()
    if args.allow_managed_vector_primitives and not (args.vector or args.install_vector or args.vector_storage or args.security):
        print('Managed vector primitives require --vector or --install-vector.')
        return 2
    if args.install_vector and not args.apply:
        print('PostgreSQL vector installation requires --apply.')
        return 2
    if args.security and not args.allow_test_writes:
        print('Security probes require explicit test-write authorization.')
        return 2
    try:
        environment = connection_environment(os.environ, confirmed=args.confirm_dedicated_target, local_socket=args.local_socket)
        items = migrations(ROOT / 'storage/postgres/migrations')
        if args.vector or args.install_vector or args.vector_storage:
            lines = execute(vector_inspection_script(), environment, marker='cragkit_vector_inspection_ok')
            observation = parse_vector_inspection(lines, database=environment['PGDATABASE'], user=environment['PGUSER'])
            print(json.dumps(observation, sort_keys=True))
        execute(migration_script(items, apply=args.apply), environment)
        if args.vector or args.install_vector or args.vector_storage:
            setup_items = migrations(VECTOR_SETUP_DIRECTORY)
            execute(vector_setup_script(setup_items[0], apply=args.install_vector,
                allow_managed_primitives=args.allow_managed_vector_primitives, storage=setup_items[1]), environment, marker='cragkit_vector_ok')
            if args.vector_storage:
                execute(vector_storage_script(setup_items[1], apply=args.apply), environment, marker='cragkit_vector_storage_ok')
        if args.integration:
            probe = (ROOT / 'storage/postgres/tests/invariants.sql').read_text(encoding='utf-8')
            execute(probe, environment)
            if args.vector_storage:
                execute((ROOT / 'storage/postgres/tests/vectors.sql').read_text(), environment, marker='cragkit_vector_storage_ok')
        if args.security:
            execute(security_script(allow_managed_primitives=args.allow_managed_vector_primitives),
                    environment, marker='cragkit_security_probe_ok')
        print(f'PostgreSQL checks passed: migrations={len(items)}, integration={int(args.integration)}, security={int(args.security)}.')
    except (PostgresCheckError, OSError, UnicodeError) as error:
        code = str(error) if isinstance(error, PostgresCheckError) else 'local_input_unavailable'
        print(f'PostgreSQL checks failed: {code}.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
