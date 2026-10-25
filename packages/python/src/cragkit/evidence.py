"""Bounded packing followed by assessment of only emitted source spans."""
from __future__ import annotations

import copy
import json
import math
import time
from typing import Any

from .assessment import assess_evidence
from .context import Cl100kCounter, render_context
from .errors import DeadlineExceeded, InvalidRequest
from .packing import pack_evidence


async def pack_and_assess(query: object, evidence: object, sources: object, *, deadline: float,
                          max_tokens: int, reserve: int = 256, counter: Cl100kCounter | None = None,
                          counting_mode: str = 'estimated', surrounding_bytes: int = 256,
                          policy: object = None, rebalance: bool = False) -> dict[str, Any]:
    if (type(rebalance) is not bool or type(deadline) not in (int, float)
            or not -9007199254740991 <= deadline <= 9007199254740991 or not math.isfinite(deadline)):
        raise InvalidRequest()

    def check() -> None:
        if time.monotonic() >= deadline:
            raise DeadlineExceeded()

    check()
    initial = assess_evidence(query, evidence, policy)
    # Snapshot trusted data before the first cooperative packing checkpoint.
    query = copy.deepcopy(query)
    policy = copy.deepcopy(policy)
    if type(evidence) is not list or type(sources) is not list:
        raise InvalidRequest()
    seeds = json.loads(render_context(evidence))
    source_copy = [dict(source) if type(source) is dict else source for source in sources]
    check()
    priorities = [facet['evidence_ids'] for facet in initial['facets'] if facet['required']]

    async def run(refs: list[list[str]]) -> dict[str, Any]:
        check()
        packed = await pack_evidence(seeds, source_copy, deadline=deadline, max_tokens=max_tokens,
                                     reserve=reserve, counter=counter, counting_mode=counting_mode,
                                     surrounding_bytes=surrounding_bytes, facet_evidence=refs)
        check()
        assessed = assess_evidence(query, packed['evidence'], policy)
        check()
        return {**packed, **assessed}

    selected = await run(priorities)
    attempts = 0
    unresolved = {facet['facet_id'] for facet in selected['facets']
                  if facet['required'] and facet['state'] != 'supported'}
    retry_refs = [facet['evidence_ids'] for facet in initial['facets']
                  if facet['required'] and facet['facet_id'] in unresolved and facet['evidence_ids']]
    if rebalance and policy is not None and retry_refs:
        attempts = 1
        candidate = await run(retry_refs + [facet['evidence_ids'] for facet in initial['facets']
                                           if facet['required'] and facet['facet_id'] not in unresolved])

        def score(value: dict[str, Any]) -> tuple[int, int, int]:
            required = [facet for facet in value['facets'] if facet['required']]
            return (sum(facet['state'] == 'supported' for facet in required),
                    -sum(facet['state'] == 'conflicting' for facet in required), len(value['evidence']))

        if score(candidate) > score(selected):
            selected = candidate
    check()
    return {**selected, 'rebalance_count': attempts}
