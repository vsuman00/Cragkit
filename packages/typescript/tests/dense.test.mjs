import test from 'node:test';
import assert from 'node:assert/strict';
import { PoolResource, parse_pool_config, now } from '../dist/postgres-pool.js';
import { PostgresSession, EXPECTED_HISTORY, _ROLE_SQL, _CATALOG_SQL, _HISTORY_SQL, _COLLECTION_SQL, _DENSE_SQL, _SOURCE_SQL, _LEXICAL_SQL } from '../dist/postgres-session.js';
import { EXPECTED_VECTOR_HISTORY, _VECTOR_CAPABILITY_SQL, _SETUP_HISTORY_SQL, _PROFILE_SQL } from '../dist/vector-ingestion.js';
import { FAKE_PROFILE, OPENAI_PROFILE } from '../dist/embeddings.js';
import { InvalidRequest, EmbeddingProfileMismatch, IntegrityViolation, UnauthorizedScope, UnsupportedCapability, DeadlineExceeded, ProviderUnavailable } from '../dist/errors.js';

const batch = () => ({ profile: {...FAKE_PROFILE}, vectors: [[1, ...Array(1535).fill(0)]], usage: {prompt_tokens:1,total_tokens:1,cost_usd:0,cost_kind:'known'},provider_calls:1,synthetic:true });
const row = () => ['tenant','collection','doc','revision','generation','chunk','0','4','a'.repeat(64),0,'fake_embedding_1536_v1','native_fts.v1'];
function fixture(request={}) {
  const client={ status:'I',queries:[],rows:[row()],capability:[[true]],history:EXPECTED_VECTOR_HISTORY,profiles:[[...Object.values(FAKE_PROFILE),'chunk_vectors_fake_1536']],hook:null,
    getTransactionStatus(){return this.status;},release(){},async query(q){
      this.queries.push(q); if(q.text.startsWith('BEGIN'))this.status='T';if(q.text==='ROLLBACK')this.status='I';
      if(q.text.startsWith(_DENSE_SQL.split('{predicate}')[0])){if(this.hook)await this.hook(q);return {rows:this.rows};}
      if(q.text.startsWith(_SOURCE_SQL.split('{predicate}')[0]))return {rows:[]};
      const rows=q.text===_ROLE_SQL||q.text===_CATALOG_SQL?[[true]]:q.text===_HISTORY_SQL?EXPECTED_HISTORY:q.text===_COLLECTION_SQL?[['0.1','native_fts.v1']]:q.text===_VECTOR_CAPABILITY_SQL?this.capability:q.text===_SETUP_HISTORY_SQL?this.history:q.text===_PROFILE_SQL?this.profiles:[];
      return {rows};
    }};
  const resource=new PoolResource(parse_pool_config({host:'synthetic.invalid',dbname:'synthetic',user:'reader',sslrootcert:'/synthetic/ca',passfile:'/synthetic/pass'}),{pool:{connect:async()=>client,end:async()=>{}}});
  const session=new PostgresSession(resource);
  const run=(body,extra={})=>session.transaction({query:'synthetic',collection:'collection',...request},{deadline:now()+2,scope:{tenant_id:'tenant',principal_id:'principal',authorization_revision:'authorization',grant_ids:['grant']},...extra},body);
  const denseQueries=()=>client.queries.filter(q=>q.text.startsWith(_DENSE_SQL.split('{predicate}')[0]));
  return {client,resource,run,denseQueries};
}
test('dense binds complete scope and filters before bounded ranking; immutable rows retain distance semantics',async()=>{
  const f=fixture({limits:{max_candidates:2},required_filters:[{field:'document_id',op:'eq',value:"doc' --"}]});
  try {await f.run(async h=>{
    const result=await h.dense_candidates(batch(),{limit:5});assert.equal(result[0].score,0);assert.equal(result[0].start_byte,0);
    assert.equal(result[0].score_kind,'cosine_distance');assert.equal(result[0].score_direction,'lower_is_better');assert.ok(Object.isFrozen(result)&&Object.isFrozen(result[0]));
  });const q=f.denseQueries()[0];assert.deepEqual(q.values.slice(1),['fake_embedding_1536_v1','tenant','collection','authorization','authorization','principal',['grant'],"doc' --",2]);
  assert.match(q.text,/eligible AS MATERIALIZED/);assert.match(q.text,/d.document_id = \$9/);assert.match(q.text,/LIMIT \$10/);assert.ok(q.text.indexOf('d.document_id = $9')<q.text.indexOf('ORDER BY distance'));
  } finally {await f.resource.close();}
});
const invalids=[['missing batch field',b=>{delete b.provider_calls;},InvalidRequest],['unknown field',b=>{b.extra=1;},InvalidRequest],['no vectors',b=>{b.vectors=[];},InvalidRequest],['multiple vectors',b=>{b.vectors.push([...b.vectors[0]]);},InvalidRequest],['dimension',b=>{b.vectors[0].pop();},EmbeddingProfileMismatch],['same dimension profile',b=>{b.profile={...OPENAI_PROFILE};b.synthetic=false;},EmbeddingProfileMismatch],['zero norm',b=>{b.vectors[0].fill(0);},InvalidRequest],['nonunit',b=>{b.vectors[0][0]=2;},InvalidRequest],['nonfinite',b=>{b.vectors[0][0]=Infinity;},InvalidRequest],['synthetic',b=>{b.synthetic=false;},InvalidRequest],['bad usage',b=>{b.usage.extra=1;},InvalidRequest],['getter',b=>{Object.defineProperty(b,'synthetic',{enumerable:true,get(){throw Error('getter');}});},InvalidRequest],['sparse',b=>{delete b.vectors[0][1];},InvalidRequest]];
for(const [name,mutate,kind] of invalids)test(`dense rejects ${name} before capability/search`,async()=>{const f=fixture();try{await f.run(async h=>{const b=batch();mutate(b);const count=f.client.queries.length;await assert.rejects(h.dense_candidates(b),kind);assert.equal(f.client.queries.length,count);});}finally{await f.resource.close();}});
for(const options of [null,[],{limit:0},{limit:1001},{limit:true},{extra:1}])test(`dense rejects options ${JSON.stringify(options)}`,async()=>{const f=fixture();try{await f.run(h=>assert.rejects(h.dense_candidates(batch(),options),InvalidRequest));}finally{await f.resource.close();}});
for(const [name,change,kind] of [
  ['shape',r=>r.pop(),IntegrityViolation],['profile',r=>{r[10]='other';},UnsupportedCapability],['lexical profile',r=>{r[11]='other';},UnsupportedCapability],['scope',r=>{r[0]='other';},IntegrityViolation],['blank identity',r=>{r[2]=' ';},IntegrityViolation],['unsafe span',r=>{r[7]='9007199254740992';},IntegrityViolation],['reversed span',r=>{r[6]=4;r[7]=4;},IntegrityViolation],['negative score',r=>{r[9]=-1;},IntegrityViolation],['large score',r=>{r[9]=2.1;},IntegrityViolation],['nonfinite score',r=>{r[9]=NaN;},IntegrityViolation],
])test(`dense row rejects ${name}`,async()=>{const f=fixture();change(f.client.rows[0]);try{await assert.rejects(f.run(h=>h.dense_candidates(batch())),kind);}finally{await f.resource.close();}});
for(const [name,field,value] of [['capability','capability',[[false]]],['history','history',[]],['registry','profiles',[]]])test(`dense rejects ${name} without search; lexical remains available`,async()=>{const f=fixture();f.client[field]=value;try{await f.run(async h=>{await assert.rejects(h.dense_candidates(batch()),UnsupportedCapability);assert.deepEqual(await h.lexical_candidates(),[]);});assert.equal(f.denseQueries().length,0);}finally{await f.resource.close();}});
test('duplicate and over-limit rows fail closed',async()=>{const f=fixture();try{f.client.rows=[row(),row()];await assert.rejects(f.run(h=>h.dense_candidates(batch())),IntegrityViolation);await assert.rejects(f.run(h=>h.dense_candidates(batch(),{limit:1})),IntegrityViolation);}finally{await f.resource.close();}});
test('batch snapshot precedes first await; busy calls fail and handle expires',async()=>{const f=fixture();let saved;try{await f.run(async h=>{saved=h;const b=batch();const pending=h.dense_candidates(b);b.vectors[0][0]=-1;b.profile.model='changed';await assert.rejects(h.lexical_candidates(),InvalidRequest);await pending;assert.equal(JSON.parse(f.denseQueries()[0].values[0])[0],1);await h.dense_candidates(batch());});await assert.rejects(saved.dense_candidates(batch()),InvalidRequest);}finally{await f.resource.close();}});
test('source release validates dense metadata before projecting and still reauthorizes',async()=>{const f=fixture();try{await f.run(async h=>{const [candidate]=await h.dense_candidates(batch());for(const changed of [{score_kind:'other'},{score_direction:'higher_is_better'},{embedding_profile:'other'},{score:3},{extra:1}])await assert.rejects(h.fetch_evidence({...candidate,...changed},{max_source_bytes:4}),InvalidRequest);assert.equal((await h.fetch_evidence(candidate,{max_source_bytes:4})).state,'unavailable');});}finally{await f.resource.close();}});
test('dense driver failure retains operational type and never returns empty evidence',async()=>{for(const [code,kind] of [['57014',DeadlineExceeded],['XX000',ProviderUnavailable],['42501',UnauthorizedScope]]){const f=fixture();f.client.hook=()=>{throw Object.assign(Error('private'),{code});};try{await assert.rejects(f.run(h=>h.dense_candidates(batch())),e=>e instanceof kind&&!String(e).includes('private'));}finally{await f.resource.close();}}});
test('abort cancels dense selection and subsequent transaction can reuse resource',async()=>{const f=fixture();const controller=new AbortController();f.client.hook=()=>controller.abort();try{await assert.rejects(f.run(h=>h.dense_candidates(batch()),{signal:controller.signal}),e=>e.name==='AbortError');f.client.status='I';f.client.hook=null;await f.run(h=>h.dense_candidates(batch()));}finally{await f.resource.close();}});

for (const [name, mutate] of [
  ['boolean call count', value => { value.provider_calls = true; }],
  ['nan usage cost', value => { value.usage.cost_usd = NaN; }],
  ['infinite usage cost', value => { value.usage.cost_usd = Infinity; }],
  ['unsafe prompt count', value => { value.usage.prompt_tokens = Number.MAX_SAFE_INTEGER + 1; }],
  ['unsafe total count', value => { value.usage.total_tokens = Number.MAX_SAFE_INTEGER + 1; }],
]) test(`dense rejects ${name} before database work`, async () => {
  const f = fixture();
  try {
    await f.run(async handle => {
      const value = batch(); mutate(value);
      const count = f.client.queries.length;
      await assert.rejects(handle.dense_candidates(value), InvalidRequest);
      assert.equal(f.client.queries.length, count);
    });
  } finally { await f.resource.close(); }
});
