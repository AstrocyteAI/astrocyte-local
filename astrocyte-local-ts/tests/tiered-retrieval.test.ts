import { describe, it, expect, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { ContextTree } from "../src/context-tree.js";
import { SearchEngine } from "../src/search.js";
import {
  LocalRecallCache,
  LocalTieredRetriever,
} from "../src/tiered-retrieval.js";
import type { SearchHit } from "../src/types.js";

// ── LocalRecallCache ���─

describe("LocalRecallCache", () => {
  it("returns null on cache miss", () => {
    const cache = new LocalRecallCache();
    expect(cache.get("test query", "bank-1")).toBeNull();
  });

  it("returns hits on cache hit", () => {
    const cache = new LocalRecallCache();
    const hits: SearchHit[] = [
      {
        id: "m1",
        text: "cached",
        score: 0.9,
        bank_id: "b1",
        domain: "test",
        file_path: "test.md",
        tags: [],
      },
    ];
    cache.put("test query", "bank-1", hits);

    const result = cache.get("test query", "bank-1");
    expect(result).not.toBeNull();
    expect(result![0].text).toBe("cached");
  });

  it("is case insensitive", () => {
    const cache = new LocalRecallCache();
    const hits: SearchHit[] = [
      {
        id: "m1",
        text: "cached",
        score: 0.9,
        bank_id: "b1",
        domain: "test",
        file_path: "test.md",
        tags: [],
      },
    ];
    cache.put("Dark Mode", "bank-1", hits);

    expect(cache.get("dark mode", "bank-1")).not.toBeNull();
    expect(cache.get("DARK MODE", "bank-1")).not.toBeNull();
  });

  it("isolates by bank", () => {
    const cache = new LocalRecallCache();
    const hits: SearchHit[] = [
      {
        id: "m1",
        text: "cached",
        score: 0.9,
        bank_id: "b1",
        domain: "test",
        file_path: "test.md",
        tags: [],
      },
    ];
    cache.put("query", "bank-1", hits);

    expect(cache.get("query", "bank-2")).toBeNull();
  });

  it("invalidates by bank", () => {
    const cache = new LocalRecallCache();
    const hits: SearchHit[] = [
      {
        id: "m1",
        text: "cached",
        score: 0.9,
        bank_id: "b1",
        domain: "test",
        file_path: "test.md",
        tags: [],
      },
    ];
    cache.put("query", "bank-1", hits);
    expect(cache.size()).toBe(1);

    cache.invalidateBank("bank-1");
    expect(cache.size()).toBe(0);
    expect(cache.get("query", "bank-1")).toBeNull();
  });

  it("expires entries by TTL", async () => {
    const cache = new LocalRecallCache(128, 10); // 10ms TTL
    const hits: SearchHit[] = [
      {
        id: "m1",
        text: "cached",
        score: 0.9,
        bank_id: "b1",
        domain: "test",
        file_path: "test.md",
        tags: [],
      },
    ];
    cache.put("query", "bank-1", hits);

    await new Promise((r) => setTimeout(r, 20));
    expect(cache.get("query", "bank-1")).toBeNull();
  });

  it("evicts oldest on LRU overflow", () => {
    const cache = new LocalRecallCache(2, 120_000);
    for (let i = 0; i < 3; i++) {
      const hits: SearchHit[] = [
        {
          id: `m${i}`,
          text: `hit${i}`,
          score: 0.9,
          bank_id: "b1",
          domain: "test",
          file_path: "t.md",
          tags: [],
        },
      ];
      cache.put(`query-${i}`, "bank-1", hits);
    }

    expect(cache.size()).toBe(2);
  });
});

// ── LocalTieredRetriever ──

describe("LocalTieredRetriever", () => {
  let tmpDir: string;
  let tree: ContextTree;
  let search: SearchEngine;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(
      path.join(os.tmpdir(), "astrocyte-tiered-test-")
    );
    tree = new ContextTree(tmpDir);
    search = new SearchEngine(path.join(tmpDir, "_search.db"));
  });

  afterEach(() => {
    search.close();
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it("retrieves via tier 1 FTS5", () => {
    tree.store({
      content: "Dark mode is preferred by Calvin",
      bank_id: "test",
    });
    search.buildIndex(tree);

    const tiered = new LocalTieredRetriever(search, null, null, 2, 0.3, 1);
    const [hits, tier] = tiered.retrieve("dark mode", "test");

    expect(hits.length).toBeGreaterThanOrEqual(1);
    expect(tier).toBe(1);
  });

  it("returns tier 0 on cache hit", () => {
    tree.store({
      content: "Cached content here",
      bank_id: "test",
    });
    search.buildIndex(tree);

    const cache = new LocalRecallCache();
    const tiered = new LocalTieredRetriever(search, cache, null, 2, 0.3, 1);

    // First query — tier 1
    const [, tier1] = tiered.retrieve("Cached content", "test");
    expect(tier1).toBe(1);

    // Second query — tier 0 (cache)
    const [hits2, tier2] = tiered.retrieve("Cached content", "test");
    expect(tier2).toBe(0);
    expect(hits2.length).toBeGreaterThanOrEqual(1);
  });

  it("falls back to tier 1 after cache invalidation", () => {
    tree.store({
      content: "Original content",
      bank_id: "test",
    });
    search.buildIndex(tree);

    const cache = new LocalRecallCache();
    const tiered = new LocalTieredRetriever(search, cache, null, 2, 0.3, 1);

    // Populate cache
    tiered.retrieve("Original", "test");

    // Invalidate
    cache.invalidateBank("test");

    // Should go to tier 1 again
    const [, tier] = tiered.retrieve("Original", "test");
    expect(tier).toBe(1);
  });

  it("respects max_tier=0", () => {
    const tiered = new LocalTieredRetriever(search, null, null, 2, 0.3, 0);
    const [hits, tier] = tiered.retrieve("anything", "test");
    expect(hits).toEqual([]);
    expect(tier).toBe(0);
  });

  it("retrieves async via tier 1", async () => {
    tree.store({
      content: "Async searchable content",
      bank_id: "test",
    });
    search.buildIndex(tree);

    const tiered = new LocalTieredRetriever(search, null, null, 2, 0.3, 1);
    const [hits, tier] = await tiered.aretrieve("Async searchable", "test");

    expect(hits.length).toBeGreaterThanOrEqual(1);
    expect(tier).toBe(1);
  });

  it("returns async tier 0 on cache hit", async () => {
    tree.store({
      content: "Async cached content",
      bank_id: "test",
    });
    search.buildIndex(tree);

    const cache = new LocalRecallCache();
    const tiered = new LocalTieredRetriever(search, cache, null, 2, 0.3, 1);

    await tiered.aretrieve("Async cached", "test");
    const [, tier] = await tiered.aretrieve("Async cached", "test");
    expect(tier).toBe(0);
  });

  describe("mergeHits", () => {
    it("deduplicates by ID keeping highest score", () => {
      const hitsA: SearchHit[] = [
        { id: "1", text: "a", score: 0.5, bank_id: "b", domain: "d", file_path: "f", tags: [] },
        { id: "2", text: "b", score: 0.8, bank_id: "b", domain: "d", file_path: "f", tags: [] },
      ];
      const hitsB: SearchHit[] = [
        { id: "1", text: "a", score: 0.9, bank_id: "b", domain: "d", file_path: "f", tags: [] },
        { id: "3", text: "c", score: 0.7, bank_id: "b", domain: "d", file_path: "f", tags: [] },
      ];

      const merged = LocalTieredRetriever.mergeHits(hitsA, hitsB);
      expect(merged.length).toBe(3);
      // Sorted by score descending
      expect(merged[0].id).toBe("1");
      expect(merged[0].score).toBe(0.9); // Kept higher score
      expect(merged[1].id).toBe("2");
      expect(merged[2].id).toBe("3");
    });
  });
});
