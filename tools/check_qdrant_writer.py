"""Opt-in native publication-authority acceptance on disposable PostgreSQL only."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from qdrant_authority_schema import ROOT
from qdrant_publication_native import PublicationDatabase, bind_scope, committed_boundary_checks, writer_role_checks
from qdrant_publication_schema import insert_sql, seed_records
from qdrant_source_native import PostgresSourceFixture
from qdrant_writer_cases import python_writer_cases, writer_input, successor_stage
from runtime_diagnostics import CleanupFailure, describe_error

ERROR_NAMES = frozenset(('IntegrityViolation', 'UnauthorizedScope', 'IndexNotReady',
    'InvalidRequest', 'ProviderUnavailable', 'UnsupportedCapability', 'DeadlineExceeded', 'internal'))
PHASES = frozenset(('input', 'initialize', 'stage', 'dispatch', 'publish', 'security', 'publication_interleaving'))


class NodeWriterFailure(RuntimeError):
    def __init__(self, observation):
        super().__init__('writer_node_case_failed')
        self.observation = observation


def failure_observation(value):
    """Accept only content-free child failure labels, including combined cleanup."""
    if (type(value) is not dict or value.get('ok') is not False
            or type(value.get('phase')) is not str or value['phase'] not in PHASES
            or type(value.get('error')) is not str
            or value['error'] not in ERROR_NAMES | {'cleanup_failed'}):
        raise RuntimeError('writer_node_failure_shape')
    if value['error'] != 'cleanup_failed':
        if set(value) != {'ok', 'phase', 'error'}:
            raise RuntimeError('writer_node_failure_shape')
    else:
        if (set(value) != {'ok', 'phase', 'error', 'primary', 'cleanup'}
                or value['primary'] is not None and (type(value['primary']) is not str or value['primary'] not in ERROR_NAMES)
                or type(value['cleanup']) is not list or not 1 <= len(value['cleanup']) <= 4):
            raise RuntimeError('writer_node_failure_shape')
        for item in value['cleanup']:
            if (type(item) is not dict or set(item) != {'operation', 'outcome'}
                    or type(item['operation']) is not str or item['operation'] not in ('writer_close', 'resource_close')
                    or type(item['outcome']) is not str or item['outcome'] not in ERROR_NAMES):
                raise RuntimeError('writer_node_failure_shape')
    return json.loads(json.dumps(value))


async def read_bounded(stream, limit=65536):
    """Read through EOF; a short pipe read is never a complete child response."""
    chunks = []
    size = 0
    while chunk := await stream.read(min(16384, limit + 1 - size)):
        size += len(chunk)
        if size > limit:
            raise RuntimeError('writer_child_output_exceeded')
        chunks.append(chunk)
    return b''.join(chunks)


async def node_writer_role_query():
    """Read the built native SQL constant without credentials or a database client."""
    script = ("import {WRITER_ROLE_SQL} from './packages/typescript/dist/qdrant-writer.js';"
              "process.stdout.write(JSON.stringify(WRITER_ROLE_SQL));")
    environment = {key: value for key, value in os.environ.items() if key != 'NODE_OPTIONS'}
    process = await asyncio.create_subprocess_exec('node', '--input-type=module', '-e', script,
        cwd=ROOT, env=environment, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    output = asyncio.create_task(read_bounded(process.stdout, 32768))
    errors = asyncio.create_task(read_bounded(process.stderr, 32768))
    primary = None
    try:
        async with asyncio.timeout(5):
            stdout, stderr = await asyncio.gather(output, errors)
            code = await process.wait()
        if code != 0 or stderr:
            raise RuntimeError('writer_node_role_constant')
        value = json.loads(stdout)
        if type(value) is not str or not 1 <= len(value) <= 32768:
            raise RuntimeError('writer_node_role_constant')
        return value
    except BaseException as error:
        primary = error
        raise
    finally:
        failure = None
        try:
            if process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), 2)
                except TimeoutError:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    await asyncio.wait_for(process.wait(), 2)
        except BaseException as error:
            failure = error
        finally:
            for task in (output, errors):
                if not task.done(): task.cancel()
            await asyncio.gather(output, errors, return_exceptions=True)
        if failure is not None:
            raise CleanupFailure([('child_stop', failure)], primary=primary, stage='typescript_runtime') from None


async def node_writer_cases(config, inputs):
    """Pass private connection paths over stdin, with bounded output and teardown."""
    environment = {key: value for key, value in os.environ.items()
        if not key.startswith('PG') and key not in
        ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NODE_USE_ENV_PROXY', 'NODE_OPTIONS')}
    process = await asyncio.create_subprocess_exec('node', str(ROOT / 'tools/check_typescript_qdrant_writer.mjs'),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=environment, limit=65536)
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    output = asyncio.create_task(read_bounded(process.stdout))
    errors = asyncio.create_task(read_bounded(process.stderr))
    primary = None
    try:
        async with asyncio.timeout(90):
            process.stdin.write(json.dumps(dict(config=config, inputs=inputs), separators=(',', ':')).encode())
            await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()
            stdout, stderr = await asyncio.gather(output, errors)
            status = await process.wait()
        if not stderr and status != 0:
            try:
                observed = failure_observation(json.loads(stdout))
            except (ValueError, RuntimeError):
                raise RuntimeError('writer_node_failed_or_output_exceeded') from None
            raise NodeWriterFailure(observed)
        if status != 0 or stderr or len(stdout) > 65536:
            raise RuntimeError('writer_node_failed_or_output_exceeded')
        result = json.loads(stdout)
        if (type(result) is not dict or set(result) != {'runtime', 'checks', 'publication_proof'}
                or result['runtime'] != 'typescript' or type(result['checks']) is not list
                or not 1 <= len(result['checks']) <= 64
                or any(type(check) is not str or not check or len(check) > 128
                    or any(char not in 'abcdefghijklmnopqrstuvwxyz_0123456789' for char in check)
                    for check in result['checks'])
                or result['publication_proof'] != 'authority_transactions_only'):
            raise RuntimeError('writer_node_result_shape')
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
                    await asyncio.wait_for(process.wait(), 2)
                except TimeoutError:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    await asyncio.wait_for(process.wait(), 2)
        except BaseException as error:
            failures.append(('child_stop', error))
        finally:
            for task in (output, errors):
                if not task.done():
                    task.cancel()
            try:
                await asyncio.gather(output, errors, return_exceptions=True)
            except BaseException as error:
                failures.append(('child_stop', error))
        if failures:
            raise CleanupFailure(failures, primary=primary, stage='typescript_runtime') from None


async def check(fixture, runtime):
    async with PublicationDatabase(fixture) as database:
        if runtime == 'sql':
            from cragkit._qdrant_writer import _WRITER_ROLE_SQL
            checks = await writer_role_checks(database, (_WRITER_ROLE_SQL, await node_writer_role_query()))
            result = dict(runtime='sql', checks=checks + await committed_boundary_checks(database),
                publication_proof='schema_committed_boundaries_only')
        else:
            records = seed_records()
            async with database.connection('supervisor') as connection:
                async with connection.transaction():
                    await bind_scope(connection, records)
                    await connection.execute(insert_sql('backend_instances', records['backend']))
            inputs = writer_input()
            inputs['successors'] = {
                suffix: successor_stage(inputs, suffix, active)
                for suffix, active in (('race-a', inputs['stage']['manifest']['generation_id']),
                    ('race-b', inputs['stage']['manifest']['generation_id']), ('denied', 'gen-race-b'),
                    ('manager-conflict', inputs['stage']['manifest']['generation_id']),
                    ('manager-denied', 'gen-race-b'))}
            runtime_config = database.config('writer')
            # Each runtime exercises two independent writer clients. Setup is
            # complete, so no administrative client remains in that window.
            await database.release_admin()
            if runtime == 'python':
                result = await python_writer_cases(runtime_config, inputs)
            else:
                result = await node_writer_cases(runtime_config, inputs)
        result['fixture_checks'] = list(database.checks)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    parser.add_argument('--runtime', choices=('sql', 'python', 'typescript', 'all'), default='all')
    parser.add_argument('--allow-local-processes', action='store_true', required=True)
    args = parser.parse_args(argv)
    result_path = args.artifacts_dir / 'results.json'
    try:
        if args.artifacts_dir.exists():
            raise RuntimeError('writer_fresh_artifacts_required')
        args.artifacts_dir.mkdir(parents=True, mode=0o700)
        results = []
        for runtime in ('sql', 'python', 'typescript') if args.runtime == 'all' else (args.runtime,):
            fixture = PostgresSourceFixture(args.postgres_bin, args.artifacts_dir / runtime)
            with fixture:
                result = asyncio.run(asyncio.wait_for(check(fixture, runtime), 120))
            result['process_checks'] = fixture.checks
            results.append(result)
        result_path.write_text(json.dumps(dict(ok=True, results=results, cleanup_verified=True), indent=2) + '\n')
        print(json.dumps(dict(ok=True, runtimes=[result['runtime'] for result in results],
            checks=sum(len(result['checks']) for result in results), cleanup_verified=True)))
        return 0
    except Exception as error:
        diagnostic = error.to_dict() if isinstance(error, CleanupFailure) else describe_error(
            error, operation='primary', stage='fixture_setup')
        # Failed runs retain no source, key, connection string or SQL message.
        print(json.dumps(dict(ok=False, error=diagnostic,
            **({'native': error.observation} if isinstance(error, NodeWriterFailure) else {}))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
