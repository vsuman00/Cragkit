/** Closed PGO-r1 storage selection. No constructor or import performs database work. */
import { deep_freeze } from './shared.js';
import { isDeepStrictEqual } from 'node:util';
import { EmbeddingProfileSchema, FAKE_PROFILE, OPENAI_PROFILE, type EmbeddingProfile } from './embeddings.js';
import { EmbeddingProfileMismatch, UnsupportedCapability } from './errors.js';

export const LEGACY_VECTOR_HISTORY = deep_freeze([
  ['0001_pgvector','b98de4a67f46ab7cc7187447757b30844ceee01901a88186746ae322cf1a7e2c'],
  ['0002_vector_profiles','33fda8141215cbdb961165822a13bc74639c97c41985529ce1b1b3ae585140fb'],
] as const);
export const OPENAI_VECTOR_HISTORY = deep_freeze([...LEGACY_VECTOR_HISTORY,
  ['0003_openai_te3small_1536','9f909b14e690112fbc4c8671f7e758e839e615e68aad33f927b400ea04eb9f16']] as const);
export const SETUP_HISTORY_SQL = 'SELECT version,checksum FROM cragkit_vector.setup_history ORDER BY version';
export const PROFILE_REGISTRY_SQL = 'SELECT profile_id,provider,model,dimensions,tokenizer,normalization,storage_table FROM cragkit.embedding_profiles ORDER BY profile_id';
export function snapshot_profile(profile: EmbeddingProfile = FAKE_PROFILE): EmbeddingProfile {
  const parsed = EmbeddingProfileSchema.safeParse(profile);
  if (!parsed.success) throw new EmbeddingProfileMismatch();
  return parsed.data;
}
export function profile_table(profile: EmbeddingProfile): 'chunk_vectors_fake_1536'|'chunk_vectors_openai_te3small_1536' {
  const selected=snapshot_profile(profile);
  return selected.provider==='fake' ? 'chunk_vectors_fake_1536' : 'chunk_vectors_openai_te3small_1536';
}
export function profile_sql(text: string, profile: EmbeddingProfile): string {
  return text.replaceAll('chunk_vectors_fake_1536',profile_table(profile));
}
export const PROFILE_ROWS = deep_freeze([
  [...Object.values(FAKE_PROFILE),'chunk_vectors_fake_1536'],
  [...Object.values(OPENAI_PROFILE),'chunk_vectors_openai_te3small_1536'],
] as const);
const VECTOR_TABLE_GUARD_TEMPLATE="SELECT\n EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace\n  WHERE n.nspname='cragkit' AND c.relname='__VECTOR_TABLE__'\n   AND c.relkind='r' AND c.relrowsecurity AND row_security_active(c.oid)\n   AND NOT pg_has_role(current_user,c.relowner,'MEMBER'))\n AND (SELECT count(*) FROM pg_attribute a WHERE a.attrelid=to_regclass('cragkit.__VECTOR_TABLE__')\n  AND a.attnum>0 AND NOT a.attisdropped)=8\n AND NOT EXISTS(SELECT 1 FROM (VALUES\n  ('tenant_id','cragkit.identity_text'),('collection_id','cragkit.collection_text'),\n  ('document_id','cragkit.identity_text'),('revision_id','cragkit.identity_text'),\n  ('generation_id','cragkit.identity_text'),('chunk_id','cragkit.identity_text'),\n  ('embedding_profile','cragkit.identity_text'),('embedding','cragkit_vector.vector')) expected(name,typ)\n  LEFT JOIN pg_attribute a ON a.attrelid=to_regclass('cragkit.__VECTOR_TABLE__')\n   AND a.attname=expected.name AND a.attnum>0 AND NOT a.attisdropped\n  WHERE a.atttypid IS DISTINCT FROM to_regtype(expected.typ) OR NOT coalesce(a.attnotnull,false)\n   OR (expected.name='embedding' AND a.atttypmod IS DISTINCT FROM 1536))\n AND (SELECT count(*) FROM pg_constraint WHERE conrelid=to_regclass('cragkit.__VECTOR_TABLE__'))=6\n AND NOT EXISTS(SELECT 1 FROM pg_constraint c WHERE c.conrelid=to_regclass('cragkit.__VECTOR_TABLE__')\n  AND (NOT c.convalidated OR c.condeferrable OR c.condeferred))\n AND NOT EXISTS(SELECT 1 FROM pg_trigger t WHERE t.tgrelid=to_regclass('cragkit.__VECTOR_TABLE__')\n  AND t.tgenabled NOT IN ('O','A'))\n AND NOT EXISTS(SELECT 1 FROM pg_class c, LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a\n  WHERE c.oid=to_regclass('cragkit.__VECTOR_TABLE__') AND a.grantee=0)\n AND NOT EXISTS(SELECT 1 FROM (VALUES ('f','FOREIGN KEY (tenant_id, collection_id, document_id, revision_id, generation_id, embedding_profile) REFERENCES cragkit.index_generations(tenant_id, collection_id, document_id, revision_id, generation_id, embedding_profile) ON DELETE CASCADE'),('c','CHECK (abs(cragkit_vector.vector_norm(embedding) - 1.0::double precision) <= 0.001::double precision)'),('c','CHECK (embedding_profile::text = ''__PROFILE_ID__''::text)'),('f','FOREIGN KEY (embedding_profile) REFERENCES cragkit.embedding_profiles(profile_id)'),('p','PRIMARY KEY (tenant_id, collection_id, document_id, revision_id, generation_id, chunk_id)'),('f','FOREIGN KEY (tenant_id, collection_id, document_id, revision_id, generation_id, chunk_id) REFERENCES cragkit.chunks(tenant_id, collection_id, document_id, revision_id, generation_id, chunk_id) ON DELETE CASCADE')) expected(kind,definition)\n  WHERE (SELECT count(*) FROM pg_constraint c\n   WHERE c.conrelid=to_regclass('cragkit.__VECTOR_TABLE__')\n    AND c.contype::text=expected.kind AND pg_get_constraintdef(c.oid,true)=expected.definition\n    AND c.convalidated AND NOT c.condeferrable AND NOT c.condeferred)<>1)\n AND NOT EXISTS(SELECT 1 FROM pg_constraint c WHERE c.conrelid=to_regclass('cragkit.__VECTOR_TABLE__')\n  AND c.contype='f' AND ((SELECT count(*) FROM pg_trigger t WHERE t.tgconstraint=c.oid AND t.tgisinternal)<>4\n   OR EXISTS(SELECT 1 FROM pg_trigger t WHERE t.tgconstraint=c.oid AND (NOT t.tgisinternal OR t.tgenabled NOT IN ('O','A')))))\n";
const REGISTRY_GUARD_SQL=" AND (SELECT count(*) FROM pg_constraint c WHERE c.conrelid=to_regclass('cragkit.embedding_profiles')\n  AND c.contype='c')=1\n AND EXISTS(SELECT 1 FROM pg_constraint c WHERE c.conrelid=to_regclass('cragkit.embedding_profiles')\n  AND c.contype='c' AND c.convalidated AND pg_get_constraintdef(c.oid,true)='CHECK (profile_id::text = ''fake_embedding_1536_v1''::text AND provider::text = ''fake''::text AND model::text = ''fake_embedding_model_v1''::text AND dimensions = 1536 AND tokenizer::text = ''fake-byte-v1''::text AND normalization::text = ''l2''::text AND storage_table::text = ''chunk_vectors_fake_1536''::text OR profile_id::text = ''openai_te3small_1536_r1''::text AND provider::text = ''openai''::text AND model::text = ''text-embedding-3-small''::text AND dimensions = 1536 AND tokenizer::text = ''cl100k_base''::text AND normalization::text = ''l2''::text AND storage_table::text = ''chunk_vectors_openai_te3small_1536''::text)')\n AND EXISTS(SELECT 1 FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid\n  JOIN pg_namespace n ON n.oid=p.pronamespace\n  WHERE t.tgrelid=to_regclass('cragkit.embedding_profiles') AND t.tgname='immutable_embedding_profile'\n   AND t.tgenabled IN ('O','A') AND NOT t.tgisinternal AND t.tgtype=27\n   AND n.nspname='cragkit' AND p.proname='reject_embedding_profile_change' AND NOT p.prosecdef)\n AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace\n  WHERE n.nspname IN ('cragkit','cragkit_vector') AND p.prosecdef)\n";
function vector_table_guard(profile:EmbeddingProfile):string {
  return VECTOR_TABLE_GUARD_TEMPLATE.replaceAll("__VECTOR_TABLE__",profile_table(profile)).replaceAll("__PROFILE_ID__",snapshot_profile(profile).profile_id);
}
export const OPENAI_TABLE_SQL="SELECT ("+vector_table_guard(OPENAI_PROFILE).replace(/^SELECT/,"")+") AND ("+vector_table_guard(FAKE_PROFILE).replace(/^SELECT/,"")+")"+REGISTRY_GUARD_SQL;
type Query = (text:string, values?:readonly unknown[])=>Promise<unknown[][]>;
export async function validate_profile_storage(query:Query,profile:EmbeddingProfile,capability_sql:string,write=false):Promise<void> {
  if (!isDeepStrictEqual(await query(capability_sql),[[true]])) throw new UnsupportedCapability();
  const history=await query(SETUP_HISTORY_SQL);
  const legacy=isDeepStrictEqual(history,LEGACY_VECTOR_HISTORY);
  const upgraded=isDeepStrictEqual(history,OPENAI_VECTOR_HISTORY);
  if ((!legacy && !upgraded) || legacy && profile.provider!=='fake') throw new UnsupportedCapability();
  if (!isDeepStrictEqual(await query(PROFILE_REGISTRY_SQL),legacy ? [PROFILE_ROWS[0]] : PROFILE_ROWS)) throw new UnsupportedCapability();
  if (upgraded && !isDeepStrictEqual(await query(OPENAI_TABLE_SQL),[[true]])) throw new UnsupportedCapability();
  if (upgraded) {
    const table='cragkit.'+profile_table(profile);
    const privileges=write?['SELECT','INSERT','UPDATE']:['SELECT'];
    const sql='SELECT '+privileges.map(privilege=>`has_table_privilege(current_user,'${table}','${privilege}')`).join(' AND ');
    if (!isDeepStrictEqual(await query(sql),[[true]])) throw new UnsupportedCapability();
  }
}
