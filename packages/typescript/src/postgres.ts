/** Optional native PostgreSQL entry point; opening a resource is explicit. */
export { PoolResource, parse_pool_config, now } from './postgres-pool.js';
export type { PoolConfig, LeaseOptions } from './postgres-pool.js';
export { PostgresIndexer } from './ingestion.js';
export type { IngestionReceipt, IngestOptions, WriteAuthorizer } from './ingestion.js';
export { PostgresLifecycle } from './lifecycle.js';
export type { LifecycleReceipt, LifecycleOptions, LifecycleAuthorizer } from './lifecycle.js';
export { PostgresRetriever } from './retrieval.js';
export type { RetrieverOptions, EvidenceConfiguration } from './hybrid.js';

export { PostgresVectorIndexer } from './vector-ingestion.js';
export type { VectorIngestionReceipt } from './vector-ingestion.js';
