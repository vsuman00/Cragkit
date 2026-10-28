"""Opt-in native managed repair acceptance on disposable local servers."""
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
from qdrant_publication_native import PublicationDatabase
from qdrant_repair_cases import (CHECKS, ERRORS, NativeRepairFailure,
    python_repair_cases, repair_input)
from qdrant_source_native import PostgresSourceFixture
from runtime_diagnostics import CleanupFailure, describe_error


def validate_result(value, runtime):
    if (type(value) is not dict or set(value) != {'runtime', 'checks', 'proof_scope'}
            or value['runtime'] != runtime or value['checks'] != list(CHECKS)
            or value['proof_scope'] != 'native_managed_repair_g1a_only'):
        raise RuntimeError('repair_native_result_shape')
    return value


def failure_observation(value):
    if (type(value) is not dict or value.get('ok') is not False or type(value.get('step')) is not int
            or not 0 <= value['step'] <= len(CHECKS) or type(value.get('error')) is not str):
        raise RuntimeError('repair_native_failure_shape')
    if value['error'] in ERRORS:
        if set(value) != {'ok', 'step', 'error'}:
            raise RuntimeError('repair_native_failure_shape')
    elif value['error'] == 'cleanup_failed':
        if (set(value) != {'ok', 'step', 'error', 'primary', 'cleanup'}
                or value['primary'] is not None and (type(value['primary']) is not str or value['primary'] not in ERRORS)
                or type(value['cleanup']) is not list or not 1 <= len(value['cleanup']) <= 64):
            raise RuntimeError('repair_native_failure_shape')
        for record in value['cleanup']:
            if (type(record) is not dict or set(record) != {'operation', 'outcome'}
                    or type(record['operation']) is not str or record['operation'] not in ('manager_close', 'transport_close', 'writer_close', 'recovery_close', 'resource_close',
                        'supervisor_resource_close', 'controller_close', 'listener_close', 'verifier_close',
                        'host_close', 'worker_drain', 'worker_terminate', 'publish_drain',
                        'wrong_verifier_close', 'reconciliation_close', 'wrong_writer_close')
                    or type(record['outcome']) is not str or record['outcome'] not in ERRORS):
                raise RuntimeError('repair_native_failure_shape')
    else:
        raise RuntimeError('repair_native_failure_shape')
    return json.loads(json.dumps(value))


async def node_repair_cases(value):
    environment = {key: val for key, val in os.environ.items() if not key.startswith(('PG', 'QDRANT__'))
        and key not in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NODE_OPTIONS', 'NODE_USE_ENV_PROXY', 'RUST_LOG')}
    process = await asyncio.create_subprocess_exec('node', str(ROOT / 'tools/check_typescript_qdrant_repair.mjs'),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=environment, start_new_session=True, limit=65536)
    output = asyncio.create_task(read_bounded(process.stdout, 65536))
    errors = asyncio.create_task(read_bounded(process.stderr, 65536))
    primary = None
    success = False
    try:
        # Allow the150s business deadline and separate cleanup to finish.
        async with asyncio.timeout(170):
            process.stdin.write(json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode())
            await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()
            stdout, stderr = await asyncio.gather(output, errors)
            code = await process.wait()
        if code != 0 and not stderr:
            observation = failure_observation(json.loads(stdout))
            failure = NativeRepairFailure(observation)
            raise failure
        if code != 0 or stderr:
            raise RuntimeError('repair_native_child_failed')
        result = validate_result(json.loads(stdout), 'typescript')
        success = True
        return result
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


async def native_role_checks(database):
    from cragkit._qdrant_writer import _WRITER_ATTESTATION_ROLE_SQL
    from qdrant_publication_native import writer_role_checks, LOGIN_ROLES
    from psycopg import sql
    environment = {key: value for key,value in os.environ.items()
        if key not in ('NODE_OPTIONS','NODE_USE_ENV_PROXY') and not key.startswith('PG')}
    process = await asyncio.create_subprocess_exec('node', '--input-type=module', '-e',
        "import {WRITER_ATTESTATION_ROLE_SQL} from './packages/typescript/dist/qdrant-writer.js';"
        "process.stdout.write(JSON.stringify(WRITER_ATTESTATION_ROLE_SQL));",
        cwd=ROOT,env=environment,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        output,errors=await asyncio.wait_for(process.communicate(),10)
        if process.returncode or errors or len(output)>65536:
            raise RuntimeError('attestation_role_query_export')
        node_query=json.loads(output)
        if type(node_query) is not str or not 1<len(node_query)<65536:
            raise RuntimeError('attestation_role_query_export')
    finally:
        if process.returncode is None:
            process.kill()
            await asyncio.wait_for(process.wait(),3)
    queries=(_WRITER_ATTESTATION_ROLE_SQL,node_query)
    checks=await writer_role_checks(database,queries)
    async with database.connection('writer') as connection:
        for role in (LOGIN_ROLES['writer'],'cragkit_qdrant_writer'):
            identifier=sql.Identifier(role)
            await database.admin.execute(sql.SQL('GRANT UPDATE(readback_sha256) ON cragkit_qdrant.preparation_attestations TO {}').format(identifier))
            try:
                for query in queries:
                    cursor=await connection.execute(query,prepare=False)
                    if await cursor.fetchall()!=[(False,)]:
                        raise RuntimeError('attestation_extra_grant_not_rejected')
            finally:
                await database.admin.execute(sql.SQL('REVOKE UPDATE(readback_sha256) ON cragkit_qdrant.preparation_attestations FROM {}').format(identifier))
            for query in queries:
                cursor=await connection.execute(query,prepare=False)
                if await cursor.fetchall()!=[(True,)]:
                    raise RuntimeError('attestation_grants_not_restored')
            checks.append('native_attestation_predicates_reject_'+role+'_update')
    return checks


async def check(fixture, runtime, binary, work_dir):
    async with PublicationDatabase(fixture, with_attestations=True) as database:
        cursor = await database.admin.execute("SELECT current_setting('max_connections')::int,"
            "current_setting('superuser_reserved_connections')::int,"
            "current_setting('reserved_connections')::int")
        maximum, superuser, reserved = (await cursor.fetchall())[0]
        if maximum - superuser - reserved < 2:
            raise RuntimeError('repair_native_two_runtime_slots_required')
        (work_dir.parent.parent / (runtime + '-postgres-limits.json')).write_text(json.dumps(dict(
            max_connections=maximum, superuser_reserved_connections=superuser,
            reserved_connections=reserved, runtime_client_ceiling=2), indent=2) + '\n')
        role_checks=await native_role_checks(database)
        (work_dir.parent.parent / (runtime+'-role-checks.json')).write_text(json.dumps(role_checks,indent=2)+'\n')
        value = dict(binary=str(binary), work_dir=str(work_dir), inputs=repair_input(),
            writer_config=database.config('writer'), supervisor_config=database.config('supervisor'))
        await database.release_admin()
        runner = python_repair_cases if runtime == 'python' else node_repair_cases
        return validate_result(await runner(value), runtime)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--server-binary', type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    parser.add_argument('--runtime', choices=('python', 'typescript', 'all'), default='all')
    parser.add_argument('--allow-local-processes', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        binary = args.server_binary.resolve(strict=True)
        if (args.binary_sha256 != REFERENCE_BINARY_SHA256 or not binary.is_file()
                or not os.access(binary, os.X_OK) or sha256(binary.read_bytes()).hexdigest() != REFERENCE_BINARY_SHA256):
            raise RuntimeError('repair_native_binary_profile')
        if args.artifacts_dir.exists():
            raise RuntimeError('repair_native_fresh_artifacts_required')
        args.artifacts_dir.mkdir(parents=True, mode=0o700)
        results = []
        for runtime in ('python', 'typescript') if args.runtime == 'all' else (args.runtime,):
            private = Path(tempfile.mkdtemp(prefix=runtime + '-', dir=args.artifacts_dir)).resolve()
            # Two runtime clients and the default three reserved slots.
            with PostgresSourceFixture(args.postgres_bin, private / 'postgres', max_connections=5) as fixture:
                result = asyncio.run(asyncio.wait_for(check(fixture, runtime, binary, private / 'managed'), 180))
            shutil.rmtree(private)
            results.append(result)
        (args.artifacts_dir / 'results.json').write_text(json.dumps(
            dict(ok=True, results=results, cleanup_verified=True), indent=2) + '\n')
        print(json.dumps(dict(ok=True, checks=sum(len(r['checks']) for r in results), cleanup_verified=True)))
        return 0
    except Exception as error:
        diagnostic = error.to_dict() if isinstance(error, CleanupFailure) else describe_error(error, operation='primary', stage='recovery')
        print(json.dumps(dict(ok=False, error=diagnostic,
            **({'native': error.observation} if isinstance(error, NativeRepairFailure) else {}))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
