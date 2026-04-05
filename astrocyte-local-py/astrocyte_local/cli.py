"""CLI for Astrocyte Local — retain, search, browse, forget, export.

See docs/cli-reference.md for the full command specification.

Usage:
    astrocyte-local retain "Calvin prefers dark mode" --tags preference
    astrocyte-local search "dark mode"
    astrocyte-local browse
    astrocyte-local forget a1b2c3d4e5f6
    astrocyte-local export --output backup.ama.jsonl
    astrocyte-local health
    astrocyte-local mcp
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from astrocyte_local.context_tree import ContextTree
from astrocyte_local.search import SearchEngine


def main() -> None:
    parser = argparse.ArgumentParser(prog="astrocyte-local", description="Local memory for AI coding agents")
    parser.add_argument("--root", "-r", default=".astrocyte", help="Context Tree root directory")
    parser.add_argument("--bank", "-b", default="project", help="Memory bank ID")
    parser.add_argument("--format", "-f", choices=["text", "json"], default="text", help="Output format")

    sub = parser.add_subparsers(dest="command")

    # retain
    p_retain = sub.add_parser("retain", help="Store content into memory")
    p_retain.add_argument("content", nargs="?", help="Content to retain")
    p_retain.add_argument("--tags", help="Comma-separated tags")
    p_retain.add_argument("--domain", help="Context Tree domain")
    p_retain.add_argument("--stdin", action="store_true", help="Read from stdin")

    # search
    p_search = sub.add_parser("search", help="Search memory")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--tags", help="Filter by tags (comma-separated)")
    p_search.add_argument("--max-results", type=int, default=10)

    # browse
    p_browse = sub.add_parser("browse", help="Browse the Context Tree")
    p_browse.add_argument("path", nargs="?", default="", help="Path to browse")

    # forget
    p_forget = sub.add_parser("forget", help="Remove memories")
    p_forget.add_argument("memory_ids", nargs="*", help="Memory IDs to delete")
    p_forget.add_argument("--all", action="store_true", help="Delete all in bank")

    # export
    p_export = sub.add_parser("export", help="Export to AMA format")
    p_export.add_argument("--output", "-o", help="Output file path")

    # health
    sub.add_parser("health", help="System health check")

    # rebuild-index
    sub.add_parser("rebuild-index", help="Rebuild the search index")

    # mcp
    p_mcp = sub.add_parser("mcp", help="Start MCP server")
    p_mcp.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    p_mcp.add_argument("--port", type=int, default=8090)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    root = Path(args.root)
    tree = ContextTree(root)
    search = SearchEngine(root / "_search.db")
    fmt = args.format

    if args.command == "retain":
        content = args.content
        if args.stdin or content is None:
            content = sys.stdin.read().strip()
        if not content:
            print("Error: no content provided", file=sys.stderr)
            sys.exit(2)

        tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
        domain = args.domain or (tags[0] if tags else "general")

        entry = tree.store(content, bank_id=args.bank, domain=domain, tags=tags)
        search.add_document(entry)

        if fmt == "json":
            print(json.dumps({"stored": True, "memory_id": entry.id, "domain": entry.domain, "file": entry.file_path}))
        else:
            print(f"Stored: {entry.id} → {entry.file_path}")

    elif args.command == "search":
        search.build_index(tree, bank_id=args.bank)
        tags = [t.strip() for t in args.tags.split(",")] if args.tags else None
        hits = search.search(args.query, args.bank, limit=args.max_results, tags=tags)

        if fmt == "json":
            hit_dicts = [
                {"score": round(h.score, 4), "text": h.text, "domain": h.domain, "file": h.file_path, "memory_id": h.id}
                for h in hits
            ]
            print(json.dumps({"hits": hit_dicts}))
        else:
            if not hits:
                print("No results found.")
            for h in hits:
                print(f"[{h.score:.2f}] {h.file_path}")
                print(f"  {h.text[:100]}")
                print()

    elif args.command == "browse":
        path = args.path
        if not path:
            domains = tree.list_domains(args.bank)
            total = tree.count(args.bank)
            if fmt == "json":
                print(json.dumps({"path": "", "domains": domains, "total_memories": total}))
            else:
                print(f"{root}/memory/")
                for d in domains:
                    count = len(tree.list_entries(args.bank, domain=d))
                    print(f"  {d}/     ({count} entries)")
                print(f"\nTotal: {total} memories")
        else:
            entries = tree.list_entries(args.bank, domain=path)
            if fmt == "json":
                entry_dicts = [{"file": e.file_path, "title": e.text[:80], "memory_id": e.id} for e in entries]
                print(json.dumps({"path": path, "entries": entry_dicts}))
            else:
                for e in entries:
                    print(f"  {e.file_path}  [{e.id}]")
                    print(f"    {e.text[:80]}")

    elif args.command == "forget":
        if args.all:
            entries = tree.list_entries(args.bank)
            deleted = 0
            for e in entries:
                if tree.delete(e.id):
                    search.remove_document(e.id)
                    deleted += 1
            if fmt == "json":
                print(json.dumps({"deleted_count": deleted}))
            else:
                print(f"Deleted {deleted} memories")
        else:
            deleted = 0
            for mid in args.memory_ids:
                if tree.delete(mid):
                    search.remove_document(mid)
                    deleted += 1
            if fmt == "json":
                print(json.dumps({"deleted_count": deleted}))
            else:
                print(f"Deleted {deleted} memories")

    elif args.command == "export":
        entries = tree.scan_all(args.bank)
        output = args.output
        header = {"_ama_version": 1, "bank_id": args.bank, "memory_count": len(entries)}

        lines = [json.dumps(header)]
        for e in entries:
            record = {"id": e.id, "text": e.text, "fact_type": e.fact_type, "tags": e.tags, "created_at": e.created_at}
            if e.occurred_at:
                record["occurred_at"] = e.occurred_at
            if e.source:
                record["source"] = e.source
            lines.append(json.dumps(record))

        content = "\n".join(lines) + "\n"
        if output:
            Path(output).write_text(content)
            print(f"Exported {len(entries)} memories to {output}")
        else:
            print(content, end="")

    elif args.command == "health":
        total = tree.count()
        domains = tree.list_domains()
        if fmt == "json":
            print(json.dumps({"healthy": True, "total_memories": total, "root": str(root)}))
        else:
            print("Status: healthy")
            print(f"Root: {root}")
            print(f"Memories: {total}")
            print(f"Domains: {', '.join(domains) if domains else '(none)'}")

    elif args.command == "rebuild-index":
        count = search.build_index(tree)
        print(f"Rebuilt index: {count} entries")

    elif args.command == "mcp":
        from astrocyte_local.mcp import create_mcp_server

        mcp = create_mcp_server(root, default_bank=args.bank)
        if args.transport == "stdio":
            mcp.run(transport="stdio")
        else:
            mcp.run(transport="sse", port=args.port)


if __name__ == "__main__":
    main()
