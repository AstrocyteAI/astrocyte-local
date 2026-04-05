/**
 * Search engine — SQLite FTS5 full-text search.
 *
 * See docs/search-contract.md for behavior specification.
 * All operations are sync. Uses better-sqlite3 for SQLite access.
 */

import Database from "better-sqlite3";
import path from "node:path";
import fs from "node:fs";
import type { MemoryEntry, SearchHit } from "./types.js";
import type { ContextTree } from "./context-tree.js";

export class SearchEngine {
  private db: Database.Database;

  constructor(private dbPath: string) {
    const dir = path.dirname(dbPath);
    fs.mkdirSync(dir, { recursive: true });
    this.db = new Database(dbPath);
    this.db.pragma("journal_mode = WAL");
    this.createTables();
  }

  private createTables(): void {
    this.db.exec(`
      CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
        id,
        bank_id,
        text,
        tags,
        domain,
        memory_layer,
        fact_type,
        file_path,
        tokenize='porter unicode61'
      );
    `);
  }

  /**
   * Rebuild the FTS index from the Context Tree. Returns count indexed.
   */
  buildIndex(tree: ContextTree, bankId?: string): number {
    if (bankId) {
      this.db.prepare("DELETE FROM memory_fts WHERE bank_id = ?").run(bankId);
    } else {
      this.db.exec("DELETE FROM memory_fts");
    }

    const entries = tree.scanAll(bankId);
    const insert = this.db.prepare(
      `INSERT INTO memory_fts (id, bank_id, text, tags, domain, memory_layer, fact_type, file_path)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
    );

    const insertMany = this.db.transaction((entries: MemoryEntry[]) => {
      for (const entry of entries) {
        insert.run(
          entry.id,
          entry.bank_id,
          entry.text,
          entry.tags.join(" "),
          entry.domain,
          entry.memory_layer,
          entry.fact_type,
          entry.file_path
        );
      }
    });

    insertMany(entries);
    return entries.length;
  }

  /**
   * Full-text search. Returns scored hits sorted by relevance.
   */
  search(
    query: string,
    bankId: string,
    options?: {
      limit?: number;
      tags?: string[];
      layers?: string[];
    }
  ): SearchHit[] {
    const limit = options?.limit ?? 10;
    const tags = options?.tags;
    const layers = options?.layers;

    if (query.trim() === "*") {
      return this.searchAll(bankId, { limit, tags, layers });
    }

    const ftsQuery = SearchEngine.escapeFtsQuery(query);
    if (!ftsQuery) return [];

    let rows: Record<string, unknown>[];
    try {
      rows = this.db
        .prepare(
          `SELECT id, bank_id, text, tags, domain, memory_layer, fact_type, file_path, rank
           FROM memory_fts
           WHERE memory_fts MATCH ? AND bank_id = ?
           ORDER BY rank
           LIMIT ?`
        )
        .all(ftsQuery, bankId, limit * 3) as Record<string, unknown>[];
    } catch {
      return [];
    }

    let hits = this.rowsToHits(rows);

    // Post-filter by tags
    if (tags && tags.length > 0) {
      const tagSet = new Set(tags);
      hits = hits.filter(
        (h) => h.tags && tagSet.size > 0 && [...tagSet].every((t) => h.tags.includes(t))
      );
    }

    // Post-filter by layers
    if (layers && layers.length > 0) {
      hits = hits.filter((h) => h.memory_layer && layers.includes(h.memory_layer));
    }

    return hits.slice(0, limit);
  }

  /**
   * Add a single entry to the index (incremental update).
   */
  addDocument(entry: MemoryEntry): void {
    this.db
      .prepare(
        `INSERT INTO memory_fts (id, bank_id, text, tags, domain, memory_layer, fact_type, file_path)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
      )
      .run(
        entry.id,
        entry.bank_id,
        entry.text,
        entry.tags.join(" "),
        entry.domain,
        entry.memory_layer,
        entry.fact_type,
        entry.file_path
      );
  }

  /**
   * Remove a single entry from the index.
   */
  removeDocument(entryId: string): void {
    this.db.prepare("DELETE FROM memory_fts WHERE id = ?").run(entryId);
  }

  /**
   * Close the database connection.
   */
  close(): void {
    this.db.close();
  }

  // ── Internal ──

  private searchAll(
    bankId: string,
    options: { limit: number; tags?: string[]; layers?: string[] }
  ): SearchHit[] {
    const rows = this.db
      .prepare(
        `SELECT id, bank_id, text, tags, domain, memory_layer, fact_type, file_path, 0 as rank
         FROM memory_fts WHERE bank_id = ? LIMIT ?`
      )
      .all(bankId, options.limit) as Record<string, unknown>[];

    let hits = this.rowsToHits(rows, 1.0);

    if (options.tags && options.tags.length > 0) {
      const tagSet = new Set(options.tags);
      hits = hits.filter(
        (h) => h.tags && [...tagSet].every((t) => h.tags.includes(t))
      );
    }

    if (options.layers && options.layers.length > 0) {
      hits = hits.filter(
        (h) => h.memory_layer && options.layers!.includes(h.memory_layer)
      );
    }

    return hits;
  }

  private rowsToHits(
    rows: Record<string, unknown>[],
    defaultScore?: number
  ): SearchHit[] {
    if (rows.length === 0) return [];

    // Normalize BM25 scores (more negative = more relevant)
    const rawScores = rows.map((r) => Math.abs(Number(r.rank)));
    const maxScore = Math.max(...rawScores) || 1.0;

    return rows.map((row) => {
      const score =
        defaultScore !== undefined
          ? defaultScore
          : maxScore > 0
            ? Math.abs(Number(row.rank)) / maxScore
            : 0.5;

      const tagStr = (row.tags as string) || "";
      const tags = tagStr.split(/\s+/).filter(Boolean);

      return {
        id: row.id as string,
        text: row.text as string,
        score,
        bank_id: row.bank_id as string,
        domain: row.domain as string,
        file_path: row.file_path as string,
        memory_layer: (row.memory_layer as string) || undefined,
        fact_type: (row.fact_type as string) || undefined,
        tags,
      };
    });
  }

  /**
   * Escape special FTS5 characters for safe querying.
   * Does NOT quote individual tokens — quoting disables stemming.
   */
  static escapeFtsQuery(query: string): string {
    let cleaned = query
      .replace(/"/g, " ")
      .replace(/'/g, " ")
      .replace(/\(/g, " ")
      .replace(/\)/g, " ")
      .replace(/:/g, " ")
      .replace(/\^/g, " ");

    const tokens = cleaned.split(/\s+/).filter(Boolean);
    return tokens.join(" ");
  }
}
