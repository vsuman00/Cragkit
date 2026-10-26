/** Authority-bound readback evidence only: no SQL settlement or admission reopen. */
import { ManagedQdrantSupervisor, type SupervisorTransport } from './qdrant-supervisor.js';
import { randomUUID } from 'node:crypto';
import { types } from 'node:util';
import { PostgresQdrantWriter, projection_data, type ExpectedProjection, type ProjectionData, type ProjectionPoint } from './qdrant-writer.js';
import { context as parse_context, options as parse_options, fields, native_array, metadata, uuid, count, hash,
  type Data, type WriterContext } from './qdrant-writer-contract.js';
import { parse_response, same } from './qdrant-contract.js';
import { verify_dense_readback, verify_sparse_readback } from './qdrant-vectors.js';
import { bounded, now } from './postgres-pool.js';
import { DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability } from './errors.js';

export type ReconciliationReceipt = Readonly<Record<never, never>>;
export type ReceiptData = Readonly<{
  projection: ExpectedProjection;
  context: WriterContext;
  physical_binding: Readonly<Data>;
  manifest_sha256: string;
  revision_id: string;
  generation_id: string;
  authorization_revision: string;
  mutation_epoch: number;
  active_generation_id: string | null;
  tombstoned: boolean;
  point_ids: readonly string[];
  readback_sha256: string;
  witness: readonly unknown[];
  encoded_bytes: readonly number[];
  sha256: string;
}>;
type Issued = Readonly<{
  issuer: QdrantReconciliationVerifier;
  supervisor: ManagedQdrantSupervisor;
  proof: unknown;
  data: ReceiptData;
}>;
const receipts = new WeakMap<object, Issued>();
const verifiers = new WeakMap<object, Readonly<{
  writer: PostgresQdrantWriter;
  supervisor: ManagedQdrantSupervisor;
}>>();

export function verifier_authority(input: unknown, supervisor: unknown): PostgresQdrantWriter {
  if (typeof input !== 'object' || input === null || types.isProxy(input)
      || Object.getPrototypeOf(input) !== QdrantReconciliationVerifier.prototype) {
    throw new InvalidRequest();
  }
  const binding = verifiers.get(input);
  if (!binding || binding.supervisor !== supervisor) throw new InvalidRequest();
  return binding.writer;
}
const MAX_CALLS = 17;
const MAX_PAGE = 8;
const MAX_RESPONSE = 1048576;
const MAX_AGGREGATE = 8388608;

export function receipt_data(input: unknown, verifier: QdrantReconciliationVerifier): ReceiptData {
  if (typeof input !== 'object' || input === null) {
    throw new InvalidRequest();
  }
  const issued = receipts.get(input);
  if (!issued || issued.issuer !== verifier) {
    throw new InvalidRequest();
  }
  const current = issued.supervisor.recovery_binding(issued.proof);
  if (!same(current, issued.data.physical_binding)) {
    throw new UnsupportedCapability();
  }
  return issued.data;
}
function safe(error: unknown): Error {
  if (error instanceof IntegrityViolation) return new IntegrityViolation();
  if (error instanceof InvalidRequest) return new InvalidRequest();
  if (error instanceof UnsupportedCapability) return new UnsupportedCapability();
  if (error instanceof UnauthorizedScope) return new UnauthorizedScope();
  if (error instanceof DeadlineExceeded) return new DeadlineExceeded();
  if (error instanceof DOMException && error.name === 'AbortError') {
    return new DOMException('Operation aborted.', 'AbortError');
  }
  return new ProviderUnavailable();
}
function frozen(value: unknown): unknown {
  if (value !== null && typeof value === 'object') {
    for (const child of Object.values(value)) frozen(child);
    Object.freeze(value);
  }
  return value;
}
function envelope(raw: unknown): Data {
  // The strict parser owns this graph and uses null-prototype records. Copy
  // those records before applying the native-object boundary validators.
  function native(value: unknown): unknown {
    if (Array.isArray(value)) return value.map(native);
    if (value !== null && typeof value === 'object') {
      return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, native(child)]));
    }
    return value;
  }
  const parsed = native(parse_response(raw));
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new IntegrityViolation();
  }
  const result = parsed as Data;
  if (result.status !== 'ok' || !Object.hasOwn(result, 'result')) {
    throw new IntegrityViolation();
  }
  return result;
}
function rows(input: unknown, max: number): Data[] {
  try {
    return native_array(input, 0, max).map(row => fields(row, ['id', 'payload', 'vector'], ['shard_key']));
  } catch (error) {
    if (error instanceof InvalidRequest) throw new IntegrityViolation();
    throw error;
  }
}
function point_id(row: Data): string {
  try {
    const id = uuid(row.id);
    if (row.shard_key !== undefined && row.shard_key !== null) throw new InvalidRequest();
    return id;
  } catch (error) {
    if (error instanceof InvalidRequest) throw new IntegrityViolation();
    throw error;
  }
}

/** Pure response validation uses B1-issued expected vectors from SQL projection. */
export function verify_point(expected: ProjectionPoint, observed: Data): void {
  try {
    if (point_id(observed) !== expected.point_id || !same(metadata(observed.payload), expected.payload)) {
      throw new IntegrityViolation();
    }
    const vector = fields(observed.vector, ['dense', ...(expected.sparse ? ['sparse'] : [])]);
    verify_dense_readback(expected.dense, vector.dense);
    if (expected.sparse) {
      const sparse = fields(vector.sparse, ['indices', 'values']);
      verify_sparse_readback(expected.sparse, sparse.indices, sparse.values);
    }
  } catch (error) {
    if (error instanceof InvalidRequest) throw new IntegrityViolation();
    throw error;
  }
}
/** Shared exact replica readback; callers own provenance and transport lifetime. */
export async function verify_projection_readback(
  transport: SupervisorTransport,
  collection: string,
  expected: Readonly<{points: readonly ProjectionPoint[]; tombstoned: boolean}>,
  rawOptions: unknown,
): Promise<void> {
  const options = parse_options(rawOptions);
  const lease = {deadline: options.deadline, signal: options.signal};
  let calls = 0;
  let aggregate = 0;
  const request = async (path: string, body: unknown): Promise<Data> => {
    if (calls >= MAX_CALLS || aggregate >= MAX_AGGREGATE) throw new ProviderUnavailable();
    calls++;
    const raw = await transport.request('POST', path, {
      body: Object.freeze(Array.from(Buffer.from(JSON.stringify(body)))),
      max_response_bytes: Math.min(MAX_RESPONSE, MAX_AGGREGATE - aggregate),
      ...lease,
    });
    let bytes: unknown[];
    try {
      bytes = native_array(raw, 0, MAX_RESPONSE);
    } catch (error) {
      if (error instanceof InvalidRequest) throw new IntegrityViolation();
      throw error;
    }
    if (bytes.length > MAX_AGGREGATE - aggregate) throw new ProviderUnavailable();
    aggregate += bytes.length;
    const buffer = Buffer.from(bytes.map(value => {
      try {
        return count(value, 0, 255);
      } catch (error) {
        if (error instanceof InvalidRequest) throw new IntegrityViolation();
        throw error;
      }
    }));
    return envelope(buffer);
  };
  const base = '/collections/' + collection + '/points';
  const byId = new Map(expected.points.map(point => [point.point_id, point]));
  for (let start = 0; start < expected.points.length; start += MAX_PAGE) {
    const ids = expected.points.slice(start, start + MAX_PAGE).map(point => point.point_id);
    const parsed = await request(base, {ids, with_payload: true, with_vector: true});
    const observed = rows(parsed.result, ids.length);
    const seen = new Set<string>();
    if (expected.tombstoned && observed.length) throw new IntegrityViolation();
    for (const row of observed) {
      const id = point_id(row);
      if (!ids.includes(id) || seen.has(id)) throw new IntegrityViolation();
      seen.add(id);
      verify_point(byId.get(id)!, row);
    }
    if (!expected.tombstoned && seen.size !== ids.length) throw new IntegrityViolation();
  }
  const filterKeys = ['backend_namespace', 'physical_collection', 'collection_incarnation',
    'tenant_id', 'collection', 'document_id', 'revision_id', 'generation_id'];
  const filter = {must: filterKeys.map(key => ({key, match: {value: expected.points[0].payload[key]}}))};
  const seen = new Set<string>();
  const offsets = new Set<string>();
  let offset: string | null = null;
  let pages = 0;
  for (;;) {
    if (++pages > 9) throw new ProviderUnavailable();
    const parsed = await request(base + '/scroll', {
      filter, limit: MAX_PAGE, with_payload: true, with_vector: true, ...(offset === null ? {} : {offset}),
    });
    let page: Data;
    try {
      page = fields(parsed.result, ['points', 'next_page_offset']);
    } catch (error) {
      if (error instanceof InvalidRequest) throw new IntegrityViolation();
      throw error;
    }
    const observed = rows(page.points, MAX_PAGE);
    if (expected.tombstoned && observed.length) throw new IntegrityViolation();
    for (const row of observed) {
      const id = point_id(row);
      const point = byId.get(id);
      if (!point || seen.has(id) || seen.size >= 64) throw new IntegrityViolation();
      seen.add(id);
      verify_point(point, row);
    }
    if (page.next_page_offset === null) break;
    let next: string;
    try {
      next = uuid(page.next_page_offset);
    } catch (error) {
      if (error instanceof InvalidRequest) throw new IntegrityViolation();
      throw error;
    }
    if (observed.length === 0 || offsets.has(next)) throw new IntegrityViolation();
    offsets.add(next);
    offset = next;
  }
  if (seen.size !== (expected.tombstoned ? 0 : expected.points.length)) throw new IntegrityViolation();
}

function canonical_acl(ids: readonly string[]): readonly string[] {
  return Object.freeze([...new Set(ids)].sort((a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b))));
}
function witness(data: ProjectionData): readonly unknown[] {
  const physical = data.physical_binding;
  const context = data.context;
  return frozen([
    'cragkit.qdrant.readback.v1', physical.instance_id, physical.storage_identity, physical.supervisor_id,
    physical.recovery_id, String(physical.old_epoch), String(physical.new_epoch), physical.credential_generation,
    context.scope.tenant_id, context.collection, context.document_id, context.intent_id, context.owner_token,
    data.revision_id, data.generation_id, data.manifest_sha256, data.authorization_revision, String(data.mutation_epoch),
    data.active_generation_id, data.tombstoned ? 'true' : 'false',
    data.points.map(point => [point.point_id, point.dense.input_sha256, point.sparse?.input_sha256 ?? null]),
    [canonical_acl(data.principal_ids), canonical_acl(data.grant_ids), data.language, data.kind, data.tag],
  ]) as readonly unknown[];
}

export class QdrantReconciliationVerifier {
  readonly #writer: PostgresQdrantWriter;
  readonly #supervisor: ManagedQdrantSupervisor;
  #active?: Readonly<{controller: AbortController; done: Promise<void>}>;
  #closed = false;
  constructor(writer: PostgresQdrantWriter, supervisor: ManagedQdrantSupervisor) {
    if (typeof writer !== 'object' || writer === null || types.isProxy(writer)
      || typeof supervisor !== 'object' || supervisor === null || types.isProxy(supervisor)
      || Object.getPrototypeOf(writer) !== PostgresQdrantWriter.prototype
      || Object.getPrototypeOf(supervisor) !== ManagedQdrantSupervisor.prototype) {
      throw new InvalidRequest();
    }
    this.#writer = writer;
    this.#supervisor = supervisor;
    verifiers.set(this, Object.freeze({writer, supervisor}));
  }
  async verify(proof: unknown, input: unknown, rawOptions: unknown): Promise<ReconciliationReceipt> {
    const context = parse_context(input);
    const options = parse_options(rawOptions);
    if (this.#closed || this.#active) throw new ProviderUnavailable();
    const physical = metadata(this.#supervisor.recovery_binding(proof));
    const controller = new AbortController();
    const relay = () => controller.abort();
    options.signal?.addEventListener('abort', relay, {once: true});
    if (options.signal?.aborted) controller.abort();
    let finish!: () => void;
    const done = new Promise<void>(resolve => { finish = resolve; });
    this.#active = {controller, done};
    const lease = {deadline: options.deadline, signal: controller.signal};
    let transport: ReturnType<ManagedQdrantSupervisor['transport_for']> | undefined;
    try {
      const projection = await this.#writer.project_stage(context, physical, lease);
      const expected = projection_data(projection, this.#writer);
      const capability = this.#supervisor.issue_recovery_attempt(proof, {
        intent_id: context.intent_id, owner_token: context.owner_token,
        epoch: physical.new_epoch, dispatch_id: 'readback-' + randomUUID(), recovery_id: physical.recovery_id,
      }, lease);
      transport = this.#supervisor.transport_for(capability);
      await verify_projection_readback(
        transport, String(expected.points[0].payload.physical_collection), expected, lease,
      );
      await transport.close();
      transport = undefined;
      await this.#writer.validate_projection(projection, lease);
      const current = this.#supervisor.recovery_binding(proof);
      if (!same(current, physical)) throw new UnsupportedCapability();
      parse_options(lease);
      const value = witness(expected);
      const encoded_bytes = Object.freeze(Array.from(Buffer.from(JSON.stringify(value))));
      const sha256 = hash(Buffer.from(encoded_bytes));
      const data: ReceiptData = Object.freeze({
        projection, context, physical_binding: physical, manifest_sha256: expected.manifest_sha256,
        revision_id: expected.revision_id, generation_id: expected.generation_id,
        authorization_revision: expected.authorization_revision, mutation_epoch: expected.mutation_epoch,
        active_generation_id: expected.active_generation_id, tombstoned: expected.tombstoned,
        point_ids: Object.freeze(expected.points.map(point => point.point_id)),
        readback_sha256: sha256, witness: value, encoded_bytes, sha256,
      });
      const receipt = Object.freeze({});
      receipts.set(receipt, Object.freeze({issuer: this, supervisor: this.#supervisor, proof, data}));
      return receipt;
    } catch (error) {
      throw safe(error);
    } finally {
      controller.abort();
      options.signal?.removeEventListener('abort', relay);
      let cleanupFailed = false;
      if (transport) {
        try {
          await bounded(transport.close(), {deadline: now() + 2});
        } catch {
          cleanupFailed = true;
        }
      }
      this.#active = undefined;
      finish();
      if (cleanupFailed) throw new ProviderUnavailable();
    }
  }
  async close(): Promise<void> {
    this.#closed = true;
    const active = this.#active;
    active?.controller.abort();
    if (active) await bounded(active.done, {deadline: now() + 2});
  }
}
