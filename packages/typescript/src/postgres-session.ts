/** Internal read-only scoped lifecycle and native lexical candidates. */
import { validate_identifier } from './identifiers.js';
import { z } from 'zod';
import { isDeepStrictEqual } from 'node:util';
import { EmbeddingBatchSchema, FAKE_PROFILE, type EmbeddingBatch } from './embeddings.js';
import { valid_native_json } from './shared.js';
import { verify_source, type SourceFetch } from './postgres-source.js';
import { AsyncLocalStorage } from 'node:async_hooks';
import { PoolResource, bounded, check_options, now, type LeaseOptions, type PgClient } from './postgres-pool.js';
import { parse_request, parse_scope, type RetrievalRequest, type TrustedScope } from './contracts.js';
import { CragkitError, EmbeddingProfileMismatch, DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability } from './errors.js';

export const EXPECTED_HISTORY: readonly (readonly string[])[] = Object.freeze([["0001_initial", "5a7259e6375f8578c8775fe91994bd28b85ff76734744dc2c2b4ee63f623d92f"], ["0002_portable_lexical_config", "a7380a57690791bc5766d969decba36b5a5ec4591d7481601eb0fd5ce096c875"]].map(row => Object.freeze(row)));
export const _CATALOG_SQL = `
SELECT current_setting('server_encoding') = 'UTF8'
 AND to_regprocedure('pg_catalog.to_tsvector(regconfig,text)') IS NOT NULL
 AND to_regprocedure('pg_catalog.websearch_to_tsquery(regconfig,text)') IS NOT NULL
 AND NOT EXISTS (
   SELECT 1 FROM (VALUES ('collections','tenant_id','cragkit.identity_text'),
     ('collections','collection_id','cragkit.collection_text'),
     ('collections','schema_version','pg_catalog.text'),
     ('collections','active_profile','cragkit.identity_text'),
     ('collections','policy_metadata','pg_catalog.jsonb'),
     ('collections','created_at','pg_catalog.timestamptz'),
     ('documents','tenant_id','cragkit.identity_text'),
     ('documents','collection_id','cragkit.collection_text'),
     ('documents','document_id','cragkit.identity_text'),
     ('documents','active_generation_id','cragkit.identity_text'),
     ('documents','tombstoned','pg_catalog.bool'),
     ('documents','metadata','pg_catalog.jsonb'),
     ('documents','authorization_revision','cragkit.identity_text'),
     ('documents','created_at','pg_catalog.timestamptz'),
     ('document_revisions','tenant_id','cragkit.identity_text'),
     ('document_revisions','collection_id','cragkit.collection_text'),
     ('document_revisions','document_id','cragkit.identity_text'),
     ('document_revisions','revision_id','cragkit.identity_text'),
     ('document_revisions','source_sha256','cragkit.sha256_hex'),
     ('document_revisions','source_locator','cragkit.identity_text'),
     ('document_revisions','canonical_text','pg_catalog.text'),
     ('document_revisions','canonical_sha256','cragkit.sha256_hex'),
     ('document_revisions','parser_id','cragkit.identity_text'),
     ('document_revisions','created_at','pg_catalog.timestamptz'),
     ('index_generations','tenant_id','cragkit.identity_text'),
     ('index_generations','collection_id','cragkit.collection_text'),
     ('index_generations','document_id','cragkit.identity_text'),
     ('index_generations','revision_id','cragkit.identity_text'),
     ('index_generations','generation_id','cragkit.identity_text'),
     ('index_generations','chunker_profile','cragkit.identity_text'),
     ('index_generations','lexical_profile','cragkit.identity_text'),
     ('index_generations','embedding_profile','cragkit.identity_text'),
     ('index_generations','status','pg_catalog.text'),
     ('index_generations','expected_chunk_count','pg_catalog.int4'),
     ('index_generations','created_at','pg_catalog.timestamptz'),
     ('chunks','tenant_id','cragkit.identity_text'),
     ('chunks','collection_id','cragkit.collection_text'),
     ('chunks','document_id','cragkit.identity_text'),
     ('chunks','revision_id','cragkit.identity_text'),
     ('chunks','generation_id','cragkit.identity_text'),
     ('chunks','chunk_id','cragkit.identity_text'),
     ('chunks','parent_chunk_id','cragkit.identity_text'),
     ('chunks','ordinal','pg_catalog.int4'),
     ('chunks','start_byte','cragkit.safe_count'),
     ('chunks','end_byte','cragkit.safe_count'),
     ('chunks','text','pg_catalog.text'),
     ('chunks','text_sha256','cragkit.sha256_hex'),
     ('chunks','metadata','pg_catalog.jsonb'),
     ('chunk_lexical','tenant_id','cragkit.identity_text'),
     ('chunk_lexical','collection_id','cragkit.collection_text'),
     ('chunk_lexical','document_id','cragkit.identity_text'),
     ('chunk_lexical','revision_id','cragkit.identity_text'),
     ('chunk_lexical','generation_id','cragkit.identity_text'),
     ('chunk_lexical','chunk_id','cragkit.identity_text'),
     ('chunk_lexical','language_config','pg_catalog.text'),
     ('chunk_lexical','search_vector','pg_catalog.tsvector'),
     ('chunk_lexical','identifier_tokens','cragkit.identity_text[]'),
     ('document_grants','tenant_id','cragkit.identity_text'),
     ('document_grants','collection_id','cragkit.collection_text'),
     ('document_grants','document_id','cragkit.identity_text'),
     ('document_grants','grant_id','cragkit.identity_text'),
     ('document_grants','principal_id','cragkit.identity_text'),
     ('document_grants','authorization_revision','cragkit.identity_text'),
     ('ingestion_jobs','tenant_id','cragkit.identity_text'),
     ('ingestion_jobs','collection_id','cragkit.collection_text'),
     ('ingestion_jobs','document_id','cragkit.identity_text'),
     ('ingestion_jobs','intent_id','cragkit.identity_text'),
     ('ingestion_jobs','payload_sha256','cragkit.sha256_hex'),
     ('ingestion_jobs','generation_id','cragkit.identity_text'),
     ('ingestion_jobs','state','pg_catalog.text'),
     ('ingestion_jobs','attempt_count','cragkit.safe_count'),
     ('ingestion_jobs','last_error_code','pg_catalog.text'),
     ('ingestion_jobs','created_at','pg_catalog.timestamptz'),
     ('migration_history','version','pg_catalog.text'),
     ('migration_history','checksum','pg_catalog.text'),
     ('migration_history','applied_at','pg_catalog.timestamptz')) expected(tbl,col,typ)
   LEFT JOIN pg_namespace n ON n.nspname='cragkit'
   LEFT JOIN pg_class c ON c.relnamespace=n.oid AND c.relname=expected.tbl
   LEFT JOIN pg_attribute a ON a.attrelid=c.oid AND a.attname=expected.col
     AND a.attnum>0 AND NOT a.attisdropped
   WHERE c.relkind IS DISTINCT FROM 'r' OR NOT c.relrowsecurity
     OR a.atttypid IS DISTINCT FROM to_regtype(expected.typ)
 ) AND NOT EXISTS (
   SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname='cragkit' AND p.prosecdef
 )
`;
export const _ROLE_SQL = `
SELECT current_user = session_user
 AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolcanlogin)
 AND NOT EXISTS (
   SELECT 1 FROM pg_roles r WHERE pg_has_role(current_user,r.oid,'MEMBER')
     AND (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication)
 ) AND NOT EXISTS (
   SELECT 1 FROM pg_namespace n WHERE n.nspname='cragkit'
     AND (pg_has_role(current_user,n.nspowner,'MEMBER')
       OR has_schema_privilege(current_user,n.oid,'CREATE'))
 ) AND NOT EXISTS (
   SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='cragkit' AND c.relkind IN ('r','p')
     AND (pg_has_role(current_user,c.relowner,'MEMBER')
       OR NOT row_security_active(c.oid)
       OR has_table_privilege(current_user,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
       OR has_any_column_privilege(current_user,c.oid,'INSERT,UPDATE,REFERENCES'))
 ) AND NOT EXISTS (
   SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname='cragkit' AND pg_has_role(current_user,p.proowner,'MEMBER')
 ) AND NOT EXISTS (
   SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
   WHERE n.nspname='cragkit' AND pg_has_role(current_user,t.typowner,'MEMBER')
 )
`;
export const _HISTORY_SQL = `SELECT version, checksum FROM cragkit.migration_history ORDER BY version`;
export const _COLLECTION_SQL = `SELECT schema_version, active_profile FROM cragkit.collections WHERE tenant_id=$1 AND collection_id=$2`;
export const _SCOPE_SQL = `SELECT
 set_config('cragkit.tenant_id',$1,true),
 set_config('cragkit.principal_id',$2,true),
 set_config('cragkit.authorization_revision',$3,true),
 set_config('cragkit.grant_ids',$4,true)
`;
export const _DOCUMENT_SQL = `
SELECT d.document_id, g.revision_id, g.lexical_profile
FROM cragkit.documents d
JOIN cragkit.index_generations g ON g.tenant_id=d.tenant_id
 AND g.collection_id=d.collection_id AND g.document_id=d.document_id
 AND g.generation_id=d.active_generation_id
WHERE d.tenant_id=$1 AND d.collection_id=$2 AND NOT d.tombstoned
 AND d.authorization_revision=$3 AND g.status='ready'
 AND EXISTS (
   SELECT 1 FROM cragkit.document_grants x
   WHERE x.tenant_id=d.tenant_id AND x.collection_id=d.collection_id
     AND x.document_id=d.document_id AND x.authorization_revision=$4
     AND (x.principal_id=$5 OR (x.principal_id IS NULL AND x.grant_id=ANY($6::text[])))
 ) AND ({predicate})
ORDER BY d.document_id COLLATE pg_catalog."C", g.revision_id COLLATE pg_catalog."C"
LIMIT {limit}
`;

export const _LEXICAL_SQL = `
WITH search AS (SELECT websearch_to_tsquery('pg_catalog.simple'::regconfig,$1) AS query)
SELECT d.tenant_id,d.collection_id,d.document_id,g.revision_id,g.generation_id,c.chunk_id,
 c.start_byte,c.end_byte,c.text_sha256,ts_rank_cd(l.search_vector,search.query)::double precision,g.lexical_profile,l.language_config
FROM cragkit.documents d
JOIN cragkit.index_generations g ON g.tenant_id=d.tenant_id AND g.collection_id=d.collection_id
 AND g.document_id=d.document_id AND g.generation_id=d.active_generation_id
JOIN cragkit.chunks c ON c.tenant_id=g.tenant_id AND c.collection_id=g.collection_id
 AND c.document_id=g.document_id AND c.revision_id=g.revision_id AND c.generation_id=g.generation_id
JOIN cragkit.chunk_lexical l ON l.tenant_id=c.tenant_id AND l.collection_id=c.collection_id
 AND l.document_id=c.document_id AND l.revision_id=c.revision_id AND l.generation_id=c.generation_id AND l.chunk_id=c.chunk_id
CROSS JOIN search
WHERE d.tenant_id=$2 AND d.collection_id=$3 AND NOT d.tombstoned
 AND d.authorization_revision=$4 AND g.status='ready'
 AND EXISTS(SELECT 1 FROM cragkit.document_grants x WHERE x.tenant_id=d.tenant_id AND x.collection_id=d.collection_id
  AND x.document_id=d.document_id AND x.authorization_revision=$5
  AND (x.principal_id=$6 OR (x.principal_id IS NULL AND x.grant_id=ANY($7::text[]))))
 AND ({predicate}) AND l.search_vector @@ search.query
ORDER BY ts_rank_cd(l.search_vector,search.query) DESC,d.document_id COLLATE pg_catalog."C",
 g.revision_id COLLATE pg_catalog."C",c.ordinal,c.chunk_id COLLATE pg_catalog."C"
LIMIT {limit}
`;
export const _IDENTIFIER_SQL = `
SELECT d.tenant_id,d.collection_id,d.document_id,g.revision_id,g.generation_id,c.chunk_id,
 c.start_byte,c.end_byte,c.text_sha256,1.0::double precision,g.lexical_profile,l.language_config
FROM cragkit.documents d
JOIN cragkit.index_generations g ON g.tenant_id=d.tenant_id AND g.collection_id=d.collection_id
 AND g.document_id=d.document_id AND g.generation_id=d.active_generation_id
JOIN cragkit.chunks c ON c.tenant_id=g.tenant_id AND c.collection_id=g.collection_id
 AND c.document_id=g.document_id AND c.revision_id=g.revision_id AND c.generation_id=g.generation_id
JOIN cragkit.chunk_lexical l ON l.tenant_id=c.tenant_id AND l.collection_id=c.collection_id
 AND l.document_id=c.document_id AND l.revision_id=c.revision_id AND l.generation_id=c.generation_id AND l.chunk_id=c.chunk_id
WHERE d.tenant_id=$1 AND d.collection_id=$2 AND NOT d.tombstoned
 AND d.authorization_revision=$3 AND g.status='ready'
 AND EXISTS(SELECT 1 FROM cragkit.document_grants x WHERE x.tenant_id=d.tenant_id AND x.collection_id=d.collection_id
  AND x.document_id=d.document_id AND x.authorization_revision=$4
  AND (x.principal_id=$5 OR (x.principal_id IS NULL AND x.grant_id=ANY($6::text[]))))
 AND ({predicate}) AND l.identifier_tokens @> ARRAY[{identifier}]::cragkit.identity_text[]
ORDER BY d.document_id COLLATE pg_catalog."C",
 g.revision_id COLLATE pg_catalog."C",c.ordinal,c.chunk_id COLLATE pg_catalog."C"
LIMIT {limit}
`;
export const _DENSE_SQL = `
WITH query_vector AS (SELECT $1::cragkit_vector.vector(1536) AS embedding),
eligible AS MATERIALIZED (
 SELECT d.tenant_id,d.collection_id,d.document_id,g.revision_id,g.generation_id,c.chunk_id,
  c.start_byte,c.end_byte,c.text_sha256,c.ordinal,v.embedding,g.embedding_profile,g.lexical_profile
 FROM cragkit.documents d
 JOIN cragkit.index_generations g ON g.tenant_id=d.tenant_id AND g.collection_id=d.collection_id
  AND g.document_id=d.document_id AND g.generation_id=d.active_generation_id
 JOIN cragkit.chunks c ON c.tenant_id=g.tenant_id AND c.collection_id=g.collection_id
  AND c.document_id=g.document_id AND c.revision_id=g.revision_id AND c.generation_id=g.generation_id
 JOIN cragkit.chunk_vectors_fake_1536 v ON v.tenant_id=c.tenant_id AND v.collection_id=c.collection_id
  AND v.document_id=c.document_id AND v.revision_id=c.revision_id AND v.generation_id=c.generation_id
  AND v.chunk_id=c.chunk_id AND v.embedding_profile=g.embedding_profile
 WHERE v.embedding_profile=$2 AND d.tenant_id=$3 AND d.collection_id=$4 AND NOT d.tombstoned
  AND d.authorization_revision=$5 AND g.status='ready'
  AND EXISTS(SELECT 1 FROM cragkit.document_grants x WHERE x.tenant_id=d.tenant_id AND x.collection_id=d.collection_id
   AND x.document_id=d.document_id AND x.authorization_revision=$6
   AND (x.principal_id=$7 OR (x.principal_id IS NULL AND x.grant_id=ANY($8::text[]))))
  AND ({predicate})
)
SELECT e.tenant_id,e.collection_id,e.document_id,e.revision_id,e.generation_id,e.chunk_id,
 e.start_byte,e.end_byte,e.text_sha256,
 (e.embedding OPERATOR(cragkit_vector.<=>) q.embedding)::double precision AS distance,
 e.embedding_profile,e.lexical_profile
FROM eligible e CROSS JOIN query_vector q
ORDER BY distance ASC,e.document_id COLLATE pg_catalog."C",e.revision_id COLLATE pg_catalog."C",
 e.ordinal,e.chunk_id COLLATE pg_catalog."C"
LIMIT {limit}
`;
export const _SOURCE_SQL = `
SELECT c.tenant_id,c.collection_id,c.document_id,c.revision_id,c.generation_id,c.chunk_id,
 r.canonical_sha256,octet_length(r.canonical_text),
 CASE WHEN octet_length(r.canonical_text)<=$1 AND octet_length(r.canonical_text)<=16777216
      THEN r.canonical_text ELSE NULL END,
 c.start_byte,c.end_byte,octet_length(c.text),
 CASE WHEN octet_length(c.text)<=32768 THEN c.text ELSE NULL END,
 c.text_sha256,r.source_locator,g.lexical_profile,
 (d.active_generation_id IS NOT DISTINCT FROM g.generation_id)
FROM cragkit.documents d
JOIN cragkit.index_generations g ON g.tenant_id=d.tenant_id AND g.collection_id=d.collection_id
 AND g.document_id=d.document_id
JOIN cragkit.document_revisions r ON r.tenant_id=g.tenant_id AND r.collection_id=g.collection_id
 AND r.document_id=g.document_id AND r.revision_id=g.revision_id
JOIN cragkit.chunks c ON c.tenant_id=g.tenant_id AND c.collection_id=g.collection_id
 AND c.document_id=g.document_id AND c.revision_id=g.revision_id AND c.generation_id=g.generation_id
WHERE c.tenant_id=$2 AND c.collection_id=$3 AND c.document_id=$4 AND c.revision_id=$5
 AND c.generation_id=$6 AND c.chunk_id=$7
 AND d.tenant_id=$8 AND d.collection_id=$9 AND NOT d.tombstoned
 AND d.authorization_revision=$10 AND g.status='ready'
 AND EXISTS(SELECT 1 FROM cragkit.document_grants x WHERE x.tenant_id=d.tenant_id AND x.collection_id=d.collection_id
  AND x.document_id=d.document_id AND x.authorization_revision=$11
  AND (x.principal_id=$12 OR (x.principal_id IS NULL AND x.grant_id=ANY($13::text[]))))
 AND ({predicate})
`;
const CandidateSchema = z.strictObject({
  tenant_id: z.string(), collection: z.string(), document_id: z.string(), revision_id: z.string(),
  generation_id: z.string(), chunk_id: z.string(), start_byte: z.number().int().min(0).max(Number.MAX_SAFE_INTEGER),
  end_byte: z.number().int().positive().max(Number.MAX_SAFE_INTEGER), text_sha256: z.string().regex(/^[0-9a-f]{64}$/),
  score: z.number().finite().min(0),
});
export const DenseCandidateSchema = CandidateSchema.extend({
  score: z.number().finite().min(0).max(2),
  embedding_profile: z.literal('fake_embedding_1536_v1'),
  score_direction: z.literal('lower_is_better'), score_kind: z.literal('cosine_distance'),
});
export const IdentifierCandidateSchema = CandidateSchema.extend({
  score: z.literal(1), score_kind: z.literal('exact_identifier'),
  score_direction: z.literal('higher_is_better'), identifier_profile: z.literal('identifier_ascii_v1'),
});
export type IdentifierCandidate = Readonly<z.infer<typeof IdentifierCandidateSchema>>;
export type DenseCandidate = Readonly<z.infer<typeof DenseCandidateSchema>>;
const candidate_identity = (candidate: LexicalCandidate): boolean =>
  [candidate.tenant_id, candidate.collection, candidate.document_id, candidate.revision_id,
    candidate.generation_id, candidate.chunk_id].every(value => Buffer.byteLength(value) <= 256
      && /[^ \t\r\n\f\v]/.test(value) && !/[\0\uD800-\uDFFF]/u.test(value))
  && Buffer.byteLength(candidate.collection) <= 128 && candidate.end_byte > candidate.start_byte;
function dense_batch(input: unknown): EmbeddingBatch {
  try {
    if (!valid_native_json(input)) throw new InvalidRequest();
    const batch = z.strictObject({ profile: z.strictObject({ profile_id: z.string(), provider: z.string(),
      model: z.string(), dimensions: z.number().int().positive(), tokenizer: z.string(), normalization: z.string() }),
      vectors: z.array(z.array(z.number().finite())), usage: z.unknown(), provider_calls: z.literal(1), synthetic: z.boolean(),
    }).safeParse(input);
    if (!batch.success) throw new InvalidRequest();
    const parsed = EmbeddingBatchSchema.safeParse(batch.data);
    if (!parsed.success) throw new InvalidRequest();
    if (parsed.data.vectors.length !== 1 || parsed.data.synthetic !== (parsed.data.profile.provider === 'fake')) throw new InvalidRequest();
    if (!isDeepStrictEqual(parsed.data.profile, FAKE_PROFILE)) throw new EmbeddingProfileMismatch();
    if (parsed.data.vectors[0].length !== FAKE_PROFILE.dimensions) throw new EmbeddingProfileMismatch();
    const norm = Math.sqrt(parsed.data.vectors[0].reduce((sum, value) => sum + value * value, 0));
    if (!Number.isFinite(norm) || Math.abs(norm - 1) > 0.001) throw new InvalidRequest();
    return parsed.data;
  } catch (error) {
    if (error instanceof EmbeddingProfileMismatch) throw error;
    throw new InvalidRequest();
  }
}
export type LexicalCandidate = Readonly<z.infer<typeof CandidateSchema>>;
export function compile_filters(filters: RetrievalRequest['required_filters'], start = 1): readonly [string, readonly unknown[]] {
  const values: unknown[] = [];
  const visit = (item: RetrievalRequest['required_filters'][number]): string => {
    if (item.op === 'and' || item.op === 'or') return '(' + item.filters.map(visit).join(item.op === 'and' ? ' AND ' : ' OR ') + ')';
    if (item.op === 'not') return '(NOT ' + visit(item.filter) + ')';
    if (!('field' in item)) throw new UnsupportedCapability();
    const column = item.field === 'document_id' ? 'd.document_id' : item.field === 'revision_id' ? 'g.revision_id' : undefined;
    if (!column) throw new UnsupportedCapability();
    if (item.op === 'eq' || item.op === 'ne') {
      if (typeof item.value !== 'string') throw new UnsupportedCapability();
      if (item.value.includes('\0')) throw new InvalidRequest();
      values.push(item.value);
      return `(${column} ${item.op === 'eq' ? '=' : '<>'} $${start + values.length - 1})`;
    }
    if (item.op === 'in') {
      if (!item.values.every(value => typeof value === 'string')) throw new UnsupportedCapability();
      if (item.values.some(value => (value as string).includes('\0'))) throw new InvalidRequest();
      values.push([...item.values]);
      return `(${column} = ANY($${start + values.length - 1}::text[]))`;
    }
    throw new UnsupportedCapability();
  };
  return Object.freeze([`COALESCE((${filters.map(visit).join(' AND ') || 'TRUE'}), FALSE)`, Object.freeze(values)]);
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
async function query(client: PgClient, text: string, values: readonly unknown[] | undefined,
                     options: LeaseOptions): Promise<unknown[][]> {
  check_options(options);
  try {
    // Server statement limits complement the shared monotonic callback deadline.
    const timeout = Math.max(1, Math.floor(Math.min(options.deadline - now(), 2_147_483.647) * 1000));
    await bounded(client.query({ text: "SELECT set_config('statement_timeout',$1,true)", values: [String(timeout)], rowMode: 'array' }), options);
    const result = await bounded(client.query({ text, values, rowMode: 'array' }), options);
    check_options(options);
    if (!result || !Array.isArray(result.rows) || result.rows.some(row => !Array.isArray(row))) throw new UnsupportedCapability();
    return result.rows;
  } catch (error) { throw safe_error(error); }
}
async function validate(client: PgClient, options: LeaseOptions): Promise<void> {
  const role = await query(client, _ROLE_SQL, undefined, options);
  if (role.length !== 1 || role[0].length !== 1 || role[0][0] !== true) throw new UnauthorizedScope();
  const catalog = await query(client, _CATALOG_SQL, undefined, options);
  if (catalog.length !== 1 || catalog[0].length !== 1 || catalog[0][0] !== true) throw new UnsupportedCapability();
  const history = await query(client, _HISTORY_SQL, undefined, options);
  if (JSON.stringify(history) !== JSON.stringify(EXPECTED_HISTORY)) throw new UnsupportedCapability();
}
const context = new AsyncLocalStorage<symbol>();
export class ScopedSession {
  private active = true;
  private busy = false;
  constructor(private readonly client: PgClient, private readonly request: RetrievalRequest,
              private readonly scope: TrustedScope, private readonly options: LeaseOptions,
              private readonly predicate: string, private readonly parameters: readonly unknown[],
              private readonly token: symbol) {}
  invalidate(): void { this.active = false; }
  async visible_documents(options: { limit?: number } = {}): Promise<readonly (readonly [string, string])[]> {
    if (!this.active || this.busy || context.getStore() !== this.token) throw new InvalidRequest();
    if (!options || typeof options !== 'object') throw new InvalidRequest();
    const limit = options.limit === undefined ? 100 : options.limit;
    if (!Number.isInteger(limit) || limit < 1 || limit > 1000) throw new InvalidRequest();
    this.busy = true;
    try {
      const text = _DOCUMENT_SQL.replace('{predicate}', this.predicate).replace('{limit}', `$${7 + this.parameters.length}`);
      const rows = await query(this.client, text, [this.scope.tenant_id, this.request.collection,
        this.scope.authorization_revision, this.scope.authorization_revision, this.scope.principal_id,
        [...this.scope.grant_ids], ...this.parameters, Math.min(limit, this.request.limits.max_candidates)], this.options);
      if (rows.some(row => row.length !== 3 || typeof row[0] !== 'string' || typeof row[1] !== 'string' || row[2] !== 'native_fts.v1')) throw new UnsupportedCapability();
      return Object.freeze(rows.map(row => Object.freeze([row[0] as string, row[1] as string] as const)));
    } finally { this.busy = false; }
  }
  async fetch_evidence(input: LexicalCandidate | DenseCandidate | IdentifierCandidate, options: { max_source_bytes: number }): Promise<SourceFetch> {
    if (!this.active || this.busy || context.getStore() !== this.token) throw new InvalidRequest();
    if (!valid_native_json(input) || !valid_native_json(options)) throw new InvalidRequest();
    const budget = z.strictObject({ max_source_bytes: z.number().int().min(0).max(16777216) }).safeParse(options);
    if (!budget.success) throw new InvalidRequest();
    const maxSourceBytes = budget.data.max_source_bytes;
    const dense = input !== null && typeof input === 'object' && (Object.hasOwn(input, 'embedding_profile') || Object.hasOwn(input, 'score_direction') || Object.hasOwn(input, 'score_kind'));
    const identifier = input !== null && typeof input === 'object' && Object.hasOwn(input, 'identifier_profile');
    const validated = (identifier ? IdentifierCandidateSchema : dense ? DenseCandidateSchema : CandidateSchema).safeParse(input);
    const parsed = validated.success ? CandidateSchema.safeParse(Object.fromEntries(
      Object.keys(CandidateSchema.shape).map(key => [key, validated.data[key as keyof typeof validated.data]]))) : validated;
    const identityValues = parsed.success ? [parsed.data.tenant_id, parsed.data.collection, parsed.data.document_id, parsed.data.revision_id, parsed.data.generation_id, parsed.data.chunk_id] : [];
    if (!parsed.success || parsed.data.end_byte <= parsed.data.start_byte || identityValues.some(value => value.length > 256 || !/[^ \t\r\n\f\v]/.test(value) || value.includes('\0') || /[\uD800-\uDFFF]/u.test(value) || Buffer.byteLength(value) > 256)
      || (parsed.success && Buffer.byteLength(parsed.data.collection) > 128)
      || !options || !Number.isSafeInteger(options.max_source_bytes) || options.max_source_bytes < 0 || options.max_source_bytes > 16777216) throw new InvalidRequest();
    const candidate = Object.freeze(parsed.data);
    if (candidate.tenant_id !== this.scope.tenant_id || candidate.collection !== this.request.collection) throw new UnauthorizedScope();
    this.busy = true;
    try {
      const [predicate, parameters] = compile_filters(this.request.required_filters, 14);
      const rows = await query(this.client, _SOURCE_SQL.replace('{predicate}', predicate), [maxSourceBytes,
        candidate.tenant_id,candidate.collection,candidate.document_id,candidate.revision_id,candidate.generation_id,candidate.chunk_id,
        this.scope.tenant_id,this.request.collection,this.scope.authorization_revision,this.scope.authorization_revision,this.scope.principal_id,[...this.scope.grant_ids],...parameters],this.options);
      const result = verify_source(candidate, rows, maxSourceBytes);
      check_options(this.options);
      return result;
    } finally { this.busy = false; }
  }
  async identifier_candidates(input: string, options: { limit?: number } = {}): Promise<readonly IdentifierCandidate[]> {
    if (!this.active || this.busy || context.getStore() !== this.token) throw new InvalidRequest();
    const identifier = validate_identifier(input);
    if (!valid_native_json(options)) throw new InvalidRequest();
    const parsedOptions = z.strictObject({ limit: z.number().int().min(1).max(1000).default(100) }).safeParse(options);
    if (!parsedOptions.success) throw new InvalidRequest();
    const limit = Math.min(parsedOptions.data.limit, this.request.limits.max_candidates);
    this.busy = true;
    try {
      const [predicate, parameters] = compile_filters(this.request.required_filters, 7);
      const text = _IDENTIFIER_SQL.replace('{predicate}', predicate).replace('{identifier}', `$${7 + parameters.length}`).replace('{limit}', `$${8 + parameters.length}`);
      const rows = await query(this.client, text, [this.scope.tenant_id, this.request.collection,
        this.scope.authorization_revision, this.scope.authorization_revision, this.scope.principal_id,
        [...this.scope.grant_ids], ...parameters, identifier, limit], this.options);
      if (rows.length > limit) throw new IntegrityViolation();
      const seen = new Set<string>();
      const fields = Object.keys(CandidateSchema.shape);
      const result = rows.map(row => {
        if (row.length !== 12) throw new IntegrityViolation();
        if (row[10] !== 'native_fts.v1' || row[11] !== 'pg_catalog.simple') throw new UnsupportedCapability();
        const values = row.slice(0, 10);
        for (const index of [6, 7]) {
          const value = values[index];
          if (typeof value === 'string' && /^(0|[1-9][0-9]*)$/.test(value) && Number.isSafeInteger(Number(value))) values[index] = Number(value);
        }
        const parsed = IdentifierCandidateSchema.safeParse({ ...Object.fromEntries(fields.map((field, index) => [field, values[index]])),
          score_kind: 'exact_identifier', score_direction: 'higher_is_better', identifier_profile: 'identifier_ascii_v1' });
        if (!parsed.success || !candidate_identity(parsed.data) || parsed.data.tenant_id !== this.scope.tenant_id
          || parsed.data.collection !== this.request.collection) throw new IntegrityViolation();
        const identity = JSON.stringify(values.slice(0, 6));
        if (seen.has(identity)) throw new IntegrityViolation();
        seen.add(identity);
        return Object.freeze(parsed.data);
      });
      check_options(this.options);
      return Object.freeze(result);
    } finally { this.busy = false; }
  }
  async dense_candidates(input: EmbeddingBatch, options: { limit?: number } = {}): Promise<readonly DenseCandidate[]> {
    if (!this.active || this.busy || context.getStore() !== this.token) throw new InvalidRequest();
    const batch = dense_batch(input);
    if (!valid_native_json(options)) throw new InvalidRequest();
    const parsedOptions = z.strictObject({ limit: z.number().int().min(1).max(1000).default(100) }).safeParse(options);
    if (!parsedOptions.success) throw new InvalidRequest();
    const limit = Math.min(parsedOptions.data.limit, this.request.limits.max_candidates);
    const vector = JSON.stringify(batch.vectors[0]);
    check_options(this.options);
    this.busy = true;
    try {
      // This module imports session constants; defer it until after module initialization.
      const capability = await import('./vector-ingestion.js');
      check_options(this.options);
      if (!isDeepStrictEqual(await query(this.client, capability._VECTOR_CAPABILITY_SQL, undefined, this.options), [[true]])
        || !isDeepStrictEqual(await query(this.client, capability._SETUP_HISTORY_SQL, undefined, this.options), capability.EXPECTED_VECTOR_HISTORY)
        || !isDeepStrictEqual(await query(this.client, capability._PROFILE_SQL, undefined, this.options),
          [[...Object.values(FAKE_PROFILE), 'chunk_vectors_fake_1536']])) throw new UnsupportedCapability();
      const [predicate, parameters] = compile_filters(this.request.required_filters, 9);
      const text = _DENSE_SQL.replace('{predicate}', predicate).replace('{limit}', `$${9 + parameters.length}`);
      const rows = await query(this.client, text, [vector, FAKE_PROFILE.profile_id, this.scope.tenant_id,
        this.request.collection, this.scope.authorization_revision, this.scope.authorization_revision,
        this.scope.principal_id, [...this.scope.grant_ids], ...parameters, limit], this.options);
      if (rows.length > limit) throw new IntegrityViolation();
      const seen = new Set<string>();
      const fields = Object.keys(CandidateSchema.shape);
      const result = rows.map(row => {
        if (row.length !== 12) throw new IntegrityViolation();
        if (row[10] !== FAKE_PROFILE.profile_id || row[11] !== 'native_fts.v1') throw new UnsupportedCapability();
        const values = row.slice(0, 10);
        for (const index of [6, 7]) {
          const value = values[index];
          if (typeof value === 'string' && /^(0|[1-9][0-9]*)$/.test(value) && Number.isSafeInteger(Number(value))) values[index] = Number(value);
        }
        const parsed = DenseCandidateSchema.safeParse({ ...Object.fromEntries(fields.map((field, index) => [field, values[index]])),
          embedding_profile: row[10], score_direction: 'lower_is_better', score_kind: 'cosine_distance' });
        if (!parsed.success || !candidate_identity(parsed.data) || parsed.data.tenant_id !== this.scope.tenant_id
          || parsed.data.collection !== this.request.collection) throw new IntegrityViolation();
        const identity = JSON.stringify(values.slice(0, 6));
        if (seen.has(identity)) throw new IntegrityViolation();
        seen.add(identity);
        return Object.freeze(parsed.data);
      });
      check_options(this.options);
      return Object.freeze(result);
    } finally { this.busy = false; }
  }
  async lexical_candidates(options: { limit?: number } = {}): Promise<readonly LexicalCandidate[]> {
    if (!this.active || this.busy || context.getStore() !== this.token) throw new InvalidRequest();
    if (!options || typeof options !== 'object') throw new InvalidRequest();
    const limit = options.limit === undefined ? 100 : options.limit;
    if (!Number.isInteger(limit) || limit < 1 || limit > 1000) throw new InvalidRequest();
    this.busy = true;
    try {
      // The query parameter shifts identifier-filter placeholders by one.
      const [predicate, parameters] = compile_filters(this.request.required_filters, 8);
      const text = _LEXICAL_SQL.replace('{predicate}', predicate).replace('{limit}', `$${8 + parameters.length}`);
      const rows = await query(this.client, text, [this.request.query, this.scope.tenant_id, this.request.collection,
        this.scope.authorization_revision, this.scope.authorization_revision, this.scope.principal_id,
        [...this.scope.grant_ids], ...parameters, Math.min(limit, this.request.limits.max_candidates)], this.options);
      const fields = Object.keys(CandidateSchema.shape);
      return Object.freeze(rows.map(row => {
        if (row.length !== 12 || row[10] !== 'native_fts.v1' || row[11] !== 'pg_catalog.simple') throw new UnsupportedCapability();
        const values = row.slice(0, 10);
        // pg returns bigint/domain offsets as decimal strings. Convert only exact safe integers.
        for (const index of [6, 7]) {
          const value = values[index];
          if (typeof value === 'string' && /^(0|[1-9][0-9]*)$/.test(value)) values[index] = Number(value);
        }
        const parsed = CandidateSchema.safeParse(Object.fromEntries(fields.map((field, index) => [field, values[index]])));
        if (!parsed.success || parsed.data.tenant_id !== this.scope.tenant_id || parsed.data.collection !== this.request.collection
            || parsed.data.end_byte <= parsed.data.start_byte) throw new IntegrityViolation();
        return Object.freeze(parsed.data);
      }));
    } finally { this.busy = false; }
  }

}
export class PostgresSession {
  constructor(private readonly resource: PoolResource) {}
  private async run<T>(options: LeaseOptions, body: (client: PgClient, options: LeaseOptions) => Promise<T>): Promise<T> {
    check_options(options);
    return this.resource.withLease(options, async (client, signal) => {
      let status: string | null;
      try { status = client.getTransactionStatus(); } catch (error) { throw safe_error(error); }
      if (status !== 'I') throw new InvalidRequest();
      const requestOptions = { deadline: options.deadline, signal };
      let dispatched = false;
      let begun = false;
      let failed = false;
      let failure: unknown;
      let result!: T;
      try {
        dispatched = true;
        try {
          await bounded(client.query({ text: 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY', rowMode: 'array' }), requestOptions);
          begun = true;
          await bounded(client.query({ text: 'SET LOCAL search_path = pg_catalog', rowMode: 'array' }), requestOptions);
        } catch (error) { throw safe_error(error); }
        result = await body(client, requestOptions);
        check_options(requestOptions);
      } catch (error) { failed = true; failure = error; }
      finally {
        if (dispatched) {
          let clean = false;
          if (begun && !signal.aborted) {
            try {
              // Always rollback, even success. Never return an uncertain transaction.
              await bounded(client.query({ text: 'ROLLBACK', rowMode: 'array' }), { deadline: now() + this.resource.config.release_timeout });
              clean = client.getTransactionStatus() === 'I';
            } catch {}
          }
          if (!clean) {
            try { client.release(true); } catch {}
            if (!failed) { failed = true; failure = new ProviderUnavailable(); }
          }
        }
      }
      if (failed) throw failure;
      return result;
    });
  }
  async validate(options: LeaseOptions): Promise<void> {
    await this.run(options, async (client, scoped) => validate(client, scoped));
  }
  async transaction<T>(input: RetrievalRequest, options: LeaseOptions & { scope: TrustedScope },
                       body: (session: ScopedSession) => Promise<T>): Promise<T> {
    check_options(options);
    const request = parse_request(input);
    const scope = parse_scope(options.scope);
    if ([request.query, request.collection, scope.tenant_id, scope.principal_id,
         scope.authorization_revision, ...scope.grant_ids].some(value => value.includes('\0'))) throw new InvalidRequest();
    const [predicate, parameters] = compile_filters(request.required_filters, 7);
    const deadline = Math.min(options.deadline, now() + request.limits.deadline_ms / 1000);
    return this.run({ deadline, signal: options.signal }, async (client, scoped) => {
      await validate(client, scoped);
      await query(client, _SCOPE_SQL, [scope.tenant_id, scope.principal_id,
        scope.authorization_revision, JSON.stringify(scope.grant_ids)], scoped);
      const collection = await query(client, _COLLECTION_SQL, [scope.tenant_id, request.collection], scoped);
      if (collection.length !== 1 || collection[0].length !== 2 || collection[0][0] !== '0.1' || collection[0][1] !== 'native_fts.v1') throw new UnsupportedCapability();
      const token = Symbol('scoped-read');
      const handle = new ScopedSession(client, request, scope, scoped, predicate, parameters, token);
      const invalidate = (): void => handle.invalidate();
      scoped.signal?.addEventListener('abort', invalidate, { once: true });
      try { return await context.run(token, () => body(handle)); }
      finally { scoped.signal?.removeEventListener('abort', invalidate); handle.invalidate(); }
    });
  }
}
