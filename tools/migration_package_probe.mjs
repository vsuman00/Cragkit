/** MRR-r1 retained native npm consumer. No provider sender or migration operation. */
import { pathToFileURL } from 'node:url';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';

function requireCondition(condition) {
  if (!condition) throw new Error('migration_package_probe_invalid');
}

function verifyInstalledFiles(sdkRoot, expected, expectedVersion) {
  const manifest = JSON.parse(fs.readFileSync(path.join(sdkRoot, 'package.json')));
  requireCondition(['0.0.0', '1.0.0-rc.1'].includes(expectedVersion)
    && manifest.version === expectedVersion);
  const observed = {};
  let entries = 0;
  function walk(directory, relative = '') {
    for (const item of fs.readdirSync(directory, { withFileTypes: true })) {
      requireCondition(++entries <= 2000);
      const name = relative + item.name;
      const file = path.join(directory, item.name);
      if (item.isDirectory()) walk(file, name + '/');
      else {
        requireCondition(item.isFile() && fs.statSync(file).size <= 2 * 1024 * 1024);
        observed[name] = createHash('sha256').update(fs.readFileSync(file)).digest('hex');
      }
    }
  }
  walk(path.join(sdkRoot, 'dist'));
  requireCondition(JSON.stringify(Object.entries(observed).sort())
    === JSON.stringify(Object.entries(expected).sort()));
  return manifest.version;
}

async function probe(value, sdkRoot) {
  const version = verifyInstalledFiles(sdkRoot, value.files, value.expected_version);
  const load = name => import(pathToFileURL(path.join(sdkRoot, 'dist', name + '.js')));
  const { PoolResource, parse_pool_config, now } = await load('postgres-pool');
  const { parse_request, parse_scope } = await load('contracts');
  const { EmbeddingAdapter, FAKE_PROFILE } = await load('embeddings');
  const { PostgresRetriever } = await load('retrieval');
  const { PostgresSession } = await load('postgres-session');
  const fake = new EmbeddingAdapter(async body => {
    const request = JSON.parse(new TextDecoder().decode(body));
    const tokens = request.input.reduce((sum, text) => sum + Buffer.byteLength(text), 0);
    return Buffer.from(JSON.stringify({
      model: FAKE_PROFILE.model,
      data: request.input.map((_, index) => ({ index, embedding: [1, ...Array(1535).fill(0)] })),
      usage: { prompt_tokens: tokens, total_tokens: tokens },
    }));
  }, { name: 'fake-byte-v1', count: text => Buffer.byteLength(text) });
  const resource = new PoolResource(parse_pool_config(value.reader_config));
  const outcomes = {};
  const cases = [
    ['lexical', 'lexical', 'lexical-document', 'Migration recovery'],
    ['identifier', 'lexical', 'identifier-document', 'ERR_RECOVERY_42'],
    ['dense', 'dense', 'vector-document', 'Migration recovery'],
  ];
  await resource.open();
  try {
    for (const [probeName, mode, document, query] of cases) {
      const expected = value.expected_sources[document];
      try {
        const request = parse_request({
          query, collection: value.collection,
          required_filters: [{ op: 'eq', field: 'document_id', value: document }],
        });
        const options = { scope: parse_scope(value.scope), deadline: now() + 15 };
        let evidence;
        if (probeName === 'identifier') {
          evidence = await new PostgresSession(resource).transaction(request, options, async session => {
            const candidates = await session.identifier_candidates(query, { limit: 5 });
            requireCondition(candidates.length === 1
              && candidates[0].identifier_profile === 'identifier_ascii_v1');
            const fetched = await session.fetch_evidence(candidates[0], { max_source_bytes: 4096 });
            requireCondition(fetched.state === 'verified' && !fetched.stale && fetched.evidence !== null);
            return [fetched.evidence];
          });
        } else {
          const retriever = new PostgresRetriever(resource, {
            mode, ...(mode === 'dense' ? { embedder: fake } : {}),
          });
          const result = await retriever.retrieve(request, options);
          requireCondition(result.execution === 'complete');
          evidence = result.evidence;
        }
        requireCondition(evidence.length > 0
          && evidence.every(item => item.document_id === document
            && item.source_sha256 === expected.sha256 && item.revision_id === expected.revision_id
            && item.text === expected.text && item.start_byte === 0
            && item.end_byte === Buffer.byteLength(expected.text)
            && item.text_sha256 === createHash('sha256').update(item.text).digest('hex')));
        outcomes[probeName] = 'complete';
      } catch (error) {
        requireCondition(error?.code === 'unsupported_capability');
        outcomes[probeName] = 'unsupported_capability';
      }
    }
  } finally {
    await resource.close();
  }
  return { runtime: 'node', version, installed_bytes_verified: true, ...outcomes };
}

try {
  let raw = '';
  for await (const piece of process.stdin) {
    raw += piece;
    requireCondition(Buffer.byteLength(raw) <= 131072);
  }
  console.log(JSON.stringify(await probe(JSON.parse(raw), process.argv[2])));
} catch {
  console.log(JSON.stringify({ state: 'failed', code: 'migration_package_probe_invalid' }));
  process.exitCode = 1;
}
