import hashlib
from typing import Annotated, Literal, Self, TypeAlias

from pydantic import AfterValidator, BeforeValidator, Field, model_validator

from .. import _ENGINE_VERSION
from ._validation import MAX_SAFE_NUMBER, sequence, text
from .models import ContractModel, Identity, Integer, Number


def digest(value: str) -> str:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("Expected a lowercase SHA-256 digest")
    return value


def unique_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError("Duplicate identity reference")
    return values


Digest: TypeAlias = Annotated[str, AfterValidator(digest)]
SafeCount: TypeAlias = Annotated[Integer, Field(ge=0, le=MAX_SAFE_NUMBER)]
EvidenceIds: TypeAlias = Annotated[
    tuple[Identity, ...], BeforeValidator(sequence), Field(max_length=64), AfterValidator(unique_ids)
]
FacetIds: TypeAlias = Annotated[
    tuple[Identity, ...], BeforeValidator(sequence), Field(max_length=32), AfterValidator(unique_ids)
]


class Evidence(ContractModel):
    evidence_id: Identity
    collection: Identity
    document_id: Identity
    revision_id: Identity
    chunk_id: Identity
    source_locator: Identity
    start_byte: SafeCount
    end_byte: SafeCount
    text: Annotated[str, Field(min_length=1), AfterValidator(lambda value: text(value, 32_768, nonblank=False))]
    source_sha256: Digest
    text_sha256: Digest

    @model_validator(mode="after")
    def validate_excerpt(self) -> Self:
        encoded = self.text.encode("utf-8")
        if self.end_byte <= self.start_byte or self.end_byte - self.start_byte != len(encoded):
            raise ValueError("Excerpt byte span does not match text")
        if hashlib.sha256(encoded).hexdigest() != self.text_sha256:
            raise ValueError("Excerpt digest does not match text")
        return self


class Facet(ContractModel):
    facet_id: Identity
    question: Annotated[str, AfterValidator(lambda value: text(value, 2_048))]
    state: Literal["supported", "missing", "unknown", "conflicting"]
    required: bool = True
    evidence_ids: EvidenceIds = ()
    assessment_method: Identity = "none"
    assessment_version: Identity = "0"

    @model_validator(mode="after")
    def validate_assessment(self) -> Self:
        if self.state == "supported" and not self.evidence_ids:
            raise ValueError("Supported facets need evidence")
        if self.state == "conflicting" and len(self.evidence_ids) < 2:
            raise ValueError("Conflicting facets need two evidence items")
        if self.state == "missing" and self.evidence_ids:
            raise ValueError("Missing facets cannot reference evidence")
        if self.state != "unknown" and self.assessment_method == "none":
            raise ValueError("Assessed facets need an assessment method")
        return self


class Limitation(ContractModel):
    code: Literal[
        "coverage_unknown", "incomplete_facets", "stale_evidence",
        "truncated_evidence", "budget_exhausted", "degraded_search",
    ]
    facet_ids: FacetIds = ()
    evidence_ids: EvidenceIds = ()


class StageDuration(ContractModel):
    stage: Identity
    duration_ms: Annotated[Number, Field(ge=0, le=300_000)]


class Usage(ContractModel):
    attempt_count: Annotated[Integer, Field(ge=0, le=10)] = 0
    provider_calls: Annotated[Integer, Field(ge=0, le=1_000)] = 0
    provider_input_tokens: SafeCount | None = None
    provider_output_tokens: SafeCount | None = None
    cost_usd: Annotated[Number, Field(ge=0, le=1_000_000)] | None = None
    cost_kind: Literal["unknown", "estimated", "known"] = "unknown"
    context_tokens: Annotated[Integer, Field(ge=0, le=1_000_000)] | None = None
    context_counting: Literal["unknown", "estimated", "strict"] = "unknown"
    stage_durations: Annotated[
        tuple[StageDuration, ...], BeforeValidator(sequence), Field(max_length=32)
    ] = ()

    @model_validator(mode="after")
    def validate_accounting(self) -> Self:
        if (self.cost_kind == "unknown") != (self.cost_usd is None):
            raise ValueError("Cost declaration does not match value")
        if (self.context_counting == "unknown") != (self.context_tokens is None):
            raise ValueError("Context counting declaration does not match value")
        names = [duration.stage for duration in self.stage_durations]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate stage name")
        return self


class Versions(ContractModel):
    engine: Identity = _ENGINE_VERSION
    policy: Identity = "unassessed.v0"
    model: Identity | None = None
    tokenizer: Identity | None = None
    index: Identity | None = None


class RetrievalResult(ContractModel):
    request_id: Identity
    status: Literal["sufficient", "partial", "insufficient"]
    schema_version: Literal["0.1"] = "0.1"
    execution: Literal["complete", "degraded"] = "complete"
    evidence: Annotated[tuple[Evidence, ...], BeforeValidator(sequence), Field(max_length=64)] = ()
    facets: Annotated[tuple[Facet, ...], BeforeValidator(sequence), Field(max_length=32)] = ()
    context: Annotated[str, AfterValidator(lambda value: text(value, 262_144, nonblank=False))] = ""
    usage: Usage = Field(default_factory=Usage)
    limitations: Annotated[tuple[Limitation, ...], BeforeValidator(sequence), Field(max_length=32)] = ()
    trace_id: Identity | None = None
    versions: Versions = Field(default_factory=Versions)

    @model_validator(mode="after")
    def validate_references_and_revisions(self) -> Self:
        evidence_ids = {item.evidence_id for item in self.evidence}
        facet_ids = {facet.facet_id for facet in self.facets}
        if len(evidence_ids) != len(self.evidence) or len(facet_ids) != len(self.facets):
            raise ValueError("Duplicate evidence or facet identity")
        source_digests: dict[tuple[str, str, str], str] = {}
        for item in self.evidence:
            revision = (item.collection, item.document_id, item.revision_id)
            previous = source_digests.setdefault(revision, item.source_sha256)
            if previous != item.source_sha256:
                raise ValueError("Conflicting source digests for one revision")
        for facet in self.facets:
            if not set(facet.evidence_ids) <= evidence_ids:
                raise ValueError("Unresolved facet evidence reference")
        for limitation in self.limitations:
            if not set(limitation.evidence_ids) <= evidence_ids or not set(limitation.facet_ids) <= facet_ids:
                raise ValueError("Unresolved limitation reference")
        return self

    @model_validator(mode="after")
    def validate_status_declarations(self) -> Self:
        required = [facet for facet in self.facets if facet.required]
        if self.status == "sufficient" and (
            not required or any(facet.state != "supported" for facet in required)
            or self.versions.policy == "unassessed.v0"
        ):
            raise ValueError("Sufficiency needs assessed supported required facets")
        if self.status == "partial" and not self.evidence:
            raise ValueError("Partial results need evidence")
        if self.execution == "degraded" and not any(
            limitation.code == "degraded_search" for limitation in self.limitations
        ):
            raise ValueError("Degraded execution needs a visible limitation")
        if self.usage.context_counting == "strict" and self.versions.tokenizer is None:
            raise ValueError("Strict context counting needs a tokenizer identity")
        return self
