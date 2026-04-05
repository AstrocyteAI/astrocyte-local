# MCP tools

Defines the MCP tool surface that all Astrocyte Local implementations must expose. Identical tool names, schemas, and behaviors across TypeScript, Python, and Rust.

---

## 1. Tools

| Tool | Description |
|---|---|
| `memory_retain` | Store content into local memory |
| `memory_recall` | Search local memory for relevant content |
| `memory_reflect` | Synthesize an answer from local memory (requires LLM) |
| `memory_forget` | Remove memories |
| `memory_browse` | Browse the Context Tree hierarchy (unique to local) |
| `memory_banks` | List available banks |
| `memory_health` | Check system status |

## 2. Tool schemas

### memory_retain

```json
{
  "name": "memory_retain",
  "description": "Store content into local memory for future recall.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "content": { "type": "string", "description": "The text to memorize." },
      "bank_id": { "type": "string", "description": "Memory bank. Uses default if omitted." },
      "tags": { "type": "array", "items": { "type": "string" }, "description": "Optional tags." },
      "domain": { "type": "string", "description": "Context Tree domain (e.g., 'preferences', 'architecture'). Auto-inferred if omitted." }
    },
    "required": ["content"]
  }
}
```

**Returns:** `{"stored": true, "memory_id": "a1b2c3d4e5f6", "domain": "preferences", "file": "dark-mode.md"}`

### memory_recall

```json
{
  "name": "memory_recall",
  "description": "Search local memory for content relevant to a query.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": { "type": "string", "description": "Natural language search query." },
      "bank_id": { "type": "string", "description": "Memory bank. Uses default if omitted." },
      "max_results": { "type": "integer", "default": 10, "description": "Maximum results." },
      "tags": { "type": "array", "items": { "type": "string" }, "description": "Filter by tags." }
    },
    "required": ["query"]
  }
}
```

**Returns:** `{"hits": [{"text": "...", "score": 0.85, "domain": "preferences", "file": "dark-mode.md", "memory_id": "..."}], "total": 5}`

### memory_reflect

```json
{
  "name": "memory_reflect",
  "description": "Synthesize an answer from local memory. Requires an LLM provider.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": { "type": "string", "description": "The question to answer from memory." },
      "bank_id": { "type": "string", "description": "Memory bank." },
      "max_tokens": { "type": "integer", "description": "Maximum tokens for the answer." }
    },
    "required": ["query"]
  }
}
```

**Returns:** `{"answer": "Based on your memories, Calvin prefers...", "sources": [...]}`

If no LLM is configured, returns an error: `{"error": "reflect requires an LLM provider"}`

### memory_browse

```json
{
  "name": "memory_browse",
  "description": "Browse the Context Tree hierarchy. Lists domains, topics, and memory titles.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": { "type": "string", "description": "Path to browse (e.g., '' for root, 'preferences' for a domain). Default: root." },
      "bank_id": { "type": "string", "description": "Memory bank." }
    }
  }
}
```

**Returns:**
```json
{
  "path": "",
  "domains": ["preferences", "architecture", "decisions"],
  "entries": [],
  "total_memories": 42
}
```

Or for a specific domain:
```json
{
  "path": "preferences",
  "domains": [],
  "entries": [
    {"file": "dark-mode.md", "title": "Calvin prefers dark mode", "memory_id": "a1b2c3", "recall_count": 5},
    {"file": "languages.md", "title": "Calvin's favorite is Python", "memory_id": "d4e5f6", "recall_count": 2}
  ],
  "total_memories": 2
}
```

### memory_forget

```json
{
  "name": "memory_forget",
  "description": "Remove memories from local storage.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "memory_ids": { "type": "array", "items": { "type": "string" }, "description": "Specific IDs to delete." },
      "bank_id": { "type": "string", "description": "Memory bank." }
    },
    "required": ["memory_ids"]
  }
}
```

**Returns:** `{"deleted_count": 2, "files_removed": ["preferences/dark-mode.md", "architecture/deploy.md"]}`

### memory_banks

```json
{
  "name": "memory_banks",
  "description": "List available memory banks.",
  "inputSchema": { "type": "object", "properties": {} }
}
```

**Returns:** `{"banks": ["project", "personal"], "default": "project", "root": ".astrocyte"}`

### memory_health

```json
{
  "name": "memory_health",
  "description": "Check local memory system health.",
  "inputSchema": { "type": "object", "properties": {} }
}
```

**Returns:** `{"healthy": true, "total_memories": 42, "index_status": "current", "root": ".astrocyte"}`

## 3. Configuration

MCP server reads configuration from `{root}/config.yaml`:

```yaml
default_bank_id: project
expose_reflect: true
expose_forget: true
```

Or from CLI flags:

```bash
astrocyte-local-mcp --root .astrocyte --default-bank project
```

## 4. Transport

- **stdio** (default) — for local MCP clients (Claude Code, Cursor)
- **SSE** (optional) — for remote access

```bash
# stdio
astrocyte-local-mcp --root .astrocyte

# SSE
astrocyte-local-mcp --root .astrocyte --transport sse --port 8090
```
