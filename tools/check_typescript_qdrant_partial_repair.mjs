/** Actual nine-point partial repair on disposable native servers. */
import {execFile} from 'node:child_process';
import {promises as fs} from 'node:fs';
import {resolve,join} from 'node:path';
import http from 'node:http';
import {isDeepStrictEqual as same} from 'node:util';
import {PoolResource,parse_pool_config,bounded,now} from '../packages/typescript/dist/postgres-pool.js';
import {ExecutionLedger} from '../packages/typescript/dist/execution.js';
import {QdrantPublicationManager,PostgresQdrantPublicationAuthority,ManagedQdrantPublicationTransport,
  PostgresQdrantWriter,PostgresQdrantRecovery,ManagedQdrantSupervisor,QdrantReconciliationVerifier} from '../packages/typescript/dist/qdrant-publication.js';
import {ProviderUnavailable,UnauthorizedScope,IntegrityViolation} from '../packages/typescript/dist/errors.js';

const CHECKS=Object.freeze([
  'partial_nine_point_write_preserves_previous_active',
  'callback_denial_after_reservation_preserves_gate_and_pointer',
  'recovery_sql_ack_loss_confirms_without_http_resend',
  'same_intent_nine_point_publication_with_one_attempt',
  'unknown_recovery_write_cannot_settle_current_credential',
  'actual_refence_rejects_old_key_and_resumes_without_duplicate_recovery_write',
  'corrupt_and_extra_members_rejected_before_recovery_write',
  'foreign_uncertainty_preserved_and_global_reopen_blocked',
]);
const ERRORS=new Set(['IntegrityViolation','InvalidRequest','ProviderUnavailable','UnauthorizedScope',
  'UnsupportedCapability','DeadlineExceeded','IndexNotReady','AbortError']);
const OWNER='00000000-0000-4000-8000-000000000001';
const cancellation=new AbortController();let readingInput=true,step=0;
const cancel=()=>{cancellation.abort();if(readingInput)process.stdin.destroy();};
process.on('SIGTERM',cancel);process.on('SIGINT',cancel);
const bytes=value=>[...Buffer.from(JSON.stringify(value),'utf8')];
function outcome(error){let name;try{name=error?.name;}catch{return 'internal';}return ERRORS.has(name)?name:'internal';}
class RuntimeCleanupFailure extends Error{
  constructor(primary,failures){super('runtime_cleanup_failed');this.primary=primary?outcome(primary):null;this.failures=failures;}
}
async function input(){
  const chunks=[];let length=0;
  for await(const chunk of process.stdin){length+=chunk.length;if(length>1048576)throw new Error('bounded_input');chunks.push(chunk);}
  const value=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks)));
  if(!value||typeof value!=='object'||Array.isArray(value)
    ||!same(Object.keys(value).sort(),['binary','inputs','supervisor_config','work_dir','writer_config'])
    ||typeof value.binary!=='string'||typeof value.work_dir!=='string'||!value.inputs?.second_stage
    ||!['partial','unknown','corrupt','foreign'].every(key=>value.inputs?.stages?.[key]))throw new Error('input_shape');
  return value;
}
async function listener(address,absent=false){
  const url=new URL(address);
  if(url.protocol!=='http:'||url.hostname!=='127.0.0.1'||!url.port||url.origin!==address)throw new Error('endpoint_shape');
  return new Promise((resolve,reject)=>execFile('/usr/sbin/lsof',['-nP','-a','-iTCP@127.0.0.1:'+url.port,'-sTCP:LISTEN','-t'],
    {encoding:'utf8',env:{PATH:'/usr/bin:/bin'},maxBuffer:1024,timeout:3000,killSignal:'SIGKILL'},(error,stdout,stderr)=>{
      if(absent&&error?.code===1&&stdout===''&&stderr==='')return resolve(null);
      if(error||stderr||absent||!/^[1-9][0-9]{0,9}\n?$/.test(stdout))return reject(new Error('listener_observation'));
      resolve(Number(stdout.trim()));
    }));
}
async function refuses(operation,Type){
  try{await operation();}catch(error){if(error instanceof Type&&(Type!==DOMException||error.name==='AbortError'))return;throw error;}
  throw new Error('expected_refusal_missing');
}
async function cases(value){
  const {inputs}=value,writerConfig=parse_pool_config(value.writer_config),supervisorConfig=parse_pool_config(value.supervisor_config);
  if(writerConfig.max_size!==1||supervisorConfig.max_size!==1)throw new Error('two_client_ceiling');
  const options={deadline:now()+240,signal:cancellation.signal};
  const resource=new PoolResource(writerConfig),supervisorResource=new PoolResource(supervisorConfig);
  const writer=new PostgresQdrantWriter(resource,inputs.config,inputs.instance_id);
  const supervisor=new ManagedQdrantSupervisor(value.binary,value.work_dir,inputs.instance_id,inputs.config);
  const reconciliation=new QdrantReconciliationVerifier(writer,supervisor);
  const recovery=new PostgresQdrantRecovery(supervisorResource,inputs.config,supervisor,reconciliation);
  const authority=new PostgresQdrantPublicationAuthority(writer,recovery),transport=new ManagedQdrantPublicationTransport(supervisor);
  const checks=[],handles=new Set(),ordinaryBodies=[],recoveryBodies=[],recoveryBindings=[],ack={armed:false,reserve:0,dispatched:0,settled:0,destroyed:0};
  let manager,address,primary,ordinaryPuts=0,recoveryPuts=0,dropOrdinary=false,dropRecovery=false;
  let denyAfterReservation=false,denialFired=false,lastProof,retiredKey,lostOrdinaryIds;
  const target='/collections/'+inputs.config.physical_collection;
  const reference=stage=>({collection:stage.manifest.collection,document_id:stage.manifest.document_id,intent_id:stage.intent.intent_id});
  const context=(stage,scope=inputs.scope,token=OWNER)=>({...reference(stage),scope,owner_token:token});
  const ledger=()=>new ExecutionLedger({limits:{deadline_ms:240000,max_attempts:1,max_provider_calls:0},deadline:options.deadline});
  const mark=()=>{checks.push(CHECKS[checks.length]);step=checks.length;};
  const snapshot=(stage,scope=inputs.scope)=>writer.manager_snapshot(context(stage,scope),options);
  async function active(generation){if((await snapshot(inputs.stage)).document?.active_generation_id!==generation)throw new Error('active_changed');}
  function completed(raw){const body=JSON.parse(Buffer.from(raw));if(body?.status!=='ok'||body?.result?.status!=='completed')throw new Error('ack_not_completed');}
  function points(stage){
    const manifest=stage.manifest;
    return manifest.members.map((member,index)=>{
      const payload={...inputs.expected_points[0].payload};
      for(const key of ['backend_namespace','physical_collection','collection_incarnation','tenant_id','collection','document_id','revision_id','generation_id','source_sha256','dense_profile','sparse_profile'])payload[key]=manifest[key];
      for(const key of ['chunk_id','start_byte','end_byte','text_sha256'])payload[key]=member[key];
      payload.dense_profile_id=manifest.dense_profile.profile_id;payload.sparse_profile_id=manifest.sparse_profile.profile_id;
      return {id:member.point_id,payload,vector:{dense:stage.dense_vectors[index],sparse:stage.sparse_vectors[index]}};
    });
  }
  async function fixtureKey(){
    const work=resolve(value.work_dir),path=join(work,'config.yaml');
    if(await fs.realpath(work)!==work)throw new Error('owned_work_identity');
    const stat=await fs.lstat(path);
    if(!stat.isFile()||stat.isSymbolicLink()||stat.uid!==process.getuid()||(stat.mode&0o077)!==0||stat.size<1||stat.size>65536||await fs.realpath(path)!==path)throw new Error('owned_config_identity');
    const config=JSON.parse(await fs.readFile(path,'utf8')),key=config?.service?.api_key;
    if(typeof key!=='string'||!/^[0-9a-f]{64}$/.test(key))throw new Error('owned_config_key_shape');
    return key;
  }
  async function rawRequest(method,path,body,key=undefined){
    key??=await fixtureKey();const endpoint=new URL(address),encoded=Buffer.from(JSON.stringify(body));
    if(endpoint.protocol!=='http:'||endpoint.hostname!=='127.0.0.1'||endpoint.origin!==address)throw new Error('loopback_only');
    return new Promise((resolve,reject)=>{
      let request,finished=false;
      const done=(error,result)=>{if(finished)return;finished=true;clearTimeout(timer);options.signal.removeEventListener('abort',abort);if(error)reject(new ProviderUnavailable());else resolve(result);};
      const abort=()=>request?.destroy(new Error('aborted'));
      const timer=setTimeout(()=>request?.destroy(new Error('deadline')),Math.max(1,Math.min(5000,(options.deadline-now())*1000)));
      request=http.request({hostname:'127.0.0.1',port:Number(endpoint.port),method,path,agent:false,maxHeaderSize:16384,
        headers:{'api-key':key,'content-type':'application/json','content-length':encoded.length}},response=>{
        const chunks=[];let length=0;
        response.on('data',chunk=>{length+=chunk.length;if(length>1048576){request.destroy();done(new Error('response_bound'));}else chunks.push(chunk);});
        response.on('end',()=>done(null,{status:response.statusCode,body:Buffer.concat(chunks)}));
        response.on('error',error=>done(error));
      });
      request.on('error',error=>done(error));options.signal.addEventListener('abort',abort,{once:true});
      if(options.signal.aborted){abort();return;}
      request.end(encoded);
    });
  }
  async function faultPut(selected){const response=await rawRequest('PUT',target+'/points?wait=true&ordering=strong',{points:selected});if(response.status!==200)throw new Error('owned_fault_put');completed(response.body);}
  async function faultDelete(ids){const response=await rawRequest('POST',target+'/points/delete?wait=true&ordering=strong',{points:ids});if(response.status!==200)throw new Error('owned_fault_delete');completed(response.body);}
  async function repair(stage,scope=inputs.scope){const book=ledger(),result=await manager.repair(reference(stage),scope,book,options);if(book.snapshot().attempts!==1||book.snapshot().provider_calls!==0)throw new Error('repair_ledger');return result;}
  async function lost(stage,scope=inputs.scope){
    await manager.stage(stage,scope,ledger(),options);dropOrdinary=true;
    await refuses(()=>manager.publish(reference(stage),scope,ledger(),options),ProviderUnavailable);
    const state=await snapshot(stage,scope);
    if(!state.pending||!state.owner)throw new Error('lost_write_not_durable');
    return context(stage,scope,state.owner.owner_token);
  }
  async function journal(){
    return supervisorResource.withLease(options,async client=>{
      await client.query({text:'BEGIN',values:[],rowMode:'array'});
      try{
        await client.query({text:"SELECT set_config('cragkit_qdrant.backend_instance_id',$1,true)",values:[inputs.instance_id],rowMode:'array'});
        const result=await client.query({text:'SELECT intent_id,dispatch_id,sequence,recovery,state FROM cragkit_qdrant.dispatch_journal WHERE instance_id=$1 ORDER BY intent_id,sequence',values:[inputs.instance_id],rowMode:'array'});
        await client.query({text:'COMMIT',values:[],rowMode:'array'});return result.rows;
      }catch(error){await client.query({text:'ROLLBACK',values:[],rowMode:'array'});throw error;}
    });
  }
  const actualLease=supervisorResource.withLease.bind(supervisorResource);
  supervisorResource.withLease=(opts,body)=>actualLease(opts,(client,signal)=>{
    let phase=null,unknown=false;
    return body({async query(query){
      const result=await client.query(query);
      if(/^BEGIN\b/.test(query.text))phase=null;
      if(/^INSERT INTO cragkit_qdrant\.dispatch_journal\b/.test(query.text)&&query.values?.[11]===true)phase='reserve';
      if(/^UPDATE cragkit_qdrant\.dispatch_journal SET state=\$6,completion_sha256=\$7/.test(query.text)){
        if(['dispatched','settled'].includes(query.values?.[5]))phase=query.values[5];
      }
      if(query.text==='COMMIT'&&ack.armed&&phase&&ack[phase]===0){ack[phase]++;unknown=true;throw Object.assign(new Error('committed_ack_loss'),{code:'08006'});}
      return result;
    },getTransactionStatus:()=>client.getTransactionStatus(),release(destroy){if(unknown){if(destroy!==true)throw new Error('unknown_client_reused');ack.destroyed++;unknown=false;}client.release(destroy);}},signal);
  });
  const actualRecover=recovery.recover.bind(recovery);
  recovery.recover=async(...args)=>{const proof=await actualRecover(...args);lastProof=proof;recoveryBindings.push({...supervisor.recovery_binding(proof)});return proof;};
  const actualSession=supervisor.control_session.bind(supervisor);
  supervisor.control_session=body=>actualSession(control=>body(Object.freeze({...control,recovery_transport_for(attempt){
    const actual=control.recovery_transport_for(attempt);
    return {async request(method,path,requestOptions){
      const mutation=method==='PUT'&&path===target+'/points?wait=true&ordering=strong';
      if(mutation){recoveryPuts++;recoveryBodies.push(JSON.parse(Buffer.from(requestOptions.body)).points.map(point=>point.id).sort());}
      const raw=await actual.request(method,path,requestOptions);
      if(mutation&&dropRecovery){completed(raw);dropRecovery=false;retiredKey=await fixtureKey();throw new ProviderUnavailable();}
      return raw;
    },async close(){await actual.close();}};
  }})));
  try{
    await supervisor.initialize({...options,provision:async(admin,probe)=>{
      await admin.request('PUT',target,{...options,body:bytes(inputs.collection_config)});
      await admin.request('PUT','/collections/'+probe.collection,{...options,body:bytes(probe.collection_config)});
      completed(await admin.request('PUT','/collections/'+probe.collection+'/points?wait=true&ordering=strong',{...options,body:bytes({points:[probe.point]})}));
    }});
    address=supervisor.identity().endpoint;await listener(address);
    const actualTransport=supervisor.transport_for.bind(supervisor);
    supervisor.transport_for=attempt=>{
      const actual=actualTransport(attempt);
      const handle={async request(method,path,requestOptions){
        const mutation=method==='PUT'&&path===target+'/points?wait=true&ordering=strong';
        if(mutation){ordinaryPuts++;ordinaryBodies.push(JSON.parse(Buffer.from(requestOptions.body)).points.map(point=>point.id).sort());}
        const raw=await actual.request(method,path,requestOptions);
        if(mutation&&dropOrdinary){completed(raw);lostOrdinaryIds=JSON.parse(Buffer.from(requestOptions.body)).points.map(point=>point.id).sort();dropOrdinary=false;throw new ProviderUnavailable();}return raw;
      },async close(){await actual.close();handles.delete(handle);}};handles.add(handle);return handle;
    };
    await resource.open();await supervisorResource.open();
    manager=new QdrantPublicationManager(authority,transport,inputs.config,supervisor,async(scope,collection,document)=>{
      if(denyAfterReservation){
        const state=await writer.manager_snapshot({...reference(inputs.stages.partial),scope,owner_token:OWNER},options);
        if(state.backend.state==='recovery_blocked'&&state.max_sequence>=2){denialFired=true;return false;}
      }
      return true;
    });
    await manager.initialize(options);
    await manager.stage(inputs.stage,inputs.scope,ledger(),options);
    if(!(await manager.publish(reference(inputs.stage),inputs.scope,ledger(),options)).published)throw new Error('base_publish');
    const partial=inputs.stages.partial;
    const originalIdentity=[partial.intent.intent_id,partial.manifest.revision_id,partial.manifest.generation_id];
    const partialIds=points(partial).map(point=>point.id).sort(),beforePartial=ordinaryPuts;
    if(partialIds.length!==9||new Set(partialIds).size!==9)throw new Error('partial_nine_point_fixture');
    await lost(partial);const ordinaryBeforePartial=ordinaryPuts,partialState=await snapshot(partial);
    const originalIntent=partialState.intent;
    if(ordinaryBeforePartial!==beforePartial+1||!same(lostOrdinaryIds,partialIds.slice(0,8))
      ||partialState.owner?.intent_id!==originalIdentity[0]
      ||!originalIntent||!same([originalIntent.revision_id,originalIntent.generation_id],originalIdentity.slice(1))
      ||originalIntent.manifest_sha256!==partial.intent.manifest_sha256
      ||originalIntent.state==='published')throw new Error('partial_original_identity');
    const sameOriginalIntent=state=>state.owner?.intent_id===originalIdentity[0]&&state.intent&&same(
      [state.intent.revision_id,state.intent.generation_id,state.intent.manifest_sha256,state.intent.payload_sha256],
      [originalIntent.revision_id,originalIntent.generation_id,originalIntent.manifest_sha256,originalIntent.payload_sha256]);
    await active(inputs.stage.manifest.generation_id);mark();
    ack.armed=true;denyAfterReservation=true;
    await refuses(()=>repair(partial),UnauthorizedScope);denyAfterReservation=false;
    const deniedState=await snapshot(partial);
    if(!denialFired||recoveryPuts!==0||deniedState.backend.state!=='recovery_blocked'||!sameOriginalIntent(deniedState)
      ||deniedState.owner?.intent_id!==originalIdentity[0]
      ||deniedState.intent.state==='published')throw new Error('reservation_denial');
    await active(inputs.stage.manifest.generation_id);mark();
    const result=await repair(partial);
    if(!same([ack.reserve,ack.dispatched,ack.settled],[1,1,1])||ack.destroyed!==3||recoveryPuts!==1||!same(recoveryBodies[0],[points(partial).map(point=>point.id).sort()[8]]))throw new Error('recovery_ack_reconciliation');
    mark();
    const publishedState=await snapshot(partial);
    if(ordinaryPuts!==ordinaryBeforePartial+2||!same(ordinaryBodies.slice(ordinaryBeforePartial),[partialIds.slice(0,8),partialIds.slice(8)])
      ||!result.published||!result.replica_complete
      ||!same([result.intent_id,result.revision_id,result.generation_id],originalIdentity)
      ||!sameOriginalIntent(publishedState)||publishedState.intent.state!=='published'||!publishedState.intent.replica_complete
      ||(await journal()).some(row=>row[4]!=='settled'))throw new Error('partial_publication');
    await active(partial.manifest.generation_id);mark();ack.armed=false;
    const unknown=inputs.stages.unknown,unknownCtx=await lost(unknown),beforeUnknown=recoveryPuts;
    dropRecovery=true;
    await refuses(()=>repair(unknown),ProviderUnavailable);
    if(recoveryPuts!==beforeUnknown+1||!retiredKey||!lastProof)throw new Error('recovery_unknown_not_exercised');
    const blockedState=await snapshot(unknown),binding=supervisor.recovery_binding(lastProof),ordinaryBeforeUnknown=ordinaryPuts;
    await refuses(()=>recovery.dispatch_stage_recovery(lastProof,unknownCtx,async()=>true,options),ProviderUnavailable);
    const receipt=await reconciliation.verify(lastProof,unknownCtx,options);
    await refuses(()=>recovery.settle_retired(lastProof,receipt,options),ProviderUnavailable);mark();
    const retried=await repair(unknown),afterUnknown=await snapshot(unknown);
    const old=await rawRequest('PUT',target+'/points?wait=true&ordering=strong',{points:[]},retiredKey);retiredKey=undefined;
    if(old.status!==401||!retried.published||recoveryPuts!==beforeUnknown+1||afterUnknown.backend.epoch!==blockedState.backend.epoch||ordinaryPuts!==ordinaryBeforeUnknown+2||recoveryBindings.at(-1).recovery_id!==binding.recovery_id||recoveryBindings.at(-1).new_epoch!==binding.new_epoch||recoveryBindings.at(-1).credential_generation===binding.credential_generation)throw new Error('unknown_refence_retry');
    mark();
    const corrupt=inputs.stages.corrupt;await lost(corrupt);
    const correct=points(corrupt).sort((a,b)=>a.id<b.id?-1:1),wrong=JSON.parse(JSON.stringify(correct[0]));wrong.vector.dense=wrong.vector.dense.map(number=>-number);
    await faultPut([wrong]);const beforeCorrupt=recoveryPuts;
    await refuses(()=>repair(corrupt),IntegrityViolation);
    await faultPut([correct[0]]);
    const extra=JSON.parse(JSON.stringify(correct[0]));extra.id='ffffffff-ffff-5fff-8fff-ffffffffffff';await faultPut([extra]);
    await refuses(()=>repair(corrupt),IntegrityViolation);
    if(recoveryPuts!==beforeCorrupt)throw new Error('corrupt_recovery_wrote');
    await faultDelete([extra.id]);if(!(await repair(corrupt)).published)throw new Error('corrupt_restore_publish');mark();
    const foreign=inputs.stages.foreign;await lost(foreign);await lost(inputs.second_stage,inputs.second_scope);
    const beforeForeign=await snapshot(inputs.second_stage,inputs.second_scope);
    await refuses(()=>repair(foreign),ProviderUnavailable);
    const finalTarget=await snapshot(foreign),finalForeign=await snapshot(inputs.second_stage,inputs.second_scope);
    if(finalTarget.backend.state!=='recovery_blocked'||finalTarget.pending||!finalForeign.pending||!same(finalForeign.owner,beforeForeign.owner))throw new Error('foreign_uncertainty_changed');
    await active(corrupt.manifest.generation_id);mark();
    return {runtime:'typescript',checks,proof_scope:'native_partial_repair_only'};
  }catch(error){primary=error;throw error;}
  finally{
    retiredKey=undefined;const failures=[],deadline=now()+15;
    const owned=[...(manager?[['manager_close',manager]]:[]),['transport_close',transport],...[...handles].map(handle=>['transport_close',handle]),
      ['reconciliation_close',reconciliation],['recovery_close',recovery],['writer_close',writer],['resource_close',resource],['supervisor_resource_close',supervisorResource],['controller_close',supervisor]];
    for(const [operation,owner]of owned){try{await bounded(Promise.resolve().then(()=>owner.close()),{deadline:Math.max(now()+.001,Math.min(now()+8,deadline))});}catch(error){failures.push({operation,outcome:outcome(error)});}}
    if(address){try{await listener(address,true);}catch(error){failures.push({operation:'listener_close',outcome:outcome(error)});}}
    if(failures.length)throw new RuntimeCleanupFailure(primary,failures);
  }
}
try{const value=await bounded(input(),{deadline:now()+5,signal:cancellation.signal});readingInput=false;process.stdout.write(JSON.stringify(await cases(value))+'\n');}
catch(error){process.stdout.write(JSON.stringify(error instanceof RuntimeCleanupFailure?{ok:false,step,error:'cleanup_failed',primary:error.primary,cleanup:error.failures}:{ok:false,step,error:outcome(error)})+'\n');process.exitCode=1;}
finally{process.removeListener('SIGTERM',cancel);process.removeListener('SIGINT',cancel);}
