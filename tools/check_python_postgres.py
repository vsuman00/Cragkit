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
import tempfile


CURRENT_STAGE = 'not_started'


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


async def check(config_path: Path, *, typescript: bool = False, ingestion: bool = False,
                lexical: bool = False, results: bool = False, lifecycle: bool = False) -> dict:
    global CURRENT_STAGE
    CURRENT_STAGE = 'configuration'
    # Optional dependencies are loaded only after explicit CLI authorization.
    import psycopg
    from psycopg import sql
    from cragkit._postgres_pool import PoolResource, parse_pool_config
    from cragkit._postgres_session import PostgresSession
    from cragkit.retrieval import PostgresRetriever
    from contextlib import asynccontextmanager
    from cragkit.contracts import parse_request, parse_scope
    from cragkit.errors import DeadlineExceeded, IndexNotReady, UnauthorizedScope, UnsupportedCapability

    config = parse_pool_config(load_config(config_path))
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
    # Retrieval probes need read access to every joined table, even with no chunks.
    selected = tables + ('migration_history',)
    policy = role + '_select'
    admin = runtime = node_process = None
    locked = created_role = renamed = False
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
        if await rows('SELECT pg_try_advisory_lock(1129464148,1)') != [(True,)]:
            raise RuntimeCheckError('migration_lock_busy')
        locked = True
        if await rows("SELECT count(*) FROM pg_policies WHERE schemaname='cragkit'") != [(0,)]:
            raise RuntimeCheckError('existing_policies')
        if await rows('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)):
            raise RuntimeCheckError('existing_probe_role')
        for table in tables:
            if await rows(sql.SQL('SELECT count(*) FROM cragkit.{}').format(sql.Identifier(table))) != [(0,)]:
                raise RuntimeCheckError('nonempty_target')

        CURRENT_STAGE = 'fixture_setup'
        encrypted = admin.pgconn.encrypt_password(password.encode(), role.encode(), b'scram-sha-256').decode()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        async with admin.transaction():
            await command(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS CONNECTION LIMIT 1 PASSWORD {} VALID UNTIL {}').format(sql.Identifier(role), sql.Literal(encrypted), sql.Literal(expires)))
            await command(sql.SQL('GRANT USAGE ON SCHEMA cragkit TO {}').format(sql.Identifier(role)))
            await command(sql.SQL('GRANT USAGE ON DOMAIN cragkit.identity_text,cragkit.collection_text,cragkit.sha256_hex,cragkit.safe_count TO {}').format(sql.Identifier(role)))
            for table in selected:
                permissions = 'SELECT,INSERT,UPDATE' if ingestion and table != 'migration_history' else 'SELECT'
                await command(sql.SQL('GRANT ' + permissions + ' ON cragkit.{} TO {}').format(sql.Identifier(table), sql.Identifier(role)))
                if table == 'migration_history':
                    predicate = sql.SQL('true')
                else:
                    predicate = sql.SQL("tenant_id=current_setting('cragkit.tenant_id',true) AND tenant_id IN ({},{}) AND collection_id={}").format(sql.Literal(tenants[0]), sql.Literal(tenants[1]), sql.Literal(collection))
                if ingestion and table != 'migration_history':
                    await command(sql.SQL('CREATE POLICY {} ON cragkit.{} FOR ALL TO {} USING ({}) WITH CHECK ({})').format(sql.Identifier(policy), sql.Identifier(table), sql.Identifier(role), predicate, predicate))
                else:
                    await command(sql.SQL('CREATE POLICY {} ON cragkit.{} FOR SELECT TO {} USING ({})').format(sql.Identifier(policy), sql.Identifier(table), sql.Identifier(role), predicate))
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
        created_role = True
        completed.append('isolated_fixture')
        passfile = Path(temporary.name) / 'runtime.pgpass'
        descriptor = os.open(passfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as destination:
            destination.write(':'.join(pgpass_field(value) for value in (config.host, str(config.port), config.dbname, role, password)) + '\n')
        runtime_config = config.model_copy(update={'user': role, 'passfile': passfile})
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
                }, admin, typescript=typescript, lexical=lexical, results=results, lifecycle=lifecycle)
            except IngestionCheckError as error:
                code = str(error) if re.fullmatch(r'[a-z_]{1,80}', str(error)) else 'check_failed'
                raise RuntimeCheckError('ingestion_' + code) from None
            return {**result, 'runtime': 'python_and_node' if typescript else 'python', 'cleanup_verified': True, 'maximum_connections': 2}
        if typescript:
            CURRENT_STAGE = 'typescript_runtime'
            fixture_path = Path(temporary.name) / 'fixture.json'
            runtime_path = Path(temporary.name) / 'runtime.json'
            fixture = {
                'collection': collection,
                'scopes': [dict(tenant_id=tenant, principal_id=principal,
                               authorization_revision='scope-rev', grant_ids=[])
                           for tenant, principal in zip(tenants, principals)],
                'expected_documents': [[f'document-{index}', f'revision-{index}'] for index in range(2)],
                'admin_config': str(config_path.resolve()),
            }
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
            try:
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
                        'maximum_connections': 2, 'checks': result.get('checks', [])}
            finally:
                if node_process.returncode is None:
                    node_process.kill()
                    await node_process.wait()
                if lock_transaction is not None:
                    await lock_transaction.__aexit__(None, None, None)
        CURRENT_STAGE = 'runtime_login'
        runtime = PoolResource(runtime_config)
        await runtime.open()
        session = PostgresSession(runtime)
        loop = asyncio.get_running_loop()
        await session.validate(deadline=loop.time() + 5)
        async with runtime.lease(deadline=loop.time() + 5) as connection:
            async with connection.transaction(force_rollback=True):
                cursor = await connection.execute('SELECT current_user=session_user,current_user=%s,ssl,pg_backend_pid() FROM pg_stat_ssl WHERE pid=pg_backend_pid()', (role,))
                identity = await cursor.fetchall()
                if len(identity) != 1 or identity[0][:3] != (True, True, True):
                    raise RuntimeCheckError('runtime_login_identity_or_tls')
                physical_pid = identity[0][3]
                cursor = await connection.execute('SELECT count(*) FROM cragkit.documents')
                if await cursor.fetchall() != [(0,)]:
                    raise RuntimeCheckError('unscoped_rls_read')
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
        async def assert_reset():
            async with runtime.lease(deadline=loop.time() + 5) as connection:
                async with connection.transaction(force_rollback=True):
                    cursor = await connection.execute("SELECT current_setting('cragkit.tenant_id',true),current_setting('cragkit.principal_id',true),current_setting('cragkit.authorization_revision',true),current_setting('cragkit.grant_ids',true)")
                    values = await cursor.fetchall()
                    pid_cursor = await connection.execute('SELECT pg_backend_pid()')
                    if await pid_cursor.fetchall() != [(physical_pid,)]:
                        raise RuntimeCheckError('physical_connection_not_reused')
                    if len(values) != 1 or any(value not in (None, '') for value in values[0]):
                        raise RuntimeCheckError('scope_not_reset')
        await assert_reset()
        completed.append('body_rollback_and_reset')
        class BorrowedAdmin:
            async def getconn(self, timeout=None): return admin
            async def putconn(self, connection): return None
        unsafe = PoolResource(config, pool=BorrowedAdmin())
        try:
            await PostgresSession(unsafe).validate(deadline=loop.time() + 5)
        except UnauthorizedScope:
            pass
        else:
            raise RuntimeCheckError('unsafe_administrator_accepted')
        await unsafe.close()
        completed.append('unsafe_administrator_rejected')

        CURRENT_STAGE = 'deadline_cancellation'
        retriever = PostgresRetriever(runtime)
        async def reuse_retriever():
            for scope in (scopes[1], scopes[0]):
                result = await retriever.retrieve(request, scope=scope, deadline=loop.time() + 8)
                if result.evidence or result.status != 'insufficient':
                    raise RuntimeCheckError('retriever_fresh_scope_reuse')
            await assert_reset()

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
            started, query_gate = asyncio.Event(), asyncio.Event()
            class GatedSession:
                @asynccontextmanager
                async def transaction(self, *args, **kwargs):
                    async with session.transaction(*args, **kwargs) as handle:
                        started.set()
                        await query_gate.wait()
                        yield handle
            retriever._session = GatedSession()
            task = asyncio.create_task(retriever.retrieve(
                request, scope=scopes[0], deadline=loop.time() + 5))
            try:
                await asyncio.wait_for(started.wait(), 3)
                async with admin.transaction():
                    await command('LOCK TABLE cragkit.documents IN ACCESS EXCLUSIVE MODE')
                    query_gate.set()
                    observed = False
                    until = loop.time() + 2
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
                    try:
                        await asyncio.wait_for(task, 6)
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
            await reuse_retriever()
        completed.append('retriever_query_deadline_cancel_and_fresh_scope_reuse')
        CURRENT_STAGE = 'schema_rejection'
        await command('ALTER TABLE cragkit.documents RENAME COLUMN authorization_revision TO probe_hidden_authorization_revision')
        renamed = True
        try:
            try:
                await session.validate(deadline=loop.time() + 5)
            except (UnsupportedCapability, IndexNotReady):
                pass
            else:
                raise RuntimeCheckError('invalid_schema_accepted')
        finally:
            await command('ALTER TABLE cragkit.documents RENAME COLUMN probe_hidden_authorization_revision TO authorization_revision')
            renamed = False
        if await rows("SELECT count(*) FROM information_schema.columns WHERE table_schema='cragkit' AND table_name='documents' AND column_name='authorization_revision'") != [(1,)]:
            raise RuntimeCheckError('schema_restore_failed')
        completed.append('schema_rejection_and_restore')
        return {'state': 'passed', 'checks': completed, 'runtime_login': True, 'maximum_connections': 2, 'cleanup_verified': True}
    finally:
        async def cleanup():
            nonlocal renamed
            errors = []
            if runtime is not None:
                try:
                    await asyncio.wait_for(runtime.close(), 3)
                except Exception:
                    errors.append('runtime_close')
            if admin is not None:
                try:
                    if renamed:
                        await command('ALTER TABLE cragkit.documents RENAME COLUMN probe_hidden_authorization_revision TO authorization_revision')
                        renamed = False
                    if await rows("SELECT count(*) FROM information_schema.columns WHERE table_schema='cragkit' AND table_name='documents' AND column_name='authorization_revision'") != [(1,)] or await rows("SELECT count(*) FROM information_schema.columns WHERE table_schema='cragkit' AND table_name='documents' AND column_name='probe_hidden_authorization_revision'") != [(0,)]:
                        raise RuntimeCheckError('schema_restore_failed')
                    if created_role:
                        async with admin.transaction():
                            if lifecycle:
                                await command(sql.SQL('REVOKE UPDATE(created_at),DELETE ON cragkit.documents FROM {}').format(sql.Identifier(role)))
                            if ingestion:
                                await command(sql.SQL('DROP POLICY IF EXISTS {} ON cragkit.index_generations').format(sql.Identifier(role + '_block_ready')))
                            for table in selected:
                                await command(sql.SQL('DROP POLICY IF EXISTS {} ON cragkit.{}').format(sql.Identifier(policy), sql.Identifier(table)))
                                permissions = 'SELECT,INSERT,UPDATE' if ingestion and table != 'migration_history' else 'SELECT'
                                await command(sql.SQL('REVOKE ' + permissions + ' ON cragkit.{} FROM {}').format(sql.Identifier(table), sql.Identifier(role)))
                            await command('DELETE FROM cragkit.documents WHERE tenant_id=ANY(%s) AND collection_id=%s', (tenants, collection))
                            await command('DELETE FROM cragkit.collections WHERE tenant_id=ANY(%s) AND collection_id=%s', (tenants, collection))
                            # CREATEROLE does not grant permission to DROP OWNED BY
                            # the new role. Revoke only this fixture's exact grants.
                            await command(sql.SQL('REVOKE USAGE ON DOMAIN cragkit.identity_text,cragkit.collection_text,cragkit.sha256_hex,cragkit.safe_count FROM {}').format(sql.Identifier(role)))
                            await command(sql.SQL('REVOKE USAGE ON SCHEMA cragkit FROM {}').format(sql.Identifier(role)))
                            await command(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
                        if await rows('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)):
                            raise RuntimeCheckError('role_cleanup_failed')
                        if await rows("SELECT count(*) FROM pg_policies WHERE schemaname='cragkit'") != [(0,)]:
                            raise RuntimeCheckError('policy_cleanup_failed')
                        for table in tables:
                            if await rows(sql.SQL('SELECT count(*) FROM cragkit.{}').format(sql.Identifier(table))) != [(0,)]:
                                raise RuntimeCheckError('fixture_cleanup_failed')
                    if locked:
                        await command('SELECT pg_advisory_unlock(1129464148,1)')
                except Exception:
                    errors.append('database_cleanup')
                finally:
                    await asyncio.wait_for(admin.close(), 3)
            if errors:
                raise RuntimeCheckError('cleanup_failed')
        try:
            async with asyncio.timeout(25):
                await cleanup()
        except Exception:
            raise RuntimeCheckError('cleanup_failed') from None
        finally:
            temporary.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--allow-test-writes', action='store_true')
    parser.add_argument('--typescript', action='store_true')
    parser.add_argument('--ingestion', action='store_true')
    parser.add_argument('--lexical', action='store_true')
    parser.add_argument('--results', action='store_true')
    parser.add_argument('--lifecycle', action='store_true')
    args = parser.parse_args()
    if not args.allow_test_writes:
        print('Runtime checks require explicit test-write authorization.')
        return 2
    try:
        async def bounded():
            timeout = (600 if args.lifecycle else 420 if args.results else 300 if args.lexical
                       else 180 if args.ingestion and args.typescript else 90)
            async with asyncio.timeout(timeout):
                return await check(
                    args.config,
                    typescript=args.typescript or args.lexical or args.results or args.lifecycle,
                    ingestion=args.ingestion or args.lexical or args.results or args.lifecycle,
                    lexical=args.lexical or args.results or args.lifecycle,
                    results=args.results or args.lifecycle, lifecycle=args.lifecycle,
                )
        result = asyncio.run(bounded())
    except RuntimeCheckError as error:
        code = str(error) if re.fullmatch(r'[a-z_]+', str(error)) else 'runtime_check_failed'
        print(f'Runtime PostgreSQL checks failed: {code}; stage={CURRENT_STAGE}.')
        return 1
    except Exception as error:
        kind = type(error).__name__
        kind = kind if re.fullmatch(r'[A-Za-z_]+', kind) else 'Exception'
        state = getattr(error, 'sqlstate', None)
        state = state if isinstance(state, str) and re.fullmatch(r'[A-Z0-9]{5}', state) else 'none'
        print(f'Runtime PostgreSQL checks failed: {kind}; SQLSTATE={state}; stage={CURRENT_STAGE}.')
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
