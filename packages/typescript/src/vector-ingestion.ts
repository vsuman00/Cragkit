/** Explicit bounded shadow-vector staging; no import-time I/O. */
import { createHash } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';
import { z } from 'zod';
import { PoolResource, bounded, check_options, type LeaseOptions, type PgClient } from './postgres-pool.js';
import { EXPECTED_HISTORY, _CATALOG_SQL, _HISTORY_SQL, _SCOPE_SQL, _COLLECTION_SQL } from './postgres-session.js';
import { canonicalize, type CanonicalDocument, type CanonicalOptions } from './canonical.js';
import { parse_scope, type TrustedScope } from './contracts.js';
import { EmbeddingAdapter, EmbeddingBatchSchema, FAKE_PROFILE, type EmbeddingBatch, type EmbeddingUsage } from './embeddings.js';
import * as lexical from './ingestion.js';
import { EmbeddingProfileMismatch, IndexNotReady, IntegrityViolation, InvalidRequest, UnauthorizedScope, UnsupportedCapability } from './errors.js';

export type VectorIngestionReceipt = lexical.IngestionReceipt & Readonly<{
  embedding_profile: string; provider_calls: number; usage: readonly EmbeddingUsage[];
}>;
export const _VECTOR_CAPABILITY_SQL = "SELECT current_setting('server_encoding')='UTF8'\n AND EXISTS (SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace\n  WHERE e.extname='vector' AND e.extversion='0.8.0' AND n.nspname='cragkit_vector')\n AND EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace\n  JOIN pg_depend d ON d.classid='pg_type'::regclass AND d.objid=t.oid AND d.deptype='e'\n  JOIN pg_extension e ON e.oid=d.refobjid AND d.refclassid='pg_extension'::regclass\n  WHERE n.nspname='cragkit_vector' AND t.typname='vector' AND t.typtype='b' AND e.extname='vector'\n  AND EXISTS (SELECT 1 FROM pg_proc p JOIN pg_depend pd ON pd.classid='pg_proc'::regclass AND pd.objid=p.oid AND pd.deptype='e'\n   WHERE p.pronamespace=n.oid AND p.proname='vector_dims' AND p.pronargs=1 AND p.proargtypes[0]=t.oid\n   AND p.prorettype='int4'::regtype AND NOT p.prosecdef AND pd.refclassid='pg_extension'::regclass AND pd.refobjid=e.oid))\n AND NOT EXISTS (SELECT 1 FROM (VALUES ('embedding_profiles'),('chunk_vectors_fake_1536')) expected(name)\n  LEFT JOIN pg_namespace n ON n.nspname='cragkit' LEFT JOIN pg_class c ON c.relnamespace=n.oid AND c.relname=expected.name\n  WHERE c.relkind IS DISTINCT FROM 'r' OR NOT coalesce(c.relrowsecurity,false))\n AND EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace\n  JOIN pg_attribute a ON a.attrelid=c.oid AND a.attname='embedding' AND NOT a.attisdropped\n  WHERE n.nspname='cragkit' AND c.relname='chunk_vectors_fake_1536'\n   AND a.atttypid=to_regtype('cragkit_vector.vector') AND a.atttypmod=1536)\n AND NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace\n  WHERE n.nspname IN ('cragkit','cragkit_vector') AND p.prosecdef)\n AND NOT EXISTS (SELECT 1 FROM pg_namespace n WHERE n.nspname='cragkit_vector'\n  AND (pg_has_role(current_user,n.nspowner,'MEMBER')\n   OR has_schema_privilege(current_user,n.oid,'CREATE')))\n AND NOT EXISTS (SELECT 1 FROM pg_extension e WHERE e.extname='vector'\n  AND pg_has_role(current_user,e.extowner,'MEMBER'))\n AND NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace\n  WHERE n.nspname='cragkit_vector' AND pg_has_role(current_user,p.proowner,'MEMBER'))\n AND NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace\n  WHERE n.nspname='cragkit_vector' AND pg_has_role(current_user,t.typowner,'MEMBER'))\n AND NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace\n  WHERE n.nspname='cragkit_vector' AND c.relname='setup_history'\n   AND (pg_has_role(current_user,c.relowner,'MEMBER') OR NOT row_security_active(c.oid)\n    OR has_table_privilege(current_user,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')\n    OR has_any_column_privilege(current_user,c.oid,'INSERT,UPDATE,REFERENCES')))" as const;
export const EXPECTED_VECTOR_HISTORY = [["0001_pgvector", "b98de4a67f46ab7cc7187447757b30844ceee01901a88186746ae322cf1a7e2c"], ["0002_vector_profiles", "33fda8141215cbdb961165822a13bc74639c97c41985529ce1b1b3ae585140fb"]] as const;
export const _SETUP_HISTORY_SQL = "SELECT version,checksum FROM cragkit_vector.setup_history ORDER BY version" as const;
export const _PROFILE_SQL = "SELECT profile_id,provider,model,dimensions,tokenizer,normalization,storage_table FROM cragkit.embedding_profiles ORDER BY profile_id" as const;
export const _VECTOR_JOB_SQL = "SELECT payload_sha256,generation_id,state,document_id,attempt_count\nFROM cragkit.ingestion_jobs WHERE tenant_id=$1 AND collection_id=$2 AND intent_id=$3 FOR UPDATE" as const;
export const _VECTOR_GENERATION_SQL = "SELECT revision_id,status,expected_chunk_count,embedding_profile,chunker_profile,lexical_profile\nFROM cragkit.index_generations WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3 AND generation_id=$4" as const;
export const _VECTOR_REVISION_SQL = "SELECT source_sha256,canonical_sha256,source_locator,parser_id,canonical_text\nFROM cragkit.document_revisions WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3 AND revision_id=$4" as const;
export const _MANIFEST_SQL = "SELECT chunk_id,ordinal,start_byte,end_byte,text,text_sha256,metadata FROM cragkit.chunks\nWHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3 AND generation_id=$4 ORDER BY ordinal" as const;
export const _MISSING_SQL = "SELECT c.chunk_id FROM cragkit.chunks c\nLEFT JOIN cragkit.chunk_vectors_fake_1536 v ON v.tenant_id=c.tenant_id AND v.collection_id=c.collection_id\n AND v.document_id=c.document_id AND v.revision_id=c.revision_id AND v.generation_id=c.generation_id AND v.chunk_id=c.chunk_id\nWHERE c.tenant_id=$1 AND c.collection_id=$2 AND c.document_id=$3 AND c.generation_id=$4\n AND v.chunk_id IS NULL ORDER BY c.ordinal" as const;
export const _VECTOR_COUNTS_SQL = "SELECT count(*)::int FROM cragkit.chunk_vectors_fake_1536\nWHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3 AND generation_id=$4 AND embedding_profile=$5" as const;
export const _GRANTS_SQL = "SELECT EXISTS(SELECT 1 FROM cragkit.document_grants WHERE tenant_id=$1 AND collection_id=$2\n AND document_id=$3 AND authorization_revision=$4\n AND (principal_id=$5 OR (principal_id IS NULL AND grant_id=ANY($6::text[]))))" as const;
export const _VECTOR_INSERT_SQL = "INSERT INTO cragkit.chunk_vectors_fake_1536\n(tenant_id,collection_id,document_id,revision_id,generation_id,embedding_profile,chunk_id,embedding)\nSELECT $1,$2,$3,$4,$5,$6,x.chunk_id,x.embedding::cragkit_vector.vector(1536)\nFROM jsonb_to_recordset($7::jsonb) AS x(chunk_id text,embedding text)\nON CONFLICT DO NOTHING RETURNING chunk_id" as const;

const hash = (value: unknown): string => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const profile_values = Object.values(FAKE_PROFILE);
const identity = (maximum = 256) => z.string().refine(value => /[^ \t\r\n\f\v]/.test(value)
  && !/[\0\uD800-\uDFFF]/u.test(value) && Buffer.byteLength(value) <= maximum);
const OptionsSchema = z.strictObject({
  collection: identity(128), document_id: identity(), intent_id: identity(), source_locator: identity(),
  scope: z.unknown(), deadline: z.number().finite(), signal: z.instanceof(AbortSignal).optional(),
  expected_generation_id: identity().nullable().optional(), metadata: z.unknown().optional(),
  format: z.string().default('text/plain'), canonical_options: z.unknown().optional(),
  before_publish: z.custom<() => Promise<void>>(value => typeof value === 'function').optional(),
});
function plain_data(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) return false;
  return Reflect.ownKeys(value).every(key => {
    const descriptor = Object.getOwnPropertyDescriptor(value, key)!;
    return typeof key === 'string' && 'value' in descriptor && descriptor.enumerable;
  });
}
function equal(actual: unknown, expected: unknown): boolean { return isDeepStrictEqual(actual, expected); }
type Prepared = Readonly<{
  document: CanonicalDocument; receipt: VectorIngestionReceipt; scope: TrustedScope;
  locator: string; metadata_json: string; expected: string | null; options: LeaseOptions; hook?: () => Promise<void>;
}>;
const key = (p: Prepared): string[] => [p.scope.tenant_id, p.receipt.collection, p.receipt.document_id];
const chunk_rows = (d: CanonicalDocument) => d.chunks.map(c => ({ chunk_id: c.chunk_id, ordinal: c.ordinal,
  start_byte: c.start_byte, end_byte: c.end_byte, text: c.text, text_sha256: c.text_sha256,
  metadata: { oversized_split: c.oversized_split, token_count: c.token_count, tokenizer_id: d.tokenizer_id } }));

export class PostgresVectorIndexer {
  private inflight = false;
  private readonly max_batches: number;
  private readonly max_attempts: number;
  constructor(private readonly resource: PoolResource, private readonly authorize_write: lexical.WriteAuthorizer,
    private readonly embedder: EmbeddingAdapter, limits: { max_batches?: number; max_attempts?: number } = {}) {
    try {
      if (!plain_data(limits) || typeof authorize_write !== 'function' || !(embedder instanceof EmbeddingAdapter)) throw new InvalidRequest();
      const parsed = z.strictObject({ max_batches: z.number().int().min(1).max(128).default(128),
        max_attempts: z.number().int().min(1).max(8).default(8) }).parse(limits);
      this.max_batches = parsed.max_batches; this.max_attempts = parsed.max_attempts;
    } catch { throw new InvalidRequest(); }
    if (!equal(embedder.profile, FAKE_PROFILE)) throw new UnsupportedCapability();
  }
  private async authorize(p: Prepared): Promise<void> {
    const allowed = await bounded(Promise.resolve().then(() => this.authorize_write(p.scope, p.receipt.collection, p.receipt.document_id)), p.options);
    check_options(p.options);
    if (allowed !== true) throw new UnauthorizedScope();
  }
  private async prepare(source: string | Uint8Array, input: lexical.IngestOptions): Promise<Prepared> {
    let parsed: z.infer<typeof OptionsSchema>;
    try { if (!plain_data(input)) throw new InvalidRequest(); parsed = OptionsSchema.parse(input); }
    catch { throw new InvalidRequest(); }
    const options = { deadline: parsed.deadline, signal: parsed.signal };
    check_options(options);
    const scope = parse_scope(parsed.scope);
    for (const value of [scope.tenant_id, scope.principal_id, scope.authorization_revision, ...scope.grant_ids]) {
      if (!identity().safeParse(value).success) throw new InvalidRequest();
    }
    const canonical_input = parsed.canonical_options ?? {};
    const allowed = ['max_source_bytes', 'target_bytes', 'max_chunk_bytes', 'token_counter', 'tokenizer_id', 'token_target', 'max_tokens'];
    if (!plain_data(canonical_input) || Object.keys(canonical_input).some(k => !allowed.includes(k))) throw new InvalidRequest();
    const canonical_options: CanonicalOptions = { ...canonical_input, format: parsed.format };
    const [metadata_json, metadata_hash] = lexical.metadata_snapshot(parsed.metadata ?? {});
    if (source instanceof Uint8Array) {
      if (source.byteLength > 16_777_216) throw new InvalidRequest();
      source = Uint8Array.from(source);
    }
    const permitted = await bounded(Promise.resolve().then(() => this.authorize_write(scope, parsed.collection, parsed.document_id)), options);
    check_options(options);
    if (permitted !== true) throw new UnauthorizedScope();
    const document = canonicalize(source, canonical_options);
    const expected = parsed.expected_generation_id ?? null;
    const [base, revision] = lexical.identifiers(document, scope, parsed.collection, parsed.document_id, parsed.intent_id,
      parsed.source_locator, metadata_hash, expected);
    const payload = hash(['cragkit.vector-ingest.v1', base, profile_values]);
    const receipt: VectorIngestionReceipt = Object.freeze({ tenant_id: scope.tenant_id, collection: parsed.collection,
      document_id: parsed.document_id, intent_id: parsed.intent_id, revision_id: revision,
      generation_id: hash(['cragkit.vector-generation.v1', payload]), payload_sha256: payload,
      canonical_sha256: document.canonical_sha256, chunk_count: document.chunks.length, replayed: false,
      embedding_profile: FAKE_PROFILE.profile_id, provider_calls: 0, usage: Object.freeze([]) });
    return { document, receipt, scope, locator: parsed.source_locator, metadata_json, expected, options, hook: parsed.before_publish };
  }
  private async transaction(p: Prepared, work: (client: PgClient, options: LeaseOptions) => Promise<VectorIngestionReceipt>): Promise<VectorIngestionReceipt> {
    await this.authorize(p);
    return lexical.write_transaction(this.resource, p.options, async (client, options) => {
      await this.bind(client, p, options);
      return work(client, options);
    });
  }
  private async bind(client: PgClient, p: Prepared, options: LeaseOptions): Promise<void> {
    const q = (sql: string, values?: readonly unknown[]) => lexical.query(client, sql, values, options);
    if (!equal(await q(lexical._WRITER_ROLE_SQL), [[true]])) throw new UnauthorizedScope();
    if (!equal(await q(_CATALOG_SQL), [[true]]) || !equal(await q(_HISTORY_SQL), EXPECTED_HISTORY)) throw new UnsupportedCapability();
    if (!equal(await q(_VECTOR_CAPABILITY_SQL), [[true]]) || !equal(await q(_SETUP_HISTORY_SQL), EXPECTED_VECTOR_HISTORY)
      || !equal(await q(_PROFILE_SQL), [[...profile_values, 'chunk_vectors_fake_1536']])) throw new UnsupportedCapability();
    const scope = p.scope;
    const grants = [...new Set(scope.grant_ids)].sort((a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b)));
    await q(_SCOPE_SQL, [scope.tenant_id, scope.principal_id, scope.authorization_revision, JSON.stringify(grants)]);
    await q(lexical._LOCK_SQL, [JSON.stringify(['cragkit.intent.v1', ...key(p).slice(0, 2), p.receipt.intent_id])]);
    await q(lexical._LOCK_SQL, [JSON.stringify(['cragkit.document.v1', ...key(p)])]);
  }
  private authorize_document(rows: unknown[][], scope: TrustedScope): void {
    if (rows.length !== 1 || rows[0].length !== 3 || rows[0][1] !== false || rows[0][2] !== scope.authorization_revision) throw new UnauthorizedScope();
  }
  private async authorized(client: PgClient, p: Prepared, options: LeaseOptions, require_expected = false): Promise<void> {
    const rows = await lexical.query(client, lexical._DOCUMENT_LOCK_SQL, key(p), options);
    this.authorize_document(rows, p.scope);
    if (!equal(await lexical.query(client, _GRANTS_SQL, [...key(p), p.scope.authorization_revision,
      p.scope.principal_id, p.scope.grant_ids], options), [[true]])) throw new UnauthorizedScope();
    if (require_expected && rows[0][0] !== p.expected) throw new IndexNotReady();
  }
  private async manifest(client: PgClient, p: Prepared, options: LeaseOptions, ready = false): Promise<void> {
    const q = (sql: string, values?: readonly unknown[]) => lexical.query(client, sql, values, options);
    const r = p.receipt, d = p.document, k = key(p);
    if (!equal(await q(_VECTOR_REVISION_SQL, [...k, r.revision_id]), [[d.source_sha256, d.canonical_sha256, p.locator, d.parser_id, d.canonical_text]])) throw new IntegrityViolation();
    if (!equal(await q(_VECTOR_GENERATION_SQL, [...k, r.generation_id]), [[r.revision_id, ready ? 'ready' : 'staging', r.chunk_count, FAKE_PROFILE.profile_id, d.chunker_profile, 'native_fts.v1']])) throw new IntegrityViolation();
    const actual = await q(_MANIFEST_SQL, [...k, r.generation_id]);
    const expected = chunk_rows(d).map(row => Object.values(row));
    // Native pg returns bigint spans as strings; normalize only exact safe decimal integers.
    for (const row of actual) for (const index of [2, 3]) {
      if (typeof row[index] === 'string' && /^(0|[1-9][0-9]*)$/.test(row[index] as string) && Number.isSafeInteger(Number(row[index]))) row[index] = Number(row[index]);
    }
    if (!equal(actual, expected)) throw new IntegrityViolation();
    const values = [...k, r.generation_id];
    if (!equal(await q(lexical._COUNTS_SQL, [...values, ...values]), [[r.chunk_count, r.chunk_count]])) throw new IntegrityViolation();
  }
  private batches(p: Prepared, missing: string[]): string[][] {
    const chunks = new Map(p.document.chunks.map(c => [c.chunk_id, c.text]));
    if (new Set(missing).size !== missing.length || missing.some(id => !chunks.has(id))) throw new IntegrityViolation();
    const result: string[][] = [];
    // Reuse E-r1 admission without exposing a new public adapter API.
    const admission = this.embedder as unknown as { inputs(texts: readonly string[]): unknown };
    for (const id of missing) {
      if (!result.length) result.push([]);
      const batch = result[result.length - 1];
      try { admission.inputs([...batch, id].map(k => chunks.get(k)!)); }
      catch (error) {
        if (!(error instanceof InvalidRequest) || !batch.length) throw error;
        admission.inputs([chunks.get(id)!]);
        if (result.length >= this.max_batches) throw new InvalidRequest();
        result.push([]);
      }
      result[result.length - 1].push(id);
    }
    if (result.length > this.max_batches) throw new InvalidRequest();
    return result;
  }
  async stage(source: string | Uint8Array, input: lexical.IngestOptions): Promise<VectorIngestionReceipt> {
    if (this.inflight) throw new IndexNotReady();
    this.inflight = true;
    try { return await this.stage_operation(source, input); }
    finally { this.inflight = false; }
  }
  private async stage_operation(source: string | Uint8Array, input: lexical.IngestOptions, prepared?: Prepared): Promise<VectorIngestionReceipt> {
    const p = prepared ?? await this.prepare(source, input);
    this.batches(p, p.document.chunks.map(c => c.chunk_id));
    let missing: string[] = [];
    const result = await this.transaction(p, async (client, options) => {
      const r = await this.stage_initial(client, p, options);
      if (!r.replayed) {
        const rows = await lexical.query(client, _MISSING_SQL, [...key(p), r.generation_id], options);
        if (rows.some(row => row.length !== 1 || typeof row[0] !== 'string')) throw new IntegrityViolation();
        missing = rows.map(row => row[0] as string);
      }
      return r;
    });
    const chunks = new Map(p.document.chunks.map(c => [c.chunk_id, c.text]));
    const usage: EmbeddingUsage[] = [];
    for (const ids of this.batches(p, missing)) {
      await this.transaction(p, async (client, options) => {
        await this.authorized(client, p, options, true); await this.manifest(client, p, options); return p.receipt;
      });
      const response = await this.embedder.embed_batch(ids.map(id => chunks.get(id)!), p.options);
      this.validate_batch(response, ids.length);
      usage.push(response.usage);
      await this.transaction(p, async (client, options) => {
        await this.authorized(client, p, options, true); await this.manifest(client, p, options);
        const rows = ids.map((id, index) => ({ chunk_id: id, embedding: JSON.stringify(response.vectors[index]) }));
        await lexical.query(client, _VECTOR_INSERT_SQL, [...key(p), p.receipt.revision_id, p.receipt.generation_id,
          FAKE_PROFILE.profile_id, JSON.stringify(rows)], options);
        return p.receipt;
      });
    }
    if (!result.replayed) await this.transaction(p, async (client, options) => {
      await this.authorized(client, p, options, true); await this.manifest(client, p, options);
      if (!equal(await lexical.query(client, _VECTOR_COUNTS_SQL, [...key(p), p.receipt.generation_id, FAKE_PROFILE.profile_id], options), [[p.receipt.chunk_count]])) throw new IntegrityViolation();
      return p.receipt;
    });
    return Object.freeze({ ...result, provider_calls: usage.length, usage: Object.freeze(usage) });
  }
  private validate_batch(response: EmbeddingBatch, count: number): void {
    if (!response || !equal(response.profile, FAKE_PROFILE)) throw new EmbeddingProfileMismatch();
    const checked = EmbeddingBatchSchema.safeParse(response);
    if (!checked.success) throw new IntegrityViolation();
    if (checked.data.vectors.some(v => v.length !== FAKE_PROFILE.dimensions)) throw new EmbeddingProfileMismatch();
    if (checked.data.vectors.length !== count || !checked.data.synthetic || checked.data.provider_calls !== 1
      || checked.data.vectors.some(v => v.some(x => !Number.isFinite(x)) || Math.abs(Math.sqrt(v.reduce((s, x) => s + x * x, 0)) - 1) > 0.001)) throw new IntegrityViolation();
  }
  private async stage_initial(client: PgClient, p: Prepared, options: LeaseOptions): Promise<VectorIngestionReceipt> {
    const q = (sql: string, values?: readonly unknown[]) => lexical.query(client, sql, values, options);
    const r = p.receipt, d = p.document, k = key(p);
    const jobs = await q(_VECTOR_JOB_SQL, [...k.slice(0, 2), r.intent_id]);
    if (jobs.length) {
      if (jobs.length !== 1 || jobs[0][0] !== r.payload_sha256 || jobs[0][3] !== r.document_id) throw new InvalidRequest();
      if (jobs[0][1] !== r.generation_id || !['running', 'succeeded'].includes(jobs[0][2] as string)) throw new IndexNotReady();
      const succeeded = jobs[0][2] === 'succeeded';
      await this.authorized(client, p, options, !succeeded); await this.manifest(client, p, options, succeeded);
      if (succeeded) {
        if (!equal(await q(_VECTOR_COUNTS_SQL, [...k, r.generation_id, FAKE_PROFILE.profile_id]), [[r.chunk_count]])) throw new IntegrityViolation();
        return Object.freeze({ ...r, replayed: true });
      }
      const stored_attempt = jobs[0][4];
      const attempt = typeof stored_attempt === 'string' && /^(0|[1-9][0-9]*)$/.test(stored_attempt)
        && Number.isSafeInteger(Number(stored_attempt)) ? Number(stored_attempt) : stored_attempt;
      if (typeof attempt !== 'number' || !Number.isSafeInteger(attempt) || attempt < 1 || attempt >= this.max_attempts) throw new IndexNotReady();
      await q('UPDATE cragkit.ingestion_jobs SET attempt_count=attempt_count+1 WHERE tenant_id=$1 AND collection_id=$2 AND intent_id=$3 RETURNING 1', [...k.slice(0, 2), r.intent_id]);
      return r;
    }
    await q('INSERT INTO cragkit.collections(tenant_id,collection_id) VALUES ($1,$2) ON CONFLICT DO NOTHING RETURNING collection_id', k.slice(0, 2));
    if (!equal(await q(_COLLECTION_SQL, k.slice(0, 2)), [['0.1', 'native_fts.v1']])) throw new UnsupportedCapability();
    const created = await q('INSERT INTO cragkit.documents(tenant_id,collection_id,document_id,authorization_revision) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING RETURNING document_id', [...k, p.scope.authorization_revision]);
    const documents = await q(lexical._DOCUMENT_LOCK_SQL, k);
    this.authorize_document(documents, p.scope);
    if ((!created.length && p.expected === null) || documents[0][0] !== p.expected) throw new IndexNotReady();
    if (created.length) await q('INSERT INTO cragkit.document_grants(tenant_id,collection_id,document_id,grant_id,principal_id,authorization_revision) VALUES ($1,$2,$3,$4,$5,$6) RETURNING 1', [...k, hash(['cragkit.principal.v1', p.scope.principal_id]), p.scope.principal_id, p.scope.authorization_revision]);
    await this.authorized(client, p, options);
    await q("INSERT INTO cragkit.ingestion_jobs(tenant_id,collection_id,document_id,intent_id,payload_sha256,generation_id,state,attempt_count) VALUES ($1,$2,$3,$4,$5,$6,'running',1) RETURNING 1", [...k, r.intent_id, r.payload_sha256, r.generation_id]);
    await q('INSERT INTO cragkit.document_revisions(tenant_id,collection_id,document_id,revision_id,source_sha256,source_locator,canonical_text,canonical_sha256,parser_id) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT DO NOTHING RETURNING revision_id', [...k, r.revision_id, d.source_sha256, p.locator, d.canonical_text, d.canonical_sha256, d.parser_id]);
    await q("INSERT INTO cragkit.index_generations(tenant_id,collection_id,document_id,revision_id,generation_id,chunker_profile,lexical_profile,embedding_profile,status,expected_chunk_count) VALUES ($1,$2,$3,$4,$5,$6,'native_fts.v1',$7,'staging',$8) RETURNING 1", [...k, r.revision_id, r.generation_id, d.chunker_profile, FAKE_PROFILE.profile_id, r.chunk_count]);
    await q(lexical._CHUNKS_SQL, [...k, r.revision_id, r.generation_id, JSON.stringify(chunk_rows(d))]);
    await q(lexical._LEXICAL_SQL, [...k, r.generation_id]);
    await this.manifest(client, p, options);
    return r;
  }
  async publish(source: string | Uint8Array, input: lexical.IngestOptions): Promise<VectorIngestionReceipt> {
    if (this.inflight) throw new IndexNotReady();
    this.inflight = true;
    try { return await this.publish_operation(source, input); }
    finally { this.inflight = false; }
  }
  private async publish_operation(source: string | Uint8Array, input: lexical.IngestOptions, prepared?: Prepared): Promise<VectorIngestionReceipt> {
    const p = prepared ?? await this.prepare(source, input);
    const hook = p.hook;
    return this.transaction(p, async (client, options) => {
      const q = (sql: string, values?: readonly unknown[]) => lexical.query(client, sql, values, options);
      const r = p.receipt, k = key(p);
      const jobs = await q(_VECTOR_JOB_SQL, [...k.slice(0, 2), r.intent_id]);
      if (!jobs.length) throw new IndexNotReady();
      if (jobs.length !== 1 || jobs[0][0] !== r.payload_sha256 || jobs[0][3] !== r.document_id) throw new InvalidRequest();
      if (jobs[0][1] !== r.generation_id || !['running', 'succeeded'].includes(jobs[0][2] as string)) throw new IndexNotReady();
      const succeeded = jobs[0][2] === 'succeeded';
      const barrier = async (): Promise<void> => {
        await this.authorized(client, p, options, !succeeded);
        await this.manifest(client, p, options, succeeded);
        if (!equal(await q(_VECTOR_COUNTS_SQL, [...k, r.generation_id, FAKE_PROFILE.profile_id]), [[r.chunk_count]])) throw new IntegrityViolation();
      };
      await barrier();
      if (succeeded) return Object.freeze({ ...r, replayed: true });
      if (hook) await bounded(Promise.resolve().then(hook), options);
      check_options(options);
      await this.authorize(p);
      await barrier();
      if (!equal(await q("UPDATE cragkit.index_generations SET status='ready' WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3 AND generation_id=$4 AND status='staging' AND embedding_profile=$5 RETURNING 1", [...k, r.generation_id, FAKE_PROFILE.profile_id]), [[1]])) throw new IntegrityViolation();
      if (!equal(await q('UPDATE cragkit.documents SET active_generation_id=$1,metadata=$2::jsonb WHERE tenant_id=$3 AND collection_id=$4 AND document_id=$5 AND active_generation_id IS NOT DISTINCT FROM $6 AND NOT tombstoned AND authorization_revision=$7 RETURNING 1', [r.generation_id, p.metadata_json, ...k, p.expected, p.scope.authorization_revision]), [[1]])) throw new IndexNotReady();
      if (!equal(await q("UPDATE cragkit.ingestion_jobs SET state='succeeded' WHERE tenant_id=$1 AND collection_id=$2 AND intent_id=$3 AND payload_sha256=$4 AND generation_id=$5 AND state='running' RETURNING 1", [...k.slice(0, 2), r.intent_id, r.payload_sha256, r.generation_id]), [[1]])) throw new IntegrityViolation();
      return r;
    });
  }
  async ingest(source: string | Uint8Array, input: lexical.IngestOptions): Promise<VectorIngestionReceipt> {
    if (this.inflight) throw new IndexNotReady();
    this.inflight = true;
    try {
      // Share the validated immutable snapshot across both halves of this invocation.
      const prepared = await this.prepare(source, input);
      const staged = await this.stage_operation(source, input, prepared);
      const published = await this.publish_operation(source, input, prepared);
      return Object.freeze({ ...published, provider_calls: staged.provider_calls, usage: staged.usage });
    } finally { this.inflight = false; }
  }
}
