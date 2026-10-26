"""Explicit disposable PostgreSQL publication-schema acceptance; never hosted."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
import json
from pathlib import Path

from qdrant_authority_schema import ROOT, catalog_queries, migration as source_migration
from qdrant_source_native import PostgresSourceFixture
from runtime_diagnostics import CleanupFailure, describe_error

STAGE = 'configuration'


@asynccontextmanager
async def owned_connection(connection):
    """Close without the driver's implicit commit or raw rollback warning."""
    primary = None
    try:
        yield connection
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            await asyncio.wait_for(connection.close(), 3)
        except BaseException as error:
            raise CleanupFailure([('admin_close',error)],primary=primary,stage='fixture_setup') from None


async def check(fixture):
    """Borrow one private fixture connection and roll back every schema change."""
    global STAGE
    import psycopg
    from qdrant_publication_schema import CAPABILITY_ROLES, insert_sql, migration, rejected_sql, run_probes

    STAGE = 'connection'
    config = fixture.config
    connection = await psycopg.AsyncConnection.connect(
        host=config['host'], port=config['port'], dbname=config['dbname'],
        user=config['user'], passfile=config['passfile'], sslmode='verify-full',
        sslrootcert=config['sslrootcert'], connect_timeout=5, autocommit=True,
        options='-c statement_timeout=10000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=15000')
    async with owned_connection(connection):
        if not connection.pgconn.ssl_in_use:
            raise RuntimeError('publication_fixture_tls_required')

        async def rows(query, params=None):
            cursor = await connection.execute(query, params, prepare=False)
            return await cursor.fetchall()

        async def snapshot():
            # Metadata only; no source rows, role passwords or connection strings.
            roles = await rows('SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,rolreplication,rolbypassrls FROM pg_roles ORDER BY rolname')
            memberships = await rows('SELECT roleid,member,grantor,admin_option,inherit_option,set_option FROM pg_auth_members ORDER BY roleid,member,grantor')
            schemas = await rows('SELECT nspname,nspowner,nspacl::text FROM pg_namespace ORDER BY nspname')
            defaults = await rows('SELECT defaclrole,defaclnamespace,defaclobjtype,defaclacl::text FROM pg_default_acl ORDER BY defaclrole,defaclnamespace,defaclobjtype')
            return sha256(json.dumps([roles,memberships,schemas,defaults], separators=(',', ':')).encode()).hexdigest()

        before = await snapshot()
        source, publication = source_migration(), migration()
        fingerprint_query, payload_query = catalog_queries()
        source_profile = json.loads((ROOT/'contracts/fixtures/qdrant_authority_catalog.json').read_text())

        async def install():
            global STAGE
            STAGE = 'source_migration'
            await connection.execute('SET LOCAL search_path=pg_catalog')
            await connection.execute('ALTER DEFAULT PRIVILEGES REVOKE USAGE ON TYPES FROM PUBLIC')
            await connection.execute(source.sql, prepare=False)
            await connection.execute('INSERT INTO cragkit_qdrant.schema_migrations(version,checksum_sha256) VALUES(%s,%s)', (source.version,source.checksum))
            if await rows(fingerprint_query) != [(source_profile['catalog_fingerprint'],)]:
                raise RuntimeError('publication_fixture_source_catalog_mismatch')
            # Stable NOLOGIN capability roles are part of the explicit fixture
            # setup, not an automatic runtime provisioning path.
            for role in CAPABILITY_ROLES:
                await connection.execute(psycopg.sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT').format(psycopg.sql.Identifier(role)))
            STAGE = 'publication_migration'
            await connection.execute(publication.sql, prepare=False)
            await connection.execute('INSERT INTO cragkit_qdrant.schema_migrations(version,checksum_sha256) VALUES(%s,%s)', (publication.version,publication.checksum))

        async with connection.transaction(force_rollback=True):
            await install()
            STAGE = 'catalog_capture'
            fingerprint = (await rows(fingerprint_query))[0][0]
            catalog = json.loads((await rows(payload_query))[0][0])
            STAGE = 'native_probes'
            checks = await run_probes(connection)
            await connection.execute('RESET ROLE')
        STAGE = 'rollback_inventory'
        if before != await snapshot():
            raise RuntimeError('publication_fixture_rollback_mismatch')
        # Fresh transactions are necessary: PostgreSQL refuses an isolation
        # change after the current transaction has already queried data.
        for isolation in ('REPEATABLE READ','SERIALIZABLE'):
            async with connection.transaction(force_rollback=True):
                await connection.execute('SET TRANSACTION ISOLATION LEVEL ' + isolation)
                await install()
                STAGE = 'isolation_admission'
                settings = {'tenant_id':'isolation-tenant','collection':'isolation-collection',
                    'writer_document_id':'isolation-document','writer_intent_id':'isolation-intent',
                    'writer_owner_token':'00000000-0000-4000-8000-000000000001',
                    'backend_instance_id':'isolation-instance','principal_id':'isolation-principal',
                    'grant_ids':'[]','authorization_revision':'isolation-auth'}
                for name,value in settings.items():
                    await connection.execute('SELECT set_config(%s,%s,true)',('cragkit_qdrant.'+name,value))
                await connection.execute('SET LOCAL ROLE cragkit_qdrant_writer')
                statement = insert_sql('documents',{'tenant_id':settings['tenant_id'],
                    'collection':settings['collection'],'document_id':settings['writer_document_id'],
                    'authorization_revision':settings['authorization_revision']})
                await connection.execute(rejected_sql(statement,'23514'))
                await connection.execute('RESET ROLE')
                await connection.execute('SET LOCAL ROLE cragkit_qdrant_supervisor')
                statement = insert_sql('backend_instances',{'instance_id':settings['backend_instance_id'],
                    'backend_namespace':'isolation-backend','storage_identity':'isolation-storage',
                    'supervisor_id':'isolation-supervisor'})
                await connection.execute(rejected_sql(statement,'23514'))
                await connection.execute('RESET ROLE')
            if before != await snapshot():
                raise RuntimeError('publication_fixture_isolation_rollback_mismatch')
            checks.append(isolation.lower().replace(' ','_')+'_writer_supervisor_admission_denied')
        STAGE = 'rollback_inventory'
        if await rows("SELECT to_regnamespace('cragkit_qdrant') IS NULL") != [(True,)]:
            raise RuntimeError('publication_fixture_schema_remains')
        return {'checks': checks + ['tls_verified', 'complete_schema_role_membership_defaults_rollback'],
                'migrations': [[item.version,item.checksum] for item in (source,publication)],
                'catalog_fingerprint': fingerprint, 'catalog': catalog}


def main(argv=None):
    global STAGE
    STAGE = 'configuration'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    parser.add_argument('--allow-local-processes', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        if (args.artifacts_dir/'publication-schema-results.json').exists():
            raise RuntimeError('publication_fixture_fresh_artifacts_required')
        fixture = PostgresSourceFixture(args.postgres_bin,args.artifacts_dir)
        with fixture:
            result = asyncio.run(asyncio.wait_for(check(fixture), 90))
            STAGE = 'fixture_cleanup'
        result['fixture_checks'] = fixture.checks
        # Success is written only after proven server shutdown/private cleanup.
        args.artifacts_dir.mkdir(parents=True,exist_ok=True)
        (args.artifacts_dir/'publication-schema-results.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'ok':True,'checks':len(result['checks']),'cleanup':True}))
        return 0
    except Exception as error:
        diagnostic = error.to_dict() if isinstance(error,CleanupFailure) else describe_error(
            error,operation='primary',stage='fixture_setup')
        print(json.dumps({'ok':False,'stage':STAGE,'error':diagnostic}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
