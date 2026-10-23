WITH query_vector AS (SELECT %s::cragkit_vector.vector(1536) AS embedding),
eligible AS MATERIALIZED (
 SELECT d.tenant_id,d.collection_id,d.document_id,g.revision_id,g.generation_id,c.chunk_id,
  c.start_byte,c.end_byte,c.text_sha256,c.ordinal,v.embedding,g.embedding_profile,g.lexical_profile
 FROM cragkit.documents d
 JOIN cragkit.index_generations g ON g.tenant_id=d.tenant_id AND g.collection_id=d.collection_id
  AND g.document_id=d.document_id AND g.generation_id=d.active_generation_id
 JOIN cragkit.chunks c ON c.tenant_id=g.tenant_id AND c.collection_id=g.collection_id
  AND c.document_id=g.document_id AND c.revision_id=g.revision_id AND c.generation_id=g.generation_id
 JOIN cragkit.chunk_vectors_fake_1536 v ON v.tenant_id=c.tenant_id AND v.collection_id=c.collection_id
  AND v.document_id=c.document_id AND v.revision_id=c.revision_id AND v.generation_id=c.generation_id
  AND v.chunk_id=c.chunk_id AND v.embedding_profile=g.embedding_profile
 WHERE v.embedding_profile=%s AND d.tenant_id=%s AND d.collection_id=%s AND NOT d.tombstoned
  AND d.authorization_revision=%s AND g.status='ready'
  AND EXISTS(SELECT 1 FROM cragkit.document_grants x WHERE x.tenant_id=d.tenant_id AND x.collection_id=d.collection_id
   AND x.document_id=d.document_id AND x.authorization_revision=%s
   AND (x.principal_id=%s OR (x.principal_id IS NULL AND x.grant_id=ANY(%s::text[]))))
  AND ({predicate})
)
SELECT e.tenant_id,e.collection_id,e.document_id,e.revision_id,e.generation_id,e.chunk_id,
 e.start_byte,e.end_byte,e.text_sha256,
 (e.embedding OPERATOR(cragkit_vector.<=>) q.embedding)::double precision AS distance,
 e.embedding_profile,e.lexical_profile
FROM eligible e CROSS JOIN query_vector q
ORDER BY distance ASC,e.document_id COLLATE pg_catalog."C",e.revision_id COLLATE pg_catalog."C",
 e.ordinal,e.chunk_id COLLATE pg_catalog."C"
LIMIT %s
