"""Opt-in isolated native PostgreSQL/Qdrant source-disclosure acceptance."""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from hashlib import sha256
import json
import logging
import os
import re
from pathlib import Path
import secrets

from check_qdrant import compare
from qdrant_authority_schema import ROOT, fixture_row, migration, seed_statements, catalog_queries
from qdrant_native import QdrantFixture
from qdrant_source_cases import run_cases
from runtime_diagnostics import CleanupFailure, describe_error

ACTIONS = frozenset(('reset_active', 'reset_staging', 'reset_invalid_utf8', 'revoke',
                     'metadata', 'tombstone', 'supersede', 'source_outage'))
STAGE = 'configuration'
NODE_STEP = 'not_started'


class NodeCaseFailure(RuntimeError):
    def __init__(self, stage, outcome, detail=None):
        super().__init__('native_node_case_failure')
        self.observation = {'stage': stage, 'outcome': outcome, **(detail or {})}


async def node_cases(value, mutate):
    global NODE_STEP
    """Only fixed mutation names cross back into the administrator parent."""
    environment = {key: child for key, child in os.environ.items()
                   if not key.startswith('PG') and key not in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NODE_USE_ENV_PROXY')}
    process = await asyncio.create_subprocess_exec('node', str(ROOT / 'tools/check_typescript_qdrant_source.mjs'),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=environment, limit=65536)
    error_task = asyncio.create_task(process.stderr.read(65537))
    async def send(frame):
        process.stdin.write((json.dumps(frame, separators=(',', ':')) + '\n').encode())
        await process.stdin.drain()
    try:
        await send({'type': 'init', 'data': value})
        result = None
        NODE_STEP = 'initial_frame_sent'
        async with asyncio.timeout(60):
            while line := await process.stdout.readline():
                frame = json.loads(line)
                if type(frame) is not dict:
                    raise RuntimeError('node_source_protocol_shape')
                if frame.get('type') == 'mutation' and set(frame) == {'type', 'action'} and frame['action'] in ACTIONS:
                    if result is not None:
                        raise RuntimeError('node_source_mutation_after_result')
                    NODE_STEP = 'mutation_' + frame['action']
                    await mutate(frame['action'])
                    await send({'type': 'mutation_result', 'action': frame['action'], 'ok': True})
                elif (frame.get('type') == 'failure' and {'type', 'stage', 'outcome'} <= set(frame)
                      and set(frame) <= {'type', 'stage', 'outcome', 'phase', 'error_class'}):
                    ids = [case['id'] for case in value.get('cases', [])]
                    stages = {'input', 'reader_login_preflight', 'reader_preflight_inputs', 'reader_preflight_connect',
                              'reader_preflight_query', 'reader_preflight_assert', 'reader_preflight_negative', 'reader_pool_open', 'candidate_initialize'} | {
                        prefix + case_id for prefix in ('reset_', 'candidate_search_', 'source_initialize_', 'source_flow_', 'source_assert_') for case_id in ids}
                    outcomes = {'internal', 'tls_error', 'InvalidRequest', 'UnauthorizedScope', 'UnsupportedCapability',
                                'IndexNotReady', 'EmbeddingProfileMismatch', 'ProviderUnavailable',
                                'DeadlineExceeded', 'ContextBudgetTooSmall', 'IntegrityViolation',
                                'ERR_TLS_CERT_ALTNAME_INVALID', 'SELF_SIGNED_CERT_IN_CHAIN',
                                'DEPTH_ZERO_SELF_SIGNED_CERT', 'CERT_HAS_EXPIRED',
                                'UNABLE_TO_VERIFY_LEAF_SIGNATURE', 'INVALID_PURPOSE',
                                'EPERM', 'EACCES', 'ENETUNREACH', 'EHOSTUNREACH', 'ENOTFOUND', 'EAI_AGAIN',
                                'ECONNREFUSED', 'ECONNRESET', '53300', '28P01', 'ETIMEDOUT',
                                'UNABLE_TO_GET_ISSUER_CERT_LOCALLY', 'UNABLE_TO_GET_ISSUER_CERT',
                                'CERT_UNTRUSTED', 'CERT_REJECTED', 'CERT_NOT_YET_VALID', 'CERT_SIGNATURE_FAILURE'}
                    if (type(frame['stage']) is not str or type(frame['outcome']) is not str
                            or frame['stage'] not in stages
                            or frame['outcome'] not in outcomes and re.fullmatch(r'[0-9A-Z]{5}', frame['outcome']) is None):
                        raise RuntimeError('node_source_failure_frame')
                    detail = {}
                    if 'phase' in frame or 'error_class' in frame:
                        phases = {'created', 'tcp_connected', 'tls_connected', 'sasl_initial', 'sasl_continue', 'sasl_final', 'ready'}
                        classes = {'Error', 'TypeError', 'RangeError', 'DOMException', 'CragkitError', 'unknown'}
                        if (type(frame.get('phase')) is not str or frame['phase'] not in phases
                                or type(frame.get('error_class')) is not str or frame['error_class'] not in classes):
                            raise RuntimeError('node_source_failure_detail')
                        detail = {'phase': frame['phase'], 'error_class': frame['error_class']}
                    raise NodeCaseFailure(frame['stage'], frame['outcome'], detail)
                elif frame.get('type') == 'result' and set(frame) == {'type', 'cases'} and result is None:
                    result = frame['cases']
                    NODE_STEP = 'result_received'
                    process.stdin.close()
                else:
                    raise RuntimeError('node_source_protocol_frame')
            await process.wait()
            errors = await error_task
            if process.returncode != 0 or result is None or errors:
                raise RuntimeError('node_source_child_failed')
        return result
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 3)
            except TimeoutError:
                process.kill()
                await asyncio.wait_for(process.wait(), 3)
        if not error_task.done():
            error_task.cancel()
        await asyncio.gather(error_task, return_exceptions=True)
        if process.stdin is not None:
            process.stdin.close()


async def check(pg, qdrant):
    global STAGE
    import psycopg
    from psycopg import sql
    from cragkit._qdrant_contract import CandidatePayload
    from qdrant_source_native import PostgresSourceFixture
    from check_python_postgres import require_client_tls

    assert isinstance(pg, PostgresSourceFixture)
    admin = None
    failures = []
    primary = None
    row = fixture_row()
    scenarios = json.loads((ROOT / 'contracts/fixtures/qdrant_source_native.json').read_text())
    reader = 'qs_reader_' + secrets.token_hex(8)
    password = secrets.token_urlsafe(48)
    reader_config = pg.reader_config(reader, password)
    checks = []

    async def connect_admin():
        config = pg.config
        connection = await psycopg.AsyncConnection.connect(host=config['host'], port=config['port'],
            dbname=config['dbname'], user=config['user'], passfile=config['passfile'],
            sslmode='verify-full', sslrootcert=config['sslrootcert'], connect_timeout=3,
            autocommit=True, options='-c statement_timeout=10000 -c lock_timeout=1000')
        require_client_tls(connection)
        return connection

    async def command(query, params=None):
        async with asyncio.timeout(10):
            cursor = await admin.execute(query, params, prepare=False)
            results = []
            while True:
                if cursor.description is not None:
                    results.extend(await cursor.fetchall())
                if not cursor.nextset():
                    return results

    async def replace_vector(selected):
        payload = {key: selected[key] for key in CandidatePayload.model_fields if selected.get(key) is not None}
        points = [{'id': selected['point_id'], 'payload': payload,
                   'vector': {'dense': qdrant.dense, 'sparse': qdrant.sparse}}]
        response = await asyncio.to_thread(qdrant.request, 'PUT', qdrant.collection_path + '/points?wait=true&ordering=strong', {'points': points})
        if response['result']['status'] != 'completed':
            raise RuntimeError('source_vector_fixture_incomplete')
        count = await asyncio.to_thread(qdrant.request, 'POST', qdrant.collection_path + '/points/count', {'exact': True})
        if count['result']['count'] != 1:
            raise RuntimeError('source_vector_fixture_inventory')

    async def mutate(action):
        nonlocal admin
        if action not in ACTIONS:
            raise ValueError('source_mutation_not_allowed')
        if action == 'source_outage':
            await admin.close()
            admin = None
            await asyncio.to_thread(pg.stop)
            return
        if action.startswith('reset_'):
            selected = deepcopy(row)
            if action == 'reset_invalid_utf8':
                selected['canonical_utf8'] = bytes.fromhex('4120636166c3a920e99baa2eff')
                selected['source_sha256'] = sha256(selected['canonical_utf8']).hexdigest()
            async with admin.transaction():
                await command('UPDATE cragkit_qdrant.documents SET active_generation_id=NULL')
                for table in ('members', 'generations', 'document_revisions', 'documents'):
                    await command('DELETE FROM cragkit_qdrant.' + table)
                statements = seed_statements(selected)
                for statement in statements[:4] if action == 'reset_staging' else statements:
                    await command(statement)
            await replace_vector(selected)
            return
        async with admin.transaction():
            if action == 'supersede':
                generation = deepcopy(row)
                generation['generation_id'] = 'gen-2'
                from qdrant_native import point_identity
                generation['point_id'] = point_identity(generation)
                statements = seed_statements(generation)
                await command('UPDATE cragkit_qdrant.generations SET published=false')
                for statement in statements[2:]:
                    await command(statement)
            else:
                update = {'revoke': "principal_ids='{}',grant_ids='{}'", 'metadata': "kind='blocked'",
                          'tombstone': 'tombstoned=true'}[action]
                await command("UPDATE cragkit_qdrant.documents SET " + update +
                              ",authorization_revision='auth-2',mutation_epoch=mutation_epoch+1")

    previous_logging = logging.getLogger('psycopg.pool').disabled
    logging.getLogger('psycopg.pool').disabled = True
    try:
        STAGE = 'local_tls_schema_and_reader'
        admin = await connect_admin()
        if await command("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()") != [(True,)]:
            raise RuntimeError('source_admin_tls_not_observed')
        # Match the frozen private-domain profile also used by the Neon reference owner.
        await command('ALTER DEFAULT PRIVILEGES REVOKE USAGE ON TYPES FROM PUBLIC')
        item = migration()
        await command(item.sql)
        await command('INSERT INTO cragkit_qdrant.schema_migrations(version,checksum_sha256) VALUES(%s,%s)', (item.version, item.checksum))
        await command(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT PASSWORD {}').format(sql.Identifier(reader), sql.Literal(password)))
        await command(sql.SQL('GRANT USAGE ON SCHEMA cragkit_qdrant TO {}').format(sql.Identifier(reader)))
        await command(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA cragkit_qdrant TO {}').format(sql.Identifier(reader)))
        await command(sql.SQL('GRANT EXECUTE ON FUNCTION cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean),cragkit_qdrant.scope_grants(),cragkit_qdrant.valid_identity_array(text[]) TO {}').format(sql.Identifier(reader)))
        await command('SET search_path=pg_catalog')
        fingerprint_sql, payload_sql = catalog_queries()
        reference = json.loads((ROOT / 'contracts/fixtures/qdrant_authority_catalog.json').read_text())
        observed_hash = (await command(fingerprint_sql))[0][0]
        observed_catalog = json.loads((await command(payload_sql))[0][0])
        (pg.artifacts / 'observed-catalog.json').write_text(json.dumps(observed_catalog, indent=2) + '\n')
        if observed_hash != reference['catalog_fingerprint']:
            raise RuntimeError('source_local_catalog_reference_mismatch')
        from cragkit._qdrant_authority import _CATALOG_SQL
        if await command(_CATALOG_SQL) != [(True,)]:
            raise RuntimeError('source_local_catalog_shape_mismatch')
        checks.append('isolated_tls_schema_and_restricted_login_created')
        # Replace only the eight points owned by the Qdrant fixture.
        deleted = await asyncio.to_thread(qdrant.request, 'POST', qdrant.collection_path + '/points/delete?wait=true&ordering=strong',
                                         {'points': [payload_id(p) for p in qdrant.payloads.values()]})
        if deleted['result']['status'] != 'completed':
            raise RuntimeError('source_vector_reset_incomplete')
        value = {'postgres_config': reader_config, 'qdrant': qdrant.child_input(),
                 'request': json.loads((ROOT / 'contracts/fixtures/qdrant_sources.json').read_text())['request'],
                 'scope': qdrant.scope, 'cases': scenarios['cases']}
        STAGE = 'python_native_source_cases'
        python = await run_cases(value, mutate)
        await asyncio.to_thread(pg.start)
        admin = await connect_admin()
        STAGE = 'node_native_source_cases'
        node = await node_cases(value, mutate)
        if not compare(python, node):
            raise RuntimeError('source_runtime_result_parity')
        checks.append('node_tls_rejected_wrong_hostname_and_untrusted_private_certificate')
        checks.append('full_source_result_and_candidate_ledger_parity')
        return {'task': 'V5-03D', 'contract_revision': scenarios['revision'], 'runtime_cases_each': len(python),
                'checks': checks, 'python': python, 'node': node, 'live_model_calls': 0,
                'publication_compatibility_tested': False, 'hosted_database_tested': False}
    except BaseException as error:
        primary = error
        if isinstance(error, NodeCaseFailure):
            try:
                with open(pg._work / 'postgres.log', 'rb') as log:
                    content = log.read(1048576)
                error.observation['server_flags'] = {
                    'ssl_failure': b'could not accept SSL connection' in content,
                    'capacity_failure': b'remaining connection slots' in content or b'too many clients' in content,
                    'password_failure': b'password authentication failed' in content,
                }
                if admin is not None:
                    error.observation['client_backends'] = (await command(
                        "SELECT count(*)::int FROM pg_stat_activity WHERE backend_type='client backend'"))[0][0]
            except Exception:
                error.observation['server_probe_unavailable'] = True
        raise
    finally:
        logging.getLogger('psycopg.pool').disabled = previous_logging
        if admin is not None:
            try:
                await asyncio.wait_for(admin.close(), 3)
            except BaseException as error:
                failures.append(('source_admin_close', error))
        if failures:
            raise CleanupFailure(failures, primary=primary) from None


def payload_id(payload):
    from qdrant_native import point_identity
    return point_identity(payload)


def main():
    from qdrant_source_native import PostgresSourceFixture
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--server-binary', type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--allow-local-processes', action='store_true', required=True)
    parser.add_argument('--artifacts-dir', type=Path, default=ROOT / 'artifacts/V5/native-sources')
    args = parser.parse_args()
    try:
        with QdrantFixture(args.server_binary, args.artifacts_dir, args.binary_sha256) as qdrant:
            with PostgresSourceFixture(args.postgres_bin, args.artifacts_dir) as postgres:
                report = asyncio.run(check(postgres, qdrant))
            report['postgres_checks'] = postgres.checks
        report['qdrant_checks'] = qdrant.checks
        args.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (args.artifacts_dir / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({key: value for key, value in report.items() if key not in ('python', 'node')}, indent=2))
    except Exception as error:
        from qdrant_source_cases import STEP, SourceCaseMismatch
        print(json.dumps({'state': 'failed', 'stage': STAGE, 'native_step': STEP, 'node_step': NODE_STEP,
                          'case_observation': error.observation if isinstance(error, (SourceCaseMismatch, NodeCaseFailure)) else None,
                          'diagnostic': error.to_dict() if isinstance(error, CleanupFailure) else describe_error(error, operation='primary', stage='fixture_setup')}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
