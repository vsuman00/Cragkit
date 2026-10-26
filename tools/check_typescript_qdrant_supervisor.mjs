/** Native E1 process and credential observations. No SQL settlement is asserted. */
import {execFile} from 'node:child_process';
import http from 'node:http';
import {isDeepStrictEqual} from 'node:util';
import {ManagedQdrantSupervisor} from '../packages/typescript/dist/qdrant-supervisor.js';
import {now} from '../packages/typescript/dist/postgres-pool.js';
import {ProviderUnavailable, UnsupportedCapability} from '../packages/typescript/dist/errors.js';

const OWNER_TOKEN = '00000000-0000-4000-8000-000000000001';
const ERROR_NAMES = new Set(['IntegrityViolation', 'UnauthorizedScope', 'IndexNotReady',
  'InvalidRequest', 'ProviderUnavailable', 'UnsupportedCapability', 'DeadlineExceeded']);
let phase = 'input';
const cancellation = new AbortController();
const cancel = () => {
  cancellation.abort();
  if (phase === 'input') process.stdin.destroy();
};
process.on('SIGTERM', cancel);
process.on('SIGINT', cancel);

function outcome(error) {
  let name;
  try { name = error?.name; } catch { return 'internal'; }
  return ERROR_NAMES.has(name) ? name : 'internal';
}

class RuntimeCleanupFailure extends Error {
  constructor(primary, failures) {
    super('runtime_cleanup_failed');
    this.primary = primary ? outcome(primary) : null;
    this.failures = failures;
  }
}

async function bounded(operation, milliseconds) {
  let timer;
  try {
    return await Promise.race([Promise.resolve().then(operation), new Promise((_, reject) => {
      timer = setTimeout(() => reject(new ProviderUnavailable()), milliseconds);
    })]);
  } finally {
    clearTimeout(timer);
  }
}

async function input() {
  const chunks = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > 262144) throw new Error('bounded_input');
    chunks.push(chunk);
  }
  const value = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(Buffer.concat(chunks)));
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || !isDeepStrictEqual(Object.keys(value).sort(), ['binary', 'inputs', 'work_dir'])
    || typeof value.binary !== 'string' || typeof value.work_dir !== 'string'
    || !value.inputs || typeof value.inputs !== 'object' || Array.isArray(value.inputs)) {
    throw new Error('input_shape');
  }
  return value;
}

const bytes = value => [...Buffer.from(JSON.stringify(value), 'utf8')];
const decode = value => JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(Buffer.from(value)));
const byId = (left, right) => left.id < right.id ? -1 : left.id > right.id ? 1 : 0;

function endpoint(value) {
  if (typeof value !== 'string') throw new Error('endpoint_shape');
  const parsed = new URL(value);
  if (parsed.protocol !== 'http:' || parsed.hostname !== '127.0.0.1' || !parsed.port
    || parsed.username || parsed.password || parsed.pathname !== '/' || parsed.search || parsed.hash
    || parsed.origin !== value) throw new Error('endpoint_shape');
  return parsed;
}

async function observedListener(address, absent = false) {
  const parsed = endpoint(address);
  return new Promise((resolve, reject) => {
    execFile('/usr/sbin/lsof', ['-nP', '-a', '-iTCP@127.0.0.1:' + parsed.port,
      '-sTCP:LISTEN', '-t'], {encoding: 'utf8', env: {PATH: '/usr/bin:/bin'},
      maxBuffer: 1024, timeout: 3000, killSignal: 'SIGKILL'}, (error, stdout, stderr) => {
      if (absent && error?.code === 1 && stdout === '' && stderr === '') return resolve(null);
      const lines = stdout.trim().split('\n');
      if (error || stderr || lines.length !== 1 || !/^[1-9][0-9]{0,9}$/.test(lines[0])) {
        return reject(new Error('owned_listener_not_observed'));
      }
      const pid = Number(lines[0]);
      if (absent || !Number.isSafeInteger(pid) || pid > 2147483647) {
        return reject(new Error('owned_listener_observation'));
      }
      resolve(pid);
    });
  });
}

async function oldKeyMutationStatus(credential, path, body, signal) {
  const parsed = endpoint(credential.endpoint);
  if (typeof credential.api_key !== 'string' || !/^[0-9a-f]{64}$/.test(credential.api_key)) {
    throw new Error('worker_credential_shape');
  }
  if (signal.aborted) throw new ProviderUnavailable();
  return new Promise((resolve, reject) => {
    let finished = false;
    let request;
    const finish = (error, status) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      signal.removeEventListener('abort', abort);
      if (error) reject(new Error('old_key_request_failed'));
      else resolve(status);
    };
    const abort = () => request?.destroy(new Error('request_cancelled'));
    const timer = setTimeout(() => request?.destroy(new Error('request_deadline')), 3000);
    request = http.request({hostname: '127.0.0.1', port: Number(parsed.port), method: 'PUT',
      path, agent: false, maxHeaderSize: 16384,
      headers: {'api-key': credential.api_key, 'content-type': 'application/json',
        'content-length': body.length}}, response => {
      let size = 0;
      response.on('data', chunk => {
        size += chunk.length;
        if (size > 1024) response.destroy(new Error('bounded_response'));
      });
      response.once('end', () => finish(null, response.statusCode));
      response.once('aborted', () => finish(new Error('response_aborted')));
      response.once('error', () => finish(new Error('response_failed')));
    });
    signal.addEventListener('abort', abort, {once: true});
    if (signal.aborted) abort();
    request.once('error', () => finish(new Error('request_failed')));
    request.end(body);
  });
}

function completed(raw) {
  const value = decode(raw);
  if (value?.status !== 'ok' || value?.result?.status !== 'completed') {
    throw new Error('write_not_completed');
  }
}

async function expect(Type, operation) {
  try { await operation(); } catch (error) { if (error instanceof Type) return; throw error; }
  throw new Error('expected_failure_missing');
}

async function cases({binary, work_dir, inputs}) {
  const supervisor = new ManagedQdrantSupervisor(binary, work_dir, inputs.instance_id, inputs.config);
  const competitor = new ManagedQdrantSupervisor(binary, work_dir, inputs.instance_id, inputs.config);
  const options = {deadline: now() + 60, signal: cancellation.signal};
  const checks = [];
  const oldCredential = {};
  const target = '/collections/' + inputs.config.physical_collection;
  const body = bytes({points: inputs.points});
  let primary;
  let ownedEndpoint;
  async function provision(admin, probe) {
    await admin.request('PUT', target, {...options, body: bytes(inputs.collection_config)});
    await admin.request('PUT', '/collections/' + probe.collection,
      {...options, body: bytes(probe.collection_config)});
    await admin.request('PUT', '/collections/' + probe.collection + '/points?wait=true&ordering=strong',
      {...options, body: bytes({points: [probe.point]})});
  }
  async function sink(value) { Object.assign(oldCredential, value); }
  try {
    phase = 'initialize';
    await supervisor.initialize({...options, provision});
    const before = supervisor.identity();
    const registered = supervisor.profile_binding(inputs.config);
    if (registered.instance_id !== before.instance_id || registered.storage_identity !== before.storage_identity
      || registered.supervisor_id !== before.supervisor_id || registered.epoch !== 1
      || registered.alive !== true || registered.sealed || registered.recovery !== null) throw new Error('registered_profile_binding');
    let profileRejected = false;
    try { supervisor.profile_binding({...inputs.config, physical_collection: 'UnregisteredProfile'}); }
    catch (error) { if (!(error instanceof UnsupportedCapability)) throw error; profileRejected = true; }
    if (!profileRejected) throw new Error('unregistered_profile_accepted');
    ownedEndpoint = before.endpoint;
    if (!Object.isFrozen(before) || !Object.isFrozen(before.probe_spec)) throw new Error('identity_not_frozen');
    const firstPid = await observedListener(before.endpoint);
    checks.push('explicit_provisioning_verified_profiles_probe_and_owned_listener');

    phase = 'competing_controller';
    let competitorRejected = false;
    try { await competitor.initialize({...options, provision}); }
    catch (error) {
      if (!(error instanceof UnsupportedCapability) && !(error instanceof ProviderUnavailable)) throw error;
      competitorRejected = true;
    }
    if (!competitorRejected) throw new Error('competing_controller_admitted');
    await bounded(() => competitor.close(), 6000);
    if (await observedListener(before.endpoint) !== firstPid) throw new Error('competitor_affected_owner');
    checks.push('competing_controller_refused_without_affecting_owned_process');

    phase = 'ordinary_attempt';
    const attempt = {intent_id: 'e1-native', owner_token: OWNER_TOKEN, epoch: 1, dispatch_id: 'e1-write'};
    const capability = supervisor.issue_attempt(attempt, options);
    const handle = supervisor.transport_for(capability);
    completed(await handle.request('PUT', target + '/points?wait=true&ordering=strong', {...options, body}));
    await supervisor.deliver_worker_credential(capability, sink, options);
    if (!isDeepStrictEqual(Object.keys(oldCredential).sort(), ['api_key', 'endpoint', 'epoch', 'instance_id'])
      || oldCredential.epoch !== 1 || oldCredential.instance_id !== inputs.instance_id
      || oldCredential.endpoint !== before.endpoint) throw new Error('worker_delivery_shape');
    checks.push('ordinary_attempt_uses_immutable_key_and_explicit_private_worker_delivery');

    phase = 'physical_recovery';
    const recovery = {recovery_id: 'e1-recovery', old_epoch: 1, new_epoch: 2};
    const proof = await supervisor.recover(recovery, options);
    const after = supervisor.identity();
    const recoveryProfile = supervisor.profile_binding(inputs.config);
    if (recoveryProfile.epoch !== 2 || recoveryProfile.recovery?.recovery_id !== 'e1-recovery'
      || recoveryProfile.alive !== true) throw new Error('recovery_profile_binding');
    const secondPid = await observedListener(after.endpoint);
    if (firstPid === secondPid || after.endpoint !== before.endpoint) throw new Error('process_not_restarted');
    for (const field of ['instance_id', 'storage_identity', 'supervisor_id']) {
      if (after[field] !== before[field]) throw new Error('durable_identity_changed');
    }
    if (await oldKeyMutationStatus(oldCredential, target + '/points?wait=true&ordering=strong', Buffer.from(body), options.signal) !== 401) {
      throw new Error('old_key_not_denied');
    }
    checks.push('actual_restart_same_storage_and_captured_old_key_mutation_denied');

    phase = 'recovery_capability';
    const binding = supervisor.recovery_binding(proof);
    if (binding.recovery_id !== 'e1-recovery' || binding.old_epoch !== 1 || binding.new_epoch !== 2) {
      throw new Error('physical_binding');
    }
    await expect(ProviderUnavailable, () => supervisor.issue_attempt(
      {...attempt, epoch: 2, dispatch_id: 'forbidden-ordinary'}, options));
    checks.push('physical_proof_does_not_reopen_ordinary_admission');
    await expect(UnsupportedCapability, () => supervisor.issue_recovery_attempt(
      JSON.parse(JSON.stringify(binding)), {...attempt, epoch: 2, recovery_id: 'e1-recovery'}, options));
    checks.push('serialized_physical_metadata_is_not_a_recovery_capability');

    phase = 'recovery_readback';
    const newCapability = supervisor.issue_recovery_attempt(proof,
      {...attempt, epoch: 2, recovery_id: 'e1-recovery', dispatch_id: 'e1-reconcile'}, options);
    const newHandle = supervisor.transport_for(newCapability);
    completed(await newHandle.request('PUT', target + '/points?wait=true&ordering=strong', {...options, body}));
    const readback = decode(await newHandle.request('POST', target + '/points', {...options,
      body: bytes({ids: inputs.points.map(point => point.id), with_payload: true, with_vector: true})}));
    if (readback?.status !== 'ok' || !Array.isArray(readback.result)) throw new Error('readback_shape');
    const observed = readback.result.map(point => ({id: point.id, payload: point.payload, vector: point.vector})).sort(byId);
    if (!isDeepStrictEqual(observed, [...inputs.points].sort(byId))) throw new Error('complete_readback_mismatch');
    checks.push('new_recovery_key_completes_write_and_exact_full_point_readback');
    await expect(UnsupportedCapability, () => supervisor.deliver_worker_credential(newCapability, sink, options));
    checks.push('recovery_credential_cannot_be_delivered_to_worker');

    phase = 'repeated_recovery';
    const resumed = await supervisor.recover(recovery, options);
    if (supervisor.recovery_binding(resumed).new_epoch !== 2
      || await observedListener(after.endpoint) === secondPid) throw new Error('resume_skipped_physical_fence');
    await expect(UnsupportedCapability, () => supervisor.recovery_binding(proof));
    checks.push('same_recovery_identity_repeats_physical_fence_without_new_gate_epoch');
    return {runtime: 'typescript', checks, proof_scope: 'process_credentials_profiles_only'};
  } catch (error) {
    primary = error;
    throw error;
  } finally {
    const failures = [];
    for (const owned of [competitor, supervisor]) {
      try {
        await bounded(() => owned.close(), 6000);
        await bounded(() => owned.close(), 6000);
      } catch (error) { failures.push({operation: 'controller_close', outcome: outcome(error)}); }
    }
    for (const key of Object.keys(oldCredential)) delete oldCredential[key];
    if (ownedEndpoint) {
      try { await observedListener(ownedEndpoint, true); }
      catch (error) { failures.push({operation: 'listener_close', outcome: outcome(error)}); }
    }
    if (failures.length) throw new RuntimeCleanupFailure(primary, failures);
  }
}

try {
  const value = await bounded(input, 5000);
  process.stdout.write(JSON.stringify(await cases(value)) + '\n');
} catch (error) {
  process.stdin.destroy();
  // Closed diagnostics only. Never print controller messages, credentials or fixture data.
  process.stdout.write(JSON.stringify({ok: false, phase,
    error: error instanceof RuntimeCleanupFailure ? 'cleanup_failed' : outcome(error),
    ...(error instanceof RuntimeCleanupFailure ? {primary: error.primary, cleanup: error.failures} : {})}) + '\n');
  process.exitCode = 1;
}
