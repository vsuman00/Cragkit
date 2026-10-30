/** Native QD-W10 collision; the isolated child owns the temporary derivation hook. */
import http from 'node:http';
import {execFile} from 'node:child_process';
import {createHash} from 'node:crypto';
import {registerHooks} from 'node:module';
import {isDeepStrictEqual as same} from 'node:util';

const CHECKS = Object.freeze([
  'distinct_coordinators_and_targeted_collision',
  'native_claim_conflict_wait_observed',
  'one_atomic_winner_loser_integrity_violation',
  'loser_successor_rolled_back_baselines_preserved',
  'winner_published_with_exact_native_readback',
  'loser_retry_zero_mutations_preserves_points',
  'collision_hook_restored_and_cleanup_verified',
]);
const ERRORS = new Set(['InvalidRequest','IntegrityViolation','ProviderUnavailable','UnauthorizedScope',
  'UnsupportedCapability','DeadlineExceeded','IndexNotReady','BudgetExhausted','AbortError']);
const SOURCE_SHA256 = '66f3dbb62611575567b74e7b4aeab13a1f9eff7023e2c2ec66c4bf3c373cdc7c';
const SLOT = 'cragkit.native.global-uuid.v1';
const assert = value => { if (!value) throw new Error('acceptance_failed'); };
const hash = value => createHash('sha256').update(value).digest('hex');
const encode = value => Buffer.from(JSON.stringify(value),'utf8');
const decode = value => JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.from(value)));
const now = () => performance.now()/1000;
const cancellation = new AbortController();
let step = 0, reading = true;
const cancel = () => { cancellation.abort(); if (reading) process.stdin.destroy(); };
process.on('SIGTERM',cancel); process.on('SIGINT',cancel);
async function input() {
  const chunks=[]; let size=0;
  for await (const chunk of process.stdin) { size+=chunk.length; assert(size<=1048576); chunks.push(chunk); }
  const value=decode(Buffer.concat(chunks));
  assert(value && same(Object.keys(value).sort(),['binary','inputs','observer_config','supervisor_config','work_dir','writer_config'])
    && typeof value.binary==='string' && typeof value.work_dir==='string');
  return value;
}
async function listener(address,absent=false) {
  const url=new URL(address); assert(url.protocol==='http:' && url.hostname==='127.0.0.1' && url.port && url.origin===address);
  return new Promise((resolve,reject)=>execFile('/usr/sbin/lsof',['-nP','-a','-iTCP@127.0.0.1:'+url.port,'-sTCP:LISTEN','-t'],
    {encoding:'utf8',env:{PATH:'/usr/bin:/bin'},maxBuffer:1024,timeout:3000,killSignal:'SIGKILL'},(error,out,err)=>{
      if (absent && error?.code===1 && out==='' && err==='') return resolve();
      if (error || err || absent || !/^[1-9][0-9]{0,9}\n?$/.test(out)) return reject(new Error('listener_observation'));
      resolve();
    }));
}
async function cases(value) {
  const {inputs}=value;
  const state={enabled:true,hits:0,loads:0,tuple:JSON.stringify(inputs.collision_tuple),uuid:inputs.collision_uuid};
  assert(!Object.hasOwn(globalThis,Symbol.for(SLOT)));
  globalThis[Symbol.for(SLOT)]=state;
  const contractURL=new URL('../packages/typescript/dist/qdrant-contract.js',import.meta.url).href;
  const hook=registerHooks({load(url,context,nextLoad) {
    const loaded=nextLoad(url,context);
    if (url!==contractURL) return loaded;
    const source=typeof loaded.source==='string'?loaded.source:Buffer.from(loaded.source).toString('utf8');
    const marker='export function point_id(tuple) {';
    assert(hash(Buffer.from(source,'utf8'))===SOURCE_SHA256 && source.split(marker).length===2);
    state.loads++;
    const wrapper=`export function point_id(tuple) { const original=native_global_uuid_point_id(tuple); const state=globalThis[Symbol.for(${JSON.stringify(SLOT)})]; if(state?.enabled && JSON.stringify(tuple)===state.tuple) { state.hits++; return state.uuid; } return original; }\nfunction native_global_uuid_point_id(tuple) {`;
    return {...loaded,source:source.replace(marker,wrapper)};
  }});
  let bounded, resources=[],owners=[],address,releaseA=()=>{},raceJobs=[],nativeRequest=http.request;
  let failed=false;
  const checks=[],rows=[];
  const add=row=>{ rows.push(row); checks.push(CHECKS[checks.length]); step=checks.length; };
  try {
    // Dynamic imports are essential: every importer must share the transformed module.
    const poolModule=await import('../packages/typescript/dist/postgres-pool.js');
    bounded=poolModule.bounded;
    const {PoolResource,parse_pool_config}=poolModule;
    const {ExecutionLedger}=await import('../packages/typescript/dist/execution.js');
    const {IntegrityViolation,ProviderUnavailable}=await import('../packages/typescript/dist/errors.js');
    const {point_id}=await import('../packages/typescript/dist/qdrant-contract.js');
    const {encode_manifest}=await import('../packages/typescript/dist/qdrant-manifest.js');
    const {QdrantPublicationManager,PostgresQdrantPublicationAuthority,ManagedQdrantPublicationTransport,
      PostgresQdrantWriter,PostgresQdrantRecovery,ManagedQdrantSupervisor,QdrantReconciliationVerifier}
      =await import('../packages/typescript/dist/qdrant-publication.js');
    assert(state.loads===1);
    const options={deadline:now()+150,signal:cancellation.signal};
    const pool=raw=>{ const result=new PoolResource(parse_pool_config(raw)); assert(result.config.max_size===1); resources.push(result); return result; };
    const pools=[pool(value.writer_config),pool(value.writer_config)];
    let supervisorPool=pool(value.supervisor_config);
    const writers=pools.map(resource=>new PostgresQdrantWriter(resource,inputs.config,inputs.instance_id));
    owners.push(...writers);
    const supervisor=new ManagedQdrantSupervisor(value.binary,value.work_dir,inputs.instance_id,inputs.config);
    owners.push(supervisor);
    const transport=new ManagedQdrantPublicationTransport(supervisor); owners.push(transport);
    const allowed=async(scope,collection,document)=>scope.tenant_id===inputs.scope.tenant_id
      && [inputs.baseline_a,inputs.baseline_b].some(stage=>stage.manifest.collection===collection && stage.manifest.document_id===document);
    function managersFor(resource) {
      return writers.map(writer=>{
        const verifier=new QdrantReconciliationVerifier(writer,supervisor);
        const recovery=new PostgresQdrantRecovery(resource,inputs.config,supervisor,verifier);
        const manager=new QdrantPublicationManager(new PostgresQdrantPublicationAuthority(writer,recovery),transport,inputs.config,supervisor,allowed);
        owners.push(verifier,recovery,manager); return manager;
      });
    }
    let managers=managersFor(supervisorPool);
    const reference=stage=>({collection:stage.manifest.collection,document_id:stage.manifest.document_id,intent_id:stage.intent.intent_id});
    const context=stage=>({...reference(stage),scope:inputs.scope,owner_token:'00000000-0000-4000-8000-000000000001'});
    async function call(work) {
      const ledger=new ExecutionLedger({limits:{deadline_ms:150000,max_attempts:1,max_provider_calls:0},deadline:options.deadline});
      try { return await work(ledger); }
      finally { const usage=ledger.snapshot(); assert(usage.attempts===1 && usage.provider_calls===0 && usage.pending===0); }
    }
    const stage=(index,record)=>call(book=>managers[index].stage(record,inputs.scope,book,options));
    const publish=(index,record)=>call(book=>managers[index].publish(reference(record),inputs.scope,book,options));
    let currentKey,mutations=0;
    http.request=function(requestOptions,callback) {
      if (requestOptions?.headers?.['api-key']) currentKey=requestOptions.headers['api-key'];
      if (['PUT','PATCH','DELETE'].includes(requestOptions?.method)
        || requestOptions?.method==='POST' && /\/points\/(?:delete|payload|clear_payload|vectors)(?:\?|$)/.test(requestOptions.path??'')) mutations++;
      return nativeRequest.call(this,requestOptions,callback);
    };
    const target='/collections/'+inputs.config.physical_collection;
    const complete=raw=>{ const response=decode(raw); assert(response.status==='ok' && response.result.status==='completed'); };
    await supervisor.initialize({...options,provision:async(admin,probe)=>{
      await admin.request('PUT',target,{...options,body:[...encode(inputs.collection_config)]});
      await admin.request('PUT','/collections/'+probe.collection,{...options,body:[...encode(probe.collection_config)]});
      complete(await admin.request('PUT','/collections/'+probe.collection+'/points?wait=true&ordering=strong',
        {...options,body:[...encode({points:[probe.point]})]}));
    }});
    address=supervisor.identity().endpoint; await listener(address);
    for (const resource of [...pools,supervisorPool]) await resource.open();
    for (const manager of managers) await manager.initialize(options);
    const baselines=[inputs.baseline_a,inputs.baseline_b],successors=[inputs.successor_a,structuredClone(inputs.successor_b)];
    successors[1].intent.manifest_sha256=encode_manifest(successors[1].manifest,successors[1].canonical_text).sha256;
    for (let index=0;index<2;index++) {
      assert(baselines[index].manifest.members.length>=1 && successors[index].manifest.members.length>=1);
      await stage(index,baselines[index]); assert((await publish(index,baselines[index])).published===true);
    }
    const before=await Promise.all(writers.map((writer,index)=>writer.manager_snapshot(context(baselines[index]),options)));
    assert(before.every((snapshot,index)=>snapshot.owner?.intent_id===baselines[index].intent.intent_id
      && snapshot.owner.backend_epoch===1 && snapshot.document.active_generation_id===baselines[index].manifest.generation_id && !snapshot.pending)
      && before[0].owner.owner_token!==before[1].owner.owner_token
      && baselines[0].manifest.document_id!==baselines[1].manifest.document_id);
    assert(inputs.collision_tuple.length===12 && point_id(inputs.collision_tuple)===inputs.collision_uuid
      && successors.every(record=>record.manifest.members[0].point_id===inputs.collision_uuid));
    state.enabled=false; const naturalLoser=point_id(inputs.collision_tuple); state.enabled=true;
    assert(naturalLoser!==inputs.collision_uuid);
    async function physical(ids) {
      const endpoint=new URL(address),body=encode({ids,with_payload:true,with_vector:true});
      const response=await bounded(new Promise((resolve,reject)=>{
        const request=nativeRequest.call(http,{hostname:'127.0.0.1',port:Number(endpoint.port),method:'POST',path:target+'/points',agent:false,
          signal:options.signal,headers:{'api-key':currentKey,'content-type':'application/json','content-length':body.length}},incoming=>{
          const chunks=[];let size=0;
          incoming.on('data',chunk=>{size+=chunk.length;if(size>1048576) request.destroy(new ProviderUnavailable());else chunks.push(Buffer.from(chunk));});
          incoming.on('error',reject);incoming.once('end',()=>resolve({status:incoming.statusCode,body:Buffer.concat(chunks)}));
        });
        request.on('error',reject);request.setTimeout(5000,()=>request.destroy(new ProviderUnavailable()));request.end(body);
      }),options);
      assert(response.status===200);const found=decode(response.body);assert(found.status==='ok' && Array.isArray(found.result));
      assert(found.result.length===ids.length && same(found.result.map(point=>point.id).sort(),[...ids].sort()));
      return found.result.map(({id,payload,vector})=>({id,payload,vector})).sort((a,b)=>a.id<b.id?-1:a.id>b.id?1:0);
    }
    const baselineIDs=baselines.flatMap(record=>record.manifest.members.map(member=>member.point_id));
    const baselinePoints=await physical(baselineIDs); assert(baselinePoints.every(point=>point.payload && point.vector));
    add(['coordinators',2,2,1]);
    // Three live SQL sessions maximum during contention: two writers and observer.
    await supervisorPool.close();
    let observer=pool(value.observer_config); await observer.open();
    const query=(text,values=[])=>observer.withLease(options,async client=>(await bounded(client.query({text,values,rowMode:'array'}),options)).rows);
    let inserted; const insertedA=new Promise(resolve=>{inserted=resolve;});
    let released=false; const releasedA=new Promise(resolve=>{releaseA=()=>{released=true;resolve();};});
    const pids=[null,null],arrivals=[0,0];
    for (let index=0;index<2;index++) {
      const realLease=pools[index].withLease.bind(pools[index]);
      pools[index].withLease=(lease,operation)=>realLease(lease,(client,signal)=>operation({
        async query(request) {
          const relevant=request.text.startsWith('INSERT INTO cragkit_qdrant.point_claims ')
            && request.values?.includes(inputs.collision_uuid) && request.values.includes(successors[index].manifest.document_id);
          if (relevant) {
            arrivals[index]++; assert(arrivals[index]===1);
            const rows=(await client.query({text:'SELECT pg_backend_pid()',rowMode:'array'})).rows;
            assert(rows.length===1 && Number.isInteger(rows[0][0]));pids[index]=rows[0][0];
          }
          const result=await client.query(request);
          if (relevant && index===0) { inserted(); await bounded(releasedA,options); }
          return result;
        },
        getTransactionStatus:()=>client.getTransactionStatus(),release:destroy=>client.release(destroy),
      },signal));
    }
    const noMutation=mutations;
    const attempt=index=>stage(index,successors[index]).then(result=>({result}),error=>({error}));
    raceJobs.push(attempt(0));
    await bounded(Promise.race([insertedA,raceJobs[0].then(()=>{throw new Error('claim_barrier_missing');})]),options);
    raceJobs.push(attempt(1));
    let waited=false;
    const waitDeadline=Math.min(options.deadline,now()+5);
    while (now()<waitDeadline) {
      if (pids[1]!==null) {
        const observed=await query("SELECT EXISTS(SELECT 1 FROM pg_stat_activity a JOIN pg_locks l ON l.pid=a.pid WHERE a.pid=$1 AND a.state='active' AND a.wait_event_type='Lock' AND a.wait_event='transactionid' AND l.locktype='transactionid' AND NOT l.granted AND $2=ANY(pg_blocking_pids(a.pid)))",[pids[1],pids[0]]);
        if (same(observed,[[true]])) { waited=true;break; }
      }
      await bounded(new Promise(resolve=>setTimeout(resolve,10)),options);
    }
    assert(waited && !released && same(arrivals,[1,1]) && pids[0]!==pids[1]);
    add(['claim_wait',true]); releaseA();
    const outcomes=await bounded(Promise.all(raceJobs),options);raceJobs=[];
    assert(outcomes[0].result?.operation==='stage' && outcomes[0].result.state==='staged'
      && outcomes[1].error instanceof IntegrityViolation && mutations===noMutation);
    add(['claim_result',1,'IntegrityViolation',0]);
    const readClaim=()=>query('SELECT instance_id,tenant_id,collection,document_id,revision_id,generation_id,chunk_id,source_sha256,text_sha256,start_byte::text,end_byte::text,dense_profile,sparse_profile,dense_input_sha256,sparse_input_sha256 FROM cragkit_qdrant.point_claims WHERE backend_namespace=$1 AND physical_collection=$2 AND collection_incarnation=$3 AND point_id=$4::uuid',
      [inputs.config.backend_namespace,inputs.config.physical_collection,inputs.config.collection_incarnation,inputs.collision_uuid]);
    const claim=await readClaim();
    const winning=successors[0].manifest,member=winning.members.find(value=>value.point_id===inputs.collision_uuid);
    assert(member && same(claim,[[inputs.instance_id,winning.tenant_id,winning.collection,winning.document_id,winning.revision_id,
      winning.generation_id,member.chunk_id,winning.source_sha256,member.text_sha256,String(member.start_byte),String(member.end_byte),
      winning.dense_profile,winning.sparse_profile,member.dense_input_sha256,member.sparse_input_sha256]]));
    async function assertLoserRolledBack() {
      for (const table of ['publication_intents','document_revisions','generations','members','point_claims','vector_replays','dispatch_journal']) {
        const field=table==='publication_intents'||table==='dispatch_journal'?'intent_id':table==='document_revisions'?'revision_id':'generation_id';
        const selected=field==='intent_id'?successors[1].intent.intent_id:successors[1].manifest[field];
        assert(same(await query(`SELECT count(*)::text FROM cragkit_qdrant.${table} WHERE tenant_id=$1 AND collection=$2 AND document_id=$3 AND ${field}=$4`,
          [inputs.scope.tenant_id,successors[1].manifest.collection,successors[1].manifest.document_id,selected]),[['0']]));
      }
    }
    await assertLoserRolledBack();
    const after=await Promise.all(writers.map((writer,index)=>writer.manager_snapshot(context(baselines[index]),options)));
    assert(same(after,before) && same(await physical(baselineIDs),baselinePoints));
    add(['rollback',0,true,true]);
    await observer.close();
    // The closed supervisor resource is replaced only after the observer is closed.
    supervisorPool=pool(value.supervisor_config);await supervisorPool.open();
    managers=managersFor(supervisorPool);for (const manager of managers) await manager.initialize(options);
    assert((await publish(0,successors[0])).published===true);
    const winnerIDs=winning.members.map(member=>member.point_id),winnerPoint=await physical(winnerIDs);
    assert(winnerPoint.every(point=>point.payload.document_id===winning.document_id && point.payload.generation_id===winning.generation_id
      && point.vector) && same(await physical(baselineIDs),baselinePoints));
    add(['publication',true,1]);
    // End the race instrumentation before retry; the retry must reach native SQL again.
    arrivals[1]=0;
    const mutationsBeforeRetry=mutations;
    const retry=await stage(1,successors[1]).then(result=>({result}),error=>({error}));
    assert(retry.error instanceof IntegrityViolation && arrivals[1]===1 && mutations===mutationsBeforeRetry
      && same(await physical(winnerIDs),winnerPoint) && same(await physical(baselineIDs),baselinePoints));
    // Reconnect independently after the retry; do not infer rollback from its error.
    await supervisorPool.close();
    observer=pool(value.observer_config);await observer.open();
    await assertLoserRolledBack();assert(same(await readClaim(),claim));
    await observer.close();
    add(['retry','IntegrityViolation',0,true,true]);
    assert(state.hits>=3);
    state.enabled=false; assert(point_id(inputs.collision_tuple)===naturalLoser);
  } catch (error) { failed=true;throw error; }
  finally {
    state.enabled=false;releaseA();http.request=nativeRequest;
    const failures=[];const deadline=now()+20;
    if (raceJobs.length) {
      cancellation.abort();
      try { await bounded(Promise.allSettled(raceJobs),{deadline:Math.min(deadline,now()+5)}); } catch { failures.push(true); }
    }
    for (const owner of [...owners].reverse().concat([...resources].reverse())) {
      try { if (bounded) await bounded(Promise.resolve().then(()=>owner.close()),{deadline:Math.min(deadline,now()+5)}); }
      catch { failures.push(true); }
    }
    if (address) try { await listener(address,true); } catch { failures.push(true); }
    hook.deregister();delete globalThis[Symbol.for(SLOT)];
    if (failures.length) throw new Error('cleanup_failed');
    if (!failed) add(['cleanup',true]);
  }
  assert(same(checks,CHECKS));
  return {runtime:'typescript',checks,proof_scope:'native_global_uuid_collision_only',
    semantic_witness_sha256:hash(encode(['cragkit.qdrant.global-uuid.v1',rows]))};
}
try {
  const timeout=setTimeout(cancel,5000);let value;
  try { value=await input(); } finally { clearTimeout(timeout); }
  reading=false;process.stdout.write(JSON.stringify(await cases(value))+'\n');
} catch (error) {
  process.stdin.destroy();process.stdout.write(JSON.stringify({ok:false,step,error:ERRORS.has(error?.name)?error.name:error?.message==='cleanup_failed'?'cleanup_failed':'internal'})+'\n');process.exitCode=1;
} finally {
  process.removeListener('SIGTERM',cancel);process.removeListener('SIGINT',cancel);
}
