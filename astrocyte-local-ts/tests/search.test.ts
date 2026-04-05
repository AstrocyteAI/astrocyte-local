import { describe, it, expect, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { ContextTree } from "../src/context-tree.js";
import { SearchEngine } from "../src/search.js";

let tmpDir: string;
let tree: ContextTree;
let search: SearchEngine;

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "astrocyte-search-test-"));
  tree = new ContextTree(tmpDir);
  search = new SearchEngine(path.join(tmpDir, "_search.db"));
});

afterEach(() => {
  search.close();
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

describe("SearchEngine", () => {
  // ── Test Vector 1: Basic keyword match ──
  describe("basic keyword match", () => {
    it("finds memories by keyword", () => {
      const entry = tree.store({
        content: "Calvin prefers dark mode in all applications",
        bank_id: "test",
        tags: ["preference"],
      });
      search.addDocument(entry);

      const hits = search.search("dark mode", "test");
      expect(hits.length).toBeGreaterThanOrEqual(1);
      expect(hits[0].text).toContain("dark mode");
    });
  });

  // ── Test Vector 2: Stemming ──
  describe("stemming", () => {
    it("matches stemmed forms (deploy → deployment)", () => {
      const entry = tree.store({
        content: "The deploy pipeline uses GitHub Actions",
        bank_id: "test",
      });
      search.addDocument(entry);

      const hits = search.search("deploying", "test");
      expect(hits.length).toBeGreaterThanOrEqual(1);
    });
  });

  // ── Test Vector 3: Tag filtering ──
  describe("tag filtering", () => {
    it("filters by tags", () => {
      const a = tree.store({
        content: "Memory A content",
        bank_id: "test",
        tags: ["alpha"],
      });
      const b = tree.store({
        content: "Memory B content",
        bank_id: "test",
        tags: ["beta"],
      });
      search.addDocument(a);
      search.addDocument(b);

      const hits = search.search("Memory", "test", { tags: ["alpha"] });
      expect(hits.length).toBe(1);
      expect(hits[0].text).toContain("Memory A");
    });
  });

  // ── Test Vector 4: Bank isolation ──
  describe("bank isolation", () => {
    it("isolates memories by bank", () => {
      const entry = tree.store({
        content: "Secret information",
        bank_id: "bank-1",
      });
      search.addDocument(entry);

      const hits = search.search("Secret", "bank-2");
      expect(hits.length).toBe(0);
    });
  });

  // ── Test Vector 5: Wildcard ──
  describe("wildcard query", () => {
    it("returns all memories with * query", () => {
      const a = tree.store({ content: "Memory 1", bank_id: "test" });
      const b = tree.store({ content: "Memory 2", bank_id: "test" });
      search.addDocument(a);
      search.addDocument(b);

      const hits = search.search("*", "test");
      expect(hits.length).toBe(2);
    });
  });

  describe("buildIndex", () => {
    it("rebuilds index from context tree", () => {
      tree.store({ content: "Entry one", bank_id: "test" });
      tree.store({ content: "Entry two", bank_id: "test" });

      const count = search.buildIndex(tree);
      expect(count).toBe(2);

      const hits = search.search("Entry", "test");
      expect(hits.length).toBe(2);
    });

    it("rebuilds for specific bank", () => {
      tree.store({ content: "Bank A entry", bank_id: "a" });
      tree.store({ content: "Bank B entry", bank_id: "b" });

      search.buildIndex(tree, "a");
      const hitsA = search.search("entry", "a");
      expect(hitsA.length).toBe(1);
    });
  });

  describe("addDocument / removeDocument", () => {
    it("adds and removes documents incrementally", () => {
      const entry = tree.store({ content: "Temporary", bank_id: "test" });
      search.addDocument(entry);

      let hits = search.search("Temporary", "test");
      expect(hits.length).toBe(1);

      search.removeDocument(entry.id);
      hits = search.search("Temporary", "test");
      expect(hits.length).toBe(0);
    });
  });

  describe("score normalization", () => {
    it("returns scores between 0 and 1", () => {
      const a = tree.store({
        content: "TypeScript is a great programming language",
        bank_id: "test",
      });
      const b = tree.store({
        content: "Python is also a good language for scripting",
        bank_id: "test",
      });
      search.addDocument(a);
      search.addDocument(b);

      const hits = search.search("programming language", "test");
      for (const h of hits) {
        expect(h.score).toBeGreaterThanOrEqual(0);
        expect(h.score).toBeLessThanOrEqual(1);
      }
    });
  });

  describe("layer filtering", () => {
    it("filters by memory layer", () => {
      const fact = tree.store({
        content: "A factual memory",
        bank_id: "test",
        memory_layer: "fact",
      });
      const obs = tree.store({
        content: "An observed memory",
        bank_id: "test",
        memory_layer: "observation",
      });
      search.addDocument(fact);
      search.addDocument(obs);

      const hits = search.search("memory", "test", { layers: ["fact"] });
      expect(hits.length).toBe(1);
      expect(hits[0].memory_layer).toBe("fact");
    });
  });

  describe("escapeFtsQuery", () => {
    it("strips special FTS5 characters", () => {
      expect(SearchEngine.escapeFtsQuery('"hello" (world)')).toBe("hello world");
      expect(SearchEngine.escapeFtsQuery("test:query")).toBe("test query");
      expect(SearchEngine.escapeFtsQuery("")).toBe("");
    });
  });
});
