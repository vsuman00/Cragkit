/** E2a native authority-bound readback. Fault injection never settles a journal. */
import {execFile} from 'node:child_process';
import {constants} from 'node:fs';
import {open, readFile, stat} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {isDeepStrictEqual} from 'node:util';
import {createHash} from 'node:crypto';
import {PoolResource, parse_pool_config, bounded, now, verified_tls_options} from '../packages/typescript/dist/postgres-pool.js';
import {ManagedQdrantSupervisor} from '../packages/typescript/dist/qdrant-supervisor.js';
import {PostgresQdrantWriter, prepare_stage} from '../packages/typescript/dist/qdrant-writer.js';
import {QdrantReconciliationVerifier, receipt_data} from '../packages/typescript/dist/qdrant-reconciliation.js';
import {IntegrityViolation, UnauthorizedScope, UnsupportedCapability, InvalidRequest, ProviderUnavailable} from '../packages/typescript/dist/errors.js';

const OWNER_TOKEN = '00000000-0000-4000-8000-000000000001';
const CHECKS = Object.freeze([
  'same_generation_different_manifest_rejected_without_member_append',
  'actual_journaled_write_lost_ack_remains_unknown',
  'physical_fence_and_same_owner_epoch_advance_remain_blocked',
  'actual_exact_current_authority_membership_and_vectors_verified',
  'serialized_physical_proof_cannot_mint_receipt',
  'serialized_receipt_has_no_private_provenance',
  'equal_count_wrong_membership_rejected',
  'same_dimension_wrong_dense_vector_rejected',
  'wrong_sparse_vector_rejected',
  'missing_named_sparse_vector_rejected',
  'wrong_full_profile_payload_rejected',
  'stale_scope_and_old_acl_replica_rejected_after_authority_change',
  'fresh_scope_and_actual_current_acl_readback_verified',
  'projection_invalidated_by_later_authority_change',
  'tombstone_requires_actual_absence_and_scoped_eof',
  'unexpected_scoped_point_prevents_tombstone_absence',
  'actual_transport_enforces_remaining_response_allowance',
  'readback_never_settles_journal_or_reopens_gate',
]);
const ERRORS = new Set(['IntegrityViolation', 'UnauthorizedScope', 'IndexNotReady', 'InvalidRequest',
  'ProviderUnavailable', 'UnsupportedCapability', 'DeadlineExceeded']);
let phase = 'input';
let step = 0;
const cancellation = new AbortController();
const cancel = () => {
  cancellation.abort();
  if (phase === 'input') process.stdin.destroy();
};
process.on('SIGTERM', cancel);
process.on('SIGINT', cancel);
const bytes = value => [...Buffer.from(JSON.stringify(value), 'utf8')];

function outcome(error) {
  let name;
  try { name = error?.name; } catch { return 'internal'; }
  return ERRORS.has(name) ? name : 'internal';
}
class RuntimeCleanupFailure extends Error {
  constructor(primary, failures) {
    super('runtime_cleanup_failed');
    this.primary = primary ? outcome(primary) : null;
    this.failures = failures;
  }
}
async function input() {
  const chunks = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > 524288) throw new Error('bounded_input');
    chunks.push(chunk);
  }
  const value = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(Buffer.concat(chunks)));
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || !isDeepStrictEqual(Object.keys(value).sort(), ['binary', 'inputs', 'supervisor_config', 'work_dir', 'writer_config'])
    || typeof value.binary !== 'string' || typeof value.work_dir !== 'string'
    || !value.inputs || !Array.isArray(value.inputs.expected_points)) throw new Error('input_shape');
  return value;
}
function completed(raw) {
  const value = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(Buffer.from(raw)));
  if (value?.status !== 'ok' || value?.result?.status !== 'completed') throw new Error('write_not_completed');
}
async function expected(types, operation) {
  const allowed = Array.isArray(types) ? types : [types];
  try { await operation(); } catch (error) {
    if (allowed.some(Type => error instanceof Type)) return;
    throw error;
  }
  throw new Error('expected_failure_missing');
}
async function observedListener(address, absent = false) {
  const parsed = new URL(address);
  if (parsed.protocol !== 'http:' || parsed.hostname !== '127.0.0.1' || !parsed.port
    || parsed.origin !== address) throw new Error('endpoint_shape');
  return new Promise((resolve, reject) => {
    execFile('/usr/sbin/lsof', ['-nP', '-a', '-iTCP@127.0.0.1:' + parsed.port, '-sTCP:LISTEN', '-t'],
      {encoding: 'utf8', env: {PATH: '/usr/bin:/bin'}, maxBuffer: 1024, timeout: 3000, killSignal: 'SIGKILL'},
      (error, stdout, stderr) => {
        if (absent && error?.code === 1 && stdout === '' && stderr === '') return resolve(null);
        if (error || stderr || absent || !/^[1-9][0-9]{0,9}\n?$/.test(stdout)) return reject(new Error('listener_observation'));
        resolve(Number(stdout.trim()));
      });
  });
}
async function credentials(config, options) {
  return bounded((async () => {
    const file = await open(config.passfile, constants.O_RDONLY | constants.O_NOFOLLOW);
    let contents;
    try {
      const info = await file.stat();
      if (!info.isFile() || info.size > 65536 || info.uid !== process.getuid?.() || (info.mode & 0o077)) throw new Error('passfile_shape');
      contents = await file.readFile('utf8');
    } finally { await file.close(); }
    const lines = contents.split(/\r?\n/).filter(Boolean);
    if (lines.length !== 1 || lines[0].includes('\\')) throw new Error('passfile_shape');
    const fields = lines[0].split(':');
    if (fields.length !== 5 || fields.slice(0, 4).join(':') !== [config.host, String(config.port), config.dbname, config.user].join(':')
      || !/^[A-Za-z0-9._~-]+$/.test(fields[4])) throw new Error('passfile_shape');
    const ca = await stat(config.sslrootcert);
    if (!ca.isFile() || ca.size > 1048576) throw new Error('ca_shape');
    return {password: fields[4], ca: await readFile(config.sslrootcert, 'utf8')};
  })(), options);
}

async function cases(value) {
  const inputs = value.inputs;
  const writerConfig = parse_pool_config(value.writer_config);
  const supervisorConfig = parse_pool_config(value.supervisor_config);
  if (writerConfig.max_size !== 1) throw new Error('two_client_ceiling');
  const resource = new PoolResource(writerConfig);
  const writer = new PostgresQdrantWriter(resource, inputs.config, inputs.instance_id);
  const supervisor = new ManagedQdrantSupervisor(value.binary, value.work_dir, inputs.instance_id, inputs.config);
  const options = {deadline: now() + 100, signal: cancellation.signal};
  const ctx = {scope: inputs.scope, collection: inputs.stage.manifest.collection,
    document_id: inputs.stage.manifest.document_id, intent_id: inputs.stage.intent.intent_id, owner_token: OWNER_TOKEN};
  const target = '/collections/' + inputs.config.physical_collection;
  const checks = [];
  let client, handle, ordinary, endpoint, primary;
  const destroyConnection = () => client?.connection?.stream?.destroy();
  const query = async (text, values = [], cleanup = false) => {
    const limit = cleanup ? {deadline: now() + 2} : options;
    const result = await bounded(client.query({text, values, rowMode: 'array'}), limit, destroyConnection);
    return result.rows;
  };
  async function sup(text, values = []) {
    let begun = false;
    try {
      await query('BEGIN ISOLATION LEVEL READ COMMITTED'); begun = true;
      await query('SET LOCAL search_path=pg_catalog');
      await query("SELECT set_config('cragkit_qdrant.backend_instance_id',$1,true)", [inputs.instance_id]);
      const rows = await query(text, values);
      await query('COMMIT'); begun = false;
      return rows;
    } finally {
      if (begun) {
        try { await query('ROLLBACK', [], true); }
        catch { destroyConnection(); }
      }
    }
  }
  async function quarantined() {
    const state = await sup('SELECT state,epoch::text,recovery_id FROM cragkit_qdrant.backend_instances WHERE instance_id=$1', [inputs.instance_id]);
    const journal = await sup('SELECT state FROM cragkit_qdrant.dispatch_journal WHERE instance_id=$1 AND dispatch_id=$2', [inputs.instance_id, 'e2a-lost-ack']);
    if (!isDeepStrictEqual(state, [['recovery_blocked', '2', 'e2a-native']])
      || !isDeepStrictEqual(journal, [['unknown']])) throw new Error('quarantine_changed');
  }
  async function provision(admin, probe) {
    await admin.request('PUT', target, {...options, body: bytes(inputs.collection_config)});
    await admin.request('PUT', '/collections/' + probe.collection, {...options, body: bytes(probe.collection_config)});
    completed(await admin.request('PUT', '/collections/' + probe.collection + '/points?wait=true&ordering=strong',
      {...options, body: bytes({points: [probe.point]})}));
  }
  async function faultPoints(points) {
    // Explicit fixture intervention: this is not a journaled production replay.
    completed(await handle.request('PUT', target + '/points?wait=true&ordering=strong', {...options, body: bytes({points})}));
  }
  async function deletePoints(ids) {
    completed(await handle.request('POST', target + '/points/delete?wait=true&ordering=strong', {...options, body: bytes({points: ids})}));
  }
  try {
    phase = 'initialize';
    await supervisor.initialize({...options, provision});
    const identity = supervisor.identity();
    endpoint = identity.endpoint;
    await observedListener(endpoint);
    const require = createRequire(new URL('../packages/typescript/package.json', import.meta.url));
    const {Client} = require('pg');
    const secret = await credentials(supervisorConfig, options);
    client = new Client({host: supervisorConfig.host, port: supervisorConfig.port, database: supervisorConfig.dbname,
      user: supervisorConfig.user, password: secret.password, ssl: verified_tls_options(supervisorConfig.host, secret.ca),
      connectionTimeoutMillis: 3000, options: '-c statement_timeout=10000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=15000'});
    client.on('error', () => {});
    cancellation.signal.addEventListener('abort', destroyConnection, {once: true});
    await bounded(client.connect(), options, destroyConnection);
    const role = await query("SELECT current_user=session_user,rolcanlogin AND NOT(rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication),pg_has_role(current_user,'cragkit_qdrant_supervisor','USAGE'),NOT pg_has_role(current_user,'cragkit_qdrant_writer','MEMBER'),(SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()) FROM pg_roles WHERE rolname=current_user");
    if (!isDeepStrictEqual(role, [[true, true, true, true, true]])) throw new Error('supervisor_login_boundary');
    await sup('INSERT INTO cragkit_qdrant.backend_instances(instance_id,backend_namespace,storage_identity,supervisor_id) VALUES($1,$2,$3,$4)',
      [inputs.instance_id, inputs.config.backend_namespace, identity.storage_identity, identity.supervisor_id]);
    await resource.open();
    await writer.initialize(options);

    phase = 'stage';
    await writer.stage(prepare_stage(inputs.stage), inputs.scope, {...options, owner_token: OWNER_TOKEN});
    await expected(IntegrityViolation, () => writer.stage(prepare_stage(inputs.conflicting_stage), inputs.scope, {...options, owner_token: OWNER_TOKEN}));
    const intact = await writer.load_stage(ctx, options);
    if (intact.member_count !== inputs.expected_points.length) throw new Error('generation_members_changed');
    checks.push(CHECKS[0]);
    await writer.acquire_owner(ctx, options);
    const binding = {intent_id: ctx.intent_id, owner_token: OWNER_TOKEN, epoch: 1, dispatch_id: 'e2a-lost-ack'};
    const cap = supervisor.issue_attempt(binding, options);
    ordinary = supervisor.transport_for(cap);
    const reservation = await writer.reserve_dispatch(ctx, {dispatch_id: binding.dispatch_id, sequence: 1,
      credential_generation: supervisor.attempt_binding(cap).credential_generation,
      operation: 'complete_point_upsert', point_ids: inputs.expected_points.map(point => point.id)}, options);
    await writer.mark_dispatched(ctx, binding.dispatch_id, options);
    phase = 'lost_ack';
    completed(await ordinary.request('PUT', target + '/points?wait=true&ordering=strong', {...options, body: reservation.request_bytes}));
    await writer.mark_unknown(ctx, binding.dispatch_id, options);
    await ordinary.close();
    ordinary = undefined;
    const unknown = await sup('SELECT state FROM cragkit_qdrant.dispatch_journal WHERE instance_id=$1 AND dispatch_id=$2', [inputs.instance_id, binding.dispatch_id]);
    if (!isDeepStrictEqual(unknown, [['unknown']])) throw new Error('lost_ack_not_unknown');
    checks.push(CHECKS[1]);

    phase = 'physical_recovery';
    await sup("UPDATE cragkit_qdrant.backend_instances SET state='recovery_blocked',epoch=2,recovery_id=$2 WHERE instance_id=$1", [inputs.instance_id, 'e2a-native']);
    const proof = await supervisor.recover({recovery_id: 'e2a-native', old_epoch: 1, new_epoch: 2}, options);
    const ownerEpoch = await sup('UPDATE cragkit_qdrant.document_owners SET backend_epoch=2 WHERE instance_id=$1 AND tenant_id=$2 AND collection=$3 AND document_id=$4 AND owner_token=$5 AND intent_id=$6 RETURNING backend_epoch::text',
      [inputs.instance_id, ctx.scope.tenant_id, ctx.collection, ctx.document_id, OWNER_TOKEN, ctx.intent_id]);
    if (!isDeepStrictEqual(ownerEpoch, [['2']])) throw new Error('same_owner_epoch_not_advanced');
    await quarantined();
    checks.push(CHECKS[2]);

    phase = 'verify';
    const verifier = new QdrantReconciliationVerifier(writer, supervisor);
    const receipt = await verifier.verify(proof, ctx, options);
    const witness = structuredClone(receipt_data(receipt, verifier).witness);
    for (const index of [2, 3, 7]) witness[index] = '<native-identity>';
    const witnessDigest = createHash('sha256').update(JSON.stringify(witness)).digest('hex');
    await quarantined();
    checks.push(CHECKS[3]);
    await expected(UnsupportedCapability, () => verifier.verify(JSON.parse(JSON.stringify(supervisor.recovery_binding(proof))), ctx, options));
    await quarantined();
    checks.push(CHECKS[4]);
    await expected(InvalidRequest, () => receipt_data(JSON.parse(JSON.stringify(receipt)), verifier));
    await quarantined();
    checks.push(CHECKS[5]);
    const recoveryCap = supervisor.issue_recovery_attempt(proof, {...binding, epoch: 2,
      recovery_id: 'e2a-native', dispatch_id: 'e2a-fault-injection'}, options);
    handle = supervisor.transport_for(recoveryCap);
    const original = structuredClone(inputs.expected_points);

    phase = 'wrong_membership';
    const foreign = structuredClone(original[0]);
    foreign.id = '00000000-0000-4000-8000-000000000099';
    await deletePoints([original[0].id]);
    await faultPoints([foreign]);
    await expected(IntegrityViolation, () => verifier.verify(proof, ctx, options));
    await quarantined();
    await deletePoints([foreign.id]);
    await faultPoints(original);
    checks.push(CHECKS[6]);
    const mutations = [
      point => { point.vector.dense.reverse(); },
      point => { point.vector.sparse.values[0] += 0.25; },
      point => { delete point.vector.sparse; },
      point => { point.payload.dense_profile.model = 'wrong-profile'; },
    ];
    for (let index = 0; index < mutations.length; index++) {
      phase = ['wrong_dense', 'wrong_sparse', 'missing_vector', 'wrong_profile'][index];
      const changed = structuredClone(original);
      mutations[index](changed[0]);
      await faultPoints(changed);
      await expected(IntegrityViolation, () => verifier.verify(proof, ctx, options));
      await quarantined();
      await faultPoints(original);
      checks.push(CHECKS[7 + index]);
    }

    phase = 'authorization_change';
    const security = {action: 'update_authorization', intent_id: 'e2a-authority-change',
      tenant_id: ctx.scope.tenant_id, collection: ctx.collection, document_id: ctx.document_id,
      expected_authorization_revision: ctx.scope.authorization_revision, expected_mutation_epoch: 1,
      authorization: {authorization_revision: 'auth-e2a-2', principal_ids: ['reader-b'], grant_ids: [],
        language: null, kind: null, tag: 'current', tombstoned: false}};
    await writer.apply_security(security, inputs.scope, {...options, owner_token: OWNER_TOKEN});
    await expected(UnauthorizedScope, () => verifier.verify(proof, ctx, options));
    const fresh = {...inputs.scope, authorization_revision: 'auth-e2a-2'};
    const current = {...ctx, scope: fresh};
    await expected(IntegrityViolation, () => verifier.verify(proof, current, options));
    await quarantined();
    checks.push(CHECKS[11]);
    for (const point of original) {
      Object.assign(point.payload, {authorization_revision: 'auth-e2a-2', principal_ids: ['reader-b'], grant_ids: [], tag: 'current'});
      delete point.payload.language;
      delete point.payload.kind;
    }
    await faultPoints(original);
    await verifier.verify(proof, current, options);
    checks.push(CHECKS[12]);
    const projection = await writer.project_stage(current, supervisor.recovery_binding(proof), options);

    phase = 'projection_change';
    const tombstone = {...security, action: 'tombstone', intent_id: 'e2a-tombstone',
      expected_authorization_revision: 'auth-e2a-2', expected_mutation_epoch: 2,
      authorization: {authorization_revision: 'auth-e2a-3', principal_ids: [], grant_ids: [],
        language: null, kind: null, tag: null, tombstoned: true}};
    await writer.apply_security(tombstone, fresh, {...options, owner_token: OWNER_TOKEN});
    await expected([IntegrityViolation, UnauthorizedScope], () => writer.validate_projection(projection, options));
    await quarantined();
    checks.push(CHECKS[13]);

    phase = 'tombstone_absence';
    const dead = {...ctx, scope: {...inputs.scope, authorization_revision: 'auth-e2a-3'}};
    await expected(IntegrityViolation, () => verifier.verify(proof, dead, options));
    await quarantined();
    await deletePoints(original.map(point => point.id));
    await verifier.verify(proof, dead, options);
    checks.push(CHECKS[14]);
    const extra = structuredClone(original[0]);
    extra.id = '00000000-0000-4000-8000-000000000098';
    extra.payload.dense_profile.model = 'wrong-profile';
    await faultPoints([extra]);
    await expected(IntegrityViolation, () => verifier.verify(proof, dead, options));
    await quarantined();
    await deletePoints([extra.id]);
    await verifier.verify(proof, dead, options);
    checks.push(CHECKS[15]);
    await expected(ProviderUnavailable, () => handle.request('GET', '/', {...options, max_response_bytes: 1}));
    checks.push(CHECKS[16]);
    await quarantined();
    checks.push(CHECKS[17]);
    return {runtime: 'typescript', checks, proof_scope: 'authority_bound_readback_only', normalized_witness_sha256: witnessDigest};
  } catch (error) {
    primary = error;
    throw error;
  } finally {
    step = checks.length;
    cancellation.signal.removeEventListener('abort', destroyConnection);
    const failures = [];
    const owned = [['transport_close', handle], ['transport_close', ordinary], ['writer_close', writer],
      ['resource_close', resource], ['supervisor_connection_close', client], ['controller_close', supervisor]];
    for (const [operation, value] of owned) {
      if (!value) continue;
      try {
        const close = operation === 'supervisor_connection_close' ? value.end() : value.close();
        await bounded(Promise.resolve(close), {deadline: now() + 8});
      } catch (error) { failures.push({operation, outcome: outcome(error)}); }
    }
    if (endpoint) {
      try { await observedListener(endpoint, true); }
      catch (error) { failures.push({operation: 'listener_close', outcome: outcome(error)}); }
    }
    if (failures.length) throw new RuntimeCleanupFailure(primary, failures);
  }
}

try {
  const value = await bounded(input(), {deadline: now() + 5, signal: cancellation.signal});
  process.stdout.write(JSON.stringify(await cases(value)) + '\n');
} catch (error) {
  process.stdin.destroy();
  // Emit closed labels only, including when a primary error and cleanup both fail.
  process.stdout.write(JSON.stringify({ok: false, step,
    error: error instanceof RuntimeCleanupFailure ? 'cleanup_failed' : outcome(error),
    ...(error instanceof RuntimeCleanupFailure ? {primary: error.primary, cleanup: error.failures} : {})}) + '\n');
  process.exitCode = 1;
}
