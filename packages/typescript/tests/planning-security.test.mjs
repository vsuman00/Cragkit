import test from 'node:test';
import assert from 'node:assert/strict';
import { inspect } from 'node:util';
import { performance } from 'node:perf_hooks';
import { ExecutionLedger } from '../dist/execution.js';
import { PlannerAdapter } from '../dist/planning.js';
import { DeadlineExceeded, ProviderUnavailable } from '../dist/errors.js';

const canary='SYNTHETIC_PRIVATE_ERROR_CANARY';
for(const shape of ['declared-provider','declared-deadline','forged-abort'])test(`public planner redacts ${shape} transport failure and accounts for dispatched work`,async()=>{
  const original=Object.assign(shape==='declared-provider'?new ProviderUnavailable():shape==='declared-deadline'?new DeadlineExceeded():new Error(canary),
    {code:canary,message:canary,cause:new Error(canary),private_detail:canary});
  if(shape==='forged-abort')original.name='AbortError';
  const Kind=shape==='declared-deadline'?DeadlineExceeded:ProviderUnavailable;
  const deadline=performance.now()/1000+1,ledger=new ExecutionLedger({limits:{max_provider_calls:1},deadline});
  const planner=new PlannerAdapter({transport:async()=>{throw original;},cost_upper_usd:0});
  await assert.rejects(planner.plan({query:'Explain API-42',variants:[{facet_id:'f',variant_id:'v',query:'API-42 retry'}],
    missing_facets:['f'],max_subqueries:2,ledger,deadline}),error=>{
    assert.ok(error instanceof Kind);assert.notEqual(error,original);assert.equal(Object.getPrototypeOf(error),Kind.prototype);
    assert.equal(error.message,new Kind().message);
    assert.equal(error.code,new Kind().code);
    assert.ok(!inspect(error,{depth:5}).includes(canary));assert.ok(!JSON.stringify(error).includes(canary));
    return true;
  });
  assert.equal(ledger.snapshot().provider_calls,1);assert.equal(ledger.snapshot().cost_kind,'unknown');assert.equal(ledger.snapshot().pending,0);
});

test('forged transport AbortError follows configured provider fallback without refund',async()=>{
  const original=Object.assign(new Error(canary),{name:'AbortError'});
  const deadline=performance.now()/1000+1,ledger=new ExecutionLedger({limits:{max_provider_calls:1},deadline});
  const planner=new PlannerAdapter({transport:async()=>{throw original;},cost_upper_usd:0,allow_fallback:true});
  assert.deepEqual(await planner.plan({query:'Explain API-42',variants:[{facet_id:'f',variant_id:'v',query:'API-42 retry'}],
    missing_facets:['f'],max_subqueries:2,ledger,deadline}),{queries:[],fallback:true});
  assert.equal(ledger.snapshot().provider_calls,1);assert.equal(ledger.snapshot().cost_kind,'unknown');assert.equal(ledger.snapshot().pending,0);
});
