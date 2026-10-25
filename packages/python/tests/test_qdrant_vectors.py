"""Pure QW-r1 vector seals and bounded readback; no backend or model calls."""
import dataclasses
import hashlib
import json
import math
from pathlib import Path
import struct

import pytest

from cragkit._qdrant_contract import DenseProfile, SPARSE_PROFILE
from cragkit._qdrant_vectors import (
    encode_dense, encode_sparse, verify_dense_readback, verify_sparse_readback,
)
from cragkit.embeddings import EmbeddingProfile, FAKE_PROFILE, OPENAI_PROFILE
from cragkit.errors import EmbeddingProfileMismatch, IntegrityViolation, InvalidRequest


FIXTURE = json.loads((Path(__file__).resolve().parents[3] /
                     'contracts/fixtures/qdrant_publication.json').read_text())


def vector(*pairs):
    result = [0.0] * 1536
    for index, value in pairs:
        result[index] = value
    return result


def expand(spec):
    result = vector(*spec['nonzero'])
    if 'negative_zero_index' in spec:
        result[spec['negative_zero_index']] = -0.0
    return result


def normalized(values):
    total = 0.0
    for value in values:
        total += value * value
    norm = math.sqrt(total)
    return [value / norm for value in values]


def test_fixture_member_seals_and_exact_named_framing():
    for member in FIXTURE['members']:
        dense = member['dense']
        result = encode_dense(vector((dense['basis_index'], dense['value'])), FIXTURE['profiles']['dense'])
        assert result.kind == result.name == 'dense'
        assert result.input_sha256 == dense['vector_sha256']
        assert hashlib.sha256(result.sealed_bytes).hexdigest() == result.input_sha256
        assert result.sealed_bytes.startswith(b'cragkit.qdrant.vector.v1\0\x05\0\0\0dense\x05\0\0\0dense')
        assert result.sealed_bytes[-6144:] == struct.pack('<1536f', *result.values)
        verify_dense_readback(result, list(result.values))
        sparse = member['sparse']
        encoded = encode_sparse(sparse['indices'], sparse['values'], FIXTURE['profiles']['sparse'])
        assert encoded.kind == encoded.name == 'sparse'
        assert encoded.input_sha256 == sparse['vector_sha256']
        assert hashlib.sha256(encoded.sealed_bytes).hexdigest() == encoded.input_sha256
        verify_sparse_readback(encoded, sparse['indices'], sparse['values'])


@pytest.mark.parametrize('case', FIXTURE['numeric_cases'], ids=lambda case: case['id'])
def test_all_shared_numeric_cases(case):
    raw = expand(case['input_encoding'])
    if case.get('expected_error') == 'InvalidRequest':
        with pytest.raises(InvalidRequest):
            encode_dense(raw, FAKE_PROFILE)
        return
    result = encode_dense(raw, FAKE_PROFILE)
    for bit in case.get('expected_float32_bits_le', []):
        assert struct.pack('<f', result.values[bit['index']]).hex() == bit['hex']
    observed = expand(case['readback_encoding']) if 'readback_encoding' in case else normalized(result.values)
    if case.get('expected_error') == 'IntegrityViolation':
        with pytest.raises(IntegrityViolation):
            verify_dense_readback(result, observed)
    else:
        verify_dense_readback(result, observed)


def test_profile_bound_seals_and_semantic_integer_dimension():
    fake = encode_dense(vector((0, 1)), FAKE_PROFILE)
    real = encode_dense(vector((0, 1)), OPENAI_PROFILE)
    assert fake.input_sha256 != real.input_sha256
    profile = FAKE_PROFILE.model_dump()
    profile['dimensions'] = 1536.0
    assert encode_dense(vector((0, 1)), profile).input_sha256 == fake.input_sha256
    assert encode_dense(tuple(vector((0, 1))), DenseProfile.model_validate(FAKE_PROFILE.model_dump())).input_sha256 == fake.input_sha256


def test_snapshot_and_nested_immutability():
    raw = vector((0, 1))
    profile = FAKE_PROFILE.model_dump()
    result = encode_dense(raw, profile)
    raw[0] = 0
    profile['model'] = 'changed'
    assert result.values[0] == 1
    assert result.profile.model == FAKE_PROFILE.model
    assert type(result.values) is tuple and type(result.sealed_bytes) is bytes
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        result.input_sha256 = 'changed'
    with pytest.raises((AttributeError, ValueError, TypeError)):
        result.profile.model = 'changed'
    indices, values = [2, 7], [1.0, .5]
    sparse = encode_sparse(indices, values, SPARSE_PROFILE)
    indices[0], values[0] = 3, 2
    assert sparse.indices == (2, 7) and sparse.values == (1.0, .5)


@pytest.mark.parametrize('bad', [None, True, '1', {}, [], [1.0], [0.0] * 1536,
                                 vector((0, 1.002)), vector((0, float('nan'))),
                                 vector((0, float('inf'))), vector((0, True)),
                                 vector((0, '1')), vector((0, 10**10000))])
def test_invalid_original_dense_values(bad):
    with pytest.raises(InvalidRequest):
        encode_dense(bad, FAKE_PROFILE)


@pytest.mark.parametrize('patch,error', [
    ({'model': 'wrong'}, EmbeddingProfileMismatch),
    ({'dimensions': 2}, EmbeddingProfileMismatch),
    ({'dimensions': True}, InvalidRequest),
    ({'dimensions': '1536'}, InvalidRequest),
    ({'dimensions': 1536.5}, InvalidRequest),
    ({'model': 'x' * 1025}, InvalidRequest),
    ({'model': '\ud800'}, InvalidRequest),
    ({'model': None}, InvalidRequest),
    ({'extra': 'field'}, InvalidRequest),
])
def test_profile_shape_and_full_identity(patch, error):
    with pytest.raises(error):
        encode_dense(vector((0, 1)), {**FAKE_PROFILE.model_dump(), **patch})


def test_unchecked_profile_and_string_byte_bounds():
    unchecked = FAKE_PROFILE.model_copy(update={'model': object()})
    with pytest.raises(InvalidRequest):
        encode_dense(vector((0, 1)), unchecked)
    forged = EmbeddingProfile.model_construct(**{**FAKE_PROFILE.model_dump(), 'model': 'wrong'})
    with pytest.raises(EmbeddingProfileMismatch):
        encode_dense(vector((0, 1)), forged)
    for patch in ({'model': '雪' * 342}, {'x' * 257: 'value'}):
        with pytest.raises(InvalidRequest):
            encode_dense(vector((0, 1)), {**FAKE_PROFILE.model_dump(), **patch})


def test_custom_containers_and_numeric_objects_never_execute_hooks():
    class ListTrap(list):
        def __iter__(self):
            raise AssertionError('private-canary')
        def __len__(self):
            raise AssertionError('private-canary')
    class DictTrap(dict):
        def items(self):
            raise AssertionError('private-canary')
    class NumericTrap:
        def __float__(self):
            raise AssertionError('private-canary')
    for value, profile in [(ListTrap(), FAKE_PROFILE), (vector((0, NumericTrap())), FAKE_PROFILE),
                           (vector((0, 1)), DictTrap())]:
        with pytest.raises(InvalidRequest) as caught:
            encode_dense(value, profile)
        assert 'private-canary' not in str(caught.value)
        assert caught.value.__cause__ is None


def test_signed_zero_subnormal_and_norm_before_rounding_only():
    zero = encode_dense(vector((0, 1), (1, -0.0)), FAKE_PROFILE)
    assert math.copysign(1, zero.values[1]) == 1
    assert zero.input_sha256 == encode_dense(vector((0, 1)), FAKE_PROFILE).input_sha256
    tiny = 2**-149
    subnormal = encode_dense(vector((0, 1), (1, tiny)), FAKE_PROFILE)
    assert subnormal.values[1] == tiny
    assert subnormal.input_sha256 != zero.input_sha256
    # The original norm is valid, but binary32 rounding crosses E-r1's upper tolerance.
    result = encode_dense(vector((0, 1.00099999)), FAKE_PROFILE)
    assert result.values[0] > 1.001
    verify_dense_readback(result, vector((0, 1)))


def test_dense_nearest_float32_tolerance_boundary_and_component_gate():
    result = encode_dense(vector((0, 1)), FAKE_PROFILE)
    bits = struct.unpack('<I', struct.pack('<f', 1.0002))[0]
    above = struct.unpack('<f', struct.pack('<I', bits))[0]
    below = struct.unpack('<f', struct.pack('<I', bits - 1))[0]
    verify_dense_readback(result, vector((0, below)))
    with pytest.raises(IntegrityViolation):
        verify_dense_readback(result, vector((0, above)))
    # Unit norm alone would permit a tiny orthogonal component; the component bound rejects it.
    with pytest.raises(IntegrityViolation):
        verify_dense_readback(result, vector((0, 1), (1, 1e-6)))


@pytest.mark.parametrize('observed', [None, {}, [], [1], vector((0, True)), vector((0, '1')),
                                      vector((0, float('nan'))), vector((0, float('inf'))),
                                      vector((0, 1), (1, 1e-50)), vector((1, 1))])
def test_bad_dense_readback_is_integrity(observed):
    with pytest.raises(IntegrityViolation):
        verify_dense_readback(encode_dense(vector((0, 1)), FAKE_PROFILE), observed)


@pytest.mark.parametrize('indices,values', [([], []), ([2, 2], [1, 1]), ([3, 2], [1, 1]),
    ([True], [1]), ([-1], [1]), ([2**32], [1]), ([1.5], [1]), ([1], [True]),
    ([1], [0]), ([1], [-1]), ([1], [1e-50]), ([1], [1e39]), ([1], [float('nan')]),
    ([1], [1, 2]), (list(range(17)), [1] * 17)])
def test_sparse_shape_range_order_and_rounding(indices, values):
    with pytest.raises(InvalidRequest):
        encode_sparse(indices, values, SPARSE_PROFILE)


def test_sparse_exact_readback_profile_and_float32_ties():
    assert encode_sparse([1.0], [1], SPARSE_PROFILE).indices == (1,)
    result = encode_sparse([0, 2**32 - 1], [2**-149, .5000000298023224], SPARSE_PROFILE)
    assert result.values == (2**-149, .5)
    verify_sparse_readback(result, [0, 2**32 - 1], [2**-149, .5])
    for indices, values in [([0, 2**32 - 2], result.values), (result.indices, [2**-149, .5000000596046448]),
                            ([0], [.5]), ([0, 2**32 - 1], [0, .5])]:
        with pytest.raises(IntegrityViolation):
            verify_sparse_readback(result, indices, values)
    with pytest.raises(EmbeddingProfileMismatch):
        encode_sparse([1], [1], {**SPARSE_PROFILE.model_dump(), 'revision': '2'})
    with pytest.raises(InvalidRequest):
        encode_sparse([1], [1], {**SPARSE_PROFILE.model_dump(), 'revision': None})


def test_wrong_kind_forged_or_uninitialized_expected_objects_fail_safely():
    dense = encode_dense(vector((0, 1)), FAKE_PROFILE)
    sparse = encode_sparse([1], [1], SPARSE_PROFILE)
    for expected in (None, {}, sparse, object.__new__(type(dense))):
        with pytest.raises(IntegrityViolation):
            verify_dense_readback(expected, vector((0, 1)))
    for expected in (None, {}, dense, object.__new__(type(sparse))):
        with pytest.raises(IntegrityViolation):
            verify_sparse_readback(expected, [1], [1])


def test_readback_does_not_reclassify_memory_failure_as_corrupt_data(monkeypatch):
    import cragkit._qdrant_vectors as codec

    dense = encode_dense(vector((0, 1)), FAKE_PROFILE)
    sparse = encode_sparse([1], [1], SPARSE_PROFILE)

    def exhausted(*args, **kwargs):
        raise MemoryError('allocation failure')

    with monkeypatch.context() as patch:
        patch.setattr(codec, '_numbers', exhausted)
        with pytest.raises(MemoryError):
            verify_dense_readback(dense, vector((0, 1)))
    with monkeypatch.context() as patch:
        patch.setattr(codec, '_sparse_arrays', exhausted)
        with pytest.raises(MemoryError):
            verify_sparse_readback(sparse, [1], [1])
