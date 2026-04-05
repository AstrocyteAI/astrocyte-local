"""Integration tests — LocalEngineProvider through the full Astrocyte framework.

Tests that the local engine works with Astrocyte's policy layer, hooks,
multi-bank orchestration, access control, and memory portability.
"""

from pathlib import Path

import pytest
from astrocyte._astrocyte import Astrocyte
from astrocyte.config import AstrocyteConfig
from astrocyte.errors import AccessDenied, RateLimited
from astrocyte.types import AccessGrant, AstrocyteContext

from astrocyte_local import LocalEngineProvider


def _make_brain(
    tmp_path: Path,
    *,
    pii_mode: str = "disabled",
    rate_limit_retain: int | None = None,
    access_enabled: bool = False,
) -> tuple[Astrocyte, LocalEngineProvider]:
    config = AstrocyteConfig()
    config.provider = "local"
    config.provider_tier = "engine"
    config.barriers.pii.mode = pii_mode
    config.barriers.pii.action = "redact"
    config.escalation.degraded_mode = "error"
    config.access_control.enabled = access_enabled
    config.access_control.default_policy = "deny"
    if rate_limit_retain:
        config.homeostasis.rate_limits.retain_per_minute = rate_limit_retain

    brain = Astrocyte(config)
    provider = LocalEngineProvider(root=tmp_path / ".astrocyte", enable_cache=True)
    brain.set_engine_provider(provider)
    return brain, provider


# ---------------------------------------------------------------------------
# Basic framework integration
# ---------------------------------------------------------------------------


class TestFrameworkRetainRecall:
    async def test_retain_through_framework(self, tmp_path: Path):
        brain, _ = _make_brain(tmp_path)
        result = await brain.retain("Calvin prefers dark mode", bank_id="project")
        assert result.stored is True

    async def test_recall_through_framework(self, tmp_path: Path):
        brain, _ = _make_brain(tmp_path)
        await brain.retain("Calvin prefers dark mode", bank_id="project")
        result = await brain.recall("dark mode", bank_id="project")
        assert len(result.hits) >= 1
        assert "dark mode" in result.hits[0].text.lower()

    async def test_retain_recall_roundtrip(self, tmp_path: Path):
        brain, _ = _make_brain(tmp_path)
        await brain.retain("The database uses PostgreSQL 16", bank_id="project", tags=["technical"])
        await brain.retain("Calvin likes Python 3.11", bank_id="project", tags=["preference"])

        result = await brain.recall("PostgreSQL", bank_id="project")
        assert len(result.hits) >= 1
        assert any("PostgreSQL" in h.text for h in result.hits)

    async def test_forget_through_framework(self, tmp_path: Path):
        brain, _ = _make_brain(tmp_path)
        retain_result = await brain.retain("to delete", bank_id="project")
        forget_result = await brain.forget("project", memory_ids=[retain_result.memory_id])
        assert forget_result.deleted_count == 1

        recall_result = await brain.recall("to delete", bank_id="project")
        assert len(recall_result.hits) == 0


# ---------------------------------------------------------------------------
# Policy layer enforcement
# ---------------------------------------------------------------------------


class TestPolicyEnforcement:
    async def test_pii_redaction(self, tmp_path: Path):
        brain, provider = _make_brain(tmp_path, pii_mode="regex")
        result = await brain.retain("Contact user@example.com for help", bank_id="project")
        assert result.stored is True

        # Check that PII was redacted in the stored file
        entries = provider._tree.scan_all(bank_id="project")
        assert len(entries) >= 1
        assert "user@example.com" not in entries[0].text
        assert "[EMAIL_REDACTED]" in entries[0].text

    async def test_rate_limiting(self, tmp_path: Path):
        brain, _ = _make_brain(tmp_path, rate_limit_retain=2)
        await brain.retain("First", bank_id="project")
        await brain.retain("Second", bank_id="project")
        with pytest.raises(RateLimited):
            await brain.retain("Third", bank_id="project")

    async def test_empty_content_rejected(self, tmp_path: Path):
        brain, _ = _make_brain(tmp_path)
        result = await brain.retain("", bank_id="project")
        assert result.stored is False
        assert "empty" in result.error.lower()


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


class TestAccessControl:
    async def test_access_denied_without_grant(self, tmp_path: Path):
        brain, _ = _make_brain(tmp_path, access_enabled=True)
        ctx = AstrocyteContext(principal="agent:unauthorized")
        with pytest.raises(AccessDenied):
            await brain.retain("test", bank_id="project", context=ctx)

    async def test_access_granted_with_grant(self, tmp_path: Path):
        brain, _ = _make_brain(tmp_path, access_enabled=True)
        brain.set_access_grants(
            [
                AccessGrant(bank_id="project", principal="agent:bot", permissions=["read", "write"]),
            ]
        )
        ctx = AstrocyteContext(principal="agent:bot")
        result = await brain.retain("authorized content", bank_id="project", context=ctx)
        assert result.stored is True

    async def test_read_access_for_recall(self, tmp_path: Path):
        brain, _ = _make_brain(tmp_path, access_enabled=True)
        brain.set_access_grants(
            [
                AccessGrant(bank_id="project", principal="agent:bot", permissions=["read", "write"]),
            ]
        )
        ctx = AstrocyteContext(principal="agent:bot")
        await brain.retain("searchable", bank_id="project", context=ctx)
        result = await brain.recall("searchable", bank_id="project", context=ctx)
        assert len(result.hits) >= 1


# ---------------------------------------------------------------------------
# Multi-bank orchestration
# ---------------------------------------------------------------------------


class TestMultiBank:
    async def test_bank_isolation(self, tmp_path: Path):
        brain, _ = _make_brain(tmp_path)
        await brain.retain("Secret in bank 1", bank_id="bank-1")
        await brain.retain("Public in bank 2", bank_id="bank-2")

        result = await brain.recall("Secret", bank_id="bank-2")
        for hit in result.hits:
            assert "Secret in bank 1" not in hit.text

    async def test_multi_bank_parallel_recall(self, tmp_path: Path):
        brain, _ = _make_brain(tmp_path)
        await brain.retain("Personal preference for dark mode", bank_id="personal")
        await brain.retain("Team uses GitHub Actions for CI", bank_id="team")

        result = await brain.recall("preference", banks=["personal", "team"])
        assert result.total_available >= 1

    async def test_multi_bank_reflect(self, tmp_path: Path):
        """Reflect across banks should work via Astrocyte's fallback (degrade mode)."""
        config = AstrocyteConfig()
        config.provider = "local"
        config.barriers.pii.mode = "disabled"
        config.fallback_strategy = "degrade"
        brain = Astrocyte(config)
        brain.set_engine_provider(LocalEngineProvider(root=tmp_path / ".astrocyte"))

        await brain.retain("Calvin likes Python", bank_id="personal")
        await brain.retain("Team policy requires code review", bank_id="team")

        # Degrade mode returns recall hits concatenated as the answer
        result = await brain.reflect(
            "What do we know?",
            banks=["personal", "team"],
            strategy="parallel",
        )
        assert result.answer  # Should have some content


# ---------------------------------------------------------------------------
# Event hooks
# ---------------------------------------------------------------------------


class TestHooks:
    async def test_retain_fires_hook(self, tmp_path: Path):
        brain, _ = _make_brain(tmp_path)
        events = []
        brain.register_hook("on_retain", lambda e: events.append(e))

        await brain.retain("hook test", bank_id="project")
        assert len(events) == 1
        assert events[0].type == "on_retain"

    async def test_recall_fires_hook(self, tmp_path: Path):
        brain, _ = _make_brain(tmp_path)
        events = []
        brain.register_hook("on_recall", lambda e: events.append(e))

        await brain.retain("searchable content", bank_id="project")
        await brain.recall("searchable", bank_id="project")
        assert len(events) == 1
        assert events[0].type == "on_recall"

    async def test_pii_hook_fires(self, tmp_path: Path):
        brain, _ = _make_brain(tmp_path, pii_mode="regex")
        events = []
        brain.register_hook("on_pii_detected", lambda e: events.append(e))

        await brain.retain("Email: user@example.com", bank_id="project")
        assert len(events) == 1
        assert "email" in events[0].data.get("pii_types", "")


# ---------------------------------------------------------------------------
# Memory portability
# ---------------------------------------------------------------------------


class TestPortability:
    async def test_export_import_roundtrip(self, tmp_path: Path):
        brain_a, _ = _make_brain(tmp_path / "a")
        await brain_a.retain("Memory one about Python", bank_id="project")
        await brain_a.retain("Memory two about Rust", bank_id="project")

        export_path = tmp_path / "backup.ama.jsonl"
        exported = await brain_a.export_bank("project", str(export_path))
        assert exported >= 2

        # Import into a fresh provider
        brain_b, _ = _make_brain(tmp_path / "b")
        result = await brain_b.import_bank("project", str(export_path))
        assert result.imported >= 2

        # Verify imported memories are recallable
        recall_result = await brain_b.recall("Python", bank_id="project")
        assert len(recall_result.hits) >= 1


# ---------------------------------------------------------------------------
# Tiered retrieval + cache
# ---------------------------------------------------------------------------


class TestTieredRetrieval:
    async def test_cache_hit_on_repeat_query(self, tmp_path: Path):
        """Test cache directly on the provider (bypassing framework which adds overhead)."""
        from astrocyte.types import RecallRequest

        provider = LocalEngineProvider(root=tmp_path / ".astrocyte", enable_cache=True)
        from astrocyte.types import RetainRequest

        await provider.retain(RetainRequest(content="Dark mode is preferred", bank_id="project"))

        # First query — cache miss (tier 1)
        result1 = await provider.recall(RecallRequest(query="dark mode", bank_id="project"))
        assert len(result1.hits) >= 1
        assert result1.trace.tier_used == 1

        # Second query — should hit cache (tier 0)
        result2 = await provider.recall(RecallRequest(query="dark mode", bank_id="project"))
        assert len(result2.hits) >= 1
        assert result2.trace.cache_hit is True
        assert result2.trace.tier_used == 0

    async def test_cache_invalidated_on_retain(self, tmp_path: Path):
        brain, provider = _make_brain(tmp_path)
        await brain.retain("Original content", bank_id="project")
        await brain.recall("Original", bank_id="project")  # Populate cache

        # Retain new content — cache should be invalidated
        await brain.retain("New additional content", bank_id="project")

        # This recall should NOT use the old cache
        result = await brain.recall("New additional", bank_id="project")
        assert len(result.hits) >= 1


# ---------------------------------------------------------------------------
# Context Tree file persistence
# ---------------------------------------------------------------------------


class TestFilePersistence:
    async def test_memories_survive_provider_restart(self, tmp_path: Path):
        from astrocyte.types import RecallRequest, RetainRequest

        root = tmp_path / ".astrocyte"

        # Create provider, store memory, destroy it
        provider1 = LocalEngineProvider(root=root)
        await provider1.retain(RetainRequest(content="Persistent memory", bank_id="project"))

        # Create a new provider pointing to the same root
        provider2 = LocalEngineProvider(root=root)
        result = await provider2.recall(RecallRequest(query="Persistent", bank_id="project"))
        assert len(result.hits) >= 1
        assert "Persistent memory" in result.hits[0].text

    async def test_files_are_readable_markdown(self, tmp_path: Path):
        brain, provider = _make_brain(tmp_path)
        await brain.retain("Human readable content", bank_id="project")

        # Check that actual .md files exist
        memory_dir = provider.root / "memory"
        md_files = list(memory_dir.rglob("*.md"))
        assert len(md_files) >= 1

        # Check file content is valid markdown
        content = md_files[0].read_text()
        assert content.startswith("---\n")  # YAML frontmatter
        assert "Human readable content" in content
