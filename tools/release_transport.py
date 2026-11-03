"""Carry the fixed reviewed release inputs offline; never publish or execute them."""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import tempfile
import zipfile

import prepare_release_products as P

REVISION = 'PWK-r1'
MANIFEST_SHA256 = '7ced6f15ee096752d8e974d793d1bd99a8f41d77181fb061d2871d890aeb5dc5'
TRANSPORT_NAME = 'release-transport.zip'
RECEIPT_NAME = 'transport-receipt.json'
INPUT_NAMES = dict(archive='hosted-candidate-0c7c568.zip', run='ci-run.json',
                   jobs='ci-jobs.json', artifact='ci-artifact.json')
MEMBER_LIMITS = {INPUT_NAMES['archive']: P.MAX_ARCHIVE,
                 **{INPUT_NAMES[key]: 1024 * 1024 for key in ('run', 'jobs', 'artifact')},
                 P.MANIFEST_NAME: 4 * 1024 * 1024}
# Stay within the shared publication verifier's per-file ceiling as well.
MAX_TRANSPORT = P.MAX_ARCHIVE
MAX_EXPANDED = P.MAX_ARCHIVE


class TransportError(ValueError):
    """A fixed diagnostic with no retained input or parser contents."""


def require(condition, code):
    if not condition:
        raise TransportError(code)


def _destination(output):
    require(not os.path.lexists(output), 'output_exists')
    require(output.parent.is_dir()
            and not any(path.is_symlink() for path in (output.parent, *output.parent.parents)),
            'output_parent')


def _zip(payload):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED,
                         allowZip64=False) as archive:
        for name in sorted(payload):
            header = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            header.create_system = 3
            header.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(header, payload[name])
    raw = stream.getvalue()
    require(len(raw) <= MAX_TRANSPORT, 'transport_size_limit')
    return raw


def _members(raw):
    require(len(raw) <= MAX_TRANSPORT, 'transport_size_limit')
    # Check the small central-directory budget before ZipFile allocates its entries.
    # Our own deterministic format has neither ZIP64, disk splits nor a comment.
    require(len(raw) >= 22, 'transport_zip')
    end = struct.unpack('<4s4H2LH', raw[-22:])
    count = len(MEMBER_LIMITS)
    require(end[0] == b'PK\x05\x06' and end[1:3] == (0, 0)
            and end[3:5] == (count, count) and end[7] == 0, 'transport_inventory')
    max_central = sum(46 + len(name.encode('ascii')) for name in MEMBER_LIMITS)
    require(end[5] <= max_central and end[6] + end[5] == len(raw) - 22,
            'transport_central_limit')
    payload = {}
    total = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(len(entries) == count, 'transport_inventory')
        seen = set()
        for entry in entries:
            name = entry.filename
            require(name in MEMBER_LIMITS and name not in seen, 'transport_inventory')
            seen.add(name)
            mode = entry.external_attr >> 16
            require(not entry.is_dir() and stat.S_IFMT(mode) == stat.S_IFREG
                    and stat.S_IMODE(mode) == 0o600 and entry.create_system == 3,
                    'transport_member_type')
            require(entry.flag_bits == 0 and entry.compress_type == zipfile.ZIP_STORED
                    and not entry.extra and not entry.comment,
                    'transport_member_format')
            require(0 <= entry.file_size <= MEMBER_LIMITS[name]
                    and entry.compress_size == entry.file_size, 'transport_member_limit')
            total += entry.file_size
            require(total <= MAX_EXPANDED, 'transport_expanded_limit')
        # Refuse duplicate headers before ZipFile can emit payload-bearing warnings.
        for entry in entries:
            name = entry.filename
            with archive.open(entry) as source:
                content = source.read(MEMBER_LIMITS[name] + 1)
            require(len(content) == entry.file_size, 'transport_member_limit')
            payload[name] = content
    require(payload.keys() == MEMBER_LIMITS.keys(), 'transport_inventory')
    # Reject hidden prefixes/trailers, local-header drift and alternate metadata.
    require(_zip(payload) == raw, 'transport_noncanonical')
    return payload


def _validated_products(payload, temporary):
    require(payload.keys() == MEMBER_LIMITS.keys(), 'transport_inventory')
    manifest = payload[P.MANIFEST_NAME]
    require(P.digest(manifest) == MANIFEST_SHA256, 'manifest_digest')
    inputs = {}
    for key, name in INPUT_NAMES.items():
        path = temporary / name
        path.write_bytes(payload[name])
        path.chmod(0o600)
        inputs[key] = path
    # PPR derives bytes from the pinned CIB candidate, not from caller hashes.
    expected, _ = P.expected_products(**inputs)
    require(P.digest(expected[P.MANIFEST_NAME]) == MANIFEST_SHA256
            and expected[P.MANIFEST_NAME] == manifest, 'manifest_identity')
    return expected


def _expose(output, expected, *, completion_marker=P.MANIFEST_NAME):
    _destination(output)
    stage = Path(tempfile.mkdtemp(prefix='.cragkit-transport-', dir=output.parent))
    try:
        for relative, raw in expected.items():
            path = stage / relative
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with path.open('xb') as target:
                target.write(raw)
            path.chmod(0o600)
        P.verify_directory(stage, expected)
        _destination(output)
        P.publish_directory(stage, output, expected, completion_marker=completion_marker)
    finally:
        shutil.rmtree(stage)


def _receipt(raw, payload):
    return dict(revision=REVISION, state='prepared_local', publication_authorized=False,
                published=False, manifest_sha256=MANIFEST_SHA256,
                transport=dict(path=TRANSPORT_NAME, sha256=P.digest(raw), bytes=len(raw)),
                members=[dict(path=name, sha256=P.digest(payload[name]), bytes=len(payload[name]))
                         for name in sorted(payload)])


def _pack(*, archive, run, jobs, artifact, manifest, output):
    _destination(output)
    paths = dict(archive=archive, run=run, jobs=jobs, artifact=artifact)
    payload = {name: P.read_file(paths[key], MEMBER_LIMITS[name])
               for key, name in INPUT_NAMES.items()}
    payload[P.MANIFEST_NAME] = P.read_file(manifest, MEMBER_LIMITS[P.MANIFEST_NAME])
    require(sum(map(len, payload.values())) <= MAX_EXPANDED, 'transport_expanded_limit')
    with tempfile.TemporaryDirectory(prefix='cragkit-transport-audit-') as temporary:
        _validated_products(payload, Path(temporary))
    raw = _zip(payload)
    receipt = _receipt(raw, payload)
    _expose(output, {TRANSPORT_NAME: raw, RECEIPT_NAME: P.encode_json(receipt)},
            completion_marker=RECEIPT_NAME)
    return receipt


def _unpack(*, archive, expected_sha256, output):
    _destination(output)
    require(isinstance(expected_sha256, str)
            and re.fullmatch('[0-9a-f]{64}', expected_sha256) is not None,
            'expected_transport_digest')
    raw = P.read_file(archive, MAX_TRANSPORT)
    require(P.digest(raw) == expected_sha256, 'transport_digest')
    payload = _members(raw)
    with tempfile.TemporaryDirectory(prefix='cragkit-transport-audit-') as temporary:
        expected = _validated_products(payload, Path(temporary))
    expected.update({f'candidate/{name}': payload[name] for name in INPUT_NAMES.values()})
    _expose(output, expected)
    receipt = _receipt(raw, payload)
    receipt['state'] = 'verified_local'
    return receipt


def _guard(operation, **kwargs):
    code = 'transport_invalid'
    try:
        return operation(**kwargs)
    except TransportError as error:
        code = str(error)
    except Exception:
        pass
    raise TransportError(code)


def pack_transport(**kwargs):
    return _guard(_pack, **kwargs)


def unpack_transport(**kwargs):
    return _guard(_unpack, **kwargs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    pack = modes.add_parser('pack')
    for name in ('archive', 'run', 'jobs', 'artifact', 'manifest', 'output'):
        pack.add_argument('--' + name, type=Path, required=True)
    unpack = modes.add_parser('unpack')
    for name in ('archive', 'output'):
        unpack.add_argument('--' + name, type=Path, required=True)
    unpack.add_argument('--expected-sha256', required=True)
    args = vars(parser.parse_args(argv))
    mode = args.pop('mode')
    failed = False
    try:
        (pack_transport if mode == 'pack' else unpack_transport)(**args)
    except TransportError:
        failed = True
    print(json.dumps(dict(revision=REVISION, mode=mode,
        state='failed' if failed else 'prepared_local' if mode == 'pack' else 'verified_local',
        publication_authorized=False, published=False)))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
