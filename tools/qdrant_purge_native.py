"""Disposable QP-r1 native SQL fixtures; no physical Qdrant absence claim."""
from __future__ import annotations

import asyncio
from hashlib import sha256
import json

from qdrant_publication_native import bind_scope
from qdrant_publication_schema import insert_sql, rejected_sql
from qdrant_security_guard_native import guard_inputs, install_guard, metadata_snapshot, rows
from qdrant_security_guard_schema import guard_statement
from qdrant_security_lock_cases import _writer, _security_change
from qdrant_writer_cases import OWNER_TOKEN


async def seed_documents(database):
    """Commit source and operation history through the accepted native writer."""
    from cragkit._qdrant_writer import prepare_stage, admit_security_owner, security_projection_data
    from cragkit.contracts import parse_scope

    inputs, records = guard_inputs('purge')
    async with database.connection('supervisor') as connection:
        async with connection.transaction():
            await bind_scope(connection, records)
            await connection.execute(insert_sql('backend_instances', records['backend']))
    # Security-owner admission is an existing profile-4 capability. Install its
    # exact catalog before constructing the writer used by these fixture paths.
    await install_guard(database)
    writer, resource = await _writer(database, inputs)
    guards = {}
    deadline = asyncio.get_running_loop().time() + 60
    try:
        for name in ('purge', 'stage-anchor', 'security-anchor', 'same-security'):
            current, seed = guard_inputs(name)
            scope = parse_scope(current['scope'])
            manifest = current['stage']['manifest']
            owner = dict(scope=scope, collection=manifest['collection'], document_id=manifest['document_id'],
                         intent_id=current['stage']['intent']['intent_id'], owner_token=OWNER_TOKEN)
            await writer.stage(prepare_stage(current['stage']), scope, owner_token=OWNER_TOKEN, deadline=deadline)
            await writer.admit_publication(owner, deadline=deadline)
            # A SQL-only synthetic acknowledgment settles a real durable journal;
            # it is not evidence that Qdrant received this fixture's request.
            dispatch = 'qp-synthetic-dispatch-' + name
            await writer.reserve_dispatch(owner, dict(dispatch_id=dispatch, sequence=1,
                credential_generation='qp-synthetic-credential', operation='complete_point_upsert',
                point_ids=[member['point_id'] for member in manifest['members']]), deadline=deadline)
            await writer.mark_dispatched(owner, dispatch, deadline=deadline)
            await writer.settle_dispatch(owner, dispatch, sha256(b'QP SQL fixture acknowledgment').hexdigest(), deadline=deadline)
            change = _security_change(current, 'qp-auth-2-' + name, 'auth-1', 1, 'auth-2')
            if name == 'purge':
                change['action'] = 'tombstone'
                change['authorization']['tombstoned'] = True
            security = await writer.apply_security(change, scope, owner_token=OWNER_TOKEN, deadline=deadline)
            new_scope = parse_scope(dict(current['scope'], authorization_revision='auth-2'))
            security_context = dict(owner, scope=new_scope, intent_id=change['intent_id'])
            if name in ('security-anchor', 'same-security'):
                await admit_security_owner(writer, security_context, deadline=deadline)
                owner = security_context
            if name == 'security-anchor':
                change = _security_change(current, 'qp-auth-3-' + name, 'auth-2', 2, 'auth-3')
                security = await writer.apply_security(change, new_scope, owner_token=OWNER_TOKEN, deadline=deadline)
                new_scope = parse_scope(dict(current['scope'], authorization_revision='auth-3'))
                security_context = dict(owner, scope=new_scope, intent_id=change['intent_id'])
            projection = security_projection_data(
                await writer.project_security(security_context, deadline=deadline), writer)
            if name == 'purge':
                purge = dict(intent_id='qp-purge', tenant_id=manifest['tenant_id'], collection=manifest['collection'],
                    document_id=manifest['document_id'], tombstone_intent_payload_sha256=security['payload_sha256'],
                    expected_authorization_revision='auth-2', expected_mutation_epoch=2)
                bound = await writer.bind_purge(purge, new_scope, owner_token=OWNER_TOKEN, deadline=deadline)
                await writer.acquire_owner(dict(owner, scope=new_scope, intent_id=purge['intent_id']), deadline=deadline)
                physical = [current['config'][key] for key in
                            ('backend_namespace', 'physical_collection', 'collection_incarnation')]
                groups = [[group['revision_id'], group['generation_id'], group['manifest_sha256'], list(group['point_ids'])]
                          for group in projection['generations']]
                inventory = json.dumps(['cragkit.qdrant.security-inventory.v1', *physical,
                    manifest['tenant_id'], manifest['collection'], manifest['document_id'], current['instance_id'], groups],
                    ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                purge_fixture = dict(records=seed, arguments=(current['instance_id'], physical[0], 'storage-fixture',
                    'supervisor-fixture', 1, physical[1], physical[2], manifest['tenant_id'], manifest['collection'],
                    manifest['document_id'], purge['intent_id'], bound['payload_sha256'], OWNER_TOKEN,
                    security['payload_sha256'], 'auth-2', 2, inventory, sha256(inventory).hexdigest(),
                    'erase_managed_source_and_replay_v1', sha256(b'QP synthetic absence, SQL only').hexdigest()))
            else:
                guards[name] = (current['instance_id'], current['config']['backend_namespace'], 'storage-fixture',
                    'supervisor-fixture', 'qp-guard-recovery', 2, manifest['tenant_id'], manifest['collection'],
                    manifest['document_id'], owner['intent_id'], OWNER_TOKEN, change['intent_id'],
                    projection['intent_sha256'], projection['active_generation_id'], projection['authorization_revision'],
                    projection['mutation_epoch'], list(projection['principal_ids']), list(projection['grant_ids']),
                    projection['language'], projection['kind'], projection['tag'], projection['tombstoned'])
    finally:
        await writer.close()
        await resource.close()
    return purge_fixture, guards


async def install(database):
    """Check complete operator DDL rollback before committing its exact checksum."""
    from qdrant_purge_schema import migration

    source = migration()
    baseline = await metadata_snapshot(database.admin)
    async with database.operator_connection() as connection:
        await connection.execute('BEGIN ISOLATION LEVEL READ COMMITTED')
        try:
            await connection.execute(source.sql, prepare=False)
            await connection.execute('INSERT INTO cragkit_qdrant.schema_migrations(version,checksum_sha256) VALUES(%s,%s)',
                                     (source.version, source.checksum))
            if await rows(connection, "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cragkit_qdrant_purger')") != [(True,)]:
                raise RuntimeError('purge_rollback_before_role_creation')
        finally:
            await connection.execute('ROLLBACK')
    if await metadata_snapshot(database.admin) != baseline:
        raise RuntimeError('purge_install_rollback_changed_catalog')
    async with database.operator_connection() as connection:
        async with connection.transaction():
            await connection.execute(source.sql, prepare=False)
            await connection.execute('INSERT INTO cragkit_qdrant.schema_migrations(version,checksum_sha256) VALUES(%s,%s)',
                                     (source.version, source.checksum))
    return source


async def guard_probes(database, guards):
    """Exercise actual three owner branches under one rolled-back recovery state."""
    async with database.connection('supervisor') as connection:
        async with connection.transaction(force_rollback=True):
            first = next(iter(guards.values()))
            await connection.execute("SELECT set_config('cragkit_qdrant.backend_instance_id',%s,true)", (first[0],))
            await connection.execute("UPDATE cragkit_qdrant.backend_instances SET state='recovery_blocked',"
                "epoch=2,recovery_id='qp-guard-recovery' WHERE instance_id=%s", (first[0],))
            for name, args in guards.items():
                await connection.execute('UPDATE cragkit_qdrant.document_owners SET backend_epoch=2 '
                    'WHERE tenant_id=%s AND collection=%s AND document_id=%s', args[6:9])
                await rows(connection, guard_statement(args))
                wrong = list(args); wrong[12] = '0' * 64
                await connection.execute(rejected_sql(guard_statement(wrong) + ';', '23514'), prepare=False)
    return ['stage_owner_guard', 'prior_committed_security_owner_guard', 'same_current_security_owner_guard']
