import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { PoolResource, parse_pool_config, now } from '../dist/postgres-pool.js';
import { PostgresSession, EXPECTED_HISTORY, _ROLE_SQL, _CATALOG_SQL, _HISTORY_SQL, _COLLECTION_SQL, _IDENTIFIER_SQL, _SOURCE_SQL } from '../dist/postgres-session.js';
import { EXPECTED_VECTOR_HISTORY, _VECTOR_CAPABILITY_SQL, _SETUP_HISTORY_SQL, _PROFILE_SQL } from '../dist/vector-ingestion.js';
import { FAKE_PROFILE } from '../dist/embeddings.js';
import { extract_identifiers, validate_identifier } from '../dist/identifiers.js';
import { InvalidRequest, IntegrityViolation, UnsupportedCapability } from '../dist/errors.js';
const row = () => ['tenant','collection','doc','revision','generation','chunk','0','4','a'.repeat(64),1,'native_fts.v1','pg_catalog.simple'];
function fixture(request={}) {
  const client={ status:'I',queries:[],rows:[row()],capability:[[true]],history:EXPECTED_VECTOR_HISTORY,profiles:[[...Object.values(FAKE_PROFILE),'chunk_vectors_fake_1536']],hook:null,
    getTransactionStatus(){return this.status;},release(){},async query(q){
      this.queries.push(q); if(q.text.startsWith('BEGIN'))this.status='T';if(q.text==='ROLLBACK')this.status='I';
      if(q.text.startsWith(_IDENTIFIER_SQL.split('{predicate}')[0])){if(this.hook)await this.hook(q);return {rows:this.rows};}
      if(q.text.startsWith(_SOURCE_SQL.split('{predicate}')[0]))return {rows:[]};
      const rows=q.text===_ROLE_SQL||q.text===_CATALOG_SQL?[[true]]:q.text===_HISTORY_SQL?EXPECTED_HISTORY:q.text===_COLLECTION_SQL?[['0.1','native_fts.v1']]:q.text===_VECTOR_CAPABILITY_SQL?this.capability:q.text===_SETUP_HISTORY_SQL?this.history:q.text===_PROFILE_SQL?this.profiles:[];
      return {rows};
    }};
  const resource=new PoolResource(parse_pool_config({host:'synthetic.invalid',dbname:'synthetic',user:'reader',sslrootcert:'/synthetic/ca',passfile:'/synthetic/pass'}),{pool:{connect:async()=>client,end:async()=>{}}});
  const session=new PostgresSession(resource);
  const run=(body,extra={})=>session.transaction({query:'synthetic',collection:'collection',...request},{deadline:now()+2,scope:{tenant_id:'tenant',principal_id:'principal',authorization_revision:'authorization',grant_ids:['grant']},...extra},body);
  const identifierQueries=()=>client.queries.filter(q=>q.text.startsWith(_IDENTIFIER_SQL.split('{predicate}')[0]));
  return {client,resource,run,identifierQueries};
}

test('shared exact identifier extraction fixtures', () => {
  const fixture = JSON.parse(readFileSync(new URL('../../../contracts/fixtures/identifier_fusion.json', import.meta.url), 'utf8'));
  for (const item of fixture.extraction) assert.deepEqual(extract_identifiers(item.text), item.expected);
  assert.equal(validate_identifier('C++'), 'C++');
  assert.deepEqual(extract_identifiers('x'+'1'.repeat(255)), ['x'+'1'.repeat(255)]);
});
test('identifier selection binds scope and filters before effective limit and reauthorizes source', async () => {
  const f=fixture({limits:{max_candidates:2},required_filters:[{field:'document_id',op:'eq',value:"doc' --"}]});
  try {await f.run(async h=>{
    const [candidate]=await h.identifier_candidates('ERR_CONN-42',{limit:5});
    assert.equal(candidate.identifier_profile,'identifier_ascii_v1');
    const q=f.identifierQueries()[0];
    assert.deepEqual(q.values,['tenant','collection','authorization','authorization','principal',['grant'],"doc' --",'ERR_CONN-42',2]);
    assert.ok(q.text.indexOf('identifier_tokens @>')<q.text.indexOf('LIMIT'));
    assert.match(q.text,/d.document_id = \$7/);assert.match(q.text,/LIMIT \$9/);
    for(const changed of [{identifier_profile:'forged'},{score:2},{score_kind:'confidence'},{score_direction:'lower_is_better'},{extra:1}]) {
      const before=f.client.queries.length;
      await assert.rejects(h.fetch_evidence({...candidate,...changed},{max_source_bytes:4}),InvalidRequest);
      assert.equal(f.client.queries.length,before);
    }
    assert.equal((await h.fetch_evidence(candidate,{max_source_bytes:4})).state,'unavailable');
  });}finally{await f.resource.close();}
});
for(const identifier of ['', 'hello','HTTP','x1 x2','x1 ',' x1','x1\0','x'+'1'.repeat(256),null,true,42])test(`invalid identifier ${JSON.stringify(identifier)}`,async()=>{
  const f=fixture();try{await f.run(async h=>{const before=f.client.queries.length;await assert.rejects(h.identifier_candidates(identifier),InvalidRequest);assert.equal(f.client.queries.length,before);});}finally{await f.resource.close();}
});
for(const options of [null,[],{limit:true},{limit:0},{limit:1001},{limit:1.5},{extra:1}])test(`identifier invalid limit ${JSON.stringify(options)}`,async()=>{
  const f=fixture();try{await f.run(async h=>{const before=f.client.queries.length;await assert.rejects(h.identifier_candidates('x1',options),InvalidRequest);assert.equal(f.client.queries.length,before);});}finally{await f.resource.close();}
});
for(const [name,change,kind] of [['shape',r=>r.pop(),IntegrityViolation],['scope',r=>{r[0]='other';},IntegrityViolation],['score',r=>{r[9]=0;},IntegrityViolation],['span',r=>{r[7]='0';},IntegrityViolation],['profile',r=>{r[10]='wrong';},UnsupportedCapability]])test(`identifier malformed ${name}`,async()=>{
  const f=fixture();change(f.client.rows[0]);try{await assert.rejects(f.run(h=>h.identifier_candidates('x1')),kind);}finally{await f.resource.close();}
});
test('identifier duplicate/overlimit rows and expired handles fail closed',async()=>{
  const f=fixture();let saved;try{f.client.rows=[row(),row()];await assert.rejects(f.run(h=>h.identifier_candidates('x1')),IntegrityViolation);await assert.rejects(f.run(h=>h.identifier_candidates('x1',{limit:1})),IntegrityViolation);f.client.rows=[];await f.run(async h=>{saved=h;assert.deepEqual(await h.identifier_candidates('x1'),[]);});await assert.rejects(saved.identifier_candidates('x1'),InvalidRequest);}finally{await f.resource.close();}
});
