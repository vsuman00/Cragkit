/** Explicit isolated native lifecycle probe. Never receives an admin credential. */
import assert from 'node:assert/strict';
import { lstatSync, readFileSync } from 'node:fs';
import { PoolResource, parse_pool_config, now } from '../packages/typescript/dist/postgres-pool.js';
import { PostgresIndexer } from '../packages/typescript/dist/ingestion.js';
import { PostgresLifecycle, _MARKER_SQL } from '../packages/typescript/dist/lifecycle.js';
import { PostgresSession, _SCOPE_SQL } from '../packages/typescript/dist/postgres-session.js';
import { PostgresRetriever } from '../packages/typescript/dist/retrieval.js';
import { parse_request, parse_scope } from '../packages/typescript/dist/contracts.js';
import { CragkitError, IndexNotReady, UnauthorizedScope } from '../packages/typescript/dist/errors.js';

class CheckError extends Error {}
function requireCheck(value, code) { if (!value) throw new CheckError(code); }
function privateJSON(path) {
  const info = lstatSync(path);
  requireCheck(info.isFile() && info.uid === process.getuid() && (info.mode & 0o077) === 0, 'lifecycle_private_file');
  return JSON.parse(readFileSync(path, 'utf8'));
}
async function rejects(operation, kind, code) {
  let denied = false;
  try { await operation(); } catch (error) { denied = error instanceof kind; }
  requireCheck(denied, code);
}
async function run(config, fixture) {
  const resource = new PoolResource(parse_pool_config(config));
  const scope = parse_scope(fixture.scope);
  const common = { collection: fixture.collection, document_id: fixture.document_id, scope };
  const options = () => ({ ...common, deadline: now() + 25 });
  const lifecycle = new PostgresLifecycle(resource, async () => true);
  try {
    await resource.open();
    if (fixture.mode === 'write') {
      const allow = async () => true;
      const indexer = new PostgresIndexer(resource, allow);
      const ingest = (source, changes = {}, writer = indexer) => writer.ingest(source, {
        ...options(), intent_id: fixture.document_id + ':initial', source_locator: 'synthetic:lifecycle', ...changes,
      });
      const first = await ingest('Lifecycle old café🙂');
      let ready;
      let release;
      const prepared = new Promise(resolve => { ready = resolve; });
      const gate = new Promise(resolve => { release = resolve; });
      const slowWriter = new PostgresIndexer(resource, async () => { ready(); await gate; return true; });
      const slow = ingest('Lifecycle slow loser', { intent_id: fixture.document_id + ':slow', expected_generation_id: first.generation_id }, slowWriter)
        .then(() => false, error => error instanceof IndexNotReady);
      await prepared;
      let winner;
      try {
        winner = await ingest('Lifecycle fast winner', { intent_id: fixture.document_id + ':fast', expected_generation_id: first.generation_id });
      } finally { release(); }
      requireCheck(await slow, 'lifecycle_node_stale_update_overwrote');
      await rejects(() => ingest('Lifecycle crash unpublished', {
        intent_id: fixture.document_id + ':crash', expected_generation_id: winner.generation_id,
        before_publish: async () => { throw new CheckError('synthetic_crash'); },
      }), CheckError, 'lifecycle_node_crash_published');
      return { first, winner };
    }
    if (fixture.mode === 'resurrection') {
      const indexer = new PostgresIndexer(resource, async () => true);
      await rejects(() => indexer.ingest('Lifecycle old café🙂', {
        ...options(), intent_id: fixture.document_id + ':initial', source_locator: 'synthetic:lifecycle',
      }), UnauthorizedScope, 'lifecycle_node_resurrection');
      return {};
    }
    if (fixture.mode === 'read') {
      const request = parse_request({ collection: fixture.collection, query: 'Lifecycle',
        required_filters: [{ op: 'eq', field: 'document_id', value: fixture.document_id }] });
      const result = await new PostgresRetriever(resource).retrieve(request, options());
      requireCheck(result.status === (fixture.visible ? 'partial' : 'insufficient'), 'lifecycle_node_visibility');
      if (fixture.visible) {
        requireCheck(result.evidence.length === 1 && result.evidence[0].generation_id === undefined
          && result.evidence[0].revision_id === fixture.winner.revision_id, 'lifecycle_node_active_revision');
      } else requireCheck(result.evidence.length === 0, 'lifecycle_node_deleted_evidence');
      const source = await new PostgresSession(resource).transaction(request, options(),
        handle => handle.fetch_evidence(fixture.candidate, { max_source_bytes: 16777216 }));
      requireCheck(source.state === (fixture.visible ? 'verified' : 'unavailable'), 'lifecycle_node_historical_state');
      if (fixture.visible) requireCheck(source.stale && source.evidence.text === 'Lifecycle old café🙂', 'lifecycle_node_revision_mixed');
      return {};
    }
    const expected_generation_id = fixture.expected_generation_id;
    const input = { ...options(), expected_generation_id };
    if (fixture.mode === 'tombstone') {
      await rejects(() => new PostgresLifecycle(resource, async () => false).tombstone(input),
        UnauthorizedScope, 'lifecycle_node_callback_denial');
      await rejects(() => lifecycle.tombstone({ ...input, expected_generation_id: 'stale' }),
        IndexNotReady, 'lifecycle_node_stale_tombstone');
      const receipt = await lifecycle.tombstone(input);
      assert.deepEqual(await lifecycle.tombstone(input), { ...receipt, changed: false });
      assert.deepEqual(receipt, fixture.expected);
      return { receipt };
    }
    if (fixture.mode === 'purge_denied') {
      let sawMarker = false;
      const observed = {
        withLease: (leaseOptions, body) => resource.withLease(leaseOptions, (client, signal) => {
          const connection = new Proxy(client, {
            get(target, key) {
              if (key === 'query') return config => {
                if (config.text === _MARKER_SQL) sawMarker = true;
                return target.query(config);
              };
              return Reflect.get(target, key, target);
            },
          });
          return body(connection, signal);
        }),
        config: resource.config,
      };
      await rejects(() => new PostgresLifecycle(observed, async () => true).purge_tombstoned(input),
        UnauthorizedScope, 'lifecycle_node_failed_purge_committed');
      requireCheck(sawMarker, 'lifecycle_node_reinsertion_not_reached');
      return {};
    }
    requireCheck(fixture.mode === 'purge', 'lifecycle_node_mode');
    await resource.withLease({ deadline: now() + 10 }, async client => {
      await client.query({ text: 'BEGIN', rowMode: 'array' });
      try {
        await client.query({ text: _SCOPE_SQL, values: [scope.tenant_id, scope.principal_id, scope.authorization_revision, JSON.stringify(scope.grant_ids)], rowMode: 'array' });
        const hidden = await client.query({ text: 'SELECT count(*)::int FROM cragkit.document_revisions WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3',
          values: [scope.tenant_id, fixture.collection, fixture.document_id], rowMode: 'array' });
        assert.deepEqual(hidden.rows, [[0]]);
      } finally { await client.query({ text: 'ROLLBACK', rowMode: 'array' }); }
    });
    const receipt = await lifecycle.purge_tombstoned(input);
    assert.deepEqual(receipt, fixture.expected);
    assert.deepEqual(await lifecycle.purge_tombstoned({ ...input, expected_generation_id: null }), receipt);
    return { receipt };
  } finally { await resource.close(); }
}
try {
  const args = process.argv.slice(2);
  requireCheck(args.length === 3 && args[0] === '--allow-lifecycle-checks', 'lifecycle_explicit_authorization');
  const result = await run(privateJSON(args[1]), privateJSON(args[2]));
  process.stdout.write(JSON.stringify({ state: 'passed', ...result }) + '\n');
} catch (error) {
  const code = error instanceof CheckError ? error.message
    : error instanceof CragkitError ? 'lifecycle_node_' + error.code : 'lifecycle_node_failed';
  process.stdout.write(JSON.stringify({ state: 'failed', code }) + '\n');
  process.exitCode = 1;
}
