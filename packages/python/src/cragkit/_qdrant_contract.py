"""QC-r1 immutable models and pure validation helpers; no optional driver imports."""
from __future__ import annotations

import json
import math
import struct
import uuid
from typing import Annotated, Any, Literal, TypeVar, cast

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_serializer, model_validator

from .contracts import RetrievalRequest, TrustedScope
from .contracts.models import Collection, Identity
from .contracts._validation import input_text, integer

from .errors import IntegrityViolation, InvalidRequest, UnsupportedCapability


class FrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid', allow_inf_nan=False,
                              revalidate_instances='always')


class SparseProfile(FrozenModel):
    profile_id: Identity
    encoder: Identity
    model: Identity
    revision: Identity
    vocabulary: Identity
    preprocessing: Identity
    weighting: Identity
    corpus_statistics_revision: Identity


SPARSE_PROFILE = SparseProfile(profile_id='fake_manual_sparse_v1', encoder='caller_supplied_fixture',
                              model='none', revision='1', vocabulary='fixture_uint32_v1',
                              preprocessing='none', weighting='caller_supplied', corpus_statistics_revision='none')


class DenseProfile(FrozenModel):
    # Structural QC boundary; compatibility is checked separately from shape.
    profile_id: Identity
    provider: Identity
    model: Identity
    dimensions: Annotated[int, BeforeValidator(integer), Field(ge=1, le=9007199254740991)]
    tokenizer: Identity
    normalization: Identity


class QdrantConfig(FrozenModel):
    backend_namespace: Identity
    physical_collection: Annotated[str, Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,63}$')]
    collection_incarnation: Identity
    dense_profile: DenseProfile
    sparse_profile: SparseProfile | None



def _seq(value: object) -> object:
    if type(value) not in (list, tuple):
        raise ValueError('Invalid sequence')
    assert isinstance(value, (list, tuple))
    return tuple(value)


Identities = Annotated[tuple[Identity, ...], BeforeValidator(_seq), Field(max_length=64)]


class CandidatePayload(FrozenModel):
    backend_namespace: Identity
    physical_collection: Identity
    collection_incarnation: Identity
    tenant_id: Identity
    collection: Collection
    document_id: Identity
    revision_id: Identity
    generation_id: Identity
    chunk_id: Identity
    start_byte: Annotated[int, BeforeValidator(integer), Field(ge=0, le=9007199254740991)]
    end_byte: Annotated[int, BeforeValidator(integer), Field(ge=1, le=9007199254740991)]
    source_sha256: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
    text_sha256: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
    dense_profile_id: Identity
    sparse_profile_id: str
    dense_profile: DenseProfile
    sparse_profile: SparseProfile | None
    principal_ids: Identities
    grant_ids: Identities
    authorization_revision: Identity
    language: str | None = None
    kind: str | None = None
    tag: str | None = None

    @model_validator(mode='before')
    @classmethod
    def optional_strings(cls, value: Any) -> Any:
        if type(value) is cls:
            value = value.model_dump(mode='json')
        if type(value) is not dict:
            raise ValueError('Invalid payload')
        for key in ('language', 'kind', 'tag'):
            if key in value:
                item = value[key]
                if type(item) is not str or '\0' in item or len(item.encode('utf-8')) > 1024:
                    raise ValueError('Invalid metadata')
        return value

    @model_serializer(mode='wrap')
    def serialize_payload(self, handler: Any) -> dict[str, Any]:
        result = cast(dict[str, Any], handler(self))
        for field in ('language', 'kind', 'tag'):
            if getattr(self, field) is None:
                result.pop(field, None)
        return result

    @model_validator(mode='after')
    def spans(self) -> CandidatePayload:
        if self.end_byte <= self.start_byte:
            raise ValueError('Invalid span')
        return self


class QdrantNomination(FrozenModel):
    point_id: str
    branch: Literal['dense', 'sparse']
    score: float
    score_kind: Literal['cosine_similarity', 'dot_product']
    score_direction: Literal['higher_is_better'] = 'higher_is_better'
    verification: Literal['UNVERIFIED'] = 'UNVERIFIED'
    payload: CandidatePayload

    @field_validator('payload', mode='before')
    @classmethod
    def snapshot_payload(cls, value: Any) -> Any:
        if type(value) is CandidatePayload:
            return value.model_dump(mode='json')
        return value


PAYLOAD_FIELDS = tuple(field for field in CandidatePayload.model_fields if field != 'authorization_revision')
PAYLOAD_FIELDS = PAYLOAD_FIELDS[:17] + ('authorization_revision',) + PAYLOAD_FIELDS[17:]


def snapshot(value: object) -> Any:
    """Copy native JSON with bounded traversal, without invoking arbitrary encoders."""
    seen: set[int] = set()
    count = 0
    def visit(item: object, depth: int) -> Any:
        nonlocal count
        count += 1
        if count > 4096 or depth > 32:
            raise InvalidRequest()
        if item is None or type(item) in (str, bool, int, float):
            if type(item) is str:
                try:
                    item.encode('utf-8')
                except UnicodeError:
                    raise InvalidRequest() from None
            if type(item) is float and not math.isfinite(item):
                raise InvalidRequest()
            return item
        if type(item) not in (dict, list, tuple) or id(item) in seen:
            raise InvalidRequest()
        seen.add(id(item))
        try:
            if type(item) is dict:
                if any(type(key) is not str for key in item):
                    raise InvalidRequest()
                return {key: visit(val, depth + 1) for key, val in item.items()}
            assert isinstance(item, (tuple, list))
            return [visit(val, depth + 1) for val in item]
        finally:
            seen.remove(id(item))
    return visit(value, 0)


Model = TypeVar('Model', bound=BaseModel)


def parse_model(model: type[Model], value: object) -> Model:
    if type(value) is model:
        assert isinstance(value, BaseModel)
        value = value.model_dump(mode='json', exclude_unset=True)
    try:
        return model.model_validate(snapshot(value))
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        raise InvalidRequest() from None


def point_id(identity: object) -> str:
    if type(identity) not in (tuple, list):
        raise InvalidRequest()
    assert isinstance(identity, (tuple, list))
    if len(identity) != 12:
        raise InvalidRequest()
    if any(type(value) is not str for value in identity):
        raise InvalidRequest()
    if identity[0] != 'cragkit.qdrant.point.v1':
        raise InvalidRequest()
    try:
        for index, value in enumerate(identity):
            input_text(value, 128 if index == 5 else 256, nonblank=not (index == 11 and value == ''))
        text = json.dumps(identity, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        text.encode('utf-8')
        return str(uuid.uuid5(uuid.NAMESPACE_URL, text))
    except (UnicodeError, TypeError, ValueError):
        raise InvalidRequest() from None


def identity_tuple(payload: CandidatePayload) -> tuple[str, ...]:
    return ('cragkit.qdrant.point.v1', payload.backend_namespace, payload.physical_collection,
            payload.collection_incarnation, payload.tenant_id, payload.collection,
            payload.document_id, payload.revision_id, payload.generation_id, payload.chunk_id,
            payload.dense_profile_id, payload.sparse_profile_id)


def _condition(value: dict[str, Any]) -> dict[str, Any]:
    op = value['op']
    if op in ('and', 'or'):
        return {'must' if op == 'and' else 'should': [_condition(item) for item in value['filters']]}
    if op == 'eq' and type(value['value']) is str:
        return {'key': value['field'], 'match': {'value': value['value']}}
    if op == 'in' and all(type(item) is str for item in value['values']):
        return {'key': value['field'], 'match': {'any': value['values']}}
    raise UnsupportedCapability()


def compile_filter(request: object, scope: object) -> dict[str, Any]:
    req = parse_model(RetrievalRequest, request)
    trusted = parse_model(TrustedScope, scope)
    arms: list[dict[str, Any]] = [{'key': 'principal_ids', 'match': {'value': trusted.principal_id}}]
    if trusted.grant_ids:
        arms.append({'key': 'grant_ids', 'match': {'any': list(trusted.grant_ids)}})
    conditions = [{'key': 'tenant_id', 'match': {'value': trusted.tenant_id}},
                  {'key': 'collection', 'match': {'value': req.collection}}, {'should': arms}]
    conditions.extend(_condition(item) for item in req.model_dump(mode='json')['required_filters'])
    return {'must': conditions}


def matches(filters: list[dict[str, Any]], payload: dict[str, Any]) -> bool:
    def match(node: dict[str, Any]) -> bool:
        if node['op'] == 'and':
            return all(match(child) for child in node['filters'])
        if node['op'] == 'or':
            return any(match(child) for child in node['filters'])
        actual = payload.get(node['field'])
        return type(actual) is str and (actual == node['value'] if node['op'] == 'eq' else actual in node['values'])
    return all(match(node) for node in filters)


def dense_vector(value: object) -> list[float]:
    if type(value) not in (tuple, list):
        raise InvalidRequest()
    assert isinstance(value, (tuple, list))
    if len(value) != 1536:
        raise InvalidRequest()
    result: list[float] = []
    for val in value:
        if type(val) not in (int, float):
            raise InvalidRequest()
        try:
            f = float(val)
            if not math.isfinite(f) or not math.isfinite(struct.unpack('!f', struct.pack('!f', f))[0]):
                raise InvalidRequest()
            result.append(f)
        except (OverflowError, struct.error):
            raise InvalidRequest() from None
    if abs(math.sqrt(sum(item * item for item in result)) - 1) > 0.001:
        raise InvalidRequest()
    return result


def sparse_vector(value: object) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {'indices', 'values'}:
        raise InvalidRequest()
    indices, values = value['indices'], value['values']
    if type(indices) not in (list, tuple) or type(values) not in (list, tuple):
        raise InvalidRequest()
    if not 1 <= len(indices) <= 16 or len(indices) != len(values):
        raise InvalidRequest()
    if any(type(i) is not int or not 0 <= i <= 4294967295 for i in indices):
        raise InvalidRequest()
    if any(a >= b for a, b in zip(indices, indices[1:])):
        raise InvalidRequest()
    result = []
    for weight in values:
        if type(weight) not in (int, float):
            raise InvalidRequest()
        try:
            assert isinstance(weight, (int, float))
            f = float(weight)
            f32 = struct.unpack('!f', struct.pack('!f', f))[0]
            if not math.isfinite(f) or not math.isfinite(f32) or f32 <= 0:
                raise InvalidRequest()
            result.append(f)
        except (OverflowError, struct.error):
            raise InvalidRequest() from None
    return {'indices': list(indices), 'values': result}


def decode_response(raw: object) -> Any:
    if type(raw) is not bytes or len(raw) > 1048576:
        raise IntegrityViolation()
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate key')
            result[key] = value
        return result
    def constant(_: str) -> Any:
        raise ValueError('Nonfinite')
    def integer_token(token: str) -> int:
        if len(token) > 128:
            raise ValueError('Numeric token bound')
        return int(token)
    def float_token(token: str) -> float:
        if len(token) > 128:
            raise ValueError('Numeric token bound')
        return float(token)
    try:
        parsed = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant,
                            parse_int=integer_token, parse_float=float_token)
        count = 0
        def visit(item: Any, depth: int) -> None:
            nonlocal count
            count += 1
            if depth > 32 or count > 32768:
                raise ValueError('Complexity')
            if type(item) is str:
                item.encode('utf-8')
            elif type(item) is float and not math.isfinite(item):
                raise ValueError('Nonfinite')
            elif type(item) is dict:
                for key, val in item.items():
                    key.encode('utf-8')
                    visit(val, depth + 1)
            elif type(item) is list:
                for val in item:
                    visit(val, depth + 1)
        visit(parsed, 0)
        return parsed
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise IntegrityViolation() from None
