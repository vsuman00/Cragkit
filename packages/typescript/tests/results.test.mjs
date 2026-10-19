import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { parse_result, ResultSchema, EvidenceSchema, UsageSchema } from 'cragkit/contracts';
import { InvalidRequest } from 'cragkit/errors';
const fixture = JSON.parse(readFileSync(new URL('../../../contracts/fixtures/results.json', import.meta.url), 'utf8'));
for (const example of fixture.cases) {
  test(`shared result fixture: ${example.id}`, () => {
    assert.equal(ResultSchema.safeParse(example.input).success, example.valid);
    if (example.valid) {
      const parsed = parse_result(example.input);
      assert.equal(parsed.status, example.input.status);
      assert.equal(parsed.request_id, example.input.request_id);
      assert.deepEqual(JSON.parse(JSON.stringify(parsed)).evidence, example.input.evidence ?? []);
    } else assert.throws(() => parse_result(example.input), InvalidRequest);
  });
}
const minimal = () => ({ request_id: 'r', status: 'insufficient' });
const partial = () => structuredClone(fixture.cases.find(example => example.id === 'unicode-large-id-unknown-partial').input);
test('unknown usage remains null and counting identities are required', () => {
  const result = parse_result(minimal());
  assert.deepEqual(result.usage, { attempt_count: 0, provider_calls: 0, provider_input_tokens: null, provider_output_tokens: null,
    cost_usd: null, cost_kind: 'unknown', context_tokens: null, context_counting: 'unknown', stage_durations: [] });
  for (const kind of ['estimated', 'known']) {
    assert.throws(() => parse_result({ ...minimal(), usage: { cost_kind: kind } }), InvalidRequest);
    assert.equal(parse_result({ ...minimal(), usage: { cost_kind: kind, cost_usd: 0 } }).usage.cost_usd, 0);
  }
  assert.throws(() => parse_result({ ...minimal(), usage: { context_counting: 'strict', context_tokens: 0 } }), InvalidRequest);
  assert.equal(parse_result({ ...minimal(), usage: { context_counting: 'strict', context_tokens: 0 }, versions: { tokenizer: 'declared' } }).usage.context_tokens, 0);
});
test('native invalid numbers, cycles and errors never leak input', () => {
  for (const value of [NaN, Infinity, -Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    for (const field of ['provider_input_tokens', 'cost_usd', 'attempt_count']) {
      assert.throws(() => parse_result({ ...minimal(), usage: { [field]: value } }), InvalidRequest);
    }
  }
  const cycle = minimal(); cycle.extra = cycle;
  assert.equal(ResultSchema.safeParse(cycle).success, false);
  try { parse_result({ ...minimal(), secret: 'private-source-secret' }); assert.fail('must reject'); }
  catch (error) {
    assert.ok(error instanceof InvalidRequest);
    assert.equal(error.cause, undefined);
    assert.doesNotMatch(String(error) + JSON.stringify(error), /private-source-secret/);
  }
});
test('excerpt byte lengths and digests are verified without fetching source', () => {
  const evidence = partial().evidence[0];
  assert.equal(evidence.document_id, '900719925474099312345');
  assert.equal(evidence.end_byte - evidence.start_byte, Buffer.byteLength(evidence.text, 'utf8'));
  assert.ok(EvidenceSchema.safeParse(evidence).success);
  assert.equal(EvidenceSchema.safeParse({ ...evidence, end_byte: evidence.start_byte + evidence.text.length }).success, false);
  assert.equal(EvidenceSchema.safeParse({ ...evidence, text: 'modified' }).success, false);
  const whitespace = ' \n';
  assert.ok(EvidenceSchema.safeParse({ ...evidence, text: whitespace, end_byte: evidence.start_byte + 2,
    text_sha256: createHash('sha256').update(whitespace).digest('hex') }).success);
  assert.ok(EvidenceSchema.safeParse({ ...evidence, source_sha256: '0'.repeat(64) }).success);
});
test('parsed results are immutable snapshots down to reference arrays and durations', () => {
  const input = partial(); input.usage = { stage_durations: [{ stage: 'search', duration_ms: 1.5 }] };
  const result = parse_result(input);
  input.evidence[0].text = 'changed'; input.facets[0].evidence_ids.push('absent'); input.usage.stage_durations[0].duration_ms = 99;
  assert.notEqual(result.evidence[0].text, 'changed');
  assert.deepEqual(result.facets[0].evidence_ids, ['ev-1']);
  assert.equal(result.usage.stage_durations[0].duration_ms, 1.5);
  assert.throws(() => result.facets[0].evidence_ids.push('x'), TypeError);
  assert.throws(() => { result.versions.policy = 'changed'; }, TypeError);
  assert.ok(Object.isFrozen(UsageSchema.parse({}).stage_durations));
});
test('coverage, evidence references and execution remain distinct', () => {
  const input = partial(); input.status = 'sufficient';
  assert.throws(() => parse_result(input), InvalidRequest);
  input.facets[0].state = 'supported'; input.facets[0].assessment_method = 'review'; input.versions = { policy: 'review.v1' };
  assert.equal(parse_result(input).execution, 'complete');
  input.execution = 'degraded'; input.limitations.push({ code: 'degraded_search' });
  assert.equal(parse_result(input).status, 'sufficient');
  input.evidence = [];
  assert.throws(() => parse_result(input), InvalidRequest);
});
