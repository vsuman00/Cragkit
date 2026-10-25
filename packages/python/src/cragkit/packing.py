"""Bounded extractive packing of caller-authorized immutable source bytes."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any

from .context import Cl100kCounter, count_context
from .contracts import Evidence
from .contracts._validation import identity
from .contracts.results import digest
from .errors import ContextBudgetTooSmall, DeadlineExceeded, IntegrityViolation, InvalidRequest

_DEFAULT_FACETS: list[list[str]] = []

@dataclass
class _Group:
    source: tuple[str, str, str]
    start: int
    end: int
    seeds: list[int]


def _fenced_spans(data: bytes) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    opening: tuple[bytes, int, int] | None = None
    offset = 0
    for line in data.split(b'\n'):
        match = re.match(rb'^ {0,3}(`{3,}|~{3,})(.*)$', line.rstrip(b'\r'))
        if match:
            marker, tail = match.groups()
            if opening is None:
                opening = (marker[:1], len(marker), offset)
            elif marker[:1] == opening[0] and len(marker) >= opening[1] and not tail.strip(b' \t'):
                spans.append((opening[2], offset + len(line)))
                opening = None
        offset += len(line) + 1
    if opening is not None:
        spans.append((opening[2], len(data)))
    return spans


async def pack_evidence(evidence: object, sources: object, *, deadline: float,
                        max_tokens: int, reserve: int = 256,
                        counter: Cl100kCounter | None = None,
                        counting_mode: str = 'estimated', surrounding_bytes: int = 256,
                        facet_evidence: object = _DEFAULT_FACETS) -> dict[str, Any]:
    """Pack complete spans; authorization and coverage assessment belong to callers."""
    if (type(deadline) not in (int, float) or not -9_007_199_254_740_991 <= deadline <= 9_007_199_254_740_991 or not math.isfinite(deadline)
            or type(surrounding_bytes) is not int or not 0 <= surrounding_bytes <= 4096
            or type(evidence) is not list or len(evidence) > 64
            or type(sources) is not list or len(sources) > 64):
        raise InvalidRequest()

    def check() -> None:
        if time.monotonic() >= deadline:
            raise DeadlineExceeded()

    async def checkpoint() -> None:
        await asyncio.sleep(0)
        check()

    check()
    counted = count_context([], max_tokens=max_tokens, reserve=reserve, counter=counter,
                            counting_mode=counting_mode)
    parsed: list[Evidence] = []
    ids: set[str] = set()
    try:
        for value in evidence:
            if type(value) is Evidence:
                value = value.model_dump(warnings=False)
            item = Evidence.model_validate(value)
            if item.evidence_id in ids:
                raise ValueError()
            ids.add(item.evidence_id)
            parsed.append(item)
        facets = facet_evidence
        if type(facets) is not list or len(facets) > 32:
            raise ValueError()
        for facet in facets:
            if (type(facet) is not list or len(facet) > 64
                    or any(type(ref) is not str or ref not in ids for ref in facet)
                    or len(set(facet)) != len(facet)):
                raise ValueError()
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise InvalidRequest() from None

    facets = [list(facet) for facet in facets]
    sources = [dict(source) if type(source) is dict else source for source in sources]
    used_ids = set(ids)
    source_map: dict[tuple[str, str, str], tuple[str, bytes]] = {}
    fences: dict[tuple[str, str, str], list[tuple[int, int]]] = {}
    total_bytes = 0
    for value in sources:
        check()
        try:
            if type(value) is not dict or len(value) != 5 or set(value) != {
                'collection', 'document_id', 'revision_id', 'source_sha256', 'text'
            }:
                raise ValueError()
            for field in ('collection', 'document_id', 'revision_id'):
                if type(value[field]) is not str:
                    raise ValueError()
                identity(value[field])
            if type(value['source_sha256']) is not str or type(value['text']) is not str:
                raise ValueError()
            digest(value['source_sha256'])
            if len(value['text']) > 16_777_216:
                raise ValueError()
            encoded = value['text'].encode('utf-8', errors='strict')
            total_bytes += len(encoded)
            if total_bytes > 16_777_216:
                raise ValueError()
        except (ValueError, TypeError, UnicodeError):
            raise InvalidRequest() from None
        key = (value['collection'], value['document_id'], value['revision_id'])
        record = (value['source_sha256'], encoded)
        if (hashlib.sha256(encoded).hexdigest() != record[0]
                or (key in source_map and source_map[key] != record)):
            raise IntegrityViolation()
        source_map[key] = record
        fences[key] = _fenced_spans(encoded)
        await checkpoint()

    intervals: list[_Group] = []
    locators: dict[tuple[str, str, str], str] = {}
    for index, item in enumerate(parsed):
        check()
        key = (item.collection, item.document_id, item.revision_id)
        source = source_map.get(key)
        if (source is None or source[0] != item.source_sha256
                or source[1][item.start_byte:item.end_byte] != item.text.encode('utf-8')
                or locators.setdefault(key, item.source_locator) != item.source_locator):
            raise IntegrityViolation()
        data = source[1]
        start, end = item.start_byte, item.end_byte
        if surrounding_bytes:
            left = data.rfind(b'\n\n', max(0, start - surrounding_bytes), start)
            if left >= 0:
                start = left + 2
            elif start <= surrounding_bytes:
                start = 0
            right = data.find(b'\n\n', end)
            if right >= 0 and right <= end + surrounding_bytes:
                end = right
            elif len(data) - end <= surrounding_bytes:
                end = len(data)
        for fence_start, fence_end in fences[key]:
            if fence_start <= item.start_byte and item.end_byte <= fence_end:
                if (item.start_byte - fence_start <= surrounding_bytes
                        and fence_end - item.end_byte <= surrounding_bytes):
                    start, end = fence_start, fence_end
                break
        # Include an immediately preceding Markdown heading when it fits.
        if start > 0 and surrounding_bytes:
            before = data[:start].rstrip(b'\n')
            heading_start = before.rfind(b'\n') + 1
            heading = before[heading_start:]
            if re.match(rb'^ {0,3}#{1,6}[ \t]+', heading) and item.start_byte - heading_start <= surrounding_bytes:
                start = heading_start
        intervals.append(_Group(key, start, end, [index]))
    intervals.sort(key=lambda group: (group.source, group.start, group.end))
    groups: list[_Group] = []
    for group in intervals:
        if groups and groups[-1].source == group.source and group.start <= groups[-1].end:
            previous = groups[-1]
            previous.end = max(previous.end, group.end)
            previous.seeds.extend(group.seeds)
        else:
            groups.append(group)
    groups.sort(key=lambda group: min(group.seeds))
    group_ids = [{parsed[index].evidence_id for index in group.seeds} for group in groups]
    priority: list[int] = []
    for facet in facets:
        refs = set(facet)
        if any(group_ids[index] & refs for index in priority):
            continue
        for index, members in enumerate(group_ids):
            if members & refs:
                priority.append(index)
                break
    priority.extend(index for index in range(len(groups)) if index not in priority)
    emitted: list[dict[str, Any]] = []
    aliases: dict[str, list[str]] = {}
    expanded = merged = 0
    for index in priority:
        await checkpoint()
        group = groups[index]
        if group.end - group.start > 32_768:
            continue
        group.seeds.sort()
        first = parsed[group.seeds[0]]
        unchanged = (len(group.seeds) == 1 and group.start == first.start_byte
                     and group.end == first.end_byte)
        span_id = first.evidence_id
        if not unchanged:
            payload = [*group.source, first.source_sha256, group.start, group.end]
            span_id = 'span-' + hashlib.sha256(json.dumps(
                payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
        if not unchanged:
            base_id = span_id
            suffix = 1
            while span_id in used_ids:
                span_id = f'{base_id}-{suffix}'
                suffix += 1
        text = source_map[group.source][1][group.start:group.end].decode('utf-8')
        candidate = first.model_dump(mode='json')
        candidate.update(evidence_id=span_id, chunk_id=first.chunk_id if unchanged else span_id,
                         start_byte=group.start, end_byte=group.end, text=text,
                         text_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest())
        proposal = [*emitted, candidate]
        if len(json.dumps(proposal, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) > 262_144:
            continue
        try:
            result = count_context(proposal, max_tokens=max_tokens, reserve=reserve,
                                   counter=counter, counting_mode=counting_mode)
        except ContextBudgetTooSmall:
            continue
        check()
        used_ids.add(span_id)
        emitted = proposal
        counted = result
        aliases[span_id] = [parsed[seed].evidence_id for seed in group.seeds]
        merged += len(group.seeds) - 1
        expanded += int(group.start < min(parsed[seed].start_byte for seed in group.seeds)
                        or group.end > max(parsed[seed].end_byte for seed in group.seeds))
    await checkpoint()
    return {'evidence': emitted, **counted, 'omitted_count': len(parsed) - sum(map(len, aliases.values())),
            'merged_count': merged, 'expanded_count': expanded, 'aliases': aliases}
