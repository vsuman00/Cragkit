import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { parse_request, parse_tool_request, parse_scope, RequestSchema, ToolRequestSchema, TrustedScopeSchema } from 'cragkit/contracts';
import * as errors from 'cragkit/errors';

const fixture = JSON.parse(readFileSync(new URL('../../../contracts/fixtures/requests.json', import.meta.url), 'utf8'));
const parsers = { request: parse_request, tool: parse_tool_request, scope: parse_scope };
const schemas = { request: RequestSchema, tool: ToolRequestSchema, scope: TrustedScopeSchema };
for (const example of fixture.cases) {
  test(`shared request fixture: ${example.id}`, () => {
    assert.equal(schemas[example.kind].safeParse(example.input).success, example.valid);
    if (example.valid) {
      const parsed = parsers[example.kind](example.input);
      if (example.kind !== 'scope') {
        assert.equal(parsed.query, example.input.query);
        assert.equal(parsed.request_id, example.input.request_id);
      } else assert.equal(parsed.authorization_revision, example.input.authorization_revision);
    } else assert.throws(() => parsers[example.kind](example.input), errors.InvalidRequest);
  });
}
const basic = () => ({ query: 'private query', collection: 'engineering' });
test('defaults and generated request IDs are isolated', () => {
  const first = parse_request(basic());
  const second = parse_request(basic());
  assert.match(first.request_id, /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/);
  assert.notEqual(first.request_id, second.request_id);
  assert.equal(first.schema_version, '0.1');
  assert.deepEqual(first.limits, { deadline_ms: 10000, max_attempts: 3, max_subqueries: 4, max_candidates: 200, max_context_tokens: 2000, max_provider_calls: 16, max_spend_usd: null });
  assert.deepEqual(first.output_profile, { renderer: 'cragkit.context.v1', tokenizer: null, envelope_reserve_tokens: 256, counting_mode: 'estimated' });
  assert.equal(parse_tool_request(basic()).schema_version, '0.1');
});
test('native nonfinite, unsafe and malformed inputs fail safely', () => {
  for (const value of [NaN, Infinity, -Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => parse_request({ ...basic(), required_filters: [{ op: 'eq', field: 'tag', value }] }), errors.InvalidRequest);
    assert.throws(() => parse_request({ ...basic(), limits: { max_spend_usd: value } }), errors.InvalidRequest);
  }
  assert.equal(parse_request({ ...basic(), limits: { max_attempts: 3.0 } }).limits.max_attempts, 3);
  const cycle = { op: 'not' }; cycle.filter = cycle;
  assert.equal(RequestSchema.safeParse({ ...basic(), required_filters: [cycle] }).success, false);
  const input = basic(); input.extra = input;
  assert.throws(() => parse_request(input), errors.InvalidRequest);
  assert.throws(() => parse_request({ ...basic(), limits: undefined }), errors.InvalidRequest);
  const getter = Object.defineProperty(basic(), 'query', { enumerable: true, get() { throw new Error('secret getter'); } });
  assert.throws(() => parse_request(getter), errors.InvalidRequest);
});
test('parsed collections are detached deeply frozen snapshots', () => {
  const input = { ...basic(), search_hints: ['first'], required_filters: [{ op: 'and', filters: [{ op: 'in', field: 'tag', values: ['original'] }] }] };
  const result = parse_request(input);
  input.search_hints.push('changed');
  input.required_filters[0].filters[0].values[0] = 'changed';
  assert.deepEqual(result.search_hints, ['first']);
  assert.equal(result.required_filters[0].filters[0].values[0], 'original');
  assert.throws(() => result.required_filters[0].filters[0].values.push('x'), TypeError);
  assert.throws(() => { result.limits.max_attempts = 9; }, TypeError);
  const scopeInput = { tenant_id: 't', principal_id: 'p', authorization_revision: 'r', grant_ids: ['g'] };
  const scope = parse_scope(scopeInput); scopeInput.grant_ids.push('other');
  assert.deepEqual(scope.grant_ids, ['g']);
  assert.throws(() => scope.grant_ids.push('x'), TypeError);
});
test('typed errors expose only the frozen safe wire envelope', () => {
  const expected = [
    ['InvalidRequest', 'invalid_request', 'Invalid retrieval request.', false],
    ['UnauthorizedScope', 'unauthorized_scope', 'Access scope is not authorized.', false],
    ['UnsupportedCapability', 'unsupported_capability', 'Required capability is unavailable.', false],
    ['IndexNotReady', 'index_not_ready', 'Index is not ready.', true],
    ['EmbeddingProfileMismatch', 'embedding_profile_mismatch', 'Embedding profile does not match.', false],
    ['ProviderUnavailable', 'provider_unavailable', 'Provider is unavailable.', true],
    ['DeadlineExceeded', 'deadline_exceeded', 'Request deadline exceeded.', true],
    ['ContextBudgetTooSmall', 'context_budget_too_small', 'Context budget cannot fit the required envelope.', false],
    ['IntegrityViolation', 'integrity_violation', 'Source integrity validation failed.', false],
  ];
  for (const [name, code, message, retryable] of expected) {
    const error = new errors[name]();
    assert.equal(error.name, name);
    assert.equal(error.message, message);
    assert.deepEqual(error.to_dict(), { code, message, retryable });
    assert.deepEqual(JSON.parse(JSON.stringify(error)), { code, message, retryable });
    assert.ok(Object.isFrozen(error.to_dict()));
  }
  try { parse_request({ ...basic(), unknown: 'credential-secret' }); assert.fail('must reject'); }
  catch (error) {
    assert.ok(error instanceof errors.InvalidRequest);
    assert.equal(error.cause, undefined);
    assert.doesNotMatch(String(error) + JSON.stringify(error), /credential-secret|private query/);
  }
});
test('UTF-8 byte, recursive depth and node ceilings accept exact boundaries', () => {
  assert.equal(parse_request({ ...basic(), query: '🙂'.repeat(4096) }).query.length, 8192);
  let filter = { op: 'eq', field: 'tag', value: '' };
  for (let level = 1; level < 8; level++) filter = { op: 'not', filter };
  assert.ok(parse_request({ ...basic(), required_filters: [filter] }));
  const leaf = () => ({ op: 'eq', field: 'tag', value: 'x' });
  const roots = Array.from({ length: 4 }, () => ({ op: 'and', filters: Array.from({ length: 15 }, leaf) }));
  assert.ok(parse_request({ ...basic(), required_filters: roots }));
  roots[0].filters.push(leaf());
  assert.throws(() => parse_request({ ...basic(), required_filters: roots }), errors.InvalidRequest);
});

test('native input bounds reject deep and oversized unknown fields before recursive validation', () => {
  let deep = null;
  for (let depth = 0; depth < 33; depth++) deep = [deep];
  for (const extra of [deep, Array(4096).fill(null)]) {
    const input = { ...basic(), extra };
    assert.equal(RequestSchema.safeParse(input).success, false);
    assert.throws(() => parse_request(input), errors.InvalidRequest);
  }
});
