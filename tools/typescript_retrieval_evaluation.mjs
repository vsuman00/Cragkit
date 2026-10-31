/** EVX-r1 native execution. Mechanics and replay never authorize live inference. */
import { createHash } from 'node:crypto';
import { realpathSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { PoolResource, parse_pool_config, now } from '../packages/typescript/dist/postgres-pool.js';
import { parse_request, parse_scope } from '../packages/typescript/dist/requests.js';
import { parse_result } from '../packages/typescript/dist/results.js';
import { identity, deep_freeze } from '../packages/typescript/dist/shared.js';
import { Cl100kCounter } from '../packages/typescript/dist/context.js';
import { EmbeddingAdapter, FAKE_PROFILE, OPENAI_PROFILE } from '../packages/typescript/dist/embeddings.js';
import { RerankingAdapter, FAKE_RERANK_PROFILE } from '../packages/typescript/dist/reranking.js';
import { PlannerAdapter } from '../packages/typescript/dist/planning.js';
import { extract_identifiers } from '../packages/typescript/dist/identifiers.js';
import { PostgresVectorIndexer } from '../packages/typescript/dist/vector-ingestion.js';
import { PostgresRetriever } from '../packages/typescript/dist/retrieval.js';
import { PostgresCorrectiveBackend } from '../packages/typescript/dist/postgres-corrective.js';
import { CorrectiveRetriever } from '../packages/typescript/dist/corrective.js';
import { InvalidRequest, IntegrityViolation, DeadlineExceeded } from '../packages/typescript/dist/errors.js';
import { create_provider_replay } from './provider_replay.mjs';

export class EvaluationExecutionError extends Error {
    constructor(code) {
        const allowed = ['invalid_evaluation_packet', 'invalid_evaluation_configuration', 'evaluation_execution_failed'];
        const safe = allowed.includes(code) ? code : 'evaluation_execution_failed';
        super(safe);
        this.name = 'EvaluationExecutionError';
        this.code = safe;
    }
}

export const MODES = Object.freeze(['lexical', 'dense', 'hybrid', 'reranked_hybrid', 'corrective']);
const LIMITS = Object.freeze({
    deadline_ms: 25000, max_candidates: 15, max_attempts: 3, max_subqueries: 3,
    max_provider_calls: 8, max_context_tokens: 20000,
});
const OUTPUT = Object.freeze({
    renderer: 'cragkit.context.v2', tokenizer: 'cl100k_base',
    counting_mode: 'strict', envelope_reserve_tokens: 256,
});
const COHERE_PROFILE = Object.freeze({
    profile_id: 'cohere_v5fast_evaluation_v1', provider: 'cohere', model: 'rerank-v5.0-fast',
    model_revision: 'mutable_alias:rerank-v5.0-fast', score_kind: 'relevance_score',
    score_direction: 'higher_is_better', preprocessing_revision: 'utf8-evaluation-r1',
    truncation_policy: 'reject',
});
const sha256 = value => createHash('sha256').update(value).digest('hex');
const compact = value => Buffer.from(JSON.stringify(value), 'utf8');
const compareUTF8 = (left, right) => Buffer.compare(Buffer.from(left), Buffer.from(right));
const groupKey = document => JSON.stringify([document.tenant_id, document.collection, document.document_id]);
const scopeFor = tenant_id => parse_scope({
    tenant_id, principal_id: 'v6-evaluation', authorization_revision: 'v6-auth-r1', grant_ids: [],
});
function exactFields(value, fields) {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
        && Object.keys(value).sort().join('\0') === [...fields].sort().join('\0');
}
function invalid() {
    throw new InvalidRequest();
}
// Copy data descriptors only; never invoke a packet getter, iterator or toJSON hook.
function snapshotJSON(input) {
    let nodes = 0;
    const ancestors = new Set();
    function copy(value, depth = 0) {
        if (++nodes > 32000 || depth > 32) invalid();
        if (value === null || typeof value === 'boolean') return value;
        if (typeof value === 'string') {
            if (/[\uD800-\uDFFF]/u.test(value)) invalid();
            return value;
        }
        if (typeof value === 'number') {
            if (!Number.isFinite(value) || Math.abs(value) > Number.MAX_SAFE_INTEGER) invalid();
            return value;
        }
        if (typeof value !== 'object' || ancestors.has(value)
            || Object.getOwnPropertySymbols(value).length) invalid();
        const array = Array.isArray(value);
        if (!array && ![Object.prototype, null].includes(Object.getPrototypeOf(value))) invalid();
        const descriptors = Object.getOwnPropertyDescriptors(value);
        if (array && (value.length > 4096 || Object.keys(descriptors).length !== value.length + 1)) invalid();
        const output = array ? [] : Object.create(null);
        ancestors.add(value);
        try {
            for (const [key, descriptor] of Object.entries(descriptors)) {
                if (array && key === 'length') continue;
                if (!('value' in descriptor) || !descriptor.enumerable) invalid();
                if (array && !/^(0|[1-9]\d*)$/.test(key)) invalid();
                output[key] = copy(descriptor.value, depth + 1);
            }
        } finally {
            ancestors.delete(value);
        }
        return output;
    }
    return copy(input);
}
export function validate_packet(input) {
    try {
        const packet = snapshotJSON(input);
        if (!exactFields(packet, ['revision', 'documents', 'queries']) || packet.revision !== 'EVX-r1'
            || !Array.isArray(packet.documents) || packet.documents.length < 1 || packet.documents.length > 32
            || !Array.isArray(packet.queries) || packet.queries.length < 1 || packet.queries.length > 30) invalid();
        let totalBytes = 0;
        const revisions = new Set(), activeGroups = new Map(), tenantCollections = new Set();
        for (const document of packet.documents) {
            if (!exactFields(document, ['tenant_id', 'collection', 'document_id', 'revision_id',
                'active', 'text', 'canonical_sha256'])) invalid();
            scopeFor(document.tenant_id);
            identity.parse(document.document_id);
            identity.parse(document.revision_id);
            parse_request({query: 'validation', collection: document.collection});
            if (typeof document.active !== 'boolean' || typeof document.text !== 'string'
                || !document.text || Buffer.byteLength(document.text) > 65536
                || typeof document.canonical_sha256 !== 'string'
                || !/^[a-f0-9]{64}$/.test(document.canonical_sha256)
                || sha256(document.text) !== document.canonical_sha256) invalid();
            totalBytes += Buffer.byteLength(document.text);
            const revisionKey = JSON.stringify([document.tenant_id, document.collection,
                document.document_id, document.revision_id]);
            if (revisions.has(revisionKey)) invalid();
            revisions.add(revisionKey);
            const group = groupKey(document);
            activeGroups.set(group, (activeGroups.get(group) ?? 0) + Number(document.active));
            tenantCollections.add(JSON.stringify([document.tenant_id, document.collection]));
        }
        if ([...activeGroups.values()].some(count => count !== 1)) invalid();
        const queryIDs = new Set();
        for (const query of packet.queries) {
            if (!exactFields(query, ['question_id', 'tenant_id', 'collection', 'query', 'required_filters'])) invalid();
            identity.parse(query.question_id);
            scopeFor(query.tenant_id);
            parse_request({query: query.query, collection: query.collection, required_filters: query.required_filters});
            if (typeof query.query !== 'string' || Buffer.byteLength(query.query) > 8192
                || !Array.isArray(query.required_filters) || queryIDs.has(query.question_id)
                || !tenantCollections.has(JSON.stringify([query.tenant_id, query.collection]))) invalid();
            queryIDs.add(query.question_id);
            totalBytes += Buffer.byteLength(query.query);
        }
        if (totalBytes > 1048576) invalid();
        return deep_freeze(packet);
    } catch {
        throw new EvaluationExecutionError('invalid_evaluation_packet');
    }
}
export function query_variants(query) {
    const variants = [], seen = new Set([query]);
    const normalized = query.replace(/[ \t\r\n\f\v]+/g, ' ').replace(/^ | $/g, '');
    const identifiers = extract_identifiers(query).join(' ');
    for (const [variant_id, text] of [['normalized', normalized], ['identifiers', identifiers]]) {
        if (text && !seen.has(text)) {
            seen.add(text);
            variants.push({facet_id: 'query-intent', variant_id, query: text});
        }
    }
    return deep_freeze(variants);
}
export function translate_filters(filters, receipts, tenant, collection) {
    function aliases(value) {
        if (typeof value !== 'string') return [value];
        const matches = receipts.filter(receipt => receipt.tenant_id === tenant && receipt.collection === collection
            && receipt.logical_revision_id === value).map(receipt => receipt.revision_id);
        return matches.length ? matches : [value];
    }
    function translate(filter) {
        if (filter.op === 'and' || filter.op === 'or') {
            return {op: filter.op, filters: filter.filters.map(translate)};
        }
        if (filter.op === 'not') return {op: 'not', filter: translate(filter.filter)};
        if (filter.field !== 'revision_id' || !['eq', 'ne', 'in'].includes(filter.op)) return {...filter};
        if (filter.op !== 'in' && typeof filter.value !== 'string') return {...filter};
        const values = [...new Set((filter.op === 'in' ? filter.values : [filter.value]).flatMap(aliases))];
        values.sort((left, right) => typeof left === 'string' && typeof right === 'string'
            ? compareUTF8(left, right) : compareUTF8(JSON.stringify(left), JSON.stringify(right)));
        const chunks = [];
        for (let index = 0; index < values.length; index += 32) {
            chunks.push({op: 'in', field: 'revision_id', values: values.slice(index, index + 32)});
        }
        const membership = chunks.length === 1 ? chunks[0] : {op: 'or', filters: chunks};
        return filter.op === 'ne' ? {op: 'not', filter: membership} : membership;
    }
    return filters.map(translate);
}
function sortedDocuments(packet) {
    return [...packet.documents].sort((left, right) => {
        for (const field of ['tenant_id', 'collection', 'document_id']) {
            const difference = compareUTF8(left[field], right[field]);
            if (difference) return difference;
        }
        return Number(left.active) - Number(right.active) || compareUTF8(left.revision_id, right.revision_id);
    });
}
function safeCode(error) {
    const codes = ['invalid_request', 'unauthorized_scope', 'unsupported_capability', 'index_not_ready',
        'embedding_profile_mismatch', 'provider_unavailable', 'deadline_exceeded',
        'context_budget_too_small', 'integrity_violation'];
    if (error instanceof EvaluationExecutionError) return error.code;
    return codes.includes(error?.code) ? error.code : 'evaluation_execution_failed';
}
function uncheckedConfiguration(options) {
    if (!options || ![Object.prototype, null].includes(Object.getPrototypeOf(options))
        || Object.getOwnPropertySymbols(options).length) invalid();
    const descriptors = Object.getOwnPropertyDescriptors(options);
    if (Object.entries(descriptors).some(([key, descriptor]) => !['reader_config', 'writer_config',
        'tokenizer_path', 'kind', 'recordings', 'signal'].includes(key)
        || !('value' in descriptor) || !descriptor.enumerable)) invalid();
    const kind = options.kind ?? 'mechanics';
    if (!['mechanics', 'replay'].includes(kind) || typeof options.tokenizer_path !== 'string'
        || !options.tokenizer_path || options.signal !== undefined && !(options.signal instanceof AbortSignal)
        || kind === 'mechanics' && Object.hasOwn(options, 'recordings')
        || kind === 'replay' && !Object.hasOwn(options, 'recordings')) invalid();
    return {
        kind, reader_config: parse_pool_config({...options.reader_config, max_size: 1}),
        writer_config: parse_pool_config({...options.writer_config, max_size: 1}),
        tokenizer_path: options.tokenizer_path, signal: options.signal,
        replay: kind === 'replay' ? create_provider_replay(options.recordings) : null,
    };
}
function configuration(options) {
    try {
        return uncheckedConfiguration(options);
    } catch {
        throw new EvaluationExecutionError('invalid_evaluation_configuration');
    }
}
export async function run_evaluation(input, options) {
    const packet = validate_packet(input);
    const config = configuration(options);
    if (config.signal?.aborted) throw config.signal.reason;
    const controller = new AbortController();
    const relayAbort = () => controller.abort(config.signal.reason);
    config.signal?.addEventListener('abort', relayAbort, {once: true});
    const timer = setTimeout(() => controller.abort(new DeadlineExceeded()), 900000);
    const executionDeadline = now() + 900;
    const reader = new PoolResource(config.reader_config), writer = new PoolResource(config.writer_config);
    let counter, activeLeases = 0;
    for (const resource of [reader, writer]) {
        const withLease = resource.withLease.bind(resource);
        resource.withLease = (bound, operation) => withLease(bound, async (...arguments_) => {
            activeLeases++;
            try { return await operation(...arguments_); } finally { activeLeases--; }
        });
    }
    const check = () => {
        if (config.signal?.aborted) throw config.signal.reason;
        if (controller.signal.aborted || now() >= executionDeadline) throw new DeadlineExceeded();
    };
    const bound = tenant => ({scope: scopeFor(tenant), deadline: Math.min(now() + 25, executionDeadline), signal: controller.signal});
    const noLease = () => {
        check();
        if (activeLeases !== 0) throw new IntegrityViolation();
    };
    const receipts = [], rows = [];
    let cleanupFailure = false;
    let executionFailure;
    try {
        counter = await Cl100kCounter.create(config.tokenizer_path);
        check();
        const selectedProfile = config.kind === 'mechanics' ? FAKE_PROFILE : OPENAI_PROFILE;
        const embeddingTransport = config.kind === 'mechanics' ? async body => {
            noLease();
            const request = JSON.parse(new TextDecoder().decode(body));
            return compact({model: FAKE_PROFILE.model, data: request.input.map((_, index) => ({
                index, embedding: [1, ...Array(1535).fill(0)],
            })), usage: {prompt_tokens: 0, total_tokens: 0}});
        } : async (body, options_) => {
            noLease();
            return config.replay.embedding_transport(body, options_);
        };
        const embedder = new EmbeddingAdapter(embeddingTransport, {
            name: selectedProfile.tokenizer,
            count: text => config.kind === 'mechanics' ? Math.max(1, Buffer.byteLength(text)) : counter.count(text),
        }, {profile: selectedProfile, policy: config.kind === 'mechanics' ? {} : {
            allow_live: true, max_cost_usd: .01, usd_per_million_tokens: .02,
        }});
        const reranker = new RerankingAdapter(async (body, options_) => {
            noLease();
            if (config.replay) return config.replay.rerank_transport(body, options_);
            const request = JSON.parse(new TextDecoder().decode(body));
            return compact(request.candidates.map((candidate, index) => ({
                candidate_id: candidate.candidate_id, raw_score: 1 / (index + 1),
            })));
        }, {profile: config.kind === 'mechanics' ? FAKE_RERANK_PROFILE : COHERE_PROFILE,
            allow_live: config.kind === 'replay'});
        const allowed = new Set(packet.documents.map(groupKey));
        const authorize = async (scope, collection, document_id) => scope.principal_id === 'v6-evaluation'
            && scope.authorization_revision === 'v6-auth-r1' && scope.grant_ids.length === 0
            && allowed.has(groupKey({tenant_id: scope.tenant_id, collection, document_id}));
        const indexer = new PostgresVectorIndexer(writer, authorize, embedder, {embedding_profile: selectedProfile});
        await writer.open();
        const previous = new Map(), nativeAliases = new Set();
        for (const document of sortedDocuments(packet)) {
            check();
            const identityDigest = sha256(compact([document.tenant_id, document.collection,
                document.document_id, document.revision_id]));
            const receipt = await indexer.ingest(document.text, {
                ...bound(document.tenant_id), collection: document.collection, document_id: document.document_id,
                intent_id: 'eval-' + identityDigest, source_locator: 'evaluation:' + identityDigest,
                expected_generation_id: previous.get(groupKey(document)) ?? null,
                canonical_options: {target_bytes: 2048, max_chunk_bytes: 4096},
            });
            check();
            if (receipt.canonical_sha256 !== document.canonical_sha256) throw new IntegrityViolation();
            const aliasKey = JSON.stringify([groupKey(document), receipt.revision_id]);
            if (nativeAliases.has(aliasKey)) throw new IntegrityViolation();
            nativeAliases.add(aliasKey);
            previous.set(groupKey(document), receipt.generation_id);
            receipts.push({tenant_id: document.tenant_id, collection: document.collection,
                document_id: document.document_id, logical_revision_id: document.revision_id,
                revision_id: receipt.revision_id, generation_id: receipt.generation_id,
                canonical_sha256: receipt.canonical_sha256, embedding_profile: receipt.embedding_profile,
                active: document.active});
        }
        await writer.close();
        await reader.open();
        for (const query of packet.queries) {
            for (const mode of MODES) {
                check();
                const started = performance.now();
                let result;
                try {
                    const request = parse_request({
                        request_id: 'eval-' + sha256(compact([query.question_id, mode])), query: query.query,
                        collection: query.collection, required_filters: translate_filters(query.required_filters,
                            receipts, query.tenant_id, query.collection), limits: LIMITS, output_profile: OUTPUT,
                    });
                    const options_ = bound(query.tenant_id);
                    if (mode === 'corrective') {
                        const variants = query_variants(query.query);
                        const planner = new PlannerAdapter({cost_upper_usd: 0, transport: async payload => {
                            noLease();
                            const approved = payload.variants.filter(variant => payload.missing_facets.includes(variant.facet_id));
                            return {plan: {queries: approved.slice(0, payload.max_subqueries - 1).map(({facet_id, variant_id}) =>
                                ({facet_id, variant_id}))}, usage: {input_tokens: 0, output_tokens: 0, cost_usd: 0}};
                        }});
                        const backend = new PostgresCorrectiveBackend({resource: reader, mode: 'hybrid',
                            embedder, embedding_profile: selectedProfile, reranker});
                        result = (await new CorrectiveRetriever({backend, variants, planner, counter,
                            batch_size: 15, max_retries: 0}).retrieve(request, options_)).result;
                    } else {
                        const evidence_options = {counter};
                        if (mode === 'reranked_hybrid') evidence_options.reranker = reranker;
                        const retrievalOptions = {mode: mode === 'reranked_hybrid' ? 'hybrid' : mode, evidence_options};
                        if (mode !== 'lexical') Object.assign(retrievalOptions, {embedder, embedding_profile: selectedProfile});
                        result = await new PostgresRetriever(reader, retrievalOptions).retrieve(request, options_);
                    }
                    check();
                    result = parse_result(result);
                } catch (error) {
                    check();
                    result = {operational_failure: true, error_code: safeCode(error)};
                }
                rows.push({question_id: query.question_id, mode, result,
                    latency_ms: Math.max(0, performance.now() - started)});
            }
        }
        // Failed rows already make acceptance fail; retain their denominator evidence.
        if (!rows.some(row => row.result.operational_failure === true)) {
            config.replay?.assert_complete();
        }
    } catch (error) {
        executionFailure = error;
        if (config.signal?.aborted) throw config.signal.reason;
        if (safeCode(error) === 'evaluation_execution_failed' && !(error instanceof EvaluationExecutionError)) {
            throw new EvaluationExecutionError('evaluation_execution_failed');
        }
        throw error;
    } finally {
        const closed = await Promise.allSettled([writer.close(), reader.close()]);
        cleanupFailure = closed.some(outcome => outcome.status !== 'fulfilled') || activeLeases !== 0;
        try { counter?.close(); } catch { cleanupFailure = true; }
        clearTimeout(timer);
        config.signal?.removeEventListener('abort', relayAbort);
        if (config.signal?.aborted) throw config.signal.reason;
        if (cleanupFailure && executionFailure === undefined) {
            throw new EvaluationExecutionError('evaluation_execution_failed');
        }
    }
    return deep_freeze({revision: 'EVX-r1', runtime: 'node', kind: config.kind,
        receipts, rows, cleanup_verified: true});
}
async function main() {
    const controller = new AbortController();
    const abort = () => {
        controller.abort(new DOMException('Evaluation cancelled.', 'AbortError'));
        process.stdin.destroy();
    };
    const timer = setTimeout(() => {
        controller.abort(new DeadlineExceeded());
        process.stdin.destroy();
    }, 900000);
    process.once('SIGINT', abort);
    process.once('SIGTERM', abort);
    try {
        const chunks = [];
        let bytes = 0;
        for await (const chunk of process.stdin) {
            bytes += chunk.length;
            if (bytes > 67108864) invalid();
            chunks.push(chunk);
        }
        const decoded = new TextDecoder('utf-8', {fatal: true}).decode(Buffer.concat(chunks));
        const input = JSON.parse(decoded);
        if (!exactFields(input, ['packet', 'options']) || !input.options
            || Object.hasOwn(input.options, 'signal')) invalid();
        const result = await run_evaluation(input.packet, {...input.options, signal: controller.signal});
        process.stdout.write(JSON.stringify(result) + '\n');
    } catch (error) {
        process.stdout.write(JSON.stringify({revision: 'EVX-r1', runtime: 'node',
            error_code: controller.signal.aborted
                ? controller.signal.reason instanceof DeadlineExceeded ? 'deadline_exceeded' : 'cancelled'
                : safeCode(error), cleanup_verified: false}) + '\n');
        process.exitCode = 1;
    } finally {
        clearTimeout(timer);
        process.removeListener('SIGINT', abort);
        process.removeListener('SIGTERM', abort);
    }
}
let directEntry = false;
try {
    directEntry = Boolean(process.argv[1])
        && realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url));
} catch {
    // An importing host may supply an argv value that is not a filesystem path.
}
if (directEntry) await main();
