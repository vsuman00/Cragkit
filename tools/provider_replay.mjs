/** Offline ordered provider replay. Synthetic tapes establish mechanics only. */
import { createHash } from 'node:crypto';
const OPENAI = 'text-embedding-3-small', COHERE = 'rerank-v5.0-fast', MAX = 2097152;
export class ProviderReplayError extends Error {
    constructor(code = 'provider_mapping_invalid') {
        const allowedCodes = [
            'provider_mapping_invalid', 'cancelled', 'deadline_exceeded',
            'concurrent_dispatch', 'replay_missing', 'replay_mismatch', 'replay_unconsumed',
        ];
        const safe = allowedCodes.includes(code) ? code : 'provider_mapping_invalid';
        super(safe);
        this.name = 'ProviderReplayError';
        this.code = safe;
    }
}
const fail = (code) => {
    throw new ProviderReplayError(code);
};
const hash = value => createHash('sha256').update(value).digest('hex');
const encode = value => Buffer.from(JSON.stringify(value, (_, v) => v instanceof DecimalOrExponentToken ? v.value : v));
// Records JSON number spelling; its value still uses ordinary JavaScript numbers.
class DecimalOrExponentToken {
    constructor(value) {
        this.value = value;
    }
}
const number = value => value instanceof DecimalOrExponentToken ? value.value : value;
const finite = value => {
    const numericValue = number(value);
    if (typeof numericValue !== 'number' || !Number.isFinite(numericValue)) {
        fail();
    }
    return numericValue;
};
const count = value => {
    if (typeof value !== 'number' || !Number.isInteger(value) || value < 0 || value > 2147483647) {
        fail();
    }
    return value;
};
const object = value => value !== null && typeof value === 'object'
    && !Array.isArray(value) && !(value instanceof DecimalOrExponentToken);
const exact = (value, keys) => object(value)
    && Object.keys(value).sort().join('\0') === [...keys].sort().join('\0');
function text(value, max, empty = false) {
    if (typeof value !== 'string' || (!empty && !value)
        || /[\uD800-\uDFFF]/u.test(value) || Buffer.byteLength(value) > max) {
        fail();
    }
    return value;
}
// Keep integer spelling distinct from decimal/exponent tokens, as Python's strict mapper does.
function parse(raw, limit) {
    if (!(raw instanceof Uint8Array) || raw.length > limit) {
        fail();
    }
    let jsonText;
    try {
        jsonText = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(raw);
    }
    catch {
        fail();
    }
    let position = 0, nodeCount = 0;
    function skipWhitespace() {
        while (/[\x20\t\r\n]/.test(jsonText[position] ?? 'x')) {
            position++;
        }
    }
    function parseString() {
        const startPosition = position++;
        let escaped = false;
        while (position < jsonText.length) {
            const character = jsonText[position++];
            if (!escaped && character === '"') {
                try {
                    return text(JSON.parse(jsonText.slice(startPosition, position)), MAX, true);
                } catch {
                    fail();
                }
            }
            if (!escaped && character === '\\') {
                escaped = true;
            } else {
                escaped = false;
            }
        }
        fail();
    }
    function parseValue(depth) {
        if (depth > 32 || ++nodeCount > 300000) {
            fail();
        }
        skipWhitespace();
        const character = jsonText[position];
        if (character === '"') {
            return parseString();
        }
        if (character === '{' || character === '[') {
            const isArray = character === '[', parsedContainer = isArray ? [] : Object.create(null), seenKeys = new Set();
            position++;
            skipWhitespace();
            if (jsonText[position] === (isArray ? ']' : '}')) {
                position++;
                return parsedContainer;
            }
            while (true) {
                skipWhitespace();
                let key;
                if (!isArray) {
                    if (jsonText[position] !== '"') {
                        fail();
                    }
                    key = parseString();
                    if (seenKeys.has(key)) {
                        fail();
                    }
                    seenKeys.add(key);
                    skipWhitespace();
                    if (jsonText[position++] !== ':') {
                        fail();
                    }
                }
                const parsedItem = parseValue(depth + 1);
                if (isArray)
                    parsedContainer.push(parsedItem);
                else
                    parsedContainer[key] = parsedItem;
                skipWhitespace();
                const separator = jsonText[position++];
                if (separator === (isArray ? ']' : '}')) {
                    return parsedContainer;
                }
                if (separator !== ',') {
                    fail();
                }
            }
        }
        for (const [token, result] of [['true', true], ['false', false], ['null', null]])
            if (jsonText.startsWith(token, position)) {
                position += token.length;
                return result;
            }
        const numberMatch = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(jsonText.slice(position));
        if (!numberMatch) {
            fail();
        }
        position += numberMatch[0].length;
        const numericValue = Number(numberMatch[0]);
        if (!Number.isFinite(numericValue)) {
            fail();
        }
        return /[.eE]/.test(numberMatch[0]) ? new DecimalOrExponentToken(numericValue) : numericValue;
    }
    const parsedContainer = parseValue(0);
    skipWhitespace();
    if (position !== jsonText.length) {
        fail();
    }
    return parsedContainer;
}
function snapshotRows(input) {
    let nodes = 0;
    function copy(value, depth = 0) {
        if (depth > 8 || ++nodes > 1000) {
            fail();
        }
        if (value === null || typeof value === 'boolean') {
            return value;
        }
        if (typeof value === 'string') {
            text(value, MAX * 2, true);
            return value;
        }
        if (typeof value === 'number') {
            if (!Number.isFinite(value)) {
                fail();
            }
            return value;
        }
        if (typeof value !== 'object' || Object.getOwnPropertySymbols(value).length) {
            fail();
        }
        const array = Array.isArray(value);
        if (!array && ![Object.prototype, null].includes(Object.getPrototypeOf(value))) {
            fail();
        }
        const fields = Object.getOwnPropertyDescriptors(value), out = array ? [] : {};
        if (array && (value.length > 60 || Object.keys(fields).length !== value.length + 1)) {
            fail();
        }
        for (const [key, d] of Object.entries(fields)) {
            if (array && key === 'length') {
                continue;
            }
            if (!('value' in d) || !d.enumerable || ['__proto__', 'constructor', 'prototype'].includes(key)) {
                fail();
            }
            if (array && !/^(0|[1-9]\d*)$/.test(key)) {
                fail();
            }
            out[key] = copy(d.value, depth + 1);
        }
        return out;
    }
    const rows = copy(input);
    if (!Array.isArray(rows) || rows.length > 60) {
        fail();
    }
    let total = 0;
    return rows.map(row => {
        if (!exact(row, ['provider', 'model', 'replay_key', 'response_base64'])
            || !(row.provider === 'openai' && row.model === OPENAI || row.provider === 'cohere' && row.model === COHERE)
            || typeof row.replay_key !== 'string' || !/^[a-f0-9]{64}$/.test(row.replay_key)
            || typeof row.response_base64 !== 'string' || row.response_base64.length > Math.ceil(MAX / 3) * 4)
            fail();
        const response = Buffer.from(row.response_base64, 'base64');
        if (response.toString('base64') !== row.response_base64 || response.length > MAX || (total += response.length) > 67108864) {
            fail();
        }
        return { provider: row.provider, model: row.model, replay_key: row.replay_key, response };
    });
}
function prepare(kind, body) {
    const request = parse(body, kind === 'embedding' ? 65536 : 300000);
    let provider, model, payload, identity, context;
    if (kind === 'embedding') {
        if (!exact(request, ['model', 'dimensions', 'encoding_format', 'input']) || request.model !== OPENAI || request.dimensions !== 1536 || request.encoding_format !== 'float'
            || !Array.isArray(request.input) || request.input.length < 1 || request.input.length > 8)
            fail();
        const texts = request.input.map(v => text(v, 8192));
        if (texts.reduce((n, v) => n + Buffer.byteLength(v), 0) > 32768) {
            fail();
        }
        provider = 'openai';
        model = OPENAI;
        // Python retains the native request object's insertion order for this payload.
        payload = request;
        identity = { input_sha256: texts.map(hash) };
        context = texts.length;
    }
    else {
        if (!exact(request, ['profile', 'query', 'candidates'])) {
            fail();
        }
        const profile = request.profile;
        const fields = ['profile_id', 'provider', 'model', 'model_revision', 'score_kind', 'score_direction', 'preprocessing_revision', 'truncation_policy'];
        if (!exact(profile, fields) || fields.some(key => typeof profile[key] !== 'string')
            || profile.provider !== 'cohere' || profile.model !== COHERE
            || profile.score_kind !== 'relevance_score'
            || profile.score_direction !== 'higher_is_better' || profile.truncation_policy !== 'reject')
            fail();
        const query = text(request.query, 8192), rows = request.candidates;
        if (!Array.isArray(rows) || rows.length < 1 || rows.length > 40) {
            fail();
        }
        const ids = [], texts = [];
        for (const row of rows) {
            if (!exact(row, ['candidate_id', 'text'])) {
                fail();
            }
            ids.push(text(row.candidate_id, 512));
            texts.push(text(row.text, 16384, true));
        }
        if (new Set(ids).size !== ids.length || Buffer.byteLength(query) + texts.reduce((n, v) => n + Buffer.byteLength(v), 0) > 262144) {
            fail();
        }
        provider = 'cohere';
        model = COHERE;
        context = ids;
        payload = { model, query, documents: texts, top_n: rows.length, max_tokens_per_doc: 4096 };
        identity = { query_sha256: hash(query), candidates: ids.map((candidate_id, i) => ({ candidate_id, text_sha256: hash(texts[i]) })), profile };
    }
    const replay_key = hash(encode({ provider, model, identity, payload_sha256: hash(encode(payload)) }));
    return { provider, model, replay_key, context };
}
function mapResponse(raw, request, cap) {
    const response = parse(raw, cap);
    if (!object(response)) {
        fail();
    }
    if (request.provider === 'openai') {
        if (response.model !== OPENAI || !Array.isArray(response.data) || response.data.length !== request.context) {
            fail();
        }
        response.data.forEach((row, index) => {
            if (!object(row) || count(row.index) !== index || !Array.isArray(row.embedding) || row.embedding.length !== 1536) {
                fail();
            }
            const norm = Math.sqrt(row.embedding.reduce((sum, component) => {
                const numericValue = finite(component);
                return sum + numericValue * numericValue;
            }, 0));
            if (!Number.isFinite(norm) || Math.abs(norm - 1) > .001) {
                fail();
            }
        });
        if (response.usage !== undefined && response.usage !== null) {
            if (!exact(response.usage, ['prompt_tokens', 'total_tokens']) || count(response.usage.total_tokens) < count(response.usage.prompt_tokens)) {
                fail();
            }
        }
        return encode(response);
    }
    if (response.model !== undefined && response.model !== COHERE || !Array.isArray(response.results) || response.results.length !== request.context.length) {
        fail();
    }
    const scores = new Map();
    let previous = Infinity;
    for (const row of response.results) {
        if (!object(row)) {
            fail();
        }
        const index = count(row.index), score = finite(row.relevance_score);
        if (index >= request.context.length || scores.has(index) || score < 0 || score > 1 || score > previous) {
            fail();
        }
        scores.set(index, score);
        previous = score;
    }
    if (response.meta !== undefined && response.meta !== null) {
        if (!object(response.meta)) {
            fail();
        }
        const usage = response.meta.billed_units;
        if (usage !== undefined && usage !== null) {
            if (!object(usage)) {
                fail();
            }
            for (const value of Object.values(usage))
                if (value !== null) {
                    const n = finite(value);
                    if (n < 0 || n > 2147483647) {
                        fail();
                    }
                }
        }
    }
    return encode(request.context.map((candidate_id, index) => ({ candidate_id, raw_score: scores.get(index) })));
}
export function create_provider_replay(recordings) {
    let rows;
    try {
        rows = snapshotRows(recordings);
    }
    catch {
        fail();
    }
    let cursor = 0, inflight = false;
    function admission(options) {
        if (!options || typeof options.deadline !== 'number' || !Number.isFinite(options.deadline)
            || !Number.isInteger(options.max_response_bytes)
            || options.max_response_bytes < 1 || options.max_response_bytes > MAX
            || options.signal !== undefined && !(options.signal instanceof AbortSignal))
            fail();
        if (options.signal?.aborted) {
            fail('cancelled');
        }
        if (performance.now() / 1000 >= options.deadline) {
            fail('deadline_exceeded');
        }
    }
    async function transport(kind, body, options) {
        let entered = false;
        try {
            if (!options || ![Object.prototype, null].includes(Object.getPrototypeOf(options)) || Object.getOwnPropertySymbols(options).length) {
                fail();
            }
            const descriptors = Object.getOwnPropertyDescriptors(options);
            if (Object.entries(descriptors).some(([key, d]) => !['deadline', 'signal', 'max_response_bytes'].includes(key) || !('value' in d) || !d.enumerable)) {
                fail();
            }
            options = { ...options };
            admission(options);
            if (inflight) {
                fail('concurrent_dispatch');
            }
            inflight = true;
            entered = true;
            const request = prepare(kind, body), row = rows[cursor];
            if (!row) {
                fail('replay_missing');
            }
            if (row.provider !== request.provider || row.model !== request.model || row.replay_key !== request.replay_key) {
                fail('replay_mismatch');
            }
            if (row.response.length > options.max_response_bytes) {
                fail();
            }
            // Consume a matched send before mapping, just as Python ReplaySend does.
            cursor++;
            const encoded = mapResponse(row.response, request, options.max_response_bytes);
            if (encoded.length > options.max_response_bytes) {
                fail();
            }
            admission(options);
            return encoded;
        }
        catch (error) {
            if (error instanceof ProviderReplayError) {
                throw error;
            }
            fail();
        }
        finally {
            if (entered) {
                inflight = false;
            }
        }
    }
    return Object.freeze({
        embedding_transport: (body, options) => transport('embedding', body, options),
        rerank_transport: (body, options) => transport('rerank', body, options),
        assert_complete() {
            if (cursor !== rows.length) {
                fail('replay_unconsumed');
            }
        },
        snapshot() {
            return Object.freeze({
                records: rows.length,
                consumed: cursor,
                remaining: rows.length - cursor,
            });
        },
    });
}
