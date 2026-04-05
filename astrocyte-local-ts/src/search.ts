/**
 * Search engine — SQLite FTS5 full-text search.
 *
 * See docs/search-contract.md for behavior specification.
 */

// TODO: Implement in Phase 1
// - buildIndex() — scan all .md files, populate FTS5
// - search(query, bank_id, options?) → SearchHit[]
// - addDocument(entry) — incremental index update
// - removeDocument(id) — incremental removal
// - rebuild() — full index rebuild

export class SearchEngine {
  constructor(private dbPath: string) {}
}
