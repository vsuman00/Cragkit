import test from 'node:test';
import assert from 'node:assert/strict';
import { performance } from 'node:perf_hooks';
import { ExecutionLedger } from '../dist/execution.js';
import { InvalidRequest, IntegrityViolation, UnsupportedCapability, DeadlineExceeded } from '../dist/errors.js';
const ledger = (limits = {}, deadline = performance.now() / 1000 + 60) => new ExecutionLedger({limits, deadline});
const exhausted = error => error.name === 'BudgetExhausted';

test('event-loop tasks race for one final provider slot without overspending', async () => {
  const l = ledger({max_provider_calls: 1});
  const results = await Promise.allSettled(Array.from({length: 12}, async () => {
    await Promise.resolve();
    const r = l.reserve({provider_calls: 1}); l.dispatch(r);
    await Promise.resolve(); l.reconcile(r, {input_tokens: 2, output_tokens: 3, cost_usd: 0.01});
  }));
  assert.equal(results.filter(r => r.status === 'fulfilled').length, 1);
  assert.ok(results.filter(r => r.status === 'rejected').every(r => exhausted(r.reason)));
  assert.deepEqual(l.snapshot(), {provider_calls: 1, candidates: 0, attempts: 0, input_tokens: 2,
    output_tokens: 3, cost_usd: 0.01, cost_kind: 'known', pending: 0});
});

test('nested SDK transport retry reserves every call and stops at its shared boundary', () => {
  const l = ledger({max_provider_calls: 2, max_attempts: 2});
  const run = () => {
    const r = l.reserve({provider_calls: 1, attempts: 1}); l.dispatch(r); l.abandon(r);
  };
  run(); run(); assert.throws(run, exhausted);
  assert.equal(l.snapshot().provider_calls, 2); assert.equal(l.snapshot().attempts, 2);
  assert.equal(l.snapshot().cost_kind, 'unknown');
});

test('native cancellation before dispatch refunds; cancellation after dispatch retains unknown charge', async () => {
  const l = ledger({max_provider_calls: 1});
  const controller = new AbortController();
  const before = l.reserve({provider_calls: 1, candidates: 2}); controller.abort();
  try { controller.signal.throwIfAborted(); } catch { l.abandon(before); }
  assert.equal(l.snapshot().provider_calls, 0); assert.equal(l.snapshot().cost_usd, 0);
  const after = l.reserve({provider_calls: 1}); l.dispatch(after);
  await assert.rejects(async () => { try { controller.signal.throwIfAborted(); } finally { l.abandon(after); } }, {name: 'AbortError'});
  assert.equal(l.snapshot().provider_calls, 1); assert.equal(l.snapshot().input_tokens, null);
  assert.throws(() => l.reserve({provider_calls: 1}), exhausted);
});

test('opaque tokens enforce ownership and exactly-once state', () => {
  const a = ledger(), b = ledger(); const r = a.reserve({candidates: 1});
  for (const bad of [{}, {...r}, null, 1]) assert.throws(() => a.dispatch(bad), InvalidRequest);
  assert.throws(() => b.dispatch(r), InvalidRequest);
  assert.throws(() => a.reconcile(r), InvalidRequest);
  a.dispatch(r); assert.throws(() => a.dispatch(r), InvalidRequest);
  assert.throws(() => a.reconcile(r, {input_tokens: 1}), InvalidRequest);
  a.reconcile(r); assert.throws(() => a.abandon(r), InvalidRequest);
  assert.throws(() => a.reconcile(r), InvalidRequest);
  assert.equal(a.snapshot().cost_usd, 0);
});

test('pending upper bounds enforce strict spend without pretending to be actual usage', () => {
  const l = ledger({max_spend_usd: 1});
  assert.throws(() => l.reserve({provider_calls: 1}), UnsupportedCapability);
  const r = l.reserve({provider_calls: 1, cost_upper_usd: 0.75});
  assert.equal(l.snapshot().cost_usd, null);
  assert.throws(() => l.reserve({provider_calls: 1, cost_upper_usd: 0.5}), exhausted);
  l.dispatch(r); l.reconcile(r, {input_tokens: 1, output_tokens: 1, cost_usd: 0.25});
  const next = l.reserve({provider_calls: 1, cost_upper_usd: 0.75}); l.dispatch(next); l.reconcile(next);
  assert.equal(l.snapshot().cost_usd, null);
  assert.throws(() => l.reserve({provider_calls: 1, cost_upper_usd: 0.01}), exhausted);
});

test('overrun records actual cost and poisons further admission', () => {
  const l = ledger(); const r = l.reserve({provider_calls: 1, cost_upper_usd: 0.1});
  l.dispatch(r); assert.throws(() => l.reconcile(r, {cost_usd: 0.2}), IntegrityViolation);
  assert.equal(l.snapshot().cost_usd, 0.2); assert.equal(l.snapshot().pending, 0);
  assert.throws(() => l.reserve({candidates: 1}), IntegrityViolation);
  assert.throws(() => l.reconcile(r), InvalidRequest);
});

test('validation rejects malformed boundaries without changing ledger state', () => {
  for (const options of [{limits: {}}, {limits: {}, deadline: NaN}, {limits: {max_attempts: true}, deadline: 1}])
    assert.throws(() => new ExecutionLedger(options), InvalidRequest);
  const l = ledger();
  for (const options of [{}, {provider_calls: true}, {attempts: -1}, {candidates: 1.5},
    {candidates: Number.MAX_SAFE_INTEGER + 1}, {candidates: 1, extra: 1}, {provider_calls: 1, cost_upper_usd: Infinity},
    {candidates: 1, cost_upper_usd: 1}]) assert.throws(() => l.reserve(options), InvalidRequest);
  const r = l.reserve({provider_calls: 1}); l.dispatch(r);
  for (const actual of [{input_tokens: true}, {cost_usd: NaN}, {output_tokens: -1}, {extra: 1}])
    assert.throws(() => l.reconcile(r, actual), InvalidRequest);
  assert.equal(l.snapshot().pending, 1); l.reconcile(r);
});

test('deadlines stop admission and dispatch while cleanup remains possible', () => {
  const l = ledger({}, -1); assert.throws(() => l.reserve({attempts: 1}), DeadlineExceeded);
  const live = ledger(); const r = live.reserve({candidates: 2});
  const snapshot = live.snapshot(); assert.ok(Object.isFrozen(snapshot));
  live.abandon(r); assert.equal(snapshot.candidates, 2); assert.equal(live.snapshot().candidates, 0);
});

test('safe token aggregate overflow poisons ledger instead of rounding usage', () => {
  const l = ledger();
  for (const n of [Number.MAX_SAFE_INTEGER, 1]) {
    const r = l.reserve({provider_calls: 1}); l.dispatch(r);
    if (n === 1) assert.throws(() => l.reconcile(r, {input_tokens: n, output_tokens: 0, cost_usd: 0}), IntegrityViolation);
    else l.reconcile(r, {input_tokens: n, output_tokens: 0, cost_usd: 0});
  }
  assert.equal(l.snapshot().input_tokens, null);
  assert.throws(() => l.reserve({attempts: 1}), IntegrityViolation);
});

test('close revokes late admission/dispatch while accounting cleanup remains available',()=>{
 const l=ledger(),active=l.reserve({provider_calls:1});l.dispatch(active);
 const waiting=l.reserve({candidates:1});l.close();l.close();
 assert.throws(()=>l.reserve({attempts:1}),InvalidRequest);
 assert.throws(()=>l.dispatch(waiting),InvalidRequest);
 l.abandon(waiting);l.reconcile(active,{input_tokens:1,output_tokens:0,cost_usd:0});
 assert.equal(l.snapshot().pending,0);
});
