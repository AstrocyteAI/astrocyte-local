import { describe, it, expect, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { createMcpServer } from "../src/mcp-server.js";

let tmpDir: string;
let client: Client;

beforeEach(async () => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "astrocyte-mcp-test-"));
  const mcpServer = createMcpServer({ root: tmpDir, defaultBank: "test" });

  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  client = new Client({ name: "test-client", version: "1.0.0" });

  await mcpServer.connect(serverTransport);
  await client.connect(clientTransport);
});

afterEach(async () => {
  await client.close();
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

describe("MCP Server", () => {
  it("lists all tools", async () => {
    const result = await client.listTools();
    const names = result.tools.map((t) => t.name);

    expect(names).toContain("memory_retain");
    expect(names).toContain("memory_recall");
    expect(names).toContain("memory_browse");
    expect(names).toContain("memory_forget");
    expect(names).toContain("memory_banks");
    expect(names).toContain("memory_health");
  });

  describe("memory_retain", () => {
    it("stores content and returns result", async () => {
      const result = await client.callTool({
        name: "memory_retain",
        arguments: {
          content: "TypeScript is my preferred language",
          tags: ["preference"],
        },
      });

      const text = (result.content as Array<{ type: string; text: string }>)[0].text;
      const data = JSON.parse(text);
      expect(data.stored).toBe(true);
      expect(data.memory_id).toBeTruthy();
      expect(data.domain).toBe("preference");
    });
  });

  describe("memory_recall", () => {
    it("finds stored memories", async () => {
      // Store first
      await client.callTool({
        name: "memory_retain",
        arguments: { content: "I prefer vim keybindings" },
      });

      // Search
      const result = await client.callTool({
        name: "memory_recall",
        arguments: { query: "vim" },
      });

      const text = (result.content as Array<{ type: string; text: string }>)[0].text;
      const data = JSON.parse(text);
      expect(data.total).toBeGreaterThanOrEqual(1);
      expect(data.hits[0].text).toContain("vim");
    });
  });

  describe("memory_browse", () => {
    it("lists domains at root", async () => {
      await client.callTool({
        name: "memory_retain",
        arguments: { content: "In preferences", domain: "preferences" },
      });

      const result = await client.callTool({
        name: "memory_browse",
        arguments: {},
      });

      const text = (result.content as Array<{ type: string; text: string }>)[0].text;
      const data = JSON.parse(text);
      expect(data.domains).toContain("preferences");
      expect(data.total_memories).toBeGreaterThanOrEqual(1);
    });

    it("lists entries in a domain", async () => {
      await client.callTool({
        name: "memory_retain",
        arguments: { content: "Memory in arch", domain: "architecture" },
      });

      const result = await client.callTool({
        name: "memory_browse",
        arguments: { path: "architecture" },
      });

      const text = (result.content as Array<{ type: string; text: string }>)[0].text;
      const data = JSON.parse(text);
      expect(data.entries.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("memory_forget", () => {
    it("deletes memories by ID", async () => {
      const retainResult = await client.callTool({
        name: "memory_retain",
        arguments: { content: "Delete me soon" },
      });
      const retainData = JSON.parse(
        (retainResult.content as Array<{ type: string; text: string }>)[0].text
      );

      const result = await client.callTool({
        name: "memory_forget",
        arguments: { memory_ids: [retainData.memory_id] },
      });

      const text = (result.content as Array<{ type: string; text: string }>)[0].text;
      const data = JSON.parse(text);
      expect(data.deleted_count).toBe(1);
    });
  });

  describe("memory_banks", () => {
    it("lists available banks", async () => {
      const result = await client.callTool({
        name: "memory_banks",
        arguments: {},
      });

      const text = (result.content as Array<{ type: string; text: string }>)[0].text;
      const data = JSON.parse(text);
      expect(data.banks).toContain("test");
      expect(data.default).toBe("test");
    });
  });

  describe("memory_health", () => {
    it("reports health status", async () => {
      const result = await client.callTool({
        name: "memory_health",
        arguments: {},
      });

      const text = (result.content as Array<{ type: string; text: string }>)[0].text;
      const data = JSON.parse(text);
      expect(data.healthy).toBe(true);
      expect(data.total_memories).toBeDefined();
    });
  });
});
