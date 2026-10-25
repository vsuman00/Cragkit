"""Conservative assessment against trusted, query-bound reviewed source spans."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .context import render_context
from .contracts import Facet
from .contracts._validation import MAX_SAFE_NUMBER, identity, integer, native_json, text
from .contracts.results import digest
from .errors import InvalidRequest


def _shape(value: Any, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError()
    return value


def _string(value: Any, limit: int = 256) -> str:
    if type(value) is not str:
        raise ValueError()
    return text(value, limit)


def _policy(value: Any, query: str) -> dict[str, Any]:
    native_json(value)
    value = _shape(value, {'policy_id', 'version', 'query_sha256', 'facets'})
    policy_id, version = _string(value['policy_id']), _string(value['version'])
    identity(policy_id + ':' + version)
    bound = _string(value['query_sha256'])
    digest(bound)
    if bound != hashlib.sha256(query.encode('utf-8')).hexdigest():
        raise ValueError()
    raw_facets = value['facets']
    if type(raw_facets) is not list or not 1 <= len(raw_facets) <= 32:
        raise ValueError()
    facets: list[dict[str, Any]] = []
    facet_ids: set[str] = set()
    anchor_count = anchor_bytes = 0
    for raw in raw_facets:
        facet = _shape(raw, {'facet_id', 'question', 'required', 'absence', 'anchors'})
        fid, question = _string(facet['facet_id']), _string(facet['question'], 2048)
        if fid in facet_ids or type(facet['required']) is not bool or facet['absence'] not in ('missing', 'unknown'):
            raise ValueError()
        facet_ids.add(fid)
        if type(facet['anchors']) is not list or len(facet['anchors']) > 16:
            raise ValueError()
        anchors = []
        seen: set[tuple[Any, ...]] = set()
        for raw_anchor in facet['anchors']:
            anchor = _shape(raw_anchor, {'claim_id', 'collection', 'document_id', 'revision_id',
                                         'source_sha256', 'start_byte', 'end_byte', 'text'})
            copied = {key: _string(anchor[key]) for key in
                      ('claim_id', 'collection', 'document_id', 'revision_id', 'source_sha256')}
            digest(copied['source_sha256'])
            start, end = integer(anchor['start_byte']), integer(anchor['end_byte'])
            if (type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= MAX_SAFE_NUMBER):
                raise ValueError()
            if type(anchor['text']) is not str:
                raise ValueError()
            encoded = text(anchor['text'], 32768, nonblank=False).encode('utf-8')
            if len(encoded) != end - start:
                raise ValueError()
            result = {**copied, 'start_byte': start, 'end_byte': end, 'text': anchor['text']}
            key = tuple(result.values())
            if key in seen:
                raise ValueError()
            seen.add(key)
            anchors.append(result)
            anchor_count += 1
            anchor_bytes += len(encoded)
            if anchor_count > 64 or anchor_bytes > 262144:
                raise ValueError()
        facets.append(dict(facet_id=fid, question=question, required=facet['required'],
                           absence=facet['absence'], anchors=anchors))
    return dict(policy_id=policy_id, version=version, facets=facets)


def validate_assessment(evidence: object, facets: object) -> list[dict[str, Any]]:
    """Copy valid wire facets and reject references outside emitted evidence."""
    emitted = json.loads(render_context(evidence))
    try:
        if type(facets) is not list or len(facets) > 32:
            raise ValueError()
        evidence_ids = {item['evidence_id'] for item in emitted}
        result = []
        seen: set[str] = set()
        for raw in facets:
            if type(raw) is Facet:
                raw = raw.model_dump(mode='json', warnings=False)
            facet = Facet.model_validate(raw)
            if facet.facet_id in seen or not set(facet.evidence_ids) <= evidence_ids:
                raise ValueError()
            seen.add(facet.facet_id)
            result.append(facet.model_dump(mode='json'))
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise InvalidRequest() from None
    return result


def assess_evidence(query: object, evidence: object, policy: object = None) -> dict[str, Any]:
    """Assess exact emitted spans without a provider call or source fetch."""
    emitted = json.loads(render_context(evidence))
    try:
        query_text = _string(query, 16384)
        configured = None if policy is None else _policy(policy, query_text)
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise InvalidRequest() from None
    if configured is None:
        facets = [dict(facet_id='query', question='Original query', state='unknown', required=True,
                       evidence_ids=[], assessment_method='none', assessment_version='0')]
        return dict(facets=facets, status='partial' if emitted else 'insufficient', policy='unassessed.v0')
    facets = []
    for facet in configured['facets']:
        declared = {anchor['claim_id'] for anchor in facet['anchors']}
        claims: set[str] = set()
        refs = []
        for item in emitted:
            matched = False
            for anchor in facet['anchors']:
                if (all(item[key] == anchor[key] for key in
                        ('collection', 'document_id', 'revision_id', 'source_sha256'))
                        and item['start_byte'] <= anchor['start_byte']
                        and item['end_byte'] >= anchor['end_byte']):
                    start = anchor['start_byte'] - item['start_byte']
                    end = anchor['end_byte'] - item['start_byte']
                    if item['text'].encode('utf-8')[start:end] == anchor['text'].encode('utf-8'):
                        claims.add(anchor['claim_id'])
                        matched = True
            if matched:
                refs.append(item['evidence_id'])
        state = facet['absence']
        if claims:
            state = ('conflicting' if len(claims) >= 2 and len(refs) >= 2 else
                     'supported' if len(declared) == 1 else 'unknown')
        facets.append(dict(facet_id=facet['facet_id'], question=facet['question'], state=state,
                           required=facet['required'], evidence_ids=refs,
                           assessment_method='reviewed-span', assessment_version=configured['version']))
    validated = validate_assessment(emitted, facets)
    required = [facet for facet in validated if facet['required']]
    sufficient = bool(emitted and required and all(facet['state'] == 'supported' for facet in required))
    return dict(facets=validated, status='sufficient' if sufficient else 'partial' if emitted else 'insufficient',
                policy=configured['policy_id'] + ':' + configured['version'])
