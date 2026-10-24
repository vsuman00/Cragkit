/** One explicit live observation through the native RK-r2 adapter. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import https from 'node:https';

const PROFILE = Object.freeze({
  profile_id: 'cohere_v5fast_probe_v1', provider: 'cohere', model: 'rerank-v5.0-fast',
  model_revision: 'mutable_alias:rerank-v5.0-fast', score_kind: 'relevance_score',
  score_direction: 'higher_is_better', preprocessing_revision: 'ascii_short_probe_v1',
  truncation_policy: 'reject',
});
const observation = {
  state: 'failed', runtime: 'node', profile: PROFILE, http_status: null,
  provider_calls: 0, synthetic: false, billed_input_tokens: null, observed_ms: 0,
  request_id_present: false, api_version: '2', processed_tokens: null,
  provider_truncation: 'unknown', weight_revision: 'mutable_alias',
  admission_pair_upper_usd: 2 * 3 * 32768 * 0.02 / 1000000,
};
let errorCode = 'live_opt_in_required';
let started;

function readKey() {
  const home = os.homedir();
  for (const ancestor of [path.join(home, '.config'), path.join(home, '.config', 'cragkit')]) {
    const info = fs.lstatSync(ancestor);
    if (!info.isDirectory() || info.isSymbolicLink() || info.uid !== process.getuid()) throw new Error();
  }
  const directory = path.join(home, '.config', 'cragkit', 'cohere');
  const parent = fs.lstatSync(directory);
  if (!parent.isDirectory() || parent.isSymbolicLink() || parent.uid !== process.getuid() || (parent.mode & 0o777) !== 0o700) throw new Error();
  const filename = path.join(directory, 'api-key');
  const before = fs.lstatSync(filename);
  if (!before.isFile() || before.isSymbolicLink() || before.uid !== process.getuid() || (before.mode & 0o777) !== 0o600 || before.size < 1 || before.size > 4096) throw new Error();
  const fd = fs.openSync(filename, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  try {
    const current = fs.fstatSync(fd);
    if (!current.isFile() || current.uid !== process.getuid() || (current.mode & 0o777) !== 0o600 || current.size < 1 || current.size > 4096 || current.dev !== before.dev || current.ino !== before.ino) throw new Error();
    const buffer = Buffer.alloc(4097);
    const count = fs.readSync(fd, buffer, 0, buffer.length, 0);
    if (count < 1 || count > 4096 || buffer.subarray(0, count).some(byte => byte > 127)) throw new Error();
    const key = buffer.subarray(0, count).toString('ascii').trim();
    if (!key || !/^[\x21-\x7e]+$/.test(key)) throw new Error();
    if (key.startsWith('sk-proj-') || key.startsWith('sk-svcacct-')) { errorCode = 'credential_provider_mismatch'; throw new Error(); }
    return key;
  } finally { fs.closeSync(fd); }
}

function shortASCII(value) {
  return typeof value === 'string' && value.length > 0 && /^[\x00-\x7f]*$/.test(value) && Buffer.byteLength(value, 'utf8') <= 256;
}

async function main() {
  if (process.argv.length !== 3 || process.argv[2] !== '--allow-live') throw new Error();
  errorCode = 'admission_failed';
  if (!(observation.admission_pair_upper_usd < 0.01)) throw new Error();
  errorCode = 'fixture_invalid';
  const {sample} = JSON.parse(fs.readFileSync(new URL('../contracts/fixtures/reranking.json', import.meta.url), 'utf8'));
  if (!shortASCII(sample.query) || !Array.isArray(sample.candidates) || sample.candidates.length < 1 || sample.candidates.length > 3 || sample.candidates.some(item => !shortASCII(item.text))) throw new Error();
  errorCode = 'adapter_unavailable';
  const {RerankingAdapter} = await import('../packages/typescript/dist/reranking.js');
  errorCode = 'credential_invalid';
  const key = readKey();
  const transport = async (body, options) => {
    errorCode = 'request_invalid';
    const request = JSON.parse(Buffer.from(body).toString('utf8'));
    if (request.profile.model !== PROFILE.model || request.query !== sample.query || request.candidates.length !== sample.candidates.length || request.candidates.some((item, index) => item.candidate_id !== sample.candidates[index].candidate_id || item.text !== sample.candidates[index].text)) throw new Error();
    const payload = Buffer.from(JSON.stringify({model: PROFILE.model, query: request.query, documents: request.candidates.map(item => item.text), top_n: request.candidates.length, max_tokens_per_doc: 1024}));
    const milliseconds = Math.min(20000, Math.max(1, Math.floor((options.deadline - performance.now() / 1000) * 1000)));
    errorCode = 'transport_failed';
    const raw = await new Promise((resolve, reject) => {
      let settled = false;
      const finish = (error, value) => { if (settled) return; settled = true; clearTimeout(timer); error ? reject(new Error()) : resolve(value); };
      const req = https.request({hostname: 'api.cohere.com', port: 443, path: '/v2/rerank', method: 'POST', rejectUnauthorized: true, agent: false, signal: options.signal, headers: {'Content-Type': 'application/json', 'Authorization': `Bearer ${key}`, 'Content-Length': payload.length}}, response => {
        observation.http_status = response.statusCode ?? null;
        observation.request_id_present = typeof response.headers['x-request-id'] === 'string' && response.headers['x-request-id'].length > 0;
        const chunks = [];
        let bytes = 0;
        response.on('data', chunk => {
          bytes += chunk.length;
          if (bytes > Math.min(65536, options.max_response_bytes)) { errorCode = 'response_too_large'; response.destroy(); req.destroy(); finish(true); return; }
          chunks.push(chunk);
        });
        response.on('error', () => finish(true));
        response.on('aborted', () => finish(true));
        response.on('end', () => {
          if (observation.http_status !== 200) { errorCode = 'http_failure'; finish(true); return; }
          finish(false, Buffer.concat(chunks));
        });
      });
      const timer = setTimeout(() => { errorCode = 'request_timeout'; req.destroy(); finish(true); }, milliseconds);
      req.on('error', () => finish(true));
      observation.provider_calls += 1;
      req.end(payload);
    });
    errorCode = 'response_invalid';
    const parsed = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(raw));
    observation.request_id_present ||= typeof parsed.id === 'string' && parsed.id.length > 0;
    const billed = parsed.meta?.billed_units?.input_tokens;
    if (Number.isSafeInteger(billed) && billed >= 0) observation.billed_input_tokens = billed;
    if (!Array.isArray(parsed.results) || parsed.results.length !== request.candidates.length) throw new Error();
    const scores = parsed.results.map(item => {
      if (!Number.isInteger(item.index) || item.index < 0 || item.index >= request.candidates.length || typeof item.relevance_score !== 'number' || !Number.isFinite(item.relevance_score)) throw new Error();
      return {candidate_id: request.candidates[item.index].candidate_id, raw_score: item.relevance_score};
    });
    return Buffer.from(JSON.stringify(scores));
  };
  const adapter = new RerankingAdapter(transport, {profile: PROFILE, allow_live: true});
  started = performance.now();
  errorCode = 'adapter_failed';
  const result = await adapter.rank(sample.query, sample.candidates, {deadline: started / 1000 + 20, signal: AbortSignal.timeout(20000), max_provider_calls: 1, allow_fallback: false});
  if (result.synthetic || result.degraded || result.truncations.length || result.provider_calls !== 1 || observation.provider_calls !== 1) throw new Error();
  Object.assign(observation, {state: 'passed', order: result.order, scores: result.scores});
}

try { await main(); } catch { observation.error_code = errorCode; process.exitCode = 1; }
if (started !== undefined) observation.observed_ms = Math.round((performance.now() - started) * 1000) / 1000;
console.log(JSON.stringify(observation));
