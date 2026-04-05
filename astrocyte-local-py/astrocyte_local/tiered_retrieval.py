"""Tiered retrieval for local Context Tree — cache → FTS5 → LLM-guided.

3-tier progressive escalation adapted for file-based storage:
  Tier 0: In-memory result cache (exact/fuzzy query match)
  Tier 1: FTS5 keyword search (standard)
  Tier 2: LLM-guided query reformulation + FTS5 retry

Stops when sufficient results are found. No embeddings needed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from astrocyte_local.search import SearchEngine, SearchHit

if TYPE_CHECKING:
    from astrocyte.provider import LLMProvider


@dataclass
class _CacheEntry:
    query: str
    bank_id: str
    hits: list[SearchHit]
    timestamp: float


class LocalRecallCache:
    """Simple in-memory cache for local recall results.

    Keyed by (query_lowercase, bank_id). TTL-based expiry.
    Invalidated on retain (bank contents changed).
    """

    def __init__(self, max_entries: int = 128, ttl_seconds: float = 120.0) -> None:
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, _CacheEntry] = {}

    def get(self, query: str, bank_id: str) -> list[SearchHit] | None:
        key = f"{bank_id}:{query.lower().strip()}"
        entry = self._cache.get(key)
        if entry is None:
            return None

        # Check TTL
        if (time.monotonic() - entry.timestamp) > self.ttl_seconds:
            del self._cache[key]
            return None

        return entry.hits

    def put(self, query: str, bank_id: str, hits: list[SearchHit]) -> None:
        key = f"{bank_id}:{query.lower().strip()}"

        # LRU eviction
        while len(self._cache) >= self.max_entries:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]

        self._cache[key] = _CacheEntry(
            query=query,
            bank_id=bank_id,
            hits=hits,
            timestamp=time.monotonic(),
        )

    def invalidate_bank(self, bank_id: str) -> None:
        keys_to_remove = [k for k in self._cache if k.startswith(f"{bank_id}:")]
        for k in keys_to_remove:
            del self._cache[k]

    def invalidate_all(self) -> None:
        self._cache.clear()

    def size(self) -> int:
        return len(self._cache)


class LocalTieredRetriever:
    """3-tier progressive retrieval for local Context Tree.

    Tier 0: Cache hit (~0ms)
    Tier 1: FTS5 keyword search (~10ms)
    Tier 2: LLM reformulates query + FTS5 retry (~2-5s)
    """

    def __init__(
        self,
        search: SearchEngine,
        cache: LocalRecallCache | None = None,
        llm_provider: LLMProvider | None = None,
        min_results: int = 2,
        min_score: float = 0.3,
        max_tier: int = 1,
    ) -> None:
        self.search = search
        self.cache = cache
        self.llm = llm_provider
        self.min_results = min_results
        self.min_score = min_score
        self.max_tier = min(max_tier, 2)

    def retrieve(
        self,
        query: str,
        bank_id: str,
        *,
        limit: int = 10,
        tags: list[str] | None = None,
    ) -> tuple[list[SearchHit], int]:
        """Run tiered retrieval. Returns (hits, tier_used)."""

        # ── Tier 0: Cache ──
        if self.cache and self.max_tier >= 0:
            cached = self.cache.get(query, bank_id)
            if cached is not None:
                return cached[:limit], 0

        # ── Tier 1: FTS5 search ──
        hits: list[SearchHit] = []
        if self.max_tier >= 1:
            hits = self.search.search(query, bank_id, limit=limit, tags=tags)
            if self._sufficient(hits) or self.max_tier <= 1:
                if self.cache and hits:
                    self.cache.put(query, bank_id, hits)
                return hits, 1

        # ── Tier 2: LLM-guided reformulation ──
        if self.max_tier >= 2 and self.llm:
            import asyncio

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                if self.cache and hits:
                    self.cache.put(query, bank_id, hits)
                return hits if self.max_tier >= 1 else [], 1
            else:
                reformulated = asyncio.run(self._reformulate(query))
                if reformulated != query:
                    hits2 = self.search.search(reformulated, bank_id, limit=limit, tags=tags)
                    merged = self._merge_hits(hits if self.max_tier >= 1 else [], hits2)
                    if self.cache:
                        self.cache.put(query, bank_id, merged)
                    return merged[:limit], 2

        if self.cache and hits:
            self.cache.put(query, bank_id, hits)
        return hits[:limit], max(self.max_tier, 0)

    async def aretrieve(
        self,
        query: str,
        bank_id: str,
        *,
        limit: int = 10,
        tags: list[str] | None = None,
    ) -> tuple[list[SearchHit], int]:
        """Async version of retrieve — supports LLM reformulation natively."""

        # ── Tier 0: Cache ──
        if self.cache and self.max_tier >= 0:
            cached = self.cache.get(query, bank_id)
            if cached is not None:
                return cached[:limit], 0

        # ── Tier 1: FTS5 search ──
        hits: list[SearchHit] = []
        if self.max_tier >= 1:
            hits = self.search.search(query, bank_id, limit=limit, tags=tags)
            if self._sufficient(hits) or self.max_tier <= 1:
                # Cache whatever we found (even if not "sufficient" for escalation)
                if self.cache and hits:
                    self.cache.put(query, bank_id, hits)
                return hits, 1

        # ── Tier 2: LLM-guided reformulation ──
        if self.max_tier >= 2 and self.llm:
            reformulated = await self._reformulate(query)
            if reformulated != query:
                hits2 = self.search.search(reformulated, bank_id, limit=limit, tags=tags)
                merged = self._merge_hits(hits, hits2)
                if self.cache:
                    self.cache.put(query, bank_id, merged)
                return merged[:limit], 2

        # Cache whatever we have from tier 1
        if self.cache and hits:
            self.cache.put(query, bank_id, hits)
        return hits[:limit], max(self.max_tier, 0)

    def _sufficient(self, hits: list[SearchHit]) -> bool:
        """Check if results are sufficient (enough hits with good scores)."""
        if len(hits) < self.min_results:
            return False
        avg_score = sum(h.score for h in hits) / max(len(hits), 1)
        return avg_score >= self.min_score

    async def _reformulate(self, query: str) -> str:
        """Use LLM to reformulate query for better keyword matching."""
        from astrocyte.types import Message

        prompt = (
            "Reformulate this search query to improve keyword-based search results. "
            "Add synonyms and related terms. Return only the reformulated query.\n\n"
            f"Query: {query}"
        )
        try:
            completion = await self.llm.complete(
                messages=[Message(role="user", content=prompt)],
                max_tokens=100,
                temperature=0.3,
            )
            return completion.text.strip() or query
        except Exception:
            return query

    @staticmethod
    def _merge_hits(hits_a: list[SearchHit], hits_b: list[SearchHit]) -> list[SearchHit]:
        """Merge two hit lists, deduplicate by ID, keep highest score."""
        best: dict[str, SearchHit] = {}
        for h in hits_a + hits_b:
            prev = best.get(h.id)
            if prev is None or h.score > prev.score:
                best[h.id] = h
        return sorted(best.values(), key=lambda x: x.score, reverse=True)
