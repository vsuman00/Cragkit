/** Actual repair interrupted by an independently committed tombstone. */
import http from 'node:http';
import {execFile} from 'node:child_process';
import {createHash} from 'node:crypto';
import {isDeepStrictEqual as same} from 'node:util';
import {PoolResource,parse_pool_config,bounded,now} from '../packages/typescript/dist/postgres-pool.js';
import {ExecutionLedger} from '../packages/typescript/dist/execution.js';
import {parse_request} from '../packages/typescript/dist/requests.js';
import {QdrantPublicationManager,PostgresQdrantPublicationAuthority,ManagedQdrantPublicationTransport,
  PostgresQdrantWriter,PostgresQdrantRecovery,ManagedQdrantSupervisor,QdrantReconciliationVerifier} from '../packages/typescript/dist/qdrant-publication.js';
import {QdrantSecurityManager} from '../packages/typescript/dist/qdrant-security.js';
import {PostgresQdrantSourceStore} from '../packages/typescript/dist/qdrant-source.js';
import {purge_projection_data,security_projection_data,PURGE_RETENTION_POLICY} from '../packages/typescript/dist/qdrant-writer.js';
import {encode_security_intent} from '../packages/typescript/dist/qdrant-manifest.js';
import {ProviderUnavailable} from '../packages/typescript/dist/errors.js';

const CHECKS=[
  'repair_admitted_before_tombstone',
  'independent_tombstone_commits_without_wait',
  'source_and_grants_denied_while_repair_held',
  'pending_purge_preserves_owner_claims_pointer',
  'late_repair_ack_unknown_cannot_publish',
  'managed_purge_fences_and_settles_uncertainty',
  'final_absence_and_source_denial_preserve_outside',
];
const ERRORS=new Set(['InvalidRequest','IntegrityViolation','ProviderUnavailable','UnauthorizedScope',
  'UnsupportedCapability','DeadlineExceeded','IndexNotReady','BudgetExhausted','AbortError']);
const OWNER='00000000-0000-4000-8000-000000000001';
const cancellation=new AbortController();let reading=true,step=0;
const cancel=()=>{cancellation.abort();if(reading)process.stdin.destroy();};
process.on('SIGTERM',cancel);process.on('SIGINT',cancel);
const assert=value=>{if(!value)throw new Error('acceptance_failed');};
const bytes=value=>[...Buffer.from(JSON.stringify(value),'utf8')];
const decode=value=>JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.from(value)));
const hash=value=>createHash('sha256').update(value).digest('hex');
async function input(){
  const chunks=[];let size=0;
  for await(const chunk of process.stdin){size+=chunk.length;assert(size<=1048576);chunks.push(chunk);}
  const value=decode(Buffer.concat(chunks));
  assert(value&&same(Object.keys(value).sort(),['binary','inputs','reader_config','supervisor_config','work_dir','writer_config'])
    &&typeof value.binary==='string'&&typeof value.work_dir==='string');return value;
}
async function listener(address,absent=false){
  const url=new URL(address);assert(url.protocol==='http:'&&url.hostname==='127.0.0.1'&&url.port&&url.origin===address);
  return new Promise((resolve,reject)=>execFile('/usr/sbin/lsof',['-nP','-a','-iTCP@127.0.0.1:'+url.port,'-sTCP:LISTEN','-t'],
    {encoding:'utf8',env:{PATH:'/usr/bin:/bin'},maxBuffer:1024,timeout:3000,killSignal:'SIGKILL'},(error,out,err)=>{
      if(absent&&error?.code===1&&out===''&&err==='')return resolve();
      if(error||err||absent||!/^[1-9][0-9]{0,9}\n?$/.test(out))return reject(new Error('listener_observation'));
      resolve();
    }));
}
async function cases(value){
  const {inputs}=value,options={deadline:now()+120,signal:cancellation.signal};
  const pools=[value.writer_config,value.supervisor_config,value.reader_config].map(config=>new PoolResource(parse_pool_config(config)));
  assert(pools.every(pool=>pool.config.max_size===1));
  const writer=new PostgresQdrantWriter(pools[0],inputs.config,inputs.instance_id);
  const independent=new PostgresQdrantWriter(pools[0],inputs.config,inputs.instance_id);
  const supervisor=new ManagedQdrantSupervisor(value.binary,value.work_dir,inputs.instance_id,inputs.config);
  const verifier=new QdrantReconciliationVerifier(writer,supervisor);
  const recovery=new PostgresQdrantRecovery(pools[1],inputs.config,supervisor,verifier);
  const transport=new ManagedQdrantPublicationTransport(supervisor);
  const allowed=async(scope,collection,document)=>scope.tenant_id===inputs.scope.tenant_id
    &&collection===inputs.stage.manifest.collection&&[inputs.stage.manifest.document_id,inputs.ownerless_stage.manifest.document_id].includes(document);
  const manager=new QdrantPublicationManager(new PostgresQdrantPublicationAuthority(writer,recovery),transport,inputs.config,supervisor,allowed);
  const security=new QdrantSecurityManager(independent,allowed),store=new PostgresQdrantSourceStore(pools[2],inputs.config);
  const nativeRequest=http.request,pointPath='/collections/'+inputs.config.physical_collection+'/points',target=pointPath+'?wait=true&ordering=strong';
  const scope=revision=>({...inputs.scope,authorization_revision:revision,...(revision==='auth-2'?{principal_id:'reader-b'}:{})});
  const ref=(intent,stage=inputs.stage)=>({collection:stage.manifest.collection,document_id:stage.manifest.document_id,intent_id:intent});
  const context=(intent,revision)=>({...ref(intent),scope:scope(revision),owner_token:OWNER});
  const checks=[],observations=[],handles=new Set();
  let address,held=null,oldJob=null,currentKey,puts=0,oldKey;
  const add=row=>{observations.push(row);checks.push(CHECKS[checks.length]);step=checks.length;};
  async function call(work){
    const book=new ExecutionLedger({limits:{deadline_ms:120000,max_attempts:1,max_provider_calls:0},deadline:options.deadline});
    try{return await work(book);}finally{const state=book.snapshot();assert(state.attempts===1&&state.provider_calls===0&&state.pending===0);}
  }
  async function journal(intent){
    return pools[1].withLease(options,async client=>{
      await client.query({text:'BEGIN',rowMode:'array'});
      try{
        await client.query({text:"SELECT set_config('cragkit_qdrant.backend_instance_id',$1,true)",values:[inputs.instance_id],rowMode:'array'});
        const rows=(await client.query({text:'SELECT dispatch_id,state,completion_sha256 FROM cragkit_qdrant.dispatch_journal WHERE instance_id=$1 AND tenant_id=$2 AND collection=$3 AND document_id=$4 AND intent_id=$5 ORDER BY sequence LIMIT 9',
          values:[inputs.instance_id,inputs.scope.tenant_id,inputs.stage.manifest.collection,inputs.stage.manifest.document_id,intent],rowMode:'array'})).rows;
        await client.query({text:'COMMIT',rowMode:'array'});return rows;
      }catch(error){await client.query({text:'ROLLBACK',rowMode:'array'});throw error;}
    });
  }
  const nomination={point_id:inputs.expected_points[0].id,branch:'dense',score:1,score_kind:'cosine_similarity',score_direction:'higher_is_better',verification:'UNVERIFIED',payload:structuredClone(inputs.expected_points[0].payload)};
  const request=parse_request({query:'native source verification',collection:inputs.stage.manifest.collection});
  function unavailable(result){assert(result.state==='unavailable'&&result.binding===null&&result.evidence===null&&result.private_source===null&&result.source_bytes===0);}
  async function source(revision,principal=inputs.scope.principal_id,stage=inputs.stage){
    const handle=store.open_request(request,{...options,scope:{...scope(revision),principal_id:principal}});handles.add(handle);
    const selected={...nomination,point_id:stage.manifest.members[0].point_id,
      payload:{...nomination.payload,document_id:stage.manifest.document_id}};
    const result=await handle.fetch_candidate(selected,{max_source_bytes:16777216,include_source:true});
    if(result.state==='verified'){
      const canonical=Buffer.from(stage.canonical_text,'utf8'),member=stage.manifest.members.find(item=>item.point_id===selected.point_id);
      const excerpt=canonical.subarray(member.start_byte,member.end_byte);
      assert(result.binding&&result.private_source.canonical_text===stage.canonical_text
        &&result.evidence.text===new TextDecoder('utf-8',{fatal:true}).decode(excerpt)
        &&result.evidence.source_sha256===hash(canonical)&&result.evidence.text_sha256===hash(excerpt));
    }
    else unavailable(result);return {handle,result};
  }
  async function closeSource(pair){await pair.handle.close();handles.delete(pair.handle);}
  async function physical(method,path,key,body){
    const endpoint=new URL(address),encoded=body===undefined?undefined:Buffer.from(JSON.stringify(body));
    return bounded(new Promise((resolve,reject)=>{
      const outgoing=nativeRequest.call(http,{hostname:'127.0.0.1',port:Number(endpoint.port),method,path,agent:false,signal:options.signal,
        headers:{'api-key':key,...(encoded?{'content-type':'application/json','content-length':encoded.length}:{})}},incoming=>{
        const chunks=[];let size=0;
        incoming.on('data',chunk=>{size+=chunk.length;if(size>1048576)outgoing.destroy(new ProviderUnavailable());else chunks.push(Buffer.from(chunk));});
        incoming.on('error',reject);incoming.once('end',()=>resolve({status:incoming.statusCode,body:Buffer.concat(chunks)}));
      });outgoing.on('error',reject);outgoing.setTimeout(Math.max(1,Math.min(5000,(options.deadline-now())*1000)),()=>outgoing.destroy(new ProviderUnavailable()));outgoing.end(encoded);
    }),options);
  }
  http.request=function(requestOptions,callback){
    if(requestOptions?.headers?.['api-key'])currentKey=requestOptions.headers['api-key'];
    const isPut=requestOptions?.method==='PUT'&&requestOptions.path===target;
    if(isPut)puts++;
    const hold=isPut&&held?.armed?held:null;
    if(hold){hold.armed=false;oldKey=currentKey;}
    const outgoing=nativeRequest.call(this,requestOptions,incoming=>{
      if(!hold)return callback(incoming);
      const chunks=[];let size=0,suppressed=false;const originalOnce=incoming.once;
      incoming.on('data',chunk=>{size+=chunk.length;if(size<=1048576)chunks.push(Buffer.from(chunk));});
      originalOnce.call(incoming,'end',()=>{
        try{
          const response=decode(Buffer.concat(chunks));
          assert(suppressed&&size<=1048576&&incoming.statusCode===200&&response.status==='ok'&&response.result.status==='completed');
          hold.status=200;hold.completed=true;
        }catch{hold.invalid=true;}
        incoming.emit('error',new ProviderUnavailable());
      });
      incoming.once=function(event,listener){if(event==='end'&&!suppressed){suppressed=true;return this;}return originalOnce.call(this,event,listener);};
      try{callback(incoming);}finally{incoming.once=originalOnce;}
    });
    if(hold){
      const originalWrite=outgoing.write,originalEnd=outgoing.end,chunks=[];
      outgoing.write=function(chunk){chunks.push(Buffer.from(chunk));return true;};
      outgoing.end=function(chunk){
        if(chunk&&typeof chunk!=='function')chunks.push(Buffer.from(chunk));hold.body=Buffer.concat(chunks);
        hold.release=()=>{assert(!hold.released);hold.released=true;originalWrite.call(outgoing,hold.body);originalEnd.call(outgoing);};
        hold.reached();return outgoing;
      };
    }
    return outgoing;
  };
  try{
    await supervisor.initialize({...options,provision:async(admin,probe)=>{
      await admin.request('PUT','/collections/'+inputs.config.physical_collection,{...options,body:bytes(inputs.collection_config)});
      await admin.request('PUT','/collections/'+probe.collection,{...options,body:bytes(probe.collection_config)});
      const response=decode(await admin.request('PUT','/collections/'+probe.collection+'/points?wait=true&ordering=strong',{...options,body:bytes({points:[probe.point]})}));
      assert(response.status==='ok'&&response.result.status==='completed');
    }});
    address=supervisor.identity().endpoint;await listener(address);
    for(const pool of pools)await pool.open();
    await manager.initialize(options);await independent.initialize(options);await security.initialize(options);await store.initialize(options);
    await call(book=>manager.stage(inputs.stage,inputs.scope,book,options));
    assert((await call(book=>manager.publish(ref(inputs.stage.intent.intent_id),inputs.scope,book,options))).published);
    const outside=inputs.ownerless_stage;
    await call(book=>manager.stage(outside,inputs.scope,book,options));
    assert((await call(book=>manager.publish(ref(outside.intent.intent_id,outside),inputs.scope,book,options))).published);
    const outsideBefore=decode((await physical('POST',pointPath,currentKey,{ids:outside.manifest.members.map(member=>member.point_id),with_payload:true,with_vector:true})).body).result;
    assert(outsideBefore.length===outside.manifest.members.length);
    const second=structuredClone(inputs.second_stage);second.intent.expected_active_generation_id=inputs.stage.manifest.generation_id;
    await call(book=>manager.stage(second,inputs.scope,book,options));
    const admitted=await independent.admit_publication(context(second.intent.intent_id,'auth-1'),options);
    assert(admitted.owner?.owner_token===OWNER&&admitted.owner.backend_epoch===1&&admitted.intent.state==='writing');
    const owned=await independent.manager_snapshot(context(second.intent.intent_id,'auth-1'),options);
    assert(owned.owner?.intent_id===second.intent.intent_id&&owned.owner.owner_token===OWNER&&!owned.pending);
    const retained=await source('auth-1');assert(retained.result.state==='verified');
    let reached;const entered=new Promise(resolve=>{reached=resolve;});held={armed:true,reached,released:false,completed:false};
    oldJob=call(book=>manager.repair(ref(second.intent.intent_id),inputs.scope,book,options)).then(result=>({result}),error=>({error}));
    await bounded(Promise.race([entered,oldJob.then(()=>{throw new Error('held_write_missing');})]),options);
    const oldPoints=decode(held.body).points,oldRows=await journal(second.intent.intent_id);
    assert(oldPoints.length===2&&oldPoints.every(point=>point.payload.authorization_revision==='auth-1'&&point.vector.dense&&point.vector.sparse)
      &&same(oldPoints.map(point=>point.id).sort(),second.manifest.members.map(member=>member.point_id).sort())
      &&oldRows.length===1&&oldRows[0][1]==='dispatched'&&!held.released&&!held.completed);
    const ownerBefore=await independent.manager_snapshot(context(second.intent.intent_id,'auth-1'),options);
    assert(ownerBefore.owner?.intent_id===second.intent.intent_id&&ownerBefore.document.active_generation_id===inputs.stage.manifest.generation_id);
    add(['repair','auth-1',2,'dispatched']);
    const change=structuredClone(inputs.security);change.action='tombstone';change.authorization.tombstoned=true;
    change.authorization.principal_ids=[];change.authorization.grant_ids=[];
    const beforePuts=puts;
    const committed=await call(book=>security.tombstone(change,scope('auth-1'),book,options));
    assert(committed.authority_committed&&!committed.replica_complete&&!held.released&&!held.completed&&puts===beforePuts);
    const state=await independent.manager_snapshot(context(change.intent_id,'auth-2'),options);
    assert(state.document.authorization_revision==='auth-2'&&state.document.tombstoned
      &&state.document.mutation_epoch===2
      &&state.document.active_generation_id===inputs.stage.manifest.generation_id&&state.pending);
    add(['tombstone','auth-2',true,false]);
    const preRelease=await retained.handle.release(retained.result.binding,{purpose:'provider',max_source_bytes:16777216,include_source:true});unavailable(preRelease);
    unavailable(await retained.handle.release(retained.result.binding,{purpose:'final',max_source_bytes:16777216,include_source:true}));
    await closeSource(retained);
    const freshDenied=await source('auth-2');unavailable(freshDenied.result);await closeSource(freshDenied);
    add(['source','unavailable','unavailable',0]);
    const purge={intent_id:'native-tombstone-repair-purge',tenant_id:change.tenant_id,collection:change.collection,document_id:change.document_id,
      tombstone_intent_payload_sha256:encode_security_intent(change).sha256,expected_authorization_revision:'auth-2',expected_mutation_epoch:2};
    const bound=await independent.bind_purge(purge,scope('auth-2'),{...options,owner_token:OWNER});
    assert(bound.authority_committed&&!bound.replica_complete&&!bound.purge_complete);
    const purgeProjection=await independent.project_purge(context(purge.intent_id,'auth-2'),PURGE_RETENTION_POLICY,options);
    const projected=purge_projection_data(purgeProjection,independent),graph=security_projection_data(projected.projection,independent);
    const claims=[...graph.point_ids].sort();assert(claims.length===4&&graph.tombstoned
      &&same(graph.principal_ids,[])&&same(graph.grant_ids,[]));
    let refused=false;
    try{await independent.admit_purge_tombstone(purgeProjection,options);}catch(error){assert(error instanceof ProviderUnavailable);refused=true;}
    const pending=await independent.manager_snapshot(context(purge.intent_id,'auth-2'),options);
    assert(refused&&same(pending.owner,ownerBefore.owner)&&pending.document.active_generation_id===inputs.stage.manifest.generation_id
      &&pending.pending&&!pending.intent.purge_complete&&puts===beforePuts&&same(await journal(second.intent.intent_id),oldRows)&&!held.released);
    add(['pending',4,'ProviderUnavailable']);
    held.release();const oldOutcome=await bounded(oldJob,options);oldJob=null;
    assert(oldOutcome.error instanceof ProviderUnavailable&&held.completed&&held.status===200&&!held.invalid);
    const uncertain=await journal(second.intent.intent_id);assert(uncertain.length===1&&uncertain[0][0]===oldRows[0][0]&&uncertain[0][1]==='unknown');
    const denied=await source('auth-1');unavailable(denied.result);await closeSource(denied);
    const failedRepair=await independent.manager_snapshot(context(second.intent.intent_id,'auth-2'),options);
    const pendingAfter=await independent.manager_snapshot(context(purge.intent_id,'auth-2'),options);
    assert(failedRepair.intent.state!=='published'&&failedRepair.document.tombstoned
      &&failedRepair.document.authorization_revision==='auth-2'&&failedRepair.document.mutation_epoch===2
      &&failedRepair.document.active_generation_id===inputs.stage.manifest.generation_id&&same(failedRepair.owner,ownerBefore.owner)
      &&pendingAfter.pending&&!pendingAfter.intent.purge_complete);
    const afterGraph=security_projection_data(purge_projection_data(await independent.project_purge(context(purge.intent_id,'auth-2'),PURGE_RETENTION_POLICY,options),independent).projection,independent);
    assert(same([...afterGraph.point_ids].sort(),claims)&&afterGraph.tombstoned
      &&same(afterGraph.principal_ids,[])&&same(afterGraph.grant_ids,[]));
    add(['late_completion',200,'unknown',false]);
    const generation=supervisor.control_binding().credential_generation;
    async function assertAbsence(){
      for(let repeat=0;repeat<2;repeat++){
        const found=await physical('POST',pointPath,currentKey,{ids:claims,with_payload:true,with_vector:true});
        assert(found.status===200&&same(decode(found.body).result,[]));
        const match=key=>({key,match:{value:inputs.stage.manifest[key]}});
        const scoped=await physical('POST',pointPath+'/scroll',currentKey,{filter:{must:['backend_namespace','physical_collection','collection_incarnation','tenant_id','collection','document_id'].map(match)},limit:8,with_payload:true,with_vector:true});
        const result=decode(scoped.body).result;
        assert(scoped.status===200&&same(result.points,[])&&result.next_page_offset===null);
      }
    }
    const originalComplete=writer.complete_purge;let completionChecks=0;
    writer.complete_purge=async function(...args){
      const before=await writer.manager_snapshot(context(purge.intent_id,'auth-2'),options);
      assert(!before.pending&&!before.intent.purge_complete
        &&(await journal(second.intent.intent_id)).every(row=>row[1]==='settled')
        &&(await journal(purge.intent_id)).every(row=>row[1]==='settled'));
      await assertAbsence();completionChecks++;
      return originalComplete.apply(this,args);
    };
    let purged;
    try{purged=await call(book=>manager.purge(purge,scope('auth-2'),book,PURGE_RETENTION_POLICY,options));}
    finally{writer.complete_purge=originalComplete;}
    assert(completionChecks===1);
    assert(purged.state==='complete'&&purged.authority_committed&&purged.replica_complete&&purged.purge_complete);
    const recovered=await writer.manager_snapshot(context(purge.intent_id,'auth-2'),options);
    assert(recovered.backend.state==='open'&&!recovered.pending&&recovered.document.tombstoned
      &&supervisor.control_binding().credential_generation!==generation);
    assert((await physical('GET',pointPath,oldKey)).status===401);
    assert((await journal(second.intent.intent_id)).every(row=>row[1]==='settled')&&(await journal(purge.intent_id)).every(row=>row[1]==='settled'));
    add(['purged','open',true,true]);
    await assertAbsence();
    const stale=await source('auth-1');unavailable(stale.result);await closeSource(stale);
    const revoked=await source('auth-2');unavailable(revoked.result);await closeSource(revoked);
    const outsideAfter=decode((await physical('POST',pointPath,currentKey,{ids:outside.manifest.members.map(member=>member.point_id),with_payload:true,with_vector:true})).body).result;
    const normalized=points=>points.map(({id,payload,vector})=>({id,payload,vector})).sort((a,b)=>a.id.localeCompare(b.id));
    assert(same(normalized(outsideAfter),normalized(outsideBefore)));
    const current=await source('auth-1',inputs.scope.principal_id,outside);assert(current.result.state==='verified');await closeSource(current);
    add(['absence',0,'unavailable','verified',0]);
    return {runtime:'typescript',checks,proof_scope:'native_tombstone_during_repair_only',
      semantic_witness_sha256:hash(Buffer.from(JSON.stringify(['cragkit.qdrant.tombstone-repair.v1',observations]),'utf8'))};
  }finally{
    http.request=nativeRequest;
    const failures=[],deadline=now()+15;
    async function close(owner){try{await bounded(Promise.resolve().then(()=>owner.close()),{deadline:Math.max(now()+.001,Math.min(now()+8,deadline))});}catch{failures.push(true);}}
    if(oldJob){cancellation.abort();try{await bounded(oldJob,{deadline:Math.min(now()+5,deadline)});}catch{failures.push(true);}}
    for(const owner of [...handles,store,manager,security,transport,recovery,verifier,independent,writer,...pools,supervisor])await close(owner);
    if(address)try{await listener(address,true);}catch{failures.push(true);}
    if(failures.length)throw new Error('cleanup_failed');
  }
}
try{const value=await bounded(input(),{deadline:now()+5,signal:cancellation.signal});reading=false;process.stdout.write(JSON.stringify(await cases(value))+'\n');}
catch(error){process.stdin.destroy();process.stdout.write(JSON.stringify({ok:false,step,error:ERRORS.has(error?.name)?error.name:'internal'})+'\n');process.exitCode=1;}
finally{process.removeListener('SIGTERM',cancel);process.removeListener('SIGINT',cancel);}
