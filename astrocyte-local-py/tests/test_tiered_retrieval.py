"""Tests for tiered retrieval in the local engine."""

import time
from pathlib import Path

from astrocyte_local.context_tree import ContextTree
from astrocyte_local.search import SearchEngine
from astrocyte_local.tiered_retrieval import LocalRecallCache, LocalTieredRetriever


class TestLocalRecallCache:
    def test_cache_miss(self):
        cache = LocalRecallCache()
        assert cache.get("test query", "bank-1") is None

    def test_cache_hit(self):
        from astrocyte_local.search import SearchHit

        cache = LocalRecallCache()
        hits = [SearchHit(id="m1", text="cached", score=0.9, bank_id="b1", domain="test", file_path="test.md")]
        cache.put("test query", "bank-1", hits)

        result = cache.get("test query", "bank-1")
        assert result is not None
        assert result[0].text == "cached"

    def test_case_insensitive(self):
        from astrocyte_local.search import SearchHit

        cache = LocalRecallCache()
        hits = [SearchHit(id="m1", text="cached", score=0.9, bank_id="b1", domain="test", file_path="test.md")]
        cache.put("Dark Mode", "bank-1", hits)

        assert cache.get("dark mode", "bank-1") is not None
        assert cache.get("DARK MODE", "bank-1") is not None

    def test_bank_isolation(self):
        from astrocyte_local.search import SearchHit

        cache = LocalRecallCache()
        hits = [SearchHit(id="m1", text="cached", score=0.9, bank_id="b1", domain="test", file_path="test.md")]
        cache.put("query", "bank-1", hits)

        assert cache.get("query", "bank-2") is None

    def test_invalidate_bank(self):
        from astrocyte_local.search import SearchHit

        cache = LocalRecallCache()
        hits = [SearchHit(id="m1", text="cached", score=0.9, bank_id="b1", domain="test", file_path="test.md")]
        cache.put("query", "bank-1", hits)
        assert cache.size() == 1

        cache.invalidate_bank("bank-1")
        assert cache.size() == 0
        assert cache.get("query", "bank-1") is None

    def test_ttl_expiry(self):
        from astrocyte_local.search import SearchHit

        cache = LocalRecallCache(ttl_seconds=0.01)
        hits = [SearchHit(id="m1", text="cached", score=0.9, bank_id="b1", domain="test", file_path="test.md")]
        cache.put("query", "bank-1", hits)

        time.sleep(0.02)
        assert cache.get("query", "bank-1") is None

    def test_lru_eviction(self):
        from astrocyte_local.search import SearchHit

        cache = LocalRecallCache(max_entries=2)
        for i in range(3):
            hits = [SearchHit(id=f"m{i}", text=f"hit{i}", score=0.9, bank_id="b1", domain="test", file_path="t.md")]
            cache.put(f"query-{i}", "bank-1", hits)

        assert cache.size() == 2


class TestLocalTieredRetriever:
    def test_tier_1_fts5(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        tree.store("Dark mode is preferred by Calvin", bank_id="test")
        search = SearchEngine(tmp_path / "_search.db")
        search.build_index(tree)

        tiered = LocalTieredRetriever(search=search, max_tier=1)
        hits, tier = tiered.retrieve("dark mode", "test")

        assert len(hits) >= 1
        assert tier == 1

    def test_tier_0_cache_hit(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        tree.store("Cached content here", bank_id="test")
        search = SearchEngine(tmp_path / "_search.db")
        search.build_index(tree)

        cache = LocalRecallCache()
        tiered = LocalTieredRetriever(search=search, cache=cache, max_tier=1)

        # First query — tier 1
        hits1, tier1 = tiered.retrieve("Cached content", "test")
        assert tier1 == 1

        # Second query — tier 0 (cache)
        hits2, tier2 = tiered.retrieve("Cached content", "test")
        assert tier2 == 0
        assert len(hits2) >= 1

    def test_cache_invalidation_changes_tier(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        tree.store("Original content", bank_id="test")
        search = SearchEngine(tmp_path / "_search.db")
        search.build_index(tree)

        cache = LocalRecallCache()
        tiered = LocalTieredRetriever(search=search, cache=cache, max_tier=1)

        # Populate cache
        tiered.retrieve("Original", "test")

        # Invalidate
        cache.invalidate_bank("test")

        # Should go to tier 1 again
        hits, tier = tiered.retrieve("Original", "test")
        assert tier == 1

    def test_max_tier_respected(self, tmp_path: Path):
        search = SearchEngine(tmp_path / "_search.db")
        tiered = LocalTieredRetriever(search=search, max_tier=0)

        hits, tier = tiered.retrieve("anything", "test")
        assert hits == []
        assert tier == 0

    async def test_async_tier_1(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        tree.store("Async searchable content", bank_id="test")
        search = SearchEngine(tmp_path / "_search.db")
        search.build_index(tree)

        tiered = LocalTieredRetriever(search=search, max_tier=1)
        hits, tier = await tiered.aretrieve("Async searchable", "test")

        assert len(hits) >= 1
        assert tier == 1

    async def test_async_cache_hit(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        tree.store("Async cached", bank_id="test")
        search = SearchEngine(tmp_path / "_search.db")
        search.build_index(tree)

        cache = LocalRecallCache()
        tiered = LocalTieredRetriever(search=search, cache=cache, max_tier=1)

        await tiered.aretrieve("Async cached", "test")
        hits, tier = await tiered.aretrieve("Async cached", "test")
        assert tier == 0
