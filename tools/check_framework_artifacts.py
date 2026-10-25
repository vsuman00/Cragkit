"""Build optional SDK archives and validate isolated installations; never publish."""
from __future__ import annotations

import argparse
import email.parser
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

from check_artifacts import archive_files, artifact_record, require, run, size_tree

ROOT = Path(__file__).resolve().parents[1]


def python_adapter(root: Path, output: Path, core: Path, work: Path,
                   commands: list[dict[str, Any]]) -> dict[str, Any]:
    project = root / 'packages/langchain-python'
    built = output / 'python'
    built.mkdir(parents=True, exist_ok=True)
    run(['uv', 'build', str(project), '--out-dir', str(built), '--no-python-downloads'], root, commands)
    wheel = built / 'cragkit_langchain-0.0.0-py3-none-any.whl'
    sdist = built / 'cragkit_langchain-0.0.0.tar.gz'
    files = archive_files(wheel)
    require('cragkit_langchain/__init__.py' in files and 'cragkit_langchain/py.typed' in files, 'adapter_wheel_missing')
    metadata_files = [name for name in files if name.endswith('.dist-info/METADATA')]
    require(len(metadata_files) == 1, 'adapter_metadata')
    metadata = email.parser.BytesParser().parsebytes(files[metadata_files[0]])
    require(metadata['Name'] == 'cragkit-langchain' and sorted(metadata.get_all('Requires-Dist', [])) == ['cragkit==0.0.0', 'langchain-core==1.7.0'], 'adapter_dependencies')
    rebuilt = output / 'rebuilt'
    rebuilt.mkdir(exist_ok=True)
    run(['uv', 'build', str(sdist), '--wheel', '--out-dir', str(rebuilt), '--no-python-downloads'], work, commands)
    require(archive_files(rebuilt / wheel.name) == files, 'adapter_rebuilt_content')
    requirements = work / 'sdk-requirements.txt'
    run(['uv', 'export', '--project', str(project), '--frozen', '--no-dev', '--no-emit-project',
         '--no-emit-package', 'cragkit', '--format', 'requirements.txt', '--output-file', str(requirements)], root, commands)
    environment = work / 'python'
    run(['uv', 'venv', '--python', sys.executable, '--no-python-downloads', str(environment)], work, commands)
    python = environment / 'bin/python'
    run(['uv', 'pip', 'install', '--python', str(python), '--require-hashes', '-r', str(requirements)], work, commands)
    run(['uv', 'pip', 'install', '--python', str(python), str(core), str(wheel), 'pytest==9.1.1', 'tiktoken==0.14.0'], work, commands)
    tests = work / 'test_adapter.py'
    shutil.copyfile(project / 'tests/test_adapter.py', tests)
    variables = {'CRAGKIT_FIXTURES': str(root / 'contracts/fixtures'),
                 'CRAGKIT_TOKENIZER': str(root / 'artifacts/tokenizers/cl100k_base.tiktoken'),
                 'PYTHONPATH': ''}
    result = run([str(python), '-I', '-B', '-m', 'pytest', str(tests), '-q'], work, commands, environment=variables)
    require('passed' in result, 'installed_adapter_tests_missing')
    probe = "import cragkit_langchain,cragkit,pathlib,sys; assert all(pathlib.Path(m.__file__).resolve().is_relative_to(pathlib.Path(sys.prefix)) for m in (cragkit_langchain,cragkit)); print('installed')"
    run([str(python), '-I', '-B', '-c', probe], work, commands)
    return dict(state='passed', wheel=artifact_record(wheel, files),
                sdist=artifact_record(sdist, archive_files(sdist)), rebuilt_wheel=artifact_record(rebuilt / wheel.name, files), installed_tests=result.strip(),
                clean_environment_bytes=size_tree(environment))



def node_adapter(root: Path, output: Path, core: Path, work: Path,
                 commands: list[dict[str, Any]]) -> dict[str, Any]:
    project = root / 'packages/langchain-typescript'
    run(['npm', 'run', 'build'], project, commands)
    built = output / 'npm'
    built.mkdir(parents=True, exist_ok=True)
    packed = json.loads(run(['npm', 'pack', '--json', '--ignore-scripts', '--pack-destination', str(built)], project, commands))
    require(len(packed) == 1, 'adapter_npm_count')
    archive = built / packed[0]['filename']
    require(archive.parent == built, 'adapter_npm_path')
    files = archive_files(archive)
    metadata = json.loads(files['package/package.json'])
    require(metadata['name'] == 'cragkit-langchain' and metadata['version'] == '0.0.0'
        and metadata.get('private') is True, 'adapter_npm_identity')
    require(metadata.get('dependencies') == {'@langchain/core': '1.3.0', 'langsmith': '0.11.1', 'zod': '4.6.7'}
        and metadata.get('peerDependencies') == {'cragkit': '0.0.0'}, 'adapter_npm_dependencies')
    require({'package/dist/index.js', 'package/dist/index.d.ts'} <= files.keys(), 'adapter_npm_exports')
    locked = json.loads((project / 'package-lock.json').read_text())['packages']
    dependencies = {name.removeprefix('node_modules/'): item for name,item in locked.items()
        if name.startswith('node_modules/') and not item.get('dev') and not item.get('link')}
    require(all('/node_modules/' not in name for name in dependencies), 'adapter_nested_lock_review_required')
    consumer = work / 'node'
    consumer.mkdir()
    package = {'private': True, 'type': 'module', 'dependencies': {
        'cragkit': 'file:' + str(core), 'cragkit-langchain': 'file:' + str(archive), 'tiktoken': '1.0.22'},
        'overrides': {name: item['version'] for name,item in dependencies.items()}}
    (consumer / 'package.json').write_text(json.dumps(package))
    run(['npm', 'install', '--ignore-scripts', '--no-audit', '--no-fund'], consumer, commands)
    installed = json.loads((consumer / 'package-lock.json').read_text())['packages']
    for name,item in dependencies.items():
        actual = installed.get('node_modules/' + name, {})
        require(actual.get('version') == item['version'] and actual.get('integrity') == item.get('integrity'), 'adapter_sdk_lock_drift')
    (consumer / 'tests').mkdir()
    shutil.copyfile(project / 'tests/adapter.test.mjs', consumer / 'tests/adapter.test.mjs')
    (consumer / 'dist').symlink_to(consumer / 'node_modules/cragkit-langchain/dist', target_is_directory=True)
    variables = {'CRAGKIT_FIXTURES': str(root / 'contracts/fixtures'),
        'CRAGKIT_TOKENIZER': str(root / 'artifacts/tokenizers/cl100k_base.tiktoken')}
    result = run(['node', '--test', '--test-concurrency=1', 'tests/adapter.test.mjs'], consumer, commands, environment=variables)
    probe = consumer / 'probe.mjs'
    probe.write_text("import assert from 'node:assert/strict';import {realpathSync} from 'node:fs';for(const n of ['cragkit','cragkit-langchain'])assert.ok(realpathSync(new URL(import.meta.resolve(n))).startsWith(process.cwd()+'/node_modules/'));console.log('installed');")
    run(['node', str(probe)], consumer, commands)
    return dict(state='passed', npm=artifact_record(archive, files), installed_tests=result.strip(),
        clean_environment_bytes=size_tree(consumer / 'node_modules'), locked_sdk_packages=len(dependencies))

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-artifacts', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'artifacts/V4/frameworks')
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {'state': 'running', 'commands': [], 'provenance': 'Isolated installed product imports outside checkout; explicit fixture/tokenizer inputs; original checkout remains present.'}
    try:
        with tempfile.TemporaryDirectory(prefix='cragkit-framework-') as temporary:
            report['python'] = python_adapter(ROOT, output, args.core_artifacts.resolve() / 'python/cragkit-0.0.0-py3-none-any.whl', Path(temporary), report['commands'])
            report['node'] = node_adapter(ROOT, output, args.core_artifacts.resolve() / 'npm/cragkit-0.0.0.tgz', Path(temporary), report['commands'])
        report['state'] = 'passed'
    except Exception as error:
        # Commands capture output privately; never copy provider/environment payloads to reports.
        report['state'] = 'failed'
        report['error'] = type(error).__name__
    (output / 'acceptance.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'state': report['state'], 'report': str(output / 'acceptance.json')}))
    return 0 if report['state'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
