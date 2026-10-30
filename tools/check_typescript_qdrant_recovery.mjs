/** Actual E2b SQL/HTTP observations. Fixture interventions are not production replay. */
import {execFile} from 'node:child_process';
import {createHash} from 'node:crypto';
import {constants} from 'node:fs';
import {open, readFile, stat} from 'node:fs/promises';
import http from 'node:http';
import {createRequire} from 'node:module';
import {isDeepStrictEqual} from 'node:util';
import {PoolResource, parse_pool_config, bounded, now, verified_tls_options} from '../packages/typescript/dist/postgres-pool.js';
import {ManagedQdrantSupervisor} from '../packages/typescript/dist/qdrant-supervisor.js';
import {PostgresQdrantWriter, prepare_stage, writer_binding} from '../packages/typescript/dist/qdrant-writer.js';
import {QdrantReconciliationVerifier, receipt_data} from '../packages/typescript/dist/qdrant-reconciliation.js';
import {PostgresQdrantRecovery, recovery_components} from '../packages/typescript/dist/qdrant-recovery.js';
import {InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability} from '../packages/typescript/dist/errors.js';

const OWNER = '00000000-0000-4000-8000-000000000001';
const SECOND_OWNER = '00000000-0000-4000-8000-000000000002';
const THIRD_OWNER = '00000000-0000-4000-8000-000000000003';
const CHECKS = Object.freeze([
  'actual_native_instance_registered_with_restricted_supervisor_login',
  'two_documents_have_real_journaled_writes_with_lost_acknowledgments',
  'durable_instance_block_commits_before_actual_physical_fencing',
  'captured_old_key_is_denied_after_same_storage_restart',
  'fabricated_physical_proofs_cannot_authorize_recovery_or_clear_unknowns',
  'recovery_owner_advance_preserves_exact_token_and_rejects_wrong_owner',
  'copied_receipt_cannot_authorize_sql_settlement',
  'retired_readback_settles_only_the_authorized_document',
  'another_document_uncertainty_keeps_sql_and_native_admission_closed',
  'same_recovery_identity_refences_without_advancing_blocked_sql_epoch',
  'second_authorized_document_settles_without_invented_scope',
  'actual_current_generation_write_remains_unknown_in_durable_journal',
  'current_generation_readback_cannot_clear_a_possible_late_write',
  'current_generation_uncertainty_prevents_reopening',
  'another_actual_same_identity_fence_retires_the_unknown_generation',
  'retired_settlement_retry_is_idempotent',
  'shared_supervisor_session_blocks_competing_coordinator_and_raw_mutations',
  'released_session_allows_same_identity_refence_and_manager_handoff',
  'actual_sql_open_commit_lost_ack_reconciles_with_native_gate_sealed',
  'private_sql_handoff_resumes_actual_ordinary_reads_at_current_epoch',
  'next_recovery_identity_advances_a_fresh_epoch_and_reopens_privately',
  'recovery_never_publishes_or_marks_replica_completion',
  'backend_wide_recovery_gate_allows_independent_revocation',
]);
const ERRORS = new Set(['InvalidRequest', 'ProviderUnavailable', 'UnsupportedCapability', 'DeadlineExceeded',
  'IndexNotReady', 'IntegrityViolation', 'UnauthorizedScope']);
let step = 0;
let readingInput = true;
const cancellation = new AbortController();
const cancel = () => { cancellation.abort(); if (readingInput) process.stdin.destroy(); };
process.on('SIGTERM', cancel);
process.on('SIGINT', cancel);
const bytes = value => [...Buffer.from(JSON.stringify(value), 'utf8')];
const digest = value => createHash('sha256').update(Buffer.from(value)).digest('hex');
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
    || !Array.isArray(value.inputs.expected_points) || !Array.isArray(value.inputs.second_points)) throw new Error('input_shape');
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
function endpoint(value) {
  const parsed = new URL(value);
  if (parsed.protocol !== 'http:' || parsed.hostname !== '127.0.0.1' || !parsed.port
    || parsed.origin !== value) throw new Error('endpoint_shape');
  return parsed;
}
async function observedListener(address, absent = false) {
  const parsed = endpoint(address);
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
async function oldKeyStatus(credential, path, body, signal) {
  const address = endpoint(credential.endpoint);
  if (!/^[0-9a-f]{64}$/.test(credential.api_key) || signal.aborted) throw new ProviderUnavailable();
  return new Promise((resolve, reject) => {
    let request, finished = false;
    const finish = (error, status) => {
      if (finished) return;
      finished = true; clearTimeout(timer); signal.removeEventListener('abort', abort);
      if (error) reject(new Error('old_key_request_failed')); else resolve(status);
    };
    const abort = () => request?.destroy(new Error('request_cancelled'));
    const timer = setTimeout(() => request?.destroy(new Error('request_deadline')), 3000);
    request = http.request({hostname: '127.0.0.1', port: Number(address.port), method: 'PUT', path,
      agent: false, maxHeaderSize: 16384, headers: {'api-key': credential.api_key,
        'content-type': 'application/json', 'content-length': body.length}}, response => {
      let size = 0;
      response.on('data', chunk => { size += chunk.length; if (size > 1024) response.destroy(new Error('bounded_response')); });
      response.once('end', () => finish(null, response.statusCode));
      response.once('error', () => finish(new Error('response_failed')));
      response.once('aborted', () => finish(new Error('response_aborted')));
    });
    request.once('error', () => finish(new Error('request_failed')));
    signal.addEventListener('abort', abort, {once: true});
    if (signal.aborted) abort();
    request.end(body);
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
  if (writerConfig.max_size !== 1 || supervisorConfig.max_size !== 1) throw new Error('two_client_ceiling');
  const options = {deadline: now() + 140, signal: cancellation.signal};
  const resource = new PoolResource(writerConfig);
  const writer = new PostgresQdrantWriter(resource, inputs.config, inputs.instance_id);
  const supervisor = new ManagedQdrantSupervisor(value.binary, value.work_dir, inputs.instance_id, inputs.config);
  const verifier = new QdrantReconciliationVerifier(writer, supervisor);
  const ctx = {scope: inputs.scope, collection: inputs.stage.manifest.collection, document_id: inputs.stage.manifest.document_id,
    intent_id: inputs.stage.intent.intent_id, owner_token: OWNER};
  const second = {scope: inputs.second_scope, collection: inputs.second_stage.manifest.collection,
    document_id: inputs.second_stage.manifest.document_id, intent_id: inputs.second_stage.intent.intent_id, owner_token: SECOND_OWNER};
  const third = {scope: inputs.third_scope, collection: inputs.third_stage.manifest.collection,
    document_id: inputs.third_stage.manifest.document_id, intent_id: inputs.third_stage.intent.intent_id, owner_token: THIRD_OWNER};
  const thirdFresh = {...third, scope: {...third.scope, authorization_revision: 'auth-e2b-third-2'}};
  const target = '/collections/' + inputs.config.physical_collection;
  const checks = [], handles = new Set(), oldCredential = {};
  const injection = {armed: false, fired: false, boundarySealed: false, openUpdates: 0, freshOpenReads: 0, handoffChecked: false, sqlCalls: 0};
  let supervisorResource, rawPool, recovery, competingRecovery, address, primary;
  let pausePhysical;
  let fenceCount = 0;
  let thirdRevoked = false;
  function ordinaryBlocked(epoch) {
    try {
      supervisor.issue_attempt({intent_id: ctx.intent_id, owner_token: OWNER, epoch, dispatch_id: 'must-remain-blocked'}, options);
    } catch (error) { if (error instanceof ProviderUnavailable) return; throw error; }
    throw new Error('ordinary_admission_reopened');
  }
  async function provision(admin, probe) {
    await admin.request('PUT', target, {...options, body: bytes(inputs.collection_config)});
    await admin.request('PUT', '/collections/' + probe.collection, {...options, body: bytes(probe.collection_config)});
    completed(await admin.request('PUT', '/collections/' + probe.collection + '/points?wait=true&ordering=strong',
      {...options, body: bytes({points: [probe.point]})}));
  }
  async function sup(operation) {
    return supervisorResource.withLease(options, async (client, signal) => {
      const lease = {deadline: options.deadline, signal};
      const query = async (text, values = []) => (await bounded(client.query({text, values, rowMode: 'array'}), lease)).rows;
      let begun = false;
      try {
        await query('BEGIN ISOLATION LEVEL READ COMMITTED'); begun = true;
        await query('SET LOCAL search_path=pg_catalog');
        await query("SELECT set_config('cragkit_qdrant.backend_instance_id',$1,true)", [inputs.instance_id]);
        const result = await operation(query);
        await query('COMMIT'); begun = false;
        return result;
      } finally {
        if (begun) {
          try { await bounded(client.query({text: 'ROLLBACK', rowMode: 'array'}), {deadline: now() + 2}); }
          catch { client.release(true); }
        }
      }
    });
  }
  const state = () => sup(query => query('SELECT state,epoch::text,recovery_id FROM cragkit_qdrant.backend_instances WHERE instance_id=$1', [inputs.instance_id]));
  const journal = () => sup(query => query('SELECT dispatch_id,state FROM cragkit_qdrant.dispatch_journal WHERE instance_id=$1 ORDER BY dispatch_id', [inputs.instance_id]));
  async function assertBlocked(epoch = 2) {
    if (!isDeepStrictEqual(await state(), [['recovery_blocked', String(epoch), epoch === 2 ? 'e2b-native' : 'e2b-next']])) throw new Error('sql_not_blocked');
    ordinaryBlocked(epoch);
  }
  async function closeHandle(handle) { await handle.close(); handles.delete(handle); }
  async function ordinaryRead(epoch, dispatch_id) {
    const cap = supervisor.issue_attempt({intent_id: ctx.intent_id, owner_token: OWNER, epoch, dispatch_id}, options);
    const handle = supervisor.transport_for(cap); handles.add(handle);
    const raw = await handle.request('GET', target, options);
    const result = JSON.parse(Buffer.from(raw).toString('utf8'));
    if (result?.status !== 'ok') throw new Error('ordinary_read_failed');
    await closeHandle(handle);
  }
  async function lostAck(context, stage, points, dispatch_id, capture = false) {
    await writer.stage(prepare_stage(stage), context.scope, {...options, owner_token: context.owner_token});
    await writer.acquire_owner(context, options);
    const cap = supervisor.issue_attempt({intent_id: context.intent_id, owner_token: context.owner_token, epoch: 1, dispatch_id}, options);
    const handle = supervisor.transport_for(cap); handles.add(handle);
    if (capture) await supervisor.deliver_worker_credential(cap, async credential => Object.assign(oldCredential, credential), options);
    const reservation = await writer.reserve_dispatch(context, {dispatch_id, sequence: 1,
      credential_generation: supervisor.attempt_binding(cap).credential_generation,
      operation: 'complete_point_upsert', point_ids: points.map(point => point.id)}, options);
    await writer.mark_dispatched(context, dispatch_id, options);
    completed(await handle.request('PUT', target + '/points?wait=true&ordering=strong', {...options, body: reservation.request_bytes}));
    await writer.mark_unknown(context, dispatch_id, options);
    await closeHandle(handle);
    return reservation;
  }
  try {
    await supervisor.initialize({...options, provision});
    address = supervisor.identity().endpoint;
    const firstPid = await observedListener(address);
    const require = createRequire(new URL('../packages/typescript/package.json', import.meta.url));
    const {Pool} = require('pg');
    const secret = await credentials(supervisorConfig, options);
    rawPool = new Pool({host: supervisorConfig.host, port: supervisorConfig.port, database: supervisorConfig.dbname,
      user: supervisorConfig.user, password: secret.password, ssl: verified_tls_options(supervisorConfig.host, secret.ca),
      max: 1, min: 1, connectionTimeoutMillis: 3000, idleTimeoutMillis: 10000,
      options: '-c statement_timeout=10000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=15000'});
    rawPool.on('error', () => {});
    const borrowed = {
      async connect() {
        const client = await rawPool.connect();
        let openUpdateInTransaction = false;
        return {
          async query(query) {
            injection.sqlCalls++;
            const text = query.text;
            const result = await client.query(query);
            if (/^BEGIN\b/i.test(text)) openUpdateInTransaction = false;
            if (/UPDATE cragkit_qdrant\.backend_instances SET state='open'/i.test(text)) {
              openUpdateInTransaction = true;
              if (injection.armed || injection.fired) injection.openUpdates++;
            }
            if (injection.fired && /^SELECT instance_id,backend_namespace,storage_identity,supervisor_id,epoch,state,recovery_id FROM cragkit_qdrant\.backend_instances/i.test(text)) {
              if (result.rows.length === 1 && String(result.rows[0][4]) === '2' && result.rows[0][5] === 'open' && result.rows[0][6] === null) injection.freshOpenReads++;
            }
            if (/^COMMIT\b/i.test(text) && injection.armed && openUpdateInTransaction) {
              injection.armed = false; injection.fired = true;
              const local = supervisor.control_binding();
              if (!local.sealed) throw new Error('lost_ack_native_gate_not_sealed');
              ordinaryBlocked(2);
              injection.boundarySealed = true;
              // The server really committed. Only its acknowledgment is withheld.
              throw Object.assign(new Error('closed_commit_fault'), {code: '08006'});
            }
            return result;
          },
          getTransactionStatus: () => client.getTransactionStatus(),
          release: destroy => client.release(destroy),
        };
      },
      end: () => rawPool.end(),
    };
    supervisorResource = new PoolResource(supervisorConfig, {pool: borrowed});
    await supervisorResource.open();
    await resource.open(); await writer.initialize(options);
    recovery = new PostgresQdrantRecovery(supervisorResource, inputs.config, supervisor, verifier);
    if (writer_binding(writer).instance_id !== inputs.instance_id
      || recovery_components(recovery, writer, supervisor, inputs.config) !== verifier) throw new Error('native_dependency_binding');
    await recovery.initialize(options);
    const registered = await state();
    if (!isDeepStrictEqual(registered, [['open', '1', null]])) throw new Error('instance_registration');
    checks.push(CHECKS[0]);

    const originalRequest = await lostAck(ctx, inputs.stage, inputs.expected_points, 'e2b-first-lost', true);
    await lostAck(second, inputs.second_stage, inputs.second_points, 'e2b-second-lost');
    await writer.stage(prepare_stage(inputs.third_stage), third.scope, {...options, owner_token: THIRD_OWNER});
    if (!isDeepStrictEqual(await journal(), [['e2b-first-lost', 'unknown'], ['e2b-second-lost', 'unknown']])) throw new Error('two_unknown_journals');
    checks.push(CHECKS[1]);

    // Observe the actual exclusive session and forward its real private facade.
    // Public lifecycle methods remain unmodified so their exclusion is tested.
    const controlSession = supervisor.control_session.bind(supervisor);
    supervisor.control_session = callback => controlSession(async actualFacade => {
      const observedFacade = Object.freeze({...actualFacade,
        recover: async (record, lease) => {
          const observed = await state();
          if (!isDeepStrictEqual(observed, [['recovery_blocked', String(record.new_epoch), record.recovery_id]])) throw new Error('physical_before_durable_block');
          ordinaryBlocked(record.new_epoch);
          if (!thirdRevoked) {
            const unknowns = [['e2b-first-lost', 'unknown'], ['e2b-second-lost', 'unknown']];
            if (!isDeepStrictEqual(await journal(), unknowns)) throw new Error('third_gate_requires_two_unknowns');
            const before = await writer.manager_snapshot(third, options);
            if (before.owner !== null || before.max_sequence !== 0 || before.pending) throw new Error('third_stage_already_mutated');
            await expected(ProviderUnavailable, () => writer.acquire_owner(third, options));
            await expected(ProviderUnavailable, () => supervisor.issue_attempt({intent_id: third.intent_id,
              owner_token: THIRD_OWNER, epoch: record.new_epoch, dispatch_id: 'e2b-third-blocked'}, options));
            if (!isDeepStrictEqual(await writer.manager_snapshot(third, options), before)
              || !isDeepStrictEqual(await journal(), unknowns)) throw new Error('third_block_changed_mutation_state');
            const initial = inputs.third_stage.intent.initial_authorization;
            const revocation = await writer.apply_security({action: 'update_authorization', intent_id: 'e2b-third-revoke',
              tenant_id: third.scope.tenant_id, collection: third.collection, document_id: third.document_id,
              expected_authorization_revision: 'auth-1', expected_mutation_epoch: 1,
              authorization: {authorization_revision: 'auth-e2b-third-2', principal_ids: [], grant_ids: [],
                tombstoned: false, language: initial.language, kind: initial.kind, tag: initial.tag}},
              third.scope, {...options, owner_token: THIRD_OWNER});
            if (revocation.state !== 'authority_committed' || !revocation.authority_committed
              || revocation.replica_complete || revocation.purge_complete) throw new Error('third_revocation_not_committed');
            const after = await writer.manager_snapshot(thirdFresh, options);
            if (after.document?.authorization_revision !== 'auth-e2b-third-2' || after.document.mutation_epoch !== 2
              || after.document.tombstoned || after.owner !== null || after.max_sequence !== 0 || after.pending)
              throw new Error('third_revocation_not_independently_visible');
            await expected(UnauthorizedScope, () => writer.manager_snapshot(third, options));
            if (!isDeepStrictEqual(await state(), observed) || !isDeepStrictEqual(await journal(), unknowns))
              throw new Error('third_revocation_changed_recovery_window');
            thirdRevoked = true;
          }
          if (pausePhysical) {
            const pause = pausePhysical;
            pausePhysical = undefined;
            // An ambient callback or inherited Promise context conveys no
            // authority to invoke a raw lifecycle mutation during this session.
            await expected(ProviderUnavailable, () => supervisor.recover(record, lease));
            await expected(ProviderUnavailable, () => Promise.resolve().then(() => supervisor.recover(record, lease)));
            pause.started();
            await bounded(pause.release, lease);
          }
          const proof = await actualFacade.recover(record, lease);
          fenceCount++;
          return proof;
        },
        finish_recovery: (barrier, settlement, lease) => {
          if (injection.fired && !injection.handoffChecked) {
            if (!supervisor.control_binding().sealed || !injection.boundarySealed || injection.freshOpenReads < 1 || injection.openUpdates !== 1) throw new Error('handoff_without_commit_reconciliation');
            injection.handoffChecked = true;
          }
          return actualFacade.finish_recovery(barrier, settlement, lease);
        },
      });
      return callback(observedFacade);
    });
    const proofA = await recovery.recover('e2b-native', options);
    await assertBlocked();
    if (fenceCount !== 1 || await observedListener(address) === firstPid) throw new Error('physical_fence_missing');
    const bindingA = supervisor.recovery_binding(proofA);
    checks.push(CHECKS[2]);
    if (await oldKeyStatus(oldCredential, target + '/points?wait=true&ordering=strong', Buffer.from(originalRequest.request_bytes), options.signal) !== 401) throw new Error('old_key_not_denied');
    checks.push(CHECKS[3]);
    const unknownRows = () => sup(query => query('SELECT tenant_id,collection,document_id,intent_id,dispatch_id,instance_id,sequence,owner_token::text,backend_epoch,credential_generation,operation,recovery,request_sha256,state,completion_sha256,created_xid::text FROM cragkit_qdrant.dispatch_journal WHERE instance_id=$1 ORDER BY dispatch_id', [inputs.instance_id]));
    const unknownBefore = await unknownRows();
    const blockedBefore = await state();
    if (!isDeepStrictEqual(await journal(), [['e2b-first-lost', 'unknown'], ['e2b-second-lost', 'unknown']])) throw new Error('fabricated_proof_requires_two_unknowns');
    const fabricatedProofs = [
      JSON.parse(JSON.stringify(bindingA)),
      {...bindingA, drained: true, quiescent: true, writer_pid: await observedListener(address)},
    ];
    for (const fabricated of fabricatedProofs) {
      await assertBlocked();
      await expected(UnsupportedCapability, () => recovery.advance_owner(fabricated, ctx, options));
      if (!isDeepStrictEqual(await unknownRows(), unknownBefore)
        || !isDeepStrictEqual(await state(), blockedBefore)) throw new Error('fabricated_proof_changed_durable_state');
      await assertBlocked();
    }
    checks.push(CHECKS[4]);
    await expected(ProviderUnavailable, () => recovery.advance_owner(proofA, {...ctx, owner_token: SECOND_OWNER}, options));
    const owner = await recovery.advance_owner(proofA, ctx, options);
    if (!isDeepStrictEqual(owner, {owner_token: OWNER, backend_epoch: 2})) throw new Error('owner_rebound');
    checks.push(CHECKS[5]);
    const receiptA = await verifier.verify(proofA, ctx, options);
    await expected(InvalidRequest, () => recovery.settle_retired(proofA, JSON.parse(JSON.stringify(receiptA)), options));
    checks.push(CHECKS[6]);
    if ((await recovery.settle_retired(proofA, receiptA, options)).settled_count !== 1
      || !isDeepStrictEqual(await journal(), [['e2b-first-lost', 'settled'], ['e2b-second-lost', 'unknown']])) throw new Error('cross_document_settlement');
    checks.push(CHECKS[7]);
    await expected(ProviderUnavailable, () => recovery.reopen(proofA, options));
    await assertBlocked();
    if (!supervisor.control_binding().sealed) throw new Error('pending_other_document_not_sealed');
    checks.push(CHECKS[8]);

    const proofB = await recovery.recover('e2b-native', options);
    const bindingB = supervisor.recovery_binding(proofB);
    if (fenceCount !== 2 || bindingB.new_epoch !== 2 || bindingA.credential_generation === bindingB.credential_generation) throw new Error('same_identity_did_not_refence');
    await expected(UnsupportedCapability, () => supervisor.recovery_binding(proofA));
    await expected(UnsupportedCapability, () => receipt_data(receiptA, verifier));
    await assertBlocked();
    checks.push(CHECKS[9]);
    await recovery.advance_owner(proofB, second, options);
    const secondReceipt = await verifier.verify(proofB, second, options);
    if ((await recovery.settle_retired(proofB, secondReceipt, options)).settled_count !== 1) throw new Error('second_document_not_settled');
    checks.push(CHECKS[10]);

    // Explicit fixture-only current-generation admission; journal and membership commit together.
    const currentDispatch = 'e2b-current-unknown';
    await sup(async query => {
      await query("INSERT INTO cragkit_qdrant.dispatch_journal(tenant_id,collection,document_id,intent_id,dispatch_id,instance_id,sequence,owner_token,backend_epoch,credential_generation,operation,recovery,request_bytes,request_sha256) VALUES($1,$2,$3,$4,$5,$6,2,$7,2,$8,'complete_point_upsert',true,$9,$10)",
        [ctx.scope.tenant_id, ctx.collection, ctx.document_id, ctx.intent_id, currentDispatch, inputs.instance_id, OWNER,
          bindingB.credential_generation, Buffer.from(originalRequest.request_bytes), digest(originalRequest.request_bytes)]);
      for (const point of inputs.expected_points) await query('INSERT INTO cragkit_qdrant.dispatch_points(tenant_id,collection,document_id,intent_id,dispatch_id,backend_namespace,physical_collection,collection_incarnation,point_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)',
        [ctx.scope.tenant_id, ctx.collection, ctx.document_id, ctx.intent_id, currentDispatch, inputs.config.backend_namespace,
          inputs.config.physical_collection, inputs.config.collection_incarnation, point.id]);
    });
    await sup(query => query("UPDATE cragkit_qdrant.dispatch_journal SET state='dispatched' WHERE instance_id=$1 AND dispatch_id=$2", [inputs.instance_id, currentDispatch]));
    const currentCap = supervisor.issue_recovery_attempt(proofB, {intent_id: ctx.intent_id, owner_token: OWNER,
      epoch: 2, dispatch_id: currentDispatch, recovery_id: 'e2b-native'}, options);
    const currentHandle = supervisor.transport_for(currentCap); handles.add(currentHandle);
    completed(await currentHandle.request('PUT', target + '/points?wait=true&ordering=strong', {...options, body: originalRequest.request_bytes}));
    await closeHandle(currentHandle);
    await sup(query => query("UPDATE cragkit_qdrant.dispatch_journal SET state='unknown' WHERE instance_id=$1 AND dispatch_id=$2", [inputs.instance_id, currentDispatch]));
    checks.push(CHECKS[11]);
    const currentReceipt = await verifier.verify(proofB, ctx, options);
    await expected(ProviderUnavailable, () => recovery.settle_retired(proofB, currentReceipt, options));
    if (!isDeepStrictEqual(await journal(), [['e2b-current-unknown', 'unknown'], ['e2b-first-lost', 'settled'], ['e2b-second-lost', 'settled']])) throw new Error('current_generation_was_settled');
    checks.push(CHECKS[12]);
    await expected(ProviderUnavailable, () => recovery.reopen(proofB, options));
    await assertBlocked();
    if (!supervisor.control_binding().sealed) throw new Error('current_generation_not_sealed');
    checks.push(CHECKS[13]);

    const proofC = await recovery.recover('e2b-native', options);
    const bindingC = supervisor.recovery_binding(proofC);
    if (fenceCount !== 3 || bindingC.new_epoch !== 2 || bindingC.credential_generation === bindingB.credential_generation) throw new Error('current_generation_not_retired');
    await recovery.advance_owner(proofC, ctx, options);
    const receiptC = await verifier.verify(proofC, ctx, options);
    if ((await recovery.settle_retired(proofC, receiptC, options)).settled_count !== 1) throw new Error('retired_current_write_not_settled');
    checks.push(CHECKS[14]);
    if ((await recovery.settle_retired(proofC, receiptC, options)).settled_count !== 0) throw new Error('settlement_replay_changed');
    checks.push(CHECKS[15]);

    competingRecovery = new PostgresQdrantRecovery(supervisorResource, inputs.config, supervisor, verifier);
    await competingRecovery.initialize(options);
    let started, release;
    const paused = new Promise(resolve => { started = resolve; });
    const released = new Promise(resolve => { release = resolve; });
    pausePhysical = {started, release: released};
    const competing = competingRecovery.recover('e2b-native', options);
    // Observe rejection before attaching later awaits, including a failed run.
    void competing.catch(() => {});
    await bounded(Promise.race([paused, competing.then(() => {
      throw new Error('competing_recovery_skipped_pause');
    })]), options);
    const queriesBeforeCompetition = injection.sqlCalls;
    await expected(ProviderUnavailable, () => recovery.reopen(proofC, options));
    await expected(ProviderUnavailable, () => supervisor.recover({recovery_id: 'e2b-native', old_epoch: 1, new_epoch: 2}, options));
    if (injection.sqlCalls !== queriesBeforeCompetition) throw new Error('competing_operation_reached_sql');
    await assertBlocked();
    checks.push(CHECKS[16]);
    release();
    const handoffProof = await competing;
    if (supervisor.recovery_binding(handoffProof).new_epoch !== 2 || fenceCount !== 4) throw new Error('shared_session_handoff_failed');
    await competingRecovery.close(); competingRecovery = undefined;
    checks.push(CHECKS[17]);

    injection.armed = true;
    let reopened;
    try { reopened = await recovery.reopen(handoffProof, options); }
    catch (error) {
      if (!(error instanceof ProviderUnavailable)) throw error;
      if (!injection.fired || !supervisor.control_binding().sealed) throw new Error('lost_ack_unsealed');
      ordinaryBlocked(2);
      reopened = await recovery.reopen(handoffProof, {deadline: now() + 30, signal: options.signal});
    }
    if (!injection.fired || !injection.boundarySealed || !injection.handoffChecked || injection.openUpdates !== 1
      || injection.freshOpenReads < 1 || !isDeepStrictEqual(reopened, {state: 'open', epoch: 2})) throw new Error('open_commit_not_reconciled');
    checks.push(CHECKS[18]);
    if (!isDeepStrictEqual(await state(), [['open', '2', null]])) throw new Error('sql_open_state');
    await ordinaryRead(2, 'e2b-ordinary-after-recovery');
    await expected(UnsupportedCapability, () => supervisor.recovery_binding(handoffProof));
    checks.push(CHECKS[19]);

    const nextProof = await recovery.recover('e2b-next', options);
    if (supervisor.recovery_binding(nextProof).new_epoch !== 3 || fenceCount !== 5) throw new Error('next_epoch_not_advanced');
    await assertBlocked(3);
    const nextOpen = await recovery.reopen(nextProof, options);
    if (!isDeepStrictEqual(nextOpen, {state: 'open', epoch: 3}) || !isDeepStrictEqual(await state(), [['open', '3', null]])) throw new Error('next_epoch_not_open');
    await ordinaryRead(3, 'e2b-next-ordinary');
    checks.push(CHECKS[20]);
    for (const context of [ctx, second]) {
      const intent = await writer.inspect(context, options);
      if (!intent || intent.state !== 'writing' || intent.authority_committed || intent.replica_complete || intent.purge_complete) throw new Error('recovery_claimed_publication');
    }
    const remaining = await journal();
    if (remaining.length !== 3 || remaining.some(row => row[1] !== 'settled')) throw new Error('unexpected_final_journal');
    checks.push(CHECKS[21]);
    const thirdFinal = await writer.manager_snapshot(thirdFresh, options);
    if (!thirdRevoked || thirdFinal.document?.authorization_revision !== 'auth-e2b-third-2'
      || thirdFinal.document.mutation_epoch !== 2 || thirdFinal.document.tombstoned
      || thirdFinal.owner !== null || thirdFinal.max_sequence !== 0 || thirdFinal.pending)
      throw new Error('third_revocation_lost_after_recovery');
    await expected(UnauthorizedScope, () => writer.manager_snapshot(third, options));
    checks.push(CHECKS[22]);
    return {runtime: 'typescript', checks, proof_scope: 'durable_recovery_settlement_only'};
  } catch (error) { primary = error; throw error; }
  finally {
    step = checks.length;
    const failures = [];
    const close = async (operation, owned, method = 'close') => {
      if (!owned) return;
      try { await bounded(Promise.resolve().then(() => owned[method]()), {deadline: now() + 8}); }
      catch (error) { failures.push({operation, outcome: outcome(error)}); }
    };
    let transportError;
    for (const handle of handles) {
      try { await bounded(handle.close(), {deadline: now() + 3}); }
      catch (error) { transportError ??= error; }
    }
    if (transportError) failures.push({operation: 'transport_close', outcome: outcome(transportError)});
    await close('verifier_close', verifier);
    await close('writer_close', writer);
    await close('recovery_close', competingRecovery);
    await close('recovery_close', recovery);
    await close('resource_close', resource);
    await close('supervisor_resource_close', supervisorResource);
    await close('supervisor_pool_close', rawPool, 'end');
    await close('controller_close', supervisor);
    for (const key of Object.keys(oldCredential)) delete oldCredential[key];
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
