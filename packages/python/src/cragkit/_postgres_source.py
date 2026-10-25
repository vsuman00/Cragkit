"""Verify authorized canonical spans without exposing full sources in results."""
from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, PrivateAttr, ValidationError

from .contracts import Evidence
from .errors import IntegrityViolation, InvalidRequest, UnsupportedCapability

if TYPE_CHECKING:
    from ._postgres_session import LexicalCandidate


_SOURCE_SQL = """
SELECT c.tenant_id,c.collection_id,c.document_id,c.revision_id,c.generation_id,c.chunk_id,
 r.canonical_sha256,octet_length(r.canonical_text),
 CASE WHEN octet_length(r.canonical_text)<=%s AND octet_length(r.canonical_text)<=16777216
      THEN r.canonical_text ELSE NULL END,
 c.start_byte,c.end_byte,octet_length(c.text),
 CASE WHEN octet_length(c.text)<=32768 THEN c.text ELSE NULL END,
 c.text_sha256,r.source_locator,g.lexical_profile,
 (d.active_generation_id IS NOT DISTINCT FROM g.generation_id)
FROM cragkit.documents d
JOIN cragkit.index_generations g ON g.tenant_id=d.tenant_id AND g.collection_id=d.collection_id
 AND g.document_id=d.document_id
JOIN cragkit.document_revisions r ON r.tenant_id=g.tenant_id AND r.collection_id=g.collection_id
 AND r.document_id=g.document_id AND r.revision_id=g.revision_id
JOIN cragkit.chunks c ON c.tenant_id=g.tenant_id AND c.collection_id=g.collection_id
 AND c.document_id=g.document_id AND c.revision_id=g.revision_id AND c.generation_id=g.generation_id
WHERE c.tenant_id=%s AND c.collection_id=%s AND c.document_id=%s AND c.revision_id=%s
 AND c.generation_id=%s AND c.chunk_id=%s
 AND d.tenant_id=%s AND d.collection_id=%s AND NOT d.tombstoned
 AND d.authorization_revision=%s AND g.status='ready'
 AND EXISTS(SELECT 1 FROM cragkit.document_grants x WHERE x.tenant_id=d.tenant_id AND x.collection_id=d.collection_id
  AND x.document_id=d.document_id AND x.authorization_revision=%s
  AND (x.principal_id=%s OR (x.principal_id IS NULL AND x.grant_id=ANY(%s::text[]))))
 AND ({predicate})
"""


class SourceFetch(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')
    state: Literal['verified', 'unavailable', 'budget_exhausted']
    evidence: Evidence | None = None
    source_bytes: int = 0
    stale: bool = False
    _canonical_text: str | None = PrivateAttr(default=None)

    def source_snapshot(self) -> dict[str, str]:
        if self.state != 'verified' or self.evidence is None or self._canonical_text is None:
            raise UnsupportedCapability()
        return {'collection': self.evidence.collection, 'document_id': self.evidence.document_id,
                'revision_id': self.evidence.revision_id, 'source_sha256': self.evidence.source_sha256,
                'text': self._canonical_text}


def _integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise IntegrityViolation()
    return value


def _text(value: object, maximum: int, *, nonblank: bool = False) -> str:
    if type(value) is not str:
        raise IntegrityViolation()
    assert isinstance(value, str)
    failed = False
    try:
        failed = (len(value) > maximum or len(value.encode('utf-8')) > maximum
                  or '\0' in value or (nonblank and not value.strip(' \t\r\n\f\v')))
    except UnicodeError:
        failed = True
    if failed:
        raise IntegrityViolation()
    return value


def verify_source(candidate: LexicalCandidate, rows: list[tuple[object, ...]],
                  max_source_bytes: int, *, include_source: bool = False) -> SourceFetch:
    if type(include_source) is not bool:
        raise InvalidRequest()
    if not rows:
        return SourceFetch(state='unavailable')
    if len(rows) != 1 or len(rows[0]) != 17:
        raise IntegrityViolation()
    row = rows[0]
    identity = (candidate.tenant_id, candidate.collection, candidate.document_id,
                candidate.revision_id, candidate.generation_id, candidate.chunk_id)
    if row[:6] != identity or any(type(value) is not str for value in row[:6]):
        raise IntegrityViolation()
    canonical_digest = _text(row[6], 64)
    text_digest = _text(row[13], 64)
    if not re.fullmatch('[0-9a-f]{64}', canonical_digest) or not re.fullmatch('[0-9a-f]{64}', text_digest):
        raise IntegrityViolation()
    source_bytes = _integer(row[7], 1, 16_777_216)
    start = _integer(row[9], 0, source_bytes)
    end = _integer(row[10], start + 1, source_bytes)
    chunk_bytes = _integer(row[11], 1, 32_768)
    excerpt = _text(row[12], 32_768)
    locator = _text(row[14], 256, nonblank=True)
    if row[15] != 'native_fts.v1':
        raise UnsupportedCapability()
    if type(row[16]) is not bool:
        raise IntegrityViolation()
    encoded_excerpt = excerpt.encode('utf-8')
    if (end - start != chunk_bytes or len(encoded_excerpt) != chunk_bytes
            or sha256(encoded_excerpt).hexdigest() != text_digest
            or (start, end, text_digest) != (candidate.start_byte, candidate.end_byte, candidate.text_sha256)):
        raise IntegrityViolation()
    if source_bytes > max_source_bytes:
        if row[8] is not None:
            raise IntegrityViolation()
        return SourceFetch(state='budget_exhausted')
    canonical = _text(row[8], source_bytes)
    canonical_bytes = canonical.encode('utf-8')
    if len(canonical_bytes) != source_bytes or sha256(canonical_bytes).hexdigest() != canonical_digest:
        raise IntegrityViolation()
    invalid_slice = False
    try:
        invalid_slice = canonical_bytes[start:end].decode('utf-8', errors='strict') != excerpt
    except UnicodeError:
        invalid_slice = True
    if invalid_slice or canonical_bytes[start:end] != encoded_excerpt:
        raise IntegrityViolation()
    evidence_id = sha256(json.dumps(['cragkit.evidence.v1', *identity[:4], identity[5],
        str(start), str(end), text_digest], ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    evidence = None
    try:
        evidence = Evidence.model_validate({'evidence_id': evidence_id, 'collection': candidate.collection,
            'document_id': candidate.document_id, 'revision_id': candidate.revision_id, 'chunk_id': candidate.chunk_id,
            'source_locator': locator, 'start_byte': start, 'end_byte': end, 'text': excerpt,
            'source_sha256': canonical_digest, 'text_sha256': text_digest})
    except (ValidationError, ValueError, TypeError):
        pass
    if evidence is None:
        raise IntegrityViolation()
    result = SourceFetch(state='verified', evidence=evidence, source_bytes=source_bytes, stale=not row[16])
    if include_source:
        result._canonical_text = canonical
    return result
