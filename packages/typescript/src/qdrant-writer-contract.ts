/** Internal, pure admission for the optional publication authority. */
import { createHash } from 'node:crypto';
import { types } from 'node:util';
import { z } from 'zod';
import { EmbeddingProfileMismatch, IntegrityViolation, InvalidRequest, UnauthorizedScope } from './errors.js';
import { bind_embedding_batch, parse_config, type QdrantConfig } from './qdrant-contract.js';
import { parse_scope, type TrustedScope } from './requests.js';
import { identity, input_text } from './shared.js';
import { check_deadline } from './qdrant-transport.js';
import { type LeaseOptions } from './postgres-pool.js';
import {
  encode_manifest, encode_stage_intent, encode_security_intent, encode_purge_intent,
  encode_dense_replay, encode_sparse_replay, type EncodedManifest,
  type DenseReplay, type SparseReplay,
} from './qdrant-manifest.js';

export type Data = Record<string, unknown>;
export type WriterContext = Readonly<{scope: TrustedScope; collection: string; document_id: string; intent_id: string; owner_token: string}>;
export type StagePlan = Readonly<{manifest_sha256: string; payload_sha256: string; member_count: number}>;
export type StageData = Readonly<{
  record: Data; intent: Data; canonical_text: string; manifest: EncodedManifest;
  payload: EncodedManifest; dense: readonly DenseReplay[]; sparse: readonly (SparseReplay | null)[];
}>;
const plans = new WeakMap<object, StageData>();
export const hash = (bytes: Uint8Array | string): string => createHash('sha256').update(bytes).digest('hex');

export function fields(input: unknown, required: readonly string[], optional: readonly string[] = []): Data {
  if (typeof input !== 'object' || input === null || types.isProxy(input)
    || Object.getPrototypeOf(input) !== Object.prototype) throw new InvalidRequest();
  const keys = Reflect.ownKeys(input);
  if (keys.length > required.length + optional.length) throw new InvalidRequest();
  const result: Data = {};
  for (const key of keys) {
    if (typeof key !== 'string' || (!required.includes(key) && !optional.includes(key))) throw new InvalidRequest();
    const descriptor = Object.getOwnPropertyDescriptor(input, key);
    if (!descriptor || !('value' in descriptor)) throw new InvalidRequest();
    Object.defineProperty(result, key, {value: descriptor.value, enumerable: true});
  }
  if (required.some(key => !Object.hasOwn(result, key))) throw new InvalidRequest();
  return result;
}

export function native_array(input: unknown, min: number, max: number): unknown[] {
  if (typeof input !== 'object' || input === null || types.isProxy(input)
    || !Array.isArray(input) || Object.getPrototypeOf(input) !== Array.prototype) throw new InvalidRequest();
  const length: unknown = Object.getOwnPropertyDescriptor(input, 'length')?.value;
  if (typeof length !== 'number' || length < min || length > max
    || Reflect.ownKeys(input).length !== length + 1) throw new InvalidRequest();
  const result: unknown[] = [];
  for (let i = 0; i < length; i++) {
    const descriptor = Object.getOwnPropertyDescriptor(input, String(i));
    if (!descriptor || !('value' in descriptor)) throw new InvalidRequest();
    result.push(descriptor.value);
  }
  return result;
}

/** Metadata and E batches have separate budgets; source text is admitted by B2. */
export function snapshot(input: unknown, maxNodes = 4096, maxDepth = 32): unknown {
  let nodes = 0;
  const ancestors = new Set<object>();
  function visit(value: unknown, depth: number): unknown {
    if (++nodes > maxNodes || depth > maxDepth) throw new InvalidRequest();
    if (value === null || typeof value === 'boolean') return value;
    if (typeof value === 'number') {
      if (!Number.isFinite(value)) throw new InvalidRequest();
      return value;
    }
    if (typeof value === 'string') {
      if (value.length > 1024 || /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value)
        || Buffer.byteLength(value) > 1024) throw new InvalidRequest();
      return value;
    }
    if (typeof value !== 'object' || types.isProxy(value) || ancestors.has(value)) throw new InvalidRequest();
    ancestors.add(value);
    try {
      if (Array.isArray(value)) return Object.freeze(native_array(value, 0, maxNodes).map(item => visit(item, depth + 1)));
      if (Object.getPrototypeOf(value) !== Object.prototype) throw new InvalidRequest();
      const keys = Reflect.ownKeys(value);
      if (keys.length > maxNodes) throw new InvalidRequest();
      const result: Data = {};
      for (const key of keys) {
        if (typeof key !== 'string' || key.length > 256 || Buffer.byteLength(key) > 256) throw new InvalidRequest();
        const descriptor = Object.getOwnPropertyDescriptor(value, key);
        if (!descriptor || !('value' in descriptor)) throw new InvalidRequest();
        Object.defineProperty(result, key, {value: visit(descriptor.value, depth + 1), enumerable: true});
      }
      return Object.freeze(result);
    } finally { ancestors.delete(value); }
  }
  return visit(input, 0);
}

export function text(input: unknown, collection = false): string {
  const result = (collection ? input_text(128) : identity).safeParse(input);
  if (!result.success) throw new InvalidRequest();
  return result.data;
}
export function uuid(input: unknown): string {
  if (typeof input !== 'string' || input.length !== 36
    || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(input)) throw new InvalidRequest();
  return input;
}
export function digest(input: unknown): string {
  if (typeof input !== 'string' || input.length !== 64 || !/^[0-9a-f]{64}$/.test(input)) throw new InvalidRequest();
  return input;
}
export function count(input: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number {
  if (typeof input !== 'number' || !Number.isSafeInteger(input) || input < min || input > max) throw new InvalidRequest();
  return input === 0 ? 0 : input;
}
export function scope(input: unknown): TrustedScope { return parse_scope(snapshot(input)); }
export function config(input: unknown): QdrantConfig { return parse_config(snapshot(input)); }
export function options(input: unknown, withOwner = false): LeaseOptions & {owner_token?: string} {
  const value = fields(input, ['deadline'], withOwner ? ['signal', 'owner_token'] : ['signal']);
  const signal = value.signal;
  if (signal !== undefined && !(signal instanceof AbortSignal)) throw new InvalidRequest();
  const deadline = value.deadline;
  if (typeof deadline !== 'number') throw new InvalidRequest();
  check_deadline(deadline, signal as AbortSignal | undefined);
  const owner_token = withOwner ? uuid(value.owner_token) : undefined;
  return Object.freeze({deadline, signal: signal as AbortSignal | undefined, owner_token});
}
export function context(input: unknown): WriterContext {
  const value = fields(input, ['scope', 'collection', 'document_id', 'intent_id', 'owner_token']);
  return Object.freeze({scope: scope(value.scope), collection: text(value.collection, true), document_id: text(value.document_id), intent_id: text(value.intent_id), owner_token: uuid(value.owner_token)});
}
export function metadata(input: unknown): Data {
  const result = snapshot(input);
  if (typeof result !== 'object' || result === null || Array.isArray(result)) throw new InvalidRequest();
  return result as Data;
}

export function prepare_stage(input: unknown): StagePlan {
  const value = fields(input, ['manifest', 'canonical_text', 'intent'], ['dense_batches', 'dense_vectors', 'sparse_vectors']);
  const record = metadata(value.manifest), intent = metadata(value.intent);
  const manifest = encode_manifest(record, value.canonical_text);
  const payload = encode_stage_intent(intent);
  if (intent.manifest_sha256 !== manifest.sha256 || ['tenant_id', 'collection', 'document_id'].some(key => intent[key] !== record[key])) throw new IntegrityViolation();
  const members = native_array(record.members, 1, 64).map(member => metadata(member));
  const checkedConfig = parse_config({backend_namespace: record.backend_namespace, physical_collection: record.physical_collection,
    collection_incarnation: record.collection_incarnation, dense_profile: record.dense_profile, sparse_profile: record.sparse_profile});
  const hasBatches = Object.hasOwn(value, 'dense_batches'), hasVectors = Object.hasOwn(value, 'dense_vectors');
  if (hasBatches === hasVectors) throw new InvalidRequest();
  const originals: unknown[] = [];
  if (hasBatches) {
    for (const batch of native_array(value.dense_batches, 1, 8)) {
      const bound = bind_embedding_batch(snapshot(batch, 16384, 8), checkedConfig.dense_profile);
      originals.push(...bound.vectors);
    }
  } else {
    if (checkedConfig.dense_profile.provider !== 'fake') throw new EmbeddingProfileMismatch();
    originals.push(...native_array(value.dense_vectors, 1, 64));
  }
  if (originals.length !== members.length) throw new InvalidRequest();
  const dense = originals.map(vector => encode_dense_replay(vector, checkedConfig.dense_profile));
  let sparse: (SparseReplay | null)[];
  if (checkedConfig.sparse_profile === null) {
    if (value.sparse_vectors !== undefined && value.sparse_vectors !== null) throw new InvalidRequest();
    sparse = members.map(() => null);
  } else {
    sparse = native_array(value.sparse_vectors, members.length, members.length).map(vector => {
      const checked = fields(vector, ['indices', 'values']);
      return encode_sparse_replay(checked.indices, checked.values, checkedConfig.sparse_profile);
    });
  }
  for (let i = 0; i < members.length; i++) {
    if (members[i].dense_input_sha256 !== dense[i].input_sha256
      || members[i].sparse_input_sha256 !== (sparse[i]?.input_sha256 ?? null)) throw new IntegrityViolation();
  }
  const plan = Object.freeze({manifest_sha256: manifest.sha256, payload_sha256: payload.sha256, member_count: members.length});
  plans.set(plan, Object.freeze({record, intent, canonical_text: value.canonical_text as string, manifest, payload,
    dense: Object.freeze(dense), sparse: Object.freeze(sparse)}));
  return plan;
}

export function stage_data(input: unknown): StageData {
  if (typeof input !== 'object' || input === null || !plans.has(input)) throw new InvalidRequest();
  return plans.get(input)!;
}

/** Internal authority handoff after full stored-graph and original-sidecar verification. */
export function issue_verified_stage(data: StageData): StagePlan {
  const plan = Object.freeze({manifest_sha256:data.manifest.sha256,payload_sha256:data.payload.sha256,
    member_count:data.dense.length});
  plans.set(plan,Object.freeze(data));
  return plan;
}

export function operation(record: unknown, inputScope: unknown, owner: unknown, purge = false): Readonly<{record: Data; scope: TrustedScope; owner_token: string; encoded: EncodedManifest}> {
  const value = metadata(record), trusted = scope(inputScope);
  const encoded = purge ? encode_purge_intent(value) : encode_security_intent(value);
  if (value.tenant_id !== trusted.tenant_id) throw new UnauthorizedScope();
  return Object.freeze({record: value, scope: trusted, owner_token: uuid(owner), encoded});
}

/** Driver values are checked without trusting coercion or custom model hooks. */
export function db_count(input: unknown): number {
  try {
    if (typeof input === 'number') return count(input);
    if (typeof input === 'string' && input.length <= 16 && /^(?:0|[1-9][0-9]*)$/.test(input)) return count(Number(input));
  } catch (error) {
    if (error instanceof InvalidRequest) throw new IntegrityViolation();
    throw error;
  }
  throw new IntegrityViolation();
}
export function db_bytes(input: unknown, max: number): Buffer {
  if (!Buffer.isBuffer(input) || types.isProxy(input) || Object.getPrototypeOf(input) !== Buffer.prototype || input.length > max) throw new IntegrityViolation();
  return input;
}
export function db_json(input: unknown): unknown {
  try { return snapshot(input); } catch (error) {
    if (error instanceof InvalidRequest) throw new IntegrityViolation();
    throw error;
  }
}

export const DispatchOptionsSchema = z.strictObject({dispatch_id: identity, sequence: z.number().int().min(1).max(256),
  credential_generation: identity, operation: z.enum(['complete_point_upsert', 'delete_points']),
  point_ids: z.array(z.string().length(36).regex(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/)).min(1).max(8)});
