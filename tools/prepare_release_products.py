"""Prepare and verify reviewed RC1 products offline, without uploading anything."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import zipfile

from artifact_licensing import validate_artifact_licensing
import check_ci_bundle as CI
from check_artifacts import safe_member

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = 'a3ff7e81332d849724407356d220c991e8a8411d'
RUN_ID, JOB_ID, ARTIFACT_ID = 41777862696, 126402305700, 13297269766
BUNDLE_SHA256 = '422cb0367bdd11b61416b287378abffbd78c60442f1ceb1ce7523280d58858be'
MAX_ARCHIVE = 16 * 1024 * 1024
MAX_UNPACKED = 32 * 1024 * 1024
MAX_TAR = 40 * 1024 * 1024
MAX_MEMBERS = 2048
MANIFEST_NAME = 'publication-manifest.json'
TRANSFORMATION = {'member': 'package/package.json', 'json_pointer': '/private',
                  'before': True, 'after': False,
                  'other_json_values_and_member_bytes_names_modes': 'unchanged'}


class PreparationError(ValueError):
    """A fixed diagnostic without private archive or parser content."""


def require(condition, code):
    if not condition:
        raise PreparationError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encode_json(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True,
                       allow_nan=False) + '\n').encode('utf-8')


def parse_json(raw):
    value = CI.parse_json(raw)
    pending = [value]
    while pending:
        item = pending.pop()
        require(not isinstance(item, float) or math.isfinite(item), 'json_nonfinite')
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return value


def read_file(path, limit):
    require(not path.is_symlink() and path.is_file(), 'input_not_regular')
    with path.open('rb') as source:
        raw = source.read(limit + 1)
    require(len(raw) <= limit, 'input_size_limit')
    return raw


def member_path(name):
    safe_member(name)
    pieces = name[:-1].split('/') if name.endswith('/') else name.split('/')
    require(all(piece not in ('', '.', '..') for piece in pieces), 'unsafe_member_name')
    require(not any(ord(char) < 32 or ord(char) == 127 for char in name),
            'unsafe_member_name')


@dataclass(frozen=True)
class Member:
    name: str
    content: bytes
    mode: int
    directory: bool = False


def members(raw, kind):
    """Read bounded archives in memory; never extract or execute members."""
    require(len(raw) <= MAX_ARCHIVE, 'archive_size_limit')
    result = []
    names = set()
    total = 0

    def add(name, content, mode, directory):
        nonlocal total
        member_path(name)
        # A file and a directory cannot share a normalized path.
        key = name.rstrip('/')
        require(key not in names, 'duplicate_archive_member')
        names.add(key)
        total += len(content)
        require(len(names) <= MAX_MEMBERS and total <= MAX_UNPACKED, 'member_limit')
        result.append(Member(name, content, mode, directory))

    if kind == 'wheel':
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            require(len(archive.infolist()) <= MAX_MEMBERS, 'member_limit')
            for item in archive.infolist():
                mode = item.external_attr >> 16
                directory = item.is_dir()
                require(mode & 0o170000 in (0, 0o040000 if directory else 0o100000),
                        'archive_special_member')
                require(item.file_size >= 0 and total + item.file_size <= MAX_UNPACKED,
                        'member_limit')
                add(item.filename, archive.read(item), mode & 0o777, directory)
    else:
        with gzip.GzipFile(fileobj=io.BytesIO(raw), mode='rb') as compressed:
            unpacked = compressed.read(MAX_TAR + 1)
        require(len(unpacked) <= MAX_TAR, 'tar_size_limit')
        with tarfile.open(fileobj=io.BytesIO(unpacked), mode='r:') as archive:
            for item in archive:
                require(item.isdir() or item.isfile(), 'archive_special_member')
                require(len(names) < MAX_MEMBERS and item.size >= 0
                        and total + item.size <= MAX_UNPACKED, 'member_limit')
                source = None if item.isdir() else archive.extractfile(item)
                require(item.isdir() or source is not None, 'archive_read')
                content = b'' if source is None else source.read(item.size + 1)
                require(item.isdir() or len(content) == item.size, 'archive_read')
                add(item.name, content, item.mode & 0o777, item.isdir())
    require(bool(result), 'empty_archive')
    files = {item.name for item in result if not item.directory}
    require(not any('/'.join(item.name.rstrip('/').split('/')[:index]) in files
                    for item in result
                    for index in range(1, len(item.name.rstrip('/').split('/')))),
            'member_path_conflict')
    return sorted(result, key=lambda item: item.name)


def file_view(entries):
    return {item.name: item.content for item in entries if not item.directory}


def inventory(entries):
    return [dict(path=item.name, mode=item.mode,
                 kind='directory' if item.directory else 'file',
                 bytes=len(item.content), sha256=digest(item.content)) for item in entries]


def public_manifest(raw):
    project = parse_json(raw)
    require(type(project) is dict and project.get('private') is True, 'npm_private_guard')
    text = raw.decode('utf-8')
    decoder = json.JSONDecoder()

    def skip(index):
        while index < len(text) and text[index] in ' \t\r\n':
            index += 1
        return index

    index = skip(0) + 1
    while True:
        key, index = decoder.raw_decode(text, skip(index))
        index = skip(index)
        require(text[index] == ':', 'npm_json_shape')
        value_start = skip(index + 1)
        _, index = decoder.raw_decode(text, value_start)
        if key == 'private':
            require(text[value_start:index] == 'true', 'npm_private_guard')
            # Preserve all other bytes, including exact JSON number representations.
            return (text[:value_start] + 'false' + text[index:]).encode('utf-8')
        index = skip(index)
        require(text[index] == ',', 'npm_json_shape')
        index += 1


def repack_npm(entries):
    original = file_view(entries)
    changed = public_manifest(original['package/package.json'])
    expected = [Member(item.name, changed if item.name == 'package/package.json'
                       else item.content, item.mode, item.directory) for item in entries]
    stream = io.BytesIO()
    # Explicit mtime/name and normalized headers make the new archive reproducible.
    with gzip.GzipFile(fileobj=stream, mode='wb', filename='', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for item in expected:
                header = tarfile.TarInfo(item.name)
                header.mode = item.mode
                header.type = tarfile.DIRTYPE if item.directory else tarfile.REGTYPE
                header.size = len(item.content)
                archive.addfile(header, None if item.directory else io.BytesIO(item.content))
    prepared = stream.getvalue()
    actual = members(prepared, 'npm')
    require(actual == expected, 'npm_projection_drift')
    # Guard the comparison view before reusing ALC-r1's private-candidate rule.
    public = parse_json(file_view(actual)['package/package.json'])
    require(public.get('private') is False, 'npm_public_guard')
    public['private'] = True
    require(public == parse_json(original['package/package.json']), 'npm_json_drift')
    comparison = file_view(actual)
    comparison['package/package.json'] = original['package/package.json']
    require(comparison == original, 'npm_member_drift')
    return prepared, actual, comparison


def expected_products(*, archive, run, jobs, artifact):
    original = read_file(archive, MAX_ARCHIVE)
    require(digest(original) == BUNDLE_SHA256, 'candidate_digest')
    metadata = [parse_json(read_file(path, 1024 * 1024))
                for path in (run, jobs, artifact)]
    license_bytes, notice_bytes = (read_file(ROOT / name, 1024 * 1024)
                                   for name in ('LICENSE', 'NOTICE'))
    # Audit a private snapshot, so later input-path changes cannot replace checked bytes.
    with tempfile.TemporaryDirectory(prefix='cragkit-publication-audit-') as temporary:
        snapshot = Path(temporary) / 'candidate.zip'
        snapshot.write_bytes(original)
        audit = CI.verify_bundle(snapshot, *metadata, expected_source=SOURCE_COMMIT,
            expected_run=RUN_ID, expected_job=JOB_ID, expected_artifact=ARTIFACT_ID,
            expected_digest=BUNDLE_SHA256, license_bytes=license_bytes,
            notice_bytes=notice_bytes)
    outputs = {}
    records = []
    retained = []
    with zipfile.ZipFile(io.BytesIO(original)) as bundle:
        for source_path, (kind, package, role) in CI.product_inventory().items():
            raw = bundle.read(source_path)
            original_members = members(raw, kind)
            if role == 'rebuilt_wheel':
                retained.append(dict(path=source_path, bytes=len(raw), sha256=digest(raw),
                                     members=inventory(original_members)))
                continue
            prepared, prepared_members = raw, original_members
            comparison = file_view(original_members)
            if kind == 'npm':
                prepared, prepared_members, comparison = repack_npm(original_members)
            validate_artifact_licensing(comparison, kind=kind, package_name=package,
                version='1.0.0-rc.1' if kind == 'npm' else '1.0.0rc1',
                license_bytes=license_bytes, notice_bytes=notice_bytes)
            registry = 'npm' if kind == 'npm' else 'pypi'
            product_path = f'products/{registry}/{Path(source_path).name}'
            require(product_path not in outputs, 'product_collision')
            outputs[product_path] = prepared
            records.append(dict(path=product_path, source_path=source_path,
                package=package, registry=registry, kind=kind,
                version='1.0.0-rc.1' if kind == 'npm' else '1.0.0rc1',
                original=dict(bytes=len(raw), sha256=digest(raw), members=inventory(original_members)),
                prepared=dict(bytes=len(prepared), sha256=digest(prepared), members=inventory(prepared_members)),
                transformation=TRANSFORMATION if kind == 'npm' else 'byte_for_byte_copy'))
    require(len(outputs) == 9 and len(retained) == 3, 'publication_inventory')
    manifest = dict(revision='PPR-r1', state='prepared_local',
        publication_authorized=False, published=False, source_commit=SOURCE_COMMIT,
        ci=dict(revision='CIB-r1', run_id=RUN_ID, job_id=JOB_ID, artifact_id=ARTIFACT_ID,
                archive_sha256=BUNDLE_SHA256, archive_bytes=len(original),
                acceptance_reports=audit['acceptance_reports']),
        license_sha256=digest(license_bytes), notice_sha256=digest(notice_bytes),
        pending=['registry_ownership', 'authentication', 'post_publication_smoke'],
        retained_evidence=dict(original_bundle='supplied --archive input; retained unchanged',
                               rebuilt_wheels=retained),
        products=sorted(records, key=lambda record: record['path']))
    outputs[MANIFEST_NAME] = encode_json(manifest)
    return outputs, manifest


def verify_directory(prepared, expected):
    require(not prepared.is_symlink() and prepared.is_dir(), 'prepared_directory')
    expected_dirs = {str(parent) for path in expected for parent in Path(path).parents
                     if str(parent) != '.'}
    found = set()
    directories = set()
    for current, dirs, files in os.walk(prepared, followlinks=False):
        for name in dirs + files:
            path = Path(current) / name
            require(not path.is_symlink(), 'prepared_link')
            relative = path.relative_to(prepared).as_posix()
            if path.is_dir():
                directories.add(relative)
                require(relative in expected_dirs, 'prepared_inventory')
            else:
                require(path.is_file() and relative in expected, 'prepared_inventory')
                require(read_file(path, MAX_ARCHIVE) == expected[relative], 'prepared_bytes')
                found.add(relative)
    require(found == expected.keys() and directories == expected_dirs, 'prepared_inventory')


def publish_directory(stage, output, expected, *, completion_marker=MANIFEST_NAME):
    require(completion_marker in expected, 'completion_marker_missing')
    created_files = []
    created_dirs = []

    def identity(path):
        status = path.lstat()
        return status.st_dev, status.st_ino

    def own_directory(path):
        path.mkdir(mode=0o700)
        created_dirs.append((path, identity(path)))

    def link(relative):
        source, target = stage / relative, output / relative
        own_identity = identity(source)
        os.link(source, target, follow_symlinks=False)
        created_files.append((target, own_identity))

    complete = False
    try:
        # Exclusive claim: unlike POSIX rename, mkdir cannot replace an empty directory.
        own_directory(output)
        directories = {parent for name in expected for parent in Path(name).parents
                       if str(parent) != '.'}
        for relative in sorted(directories, key=lambda path: (len(path.parts), str(path))):
            own_directory(output / relative)
        for relative in sorted(set(expected) - {completion_marker}):
            link(relative)
        verify_directory(output, {name: raw for name, raw in expected.items()
                                  if name != completion_marker})
        # A directory becomes complete only when its checked manifest exists.
        link(completion_marker)
        verify_directory(output, expected)
        complete = True
    finally:
        if not complete:
            for path, own_identity in reversed(created_files):
                try:
                    if identity(path) == own_identity:
                        path.unlink()
                except OSError:
                    pass
            for path, own_identity in reversed(created_dirs):
                try:
                    if identity(path) == own_identity:
                        path.rmdir()
                except OSError:
                    pass


def _prepare(*, output, **inputs):
    require(not os.path.lexists(output), 'output_exists')
    require(output.parent.is_dir()
            and not any(path.is_symlink() for path in (output.parent, *output.parent.parents)),
            'output_parent')
    expected, manifest = expected_products(**inputs)
    stage = Path(tempfile.mkdtemp(prefix='.cragkit-publication-', dir=output.parent))
    try:
        for relative, raw in expected.items():
            path = stage / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        verify_directory(stage, expected)
        require(not os.path.lexists(output), 'output_exists')
        publish_directory(stage, output, expected)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return manifest


def _verify(*, prepared, **inputs):
    expected, manifest = expected_products(**inputs)
    verify_directory(prepared, expected)
    return manifest


def _guard(operation, **kwargs):
    code = 'publication_invalid'
    try:
        return operation(**kwargs)
    except PreparationError as error:
        code = str(error)
    except Exception:
        pass
    raise PreparationError(code)


def prepare_products(**kwargs):
    return _guard(_prepare, **kwargs)


def verify_products(**kwargs):
    return _guard(_verify, **kwargs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    for name in ('prepare', 'verify'):
        mode = modes.add_parser(name)
        for option in ('archive', 'run', 'jobs', 'artifact'):
            mode.add_argument('--' + option, type=Path, required=True)
        mode.add_argument('--output' if name == 'prepare' else '--prepared',
                          type=Path, required=True)
    args = vars(parser.parse_args(argv))
    mode = args.pop('mode')
    failed = False
    try:
        (prepare_products if mode == 'prepare' else verify_products)(**args)
    except PreparationError:
        failed = True
    print(json.dumps(dict(revision='PPR-r1', mode=mode,
        state='failed' if failed else 'prepared_local' if mode == 'prepare' else 'verified_local',
        publication_authorized=False, published=False)))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
