SELECT d.tenant_id,d.collection_id,d.document_id,g.revision_id,g.generation_id,c.chunk_id,
 c.start_byte,c.end_byte,c.text_sha256,1.0::double precision,g.lexical_profile,l.language_config
FROM cragkit.documents d
JOIN cragkit.index_generations g ON g.tenant_id=d.tenant_id AND g.collection_id=d.collection_id
 AND g.document_id=d.document_id AND g.generation_id=d.active_generation_id
JOIN cragkit.chunks c ON c.tenant_id=g.tenant_id AND c.collection_id=g.collection_id
 AND c.document_id=g.document_id AND c.revision_id=g.revision_id AND c.generation_id=g.generation_id
JOIN cragkit.chunk_lexical l ON l.tenant_id=c.tenant_id AND l.collection_id=c.collection_id
 AND l.document_id=c.document_id AND l.revision_id=c.revision_id AND l.generation_id=c.generation_id AND l.chunk_id=c.chunk_id
WHERE d.tenant_id=%s AND d.collection_id=%s AND NOT d.tombstoned
 AND d.authorization_revision=%s AND g.status='ready'
 AND EXISTS(SELECT 1 FROM cragkit.document_grants x WHERE x.tenant_id=d.tenant_id AND x.collection_id=d.collection_id
  AND x.document_id=d.document_id AND x.authorization_revision=%s
  AND (x.principal_id=%s OR (x.principal_id IS NULL AND x.grant_id=ANY(%s::text[]))))
 AND ({predicate}) AND l.identifier_tokens @> ARRAY[%s]::cragkit.identity_text[]
ORDER BY d.document_id COLLATE pg_catalog."C",
 g.revision_id COLLATE pg_catalog."C",c.ordinal,c.chunk_id COLLATE pg_catalog."C"
LIMIT %s
