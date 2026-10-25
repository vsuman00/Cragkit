import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { assess_evidence, validate_assessment } from '../dist/assessment.js';
import { InvalidRequest } from '../dist/errors.js';
const hash = text => createHash('sha256').update(text).digest('hex');
const query = 'What are the retry limit and delay?';
const evidence = (text, id = 'e1', extra = {}) => ({evidence_id: id, collection: 'c', document_id: 'd', revision_id: 'r', chunk_id: id,
  source_locator: 'source:1', start_byte: 0, end_byte: Buffer.byteLength(text), text, source_sha256: hash(text), text_sha256: hash(text), ...extra});
const anchor = (item, claim_id = 'claim') => ({claim_id, collection: item.collection, document_id: item.document_id,
  revision_id: item.revision_id, source_sha256: item.source_sha256, start_byte: item.start_byte, end_byte: item.end_byte, text: item.text});
const facet = (id, anchors, extra = {}) => ({facet_id: id, question: id, required: true, absence: 'missing', anchors, ...extra});
const policy = facets => ({policy_id: 'reviewed', version: '1', query_sha256: hash(query), facets});

test('unassessed query stays unknown with explicit conservative status', () => {
  const item = evidence('helpful');
  for (const items of [[], [item]]) {
    const result = assess_evidence(query, items);
    assert.equal(result.status, items.length ? 'partial' : 'insufficient');
    assert.equal(result.policy, 'unassessed.v0');
    assert.deepEqual(result.facets, [{facet_id: 'query', question: 'Original query', required: true, state: 'unknown', evidence_ids: [], assessment_method: 'none', assessment_version: '0'}]);
  }
});

test('two required facets downgrade when one support is removed and optional facets do not confer sufficiency', () => {
  const retry = evidence('retry three times', 'retry'), delay = evidence('wait ten seconds', 'delay', {document_id: 'delay'});
  const configured = policy([facet('limit', [anchor(retry)]), facet('delay', [anchor(delay)])]);
  assert.equal(assess_evidence(query, [retry, delay], configured).status, 'sufficient');
  const partial = assess_evidence(query, [retry], configured);
  assert.equal(partial.status, 'partial');
  assert.deepEqual(partial.facets.map(value => value.state), ['supported', 'missing']);
  assert.equal(assess_evidence(query, [], configured).status, 'insufficient');
  assert.equal(assess_evidence(query, [retry], policy([facet('optional', [anchor(retry)], {required: false})])).status, 'partial');
});

test('q19 conflict projections never make an omitted known incompatible claim sufficient', () => {
  const old = evidence('limit is three', 'old', {revision_id: 'old'});
  const current = evidence('limit is five', 'new', {revision_id: 'new'});
  const configured = policy([facet('limit', [anchor(old, 'three'), anchor(current, 'five')])]);
  for (const items of [[old], [current]]) {
    const result = assess_evidence(query, items, configured);
    assert.equal(result.status, 'partial'); assert.equal(result.facets[0].state, 'unknown');
    assert.deepEqual(result.facets[0].evidence_ids, [items[0].evidence_id]);
  }
  const conflict = assess_evidence(query, [current, old], configured);
  assert.equal(conflict.facets[0].state, 'conflicting');
  assert.deepEqual(conflict.facets[0].evidence_ids, ['new', 'old']);
  const together = evidence('three five');
  const shared = policy([facet('limit', [anchor(together, 'three'), anchor(together, 'five')])]);
  assert.equal(assess_evidence(query, [together], shared).facets[0].state, 'unknown');
});

test('anchors require exact metadata, UTF-8 offsets and whole containment', () => {
  const item = evidence('é中文 retries');
  const exact = {...anchor(item), start_byte: 2, end_byte: 8, text: '中文'};
  assert.equal(assess_evidence(query, [item], policy([facet('unicode', [exact])])).status, 'sufficient');
  for (const changed of [{revision_id: 'other'}, {document_id: 'other'}, {collection: 'other'}, {source_sha256: '0'.repeat(64)}, {start_byte: 3, end_byte: 9}, {text: '文中'}]) {
    const result = assess_evidence(query, [item], policy([facet('unicode', [{...exact, ...changed}])]));
    assert.equal(result.facets[0].state, 'missing');
  }
  const slice = {...item, evidence_id: 'slice', start_byte: 2, end_byte: 5, text: '中', text_sha256: hash('中')};
  assert.equal(assess_evidence(query, [slice], policy([facet('unicode', [exact])])).facets[0].state, 'missing');
});

test('wire validation rejects invented references and malformed facet states', () => {
  const item = evidence('support');
  const valid = assess_evidence(query, [item], policy([facet('f', [anchor(item)])])).facets[0];
  assert.deepEqual(validate_assessment([item], [valid]), [valid]);
  for (const values of [[{...valid, evidence_ids: ['invented']}], [valid, valid], [{...valid, state: 'conflicting'}], [{...valid, state: 'missing'}], [{...valid, unknown: true}]]) {
    assert.throws(() => validate_assessment([item], values), InvalidRequest);
  }
});

test('native boundaries reject accessors, cycles, forged objects and unbound policies', () => {
  const item = evidence('support'), configured = policy([facet('f', [anchor(item)])]);
  let getters = 0;
  const accessor = {...configured}; Object.defineProperty(accessor, 'facets', {enumerable: true, get() {getters++; return configured.facets;}});
  const cyclic = {}; cyclic.self = cyclic;
  for (const bad of [accessor, cyclic, new Date(), {...configured, query_sha256: hash('different')}, {...configured, extra: true}, policy([facet('f', [anchor(item), anchor(item)])]), policy([facet('f', [anchor(item)], {required: 1})])]) {
    assert.throws(() => assess_evidence(query, [item], bad), InvalidRequest);
  }
  const forged = Object.create({}); Object.assign(forged, item);
  assert.throws(() => assess_evidence(query, [forged], configured), InvalidRequest);
  assert.equal(getters, 0);
  for (const invalid of ['', '\ud800', 'x'.repeat(16385)]) assert.throws(() => assess_evidence(invalid, []), InvalidRequest);
  assert.equal(assess_evidence('x'.repeat(16384), []).status, 'insufficient');
});

test('snapshots remain frozen and independent of later caller mutation', () => {
  const item = evidence('support'), configured = policy([facet('f', [anchor(item)])]);
  const result = assess_evidence(query, [item], configured);
  configured.facets[0].question = 'changed'; configured.facets[0].anchors.length = 0; item.text = 'changed';
  assert.equal(result.facets[0].question, 'f');
  assert.deepEqual(result.facets[0].evidence_ids, ['e1']);
  assert.ok(Object.isFrozen(result)); assert.ok(Object.isFrozen(result.facets)); assert.ok(Object.isFrozen(result.facets[0].evidence_ids));
});

test('policy bounds reject excess anchors, cumulative text and oversized version identity', () => {
  const item = evidence('support');
  const base = anchor(item);
  const many = Array.from({length: 5}, (_, group) => facet(`f${group}`, Array.from({length: group === 4 ? 1 : 16}, (_, i) => ({...base, claim_id: `c${i}`}))));
  assert.throws(() => assess_evidence(query, [item], policy(many)), InvalidRequest);
  const huge = {...base, text: 'x'.repeat(32768), end_byte: 32768};
  const excessiveText = policy([facet('f', Array.from({length: 9}, (_, i) => ({...huge, claim_id: `c${i}`})))]);
  assert.throws(() => assess_evidence(query, [item], excessiveText), InvalidRequest);
  assert.throws(() => assess_evidence(query, [item], {...policy([facet('f', [base])]), policy_id: 'p'.repeat(256)}), InvalidRequest);
});
