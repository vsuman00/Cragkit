"""Pure request/response validation shared by durable evaluation recordings."""
from __future__ import annotations

from hashlib import sha256
import math
import re

from provider_adapters import (COHERE_MODEL, OPENAI_MODEL, CohereRerankTransport,
    OpenAIEmbeddingTransport, ProviderAdapterError, ProviderRequest, _json, _text)


class RecordingValidationError(ValueError):
    """Fixed diagnostic with no retained parser/provider exception."""


def _invalid():
    raise RecordingValidationError('provider_recording_invalid')


def request_metadata(request: ProviderRequest) -> dict:
    """Validate mapped provider wire shape; text provenance belongs to the gate."""
    if (type(request) is not ProviderRequest or type(request.provider) is not str
            or request.provider not in ('openai', 'cohere') or type(request.model) is not str
            or type(request.replay_key) is not str or re.fullmatch('[0-9a-f]{64}', request.replay_key) is None):
        _invalid()
    failed = False
    try:
        if request.provider == 'openai':
            if request.model != OPENAI_MODEL:
                _invalid()
            _, items = OpenAIEmbeddingTransport(lambda *args, **kwargs: None)._prepare(request.body)
        else:
            body = _json(request.body, 300000)
            if (request.model != COHERE_MODEL or type(body) is not dict
                    or set(body) != {'model', 'query', 'documents', 'top_n', 'max_tokens_per_doc'}
                    or body['model'] != COHERE_MODEL or type(body['documents']) is not list
                    or not 1 <= len(body['documents']) <= 15
                    or type(body['top_n']) is not int or body['top_n'] != len(body['documents'])
                    or type(body['max_tokens_per_doc']) is not int or body['max_tokens_per_doc'] != 4096):
                _invalid()
            query = _text(body['query'], 8192)
            texts = [_text(text, 16384, nonempty=False) for text in body['documents']]
            if len(query.encode('utf-8')) + sum(len(text.encode('utf-8')) for text in texts) > 262144:
                _invalid()
            items = len(texts)
    except (ProviderAdapterError, RecordingValidationError, TypeError, ValueError, OverflowError):
        failed = True
    if failed:
        _invalid()
    return dict(provider=request.provider, model=request.model, replay_key=request.replay_key,
                request_sha256=sha256(request.body).hexdigest(), response_items=items)


def validate_recording(provider: str, model: str, response: bytes, *, expected_items: int,
                       max_response_bytes: int = 2097152) -> int | None:
    """Validate complete provider output; return reported input counts, not a bill."""
    if (type(provider) is not str or provider not in ('openai', 'cohere')
            or type(model) is not str or model != {'openai': OPENAI_MODEL, 'cohere': COHERE_MODEL}[provider]
            or type(expected_items) is not int or not 1 <= expected_items <= (8 if provider == 'openai' else 15)
            or type(max_response_bytes) is not int or not 0 < max_response_bytes <= 2097152):
        _invalid()
    failed, reported = False, None
    try:
        parsed = _json(response, max_response_bytes)
        if provider == 'openai':
            _, usage = OpenAIEmbeddingTransport(lambda *args, **kwargs: None)._map(parsed, expected_items)
            reported = usage['total_tokens'] if usage is not None else None
        else:
            _, usage = CohereRerankTransport(lambda *args, **kwargs: None)._map(
                parsed, [str(index) for index in range(expected_items)])
            reported = usage.get('input_tokens') if usage is not None else None
            if type(reported) is float and math.isfinite(reported) and reported.is_integer():
                reported = int(reported)
        if reported is not None and (type(reported) is not int or not 0 <= reported <= 2147483647):
            _invalid()
    except (ProviderAdapterError, RecordingValidationError, KeyError, TypeError, ValueError, OverflowError):
        failed = True
    if failed:
        _invalid()
    return reported
