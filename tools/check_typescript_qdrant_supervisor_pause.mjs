/** Actual reversible loss of the process owning the native supervisor. */
import {spawn,execFile} from 'node:child_process';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {isDeepStrictEqual as same} from 'node:util';
import {PoolResource,parse_pool_config,bounded,now} from '../packages/typescript/dist/postgres-pool.js';
import {ExecutionLedger} from '../packages/typescript/dist/execution.js';
import {ManagedQdrantPublicationWorkerHost} from '../packages/typescript/dist/qdrant-publication-worker.js';
import {QdrantPublicationManager,PostgresQdrantPublicationAuthority,ManagedQdrantPublicationTransport,
  PostgresQdrantWriter,PostgresQdrantRecovery,ManagedQdrantSupervisor,QdrantReconciliationVerifier}
  from '../packages/typescript/dist/qdrant-publication.js';
import {ProviderUnavailable,UnsupportedCapability} from '../packages/typescript/dist/errors.js';

const CHECKS=Object.freeze([
  'actual_capability_and_dispatch_before_pause','supervisor_process_stopped_server_preserved',
  'competing_supervisor_refused_without_start','independent_successor_owner_refused',
  'durable_uncertainty_and_pointer_preserved','repeat_refusal_while_supervisor_stopped',
  'same_owner_resumed_for_verified_cleanup',
]);
const ERRORS=new Set(['IntegrityViolation','UnauthorizedScope','UnsupportedCapability','InvalidRequest',
  'ProviderUnavailable','DeadlineExceeded','IndexNotReady','BudgetExhausted','AbortError']);
const cancellation=new AbortController();let reading=true,step=0;
const assert=value=>{if(!value)throw new Error('acceptance_failed');};
const encode=value=>Buffer.from(JSON.stringify(value),'utf8');
const decode=value=>JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.from(value)));
const hash=value=>createHash('sha256').update(value).digest('hex');
const cancel=()=>{cancellation.abort();if(reading)process.stdin.destroy();};
process.on('SIGTERM',cancel);process.on('SIGINT',cancel);
const reference=stage=>({collection:stage.manifest.collection,document_id:stage.manifest.document_id,intent_id:stage.intent.intent_id});
async function input(){
  const chunks=[];let size=0;
  for await(const chunk of process.stdin){size+=chunk.length;assert(size<=1048576);chunks.push(chunk);}
  const value=decode(Buffer.concat(chunks));
  assert(value&&same(Object.keys(value).sort(),['binary','inputs','observer_config','supervisor_config','work_dir','writer_config'])
    &&typeof value.binary==='string'&&typeof value.work_dir==='string'&&value.inputs?.competing_successor);
  return value;
}
async function command(binary,args,options){
  return bounded(new Promise((resolve,reject)=>execFile(binary,args,{encoding:'utf8',env:{PATH:'/usr/bin:/bin'},
    maxBuffer:16384,timeout:3000,killSignal:'SIGKILL'},(error,out,err)=>error||err?reject(new Error('process_observation')):resolve(out))),options);
}
async function listener(endpoint,options,absent=false){
  const url=new URL(endpoint);assert(url.protocol==='http:'&&url.hostname==='127.0.0.1'&&url.port&&url.origin===endpoint);
  const result=await bounded(new Promise((resolve,reject)=>execFile('/usr/sbin/lsof',
    ['-nP','-a','-iTCP@127.0.0.1:'+url.port,'-sTCP:LISTEN','-t'],
    {encoding:'utf8',env:{PATH:'/usr/bin:/bin'},maxBuffer:1024,timeout:3000,killSignal:'SIGKILL'},(error,out,err)=>{
      if(absent&&error?.code===1&&out===''&&err==='')return resolve(null);
      if(error||err||absent||!/^[1-9][0-9]{0,9}\n?$/.test(out))return reject(new Error('listener_observation'));
      resolve(Number(out.trim()));
    })),options);return result;
}
async function closeAll(owners){
  let failed=false;const deadline=now()+20;
  for(const owner of owners)try{await bounded(Promise.resolve().then(()=>owner.close()),{deadline:Math.min(deadline,now()+5)});}catch{failed=true;}
  if(failed)throw new Error('cleanup_failed');
}
async function child(value){
  assert(typeof process.send==='function');
  const {inputs}=value,options={deadline:now()+120,signal:cancellation.signal};
  const pools=[value.writer_config,value.supervisor_config].map(raw=>new PoolResource(parse_pool_config(raw)));
  assert(pools.every(pool=>pool.config.max_size===1));
  const supervisor=new ManagedQdrantSupervisor(value.binary,value.work_dir,inputs.instance_id,inputs.config);
  const writer=new PostgresQdrantWriter(pools[0],inputs.config,inputs.instance_id);
  const verifier=new QdrantReconciliationVerifier(writer,supervisor);
  const recovery=new PostgresQdrantRecovery(pools[1],inputs.config,supervisor,verifier);
  const transport=new ManagedQdrantPublicationTransport(supervisor);
  const authorize=async(scope,collection,document)=>same(scope,inputs.scope)&&collection===inputs.stage.manifest.collection&&document===inputs.stage.manifest.document_id;
  const manager=new QdrantPublicationManager(new PostgresQdrantPublicationAuthority(writer,recovery),transport,inputs.config,supervisor,authorize);
  let host,endpoint,owned,job,releaseCleanup,events=0,writeObserved=false,primary;
  const cleanupCommand=new Promise(resolve=>{releaseCleanup=resolve;});
  const onMessage=message=>{if(same(message,{kind:'cleanup'}))releaseCleanup();else cancellation.abort();};
  process.on('message',onMessage);process.once('disconnect',cancel);
  const notify=message=>bounded(new Promise((resolve,reject)=>process.send(message,error=>error?reject(new Error('ipc_failed')):resolve())),options);
  const limits={deadline_ms:60000,max_attempts:1,max_provider_calls:0};
  async function call(work){
    const ledger=new ExecutionLedger({limits,deadline:options.deadline});
    try{return await work(ledger);}finally{const usage=ledger.snapshot();assert(usage.attempts===1&&usage.pending===0&&usage.provider_calls===0);}
  }
  try{
    await supervisor.initialize({...options,provision:async(admin,probe)=>{
      for(const [name,config] of [[inputs.config.physical_collection,inputs.collection_config],[probe.collection,probe.collection_config]])
        await admin.request('PUT','/collections/'+name,{...options,body:[...encode(config)]});
      const completed=decode(await admin.request('PUT','/collections/'+probe.collection+'/points?wait=true&ordering=strong',
        {...options,body:[...encode({points:[probe.point]})]}));assert(completed.status==='ok'&&completed.result.status==='completed');
    }});
    endpoint=supervisor.identity().endpoint;
    for(const pool of pools)await pool.open();await manager.initialize(options);
    await call(book=>manager.stage(inputs.stage,inputs.scope,book,options));
    assert((await call(book=>manager.publish(reference(inputs.stage),inputs.scope,book,options))).published);
    for(const stage of [inputs.successor,inputs.competing_successor])await call(book=>manager.stage(stage,inputs.scope,book,options));
    // Release both bootstrap SQL pools before the worker and two outer observers connect.
    await closeAll([manager,transport,recovery,verifier,writer,...pools]);
    host=new ManagedQdrantPublicationWorkerHost(supervisor,authorize);
    job=call(book=>host.publish({writer_pool:value.writer_config,config:inputs.config,scope:inputs.scope,
      reference:reference(inputs.successor),limits},book,{...options,observer:async(event,worker)=>{
        if(event.kind==='write_observed'){writeObserved=true;throw new Error('old_worker_wrote');}
        if(event.kind==='reserved'){assert(events===0);events++;return;}
        assert(event.kind==='before_write'&&events===1&&event.attempt_id===1&&event.sequence===1);events++;owned=worker;
        await notify({kind:'barrier',endpoint,server_pid:await listener(endpoint,options),
          dispatch_id:event.dispatch_id,request_sha256:event.request_sha256});
        await bounded(cleanupCommand,options);
        await worker.terminate({deadline:Math.min(options.deadline,now()+5)});
        owned=undefined;
        throw new ProviderUnavailable();
      }})).then(result=>({result}),error=>({error}));
    const outcome=await bounded(job,options);job=null;
    assert(outcome.error&&ERRORS.has(outcome.error.name)&&events===2&&!writeObserved);
  }catch(error){primary=error;throw error;}
  finally{
    releaseCleanup();
    let failed=false;
    if(job){cancellation.abort();try{await bounded(job,{deadline:now()+5});}catch{failed=true;}}
    if(owned)try{await owned.terminate({deadline:now()+5});}catch{failed=true;}
    try{await closeAll([...(host?[host]:[]),manager,transport,recovery,verifier,writer,...pools,supervisor]);}catch{failed=true;}
    if(endpoint)try{await listener(endpoint,{deadline:now()+5},true);}catch{failed=true;}
    process.removeListener('message',onMessage);process.removeListener('disconnect',cancel);
    if(failed)throw new Error('cleanup_failed');
  }
  await notify({kind:'cleaned',worker_reaped:true,server_closed:true,no_write:!writeObserved});
}
async function outer(value){
  const {inputs}=value,options={deadline:now()+140,signal:cancellation.signal};
  const observer=new PoolResource(parse_pool_config(value.observer_config));
  const resource=new PoolResource(parse_pool_config(value.writer_config));
  assert(observer.config.max_size===1&&resource.config.max_size===1);
  const writer=new PostgresQdrantWriter(resource,inputs.config,inputs.instance_id);
  const competitor=new ManagedQdrantSupervisor(value.binary,value.work_dir,inputs.instance_id,inputs.config);
  const checks=[],rows=[];const add=row=>{rows.push(row);checks.push(CHECKS[checks.length]);step=checks.length;};
  let childProcess,exit,exited=false,stopped=false,barrier,cleaned=false,provisions=0,primary;
  const query=(text,values=[])=>observer.withLease(options,async client=>(await bounded(client.query({text,values,rowMode:'array'}),options)).rows);
  const target=[inputs.scope.tenant_id,inputs.stage.manifest.collection,inputs.stage.manifest.document_id];
  async function snapshot(){
    const tables=['documents','document_owners','publication_intents','dispatch_journal','dispatch_points','preparations','preparation_attestations'];
    const parts=tables.map(table=>`'${table}',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY to_jsonb(r)::text),'[]'::jsonb) FROM cragkit_qdrant.${table} r WHERE tenant_id=$1 AND collection=$2 AND document_id=$3)`);
    const result=await query(`SELECT encode(sha256(convert_to(jsonb_build_object(${parts.join(',')})::text,'UTF8')),'hex')`,target);
    assert(result.length===1&&/^[a-f0-9]{64}$/.test(result[0][0]));return result[0][0];
  }
  const context={scope:inputs.scope,...reference(inputs.competing_successor),owner_token:'00000000-0000-4000-8000-000000000099'};
  async function refusal(){
    let rejected=false;
    try{await writer.acquire_owner(context,options);}catch(error){assert(error instanceof ProviderUnavailable);rejected=true;}
    assert(rejected);
    assert(same(await query('SELECT count(*)::text FROM cragkit_qdrant.dispatch_journal WHERE tenant_id=$1 AND collection=$2 AND document_id=$3 AND intent_id=$4',
      [...target,inputs.competing_successor.intent.intent_id]),[['0']]));
  }
  async function state(){
    assert(childProcess&&!exited);
    const observed=(await command('/bin/ps',['-o','state=','-p',String(childProcess.pid)],options)).trim();
    assert(observed.length>0);return observed;
  }
  async function expectStopped(){assert((await state()).startsWith('T')&&await listener(barrier.endpoint,options)===barrier.server_pid);}
  try{
    childProcess=spawn(process.execPath,[fileURLToPath(import.meta.url),'--owned-supervisor'],{
      stdio:['pipe','pipe','pipe','ipc'],env:Object.fromEntries(['HOME','TMPDIR','LANG','LC_ALL','TZ'].filter(key=>process.env[key]!==undefined).map(key=>[key,process.env[key]])),windowsHide:true});
    exit=new Promise((resolve,reject)=>{childProcess.once('error',()=>{exited=true;reject(new Error('child_failed'));});
      childProcess.once('exit',(code,signal)=>{exited=true;resolve({code,signal});});});void exit.catch(()=>{});
    let reached,rejectBarrier;const entered=new Promise((resolve,reject)=>{reached=resolve;rejectBarrier=reject;});
    let output=0,messages=0;
    for(const stream of [childProcess.stdout,childProcess.stderr])stream.on('data',chunk=>{
      output+=chunk.length;if(output>65536){rejectBarrier(new Error('child_output_limit'));cancellation.abort();}
    });
    childProcess.on('message',message=>{
      try{
        assert(++messages<=2);
        if(message?.kind==='barrier'){
          assert(!barrier&&same(Object.keys(message).sort(),['dispatch_id','endpoint','kind','request_sha256','server_pid'])
            &&typeof message.dispatch_id==='string'&&/^[a-f0-9]{64}$/.test(message.request_sha256)&&Number.isInteger(message.server_pid)&&message.server_pid>1);
          barrier=message;reached();
        }else{assert(same(message,{kind:'cleaned',worker_reaped:true,server_closed:true,no_write:true}));cleaned=true;}
      }catch(error){rejectBarrier(error);cancellation.abort();}
    });
    childProcess.stdin.end(encode(value));
    await bounded(Promise.race([entered,exit.then(()=>{throw new Error('barrier_missing');})]),options);
    await observer.open();await resource.open();await writer.initialize(options);
    const journal=await query('SELECT dispatch_id,state,request_sha256 FROM cragkit_qdrant.dispatch_journal WHERE tenant_id=$1 AND collection=$2 AND document_id=$3 AND intent_id=$4 ORDER BY sequence',
      [...target,inputs.successor.intent.intent_id]);
    assert(same(journal,[[barrier.dispatch_id,'dispatched',barrier.request_sha256]]));
    const document=await query('SELECT active_generation_id FROM cragkit_qdrant.documents WHERE tenant_id=$1 AND collection=$2 AND document_id=$3',target);
    const owner=await query('SELECT intent_id,backend_epoch::text FROM cragkit_qdrant.document_owners WHERE tenant_id=$1 AND collection=$2 AND document_id=$3',target);
    assert(same(document,[[inputs.stage.manifest.generation_id]])&&same(owner,[[inputs.successor.intent.intent_id,'1']]));
    const retained=await snapshot();add(['capability','dispatched',1]);
    assert(!exited&&childProcess.kill('SIGSTOP'));stopped=true;
    const stopDeadline=Math.min(options.deadline,now()+5);
    while(!(await state()).startsWith('T')){assert(now()<stopDeadline);await bounded(new Promise(resolve=>setTimeout(resolve,10)),options);}
    await expectStopped();add(['pause',true,true]);
    let denied=false;
    try{await competitor.initialize({...options,provision:async()=>{provisions++;throw new Error('unexpected_provision');}});}
    catch(error){assert(error instanceof UnsupportedCapability||error instanceof ProviderUnavailable);denied=true;}
    assert(denied&&provisions===0);await expectStopped();add(['competitor','refused',0]);
    await refusal();add(['successor','ProviderUnavailable',0]);
    assert(await snapshot()===retained);await expectStopped();add(['preserved',true,true,true]);
    for(let repeat=0;repeat<2;repeat++){await refusal();assert(await snapshot()===retained);await expectStopped();}
    add(['repeat',2,0]);
    assert(!exited&&childProcess.kill('SIGCONT'));stopped=false;
    const resumeDeadline=Math.min(options.deadline,now()+5);
    while((await state()).startsWith('T')){assert(now()<resumeDeadline);await bounded(new Promise(resolve=>setTimeout(resolve,10)),options);}
    childProcess.send({kind:'cleanup'});
    const ended=await bounded(exit,options);assert(ended.code===0&&ended.signal===null&&cleaned);
    await listener(barrier.endpoint,options,true);
    // A cleanup error may change dispatched to unknown, but cannot publish the old intent.
    const final=await query('SELECT state,authority_committed,replica_complete FROM cragkit_qdrant.publication_intents WHERE tenant_id=$1 AND collection=$2 AND document_id=$3 AND intent_id=$4',
      [...target,inputs.successor.intent.intent_id]);assert(same(final,[['writing',false,false]]));
    assert(same(await query('SELECT active_generation_id FROM cragkit_qdrant.documents WHERE tenant_id=$1 AND collection=$2 AND document_id=$3',target),document));
  }catch(error){primary=error;throw error;}
  finally{
    const failures=[];
    if(childProcess&&!exited){
      try{
        if(stopped){assert(childProcess.kill('SIGCONT'));stopped=false;}
        if(childProcess.connected)childProcess.send({kind:'cleanup'});
        await bounded(exit,{deadline:now()+12});
      }catch{failures.push(true);if(!exited)childProcess.kill('SIGTERM');}
    }
    try{await closeAll([competitor,writer,resource,observer]);}catch{failures.push(true);}
    if(barrier)try{await listener(barrier.endpoint,{deadline:now()+5},true);}catch{failures.push(true);}
    if(failures.length)throw new Error('cleanup_failed');
    if(!primary)add(['cleanup',true,true,true]);
  }
  assert(same(checks,CHECKS));
  return {runtime:'typescript',checks,proof_scope:'native_supervisor_pause_blocks_only',
    public_results_sha256:hash(encode(['cragkit.qdrant.supervisor-pause.v1',rows]))};
}
try{
  const value=await bounded(input(),{deadline:now()+5,signal:cancellation.signal});reading=false;
  if(process.argv[2]==='--owned-supervisor'){await child(value);process.disconnect();}
  else process.stdout.write(JSON.stringify(await outer(value))+'\n');
}catch(error){
  process.stdin.destroy();
  if(process.argv[2]==='--owned-supervisor'){if(process.connected)process.disconnect();process.exitCode=1;}
  else{process.stdout.write(JSON.stringify({ok:false,step,error:error?.message==='cleanup_failed'?'cleanup_failed':ERRORS.has(error?.name)?error.name:'internal'})+'\n');process.exitCode=1;}
}finally{process.removeListener('SIGTERM',cancel);process.removeListener('SIGINT',cancel);}
