import { createHash } from 'node:crypto';
import { types } from 'node:util';
import { EmbeddingProfileMismatch, IntegrityViolation, InvalidRequest, UnsupportedCapability } from './errors.js';
import { parse_config, point_id } from './qdrant-contract.js';
import { encode_dense, encode_sparse, type DenseVector, type SparseVector } from './qdrant-vectors.js';

type Json = string | null | readonly Json[];
type RecordValue = Record<string, unknown>;
export type EncodedManifest = Readonly<{ value: readonly Json[]; encoded_bytes: readonly number[]; sha256: string }>;
export type DenseReplay = Readonly<{ blob: readonly number[]; blob_sha256: string; input_sha256: string; encoded: DenseVector }>;
export type SparseReplay = Readonly<{ blob: readonly number[]; blob_sha256: string; input_sha256: string; encoded: SparseVector }>;
const MAX_SOURCE = 16777216;
const MAX_MANIFEST = 1048576;
const DOMAIN = Buffer.from('cragkit.qdrant.replay.v1\0', 'ascii');
const DENSE_FIELDS = ['profile_id', 'provider', 'model', 'dimensions', 'tokenizer', 'normalization'];
const SPARSE_FIELDS = ['profile_id', 'encoder', 'model', 'revision', 'vocabulary', 'preprocessing', 'weighting', 'corpus_statistics_revision'];
const TARGET = ['tenant_id', 'collection', 'document_id'];
const FENCES = ['expected_authorization_revision', 'expected_mutation_epoch'];
const MANIFEST_FIELDS = ['backend_namespace', 'physical_collection', 'collection_incarnation', ...TARGET,
  'revision_id', 'generation_id', 'source_sha256', 'source_bytes', 'source_locator', 'parser_id',
  'chunker_profile', 'dense_profile', 'sparse_profile', 'members'];
const MEMBER_FIELDS = ['chunk_id', 'point_id', 'start_byte', 'end_byte', 'text_sha256', 'dense_input_sha256', 'sparse_input_sha256'];
const AUTH_FIELDS = ['authorization_revision', 'principal_ids', 'grant_ids', 'language', 'kind', 'tag', 'tombstoned'];

const sha = (bytes: Uint8Array | string): string => createHash('sha256').update(bytes).digest('hex');
const invalidUnicode = (value: string): boolean => /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value);

/** Snapshot only native data descriptors, with a separate bounded metadata budget. */
function snapshot(input: unknown): unknown {
  let nodes = 0;
  const ancestors = new Set<object>();
  function visit(value: unknown, depth: number): unknown {
    if (++nodes > 4096 || depth > 32) throw new InvalidRequest();
    if (value === null || typeof value === 'boolean') return value;
    if (typeof value === 'number') {
      if (!Number.isFinite(value)) throw new InvalidRequest();
      return value;
    }
    if (typeof value === 'string') {
      if (value.length > 1024 || invalidUnicode(value) || Buffer.byteLength(value) > 1024) throw new InvalidRequest();
      return value;
    }
    if (typeof value !== 'object' || types.isProxy(value) || ancestors.has(value)) throw new InvalidRequest();
    ancestors.add(value);
    try {
      if (Array.isArray(value)) {
        const values = arrayDescriptors(value, 0, 4096);
        return values.map(item => visit(item, depth + 1));
      }
      if (Object.getPrototypeOf(value) !== Object.prototype) throw new InvalidRequest();
      const keys = Reflect.ownKeys(value);
      if (keys.length > 4096) throw new InvalidRequest();
      const result: RecordValue = {};
      for (const key of keys) {
        if (typeof key !== 'string' || key.length > 256 || invalidUnicode(key) || Buffer.byteLength(key) > 256) throw new InvalidRequest();
        const descriptor = Object.getOwnPropertyDescriptor(value, key);
        if (!descriptor || !('value' in descriptor)) throw new InvalidRequest();
        Object.defineProperty(result, key, { value: visit(descriptor.value, depth + 1), enumerable: true });
      }
      return result;
    } finally {
      ancestors.delete(value);
    }
  }
  return visit(input, 0);
}

function arrayDescriptors(input: unknown, min: number, max: number): unknown[] {
  if (typeof input !== 'object' || input === null || types.isProxy(input)
    || !Array.isArray(input) || Object.getPrototypeOf(input) !== Array.prototype) throw new InvalidRequest();
  const length: unknown = Object.getOwnPropertyDescriptor(input, 'length')?.value;
  if (typeof length !== 'number' || !Number.isSafeInteger(length) || length < min || length > max) throw new InvalidRequest();
  if (Reflect.ownKeys(input).length !== length + 1) throw new InvalidRequest();
  const result: unknown[] = [];
  for (let i = 0; i < length; i++) {
    const descriptor = Object.getOwnPropertyDescriptor(input, String(i));
    if (!descriptor || !('value' in descriptor)) throw new InvalidRequest();
    result.push(descriptor.value);
  }
  return result;
}

function shape(value: unknown, fields: readonly string[]): RecordValue {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new InvalidRequest();
  const record = value as RecordValue;
  const keys = Object.keys(record);
  if (keys.length !== fields.length || !fields.every(key => Object.hasOwn(record, key))) throw new InvalidRequest();
  return record;
}

function text(value: unknown, limit = 256, nonblank = true): string {
  if (typeof value !== 'string' || value.length > limit || invalidUnicode(value)
    || Buffer.byteLength(value) > limit || value.includes('\0')
    || (nonblank && !/[^ \t\r\n\f\v]/.test(value))) throw new InvalidRequest();
  return value;
}

function integer(value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < min || value > max) throw new InvalidRequest();
  return value === 0 ? 0 : value;
}

function digest(value: unknown): string {
  if (typeof value !== 'string' || value.length !== 64 || !/^[0-9a-f]{64}$/.test(value)) throw new InvalidRequest();
  return value;
}

function freezeJson(value: Json): Json {
  if (Array.isArray(value)) {
    for (const child of value) freezeJson(child);
    Object.freeze(value);
  }
  return value;
}

function encode(value: Json[]): EncodedManifest {
  const json = JSON.stringify(value);
  if (Buffer.byteLength(json) > MAX_MANIFEST) throw new InvalidRequest();
  const bytes = Buffer.from(json, 'utf8');
  return Object.freeze({ value: freezeJson(value) as readonly Json[], encoded_bytes: Object.freeze(Array.from(bytes)), sha256: sha(bytes) });
}

function target(record: RecordValue): string[] {
  return [text(record.tenant_id), text(record.collection, 128), text(record.document_id)];
}

function fences(record: RecordValue): string[] {
  return [text(record.expected_authorization_revision), String(integer(record.expected_mutation_epoch))];
}

function profilePairs(profile: Record<string, unknown>, fields: string[]): Json[] {
  return fields.map(key => [key, String(profile[key])]);
}

/** This seals declared metadata; it cannot establish vector or publication authority. */
export function encode_manifest(input: unknown, canonical_text: unknown): EncodedManifest {
  const record = shape(snapshot(input), MANIFEST_FIELDS);
  if (typeof canonical_text !== 'string' || canonical_text.length > MAX_SOURCE
    || invalidUnicode(canonical_text)) throw new InvalidRequest();
  const count = Buffer.byteLength(canonical_text, 'utf8');
  if (count < 1 || count > MAX_SOURCE) throw new InvalidRequest();
  const sourceBytes = integer(record.source_bytes, 1, MAX_SOURCE);
  const sourceDigest = digest(record.source_sha256);
  const config = parse_config({ backend_namespace: record.backend_namespace,
    physical_collection: record.physical_collection, collection_incarnation: record.collection_incarnation,
    dense_profile: record.dense_profile, sparse_profile: record.sparse_profile });
  const source = Buffer.from(canonical_text, 'utf8');
  if (source.length !== sourceBytes || sha(source) !== sourceDigest) throw new IntegrityViolation();
  const [tenant, collection, document] = target(record);
  const revision = text(record.revision_id), generation = text(record.generation_id);
  const locator = text(record.source_locator), parser = text(record.parser_id), chunker = text(record.chunker_profile);
  const members = arrayDescriptors(record.members, 1, 64);
  const chunks = new Set<string>(), points = new Set<string>();
  const tuples: { chunk: string; tuple: Json[] }[] = [];
  for (const item of members) {
    const member = shape(item, MEMBER_FIELDS);
    const chunk = text(member.chunk_id), suppliedPoint = text(member.point_id);
    if (suppliedPoint.length !== 36
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(suppliedPoint)) {
      throw new InvalidRequest();
    }
    const start = integer(member.start_byte), end = integer(member.end_byte);
    if (start >= end || end > source.length) throw new IntegrityViolation();
    if (end - start > 32768) throw new InvalidRequest();
    const excerptDigest = digest(member.text_sha256), denseSeal = digest(member.dense_input_sha256);
    const sparseSeal = member.sparse_input_sha256 === null ? null : digest(member.sparse_input_sha256);
    if ((config.sparse_profile === null) !== (sparseSeal === null)) throw new IntegrityViolation();
    const identity = ['cragkit.qdrant.point.v1', config.backend_namespace, config.physical_collection,
      config.collection_incarnation, tenant, collection, document, revision, generation, chunk,
      config.dense_profile.profile_id, config.sparse_profile?.profile_id ?? ''];
    if (chunks.has(chunk) || points.has(suppliedPoint) || suppliedPoint !== point_id(identity)
    ) throw new IntegrityViolation();
    const excerpt = source.subarray(start, end);
    try {
      new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(excerpt);
    } catch (error) {
      if (error instanceof TypeError) throw new IntegrityViolation();
      throw error;
    }
    if (sha(excerpt) !== excerptDigest) throw new IntegrityViolation();
    chunks.add(chunk); points.add(suppliedPoint);
    tuples.push({ chunk, tuple: [identity, suppliedPoint, String(start), String(end), excerptDigest, denseSeal, sparseSeal] });
  }
  tuples.sort((a, b) => Buffer.compare(Buffer.from(a.chunk), Buffer.from(b.chunk)));
  return encode(['cragkit.qdrant.manifest.v1', config.backend_namespace, config.physical_collection,
    config.collection_incarnation, tenant, collection, document, revision, generation, sourceDigest,
    String(sourceBytes), locator, parser, chunker,
    profilePairs(config.dense_profile, DENSE_FIELDS), config.sparse_profile === null ? null : profilePairs(config.sparse_profile, SPARSE_FIELDS),
    String(tuples.length), tuples.map(item => item.tuple)]);
}

function acl(value: unknown): string[] {
  const values = arrayDescriptors(value, 0, 64).map(item => text(item));
  return [...new Set(values)].sort((a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b)));
}

function authorization(value: unknown): Json[] {
  const record = shape(value, AUTH_FIELDS);
  if (typeof record.tombstoned !== 'boolean') throw new InvalidRequest();
  return [text(record.authorization_revision), acl(record.principal_ids), acl(record.grant_ids),
    ...['language', 'kind', 'tag'].map(key => record[key] === null ? null : text(record[key], 1024, false)),
    record.tombstoned ? 'true' : 'false'];
}

export function encode_stage_intent(input: unknown): EncodedManifest {
  const record = shape(snapshot(input), ['intent_id', ...TARGET, 'manifest_sha256', 'expected_active_generation_id', ...FENCES, 'initial_authorization']);
  const expectedActive = record.expected_active_generation_id === null ? null : text(record.expected_active_generation_id);
  const expectedFences = fences(record);
  const initial = record.initial_authorization === null ? null : authorization(record.initial_authorization);
  if (initial !== null && (expectedActive !== null || expectedFences[1] !== '1'
    || initial[0] !== expectedFences[0] || initial[6] !== 'false')) throw new InvalidRequest();
  return encode(['cragkit.qdrant.intent.v1', 'stage', text(record.intent_id), ...target(record),
    digest(record.manifest_sha256), expectedActive, ...expectedFences, initial]);
}

export function encode_security_intent(input: unknown): EncodedManifest {
  const record = shape(snapshot(input), ['action', 'intent_id', ...TARGET, ...FENCES, 'authorization']);
  if (record.action !== 'update_authorization' && record.action !== 'tombstone') throw new InvalidRequest();
  const security = authorization(record.authorization);
  if (record.action === 'tombstone' && security[6] !== 'true') throw new InvalidRequest();
  return encode(['cragkit.qdrant.intent.v1', record.action, text(record.intent_id), ...target(record), ...fences(record), security]);
}

export function encode_purge_intent(input: unknown): EncodedManifest {
  const record = shape(snapshot(input), ['intent_id', ...TARGET, 'tombstone_intent_payload_sha256', ...FENCES]);
  return encode(['cragkit.qdrant.intent.v1', 'purge', text(record.intent_id), ...target(record),
    digest(record.tombstone_intent_payload_sha256), ...fences(record)]);
}

/** Original binary64 snapshots must survive durable replay without readmitting rounded values. */
function originals(input: unknown, min: number, max: number): number[] {
  return arrayDescriptors(input, min, max).map(value => {
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new InvalidRequest();
    return value;
  });
}

function replayBlob(kind: 'dense' | 'sparse', values: number[], indices?: readonly number[]): readonly number[] {
  const name = Buffer.from(kind, 'ascii');
  const bytes = Buffer.alloc(DOMAIN.length + 4 + name.length + 4 + values.length * (indices ? 12 : 8));
  DOMAIN.copy(bytes);
  let offset = DOMAIN.length;
  bytes.writeUInt32LE(name.length, offset); offset += 4;
  name.copy(bytes, offset); offset += name.length;
  bytes.writeUInt32LE(values.length, offset); offset += 4;
  if (indices) {
    for (const index of indices) { bytes.writeUInt32LE(index, offset); offset += 4; }
  }
  for (const value of values) { bytes.writeDoubleLE(value, offset); offset += 8; }
  return Object.freeze(Array.from(bytes));
}

export function encode_dense_replay(original: unknown, profile: unknown): DenseReplay {
  const values = originals(original, 1536, 1536);
  const encoded = encode_dense(values, profile);
  const blob = replayBlob('dense', values);
  return Object.freeze({ blob, blob_sha256: sha(Buffer.from(blob)), input_sha256: encoded.input_sha256, encoded });
}

export function encode_sparse_replay(indices: unknown, original: unknown, profile: unknown): SparseReplay {
  const indexSnapshot = originals(indices, 1, 16);
  const values = originals(original, 1, 16);
  const encoded = encode_sparse(indexSnapshot, values, profile);
  const blob = replayBlob('sparse', values, encoded.indices);
  return Object.freeze({ blob, blob_sha256: sha(Buffer.from(blob)), input_sha256: encoded.input_sha256, encoded });
}

function restore(
  input: unknown, expectedBlob: unknown, expectedInput: unknown, profile: unknown, kind: 'dense' | 'sparse',
): DenseVector | SparseVector {
  try {
    const maxLength = kind === 'dense' ? 12326 : 231;
    const values = arrayDescriptors(input, 1, maxLength).map(value => integer(value, 0, 255));
    const blobHash = digest(expectedBlob), inputHash = digest(expectedInput);
    const bytes = Buffer.from(values);
    if (sha(bytes) !== blobHash) throw new IntegrityViolation();
    const name = Buffer.from(kind, 'ascii');
    const header = DOMAIN.length + 4 + name.length + 4;
    if (bytes.length < header || !bytes.subarray(0, DOMAIN.length).equals(DOMAIN)
      || bytes.readUInt32LE(DOMAIN.length) !== name.length
      || !bytes.subarray(DOMAIN.length + 4, DOMAIN.length + 4 + name.length).equals(name)) throw new IntegrityViolation();
    const count = bytes.readUInt32LE(header - 4);
    if ((kind === 'dense' && count !== 1536) || (kind === 'sparse' && (count < 1 || count > 16))
      || bytes.length !== header + count * (kind === 'dense' ? 8 : 12)) throw new IntegrityViolation();
    let offset = header;
    const indices: number[] = [];
    if (kind === 'sparse') {
      for (let i = 0; i < count; i++) { indices.push(bytes.readUInt32LE(offset)); offset += 4; }
    }
    const originals: number[] = [];
    for (let i = 0; i < count; i++) { originals.push(bytes.readDoubleLE(offset)); offset += 8; }
    const encoded = kind === 'dense' ? encode_dense(originals, profile) : encode_sparse(indices, originals, profile);
    if (encoded.input_sha256 !== inputHash) throw new IntegrityViolation();
    return encoded;
  } catch (error) {
    if (error instanceof InvalidRequest || error instanceof IntegrityViolation
      || error instanceof EmbeddingProfileMismatch || error instanceof UnsupportedCapability) throw new IntegrityViolation();
    throw error;
  }
}

export function restore_dense_replay(blob: unknown, expected_blob_sha256: unknown, expected_input_sha256: unknown, profile: unknown): DenseVector {
  return restore(blob, expected_blob_sha256, expected_input_sha256, profile, 'dense') as DenseVector;
}

export function restore_sparse_replay(blob: unknown, expected_blob_sha256: unknown, expected_input_sha256: unknown, profile: unknown): SparseVector {
  return restore(blob, expected_blob_sha256, expected_input_sha256, profile, 'sparse') as SparseVector;
}
