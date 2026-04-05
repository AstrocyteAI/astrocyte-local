/**
 * MCP server — exposes Context Tree as MCP tools.
 *
 * See docs/mcp-tools.md for tool schemas.
 *
 * Usage:
 *   npx @astrocyteai/local --root .astrocyte
 *   astrocyte-local-mcp --root .astrocyte
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { ContextTree } from "./context-tree.js";
import { SearchEngine } from "./search.js";

export interface McpServerOptions {
  root: string;
  defaultBank?: string;
  transport?: "stdio" | "sse";
  port?: number;
}

export function createMcpServer(options: McpServerOptions): McpServer {
  const { root, defaultBank = "project" } = options;

  const tree = new ContextTree(root);
  const search = new SearchEngine(`${root}/_search.db`);
  search.buildIndex(tree);

  const server = new McpServer(
    {
      name: "astrocyte-local",
      version: "0.1.0",
    },
    {
      instructions:
        "Local memory server. Use memory_retain to store information, " +
        "memory_recall to search memories, memory_browse to explore the " +
        "Context Tree hierarchy, and memory_forget to remove memories.",
    }
  );

  // ── memory_retain ──

  server.tool(
    "memory_retain",
    "Store content into local memory.",
    {
      content: z.string().describe("The text to memorize."),
      bank_id: z.string().optional().describe("Memory bank (default: project)."),
      tags: z.array(z.string()).optional().describe("Optional tags for filtering."),
      domain: z.string().optional().describe("Context Tree domain (auto-inferred if omitted)."),
    },
    async (args) => {
      const bankId = args.bank_id || defaultBank;
      const domain = args.domain || (args.tags?.[0] ?? "general");

      const entry = tree.store({
        content: args.content,
        bank_id: bankId,
        domain,
        tags: args.tags || [],
      });
      search.addDocument(entry);

      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({
              stored: true,
              memory_id: entry.id,
              domain: entry.domain,
              file: entry.file_path,
            }),
          },
        ],
      };
    }
  );

  // ── memory_recall ──

  server.tool(
    "memory_recall",
    "Search local memory for content relevant to a query.",
    {
      query: z.string().describe("Natural language search query."),
      bank_id: z.string().optional().describe("Memory bank (default: project)."),
      max_results: z.number().optional().describe("Maximum results (default: 10)."),
      tags: z.array(z.string()).optional().describe("Filter by tags."),
    },
    async (args) => {
      const bankId = args.bank_id || defaultBank;
      const hits = search.search(args.query, bankId, {
        limit: args.max_results || 10,
        tags: args.tags,
      });

      // Record recall
      for (const h of hits) {
        tree.recordRecall(h.id);
      }

      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({
              hits: hits.map((h) => ({
                text: h.text,
                score: Math.round(h.score * 10000) / 10000,
                domain: h.domain,
                file: h.file_path,
                memory_id: h.id,
              })),
              total: hits.length,
            }),
          },
        ],
      };
    }
  );

  // ── memory_browse ──

  server.tool(
    "memory_browse",
    "Browse the Context Tree hierarchy.",
    {
      path: z.string().optional().describe("Path to browse (empty for root, 'preferences' for a domain)."),
      bank_id: z.string().optional().describe("Memory bank (default: project)."),
    },
    async (args) => {
      const bankId = args.bank_id || defaultBank;
      const browsePath = args.path || "";

      if (!browsePath) {
        const domains = tree.listDomains(bankId);
        const total = tree.count(bankId);
        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify({
                path: "",
                domains,
                entries: [],
                total_memories: total,
              }),
            },
          ],
        };
      }

      const entries = tree.listEntries(bankId, browsePath);
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({
              path: browsePath,
              domains: [],
              entries: entries.map((e) => ({
                file: e.file_path,
                title: e.text.slice(0, 80),
                memory_id: e.id,
                recall_count: e.recall_count,
              })),
              total_memories: entries.length,
            }),
          },
        ],
      };
    }
  );

  // ── memory_forget ──

  server.tool(
    "memory_forget",
    "Remove memories from local storage.",
    {
      memory_ids: z.array(z.string()).describe("IDs of memories to delete."),
      bank_id: z.string().optional().describe("Memory bank (default: project)."),
    },
    async (args) => {
      let deleted = 0;
      const filesRemoved: string[] = [];

      for (const mid of args.memory_ids) {
        const entry = tree.read(mid);
        if (entry) {
          filesRemoved.push(entry.file_path);
        }
        if (tree.delete(mid)) {
          search.removeDocument(mid);
          deleted++;
        }
      }

      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({
              deleted_count: deleted,
              files_removed: filesRemoved,
            }),
          },
        ],
      };
    }
  );

  // ── memory_banks ──

  server.tool(
    "memory_banks",
    "List available memory banks.",
    {},
    async () => {
      const allEntries = tree.scanAll();
      const bankIds = [...new Set(allEntries.map((e) => e.bank_id))].sort();
      if (!bankIds.includes(defaultBank)) {
        bankIds.unshift(defaultBank);
      }

      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({
              banks: bankIds,
              default: defaultBank,
              root,
            }),
          },
        ],
      };
    }
  );

  // ── memory_health ──

  server.tool(
    "memory_health",
    "Check local memory system health.",
    {},
    async () => {
      const total = tree.count();
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({
              healthy: true,
              total_memories: total,
              index_status: "current",
              root,
            }),
          },
        ],
      };
    }
  );

  return server;
}

export async function startMcpServer(options: McpServerOptions): Promise<void> {
  const server = createMcpServer(options);

  if (options.transport === "sse") {
    // SSE transport would require express — for now only stdio
    throw new Error("SSE transport not yet implemented in TypeScript. Use stdio.");
  }

  const transport = new StdioServerTransport();
  await server.connect(transport);
}
