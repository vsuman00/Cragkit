export type ErrorCode = 'invalid_request' | 'unauthorized_scope' | 'unsupported_capability'
  | 'index_not_ready' | 'embedding_profile_mismatch' | 'provider_unavailable'
  | 'deadline_exceeded' | 'context_budget_too_small' | 'integrity_violation';
export type ErrorEnvelope = Readonly<{ code: ErrorCode; message: string; retryable: boolean }>;

export class CragkitError extends Error {
  readonly code: ErrorCode;
  readonly retryable: boolean;
  constructor(code: ErrorCode, message: string, retryable: boolean) {
    super(message);
    this.name = new.target.name;
    this.code = code;
    this.retryable = retryable;
  }
  to_dict(): ErrorEnvelope { return Object.freeze({ code: this.code, message: this.message, retryable: this.retryable }); }
  toJSON(): ErrorEnvelope { return this.to_dict(); }
}
export class InvalidRequest extends CragkitError {
  constructor() { super('invalid_request', 'Invalid retrieval request.', false); }
}
export class UnauthorizedScope extends CragkitError {
  constructor() { super('unauthorized_scope', 'Access scope is not authorized.', false); }
}
export class UnsupportedCapability extends CragkitError {
  constructor() { super('unsupported_capability', 'Required capability is unavailable.', false); }
}
export class IndexNotReady extends CragkitError {
  constructor() { super('index_not_ready', 'Index is not ready.', true); }
}
export class EmbeddingProfileMismatch extends CragkitError {
  constructor() { super('embedding_profile_mismatch', 'Embedding profile does not match.', false); }
}
export class ProviderUnavailable extends CragkitError {
  constructor() { super('provider_unavailable', 'Provider is unavailable.', true); }
}
export class DeadlineExceeded extends CragkitError {
  constructor() { super('deadline_exceeded', 'Request deadline exceeded.', true); }
}
export class ContextBudgetTooSmall extends CragkitError {
  constructor() { super('context_budget_too_small', 'Context budget cannot fit the required envelope.', false); }
}
export class IntegrityViolation extends CragkitError {
  constructor() { super('integrity_violation', 'Source integrity validation failed.', false); }
}
