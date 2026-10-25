import assert from 'node:assert/strict';
import test from 'node:test';
import { createHash } from 'node:crypto';
import { parse_request, parse_tool_request, parse_scope, EvidenceSchema, parse_result } from 'cragkit/contracts';
import { InvalidRequest } from 'cragkit/errors';
import { pack_evidence } from '../dist/packing.js';

const basic = () => ({ query: 'find exact evidence', collection: 'engineering' });
const scope = () => ({ tenant_id: 'tenant', principal_id: 'principal', authorization_revision: 'revision', grant_ids: ['grant'] });
const nul = 'private\u0000value';
const reject = callback => assert.throws(callback, error => {
  assert.ok(error instanceof InvalidRequest);
  assert.equal(error.cause, undefined);
  assert.deepEqual(error.to_dict(), { code: 'invalid_request', message: 'Invalid retrieval request.', retryable: false });
  return true;
});

for (const [name, parser] of [['request', parse_request], ['tool', parse_tool_request]]) {
  for (const field of ['query', 'collection', 'request_id']) {
    test(`${name} rejects NUL in ${field}`, () => reject(() => parser({ ...basic(), [field]: nul })));
  }
  test(`${name} rejects NUL search hints`, () => reject(() => parser({ ...basic(), search_hints: ['valid', nul] })));
}

for (const field of ['tenant_id', 'principal_id', 'authorization_revision']) {
  test(`scope rejects NUL in ${field}`, () => reject(() => parse_scope({ ...scope(), [field]: nul })));
}
test('scope rejects NUL grant IDs', () => reject(() => parse_scope({ ...scope(), grant_ids: ['valid', nul] })));
for (const field of ['renderer', 'tokenizer']) {
  test(`request rejects NUL output profile ${field}`, () => reject(() => parse_request({ ...basic(), output_profile: { [field]: nul } })));
}

for (const field of ['document_id', 'revision_id', 'language', 'kind', 'tag']) {
  for (const op of ['eq', 'ne', 'in']) {
    test(`nested ${op} ${field} filter rejects NUL strings`, () => {
      const leaf = op === 'in' ? { op, field, values: ['valid', nul] } : { op, field, value: nul };
      reject(() => parse_request({ ...basic(), required_filters: [{ op: 'and', filters: [{ op: 'not', filter: { op: 'or', filters: [leaf] } }] }] }));
    });
  }
}

test('non-NUL control characters, Unicode and empty filter strings retain existing behavior', () => {
  const query = 'é\t中文\n😀';
  const request = parse_request({ ...basic(), query, search_hints: ['line\r\nbreak'], required_filters: [{ op: 'in', field: 'tag', values: ['', '\t', 1, false] }] });
  assert.equal(request.query, query);
  assert.deepEqual(request.required_filters[0].values, ['', '\t', 1, false]);
  assert.equal(parse_tool_request({ ...basic(), query }).query, query);
});

test('NUL source and evidence text retain exact bytes through parsing and packing', async () => {
  const text = 'é\u0000中文😀';
  const digest = createHash('sha256').update(text, 'utf8').digest('hex');
  const source = { collection: 'engineering', document_id: 'd', revision_id: 'r', source_sha256: digest, text };
  const evidence = { ...source, evidence_id: 'e', chunk_id: 'chunk', source_locator: 'source:1', start_byte: 0, end_byte: Buffer.byteLength(text, 'utf8'), text_sha256: digest };
  assert.equal(EvidenceSchema.parse(evidence).text, text);
  const packed = await pack_evidence([evidence], [source], { deadline: performance.now() / 1000 + 10, max_tokens: 10000, reserve: 0, surrounding_bytes: 0 });
  assert.equal(packed.evidence[0].text, text);
  assert.equal(packed.evidence[0].text_sha256, digest);
  assert.equal(JSON.parse(packed.context)[0].text, text);
  const result = parse_result({ request_id: 'request', status: 'partial', evidence: packed.evidence, context: packed.context });
  assert.deepEqual(Buffer.from(result.evidence[0].text, 'utf8'), Buffer.from(text, 'utf8'));
});
