"""Optional bounded embeddings with caller-owned transport and token counting."""

import asyncio
import json
import math
import time
from decimal import Context, Decimal, localcontext
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import (
    DeadlineExceeded, EmbeddingProfileMismatch, InvalidRequest,
    ProviderUnavailable, UnsupportedCapability,
)


class _Model(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", revalidate_instances="always")


class EmbeddingProfile(_Model):
    profile_id: str
    provider: str
    model: str
    dimensions: int
    tokenizer: str
    normalization: str

    @model_validator(mode="after")
    def supported(self) -> "EmbeddingProfile":
        identity = (self.profile_id, self.provider, self.model, self.dimensions, self.tokenizer, self.normalization)
        if identity not in (
            ("openai_te3small_1536_r1", "openai", "text-embedding-3-small", 1536, "cl100k_base", "l2"),
            ("fake_embedding_1536_v1", "fake", "fake_embedding_model_v1", 1536, "fake-byte-v1", "l2"),
        ):
            raise ValueError("Unsupported embedding profile")
        return self


OPENAI_PROFILE = EmbeddingProfile(profile_id="openai_te3small_1536_r1", provider="openai", model="text-embedding-3-small", dimensions=1536, tokenizer="cl100k_base", normalization="l2")
FAKE_PROFILE = EmbeddingProfile(profile_id="fake_embedding_1536_v1", provider="fake", model="fake_embedding_model_v1", dimensions=1536, tokenizer="fake-byte-v1", normalization="l2")


class EmbeddingLimits(_Model):
    max_items: Annotated[int, Field(gt=0, le=8)] = 8
    max_input_bytes: Annotated[int, Field(gt=0, le=8192)] = 8192
    max_batch_bytes: Annotated[int, Field(gt=0, le=32768)] = 32768
    max_input_tokens: Annotated[int, Field(gt=0, le=8192)] = 2048
    max_batch_tokens: Annotated[int, Field(gt=0, le=32768)] = 8192
    max_response_bytes: Annotated[int, Field(gt=0, le=2097152)] = 1048576


class EmbeddingPolicy(_Model):
    allow_live: bool = False
    max_cost_usd: Annotated[float, Field(ge=0, le=1000000, allow_inf_nan=False)] = 0.0
    usd_per_million_tokens: Annotated[float, Field(gt=0, le=1000000, allow_inf_nan=False)] | None = None


class TokenCounter(Protocol):
    name: str

    def count(self, text: str) -> int: ...


class EmbeddingTransport(Protocol):
    async def __call__(self, body: bytes, *, deadline: float, max_response_bytes: int) -> bytes: ...


class EmbeddingUsage(_Model):
    prompt_tokens: int | None
    total_tokens: int | None
    cost_usd: float | None
    cost_kind: Literal["known", "estimated", "unknown"]


class EmbeddingBatch(_Model):
    profile: EmbeddingProfile
    vectors: tuple[tuple[float, ...], ...]
    usage: EmbeddingUsage
    provider_calls: Literal[1] = 1
    synthetic: bool


def _configuration(model: type[_Model], value: object) -> Any:
    result = None
    try:
        if type(value) is model:
            result = model.model_validate(value.model_dump(warnings=False))
    except Exception:
        pass
    if result is None:
        raise InvalidRequest()
    return result


def _integer(value: object, *, positive: bool = False) -> bool:
    return type(value) is int and (1 if positive else 0) <= value <= 2147483647


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> Any:
    raise ValueError("Invalid JSON constant")


class EmbeddingAdapter:
    def __init__(
        self, transport: EmbeddingTransport, token_counter: TokenCounter, *,
        profile: EmbeddingProfile = FAKE_PROFILE, limits: EmbeddingLimits | None = None,
        policy: EmbeddingPolicy | None = None,
    ) -> None:
        self.profile: EmbeddingProfile = _configuration(EmbeddingProfile, profile)
        self.limits: EmbeddingLimits = _configuration(EmbeddingLimits, limits if limits is not None else EmbeddingLimits())
        self.policy: EmbeddingPolicy = _configuration(EmbeddingPolicy, policy if policy is not None else EmbeddingPolicy())
        valid = False
        name: object = None
        try:
            valid = callable(transport) and callable(token_counter.count)
            name = token_counter.name
        except Exception:
            pass
        if not valid or type(name) is not str:
            raise InvalidRequest()
        if name != self.profile.tokenizer:
            raise UnsupportedCapability()
        self._transport = transport
        self._counter = token_counter
        self._inflight = False

    def _check_deadline(self, deadline: float) -> None:
        if time.monotonic() >= deadline:
            raise DeadlineExceeded()

    def _inputs(self, texts: object) -> tuple[tuple[str, ...], int]:
        if not isinstance(texts, (list, tuple)) or type(texts) not in (list, tuple):
            raise InvalidRequest()
        if not texts or len(texts) > self.limits.max_items:
            raise InvalidRequest()
        snapshot = tuple(texts)
        total_bytes = total_tokens = 0
        for text in snapshot:
            if type(text) is not str or not text or len(text) > self.limits.max_input_bytes:
                raise InvalidRequest()
            size: int | None = None
            count: object = None
            try:
                size = len(text.encode("utf-8"))
                if size <= self.limits.max_input_bytes:
                    count = self._counter.count(text)
            except Exception:
                pass
            if size is None or size > self.limits.max_input_bytes or not _integer(count, positive=True):
                raise InvalidRequest()
            assert isinstance(count, int)
            total_bytes += size
            total_tokens += count
            if count > self.limits.max_input_tokens or total_bytes > self.limits.max_batch_bytes or total_tokens > self.limits.max_batch_tokens:
                raise InvalidRequest()
        return snapshot, total_tokens

    def _cost(self, tokens: int) -> Decimal:
        assert self.policy.usd_per_million_tokens is not None
        with localcontext(Context(prec=50)):
            return Decimal(tokens) * Decimal(str(self.policy.usd_per_million_tokens)) / Decimal(1000000)

    def _response(self, raw: object, size: int, counted: int) -> EmbeddingBatch:
        parsed: Any = None
        try:
            if type(raw) is bytes and len(raw) <= self.limits.max_response_bytes:
                parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
        except Exception:
            pass
        if type(parsed) is not dict:
            raise ProviderUnavailable()
        if parsed.get("model") != self.profile.model:
            raise EmbeddingProfileMismatch()
        data = parsed.get("data")
        if type(data) is not list or len(data) != size:
            raise ProviderUnavailable()
        ordered: dict[int, tuple[float, ...]] = {}
        for item in data:
            if type(item) is not dict:
                raise ProviderUnavailable()
            index = item.get("index")
            vector = item.get("embedding")
            if type(index) is not int or index < 0 or index >= size or index in ordered:
                raise ProviderUnavailable()
            if type(vector) is not list:
                raise ProviderUnavailable()
            if len(vector) != self.profile.dimensions:
                raise EmbeddingProfileMismatch()
            converted: list[float] = []
            valid = True
            try:
                for component in vector:
                    if type(component) not in (int, float):
                        valid = False
                        break
                    number = float(component)
                    if not math.isfinite(number):
                        valid = False
                        break
                    converted.append(number)
            except (ValueError, OverflowError):
                valid = False
            if not valid:
                raise ProviderUnavailable()
            norm = math.sqrt(sum(value * value for value in converted))
            if not math.isfinite(norm) or abs(norm - 1) > 0.001:
                raise ProviderUnavailable()
            ordered[index] = tuple(converted)
        prompt = total = None
        usage = parsed.get("usage")
        if usage is not None:
            if type(usage) is not dict:
                raise ProviderUnavailable()
            prompt, total = usage.get("prompt_tokens"), usage.get("total_tokens")
            if not _integer(prompt) or not _integer(total):
                raise ProviderUnavailable()
            assert isinstance(prompt, int) and isinstance(total, int)
            if total < prompt:
                raise ProviderUnavailable()
            if self.profile.provider == "openai" and total > counted:
                raise ProviderUnavailable()
        synthetic = self.profile.provider == "fake"
        cost = 0.0 if synthetic else (float(self._cost(total)) if total is not None else None)
        return EmbeddingBatch(
            profile=self.profile, vectors=tuple(ordered[index] for index in range(size)),
            usage=EmbeddingUsage(prompt_tokens=prompt, total_tokens=total, cost_usd=cost,
                                 cost_kind="known" if synthetic else ("estimated" if cost is not None else "unknown")),
            synthetic=synthetic,
        )

    async def embed_query(self, text: str, *, deadline: float) -> EmbeddingBatch:
        return await self.embed_batch([text], deadline=deadline)

    async def embed_batch(self, texts: list[str] | tuple[str, ...], *, deadline: float) -> EmbeddingBatch:
        if type(deadline) not in (float, int):
            raise InvalidRequest()
        valid_deadline = False
        try:
            valid_deadline = math.isfinite(deadline)
        except (OverflowError, ValueError):
            pass
        if not valid_deadline:
            raise InvalidRequest()
        self._check_deadline(deadline)
        if self._inflight:
            raise ProviderUnavailable()
        self._inflight = True
        try:
            snapshot, counted = self._inputs(texts)
            self._check_deadline(deadline)
            if self.profile.provider == "openai":
                if not self.policy.allow_live or self.policy.usd_per_million_tokens is None:
                    raise UnsupportedCapability()
                if self._cost(counted) > Decimal(str(self.policy.max_cost_usd)):
                    raise UnsupportedCapability()
            body = json.dumps({"model": self.profile.model, "dimensions": self.profile.dimensions,
                               "encoding_format": "float", "input": snapshot},
                              ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            raw: object = None
            failure: type[DeadlineExceeded] | type[ProviderUnavailable] | None = None
            try:
                async with asyncio.timeout(max(0.0, deadline - time.monotonic())):
                    raw = await self._transport(body, deadline=deadline, max_response_bytes=self.limits.max_response_bytes)
            except TimeoutError:
                failure = DeadlineExceeded
            except Exception:
                failure = ProviderUnavailable
            if failure is not None:
                raise failure()
            self._check_deadline(deadline)
            result = self._response(raw, len(snapshot), counted)
            self._check_deadline(deadline)
            return result
        finally:
            self._inflight = False
