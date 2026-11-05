"""Check all public packages serially from a package-only temporary export."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ('python', 'langchain-python', 'mcp-python')
NODE = ('typescript', 'langchain-typescript', 'mcp-typescript')


class CheckFailure(RuntimeError):
    pass


def archive_members(path: Path) -> dict[str, bytes]:
    """Read bounded regular members without extracting untrusted paths."""
    members: dict[str, bytes] = {}
    if path.suffix == '.whl':
        with zipfile.ZipFile(path) as archive:
            entries = [(item.filename, item.file_size, item.is_dir(),
                        (item.external_attr >> 16) & 0o170000 == 0o120000,
                        lambda item=item: archive.read(item)) for item in archive.infolist()]
            read_members(entries, members)
    else:
        with tarfile.open(path) as archive:
            entries = [(item.name, item.size, item.isdir(),
                        not (item.isfile() or item.isdir()),
                        lambda item=item: read_tar_member(archive, item)) for item in archive]
            read_members(entries, members)
    return members


def read_tar_member(archive: tarfile.TarFile, item: tarfile.TarInfo) -> bytes:
    stream = archive.extractfile(item)
    if stream is None:
        raise CheckFailure('archive unreadable member')
    return stream.read()


def read_members(entries: list, result: dict[str, bytes]) -> None:
    total = 0
    forbidden = {'tests', 'evaluation', 'examples', 'tasks', 'node_modules', '.venv', '.git'}
    for name, size, directory, special, reader in entries:
        parts = PurePosixPath(name).parts
        if (special or not parts or name.startswith('/') or '\\' in name
                or '..' in parts or any(part in forbidden or part.startswith('.env') for part in parts)):
            raise CheckFailure('unexpected archive member')
        if directory:
            continue
        total += size
        if name in result or total > 32 * 1024 * 1024 or len(result) >= 2048:
            raise CheckFailure('archive limits exceeded')
        result[name] = reader()


class Checker:
    def __init__(self, output: Path, downloads: bool) -> None:
        self.output = output
        self.report: dict = {'state': 'running', 'profile': 'public-package-build-and-import',
                            'private_inputs': False, 'dependency_downloads_allowed': downloads,
                            'steps': [], 'artifacts': [], 'source_digests': {}}
        # Do not pass caller credentials, provider configuration or import overrides to children.
        allowed = ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'SYSTEMROOT', 'UV_CACHE_DIR', 'NPM_CONFIG_CACHE')
        self.env = {key: os.environ[key] for key in allowed if key in os.environ}
        npm_user_config = output / 'npm-user-config'
        npm_global_config = output / 'npm-global-config'
        for config in (npm_user_config, npm_global_config):
            config.write_text('')
            config.chmod(0o600)
        self.env.update({'UV_PYTHON_DOWNLOADS': 'never', 'UV_NO_PROGRESS': '1',
                         'UV_NO_CONFIG': '1', 'UV_KEYRING_PROVIDER': 'disabled',
                         'NPM_CONFIG_USERCONFIG': str(npm_user_config),
                         'NPM_CONFIG_GLOBALCONFIG': str(npm_global_config),
                         'npm_config_ignore_scripts': 'true', 'npm_config_audit': 'false',
                         'npm_config_fund': 'false', 'npm_config_update_notifier': 'false',
                         'PYTHONDONTWRITEBYTECODE': '1'})
        if not downloads:
            self.env.update({'UV_OFFLINE': '1', 'npm_config_offline': 'true'})

    def run(self, name: str, command: list[str], cwd: Path, timeout: int = 300) -> str:
        record = {'name': name, 'argv': command, 'returncode': None}
        self.report['steps'].append(record)
        print(f'[{len(self.report["steps"])}] {name}', flush=True)
        log = self.output / f'{len(self.report["steps"]):02d}-{name}.log'
        try:
            result = subprocess.run(command, cwd=cwd, env=self.env, capture_output=True,
                                    text=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            record['error'] = type(error).__name__
            raise CheckFailure(name) from None
        log.write_text(result.stdout + result.stderr)
        log.chmod(0o600)
        record['returncode'] = result.returncode
        if result.returncode:
            raise CheckFailure(name)
        return result.stdout

    def record(self, path: Path) -> dict[str, bytes]:
        members = archive_members(path)
        if not any(name.endswith('/LICENSE') or name.endswith('/licenses/LICENSE') for name in members):
            raise CheckFailure('archive license missing')
        if not any(name.endswith('/NOTICE') or name.endswith('/licenses/NOTICE') for name in members):
            raise CheckFailure('archive notice missing')
        self.report['artifacts'].append({'path': str(path.relative_to(self.output)),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'members': len(members)})
        return members

    def check(self, work: Path) -> None:
        source = work / 'source'
        for package in PYTHON + NODE:
            original, target = ROOT / 'packages' / package, source / 'packages' / package
            target.mkdir(parents=True)
            # This allowlist makes private directories unnecessary and unavailable to builds.
            for name in ('src', 'pyproject.toml', 'uv.lock', 'package.json', 'package-lock.json',
                         'tsconfig.json', 'LICENSE', 'NOTICE'):
                item = original / name
                if item.is_dir():
                    shutil.copytree(item, target / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
                elif item.is_file():
                    shutil.copyfile(item, target / name)
        for package in PYTHON + NODE:
            digest = hashlib.sha256()
            native = source / 'packages' / package / 'src'
            for item in sorted(native.rglob('*')):
                if item.is_file():
                    digest.update(item.relative_to(native).as_posix().encode())
                    digest.update(b'\0')
                    digest.update(item.read_bytes())
            self.report['source_digests'][package] = digest.hexdigest()
        wheels: list[Path] = []
        tarballs: list[Path] = []
        for package in PYTHON:
            project = source / 'packages' / package
            self.run(f'{package}-frozen-install', ['uv', 'sync', '--project', str(project), '--frozen'], source)
            self.run(f'{package}-strict-types', ['uv', 'run', '--project', str(project), '--frozen',
                     '--no-sync', 'mypy', '--config-file', str(project / 'pyproject.toml'), str(project / 'src')], source)
            built = self.output / package
            built.mkdir()
            self.run(f'{package}-archives', ['uv', 'build', str(project), '--out-dir', str(built)], source)
            wheel, = built.glob('*.whl')
            sdist, = built.glob('*.tar.gz')
            expected = self.record(wheel)
            self.record(sdist)
            rebuilt = work / 'rebuilt' / package
            self.run(f'{package}-sdist-wheel', ['uv', 'build', str(sdist), '--wheel', '--out-dir', str(rebuilt)], work)
            rebuilt_wheel, = rebuilt.glob('*.whl')
            if archive_members(rebuilt_wheel) != expected:
                raise CheckFailure(f'{package}-sdist-content')
            wheels.append(wheel)
        for package in NODE:
            project = source / 'packages' / package
            self.run(f'{package}-frozen-install', ['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], project)
            self.run(f'{package}-strict-types', ['npm', 'run', 'typecheck'], project)
            self.run(f'{package}-build', ['npm', 'run', 'build'], project)
            built = self.output / package
            built.mkdir()
            self.run(f'{package}-archive', ['npm', 'pack', '--ignore-scripts', '--json', '--pack-destination', str(built)], project)
            tarball, = built.glob('*.tgz')
            self.record(tarball)
            tarballs.append(tarball)
        consumer = work / 'consumer'
        consumer.mkdir()
        env = consumer / 'python'
        self.run('python-consumer-create', ['uv', 'venv', '--python', str(source / 'packages/python/.venv/bin/python'), str(env)], consumer)
        requirements = consumer / 'requirements.txt'
        exports: list[str] = []
        for package in PYTHON:
            export = self.run(f'{package}-locked-runtime', ['uv', 'export', '--project', str(source / 'packages' / package),
                '--frozen', '--no-dev', '--no-emit-project', '--no-emit-package', 'cragkit', '--no-header', '--no-annotate'], source)
            exports.append(export)
        requirements.write_text('\n'.join(exports))
        python = str(env / 'bin/python')
        self.run('python-consumer-dependencies', ['uv', 'pip', 'install', '--python', python, '--require-hashes', '-r', str(requirements)], consumer)
        self.run('python-consumer-wheels', ['uv', 'pip', 'install', '--python', python, '--no-deps', *map(str, wheels)], consumer)
        probe = """import importlib,pathlib,sys
root=pathlib.Path(sys.prefix).resolve()
def audit(event,args):
    if event.startswith(('socket.','subprocess.')) or event in ('os.system','os.posix_spawn'):
        raise RuntimeError('import attempted external I/O')
sys.addaudithook(audit)
for name in ('cragkit','cragkit.contracts','cragkit.postgres','cragkit.qdrant','cragkit_langchain','cragkit_mcp'):
    module=importlib.import_module(name)
    assert pathlib.Path(module.__file__).resolve().is_relative_to(root),name
print('all installed Python package imports passed')
"""
        self.run('python-installed-imports', [python, '-I', '-B', '-c', probe], consumer)
        node = consumer / 'node'
        node.mkdir()
        dependencies = {json.loads((source / 'packages' / package / 'package.json').read_text())['name']:
                        'file:' + str(tarball) for package, tarball in zip(NODE, tarballs, strict=True)}
        overrides: dict[str, str] = {}
        runtime_integrities: dict[str, str | None] = {}
        for package in NODE:
            locked = json.loads((source / 'packages' / package / 'package-lock.json').read_text())['packages']
            for name, item in locked.items():
                if name.startswith('node_modules/') and not item.get('dev') and not item.get('link'):
                    short = name.removeprefix('node_modules/')
                    if '/node_modules/' in short or (short in overrides and overrides[short] != item['version']):
                        raise CheckFailure('runtime lock requires nested override review')
                    if short in runtime_integrities and runtime_integrities[short] != item.get('integrity'):
                        raise CheckFailure('runtime integrity differs across locks')
                    overrides[short] = item['version']
                    runtime_integrities[short] = item.get('integrity')
        (node / 'package.json').write_text(json.dumps({'private': True, 'type': 'module',
            'dependencies': dependencies, 'overrides': overrides}))
        self.run('node-consumer-install', ['npm', 'install', '--ignore-scripts', '--no-audit', '--no-fund'], node)
        installed = json.loads((node / 'package-lock.json').read_text())['packages']
        for name, version in overrides.items():
            actual = installed.get('node_modules/' + name, {})
            if actual.get('version') != version or actual.get('integrity') != runtime_integrities[name]:
                raise CheckFailure('installed runtime lock integrity drift')
        node_probe = node / 'probe.mjs'
        node_probe.write_text("""import assert from 'node:assert/strict';
import {realpathSync} from 'node:fs';
import net from 'node:net';import tls from 'node:tls';import http from 'node:http';import https from 'node:https';
const blocked=()=>{throw new Error('import attempted network I/O')};
net.connect=net.createConnection=tls.connect=http.request=http.get=https.request=https.get=globalThis.fetch=blocked;
for (const name of ['cragkit','cragkit/contracts','cragkit/postgres','cragkit/qdrant','cragkit-langchain','cragkit-mcp']) {
 assert.ok(realpathSync(new URL(import.meta.resolve(name))).startsWith(process.cwd()+'/node_modules/'));
 await import(name);
}
console.log('all installed Node package imports passed');
""")
        self.run('node-installed-imports', ['node', str(node_probe)], node)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'artifacts/public-check')
    parser.add_argument('--allow-downloads', action='store_true', help='Allow dependency downloads; no provider calls or uploads.')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if not output.is_relative_to(ROOT / 'artifacts') or output == ROOT / 'artifacts' or output.exists():
        parser.error('output must be a fresh directory below artifacts/')
    os.umask(0o077)
    output.mkdir(parents=True, mode=0o700)
    checker = Checker(output, args.allow_downloads)
    try:
        with tempfile.TemporaryDirectory(prefix='cragkit-public-') as temporary:
            checker.check(Path(temporary))
        checker.report['state'] = 'passed'
    except Exception as error:
        checker.report['state'] = 'failed'
        checker.report['failure'] = str(error) if isinstance(error, CheckFailure) else type(error).__name__
    (output / 'report.json').write_text(json.dumps(checker.report, indent=2) + '\n')
    print(json.dumps({'state': checker.report['state'], 'report': str(output / 'report.json')}))
    return 0 if checker.report['state'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
