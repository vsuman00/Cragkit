"""Pure QW-r1 canonical input seals and bounded server-vector comparison."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import struct
from typing import Literal, cast
from weakref import WeakSet

from ._qdrant_contract import DenseProfile, SparseProfile, SPARSE_PROFILE
from .embeddings import EmbeddingProfile, FAKE_PROFILE, OPENAI_PROFILE
from .errors import EmbeddingProfileMismatch, IntegrityViolation, InvalidRequest


_DENSE_FIELDS = ('profile_id', 'provider', 'model', 'dimensions', 'tokenizer', 'normalization')
_SPARSE_FIELDS = ('profile_id', 'encoder', 'model', 'revision', 'vocabulary',
                  'preprocessing', 'weighting', 'corpus_statistics_revision')
_DOMAIN = b'cragkit.qdrant.vector.v1\0'
_TOLERANCE = 0.0002 - 0.000000000002
_JS_WHITESPACE = '\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


@dataclass(frozen=True, slots=True, weakref_slot=True, eq=False)
class _DenseVector:
    kind: Literal['dense']
    name: Literal['dense']
    profile: EmbeddingProfile
    values: tuple[float, ...]
    sealed_bytes: bytes
    input_sha256: str


@dataclass(frozen=True, slots=True, weakref_slot=True, eq=False)
class _SparseVector:
    kind: Literal['sparse']
    name: Literal['sparse']
    profile: SparseProfile
    indices: tuple[int, ...]
    values: tuple[float, ...]
    sealed_bytes: bytes
    input_sha256: str


_DENSE_ISSUED: WeakSet[_DenseVector] = WeakSet()
_SPARSE_ISSUED: WeakSet[_SparseVector] = WeakSet()


def _profile_snapshot(value: object, *, sparse: bool) -> dict[str, str | int]:
    allowed_models = (SparseProfile,) if sparse else (EmbeddingProfile, DenseProfile)
    if type(value) in allowed_models:
        # Exact known model types only. Read their stored native fields rather than
        # invoking serialization hooks on an unchecked model_copy/model_construct.
        value = object.__getattribute__(value, '__dict__')
    if type(value) is not dict:
        raise InvalidRequest()
    source = cast(dict[object, object], value)
    fields = _SPARSE_FIELDS if sparse else _DENSE_FIELDS
    if len(source) != len(fields):
        raise InvalidRequest()
    for key in source:
        if type(key) is not str or len(key) > 256:
            raise InvalidRequest()
        try:
            if len(key.encode('utf-8')) > 256 or key not in fields:
                raise InvalidRequest()
        except UnicodeError:
            raise InvalidRequest() from None
    result: dict[str, str | int] = {}
    for key in fields:
        item = source[key]
        if key == 'dimensions':
            if type(item) not in (int, float):
                raise InvalidRequest()
            number = cast(int | float, item)
            if not 1 <= number <= 9007199254740991 or int(number) != number:
                raise InvalidRequest()
            result[key] = int(number)
        else:
            if type(item) is not str or len(item) > 1024:
                raise InvalidRequest()
            try:
                if len(item.encode('utf-8')) > 1024 or not item.strip(_JS_WHITESPACE) or '\0' in item:
                    raise InvalidRequest()
            except UnicodeError:
                raise InvalidRequest() from None
            result[key] = item
    supported = (SPARSE_PROFILE,) if sparse else (FAKE_PROFILE, OPENAI_PROFILE)
    if not any(all(result[key] == object.__getattribute__(profile, '__dict__')[key]
                   for key in fields) for profile in supported):
        raise EmbeddingProfileMismatch()
    return result


def _numbers(value: object, *, minimum: int, maximum: int) -> list[float]:
    if type(value) not in (list, tuple):
        raise InvalidRequest()
    source = cast(list[object] | tuple[object, ...], value)
    if not minimum <= len(source) <= maximum:
        raise InvalidRequest()
    result: list[float] = []
    for item in source:
        if type(item) not in (int, float):
            raise InvalidRequest()
        try:
            number = float(cast(int | float, item))
        except (OverflowError, ValueError):
            raise InvalidRequest() from None
        if not math.isfinite(number):
            raise InvalidRequest()
        result.append(number)
    return result


def _float32(value: float) -> float:
    try:
        rounded = cast(float, struct.unpack('<f', struct.pack('<f', value))[0])
    except (OverflowError, struct.error):
        raise InvalidRequest() from None
    if not math.isfinite(rounded) or (value != 0 and rounded == 0):
        raise InvalidRequest()
    return 0.0 if rounded == 0 else rounded


def _seal(kind: Literal['dense', 'sparse'], profile: dict[str, str | int],
          values: tuple[float, ...], indices: tuple[int, ...] | None = None) -> bytes:
    parts = [_DOMAIN]

    def frame(value: str) -> None:
        encoded = value.encode('utf-8')
        parts.extend((struct.pack('<I', len(encoded)), encoded))

    frame(kind)
    frame(kind)
    fields = _DENSE_FIELDS if kind == 'dense' else _SPARSE_FIELDS
    parts.append(struct.pack('<I', len(fields)))
    for key in fields:
        frame(key)
        frame(str(profile[key]))
    parts.append(struct.pack('<I', len(values)))
    if indices is not None:
        parts.append(struct.pack(f'<{len(indices)}I', *indices))
    parts.append(struct.pack(f'<{len(values)}f', *values))
    return b''.join(parts)


def encode_dense(vector: object, profile: object) -> _DenseVector:
    """Validate the original E-r1 vector, then seal canonical binary32 input."""
    checked_profile = _profile_snapshot(profile, sparse=False)
    original = _numbers(vector, minimum=1536, maximum=1536)
    squares = 0.0
    for component in original:
        squares += component * component
    norm = math.sqrt(squares)
    if not math.isfinite(norm) or abs(norm - 1) > 0.001:
        raise InvalidRequest()
    values = tuple(_float32(component) for component in original)
    sealed = _seal('dense', checked_profile, values)
    result = _DenseVector('dense', 'dense', EmbeddingProfile.model_validate(checked_profile),
                          values, sealed, hashlib.sha256(sealed).hexdigest())
    _DENSE_ISSUED.add(result)
    return result


def _sparse_arrays(indices: object, values: object) -> tuple[tuple[int, ...], tuple[float, ...]]:
    raw_indices = _numbers(indices, minimum=1, maximum=16)
    raw_values = _numbers(values, minimum=1, maximum=16)
    if len(raw_indices) != len(raw_values):
        raise InvalidRequest()
    checked_indices: list[int] = []
    for index in raw_indices:
        if not 0 <= index <= 4294967295 or int(index) != index:
            raise InvalidRequest()
        integer = int(index)
        if checked_indices and integer <= checked_indices[-1]:
            raise InvalidRequest()
        checked_indices.append(integer)
    if any(component <= 0 for component in raw_values):
        raise InvalidRequest()
    return tuple(checked_indices), tuple(_float32(component) for component in raw_values)


def encode_sparse(indices: object, values: object, profile: object) -> _SparseVector:
    """Seal the declared manual sparse profile, sorted indices and positive weights."""
    checked_profile = _profile_snapshot(profile, sparse=True)
    checked_indices, checked_values = _sparse_arrays(indices, values)
    sealed = _seal('sparse', checked_profile, checked_values, checked_indices)
    result = _SparseVector('sparse', 'sparse', SparseProfile.model_validate(checked_profile),
                           checked_indices, checked_values, sealed, hashlib.sha256(sealed).hexdigest())
    _SPARSE_ISSUED.add(result)
    return result


def verify_dense_readback(expected: object, observed: object) -> None:
    """Require QW-r1 component, norm and L2 bounds around ideal normalization."""
    try:
        if type(expected) is not _DenseVector or expected not in _DENSE_ISSUED:
            raise IntegrityViolation()
        assert isinstance(expected, _DenseVector)
        returned = tuple(_float32(value) for value in _numbers(observed, minimum=1536, maximum=1536))
        squares = 0.0
        for value in expected.values:
            squares += value * value
        input_norm = math.sqrt(squares)
        returned_squares = 0.0
        difference_squares = 0.0
        for original, actual in zip(expected.values, returned):
            ideal = original / input_norm
            difference = actual - ideal
            if abs(difference) > _TOLERANCE * abs(ideal) + 2**-126:
                raise IntegrityViolation()
            returned_squares += actual * actual
            difference_squares += difference * difference
        if abs(math.sqrt(returned_squares) - 1) > _TOLERANCE or math.sqrt(difference_squares) > _TOLERANCE:
            raise IntegrityViolation()
    except (InvalidRequest, IntegrityViolation):
        raise IntegrityViolation() from None


def verify_sparse_readback(expected: object, observed_indices: object, observed_values: object) -> None:
    """Require exact sparse indices and canonical binary32 weights."""
    try:
        if type(expected) is not _SparseVector or expected not in _SPARSE_ISSUED:
            raise IntegrityViolation()
        assert isinstance(expected, _SparseVector)
        indices, values = _sparse_arrays(observed_indices, observed_values)
        if indices != expected.indices or values != expected.values:
            raise IntegrityViolation()
    except (InvalidRequest, IntegrityViolation):
        raise IntegrityViolation() from None
