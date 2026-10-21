/** Explicit native staged ingestion; no driver load or I/O at import. */
import { createHash } from 'node:crypto';
import { z } from 'zod';
import { PoolResource, bounded, check_options, now, type LeaseOptions, type PgClient } from './postgres-pool.js';
import { EXPECTED_HISTORY, _CATALOG_SQL, _HISTORY_SQL, _SCOPE_SQL, _COLLECTION_SQL } from './postgres-session.js';
import { canonicalize, type CanonicalDocument, type CanonicalOptions } from './canonical.js';
import { parse_scope, type TrustedScope } from './contracts.js';
import { valid_native_json } from './shared.js';
import { CragkitError, DeadlineExceeded, IndexNotReady, IntegrityViolation, InvalidRequest,
         ProviderUnavailable, UnauthorizedScope, UnsupportedCapability } from './errors.js';

export type IngestionReceipt = Readonly<{
  tenant_id: string; collection: string; document_id: string; intent_id: string;
  revision_id: string; generation_id: string; payload_sha256: string;
  canonical_sha256: string; chunk_count: number; replayed: boolean;
}>;
export type WriteAuthorizer = (scope: TrustedScope, collection: string, document_id: string) => Promise<boolean>;
export type IngestOptions = LeaseOptions & Readonly<{
  collection: string; document_id: string; intent_id: string; source_locator: string; scope: TrustedScope;
  expected_generation_id?: string | null; metadata?: Record<string, unknown> | null; format?: string;
  canonical_options?: Omit<CanonicalOptions, 'format'>; before_publish?: () => Promise<void>;
}>;
export const _WRITER_ROLE_SQL = "\nSELECT current_user = session_user\n AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolcanlogin)\n AND NOT EXISTS (\n   SELECT 1 FROM pg_roles r WHERE pg_has_role(current_user,r.oid,'MEMBER')\n     AND (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication)\n ) AND NOT EXISTS (\n   SELECT 1 FROM pg_namespace n WHERE n.nspname='cragkit'\n     AND (pg_has_role(current_user,n.nspowner,'MEMBER') OR has_schema_privilege(current_user,n.oid,'CREATE'))\n ) AND NOT EXISTS (\n   SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace\n   WHERE n.nspname='cragkit' AND c.relkind IN ('r','p')\n     AND (pg_has_role(current_user,c.relowner,'MEMBER') OR NOT row_security_active(c.oid)\n          OR has_table_privilege(current_user,c.oid,'TRUNCATE')\n          OR has_table_privilege(current_user,c.oid,'DELETE'))\n ) AND NOT EXISTS (\n   SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace\n   WHERE n.nspname='cragkit' AND pg_has_role(current_user,p.proowner,'MEMBER')\n ) AND NOT EXISTS (\n   SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace\n   WHERE n.nspname='cragkit' AND pg_has_role(current_user,t.typowner,'MEMBER')\n )\n";
export const _LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended($1,0))";
export const _JOB_SQL = "SELECT payload_sha256,generation_id,state,document_id FROM cragkit.ingestion_jobs\nWHERE tenant_id=$1 AND collection_id=$2 AND intent_id=$3 FOR UPDATE";
export const _DOCUMENT_LOCK_SQL = "SELECT active_generation_id,tombstoned,authorization_revision FROM cragkit.documents\nWHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3 FOR UPDATE";
export const _REVISION_SQL = "SELECT source_sha256,canonical_sha256,source_locator,parser_id FROM cragkit.document_revisions\nWHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3 AND revision_id=$4";
export const _GENERATION_SQL = "SELECT revision_id,status,expected_chunk_count FROM cragkit.index_generations\nWHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3 AND generation_id=$4";
export const _COUNTS_SQL = "SELECT\n (SELECT count(*)::int FROM cragkit.chunks WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3 AND generation_id=$4),\n (SELECT count(*)::int FROM cragkit.chunk_lexical WHERE tenant_id=$5 AND collection_id=$6 AND document_id=$7 AND generation_id=$8)";
export const _CHUNKS_SQL = "INSERT INTO cragkit.chunks\n(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,ordinal,start_byte,end_byte,text,text_sha256,metadata)\nSELECT $1,$2,$3,$4,$5,x.chunk_id,x.ordinal,x.start_byte,x.end_byte,x.text,x.text_sha256,x.metadata\nFROM jsonb_to_recordset($6::jsonb) AS x(chunk_id text,ordinal integer,start_byte bigint,end_byte bigint,\n text text,text_sha256 text,metadata jsonb) RETURNING 1";
export const _LEXICAL_SQL = "INSERT INTO cragkit.chunk_lexical\n(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,language_config,search_vector)\nSELECT tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,'pg_catalog.simple',''::tsvector\nFROM cragkit.chunks WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3 AND generation_id=$4 RETURNING 1";

const digest = (value: string | Uint8Array): string => createHash('sha256').update(value).digest('hex');
const hash = (value: unknown): string => digest(JSON.stringify(value));
const utf8_order = (a: string, b: string): number => Buffer.compare(Buffer.from(a), Buffer.from(b));
const identity = (maximum = 256) => z.string().refine(value => /[^ \t\r\n\f\v]/.test(value)
  && !/[\0\uD800-\uDFFF]/u.test(value) && Buffer.byteLength(value) <= maximum);
const OptionsSchema = z.strictObject({
  collection: identity(128), document_id: identity(), intent_id: identity(), source_locator: identity(),
  scope: z.unknown(), deadline: z.number().finite(), signal: z.instanceof(AbortSignal).optional(),
  expected_generation_id: identity().nullable().optional(), metadata: z.unknown().optional(),
  format: z.string().default('text/plain'), canonical_options: z.unknown().optional(),
  before_publish: z.custom<() => Promise<void>>(value => typeof value === 'function').optional(),
});
function plain_data(input: unknown): input is Record<string, unknown> {
  if (!input || typeof input !== 'object' || ![Object.prototype, null].includes(Object.getPrototypeOf(input))) return false;
  return Reflect.ownKeys(input).every(key => {
    const descriptor = Object.getOwnPropertyDescriptor(input, key)!;
    return typeof key === 'string' && 'value' in descriptor && descriptor.enumerable;
  });
}

/** Internal fixture hook: bounded metadata TLV is independent of JSON number spelling. */
export function metadata_snapshot(value: unknown): readonly [string, string] {
  try { return metadata_checked(value); } catch { throw new InvalidRequest(); }
}
function metadata_checked(value: unknown): readonly [string, string] {
  if (!plain_data(value) || !valid_native_json(value)) throw new InvalidRequest();
  const pieces: Buffer[] = [];
  let length = 0;
  const append = (data: Buffer): void => {
    length += data.length;
    if (length > 65_536) throw new InvalidRequest();
    pieces.push(data);
  };
  const count = (size: number): Buffer => { const buffer = Buffer.alloc(4); buffer.writeUInt32BE(size); return buffer; };
  const encode = (item: unknown): void => {
    if (item === null) append(Buffer.from('n'));
    else if (typeof item === 'boolean') append(Buffer.from(item ? 't' : 'f'));
    else if (typeof item === 'number') {
      const buffer = Buffer.alloc(9); buffer[0] = 100; buffer.writeDoubleBE(item === 0 ? 0 : item, 1); append(buffer);
    } else if (typeof item === 'string') {
      if (item.length > 65_536 || item.includes('\0') || /[\uD800-\uDFFF]/u.test(item)) throw new InvalidRequest();
      const data = Buffer.from(item);
      append(Buffer.concat([Buffer.from('s'), count(data.length), data]));
    } else if (Array.isArray(item)) {
      append(Buffer.concat([Buffer.from('a'), count(item.length)]));
      for (const child of item) encode(child);
    } else {
      const object = item as Record<string, unknown>;
      const keys = Object.keys(object).sort(utf8_order);
      append(Buffer.concat([Buffer.from('o'), count(keys.length)]));
      for (const key of keys) { encode(key); encode(object[key]); }
    }
  };
  try {
    encode(value);
    return Object.freeze([JSON.stringify(value), digest(Buffer.concat(pieces))]);
  } catch { throw new InvalidRequest(); }
}
export function identifiers(document: CanonicalDocument, scope: TrustedScope, collection: string,
                            document_id: string, intent_id: string, locator: string,
                            metadata_hash: string, expected: string | null): readonly [string, string, string] {
  const grants = [...new Set(scope.grant_ids)].sort(utf8_order);
  const manifest = hash(document.chunks.map(chunk => [chunk.chunk_id, String(chunk.start_byte), String(chunk.end_byte),
    chunk.text_sha256, chunk.oversized_split ? 'true' : 'false', chunk.token_count === null ? null : String(chunk.token_count)]));
  const payload = hash(['cragkit.ingest.v1', scope.tenant_id, collection, document_id, intent_id, locator,
    document.source_sha256, document.canonical_sha256, document.parser_id, document.chunker_profile,
    metadata_hash, manifest, scope.principal_id, scope.authorization_revision, grants, expected]);
  const revision = hash(['cragkit.revision.v1', scope.tenant_id, collection, document_id, document.source_sha256,
    document.canonical_sha256, document.parser_id, locator]);
  return Object.freeze([payload, revision, hash(['cragkit.generation.v1', payload])]);
}
function safe_error(error: unknown): Error {
  if (error instanceof CragkitError || (error instanceof DOMException && error.name === 'AbortError')) return error;
  const code = error !== null && typeof error === 'object' ? (error as { code?: unknown }).code : undefined;
  if (code === '57014') return new DeadlineExceeded();
  if (typeof code === 'string' && code.startsWith('23')) return new IntegrityViolation();
  if (code === '42501') return new UnauthorizedScope();
  if (['42P01', '42703', '42883', '3F000'].includes(String(code))) return new UnsupportedCapability();
  return new ProviderUnavailable();
}
const equal = (actual: unknown, expected: unknown): boolean => JSON.stringify(actual) === JSON.stringify(expected);
async function query(client: PgClient, text: string, values: readonly unknown[] | undefined,
                     options: LeaseOptions): Promise<unknown[][]> {
  check_options(options);
  try {
    const timeout = Math.max(1, Math.floor(Math.min(options.deadline - now(), 2_147_483.647) * 1000));
    await bounded(client.query({ text: "SELECT set_config('statement_timeout',$1,true)", values: [String(timeout)], rowMode: 'array' }), options);
    const result = await bounded(client.query({ text, values, rowMode: 'array' }), options);
    check_options(options);
    if (!result || !Array.isArray(result.rows) || result.rows.some(row => !Array.isArray(row))) throw new UnsupportedCapability();
    return result.rows;
  } catch (error) { throw safe_error(error); }
}

export class PostgresIndexer {
  constructor(private readonly resource: PoolResource, private readonly authorize_write: WriteAuthorizer) {
    if (typeof authorize_write !== 'function') throw new InvalidRequest();
  }
  async ingest(source: string | Uint8Array, input: IngestOptions): Promise<IngestionReceipt> {
    let parsed: z.infer<typeof OptionsSchema>;
    try { if (!plain_data(input)) throw new InvalidRequest(); parsed = OptionsSchema.parse(input); }
    catch { throw new InvalidRequest(); }
    check_options({ deadline: parsed.deadline, signal: parsed.signal });
    const scope = parse_scope(parsed.scope);
    for (const value of [scope.tenant_id, scope.principal_id, scope.authorization_revision, ...scope.grant_ids]) {
      if (!identity().safeParse(value).success) throw new InvalidRequest();
    }
    const canonical_input = parsed.canonical_options ?? {};
    const allowedKeys = ['max_source_bytes', 'target_bytes', 'max_chunk_bytes', 'token_counter', 'tokenizer_id', 'token_target', 'max_tokens'];
    if (!plain_data(canonical_input) || Object.keys(canonical_input).some(key => !allowedKeys.includes(key))) throw new InvalidRequest();
    const canonical_options: CanonicalOptions = { ...canonical_input, format: parsed.format };
    const [metadata_json, metadata_hash] = metadata_snapshot(parsed.metadata ?? {});
    const options = { deadline: parsed.deadline, signal: parsed.signal };
    // Uint8Array is mutable; bind caller bytes before the authorization await.
    if (source instanceof Uint8Array) {
      if (source.byteLength > 16_777_216) throw new InvalidRequest();
      source = Uint8Array.from(source);
    }
    const allowed = await bounded(Promise.resolve().then(() => this.authorize_write(scope, parsed.collection, parsed.document_id)), options);
    check_options(options);
    if (allowed !== true) throw new UnauthorizedScope();
    const document = canonicalize(source, canonical_options);
    const expected = parsed.expected_generation_id ?? null;
    const [payload, revision, generation] = identifiers(document, scope, parsed.collection, parsed.document_id,
      parsed.intent_id, parsed.source_locator, metadata_hash, expected);
    const receipt: IngestionReceipt = Object.freeze({ tenant_id: scope.tenant_id, collection: parsed.collection,
      document_id: parsed.document_id, intent_id: parsed.intent_id, revision_id: revision, generation_id: generation,
      payload_sha256: payload, canonical_sha256: document.canonical_sha256, chunk_count: document.chunks.length, replayed: false });
    check_options(options);
    return this.resource.withLease(options, async (client, signal) => {
      const boundedOptions = { deadline: options.deadline, signal };
      let status: string | null;
      try { status = client.getTransactionStatus(); } catch (error) { throw safe_error(error); }
      if (status !== 'I') throw new InvalidRequest();
      let begun = false;
      let commitAttempted = false;
      let succeeded = false;
      try {
        try {
          await bounded(client.query({ text: 'BEGIN', rowMode: 'array' }), boundedOptions);
          begun = true;
          await bounded(client.query({ text: 'SET LOCAL search_path = pg_catalog', rowMode: 'array' }), boundedOptions);
        } catch (error) { throw safe_error(error); }
        const result = await this.stage(client, document, receipt, scope, parsed.source_locator,
          metadata_json, expected, boundedOptions, parsed.before_publish);
        check_options(boundedOptions);
        commitAttempted = true;
        try { await bounded(client.query({ text: 'COMMIT', rowMode: 'array' }), boundedOptions); }
        catch (error) { throw safe_error(error); }
        if (client.getTransactionStatus() !== 'I') throw new ProviderUnavailable();
        check_options(boundedOptions);
        succeeded = true;
        return result;
      } finally {
        if (!succeeded) {
          let clean = false;
          if (begun && !commitAttempted && !signal.aborted) {
            try {
              await bounded(client.query({ text: 'ROLLBACK', rowMode: 'array' }), { deadline: now() + this.resource.config.release_timeout });
              clean = client.getTransactionStatus() === 'I';
            } catch {}
          }
          if (!clean) { try { client.release(true); } catch {} }
        }
      }
    });
  }
  private authorize_document(rows: unknown[][], scope: TrustedScope): void {
    if (rows.length !== 1 || rows[0].length !== 3 || rows[0][1] !== false || rows[0][2] !== scope.authorization_revision) throw new UnauthorizedScope();
  }
  private async counts(client: PgClient, key: readonly string[], receipt: IngestionReceipt, options: LeaseOptions): Promise<void> {
    const values = [...key, receipt.generation_id];
    if (!equal(await query(client, _COUNTS_SQL, [...values, ...values], options), [[receipt.chunk_count, receipt.chunk_count]])) throw new IntegrityViolation();
  }
  private async stage(client: PgClient, document: CanonicalDocument, receipt: IngestionReceipt, scope: TrustedScope,
                      locator: string, metadata: string, expected: string | null, options: LeaseOptions,
                      hook?: () => Promise<void>): Promise<IngestionReceipt> {
    const q = (text: string, values?: readonly unknown[]): Promise<unknown[][]> => query(client, text, values, options);
    if (!equal(await q(_WRITER_ROLE_SQL), [[true]])) throw new UnauthorizedScope();
    if (!equal(await q(_CATALOG_SQL), [[true]])) throw new UnsupportedCapability();
    if (!equal(await q(_HISTORY_SQL), EXPECTED_HISTORY)) throw new UnsupportedCapability();
    await q(_SCOPE_SQL, [scope.tenant_id, scope.principal_id, scope.authorization_revision, JSON.stringify([...new Set(scope.grant_ids)].sort(utf8_order))]);
    const key = [scope.tenant_id, receipt.collection, receipt.document_id];
    await q(_LOCK_SQL, [JSON.stringify(['cragkit.intent.v1', ...key.slice(0, 2), receipt.intent_id])]);
    await q(_LOCK_SQL, [JSON.stringify(['cragkit.document.v1', ...key])]);
    const jobs = await q(_JOB_SQL, [...key.slice(0, 2), receipt.intent_id]);
    if (jobs.length) {
      if (jobs.length !== 1 || jobs[0][0] !== receipt.payload_sha256 || jobs[0][3] !== receipt.document_id) throw new InvalidRequest();
      if (jobs[0][1] !== receipt.generation_id || jobs[0][2] !== 'succeeded') throw new IndexNotReady();
      this.authorize_document(await q(_DOCUMENT_LOCK_SQL, key), scope);
      if (!equal(await q(_GENERATION_SQL, [...key, receipt.generation_id]), [[receipt.revision_id, 'ready', receipt.chunk_count]])) throw new IntegrityViolation();
      await this.counts(client, key, receipt, options);
      return Object.freeze({ ...receipt, replayed: true });
    }
    await q('INSERT INTO cragkit.collections(tenant_id,collection_id) VALUES ($1,$2) ON CONFLICT DO NOTHING RETURNING collection_id', key.slice(0, 2));
    if (!equal(await q(_COLLECTION_SQL, key.slice(0, 2)), [['0.1', 'native_fts.v1']])) throw new UnsupportedCapability();
    const created = await q('INSERT INTO cragkit.documents(tenant_id,collection_id,document_id,authorization_revision) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING RETURNING document_id', [...key, scope.authorization_revision]);
    const documents = await q(_DOCUMENT_LOCK_SQL, key);
    this.authorize_document(documents, scope);
    if ((!created.length && expected === null) || documents[0][0] !== expected) throw new IndexNotReady();
    await q("INSERT INTO cragkit.ingestion_jobs(tenant_id,collection_id,document_id,intent_id,payload_sha256,generation_id,state,attempt_count) VALUES ($1,$2,$3,$4,$5,$6,'running',1) RETURNING 1", [...key, receipt.intent_id, receipt.payload_sha256, receipt.generation_id]);
    await q('INSERT INTO cragkit.document_revisions(tenant_id,collection_id,document_id,revision_id,source_sha256,source_locator,canonical_text,canonical_sha256,parser_id) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT DO NOTHING RETURNING revision_id', [...key, receipt.revision_id, document.source_sha256, locator, document.canonical_text, document.canonical_sha256, document.parser_id]);
    if (!equal(await q(_REVISION_SQL, [...key, receipt.revision_id]), [[document.source_sha256, document.canonical_sha256, locator, document.parser_id]])) throw new IntegrityViolation();
    await q("INSERT INTO cragkit.index_generations(tenant_id,collection_id,document_id,revision_id,generation_id,chunker_profile,lexical_profile,status,expected_chunk_count) VALUES ($1,$2,$3,$4,$5,$6,'native_fts.v1','staging',$7) RETURNING 1", [...key, receipt.revision_id, receipt.generation_id, document.chunker_profile, document.chunks.length]);
    const chunks = document.chunks.map(chunk => ({ chunk_id: chunk.chunk_id, ordinal: chunk.ordinal, start_byte: chunk.start_byte,
      end_byte: chunk.end_byte, text: chunk.text, text_sha256: chunk.text_sha256,
      metadata: { oversized_split: chunk.oversized_split, token_count: chunk.token_count, tokenizer_id: document.tokenizer_id } }));
    await q(_CHUNKS_SQL, [...key, receipt.revision_id, receipt.generation_id, JSON.stringify(chunks)]);
    await q(_LEXICAL_SQL, [...key, receipt.generation_id]);
    if (created.length) await q('INSERT INTO cragkit.document_grants(tenant_id,collection_id,document_id,grant_id,principal_id,authorization_revision) VALUES ($1,$2,$3,$4,$5,$6) RETURNING 1', [...key, hash(['cragkit.principal.v1', scope.principal_id]), scope.principal_id, scope.authorization_revision]);
    await this.counts(client, key, receipt, options);
    if (hook) await bounded(Promise.resolve().then(hook), options);
    check_options(options);
    if (!equal(await q("UPDATE cragkit.index_generations SET status='ready' WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3 AND generation_id=$4 RETURNING 1", [...key, receipt.generation_id]), [[1]])) throw new IntegrityViolation();
    const changed = await q('UPDATE cragkit.documents SET active_generation_id=$1,metadata=$2::jsonb WHERE tenant_id=$3 AND collection_id=$4 AND document_id=$5 AND active_generation_id IS NOT DISTINCT FROM $6 AND NOT tombstoned AND authorization_revision=$7 RETURNING 1', [receipt.generation_id, metadata, ...key, expected, scope.authorization_revision]);
    if (!equal(changed, [[1]])) throw new IndexNotReady();
    if (!equal(await q("UPDATE cragkit.ingestion_jobs SET state='succeeded' WHERE tenant_id=$1 AND collection_id=$2 AND intent_id=$3 AND payload_sha256=$4 RETURNING 1", [...key.slice(0, 2), receipt.intent_id, receipt.payload_sha256]), [[1]])) throw new IntegrityViolation();
    return receipt;
  }
}
