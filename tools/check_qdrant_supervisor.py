"""Opt-in native E1 controller acceptance; never uses hosted data or SQL proof."""
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
from qdrant_supervisor_cases import python_supervisor_cases, supervisor_input, SupervisorCaseFailure
from runtime_diagnostics import CleanupFailure, describe_error

EXPECTED_CHECKS = (
    'explicit_provisioning_verified_profiles_probe_and_owned_listener',
    'competing_controller_refused_without_affecting_owned_process',
    'ordinary_attempt_uses_immutable_key_and_explicit_private_worker_delivery',
    'actual_restart_same_storage_and_captured_old_key_mutation_denied',
    'physical_proof_does_not_reopen_ordinary_admission',
    'serialized_physical_metadata_is_not_a_recovery_capability',
    'new_recovery_key_completes_write_and_exact_full_point_readback',
    'recovery_credential_cannot_be_delivered_to_worker',
    'same_recovery_identity_repeats_physical_fence_without_new_gate_epoch',
)
ERRORS = frozenset(('InvalidRequest', 'ProviderUnavailable', 'UnsupportedCapability',
    'DeadlineExceeded', 'IndexNotReady', 'IntegrityViolation', 'UnauthorizedScope', 'AbortError', 'internal'))
PHASES = frozenset(('input', 'initialize', 'competing_controller', 'ordinary_attempt', 'physical_recovery',
    'recovery_capability', 'recovery_readback', 'repeated_recovery'))


class NativeSupervisorFailure(RuntimeError):
    def __init__(self, observation):
        super().__init__('supervisor_native_case_failed')
        self.observation = observation


def failure_observation(value):
    """Validate a child's closed labels without copying exception messages."""
    if (type(value) is not dict or value.get('ok') is not False
            or type(value.get('phase')) is not str or value['phase'] not in PHASES
            or type(value.get('error')) is not str or value['error'] not in ERRORS | {'cleanup_failed'}):
        raise RuntimeError('supervisor_child_failure_shape')
    if value['error'] == 'cleanup_failed':
        if (set(value) != {'ok', 'phase', 'error', 'primary', 'cleanup'}
                or value['primary'] is not None and (type(value['primary']) is not str or value['primary'] not in ERRORS)
                or type(value['cleanup']) is not list or not 1 <= len(value['cleanup']) <= 6):
            raise RuntimeError('supervisor_child_failure_shape')
        for item in value['cleanup']:
            if (type(item) is not dict or set(item) != {'operation', 'outcome'}
                    or type(item['operation']) is not str or item['operation'] not in ('controller_close', 'listener_close')
                    or type(item['outcome']) is not str or item['outcome'] not in ERRORS):
                raise RuntimeError('supervisor_child_failure_shape')
    elif set(value) != {'ok', 'phase', 'error'}:
        raise RuntimeError('supervisor_child_failure_shape')
    return json.loads(json.dumps(value))


def validate_result(value, runtime):
    if (type(value) is not dict or set(value) != {'runtime', 'checks', 'proof_scope'}
            or value['runtime'] != runtime or value['proof_scope'] != 'process_credentials_profiles_only'
            or type(value['checks']) is not list or value['checks'] != list(EXPECTED_CHECKS)):
        raise RuntimeError('supervisor_native_result_shape')
    return value


async def node_supervisor_cases(binary, work_dir, inputs):
    environment = {key: value for key, value in os.environ.items()
        if not key.startswith(('PG', 'QDRANT__')) and key not in
        ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NODE_USE_ENV_PROXY', 'NODE_OPTIONS', 'RUST_LOG')}
    process = await asyncio.create_subprocess_exec('node', str(ROOT / 'tools/check_typescript_qdrant_supervisor.mjs'),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=environment, start_new_session=True, limit=65536)
    output = asyncio.create_task(read_bounded(process.stdout, 65536))
    errors = asyncio.create_task(read_bounded(process.stderr, 65536))
    primary = None
    success = False
    try:
        async with asyncio.timeout(90):
            process.stdin.write(json.dumps(dict(binary=str(binary), work_dir=str(work_dir), inputs=inputs),
                separators=(',', ':'), ensure_ascii=False).encode())
            await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()
            stdout, stderr = await asyncio.gather(output, errors)
            code = await process.wait()
        if code != 0 and not stderr:
            try:
                observation = failure_observation(json.loads(stdout))
            except (ValueError, RuntimeError):
                raise RuntimeError('supervisor_child_failed') from None
            raise NativeSupervisorFailure(observation)
        if code != 0 or stderr:
            raise RuntimeError('supervisor_child_failed')
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
                    await asyncio.wait_for(process.wait(), 8)
                except TimeoutError:
                    os.killpg(process.pid, signal.SIGKILL)
                    await asyncio.wait_for(process.wait(), 2)
            if not success:
                # The consumer owns this new process group. The Qdrant child is
                # not detached; failed consumers cannot leave that group alive.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        except BaseException as error:
            failures.append(('child_stop', error))
        finally:
            for task in (output, errors):
                if not task.done(): task.cancel()
            try:
                await asyncio.gather(output, errors, return_exceptions=True)
            except BaseException as error:
                failures.append(('child_stop', error))
        if failures:
            raise CleanupFailure(failures, primary=primary, stage='recovery') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
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
            raise RuntimeError('supervisor_native_binary_profile')
        if args.artifacts_dir.exists():
            raise RuntimeError('supervisor_native_fresh_artifacts_required')
        args.artifacts_dir.mkdir(parents=True, mode=0o700)
        results = []
        for runtime in ('python', 'typescript') if args.runtime == 'all' else (args.runtime,):
            private = Path(tempfile.mkdtemp(prefix=runtime + '-', dir=args.artifacts_dir)).resolve()
            os.chmod(private, 0o700)
            inputs = supervisor_input()
            runner = python_supervisor_cases if runtime == 'python' else node_supervisor_cases
            result = asyncio.run(asyncio.wait_for(runner(binary, private / 'managed', inputs), 100))
            validate_result(result, runtime)
            # Only a passed consumer has verified owned listener absence. A
            # failed run retains its owner-only directory for explicit recovery.
            shutil.rmtree(private)
            if private.exists():
                raise RuntimeError('supervisor_native_private_directory_remains')
            results.append(result)
        (args.artifacts_dir / 'results.json').write_text(json.dumps(
            dict(ok=True, results=results, cleanup_verified=True), indent=2) + '\n')
        print(json.dumps(dict(ok=True, runtimes=[result['runtime'] for result in results],
            checks=sum(len(result['checks']) for result in results), cleanup_verified=True)))
        return 0
    except Exception as error:
        diagnostic = error.to_dict() if isinstance(error, CleanupFailure) else describe_error(
            error, operation='primary', stage='recovery')
        print(json.dumps(dict(ok=False, error=diagnostic,
            **({'native': error.observation} if isinstance(error, (NativeSupervisorFailure, SupervisorCaseFailure)) else {}))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
