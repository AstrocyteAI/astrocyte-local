# CLI reference

Defines the CLI commands that all Astrocyte Local implementations must provide. Same commands, same flags, same output format across TypeScript, Python, and Rust.

---

## 1. Global flags

| Flag | Short | Default | Description |
|---|---|---|---|
| `--root` | `-r` | `.astrocyte` | Context Tree root directory |
| `--bank` | `-b` | `project` | Memory bank ID |
| `--format` | `-f` | `text` | Output format: `text`, `json` |
| `--help` | `-h` | | Show help |
| `--version` | `-V` | | Show version |

## 2. Commands

### `retain` — Store content

```bash
astrocyte-local retain "Calvin prefers dark mode" --tags preference,ui
astrocyte-local retain --file notes.txt --domain architecture
echo "Pipeline uses GitHub Actions" | astrocyte-local retain --stdin
```

| Flag | Description |
|---|---|
| `--tags` | Comma-separated tags |
| `--domain` | Context Tree domain (auto-inferred if omitted) |
| `--file` | Read content from file |
| `--stdin` | Read content from stdin |
| `--occurred-at` | ISO 8601 timestamp for when the event happened |

**Output (text):**
```
Stored: a1b2c3d4e5f6 → preferences/dark-mode.md
```

**Output (json):**
```json
{"stored": true, "memory_id": "a1b2c3d4e5f6", "domain": "preferences", "file": "dark-mode.md"}
```

### `search` — Search memory

```bash
astrocyte-local search "dark mode"
astrocyte-local search "deployment" --tags technical --max-results 5
```

| Flag | Description |
|---|---|
| `--tags` | Filter by tags (comma-separated) |
| `--max-results` | Maximum results (default: 10) |
| `--layers` | Filter by memory layers (comma-separated) |

**Output (text):**
```
[0.92] preferences/dark-mode.md
  Calvin prefers dark mode in all applications

[0.78] architecture/deployment.md
  The deployment pipeline uses GitHub Actions with a 10-minute timeout
```

**Output (json):**
```json
{"hits": [{"score": 0.92, "text": "...", "domain": "preferences", "file": "dark-mode.md", "memory_id": "a1b2c3"}]}
```

### `browse` — Browse the Context Tree

```bash
astrocyte-local browse                     # List domains
astrocyte-local browse preferences         # List entries in a domain
astrocyte-local browse preferences/dark-mode.md  # Show a specific entry
```

**Output (text):**
```
.astrocyte/memory/
  preferences/     (3 entries)
  architecture/    (5 entries)
  decisions/       (2 entries)
```

### `forget` — Remove memories

```bash
astrocyte-local forget a1b2c3d4e5f6
astrocyte-local forget --domain decisions --all
```

| Flag | Description |
|---|---|
| `--all` | Remove all memories in the specified domain or bank |
| `--domain` | Target a specific domain |

### `export` — Export to AMA format

```bash
astrocyte-local export --output backup.ama.jsonl
astrocyte-local export --format ama > backup.jsonl
```

| Flag | Description |
|---|---|
| `--output` | Output file path |
| `--format` | `ama` (default) — Astrocyte Memory Archive JSONL |

### `import` — Import from AMA format

```bash
astrocyte-local import backup.ama.jsonl
astrocyte-local import --on-conflict skip backup.jsonl
```

| Flag | Description |
|---|---|
| `--on-conflict` | `skip` (default), `overwrite`, `error` |

### `rebuild-index` — Rebuild the search index

```bash
astrocyte-local rebuild-index
```

Scans all `.md` files and rebuilds the SQLite FTS5 index. Useful after manual file edits.

### `health` — System health check

```bash
astrocyte-local health
```

**Output:**
```
Status: healthy
Root: .astrocyte
Memories: 42
Banks: project, personal
Index: current (last built 2s ago)
```

## 3. MCP server command

```bash
# Start as MCP server (stdio transport)
astrocyte-local mcp

# Or via dedicated binary
astrocyte-local-mcp --root .astrocyte

# SSE transport
astrocyte-local mcp --transport sse --port 8090
```

## 4. Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | General error |
| 2 | Invalid arguments |
| 3 | File not found |
| 4 | Bank not found |
