"""Opt-in native same-session security receipt acceptance on disposable local servers."""
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
from qdrant_security_guard_native import SecurityGuardDatabase,install_guard
from qdrant_purge_native import install as install_purge_profile
from qdrant_security_verification_cases import (CHECKS, GUARD_CHECKS, SETTLEMENT_CHECKS, DISPATCH_CHECKS, COMPLETION_CHECKS, REPETITION_CHECKS, ERRORS, NativeSecurityVerificationFailure,
    python_security_verification_cases, security_verification_input)
from qdrant_source_native import PostgresSourceFixture
from runtime_diagnostics import CleanupFailure, describe_error
from check_qdrant_partial_repair import native_role_checks


GRAPH_CHECKS=(
 'actual_guard_nonlocking_full_graph',
 'document_lock_wait_observed_until_guard_commit',
 'late_canonical_drift_refused',
 'late_vector_drift_refused',
 'late_manifest_drift_refused',
 'extra_raw_claim_refused',
 'post_wait_authority_mismatch_refused',
 'supervisor_connection_loss_releases_document_without_commit',
 'late_callback_retains_control_and_writer_until_drained',
)


def validate_result(value, runtime, *, security_guard=False, guarded_graph=False, security_settlement=False, security_dispatch=False, security_completion=False, security_repetition=False, public_security=False):
    if public_security:
        from qdrant_public_security_cases import CHECKS as PUBLIC_CHECKS
        if (type(value) is not dict or set(value)!={'runtime','checks','proof_scope','semantic_witness_sha256'}
                or value['runtime']!=runtime or value['checks']!=list(PUBLIC_CHECKS)
                or value['proof_scope']!='native_public_security_convergence_only'
                or type(value['semantic_witness_sha256']) is not str or len(value['semantic_witness_sha256'])!=64
                or any(char not in '0123456789abcdef' for char in value['semantic_witness_sha256'])
                or any((guarded_graph,security_settlement,security_dispatch,security_completion,security_repetition))):
            raise RuntimeError('public_security_native_result_shape')
        return json.loads(json.dumps(value))
    fields={'runtime','checks','proof_scope','semantic_witness_sha256'}
    if security_guard:fields.add('guard_admission')
    if guarded_graph:fields.add('guarded_graph')
    if security_settlement:fields.add('security_settlement')
    if security_repetition and (not security_guard or guarded_graph or security_settlement or security_dispatch or security_completion):
        raise RuntimeError('security_repetition_requires_exclusive_guard_profile')
    if security_completion and (not security_guard or guarded_graph or security_settlement or security_dispatch):
        raise RuntimeError('security_completion_requires_exclusive_guard_profile')
    if security_dispatch and (not security_guard or guarded_graph or security_settlement):
        raise RuntimeError('security_dispatch_requires_exclusive_guard_profile')
    if security_settlement and (not security_guard or guarded_graph):
        raise RuntimeError('security_settlement_requires_exclusive_guard_profile')
    if (type(value) is not dict or set(value) != fields
            or value['runtime'] != runtime or value['checks'] != list(REPETITION_CHECKS if security_repetition else COMPLETION_CHECKS if security_completion else DISPATCH_CHECKS if security_dispatch else CHECKS)
            or value['proof_scope'] != ('native_security_repetition_only' if security_repetition else 'native_security_completion_only' if security_completion else 'native_security_dispatch_only' if security_dispatch else 'native_security_receipt_only')
            or type(value['semantic_witness_sha256']) is not str or len(value['semantic_witness_sha256'])!=64
            or any(char not in '0123456789abcdef' for char in value['semantic_witness_sha256'])):
        raise RuntimeError('security_verification_native_result_shape')
    if security_guard:
        guard=value['guard_admission']
        if (type(guard) is not dict or set(guard)!={'checks','denied_backend_queries'}
                or type(guard['checks']) is not list or guard['checks']!=list(GUARD_CHECKS)
                or any(type(item) is not str for item in guard['checks'])
                or type(guard['denied_backend_queries']) is not int or guard['denied_backend_queries']!=0):
            raise RuntimeError('security_verification_guard_result_shape')
    if guarded_graph:
        graph=value['guarded_graph']
        if (not security_guard or type(graph) is not dict or set(graph)!={'checks','denied_commits'}
                or type(graph['checks']) is not list or graph['checks']!=list(GRAPH_CHECKS)
                or any(type(item) is not str for item in graph['checks'])
                or type(graph['denied_commits']) is not int or graph['denied_commits']!=0):
            raise RuntimeError('security_guarded_graph_result_shape')
    if security_settlement:
        settlement=value['security_settlement']
        if (type(settlement) is not dict or set(settlement)!={'checks','confirmation_writes'}
                or type(settlement['checks']) is not list or settlement['checks']!=list(SETTLEMENT_CHECKS)
                or any(type(item) is not str for item in settlement['checks'])
                or type(settlement['confirmation_writes']) is not int or settlement['confirmation_writes']!=0):
            raise RuntimeError('security_settlement_result_shape')
    return json.loads(json.dumps(value))


def failure_observation(value):
    if (type(value) is not dict or value.get('ok') is not False or type(value.get('step')) is not int
            or not 0 <= value['step'] <= len(CHECKS) or type(value.get('error')) is not str):
        raise RuntimeError('security_verification_native_failure_shape')
    if value['error'] in ERRORS:
        if set(value) != {'ok', 'step', 'error'}:
            raise RuntimeError('security_verification_native_failure_shape')
    elif value['error'] == 'cleanup_failed':
        if (set(value) != {'ok', 'step', 'error', 'primary', 'cleanup'}
                or value['primary'] is not None and (type(value['primary']) is not str or value['primary'] not in ERRORS)
                or type(value['cleanup']) is not list or not 1 <= len(value['cleanup']) <= 64):
            raise RuntimeError('security_verification_native_failure_shape')
        for record in value['cleanup']:
            if (type(record) is not dict or set(record) != {'operation', 'outcome'}
                    or type(record['operation']) is not str or record['operation'] not in ('manager_close', 'transport_close', 'writer_close', 'recovery_close', 'resource_close',
                        'supervisor_resource_close', 'controller_close', 'listener_close', 'verifier_close',
                        'host_close', 'worker_drain', 'worker_terminate', 'publish_drain',
                        'wrong_verifier_close', 'reconciliation_close', 'wrong_writer_close',
                        'catalog_restore','operator_pool_close','factory_pool_close',
                        'guard_graph_restore','guard_graph_drain','contender_writer_close','contender_pool_close','admin_pool_close')
                    or type(record['outcome']) is not str or record['outcome'] not in ERRORS):
                raise RuntimeError('security_verification_native_failure_shape')
    else:
        raise RuntimeError('security_verification_native_failure_shape')
    return json.loads(json.dumps(value))


async def node_security_verification_cases(value, *, public_security=False):
    environment = {key: val for key, val in os.environ.items() if not key.startswith(('PG', 'QDRANT__'))
        and key not in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NODE_OPTIONS', 'NODE_USE_ENV_PROXY', 'RUST_LOG')}
    consumer = 'check_typescript_qdrant_public_security.mjs' if public_security else 'check_typescript_qdrant_security_verification.mjs'
    process = await asyncio.create_subprocess_exec('node', str(ROOT / 'tools' / consumer),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=environment, start_new_session=True, limit=65536)
    output = asyncio.create_task(read_bounded(process.stdout, 65536))
    errors = asyncio.create_task(read_bounded(process.stderr, 65536))
    primary = None
    success = False
    try:
        # Allow the 120s business deadline and bounded owned cleanup to finish.
        async with asyncio.timeout(200):
            process.stdin.write(json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode())
            await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()
            stdout, stderr = await asyncio.gather(output, errors)
            code = await process.wait()
        if code != 0 and not stderr:
            observation = failure_observation(json.loads(stdout))
            failure = NativeSecurityVerificationFailure(observation)
            raise failure
        if code != 0 or stderr:
            raise RuntimeError('security_verification_native_child_failed')
        result = validate_result(json.loads(stdout), 'typescript',public_security=public_security,security_guard='guard_operator_config' in value,guarded_graph='guard_graph_config' in value,security_settlement='settlement_config' in value,security_dispatch='dispatch_config' in value,security_completion='completion_config' in value,security_repetition='repetition_config' in value)
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


async def check(fixture, runtime, binary, work_dir, *, security_guard=False, purge_profile=False, guarded_graph=False, security_settlement=False, security_dispatch=False, security_completion=False, security_repetition=False, public_security=False):
    database_type=SecurityGuardDatabase if security_guard else PublicationDatabase
    async with database_type(fixture, with_attestations=True) as database:
        if security_guard:await install_guard(database)
        if purge_profile:await install_purge_profile(database)
        client_ceiling=4 if guarded_graph else 3 if security_guard else 2
        cursor = await database.admin.execute("SELECT current_setting('max_connections')::int,"
            "current_setting('superuser_reserved_connections')::int,"
            "current_setting('reserved_connections')::int")
        maximum, superuser, reserved = (await cursor.fetchall())[0]
        if maximum - superuser - reserved < client_ceiling:
            raise RuntimeError('security_verification_native_two_runtime_slots_required')
        (work_dir.parent.parent / (runtime + '-postgres-limits.json')).write_text(json.dumps(dict(
            max_connections=maximum, superuser_reserved_connections=superuser,
            reserved_connections=reserved, runtime_client_ceiling=client_ceiling), indent=2) + '\n')
        role_checks=await native_role_checks(database,profile=5 if purge_profile else 3)
        (work_dir.parent.parent / (runtime+'-role-checks.json')).write_text(json.dumps(role_checks,indent=2)+'\n')
        value = dict(binary=str(binary), work_dir=str(work_dir), inputs=security_verification_input(),
            writer_config=database.config('writer'), supervisor_config=database.config('supervisor'))
        if public_security:
            from qdrant_public_security_cases import python_public_security_cases
            value['reader_config']=database.config('reader')
            await database.release_admin()
            result = (await python_public_security_cases(value) if runtime=='python' else
                      await node_security_verification_cases(value,public_security=True))
            return validate_result(result,runtime,public_security=True)
        if security_guard:value['guard_operator_config']=dict(database._operator_config)
        if guarded_graph:value['guard_graph_config']=dict(admin_config=fixture.config)
        if security_settlement:value['settlement_config']=dict(admin_config=fixture.config)
        if security_dispatch:value['dispatch_config']=dict(admin_config=fixture.config)
        if security_completion:value['completion_config']=dict(admin_config=fixture.config)
        if security_repetition:value['repetition_config']=dict(admin_config=fixture.config)
        await database.release_admin()
        runner = python_security_verification_cases if runtime == 'python' else node_security_verification_cases
        return validate_result(await runner(value), runtime,security_guard=security_guard,guarded_graph=guarded_graph,security_settlement=security_settlement,security_dispatch=security_dispatch,security_completion=security_completion,security_repetition=security_repetition)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--server-binary', type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    parser.add_argument('--with-security-guard',action='store_true')
    parser.add_argument('--with-purge-profile',action='store_true')
    parser.add_argument('--guarded-graph',action='store_true')
    parser.add_argument('--security-settlement',action='store_true')
    parser.add_argument('--security-dispatch',action='store_true')
    parser.add_argument('--security-completion',action='store_true')
    parser.add_argument('--security-repetition',action='store_true')
    parser.add_argument('--public-security',action='store_true')
    parser.add_argument('--runtime', choices=('python', 'typescript', 'all'), default='all')
    parser.add_argument('--allow-local-processes', action='store_true', required=True)
    args = parser.parse_args(argv)
    artifacts_owned=False
    try:
        if args.guarded_graph and not args.with_security_guard:raise RuntimeError('guarded_graph_requires_guard_profile')
        if args.with_purge_profile and not args.with_security_guard:raise RuntimeError('purge_profile_requires_guard_profile')
        if args.public_security and (not args.with_purge_profile or args.guarded_graph or args.security_settlement or args.security_dispatch or args.security_completion or args.security_repetition):
            raise RuntimeError('public_security_requires_exclusive_purge_profile')
        if args.security_repetition and (not args.with_purge_profile or args.guarded_graph or args.security_settlement or args.security_dispatch or args.security_completion):
            raise RuntimeError('security_repetition_requires_exclusive_purge_profile')
        if args.security_settlement and (not args.with_security_guard or args.guarded_graph):
            raise RuntimeError('security_settlement_requires_exclusive_guard_profile')
        if args.security_dispatch and (not args.with_security_guard or args.guarded_graph or args.security_settlement):
            raise RuntimeError('security_dispatch_requires_exclusive_guard_profile')
        if args.security_completion and (not args.with_security_guard or args.guarded_graph or args.security_settlement or args.security_dispatch):
            raise RuntimeError('security_completion_requires_exclusive_guard_profile')
        binary = args.server_binary.resolve(strict=True)
        if (args.binary_sha256 != REFERENCE_BINARY_SHA256 or not binary.is_file()
                or not os.access(binary, os.X_OK) or sha256(binary.read_bytes()).hexdigest() != REFERENCE_BINARY_SHA256):
            raise RuntimeError('security_verification_native_binary_profile')
        if args.artifacts_dir.exists():
            raise RuntimeError('security_verification_native_fresh_artifacts_required')
        args.artifacts_dir.mkdir(parents=True, mode=0o700);artifacts_owned=True
        results = []
        for runtime in ('python', 'typescript') if args.runtime == 'all' else (args.runtime,):
            private = Path(tempfile.mkdtemp(prefix=runtime + '-', dir=args.artifacts_dir)).resolve()
            # Two runtime clients and the default three reserved slots.
            with PostgresSourceFixture(args.postgres_bin, private / 'postgres', max_connections=7 if args.guarded_graph else 6 if args.with_security_guard else 5) as fixture:
                result = asyncio.run(asyncio.wait_for(check(fixture, runtime, binary, private / 'managed',security_guard=args.with_security_guard,purge_profile=args.with_purge_profile,guarded_graph=args.guarded_graph,security_settlement=args.security_settlement,security_dispatch=args.security_dispatch,security_completion=args.security_completion,security_repetition=args.security_repetition,public_security=args.public_security), 210))
            shutil.rmtree(private)
            results.append(result)
        if len({result['semantic_witness_sha256'] for result in results})!=1:
            raise RuntimeError('security_verification_native_semantic_witness_mismatch')
        (args.artifacts_dir / 'results.json').write_text(json.dumps(
            dict(ok=True, results=results, cleanup_verified=True), indent=2) + '\n')
        print(json.dumps(dict(ok=True, checks=sum(len(r['checks'])+len(r.get('guard_admission',{}).get('checks',[]))+len(r.get('guarded_graph',{}).get('checks',[]))+len(r.get('security_settlement',{}).get('checks',[])) for r in results), cleanup_verified=True)))
        return 0
    except Exception as error:
        primary=getattr(error,'primary',None) if isinstance(error,NativeSecurityVerificationFailure) else None
        diagnostic = error.to_dict() if isinstance(error, CleanupFailure) else describe_error(primary or error, operation='primary', stage='recovery')
        if artifacts_owned:
            import traceback
            locations=[]
            for frame in traceback.extract_tb((primary or error).__traceback__):
                try:relative=Path(frame.filename).resolve().relative_to(ROOT)
                except ValueError:continue
                if relative.parts[0] in ('tools','packages'):locations.append(dict(path=str(relative),line=frame.lineno))
            try:(args.artifacts_dir/'failure-locations.json').write_text(json.dumps(locations)+'\n')
            except Exception:pass
        print(json.dumps(dict(ok=False, error=diagnostic,
            **({'native': error.observation} if isinstance(error, NativeSecurityVerificationFailure) else {}))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
