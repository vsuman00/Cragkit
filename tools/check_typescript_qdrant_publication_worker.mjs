/** Actual owned-child publication acceptance. No recovery settlement is performed. */
import {execFile,spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {isDeepStrictEqual} from 'node:util';
import {fileURLToPath} from 'node:url';
import {PoolResource,parse_pool_config,bounded,now} from '../packages/typescript/dist/postgres-pool.js';
import {ExecutionLedger,BudgetExhausted} from '../packages/typescript/dist/execution.js';
import {ManagedQdrantPublicationWorkerHost,PublicationWorkerFrameDecoder,encode_worker_frame} from '../packages/typescript/dist/qdrant-publication-worker.js';
import {QdrantPublicationManager,PostgresQdrantPublicationAuthority,ManagedQdrantPublicationTransport,
  PostgresQdrantWriter,PostgresQdrantRecovery,ManagedQdrantSupervisor,QdrantReconciliationVerifier} from '../packages/typescript/dist/qdrant-publication.js';

const CHECKS=[
  'actual_child_publish_and_exit_preserves_parent_supervisor',
  'historical_retry_runs_child_without_physical_rewrite',
  'exhausted_parent_ledger_preserves_durable_state',
  'committed_dispatch_then_owned_worker_sigkill_preserves_previous_generation',
  'fixed_child_channel_eof_preserves_uncertainty_without_http',
  'independent_document_worker_pauses_after_dispatch_before_http',
  'same_supervisor_durable_recovery_retires_paused_worker_key_with_actual_401',
  'retired_worker_cannot_refresh_credential_or_publish',
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
const canonical=value=>Array.isArray(value)?'['+value.map(canonical).join(',')+']':value&&typeof value==='object'
  ?'{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+canonical(value[key])).join(',')+'}':JSON.stringify(value);
const digest=value=>createHash('sha256').update(value).digest('hex');
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
  let address,initialPid,originalIdentity,host,activeJob,pausedWorker,eofChild,eofExit,eofExited=false,primary;
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
  const journal=()=>transaction(query=>query('SELECT intent_id,dispatch_id,state,completion_sha256 FROM cragkit_qdrant.dispatch_journal WHERE instance_id=$1 ORDER BY intent_id,sequence',[inputs.instance_id]));
  const backend=()=>transaction(query=>query('SELECT state,epoch::text,recovery_id FROM cragkit_qdrant.backend_instances WHERE instance_id=$1',[inputs.instance_id]));
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
  async function actualEof(){
    assert(inputs.eof_stage&&inputs.eof_scope);
    const pinned=supervisor.profile_binding(inputs.config),selectedJob=job(inputs.eof_stage,inputs.eof_scope);
    const eofOptions={deadline:Math.min(options.deadline,now()+60),signal:cancellation.signal};
    eofChild=spawn(process.execPath,[fileURLToPath(new URL('../packages/typescript/dist/qdrant-publication-worker.js',import.meta.url)),'--cragkit-publication-worker-r1'],{
      stdio:['ignore','pipe','pipe','pipe'],env:Object.fromEntries(['HOME','TMPDIR','LANG','LC_ALL','TZ'].filter(key=>process.env[key]!==undefined).map(key=>[key,process.env[key]])),windowsHide:true});
    const socket=eofChild.stdio[3],decoder=new PublicationWorkerFrameDecoder(),queue=[];let wake,failure,output=0;
    const fail=()=>{failure=new Error('worker_channel_failed');wake?.();};
    eofExit=new Promise((resolve,reject)=>{eofChild.once('exit',(code,signal)=>{eofExited=true;resolve({code,signal});});eofChild.once('error',()=>{eofExited=true;reject(new Error('worker_spawn_failed'));});});eofExit.catch(()=>{});
    for(const stream of [eofChild.stdout,eofChild.stderr])stream.on('data',chunk=>{output+=chunk.length;if(output>65536){fail();socket.destroy();}});
    socket.on('data',chunk=>{try{queue.push(...decoder.push(chunk));assert(queue.length<=2);wake?.();}catch{fail();socket.destroy();}});
    socket.on('error',fail);socket.on('end',fail);socket.on('close',fail);
    async function send(frame){await bounded(new Promise((resolve,reject)=>socket.write(encode_worker_frame(frame),error=>error?reject(new Error('worker_send_failed')):resolve())),eofOptions);}
    async function receive(){while(!queue.length){if(failure)throw failure;await bounded(new Promise(resolve=>{wake=resolve;}),eofOptions);wake=undefined;}return queue.shift();}
    const bootstrap=Buffer.from(canonical({v:1,job:selectedJob,identity:pinned,remaining_ms:Math.max(1,Math.floor((eofOptions.deadline-now())*1000))}),'utf8');
    assert(bootstrap.length<=262144);await send({v:1,op:'boot_begin',total:bootstrap.length,sha256:digest(bootstrap)});
    for(let offset=0;offset<bootstrap.length;offset+=48000)await send({v:1,op:'boot_chunk',offset,data:bootstrap.subarray(offset,offset+48000).toString('base64')});
    await send({v:1,op:'boot_end'});
    let id=0,issued,issuedBinding,barrier=false;
    for(;;){
      const frame=await receive();assert(isDeepStrictEqual(Object.keys(frame).sort(),['data','id','op','remaining_ms','v'])&&frame.v===1&&frame.id===++id&&id<=128
        &&Number.isSafeInteger(frame.remaining_ms)&&frame.remaining_ms>0&&frame.remaining_ms<=300000);
      const data=frame.data;let reply;
      if(frame.op==='profile'){assert(isDeepStrictEqual(data,{config_sha256:digest(canonical(inputs.config))}));reply=supervisor.profile_binding(inputs.config);assert(isDeepStrictEqual(reply,pinned));}
      else if(frame.op==='authorize'){assert(isDeepStrictEqual(data,{reference:selectedJob.reference,scope_sha256:digest(canonical(inputs.eof_scope))}));reply={allowed:true};}
      else if(frame.op==='issue'){
        assert(!issued&&isDeepStrictEqual(Object.keys(data).sort(),['dispatch_id','epoch','intent_id','owner_token'])&&data.intent_id===selectedJob.reference.intent_id&&data.epoch===pinned.epoch);
        issued=supervisor.issue_attempt(data,eofOptions);issuedBinding=supervisor.attempt_binding(issued);let credential;
        await supervisor.deliver_worker_credential(issued,value=>{assert(!credential);credential=value;},eofOptions);
        reply={attempt_id:1,binding:issuedBinding,endpoint:credential.endpoint,api_key:credential.api_key};credential=undefined;
      }else if(frame.op==='validate'){assert(issued&&isDeepStrictEqual(data,{attempt_id:1}));reply={binding:supervisor.attempt_binding(issued)};assert(isDeepStrictEqual(reply.binding,issuedBinding));}
      else if(frame.op==='before_write'){
        assert(issued&&isDeepStrictEqual(Object.keys(data).sort(),['attempt_id','dispatch_id','request_sha256','sequence'])&&data.attempt_id===1&&data.dispatch_id===issuedBinding.dispatch_id&&data.sequence===1&&/^[0-9a-f]{64}$/.test(data.request_sha256));
        barrier=true;socket.end();break;
      }else throw new Error('unexpected_worker_operation');
      await send({v:1,id,ok:true,data:reply});reply=undefined;
    }
    const exit=await bounded(eofExit,{deadline:Math.min(options.deadline,now()+8)});assert(barrier&&eofExited&&exit.code!==0);socket.destroy();eofChild=null;
  }
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
    const writes=[],barriers=[];
    const normal=async event=>{if(event.kind==='before_write')barriers.push(event);else writes.push(event);};
    const first=save(await publish(inputs.stage,inputs.scope,normal));
    assert(writes.length===1&&writes[0].status===200&&barriers.length===1
      &&writes[0].attempt_id===barriers[0].attempt_id&&writes[0].dispatch_id===barriers[0].dispatch_id);
    await unchangedSupervisor();const settled=await journal();assert(settled.length===1&&settled[0][2]==='settled');add(0);
    const historicalEvents=[];const historical=save(await publish(inputs.stage,inputs.scope,async event=>{historicalEvents.push(event);}));
    assert(isDeepStrictEqual(first,historical)&&historicalEvents.length===0&&isDeepStrictEqual(await journal(),settled));await unchangedSupervisor();add(1);
    const exhausted=book(),priorAttempt=exhausted.reserve({attempts:1});exhausted.dispatch(priorAttempt);exhausted.reconcile(priorAttempt);let denied=false;
    try{await host.publish(job(inputs.stage),exhausted,options);}catch(error){assert(error instanceof BudgetExhausted);denied=true;}
    assert(denied);accounting(exhausted,1);assert(isDeepStrictEqual(await journal(),settled));add(2);
    await stage(inputs.successor);
    let killed=false;
    await operational(publish(inputs.successor,inputs.scope,async(event,owned)=>{
      if(event.kind==='before_write'){assert(!killed);await owned.terminate(short());killed=true;}
      else throw new Error('killed_worker_sent_http');
    }));
    assert(killed);await unchangedSupervisor();
    const afterKill=await snapshot(inputs.successor),pendingA=(await journal()).filter(row=>row[0]===inputs.successor.intent.intent_id);
    assert(afterKill.intent.state==='writing'&&!afterKill.intent.authority_committed&&!afterKill.intent.replica_complete
      &&afterKill.document.active_generation_id===inputs.stage.manifest.generation_id&&afterKill.pending
      &&pendingA.length===1&&['dispatched','unknown'].includes(pendingA[0][2]));add(3);
    await stage(inputs.eof_stage,inputs.eof_scope);await actualEof();await unchangedSupervisor();
    const afterEof=await snapshot(inputs.eof_stage,inputs.eof_scope),eofJournal=(await journal()).filter(row=>row[0]===inputs.eof_stage.intent.intent_id);
    assert(afterEof.intent.state==='writing'&&!afterEof.intent.authority_committed&&!afterEof.intent.replica_complete&&afterEof.document.active_generation_id===null&&afterEof.pending
      &&eofJournal.length===1&&['dispatched','unknown'].includes(eofJournal[0][2]));
    const absenceAttempt=supervisor.issue_attempt({intent_id:'eof-absence',owner_token:context(inputs.eof_stage,inputs.eof_scope).owner_token,epoch:1,dispatch_id:'eof-absence'},options);
    const absenceTransport=supervisor.transport_for(absenceAttempt);
    try{
      const raw=await absenceTransport.request('POST','/collections/'+inputs.config.physical_collection+'/points',{
        ...options,body:bytes({ids:inputs.eof_points.map(point=>point.id),with_payload:true,with_vector:true})});
      const observed=JSON.parse(Buffer.from(raw).toString('utf8'));assert(observed.status==='ok'&&isDeepStrictEqual(observed.result,[]));
    }finally{await absenceTransport.close();}
    add(4);
    await stage(inputs.second_stage,inputs.second_scope);
    let arrived;const paused=new Promise(resolve=>{arrived=resolve;});let statuses=[];
    activeJob=publish(inputs.second_stage,inputs.second_scope,async(event,owned)=>{
      if(event.kind==='before_write'){assert(!pausedWorker);await owned.pause(short());pausedWorker=owned;arrived();}
      else statuses.push(event.status);
    });activeJob.catch(()=>{});
    await bounded(Promise.race([paused,activeJob.then(()=>{throw new Error('worker_pause_missing');})]),options);
    const pendingB=(await journal()).filter(row=>row[0]===inputs.second_stage.intent.intent_id);
    assert(statuses.length===0&&pendingB.length===1&&pendingB[0][2]==='dispatched');add(5);
    // This bounded window has three max-one clients: stopped child, parent writer and supervisor.
    const recoveryEntry=await bundle();
    try{
      const proof=await recoveryEntry.recovery.recover('worker-native-recovery',options),binding=supervisor.recovery_binding(proof);
      assert(binding.new_epoch===2&&binding.credential_generation!==originalIdentity.credential_generation);
    }finally{await closeBundle(recoveryEntry);}
    assert(isDeepStrictEqual(await backend(),[['recovery_blocked','2','worker-native-recovery']])&&await listener(address)!==initialPid);
    await pausedWorker.resume(short());pausedWorker=null;
    await operational(activeJob);activeJob=null;assert(isDeepStrictEqual(statuses,[401]));add(6);
    const afterRetire=await snapshot(inputs.second_stage,inputs.second_scope);
    const old=await snapshot(inputs.successor);
    const remaining=await journal();
    assert(afterRetire.intent.state==='writing'&&!afterRetire.intent.authority_committed&&!afterRetire.intent.replica_complete
      &&afterRetire.document.active_generation_id===null&&afterRetire.pending
      &&old.document.active_generation_id===inputs.stage.manifest.generation_id&&old.pending
      &&remaining.filter(row=>row[0]!==inputs.stage.intent.intent_id).every(row=>['dispatched','unknown'].includes(row[2]))
      &&remaining.length===4&&isDeepStrictEqual(await backend(),[['recovery_blocked','2','worker-native-recovery']]));add(7);
    pausedWorker=null;
    await host.close();host=null;assert(supervisor.control_binding().alive&&await listener(address));add(8);
    return {runtime:'typescript',checks,proof_scope:'ordinary_worker_process_only',
      public_results_sha256:createHash('sha256').update(JSON.stringify(results),'utf8').digest('hex')};
  }catch(error){primary=error;throw error;}
  finally{
    const failures=[],deadline=now()+15;
    async function cleanup(operation,action){try{await bounded(Promise.resolve().then(action),{deadline:Math.max(now()+.001,Math.min(now()+8,deadline))});}catch(error){if(failures.length<64)failures.push({operation,outcome:outcome(error)});}}
    if(eofChild&&!eofExited)await cleanup('worker_terminate',async()=>{assert(eofChild.kill('SIGKILL'));await bounded(eofExit,{deadline:Math.min(now()+5,deadline)});});
    if(pausedWorker)await cleanup('worker_terminate',()=>pausedWorker.terminate({deadline:Math.min(now()+5,deadline)}));
    if(host)await cleanup('host_close',()=>host.close());
    if(activeJob)await cleanup('publish_drain',()=>activeJob.catch(()=>{}));
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
