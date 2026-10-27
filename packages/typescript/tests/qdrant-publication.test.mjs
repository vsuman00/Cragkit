import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {PoolResource,parse_pool_config,now} from '../dist/postgres-pool.js';
import {ExecutionLedger} from '../dist/execution.js';
import {QdrantPublicationManager,PostgresQdrantPublicationAuthority,ManagedQdrantPublicationTransport,
  PostgresQdrantWriter,PostgresQdrantRecovery,ManagedQdrantSupervisor,QdrantReconciliationVerifier} from '../dist/qdrant-publication.js';
import {WRITER_ROLE_SQL,prepare_stage} from '../dist/qdrant-writer.js';
import {AUTHORITY_HISTORY_SQL,AUTHORITY_PUBLICATION_HISTORY,AUTHORITY_PUBLICATION_CATALOG_SQL,
  AUTHORITY_FINGERPRINT_SQL,EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT} from '../dist/qdrant-authority.js';
import {InvalidRequest,UnauthorizedScope,UnsupportedCapability,ProviderUnavailable,IndexNotReady,IntegrityViolation} from '../dist/errors.js';

const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_publication.json',import.meta.url),'utf8'));
const config={...fixture.physical,dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse};
const scope={tenant_id:'tenant-a',principal_id:'reader-a',grant_ids:['grant-a'],authorization_revision:'auth-1'};
const ref={collection:'docs',document_id:'doc-1',intent_id:'intent-2'};
const options=()=>({deadline:now()+5});
const ledger=(limits={})=>new ExecutionLedger({limits:{max_provider_calls:0,max_candidates:1,max_attempts:1,...limits},deadline:now()+5});
const bytes=value=>Object.freeze(Array.from(Buffer.from(JSON.stringify(value))));
function clone(value){
  if(Buffer.isBuffer(value))return Buffer.from(value);
  if(Array.isArray(value))return value.map(clone);
  if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,clone(item)]));
  return value;
}
function change(){
  return {manifest:{...fixture.physical,tenant_id:scope.tenant_id,collection:ref.collection,document_id:ref.document_id,revision_id:fixture.source_revision.revision_id,
    generation_id:fixture.intent.generation_id,source_sha256:fixture.source_revision.source_sha256,source_bytes:fixture.source_revision.source_bytes,
    source_locator:fixture.source_revision.source_locator,parser_id:fixture.source_revision.parser_id,chunker_profile:fixture.intent.chunker_profile,
    dense_profile:clone(config.dense_profile),sparse_profile:clone(config.sparse_profile),members:fixture.members.map(member=>({
      chunk_id:member.chunk_id,point_id:member.point_id,start_byte:member.start_byte,end_byte:member.end_byte,text_sha256:member.text_sha256,
      dense_input_sha256:member.dense.vector_sha256,sparse_input_sha256:member.sparse.vector_sha256}))},
    intent:{intent_id:ref.intent_id,tenant_id:scope.tenant_id,collection:ref.collection,document_id:ref.document_id,
      manifest_sha256:fixture.intent.manifest_sha256,expected_active_generation_id:null,expected_authorization_revision:'auth-1',expected_mutation_epoch:1,
      initial_authorization:{authorization_revision:'auth-1',principal_ids:['reader-a'],grant_ids:['grant-a'],language:'en',kind:'guide',tag:'reference',tombstoned:false}},
    canonical_text:fixture.source_revision.canonical_utf8.value,
    dense_vectors:fixture.members.map(member=>Array.from({length:1536},(_,i)=>i===member.dense.basis_index?1:0)),
    sparse_vectors:fixture.members.map(member=>({indices:[...member.sparse.indices],values:[...member.sparse.values]}))};
}

/** SQL and controller method doubles exercise the manager, not native proofs. */
function setup(authorize=async()=>true){
  const state={queries:[],clients:[],http:[],points:new Map(),attempts:new Map(),handles:0,authorizations:0,
    callback:authorize,session:false,ackMode:null,afterPut:null,tables:{backend_instances:[{instance_id:'instance-fixture',backend_namespace:config.backend_namespace,
      storage_identity:'storage-fixture',supervisor_id:'supervisor-fixture',epoch:1,state:'open',recovery_id:null}]}};
  const keyFields={documents:['tenant_id','collection','document_id'],document_revisions:['tenant_id','collection','document_id','revision_id'],
    generations:['tenant_id','collection','document_id','generation_id'],members:['tenant_id','collection','document_id','revision_id','generation_id','chunk_id'],
    publication_intents:['tenant_id','collection','document_id','intent_id'],point_claims:['backend_namespace','physical_collection','collection_incarnation','point_id'],
    vector_replays:['tenant_id','collection','document_id','revision_id','generation_id','chunk_id'],document_owners:['tenant_id','collection','document_id'],
    dispatch_journal:['tenant_id','collection','document_id','intent_id','dispatch_id'],dispatch_points:['tenant_id','collection','document_id','intent_id','dispatch_id','point_id'],
    preparations:['tenant_id','collection','document_id','intent_id']};
  const pool={ended:0,async end(){this.ended++;},async connect(){
    const client={status:'I',released:false,destroyed:false,getTransactionStatus(){return this.status;},
      release(destroy=false){this.released=true;this.destroyed=destroy;},async query(query){
        const sql=query.text,p=query.values??[];state.queries.push(sql);
        if(sql.startsWith('BEGIN')){this.before=clone(state.tables);this.status='T';return {rows:[]};}
        if(sql==='ROLLBACK'){state.tables=this.before;this.status='I';return {rows:[]};}
        if(sql==='COMMIT'){this.status='I';return {rows:[]};}
        if(sql.startsWith('SET ')||sql.startsWith('SELECT set_config'))return {rows:[]};
        if(sql===WRITER_ROLE_SQL||sql===AUTHORITY_PUBLICATION_CATALOG_SQL)return {rows:[[true]]};
        if(sql===AUTHORITY_HISTORY_SQL)return {rows:AUTHORITY_PUBLICATION_HISTORY.map(row=>[...row])};
        if(sql===AUTHORITY_FINGERPRINT_SQL)return {rows:[[EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT]]};
        const insert=/^INSERT INTO cragkit_qdrant\.(\w+) \(([^)]+)\)/.exec(sql);
        if(insert){
          const [,table,columns]=insert;
          const row=Object.fromEntries(columns.split(',').map((column,i)=>[column,['dense_profile','sparse_profile'].includes(column)&&p[i]!==null?JSON.parse(p[i]):clone(p[i])]));
          const rows=state.tables[table]??=[];
          if(rows.some(old=>keyFields[table].every(key=>old[key]===row[key])))return {rows:[]};
          if(table==='documents')Object.assign(row,{active_generation_id:null,...row});
          if(table==='generations')Object.assign(row,{published:false,ever_published:false,...row});
          if(table==='publication_intents')Object.assign(row,{state:'staged',authority_committed:false,replica_complete:false,purge_complete:false,...row});
          if(table==='dispatch_journal')Object.assign(row,{state:'reserved',recovery:false,completion_sha256:null,...row});
          rows.push(row);return {rows:sql.includes('RETURNING document_id')?[[row.document_id]]:[]};
        }
        const select=/^SELECT (.+?) FROM cragkit_qdrant\.(\w+) WHERE /.exec(sql);
        if(select){
          const [,columns,table]=select;
          let rows=(state.tables[table]??[]).filter(row=>table==='backend_instances'?row.instance_id===p[0]:
            row.tenant_id===p[0]&&row.collection===p[1]&&row.document_id===p[2]);
          for(const field of ['intent_id','dispatch_id','revision_id','generation_id','chunk_id','point_id',
            'payload_sha256','backend_namespace','physical_collection','collection_incarnation']){
            const parameter=new RegExp('(?: AND |\\()'+field+'=\\$(\\d+)(?!\\d)').exec(sql);
            if(parameter)rows=rows.filter(row=>row[field]===p[Number(parameter[1])-1]);
          }
          if(sql.includes('point_id=ANY'))rows=rows.filter(row=>p[3].includes(row.point_id));
          if(sql.includes("state<>'settled'"))rows=rows.filter(row=>row.state!=='settled');
          if(sql.includes('manifest_sha256<>$6'))rows=rows.filter(row=>row.manifest_sha256!==p[5]);
          return {rows:rows.slice(0,Number(/LIMIT (\d+)/.exec(sql)?.[1]??65)).map(row=>columns.split(',').map(key=>clone(row[key.replace('::text','')])))};
        }
        const update=/^UPDATE cragkit_qdrant\.(\w+) SET /.exec(sql);
        if(update){
          const table=update[1];let rows=(state.tables[table]??[]).filter(row=>row.tenant_id===p[0]&&row.collection===p[1]&&row.document_id===p[2]);
          if(table==='publication_intents'){
            rows=rows.filter(row=>row.intent_id===(sql.includes('state=$4')?p[4]:p[3]));
            for(const row of rows){row.state=sql.includes('state=$4')?p[3]:/state='([^']+)'/.exec(sql)[1];
              if(sql.includes('authority_committed=true'))row.authority_committed=true;
              if(sql.includes('replica_complete=true'))row.replica_complete=true;}
          }else if(table==='document_owners')for(const row of rows)Object.assign(row,{instance_id:p[3],intent_id:p[4],owner_token:p[5],backend_epoch:p[6]});
          else if(table==='dispatch_journal'){
            rows=rows.filter(row=>row.intent_id===p[3]&&row.dispatch_id===p[4]);
            for(const row of rows)Object.assign(row,{state:p[5],completion_sha256:p[6]});
          }else if(table==='documents')for(const row of rows)row.active_generation_id=p[3];
          else if(table==='generations')for(const row of rows){
            if(sql.includes('published=false')){if(row.generation_id!==p[3])row.published=false;}
            else if(row.generation_id===p[3]){row.published=true;row.ever_published=true;}
          }
          return {rows:sql.includes('RETURNING document_id')?rows.map(row=>[row.document_id]):[]};
        }
        throw Error('Unexpected SQL double statement');
      }};
    state.clients.push(client);return client;
  }};
  const resource=new PoolResource(parse_pool_config({host:'host.invalid',dbname:'fixture',user:'writer',sslrootcert:'/fake/ca',passfile:'/fake/pass',release_timeout:.05,close_timeout:.1}),{pool});
  const writer=new PostgresQdrantWriter(resource,config,'instance-fixture');
  const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-fixture',config);
  supervisor.profile_binding=()=>({instance_id:'instance-fixture',backend_namespace:config.backend_namespace,storage_identity:'storage-fixture',
    supervisor_id:'supervisor-fixture',epoch:1,credential_generation:'credential-1',recovery:null,sealed:false,alive:true});
  supervisor.issue_attempt=input=>{
    assert.equal(state.session,false);const attempt=Object.freeze({});
    state.attempts.set(attempt,{instance_id:'instance-fixture',storage_identity:'storage-fixture',supervisor_id:'supervisor-fixture',credential_generation:'credential-1',...input});
    return attempt;
  };
  supervisor.attempt_binding=attempt=>{const binding=state.attempts.get(attempt);if(!binding)throw new InvalidRequest();return binding;};
  supervisor.recover=async()=>{if(state.session)throw new ProviderUnavailable();throw new UnsupportedCapability();};
  supervisor.control_session=async body=>{
    if(state.session)throw new ProviderUnavailable();state.session=true;
    try{return await body(Object.freeze({}));}finally{state.session=false;}
  };
  supervisor.transport_for=attempt=>{
    supervisor.attempt_binding(attempt);state.handles++;
    let closed=false;
    return {async close(){if(!closed){closed=true;state.handles--;}},async request(method,path,opts){
      assert.equal(state.session,false,'no HTTP inside finalization session');
      assert.ok(state.clients.every(client=>client.released&&(client.destroyed||client.status==='I')),'no SQL lease across HTTP');
      const body=JSON.parse(Buffer.from(opts.body));state.http.push({method,path,body});
      if(method==='PUT'){
        for(const point of body.points)state.points.set(point.id,clone(point));
        state.afterPut?.();
        if(state.ackMode==='lost')throw new ProviderUnavailable();
        return bytes({status:'ok',result:{operation_id:1,status:state.ackMode==='incomplete'?'acknowledged':'completed'}});
      }
      const points=[...state.points.values()].filter(point=>path.endsWith('/scroll')||body.ids.includes(point.id));
      return bytes({status:'ok',result:path.endsWith('/scroll')?{points,next_page_offset:null}:points});
    }};
  };
  const verifier=new QdrantReconciliationVerifier(writer,supervisor);
  const recovery=new PostgresQdrantRecovery(resource,config,supervisor,verifier);
  recovery.initialize=async()=>{};
  const authority=new PostgresQdrantPublicationAuthority(writer,recovery);
  const transport=new ManagedQdrantPublicationTransport(supervisor);
  const authorizer=async(...args)=>{state.authorizations++;assert.ok(state.clients.every(client=>client.released),'callback outside SQL');return state.callback(...args);};
  const manager=new QdrantPublicationManager(authority,transport,config,supervisor,authorizer);
  return {state,writer,supervisor,recovery,authority,transport,manager,resource,pool,authorizer,
    async close(){await manager.close();await writer.close();await recovery.close();await verifier.close();await resource.close();await supervisor.close();}};
}

test('explicit dependency graph is inert and initialization is required',async()=>{
  const f=setup();
  try{
    assert.equal(f.state.queries.length,0);
    assert.equal(f.state.http.length,0);
    await assert.rejects(f.manager.stage(change(),scope,ledger(),options()),IndexNotReady);
    assert.throws(()=>new QdrantPublicationManager(f.writer,f.transport,config,f.supervisor,f.authorizer),InvalidRequest);
    assert.throws(()=>new QdrantPublicationManager(f.authority,f.transport,{...config,physical_collection:'other'},f.supervisor,f.authorizer),UnsupportedCapability);
    const phantom=Object.create(PostgresQdrantRecovery.prototype);
    const holder=new PostgresQdrantPublicationAuthority(f.writer,phantom);
    assert.throws(()=>new QdrantPublicationManager(holder,f.transport,config,f.supervisor,f.authorizer),InvalidRequest);
    assert.throws(()=>new ManagedQdrantPublicationTransport(new Proxy(f.supervisor,{})),InvalidRequest);
    assert.equal(f.state.queries.length,0);
    await f.manager.initialize(options());
  }finally{await f.close();}
});

test('stage performs no HTTP and publish settles exact writes before a closed nine-field outcome',async()=>{
  const f=setup();
  try{
    await f.manager.initialize(options());
    const stagedLedger=ledger();
    const staged=await f.manager.stage(change(),scope,stagedLedger,options());
    assert.equal(staged.state,'staged');
    assert.deepEqual(f.state.tables.point_claims.map(claim=>claim.point_id).sort(),fixture.members.map(member=>member.point_id).sort(),
      'SQL double must preserve distinct physical point predicates for both staged chunks');
    assert.equal(f.state.http.length,0);
    const publishedLedger=ledger();
    const published=await f.manager.publish(ref,scope,publishedLedger,options());
    assert.deepEqual(Object.keys(published).sort(),['intent_id','operation','state','revision_id','generation_id','authority_committed','replica_complete','published','purge_complete'].sort());
    assert.equal(published.state,'published');
    assert.equal(published.operation,'publish');
    assert.ok(Object.isFrozen(published));
    assert.equal(f.state.http.filter(request=>request.method==='PUT').length,1);
    assert.equal(f.state.tables.dispatch_journal[0].state,'settled');
    assert.equal(f.state.tables.documents[0].active_generation_id,fixture.intent.generation_id);
    assert.equal(f.state.handles,0);
    assert.deepEqual(publishedLedger.snapshot(),{provider_calls:0,candidates:0,attempts:1,input_tokens:0,output_tokens:0,cost_usd:0,cost_kind:'known',pending:0});
    const before=f.state.http.length;
    f.state.tables.documents[0].authorization_revision='auth-2';
    f.state.tables.documents[0].mutation_epoch=2;
    const fresh={...scope,authorization_revision:'auth-2'};
    assert.equal((await f.manager.stage(change(),fresh,ledger(),options())).published,true);
    assert.equal((await f.manager.publish(ref,fresh,ledger(),options())).published,true);
    assert.equal(f.state.http.length,before);
    assert.equal(f.state.tables.documents[0].authorization_revision,'auth-2');
  }finally{await f.close();}
});

test('callback denial, malformed result and ledger bounds cause no source or HTTP mutation',async()=>{
  for(const [callback,error] of [[async()=>false,UnauthorizedScope],[async()=>1,InvalidRequest],[async()=>{throw Error('private');},ProviderUnavailable]]){
    const f=setup(callback);
    try{
      await f.manager.initialize(options());
      await assert.rejects(f.manager.stage(change(),scope,ledger(),options()),error);
      assert.equal(f.state.tables.documents,undefined);
      assert.equal(f.state.http.length,0);
    }finally{await f.close();}
  }
  const f=setup();
  try{
    await f.manager.initialize(options());
    const exhausted=ledger();
    const prior=exhausted.reserve({attempts:1});exhausted.dispatch(prior);exhausted.reconcile(prior);
    await assert.rejects(f.manager.stage(change(),scope,exhausted,options()),error=>error.name==='BudgetExhausted');
    assert.equal(f.state.authorizations,0);
    await assert.rejects(f.manager.publish({...ref,owner_token:'forged'},scope,ledger(),options()),InvalidRequest);
  }finally{await f.close();}
});

test('SQL acknowledgment reconciliation never repeats a native HTTP write',async()=>{
  for(const name of ['reserve_dispatch','mark_dispatched','settle_dispatch','prepare','publish']){
    const f=setup();
    try{
      await f.manager.initialize(options());
      await f.manager.stage(change(),scope,ledger(),options());
      const actual=f.writer[name].bind(f.writer);
      let dropped=false;
      f.writer[name]=async(...args)=>{
        const result=await actual(...args);
        if(!dropped){dropped=true;throw new ProviderUnavailable();}
        return result;
      };
      const result=await f.manager.publish(ref,scope,ledger(),options());
      assert.equal(result.state,'published',name);
      assert.equal(f.state.http.filter(request=>request.method==='PUT').length,1,name);
      assert.equal(f.state.tables.dispatch_journal.length,1,name);
    }finally{await f.close();}
  }
});

test('lost or incomplete HTTP ACK leaves uncertainty and a retry cannot resend',async()=>{
  for(const mode of ['lost','incomplete']){
    const f=setup();
    try{
      await f.manager.initialize(options());
      await f.manager.stage(change(),scope,ledger(),options());
      f.state.ackMode=mode;
      await assert.rejects(f.manager.publish(ref,scope,ledger(),options()),mode==='lost'?ProviderUnavailable:IntegrityViolation);
      assert.equal(f.state.tables.dispatch_journal[0].state,'unknown');
      assert.equal(f.state.tables.documents[0].active_generation_id,null);
      f.state.ackMode=null;
      await assert.rejects(f.manager.publish(ref,scope,ledger(),options()),ProviderUnavailable);
      assert.equal(f.state.http.filter(request=>request.method==='PUT').length,1);
    }finally{await f.close();}
  }
});

test('same-epoch prepared restart verifies the original witness without rewriting or replacing preparation',async()=>{
  const f=setup();
  let resumed;
  try{
    await f.manager.initialize(options());
    await f.manager.stage(change(),scope,ledger(),options());
    const actual=f.writer.publish.bind(f.writer);
    f.writer.publish=async()=>{throw new ProviderUnavailable();};
    await assert.rejects(f.manager.publish(ref,scope,ledger(),options()),ProviderUnavailable);
    assert.equal(f.state.tables.publication_intents[0].state,'prepared');
    const original=clone(f.state.tables.preparations[0]);
    const puts=f.state.http.filter(request=>request.method==='PUT').length;
    await f.manager.close();
    f.writer.publish=actual;
    resumed=new QdrantPublicationManager(f.authority,f.transport,config,f.supervisor,f.authorizer);
    await resumed.initialize(options());
    assert.equal((await resumed.publish(ref,scope,ledger(),options())).state,'published');
    assert.equal(f.state.http.filter(request=>request.method==='PUT').length,puts);
    assert.deepEqual(f.state.tables.preparations[0],original);
  }finally{await resumed?.close();await f.close();}
});

test('finalization session excludes lifecycle changes and final CAS persists late revocation',async()=>{
  const f=setup();
  try{
    await f.manager.initialize(options());
    await f.manager.stage(change(),scope,ledger(),options());
    let challenged=false;
    f.state.callback=async()=>{
      if(f.state.session){
        await assert.rejects(f.supervisor.recover({},options()),ProviderUnavailable);
        challenged=true;
        if(f.state.tables.publication_intents[0].state==='prepared'){
          Object.assign(f.state.tables.documents[0],{authorization_revision:'auth-2',mutation_epoch:2});
        }
      }
      return true;
    };
    const result=await f.manager.publish(ref,scope,ledger(),options());
    assert.equal(challenged,true);
    assert.equal(result.state,'denied');
    assert.equal(f.state.tables.documents[0].active_generation_id,null);
    assert.equal(f.state.session,false);
  }finally{await f.close();}
});

test('durable preparation terminal outcomes return before another callback or publication call',async()=>{
  for(const terminal of ['denied','conflict','published']){
    const f=setup();
    try{
      await f.manager.initialize(options());
      await f.manager.stage(change(),scope,ledger(),options());
      const actualPrepare=f.writer.prepare.bind(f.writer);
      const actualPublish=f.writer.publish.bind(f.writer);
      let publishCalls=0;
      f.writer.publish=async(...args)=>{publishCalls++;return actualPublish(...args);};
      f.writer.prepare=async(...args)=>{
        if(terminal==='denied')f.state.tables.documents[0].mutation_epoch=2;
        if(terminal==='conflict')f.state.tables.documents[0].active_generation_id='newer-winner';
        const prepared=await actualPrepare(...args);
        return terminal==='published'?actualPublish(args[0],args[2]):prepared;
      };
      f.state.callback=async()=>{
        const state=f.state.tables.publication_intents?.[0]?.state;
        if(['denied','conflict','published'].includes(state))throw Error('callback after durable terminal outcome');
        return true;
      };
      const outcome=await f.manager.publish(ref,scope,ledger(),options());
      assert.equal(outcome.state,terminal);
      assert.equal(publishCalls,0,'manager must not repeat publication after terminal prepare outcome');
      assert.equal(f.state.tables.documents[0].active_generation_id,
        terminal==='published'?fixture.intent.generation_id:terminal==='conflict'?'newer-winner':null);
    }finally{await f.close();}
  }
});

test('cancellation keeps admission until callback unwind and close preserves borrowed dependencies',async()=>{
  const f=setup();
  let release;
  try{
    await f.manager.initialize(options());
    let entered;
    const started=new Promise(resolve=>{entered=resolve;});
    const wait=new Promise(resolve=>{release=resolve;});
    f.state.callback=async()=>{entered();await wait;return true;};
    const abort=new AbortController();
    const pending=f.manager.stage(change(),scope,ledger(),{...options(),signal:abort.signal});
    await started;
    abort.abort();
    await assert.rejects(f.manager.stage(change(),scope,ledger(),options()),ProviderUnavailable);
    const closing=f.manager.close();
    release();
    await assert.rejects(pending,error=>error.name==='AbortError');
    await closing;
    assert.equal(f.state.tables.documents,undefined);
    assert.equal(f.pool.ended,0);
    assert.equal(f.state.handles,0);
    await assert.rejects(f.manager.publish(ref,scope,ledger(),options()),ProviderUnavailable);
    assert.equal((await f.writer.manager_snapshot({...ref,scope,owner_token:'00000000-0000-4000-8000-000000000001'},options())).intent,null);
  }finally{release?.();await f.close();}
});

test('borrowed transport factory close refuses new sessions without closing the supervisor',async()=>{
  const f=setup();
  try{
    await f.manager.initialize(options());
    await f.manager.stage(change(),scope,ledger(),options());
    await f.transport.close();
    await f.transport.close();
    await assert.rejects(f.manager.publish(ref,scope,ledger(),options()),ProviderUnavailable);
    assert.equal(f.state.http.length,0);
    assert.equal(f.state.handles,0);
    assert.equal(f.supervisor.profile_binding(config).alive,true);
  }finally{await f.close();}
});
