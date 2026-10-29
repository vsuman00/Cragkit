-- QP-r1 capability inventory. Normalize only installation-specific operator
-- and bootstrap names; preserve every effective privilege and membership edge.
WITH operators AS (
 SELECT nspowner AS operator_id FROM pg_catalog.pg_namespace WHERE nspname='cragkit_qdrant'
), names AS (
 SELECT r.oid, CASE WHEN r.oid=o.operator_id THEN pg_catalog.jsonb_build_array('operator')
                   WHEN r.oid=10 THEN pg_catalog.jsonb_build_array('bootstrap')
                   ELSE pg_catalog.jsonb_build_array('role',r.rolname) END AS name
 FROM pg_catalog.pg_roles r CROSS JOIN operators o
 UNION ALL SELECT 0::oid,pg_catalog.jsonb_build_array('public')
), capabilities AS (
 SELECT * FROM pg_catalog.pg_roles
 WHERE rolname IN ('cragkit_qdrant_security_guard','cragkit_qdrant_purger')
), inventory AS (
 SELECT pg_catalog.jsonb_build_object(
  'roles',(SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(rolname,
    rolcanlogin,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication,rolinherit,
    pg_catalog.has_schema_privilege(oid,'cragkit_qdrant','USAGE'),
    pg_catalog.has_schema_privilege(oid,'cragkit_qdrant','CREATE')) ORDER BY rolname) FROM capabilities),
  'memberships',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(
    a.name,b.name,g.name,m.admin_option,m.inherit_option,m.set_option)
    ORDER BY a.name,b.name,g.name),'[]'::jsonb)
    FROM pg_catalog.pg_auth_members m JOIN names a ON a.oid=m.roleid
    JOIN names b ON b.oid=m.member JOIN names g ON g.oid=m.grantor
    WHERE m.roleid IN (SELECT oid FROM capabilities) OR m.member IN (SELECT oid FROM capabilities)),
  'table_privileges',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(
    r.rolname,c.relname,p.privilege,
    pg_catalog.has_table_privilege(r.oid,c.oid,p.privilege||' WITH GRANT OPTION'))
    ORDER BY r.rolname,c.relname,p.privilege),'[]'::jsonb)
    FROM capabilities r CROSS JOIN pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    CROSS JOIN pg_catalog.unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) p(privilege)
    WHERE n.nspname='cragkit_qdrant' AND c.relkind='r'
    AND pg_catalog.has_table_privilege(r.oid,c.oid,p.privilege)),
  'column_privileges',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(
    r.rolname,c.relname,a.attname,p.privilege,
    pg_catalog.has_column_privilege(r.oid,c.oid,a.attnum,p.privilege||' WITH GRANT OPTION'))
    ORDER BY r.rolname,c.relname,a.attname,p.privilege),'[]'::jsonb)
    FROM capabilities r CROSS JOIN pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid
    CROSS JOIN pg_catalog.unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) p(privilege)
    WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
    AND pg_catalog.has_column_privilege(r.oid,c.oid,a.attnum,p.privilege)),
  'function_privileges',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(
    r.rolname,f.proname,pg_catalog.pg_get_function_identity_arguments(f.oid),
    pg_catalog.has_function_privilege(r.oid,f.oid,'EXECUTE WITH GRANT OPTION'))
    ORDER BY r.rolname,f.proname,pg_catalog.pg_get_function_identity_arguments(f.oid)),'[]'::jsonb)
    FROM capabilities r CROSS JOIN pg_catalog.pg_proc f
    JOIN pg_catalog.pg_namespace n ON n.oid=f.pronamespace
    WHERE n.nspname='cragkit_qdrant' AND pg_catalog.has_function_privilege(r.oid,f.oid,'EXECUTE')),
  'function_owners',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(
    n.nspname,f.proname,pg_catalog.pg_get_function_identity_arguments(f.oid),r.rolname)
    ORDER BY n.nspname,f.proname,pg_catalog.pg_get_function_identity_arguments(f.oid)),'[]'::jsonb)
    FROM pg_catalog.pg_proc f JOIN capabilities r ON r.oid=f.proowner
    JOIN pg_catalog.pg_namespace n ON n.oid=f.pronamespace),
  'function_acls',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(
    f.proname,pg_catalog.pg_get_function_identity_arguments(f.oid),g.name,u.name,x.privilege_type,x.is_grantable)
    ORDER BY f.proname,pg_catalog.pg_get_function_identity_arguments(f.oid),g.name,u.name,x.privilege_type),'[]'::jsonb)
    FROM pg_catalog.pg_proc f JOIN capabilities r ON r.oid=f.proowner
    CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(f.proacl,pg_catalog.acldefault('f',f.proowner))) x
    JOIN names g ON g.oid=x.grantor JOIN names u ON u.oid=x.grantee),
  'owned_schemas',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(n.nspname,r.rolname)
    ORDER BY n.nspname,r.rolname),'[]'::jsonb) FROM pg_catalog.pg_namespace n JOIN capabilities r ON r.oid=n.nspowner),
  'owned_relations',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(n.nspname,c.relname,r.rolname)
    ORDER BY n.nspname,c.relname,r.rolname),'[]'::jsonb) FROM pg_catalog.pg_class c JOIN capabilities r ON r.oid=c.relowner
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace),
  'owned_types',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(n.nspname,t.typname,r.rolname)
    ORDER BY n.nspname,t.typname,r.rolname),'[]'::jsonb) FROM pg_catalog.pg_type t JOIN capabilities r ON r.oid=t.typowner
    JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace),
  'owned_databases',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(d.datname,r.rolname)
    ORDER BY d.datname,r.rolname),'[]'::jsonb) FROM pg_catalog.pg_database d JOIN capabilities r ON r.oid=d.datdba)
 ) AS payload
)
SELECT pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(payload::text,'UTF8')),'hex') FROM inventory
