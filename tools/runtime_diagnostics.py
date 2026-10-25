"""Bounded, content-free error records for administrative acceptance tools."""

import asyncio
from concurrent.futures import CancelledError as FutureCancelledError


_OPERATIONS = frozenset({
    'primary', 'runtime_close', 'child_stop', 'admin_close', 'admin_connect',
    'schema_restore', 'fixture_transaction', 'policy_drop', 'privilege_revoke',
    'row_delete', 'role_drop', 'verify_inventory', 'lock_acquire', 'lock_release',
    'journal_write', 'journal_read', 'journal_remove', 'cleanup_budget', 'unknown',
})
_STAGES = frozenset({
    'configuration', 'admin_connect', 'lexical_fixture_locale', 'fixture_setup',
    'hybrid_evaluation', 'dense_retrieval', 'vector_generations', 'python_ingestion',
    'typescript_runtime', 'runtime_login', 'scope_filters', 'deadline_cancellation',
    'schema_rejection', 'deadline_query_starting', 'deadline_query_observation',
    'deadline_query_completion', 'deadline_query_fresh_scope_reuse',
    'cancel_query_starting', 'cancel_query_observation', 'cancel_query_completion',
    'cancel_query_fresh_scope_reuse', 'recovery', 'unknown',
})


def _label(value: object, allowed: frozenset[str]) -> str:
    # Exact strings avoid invoking attacker-controlled hashing/equality methods.
    return value if type(value) is str and len(value) <= 64 and value in allowed else 'unknown'


def _sqlstate(error: BaseException) -> str | None:
    try:
        value = getattr(error, 'sqlstate', None)
    except BaseException:
        # Diagnostic extraction must not replace the pending error, even if a
        # hostile descriptor raises cancellation or another BaseException.
        return None
    if type(value) is not str or len(value) != 5:
        return None
    if all('A' <= character <= 'Z' or '0' <= character <= '9' for character in value):
        return value
    return None


def describe_error(
    error: BaseException, *, operation: str, stage: str,
) -> dict[str, str | None]:
    """Return only closed labels and a validated SQLSTATE; never format errors."""
    error_type = type(error)
    if not issubclass(error_type, BaseException):
        raise ValueError('invalid_cleanup_failures')
    sqlstate = _sqlstate(error)
    if issubclass(error_type, (asyncio.CancelledError, FutureCancelledError)):
        category = 'cancelled'
    elif issubclass(error_type, TimeoutError):
        category = 'timeout'
    elif issubclass(error_type, ConnectionError) or (sqlstate is not None and sqlstate[:2] == '08'):
        category = 'connection'
    elif sqlstate is not None:
        category = 'database'
    elif issubclass(error_type, (ValueError, TypeError)):
        category = 'validation'
    else:
        category = 'operation'
    return {
        'operation': _label(operation, _OPERATIONS),
        'stage': _label(stage, _STAGES),
        'category': category,
        'sqlstate': sqlstate,
    }


class CleanupFailure(Exception):
    """Snapshot simultaneous primary and cleanup failures without their content."""

    def __init__(self, failures, *, primary=None, stage='unknown'):
        # Validate native containers before iterating so the work and any user
        # hooks remain bounded. Validate everything before reading descriptors.
        if type(failures) not in (list, tuple) or not 1 <= len(failures) <= 16:
            raise ValueError('invalid_cleanup_failures')
        if primary is not None and not issubclass(type(primary), BaseException):
            raise ValueError('invalid_cleanup_failures')
        pairs = []
        for pair in failures:
            if type(pair) not in (list, tuple) or len(pair) != 2:
                raise ValueError('invalid_cleanup_failures')
            if not issubclass(type(pair[1]), BaseException):
                raise ValueError('invalid_cleanup_failures')
            pairs.append((pair[0], pair[1]))
        self._primary = (
            describe_error(primary, operation='primary', stage=stage)
            if primary is not None else None
        )
        self._cleanup = tuple(
            describe_error(error, operation=operation, stage=stage)
            for operation, error in pairs
        )
        super().__init__('cleanup_failed')

    def to_dict(self) -> dict:
        """Return fresh native containers, detached from the stored snapshot."""
        return {
            'code': 'cleanup_failed',
            'primary': dict(self._primary) if self._primary is not None else None,
            'cleanup': [dict(record) for record in self._cleanup],
        }
