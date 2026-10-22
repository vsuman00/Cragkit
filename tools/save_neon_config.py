"""Import one pinned Neon administrator URI into private native-client files."""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import parse_qsl, unquote_to_bytes, urlsplit
import warnings

REPOSITORY = Path(__file__).resolve().parents[1]
MAX_URI_BYTES = 16384


class ConfigError(ValueError):
    """A safe error code, never containing credential input."""


def _clean(value: str) -> bool:
    return not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)


def _decode(value: str) -> str:
    if re.search(r'%(?![0-9A-Fa-f]{2})', value):
        raise ConfigError('invalid_uri_encoding')
    try:
        result = unquote_to_bytes(value).decode('utf-8', errors='strict')
    except UnicodeError:
        raise ConfigError('invalid_uri_encoding') from None
    if not _clean(result):
        raise ConfigError('invalid_uri_field')
    return result


def _private_directory(directory: Path) -> int:
    if not directory.is_absolute() or not _clean(str(directory)):
        raise ConfigError('private_directory_required')
    resolved = directory.resolve()
    if resolved != directory or resolved == REPOSITORY or REPOSITORY in resolved.parents:
        raise ConfigError('external_nonsymlink_directory_required')
    try:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            os.close(fd)
            raise ConfigError('private_directory_required')
        return fd
    except OSError:
        raise ConfigError('private_directory_required') from None


def save_config(uri: str, *, directory: Path, expected_host: str,
                expected_database: str, expected_user: str, ca: Path) -> None:
    """Validate synthetic or hidden input, then exclusively create two private files."""
    if not isinstance(uri, str) or not uri.isascii() or not _clean(uri) or ' ' in uri:
        raise ConfigError('invalid_uri')
    try:
        if len(uri.encode('utf-8')) > MAX_URI_BYTES:
            raise ConfigError('invalid_uri')
    except UnicodeError:
        raise ConfigError('invalid_uri_encoding') from None
    if not re.fullmatch(r'ep-[a-z0-9-]+(?:\.[a-z0-9-]+)+\.neon\.tech', expected_host) or '-pooler' in expected_host:
        raise ConfigError('direct_neon_host_required')
    if not all(re.fullmatch(r'[A-Za-z0-9_.@-]+', value) for value in (expected_database, expected_user)):
        raise ConfigError('scalar_identity_required')
    if not ca.is_absolute() or not _clean(str(ca)) or not ca.is_file() or ca.is_symlink():
        raise ConfigError('ca_file_required')
    try:
        parsed = urlsplit(uri)
        if parsed.scheme not in ('postgresql', 'postgres') or parsed.fragment or parsed.netloc.count('@') != 1:
            raise ConfigError('invalid_uri')
        if parsed.hostname != expected_host or parsed.port not in (None, 5432):
            raise ConfigError('target_mismatch')
        if parsed.username is None or parsed.password is None:
            raise ConfigError('credentials_required')
        user, password, database = (_decode(parsed.username), _decode(parsed.password), _decode(parsed.path[1:]))
        if not parsed.path.startswith('/') or user != expected_user or database != expected_database or not password:
            raise ConfigError('target_mismatch')
        # Only harmless TLS requests are accepted; the native config always verifies fully.
        if re.search(r'%(?![0-9A-Fa-f]{2})', parsed.query):
            raise ConfigError('invalid_uri_encoding')
        query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True,
                          encoding='utf-8', errors='strict', max_num_fields=4)
        allowed = {'sslmode': {'require', 'verify-full'}}
        if len({key for key, _ in query}) != len(query) or any(
            key not in allowed or value not in allowed[key] for key, value in query
        ):
            raise ConfigError('uri_options_forbidden')
    except (ValueError, UnicodeError) as error:
        if isinstance(error, ConfigError):
            raise
        raise ConfigError('invalid_uri') from None
    config = dict(host=expected_host, port=5432, dbname=database, user=user,
                  sslrootcert=str(ca), passfile=str(directory / 'admin.pgpass'),
                  max_size=1, max_waiting=1, startup_timeout=5.0, acquire_timeout=2.0,
                  close_timeout=3.0, release_timeout=1.0)
    def escape(value: str) -> str:
        return value.replace('\\', '\\\\').replace(':', '\\:')
    pgpass = ':'.join(escape(value) for value in (expected_host, '5432', database, user, password)) + '\n'
    fd = _private_directory(directory)
    created: list[str] = []
    try:
        for name, content in (('admin.pgpass', pgpass), ('admin-config.json', json.dumps(config, indent=2) + '\n')):
            output = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            created.append(name)
            os.fchmod(output, 0o600)
            with os.fdopen(output, 'w', encoding='utf-8') as destination:
                destination.write(content)
                destination.flush()
                os.fsync(destination.fileno())
    except OSError:
        for name in reversed(created):
            os.unlink(name, dir_fd=fd)
        raise ConfigError('private_file_creation_failed') from None
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--expected-host', required=True)
    parser.add_argument('--expected-database', required=True)
    parser.add_argument('--expected-user', required=True)
    parser.add_argument('--ca', type=Path, required=True)
    args = parser.parse_args()
    try:
        if not sys.stdin.isatty():
            raise ConfigError('interactive_terminal_required')
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            uri = getpass.getpass('Neon administrator URI (hidden): ')
        save_config(uri, directory=args.directory, expected_host=args.expected_host,
                    expected_database=args.expected_database, expected_user=args.expected_user, ca=args.ca)
    except (ConfigError, getpass.GetPassWarning, EOFError, KeyboardInterrupt) as error:
        code = str(error) if isinstance(error, ConfigError) else 'hidden_input_unavailable'
        print(f'Neon configuration import failed: {code}.', file=sys.stderr)
        return 1
    print('Private Neon administrator configuration saved.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
