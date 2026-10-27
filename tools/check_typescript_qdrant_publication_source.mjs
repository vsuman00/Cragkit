/** Native public publication and authoritative source acceptance; F3-r1. */
import {execFile} from 'node:child_process';
import {createHash} from 'node:crypto';
import {isDeepStrictEqual} from 'node:util';
import {PoolResource,parse_pool_config,bounded,now} from '../packages/typescript/dist/postgres-pool.js';
import {ExecutionLedger} from '../packages/typescript/dist/execution.js';
import {QdrantPublicationManager,PostgresQdrantPublicationAuthority,ManagedQdrantPublicationTransport,
  PostgresQdrantWriter,PostgresQdrantRecovery,ManagedQdrantSupervisor,QdrantReconciliationVerifier} from '../packages/typescript/dist/qdrant-publication.js';
import {FetchQdrantTransport,QdrantSearchStore} from '../packages/typescript/dist/qdrant.js';
import {PostgresQdrantSourceStore} from '../packages/typescript/dist/qdrant-source.js';
import {UnauthorizedScope} from '../packages/typescript/dist/errors.js';

const OWNER='00000000-0000-4000-8000-000000000001';
const CHECKS=[
  'stage_has_no_search_candidates_or_active_generation',
  'prepared_replica_has_candidates_but_no_source_release',
  'published_generation_releases_exact_utf8_sources',
  'prepared_successor_preserves_previous_active_sources',
  'published_successor_replaces_fresh_source_admission',
  'retained_previous_binding_releases_exact_stale_evidence',
  'foreign_scope_cannot_search_or_release_source',
  'no_sql_lease_across_callback_or_http_and_borrowed_cleanup',
];
const ERRORS=new Set(['IntegrityViolation','UnauthorizedScope','UnsupportedCapability','InvalidRequest',
  'ProviderUnavailable','DeadlineExceeded','IndexNotReady','BudgetExhausted','CancelledError','AbortError']);
const cancellation=new AbortController();
let readingInput=true,step=0;
const cancel=()=>{cancellation.abort();if(readingInput)process.stdin.destroy();};
process.on('SIGTERM',cancel);process.on('SIGINT',cancel);
const bytes=value=>[...Buffer.from(JSON.stringify(value),'utf8')];
const digest=value=>createHash('sha256').update(value).digest('hex');
function outcome(error){let name;try{name=error?.name;}catch{return 'internal';}return ERRORS.has(name)?name:'internal';}
class RuntimeCleanupFailure extends Error{
  constructor(primary,failures){super('runtime_cleanup_failed');this.primary=primary?outcome(primary):null;this.failures=failures;}
}
function assert(value){if(!value)throw new Error('acceptance_failed');}
async function input(){
  let size=0;const chunks=[];
  for await(const chunk of process.stdin){size+=chunk.length;if(size>1048576)throw new Error('bounded_input');chunks.push(chunk);}
  const value=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks)));
  assert(value&&typeof value==='object'&&!Array.isArray(value)
    &&isDeepStrictEqual(Object.keys(value).sort(),['binary','inputs','reader_config','supervisor_config','work_dir','writer_config'])
    &&typeof value.binary==='string'&&typeof value.work_dir==='string'&&value.inputs?.successor&&value.inputs?.request);
  return value;
}
async function listener(address,absent=false){
  const parsed=new URL(address);assert(parsed.protocol==='http:'&&parsed.hostname==='127.0.0.1'&&parsed.port&&parsed.origin===address);
  return new Promise((resolve,reject)=>execFile('/usr/sbin/lsof',['-nP','-a','-iTCP@127.0.0.1:'+parsed.port,'-sTCP:LISTEN','-t'],
    {encoding:'utf8',env:{PATH:'/usr/bin:/bin'},maxBuffer:1024,timeout:3000,killSignal:'SIGKILL'},(error,stdout,stderr)=>{
      if(absent&&error?.code===1&&stdout===''&&stderr==='')return resolve();
      if(error||stderr||absent||!/^[1-9][0-9]{0,9}\n?$/.test(stdout))return reject(new Error('listener_observation'));
      resolve();
    }));
}
async function cases(value){
  const inputs=value.inputs,configs=[value.writer_config,value.supervisor_config,value.reader_config].map(parse_pool_config);
  assert(configs.every(config=>config.max_size===1));
  const options={deadline:now()+105,signal:cancellation.signal};
  const resource=new PoolResource(configs[0]),supervisorResource=new PoolResource(configs[1]),readerResource=new PoolResource(configs[2]);
  const writer=new PostgresQdrantWriter(resource,inputs.config,inputs.instance_id);
  const supervisor=new ManagedQdrantSupervisor(value.binary,value.work_dir,inputs.instance_id,inputs.config);
  const verifier=new QdrantReconciliationVerifier(writer,supervisor);
  const recovery=new PostgresQdrantRecovery(supervisorResource,inputs.config,supervisor,verifier);
  const authority=new PostgresQdrantPublicationAuthority(writer,recovery),transport=new ManagedQdrantPublicationTransport(supervisor);
  const checks=[],observations=[],stores=new Set(),requests=new Set(),handles=new Set();
  let writerLeases=0,httpObservations=0,callbackObservations=0,paused=null,publishTask=null,publishController=null;
  let manager,candidateTransport,candidates,address,primary,retained,retainedNomination,retainedFetch;
  const realLease=resource.withLease.bind(resource);
  resource.withLease=(opts,operation)=>realLease(opts,async(client,signal)=>{writerLeases++;try{return await operation(client,signal);}finally{writerLeases--;}});
  const noLease=()=>assert(writerLeases===0);
  const context=stage=>({scope:inputs.scope,collection:stage.manifest.collection,document_id:stage.manifest.document_id,intent_id:stage.intent.intent_id,owner_token:OWNER});
  const reference=stage=>({collection:stage.manifest.collection,document_id:stage.manifest.document_id,intent_id:stage.intent.intent_id});
  const book=()=>new ExecutionLedger({limits:{deadline_ms:60000,max_attempts:1,max_provider_calls:0},deadline:options.deadline});
  const add=index=>{checks.push(CHECKS[index]);step=checks.length;};
  async function active(generation){assert((await writer.manager_snapshot(context(inputs.stage),options)).document?.active_generation_id===generation);}
  async function authorize(scope,collection,document_id){
    noLease();
    assert(isDeepStrictEqual(scope,inputs.scope)&&collection===inputs.stage.manifest.collection&&document_id===inputs.stage.manifest.document_id);
    if(!paused||paused.fired)return true;
    if((await writer.inspect(context(paused.stage),options))?.state!=='prepared')return true;
    noLease();callbackObservations++;paused.fired=true;paused.arrived();
    await bounded(paused.gate,options);noLease();return true;
  }
  async function newRequest(scope=inputs.scope){
    const store=new PostgresQdrantSourceStore(readerResource,inputs.config);stores.add(store);
    await store.initialize(options);
    const handle=store.open_request(inputs.request,{scope,deadline:Math.min(options.deadline,now()+60),signal:cancellation.signal});requests.add(handle);
    return {store,handle};
  }
  async function closeRequest(pair){await pair.handle.close();requests.delete(pair.handle);await pair.store.close();stores.delete(pair.store);}
  function row(phase,nomination,result,stale=false){
    const point=nomination.point_id??nomination.id;
    if(result.state!=='verified'){
      assert(result.state==='unavailable'&&result.evidence===null&&result.binding===null&&result.private_source===null&&result.source_bytes===0&&!result.stale);
      return [phase,point,result.state,...Array(13).fill(null)];
    }
    const payload=nomination.payload,e=result.evidence;
    const stage=payload.generation_id===inputs.stage.manifest.generation_id?inputs.stage:inputs.successor;
    const member=stage.manifest.members.find(item=>item.point_id===point);
    assert(member&&['document_id','revision_id','generation_id','source_sha256'].every(key=>payload[key]===stage.manifest[key])
      &&['chunk_id','start_byte','end_byte','text_sha256'].every(key=>payload[key]===member[key]));
    const canonical=Buffer.from(stage.canonical_text,'utf8'),excerpt=canonical.subarray(member.start_byte,member.end_byte);
    const text=new TextDecoder('utf-8',{fatal:true}).decode(excerpt);
    const evidenceId=digest(Buffer.from(JSON.stringify(['cragkit.evidence.v1',payload.tenant_id,payload.collection,payload.document_id,payload.revision_id,payload.chunk_id,String(payload.start_byte),String(payload.end_byte),payload.text_sha256]),'utf8'));
    assert(e&&result.binding&&result.stale===stale&&result.source_bytes===canonical.length
      &&result.private_source?.canonical_text===stage.canonical_text&&result.private_source.source_sha256===digest(canonical)
      &&e.evidence_id===evidenceId&&e.text===text&&e.source_sha256===digest(canonical)&&e.text_sha256===digest(excerpt)
      &&e.collection===payload.collection&&e.source_locator===stage.manifest.source_locator
      &&['document_id','revision_id','chunk_id','start_byte','end_byte'].every(key=>e[key]===payload[key]));
    const publicResult=result.toJSON();assert(!Object.hasOwn(publicResult,'binding')&&!Object.hasOwn(publicResult,'private_source'));
    return [phase,point,result.state,e.evidence_id,e.document_id,e.revision_id,payload.generation_id,e.chunk_id,
      e.source_sha256,e.text_sha256,String(e.start_byte),String(e.end_byte),e.text,result.private_source.canonical_text,String(result.source_bytes),result.stale];
  }
  async function search(scope=inputs.scope){
    const ledger=new ExecutionLedger({limits:inputs.request.limits,deadline:options.deadline});
    const nominations=await candidates.search_candidates(inputs.request,{scope,dense:inputs.stage.dense_vectors[0],branch_limits:{dense:8},ledger,...options});
    const state=ledger.snapshot();assert(state.candidates===8&&state.provider_calls===0&&state.pending===0);
    return [...nominations].sort((a,b)=>(a.point_id??a.id).localeCompare(b.point_id??b.id));
  }
  async function phase(name,count,generation,keep=false){
    const nominations=await search();assert(nominations.length===count);observations.push(['phase',name,String(count)]);
    const pair=await newRequest();let verified=0;
    try{
      for(const nomination of nominations){
        const result=await pair.handle.fetch_candidate(nomination,{max_source_bytes:16777216,include_source:true});
        const shouldVerify=nomination.payload.generation_id===generation;
        assert((result.state==='verified')===shouldVerify);if(shouldVerify)verified++;
        observations.push(row(name,nomination,result));
      }
    }finally{await closeRequest(pair);}
    assert(verified===(generation===null?0:2));
    if(keep){retained=await newRequest();retainedNomination=nominations[0];retainedFetch=await retained.handle.fetch_candidate(retainedNomination,{max_source_bytes:16777216,include_source:true});row(name,retainedNomination,retainedFetch);}
    return nominations;
  }
  async function prepare(stage,name,count,generation){
    let arrived,release;const reached=new Promise(resolve=>{arrived=resolve;});const gate=new Promise(resolve=>{release=resolve;});
    paused={stage,arrived,gate,release,fired:false};publishController=new AbortController();
    publishTask=manager.publish(reference(stage),inputs.scope,book(),{...options,signal:AbortSignal.any([cancellation.signal,publishController.signal])});
    // Attach immediately so failure before the rendezvous never becomes unhandled.
    publishTask.catch(()=>{});
    await bounded(Promise.race([reached,publishTask.then(()=>{throw new Error('prepared_pause_missing');})]),options);
    const snapshot=await writer.manager_snapshot(context(stage),options);
    assert(snapshot.intent?.state==='prepared'&&snapshot.document?.active_generation_id===generation);
    await phase(name,count,generation);
    release();const result=await publishTask;publishTask=null;publishController=null;assert(result.published);paused=null;
  }
  try{
    const provision=async(admin,probe)=>{
      await admin.request('PUT','/collections/'+inputs.config.physical_collection,{...options,body:bytes(inputs.collection_config)});
      await admin.request('PUT','/collections/'+probe.collection,{...options,body:bytes(probe.collection_config)});
      const raw=await admin.request('PUT','/collections/'+probe.collection+'/points?wait=true&ordering=strong',{...options,body:bytes({points:[probe.point]})});
      const result=JSON.parse(Buffer.from(raw).toString('utf8'));assert(result.status==='ok'&&result.result?.status==='completed');
    };
    await supervisor.initialize({...options,provision});address=supervisor.identity().endpoint;await listener(address);
    const actualTransport=supervisor.transport_for.bind(supervisor);
    supervisor.transport_for=capability=>{
      const actual=actualTransport(capability);
      const observed={async request(method,path,opts){noLease();httpObservations++;const result=await actual.request(method,path,opts);noLease();return result;},
        async close(){await actual.close();handles.delete(observed);}};handles.add(observed);return observed;
    };
    await resource.open();await supervisorResource.open();
    manager=new QdrantPublicationManager(authority,transport,inputs.config,supervisor,authorize);await manager.initialize(options);
    await supervisorResource.close();await readerResource.open();
    let credential;
    const attempt=supervisor.issue_attempt({intent_id:'source-reader',owner_token:OWNER,epoch:1,dispatch_id:'source-reader'},options);
    await supervisor.deliver_worker_credential(attempt,value=>{assert(!credential);credential=value;},options);
    candidateTransport=new FetchQdrantTransport(credential.endpoint,{api_key:credential.api_key,allow_loopback_http:true,
      fetch:async(...args)=>{noLease();httpObservations++;const response=await globalThis.fetch(...args);noLease();return response;}});
    credential=undefined;
    candidates=new QdrantSearchStore(inputs.config,candidateTransport);await candidates.initialize(options);
    const staged=await manager.stage(inputs.stage,inputs.scope,book(),options);assert(staged.state==='staged'&&!staged.published);
    await active(null);await phase('staged',0,null);add(0);
    await prepare(inputs.stage,'g1_prepared',2,null);add(1);
    await active(inputs.stage.manifest.generation_id);await phase('g1_published',2,inputs.stage.manifest.generation_id,true);add(2);
    await manager.stage(inputs.successor,inputs.scope,book(),options);
    await prepare(inputs.successor,'g2_prepared',4,inputs.stage.manifest.generation_id);add(3);
    await active(inputs.successor.manifest.generation_id);
    const current=await phase('g2_published',4,inputs.successor.manifest.generation_id);add(4);
    for(const purpose of ['provider','final']){
      const name='retained_'+purpose,result=await retained.handle.release(retainedFetch.binding,{purpose,max_source_bytes:16777216,include_source:true});
      observations.push(['phase',name,'1'],row(name,retainedNomination,result,true));
      assert(isDeepStrictEqual(result.evidence,retainedFetch.evidence));
    }
    add(5);
    const foreign={...inputs.scope,tenant_id:'foreign'};assert((await search(foreign)).length===0);observations.push(['phase','foreign_search','0']);
    const pair=await newRequest(foreign);
    try{
      let denied=false;try{await pair.handle.fetch_candidate(current.find(item=>item.payload.generation_id===inputs.successor.manifest.generation_id),{max_source_bytes:16777216,include_source:true});}
      catch(error){if(!(error instanceof UnauthorizedScope))throw error;denied=true;}
      assert(denied);observations.push(['foreign_source','UnauthorizedScope']);
    }finally{await closeRequest(pair);}
    add(6);
    await manager.close();manager=null;noLease();await writer.initialize(options);await active(inputs.successor.manifest.generation_id);
    assert(supervisor.profile_binding(inputs.config).alive&&handles.size===0&&httpObservations>0&&callbackObservations===2);add(7);
    return {runtime:'typescript',checks,proof_scope:'public_source_publication_only',source_observations_sha256:digest(Buffer.from(JSON.stringify(observations),'utf8'))};
  }catch(error){primary=error;throw error;}
  finally{
    const failures=[],deadline=now()+12;
    async function cleanup(operation,action){try{await bounded(Promise.resolve().then(action),{deadline:Math.max(now()+.001,Math.min(now()+8,deadline))});}catch(error){if(failures.length<64)failures.push({operation,outcome:outcome(error)});}}
    if(publishTask){publishController?.abort();paused?.release();await cleanup('publish_drain',()=>publishTask.catch(()=>{}));}
    for(const request of requests)await cleanup('request_close',()=>request.close());
    for(const store of stores)await cleanup('source_close',()=>store.close());
    if(candidates)await cleanup('candidate_close',()=>candidates.close());
    if(candidateTransport)await cleanup('transport_close',()=>candidateTransport.close());
    if(manager)await cleanup('manager_close',()=>manager.close());
    await cleanup('transport_close',()=>transport.close());
    for(const handle of handles)await cleanup('transport_close',()=>handle.close());
    for(const [operation,owner] of [['recovery_close',recovery],['verifier_close',verifier],['writer_close',writer],
      ['reader_pool_close',readerResource],['resource_close',resource],['supervisor_resource_close',supervisorResource],['controller_close',supervisor]])await cleanup(operation,()=>owner.close());
    if(address)await cleanup('listener_close',()=>listener(address,true));
    if(failures.length)throw new RuntimeCleanupFailure(primary,failures);
  }
}
try{
  const value=await bounded(input(),{deadline:now()+5,signal:cancellation.signal});readingInput=false;
  process.stdout.write(JSON.stringify(await cases(value))+'\n');
}catch(error){
  process.stdout.write(JSON.stringify(error instanceof RuntimeCleanupFailure
    ?{ok:false,step,error:'cleanup_failed',primary:error.primary,cleanup:error.failures}
    :{ok:false,step,error:outcome(error)})+'\n');process.exitCode=1;
}finally{process.removeListener('SIGTERM',cancel);process.removeListener('SIGINT',cancel);}
