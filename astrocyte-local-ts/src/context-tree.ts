/**
 * Context Tree — hierarchical markdown file storage.
 *
 * Stores memories as .md files with YAML frontmatter in a
 * domain-based directory structure. See docs/context-tree-format.md.
 */

// TODO: Implement in Phase 1
// - store(content, bank_id, domain?, tags?) → MemoryEntry
// - read(id) → MemoryEntry | null
// - update(id, content) → void
// - delete(id) → void
// - listDomains(bank_id) → string[]
// - listEntries(bank_id, domain) → MemoryEntry[]
// - scanAll(bank_id) → MemoryEntry[]

export class ContextTree {
  constructor(private root: string) {}
}
