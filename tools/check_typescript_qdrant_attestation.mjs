/** Actual native G0 receipts, recovery and same-intent attestation. */
import {execFile} from 'node:child_process';
import {isDeepStrictEqual as same} from 'node:util';
import {PoolResource, parse_pool_config, bounded, now} from '../packages/typescript/dist/postgres-pool.js';
import {ExecutionLedger} from '../packages/typescript/dist/execution.js';
import {QdrantPublicationManager, PostgresQdrantPublicationAuthority, ManagedQdrantPublicationTransport,
  PostgresQdrantWriter, PostgresQdrantRecovery, ManagedQdrantSupervisor,
  QdrantReconciliationVerifier} from '../packages/typescript/dist/qdrant-publication.js';
import {prepare_stage} from '../packages/typescript/dist/qdrant-writer.js';
import {QdrantPublicationVerifier} from '../packages/typescript/dist/qdrant-publication-verification.js';
import {publication_finalization} from '../packages/typescript/dist/qdrant-publication-worker.js';
import {IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability} from '../packages/typescript/dist/errors.js';
const OWNER = '00000000-0000-4000-8000-000000000001';
const SECOND_OWNER = '00000000-0000-4000-8000-000000000002';
const CHECKS = Object.freeze([
  'native_g1_published_and_g2_prepared',
  'unrelated_document_recovery_preserves_prepared_intent_and_original_preparation',
  'current_f1_receipt_requires_live_finalization_and_original_writer',
  'actual_attestation_commit_ack_loss_reconciles_same_key',
  'exact_receipt_retry_preserves_attestation_without_mutation',
  'contradictory_verification_binding_is_denied',
  'copied_and_stale_receipts_and_context_are_denied',
  'interruption_preserves_prior_active_and_original_preparation',
  'same_prepared_intent_and_generation_publish_at_current_epoch',
  'current_security_change_denies_attestation_and_preserves_active',
]);
const ERRORS = new Set(['IntegrityViolation','InvalidRequest','ProviderUnavailable','UnauthorizedScope',
  'UnsupportedCapability','DeadlineExceeded','IndexNotReady','AbortError']);
const cancellation = new AbortController();
let readingInput = true, step = 0;
const cancel = () => { cancellation.abort(); if (readingInput) process.stdin.destroy(); };
process.on('SIGTERM', cancel); process.on('SIGINT', cancel);
const bytes = value => [...Buffer.from(JSON.stringify(value), 'utf8')];
function outcome(error) { let name; try { name = error?.name; } catch { return 'internal'; } return ERRORS.has(name) ? name : 'internal'; }
class RuntimeCleanupFailure extends Error {
  constructor(primary, failures) { super('runtime_cleanup_failed'); this.primary = primary ? outcome(primary) : null; this.failures = failures; }
}
async function input() {
  const chunks = []; let length = 0;
  for await (const chunk of process.stdin) { length += chunk.length; if (length > 1048576) throw new Error('bounded_input'); chunks.push(chunk); }
  const value = JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks)));
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || !same(Object.keys(value).sort(), ['binary','inputs','supervisor_config','work_dir','writer_config'])
    || typeof value.binary !== 'string' || typeof value.work_dir !== 'string' || !value.inputs?.second_stage
    || !value.inputs?.stages?.prepared || !value.inputs?.stages?.revoked) throw new Error('input_shape');
  return value;
}
async function denied(operation, allowed = [InvalidRequest, UnsupportedCapability, ProviderUnavailable, UnauthorizedScope]) {
  try { await operation(); } catch (error) { if (allowed.some(Type => error instanceof Type)) return; throw error; }
  throw new Error('expected_denial_missing');
}
function completed(raw) { const value = JSON.parse(Buffer.from(raw).toString('utf8')); if (value?.status !== 'ok' || value?.result?.status !== 'completed') throw new Error('write_not_completed'); }
async function listener(address, absent = false) {
  const parsed = new URL(address);
  if (parsed.protocol !== 'http:' || parsed.hostname !== '127.0.0.1' || !parsed.port || parsed.origin !== address) throw new Error('endpoint_shape');
  return new Promise((resolve,reject) => execFile('/usr/sbin/lsof',['-nP','-a','-iTCP@127.0.0.1:'+parsed.port,'-sTCP:LISTEN','-t'],
    {encoding:'utf8',env:{PATH:'/usr/bin:/bin'},maxBuffer:1024,timeout:3000,killSignal:'SIGKILL'},(error,stdout,stderr) => {
      if (absent && error?.code === 1 && stdout === '' && stderr === '') return resolve(null);
      if (error || stderr || absent || !/^[1-9][0-9]{0,9}\n?$/.test(stdout)) return reject(new Error('listener_observation'));
      resolve(Number(stdout.trim()));
    }));
}
async function cases(value) {
  const inputs = value.inputs;
  const writerConfig = parse_pool_config(value.writer_config), supervisorConfig = parse_pool_config(value.supervisor_config);
  if (writerConfig.max_size !== 1 || supervisorConfig.max_size !== 1) throw new Error('two_client_ceiling');
  const options = {deadline:now()+150,signal:cancellation.signal};
  const resource = new PoolResource(writerConfig), supervisorResource = new PoolResource(supervisorConfig);
  const writer = new PostgresQdrantWriter(resource,inputs.config,inputs.instance_id);
  const supervisor = new ManagedQdrantSupervisor(value.binary,value.work_dir,inputs.instance_id,inputs.config);
  const reconciliation = new QdrantReconciliationVerifier(writer,supervisor);
  const recovery = new PostgresQdrantRecovery(supervisorResource,inputs.config,supervisor,reconciliation);
  const verifier = new QdrantPublicationVerifier(writer,supervisor);
  const wrongWriter = new PostgresQdrantWriter(resource,inputs.config,inputs.instance_id);
  const wrongVerifier = new QdrantPublicationVerifier(wrongWriter,supervisor);
  const authority = new PostgresQdrantPublicationAuthority(writer,recovery);
  const transport = new ManagedQdrantPublicationTransport(supervisor);
  const checks = [], handles = new Set();
  const fault = {armed:false,fired:0,destroyed:0,inserts:0};
  let manager, address, primary, puts = 0, cancelStage = null;
  const target = '/collections/'+inputs.config.physical_collection;
  const context = (stage,owner = OWNER,scope = inputs.scope) => ({scope,collection:stage.manifest.collection,
    document_id:stage.manifest.document_id,intent_id:stage.intent.intent_id,owner_token:owner});
  const reference = stage => ({collection:stage.manifest.collection,document_id:stage.manifest.document_id,intent_id:stage.intent.intent_id});
  const ledger = () => new ExecutionLedger({limits:{deadline_ms:120000,max_attempts:1,max_provider_calls:0},deadline:options.deadline});
  const mark = () => { checks.push(CHECKS[checks.length]); step = checks.length; };
  async function active(generation,scope = inputs.scope) {
    const snapshot = await writer.manager_snapshot(context(inputs.stage,OWNER,scope),options);
    if (snapshot.document?.active_generation_id !== generation) throw new Error('prior_active_changed');
    return snapshot;
  }
  async function prepare(stage) {
    await manager.stage(stage,inputs.scope,ledger(),options);
    const local = new AbortController(); cancelStage = {stage,local,fired:false};
    try { await manager.publish(reference(stage),inputs.scope,ledger(),{...options,signal:AbortSignal.any([options.signal,local.signal])}); throw new Error('prepare_not_interrupted'); }
    catch (error) { if (!(error instanceof DOMException && error.name === 'AbortError')) throw error; }
    if (!cancelStage.fired) throw new Error('prepare_callback_missing'); cancelStage = null;
    const stored = await writer.manager_snapshot(context(stage),options);
    if (stored.intent?.state !== 'prepared' || !stored.owner) throw new Error('not_prepared');
    return context(stage,stored.owner.owner_token);
  }
  async function receipt(ctx,epoch,id) {
    const attempt = supervisor.issue_attempt({intent_id:ctx.intent_id,owner_token:ctx.owner_token,epoch,dispatch_id:id},options);
    return {attempt,receipt:await verifier.verify(attempt,ctx,options)};
  }
  async function recover(id,contexts,epoch) {
    const proof = await recovery.recover(id,options);
    for (const ctx of contexts) {
      const advanced = await recovery.advance_owner(proof,ctx,options);
      if (!same(advanced,{owner_token:ctx.owner_token,backend_epoch:epoch})) throw new Error('owner_changed');
    }
    if (!same(await recovery.reopen(proof,options),{state:'open',epoch})) throw new Error('reopen_failed');
  }
  const realLease = resource.withLease.bind(resource);
  resource.withLease = (opts,operation) => realLease(opts,(client,signal) => {
    let inserted = false, unknown = false;
    return operation({async query(query) {
      const result = await client.query(query);
      if (/^BEGIN\b/.test(query.text)) inserted = false;
      if (/^INSERT INTO cragkit_qdrant\.preparation_attestations\b/.test(query.text)) { inserted = true; fault.inserts++; }
      if (query.text === 'COMMIT' && inserted && fault.armed) {
        fault.armed = false; fault.fired++; unknown = true;
        throw Object.assign(new Error('closed_commit_fault'),{code:'08006'});
      }
      return result;
    },getTransactionStatus:()=>client.getTransactionStatus(),release(destroy) {
      if (unknown) { if (destroy !== true) throw new Error('unknown_client_reused'); fault.destroyed++; unknown = false; }
      client.release(destroy);
    }},signal);
  });
  try {
    await supervisor.initialize({...options,provision:async (admin,probe) => {
      await admin.request('PUT',target,{...options,body:bytes(inputs.collection_config)});
      await admin.request('PUT','/collections/'+probe.collection,{...options,body:bytes(probe.collection_config)});
      completed(await admin.request('PUT','/collections/'+probe.collection+'/points?wait=true&ordering=strong',{...options,body:bytes({points:[probe.point]})}));
    }});
    address = supervisor.identity().endpoint; await listener(address);
    const actualTransport = supervisor.transport_for.bind(supervisor);
    supervisor.transport_for = capability => {
      const actual = actualTransport(capability);
      const handle = {async request(method,path,opts) {
        if (method === 'PUT' && path === target+'/points?wait=true&ordering=strong') puts++;
        return actual.request(method,path,opts);
      },async close() { await actual.close(); handles.delete(handle); }};
      handles.add(handle); return handle;
    };
    await resource.open(); await supervisorResource.open();
    manager = new QdrantPublicationManager(authority,transport,inputs.config,supervisor,async scope => {
      if (cancelStage && !cancelStage.fired) {
        const stored = await writer.inspect(context(cancelStage.stage,OWNER,scope),options);
        if (stored?.state === 'prepared') { cancelStage.fired = true; cancelStage.local.abort(); throw new DOMException('Operation aborted.','AbortError'); }
      }
      return true;
    });
    await manager.initialize(options);
    await manager.stage(inputs.stage,inputs.scope,ledger(),options);
    if (!(await manager.publish(reference(inputs.stage),inputs.scope,ledger(),options)).published) throw new Error('g1_not_published');
    const ctx = await prepare(inputs.stages.prepared);
    const original = await writer.publication_preparation(ctx,options);
    const initialIntent = await writer.inspect(ctx,options);
    const stale = await receipt(ctx,1,'attestation-stale');
    await active(inputs.stage.manifest.generation_id); mark();

    const second = context(inputs.second_stage,SECOND_OWNER,inputs.second_scope);
    await writer.stage(prepare_stage(inputs.second_stage),inputs.second_scope,{...options,owner_token:SECOND_OWNER});
    await writer.acquire_owner(second,options);
    const oldPid = await listener(address);
    await recover('g0-native-recovery',[ctx,second],2);
    if (await listener(address) === oldPid || !same(await writer.inspect(ctx,options),initialIntent)
      || !same((await writer.attestation_snapshot(ctx,options)).preparation,original.preparation)) throw new Error('recovery_changed_prepared');
    mark();

    const current = await receipt(ctx,2,'attestation-current');
    const before = puts;
    await denied(()=>writer.attest_prepared(current.receipt,verifier,options));
    await publication_finalization(supervisor,current.attempt,async()=> {
      await denied(()=>writer.attest_prepared(current.receipt,wrongVerifier,options));
    },options);
    if (puts !== before || fault.inserts !== 0) throw new Error('guard_mutated'); mark();

    fault.armed = true;
    const attested = await publication_finalization(supervisor,current.attempt,
      ()=>writer.attest_prepared(current.receipt,verifier,options),options);
    if (!attested.attestation || attested.intent.state !== 'prepared' || attested.attestation.backend_epoch !== 2
      || attested.attestation.verification_id !== 'attestation-current' || attested.attestation.owner_token !== ctx.owner_token
      || attested.attestation.intent_id !== ctx.intent_id || fault.armed || fault.fired !== 1 || fault.destroyed !== 1
      || fault.inserts !== 1 || puts !== before) throw new Error('attestation_ack_loss'); mark();
    const retry = await publication_finalization(supervisor,current.attempt,
      ()=>writer.attest_prepared(current.receipt,verifier,options),options);
    if (!same(retry,attested) || fault.inserts !== 1 || puts !== before) throw new Error('retry_changed'); mark();

    const contradiction = await receipt(ctx,2,'attestation-contradiction');
    await publication_finalization(supervisor,contradiction.attempt,()=>denied(
      ()=>writer.attest_prepared(contradiction.receipt,verifier,options),[IntegrityViolation]),options); mark();
    await publication_finalization(supervisor,current.attempt,async()=> {
      await denied(()=>writer.attest_prepared(JSON.parse(JSON.stringify(current.receipt)),verifier,options));
      await denied(()=>writer.attest_prepared(stale.receipt,verifier,options));
    },options);
    await denied(()=>writer.attest_prepared(current.receipt,verifier,options)); mark();

    const paused = await writer.attestation_snapshot(ctx,options);
    if (!same(paused.preparation,original.preparation) || !same(paused.attestation,attested.attestation)
      || !same(await writer.inspect(ctx,options),initialIntent) || puts !== before || fault.inserts !== 1) throw new Error('paused_state_changed');
    await active(inputs.stage.manifest.generation_id); mark();
    const published = await publication_finalization(supervisor,current.attempt,()=>writer.publish(ctx,options),options);
    if (published.state !== 'published' || published.generation_id !== initialIntent.generation_id || puts !== before) throw new Error('same_intent_publish_failed');
    await active(inputs.stages.prepared.manifest.generation_id); mark();

    const revoked = await prepare(inputs.stages.revoked);
    await recover('g0-native-security',[revoked],3);
    const revokedReceipt = await receipt(revoked,3,'attestation-revoked');
    const security = await writer.manager_snapshot(revoked,options);
    await writer.apply_security({action:'update_authorization',intent_id:'g0-security-change',tenant_id:inputs.scope.tenant_id,
      collection:revoked.collection,document_id:revoked.document_id,
      expected_authorization_revision:security.document.authorization_revision,expected_mutation_epoch:security.document.mutation_epoch,
      authorization:{authorization_revision:'auth-g0-revoked',principal_ids:[],grant_ids:[],language:null,kind:null,tag:null,tombstoned:false}},
    inputs.scope,{...options,owner_token:revoked.owner_token});
    const insertCount = fault.inserts;
    await publication_finalization(supervisor,revokedReceipt.attempt,async()=> {
      try {
        const result = await writer.attest_prepared(revokedReceipt.receipt,verifier,options);
        if (result.intent.state !== 'denied' || result.attestation !== null) throw new Error('security_not_denied');
      } catch (error) { if (!(error instanceof UnauthorizedScope)) throw error; }
    },options);
    await active(inputs.stages.prepared.manifest.generation_id,{...inputs.scope,authorization_revision:'auth-g0-revoked'});
    if (fault.inserts !== insertCount) throw new Error('security_inserted_attestation'); mark();
    await manager.close(); manager = undefined;
    await writer.initialize(options);
    if (!supervisor.profile_binding(inputs.config).alive) throw new Error('borrowed_controller_closed');
    return {runtime:'typescript',checks,proof_scope:'native_prepared_attestation_only'};
  } catch (error) { primary = error; throw error; }
  finally {
    const failures = [], deadline = now()+12;
    const owned = [...(manager?[['manager_close',manager]]:[]),['transport_close',transport],
      ...[...handles].map(handle=>['transport_close',handle]),['verifier_close',verifier],
      ['wrong_verifier_close',wrongVerifier],['reconciliation_close',reconciliation],['recovery_close',recovery],['writer_close',writer],['wrong_writer_close',wrongWriter],
      ['resource_close',resource],['supervisor_resource_close',supervisorResource],['controller_close',supervisor]];
    for (const [operation,owner] of owned) {
      try { await bounded(Promise.resolve().then(()=>owner.close()),{deadline:Math.max(now()+.001,Math.min(now()+8,deadline))}); }
      catch (error) { failures.push({operation,outcome:outcome(error)}); }
    }
    if (address) { try { await listener(address,true); } catch (error) { failures.push({operation:'listener_close',outcome:outcome(error)}); } }
    if (failures.length) throw new RuntimeCleanupFailure(primary,failures);
  }
}
try {
  const value = await bounded(input(),{deadline:now()+5,signal:cancellation.signal}); readingInput = false;
  process.stdout.write(JSON.stringify(await cases(value))+'\n');
} catch (error) {
  process.stdout.write(JSON.stringify(error instanceof RuntimeCleanupFailure
    ? {ok:false,step,error:'cleanup_failed',primary:error.primary,cleanup:error.failures}
    : {ok:false,step,error:outcome(error)})+'\n'); process.exitCode = 1;
} finally { process.removeListener('SIGTERM',cancel); process.removeListener('SIGINT',cancel); }
