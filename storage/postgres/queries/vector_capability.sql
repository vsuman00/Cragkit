SELECT current_setting('server_encoding')='UTF8'
 AND EXISTS (SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
  WHERE e.extname='vector' AND e.extversion='0.8.0' AND n.nspname='cragkit_vector')
 AND EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
  JOIN pg_depend d ON d.classid='pg_type'::regclass AND d.objid=t.oid AND d.deptype='e'
  JOIN pg_extension e ON e.oid=d.refobjid AND d.refclassid='pg_extension'::regclass
  WHERE n.nspname='cragkit_vector' AND t.typname='vector' AND t.typtype='b' AND e.extname='vector'
  AND EXISTS (SELECT 1 FROM pg_proc p JOIN pg_depend pd ON pd.classid='pg_proc'::regclass AND pd.objid=p.oid AND pd.deptype='e'
   WHERE p.pronamespace=n.oid AND p.proname='vector_dims' AND p.pronargs=1 AND p.proargtypes[0]=t.oid
   AND p.prorettype='int4'::regtype AND NOT p.prosecdef AND pd.refclassid='pg_extension'::regclass AND pd.refobjid=e.oid))
 AND NOT EXISTS (SELECT 1 FROM (VALUES ('embedding_profiles'),('chunk_vectors_fake_1536')) expected(name)
  LEFT JOIN pg_namespace n ON n.nspname='cragkit' LEFT JOIN pg_class c ON c.relnamespace=n.oid AND c.relname=expected.name
  WHERE c.relkind IS DISTINCT FROM 'r' OR NOT coalesce(c.relrowsecurity,false))
 AND EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  JOIN pg_attribute a ON a.attrelid=c.oid AND a.attname='embedding' AND NOT a.attisdropped
  WHERE n.nspname='cragkit' AND c.relname='chunk_vectors_fake_1536'
   AND a.atttypid=to_regtype('cragkit_vector.vector') AND a.atttypmod=1536)
 AND NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname IN ('cragkit','cragkit_vector') AND p.prosecdef)
