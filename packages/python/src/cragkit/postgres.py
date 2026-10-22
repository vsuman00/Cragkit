"""Optional native PostgreSQL library entry point; resources open explicitly."""
from ._postgres_pool import PoolConfig, PoolResource, parse_pool_config
from .ingestion import IngestionReceipt, PostgresIndexer
from .lifecycle import LifecycleReceipt, PostgresLifecycle
from .retrieval import PostgresRetriever

__all__ = [
    "PoolConfig", "PoolResource", "parse_pool_config", "PostgresIndexer",
    "IngestionReceipt", "PostgresLifecycle", "LifecycleReceipt", "PostgresRetriever",
]
