"""EBC-r1: a fixed, offline bridge from the historical ECR-r1 to CI products.

Run with the target wheel's isolated Python (-I -B). Only target/tools is added
to its import path. The old interpreter verifies the unchanged original ECR and
issues its sealed, label-free packet. Fixed hashes bind the retained live files;
the private journal additionally verifies every request/completion/response.
Target source, exact CI core products, imported wheel files, Node dist, locked
dependencies and tokenizer are checked before and after serial native replay.
Only timing is normalized. This is recorded-output compatibility, never new
live quality evidence; run_release_evaluation's same-ECR guard is unchanged.
"""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tomllib
import zipfile

SOURCE = '0c7c568d5cb71638eebab2dea97c5973b0f8cc08'
TREE = '60a251c2bf94402cb562d0398403c218875454f3'
BASE_SOURCE = '25275e447c64ecfd243ef6bc26c87031d5e2e472'
BASE_IDENTITY = '59af39c6cb0a5d118c73511dbb67b5fd22b2289a731ffeaaa5fc488d4105b993'
CI_ARCHIVE = '37b5fbcadc65be97556d885810a598e791b4321ba2ef9d3868877e2a67e4b17b'
WHEEL = 'sdks/core/python/cragkit-1.0.0rc1-py3-none-any.whl'
NPM = 'sdks/core/npm/cragkit-1.0.0-rc.1.tgz'
RETAINED = {
    'run-binding.json': 'fed3fb7d599a42d0938e24cae5bafa4b8a9151b8b896cf642f3bde77d22ff2a5',
    'provider-accounting.json': 'c6d2d76b1ee4aa4a9de3d748e4b5a5cd0080834f7ff576ca21b790e2fb0516c3',
    'python_live.json': 'd0dd734e626da08b957a519558644e6979f5e5573936a8b21cfb4b96f3212ebf',
    'recordings/seal.json': '65d10033aba64d5179b442b59e8776e78257bef460f9250dc1222ab295d36275',
}
_PHASE = 'arguments'


def require(condition):
    if not condition:
        raise ValueError('recorded_compatibility_invalid')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def read(path, limit=16 * 1024 * 1024):
    from evaluation_runtime import _regular_bytes
    return _regular_bytes(path, limit)


def decoded(raw):
    from evaluation_packet import _json
    return _json(raw)


def environment():
    return {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR', 'TZ')
            if key in os.environ}


def command(argv, cwd, *, timeout=180):
    result = subprocess.run(argv, cwd=cwd, env=environment(), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    require(result.returncode == 0 and len(result.stdout) <= 1024 * 1024)
    return result.stdout


def baseline(root, receipt):
    # Separate process keeps old source imports and dependency identity intact.
    script = '''import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(sys.argv[1])/'tools'))
from evaluation_runtime import verify_runtime
from evaluation_packet import bind_packet
root=pathlib.Path(sys.argv[1]); identity=verify_runtime(root, pathlib.Path(sys.argv[2]))
bound=bind_packet(root, split='held_out', allow_held_out=True, require_candidate=True)
print(json.dumps(dict(identity=identity['identity_sha256'], source=identity['source_commit'],
    packet=bound.runtime_packet(), provenance=bound.provenance())))
'''
    value = decoded(command([str(root/'packages/python/.venv/bin/python'), '-I', '-B', '-c',
        script, str(root), str(receipt)], root))
    require(value['identity'] == BASE_IDENTITY and value['source'] == BASE_SOURCE)
    return value


def source(root):
    def git(*arguments):
        return command(['git', '-c', 'core.fsmonitor=false', '-C', str(root), *arguments], root).decode().strip()
    require(git('rev-parse', 'HEAD') == SOURCE and git('rev-parse', 'HEAD:packages') == TREE)
    paths = ('packages', 'tools', 'contracts', 'evaluation/runners', 'evaluation/release')
    require(not git('status', '--porcelain', '--untracked-files=all', '--', *paths))
    git('diff', '--no-ext-diff', '--quiet', SOURCE, '--', *paths)


def retained(live, bound):
    from provider_journal import load_recordings
    values = {}
    for name, digest in RETAINED.items():
        raw = read(live/name)
        require(sha256(raw).hexdigest() == digest)
        values[name] = decoded(raw)
    binding, accounting = values['run-binding.json'], values['provider-accounting.json']
    require(binding == dict(revision='ECR-r1', mode='live', packet=bound['provenance'],
        runtime_identity_sha256=BASE_IDENTITY))
    require(accounting['evidence_kind'] == 'live' and accounting['failed'] is False
        and accounting['cleanup_verified'] is True and accounting['budget']['attempts'] == 39
        and accounting['budget']['pending'] == 0 and accounting['journal'] == dict(
            evidence_kind='live', attempts=39, completed=39, pending=0, failed=False, sealed=True))
    tape = load_recordings(live/'recordings')
    require(len(tape) == 39)
    return tape, values['python_live.json']


def product_paths(bundle, metadata, archive):
    require(metadata['revision'] == 'CIB-r1' and metadata['state'] == 'passed'
        and metadata['source_commit'] == SOURCE and metadata['archive_sha256'] == CI_ARCHIVE)
    require(sha256(read(archive)).hexdigest() == CI_ARCHIVE)
    products = metadata['products']
    require(type(products) is list and len({row['path'] for row in products}) == len(products))
    selected = {}
    for name in (WHEEL, NPM):
        rows = [row for row in products if row['path'] == name]
        require(len(rows) == 1)
        raw = read(bundle/name)
        require(len(raw) == rows[0]['bytes'] and sha256(raw).hexdigest() == rows[0]['sha256'])
        with zipfile.ZipFile(archive) as hosted:
            require(hosted.namelist().count(name) == 1 and hosted.getinfo(name).file_size == len(raw))
            require(hosted.read(name) == raw)
        selected[name] = rows[0]['sha256']
    return selected


def package_files(archive, prefix, *, wheel=False):
    result = {}
    if wheel:
        with zipfile.ZipFile(archive) as product:
            rows = product.infolist()
            require(len(rows) <= 2000)
            for row in rows:
                if row.filename.startswith(prefix) and not row.is_dir():
                    require(row.file_size <= 2 * 1024 * 1024)
                    require(row.filename not in result)
                    result[row.filename] = sha256(product.read(row)).hexdigest()
    else:
        with tarfile.open(archive, 'r:gz') as product:
            for ordinal, row in enumerate(product):
                require(ordinal < 2000)
                if row.name.startswith(prefix) and not row.isdir():
                    require(row.isfile() and row.size <= 2 * 1024 * 1024 and row.name not in result)
                    result[row.name] = sha256(product.extractfile(row).read()).hexdigest()
    require(bool(result) and all('..' not in Path(name).parts for name in result))
    return {name.removeprefix(prefix): digest for name, digest in result.items()}


def target(root, bundle, metadata, archive):
    from evaluation_runtime import _Inventory, TOKENIZER_SHA256, _versions
    import cragkit
    source(root)
    products = product_paths(bundle, metadata, archive)
    require(Path(sys.prefix).resolve() == (root/'packages/python/.venv').resolve())
    site = Path(cragkit.__file__).resolve().parent.parent
    require(site.is_relative_to(Path(sys.prefix).resolve())
        and not site.is_relative_to(root/'packages/python/src'))
    inventory = _Inventory()
    inventory.tree('python_dependencies', site)
    expected = package_files(bundle/WHEEL, 'cragkit/', wheel=True)
    actual = {key.removeprefix('python_dependencies/cragkit/'): digest
        for key, digest in inventory.files.items() if key.startswith('python_dependencies/cragkit/')}
    require(actual == expected)
    inventory.tree('node_dist', root/'packages/typescript/dist')
    require({key.removeprefix('node_dist/'): digest for key, digest in inventory.files.items()
        if key.startswith('node_dist/')} == package_files(bundle/NPM, 'package/dist/'))
    inventory.tree('node_dependencies', (root/'packages/typescript/node_modules').resolve())
    locks = tomllib.loads(read(root/'packages/python/uv.lock').decode())
    versions = {re.sub('[-_.]+', '-', row['name']).lower(): row['version'] for row in locks['package']}
    installed = [(re.sub('[-_.]+', '-', row.metadata['Name']).lower(), row.version)
        for row in importlib.metadata.distributions(path=[str(site)])]
    require(len(dict(installed)) == len(installed) and all(versions.get(name) == version
        for name, version in installed))
    project = decoded(read(root/'packages/typescript/package-lock.json'))['packages']
    installed_node = decoded(read(root/'packages/typescript/node_modules/.package-lock.json'))['packages']
    require(all(path in installed_node for path, row in project.items() if path and not row.get('optional')))
    for path, row in installed_node.items():
        require(path.startswith('node_modules/') and project.get(path) == row)
        require(decoded(read(root/'packages/typescript'/path/'package.json'))['version'] == row['version'])
    for name, module in tuple(sys.modules.items()):
        if name == 'cragkit' or name.startswith('cragkit.'):
            require(Path(module.__file__).resolve().is_relative_to(site/'cragkit'))
    for name in ('python', 'node'):
        inventory.file('toolchain/'+name, Path(sys.executable).resolve() if name == 'python'
            else Path(shutil.which('node')).resolve())
    tokenizer = read(root/'artifacts/tokenizers/cl100k_base.tiktoken', 2000000)
    require(sha256(tokenizer).hexdigest() == TOKENIZER_SHA256)
    configuration = decoded(read(root/'evaluation/release/V6-candidate.json'))
    return dict(source_commit=SOURCE, package_tree=TREE, products=products,
        runtime_versions=_versions(root, configuration), files=inventory.files,
        tokenizer_sha256=TOKENIZER_SHA256)


def compare(packet, original, observed, runtime, kind, counter):
    from run_release_evaluation import check_observation, normalized
    from cragkit.embeddings import OPENAI_PROFILE
    require(observed.get('revision') == 'EVX-r1' and observed.get('runtime') == runtime
        and observed.get('kind') == kind and len(observed['rows']) == 30
        and len(observed['receipts']) == 5
        and not any(row['result'].get('operational_failure') for row in observed['rows']))
    check_observation(packet, observed, profile=OPENAI_PROFILE, counter=counter)
    require(normalized(observed) == normalized(original))


async def resources(args, root, identity):
    global _PHASE
    from measure_native_resources import execute, validate_observation
    from measure_default_resources import pressure_guard
    from postgres_vector_fixture import V6PostgresFixture
    from run_release_evaluation import save
    targets = decoded(read(root/'evaluation/release/V6-candidate.json'))['resource_targets']
    observations, pressures = [], []
    for runtime in ('python', 'node'):
        _PHASE = 'resource_'+runtime
        pressure_guard(pressures)
        with V6PostgresFixture(args.prepared_postgres_bin, args.output/('resource-'+runtime)) as fixture:
            address = fixture.config['host'], fixture.config['port']
            value = await execute(fixture, runtime, root, pressures)
            observations.append(validate_observation(value, runtime, targets))
        try:
            connection = socket.create_connection(address, timeout=.2)
        except ConnectionRefusedError:
            pass
        else:
            connection.close()
            require(False)
        save(args.output/('resource-'+runtime+'.json'), observations[-1])
        pressure_guard(pressures)
    return dict(revision='RST-r1', state='passed', evidence_kind='local_postgres_fake_providers',
        target_identity_sha256=sha256(encoded(identity)).hexdigest(),
        observations=observations, pressure=pressures, cleanup_verified=True, live_provider_calls=0,
        new_live_quality_evidence=False)


async def run(args):
    global _PHASE
    require(sys.dont_write_bytecode and sys.flags.isolated)
    require(not any(os.environ.get(key) for key in ('PYTHONPATH', 'PYTHONHOME', 'NODE_PATH', 'NODE_OPTIONS')))
    root = args.target_root.resolve()
    _PHASE = 'target_source'
    source(root)
    sys.path.insert(0, str(root/'tools'))
    _PHASE = 'target_imports'
    from run_release_evaluation import execute, save, check_observation
    from cragkit.context import Cl100kCounter
    from cragkit.embeddings import OPENAI_PROFILE
    from provider_adapters import ReplaySend
    require(Path(sys.modules['run_release_evaluation'].__file__).resolve() == root/'tools/run_release_evaluation.py')
    _PHASE = 'baseline_runtime'
    bound = baseline(args.baseline_root.resolve(), args.baseline_runtime.resolve())
    _PHASE = 'retained_tape'
    tape, original = retained(args.baseline_live.resolve(), bound)
    _PHASE = 'target_products'
    metadata = decoded(read(args.bundle_metadata))
    metadata = metadata.get('bundle', metadata)
    before = target(root, args.bundle_root.resolve(), metadata, args.bundle_archive)
    counter = Cl100kCounter.from_file(root/'artifacts/tokenizers/cl100k_base.tiktoken')
    _PHASE = 'baseline_observation'
    check_observation(bound['packet'], original, profile=OPENAI_PROFILE, counter=counter)
    _PHASE = 'output_create'
    args.output.mkdir(mode=0o700)
    for runtime, kind in (('python', 'provider'), ('node', 'replay')):
        _PHASE = runtime+'_replay'
        replay = ReplaySend(tape) if runtime == 'python' else None
        observed = await execute(bound['packet'], args.prepared_postgres_bin,
            args.output/runtime, runtime=runtime, kind=kind, send=replay, tape=tape if runtime == 'node' else None)
        if replay is not None:
            replay.assert_complete()
        compare(bound['packet'], original, observed, runtime, kind, counter)
        save(args.output/(runtime+'.json'), observed)
        _PHASE = runtime+'_target_recheck'
        require(target(root, args.bundle_root.resolve(), metadata, args.bundle_archive) == before)
    resource_result = await resources(args, root, before) if args.include_resources else None
    _PHASE = 'target_final'
    require(target(root, args.bundle_root.resolve(), metadata, args.bundle_archive) == before)
    # Revalidate all retained files and response hashes after both native runs.
    retained(args.baseline_live.resolve(), bound)
    _PHASE = 'write_result'
    result = dict(revision='EBC-r1', state='passed', evidence_kind='recorded_output_compatibility',
        baseline_runtime_identity_sha256=BASE_IDENTITY, baseline_source_commit=BASE_SOURCE,
        packet=bound['provenance'], target=before, retained_sha256=RETAINED,
        rows_per_runtime=30, receipts_per_runtime=5, consumed_calls_per_runtime=39,
        normalized_parity=True, live_http_calls_this_run=0, new_live_quality_evidence=False,
        cleanup_verified=True, resources=resource_result)
    result['identity_sha256'] = sha256(encoded(result)).hexdigest()
    save(args.output/'results.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline-root', 'baseline-runtime', 'baseline-live', 'target-root',
            'bundle-root', 'bundle-metadata', 'bundle-archive', 'prepared-postgres-bin', 'output'):
        parser.add_argument('--'+name, required=True, type=Path)
    parser.add_argument('--allow-local-processes', required=True, action='store_true')
    parser.add_argument('--include-resources', action='store_true')
    try:
        result = asyncio.run(run(parser.parse_args(argv)))
        print(json.dumps({key: result[key] for key in ('revision', 'state', 'identity_sha256')}))
        return 0
    except Exception:
        print(json.dumps(dict(revision='EBC-r1', state='failed', code='recorded_compatibility_invalid', phase=_PHASE)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
