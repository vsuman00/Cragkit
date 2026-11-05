"""Small, offline helpers for explicitly invoked PostgreSQL operator commands."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import stat


class OperatorError(RuntimeError):
    """Fixed diagnostics without configuration contents or database details."""


def regular_bytes(path: Path, limit: int, *, private: bool = False) -> bytes:
    """Read a bounded regular file without following a final-component symlink."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if private and (not stat.S_ISREG(before.st_mode)
                        or before.st_uid != os.getuid() or before.st_mode & 0o077):
            raise OperatorError('private_config_permissions')
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise OperatorError('operator_file_invalid')
        chunks = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(65536, limit + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise OperatorError('operator_file_invalid')
            chunks.append(chunk)
        after = os.fstat(descriptor)
        current = path.lstat()
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size,
                                  value.st_mtime_ns, value.st_mode, value.st_uid)
        if identity(before) != identity(after) or identity(after) != identity(current):
            raise OperatorError('operator_file_changed')
        return b''.join(chunks)
    finally:
        os.close(descriptor)


def load_config(path: Path) -> dict:
    raw = regular_bytes(path, 131072, private=True)
    try:
        value = json.loads(raw.decode('utf-8'))
    except (UnicodeError, ValueError):
        raise OperatorError('config_json_invalid') from None
    if type(value) is not dict:
        raise OperatorError('config_shape')
    for name in ('sslrootcert', 'passfile'):
        if type(value.get(name)) is not str:
            raise OperatorError('config_paths')
        value[name] = Path(value[name])
    value['max_size'] = 1
    return value


def require_neon_host(host: str) -> None:
    if not re.fullmatch(r'ep-[a-z0-9]+(?:-[a-z0-9]+)*\.c-[0-9]+\.[a-z0-9-]+\.aws\.neon\.tech', host) or '-pooler.' in host:
        raise OperatorError('direct_neon_host_required')


def require_client_tls(connection) -> None:
    if getattr(getattr(connection, 'pgconn', None), 'ssl_in_use', None) is not True:
        raise OperatorError('client_tls_required')


async def connect(config):
    """Open the legacy repair connection with verified TLS and bounded SQL waits."""
    import psycopg

    connection = await psycopg.AsyncConnection.connect(
        **{key: value for key, value in config.items() if key != 'max_size'},
        sslmode='verify-full', autocommit=True, connect_timeout=5,
        options='-c statement_timeout=30000 -c lock_timeout=2000')
    try:
        require_client_tls(connection)
    except BaseException:
        await asyncio.wait_for(connection.close(), 3)
        raise
    return connection
