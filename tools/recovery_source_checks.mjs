/** MRR-r1 installed Node source checks; private configuration arrives on stdin. */
import { createHash } from 'node:crypto';
import { realpath } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const requireCheck = value => { if (!value) throw Error('recovery_source_invalid'); };
const hash = value => createHash('sha256').update(value).digest('hex');

export async function runSourceChecks(configuration) {
    let reader;
    try {
        const { reader_config, sdk_root, tokenizer_path, expected } = configuration;
        const dist = await realpath(join(sdk_root, 'dist'));
        const sdk = Object.assign({}, ...await Promise.all(
            ['index', 'postgres-pool', 'requests', 'results', 'context', 'embeddings',
                'vector-ingestion', 'retrieval'].map(name => import(pathToFileURL(join(dist, name + '.js')).href))));
        reader = new sdk.PoolResource(sdk.parse_pool_config({ ...reader_config, max_size: 1,
            max_waiting: 1, acquire_timeout: 2, close_timeout: 5, release_timeout: 1 }));
        const counter = await sdk.Cl100kCounter.create(tokenizer_path);
        await reader.open();
        const retriever = new sdk.PostgresRetriever(reader, { mode: 'lexical', evidence_options: { counter } });
        const checks = {};
        for (const [name, document, principal, tenant, revision, allowed] of [
            ['allowed_exact_source', 'allowed', 'recovery-reader', 'recovery-tenant', '2', true],
            ['revoked_denied', 'revoked', 'recovery-reader', 'recovery-tenant', '2', false],
            ['foreign_tenant_denied', 'allowed', 'recovery-reader', 'recovery-foreign', '2', false],
            ['tombstone_denied', 'deleted', 'recovery-reader', 'recovery-tenant', '2', false],
            ['held_old_scope_denied', 'allowed', 'recovery-reader', 'recovery-tenant', '1', false],
        ]) {
            const request = sdk.parse_request({ request_id: 'recovery-' + name,
                query: 'support route', collection: 'recovery-tests',
                required_filters: [{ op: 'eq', field: 'document_id', value: document }],
                limits: { deadline_ms: 10000, max_candidates: 5, max_context_tokens: 2000 },
                output_profile: { renderer: 'cragkit.context.v2', tokenizer: 'cl100k_base',
                    counting_mode: 'strict', envelope_reserve_tokens: 128 } });
            const scope = sdk.parse_scope({ tenant_id: tenant, principal_id: principal,
                authorization_revision: revision, grant_ids: [] });
            const result = sdk.parse_result(await retriever.retrieve(request, { scope, deadline: sdk.now() + 10 }));
            requireCheck(result.execution === 'complete' && result.usage.provider_calls === 0);
            if (allowed) {
                requireCheck(result.evidence.length === 1);
                const evidence = result.evidence[0];
                const bytes = Buffer.from(expected.source);
                requireCheck(evidence.document_id === 'allowed' && evidence.collection === 'recovery-tests'
                    && evidence.revision_id === expected.revision_id && evidence.source_sha256 === hash(bytes)
                    && evidence.start_byte === 0 && evidence.end_byte === bytes.length
                    && Buffer.from(evidence.text).equals(bytes) && evidence.text_sha256 === hash(bytes));
            } else {
                requireCheck(result.evidence.length === 0 && result.context === '[]');
            }
            checks[name] = true;
        }
        return { revision: 'MRR-r1', runtime: 'node', checks, provider_http_calls: 0 };
    } finally {
        if (reader) await reader.close();
    }
}
