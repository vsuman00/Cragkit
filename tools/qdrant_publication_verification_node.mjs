/** F1 native ordinary readback primitives, not production dispatch/publication. */
import {execFile} from 'node:child_process';
import {createHash} from 'node:crypto';
import {constants} from 'node:fs';
import {open, readFile, stat} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {isDeepStrictEqual} from 'node:util';
import {PoolResource, parse_pool_config, bounded, now, verified_tls_options} from '../packages/typescript/dist/postgres-pool.js';
import {ManagedQdrantSupervisor} from '../packages/typescript/dist/qdrant-supervisor.js';
import {PostgresQdrantWriter, prepare_stage} from '../packages/typescript/dist/qdrant-writer.js';
import {QdrantPublicationVerifier, publication_receipt_data} from '../packages/typescript/dist/qdrant-publication-verification.js';
import {IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability} from '../packages/typescript/dist/errors.js';

const OWNER = '00000000-0000-4000-8000-000000000001';
const CHECKS = Object.freeze([
  'native_registration_and_atomic_stage',
  'pending_dispatch_refuses_before_http',
  'actual_completed_ack_primitive_settlement',
  'exact_ordinary_current_authority_receipt',
  'serialized_attempt_has_no_capability',
  'serialized_receipt_has_no_private_provenance',
  'equal_count_wrong_membership_rejected',
  'same_dimension_wrong_dense_vector_rejected',
  'wrong_sparse_vector_rejected',
  'missing_named_sparse_vector_rejected',
  'wrong_full_profile_payload_rejected',
  'projection_invalidated_by_owner_replacement',
  'later_authority_change_invalidates_projection_and_scope',
  'fresh_scope_rejects_stale_acl_replica',
  'fresh_scope_current_acl_readback_verified',
  'actual_transport_enforces_remaining_response_allowance',
  'epoch_advance_retires_ordinary_attempt',
  'recovery_attempt_cannot_mint_ordinary_receipt',
  'readback_never_publishes_or_changes_settled_journal',
]);
const ERRORS = new Set(['IntegrityViolation', 'UnauthorizedScope', 'UnsupportedCapability',
  'InvalidRequest', 'ProviderUnavailable', 'DeadlineExceeded', 'IndexNotReady']);
const cancellation = new AbortController();
let readingInput = true;
let step = 0;
const cancel = () => { cancellation.abort(); if (readingInput) process.stdin.destroy(); };
process.on('SIGTERM', cancel);
process.on('SIGINT', cancel);
const bytes = value => [...Buffer.from(JSON.stringify(value), 'utf8')];
const hash = value => createHash('sha256').update(Buffer.from(value)).digest('hex');

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
    || typeof value.binary !== 'string' || typeof value.work_dir !== 'string' || !value.inputs
    || !Array.isArray(value.inputs.expected_points)) throw new Error('input_shape');
  return value;
}
async function expected(Type, operation) {
  try { await operation(); } catch (error) { if (error instanceof Type) return; throw error; }
  throw new Error('expected_failure_missing');
}
function completed(raw) {
  const value = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(Buffer.from(raw)));
  if (value?.status !== 'ok' || value?.result?.status !== 'completed') throw new Error('write_not_completed');
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
  const writerConfig = parse_pool_config(value.writer_config), supervisorConfig = parse_pool_config(value.supervisor_config);
  if (writerConfig.max_size !== 1) throw new Error('two_client_ceiling');
  const resource = new PoolResource(writerConfig);
  const writer = new PostgresQdrantWriter(resource, inputs.config, inputs.instance_id);
  const supervisor = new ManagedQdrantSupervisor(value.binary, value.work_dir, inputs.instance_id, inputs.config);
  const verifier = new QdrantPublicationVerifier(writer, supervisor);
  const options = {deadline: now() + 100, signal: cancellation.signal};
  const context = {scope: inputs.scope, collection: inputs.stage.manifest.collection,
    document_id: inputs.stage.manifest.document_id, intent_id: inputs.stage.intent.intent_id, owner_token: OWNER};
  const target = '/collections/' + inputs.config.physical_collection;
  const checks = [];
  let client, handle, address, primary;
  const destroyConnection = () => client?.connection?.stream?.destroy();
  const query = async (text, values = [], cleanup = false) => {
    const result = await bounded(client.query({text, values, rowMode: 'array'}),
      cleanup ? {deadline: now() + 2} : options, destroyConnection);
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
  async function provision(admin, probe) {
    await admin.request('PUT', target, {...options, body: bytes(inputs.collection_config)});
    const probeTarget = '/collections/' + probe.collection;
    await admin.request('PUT', probeTarget, {...options, body: bytes(probe.collection_config)});
    completed(await admin.request('PUT', probeTarget + '/points?wait=true&ordering=strong',
      {...options, body: bytes({points: [probe.point]})}));
  }
  async function faultPoints(points) {
    // Explicit bounded fixture intervention, never a production dispatch.
    completed(await handle.request('PUT', target + '/points?wait=true&ordering=strong', {...options, body: bytes({points})}));
  }
  async function deletePoints(ids) {
    completed(await handle.request('POST', target + '/points/delete?wait=true&ordering=strong', {...options, body: bytes({points: ids})}));
  }
  try {
    await supervisor.initialize({...options, provision});
    const identity = supervisor.identity();
    address = identity.endpoint;
    await observedListener(address);
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
    await resource.open(); await writer.initialize(options);
    await writer.stage(prepare_stage(inputs.stage), inputs.scope, {...options, owner_token: OWNER});
    await writer.acquire_owner(context, options);
    checks.push(CHECKS[0]);

    const binding = {intent_id: context.intent_id, owner_token: OWNER, epoch: 1, dispatch_id: 'f1-completed-ack'};
    const attempt = supervisor.issue_attempt(binding, options);
    handle = supervisor.transport_for(attempt);
    const reservation = await writer.reserve_dispatch(context, {dispatch_id: binding.dispatch_id, sequence: 1,
      credential_generation: supervisor.attempt_binding(attempt).credential_generation,
      operation: 'complete_point_upsert', point_ids: inputs.expected_points.map(point => point.id)}, options);
    const actualTransportFor = supervisor.transport_for.bind(supervisor);
    let transportCalls = 0;
    supervisor.transport_for = capability => { transportCalls++; return actualTransportFor(capability); };
    await expected(ProviderUnavailable, () => verifier.verify(attempt, context, options));
    if (transportCalls !== 0) throw new Error('pending_verification_started_transport');
    checks.push(CHECKS[1]);
    await writer.mark_dispatched(context, binding.dispatch_id, options);
    const acknowledgement = await handle.request('PUT', target + '/points?wait=true&ordering=strong', {...options, body: reservation.request_bytes});
    completed(acknowledgement);
    // Primitive fixture settlement after the actual completed acknowledgment.
    await writer.settle_dispatch(context, binding.dispatch_id, hash(acknowledgement), options);
    checks.push(CHECKS[2]);
    const receipt = await verifier.verify(attempt, context, options);
    const data = publication_receipt_data(receipt, verifier);
    const witness = structuredClone(data.witness);
    if (witness.length !== 21 || data.readback_sha256 !== hash(data.encoded_bytes)) throw new Error('receipt_witness_shape');
    for (const index of [2, 3, 5]) witness[index] = '<native-identity>';
    const witnessDigest = hash(bytes(witness));
    checks.push(CHECKS[3]);
    await expected(InvalidRequest, () => verifier.verify(JSON.parse(JSON.stringify(supervisor.attempt_binding(attempt))), context, options));
    checks.push(CHECKS[4]);
    await expected(InvalidRequest, () => publication_receipt_data({}, verifier));
    checks.push(CHECKS[5]);

    const original = structuredClone(inputs.expected_points);
    const foreign = structuredClone(original[0]);
    foreign.id = '00000000-0000-4000-8000-000000000099';
    await deletePoints([original[0].id]);
    await faultPoints([foreign]);
    await expected(IntegrityViolation, () => verifier.verify(attempt, context, options));
    await deletePoints([foreign.id]); await faultPoints(original);
    checks.push(CHECKS[6]);
    const mutations = [
      point => { point.vector.dense.reverse(); },
      point => { point.vector.sparse.values[0] += 0.25; },
      point => { delete point.vector.sparse; },
      point => { point.payload.dense_profile.model = 'wrong-profile'; },
    ];
    for (let index = 0; index < mutations.length; index++) {
      const changed = structuredClone(original); mutations[index](changed[0]);
      await faultPoints(changed);
      await expected(IntegrityViolation, () => verifier.verify(attempt, context, options));
      await faultPoints(original);
      checks.push(CHECKS[7 + index]);
    }

    const ownerProjection = await writer.project_publication(context, supervisor.attempt_binding(attempt), options);
    await writer.acquire_owner({...context, owner_token: '00000000-0000-4000-8000-000000000002'}, options);
    await expected(ProviderUnavailable, () => writer.validate_publication_projection(ownerProjection, options));
    await writer.acquire_owner(context, options);
    checks.push(CHECKS[11]);
    const authorityProjection = await writer.project_publication(context, supervisor.attempt_binding(attempt), options);
    const security = {action: 'update_authorization', intent_id: 'f1-authority-change',
      tenant_id: context.scope.tenant_id, collection: context.collection, document_id: context.document_id,
      expected_authorization_revision: context.scope.authorization_revision, expected_mutation_epoch: 1,
      authorization: {authorization_revision: 'auth-f1-2', principal_ids: ['reader-b'], grant_ids: [],
        language: null, kind: null, tag: 'current', tombstoned: false}};
    await writer.apply_security(security, inputs.scope, {...options, owner_token: OWNER});
    await expected(UnauthorizedScope, () => writer.validate_publication_projection(authorityProjection, options));
    await expected(UnauthorizedScope, () => verifier.verify(attempt, context, options));
    checks.push(CHECKS[12]);
    const freshScope = {...inputs.scope, authorization_revision: 'auth-f1-2'};
    const current = {...context, scope: freshScope};
    await expected(IntegrityViolation, () => verifier.verify(attempt, current, options));
    checks.push(CHECKS[13]);
    for (const point of original) {
      Object.assign(point.payload, {authorization_revision: 'auth-f1-2', principal_ids: ['reader-b'], grant_ids: [], tag: 'current'});
      delete point.payload.language; delete point.payload.kind;
    }
    await faultPoints(original);
    await verifier.verify(attempt, current, options);
    checks.push(CHECKS[14]);
    await expected(ProviderUnavailable, () => handle.request('GET', '/', {...options, max_response_bytes: 1}));
    checks.push(CHECKS[15]);
    await handle.close(); handle = undefined;

    await sup("UPDATE cragkit_qdrant.backend_instances SET state='recovery_blocked',epoch=2,recovery_id='f1-native' WHERE instance_id=$1", [inputs.instance_id]);
    const proof = await supervisor.recover({recovery_id: 'f1-native', old_epoch: 1, new_epoch: 2}, options);
    await expected(ProviderUnavailable, () => verifier.verify(attempt, current, options));
    checks.push(CHECKS[16]);
    const recoveryAttempt = supervisor.issue_recovery_attempt(proof, {...binding, epoch: 2,
      recovery_id: 'f1-native', dispatch_id: 'f1-recovery-readback'}, options);
    await expected(UnsupportedCapability, () => verifier.verify(recoveryAttempt, current, options));
    checks.push(CHECKS[17]);
    const backend = await sup('SELECT state,epoch::text FROM cragkit_qdrant.backend_instances WHERE instance_id=$1', [inputs.instance_id]);
    const journals = await sup('SELECT state FROM cragkit_qdrant.dispatch_journal WHERE instance_id=$1', [inputs.instance_id]);
    const staged = await writer.inspect(current, options);
    if (!isDeepStrictEqual(backend, [['recovery_blocked', '2']]) || !isDeepStrictEqual(journals, [['settled']])
      || !staged || staged.state !== 'writing' || staged.authority_committed || staged.replica_complete) throw new Error('readback_changed_publication_state');
    await resource.withLease(options, async (lease, signal) => {
      const leaseOptions = {deadline: options.deadline, signal};
      const read = async (text, values = []) => (await bounded(lease.query({text, values, rowMode: 'array'}), leaseOptions)).rows;
      let begun = false;
      try {
        await read('BEGIN ISOLATION LEVEL READ COMMITTED'); begun = true;
        await read("SELECT set_config('cragkit_qdrant.tenant_id',$1,true),set_config('cragkit_qdrant.collection',$2,true),set_config('cragkit_qdrant.principal_id',$3,true),set_config('cragkit_qdrant.grant_ids',$4,true),set_config('cragkit_qdrant.authorization_revision',$5,true),set_config('cragkit_qdrant.writer_document_id',$6,true),set_config('cragkit_qdrant.writer_intent_id',$7,true),set_config('cragkit_qdrant.writer_owner_token',$8,true),set_config('cragkit_qdrant.backend_instance_id',$9,true)",
          [freshScope.tenant_id, current.collection, freshScope.principal_id, JSON.stringify(freshScope.grant_ids),
            freshScope.authorization_revision, current.document_id, current.intent_id, OWNER, inputs.instance_id]);
        const targetValues = [freshScope.tenant_id, current.collection, current.document_id];
        const where = ' WHERE (tenant_id,collection,document_id)=($1,$2,$3)';
        if (!isDeepStrictEqual(await read('SELECT active_generation_id FROM cragkit_qdrant.documents' + where, targetValues), [[null]])
          || !isDeepStrictEqual(await read('SELECT published,ever_published FROM cragkit_qdrant.generations' + where, targetValues), [[false, false]])) throw new Error('readback_published_source');
        await read('COMMIT'); begun = false;
      } finally {
        if (begun) {
          try { await bounded(lease.query({text: 'ROLLBACK', rowMode: 'array'}), {deadline: now() + 2}); }
          catch { lease.release(true); }
        }
      }
    });
    checks.push(CHECKS[18]);
    return {runtime: 'typescript', checks, proof_scope: 'ordinary_readback_only', normalized_witness_sha256: witnessDigest};
  } catch (error) { primary = error; throw error; }
  finally {
    step = checks.length;
    cancellation.signal.removeEventListener('abort', destroyConnection);
    const failures = [];
    for (const [operation, owned, method] of [['transport_close', handle, 'close'], ['verifier_close', verifier, 'close'],
      ['writer_close', writer, 'close'], ['resource_close', resource, 'close'],
      ['supervisor_connection_close', client, 'end'], ['controller_close', supervisor, 'close']]) {
      if (!owned) continue;
      try { await bounded(Promise.resolve().then(() => owned[method]()), {deadline: now() + 8}); }
      catch (error) { failures.push({operation, outcome: outcome(error)}); }
    }
    if (address) {
      try { await observedListener(address, true); }
      catch (error) { failures.push({operation: 'listener_close', outcome: outcome(error)}); }
    }
    if (failures.length) throw new RuntimeCleanupFailure(primary, failures);
  }
}

try {
  const value = await bounded(input(), {deadline: now() + 5, signal: cancellation.signal});
  readingInput = false;
  process.stdout.write(JSON.stringify(await cases(value)) + '\n');
} catch (error) {
  process.stdin.destroy();
  process.stdout.write(JSON.stringify({ok: false, step,
    error: error instanceof RuntimeCleanupFailure ? 'cleanup_failed' : outcome(error),
    ...(error instanceof RuntimeCleanupFailure ? {primary: error.primary, cleanup: error.failures} : {})}) + '\n');
  process.exitCode = 1;
}
