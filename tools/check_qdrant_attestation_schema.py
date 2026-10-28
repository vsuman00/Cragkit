"""Explicit rollback-only PostgreSQL preparation-attestation schema acceptance."""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
from pathlib import Path

from check_qdrant_publication_schema import owned_connection
from qdrant_authority_schema import ROOT, catalog_queries, migration as source_migration
from qdrant_publication_schema import (CAPABILITY_ROLES, insert_sql, rejected_sql,
    migration as publication_migration)
from qdrant_source_native import PostgresSourceFixture
from runtime_diagnostics import CleanupFailure, describe_error

STAGE = 'configuration'


async def check(fixture):
    """Capture a new exact profile only after upgrade/constraint/rollback probes."""
    global STAGE
    import psycopg
    from qdrant_attestation_schema import migration, seed_pre_upgrade, run_probes

    config = fixture.config
    STAGE = 'connection'
    connection = await psycopg.AsyncConnection.connect(host=config['host'], port=config['port'],
        dbname=config['dbname'], user=config['user'], passfile=config['passfile'],
        sslmode='verify-full', sslrootcert=config['sslrootcert'], connect_timeout=5,
        autocommit=True, options='-c statement_timeout=10000 -c lock_timeout=1000 '
            '-c idle_in_transaction_session_timeout=15000')
    async with owned_connection(connection):
        if not connection.pgconn.ssl_in_use:
            raise RuntimeError('attestation_fixture_tls_required')
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
        fingerprint_query, catalog_query = catalog_queries()
        source_profile = json.loads((ROOT/'contracts/fixtures/qdrant_authority_catalog.json').read_text())
        publication_profile = json.loads((ROOT/'contracts/fixtures/qdrant_publication_catalog.json').read_text())
        async def apply(item):
            await connection.execute(item.sql, prepare=False)
            await connection.execute('INSERT INTO cragkit_qdrant.schema_migrations '
                '(version,checksum_sha256) VALUES(%s,%s)', (item.version, item.checksum))
        async def install_old():
            await connection.execute('SET LOCAL search_path=pg_catalog')
            await connection.execute('ALTER DEFAULT PRIVILEGES REVOKE USAGE ON TYPES FROM PUBLIC')
            await apply(source)
            if await rows(fingerprint_query) != [(source_profile['catalog_fingerprint'],)]:
                raise RuntimeError('attestation_fixture_old_source_profile_mismatch')
            for role in CAPABILITY_ROLES:
                await connection.execute(psycopg.sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER '
                    'NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT').format(psycopg.sql.Identifier(role)))
            await apply(publication)
            if await rows(fingerprint_query) != [(publication_profile['catalog_fingerprint'],)]:
                raise RuntimeError('attestation_fixture_old_publication_profile_mismatch')

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
                raise RuntimeError('attestation_fixture_three_entry_history_mismatch')
            STAGE = 'attestation_constraint_probes'
            checks = await run_probes(connection, state)
            await connection.execute('RESET ROLE')
            STAGE = 'catalog_capture'
            fingerprint = (await rows(fingerprint_query))[0][0]
            catalog = json.loads((await rows(catalog_query))[0][0])
        STAGE = 'rollback_inventory'
        if await inventory() != original:
            raise RuntimeError('attestation_fixture_upgrade_rollback_mismatch')

        for isolation in ('REPEATABLE READ', 'SERIALIZABLE'):
            async with connection.transaction(force_rollback=True):
                await connection.execute('SET TRANSACTION ISOLATION LEVEL ' + isolation)
                STAGE = 'higher_isolation_installation'
                await install_old()
                await apply(attestation)
                STAGE = 'attestation_isolation_denial'
                # Administrative fixture injection isolates the trigger's
                # isolation check; it is not runtime provenance or readback.
                row = dict(tenant_id='isolation-tenant', collection='isolation-collection',
                    document_id='isolation-document', intent_id='isolation-intent',
                    instance_id='isolation-instance', owner_token='00000000-0000-4000-8000-000000000001',
                    backend_epoch=2, authorization_revision='isolation-auth', mutation_epoch=1,
                    manifest_sha256='a'*64, expected_active_generation_id=None,
                    credential_generation='isolation-key', verification_id='isolation-verification',
                    readback_sha256='b'*64)
                await connection.execute(rejected_sql(insert_sql('preparation_attestations', row), '23514'), prepare=False)
            if await inventory() != original:
                raise RuntimeError('attestation_fixture_isolation_rollback_mismatch')
            checks.append(isolation.lower().replace(' ', '_') + '_attestation_denied')
        if await rows("SELECT to_regnamespace('cragkit_qdrant') IS NULL") != [(True,)]:
            raise RuntimeError('attestation_fixture_schema_remains')
        return dict(checks=checks + ['tls_verified', 'complete_schema_roles_memberships_defaults_rollback'],
            migrations=[[item.version, item.checksum] for item in (source, publication, attestation)],
            catalog_fingerprint=fingerprint, catalog=catalog, proof_scope='attestation_sql_schema_only')


def main(argv=None):
    global STAGE
    STAGE = 'configuration'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    parser.add_argument('--allow-local-processes', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        if args.artifacts_dir.exists():
            raise RuntimeError('attestation_fixture_fresh_artifacts_required')
        fixture = PostgresSourceFixture(args.postgres_bin, args.artifacts_dir)
        with fixture:
            result = asyncio.run(asyncio.wait_for(check(fixture), 110))
            STAGE = 'fixture_cleanup'
        result['fixture_checks'] = fixture.checks
        args.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (args.artifacts_dir/'attestation-schema-results.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(dict(ok=True, checks=len(result['checks']), cleanup=True)))
        return 0
    except Exception as error:
        frame, locations = error.__traceback__, []
        while frame is not None:
            if Path(frame.tb_frame.f_code.co_filename).name == 'qdrant_attestation_schema.py':
                locations.append(frame.tb_lineno)
            frame = frame.tb_next
        if args.artifacts_dir.is_dir() and locations:
            # Fixture code locations only; no SQL, error text, values or locals.
            (args.artifacts_dir/'attestation-failure-locations.json').write_text(
                json.dumps(dict(lines=locations[:32]))+'\n')
        diagnostic = error.to_dict() if isinstance(error, CleanupFailure) else describe_error(error,
            operation='primary', stage='fixture_setup')
        print(json.dumps(dict(ok=False, stage=STAGE, error=diagnostic)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
