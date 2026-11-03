"""Sealed packet projection and source gates; held-out fixtures are synthetic."""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evaluation_packet as binding


def write(root, path, value):
    target = root/path
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = value if type(value) is bytes else json.dumps(value).encode()
    target.write_bytes(raw)
    return sha256(raw).hexdigest()


@pytest.fixture
def packet_root(tmp_path, monkeypatch):
    """Synthetic approval replaces the pin only inside this test fixture."""
    configuration = json.loads((binding.ROOT/'evaluation/release/V6-candidate.json').read_text())
    configuration['evaluation_revision'] = 'original-r1'
    configuration['held_out']['path'] = 'evaluation/questions/held_out.json'
    documents = []
    inventory = []
    for split, name in [('development', 'dev'), ('held_out', 'held')]:
        source = ('public synthetic '+name+'\n').encode()
        relative = 'documents/'+name+'.txt'
        digest = write(tmp_path, 'evaluation/corpus/'+relative, source)
        documents.append(dict(tenant_id='test-tenant', collection='test-collection', document_id=name,
            revision_id='r1', family_id=name, split=split, active=True, path=relative, canonical_sha256=digest))
        inventory.append(dict(path='evaluation/corpus/'+relative, sha256=digest))
        dataset = dict(schema_version='0.1', origin='synthetic', human_review=dict(state='approved', reviewer='test'),
            questions=[dict(question_id=name, tenant_id='test-tenant', collection='test-collection',
                query='public question '+name, required_filters=[], answerability='answerable',
                facets=[dict(facet_id='test', question='LABEL_CANARY_'+name, state='supported', support=[])])])
        path = 'evaluation/questions/'+('dev.json' if split == 'development' else 'held_out.json')
        inventory.append(dict(path=path, sha256=write(tmp_path, path, dataset)))
    path = 'evaluation/corpus/manifest.json'
    inventory.append(dict(path=path, sha256=write(tmp_path, path, dict(schema_version='0.1', documents=documents))))
    seal = dict(schema_version='0.1', state='sealed', human_review=dict(state='approved', reviewer='test'), files=inventory)
    seal_digest = write(tmp_path, 'evaluation/review/seal.json', seal)
    monkeypatch.setattr(binding, 'APPROVED_SEAL_SHA256', seal_digest)
    for name in binding._INPUT_LIMITS:
        if not (tmp_path/name).exists():
            write(tmp_path, name, b'bounded synthetic preregistration dependency')
    configuration['inputs'] = {name:sha256((tmp_path/name).read_bytes()).hexdigest() for name in binding._INPUT_LIMITS}
    configuration['held_out']['sha256'] = next(row['sha256'] for row in inventory if row['path'].endswith('held_out.json'))
    write(tmp_path, 'evaluation/release/V6-candidate.json', configuration)
    return tmp_path


def test_projection_is_label_free_and_returned_copies_cannot_mutate_issued_snapshot(packet_root):
    bound = binding.bind_packet(packet_root)
    packet = bound.runtime_packet()
    assert set(packet) == {'revision', 'documents', 'queries'}
    assert len(packet['documents']) == len(packet['queries']) == 1
    assert 'LABEL_CANARY' not in json.dumps(packet)
    assert set(packet['queries'][0]) == {'question_id', 'tenant_id', 'collection', 'query', 'required_filters'}
    original = bound.provenance()
    packet['queries'][0]['query'] = 'unapproved replacement'
    assert bound.runtime_packet()['queries'][0]['query'] == 'public question dev'
    assert bound.provenance() == original
    assert not original['candidate_source_verified'] and not original['compiled_artifacts_verified']


def test_held_out_requires_explicit_access_and_valid_source_before_decoding_labels(packet_root, monkeypatch):
    decoded = []
    original = binding._json
    def spy(raw):
        if b'LABEL_CANARY_held' in raw:
            decoded.append(True)
        return original(raw)
    monkeypatch.setattr(binding, '_json', spy)
    with pytest.raises(binding.PacketBindingError, match='held_out_not_enabled'):
        binding.bind_packet(packet_root, split='held_out')
    def refuse(*args):
        raise binding.PacketBindingError('evaluation_candidate_dirty')
    monkeypatch.setattr(binding, 'verify_candidate_source', refuse)
    with pytest.raises(binding.PacketBindingError, match='candidate_dirty'):
        binding.bind_packet(packet_root, split='held_out', allow_held_out=True)
    assert not decoded
    monkeypatch.setattr(binding, 'verify_candidate_source', lambda *args:'a'*40)
    bound = binding.bind_packet(packet_root, split='held_out', allow_held_out=True)
    assert decoded == [True] and bound.provenance()['held_out_opened']
    assert 'LABEL_CANARY' not in json.dumps(bound.runtime_packet())


def test_updated_mutable_manifest_and_seal_cannot_replace_independent_approval(packet_root):
    path = packet_root/'evaluation/review/seal.json'
    seal = json.loads(path.read_text());seal['human_review']['reviewer'] = 'replacement'
    digest = write(packet_root, 'evaluation/review/seal.json', seal)
    candidate = json.loads((packet_root/'evaluation/release/V6-candidate.json').read_text())
    candidate['inputs']['evaluation/review/seal.json'] = digest
    write(packet_root, 'evaluation/release/V6-candidate.json', candidate)
    with pytest.raises(binding.PacketBindingError, match='input_drift'):
        binding.bind_packet(packet_root)


def test_source_drift_rejected_before_runtime_projection(packet_root):
    write(packet_root, 'evaluation/corpus/documents/dev.txt', b'private replacement')
    with pytest.raises(binding.PacketBindingError, match='input_drift') as failure:
        binding.bind_packet(packet_root)
    assert failure.value.__context__ is None


def test_invalid_source_utf8_does_not_retain_decoder_bytes(packet_root, monkeypatch):
    source = 'evaluation/corpus/documents/dev.txt'
    digest = write(packet_root, source, b'private\xff')
    manifest_path = 'evaluation/corpus/manifest.json'
    manifest = json.loads((packet_root/manifest_path).read_text())
    manifest['documents'][0]['canonical_sha256'] = digest
    manifest_digest = write(packet_root, manifest_path, manifest)
    seal_path = 'evaluation/review/seal.json'
    seal = json.loads((packet_root/seal_path).read_text())
    for row in seal['files']:
        if row['path'] == source:
            row['sha256'] = digest
        if row['path'] == manifest_path:
            row['sha256'] = manifest_digest
    seal_digest = write(packet_root, seal_path, seal)
    monkeypatch.setattr(binding, 'APPROVED_SEAL_SHA256', seal_digest)
    candidate_path = 'evaluation/release/V6-candidate.json'
    candidate = json.loads((packet_root/candidate_path).read_text())
    candidate['inputs'].update({manifest_path:manifest_digest, seal_path:seal_digest})
    write(packet_root, candidate_path, candidate)
    with pytest.raises(binding.PacketBindingError, match='source_encoding') as error:
        binding.bind_packet(packet_root)
    assert error.value.__context__ is None and error.value.__cause__ is None


def test_verified_json_uses_the_same_bytes_when_file_changes_after_read(packet_root, monkeypatch):
    original = binding._json
    def swap(raw):
        if b'LABEL_CANARY_dev' in raw:
            replacement = original(raw)
            replacement['questions'][0]['query'] = 'private changed query'
            write(packet_root, 'evaluation/questions/dev.json', replacement)
        return original(raw)
    monkeypatch.setattr(binding, '_json', swap)
    assert binding.bind_packet(packet_root).runtime_packet()['queries'][0]['query'] == 'public question dev'


def test_preregistration_and_approval_must_bind_the_same_consumed_bytes(packet_root, monkeypatch):
    path = 'evaluation/questions/dev.json'
    approved = (packet_root/path).read_bytes()
    changed = json.loads(approved)
    changed['questions'][0]['query'] = 'different preregistered bytes'
    digest = write(packet_root, path, changed)
    candidate_path = 'evaluation/release/V6-candidate.json'
    candidate = json.loads((packet_root/candidate_path).read_text())
    candidate['inputs'][path] = digest
    write(packet_root, candidate_path, candidate)
    original = binding._json
    def swap_after_preregistration(raw):
        if b'"state": "sealed"' in raw:
            (packet_root/path).write_bytes(approved)
        return original(raw)
    monkeypatch.setattr(binding, '_json', swap_after_preregistration)
    with pytest.raises(binding.PacketBindingError, match='input_drift'):
        binding.bind_packet(packet_root)


def test_each_consumed_preregistration_file_has_one_bounded_read(packet_root, monkeypatch):
    reads = []
    original = binding._read
    def capture(root, name, *args):
        reads.append(name)
        return original(root, name, *args)
    monkeypatch.setattr(binding, '_read', capture)
    binding.bind_packet(packet_root)
    assert all(reads.count(name) == 1 for name in binding._INPUT_LIMITS)


@pytest.mark.parametrize('kind', ['fifo', 'symlink', 'directory', 'oversized', 'ancestor_link'])
def test_nonregular_or_unbounded_files_fail_without_following_links(tmp_path, kind):
    path = tmp_path/'input'
    if kind == 'fifo':
        os.mkfifo(path)
    elif kind == 'symlink':
        path.symlink_to(tmp_path/'outside')
    elif kind == 'directory':
        path.mkdir()
    elif kind == 'oversized':
        path.write_bytes(b'x'*17)
    else:
        target = tmp_path/'actual';target.mkdir();(target/'data').write_bytes(b'ok')
        path.symlink_to(target, target_is_directory=True)
        path /= 'data'
    with pytest.raises(binding.PacketBindingError) as error:
        binding._read(tmp_path, str(path.relative_to(tmp_path)), 16)
    assert error.value.__context__ is None


@pytest.mark.parametrize('raw', [b'{private invalid', b'{"x":1,"x":2}', b'[]', b'{"x":NaN}', b'{"x":1e999}', b'\xff'])
def test_json_rejection_does_not_retain_private_parser_context(raw):
    with pytest.raises(binding.PacketBindingError) as error:
        binding._json(raw)
    assert error.value.__context__ is None and error.value.__cause__ is None


@pytest.mark.parametrize('name,value', [('license', []), ('live_limits', None), ('comparison', 'private')])
def test_malformed_preregistration_has_fixed_context_free_error(packet_root, name, value):
    candidate = json.loads((packet_root/'evaluation/release/V6-candidate.json').read_text());candidate[name] = value
    write(packet_root, 'evaluation/release/V6-candidate.json', candidate)
    with pytest.raises(binding.PacketBindingError, match='release_configuration_invalid') as error:
        binding.bind_packet(packet_root)
    assert error.value.__context__ is None


def test_contradictory_provider_profile_is_rejected_before_packet_reads(packet_root):
    path = 'evaluation/release/V6-candidate.json'
    candidate = json.loads((packet_root/path).read_text())
    candidate['comparison']['live_embeddings']['dimensions'] = 3072
    write(packet_root, path, candidate)
    with pytest.raises(binding.PacketBindingError, match='release_configuration_invalid'):
        binding.bind_packet(packet_root)


def test_manually_constructed_or_forged_snapshot_cannot_attest_source():
    with pytest.raises(binding.PacketBindingError, match='not_issued'):
        binding.BoundEvaluationPacket(b'{}', 'held_out', 'a'*64, 'a'*40, 'b'*64)
    fake = object.__new__(binding.BoundEvaluationPacket)
    with pytest.raises(binding.PacketBindingError, match='not_issued'):
        fake.provenance()


def test_bound_provenance_snapshots_approval_pin_and_has_no_mutable_fields(packet_root, monkeypatch):
    bound = binding.bind_packet(packet_root)
    original = bound.provenance()
    monkeypatch.setattr(binding, 'APPROVED_SEAL_SHA256', '0'*64)
    assert bound.provenance() == original
    with pytest.raises(AttributeError):
        bound.source_commit = 'a'*40


def test_real_development_packet_preserves_original_seal_without_held_out_interpretation():
    bound = binding.bind_packet()
    packet = bound.runtime_packet()
    assert len(packet['documents']) == 9 and len(packet['queries']) == 24
    assert not bound.provenance()['held_out_opened']
    assert not bound.provenance()['candidate_source_verified']


def test_candidate_git_identity_refuses_dirty_source_and_wrong_package_tree(tmp_path, monkeypatch):
    import cragkit
    package = tmp_path/'packages/python/src/cragkit/__init__.py'
    package.parent.mkdir(parents=True);package.write_text('# synthetic source\n')
    subprocess.run(['git','init','-q',str(tmp_path)],check=True)
    subprocess.run(['git','-C',str(tmp_path),'add','packages'],check=True)
    subprocess.run(['git','-C',str(tmp_path),'-c','user.name=Test','-c','user.email=test@example.invalid',
                    'commit','-qm','synthetic source'],check=True)
    def git(*args):
        return subprocess.check_output(['git','-C',str(tmp_path),*args],text=True).strip()
    config = dict(source_commit=git('rev-parse','HEAD'), package_tree=git('rev-parse','HEAD:packages'))
    monkeypatch.setattr(binding, 'ROOT', tmp_path)
    monkeypatch.setattr(cragkit, '__file__', str(package))
    assert binding.verify_candidate_source(tmp_path, config) == config['source_commit']
    package.write_text('# changed\n')
    with pytest.raises(binding.PacketBindingError, match='source_mismatch'):
        binding.verify_candidate_source(tmp_path, config)
    package.write_text('# synthetic source\n')
    (package.parent/'untracked.py').write_text('# extra\n')
    with pytest.raises(binding.PacketBindingError, match='candidate_dirty'):
        binding.verify_candidate_source(tmp_path, config)
    wrong = deepcopy(config);wrong['package_tree'] = '0'*40
    with pytest.raises(binding.PacketBindingError, match='package_tree'):
        binding.verify_candidate_source(tmp_path, wrong)


@pytest.fixture
def recovery_root(packet_root, monkeypatch):
    """Build a separately pinned synthetic recovery packet, never real labels."""
    import evaluation_profiles
    base = evaluation_profiles.RECOVERY_ROOT
    source = b'Synthetic recovery evidence only.\n'
    source_path = base+'/corpus/recovery.md'
    digest = write(packet_root, source_path, source)
    manifest_path = base+'/corpus/manifest.json'
    manifest = dict(schema_version='0.1', documents=[dict(tenant_id='recovery-tenant',
        collection='test-collection', document_id='fresh-doc', revision_id='r1', family_id='fresh-family',
        split='held_out', active=True, path='recovery.md', canonical_sha256=digest)])
    manifest_digest = write(packet_root, manifest_path, manifest)
    labels_path = base+'/questions/held_out.json'
    labels = dict(schema_version='0.1', origin='synthetic', human_review=dict(state='approved', reviewer='test'),
        questions=[dict(question_id='fresh-q', tenant_id='recovery-tenant', collection='test-collection',
            query='synthetic recovery question', required_filters=[], answerability='answerable',
            facets=[dict(facet_id='fresh-f', question='RECOVERY_LABEL_CANARY', state='supported', support=[])])])
    labels_digest = write(packet_root, labels_path, labels)
    seal = dict(schema_version='0.1', state='sealed', human_review=dict(state='approved', reviewer='test'),
        files=[dict(path=source_path, sha256=digest), dict(path=manifest_path, sha256=manifest_digest),
               dict(path=labels_path, sha256=labels_digest)])
    seal_path = base+'/seal.json'
    pin = write(packet_root, seal_path, seal)
    monkeypatch.setattr(evaluation_profiles, 'RECOVERY_SEAL_SHA256', pin)
    candidate_path = 'evaluation/release/V6-candidate.json'
    candidate = json.loads((packet_root/candidate_path).read_text())
    candidate['evaluation_revision'] = 'recovery-r1'
    candidate['inputs'].update({manifest_path:manifest_digest, seal_path:pin})
    candidate['held_out']['path'] = labels_path
    candidate['held_out']['sha256'] = labels_digest
    write(packet_root, candidate_path, candidate)
    monkeypatch.setattr(binding, 'verify_candidate_source', lambda *args:'a'*40)
    return packet_root


def test_recovery_profile_projects_only_selected_inputs_and_snapshots_labels(recovery_root):
    bound = binding.bind_packet(recovery_root, split='held_out', allow_held_out=True)
    packet = bound.runtime_packet()
    assert [row['document_id'] for row in packet['documents']] == ['fresh-doc']
    assert [row['question_id'] for row in packet['queries']] == ['fresh-q']
    assert 'RECOVERY_LABEL_CANARY' not in json.dumps(packet)
    assert bound.provenance()['packet_revision'] == 'recovery-r1'
    assert bound.provenance()['labels_path'].endswith('retrieval-recovery/questions/held_out.json')
    questions = bound.reviewed_questions(recovery_root)
    assert questions[0]['facets'][0]['question'] == 'RECOVERY_LABEL_CANARY'
    questions[0]['query'] = 'changed returned copy'
    assert bound.reviewed_questions(recovery_root)[0]['query'] == 'synthetic recovery question'
    assert bound.runtime_packet() == packet


def test_recovery_configuration_keeps_original_development_packet(recovery_root):
    bound = binding.bind_packet(recovery_root)
    assert bound.provenance()['packet_revision'] == 'original-r1'
    assert bound.provenance()['labels_path'] == 'evaluation/questions/dev.json'
    assert bound.runtime_packet()['queries'][0]['question_id'] == 'dev'


@pytest.mark.parametrize('revision', ['unknown', None, 1, [], {}])
def test_unknown_profile_refuses_before_label_decode(packet_root, monkeypatch, revision):
    path = 'evaluation/release/V6-candidate.json'
    configuration = json.loads((packet_root/path).read_text())
    configuration['evaluation_revision'] = revision
    write(packet_root, path, configuration)
    with pytest.raises(binding.PacketBindingError, match='release_configuration_invalid'):
        binding.bind_packet(packet_root)


def test_recovery_source_gate_precedes_label_decode(recovery_root, monkeypatch):
    decoded = []
    original = binding._json
    def spy(raw):
        if b'RECOVERY_LABEL_CANARY' in raw:
            decoded.append(True)
        return original(raw)
    monkeypatch.setattr(binding, '_json', spy)
    def refuse(*args):
        raise binding.PacketBindingError('evaluation_candidate_dirty')
    monkeypatch.setattr(binding, 'verify_candidate_source', refuse)
    with pytest.raises(binding.PacketBindingError, match='candidate_dirty'):
        binding.bind_packet(recovery_root, split='held_out', allow_held_out=True)
    assert decoded == []


@pytest.mark.parametrize('kind', ['replaced_seal', 'original_seal', 'label_path', 'source', 'symlink'])
def test_recovery_profile_rejects_independent_identity_changes(recovery_root, kind):
    base = 'evaluation/review/retrieval-recovery'
    candidate_path = 'evaluation/release/V6-candidate.json'
    config = json.loads((recovery_root/candidate_path).read_text())
    if kind == 'replaced_seal':
        path = base+'/seal.json'
        seal = json.loads((recovery_root/path).read_text())
        seal['human_review']['reviewer'] = 'unapproved replacement'
        config['inputs'][path] = write(recovery_root, path, seal)
    elif kind == 'original_seal':
        path = 'evaluation/review/seal.json'
        seal = json.loads((recovery_root/path).read_text())
        seal['human_review']['reviewer'] = 'unapproved replacement'
        config['inputs'][path] = write(recovery_root, path, seal)
    elif kind == 'label_path':
        config['held_out']['path'] = 'evaluation/questions/held_out.json'
    elif kind == 'source':
        write(recovery_root, base+'/corpus/recovery.md', b'changed evidence')
    else:
        path = recovery_root/(base+'/questions/held_out.json')
        raw = path.read_bytes(); path.unlink()
        target = recovery_root/'redirected.json';target.write_bytes(raw);path.symlink_to(target)
    write(recovery_root, candidate_path, config)
    with pytest.raises(binding.PacketBindingError):
        binding.bind_packet(recovery_root, split='held_out', allow_held_out=True)


@pytest.mark.parametrize('kind', ['seal', 'labels'])
def test_synthetically_pinned_pending_recovery_is_not_approval(recovery_root, monkeypatch, kind):
    import evaluation_profiles
    base = evaluation_profiles.RECOVERY_ROOT
    seal_path = base+'/seal.json'
    seal = json.loads((recovery_root/seal_path).read_text())
    config_path = 'evaluation/release/V6-candidate.json'
    config = json.loads((recovery_root/config_path).read_text())
    if kind == 'seal':
        seal['human_review'] = dict(state='pending', reviewer=None)
    else:
        path = base+'/questions/held_out.json'
        labels = json.loads((recovery_root/path).read_text())
        labels['human_review'] = dict(state='pending', reviewer=None)
        digest = write(recovery_root, path, labels)
        next(row for row in seal['files'] if row['path'] == path)['sha256'] = digest
        config['held_out']['sha256'] = digest
    pin = write(recovery_root, seal_path, seal)
    monkeypatch.setattr(evaluation_profiles, 'RECOVERY_SEAL_SHA256', pin)
    config['inputs'][seal_path] = pin
    write(recovery_root, config_path, config)
    with pytest.raises(binding.PacketBindingError, match='approval_missing'):
        binding.bind_packet(recovery_root, split='held_out', allow_held_out=True)


def test_reviewed_questions_refuses_unissued_wrong_root_and_tampered_labels(recovery_root, tmp_path):
    fake = object.__new__(binding.BoundEvaluationPacket)
    with pytest.raises(binding.PacketBindingError, match='not_issued'):
        fake.reviewed_questions(recovery_root)
    bound = binding.bind_packet(recovery_root, split='held_out', allow_held_out=True)
    with pytest.raises(binding.PacketBindingError, match='binding_root'):
        bound.reviewed_questions(tmp_path/'other-root')
    path = 'evaluation/review/retrieval-recovery/questions/held_out.json'
    write(recovery_root, path, dict(human_review=dict(state='approved'), questions=[]))
    with pytest.raises(binding.PacketBindingError, match='input_drift'):
        bound.reviewed_questions(recovery_root)


def test_scoring_snapshot_does_not_follow_later_profile_pin_changes(recovery_root, monkeypatch):
    import evaluation_profiles
    bound = binding.bind_packet(recovery_root, split='held_out', allow_held_out=True)
    provenance = bound.provenance()
    monkeypatch.setattr(evaluation_profiles, 'RECOVERY_SEAL_SHA256', '0'*64)
    assert bound.provenance() == provenance
    assert bound.reviewed_questions(recovery_root)[0]['question_id'] == 'fresh-q'


def test_recovery_label_replacement_cannot_self_approve_with_candidate_digest(recovery_root):
    base = 'evaluation/review/retrieval-recovery'
    labels_path = base+'/questions/held_out.json'
    labels = json.loads((recovery_root/labels_path).read_text())
    labels['questions'][0]['facets'][0]['question'] = 'forged replacement label'
    digest = write(recovery_root, labels_path, labels)
    candidate_path = 'evaluation/release/V6-candidate.json'
    candidate = json.loads((recovery_root/candidate_path).read_text())
    candidate['held_out']['sha256'] = digest
    write(recovery_root, candidate_path, candidate)
    with pytest.raises(binding.PacketBindingError, match='held_out_seal'):
        binding.bind_packet(recovery_root, split='held_out', allow_held_out=True)


def test_unregistered_input_cannot_add_a_caller_selected_seal(recovery_root):
    path = 'evaluation/release/V6-candidate.json'
    candidate = json.loads((recovery_root/path).read_text())
    candidate['inputs']['evaluation/review/caller-seal.json'] = 'a'*64
    write(recovery_root, path, candidate)
    with pytest.raises(binding.PacketBindingError, match='preregistration_inputs'):
        binding.bind_packet(recovery_root)
