import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { create_provider_replay, ProviderReplayError } from '../provider_replay.mjs';
const fixture = JSON.parse(readFileSync(new URL('../../contracts/fixtures/provider_replay.json', import.meta.url), 'utf8'));
const rows = () => structuredClone(fixture.calls.map(call => call.recording));
const body = call => Buffer.from(JSON.stringify(call.native_body));
const options = (changes = {}) => ({ deadline: performance.now() / 1000 + 10, max_response_bytes: 2097152, ...changes });
const error = code => value => value instanceof ProviderReplayError && value.message === code && !value.cause;
const execute = (replay, call, opts = options()) => replay[call.transport === 'embedding' ? 'embedding_transport' : 'rerank_transport'](body(call), opts);
test('shared Python fixture preserves Unicode mapping, one cursor and duplicate keys', async () => {
    const replay = create_provider_replay(rows());
    for (const call of fixture.calls) {
        const result = JSON.parse(Buffer.from(await execute(replay, call)).toString('utf8'));
        assert.deepEqual(result, call.mapped_response);
    }
    replay.assert_complete();
    assert.deepEqual(replay.snapshot(), { records: 3, consumed: 3, remaining: 0 });
    assert.equal(Object.isFrozen(replay.snapshot()), true);
    assert.equal(Object.isFrozen(replay), true);
    await assert.rejects(execute(replay, fixture.calls[0]), error('replay_missing'));
});
test('snapshot isolates caller tape mutations and returned buffers', async () => {
    const tape = rows(), replay = create_provider_replay(tape);
    tape[0].response_base64 = '';
    tape.reverse();
    const result = await execute(replay, fixture.calls[0]);
    result.fill(0);
    await execute(replay, fixture.calls[1]);
    assert.deepEqual(JSON.parse(Buffer.from(await execute(replay, fixture.calls[2])).toString()), fixture.calls[2].mapped_response);
});
test('reordered or altered calls fail without consuming the next record', async () => {
    const replay = create_provider_replay(rows());
    await assert.rejects(execute(replay, fixture.calls[1]), error('replay_mismatch'));
    const changed = structuredClone(fixture.calls[0]);
    changed.native_body.input[0] += ' changed';
    await assert.rejects(execute(replay, changed), error('replay_mismatch'));
    assert.equal(replay.snapshot().consumed, 0);
    await execute(replay, fixture.calls[0]);
    assert.throws(() => replay.assert_complete(), error('replay_unconsumed'));
});
for (const mutate of [
    tape => tape[0].extra = true, tape => tape[0].model = 'wrong', tape => tape[0].provider = 'other',
    tape => tape[0].replay_key = 'private payload', tape => tape[0].response_base64 += '\n',
    tape => tape[0].response_base64 = '====', tape => tape.push(...Array(60).fill(tape[0])),
    tape => Object.defineProperty(tape[0], 'model', { get() { throw Error('private getter must not run'); } }),
    tape => tape[0][Symbol('private')] = true, tape => delete tape[0],
])
    test('unsafe or noncanonical tape rejected with a fixed diagnostic', () => {
        const tape = rows();
        mutate(tape);
        assert.throws(() => create_provider_replay(tape), error('provider_mapping_invalid'));
    });
test('input getters are rejected without invocation', () => {
    let called = false;
    const row = { ...rows()[0] };
    Object.defineProperty(row, 'model', { enumerable: true, get() { called = true; return 'private'; } });
    assert.throws(() => create_provider_replay([row]), error('provider_mapping_invalid'));
    assert.equal(called, false);
});
for (const opts of [() => options({ deadline: 0 }), () => options({ signal: AbortSignal.abort('private cancellation') }),
    () => options({ max_response_bytes: 0 }), () => options({ max_response_bytes: 2097153 }), () => options({ deadline: NaN })]) {
    test('deadline, abort and response cap admission never consumes tape', async () => {
        const replay = create_provider_replay(rows());
        await assert.rejects(execute(replay, fixture.calls[0], opts()), ProviderReplayError);
        assert.equal(replay.snapshot().consumed, 0);
    });
}
test('response byte refusal leaves matched record unconsumed', async () => {
    const replay = create_provider_replay(rows());
    await assert.rejects(execute(replay, fixture.calls[0], options({ max_response_bytes: 1 })), error('provider_mapping_invalid'));
    assert.equal(replay.snapshot().consumed, 0);
});
for (const raw of ['{"model":1,"model":2}', '{"private":NaN}', '{"private":"\\ud800"}', '{', '\uFEFF{}']) {
    test('malformed native body is sanitized before cursor movement', async () => {
        const replay = create_provider_replay(rows());
        await assert.rejects(replay.embedding_transport(Buffer.from(raw), options()), error('provider_mapping_invalid'));
        assert.equal(replay.snapshot().consumed, 0);
    });
}
function invalidResponse(callIndex, mutate) {
    const tape = rows().slice(callIndex, callIndex + 1), response = JSON.parse(Buffer.from(tape[0].response_base64, 'base64'));
    mutate(response);
    tape[0].response_base64 = Buffer.from(JSON.stringify(response)).toString('base64');
    return tape;
}
for (const mutate of [response => response.model = 'wrong', response => response.data[0].embedding = [1],
    response => response.data[0].embedding[0] = 2, response => response.data[0].embedding[0] = true,
    response => response.data[0].index = 1, response => response.usage = { prompt_tokens: 2, total_tokens: 1 },
    response => response.usage = { prompt_tokens: 1, total_tokens: 1, extra: 1 }]) {
    test('OpenAI malformed response consumes dispatched record and fails strict mapping', async () => {
        const replay = create_provider_replay(invalidResponse(0, mutate));
        await assert.rejects(execute(replay, fixture.calls[0]), error('provider_mapping_invalid'));
        assert.equal(replay.snapshot().consumed, 1);
    });
}
for (const mutate of [response => response.results.pop(), response => response.results[1].index = response.results[0].index,
    response => response.results[0].relevance_score = 2, response => response.results.reverse(),
    response => response.meta = { billed_units: { input_tokens: -1 } }]) {
    test('Cohere incomplete, duplicate, invalid and non-descending results fail strict mapping', async () => {
        const replay = create_provider_replay(invalidResponse(1, mutate));
        await assert.rejects(execute(replay, fixture.calls[1]), error('provider_mapping_invalid'));
    });
}
test('integer index spelling and duplicate response JSON keys match Python rejection', async () => {
    for (const transform of [raw => raw.replace('"index":0', '"index":0.0'), raw => raw.replace('"model":', '"model":"duplicate","model":')]) {
        const tape = rows().slice(0, 1);
        tape[0].response_base64 = Buffer.from(transform(Buffer.from(tape[0].response_base64, 'base64').toString())).toString('base64');
        await assert.rejects(execute(create_provider_replay(tape), fixture.calls[0]), error('provider_mapping_invalid'));
    }
});
test('empty tape completes but cannot dispatch', async () => {
    const replay = create_provider_replay([]);
    replay.assert_complete();
    await assert.rejects(execute(replay, fixture.calls[0]), error('replay_missing'));
});
test('native Node adapters consume the shared tape without a Python process or provider call', async () => {
    const { EmbeddingAdapter, OPENAI_PROFILE } = await import('../../packages/typescript/dist/embeddings.js');
    const { RerankingAdapter } = await import('../../packages/typescript/dist/reranking.js');
    const replay = create_provider_replay(rows());
    const embedder = new EmbeddingAdapter(
        replay.embedding_transport,
        { name: 'cl100k_base', count: () => 3 },
        { profile: OPENAI_PROFILE, policy: { allow_live: true, max_cost_usd: .01, usd_per_million_tokens: .02 } },
    );
    const first = await embedder.embed_query(fixture.calls[0].native_body.input[0], { deadline: options().deadline });
    assert.equal(first.usage.total_tokens, 3);
    assert.equal(first.synthetic, false);
    assert.equal(first.vectors[0].length, 1536);
    const call = fixture.calls[1], reranker = new RerankingAdapter(replay.rerank_transport, { profile: call.native_body.profile, allow_live: true });
    const ranked = await reranker.rank(call.native_body.query, call.native_body.candidates, { deadline: options().deadline });
    assert.deepEqual(ranked.scores, call.mapped_response);
    assert.equal(ranked.synthetic, false);
    await embedder.embed_query(fixture.calls[2].native_body.input[0], { deadline: options().deadline });
    replay.assert_complete();
});
test('unsafe options and forged private diagnostics cannot escape replay', async () => {
    const replay = create_provider_replay(rows());
    let invoked = false;
    const unsafe = { ...options() };
    Object.defineProperty(unsafe, 'deadline', { get() { invoked = true; throw Error('private payload'); }, enumerable: true });
    await assert.rejects(execute(replay, fixture.calls[0], unsafe), error('provider_mapping_invalid'));
    assert.equal(invoked, false);
    assert.equal(replay.snapshot().consumed, 0);
    assert.equal(new ProviderReplayError('private payload').message, 'provider_mapping_invalid');
});
