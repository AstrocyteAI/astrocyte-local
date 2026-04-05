"""LLM-curated retain for local Context Tree.

When an LLM provider is available, the LLM decides:
- What action to take: ADD, UPDATE, MERGE, SKIP, DELETE
- Which domain to store in (instead of just using the first tag)
- What memory_layer to assign (fact, observation, model)

Falls back to simple mechanical retain when no LLM is configured.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from astrocyte_local.context_tree import ContextTree
from astrocyte_local.search import SearchEngine

if TYPE_CHECKING:
    from astrocyte.provider import LLMProvider


@dataclass
class LocalCurationDecision:
    """Result of LLM curation for local storage."""

    action: str  # "add", "update", "merge", "skip", "delete"
    domain: str  # Where to store in the Context Tree
    content: str  # Processed content (may be rewritten)
    memory_layer: str  # "fact", "observation", "model"
    reasoning: str
    target_id: str | None = None  # For update/merge/delete — which existing entry


_CURATION_PROMPT = """You are a memory curation agent for a local Context Tree. Analyze the new content and decide how to store it.

## Existing memories (most similar):
{existing}

## Context Tree domains currently in use:
{domains}

## New content:
{content}

## Decide:
1. action: "add" (new info), "update" (replace existing), "merge" (combine with existing), "skip" (redundant), "delete" (contradicts old)
2. domain: Which Context Tree directory to store in (e.g., "preferences", "architecture", "decisions"). Use an existing domain if appropriate, or suggest a new one.
3. memory_layer: "fact" (raw info), "observation" (pattern/insight), "model" (consolidated understanding)
4. content: The processed text to store (may rewrite for clarity)
5. reasoning: Brief explanation

Respond with JSON:
{{"action": "add", "domain": "preferences", "content": "...", "memory_layer": "fact", "reasoning": "...", "target_id": null}}
"""


async def curate_local_retain(
    content: str,
    bank_id: str,
    tree: ContextTree,
    search: SearchEngine,
    llm_provider: LLMProvider,
    *,
    context_limit: int = 5,
) -> LocalCurationDecision:
    """Ask the LLM to curate a retain operation for the local Context Tree.

    Searches existing memories for context, then asks the LLM to decide
    action, domain, memory_layer, and optionally rewrite the content.

    Falls back to simple ADD with domain="general" on failure.
    """
    from astrocyte.types import Message

    # Get existing similar memories for context
    existing_hits = search.search(content, bank_id, limit=context_limit)
    if existing_hits:
        existing_text = "\n".join(
            f"- [{h.id}] ({h.domain}/{h.file_path}) score={h.score:.2f}: {h.text[:200]}" for h in existing_hits
        )
    else:
        existing_text = "(no existing memories)"

    # Get current domains
    domains = tree.list_domains(bank_id)
    domains_text = ", ".join(domains) if domains else "(none yet)"

    prompt = _CURATION_PROMPT.format(
        existing=existing_text,
        domains=domains_text,
        content=content,
    )

    try:
        completion = await llm_provider.complete(
            messages=[Message(role="user", content=prompt)],
            max_tokens=500,
            temperature=0.0,
        )
        return _parse_response(completion.text, content)
    except Exception:
        return LocalCurationDecision(
            action="add",
            domain="general",
            content=content,
            memory_layer="fact",
            reasoning="LLM curation failed, defaulting to ADD",
        )


def _parse_response(response: str, original_content: str) -> LocalCurationDecision:
    """Parse LLM response into a LocalCurationDecision."""
    try:
        text = response.strip()
        if "```" in text:
            start = text.index("```") + 3
            if text[start:].startswith("json"):
                start += 4
            end = text.index("```", start)
            text = text[start:end].strip()

        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("Expected JSON object")

        action = data.get("action", "add").lower()
        if action not in ("add", "update", "merge", "skip", "delete"):
            action = "add"

        memory_layer = data.get("memory_layer", "fact").lower()
        if memory_layer not in ("fact", "observation", "model"):
            memory_layer = "fact"

        # Sanitize domain name
        domain = data.get("domain", "general").lower().strip()
        domain = domain.replace(" ", "-").replace("/", "-")
        if not domain:
            domain = "general"

        return LocalCurationDecision(
            action=action,
            domain=domain,
            content=data.get("content", original_content),
            memory_layer=memory_layer,
            reasoning=data.get("reasoning", ""),
            target_id=data.get("target_id"),
        )
    except (json.JSONDecodeError, ValueError):
        return LocalCurationDecision(
            action="add",
            domain="general",
            content=original_content,
            memory_layer="fact",
            reasoning="Failed to parse LLM response",
        )
