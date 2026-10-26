"""Actual PostgreSQL probes of both native source-reader permission predicates."""
from __future__ import annotations

import asyncio
import json

from qdrant_authority_schema import ROOT, catalog_queries
from qdrant_publication_schema import CAPABILITY_ROLES
from check_qdrant_publication_schema import owned_connection
from runtime_diagnostics import CleanupFailure


async def node_reader_queries():
    """Read compiled Node constants without credentials, sockets or a pool."""
    script = ("import {AUTHORITY_ROLE_SQL,AUTHORITY_PUBLICATION_CATALOG_SQL} "
        "from './packages/typescript/dist/qdrant-authority.js';"
        "process.stdout.write(JSON.stringify({role:AUTHORITY_ROLE_SQL,catalog:AUTHORITY_PUBLICATION_CATALOG_SQL}));")
    process = await asyncio.create_subprocess_exec('node','--input-type=module','-e',script,
        cwd=ROOT,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        output,errors = await asyncio.wait_for(process.communicate(),5)
        if process.returncode != 0 or errors or len(output)>65536:
            raise RuntimeError('reader_node_query_constants')
        value=json.loads(output)
        if (type(value) is not dict or set(value)!={'role','catalog'}
                or any(type(item) is not str or not 1<=len(item)<=32768 for item in value.values())):
            raise RuntimeError('reader_node_query_constants')
        return value
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(),2)
            except TimeoutError:
                process.kill()
                await asyncio.wait_for(process.wait(),2)


async def check_reader_privileges(admin,config,*,publication):
    """Use one extra TLS reader client; restore each deliberately unsafe grant."""
    import psycopg
    from psycopg import sql
    from check_python_postgres import require_client_tls
    from cragkit._qdrant_authority import _ROLE_SQL, _PUBLICATION_CATALOG_SQL

    node=await node_reader_queries()
    reader=sql.Identifier(config['user'])
    if not publication:
        # Role definitions do not alter the source-only catalog. These exact
        # names must still be rejected when membership does not inherit grants.
        for role in CAPABILITY_ROLES:
            await admin.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT').format(sql.Identifier(role)))
    connection=await psycopg.AsyncConnection.connect(host=config['host'],port=config['port'],
        dbname=config['dbname'],user=config['user'],passfile=config['passfile'],
        sslmode='verify-full',sslrootcert=config['sslrootcert'],connect_timeout=3,
        autocommit=True,options='-c statement_timeout=10000 -c lock_timeout=1000')
    async with owned_connection(connection):
        require_client_tls(connection)

        async def expect(allowed):
            for query in (_ROLE_SQL,node['role']):
                cursor=await connection.execute(query,prepare=False)
                if await cursor.fetchall()!=[(allowed,)]:
                    raise RuntimeError('reader_permission_predicate_mismatch')

        async def changed(grant,revoke):
            await admin.execute(grant)
            primary=None
            try:
                await expect(False)
            except BaseException as error:
                primary=error
                raise
            finally:
                try:
                    await asyncio.wait_for(admin.execute(revoke),3)
                except BaseException as error:
                    raise CleanupFailure([('privilege_revoke',error)],primary=primary,stage='fixture_setup') from None
            await expect(True)

        await expect(True)
        for role in CAPABILITY_ROLES:
            await changed(sql.SQL('GRANT {} TO {} WITH INHERIT FALSE, SET TRUE').format(sql.Identifier(role),reader),
                sql.SQL('REVOKE {} FROM {}').format(sql.Identifier(role),reader))
        await changed(sql.SQL('GRANT UPDATE(tag) ON cragkit_qdrant.documents TO {}').format(reader),
            sql.SQL('REVOKE UPDATE(tag) ON cragkit_qdrant.documents FROM {}').format(reader))
        checks=['python_node_sql_predicates_reject_noninherited_capability_memberships_and_column_writes']
        if publication:
            await changed(sql.SQL('GRANT SELECT(state) ON cragkit_qdrant.publication_intents TO {}').format(reader),
                sql.SQL('REVOKE SELECT(state) ON cragkit_qdrant.publication_intents FROM {}').format(reader))
            await changed(sql.SQL('GRANT EXECUTE ON FUNCTION cragkit_qdrant.lock_publication_owner(text,text,text,text,uuid,bigint,boolean) TO {}').format(reader),
                sql.SQL('REVOKE EXECUTE ON FUNCTION cragkit_qdrant.lock_publication_owner(text,text,text,text,uuid,bigint,boolean) FROM {}').format(reader))
            checks.append('python_node_sql_predicates_reject_operational_column_reads_and_helper_execution')

    if publication:
        fingerprint_query,_=catalog_queries()
        cursor=await admin.execute(fingerprint_query,prepare=False)
        before=await cursor.fetchall()
        for drift in (
            'ALTER POLICY writer_read ON cragkit_qdrant.publication_intents USING (true)',
            'ALTER FUNCTION cragkit_qdrant.writer_scope(text,text,text) VOLATILE',
            'ALTER TABLE cragkit_qdrant.publication_intents ADD COLUMN probe_unexpected integer',
            'GRANT SELECT ON cragkit_qdrant.publication_intents TO PUBLIC',
        ):
            async with admin.transaction(force_rollback=True):
                await admin.execute(drift)
                cursor=await admin.execute(fingerprint_query,prepare=False)
                if await cursor.fetchall()==before:
                    raise RuntimeError('reader_publication_catalog_drift_not_detected')
            cursor=await admin.execute(fingerprint_query,prepare=False)
            if await cursor.fetchall()!=before:
                raise RuntimeError('reader_publication_catalog_drift_rollback')
        checks.append('publication_fingerprint_detects_policy_function_column_and_public_acl_drift')
        async with admin.transaction(force_rollback=True):
            cursor=await admin.execute("SELECT t.tgname FROM pg_trigger t WHERE t.tgrelid='cragkit_qdrant.documents'::regclass AND t.tgisinternal ORDER BY t.tgname LIMIT 1")
            names=await cursor.fetchall()
            if len(names)!=1:
                raise RuntimeError('reader_internal_trigger_fixture')
            await admin.execute(sql.SQL('ALTER TABLE cragkit_qdrant.documents DISABLE TRIGGER {}').format(sql.Identifier(names[0][0])))
            cursor=await admin.execute(fingerprint_query,prepare=False)
            if await cursor.fetchall()!=before:
                raise RuntimeError('reader_internal_trigger_fingerprint_assumption')
            for query in (_PUBLICATION_CATALOG_SQL,node['catalog']):
                cursor=await admin.execute(query,prepare=False)
                if await cursor.fetchall()!=[(False,)]:
                    raise RuntimeError('reader_disabled_internal_trigger_admitted')
        for query in (_PUBLICATION_CATALOG_SQL,node['catalog']):
            cursor=await admin.execute(query,prepare=False)
            if await cursor.fetchall()!=[(True,)]:
                raise RuntimeError('reader_internal_trigger_rollback')
        checks.append('python_node_structural_probes_reject_disabled_internal_fk_trigger_with_unchanged_fingerprint')
    return checks
