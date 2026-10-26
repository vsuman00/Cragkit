"""Explicit E2b native recovery acceptance, using only disposable local servers."""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import signal
import tempfile

from check_qdrant_writer import read_bounded
from qdrant_authority_schema import ROOT
from qdrant_native import REFERENCE_BINARY_SHA256
from qdrant_publication_native import PublicationDatabase, LOGIN_ROLES
from qdrant_recovery_cases import CHECKS, ERRORS, NativeRecoveryFailure, recovery_input
from qdrant_source_native import PostgresSourceFixture
from runtime_diagnostics import CleanupFailure, describe_error

CLEANUP = frozenset(('transport_close', 'verifier_close', 'writer_close', 'recovery_close',
    'resource_close', 'supervisor_resource_close', 'supervisor_pool_close', 'controller_close', 'listener_close'))


def failure_observation(value):
    if (type(value) is not dict or value.get('ok') is not False or type(value.get('step')) is not int
            or not 0 <= value['step'] <= len(CHECKS) or type(value.get('error')) is not str):
        raise RuntimeError('recovery_native_failure_shape')
    if value['error'] in ERRORS:
        if set(value) != {'ok', 'step', 'error'}:
            raise RuntimeError('recovery_native_failure_shape')
    elif value['error'] == 'cleanup_failed':
        if (set(value) != {'ok', 'step', 'error', 'primary', 'cleanup'}
                or value['primary'] is not None and (type(value['primary']) is not str or value['primary'] not in ERRORS)
                or type(value['cleanup']) is not list or not 1 <= len(value['cleanup']) <= 10):
            raise RuntimeError('recovery_native_failure_shape')
        for record in value['cleanup']:
            if (type(record) is not dict or set(record) != {'operation', 'outcome'}
                    or type(record['operation']) is not str or record['operation'] not in CLEANUP
                    or type(record['outcome']) is not str or record['outcome'] not in ERRORS):
                raise RuntimeError('recovery_native_failure_shape')
    else:
        raise RuntimeError('recovery_native_failure_shape')
    return json.loads(json.dumps(value))


def validate_result(value, runtime):
    if (type(value) is not dict or set(value) != {'runtime', 'checks', 'proof_scope'}
            or value['runtime'] != runtime or value['checks'] != list(CHECKS)
            or value['proof_scope'] != 'durable_recovery_settlement_only'):
        raise RuntimeError('recovery_native_result_shape')
    return value


async def node_process(script, payload=None, *, limit=65536, timeout=120):
    environment = {key: value for key, value in os.environ.items() if not key.startswith(('PG', 'QDRANT__'))
        and key not in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NODE_OPTIONS', 'NODE_USE_ENV_PROXY', 'RUST_LOG')}
    process = await asyncio.create_subprocess_exec('node', *script, cwd=ROOT,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=environment, start_new_session=True, limit=65536)
    output = asyncio.create_task(read_bounded(process.stdout, limit))
    errors = asyncio.create_task(read_bounded(process.stderr, limit))
    success = False
    primary = None
    try:
        async with asyncio.timeout(timeout):
            if payload is not None:
                process.stdin.write(json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode())
                await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()
            stdout, stderr = await asyncio.gather(output, errors)
            code = await process.wait()
        if stderr:
            raise RuntimeError('recovery_native_child_failed')
        value = json.loads(stdout)
        if code != 0:
            raise NativeRecoveryFailure(failure_observation(value))
        success = True
        return value
    except BaseException as error:
        primary = error
        raise
    finally:
        failures = []
        try:
            if process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except TimeoutError:
                    os.killpg(process.pid, signal.SIGKILL)
                    await asyncio.wait_for(process.wait(), 2)
            if not success:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        except BaseException as error:
            failures.append(('child_stop', error))
        finally:
            for task in (output, errors):
                if not task.done(): task.cancel()
            await asyncio.gather(output, errors, return_exceptions=True)
        if failures:
            raise CleanupFailure(failures, primary=primary, stage='recovery') from None


async def role_checks(database):
    from psycopg import sql
    from cragkit._qdrant_recovery import _SUPERVISOR_ROLE_SQL
    script = "import {RECOVERY_ROLE_SQL} from './packages/typescript/dist/qdrant-recovery.js';process.stdout.write(JSON.stringify(RECOVERY_ROLE_SQL));"
    node_query = await node_process(['--input-type=module', '-e', script], timeout=5)
    if type(node_query) is not str or not 1 <= len(node_query) <= 32768:
        raise RuntimeError('recovery_native_role_query_shape')
    queries = (_SUPERVISOR_ROLE_SQL, node_query)
    checks = []
    async with database.connection('supervisor') as connection:
        async def expect(expected):
            for query in queries:
                cursor = await connection.execute(query, prepare=False)
                if await cursor.fetchall() != [(expected,)]:
                    raise RuntimeError('recovery_native_supervisor_predicate')
        async def changed(grant, revoke, label):
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
                    raise CleanupFailure([('privilege_revoke', error)], primary=primary, stage='recovery') from None
            await expect(True)
            checks.append(label)
        await expect(True)
        checks.append('dedicated_supervisor_login_satisfies_both_literal_privilege_predicates')
        for table, column in [('document_revisions', 'canonical_utf8'), ('dispatch_journal', 'request_bytes')]:
            try:
                await connection.execute(sql.SQL('SELECT {} FROM cragkit_qdrant.{} LIMIT 1').format(
                    sql.Identifier(column), sql.Identifier(table)))
            except Exception as error:
                if getattr(error, 'sqlstate', None) != '42501': raise
            else:
                raise RuntimeError('recovery_native_sensitive_column_read_allowed')
        checks.append('supervisor_source_and_journal_body_reads_are_denied_by_actual_sql_privileges')
        login = sql.Identifier(LOGIN_ROLES['supervisor'])
        capability = sql.Identifier('cragkit_qdrant_supervisor')
        await changed(sql.SQL('GRANT SELECT(canonical_utf8) ON cragkit_qdrant.document_revisions TO {}').format(login),
            sql.SQL('REVOKE SELECT(canonical_utf8) ON cragkit_qdrant.document_revisions FROM {}').format(login),
            'extra_login_source_column_privilege_rejected')
        await changed(sql.SQL('GRANT SELECT(request_bytes) ON cragkit_qdrant.dispatch_journal TO {}').format(capability),
            sql.SQL('REVOKE SELECT(request_bytes) ON cragkit_qdrant.dispatch_journal FROM {}').format(capability),
            'extra_fixed_capability_journal_body_privilege_rejected')
        await changed(sql.SQL('ALTER ROLE {} LOGIN').format(capability), sql.SQL('ALTER ROLE {} NOLOGIN').format(capability),
            'fixed_supervisor_capability_login_conversion_rejected')
        await changed(sql.SQL('GRANT cragkit_qdrant_writer TO {} WITH INHERIT FALSE,SET FALSE').format(login),
            sql.SQL('REVOKE cragkit_qdrant_writer FROM {}').format(login),
            'noninherited_writer_membership_rejected')
        await changed(sql.SQL('GRANT EXECUTE ON FUNCTION cragkit_qdrant.guard_backend_instance() TO {}').format(capability),
            sql.SQL('REVOKE EXECUTE ON FUNCTION cragkit_qdrant.guard_backend_instance() FROM {}').format(capability),
            'extra_fixed_capability_helper_execution_rejected')
        await database.admin.execute('CREATE ROLE recovery_fixture_safe_group NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT')
        primary = None
        try:
            await changed('GRANT recovery_fixture_safe_group TO cragkit_qdrant_supervisor WITH INHERIT FALSE,SET FALSE',
                'REVOKE recovery_fixture_safe_group FROM cragkit_qdrant_supervisor',
                'fixed_supervisor_outbound_membership_rejected')
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                await asyncio.wait_for(database.admin.execute('DROP ROLE recovery_fixture_safe_group'), 3)
            except BaseException as error:
                raise CleanupFailure([('role_drop', error)], primary=primary, stage='recovery') from None
    return dict(runtime='sql', checks=checks, proof_scope='least_privilege_predicates_only')


async def check(fixture, runtime, binary, work_dir):
    async with PublicationDatabase(fixture) as database:
        if runtime == 'sql':
            return await role_checks(database)
        value = dict(binary=str(binary), work_dir=str(work_dir), inputs=recovery_input(),
            writer_config=database.config('writer'), supervisor_config=database.config('supervisor'))
        await database.release_admin()
        if runtime == 'python':
            from qdrant_recovery_cases import python_recovery_cases
            result = await python_recovery_cases(value)
        else:
            result = await node_process([str(ROOT / 'tools/check_typescript_qdrant_recovery.mjs')], value)
        return validate_result(result, runtime)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--server-binary', type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    parser.add_argument('--runtime', choices=('sql', 'python', 'typescript', 'all'), default='all')
    parser.add_argument('--allow-local-processes', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        binary = args.server_binary.resolve(strict=True)
        if (args.binary_sha256 != REFERENCE_BINARY_SHA256 or not binary.is_file()
                or not os.access(binary, os.X_OK) or sha256(binary.read_bytes()).hexdigest() != REFERENCE_BINARY_SHA256):
            raise RuntimeError('recovery_native_binary_profile')
        if args.artifacts_dir.exists(): raise RuntimeError('recovery_native_fresh_artifacts_required')
        args.artifacts_dir.mkdir(parents=True, mode=0o700)
        results = []
        for runtime in ('sql', 'python', 'typescript') if args.runtime == 'all' else (args.runtime,):
            private = Path(tempfile.mkdtemp(prefix=runtime + '-', dir=args.artifacts_dir)).resolve()
            with PostgresSourceFixture(args.postgres_bin, private / 'postgres') as fixture:
                result = asyncio.run(asyncio.wait_for(check(fixture, runtime, binary, private / 'managed'), 150))
            shutil.rmtree(private)
            results.append(result)
        (args.artifacts_dir / 'results.json').write_text(json.dumps(dict(
            ok=True, results=results, cleanup_verified=True), indent=2) + '\n')
        print(json.dumps(dict(ok=True, checks=sum(len(r['checks']) for r in results), cleanup_verified=True)))
        return 0
    except Exception as error:
        diagnostic = error.to_dict() if isinstance(error, CleanupFailure) else describe_error(error, operation='primary', stage='recovery')
        print(json.dumps(dict(ok=False, error=diagnostic,
            **({'native': error.observation} if isinstance(error, NativeRecoveryFailure) else {}))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
