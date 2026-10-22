/** Explicit child of the Python-owned empty-target fixture; performs no database DDL. */
import { readFileSync, lstatSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { parse_pool_config, PoolResource, now } from '../packages/typescript/dist/postgres-pool.js';
import { PostgresRetriever } from '../packages/typescript/dist/retrieval.js';
import { PostgresSession } from '../packages/typescript/dist/postgres-session.js';
import { parse_request, parse_scope } from '../packages/typescript/dist/contracts.js';
import { DeadlineExceeded, UnauthorizedScope, UnsupportedCapability } from '../packages/typescript/dist/errors.js';

class CheckError extends Error {}
function requireCheck(condition, code) { if (!condition) throw new CheckError(code); }
export function requireNeonTLS(client, host) {
  requireCheck(typeof host === 'string'
    && /^ep-[a-z0-9]+(?:-[a-z0-9]+)*\.c-[0-9]+\.[a-z0-9-]+\.aws\.neon\.tech$/.test(host)
    && !host.includes('-pooler.'), 'direct_neon_host_required');
  const stream = client?.connection?.stream;
  requireCheck(stream?.encrypted === true && stream?.authorized === true
    && client?.ssl?.rejectUnauthorized === true && client?.ssl?.servername === host,
  'native_client_tls_required');
}
export function verifyNeonResource(resource, host) {
  // Test tooling instruments the existing owned factory before guarded leases
  // hide the raw driver socket. No raw socket is added to the library interface.
  const factory = resource.factory;
  requireCheck(typeof factory === 'function', 'native_factory_unavailable');
  resource.factory = async config => {
    const pool = await factory(config);
    const connect = pool.connect.bind(pool);
    pool.connect = async () => {
      const client = await connect();
      try { requireNeonTLS(client, host); }
      catch (error) { client.release(true); throw error; }
      return client;
    };
    return pool;
  };
}
function privateJSON(path) {
  const info = lstatSync(path);
  requireCheck(info.isFile() && info.uid === process.getuid() && (info.mode & 0o077) === 0, 'private_file_permissions');
  return JSON.parse(readFileSync(path, 'utf8'));
}
function send(type, fields = {}) { process.stdout.write(JSON.stringify({ type, ...fields }) + '\n'); }
function control() {
  const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
  const queued = [];
  const waiters = [];
  let ended = false;
  lines.on('line', line => {
    let value;
    try { value = JSON.parse(line); } catch { value = { type: 'invalid' }; }
    if (waiters.length) waiters.shift()(value); else queued.push(value);
  });
  lines.on('close', () => { ended = true; while (waiters.length) waiters.shift()({ type: 'closed' }); });
  return {
    async expect(type) {
      const message = queued.length ? queued.shift() : ended ? { type: 'closed' } : await new Promise((resolveMessage, reject) => {
        const timer = setTimeout(() => reject(new CheckError('parent_ack_timeout')), 12000);
        waiters.push(value => { clearTimeout(timer); resolveMessage(value); });
      });
      requireCheck(message?.type === type, 'parent_protocol');
    },
    close() { lines.close(); },
  };
}

export async function run(runtimeInput, fixture, channel) {
  requireCheck(fixture.neon === undefined || typeof fixture.neon === 'boolean', 'fixture_transport_mode');
  requireCheck(Array.isArray(fixture.scopes) && fixture.scopes.length === 2
    && Array.isArray(fixture.expected_documents) && fixture.expected_documents.length === 2, 'fixture_shape');
  const config = parse_pool_config({ ...runtimeInput, max_size: 1 });
  const scopes = fixture.scopes.map(parse_scope);
  const request = parse_request({ query: 'synthetic scope check', collection: fixture.collection });
  const resource = new PoolResource(config);
  if (fixture.neon) verifyNeonResource(resource, config.host);
  const checks = [];
  let adminResource;
  let physicalPID;
  async function raw(callback) {
    return resource.withLease({ deadline: now() + 8 }, async client => {
      requireCheck(client.getTransactionStatus() === 'I', 'raw_connection_not_idle');
      await client.query({ text: 'BEGIN READ ONLY', rowMode: 'array' });
      try { return await callback(client); }
      finally { await client.query({ text: 'ROLLBACK', rowMode: 'array' }); requireCheck(client.getTransactionStatus() === 'I', 'raw_rollback_not_idle'); }
    });
  }
  async function reset(requireSamePID = false) {
    await raw(async client => {
      const result = await client.query({ text: "SELECT pg_backend_pid(),current_setting('cragkit.tenant_id',true),current_setting('cragkit.principal_id',true),current_setting('cragkit.authorization_revision',true),current_setting('cragkit.grant_ids',true)", rowMode: 'array' });
      requireCheck(result.rows.length === 1 && result.rows[0].slice(1).every(value => value === null || value === ''), 'scope_reset');
      if (requireSamePID) requireCheck(result.rows[0][0] === physicalPID, 'physical_reuse');
    });
  }
  try {
    await resource.open();
    const session = new PostgresSession(resource);
    await session.validate({ deadline: now() + 8 });
    await raw(async client => {
      const identity = await client.query({ text: fixture.neon
        ? 'SELECT current_user=session_user,current_user=$1,pg_backend_pid()'
        : 'SELECT current_user=session_user,current_user=$1,ssl,pg_backend_pid() FROM pg_stat_ssl WHERE pid=pg_backend_pid()', values: [config.user], rowMode: 'array' });
      requireCheck(identity.rows.length === 1
        && identity.rows[0].slice(0, fixture.neon ? 2 : 3).every(value => value === true), 'runtime_login_tls');
      physicalPID = identity.rows[0].at(-1);
      const unscoped = await client.query({ text: 'SELECT count(*)::int FROM cragkit.documents', rowMode: 'array' });
      requireCheck(unscoped.rows[0][0] === 0, 'unscoped_rls');
    });
    checks.push('actual_runtime_login_tls_rls');
    for (const index of [0, 1, 0]) {
      await session.transaction(request, { scope: scopes[index], deadline: now() + 8 }, async handle => {
        requireCheck(JSON.stringify(await handle.visible_documents()) === JSON.stringify([fixture.expected_documents[index]]), 'scope_visibility');
      });
      await reset(true);
    }
    const scopeValue = scopes[0];
    for (const [changed, expected] of [
      [{ principal_id: 'not-granted', grant_ids: [] }, []],
      [{ principal_id: 'not-granted', grant_ids: ['trusted-grant'] }, [fixture.expected_documents[0]]],
      [{ authorization_revision: 'stale' }, []],
    ]) {
      const trusted = parse_scope({ ...scopeValue, ...changed });
      await session.transaction(request, { scope: trusted, deadline: now() + 8 }, async handle => {
        requireCheck(JSON.stringify(await handle.visible_documents()) === JSON.stringify(expected), 'principal_grant_revision');
      });
    }
    const filtered = parse_request({ query: 'synthetic', collection: fixture.collection,
      required_filters: [{ op: 'eq', field: 'document_id', value: "literal' OR TRUE --" }] });
    await session.transaction(filtered, { scope: scopes[0], deadline: now() + 8 }, async handle => {
      requireCheck((await handle.visible_documents()).length === 0, 'parameterized_filter');
    });
    const sentinel = new Error('synthetic caller sentinel');
    try { await session.transaction(request, { scope: scopes[0], deadline: now() + 8 }, async () => { throw sentinel; }); }
    catch (error) { requireCheck(error === sentinel, 'body_error_identity'); }
    await reset(true);
    checks.push('scope_filter_rollback_same_connection');

    // Reuse the actual driver pool as a caller-owned dependency of another wrapper.
    // The outer resource remains its owner; no extra connection is opened.
    const borrowed = new PoolResource(config, { pool: resource.pool });
    await borrowed.withLease({ deadline: now() + 8 }, async client => {
      const value = await client.query({ text: 'SELECT 42', rowMode: 'array' });
      requireCheck(value.rows[0][0] === 42, 'borrowed_pool_query');
    });
    await borrowed.close();
    await borrowed.close();
    await reset(true);
    checks.push('borrowed_pool_stays_usable');

    const retriever = new PostgresRetriever(resource);
    async function reuseRetriever() {
      for (const scope of [scopes[1], scopes[0]]) {
        const result = await retriever.retrieve(request, { scope, deadline: now() + 8 });
        requireCheck(result.status === 'insufficient' && result.evidence.length === 0, 'retriever_fresh_scope_reuse');
      }
      await reset(false);
    }
    // Abort while admission is queued, without opening a second runtime connection.
    let releaseHolder;
    let entered;
    const entry = new Promise(resolveEntry => { entered = resolveEntry; });
    const holder = resource.withLease({ deadline: now() + 8 }, async () => {
      entered();
      await new Promise(resolveRelease => { releaseHolder = resolveRelease; });
    });
    await entry;
    const controller = new AbortController();
    const queued = retriever.retrieve(request, { scope: scopes[0], deadline: now() + 8, signal: controller.signal });
    controller.abort('private reason must never escape');
    try { await queued; throw new CheckError('wait_abort_accepted'); }
    catch (error) { requireCheck(error?.name === 'AbortError' && !String(error).includes('private reason'), 'wait_abort_kind'); }
    finally { releaseHolder(); await holder; }
    await reset(false);
    await reuseRetriever();
    checks.push('retriever_abort_queued_acquisition_and_fresh_scope_reuse');

    for (const mode of ['deadline', 'abort']) {
      const abort = new AbortController();
      send('lock_request', { mode });
      await channel.expect('locked');
      const query = retriever.retrieve(request, {
        scope: scopes[0], deadline: now() + 5, signal: abort.signal,
      }).then(value => ({ value }), error => ({ error }));
      send('query_started');
      if (mode === 'abort') { await channel.expect('abort'); abort.abort('private abort detail'); }
      else await channel.expect('observed');
      const outcome = await query;
      requireCheck('error' in outcome, 'blocked_query_completed');
      requireCheck(mode === 'abort' ? outcome.error?.name === 'AbortError' : outcome.error instanceof DeadlineExceeded, 'blocked_query_error');
      send('lock_done');
      await channel.expect('unlocked');
      await reuseRetriever();
    }
    checks.push('retriever_observed_query_deadline_abort_and_fresh_scope_reuse');
    send('schema_hide');
    await channel.expect('schema_hidden');
    try {
      let rejected = false;
      try { await session.validate({ deadline: now() + 8 }); }
      catch (error) { rejected = error instanceof UnsupportedCapability; }
      requireCheck(rejected, 'incompatible_schema_accepted');
    } finally {
      send('schema_restore');
      await channel.expect('schema_restored');
    }
    await session.validate({ deadline: now() + 8 });
    checks.push('schema_rejection_restoration');
    await resource.close();
    adminResource = new PoolResource(parse_pool_config({ ...privateJSON(fixture.admin_config), max_size: 1 }));
    await adminResource.open();
    let rejected = false;
    try { await new PostgresSession(adminResource).validate({ deadline: now() + 8 }); }
    catch (error) { rejected = error instanceof UnauthorizedScope; }
    requireCheck(rejected, 'unsafe_admin_accepted');
    await adminResource.close();
    checks.push('unsafe_admin_rejected');
    return { type: 'result', state: 'passed', checks, runtime_login: true, runtime_connections: 1 };
  } finally {
    // Both pools close before the Python owner removes policies, fixture rows and role.
    if (adminResource) await adminResource.close();
    await resource.close();
  }
}

export async function main(argv = process.argv.slice(2)) {
  if (!argv.includes('--allow-runtime-checks')) {
    send('result', { state: 'refused', code: 'explicit_runtime_authorization_required' });
    return 2;
  }
  const value = name => { const index = argv.indexOf(name); return index >= 0 ? argv[index + 1] : undefined; };
  let channel;
  try {
    const configPath = value('--config'); const fixturePath = value('--fixture');
    requireCheck(typeof configPath === 'string' && typeof fixturePath === 'string', 'arguments');
    const config = privateJSON(configPath); const fixture = privateJSON(fixturePath);
    channel = control();
    const result = await run(config, fixture, channel);
    process.stdout.write(JSON.stringify(result) + '\n');
    return 0;
  } catch (error) {
    const kinds = {IntegrityViolation:'integrity_violation',DeadlineExceeded:'deadline_exceeded',UnauthorizedScope:'unauthorized_scope',UnsupportedCapability:'unsupported_capability'};
    const code = error instanceof CheckError && /^[a-z_]+$/.test(error.message) ? error.message : (kinds[error?.constructor?.name] ?? 'runtime_check_failed');
    send('error', { code });
    return 1;
  } finally { channel?.close(); }
}
if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) process.exitCode = await main();
