"""Optional native PostgreSQL library entry point; resources open explicitly."""
from ._postgres_pool import PoolConfig, PoolResource, parse_pool_config
from .ingestion import IngestionReceipt, PostgresIndexer
from .lifecycle import LifecycleReceipt, PostgresLifecycle
from .retrieval import PostgresRetriever
from .vector_ingestion import PostgresVectorIndexer, VectorIngestionReceipt

__all__ = [
    "PoolConfig", "PoolResource", "parse_pool_config", "PostgresIndexer",
    "IngestionReceipt", "PostgresVectorIndexer", "VectorIngestionReceipt", "PostgresLifecycle", "LifecycleReceipt", "PostgresRetriever",
]
