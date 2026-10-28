/** Native authority transaction cases. Actual Qdrant completion is checked in F/H. */
import {PoolResource, parse_pool_config, now} from '../packages/typescript/dist/postgres-pool.js';
import {PostgresQdrantWriter, prepare_stage} from '../packages/typescript/dist/qdrant-writer.js';
import {createHash} from 'node:crypto';
import {isDeepStrictEqual} from 'node:util';
import {IntegrityViolation, UnauthorizedScope, IndexNotReady, ProviderUnavailable} from '../packages/typescript/dist/errors.js';

const OWNER_TOKEN = '00000000-0000-4000-8000-000000000001';
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
let phase = 'input';
const ERROR_NAMES = new Set(['IntegrityViolation', 'UnauthorizedScope', 'IndexNotReady',
  'InvalidRequest', 'ProviderUnavailable', 'UnsupportedCapability', 'DeadlineExceeded']);
const outcome = error => ERROR_NAMES.has(error?.name) ? error.name : 'internal';

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
    if (size > 262144) throw new Error('bounded_input');
    chunks.push(chunk);
  }
  return JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(Buffer.concat(chunks)));
}

async function cases(value) {
  const {config, inputs} = value;
  const resource = new PoolResource(parse_pool_config(config));
  const acknowledgment = {armed: false, fired: 0, destroyed: 0};
  const withLease = resource.withLease.bind(resource);
  // Forward every query to the owned native driver. Withhold one real COMMIT
  // acknowledgment during alternate-owner admission and security commit below.
  resource.withLease = (leaseOptions, operation) => withLease(leaseOptions, (client, signal) => {
    let committedUnknown = false;
    return operation({
      async query(query) {
        const result = await client.query(query);
        if (query.text === 'COMMIT' && acknowledgment.armed) {
          acknowledgment.armed = false;
          acknowledgment.fired++;
          committedUnknown = true;
          throw Object.assign(new Error('closed_commit_fault'), {code: '08006'});
        }
        return result;
      },
      getTransactionStatus: () => client.getTransactionStatus(),
      release(destroy) {
        if (committedUnknown) {
          if (destroy !== true) throw new Error('unknown_commit_client_reused');
          acknowledgment.destroyed++;
          committedUnknown = false;
        }
        client.release(destroy);
      },
    }, signal);
  });
  const writer = new PostgresQdrantWriter(resource, inputs.config, inputs.instance_id);
  const otherResource = new PoolResource(parse_pool_config(config));
  const other = new PostgresQdrantWriter(otherResource, inputs.config, inputs.instance_id);
  const scope = inputs.scope;
  const context = {scope, collection: inputs.stage.manifest.collection,
    document_id: inputs.stage.manifest.document_id, intent_id: inputs.stage.intent.intent_id,
    owner_token: OWNER_TOKEN};
  const options = {deadline: now() + 60};
  const checks = [];
  async function expect(type, operation) {
    try { await operation(); } catch (error) { if (error instanceof type) return; throw error; }
    throw new Error('expected_failure_missing');
  }
  let primary;
  try {
    phase = 'initialize';
    await resource.open();
    await expect(IndexNotReady, () => writer.inspect(context, options));
    await writer.initialize(options);
    checks.push('explicit_initialization_exact_schema_and_dedicated_login');
    phase = 'stage';
    const empty = await writer.manager_snapshot(context, options);
    if (empty.intent !== null || empty.document !== null || empty.owner !== null
      || empty.max_sequence !== 0 || empty.pending || empty.backend.state !== 'open'
      || empty.backend.epoch !== 1 || empty.backend.backend_namespace !== inputs.config.backend_namespace) {
      throw new Error('manager_absent_snapshot');
    }
    const plan = prepare_stage(inputs.stage);
    await writer.stage(plan, scope, {...options, owner_token: OWNER_TOKEN});
    const first = await writer.inspect(context, options);
    if (!first || first.state !== 'staged' || first.authority_committed) throw new Error('stage_state');
    await writer.stage(plan, scope, {...options, owner_token: OWNER_TOKEN});
    if (JSON.stringify(await writer.inspect(context, options)) !== JSON.stringify(first)) throw new Error('stage_replay_changed');
    checks.push('immutable_creation_and_exact_idempotent_stage_replay');
    const staged = await writer.manager_snapshot(context, options);
    if (staged.intent?.state !== 'staged' || staged.document?.active_generation_id !== null
      || staged.document.authorization_revision !== 'auth-1') throw new Error('manager_staged_snapshot');
    checks.push('manager_snapshot_absent_and_staged_state');
    const admission = await writer.admit_publication(context, options);
    const admittedSnapshot = await writer.manager_snapshot(context, options);
    if (admission.intent.state !== 'writing'
      || !isDeepStrictEqual(admission.owner, {owner_token: OWNER_TOKEN, backend_epoch: 1})
      || !isDeepStrictEqual(admittedSnapshot.owner, {instance_id: inputs.instance_id,
        intent_id: context.intent_id, owner_token: OWNER_TOKEN, backend_epoch: 1})) throw new Error('manager_owner_admission');
    checks.push('manager_admission_acquires_exact_private_owner');
    const alternate = {...context, owner_token: '00000000-0000-4000-8000-000000000002'};
    acknowledgment.armed = true;
    const admitted = await writer.admit_publication(alternate, options);
    const reconciled = await writer.manager_snapshot(context, options);
    if (acknowledgment.armed || acknowledgment.fired !== 1 || acknowledgment.destroyed !== 1
      || !isDeepStrictEqual(admitted.owner, {owner_token: alternate.owner_token, backend_epoch: 1})
      || reconciled.owner?.owner_token !== alternate.owner_token || reconciled.owner.backend_epoch !== 1) {
      throw new Error('manager_committed_admission_ack_loss');
    }
    await writer.admit_publication(context, options);
    checks.push('manager_admission_commit_ack_loss_reconciles_same_owner');
    const changed = structuredClone(inputs.stage);
    changed.intent.initial_authorization.tag = 'changed';
    const changedPlan = prepare_stage(changed);
    await expect(IntegrityViolation, () => writer.stage(changedPlan, scope, {...options, owner_token: OWNER_TOKEN}));
    checks.push('stable_intent_changed_payload_rejected');
    await expect(UnauthorizedScope, () => writer.stage(plan, {...scope, tenant_id: 'foreign-tenant'},
      {...options, owner_token: OWNER_TOKEN}));
    checks.push('stage_trusted_scope_cannot_be_rebound');
    phase = 'dispatch';
    await writer.acquire_owner(context, options);
    const point_ids = inputs.stage.manifest.members.map(member => member.point_id);
    const dispatch = {dispatch_id: 'native-dispatch-1', sequence: 1, credential_generation: 'credential-1',
      operation: 'complete_point_upsert', point_ids};
    const reservation = await writer.reserve_dispatch(context, dispatch, options);
    const body = Buffer.from(reservation.request_bytes);
    if (digest(body) !== reservation.request_sha256) throw new Error('request_digest');
    const payload = JSON.parse(body);
    if (JSON.stringify(payload.points.map(point => point.id).sort()) !== JSON.stringify([...point_ids].sort())) throw new Error('exact_point_set');
    const byId = (left, right) => left.id < right.id ? -1 : left.id > right.id ? 1 : 0;
    if (!isDeepStrictEqual([...payload.points].sort(byId), [...inputs.expected_points].sort(byId))) throw new Error('complete_vectors_current_acl');
    checks.push('committed_reservation_constructs_exact_complete_points_and_current_acl');
    const waiting = await writer.manager_snapshot({...context, intent_id: 'manager-other-intent'}, options);
    const status = await writer.dispatch_status(context, dispatch.dispatch_id, options);
    if (!waiting.pending || waiting.intent !== null
      || !isDeepStrictEqual(status, {dispatch_id: dispatch.dispatch_id, sequence: 1, owner_token: OWNER_TOKEN,
        backend_epoch: 1, credential_generation: dispatch.credential_generation, operation: dispatch.operation,
        state: 'reserved', completion_sha256: null, request_sha256: reservation.request_sha256,
        point_ids: [...point_ids].sort()})
      || await writer.dispatch_status(context, 'manager-missing-dispatch', options) !== null) {
      throw new Error('manager_pending_dispatch_snapshot');
    }
    checks.push('manager_snapshot_document_wide_uncertainty_and_exact_dispatch_metadata');
    const reordered = await writer.reserve_dispatch(context, {...dispatch, point_ids: [...point_ids].reverse()}, options);
    if (!Buffer.from(reordered.request_bytes).equals(body) || reordered.request_sha256 !== reservation.request_sha256) throw new Error('same_claimed_set_replay_changed');
    checks.push('reservation_replay_uses_same_exact_claimed_set_independent_of_input_order');
    await expect(ProviderUnavailable, () => writer.reserve_dispatch(context, {...dispatch, dispatch_id: 'blocked-dispatch', sequence: 2}, options));
    await expect(ProviderUnavailable, () => writer.prepare(context, digest(Buffer.from('blocked-preparation')), options));
    checks.push('reserved_work_blocks_new_dispatch_and_preparation_as_operational_failure');
    await writer.mark_dispatched(context, dispatch.dispatch_id, options);
    // Synthetic proof exercises only SQL transitions in D, never F/H acceptance.
    const completion = digest(Buffer.from('D-native-synthetic-completion'));
    await writer.settle_dispatch(context, dispatch.dispatch_id, completion, options);
    const settled = await writer.dispatch_status(context, dispatch.dispatch_id, options);
    if (!isDeepStrictEqual(settled, {...status, state: 'settled', completion_sha256: completion})) throw new Error('manager_settled_dispatch_snapshot');
    checks.push('manager_settled_dispatch_status_preserves_known_fixture_hash');
    phase = 'publish';
    await writer.prepare(context, completion, options);
    await writer.publish(context, options);
    const published = await writer.inspect(context, options);
    if (!published || published.state !== 'published' || !published.authority_committed || !published.replica_complete) throw new Error('publication_state');
    await writer.publish(context, options);
    checks.push('atomic_authority_preparation_publication_and_replay');
    phase = 'publication_interleaving';
    await otherResource.open();
    await other.initialize(options);
    async function prepared(actor, stage, token) {
      const target = {...context, intent_id: stage.intent.intent_id, owner_token: token};
      await actor.stage(prepare_stage(stage), scope, {...options, owner_token: token});
      await actor.acquire_owner(target, options);
      const request = {dispatch_id: 'dispatch-' + stage.intent.intent_id, sequence: 1,
        credential_generation: 'credential-1', operation: 'complete_point_upsert',
        point_ids: stage.manifest.members.map(member => member.point_id)};
      await actor.reserve_dispatch(target, request, options);
      await actor.mark_dispatched(target, request.dispatch_id, options);
      await actor.settle_dispatch(target, request.dispatch_id, completion, options);
      await actor.prepare(target, completion, options);
      return target;
    }
    const tokenB = '00000000-0000-4000-8000-000000000002';
    await other.stage(prepare_stage(inputs.successors['race-b']), scope, {...options, owner_token: tokenB});
    const a = await prepared(writer, inputs.successors['race-a'], OWNER_TOKEN);
    const b = await prepared(other, inputs.successors['race-b'], tokenB);
    const conflictStage = inputs.successors['manager-conflict'];
    const conflictContext = {...context, intent_id: conflictStage.intent.intent_id};
    await writer.stage(prepare_stage(conflictStage), scope, {...options, owner_token: OWNER_TOKEN});
    await other.publish(b, options);
    const beforeConflict = await writer.manager_snapshot(conflictContext, options);
    const conflict = await writer.admit_publication(conflictContext, options);
    const afterConflict = await writer.manager_snapshot(conflictContext, options);
    if (conflict.intent.state !== 'conflict' || conflict.owner !== null
      || !isDeepStrictEqual(beforeConflict.document, afterConflict.document)
      || !isDeepStrictEqual(beforeConflict.owner, afterConflict.owner)) throw new Error('manager_original_pointer_conflict');
    checks.push('manager_original_pointer_conflict_before_takeover');
    const loser = await writer.publish(a, options);
    if (loser.state !== 'conflict' || loser.authority_committed) throw new Error('competing_publication_conflict');
    if ((await other.inspect(b, options)).state !== 'published') throw new Error('publication_winner_changed');
    checks.push('two_login_publication_interleaving_preserves_winner_and_original_cas');
    const historical = await writer.publish(context, options);
    if (historical.state !== 'published' || historical.generation_id !== inputs.stage.manifest.generation_id) throw new Error('historical_publication_replay_lost');
    checks.push('superseded_completed_publication_replays_historical_outcome');
    const deniedContext = await prepared(writer, inputs.successors.denied, OWNER_TOKEN);
    const managerDeniedStage = inputs.successors['manager-denied'];
    const managerDeniedContext = {...context, intent_id: managerDeniedStage.intent.intent_id};
    await writer.stage(prepare_stage(managerDeniedStage), scope, {...options, owner_token: OWNER_TOKEN});
    const revocation = {action: 'update_authorization', intent_id: 'native-revocation', tenant_id: scope.tenant_id,
      collection: context.collection, document_id: context.document_id,
      expected_authorization_revision: 'auth-1', expected_mutation_epoch: 1,
      authorization: {authorization_revision: 'auth-2', principal_ids: [], grant_ids: [],
        language: null, kind: null, tag: null, tombstoned: false}};
    await other.apply_security(revocation, scope, {...options, owner_token: tokenB});
    const denied = await writer.publish(deniedContext, options);
    if (denied.state !== 'denied' || denied.authority_committed) throw new Error('revoked_publication_not_denied');
    checks.push('two_login_revocation_after_preparation_denies_publication');
    const currentScope = {...scope, authorization_revision: 'auth-2'};
    await expect(UnauthorizedScope, () => writer.admit_publication(managerDeniedContext, options));
    if ((await writer.inspect(managerDeniedContext, options))?.state !== 'staged') throw new Error('manager_stale_scope_poisoned_intent');
    checks.push('manager_stale_caller_cannot_poison_valid_intent');
    const freshDenied = {...managerDeniedContext, scope: currentScope};
    const beforeDenial = await writer.manager_snapshot(freshDenied, options);
    const admissionDenied = await writer.admit_publication(freshDenied, options);
    const historicalContext = {...context, scope: currentScope};
    const historicalAdmission = await writer.admit_publication(historicalContext, options);
    const afterDenial = await writer.manager_snapshot(historicalContext, options);
    if (admissionDenied.intent.state !== 'denied' || admissionDenied.owner !== null
      || historicalAdmission.intent.state !== 'published' || historicalAdmission.owner !== null
      || !isDeepStrictEqual(beforeDenial.document, afterDenial.document)
      || !isDeepStrictEqual(beforeDenial.owner, afterDenial.owner)) throw new Error('manager_original_security_denial');
    checks.push('manager_original_security_denial_before_takeover_and_historical_metadata');
    const stale = {...revocation, intent_id: 'native-stale-security'};
    const staleReceipt = await writer.apply_security(stale, scope, {...options, owner_token: OWNER_TOKEN});
    if (staleReceipt.state !== 'denied' || staleReceipt.authority_committed) throw new Error('stale_security_not_denied');
    if (!isDeepStrictEqual(await writer.apply_security(stale, currentScope, {...options, owner_token: OWNER_TOKEN}), staleReceipt)) throw new Error('stale_security_replay_changed');
    checks.push('stale_security_intent_denied_without_overwriting_current_authority');
    phase = 'security';
    const security = {action: 'tombstone', intent_id: 'native-tombstone', tenant_id: scope.tenant_id,
      collection: context.collection, document_id: context.document_id,
      expected_authorization_revision: 'auth-2', expected_mutation_epoch: 2,
      authorization: {authorization_revision: 'auth-3', principal_ids: [], grant_ids: [],
        language: null, kind: null, tag: null, tombstoned: true}};
    acknowledgment.armed = true;
    const tombstone = await writer.apply_security(security, currentScope, {...options, owner_token: OWNER_TOKEN});
    if(acknowledgment.armed||acknowledgment.fired!==2||acknowledgment.destroyed!==2||!tombstone.authority_committed||tombstone.replica_complete||tombstone.purge_complete)throw new Error('security_commit_ack_confirmation_failed');
    checks.push('security_commit_ack_loss_confirms_without_mutation_replay');
    await writer.apply_security(security, currentScope, {...options, owner_token: OWNER_TOKEN});
    checks.push('immediate_monotonic_tombstone_with_stable_security_intent');
    const historicalSecurity=await writer.apply_security(revocation,scope,{...options,owner_token:OWNER_TOKEN});
    if(!historicalSecurity.authority_committed||historicalSecurity.payload_sha256===tombstone.payload_sha256)throw new Error('superseded_security_history_lost');
    checks.push('superseded_security_retry_preserves_current_tombstone');
    const purgeScope = {...scope, authorization_revision: 'auth-3'};
    const purge = {intent_id: 'native-purge', tenant_id: scope.tenant_id, collection: context.collection,
      document_id: context.document_id, tombstone_intent_payload_sha256: tombstone.payload_sha256,
      expected_authorization_revision: 'auth-3', expected_mutation_epoch: 3};
    const purgeReceipt = await writer.bind_purge(purge, purgeScope, {...options, owner_token: OWNER_TOKEN});
    if (purgeReceipt.state !== 'authority_committed' || !purgeReceipt.authority_committed || purgeReceipt.purge_complete || purgeReceipt.replica_complete) throw new Error('purge_binding_completion_flags');
    if (!isDeepStrictEqual(await writer.bind_purge(purge, purgeScope, {...options, owner_token: OWNER_TOKEN}), purgeReceipt)) throw new Error('purge_binding_replay_changed');
    checks.push('tombstone_bound_purge_admission_is_idempotent_and_replica_pending');
    return {runtime: 'typescript', checks, publication_proof: 'authority_transactions_only'};
  } catch (error) {
    primary = error;
    throw error;
  } finally {
    const failures = [];
    try { await writer.close(); } catch (error) { failures.push({operation: 'writer_close', outcome: outcome(error)}); }
    try { await other.close(); } catch (error) { failures.push({operation: 'writer_close', outcome: outcome(error)}); }
    try { await resource.close(); } catch (error) { failures.push({operation: 'resource_close', outcome: outcome(error)}); }
    try { await otherResource.close(); } catch (error) { failures.push({operation: 'resource_close', outcome: outcome(error)}); }
    if (failures.length) throw new RuntimeCleanupFailure(primary, failures);
  }
}

try {
  process.stdout.write(JSON.stringify(await cases(await input())) + '\n');
} catch (error) {
  // Closed diagnostics only: never print driver messages, rows or config.
  process.stdout.write(JSON.stringify({ok: false, phase,
    error: error instanceof RuntimeCleanupFailure ? 'cleanup_failed' : outcome(error),
    ...(error instanceof RuntimeCleanupFailure ? {primary: error.primary, cleanup: error.failures} : {})}) + '\n');
  process.exitCode = 1;
}
