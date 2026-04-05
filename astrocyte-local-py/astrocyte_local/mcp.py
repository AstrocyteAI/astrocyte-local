"""MCP server for Astrocyte Local — exposes Context Tree as MCP tools.

Usage:
    astrocyte-local-mcp --root .astrocyte
    astrocyte-local mcp --root .astrocyte

See docs/mcp-tools.md for the tool specification.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fastmcp import FastMCP

from astrocyte_local.context_tree import ContextTree
from astrocyte_local.search import SearchEngine


def create_mcp_server(root: str | Path, default_bank: str = "project") -> FastMCP:
    """Create a FastMCP server backed by a local Context Tree."""
    root = Path(root)
    tree = ContextTree(root)
    search = SearchEngine(root / "_search.db")
    search.build_index(tree)

    mcp = FastMCP(
        name="astrocyte-local",
        instructions=(
            "Local memory server. Use memory_retain to store information, "
            "memory_recall to search memories, memory_browse to explore the "
            "Context Tree hierarchy, and memory_forget to remove memories."
        ),
    )

    # ── memory_retain ──

    @mcp.tool()
    async def memory_retain(
        content: str,
        bank_id: str | None = None,
        tags: list[str] | None = None,
        domain: str | None = None,
    ) -> str:
        """Store content into local memory.

        Args:
            content: The text to memorize.
            bank_id: Memory bank (default: project).
            tags: Optional tags for filtering.
            domain: Context Tree domain (auto-inferred if omitted).
        """
        bid = bank_id or default_bank
        dom = domain or (tags[0] if tags else "general")

        entry = tree.store(content, bank_id=bid, domain=dom, tags=tags or [])
        search.add_document(entry)

        return json.dumps(
            {
                "stored": True,
                "memory_id": entry.id,
                "domain": entry.domain,
                "file": entry.file_path,
            }
        )

    # ── memory_recall ──

    @mcp.tool()
    async def memory_recall(
        query: str,
        bank_id: str | None = None,
        max_results: int = 10,
        tags: list[str] | None = None,
    ) -> str:
        """Search local memory for content relevant to a query.

        Args:
            query: Natural language search query.
            bank_id: Memory bank (default: project).
            max_results: Maximum results.
            tags: Filter by tags.
        """
        bid = bank_id or default_bank
        hits = search.search(query, bid, limit=max_results, tags=tags)

        # Record recall
        for h in hits:
            tree.record_recall(h.id)

        return json.dumps(
            {
                "hits": [
                    {
                        "text": h.text,
                        "score": round(h.score, 4),
                        "domain": h.domain,
                        "file": h.file_path,
                        "memory_id": h.id,
                    }
                    for h in hits
                ],
                "total": len(hits),
            }
        )

    # ── memory_browse ──

    @mcp.tool()
    async def memory_browse(
        path: str = "",
        bank_id: str | None = None,
    ) -> str:
        """Browse the Context Tree hierarchy.

        Args:
            path: Path to browse (empty for root, 'preferences' for a domain).
            bank_id: Memory bank (default: project).
        """
        bid = bank_id or default_bank

        if not path:
            # Root level — list domains
            domains = tree.list_domains(bid)
            total = tree.count(bid)
            return json.dumps(
                {
                    "path": "",
                    "domains": domains,
                    "entries": [],
                    "total_memories": total,
                }
            )

        # Domain level — list entries
        entries = tree.list_entries(bid, domain=path)
        return json.dumps(
            {
                "path": path,
                "domains": [],
                "entries": [
                    {
                        "file": e.file_path,
                        "title": e.text[:80],
                        "memory_id": e.id,
                        "recall_count": e.recall_count,
                    }
                    for e in entries
                ],
                "total_memories": len(entries),
            }
        )

    # ── memory_forget ──

    @mcp.tool()
    async def memory_forget(
        memory_ids: list[str],
        bank_id: str | None = None,
    ) -> str:
        """Remove memories from local storage.

        Args:
            memory_ids: IDs of memories to delete.
            bank_id: Memory bank (default: project).
        """
        deleted = 0
        files_removed: list[str] = []
        for mid in memory_ids:
            entry = tree.read(mid)
            if entry:
                files_removed.append(entry.file_path)
            if tree.delete(mid):
                search.remove_document(mid)
                deleted += 1

        return json.dumps(
            {
                "deleted_count": deleted,
                "files_removed": files_removed,
            }
        )

    # ── memory_banks ──

    @mcp.tool()
    async def memory_banks() -> str:
        """List available memory banks."""
        all_entries = tree.scan_all()
        bank_ids = sorted(set(e.bank_id for e in all_entries))
        if default_bank not in bank_ids:
            bank_ids.insert(0, default_bank)
        return json.dumps(
            {
                "banks": bank_ids,
                "default": default_bank,
                "root": str(root),
            }
        )

    # ── memory_health ──

    @mcp.tool()
    async def memory_health() -> str:
        """Check local memory system health."""
        total = tree.count()
        return json.dumps(
            {
                "healthy": True,
                "total_memories": total,
                "index_status": "current",
                "root": str(root),
            }
        )

    return mcp


def main() -> None:
    """CLI entry point for astrocyte-local-mcp."""
    parser = argparse.ArgumentParser(
        prog="astrocyte-local-mcp",
        description="Astrocyte Local MCP server — memory tools backed by local files",
    )
    parser.add_argument("--root", default=".astrocyte", help="Context Tree root directory")
    parser.add_argument("--bank", default="project", help="Default memory bank")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()

    mcp = create_mcp_server(args.root, default_bank=args.bank)

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="sse", port=args.port)


if __name__ == "__main__":
    main()
