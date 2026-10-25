"""Optional reranking with bounded, caller-owned asynchronous transport."""

import asyncio
import json
import math
import time
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, model_validator

from .errors import DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnsupportedCapability


class RerankProfile(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", revalidate_instances="always")
    profile_id: str
    provider: str
    model: str
    model_revision: str
    score_kind: str
    score_direction: Literal["higher_is_better", "lower_is_better"]
    preprocessing_revision: str
    truncation_policy: Literal["reject", "utf8_prefix"] = "reject"

    @model_validator(mode="after")
    def bounded(self) -> "RerankProfile":
        for value in self.model_dump().values():
            if type(value) is not str or not value.strip(" \t\r\n\v\f") or len(value.encode("utf-8")) > 256:
                raise ValueError("Invalid reranking profile")
        return self


FAKE_RERANK_PROFILE = RerankProfile(
    profile_id="fake_reranker_v1", provider="fake", model="synthetic-recorded-reranker",
    model_revision="synthetic-r1", score_kind="synthetic_raw_logit",
    score_direction="higher_is_better", preprocessing_revision="utf8-prefix-r1",
)


class RerankTransport(Protocol):
    async def __call__(self, body: bytes, *, deadline: float, max_response_bytes: int) -> bytes: ...


def _text(value: object, limit: int, *, nonempty: bool = False) -> bytes:
    if type(value) is not str or len(value) > limit or (nonempty and not value):
        raise InvalidRequest()
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        raise InvalidRequest() from None
    if len(encoded) > limit:
        raise InvalidRequest()
    return encoded


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _number(value: str) -> float:
    if len(value) > 128:
        raise ValueError("Numeric token too long")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Nonfinite score")
    return number


def _constant(value: str) -> Any:
    raise ValueError("Nonfinite JSON constant")


class RerankingAdapter:
    def __init__(self, transport: RerankTransport, *, profile: RerankProfile = FAKE_RERANK_PROFILE,
                 allow_live: bool = False) -> None:
        if type(profile) is not RerankProfile or type(allow_live) is not bool or not callable(transport):
            raise InvalidRequest()
        try:
            self._profile = RerankProfile.model_validate(profile.model_dump(warnings=False))
        except Exception:
            raise InvalidRequest() from None
        self._transport = transport
        self._allow_live = allow_live
        self._inflight = False
        self._pending: asyncio.Task[bytes] | None = None

    @property
    def profile(self) -> RerankProfile:
        """Return a validated immutable profile snapshot for request admission."""
        try:
            return RerankProfile.model_validate(self._profile.model_dump(warnings=False))
        except Exception:
            raise InvalidRequest() from None

    def _settled(self, task: asyncio.Task[bytes]) -> None:
        if not task.cancelled():
            task.exception()
        if self._pending is task:
            self._pending = None
            self._inflight = False

    @staticmethod
    def _deadline(deadline: float) -> None:
        if time.monotonic() >= deadline:
            raise DeadlineExceeded()

    def _inputs(self, query: object, candidates: object) -> tuple[str, list[dict[str, str]], list[dict[str, Any]]]:
        total = len(_text(query, 8192))
        assert isinstance(query, str)
        if not query.strip(" \t\r\n\v\f"):
            raise InvalidRequest()
        if not isinstance(candidates, (list, tuple)) or type(candidates) not in (list, tuple) or len(candidates) > 40:
            raise InvalidRequest()
        views: list[dict[str, str]] = []
        truncations: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in candidates:
            if type(row) is not dict or len(row) != 2 or set(row) != {"candidate_id", "text"}:
                raise InvalidRequest()
            identity = row["candidate_id"]
            _text(identity, 512, nonempty=True)
            if identity in seen:
                raise InvalidRequest()
            seen.add(identity)
            text = row["text"]
            # The aggregate ceiling also bounds work before allocating an encoded view.
            raw = _text(text, 262144)
            if len(raw) > 16384:
                if self._profile.truncation_policy != "utf8_prefix":
                    raise InvalidRequest()
                view = raw[:16384].decode("utf-8", errors="ignore")
                view_size = len(view.encode("utf-8"))
                truncations.append({"candidate_id": identity, "original_bytes": len(raw), "view_bytes": view_size})
            else:
                view, view_size = text, len(raw)
            total += view_size
            if total > 262144:
                raise InvalidRequest()
            views.append({"candidate_id": identity, "text": view})
        assert isinstance(query, str)
        return query, views, truncations

    def _scores(self, raw: object, candidates: list[dict[str, str]]) -> list[dict[str, Any]]:
        try:
            if type(raw) is not bytes or len(raw) > 65536:
                raise ValueError("Invalid response bytes")
            parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                                parse_int=_number, parse_float=_number, parse_constant=_constant)
            if type(parsed) is not list or len(parsed) != len(candidates):
                raise ValueError("Incomplete score mapping")
            expected = {row["candidate_id"] for row in candidates}
            scores: dict[str, float] = {}
            for row in parsed:
                if type(row) is not dict or set(row) != {"candidate_id", "raw_score"}:
                    raise ValueError("Invalid score row")
                identity, score = row["candidate_id"], row["raw_score"]
                _text(identity, 512, nonempty=True)
                if identity not in expected or identity in scores or type(score) is not float or not math.isfinite(score):
                    raise ValueError("Invalid score mapping")
                scores[identity] = score
            return [{"candidate_id": row["candidate_id"], "raw_score": scores[row["candidate_id"]]} for row in candidates]
        except Exception:
            raise IntegrityViolation() from None

    async def rank(self, query: str, candidates: list[dict[str, str]] | tuple[dict[str, str], ...], *,
                   deadline: float, max_provider_calls: int = 1, allow_fallback: bool = False) -> dict[str, Any]:
        if type(deadline) not in (int, float) or type(max_provider_calls) is not int or not 0 <= max_provider_calls <= 1000 or type(allow_fallback) is not bool:
            raise InvalidRequest()
        try:
            valid_deadline = math.isfinite(deadline)
        except (OverflowError, ValueError):
            valid_deadline = False
        if not valid_deadline:
            raise InvalidRequest()
        self._deadline(deadline)
        if self._inflight:
            raise InvalidRequest()
        self._inflight = True
        try:
            try:
                if type(self._profile) is not RerankProfile:
                    raise InvalidRequest()
                profile = RerankProfile.model_validate(self._profile.model_dump(warnings=False))
            except Exception:
                raise InvalidRequest() from None
            query_view, views, truncations = self._inputs(query, candidates)
            self._deadline(deadline)
            result: dict[str, Any] = {
                "profile": profile.model_dump(), "order": [row["candidate_id"] for row in views],
                "scores": [], "truncations": truncations, "degraded": False, "provider_calls": 0,
                "synthetic": profile.provider == "fake",
            }
            if not views:
                return result
            if max_provider_calls == 0:
                raise InvalidRequest()
            if profile.provider != "fake" and not self._allow_live:
                raise UnsupportedCapability()
            body = json.dumps({"profile": profile.model_dump(), "query": query_view, "candidates": views},
                              ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._deadline(deadline)
            result["provider_calls"] = 1
            async def invoke() -> bytes:
                self._deadline(deadline)
                return await self._transport(body, deadline=deadline, max_response_bytes=65536)

            task = asyncio.create_task(invoke())
            self._pending = task
            task.add_done_callback(self._settled)
            try:
                done, _ = await asyncio.wait({task}, timeout=max(0.0, deadline - time.monotonic()))
                if not done:
                    task.cancel()
                    raise DeadlineExceeded()
                raw = task.result()
            except asyncio.CancelledError:
                task.cancel()
                raise
            except TimeoutError:
                raise DeadlineExceeded() from None
            except (ProviderUnavailable, UnsupportedCapability):
                self._deadline(deadline)
                if not allow_fallback:
                    raise
                result["degraded"] = True
                return result
            self._deadline(deadline)
            scores = self._scores(raw, views)
            ordered = sorted(scores, key=lambda row: row["raw_score"], reverse=profile.score_direction == "higher_is_better")
            result["scores"] = scores
            result["order"] = [row["candidate_id"] for row in ordered]
            self._deadline(deadline)
            return result
        finally:
            if self._pending is None or self._pending.done():
                self._pending = None
                self._inflight = False
