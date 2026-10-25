"""Explicit rolled-back security regressions on the dedicated Neon development target."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from check_neon_postgres import execute_script
from check_postgres import security_script
from check_python_postgres import load_config, require_client_tls, require_neon_host

PROBES = (
    ('unexpected_vector_domain', 'CREATE DOMAIN cragkit_vector.cragkit_remnant_domain AS text',
     'unexpected vector object inventory'),
    ('unexpected_vector_function', "CREATE FUNCTION cragkit_vector.cragkit_remnant_routine() RETURNS integer LANGUAGE sql AS 'SELECT 1'",
     'unexpected vector object inventory'),
    ('implicit_global_function_default', 'ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO PUBLIC',
     'unsafe application creator default privileges'),
    ('public_default_table', 'ALTER DEFAULT PRIVILEGES IN SCHEMA cragkit GRANT SELECT ON TABLES TO PUBLIC',
     'unsafe application creator default privileges'),
    ('public_vector_schema', 'GRANT USAGE ON SCHEMA cragkit_vector TO PUBLIC',
     'unexpected vector schema table or type privileges'),
    ('vector_ledger_rls', 'ALTER TABLE cragkit_vector.setup_history DISABLE ROW LEVEL SECURITY',
     'unsafe vector extension or setup ledger'),
    ('vector_security_definer', "CREATE FUNCTION cragkit_vector.cragkit_remnant_probe() RETURNS integer LANGUAGE sql SECURITY DEFINER AS 'SELECT 1'",
     'unsafe vector extension or setup ledger'),
)


async def snapshot(connection):
    cursor = await connection.execute("""SELECT
        (SELECT jsonb_agg(to_jsonb(h) ORDER BY version) FROM cragkit.migration_history h),
        (SELECT jsonb_agg(to_jsonb(h) ORDER BY version) FROM cragkit_vector.setup_history h),
        (SELECT count(*) FROM pg_roles WHERE rolname='cragkit_security_probe'),
        (SELECT count(*) FROM pg_policies WHERE schemaname IN ('cragkit','cragkit_vector'))""")
    return await cursor.fetchall()


async def probe(connection, label, mutation, expected, *, managed):
    try:
        await connection.execute("BEGIN; SET LOCAL lock_timeout='5s'; SET LOCAL statement_timeout='30s'; SELECT pg_advisory_xact_lock(1129464148,1);", prepare=False)
        await connection.execute(mutation)
        # Retain the probe's transaction so the injected catalog change is visible.
        script = security_script(allow_managed_primitives=managed).replace('BEGIN;', '', 1)
        try:
            await execute_script(connection, script, 'cragkit_security_probe_ok')
        except Exception as error:
            message = getattr(getattr(error, 'diag', None), 'message_primary', None)
            if getattr(error, 'sqlstate', None) != 'P0001' or message != expected:
                raise RuntimeError('unexpected_security_probe_failure') from None
        else:
            raise RuntimeError('unsafe_security_probe_accepted')
    finally:
        await connection.execute('ROLLBACK')
    return label


async def check(config_path: Path, *, managed: bool):
    import psycopg
    from cragkit._postgres_pool import PoolResource, parse_pool_config

    config = parse_pool_config(load_config(config_path))
    require_neon_host(config.host)
    PoolResource(config)._check_owned_configuration()
    async with await psycopg.AsyncConnection.connect(
        host=config.host, port=config.port, dbname=config.dbname, user=config.user,
        sslmode='verify-full', sslrootcert=str(config.sslrootcert), passfile=str(config.passfile),
        connect_timeout=5, autocommit=True, application_name='cragkit-security-regressions',
        options='-c statement_timeout=30000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=30000',
    ) as connection:
        require_client_tls(connection)
        cursor = await connection.execute('SELECT pg_try_advisory_lock(1129464148,1)')
        if await cursor.fetchall() != [(True,)]:
            raise RuntimeError('security_regression_lock_busy')
        from psycopg import sql
        for table in ('collections','documents','document_revisions','index_generations','chunks',
                      'chunk_lexical','document_grants','ingestion_jobs','chunk_vectors_fake_1536'):
            cursor = await connection.execute(sql.SQL('SELECT count(*) FROM cragkit.{}').format(sql.Identifier(table)))
            if await cursor.fetchall() != [(0,)]:
                raise RuntimeError('security_regressions_require_empty_target')
        before = await snapshot(connection)
        await execute_script(connection, security_script(allow_managed_primitives=managed), 'cragkit_security_probe_ok')
        checks = []
        for label, mutation, expected in PROBES:
            checks.append(await probe(connection, label, mutation, expected, managed=managed))
        await execute_script(connection, security_script(allow_managed_primitives=managed), 'cragkit_security_probe_ok')
        if await snapshot(connection) != before:
            raise RuntimeError('security_probe_cleanup_mismatch')
        return {'state': 'passed', 'negative_probes': checks, 'cleanup_verified': True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--confirm-dedicated-target', action='store_true', required=True)
    parser.add_argument('--allow-test-writes', action='store_true', required=True)
    parser.add_argument('--allow-managed-vector-primitives', action='store_true')
    args = parser.parse_args()
    try:
        async def bounded():
            async with asyncio.timeout(120):
                return await check(args.config, managed=args.allow_managed_vector_primitives)
        print(json.dumps(asyncio.run(bounded()), sort_keys=True))
    except Exception:
        print('Security regression checks failed; details redacted.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
