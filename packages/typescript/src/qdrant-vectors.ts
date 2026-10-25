import { createHash } from 'node:crypto';
import { types } from 'node:util';
import { EmbeddingProfileMismatch, IntegrityViolation, InvalidRequest } from './errors.js';
import { FAKE_PROFILE, OPENAI_PROFILE } from './embeddings.js';

const DENSE_FIELDS = [
  'profile_id', 'provider', 'model', 'dimensions', 'tokenizer', 'normalization',
] as const;
const SPARSE_FIELDS = [
  'profile_id', 'encoder', 'model', 'revision', 'vocabulary', 'preprocessing',
  'weighting', 'corpus_statistics_revision',
] as const;
const SPARSE_PROFILE = {
  profile_id: 'fake_manual_sparse_v1', encoder: 'caller_supplied_fixture',
  model: 'none', revision: '1', vocabulary: 'fixture_uint32_v1',
  preprocessing: 'none', weighting: 'caller_supplied',
  corpus_statistics_revision: 'none',
};
const T = 0.0002 - 0.000000000002;
type Profile = Readonly<Record<string, string | number>>;
export type DenseVector = Readonly<{
  kind: 'dense'; name: 'dense'; profile: Profile;
  values: readonly number[];
  sealed_bytes: readonly number[];
  input_sha256: string;
}>;
export type SparseVector = Readonly<{
  kind: 'sparse'; name: 'sparse'; profile: Profile;
  indices: readonly number[];
  values: readonly number[];
  sealed_bytes: readonly number[];
  input_sha256: string;
}>;
const denseIssued = new WeakSet<object>();
const sparseIssued = new WeakSet<object>();

/** Snapshot bounded arrays without evaluating caller accessors or proxy traps. */
function nativeArray(input: unknown, min: number, max: number): number[] {
  if (
    typeof input !== 'object' || input === null || types.isProxy(input)
    || !Array.isArray(input) || Object.getPrototypeOf(input) !== Array.prototype
  ) {
    throw new InvalidRequest();
  }
  const length = Object.getOwnPropertyDescriptor(input, 'length')?.value as unknown;
  if (typeof length !== 'number' || !Number.isSafeInteger(length) || length < min || length > max) {
    throw new InvalidRequest();
  }
  const keys = Reflect.ownKeys(input);
  if (keys.length !== length + 1) {
    throw new InvalidRequest();
  }
  const result: number[] = [];
  for (let i = 0; i < length; i++) {
    const descriptor = Object.getOwnPropertyDescriptor(input, String(i));
    if (!descriptor || !('value' in descriptor)
      || typeof descriptor.value !== 'number' || !Number.isFinite(descriptor.value)) {
      throw new InvalidRequest();
    }
    result.push(descriptor.value);
  }
  return result;
}

/** Validate shape before comparing the complete supported profile identity. */
function profileSnapshot(input: unknown, sparse: boolean): Profile {
  if (typeof input !== 'object' || input === null || types.isProxy(input)
    || Object.getPrototypeOf(input) !== Object.prototype) {
    throw new InvalidRequest();
  }
  const fields = sparse ? SPARSE_FIELDS : DENSE_FIELDS;
  const keys = Reflect.ownKeys(input);
  if (keys.length !== fields.length) {
    throw new InvalidRequest();
  }
  const result: Record<string, string | number> = {};
  for (const key of keys) {
    if (typeof key !== 'string' || key.length > 256
      || Buffer.byteLength(key, 'utf8') > 256 || !fields.includes(key as never)) {
      throw new InvalidRequest();
    }
  }
  for (const key of fields) {
    const descriptor = Object.getOwnPropertyDescriptor(input, key);
    if (!descriptor || !('value' in descriptor)) {
      throw new InvalidRequest();
    }
    const value: unknown = descriptor.value;
    if (key === 'dimensions') {
      if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1) {
        throw new InvalidRequest();
      }
    } else {
      if (typeof value !== 'string' || value.length > 1024
        || /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value)
        || Buffer.byteLength(value, 'utf8') > 1024 || !value.trim() || value.includes('\0')) {
        throw new InvalidRequest();
      }
    }
    result[key] = value as string | number;
  }
  const supported = sparse ? [SPARSE_PROFILE] : [FAKE_PROFILE, OPENAI_PROFILE];
  const matches = supported.some(profile => fields.every(
    key => result[key] === (profile as Record<string, unknown>)[key],
  ));
  if (!matches) {
    throw new EmbeddingProfileMismatch();
  }
  return Object.freeze(result);
}

/** Round once, retaining representable subnormals and canonical positive zero. */
function f32(value: number): number {
  const rounded = Math.fround(value);
  if (!Number.isFinite(rounded) || (value !== 0 && rounded === 0)) {
    throw new InvalidRequest();
  }
  return rounded === 0 ? 0 : rounded;
}

/** Seal submitted content, separately from normalized server readback. */
function seal(
  kind: 'dense' | 'sparse', profile: Profile,
  values: readonly number[], indices?: readonly number[],
): Readonly<{ sealed_bytes: readonly number[]; input_sha256: string }> {
  const parts: Buffer[] = [Buffer.from('cragkit.qdrant.vector.v1\0', 'ascii')];
  const u32 = (value: number): Buffer => {
    const bytes = Buffer.alloc(4);
    bytes.writeUInt32LE(value);
    return bytes;
  };
  const frame = (value: string): void => {
    const bytes = Buffer.from(value, 'utf8');
    parts.push(u32(bytes.length), bytes);
  };
  frame(kind);
  frame(kind);
  const fields = kind === 'dense' ? DENSE_FIELDS : SPARSE_FIELDS;
  parts.push(u32(fields.length));
  for (const key of fields) {
    frame(key);
    frame(String(profile[key]));
  }
  parts.push(u32(values.length));
  if (indices) {
    for (const index of indices) {
      parts.push(u32(index));
    }
  }
  const components = Buffer.alloc(values.length * 4);
  for (let i = 0; i < values.length; i++) {
    components.writeFloatLE(values[i], i * 4);
  }
  parts.push(components);
  const bytes = Buffer.concat(parts);
  return {
    sealed_bytes: Object.freeze(Array.from(bytes)),
    input_sha256: createHash('sha256').update(bytes).digest('hex'),
  };
}

export function encode_dense(vector: unknown, profile: unknown): DenseVector {
  const checkedProfile = profileSnapshot(profile, false);
  const original = nativeArray(vector, 1536, 1536);
  let squares = 0;
  for (let i = 0; i < original.length; i++) {
    squares += original[i] * original[i];
  }
  const norm = Math.sqrt(squares);
  if (!Number.isFinite(norm) || Math.abs(norm - 1) > 0.001) {
    throw new InvalidRequest();
  }
  const values = Object.freeze(original.map(f32));
  const result: DenseVector = Object.freeze({
    kind: 'dense', name: 'dense', profile: checkedProfile, values,
    ...seal('dense', checkedProfile, values),
  });
  denseIssued.add(result);
  return result;
}

function sparseArrays(indices: unknown, values: unknown): { indices: number[]; values: number[] } {
  const checkedIndices = nativeArray(indices, 1, 16);
  const checkedValues = nativeArray(values, 1, 16);
  if (checkedIndices.length !== checkedValues.length) {
    throw new InvalidRequest();
  }
  for (let i = 0; i < checkedIndices.length; i++) {
    const index = checkedIndices[i];
    if (!Number.isInteger(index) || index < 0 || index > 4294967295
      || (i > 0 && index <= checkedIndices[i - 1]) || checkedValues[i] <= 0) {
      throw new InvalidRequest();
    }
    checkedIndices[i] = index === 0 ? 0 : index;
  }
  return { indices: checkedIndices, values: checkedValues.map(f32) };
}

export function encode_sparse(indices: unknown, values: unknown, profile: unknown): SparseVector {
  const checkedProfile = profileSnapshot(profile, true);
  const checked = sparseArrays(indices, values);
  const canonicalIndices = Object.freeze(checked.indices);
  const canonicalValues = Object.freeze(checked.values);
  const result: SparseVector = Object.freeze({
    kind: 'sparse', name: 'sparse', profile: checkedProfile,
    indices: canonicalIndices, values: canonicalValues,
    ...seal('sparse', checkedProfile, canonicalValues, canonicalIndices),
  });
  sparseIssued.add(result);
  return result;
}

/** Every reduction preserves the contract's ascending binary64 order. */
export function verify_dense_readback(expected: unknown, observed: unknown): void {
  try {
    if (typeof expected !== 'object' || expected === null || !denseIssued.has(expected)) {
      throw new IntegrityViolation();
    }
    const input = (expected as DenseVector).values;
    const returned = nativeArray(observed, 1536, 1536).map(f32);
    let inputSquares = 0;
    for (let i = 0; i < input.length; i++) {
      inputSquares += input[i] * input[i];
    }
    const inputNorm = Math.sqrt(inputSquares);
    let returnedSquares = 0;
    let differenceSquares = 0;
    for (let i = 0; i < input.length; i++) {
      const ideal = input[i] / inputNorm;
      const difference = returned[i] - ideal;
      if (Math.abs(difference) > T * Math.abs(ideal) + 2 ** -126) {
        throw new IntegrityViolation();
      }
      returnedSquares += returned[i] * returned[i];
      differenceSquares += difference * difference;
    }
    if (Math.abs(Math.sqrt(returnedSquares) - 1) > T || Math.sqrt(differenceSquares) > T) {
      throw new IntegrityViolation();
    }
  } catch (error) {
    if (error instanceof InvalidRequest || error instanceof IntegrityViolation) {
      throw new IntegrityViolation();
    }
    throw error;
  }
}

export function verify_sparse_readback(
  expected: unknown, observed_indices: unknown, observed_values: unknown,
): void {
  try {
    if (typeof expected !== 'object' || expected === null || !sparseIssued.has(expected)) {
      throw new IntegrityViolation();
    }
    const input = expected as SparseVector;
    const returned = sparseArrays(observed_indices, observed_values);
    if (returned.indices.length !== input.indices.length) {
      throw new IntegrityViolation();
    }
    for (let i = 0; i < input.indices.length; i++) {
      if (returned.indices[i] !== input.indices[i] || returned.values[i] !== input.values[i]) {
        throw new IntegrityViolation();
      }
    }
  } catch (error) {
    if (error instanceof InvalidRequest || error instanceof IntegrityViolation) {
      throw new IntegrityViolation();
    }
    throw error;
  }
}
