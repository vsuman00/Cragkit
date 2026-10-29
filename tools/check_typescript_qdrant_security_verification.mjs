/** Actual security receipts on disposable native servers; no settlement proof. */
import {execFile} from 'node:child_process';
import {createHash} from 'node:crypto';
import {isDeepStrictEqual as same} from 'node:util';
import {PoolResource,parse_pool_config,bounded,now} from '../packages/typescript/dist/postgres-pool.js';
import {PostgresQdrantWriter,prepare_stage,security_projection_data} from '../packages/typescript/dist/qdrant-writer.js';
import {ManagedQdrantSupervisor} from '../packages/typescript/dist/qdrant-supervisor.js';
import {PostgresQdrantRecovery} from '../packages/typescript/dist/qdrant-recovery.js';
import {QdrantReconciliationVerifier} from '../packages/typescript/dist/qdrant-reconciliation.js';
import {QdrantSecurityVerifier,security_receipt_data} from '../packages/typescript/dist/qdrant-security-verification.js';
import {InvalidRequest,IntegrityViolation,UnsupportedCapability,UnauthorizedScope} from '../packages/typescript/dist/errors.js';

const CHECKS=Object.freeze([
  'actual_current_authority_two_generations_binds_historical_owner',
  'missing_or_stale_replicas_cannot_mint_security_receipt',
  'exact_current_readback_mints_same_session_receipt',
  'copied_wrong_issuer_and_wrong_facade_receipts_rejected',
  'subsequent_session_attempt_or_http_invalidates_receipt',
  'session_exit_expires_receipt_and_new_session_requires_fresh_readback',
  'superseding_source_authority_invalidates_receipt_projection',
  'tombstone_receipt_requires_exact_scoped_absence',
]);
const GUARD_CHECKS=Object.freeze([
  'guard_source_grant_refused_before_backend_binding',
  'guard_login_refused_before_backend_binding',
  'fifth_history_refused_before_backend_binding',
  'extra_definer_refused_before_backend_binding',
]);
const ERRORS=new Set(['IntegrityViolation','InvalidRequest','ProviderUnavailable','UnauthorizedScope','UnsupportedCapability','DeadlineExceeded','IndexNotReady','AbortError']);
const OWNER='00000000-0000-4000-8000-000000000001',SECURITY='00000000-0000-4000-8000-000000000002';
const cancellation=new AbortController();let readingInput=true,step=0;
const cancel=()=>{cancellation.abort();if(readingInput)process.stdin.destroy();};
process.on('SIGTERM',cancel);process.on('SIGINT',cancel);
const bytes=value=>[...Buffer.from(JSON.stringify(value),'utf8')];
const decode=value=>JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.from(value)));
function outcome(error){try{return ERRORS.has(error?.name)?error.name:'internal';}catch{return 'internal';}}
class RuntimeCleanupFailure extends Error{constructor(primary,failures){super('runtime_cleanup_failed');this.primary=primary?outcome(primary):null;this.failures=failures;}}
async function input(){
  const chunks=[];let size=0;
  for await(const chunk of process.stdin){size+=chunk.length;if(size>1048576)throw new Error('bounded_input');chunks.push(chunk);}
  const value=decode(Buffer.concat(chunks));
  if(!value||typeof value!=='object'||Array.isArray(value)||!same(Object.keys(value).sort(),
      (Object.hasOwn(value,'guard_operator_config')?['binary','guard_operator_config','inputs','supervisor_config','work_dir','writer_config']:
        ['binary','inputs','supervisor_config','work_dir','writer_config']))
    ||typeof value.binary!=='string'||typeof value.work_dir!=='string'||!value.inputs?.second_stage||!value.inputs?.security||!value.inputs?.tombstone)throw new Error('input_shape');
  return value;
}
async function listener(address,absent=false){
  const url=new URL(address);
  if(url.protocol!=='http:'||url.hostname!=='127.0.0.1'||!url.port||url.origin!==address||url.username||url.password)throw new Error('endpoint_shape');
  return new Promise((resolve,reject)=>execFile('/usr/sbin/lsof',['-nP','-a','-iTCP@127.0.0.1:'+url.port,'-sTCP:LISTEN','-t'],
    {encoding:'utf8',env:{PATH:'/usr/bin:/bin'},maxBuffer:1024,timeout:3000,killSignal:'SIGKILL'},(error,stdout,stderr)=>{
      if(absent&&error?.code===1&&stdout===''&&stderr==='')return resolve(null);
      if(error||stderr||absent||!/^[1-9][0-9]{0,9}\n?$/.test(stdout))return reject(new Error('listener_observation'));
      const pid=Number(stdout.trim());if(!Number.isSafeInteger(pid)||pid>2147483647)return reject(new Error('listener_observation'));resolve(pid);
    }));
}
async function refuses(operation,...classes){try{await operation();}catch(error){if(classes.some(Type=>error instanceof Type))return;throw error;}throw new Error('expected_refusal_missing');}
function completed(raw){const body=decode(raw);if(body?.status!=='ok'||body?.result?.status!=='completed')throw new Error('ack_not_completed');}
async function cases(value){
  const {inputs}=value,writerConfig=parse_pool_config(value.writer_config),supervisorConfig=parse_pool_config(value.supervisor_config);
  if(writerConfig.max_size!==1||supervisorConfig.max_size!==1)throw new Error('two_client_ceiling');
  const options={deadline:now()+120,signal:cancellation.signal};
  const guarded=Object.hasOwn(value,'guard_operator_config');
  let backendQueries=0,deniedBackendQueries=0,activeRestore;
  const factoryResource=guarded?new PoolResource(supervisorConfig):undefined;
  const defaultFactory=factoryResource?.factory;
  if(guarded&&typeof defaultFactory!=='function')throw new Error('native_factory_unavailable');
  const resource=new PoolResource(writerConfig),supervisorResource=new PoolResource(supervisorConfig,guarded?{factory:async config=>{
    const actual=await defaultFactory(config);
    return {async connect(){
      const client=await actual.connect();
      return {query(query){
        if(typeof query?.text==='string'&&query.text.includes("set_config('cragkit_qdrant.backend_instance_id'"))backendQueries++;
        return client.query(query);
      },getTransactionStatus(){return client.getTransactionStatus();},release(destroy){client.release(destroy);}};
    },end(){return actual.end();}};
  }}:{});
  const operatorConfig=guarded?parse_pool_config(value.guard_operator_config):undefined;
  if(operatorConfig&&operatorConfig.max_size!==1)throw new Error('operator_client_ceiling');
  const operator=operatorConfig?new PoolResource(operatorConfig):undefined;
  const writer=new PostgresQdrantWriter(resource,inputs.config,inputs.instance_id);
  const supervisor=new ManagedQdrantSupervisor(value.binary,value.work_dir,inputs.instance_id,inputs.config);
  const reconciliation=new QdrantReconciliationVerifier(writer,supervisor);
  const recovery=new PostgresQdrantRecovery(supervisorResource,inputs.config,supervisor,reconciliation);
  const verifier=new QdrantSecurityVerifier(writer,supervisor),other=new QdrantSecurityVerifier(writer,supervisor);
  const target='/collections/'+inputs.config.physical_collection,checks=[],guardChecks=[];
  const mark=()=>{checks.push(CHECKS[checks.length]);step=checks.length;};
  const base={collection:inputs.stage.manifest.collection,document_id:inputs.stage.manifest.document_id};
  const context=(scope,intent,owner)=>({...base,scope,intent_id:intent,owner_token:owner});
  const currentScope={...inputs.scope,authorization_revision:'auth-2'};
  const owner=context(currentScope,inputs.stage.intent.intent_id,OWNER),security=context(currentScope,inputs.security.intent_id,SECURITY);
  let address,primary,receipt,oldControl,oldProjection,semanticWitnessSha256;
  function receiptData(control){return security_receipt_data(receipt,verifier,control,options);}
  function actualPoints(source){return source.points.map(point=>({id:point.point_id,payload:point.payload,
    vector:{dense:point.dense.values,sparse:{indices:point.sparse.indices,values:point.sparse.values}}}));}
  function assertReceipt(control){
    const data=receiptData(control),source=security_projection_data(data.projection,writer);
    if(!same(Object.keys(data).sort(),['projection','owner_context','security_context','physical_binding','attempt_binding','activity','intent_sha256','inventory_sha256','point_ids','readback_sha256','witness','encoded_bytes','sha256'].sort())
      ||!same(data.owner_context,owner)||!same(data.security_context,security)||data.point_ids.length!==4
      ||data.attempt_binding.intent_id!==owner.intent_id||data.attempt_binding.owner_token!==OWNER
      ||source.generations.length!==2||source.authorization_revision!=='auth-2'||!Object.isFrozen(data)||!Object.isFrozen(data.witness)
      ||!same(bytes(data.witness),data.encoded_bytes)||data.witness[0]!=='cragkit.qdrant.security-readback.v1'
      ||data.sha256!==createHash('sha256').update(Buffer.from(data.encoded_bytes)).digest('hex')||data.readback_sha256!==data.sha256)throw new Error('receipt_binding');
    oldProjection=data.projection;semanticWitnessSha256=createHash('sha256').update(Buffer.from(JSON.stringify([data.witness[0],...data.witness.slice(4)]))).digest('hex');return data;
  }
  try{
    await supervisor.initialize({...options,provision:async(admin,probe)=>{
      await admin.request('PUT',target,{...options,body:bytes(inputs.collection_config)});
      await admin.request('PUT','/collections/'+probe.collection,{...options,body:bytes(probe.collection_config)});
      completed(await admin.request('PUT','/collections/'+probe.collection+'/points?wait=true&ordering=strong',{...options,body:bytes({points:[probe.point]})}));
    }});
    address=supervisor.identity().endpoint;await listener(address);
    await resource.open();await supervisorResource.open();await writer.initialize(options);await recovery.initialize(options);
    await writer.stage(prepare_stage(inputs.stage),inputs.scope,{...options,owner_token:OWNER});
    await writer.stage(prepare_stage(inputs.second_stage),inputs.scope,{...options,owner_token:OWNER});
    const historical=context(inputs.scope,inputs.stage.intent.intent_id,OWNER);
    const admitted=await writer.admit_publication(historical,options);
    if(admitted.owner?.owner_token!==OWNER)throw new Error('historical_owner_missing');
    await writer.apply_security(inputs.security,inputs.scope,{...options,owner_token:SECURITY});
    const projected=await writer.project_security(security,options),source=security_projection_data(projected,writer);
    const state=await writer.manager_snapshot(owner,options);
    if(source.point_ids.length!==4||source.generations.length!==2||source.authorization_revision!=='auth-2'
      ||source.points.some(point=>point.payload.authorization_revision!=='auth-2')||state.owner?.owner_token!==OWNER||state.owner?.intent_id!==owner.intent_id)throw new Error('current_projection');
    mark();
    const proof=await recovery.recover('security-receipt-native',options);
    if(guarded){
      await operator.open();
      const execute=(text,values=[],selected=options)=>operator.withLease(selected,client=>client.query({text,values,rowMode:'array'}));
      async function mutation(apply,restore,applyValues=[],restoreValues=[]){
        await execute(apply,applyValues);
        activeRestore=()=>execute(restore,restoreValues,{deadline:now()+5});
        let failure;
        try{
          const before=backendQueries;
          await refuses(()=>recovery.advance_owner(proof,owner,options),UnsupportedCapability);
          deniedBackendQueries+=backendQueries-before;
          if(backendQueries!==before)throw new Error('guard_fault_reached_backend_binding');
        }catch(error){failure=error;}
        try{await activeRestore();}
        catch(error){throw new RuntimeCleanupFailure(failure,[{operation:'catalog_restore',outcome:outcome(error)}]);}
        activeRestore=undefined;
        if(failure)throw failure;
        const before=backendQueries,advanced=await recovery.advance_owner(proof,owner,options);
        if(!same(advanced,{owner_token:OWNER,backend_epoch:2})||backendQueries!==before+1)throw new Error('guard_owner_restoration');
        guardChecks.push(GUARD_CHECKS[guardChecks.length]);
      }
      await mutation('GRANT SELECT(canonical_utf8) ON cragkit_qdrant.document_revisions TO cragkit_qdrant_security_guard',
        'REVOKE SELECT(canonical_utf8) ON cragkit_qdrant.document_revisions FROM cragkit_qdrant_security_guard');
      await mutation('ALTER ROLE cragkit_qdrant_security_guard LOGIN','ALTER ROLE cragkit_qdrant_security_guard NOLOGIN');
      await mutation('INSERT INTO cragkit_qdrant.schema_migrations(version,checksum_sha256) VALUES($1,$2)',
        'DELETE FROM cragkit_qdrant.schema_migrations WHERE version=$1 AND checksum_sha256=$2',
        ['9999_native_guard_recovery_probe','0'.repeat(64)],['9999_native_guard_recovery_probe','0'.repeat(64)]);
      await mutation("CREATE FUNCTION cragkit_qdrant.native_guard_recovery_probe() RETURNS boolean LANGUAGE SQL SECURITY DEFINER AS 'SELECT true'",
        'DROP FUNCTION cragkit_qdrant.native_guard_recovery_probe()');
    }
    await supervisor.control_session(async control=>{
      oldControl=control;
      const attempt=control.issue_recovery_attempt(proof,{intent_id:owner.intent_id,owner_token:OWNER,epoch:2,
        dispatch_id:'security-native-mutation',recovery_id:'security-receipt-native'},options);
      const mutation=control.recovery_transport_for(attempt);
      async function put(points){completed(await mutation.request('PUT',target+'/points?wait=true&ordering=strong',{...options,body:bytes({points})}));}
      await refuses(()=>verifier.verify(proof,control,owner,security,options),IntegrityViolation);
      const stale=actualPoints(source).map(point=>({...point,payload:{...point.payload,authorization_revision:'auth-1'}}));
      await put(stale);await refuses(()=>verifier.verify(proof,control,owner,security,options),IntegrityViolation);mark();
      await put(actualPoints(source));receipt=await verifier.verify(proof,control,owner,security,options);assertReceipt(control);mark();
      await refuses(()=>security_receipt_data({...receipt},verifier,control,options),InvalidRequest);
      await refuses(()=>security_receipt_data(receipt,other,control,options),InvalidRequest);
      await refuses(()=>security_receipt_data(receipt,verifier,{},options),InvalidRequest);mark();
      await mutation.request('POST',target+'/points',{...options,body:bytes({ids:[source.point_ids[0]],with_payload:true,with_vector:true})});
      await refuses(()=>receiptData(control),UnsupportedCapability);
      receipt=await verifier.verify(proof,control,owner,security,options);
      control.issue_recovery_attempt(proof,{intent_id:owner.intent_id,owner_token:OWNER,epoch:2,
        dispatch_id:'security-native-intervening',recovery_id:'security-receipt-native'},options);
      await refuses(()=>receiptData(control),UnsupportedCapability);mark();
      receipt=await verifier.verify(proof,control,owner,security,options);assertReceipt(control);
      await mutation.close();
    });
    await refuses(()=>receiptData(oldControl),InvalidRequest);
    await supervisor.control_session(async control=>{
      await refuses(()=>receiptData(control),InvalidRequest);
      receipt=await verifier.verify(proof,control,owner,security,options);assertReceipt(control);mark();
      await writer.apply_security(inputs.tombstone,currentScope,{...options,owner_token:SECURITY});
      await refuses(()=>writer.validate_security_projection(oldProjection,options),UnauthorizedScope);mark();
      const tombScope={...currentScope,authorization_revision:'auth-3'},tombOwner={...owner,scope:tombScope},
        tombSecurity=context(tombScope,inputs.tombstone.intent_id,SECURITY);
      await refuses(()=>verifier.verify(proof,control,tombOwner,tombSecurity,options),IntegrityViolation);
      const tombProjection=await writer.project_security(tombSecurity,options),tombSource=security_projection_data(tombProjection,writer);
      const attempt=control.issue_recovery_attempt(proof,{intent_id:owner.intent_id,owner_token:OWNER,epoch:2,
        dispatch_id:'security-native-delete',recovery_id:'security-receipt-native'},options);
      const mutation=control.recovery_transport_for(attempt);
      completed(await mutation.request('POST',target+'/points/delete?wait=true&ordering=strong',{...options,body:bytes({points:tombSource.point_ids})}));
      await mutation.close();
      const tombReceipt=await verifier.verify(proof,control,tombOwner,tombSecurity,options);
      const tombData=security_receipt_data(tombReceipt,verifier,control,options);
      if(!security_projection_data(tombData.projection,writer).tombstoned||tombData.point_ids.length!==4)throw new Error('tombstone_receipt');mark();
    });
    return {runtime:'typescript',checks,proof_scope:'native_security_receipt_only',semantic_witness_sha256:semanticWitnessSha256,
      ...(guarded?{guard_admission:{checks:guardChecks,denied_backend_queries:deniedBackendQueries}}:{})};
  }catch(error){primary=error;throw error;}
  finally{
    const failures=[],deadline=now()+12;
    if(activeRestore){
      try{await bounded(Promise.resolve().then(activeRestore),{deadline:Math.max(now()+.001,Math.min(now()+5,deadline))});}
      catch(error){failures.push({operation:'catalog_restore',outcome:outcome(error)});}
    }
    for(const [operation,owned]of [['verifier_close',verifier],['wrong_verifier_close',other],['reconciliation_close',reconciliation],
      ['recovery_close',recovery],['writer_close',writer],['resource_close',resource],['supervisor_resource_close',supervisorResource],
      ...(operator?[['operator_pool_close',operator]]:[]),...(factoryResource?[['factory_pool_close',factoryResource]]:[]),['controller_close',supervisor]]){
      try{await bounded(Promise.resolve().then(()=>owned.close()),{deadline:Math.max(now()+.001,Math.min(now()+8,deadline))});}catch(error){failures.push({operation,outcome:outcome(error)});}
    }
    if(address){try{await listener(address,true);}catch(error){failures.push({operation:'listener_close',outcome:outcome(error)});}}
    if(failures.length)throw new RuntimeCleanupFailure(primary,failures);
  }
}
try{const value=await bounded(input(),{deadline:now()+5,signal:cancellation.signal});readingInput=false;process.stdout.write(JSON.stringify(await cases(value))+'\n');}
catch(error){process.stdout.write(JSON.stringify(error instanceof RuntimeCleanupFailure?{ok:false,step,error:'cleanup_failed',primary:error.primary,cleanup:error.failures}:{ok:false,step,error:outcome(error)})+'\n');process.exitCode=1;}
finally{process.removeListener('SIGTERM',cancel);process.removeListener('SIGINT',cancel);}
