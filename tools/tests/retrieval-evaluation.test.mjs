/** Native evaluation mechanics tests; no server, HTTP or live identity vectors. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, mkdtempSync, symlinkSync, rmSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {spawn, spawnSync} from 'node:child_process';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {validate_packet, query_variants, translate_filters, run_evaluation, MODES, EvaluationExecutionError}
    from '../typescript_retrieval_evaluation.mjs';
import {PoolResource} from '../../packages/typescript/dist/postgres-pool.js';
import {PostgresVectorIndexer} from '../../packages/typescript/dist/vector-ingestion.js';
import {PostgresRetriever} from '../../packages/typescript/dist/retrieval.js';
import {CorrectiveRetriever} from '../../packages/typescript/dist/corrective.js';
import {ProviderUnavailable} from '../../packages/typescript/dist/errors.js';

const packet = () => JSON.parse(readFileSync(new URL('../../contracts/fixtures/retrieval_evaluation.json', import.meta.url)));
const hash = text => createHash('sha256').update(text).digest('hex');
const invalid = error => error instanceof EvaluationExecutionError
    && ['invalid_evaluation_packet', 'invalid_evaluation_configuration'].includes(error.code);
const poolConfig = {
    host: 'localhost', dbname: 'evaluation', user: 'evaluation',
    sslrootcert: '/synthetic/root.crt', passfile: '/synthetic/pgpass',
};
const options = () => ({reader_config: {...poolConfig}, writer_config: {...poolConfig},
    tokenizer_path: fileURLToPath(new URL('../../artifacts/tokenizers/cl100k_base.tiktoken', import.meta.url))});

test('packet snapshot rejects labels before opening a pool or tokenizer', async () => {
    let opened = false;
    const original = PoolResource.prototype.open;
    PoolResource.prototype.open = async () => {opened = true; throw Error('unexpected I/O');};
    try {
        const raw = packet();
        raw.queries[0].support_spans = [];
        await assert.rejects(run_evaluation(raw, options()), invalid);
        assert.equal(opened, false);
    } finally {
        PoolResource.prototype.open = original;
    }
});
for (const mutate of [
    raw => raw.labels = [],
    raw => raw.documents[0].active = 'false',
    raw => raw.documents[0].canonical_sha256 = '0'.repeat(64),
    raw => raw.documents[1].active = false,
    raw => raw.documents.push({...raw.documents[0]}),
    raw => raw.queries[1].question_id = raw.queries[0].question_id,
    raw => raw.queries[0].tenant_id = 'unknown',
    raw => raw.queries[0].required_filters = 'all',
    raw => raw.queries[0].query = 'x'.repeat(8193),
    raw => raw.documents[0].text = '\ud800',
    raw => raw.documents = [],
    raw => raw.queries = [],
]) {
    test('malformed or label-bearing packet fails full pre-I/O validation', () => {
        const raw = packet();
        mutate(raw);
        assert.throws(() => validate_packet(raw), invalid);
    });
}
test('packet data snapshots are deep frozen and never invoke getters', () => {
    const raw = packet(), snapshot = validate_packet(raw);
    raw.queries[0].query = 'changed';
    assert.notEqual(snapshot.queries[0].query, raw.queries[0].query);
    assert.equal(Object.isFrozen(snapshot.documents[0]), true);
    let invoked = false;
    Object.defineProperty(raw.documents[0], 'text', {enumerable: true, get() {invoked = true; return 'private';}});
    assert.throws(() => validate_packet(raw), invalid);
    assert.equal(invoked, false);
});
test('source and query packet bytes share the 1 MiB cap', () => {
    const raw = packet();
    raw.documents = Array.from({length: 17}, (_, index) => ({...raw.documents[0],
        document_id: 'doc-' + index, active: true, text: 'x'.repeat(65536),
        canonical_sha256: hash('x'.repeat(65536))}));
    assert.throws(() => validate_packet(raw), invalid);
});
test('query-only variants normalize ASCII whitespace and retain identifiers without duplicates', () => {
    assert.deepEqual(query_variants('  ERR-17\tCACHE-2\nquestion  '), [
        {facet_id: 'query-intent', variant_id: 'normalized', query: 'ERR-17 CACHE-2 question'},
        {facet_id: 'query-intent', variant_id: 'identifiers', query: 'CACHE-2 ERR-17'},
    ]);
    assert.deepEqual(query_variants('ERR-17'), []);
    assert.deepEqual(query_variants('plain words'), []);
    assert.deepEqual(query_variants('plain\u00a0words'), []);
});
const receipts = [
    {tenant_id: 'a', collection: 'c', document_id: 'one', logical_revision_id: 'r1', revision_id: 'hash-b'},
    {tenant_id: 'a', collection: 'c', document_id: 'two', logical_revision_id: 'r1', revision_id: 'hash-a'},
    {tenant_id: 'b', collection: 'c', document_id: 'one', logical_revision_id: 'r1', revision_id: 'foreign'},
];
test('revision equality, inequality and membership preserve scoped alias unions and unknown literals', () => {
    const mapped = translate_filters([
        {op: 'eq', field: 'revision_id', value: 'r1'},
        {op: 'ne', field: 'revision_id', value: 'r1'},
        {op: 'in', field: 'revision_id', values: ['missing', 'r1']},
        {op: 'eq', field: 'document_id', value: 'one'},
        {op: 'eq', field: 'revision_id', value: 7},
    ], receipts, 'a', 'c');
    assert.deepEqual(mapped, [
        {op: 'in', field: 'revision_id', values: ['hash-a', 'hash-b']},
        {op: 'not', filter: {op: 'in', field: 'revision_id', values: ['hash-a', 'hash-b']}},
        {op: 'in', field: 'revision_id', values: ['hash-a', 'hash-b', 'missing']},
        {op: 'eq', field: 'document_id', value: 'one'},
        {op: 'eq', field: 'revision_id', value: 7},
    ]);
});
test('recursive alias translation retains every not/and/or restriction', () => {
    const filters = [{op: 'not', filter: {op: 'or', filters: [
        {op: 'and', filters: [{op: 'eq', field: 'revision_id', value: 'r1'}]},
        {op: 'eq', field: 'document_id', value: 'one'},
    ]}}];
    const expected = structuredClone(filters);
    expected[0].filter.filters[0].filters[0] = {op: 'in', field: 'revision_id', values: ['hash-a', 'hash-b']};
    assert.deepEqual(translate_filters(filters, receipts, 'a', 'c'), expected);
});
test('large alias unions split into bounded membership groups without dropping unknowns', () => {
    const many = Array.from({length: 32}, (_, index) => ({tenant_id: 'a', collection: 'c',
        logical_revision_id: 'r1', revision_id: 'hash-' + index}));
    const filters = [{op: 'in', field: 'revision_id', values: ['r1', 'unknown']}];
    const mapped = translate_filters(filters, many, 'a', 'c');
    assert.equal(mapped[0].op, 'or');
    assert.equal(mapped[0].filters[0].values.length, 32);
    assert.equal(mapped[0].filters[1].values.length, 1);
    assert.equal(mapped[0].filters.flatMap(filter => filter.values).includes('unknown'), true);
});
test('operational failures retain all five rows and owned resources close', async () => {
    const originals = {
        open: PoolResource.prototype.open, close: PoolResource.prototype.close,
        ingest: PostgresVectorIndexer.prototype.ingest, retrieve: PostgresRetriever.prototype.retrieve,
        corrective: CorrectiveRetriever.prototype.retrieve,
    };
    let closes = 0;
    PoolResource.prototype.open = async () => {};
    PoolResource.prototype.close = async () => {closes++;};
    PostgresVectorIndexer.prototype.ingest = async (text, input) => ({
        revision_id: hash(input.source_locator), generation_id: hash(input.intent_id),
        canonical_sha256: hash(text), embedding_profile: 'fake_embedding_1536_v1',
    });
    PostgresRetriever.prototype.retrieve = async () => {throw new ProviderUnavailable();};
    CorrectiveRetriever.prototype.retrieve = async () => {throw new ProviderUnavailable();};
    try {
        const raw = packet();
        raw.queries = raw.queries.slice(0, 1);
        const result = await run_evaluation(raw, options());
        assert.equal(result.runtime, 'node');
        assert.equal(result.rows.length, 5);
        assert.deepEqual(result.rows.map(row => row.mode), MODES);
        assert.ok(result.rows.every(row => row.result.operational_failure
            && row.result.error_code === 'provider_unavailable'));
        assert.equal(result.cleanup_verified, true);
        assert.equal(closes, 3);
        assert.deepEqual(result.receipts.map(receipt => [receipt.document_id, receipt.logical_revision_id]),
            [['cache-policy', 'r1'], ['retry-policy', 'r1'], ['retry-policy', 'r2'], ['foreign-only', 'r1']]);
    } finally {
        PoolResource.prototype.open = originals.open;
        PoolResource.prototype.close = originals.close;
        PostgresVectorIndexer.prototype.ingest = originals.ingest;
        PostgresRetriever.prototype.retrieve = originals.retrieve;
        CorrectiveRetriever.prototype.retrieve = originals.corrective;
    }
});
test('caller cancellation is preserved before any I/O', async () => {
    const failure = new DOMException('synthetic cancelled', 'AbortError');
    await assert.rejects(run_evaluation(packet(), {...options(), signal: AbortSignal.abort(failure)}),
        error => error === failure);
});
test('mechanics rejects recording tapes and malformed trusted configuration before opening resources', async () => {
    await assert.rejects(run_evaluation(packet(), {...options(), recordings: []}), invalid);
    await assert.rejects(run_evaluation(packet(), {...options(), kind: 'live'}), invalid);
});

test('real CLI aborts incomplete stdin promptly and emits only redacted cancellation JSON', async () => {
    const preload = "process.on('newListener', name => { if (name === 'SIGTERM') setImmediate(() => process.stderr.write('ready\\n')); });";
    const child = spawn(process.execPath, [
        '--import', 'data:text/javascript,' + encodeURIComponent(preload),
        fileURLToPath(new URL('../typescript_retrieval_evaluation.mjs', import.meta.url)),
    ], {stdio: ['pipe', 'pipe', 'pipe']});
    let output = '', diagnostics = '';
    const timeout = setTimeout(() => child.kill('SIGKILL'), 5000);
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', chunk => {output += chunk;});
    const ready = new Promise(resolve => child.stderr.on('data', chunk => {
        diagnostics += chunk;
        if (diagnostics.includes('ready\n')) resolve();
    }));
    const exited = new Promise(resolve => child.once('exit', (code, signal) => resolve({code, signal})));
    try {
        child.stdin.write('{"packet":');
        await Promise.race([ready, exited.then(() => {throw Error('CLI exited before readiness');})]);
        child.kill('SIGTERM');
        const result = await exited;
        assert.equal(result.signal, null);
        assert.equal(result.code, 1);
        assert.deepEqual(JSON.parse(output), {
            revision: 'EVX-r1', runtime: 'node', error_code: 'cancelled', cleanup_verified: false,
        });
        assert.equal(diagnostics, 'ready\n');
    } finally {
        clearTimeout(timeout);
        child.stdin.destroy();
        if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
    }
});

test('symlink CLI validates stdin instead of silently succeeding without execution', () => {
    const directory = mkdtempSync(join(tmpdir(), 'cragkit-evaluation-entry-'));
    try {
        const link = join(directory, 'evaluation.mjs');
        symlinkSync(fileURLToPath(new URL('../typescript_retrieval_evaluation.mjs', import.meta.url)), link);
        const result = spawnSync(process.execPath, [link], {input: '', encoding: 'utf8', timeout: 5000});
        assert.equal(result.status, 1);
        assert.equal(result.stderr, '');
        assert.deepEqual(JSON.parse(result.stdout), {
            revision: 'EVX-r1', runtime: 'node', error_code: 'evaluation_execution_failed', cleanup_verified: false,
        });
    } finally {
        rmSync(directory, {recursive: true});
    }
});
