/** Actual full-document security diagnostics; no SQL or settlement proof. */
import {execFile} from 'node:child_process';
import {isDeepStrictEqual as same} from 'node:util';
import {ManagedQdrantSupervisor} from '../packages/typescript/dist/qdrant-supervisor.js';
import {now,bounded} from '../packages/typescript/dist/postgres-pool.js';
import {IntegrityViolation} from '../packages/typescript/dist/errors.js';
import {QdrantPayloadSchema} from '../packages/typescript/dist/qdrant-contract.js';
import {encode_dense,encode_sparse} from '../packages/typescript/dist/qdrant-vectors.js';
import {SecurityReadbackBudget,inspect_security_readback,verify_security_readback} from '../packages/typescript/dist/qdrant-security-readback.js';

const CHECKS=Object.freeze([
  'multiple_generations_report_missing_and_stale_mutable_fields',
  'strict_current_readback_requires_every_current_member',
  'immutable_dense_sparse_and_payload_corruption_rejected',
  'unexpected_generation_visible_in_full_document_scope',
  'get_scroll_membership_and_mutable_payload_drift_rejected',
  'tombstone_requires_exact_ids_absent_and_full_document_empty',
  'empty_inventory_still_enumerates_explicit_scope',
  'shared_actual_response_bytes_and_request_calls_across_passes',
]);
const ERRORS=new Set(['InvalidRequest','ProviderUnavailable','UnsupportedCapability','DeadlineExceeded',
  'IndexNotReady','IntegrityViolation','UnauthorizedScope','CancelledError','AbortError']);
const cancellation=new AbortController();
let readingInput=true,step=0;
const cancel=()=>{cancellation.abort();if(readingInput)process.stdin.destroy();};
process.on('SIGTERM',cancel);process.on('SIGINT',cancel);
const bytes=value=>[...Buffer.from(JSON.stringify(value),'utf8')];
const decode=value=>JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.from(value)));
const clone=value=>JSON.parse(JSON.stringify(value));
function outcome(error){try{return ERRORS.has(error?.name)?error.name:'internal';}catch{return 'internal';}}
class RuntimeCleanupFailure extends Error{
  constructor(primary,failures){super('runtime_cleanup_failed');this.primary=primary?outcome(primary):null;this.failures=failures;}
}
async function input(){
  const chunks=[];let size=0;
  for await(const chunk of process.stdin){size+=chunk.length;if(size>262144)throw new Error('bounded_input');chunks.push(chunk);}
  const value=decode(Buffer.concat(chunks));
  if(!value||typeof value!=='object'||Array.isArray(value)||!same(Object.keys(value).sort(),['binary','inputs','work_dir'])
    ||typeof value.binary!=='string'||typeof value.work_dir!=='string'||!value.inputs||typeof value.inputs!=='object'
    ||Array.isArray(value.inputs)||!Array.isArray(value.inputs.points)||value.inputs.points.length!==4)throw new Error('input_shape');
  return value;
}
async function denied(operation){
  try{await operation();}catch(error){if(error instanceof IntegrityViolation)return;throw error;}
  throw new Error('expected_refusal_missing');
}
function completed(raw){const value=decode(raw);if(value?.status!=='ok'||value?.result?.status!=='completed')throw new Error('write_not_completed');}
async function observedListener(address,absent=false){
  const parsed=new URL(address);
  if(parsed.protocol!=='http:'||parsed.hostname!=='127.0.0.1'||!parsed.port||parsed.username||parsed.password||parsed.origin!==address)throw new Error('endpoint_shape');
  return new Promise((resolve,reject)=>execFile('/usr/sbin/lsof',
    ['-nP','-a','-iTCP@127.0.0.1:'+parsed.port,'-sTCP:LISTEN','-t'],
    {encoding:'utf8',env:{PATH:'/usr/bin:/bin'},maxBuffer:1024,timeout:3000,killSignal:'SIGKILL'},
    (error,stdout,stderr)=>{
      if(absent&&error?.code===1&&stdout===''&&stderr==='')return resolve(null);
      if(error||stderr||absent||!/^[1-9][0-9]{0,9}\n?$/.test(stdout))return reject(new Error('listener_observation'));
      const pid=Number(stdout.trim());if(!Number.isSafeInteger(pid)||pid>2147483647)return reject(new Error('listener_observation'));resolve(pid);
    }));
}
async function cases(value){
  const {inputs}=value,options={deadline:now()+100,signal:cancellation.signal};
  const supervisor=new ManagedQdrantSupervisor(value.binary,value.work_dir,inputs.instance_id,inputs.config);
  const points=Object.freeze(inputs.points.map(point=>Object.freeze({point_id:point.id,payload:QdrantPayloadSchema.parse(point.payload),
    dense:encode_dense(point.vector.dense,inputs.config.dense_profile),
    sparse:encode_sparse(point.vector.sparse.indices,point.vector.sparse.values,inputs.config.sparse_profile)})));
  const data={context:inputs.context,points,point_ids:points.map(point=>point.point_id),tombstoned:false};
  const target='/collections/'+inputs.config.physical_collection,checks=[];
  const mark=()=>{checks.push(CHECKS[checks.length]);step=checks.length;};
  let address,primary;
  try{
    await supervisor.initialize({...options,provision:async(admin,probe)=>{
      await admin.request('PUT',target,{...options,body:bytes(inputs.collection_config)});
      await admin.request('PUT','/collections/'+probe.collection,{...options,body:bytes(probe.collection_config)});
      completed(await admin.request('PUT','/collections/'+probe.collection+'/points?wait=true&ordering=strong',
        {...options,body:bytes({points:[probe.point]})}));
    }});
    address=supervisor.identity().endpoint;await observedListener(address);supervisor.block_ordinary();
    const proof=await supervisor.recover({recovery_id:'native-security-readback',old_epoch:1,new_epoch:2},options);
    await supervisor.control_session(async control=>{
      const attempt=control.issue_recovery_attempt(proof,{intent_id:'native-security-readback',owner_token:inputs.context.owner_token,
        epoch:2,dispatch_id:'native-security-readback-attempt',recovery_id:'native-security-readback'},options);
      const read=control.recovery_transport_for(attempt),mutation=control.recovery_transport_for(attempt);
      async function put(selected){completed(await mutation.request('PUT',target+'/points?wait=true&ordering=strong',{...options,body:bytes({points:selected})}));}
      async function remove(ids){completed(await mutation.request('POST',target+'/points/delete?wait=true&ordering=strong',{...options,body:bytes({points:ids})}));}
      const inspect=(handle=read,selected=data,budget)=>inspect_security_readback(handle,inputs.config,selected,options,budget);
      const verify=(handle=read,selected=data,budget)=>verify_security_readback(handle,inputs.config,selected,options,budget);
      const partial=clone(inputs.points.slice(0,-1));
      Object.assign(partial[0].payload,{authorization_revision:'auth-1',principal_ids:['old-reader'],grant_ids:['old-grant'],language:'en'});
      await put(partial);
      const observed=await inspect();
      if(!same(observed,{present_ids:partial.map(point=>point.id),missing_ids:[inputs.points.at(-1).id],stale_ids:[partial[0].id]}))throw new Error('wrong_diagnostics');
      mark();await denied(()=>verify());await put(inputs.points);await verify();mark();
      for(const kind of ['dense','sparse','payload']){
        const wrong=clone(inputs.points[0]);
        if(kind==='dense')wrong.vector.dense=wrong.vector.dense.map(value=>-value);
        else if(kind==='sparse')wrong.vector.sparse.values[0]+=1;
        else wrong.payload.tenant_id='foreign-native-tenant';
        await put([wrong]);await denied(()=>inspect());await put(inputs.points.slice(0,1));
      }
      mark();
      const extra=clone(inputs.points[0]);extra.id='00000000-0000-4000-8000-000000000099';extra.payload.generation_id='unexpected-native-generation';
      await put([extra]);await denied(()=>inspect());await remove([extra.id]);mark();
      for(const mode of ['membership','payload']){
        let fired=false;
        const drift={async request(method,path,requestOptions){
          if(path.endsWith('/scroll')&&!fired){fired=true;
            if(mode==='membership')await remove([inputs.points.at(-1).id]);
            else{const changed=clone(inputs.points[0]);changed.payload.tag='changed-between-reads';await put([changed]);}
          }
          return read.request(method,path,requestOptions);
        },async close(){}};
        await denied(()=>inspect(drift));if(!fired)throw new Error('drift_not_exercised');await put(inputs.points);
      }
      mark();
      const tombstone={...data,tombstoned:true};await denied(()=>verify(read,tombstone));await remove(data.point_ids);await verify(read,tombstone);mark();
      const empty={...data,points:[],point_ids:[]};await put(inputs.points.slice(0,1));await denied(()=>inspect(read,empty));
      await remove([inputs.points[0].id]);
      if(!same(await inspect(read,empty),{present_ids:[],missing_ids:[],stale_ids:[]}))throw new Error('empty_scope');
      await verify(read,empty);mark();await put(inputs.points);
      let observedBytes=0,calls=0;
      const measured={async request(method,path,requestOptions){
        calls++;const body=decode(requestOptions.body);
        if(path.endsWith('/scroll')&&!same(body.filter.must.map(item=>item.key).sort(),
          ['backend_namespace','physical_collection','collection_incarnation','tenant_id','collection','document_id'].sort()))throw new Error('hidden_scope');
        const raw=await read.request(method,path,requestOptions);observedBytes+=raw.length;return raw;
      },async close(){}};
      const budget=new SecurityReadbackBudget();
      for(let pass=0;pass<2;pass++){const result=await inspect(measured,data,budget);if(result.missing_ids.length||result.stale_ids.length)throw new Error('complete_diagnostics');}
      await verify(measured,data,budget);
      if(budget.remaining_bytes!==8388608-observedBytes||budget.remaining_calls!==513-calls||calls<=0||observedBytes<=0)throw new Error('budget_reset');
      mark();
    });
    return {runtime:'typescript',checks,proof_scope:'security_document_readback_diagnostics_only'};
  }catch(error){primary=error;throw error;}
  finally{
    const failures=[],deadline=now()+12;
    try{await bounded(supervisor.close(),{deadline:Math.min(now()+8,deadline)});}catch(error){failures.push({operation:'controller_close',outcome:outcome(error)});}
    if(address){try{await observedListener(address,true);}catch(error){failures.push({operation:'listener_close',outcome:outcome(error)});}}
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
