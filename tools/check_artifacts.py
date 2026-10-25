"""Build and inspect internal artifacts, then probe isolated default installations."""
from __future__ import annotations

import argparse
import email.parser
import hashlib
import json
import os
import shutil
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


class ArtifactError(RuntimeError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise ArtifactError(code)


def safe_member(name: str) -> None:
    path = PurePosixPath(name)
    forbidden = {'.venv', 'node_modules', '__pycache__', '.git', '.pytest_cache', '.mypy_cache',
                 '.cache', 'models', 'model-cache', 'credentials', 'secrets'}
    require(bool(name) and not path.is_absolute() and '\\' not in name
            and '..' not in path.parts and not any(':' in part for part in path.parts), 'unsafe_archive_path')
    require(not any(part in forbidden or part.startswith('.env') or part.endswith(('.pyc', '.pem', '.key', '.safetensors', '.onnx', '.gguf'))
                    for part in path.parts), 'forbidden_archive_content')


def archive_files(path: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    total = 0
    if path.suffix == '.whl':
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                safe_member(member.filename)
                require((member.external_attr >> 16) & 0o170000 != 0o120000, 'archive_symlink')
                if member.is_dir():
                    continue
                require(member.filename not in files, 'duplicate_archive_member')
                total += member.file_size
                require(total <= 32 * 1024 * 1024 and len(files) < 2048, 'archive_size_limit')
                files[member.filename] = archive.read(member)
    else:
        with tarfile.open(path, 'r:*') as archive:
            for member in archive:
                safe_member(member.name)
                require(member.isdir() or member.isfile(), 'archive_special_member')
                if member.isdir():
                    continue
                require(member.name not in files, 'duplicate_archive_member')
                total += member.size
                require(total <= 32 * 1024 * 1024 and len(files) < 2048, 'archive_size_limit')
                source = archive.extractfile(member)
                require(source is not None, 'archive_read')
                assert source is not None
                files[member.name] = source.read()
    return files


def inspect_wheel(path: Path) -> dict[str, bytes]:
    files = archive_files(path)
    require({'cragkit/__init__.py', 'cragkit/py.typed', 'cragkit/contracts/__init__.py', 'cragkit/contracts/results.py', 'cragkit/errors.py', 'cragkit/postgres.py', 'cragkit/embeddings.py', 'cragkit/vector_ingestion.py', 'cragkit/reranking.py', 'cragkit/context.py', 'cragkit/packing.py', 'cragkit/assessment.py', 'cragkit/evidence.py'} <= files.keys(), 'wheel_missing_core')
    names = [name for name in files if name.endswith('.dist-info/METADATA')]
    require(len(names) == 1, 'wheel_metadata')
    metadata = email.parser.BytesParser().parsebytes(files[names[0]])
    require(metadata['Name'] == 'cragkit' and metadata['Version'] == '0.0.0', 'wheel_identity')
    requirements = metadata.get_all('Requires-Dist', [])
    core = [entry for entry in requirements if 'extra ==' not in entry]
    require(core == ['pydantic==2.14.1'], 'wheel_core_dependencies')
    optional = [entry for entry in requirements if 'extra ==' in entry]
    require(all(('postgres' in entry and entry.startswith(('psycopg[', 'psycopg-pool'))) or ('tokenizers' in entry and entry.startswith('tiktoken==0.14.0')) for entry in optional), 'wheel_optional_dependencies')
    return files


def inspect_npm(path: Path) -> dict[str, bytes]:
    files = archive_files(path)
    require('package/package.json' in files, 'npm_metadata')
    package = json.loads(files['package/package.json'])
    require(package['name'] == 'cragkit' and package['version'] == '0.0.0' and package.get('private') is True, 'npm_identity')
    require(package.get('dependencies') == {'zod': '4.6.7'}, 'npm_core_dependencies')
    for name in ('.', './contracts', './errors', './postgres', './embeddings', './reranking', './context', './packing', './assessment', './evidence'):
        target = package.get('exports', {}).get(name, {})
        for kind, suffix in (('import', '.js'), ('types', '.d.ts')):
            value = target.get(kind)
            require(isinstance(value, str) and value.startswith('./dist/') and value.endswith(suffix), 'npm_export_target')
            require('package/' + value[2:] in files, 'npm_missing_export')
    return files


def size_tree(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob('*') if item.is_file() and not item.is_symlink())


def run(command: list[str], cwd: Path, commands: list[dict[str, Any]], timeout: int = 120, *, environment: dict[str, str] | None = None) -> str:
    record: dict[str, Any] = {'argv': command, 'cwd': str(cwd), 'timeout_seconds': timeout}
    commands.append(record)
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False,
                                env={**os.environ, 'UV_PYTHON_DOWNLOADS': 'never', 'PIP_DISABLE_PIP_VERSION_CHECK': '1', **(environment or {})})
    except (OSError, subprocess.TimeoutExpired):
        record['result'] = 'launch_or_timeout_failure'
        raise ArtifactError('command_launch_or_timeout') from None
    record['returncode'] = result.returncode
    require(result.returncode == 0, 'command_failed')
    return result.stdout


PYTHON_PROBE = r'''
import importlib, importlib.metadata, importlib.util, json, pathlib, resource, sys, time
optional = ('psycopg', 'psycopg_pool', 'torch', 'transformers', 'qdrant_client', 'langchain', 'mcp', 'tiktoken')
assert all(importlib.util.find_spec(name) is None for name in optional)
def audit(event, args):
    if event.startswith(('socket.', 'subprocess.')) or event in ('os.system', 'os.posix_spawn'):
        raise RuntimeError('Import attempted external I/O')
sys.addaudithook(audit)
start = time.perf_counter()
modules = [importlib.import_module(name) for name in ('cragkit', 'cragkit.contracts', 'cragkit.errors', 'cragkit.postgres', 'cragkit.embeddings', 'cragkit.reranking', 'cragkit.context', 'cragkit.packing', 'cragkit.assessment', 'cragkit.evidence')]
elapsed = time.perf_counter() - start
assert modules[0].__version__ == '0.0.0'
assert all(pathlib.Path(module.__file__).resolve().is_relative_to(pathlib.Path(sys.prefix).resolve()) for module in modules)
assert modules[1].parse_request({'query': 'smoke', 'collection': 'smoke'}).query == 'smoke'
assert modules[1].parse_result({'request_id': 'smoke', 'status': 'insufficient'}).usage.cost_usd is None
assert modules[2].InvalidRequest().to_dict()['code'] == 'invalid_request'
assert callable(modules[3].PostgresRetriever)
assert callable(modules[3].PostgresVectorIndexer)
assert callable(modules[3].VectorIngestionReceipt)
assert callable(modules[4].EmbeddingAdapter)
assert callable(modules[5].RerankingAdapter)
assert modules[6].count_context([], max_tokens=1000)["counting_mode"] == "estimated"
assert callable(modules[7].pack_evidence)
assert modules[8].assess_evidence("smoke", [])["status"] == "insufficient"
assert callable(modules[9].pack_and_assess)
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps({'import_seconds': elapsed, 'peak_rss_bytes': rss if sys.platform == 'darwin' else rss * 1024,
 'platform': sys.platform, 'python': sys.version.split()[0],
 'installed': sorted((dist.metadata['Name'], dist.version) for dist in importlib.metadata.distributions())}))
'''

NODE_PROBE = r'''
import assert from 'node:assert/strict';
import { createRequire, syncBuiltinESMExports } from 'node:module';
import http from 'node:http'; import https from 'node:https'; import net from 'node:net';
import tls from 'node:tls'; import dns from 'node:dns'; import dgram from 'node:dgram'; import childProcess from 'node:child_process';
const require = createRequire(import.meta.url);
for (const name of ['pg', 'postgres', 'onnxruntime-node', '@qdrant/js-client-rest', 'langchain', '@modelcontextprotocol/sdk', 'tiktoken']) {
  assert.throws(() => require.resolve(name));
}
const deny = () => { throw Error('Import attempted external I/O'); };
globalThis.fetch = deny; globalThis.WebSocket = deny;
for (const [object, names] of [[http,['request','get','createServer']],[https,['request','get','createServer']],
  [net,['connect','createConnection','createServer']],[net.Socket.prototype,['connect']],[dns,['lookup','resolve']],[dns.promises,['lookup','resolve']],[tls,['connect','createServer']],[dgram,['createSocket']],
  [childProcess,['spawn','spawnSync','exec','execSync','execFile','execFileSync','fork']]]) {
  for (const name of names) object[name] = deny;
}
syncBuiltinESMExports();
const start = performance.now();
const [core, contracts, errors, postgres, embeddings, reranking, context, packing, assessment, evidence] = await Promise.all([import('cragkit'), import('cragkit/contracts'), import('cragkit/errors'), import('cragkit/postgres'), import('cragkit/embeddings'), import('cragkit/reranking'), import('cragkit/context'), import('cragkit/packing'), import('cragkit/assessment'), import('cragkit/evidence')]);
const importSeconds = (performance.now()-start)/1000;
assert.equal(core.version,'0.0.0');
assert.equal(contracts.parse_result({request_id:'smoke',status:'insufficient'}).usage.cost_usd,null);
assert.equal(contracts.parse_request({query:'smoke',collection:'smoke'}).query,'smoke');
assert.equal(new errors.InvalidRequest().code,'invalid_request');
assert.equal(typeof postgres.PostgresRetriever,'function');
assert.equal(typeof postgres.PostgresVectorIndexer,'function');
assert.equal(typeof embeddings.EmbeddingAdapter,'function');
assert.equal(typeof reranking.RerankingAdapter,'function');
assert.equal(context.count_context([],{max_tokens:1000}).counting_mode,'estimated');
assert.equal(typeof packing.pack_evidence,'function');
assert.equal(assessment.assess_evidence('smoke',[]).status,'insufficient');
assert.equal(typeof evidence.pack_and_assess,'function');
console.log(JSON.stringify({import_seconds:importSeconds,peak_rss_bytes:process.resourceUsage().maxRSS*1024,node:process.version}));
'''


def artifact_record(path: Path, files: dict[str, bytes]) -> dict[str, Any]:
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'file_count': len(files), 'unpacked_bytes': sum(map(len, files.values()))}


def installed_evidence(root: Path, work: Path, python: Path, node_env: Path,
                       commands: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare complete native contract results from installed artifacts."""
    fixtures = root / 'contracts/fixtures'
    tokenizer = root / 'artifacts/tokenizers/cl100k_base.tiktoken'
    python_probe, node_probe = work / 'probe_installed_evidence.py', node_env / 'probe_installed_evidence.mjs'
    shutil.copyfile(root / 'tools/probe_installed_evidence.py', python_probe)
    shutil.copyfile(root / 'tools/probe_installed_evidence.mjs', node_probe)
    py_prefix = python.parent.parent
    node_prefix = node_env / 'node_modules/cragkit'
    py_result = json.loads(run([str(python), '-I', '-B', str(python_probe), '--fixtures', str(fixtures),
        '--tokenizer', str(tokenizer), '--prefix', str(py_prefix)], work, commands))
    node_result = json.loads(run(['node', str(node_probe), '--fixtures', str(fixtures),
        '--tokenizer', str(tokenizer), '--prefix', str(node_prefix)], node_env, commands))
    require(py_result == node_result and py_result.get('revision') == 'INST-r1', 'installed_evidence_parity')
    counts = {'source_cases': len(py_result['source_cases']), 'context_cases': len(py_result['context']['cases']),
        'token_cases': len(py_result['context']['token_counts']), 'packing_cases': len(py_result['packing']),
        'assessment_cases': len(py_result['assessment']), 'pipeline_cases': len(py_result['pipeline'])}
    expected = {
        'source_cases': len(json.loads((fixtures / 'retrieval.json').read_text())['source_cases']),
        'context_cases': len(json.loads((fixtures / 'context.json').read_text())['cases']),
        'token_cases': len(json.loads((fixtures / 'context.json').read_text())['token_cases']),
        'packing_cases': len(json.loads((fixtures / 'packing.json').read_text())['cases']),
        'assessment_cases': len(json.loads((fixtures / 'assessment.json').read_text())['cases']),
        'pipeline_cases': len(json.loads((fixtures / 'evidence-pipeline.json').read_text())['cases']),
    }
    require(counts == expected, 'installed_evidence_counts')
    python_example, node_example = work / 'evidence.py', node_env / 'evidence.mjs'
    shutil.copyfile(root / 'examples/evidence.py', python_example)
    shutil.copyfile(root / 'examples/evidence.mjs', node_example)
    py_example = json.loads(run([str(python), '-I', '-B', str(python_example), '--tokenizer', str(tokenizer),
        '--prefix', str(py_prefix)], work, commands))
    js_example = json.loads(run(['node', str(node_example), '--tokenizer', str(tokenizer),
        '--prefix', str(node_prefix)], node_env, commands))
    require(py_example == js_example and set(py_example) == {'partial', 'strict_budget'}, 'installed_example_parity')
    require(py_example['partial']['status'] == 'partial'
            and py_example['strict_budget']['counting_mode'] == 'strict', 'installed_example_behavior')
    return dict(state='passed', counts=counts, results=py_result, examples=py_example,
                provenance='Installed wheel and npm product modules; copied probes and examples outside checkout; source fixtures use fakes, not a database.')


def native_harness(root: Path, work: Path, python: Path, node_env: Path,
                   postgres_config: Path) -> tuple[list[str], Path, dict[str, str]]:
    """Copy harness code and link data without exposing checkout product modules."""
    harness = work / 'installed-native-harness'
    harness.mkdir()
    shutil.copytree(root / 'tools', harness / 'tools', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('storage', 'evaluation', 'contracts'):
        (harness / name).symlink_to(root / name, target_is_directory=True)
    (harness / 'artifacts').mkdir()
    (harness / 'artifacts/tokenizers').symlink_to(root / 'artifacts/tokenizers', target_is_directory=True)
    ts = harness / 'packages/typescript'
    ts.mkdir(parents=True)
    installed_node = node_env / 'node_modules/cragkit'
    (ts / 'dist').symlink_to(installed_node / 'dist', target_is_directory=True)
    (ts / 'node_modules').symlink_to(node_env / 'node_modules', target_is_directory=True)
    bootstrap = ('import runpy,sys; sys.path.insert(0,sys.argv[1]); '
                 'sys.argv=sys.argv[2:]; runpy.run_path(sys.argv[0],run_name="__main__")')
    command = [str(python), '-I', '-B', '-c', bootstrap, str(harness / 'tools'),
        str(harness / 'tools/check_python_postgres.py'), '--config', str(postgres_config),
        '--allow-test-writes', '--neon', '--hybrid', '--evidence', '--typescript']
    environment = {'CRAGKIT_REQUIRE_INSTALLED_PREFIX': str(python.parent.parent),
                   'CRAGKIT_INSTALLED_NODE_ROOT': str(installed_node)}
    return command, harness, environment


def installed_postgres_examples(root: Path, work: Path, python: Path, node_env: Path,
                                config: Path, commands: list[dict[str, Any]], *, neon: bool = False) -> dict[str, Any]:
    python_example, node_example = work / 'postgres.py', node_env / 'postgres.mjs'
    shutil.copyfile(root / 'examples/postgres.py', python_example)
    shutil.copyfile(root / 'examples/postgres.mjs', node_example)
    command = ['uv', 'run', '--project', str(root / 'packages/python'), '--frozen', '--extra', 'postgres',
        'python', str(root / 'tools/check_python_postgres.py'), '--config', str(config), '--allow-test-writes', '--results']
    if neon:
        command.append('--neon')
    hosted = json.loads(run(command, root, commands, timeout=600, environment={
        'CRAGKIT_INSTALLED_PYTHON': str(python), 'CRAGKIT_INSTALLED_PYTHON_EXAMPLE': str(python_example),
        'CRAGKIT_INSTALLED_NODE_EXAMPLE': str(node_example)}))
    require(hosted.get('state') == 'passed' and hosted.get('cleanup_verified') is True,
            'installed_postgres_examples_failed')
    return hosted


def accept_artifacts(root: Path, output: Path, postgres_config: Path | None = None, *,
                     neon: bool = False, evidence_native: bool = False) -> dict[str, Any]:
    require(type(neon) is bool and type(evidence_native) is bool, 'artifact_options')
    require(not evidence_native or (postgres_config is not None and neon), 'native_evidence_requires_neon_config')
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {'state': 'in_progress', 'commands': [], 'artifacts': {}, 'imports': {},
        'method': 'One fresh child process per installed artifact; filesystem caches are uncontrolled. Duration covers core, contracts, errors and the optional PostgreSQL/embedding entry points together. Peak RSS covers the whole child lifetime, not an import-only increment. macOS Python RSS is bytes; other supported Unix Python and Node RSS are KiB converted to bytes. Samples are separate and never summed.',
        'limitations': ['Local current-platform single fresh-process samples with uncontrolled filesystem caches; no OS-cold-cache, latency-distribution or performance claim.',
                         'Build and clean dependency setup may access registries; guarded imports do not.',
                         'Import guards are focused regression checks, not a network security sandbox.',
                         'Clean installed payload sizes are logical file sizes, not disk allocation or process memory.']}
    commands = report['commands']
    try:
        with tempfile.TemporaryDirectory(prefix='cragkit-artifact-') as temporary:
            work = Path(temporary)
            py_out, npm_out, rebuilt_out = output / 'python', output / 'npm', output / 'rebuilt'
            for path in (py_out, npm_out, rebuilt_out): path.mkdir(exist_ok=True)
            run(['uv', 'build', str(root / 'packages/python'), '--out-dir', str(py_out), '--no-python-downloads'], root, commands)
            wheel = py_out / 'cragkit-0.0.0-py3-none-any.whl'
            sdist = py_out / 'cragkit-0.0.0.tar.gz'
            original_files = inspect_wheel(wheel)
            source_files = archive_files(sdist)
            require(any(name.endswith('/pyproject.toml') for name in source_files)
                    and any(name.endswith('/src/cragkit/py.typed') for name in source_files), 'sdist_missing_source')
            run(['uv', 'build', str(sdist), '--wheel', '--out-dir', str(rebuilt_out), '--no-python-downloads'], work, commands)
            rebuilt = rebuilt_out / wheel.name
            rebuilt_files = inspect_wheel(rebuilt)
            require(original_files == rebuilt_files, 'rebuilt_wheel_content_mismatch')
            report['artifacts']['wheel'] = artifact_record(wheel, original_files)
            report['artifacts']['sdist'] = artifact_record(sdist, source_files)
            report['artifacts']['rebuilt_wheel'] = artifact_record(rebuilt, rebuilt_files)
            report['rebuilt_wheel_files_identical'] = True
            run(['npm', 'run', 'build'], root / 'packages/typescript', commands)
            packed = json.loads(run(['npm', 'pack', '--json', '--ignore-scripts', '--pack-destination', str(npm_out)], root / 'packages/typescript', commands))
            require(len(packed) == 1, 'npm_pack_count')
            npm_path = npm_out / packed[0]['filename']
            require(npm_path.parent == npm_out and npm_path.is_file(), 'npm_pack_path')
            report['artifacts']['npm'] = artifact_record(npm_path, inspect_npm(npm_path))
            constraints = work / 'constraints.txt'
            run(['uv', 'export', '--project', str(root / 'packages/python'), '--frozen', '--all-extras', '--no-dev', '--no-emit-project', '--no-hashes', '--format', 'requirements.txt', '--output-file', str(constraints)], root, commands)
            for name, package in (('wheel', wheel), ('rebuilt_sdist_wheel', rebuilt)):
                environment = work / name
                run(['uv', 'venv', '--python', sys.executable, '--no-python-downloads', str(environment)], work, commands)
                python = environment / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
                run(['uv', 'pip', 'install', '--python', str(python), '--constraints', str(constraints), str(package)], work, commands)
                sample = json.loads(run([str(python), '-I', '-B', '-c', PYTHON_PROBE], work, commands))
                sample['clean_environment_bytes'] = size_tree(environment)
                report['imports'][name] = sample
            node_env = work / 'node'
            node_env.mkdir()
            (node_env / 'package.json').write_text('{"private":true,"type":"module"}', encoding='utf-8')
            run(['npm', 'install', '--ignore-scripts', '--omit=dev', '--no-audit', '--no-fund', str(npm_path)], node_env, commands)
            probe = node_env / 'probe.mjs'
            probe.write_text(NODE_PROBE, encoding='utf-8')
            sample = json.loads(run(['node', str(probe)], node_env, commands))
            sample['installed'] = json.loads(run(['npm', 'ls', '--omit=dev', '--json'], node_env, commands))
            sample['clean_environment_bytes'] = size_tree(node_env / 'node_modules')
            report['imports']['npm'] = sample
            # Optional tokenizer dependencies are added after all three default import guards.
            installed_python = work / 'wheel' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
            run(['uv', 'pip', 'install', '--python', str(installed_python), '--constraints', str(constraints),
                 str(wheel) + '[tokenizers]'], work, commands)
            run(['npm', 'install', '--ignore-scripts', '--no-audit', '--no-fund', 'tiktoken@1.0.22'], node_env, commands)
            report['installed_evidence'] = installed_evidence(root, work, installed_python, node_env, commands)
            if postgres_config is not None:
                # Install optional drivers only after the driver-free import probes.
                installed_python = work / 'wheel' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
                run(['uv', 'pip', 'install', '--python', str(installed_python), '--constraints', str(constraints),
                     str(wheel) + '[postgres,tokenizers]'], work, commands)
                run(['npm', 'install', '--ignore-scripts', '--no-audit', '--no-fund', 'pg@8.23.1'], node_env, commands)
                if evidence_native:
                    command, harness, environment = native_harness(root, work, installed_python, node_env, postgres_config)
                    hosted = json.loads(run(command, harness, commands, timeout=720, environment=environment))
                    require(hosted.get('state') == 'passed' and hosted.get('cleanup_verified') is True,
                            'installed_native_evidence_failed')
                    report['hosted_evidence_native'] = hosted
                else:
                    hosted = installed_postgres_examples(root, work, installed_python, node_env, postgres_config,
                                                         commands, neon=neon)
                    report['hosted_examples'] = hosted
        report['state'] = 'passed'
        report['temporary_environments_cleaned'] = not work.exists()
        return report
    except ArtifactError as error:
        report['failure_code'] = str(error)
        raise
    finally:
        if report['state'] != 'passed':
            report['state'] = 'failed'
            report['temporary_environments_cleaned'] = 'work' not in locals() or not work.exists()
        (output / 'acceptance.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'artifacts/V0')
    parser.add_argument('--postgres-config', type=Path, help='Private hosted test configuration; requires explicit write consent')
    parser.add_argument('--allow-test-writes', action='store_true')
    parser.add_argument('--neon', action='store_true', help='Explicit direct Neon target for optional hosted checks')
    parser.add_argument('--evidence-native', action='store_true', help='Run hosted V3 checks against installed native product modules')
    args = parser.parse_args()
    if args.postgres_config is not None and not args.allow_test_writes:
        parser.error('--postgres-config requires --allow-test-writes')
    if args.neon and args.postgres_config is None:
        parser.error('--neon requires --postgres-config')
    if args.evidence_native and (args.postgres_config is None or not args.neon):
        parser.error('--evidence-native requires --postgres-config, --allow-test-writes and --neon')
    try:
        if args.neon or args.evidence_native:
            report = accept_artifacts(ROOT, args.output_dir.resolve(), args.postgres_config,
                                      neon=args.neon, evidence_native=args.evidence_native)
        else:
            report = accept_artifacts(ROOT, args.output_dir.resolve(), args.postgres_config)
    except (ArtifactError, OSError, ValueError, KeyError, tarfile.TarError, zipfile.BadZipFile):
        print('Artifact acceptance failed; inspect acceptance.json command statuses.')
        return 1
    print(json.dumps({'state': report['state'], 'artifacts': len(report['artifacts']), 'import_samples': len(report['imports'])}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
