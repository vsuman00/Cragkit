-- QS-r1 PostgreSQL 17 catalog signature. Execute with search_path=pg_catalog.
-- Runtime role/ownership/permissions are checked separately. This signature
-- excludes physical OIDs, owners, timestamps and named runtime grants.
WITH catalog AS (
SELECT jsonb_build_object(
 'namespace_public', (SELECT COALESCE(jsonb_agg(jsonb_build_array(x.privilege_type,x.is_grantable) ORDER BY x.privilege_type,x.is_grantable),'[]'::jsonb)
   FROM pg_namespace n CROSS JOIN LATERAL aclexplode(COALESCE(n.nspacl,acldefault('n',n.nspowner))) x
   WHERE n.nspname='cragkit_qdrant' AND x.grantee=0),
 'relations', (SELECT COALESCE(jsonb_agg(jsonb_build_array(c.relname,c.relkind,c.relpersistence,c.relrowsecurity,c.relforcerowsecurity,c.reloptions,
   (SELECT COALESCE(jsonb_agg(jsonb_build_array(x.privilege_type,x.is_grantable) ORDER BY x.privilege_type,x.is_grantable),'[]'::jsonb)
    FROM aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) x WHERE x.grantee=0)) ORDER BY c.relname),'[]'::jsonb)
   FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant'),
 'columns', (SELECT COALESCE(jsonb_agg(jsonb_build_array(c.relname,a.attnum,a.attname,format_type(a.atttypid,a.atttypmod),
   a.attnotnull,a.attidentity,a.attgenerated,a.attisdropped,cn.nspname,co.collname,pg_get_expr(d.adbin,d.adrelid),
   (SELECT COALESCE(jsonb_agg(jsonb_build_array(x.privilege_type,x.is_grantable) ORDER BY x.privilege_type,x.is_grantable),'[]'::jsonb)
    FROM aclexplode(a.attacl) x WHERE x.grantee=0)) ORDER BY c.relname,a.attnum),'[]'::jsonb)
   FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid
   LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum LEFT JOIN pg_collation co ON co.oid=a.attcollation
   LEFT JOIN pg_namespace cn ON cn.oid=co.collnamespace WHERE n.nspname='cragkit_qdrant' AND a.attnum>0 AND c.relkind IN ('r','p','v','m','f')),
 'types', (SELECT COALESCE(jsonb_agg(jsonb_build_array(t.typname,t.typtype,t.typcategory,
   CASE WHEN t.typbasetype=0 THEN NULL ELSE format_type(t.typbasetype,t.typtypmod) END,t.typnotnull,
   cn.nspname,co.collname,t.typdefault,
   (SELECT COALESCE(jsonb_agg(jsonb_build_array(x.privilege_type,x.is_grantable) ORDER BY x.privilege_type,x.is_grantable),'[]'::jsonb)
    FROM aclexplode(COALESCE(t.typacl,acldefault('T',t.typowner))) x WHERE x.grantee=0)) ORDER BY t.typname),'[]'::jsonb)
   FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace LEFT JOIN pg_collation co ON co.oid=t.typcollation
   LEFT JOIN pg_namespace cn ON cn.oid=co.collnamespace WHERE n.nspname='cragkit_qdrant'),
 'constraints', (SELECT COALESCE(jsonb_agg(jsonb_build_array(cl.relname,ty.typname,k.conname,k.contype,k.convalidated,k.condeferrable,k.condeferred,
   pg_get_constraintdef(k.oid,true)) ORDER BY cl.relname NULLS FIRST,ty.typname NULLS FIRST,k.conname),'[]'::jsonb)
   FROM pg_constraint k JOIN pg_namespace n ON n.oid=k.connamespace LEFT JOIN pg_class cl ON cl.oid=k.conrelid
   LEFT JOIN pg_type ty ON ty.oid=k.contypid WHERE n.nspname='cragkit_qdrant'),
 'indexes', (SELECT COALESCE(jsonb_agg(jsonb_build_array(c.relname,i.indisvalid,i.indisready,pg_get_indexdef(i.indexrelid)) ORDER BY c.relname),'[]'::jsonb)
   FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant'),
 'triggers', (SELECT COALESCE(jsonb_agg(jsonb_build_array(c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid,true)) ORDER BY c.relname,t.tgname),'[]'::jsonb)
   FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND NOT t.tgisinternal),
 'policies', (SELECT COALESCE(jsonb_agg(jsonb_build_array(c.relname,p.polname,p.polcmd,p.polpermissive,
   (SELECT jsonb_agg(role_name ORDER BY role_name) FROM (SELECT CASE WHEN role_id=0 THEN 'PUBLIC' ELSE (SELECT rolname::text FROM pg_roles WHERE oid=role_id) END AS role_name FROM unnest(p.polroles) role_id) named_roles),pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid)) ORDER BY c.relname,p.polname),'[]'::jsonb)
   FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant'),
 'functions', (SELECT COALESCE(jsonb_agg(jsonb_build_array(p.proname,pg_get_function_identity_arguments(p.oid),p.prokind,
   p.prosecdef,p.proleakproof,p.provolatile,p.proparallel,p.proisstrict,p.proconfig,CASE WHEN p.prokind='a' THEN NULL ELSE pg_get_functiondef(p.oid) END,
   (SELECT COALESCE(jsonb_agg(jsonb_build_array(x.privilege_type,x.is_grantable) ORDER BY x.privilege_type,x.is_grantable),'[]'::jsonb)
    FROM aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) x WHERE x.grantee=0)) ORDER BY p.proname,pg_get_function_identity_arguments(p.oid)),'[]'::jsonb)
   FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='cragkit_qdrant')
) AS payload
)
SELECT encode(sha256(convert_to(payload::text,'UTF8')),'hex') AS schema_fingerprint FROM catalog;
