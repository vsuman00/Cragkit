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
EXPECTED_ATTESTATION_HISTORY = (*EXPECTED_PUBLICATION_HISTORY,
    ('0003_preparation_attestations', '8c6791cd0fd65ff09758c068ebc90a895a4ac21d9713512486d3daf9cb7c8433'))
EXPECTED_ATTESTATION_CATALOG_FINGERPRINT = '7ffd3b585b1fe32bc3476a3dc4390b022f5dcfd6c5ed186c9964fec4ffd72848'
EXPECTED_ATTESTATION_FINGERPRINT = EXPECTED_ATTESTATION_CATALOG_FINGERPRINT
_ATTESTATION_CATALOG_SQL = _PUBLICATION_CATALOG_SQL.replace('count(*)=13', 'count(*)=14').replace('count(*)=12', 'count(*)=13')
EXPECTED_SECURITY_GUARD_HISTORY = (*EXPECTED_ATTESTATION_HISTORY,
    ('0004_security_settlement_guard', '44b666cb47f3bb51ac8c5f6eb05fe8aea9138a9c603ab2fa427bdd807255be0b'))
EXPECTED_SECURITY_GUARD_CATALOG_FINGERPRINT = '352cf043dc8c19f700b8e2e9b4776dede7dd0402b2db79f7d79668cab115d8a3'
_SECURITY_GUARD_SIGNATURE = 'cragkit_qdrant.lock_current_security(text,text,text,text,text,bigint,text,text,text,text,uuid,text,text,text,text,bigint,text[],text[],text,text,text,boolean)'
# The complete fingerprint pins the function body; this separate structural
# predicate admits only the one deliberately privileged routine.
_SECURITY_GUARD_CATALOG_SQL = _ATTESTATION_CATALOG_SQL.replace(
    "WHERE n.nspname='cragkit_qdrant' AND p.prosecdef)",
    "WHERE n.nspname='cragkit_qdrant' AND p.prosecdef AND p.oid IS DISTINCT FROM "
    "to_regprocedure('" + _SECURITY_GUARD_SIGNATURE + "'))") + """
 AND (SELECT count(*)=1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
      WHERE n.nspname='cragkit_qdrant' AND p.prosecdef)
 AND EXISTS(SELECT 1 FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
      WHERE p.oid=to_regprocedure('""" + _SECURITY_GUARD_SIGNATURE + """')
      AND p.prokind='f' AND p.prorettype='void'::regtype AND l.lanname='plpgsql'
      AND p.prosecdef AND NOT p.proleakproof AND NOT p.proisstrict
      AND p.provolatile='v' AND p.proparallel='u'
      AND p.proconfig=ARRAY['search_path=pg_catalog','row_security=on'])
"""
_SECURITY_GUARD_OWNER_SQL = """WITH guard_profile AS (
 SELECT (SELECT oid FROM pg_catalog.pg_roles WHERE rolname='cragkit_qdrant_security_guard') AS guard_id,
 (SELECT oid FROM pg_catalog.pg_roles WHERE rolname='cragkit_qdrant_supervisor') AS supervisor_role_id,
 (SELECT nspowner FROM pg_catalog.pg_namespace WHERE nspname='cragkit_qdrant') AS operator_id,
 pg_catalog.to_regprocedure('cragkit_qdrant.lock_current_security(text,text,text,text,text,bigint,text,text,text,text,uuid,text,text,text,text,bigint,text[],text[],text,text,text,boolean)') AS function_id
)
SELECT guard_id IS NOT NULL AND supervisor_role_id IS NOT NULL AND operator_id IS NOT NULL AND function_id IS NOT NULL
 AND EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE oid=operator_id AND rolcanlogin AND rolcreaterole AND NOT rolsuper AND NOT rolbypassrls)
 AND pg_catalog.has_schema_privilege(supervisor_role_id,'cragkit_qdrant','USAGE')
 AND NOT pg_catalog.has_schema_privilege(supervisor_role_id,'cragkit_qdrant','CREATE')
 AND NOT (NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE oid=guard_id AND NOT
           (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication OR rolinherit))
       OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE oid=supervisor_role_id AND NOT
           (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication OR rolinherit))
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members WHERE member IN (guard_id,supervisor_role_id))
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspowner=supervisor_role_id)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_class WHERE relowner=supervisor_role_id)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc WHERE proowner=supervisor_role_id)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_type WHERE typowner=supervisor_role_id)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_database WHERE datdba=supervisor_role_id)
       OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE oid=operator_id AND rolcreaterole AND NOT rolsuper AND NOT rolbypassrls)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.roleid=guard_id AND NOT
           (m.member=operator_id AND NOT m.inherit_option AND
             ((m.grantor=10 AND m.admin_option AND NOT m.set_option)
              OR (m.grantor=operator_id AND NOT m.admin_option AND m.set_option))))
       OR (SELECT count(*) FROM pg_catalog.pg_auth_members WHERE roleid=guard_id)<>2
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_roles r WHERE NOT r.rolsuper AND
           (pg_catalog.pg_has_role(r.oid,supervisor_role_id,'MEMBER') OR pg_catalog.pg_has_role(r.oid,'cragkit_qdrant_writer','MEMBER'))
           AND pg_catalog.pg_has_role(r.oid,operator_id,'MEMBER'))
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspowner=guard_id)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND c.relowner<>operator_id)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_class WHERE relowner=guard_id)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_type WHERE typowner=guard_id)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_database WHERE datdba=guard_id)
       OR (SELECT count(*) FROM pg_catalog.pg_proc WHERE proowner=guard_id)<>1
       OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_proc WHERE oid=function_id AND proowner=guard_id AND prosecdef
           AND provolatile='v' AND proparallel='u' AND NOT proisstrict AND NOT proleakproof
           AND proconfig=ARRAY['search_path=pg_catalog','row_security=on']::text[])
       OR pg_catalog.has_schema_privilege(guard_id,'cragkit_qdrant','CREATE')
       OR NOT pg_catalog.has_schema_privilege(guard_id,'cragkit_qdrant','USAGE')
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND c.relname<>'schema_migrations'
             AND NOT(c.relrowsecurity AND c.relforcerowsecurity))
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
           WHERE n.nspname='cragkit_qdrant' AND p.prosecdef AND p.oid<>function_id)
       OR (SELECT count(*) FROM pg_catalog.pg_policy WHERE guard_id=ANY(polroles))<>7
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_policy WHERE guard_id=ANY(polroles) AND
          (polroles<>ARRAY[guard_id]::oid[] OR NOT polpermissive OR polqual IS NULL
           OR polname NOT IN ('security_guard_backend_select','security_guard_backend_update','security_guard_owner_select',
                             'security_guard_owner_update','security_guard_document_select','security_guard_document_update','security_guard_intent_select')
           OR polcmd NOT IN ('r','w') OR (polcmd='w' AND pg_catalog.pg_get_expr(polwithcheck,polrelid) IS DISTINCT FROM 'false'))))
 AND NOT (EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN pg_catalog.unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) privilege
        WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND pg_catalog.has_table_privilege(guard_id,c.oid,privilege))
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN pg_catalog.unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) privilege
        WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
        AND pg_catalog.has_column_privilege(guard_id,c.oid,a.attnum,privilege) IS DISTINCT FROM CASE
          WHEN privilege='SELECT' THEN
            (c.relname='backend_instances' AND a.attname IN ('instance_id','backend_namespace','storage_identity','supervisor_id','epoch','state','recovery_id'))
            OR (c.relname='document_owners' AND a.attname IN ('tenant_id','collection','document_id','instance_id','intent_id','owner_token','backend_epoch'))
            OR (c.relname='documents' AND a.attname IN ('tenant_id','collection','document_id','active_generation_id','authorization_revision','mutation_epoch','principal_ids','grant_ids','language','kind','tag','tombstoned'))
            OR (c.relname='publication_intents' AND a.attname IN ('tenant_id','collection','document_id','intent_id','instance_id','action','payload_sha256','expected_mutation_epoch','authority_committed'))
          WHEN privilege='UPDATE' THEN (c.relname='backend_instances' AND a.attname='epoch')
            OR (c.relname='document_owners' AND a.attname='backend_epoch') OR (c.relname='documents' AND a.attname='mutation_epoch')
          ELSE false END)
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname='cragkit_qdrant' AND pg_catalog.has_function_privilege(guard_id,p.oid,'EXECUTE') IS DISTINCT FROM
            (p.oid=function_id OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean)')
             OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.scope_grants()')
             OR p.oid=pg_catalog.to_regprocedure('cragkit_qdrant.valid_identity_array(text[])')))
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p CROSS JOIN LATERAL pg_catalog.aclexplode(p.proacl) a
          WHERE p.oid=function_id AND (a.grantee NOT IN (guard_id,supervisor_role_id) OR a.grantor<>guard_id
            OR a.privilege_type<>'EXECUTE' OR (a.grantee=supervisor_role_id AND a.is_grantable)))
       OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p CROSS JOIN LATERAL pg_catalog.aclexplode(p.proacl) a
          WHERE p.oid=function_id AND a.grantee=supervisor_role_id AND a.privilege_type='EXECUTE' AND NOT a.is_grantable))
FROM guard_profile"""

EXPECTED_PURGE_HISTORY = (*EXPECTED_SECURITY_GUARD_HISTORY,
    ('0005_security_owners_and_erasure', 'ff368df59dc3e6bea2d5a032c915c625427cc74f103924bc8a4a31f5f2b26e68'))
EXPECTED_PURGE_CATALOG_FINGERPRINT = 'ca83de1388d892be58ccf6a49acf1a8afcdccd66c3f30b87d57bd457fe76f5d8'
EXPECTED_PURGE_CAPABILITY_FINGERPRINT = '80210922ed1130d45762383222affbf0147c679f5a23e9b2ed20ac079f33c817'
_PURGE_SIGNATURE = 'cragkit_qdrant.erase_purged_document(text,text,text,text,bigint,text,text,text,text,text,text,text,uuid,text,text,bigint,bytea,text,text,text)'
_PURGE_CATALOG_SQL = _SECURITY_GUARD_CATALOG_SQL.replace('count(*)=14 FROM pg_class', 'count(*)=15 FROM pg_class').replace(
    'count(*)=13 FROM pg_class', 'count(*)=14 FROM pg_class').replace(
    "p.prosecdef AND p.oid IS DISTINCT FROM to_regprocedure('" + _SECURITY_GUARD_SIGNATURE + "'))",
    "p.prosecdef AND p.oid NOT IN (to_regprocedure('" + _SECURITY_GUARD_SIGNATURE + "'),to_regprocedure('" + _PURGE_SIGNATURE + "')))").replace(
    'count(*)=1 FROM pg_proc', 'count(*)=2 FROM pg_proc') + """
 AND EXISTS(SELECT 1 FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
      WHERE p.oid=to_regprocedure('""" + _PURGE_SIGNATURE + """')
      AND p.prokind='f' AND p.prorettype='boolean'::regtype AND l.lanname='plpgsql'
      AND p.prosecdef AND NOT p.proleakproof AND NOT p.proisstrict
      AND p.provolatile='v' AND p.proparallel='u'
      AND p.proconfig=ARRAY['search_path=pg_catalog','row_security=on'])
"""
_PURGE_OWNER_SQL = _SECURITY_GUARD_OWNER_SQL.replace(
    "WHERE n.nspname='cragkit_qdrant' AND p.prosecdef AND p.oid<>function_id)",
    "WHERE n.nspname='cragkit_qdrant' AND p.prosecdef AND p.oid NOT IN (function_id,pg_catalog.to_regprocedure('" + _PURGE_SIGNATURE + "')))")
_PURGE_CAPABILITY_FINGERPRINT_SQL = "-- QP-r1 capability inventory. Normalize only installation-specific operator\n-- and bootstrap names; preserve every effective privilege and membership edge.\nWITH operators AS (\n SELECT nspowner AS operator_id FROM pg_catalog.pg_namespace WHERE nspname='cragkit_qdrant'\n), names AS (\n SELECT r.oid, CASE WHEN r.oid=o.operator_id THEN pg_catalog.jsonb_build_array('operator')\n                   WHEN r.oid=10 THEN pg_catalog.jsonb_build_array('bootstrap')\n                   ELSE pg_catalog.jsonb_build_array('role',r.rolname) END AS name\n FROM pg_catalog.pg_roles r CROSS JOIN operators o\n UNION ALL SELECT 0::oid,pg_catalog.jsonb_build_array('public')\n), capabilities AS (\n SELECT * FROM pg_catalog.pg_roles\n WHERE rolname IN ('cragkit_qdrant_security_guard','cragkit_qdrant_purger')\n), inventory AS (\n SELECT pg_catalog.jsonb_build_object(\n  'roles',(SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(rolname,\n    rolcanlogin,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication,rolinherit,\n    pg_catalog.has_schema_privilege(oid,'cragkit_qdrant','USAGE'),\n    pg_catalog.has_schema_privilege(oid,'cragkit_qdrant','CREATE')) ORDER BY rolname) FROM capabilities),\n  'memberships',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(\n    a.name,b.name,g.name,m.admin_option,m.inherit_option,m.set_option)\n    ORDER BY a.name,b.name,g.name),'[]'::jsonb)\n    FROM pg_catalog.pg_auth_members m JOIN names a ON a.oid=m.roleid\n    JOIN names b ON b.oid=m.member JOIN names g ON g.oid=m.grantor\n    WHERE m.roleid IN (SELECT oid FROM capabilities) OR m.member IN (SELECT oid FROM capabilities)),\n  'table_privileges',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(\n    r.rolname,c.relname,p.privilege,\n    pg_catalog.has_table_privilege(r.oid,c.oid,p.privilege||' WITH GRANT OPTION'))\n    ORDER BY r.rolname,c.relname,p.privilege),'[]'::jsonb)\n    FROM capabilities r CROSS JOIN pg_catalog.pg_class c\n    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace\n    CROSS JOIN pg_catalog.unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) p(privilege)\n    WHERE n.nspname='cragkit_qdrant' AND c.relkind='r'\n    AND pg_catalog.has_table_privilege(r.oid,c.oid,p.privilege)),\n  'column_privileges',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(\n    r.rolname,c.relname,a.attname,p.privilege,\n    pg_catalog.has_column_privilege(r.oid,c.oid,a.attnum,p.privilege||' WITH GRANT OPTION'))\n    ORDER BY r.rolname,c.relname,a.attname,p.privilege),'[]'::jsonb)\n    FROM capabilities r CROSS JOIN pg_catalog.pg_class c\n    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace\n    JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid\n    CROSS JOIN pg_catalog.unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) p(privilege)\n    WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped\n    AND pg_catalog.has_column_privilege(r.oid,c.oid,a.attnum,p.privilege)),\n  'function_privileges',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(\n    r.rolname,f.proname,pg_catalog.pg_get_function_identity_arguments(f.oid),\n    pg_catalog.has_function_privilege(r.oid,f.oid,'EXECUTE WITH GRANT OPTION'))\n    ORDER BY r.rolname,f.proname,pg_catalog.pg_get_function_identity_arguments(f.oid)),'[]'::jsonb)\n    FROM capabilities r CROSS JOIN pg_catalog.pg_proc f\n    JOIN pg_catalog.pg_namespace n ON n.oid=f.pronamespace\n    WHERE n.nspname='cragkit_qdrant' AND pg_catalog.has_function_privilege(r.oid,f.oid,'EXECUTE')),\n  'function_owners',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(\n    n.nspname,f.proname,pg_catalog.pg_get_function_identity_arguments(f.oid),r.rolname)\n    ORDER BY n.nspname,f.proname,pg_catalog.pg_get_function_identity_arguments(f.oid)),'[]'::jsonb)\n    FROM pg_catalog.pg_proc f JOIN capabilities r ON r.oid=f.proowner\n    JOIN pg_catalog.pg_namespace n ON n.oid=f.pronamespace),\n  'function_acls',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(\n    f.proname,pg_catalog.pg_get_function_identity_arguments(f.oid),g.name,u.name,x.privilege_type,x.is_grantable)\n    ORDER BY f.proname,pg_catalog.pg_get_function_identity_arguments(f.oid),g.name,u.name,x.privilege_type),'[]'::jsonb)\n    FROM pg_catalog.pg_proc f JOIN capabilities r ON r.oid=f.proowner\n    CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(f.proacl,pg_catalog.acldefault('f',f.proowner))) x\n    JOIN names g ON g.oid=x.grantor JOIN names u ON u.oid=x.grantee),\n  'owned_schemas',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(n.nspname,r.rolname)\n    ORDER BY n.nspname,r.rolname),'[]'::jsonb) FROM pg_catalog.pg_namespace n JOIN capabilities r ON r.oid=n.nspowner),\n  'owned_relations',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(n.nspname,c.relname,r.rolname)\n    ORDER BY n.nspname,c.relname,r.rolname),'[]'::jsonb) FROM pg_catalog.pg_class c JOIN capabilities r ON r.oid=c.relowner\n    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace),\n  'owned_types',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(n.nspname,t.typname,r.rolname)\n    ORDER BY n.nspname,t.typname,r.rolname),'[]'::jsonb) FROM pg_catalog.pg_type t JOIN capabilities r ON r.oid=t.typowner\n    JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace),\n  'owned_databases',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(d.datname,r.rolname)\n    ORDER BY d.datname,r.rolname),'[]'::jsonb) FROM pg_catalog.pg_database d JOIN capabilities r ON r.oid=d.datdba)\n ) AS payload\n)\nSELECT pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(payload::text,'UTF8')),'hex') FROM inventory\n"
_HISTORY_SQL = 'SELECT version, checksum_sha256 FROM cragkit_qdrant.schema_migrations ORDER BY version LIMIT 6'
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


_PURGE_SELECTION = _SELECTION.replace('octet_length(r.canonical_utf8)', 'r.canonical_original_bytes').replace(
    'octet_length(m.excerpt_utf8)', 'm.excerpt_original_bytes').replace(
    'CASE WHEN ', 'CASE WHEN NOT d.content_unavailable AND ').replace(
    'g.ever_published,d.tombstoned', 'g.ever_published,(d.tombstoned OR d.content_unavailable)')
_PURGE_SOURCE_SQL = _SOURCE_SQL.replace(_SELECTION, _PURGE_SELECTION)


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
        self._requires_security_guard = False
        self._admitted_history: tuple[tuple[str, str], ...] | None = None

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

    async def _history(self, connection: SessionConnection, deadline: float) -> tuple[tuple[str, str], ...]:
        try:
            rows = await query(connection, _HISTORY_SQL, None, deadline)
        except IntegrityViolation:
            raise UnsupportedCapability() from None
        if len(rows) not in (1, 2, 3, 4, 5) or any(
                len(row) != 2 or any(type(value) is not str for value in row) for row in rows):
            raise UnsupportedCapability()
        history = tuple(rows)
        if history not in (EXPECTED_HISTORY, EXPECTED_PUBLICATION_HISTORY,
                           EXPECTED_ATTESTATION_HISTORY, EXPECTED_SECURITY_GUARD_HISTORY, EXPECTED_PURGE_HISTORY):
            raise UnsupportedCapability()
        if self._admitted_history is not None and history != self._admitted_history:
            raise UnsupportedCapability()
        return history

    async def _validate_profile(self, connection: SessionConnection,
                                history: tuple[tuple[str, str], ...], deadline: float) -> None:
        if history == EXPECTED_HISTORY:
            catalog_sql, fingerprint = _CATALOG_SQL, EXPECTED_CATALOG_FINGERPRINT
        elif history == EXPECTED_PUBLICATION_HISTORY:
            catalog_sql, fingerprint = _PUBLICATION_CATALOG_SQL, EXPECTED_PUBLICATION_CATALOG_FINGERPRINT
        elif history == EXPECTED_ATTESTATION_HISTORY:
            catalog_sql, fingerprint = _ATTESTATION_CATALOG_SQL, EXPECTED_ATTESTATION_CATALOG_FINGERPRINT
        elif history == EXPECTED_SECURITY_GUARD_HISTORY:
            catalog_sql, fingerprint = _SECURITY_GUARD_CATALOG_SQL, EXPECTED_SECURITY_GUARD_CATALOG_FINGERPRINT
        else:
            catalog_sql, fingerprint = _PURGE_CATALOG_SQL, EXPECTED_PURGE_CATALOG_FINGERPRINT
        catalog = await query(connection, catalog_sql, None, deadline)
        if len(catalog) != 1 or len(catalog[0]) != 1 or catalog[0][0] is not True:
            raise UnsupportedCapability()
        role = await query(connection, _ROLE_SQL, None, deadline)
        if len(role) != 1 or len(role[0]) != 1 or role[0][0] is not True:
            raise UnauthorizedScope()
        observed = await query(connection, _CATALOG_FINGERPRINT_SQL, None, deadline)
        if (len(observed) != 1 or len(observed[0]) != 1 or type(observed[0][0]) is not str
                or observed[0][0] != fingerprint):
            raise UnsupportedCapability()
        if history in (EXPECTED_SECURITY_GUARD_HISTORY, EXPECTED_PURGE_HISTORY):
            owner_sql = _PURGE_OWNER_SQL if history == EXPECTED_PURGE_HISTORY else _SECURITY_GUARD_OWNER_SQL
            owner = await query(connection, owner_sql, None, deadline)
            if len(owner) != 1 or len(owner[0]) != 1 or owner[0][0] is not True:
                raise UnsupportedCapability()
        if history == EXPECTED_PURGE_HISTORY:
            capability = await query(connection, _PURGE_CAPABILITY_FINGERPRINT_SQL, None, deadline)
            if (len(capability) != 1 or len(capability[0]) != 1 or type(capability[0][0]) is not str
                    or capability[0][0] != EXPECTED_PURGE_CAPABILITY_FINGERPRINT):
                raise UnsupportedCapability()

    async def initialize(self, *, deadline: float) -> None:
        async with self.transaction(deadline) as connection:
            history = await self._history(connection, deadline)
            await self._validate_profile(connection, history, deadline)
        self._requires_security_guard = history in (EXPECTED_SECURITY_GUARD_HISTORY, EXPECTED_PURGE_HISTORY)
        self._admitted_history = history

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
            history = await self._history(connection, deadline)
            if history in (EXPECTED_SECURITY_GUARD_HISTORY, EXPECTED_PURGE_HISTORY):
                await self._validate_profile(connection, history, deadline)
                self._requires_security_guard = True
            elif await query(connection, _ROLE_SQL, None, deadline) != [(True,)]:
                raise UnauthorizedScope()
            await query(connection, _SCOPE_SQL, (scope.tenant_id,request.collection,scope.principal_id,grants,scope.authorization_revision), deadline)
            source_sql = _PURGE_SOURCE_SQL if history == EXPECTED_PURGE_HISTORY else _SOURCE_SQL
            rows = await query(connection, source_sql.format(publication='TRUE' if retained else 'g.published AND d.active_generation_id=g.generation_id', predicate=predicate), args, deadline)
            if len(rows) > 1 or any(len(row) != len(SOURCE_ROW_FIELDS) for row in rows):
                raise IntegrityViolation()
            self._admitted_history = history
            return [dict(zip(SOURCE_ROW_FIELDS, row)) for row in rows]
