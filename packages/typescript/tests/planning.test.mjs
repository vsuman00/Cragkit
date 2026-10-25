import test from 'node:test';
import assert from 'node:assert/strict';
import { performance } from 'node:perf_hooks';
import { PlannerAdapter, validate_plan } from '../dist/planning.js';
import { ExecutionLedger, BudgetExhausted } from '../dist/execution.js';
import { InvalidRequest, IntegrityViolation, ProviderUnavailable, UnsupportedCapability, DeadlineExceeded } from '../dist/errors.js';
const deadline = () => performance.now() / 1000 + 1;
const variants = [{facet_id: 'retry', variant_id: 'v1', query: 'How does API-42 retry?'}];
const config = () => ({query: 'Explain API-42', variants: structuredClone(variants), missing_facets: ['retry'], max_subqueries: 4});
const selection = {queries: [{facet_id: 'retry', variant_id: 'v1'}]};
const output = (plan = selection, usage = {input_tokens: 2, output_tokens: 3, cost_usd: 0.01}) => ({plan, usage});
const ledger = (limits = {}) => new ExecutionLedger({limits, deadline: deadline()});
const options = (l = ledger(), extra = {}) => ({...config(), ledger: l, deadline: deadline(), ...extra});

test('selection returns frozen detached approved variants and rejects invented intent or scope', () => {
  const c = config(), result = validate_plan(selection, c);
  c.variants[0].query = 'changed'; assert.deepEqual(result, variants); assert.ok(Object.isFrozen(result[0]));
  for (const plan of ['{"queries":[]}', {queries: [{facet_id: 'retry', variant_id: 'invented'}]},
    {queries: [{facet_id: 'absent', variant_id: 'v1'}]}, {queries: selection.queries, scope: 'admin'},
    {queries: [{...selection.queries[0], query: 'invented facts'}]}, {queries: [...selection.queries, ...selection.queries]}])
    assert.throws(() => validate_plan(plan, config()), InvalidRequest);
  assert.throws(() => validate_plan(selection, {...config(), max_subqueries: 1}), InvalidRequest);
});

test('trusted configuration validates identifiers and uniqueness even for an empty plan', () => {
  for (const c of [{...config(), variants: [{...variants[0], query: 'How does api-42 retry?'}]},
    {...config(), variants: [...variants, ...variants]}, {...config(), missing_facets: ['retry', 'retry']},
    {...config(), max_subqueries: true}, {...config(), variants: [{...variants[0], limits: {}}]}])
    assert.throws(() => validate_plan({queries: []}, c), InvalidRequest);
  assert.deepEqual(validate_plan({queries: []}, config()), []);
});

test('successful fake transport receives an immutable snapshot and reconciles usage', async () => {
  const l = ledger(); let release;
  const gate = new Promise(resolve => { release = resolve; });
  const c = options(l);
  const adapter = new PlannerAdapter({transport: async (payload, o) => {
    await gate; assert.equal(payload.query, 'Explain API-42'); assert.equal(payload.variants[0].query, variants[0].query);
    assert.ok(Object.isFrozen(payload.variants[0])); assert.ok(o.signal instanceof AbortSignal); return output();
  }});
  const pending = adapter.plan(c); c.query = 'changed'; c.variants[0].query = 'changed'; release();
  assert.deepEqual(await pending, {queries: variants, fallback: false});
  assert.equal(l.snapshot().cost_usd, 0.01); assert.equal(l.snapshot().provider_calls, 1); assert.equal(l.snapshot().pending, 0);
});

test('no-op configuration never dispatches and SDK retries are forbidden', async () => {
  let calls = 0; const a = new PlannerAdapter({transport: async () => { calls++; return output(); }});
  for (const extra of [{variants: []}, {missing_facets: []}, {max_subqueries: 1}])
    assert.deepEqual(await a.plan(options(ledger(), extra)), {queries: [], fallback: false});
  assert.equal(calls, 0);
  for (const sdk_retries of [1, -1, true]) assert.throws(() => new PlannerAdapter({transport: async () => output(), sdk_retries}), InvalidRequest);
});

test('malformed bounded responses fail integrity or use configured fallback', async () => {
  for (const raw of ['{"plan":{}}', {...output(), scope: 'admin'}, output({queries: [{facet_id: 'retry', variant_id: 'x'}]}),
    output(selection, {input_tokens: true, output_tokens: null, cost_usd: null}), output({queries: [], extra: 'x'.repeat(17000)}),
    {plan: {}, usage: {input_tokens: null, output_tokens: null, cost_usd: null}, get danger() { throw new Error('never inspect'); }}]) {
    const strict = new PlannerAdapter({transport: async () => raw});
    await assert.rejects(strict.plan(options()), IntegrityViolation);
    const l = ledger(), fallback = new PlannerAdapter({transport: async () => raw, allow_fallback: true});
    assert.deepEqual(await fallback.plan(options(l)), {queries: [], fallback: true});
    assert.equal(l.snapshot().provider_calls, 1); assert.equal(l.snapshot().pending, 0);
  }
});

test('malformed plans reconcile valid usage; malformed usage remains unknown', async () => {
  const l = ledger();
  await new PlannerAdapter({transport: async () => output({queries: [{facet_id: 'x', variant_id: 'x'}]}), allow_fallback: true}).plan(options(l));
  assert.equal(l.snapshot().cost_usd, 0.01);
  const unknown = ledger(); await new PlannerAdapter({transport: async () => output(selection, {}), allow_fallback: true}).plan(options(unknown));
  assert.equal(unknown.snapshot().cost_usd, null);
});

test('provider faults are redacted and fallback is explicit', async () => {
  const transport = async () => { throw new Error('private provider details'); };
  await assert.rejects(new PlannerAdapter({transport}).plan(options()), error => error instanceof ProviderUnavailable && !error.message.includes('private'));
  assert.deepEqual(await new PlannerAdapter({transport, allow_fallback: true}).plan(options()), {queries: [], fallback: true});
});

test('strict capability, exhausted budgets, unsafe configuration and actual overruns cannot fallback', async () => {
  let calls = 0; const transport = async () => { calls++; return output(); };
  const a = new PlannerAdapter({transport, allow_fallback: true});
  await assert.rejects(a.plan(options(ledger({max_spend_usd: 1}))), UnsupportedCapability);
  await assert.rejects(a.plan(options(ledger({max_provider_calls: 0}))), BudgetExhausted);
  await assert.rejects(a.plan(options(ledger(), {variants: [{...variants[0], query: 'no identifier'}]})), InvalidRequest);
  assert.equal(calls, 0);
  const l = ledger(); const over = new PlannerAdapter({transport, allow_fallback: true, cost_upper_usd: 0});
  await assert.rejects(over.plan(options(l)), IntegrityViolation);
  assert.equal(l.snapshot().cost_usd, 0.01); assert.equal(l.snapshot().pending, 0);
});

test('outer deadline bounds an ignoring transport and retains unknown dispatched cost', async () => {
  const l = ledger(); let child;
  const a = new PlannerAdapter({transport: async (_payload, {signal}) => { child = signal; return new Promise(() => {}); }, allow_fallback: true});
  await assert.rejects(a.plan(options(l, {deadline: performance.now() / 1000 + 0.01})), DeadlineExceeded);
  assert.equal(child.aborted, true); assert.equal(l.snapshot().cost_usd, null); assert.equal(l.snapshot().pending, 0);
});

test('native abort before and after dispatch propagates without fallback or refund after dispatch', async () => {
  const controller = new AbortController(), l = ledger(); controller.abort();
  const a = new PlannerAdapter({transport: async () => output(), allow_fallback: true});
  await assert.rejects(a.plan(options(l, {signal: controller.signal})), {name: 'AbortError'});
  assert.equal(l.snapshot().provider_calls, 0);
  const active = new AbortController(), l2 = ledger();
  const b = new PlannerAdapter({transport: async () => { active.abort(); return new Promise(() => {}); }, allow_fallback: true});
  await assert.rejects(b.plan(options(l2, {signal: active.signal})), {name: 'AbortError'});
  assert.equal(l2.snapshot().provider_calls, 1); assert.equal(l2.snapshot().cost_usd, null); assert.equal(l2.snapshot().pending, 0);
});


test('ledger request duration bounds a transport despite a later supplied deadline', async () => {
  const l = ledger({deadline_ms: 1});
  const a = new PlannerAdapter({transport: async () => new Promise(() => {}), allow_fallback: true});
  await assert.rejects(a.plan(options(l)), DeadlineExceeded);
  assert.equal(l.snapshot().pending, 0);
});
