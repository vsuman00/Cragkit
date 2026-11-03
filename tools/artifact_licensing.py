"""Pure ALC-r1 identity and licensing checks on already bounded archive bytes."""
from email import policy
from email.parser import BytesParser
import json
import re
import tomllib


class ArtifactLicensingError(ValueError):
    """One fixed diagnostic without archive content or parser exception chains."""

    def __init__(self):
        super().__init__('artifact_licensing_invalid')


def _require(condition):
    if not condition:
        raise ArtifactLicensingError()


def _python_name(value):
    _require(type(value) is str and re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?', value) is not None)
    return re.sub(r'[-_.]+', '-', value).lower()


def _license_files(value):
    _require(type(value) is list and len(value) == 2
             and all(type(name) is str for name in value)
             and sorted(value) == ['LICENSE', 'NOTICE'])


def _assets(files, prefix, license_bytes, notice_bytes):
    _require(files.get(prefix + 'LICENSE') == license_bytes
             and files.get(prefix + 'NOTICE') == notice_bytes)


def _wheel(files, package_name, version, license_bytes, notice_bytes):
    names = [name for name in files if name.endswith('.dist-info/METADATA')]
    _require(len(names) == 1)
    parts = names[0].split('/')
    _require(len(parts) == 2 and parts[0] != '.dist-info')
    metadata = BytesParser(policy=policy.default).parsebytes(files[names[0]])
    _require(not metadata.defects)
    for name in ('Metadata-Version', 'Name', 'Version', 'License-Expression'):
        _require(len(metadata.get_all(name, [])) == 1)
    _require(str(metadata['Metadata-Version']) in ('2.4', '2.5', '2.6')
             and _python_name(str(metadata['Name'])) == _python_name(package_name)
             and str(metadata['Version']) == version
             and str(metadata['License-Expression']) == 'MIT')
    # License-File is intentionally repeated; dependency/extra headers may be too.
    _license_files([str(value) for value in metadata.get_all('License-File', [])])
    _require(metadata.get_all('License', []) == [])
    _assets(files, parts[0] + '/licenses/', license_bytes, notice_bytes)


def _sdist(files, package_name, version, license_bytes, notice_bytes):
    roots = {name.split('/')[0] for name in files}
    _require(len(roots) == 1 and all('/' in name for name in files))
    prefix = next(iter(roots)) + '/'
    raw = files.get(prefix + 'pyproject.toml')
    _require(type(raw) is bytes)
    metadata = tomllib.loads(raw.decode('utf-8'))
    project = metadata.get('project')
    _require(type(project) is dict
             and _python_name(project.get('name')) == _python_name(package_name)
             and project.get('version') == version and project.get('license') == 'MIT')
    _license_files(project.get('license-files'))
    _assets(files, prefix, license_bytes, notice_bytes)


def _json_object(pairs):
    result = {}
    for name, value in pairs:
        _require(name not in result)
        result[name] = value
    return result


def _json_constant(_):
    raise ArtifactLicensingError()


def _npm(files, package_name, version, license_bytes, notice_bytes):
    raw = files.get('package/package.json')
    _require(type(raw) is bytes and all(name.startswith('package/') for name in files))
    project = json.loads(raw.decode('utf-8'), object_pairs_hook=_json_object, parse_constant=_json_constant)
    _require(type(project) is dict and project.get('name') == package_name
             and project.get('version') == version and project.get('license') == 'MIT'
             and project.get('private') is True)
    entries = project.get('files')
    _require(type(entries) is list and len(entries) == 3
             and all(type(name) is str for name in entries)
             and sorted(entries) == ['LICENSE', 'NOTICE', 'dist'])
    _assets(files, 'package/', license_bytes, notice_bytes)


def validate_artifact_licensing(files, *, kind, package_name, version, license_bytes, notice_bytes):
    """Validate known archive layouts without I/O, building or executing code.

    Archive extraction/path/size/model-asset admission belongs to the caller's
    separate generic guard. This helper inspects only supplied data bytes.
    """
    failed = False
    try:
        _require(type(files) is dict and bool(files)
                 and all(type(name) is str and type(raw) is bytes for name, raw in files.items())
                 and type(kind) is str and kind in ('wheel', 'sdist', 'npm')
                 and type(package_name) is str and bool(package_name)
                 and type(version) is str and bool(version)
                 and type(license_bytes) is bytes and bool(license_bytes)
                 and type(notice_bytes) is bytes and bool(notice_bytes))
        validator = {'wheel': _wheel, 'sdist': _sdist, 'npm': _npm}[kind]
        validator(files, package_name, version, license_bytes, notice_bytes)
    except Exception:
        failed = True
    if failed:
        # Raise after leaving the handler so parser errors cannot retain payloads.
        raise ArtifactLicensingError()
