"""Bounded read-only PostgreSQL authority, independent of the reference store."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import math
from typing import Any, AsyncIterator, cast

from ._postgres_pool import PoolResource
from ._postgres_session import SessionConnection
from ._qdrant_contract import QdrantConfig
from ._qdrant_source import SOURCE_ROW_FIELDS
from ._qdrant_transport import deadline_value
from .contracts import RetrievalRequest, TrustedScope
from .errors import (CragkitError, DeadlineExceeded, IntegrityViolation, InvalidRequest,
                     ProviderUnavailable, UnauthorizedScope, UnsupportedCapability)

EXPECTED_HISTORY = (('0001_authority','3d75cd46eb32a10864f1097a7494b01f9759150911a7cd9a1e6aab60105c1f1a'),)
EXPECTED_PUBLICATION_HISTORY = EXPECTED_HISTORY + (
    ('0002_publication', '386fe01d0d03e35ac35c21bce598b21bff2c5ad510e9cdf0a6fbe56f359b6661'),
)
_TABLES = ('documents','document_revisions','generations','members','schema_migrations')
_ROLE_SQL = """
SELECT current_user=session_user
 AND EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolcanlogin)
 AND NOT EXISTS(SELECT 1 FROM pg_roles r WHERE pg_has_role(current_user,r.oid,'MEMBER') AND
   (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication OR
    r.rolname IN ('pg_read_all_data','pg_write_all_data','pg_read_server_files','pg_write_server_files','pg_execute_server_program',
                 'cragkit_qdrant_writer','cragkit_qdrant_supervisor')))
 AND EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='cragkit_qdrant' AND has_schema_privilege(current_user,oid,'USAGE'))
 AND NOT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='cragkit_qdrant' AND
   (pg_has_role(current_user,nspowner,'MEMBER') OR has_schema_privilege(current_user,oid,'CREATE')))
 AND NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='cragkit_qdrant' AND c.relkind IN ('r','p') AND
   (pg_has_role(current_user,c.relowner,'MEMBER')
    OR (c.relname IN ('documents','document_revisions','generations','members','schema_migrations')
        AND NOT has_table_privilege(current_user,c.oid,'SELECT'))
    OR (c.relname NOT IN ('documents','document_revisions','generations','members','schema_migrations')
        AND (has_table_privilege(current_user,c.oid,'SELECT') OR has_any_column_privilege(current_user,c.oid,'SELECT')))
    OR (c.relname<>'schema_migrations' AND NOT row_security_active(c.oid))
    OR has_table_privilege(current_user,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
    OR has_any_column_privilege(current_user,c.oid,'INSERT,UPDATE,REFERENCES')))
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname='cragkit_qdrant' AND pg_has_role(current_user,p.proowner,'MEMBER'))
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname='cragkit_qdrant' AND has_function_privilege(current_user,p.oid,'EXECUTE')
    AND p.oid IS DISTINCT FROM to_regprocedure('cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean)')
    AND p.oid IS DISTINCT FROM to_regprocedure('cragkit_qdrant.scope_grants()')
    AND p.oid IS DISTINCT FROM to_regprocedure('cragkit_qdrant.valid_identity_array(text[])'))
 AND NOT EXISTS(SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
   WHERE n.nspname='cragkit_qdrant' AND pg_has_role(current_user,t.typowner,'MEMBER'))
 AND has_function_privilege(current_user,'cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean)','EXECUTE')
 AND has_function_privilege(current_user,'cragkit_qdrant.scope_grants()','EXECUTE')
 AND has_function_privilege(current_user,'cragkit_qdrant.valid_identity_array(text[])','EXECUTE')
"""
_COLUMNS = {
 'schema_migrations':'version:identity_text checksum_sha256:sha256_hex applied_at:timestamptz',
 'documents':'tenant_id:identity_text collection:collection_text document_id:identity_text active_generation_id:identity_text principal_ids:_text grant_ids:_text authorization_revision:identity_text mutation_epoch:safe_count language:text kind:text tag:text tombstoned:bool created_at:timestamptz',
 'document_revisions':'tenant_id:identity_text collection:collection_text document_id:identity_text revision_id:identity_text canonical_utf8:bytea source_sha256:sha256_hex source_locator:text parser_id:identity_text created_at:timestamptz',
 'generations':'tenant_id:identity_text collection:collection_text document_id:identity_text revision_id:identity_text generation_id:identity_text backend_namespace:identity_text physical_collection:text collection_incarnation:identity_text chunker_profile:identity_text dense_profile_id:identity_text sparse_profile_id:text dense_profile:jsonb sparse_profile:jsonb expected_member_count:int4 published:bool ever_published:bool created_at:timestamptz',
 'members':'tenant_id:identity_text collection:collection_text document_id:identity_text revision_id:identity_text generation_id:identity_text chunk_id:identity_text point_id:uuid start_byte:safe_count end_byte:safe_count source_sha256:sha256_hex text_sha256:sha256_hex excerpt_utf8:bytea',
}
_COLUMN_VALUES = ','.join("('%s','%s','%s')" % (table, *pair.split(':'))
                          for table, columns in _COLUMNS.items() for pair in columns.split())
_CATALOG_SQL = """
SELECT current_setting('server_version_num')::int BETWEEN 170000 AND 179999
 AND current_setting('server_encoding')='UTF8'
 AND to_regprocedure('cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean)') IS NOT NULL
 AND to_regprocedure('cragkit_qdrant.scope_grants()') IS NOT NULL
 AND to_regprocedure('cragkit_qdrant.valid_identity_array(text[])') IS NOT NULL
 AND (SELECT count(*)=5 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='cragkit_qdrant' AND c.relkind='r')
 AND NOT EXISTS(SELECT 1 FROM (VALUES """ + _COLUMN_VALUES + """) expected(tbl,col,typ)
   LEFT JOIN pg_namespace n ON n.nspname='cragkit_qdrant'
   LEFT JOIN pg_class c ON c.relnamespace=n.oid AND c.relname=expected.tbl
   LEFT JOIN pg_attribute a ON a.attrelid=c.oid AND a.attname=expected.col AND a.attnum>0 AND NOT a.attisdropped
   LEFT JOIN pg_type t ON t.oid=a.atttypid WHERE t.typname IS DISTINCT FROM expected.typ)
 AND (SELECT count(*)=4 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='cragkit_qdrant' AND c.relname IN ('documents','document_revisions','generations','members')
      AND c.relrowsecurity AND c.relforcerowsecurity)
 AND (SELECT count(*)=4 FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='cragkit_qdrant' AND p.polcmd='r' AND p.polpermissive AND p.polroles=ARRAY[0::oid])
 AND NOT EXISTS(SELECT 1 FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='cragkit_qdrant' AND (p.polcmd<>'r' OR NOT p.polpermissive OR p.polwithcheck IS NOT NULL))
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
      WHERE n.nspname='cragkit_qdrant' AND p.prosecdef)
 AND NOT EXISTS(SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace
      WHERE n.nspname='cragkit_qdrant' AND NOT x.convalidated)
 AND (SELECT count(*)=5 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='cragkit_qdrant' AND NOT t.tgisinternal AND t.tgenabled='O')
"""
_CATALOG_FINGERPRINT_SQL = "-- QS-r1 PostgreSQL 17 catalog signature. Execute with search_path=pg_catalog.\n-- Runtime role/ownership/permissions are checked separately. This signature\n-- excludes physical OIDs, owners, timestamps and named runtime grants.\nWITH catalog AS (\nSELECT jsonb_build_object(\n 'namespace_public', (SELECT COALESCE(jsonb_agg(jsonb_build_array(x.privilege_type,x.is_grantable) ORDER BY x.privilege_type,x.is_grantable),'[]'::jsonb)\n   FROM pg_namespace n CROSS JOIN LATERAL aclexplode(COALESCE(n.nspacl,acldefault('n',n.nspowner))) x\n   WHERE n.nspname='cragkit_qdrant' AND x.grantee=0),\n 'relations', (SELECT COALESCE(jsonb_agg(jsonb_build_array(c.relname,c.relkind,c.relpersistence,c.relrowsecurity,c.relforcerowsecurity,c.reloptions,\n   (SELECT COALESCE(jsonb_agg(jsonb_build_array(x.privilege_type,x.is_grantable) ORDER BY x.privilege_type,x.is_grantable),'[]'::jsonb)\n    FROM aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) x WHERE x.grantee=0)) ORDER BY c.relname),'[]'::jsonb)\n   FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant'),\n 'columns', (SELECT COALESCE(jsonb_agg(jsonb_build_array(c.relname,a.attnum,a.attname,format_type(a.atttypid,a.atttypmod),\n   a.attnotnull,a.attidentity,a.attgenerated,a.attisdropped,cn.nspname,co.collname,pg_get_expr(d.adbin,d.adrelid),\n   (SELECT COALESCE(jsonb_agg(jsonb_build_array(x.privilege_type,x.is_grantable) ORDER BY x.privilege_type,x.is_grantable),'[]'::jsonb)\n    FROM aclexplode(a.attacl) x WHERE x.grantee=0)) ORDER BY c.relname,a.attnum),'[]'::jsonb)\n   FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid\n   LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum LEFT JOIN pg_collation co ON co.oid=a.attcollation\n   LEFT JOIN pg_namespace cn ON cn.oid=co.collnamespace WHERE n.nspname='cragkit_qdrant' AND a.attnum>0 AND c.relkind IN ('r','p','v','m','f')),\n 'types', (SELECT COALESCE(jsonb_agg(jsonb_build_array(t.typname,t.typtype,t.typcategory,\n   CASE WHEN t.typbasetype=0 THEN NULL ELSE format_type(t.typbasetype,t.typtypmod) END,t.typnotnull,\n   cn.nspname,co.collname,t.typdefault,\n   (SELECT COALESCE(jsonb_agg(jsonb_build_array(x.privilege_type,x.is_grantable) ORDER BY x.privilege_type,x.is_grantable),'[]'::jsonb)\n    FROM aclexplode(COALESCE(t.typacl,acldefault('T',t.typowner))) x WHERE x.grantee=0)) ORDER BY t.typname),'[]'::jsonb)\n   FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace LEFT JOIN pg_collation co ON co.oid=t.typcollation\n   LEFT JOIN pg_namespace cn ON cn.oid=co.collnamespace WHERE n.nspname='cragkit_qdrant'),\n 'constraints', (SELECT COALESCE(jsonb_agg(jsonb_build_array(cl.relname,ty.typname,k.conname,k.contype,k.convalidated,k.condeferrable,k.condeferred,\n   pg_get_constraintdef(k.oid,true)) ORDER BY cl.relname NULLS FIRST,ty.typname NULLS FIRST,k.conname),'[]'::jsonb)\n   FROM pg_constraint k JOIN pg_namespace n ON n.oid=k.connamespace LEFT JOIN pg_class cl ON cl.oid=k.conrelid\n   LEFT JOIN pg_type ty ON ty.oid=k.contypid WHERE n.nspname='cragkit_qdrant'),\n 'indexes', (SELECT COALESCE(jsonb_agg(jsonb_build_array(c.relname,i.indisvalid,i.indisready,pg_get_indexdef(i.indexrelid)) ORDER BY c.relname),'[]'::jsonb)\n   FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant'),\n 'triggers', (SELECT COALESCE(jsonb_agg(jsonb_build_array(c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid,true)) ORDER BY c.relname,t.tgname),'[]'::jsonb)\n   FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND NOT t.tgisinternal),\n 'policies', (SELECT COALESCE(jsonb_agg(jsonb_build_array(c.relname,p.polname,p.polcmd,p.polpermissive,\n   (SELECT jsonb_agg(role_name ORDER BY role_name) FROM (SELECT CASE WHEN role_id=0 THEN 'PUBLIC' ELSE (SELECT rolname::text FROM pg_roles WHERE oid=role_id) END AS role_name FROM unnest(p.polroles) role_id) named_roles),pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid)) ORDER BY c.relname,p.polname),'[]'::jsonb)\n   FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant'),\n 'functions', (SELECT COALESCE(jsonb_agg(jsonb_build_array(p.proname,pg_get_function_identity_arguments(p.oid),p.prokind,\n   p.prosecdef,p.proleakproof,p.provolatile,p.proparallel,p.proisstrict,p.proconfig,CASE WHEN p.prokind='a' THEN NULL ELSE pg_get_functiondef(p.oid) END,\n   (SELECT COALESCE(jsonb_agg(jsonb_build_array(x.privilege_type,x.is_grantable) ORDER BY x.privilege_type,x.is_grantable),'[]'::jsonb)\n    FROM aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) x WHERE x.grantee=0)) ORDER BY p.proname,pg_get_function_identity_arguments(p.oid)),'[]'::jsonb)\n   FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='cragkit_qdrant')\n) AS payload\n)\nSELECT encode(sha256(convert_to(payload::text,'UTF8')),'hex') AS schema_fingerprint FROM catalog;\n"
EXPECTED_CATALOG_FINGERPRINT = '8104abeef00594e7bfa4b533a139767599b56b87d09062c0d6f52f6e2f5d0b48'
EXPECTED_PUBLICATION_CATALOG_FINGERPRINT = 'e395925257def30b9d143b7210c68583d4cbbb0950d8a8e1bb4f5aba5b8be69b'
_PUBLICATION_CATALOG_SQL = """
SELECT current_setting('server_version_num')::int BETWEEN 170000 AND 179999
 AND current_setting('server_encoding')='UTF8'
 AND (SELECT count(*)=13 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='cragkit_qdrant' AND c.relkind='r')
 AND (SELECT count(*)=12 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND c.relname<>'schema_migrations'
      AND c.relrowsecurity AND c.relforcerowsecurity)
 AND NOT EXISTS(SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace
      WHERE n.nspname='cragkit_qdrant' AND NOT x.convalidated)
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
      WHERE n.nspname='cragkit_qdrant' AND p.prosecdef)
 AND NOT EXISTS(SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
      JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant'
      AND t.tgenabled<>'O')
"""
_HISTORY_SQL = 'SELECT version, checksum_sha256 FROM cragkit_qdrant.schema_migrations ORDER BY version LIMIT 3'
_SCOPE_SQL = """SELECT set_config('cragkit_qdrant.tenant_id',%s,true),
 set_config('cragkit_qdrant.collection',%s,true),set_config('cragkit_qdrant.principal_id',%s,true),
 set_config('cragkit_qdrant.grant_ids',%s,true),set_config('cragkit_qdrant.authorization_revision',%s,true)"""


def compile_filters(request: RetrievalRequest) -> tuple[str, tuple[object, ...]]:
    params: list[object] = []
    def visit(node: dict[str, Any]) -> str:
        op = node['op']
        if op in ('and','or'):
            return '(' + (' AND ' if op == 'and' else ' OR ').join(visit(child) for child in node['filters']) + ')'
        field = ('g.revision_id' if node['field'] == 'revision_id' else 'd.' + node['field'])
        if op == 'eq' and type(node['value']) is str:
            params.append(node['value'])
            return field + ' = %s'
        if op == 'in' and all(type(item) is str for item in node['values']):
            params.append(node['values'])
            return field + ' = ANY(%s::text[])'
        raise UnsupportedCapability()
    predicates = [visit(node) for node in request.model_dump(mode='json')['required_filters']]
    return ' AND '.join(predicates) or 'TRUE', tuple(params)


_SELECTION = """
m.point_id::text,g.backend_namespace,g.physical_collection,g.collection_incarnation,
m.tenant_id,m.collection,m.document_id,m.revision_id,m.generation_id,m.chunk_id,m.start_byte,m.end_byte,
m.source_sha256,m.text_sha256,g.dense_profile_id,g.sparse_profile_id,g.dense_profile,g.sparse_profile,
d.authorization_revision,d.mutation_epoch,d.principal_ids,d.grant_ids,d.language,d.kind,d.tag,
r.source_locator,r.parser_id,g.chunker_profile,octet_length(r.canonical_utf8),
CASE WHEN octet_length(r.canonical_utf8)<=%s AND octet_length(r.canonical_utf8)<=16777216 THEN r.canonical_utf8 ELSE NULL END,
octet_length(m.excerpt_utf8),
CASE WHEN octet_length(r.canonical_utf8)<=%s AND octet_length(r.canonical_utf8)<=16777216
 AND octet_length(m.excerpt_utf8)<=32768 THEN m.excerpt_utf8 ELSE NULL END,
d.active_generation_id,g.published,g.ever_published,d.tombstoned
"""
_SOURCE_SQL = """SELECT """ + _SELECTION + """
FROM cragkit_qdrant.documents d JOIN cragkit_qdrant.generations g
 ON g.tenant_id=d.tenant_id AND g.collection=d.collection AND g.document_id=d.document_id
JOIN cragkit_qdrant.document_revisions r ON r.tenant_id=g.tenant_id AND r.collection=g.collection
 AND r.document_id=g.document_id AND r.revision_id=g.revision_id
JOIN cragkit_qdrant.members m ON m.tenant_id=g.tenant_id AND m.collection=g.collection
 AND m.document_id=g.document_id AND m.revision_id=g.revision_id AND m.generation_id=g.generation_id
WHERE m.tenant_id=%s AND m.collection=%s AND m.document_id=%s AND m.revision_id=%s AND m.generation_id=%s AND m.chunk_id=%s
 AND g.backend_namespace=%s AND g.physical_collection=%s AND g.collection_incarnation=%s
 AND d.tenant_id=%s AND d.collection=%s AND d.authorization_revision=%s AND NOT d.tombstoned
 AND (%s=ANY(d.principal_ids) OR d.grant_ids && %s::text[])
 AND g.ever_published AND ({publication}) AND ({predicate}) LIMIT 2
"""


async def query(connection: SessionConnection, sql: str, params: tuple[object, ...] | None,
                deadline: float) -> list[tuple[object, ...]]:
    remaining = deadline_value(deadline) - asyncio.get_running_loop().time()
    try:
        milliseconds = max(1, math.floor(min(remaining, 2147483.647) * 1000))
        await connection.execute("SELECT set_config('statement_timeout',%s,true)", (str(milliseconds),))
        cursor = await connection.execute(sql, params)
        rows = await cursor.fetchall()
        deadline_value(deadline)
        if type(rows) is not list or any(type(row) is not tuple for row in rows):
            raise IntegrityViolation()
        return rows
    except asyncio.CancelledError:
        raise
    except CragkitError as error:
        for kind in (DeadlineExceeded, IntegrityViolation, InvalidRequest, UnauthorizedScope, UnsupportedCapability):
            if type(error) is kind:
                raise kind() from None
        raise ProviderUnavailable() from None
    except Exception as error:
        try:
            code = getattr(error, 'sqlstate', None)
        except Exception:
            code = None
        if type(code) is str and code in ('42P01', '42703', '42883'):
            raise UnsupportedCapability() from None
        raise (DeadlineExceeded() if code == '57014' and asyncio.get_running_loop().time() >= deadline else ProviderUnavailable()) from None


class PostgresQdrantAuthority:
    def __init__(self, resource: PoolResource) -> None:
        self.resource = resource

    @asynccontextmanager
    async def transaction(self, deadline: float) -> AsyncIterator[SessionConnection]:
        deadline_value(deadline)
        async with self.resource.lease(deadline=deadline) as leased:
            connection = cast(SessionConnection, leased)
            transaction = None
            failure: BaseException | None = None
            begun = False
            try:
                if connection.info.transaction_status != 0:
                    raise ProviderUnavailable()
                transaction = connection.transaction(force_rollback=True)
                async with asyncio.timeout_at(deadline):
                    await transaction.__aenter__()
                    begun = True
                    await connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                    await connection.execute('SET LOCAL search_path = pg_catalog')
                    yield connection
                    deadline_value(deadline)
            except asyncio.CancelledError as error:
                failure = error
            except TimeoutError:
                failure = DeadlineExceeded()
            except CragkitError as error:
                failure = error
            except Exception:
                failure = ProviderUnavailable()
            finally:
                async def cleanup() -> bool:
                    try:
                        async with asyncio.timeout(self.resource.config.release_timeout):
                            if transaction is not None and begun:
                                await transaction.__aexit__(None, None, None)
                                if connection.info.transaction_status == 0:
                                    return True
                    except Exception:
                        pass
                    try:
                        async with asyncio.timeout(self.resource.config.release_timeout):
                            await connection.close()
                    except Exception:
                        pass
                    return False
                task = asyncio.create_task(cleanup())
                try:
                    clean = await asyncio.shield(task)
                except asyncio.CancelledError:
                    await asyncio.shield(task)
                    raise
                if not clean and failure is None:
                    failure = ProviderUnavailable()
            if failure is not None:
                raise failure from None

    async def initialize(self, *, deadline: float) -> None:
        async with self.transaction(deadline) as connection:
            try:
                rows = await query(connection, _HISTORY_SQL, None, deadline)
            except IntegrityViolation:
                raise UnsupportedCapability() from None
            if len(rows) not in (1, 2) or any(len(row) != 2 or any(type(value) is not str for value in row)
                                             for row in rows):
                raise UnsupportedCapability()
            history = tuple(rows)
            if history == EXPECTED_HISTORY:
                catalog_sql, fingerprint = _CATALOG_SQL, EXPECTED_CATALOG_FINGERPRINT
            elif history == EXPECTED_PUBLICATION_HISTORY:
                catalog_sql, fingerprint = _PUBLICATION_CATALOG_SQL, EXPECTED_PUBLICATION_CATALOG_FINGERPRINT
            else:
                raise UnsupportedCapability()
            if await query(connection, catalog_sql, None, deadline) != [(True,)]:
                raise UnsupportedCapability()
            if await query(connection, _ROLE_SQL, None, deadline) != [(True,)]:
                raise UnauthorizedScope()
            if await query(connection, _CATALOG_FINGERPRINT_SQL, None, deadline) != [(fingerprint,)]:
                raise UnsupportedCapability()

    async def read(self, nomination: Any, request: RetrievalRequest, scope: TrustedScope, config: QdrantConfig, *,
                   retained: bool, max_source_bytes: int, deadline: float) -> list[dict[str, Any]]:
        predicate, parameters = compile_filters(request)
        payload = nomination.payload
        args = (max_source_bytes,max_source_bytes,payload.tenant_id,payload.collection,payload.document_id,payload.revision_id,
                payload.generation_id,payload.chunk_id,config.backend_namespace,config.physical_collection,config.collection_incarnation,
                scope.tenant_id,request.collection,scope.authorization_revision,scope.principal_id,list(scope.grant_ids),*parameters)
        grants = json.dumps(list(scope.grant_ids), ensure_ascii=False, separators=(',', ':'))
        if len(grants.encode()) > 131072:
            raise InvalidRequest()
        async with self.transaction(deadline) as connection:
            if await query(connection, _ROLE_SQL, None, deadline) != [(True,)]:
                raise UnauthorizedScope()
            await query(connection, _SCOPE_SQL, (scope.tenant_id,request.collection,scope.principal_id,grants,scope.authorization_revision), deadline)
            rows = await query(connection, _SOURCE_SQL.format(publication='TRUE' if retained else 'g.published AND d.active_generation_id=g.generation_id', predicate=predicate), args, deadline)
            if len(rows) > 1 or any(len(row) != len(SOURCE_ROW_FIELDS) for row in rows):
                raise IntegrityViolation()
            return [dict(zip(SOURCE_ROW_FIELDS, row)) for row in rows]
