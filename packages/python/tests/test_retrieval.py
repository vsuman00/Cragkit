import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
import json
from pathlib import Path
import time
import traceback

import pytest
from pydantic import ValidationError

from cragkit._postgres_filters import compile_filters
from cragkit._postgres_session import LexicalCandidate, ScopedSession
from cragkit._postgres_source import SourceFetch, _SOURCE_SQL, verify_source
from cragkit.contracts import parse_request, parse_scope
from cragkit.errors import (ContextBudgetTooSmall, DeadlineExceeded, IntegrityViolation,
                            InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability)
from cragkit.retrieval import PostgresRetriever


FIXTURES = json.loads((Path(__file__).resolve().parents[3] / 'contracts/fixtures/retrieval.json').read_text())
ERRORS = {kind.code: kind for kind in (ContextBudgetTooSmall, DeadlineExceeded, IntegrityViolation,
    InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability)}


class Cursor:
    def __init__(self, rows): self.rows = rows
    async def fetchall(self): return self.rows


class Connection:
    def __init__(self, rows): self.rows = rows; self.calls = []; self.error = None; self.delay = 0
    async def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if 'statement_timeout' in sql: return Cursor([])
        if self.error: raise self.error
        if self.delay: time.sleep(self.delay)
        return Cursor(self.rows)


def handle(connection, request, scope):
    predicate, parameters = compile_filters(request.required_filters)
    return ScopedSession(connection, request, scope, asyncio.get_running_loop().time() + 2, predicate, parameters)


@pytest.mark.parametrize('case', FIXTURES['source_cases'], ids=lambda case: case['id'])
def test_shared_source_fixture(case):
    async def scenario():
        request = parse_request(case['request']); scope = parse_scope(case['scope'])
        candidate = LexicalCandidate.model_validate(case['candidate'])
        connection = Connection([tuple(row) for row in case['rows']])
        scoped = handle(connection, request, scope)
        if 'error' in case:
            with pytest.raises(ERRORS[case['error']]):
                await scoped.fetch_evidence(candidate, max_source_bytes=case['max_source_bytes'])
        else:
            fetched = await scoped.fetch_evidence(candidate, max_source_bytes=case['max_source_bytes'])
            assert fetched.model_dump(mode='json') == case['expected']
    asyncio.run(scenario())


class FakeSession:
    def __init__(self, candidates, sources):
        self.candidates = tuple(LexicalCandidate.model_validate(item) for item in candidates)
        self.sources = {item['candidate_index']: [tuple(row) for row in item['rows']] for item in sources}
        self.transactions = 0; self.fetches = []; self.fail = None
    @asynccontextmanager
    async def transaction(self, request, *, scope, deadline):
        self.transactions += 1
        parent = self
        class Handle:
            async def lexical_candidates(self, *, limit):
                if parent.fail: raise parent.fail
                return parent.candidates[:limit]
            async def fetch_evidence(self, candidate, *, max_source_bytes):
                parent.fetches.append(max_source_bytes)
                index = parent.candidates.index(candidate)
                return verify_source(candidate, parent.sources.get(index, []), max_source_bytes)
        yield Handle()


@pytest.mark.parametrize('case', FIXTURES['result_cases'], ids=lambda case: case['id'])
def test_shared_result_fixture(case):
    async def scenario():
        fake = FakeSession(case['candidates'], case['sources'])
        retriever = PostgresRetriever(None); retriever._session = fake
        request = parse_request(case['request']); scope = parse_scope(case['scope'])
        if 'error' in case:
            with pytest.raises(ERRORS[case['error']]):
                await retriever.retrieve(request, scope=scope, deadline=asyncio.get_running_loop().time() + 2)
        else:
            result = await retriever.retrieve(request, scope=scope, deadline=asyncio.get_running_loop().time() + 2)
            assert result.model_dump(mode='json') == case['expected']
            assert fake.transactions == (2 if fake.candidates else 1)
    asyncio.run(scenario())


def sample():
    text = 'Café 🙂\n'
    digest = sha256(text.encode()).hexdigest()
    candidate = LexicalCandidate(tenant_id='tenant', collection='docs', document_id='doc',
        revision_id='rev', generation_id='gen', chunk_id='chunk', start_byte=0,
        end_byte=len(text.encode()), text_sha256=digest, score=1.0)
    row = ('tenant', 'docs', 'doc', 'rev', 'gen', 'chunk', digest, len(text.encode()), text,
           0, len(text.encode()), len(text.encode()), text, digest, '<opaque:locator>', 'native_fts.v1', True)
    request = parse_request({'request_id': 'request', 'query': 'Café', 'collection': 'docs'})
    scope = parse_scope({'tenant_id': 'tenant', 'principal_id': 'principal', 'authorization_revision': 'auth'})
    return candidate, row, request, scope


def test_fresh_source_transaction_opaque_locator_canonical_digest_and_immutable_result():
    async def scenario():
        candidate, row, request, scope = sample()
        fake = FakeSession([candidate.model_dump(mode='json')], [{'candidate_index': 0, 'rows': [row]}])
        retriever = PostgresRetriever(None); retriever._session = fake
        result = await retriever.retrieve(request, scope=scope, deadline=asyncio.get_running_loop().time() + 2)
        assert fake.transactions == 2 and fake.fetches == [16_777_216]
        assert result.status == 'partial' and result.facets == ()
        assert result.evidence[0].source_sha256 == row[6]
        assert result.evidence[0].source_locator == '<opaque:locator>'
        assert result.context == json.dumps([result.evidence[0].model_dump(mode='json')], ensure_ascii=False, separators=(',', ':'))
        assert result.usage.context_tokens == (len(result.context.encode()) + 3) // 4
        assert result.usage.provider_calls == 0 and result.usage.cost_kind == 'known'
        with pytest.raises(ValidationError): result.evidence[0].text = 'changed'
        assert 'r.source_sha256' not in _SOURCE_SQL
    asyncio.run(scenario())


def test_scope_mismatch_and_bad_budgets_do_not_issue_sql():
    async def scenario():
        candidate, row, request, scope = sample()
        connection = Connection([row]); scoped = handle(connection, request, scope)
        foreign = candidate.model_copy(update={'tenant_id': 'foreign'})
        with pytest.raises(UnauthorizedScope): await scoped.fetch_evidence(foreign, max_source_bytes=100)
        oversized = candidate.model_copy(update={'collection': 'x' * 129})
        with pytest.raises(InvalidRequest): await scoped.fetch_evidence(oversized, max_source_bytes=100)
        for budget in (True, -1, 16_777_217, 1.0, None):
            with pytest.raises(InvalidRequest): await scoped.fetch_evidence(candidate, max_source_bytes=budget)
        assert connection.calls == []
        scoped._active = False
        with pytest.raises(InvalidRequest): await scoped.fetch_evidence(candidate, max_source_bytes=100)
    asyncio.run(scenario())


def test_source_fetch_other_task_is_rejected():
    async def scenario():
        candidate, row, request, scope = sample()
        scoped = handle(Connection([row]), request, scope)
        with pytest.raises(InvalidRequest):
            await asyncio.create_task(scoped.fetch_evidence(candidate, max_source_bytes=100))
    asyncio.run(scenario())


def test_source_query_binds_identity_scope_filters_and_budget():
    async def scenario():
        candidate, row, _, scope = sample()
        request = parse_request({'query': 'x', 'collection': 'docs', 'required_filters': [
            {'op': 'eq', 'field': 'document_id', 'value': "literal' OR TRUE --"}]})
        connection = Connection([row]); scoped = handle(connection, request, scope)
        await scoped.fetch_evidence(candidate, max_source_bytes=100)
        sql, parameters = connection.calls[-1]
        assert parameters[:7] == (100, 'tenant', 'docs', 'doc', 'rev', 'gen', 'chunk')
        assert parameters[7:13] == ('tenant', 'docs', 'auth', 'auth', 'principal', [])
        assert parameters[-1] == "literal' OR TRUE --" and 'OR TRUE' not in sql
        assert 'g.generation_id=d.active_generation_id' not in sql
    asyncio.run(scenario())


def test_mid_scalar_span_duplicate_rows_and_wrong_digest_fail_closed():
    candidate, row, _, _ = sample()
    for rows in ([row, row], [(*row[:13], '0' * 64, *row[14:])],
                 [(*row[:6], '0' * 64, *row[7:])]):
        with pytest.raises(IntegrityViolation): verify_source(candidate, rows, 100)
    text = '🙂'; digest = sha256(text.encode()).hexdigest(); excerpt_hash = sha256(b'?').hexdigest()
    forged = candidate.model_copy(update={'start_byte': 1, 'end_byte': 2, 'text_sha256': excerpt_hash})
    forged_row = (*row[:6], digest, 4, text, 1, 2, 1, '?', excerpt_hash, *row[14:])
    with pytest.raises(IntegrityViolation): verify_source(forged, [forged_row], 100)


def test_missing_source_and_unloaded_budget_have_distinct_states():
    candidate, row, _, _ = sample()
    assert verify_source(candidate, [], 0).state == 'unavailable'
    unloaded = (*row[:8], None, *row[9:])
    result = verify_source(candidate, [unloaded], 0)
    assert result.model_dump(mode='json') == {'state': 'budget_exhausted', 'evidence': None, 'source_bytes': 0, 'stale': False}
    with pytest.raises(IntegrityViolation): verify_source(candidate, [row], 0)
    oversized = (*row[:7], 16_777_217, None, *row[9:])
    with pytest.raises(IntegrityViolation): verify_source(candidate, [oversized], 0)


def test_unsupported_output_profiles_and_empty_context_capacity_are_prelease():
    async def scenario():
        _, _, request, scope = sample()
        for output, error in (({'renderer': 'other'}, UnsupportedCapability),
                              ({'tokenizer': 'named'}, UnsupportedCapability),
                              ({'counting_mode': 'strict', 'tokenizer': 'named'}, UnsupportedCapability),
                              ({'envelope_reserve_tokens': 2000}, ContextBudgetTooSmall)):
            changed = parse_request({**request.model_dump(mode='json'), 'output_profile': output})
            retriever = PostgresRetriever(None)
            with pytest.raises(error):
                await retriever.retrieve(changed, scope=scope, deadline=asyncio.get_running_loop().time() + 2)
    asyncio.run(scenario())


def test_operational_errors_are_not_converted_to_missing_evidence():
    async def scenario():
        _, _, request, scope = sample()
        fake = FakeSession([], []); fake.fail = ProviderUnavailable()
        retriever = PostgresRetriever(None); retriever._session = fake
        with pytest.raises(ProviderUnavailable):
            await retriever.retrieve(request, scope=scope, deadline=asyncio.get_running_loop().time() + 2)
    asyncio.run(scenario())


def test_late_driver_return_rechecks_deadline_without_leaking_source():
    async def scenario():
        candidate, row, request, scope = sample()
        connection = Connection([row]); connection.delay = 0.02
        scoped = handle(connection, request, scope); scoped._deadline = asyncio.get_running_loop().time() + 0.005
        with pytest.raises(DeadlineExceeded): await scoped.fetch_evidence(candidate, max_source_bytes=100)
        connection.error = RuntimeError('private-canonical-source'); connection.delay = 0
        scoped._deadline = asyncio.get_running_loop().time() + 1
        with pytest.raises(ProviderUnavailable) as caught: await scoped.fetch_evidence(candidate, max_source_bytes=100)
        assert 'private-canonical-source' not in ''.join(traceback.format_exception(caught.value))
    asyncio.run(scenario())


def test_retrieval_import_requires_no_optional_driver_or_network_or_writes():
    import subprocess
    import sys
    script = """
import sys
class Deny:
 def find_spec(self, name, *args):
  if name in ('psycopg', 'psycopg_pool'): raise AssertionError('optional driver imported')
sys.meta_path.insert(0,Deny())
def audit(event,args):
 if event.startswith(('socket.','subprocess.')): raise AssertionError('network or process')
 if event=='open' and isinstance(args[1],str) and any(flag in args[1] for flag in 'wax+'): raise AssertionError('write')
sys.addaudithook(audit)
import cragkit.retrieval
"""
    process = subprocess.run([sys.executable,'-B','-c',script],capture_output=True,text=True,timeout=5)
    assert process.returncode == 0, process.stderr
    assert process.stdout == ''


def test_request_deadline_starts_before_request_snapshot(monkeypatch):
    import cragkit.retrieval as implementation
    async def scenario():
        candidate, row, request, scope = sample()
        request = parse_request({**request.model_dump(mode='json'), 'limits': {'deadline_ms': 1}})
        original_parse = implementation.parse_request
        def slow_parse(value):
            time.sleep(0.02)
            return original_parse(value)
        monkeypatch.setattr(implementation, 'parse_request', slow_parse)
        fake = FakeSession([], [])
        retriever = PostgresRetriever(None)
        retriever._session = fake
        with pytest.raises(DeadlineExceeded):
            await retriever.retrieve(request, scope=scope, deadline=asyncio.get_running_loop().time()+1)
        assert fake.transactions == 0
    asyncio.run(scenario())
