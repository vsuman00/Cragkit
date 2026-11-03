"""Bind label-free execution input to independently pinned reviewed profiles."""
from __future__ import annotations

from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
from weakref import WeakKeyDictionary

from check_release_readiness import check_settings
from retrieval_evaluation import validate_packet
from evaluation_profiles import ORIGINAL_INPUT_LIMITS, packet_profile, input_limits

ROOT = Path(__file__).resolve().parents[1]
APPROVED_SEAL_SHA256 = '210ddce9237847d271db35dbff1d7c74a1ba1f30323a3f4119f939a604a83f81'
_CODE_PATHS = ('packages', 'tools', 'contracts', 'evaluation/runners')
_FACTORY = object()
_BINDINGS = WeakKeyDictionary()
_INPUT_LIMITS = ORIGINAL_INPUT_LIMITS


class PacketBindingError(ValueError):
    """Fixed diagnostics with no source, query, credentials or Git output."""


def _require(condition, code):
    if not condition:
        raise PacketBindingError(code)


def _read(root, relative, limit, digest=None):
    """Confine regular-file reads and hash exactly the bytes returned to parsing."""
    path = Path(relative)
    _require(bool(path.parts) and not path.is_absolute() and '..' not in path.parts, 'evaluation_input_path')
    failed = False
    directory = None
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for component in path.parts[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            _require(stat.S_ISREG(info.st_mode) and info.st_size <= limit, 'evaluation_input_size')
            raw = stream.read(limit+1)
        _require(len(raw) <= limit, 'evaluation_input_size')
        _require(digest is None or sha256(raw).hexdigest() == digest, 'evaluation_input_drift')
    except PacketBindingError:
        raise
    except (OSError, ValueError):
        failed = True
    finally:
        if directory is not None:
            os.close(directory)
    if failed:
        raise PacketBindingError('evaluation_input_unreadable')
    return raw


def _json(raw):
    def finite(value):
        number = float(value)
        _require(math.isfinite(number), 'evaluation_json_invalid')
        return number
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'evaluation_json_invalid')
            result[key] = value
        return result
    failed = False
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_float=finite,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        _require(type(value) is dict, 'evaluation_json_invalid')
    except PacketBindingError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        failed = True
    if failed:
        raise PacketBindingError('evaluation_json_invalid')
    return value


def _git(root, *arguments, quiet=False):
    failed = False
    try:
        result = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-C', str(root), *arguments],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL if quiet else subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=10, check=False,
            env={key: value for key, value in os.environ.items() if not key.startswith('GIT_')})
        _require(result.returncode == 0, 'evaluation_candidate_source_mismatch')
        output = '' if quiet else result.stdout.decode('utf-8')
        _require(len(output) <= 65536, 'evaluation_candidate_source_mismatch')
    except PacketBindingError:
        raise
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        failed = True
    if failed:
        raise PacketBindingError('evaluation_candidate_unverifiable')
    return output.strip()


def verify_candidate_source(root, configuration):
    """Verify checkout source only; compiled artifact identity is a separate gate."""
    root = Path(root).resolve()
    _require(root == ROOT, 'evaluation_candidate_import_origin')
    commit, tree = configuration.get('source_commit'), configuration.get('package_tree')
    _require(type(commit) is str and re.fullmatch('[0-9a-f]{40}', commit) is not None
        and type(tree) is str and re.fullmatch('[0-9a-f]{40}', tree) is not None,
        'evaluation_candidate_identity')
    _require(Path(_git(root, 'rev-parse', '--show-toplevel')).resolve() == root,
             'evaluation_candidate_import_origin')
    _require(_git(root, 'rev-parse', commit+':packages') == tree, 'evaluation_candidate_package_tree')
    _git(root, 'diff', '--no-ext-diff', '--quiet', commit, '--', *_CODE_PATHS, quiet=True)
    dirty = _git(root, 'status', '--porcelain', '--untracked-files=all', '--',
                 *_CODE_PATHS, 'evaluation/release')
    _require(not dirty, 'evaluation_candidate_dirty')
    import cragkit
    _require(Path(cragkit.__file__).resolve().is_relative_to(root/'packages/python/src/cragkit'),
             'evaluation_candidate_import_origin')
    return commit


class BoundEvaluationPacket:
    """Issued immutable snapshot; live callers must invoke the binder themselves."""
    __slots__ = ('__weakref__',)

    def __init__(self, wire, split, labels_digest, commit, seal_digest, *,
                 profile=None, root=None, _factory=None):
        _require(_factory is _FACTORY, 'evaluation_binding_not_issued')
        _BINDINGS[self] = (wire, split, labels_digest, commit, seal_digest,
                           profile.revision, profile.question_path, root)

    def _binding(self):
        _require(type(self) is BoundEvaluationPacket and self in _BINDINGS, 'evaluation_binding_not_issued')
        return _BINDINGS[self]

    def runtime_packet(self):
        """Fresh copies prevent caller mutation of the approved input snapshot."""
        return json.loads(self._binding()[0])

    def provenance(self):
        wire, split, labels_digest, commit, seal_digest, revision, labels_path, _ = self._binding()
        return dict(split=split, packet_sha256=sha256(wire).hexdigest(),
            labels_sha256=labels_digest, seal_sha256=seal_digest,
            candidate_source_verified=commit is not None, source_commit=commit,
            compiled_artifacts_verified=False, held_out_opened=split == 'held_out',
            packet_revision=revision, labels_path=labels_path)


    def reviewed_questions(self, root):
        """Read the issued snapshot's approved labels for post-execution scoring."""
        _, _, digest, _, _, _, path, issued_root = self._binding()
        _require(Path(root).resolve() == issued_root, 'evaluation_binding_root')
        labels = _json(_read(issued_root, path, 262144, digest))
        _require(type(labels.get('human_review')) is dict
            and labels['human_review'].get('state') == 'approved'
            and type(labels['human_review'].get('reviewer')) is str
            and bool(labels['human_review']['reviewer'].strip())
            and type(labels.get('questions')) is list, 'evaluation_approval_missing')
        return labels['questions']


def _seal(raw, pin):
    _require(sha256(raw).hexdigest() == pin, 'evaluation_input_drift')
    seal = _json(raw)
    _require(seal.get('state') == 'sealed' and type(seal.get('human_review')) is dict
        and seal['human_review'].get('state') == 'approved'
        and type(seal['human_review'].get('reviewer')) is str
        and bool(seal['human_review']['reviewer'].strip()), 'evaluation_approval_missing')
    _require(type(seal.get('files')) is list and len(seal['files']) <= 128,
             'evaluation_seal_inventory')
    inventory = {}
    for item in seal['files']:
        _require(type(item) is dict and set(item) == {'path', 'sha256'}
            and type(item['path']) is str and item['path'].startswith('evaluation/')
            and not Path(item['path']).is_absolute() and '..' not in Path(item['path']).parts
            and item['path'] not in inventory and type(item['sha256']) is str
            and re.fullmatch('[0-9a-f]{64}', item['sha256']) is not None, 'evaluation_seal_inventory')
        inventory[item['path']] = item['sha256']
    return inventory


def bind_packet(root=ROOT, *, split='development', allow_held_out=False, require_candidate=False):
    """Read approved bytes, project runtime fields, and leave labels in the parent.

    Development defaults to an offline rehearsal. Held-out interpretation requires
    explicit selection and matching clean candidate source. Neither path makes a
    provider request or attests compiled Node output or installed artifacts.
    """
    root = Path(root).resolve()
    _require(split in ('development', 'held_out') and type(allow_held_out) is bool
             and type(require_candidate) is bool, 'evaluation_binding_configuration')
    _require(split != 'held_out' or allow_held_out, 'evaluation_held_out_not_enabled')
    configuration = _json(_read(root, 'evaluation/release/V6-candidate.json', 65536))
    failure = False
    try:
        check_settings(configuration)
        profile = packet_profile(configuration, split=split)
        held_profile = packet_profile(configuration)
        limits = input_limits(configuration)
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        failure = True
    if failure:
        raise PacketBindingError('evaluation_release_configuration_invalid')
    commit = verify_candidate_source(root, configuration) if require_candidate or split == 'held_out' else None
    inputs = configuration.get('inputs')
    _require(type(inputs) is dict and set(inputs) == set(limits), 'evaluation_preregistration_inputs')
    raw_inputs = {}
    for name, limit in limits.items():
        digest = inputs[name]
        _require(type(digest) is str and re.fullmatch('[0-9a-f]{64}', digest) is not None,
                 'evaluation_preregistration_inputs')
        raw_inputs[name] = _read(root, name, limit, digest)
    original_inventory = _seal(raw_inputs['evaluation/review/seal.json'], APPROVED_SEAL_SHA256)
    _require(original_inventory.get('evaluation/corpus/manifest.json') ==
        sha256(raw_inputs['evaluation/corpus/manifest.json']).hexdigest()
        and original_inventory.get('evaluation/questions/dev.json') ==
        sha256(raw_inputs['evaluation/questions/dev.json']).hexdigest(), 'evaluation_input_drift')
    held_pin = APPROVED_SEAL_SHA256 if held_profile.revision == 'original-r1' else held_profile.seal_sha256
    held_inventory = original_inventory if held_profile.revision == 'original-r1' else _seal(
        raw_inputs[held_profile.seal_path], held_pin)
    inventory = original_inventory if profile.revision == 'original-r1' else held_inventory
    seal_digest = APPROVED_SEAL_SHA256 if profile.revision == 'original-r1' else profile.seal_sha256
    manifest_path, question_path = profile.manifest_path, profile.question_path
    _require(manifest_path in inventory and question_path in inventory, 'evaluation_seal_inventory')
    _require(held_profile.manifest_path in held_inventory
        and held_profile.question_path in held_inventory, 'evaluation_seal_inventory')
    _require(sha256(raw_inputs[held_profile.manifest_path]).hexdigest() ==
        held_inventory[held_profile.manifest_path], 'evaluation_input_drift')
    _require(type(configuration.get('held_out')) is dict, 'evaluation_held_out_seal')
    _require(configuration['held_out'].get('path') == held_profile.question_path
        and configuration['held_out'].get('current_run_access') == 'not_opened_or_scored'
        and configuration['held_out'].get('sha256') == held_inventory[held_profile.question_path],
        'evaluation_held_out_seal')
    manifest_raw = raw_inputs[manifest_path]
    _require(sha256(manifest_raw).hexdigest() == inventory[manifest_path], 'evaluation_input_drift')
    manifest = _json(manifest_raw)
    # No held-out question JSON has been decoded before the source gate above.
    labels_raw = raw_inputs.get(question_path)
    if labels_raw is None:
        labels_raw = _read(root, question_path, 262144, inventory[question_path])
    _require(sha256(labels_raw).hexdigest() == inventory[question_path], 'evaluation_input_drift')
    labels = _json(labels_raw)
    _require(type(labels.get('human_review')) is dict
        and labels['human_review'].get('state') == 'approved'
        and type(labels['human_review'].get('reviewer')) is str
        and bool(labels['human_review']['reviewer'].strip())
        and type(labels.get('questions')) is list and type(manifest.get('documents')) is list,
        'evaluation_approval_missing')
    documents = []
    for document in manifest['documents']:
        _require(type(document) is dict, 'evaluation_document_invalid')
        if document.get('split') != split:
            continue
        _require(type(document.get('path')) is str and all(key in document for key in (
            'tenant_id', 'collection', 'document_id', 'revision_id', 'active', 'canonical_sha256')),
            'evaluation_document_invalid')
        name = profile.source_prefix+document['path']
        _require(name in inventory and inventory[name] == document['canonical_sha256'], 'evaluation_source_identity')
        raw = _read(root, name, 65536, inventory[name])
        invalid_encoding = False
        try:
            text = raw.decode('utf-8')
        except UnicodeError:
            invalid_encoding = True
        if invalid_encoding:
            raise PacketBindingError('evaluation_source_encoding')
        documents.append({key: document[key] for key in (
            'tenant_id', 'collection', 'document_id', 'revision_id', 'active', 'canonical_sha256')} | {'text': text})
    query_keys = ('question_id', 'tenant_id', 'collection', 'query', 'required_filters')
    _require(all(type(query) is dict and all(key in query for key in query_keys)
        for query in labels['questions']), 'evaluation_runtime_packet_invalid')
    queries = [{key: query[key] for key in query_keys} for query in labels['questions']]
    projected = dict(revision='EVX-r1', documents=documents, queries=queries)
    failure = False
    try:
        projected = validate_packet(projected)
    except (ValueError, TypeError, KeyError):
        failure = True
    if failure:
        raise PacketBindingError('evaluation_runtime_packet_invalid')
    wire = json.dumps(projected, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return BoundEvaluationPacket(wire, split, inventory[question_path], commit, seal_digest,
        profile=profile, root=root, _factory=_FACTORY)
