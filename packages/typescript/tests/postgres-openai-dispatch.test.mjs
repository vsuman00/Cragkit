import test from 'node:test';
import assert from 'node:assert/strict';
import { EmbeddingAdapter, FAKE_PROFILE, OPENAI_PROFILE } from '../dist/embeddings.js';
import { BudgetExhausted } from '../dist/execution.js';
const future=()=>performance.now()/1000+10;
function harness(profile=FAKE_PROFILE,policy={}) {
  const calls=[];
  const adapter=new EmbeddingAdapter(async body=>{
    calls.push('transport');
    return Buffer.from(JSON.stringify({model:profile.model,data:[{index:0,embedding:[1,...Array(1535).fill(0)]}]}));
  },{name:profile.tokenizer,count:()=>1},{profile,policy});
  return {adapter,calls};
}
test('dispatch callback runs once after admission and before transport',async()=>{
  const {adapter,calls}=harness();
  await adapter.embed_query('tiny',{deadline:future(),on_dispatch:()=>{calls.push('observer');}});
  assert.deepEqual(calls,['observer','transport']);
});
test('local policy failure does not invoke observer or transport',async()=>{
  const {adapter,calls}=harness(OPENAI_PROFILE);
  await assert.rejects(adapter.embed_query('tiny',{deadline:future(),on_dispatch:()=>{calls.push('observer');}}));
  assert.deepEqual(calls,[]);
});
test('observer admission error remains unchanged with no dispatch',async()=>{
  const {adapter,calls}=harness();const failure=new BudgetExhausted();
  await assert.rejects(adapter.embed_query('tiny',{deadline:future(),on_dispatch:()=>{throw failure;}}),error=>error===failure);
  assert.deepEqual(calls,[]);
});
test('async and nonvoid observers never invoke transport or leak a rejection',async()=>{
  const {adapter,calls}=harness();
  for(const on_dispatch of [async()=>{},()=>1,()=>Promise.reject(Error('observed'))]) {
    await assert.rejects(adapter.embed_query('tiny',{deadline:future(),on_dispatch}));
  }
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(calls,[]);
});
