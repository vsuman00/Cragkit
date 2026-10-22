import importlib.util
import json
import os
from pathlib import Path
import stat
import sys

import pytest

SPEC = importlib.util.spec_from_file_location('save_neon_config', Path(__file__).resolve().parents[1] / 'save_neon_config.py')
assert SPEC and SPEC.loader
SAVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAVE)
HOST = 'ep-test-unit.c-4.ap-southeast-1.aws.neon.tech'
URI = f'postgresql://cragkit_admin:synthetic%25%3A%5Cpassword@{HOST}/cragkit?sslmode=require'


@pytest.fixture
def options(tmp_path):
    directory = tmp_path / 'private'
    directory.mkdir(mode=0o700)
    ca = tmp_path / 'ca.pem'
    ca.write_text('Synthetic CA fixture, never used for a connection.')
    return dict(directory=directory, expected_host=HOST, expected_database='cragkit',
                expected_user='cragkit_admin', ca=ca)


def test_pinned_config_and_escaped_password(options, monkeypatch):
    monkeypatch.setenv('PGSSLMODE', 'disable')
    monkeypatch.setenv('DATABASE_URL', 'ignored')
    SAVE.save_config(URI, **options)
    directory = options['directory']
    config = json.loads((directory / 'admin-config.json').read_text())
    assert config == dict(host=HOST, port=5432, dbname='cragkit', user='cragkit_admin',
                         sslrootcert=str(options['ca']), passfile=str(directory / 'admin.pgpass'),
                         max_size=1, max_waiting=1, startup_timeout=5.0, acquire_timeout=2.0,
                         close_timeout=3.0, release_timeout=1.0)
    assert (directory / 'admin.pgpass').read_text() == f'{HOST}:5432:cragkit:cragkit_admin:synthetic%\\:\\\\password\n'
    for path in directory.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert 'password' not in (directory / 'admin-config.json').read_text()


@pytest.mark.parametrize('uri', [
    URI.replace(HOST, 'ep-wrong.c-4.ap-southeast-1.aws.neon.tech'),
    URI.replace(HOST, HOST + ':5433'),
    URI.replace('/cragkit?', '/other?'), URI.replace('cragkit_admin:', 'other:'),
    URI.replace('sslmode=require', 'sslmode=disable'), URI + '&host=evil.invalid',
    URI + '&sslrootcert=evil', URI + '&channel_binding=require', URI + '&channel_binding=prefer', URI + '&sslmode=require', URI + '#fragment',
    URI.replace('synthetic%25', 'synthetic%xx'), URI.replace('%25', '%ff'),
    URI.replace('%25', '%00'), URI.replace('%25', '%0a'), URI.replace('%25', '%0d'),
    URI.replace('%25', '%7f'), URI.replace('%25', '@'), URI.replace('%25', ' '), '\n' + URI, URI + '\0', 'x' * 16385,
])
def test_rejects_unsafe_uri_without_outputs(options, uri):
    with pytest.raises(SAVE.ConfigError) as caught:
        SAVE.save_config(uri, **options)
    assert 'synthetic' not in str(caught.value)
    assert list(options['directory'].iterdir()) == []


@pytest.mark.parametrize('kind', ['public', 'symlink', 'relative', 'missing_ca', 'repo', 'pooler'])
def test_rejects_unsafe_paths_and_pooled_target(options, tmp_path, kind):
    if kind == 'public':
        options['directory'].chmod(0o755)
    elif kind == 'symlink':
        link = tmp_path / 'link'; link.symlink_to(options['directory'], target_is_directory=True)
        options['directory'] = link
    elif kind == 'relative':
        options['directory'] = Path('relative')
    elif kind == 'missing_ca':
        options['ca'] = tmp_path / 'missing'
    elif kind == 'repo':
        options['directory'] = SAVE.REPOSITORY
    else:
        options['expected_host'] = HOST.replace('ep-test-unit', 'ep-test-unit-pooler')
    with pytest.raises(SAVE.ConfigError):
        SAVE.save_config(URI, **options)


@pytest.mark.parametrize('name', ['admin.pgpass', 'admin-config.json'])
def test_existing_file_is_preserved_and_only_created_files_rolled_back(options, name):
    existing = options['directory'] / name
    existing.write_text('preserve me')
    with pytest.raises(SAVE.ConfigError, match='private_file_creation_failed'):
        SAVE.save_config(URI, **options)
    assert existing.read_text() == 'preserve me'
    assert sorted(path.name for path in options['directory'].iterdir()) == [name]


def test_existing_symlink_is_not_followed(options, tmp_path):
    target = tmp_path / 'preserved'; target.write_text('untouched')
    (options['directory'] / 'admin.pgpass').symlink_to(target)
    with pytest.raises(SAVE.ConfigError):
        SAVE.save_config(URI, **options)
    assert target.read_text() == 'untouched'


def test_nonterminal_prompt_never_calls_getpass(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['save_neon_config', '--directory', '/unused', '--expected-host', HOST,
                                    '--expected-database', 'cragkit', '--expected-user', 'cragkit_admin', '--ca', '/unused'])
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: False)
    monkeypatch.setattr(SAVE.getpass, 'getpass', lambda *args: pytest.fail('prompt called'))
    assert SAVE.main() == 1
