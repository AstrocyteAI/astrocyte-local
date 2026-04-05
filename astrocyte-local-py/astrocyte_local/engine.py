"""LocalEngineProvider — implements the Astrocyte EngineProvider SPI.

Plugs the Context Tree + FTS5 search into the Astrocyte framework with
full policy enforcement (PII, rate limits, quotas, access control, hooks).

Registers via entry point: astrocyte.engine_providers → local
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from astrocyte_local.context_tree import ContextTree
from astrocyte_local.search import SearchEngine, SearchHit

# Lazy import to avoid hard dependency on astrocyte at module level
try:
    from astrocyte.types import (
        EngineCapabilities,
        ForgetRequest,
        ForgetResult,
        HealthStatus,
        MemoryHit,
        RecallRequest,
        RecallResult,
        RecallTrace,
        ReflectRequest,
        ReflectResult,
        RetainRequest,
        RetainResult,
    )
except ImportError:
    # Allow standalone usage without astrocyte installed
    pass


class LocalEngineProvider:
    """Astrocyte EngineProvider backed by local markdown files + SQLite FTS5.

    Usage with Astrocyte framework:
        from astrocyte import Astrocyte
        from astrocyte_local import LocalEngineProvider

        brain = Astrocyte.from_config("astrocyte.yaml")
        brain.set_engine_provider(LocalEngineProvider(root=".astrocyte"))

    Standalone usage:
        provider = LocalEngineProvider(root=".astrocyte")
        result = await provider.retain(RetainRequest(content="test", bank_id="project"))
    """

    SPI_VERSION: ClassVar[int] = 1

    def __init__(self, root: str | Path = ".astrocyte") -> None:
        self.root = Path(root)
        self._tree = ContextTree(self.root)
        self._search = SearchEngine(self.root / "_search.db")

        # Build index from existing files on startup
        self._search.build_index(self._tree)

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            supports_reflect=False,  # Reflect needs LLM — handled by Astrocyte fallback
            supports_forget=True,
            supports_semantic_search=False,  # No vectors — FTS5 keyword only
            supports_keyword_search=True,
            supports_tags=True,
            supports_metadata=True,
        )

    async def health(self) -> HealthStatus:
        total = self._tree.count()
        return HealthStatus(
            healthy=True,
            message=f"Local Context Tree: {total} memories, root={self.root}",
        )

    async def retain(self, request: RetainRequest) -> RetainResult:
        """Store content as a markdown file in the Context Tree."""
        # Infer domain from tags or default to "general"
        domain = "general"
        if request.tags:
            domain = request.tags[0]  # Use first tag as domain hint

        entry = self._tree.store(
            content=request.content,
            bank_id=request.bank_id,
            domain=domain,
            tags=request.tags or [],
            occurred_at=request.occurred_at.isoformat() if request.occurred_at else None,
            source=request.source,
            metadata=dict(request.metadata) if request.metadata else {},
        )

        # Update search index
        self._search.add_document(entry)

        return RetainResult(
            stored=True,
            memory_id=entry.id,
        )

    async def recall(self, request: RecallRequest) -> RecallResult:
        """Search local memory using FTS5."""
        hits_raw = self._search.search(
            query=request.query,
            bank_id=request.bank_id,
            limit=request.max_results,
            tags=request.tags,
        )

        hits = [self._to_memory_hit(h, request.bank_id) for h in hits_raw]

        # Record recall on matching entries
        for h in hits_raw:
            self._tree.record_recall(h.id)

        return RecallResult(
            hits=hits,
            total_available=len(hits),
            truncated=False,
            trace=RecallTrace(
                strategies_used=["fts5"],
                total_candidates=len(hits),
                fusion_method="bm25",
            ),
        )

    async def reflect(self, request: ReflectRequest) -> ReflectResult:
        """Not supported — Astrocyte framework handles reflect via LLM fallback."""
        raise NotImplementedError(
            "LocalEngineProvider does not support reflect. "
            "Use with Astrocyte framework (fallback_strategy='local_llm') for reflect."
        )

    async def forget(self, request: ForgetRequest) -> ForgetResult:
        """Delete memories from Context Tree and search index."""
        deleted = 0

        if request.scope == "all":
            # Delete all entries in the bank
            entries = self._tree.list_entries(request.bank_id)
            for entry in entries:
                if self._tree.delete(entry.id):
                    self._search.remove_document(entry.id)
                    deleted += 1
        elif request.memory_ids:
            for mem_id in request.memory_ids:
                if self._tree.delete(mem_id):
                    self._search.remove_document(mem_id)
                    deleted += 1

        return ForgetResult(deleted_count=deleted)

    def _to_memory_hit(self, hit: SearchHit, bank_id: str) -> MemoryHit:
        """Convert a SearchHit to Astrocyte MemoryHit."""
        return MemoryHit(
            text=hit.text,
            score=hit.score,
            fact_type=hit.fact_type,
            tags=hit.tags,
            memory_id=hit.id,
            bank_id=bank_id,
            memory_layer=hit.memory_layer,
            metadata=hit.metadata,
            occurred_at=None,  # Would need datetime parsing
        )
