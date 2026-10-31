"""Closed native PostgreSQL embedding profiles and immutable storage admission."""
from types import MappingProxyType
from typing import Awaitable, Callable

from .embeddings import EmbeddingProfile, FAKE_PROFILE, OPENAI_PROFILE
from .errors import EmbeddingProfileMismatch, InvalidRequest, UnsupportedCapability

LEGACY_VECTOR_HISTORY = (
    ('0001_pgvector', 'b98de4a67f46ab7cc7187447757b30844ceee01901a88186746ae322cf1a7e2c'),
    ('0002_vector_profiles', '33fda8141215cbdb961165822a13bc74639c97c41985529ce1b1b3ae585140fb'),
)
OPENAI_VECTOR_HISTORY = (*LEGACY_VECTOR_HISTORY,
    ('0003_openai_te3small_1536', '9f909b14e690112fbc4c8671f7e758e839e615e68aad33f927b400ea04eb9f16'))
_TABLES = MappingProxyType({FAKE_PROFILE.profile_id: 'chunk_vectors_fake_1536',
                          OPENAI_PROFILE.profile_id: 'chunk_vectors_openai_te3small_1536'})
SETUP_HISTORY_SQL = 'SELECT version,checksum FROM cragkit_vector.setup_history ORDER BY version'
PROFILE_SQL = 'SELECT profile_id,provider,model,dimensions,tokenizer,normalization,storage_table FROM cragkit.embedding_profiles ORDER BY profile_id'


def snapshot_profile(profile: EmbeddingProfile = FAKE_PROFILE) -> EmbeddingProfile:
    try:
        if type(profile) is not EmbeddingProfile:
            raise ValueError()
        checked = EmbeddingProfile.model_validate(profile.model_dump())
    except Exception:
        raise InvalidRequest() from None
    if checked not in (FAKE_PROFILE, OPENAI_PROFILE):
        raise EmbeddingProfileMismatch()
    return checked


def profile_table(profile: EmbeddingProfile) -> str:
    return _TABLES[snapshot_profile(profile).profile_id]


def profile_rows(upgraded: bool) -> list[tuple[object, ...]]:
    return [(*profile.model_dump().values(), profile_table(profile))
            for profile in ((FAKE_PROFILE, OPENAI_PROFILE) if upgraded else (FAKE_PROFILE,))]


# Definitions are frozen from the PGO-r1 PostgreSQL 17.11 catalog fixture.
# Compare semantics/validation rather than PostgreSQL-truncated constraint names.
_VECTOR_TABLE_GUARD_TEMPLATE = """SELECT
 EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='cragkit' AND c.relname='__VECTOR_TABLE__'
   AND c.relkind='r' AND c.relrowsecurity AND row_security_active(c.oid)
   AND NOT pg_has_role(current_user,c.relowner,'MEMBER'))
 AND (SELECT count(*) FROM pg_attribute a WHERE a.attrelid=to_regclass('cragkit.__VECTOR_TABLE__')
  AND a.attnum>0 AND NOT a.attisdropped)=8
 AND NOT EXISTS(SELECT 1 FROM (VALUES
  ('tenant_id','cragkit.identity_text'),('collection_id','cragkit.collection_text'),
  ('document_id','cragkit.identity_text'),('revision_id','cragkit.identity_text'),
  ('generation_id','cragkit.identity_text'),('chunk_id','cragkit.identity_text'),
  ('embedding_profile','cragkit.identity_text'),('embedding','cragkit_vector.vector')) expected(name,typ)
  LEFT JOIN pg_attribute a ON a.attrelid=to_regclass('cragkit.__VECTOR_TABLE__')
   AND a.attname=expected.name AND a.attnum>0 AND NOT a.attisdropped
  WHERE a.atttypid IS DISTINCT FROM to_regtype(expected.typ) OR NOT coalesce(a.attnotnull,false)
   OR (expected.name='embedding' AND a.atttypmod IS DISTINCT FROM 1536))
 AND (SELECT count(*) FROM pg_constraint WHERE conrelid=to_regclass('cragkit.__VECTOR_TABLE__'))=6
 AND NOT EXISTS(SELECT 1 FROM pg_constraint c WHERE c.conrelid=to_regclass('cragkit.__VECTOR_TABLE__')
  AND (NOT c.convalidated OR c.condeferrable OR c.condeferred))
 AND NOT EXISTS(SELECT 1 FROM pg_trigger t WHERE t.tgrelid=to_regclass('cragkit.__VECTOR_TABLE__')
  AND t.tgenabled NOT IN ('O','A'))
 AND NOT EXISTS(SELECT 1 FROM pg_class c, LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
  WHERE c.oid=to_regclass('cragkit.__VECTOR_TABLE__') AND a.grantee=0)
 AND NOT EXISTS(SELECT 1 FROM (VALUES ('f','FOREIGN KEY (tenant_id, collection_id, document_id, revision_id, generation_id, embedding_profile) REFERENCES cragkit.index_generations(tenant_id, collection_id, document_id, revision_id, generation_id, embedding_profile) ON DELETE CASCADE'),('c','CHECK (abs(cragkit_vector.vector_norm(embedding) - 1.0::double precision) <= 0.001::double precision)'),('c','CHECK (embedding_profile::text = ''__PROFILE_ID__''::text)'),('f','FOREIGN KEY (embedding_profile) REFERENCES cragkit.embedding_profiles(profile_id)'),('p','PRIMARY KEY (tenant_id, collection_id, document_id, revision_id, generation_id, chunk_id)'),('f','FOREIGN KEY (tenant_id, collection_id, document_id, revision_id, generation_id, chunk_id) REFERENCES cragkit.chunks(tenant_id, collection_id, document_id, revision_id, generation_id, chunk_id) ON DELETE CASCADE')) expected(kind,definition)
  WHERE (SELECT count(*) FROM pg_constraint c
   WHERE c.conrelid=to_regclass('cragkit.__VECTOR_TABLE__')
    AND c.contype::text=expected.kind AND pg_get_constraintdef(c.oid,true)=expected.definition
    AND c.convalidated AND NOT c.condeferrable AND NOT c.condeferred)<>1)
 AND NOT EXISTS(SELECT 1 FROM pg_constraint c WHERE c.conrelid=to_regclass('cragkit.__VECTOR_TABLE__')
  AND c.contype='f' AND ((SELECT count(*) FROM pg_trigger t WHERE t.tgconstraint=c.oid AND t.tgisinternal)<>4
   OR EXISTS(SELECT 1 FROM pg_trigger t WHERE t.tgconstraint=c.oid AND (NOT t.tgisinternal OR t.tgenabled NOT IN ('O','A')))))
"""

_REGISTRY_GUARD_SQL = """ AND (SELECT count(*) FROM pg_constraint c WHERE c.conrelid=to_regclass('cragkit.embedding_profiles')
  AND c.contype='c')=1
 AND EXISTS(SELECT 1 FROM pg_constraint c WHERE c.conrelid=to_regclass('cragkit.embedding_profiles')
  AND c.contype='c' AND c.convalidated AND pg_get_constraintdef(c.oid,true)='CHECK (profile_id::text = ''fake_embedding_1536_v1''::text AND provider::text = ''fake''::text AND model::text = ''fake_embedding_model_v1''::text AND dimensions = 1536 AND tokenizer::text = ''fake-byte-v1''::text AND normalization::text = ''l2''::text AND storage_table::text = ''chunk_vectors_fake_1536''::text OR profile_id::text = ''openai_te3small_1536_r1''::text AND provider::text = ''openai''::text AND model::text = ''text-embedding-3-small''::text AND dimensions = 1536 AND tokenizer::text = ''cl100k_base''::text AND normalization::text = ''l2''::text AND storage_table::text = ''chunk_vectors_openai_te3small_1536''::text)')
 AND EXISTS(SELECT 1 FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid
  JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE t.tgrelid=to_regclass('cragkit.embedding_profiles') AND t.tgname='immutable_embedding_profile'
   AND t.tgenabled IN ('O','A') AND NOT t.tgisinternal AND t.tgtype=27
   AND n.nspname='cragkit' AND p.proname='reject_embedding_profile_change' AND NOT p.prosecdef)
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname IN ('cragkit','cragkit_vector') AND p.prosecdef)
"""


def _vector_table_guard(profile: EmbeddingProfile) -> str:
    """Render only the two trusted table/profile identities from the closed map."""
    return _VECTOR_TABLE_GUARD_TEMPLATE.replace(
        "__VECTOR_TABLE__", profile_table(profile)).replace("__PROFILE_ID__", profile.profile_id)


# Either selected profile requires the complete upgraded pair to remain valid.
OPENAI_TABLE_SQL = ("SELECT (" + _vector_table_guard(OPENAI_PROFILE).removeprefix("SELECT")
                    + ") AND (" + _vector_table_guard(FAKE_PROFILE).removeprefix("SELECT")
                    + ")" + _REGISTRY_GUARD_SQL)


def _selected_privilege_sql(profile: EmbeddingProfile, *, write: bool = False) -> str:
    table = 'cragkit.' + profile_table(profile)
    query = f"SELECT has_table_privilege(current_user,'{table}','SELECT')"
    if write:
        query += f" AND has_table_privilege(current_user,'{table}','INSERT')"
        query += f" AND has_table_privilege(current_user,'{table}','UPDATE')"
    return query


async def validate_profile_storage(query: Callable[[str], Awaitable[list[tuple[object, ...]]]],
                                   profile: EmbeddingProfile, capability_sql: str, *, write: bool = False) -> None:
    if await query(capability_sql) != [(True,)]:
        raise UnsupportedCapability()
    history = tuple(await query(SETUP_HISTORY_SQL))
    if history not in (LEGACY_VECTOR_HISTORY, OPENAI_VECTOR_HISTORY):
        raise UnsupportedCapability()
    upgraded = history == OPENAI_VECTOR_HISTORY
    if profile == OPENAI_PROFILE and not upgraded:
        raise UnsupportedCapability()
    if await query(PROFILE_SQL) != profile_rows(upgraded):
        raise UnsupportedCapability()
    if upgraded:
        if await query(OPENAI_TABLE_SQL) != [(True,)]:
            raise UnsupportedCapability()
        if await query(_selected_privilege_sql(profile, write=write)) != [(True,)]:
            raise UnsupportedCapability()
