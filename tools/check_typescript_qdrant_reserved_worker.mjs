/** Reserved-boundary owned-child acceptance. No recovery settlement is performed. */
import {execFile} from 'node:child_process';
import {createHash} from 'node:crypto';
import {isDeepStrictEqual} from 'node:util';
import {PoolResource,parse_pool_config,bounded,now} from '../packages/typescript/dist/postgres-pool.js';
import {ExecutionLedger} from '../packages/typescript/dist/execution.js';
import {ManagedQdrantPublicationWorkerHost} from '../packages/typescript/dist/qdrant-publication-worker.js';
import {QdrantPublicationManager,PostgresQdrantPublicationAuthority,ManagedQdrantPublicationTransport,
  PostgresQdrantWriter,PostgresQdrantRecovery,ManagedQdrantSupervisor,QdrantReconciliationVerifier} from '../packages/typescript/dist/qdrant-publication.js';

const CHECKS=[
  'actual_child_base_publish_preserves_parent_supervisor',
  'durable_reserved_then_owned_worker_sigkill_preserves_previous_generation',
  'fresh_sql_reserved_or_unknown_successor_unpublished',
  'physical_successor_points_absent',
  'elapsed_fresh_child_retry_preserves_single_reserved_dispatch',
  'host_close_preserves_supervisor_and_reaps_owned_children',
];
const RESULT_KEYS=['intent_id','operation','state','revision_id','generation_id',
  'authority_committed','replica_complete','published','purge_complete'];
const ERRORS=new Set(['IntegrityViolation','UnauthorizedScope','UnsupportedCapability','InvalidRequest',
  'ProviderUnavailable','DeadlineExceeded','IndexNotReady','BudgetExhausted','CancelledError','AbortError']);
const cancellation=new AbortController();let readingInput=true,step=0;
const cancel=()=>{cancellation.abort();if(readingInput)process.stdin.destroy();};
process.on('SIGTERM',cancel);process.on('SIGINT',cancel);
const assert=value=>{if(!value)throw new Error('acceptance_failed');};
const bytes=value=>[...Buffer.from(JSON.stringify(value),'utf8')];
function outcome(error){let name;try{name=error?.name;}catch{return 'internal';}return ERRORS.has(name)?name:'internal';}
class CleanupFailure extends Error{constructor(primary,failures){super('cleanup_failed');this.primary=primary?outcome(primary):null;this.failures=failures;}}
async function input(){
  const chunks=[];let size=0;
  for await(const chunk of process.stdin){size+=chunk.length;assert(size<=1048576);chunks.push(chunk);}
  const value=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks)));
  assert(value&&isDeepStrictEqual(Object.keys(value).sort(),['binary','inputs','supervisor_config','work_dir','writer_config'])
    &&typeof value.binary==='string'&&typeof value.work_dir==='string'&&value.inputs?.successor&&value.inputs?.second_stage);
  return value;
}
async function listener(address,absent=false){
  const parsed=new URL(address);assert(parsed.protocol==='http:'&&parsed.hostname==='127.0.0.1'&&parsed.port&&parsed.origin===address);
  return new Promise((resolve,reject)=>execFile('/usr/sbin/lsof',['-nP','-a','-iTCP@127.0.0.1:'+parsed.port,'-sTCP:LISTEN','-t'],
    {encoding:'utf8',env:{PATH:'/usr/bin:/bin'},maxBuffer:1024,timeout:3000,killSignal:'SIGKILL'},(error,stdout,stderr)=>{
      if(absent&&error?.code===1&&stdout===''&&stderr==='')return resolve(null);
      if(error||stderr||absent||!/^[1-9][0-9]{0,9}\n?$/.test(stdout))return reject(new Error('listener_observation'));
      resolve(Number(stdout.trim()));
    }));
}
async function cases(value){
  const inputs=value.inputs,writerConfig=parse_pool_config(value.writer_config),supervisorConfig=parse_pool_config(value.supervisor_config);
  assert(writerConfig.max_size===1&&supervisorConfig.max_size===1);
  const options={deadline:now()+145,signal:cancellation.signal};
  const supervisorResource=new PoolResource(supervisorConfig);
  const supervisor=new ManagedQdrantSupervisor(value.binary,value.work_dir,inputs.instance_id,inputs.config);
  const bundles=new Set(),checks=[],results=[];
  let address,initialPid,originalIdentity,host,primary;
  const reference=stage=>({collection:stage.manifest.collection,document_id:stage.manifest.document_id,intent_id:stage.intent.intent_id});
  const context=(stage,scope)=>({...reference(stage),scope,owner_token:'00000000-0000-4000-8000-000000000001'});
  const limits={deadline_ms:60000,max_attempts:1,max_provider_calls:0};
  const book=(max_attempts=1)=>new ExecutionLedger({limits:{...limits,max_attempts},deadline:options.deadline});
  const job=(stage,scope=inputs.scope)=>({writer_pool:value.writer_config,config:inputs.config,scope,reference:reference(stage),limits});
  const short=()=>({deadline:Math.min(options.deadline,now()+5)});
  const add=index=>{checks.push(CHECKS[index]);step=checks.length;};
  function accounting(ledger,attempts){const state=ledger.snapshot();assert(state.attempts===attempts&&state.provider_calls===0&&state.candidates===0&&state.pending===0);}
  function save(result){
    assert(result&&isDeepStrictEqual(Object.keys(result).sort(),[...RESULT_KEYS].sort())&&result.operation==='publish'
      &&result.state==='published'&&result.published&&result.authority_committed&&result.replica_complete
      &&RESULT_KEYS.slice(5).every(key=>typeof result[key]==='boolean')
      &&RESULT_KEYS.slice(0,5).every(key=>typeof result[key]==='string'||result[key]===null));
    results.push(RESULT_KEYS.map(key=>result[key]));return result;
  }
  async function transaction(operation){
    return supervisorResource.withLease(options,async(client,signal)=>{
      const lease={deadline:options.deadline,signal};let begun=false;
      const query=async(text,values=[])=> (await bounded(client.query({text,values,rowMode:'array'}),lease)).rows;
      try{
        await query('BEGIN ISOLATION LEVEL READ COMMITTED');begun=true;await query('SET LOCAL search_path=pg_catalog');
        await query("SELECT set_config('cragkit_qdrant.backend_instance_id',$1,true)",[inputs.instance_id]);
        const result=await operation(query);await query('COMMIT');begun=false;return result;
      }finally{if(begun){try{await bounded(client.query({text:'ROLLBACK',rowMode:'array'}),{deadline:now()+2});}catch{client.release(true);}}}
    });
  }
  async function bundle(initializeManager=true){
    const resource=new PoolResource(writerConfig),writer=new PostgresQdrantWriter(resource,inputs.config,inputs.instance_id);
    const verifier=new QdrantReconciliationVerifier(writer,supervisor);
    const recovery=new PostgresQdrantRecovery(supervisorResource,inputs.config,supervisor,verifier);
    const transport=new ManagedQdrantPublicationTransport(supervisor);
    const authority=new PostgresQdrantPublicationAuthority(writer,recovery);
    const manager=new QdrantPublicationManager(authority,transport,inputs.config,supervisor,async()=>true);
    const entry={resource,writer,verifier,recovery,transport,manager};bundles.add(entry);
    await resource.open();if(initializeManager)await manager.initialize(options);else await writer.initialize(options);return entry;
  }
  async function closeBundle(entry){
    for(const owner of [entry.manager,entry.transport,entry.recovery,entry.verifier,entry.writer,entry.resource])await owner.close();
    bundles.delete(entry);
  }
  async function snapshot(stage,scope=inputs.scope){const entry=await bundle(false);try{return await entry.writer.manager_snapshot(context(stage,scope),options);}finally{await closeBundle(entry);}}
  async function stage(stage,scope=inputs.scope){const entry=await bundle();try{await entry.manager.stage(stage,scope,book(),options);}finally{await closeBundle(entry);}}
  async function publish(stage,scope,observer,ledger=book()){
    try{return await host.publish(job(stage,scope),ledger,{...options,observer});}finally{accounting(ledger,1);}
  }
  async function operational(work){
    try{await work;}catch(error){assert(['ProviderUnavailable','UnauthorizedScope'].includes(outcome(error)));return;}
    throw new Error('expected_operational_failure');
  }
  async function unchangedSupervisor(){assert(await listener(address)===initialPid&&isDeepStrictEqual(supervisor.control_binding(),originalIdentity));}
  try{
    await supervisor.initialize({...options,provision:async(admin,probe)=>{
      await admin.request('PUT','/collections/'+inputs.config.physical_collection,{...options,body:bytes(inputs.collection_config)});
      await admin.request('PUT','/collections/'+probe.collection,{...options,body:bytes(probe.collection_config)});
      await admin.request('PUT','/collections/'+probe.collection+'/points?wait=true&ordering=strong',{...options,body:bytes({points:[probe.point]})});
    }});
    address=supervisor.identity().endpoint;initialPid=await listener(address);originalIdentity=supervisor.control_binding();await supervisorResource.open();
    await stage(inputs.stage);
    host=new ManagedQdrantPublicationWorkerHost(supervisor,async(scope,collection,document)=>{
      const expected=document===inputs.stage.manifest.document_id?inputs.scope:inputs.second_scope;
      assert(isDeepStrictEqual(scope,expected)&&collection===inputs.stage.manifest.collection
        &&[inputs.stage.manifest.document_id,inputs.second_stage.manifest.document_id].includes(document));return true;
    });
    const events=[];
    save(await publish(inputs.stage,inputs.scope,async event=>{events.push(event);}));
    assert(events.filter(event=>event.kind==='reserved').length===1
      &&events.filter(event=>event.kind==='before_write').length===1
      &&events.filter(event=>event.kind==='write_observed'&&event.status===200).length===1);
    await unchangedSupervisor();add(0);
    await stage(inputs.successor);
    const reservedEvents=[];let killed=false;
    await operational(publish(inputs.successor,inputs.scope,async(event,owned)=>{
      reservedEvents.push(event);
      assert(event.kind==='reserved'&&!killed);
      await owned.terminate(short());killed=true;
    }));
    assert(killed&&reservedEvents.length===1);await unchangedSupervisor();add(1);
    const successorJournal=()=>transaction(query=>query(
      'SELECT dispatch_id,state,sequence::text FROM cragkit_qdrant.dispatch_journal WHERE instance_id=$1 AND intent_id=$2 ORDER BY sequence',
      [inputs.instance_id,inputs.successor.intent.intent_id]));
    const pending=await successorJournal();
    async function unpublished(){
      const observed=await snapshot(inputs.successor);
      assert(observed.intent.state==='writing'&&!observed.intent.authority_committed&&!observed.intent.replica_complete
        &&observed.document.active_generation_id===inputs.stage.manifest.generation_id&&observed.pending);
    }
    assert(pending.length===1&&['reserved','unknown'].includes(pending[0][1])&&pending[0][2]==='1');
    assert(pending[0][0]===reservedEvents[0].dispatch_id);await unpublished();add(2);
    async function absent(){
      const attempt=supervisor.issue_attempt({intent_id:'reserved-absence',owner_token:context(inputs.successor,inputs.scope).owner_token,
        epoch:1,dispatch_id:'reserved-absence'},options);
      const transport=supervisor.transport_for(attempt);
      try{
        const raw=await transport.request('POST','/collections/'+inputs.config.physical_collection+'/points',{
          ...options,body:bytes({ids:inputs.successor.manifest.members.map(member=>member.point_id),with_payload:true,with_vector:true})});
        const observed=JSON.parse(Buffer.from(raw).toString('utf8'));
        assert(observed.status==='ok'&&isDeepStrictEqual(observed.result,[]));
      }finally{await transport.close();}
    }
    await absent();add(3);
    await host.close();host=null;
    await bounded(new Promise(resolve=>setTimeout(resolve,1050)),options);
    host=new ManagedQdrantPublicationWorkerHost(supervisor,async(scope,collection,document)=>
      isDeepStrictEqual(scope,inputs.scope)&&collection===inputs.stage.manifest.collection&&document===inputs.stage.manifest.document_id);
    const retryEvents=[];
    await operational(publish(inputs.successor,inputs.scope,async event=>{retryEvents.push(event);}));
    assert(retryEvents.length===0&&isDeepStrictEqual(await successorJournal(),pending));
    await unpublished();await absent();await unchangedSupervisor();add(4);
    await host.close();host=null;await unchangedSupervisor();assert(supervisor.control_binding().alive);add(5);
    return {runtime:'typescript',checks,proof_scope:'reserved_worker_process_only',
      public_results_sha256:createHash('sha256').update(JSON.stringify(results),'utf8').digest('hex')};
  }catch(error){primary=error;throw error;}
  finally{
    const failures=[],deadline=now()+15;
    async function cleanup(operation,action){try{await bounded(Promise.resolve().then(action),{deadline:Math.max(now()+.001,Math.min(now()+8,deadline))});}catch(error){if(failures.length<64)failures.push({operation,outcome:outcome(error)});}}
    if(host)await cleanup('host_close',()=>host.close());
    for(const entry of bundles){for(const [operation,owner] of [['manager_close',entry.manager],['transport_close',entry.transport],['recovery_close',entry.recovery],['verifier_close',entry.verifier],['writer_close',entry.writer],['resource_close',entry.resource]])await cleanup(operation,()=>owner.close());}
    await cleanup('supervisor_resource_close',()=>supervisorResource.close());
    await cleanup('controller_close',()=>supervisor.close());
    if(address)await cleanup('listener_close',()=>listener(address,true));
    if(failures.length)throw new CleanupFailure(primary,failures);
  }
}
try{const value=await bounded(input(),{deadline:now()+5,signal:cancellation.signal});readingInput=false;process.stdout.write(JSON.stringify(await cases(value))+'\n');}
catch(error){process.stdin.destroy();process.stdout.write(JSON.stringify(error instanceof CleanupFailure
  ?{ok:false,step,error:'cleanup_failed',primary:error.primary,cleanup:error.failures}
  :{ok:false,step,error:outcome(error)})+'\n');process.exitCode=1;}
finally{process.removeListener('SIGTERM',cancel);process.removeListener('SIGINT',cancel);}
