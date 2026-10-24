import asyncio
from hashlib import sha256
import json
from pathlib import Path

import pytest

import cragkit._postgres_session as implementation
from cragkit._identifiers import extract_identifiers, validate_identifier
from cragkit._postgres_session import IdentifierCandidate, PostgresSession
from cragkit.errors import IntegrityViolation, InvalidRequest, UnsupportedCapability
from test_postgres_session import Connection, Cursor, Resource, request, scope

DIGEST = sha256(b'text').hexdigest()
ROW = ('tenant-a', 'engineering', 'document', 'revision', 'generation', 'chunk', 0, 4, DIGEST, 1.0, 'native_fts.v1', 'pg_catalog.simple')


class IdentifierConnection(Connection):
    def __init__(self):
        super().__init__()
        self.identifiers = [ROW]
        self.source = [(*ROW[:6], DIGEST, 4, 'text', 0, 4, 4, 'text', DIGEST, 'fixture', 'native_fts.v1', True)]

    async def execute(self, query, params=None):
        for sql, rows in ((implementation._IDENTIFIER_SQL, self.identifiers), (implementation._SOURCE_SQL, self.source)):
            if query.startswith(sql.split('{predicate}')[0]):
                self.calls.append((query, params))
                return Cursor(rows)
        return await super().execute(query, params)


def test_shared_extraction_profile():
    fixture = json.loads((Path(__file__).resolve().parents[3] / 'contracts/fixtures/identifier_fusion.json').read_text())
    for case in fixture['extraction']:
        assert list(extract_identifiers(case['text'])) == case['expected']
    assert validate_identifier('C++') == 'C++'
    assert extract_identifiers('x' + '1' * 255) == ('x' + '1' * 255,)


def test_exact_selection_scope_filters_limit_and_source_metadata():
    async def scenario():
        c = IdentifierConnection()
        async with PostgresSession(Resource(c)).transaction(request([{'field': 'document_id', 'op': 'eq', 'value': 'document'}]), scope=scope(), deadline=asyncio.get_running_loop().time()+2) as h:
            candidate, = await h.identifier_candidates('ERR_CONN-42', limit=1000)
            assert candidate.identifier_profile == 'identifier_ascii_v1'
            sql, params = next(call for call in c.calls if call[0].startswith(implementation._IDENTIFIER_SQL.split('{predicate}')[0]))
            assert params == ('tenant-a', 'engineering', 'auth-r1', 'auth-r1', 'principal-a', ['read'], 'document', 'ERR_CONN-42', request().limits.max_candidates)
            assert sql.index('identifier_tokens @>') < sql.index('LIMIT')
            assert (await h.fetch_evidence(candidate, max_source_bytes=100)).state == 'verified'
            for changed in ({'score': 2.0}, {'identifier_profile': 'forged'}, {'score_kind': 'confidence'}, {'score_direction': 'lower_is_better'}):
                before = len(c.calls)
                with pytest.raises(InvalidRequest):
                    await h.fetch_evidence(IdentifierCandidate.model_construct(**(candidate.model_dump() | changed)), max_source_bytes=100)
                assert len(c.calls) == before
            c.source = []
            assert (await h.fetch_evidence(candidate, max_source_bytes=100)).state == 'unavailable'
        with pytest.raises(InvalidRequest):
            await h.identifier_candidates('x1')
    asyncio.run(scenario())


@pytest.mark.parametrize('identifier', ['', 'hello', 'HTTP', 'x1 x2', 'x1 ', ' x1', 'x1\0', 'x'+'1'*256, None, True, 42])
def test_invalid_identifiers_never_dispatch(identifier):
    async def scenario():
        c = IdentifierConnection()
        async with PostgresSession(Resource(c)).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time()+2) as h:
            before = len(c.calls)
            with pytest.raises(InvalidRequest):
                await h.identifier_candidates(identifier)
            assert len(c.calls) == before
    asyncio.run(scenario())


@pytest.mark.parametrize('rows,error', [([ROW, ROW], IntegrityViolation), ([ROW[:-1]], IntegrityViolation),
    ([('other', *ROW[1:])], IntegrityViolation), ([(*ROW[:9], 0.0, *ROW[10:])], IntegrityViolation), ([(*ROW[:9], True, *ROW[10:])], IntegrityViolation),
    ([(*ROW[:10], 'wrong', ROW[11])], UnsupportedCapability), ([(*ROW[:6], 4, 4, *ROW[8:])], IntegrityViolation)])
def test_bad_rows_fail_closed(rows, error):
    async def scenario():
        c = IdentifierConnection(); c.identifiers = rows
        async with PostgresSession(Resource(c)).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time()+2) as h:
            with pytest.raises(error):
                await h.identifier_candidates('x1', limit=2)
    asyncio.run(scenario())


@pytest.mark.parametrize('limit', [True, 0, 1001, 1.5])
def test_bad_limit_never_dispatches(limit):
    async def scenario():
        c = IdentifierConnection()
        async with PostgresSession(Resource(c)).transaction(request(), scope=scope(), deadline=asyncio.get_running_loop().time()+2) as h:
            before = len(c.calls)
            with pytest.raises(InvalidRequest):
                await h.identifier_candidates('x1', limit=limit)
            assert len(c.calls) == before
    asyncio.run(scenario())
