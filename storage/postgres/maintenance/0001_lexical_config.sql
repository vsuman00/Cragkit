-- LCR-r1: explicit operator maintenance, never a migration-history replacement.
-- The caller validates and locks the complete supported state before this update.
UPDATE cragkit.chunk_lexical AS lexical
SET language_config = 'pg_catalog.simple'
FROM cragkit.index_generations AS generation
WHERE lexical.tenant_id = generation.tenant_id
  AND lexical.collection_id = generation.collection_id
  AND lexical.document_id = generation.document_id
  AND lexical.revision_id = generation.revision_id
  AND lexical.generation_id = generation.generation_id
  AND generation.lexical_profile = 'native_fts.v1'
  AND lexical.language_config = 'simple';
