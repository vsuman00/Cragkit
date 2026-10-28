import test,{mock} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import fs from 'node:fs/promises';
import childProcess from 'node:child_process';
import http from 'node:http';
import net from 'node:net';
import crypto,{createHash} from 'node:crypto';
import {EventEmitter} from 'node:events';
import {QdrantSecurityVerifier,security_receipt_data,security_verifier_binding} from '../dist/qdrant-security-verification.js';
import {ManagedQdrantSupervisor,control_session_binding} from '../dist/qdrant-supervisor.js';
import {PostgresQdrantWriter,prepare_stage,security_projection_data,WRITER_ROLE_SQL,WRITER_ATTESTATION_ROLE_SQL} from '../dist/qdrant-writer.js';
import {RECOVERY_ROLE_SQL} from '../dist/qdrant-recovery.js';
import {PoolResource,parse_pool_config,now} from '../dist/postgres-pool.js';
import {SecurityReadbackBudget} from '../dist/qdrant-security-readback.js';
import {AUTHORITY_HISTORY_SQL,AUTHORITY_PUBLICATION_HISTORY,AUTHORITY_PUBLICATION_CATALOG_SQL,AUTHORITY_FINGERPRINT_SQL,
 EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT,AUTHORITY_ATTESTATION_CATALOG_SQL,EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT} from '../dist/qdrant-authority.js';
import {InvalidRequest,IntegrityViolation,UnauthorizedScope,UnsupportedCapability,ProviderUnavailable,IndexNotReady,DeadlineExceeded} from '../dist/errors.js';
const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_publication.json',import.meta.url),'utf8'));
const config={...fixture.physical,dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse};
const token='00000000-0000-4000-8000-000000000001';
const scope={tenant_id:'tenant-a',principal_id:'reader-a',grant_ids:['grant-a'],authorization_revision:'auth-1'};
const options=()=>({deadline:now()+5}),opts=options,stageOpts=()=>({...options(),owner_token:token});
const bytes=value=>Array.from(Buffer.from(JSON.stringify(value)));
const clone=value=>Buffer.isBuffer(value)?Buffer.from(value):Array.isArray(value)?value.map(clone):value&&typeof value==='object'?Object.fromEntries(Object.entries(value).map(([key,child])=>[key,clone(child)])):value;
function input(){
 const manifest={...fixture.physical,tenant_id:'tenant-a',collection:'docs',document_id:'doc-1',revision_id:fixture.source_revision.revision_id,
 generation_id:fixture.intent.generation_id,source_sha256:fixture.source_revision.source_sha256,source_bytes:fixture.source_revision.source_bytes,
 source_locator:fixture.source_revision.source_locator,parser_id:fixture.source_revision.parser_id,chunker_profile:fixture.intent.chunker_profile,
 dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse,members:fixture.members.map(member=>({chunk_id:member.chunk_id,point_id:member.point_id,
 start_byte:member.start_byte,end_byte:member.end_byte,text_sha256:member.text_sha256,dense_input_sha256:member.dense.vector_sha256,sparse_input_sha256:member.sparse.vector_sha256}))};
 return {manifest,intent:{intent_id:'intent-2',tenant_id:'tenant-a',collection:'docs',document_id:'doc-1',manifest_sha256:fixture.intent.manifest_sha256,
 expected_active_generation_id:null,expected_authorization_revision:'auth-1',expected_mutation_epoch:1,initial_authorization:{authorization_revision:'auth-1',principal_ids:['reader-a'],grant_ids:['grant-a'],language:'en',kind:'guide',tag:'reference',tombstoned:false}},
 canonical_text:fixture.source_revision.canonical_utf8.value,dense_vectors:fixture.members.map(member=>Array.from({length:1536},(_,index)=>index===member.dense.basis_index?1:0)),
 sparse_vectors:fixture.members.map(member=>({indices:[...member.sparse.indices],values:[...member.sparse.values]}))};
}
function setup(){
  const state={queries:[],clients:[],role:true,history:AUTHORITY_PUBLICATION_HISTORY.map(row=>[...row]),
    catalog:true,fingerprint:EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT,startStatus:'I',commitLost:false,
    rollbackFail:false,wait:null,commitError:null,tables:{backend_instances:[{instance_id:'instance-fixture',backend_namespace:'fixture-local',
      storage_identity:'storage-fixture',supervisor_id:'supervisor-fixture',epoch:1,state:'open',recovery_id:null}]}};
  const keys={documents:['tenant_id','collection','document_id'],document_revisions:['tenant_id','collection','document_id','revision_id'],
    generations:['tenant_id','collection','document_id','generation_id'],members:['tenant_id','collection','document_id','revision_id','generation_id','chunk_id'],
    publication_intents:['tenant_id','collection','document_id','intent_id'],point_claims:['backend_namespace','physical_collection','collection_incarnation','point_id'],
    vector_replays:['tenant_id','collection','document_id','revision_id','generation_id','chunk_id'],document_owners:['tenant_id','collection','document_id'],
    dispatch_journal:['tenant_id','collection','document_id','intent_id','dispatch_id'],dispatch_points:['tenant_id','collection','document_id','intent_id','dispatch_id','point_id'],
    preparations:['tenant_id','collection','document_id','intent_id'],preparation_attestations:['tenant_id','collection','document_id','intent_id','backend_epoch','owner_token']};
  const pool={ends:0,async end(){this.ends++;},async connect(){
    const client={status:state.startStatus,releases:[],snapshot:null,getTransactionStatus(){return this.status;},release(value=false){
      this.releases.push(value);
      // Destroying a native connection rolls back its still-open transaction.
      if(value&&this.status==='T'&&this.snapshot){state.tables=this.snapshot;this.status='I';}
    },
      async query(query){
        const sql=query.text,params=query.values??[];state.queries.push(query);
        if(sql.startsWith('BEGIN')){this.recoveryInserted=false;this.recoveryMarked=null;this.attestationInserted=false;this.snapshot=clone(state.tables);this.status='T';return {rows:[]};}
        if(sql==='ROLLBACK'){if(state.rollbackFail)throw Error('private rollback');state.tables=this.snapshot;this.status='I';return {rows:[]};}
        if(sql==='COMMIT'){
          this.status='I';
          if(this.recoveryInserted&&state.recoveryCommitLost){state.recoveryCommitLost=false;throw Object.assign(Error('synthetic recovery commit lost'),{code:'08006'});}
          if(state.recoveryMarkLost&&this.recoveryMarked===state.recoveryMarkLost){state.recoveryMarkLost=null;throw Object.assign(Error('synthetic marker commit lost'),{code:'08006'});}
          if(this.attestationInserted&&state.attestationCommitLost){state.attestationCommitLost=false;state.onAttestationLost?.();throw Error('synthetic attestation commit acknowledgment loss');}
          if(state.commitError){const failure=state.commitError;state.commitError=null;state.tables=this.snapshot;throw failure;}
          if(state.commitLost){state.commitLost=false;state.onLostCommit?.();throw Error('private lost acknowledgment');}
          return {rows:[]};
        }
        if(sql===WRITER_ATTESTATION_ROLE_SQL)return {rows:[[state.role&&state.attestationRole!==false]]};
        if(sql===RECOVERY_ROLE_SQL)return {rows:[[state.recoveryRole!==false]]};
        if(sql===WRITER_ROLE_SQL){if(state.wait)await state.wait;return {rows:[[state.role]]};}
        if(sql===AUTHORITY_HISTORY_SQL)return {rows:state.history};
        if(sql===AUTHORITY_PUBLICATION_CATALOG_SQL||sql===AUTHORITY_ATTESTATION_CATALOG_SQL)return {rows:[[state.catalog]]};
        if(sql===AUTHORITY_FINGERPRINT_SQL)return {rows:[[state.fingerprint]]};
        if(sql.startsWith('SET ')||sql.startsWith('SELECT set_config'))return {rows:[]};
        const insert=/^INSERT INTO cragkit_qdrant\.(\w+) \(([^)]+)\)/.exec(sql);
        if(insert){
          const [,table,columns]=insert;
          if(table==='preparation_attestations'){if(state.attestationBodyError)throw state.attestationBodyError;this.attestationInserted=true;}
          const row=Object.fromEntries(columns.split(',').map((column,i)=>[column,['dense_profile','sparse_profile'].includes(column)&&params[i]!==null?JSON.parse(params[i]):clone(params[i])]));
          if(table==='dispatch_journal'&&row.recovery){this.recoveryInserted=true;state.recoveryInsertAttempts=(state.recoveryInsertAttempts??0)+1;if(state.recoveryBodyError)throw state.recoveryBodyError;}
          const rows=state.tables[table]??=[];
          if(rows.some(existing=>keys[table].every(key=>existing[key]===row[key])))return {rows:[]};
          if(table==='documents')Object.assign(row,{active_generation_id:null,...row});
          if(table==='generations')Object.assign(row,{published:false,ever_published:false,...row});
          if(table==='publication_intents')Object.assign(row,{state:'staged',authority_committed:false,replica_complete:false,purge_complete:false,...row});
          if(table==='dispatch_journal')Object.assign(row,{state:'reserved',recovery:false,completion_sha256:null,...row});
          rows.push(row);return {rows:sql.includes('RETURNING document_id')?[[row.document_id]]:[]};
        }
        const select=/^SELECT (.+?) FROM cragkit_qdrant\.(\w+) WHERE /.exec(sql);
        if(select){
          const [,columns,table]=select;
          if(table==='document_owners'&&sql.includes('FOR UPDATE')&&state.onOwnerLock){
            const boundary=state.onOwnerLock;state.onOwnerLock=null;boundary(state);
          }
          let rows=(state.tables[table]??[]).filter(row=>table==='backend_instances'?row.instance_id===params[0]:
            row.tenant_id===params[0]&&row.collection===params[1]&&row.document_id===params[2]);
          for(const [column,number] of [...sql.matchAll(/(?:AND |\()((?:intent|dispatch|revision|generation|chunk|point)_id|payload_sha256|backend_namespace|physical_collection|collection_incarnation|backend_epoch|owner_token|instance_id)=\$(\d+)(?!\d)/g)].map(match=>[match[1],Number(match[2])])){
            rows=rows.filter(row=>row[column]===params[number-1]);
          }
          if(sql.includes('(tenant_id,collection,document_id,intent_id,dispatch_id)='))rows=rows.filter(row=>row.intent_id===params[3]&&row.dispatch_id===params[4]);
          else if(sql.includes('(tenant_id,collection,document_id,intent_id)='))rows=rows.filter(row=>row.intent_id===params[3]);
          if(sql.includes('intent_id<>$4'))rows=rows.filter(row=>row.intent_id!==params[3]);
          if(sql.includes('point_id=ANY'))rows=rows.filter(row=>params[3].includes(row.point_id));
          if(sql.includes("state<>'settled'"))rows=rows.filter(row=>row.state!=='settled');
          if(sql.includes('manifest_sha256<>$6'))rows=rows.filter(row=>row.manifest_sha256!==params[5]);
          if(sql.includes("action='stage'"))rows=rows.filter(row=>row.action==='stage');
          if(sql.includes("ORDER BY convert_to(intent_id,'UTF8')"))rows.sort((left,right)=>Buffer.compare(Buffer.from(left.intent_id),Buffer.from(right.intent_id)));
          const limit=Number(/LIMIT (\d+)/.exec(sql)?.[1]??65);
          return {rows:rows.slice(0,limit).map(row=>columns.split(',').map(column=>clone(row[column.replace('::text','')])))};
        }
        const update=/^UPDATE cragkit_qdrant\.(\w+) SET /.exec(sql);
        if(update){
          const table=update[1];let rows=(state.tables[table]??[]).filter(row=>row.tenant_id===params[0]&&row.collection===params[1]&&row.document_id===params[2]);
          if(table==='publication_intents'){
            const id=sql.includes('state=$4')?params[4]:params[3];rows=rows.filter(row=>row.intent_id===id);
            for(const row of rows){row.state=sql.includes('state=$4')?params[3]:/state='([^']+)'/.exec(sql)[1];
              if(sql.includes('authority_committed=true'))row.authority_committed=true;if(sql.includes('replica_complete=true'))row.replica_complete=true;}
          }else if(table==='document_owners')for(const row of rows)Object.assign(row,{instance_id:params[3],intent_id:params[4],owner_token:params[5],backend_epoch:params[6]});
          else if(table==='dispatch_journal'){
            rows=rows.filter(row=>row.intent_id===params[3]&&row.dispatch_id===params[4]);for(const row of rows)Object.assign(row,{state:params[5],completion_sha256:params[6]});if(rows.some(row=>row.recovery))this.recoveryMarked=params[5];
          }else if(table==='documents'){
            if(sql.includes('SET active_generation_id'))for(const row of rows)row.active_generation_id=params[3];
            else {await state.onSecurityBody?.();for(const row of rows)Object.assign(row,{principal_ids:params[3],grant_ids:params[4],authorization_revision:params[5],mutation_epoch:params[6],language:params[7],kind:params[8],tag:params[9],tombstoned:params[10]});}
          }else if(table==='generations'){
            for(const row of rows){if(sql.includes('published=false')){if(row.generation_id!==params[3])row.published=false;}
              else if(row.generation_id===params[3]){row.published=true;row.ever_published=true;}}
          }
          return {rows:sql.includes('RETURNING document_id')?rows.map(row=>[row.document_id]):sql.includes('RETURNING dispatch_id')?rows.map(row=>[row.dispatch_id]):[]};
        }
        throw Error('unexpected synthetic SQL');
      }};
    state.clients.push(client);return client;
  }};
  const resource=new PoolResource(parse_pool_config({host:'host.invalid',dbname:'fixture',user:'writer',
    sslrootcert:'/fake/ca',passfile:'/fake/pass',release_timeout:.05,close_timeout:.1}),{pool});
  return {state,pool,resource,writer:new PostgresQdrantWriter(resource,config,'instance-fixture')};
}
function runtime(){
  const state={directories:new Set(),files:new Map(),pendingConfig:null,key:null,children:[],requests:[],collections:new Map(),
    nextPid:12000,listenerWrong:false,wait:null,stops:0,spawns:0,oldKeyAccepted:false,
    binaryHash:'830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3',binaryClosed:0};
  const mocks=[];
  const replace=(object,key,implementation)=>mocks.push(mock.method(object,key,implementation));
  replace(fs,'realpath',async path=>path);
  replace(fs,'mkdir',async path=>{if(state.directories.has(path))throw Object.assign(Error('private'),{code:'EEXIST'});state.directories.add(path);});
  replace(fs,'lstat',async path=>({dev:1,ino:path.length,uid:process.getuid(),size:path==='/owned/qdrant'?1:0,mode:path==='/owned/qdrant'?0o100700:0o40700,
    isFile:()=>path==='/owned/qdrant',isDirectory:()=>path!=='/owned/qdrant',isSymbolicLink:()=>false}));
  replace(fs,'open',async(path,flags,mode)=>{
    if(path==='/owned/qdrant'){
      let read=false;
      return {async read(buffer){if(read)return {bytesRead:0};read=true;buffer[0]=97;return {bytesRead:1};},async close(){state.binaryClosed++;}};
    }
    assert.equal(mode,0o600);
    return {async writeFile(value){state.files.set(path,value);},async sync(){},async close(){}};
  });
  replace(crypto,'createHash',()=>{const hash={update(){return hash;},digest(){return state.binaryHash;}};return hash;});
  replace(fs,'rename',async(from,to)=>{state.files.set(to,state.files.get(from));state.files.delete(from);state.pendingConfig=JSON.parse(state.files.get(to));});
  replace(net,'createServer',()=>{
    const server=new EventEmitter();server.listen=(_port,_host,callback)=>queueMicrotask(callback);
    server.address=()=>({port:32123});server.close=callback=>queueMicrotask(callback);return server;
  });
  replace(childProcess,'spawn',(binary,args,settings)=>{
    assert.equal(binary,'/owned/qdrant');assert.equal(args[0],'--config-path');
    assert.equal(Object.keys(settings.env).some(key=>key.startsWith('QDRANT')),false);
    assert.equal(JSON.stringify(args).includes(state.pendingConfig.service.api_key),false);
    const child=new EventEmitter();Object.assign(child,{pid:state.nextPid++,exitCode:null,signalCode:null});
    child.kill=signal=>{state.stops++;child.signalCode=signal;queueMicrotask(()=>child.emit('exit',null,signal));return true;};
    state.children.push(child);state.spawns++;state.key=state.pendingConfig.service.api_key;return child;
  });
  replace(childProcess,'execFile',(_binary,args,_options,callback)=>{
    const child={exitCode:0,signalCode:null,kill(){return true;}};
    queueMicrotask(()=>callback(null,'p'+args[3]+'\nn127.0.0.1:'+(state.listenerWrong?32124:32123)+'\n',''));
    return child;
  });
  replace(http,'request',(settings,callback)=>{
    const request=new EventEmitter();let body=Buffer.alloc(0),destroyed=false;
    request.write=value=>{body=Buffer.from(value);};
    request.destroy=()=>{destroyed=true;};
    request.end=()=>queueMicrotask(async()=>{
      state.waitStarted?.();
      if(state.wait)await state.wait;
      if(destroyed)return;
      state.requests.push({method:settings.method,path:settings.path,key:settings.headers['api-key']});
      let status=200,payload;
      const accepted=settings.headers['api-key']===state.key||state.oldKeyAccepted;
      const parsed=body.length?JSON.parse(body):null;
      const path=settings.path.split('?')[0];
      const parts=path.split('/');const name=parts[2];
      if(!accepted){status=401;payload={status:'error'};}
      else if(path==='/')payload={version:'1.20.0'};
      else if(path==='/cluster')payload={status:'ok',result:{status:'disabled'}};
      else if(path==='/collections')payload={status:'ok',result:{collections:[...state.collections.keys()].map(name=>({name}))}};
      else if(parts.length===3&&settings.method==='PUT'){
        state.collections.set(name,{params:{vectors:parsed.vectors,sparse_vectors:parsed.sparse_vectors??null,
          replication_factor:parsed.replication_factor,write_consistency_factor:parsed.write_consistency_factor},
          optimizer_config:parsed.optimizers_config,points:new Map()});payload={status:'ok',result:true};
      }else if(parts.length===3&&settings.method==='GET'){
        const collection=state.collections.get(name);
        payload={status:'ok',result:{status:'green',optimizer_status:'ok',config:{params:collection.params,optimizer_config:collection.optimizer_config}}};
      }else if(parts[3]==='points'&&settings.method==='PUT'){
        const collection=state.collections.get(name);for(const point of parsed.points)collection.points.set(point.id,point);
        payload={status:'ok',result:{status:'completed'}};
      }else if(parts[3]==='points'&&settings.method==='POST'){
        if(parts[4]==='scroll')payload={status:'ok',result:{points:[...state.collections.get(name).points.values()],next_page_offset:null}};
        else payload={status:'ok',result:parsed.ids.map(id=>state.collections.get(name).points.get(id)).filter(Boolean)};
      }else throw Error('unexpected synthetic HTTP path');
      const incoming=new EventEmitter();incoming.headers={};incoming.statusCode=status;incoming.destroy=()=>{};
      callback(incoming);queueMicrotask(()=>{incoming.emit('data',Buffer.from(JSON.stringify(payload)));incoming.emit('end');});
    });
    return request;
  });
  return {state,restore(){for(const item of mocks.reverse())item.mock.restore();}};
}
async function provision(admin,probe){
  await admin.request('PUT','/collections/'+config.physical_collection,{...options(),body:bytes({
    vectors:{dense:{size:1536,distance:'Cosine'}},sparse_vectors:{sparse:{}},optimizers_config:{prevent_unoptimized:false},
    replication_factor:1,write_consistency_factor:1})});
  await admin.request('PUT','/collections/'+probe.collection,{...options(),body:bytes(probe.collection_config)});
  await admin.request('PUT','/collections/'+probe.collection+'/points?wait=true&ordering=strong',{...options(),body:bytes({points:[probe.point]})});
}

const nativeDouble={skip:process.platform!=='darwin'||process.arch!=='arm64'};
async function scenario(tombstoned=false){
 const f=setup(),fake=runtime();
 const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-fixture',config);
 try{
  await f.writer.initialize(options());await f.writer.stage(prepare_stage(input()),scope,stageOpts());
  const security={action:tombstoned?'tombstone':'update_authorization',intent_id:'security-1',tenant_id:'tenant-a',collection:'docs',document_id:'doc-1',
   expected_authorization_revision:'auth-1',expected_mutation_epoch:1,authorization:{authorization_revision:'auth-2',principal_ids:['reader-b'],grant_ids:['grant-b'],language:null,kind:null,tag:null,tombstoned}};
  await f.writer.apply_security(security,scope,stageOpts());
  const trusted={...scope,authorization_revision:'auth-2'},owner={scope:trusted,collection:'docs',document_id:'doc-1',intent_id:'intent-2',owner_token:token},
   current={...owner,intent_id:'security-1',owner_token:'00000000-0000-4000-8000-000000000002'};
  const projection=await f.writer.project_security(current,options()),data=security_projection_data(projection,f.writer);
  await supervisor.initialize({...options(),provision});
  if(!tombstoned)for(const point of data.points)fake.state.collections.get(config.physical_collection).points.set(point.point_id,
   {id:point.point_id,payload:clone(point.payload),vector:{dense:[...point.dense.values],sparse:{indices:[...point.sparse.indices],values:[...point.sparse.values]}}});
  const proof=await supervisor.recover({recovery_id:'security-recovery',old_epoch:1,new_epoch:2},options());
  const verifier=new QdrantSecurityVerifier(f.writer,supervisor);
  return {...f,fake,supervisor,proof,verifier,owner,current,data,async close(){await verifier.close();await f.writer.close();await f.resource.close();await supervisor.close();fake.restore();}};
 }catch(error){await f.writer.close();await f.resource.close();await supervisor.close();fake.restore();throw error;}
}

test('security verifier constructor and dependency binding are local and reject nominal copies',async()=>{
 const f=setup(),supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-fixture',config);
 const verifier=new QdrantSecurityVerifier(f.writer,supervisor);
 try{
  assert.equal(f.state.queries.length,0);security_verifier_binding(verifier,f.writer,supervisor);
  class Derived extends QdrantSecurityVerifier {}
  assert.throws(()=>new Derived(f.writer,supervisor),InvalidRequest);
  for(const value of [{},Object.create(QdrantSecurityVerifier.prototype),new Proxy(verifier,{})])assert.throws(()=>security_verifier_binding(value,f.writer,supervisor),InvalidRequest);
  assert.throws(()=>new QdrantSecurityVerifier(Object.create(PostgresQdrantWriter.prototype),supervisor),InvalidRequest);
  assert.throws(()=>security_verifier_binding(verifier,f.writer,{}),InvalidRequest);
  await verifier.close();assert.throws(()=>security_verifier_binding(verifier,f.writer,supervisor),InvalidRequest);
  assert.equal(f.pool.ends,0);assert.equal(f.state.queries.length,0);
 }finally{await f.writer.close();await f.resource.close();await supervisor.close();}
});
for(const tombstoned of [false,true])test(`security receipt strict ${tombstoned?'absence':'current'} witness is bound to actual facade registry`,nativeDouble,async()=>{
 const f=await scenario(tombstoned);let receipt,escaped;
 try{
  await f.supervisor.control_session(async control=>{
   escaped=control;const lease=options(),budget=new SecurityReadbackBudget();
   receipt=await f.verifier.verify(f.proof,control,f.owner,f.current,lease,budget);
   const data=security_receipt_data(receipt,f.verifier,control,lease),physical=f.supervisor.recovery_binding(f.proof),attempt=data.attempt_binding;
   assert.equal(Object.keys(data).length,13);assert.equal(Object.isFrozen(data.witness),true);assert.equal(Object.isFrozen(data.witness[1]),true);
   assert.deepEqual(data.witness,['cragkit.qdrant.security-readback.v1',
    [physical.instance_id,physical.storage_identity,physical.supervisor_id,physical.recovery_id,'1','2',physical.credential_generation],
    [f.owner.intent_id,f.owner.owner_token,'2',attempt.dispatch_id,physical.recovery_id],String(data.activity),
    ['tenant-a','docs','doc-1',f.owner.intent_id,f.owner.owner_token],['tenant-a','reader-a',['grant-a'],'auth-2'],
    ['security-1',f.current.owner_token,f.data.intent_sha256,'auth-2','2',null,tombstoned?'true':'false',['reader-b'],['grant-b'],null,null,null],
    [f.data.inventory_sha256,f.data.generations.map(group=>[group.revision_id,group.generation_id,group.manifest_sha256,group.point_ids])],
    f.data.points.map(point=>[point.point_id,point.dense.input_sha256,point.sparse.input_sha256])]);
   assert.equal(data.sha256,createHash('sha256').update(Buffer.from(data.encoded_bytes)).digest('hex'));assert.equal(data.readback_sha256,data.sha256);
   assert.deepEqual(JSON.parse(Buffer.from(data.encoded_bytes)),data.witness);assert.ok(budget.remaining_calls<513);
   assert.throws(()=>security_receipt_data({...receipt},f.verifier,control,lease),InvalidRequest);
   assert.throws(()=>security_receipt_data(receipt,f.verifier,{...control},lease),InvalidRequest);
   assert.throws(()=>security_receipt_data(receipt,f.verifier,control,{deadline:lease.deadline+1}),InvalidRequest);
   assert.throws(()=>security_receipt_data(receipt,f.verifier,control,{...lease,signal:new AbortController().signal}),InvalidRequest);
   const attempt2=control.issue_recovery_attempt(f.proof,{intent_id:f.owner.intent_id,owner_token:f.owner.owner_token,epoch:2,recovery_id:'security-recovery',dispatch_id:'intervening'},lease);
   assert.throws(()=>security_receipt_data(receipt,f.verifier,control,lease),UnsupportedCapability);
   assert.ok(attempt2);
  });
  assert.throws(()=>security_receipt_data(receipt,f.verifier,escaped,options()),InvalidRequest);
 }finally{await f.close();}
});
for(const phase of ['close','source'])test(`security receipt rejects HTTP activity interposed during ${phase} await`,nativeDouble,async()=>{
 const f=await scenario();
 try{await f.supervisor.control_session(async control=>{
  if(phase==='source'){
   const validate=f.writer.validate_security_projection.bind(f.writer);
   f.writer.validate_security_projection=async(...args)=>{control.issue_recovery_attempt(f.proof,{intent_id:f.owner.intent_id,owner_token:token,epoch:2,recovery_id:'security-recovery',dispatch_id:'interposed-source'},options());await validate(...args);};
  }else{
   // Change an actual session request's completion path while the verifier owns its handle.
   const original=f.supervisor.attempt_binding.bind(f.supervisor);let sawFinal=false;
   f.supervisor.attempt_binding=attempt=>{const data=original(attempt);if(f.fake.state.requests.some(request=>request.path.endsWith('/scroll'))&&!sawFinal){sawFinal=true;queueMicrotask(()=>control.issue_recovery_attempt(f.proof,{intent_id:f.owner.intent_id,owner_token:token,epoch:2,recovery_id:'security-recovery',dispatch_id:'interposed-close'},options()));}return data;};
  }
  await assert.rejects(f.verifier.verify(f.proof,control,f.owner,f.current,options()),UnsupportedCapability);
 });}finally{await f.close();}
});
for(const fault of ['missing','stale','extra','vector','source'])test(`security ${fault} observation cannot mint receipt`,nativeDouble,async()=>{
 const f=await scenario();
 try{
  const points=f.fake.state.collections.get(config.physical_collection).points;
  if(fault==='missing')points.delete(f.data.point_ids[0]);
  if(fault==='stale')points.get(f.data.point_ids[0]).payload.authorization_revision='auth-1';
  if(fault==='extra'){const point=clone(points.values().next().value);point.id='00000000-0000-4000-8000-000000000099';points.set(point.id,point);}
  if(fault==='vector')points.get(f.data.point_ids[0]).vector.dense.fill(0);
  if(fault==='source')f.state.tables.documents[0].authorization_revision='auth-3';
  await f.supervisor.control_session(async control=>{
   await assert.rejects(f.verifier.verify(f.proof,control,f.owner,f.current,options()),fault==='source'?UnauthorizedScope:IntegrityViolation);
  });
 }finally{await f.close();}
});

test('security admission rejects wrong context/facade/proof before receipt work',nativeDouble,async()=>{
 const f=await scenario();
 try{await f.supervisor.control_session(async control=>{
  await assert.rejects(f.verifier.verify(f.proof,{...control},f.owner,f.current,options()),InvalidRequest);
  await assert.rejects(f.verifier.verify({...f.proof},control,f.owner,f.current,options()),UnsupportedCapability);
  await assert.rejects(f.verifier.verify(f.proof,control,{...f.owner,document_id:'foreign'},f.current,options()),InvalidRequest);
  const lease=options(),receipt=await f.verifier.verify(f.proof,control,f.owner,f.current,lease);
  await f.verifier.close();assert.throws(()=>security_receipt_data(receipt,f.verifier,control,lease),InvalidRequest);
 });}finally{await f.close();}
});

const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};
for(const mode of ['abort','deadline','close'])test(`security ${mode} holds admission until owned source work unwinds`,nativeDouble,async()=>{
 const f=await scenario(),started=deferred(),release=deferred(),controller=new AbortController();
 try{await f.supervisor.control_session(async control=>{
  const original=f.writer.project_security.bind(f.writer);
  f.writer.project_security=async(...args)=>{started.resolve();await release.promise;return original(...args);};
  const lease={deadline:now()+(mode==='deadline'?.02:5),signal:controller.signal};
  const work=f.verifier.verify(f.proof,control,f.owner,f.current,lease);
  const refusal=assert.rejects(work,mode==='deadline'?DeadlineExceeded:error=>error.name==='AbortError');
  await started.promise;
  let closing;
  if(mode==='abort')controller.abort();else if(mode==='close')closing=f.verifier.close();else await new Promise(resolve=>setTimeout(resolve,35));
  await assert.rejects(f.verifier.verify(f.proof,control,f.owner,f.current,options()),ProviderUnavailable);
  release.resolve();await refusal;if(closing)await closing;
  assert.equal(f.pool.ends,0);
 });}finally{release.resolve();await f.close();}
});

test('security stale source after strict observation cannot produce a receipt',nativeDouble,async()=>{
 const f=await scenario();
 try{await f.supervisor.control_session(async control=>{
  const original=f.writer.validate_security_projection.bind(f.writer);
  f.writer.validate_security_projection=async(...args)=>{f.state.tables.documents[0].tag='changed-after-observation';return original(...args);};
  await assert.rejects(f.verifier.verify(f.proof,control,f.owner,f.current,options()),UnauthorizedScope);
 });}finally{await f.close();}
});

test('security receipt access observes original caller cancellation and forged verifier',nativeDouble,async()=>{
 const f=await scenario();
 try{await f.supervisor.control_session(async control=>{
  const controller=new AbortController(),lease={...options(),signal:controller.signal};
  const receipt=await f.verifier.verify(f.proof,control,f.owner,f.current,lease);
  assert.throws(()=>security_receipt_data(receipt,Object.create(QdrantSecurityVerifier.prototype),control,lease),InvalidRequest);
  controller.abort();assert.throws(()=>security_receipt_data(receipt,f.verifier,control,lease),error=>error.name==='AbortError');
 });}finally{await f.close();}
});
