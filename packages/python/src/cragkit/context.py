"""Explicit context rendering and optional local cl100k token accounting."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path
from typing import Any
from weakref import WeakSet

from .contracts import Evidence
from .errors import ContextBudgetTooSmall, InvalidRequest, UnsupportedCapability

_RENDERER = 'cragkit.context.v2'
_SHA256 = '223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7'
_PATTERN = r"'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}++|\p{N}{1,3}+| ?[^\s\p{L}\p{N}]++[\r\n]*+|\s++$|\s*[\r\n]|\s+(?!\S)|\s"
_FIELDS = ('evidence_id', 'collection', 'document_id', 'revision_id', 'chunk_id',
           'source_locator', 'start_byte', 'end_byte', 'text', 'source_sha256', 'text_sha256')
_MAX_SAFE = 9_007_199_254_740_991
_FACTORY = object()
_ISSUED: WeakSet[Cl100kCounter] = WeakSet()


class Cl100kCounter:
    """Load a caller-supplied, pinned tokenizer asset without network access."""

    def __init__(self, encoding: Any, *, _factory: object = None) -> None:
        if _factory is not _FACTORY:
            raise UnsupportedCapability()
        self._encoding = encoding
        _ISSUED.add(self)

    @classmethod
    def from_file(cls, path: str | Path) -> Cl100kCounter:
        try:
            import tiktoken
        except ImportError:
            raise UnsupportedCapability() from None
        try:
            with Path(path).open('rb') as stream:
                data = stream.read(2_000_001)
            if len(data) > 2_000_000 or hashlib.sha256(data).hexdigest() != _SHA256:
                raise ValueError()
            ranks: dict[bytes, int] = {}
            for line in data.splitlines():
                token, rank = line.split(b' ')
                decoded = base64.b64decode(token, validate=True)
                if not decoded or not rank.isdigit() or decoded in ranks:
                    raise ValueError()
                ranks[decoded] = int(rank)
            if len(ranks) != 100_256 or set(ranks.values()) != set(range(100_256)):
                raise ValueError()
            encoding = tiktoken.Encoding(name='cl100k_base', pat_str=_PATTERN,
                                         mergeable_ranks=ranks, special_tokens={})
        except (OSError, ValueError, TypeError, binascii.Error):
            pass
        else:
            return cls(encoding, _factory=_FACTORY)
        raise InvalidRequest() from None

    def count(self, text: str) -> int:
        if type(text) is not str or len(text) > 262_144:
            raise InvalidRequest()
        try:
            if len(text.encode('utf-8', errors='strict')) > 262_144:
                raise ValueError()
            value = len(self._encoding.encode_ordinary(text))
        except (ValueError, TypeError, UnicodeError):
            pass
        else:
            if type(value) is int and 0 <= value <= _MAX_SAFE:
                return value
        raise InvalidRequest() from None


def render_context(evidence: object) -> str:
    """Render exact excerpts and source references as a compact JSON array."""
    if type(evidence) is not list or len(evidence) > 64:
        raise InvalidRequest()
    items: list[dict[str, Any]] = []
    ids: set[str] = set()
    revisions: dict[tuple[str, str, str], str] = {}
    try:
        for value in evidence:
            if type(value) is Evidence:
                value = value.model_dump(warnings=False)
            item = Evidence.model_validate(value)
            if item.evidence_id in ids:
                raise ValueError()
            ids.add(item.evidence_id)
            key = (item.collection, item.document_id, item.revision_id)
            if revisions.setdefault(key, item.source_sha256) != item.source_sha256:
                raise ValueError()
            snapshot = item.model_dump(mode='json')
            items.append({field: snapshot[field] for field in _FIELDS})
        rendered = json.dumps(items, ensure_ascii=False, separators=(',', ':'))
        if len(rendered.encode('utf-8')) > 262_144:
            raise ValueError()
    except (ValueError, TypeError, RecursionError, OverflowError):
        pass
    else:
        return rendered
    raise InvalidRequest() from None


def count_context(evidence: object, *, max_tokens: int, reserve: int = 256,
                  counter: Cl100kCounter | None = None,
                  counting_mode: str = 'estimated') -> dict[str, Any]:
    """Count the final context representation and its declared wrapper reserve."""
    if (type(max_tokens) is not int or not 1 <= max_tokens <= 1_000_000
            or type(reserve) is not int or not 0 <= reserve <= 1_000_000):
        raise InvalidRequest()
    if type(counting_mode) is not str or counting_mode not in ('estimated', 'strict'):
        raise InvalidRequest()
    if counting_mode == 'estimated' and counter is not None:
        raise InvalidRequest()
    if counting_mode == 'strict' and (type(counter) is not Cl100kCounter or counter not in _ISSUED):
        raise UnsupportedCapability()
    context = render_context(evidence)

    def count(value: str) -> int:
        if counting_mode == 'strict':
            assert counter is not None
            result = counter.count(value)
        else:
            result = (len(value.encode('utf-8')) + 3) // 4
        if type(result) is not int or not 0 <= result <= _MAX_SAFE:
            raise InvalidRequest()
        return result

    if count('[]') + reserve > max_tokens:
        raise ContextBudgetTooSmall()
    tokens = count(context)
    if tokens + reserve > max_tokens:
        raise ContextBudgetTooSmall()
    return {'context': context, 'context_tokens': tokens, 'total_tokens': tokens + reserve,
            'renderer': _RENDERER,
            'tokenizer': 'cl100k_base' if counting_mode == 'strict' else None,
            'counting_mode': counting_mode}
