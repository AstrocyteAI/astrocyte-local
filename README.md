# Astrocyte Local

**Zero-infrastructure, local-first memory for AI Agents.** Store, search, and recall memories as local markdown files — no database, no embeddings, no API keys.

Astrocyte Local is the client-side companion to [Astrocyte](https://github.com/AstrocyteAI/astrocyte), the open-source memory framework for AI agents. It provides persistent, single-user memory as a hierarchical Context Tree of plain markdown files — exposed via MCP, CLI, and libraries. Common MCP hosts include Claude Code, Cursor, and Windsurf; any MCP-capable agent or tool can use the same interface.

## Implementations

| Language | Package | Primary use case | Status |
|---|---|---|---|
| **TypeScript** | [`@astrocyteai/local`](astrocyte-local-ts/) (npm) | MCP server for AI agents and tools | Phase 1 |
| **Python** | [`astrocyte-local`](astrocyte-local-py/) (PyPI) | Library + Astrocyte framework integration | Phase 2 |
| **Rust** | [`astrocyte-local`](astrocyte-local-rs/) (crates.io) | Fast CLI + single binary MCP server | Phase 3 |

All implementations follow the same [shared specification](docs/) — same Context Tree format, same search behavior, same MCP tools, same CLI commands.

## Quick start

### MCP server (Claude Code / Cursor)

```json
{
  "mcpServers": {
    "memory": {
      "command": "npx",
      "args": ["@astrocyteai/local", "--root", ".astrocyte"]
    }
  }
}
```

### Python library

```python
from astrocyte_local import LocalEngineProvider
from astrocyte import Astrocyte

brain = Astrocyte.from_config("astrocyte.yaml")
brain.set_engine_provider(LocalEngineProvider(root=".astrocyte"))

await brain.retain("Calvin prefers dark mode", bank_id="project")
hits = await brain.recall("preferences", bank_id="project")
```

### CLI

```bash
astrocyte-local retain "Calvin prefers dark mode" --root .astrocyte
astrocyte-local search "preferences" --root .astrocyte
astrocyte-local browse --root .astrocyte
```

## Architecture

### Context Tree

Memories stored as markdown files in a hierarchical directory:

```
.astrocyte/
├── memory/
│   ├── preferences/
│   │   ├── ui-theme.md
│   │   └── languages.md
│   ├── architecture/
│   │   ├── deployment.md
│   │   └── database.md
│   └── decisions/
│       └── 2026-04-05-api-design.md
└── config.yaml
```

Each `.md` file has YAML frontmatter (id, tags, created_at, recall_count) and plain text content. Human-readable, git-friendly, version-controllable.

### Search

Full-text search via SQLite FTS5 (built into every language runtime). No embeddings, no vector database. Optional local embeddings for semantic search.

### Governance

When used with the Astrocyte framework (Python), the full policy layer applies — PII scanning, rate limits, quotas, access control, hooks. When used standalone (MCP/CLI), basic governance is built-in.

## Shared specification

See [docs/README.md](docs/README.md) for the specification index. All implementations must conform to:

- [Context Tree Format](docs/context-tree-format.md) — file structure, frontmatter schema
- [Search Contract](docs/search-contract.md) — query behavior, ranking, test vectors
- [MCP Tools](docs/mcp-tools.md) — tool schemas, parameter types, return formats
- [CLI Reference](docs/cli-reference.md) — commands, flags, output formats

## License

Apache 2.0
