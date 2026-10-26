"""Native E1 process/credential observations; no SQL settlement is asserted."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from copy import deepcopy
import json
import urllib.error
import urllib.request

from qdrant_writer_cases import writer_input
from runtime_diagnostics import CleanupFailure


class SupervisorCaseFailure(RuntimeError):
    def __init__(self, phase, error):
        super().__init__('supervisor_native_case_failed')
        allowed = {'InvalidRequest', 'ProviderUnavailable', 'UnsupportedCapability', 'DeadlineExceeded',
            'IndexNotReady', 'IntegrityViolation', 'UnauthorizedScope'}
        name = type(error).__name__
        self.observation = dict(phase=phase, error=name if name in allowed else 'internal')


def supervisor_input():
    value = writer_input()
    collection = dict(vectors=dict(dense=dict(size=1536, distance='Cosine')),
        sparse_vectors=dict(sparse={}), replication_factor=1, write_consistency_factor=1,
        optimizers_config=dict(prevent_unoptimized=False, max_optimization_threads=1),
        hnsw_config=dict(m=0))
    return dict(config=value['config'], collection_config=collection,
        instance_id='supervisor-native-fixture', points=value['expected_points'])


def plain(value):
    """Copy controller-issued immutable fixture data for explicit provisioning."""
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if type(value) in (tuple, list):
        return [plain(item) for item in value]
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise RuntimeError('supervisor_fixture_metadata_shape')


def request_bytes(value):
    return json.dumps(plain(value), separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


async def observed_listener(endpoint, *, allow_absent=False):
    """Observe the actual loopback listener independently of a proof object."""
    from urllib.parse import urlsplit
    port = urlsplit(endpoint).port
    if not endpoint.startswith('http://127.0.0.1:') or port is None:
        raise RuntimeError('supervisor_fixture_endpoint')
    process = await asyncio.create_subprocess_exec('/usr/sbin/lsof', '-nP', '-a',
        '-iTCP@127.0.0.1:' + str(port), '-sTCP:LISTEN', '-t',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    primary = None
    from check_qdrant_writer import read_bounded
    output = asyncio.create_task(read_bounded(process.stdout, 1024))
    errors = asyncio.create_task(read_bounded(process.stderr, 1024))
    try:
        async with asyncio.timeout(3):
            stdout, stderr = await asyncio.gather(output, errors)
            await process.wait()
        if allow_absent and process.returncode == 1 and not stdout and not stderr:
            return None
        lines = stdout.splitlines()
        if process.returncode != 0 or stderr or len(stdout) > 1024 or len(lines) != 1 or not lines[0].isdigit():
            raise RuntimeError('supervisor_fixture_owned_listener_not_observed')
        return int(lines[0])
    except BaseException as error:
        primary = error
        raise
    finally:
        failure = None
        try:
            if process.returncode is None:
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
            raise CleanupFailure([('child_stop', failure)], primary=primary, stage='recovery') from None


def old_key_mutation_status(credential, path, body):
    """Use the captured immutable old secret only on the owned loopback server."""
    endpoint = credential['endpoint']
    if not endpoint.startswith('http://127.0.0.1:'):
        raise RuntimeError('supervisor_fixture_endpoint')
    request = urllib.request.Request(endpoint + path, data=body, method='PUT',
        headers={'api-key': credential['api_key'], 'content-type': 'application/json'})
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with client.open(request, timeout=3) as response:
            response.read(1025)
            return response.status
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        return code
    except Exception:
        raise RuntimeError('supervisor_fixture_old_key_request_failed') from None


async def python_supervisor_cases(binary, work_dir, inputs):
    from cragkit._qdrant_supervisor import ManagedQdrantSupervisor
    from cragkit.errors import ProviderUnavailable, UnsupportedCapability
    supervisor = ManagedQdrantSupervisor(binary, work_dir, inputs['instance_id'], inputs['config'])
    competitor = ManagedQdrantSupervisor(binary, work_dir, inputs['instance_id'], inputs['config'])
    deadline = asyncio.get_running_loop().time() + 60
    checks = []
    old_credential = {}
    owner = '00000000-0000-4000-8000-000000000001'
    target = '/collections/' + inputs['config']['physical_collection']
    body = request_bytes(dict(points=inputs['points']))
    primary = None
    endpoint = None
    phase = 'initialize'

    async def provision(admin, probe):
        await admin.request('PUT', target, body=request_bytes(inputs['collection_config']), deadline=deadline)
        specification = plain(probe)
        await admin.request('PUT', '/collections/' + specification['collection'],
            body=request_bytes(specification['collection_config']), deadline=deadline)
        await admin.request('PUT', '/collections/' + specification['collection'] + '/points?wait=true&ordering=strong',
            body=request_bytes(dict(points=[specification['point']])), deadline=deadline)

    async def sink(value):
        old_credential.update(value)

    def completed(raw):
        result = json.loads(bytes(raw))
        if result.get('status') != 'ok' or result.get('result', {}).get('status') != 'completed':
            raise RuntimeError('supervisor_fixture_write_not_completed')

    try:
        await supervisor.initialize(deadline=deadline, provision=provision)
        before = plain(supervisor.identity())
        registered = plain(supervisor.profile_binding(inputs['config']))
        if (registered['instance_id'] != before['instance_id']
                or registered['storage_identity'] != before['storage_identity']
                or registered['supervisor_id'] != before['supervisor_id']
                or registered['epoch'] != 1 or registered['alive'] is not True
                or registered['sealed'] or registered['recovery'] is not None):
            raise RuntimeError('supervisor_fixture_registered_profile_binding')
        try:
            supervisor.profile_binding(dict(inputs['config'], physical_collection='UnregisteredProfile'))
        except UnsupportedCapability:
            pass
        else:
            raise RuntimeError('supervisor_fixture_unregistered_profile_accepted')
        endpoint = before['endpoint']
        first_pid = await observed_listener(before['endpoint'])
        checks.append('explicit_provisioning_verified_profiles_probe_and_owned_listener')
        phase = 'competing_controller'
        try:
            await competitor.initialize(deadline=deadline, provision=provision)
        except (UnsupportedCapability, ProviderUnavailable):
            pass
        else:
            raise RuntimeError('supervisor_fixture_competing_controller_admitted')
        await competitor.close()
        if await observed_listener(before['endpoint']) != first_pid:
            raise RuntimeError('supervisor_fixture_competitor_affected_owner')
        checks.append('competing_controller_refused_without_affecting_owned_process')
        phase = 'ordinary_attempt'
        attempt = dict(intent_id='e1-native', owner_token=owner, epoch=1, dispatch_id='e1-write')
        capability = supervisor.issue_attempt(attempt, deadline=deadline)
        handle = supervisor.transport_for(capability)
        completed(await handle.request('PUT', target + '/points?wait=true&ordering=strong', body=body, deadline=deadline))
        await supervisor.deliver_worker_credential(capability, sink, deadline=deadline)
        if set(old_credential) != {'endpoint', 'api_key', 'epoch', 'instance_id'} or old_credential['epoch'] != 1:
            raise RuntimeError('supervisor_fixture_worker_delivery_shape')
        checks.append('ordinary_attempt_uses_immutable_key_and_explicit_private_worker_delivery')
        phase = 'physical_recovery'
        recovery = dict(recovery_id='e1-recovery', old_epoch=1, new_epoch=2)
        proof = await supervisor.recover(recovery, deadline=deadline)
        after = plain(supervisor.identity())
        registered = plain(supervisor.profile_binding(inputs['config']))
        if (registered['epoch'] != 2 or registered['recovery']['recovery_id'] != 'e1-recovery'
                or registered['alive'] is not True):
            raise RuntimeError('supervisor_fixture_recovery_profile_binding')
        second_pid = await observed_listener(after['endpoint'])
        if second_pid == first_pid or after['endpoint'] != before['endpoint']:
            raise RuntimeError('supervisor_fixture_process_was_not_restarted')
        for field in ('instance_id', 'storage_identity', 'supervisor_id'):
            if after[field] != before[field]:
                raise RuntimeError('supervisor_fixture_durable_identity_changed')
        status = await asyncio.to_thread(old_key_mutation_status, old_credential,
            target + '/points?wait=true&ordering=strong', body)
        if status != 401:
            raise RuntimeError('supervisor_fixture_old_key_was_not_denied')
        checks.append('actual_restart_same_storage_and_captured_old_key_mutation_denied')
        phase = 'recovery_capability'
        binding = plain(supervisor.recovery_binding(proof))
        if (binding['recovery_id'], binding['old_epoch'], binding['new_epoch']) != ('e1-recovery', 1, 2):
            raise RuntimeError('supervisor_fixture_physical_binding')
        try:
            supervisor.issue_attempt(dict(attempt, epoch=2, dispatch_id='forbidden-ordinary'), deadline=deadline)
        except ProviderUnavailable:
            pass
        else:
            raise RuntimeError('supervisor_fixture_ordinary_admission_reopened_without_sql')
        checks.append('physical_proof_does_not_reopen_ordinary_admission')
        try:
            supervisor.issue_recovery_attempt(binding, dict(attempt, epoch=2, recovery_id='e1-recovery'), deadline=deadline)
        except UnsupportedCapability:
            pass
        else:
            raise RuntimeError('supervisor_fixture_serialized_proof_accepted')
        checks.append('serialized_physical_metadata_is_not_a_recovery_capability')
        recovery_attempt = dict(attempt, epoch=2, recovery_id='e1-recovery', dispatch_id='e1-reconcile')
        new_capability = supervisor.issue_recovery_attempt(proof, recovery_attempt, deadline=deadline)
        phase = 'recovery_readback'
        new_handle = supervisor.transport_for(new_capability)
        completed(await new_handle.request('PUT', target + '/points?wait=true&ordering=strong', body=body, deadline=deadline))
        readback = json.loads(bytes(await new_handle.request('POST', target + '/points',
            body=request_bytes(dict(ids=[point['id'] for point in inputs['points']], with_payload=True, with_vector=True)), deadline=deadline)))
        observed = sorted(readback['result'], key=lambda point: point['id'])
        expected = sorted(deepcopy(inputs['points']), key=lambda point: point['id'])
        if [{key: point[key] for key in ('id', 'payload', 'vector')} for point in observed] != expected:
            raise RuntimeError('supervisor_fixture_complete_readback_mismatch')
        checks.append('new_recovery_key_completes_write_and_exact_full_point_readback')
        try:
            await supervisor.deliver_worker_credential(new_capability, sink, deadline=deadline)
        except UnsupportedCapability:
            pass
        else:
            raise RuntimeError('supervisor_fixture_recovery_key_exported_to_worker')
        checks.append('recovery_credential_cannot_be_delivered_to_worker')
        phase = 'repeated_recovery'
        resumed = await supervisor.recover(recovery, deadline=deadline)
        if plain(supervisor.recovery_binding(resumed))['new_epoch'] != 2:
            raise RuntimeError('supervisor_fixture_resume_allocated_new_gate_epoch')
        if await observed_listener(after['endpoint']) == second_pid:
            raise RuntimeError('supervisor_fixture_resume_skipped_physical_fence')
        try:
            supervisor.recovery_binding(proof)
        except UnsupportedCapability:
            pass
        else:
            raise RuntimeError('supervisor_fixture_old_physical_proof_still_current')
        checks.append('same_recovery_identity_repeats_physical_fence_without_new_gate_epoch')
        return dict(runtime='python', checks=checks, proof_scope='process_credentials_profiles_only')
    except BaseException as error:
        primary = error
        if isinstance(error, Exception):
            raise SupervisorCaseFailure(phase, error) from None
        raise
    finally:
        failures = []
        for owned in (competitor, supervisor):
            try:
                await owned.close()
            except BaseException as error:
                failures.append(('runtime_close', error))
        if endpoint is not None:
            try:
                if await observed_listener(endpoint, allow_absent=True) is not None:
                    raise RuntimeError('supervisor_fixture_listener_remains_after_close')
            except BaseException as error:
                failures.append(('verify_inventory', error))
        old_credential.clear()
        if failures:
            raise CleanupFailure(failures, primary=primary, stage='recovery') from None
