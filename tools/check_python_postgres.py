"""Opt-in isolated runtime-LOGIN checks against an explicitly empty development target."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import stat
import sys
import tempfile

from runtime_diagnostics import CleanupFailure, describe_error
from runtime_recovery import Journal, RecoveryRefused, recover, target_fingerprint


CURRENT_STAGE = 'not_started'


def require_installed_origin(expected: str | None, module_file: str, interpreter_prefix: str) -> None:
    if expected is None:
        return
    target = Path(expected).resolve()
    if (Path(interpreter_prefix).resolve() != target
            or not Path(module_file).resolve().is_relative_to(target)):
        raise RuntimeCheckError('installed_product_origin_required')


def require_neon_host(host: str) -> None:
    if not re.fullmatch(r'ep-[a-z0-9]+(?:-[a-z0-9]+)*\.c-[0-9]+\.[a-z0-9-]+\.aws\.neon\.tech', host) or '-pooler.' in host:
        raise RuntimeCheckError('direct_neon_host_required')


def require_client_tls(connection) -> None:
    if getattr(getattr(connection, 'pgconn', None), 'ssl_in_use', None) is not True:
        raise RuntimeCheckError('client_tls_required')


def fixture_password(connection, password: str, role: str, *, neon: bool = False) -> str:
    if neon:
        require_client_tls(connection)
        return password
    return connection.pgconn.encrypt_password(password.encode(), role.encode(), b'scram-sha-256').decode()


async def await_fixture_completion(task, *, deadline: float, release_timeout: float):
    # Session rollback and pool return each have their declared release budget.
    # This bounds the observation; it does not extend the request's SQL deadline.
    remaining = max(0.0, deadline + 2 * release_timeout - asyncio.get_running_loop().time())
    return await asyncio.wait_for(task, remaining)


class RuntimeCheckError(RuntimeError):
    pass


def load_config(path: Path) -> dict:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeCheckError('private_config_permissions')
    value = json.loads(path.read_text(encoding='utf-8'))
    if type(value) is not dict:
        raise RuntimeCheckError('config_shape')
    for name in ('sslrootcert', 'passfile'):
        if type(value.get(name)) is not str:
            raise RuntimeCheckError('config_paths')
        value[name] = Path(value[name])
    value['max_size'] = 1
    return value


def pgpass_field(value: str) -> str:
    if any(char in value for char in '\r\n\0'):
        raise RuntimeCheckError('password_file_field')
    return value.replace('\\', '\\\\').replace(':', '\\:')


async def require_lexical_fixture_behavior(connection) -> None:
    # UTF8 encoding alone does not determine emoji-adjacent FTS tokenization.
    cursor = await connection.execute(
        "SELECT to_tsvector('pg_catalog.simple', %s) @@ websearch_to_tsquery('pg_catalog.simple', %s)",
        ('Café🙂', 'Café'))
    if await cursor.fetchall() != [(True,)]:
        raise RuntimeCheckError('lexical_fixture_locale_unsupported')


async def require_parent_admin_role_rejected(connection, role_sql: str) -> None:
    # Reuse the parent's administrator connection; never disclose it to a child.
    cursor = await connection.execute(role_sql)
    if await cursor.fetchall() != [(False,)]:
        raise RuntimeCheckError('unsafe_administrator_accepted')


def base_child_fixture(collection, tenants, principals, *, neon: bool) -> dict:
    return {
        'collection': collection,
        'scopes': [dict(tenant_id=tenant, principal_id=principal,
                       authorization_revision='scope-rev', grant_ids=[])
                   for tenant, principal in zip(tenants, principals)],
        'expected_documents': [[f'document-{index}', f'revision-{index}'] for index in range(2)],
        'neon': neon,
    }


def require_evaluation_profile(seconds, *, hybrid):
    if type(seconds) is not int or seconds not in (25, 60):
        raise RuntimeCheckError('invalid_evaluation_profile')
    if not hybrid and seconds != 25:
        raise RuntimeCheckError('evaluation_profile_requires_hybrid')


def fixture_role_lifetime_seconds(evaluation_deadline_seconds):
    require_evaluation_profile(evaluation_deadline_seconds, hybrid=True)
    return 1920 if evaluation_deadline_seconds == 60 else 600


async def check(config_path: Path, *, typescript: bool = False, ingestion: bool = False,
                lexical: bool = False, results: bool = False, lifecycle: bool = False, neon: bool = False, vectors: bool = False, vector_stage_only: bool = False, dense: bool = False, hybrid: bool = False, evidence: bool = False, corrective: bool = False, evaluation_deadline_seconds: int = 25, _test_hook=None) -> dict:
    global CURRENT_STAGE
    CURRENT_STAGE = 'configuration'
    require_evaluation_profile(evaluation_deadline_seconds, hybrid=hybrid)
    import cragkit
    require_installed_origin(os.environ.get('CRAGKIT_REQUIRE_INSTALLED_PREFIX'), cragkit.__file__, sys.prefix)
    # Optional dependencies are loaded only after explicit CLI authorization.
    import psycopg
    from psycopg import sql
    from cragkit._postgres_pool import PoolResource, parse_pool_config
    from cragkit._postgres_session import PostgresSession, _ROLE_SQL
    from cragkit.retrieval import PostgresRetriever
    from contextlib import asynccontextmanager
    from cragkit.contracts import parse_request, parse_scope
    from cragkit.errors import DeadlineExceeded, IndexNotReady, UnsupportedCapability

    if dense or hybrid:
        vectors = True
    if vectors:
        ingestion = True
    config = parse_pool_config(load_config(config_path))
    if neon:
        require_neon_host(config.host)
    resource_check = PoolResource(config)
    resource_check._check_owned_configuration()
    token = secrets.token_hex(8)
    role = 'cragkit_probe_' + token
    password = secrets.token_urlsafe(48)
    collection = 'probe_' + token
    tenants = ['probe_a_' + token, 'probe_b_' + token]
    principals = ['principal_a_' + token, 'principal_b_' + token]
    tables = ('collections', 'documents', 'document_revisions', 'index_generations',
              'chunks', 'chunk_lexical', 'document_grants', 'ingestion_jobs')
    if vectors:
        tables += ('chunk_vectors_fake_1536',)
    # Retrieval probes need read access to every joined table, even with no chunks.
    selected = tables + ('migration_history',) + (('embedding_profiles',) if vectors else ())
    policy = role + '_select'
    admin = runtime = node_process = None
    journal = None
    renamed = False
    completed = []
    temporary = tempfile.TemporaryDirectory(prefix='cragkit-runtime-')

    async def command(query, params=None):
        async with asyncio.timeout(10):
            return await admin.execute(query, params)

    async def rows(query, params=None):
        cursor = await command(query, params)
        return await cursor.fetchall()

    try:
        CURRENT_STAGE = 'admin_connect'
        admin = await psycopg.AsyncConnection.connect(
            host=config.host, port=config.port, dbname=config.dbname, user=config.user,
            sslmode='verify-full', sslrootcert=str(config.sslrootcert), passfile=str(config.passfile),
            connect_timeout=5, autocommit=True, application_name='cragkit-runtime-check-admin',
            options='-c statement_timeout=5000 -c lock_timeout=2000 -c idle_in_transaction_session_timeout=10000')
        if neon:
            require_client_tls(admin)
        if ingestion or lexical:
            CURRENT_STAGE = 'lexical_fixture_locale'
            await require_lexical_fixture_behavior(admin)
        if await rows('SELECT pg_try_advisory_lock(1129464148,1)') != [(True,)]:
            raise RuntimeCheckError('migration_lock_busy')
        if await rows("SELECT count(*) FROM pg_policies WHERE schemaname IN ('cragkit','cragkit_vector')") != [(0,)]:
            raise RuntimeCheckError('existing_policies')
        if await rows('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)):
            raise RuntimeCheckError('existing_probe_role')
        for table in tables:
            if await rows(sql.SQL('SELECT count(*) FROM cragkit.{}').format(sql.Identifier(table))) != [(0,)]:
                raise RuntimeCheckError('nonempty_target')

        from runtime_recovery_postgres import snapshot_histories
        migration_sha256, vector_sha256 = await snapshot_histories(admin, vectors=vectors)
        journal = Journal.create(
            run_id=token, target_sha256=target_fingerprint(config.host, config.port, config.dbname, config.user),
            ingestion=ingestion, vectors=vectors, lifecycle=lifecycle, allow_schema_restore=not ingestion,
            migration_sha256=migration_sha256, vector_sha256=vector_sha256)
        CURRENT_STAGE = 'fixture_setup'
        encrypted = fixture_password(admin, password, role, neon=neon)
        expires = (datetime.now(timezone.utc) + timedelta(seconds=fixture_role_lifetime_seconds(evaluation_deadline_seconds))).isoformat()
        async with admin.transaction():
            await command(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS CONNECTION LIMIT 1 PASSWORD {} VALID UNTIL {}').format(sql.Identifier(role), sql.Literal(encrypted), sql.Literal(expires)))
            await command(sql.SQL('COMMENT ON ROLE {} IS {}').format(
                sql.Identifier(role), sql.Literal(journal.manifest.owner_marker)))
            await command(sql.SQL('GRANT USAGE ON SCHEMA cragkit TO {}').format(sql.Identifier(role)))
            await command(sql.SQL('GRANT USAGE ON DOMAIN cragkit.identity_text,cragkit.collection_text,cragkit.sha256_hex,cragkit.safe_count TO {}').format(sql.Identifier(role)))
            for table in selected:
                permissions = 'SELECT,INSERT,UPDATE' if ingestion and table not in ('migration_history','embedding_profiles') else 'SELECT'
                await command(sql.SQL('GRANT ' + permissions + ' ON cragkit.{} TO {}').format(sql.Identifier(table), sql.Identifier(role)))
                if table in ('migration_history','embedding_profiles'):
                    predicate = sql.SQL('true')
                else:
                    predicate = sql.SQL("tenant_id=current_setting('cragkit.tenant_id',true) AND tenant_id IN ({},{}) AND collection_id={}").format(sql.Literal(tenants[0]), sql.Literal(tenants[1]), sql.Literal(collection))
                if ingestion and table not in ('migration_history','embedding_profiles'):
                    await command(sql.SQL('CREATE POLICY {} ON cragkit.{} FOR ALL TO {} USING ({}) WITH CHECK ({})').format(sql.Identifier(policy), sql.Identifier(table), sql.Identifier(role), predicate, predicate))
                else:
                    await command(sql.SQL('CREATE POLICY {} ON cragkit.{} FOR SELECT TO {} USING ({})').format(sql.Identifier(policy), sql.Identifier(table), sql.Identifier(role), predicate))
            if vectors:
                # Explicit accepted managed-primitive exposure; no permanent grants.
                await command(sql.SQL('GRANT USAGE ON SCHEMA cragkit_vector TO {}').format(sql.Identifier(role)))
                await command(sql.SQL('GRANT SELECT ON cragkit_vector.setup_history TO {}').format(sql.Identifier(role)))
                await command(sql.SQL('CREATE POLICY {} ON cragkit_vector.setup_history FOR SELECT TO {} USING(true)').format(sql.Identifier(policy),sql.Identifier(role)))
            digest = hashlib.sha256(b'synthetic runtime fixture').hexdigest()
            for index, (tenant, principal) in enumerate([] if ingestion else zip(tenants, principals)):
                document, revision = f'document-{index}', f'revision-{index}'
                await command('INSERT INTO cragkit.collections(tenant_id,collection_id) VALUES (%s,%s)', (tenant, collection))
                await command('INSERT INTO cragkit.documents(tenant_id,collection_id,document_id,authorization_revision) VALUES (%s,%s,%s,%s)', (tenant, collection, document, 'scope-rev'))
                await command('INSERT INTO cragkit.document_revisions(tenant_id,collection_id,document_id,revision_id,source_sha256,source_locator,canonical_text,canonical_sha256,parser_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)', (tenant, collection, document, revision, digest, 'synthetic:runtime', 'synthetic runtime fixture', digest, 'probe.v1'))
                await command("INSERT INTO cragkit.index_generations(tenant_id,collection_id,document_id,revision_id,generation_id,chunker_profile,lexical_profile,expected_chunk_count,status) VALUES (%s,%s,%s,%s,%s,%s,%s,1,'ready')", (tenant, collection, document, revision, 'generation', 'probe.v1', 'native_fts.v1'))
                await command('UPDATE cragkit.documents SET active_generation_id=%s WHERE tenant_id=%s AND collection_id=%s', ('generation', tenant, collection))
                await command('INSERT INTO cragkit.document_grants(tenant_id,collection_id,document_id,grant_id,principal_id,authorization_revision) VALUES (%s,%s,%s,%s,%s,%s)', (tenant, collection, document, 'read', principal, 'scope-rev'))
                await command('INSERT INTO cragkit.document_grants(tenant_id,collection_id,document_id,grant_id,principal_id,authorization_revision) VALUES (%s,%s,%s,%s,NULL,%s)', (tenant, collection, document, 'trusted-grant', 'scope-rev'))
        completed.append('isolated_fixture')
        if _test_hook is not None:
            await _test_hook(journal, admin)
        passfile = Path(temporary.name) / 'runtime.pgpass'
        descriptor = os.open(passfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as destination:
            destination.write(':'.join(pgpass_field(value) for value in (config.host, str(config.port), config.dbname, role, password)) + '\n')
        runtime_config = config.model_copy(update={'user': role, 'passfile': passfile})
        if vectors:
            if hybrid:
                from check_hybrid import run as run_vectors
            elif dense:
                from check_dense import run as run_vectors
            else:
                from check_vectors import run as run_vectors
            CURRENT_STAGE = 'hybrid_evaluation' if hybrid else 'dense_retrieval' if dense else 'vector_generations'
            try:
                return await run_vectors(runtime_config, {
                'collection': collection,
                'scopes': [dict(tenant_id=tenant, principal_id=principal,
                    authorization_revision='scope-rev', grant_ids=[])
                    for tenant,principal in zip(tenants,principals)],
                }, admin, typescript=typescript, neon=neon, **({'evidence': evidence, 'corrective': corrective, 'evaluation_deadline_seconds': evaluation_deadline_seconds} if hybrid else {} if dense else {'stage_only': vector_stage_only}))
            except Exception as error:
                from check_vectors import VectorCheckError
                from check_dense import DenseCheckError
                from check_hybrid import HybridCheckError
                if isinstance(error,(VectorCheckError,DenseCheckError,HybridCheckError)) and re.fullmatch(r'[a-z_]+',str(error)):
                    raise RuntimeCheckError(('hybrid_' if hybrid else 'dense_' if dense else 'vector_')+str(error)) from None
                raise
        if ingestion:
            from check_ingestion import IngestionCheckError, run
            CURRENT_STAGE = 'python_ingestion'
            try:
                result = await run(runtime_config, {
                    'collection': collection,
                    'scopes': [dict(tenant_id=tenant, principal_id=principal,
                                   authorization_revision='scope-rev', grant_ids=[])
                               for tenant, principal in zip(tenants, principals)],
                    'document_ids': ['document-0', 'document-1'],
                }, admin, typescript=typescript, lexical=lexical, results=results, lifecycle=lifecycle, neon=neon)
            except IngestionCheckError as error:
                code = str(error) if re.fullmatch(r'[a-z_]{1,80}', str(error)) else 'check_failed'
                raise RuntimeCheckError('ingestion_' + code) from None
            return {**result, 'runtime': 'python_and_node' if typescript else 'python', 'cleanup_verified': True, 'maximum_connections': 2}
        await require_parent_admin_role_rejected(admin, _ROLE_SQL)
        completed.append('parent_unsafe_administrator_role_rejected')
        if typescript:
            CURRENT_STAGE = 'typescript_runtime'
            fixture_path = Path(temporary.name) / 'fixture.json'
            runtime_path = Path(temporary.name) / 'runtime.json'
            fixture = base_child_fixture(collection, tenants, principals, neon=neon)
            for path, value in ((fixture_path, fixture),
                                (runtime_path, runtime_config.model_dump(mode='json'))):
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'w', encoding='utf-8') as destination:
                    json.dump(value, destination)
            node_process = await asyncio.create_subprocess_exec(
                'node', str(Path(__file__).resolve().with_name('check_typescript_postgres.mjs')),
                '--config', str(runtime_path), '--fixture', str(fixture_path), '--allow-runtime-checks',
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=8192)
            assert node_process.stdout is not None and node_process.stdin is not None
            result = None
            lock_transaction = None
            lock_mode = None
            while line := await node_process.stdout.readline():
                message = json.loads(line)
                kind = message.get('type')
                response = None
                if (kind == 'lock_request' and lock_transaction is None
                        and message.get('mode') in ('deadline', 'abort')):
                    lock_mode = message['mode']
                    lock_transaction = admin.transaction()
                    await lock_transaction.__aenter__()
                    await command('LOCK TABLE cragkit.documents IN ACCESS EXCLUSIVE MODE')
                    response = {'type': 'locked'}
                elif kind == 'query_started' and lock_transaction is not None:
                    until = asyncio.get_running_loop().time() + 3
                    while True:
                        if await rows("SELECT count(*) FROM pg_stat_activity WHERE usename=%s AND wait_event_type='Lock'", (role,)) == [(1,)]:
                            break
                        if asyncio.get_running_loop().time() >= until:
                            raise RuntimeCheckError('typescript_lock_not_observed')
                        await asyncio.sleep(0.02)
                    response = {'type': 'abort' if lock_mode == 'abort' else 'observed'}
                elif kind == 'lock_done' and lock_transaction is not None:
                    await lock_transaction.__aexit__(None, None, None)
                    lock_transaction = None
                    response = {'type': 'unlocked'}
                elif kind == 'schema_hide' and not renamed:
                    await command('ALTER TABLE cragkit.documents RENAME COLUMN authorization_revision TO probe_hidden_authorization_revision')
                    renamed = True
                    response = {'type': 'schema_hidden'}
                elif kind == 'schema_restore' and renamed:
                    await command('ALTER TABLE cragkit.documents RENAME COLUMN probe_hidden_authorization_revision TO authorization_revision')
                    renamed = False
                    response = {'type': 'schema_restored'}
                elif kind == 'result' and message.get('state') == 'passed':
                    checks = message.get('checks')
                    if (not isinstance(checks, list) or len(checks) > 32
                            or any(not isinstance(item, str) or not re.fullmatch(r'[a-z_]+', item)
                                   for item in checks)):
                        raise RuntimeCheckError('typescript_result_shape')
                    result = message
                elif ((kind == 'error' or (kind == 'result' and message.get('state') == 'failed'))
                      and isinstance(message.get('code'), str)
                      and re.fullmatch(r'[a-z_]+', message['code'])):
                    raise RuntimeCheckError('typescript_' + message['code'])
                else:
                    raise RuntimeCheckError('typescript_protocol_failed')
                if response is not None:
                    node_process.stdin.write((json.dumps(response) + '\n').encode())
                    await node_process.stdin.drain()
            if await node_process.wait() != 0 or result is None:
                raise RuntimeCheckError('typescript_runtime_failed')
            return {'state': 'passed', 'runtime': 'typescript', 'cleanup_verified': True,
                    'maximum_connections': 2, 'checks': completed + result.get('checks', [])}
        CURRENT_STAGE = 'runtime_login'
        runtime = PoolResource(runtime_config)
        await runtime.open()
        session = PostgresSession(runtime)
        loop = asyncio.get_running_loop()
        if not neon:
            await session.validate(deadline=loop.time() + 5)
        async with runtime.lease(deadline=loop.time() + 5) as connection:
            if neon:
                require_client_tls(connection)
            async with connection.transaction(force_rollback=True):
                identity_sql = ('SELECT current_user=session_user,current_user=%s,true,pg_backend_pid()' if neon else
                                'SELECT current_user=session_user,current_user=%s,ssl,pg_backend_pid() FROM pg_stat_ssl WHERE pid=pg_backend_pid()')
                cursor = await connection.execute(identity_sql, (role,))
                identity = await cursor.fetchall()
                if len(identity) != 1 or identity[0][:3] != (True, True, True):
                    raise RuntimeCheckError('runtime_login_identity_or_tls')
                physical_pid = identity[0][3]
                cursor = await connection.execute('SELECT count(*) FROM cragkit.documents')
                if await cursor.fetchall() != [(0,)]:
                    raise RuntimeCheckError('unscoped_rls_read')
        if neon:
            await session.validate(deadline=loop.time() + 5)
        completed.append('authenticated_runtime_login')
        CURRENT_STAGE = 'scope_filters'
        request = parse_request({'query': 'synthetic', 'collection': collection})
        scopes = [parse_scope({'tenant_id': tenant, 'principal_id': principal, 'authorization_revision': 'scope-rev', 'grant_ids': []}) for tenant, principal in zip(tenants, principals)]
        for index in (0, 1, 0):
            async with session.transaction(request, scope=scopes[index], deadline=loop.time() + 5) as handle:
                if await handle.visible_documents() != ((f'document-{index}', f'revision-{index}'),):
                    raise RuntimeCheckError('scope_visibility')
        denied = parse_scope({'tenant_id': tenants[0], 'principal_id': 'not-granted', 'authorization_revision': 'scope-rev', 'grant_ids': []})
        async with session.transaction(request, scope=denied, deadline=loop.time() + 5) as handle:
            if await handle.visible_documents():
                raise RuntimeCheckError('principal_filter')
        granted = parse_scope({'tenant_id': tenants[0], 'principal_id': 'not-granted', 'authorization_revision': 'scope-rev', 'grant_ids': ['trusted-grant']})
        async with session.transaction(request, scope=granted, deadline=loop.time() + 5) as handle:
            if await handle.visible_documents() != (('document-0', 'revision-0'),):
                raise RuntimeCheckError('trusted_grant_branch')
        stale = parse_scope({'tenant_id': tenants[0], 'principal_id': principals[0], 'authorization_revision': 'stale', 'grant_ids': ['trusted-grant']})
        async with session.transaction(request, scope=stale, deadline=loop.time() + 5) as handle:
            if await handle.visible_documents():
                raise RuntimeCheckError('stale_authorization_revision')
        filtered = parse_request({'query': 'synthetic', 'collection': collection, 'required_filters': [{'op': 'eq', 'field': 'document_id', 'value': "literal' OR TRUE --"}]})
        async with session.transaction(filtered, scope=scopes[0], deadline=loop.time() + 5) as handle:
            if await handle.visible_documents():
                raise RuntimeCheckError('identifier_filter')
        completed.append('scope_reuse_and_filters')

        class Sentinel(Exception): pass
        try:
            async with session.transaction(request, scope=scopes[0], deadline=loop.time() + 5):
                raise Sentinel()
        except Sentinel:
            pass
        # A raw checkout checks transaction-local state after normal and exceptional reuse.
        async def assert_reset(*, require_same_pid: bool = True):
            nonlocal physical_pid
            async with runtime.lease(deadline=loop.time() + 5) as connection:
                async with connection.transaction(force_rollback=True):
                    cursor = await connection.execute("SELECT current_setting('cragkit.tenant_id',true),current_setting('cragkit.principal_id',true),current_setting('cragkit.authorization_revision',true),current_setting('cragkit.grant_ids',true)")
                    values = await cursor.fetchall()
                    pid_cursor = await connection.execute('SELECT pg_backend_pid()')
                    pids = await pid_cursor.fetchall()
                    if len(pids) != 1 or len(pids[0]) != 1:
                        raise RuntimeCheckError('physical_connection_identity_missing')
                    if require_same_pid and pids != [(physical_pid,)]:
                        raise RuntimeCheckError('physical_connection_not_reused')
                    physical_pid = pids[0][0]
                    if len(values) != 1 or any(value not in (None, '') for value in values[0]):
                        raise RuntimeCheckError('scope_not_reset')
        await assert_reset()
        completed.append('body_rollback_and_reset')

        CURRENT_STAGE = 'deadline_cancellation'
        retriever = PostgresRetriever(runtime)
        async def reuse_retriever(*, require_same_pid: bool = True):
            for scope in (scopes[1], scopes[0]):
                result = await retriever.retrieve(request, scope=scope, deadline=loop.time() + 8)
                if result.evidence or result.status != 'insufficient':
                    raise RuntimeCheckError('retriever_fresh_scope_reuse')
            await assert_reset(require_same_pid=require_same_pid)

        # Occupy the sole lease so cancellation must remove an admitted waiter.
        async with runtime.lease(deadline=loop.time() + 8):
            waiting = asyncio.create_task(retriever.retrieve(
                request, scope=scopes[0], deadline=loop.time() + 5))
            await asyncio.sleep(0.05)
            if waiting.done():
                raise RuntimeCheckError('retriever_wait_not_observed')
            waiting.cancel()
            try:
                await waiting
            except asyncio.CancelledError:
                pass
            else:
                raise RuntimeCheckError('retriever_wait_cancel_accepted')
        await reuse_retriever()
        completed.append('retriever_wait_cancel_and_fresh_scope_reuse')
        for cancel in (False, True):
            phase = 'cancel' if cancel else 'deadline'
            CURRENT_STAGE = phase + '_query_starting'
            started, query_gate = asyncio.Event(), asyncio.Event()
            class GatedSession:
                @asynccontextmanager
                async def transaction(self, *args, **kwargs):
                    async with session.transaction(*args, **kwargs) as handle:
                        started.set()
                        await query_gate.wait()
                        yield handle
            retriever._session = GatedSession()
            query_deadline = loop.time() + 5
            task = asyncio.create_task(retriever.retrieve(
                request, scope=scopes[0], deadline=query_deadline))
            try:
                await asyncio.wait_for(started.wait(), max(0.0, query_deadline - loop.time()))
                async with admin.transaction():
                    await command('LOCK TABLE cragkit.documents IN ACCESS EXCLUSIVE MODE')
                    CURRENT_STAGE = phase + '_query_observation'
                    query_gate.set()
                    observed = False
                    until = min(loop.time() + 2, query_deadline)
                    while loop.time() < until:
                        waits = await rows("SELECT count(*) FROM pg_stat_activity WHERE usename=%s AND wait_event_type='Lock'", (role,))
                        if waits == [(1,)]:
                            observed = True
                            break
                        await asyncio.sleep(0.02)
                    if not observed:
                        raise RuntimeCheckError('runtime_query_lock_not_observed')
                    if cancel:
                        task.cancel()
                    CURRENT_STAGE = phase + '_query_completion'
                    try:
                        await await_fixture_completion(task, deadline=query_deadline,
                                                       release_timeout=config.release_timeout)
                    except asyncio.CancelledError:
                        if not cancel: raise
                    except DeadlineExceeded:
                        if cancel: raise
                    else:
                        raise RuntimeCheckError('blocked_query_did_not_stop')
            finally:
                query_gate.set()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            retriever._session = session
            CURRENT_STAGE = phase + '_query_fresh_scope_reuse'
            await reuse_retriever(require_same_pid=False)
        completed.append('retriever_query_deadline_cancel_and_fresh_scope_reuse')
        CURRENT_STAGE = 'schema_rejection'
        await command('ALTER TABLE cragkit.documents RENAME COLUMN authorization_revision TO probe_hidden_authorization_revision')
        renamed = True
        try:
            await session.validate(deadline=loop.time() + 5)
        except (UnsupportedCapability, IndexNotReady):
            pass
        else:
            raise RuntimeCheckError('invalid_schema_accepted')
        await command('ALTER TABLE cragkit.documents RENAME COLUMN probe_hidden_authorization_revision TO authorization_revision')
        renamed = False
        if await rows("SELECT count(*) FROM information_schema.columns WHERE table_schema='cragkit' AND table_name='documents' AND column_name='authorization_revision'") != [(1,)]:
            raise RuntimeCheckError('schema_restore_failed')
        completed.append('schema_rejection_and_restore')
        return {'state': 'passed', 'checks': completed, 'runtime_login': True, 'maximum_connections': 2, 'cleanup_verified': True}
    finally:
        primary_failure = sys.exception()
        cleanup_stage = CURRENT_STAGE
        deadline = asyncio.get_running_loop().time() + 25
        try:
            # Quiesce existing clients before recovery opens a fresh connection.
            # Closing the administrator also releases its session advisory lock.
            await quiesce_clients(admin=admin, runtime=runtime, child=node_process,
                                  deadline=deadline, primary=primary_failure, stage=cleanup_stage)
            if journal is not None:
                from runtime_recovery_postgres import connect_transport
                await recover(journal, connect=lambda end: connect_transport(config, end),
                              deadline=deadline, primary=primary_failure, stage=cleanup_stage)
        except CleanupFailure as error:
            if journal is not None:
                error.recovery_id = journal.manifest.run_id
                error.recovery_required = True
            raise
        finally:
            temporary.cleanup()


async def quiesce_clients(*, admin, runtime, child, deadline, primary=None, stage='recovery'):
    """Never open another client while an old client has unsettled closure."""
    async def stop_child():
        if child.returncode is None:
            child.kill()
        await child.wait()

    errors = []
    for operation, close in (
        ('child_stop', stop_child if child is not None else None),
        ('admin_close', admin.close if admin is not None else None),
        ('runtime_close', runtime.close if runtime is not None else None),
    ):
        if close is None:
            continue
        task = asyncio.create_task(close())
        try:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0 or not (await asyncio.wait({task}, timeout=remaining))[0]:
                raise TimeoutError()
            task.result()
        except BaseException as error:
            task.cancel()
            def observe(done):
                try:
                    done.result()
                except BaseException:
                    pass
            task.add_done_callback(observe)
            errors.append((operation, error))
    if errors:
        raise CleanupFailure(errors, primary=primary, stage=stage) from None


async def recover_run(config_path, run_id, *, neon=False):
    from cragkit._postgres_pool import PoolResource, parse_pool_config
    from runtime_recovery_postgres import connect_transport
    config = parse_pool_config(load_config(config_path))
    if neon:
        require_neon_host(config.host)
    PoolResource(config)._check_owned_configuration()
    journal = Journal.load(run_id, target_sha256=target_fingerprint(
        config.host, config.port, config.dbname, config.user))
    try:
        return await recover(journal, connect=lambda end: connect_transport(config, end),
                             deadline=asyncio.get_running_loop().time() + 25)
    except CleanupFailure as error:
        error.recovery_id = journal.manifest.run_id
        error.recovery_required = True
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--allow-test-writes', action='store_true')
    parser.add_argument('--recover', metavar='RUN_ID', help='Recover one validated private fixture journal')
    parser.add_argument('--typescript', action='store_true')
    parser.add_argument('--ingestion', action='store_true')
    parser.add_argument('--lexical', action='store_true')
    parser.add_argument('--results', action='store_true')
    parser.add_argument('--lifecycle', action='store_true')
    parser.add_argument('--vectors', action='store_true')
    parser.add_argument('--dense', action='store_true')
    parser.add_argument('--hybrid', action='store_true')
    parser.add_argument('--evaluation-deadline-seconds', type=int, choices=(25, 60),
                        help='Explicit hybrid evaluation profile; default 25 seconds')
    parser.add_argument('--corrective', action='store_true', help='Explicit V4 corrective checks within --hybrid')
    parser.add_argument('--evidence', action='store_true', help='Explicit V3 packed-assessment checks within --hybrid')
    parser.add_argument('--vector-stage-only', action='store_true')
    parser.add_argument('--neon', action='store_true', help='Explicit direct Neon fixture mode with client TLS proof')
    args = parser.parse_args()
    if args.evaluation_deadline_seconds is not None and not args.hybrid:
        print('The evaluation profile requires --hybrid.')
        return 2
    evaluation_deadline = args.evaluation_deadline_seconds or 25
    if args.recover and any((args.typescript, args.ingestion, args.lexical, args.results,
                             args.lifecycle, args.vectors, args.dense, args.hybrid,
                             args.corrective, args.evidence, args.vector_stage_only)):
        print('Recovery cannot be combined with fixture modes.')
        return 2
    if args.corrective and not args.hybrid:
        print('Corrective checks require --hybrid.')
        return 2
    if args.evidence and not args.hybrid:
        print('Evidence checks require --hybrid.')
        return 2
    if args.hybrid and (args.dense or args.vector_stage_only):
        print("Hybrid mode cannot select dense-only or staging-only checks.")
        return 2
    if args.dense and args.vector_stage_only:
        print('Dense mode cannot select vector staging-only checks.')
        return 2
    if args.vector_stage_only and not (args.vectors and args.typescript):
        print('Vector stage-only mode requires --vectors and --typescript.')
        return 2
    if not args.allow_test_writes:
        print('Runtime checks require explicit test-write authorization.')
        return 2
    try:
        async def bounded():
            if args.recover:
                return await recover_run(args.config, args.recover, neon=args.neon)
            timeout = (600 if args.vectors or args.dense or args.hybrid else 600 if args.lifecycle else 420 if args.results else 300 if args.lexical
                       else 180 if args.ingestion and args.typescript else 90)
            if evaluation_deadline == 60:
                timeout = 1800
            async with asyncio.timeout(timeout):
                return await check(
                    args.config,
                    typescript=args.typescript or args.lexical or args.results or args.lifecycle,
                    ingestion=args.ingestion or args.lexical or args.results or args.lifecycle,
                    lexical=args.lexical or args.results or args.lifecycle,
                    results=args.results or args.lifecycle, lifecycle=args.lifecycle, neon=args.neon, vectors=args.vectors, vector_stage_only=args.vector_stage_only, dense=args.dense, hybrid=args.hybrid, evidence=args.evidence, corrective=args.corrective,
                    evaluation_deadline_seconds=evaluation_deadline,
                )
        result = asyncio.run(bounded())
    except CleanupFailure as error:
        detail = {'state': 'failed', **error.to_dict()}
        recovery_id = getattr(error, 'recovery_id', None)
        if type(recovery_id) is str and re.fullmatch('[0-9a-f]{16}', recovery_id):
            detail.update(recovery_id=recovery_id, recovery_required=True)
        reason = getattr(error, 'refusal_reason', None)
        if reason in ('invalid_manifest', 'unsafe_path', 'target_mismatch', 'ownership_mismatch',
                      'unsafe_role', 'unexpected_policy', 'history_mismatch', 'schema_mismatch',
                      'lock_busy', 'fixture_remaining'):
            detail['refusal_reason'] = reason
        print(json.dumps(detail, sort_keys=True))
        return 1
    except RecoveryRefused as error:
        print(json.dumps({'state': 'failed', 'code': 'recovery_refused', 'reason': error.reason}, sort_keys=True))
        return 1
    except RuntimeCheckError as error:
        code = str(error) if re.fullmatch(r'[a-z_]+', str(error)) else 'runtime_check_failed'
        print(f'Runtime PostgreSQL checks failed: {code}; stage={CURRENT_STAGE}.')
        return 1
    except (Exception, asyncio.CancelledError, KeyboardInterrupt) as error:
        cancelled = issubclass(type(error), (asyncio.CancelledError, KeyboardInterrupt))
        record = describe_error(asyncio.CancelledError() if cancelled else error,
                                operation='primary', stage=CURRENT_STAGE)
        print(json.dumps({'state': 'failed', 'code': 'runtime_check_failed', 'error': record}, sort_keys=True))
        return 130 if cancelled else 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
