"""Opt-in E2a native authority/readback acceptance on disposable local servers."""
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

from check_qdrant_writer import read_bounded
from qdrant_authority_schema import ROOT
from qdrant_native import REFERENCE_BINARY_SHA256
from qdrant_publication_native import PublicationDatabase
from qdrant_reconciliation_cases import CHECKS, ERRORS, ReconciliationCaseFailure, python_reconciliation_cases
from qdrant_source_native import PostgresSourceFixture
from qdrant_supervisor_cases import supervisor_input
from qdrant_writer_cases import writer_input
from runtime_diagnostics import CleanupFailure, describe_error


def reconciliation_input():
    from copy import deepcopy
    from cragkit._qdrant_contract import point_id
    from cragkit._qdrant_manifest import encode_manifest
    value = writer_input()
    value['collection_config'] = supervisor_input()['collection_config']
    changed = deepcopy(value['stage'])
    manifest = changed['manifest']
    for member in manifest['members']:
        member['chunk_id'] += '-different'
        member['point_id'] = point_id(['cragkit.qdrant.point.v1', manifest['backend_namespace'],
            manifest['physical_collection'], manifest['collection_incarnation'], manifest['tenant_id'],
            manifest['collection'], manifest['document_id'], manifest['revision_id'], manifest['generation_id'],
            member['chunk_id'], manifest['dense_profile']['profile_id'], manifest['sparse_profile']['profile_id']])
    changed['intent'].update(intent_id='e2a-conflicting-generation', initial_authorization=None,
        manifest_sha256=encode_manifest(manifest, changed['canonical_text']).sha256)
    value['conflicting_stage'] = changed
    return value


def validate_result(value, runtime):
    if (type(value) is not dict or set(value) != {'runtime', 'checks', 'proof_scope', 'normalized_witness_sha256'}
            or value['runtime'] != runtime or value['checks'] != list(CHECKS)
            or type(value['normalized_witness_sha256']) is not str
            or re.fullmatch('[0-9a-f]{64}', value['normalized_witness_sha256']) is None
            or value['proof_scope'] != 'authority_bound_readback_only'):
        raise RuntimeError('reconciliation_native_result_shape')
    return value


def failure_observation(value):
    if (type(value) is not dict or value.get('ok') is not False or type(value.get('step')) is not int
            or not 0 <= value['step'] <= len(CHECKS) or type(value.get('error')) is not str):
        raise RuntimeError('reconciliation_native_failure_shape')
    if value['error'] in ERRORS:
        if set(value) != {'ok', 'step', 'error'}:
            raise RuntimeError('reconciliation_native_failure_shape')
    elif value['error'] == 'cleanup_failed':
        if (set(value) != {'ok', 'step', 'error', 'primary', 'cleanup'}
                or value['primary'] is not None and (type(value['primary']) is not str or value['primary'] not in ERRORS)
                or type(value['cleanup']) is not list or not 1 <= len(value['cleanup']) <= 6):
            raise RuntimeError('reconciliation_native_failure_shape')
        for record in value['cleanup']:
            if (type(record) is not dict or set(record) != {'operation', 'outcome'}
                    or type(record['operation']) is not str or record['operation'] not in ('transport_close', 'writer_close', 'resource_close',
                        'supervisor_connection_close', 'controller_close', 'listener_close')
                    or type(record['outcome']) is not str or record['outcome'] not in ERRORS):
                raise RuntimeError('reconciliation_native_failure_shape')
    else:
        raise RuntimeError('reconciliation_native_failure_shape')
    return json.loads(json.dumps(value))


async def node_reconciliation_cases(value):
    environment = {key: val for key, val in os.environ.items() if not key.startswith(('PG', 'QDRANT__'))
        and key not in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NODE_OPTIONS', 'NODE_USE_ENV_PROXY', 'RUST_LOG')}
    process = await asyncio.create_subprocess_exec('node', str(ROOT / 'tools/check_typescript_qdrant_reconciliation.mjs'),
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
            observation = failure_observation(json.loads(stdout))
            failure = ReconciliationCaseFailure(observation['step'], RuntimeError())
            failure.observation = observation
            raise failure
        if code != 0 or stderr:
            raise RuntimeError('reconciliation_native_child_failed')
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


async def check(fixture, runtime, binary, work_dir):
    async with PublicationDatabase(fixture) as database:
        value = dict(binary=str(binary), work_dir=str(work_dir), inputs=reconciliation_input(),
            writer_config=database.config('writer'), supervisor_config=database.config('supervisor'))
        await database.release_admin()
        runner = python_reconciliation_cases if runtime == 'python' else node_reconciliation_cases
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
            raise RuntimeError('reconciliation_native_binary_profile')
        if args.artifacts_dir.exists():
            raise RuntimeError('reconciliation_native_fresh_artifacts_required')
        args.artifacts_dir.mkdir(parents=True, mode=0o700)
        results = []
        for runtime in ('python', 'typescript') if args.runtime == 'all' else (args.runtime,):
            private = Path(tempfile.mkdtemp(prefix=runtime + '-', dir=args.artifacts_dir)).resolve()
            with PostgresSourceFixture(args.postgres_bin, private / 'postgres') as fixture:
                result = asyncio.run(asyncio.wait_for(check(fixture, runtime, binary, private / 'managed'), 120))
            shutil.rmtree(private)
            results.append(result)
        if len(results) == 2:
            matched = results[0]['normalized_witness_sha256'] == results[1]['normalized_witness_sha256']
            (args.artifacts_dir / 'witness-comparison.json').write_text(json.dumps(dict(
                matched=matched, normalized_physical_nonce_positions=[2, 3, 7],
                hashes={result['runtime']: result['normalized_witness_sha256'] for result in results}), indent=2) + '\n')
            if not matched:
                raise RuntimeError('reconciliation_native_witness_parity')
        (args.artifacts_dir / 'results.json').write_text(json.dumps(
            dict(ok=True, results=results, cleanup_verified=True), indent=2) + '\n')
        print(json.dumps(dict(ok=True, checks=sum(len(r['checks']) for r in results), cleanup_verified=True)))
        return 0
    except Exception as error:
        diagnostic = error.to_dict() if isinstance(error, CleanupFailure) else describe_error(error, operation='primary', stage='recovery')
        print(json.dumps(dict(ok=False, error=diagnostic,
            **({'native': error.observation} if isinstance(error, ReconciliationCaseFailure) else {}))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
