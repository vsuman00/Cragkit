import {PoolResource,bounded,now,type PgClient,type LeaseOptions} from './postgres-pool.js';
import { types } from 'node:util';
import {DeadlineExceeded,IntegrityViolation,InvalidRequest,ProviderUnavailable,UnauthorizedScope,UnsupportedCapability} from './errors.js';
import {check_deadline} from './qdrant-transport.js';
import {compile_source_filters,SOURCE_ROW_FIELDS} from './qdrant-source-contract.js';
import {type QdrantNomination,type QdrantConfig} from './qdrant-contract.js';
import {type RetrievalRequest,type TrustedScope} from './requests.js';

export const AUTHORITY_HISTORY=Object.freeze([Object.freeze(['0001_authority','3d75cd46eb32a10864f1097a7494b01f9759150911a7cd9a1e6aab60105c1f1a'])]);
export const AUTHORITY_PUBLICATION_HISTORY = Object.freeze([
  ...AUTHORITY_HISTORY,
  Object.freeze(['0002_publication', '386fe01d0d03e35ac35c21bce598b21bff2c5ad510e9cdf0a6fbe56f359b6661']),
]);
export const AUTHORITY_ATTESTATION_HISTORY=Object.freeze([
  ...AUTHORITY_PUBLICATION_HISTORY,
  Object.freeze(['0003_preparation_attestations','8c6791cd0fd65ff09758c068ebc90a895a4ac21d9713512486d3daf9cb7c8433']),
]);
export const EXPECTED_ATTESTATION_HISTORY=AUTHORITY_ATTESTATION_HISTORY;
export const EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT='7ffd3b585b1fe32bc3476a3dc4390b022f5dcfd6c5ed186c9964fec4ffd72848';
export const EXPECTED_ATTESTATION_FINGERPRINT=EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT;
export const EXPECTED_ATTESTATION_CATALOG_FINGERPRINT=EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT;
export const EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT = 'e395925257def30b9d143b7210c68583d4cbbb0950d8a8e1bb4f5aba5b8be69b';
export const AUTHORITY_ROLE_SQL=`SELECT current_user = session_user
 AND EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolcanlogin AND NOT(rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication))
 AND NOT EXISTS(SELECT 1 FROM pg_roles r WHERE pg_has_role(current_user,r.oid,'MEMBER') AND (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication OR r.rolname IN('pg_read_all_data','pg_write_all_data','pg_read_server_files','pg_write_server_files','pg_execute_server_program','cragkit_qdrant_writer','cragkit_qdrant_supervisor')))
 AND EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='cragkit_qdrant' AND has_schema_privilege(current_user,oid,'USAGE') AND NOT has_schema_privilege(current_user,oid,'CREATE') AND NOT pg_has_role(current_user,nspowner,'MEMBER'))
 AND NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND c.relkind IN('r','p') AND (pg_has_role(current_user,c.relowner,'MEMBER') OR has_table_privilege(current_user,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') OR has_any_column_privilege(current_user,c.oid,'INSERT,UPDATE,REFERENCES') OR (c.relname<>'schema_migrations' AND NOT row_security_active(c.oid))))
 AND NOT EXISTS(SELECT 1 FROM (VALUES('documents'),('document_revisions'),('generations'),('members'),('schema_migrations')) required(name) WHERE NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND c.relname=required.name AND c.relkind='r' AND has_table_privilege(current_user,c.oid,'SELECT')))
 AND NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND c.relkind IN('r','p') AND c.relname NOT IN('documents','document_revisions','generations','members','schema_migrations') AND (has_table_privilege(current_user,c.oid,'SELECT') OR has_any_column_privilege(current_user,c.oid,'SELECT')))
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='cragkit_qdrant' AND pg_has_role(current_user,p.proowner,'MEMBER'))
 AND NOT EXISTS(SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='cragkit_qdrant' AND pg_has_role(current_user,t.typowner,'MEMBER'))
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='cragkit_qdrant' AND p.oid IS DISTINCT FROM to_regprocedure('cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean)') AND p.oid IS DISTINCT FROM to_regprocedure('cragkit_qdrant.scope_grants()') AND p.oid IS DISTINCT FROM to_regprocedure('cragkit_qdrant.valid_identity_array(text[])') AND has_function_privilege(current_user,p.oid,'EXECUTE'))
 AND has_function_privilege(current_user,'cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean)','EXECUTE')
 AND has_function_privilege(current_user,'cragkit_qdrant.scope_grants()','EXECUTE')
 AND has_function_privilege(current_user,'cragkit_qdrant.valid_identity_array(text[])','EXECUTE')`;
export const AUTHORITY_CATALOG_SQL=`SELECT current_setting('server_version_num')::integer BETWEEN 170000 AND 179999
 AND current_setting('server_encoding')='UTF8'
 AND (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND c.relname IN('documents','document_revisions','generations','members','schema_migrations'))=5
 AND NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND c.relname IN('documents','document_revisions','generations','members') AND (NOT c.relrowsecurity OR NOT c.relforcerowsecurity OR (SELECT count(*) FROM pg_policy p WHERE p.polrelid=c.oid AND p.polcmd='r')<>1 OR EXISTS(SELECT 1 FROM pg_policy p WHERE p.polrelid=c.oid AND p.polcmd<>'r')))
 AND (SELECT count(*) FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND k.contype='p')=5
 AND (SELECT count(*) FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND k.contype='f')=4
 AND NOT EXISTS(SELECT 1 FROM (VALUES('document_revisions','immutable_revision'),('members','immutable_member'),('documents','document_authority_update'),('generations','generation_identity_update'),('members','canonical_member_insert')) AS expected(tbl,trg) WHERE NOT EXISTS(SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND c.relname=expected.tbl AND t.tgname=expected.trg AND t.tgenabled='O'))
 AND NOT EXISTS(SELECT 1 FROM (VALUES('document_revisions','canonical_utf8','pg_catalog.bytea'),('document_revisions','source_sha256','cragkit_qdrant.sha256_hex'),('documents','mutation_epoch','cragkit_qdrant.safe_count'),('documents','principal_ids','pg_catalog.text[]'),('documents','grant_ids','pg_catalog.text[]'),('members','excerpt_utf8','pg_catalog.bytea'),('members','point_id','pg_catalog.uuid'),('members','start_byte','cragkit_qdrant.safe_count'),('members','end_byte','cragkit_qdrant.safe_count'),('generations','dense_profile','pg_catalog.jsonb'),('generations','sparse_profile','pg_catalog.jsonb')) AS expected(tbl,col,typ) WHERE NOT EXISTS(SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND c.relname=expected.tbl AND a.attname=expected.col AND a.atttypid=to_regtype(expected.typ) AND NOT a.attisdropped))`;
export const EXPECTED_AUTHORITY_FINGERPRINT='8104abeef00594e7bfa4b533a139767599b56b87d09062c0d6f52f6e2f5d0b48';
export const AUTHORITY_PUBLICATION_CATALOG_SQL = `SELECT current_setting('server_version_num')::integer BETWEEN 170000 AND 179999
 AND current_setting('server_encoding')='UTF8'
 AND (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND c.relkind='r')=13
 AND (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND c.relname IN('documents','document_revisions','generations','members','schema_migrations','backend_instances','publication_intents','document_owners','point_claims','vector_replays','dispatch_journal','dispatch_points','preparations'))=13
 AND (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND c.relname<>'schema_migrations' AND c.relrowsecurity AND c.relforcerowsecurity)=12
 AND NOT EXISTS(SELECT 1 FROM pg_constraint k JOIN pg_namespace n ON n.oid=k.connamespace WHERE n.nspname='cragkit_qdrant' AND NOT k.convalidated)
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='cragkit_qdrant' AND p.prosecdef)
 AND NOT EXISTS(SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND t.tgenabled<>'O')`;
export const AUTHORITY_ATTESTATION_CATALOG_SQL = `SELECT current_setting('server_version_num')::integer BETWEEN 170000 AND 179999
 AND current_setting('server_encoding')='UTF8'
 AND (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND c.relkind='r')=14
 AND (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND c.relname IN('documents','document_revisions','generations','members','schema_migrations','backend_instances','publication_intents','document_owners','point_claims','vector_replays','dispatch_journal','dispatch_points','preparations','preparation_attestations'))=14
 AND (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND c.relname<>'schema_migrations' AND c.relrowsecurity AND c.relforcerowsecurity)=13
 AND NOT EXISTS(SELECT 1 FROM pg_constraint k JOIN pg_namespace n ON n.oid=k.connamespace WHERE n.nspname='cragkit_qdrant' AND NOT k.convalidated)
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='cragkit_qdrant' AND p.prosecdef)
 AND NOT EXISTS(SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND t.tgenabled<>'O')`;
export const AUTHORITY_FINGERPRINT_SQL="-- QS-r1 PostgreSQL 17 catalog signature. Execute with search_path=pg_catalog.\n-- Runtime role/ownership/permissions are checked separately. This signature\n-- excludes physical OIDs, owners, timestamps and named runtime grants.\nWITH catalog AS (\nSELECT jsonb_build_object(\n 'namespace_public', (SELECT COALESCE(jsonb_agg(jsonb_build_array(x.privilege_type,x.is_grantable) ORDER BY x.privilege_type,x.is_grantable),'[]'::jsonb)\n   FROM pg_namespace n CROSS JOIN LATERAL aclexplode(COALESCE(n.nspacl,acldefault('n',n.nspowner))) x\n   WHERE n.nspname='cragkit_qdrant' AND x.grantee=0),\n 'relations', (SELECT COALESCE(jsonb_agg(jsonb_build_array(c.relname,c.relkind,c.relpersistence,c.relrowsecurity,c.relforcerowsecurity,c.reloptions,\n   (SELECT COALESCE(jsonb_agg(jsonb_build_array(x.privilege_type,x.is_grantable) ORDER BY x.privilege_type,x.is_grantable),'[]'::jsonb)\n    FROM aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) x WHERE x.grantee=0)) ORDER BY c.relname),'[]'::jsonb)\n   FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant'),\n 'columns', (SELECT COALESCE(jsonb_agg(jsonb_build_array(c.relname,a.attnum,a.attname,format_type(a.atttypid,a.atttypmod),\n   a.attnotnull,a.attidentity,a.attgenerated,a.attisdropped,cn.nspname,co.collname,pg_get_expr(d.adbin,d.adrelid),\n   (SELECT COALESCE(jsonb_agg(jsonb_build_array(x.privilege_type,x.is_grantable) ORDER BY x.privilege_type,x.is_grantable),'[]'::jsonb)\n    FROM aclexplode(a.attacl) x WHERE x.grantee=0)) ORDER BY c.relname,a.attnum),'[]'::jsonb)\n   FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid\n   LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum LEFT JOIN pg_collation co ON co.oid=a.attcollation\n   LEFT JOIN pg_namespace cn ON cn.oid=co.collnamespace WHERE n.nspname='cragkit_qdrant' AND a.attnum>0 AND c.relkind IN ('r','p','v','m','f')),\n 'types', (SELECT COALESCE(jsonb_agg(jsonb_build_array(t.typname,t.typtype,t.typcategory,\n   CASE WHEN t.typbasetype=0 THEN NULL ELSE format_type(t.typbasetype,t.typtypmod) END,t.typnotnull,\n   cn.nspname,co.collname,t.typdefault,\n   (SELECT COALESCE(jsonb_agg(jsonb_build_array(x.privilege_type,x.is_grantable) ORDER BY x.privilege_type,x.is_grantable),'[]'::jsonb)\n    FROM aclexplode(COALESCE(t.typacl,acldefault('T',t.typowner))) x WHERE x.grantee=0)) ORDER BY t.typname),'[]'::jsonb)\n   FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace LEFT JOIN pg_collation co ON co.oid=t.typcollation\n   LEFT JOIN pg_namespace cn ON cn.oid=co.collnamespace WHERE n.nspname='cragkit_qdrant'),\n 'constraints', (SELECT COALESCE(jsonb_agg(jsonb_build_array(cl.relname,ty.typname,k.conname,k.contype,k.convalidated,k.condeferrable,k.condeferred,\n   pg_get_constraintdef(k.oid,true)) ORDER BY cl.relname NULLS FIRST,ty.typname NULLS FIRST,k.conname),'[]'::jsonb)\n   FROM pg_constraint k JOIN pg_namespace n ON n.oid=k.connamespace LEFT JOIN pg_class cl ON cl.oid=k.conrelid\n   LEFT JOIN pg_type ty ON ty.oid=k.contypid WHERE n.nspname='cragkit_qdrant'),\n 'indexes', (SELECT COALESCE(jsonb_agg(jsonb_build_array(c.relname,i.indisvalid,i.indisready,pg_get_indexdef(i.indexrelid)) ORDER BY c.relname),'[]'::jsonb)\n   FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant'),\n 'triggers', (SELECT COALESCE(jsonb_agg(jsonb_build_array(c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid,true)) ORDER BY c.relname,t.tgname),'[]'::jsonb)\n   FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND NOT t.tgisinternal),\n 'policies', (SELECT COALESCE(jsonb_agg(jsonb_build_array(c.relname,p.polname,p.polcmd,p.polpermissive,\n   (SELECT jsonb_agg(role_name ORDER BY role_name) FROM (SELECT CASE WHEN role_id=0 THEN 'PUBLIC' ELSE (SELECT rolname::text FROM pg_roles WHERE oid=role_id) END AS role_name FROM unnest(p.polroles) role_id) named_roles),pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid)) ORDER BY c.relname,p.polname),'[]'::jsonb)\n   FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant'),\n 'functions', (SELECT COALESCE(jsonb_agg(jsonb_build_array(p.proname,pg_get_function_identity_arguments(p.oid),p.prokind,\n   p.prosecdef,p.proleakproof,p.provolatile,p.proparallel,p.proisstrict,p.proconfig,CASE WHEN p.prokind='a' THEN NULL ELSE pg_get_functiondef(p.oid) END,\n   (SELECT COALESCE(jsonb_agg(jsonb_build_array(x.privilege_type,x.is_grantable) ORDER BY x.privilege_type,x.is_grantable),'[]'::jsonb)\n    FROM aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) x WHERE x.grantee=0)) ORDER BY p.proname,pg_get_function_identity_arguments(p.oid)),'[]'::jsonb)\n   FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='cragkit_qdrant')\n) AS payload\n)\nSELECT encode(sha256(convert_to(payload::text,'UTF8')),'hex') AS schema_fingerprint FROM catalog;\n";
export const AUTHORITY_HISTORY_SQL='SELECT version, checksum_sha256 FROM cragkit_qdrant.schema_migrations ORDER BY version COLLATE pg_catalog."C" LIMIT 4';
export const AUTHORITY_SCOPE_SQL=`SELECT set_config('cragkit_qdrant.tenant_id',$1,true),set_config('cragkit_qdrant.collection',$2,true),set_config('cragkit_qdrant.principal_id',$3,true),set_config('cragkit_qdrant.grant_ids',$4,true),set_config('cragkit_qdrant.authorization_revision',$5,true)`;
const SELECT_SOURCE=`SELECT m.point_id::text,g.backend_namespace,g.physical_collection,g.collection_incarnation,m.tenant_id,m.collection,m.document_id,m.revision_id,m.generation_id,m.chunk_id,m.start_byte,m.end_byte,m.source_sha256,m.text_sha256,g.dense_profile_id,g.sparse_profile_id,g.dense_profile,g.sparse_profile,d.authorization_revision,d.mutation_epoch,d.principal_ids,d.grant_ids,d.language,d.kind,d.tag,r.source_locator,r.parser_id,g.chunker_profile,octet_length(r.canonical_utf8),CASE WHEN octet_length(r.canonical_utf8)<=$1 AND octet_length(r.canonical_utf8)<=16777216 AND octet_length(m.excerpt_utf8)<=32768 THEN r.canonical_utf8 ELSE NULL END,octet_length(m.excerpt_utf8),CASE WHEN octet_length(r.canonical_utf8)<=$1 AND octet_length(r.canonical_utf8)<=16777216 AND octet_length(m.excerpt_utf8)<=32768 THEN m.excerpt_utf8 ELSE NULL END,d.active_generation_id,g.published,g.ever_published,d.tombstoned
 FROM cragkit_qdrant.members m
 JOIN cragkit_qdrant.generations g ON (g.tenant_id,g.collection,g.document_id,g.revision_id,g.generation_id)=(m.tenant_id,m.collection,m.document_id,m.revision_id,m.generation_id)
 JOIN cragkit_qdrant.document_revisions r ON (r.tenant_id,r.collection,r.document_id,r.revision_id)=(m.tenant_id,m.collection,m.document_id,m.revision_id)
 JOIN cragkit_qdrant.documents d ON (d.tenant_id,d.collection,d.document_id)=(m.tenant_id,m.collection,m.document_id)
 WHERE (m.tenant_id,m.collection,m.document_id,m.revision_id,m.generation_id,m.chunk_id)=($2,$3,$4,$5,$6,$7)
 AND d.tenant_id=$8 AND d.collection=$9 AND d.authorization_revision=$10 AND NOT d.tombstoned
 AND ($11=ANY(d.principal_ids) OR d.grant_ids && $12::text[])
 AND (g.backend_namespace,g.physical_collection,g.collection_incarnation)=($13,$14,$15)
 AND g.ever_published AND {publication} AND {filters} LIMIT 2`;
function safe_error(error:unknown,deadline?:number):Error{
  if(error instanceof DeadlineExceeded)return new DeadlineExceeded();
  if(error instanceof InvalidRequest)return new InvalidRequest();
  if(error instanceof UnsupportedCapability)return new UnsupportedCapability();
  if(error instanceof UnauthorizedScope)return new UnauthorizedScope();
  if(error instanceof IntegrityViolation)return new IntegrityViolation();
  if(error instanceof DOMException&&error.name==='AbortError')return new DOMException('Operation aborted.','AbortError');
  let code:unknown;
  try{
    code=(error as {code?:unknown})?.code;
  }catch{
    // Error properties are untrusted and are never copied into the public error.
  }
  if(code==='57014')return deadline!==undefined&&now()>=deadline?new DeadlineExceeded():new ProviderUnavailable();
  if(typeof code==='string'&&['42P01','42703','42883','3F000'].includes(code))return new UnsupportedCapability();
  return new ProviderUnavailable();
}

/** History is bounded native driver data; never call value serialization hooks. */
function validated_history(value: unknown): readonly (readonly string[])[] {
  function array(input: unknown, min: number, max: number): unknown[] {
    if (typeof input !== 'object' || input === null || types.isProxy(input)
      || !Array.isArray(input) || Object.getPrototypeOf(input) !== Array.prototype) {
      throw new UnsupportedCapability();
    }
    const length: unknown = Object.getOwnPropertyDescriptor(input, 'length')?.value;
    if (typeof length !== 'number' || length < min || length > max
      || Reflect.ownKeys(input).length !== length + 1) throw new UnsupportedCapability();
    const result: unknown[] = [];
    for (let index = 0; index < length; index++) {
      const descriptor = Object.getOwnPropertyDescriptor(input, String(index));
      if (!descriptor || !('value' in descriptor)) throw new UnsupportedCapability();
      result.push(descriptor.value);
    }
    return result;
  }
  return array(value, 1, 3).map(row => array(row, 2, 2).map(field => {
    if (typeof field !== 'string') throw new UnsupportedCapability();
    return field;
  }));
}

function history_matches(actual: readonly (readonly string[])[], expected: readonly (readonly string[])[]): boolean {
  return actual.length === expected.length
    && actual.every((row, index) => row[0] === expected[index][0] && row[1] === expected[index][1]);
}
export type PublicationSchemaProfile='publication'|'attestation';
export function publication_schema_profile(history:unknown):PublicationSchemaProfile{
  const checked=validated_history(history);
  if(history_matches(checked,AUTHORITY_PUBLICATION_HISTORY))return 'publication';
  if(history_matches(checked,AUTHORITY_ATTESTATION_HISTORY))return 'attestation';
  throw new UnsupportedCapability();
}
export class PostgresQdrantAuthority{
  constructor(readonly resource:PoolResource){
    if(!(resource instanceof PoolResource))throw new InvalidRequest();
  }
  async #query(client:PgClient,text:string,values:readonly unknown[]|undefined,options:LeaseOptions):Promise<unknown[][]>{
    check_deadline(options.deadline,options.signal);
    try{
      const timeout=String(Math.max(1,Math.floor(Math.min(options.deadline-now(),2147483.647)*1000)));
      await bounded(client.query({text:"SELECT set_config('statement_timeout',$1,true)",values:[timeout],rowMode:'array'}),options);
      const result=await bounded(client.query({text,values,rowMode:'array'}),options);
      check_deadline(options.deadline,options.signal);
      if (text === AUTHORITY_HISTORY_SQL) {
        if (typeof result !== 'object' || result === null || types.isProxy(result)) throw new UnsupportedCapability();
        const rows = Object.getOwnPropertyDescriptor(result, 'rows');
        if (!rows || !('value' in rows)) throw new UnsupportedCapability();
        return validated_history(rows.value).map(row => [...row]);
      }
      if(!result||!Array.isArray(result.rows)||result.rows.some(r=>!Array.isArray(r)))throw new IntegrityViolation();
      return result.rows;
    }catch(e){
      throw safe_error(e,options.deadline);
    }
  }
  async #run<T>(options:LeaseOptions,body:(client:PgClient,scope:LeaseOptions)=>Promise<T>):Promise<T>{
    check_deadline(options.deadline,options.signal);
    try{
      return await this.resource.withLease(options,async(client,signal)=>{
        let status:string|null;
        try{
          status=client.getTransactionStatus();
        }catch{
          client.release(true);
          throw new ProviderUnavailable();
        }
        if(status!=='I'){
          client.release(true);
          throw new InvalidRequest();
        }
        const scoped={deadline:options.deadline,signal};
        let begun=false;
        let failed=false;
        let failure:unknown;
        let result!:T;
        try{
          await bounded(client.query({text:'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY',rowMode:'array'}),scoped);
          begun=true;
          await bounded(client.query({text:'SET LOCAL search_path = pg_catalog',rowMode:'array'}),scoped);
          result=await body(client,scoped);
          check_deadline(scoped.deadline,signal);
        }catch(e){
          failed=true;
          failure=safe_error(e,options.deadline);
        }finally{
          let clean=false;
          if(begun&&!signal.aborted){
            try{
              await bounded(client.query({text:'ROLLBACK',rowMode:'array'}),{deadline:now()+this.resource.config.release_timeout});
              clean=client.getTransactionStatus()==='I';
            }catch{
              // A failed rollback or uncertain transaction is never reusable.
            }
          }
          if(!clean){
            try{
              client.release(true);
            }catch{
              // PoolResource owns the release state even when the driver fails.
            }
            if(!failed){
              failed=true;
              failure=new ProviderUnavailable();
            }
          }
        }
        if(failed)throw failure;
        return result;
      });
    }catch(e){
      throw safe_error(e,options.deadline);
    }
  }
  async initialize(options:LeaseOptions):Promise<void>{
    await this.#run(options,(client,scoped)=>this.#validate(client,scoped));
  }
  async #validate(client:PgClient,options:LeaseOptions):Promise<void>{
    let history: unknown[][];
    try {
      history = await this.#query(client, AUTHORITY_HISTORY_SQL, undefined, options);
    } catch (error) {
      if (error instanceof IntegrityViolation) throw new UnsupportedCapability();
      throw error;
    }
    const checkedHistory = validated_history(history);
    let catalogSql: string;
    let expectedFingerprint: string;
    if (history_matches(checkedHistory, AUTHORITY_HISTORY)) {
      catalogSql = AUTHORITY_CATALOG_SQL;
      expectedFingerprint = EXPECTED_AUTHORITY_FINGERPRINT;
    } else if (history_matches(checkedHistory, AUTHORITY_PUBLICATION_HISTORY)) {
      catalogSql = AUTHORITY_PUBLICATION_CATALOG_SQL;
      expectedFingerprint = EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT;
    } else if (history_matches(checkedHistory, AUTHORITY_ATTESTATION_HISTORY)) {
      catalogSql=AUTHORITY_ATTESTATION_CATALOG_SQL;
      expectedFingerprint=EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT;
    } else {
      throw new UnsupportedCapability();
    }
    const catalog=await this.#query(client,catalogSql,undefined,options);
    if(JSON.stringify(catalog)!=='[[true]]')throw new UnsupportedCapability();
    const role=await this.#query(client,AUTHORITY_ROLE_SQL,undefined,options);
    if(JSON.stringify(role)!=='[[true]]')throw new UnauthorizedScope();
    const fingerprint=await this.#query(client,AUTHORITY_FINGERPRINT_SQL,undefined,options);
    if(JSON.stringify(fingerprint)!==JSON.stringify([[expectedFingerprint]]))throw new UnsupportedCapability();
  }
  async read(nom:QdrantNomination,request:RetrievalRequest,scope:TrustedScope,config:QdrantConfig,options:LeaseOptions&{retained:boolean;max_source_bytes:number}):Promise<Record<string,unknown>[]>{
    const [filters,parameters]=compile_source_filters(request.required_filters,16);
    const grants=JSON.stringify(scope.grant_ids);
    if(Buffer.byteLength(grants,'utf8')>131072)throw new InvalidRequest();
    const text=SELECT_SOURCE.replace('{publication}',options.retained?'TRUE':'g.published AND d.active_generation_id=g.generation_id').replace('{filters}',filters);
    return this.#run(options,async(client,scoped)=>{
      const role=await this.#query(client,AUTHORITY_ROLE_SQL,undefined,scoped);
      if(JSON.stringify(role)!=='[[true]]')throw new UnauthorizedScope();
      await this.#query(client,AUTHORITY_SCOPE_SQL,[scope.tenant_id,request.collection,scope.principal_id,grants,scope.authorization_revision],scoped);
      const p=nom.payload;
      const rows=await this.#query(client,text,[options.max_source_bytes,p.tenant_id,p.collection,p.document_id,p.revision_id,p.generation_id,p.chunk_id,scope.tenant_id,request.collection,scope.authorization_revision,scope.principal_id,[...scope.grant_ids],config.backend_namespace,config.physical_collection,config.collection_incarnation,...parameters],scoped);
      if(rows.length>1||rows.some(row=>row.length!==SOURCE_ROW_FIELDS.length))throw new IntegrityViolation();
      for(const row of rows){
        for(let i=0;i<row.length;i++){
          const descriptor=Object.getOwnPropertyDescriptor(row,String(i));
          if(!descriptor||!('value'in descriptor)||!descriptor.enumerable)throw new IntegrityViolation();
        }
      }
      return rows.map(row=>Object.fromEntries(SOURCE_ROW_FIELDS.map((key,index)=>[key,row[index]])));
    });
  }
}
