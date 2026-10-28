/** Native G1a managed repair on parent-owned disposable servers. */
import {execFile} from 'node:child_process';
import {isDeepStrictEqual as same} from 'node:util';
import {PoolResource,parse_pool_config,bounded,now} from '../packages/typescript/dist/postgres-pool.js';
import {ExecutionLedger} from '../packages/typescript/dist/execution.js';
import {QdrantPublicationManager,PostgresQdrantPublicationAuthority,ManagedQdrantPublicationTransport,
  PostgresQdrantWriter,PostgresQdrantRecovery,ManagedQdrantSupervisor,QdrantReconciliationVerifier} from '../packages/typescript/dist/qdrant-publication.js';
import {ProviderUnavailable,UnauthorizedScope} from '../packages/typescript/dist/errors.js';

const CHECKS=Object.freeze([
  'stage_repair_publishes','same_epoch_prepared_repair_without_point_resend',
  'cross_epoch_prepared_actual_attestation_ack_loss','interrupted_attested_repair_preserves_prior_active',
  'attested_retry_same_generation_without_point_resend','complete_unknown_recovery_then_bounded_verified_replay',
  'historical_repair_no_replay','callback_denial_preserves_active','foreign_unknown_keeps_instance_blocked',
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
    ||!['prepared','cross','uncertain','blocked'].every(key=>value.inputs?.stages?.[key]))throw new Error('input_shape');
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
  const inputs=value.inputs,writerConfig=parse_pool_config(value.writer_config),supervisorConfig=parse_pool_config(value.supervisor_config);
  if(writerConfig.max_size!==1||supervisorConfig.max_size!==1)throw new Error('two_client_ceiling');
  const options={deadline:now()+150,signal:cancellation.signal};
  const resource=new PoolResource(writerConfig),supervisorResource=new PoolResource(supervisorConfig);
  const writer=new PostgresQdrantWriter(resource,inputs.config,inputs.instance_id);
  const supervisor=new ManagedQdrantSupervisor(value.binary,value.work_dir,inputs.instance_id,inputs.config);
  const reconciliation=new QdrantReconciliationVerifier(writer,supervisor);
  const recovery=new PostgresQdrantRecovery(supervisorResource,inputs.config,supervisor,reconciliation);
  const authority=new PostgresQdrantPublicationAuthority(writer,recovery),transport=new ManagedQdrantPublicationTransport(supervisor);
  const checks=[],handles=new Set(),fault={armed:false,fired:0,inserts:0,destroyed:0};
  let manager,address,primary,puts=0,failPut=false,cancelStage=null,denyCallback=false,pausePublish=null;
  const target='/collections/'+inputs.config.physical_collection;
  const reference=stage=>({collection:stage.manifest.collection,document_id:stage.manifest.document_id,intent_id:stage.intent.intent_id});
  const context=(stage,scope=inputs.scope,token=OWNER)=>({...reference(stage),scope,owner_token:token});
  const ledger=()=>new ExecutionLedger({limits:{deadline_ms:120000,max_attempts:1,max_provider_calls:0},deadline:options.deadline});
  const mark=()=>{checks.push(CHECKS[checks.length]);step=checks.length;};
  const repair=async(stage,scope=inputs.scope,opts=options)=>{
    const book=ledger(),result=await manager.repair(reference(stage),scope,book,opts);
    if(book.snapshot().attempts!==1)throw new Error('repair_double_attempt');
    return result;
  };
  const snapshot=(stage,scope=inputs.scope)=>writer.manager_snapshot(context(stage,scope),options);
  async function active(generation){if((await snapshot(inputs.stage)).document?.active_generation_id!==generation)throw new Error('active_changed');}
  function published(result,stage){if(result.operation!=='repair'||result.state!=='published'||!result.published||result.intent_id!==stage.intent.intent_id)throw new Error('repair_result');}
  async function prepare(stage){
    await manager.stage(stage,inputs.scope,ledger(),options);
    const local=new AbortController();cancelStage={stage,local,fired:false};
    await refuses(()=>manager.publish(reference(stage),inputs.scope,ledger(),{...options,signal:AbortSignal.any([options.signal,local.signal])}),DOMException);
    if(!cancelStage.fired)throw new Error('prepare_callback_missing');cancelStage=null;
    const state=await snapshot(stage);
    if(state.intent?.state!=='prepared'||!state.owner)throw new Error('not_prepared');
    return context(stage,inputs.scope,state.owner.owner_token);
  }
  const actualLease=resource.withLease.bind(resource);
  resource.withLease=(opts,body)=>actualLease(opts,(client,signal)=>{
    let inserted=false,unknown=false;
    return body({async query(query){
      const result=await client.query(query);
      if(/^BEGIN\b/.test(query.text))inserted=false;
      if(/^INSERT INTO cragkit_qdrant\.preparation_attestations\b/.test(query.text)){inserted=true;fault.inserts++;}
      if(query.text==='COMMIT'&&inserted&&fault.armed){fault.armed=false;fault.fired++;unknown=true;throw Object.assign(new Error('commit_ack_fault'),{code:'08006'});}
      return result;
    },getTransactionStatus:()=>client.getTransactionStatus(),release(destroy){
      if(unknown){if(destroy!==true)throw new Error('unknown_client_reused');fault.destroyed++;unknown=false;}client.release(destroy);
    }},signal);
  });
  const originalPublish=writer.publish.bind(writer);
  writer.publish=async(ctx,opts)=>{
    if(pausePublish?.intent===ctx.intent_id){
      const row=await writer.attestation_snapshot(ctx,opts);
      if(!row.attestation)throw new Error('pause_without_attestation');
      pausePublish.fired=true;pausePublish.controller.abort();throw new DOMException('Operation aborted.','AbortError');
    }
    return originalPublish(ctx,opts);
  };
  try{
    await supervisor.initialize({...options,provision:async(admin,probe)=>{
      await admin.request('PUT',target,{...options,body:bytes(inputs.collection_config)});
      await admin.request('PUT','/collections/'+probe.collection,{...options,body:bytes(probe.collection_config)});
      const raw=await admin.request('PUT','/collections/'+probe.collection+'/points?wait=true&ordering=strong',{...options,body:bytes({points:[probe.point]})});
      if(JSON.parse(Buffer.from(raw).toString('utf8'))?.result?.status!=='completed')throw new Error('probe_not_completed');
    }});
    address=supervisor.identity().endpoint;await listener(address);
    const actualTransport=supervisor.transport_for.bind(supervisor);
    supervisor.transport_for=capability=>{
      const actual=actualTransport(capability);
      const handle={async request(method,path,opts){
        const mutating=method==='PUT'&&path===target+'/points?wait=true&ordering=strong';
        if(mutating)puts++;
        const response=await actual.request(method,path,opts);
        if(mutating&&failPut){failPut=false;throw new ProviderUnavailable();}
        return response;
      },async close(){await actual.close();handles.delete(handle);}};
      handles.add(handle);return handle;
    };
    await resource.open();await supervisorResource.open();
    manager=new QdrantPublicationManager(authority,transport,inputs.config,supervisor,async scope=>{
      if(denyCallback)return false;
      if(cancelStage&&!cancelStage.fired){
        const state=await writer.inspect(context(cancelStage.stage,scope),options);
        if(state?.state==='prepared'){cancelStage.fired=true;cancelStage.local.abort();throw new DOMException('Operation aborted.','AbortError');}
      }
      return true;
    });
    await manager.initialize(options);
    await manager.stage(inputs.stage,inputs.scope,ledger(),options);published(await repair(inputs.stage),inputs.stage);mark();

    await prepare(inputs.stages.prepared);let before=puts;
    published(await repair(inputs.stages.prepared),inputs.stages.prepared);
    if(puts!==before)throw new Error('same_epoch_resent');mark();

    const cross=inputs.stages.cross,crossContext=await prepare(cross);
    const original=(await writer.attestation_snapshot(crossContext,options)).preparation;
    const proof=await recovery.recover('g1a-external-recovery',options);
    const advanced=await recovery.advance_owner(proof,crossContext,options);
    if(!same(advanced,{owner_token:crossContext.owner_token,backend_epoch:2})
      ||!same(await recovery.reopen(proof,options),{state:'open',epoch:2}))throw new Error('external_recovery_binding');
    before=puts;fault.armed=true;const local=new AbortController();pausePublish={intent:cross.intent.intent_id,controller:local,fired:false};
    await refuses(()=>repair(cross,inputs.scope,{...options,signal:AbortSignal.any([options.signal,local.signal])}),DOMException);
    const attested=await writer.attestation_snapshot(crossContext,options);
    if(fault.armed||fault.fired!==1||fault.destroyed!==1||fault.inserts!==1||!attested.attestation||puts!==before)throw new Error('attestation_ack_loss');mark();
    if(!pausePublish.fired||!same(attested.preparation,original)||(await snapshot(cross)).intent.state!=='prepared')throw new Error('interruption_changed_prepared');
    await active(inputs.stages.prepared.manifest.generation_id);mark();pausePublish=null;
    published(await repair(cross),cross);
    if(puts!==before||fault.inserts!==1)throw new Error('attested_retry_resent');
    const crossState=await snapshot(cross);if(crossState.intent.generation_id!==cross.manifest.generation_id)throw new Error('generation_changed');mark();

    const uncertain=inputs.stages.uncertain;
    await manager.stage(uncertain,inputs.scope,ledger(),options);failPut=true;
    await refuses(()=>manager.publish(reference(uncertain),inputs.scope,ledger(),options),ProviderUnavailable);
    if(!(await snapshot(uncertain)).pending)throw new Error('unknown_not_durable');before=puts;
    published(await repair(uncertain),uncertain);
    const settled=await snapshot(uncertain);
    if(settled.pending||settled.backend.state!=='open'||puts-before!==1)throw new Error('unknown_not_settled_or_replay_unbounded');mark();
    before=puts;published(await repair(uncertain),uncertain);if(puts!==before)throw new Error('historical_replay');mark();

    const blocked=inputs.stages.blocked;
    await manager.stage(blocked,inputs.scope,ledger(),options);denyCallback=true;before=puts;
    await refuses(()=>repair(blocked),UnauthorizedScope);denyCallback=false;
    if(puts!==before)throw new Error('denial_mutated');await active(uncertain.manifest.generation_id);mark();
    failPut=true;await refuses(()=>manager.publish(reference(blocked),inputs.scope,ledger(),options),ProviderUnavailable);
    await manager.stage(inputs.second_stage,inputs.second_scope,ledger(),options);failPut=true;
    await refuses(()=>manager.publish(reference(inputs.second_stage),inputs.second_scope,ledger(),options),ProviderUnavailable);
    before=puts;await refuses(()=>repair(blocked),ProviderUnavailable);
    const targetState=await snapshot(blocked),foreign=await snapshot(inputs.second_stage,inputs.second_scope);
    if(!foreign.pending||targetState.pending||targetState.backend.state!=='recovery_blocked'||puts!==before)throw new Error('foreign_unknown_not_blocked');
    await active(uncertain.manifest.generation_id);mark();
    return {runtime:'typescript',checks,proof_scope:'native_managed_repair_g1a_only'};
  }catch(error){primary=error;throw error;}
  finally{
    const failures=[],deadline=now()+15;
    const owned=[...(manager?[['manager_close',manager]]:[]),['transport_close',transport],
      ...[...handles].map(handle=>['transport_close',handle]),['reconciliation_close',reconciliation],['recovery_close',recovery],
      ['writer_close',writer],['resource_close',resource],['supervisor_resource_close',supervisorResource],['controller_close',supervisor]];
    for(const [operation,owner]of owned){try{await bounded(Promise.resolve().then(()=>owner.close()),{deadline:Math.max(now()+.001,Math.min(now()+8,deadline))});}catch(error){failures.push({operation,outcome:outcome(error)});}}
    if(address){try{await listener(address,true);}catch(error){failures.push({operation:'listener_close',outcome:outcome(error)});}}
    if(failures.length)throw new RuntimeCleanupFailure(primary,failures);
  }
}
try{const value=await bounded(input(),{deadline:now()+5,signal:cancellation.signal});readingInput=false;process.stdout.write(JSON.stringify(await cases(value))+'\n');}
catch(error){process.stdout.write(JSON.stringify(error instanceof RuntimeCleanupFailure?{ok:false,step,error:'cleanup_failed',primary:error.primary,cleanup:error.failures}:{ok:false,step,error:outcome(error)})+'\n');process.exitCode=1;}
finally{process.removeListener('SIGTERM',cancel);process.removeListener('SIGINT',cancel);}
