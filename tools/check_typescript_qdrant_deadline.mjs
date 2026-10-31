/** Native operation deadline with a separately owned delayed HTTP delivery. */
import http from 'node:http';
import {execFile} from 'node:child_process';
import {createHash} from 'node:crypto';
import {writeFileSync} from 'node:fs';
import {dirname,join} from 'node:path';
import {isDeepStrictEqual as same} from 'node:util';
import {PoolResource,parse_pool_config,bounded,now} from '../packages/typescript/dist/postgres-pool.js';
import {ExecutionLedger} from '../packages/typescript/dist/execution.js';
import {QdrantPublicationManager,PostgresQdrantPublicationAuthority,ManagedQdrantPublicationTransport,
  PostgresQdrantWriter,PostgresQdrantRecovery,ManagedQdrantSupervisor,QdrantReconciliationVerifier} from '../packages/typescript/dist/qdrant-publication.js';
import {ProviderUnavailable} from '../packages/typescript/dist/errors.js';

const CHECKS=['admitted_same_request_before_deadline','owner_authority_resource_closed',
  'deadline_expires_with_request_pending','fresh_successor_refused_without_dispatch',
  'same_request_completes_without_settlement','late_completion_still_blocks_successor',
  'managed_recovery_settles_before_publication'];
const ERRORS=new Set(['InvalidRequest','IntegrityViolation','ProviderUnavailable','UnauthorizedScope',
  'UnsupportedCapability','DeadlineExceeded','IndexNotReady','BudgetExhausted','AbortError']);
const assert=value=>{if(!value)throw new Error('deadline_acceptance_failed');};
const encode=value=>Buffer.from(JSON.stringify(value));
const decode=value=>JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.from(value)));
const cancel=new AbortController();let step=0,diagnosticsPath;
process.on('SIGTERM',()=>cancel.abort());process.on('SIGINT',()=>cancel.abort());
async function listener(address){
  return new Promise((resolve,reject)=>execFile('/usr/sbin/lsof',['-nP','-a','-iTCP@127.0.0.1:'+new URL(address).port,'-sTCP:LISTEN','-t'],
    {encoding:'utf8',maxBuffer:1024,timeout:3000},(error,out,err)=>error?.code===1&&out===''&&err===''?resolve():reject(new Error('deadline_listener_remains'))));
}
async function cases(value){
  const {inputs}=value,options={deadline:now()+90,signal:cancel.signal};
  const base=inputs.stage,old=inputs.successor,next=inputs.competing_successor;
  const pools=[value.writer_config,value.writer_config,value.supervisor_config].map(raw=>new PoolResource(parse_pool_config(raw)));
  const observer=new PoolResource(parse_pool_config(value.observer_config));
  assert(pools.every(pool=>pool.config.max_size===1));
  const writers=pools.slice(0,2).map(pool=>new PostgresQdrantWriter(pool,inputs.config,inputs.instance_id));
  const supervisor=new ManagedQdrantSupervisor(value.binary,value.work_dir,inputs.instance_id,inputs.config);
  const owned=[],managers=[],checks=[],rows=[];const add=row=>{rows.push(row);checks.push(CHECKS[checks.length]);step=checks.length;};
  const nativeRequest=http.request,target='/collections/'+inputs.config.physical_collection;
  const ref=stage=>Object.fromEntries(['collection','document_id','intent_id'].map(key=>[key,stage.intent[key]]));
  const context=stage=>({...ref(stage),scope:inputs.scope,owner_token:'00000000-0000-4000-8000-000000000088'});
  const allowed=async(scope,collection,document)=>same(scope,inputs.scope)&&collection===base.manifest.collection&&document===base.manifest.document_id;
  let address,currentKey,oldKey,armed=false,retained,retainedRequest,productJob,release,entered,requestBody,completed=false;
  const arrival=new Promise(resolve=>{entered=resolve;});
  async function call(manager,method,item,selected=options){
    const ledger=new ExecutionLedger({limits:{deadline_ms:60000,max_provider_calls:0},deadline:selected.deadline});
    try{return await manager[method](item,inputs.scope,ledger,selected);}
    finally{const usage=ledger.snapshot();assert(usage.attempts===1&&usage.provider_calls===0&&usage.pending===0);}
  }
  async function physical(method,path,key,body){
    const encoded=body===undefined?undefined:encode(body);
    return bounded(new Promise((resolve,reject)=>{
      const request=nativeRequest.call(http,{hostname:'127.0.0.1',port:Number(new URL(address).port),method,path,agent:false,
        headers:{'api-key':key,...(encoded?{'content-type':'application/json','content-length':encoded.length}:{})}},response=>{
        const chunks=[];let size=0;
        response.on('data',chunk=>{size+=chunk.length;if(size>65536)request.destroy(new ProviderUnavailable());else chunks.push(chunk);});
        response.on('error',reject);response.on('end',()=>resolve({status:response.statusCode,body:Buffer.concat(chunks)}));
      });request.on('error',reject);request.setTimeout(5000,()=>request.destroy(new ProviderUnavailable()));request.end(encoded);
    }),options);
  }
  const canonical=points=>points.map(point=>Object.fromEntries(['id','payload','vector'].map(key=>[key,point[key]]))).sort((a,b)=>a.id.localeCompare(b.id));
  async function read(ids){const response=await physical('POST',target+'/points',currentKey,{ids,with_payload:true,with_vector:true});assert(response.status===200);return canonical(decode(response.body).result);}
  const snapshot=()=>writers[1].manager_snapshot(context(old),options);
  async function query(text,values=[]){return observer.withLease(options,async client=>(await client.query({text,values,rowMode:'array'})).rows);}
  const journal=()=>query('SELECT intent_id,dispatch_id,state,request_sha256,sequence::text FROM cragkit_qdrant.dispatch_journal WHERE instance_id=$1 ORDER BY intent_id,sequence',[inputs.instance_id]);
  async function refuse(){try{await writers[1].acquire_owner(context(next),options);}catch(error){assert(error instanceof ProviderUnavailable);return;}throw new Error('deadline_successor_admitted');}
  http.request=function(requestOptions,callback){
    if(requestOptions?.headers?.['api-key'])currentKey=requestOptions.headers['api-key'];
    const product=nativeRequest.call(this,requestOptions,callback);
    if(!armed||requestOptions.method!=='PUT'||requestOptions.path!==target+'/points?wait=true&ordering=strong')return product;
    armed=false;oldKey=currentKey;const chunks=[];
    product.write=function(chunk){chunks.push(Buffer.from(chunk));return true;};
    product.end=function(chunk){
      if(chunk!==undefined)chunks.push(Buffer.from(chunk));requestBody=Buffer.concat(chunks);
      // The fixture owns delayed delivery. Product cancellation still destroys
      // its own request and cannot manufacture a completed acknowledgment.
      retained=new Promise((resolve,reject)=>{
        const {signal,...delayedOptions}=requestOptions;
        retainedRequest=nativeRequest.call(http,{...delayedOptions,agent:false},response=>{
          const parts=[];let size=0;
          response.on('data',part=>{size+=part.length;if(size>65536)retainedRequest.destroy(new ProviderUnavailable());else parts.push(part);});
          response.on('error',reject);response.on('end',()=>{completed=true;resolve({status:response.statusCode,body:Buffer.concat(parts)});});
        });retainedRequest.on('error',reject);retainedRequest.setTimeout(20000,()=>retainedRequest.destroy(new ProviderUnavailable()));
        retainedRequest.write(requestBody.subarray(0,-1),()=>entered());
        release=()=>retainedRequest.end(requestBody.subarray(-1));
      });retained.catch(()=>{});return product;
    };return product;
  };
  try{
    await supervisor.initialize({...options,provision:async(admin,probe)=>{
      await admin.request('PUT',target,{...options,body:[...encode(inputs.collection_config)]});
      const path='/collections/'+probe.collection;
      await admin.request('PUT',path,{...options,body:[...encode(probe.collection_config)]});
      await admin.request('PUT',path+'/points?wait=true&ordering=strong',{...options,body:[...encode({points:[probe.point]})]});
    }});address=supervisor.identity().endpoint;
    for(const pool of pools)await pool.open();
    for(const writer of writers){
      const verifier=new QdrantReconciliationVerifier(writer,supervisor),recovery=new PostgresQdrantRecovery(pools[2],inputs.config,supervisor,verifier);
      const transport=new ManagedQdrantPublicationTransport(supervisor),authority=new PostgresQdrantPublicationAuthority(writer,recovery);
      const manager=new QdrantPublicationManager(authority,transport,inputs.config,supervisor,allowed);
      owned.push(manager,transport,authority,recovery,verifier);managers.push(manager);await manager.initialize(options);
    }
    await call(managers[0],'stage',base);assert((await call(managers[0],'publish',ref(base))).published);
    for(const stage of [old,next])await call(managers[0],'stage',stage);
    const baseIds=base.manifest.members.map(member=>member.point_id),baseline=await read(baseIds);
    const short={...options,deadline:now()+5};armed=true;
    productJob=call(managers[0],'publish',ref(old),short);productJob.catch(()=>{});
    await bounded(arrival,{...options,deadline:now()+4});assert(now()<short.deadline&&!completed);
    const before=await snapshot();assert(before.pending);add(['request','dispatched',true]);
    const ownerPid=await pools[0].withLease(options,async client=>(await client.query({text:'SELECT pg_backend_pid()',rowMode:'array'})).rows[0][0]);
    await pools[0].close();await observer.open();
    assert(same(await query('SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=$1)',[ownerPid]),[[false]]));
    const durable=await journal(),dispatched=durable.filter(row=>row[0]===old.intent.intent_id);
    assert(dispatched.length===1&&dispatched[0][2]==='dispatched'&&dispatched[0][3]===createHash('sha256').update(requestBody).digest('hex'));
    try{await writers[0].manager_snapshot(context(old),options);throw new Error('deadline_reopened');}catch(error){assert(error instanceof ProviderUnavailable);}
    add(['authority','closed']);
    try{await productJob;throw new Error('deadline_succeeded');}catch(error){assert(['DeadlineExceeded','ProviderUnavailable','AbortError'].includes(error.name));}
    productJob=null;
    while(now()<short.deadline)await new Promise(resolve=>setTimeout(resolve,Math.max(1,Math.ceil((short.deadline-now())*1000))));
    assert(!completed);add(['expiry',true,true]);
    await refuse();assert(same(await snapshot(),before)&&same(await journal(),durable));add(['successor','refused',0]);
    release();const response=await bounded(retained,options);assert(response.status===200&&decode(response.body).result.status==='completed');
    const points=decode(requestBody).points;assert(same(await read(points.map(point=>point.id)),canonical(points)));add(['completion',200,true]);
    await refuse();assert(same(await snapshot(),before)&&same(await journal(),durable));add(['uncertainty',true]);
    const result=await call(managers[1],'repair',ref(old)),final=await snapshot();
    assert(result.published&&!final.pending&&final.backend.epoch>before.backend.epoch);
    const rejected=await physical('GET',target,oldKey);assert(rejected.status===401&&same(await read(baseIds),baseline));add(['recovery',true,401,true]);
  }finally{
    http.request=nativeRequest;retainedRequest?.destroy();
    if(productJob)await productJob.catch(()=>{});
    const failures=[];
    for(const item of [...owned,...writers,...pools,observer,supervisor])if(typeof item.close==='function')try{await item.close();}catch{failures.push(true);}
    assert(!failures.length&&[...pools,observer].every(pool=>pool.state==='closed'&&pool.work.size===0&&pool.connecting.size===0));
    if(address)await listener(address);
  }
  return {runtime:'typescript',checks,proof_scope:'native_deadline_not_fencing_only',
    public_results_sha256:createHash('sha256').update(encode(['cragkit.qdrant.deadline.v1',rows])).digest('hex')};
}
try{
  const chunks=[];let size=0;for await(const chunk of process.stdin){size+=chunk.length;assert(size<=1048576);chunks.push(chunk);}
  const value=decode(Buffer.concat(chunks));diagnosticsPath=join(dirname(value.work_dir),'deadline-node-failure.json');
  const result=await cases(value);process.stdout.write(JSON.stringify(result));
}catch(error){if(diagnosticsPath)writeFileSync(diagnosticsPath,JSON.stringify({step,name:error.name,frames:error.stack?.split('\n').slice(1)}));process.stdout.write(JSON.stringify({ok:false,step,error:ERRORS.has(error?.name)?error.name:'internal'}));process.exitCode=1;}
