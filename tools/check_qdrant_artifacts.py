"""Build MCP archives and verify isolated backend, tokenizer and SDK installations."""
from __future__ import annotations

import argparse
import email.parser
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

from check_artifacts import archive_files, artifact_record, check_artifact_licensing, require, run

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ('core', 'postgres', 'qdrant', 'qdrant-authoritative', 'tokenizers', 'mcp')


def inspect_mcp_wheel(path: Path) -> dict[str, bytes]:
    files = archive_files(path)
    require({'cragkit_mcp/__init__.py', 'cragkit_mcp/py.typed'} <= files.keys(), 'mcp_wheel_exports')
    names = [name for name in files if name.endswith('.dist-info/METADATA')]
    require(len(names) == 1, 'mcp_metadata')
    metadata = email.parser.BytesParser().parsebytes(files[names[0]])
    require(metadata['Name'] == 'cragkit-mcp' and metadata['Version'] == '1.0.0rc1', 'mcp_identity')
    require(sorted(metadata.get_all('Requires-Dist', [])) == ['cragkit==1.0.0rc1', 'mcp==2.3.0'], 'mcp_dependencies')
    check_artifact_licensing(files, kind='wheel', package_name='cragkit-mcp', version='1.0.0rc1')
    return files


def inspect_mcp_npm(path: Path) -> dict[str, bytes]:
    files = archive_files(path)
    package = json.loads(files['package/package.json'])
    require(package['name'] == 'cragkit-mcp' and package['version'] == '1.0.0-rc.1' and package.get('private') is True, 'mcp_npm_identity')
    require(package.get('dependencies') == {'@modelcontextprotocol/server': '2.4.0', 'zod': '4.6.7'}
            and package.get('peerDependencies') == {'cragkit': '1.0.0-rc.1'}, 'mcp_npm_dependencies')
    for kind, extension in (('import', '.js'), ('types', '.d.ts')):
        target = package.get('exports', {}).get('.', {}).get(kind, '')
        require(target.startswith('./dist/') and target.endswith(extension) and 'package/' + target[2:] in files, 'mcp_npm_export')
    check_artifact_licensing(files, kind='npm', package_name='cragkit-mcp', version='1.0.0-rc.1')
    return files


def check_node_lock(installed: dict[str, Any], expected: dict[str, Any]) -> None:
    for name, value in installed.items():
        if not name.startswith('node_modules/') or value.get('link') or name in ('node_modules/cragkit', 'node_modules/cragkit-mcp'):
            continue
        reference = expected.get(name)
        require(reference is not None and value.get('version') == reference.get('version')
                and bool(reference.get('integrity')) and value.get('integrity') == reference['integrity'], 'v5_node_lock_drift')


def accept(root: Path, core: Path, output: Path) -> dict[str, Any]:
    require(not output.exists() or (output.is_dir() and not any(output.iterdir())), 'v5_output_not_empty')
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = dict(state='running', commands=[], artifacts={}, profiles={'python': {}, 'node': {}},
        limitations=['Local current-platform artifacts only; no registry publication or hosted database writes.',
                      'Dependency installation may access registries; import probes deny focused network/process APIs.',
                      'Synthetic installed MCP tests verify transport contracts, not live model quality.'])
    commands = report['commands']
    try:
        with tempfile.TemporaryDirectory(prefix='cragkit-v5-artifacts-') as temporary:
            work = Path(temporary)
            built = output / 'mcp/python'; built.mkdir(parents=True, exist_ok=True)
            run(['uv', 'build', str(root / 'packages/mcp-python'), '--out-dir', str(built), '--no-python-downloads'], root, commands)
            wheel, sdist = built / 'cragkit_mcp-1.0.0rc1-py3-none-any.whl', built / 'cragkit_mcp-1.0.0rc1.tar.gz'
            files = inspect_mcp_wheel(wheel)
            check_artifact_licensing(archive_files(sdist), kind='sdist', package_name='cragkit-mcp', version='1.0.0rc1')
            rebuilt = output / 'mcp/rebuilt'; rebuilt.mkdir(exist_ok=True)
            run(['uv', 'build', str(sdist), '--wheel', '--out-dir', str(rebuilt), '--no-python-downloads'], work, commands)
            require(inspect_mcp_wheel(rebuilt / wheel.name) == files, 'mcp_sdist_rebuild_drift')
            for name, path in (('wheel', wheel), ('sdist', sdist), ('rebuilt_wheel', rebuilt / wheel.name)):
                report['artifacts'][name] = artifact_record(path, archive_files(path))
            npm_out = output / 'mcp/npm'; npm_out.mkdir(exist_ok=True)
            run(['npm', 'run', 'build'], root / 'packages/mcp-typescript', commands)
            packed = json.loads(run(['npm', 'pack', '--json', '--ignore-scripts', '--pack-destination', str(npm_out)], root / 'packages/mcp-typescript', commands))
            require(len(packed) == 1, 'mcp_npm_count')
            npm = npm_out / packed[0]['filename']; require(npm.parent == npm_out, 'mcp_npm_path')
            report['artifacts']['npm'] = artifact_record(npm, inspect_mcp_npm(npm))
            core_wheel, core_npm = core / 'python/cragkit-1.0.0rc1-py3-none-any.whl', core / 'npm/cragkit-1.0.0-rc.1.tgz'
            require('cragkit/qdrant_corrective.py' in archive_files(core_wheel), 'v5_core_wheel_export')
            core_files = archive_files(core_npm)
            require(json.loads(core_files['package/package.json'])['exports']['./qdrant-corrective'] ==
                    {'types': './dist/qdrant-corrective.d.ts', 'import': './dist/qdrant-corrective.js'}
                    and {'package/dist/qdrant-corrective.js', 'package/dist/qdrant-corrective.d.ts'} <= core_files.keys(), 'v5_core_npm_export')
            for profile in PROFILES:
                environment = work / ('python-' + profile)
                run(['uv', 'venv', '--python', sys.executable, '--no-python-downloads', str(environment)], work, commands)
                python = environment / 'bin/python'
                project = root / ('packages/mcp-python' if profile == 'mcp' else 'packages/python')
                requirements = work / (profile + '-requirements.txt')
                export = ['uv', 'export', '--project', str(project), '--frozen', '--no-dev', '--no-emit-project', '--no-emit-package', 'cragkit', '--format', 'requirements.txt', '--output-file', str(requirements)]
                if profile == 'mcp':
                    export.remove('--no-dev')
                    export += ['--group', 'dev']
                if profile in ('postgres', 'qdrant', 'tokenizers'): export += ['--extra', profile]
                if profile == 'qdrant-authoritative': export += ['--extra', 'postgres', '--extra', 'qdrant']
                run(export, root, commands)
                run(['uv', 'pip', 'install', '--python', str(python), '--require-hashes', '-r', str(requirements)], work, commands)
                packages = [str(core_wheel)] + ([str(wheel)] if profile == 'mcp' else [])
                run(['uv', 'pip', 'install', '--python', str(python), '--no-deps', *packages], work, commands)
                probe = work / 'probe_qdrant_installed.py'; shutil.copyfile(root / 'tools/probe_qdrant_installed.py', probe)
                report['profiles']['python'][profile] = json.loads(run([str(python), '-I', '-B', str(probe), '--profile', profile], work, commands))
                if profile == 'mcp':
                    harness = work / 'python-tests/packages/mcp-python/tests'; harness.mkdir(parents=True)
                    tokenizer = work / 'python-tests/artifacts/tokenizers'; tokenizer.mkdir(parents=True)
                    shutil.copyfile(root / 'artifacts/tokenizers/cl100k_base.tiktoken', tokenizer / 'cl100k_base.tiktoken')
                    for name in ('test_host.py', 'test_stdio_process.py'): shutil.copyfile(project / 'tests' / name, harness / name)
                    report.setdefault('installed_mcp_tests', {})['python'] = run([str(python), '-I', '-B', '-m', 'pytest', str(harness), '-q'], work, commands)
            for profile in PROFILES:
                consumer = work / ('node-' + profile); consumer.mkdir()
                base_lock = json.loads((root / 'packages/typescript/package-lock.json').read_text())['packages']
                mcp_lock = json.loads((root / 'packages/mcp-typescript/package-lock.json').read_text())['packages']
                expected = {**base_lock, **mcp_lock} if profile == 'mcp' else base_lock
                dependencies = {'cragkit': 'file:' + str(core_npm)}
                if profile in ('postgres', 'qdrant-authoritative'): dependencies['pg'] = '8.23.1'
                if profile in ('tokenizers', 'mcp'): dependencies['tiktoken'] = '1.0.22'
                if profile == 'mcp': dependencies.update({'cragkit-mcp': 'file:' + str(npm), '@modelcontextprotocol/client': '2.4.0'})
                # Freeze transitive selections to the reviewed project locks and verify integrity after resolution.
                overrides = {name.removeprefix('node_modules/'): item['version'] for name, item in expected.items()
                    if name.startswith('node_modules/') and '/node_modules/' not in name and not item.get('link') and 'version' in item}
                (consumer / 'package.json').write_text(json.dumps(dict(private=True, type='module', dependencies=dependencies, overrides=overrides)))
                run(['npm', 'install', '--ignore-scripts', '--no-audit', '--no-fund'], consumer, commands)
                check_node_lock(json.loads((consumer / 'package-lock.json').read_text())['packages'], expected)
                shutil.copyfile(root / 'tools/probe_qdrant_installed.mjs', consumer / 'probe.mjs')
                report['profiles']['node'][profile] = json.loads(run(['node', 'probe.mjs', profile], consumer, commands))
                if profile == 'mcp':
                    tests = consumer / 'packages/mcp-typescript/tests'; tests.mkdir(parents=True)
                    shutil.copyfile(root / 'packages/mcp-typescript/tests/host.test.mjs', tests / 'host.test.mjs')
                    (tests.parent / 'dist').symlink_to(consumer / 'node_modules/cragkit-mcp/dist', target_is_directory=True)
                    tokenizer = consumer / 'artifacts/tokenizers'; tokenizer.mkdir(parents=True)
                    shutil.copyfile(root / 'artifacts/tokenizers/cl100k_base.tiktoken', tokenizer / 'cl100k_base.tiktoken')
                    report['installed_mcp_tests']['node'] = run(['node', '--test', '--test-concurrency=1', str(tests / 'host.test.mjs')], consumer, commands)
        report['state'] = 'passed'
    except Exception as error:
        report['state'] = 'failed'; report['failure_code'] = str(error) if type(error).__name__ == 'ArtifactError' else type(error).__name__
    finally:
        report['temporary_environments_cleaned'] = 'work' not in locals() or not work.exists()
        (output / 'acceptance.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-artifacts', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'artifacts/V5/V5-08/artifacts')
    args = parser.parse_args()
    report = accept(ROOT, args.core_artifacts.resolve(), args.output_dir.resolve())
    print(json.dumps({'state': report['state'], 'report': str(args.output_dir.resolve() / 'acceptance.json')}))
    return 0 if report['state'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
