"""RST-r1: serial guarded default-import observations, never environment setup."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
from hashlib import sha256

from check_artifacts import NODE_PROBE, PYTHON_PROBE, size_tree

ROOT = Path(__file__).resolve().parents[1]
SAFE_ENV = ('PATH', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR', 'TZ')
PYTHON_WARM = '''
warm = []
for _ in range(50):
    started = time.perf_counter()
    for module in modules:
        assert importlib.import_module(module.__name__) is module
    warm.append(time.perf_counter() - started)
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps({'warm_seconds': warm,
 'peak_rss_bytes': rss if sys.platform == 'darwin' else rss * 1024}))
'''
NODE_WARM = '''
const names = ['','contracts','errors','postgres','embeddings','reranking','context',
 'packing','assessment','evidence','execution','planning','corrective','events',
 'postgres-corrective','qdrant','qdrant-source','qdrant-corrective','qdrant-publication'];
const warm = [];
for (let round = 0; round < 50; round++) {
  const started = performance.now();
  await Promise.all(names.map(name => import('cragkit'+(name ? '/'+name : ''))));
  warm.push((performance.now()-started)/1000);
}
console.log(JSON.stringify({warm_seconds:warm,peak_rss_bytes:process.resourceUsage().maxRSS*1024}));
'''


class ResourceCheckError(ValueError):
    """A fixed safe diagnostic; never include subprocess output."""


def distribution(samples):
    if (type(samples) is not list or not samples or len(samples) > 1000
            or any(type(n) not in (int, float) or not math.isfinite(n) or n <= 0 for n in samples)):
        raise ResourceCheckError('invalid_resource_samples')
    return dict(count=len(samples), median=statistics.median(samples),
                p95=sorted(samples)[math.ceil(len(samples)*.95)-1], maximum=max(samples))


def command(argv, *, cwd=None, timeout=15):
    try:
        result = subprocess.run(argv, cwd=cwd, timeout=timeout, check=False,
                                capture_output=True, env={k:os.environ[k] for k in SAFE_ENV if k in os.environ})
    except (OSError, subprocess.TimeoutExpired):
        raise ResourceCheckError('resource_child_launch_or_timeout') from None
    if result.returncode or len(result.stdout) > 131072 or len(result.stderr) > 131072:
        raise ResourceCheckError('resource_child_failed')
    return result.stdout.decode('utf-8', errors='strict')


def pressure():
    if sys.platform != 'darwin':
        raise ResourceCheckError('resource_pressure_platform_unsupported')
    status = command(['memory_pressure', '-Q'])
    match = re.search(r'System-wide memory free percentage: (\d+)%', status)
    vm = command(['vm_stat'])
    swap = re.search(r'^Swapouts:\s+(\d+)\.', vm, re.M)
    if match is None or swap is None:
        raise ResourceCheckError('resource_pressure_unknown')
    record = dict(free_percent=int(match[1]), swapout_pages=int(swap[1]))
    if record['free_percent'] < 10:
        raise ResourceCheckError('resource_pressure_stop')
    return record


def pressure_guard(records):
    current = pressure()
    # Two consecutive intervals with new swapouts indicate sustained paging.
    if (len(records) >= 2 and current['swapout_pages'] > records[-1]['swapout_pages']
            > records[-2]['swapout_pages']):
        raise ResourceCheckError('resource_swapping_stop')
    records.append(current)


def parse_probe(stdout):
    try:
        lines = stdout.splitlines()
        if len(lines) != 2:
            raise ValueError()
        fresh, warm = map(json.loads, lines)
        distribution([fresh['import_seconds']])
        if len(warm['warm_seconds']) != 50:
            raise ValueError()
        distribution(warm['warm_seconds'])
        for value in (fresh['peak_rss_bytes'], warm['peak_rss_bytes']):
            if type(value) is not int or not 0 < value < 2**53:
                raise ValueError()
        return {**fresh, **warm}
    except (ValueError, TypeError, KeyError):
        raise ResourceCheckError('invalid_resource_probe') from None


def measure(python_env: Path, node_env: Path, configuration: dict):
    pressures = []
    pressure_guard(pressures)
    targets = configuration['resource_targets']
    node_probe = node_env / 'resource_probe.mjs'
    node_source = NODE_PROBE + NODE_WARM
    if node_probe.exists() and node_probe.read_text() != node_source:
        raise ResourceCheckError('resource_probe_path_occupied')
    node_probe.write_text(node_source)
    report = dict(revision='RST-r1', state='failed', observations={}, pressure=pressures,
                  configuration_sha256=sha256(json.dumps(configuration, sort_keys=True,
                      separators=(',', ':'), ensure_ascii=False).encode()).hexdigest(),
                  probe_sha256=dict(python=sha256((PYTHON_PROBE+PYTHON_WARM).encode()).hexdigest(),
                                    node=sha256(node_source.encode()).hexdigest()))
    for runtime, argv, prefix in (
        ('python', [str(python_env/'bin/python'), '-I', '-B', '-c', PYTHON_PROBE+PYTHON_WARM], python_env),
        ('node', ['node', str(node_probe)], node_env/'node_modules'),
    ):
        samples = []
        for _ in range(5):
            pressure_guard(pressures)
            samples.append(parse_probe(command(argv, cwd=node_env)))
        logical_bytes = size_tree(prefix)
        checks = dict(import_seconds=all(s['import_seconds'] <= targets[runtime+'_default_import_seconds'] for s in samples),
            peak_rss_bytes=all(s['peak_rss_bytes'] <= targets[runtime+'_default_peak_rss_bytes'] for s in samples),
            logical_install_bytes=logical_bytes <= targets[runtime+'_core_logical_install_bytes'])
        report['observations'][runtime] = dict(samples=samples, logical_install_bytes=logical_bytes,
            fresh_seconds=distribution([s['import_seconds'] for s in samples]),
            warm_seconds=distribution([n for s in samples for n in s['warm_seconds']]), checks=checks)
    pressure_guard(pressures)
    report['state'] = 'passed' if all(all(x['checks'].values()) for x in report['observations'].values()) else 'failed'
    report['hardware'] = dict(model=command(['sysctl','-n','hw.model']).strip(),
        memory_bytes=int(command(['sysctl','-n','hw.memsize'])),
        os_version=command(['sysctl','-n','kern.osproductversion']).strip(),
        architecture=command(['uname','-m']).strip())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-env', type=Path, required=True)
    parser.add_argument('--node-env', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ResourceCheckError('resource_output_exists')
        configuration = json.loads((ROOT/'evaluation/release/V6-candidate.json').read_text())
        result = measure(args.python_env.resolve(), args.node_env.resolve(), configuration)
        with args.output.open('x') as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write('\n')
        print(json.dumps(dict(state=result['state'], revision='RST-r1')))
        return 0 if result['state'] == 'passed' else 1
    except (ResourceCheckError, OSError, ValueError):
        print('resource_measurement_failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
