/** Actual native public stage/publish cases; worker SIGKILL belongs to F2b/H. */
import {execFile} from 'node:child_process';
import {createHash} from 'node:crypto';
import {writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {isDeepStrictEqual} from 'node:util';
import {PoolResource, parse_pool_config, bounded, now} from '../packages/typescript/dist/postgres-pool.js';
import {ExecutionLedger, BudgetExhausted} from '../packages/typescript/dist/execution.js';
import {QdrantPublicationManager, PostgresQdrantPublicationAuthority, ManagedQdrantPublicationTransport,
  PostgresQdrantWriter, PostgresQdrantRecovery, ManagedQdrantSupervisor,
  QdrantReconciliationVerifier} from '../packages/typescript/dist/qdrant-publication.js';
import {prepare_stage, stage_data} from '../packages/typescript/dist/qdrant-writer-contract.js';
import {IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope} from '../packages/typescript/dist/errors.js';

const OWNER = '00000000-0000-4000-8000-000000000001';
const CHECKS = Object.freeze([
  'native_manager_initialized_explicit_borrowed_dependencies',
  'stage_commits_authority_without_qdrant_mutation_and_honors_ledger',
  'publish_uses_actual_completed_ack_full_readback_and_cas',
  'matching_terminal_stage_and_publish_are_historical_no_mutation',
  'changed_stage_payload_fails_without_new_writes',
  'authorizer_denial_malformed_failure_are_closed_no_writes',
  'competing_original_pointer_preserves_winner_and_persists_conflict',
  'prepared_quiescent_cancel_is_unpublished_and_resumes_without_upsert',
  'actual_preparation_commit_ack_loss_reconciles_without_http_resend',
  'finalization_session_excludes_raw_lifecycle_and_recovery',
  'late_revocation_blocks_publication_and_preserves_active',
  'fresh_scope_terminal_replay_never_restores_initial_acl',
  'actual_lost_write_ack_stays_unknown_and_retry_does_not_resend',
  'manager_close_preserves_borrowed_dependencies',
  'actual_atomic_stage_rollback_preserves_pointer_and_no_rows',
  'actual_stage_commit_ack_loss_resumes_exact_graph_without_http',
  'actual_publication_cas_commit_ack_loss_resolves_exactly_once',
  'bootstrap_acl_changed_rejected_without_sql_http_mutation',
  'partial_member_stage_rejected_before_http_preserves_pointer',
  'budget_before_dispatch_preserves_journal_stage_pointer_and_http',
]);
const ERRORS = new Set(['IntegrityViolation', 'UnauthorizedScope', 'UnsupportedCapability', 'InvalidRequest',
  'ProviderUnavailable', 'DeadlineExceeded', 'IndexNotReady', 'BudgetExhausted', 'CancelledError', 'AbortError']);
const RESULT_KEYS = ['intent_id', 'operation', 'state', 'revision_id', 'generation_id',
  'authority_committed', 'replica_complete', 'published', 'purge_complete'];
const cancellation = new AbortController();
let failureDirectory;
let readingInput = true, step = 0;
const cancel = () => { cancellation.abort(); if (readingInput) process.stdin.destroy(); };
process.on('SIGTERM', cancel); process.on('SIGINT', cancel);
const bytes = value => [...Buffer.from(JSON.stringify(value), 'utf8')];
const hash = value => createHash('sha256').update(Buffer.from(value)).digest('hex');
function outcome(error) {
  let name;
  try { name = error?.name; } catch { return 'internal'; }
  return ERRORS.has(name) ? name : 'internal';
}
class RuntimeCleanupFailure extends Error {
  constructor(primary, failures) {
    super('runtime_cleanup_failed'); this.primary = primary ? outcome(primary) : null; this.failures = failures;
  }
}
async function input() {
  const chunks = []; let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > 1048576) throw new Error('bounded_input');
    chunks.push(chunk);
  }
  const value = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(Buffer.concat(chunks)));
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || !isDeepStrictEqual(Object.keys(value).sort(), ['binary', 'inputs', 'observer_config', ...(['wrong_dense', 'wrong_sparse', 'wrong_profile'].includes(value.scenario) ? ['scenario'] : []), 'supervisor_config', 'work_dir', 'writer_config'])
    || typeof value.binary !== 'string' || typeof value.work_dir !== 'string' || !value.inputs?.stages) throw new Error('input_shape');
  return value;
}
async function expected(Type, operation) {
  try { await operation(); } catch (error) { if (error instanceof Type) return; throw error; }
  throw new Error('expected_failure_missing');
}
async function expectedAbort(operation) {
  try { await operation(); }
  catch (error) { if (error instanceof DOMException && error.name === 'AbortError') return; throw error; }
  throw new Error('expected_abort_missing');
}
function completed(raw) {
  const value = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(Buffer.from(raw)));
  if (value?.status !== 'ok' || value?.result?.status !== 'completed') throw new Error('write_not_completed');
}
async function observedListener(address, absent = false) {
  const parsed = new URL(address);
  if (parsed.protocol !== 'http:' || parsed.hostname !== '127.0.0.1' || !parsed.port || parsed.origin !== address) throw new Error('endpoint_shape');
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

async function cases(value) {
  const inputs = value.inputs;
  const writerConfig = parse_pool_config(value.writer_config), supervisorConfig = parse_pool_config(value.supervisor_config);
  if (writerConfig.max_size !== 1 || supervisorConfig.max_size !== 1) throw new Error('two_client_ceiling');
  const options = {deadline: now() + 110, signal: cancellation.signal};
  const resource = new PoolResource(writerConfig), supervisorResource = new PoolResource(supervisorConfig);
  const writer = new PostgresQdrantWriter(resource, inputs.config, inputs.instance_id);
  const supervisor = new ManagedQdrantSupervisor(value.binary, value.work_dir, inputs.instance_id, inputs.config);
  const verifier = new QdrantReconciliationVerifier(writer, supervisor);
  const recovery = new PostgresQdrantRecovery(supervisorResource, inputs.config, supervisor, verifier);
  const authority = new PostgresQdrantPublicationAuthority(writer, recovery);
  const transport = new ManagedQdrantPublicationTransport(supervisor);
  const checks = [], snapshots = [], managers = new Set(), handles = new Set();
  const injection = {armed: false, fired: 0, destroyed: 0};
  const stageFault = {kind: null, target: null, fired: 0, destroyed: 0, inserts: 0, dml: 0};
  const publicationFault = {armed:false,track:false,fired:0,destroyed:0,casWrites:0,dml:0};
  const http = {requests: 0, puts: 0, drop: false, dropped: 0};
  const wrongDense = {armed: false, fired: 0, observed: null};
  const corruptionScenario = ['wrong_dense', 'wrong_sparse', 'wrong_profile'].includes(value.scenario) ? value.scenario : null;
  let address, primary, manager, callbackMode = null, supervisorLeases = 0;
  const target = '/collections/' + inputs.config.physical_collection;
  const context = (stage, scope = inputs.scope) => ({scope, collection: stage.manifest.collection,
    document_id: stage.manifest.document_id, intent_id: stage.intent.intent_id, owner_token: OWNER});
  const reference = stage => ({collection: stage.manifest.collection,
    document_id: stage.manifest.document_id, intent_id: stage.intent.intent_id});
  const ledger = () => new ExecutionLedger({limits: {deadline_ms: 60000, max_attempts: 1, max_provider_calls: 0}, deadline: options.deadline});
  function accounting(book, exact = false) {
    const state = book.snapshot();
    if (state.provider_calls !== 0 || state.candidates !== 0 || state.pending !== 0
      || state.attempts > 1 || exact && state.attempts !== 1) throw new Error('ledger_accounting');
  }
  async function call(operation, book = ledger(), callOptions = options) {
    try { return await operation(book, callOptions); }
    finally { accounting(book); }
  }
  function save(result) {
    if (!result || !isDeepStrictEqual(Object.keys(result).sort(), [...RESULT_KEYS].sort())
      || !['stage', 'publish'].includes(result.operation)
      || typeof result.intent_id !== 'string' || typeof result.state !== 'string'
      || !['revision_id', 'generation_id'].every(key => result[key] === null || typeof result[key] === 'string')
      || !RESULT_KEYS.slice(5).every(key => typeof result[key] === 'boolean')) throw new Error('public_result_shape');
    snapshots.push(RESULT_KEYS.map(key => RESULT_KEYS.indexOf(key) >= 5 ? String(result[key]) : result[key]));
    return result;
  }
  const stageCall = (stage, scope = inputs.scope, actor = manager, book = ledger()) =>
    call((ledger, opts) => actor.stage(stage, scope, ledger, opts), book);
  const publishCall = (stage, scope = inputs.scope, actor = manager, callOptions = options, book = ledger()) =>
    call((ledger, opts) => actor.publish(reference(stage), scope, ledger, opts), book, callOptions);
  async function transaction(pool, operation, scoped = null) {
    return pool.withLease(options, async (client, signal) => {
      const lease = {deadline: options.deadline, signal};
      const query = async (text, values = []) => (await bounded(client.query({text, values, rowMode: 'array'}), lease)).rows;
      let begun = false;
      try {
        await query('BEGIN ISOLATION LEVEL READ COMMITTED'); begun = true;
        await query('SET LOCAL search_path=pg_catalog');
        if (scoped) {
          await query("SELECT set_config('cragkit_qdrant.tenant_id',$1,true),set_config('cragkit_qdrant.collection',$2,true),set_config('cragkit_qdrant.principal_id',$3,true),set_config('cragkit_qdrant.grant_ids',$4,true),set_config('cragkit_qdrant.authorization_revision',$5,true),set_config('cragkit_qdrant.writer_document_id',$6,true),set_config('cragkit_qdrant.writer_intent_id',$7,true),set_config('cragkit_qdrant.writer_owner_token',$8,true),set_config('cragkit_qdrant.backend_instance_id',$9,true)",
            [scoped.scope.tenant_id, scoped.collection, scoped.scope.principal_id, JSON.stringify(scoped.scope.grant_ids),
              scoped.scope.authorization_revision, scoped.document_id, scoped.intent_id, OWNER, inputs.instance_id]);
        } else await query("SELECT set_config('cragkit_qdrant.backend_instance_id',$1,true)", [inputs.instance_id]);
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
  const backend = () => transaction(supervisorResource, query => query('SELECT instance_id,backend_namespace,storage_identity,supervisor_id,epoch::text,state,recovery_id FROM cragkit_qdrant.backend_instances WHERE instance_id=$1', [inputs.instance_id]));
  const journal = () => transaction(supervisorResource, query => query('SELECT intent_id,dispatch_id,state,completion_sha256 FROM cragkit_qdrant.dispatch_journal WHERE instance_id=$1 ORDER BY intent_id,sequence', [inputs.instance_id]));
  async function active(generation, scope = inputs.scope) {
    const snapshot = await writer.manager_snapshot(context(inputs.stage, scope), options);
    if (snapshot.document?.active_generation_id !== generation) throw new Error('active_generation_changed');
    return snapshot;
  }
  async function authorize(scope) {
    const mode = callbackMode;
    if (!mode || mode.fired) return true;
    const stored = await writer.inspect(context(mode.stage, scope), options);
    if (stored?.state !== 'prepared') return true;
    mode.fired = true;
    if (mode.kind === 'cancel') {
      mode.controller.abort();
      throw new DOMException('Operation aborted.', 'AbortError');
    }
    if (mode.kind === 'session') {
      const leases = supervisorLeases;
      await expected(ProviderUnavailable, () => supervisor.recover({recovery_id: 'forbidden-manager-final', old_epoch: 1, new_epoch: 2}, options));
      await expected(ProviderUnavailable, () => recovery.initialize(options));
      if (supervisorLeases !== leases) throw new Error('excluded_recovery_started_sql');
      const binding = supervisor.control_binding();
      if (binding.epoch !== 1 || binding.recovery !== null) throw new Error('excluded_recovery_mutated_controller');
    } else if (mode.kind === 'revoke') {
      await writer.apply_security({action: 'update_authorization', intent_id: 'manager-security-change',
        tenant_id: scope.tenant_id, collection: inputs.stage.manifest.collection, document_id: inputs.stage.manifest.document_id,
        expected_authorization_revision: 'auth-1', expected_mutation_epoch: 1,
        authorization: {authorization_revision: 'auth-manager-2', principal_ids: [], grant_ids: [],
          language: null, kind: null, tag: null, tombstoned: false}}, scope, {...options, owner_token: OWNER});
    }
    return true;
  }
  async function createManager(callback = authorize) {
    const actor = new QdrantPublicationManager(authority, transport, inputs.config, supervisor, callback);
    managers.add(actor); await actor.initialize(options); return actor;
  }
  async function provision(admin, probe) {
    await admin.request('PUT', target, {...options, body: bytes(inputs.collection_config)});
    await admin.request('PUT', '/collections/' + probe.collection, {...options, body: bytes(probe.collection_config)});
    completed(await admin.request('PUT', '/collections/' + probe.collection + '/points?wait=true&ordering=strong',
      {...options, body: bytes({points: [probe.point]})}));
  }
  const realLease = resource.withLease.bind(resource);
  resource.withLease = (opts, operation) => realLease(opts, (client, signal) => {
    let preparation = false, unknown = false, targetStage = false, stageUnknown = false,
      publicationCas = false, publicationUnknown = false;
    return operation({
      async query(query) {
        if (stageFault.target && /^(?:INSERT INTO|UPDATE|DELETE FROM) cragkit_qdrant\./.test(query.text)) stageFault.dml++;
        if (publicationFault.track && /^(?:INSERT INTO|UPDATE|DELETE FROM) cragkit_qdrant\./.test(query.text)) publicationFault.dml++;
        const result = await client.query(query);
        if (/^BEGIN\b/.test(query.text)) { preparation = publicationCas = false; targetStage = false; }
        if (publicationFault.armed && query.text.startsWith('UPDATE cragkit_qdrant.documents SET active_generation_id=')) {
          publicationCas = true;publicationFault.casWrites++;
        }
        if (stageFault.target && /^INSERT INTO cragkit_qdrant\.publication_intents\b/.test(query.text)
          && query.values?.includes(stageFault.target)) {
          targetStage = true; stageFault.inserts++;
          if (stageFault.kind === 'rollback') {
            stageFault.kind = null; stageFault.fired++; throw new ProviderUnavailable();
          }
        }
        if (query.text === 'COMMIT' && targetStage && stageFault.kind === 'ack') {
          stageFault.kind = null; stageFault.fired++; stageUnknown = true;
          throw Object.assign(new Error('closed_stage_commit_fault'), {code: '08006'});
        }
        if(query.text==='COMMIT'&&publicationCas&&publicationFault.armed){
          publicationFault.armed=false;publicationFault.fired++;publicationUnknown=true;
          throw Object.assign(new Error('closed_publication_commit_fault'),{code:'08006'});
        }
        if (/^INSERT INTO cragkit_qdrant\.preparations\b/.test(query.text)) preparation = true;
        if (query.text === 'COMMIT' && preparation && injection.armed) {
          injection.armed = false; injection.fired++; unknown = true;
          throw Object.assign(new Error('closed_commit_fault'), {code: '08006'});
        }
        return result;
      },
      getTransactionStatus: () => client.getTransactionStatus(),
      release(destroy) {
        if(publicationUnknown){
          if(destroy!==true)throw new Error('publication_unknown_client_reused');
          publicationFault.destroyed++;publicationUnknown=false;
        }
        if (stageUnknown) {
          if (destroy !== true) throw new Error('stage_unknown_client_reused');
          stageFault.destroyed++; stageUnknown = false;
        }
        if (unknown) {
          if (destroy !== true) throw new Error('unknown_commit_client_reused');
          injection.destroyed++; unknown = false;
        }
        client.release(destroy);
      },
    }, signal);
  });
  const realSupervisorLease = supervisorResource.withLease.bind(supervisorResource);
  supervisorResource.withLease = (...args) => { supervisorLeases++; return realSupervisorLease(...args); };
  try {
    await supervisor.initialize({...options, provision}); address = supervisor.identity().endpoint;
    await observedListener(address);
    const realTransportFor = supervisor.transport_for.bind(supervisor);
    supervisor.transport_for = capability => {
      const actual = realTransportFor(capability);
      const observed = {
        async request(method, path, requestOptions) {
          http.requests++;
          const upsert = method === 'PUT' && path === target + '/points?wait=true&ordering=strong';
          if (upsert) http.puts++;
          const response = await actual.request(method, path, requestOptions);
          if (upsert && wrongDense.armed) {
            const body = JSON.parse(Buffer.from(requestOptions.body).toString('utf8'));
            const ids = inputs.stages[corruptionScenario].manifest.members.map(member => member.point_id).sort();
            if (isDeepStrictEqual(body.points?.map(point => point.id).sort(), ids)) {
              completed(response);
              wrongDense.armed = false; wrongDense.fired++;
              const basis = body.points.filter(point => point.vector?.dense?.[0] === 1
                && point.vector.dense.slice(1).every(value => value === 0));
              if (basis.length !== 1) throw new Error('wrong_dense_basis_input');
              const point = structuredClone(basis[0]);
              const dense = point.vector?.dense;
              if (!Array.isArray(dense) || dense.length < 2 || dense[0] !== 1
                || dense.slice(1).some(value => value !== 0)) throw new Error('wrong_dense_basis_input');
              if (corruptionScenario === 'wrong_sparse') {
                const sparse = point.vector.sparse;
                if (!Array.isArray(sparse?.indices) || !Array.isArray(sparse.values)
                  || sparse.indices.length !== sparse.values.length || sparse.values.length === 0
                  || !sparse.values.every(Number.isFinite)) throw new Error('wrong_sparse_basis_input');
                sparse.values[0] += .25;
              } else if (corruptionScenario === 'wrong_profile') {
                if (!point.payload?.dense_profile || typeof point.payload.dense_profile.model !== 'string'
                  || point.payload.dense_profile.model === 'wrong-profile') throw new Error('wrong_profile_basis_input');
                point.payload.dense_profile.model = 'wrong-profile';
              } else point.vector.dense = dense.map((_, index) => index === 1 ? 1 : 0);
              completed(await actual.request('PUT', path, {...requestOptions, body: bytes({points: [point]})}));
              wrongDense.observed = {point, ids, points: body.points.map(original => original.id === point.id ? point : original)};
            }
          }
          if (upsert && http.drop) {
            completed(response); http.drop = false; http.dropped++;
            throw new ProviderUnavailable();
          }
          return response;
        },
        async close() { await actual.close(); handles.delete(observed); },
      };
      handles.add(observed); return observed;
    };
    await resource.open(); await supervisorResource.open(); manager = await createManager();
    const identity = supervisor.identity();
    if (!isDeepStrictEqual(await backend(), [[inputs.instance_id, inputs.config.backend_namespace,
      identity.storage_identity, identity.supervisor_id, '1', 'open', null]])) throw new Error('public_manager_registration');
    if (corruptionScenario !== null) {
      const staged = save(await stageCall(inputs.stage));
      const published = save(await publishCall(inputs.stage));
      if (staged.state !== 'staged' || !published.published || !published.replica_complete
        || http.puts !== 1) throw new Error('wrong_dense_base_publication');
      const successor = inputs.stages[corruptionScenario];
      const successorStaged = save(await stageCall(successor));
      if (successor.manifest.members.length !== 2 || successorStaged.state !== 'staged'
        || successorStaged.published || successorStaged.replica_complete) throw new Error('wrong_dense_successor_stage');
      const before = await observeStage(successor);
      const baseBefore = await observeStage(inputs.stage);
      wrongDense.armed = true;
      await expected(IntegrityViolation, () => publishCall(successor));
      const after = await observeStage(successor);
      const baseAfter = await observeStage(inputs.stage);
      const stored = wrongDense.observed;
      if (wrongDense.armed || wrongDense.fired !== 1 || !stored || http.puts !== 2) throw new Error('wrong_dense_fault_not_exact');
      const current = await writer.manager_snapshot(context(successor), options);
      const probeAttempt = supervisor.issue_attempt({intent_id: successor.intent.intent_id,
        owner_token: current.owner.owner_token, epoch: current.backend.epoch,
        dispatch_id: 'manager-' + corruptionScenario.replaceAll('_', '-') + '-readback'}, options);
      const probe = supervisor.transport_for(probeAttempt);
      let physical;
      try {
        physical = JSON.parse(Buffer.from(await probe.request('POST', target + '/points',
          {...options, body: bytes({ids: stored.ids, with_payload: true, with_vector: true})})).toString('utf8'));
      } finally { await probe.close(); }
      const corrupted = physical.result?.find(point => point.id === stored.point.id);
      if (physical.status !== 'ok' || !isDeepStrictEqual(physical.result?.map(point => point.id).sort(), stored.ids)
        || !isDeepStrictEqual(corrupted?.vector, stored.point.vector)
        || !isDeepStrictEqual(corrupted?.payload, stored.point.payload)) throw new Error('wrong_dense_physical_fault_missing');
      if (corruptionScenario !== 'wrong_dense') {
        const byId = points => points.map(({id, vector, payload}) => ({id, vector, payload})).sort((a, b) => a.id.localeCompare(b.id));
        if (!isDeepStrictEqual(byId(physical.result), byId(stored.points))) throw new Error('public_corruption_physical_readback_changed');
      }
      for (const key of ['document_revisions', 'generations', 'members', 'point_claims', 'vector_replays']) {
        if (!isDeepStrictEqual(before[key], after[key]) || !isDeepStrictEqual(baseBefore[key], baseAfter[key])) throw new Error('wrong_dense_immutable_graph_changed');
      }
      const dispatches = (await journal()).filter(row => row[0] === successor.intent.intent_id);
      if (!isDeepStrictEqual(after.pointer, [[inputs.stage.manifest.generation_id]])
        || !isDeepStrictEqual(baseBefore.publication_intents, baseAfter.publication_intents)
        || !isDeepStrictEqual(baseBefore.pointer, baseAfter.pointer)
        || after.generations.length !== 1 || after.generations[0][0].published !== false
        || after.generations[0][0].ever_published !== false || after.publication_intents.length !== 1
        || after.publication_intents[0][0].state !== 'writing'
        || after.publication_intents[0][0].authority_committed !== false
        || after.publication_intents[0][0].replica_complete !== false
        || current.pending !== false || current.intent?.state !== 'writing'
        || current.intent?.authority_committed !== false || current.intent?.replica_complete !== false
        || dispatches.length !== 1 || dispatches[0][2] !== 'settled' || !/^[0-9a-f]{64}$/.test(dispatches[0][3])
        || await writer.publication_preparation(context(successor), options) !== null
        || snapshots.length !== 3) throw new Error('wrong_dense_publication_fence_changed');
      await active(inputs.stage.manifest.generation_id);
      checks.push({wrong_dense: 'wrong_dense_vector_public_publish_rejected',
        wrong_sparse: 'wrong_sparse_vector_public_publish_rejected',
        wrong_profile: 'wrong_full_profile_public_publish_rejected'}[corruptionScenario]); step = checks.length;
      return {runtime: 'typescript', checks, proof_scope: 'public_corruption_only', public_snapshots_sha256: hash(bytes(snapshots))};
    }
    checks.push(CHECKS[0]); step = checks.length;

    const baseBook = ledger(); const baseStaged = save(await stageCall(inputs.stage, inputs.scope, manager, baseBook)); accounting(baseBook, true);
    if (baseStaged.state !== 'staged' || baseStaged.authority_committed || baseStaged.replica_complete || baseStaged.published) throw new Error('public_stage_state');
    const budgetSnapshot = await active(null);
    if (http.puts !== 0) throw new Error('stage_mutated_replica');
    const budgetJournal = await journal();
    const budgetActivity = [http.requests, http.puts];
    if (budgetJournal.length !== 0) throw new Error('staged_budget_fixture_has_dispatch');
    await expected(BudgetExhausted, () => publishCall(inputs.stage, inputs.scope, manager, options, baseBook));
    if (!isDeepStrictEqual(await journal(), budgetJournal)
      || !isDeepStrictEqual(await active(null), budgetSnapshot)
      || !isDeepStrictEqual([http.requests, http.puts], budgetActivity)) throw new Error('spent_ledger_mutated_stage_or_dispatch');
    checks.push(CHECKS[1]); step = checks.length;

    const basePublished = save(await publishCall(inputs.stage));
    if (!basePublished.published || !basePublished.replica_complete || !basePublished.authority_committed || http.puts !== 1) throw new Error('actual_public_publish');
    await active(inputs.stage.manifest.generation_id);
    const initialJournal = await journal();
    if (initialJournal.length !== 1 || initialJournal[0][2] !== 'settled' || !/^[0-9a-f]{64}$/.test(initialJournal[0][3])) throw new Error('actual_completed_journal');
    checks.push(CHECKS[2]); step = checks.length;

    const beforeHistorical = http.puts;
    const historicalStage = save(await stageCall(inputs.stage)); const historicalPublish = save(await publishCall(inputs.stage));
    if (!isDeepStrictEqual(historicalStage, {...basePublished, operation: 'stage'})
      || !isDeepStrictEqual(historicalPublish, basePublished) || http.puts !== beforeHistorical) throw new Error('historical_replay_resent');
    checks.push(CHECKS[3]); step = checks.length;

    const changed = structuredClone(inputs.stage); changed.intent.initial_authorization.tag = 'changed';
    await expected(IntegrityViolation, () => stageCall(changed));
    if (http.puts !== beforeHistorical) throw new Error('changed_stage_mutated_replica');
    checks.push(CHECKS[4]); step = checks.length;

    for (const [callback, Type] of [[async () => false, UnauthorizedScope], [async () => 'yes', InvalidRequest],
      [async () => { throw new Error('closed_authorizer_fault'); }, ProviderUnavailable]]) {
      const deniedManager = await createManager(callback);
      try { await expected(Type, () => stageCall(inputs.stages.denied_input, inputs.scope, deniedManager)); }
      finally { await deniedManager.close(); managers.delete(deniedManager); }
    }
    if (await writer.inspect(context(inputs.stages.denied_input), options) !== null || http.puts !== beforeHistorical) throw new Error('authorizer_created_work');
    checks.push(CHECKS[5]); step = checks.length;

    async function observeStage(stage) {
      const observer = new PoolResource(parse_pool_config({...value.observer_config, max_size: 1}));
      try {
        await observer.open();
        return await observer.withLease(options, async (client, signal) => {
          const query = async (text, values = []) => (await bounded(client.query({text, values, rowMode: 'array'}),
            {deadline: options.deadline, signal})).rows;
          await query('BEGIN READ ONLY');
          try {
            const graph = {};
            const key = [stage.manifest.tenant_id, stage.manifest.collection, stage.manifest.document_id];
            for (const [table, field, id] of [
              ['publication_intents', 'intent_id', stage.intent.intent_id],
              ['document_revisions', 'revision_id', stage.manifest.revision_id],
              ['generations', 'generation_id', stage.manifest.generation_id],
              ['members', 'generation_id', stage.manifest.generation_id],
              ['vector_replays', 'generation_id', stage.manifest.generation_id],
              ['point_claims', 'generation_id', stage.manifest.generation_id],
              ['document_owners', 'intent_id', stage.intent.intent_id],
            ]) graph[table] = await query(`SELECT to_jsonb(t) FROM cragkit_qdrant.${table} t WHERE (tenant_id,collection,document_id)=($1,$2,$3) AND ${field}=$4 ORDER BY to_jsonb(t)::text`, [...key, id]);
            graph.pointer = await query('SELECT active_generation_id FROM cragkit_qdrant.documents WHERE (tenant_id,collection,document_id)=($1,$2,$3)', key);
            await query('COMMIT'); return graph;
          } catch (error) { await query('ROLLBACK'); throw error; }
        });
      } finally { await observer.close(); }
    }
    const stageRequests = http.requests;
    stageFault.kind = 'rollback'; stageFault.target = inputs.stages.stage_rollback.intent.intent_id;
    await expected(ProviderUnavailable, () => stageCall(inputs.stages.stage_rollback));
    const rolledBack = await observeStage(inputs.stages.stage_rollback);
    if (stageFault.kind !== null || stageFault.fired !== 1 || stageFault.inserts !== 1
      || Object.entries(rolledBack).some(([key, rows]) => key !== 'pointer' && rows.length !== 0)
      || !isDeepStrictEqual(rolledBack.pointer, [[inputs.stage.manifest.generation_id]])
      || http.requests !== stageRequests) throw new Error('stage_rollback_not_atomic');

    stageFault.kind = 'ack'; stageFault.target = inputs.stages.stage_ack_loss.intent.intent_id;
    const ackStage = await stageCall(inputs.stages.stage_ack_loss);
    const committedStage = await observeStage(inputs.stages.stage_ack_loss);
    const committedDml = stageFault.dml;
    const memberCount = inputs.stages.stage_ack_loss.manifest.members.length;
    if (stageFault.kind !== null || stageFault.fired !== 2 || stageFault.destroyed !== 1 || stageFault.inserts !== 2
      || ackStage.state !== 'staged' || committedStage.publication_intents.length !== 1
      || committedStage.document_revisions.length !== 1 || committedStage.generations.length !== 1
      || ['members', 'vector_replays', 'point_claims'].some(key => committedStage[key].length !== memberCount)
      || committedStage.document_owners.length !== 0
      || !isDeepStrictEqual(committedStage.pointer, [[inputs.stage.manifest.generation_id]])) throw new Error('stage_ack_graph_incomplete');
    const freshWriter = new PostgresQdrantWriter(resource, inputs.config, inputs.instance_id);
    const freshVerifier = new QdrantReconciliationVerifier(freshWriter, supervisor);
    const freshRecovery = new PostgresQdrantRecovery(supervisorResource, inputs.config, supervisor, freshVerifier);
    const freshAuthority = new PostgresQdrantPublicationAuthority(freshWriter, freshRecovery);
    const freshManager = new QdrantPublicationManager(freshAuthority, transport, inputs.config, supervisor, authorize);
    managers.add(freshManager);
    try {
      await freshManager.initialize(options);
      const restored = await freshWriter.load_stage(context(inputs.stages.stage_ack_loss), options);
      if (!isDeepStrictEqual(stage_data(restored), stage_data(prepare_stage(inputs.stages.stage_ack_loss)))) throw new Error('stage_ack_reconstruction_changed');
      const replayStage = await stageCall(inputs.stages.stage_ack_loss, inputs.scope, freshManager);
      if (!isDeepStrictEqual(replayStage, ackStage) || stageFault.dml !== committedDml || stageFault.inserts !== 2 || http.requests !== stageRequests
        || !isDeepStrictEqual(await observeStage(inputs.stages.stage_ack_loss), committedStage)) throw new Error('stage_ack_retry_mutated_graph');
    } finally {
      await freshManager.close(); managers.delete(freshManager);
      await freshRecovery.close(); await freshVerifier.close(); await freshWriter.close();
    }

    // Fixture-admin corruption of a committed stage, not a public half-commit.
    const partialStage = inputs.stages.stage_ack_loss;
    const missingChunk = partialStage.manifest.members[0].chunk_id;
    const fixtureAdmin = new PoolResource(parse_pool_config({...value.observer_config, max_size: 1}));
    try {
      await fixtureAdmin.open();
      const removed = await transaction(fixtureAdmin, query => query('DELETE FROM cragkit_qdrant.members WHERE (tenant_id,collection,document_id,generation_id,chunk_id)=($1,$2,$3,$4,$5) RETURNING chunk_id',
        [partialStage.manifest.tenant_id, partialStage.manifest.collection, partialStage.manifest.document_id,
          partialStage.manifest.generation_id, missingChunk]));
      if (!isDeepStrictEqual(removed, [[missingChunk]])) throw new Error('partial_member_fixture_delete_not_exact');
    } finally { await fixtureAdmin.close(); }
    const partialGraph = await observeStage(partialStage);
    if (memberCount !== 2 || partialGraph.generations.length !== 1
      || partialGraph.generations[0][0].expected_member_count !== 2 || partialGraph.generations[0][0].published !== false
      || partialGraph.members.length !== 1 || partialGraph.publication_intents[0]?.[0]?.state !== 'staged'
      || !isDeepStrictEqual(partialGraph.point_claims, committedStage.point_claims)
      || !isDeepStrictEqual(partialGraph.vector_replays, committedStage.vector_replays)
      || !isDeepStrictEqual(partialGraph.pointer, [[inputs.stage.manifest.generation_id]])) throw new Error('partial_member_fixture_not_observed');
    const partialCounts = [http.requests, http.puts];
    await expected(IntegrityViolation, () => publishCall(partialStage));
    if (!isDeepStrictEqual([http.requests, http.puts], partialCounts)
      || !isDeepStrictEqual(await observeStage(partialStage), partialGraph)) throw new Error('partial_member_publication_mutated_graph');

    save(await stageCall(inputs.stages.loser)); save(await stageCall(inputs.stages.winner));
    publicationFault.armed=publicationFault.track=true;
    const winner=save(await publishCall(inputs.stages.winner));
    const winnerGraph=await observeStage(inputs.stages.winner);
    if(!winner.published||winner.state!=='published'||publicationFault.armed||publicationFault.fired!==1
      ||publicationFault.destroyed!==1||publicationFault.casWrites!==1
      ||!isDeepStrictEqual(winnerGraph.pointer,[[inputs.stages.winner.manifest.generation_id]])
      ||winnerGraph.publication_intents[0]?.[0]?.state!=='published'
      ||winnerGraph.publication_intents[0]?.[0]?.replica_complete!==true
      ||winnerGraph.generations[0]?.[0]?.published!==true
      ||winnerGraph.generations[0]?.[0]?.ever_published!==true)throw new Error('publication_commit_not_exact');
    const publicationAfter={dml:publicationFault.dml,requests:http.requests};
    const publicationRetry=await createManager();
    try{
      const historical=await publishCall(inputs.stages.winner,inputs.scope,publicationRetry);
      if(!isDeepStrictEqual(historical,winner)||!isDeepStrictEqual(publicationAfter,{dml:publicationFault.dml,requests:http.requests})
        ||!isDeepStrictEqual(await observeStage(inputs.stages.winner),winnerGraph))throw new Error('publication_commit_retry_mutated');
    }finally{await publicationRetry.close();managers.delete(publicationRetry);}
    publicationFault.track=false;
    const winnerPuts = http.puts;
    const conflict = save(await publishCall(inputs.stages.loser));
    if (conflict.state !== 'conflict' || conflict.published || http.puts !== winnerPuts) throw new Error('manager_cas_conflict');
    await active(inputs.stages.winner.manifest.generation_id);
    checks.push(CHECKS[6]); step = checks.length;

    save(await stageCall(inputs.stages.prepared));
    const localCancel = new AbortController();
    callbackMode = {kind: 'cancel', stage: inputs.stages.prepared, controller: localCancel, fired: false};
    await expectedAbort(() => publishCall(inputs.stages.prepared, inputs.scope, manager,
      {...options, signal: AbortSignal.any([cancellation.signal, localCancel.signal])}));
    if (!callbackMode.fired || (await writer.inspect(context(inputs.stages.prepared), options))?.state !== 'prepared') throw new Error('prepared_cancel_not_durable');
    await active(inputs.stages.winner.manifest.generation_id);
    callbackMode = null;
    const preparedBefore = await writer.publication_preparation(context(inputs.stages.prepared), options);
    const preparedPuts = http.puts;
    await manager.close(); managers.delete(manager); manager = await createManager();
    const resumed = save(await publishCall(inputs.stages.prepared));
    const preparedAfter = await writer.publication_preparation(context(inputs.stages.prepared), options);
    if (!resumed.published || http.puts !== preparedPuts || preparedBefore.preparation.readback_sha256 !== preparedAfter.preparation.readback_sha256) throw new Error('prepared_resume_changed_or_resent');
    checks.push(CHECKS[7]); step = checks.length;

    save(await stageCall(inputs.stages.commit)); injection.armed = true;
    const commitPuts = http.puts; const committed = save(await publishCall(inputs.stages.commit));
    if (!committed.published || injection.armed || injection.fired !== 1 || injection.destroyed !== 1
      || http.puts !== commitPuts + 1) throw new Error('preparation_commit_loss_not_reconciled');
    checks.push(CHECKS[8]); step = checks.length;

    save(await stageCall(inputs.stages.session)); callbackMode = {kind: 'session', stage: inputs.stages.session, fired: false};
    const session = save(await publishCall(inputs.stages.session));
    if (!callbackMode.fired || !session.published) throw new Error('finalization_exclusion_not_observed');
    callbackMode = null; await active(inputs.stages.session.manifest.generation_id);
    checks.push(CHECKS[9]); step = checks.length;

    save(await stageCall(inputs.stages.revoked)); callbackMode = {kind: 'revoke', stage: inputs.stages.revoked, fired: false};
    const revoked = save(await publishCall(inputs.stages.revoked));
    if (!callbackMode.fired || revoked.state !== 'denied' || revoked.published) throw new Error('late_revocation_not_denied');
    callbackMode = null;
    const freshScope = {...inputs.scope, authorization_revision: 'auth-manager-2'};
    await active(inputs.stages.session.manifest.generation_id, freshScope);
    checks.push(CHECKS[10]); step = checks.length;

    const freshPuts = http.puts;
    const freshStage = save(await stageCall(inputs.stage, freshScope)); const freshPublish = save(await publishCall(inputs.stage, freshScope));
    const fresh = await active(inputs.stages.session.manifest.generation_id, freshScope);
    const acl = await transaction(resource, query => query('SELECT authorization_revision,mutation_epoch::text,principal_ids,grant_ids FROM cragkit_qdrant.documents WHERE (tenant_id,collection,document_id)=($1,$2,$3)',
      [freshScope.tenant_id, inputs.stage.manifest.collection, inputs.stage.manifest.document_id]), context(inputs.stage, freshScope));
    if (fresh.document.authorization_revision !== 'auth-manager-2' || fresh.document.mutation_epoch !== 2
      || !isDeepStrictEqual(freshStage, {...basePublished, operation: 'stage'}) || !isDeepStrictEqual(freshPublish, basePublished)
      || !isDeepStrictEqual(acl, [['auth-manager-2', '2', [], []]]) || http.puts !== freshPuts) throw new Error('historical_replay_replaced_acl');
    checks.push(CHECKS[11]); step = checks.length;

    const bootstrapGraph = await observeStage(inputs.stage);
    const bootstrapAcl = await transaction(resource, query => query('SELECT authorization_revision,mutation_epoch::text,principal_ids,grant_ids FROM cragkit_qdrant.documents WHERE (tenant_id,collection,document_id)=($1,$2,$3)',
      [freshScope.tenant_id, inputs.stage.manifest.collection, inputs.stage.manifest.document_id]), context(inputs.stage, freshScope));
    const bootstrapCounts = [publicationFault.dml, http.requests, http.puts];
    const changedBootstrap = structuredClone(inputs.stage);
    changedBootstrap.intent.initial_authorization.grant_ids = ['grant-manager-bootstrap-changed'];
    changedBootstrap.intent.initial_authorization.tag = 'changed-manager-bootstrap-after-security';
    publicationFault.track = true;
    try { await expected(IntegrityViolation, () => stageCall(changedBootstrap, freshScope)); }
    finally { publicationFault.track = false; }
    const bootstrapAfter = await observeStage(inputs.stage);
    const bootstrapAclAfter = await transaction(resource, query => query('SELECT authorization_revision,mutation_epoch::text,principal_ids,grant_ids FROM cragkit_qdrant.documents WHERE (tenant_id,collection,document_id)=($1,$2,$3)',
      [freshScope.tenant_id, inputs.stage.manifest.collection, inputs.stage.manifest.document_id]), context(inputs.stage, freshScope));
    if (!isDeepStrictEqual(bootstrapAfter, bootstrapGraph) || !isDeepStrictEqual(bootstrapAclAfter, bootstrapAcl)
      || !isDeepStrictEqual([publicationFault.dml, http.requests, http.puts], bootstrapCounts)) throw new Error('changed_bootstrap_mutated_current_authority');
    save(await stageCall(inputs.stages.lost_ack, freshScope)); http.drop = true;
    const lostPuts = http.puts;
    await expected(ProviderUnavailable, () => publishCall(inputs.stages.lost_ack, freshScope));
    const unknown = (await journal()).filter(row => row[0] === inputs.stages.lost_ack.intent.intent_id);
    if (http.drop || http.dropped !== 1 || http.puts !== lostPuts + 1
      || unknown.length !== 1 || unknown[0][2] !== 'unknown' || unknown[0][3] !== null) throw new Error('lost_ack_not_unknown');
    await manager.close(); managers.delete(manager); manager = await createManager();
    await expected(ProviderUnavailable, () => publishCall(inputs.stages.lost_ack, freshScope));
    if (http.puts !== lostPuts + 1 || !isDeepStrictEqual((await journal()).filter(row => row[0] === inputs.stages.lost_ack.intent.intent_id), unknown)) throw new Error('unknown_dispatch_resent_or_changed');
    await active(inputs.stages.session.manifest.generation_id, freshScope);
    checks.push(CHECKS[12]); step = checks.length;

    await manager.close(); managers.delete(manager);
    await writer.initialize(options);
    const profile = supervisor.profile_binding(inputs.config);
    if (!profile.alive || profile.epoch !== 1 || profile.recovery !== null || profile.sealed) throw new Error('borrowed_controller_closed');
    await writer.manager_snapshot(context(inputs.stages.lost_ack, freshScope), options);
    await recovery.initialize(options); await backend();
    if (http.puts !== lostPuts + 1 || handles.size !== 0 || snapshots.length !== 19) throw new Error('borrowed_dependency_or_snapshot_count');
    checks.push(CHECKS[13], CHECKS[14], CHECKS[15], CHECKS[16], CHECKS[17], CHECKS[18], CHECKS[19]); step = checks.length;
    return {runtime: 'typescript', checks, proof_scope: 'public_stage_publish_only', public_snapshots_sha256: hash(bytes(snapshots))};
  } catch (error) { primary = error; throw error; }
  finally {
    const failures = [];
    const cleanupDeadline = now() + 12;
    const owned = [...managers].map(actor => ['manager_close', actor]);
    if (typeof transport.close === 'function') owned.push(['transport_close', transport]);
    owned.push(...[...handles].map(handle => ['transport_close', handle]), ['recovery_close', recovery],
      ['verifier_close', verifier], ['writer_close', writer], ['resource_close', resource],
      ['supervisor_resource_close', supervisorResource], ['controller_close', supervisor]);
    for (const [operation, owner] of owned) {
      try { await bounded(Promise.resolve().then(() => owner.close()), {deadline: Math.max(now() + .001, Math.min(now() + 8, cleanupDeadline))}); }
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
  const value = await bounded(input(), {deadline: now() + 5, signal: cancellation.signal}); readingInput = false;
  failureDirectory = value.work_dir;
  process.stdout.write(JSON.stringify(await cases(value)) + '\n');
} catch (error) {
  if(failureDirectory){
    const locations=[...String(error?.stack??'').matchAll(/(?:packages\/typescript\/(?:dist|src)|tools)\/[a-zA-Z0-9_.\/-]+:\d+:\d+/g)]
      .map(match=>match[0]);
    try{writeFileSync(join(failureDirectory,'failure-locations.json'),JSON.stringify(locations)+'\n',{mode:0o600});}catch{}
  }
  process.stdout.write(JSON.stringify(error instanceof RuntimeCleanupFailure
    ? {ok: false, step, error: 'cleanup_failed', primary: error.primary, cleanup: error.failures}
    : {ok: false, step, error: outcome(error)}) + '\n');
  process.exitCode = 1;
} finally {
  process.removeListener('SIGTERM', cancel); process.removeListener('SIGINT', cancel);
}
