/** RK-r2 native recorded responses. No external model or database. */
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {RerankingAdapter, FAKE_RERANK_PROFILE} from '../packages/typescript/dist/reranking.js';
import {CragkitError} from '../packages/typescript/dist/errors.js';
const fixture=JSON.parse(fs.readFileSync('contracts/fixtures/reranking.json','utf8'));
const results=[];
for (const entry of fixture.cases) {
  const selected=Object.hasOwn(entry,'candidate_ids')?[]:fixture.sample.candidates;
  const adapter=new RerankingAdapter(async()=>Buffer.from(JSON.stringify(entry.response)),{
    profile:{...FAKE_RERANK_PROFILE,score_direction:entry.score_direction??'higher_is_better'}});
  try {
    const result=await adapter.rank(fixture.sample.query,selected,{deadline:performance.now()/1000+2});
    assert.deepEqual(result.order,entry.expected_order);
    assert.equal(result.provider_calls,selected.length?1:0);
    results.push(result);
  } catch(error) {
    if (!(error instanceof CragkitError) || !entry.expected_rejection || error.code!=='integrity_violation') throw error;
    results.push({error:error.code});
  }
}
console.log(JSON.stringify(results));
