"""Bounded execution identity for a clean candidate; no installation or provider I/O."""
from __future__ import annotations

from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import selectors
import signal
import shutil
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time
import tomllib

import evaluation_packet

ROOT = Path(__file__).resolve().parents[1]
MAX_FILES = 20000
MAX_ENTRIES = 40000
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_RECEIPT_BYTES = 8 * 1024 * 1024
TOKENIZER_SHA256 = '223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7'
CATEGORIES = frozenset({'node_dist', 'node_dependencies', 'python_dependencies', 'python_stdlib',
    'checkout_bytecode', 'toolchain', 'npm_toolchain'})
FIELDS = frozenset({'revision', 'source_commit', 'package_tree', 'configuration_sha256',
    'runtime_versions', 'tokenizer_sha256', 'files', 'identity_sha256'})
VERSION_FIELDS = frozenset({'python', 'node', 'npm', 'typescript', 'python_bytecode_writes'})


class EvaluationRuntimeError(ValueError):
    """Fixed content-free diagnostic, with no retained subprocess or parser context."""


def _fail():
    raise EvaluationRuntimeError('evaluation_runtime_invalid')


def _require(condition):
    if not condition:
        _fail()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')


def _regular_bytes(path, limit):
    """No-follow bounded regular-file read; reject replacement or growth while reading."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode) and before.st_size <= limit)
        chunks = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(65536, limit + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            _require(size <= limit)
            chunks.append(chunk)
        after = os.fstat(descriptor)
        _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns))
        return b''.join(chunks)
    finally:
        os.close(descriptor)


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result)
            result[key] = value
        return result
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
        parse_constant=lambda _: _fail())


def _command(arguments, *, timeout=10, capture=True, cwd=None):
    """Finite local process group with bounded output and unconditional child cleanup."""
    # Do not inspect or forward provider credentials or ambient runtime injection.
    environment = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR', 'TZ')
        if key in os.environ}
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    process = subprocess.Popen(arguments, cwd=cwd, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=environment, start_new_session=True)
    deadline = time.monotonic() + timeout
    captured = bytearray()
    try:
        if capture:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    _require(remaining > 0)
                    for key, _ in selector.select(min(remaining, 0.1)):
                        chunk = os.read(key.fileobj.fileno(), 4096)
                        if not chunk:
                            selector.unregister(key.fileobj)
                        else:
                            captured.extend(chunk)
                            _require(len(captured) <= 4096)
        _require(process.wait(timeout=max(0.001, deadline - time.monotonic())) == 0)
        return captured.decode('utf-8').strip() if capture else ''
    finally:
        # A launcher may exit while a child still holds stdout; close the whole group.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()


def _candidate(root):
    _require(root == ROOT and sys.dont_write_bytecode)
    raw = evaluation_packet._read(root, 'evaluation/release/V6-candidate.json', 131072)
    configuration = evaluation_packet._json(raw)
    evaluation_packet.check_settings(configuration)
    commit = evaluation_packet.verify_candidate_source(root, configuration)
    _release_versions(root, configuration)
    return configuration, dict(source_commit=commit, package_tree=configuration['package_tree'],
        configuration_sha256=sha256(raw).hexdigest())


def _release_versions(root, configuration):
    """Check declared RC metadata before fingerprinting an execution candidate."""
    from cragkit import __version__, _ENGINE_VERSION

    expected = configuration.get('candidate_versions')
    _require(type(expected) is dict and expected == {'python':'1.0.0rc1', 'npm':'1.0.0-rc.1'})
    _require(__version__ == expected['python'] and _ENGINE_VERSION == expected['npm'])
    for component, distribution in (('python', 'cragkit'),
            ('langchain-python', 'cragkit-langchain'), ('mcp-python', 'cragkit-mcp')):
        project = tomllib.loads(_regular_bytes(root/'packages'/component/'pyproject.toml', 131072).decode())['project']
        _require(project['name'] == distribution and project['version'] == expected['python'])
        if component != 'python':
            _require('cragkit=='+expected['python'] in project['dependencies'])
    for component, distribution in (('typescript', 'cragkit'),
            ('langchain-typescript', 'cragkit-langchain'), ('mcp-typescript', 'cragkit-mcp')):
        project = _json(_regular_bytes(root/'packages'/component/'package.json', 131072))
        _require(project['name'] == distribution and project['version'] == expected['npm'])
        if component != 'typescript':
            _require(project['peerDependencies']['cragkit'] == expected['npm'])


def _metadata(root):
    _require(not any(os.environ.get(name) for name in ('NODE_OPTIONS', 'NODE_PATH', 'PYTHONPATH', 'PYTHONHOME')))
    python_lock = tomllib.loads(_regular_bytes(root/'packages/python/uv.lock', 4 * 1024 * 1024).decode())
    expected_python = {re.sub('[-_.]+', '-', row['name']).lower(): row['version']
        for row in python_lock['package']}
    site = root/'packages/python/.venv/lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'
    _require(Path(sys.prefix).resolve() == (root/'packages/python/.venv').resolve())
    actual_python = {}
    for distribution in importlib.metadata.distributions(path=[str(site)]):
        name = re.sub('[-_.]+', '-', distribution.metadata['Name']).lower()
        _require(expected_python.get(name) == distribution.version and name not in actual_python)
        actual_python[name] = distribution.version
    from packaging.markers import Marker
    required_python = {'cragkit'}
    for package in python_lock['package']:
        groups = [package.get('dependencies', [])]
        groups.extend(package.get('optional-dependencies', {}).values())
        groups.extend(package.get('dev-dependencies', {}).values())
        for dependencies in groups:
            for dependency in dependencies:
                if 'marker' not in dependency or Marker(dependency['marker']).evaluate():
                    required_python.add(re.sub('[-_.]+', '-', dependency['name']).lower())
    _require(required_python <= actual_python.keys())
    owned_import_roots = (site.resolve(), Path(sysconfig.get_path('stdlib')).resolve(), root/'tools',
        root/'packages/python/src', root/'evaluation/runners')
    for module in tuple(sys.modules.values()):
        origin = getattr(module, '__file__', None)
        if origin and not str(origin).startswith('<'):
            path = Path(origin).resolve()
            _require(any(path.is_relative_to(owned) for owned in owned_import_roots))
    project = _json(_regular_bytes(root/'packages/typescript/package-lock.json', 4 * 1024 * 1024))
    installed = _json(_regular_bytes(root/'packages/typescript/node_modules/.package-lock.json', 4 * 1024 * 1024))
    _require(type(installed.get('packages')) is dict and len(installed['packages']) <= 512)
    _require(all(path in installed['packages'] for path, metadata in project['packages'].items()
        if path and not metadata.get('optional')))
    for path, metadata in installed['packages'].items():
        _require(path.startswith('node_modules/') and path in project['packages'])
        _require(metadata == project['packages'][path])
        package_path = root/'packages/typescript'/path/'package.json'
        _require(package_path.resolve().is_relative_to((root/'packages/typescript/node_modules').resolve()))
        package = _json(_regular_bytes(package_path, 1048576))
        _require(package.get('version') == metadata.get('version'))
    return site


def _versions(root, configuration):
    _require(sys.dont_write_bytecode)
    node = shutil.which('node')
    npm = shutil.which('npm')
    _require(node is not None and npm is not None)
    node_path, npm_path = Path(node).resolve(), Path(npm).resolve()
    compiler = root/'packages/typescript/node_modules/typescript/bin/tsc'
    manifest = _json(_regular_bytes(root/'packages/typescript/package.json', 1048576))
    versions = dict(python=platform.python_version(), node=_command([str(node_path), '--version']).removeprefix('v'),
        npm=_command([str(node_path), str(npm_path), '--userconfig=/dev/null', '--globalconfig=/dev/null', '--version']),
        typescript=_command([str(node_path), str(compiler), '--version']).removeprefix('Version '),
        python_bytecode_writes=False)
    matrix = configuration['supported_matrix']
    _require(matrix.get('platform') == sys.platform+'-'+platform.machine().lower())
    for key in ('python', 'node', 'npm'):
        _require(versions[key] == matrix[key])
    _require(versions['typescript'] == manifest['devDependencies']['typescript'])
    return versions


def _node_export(emitted, configuration):
    """Execute only freshly compiled source after complete emitted-set equality."""
    node_path = Path(shutil.which('node')).resolve()
    entry = (emitted/'index.js').as_uri()
    expression = 'import {version} from '+json.dumps(entry)+';process.stdout.write(version);'
    _require(_command([str(node_path), '--input-type=module', '-e', expression])
        == configuration['candidate_versions']['npm'])


def _layout(root):
    site = _metadata(root)
    node_path = Path(shutil.which('node')).resolve()
    npm_path = Path(shutil.which('npm')).resolve()
    stdlib = Path(sysconfig.get_path('stdlib')).resolve()
    python_path = Path(sys.executable).resolve()
    directories = {
        'node_dist': (root/'packages/typescript/dist', frozenset()),
        'node_dependencies': (root/'packages/typescript/node_modules', frozenset()),
        'python_dependencies': (site, frozenset()),
        'python_stdlib': (stdlib, frozenset({'site-packages'})),
        'npm_toolchain': (npm_path.parent.parent, frozenset()),
    }
    singles = {'toolchain/node': node_path, 'toolchain/python': python_path}
    # Homebrew's small Node executable delegates to libnode in its own installation.
    node_libraries = node_path.parent.parent/'lib'
    if node_libraries.is_dir():
        directories['toolchain/node_libraries'] = (node_libraries, frozenset({'node_modules'}))
    framework = Path(sys.base_prefix)/'Python'
    if framework.is_file() and framework.resolve() != python_path:
        singles['toolchain/python_framework'] = framework.resolve()
    # -B prevents writes but still reads existing source caches. Refuse all checkout
    # bytecode rather than claiming that its digest proves correspondence to Git source.
    for area in ('tools', 'evaluation/runners'):
        directories['checkout_bytecode/'+area] = (root/area, frozenset())
    with os.scandir(root/'packages') as stream:
        packages = []
        for entry in stream:
            _require(len(packages) < 128)
            packages.append(entry)
    for package in packages:
        source = Path(package.path)/'src'
        if source.is_dir():
            _require(not package.is_symlink())
            directories['checkout_bytecode/packages/'+package.name+'/src'] = (source, frozenset())
    return directories, singles


class _Inventory:
    def __init__(self, allowed_files=()):
        self.allowed_files = frozenset(Path(path).resolve() for path in allowed_files)
        self.files = {}
        self.bytes = 0
        self.entries = 0

    def file(self, key, path):
        _require(len(self.files) < MAX_FILES and len(key.encode('utf-8')) <= 2048)
        size = path.stat().st_size
        _require(size <= MAX_FILE_BYTES and self.bytes + size <= MAX_TOTAL_BYTES)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(descriptor)
            _require(stat.S_ISREG(before.st_mode) and before.st_size == size)
            digest = sha256()
            consumed = 0
            while True:
                chunk = os.read(descriptor, 65536)
                if not chunk:
                    break
                consumed += len(chunk)
                _require(consumed <= MAX_FILE_BYTES and self.bytes + consumed <= MAX_TOTAL_BYTES)
                digest.update(chunk)
            after = os.fstat(descriptor)
            _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns))
            self.bytes += consumed
            _require(key not in self.files)
            self.files[key] = digest.hexdigest()
        finally:
            os.close(descriptor)

    def tree(self, category, path, excluded=frozenset(), *, reject_bytecode=False):
        _require(path.is_dir() and not path.is_symlink())
        owned = path.resolve()
        visited = set()

        def walk(directory, relative, depth=0):
            _require(depth <= 64)
            info = directory.stat()
            identity = (info.st_dev, info.st_ino)
            _require(identity not in visited)
            visited.add(identity)
            try:
                entries = []
                with os.scandir(directory) as stream:
                    for entry in stream:
                        self.entries += 1
                        _require(self.entries <= MAX_ENTRIES)
                        entries.append(entry)
                entries.sort(key=lambda entry: os.fsencode(entry.name))
                for entry in entries:
                    name = relative/entry.name
                    if not relative.parts and entry.name in excluded:
                        continue
                    candidate = Path(entry.path)
                    resolved = candidate.resolve(strict=True)
                    _require(resolved.is_relative_to(owned) or resolved in self.allowed_files)
                    mode = resolved.stat().st_mode
                    if stat.S_ISDIR(mode):
                        walk(resolved, name, depth + 1)
                    elif stat.S_ISREG(mode):
                        if reject_bytecode:
                            _require(name.suffix != '.pyc')
                        else:
                            self.file(category+'/'+name.as_posix(), resolved)
                    else:
                        _fail()
            finally:
                visited.remove(identity)
        walk(owned, PurePosixPath())


def _inventory(root):
    directories, singles = _layout(root)
    inventory = _Inventory(allowed_files=singles.values())
    for category, (directory, excluded) in sorted(directories.items()):
        inventory.tree(category, directory, excluded, reject_bytecode=category.split('/')[0] == 'checkout_bytecode')
    for key, path in sorted(singles.items()):
        inventory.file(key, path)
    return inventory.files


def _build(root, destination):
    node = str(Path(shutil.which('node')).resolve())
    compiler = str(root/'packages/typescript/node_modules/typescript/bin/tsc')
    _command([node, compiler, '--project', str(root/'packages/typescript/tsconfig.json'),
        '--outDir', str(destination), '--incremental', 'false'], timeout=120, capture=False, cwd=root)


def _snapshot(root):
    configuration, candidate = _candidate(root)
    versions = _versions(root, configuration)
    before = _inventory(root)
    with tempfile.TemporaryDirectory(prefix='cragkit-runtime-build-') as temporary:
        emitted = Path(temporary)/'dist'
        _build(root, emitted)
        built = _Inventory()
        built.tree('node_dist', emitted)
        current = {key: digest for key, digest in before.items() if key.startswith('node_dist/')}
        _require(current == built.files and bool(current))
        _node_export(emitted, configuration)
    after = _inventory(root)
    _require(before == after)
    configuration_after, candidate_after = _candidate(root)
    _require(candidate == candidate_after and configuration == configuration_after)
    _require(versions == _versions(root, configuration_after))
    tokenizer = _regular_bytes(root/'artifacts/tokenizers/cl100k_base.tiktoken', 2000000)
    tokenizer_digest = sha256(tokenizer).hexdigest()
    _require(tokenizer_digest == TOKENIZER_SHA256)
    record = dict(revision='ECR-r1', **candidate, runtime_versions=versions,
        tokenizer_sha256=tokenizer_digest, files=before)
    record['identity_sha256'] = sha256(_canonical(record)).hexdigest()
    return record


def _validate_receipt(record):
    _require(type(record) is dict and set(record) == FIELDS and record['revision'] == 'ECR-r1')
    for key in ('source_commit', 'package_tree'):
        _require(type(record[key]) is str and re.fullmatch('[a-f0-9]{40}', record[key]) is not None)
    for key in ('configuration_sha256', 'tokenizer_sha256', 'identity_sha256'):
        _require(type(record[key]) is str and re.fullmatch('[a-f0-9]{64}', record[key]) is not None)
    versions = record['runtime_versions']
    _require(type(versions) is dict and set(versions) == VERSION_FIELDS
        and versions['python_bytecode_writes'] is False)
    _require(all(type(versions[key]) is str and len(versions[key]) <= 32 and re.fullmatch(r'[0-9]+(?:\.[0-9]+){2}', versions[key])
        for key in ('python', 'node', 'npm', 'typescript')))
    files = record['files']
    _require(type(files) is dict and 0 < len(files) <= MAX_FILES)
    estimated_bytes = 0
    for key, digest in files.items():
        _require(type(key) is str and len(key.encode('utf-8')) <= 2048
            and key.split('/')[0] in CATEGORIES and not PurePosixPath(key).is_absolute()
            and all(part not in ('', '.', '..') for part in key.split('/')))
        _require(type(digest) is str and re.fullmatch('[a-f0-9]{64}', digest) is not None)
        estimated_bytes += len(key.encode('utf-8')) + len(digest) + 8
        _require(estimated_bytes <= MAX_RECEIPT_BYTES)
    identity = {key: value for key, value in record.items() if key != 'identity_sha256'}
    _require(sha256(_canonical(identity)).hexdigest() == record['identity_sha256'])
    _require(len(_canonical(record)) <= MAX_RECEIPT_BYTES)


def _private_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    info = os.fstat(descriptor)
    try:
        _require(info.st_uid == os.getuid() and info.st_mode & 0o077 == 0)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def prepare_runtime(root=ROOT, *, output):
    """Build-compare and persist an exclusive private execution identity receipt."""
    failed = False
    try:
        root = Path(root).resolve()
        record = _snapshot(root)
        _validate_receipt(record)
        output = Path(output).absolute()
        _require(output.parent.resolve() == output.parent)
        output.mkdir(mode=0o700)
        directory = _private_directory(output)
        try:
            descriptor = os.open('runtime.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=directory)
            try:
                data = _canonical(record)
                with os.fdopen(descriptor, 'wb', closefd=False) as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.fsync(directory)
        finally:
            os.close(directory)
        return record
    except (Exception, KeyboardInterrupt):
        failed = True
    if failed:
        raise EvaluationRuntimeError('evaluation_runtime_invalid') from None


def verify_runtime(root, receipt):
    """Rebuild and independently compare every recorded category; never trust a flag."""
    failed = False
    try:
        root = Path(root).resolve()
        if isinstance(receipt, (str, Path)):
            receipt = Path(receipt).absolute()
            _require(receipt.parent.resolve() == receipt.parent)
            directory = _private_directory(receipt.parent)
            try:
                info = receipt.lstat()
                _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_mode & 0o077 == 0)
                record = _json(_regular_bytes(receipt, MAX_RECEIPT_BYTES))
            finally:
                os.close(directory)
        else:
            # Validate exact native containers and bounds before allocating a JSON snapshot.
            _validate_receipt(receipt)
            record = _json(_canonical(receipt))
        _validate_receipt(record)
        current = _snapshot(root)
        _require(current == record)
        return current
    except (Exception, KeyboardInterrupt):
        failed = True
    if failed:
        raise EvaluationRuntimeError('evaluation_runtime_invalid') from None


class _SafeArgumentParser:
    @staticmethod
    def create():
        import argparse

        class Parser(argparse.ArgumentParser):
            def error(self, message):
                raise EvaluationRuntimeError('evaluation_runtime_invalid')

        parser = Parser(description='Prepare or verify a clean, preinstalled execution identity. Run Python with -B.')
        commands = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
        prepare = commands.add_parser('prepare', help='Write an exclusive private runtime.json receipt.')
        prepare.add_argument('--output', required=True, type=Path)
        verify = commands.add_parser('verify', help='Rebuild and verify a private runtime.json receipt.')
        verify.add_argument('--receipt', required=True, type=Path)
        return parser


def main(argv=None):
    """Explicit local-only entry point; never print paths or diagnostics from inputs."""
    try:
        arguments = _SafeArgumentParser.create().parse_args(argv)
        _require(sys.dont_write_bytecode)
        if arguments.command == 'prepare':
            record = prepare_runtime(ROOT, output=arguments.output)
            state = 'prepared'
        else:
            record = verify_runtime(ROOT, arguments.receipt)
            state = 'verified'
        print(json.dumps(dict(revision='ECR-r1', state=state,
            identity_sha256=record['identity_sha256'], source_commit=record['source_commit'],
            files_count=len(record['files'])), sort_keys=True))
        return 0
    except Exception:
        print(json.dumps(dict(revision='ECR-r1', state='failed',
            error_code='evaluation_runtime_invalid'), sort_keys=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
