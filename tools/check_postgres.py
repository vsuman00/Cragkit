"""Explicit administrative PostgreSQL migration checks; never imported by the libraries."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import subprocess
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
LOCK = 'pg_advisory_xact_lock(1129464148, 1)'


class PostgresCheckError(RuntimeError):
    pass


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


def execute(script: str, environment: Mapping[str, str], *, executable: str = 'psql') -> None:
    if environment.get('PGSSLMODE') == 'verify-full':
        script = "DO $cragkit_transport$ BEGIN IF inet_server_addr() IS NULL OR NOT coalesce((SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()), false) THEN RAISE EXCEPTION 'verified_remote_transport_required'; END IF; END $cragkit_transport$;\n" + script
    command = [executable, '-X', '--no-password', '--quiet', '--tuples-only', '--no-align',
               '--set', 'ON_ERROR_STOP=1', '--file', '-']
    try:
        result = subprocess.run(command, input=script, env=dict(environment), capture_output=True,
                                text=True, timeout=120, check=False)
    except subprocess.TimeoutExpired:
        raise PostgresCheckError('database_process_timeout') from None
    except OSError:
        raise PostgresCheckError('psql_unavailable') from None
    if result.returncode != 0:
        raise PostgresCheckError('database_check_failed')
    if 'cragkit_migration_ok' not in result.stdout.splitlines():
        raise PostgresCheckError('database_check_incomplete')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--apply', action='store_true')
    action.add_argument('--check', action='store_true')
    parser.add_argument('--confirm-dedicated-target', action='store_true')
    parser.add_argument('--local-socket', type=Path)
    parser.add_argument('--integration', action='store_true')
    args = parser.parse_args()
    try:
        environment = connection_environment(os.environ, confirmed=args.confirm_dedicated_target, local_socket=args.local_socket)
        items = migrations(ROOT / 'storage/postgres/migrations')
        execute(migration_script(items, apply=args.apply), environment)
        if args.integration:
            probe = (ROOT / 'storage/postgres/tests/invariants.sql').read_text(encoding='utf-8')
            execute(probe, environment)
        print(f'PostgreSQL checks passed: migrations={len(items)}, integration={int(args.integration)}.')
    except (PostgresCheckError, OSError, UnicodeError) as error:
        code = str(error) if isinstance(error, PostgresCheckError) else 'local_input_unavailable'
        print(f'PostgreSQL checks failed: {code}.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
