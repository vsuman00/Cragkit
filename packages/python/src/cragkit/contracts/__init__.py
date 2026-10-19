from typing import TypeVar

from pydantic import BaseModel

from cragkit.errors import InvalidRequest

from .models import (
    EqualityFilter,
    Filter,
    GroupFilter,
    Limits,
    MembershipFilter,
    NotFilter,
    OrderFilter,
    OutputProfile,
    RetrievalRequest,
    ToolRequest,
    TrustedScope,
)
from .results import Evidence, Facet, Limitation, RetrievalResult, StageDuration, Usage, Versions

_Model = TypeVar("_Model", bound=BaseModel)


def _parse(model: type[_Model], value: object) -> _Model:
    try:
        return model.model_validate(value)
    except (ValueError, TypeError, RecursionError, OverflowError):
        pass
    raise InvalidRequest() from None


def parse_request(value: object) -> RetrievalRequest:
    return _parse(RetrievalRequest, value)


def parse_tool_request(value: object) -> ToolRequest:
    return _parse(ToolRequest, value)


def parse_scope(value: object) -> TrustedScope:
    return _parse(TrustedScope, value)


def parse_result(value: object) -> RetrievalResult:
    return _parse(RetrievalResult, value)


__all__ = [
    "parse_request", "parse_tool_request", "parse_scope", "RetrievalRequest", "ToolRequest",
    "TrustedScope", "Limits", "OutputProfile", "Filter", "EqualityFilter", "OrderFilter",
    "MembershipFilter", "GroupFilter", "NotFilter",
    "RetrievalResult", "Evidence", "Facet", "Usage", "Versions", "Limitation",
    "StageDuration", "parse_result",
]
