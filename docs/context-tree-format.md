# Context Tree format

The Context Tree is the storage format for Astrocyte Local. All implementations (TypeScript, Python, Rust) must produce and consume this exact format for cross-language compatibility.

---

## 1. Directory structure

```
{root}/
├── memory/
│   ├── {domain}/
│   │   ├── {topic}.md
│   │   └── {topic}.md
│   └── {domain}/
│       └── {topic}.md
├── _index.json            # Bank metadata + search index state
└── config.yaml            # Local configuration
```

- `{root}` is configurable (default: `.astrocyte` in the current directory)
- `memory/` contains all memory files organized by domain
- Domains are top-level directories (e.g., `preferences/`, `architecture/`, `decisions/`)
- Each memory is a single `.md` file within a domain

## 2. Memory file format

Each `.md` file has YAML frontmatter followed by content:

```markdown
---
id: "a1b2c3d4e5f6"
bank_id: "project"
memory_layer: "fact"
fact_type: "experience"
tags: ["preference", "ui"]
created_at: "2026-04-05T10:30:00Z"
updated_at: "2026-04-05T10:30:00Z"
occurred_at: "2026-04-05T10:30:00Z"
recall_count: 3
last_recalled_at: "2026-04-05T14:00:00Z"
source: "mcp:claude-code"
metadata:
  session_id: "sess-123"
---

Calvin prefers dark mode in all applications. This was mentioned during the
initial project setup conversation.
```

### Required frontmatter fields

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique memory ID (12-char hex recommended) |
| `bank_id` | string | Memory bank this entry belongs to |
| `created_at` | ISO 8601 | When the memory was stored |

### Optional frontmatter fields

| Field | Type | Default | Description |
|---|---|---|---|
| `memory_layer` | string | `"fact"` | `"fact"`, `"observation"`, or `"model"` |
| `fact_type` | string | `"world"` | `"world"`, `"experience"`, `"observation"` |
| `tags` | list[string] | `[]` | Filtering tags |
| `updated_at` | ISO 8601 | same as created_at | Last modification time |
| `occurred_at` | ISO 8601 | null | When the event described happened |
| `recall_count` | integer | `0` | How many times this memory has been recalled |
| `last_recalled_at` | ISO 8601 | null | Last recall timestamp |
| `source` | string | null | Origin identifier (e.g., `"mcp:claude-code"`, `"api:retain"`) |
| `metadata` | map | `{}` | Arbitrary key-value metadata |

## 3. File naming

- Filenames are derived from the content: first 50 chars, lowercased, non-alphanumeric replaced with hyphens, truncated
- If a collision occurs, append `-{n}` (e.g., `dark-mode-2.md`)
- The `id` in frontmatter is the authoritative identifier, not the filename

## 4. Domain inference

When the caller does not specify a domain:
- If LLM curation is available, the LLM classifies the domain
- Otherwise, use `"general"` as the default domain

## 5. Bank isolation

Memories are scoped by `bank_id` in the frontmatter. A single Context Tree root can hold multiple banks. Search operations always filter by `bank_id`.

## 6. Index file (`_index.json`)

```json
{
  "version": 1,
  "bank_ids": ["project", "personal"],
  "total_memories": 42,
  "last_indexed_at": "2026-04-05T10:30:00Z",
  "fts_index_path": "_search.db"
}
```

The FTS search index (`_search.db`) is a SQLite database with FTS5 tables. It is **derived** from the markdown files and can be rebuilt at any time. Implementations should rebuild the index on startup if it's missing or stale.

## 7. AMA compatibility

The Context Tree can be exported to Astrocyte Memory Archive (AMA) JSONL format:

```
frontmatter fields → AMA fields (direct mapping)
content body → AMA "text" field
```

And imported from AMA:

```
AMA "text" → content body
AMA fields → frontmatter fields
Domain inferred from tags or metadata
```
