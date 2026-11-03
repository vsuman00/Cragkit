import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { RerankingAdapter, FAKE_RERANK_PROFILE } from '../dist/reranking.js';
import { DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability } from '../dist/errors.js';
const fixture = JSON.parse(fs.readFileSync(new URL('../../../contracts/fixtures/reranking.json', import.meta.url), 'utf8'));
const encode = value => new TextEncoder().encode(JSON.stringify(value));
const options = extra => ({ deadline: performance.now() / 1000 + 5, ...extra });
const candidates = [{ candidate_id: 'a', text: 'first' }, { candidate_id: 'b', text: 'second' }];
const scores = [{ candidate_id: 'b', raw_score: -2.5 }, { candidate_id: 'a', raw_score: 1.25 }];

test('RK-r1 synthetic recordings preserve raw scores, ties and complete mappings', async () => {
  for (const item of fixture.cases) {
    const profile = { ...FAKE_RERANK_PROFILE, score_direction: item.score_direction ?? 'higher_is_better' };
    let calls = 0;
    const adapter = new RerankingAdapter(async () => { calls++; return encode(item.response); }, { profile });
    const input = item.candidate_ids?.length === 0 ? [] : fixture.sample.candidates;
    if (item.expected_rejection) await assert.rejects(adapter.rank(fixture.sample.query, input, options({ allow_fallback: true })), IntegrityViolation);
    else {
      const result = await adapter.rank(fixture.sample.query, input, options());
      assert.deepEqual(result.order, item.expected_order);
      assert.equal(calls, item.expected_provider_calls ?? 1);
      assert.deepEqual(result.scores.map(row => row.candidate_id), input.map(row => row.candidate_id));
      assert.ok(Object.isFrozen(result) && Object.isFrozen(result.profile) && Object.isFrozen(result.scores));
      assert.equal(result.synthetic, true);
    }
  }
});

test('strict inputs fail before dispatch, including accessor and prototype objects', async () => {
  let calls = 0, getters = 0;
  const adapter = new RerankingAdapter(async () => { calls++; return encode(scores); });
  const accessor = { candidate_id: 'x', get text() { getters++; return 'private'; } };
  const cases = [Array(41).fill(candidates[0]), [candidates[0], candidates[0]], [{ candidate_id: '', text: '' }], [{ candidate_id: 'a', text: '\ud800' }], [accessor], [Object.assign(Object.create({ inherited: 1 }), candidates[0])], [{ ...candidates[0], extra: true }], [{ candidate_id: 'x'.repeat(513), text: '' }], [{ candidate_id: 'x', text: 'x'.repeat(16385) }]];
  for (const input of cases) await assert.rejects(adapter.rank('query', input, options()), InvalidRequest);
  await assert.rejects(adapter.rank('  \t', candidates, options()), InvalidRequest);
  await assert.rejects(adapter.rank('q', candidates, options({ max_provider_calls: 1001 })), InvalidRequest);
  await assert.rejects(adapter.rank('x'.repeat(8193), candidates, options()), InvalidRequest);
  await assert.rejects(adapter.rank('q', Array.from({ length: 17 }, (_, i) => ({ candidate_id: String(i), text: 'x'.repeat(16384) })), options()), InvalidRequest);
  await assert.rejects(adapter.rank('q', candidates, options({ max_provider_calls: 0 })), InvalidRequest);
  await assert.rejects(adapter.rank('q', candidates, options({ allow_fallback: 'yes' })), InvalidRequest);
  await assert.rejects(adapter.rank('q', candidates, options({ allow_fallback: null })), InvalidRequest);
  await assert.rejects(adapter.rank('q', candidates, options({ max_provider_calls: null })), InvalidRequest);
  assert.equal(calls, 0); assert.equal(getters, 0);
  assert.throws(() => new RerankingAdapter(async () => encode(scores), { profile: { ...FAKE_RERANK_PROFILE, bad: 1 } }), InvalidRequest);
});

test('UTF-8 prefix only changes inference view and reports byte counts', async () => {
  const original = 'a'.repeat(16383) + 'éB';
  let sent;
  const adapter = new RerankingAdapter(async body => { sent = JSON.parse(new TextDecoder().decode(body)); return encode([{ candidate_id: 'a', raw_score: -9 }]); }, { profile: { ...FAKE_RERANK_PROFILE, truncation_policy: 'utf8_prefix' } });
  const result = await adapter.rank('q', [{ candidate_id: 'a', text: original }], options());
  assert.equal(sent.candidates[0].text, 'a'.repeat(16383));
  assert.deepEqual(result.truncations, [{ candidate_id: 'a', original_bytes: 16386, view_bytes: 16383 }]);
  assert.equal(original.endsWith('éB'), true);
});

test('malformed or excessive provider bytes cannot trigger fallback', async () => {
  const raws = [new Uint8Array(65537), new Uint8Array([255]), encode([{ candidate_id: 'a', raw_score: 1 }, { candidate_id: 'b', raw_score: null }]), new TextEncoder().encode('[{"candidate_id":"a","raw_score":1,"raw_score":2},{"candidate_id":"b","raw_score":3}]'), new TextEncoder().encode('[{"candidate_id":"a","raw_score":1e999},{"candidate_id":"b","raw_score":3}]'), encode(scores.map(row => ({ ...row, extra: true }))), encode([{ candidate_id: '\ud800', raw_score: 1 }, scores[0]])];
  for (const raw of raws) await assert.rejects(new RerankingAdapter(async () => raw).rank('q', candidates, options({ allow_fallback: true })), IntegrityViolation);
});

test('fallback is explicit, limited to capability/unavailability, and preserves order', async () => {
  for (const ErrorType of [ProviderUnavailable, UnsupportedCapability]) {
    const adapter = new RerankingAdapter(async () => { throw new ErrorType(); });
    await assert.rejects(adapter.rank('q', candidates, options()), ErrorType);
    const result = await adapter.rank('q', candidates, options({ allow_fallback: true }));
    assert.deepEqual(result.order, ['a', 'b']); assert.deepEqual(result.scores, []);
    assert.equal(result.degraded, true); assert.equal(result.provider_calls, 1);
  }
  let calls = 0;
  const live = new RerankingAdapter(async () => { calls++; return encode(scores); }, { profile: { ...FAKE_RERANK_PROFILE, provider: 'hosted' } });
  await assert.rejects(live.rank('q', candidates, options({ allow_fallback: true })), UnsupportedCapability);
  assert.equal(calls, 0);
});

for (const allow_fallback of [false, true]) {
  test(`unknown transport error is redacted and fatal with fallback=${allow_fallback}`, async () => {
    const marker = 'private-provider-diagnostic';
    const original = new Error(marker, {cause: new Error(marker)});
    let calls = 0;
    const adapter = new RerankingAdapter(async () => { calls++; throw original; });
    await assert.rejects(adapter.rank('q', candidates, options({allow_fallback})), error => {
      assert.ok(error instanceof ProviderUnavailable);
      assert.notEqual(error, original);
      assert.equal(error.code, 'provider_unavailable');
      assert.equal(error.message, 'Provider is unavailable.');
      assert.equal(error.cause, undefined);
      assert.ok(!error.stack.includes(marker));
      assert.ok(!JSON.stringify(error).includes(marker));
      return true;
    });
    assert.equal(calls, 1);
  });
}

for (const Kind of [ProviderUnavailable, UnsupportedCapability, IntegrityViolation,
  UnauthorizedScope, DeadlineExceeded, InvalidRequest]) {
  for (const allow_fallback of [false, true]) {
    test(`declared ${Kind.name} retains classification without private chain, fallback=${allow_fallback}`, async () => {
      const marker = 'private-typed-provider-diagnostic';
      const original = new Kind();
      original.message = marker;
      original.cause = new Error(marker);
      let calls = 0;
      const adapter = new RerankingAdapter(async () => { calls++; throw original; });
      if (allow_fallback && [ProviderUnavailable, UnsupportedCapability].includes(Kind)) {
        const result = await adapter.rank('q', candidates, options({allow_fallback}));
        assert.equal(result.degraded, true);
        assert.equal(result.provider_calls, 1);
      } else {
        await assert.rejects(adapter.rank('q', candidates, options({allow_fallback})), error => {
          assert.equal(error.constructor, Kind);
          assert.notEqual(error, original);
          assert.equal(error.message, new Kind().message);
          assert.equal(error.cause, undefined);
          assert.ok(!error.stack.includes(marker));
          assert.ok(!JSON.stringify(error).includes(marker));
          return true;
        });
      }
      assert.equal(calls, 1);
    });
  }
}

test('caller subclass constructor is not reinvoked', async () => {
  let constructed = 0;
  class CustomUnavailable extends ProviderUnavailable {
    constructor(required) { super(); assert.ok(required); this.message = required; constructed++; }
  }
  const original = new CustomUnavailable('private-subclass-diagnostic');
  await assert.rejects(new RerankingAdapter(async () => { throw original; })
    .rank('q', candidates, options()), error => {
      assert.equal(error.constructor, ProviderUnavailable);
      assert.equal(error.message, 'Provider is unavailable.');
      return true;
    });
  assert.equal(constructed, 1);
});

test('transport abort error retains cancellation class without private message or cause', async () => {
  const original = new DOMException('private-abort-diagnostic', 'AbortError');
  await assert.rejects(new RerankingAdapter(async () => { throw original; })
    .rank('q', candidates, options({allow_fallback:true})), error => {
      assert.equal(error.name, 'AbortError');
      assert.equal(error.message, 'Operation aborted.');
      assert.equal(error.cause, undefined);
      assert.ok(!error.stack.includes('private-abort-diagnostic'));
      return true;
    });
});

test('deadline and cancellation bound noncooperative async transport and retain one slot', async () => {
  for (const cancel of [false, true]) {
    let release, observedSignal;
    const adapter = new RerankingAdapter(async (_, control) => { observedSignal = control.signal; return new Promise(resolve => { release = resolve; }); });
    const controller = new AbortController();
    const pending = adapter.rank('q', candidates, options({ deadline: performance.now() / 1000 + (cancel ? 5 : 0.02), signal: controller.signal, allow_fallback: true }));
    await new Promise(resolve => setImmediate(resolve));
    await assert.rejects(adapter.rank('q', candidates, options()), InvalidRequest);
    if (cancel) controller.abort();
    await assert.rejects(pending, cancel ? { name: 'AbortError' } : DeadlineExceeded);
    assert.equal(observedSignal.aborted, true);
    await assert.rejects(adapter.rank('q', candidates, options()), InvalidRequest);
    release(encode(scores));
    await new Promise(resolve => setImmediate(resolve));
    const next = adapter.rank('q', candidates, options());
    await new Promise(resolve => setImmediate(resolve)); release(encode(scores));
    assert.deepEqual((await next).order, ['a', 'b']);
  }
});

test('preexpired and precancelled requests never dispatch; empty requests cost no calls', async () => {
  let calls = 0;
  const adapter = new RerankingAdapter(async () => { calls++; return encode([]); });
  await assert.rejects(adapter.rank('q', candidates, options({ deadline: performance.now() / 1000 - 1 })), DeadlineExceeded);
  await assert.rejects(adapter.rank('q', candidates, options({ signal: AbortSignal.abort() })), { name: 'AbortError' });
  const result = await adapter.rank('q', [], options({ max_provider_calls: 0 }));
  assert.equal(result.provider_calls, 0); assert.equal(calls, 0);
});


test('opaque whitespace IDs remain valid and raw finite scores are not normalized', async () => {
  const adapter = new RerankingAdapter(async () => encode([{ candidate_id: ' ', raw_score: 1e100 }]));
  const result = await adapter.rank('q', [{ candidate_id: ' ', text: '' }], options());
  assert.deepEqual(result.scores, [{ candidate_id: ' ', raw_score: 1e100 }]);
});
