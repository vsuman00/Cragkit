import asyncio

import pytest

from cragkit._postgres_session import ScopedSession
from cragkit.contracts import parse_request, parse_scope
from cragkit.errors import InvalidRequest, ProviderUnavailable


class Connection:
    def __init__(self): self.calls = []; self.failed = False
    async def execute(self, sql, params=None):
        self.calls.append(sql)
        if sql.startswith('ROLLBACK'): self.failed = False
        elif self.failed: raise RuntimeError('aborted')


def test_failed_branch_rolls_back_and_later_branch_reuses_handle():
    async def scenario():
        connection = Connection()
        handle = ScopedSession(connection, parse_request({'query':'x','collection':'docs'}),
            parse_scope({'tenant_id':'t','principal_id':'p','authorization_revision':'a'}),
            asyncio.get_running_loop().time()+2, 'TRUE', ())
        async def fail():
            connection.failed = True
            raise ProviderUnavailable()
        with pytest.raises(ProviderUnavailable): await handle.candidate_branch(fail)
        async def success(): return 'same-handle'
        assert await handle.candidate_branch(success) == 'same-handle'
        assert connection.calls == ['SAVEPOINT cragkit_candidate_branch', 'ROLLBACK TO SAVEPOINT cragkit_candidate_branch',
            'RELEASE SAVEPOINT cragkit_candidate_branch', 'SAVEPOINT cragkit_candidate_branch', 'RELEASE SAVEPOINT cragkit_candidate_branch']
    asyncio.run(scenario())


def test_nested_task_expired_and_cancellation_guards():
    async def scenario():
        connection = Connection()
        handle = ScopedSession(connection, parse_request({'query':'x','collection':'docs'}),
            parse_scope({'tenant_id':'t','principal_id':'p','authorization_revision':'a'}),
            asyncio.get_running_loop().time()+2, 'TRUE', ())
        async def success(): return 1
        async def nested(): return await handle.candidate_branch(success)
        with pytest.raises(InvalidRequest): await handle.candidate_branch(nested)
        with pytest.raises(InvalidRequest): await asyncio.create_task(handle.candidate_branch(success))
        async def cancel(): raise asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError): await handle.candidate_branch(cancel)
        assert connection.calls[-2:] == ['ROLLBACK TO SAVEPOINT cragkit_candidate_branch', 'RELEASE SAVEPOINT cragkit_candidate_branch']
        handle._active = False
        with pytest.raises(InvalidRequest): await handle.candidate_branch(success)
    asyncio.run(scenario())


@pytest.mark.parametrize('control', ['SAVEPOINT', 'RELEASE', 'ROLLBACK TO'])
def test_control_failure_invalidates_handle_and_is_never_recoverable(control):
    async def scenario():
        class Broken(Connection):
            async def execute(self, sql, params=None):
                if sql.startswith(control): raise RuntimeError('synthetic control failure')
                return await super().execute(sql, params)
        connection = Broken()
        handle = ScopedSession(connection, parse_request({'query':'x','collection':'docs'}),
            parse_scope({'tenant_id':'t','principal_id':'p','authorization_revision':'a'}),
            asyncio.get_running_loop().time()+2, 'TRUE', ())
        async def operation():
            if control == 'ROLLBACK TO': raise ProviderUnavailable()
            return 1
        with pytest.raises(ProviderUnavailable): await handle.candidate_branch(operation)
        assert handle._branch_broken and not handle._active
        with pytest.raises(InvalidRequest): await handle.candidate_branch(operation)
    asyncio.run(scenario())
