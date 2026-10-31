"""Authorize evaluation payloads against an explicitly approved immutable packet."""
from __future__ import annotations

from dataclasses import dataclass
import re

from provider_adapters import COHERE_MODEL, OPENAI_MODEL, ProviderRequest, ProviderAdapterError, _json


class EvaluationPayloadError(ValueError):
    """Never expose rejected source/query text."""


def _refuse():
    raise EvaluationPayloadError('unapproved_evaluation_payload')


def _text(value, maximum, *, empty=False):
    invalid = False
    try:
        if type(value) is not str or (not empty and not value) or len(value.encode('utf-8')) > maximum:
            invalid = True
    except UnicodeError:
        invalid = True
    if invalid:
        _refuse()
    return value


@dataclass(frozen=True, repr=False)
class _AuthorizedPayload:
    provider: str
    texts: tuple[str, ...]


class EvaluationPayloadGate:
    """The runner supplies sealed public sources and query-only approved variants.

    This pure primitive does not read a corpus or attest its provenance. The live
    runner must verify the packet identity before constructing it. No labels,
    support spans, private documents or arbitrary query expansion enter here.
    """
    def __init__(self, sources, queries):
        if (type(sources) not in (list, tuple) or type(queries) not in (list, tuple)
                or not 1 <= len(sources) <= 128 or not 1 <= len(queries) <= 128):
            _refuse()
        self._sources = tuple(_text(value, 262144) for value in sources)
        self._queries = frozenset(_text(value, 8192) for value in queries)
        if sum(len(value.encode('utf-8')) for value in (*self._sources, *self._queries)) > 1048576:
            _refuse()

    def _authorize(self, request):
        if (type(request) is not ProviderRequest or type(request.provider) is not str
                or type(request.replay_key) is not str
                or re.fullmatch('[0-9a-f]{64}', request.replay_key) is None):
            _refuse()
        invalid_body = False
        try:
            body = _json(request.body, 300000)
        except ProviderAdapterError:
            invalid_body = True
        if invalid_body:
            _refuse()
        if type(body) is not dict or body.get('model') != request.model:
            _refuse()
        if request.provider == 'openai':
            if (request.model != OPENAI_MODEL
                    or set(body) != {'model', 'dimensions', 'encoding_format', 'input'}
                    or type(body['dimensions']) is not int or body['dimensions'] != 1536
                    or body['encoding_format'] != 'float' or type(body['input']) is not list
                    or not 1 <= len(body['input']) <= 8):
                _refuse()
            texts = tuple(_text(value, 8192) for value in body['input'])
            if (sum(len(value.encode('utf-8')) for value in texts) > 32768
                    or any(value not in self._queries and not any(value in source for source in self._sources)
                           for value in texts)):
                _refuse()
            return _AuthorizedPayload('openai', texts)
        if request.provider == 'cohere':
            if (request.model != COHERE_MODEL
                    or set(body) != {'model', 'query', 'documents', 'top_n', 'max_tokens_per_doc'}
                    or type(body['documents']) is not list or not 1 <= len(body['documents']) <= 15
                    or type(body['top_n']) is not int or body['top_n'] != len(body['documents'])
                    or type(body['max_tokens_per_doc']) is not int or body['max_tokens_per_doc'] != 4096):
                _refuse()
            query = _text(body['query'], 8192)
            texts = tuple(_text(value, 16384, empty=True) for value in body['documents'])
            if (query not in self._queries
                    or sum(len(value.encode('utf-8')) for value in (query, *texts)) > 262144
                    or any(not any(value in source for source in self._sources) for value in texts)):
                _refuse()
            return _AuthorizedPayload('cohere', texts)
        _refuse()

    def admission_ceiling(self, request, *, counter=None):
        """No admission exists for unapproved text or an unissued tokenizer."""
        authorized = self._authorize(request)
        if authorized.provider == 'cohere':
            # Full query/document context, independent of an unknown local tokenizer.
            return len(authorized.texts) * 32768
        from cragkit.context import Cl100kCounter, _ISSUED
        if type(counter) is not Cl100kCounter or counter not in _ISSUED:
            _refuse()
        failed = False
        try:
            count = sum(counter.count(value) for value in authorized.texts)
        except Exception:
            failed = True
        if failed:
            _refuse()
        if type(count) is not int or not 0 < count <= 65536:
            _refuse()
        return count
