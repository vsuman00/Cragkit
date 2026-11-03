"""Explicit reviewed packet identities; no caller paths, files or provider I/O."""
from dataclasses import dataclass

ORIGINAL_SEAL_SHA256 = '210ddce9237847d271db35dbff1d7c74a1ba1f30323a3f4119f939a604a83f81'
RECOVERY_SEAL_SHA256 = '46a7e1bba338ff205d6d5e49f45a61db9cca3f0c8acb81b9c70d51870fd5e195'
RECOVERY_ROOT = 'evaluation/review/retrieval-recovery'
ORIGINAL_INPUT_LIMITS = {
    'evaluation/corpus/manifest.json': 131072,
    'evaluation/questions/dev.json': 262144,
    'evaluation/review/seal.json': 65536,
    'evaluation/runners/benchmark_metrics.py': 131072,
    'evaluation/release/V6-metrics.md': 65536,
    'evaluation/release/V6-baselines.json': 65536,
}


@dataclass(frozen=True, slots=True)
class PacketProfile:
    revision: str
    manifest_path: str
    question_path: str
    seal_path: str
    source_prefix: str
    seal_sha256: str


def evaluation_revision(configuration):
    if type(configuration) is not dict:
        raise ValueError('evaluation_profile_invalid')
    revision = configuration.get('evaluation_revision', 'original-r1')
    if type(revision) is not str or revision not in ('original-r1', 'recovery-r1'):
        raise ValueError('evaluation_profile_invalid')
    return revision


def packet_profile(configuration, *, split='held_out'):
    revision = evaluation_revision(configuration)
    if split not in ('development', 'held_out'):
        raise ValueError('evaluation_profile_invalid')
    if split == 'development' or revision == 'original-r1':
        filename = 'dev.json' if split == 'development' else 'held_out.json'
        return PacketProfile('original-r1', 'evaluation/corpus/manifest.json',
            'evaluation/questions/' + filename, 'evaluation/review/seal.json',
            'evaluation/corpus/', ORIGINAL_SEAL_SHA256)
    return PacketProfile('recovery-r1', RECOVERY_ROOT + '/corpus/manifest.json',
        RECOVERY_ROOT + '/questions/held_out.json', RECOVERY_ROOT + '/seal.json',
        RECOVERY_ROOT + '/corpus/', RECOVERY_SEAL_SHA256)


def input_limits(configuration):
    revision = evaluation_revision(configuration)
    limits = dict(ORIGINAL_INPUT_LIMITS)
    if revision == 'recovery-r1':
        limits[RECOVERY_ROOT + '/corpus/manifest.json'] = 131072
        limits[RECOVERY_ROOT + '/seal.json'] = 65536
    return limits
