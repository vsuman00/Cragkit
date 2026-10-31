"""Disposable native PGO-r1 storage, migration and runtime acceptance; no inference."""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import socket
import sys

from check_postgres import connection_environment, execute
from check_postgres_profiles import MARKER, profile_upgrade_script
from postgres_vector_fixture import V6PostgresFixture

ROOT = Path(__file__).resolve().parents[1]
CASE_NAMES = ['fake_stage_publish_replay', 'fake_dense_source', 'fake_hybrid_source',
              'tenant_scope_negative', 'principal_scope_negative', 'required_filter_negative',
              'openai_default_refusal', 'openai_retrieval_dispatch_boundary',
              'openai_indexer_dispatch_boundary', 'openai_corrective_accounting']


def require(value, code):
    if not value:
        raise RuntimeError(code)


async def connect(config):
    import psycopg
    connection = await psycopg.AsyncConnection.connect(
        **{key: value for key, value in config.items() if key != 'max_size'},
        sslmode='verify-full', autocommit=True, connect_timeout=5,
        options='-c statement_timeout=30000 -c lock_timeout=2000')
    if connection.pgconn.ssl_in_use is not True:
        await connection.close()
        raise RuntimeError('profile_tls_required')
    return connection


async def snapshot(admin):
    """Fingerprint native data privately; never export source text or SQL errors."""
    result = {}
    for table, order in (
        ('cragkit.migration_history', 'version'), ('cragkit_vector.setup_history', 'version'),
        ('cragkit.documents', 'tenant_id,collection_id,document_id'),
        ('cragkit.index_generations', 'tenant_id,collection_id,document_id,generation_id'),
        ('cragkit.chunk_vectors_fake_1536', 'tenant_id,collection_id,document_id,generation_id,chunk_id'),
    ):
        row = await (await admin.execute(
            f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY {order}),'[]'::jsonb)::text FROM {table} t"
        )).fetchone()
        result[table] = sha256(row[0].encode()).hexdigest()
    return result


async def refused(admin, script, *, state='CV002'):
    import psycopg
    try:
        await admin.execute(script)
    except psycopg.Error as error:
        await admin.rollback()
        require(error.sqlstate == state, 'unexpected_profile_refusal')
    else:
        raise RuntimeError('profile_drift_not_refused')


async def runtime_admission(config, *, live=True, write=False, accepted):
    from cragkit._postgres_profiles import validate_profile_storage
    from cragkit.embeddings import FAKE_PROFILE, OPENAI_PROFILE
    from cragkit.errors import UnsupportedCapability
    from cragkit.vector_ingestion import _VECTOR_CAPABILITY_SQL
    async with await connect(config) as connection:
        async with connection.transaction():
            await connection.execute('SET LOCAL search_path=pg_catalog')
            async def query(statement):
                return await (await connection.execute(statement)).fetchall()
            try:
                await validate_profile_storage(query, OPENAI_PROFILE if live else FAKE_PROFILE,
                                               _VECTOR_CAPABILITY_SQL, write=write)
            except UnsupportedCapability:
                require(not accepted, 'valid_profile_refused')
            else:
                require(accepted, 'unsafe_profile_admitted')


async def operator_cases(fixture, roles):
    from psycopg import sql
    checks = []
    async with await connect(fixture.config) as admin:
        before = await snapshot(admin)
        await refused(admin, profile_upgrade_script(apply=False))
        checks.append('legacy_readonly_reports_pending')
        interrupted = profile_upgrade_script(apply=True).replace('COMMIT;', 'SELECT 1/0;\nCOMMIT;')
        await refused(admin, interrupted, state='22012')
        require(await snapshot(admin) == before, 'interrupted_profile_data_changed')
        require(await (await admin.execute("SELECT to_regclass('cragkit.chunk_vectors_openai_te3small_1536') IS NULL")).fetchone() == (True,),
                'interrupted_profile_table_remains')
        checks.append('interrupted_upgrade_rolls_back_ddl_and_history')
        await admin.execute("INSERT INTO cragkit_vector.setup_history(version,checksum) VALUES('0004_unknown',repeat('a',64))")
        await refused(admin, profile_upgrade_script(apply=True))
        await runtime_admission(roles.reader, live=False, accepted=False)
        await admin.execute("DELETE FROM cragkit_vector.setup_history WHERE version='0004_unknown'")
        require(await snapshot(admin) == before, 'history_probe_not_restored')
        checks.append('unknown_history_refused_without_repair')
        await admin.execute(profile_upgrade_script(apply=True))
        upgraded = await snapshot(admin)
        require(all(upgraded[key] == digest for key, digest in before.items()
                    if key != 'cragkit_vector.setup_history'), 'upgrade_changed_existing_data')
        checks.append('upgrade_preserves_active_generation_vectors_and_lexical_history')
        await admin.execute(profile_upgrade_script(apply=False))
        await admin.execute(profile_upgrade_script(apply=True))
        require(await snapshot(admin) == upgraded, 'idempotent_upgrade_changed_history')
        checks.append('readonly_check_and_idempotent_apply_preserve_timestamps')
        for config in (roles.reader, roles.writer):
            permission = await (await admin.execute(
                "SELECT has_table_privilege(%s,'cragkit.chunk_vectors_openai_te3small_1536','SELECT')",
                (config['user'],))).fetchone()
            require(permission == (False,), 'upgrade_implicitly_granted_access')
            await runtime_admission(config, live=False, write=config is roles.writer, accepted=True)
            await runtime_admission(config, write=config is roles.writer, accepted=False)
        checks.append('no_automatic_grants_fake_still_works_live_refuses')
        for config in (roles.reader, roles.writer):
            await admin.execute(sql.SQL('GRANT SELECT ON cragkit.chunk_vectors_openai_te3small_1536 TO {}')
                                .format(sql.Identifier(config['user'])))
        await runtime_admission(roles.reader, accepted=True)
        await runtime_admission(roles.writer, write=True, accepted=False)
        await admin.execute(sql.SQL('GRANT INSERT ON cragkit.chunk_vectors_openai_te3small_1536 TO {}')
                            .format(sql.Identifier(roles.writer['user'])))
        await runtime_admission(roles.writer, write=True, accepted=False)
        await admin.execute(sql.SQL('GRANT UPDATE ON cragkit.chunk_vectors_openai_te3small_1536 TO {}')
                            .format(sql.Identifier(roles.writer['user'])))
        await runtime_admission(roles.writer, write=True, accepted=True)
        checks.append('selected_read_and_all_write_privileges_required')
        probes = (
            ('new_table_rls_disabled', 'ALTER TABLE cragkit.chunk_vectors_openai_te3small_1536 DISABLE ROW LEVEL SECURITY',
             'ALTER TABLE cragkit.chunk_vectors_openai_te3small_1536 ENABLE ROW LEVEL SECURITY'),
            ('fake_table_rls_disabled', 'ALTER TABLE cragkit.chunk_vectors_fake_1536 DISABLE ROW LEVEL SECURITY',
             'ALTER TABLE cragkit.chunk_vectors_fake_1536 ENABLE ROW LEVEL SECURITY'),
            ('new_table_public_select', 'GRANT SELECT ON cragkit.chunk_vectors_openai_te3small_1536 TO PUBLIC',
             'REVOKE ALL ON cragkit.chunk_vectors_openai_te3small_1536 FROM PUBLIC'),
            ('disabled_fk_triggers', 'ALTER TABLE cragkit.chunk_vectors_openai_te3small_1536 DISABLE TRIGGER ALL',
             'ALTER TABLE cragkit.chunk_vectors_openai_te3small_1536 ENABLE TRIGGER ALL'),
            ('disabled_registry_immutable_trigger', 'ALTER TABLE cragkit.embedding_profiles DISABLE TRIGGER immutable_embedding_profile',
             'ALTER TABLE cragkit.embedding_profiles ENABLE TRIGGER immutable_embedding_profile'),
            ('missing_vector_table', 'ALTER TABLE cragkit.chunk_vectors_openai_te3small_1536 RENAME TO profile_probe_hidden',
             'ALTER TABLE cragkit.profile_probe_hidden RENAME TO chunk_vectors_openai_te3small_1536'),
        )
        for name, mutation, restore in probes:
            await admin.execute(mutation)
            try:
                await refused(admin, profile_upgrade_script(apply=False))
                await runtime_admission(roles.reader, accepted=False)
                await runtime_admission(roles.reader, live=False, accepted=False)
            finally:
                await admin.execute(restore)
            await runtime_admission(roles.reader, accepted=True)
            checks.append(name + '_refused_by_operator_and_runtime')
        # A validated but weaker CHECK must fail just like an absent constraint.
        name = 'chunk_vectors_openai_te3small_1536_embedding_check'
        await admin.execute(sql.SQL('ALTER TABLE cragkit.chunk_vectors_openai_te3small_1536 DROP CONSTRAINT {}')
                            .format(sql.Identifier(name)))
        await admin.execute(sql.SQL('ALTER TABLE cragkit.chunk_vectors_openai_te3small_1536 ADD CONSTRAINT {} CHECK(true)')
                            .format(sql.Identifier(name)))
        try:
            await refused(admin, profile_upgrade_script(apply=False))
            await runtime_admission(roles.reader, accepted=False)
        finally:
            await admin.execute(sql.SQL('ALTER TABLE cragkit.chunk_vectors_openai_te3small_1536 DROP CONSTRAINT {}')
                                .format(sql.Identifier(name)))
            await admin.execute(sql.SQL('ALTER TABLE cragkit.chunk_vectors_openai_te3small_1536 ADD CONSTRAINT {} '
                'CHECK(abs(cragkit_vector.vector_norm(embedding)-1.0)<=0.001)').format(sql.Identifier(name)))
        checks.append('validated_weaker_norm_constraint_refused')
        # Explicit deployment policies are separate from schema installation.
        for config, writer in ((roles.reader, False), (roles.writer, True)):
            role = sql.Identifier(config['user'])
            predicate = sql.SQL("tenant_id=current_setting('cragkit.tenant_id',true) "
                                "AND tenant_id='profile-tenant' AND collection_id='profile-checks'")
            policy = sql.SQL('CREATE POLICY {} ON cragkit.chunk_vectors_openai_te3small_1536 FOR '
                             + ('ALL' if writer else 'SELECT') + ' TO {} USING ({})'
                             + (' WITH CHECK ({})' if writer else ''))
            args = (role, role, predicate, predicate) if writer else (role, role, predicate)
            await admin.execute(policy.format(*args))
        await admin.execute(profile_upgrade_script(apply=False))
        require(await snapshot(admin) == upgraded, 'catalog_probes_changed_data_or_history')
        require(await (await admin.execute('SELECT count(*) FROM cragkit.chunk_vectors_openai_te3small_1536')).fetchone() == (0,),
                'synthetic_live_vectors_persisted')
        checks.append('catalog_recovery_preserves_active_fake_data_and_empty_live_table')
    # Exercise the actual administrative subprocess transport with verified TLS.
    config = fixture.config
    environment = {key: value for key, value in os.environ.items() if not key.startswith('PG')}
    for key, source in (('PGHOST', 'host'), ('PGPORT', 'port'), ('PGUSER', 'user'), ('PGDATABASE', 'dbname'),
                        ('PGPASSFILE', 'passfile'), ('PGSSLROOTCERT', 'sslrootcert')):
        environment[key] = str(config[source])
    environment['PGSSLMODE'] = 'verify-full'
    environment = connection_environment(environment, confirmed=True)
    execute(profile_upgrade_script(apply=False), environment,
            executable=str(fixture._server.binary_dir / 'psql'), marker=MARKER)
    checks.append('native_psql_verified_tls_readonly_operator')
    return checks


async def read_bounded(stream, limit):
    chunks, size = [], 0
    while chunk := await stream.read(min(8192, limit + 1 - size)):
        size += len(chunk)
        if size > limit:
            raise RuntimeError('profile_child_output_limit')
        chunks.append(chunk)
    return b''.join(chunks)


async def child(runtime, storage, roles, output_path):
    command = [sys.executable, str(ROOT / 'tools/postgres_profile_cases.py')] if runtime == 'python' else [
        'node', str(ROOT / 'tools/check_typescript_postgres_profiles.mjs')]
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('PG', 'LANGCHAIN', 'LANGSMITH', 'OTEL_'))
                   and key not in ('NODE_OPTIONS', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NODE_USE_ENV_PROXY')}
    process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=environment)
    output = asyncio.create_task(read_bounded(process.stdout, 131072))
    errors = asyncio.create_task(read_bounded(process.stderr, 65536))
    try:
        process.stdin.write(json.dumps(dict(reader_config=roles.reader, writer_config=roles.writer, storage=storage)).encode())
        await process.stdin.drain()
        process.stdin.close()
        async with asyncio.timeout(120):
            stdout, stderr = await asyncio.gather(output, errors)
            await process.wait()
        if process.returncode or stderr:
            failure = dict(runtime=runtime, storage=storage, returncode=process.returncode,
                           stdout_bytes=len(stdout), stderr_bytes=len(stderr))
            try:
                diagnostic = json.loads(stdout)
            except (ValueError, UnicodeError):
                diagnostic = {}
            if type(diagnostic) is dict:
                for key in ('failed_check', 'failure_code', 'error_type'):
                    item = diagnostic.get(key)
                    if type(item) is str and re.fullmatch(r'[A-Za-z_]{1,100}', item):
                        failure[key] = item
                frames = diagnostic.get('frames')
                if type(frames) is list and len(frames) <= 4:
                    safe_frames = [item for item in frames if type(item) is dict
                        and set(item) == {'module', 'line', 'function'}
                        and type(item['module']) is str and re.fullmatch(r'[A-Za-z_]+\.py', item['module'])
                        and type(item['line']) is int and 0 < item['line'] < 10000
                        and type(item['function']) is str and re.fullmatch(r'[A-Za-z_]+', item['function'])]
                    failure['frames'] = safe_frames
            output_path.write_text(json.dumps(failure, indent=2) + '\n')
            raise RuntimeError('profile_child_failed')
        value = json.loads(stdout)
        require(type(value) is dict and set(value) == {'runtime', 'storage', 'checks', 'observations', 'cleanup_verified', 'live_inference'}
                and value['runtime'] == runtime and value['storage'] == storage
                and value['checks'] == CASE_NAMES and value['cleanup_verified'] is True
                and value['live_inference'] is False and type(value['observations']) is list
                and len(value['observations']) == 6, 'profile_child_protocol')
        return value
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                process.kill()
                await process.wait()
        for task in (output, errors):
            if not task.done():
                task.cancel()
        await asyncio.gather(output, errors, return_exceptions=True)


async def verify(prepared, output):
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    result = dict(state='running', cleanup_verified=False, live_inference=False, results=[])
    try:
        with V6PostgresFixture(prepared, output / 'database') as fixture:
            roles = await fixture.provision(tenants=('profile-tenant',), collections=('profile-checks',))
            async with await connect(fixture.config) as admin:
                await admin.execute("INSERT INTO cragkit.collections(tenant_id,collection_id) VALUES('profile-tenant','profile-checks')")
            host, port = fixture.config['host'], fixture.config['port']
            for storage in ('legacy', 'upgraded'):
                if storage == 'upgraded':
                    result['operator_checks'] = await operator_cases(fixture, roles)
                observations = []
                for runtime in ('python', 'typescript'):
                    result['stage'] = storage + '_' + runtime
                    value = await child(runtime, storage, roles, output / 'child-failure.json')
                    result['results'].append(value)
                    observations.append(value['observations'])
                require(observations[0] == observations[1], 'native_profile_runtime_parity')
            async with await connect(fixture.config) as admin:
                require(await (await admin.execute('SELECT count(*) FROM cragkit.chunk_vectors_openai_te3small_1536')).fetchone() == (0,),
                        'synthetic_live_vectors_persisted')
        try:
            listener = socket.create_connection((host, port), timeout=.2)
        except ConnectionRefusedError:
            pass
        else:
            listener.close()
            raise RuntimeError('profile_fixture_listener_remains')
        result.update(state='passed', stage='complete', cleanup_verified=True)
    except BaseException as error:
        result.update(state='failed', error_type=type(error).__name__)
        raise
    finally:
        (output / 'results.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared-postgres-bin', type=Path, required=True)
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    parser.add_argument('--allow-local-processes', action='store_true', required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(verify(args.prepared_postgres_bin, args.artifacts_dir))
    except Exception:
        print(json.dumps(dict(state='failed', code='native_profile_storage_failed')))
        return 1
    print(json.dumps(dict(state=result['state'], operator_checks=len(result['operator_checks']),
                         runtime_checks=sum(len(item['checks']) for item in result['results']), cleanup_verified=True)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
