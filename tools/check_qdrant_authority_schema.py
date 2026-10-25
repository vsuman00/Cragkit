"""Opt-in, rollback-only PostgreSQL authority-schema acceptance. Never installs."""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import secrets
from copy import deepcopy
from contextlib import asynccontextmanager

from check_python_postgres import load_config, require_client_tls, require_neon_host
from qdrant_authority_schema import ROOT, assert_sql, fixture_row, literal, migration, seed_sql, seed_statements, force_rls_sql, catalog_queries
from qdrant_native import point_identity
from runtime_diagnostics import CleanupFailure, describe_error

TABLES = ('documents', 'document_revisions', 'generations', 'members')
STAGE = 'configuration'


class _RollbackIncomplete(Exception):
    """Internal control signal; actual rollback failure is recorded separately."""


@asynccontextmanager
async def rollback_only(connection, failures, *, cleanup_timeout=3):
    transaction = connection.transaction(force_rollback=True)
    await transaction.__aenter__()
    primary = None
    try:
        yield
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            await asyncio.wait_for(transaction.__aexit__(
                type(primary) if primary is not None else None,
                primary, primary.__traceback__ if primary is not None else None), cleanup_timeout)
        except BaseException as error:
            failures.append(('fixture_transaction', error))
            if primary is None:
                raise _RollbackIncomplete() from None


async def check(config_path, artifacts):
    global STAGE
    import psycopg
    from psycopg import sql
    from cragkit._postgres_pool import PoolResource, parse_pool_config

    config = parse_pool_config(load_config(config_path))
    require_neon_host(config.host)
    PoolResource(config)._check_owned_configuration()
    item, row = migration(), fixture_row()
    role = 'cragkit_qda_probe_' + secrets.token_hex(8)
    connection = None
    primary = None
    failures = []
    checks = []

    async def command(query, params=None):
        cursor = await connection.execute(query, params, prepare=False)
        results = []
        while True:
            if cursor.description is not None:
                results.extend(await cursor.fetchall())
            if not cursor.nextset():
                return results

    async def original_state():
        # Hash metadata only. Never collect credentials or source/query text.
        histories = await command('SELECT version,checksum,applied_at FROM cragkit.migration_history ORDER BY version')
        vectors = await command('SELECT version,checksum,applied_at FROM cragkit_vector.setup_history ORDER BY version')
        roles = await command('''SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,
            rolreplication,rolbypassrls,rolconnlimit,rolvaliduntil FROM pg_roles ORDER BY rolname''')
        memberships = await command('''SELECT roleid,member,grantor,admin_option,inherit_option,set_option
            FROM pg_auth_members ORDER BY roleid,member,grantor''')
        return sha256(json.dumps([histories, vectors, roles, memberships], default=str, separators=(',', ':')).encode()).hexdigest()

    try:
        STAGE = 'connection'
        connection = await psycopg.AsyncConnection.connect(
            host=config.host, port=config.port, dbname=config.dbname, user=config.user,
            sslmode='verify-full', sslrootcert=str(config.sslrootcert), passfile=str(config.passfile),
            connect_timeout=5, autocommit=True, application_name='cragkit-qdrant-schema-probe',
            options='-c statement_timeout=30000 -c lock_timeout=2000 -c idle_in_transaction_session_timeout=15000')
        require_client_tls(connection)
        before = await original_state()
        STAGE = 'rollback_transaction'
        async with rollback_only(connection, failures):
            await command('SET LOCAL search_path=pg_catalog')
            await command('SET LOCAL standard_conforming_strings=on')
            await command(assert_sql('pg_try_advisory_xact_lock(1129464148,1) AND pg_try_advisory_xact_lock(1129464148,5)', 'authority_probe_locked'))
            await command(assert_sql("to_regnamespace('cragkit_qdrant') IS NULL", 'authority_namespace_must_be_absent'))
            await command(assert_sql("NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=" + literal(role) + ')', 'authority_probe_role_absent'))
            STAGE = 'source_schema_ddl'
            await command(item.sql)
            await command('INSERT INTO cragkit_qdrant.schema_migrations(version,checksum_sha256) VALUES(%s,%s)', (item.version, item.checksum))
            checks.append('isolated_source_schema_and_exact_checksum_ledger')
            fingerprint_sql, payload_sql = catalog_queries()
            fingerprint_rows = await command(fingerprint_sql)
            catalog_fingerprint = fingerprint_rows[0][0]
            catalog_payload = json.loads((await command(payload_sql))[0][0])
            STAGE = 'catalog_drift_detection'
            # Each intentional drift is confined to a rolled-back savepoint.
            for statement in (
                'ALTER POLICY scoped_document_read ON cragkit_qdrant.documents USING (true)',
                'ALTER FUNCTION cragkit_qdrant.valid_identity_array(text[]) VOLATILE',
                'ALTER TABLE cragkit_qdrant.documents ADD CONSTRAINT probe_extra_check CHECK (true)',
                'GRANT SELECT ON cragkit_qdrant.documents TO PUBLIC',
            ):
                async with connection.transaction(force_rollback=True):
                    await command(statement)
                    if await command(fingerprint_sql) == [(catalog_fingerprint,)]:
                        raise RuntimeError('authority_catalog_drift_not_detected')
                if await command(fingerprint_sql) != [(catalog_fingerprint,)]:
                    raise RuntimeError('authority_catalog_drift_rollback_failed')
            checks.append('catalog_rejects_policy_function_constraint_and_public_acl_drift')

            # The fixture administrator temporarily bypasses only its own new RLS
            # tables for setup. Runtime policy assertions below run with FORCE.
            for table in TABLES:
                await command(f'ALTER TABLE cragkit_qdrant.{table} NO FORCE ROW LEVEL SECURITY')
            STAGE = 'canonical_fixture_seed'
            await command(seed_sql(row))
            # Deliberately malformed writes must fail inside savepoints while
            # leaving the surrounding rollback-only probe transaction usable.
            async def rejected(statement, sqlstate):
                if '$qdauth_probe$' in statement:
                    raise ValueError('authority_probe_delimiter')
                await command("DO $qdauth_probe$ BEGIN BEGIN " + statement +
                    " RAISE EXCEPTION 'authority_invalid_write_accepted'; EXCEPTION WHEN SQLSTATE '" + sqlstate +
                    "' THEN NULL; END; END $qdauth_probe$;")
            STAGE = 'digest_span_profile_constraints'
            invalid = deepcopy(row)
            invalid['revision_id'] = 'bad-digest'
            invalid['source_sha256'] = 'a' * 64
            await rejected(seed_statements(invalid)[1], '23514')
            staged = deepcopy(row)
            staged['generation_id'] = 'gen-staging'
            staged['point_id'] = point_identity(staged)
            await command(seed_statements(staged)[2])
            invalid = deepcopy(staged)
            invalid['start_byte'] = 0
            await rejected(seed_statements(invalid)[3], '23514')
            invalid = deepcopy(staged)
            invalid['source_sha256'] = 'a' * 64
            await rejected(seed_statements(invalid)[3], '23514')
            invalid = deepcopy(staged)
            invalid['tenant_id'] = 'foreign'
            await rejected(seed_statements(invalid)[3], '23503')
            invalid = deepcopy(staged)
            invalid['generation_id'] = 'gen-profile-mismatch'
            invalid['dense_profile']['model'] = 'same-dimension-wrong-model'
            await rejected(seed_statements(invalid)[2], '23514')
            invalid = deepcopy(staged)
            invalid['generation_id'] = 'gen-sparse-mismatch'
            invalid['sparse_profile'] = None
            await rejected(seed_statements(invalid)[2], '23514')
            await command(seed_statements(staged)[3])
            await command(force_rls_sql())
            checks.append('canonical_multibyte_source_exact_member_and_digest_span_profile_constraints')
            STAGE = 'reader_role_setup'
            await command(sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT').format(sql.Identifier(role)))
            await command(sql.SQL('GRANT {} TO CURRENT_USER WITH SET TRUE').format(sql.Identifier(role)))
            await command(sql.SQL('GRANT USAGE ON SCHEMA cragkit_qdrant TO {}').format(sql.Identifier(role)))
            await command(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA cragkit_qdrant TO {}').format(sql.Identifier(role)))
            await command(sql.SQL('GRANT EXECUTE ON FUNCTION cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean), cragkit_qdrant.scope_grants(), cragkit_qdrant.valid_identity_array(text[]) TO {}').format(sql.Identifier(role)))
            await command(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(role)))
            STAGE = 'forced_reader_policies'
            await command(assert_sql("(SELECT count(*)=4 AND bool_and(relrowsecurity AND relforcerowsecurity AND row_security_active(oid)) FROM pg_class WHERE relnamespace='cragkit_qdrant'::regnamespace AND relname IN ('documents','document_revisions','generations','members'))", 'authority_forced_reader_rls'))
            await command(assert_sql('(SELECT count(*)=0 FROM cragkit_qdrant.document_revisions)', 'authority_missing_scope_denied'))
            scope = {'tenant_id': row['tenant_id'], 'collection': row['collection'], 'principal_id': 'reader-a',
                     'grant_ids': json.dumps(row['grant_ids']), 'authorization_revision': row['authorization_revision']}
            async def set_scope(changes=None):
                for key, value in (scope | (changes or {})).items():
                    await command('SELECT set_config(%s,%s,true)', ('cragkit_qdrant.' + key, value))
            await set_scope()
            for table in TABLES:
                await command(assert_sql(f'(SELECT count(*)=1 FROM cragkit_qdrant.{table})', 'authority_authorized_' + table))
            for changes in ({'tenant_id': 'foreign'}, {'collection': 'foreign'}, {'authorization_revision': 'old'},
                            {'principal_id': 'foreign', 'grant_ids': '[]'}, {'grant_ids': '[1]'},
                            {'grant_ids': '{}'}, {'grant_ids': '["\\u0000"]'},
                            {'grant_ids': '[1e1000000]'}, {'grant_ids': '[' * 5000 + '0' + ']' * 5000}):
                await set_scope(changes)
                for table in TABLES:
                    await command(assert_sql(f'(SELECT count(*)=0 FROM cragkit_qdrant.{table})', 'authority_changed_scope_denied'))
            await set_scope({'grant_ids': json.dumps(['\x01' * 255 + 'x'] * 64)})
            await command(assert_sql('(SELECT count(*)=1 FROM cragkit_qdrant.members)', 'authority_escaped_grants_within_wire_bound'))
            await set_scope({'principal_id': 'foreign'})
            await command(assert_sql('(SELECT count(*)=1 FROM cragkit_qdrant.members)', 'authority_grant_only_allowed'))
            await set_scope({'grant_ids': '[]'})
            await command(assert_sql('(SELECT count(*)=1 FROM cragkit_qdrant.members)', 'authority_principal_only_allowed'))
            if await command(fingerprint_sql) != [(catalog_fingerprint,)]:
                raise RuntimeError('authority_catalog_not_stable_across_role_grants')
            checks.append('catalog_fingerprint_stable_across_nonowner_reader_grants')

            await command(assert_sql("NOT has_table_privilege(current_user,'cragkit_qdrant.documents','INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')", 'authority_reader_has_no_mutation_privilege'))
            await command('''DO $qdauth_probe$ BEGIN
              BEGIN UPDATE cragkit_qdrant.documents SET tag='attempted-reader-write';
                RAISE EXCEPTION 'authority_reader_write_accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
            END $qdauth_probe$;''')
            checks.append('forced_reader_scope_principal_grant_revision_and_malformed_settings')
            await command('RESET ROLE')
            for table in TABLES:
                await command(f'ALTER TABLE cragkit_qdrant.{table} NO FORCE ROW LEVEL SECURITY')
            STAGE = 'immutability_and_security_fences'
            await command('''DO $qdauth_probe$ BEGIN
              BEGIN UPDATE cragkit_qdrant.document_revisions SET source_locator='changed';
                RAISE EXCEPTION 'authority_revision_update_accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
              BEGIN UPDATE cragkit_qdrant.members SET start_byte=0;
                RAISE EXCEPTION 'authority_member_update_accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
              BEGIN UPDATE cragkit_qdrant.generations SET chunker_profile='changed';
                RAISE EXCEPTION 'authority_generation_update_accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
              BEGIN UPDATE cragkit_qdrant.documents SET grant_ids='{}'::text[];
                RAISE EXCEPTION 'authority_security_revision_unchanged'; EXCEPTION WHEN check_violation THEN NULL; END;
              BEGIN UPDATE cragkit_qdrant.documents SET authorization_revision='auth-2';
                RAISE EXCEPTION 'authority_security_epoch_unchanged'; EXCEPTION WHEN check_violation THEN NULL; END;
            END $qdauth_probe$;''')
            await command("UPDATE cragkit_qdrant.documents SET tombstoned=true,authorization_revision='auth-2',mutation_epoch=mutation_epoch+1")
            await command('''DO $qdauth_probe$ BEGIN
              BEGIN UPDATE cragkit_qdrant.documents SET tombstoned=false,authorization_revision='auth-3',mutation_epoch=mutation_epoch+1;
                RAISE EXCEPTION 'authority_tombstone_restored'; EXCEPTION WHEN check_violation THEN NULL; END;
            END $qdauth_probe$;''')
            await command(force_rls_sql())
            await command(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(role)))
            await set_scope({'authorization_revision': 'auth-2'})
            for table in TABLES:
                await command(assert_sql(f'(SELECT count(*)=0 FROM cragkit_qdrant.{table})', 'authority_tombstone_denied'))
            await command('RESET ROLE')
            checks.append('immutable_content_profile_and_monotonic_security_tombstone_fences')
            STAGE = 'binary_fidelity_boundary'
            for table in TABLES:
                await command(f'ALTER TABLE cragkit_qdrant.{table} NO FORCE ROW LEVEL SECURITY')
            nul = deepcopy(row)
            nul.update(document_id='nul-document', canonical_utf8='A\0café 雪.\n'.encode(),
                       excerpt_utf8='\0café 雪'.encode(), start_byte=1, end_byte=11)
            nul['source_sha256'] = sha256(nul['canonical_utf8']).hexdigest()
            nul['text_sha256'] = sha256(nul['excerpt_utf8']).hexdigest()
            nul['point_id'] = point_identity(nul)
            await command(seed_sql(nul))
            if await command('SELECT canonical_utf8 FROM cragkit_qdrant.document_revisions WHERE document_id=%s', (nul['document_id'],)) != [(nul['canonical_utf8'],)]:
                raise RuntimeError('authority_nul_fidelity')
            corrupt = deepcopy(row)
            corrupt.update(document_id='administrator-invalid-utf8', canonical_utf8=bytes.fromhex('4120636166c3a920e99baa2eff'))
            corrupt['source_sha256'] = sha256(corrupt['canonical_utf8']).hexdigest()
            corrupt['point_id'] = point_identity(corrupt)
            await command(seed_sql(corrupt))
            # SQL stores exact bounded bytea. Native adapters, not these bytea
            # checks, must reject invalid UTF-8 even outside the selected excerpt.
            checks.append('nul_bytes_preserved_and_native_utf8_validation_boundary_explicit')
        STAGE = 'rollback_inventory'
        if await command("SELECT to_regnamespace('cragkit_qdrant') IS NULL,NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=%s)", (role,)) != [(True, True)]:
            raise RuntimeError('authority_rollback_inventory')
        after = await original_state()
        if before != after:
            raise RuntimeError('authority_existing_history_or_role_state_changed')
        checks.append('rollback_removed_schema_role_and_preserved_histories_roles_memberships')
        report = {'task': 'V5-03A', 'state': 'source_schema_probe_passed', 'migration_sha256': item.checksum, 'catalog_fingerprint': catalog_fingerprint,
                  'checks': checks, 'native_source_adapters_tested': False, 'publication_tested': False,
                  'runtime_login_tested': False, 'transaction_rolled_back': True}
    except BaseException as error:
        primary = None if type(error) is _RollbackIncomplete else error
        raise
    finally:
        if connection is not None:
            try:
                await asyncio.wait_for(connection.close(), 3)
            except BaseException as cleanup:
                failures.append(('admin_close', cleanup))
        if failures:
            raise CleanupFailure(failures, primary=primary) from None
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / 'schema-results.json').write_text(json.dumps(report, indent=2) + '\n')
    (artifacts / 'catalog-reference.json').write_text(json.dumps({
        'revision': 'QS-r1-catalog', 'server_major': 17, 'server_reference': '17.11',
        'migration_version': item.version, 'migration_sha256': item.checksum,
        'query_sha256': sha256(fingerprint_sql.encode()).hexdigest(),
        'catalog_fingerprint': catalog_fingerprint, 'catalog': catalog_payload}, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--confirm-dedicated-target', action='store_true', required=True)
    parser.add_argument('--allow-test-writes', action='store_true', required=True)
    parser.add_argument('--artifacts-dir', type=Path, default=ROOT / 'artifacts/V5/source-schema')
    args = parser.parse_args()
    try:
        async def bounded():
            async with asyncio.timeout(120):
                return await check(args.config, args.artifacts_dir)
        print(json.dumps(asyncio.run(bounded()), indent=2))
    except Exception as error:
        print(json.dumps({'state': 'failed', 'stage': STAGE, 'diagnostic': error.to_dict() if isinstance(error, CleanupFailure) else describe_error(error, operation='primary', stage='fixture_setup')}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
