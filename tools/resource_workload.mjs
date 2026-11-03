/** RST-r1 explicit native workload; caller owns fixture, stdin and child lifetime. */
import { createHash } from 'node:crypto';
import { realpath } from 'node:fs/promises';
import { isAbsolute, join } from 'node:path';
import { pathToFileURL } from 'node:url';

const checksNames = ['ingestion_fidelity', 'evidence_scope', 'evidence_spans', 'usage_limits',
    'strict_tokens', 'deadlines', 'overload_refused', 'queued_cancelled', 'active_cancelled',
    'reuse_after_queue', 'reuse_after_active', 'cleanup_verified'];
const fail = () => { throw new Error('resource_workload_failed'); };
const requireCheck = value => { if (!value) fail(); };
const hash = value => createHash('sha256').update(value).digest('hex');
const elapsed = start => Math.max(Number.EPSILON, performance.now() - start);
const gate = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return {promise, resolve}; };
async function watchdog(operation, milliseconds) {
    let timer;
    try {
        return await Promise.race([operation, new Promise((_, reject) => {
            timer = setTimeout(() => reject(new Error('resource_workload_failed')), milliseconds);
        })]);
    } finally { clearTimeout(timer); }
}
async function until(predicate, milliseconds = 1000) {
    const start = performance.now();
    while (!predicate()) {
        requireCheck(performance.now() - start < milliseconds);
        await new Promise(resolve => setTimeout(resolve, 2));
    }
}
async function loadSDK(root) {
    const dist = await realpath(join(root, 'dist'));
    const names = ['index', 'postgres-pool', 'requests', 'results', 'context', 'embeddings',
        'vector-ingestion', 'retrieval'];
    const modules = [];
    for (const name of names) modules.push(await import(pathToFileURL(join(dist, name + '.js')).href));
    return Object.assign({}, ...modules);
}

export async function runResourceWorkload(configuration) {
    let config;
    try {
        requireCheck(configuration && Object.getPrototypeOf(configuration) === Object.prototype
            && Object.keys(configuration).sort().join('|') ===
                ['reader_config', 'sdk_root', 'tokenizer_path', 'writer_config'].sort().join('|')
            && Object.getOwnPropertySymbols(configuration).length === 0
            && Object.values(Object.getOwnPropertyDescriptors(configuration)).every(d => 'value' in d)
            && typeof configuration.sdk_root === 'string' && isAbsolute(configuration.sdk_root)
            && typeof configuration.tokenizer_path === 'string' && isAbsolute(configuration.tokenizer_path));
        config = structuredClone(configuration);
    } catch { throw new Error('resource_workload_invalid'); }
    let sdk, writer, reader, counter, failed = false, cleanupFailed = false, output;
    let stage = 'sdk', failureCategory = 'unknown';
    const tasks = [], controllers = [], releases = [];
    const workloadController = new AbortController(); controllers.push(workloadController);
    const own = promise => { tasks.push(promise); void promise.catch(() => {}); return promise; };
    const checks = Object.fromEntries(checksNames.map(name => [name, false]));
    try {
        sdk = await loadSDK(config.sdk_root);
        stage = 'configuration';
        const poolConfig = value => sdk.parse_pool_config({...value, max_size: 1, max_waiting: 1,
            acquire_timeout: 2, close_timeout: 5, release_timeout: 1});
        writer = new sdk.PoolResource(poolConfig(config.writer_config));
        reader = new sdk.PoolResource(poolConfig(config.reader_config));
        counter = await sdk.Cl100kCounter.create(config.tokenizer_path);
        const scope = sdk.parse_scope({tenant_id: 'resource-tenant', principal_id: 'resource-runner',
            authorization_revision: 'resource-auth-r1', grant_ids: []});
        const documents = Array.from({length: 3}, (_, n) => `Resource handbook ${n}. The support route is queue ${n}.`);
        const adapter = () => new sdk.EmbeddingAdapter(async body => {
            const value = JSON.parse(new TextDecoder().decode(body));
            const tokens = value.input.reduce((total, text) => total + Buffer.byteLength(text), 0);
            return Buffer.from(JSON.stringify({model: sdk.FAKE_PROFILE.model,
                data: value.input.map((_, index) => ({index, embedding: [1, ...Array(1535).fill(0)]})),
                usage: {prompt_tokens: tokens, total_tokens: tokens}}));
        }, {name: sdk.FAKE_PROFILE.tokenizer, count: text => Math.max(1, Buffer.byteLength(text))},
        {profile: sdk.FAKE_PROFILE, limits: {max_items: 1}});
        const allowed = new Set(['resource-0', 'resource-1', 'resource-2']);
        const authorize = async (trusted, collection, document) => trusted.tenant_id === scope.tenant_id
            && trusted.principal_id === scope.principal_id
            && trusted.authorization_revision === scope.authorization_revision
            && trusted.grant_ids.length === 0 && collection === 'resource-tests' && allowed.has(document);
        const ingestion_ms = [], receipts = [];
        const indexer = new sdk.PostgresVectorIndexer(writer, authorize, adapter(),
            {embedding_profile: sdk.FAKE_PROFILE, max_batches: 1, max_attempts: 1});
        stage = 'ingestion';
        await writer.open();
        for (let n = 0; n < 3; n++) {
            const start = performance.now();
            const receipt = await indexer.ingest(documents[n], {scope, deadline: sdk.now() + 25, signal: workloadController.signal,
                collection: 'resource-tests', document_id: `resource-${n}`, intent_id: `resource-intent-${n}`,
                source_locator: `resource:${n}`, expected_generation_id: null,
                canonical_options: {target_bytes: 2048, max_chunk_bytes: 4096}});
            ingestion_ms.push(elapsed(start));
            requireCheck(ingestion_ms.at(-1) < 25000);
            requireCheck(receipt.tenant_id === scope.tenant_id && receipt.collection === 'resource-tests'
                && receipt.document_id === `resource-${n}` && receipt.canonical_sha256 === hash(documents[n])
                && receipt.embedding_profile === sdk.FAKE_PROFILE.profile_id && receipt.chunk_count === 1
                && receipt.provider_calls === 1 && !receipt.replayed
                && typeof receipt.revision_id === 'string' && typeof receipt.generation_id === 'string');
            receipts.push(receipt);
        }
        checks.ingestion_fidelity = true;
        await writer.close();
        stage = 'reader_open';
        // Observe the driver's own submitted query, not a timer or a second connection.
        const factory = reader.factory;
        requireCheck(typeof factory === 'function');
        let sleepClient, sleepBytesBefore;
        reader.factory = async value => {
            const pool = await factory(value);
            const connect = pool.connect.bind(pool), wrapped = new WeakSet();
            pool.connect = async () => {
                const client = await connect();
                if (!wrapped.has(client)) {
                    wrapped.add(client);
                    const query = client.query.bind(client);
                    client.query = (...args) => {
                        const sleeping = args[0]?.text === 'SELECT pg_sleep(2)';
                        const before = sleeping ? client.connection?.stream?.bytesWritten : undefined;
                        const pending = query(...args);
                        if (sleeping) { sleepClient = client; sleepBytesBefore = before; }
                        return pending;
                    };
                }
                return client;
            };
            return pool;
        };
        await reader.open();
        const retrieval = [];
        const limits = {deadline_ms: 25000, max_candidates: 15, max_attempts: 3,
            max_subqueries: 3, max_provider_calls: 8, max_context_tokens: 20000};
        const output_profile = {renderer: 'cragkit.context.v2', tokenizer: 'cl100k_base',
            counting_mode: 'strict', envelope_reserve_tokens: 256};
        for (const concurrency of [1, 2]) {
            stage = concurrency === 1 ? 'retrieval_one' : 'retrieval_two';
            const latency_ms = Array(20), context_tokens = Array(20), attempts = Array(20), provider_calls = Array(20);
            let next = 0;
            const start = performance.now();
            const workers = Array.from({length: concurrency}, (_, worker) => own((async () => {
                const retriever = new sdk.PostgresRetriever(reader, {mode: 'hybrid', embedder: adapter(),
                    embedding_profile: sdk.FAKE_PROFILE, evidence_options: {counter}});
                for (;;) {
                    const index = next++;
                    if (index >= 20) break;
                    const request = sdk.parse_request({request_id: `resource-${concurrency}-${worker}-${index}`,
                        query: 'support route queue', collection: 'resource-tests',
                        required_filters: [{op: 'eq', field: 'document_id', value: 'resource-0'}], limits, output_profile});
                    const began = performance.now();
                    const result = sdk.parse_result(await retriever.retrieve(request,
                        {scope, deadline: sdk.now() + 25, signal: workloadController.signal}));
                    const duration = elapsed(began);
                    requireCheck(duration < 25000 && result.execution === 'complete'
                        && result.status !== 'sufficient' && result.evidence.length > 0 && result.evidence.length <= 15);
                    for (const evidence of result.evidence) {
                        requireCheck(receipts[0].tenant_id === scope.tenant_id && evidence.collection === 'resource-tests'
                            && evidence.document_id === 'resource-0' && evidence.revision_id === receipts[0].revision_id
                            && evidence.source_sha256 === hash(documents[0]));
                        const source = Buffer.from(documents[0]);
                        requireCheck(Number.isSafeInteger(evidence.start_byte) && evidence.start_byte >= 0
                            && Number.isSafeInteger(evidence.end_byte) && evidence.end_byte > evidence.start_byte
                            && evidence.end_byte <= source.length
                            && source.subarray(evidence.start_byte, evidence.end_byte).equals(Buffer.from(evidence.text))
                            && evidence.text_sha256 === hash(evidence.text));
                    }
                    const counted = sdk.count_context(result.evidence, {counter, counting_mode: 'strict', max_tokens: 20000, reserve: 256});
                    const usage = result.usage;
                    requireCheck(result.context === counted.context && usage.context_counting === 'strict'
                        && usage.context_tokens === counted.context_tokens && counted.total_tokens <= 20000);
                    requireCheck(Number.isSafeInteger(usage.provider_calls) && usage.provider_calls >= 1 && usage.provider_calls <= 8
                        && Number.isSafeInteger(usage.attempt_count) && usage.attempt_count >= 1 && usage.attempt_count <= 3
                        && usage.cost_kind === 'known' && usage.cost_usd === 0);
                    latency_ms[index] = duration; context_tokens[index] = usage.context_tokens;
                    attempts[index] = usage.attempt_count; provider_calls[index] = usage.provider_calls;
                }
            })()));
            await Promise.all(workers);
            const elapsed_ms = elapsed(start);
            requireCheck(latency_ms.every(n => Number.isFinite(n) && n > 0));
            retrieval.push({concurrency, elapsed_ms, latency_ms, context_tokens, attempts, provider_calls,
                throughput_per_second: 20000 / elapsed_ms});
        }
        for (const name of ['evidence_scope', 'evidence_spans', 'usage_limits', 'strict_tokens', 'deadlines']) checks[name] = true;
        const fresh = async () => reader.withLease({deadline: sdk.now() + 5}, async client => {
            const value = await client.query({text: 'SELECT 1', rowMode: 'array'});
            requireCheck(value.rows.length === 1 && value.rows[0][0] === 1);
        });
        const entered = gate(), release = gate(); releases.push(release);
        stage = 'contention';
        const holder = own(reader.withLease({deadline: sdk.now() + 10}, async () => { entered.resolve(); await release.promise; }));
        await watchdog(entered.promise, 1000);
        const queued = new AbortController(); controllers.push(queued);
        let queuedBody = false;
        const waiting = own(reader.withLease({deadline: sdk.now() + 10, signal: queued.signal}, async () => { queuedBody = true; }));
        await until(() => reader.work?.size === 2);
        let refused = false;
        try { await watchdog(own(reader.withLease({deadline: sdk.now() + 5}, async () => fail())), 1000); }
        catch (error) { refused = error?.code === 'provider_unavailable'; }
        requireCheck(refused); checks.overload_refused = true;
        queued.abort();
        let cancelled = false;
        try { await watchdog(waiting, 1000); } catch (error) { cancelled = error?.name === 'AbortError'; }
        requireCheck(cancelled && !queuedBody); checks.queued_cancelled = true;
        release.resolve(); await watchdog(holder, 1000);
        await until(() => reader.work.size === 0 && reader.connecting.size === 0);
        await fresh(); checks.reuse_after_queue = true;
        stage = 'active_dispatch';
        const activeController = new AbortController(); controllers.push(activeController);
        const active = own(reader.withLease({deadline: sdk.now() + 8, signal: activeController.signal},
            async client => client.query({text: 'SELECT pg_sleep(2)', rowMode: 'array'})));
        await until(() => sleepClient?._activeQuery?.text === 'SELECT pg_sleep(2)' && sleepClient.readyForQuery === false
            && Number.isFinite(sleepBytesBefore) && sleepClient.connection?.stream?.bytesWritten > sleepBytesBefore
            && sleepClient.connection.stream.writableLength === 0);
        activeController.abort();
        stage = 'active_cancel';
        cancelled = false;
        try { await watchdog(active, 5000); } catch (error) { cancelled = error?.name === 'AbortError'; }
        requireCheck(cancelled); checks.active_cancelled = true;
        stage = 'active_reuse';
        // A destroyed frontend socket can precede PostgreSQL backend-slot release.
        // Observe recovery under one deadline without changing library retry policy.
        const recoveryStart = performance.now(), recoveryDeadline = sdk.now() + 5;
        const recoveryController = new AbortController(); controllers.push(recoveryController);
        const recoveryTimer = setTimeout(() => recoveryController.abort(), 5000);
        let recoveryAttempts = 0, recoveryRefusals = 0, recovered = false;
        try {
            for (; recoveryAttempts < 25 && sdk.now() < recoveryDeadline;) {
                recoveryAttempts++;
                try {
                    await reader.withLease({deadline: Math.min(recoveryDeadline, sdk.now() + 2),
                        signal: recoveryController.signal}, async client => {
                        const value = await client.query({text: 'SELECT 1', rowMode: 'array'});
                        requireCheck(value.rows.length === 1 && value.rows[0][0] === 1);
                    });
                    recovered = true;
                    break;
                } catch (error) {
                    if (error?.code !== 'provider_unavailable' || recoveryController.signal.aborted) throw error;
                    recoveryRefusals++;
                }
                const remaining = (recoveryDeadline - sdk.now()) * 1000;
                requireCheck(remaining > 0);
                await new Promise(resolve => setTimeout(resolve, Math.min(100, remaining)));
            }
            requireCheck(recovered && sdk.now() < recoveryDeadline);
        } finally { clearTimeout(recoveryTimer); }
        checks.reuse_after_active = true;
        output = {revision: 'RST-r1', runtime: 'node', version: sdk.version, ingestion_ms, retrieval,
            checks, peak_rss_bytes: process.resourceUsage().maxRSS * 1024, provider_http_calls: 0,
            active_dispatch_observation: 1, recovery_attempts: recoveryAttempts,
            recovery_refusals: recoveryRefusals, recovery_elapsed_ms: elapsed(recoveryStart)};
            // Observation 1 = active driver query plus flushed TLS bytes, not server acknowledgment.
    } catch (error) {
        failed = true;
        if (['invalid_request', 'provider_unavailable', 'deadline_exceeded', 'integrity_violation'].includes(error?.code)) {
            failureCategory = error.code;
        }
    }
    finally {
        for (const controller of controllers) controller.abort();
        for (const release of releases) release.resolve();
        try { await watchdog(Promise.allSettled(tasks), 5000); } catch { cleanupFailed = true; }
        for (const resource of [writer, reader]) {
            try { if (resource) await resource.close(); } catch { cleanupFailed = true; }
        }
        try { counter?.close(); } catch { cleanupFailed = true; }
    }
    if (cleanupFailed) throw new Error('resource_workload_cleanup_failed');
    if (failed) {
        const error = new Error('resource_workload_failed');
        error.stage = stage;
        error.category = failureCategory;
        throw error;
    }
    checks.cleanup_verified = true;
    requireCheck(checksNames.every(name => checks[name] === true));
    return output;
}
