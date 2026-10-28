"""Explicit rollback-only PostgreSQL recovery-dispatch permission acceptance."""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import re
from pathlib import Path

from check_qdrant_publication_schema import owned_connection
from qdrant_authority_schema import ROOT, catalog_queries, migration as source_migration
from qdrant_publication_schema import CAPABILITY_ROLES, migration as publication_migration
from qdrant_recovery_dispatch_sql import CHECKS, PROOF_SCOPE, SECURITY_CHECKS, SECURITY_PROOF_SCOPE
from qdrant_source_native import PostgresSourceFixture
from runtime_diagnostics import CleanupFailure, describe_error

STAGE = 'configuration'


async def check(fixture, *, security_owner=False):
    """Check fixed installed profiles and roll back every metadata mutation."""
    global STAGE
    import psycopg
    from qdrant_attestation_schema import migration, seed_pre_upgrade
    from qdrant_recovery_dispatch_sql import run_probes, run_security_probes
    if type(security_owner) is not bool:
        raise ValueError('recovery_dispatch_security_mode')

    config = fixture.config
    STAGE = 'connection'
    connection = await psycopg.AsyncConnection.connect(host=config['host'], port=config['port'],
        dbname=config['dbname'], user=config['user'], passfile=config['passfile'],
        sslmode='verify-full', sslrootcert=config['sslrootcert'], connect_timeout=5,
        autocommit=True, options='-c statement_timeout=10000 -c lock_timeout=1000 '
            '-c idle_in_transaction_session_timeout=15000')
    async with owned_connection(connection):
        if not connection.pgconn.ssl_in_use:
            raise RuntimeError('recovery_dispatch_fixture_tls_required')
        async def rows(query, params=None):
            cursor = await connection.execute(query, params, prepare=False)
            return await cursor.fetchall()
        async def inventory():
            values = []
            for query in (
                'SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,rolreplication,rolbypassrls FROM pg_roles ORDER BY rolname',
                'SELECT roleid,member,grantor,admin_option,inherit_option,set_option FROM pg_auth_members ORDER BY roleid,member,grantor',
                'SELECT nspname,nspowner,nspacl::text FROM pg_namespace ORDER BY nspname',
                'SELECT defaclrole,defaclnamespace,defaclobjtype,defaclacl::text FROM pg_default_acl ORDER BY defaclrole,defaclnamespace,defaclobjtype'):
                values.append(await rows(query))
            return sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest()

        original = await inventory()
        source, publication, attestation = source_migration(), publication_migration(), migration()
        fingerprint_query, _ = catalog_queries()
        source_profile = json.loads((ROOT/'contracts/fixtures/qdrant_authority_catalog.json').read_text())
        publication_profile = json.loads((ROOT/'contracts/fixtures/qdrant_publication_catalog.json').read_text())
        expected_profile = json.loads((ROOT/'contracts/fixtures/qdrant_attestation_catalog.json').read_text())
        async def apply(item):
            await connection.execute(item.sql, prepare=False)
            await connection.execute('INSERT INTO cragkit_qdrant.schema_migrations '
                '(version,checksum_sha256) VALUES(%s,%s)', (item.version, item.checksum))
        async def install_old():
            await connection.execute('SET LOCAL search_path=pg_catalog')
            await connection.execute('ALTER DEFAULT PRIVILEGES REVOKE USAGE ON TYPES FROM PUBLIC')
            await apply(source)
            if await rows(fingerprint_query) != [(source_profile['catalog_fingerprint'],)]:
                raise RuntimeError('recovery_dispatch_fixture_old_source_profile_mismatch')
            for role in CAPABILITY_ROLES:
                await connection.execute(psycopg.sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER '
                    'NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT').format(psycopg.sql.Identifier(role)))
            await apply(publication)
            if await rows(fingerprint_query) != [(publication_profile['catalog_fingerprint'],)]:
                raise RuntimeError('recovery_dispatch_fixture_old_publication_profile_mismatch')

        async with connection.transaction(force_rollback=True):
            STAGE = 'old_profile_installation'
            await install_old()
            STAGE = 'prepared_preupgrade_seed'
            state = await seed_pre_upgrade(connection)
            await connection.execute('RESET ROLE')
            STAGE = 'explicit_attestation_upgrade'
            await apply(attestation)
            if await rows('SELECT version,checksum_sha256 FROM cragkit_qdrant.schema_migrations ORDER BY version LIMIT 4') != [
                    (item.version, item.checksum) for item in (source, publication, attestation)]:
                raise RuntimeError('recovery_dispatch_fixture_three_entry_history_mismatch')
            STAGE = 'recovery_dispatch_catalog_before_probes'
            if await rows(fingerprint_query) != [(expected_profile['catalog_fingerprint'],)]:
                raise RuntimeError('recovery_dispatch_fixture_attestation_profile_mismatch')
            STAGE = 'recovery_dispatch_permission_probes'
            checks = await (run_security_probes(connection,state) if security_owner else run_probes(connection,state))
            await connection.execute('RESET ROLE')
            STAGE = 'unchanged_catalog'
            fingerprint = (await rows(fingerprint_query))[0][0]
            if fingerprint != expected_profile['catalog_fingerprint']:
                raise RuntimeError('recovery_dispatch_fixture_catalog_changed')
        STAGE = 'rollback_inventory'
        assert_rollback_inventory(original, await inventory())
        if await rows("SELECT to_regnamespace('cragkit_qdrant') IS NULL") != [(True,)]:
            raise RuntimeError('recovery_dispatch_fixture_schema_remains')
        result = dict(checks=checks + ['tls_verified', 'complete_schema_roles_memberships_defaults_rollback'],
            migrations=[[item.version, item.checksum] for item in (source, publication, attestation)],
            catalog_fingerprint=fingerprint, proof_scope=SECURITY_PROOF_SCOPE if security_owner else PROOF_SCOPE)
        validate_result(result, expected_migrations=[[item.version, item.checksum]
            for item in (source, publication, attestation)], expected_fingerprint=expected_profile['catalog_fingerprint'],
            security_owner=security_owner)
        return result


def assert_rollback_inventory(before, after):
    """Require exact role/membership/schema/default inventory restoration."""
    if type(before) is not str or type(after) is not str or before != after:
        raise RuntimeError('recovery_dispatch_fixture_inventory_rollback_mismatch')


def validate_result(result, *, expected_migrations, expected_fingerprint, security_owner=False):
    """Reject open diagnostics or invented physical-proof labels in artifacts."""
    if type(security_owner) is not bool:
        raise ValueError('recovery_dispatch_security_mode')
    if type(result) is not dict or set(result) != {'checks', 'migrations', 'catalog_fingerprint', 'proof_scope'}:
        raise ValueError('recovery_dispatch_result_shape')
    expected_checks = SECURITY_CHECKS if security_owner else CHECKS
    expected_scope = SECURITY_PROOF_SCOPE if security_owner else PROOF_SCOPE
    if result['checks'] != list(expected_checks) + ['tls_verified', 'complete_schema_roles_memberships_defaults_rollback']:
        raise ValueError('recovery_dispatch_result_checks')
    if result['proof_scope'] != expected_scope:
        raise ValueError('recovery_dispatch_result_scope')
    if (type(result['catalog_fingerprint']) is not str
            or re.fullmatch(r'[0-9a-f]{64}', result['catalog_fingerprint']) is None
            or result['catalog_fingerprint'] != expected_fingerprint):
        raise ValueError('recovery_dispatch_result_catalog')
    if result['migrations'] != expected_migrations or len(expected_migrations) != 3:
        raise ValueError('recovery_dispatch_result_history')



def main(argv=None):
    global STAGE
    STAGE = 'configuration'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    parser.add_argument('--allow-local-processes', action='store_true', required=True)
    parser.add_argument('--security-owner', action='store_true')
    args = parser.parse_args(argv)
    owned_artifacts = False
    try:
        if args.artifacts_dir.exists():
            raise RuntimeError('recovery_dispatch_fixture_fresh_artifacts_required')
        fixture = PostgresSourceFixture(args.postgres_bin, args.artifacts_dir)
        with fixture:
            owned_artifacts = True
            operation = check(fixture,security_owner=True) if args.security_owner else check(fixture)
            result = asyncio.run(asyncio.wait_for(operation, 110))
            STAGE = 'fixture_cleanup'
        result['fixture_checks'] = fixture.checks
        args.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (args.artifacts_dir/'recovery-dispatch-sql-results.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(dict(ok=True, checks=len(result['checks']), cleanup=True)))
        return 0
    except Exception as error:
        frame, locations = error.__traceback__, []
        while frame is not None:
            if Path(frame.tb_frame.f_code.co_filename).name in ('qdrant_recovery_dispatch_sql.py', 'check_qdrant_recovery_dispatch_sql.py'):
                locations.append(frame.tb_lineno)
            frame = frame.tb_next
        if owned_artifacts and args.artifacts_dir.is_dir() and locations:
            # Fixture code locations only; no SQL, error text, values or locals.
            try:
                (args.artifacts_dir/'recovery-dispatch-sql-failure-locations.json').write_text(
                    json.dumps(dict(lines=locations[:32]))+'\n')
            except Exception:
                pass
        diagnostic = error.to_dict() if isinstance(error, CleanupFailure) else describe_error(error,
            operation='primary', stage='fixture_setup')
        print(json.dumps(dict(ok=False, stage=STAGE, error=diagnostic)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
