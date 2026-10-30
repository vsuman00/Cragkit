/** Native managed purge acceptance. Private configuration arrives on stdin. */
import http from 'node:http';
import {execFile} from 'node:child_process';
import {createHash} from 'node:crypto';
import {isDeepStrictEqual as same} from 'node:util';
import {writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {PoolResource, parse_pool_config, bounded, now} from '../packages/typescript/dist/postgres-pool.js';
import {ExecutionLedger} from '../packages/typescript/dist/execution.js';
import {parse_request} from '../packages/typescript/dist/requests.js';
import {QdrantPublicationManager, PostgresQdrantPublicationAuthority, ManagedQdrantPublicationTransport, PostgresQdrantWriter, PostgresQdrantRecovery, ManagedQdrantSupervisor, QdrantReconciliationVerifier} from '../packages/typescript/dist/qdrant-publication.js';
import {QdrantSecurityManager} from '../packages/typescript/dist/qdrant-security.js';
import {PostgresQdrantSourceStore} from '../packages/typescript/dist/qdrant-source.js';
import {settle_purge_guarded} from '../packages/typescript/dist/qdrant-recovery.js';
import {QdrantSecurityVerifier} from '../packages/typescript/dist/qdrant-security-verification.js';
import {security_projection_data, purge_projection_data} from '../packages/typescript/dist/qdrant-writer.js';
import {ProviderUnavailable, UnauthorizedScope, InvalidRequest, IntegrityViolation, UnsupportedCapability} from '../packages/typescript/dist/errors.js';
const POLICY = 'erase_managed_source_and_replay_v1';
const CHECKS = [
  'published_retained_and_unknown_put_erased_with_claims_retained',
  'source_denied_before_and_after_managed_erasure',
  'completed_purge_retry_is_metadata_only',
  'lost_delete_ack_requires_actual_refence_before_erasure',
  'ordinary_purge_owner_handoff_resumes_without_guard_bypass',
  'lost_erasure_commit_confirms_exact_retained_history',
  'ownerless_tombstone_bootstrap_and_forged_receipt_refusal',
  'unknown_extra_or_foreign_scope_cannot_authorize_erasure'
];
const FAULT_CHECKS = ['current_credential_pending_delete_refused','administrative_foreign_intent_pending_refused_and_restored','replaced_owner_refused_before_erasure','changed_authority_refused_before_erasure','superseded_purge_handoff_commit_loss_resumes_without_mutation'];
const ERRORS = new Set([
  'InvalidRequest',
  'IntegrityViolation',
  'ProviderUnavailable',
  'UnauthorizedScope',
  'UnsupportedCapability',
  'DeadlineExceeded',
  'IndexNotReady',
  'BudgetExhausted',
  'AbortError'
]);
const OWNER = '00000000-0000-4000-8000-000000000001';
const controller = new AbortController();
let reading = true, step = 0, failureDirectory;
const cancel = () => {
  controller.abort();
  if (reading)process.stdin.destroy();
};
process.on('SIGTERM', cancel);
process.on('SIGINT', cancel);
const assert = value => {
  if (!value) throw new Error('acceptance_failed');
};
const bytes = value => [...Buffer.from(JSON.stringify(value),'utf8')];
const hash = value => createHash('sha256').update(value).digest('hex');
const decode = value => JSON.parse(new TextDecoder('utf-8', {
  fatal: true
}).decode(Buffer.from(value)));
async function input() {
  let size = 0;
  const chunks = [];
  for await(const chunk of process.stdin) {
    size += chunk.length;
    assert(size <= 1048576);
    chunks.push(chunk);
  }
  const value = decode(Buffer.concat(chunks));
  assert(value
    && same(Object.keys(value).sort(), ['admin_config','binary','inputs','reader_config','supervisor_config','work_dir','writer_config'])
    && typeof value.binary === 'string'
    && typeof value.work_dir === 'string');
  return value;
}
async function listener(address, absent = false) {
  const url = new URL(address);
  assert(url.protocol === 'http:' && url.hostname === '127.0.0.1' && url.port && url.origin === address);
  return new Promise((resolve, reject) => execFile('/usr/sbin/lsof', ['-nP','-a','-iTCP@127.0.0.1:'+url.port,'-sTCP:LISTEN','-t'], {
    encoding:'utf8', env: {
      PATH:'/usr/bin:/bin'
    }, maxBuffer: 1024, timeout: 3000, killSignal:'SIGKILL'
  }, (error, out, err) => {
    if (absent && error?.code === 1 && out === '' && err === '') return resolve();
    if (error || err || absent || !/^[1-9][0-9]{0,9}\n?$/.test(out)) return reject(new Error('listener_observation'));
    resolve();
  }));
}
async function refuses(Type, work) {
  try {
    await work();
  } catch (error) {
    if (error instanceof Type)return;
    throw error;
  }
  throw new Error('refusal_missing');
}
function completed(raw) {
  const body = decode(raw);
  assert(body?.status === 'ok' && body?.result?.status === 'completed');
}
async function cases(value) {
  const {inputs} = value;
  const configs = [value.writer_config, value.supervisor_config, value.reader_config].map(parse_pool_config);
  assert(configs.every(config => config.max_size === 1));
  const options = {deadline: now()+180, signal: controller.signal};
  const sql = {dml: 0, bodies: 0, rollbackArmed: false, rollback: 0,
    commitArmed: false, drops: 0, functions: 0, confirming: false,
    confirmations: 0, readonly: 0, confirmationWrites: 0, confirmationBodies: 0,
    handoffArmed: false, handoffDrops: 0};
  const dml = text => /^\s*(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE)\b/i.test(text)
    || text.startsWith('SELECT cragkit_qdrant.erase_purged_document(');
  const bodies = text => {
    const selected = /^\s*SELECT\s+([\s\S]+?)\s+FROM\s+cragkit_qdrant\.(?:document_revisions|members|vector_replays|dispatch_journal)\b/i.exec(text);
    if (!selected) return false;
    const fields = selected[1].replace(/\b(?:canonical_utf8|dense_blob|sparse_blob|excerpt_utf8|request_bytes)\s+IS\s+(?:NOT\s+)?NULL\b/gi, 'body_marker');
    return /\b(?:canonical_utf8|dense_blob|sparse_blob|excerpt_utf8|request_bytes)\b/.test(fields);
  };
  const vanilla = new PoolResource(configs[0]);
  const nativeFactory = vanilla.factory;
  assert(typeof nativeFactory === 'function');
  const writerPool = new PoolResource(configs[0], {factory: async config => {
    const actual = await nativeFactory(config);
    return {
      async connect() {
        const client = await actual.connect();
        let erased = false, handed = false;
        return {
          async query(query) {
            const text = query.text;
            if (text.startsWith('BEGIN')) {
              erased = handed = false;
              if (sql.confirming) sql.confirmations++;
            }
            if (dml(text)) sql.dml++;
            if (bodies(text)) sql.bodies++;
            if (sql.confirming) {
              if (text === 'SET TRANSACTION READ ONLY') sql.readonly++;
              if (dml(text)) sql.confirmationWrites++;
              if (bodies(text)) sql.confirmationBodies++;
            }
            const result = await client.query(query);
            if(sql.handoffArmed && text.startsWith('UPDATE cragkit_qdrant.document_owners SET '))handed=true;
            if (text.startsWith('SELECT cragkit_qdrant.erase_purged_document(')) {
              sql.functions++;
              erased = true;
              if (sql.rollbackArmed) {
                sql.rollbackArmed = false;
                sql.rollback++;
                throw new IntegrityViolation();
              }
            }
            if (text === 'COMMIT' && erased && sql.commitArmed) {
              sql.commitArmed = false;
              sql.drops++;
              sql.confirming = true;
              sql.httpAtConfirmation = httpCount;
              throw Object.assign(new Error('commit_reply_withheld'), {code:'08006'});
            }
            if(text==='COMMIT'&&handed&&sql.handoffArmed){
              sql.handoffArmed=false;sql.handoffDrops++;
              throw Object.assign(new Error('handoff_commit_reply_withheld'),{code:'08006'});
            }
            if (text === 'COMMIT' && sql.confirming) {
              assert(httpCount === sql.httpAtConfirmation);
              sql.confirming = false;
            }
            return result;
          },
          getTransactionStatus() { return client.getTransactionStatus(); },
          release(destroy) { client.release(destroy); }
        };
      },
      end() { return actual.end(); }
    };
  }});
  const fault = {mode:null,owned:0,current:0,foreign:0,settlements:0};
  const supervisorPool = new PoolResource(configs[1], {factory:async config=>{
    const actual=await nativeFactory(config);
    return {async connect(){const client=await actual.connect();return {
      async query(query){const result=await client.query(query);
        if(query.text.startsWith("UPDATE cragkit_qdrant.dispatch_journal SET state='settled'"))fault.settlements++;
        if(fault.mode&&query.text.startsWith('SELECT dispatch_id,instance_id,sequence,owner_token::text,backend_epoch,credential_generation,operation,recovery,request_sha256,created_xid::text,state,completion_sha256')){
          fault.owned++;if(result.rows.some(row=>row[5]===generation()&&row[10]==='unknown'))fault.current++;
        }
        if(fault.mode&&query.text.startsWith('SELECT intent_id FROM cragkit_qdrant.dispatch_journal')&&result.rows.length)fault.foreign++;
        return result;
      },getTransactionStatus(){return client.getTransactionStatus();},release(destroy){client.release(destroy);}
    };},end(){return actual.end();}};
  }});
  const pools = [writerPool, supervisorPool, new PoolResource(configs[2])];
  const writer = new PostgresQdrantWriter(pools[0], inputs.config, inputs.instance_id);
  const supervisor = new ManagedQdrantSupervisor(value.binary, value.work_dir, inputs.instance_id, inputs.config);
  const verifier = new QdrantReconciliationVerifier(writer, supervisor);
  const recovery = new PostgresQdrantRecovery(pools[1], inputs.config, supervisor, verifier);
  const authority = new PostgresQdrantPublicationAuthority(writer, recovery);
  const transport = new ManagedQdrantPublicationTransport(supervisor);
  const documents = Object.values(inputs.documents);
  const allowed = async(scope, collection, document) => scope.tenant_id === inputs.scope.tenant_id
    && documents.some(item => item.stage.manifest.collection === collection && item.stage.manifest.document_id === document);
  const security = new QdrantSecurityManager(writer, allowed);
  const manager = new QdrantPublicationManager(authority, transport, inputs.config, supervisor, allowed);
  const store = new PostgresQdrantSourceStore(pools[2], inputs.config);
  const handles = new Set(), observations = [], faultChecks = [];
  const faultVerifier=new QdrantSecurityVerifier(writer,supervisor);
  let capturedProof;
  const originalRecover=recovery.recover;
  recovery.recover=async function(...args){capturedProof=await originalRecover.apply(this,args);return capturedProof;};
  let address, httpCount = 0, armed = null, putDrops = 0, deleteDrops = 0;
  const deleteBodies = [];
  const nativeRequest = http.request;
  const pointPath = '/collections/'+inputs.config.physical_collection+'/points';
  const scope = revision => ({...inputs.scope, authorization_revision: revision});
  const ref = record => ({collection:record.collection, document_id:record.document_id, intent_id:record.intent_id});
  const context = (record, revision='auth-2', owner_token=OWNER) => ({...ref(record), scope:scope(revision), owner_token});
  async function call(work, attempts=1) {
    const ledger = new ExecutionLedger({limits:{deadline_ms:180000,max_attempts:1,max_provider_calls:0},deadline:options.deadline});
    try { return await work(ledger); }
    finally {
      const state = ledger.snapshot();
      assert(state.attempts === attempts && state.provider_calls === 0 && state.pending === 0);
    }
  }
  const stage = record => call(book => manager.stage(record, inputs.scope, book, options));
  const purge = (item, revision='auth-2') => call(book => manager.purge(item.purge,scope(revision),book,POLICY,options));
  const snapshot = item => writer.manager_snapshot(context(item.purge), options);
  async function tombstone(item) {
    const result = await call(book => security.tombstone(item.tombstone,inputs.scope,book,options));
    assert(result.authority_committed && !result.replica_complete && !result.purge_complete);
  }
  async function setup(item, ownerless=false) {
    await stage(item.stage);
    if (!ownerless) {
      const result = await call(book => manager.publish(ref(item.stage.intent),inputs.scope,book,options));
      assert(result.published);
      await stage(item.second_stage);
      if(item.published_second){
        const second=await call(book=>manager.publish(ref(item.second_stage.intent),inputs.scope,book,options));
        assert(second.published);
      }
    }
  }
  const row = result => [result.intent_id,result.operation,result.state,result.authority_committed,result.replica_complete,result.purge_complete];
  function complete(result) {
    assert(Object.keys(result).length === 9 && result.operation === 'purge' && result.state === 'complete'
      && result.authority_committed && result.replica_complete && result.purge_complete && !result.published);
  }
  function mark(result) { complete(result); observations.push(row(result)); step++; }
  const generation = () => supervisor.control_binding().credential_generation;
  const graph = projection => security_projection_data(purge_projection_data(projection,writer).projection,writer);
  const project = (item, owner_token) => writer.project_purge(context(item.purge,'auth-2',owner_token),POLICY,options);
  async function source(item, revision) {
    const nominee = {point_id:item.expected_points[0].id,branch:'dense',score:1,score_kind:'cosine_similarity',
      score_direction:'higher_is_better',verification:'UNVERIFIED',payload:structuredClone(item.expected_points[0].payload)};
    const request = parse_request({query:'native source verification',collection:item.stage.manifest.collection});
    const handle = store.open_request(request,{...options,scope:scope(revision)});
    handles.add(handle);
    const result = await handle.fetch_candidate(nominee,{max_source_bytes:16777216,include_source:true});
    if (result.state === 'verified') {
      const canonical = Buffer.from(item.stage.canonical_text,'utf8');
      const member = item.stage.manifest.members.find(entry => entry.point_id === nominee.point_id);
      const excerpt = canonical.subarray(member.start_byte,member.end_byte);
      assert(result.binding && result.evidence.text === new TextDecoder('utf-8',{fatal:true}).decode(excerpt)
        && result.evidence.source_sha256 === hash(canonical) && result.evidence.text_sha256 === hash(excerpt)
        && result.private_source.canonical_text === item.stage.canonical_text);
    } else unavailable(result);
    return {handle,result};
  }
  function unavailable(result) {
    assert(result.state === 'unavailable' && result.binding === null && result.evidence === null
      && result.private_source === null && result.source_bytes === 0);
  }
  async function closeSource(pair) { await pair.handle.close(); handles.delete(pair.handle); }
  http.request = function(requestOptions, callback) {
    httpCount++;
    const mode = requestOptions?.method === 'PUT' && requestOptions.path === pointPath+'?wait=true&ordering=strong' ? 'upsert'
      : requestOptions?.method === 'POST' && requestOptions.path === pointPath+'/delete?wait=true&ordering=strong' ? 'delete' : null;
    const drop = armed !== null && armed === mode;
    if (drop) armed = null;
    const request = nativeRequest.call(this,requestOptions,incoming => {
      if (!drop) return callback(incoming);
      const chunks = [];
      let size = 0, suppressed = false;
      const originalOnce = incoming.once;
      incoming.on('data',chunk => { size += chunk.length; if (size <= 1048576) chunks.push(Buffer.from(chunk)); });
      originalOnce.call(incoming,'end',() => {
        try {
          assert(suppressed && size <= 1048576 && incoming.statusCode === 200);
          completed(Buffer.concat(chunks));
          if (mode === 'delete') deleteDrops++; else putDrops++;
        } catch {}
        incoming.emit('error',new ProviderUnavailable());
      });
      incoming.once = function(event, listener) {
        if (event === 'end' && !suppressed) { suppressed = true; return this; }
        return originalOnce.call(this,event,listener);
      };
      try { callback(incoming); } finally { incoming.once = originalOnce; }
    });
    if (mode === 'delete') {
      const chunks = [];
      const originalWrite = request.write, originalEnd = request.end;
      request.write = function(chunk,...args) { if (chunk) chunks.push(Buffer.from(chunk)); return originalWrite.call(this,chunk,...args); };
      request.end = function(chunk,...args) {
        if (chunk && typeof chunk !== 'function') chunks.push(Buffer.from(chunk));
        deleteBodies.push(decode(Buffer.concat(chunks)).points);
        return originalEnd.call(this,chunk,...args);
      };
    }
    return request;
  };
  try {
    await supervisor.initialize({...options,provision:async(admin,probe) => {
      await admin.request('PUT','/collections/'+inputs.config.physical_collection,{...options,body:bytes(inputs.collection_config)});
      await admin.request('PUT','/collections/'+probe.collection,{...options,body:bytes(probe.collection_config)});
      completed(await admin.request('PUT','/collections/'+probe.collection+'/points?wait=true&ordering=strong',
        {...options,body:bytes({points:[probe.point]})}));
    }});
    address = supervisor.identity().endpoint;
    await listener(address);
    for (const pool of pools) await pool.open();
    await manager.initialize(options);
    await security.initialize(options);
    await store.initialize(options);

    const base = inputs.documents.base;
    await setup(base);
    const retained = await source(base,'auth-1');
    assert(retained.result.state === 'verified');
    armed = 'upsert';
    await refuses(ProviderUnavailable,() => call(book => manager.publish(ref(base.second_stage.intent),inputs.scope,book,options)));
    const unknown = await writer.manager_snapshot(context(base.second_stage.intent,'auth-1'),options);
    assert(putDrops === 1 && unknown.pending && unknown.document.active_generation_id === base.stage.manifest.generation_id);
    const oldGeneration = generation();
    await tombstone(base);
    unavailable(await retained.handle.release(retained.result.binding,{purpose:'final',max_source_bytes:16777216,include_source:true}));
    await closeSource(retained);
    const denied = await source(base,'auth-2'); unavailable(denied.result); await closeSource(denied);
    const baseResult = await purge(base);
    assert(generation() !== oldGeneration && deleteBodies.length === 1);
    const baseIds = [...base.stage.manifest.members,...base.second_stage.manifest.members].map(member => member.point_id).sort();
    assert(same([...deleteBodies[0]].sort(),baseIds) && baseIds.length === 4);
    mark(baseResult);

    const erased = await source(base,'auth-2'); unavailable(erased.result); await closeSource(erased);
    observations.push(['source','verified','unavailable','unavailable']); step++;
    let before = {http:httpCount,dml:sql.dml,bodies:sql.bodies};
    const retry = await purge(base);
    assert(same(retry,baseResult) && same(before,{http:httpCount,dml:sql.dml,bodies:sql.bodies}));
    const newer = structuredClone(base.tombstone);
    newer.intent_id += '-newer';
    newer.expected_authorization_revision = 'auth-2'; newer.expected_mutation_epoch = 2;
    newer.authorization.authorization_revision = 'auth-3';
    await call(book => security.tombstone(newer,scope('auth-2'),book,options));
    before = {http:httpCount,dml:sql.dml,bodies:sql.bodies};
    assert(same(await purge(base,'auth-3'),baseResult) && same(before,{http:httpCount,dml:sql.dml,bodies:sql.bodies}));
    mark(retry);

    const loss = inputs.documents.delete_loss;
    await setup(loss); await tombstone(loss); armed = 'delete';
    await refuses(ProviderUnavailable,() => purge(loss));
    const pending = await snapshot(loss), fenced = generation();
    assert(deleteDrops === 1 && pending.pending && pending.backend.state === 'recovery_blocked' && !pending.intent.purge_complete);
    const lossOwner=context({...loss.purge,intent_id:pending.owner.intent_id},'auth-2',pending.owner.owner_token);
    const lossProjection=await project(loss,OWNER);
    const probeBefore={functions:sql.functions,settlements:fault.settlements,graph:graph(lossProjection)};
    fault.mode='current';
    try{await refuses(ProviderUnavailable,()=>settle_purge_guarded(recovery,faultVerifier,capturedProof,lossOwner,lossProjection,options));}
    finally{fault.mode=null;}
    assert(fault.owned>0&&fault.current>0&&fault.foreign===0&&generation()===fenced&&sql.functions===probeBefore.functions&&fault.settlements===probeBefore.settlements
      &&(await snapshot(loss)).pending&&same(graph(await project(loss,OWNER)),probeBefore.graph));
    faultChecks.push(FAULT_CHECKS[0]);
    const manifest=loss.stage.manifest;
    const key=[manifest.tenant_id,manifest.collection,manifest.document_id,loss.stage.intent.intent_id];
    const fixed=inputs.foreign_fault_sql;
    const adminConfig=parse_pool_config(value.admin_config);assert(adminConfig.max_size===1);
    async function adminWork(work,restoring=false){
      const resource=new PoolResource(adminConfig);await resource.open();
      try{return await resource.withLease(restoring?{deadline:now()+8}:options,async client=>{
        const run=async(name,values=[])=>{let index=0;const text=fixed[name].replace(/\?/g,()=>'$'+(++index));
          return (await client.query({text,values,rowMode:'array'})).rows;};
        await client.query({text:'BEGIN',rowMode:'array'});
        try{await client.query({text:'SET LOCAL statement_timeout=8000',rowMode:'array'});const result=await work(run);await client.query({text:'COMMIT',rowMode:'array'});return result;}
        catch(error){await client.query({text:'ROLLBACK',rowMode:'array'});throw error;}
      });}finally{await resource.close();}
    }
    let originalForeign,foreignInjected=false;
    try{
      originalForeign=await adminWork(async run=>{
        const rows=await run('select',key);assert(rows.length>=1&&rows.length<=256&&rows.every(row=>row.length===4&&row[1]==='settled'&&/^[0-9a-f]{64}$/.test(row[2])));
        await run('disable');assert(same(await run('inject',[...key,rows[0][0],rows[0][2]]),[[rows[0][0]]]));
        await run('enable');assert(same(await run('trigger'),[['O']]));return rows;
      });foreignInjected=true;
      fault.mode='foreign';fault.owned=0;fault.foreign=0;
      try{await refuses(ProviderUnavailable,()=>settle_purge_guarded(recovery,faultVerifier,capturedProof,lossOwner,lossProjection,options));}
      finally{fault.mode=null;}
      assert(fault.foreign>0&&fault.owned===0&&sql.functions===probeBefore.functions&&fault.settlements===probeBefore.settlements&&(await snapshot(loss)).pending
        &&same(graph(await project(loss,OWNER)),probeBefore.graph));
    }finally{
      if(foreignInjected)await adminWork(async run=>{
        await run('disable');assert(same(await run('restore',[originalForeign[0][2],...key,originalForeign[0][0]]),[[originalForeign[0][0]]]));
        await run('enable');assert(same(await run('select',key),originalForeign)&&same(await run('trigger'),[['O']]));
      },true);
    }
    faultChecks.push(FAULT_CHECKS[1]);
    const recovered = await purge(loss);
    assert(deleteDrops === 1 && generation() !== fenced); mark(recovered);

    const handoff = inputs.documents.handoff;
    await setup(handoff); await tombstone(handoff);
    const originalComplete = writer.complete_purge;
    let captured;
    writer.complete_purge = async function(...args) { captured = args; throw new ProviderUnavailable(); };
    try { await refuses(ProviderUnavailable,() => purge(handoff)); }
    finally { writer.complete_purge = originalComplete; }
    const handed = await snapshot(handoff);
    assert(captured && handed.backend.state === 'open' && !handed.pending && handed.owner.intent_id === handoff.purge.intent_id);
    const originalGraph = graph(await project(handoff,handed.owner.owner_token));
    assert(originalGraph.points.length === 4);
    before = {dml:sql.dml};
    await refuses(InvalidRequest,() => originalComplete.call(writer,captured[0],JSON.parse(JSON.stringify(captured[1])),options));
    await refuses(InvalidRequest,() => originalComplete.call(writer,captured[0],{...captured[1]},options));
    await refuses(InvalidRequest,() => originalComplete.call(writer,verifier,captured[1],options));
    try { await originalComplete.call(writer,...captured); throw new Error('expired_purge_receipt_accepted'); }
    catch(error) { if(error?.name !== 'AbortError')throw error; }
    await refuses(InvalidRequest,() => originalComplete.call(writer,captured[0],captured[1],options));
    assert(sql.dml === before.dml);
    const handoffGeneration = generation(), deletesBefore = deleteBodies.length;
    const purgeCancel = new AbortController();
    const cancelOptions = {...options, signal:AbortSignal.any([options.signal,purgeCancel.signal])};
    let reached, releaseCallback, finished;
    const callbackReached = new Promise(resolve => { reached = resolve; });
    const callbackGate = new Promise(resolve => { releaseCallback = resolve; });
    const callbackFinished = new Promise(resolve => { finished = resolve; });
    let lateErasure = false, abortedLease = false;
    writer.complete_purge = async function(...args) {
      reached();
      try {
        await callbackGate;
        abortedLease = args[2].signal.aborted;
        const result = await originalComplete.call(this,...args);
        lateErasure = true;
        return result;
      } finally { finished(); }
    };
    const canceledPurge = call(book => manager.purge(handoff.purge,scope('auth-2'),book,POLICY,cancelOptions))
      .then(() => ({success:true}),error => ({error}));
    try {
      await bounded(callbackReached,options);
      const functionsBefore = sql.functions;
      purgeCancel.abort();
      const epoch = supervisor.control_binding().epoch;
      await refuses(ProviderUnavailable,async() => supervisor.issue_attempt({intent_id:handoff.purge.intent_id,
        owner_token:handed.owner.owner_token,epoch,dispatch_id:'purge-canceled-competing-attempt'},options));
      await refuses(ProviderUnavailable,() => supervisor.recover({recovery_id:'purge-canceled-competing-recovery',old_epoch:epoch,new_epoch:epoch+1},options));
      await refuses(ProviderUnavailable,() => supervisor.close());
      assert(sql.functions === functionsBefore && !(await snapshot(handoff)).intent.purge_complete
        && same(graph(await project(handoff,handed.owner.owner_token)),originalGraph));
      releaseCallback();
      await bounded(callbackFinished,options);
      const canceled = await bounded(canceledPurge,options);
      assert(!canceled.success && canceled.error?.name === 'AbortError' && abortedLease && !lateErasure
        && sql.functions === functionsBefore && !(await snapshot(handoff)).intent.purge_complete
        && same(graph(await project(handoff,handed.owner.owner_token)),originalGraph));
    } finally {
      purgeCancel.abort();releaseCallback();
      try {
        await bounded(callbackFinished,options);
        await bounded(canceledPurge,options);
      } finally { writer.complete_purge = originalComplete; }
    }
    const replacedToken='00000000-0000-4000-8000-000000000002';
    let ownerChanged=false;
    writer.complete_purge=async function(...args){
      const state=await snapshot(handoff),originalContext=context(handoff.purge,'auth-2',state.owner.owner_token);
      const alternate={...originalContext,owner_token:replacedToken};
      const beforeFunctions=sql.functions;
      try{
        await writer.acquire_owner(alternate,options);ownerChanged=true;
        assert((await snapshot(handoff)).owner.owner_token===replacedToken);
        await refuses(ProviderUnavailable,()=>originalComplete.call(this,...args));
        assert(sql.functions===beforeFunctions&&!(await snapshot(handoff)).intent.purge_complete
          &&same(graph(await project(handoff,originalContext.owner_token)),originalGraph));
      }finally{if(ownerChanged)await writer.acquire_owner(originalContext,options);}
      throw new ProviderUnavailable();
    };
    try{await refuses(ProviderUnavailable,()=>purge(handoff));}
    finally{writer.complete_purge=originalComplete;}
    assert(ownerChanged&&(await snapshot(handoff)).owner.owner_token===handed.owner.owner_token);
    faultChecks.push(FAULT_CHECKS[2]);
    const handedResult = await purge(handoff);
    assert(generation() === handoffGeneration && deleteBodies.length === deletesBefore); mark(handedResult);

    const commitLoss = inputs.documents.commit_loss;
    await setup(commitLoss); await tombstone(commitLoss);
    let erasureContext, erasureGraph;
    writer.complete_purge = async function(...args) {
      const state = await snapshot(commitLoss);
      erasureContext = context(commitLoss.purge,'auth-2',state.owner.owner_token);
      erasureGraph = graph(await writer.project_purge(erasureContext,POLICY,options));
      return originalComplete.call(this,...args);
    };
    sql.rollbackArmed = true;
    try { await refuses(IntegrityViolation,() => purge(commitLoss)); }
    finally { writer.complete_purge = originalComplete; }
    assert(sql.rollback === 1 && same(graph(await writer.project_purge(erasureContext,POLICY,options)),erasureGraph));
    sql.commitArmed = true;
    const functionStart = sql.functions;
    const commitResult = await purge(commitLoss);
    assert(sql.functions === functionStart+1 && sql.drops === 1 && sql.confirmations === 1 && sql.readonly === 1
      && sql.confirmationWrites === 0 && sql.confirmationBodies === 0 && !sql.confirming);
    mark(commitResult);

    const ownerless = inputs.documents.ownerless;
    await setup(ownerless,true); await tombstone(ownerless);
    const admission = await writer.admit_publication(context(ownerless.stage.intent),options);
    assert(admission.intent.state === 'denied' && admission.owner === null);
    mark(await purge(ownerless));

    const authorityChange=inputs.documents.authority_change;
    await setup(authorityChange);await tombstone(authorityChange);
    let authorityChanged=false;
    writer.complete_purge=async function(...args){
      const beforeFunctions=sql.functions;
      await call(book=>security.tombstone(authorityChange.followup_tombstone,scope('auth-2'),book,options));authorityChanged=true;
      try{await originalComplete.call(this,...args);throw new Error('stale_authority_accepted');}
      catch(error){if(!(error instanceof UnauthorizedScope||error instanceof IntegrityViolation))throw error;}
      const state=await writer.manager_snapshot(context(authorityChange.purge,'auth-3'),options);
      assert(sql.functions===beforeFunctions&&!state.intent.replica_complete&&!state.intent.purge_complete&&state.document.authorization_revision==='auth-3');
      throw new UnauthorizedScope();
    };
    try{await refuses(UnauthorizedScope,()=>purge(authorityChange));}
    finally{writer.complete_purge=originalComplete;}
    assert(authorityChanged);
    const handoffBefore={functions:sql.functions,deletes:deleteBodies.length};
    sql.handoffArmed=true;
    await refuses(ProviderUnavailable,()=>call(book=>manager.purge(authorityChange.followup_purge,scope('auth-3'),book,POLICY,options)));
    const successor=await writer.manager_snapshot(context(authorityChange.followup_purge,'auth-3'),options);
    assert(sql.handoffDrops===1&&!sql.handoffArmed&&successor.owner.intent_id===authorityChange.followup_purge.intent_id
      &&successor.intent.state==='writing'&&!successor.intent.purge_complete
      &&same(handoffBefore,{functions:sql.functions,deletes:deleteBodies.length}));
    complete(await call(book=>manager.purge(authorityChange.followup_purge,scope('auth-3'),book,POLICY,options)));
    assert(deleteBodies.length===handoffBefore.deletes&&sql.functions===handoffBefore.functions+1);
    const stale=await writer.manager_snapshot(context(authorityChange.purge,'auth-3'),options);
    assert(!stale.intent.replica_complete&&!stale.intent.purge_complete);
    faultChecks.push(FAULT_CHECKS[3]);
    faultChecks.push(FAULT_CHECKS[4]);

    const extra = inputs.documents.extra;
    await setup(extra);
    const unknownId = 'ffffffff-ffff-4fff-8fff-ffffffffffff';
    const point = structuredClone(extra.expected_points[0]); point.id = unknownId;
    const attempt = supervisor.issue_attempt({intent_id:extra.stage.intent.intent_id,owner_token:OWNER,
      epoch:supervisor.control_binding().epoch,dispatch_id:'native-purge-extra-injection'},options);
    const fixture = supervisor.transport_for(attempt);
    try { completed(await fixture.request('PUT',pointPath+'?wait=true&ordering=strong',{...options,body:bytes({points:[point]})})); }
    finally { await fixture.close(); }
    await tombstone(extra);
    await refuses(IntegrityViolation,() => purge(extra));
    const exactBatches = documents.map(item => [...item.stage.manifest.members,
      ...(item === inputs.documents.ownerless ? [] : item.second_stage.manifest.members)]
      .map(member => member.point_id).sort());
    assert(deleteBodies.every(ids => !ids.includes(unknownId)
      && exactBatches.some(expected => same([...ids].sort(),expected)))
      && !(await snapshot(extra)).intent.purge_complete);
    before = {http:httpCount,dml:sql.dml};
    await refuses(UnauthorizedScope,() => call(book => manager.purge(extra.purge,{...scope('auth-2'),tenant_id:'foreign-tenant'},book,POLICY,options),0));
    await refuses(UnsupportedCapability,() => call(book => manager.purge(extra.purge,scope('auth-2'),book,'unsupported-policy',options),0));
    assert(same(before,{http:httpCount,dml:sql.dml}));
    observations.push(['refusals','integrity_violation','unauthorized_scope','unsupported_capability']); step++;
    assert(same(faultChecks,FAULT_CHECKS));
    return {runtime:'typescript',checks:CHECKS,fault_checks:faultChecks,proof_scope:'native_managed_purge_only',
      semantic_witness_sha256:hash(Buffer.from(JSON.stringify(['cragkit.qdrant.managed-purge.v2',observations,faultChecks]),'utf8'))};
  } finally {
    http.request = nativeRequest;
    let failed = false;
    const deadline = now()+12;
    for (const owner of [...handles,faultVerifier,store,manager,security,transport,recovery,verifier,writer,...pools,vanilla,supervisor]) {
      try {
        if (typeof owner.close === 'function') await bounded(Promise.resolve().then(() => owner.close()),{deadline});
      } catch { failed = true; }
    }
    if (address) { try { await bounded(listener(address,true),{deadline}); } catch { failed = true; } }
    if (failed) throw new Error('cleanup_failed');
  }
}
try {
  const value = await bounded(input(),{deadline:now()+5,signal:controller.signal});
  failureDirectory = value.work_dir;
  reading = false;
  process.stdout.write(JSON.stringify(await cases(value))+'\n');
} catch (error) {
  const locations = [...String(error?.stack ?? '').matchAll(/(?:packages\/typescript\/(?:dist|src)|tools)\/[a-zA-Z0-9_.\/-]+:\d+:\d+/g)]
    .map(match => match[0]);
  if (failureDirectory) {
    try { writeFileSync(join(failureDirectory,'failure-locations.json'),JSON.stringify(locations)+'\n',{mode:0o600}); } catch {}
  }
  const name = ERRORS.has(error?.name) ? error.name : 'internal';
  process.stdout.write(JSON.stringify({ok:false,step,error:name})+'\n');
  process.exitCode = 1;
} finally {
  process.removeListener('SIGTERM',cancel);
  process.removeListener('SIGINT',cancel);
}
