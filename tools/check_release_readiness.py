"""Check frozen V6 preregistration without evaluating or opening held-out labels."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODES = ['lexical', 'dense', 'hybrid', 'reranked_hybrid', 'corrective']


class ReleaseConfigurationError(ValueError):
    """A missing or contradictory preregistration must block evaluation."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ReleaseConfigurationError(code)


def local_path(root: Path, value: object) -> Path:
    require(type(value) is str, 'invalid_input_path')
    path = root / str(value)
    require(not path.is_symlink() and path.resolve().is_relative_to(root.resolve()), 'unsafe_input_path')
    return path


def check_settings(configuration: dict[str, Any]) -> None:
    """Validate frozen parameters without reading files or interpreting labels."""
    require(type(configuration) is dict, 'configuration_shape')
    for name in ('license', 'comparison', 'quality_targets', 'request_limits', 'live_limits', 'resource_targets'):
        require(type(configuration.get(name)) is dict, 'configuration_shape')
    require(configuration.get('revision') == 'V6-release-r1'
            and configuration.get('configuration_state') == 'frozen_before_held_out_run', 'unfrozen_configuration')
    require(configuration.get('license', {}).get('spdx') == 'MIT', 'unresolved_license')
    comparison = configuration.get('comparison', {})
    require(comparison.get('modes') == MODES and comparison.get('k') == 5
            and comparison.get('metric_version') == 'V6-reviewed-span-r1', 'comparison_incomplete')
    embedding, reranking = comparison.get('live_embeddings'), comparison.get('live_reranking')
    require(type(embedding) is dict and embedding.get('provider') == 'openai'
            and embedding.get('model') == 'text-embedding-3-small' and embedding.get('dimensions') == 1536
            and type(reranking) is dict and reranking.get('provider') == 'cohere'
            and reranking.get('model') == 'rerank-v5.0-fast', 'unfrozen_provider_profiles')
    targets = configuration.get('quality_targets', {})
    require(all(type(targets.get(key)) is int and targets[key] == 0 for key in
                ('invariant_violations', 'operational_failures', 'false_sufficient_count')), 'weakened_invariant_target')
    require(all(type(targets.get(key)) in (int, float) and targets[key] >= 0 for key in (
        'minimum_hybrid_document_recall_minus_lexical',
        'minimum_reranked_mrr_minus_same_shortlist_hybrid',
        'minimum_corrective_support_recall_minus_reranked')), 'quality_targets_missing')
    limits = configuration.get('request_limits', {})
    require(limits.get('concurrency') == 1 and limits.get('runtime_pool_clients') == 2
            and limits.get('deadline_ms') == 25000 and limits.get('max_candidates') == 15
            and limits.get('max_attempts') == 3 and limits.get('max_subqueries') == 3
            and limits.get('max_provider_calls') == 8 and limits.get('max_context_tokens') == 20000
            and limits.get('envelope_reserve_tokens') == 256, 'unfrozen_request_limits')
    live = configuration.get('live_limits', {})
    require(live.get('concurrency') == 1 and live.get('retries') == 0
            and live.get('total_admission_usd') == 0.02
            and live.get('embedding_admission_usd') == live.get('rerank_admission_usd') == 0.01
            and live.get('max_calls') == 60, 'unfrozen_live_limits')
    resources = configuration.get('resource_targets', {})
    require(all(type(resources.get(name)) in (float, int) and resources[name] > 0 for name in (
        'python_default_import_seconds', 'node_default_import_seconds',
        'python_default_peak_rss_bytes', 'node_default_peak_rss_bytes',
        'python_core_logical_install_bytes', 'node_core_logical_install_bytes')), 'resource_targets_missing')


def check_configuration(root: Path, configuration: dict[str, Any]) -> dict[str, Any]:
    check_settings(configuration)
    inputs = configuration.get('inputs', {})
    required = {'evaluation/corpus/manifest.json', 'evaluation/questions/dev.json',
                'evaluation/review/seal.json', 'evaluation/runners/benchmark_metrics.py',
                'evaluation/release/V6-metrics.md', 'evaluation/release/V6-baselines.json'}
    require(type(inputs) is dict and set(inputs) == required, 'missing_frozen_inputs')
    for name, digest in inputs.items():
        path = local_path(root, name)
        require(path.is_file() and sha256(path.read_bytes()).hexdigest() == digest, 'frozen_input_drift')
    seal = json.loads(local_path(root, 'evaluation/review/seal.json').read_text())
    require(seal.get('state') == 'sealed' and seal.get('human_review', {}).get('state') == 'approved', 'review_not_approved')
    held = configuration.get('held_out', {})
    require(held.get('path') == 'evaluation/questions/held_out.json'
            and held.get('current_run_access') == 'not_opened_or_scored', 'held_out_access_not_preregistered')
    sealed = [entry for entry in seal['files'] if entry['path'] == held['path']]
    require(len(sealed) == 1 and sealed[0]['sha256'] == held.get('sha256'), 'held_out_seal_mismatch')
    # The digest comes from the human-review seal. Never open held_out.json here.
    coverage = json.loads(local_path(root, 'evaluation/release/V6-coverage.json').read_text())
    rows = coverage['requirements'] + coverage['edge_cases']
    expected_edges = set(re.findall(r'^\| (E\d+) \|', local_path(root, 'tasks/EDGE_CASES.md').read_text(), re.M))
    expected = {f'BR-{number:02}' for number in range(1, 11)} | expected_edges
    require(len(rows) == len(expected) and {row['id'] for row in rows} == expected, 'coverage_inventory_incomplete')
    for row in rows:
        require(bool(row['owner']) and bool(row['state']) and bool(row['limitations']), 'coverage_owner_missing')
        for evidence in row['evidence']:
            require(local_path(root, evidence).is_file(), 'coverage_evidence_missing')
    return {'state': 'configuration_verified', 'revision': configuration['revision'],
            'input_digests': len(inputs), 'requirements': 10, 'edge_cases': len(expected_edges),
            'held_out_opened': False, 'release_readiness': 'not_proven_by_preregistration'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configuration', type=Path, default=ROOT / 'evaluation/release/V6-candidate.json')
    args = parser.parse_args()
    try:
        configuration = json.loads(args.configuration.read_text())
        result = check_configuration(ROOT, configuration)
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({'state': 'failed', 'code': 'release_configuration_invalid'}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
