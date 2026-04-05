"""LocalEngineProvider — implements the Astrocyte EngineProvider SPI.

Plugs the Context Tree + FTS5 search into the Astrocyte framework with
full policy enforcement (PII, rate limits, quotas, access control, hooks).

Features:
- LLM-curated retain (optional): LLM decides domain, action, memory_layer
- Tiered retrieval (optional): cache → FTS5 → LLM-guided reformulation

Registers via entry point: astrocyte.engine_providers → local
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from astrocyte_local.context_tree import ContextTree
from astrocyte_local.search import SearchEngine, SearchHit
from astrocyte_local.tiered_retrieval import LocalRecallCache, LocalTieredRetriever

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

    With curated retain (requires LLM):
        from astrocyte.testing.in_memory import MockLLMProvider
        provider = LocalEngineProvider(root=".astrocyte", llm_provider=MockLLMProvider())

    With tiered retrieval:
        provider = LocalEngineProvider(root=".astrocyte", enable_cache=True, enable_tiered=True)
    """

    SPI_VERSION: ClassVar[int] = 1

    def __init__(
        self,
        root: str | Path = ".astrocyte",
        *,
        llm_provider: object | None = None,
        enable_curated_retain: bool = False,
        enable_cache: bool = True,
        enable_tiered: bool = False,
        cache_max_entries: int = 128,
        cache_ttl_seconds: float = 120.0,
        tiered_min_results: int = 2,
        tiered_max_tier: int = 1,
    ) -> None:
        self.root = Path(root)
        self._tree = ContextTree(self.root)
        self._search = SearchEngine(self.root / "_search.db")
        self._llm = llm_provider
        self._enable_curated_retain = enable_curated_retain and llm_provider is not None

        # Recall cache
        self._cache = (
            LocalRecallCache(
                max_entries=cache_max_entries,
                ttl_seconds=cache_ttl_seconds,
            )
            if enable_cache
            else None
        )

        # Tiered retrieval
        max_tier = tiered_max_tier
        if enable_tiered and llm_provider:
            max_tier = max(max_tier, 2)  # Enable LLM-guided tier
        self._tiered = (
            LocalTieredRetriever(
                search=self._search,
                cache=self._cache,
                llm_provider=llm_provider if enable_tiered else None,
                min_results=tiered_min_results,
                max_tier=max_tier,
            )
            if (enable_cache or enable_tiered)
            else None
        )

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
        features = []
        if self._enable_curated_retain:
            features.append("curated-retain")
        if self._cache:
            features.append(f"cache({self._cache.size()})")
        if self._tiered and self._tiered.max_tier >= 2:
            features.append("tiered-llm")
        feature_str = f" [{', '.join(features)}]" if features else ""
        return HealthStatus(
            healthy=True,
            message=f"Local Context Tree: {total} memories, root={self.root}{feature_str}",
        )

    async def retain(self, request: RetainRequest) -> RetainResult:
        """Store content. Uses LLM curation if enabled, else mechanical store."""
        # ── Curated retain path ──
        if self._enable_curated_retain and self._llm:
            from astrocyte_local.curated_retain import curate_local_retain

            decision = await curate_local_retain(
                content=request.content,
                bank_id=request.bank_id,
                tree=self._tree,
                search=self._search,
                llm_provider=self._llm,
            )

            if decision.action == "skip":
                return RetainResult(
                    stored=False,
                    error="LLM curation: skipped (redundant)",
                    retention_action="skip",
                    curated=True,
                )

            if decision.action == "delete" and decision.target_id:
                self._tree.delete(decision.target_id)
                self._search.remove_document(decision.target_id)

            if decision.action == "update" and decision.target_id:
                self._tree.update(decision.target_id, decision.content)
                # Rebuild index for updated entry
                self._search.build_index(self._tree, bank_id=request.bank_id)
                return RetainResult(
                    stored=True,
                    memory_id=decision.target_id,
                    retention_action="update",
                    curated=True,
                    memory_layer=decision.memory_layer,
                )

            # ADD or MERGE — store as new entry
            entry = self._tree.store(
                content=decision.content,
                bank_id=request.bank_id,
                domain=decision.domain,
                tags=request.tags or [],
                memory_layer=decision.memory_layer,
                occurred_at=request.occurred_at.isoformat() if request.occurred_at else None,
                source=request.source,
                metadata=dict(request.metadata) if request.metadata else {},
            )
            self._search.add_document(entry)

            # Invalidate cache for this bank
            if self._cache:
                self._cache.invalidate_bank(request.bank_id)

            return RetainResult(
                stored=True,
                memory_id=entry.id,
                retention_action=decision.action,
                curated=True,
                memory_layer=decision.memory_layer,
            )

        # ── Mechanical retain path (no LLM) ──
        domain = "general"
        if request.tags:
            domain = request.tags[0]

        entry = self._tree.store(
            content=request.content,
            bank_id=request.bank_id,
            domain=domain,
            tags=request.tags or [],
            occurred_at=request.occurred_at.isoformat() if request.occurred_at else None,
            source=request.source,
            metadata=dict(request.metadata) if request.metadata else {},
        )
        self._search.add_document(entry)

        # Invalidate cache for this bank
        if self._cache:
            self._cache.invalidate_bank(request.bank_id)

        return RetainResult(stored=True, memory_id=entry.id)

    async def recall(self, request: RecallRequest) -> RecallResult:
        """Search local memory. Uses tiered retrieval if enabled."""
        # ── Tiered retrieval path ──
        if self._tiered:
            hits_raw, tier_used = await self._tiered.aretrieve(
                query=request.query,
                bank_id=request.bank_id,
                limit=request.max_results,
                tags=request.tags,
            )

            hits = [self._to_memory_hit(h, request.bank_id) for h in hits_raw]

            for h in hits_raw:
                self._tree.record_recall(h.id)

            return RecallResult(
                hits=hits,
                total_available=len(hits),
                truncated=False,
                trace=RecallTrace(
                    strategies_used=["fts5", "tiered"],
                    total_candidates=len(hits),
                    fusion_method="bm25",
                    tier_used=tier_used,
                    cache_hit=tier_used == 0,
                ),
            )

        # ── Standard FTS5 search ──
        hits_raw = self._search.search(
            query=request.query,
            bank_id=request.bank_id,
            limit=request.max_results,
            tags=request.tags,
        )

        hits = [self._to_memory_hit(h, request.bank_id) for h in hits_raw]

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

        # Invalidate cache
        if self._cache:
            self._cache.invalidate_bank(request.bank_id)

        return ForgetResult(deleted_count=deleted)

    def _to_memory_hit(self, hit: SearchHit, bank_id: str) -> MemoryHit:
        return MemoryHit(
            text=hit.text,
            score=hit.score,
            fact_type=hit.fact_type,
            tags=hit.tags,
            memory_id=hit.id,
            bank_id=bank_id,
            memory_layer=hit.memory_layer,
            metadata=hit.metadata,
            occurred_at=None,
        )
