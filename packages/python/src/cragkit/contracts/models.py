from __future__ import annotations

from typing import Annotated, Literal, Self, TypeAlias
from uuid import uuid4

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from ._validation import filter_roots, identity, integer, native_json, number, scalar, sequence, text

Identity: TypeAlias = Annotated[str, AfterValidator(identity)]
Query: TypeAlias = Annotated[str, AfterValidator(lambda value: text(value, 16_384))]
Collection: TypeAlias = Annotated[str, AfterValidator(lambda value: text(value, 128))]
Scalar: TypeAlias = Annotated[str | bool | int | float, BeforeValidator(scalar)]
Number: TypeAlias = Annotated[int | float, BeforeValidator(number)]
Integer: TypeAlias = Annotated[int, BeforeValidator(integer)]
FilterField: TypeAlias = Literal["document_id", "revision_id", "language", "kind", "tag"]


class ContractModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def validate_native_json(cls, value: object) -> object:
        if isinstance(value, dict) and "required_filters" in value:
            filter_roots(value["required_filters"])
        return native_json(value)


class FilterModel(ContractModel):
    @model_validator(mode="before")
    @classmethod
    def validate_filter_bounds(cls, value: object) -> object:
        filter_roots([value])
        return value


class EqualityFilter(FilterModel):
    op: Literal["eq", "ne"]
    field: FilterField
    value: Scalar


class OrderFilter(FilterModel):
    op: Literal["gt", "gte", "lt", "lte"]
    field: FilterField
    value: Number


class MembershipFilter(FilterModel):
    op: Literal["in"]
    field: FilterField
    values: Annotated[tuple[Scalar, ...], BeforeValidator(sequence), Field(min_length=1, max_length=32)]


class GroupFilter(FilterModel):
    op: Literal["and", "or"]
    filters: Annotated[tuple[Filter, ...], BeforeValidator(sequence), Field(min_length=1, max_length=16)]


class NotFilter(FilterModel):
    op: Literal["not"]
    filter: Filter


Filter: TypeAlias = Annotated[
    EqualityFilter | OrderFilter | MembershipFilter | GroupFilter | NotFilter,
    Field(discriminator="op"),
]

GroupFilter.model_rebuild()
NotFilter.model_rebuild()


class Limits(ContractModel):
    deadline_ms: Annotated[Integer, Field(ge=1, le=300_000)] = 10_000
    max_attempts: Annotated[Integer, Field(ge=1, le=10)] = 3
    max_subqueries: Annotated[Integer, Field(ge=1, le=16)] = 4
    max_candidates: Annotated[Integer, Field(ge=1, le=10_000)] = 200
    max_context_tokens: Annotated[Integer, Field(ge=1, le=1_000_000)] = 2_000
    max_provider_calls: Annotated[Integer, Field(ge=0, le=1_000)] = 16
    max_spend_usd: Annotated[Number, Field(ge=0, le=1_000_000)] | None = None


class OutputProfile(ContractModel):
    renderer: Identity = "cragkit.context.v1"
    tokenizer: Identity | None = None
    envelope_reserve_tokens: Annotated[Integer, Field(ge=0, le=1_000_000)] = 256
    counting_mode: Literal["estimated", "strict"] = "estimated"

    @model_validator(mode="after")
    def validate_strict_tokenizer(self) -> Self:
        if self.counting_mode == "strict" and self.tokenizer is None:
            raise ValueError("Strict mode requires a tokenizer")
        return self


class ToolRequest(ContractModel):
    schema_version: Literal["0.1"] = "0.1"
    request_id: Identity = Field(default_factory=lambda: str(uuid4()))
    query: Query
    collection: Collection
    search_hints: Annotated[tuple[Identity, ...], BeforeValidator(sequence), Field(max_length=8)] = ()


class RetrievalRequest(ToolRequest):
    required_filters: Annotated[tuple[Filter, ...], BeforeValidator(filter_roots)] = ()
    limits: Limits = Field(default_factory=Limits)
    output_profile: OutputProfile = Field(default_factory=OutputProfile)


class TrustedScope(ContractModel):
    tenant_id: Identity
    principal_id: Identity
    authorization_revision: Identity
    grant_ids: Annotated[tuple[Identity, ...], BeforeValidator(sequence), Field(max_length=64)] = ()
