/** Explicit read-only native result acceptance; no admin access or schema changes. */
import assert from 'node:assert/strict';
import { createInterface } from 'node:readline';
import { lstatSync, readFileSync } from 'node:fs';
import { PoolResource, parse_pool_config, now } from '../packages/typescript/dist/postgres-pool.js';
import { PostgresSession } from '../packages/typescript/dist/postgres-session.js';
import { PostgresRetriever } from '../packages/typescript/dist/retrieval.js';
import { parse_request, parse_scope } from '../packages/typescript/dist/contracts.js';
import { CragkitError, IntegrityViolation } from '../packages/typescript/dist/errors.js';

class CheckError extends Error {}
function requireCheck(condition, code) {
  if (!condition) throw new CheckError(code);
}
function privateJSON(path) {
  const info = lstatSync(path);
  requireCheck(info.isFile() && info.uid === process.getuid() && (info.mode & 0o077) === 0, 'source_private_file');
  return JSON.parse(readFileSync(path, 'utf8'));
}
async function run(config, fixture) {
  const resource = new PoolResource(parse_pool_config(config));
  const retriever = new PostgresRetriever(resource);
  try {
    await resource.open();
    if (fixture.mode === 'revocation') {
      const original = PostgresSession.prototype.transaction;
      let transactions = 0;
      PostgresSession.prototype.transaction = async function (...args) {
        transactions += 1;
        if (transactions === 2) {
          const input = createInterface({ input: process.stdin });
          const continued = new Promise(resolve => input.once('line', resolve));
          process.stdout.write(JSON.stringify({ state: 'boundary' }) + '\n');
          requireCheck(await continued === 'continue', 'source_node_boundary_ack');
          input.close();
        }
        return original.apply(this, args);
      };
      try {
        const result = await retriever.retrieve(parse_request(fixture.request), {
          scope: parse_scope(fixture.scope), deadline: now() + 20,
        });
        assert.deepEqual(result.evidence.map(item => item.document_id), ['tie-document']);
        requireCheck(result.limitations.some(item => item.code === 'stale_evidence'), 'source_node_revocation');
        // A subsequent call uses the same resource, with no cached candidates.
        const again = await retriever.retrieve(parse_request(fixture.request), {
          scope: parse_scope(fixture.scope), deadline: now() + 20,
        });
        assert.deepEqual(again.evidence.map(item => item.document_id), ['tie-document']);
      } finally { PostgresSession.prototype.transaction = original; }
    } else if (fixture.mode === 'corrupt') {
      let rejected = false;
      try {
        await retriever.retrieve(parse_request(fixture.request), {
          scope: parse_scope(fixture.scope), deadline: now() + 20,
        });
      } catch (error) { rejected = error instanceof IntegrityViolation; }
      requireCheck(rejected, 'source_node_corruption_accepted');
    } else {
      requireCheck(fixture.mode === 'baseline', 'source_node_mode');
      const source = await new PostgresSession(resource).transaction(parse_request(fixture.source_request), {
        scope: parse_scope(fixture.source_scope), deadline: now() + 20,
      }, handle => handle.fetch_evidence(fixture.source_candidate, { max_source_bytes: 16777216 }));
      requireCheck(source.state === 'unavailable' && source.evidence === null && source.source_bytes === 0,
        'source_node_direct_denial_failed');
      for (const item of fixture.cases) {
        const result = await retriever.retrieve(parse_request(item.request), {
          scope: parse_scope(item.scope), deadline: now() + 20,
        });
        assert.deepEqual(result, item.expected);
        requireCheck(Object.isFrozen(result) && Object.isFrozen(result.evidence), 'source_node_mutable_result');
      }
    }
  } finally { await resource.close(); }
}
try {
  const args = process.argv.slice(2);
  requireCheck(args.length === 3 && args[0] === '--allow-result-checks', 'source_explicit_authorization');
  await run(privateJSON(args[1]), privateJSON(args[2]));
  process.stdout.write(JSON.stringify({ state: 'passed' }) + '\n');
} catch (error) {
  const code = error instanceof CheckError ? error.message
    : error instanceof CragkitError ? 'source_node_' + error.code : 'source_node_failed';
  process.stdout.write(JSON.stringify({ state: 'failed', code }) + '\n');
  process.exitCode = 1;
}
