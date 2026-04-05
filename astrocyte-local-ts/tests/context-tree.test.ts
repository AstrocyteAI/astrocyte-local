import { describe, it, expect, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { ContextTree } from "../src/context-tree.js";

let tmpDir: string;
let tree: ContextTree;

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "astrocyte-test-"));
  tree = new ContextTree(tmpDir);
});

afterEach(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

describe("ContextTree", () => {
  describe("store", () => {
    it("stores a memory and returns a MemoryEntry", () => {
      const entry = tree.store({
        content: "Calvin prefers dark mode",
        bank_id: "test",
        domain: "preferences",
        tags: ["ui"],
      });

      expect(entry.id).toBeTruthy();
      expect(entry.id.length).toBe(12);
      expect(entry.bank_id).toBe("test");
      expect(entry.text).toBe("Calvin prefers dark mode");
      expect(entry.domain).toBe("preferences");
      expect(entry.tags).toEqual(["ui"]);
      expect(entry.memory_layer).toBe("fact");
      expect(entry.fact_type).toBe("world");
      expect(entry.recall_count).toBe(0);
    });

    it("creates markdown file with YAML frontmatter", () => {
      const entry = tree.store({
        content: "Test content",
        bank_id: "test",
      });

      const fullPath = path.join(tmpDir, "memory", entry.file_path);
      expect(fs.existsSync(fullPath)).toBe(true);

      const raw = fs.readFileSync(fullPath, "utf-8");
      expect(raw).toContain("---");
      expect(raw).toContain(`id: ${entry.id}`);
      expect(raw).toContain("Test content");
    });

    it("uses general domain by default", () => {
      const entry = tree.store({ content: "Hello", bank_id: "test" });
      expect(entry.domain).toBe("general");
    });

    it("handles filename collisions", () => {
      const e1 = tree.store({ content: "Same title", bank_id: "test" });
      const e2 = tree.store({ content: "Same title", bank_id: "test" });

      expect(e1.file_path).not.toBe(e2.file_path);
      expect(e1.id).not.toBe(e2.id);
    });

    it("stores metadata", () => {
      const entry = tree.store({
        content: "With metadata",
        bank_id: "test",
        metadata: { importance: 5, verified: true },
      });

      const read = tree.read(entry.id);
      expect(read).not.toBeNull();
      expect(read!.metadata.importance).toBe(5);
      expect(read!.metadata.verified).toBe(true);
    });
  });

  describe("read", () => {
    it("reads an existing entry by ID", () => {
      const entry = tree.store({ content: "Readable", bank_id: "test" });
      const read = tree.read(entry.id);

      expect(read).not.toBeNull();
      expect(read!.id).toBe(entry.id);
      expect(read!.text).toBe("Readable");
    });

    it("returns null for non-existent ID", () => {
      expect(tree.read("nonexistent")).toBeNull();
    });
  });

  describe("update", () => {
    it("updates content of existing entry", () => {
      const entry = tree.store({ content: "Original", bank_id: "test" });
      const updated = tree.update(entry.id, "Modified");

      expect(updated).not.toBeNull();
      expect(updated!.text).toBe("Modified");
      expect(updated!.updated_at).not.toBe(entry.created_at);
    });

    it("returns null for non-existent ID", () => {
      expect(tree.update("nonexistent", "nope")).toBeNull();
    });
  });

  describe("delete", () => {
    it("deletes an existing entry", () => {
      const entry = tree.store({ content: "Delete me", bank_id: "test" });
      expect(tree.delete(entry.id)).toBe(true);
      expect(tree.read(entry.id)).toBeNull();
    });

    it("returns false for non-existent ID", () => {
      expect(tree.delete("nonexistent")).toBe(false);
    });

    it("cleans up empty domain directories", () => {
      const entry = tree.store({
        content: "Lonely",
        bank_id: "test",
        domain: "temporary",
      });
      const domainDir = path.join(tmpDir, "memory", "temporary");
      expect(fs.existsSync(domainDir)).toBe(true);

      tree.delete(entry.id);
      expect(fs.existsSync(domainDir)).toBe(false);
    });
  });

  describe("recordRecall", () => {
    it("increments recall count and sets last_recalled_at", () => {
      const entry = tree.store({ content: "Recalled", bank_id: "test" });
      expect(entry.recall_count).toBe(0);

      tree.recordRecall(entry.id);
      const read = tree.read(entry.id);
      expect(read!.recall_count).toBe(1);
      expect(read!.last_recalled_at).toBeTruthy();
    });
  });

  describe("listDomains", () => {
    it("lists all domains", () => {
      tree.store({ content: "A", bank_id: "test", domain: "alpha" });
      tree.store({ content: "B", bank_id: "test", domain: "beta" });

      const domains = tree.listDomains();
      expect(domains).toContain("alpha");
      expect(domains).toContain("beta");
    });

    it("filters by bank_id", () => {
      tree.store({ content: "A", bank_id: "bank1", domain: "shared" });
      tree.store({ content: "B", bank_id: "bank2", domain: "private" });

      const domains = tree.listDomains("bank1");
      expect(domains).toContain("shared");
      expect(domains).not.toContain("private");
    });
  });

  describe("listEntries", () => {
    it("lists entries in a domain", () => {
      tree.store({ content: "One", bank_id: "test", domain: "stuff" });
      tree.store({ content: "Two", bank_id: "test", domain: "stuff" });
      tree.store({ content: "Other", bank_id: "test", domain: "other" });

      const entries = tree.listEntries("test", "stuff");
      expect(entries.length).toBe(2);
    });
  });

  describe("scanAll", () => {
    it("returns all entries", () => {
      tree.store({ content: "A", bank_id: "test", domain: "x" });
      tree.store({ content: "B", bank_id: "test", domain: "y" });

      expect(tree.scanAll().length).toBe(2);
    });

    it("filters by bank_id", () => {
      tree.store({ content: "A", bank_id: "bank1" });
      tree.store({ content: "B", bank_id: "bank2" });

      expect(tree.scanAll("bank1").length).toBe(1);
    });
  });

  describe("count", () => {
    it("counts all memories", () => {
      tree.store({ content: "A", bank_id: "test" });
      tree.store({ content: "B", bank_id: "test" });
      expect(tree.count()).toBe(2);
    });

    it("counts by bank", () => {
      tree.store({ content: "A", bank_id: "bank1" });
      tree.store({ content: "B", bank_id: "bank2" });
      expect(tree.count("bank1")).toBe(1);
    });
  });
});
