"""Optional PostgreSQL transport for exact, journal-authorized fixture recovery."""
from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import stat

from runtime_recovery import Manifest, RecoveryRefused, target_fingerprint


def _driver():
    return importlib.import_module('psycopg')


def _remaining(deadline):
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise RecoveryRefused('invalid_manifest')
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise TimeoutError()
    return remaining


async def snapshot_histories(connection, *, vectors):
    """Hash stable history identities, never modifying either ledger."""
    if type(vectors) is not bool:
        raise RecoveryRefused('invalid_manifest')
    histories = []
    for table in ('cragkit.migration_history', 'cragkit_vector.setup_history')[:2 if vectors else 1]:
        cursor = await connection.execute(
            '/* recovery:history */ SELECT version,checksum,extract(epoch FROM applied_at)::text '
            'FROM ' + table + ' ORDER BY version,checksum,applied_at')
        rows = await cursor.fetchall()
        if (type(rows) not in (list, tuple) or not 1 <= len(rows) <= 256
                or any(type(row) not in (list, tuple) or len(row) != 3
                       or any(type(value) is not str or len(value) > 256 for value in row)
                       for row in rows)):
            raise RecoveryRefused('history_mismatch')
        encoded = json.dumps(sorted([list(row) for row in rows]),
                             ensure_ascii=True, separators=(',', ':')).encode('ascii')
        histories.append(hashlib.sha256(encoded).hexdigest())
    return histories[0], histories[1] if vectors else None


def _policies(manifest):
    expected = {('cragkit', table, manifest.policy):
                ('*' if manifest.ingestion and table not in ('migration_history', 'embedding_profiles') else 'r', True)
                for table in manifest.selected}
    if manifest.vectors:
        expected[('cragkit_vector', 'setup_history', manifest.policy)] = ('r', True)
        expected[('cragkit', 'embedding_profiles', manifest.role + '_hide_profile')] = ('r', False)
    if manifest.ingestion:
        expected[('cragkit', 'index_generations', manifest.role + '_block_ready')] = ('w', False)
    if manifest.lifecycle:
        expected[('cragkit', 'documents', manifest.role + '_lifecycle_insert')] = ('a', False)
        expected[('cragkit', 'document_revisions', manifest.role + '_lifecycle_hidden')] = ('r', False)
    return expected


class PostgresTransport:
    operation = 'admin_connect'

    def __init__(self, connection, sql, target_sha256, *, operational_error=None):
        self.connection = connection
        self.sql = sql
        self.target_sha256 = target_sha256
        self._locked = False
        self._operational_error = operational_error

    async def _rows(self, query, params=None):
        cursor = await self.connection.execute(query, params)
        return await cursor.fetchall()

    async def _inventory(self, manifest):
        sql = self.sql
        queries = [sql.SQL('SELECT {}::text,count(*)::bigint FROM cragkit.{} AS fixture CROSS JOIN scope '
                           'WHERE fixture.tenant_id=ANY(scope.tenants) '
                           'AND fixture.collection_id=scope.collection').format(
                               sql.Literal(table), sql.Identifier(table)) for table in manifest.tables]
        return await self._rows(
            sql.SQL('/* recovery:inventory */ WITH scope AS '
                    '(SELECT %s::text[] AS tenants,%s::text AS collection) ') + sql.SQL(' UNION ALL ').join(queries),
            (list(manifest.tenants), manifest.collection))

    async def _schema(self):
        return await self._rows("/* recovery:schema */ SELECT attname,atttypid='cragkit.identity_text'::regtype,attnotnull "
            "FROM pg_attribute WHERE attrelid='cragkit.documents'::regclass AND NOT attisdropped "
            "AND attname IN ('authorization_revision','probe_hidden_authorization_revision') ORDER BY attname")

    async def _safe_delete_graph(self, manifest):
        # Include optional vector storage even for a base fixture: a document
        # deletion can reach it through the canonical chunk foreign keys.
        from cragkit.lifecycle import _PURGE_CATALOG_SQL
        names = sorted(set(manifest.tables) | {'chunk_vectors_fake_1536'})
        query = """/* recovery:cascade */ WITH document_graph AS (""" + _PURGE_CATALOG_SQL + """),
        collection_edges AS (
          SELECT c.* FROM pg_constraint c
          WHERE c.contype='f' AND c.confrelid='cragkit.collections'::regclass
        ), known_tables AS (
          SELECT c.* FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname='cragkit' AND c.relname=ANY(%s)
        ) SELECT (SELECT * FROM document_graph)
        AND (SELECT count(*) FROM collection_edges)=1
        AND EXISTS (SELECT 1 FROM collection_edges c
          WHERE c.conrelid='cragkit.documents'::regclass AND c.confdeltype='c' AND c.convalidated
          AND ARRAY(SELECT a.attname::text FROM unnest(c.conkey) WITH ORDINALITY k(n,i)
            JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.n ORDER BY k.i)
              = ARRAY['tenant_id','collection_id']::text[]
          AND ARRAY(SELECT a.attname::text FROM unnest(c.confkey) WITH ORDINALITY k(n,i)
            JOIN pg_attribute a ON a.attrelid=c.confrelid AND a.attnum=k.n ORDER BY k.i)
              = ARRAY['tenant_id','collection_id']::text[]
          AND (SELECT count(*) FROM pg_trigger t WHERE t.tgconstraint=c.oid AND t.tgisinternal)=4
          AND NOT EXISTS (SELECT 1 FROM pg_trigger t WHERE t.tgconstraint=c.oid
            AND (NOT t.tgisinternal OR t.tgenabled NOT IN ('O','A'))))
        AND (SELECT count(*) FROM known_tables)>=%s
        AND NOT EXISTS (SELECT 1 FROM known_tables c WHERE c.relkind<>'r' OR c.relispartition
          OR EXISTS (SELECT 1 FROM pg_inherits i WHERE i.inhrelid=c.oid OR i.inhparent=c.oid))
        AND NOT EXISTS (SELECT 1 FROM pg_trigger t JOIN known_tables c ON c.oid=t.tgrelid
          WHERE NOT t.tgisinternal AND t.tgenabled<>'D' AND (t.tgtype::int & 8)<>0)
        AND NOT EXISTS (SELECT 1 FROM pg_rewrite r JOIN known_tables c ON c.oid=r.ev_class
          WHERE r.ev_type='4')
        """
        return await self._rows(query, (names, len(manifest.tables))) == [(True,)]

    async def _role(self, manifest):
        return await self._rows('''/* recovery:role */ SELECT r.oid,r.rolsuper,r.rolcreatedb,r.rolcreaterole,
            r.rolreplication,r.rolbypassrls,r.rolinherit,r.rolconnlimit,
            shobj_description(r.oid,'pg_authid'),
            EXISTS(SELECT 1 FROM pg_auth_members m WHERE m.member=r.oid
                OR (m.roleid=r.oid AND m.member<>current_user::regrole::oid))
            FROM pg_roles r WHERE r.rolname=%s''', (manifest.role,))

    async def _policy_rows(self, manifest, role_oid):
        names = sorted({key[2] for key in _policies(manifest)})
        return await self._rows('''/* recovery:policies */ SELECT n.nspname,c.relname,p.polname,
            p.polcmd,p.polpermissive,p.polroles::oid[] FROM pg_policy p
            JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE p.polname=ANY(%s) OR (%s::oid IS NOT NULL AND %s::oid=ANY(p.polroles))''',
            (names, role_oid, role_oid))

    async def clean(self, manifest, *, deadline):
        if type(manifest) is not Manifest:
            raise RecoveryRefused('invalid_manifest')
        if manifest.target_sha256 != self.target_sha256:
            raise RecoveryRefused('target_mismatch')
        try:
            async with asyncio.timeout(_remaining(deadline)):
                await self._clean(manifest, deadline=deadline)
        except Exception as error:
            # psycopg uses SQLSTATE-less OperationalError for an already broken
            # connection. Match the actual optional driver type and handle state;
            # authentication/configuration OperationalErrors are not blanket retries.
            if (self._operational_error is not None
                    and isinstance(error, self._operational_error)
                    and getattr(error, 'sqlstate', None) is None
                    and (getattr(self.connection, 'broken', None) is True
                         or getattr(self.connection, 'closed', None) is True)):
                raise ConnectionError('recovery_connection_lost') from None
            raise

    async def _clean(self, manifest, *, deadline):
        self.operation = 'lock_acquire'
        if await self._rows('/* recovery:lock */ SELECT pg_try_advisory_lock(1129464148,1)') != [(True,)]:
            raise RecoveryRefused('lock_busy')
        self._locked = True
        # Keep the lock until every ownership check, mutation and final check ends.
        self.operation = 'verify_inventory'
        if await snapshot_histories(self.connection, vectors=manifest.vectors) != (
                manifest.migration_sha256, manifest.vector_sha256):
            raise RecoveryRefused('history_mismatch')
        roles = await self._role(manifest)
        if len(roles) > 1:
            raise RecoveryRefused('unsafe_role')
        role_oid = roles[0][0] if roles else None
        if roles:
            role = roles[0]
            if role[8] != manifest.owner_marker:
                raise RecoveryRefused('ownership_mismatch')
            if any(value is not False for value in role[1:7]) or role[7] != 1 or role[9] is not False:
                raise RecoveryRefused('unsafe_role')
        policies = await self._policy_rows(manifest, role_oid)
        expected = _policies(manifest)
        for schema, table, name, command, permissive, recipients in policies:
            if ((schema, table, name) not in expected
                    or (command, permissive) != expected[(schema, table, name)]
                    or recipients != [role_oid]):
                raise RecoveryRefused('unexpected_policy')
        schema = await self._schema()
        canonical = [('authorization_revision', True, True)]
        hidden = [('probe_hidden_authorization_revision', True, True)]
        if schema != canonical and not (roles and manifest.allow_schema_restore and schema == hidden):
            raise RecoveryRefused('schema_mismatch')
        # A temporary lifecycle test table is deliberately outside this journal's
        # authorized resources; a human must resolve it before recovery can delete.
        extra = await self._rows("/* recovery:extra */ SELECT to_regclass(%s)",
                                 ('cragkit.' + manifest.role + '_unknown_purge',))
        if extra != [(None,)]:
            raise RecoveryRefused('schema_mismatch')
        if not await self._safe_delete_graph(manifest):
            raise RecoveryRefused('schema_mismatch')
        inventory = await self._inventory(manifest)
        if not roles and (policies or any(count != 0 for _, count in inventory)):
            raise RecoveryRefused('fixture_remaining')
        if roles:
            self.operation = 'fixture_transaction'
            sql = self.sql
            # Quiesce only the role whose ownership marker and attributes passed.
            await self.connection.execute(sql.SQL('ALTER ROLE {} NOLOGIN').format(sql.Identifier(manifest.role)))
            stopped = await self._rows('/* recovery:terminate */ SELECT pg_terminate_backend(pid) '
                'FROM pg_stat_activity WHERE usesysid=%s::oid AND pid<>pg_backend_pid()', (role_oid,))
            if any(row != (True,) for row in stopped):
                raise RecoveryRefused('fixture_remaining')
            async with self.connection.transaction():
                async with self.connection.pipeline():
                    if schema == hidden:
                        await self.connection.execute('ALTER TABLE cragkit.documents RENAME COLUMN '
                            'probe_hidden_authorization_revision TO authorization_revision')
                    for schema_name, table, name, *_ in policies:
                        await self.connection.execute(sql.SQL('DROP POLICY {} ON {}.{}').format(
                            sql.Identifier(name), sql.Identifier(schema_name), sql.Identifier(table)))
                    for table in manifest.selected:
                        await self.connection.execute(sql.SQL('REVOKE ALL PRIVILEGES ON TABLE cragkit.{} FROM {}').format(
                            sql.Identifier(table), sql.Identifier(manifest.role)))
                    if manifest.lifecycle:
                        await self.connection.execute(sql.SQL('REVOKE UPDATE(created_at) ON cragkit.documents FROM {}').format(sql.Identifier(manifest.role)))
                    if manifest.vectors:
                        await self.connection.execute(sql.SQL('REVOKE ALL PRIVILEGES ON TABLE cragkit_vector.setup_history FROM {}').format(sql.Identifier(manifest.role)))
                        await self.connection.execute(sql.SQL('REVOKE ALL PRIVILEGES ON SCHEMA cragkit_vector FROM {}').format(sql.Identifier(manifest.role)))
                    await self.connection.execute('DELETE FROM cragkit.documents WHERE tenant_id=ANY(%s) AND collection_id=%s',
                                                  (list(manifest.tenants), manifest.collection))
                    await self.connection.execute('DELETE FROM cragkit.collections WHERE tenant_id=ANY(%s) AND collection_id=%s',
                                                  (list(manifest.tenants), manifest.collection))
                    await self.connection.execute(sql.SQL('REVOKE USAGE ON DOMAIN cragkit.identity_text,cragkit.collection_text,'
                        'cragkit.sha256_hex,cragkit.safe_count FROM {}').format(sql.Identifier(manifest.role)))
                    await self.connection.execute(sql.SQL('REVOKE ALL PRIVILEGES ON SCHEMA cragkit FROM {}').format(sql.Identifier(manifest.role)))
                    await self.connection.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(manifest.role)))
        self.operation = 'verify_inventory'
        if (await self._role(manifest) or await self._policy_rows(manifest, None)
                or any(count != 0 for _, count in await self._inventory(manifest))):
            raise RecoveryRefused('fixture_remaining')
        if await self._schema() != canonical:
            raise RecoveryRefused('schema_mismatch')
        if await snapshot_histories(self.connection, vectors=manifest.vectors) != (
                manifest.migration_sha256, manifest.vector_sha256):
            raise RecoveryRefused('history_mismatch')
        self.operation = 'lock_release'
        if await self._rows('/* recovery:unlock */ SELECT pg_advisory_unlock(1129464148,1)') != [(True,)]:
            raise RecoveryRefused('fixture_remaining')
        self._locked = False

    async def close(self):
        self.operation = 'admin_close'
        await self.connection.close()


async def connect_transport(config, deadline):
    """Open one explicitly configured, verified direct administrator connection."""
    remaining = _remaining(deadline)
    if any(name.startswith('PG') and value for name, value in os.environ.items()):
        raise RecoveryRefused('target_mismatch')
    for name in ('host', 'dbname', 'user'):
        value = getattr(config, name, None)
        if type(value) is not str or not 1 <= len(value) <= 253 or not re.fullmatch(r'[A-Za-z0-9_.@-]+', value):
            raise RecoveryRefused('target_mismatch')
    if 'pooler' in config.host.lower() or type(config.port) is not int or not 1 <= config.port <= 65535:
        raise RecoveryRefused('target_mismatch')
    try:
        cert, passfile = Path(config.sslrootcert), Path(config.passfile)
        info = passfile.lstat()
        if (not cert.is_absolute() or not cert.is_file() or not passfile.is_absolute()
                or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise RecoveryRefused('unsafe_path')
    except (OSError, TypeError, ValueError):
        raise RecoveryRefused('unsafe_path') from None
    driver = _driver()
    connection = None
    try:
        async with asyncio.timeout(remaining):
            connection = await driver.AsyncConnection.connect(
                host=config.host, port=config.port, dbname=config.dbname, user=config.user,
                sslmode='verify-full', sslrootcert=str(cert), passfile=str(passfile),
                connect_timeout=max(1, math.ceil(min(5, remaining))), autocommit=True,
                application_name='cragkit-runtime-recovery',
                options='-c statement_timeout=5000 -c lock_timeout=2000 -c idle_in_transaction_session_timeout=10000')
        # A connector that suppresses cancellation may still return a handle;
        # check the absolute budget and close it instead of leaking late success.
        _remaining(deadline)
        if getattr(getattr(connection, 'pgconn', None), 'ssl_in_use', None) is not True:
            raise RecoveryRefused('target_mismatch')
        identity = connection.info
        if (identity.host, identity.port, identity.dbname, identity.user) != (
                config.host, config.port, config.dbname, config.user):
            raise RecoveryRefused('target_mismatch')
    except BaseException:
        if connection is not None:
            await connection.close()
        raise
    return PostgresTransport(connection, driver.sql,
                             target_fingerprint(config.host, config.port, config.dbname, config.user),
                             operational_error=driver.OperationalError)
