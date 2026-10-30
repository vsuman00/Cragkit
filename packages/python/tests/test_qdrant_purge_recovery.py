"""Purge-only settlement boundaries over bounded SQL doubles, not native evidence."""
import asyncio
from functools import wraps
from types import SimpleNamespace
from uuid import NAMESPACE_DNS, uuid5

import pytest

import cragkit._qdrant_recovery as implementation
from cragkit._qdrant_recovery import PostgresQdrantRecovery
from cragkit._qdrant_writer_contract import context
from cragkit.errors import IntegrityViolation, InvalidRequest, ProviderUnavailable, UnsupportedCapability
from test_qdrant_writer import config, ctx


def run_async(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


def settlement_case():
    target = context(ctx())
    settings = SimpleNamespace(**config())
    points = tuple(str(uuid5(NAMESPACE_DNS, name)) for name in ('purge-a', 'purge-b'))
    group = dict(revision_id='revision-1', generation_id='generation-1',
                 manifest_sha256='a' * 64, point_ids=points)
    projection = dict(point_ids=points, generations=(group,))
    physical = dict(instance_id='instance-1', new_epoch=3, credential_generation='current-key')
    headers = [
        ['put-old', 'instance-1', 1, target.owner_token, 1, 'retired-key',
         'complete_point_upsert', False, 'b' * 64, '11', 'unknown', None],
        ['delete-old', 'instance-1', 2, target.owner_token, 2, 'retired-key',
         'delete_points', True, 'c' * 64, '12', 'dispatched', None],
    ]
    members = [(row[0], settings.backend_namespace, settings.physical_collection,
                settings.collection_incarnation, point)
               for row, point in zip(headers, points, strict=True)]
    state = dict(foreign=False, writes=0, statements=[])

    async def query(connection, sql, params=()):
        state['statements'].append(sql)
        if sql.startswith('SELECT action,instance_id,manifest_sha256'):
            return [('stage', 'instance-1', group['manifest_sha256'],
                     group['revision_id'], group['generation_id'])]
        if sql.startswith('SELECT 1 FROM cragkit_qdrant.dispatch_journal'):
            return [(1,)] if state['foreign'] else []
        if sql.startswith('SELECT ' + implementation._SECURITY_JOURNAL_COLUMNS):
            selected = params[-1] if 'dispatch_id=ANY' in sql else None
            return [tuple(row) for row in headers if selected is None or row[0] in selected]
        if sql.startswith('SELECT ' + implementation._SECURITY_MEMBER_COLUMNS):
            selected = params[-1] if 'dispatch_id=ANY' in sql else None
            return [row for row in members if selected is None or row[0] in selected]
        if sql.startswith('UPDATE cragkit_qdrant.dispatch_journal'):
            state['writes'] += 1
            selected = next(row for row in headers if row[0] == params[-1])
            assert selected[10] != 'settled' and selected[11] is None
            selected[10:] = ['settled', params[0]]
            return [(selected[0],)]
        raise AssertionError('Unexpected purge settlement SQL')

    recovery = SimpleNamespace(config=settings, _query=query)
    return recovery, target, physical, projection, headers, members, state


@run_async
async def test_purge_settlement_accepts_retired_put_and_recovery_delete_only():
    recovery, target, physical, projection, headers, members, state = settlement_case()
    result, snapshot = await PostgresQdrantRecovery._settle_purge_rows(
        recovery, object(), target, physical, projection, 'd' * 64)
    assert result == {'settled_count': 2}
    assert all(row[10:] == ['settled', 'd' * 64] for row in headers)
    assert state['writes'] == 2
    state['statements'].clear()
    await PostgresQdrantRecovery._confirm_security_rows(recovery, object(), target, snapshot)
    assert state['writes'] == 2
    assert all(sql.startswith('SELECT ') for sql in state['statements'])


@run_async
async def test_g2_settlement_stays_put_only_when_given_recovery_delete():
    recovery, target, physical, projection, headers, members, state = settlement_case()
    with pytest.raises(UnsupportedCapability):
        await PostgresQdrantRecovery._settle_security_rows(
            recovery, object(), target, physical, projection, 'd' * 64)
    assert state['writes'] == 0


@pytest.mark.parametrize('fault', ['ordinary-delete', 'current-credential', 'foreign', 'unknown-point',
                                   'duplicate-member', 'bad-completion', 'future-epoch'])
@run_async
async def test_purge_settlement_refuses_uncertain_or_unclaimed_work_before_writes(fault):
    recovery, target, physical, projection, headers, members, state = settlement_case()
    expected = IntegrityViolation
    if fault == 'ordinary-delete':
        headers[1][7] = False
        expected = UnsupportedCapability
    elif fault == 'current-credential':
        headers[1][5] = physical['credential_generation']
        expected = ProviderUnavailable
    elif fault == 'foreign':
        state['foreign'] = True
        expected = ProviderUnavailable
    elif fault == 'unknown-point':
        members[1] = (*members[1][:-1], str(uuid5(NAMESPACE_DNS, 'unclaimed')))
    elif fault == 'duplicate-member':
        members.append(members[1])
    elif fault == 'bad-completion':
        headers[1][11] = 'd' * 64
    else:
        headers[1][4] = physical['new_epoch'] + 1
    with pytest.raises(expected):
        await PostgresQdrantRecovery._settle_purge_rows(
            recovery, object(), target, physical, projection, 'd' * 64)
    assert state['writes'] == 0


@pytest.mark.parametrize('fault', ['changed-header', 'changed-member', 'missing-row', 'wrong-completion'])
@run_async
async def test_purge_lost_commit_confirmation_is_exact_and_read_only(fault):
    recovery, target, physical, projection, headers, members, state = settlement_case()
    _, snapshot = await PostgresQdrantRecovery._settle_purge_rows(
        recovery, object(), target, physical, projection, 'd' * 64)
    if fault == 'changed-header':
        headers[1][6] = 'complete_point_upsert'
    elif fault == 'changed-member':
        members[1] = (*members[1][:-1], projection['point_ids'][0])
    elif fault == 'missing-row':
        headers.pop()
    else:
        headers[1][11] = 'e' * 64
    state['statements'].clear()
    with pytest.raises(ProviderUnavailable):
        await PostgresQdrantRecovery._confirm_security_rows(recovery, object(), target, snapshot)
    assert state['writes'] == 2
    assert all(sql.startswith('SELECT ') for sql in state['statements'])


@run_async
async def test_purge_dispatch_authorizations_are_nominal_and_not_g2_tokens():
    deadline = asyncio.get_running_loop().time() + 5
    for value in (object(), {}, implementation._SecurityDispatchAuthorization(),
                  implementation._RecoveryDispatchAuthorization(), implementation._PurgeDispatchAuthorization()):
        with pytest.raises(InvalidRequest):
            implementation.purge_dispatch_authorization(value, object(), deadline=deadline)
    with pytest.raises(TypeError):
        implementation._PurgeDispatchAuthorization().__reduce__()


@run_async
async def test_unregistered_purge_dispatch_and_settlement_never_invoke_callbacks():
    called = False

    async def authorize(*args):
        nonlocal called
        called = True
        return True

    deadline = asyncio.get_running_loop().time() + 5
    with pytest.raises(InvalidRequest):
        await implementation.dispatch_purge_recovery(object(), object(), ctx(), object(), authorize,
                                                      deadline=deadline)
    with pytest.raises(InvalidRequest):
        await implementation.settle_purge_guarded(object(), object(), object(), ctx(), object(),
                                                 deadline=deadline)
    assert not called
