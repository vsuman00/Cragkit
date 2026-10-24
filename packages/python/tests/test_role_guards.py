import asyncio
import json
from pathlib import Path
import re
import time

import pytest

import cragkit._postgres_session as session
import cragkit.ingestion as ingestion
from cragkit.errors import UnauthorizedScope


DENIED_ROLES = {
    'pg_read_all_data', 'pg_write_all_data', 'pg_read_server_files',
    'pg_write_server_files', 'pg_execute_server_program',
}
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(('name', 'sql', 'filename'), [
    ('_ROLE_SQL', session._ROLE_SQL, 'postgres-session.ts'),
    ('_WRITER_ROLE_SQL', ingestion._WRITER_ROLE_SQL, 'ingestion.ts'),
])
def test_role_sql_has_exact_membership_denylist_and_native_parity(name, sql, filename):
    source = (ROOT / 'typescript' / 'src' / filename).read_text()
    match = re.search(rf'export const {name} = (`[^`]*`|"(?:[^"\\]|\\.)*");', source)
    assert match is not None
    literal = match.group(1)
    native = literal[1:-1] if literal.startswith('`') else json.loads(literal)
    assert sql == native
    assert "pg_has_role(current_user,r.oid,'MEMBER')" in sql
    assert "pg_has_role(current_user,r.oid,'USAGE')" not in sql
    denylist = re.search(r"r\.rolname IN \(([^)]+)\)", sql)
    assert denylist is not None
    assert set(re.findall(r"'([^']+)'", denylist.group(1))) == DENIED_ROLES
    for attribute in ('rolsuper', 'rolbypassrls', 'rolcreaterole', 'rolcreatedb', 'rolreplication'):
        assert f'r.{attribute}' in sql


@pytest.mark.parametrize('writer', [False, True])
def test_negative_role_decision_stops_before_catalog_scope_or_write(monkeypatch, writer):
    calls = []

    async def query(connection, sql, values, deadline):
        calls.append(sql)
        return [(False,)]

    monkeypatch.setattr(ingestion if writer else session, '_query', query)

    async def run():
        with pytest.raises(UnauthorizedScope):
            if writer:
                indexer = ingestion.PostgresIndexer(None, authorize_write=lambda *args: None)
                await indexer._stage(None, None, None, None, '', '', None, time.monotonic() + 1, None)
            else:
                await session._validate(None, time.monotonic() + 1)

    asyncio.run(run())
    assert calls == [ingestion._WRITER_ROLE_SQL if writer else session._ROLE_SQL]
