"""Opt-in public stage/publish acceptance on disposable local servers."""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import os
import re
from pathlib import Path
import shutil
import signal
import tempfile
import traceback

from check_qdrant_writer import read_bounded
from qdrant_authority_schema import ROOT
from qdrant_native import REFERENCE_BINARY_SHA256
from qdrant_publication_native import PublicationDatabase
from qdrant_publication_manager_cases import (CHECKS, ERRORS, NativePublicationManagerFailure,
    python_publication_manager_cases, publication_manager_input)
from qdrant_source_native import PostgresSourceFixture
from runtime_diagnostics import CleanupFailure, describe_error

CORRUPTION_CHECKS = {
    'wrong-dense': ('wrong_dense_vector_public_publish_rejected',),
    'wrong-sparse': ('wrong_sparse_vector_public_publish_rejected',),
    'wrong-profile': ('wrong_full_profile_public_publish_rejected',),
    'missing-sparse': ('missing_sparse_vector_public_publish_rejected',
        'missing_sparse_vector_complete_repair_published'),
    'equal-set': ('equal_count_wrong_set_public_publish_rejected',
        'third_extra_point_scroll_sentinel_rejected'),
    'invalid-input': ('mixed_revision_member_rejected_before_write',
        'malformed_utf8_span_rejected_before_write',
        'unsupported_sparse_encoder_rejected_before_write'),
}


def proof_scope_for(scenario):
    if scenario == 'default':
        return 'public_stage_publish_only'
    if scenario == 'missing-sparse':
        return 'public_corruption_repair_only'
    if scenario == 'equal-set':
        return 'public_wrong_set_only'
    if scenario == 'invalid-input':
        return 'public_invalid_input_only'
    return 'public_corruption_only'


def validate_result(value, runtime, scenario='default'):
    if scenario not in ('default', *CORRUPTION_CHECKS):
        raise RuntimeError('publication_manager_native_scenario')
    checks = CHECKS if scenario == 'default' else CORRUPTION_CHECKS[scenario]
    proof_scope = proof_scope_for(scenario)
    if (type(value) is not dict or set(value) != {'runtime', 'checks', 'proof_scope', 'public_snapshots_sha256'}
            or value['runtime'] != runtime or value['checks'] != list(checks)
            or type(value['public_snapshots_sha256']) is not str
            or re.fullmatch('[0-9a-f]{64}', value['public_snapshots_sha256']) is None
            or value['proof_scope'] != proof_scope):
        raise RuntimeError('publication_manager_native_result_shape')
    return value


def failure_observation(value, scenario='default'):
    if scenario not in ('default', *CORRUPTION_CHECKS):
        raise RuntimeError('publication_manager_native_scenario')
    checks = CHECKS if scenario == 'default' else CORRUPTION_CHECKS[scenario]
    if (type(value) is not dict or value.get('ok') is not False or type(value.get('step')) is not int
            or not 0 <= value['step'] <= len(checks) or type(value.get('error')) is not str):
        raise RuntimeError('publication_manager_native_failure_shape')
    if value['error'] in ERRORS:
        if set(value) != {'ok', 'step', 'error'}:
            raise RuntimeError('publication_manager_native_failure_shape')
    elif value['error'] == 'cleanup_failed':
        if (set(value) != {'ok', 'step', 'error', 'primary', 'cleanup'}
                or value['primary'] is not None and (type(value['primary']) is not str or value['primary'] not in ERRORS)
                or type(value['cleanup']) is not list or not 1 <= len(value['cleanup']) <= 64):
            raise RuntimeError('publication_manager_native_failure_shape')
        for record in value['cleanup']:
            if (type(record) is not dict or set(record) != {'operation', 'outcome'}
                    or type(record['operation']) is not str or record['operation'] not in ('manager_close', 'transport_close', 'writer_close', 'recovery_close', 'resource_close',
                        'supervisor_resource_close', 'controller_close', 'listener_close', 'verifier_close')
                    or type(record['outcome']) is not str or record['outcome'] not in ERRORS):
                raise RuntimeError('publication_manager_native_failure_shape')
    else:
        raise RuntimeError('publication_manager_native_failure_shape')
    return json.loads(json.dumps(value))


async def node_publication_manager_cases(value):
    scenario = value.get('scenario', 'default').replace('_', '-')
    environment = {key: val for key, val in os.environ.items() if not key.startswith(('PG', 'QDRANT__'))
        and key not in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NODE_OPTIONS', 'NODE_USE_ENV_PROXY', 'RUST_LOG')}
    process = await asyncio.create_subprocess_exec('node', str(ROOT / 'tools/check_typescript_qdrant_publication_manager.mjs'),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=environment, start_new_session=True, limit=65536)
    output = asyncio.create_task(read_bounded(process.stdout, 65536))
    errors = asyncio.create_task(read_bounded(process.stderr, 65536))
    primary = None
    success = False
    try:
        async with asyncio.timeout(110):
            process.stdin.write(json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode())
            await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()
            stdout, stderr = await asyncio.gather(output, errors)
            code = await process.wait()
        if code != 0 and not stderr:
            observation = failure_observation(json.loads(stdout), scenario)
            failure = NativePublicationManagerFailure(observation)
            raise failure
        if code != 0 or stderr:
            raise RuntimeError('publication_manager_native_child_failed')
        result = validate_result(json.loads(stdout), 'typescript', scenario)
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


async def check(fixture, runtime, binary, work_dir, scenario='default'):
    async with PublicationDatabase(fixture, with_attestations=scenario == 'missing-sparse') as database:
        value = dict(binary=str(binary), work_dir=str(work_dir), inputs=publication_manager_input(),
            writer_config=database.config('writer'), supervisor_config=database.config('supervisor'),
            observer_config=database.fixture.config)
        if scenario in CORRUPTION_CHECKS:
            value['scenario'] = scenario.replace('-', '_')
        await database.release_admin()
        runner = python_publication_manager_cases if runtime == 'python' else node_publication_manager_cases
        return validate_result(await runner(value), runtime, scenario)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--server-binary', type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    parser.add_argument('--runtime', choices=('python', 'typescript', 'all'), default='all')
    parser.add_argument('--scenario', choices=('default', *CORRUPTION_CHECKS), default='default')
    parser.add_argument('--allow-local-processes', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        binary = args.server_binary.resolve(strict=True)
        if (args.binary_sha256 != REFERENCE_BINARY_SHA256 or not binary.is_file()
                or not os.access(binary, os.X_OK) or sha256(binary.read_bytes()).hexdigest() != REFERENCE_BINARY_SHA256):
            raise RuntimeError('publication_manager_native_binary_profile')
        if args.artifacts_dir.exists():
            raise RuntimeError('publication_manager_native_fresh_artifacts_required')
        args.artifacts_dir.mkdir(parents=True, mode=0o700)
        results = []
        for runtime in ('python', 'typescript') if args.runtime == 'all' else (args.runtime,):
            private = Path(tempfile.mkdtemp(prefix=runtime + '-', dir=args.artifacts_dir)).resolve()
            with PostgresSourceFixture(args.postgres_bin, private / 'postgres') as fixture:
                result = asyncio.run(asyncio.wait_for(check(fixture, runtime, binary,
                    private / 'managed', args.scenario), 120))
            shutil.rmtree(private)
            results.append(result)
        if len(results) == 2:
            matched = results[0]['public_snapshots_sha256'] == results[1]['public_snapshots_sha256']
            (args.artifacts_dir / 'public-snapshots-comparison.json').write_text(json.dumps(dict(
                matched=matched, normalized_fields=[],
                hashes={result['runtime']: result['public_snapshots_sha256'] for result in results}), indent=2) + '\n')
            if not matched:
                raise RuntimeError('publication_manager_native_public_snapshot_parity')
        (args.artifacts_dir / 'results.json').write_text(json.dumps(
            dict(ok=True, results=results, cleanup_verified=True), indent=2) + '\n')
        print(json.dumps(dict(ok=True, checks=sum(len(r['checks']) for r in results), cleanup_verified=True)))
        return 0
    except Exception as error:
        if isinstance(error, NativePublicationManagerFailure) and error.__context__ is not None:
            locations = [{'path': frame.filename.rsplit('/Cragkit/', 1)[-1], 'line': frame.lineno}
                for frame in traceback.extract_tb(error.__context__.__traceback__)
                if '/Cragkit/tools/' in frame.filename or '/Cragkit/packages/' in frame.filename]
            (args.artifacts_dir / 'failure-locations.json').write_text(json.dumps(locations) + '\n')
        diagnostic = error.to_dict() if isinstance(error, CleanupFailure) else describe_error(error, operation='primary', stage='recovery')
        print(json.dumps(dict(ok=False, error=diagnostic,
            **({'native': error.observation} if isinstance(error, NativePublicationManagerFailure) else {}))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
