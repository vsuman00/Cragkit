"""Compose E-r1 embeddings and dense candidate search with explicit ownership.

The caller initializes and closes its store/transport. No credentials, endpoints
or tokenizers are discovered. Pass only query text approved for the injected
provider; candidate text still requires V5-03 source authorization.
"""
import asyncio
import math

from cragkit.contracts import parse_request, parse_scope
from cragkit.embeddings import EmbeddingAdapter, EmbeddingLimits, EmbeddingProfile
from cragkit.errors import DeadlineExceeded, InvalidRequest
from cragkit.execution import ExecutionLedger
from cragkit.qdrant import bind_embedding_batch, compile_filter


async def retrieve_candidates(store, request, *, scope, transport, token_counter,
                              ledger, deadline, limit=2, policy=None):
    """Return nominations and separate E-r1 usage; never claim source authority."""
    entered = asyncio.get_running_loop().time()
    request, scope = parse_request(request), parse_scope(scope)
    compile_filter(request, scope)  # Reject unsupported filters before inference.
    if (type(ledger) is not ExecutionLedger or type(deadline) not in (int, float)
            or not math.isfinite(deadline) or abs(deadline) > 9007199254740991
            or type(limit) is not int or not 1 <= limit <= min(64, request.limits.max_candidates)):
        raise InvalidRequest()
    end = min(deadline, ledger.deadline, entered + request.limits.deadline_ms / 1000)
    if end <= asyncio.get_running_loop().time():
        raise DeadlineExceeded()
    profile = EmbeddingProfile.model_validate(store.config.dense_profile.model_dump())
    if not callable(transport):
        raise InvalidRequest()
    token = None
    admission_error = None
    adapter = None

    async def accounted_transport(body, *, deadline, max_response_bytes):
        nonlocal token, admission_error
        # E-r1 has passed token, input and live-policy admission at this point.
        assert adapter is not None
        bound = 0.0 if profile.provider == 'fake' else adapter.policy.max_cost_usd
        try:
            token = ledger.reserve(provider_calls=1, cost_upper_usd=bound)
            ledger.dispatch(token)
        except Exception as error:
            admission_error = error
            raise
        return await transport(body, deadline=deadline, max_response_bytes=max_response_bytes)

    adapter = EmbeddingAdapter(accounted_transport, token_counter, profile=profile,
                               limits=EmbeddingLimits(max_items=1), policy=policy)
    try:
        batch = await adapter.embed_query(request.query, deadline=end)
        batch = bind_embedding_batch(batch, profile, expected_items=1)
        if token is None:
            raise InvalidRequest()
        usage = batch.usage
        # A configured live price produces an estimate, not verified billing.
        ledger.reconcile(token, input_tokens=usage.prompt_tokens,
                         output_tokens=(usage.total_tokens - usage.prompt_tokens
                                        if usage.total_tokens is not None and usage.prompt_tokens is not None else None),
                         cost_usd=usage.cost_usd if usage.cost_kind == 'known' else None)
        token = None
    except Exception:
        if admission_error is not None:
            raise admission_error from None
        raise
    finally:
        if token is not None:
            ledger.abandon(token)
    nominations = await store.search_candidates(request, scope=scope, dense=batch,
        branch_limits={'dense': limit}, ledger=ledger, deadline=end)
    return {'nominations': nominations, 'embedding_usage': batch.usage, 'ledger': ledger.snapshot()}
