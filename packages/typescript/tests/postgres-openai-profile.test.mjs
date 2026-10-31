import test from 'node:test';
import assert from 'node:assert/strict';
import { FAKE_PROFILE, OPENAI_PROFILE, EmbeddingAdapter } from '../dist/embeddings.js';
import { snapshot_profile, profile_table, profile_sql, validate_profile_storage, LEGACY_VECTOR_HISTORY, OPENAI_VECTOR_HISTORY, PROFILE_ROWS, OPENAI_TABLE_SQL } from '../dist/postgres-profiles.js';
import { dense_batch } from '../dist/postgres-session.js';
import { PostgresVectorIndexer } from '../dist/vector-ingestion.js';

function adapter(profile=FAKE_PROFILE) {
  return new EmbeddingAdapter(async()=>{throw Error('transport must not run');},
    {name:profile.tokenizer,count:text=>text.length},{profile});
}
function batch(profile=FAKE_PROFILE) {
  return {profile,vectors:[[1,...Array(1535).fill(0)]],provider_calls:1,synthetic:profile.provider==='fake',
    usage:{prompt_tokens:0,total_tokens:0,cost_usd:0,cost_kind:'known'}};
}
test('trusted full snapshots select only two fixed tables',()=>{
  assert.deepEqual(snapshot_profile(),FAKE_PROFILE);
  assert.equal(profile_table(OPENAI_PROFILE),'chunk_vectors_openai_te3small_1536');
  assert.equal(profile_sql('SELECT * FROM chunk_vectors_fake_1536',OPENAI_PROFILE),'SELECT * FROM chunk_vectors_openai_te3small_1536');
  assert.throws(()=>snapshot_profile({...OPENAI_PROFILE,model:'other'}));
  assert.equal(Object.isFrozen(snapshot_profile({...OPENAI_PROFILE})),true);
});
test('default refuses live adapter while explicit full snapshot admits construction without IO',()=>{
  assert.throws(()=>new PostgresVectorIndexer({},async()=>true,adapter(OPENAI_PROFILE)),/unsupported/i);
  assert.doesNotThrow(()=>new PostgresVectorIndexer({},async()=>true,adapter(OPENAI_PROFILE),{embedding_profile:OPENAI_PROFILE}));
  assert.throws(()=>new PostgresVectorIndexer({},async()=>true,adapter(),{embedding_profile:OPENAI_PROFILE}));
});
test('dense batch rejects profile and synthetic confusion',()=>{
  assert.equal(dense_batch(batch()).profile.provider,'fake');
  assert.throws(()=>dense_batch(batch(OPENAI_PROFILE)));
  assert.equal(dense_batch(batch(OPENAI_PROFILE),OPENAI_PROFILE).synthetic,false);
  assert.throws(()=>dense_batch({...batch(OPENAI_PROFILE),synthetic:true},OPENAI_PROFILE));
});
test('legacy registry remains exact and refuses live before table work',async()=>{
  const queries=[];
  const query=async sql=>{queries.push(sql);return sql.includes('setup_history')?LEGACY_VECTOR_HISTORY:sql.includes('embedding_profiles ORDER')?[PROFILE_ROWS[0]]:[[true]];};
  await validate_profile_storage(query,FAKE_PROFILE,'capability');
  await assert.rejects(validate_profile_storage(query,OPENAI_PROFILE,'capability'));
  await assert.rejects(validate_profile_storage(async sql=>sql.includes('setup_history ORDER')?[...LEGACY_VECTOR_HISTORY,['unknown','hash']]:[[true]],FAKE_PROFILE,'capability'));
  await assert.rejects(validate_profile_storage(async sql=>sql.includes('setup_history')?OPENAI_VECTOR_HISTORY:sql.includes('embedding_profiles ORDER')?[PROFILE_ROWS[0]]:[[true]],FAKE_PROFILE,'capability'));
});
test('upgraded admission checks both physical tables for either selected profile',async()=>{
  for (const profile of [FAKE_PROFILE,OPENAI_PROFILE]) {
    let checked=false;
    const query=async sql=>{
      if(sql.includes('setup_history ORDER'))return OPENAI_VECTOR_HISTORY;
      if(sql.includes('embedding_profiles ORDER'))return PROFILE_ROWS;
      if(sql===OPENAI_TABLE_SQL){checked=true;return [[false]];}
      return [[true]];
    };
    await assert.rejects(validate_profile_storage(query,profile,'capability'));
    assert.equal(checked,true);
  }
  assert.equal(Object.isFrozen(PROFILE_ROWS[0]),true);
  assert.equal(Object.isFrozen(OPENAI_VECTOR_HISTORY),true);
});
for(const profile of [FAKE_PROFILE,OPENAI_PROFILE]) for(const write of [false,true]) {
  test(`upgraded ${profile.provider} ${write?'writer':'reader'} requires each selected privilege`,async()=>{
    const table='cragkit.'+profile_table(profile);
    const privileges=write?['SELECT','INSERT','UPDATE']:['SELECT'];
    const expected='SELECT '+privileges.map(privilege=>`has_table_privilege(current_user,'${table}','${privilege}')`).join(' AND ');
    for(const permitted of [true,false]) {
      const calls=[];
      const query=async sql=>{
        calls.push(sql);
        if(sql.includes('setup_history ORDER'))return OPENAI_VECTOR_HISTORY;
        if(sql.includes('embedding_profiles ORDER'))return PROFILE_ROWS;
        if(sql.startsWith('SELECT has_table_privilege(')){assert.equal(sql,expected);return [[permitted]];}
        return [[true]];
      };
      if(permitted)await validate_profile_storage(query,profile,'capability',write);
      else await assert.rejects(validate_profile_storage(query,profile,'capability',write),error=>error.code==='unsupported_capability');
      assert.equal(calls.at(-1),expected);
      assert.equal(calls.at(-2),OPENAI_TABLE_SQL);
    }
  });
}
test('legacy fake writer admission does not introduce privilege queries',async()=>{
  const calls=[];
  await validate_profile_storage(async sql=>{
    calls.push(sql);
    if(sql.includes('setup_history ORDER'))return LEGACY_VECTOR_HISTORY;
    if(sql.includes('embedding_profiles ORDER'))return [PROFILE_ROWS[0]];
    return [[true]];
  },FAKE_PROFILE,'capability',true);
  assert.equal(calls.length,3);
  assert.equal(calls.some(sql=>sql.includes('has_table_privilege')),false);
});
