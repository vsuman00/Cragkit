"""Explicit committed publication fixture; restricted logins never target hosted data."""
from __future__ import annotations

from contextlib import asynccontextmanager
from hashlib import sha256
import json
from pathlib import Path
import secrets

from qdrant_authority_schema import ROOT, catalog_queries, migration as source_migration
from qdrant_publication_schema import CAPABILITY_ROLES, migration as publication_migration
from runtime_diagnostics import CleanupFailure

LOGIN_ROLES = {
    'writer': 'publication_fixture_writer',
    'supervisor': 'publication_fixture_supervisor',
    'reader': 'publication_fixture_reader',
}


class PublicationDatabase:
    """Borrow a private server; own only explicitly opened database connections.

    The outer PostgresSourceFixture owns the disposable server and directory.
    Callers keep at most one runtime client beside this administrative client.
    Neither credentials nor source rows are included in returned observations.
    """

    def __init__(self, fixture):
        self.fixture = fixture
        self.admin = None
        self._configs = {}
        self.checks = []

    def __repr__(self):
        return 'PublicationDatabase()'

    @staticmethod
    async def _connect(config):
        import psycopg
        connection = await psycopg.AsyncConnection.connect(
            host=config['host'], port=config['port'], dbname=config['dbname'],
            user=config['user'], passfile=config['passfile'], sslmode='verify-full',
            sslrootcert=config['sslrootcert'], connect_timeout=5, autocommit=True,
            options='-c statement_timeout=10000 -c lock_timeout=1000 '
                    '-c idle_in_transaction_session_timeout=15000')
        if not connection.pgconn.ssl_in_use:
            primary = RuntimeError('publication_fixture_tls_required')
            try:
                import asyncio
                await asyncio.wait_for(connection.close(), 3)
            except BaseException as error:
                raise CleanupFailure([('admin_close', error)], primary=primary, stage='fixture_setup') from None
            raise primary
        return connection

    async def __aenter__(self):
        if self.admin is not None:
            raise RuntimeError('publication_fixture_lifecycle')
        self.admin = await self._connect(self.fixture.config)
        try:
            await self._install()
            return self
        except BaseException as primary:
            await self._close(primary)
            raise

    async def __aexit__(self, kind, error, traceback):
        await self._close(error)

    async def _close(self, primary=None):
        connection, self.admin = self.admin, None
        if connection is not None:
            try:
                import asyncio
                await asyncio.wait_for(connection.close(), 3)
            except BaseException as error:
                raise CleanupFailure([('admin_close', error)], primary=primary, stage='fixture_setup') from None

    async def _install(self):
        from psycopg import sql
        source, publication = source_migration(), publication_migration()
        expected = json.loads((ROOT / 'contracts/fixtures/qdrant_publication_catalog.json').read_text())
        async with self.admin.transaction():
            await self.admin.execute('SET LOCAL search_path=pg_catalog')
            await self.admin.execute('ALTER DEFAULT PRIVILEGES REVOKE USAGE ON TYPES FROM PUBLIC')
            await self.admin.execute(source.sql, prepare=False)
            await self.admin.execute('INSERT INTO cragkit_qdrant.schema_migrations '
                '(version,checksum_sha256) VALUES(%s,%s)', (source.version, source.checksum))
            for role in CAPABILITY_ROLES:
                await self.admin.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS '
                    'NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT').format(sql.Identifier(role)))
            await self.admin.execute(publication.sql, prepare=False)
            await self.admin.execute('INSERT INTO cragkit_qdrant.schema_migrations '
                '(version,checksum_sha256) VALUES(%s,%s)', (publication.version, publication.checksum))
            for kind, name in LOGIN_ROLES.items():
                password = secrets.token_hex(32)
                await self.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER '
                    'NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION INHERIT').format(
                        sql.Identifier(name), sql.Literal(password)))
                self._configs[kind] = self.fixture.reader_config(name, password)
                if kind in ('writer', 'supervisor'):
                    capability = 'cragkit_qdrant_' + kind
                    await self.admin.execute(sql.SQL('GRANT {} TO {} WITH INHERIT TRUE, SET FALSE').format(
                        sql.Identifier(capability), sql.Identifier(name)))
                else:
                    await self.admin.execute(sql.SQL('GRANT USAGE ON SCHEMA cragkit_qdrant TO {}').format(sql.Identifier(name)))
                    await self.admin.execute(sql.SQL('GRANT SELECT ON cragkit_qdrant.documents,'
                        'cragkit_qdrant.document_revisions,cragkit_qdrant.generations,'
                        'cragkit_qdrant.members,cragkit_qdrant.schema_migrations TO {}').format(sql.Identifier(name)))
                    await self.admin.execute(sql.SQL('GRANT EXECUTE ON FUNCTION '
                        'cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean),'
                        'cragkit_qdrant.scope_grants(),cragkit_qdrant.valid_identity_array(text[]) TO {}').format(sql.Identifier(name)))
        # Re-read after the real commit, outside the installation transaction.
        await self.admin.execute('SET search_path=pg_catalog')
        cursor = await self.admin.execute(catalog_queries()[0], prepare=False)
        if await cursor.fetchall() != [(expected['catalog_fingerprint'],)]:
            raise RuntimeError('publication_fixture_committed_catalog_mismatch')
        self.checks += ['committed_exact_publication_schema', 'dedicated_login_roles_provisioned']

    def config(self, kind):
        if self.admin is None or kind not in LOGIN_ROLES or kind not in self._configs:
            raise RuntimeError('publication_fixture_role')
        return dict(self._configs[kind])

    async def release_admin(self):
        """Release the setup client before a two-runtime-client race window."""
        await self._close()

    @asynccontextmanager
    async def connection(self, kind):
        connection = await self._connect(self.config(kind))
        primary = None
        try:
            cursor = await connection.execute('SELECT current_user=session_user, '
                'NOT rolsuper AND NOT rolbypassrls AND NOT rolcreaterole AND NOT rolcreatedb '
                'AND NOT rolreplication FROM pg_roles WHERE rolname=current_user')
            if await cursor.fetchall() != [(True, True)]:
                raise RuntimeError('publication_fixture_login_privileges')
            yield connection
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                import asyncio
                await asyncio.wait_for(connection.close(), 3)
            except BaseException as error:
                raise CleanupFailure([('runtime_close', error)], primary=primary, stage='fixture_setup') from None


async def bind_scope(connection, records, *, intent_id=None, owner_token=None, **overrides):
    """Bind only fixed setting names to this synthetic fully scoped document."""
    document = records['document']
    settings = dict(tenant_id=document['tenant_id'], collection=document['collection'],
        principal_id='reader-a', grant_ids='["grant-a"]',
        authorization_revision=document['authorization_revision'],
        writer_document_id=document['document_id'],
        writer_intent_id=intent_id or records['intent']['intent_id'],
        writer_owner_token=owner_token or '00000000-0000-4000-8000-000000000001',
        backend_instance_id=records['backend']['instance_id'])
    if any(key not in settings for key in overrides):
        raise ValueError('publication_fixture_setting')
    settings.update(overrides)
    for name, value in settings.items():
        await connection.execute('SELECT set_config(%s,%s,true)', ('cragkit_qdrant.' + name, value))


def observation_digest(value):
    """Hash bounded synthetic observation tuples without retaining row text."""
    return sha256(json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


async def committed_boundary_checks(database):
    """Prove SQL commit boundaries with a real writer login and retained records.

    These are schema/transaction probes, not evidence of manager HTTP completion.
    The seed is deliberately synthetic; no provider identity or user data is used.
    """
    from qdrant_publication_schema import insert_sql, seed_records
    records = seed_records()
    common = {key: records['document'][key] for key in ('tenant_id', 'collection', 'document_id')}
    where = 'tenant_id=%s AND collection=%s AND document_id=%s'
    scope_values = tuple(common.values())
    token = '00000000-0000-4000-8000-000000000001'
    checks = []
    async with database.connection('supervisor') as connection:
        async with connection.transaction():
            await bind_scope(connection, records)
            await connection.execute(insert_sql('backend_instances', records['backend']))
    async with database.connection('writer') as connection:
        async with connection.transaction():
            await bind_scope(connection, records)
            for table, key in [('publication_intents', 'intent'), ('documents', 'document'),
                               ('document_revisions', 'revision'), ('generations', 'generation')]:
                await connection.execute(insert_sql(table, records[key]))
            for table, key in [('members', 'members'), ('point_claims', 'claims'), ('vector_replays', 'replays')]:
                for record in records[key]:
                    await connection.execute(insert_sql(table, record))
        checks.append('restricted_login_committed_stage_claims_and_original_replays')
    # Reconnect, so stage visibility cannot depend on a borrowed transaction.
    async with database.connection('writer') as connection:
        async with connection.transaction():
            await bind_scope(connection, records)
            cursor = await connection.execute('SELECT count(*) FROM cragkit_qdrant.vector_replays WHERE ' + where, scope_values)
            if await cursor.fetchall() != [(2,)]:
                raise RuntimeError('publication_fixture_committed_stage_missing')
            owner = dict(common, instance_id=records['backend']['instance_id'],
                intent_id=records['intent']['intent_id'], owner_token=token, backend_epoch=1)
            await connection.execute(insert_sql('document_owners', owner))
            await connection.execute("UPDATE cragkit_qdrant.publication_intents SET state='writing' WHERE " + where, scope_values)
            body = b'{"synthetic":"cross-commit-boundary"}'
            dispatch = dict(common, intent_id=records['intent']['intent_id'], dispatch_id='boundary-1',
                instance_id=records['backend']['instance_id'], sequence=1, owner_token=token, backend_epoch=1,
                credential_generation='credential-1', operation='complete_point_upsert',
                request_bytes=body, request_sha256=sha256(body).hexdigest())
            await connection.execute(insert_sql('dispatch_journal', dispatch))
            def point(claim):
                return dict(common, intent_id=records['intent']['intent_id'], dispatch_id='boundary-1',
                    **{key: claim[key] for key in ('backend_namespace','physical_collection','collection_incarnation','point_id')})
            await connection.execute(insert_sql('dispatch_points', point(records['claims'][0])))
        checks.append('reservation_and_initial_membership_commit')
        async with connection.transaction():
            await bind_scope(connection, records)
            try:
                async with connection.transaction():
                    await connection.execute(insert_sql('dispatch_points', point(records['claims'][1])))
            except Exception as error:
                if getattr(error, 'sqlstate', None) != '23514':
                    raise
            else:
                raise RuntimeError('publication_fixture_cross_commit_membership_accepted')
        checks.append('created_xid_rejects_membership_extension_after_commit')
        async with connection.transaction():
            await bind_scope(connection, records,
                owner_token='00000000-0000-4000-8000-000000000002')
            try:
                async with connection.transaction():
                    await connection.execute('UPDATE cragkit_qdrant.document_owners SET owner_token=%s WHERE ' + where,
                        ('00000000-0000-4000-8000-000000000002', *scope_values))
            except Exception as error:
                if getattr(error, 'sqlstate', None) != '23514':
                    raise
            else:
                raise RuntimeError('publication_fixture_reserved_owner_transfer_accepted')
        checks.append('committed_reserved_dispatch_blocks_successor_owner')
    # While a committed uncertain vector operation exists, authoritative denial
    # remains a separate short write. It never waits for supervisor recovery.
    async with database.connection('writer') as connection:
        async with connection.transaction():
            await bind_scope(connection, records)
            await connection.execute("UPDATE cragkit_qdrant.documents SET principal_ids='{}',grant_ids='{}',"
                "authorization_revision='auth-denied',mutation_epoch=2,tombstoned=true WHERE " + where, scope_values)
        async with connection.transaction():
            await bind_scope(connection, records, authorization_revision='auth-denied')
            cursor = await connection.execute('SELECT tombstoned,mutation_epoch FROM cragkit_qdrant.documents WHERE ' + where, scope_values)
            if await cursor.fetchall() != [(True, 2)]:
                raise RuntimeError('publication_fixture_immediate_tombstone_missing')
    checks.append('committed_tombstone_independent_of_reserved_replica_dispatch')
    async with database.connection('reader') as connection:
        async with connection.transaction():
            await bind_scope(connection, records, authorization_revision='auth-denied')
            for table in ('documents', 'document_revisions', 'generations', 'members'):
                cursor = await connection.execute('SELECT count(*) FROM cragkit_qdrant.' + table)
                if await cursor.fetchall() != [(0,)]:
                    raise RuntimeError('publication_fixture_tombstone_source_visible')
    checks.append('fresh_reader_login_cannot_release_tombstoned_staged_source')
    # Observe a genuine lock wait, then the committed new epoch/state. A fixed
    # sleep alone cannot establish that the competing admission was blocked.
    import asyncio
    async with database.connection('writer') as connection:
        pending = None
        try:
            async with connection.transaction():
                await bind_scope(connection, records)
                async with database.admin.transaction():
                    await bind_scope(database.admin, records)
                    await database.admin.execute('SET LOCAL ROLE cragkit_qdrant_supervisor')
                    await database.admin.execute("UPDATE cragkit_qdrant.backend_instances SET state='recovery_blocked',"
                        "epoch=epoch+1,recovery_id='native-gate-race' WHERE instance_id=%s", (records['backend']['instance_id'],))
                    pending = asyncio.create_task(connection.execute('SELECT epoch,state FROM cragkit_qdrant.backend_instances '
                        'WHERE instance_id=%s FOR SHARE', (records['backend']['instance_id'],)))
                    observed_wait = False
                    for _ in range(100):
                        cursor = await database.admin.execute('SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=%s AND NOT granted)',
                            (connection.info.backend_pid,))
                        if await cursor.fetchall() == [(True,)]:
                            observed_wait = True
                            break
                        if pending.done():
                            break
                        await asyncio.sleep(.005)
                    if not observed_wait:
                        raise RuntimeError('publication_fixture_gate_wait_not_observed')
                cursor = await asyncio.wait_for(pending, 2)
                if await cursor.fetchall() != [(2, 'recovery_blocked')]:
                    raise RuntimeError('publication_fixture_stale_gate_snapshot')
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
    checks.append('two_connection_gate_wait_observed_then_fresh_committed_epoch')
    return checks


async def writer_role_checks(database, queries):
    """Exercise actual native permission predicates against committed unsafe grants."""
    import asyncio
    from psycopg import sql
    writer = sql.Identifier(LOGIN_ROLES['writer'])
    capability = sql.Identifier('cragkit_qdrant_writer')
    checks = []
    async with database.connection('writer') as connection:
        async def expect(expected):
            for query in queries:
                cursor = await connection.execute(query, prepare=False)
                if await cursor.fetchall() != [(expected,)]:
                    raise RuntimeError('publication_fixture_writer_privilege_predicate')
        async def changed(grant, revoke):
            await database.admin.execute(grant)
            primary = None
            try:
                await expect(False)
            except BaseException as error:
                primary = error
                raise
            finally:
                try:
                    await asyncio.wait_for(database.admin.execute(revoke), 3)
                except BaseException as error:
                    raise CleanupFailure([('privilege_revoke', error)], primary=primary, stage='fixture_setup') from None
            await expect(True)
        await expect(True)
        for target, label in ((writer, 'login'), (capability, 'fixed_capability')):
            await changed(sql.SQL('GRANT UPDATE(dense_blob) ON cragkit_qdrant.vector_replays TO {}').format(target),
                sql.SQL('REVOKE UPDATE(dense_blob) ON cragkit_qdrant.vector_replays FROM {}').format(target))
            checks.append('native_writer_predicates_reject_' + label + '_extra_column_write')
        await changed(sql.SQL('GRANT EXECUTE ON FUNCTION cragkit_qdrant.guard_backend_instance() TO {}').format(capability),
            sql.SQL('REVOKE EXECUTE ON FUNCTION cragkit_qdrant.guard_backend_instance() FROM {}').format(capability))
        checks.append('native_writer_predicates_reject_fixed_capability_extra_helper')
        await changed(sql.SQL('GRANT cragkit_qdrant_supervisor TO {} WITH INHERIT FALSE, SET FALSE').format(writer),
            sql.SQL('REVOKE cragkit_qdrant_supervisor FROM {}').format(writer))
        checks.append('native_writer_predicates_reject_noninherited_supervisor_membership')
        await changed(sql.SQL('ALTER ROLE {} CREATEDB').format(writer), sql.SQL('ALTER ROLE {} NOCREATEDB').format(writer))
        checks.append('native_writer_predicates_reject_privileged_login_flags')
        await changed(sql.SQL('ALTER ROLE {} LOGIN').format(capability), sql.SQL('ALTER ROLE {} NOLOGIN').format(capability))
        checks.append('native_writer_predicates_reject_fixed_capability_login_conversion')
        await database.admin.execute('CREATE ROLE publication_fixture_safe_group NOLOGIN NOSUPERUSER NOBYPASSRLS '
            'NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT')
        primary = None
        try:
            await changed('GRANT publication_fixture_safe_group TO cragkit_qdrant_writer WITH INHERIT FALSE, SET FALSE',
                'REVOKE publication_fixture_safe_group FROM cragkit_qdrant_writer')
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                await asyncio.wait_for(database.admin.execute('DROP ROLE publication_fixture_safe_group'), 3)
            except BaseException as error:
                raise CleanupFailure([('role_drop', error)], primary=primary, stage='fixture_setup') from None
        checks.append('native_writer_predicates_reject_fixed_capability_outbound_membership')
    return checks
