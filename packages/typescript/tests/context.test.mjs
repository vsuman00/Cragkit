import test from 'node:test';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { Cl100kCounter, render_context, count_context } from '../dist/context.js';
import { ContextBudgetTooSmall, InvalidRequest, UnsupportedCapability } from '../dist/errors.js';
const tokenizerAsset = new URL('../../../artifacts/tokenizers/cl100k_base.tiktoken', import.meta.url);
const digest = value => createHash('sha256').update(value).digest('hex');
const evidence = (text = 'hello') => ({ evidence_id: 'E1', collection: 'c', document_id: 'd', revision_id: 'r', chunk_id: 'k', source_locator: 'source:1', start_byte: 0, end_byte: Buffer.byteLength(text), text, source_sha256: digest(text), text_sha256: digest(text) });

test('TK-r1 renderer fixes field order and preserves literal source text and citations', () => {
  const text = 'é 中文 😀 "\\\n\t<|endoftext|> [E1]';
  const item = evidence(text);
  assert.equal(render_context([]), '[]');
  assert.equal(render_context([Object.fromEntries(Object.entries(item).reverse())]), JSON.stringify([item]));
  assert.deepEqual(JSON.parse(render_context([item])), [item]);
  assert.equal(item.text, text);
});

test('estimated counts exact serialized UTF-8 and reserve separately', () => {
  const input = [evidence('中文')];
  const result = count_context(input, { max_tokens: 1000, reserve: 7 });
  assert.equal(result.context_tokens, Math.ceil(Buffer.byteLength(result.context) / 4));
  assert.equal(result.total_tokens, result.context_tokens + 7);
  assert.equal(result.tokenizer, null);
  assert.equal(result.counting_mode, 'estimated');
  assert.equal(result.renderer, 'cragkit.context.v2');
  assert.ok(Object.isFrozen(result));
  assert.throws(() => count_context([], { max_tokens: 256 }), ContextBudgetTooSmall);
  assert.equal(count_context([], { max_tokens: 257 }).total_tokens, 257);
  assert.throws(() => count_context(input, { max_tokens: 2, reserve: 0 }), ContextBudgetTooSmall);
});

test('strict uses actual cl100k with ordinary special-token text', async t => {
  const counter = await Cl100kCounter.create(tokenizerAsset);
  t.after(() => counter.close());
  assert.equal(counter.count('hello world'), 2);
  assert.equal(counter.count('你好世界'), 5);
  assert.equal(counter.count(' \u0085x'), 4);
  assert.equal(counter.count(' \ufeffx'), 2);
  assert.equal(counter.count('<|endoftext|>'), 7);
  const result = count_context([evidence('中文 <|endoftext|>')], { max_tokens: 1000, reserve: 9, counting_mode: 'strict', counter });
  assert.equal(result.context_tokens, counter.count(result.context));
  assert.equal(result.total_tokens, result.context_tokens + 9);
  assert.equal(result.tokenizer, 'cl100k_base');
  assert.throws(() => counter.count('\ud800'), InvalidRequest);
  assert.throws(() => count_context([], { max_tokens: 1, reserve: 1, counting_mode: 'strict', counter }), ContextBudgetTooSmall);
});

test('boundary errors reject spoofing, malformed options and unsafe native values', () => {
  assert.throws(() => new Cl100kCounter({ encode: () => [] }), UnsupportedCapability);
  assert.equal(count_context([], {max_tokens: 1000, counter: null}).counting_mode, 'estimated');
  for (const counter of [undefined, null, {}, Object.create(Cl100kCounter.prototype)]) {
    const options = { max_tokens: 1000, counting_mode: 'strict' };
    if (counter !== undefined) options.counter = counter;
    assert.throws(() => count_context([], options), UnsupportedCapability);
  }
  for (const options of [{ max_tokens: true }, { max_tokens: 1.5 }, { max_tokens: 1000001 }, { max_tokens: 1000, counting_mode: null }, { max_tokens: 1000, counting_mode: 'unknown' }, { max_tokens: 1000, counter: {} }, { max_tokens: 1000, reserve: null }, { max_tokens: 1000, extra: 1 }]) assert.throws(() => count_context([], options), InvalidRequest);
  let getters = 0;
  assert.throws(() => count_context([], { get max_tokens() { getters++; return 1000; } }), InvalidRequest);
  const accessor = evidence(); Object.defineProperty(accessor, 'text', { enumerable: true, get() { getters++; return 'hello'; } });
  const cycle = []; cycle.push(cycle);
  for (const input of [cycle, [accessor], [evidence(), evidence()], Array(65).fill(evidence()), [{ ...evidence(), text: '\ud800' }], [{ ...evidence(), extra: true }]]) assert.throws(() => render_context(input), InvalidRequest);
  assert.equal(getters, 0);
  assert.throws(() => render_context([evidence(), { ...evidence(), evidence_id: 'E2', source_sha256: '0'.repeat(64) }]), InvalidRequest);
});


test('shared TK-r1 serialized cases match exact context and counting contract', async t => {
  const fixture = JSON.parse(fs.readFileSync(new URL('../../../contracts/fixtures/context.json', import.meta.url), 'utf8'));
  assert.equal(fixture.revision, 'TK-r1');
  const counter = await Cl100kCounter.create(tokenizerAsset);
  t.after(() => counter.close());
  for (const item of fixture.cases) {
    const options = { max_tokens: item.max_tokens, reserve: item.reserve, counting_mode: item.counting_mode };
    if (item.counting_mode === 'strict') options.counter = counter;
    if (item.expected_error) assert.throws(() => count_context(item.evidence, options), error => error.code === item.expected_error);
    else {
      const result = count_context(item.evidence, options);
      assert.equal(result.context, render_context(item.evidence));
      if (item.expected_context !== undefined) assert.equal(result.context, item.expected_context);
      if (item.expected_context_tokens !== undefined) assert.equal(result.context_tokens, item.expected_context_tokens);
      assert.equal(result.total_tokens, result.context_tokens + item.reserve);
    }
  }
});


test('explicit local tokenizer asset rejects missing, corrupt and oversized files', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'cragkit-tokenizer-'));
  try {
    const missing = path.join(directory, 'missing');
    const corrupt = path.join(directory, 'corrupt');
    const oversized = path.join(directory, 'oversized');
    fs.writeFileSync(corrupt, 'invalid ranks');
    fs.writeFileSync(oversized, Buffer.alloc(2_000_001));
    for (const asset of [missing, corrupt, oversized, directory, new URL('https://example.invalid/tokenizer'), undefined]) {
      await assert.rejects(Cl100kCounter.create(asset), InvalidRequest);
    }
    const counter = await Cl100kCounter.create(fileURLToPath(tokenizerAsset));
    counter.close();
    counter.close();
    assert.throws(() => counter.count('hello'), UnsupportedCapability);
    assert.throws(() => count_context([], {max_tokens: 1000, counting_mode: 'strict', counter}), UnsupportedCapability);
  } finally { fs.rmSync(directory, {recursive: true, force: true}); }
});

test('shared TK-r1 token corpus has exact independently pinned counts', async t => {
  const fixture = JSON.parse(fs.readFileSync(new URL('../../../contracts/fixtures/context.json', import.meta.url), 'utf8'));
  const counter = await Cl100kCounter.create(tokenizerAsset);
  try {
    for (const item of fixture.token_cases) assert.equal(counter.count(item.text), item.expected_tokens, item.id);
  } finally { counter.close(); }
});
