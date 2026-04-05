"""Tests for LocalEngineProvider — Astrocyte EngineProvider SPI implementation."""

from pathlib import Path

# Import Astrocyte types
from astrocyte.types import ForgetRequest, RecallRequest, RetainRequest

from astrocyte_local.engine import LocalEngineProvider


class TestLocalEngineRetain:
    async def test_retain_stores(self, tmp_path: Path):
        provider = LocalEngineProvider(root=tmp_path / ".astrocyte")
        result = await provider.retain(RetainRequest(content="Dark mode preference", bank_id="project"))
        assert result.stored is True
        assert result.memory_id is not None

    async def test_retain_with_tags(self, tmp_path: Path):
        provider = LocalEngineProvider(root=tmp_path / ".astrocyte")
        result = await provider.retain(
            RetainRequest(content="Tagged content", bank_id="project", tags=["preference", "ui"])
        )
        assert result.stored is True


class TestLocalEngineRecall:
    async def test_recall_after_retain(self, tmp_path: Path):
        provider = LocalEngineProvider(root=tmp_path / ".astrocyte")
        await provider.retain(RetainRequest(content="Calvin prefers dark mode", bank_id="project"))
        result = await provider.recall(RecallRequest(query="dark mode", bank_id="project"))
        assert len(result.hits) >= 1
        assert "dark mode" in result.hits[0].text.lower()

    async def test_recall_empty_bank(self, tmp_path: Path):
        provider = LocalEngineProvider(root=tmp_path / ".astrocyte")
        result = await provider.recall(RecallRequest(query="anything", bank_id="empty"))
        assert result.hits == []

    async def test_recall_bank_isolation(self, tmp_path: Path):
        provider = LocalEngineProvider(root=tmp_path / ".astrocyte")
        await provider.retain(RetainRequest(content="Secret in bank 1", bank_id="bank-1"))
        result = await provider.recall(RecallRequest(query="Secret", bank_id="bank-2"))
        assert len(result.hits) == 0

    async def test_recall_trace(self, tmp_path: Path):
        provider = LocalEngineProvider(root=tmp_path / ".astrocyte")
        await provider.retain(RetainRequest(content="test content", bank_id="project"))
        result = await provider.recall(RecallRequest(query="test", bank_id="project"))
        assert result.trace is not None
        assert "fts5" in result.trace.strategies_used


class TestLocalEngineForget:
    async def test_forget_by_id(self, tmp_path: Path):
        provider = LocalEngineProvider(root=tmp_path / ".astrocyte")
        retain_result = await provider.retain(RetainRequest(content="to delete", bank_id="project"))
        forget_result = await provider.forget(ForgetRequest(bank_id="project", memory_ids=[retain_result.memory_id]))
        assert forget_result.deleted_count == 1

        # Verify it's gone
        recall_result = await provider.recall(RecallRequest(query="to delete", bank_id="project"))
        assert len(recall_result.hits) == 0

    async def test_forget_all(self, tmp_path: Path):
        provider = LocalEngineProvider(root=tmp_path / ".astrocyte")
        await provider.retain(RetainRequest(content="memory 1", bank_id="project"))
        await provider.retain(RetainRequest(content="memory 2", bank_id="project"))
        result = await provider.forget(ForgetRequest(bank_id="project", scope="all"))
        assert result.deleted_count == 2


class TestLocalEngineCapabilities:
    async def test_capabilities(self, tmp_path: Path):
        provider = LocalEngineProvider(root=tmp_path / ".astrocyte")
        caps = provider.capabilities()
        assert caps.supports_keyword_search is True
        assert caps.supports_semantic_search is False  # No vectors
        assert caps.supports_reflect is False  # Needs LLM
        assert caps.supports_forget is True
        assert caps.supports_tags is True

    async def test_health(self, tmp_path: Path):
        provider = LocalEngineProvider(root=tmp_path / ".astrocyte")
        status = await provider.health()
        assert status.healthy is True
        assert "Local Context Tree" in status.message
