from typing import ClassVar


class CragkitError(Exception):
    code: ClassVar[str]
    message: ClassVar[str]
    retryable: ClassVar[bool] = False

    def __init__(self) -> None:
        super().__init__(self.message)

    def to_dict(self) -> dict[str, str | bool]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


class InvalidRequest(CragkitError):
    code = "invalid_request"
    message = "Invalid retrieval request."


class UnauthorizedScope(CragkitError):
    code = "unauthorized_scope"
    message = "Access scope is not authorized."


class UnsupportedCapability(CragkitError):
    code = "unsupported_capability"
    message = "Required capability is unavailable."


class IndexNotReady(CragkitError):
    code = "index_not_ready"
    message = "Index is not ready."
    retryable = True


class EmbeddingProfileMismatch(CragkitError):
    code = "embedding_profile_mismatch"
    message = "Embedding profile does not match."


class ProviderUnavailable(CragkitError):
    code = "provider_unavailable"
    message = "Provider is unavailable."
    retryable = True


class DeadlineExceeded(CragkitError):
    code = "deadline_exceeded"
    message = "Request deadline exceeded."
    retryable = True


class ContextBudgetTooSmall(CragkitError):
    code = "context_budget_too_small"
    message = "Context budget cannot fit the required envelope."


class IntegrityViolation(CragkitError):
    code = "integrity_violation"
    message = "Source integrity validation failed."
