# Search contract

Defines the search behavior that all Astrocyte Local implementations must provide. This ensures consistent recall results across TypeScript, Python, and Rust.

---

## 1. Search engine

All implementations use **SQLite FTS5** for full-text search. SQLite is available in every target language runtime without external dependencies.

### Index schema

```sql
CREATE VIRTUAL TABLE memory_fts USING fts5(
    id,
    bank_id,
    text,
    tags,
    domain,
    memory_layer,
    fact_type,
    tokenize='porter unicode61'
);
```

The `porter` tokenizer with `unicode61` provides stemming and Unicode normalization.

### Index lifecycle

- **Build:** On first startup or when `_search.db` is missing, scan all `.md` files and populate the FTS index.
- **Incremental update:** On retain, add the new entry to the index. On forget, remove it.
- **Rebuild:** If the index is stale (modification time of `_search.db` < newest `.md` file), rebuild.

## 2. Query behavior

### Basic search

```
search(query, bank_id, limit=10) → list[SearchHit]
```

- Tokenize query using FTS5's built-in tokenizer
- Match against `text`, `tags`, and `domain` columns
- Filter by `bank_id` (always required)
- Return top `limit` results ranked by FTS5 BM25 score

### Tag filtering

```
search(query, bank_id, tags=["preference"]) → list[SearchHit]
```

- Results must contain ALL specified tags
- Tags are stored as space-separated values in the FTS `tags` column

### Time range filtering

```
search(query, bank_id, time_range=(start, end)) → list[SearchHit]
```

- Filter by `occurred_at` (or `created_at` if `occurred_at` is null)
- Time range is inclusive on both ends

### Memory layer filtering

```
search(query, bank_id, layers=["observation", "model"]) → list[SearchHit]
```

- Filter by `memory_layer` values

## 3. SearchHit format

```
SearchHit:
    id: string           # Memory ID from frontmatter
    text: string         # Full content body
    score: float         # BM25 relevance score (0.0 - 1.0 normalized)
    bank_id: string
    memory_layer: string | null
    fact_type: string | null
    tags: list[string]
    occurred_at: string | null   # ISO 8601
    metadata: map | null
    domain: string       # Directory name
    file_path: string    # Relative path to .md file
```

### Score normalization

FTS5 BM25 returns negative scores (more negative = more relevant). Normalize to 0.0-1.0:

```
normalized = 1.0 / (1.0 + abs(raw_bm25_score))
```

Alternatively, if the maximum absolute score in the result set is known:

```
normalized = abs(raw_score) / abs(max_score)
```

Implementations may choose either normalization, but must document which one they use.

## 4. Wildcard query

```
search("*", bank_id) → all memories in the bank
```

Used by export operations. Returns all entries sorted by `created_at` descending.

## 5. Test vectors

All implementations must pass these test cases:

### Test 1: Basic keyword match

```
Retain: "Calvin prefers dark mode in all applications" (bank_id="test", tags=["preference"])
Search: query="dark mode", bank_id="test"
Expected: at least 1 result containing "dark mode"
```

### Test 2: Stemming

```
Retain: "The deployment pipeline uses GitHub Actions" (bank_id="test")
Search: query="deploying", bank_id="test"
Expected: at least 1 result (porter stemmer matches deploy* → deployment)
```

### Test 3: Tag filtering

```
Retain: "Memory A" (bank_id="test", tags=["alpha"])
Retain: "Memory B" (bank_id="test", tags=["beta"])
Search: query="Memory", bank_id="test", tags=["alpha"]
Expected: only Memory A returned
```

### Test 4: Bank isolation

```
Retain: "Secret" (bank_id="bank-1")
Search: query="Secret", bank_id="bank-2"
Expected: 0 results
```

### Test 5: Wildcard

```
Retain: "Memory 1" (bank_id="test")
Retain: "Memory 2" (bank_id="test")
Search: query="*", bank_id="test"
Expected: 2 results
```
