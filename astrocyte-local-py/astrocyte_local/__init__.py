"""Astrocyte Local — zero-infrastructure memory for AI coding agents.

Context Tree + SQLite FTS5 search. No database, no embeddings, no API keys.
Implements the Astrocyte EngineProvider SPI for framework integration.

Usage:
    from astrocyte_local import LocalEngineProvider
    from astrocyte import Astrocyte

    brain = Astrocyte.from_config("astrocyte.yaml")
    brain.set_engine_provider(LocalEngineProvider(root=".astrocyte"))
"""

from astrocyte_local.context_tree import ContextTree, MemoryEntry
from astrocyte_local.engine import LocalEngineProvider
from astrocyte_local.search import SearchEngine, SearchHit

__all__ = [
    "ContextTree",
    "MemoryEntry",
    "LocalEngineProvider",
    "SearchEngine",
    "SearchHit",
]
