"""Opt-in native interruption acceptance for journal-owned development fixtures."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys

import check_python_postgres as parent
from runtime_diagnostics import CleanupFailure
from runtime_recovery import Journal, RecoveryRefused


async def worker(config):
    async def stop_after_fixture(journal, admin):
        manifest = journal.manifest
        # The V4 fixture initially has policies but no rows. Seed both exact tenants
        # so SIGKILL recovery must remove rows as well as the role and policies.
        async with admin.transaction():
            for tenant in manifest.tenants:
                await admin.execute('INSERT INTO cragkit.collections(tenant_id,collection_id) VALUES (%s,%s)',
                                    (tenant, manifest.collection))
                await admin.execute('INSERT INTO cragkit.documents(tenant_id,collection_id,document_id,authorization_revision) '
                                    'VALUES (%s,%s,%s,%s)', (tenant, manifest.collection, 'synthetic-recovery', 'scope-rev'))
        print(json.dumps({'fixture_ready': True, 'run_id': manifest.run_id}), flush=True)
        await asyncio.Event().wait()
    await parent.check(config, neon=True, hybrid=True, _test_hook=stop_after_fixture)


async def check(config):
    import runtime_recovery_postgres as transport
    from cragkit._postgres_pool import parse_pool_config
    from runtime_recovery import target_fingerprint
    parsed = parse_pool_config(parent.load_config(config))
    target = target_fingerprint(parsed.host, parsed.port, parsed.dbname, parsed.user)
    checks = []
    async def snapshot():
        handle = await transport.connect_transport(parsed, asyncio.get_running_loop().time() + 20)
        try:
            snapshots = []
            for query in (
                'SELECT row_to_json(r)::text FROM pg_roles r ORDER BY rolname',
                'SELECT row_to_json(m)::text FROM pg_auth_members m ORDER BY roleid,member,grantor',
                'SELECT row_to_json(p)::text FROM cragkit.embedding_profiles p ORDER BY profile_id',
            ):
                cursor = await handle.connection.execute(query)
                body = json.dumps(await cursor.fetchall(), ensure_ascii=True,
                                  separators=(',', ':')).encode('ascii')
                snapshots.append(hashlib.sha256(body).hexdigest())
            histories = await transport.snapshot_histories(handle.connection, vectors=True)
            return snapshots, histories
        finally:
            await handle.close()
    baseline = await snapshot()
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(Path(__file__).resolve()), '--config', str(config),
        '--allow-test-writes', '--confirm-dedicated-target', '--worker',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=8192)
    run_id = None
    try:
        async with asyncio.timeout(120):
            ready = json.loads(await process.stdout.readline())
        if ready.get('fixture_ready') is not True:
            raise RuntimeError('fixture_not_ready')
        run_id = ready['run_id']
        Journal.load(run_id, target_sha256=target)
        process.kill()
        async with asyncio.timeout(10):
            _, stderr = await process.communicate()
        if process.returncode != -9 or stderr:
            raise RuntimeError('interruption_not_observed')
        outcome = await parent.recover_run(config, run_id, neon=True)
        if outcome['cleanup_verified'] is not True:
            raise RuntimeError('interruption_cleanup_not_verified')
        checks.append('sigkill_vector_fixture_recovered_from_private_journal')
        try:
            await parent.recover_run(config, run_id, neon=True)
        except RecoveryRefused as error:
            if error.reason != 'unsafe_path':
                raise
        else:
            raise RuntimeError('missing_journal_replay_accepted')
        checks.append('completed_journal_replay_refused_without_database_action')
        run_id = None
    finally:
        if process.returncode is None:
            process.kill()
            async with asyncio.timeout(10):
                await process.communicate()
        if run_id is not None:
            # Retains a failed journal; this never sweeps by a name prefix.
            await parent.recover_run(config, run_id, neon=True)

    async def reject_changed_catalog(journal, admin):
        from psycopg import sql
        manifest = journal.manifest
        canary = manifest.role + '_outside'
        routine = manifest.role + '_delete_function'
        trigger = manifest.role + '_delete_trigger'
        for case in ('collection_fk', 'leaf_fk', 'optional_vector_trigger'):
            guard = transport.PostgresTransport(admin, sql, target)
            try:
                async with admin.transaction(force_rollback=True):
                    if case == 'collection_fk':
                        await admin.execute(sql.SQL('CREATE TABLE cragkit.{} (tenant_id cragkit.identity_text, '
                            'collection_id cragkit.collection_text, FOREIGN KEY(tenant_id,collection_id) '
                            'REFERENCES cragkit.collections(tenant_id,collection_id) ON DELETE SET NULL)').format(sql.Identifier(canary)))
                    elif case == 'leaf_fk':
                        await admin.execute(sql.SQL('CREATE TABLE cragkit.{} (tenant_id cragkit.identity_text, '
                            'collection_id cragkit.collection_text,document_id cragkit.identity_text,grant_id cragkit.identity_text, '
                            'FOREIGN KEY(tenant_id,collection_id,document_id,grant_id) '
                            'REFERENCES cragkit.document_grants(tenant_id,collection_id,document_id,grant_id) '
                            'ON DELETE CASCADE)').format(sql.Identifier(canary)))
                    else:
                        await admin.execute(sql.SQL('CREATE TABLE cragkit.{} (marker integer)').format(sql.Identifier(canary)))
                        body = sql.SQL('BEGIN DELETE FROM cragkit.{}; RETURN OLD; END').format(sql.Identifier(canary)).as_string(admin)
                        await admin.execute(sql.SQL('CREATE FUNCTION cragkit.{}() RETURNS trigger LANGUAGE plpgsql AS {}').format(
                            sql.Identifier(routine), sql.Literal(body)))
                        await admin.execute(sql.SQL('CREATE TRIGGER {} BEFORE DELETE ON cragkit.chunk_vectors_fake_1536 '
                            'FOR EACH ROW EXECUTE FUNCTION cragkit.{}()').format(sql.Identifier(trigger), sql.Identifier(routine)))
                    await admin.execute(sql.SQL('INSERT INTO cragkit.{} DEFAULT VALUES').format(sql.Identifier(canary)))
                    before = await guard._inventory(manifest)
                    try:
                        await guard.clean(manifest, deadline=asyncio.get_running_loop().time() + 15)
                    except RecoveryRefused as error:
                        if error.reason != 'schema_mismatch':
                            raise
                    else:
                        raise RuntimeError('unsafe_delete_graph_accepted')
                    cursor = await admin.execute('SELECT rolcanlogin FROM pg_roles WHERE rolname=%s', (manifest.role,))
                    if await cursor.fetchall() != [(True,)]:
                        raise RuntimeError('refused_cleanup_mutated_role')
                    cursor = await admin.execute(sql.SQL('SELECT count(*) FROM cragkit.{}').format(sql.Identifier(canary)))
                    if await cursor.fetchall() != [(1,)] or await guard._inventory(manifest) != before:
                        raise RuntimeError('refused_cleanup_mutated_rows')
                    journal.validate()
                checks.append(case + '_refused_before_mutation_with_canary_preserved')
            finally:
                if guard._locked:
                    # clean() acquired one extra count on this same session's
                    # already held lock. Remove exactly that count after rollback.
                    await admin.execute('SELECT pg_advisory_unlock(1129464148,1)')
        raise parent.RuntimeCheckError('catalog_refusal_complete')

    try:
        await parent.check(config, neon=True, _test_hook=reject_changed_catalog)
    except parent.RuntimeCheckError as error:
        if str(error) != 'catalog_refusal_complete':
            raise
    else:
        raise RuntimeError('catalog_probe_primary_lost')

    original_connect = transport.connect_transport
    for mode in ('closed_admin', 'transient_connect', 'broken_recovery', 'unavailable_connect'):
        saved = {}
        calls = 0
        async def connect(settings, deadline):
            nonlocal calls
            calls += 1
            if mode == 'unavailable_connect' or (mode == 'transient_connect' and calls == 1):
                raise ConnectionError('synthetic private failure; never copied into diagnostics')
            handle = await original_connect(settings, deadline)
            if mode == 'broken_recovery' and calls == 1:
                await handle.connection.close()
            if mode == 'closed_admin':
                class RepeatClean:
                    @property
                    def operation(self): return handle.operation
                    async def clean(self, manifest, *, deadline):
                        await handle.clean(manifest, deadline=deadline)
                        await handle.clean(manifest, deadline=deadline)
                    async def close(self): await handle.close()
                return RepeatClean()
            return handle
        async def fault(journal, admin):
            saved['journal'] = journal
            await admin.close()
            raise parent.RuntimeCheckError('synthetic_primary_failure')
        transport.connect_transport = connect
        try:
            try:
                await parent.check(config, neon=True, hybrid=True, _test_hook=fault)
            except parent.RuntimeCheckError as error:
                if mode == 'unavailable_connect' or str(error) != 'synthetic_primary_failure':
                    raise
            except CleanupFailure as error:
                if mode != 'unavailable_connect' or error.to_dict()['primary'] is None:
                    raise
                saved['journal'].validate()
            else:
                raise RuntimeError('primary_failure_lost')
            expected = 2 if mode != 'closed_admin' else 1
            if calls != expected:
                raise RuntimeError('recovery_attempt_count')
        finally:
            transport.connect_transport = original_connect
            if mode == 'unavailable_connect' and saved:
                await parent.recover_run(config, saved['journal'].manifest.run_id, neon=True)
        try:
            saved['journal'].validate()
        except RecoveryRefused:
            pass
        else:
            raise RuntimeError('verified_journal_not_removed')
        checks.append(mode + '_bounded_recovery_and_primary_preservation')
    if await snapshot() != baseline:
        raise RuntimeError('unrelated_inventory_or_history_changed')
    checks.append('preexisting_roles_memberships_profiles_and_histories_unchanged')
    return {'state': 'passed', 'checks': checks, 'cleanup_verified': True,
            'maximum_connections': 2, 'live_model_calls': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--allow-test-writes', action='store_true', required=True)
    parser.add_argument('--confirm-dedicated-target', action='store_true', required=True)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        async def bounded():
            async with asyncio.timeout(420):
                return await (worker(args.config) if args.worker else check(args.config))
        result = asyncio.run(bounded())
    except CleanupFailure as error:
        print(json.dumps({'state': 'failed', **error.to_dict(),
                          'recovery_required': True,
                          'recovery_id': getattr(error, 'recovery_id', None)}, sort_keys=True))
        return 1
    except BaseException:
        print(json.dumps({'state': 'failed', 'code': 'recovery_acceptance_failed'}))
        return 1
    if result is not None:
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
