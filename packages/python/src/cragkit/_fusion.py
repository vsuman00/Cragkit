"""Bounded deterministic weighted reciprocal rank fusion (IF-r1)."""
from __future__ import annotations

import math
import re
from typing import Any

from pydantic import ValidationError

from ._postgres_session import DenseCandidate, IdentifierCandidate, LexicalCandidate
from .contracts._validation import native_json
from .errors import IntegrityViolation, InvalidRequest

_ID = ('tenant_id', 'collection', 'document_id', 'revision_id', 'chunk_id')
_IMMUTABLE = ('generation_id', 'start_byte', 'end_byte', 'text_sha256')
_MODELS = {'dense': DenseCandidate, 'lexical': LexicalCandidate, 'identifier': IdentifierCandidate}


def _ascii(value: object) -> bool:
    return type(value) is str and bool(re.fullmatch(r'[!-~]{1,128}', value))


def _candidate(value: object, family: str) -> dict[str, Any]:
    model = _MODELS[family]
    try:
        native_json(value)
        if type(value) is not dict or set(value) != set(model.model_fields):
            raise ValueError()
        if type(value['score']) not in (int, float):
            raise ValueError()
        parsed = model.model_validate(value).model_dump(mode='json')
        for field in (*_ID, 'generation_id'):
            text = parsed[field]
            if not text.strip(' \t\r\n\f\v') or '\0' in text or len(text.encode('utf-8')) > (128 if field == 'collection' else 256):
                raise ValueError()
        if parsed['end_byte'] <= parsed['start_byte']:
            raise ValueError()
        return parsed
    except (ValueError, TypeError, ValidationError, UnicodeError):
        raise InvalidRequest() from None


def fuse(lists: object, *, k: int = 60, max_candidates: int = 200) -> list[dict[str, Any]]:
    """Snapshot validated branch lists and return ranking values with provenance."""
    if type(k) is not int or not 0 <= k <= 1_000_000 or type(max_candidates) is not int or not 1 <= max_candidates <= 1000:
        raise InvalidRequest()
    if type(lists) is not list or len(lists) > 36:
        raise InvalidRequest()
    snapshots = []
    ids: set[str] = set()
    weights: dict[tuple[str, str], float] = {}
    for branch in lists:
        if type(branch) is not dict or set(branch) != {'list_id', 'facet_id', 'family', 'weight', 'candidates'}:
            raise InvalidRequest()
        lid, facet, family, weight = (branch[key] for key in ('list_id', 'facet_id', 'family', 'weight'))
        if not _ascii(lid) or not _ascii(facet) or type(family) is not str or family not in _MODELS or lid in ids:
            raise InvalidRequest()
        if type(weight) not in (int, float) or not 0 < weight <= 1e6 or not math.isfinite(weight):
            raise InvalidRequest()
        candidates = branch['candidates']
        if type(candidates) is not list or len(candidates) > 1000:
            raise InvalidRequest()
        key = (facet, family)
        if key in weights and weights[key] != weight:
            raise InvalidRequest()
        weights[key] = weight
        ids.add(lid)
        snapshots.append((lid, facet, family, [_candidate(item, family) for item in candidates]))
    representatives: dict[tuple[str, ...], dict[str, Any]] = {}
    votes: dict[tuple[str, ...], dict[tuple[str, str], tuple[int, str, dict[str, Any]]]] = {}
    for lid, facet, family, candidates in sorted(snapshots):
        seen: set[tuple[str, ...]] = set()
        for candidate in candidates:
            identity = tuple(candidate[field] for field in _ID)
            previous = representatives.get(identity)
            if previous is not None and any(previous[field] != candidate[field] for field in _IMMUTABLE):
                raise IntegrityViolation()
            if previous is None:
                representatives[identity] = candidate
                votes[identity] = {}
                if len(representatives) > max_candidates:
                    raise InvalidRequest()
            if identity in seen:
                continue
            seen.add(identity)
            vote = (len(seen), lid, candidate)
            old = votes[identity].get((facet, family))
            if old is None or vote[:2] < old[:2]:
                votes[identity][(facet, family)] = vote
    totals: dict[str, float] = {}
    for (facet, _family), weight in sorted(weights.items()):
        totals[facet] = totals.get(facet, 0) + weight
    results = []
    for identity, candidate in representatives.items():
        contributions = []
        score = 0.0
        for (facet, family), (rank, lid, source) in sorted(votes[identity].items()):
            weight = weights[(facet, family)] / totals[facet]
            contribution = weight / (k + rank)
            if weight == 0 or contribution == 0:
                raise InvalidRequest()
            score += contribution
            contributions.append(dict(facet_id=facet, family=family, weight=weight, rank=rank, list_id=lid,
                                      raw_score=source['score'], score_direction=source.get('score_direction', 'higher_is_better'),
                                      profile=source.get('embedding_profile', source.get('identifier_profile', 'native_fts.v1'))))
        results.append(dict(candidate=candidate, score=score, contributions=contributions))
    return sorted(results, key=lambda item: (-item['score'], tuple(item['candidate'][field].encode('utf-8') for field in _ID)))
