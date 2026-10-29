/** Actual native security receipts and optional private settlement acceptance. */
import {execFile} from 'node:child_process';
import http from 'node:http';
import {createHash} from 'node:crypto';
import {isDeepStrictEqual as same} from 'node:util';
import {PoolResource,parse_pool_config,bounded,now} from '../packages/typescript/dist/postgres-pool.js';
import {PostgresQdrantWriter,prepare_stage,security_projection_data} from '../packages/typescript/dist/qdrant-writer.js';
import {ManagedQdrantSupervisor} from '../packages/typescript/dist/qdrant-supervisor.js';
import {PostgresQdrantRecovery,validate_security_guarded,settle_security_guarded,SECURITY_GUARD_SQL} from '../packages/typescript/dist/qdrant-recovery.js';
import {QdrantReconciliationVerifier} from '../packages/typescript/dist/qdrant-reconciliation.js';
import {QdrantSecurityVerifier,security_receipt_data} from '../packages/typescript/dist/qdrant-security-verification.js';
import {InvalidRequest,IntegrityViolation,UnsupportedCapability,UnauthorizedScope,ProviderUnavailable} from '../packages/typescript/dist/errors.js';

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
const GRAPH_CHECKS=Object.freeze(['actual_guard_nonlocking_full_graph','document_lock_wait_observed_until_guard_commit',
  'late_canonical_drift_refused','late_vector_drift_refused','late_manifest_drift_refused','extra_raw_claim_refused',
  'post_wait_authority_mismatch_refused','supervisor_connection_loss_releases_document_without_commit',
  'late_callback_retains_control_and_writer_until_drained']);
const SETTLEMENT_CHECKS=Object.freeze(['retired_unknown_settled_with_genuine_current_security_receipt',
  'lost_commit_confirmed_once_after_authority_advance_without_dml_retry',
  'fresh_repeat_preserves_historical_completion_and_returns_zero',
  'current_credential_unknown_preserves_rows_and_closed_admission']);
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
      ['binary','inputs','supervisor_config','work_dir','writer_config',
        ...(Object.hasOwn(value,'guard_operator_config')?['guard_operator_config']:[]),
        ...(Object.hasOwn(value,'guard_graph_config')?['guard_graph_config']:[]),
        ...(Object.hasOwn(value,'settlement_config')?['settlement_config']:[])].sort())
    ||typeof value.binary!=='string'||typeof value.work_dir!=='string'||!value.inputs?.second_stage||!value.inputs?.security||!value.inputs?.tombstone)throw new Error('input_shape');
  if(Object.hasOwn(value,'guard_graph_config')&&(!Object.hasOwn(value,'guard_operator_config')
    ||!value.guard_graph_config||!same(Object.keys(value.guard_graph_config),['admin_config'])))throw new Error('graph_input_shape');
  if(Object.hasOwn(value,'settlement_config')&&(!Object.hasOwn(value,'guard_operator_config')||Object.hasOwn(value,'guard_graph_config')
    ||!value.settlement_config||!same(Object.keys(value.settlement_config),['admin_config'])))throw new Error('settlement_input_shape');
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
  const graphMode=Object.hasOwn(value,'guard_graph_config');
  const settlementMode=Object.hasOwn(value,'settlement_config');
  let settlementDropArmed=false,settlementAfterCommit,commitDrops=0,confirmationActive=false,confirmationTransactions=0,
    confirmationWrites=0,confirmationWriterQueries=0,httpQueries=0,confirmationHttpStart=0,guardQueries=0,confirmationGuardStart=0;
  const nativeHttpRequest=http.request;
  let backendQueries=0,deniedBackendQueries=0,activeRestore;
  let supBefore,supAfter,writerAfter,contenderAfter,supPid,contenderPid,forbidCommit=false,deniedCommits=0,nonlockingReads=0,supFaultClosed=false;
  const documentQuery=query=>typeof query?.text==='string'&&query.text.startsWith('SELECT ')
    &&query.text.includes('FROM cragkit_qdrant.documents ');
  const ownedTasks=new Set(),gates=new Set();
  const factoryResource=guarded?new PoolResource(supervisorConfig):undefined;
  const defaultFactory=factoryResource?.factory;
  if(guarded&&typeof defaultFactory!=='function')throw new Error('native_factory_unavailable');
  const resource=new PoolResource(writerConfig,graphMode||settlementMode?{factory:async config=>{
    const actual=await defaultFactory(config);
    return {async connect(){const client=await actual.connect();
      return {async query(query){
        if(confirmationActive)confirmationWriterQueries++;
        if(documentQuery(query)&&!query.text.endsWith('FOR UPDATE'))nonlockingReads++;
        const result=await client.query(query);if(writerAfter)await writerAfter(query,result);return result;
      },
        getTransactionStatus(){return client.getTransactionStatus();},release(destroy){client.release(destroy);}};
    },end(){return actual.end();}};
  }}:{}),supervisorResource=new PoolResource(supervisorConfig,guarded?{factory:async config=>{
    const actual=await defaultFactory(config);
    return {async connect(){
      const client=await actual.connect();
      supPid=graphMode?(await client.query({text:'SELECT pg_backend_pid()',rowMode:'array'})).rows[0][0]:undefined;
      let guardedTransaction=false,settlementWritten=false;
      return {async query(query){
        if(typeof query?.text==='string'&&query.text.includes("set_config('cragkit_qdrant.backend_instance_id'"))backendQueries++;
        if(query.text.startsWith('BEGIN')){guardedTransaction=false;settlementWritten=false;}
        if(confirmationActive){
          if(query.text==='SET TRANSACTION READ ONLY')confirmationTransactions++;
          if(/^\s*(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE)\b/i.test(query.text))confirmationWrites++;
        }
        if(query.text===SECURITY_GUARD_SQL){guardQueries++;guardedTransaction=true;if(supBefore)await supBefore();}
        if(query.text.startsWith("UPDATE cragkit_qdrant.dispatch_journal SET state='settled'"))settlementWritten=true;
        if(query.text==='COMMIT'&&guardedTransaction&&forbidCommit)deniedCommits++;
        const result=await client.query(query);
        if(query.text===SECURITY_GUARD_SQL&&supAfter)await supAfter();
        if(settlementMode&&query.text==='COMMIT'&&settlementDropArmed&&settlementWritten){
          settlementDropArmed=false;commitDrops++;
          await settlementAfterCommit();
          confirmationHttpStart=httpQueries;confirmationGuardStart=guardQueries;confirmationActive=true;
          throw Object.assign(new Error('committed_reply_withheld'),{code:'08006'});
        }
        if(confirmationActive&&query.text==='COMMIT')confirmationActive=false;
        return result;
      },getTransactionStatus(){return client.getTransactionStatus();},release(destroy){client.release(destroy);}};
    },end(){return actual.end();}};
  }}:{});
  const operatorConfig=guarded?parse_pool_config(value.guard_operator_config):undefined;
  if(operatorConfig&&operatorConfig.max_size!==1)throw new Error('operator_client_ceiling');
  const operator=operatorConfig?new PoolResource(operatorConfig):undefined;
  const adminConfig=graphMode||settlementMode?parse_pool_config((graphMode?value.guard_graph_config:value.settlement_config).admin_config):undefined;
  if(adminConfig&&adminConfig.max_size!==1)throw new Error('admin_client_ceiling');
  const admin=adminConfig?new PoolResource(adminConfig):undefined;
  const contenderResource=graphMode?new PoolResource(writerConfig,{factory:async config=>{
    const actual=await defaultFactory(config);
    return {async connect(){const client=await actual.connect();contenderPid=(await client.query({text:'SELECT pg_backend_pid()',rowMode:'array'})).rows[0][0];
      return {async query(query){const result=await client.query(query);if(contenderAfter)await contenderAfter(query,result);return result;},
        getTransactionStatus(){return client.getTransactionStatus();},release(destroy){client.release(destroy);}};
    },end(){return actual.end();}};
  }}):undefined;
  const contender=contenderResource?new PostgresQdrantWriter(contenderResource,inputs.config,inputs.instance_id):undefined;
  const writer=new PostgresQdrantWriter(resource,inputs.config,inputs.instance_id);
  const supervisor=new ManagedQdrantSupervisor(value.binary,value.work_dir,inputs.instance_id,inputs.config);
  const reconciliation=new QdrantReconciliationVerifier(writer,supervisor);
  const recovery=new PostgresQdrantRecovery(supervisorResource,inputs.config,supervisor,reconciliation);
  const verifier=new QdrantSecurityVerifier(writer,supervisor),other=new QdrantSecurityVerifier(writer,supervisor);
  const target='/collections/'+inputs.config.physical_collection,checks=[],guardChecks=[],graphChecks=[],settlementChecks=[];
  const mark=()=>{checks.push(CHECKS[checks.length]);step=checks.length;};
  const base={collection:inputs.stage.manifest.collection,document_id:inputs.stage.manifest.document_id};
  const context=(scope,intent,owner)=>({...base,scope,intent_id:intent,owner_token:owner});
  const currentScope={...inputs.scope,authorization_revision:'auth-2'};
  const owner=context(currentScope,inputs.stage.intent.intent_id,OWNER),security=context(currentScope,inputs.security.intent_id,SECURITY);
  let address,primary,receipt,oldControl,oldProjection,semanticWitnessSha256,activeGraphRestore,restoringGraph=false;
  const docKeys=[inputs.scope.tenant_id,base.collection,base.document_id];
  const docWhere='tenant_id=$1 AND collection=$2 AND document_id=$3';
  const hash=value=>createHash('sha256').update(value).digest('hex');
  const sql=(pool,text,values=[],selected=options)=>pool.withLease(selected,client=>client.query({text,values,rowMode:'array'}));
  function gate(){
    let reached,open;const arrived=new Promise(resolve=>{reached=resolve;}),waiting=new Promise(resolve=>{open=resolve;});
    const release=()=>{open();gates.delete(release);};gates.add(release);
    return {arrived,reach:reached,wait:()=>bounded(waiting,options),release};
  }
  function owned(work){ownedTasks.add(work);void work.then(()=>ownedTasks.delete(work),()=>ownedTasks.delete(work));return work;}
  async function observe(pool,text,values){
    const end=Math.min(options.deadline,now()+4);
    while(now()<end){
      const result=await sql(pool,text,values);
      if(same(result.rows,[[true]]))return;
      await bounded(new Promise(resolve=>setTimeout(resolve,10)),options);
    }
    throw new Error('lock_observation_deadline');
  }
  const waitBlock="SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=$1 AND NOT granted AND locktype IN ('transactionid','tuple') AND $2=ANY(pg_blocking_pids(pid)))";
  async function replica(work){
    return admin.withLease({deadline:restoringGraph?now()+5:Math.min(options.deadline,now()+6)},async client=>{
      const run=(text,values=[])=>client.query({text,values,rowMode:'array'});
      await run('BEGIN');
      try{await run("SET LOCAL session_replication_role='replica'");const result=await work(run);await run('COMMIT');return result;}
      catch(error){await run('ROLLBACK');throw error;}
    });
  }
  async function restoreGraph(){
    restoringGraph=true;
    try{await activeGraphRestore();activeGraphRestore=undefined;}finally{restoringGraph=false;}
  }
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
  if(settlementMode)http.request=function(...args){httpQueries++;return nativeHttpRequest.apply(this,args);};
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
    if(settlementMode){
      const dispatch='native-security-retired-unknown';
      const attempt=supervisor.issue_attempt({intent_id:historical.intent_id,owner_token:OWNER,epoch:1,dispatch_id:dispatch},options);
      const binding=supervisor.attempt_binding(attempt);
      await writer.reserve_dispatch(historical,{dispatch_id:dispatch,sequence:1,credential_generation:binding.credential_generation,
        operation:'complete_point_upsert',point_ids:inputs.stage.manifest.members.map(member=>member.point_id)},options);
      await writer.mark_dispatched(historical,dispatch,options);await writer.mark_unknown(historical,dispatch,options);
    }
    await writer.apply_security(inputs.security,inputs.scope,{...options,owner_token:SECURITY});
    if(settlementMode&&(await writer.admit_publication(owner,options)).intent.state!=='denied')throw new Error('old_stage_not_denied');
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
      if(graphMode||settlementMode)await operator.close();
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
    if(graphMode){
      await admin.open();await contenderResource.open();await contender.initialize(options);
      await validate_security_guarded(recovery,verifier,proof,owner,security,options);graphChecks.push(GRAPH_CHECKS[0]);
      let lockTask;
      supAfter=async()=>{
        supAfter=undefined;
        let adminPid;
        const started=gate();
        lockTask=owned(admin.withLease(options,async client=>{
          const run=(text,values=[])=>client.query({text,values,rowMode:'array'});
          adminPid=(await run('SELECT pg_backend_pid()')).rows[0][0];await run('BEGIN');started.reach();
          try{await run('SELECT document_id FROM cragkit_qdrant.documents WHERE '+docWhere+' FOR UPDATE',docKeys);}
          finally{await run('ROLLBACK');}
        }));
        await bounded(started.arrived,options);started.release();
        await observe(resource,waitBlock,[adminPid,supPid]);
      };
      await validate_security_guarded(recovery,verifier,proof,owner,security,options);
      await bounded(lockTask,options);graphChecks.push(GRAPH_CHECKS[1]);
      for(const kind of ['canonical','vector','manifest','claim']){
        const before=deniedCommits;let injected=false;
        supAfter=async()=>{
          supAfter=undefined;injected=true;
          if(kind==='canonical'){
            const keys=[...docKeys,inputs.stage.manifest.revision_id];
            const saved=(await sql(admin,'SELECT canonical_utf8,source_sha256 FROM cragkit_qdrant.document_revisions WHERE '+docWhere+' AND revision_id=$4',keys)).rows[0];
            const changed=Buffer.from(saved[0]);changed[0]^=1;
            activeGraphRestore=()=>replica(run=>run('UPDATE cragkit_qdrant.document_revisions SET canonical_utf8=$5,source_sha256=$6 WHERE '+docWhere+' AND revision_id=$4',[...keys,saved[0],saved[1]]));
            await replica(run=>run('UPDATE cragkit_qdrant.document_revisions SET canonical_utf8=$5,source_sha256=$6 WHERE '+docWhere+' AND revision_id=$4',[...keys,changed,hash(changed)]));
          }else if(kind==='vector'){
            const id=inputs.stage.manifest.members[0].point_id;
            const saved=(await sql(admin,'SELECT dense_blob,dense_blob_sha256 FROM cragkit_qdrant.vector_replays WHERE point_id=$1',[id])).rows[0];
            const changed=Buffer.from(saved[0]);changed.writeDoubleLE(changed.readDoubleLE(changed.length-8)+.01,changed.length-8);
            activeGraphRestore=()=>replica(run=>run('UPDATE cragkit_qdrant.vector_replays SET dense_blob=$2,dense_blob_sha256=$3 WHERE point_id=$1',[id,saved[0],saved[1]]));
            await replica(run=>run('UPDATE cragkit_qdrant.vector_replays SET dense_blob=$2,dense_blob_sha256=$3 WHERE point_id=$1',[id,changed,hash(changed)]));
          }else if(kind==='manifest'){
            const keys=[...docKeys,inputs.stage.intent.intent_id];
            const saved=(await sql(admin,'SELECT manifest_bytes,manifest_sha256 FROM cragkit_qdrant.publication_intents WHERE '+docWhere+' AND intent_id=$4',keys)).rows[0];
            const changed=Buffer.concat([saved[0],Buffer.from(' ')]);
            activeGraphRestore=()=>replica(run=>run('UPDATE cragkit_qdrant.publication_intents SET manifest_bytes=$5,manifest_sha256=$6 WHERE '+docWhere+' AND intent_id=$4',[...keys,saved[0],saved[1]]));
            await replica(run=>run('UPDATE cragkit_qdrant.publication_intents SET manifest_bytes=$5,manifest_sha256=$6 WHERE '+docWhere+' AND intent_id=$4',[...keys,changed,hash(changed)]));
          }else{
            const extra='ffffffff-ffff-5fff-8fff-ffffffffffff',original=inputs.stage.manifest.members[0].point_id;
            activeGraphRestore=()=>replica(run=>run('DELETE FROM cragkit_qdrant.point_claims WHERE point_id=$1 AND '+
              'tenant_id=$2 AND collection=$3 AND document_id=$4',[extra,...docKeys]));
            await replica(run=>run('INSERT INTO cragkit_qdrant.point_claims SELECT (jsonb_populate_record(NULL::cragkit_qdrant.point_claims,'+
              "to_jsonb(p)||jsonb_build_object('point_id',$1::text,'chunk_id','guard-orphan-claim'))).* FROM cragkit_qdrant.point_claims p WHERE point_id=$2",[extra,original]));
          }
        };
        forbidCommit=true;
        try{await refuses(()=>validate_security_guarded(recovery,verifier,proof,owner,security,options),IntegrityViolation);}
        finally{forbidCommit=false;supAfter=undefined;if(activeGraphRestore)await restoreGraph();}
        if(!injected||deniedCommits!==before)throw new Error('late_graph_corruption_not_refused');
        graphChecks.push(GRAPH_CHECKS[graphChecks.length]);
      }
    }
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
    if(settlementMode){
      await admin.open();
      const auth3Scope={...currentScope,authorization_revision:'auth-3'},tombOwner={...owner,scope:auth3Scope},
        tombSecurity=context(auth3Scope,inputs.tombstone.intent_id,SECURITY);
      const next={...inputs.tombstone,intent_id:'native-security-settlement-auth-4',expected_authorization_revision:'auth-3',
        expected_mutation_epoch:3,authorization:{...inputs.tombstone.authorization,authorization_revision:'auth-4'}};
      settlementAfterCommit=async()=>{
        const result=await writer.apply_security(next,auth3Scope,{...options,owner_token:SECURITY});
        if(!result.authority_committed)throw new Error('post_commit_authority_missing');
      };
      settlementDropArmed=true;
      const result=await settle_security_guarded(recovery,verifier,proof,tombOwner,tombSecurity,options);
      const journalTarget=[...docKeys,owner.intent_id];
      const settledRows=(await sql(admin,'SELECT state,completion_sha256 FROM cragkit_qdrant.dispatch_journal WHERE '+docWhere+
        " AND intent_id=$4 AND dispatch_id='native-security-retired-unknown'",journalTarget)).rows;
      if(!same(result,{settled_count:1})||!Object.isFrozen(result)||settledRows.length!==1||settledRows[0][0]!=='settled'
        ||typeof settledRows[0][1]!=='string'||!/^[0-9a-f]{64}$/.test(settledRows[0][1]))throw new Error('retired_journal_not_settled');
      settlementChecks.push(SETTLEMENT_CHECKS[0]);
      if(commitDrops!==1||confirmationTransactions!==1||confirmationActive||confirmationWrites!==0||confirmationWriterQueries!==0
        ||guardQueries!==confirmationGuardStart||httpQueries!==confirmationHttpStart)throw new Error('settlement_confirmation_replayed_work');
      const authority=(await sql(admin,'SELECT authorization_revision,mutation_epoch FROM cragkit_qdrant.documents WHERE '+docWhere,docKeys)).rows;
      if(!same(authority,[['auth-4','4']])&&!same(authority,[['auth-4',4]]))throw new Error('confirmation_did_not_follow_authority_advance');
      settlementChecks.push(SETTLEMENT_CHECKS[1]);
      const auth4Scope={...auth3Scope,authorization_revision:'auth-4'},freshOwner={...owner,scope:auth4Scope},
        freshSecurity=context(auth4Scope,next.intent_id,SECURITY);
      const repeat=await settle_security_guarded(recovery,verifier,proof,freshOwner,freshSecurity,options);
      const repeatedRows=(await sql(admin,'SELECT state,completion_sha256 FROM cragkit_qdrant.dispatch_journal WHERE '+docWhere+
        " AND intent_id=$4 AND dispatch_id='native-security-retired-unknown'",journalTarget)).rows;
      if(!same(repeat,{settled_count:0})||!same(repeatedRows,settledRows))throw new Error('repeat_changed_historical_completion');
      settlementChecks.push(SETTLEMENT_CHECKS[2]);
      const binding=supervisor.recovery_binding(proof),dispatch='native-security-current-key-synthetic',request=Buffer.from(
        JSON.stringify({synthetic:'D4 current-credential uncertainty; no HTTP acknowledgment'}));
      await supervisorResource.withLease(options,async client=>{
        const run=(text,values=[])=>client.query({text,values,rowMode:'array'});
        await run('BEGIN ISOLATION LEVEL READ COMMITTED');
        try{
          await run('SET LOCAL search_path=pg_catalog');
          await run("SELECT set_config('cragkit_qdrant.backend_instance_id',$1,true)",[inputs.instance_id]);
          await run('INSERT INTO cragkit_qdrant.dispatch_journal (tenant_id,collection,document_id,intent_id,dispatch_id,instance_id,'+
            'sequence,owner_token,backend_epoch,credential_generation,operation,recovery,request_bytes,request_sha256) '+
            'VALUES($1,$2,$3,$4,$5,$6,$7,$8::uuid,$9,$10,$11,$12,$13,$14)',
            [...journalTarget,dispatch,inputs.instance_id,2,OWNER,2,binding.credential_generation,'complete_point_upsert',true,request,hash(request)]);
          for(const id of [...inputs.stage.manifest.members,...inputs.second_stage.manifest.members].map(member=>member.point_id).sort()){
            await run('INSERT INTO cragkit_qdrant.dispatch_points (tenant_id,collection,document_id,intent_id,dispatch_id,'+
              'backend_namespace,physical_collection,collection_incarnation,point_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::uuid)',
              [...journalTarget,dispatch,inputs.config.backend_namespace,inputs.config.physical_collection,inputs.config.collection_incarnation,id]);
          }
          await run("UPDATE cragkit_qdrant.dispatch_journal SET state='dispatched' WHERE "+docWhere+' AND intent_id=$4 AND dispatch_id=$5',
            [...journalTarget,dispatch]);
          await run("UPDATE cragkit_qdrant.dispatch_journal SET state='unknown' WHERE "+docWhere+' AND intent_id=$4 AND dispatch_id=$5',
            [...journalTarget,dispatch]);
          await run('COMMIT');
        }catch(error){await run('ROLLBACK');throw error;}
      });
      const snapshot=async()=>{
        const headers=await sql(admin,'SELECT dispatch_id,instance_id,sequence,owner_token::text,backend_epoch,credential_generation,'+
          'operation,recovery,request_sha256,created_xid::text,state,completion_sha256 FROM cragkit_qdrant.dispatch_journal WHERE '+
          docWhere+' AND intent_id=$4 ORDER BY sequence',journalTarget);
        const members=await sql(admin,'SELECT dispatch_id,backend_namespace,physical_collection,collection_incarnation,point_id::text '+
          'FROM cragkit_qdrant.dispatch_points WHERE '+docWhere+' AND intent_id=$4 ORDER BY dispatch_id,point_id',journalTarget);
        return [headers.rows,members.rows];
      };
      const before=await snapshot();
      await refuses(()=>settle_security_guarded(recovery,verifier,proof,freshOwner,freshSecurity,options),ProviderUnavailable);
      if(!same(await snapshot(),before))throw new Error('current_credential_settlement_changed_rows');
      await refuses(()=>recovery.reopen(proof,options),ProviderUnavailable);
      if(!same(await snapshot(),before)||(await sql(admin,'SELECT state FROM cragkit_qdrant.backend_instances WHERE instance_id=$1',
        [inputs.instance_id])).rows[0]?.[0]!=='recovery_blocked')throw new Error('current_credential_reopened_admission');
      settlementChecks.push(SETTLEMENT_CHECKS[3]);
    }
    if(graphMode){
      const auth3Scope={...currentScope,authorization_revision:'auth-3'};
      const tombOwner={...owner,scope:auth3Scope},tombSecurity=context(auth3Scope,inputs.tombstone.intent_id,SECURITY);
      const next={...inputs.tombstone,intent_id:'native-guard-contender-auth-4',expected_authorization_revision:'auth-3',
        expected_mutation_epoch:3,authorization:{...inputs.tombstone.authorization,authorization_revision:'auth-4'}};
      const contenderGate=gate(),submitted=gate();let authorityTask;
      contenderAfter=async query=>{
        if(documentQuery(query)&&query.text.endsWith('FOR UPDATE')){
          contenderAfter=undefined;contenderGate.reach();await contenderGate.wait();
        }
      };
      supBefore=async()=>{
        supBefore=undefined;
        authorityTask=owned(contender.apply_security(next,auth3Scope,{...options,owner_token:SECURITY}));
        await bounded(contenderGate.arrived,options);submitted.reach();
      };
      forbidCommit=true;
      const beforeGraph=nonlockingReads,beforeCommit=deniedCommits;
      const waiting=owned(validate_security_guarded(recovery,verifier,proof,tombOwner,tombSecurity,options));
      try{
        await bounded(submitted.arrived,options);submitted.release();
        await observe(admin,waitBlock,[supPid,contenderPid]);
        contenderGate.release();const authority=await bounded(authorityTask,options);
        if(!authority.authority_committed)throw new Error('contender_authority_missing');
        await refuses(()=>waiting,UnauthorizedScope);
        if(nonlockingReads!==beforeGraph||deniedCommits!==beforeCommit)throw new Error('post_wait_guard_reached_graph_or_commit');
      }finally{contenderGate.release();submitted.release();supBefore=undefined;contenderAfter=undefined;forbidCommit=false;}
      graphChecks.push(GRAPH_CHECKS[6]);

      const auth4Scope={...auth3Scope,authorization_revision:'auth-4'},lossOwner={...owner,scope:auth4Scope},
        lossSecurity=context(auth4Scope,next.intent_id,SECURITY);
      const callbackGate=gate(),lossController=new AbortController();let lateSuccess=false;
      writerAfter=async query=>{
        if(documentQuery(query)&&!query.text.endsWith('FOR UPDATE')){
          writerAfter=undefined;callbackGate.reach();await callbackGate.wait();
        }
      };
      const originalWriterLease=resource.withLease.bind(resource);
      // ponytail: reuse the native pool; hold this fault case's callback behind its gate without relaying the caller signal.
      resource.withLease=(selected,body)=>originalWriterLease({deadline:selected.deadline},body);
      let lostPid;const beforeLossCommit=deniedCommits;
      forbidCommit=true;
      const lossOptions={deadline:Math.min(options.deadline,now()+15),signal:AbortSignal.any([cancellation.signal,lossController.signal])};
      const loss=owned(validate_security_guarded(recovery,verifier,proof,lossOwner,lossSecurity,lossOptions).then(()=>{lateSuccess=true;}));
      try{
        await bounded(callbackGate.arrived,options);
        lostPid=supPid;
        try{await supervisorResource.close();}catch(error){if(!(error instanceof ProviderUnavailable))throw error;}
        await observe(admin,'SELECT NOT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=$1)',[lostPid]);
        const last={...next,intent_id:'native-guard-contender-auth-5',expected_authorization_revision:'auth-4',
          expected_mutation_epoch:4,authorization:{...next.authorization,authorization_revision:'auth-5'}};
        const changed=await contender.apply_security(last,auth4Scope,{...options,owner_token:SECURITY});
        if(!changed.authority_committed||deniedCommits!==beforeLossCommit)throw new Error('lost_supervisor_kept_document_or_committed');
        const state=await sql(admin,'SELECT authorization_revision,mutation_epoch FROM cragkit_qdrant.documents WHERE '+docWhere,docKeys);
        if(!same(state.rows,[['auth-5','5']])&&!same(state.rows,[['auth-5',5]]))throw new Error('lost_supervisor_authority_not_durable');
        graphChecks.push(GRAPH_CHECKS[7]);
        lossController.abort();
        await refuses(()=>bounded(loss,{deadline:Math.min(options.deadline,now()+5)}),ProviderUnavailable,DOMException);
        await refuses(()=>writer.project_security(lossSecurity,options),ProviderUnavailable);
        await refuses(()=>supervisor.control_session(async()=>{}),ProviderUnavailable);
        callbackGate.release();
        await bounded(Promise.allSettled([...ownedTasks]),{deadline:Math.min(options.deadline,now()+5)});
        await observe(admin,'SELECT NOT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=$1)',[lostPid]);
        if(lateSuccess||deniedCommits!==beforeLossCommit)throw new Error('late_graph_committed_or_succeeded');
        // Actual callback drainage, rather than an elapsed wait, must free control custody.
        let released=false;const drainDeadline=Math.min(options.deadline,now()+4);
        while(now()<drainDeadline&&!released){
          try{await supervisor.control_session(async()=>{released=true;});}
          catch(error){if(!(error instanceof ProviderUnavailable))throw error;await new Promise(resolve=>setTimeout(resolve,10));}
        }
        if(!released)throw new Error('late_callback_not_drained');
        if(supervisorResource.state!=='closed'||supervisorResource.work.size||supervisorResource.connecting.size)throw new Error('fault_close_not_drained');
        await bounded(supervisorResource.driverEnded.get(supervisorResource.pool),options);supFaultClosed=true;
        graphChecks.push(GRAPH_CHECKS[8]);
      }finally{lossController.abort();callbackGate.release();writerAfter=undefined;forbidCommit=false;resource.withLease=originalWriterLease;}
    }
    return {runtime:'typescript',checks,proof_scope:'native_security_receipt_only',semantic_witness_sha256:semanticWitnessSha256,
      ...(guarded?{guard_admission:{checks:guardChecks,denied_backend_queries:deniedBackendQueries}}:{}),
      ...(graphMode?{guarded_graph:{checks:graphChecks,denied_commits:deniedCommits}}:{}),
      ...(settlementMode?{security_settlement:{checks:settlementChecks,confirmation_writes:confirmationWrites}}:{})};
  }catch(error){primary=error;throw error;}
  finally{
    if(settlementMode)http.request=nativeHttpRequest;
    const failures=[],deadline=now()+12;
    for(const release of gates)release();
    supBefore=supAfter=writerAfter=contenderAfter=undefined;
    if(ownedTasks.size){
      try{await bounded(Promise.allSettled([...ownedTasks]),{deadline:Math.max(now()+.001,Math.min(now()+4,deadline))});}
      catch(error){failures.push({operation:'guard_graph_drain',outcome:outcome(error)});}
    }
    if(activeGraphRestore){
      try{await bounded(restoreGraph(),{deadline:Math.max(now()+.001,Math.min(now()+5,deadline))});}
      catch(error){failures.push({operation:'guard_graph_restore',outcome:outcome(error)});}
    }
    if(activeRestore){
      try{await bounded(Promise.resolve().then(activeRestore),{deadline:Math.max(now()+.001,Math.min(now()+5,deadline))});}
      catch(error){failures.push({operation:'catalog_restore',outcome:outcome(error)});}
    }
    for(const [operation,owned]of [['verifier_close',verifier],['wrong_verifier_close',other],['reconciliation_close',reconciliation],
      ['recovery_close',recovery],['writer_close',writer],['resource_close',resource],['supervisor_resource_close',supervisorResource],
      ...(contender?[['contender_writer_close',contender]]:[]),...(contenderResource?[['contender_pool_close',contenderResource]]:[]),
      ...(admin?[['admin_pool_close',admin]]:[]),
      ...(operator?[['operator_pool_close',operator]]:[]),...(factoryResource?[['factory_pool_close',factoryResource]]:[]),['controller_close',supervisor]]){
      if(operation==='supervisor_resource_close'&&supFaultClosed&&supervisorResource.state==='closed'&&!supervisorResource.work.size&&!supervisorResource.connecting.size)continue;
      try{await bounded(Promise.resolve().then(()=>owned.close()),{deadline:Math.max(now()+.001,Math.min(now()+8,deadline))});}catch(error){failures.push({operation,outcome:outcome(error)});}
    }
    if(address){try{await listener(address,true);}catch(error){failures.push({operation:'listener_close',outcome:outcome(error)});}}
    if(failures.length)throw new RuntimeCleanupFailure(primary,failures);
  }
}
try{const value=await bounded(input(),{deadline:now()+5,signal:cancellation.signal});readingInput=false;process.stdout.write(JSON.stringify(await cases(value))+'\n');}
catch(error){process.stdout.write(JSON.stringify(error instanceof RuntimeCleanupFailure?{ok:false,step,error:'cleanup_failed',primary:error.primary,cleanup:error.failures}:{ok:false,step,error:outcome(error)})+'\n');process.exitCode=1;}
finally{process.removeListener('SIGTERM',cancel);process.removeListener('SIGINT',cancel);}
