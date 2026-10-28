"""Opt-in public publication/source acceptance on disposable local servers."""
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
from qdrant_publication_source_cases import (CHECKS, ERRORS, NativePublicationSourceFailure,
    python_publication_source_cases)
from qdrant_writer_cases import writer_input, successor_stage
from qdrant_supervisor_cases import supervisor_input
from qdrant_source_native import PostgresSourceFixture
from runtime_diagnostics import CleanupFailure, describe_error


def publication_source_input():
    """Two immutable generations sharing the same synthetic canonical source."""
    inputs = writer_input()
    inputs['collection_config'] = supervisor_input()['collection_config']
    inputs['successor'] = successor_stage(inputs, 'source-successor',
        inputs['stage']['manifest']['generation_id'])
    inputs['request'] = dict(request_id='publication-source', query='fixture',
        collection=inputs['stage']['manifest']['collection'],
        limits=dict(deadline_ms=60000, max_candidates=8, max_provider_calls=0))
    return inputs


def validate_result(value, runtime):
    if (type(value) is not dict or set(value) != {'runtime', 'checks', 'proof_scope', 'source_observations_sha256'}
            or value['runtime'] != runtime or value['checks'] != list(CHECKS)
            or type(value['source_observations_sha256']) is not str
            or re.fullmatch('[0-9a-f]{64}', value['source_observations_sha256']) is None
            or value['proof_scope'] != 'public_source_publication_only'):
        raise RuntimeError('publication_source_native_result_shape')
    return value


def failure_observation(value):
    if (type(value) is not dict or value.get('ok') is not False or type(value.get('step')) is not int
            or not 0 <= value['step'] <= len(CHECKS) or type(value.get('error')) is not str):
        raise RuntimeError('publication_source_native_failure_shape')
    if value['error'] in ERRORS:
        if set(value) != {'ok', 'step', 'error'}:
            raise RuntimeError('publication_source_native_failure_shape')
    elif value['error'] == 'cleanup_failed':
        if (set(value) != {'ok', 'step', 'error', 'primary', 'cleanup'}
                or value['primary'] is not None and (type(value['primary']) is not str or value['primary'] not in ERRORS)
                or type(value['cleanup']) is not list or not 1 <= len(value['cleanup']) <= 64):
            raise RuntimeError('publication_source_native_failure_shape')
        for record in value['cleanup']:
            if (type(record) is not dict or set(record) != {'operation', 'outcome'}
                    or type(record['operation']) is not str or record['operation'] not in ('manager_close', 'transport_close', 'writer_close', 'recovery_close', 'resource_close',
                        'supervisor_resource_close', 'controller_close', 'listener_close', 'verifier_close',
                        'source_close', 'request_close', 'candidate_close', 'publish_drain', 'reader_pool_close')
                    or type(record['outcome']) is not str or record['outcome'] not in ERRORS):
                raise RuntimeError('publication_source_native_failure_shape')
    else:
        raise RuntimeError('publication_source_native_failure_shape')
    return json.loads(json.dumps(value))


async def node_publication_source_cases(value):
    environment = {key: val for key, val in os.environ.items() if not key.startswith(('PG', 'QDRANT__'))
        and key not in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NODE_OPTIONS', 'NODE_USE_ENV_PROXY', 'RUST_LOG')}
    process = await asyncio.create_subprocess_exec('node', str(ROOT / 'tools/check_typescript_qdrant_publication_source.mjs'),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=environment, start_new_session=True, limit=65536)
    output = asyncio.create_task(read_bounded(process.stdout, 65536))
    errors = asyncio.create_task(read_bounded(process.stderr, 65536))
    primary = None
    success = False
    try:
        # The business deadline is105s; allow its separate12s cleanup to finish.
        async with asyncio.timeout(120):
            process.stdin.write(json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode())
            await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()
            stdout, stderr = await asyncio.gather(output, errors)
            code = await process.wait()
        if code != 0 and not stderr:
            observation = failure_observation(json.loads(stdout))
            failure = NativePublicationSourceFailure(observation)
            raise failure
        if code != 0 or stderr:
            raise RuntimeError('publication_source_native_child_failed')
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


async def check(fixture, runtime, binary, work_dir, *, with_attestations=False):
    async with PublicationDatabase(fixture, with_attestations=with_attestations) as database:
        value = dict(binary=str(binary), work_dir=str(work_dir), inputs=publication_source_input(),
            writer_config=database.config('writer'), supervisor_config=database.config('supervisor'),
            reader_config=database.config('reader'))
        await database.release_admin()
        runner = python_publication_source_cases if runtime == 'python' else node_publication_source_cases
        return validate_result(await runner(value), runtime)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--server-binary', type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    parser.add_argument('--runtime', choices=('python', 'typescript', 'all'), default='all')
    parser.add_argument('--with-attestations', action='store_true')
    parser.add_argument('--allow-local-processes', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        binary = args.server_binary.resolve(strict=True)
        if (args.binary_sha256 != REFERENCE_BINARY_SHA256 or not binary.is_file()
                or not os.access(binary, os.X_OK) or sha256(binary.read_bytes()).hexdigest() != REFERENCE_BINARY_SHA256):
            raise RuntimeError('publication_source_native_binary_profile')
        if args.artifacts_dir.exists():
            raise RuntimeError('publication_source_native_fresh_artifacts_required')
        args.artifacts_dir.mkdir(parents=True, mode=0o700)
        results = []
        for runtime in ('python', 'typescript') if args.runtime == 'all' else (args.runtime,):
            private = Path(tempfile.mkdtemp(prefix=runtime + '-', dir=args.artifacts_dir)).resolve()
            with PostgresSourceFixture(args.postgres_bin, private / 'postgres') as fixture:
                result = asyncio.run(asyncio.wait_for(check(fixture, runtime, binary, private / 'managed', with_attestations=args.with_attestations), 130))
            shutil.rmtree(private)
            results.append(result)
        if len(results) == 2:
            matched = results[0]['source_observations_sha256'] == results[1]['source_observations_sha256']
            (args.artifacts_dir / 'source-observations-comparison.json').write_text(json.dumps(dict(
                matched=matched, normalized_fields=[],
                hashes={result['runtime']: result['source_observations_sha256'] for result in results}), indent=2) + '\n')
            if not matched:
                raise RuntimeError('publication_source_native_source_observation_parity')
        (args.artifacts_dir / 'results.json').write_text(json.dumps(
            dict(ok=True, results=results, cleanup_verified=True), indent=2) + '\n')
        print(json.dumps(dict(ok=True, checks=sum(len(r['checks']) for r in results), cleanup_verified=True)))
        return 0
    except Exception as error:
        diagnostic = error.to_dict() if isinstance(error, CleanupFailure) else describe_error(error, operation='primary', stage='recovery')
        print(json.dumps(dict(ok=False, error=diagnostic,
            **({'native': error.observation} if isinstance(error, NativePublicationSourceFailure) else {}))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
