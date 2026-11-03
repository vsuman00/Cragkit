"""Synthetic archive mappings only; no build, extraction or package execution."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import traceback

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from artifact_licensing import ArtifactLicensingError, validate_artifact_licensing

LICENSE = b'Synthetic MIT license.\n'
NOTICE = b'Synthetic copyright notice.\n'
NAME = 'cragkit-example'
VERSION = '1.0.0rc1'
WHEEL_ROOT = 'cragkit_example-1.0.0rc1.dist-info/'
SDIST_ROOT = 'cragkit_example-1.0.0rc1/'


def metadata(**changes):
    values = {'Metadata-Version': '2.4', 'Name': NAME, 'Version': VERSION,
        'License-Expression': 'MIT', 'License-File': ['LICENSE', 'NOTICE'],
        'Requires-Dist': ['dependency-a; extra == "a"', 'dependency-b; extra == "b"'],
        'Provides-Extra': ['a', 'b']}
    values.update(changes)
    rows = []
    for name, value in values.items():
        for item in value if isinstance(value, list) else [value]:
            rows.append(f'{name}: {item}')
    return ('\n'.join(rows) + '\n\nSynthetic description.\n').encode()


def archive(kind):
    if kind == 'wheel':
        return {WHEEL_ROOT + 'METADATA': metadata(), WHEEL_ROOT + 'licenses/LICENSE': LICENSE,
            WHEEL_ROOT + 'licenses/NOTICE': NOTICE, 'cragkit_example/__init__.py': b'raise RuntimeError("never execute")'}
    if kind == 'sdist':
        project = (f'[project]\nname = "{NAME}"\nversion = "{VERSION}"\n'
            'license = "MIT"\nlicense-files = ["LICENSE", "NOTICE"]\n'
            '[build-system]\nrequires = ["hatchling==1.32.4"]\nbuild-backend = "hatchling.build"\n')
        return {SDIST_ROOT + 'pyproject.toml': project.encode(), SDIST_ROOT + 'LICENSE': LICENSE,
            SDIST_ROOT + 'NOTICE': NOTICE, SDIST_ROOT + 'src/unused.py': b'raise RuntimeError("never execute")'}
    return {'package/package.json': json.dumps(dict(name=NAME, version=VERSION, license='MIT',
        private=True, files=['dist', 'LICENSE', 'NOTICE'])).encode(), 'package/LICENSE': LICENSE,
        'package/NOTICE': NOTICE, 'package/dist/index.js': b'throw Error("never execute")'}


def check(files, kind, **changes):
    options = dict(kind=kind, package_name=NAME, version=VERSION, license_bytes=LICENSE, notice_bytes=NOTICE)
    options.update(changes)
    return validate_artifact_licensing(files, **options)


def rejected(files, kind, **changes):
    with pytest.raises(ArtifactLicensingError, match='^artifact_licensing_invalid$') as error:
        check(files, kind, **changes)
    assert error.value.args == ('artifact_licensing_invalid',)
    assert error.value.__cause__ is None and error.value.__context__ is None
    return error.value


@pytest.mark.parametrize('kind', ['wheel', 'sdist', 'npm'])
def test_valid_data_only_records_and_input_immutability(kind):
    files = archive(kind)
    original = deepcopy(files)
    assert check(files, kind) is None
    assert files == original


@pytest.mark.parametrize('metadata_version', ['1.0', '2.1', 'not-a-version'])
def test_license_expression_requires_the_declared_pep639_metadata_format(metadata_version):
    files = archive('wheel')
    files[WHEEL_ROOT+'METADATA'] = metadata(**{'Metadata-Version':metadata_version})
    rejected(files, 'wheel')


@pytest.mark.parametrize('metadata_version', ['2.5', '2.6'])
def test_newer_standard_metadata_retains_the_same_license_fields(metadata_version):
    files = archive('wheel')
    files[WHEEL_ROOT+'METADATA'] = metadata(**{'Metadata-Version':metadata_version})
    assert check(files, 'wheel') is None


@pytest.mark.parametrize('kind', ['wheel', 'sdist', 'npm'])
@pytest.mark.parametrize('asset', ['LICENSE', 'NOTICE'])
@pytest.mark.parametrize('mutation', ['missing', 'mutated', 'relocated'])
def test_assets_must_be_present_at_declared_locations_and_byte_exact(kind, asset, mutation):
    files = archive(kind)
    path = next(name for name in files if name.endswith('/' + asset))
    if mutation == 'missing':
        del files[path]
    elif mutation == 'mutated':
        files[path] += b'Secret payload must not appear in the error.'
    else:
        files[path.replace('/' + asset, '/elsewhere/' + asset)] = files.pop(path)
    rejected(files, kind)


@pytest.mark.parametrize('kind', ['wheel', 'sdist', 'npm'])
@pytest.mark.parametrize('field,value', [('package_name', 'foreign'), ('version', '1.0.0')])
def test_wrong_expected_identity_is_refused(kind, field, value):
    rejected(archive(kind), kind, **{field: value})


@pytest.mark.parametrize('name', ['Cragkit_Example', 'cragkit.example', 'CRAGKIT---example'])
@pytest.mark.parametrize('kind', ['wheel', 'sdist'])
def test_python_names_use_pep503_normalization(kind, name):
    assert check(archive(kind), kind, package_name=name) is None


def test_npm_identity_is_exact_and_scoped_names_are_supported():
    files = archive('npm')
    raw = json.loads(files['package/package.json'])
    raw['name'] = '@cragkit/core'
    files['package/package.json'] = json.dumps(raw).encode()
    assert check(files, 'npm', package_name='@cragkit/core') is None
    rejected(files, 'npm', package_name='@Cragkit/core')


@pytest.mark.parametrize('header', ['Metadata-Version', 'Name', 'Version', 'License-Expression'])
@pytest.mark.parametrize('different', [False, True])
def test_duplicate_singleton_metadata_headers_are_ambiguous_even_when_identical(header, different):
    files = archive('wheel')
    value = {'Metadata-Version': '2.4', 'Name': NAME, 'Version': VERSION, 'License-Expression': 'MIT'}[header]
    files[WHEEL_ROOT + 'METADATA'] = metadata(**{header: [value, 'private-marker' if different else value]})
    rejected(files, 'wheel')


@pytest.mark.parametrize('change', [
    {'License-Expression': 'Apache-2.0'}, {'License-Expression': []},
    {'License-File': ['LICENSE']}, {'License-File': ['LICENSE', 'NOTICE', 'NOTICE']},
    {'License-File': ['LICENSE', 'licenses/NOTICE']}, {'License': 'MIT'},
    {'License': 'private-marker'}, {'Name': '../private-marker'},
])
def test_wheel_license_declarations_are_exact_and_unambiguous(change):
    files = archive('wheel')
    files[WHEEL_ROOT + 'METADATA'] = metadata(**change)
    rejected(files, 'wheel')


def test_wheel_metadata_case_insensitive_duplicate_and_multiple_directories_refused():
    files = archive('wheel')
    files[WHEEL_ROOT + 'METADATA'] = b'name: other\n' + files[WHEEL_ROOT + 'METADATA']
    rejected(files, 'wheel')
    files = archive('wheel')
    files['other.dist-info/METADATA'] = metadata()
    rejected(files, 'wheel')
    files = archive('wheel')
    files['nested/' + WHEEL_ROOT + 'METADATA'] = files.pop(WHEEL_ROOT + 'METADATA')
    rejected(files, 'wheel')


def test_duplicate_npm_license_cannot_hide_behind_last_value():
    files = archive('npm')
    raw = files['package/package.json']
    files['package/package.json'] = raw.replace(b'"license": "MIT"', b'"license": "private-marker", "license": "MIT"')
    error = rejected(files, 'npm')
    assert 'private-marker' not in ''.join(traceback.format_exception(error))


@pytest.mark.parametrize('kind', ['wheel', 'sdist', 'npm'])
def test_validation_does_not_open_files_or_execute_archive_members(monkeypatch, kind):
    def forbidden(*args, **kwargs):
        pytest.fail('pure validator attempted file I/O or code evaluation')
    monkeypatch.setattr('builtins.open', forbidden)
    monkeypatch.setattr('builtins.eval', forbidden)
    monkeypatch.setattr('builtins.exec', forbidden)
    assert check(archive(kind), kind) is None


@pytest.mark.parametrize('field,value', [('license', 'GPL-3.0'), ('private', False), ('private', 1),
    ('files', ['dist', 'LICENSE']), ('files', ['dist', 'LICENSE', 'NOTICE', 'src']),
    ('files', ['dist', 'LICENSE', 'NOTICE', 'NOTICE']), ('files', 'dist,LICENSE,NOTICE')])
def test_npm_candidate_remains_private_with_exact_explicit_file_entries(field, value):
    files = archive('npm')
    project = json.loads(files['package/package.json']); project[field] = value
    files['package/package.json'] = json.dumps(project).encode()
    rejected(files, 'npm')


@pytest.mark.parametrize('body', [b'{"name":"private-marker","name":"cragkit-example"}',
    b'{"name":NaN}', b'[]', b'private-marker invalid JSON', b'\xff'])
def test_npm_json_parser_faults_are_fixed_without_payload_context(body):
    files = archive('npm'); files['package/package.json'] = body
    error = rejected(files, 'npm')
    assert 'private-marker' not in repr(error) + ''.join(traceback.format_exception(error))


@pytest.mark.parametrize('mutation', ['license', 'files', 'name', 'version', 'parse', 'project', 'second_prefix', 'loose_file'])
def test_sdist_requires_one_project_prefix_and_static_mit_identity(mutation):
    files = archive('sdist')
    key = SDIST_ROOT + 'pyproject.toml'
    if mutation in ('license', 'files', 'name', 'version'):
        replacements = {'license': ('license = "MIT"', 'license = {text = "MIT"}'),
            'files': ('["LICENSE", "NOTICE"]', '["LICENSE"]'),
            'name': (NAME, 'foreign'), 'version': (VERSION, '1.0.0')}
        old, new = replacements[mutation]
        files[key] = files[key].replace(old.encode(), new.encode())
    elif mutation == 'parse': files[key] = b'[project\nprivate-marker'
    elif mutation == 'project': files[key] = b'[tool.example]\nname="private-marker"'
    elif mutation == 'second_prefix': files['other/NOTICE'] = NOTICE
    else: files['NOTICE'] = NOTICE
    error = rejected(files, 'sdist')
    assert 'private-marker' not in ''.join(traceback.format_exception(error))


@pytest.mark.parametrize('kind', [None, True, 'zip', [], 'WHEEL'])
def test_unknown_formats_never_dispatch_to_an_archive_parser(kind):
    rejected(archive('wheel'), kind)


@pytest.mark.parametrize('files', [{}, [], {'a': 'not bytes'}, {1: b'bytes'}])
def test_invalid_archive_mapping_shapes_are_fixed(files):
    rejected(files, 'wheel')


@pytest.mark.parametrize('field,value', [('package_name', None), ('version', ''),
    ('license_bytes', b''), ('notice_bytes', 'not bytes')])
def test_invalid_expected_inputs_fail_without_private_error_values(field, value):
    rejected(archive('wheel'), 'wheel', **{field: value})
