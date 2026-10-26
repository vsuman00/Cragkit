"""QW-r1 content manifests and portable original-vector replay sidecars."""
import copy
import hashlib
import json
from pathlib import Path
import struct

import pytest

import cragkit._qdrant_manifest as manifest_module
from cragkit._qdrant_manifest import (
    encode_dense_replay, encode_manifest, encode_purge_intent, encode_security_intent,
    encode_sparse_replay, encode_stage_intent, restore_dense_replay, restore_sparse_replay,
)
from cragkit._qdrant_vectors import encode_dense, verify_dense_readback, verify_sparse_readback
from cragkit.embeddings import FAKE_PROFILE
from cragkit.errors import EmbeddingProfileMismatch, IntegrityViolation, InvalidRequest, UnsupportedCapability
from cragkit.qdrant import point_id


FIXTURE = json.loads((Path(__file__).resolve().parents[3] /
                     'contracts/fixtures/qdrant_publication.json').read_text())
TEXT = FIXTURE['source_revision']['canonical_utf8']['value']


def digest(value):
    return hashlib.sha256(value).hexdigest()


def dense_vector(value=1, *, negative_zero=False):
    result = [value] + [0.0] * 1535
    if negative_zero:
        result[1] = -0.0
    return result


def manifest_record():
    result = {**FIXTURE['physical'], **{key: FIXTURE['document'][key]
              for key in ('tenant_id', 'collection', 'document_id')}}
    result.update({key: FIXTURE['source_revision'][key]
                   for key in ('revision_id', 'source_sha256', 'source_bytes', 'source_locator', 'parser_id')})
    result.update(generation_id=FIXTURE['intent']['generation_id'],
                  chunker_profile=FIXTURE['intent']['chunker_profile'],
                  dense_profile=copy.deepcopy(FIXTURE['profiles']['dense']),
                  sparse_profile=copy.deepcopy(FIXTURE['profiles']['sparse']), members=[])
    for row in FIXTURE['members']:
        result['members'].append({key: row[key] for key in
                                  ('chunk_id', 'point_id', 'start_byte', 'end_byte', 'text_sha256')}
                                 | {'dense_input_sha256': row['dense']['vector_sha256'],
                                    'sparse_input_sha256': row['sparse']['vector_sha256']})
    return result


def stage_record():
    return {'intent_id': 'intent-2', 'tenant_id': 'tenant-a', 'collection': 'docs', 'document_id': 'doc-1',
            'manifest_sha256': FIXTURE['intent']['manifest_sha256'],
            'expected_active_generation_id': 'gen-1', 'expected_authorization_revision': 'auth-1',
            'expected_mutation_epoch': 1, 'initial_authorization': None}


def authorization(**patch):
    return {'authorization_revision': 'auth-2', 'principal_ids': ['reader-z', 'reader-a', 'reader-a'],
            'grant_ids': ['雪', 'a', 'é'], 'language': 'en', 'kind': None, 'tag': 'reference',
            'tombstoned': False, **patch}


def security_record(**patch):
    return {'action': 'update_authorization', 'intent_id': 'acl-2', 'tenant_id': 'tenant-a',
            'collection': 'docs', 'document_id': 'doc-1', 'expected_authorization_revision': 'auth-1',
            'expected_mutation_epoch': 1, 'authorization': authorization(), **patch}


def reidentify(record, member):
    member['point_id'] = point_id(['cragkit.qdrant.point.v1', record['backend_namespace'],
        record['physical_collection'], record['collection_incarnation'], record['tenant_id'],
        record['collection'], record['document_id'], record['revision_id'], record['generation_id'],
        member['chunk_id'], record['dense_profile']['profile_id'],
        record['sparse_profile']['profile_id'] if record['sparse_profile'] else ''])


@pytest.mark.parametrize('row', FIXTURE['replay_goldens'], ids=lambda row: row['id'])
def test_shared_original_replay_goldens(row):
    if row['kind'] == 'dense':
        original = [0.0] * row['original_encoding']['dimensions']
        for index, value in row['original_encoding']['nonzero']:
            original[index] = value
        if 'negative_zero_index' in row['original_encoding']:
            original[row['original_encoding']['negative_zero_index']] = -0.0
        result = encode_dense_replay(original, FIXTURE['profiles']['dense'])
        restored = restore_dense_replay(result.blob, row['blob_sha256'], row['input_sha256'],
                                        FIXTURE['profiles']['dense'])
    else:
        result = encode_sparse_replay(row['indices'], row['values'], FIXTURE['profiles']['sparse'])
        restored = restore_sparse_replay(result.blob, row['blob_sha256'], row['input_sha256'],
                                         FIXTURE['profiles']['sparse'])
    assert len(result.blob) == row['blob_bytes']
    assert result.blob_sha256 == row['blob_sha256']
    assert result.input_sha256 == restored.input_sha256 == row['input_sha256']


@pytest.mark.parametrize('name,row', FIXTURE['operation_goldens'].items())
def test_shared_operation_goldens(name, row):
    encoder = encode_purge_intent if name == 'purge' else (
        encode_stage_intent if name == 'bootstrap_stage' else encode_security_intent)
    result = encoder(row['record'])
    assert json.loads(result.encoded_bytes) == row['value']
    assert result.sha256 == row['sha256']
    assert len(result.encoded_bytes) == row['encoded_bytes']


def test_shared_ordered_manifest_and_stage_goldens():
    encoded = encode_manifest(manifest_record(), TEXT)
    assert json.loads(encoded.encoded_bytes) == FIXTURE['canonical_tuples']['manifest']
    assert encoded.sha256 == FIXTURE['intent']['manifest_sha256']
    stage = encode_stage_intent(stage_record())
    assert json.loads(stage.encoded_bytes) == FIXTURE['canonical_tuples']['stage_intent']
    assert stage.sha256 == FIXTURE['intent']['payload_sha256']
    for result in (encoded, stage):
        assert type(result.value) is tuple and type(result.encoded_bytes) is bytes
        assert digest(result.encoded_bytes) == result.sha256
        with pytest.raises((AttributeError, TypeError, ValueError)):
            result.sha256 = 'changed'


def test_snapshot_sorting_and_member_uniqueness():
    raw = manifest_record()
    original = encode_manifest(raw, TEXT)
    raw['members'].reverse()
    assert encode_manifest(raw, TEXT).sha256 == original.sha256
    raw['members'][0]['chunk_id'] = 'changed'
    assert original.value[-1][0][0][9] == 'chunk-1'
    duplicate = manifest_record()
    duplicate['members'][1] = copy.deepcopy(duplicate['members'][0])
    with pytest.raises(IntegrityViolation):
        encode_manifest(duplicate, TEXT)
    unicode = manifest_record()
    for member, name in zip(unicode['members'], ['雪', 'é']):
        member['chunk_id'] = name
        reidentify(unicode, member)
    ordered = encode_manifest(unicode, TEXT)
    assert [row[0][9] for row in ordered.value[-1]] == ['é', '雪']


def test_bom_crlf_nul_and_exact_utf8_source_preservation():
    text = '\ufeffA\r\n雪\0é'
    raw = manifest_record()
    encoded = text.encode('utf-8')
    raw['source_bytes'], raw['source_sha256'] = len(encoded), digest(encoded)
    member = raw['members'][0]
    member.update(start_byte=0, end_byte=len(encoded), text_sha256=digest(encoded))
    raw['members'] = [member]
    result = encode_manifest(raw, text)
    assert result.value[9] == digest(encoded)
    with pytest.raises(IntegrityViolation):
        encode_manifest(raw, text.replace('\r\n', '\n'))


@pytest.mark.parametrize('patch', [
    {'source_sha256': '0' * 64}, {'source_bytes': 12},
    {'members': []}, {'members': [manifest_record()['members'][0]] * 65},
])
def test_source_mismatch_or_member_count_bounds(patch):
    error = InvalidRequest if 'members' in patch else IntegrityViolation
    with pytest.raises(error):
        encode_manifest({**manifest_record(), **patch}, TEXT)


@pytest.mark.parametrize('patch,error', [
    ({'point_id': 'not-a-uuid'}, InvalidRequest),
    ({'point_id': FIXTURE['members'][0]['point_id'] + '\n'}, InvalidRequest),
    ({'point_id': '00000000-0000-0000-0000-000000000000'}, IntegrityViolation),
    ({'start_byte': 3}, IntegrityViolation),
    ({'end_byte': 6}, IntegrityViolation),
    ({'end_byte': 14}, IntegrityViolation),
    ({'text_sha256': '0' * 64}, IntegrityViolation),
    ({'dense_input_sha256': 'bad'}, InvalidRequest),
    ({'dense_input_sha256': 'a' * 64 + '\n'}, InvalidRequest),
    ({'start_byte': True}, InvalidRequest),
    ({'end_byte': 7.5}, InvalidRequest),
    ({'end_byte': 0}, IntegrityViolation),
    ({'end_byte': 40000}, IntegrityViolation),
])
def test_member_identity_digest_span_and_shape(patch, error):
    raw = manifest_record()
    raw['members'][0].update(patch)
    with pytest.raises(error):
        encode_manifest(raw, TEXT)


def test_dense_only_profiles_and_semantic_integer_metadata():
    raw = manifest_record()
    raw['sparse_profile'] = None
    for member in raw['members']:
        member['sparse_input_sha256'] = None
        member['start_byte'] = float(member['start_byte'])
        member['end_byte'] = float(member['end_byte'])
        reidentify(raw, member)
    result = encode_manifest(raw, TEXT)
    assert result.value[15] is None
    assert all(row[-1] is None for row in result.value[-1])
    bad = manifest_record()
    bad['dense_profile']['model'] = 'wrong-model'
    with pytest.raises(UnsupportedCapability):
        encode_manifest(bad, TEXT)
    with pytest.raises(IntegrityViolation):
        encode_manifest({**raw, 'sparse_profile': FIXTURE['profiles']['sparse']}, TEXT)


def test_strict_native_metadata_bounds_and_missing_nullable_fields():
    class Trap(dict):
        def items(self):
            raise AssertionError('private-canary')
    cycle = manifest_record()
    cycle['members'] = [cycle]
    cases = [Trap(), {**manifest_record(), 'extra': 'unknown'},
             {**manifest_record(), 'parser_id': 'x' * 1025},
             {**manifest_record(), 'source_locator': '\0secret'},
             {**manifest_record(), 'extra': [None] * 4097}, cycle]
    for record in cases:
        with pytest.raises(InvalidRequest) as caught:
            encode_manifest(record, TEXT)
        assert 'private-canary' not in str(caught.value)
    missing = stage_record()
    del missing['initial_authorization']
    with pytest.raises(InvalidRequest):
        encode_stage_intent(missing)
    for bad in (b'bytes', '\ud800', ''):
        with pytest.raises(InvalidRequest):
            encode_manifest(manifest_record(), bad)


def test_identity_blank_rule_preserves_non_ascii_whitespace():
    for identity in ('\u00a0', '\ufeff'):
        raw = manifest_record()
        raw['document_id'] = identity
        for member in raw['members']:
            reidentify(raw, member)
        assert encode_manifest(raw, TEXT).value[6] == identity
        assert encode_stage_intent({**stage_record(), 'intent_id': identity}).value[2] == identity
    with pytest.raises(InvalidRequest):
        encode_stage_intent({**stage_record(), 'intent_id': ' \t\r\n\v\f'})


def test_exact_hash_spelling_does_not_accept_newline_suffix():
    for field in ('source_sha256',):
        raw = manifest_record()
        raw[field] += '\n'
        with pytest.raises(InvalidRequest):
            encode_manifest(raw, TEXT)
    with pytest.raises(InvalidRequest):
        encode_stage_intent({**stage_record(), 'manifest_sha256': 'a' * 64 + '\n'})


def test_security_and_purge_exact_ordered_tuples_and_acl_canonicalization():
    result = encode_security_intent(security_record())
    expected = ['cragkit.qdrant.intent.v1', 'update_authorization', 'acl-2', 'tenant-a', 'docs',
                'doc-1', 'auth-1', '1', ['auth-2', ['reader-a', 'reader-z'], ['a', 'é', '雪'],
                                      'en', None, 'reference', 'false']]
    assert json.loads(result.encoded_bytes) == expected
    tombstone = encode_security_intent(security_record(action='tombstone',
                                          authorization=authorization(tombstoned=True)))
    assert tombstone.value[-1][-1] == 'true'
    purge = {'intent_id': 'purge-2', 'tenant_id': 'tenant-a', 'collection': 'docs',
             'document_id': 'doc-1', 'tombstone_intent_payload_sha256': tombstone.sha256,
             'expected_authorization_revision': 'auth-2', 'expected_mutation_epoch': 2.0}
    assert json.loads(encode_purge_intent(purge).encoded_bytes) == [
        'cragkit.qdrant.intent.v1', 'purge', 'purge-2', 'tenant-a', 'docs', 'doc-1',
        tombstone.sha256, 'auth-2', '2']


def test_bootstrap_authorization_binding_and_security_shape():
    raw = stage_record()
    raw.update(expected_active_generation_id=None, initial_authorization=authorization(authorization_revision='auth-1'))
    original = encode_stage_intent(raw)
    assert original.value[-1][0] == 'auth-1'
    raw['initial_authorization']['grant_ids'] = ['another-grant']
    assert encode_stage_intent(raw).sha256 != original.sha256
    for change in ({'expected_active_generation_id': 'gen-1'}, {'expected_mutation_epoch': 0},
                   {'initial_authorization': authorization(authorization_revision='different')},
                   {'initial_authorization': authorization(authorization_revision='auth-1', tombstoned=True)}):
        with pytest.raises(InvalidRequest):
            encode_stage_intent({**raw, **change})
    with pytest.raises(InvalidRequest):
        encode_security_intent(security_record(action='tombstone'))
    with pytest.raises(InvalidRequest):
        encode_security_intent(security_record(authorization=authorization(principal_ids=['a'] * 65)))
    with pytest.raises(InvalidRequest):
        encode_security_intent(security_record(authorization=authorization(tag='雪' * 342)))


def test_dense_replay_preserves_original_bits_and_reissues_valid_encoder_result():
    original = dense_vector(1.00099999, negative_zero=True)
    encoded = encode_dense_replay(original, FAKE_PROFILE)
    assert type(encoded.blob) is bytes and digest(encoded.blob) == encoded.blob_sha256
    assert encoded.blob.startswith(b'cragkit.qdrant.replay.v1\0\x05\0\0\0dense\0\x06\0\0')
    assert encoded.blob[-12288:] == struct.pack('<1536d', *original)
    original[0] = 0
    restored = restore_dense_replay(encoded.blob, encoded.blob_sha256, encoded.input_sha256, FAKE_PROFILE)
    assert restored is not encoded.encoded and restored.input_sha256 == encoded.input_sha256
    verify_dense_readback(restored, dense_vector())
    with pytest.raises(InvalidRequest):
        encode_dense(encoded.encoded.values, FAKE_PROFILE)
    positive = encode_dense_replay(dense_vector(1.00099999), FAKE_PROFILE)
    assert positive.input_sha256 == encoded.input_sha256
    assert positive.blob_sha256 != encoded.blob_sha256


def test_sparse_replay_original_ties_and_indices_roundtrip():
    indices, values = [0.0, 2**32 - 1], [2**-149, .5000000298023224]
    replay = encode_sparse_replay(indices, values, FIXTURE['profiles']['sparse'])
    assert replay.blob[-16:] == struct.pack('<2d', *values)
    indices[0], values[0] = 4, 1
    restored = restore_sparse_replay(replay.blob, replay.blob_sha256, replay.input_sha256,
                                     FIXTURE['profiles']['sparse'])
    assert restored is not replay.encoded
    assert restored.indices == (0, 2**32 - 1)
    verify_sparse_readback(restored, [0, 2**32 - 1], [2**-149, .5])


@pytest.mark.parametrize('kind', ['dense', 'sparse'])
def test_replay_corruption_shape_hash_profile_and_layout(kind):
    profile = FAKE_PROFILE if kind == 'dense' else FIXTURE['profiles']['sparse']
    replay = encode_dense_replay(dense_vector(), profile) if kind == 'dense' else encode_sparse_replay([1], [1], profile)
    restore = restore_dense_replay if kind == 'dense' else restore_sparse_replay
    for blob in (b'', replay.blob[:-1], replay.blob + b'\0', b'x' + replay.blob[1:],
                 bytearray(replay.blob), [1, 2, 3], b'x' * 20000):
        with pytest.raises(IntegrityViolation):
            restore(blob, replay.blob_sha256, replay.input_sha256, profile)
    for blob_hash, input_hash in [('0' * 64, replay.input_sha256), (replay.blob_sha256, '0' * 64),
                                   ('bad', replay.input_sha256)]:
        with pytest.raises(IntegrityViolation):
            restore(replay.blob, blob_hash, input_hash, profile)
    altered = replay.blob[:-8] + struct.pack('<d', float('nan'))
    with pytest.raises(IntegrityViolation):
        restore(altered, digest(altered), replay.input_sha256, profile)
    bad_profile = {**(FAKE_PROFILE.model_dump() if kind == 'dense' else profile), 'model': 'wrong'}
    with pytest.raises(IntegrityViolation):
        restore(replay.blob, replay.blob_sha256, replay.input_sha256, bad_profile)


@pytest.mark.parametrize('kind', ['dense', 'sparse'])
def test_replay_layout_checked_after_matching_blob_hash(kind):
    profile = FAKE_PROFILE if kind == 'dense' else FIXTURE['profiles']['sparse']
    replay = encode_dense_replay(dense_vector(), profile) if kind == 'dense' else encode_sparse_replay([1], [1], profile)
    restore = restore_dense_replay if kind == 'dense' else restore_sparse_replay
    kind_offset = len(b'cragkit.qdrant.replay.v1\0') + 4
    count_offset = kind_offset + len(kind)
    wrong_kind = replay.blob[:kind_offset] + b'x' + replay.blob[kind_offset + 1:]
    wrong_count = replay.blob[:count_offset] + struct.pack('<I', 0) + replay.blob[count_offset + 4:]
    for altered in (wrong_kind, wrong_count, replay.blob + b'\0', replay.blob[:-1]):
        with pytest.raises(IntegrityViolation):
            restore(altered, digest(altered), replay.input_sha256, profile)
    with pytest.raises(IntegrityViolation):
        restore(replay.blob, replay.blob_sha256 + '\n', replay.input_sha256, profile)
    with pytest.raises(IntegrityViolation):
        restore(replay.blob, replay.blob_sha256, replay.input_sha256 + '\n', profile)


def test_replay_native_guards_and_operational_failure_preservation(monkeypatch):
    class Trap(list):
        def __iter__(self):
            raise AssertionError('private-canary')
    with pytest.raises(InvalidRequest):
        encode_dense_replay(Trap(), FAKE_PROFILE)
    with pytest.raises(EmbeddingProfileMismatch):
        encode_dense_replay(dense_vector(), {**FAKE_PROFILE.model_dump(), 'model': 'wrong'})
    replay = encode_dense_replay(dense_vector(), FAKE_PROFILE)
    def exhausted(*args, **kwargs):
        raise MemoryError('synthetic operational failure')
    monkeypatch.setattr(manifest_module, 'encode_dense', exhausted)
    with pytest.raises(MemoryError):
        restore_dense_replay(replay.blob, replay.blob_sha256, replay.input_sha256, FAKE_PROFILE)
