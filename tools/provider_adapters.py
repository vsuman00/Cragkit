"""Injected-I/O V6 provider mappings; no credentials, HTTP client or quality oracle.

Wire references: https://developers.openai.com/api/reference/resources/embeddings/methods/create
and https://docs.cohere.com/reference/rerank (checked 31 October 2026).
"""
from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
import time

OPENAI_MODEL = 'text-embedding-3-small'
COHERE_MODEL = 'rerank-v5.0-fast'


class ProviderAdapterError(ValueError):
    """Sanitized boundary error; never includes provider bodies or input text."""


def _fail():
    raise ProviderAdapterError('provider_mapping_invalid')


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            _fail()
        value[key] = item
    return value


def _json(raw, limit):
    try:
        if type(raw) is not bytes or len(raw) > limit:
            _fail()
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                          parse_constant=lambda _: _fail())
    except (ValueError, UnicodeError, RecursionError):
        raise ProviderAdapterError('provider_mapping_invalid') from None


def _encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


def _text(value, maximum, *, nonempty=True):
    try:
        if type(value) is not str or (nonempty and not value) or len(value.encode('utf-8')) > maximum:
            _fail()
    except UnicodeError:
        raise ProviderAdapterError('provider_mapping_invalid') from None
    return value


def _count(value):
    if type(value) is not int or not 0 <= value <= 2147483647:
        _fail()
    return value


def _finite(value):
    try:
        if type(value) not in (int, float) or not math.isfinite(value):
            _fail()
    except OverflowError:
        raise ProviderAdapterError('provider_mapping_invalid') from None
    return value


@dataclass(frozen=True)
class ProviderRequest:
    provider: str
    model: str
    body: bytes = field(repr=False)
    replay_key: str


@dataclass(frozen=True)
class ProviderRecording:
    provider: str
    model: str
    replay_key: str
    response: bytes = field(repr=False)


def _request(provider, model, payload, identity):
    # Identity includes ordered text digests and candidate IDs, never plaintext.
    material = dict(provider=provider, model=model, identity=identity,
                    payload_sha256=sha256(_encode(payload)).hexdigest())
    return ProviderRequest(provider, model, _encode(payload), sha256(_encode(material)).hexdigest())


class ReplaySend:
    """Replay one exact ordered call tape; no fallback or implicit extra calls."""
    def __init__(self, recordings):
        self._recordings = tuple(recordings)
        self._cursor = 0
        if any(type(row) is not ProviderRecording for row in self._recordings):
            _fail()

    async def __call__(self, request, *, deadline, max_response_bytes):
        if time.monotonic() >= deadline:
            raise ProviderAdapterError('deadline_exceeded')
        if self._cursor >= len(self._recordings):
            raise ProviderAdapterError('replay_missing')
        row = self._recordings[self._cursor]
        if (row.provider, row.model, row.replay_key) != (request.provider, request.model, request.replay_key):
            raise ProviderAdapterError('replay_mismatch')
        if type(row.response) is not bytes or len(row.response) > max_response_bytes:
            _fail()
        self._cursor += 1
        return row.response

    def assert_complete(self):
        if self._cursor != len(self._recordings):
            raise ProviderAdapterError('replay_unconsumed')


class _Transport:
    def __init__(self, send):
        if not callable(send):
            _fail()
        self._send = send
        self.recordings = []
        self.observations = []
        self._inflight = False

    async def __call__(self, body, *, deadline, max_response_bytes):
        if (type(deadline) not in (int, float) or not math.isfinite(deadline)
                or type(max_response_bytes) is not int or not 0 < max_response_bytes <= 2097152):
            _fail()
        if self._inflight:
            raise ProviderAdapterError('concurrent_dispatch')
        self._inflight = True
        try:
            if time.monotonic() >= deadline:
                raise ProviderAdapterError('deadline_exceeded')
            request, context = self._prepare(body)
            try:
                raw = await self._send(request, deadline=deadline, max_response_bytes=max_response_bytes)
            except ProviderAdapterError:
                raise
            except Exception:
                raise ProviderAdapterError('provider_send_failed') from None
            if time.monotonic() >= deadline:
                raise ProviderAdapterError('deadline_exceeded')
            encoded, usage = self._map(_json(raw, max_response_bytes), context)
            if len(encoded) > max_response_bytes:
                _fail()
            self.recordings.append(ProviderRecording(request.provider, request.model, request.replay_key, raw))
            self.observations.append(dict(provider=request.provider, model=request.model,
                replay_key=request.replay_key, response_sha256=sha256(raw).hexdigest(), usage=usage,
                provider_truncation='unknown' if request.provider == 'cohere' else None,
                model_revision='mutable_alias'))
            return encoded
        finally:
            self._inflight = False


class OpenAIEmbeddingTransport(_Transport):
    """Return strict model-matched embeddings without rescaling or synthesis."""
    def _prepare(self, body):
        request = _json(body, 65536)
        if (type(request) is not dict or set(request) != {'model', 'dimensions', 'encoding_format', 'input'}
                or request['model'] != OPENAI_MODEL or type(request['dimensions']) is not int
                or request['dimensions'] != 1536 or request['encoding_format'] != 'float'
                or type(request['input']) is not list or not 1 <= len(request['input']) <= 8):
            _fail()
        texts = [_text(value, 8192) for value in request['input']]
        if sum(len(value.encode('utf-8')) for value in texts) > 32768:
            _fail()
        identity = dict(input_sha256=[sha256(value.encode('utf-8')).hexdigest() for value in texts])
        return _request('openai', OPENAI_MODEL, request, identity), len(texts)

    def _map(self, response, size):
        if type(response) is not dict or response.get('model') != OPENAI_MODEL:
            _fail()
        rows = response.get('data')
        if type(rows) is not list or len(rows) != size:
            _fail()
        for index, row in enumerate(rows):
            if type(row) is not dict or type(row.get('index')) is not int or row['index'] != index:
                _fail()
            vector = row.get('embedding')
            if type(vector) is not list or len(vector) != 1536:
                _fail()
            for value in vector:
                _finite(value)
            try:
                norm = math.sqrt(sum(value * value for value in vector))
                if not math.isfinite(norm) or abs(norm - 1) > .001:
                    _fail()
            except OverflowError:
                raise ProviderAdapterError('provider_mapping_invalid') from None
        usage = response.get('usage')
        if usage is not None:
            if type(usage) is not dict or set(usage) != {'prompt_tokens', 'total_tokens'}:
                _fail()
            if _count(usage['total_tokens']) < _count(usage['prompt_tokens']):
                _fail()
        # Omitted usage stays unknown. Core computes estimated cost separately.
        return _encode(response), usage


class CohereRerankTransport(_Transport):
    """Map complete Cohere index scores onto the caller's exact candidate IDs."""
    def _prepare(self, body):
        request = _json(body, 300000)
        if type(request) is not dict or set(request) != {'profile', 'query', 'candidates'}:
            _fail()
        profile = request['profile']
        if (type(profile) is not dict or profile.get('provider') != 'cohere'
                or profile.get('model') != COHERE_MODEL or profile.get('score_kind') != 'relevance_score'
                or profile.get('score_direction') != 'higher_is_better' or profile.get('truncation_policy') != 'reject'):
            _fail()
        query = _text(request['query'], 8192)
        rows = request['candidates']
        if type(rows) is not list or not 1 <= len(rows) <= 40:
            _fail()
        ids, texts = [], []
        for row in rows:
            if type(row) is not dict or set(row) != {'candidate_id', 'text'}:
                _fail()
            ids.append(_text(row['candidate_id'], 512))
            texts.append(_text(row['text'], 16384, nonempty=False))
        if len(set(ids)) != len(ids) or len(query.encode('utf-8')) + sum(len(t.encode('utf-8')) for t in texts) > 262144:
            _fail()
        payload = dict(model=COHERE_MODEL, query=query, documents=texts, top_n=len(rows), max_tokens_per_doc=4096)
        identity = dict(query_sha256=sha256(query.encode('utf-8')).hexdigest(),
            candidates=[dict(candidate_id=cid, text_sha256=sha256(text.encode('utf-8')).hexdigest()) for cid, text in zip(ids, texts)],
            profile=profile)
        return _request('cohere', COHERE_MODEL, payload, identity), ids

    def _map(self, response, ids):
        if type(response) is not dict or response.get('model', COHERE_MODEL) != COHERE_MODEL:
            _fail()
        rows = response.get('results')
        if type(rows) is not list or len(rows) != len(ids):
            _fail()
        mapped, seen = {}, set()
        previous = math.inf
        for row in rows:
            if type(row) is not dict:
                _fail()
            index, score = row.get('index'), _finite(row.get('relevance_score'))
            if type(index) is not int or not 0 <= index < len(ids) or index in seen or not 0 <= score <= 1 or score > previous:
                _fail()
            seen.add(index)
            previous = score
            mapped[ids[index]] = score
        meta = response.get('meta')
        usage = None
        if meta is not None:
            if type(meta) is not dict:
                _fail()
            usage = meta.get('billed_units')
            if usage is not None:
                if type(usage) is not dict:
                    _fail()
                for value in usage.values():
                    if value is not None:
                        # Cohere reports token counts and fractional billing units.
                        if not 0 <= _finite(value) <= 2147483647:
                            _fail()
        normalized = [dict(candidate_id=cid, raw_score=mapped[cid]) for cid in ids]
        return _encode(normalized), usage
