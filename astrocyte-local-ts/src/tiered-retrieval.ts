/**
 * Tiered retrieval for local Context Tree — cache → FTS5 → LLM-guided.
 *
 * 3-tier progressive escalation adapted for file-based storage:
 *   Tier 0: In-memory result cache (exact/fuzzy query match)
 *   Tier 1: FTS5 keyword search (standard)
 *   Tier 2: LLM-guided query reformulation + FTS5 retry
 *
 * Stops when sufficient results are found. No embeddings needed.
 */

import type { SearchHit } from "./types.js";
import type { SearchEngine } from "./search.js";
import type { LLMProvider } from "./curated-retain.js";

// ── Recall Cache ──

interface CacheEntry {
  query: string;
  bankId: string;
  hits: SearchHit[];
  timestamp: number;
}

export class LocalRecallCache {
  private cache = new Map<string, CacheEntry>();

  constructor(
    private maxEntries: number = 128,
    private ttlMs: number = 120_000
  ) {}

  get(query: string, bankId: string): SearchHit[] | null {
    const key = `${bankId}:${query.toLowerCase().trim()}`;
    const entry = this.cache.get(key);
    if (!entry) return null;

    // Check TTL
    if (performance.now() - entry.timestamp > this.ttlMs) {
      this.cache.delete(key);
      return null;
    }

    return entry.hits;
  }

  put(query: string, bankId: string, hits: SearchHit[]): void {
    const key = `${bankId}:${query.toLowerCase().trim()}`;

    // LRU eviction
    while (this.cache.size >= this.maxEntries) {
      const oldestKey = this.cache.keys().next().value!;
      this.cache.delete(oldestKey);
    }

    this.cache.set(key, {
      query,
      bankId,
      hits,
      timestamp: performance.now(),
    });
  }

  invalidateBank(bankId: string): void {
    const prefix = `${bankId}:`;
    for (const key of [...this.cache.keys()]) {
      if (key.startsWith(prefix)) {
        this.cache.delete(key);
      }
    }
  }

  invalidateAll(): void {
    this.cache.clear();
  }

  size(): number {
    return this.cache.size;
  }
}

// ── Tiered Retriever ──

export class LocalTieredRetriever {
  readonly maxTier: number;

  constructor(
    private search: SearchEngine,
    private cache: LocalRecallCache | null = null,
    private llmProvider: LLMProvider | null = null,
    private minResults: number = 2,
    private minScore: number = 0.3,
    maxTier: number = 1
  ) {
    this.maxTier = Math.min(maxTier, 2);
  }

  /**
   * Run tiered retrieval. Returns [hits, tierUsed].
   */
  retrieve(
    query: string,
    bankId: string,
    options?: { limit?: number; tags?: string[] }
  ): [SearchHit[], number] {
    const limit = options?.limit ?? 10;
    const tags = options?.tags;

    // ── Tier 0: Cache ──
    if (this.cache && this.maxTier >= 0) {
      const cached = this.cache.get(query, bankId);
      if (cached !== null) {
        return [cached.slice(0, limit), 0];
      }
    }

    // ── Tier 1: FTS5 search ──
    let hits: SearchHit[] = [];
    if (this.maxTier >= 1) {
      hits = this.search.search(query, bankId, { limit, tags });
      if (this.sufficient(hits) || this.maxTier <= 1) {
        if (this.cache && hits.length > 0) {
          this.cache.put(query, bankId, hits);
        }
        return [hits, 1];
      }
    }

    // ── Tier 2: LLM-guided reformulation (sync path — skip if in async context) ──
    // TypeScript doesn't have asyncio.run() equivalent, so tier 2
    // is only available via aretrieve(). Cache whatever we have.
    if (this.cache && hits.length > 0) {
      this.cache.put(query, bankId, hits);
    }
    return [hits.slice(0, limit), Math.max(this.maxTier >= 1 ? 1 : 0, 0)];
  }

  /**
   * Async version of retrieve — supports LLM reformulation natively.
   */
  async aretrieve(
    query: string,
    bankId: string,
    options?: { limit?: number; tags?: string[] }
  ): Promise<[SearchHit[], number]> {
    const limit = options?.limit ?? 10;
    const tags = options?.tags;

    // ── Tier 0: Cache ──
    if (this.cache && this.maxTier >= 0) {
      const cached = this.cache.get(query, bankId);
      if (cached !== null) {
        return [cached.slice(0, limit), 0];
      }
    }

    // ── Tier 1: FTS5 search ──
    let hits: SearchHit[] = [];
    if (this.maxTier >= 1) {
      hits = this.search.search(query, bankId, { limit, tags });
      if (this.sufficient(hits) || this.maxTier <= 1) {
        if (this.cache && hits.length > 0) {
          this.cache.put(query, bankId, hits);
        }
        return [hits, 1];
      }
    }

    // ── Tier 2: LLM-guided reformulation ──
    if (this.maxTier >= 2 && this.llmProvider) {
      const reformulated = await this.reformulate(query);
      if (reformulated !== query) {
        const hits2 = this.search.search(reformulated, bankId, { limit, tags });
        const merged = LocalTieredRetriever.mergeHits(hits, hits2);
        if (this.cache) {
          this.cache.put(query, bankId, merged);
        }
        return [merged.slice(0, limit), 2];
      }
    }

    // Cache whatever we have from tier 1
    if (this.cache && hits.length > 0) {
      this.cache.put(query, bankId, hits);
    }
    return [hits.slice(0, limit), Math.max(this.maxTier, 0)];
  }

  private sufficient(hits: SearchHit[]): boolean {
    if (hits.length < this.minResults) return false;
    const avgScore =
      hits.reduce((sum, h) => sum + h.score, 0) / Math.max(hits.length, 1);
    return avgScore >= this.minScore;
  }

  private async reformulate(query: string): Promise<string> {
    if (!this.llmProvider) return query;

    const prompt =
      "Reformulate this search query to improve keyword-based search results. " +
      "Add synonyms and related terms. Return only the reformulated query.\n\n" +
      `Query: ${query}`;

    try {
      const completion = await this.llmProvider.complete({
        messages: [{ role: "user", content: prompt }],
        maxTokens: 100,
        temperature: 0.3,
      });
      return completion.text.trim() || query;
    } catch {
      return query;
    }
  }

  /**
   * Merge two hit lists, deduplicate by ID, keep highest score.
   */
  static mergeHits(hitsA: SearchHit[], hitsB: SearchHit[]): SearchHit[] {
    const best = new Map<string, SearchHit>();
    for (const h of [...hitsA, ...hitsB]) {
      const prev = best.get(h.id);
      if (!prev || h.score > prev.score) {
        best.set(h.id, h);
      }
    }
    return [...best.values()].sort((a, b) => b.score - a.score);
  }
}
