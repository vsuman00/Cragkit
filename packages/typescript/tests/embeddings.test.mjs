import assert from 'node:assert/strict';
import test from 'node:test';
import {
  EmbeddingAdapter, FAKE_PROFILE, OPENAI_PROFILE, EmbeddingProfileSchema,
  EmbeddingLimitsSchema, EmbeddingPolicySchema, EmbeddingUsageSchema, EmbeddingBatchSchema,
} from '../dist/embeddings.js';
import { InvalidRequest, UnsupportedCapability, ProviderUnavailable, DeadlineExceeded,
  EmbeddingProfileMismatch } from '../dist/errors.js';

// All vectors and transports are synthetic. OpenAI-shaped responses below are local mocks.
const deadline = () => performance.now() / 1000 + 5;
const vector = (index = 0, magnitude = 1) => Array.from({ length: 1536 }, (_, i) => i === index ? magnitude : 0);
const response = (size = 1, usage = null, model = FAKE_PROFILE.model) => ({
  model, data: Array.from({ length: size }, (_, index) => ({ index, embedding: vector(index) })), usage,
});
const encode = value => new TextEncoder().encode(JSON.stringify(value));
const counter = (value, name = 'fake-byte-v1') => ({ name, count: text => value === undefined ? Buffer.byteLength(text) : value });
function transport(payload = response()) {
  const calls = [];
  const callback = async (body, options) => {
    assert.ok(body instanceof Uint8Array);
    calls.push({ body: JSON.parse(new TextDecoder().decode(body)), options });
    return payload instanceof Uint8Array ? payload : encode(payload);
  };
  callback.calls = calls;
  return callback;
}
const run = (adapter, texts = ['a'], options = {}) => adapter.embed_batch(texts, { deadline: deadline(), ...options });
const liveOptions = (policy = {}) => ({ profile: OPENAI_PROFILE, policy: {
  allow_live: true, max_cost_usd: 1, usd_per_million_tokens: 1, ...policy,
} });
function sanitized(error, Type) {
  assert.ok(error instanceof Type);
  assert.equal(error.cause, undefined);
  assert.doesNotMatch(String(error.stack), /private-input|private-response|private-reason/);
  return true;
}

test('request bytes have exact shape; reordered vectors and copied results are deeply frozen', async () => {
  const payload = response(2, { prompt_tokens: 3, total_tokens: 4 });
  payload.data.reverse();
  const callback = transport(payload);
  const result = await run(new EmbeddingAdapter(callback, counter()), [' é', '🙂']);
  assert.deepEqual(callback.calls[0].body, { model: FAKE_PROFILE.model, dimensions: 1536,
    encoding_format: 'float', input: [' é', '🙂'] });
  assert.equal(callback.calls[0].options.max_response_bytes, 1048576);
  assert.ok(callback.calls[0].options.signal instanceof AbortSignal);
  assert.deepEqual(result.vectors, [vector(0), vector(1)]);
  assert.deepEqual(result.profile, FAKE_PROFILE);
  assert.equal(result.synthetic, true); assert.equal(result.provider_calls, 1);
  assert.deepEqual(result.usage, { prompt_tokens: 3, total_tokens: 4, cost_usd: 0, cost_kind: 'known' });
  payload.data[0].embedding[1] = 9;
  for (const object of [result, result.profile, result.vectors, ...result.vectors, result.usage]) assert.ok(Object.isFrozen(object));
  assert.throws(() => { result.vectors[0][0] = 2; }, TypeError);
  assert.equal(result.vectors[1][1], 1);
  assert.deepEqual(EmbeddingBatchSchema.parse(result), result);
});

test('public schemas forbid extras and configuration is copied and frozen', async () => {
  for (const [schema, value] of [[EmbeddingProfileSchema, FAKE_PROFILE], [EmbeddingLimitsSchema, {}],
    [EmbeddingPolicySchema, {}], [EmbeddingUsageSchema, { prompt_tokens: null, total_tokens: null, cost_usd: null, cost_kind: 'unknown' }]]) {
    const parsed = schema.parse(value);
    assert.ok(Object.isFrozen(parsed));
    assert.throws(() => schema.parse({ ...parsed, extra: true }));
  }
  assert.ok(Object.isFrozen(OPENAI_PROFILE)); assert.ok(Object.isFrozen(FAKE_PROFILE));
  const limits = { max_items: 1 };
  const adapter = new EmbeddingAdapter(transport(response(2)), counter(), { limits });
  limits.max_items = 8;
  await assert.rejects(run(adapter, ['a', 'b']), InvalidRequest);
});
for (const [name, maximum] of Object.entries({ max_items: 8, max_input_bytes: 8192,
  max_batch_bytes: 32768, max_input_tokens: 8192, max_batch_tokens: 32768, max_response_bytes: 2097152 })) {
  test(`strict limit ${name}`, () => {
    assert.equal(EmbeddingLimitsSchema.parse({ [name]: maximum })[name], maximum);
    for (const value of [0, -1, true, 1.5, '1', maximum + 1]) assert.throws(() => EmbeddingLimitsSchema.parse({ [name]: value }));
  });
}
test('adapter revalidates untrusted configurations with sanitized errors', () => {
  for (const options of [{ profile: null }, { profile: { ...FAKE_PROFILE, model: 'other' } },
    { profile: { ...FAKE_PROFILE, dimensions: true } }, { limits: { max_items: 9 } },
    { limits: { max_items: true } }, { policy: { max_cost_usd: NaN } },
    { policy: { allow_live: 'private-input' } }, { policy: { extra: true } }]) {
    assert.throws(() => new EmbeddingAdapter(transport(), counter(), options), error => sanitized(error, InvalidRequest));
  }
  for (const [field, value] of [['max_cost_usd', -1], ['max_cost_usd', Infinity], ['max_cost_usd', 1000000.1],
    ['usd_per_million_tokens', 0], ['usd_per_million_tokens', NaN], ['usd_per_million_tokens', 1000000.1]]) {
    assert.throws(() => EmbeddingPolicySchema.parse({ [field]: value }));
  }
});
for (const texts of [[], 'scalar', new Set(['a']), [''], [1], [new Uint8Array([97])], ['\ud800'], ['\udc00'], Array(9).fill('a')]) {
  test(`invalid input never dispatches ${JSON.stringify(texts)}`, async () => {
    const callback = transport();
    await assert.rejects(run(new EmbeddingAdapter(callback, counter()), texts), InvalidRequest);
    assert.equal(callback.calls.length, 0);
  });
}
for (const count of [0, -1, true, 1.5, '1', null, NaN, Infinity, 2147483648]) {
  test(`invalid counter output ${String(count)}`, async () => {
    const callback = transport();
    await assert.rejects(run(new EmbeddingAdapter(callback, counter(count))), InvalidRequest);
    assert.equal(callback.calls.length, 0);
  });
}
test('byte and token limits reject before dispatch; exact boundaries preserve whitespace', async () => {
  for (const [limits, texts, count] of [[{ max_input_bytes: 3 }, ['🙂'], 1], [{ max_batch_bytes: 3 }, ['é', 'é'], 1],
    [{ max_input_tokens: 2 }, ['a'], 3], [{ max_batch_tokens: 3 }, ['a', 'b'], 2]]) {
    const callback = transport();
    await assert.rejects(run(new EmbeddingAdapter(callback, counter(count), { limits }), texts), InvalidRequest);
    assert.equal(callback.calls.length, 0);
  }
  const callback = transport(response(2));
  await run(new EmbeddingAdapter(callback, counter(2), { limits: { max_items: 2, max_input_bytes: 4,
    max_batch_bytes: 8, max_input_tokens: 2, max_batch_tokens: 4 } }), ['🙂', '    ']);
  assert.deepEqual(callback.calls[0].body.input, ['🙂', '    ']);
});
for (const raw of [new Uint8Array([255]), new Uint8Array([0xed, 0xa0, 0x80]), Buffer.from('{'), Buffer.from('[]'), Buffer.from('null'),
  Buffer.from('{"data":NaN}'), Buffer.from('{"data":Infinity}'), Buffer.from('{"data":-Infinity}'),
  Buffer.from('{"model":"a","model":"a"}'), Buffer.from('{"model":"a","mo\\u0064el":"a"}'),
  Buffer.from(JSON.stringify(response()).replace('"usage":null', '"usage":null,"ignored":{"x":1,"\\u0078":2}')),
  Buffer.from('['.repeat(1100) + ']'.repeat(1100))]) {
  test(`malformed raw JSON rejects safely (${raw.length} bytes)`, async () => {
    await assert.rejects(run(new EmbeddingAdapter(transport(raw), counter())), error => sanitized(error, ProviderUnavailable));
  });
}
test('response must be Uint8Array or Buffer, with inclusive byte bound', async () => {
  const raw = encode(response());
  for (const bytes of [raw, Buffer.from(raw)]) await run(new EmbeddingAdapter(transport(bytes), counter(), { limits: { max_response_bytes: raw.length } }));
  await assert.rejects(run(new EmbeddingAdapter(transport(raw), counter(), { limits: { max_response_bytes: raw.length - 1 } })), ProviderUnavailable);
  for (const value of [JSON.stringify(response()), raw.buffer, [...raw], null]) {
    await assert.rejects(run(new EmbeddingAdapter(async () => value, counter())), ProviderUnavailable);
  }
});
for (const component of [true, '1', null, NaN, Infinity, -Infinity, 1e308]) {
  test(`invalid vector component ${String(component)}`, async () => {
    const payload = response(); payload.data[0].embedding[0] = component;
    await assert.rejects(run(new EmbeddingAdapter(transport(payload), counter())), ProviderUnavailable);
  });
}
test('norm tolerance preserves values and never normalizes invalid vectors', async () => {
  for (const magnitude of [0, 0.998, 1.002]) {
    const payload = response(); payload.data[0].embedding = vector(0, magnitude);
    await assert.rejects(run(new EmbeddingAdapter(transport(payload), counter())), ProviderUnavailable);
  }
  const payload = response(); payload.data[0].embedding = vector(0, 1.0009);
  assert.equal((await run(new EmbeddingAdapter(transport(payload), counter()))).vectors[0][0], 1.0009);
});
test('wrong profile or dimensions are distinct from malformed data', async () => {
  for (const change of ['model', 1535, 1537]) {
    const payload = response();
    if (change === 'model') payload.model = 'different-model';
    else payload.data[0].embedding = Array(change).fill(1);
    await assert.rejects(run(new EmbeddingAdapter(transport(payload), counter())), EmbeddingProfileMismatch);
  }
  for (const data of [null, {}, [null], [{ index: 0 }], [{ index: 0, embedding: 'wrong' }]]) {
    await assert.rejects(run(new EmbeddingAdapter(transport({ ...response(), data }), counter())), ProviderUnavailable);
  }
});
for (const indexes of [[0, 0], [0], [0, 2], [-1, 1], [false, 1], ['0', 1]]) {
  test(`index coverage ${JSON.stringify(indexes)}`, async () => {
    const payload = response(2); payload.data = indexes.map(index => ({ index, embedding: vector() }));
    await assert.rejects(run(new EmbeddingAdapter(transport(payload), counter()), ['a', 'b']), ProviderUnavailable);
  });
}
for (const spelling of ['0.0', '0e0', '0E+0']) {
  test(`integer indexes reject source spelling ${spelling}`, async () => {
    const raw = Buffer.from(JSON.stringify(response()).replace('"index":0', `"index":${spelling}`));
    await assert.rejects(run(new EmbeddingAdapter(transport(raw), counter())), ProviderUnavailable);
  });
}
for (const usage of [{}, { prompt_tokens: 1 }, { prompt_tokens: true, total_tokens: 1 },
  { prompt_tokens: -1, total_tokens: 1 }, { prompt_tokens: 2, total_tokens: 1 },
  { prompt_tokens: 0, total_tokens: 2147483648 }]) {
  test(`malformed usage ${JSON.stringify(usage)}`, async () => {
    await assert.rejects(run(new EmbeddingAdapter(transport(response(1, usage)), counter())), ProviderUnavailable);
  });
}
for (const field of ['prompt_tokens', 'total_tokens']) for (const spelling of ['1.0', '1e0']) {
  test(`usage ${field} rejects source spelling ${spelling}`, async () => {
    const raw = Buffer.from(JSON.stringify(response(1, { prompt_tokens: 1, total_tokens: 1 })).replace(`"${field}":1`, `"${field}":${spelling}`));
    await assert.rejects(run(new EmbeddingAdapter(transport(raw), counter())), ProviderUnavailable);
  });
}
test('missing fake usage stays null and live permission does not change fake identity', async () => {
  const payload = response(); delete payload.usage;
  const result = await run(new EmbeddingAdapter(transport(payload), counter(), { policy: { allow_live: true } }));
  assert.equal(result.synthetic, true); assert.deepEqual(result.profile, FAKE_PROFILE);
  assert.deepEqual(result.usage, { prompt_tokens: null, total_tokens: null, cost_usd: 0, cost_kind: 'known' });
  const large = await run(new EmbeddingAdapter(transport(response(1, { prompt_tokens: 2147483647, total_tokens: 2147483647 })), counter()));
  assert.equal(large.usage.total_tokens, 2147483647);
});
test('mocked OpenAI usage is unknown or estimated, and excess usage fails accounting', async () => {
  for (const [usage, cost, kind] of [[null, null, 'unknown'], [{ prompt_tokens: 0, total_tokens: 0 }, 0, 'estimated'],
    [{ prompt_tokens: 2, total_tokens: 2 }, 0.000002, 'estimated']]) {
    const result = await run(new EmbeddingAdapter(transport(response(1, usage, OPENAI_PROFILE.model)), counter(2, 'cl100k_base'), liveOptions()));
    assert.equal(result.synthetic, false); assert.equal(result.usage.cost_usd, cost); assert.equal(result.usage.cost_kind, kind);
    assert.equal(result.usage.prompt_tokens, usage?.prompt_tokens ?? null);
  }
  await assert.rejects(run(new EmbeddingAdapter(transport(response(1, { prompt_tokens: 3, total_tokens: 3 }, OPENAI_PROFILE.model)), counter(2, 'cl100k_base'), liveOptions())), ProviderUnavailable);
});
test('live gates and exact decimal admission reject without dispatch', async () => {
  for (const policy of [{}, { allow_live: true }, { allow_live: true, usd_per_million_tokens: 1 },
    { allow_live: true, max_cost_usd: 0.0000008999999999999999, usd_per_million_tokens: 0.3 },
    { allow_live: true, max_cost_usd: 0.00151, usd_per_million_tokens: 1.234 }]) {
    const callback = transport();
    await assert.rejects(async () => run(new EmbeddingAdapter(callback, counter(policy.max_cost_usd === 0.00151 ? 1234 : 3, 'cl100k_base'), { profile: OPENAI_PROFILE, policy })), UnsupportedCapability);
    assert.equal(callback.calls.length, 0);
  }
  const callback = transport();
  await assert.rejects(async () => run(new EmbeddingAdapter(callback, counter(1, 'wrong'))), UnsupportedCapability);
  assert.equal(callback.calls.length, 0);
});
test('exact decimal equality, exponent extremes and reported estimates', async () => {
  for (const [count, price, budget, expected] of [[3, 0.3, 0.0000009, 0.0000009],
    [1234, 1.234, 0.002, 0.001522756], [1, 1000000, 1, 1],
    [1, Number.MIN_VALUE, Number.MIN_VALUE, 0]]) {
    const callback = transport(response(1, { prompt_tokens: count, total_tokens: count }, OPENAI_PROFILE.model));
    const result = await run(new EmbeddingAdapter(callback, counter(count, 'cl100k_base'), liveOptions({ max_cost_usd: budget, usd_per_million_tokens: price })));
    assert.equal(result.usage.cost_usd, expected); assert.equal(result.usage.cost_kind, 'estimated');
    assert.equal(callback.calls.length, 1);
  }
  const callback = transport();
  await assert.rejects(run(new EmbeddingAdapter(callback, counter(1, 'cl100k_base'), liveOptions({ max_cost_usd: 0, usd_per_million_tokens: Number.MIN_VALUE }))), UnsupportedCapability);
  assert.equal(callback.calls.length, 0);
});
for (const value of [true, null, 'later', NaN, Infinity, -Infinity]) {
  test(`invalid deadline ${String(value)}`, async () => {
    const callback = transport();
    await assert.rejects(run(new EmbeddingAdapter(callback, counter()), ['a'], { deadline: value }), InvalidRequest);
    assert.equal(callback.calls.length, 0);
  });
}
test('expired and post-count deadline never dispatch', async () => {
  const callback = transport();
  await assert.rejects(run(new EmbeddingAdapter(callback, counter()), ['a'], { deadline: performance.now() / 1000 - 1 }), DeadlineExceeded);
  const stop = performance.now() / 1000 + 0.005;
  const slowCounter = { name: 'fake-byte-v1', count() { while (performance.now() / 1000 <= stop) {} return 1; } };
  await assert.rejects(run(new EmbeddingAdapter(callback, slowCounter), ['a'], { deadline: stop }), DeadlineExceeded);
  assert.equal(callback.calls.length, 0);
});
test('counter and transport failures redact private context and allow reuse', async () => {
  let countFailure = true;
  const callback = transport();
  const adapter = new EmbeddingAdapter(callback, { name: 'fake-byte-v1', count() {
    if (countFailure) { countFailure = false; throw new Error('private-input'); } return 1;
  } });
  await assert.rejects(run(adapter), error => sanitized(error, InvalidRequest));
  assert.equal(callback.calls.length, 0); await run(adapter);
  let failure = true;
  const flaky = new EmbeddingAdapter(async () => { if (failure) { failure = false; throw new Error('private-response'); } return encode(response()); }, counter());
  await assert.rejects(run(flaky), error => sanitized(error, ProviderUnavailable)); await run(flaky);
  let timeout = true;
  const timed = new EmbeddingAdapter(async () => { if (timeout) { timeout = false; throw new DOMException('private-response', 'TimeoutError'); } return encode(response()); }, counter());
  await assert.rejects(run(timed), error => sanitized(error, DeadlineExceeded)); await run(timed);
});
function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }
for (const mode of ['abort', 'deadline']) {
  test(`${mode} rejects overlap, awaits cooperative cleanup and permits same-instance reuse`, { timeout: 5000 }, async () => {
    const started = deferred(), finishCleanup = deferred(), cleanupStarted = deferred();
    let calls = 0, cleaned = false, dispatched;
    const callback = async (body, { signal }) => {
      calls++; dispatched = JSON.parse(new TextDecoder().decode(body));
      if (calls === 1) {
        started.resolve();
        await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }));
        cleanupStarted.resolve(); await finishCleanup.promise; cleaned = true;
        throw new DOMException('private-response', 'AbortError');
      }
      return encode(response());
    };
    callback.close = () => { throw new Error('caller resource closed'); };
    const ownCounter = counter(); ownCounter.close = callback.close;
    const adapter = new EmbeddingAdapter(callback, ownCounter);
    const controller = new AbortController(), texts = ['original'];
    const operation = run(adapter, texts, { signal: controller.signal,
      deadline: mode === 'deadline' ? performance.now() / 1000 + 0.03 : deadline() });
    let settled = false; operation.then(() => { settled = true; }, () => { settled = true; });
    await started.promise; texts[0] = 'changed';
    assert.deepEqual(dispatched.input, ['original']);
    await assert.rejects(run(adapter, ['overlap']), ProviderUnavailable); assert.equal(calls, 1);
    if (mode === 'abort') controller.abort(new Error('private-reason'));
    await cleanupStarted.promise;
    assert.equal(settled, false);
    await assert.rejects(run(adapter, ['cleanup-overlap']), ProviderUnavailable); assert.equal(calls, 1);
    finishCleanup.resolve();
    await assert.rejects(operation, error => mode === 'deadline' ? sanitized(error, DeadlineExceeded)
      : (assert.equal(error.name, 'AbortError'), assert.equal(error.cause, undefined), assert.doesNotMatch(String(error.stack), /private-reason|private-response/), true));
    assert.equal(cleaned, true); await run(adapter, ['reuse']); assert.equal(calls, 2);
  });
}
test('already aborted caller signal never dispatches and redacts its reason', async () => {
  const controller = new AbortController(); controller.abort(new Error('private-reason'));
  const callback = transport(), adapter = new EmbeddingAdapter(callback, counter());
  await assert.rejects(run(adapter, ['a'], { signal: controller.signal }), error => {
    assert.equal(error.name, 'AbortError'); assert.doesNotMatch(String(error.stack), /private-reason/); return true;
  });
  assert.equal(callback.calls.length, 0); await run(adapter);
});

test('finite vector float and exponent tokens are valid; numeric overflow fails safely', async () => {
  const valid = JSON.stringify(response()).replace('"embedding":[1,0', '"embedding":[1e0,0.0');
  await run(new EmbeddingAdapter(transport(Buffer.from(valid)), counter()));
  const overflow = JSON.stringify(response()).replace('"embedding":[1,0', '"embedding":[1e400,0');
  await assert.rejects(run(new EmbeddingAdapter(transport(Buffer.from(overflow)), counter())), error => sanitized(error, ProviderUnavailable));
});

test('ignored metadata honors exact JSON depth boundary', async () => {
  for (const depth of [32, 33]) {
    const payload = response();
    let ignored = null;
    for (let i = 1; i < depth; i++) ignored = [ignored];
    payload.ignored = ignored;
    const operation = run(new EmbeddingAdapter(transport(payload), counter()));
    if (depth === 32) await operation;
    else await assert.rejects(operation, ProviderUnavailable);
  }
});

test('array snapshot reads bounded indexes without invoking a custom iterator', async () => {
  const texts = ['a'];
  let iterated = false;
  texts[Symbol.iterator] = () => { iterated = true; throw new Error('private-input'); };
  const callback = transport();
  const result = await run(new EmbeddingAdapter(callback, counter()), texts);
  assert.equal(result.vectors[0][0], 1);
  assert.equal(iterated, false); assert.equal(callback.calls.length, 1);
  assert.deepEqual(callback.calls[0].body.input, ['a']);
});

test('counter tokenizer name is read once during construction', async () => {
  let nameReads = 0;
  const tokenCounter = {
    get name() {
      nameReads++;
      if (nameReads > 1) throw new Error('private-input');
      return 'fake-byte-v1';
    },
    count() { return 1; },
  };
  const callback = transport();
  const adapter = new EmbeddingAdapter(callback, tokenCounter);
  assert.equal(nameReads, 1);
  const result = await run(adapter);
  assert.equal(result.profile.tokenizer, 'fake-byte-v1');
  assert.equal(nameReads, 1); assert.equal(callback.calls.length, 1);
});
