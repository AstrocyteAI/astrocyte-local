"""Tests for SearchEngine — SQLite FTS5 full-text search."""

from pathlib import Path

from astrocyte_local.context_tree import ContextTree
from astrocyte_local.search import SearchEngine


class TestSearchBasic:
    def test_keyword_match(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        tree.store("Calvin prefers dark mode in all applications", bank_id="test", tags=["preference"])
        search = SearchEngine(tmp_path / "_search.db")
        search.build_index(tree, bank_id="test")

        hits = search.search("dark mode", "test")
        assert len(hits) >= 1
        assert "dark mode" in hits[0].text.lower()

    def test_partial_keyword_match(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        tree.store("The deployment pipeline uses GitHub Actions", bank_id="test")
        search = SearchEngine(tmp_path / "_search.db")
        search.build_index(tree)

        # Exact keyword match
        hits = search.search("deployment", "test")
        assert len(hits) >= 1

        # Multi-keyword match
        hits = search.search("deployment pipeline", "test")
        assert len(hits) >= 1

    def test_no_match_returns_empty(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        tree.store("Something about Python", bank_id="test")
        search = SearchEngine(tmp_path / "_search.db")
        search.build_index(tree)

        hits = search.search("nonexistent topic", "test")
        assert hits == []


class TestSearchFiltering:
    def test_bank_isolation(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        tree.store("Secret in bank 1", bank_id="bank-1")
        tree.store("Public in bank 2", bank_id="bank-2")
        search = SearchEngine(tmp_path / "_search.db")
        search.build_index(tree)

        hits = search.search("Secret", "bank-2")
        assert len(hits) == 0

    def test_tag_filtering(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        tree.store("Memory A", bank_id="test", tags=["alpha"])
        tree.store("Memory B", bank_id="test", tags=["beta"])
        search = SearchEngine(tmp_path / "_search.db")
        search.build_index(tree)

        hits = search.search("Memory", "test", tags=["alpha"])
        assert len(hits) == 1
        assert "A" in hits[0].text

    def test_layer_filtering(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        tree.store("fact memory", bank_id="test", memory_layer="fact")
        tree.store("model memory", bank_id="test", memory_layer="model")
        search = SearchEngine(tmp_path / "_search.db")
        search.build_index(tree)

        hits = search.search("memory", "test", layers=["model"])
        assert len(hits) == 1
        assert hits[0].memory_layer == "model"


class TestSearchWildcard:
    def test_wildcard_returns_all(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        tree.store("Memory 1", bank_id="test")
        tree.store("Memory 2", bank_id="test")
        search = SearchEngine(tmp_path / "_search.db")
        search.build_index(tree)

        hits = search.search("*", "test")
        assert len(hits) == 2


class TestSearchIncremental:
    def test_add_document(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        search = SearchEngine(tmp_path / "_search.db")

        entry = tree.store("new content", bank_id="test")
        search.add_document(entry)

        hits = search.search("new content", "test")
        assert len(hits) == 1

    def test_remove_document(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        search = SearchEngine(tmp_path / "_search.db")

        entry = tree.store("to remove", bank_id="test")
        search.add_document(entry)
        assert len(search.search("remove", "test")) == 1

        search.remove_document(entry.id)
        assert len(search.search("remove", "test")) == 0


class TestSearchScoring:
    def test_scores_are_normalized(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        tree.store("Python programming language", bank_id="test")
        tree.store("Python is great for AI", bank_id="test")
        search = SearchEngine(tmp_path / "_search.db")
        search.build_index(tree)

        hits = search.search("Python", "test")
        for h in hits:
            assert 0.0 <= h.score <= 1.0

    def test_max_results_limit(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        for i in range(20):
            tree.store(f"Memory about testing item {i}", bank_id="test")
        search = SearchEngine(tmp_path / "_search.db")
        search.build_index(tree)

        hits = search.search("testing", "test", limit=5)
        assert len(hits) <= 5
