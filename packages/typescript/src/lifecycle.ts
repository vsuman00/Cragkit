/** Explicit owner-authorized lifecycle; retention and external erasure remain caller policy. */
import { z } from 'zod';
import { PoolResource, bounded, check_options, type LeaseOptions } from './postgres-pool.js';
import { query, write_transaction, _WRITER_ROLE_SQL, _LOCK_SQL, _DOCUMENT_LOCK_SQL } from './ingestion.js';
import { EXPECTED_HISTORY, _CATALOG_SQL, _HISTORY_SQL, _SCOPE_SQL } from './postgres-session.js';
import { parse_scope, type TrustedScope } from './contracts.js';
import { InvalidRequest, UnauthorizedScope, IndexNotReady, IntegrityViolation, UnsupportedCapability } from './errors.js';

export type LifecycleReceipt = Readonly<{
  tenant_id: string; collection: string; document_id: string;
  state: 'tombstoned' | 'purged'; active_generation_id: string | null; changed: boolean;
}>;
export type LifecycleAuthorizer = (scope: TrustedScope, collection: string, document_id: string,
  operation: 'tombstone' | 'purge') => Promise<boolean>;
export type LifecycleOptions = LeaseOptions & Readonly<{
  collection: string; document_id: string; expected_generation_id: string | null; scope: TrustedScope;
}>;
const identity = (maximum: number) => z.string().refine(value => value.length <= maximum && !/[\uD800-\uDFFF\0]/u.test(value)
  && /[^ \t\r\n\f\v]/.test(value) && Buffer.byteLength(value) <= maximum);
const InputSchema = z.strictObject({
  collection: identity(128), document_id: identity(256), expected_generation_id: identity(256).nullable(),
});
export const _PURGER_ROLE_SQL = _WRITER_ROLE_SQL.replace(
  "OR has_table_privilege(current_user,c.oid,'DELETE')",
  "OR (c.relname <> 'documents' AND has_table_privilege(current_user,c.oid,'DELETE'))",
);
export const _PURGE_CATALOG_SQL = `
WITH known_vector_storage AS (
 SELECT c.relkind,c.relrowsecurity FROM pg_catalog.pg_class c
 JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='cragkit' AND c.relname='chunk_vectors_fake_1536'
), known_openai_vector_storage AS (
 SELECT c.relkind,c.relrowsecurity FROM pg_catalog.pg_class c
 JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='cragkit' AND c.relname='chunk_vectors_openai_te3small_1536'
), base_expected(child,parent,child_columns,parent_columns,delete_action) AS (VALUES
    ('document_revisions','documents',ARRAY['tenant_id','collection_id','document_id']::text[],ARRAY['tenant_id','collection_id','document_id']::text[],'c'),
    ('document_grants','documents',ARRAY['tenant_id','collection_id','document_id']::text[],ARRAY['tenant_id','collection_id','document_id']::text[],'c'),
    ('ingestion_jobs','documents',ARRAY['tenant_id','collection_id','document_id']::text[],ARRAY['tenant_id','collection_id','document_id']::text[],'c'),
    ('index_generations','document_revisions',ARRAY['tenant_id','collection_id','document_id','revision_id']::text[],ARRAY['tenant_id','collection_id','document_id','revision_id']::text[],'c'),
    ('chunks','index_generations',ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id']::text[],ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id']::text[],'c'),
    ('chunk_lexical','chunks',ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id']::text[],ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id']::text[],'c'),
    ('documents','index_generations',ARRAY['tenant_id','collection_id','document_id','active_generation_id']::text[],ARRAY['tenant_id','collection_id','document_id','generation_id']::text[],'a'),
    ('ingestion_jobs','index_generations',ARRAY['tenant_id','collection_id','document_id','generation_id']::text[],ARRAY['tenant_id','collection_id','document_id','generation_id']::text[],'a'),
    ('chunks','chunks',ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','parent_chunk_id']::text[],ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id']::text[],'a')
), expected AS (
 SELECT * FROM base_expected
 UNION ALL
 SELECT * FROM (VALUES
    ('chunk_vectors_fake_1536','chunks',ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id']::text[],ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id']::text[],'c'),
    ('chunk_vectors_fake_1536','index_generations',ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','embedding_profile']::text[],ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','embedding_profile']::text[],'c')
 ) optional(child,parent,child_columns,parent_columns,delete_action)
 WHERE EXISTS (SELECT 1 FROM known_vector_storage)
 UNION ALL
 SELECT * FROM (VALUES
    ('chunk_vectors_openai_te3small_1536','chunks',ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id']::text[],ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id']::text[],'c'),
    ('chunk_vectors_openai_te3small_1536','index_generations',ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','embedding_profile']::text[],ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','embedding_profile']::text[],'c')
 ) optional_openai(child,parent,child_columns,parent_columns,delete_action)
 WHERE EXISTS (SELECT 1 FROM known_openai_vector_storage)
), actual AS (
 SELECT c.oid,c.conrelid,c.confrelid,c.confdeltype::text AS delete_action,c.convalidated,
        child.relname::text AS child,parent.relname::text AS parent,
        ARRAY(SELECT a.attname::text FROM unnest(c.conkey) WITH ORDINALITY k(n,i)
              JOIN pg_catalog.pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.n ORDER BY k.i) AS child_columns,
        ARRAY(SELECT a.attname::text FROM unnest(c.confkey) WITH ORDINALITY k(n,i)
              JOIN pg_catalog.pg_attribute a ON a.attrelid=c.confrelid AND a.attnum=k.n ORDER BY k.i) AS parent_columns,
        child_ns.nspname::text AS child_schema
 FROM pg_catalog.pg_constraint c
 JOIN pg_catalog.pg_class child ON child.oid=c.conrelid
 JOIN pg_catalog.pg_namespace child_ns ON child_ns.oid=child.relnamespace
 JOIN pg_catalog.pg_class parent ON parent.oid=c.confrelid
 JOIN pg_catalog.pg_namespace parent_ns ON parent_ns.oid=parent.relnamespace
 WHERE c.contype='f' AND parent_ns.nspname='cragkit'
   AND (parent.relname IN ('documents','document_revisions','index_generations','chunks','chunk_vectors_fake_1536','document_grants','ingestion_jobs','chunk_lexical')
    OR parent.relname='chunk_vectors_openai_te3small_1536')
)
SELECT current_setting('session_replication_role')='origin'
 AND NOT EXISTS (SELECT 1 FROM known_openai_vector_storage WHERE relkind<>'r' OR NOT relrowsecurity)
 AND NOT EXISTS (SELECT 1 FROM known_vector_storage
  WHERE relkind<>'r' OR NOT relrowsecurity)
 AND (SELECT count(*) FROM actual)=(SELECT count(*) FROM expected)
 AND NOT EXISTS (
   SELECT 1 FROM expected e WHERE (SELECT count(*) FROM actual a
     WHERE a.child_schema='cragkit' AND a.child=e.child AND a.parent=e.parent
       AND a.child_columns=e.child_columns AND a.parent_columns=e.parent_columns
       AND a.delete_action=e.delete_action AND a.convalidated)<>1)
 AND NOT EXISTS (
   SELECT 1 FROM actual a WHERE
     (SELECT count(*) FROM pg_catalog.pg_trigger t WHERE t.tgconstraint=a.oid AND t.tgisinternal)=4
       IS NOT TRUE
     OR EXISTS (SELECT 1 FROM pg_catalog.pg_trigger t WHERE t.tgconstraint=a.oid
                AND (NOT t.tgisinternal OR t.tgenabled NOT IN ('O','A'))))
`;
export const _TOMBSTONE_SQL = `
UPDATE cragkit.documents SET tombstoned=true
WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3
 AND authorization_revision=$4 AND NOT tombstoned
 AND active_generation_id IS NOT DISTINCT FROM $5::text
RETURNING 1
`;
export const _PURGE_SQL = `
DELETE FROM cragkit.documents
WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3
 AND authorization_revision=$4 AND tombstoned
 AND active_generation_id IS NOT DISTINCT FROM $5::text
RETURNING created_at::text
`;
export const _MARKER_SQL = `
INSERT INTO cragkit.documents
(tenant_id,collection_id,document_id,authorization_revision,tombstoned,active_generation_id,metadata,created_at)
VALUES($1,$2,$3,$4,true,NULL,'{}'::jsonb,$5::timestamptz)
RETURNING 1
`;
const equal = (actual: unknown, expected: unknown): boolean => JSON.stringify(actual) === JSON.stringify(expected);
export class PostgresLifecycle {
  constructor(private readonly resource: PoolResource, private readonly authorize_lifecycle: LifecycleAuthorizer) {
    if (typeof authorize_lifecycle !== 'function') throw new InvalidRequest();
  }
  tombstone(input: LifecycleOptions): Promise<LifecycleReceipt> {
    return this.mutate(input, 'tombstone');
  }
  purge_tombstoned(input: LifecycleOptions): Promise<LifecycleReceipt> {
    return this.mutate(input, 'purge');
  }
  private async mutate(input: LifecycleOptions, operation: 'tombstone' | 'purge'): Promise<LifecycleReceipt> {
    let values: z.infer<typeof InputSchema>;
    let scope: TrustedScope;
    let options: LeaseOptions;
    try {
      if (!input || typeof input !== 'object' || ![Object.prototype, null].includes(Object.getPrototypeOf(input))) throw new InvalidRequest();
      const descriptors = Object.getOwnPropertyDescriptors(input);
      if (Object.values(descriptors).some(descriptor => !('value' in descriptor) || !descriptor.enumerable)) throw new InvalidRequest();
      if (Reflect.ownKeys(input).some(key => typeof key !== 'string'
          || !['collection','document_id','expected_generation_id','scope','deadline','signal'].includes(key))) throw new InvalidRequest();
      values = InputSchema.parse({ collection: input.collection, document_id: input.document_id,
        expected_generation_id: input.expected_generation_id });
      scope = parse_scope(input.scope);
      if ([scope.tenant_id,scope.principal_id,scope.authorization_revision,...scope.grant_ids].some(value => !identity(256).safeParse(value).success)) throw new InvalidRequest();
      options = { deadline: input.deadline, signal: input.signal };
    } catch { throw new InvalidRequest(); }
    check_options(options);
    const allowed = await bounded(Promise.resolve().then(() => this.authorize_lifecycle(scope,
      values.collection,values.document_id,operation)), options);
    check_options(options);
    if (allowed !== true) throw new UnauthorizedScope();
    return write_transaction(this.resource,options,async (client, transactionOptions) => {
      const q = (sql: string, parameters?: readonly unknown[]) => query(client,sql,parameters,transactionOptions);
      const roleSQL = operation === 'purge' ? _PURGER_ROLE_SQL : _WRITER_ROLE_SQL;
      if (!equal(await q(roleSQL),[[true]])) throw new UnauthorizedScope();
      if (!equal(await q(_CATALOG_SQL),[[true]])) throw new UnsupportedCapability();
      if (!equal(await q(_HISTORY_SQL),EXPECTED_HISTORY)) throw new UnsupportedCapability();
      if (operation === 'purge' && !equal(await q(_PURGE_CATALOG_SQL),[[true]])) throw new UnsupportedCapability();
      await q(_SCOPE_SQL,[scope.tenant_id,scope.principal_id,scope.authorization_revision,JSON.stringify(scope.grant_ids)]);
      const key = [scope.tenant_id,values.collection,values.document_id];
      await q(_LOCK_SQL,[JSON.stringify(['cragkit.document.v1',...key])]);
      const rows = await q(_DOCUMENT_LOCK_SQL,key);
      if (!rows.length) throw new UnauthorizedScope();
      if (rows.length !== 1 || rows[0].length !== 3 || typeof rows[0][1] !== 'boolean'
          || typeof rows[0][2] !== 'string' || (rows[0][0] !== null && !identity(256).safeParse(rows[0][0]).success)) throw new IntegrityViolation();
      const [active,tombstoned,authorization] = rows[0];
      if (!identity(256).safeParse(authorization).success) throw new IntegrityViolation();
      if (authorization !== scope.authorization_revision) throw new UnauthorizedScope();
      if (active !== values.expected_generation_id) throw new IndexNotReady();
      const predicates = [...key,scope.authorization_revision,values.expected_generation_id];
      let changed = true;
      if (operation === 'tombstone') {
        if (tombstoned) changed = false;
        else if (!equal(await q(_TOMBSTONE_SQL,predicates),[[1]])) throw new IntegrityViolation();
      } else {
        if (!tombstoned) throw new InvalidRequest();
        const deleted = await q(_PURGE_SQL,predicates);
        if (deleted.length !== 1 || deleted[0].length !== 1 || !identity(128).safeParse(deleted[0][0]).success) throw new IntegrityViolation();
        if (!equal(await q(_MARKER_SQL,[...key,scope.authorization_revision,deleted[0][0]]),[[1]])) throw new IntegrityViolation();
      }
      check_options(transactionOptions);
      return Object.freeze({tenant_id:scope.tenant_id,collection:values.collection,document_id:values.document_id,
        state:operation === 'purge' ? 'purged' : 'tombstoned',active_generation_id:operation === 'purge' ? null : active as string | null,changed});
    });
  }
}
