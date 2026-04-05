import { describe, it, expect, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { parseResponse, curateLocalRetain } from "../src/curated-retain.js";
import type { LLMProvider } from "../src/curated-retain.js";
import { ContextTree } from "../src/context-tree.js";
import { SearchEngine } from "../src/search.js";

describe("parseResponse", () => {
  it("parses valid JSON", () => {
    const response =
      '{"action": "add", "domain": "preferences", "content": "test", "memory_layer": "fact", "reasoning": "new"}';
    const decision = parseResponse(response, "original");
    expect(decision.action).toBe("add");
    expect(decision.domain).toBe("preferences");
    expect(decision.memory_layer).toBe("fact");
  });

  it("parses JSON in code block", () => {
    const response =
      '```json\n{"action": "merge", "domain": "arch", "content": "merged", "memory_layer": "observation", "reasoning": "similar", "target_id": "abc123"}\n```';
    const decision = parseResponse(response, "original");
    expect(decision.action).toBe("merge");
    expect(decision.target_id).toBe("abc123");
  });

  it("falls back on invalid JSON", () => {
    const decision = parseResponse("not json", "original");
    expect(decision.action).toBe("add");
    expect(decision.domain).toBe("general");
    expect(decision.content).toBe("original");
  });

  it("normalizes domain name", () => {
    const response =
      '{"action": "add", "domain": "My Domain / Sub", "content": "test", "memory_layer": "fact", "reasoning": ""}';
    const decision = parseResponse(response, "original");
    expect(decision.domain).toBe("my-domain---sub");
  });

  it("handles skip action", () => {
    const response =
      '{"action": "skip", "domain": "", "content": "", "memory_layer": "fact", "reasoning": "redundant"}';
    const decision = parseResponse(response, "original");
    expect(decision.action).toBe("skip");
  });

  it("handles delete action with target_id", () => {
    const response =
      '{"action": "delete", "domain": "", "content": "", "memory_layer": "fact", "reasoning": "contradicts", "target_id": "old123"}';
    const decision = parseResponse(response, "original");
    expect(decision.action).toBe("delete");
    expect(decision.target_id).toBe("old123");
  });

  it("sanitizes invalid action to add", () => {
    const response =
      '{"action": "invalid_action", "domain": "test", "content": "test", "memory_layer": "fact", "reasoning": ""}';
    const decision = parseResponse(response, "original");
    expect(decision.action).toBe("add");
  });

  it("sanitizes invalid memory_layer to fact", () => {
    const response =
      '{"action": "add", "domain": "test", "content": "test", "memory_layer": "invalid", "reasoning": ""}';
    const decision = parseResponse(response, "original");
    expect(decision.memory_layer).toBe("fact");
  });
});

describe("curateLocalRetain", () => {
  let tmpDir: string;
  let tree: ContextTree;
  let search: SearchEngine;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "astrocyte-curated-test-"));
    tree = new ContextTree(tmpDir);
    search = new SearchEngine(path.join(tmpDir, "_search.db"));
  });

  afterEach(() => {
    search.close();
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it("returns skip when LLM says skip", async () => {
    const llm: LLMProvider = {
      complete: async () => ({
        text: '{"action": "skip", "domain": "general", "content": "", "memory_layer": "fact", "reasoning": "redundant"}',
      }),
    };

    const decision = await curateLocalRetain({
      content: "redundant info",
      bankId: "test",
      tree,
      search,
      llmProvider: llm,
    });
    expect(decision.action).toBe("skip");
  });

  it("classifies domain and layer on add", async () => {
    const llm: LLMProvider = {
      complete: async () => ({
        text: '{"action": "add", "domain": "architecture", "content": "PostgreSQL is the primary database", "memory_layer": "fact", "reasoning": "new technical info"}',
      }),
    };

    const decision = await curateLocalRetain({
      content: "We use PostgreSQL",
      bankId: "test",
      tree,
      search,
      llmProvider: llm,
    });
    expect(decision.action).toBe("add");
    expect(decision.domain).toBe("architecture");
    expect(decision.memory_layer).toBe("fact");
  });

  it("falls back to add/general on LLM failure", async () => {
    const llm: LLMProvider = {
      complete: async () => {
        throw new Error("LLM unavailable");
      },
    };

    const decision = await curateLocalRetain({
      content: "should still store",
      bankId: "test",
      tree,
      search,
      llmProvider: llm,
    });
    expect(decision.action).toBe("add");
    expect(decision.domain).toBe("general");
    expect(decision.reasoning).toContain("failed");
  });
});
