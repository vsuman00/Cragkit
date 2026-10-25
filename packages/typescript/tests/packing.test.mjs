import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { Cl100kCounter } from '../dist/context.js';
import { pack_evidence } from '../dist/packing.js';
import { ContextBudgetTooSmall, DeadlineExceeded, IntegrityViolation, InvalidRequest } from '../dist/errors.js';
const hash = text => createHash('sha256').update(text).digest('hex');
const source = text => ({ collection: 'c', document_id: 'd', revision_id: 'r', source_sha256: hash(text), text });
const seed = (src, id, start, end) => { const text = Buffer.from(src.text).subarray(start, end).toString(); return { evidence_id: id, collection: src.collection, document_id: src.document_id, revision_id: src.revision_id, chunk_id: id, source_locator: 'source:1', start_byte: start, end_byte: end, text, source_sha256: src.source_sha256, text_sha256: hash(text) }; };
const opts = extra => ({ deadline: performance.now() / 1000 + 10, max_tokens: 10000, reserve: 0, surrounding_bytes: 0, ...extra });

test('PK-r1 merges adjacent Unicode spans and preserves disjoint quotes', async () => {
  const src = source('é中文😀 alpha gap omega');
  const a = seed(src, 'a', 0, 8), b = seed(src, 'b', 8, 12), c = seed(src, 'c', 23, 28);
  const result = await pack_evidence([a, b, c], [src], opts());
  assert.equal(result.evidence.length, 2); assert.equal(result.merged_count, 1);
  assert.deepEqual(Object.values(result.aliases), [['a', 'b'], ['c']]);
  assert.equal(result.evidence[0].text, 'é中文😀');
  assert.match(result.evidence[0].evidence_id, /^span-[a-f0-9]{64}$/);
  assert.equal(result.evidence[1].evidence_id, 'c');
  assert.deepEqual(JSON.parse(result.context), result.evidence);
});

test('expansion preserves whole negation and fenced code paragraphs', async () => {
  const src = source('Heading\n\nDo not delete data.\n\n```js\nconst x = false;\n```');
  const start = Buffer.byteLength('Heading\n\nDo not ');
  const result = await pack_evidence([seed(src, 'a', start, start + 6)], [src], opts({ surrounding_bytes: 40 }));
  assert.equal(result.evidence[0].text, 'Do not delete data.'); assert.equal(result.expanded_count, 1);
  const codeStart = Buffer.byteLength('Heading\n\nDo not delete data.\n\n```js\n');
  const code = await pack_evidence([seed(src, 'b', codeStart, codeStart + 5)], [src], opts({ surrounding_bytes: 40 }));
  assert.equal(code.evidence[0].text, '```js\nconst x = false;\n```');
});

test('facet-first selection skips whole oversize proposals and counts final serialization', async () => {
  const src = source('first gap second');
  const a = seed(src, 'a', 0, 5), b = seed(src, 'b', 10, 16);
  const single = await pack_evidence([b], [src], opts());
  const result = await pack_evidence([a, b], [src], opts({ facet_evidence: [['b']], max_tokens: single.total_tokens }));
  assert.deepEqual(result.evidence.map(item => item.evidence_id), ['b']); assert.equal(result.omitted_count, 1);
  assert.equal(result.context_tokens, Math.ceil(Buffer.byteLength(result.context) / 4));
  await assert.rejects(pack_evidence([], [], opts({ max_tokens: 1, reserve: 1 })), ContextBudgetTooSmall);
});

test('malformed native data, bad sources and byte-boundary tampering fail closed', async () => {
  const src = source('é hello'); const a = seed(src, 'a', 0, 2);
  await assert.rejects(pack_evidence([a], [], opts()), IntegrityViolation);
  await assert.rejects(pack_evidence([a], [{ ...src, text: 'changed' }], opts()), IntegrityViolation);
  await assert.rejects(pack_evidence([{ ...a, start_byte: 1, end_byte: 3 }], [src], opts()), IntegrityViolation);
  let calls = 0; const accessor = { ...a }; Object.defineProperty(accessor, 'text', { enumerable: true, get() { calls++; return 'é'; } });
  await assert.rejects(pack_evidence([accessor], [src], opts()), InvalidRequest); assert.equal(calls, 0);
  await assert.rejects(pack_evidence([a], [src], opts({ facet_evidence: [['unknown']] })), InvalidRequest);
});

test('deadline and cooperative cancellation stop packing', async () => {
  await assert.rejects(pack_evidence([], [], opts({ deadline: 0 })), DeadlineExceeded);
  const controller = new AbortController(); const src = source('hello');
  const pending = pack_evidence([seed(src, 'a', 0, 5)], [src], opts({ signal: controller.signal })); controller.abort();
  await assert.rejects(pending, { name: 'AbortError' });
});


test('source snapshots survive caller mutation and getter installation after the first yield', async () => {
  for (const installGetter of [false, true]) {
    const src = source('trusted original');
    const item = seed(src, 'a', 0, Buffer.byteLength(src.text));
    let calls = 0;
    const pending = pack_evidence([item], [src], opts());
    if (installGetter) Object.defineProperty(src, 'text', { enumerable: true, get() { calls++; return 'tampered source'; } });
    else src.text = 'tampered source';
    src.source_sha256 = hash('tampered source');
    const result = await pending;
    assert.equal(result.evidence[0].text, 'trusted original');
    assert.equal(result.evidence[0].source_sha256, hash('trusted original'));
    assert.equal(calls, 0);
  }
});

test('facet priority snapshots both outer and inner caller arrays before yielding', async () => {
  const src = source('first gap second');
  const a = seed(src, 'a', 0, 5), b = seed(src, 'b', 10, 16);
  const single = await pack_evidence([b], [src], opts());
  const inner = ['b'], facets = [inner];
  const pending = pack_evidence([a, b], [src], opts({facet_evidence: facets, max_tokens: single.total_tokens}));
  inner.splice(0, 1, 'a');
  facets.splice(0, 1, ['a']);
  const result = await pending;
  assert.deepEqual(result.evidence.map(item => item.evidence_id), ['b']);
  assert.equal(result.omitted_count, 1);
});

test('generated span IDs avoid every input ID while unchanged seeds retain their IDs', async () => {
  const src = source('ab gap cd gap ef');
  const base = 'span-' + hash(JSON.stringify([src.collection, src.document_id, src.revision_id, src.source_sha256, 0, 2]));
  const items = [seed(src, 'a', 0, 1), seed(src, 'b', 1, 2), seed(src, base, 7, 9), seed(src, base + '-1', 14, 16)];
  const result = await pack_evidence(items, [src], opts());
  assert.deepEqual(result.evidence.map(item => item.evidence_id), [base + '-2', base, base + '-1']);
  assert.deepEqual(result.aliases[base + '-2'], ['a', 'b']);
  assert.deepEqual(result.aliases[base], [base]);
  assert.deepEqual(result.aliases[base + '-1'], [base + '-1']);
  assert.equal(new Set(result.evidence.map(item => item.evidence_id)).size, 3);
});

test('__proto__ evidence ID is an own alias property without changing its prototype', async () => {
  const src = source('hello');
  const result = await pack_evidence([seed(src, '__proto__', 0, 5)], [src], opts());
  assert.equal(result.evidence[0].evidence_id, '__proto__');
  assert.equal(Object.getPrototypeOf(result.aliases), Object.prototype);
  assert.ok(Object.hasOwn(result.aliases, '__proto__'));
  assert.deepEqual(result.aliases.__proto__, ['__proto__']);
  assert.deepEqual(JSON.parse(JSON.stringify(result.aliases)), JSON.parse('{"__proto__":["__proto__"]}'));
});

test('canonically equivalent Unicode document IDs remain separate immutable revisions', async () => {
  const composed = {...source('abcd'), document_id: 'caf\u00e9'};
  const decomposed = {...source('abcd'), document_id: 'cafe\u0301'};
  assert.equal(composed.document_id.normalize(), decomposed.document_id.normalize());
  const input = [seed(composed, 'a', 0, 2), seed(composed, 'b', 2, 4), seed(decomposed, 'c', 0, 2), seed(decomposed, 'd', 2, 4)];
  const result = await pack_evidence(input, [composed, decomposed], opts());
  assert.deepEqual(result.evidence.map(item => item.document_id), [composed.document_id, decomposed.document_id]);
  assert.deepEqual(result.evidence.map(item => item.text), ['abcd', 'abcd']);
  assert.equal(result.merged_count, 2);
  assert.deepEqual(Object.values(result.aliases), [['a', 'b'], ['c', 'd']]);
  assert.notEqual(result.evidence[0].evidence_id, result.evidence[1].evidence_id);
});

test('strict pinned tokenizer packs an exact fit and omits the whole span one token below', async () => {
  const counter = await Cl100kCounter.create(new URL('../../../artifacts/tokenizers/cl100k_base.tiktoken', import.meta.url));
  try {
    const src = source('Do not delete 中文🙂 <|endoftext|>.');
    const input = [seed(src, 'strict', 0, Buffer.byteLength(src.text))];
    const strict = {counter, counting_mode: 'strict', reserve: 9};
    const reference = await pack_evidence(input, [src], opts(strict));
    assert.equal(reference.context_tokens, counter.count(reference.context));
    assert.equal(reference.total_tokens, reference.context_tokens + 9);
    assert.equal(reference.tokenizer, 'cl100k_base');
    const exact = await pack_evidence(input, [src], opts({...strict, max_tokens: reference.total_tokens}));
    assert.deepEqual(exact.evidence, reference.evidence);
    assert.equal(exact.total_tokens, reference.total_tokens);
    const below = await pack_evidence(input, [src], opts({...strict, max_tokens: reference.total_tokens - 1}));
    assert.deepEqual(below.evidence, []);
    assert.equal(below.context, '[]');
    assert.equal(below.omitted_count, 1);
    assert.equal(below.total_tokens, counter.count('[]') + 9);
  } finally { counter.close(); }
});
