"""Tests for LLM-curated retain in the local engine."""

from pathlib import Path

from astrocyte.types import RetainRequest

from astrocyte_local.curated_retain import _parse_response
from astrocyte_local.engine import LocalEngineProvider


class TestCurationParsing:
    def test_parse_valid_json(self):
        response = (
            '{"action": "add", "domain": "preferences", "content": "test", "memory_layer": "fact", "reasoning": "new"}'
        )
        decision = _parse_response(response, "original")
        assert decision.action == "add"
        assert decision.domain == "preferences"
        assert decision.memory_layer == "fact"

    def test_parse_with_code_block(self):
        response = '```json\n{"action": "merge", "domain": "arch", "content": "merged", "memory_layer": "observation", "reasoning": "similar", "target_id": "abc123"}\n```'
        decision = _parse_response(response, "original")
        assert decision.action == "merge"
        assert decision.target_id == "abc123"

    def test_parse_invalid_falls_back(self):
        decision = _parse_response("not json", "original")
        assert decision.action == "add"
        assert decision.domain == "general"
        assert decision.content == "original"

    def test_parse_normalizes_domain(self):
        response = (
            '{"action": "add", "domain": "My Domain / Sub", "content": "test", "memory_layer": "fact", "reasoning": ""}'
        )
        decision = _parse_response(response, "original")
        assert decision.domain == "my-domain---sub"  # Sanitized

    def test_skip_action(self):
        response = '{"action": "skip", "domain": "", "content": "", "memory_layer": "fact", "reasoning": "redundant"}'
        decision = _parse_response(response, "original")
        assert decision.action == "skip"

    def test_delete_action_with_target(self):
        response = '{"action": "delete", "domain": "", "content": "", "memory_layer": "fact", "reasoning": "contradicts", "target_id": "old123"}'
        decision = _parse_response(response, "original")
        assert decision.action == "delete"
        assert decision.target_id == "old123"


class TestCuratedRetainEngine:
    async def test_curated_retain_skip(self, tmp_path: Path):
        """Mock LLM that always returns SKIP."""
        from astrocyte.testing.in_memory import MockLLMProvider

        class SkipLLM(MockLLMProvider):
            async def complete(self, messages, **kwargs):
                from astrocyte.types import Completion, TokenUsage

                return Completion(
                    text='{"action": "skip", "domain": "general", "content": "", "memory_layer": "fact", "reasoning": "redundant"}',
                    model="mock",
                    usage=TokenUsage(input_tokens=10, output_tokens=20),
                )

        provider = LocalEngineProvider(
            root=tmp_path / ".astrocyte",
            llm_provider=SkipLLM(),
            enable_curated_retain=True,
        )
        result = await provider.retain(RetainRequest(content="redundant info", bank_id="project"))
        assert result.stored is False
        assert result.curated is True
        assert result.retention_action == "skip"

    async def test_curated_retain_add_with_domain(self, tmp_path: Path):
        """Mock LLM that classifies domain and layer."""
        from astrocyte.testing.in_memory import MockLLMProvider

        class ClassifyLLM(MockLLMProvider):
            async def complete(self, messages, **kwargs):
                from astrocyte.types import Completion, TokenUsage

                return Completion(
                    text='{"action": "add", "domain": "architecture", "content": "PostgreSQL is the primary database", "memory_layer": "fact", "reasoning": "new technical info"}',
                    model="mock",
                    usage=TokenUsage(input_tokens=10, output_tokens=20),
                )

        provider = LocalEngineProvider(
            root=tmp_path / ".astrocyte",
            llm_provider=ClassifyLLM(),
            enable_curated_retain=True,
        )
        result = await provider.retain(RetainRequest(content="We use PostgreSQL", bank_id="project"))
        assert result.stored is True
        assert result.curated is True
        assert result.retention_action == "add"
        assert result.memory_layer == "fact"

        # Verify it was stored in the correct domain
        entries = provider._tree.list_entries("project", domain="architecture")
        assert len(entries) >= 1

    async def test_mechanical_retain_without_llm(self, tmp_path: Path):
        """Without LLM, retain should work mechanically."""
        provider = LocalEngineProvider(
            root=tmp_path / ".astrocyte",
            enable_curated_retain=True,  # Enabled but no LLM → falls back to mechanical
        )
        result = await provider.retain(RetainRequest(content="simple store", bank_id="project"))
        assert result.stored is True
        assert result.curated is False  # No LLM available
