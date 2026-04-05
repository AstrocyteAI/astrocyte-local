#!/usr/bin/env node

/**
 * CLI for Astrocyte Local — retain, search, browse, forget, export.
 *
 * See docs/cli-reference.md for the full command specification.
 *
 * Usage:
 *   astrocyte-local retain "Calvin prefers dark mode" --tags preference
 *   astrocyte-local search "dark mode"
 *   astrocyte-local browse
 *   astrocyte-local forget a1b2c3d4e5f6
 *   astrocyte-local export --output backup.ama.jsonl
 *   astrocyte-local health
 *   astrocyte-local mcp
 */

import { Command } from "commander";
import path from "node:path";
import fs from "node:fs";
import { ContextTree } from "./context-tree.js";
import { SearchEngine } from "./search.js";
import { startMcpServer } from "./mcp-server.js";

const program = new Command();

program
  .name("astrocyte-local")
  .description("Local memory for AI coding agents")
  .version("0.1.0")
  .option("-r, --root <path>", "Context Tree root directory", ".astrocyte")
  .option("-b, --bank <id>", "Memory bank ID", "project")
  .option("-f, --format <fmt>", "Output format (text|json)", "text");

// ── retain ──

program
  .command("retain")
  .description("Store content into memory")
  .argument("[content]", "Content to retain")
  .option("--tags <tags>", "Comma-separated tags")
  .option("--domain <domain>", "Context Tree domain")
  .option("--stdin", "Read from stdin")
  .action(async (content: string | undefined, opts: Record<string, string | boolean>) => {
    const globals = program.opts();
    const tree = new ContextTree(globals.root);
    const search = new SearchEngine(path.join(globals.root, "_search.db"));

    let text = content;
    if (opts.stdin || !text) {
      const chunks: Buffer[] = [];
      for await (const chunk of process.stdin) {
        chunks.push(chunk);
      }
      text = Buffer.concat(chunks).toString("utf-8").trim();
    }
    if (!text) {
      console.error("Error: no content provided");
      process.exit(2);
    }

    const tags = opts.tags ? (opts.tags as string).split(",").map((t: string) => t.trim()) : [];
    const domain = (opts.domain as string) || (tags[0] || "general");

    const entry = tree.store({
      content: text,
      bank_id: globals.bank,
      domain,
      tags,
    });
    search.addDocument(entry);
    search.close();

    if (globals.format === "json") {
      console.log(
        JSON.stringify({
          stored: true,
          memory_id: entry.id,
          domain: entry.domain,
          file: entry.file_path,
        })
      );
    } else {
      console.log(`Stored: ${entry.id} → ${entry.file_path}`);
    }
  });

// ── search ──

program
  .command("search")
  .description("Search memory")
  .argument("<query>", "Search query")
  .option("--tags <tags>", "Filter by tags (comma-separated)")
  .option("--max-results <n>", "Maximum results", "10")
  .action((query: string, opts: Record<string, string>) => {
    const globals = program.opts();
    const tree = new ContextTree(globals.root);
    const search = new SearchEngine(path.join(globals.root, "_search.db"));

    search.buildIndex(tree, globals.bank);

    const tags = opts.tags ? opts.tags.split(",").map((t: string) => t.trim()) : undefined;
    const hits = search.search(query, globals.bank, {
      limit: parseInt(opts.maxResults || "10", 10),
      tags,
    });
    search.close();

    if (globals.format === "json") {
      const hitDicts = hits.map((h) => ({
        score: Math.round(h.score * 10000) / 10000,
        text: h.text,
        domain: h.domain,
        file: h.file_path,
        memory_id: h.id,
      }));
      console.log(JSON.stringify({ hits: hitDicts }));
    } else {
      if (hits.length === 0) {
        console.log("No results found.");
      }
      for (const h of hits) {
        console.log(`[${h.score.toFixed(2)}] ${h.file_path}`);
        console.log(`  ${h.text.slice(0, 100)}`);
        console.log();
      }
    }
  });

// ── browse ──

program
  .command("browse")
  .description("Browse the Context Tree")
  .argument("[path]", "Path to browse", "")
  .action((browsePath: string) => {
    const globals = program.opts();
    const tree = new ContextTree(globals.root);

    if (!browsePath) {
      const domains = tree.listDomains(globals.bank);
      const total = tree.count(globals.bank);
      if (globals.format === "json") {
        console.log(JSON.stringify({ path: "", domains, total_memories: total }));
      } else {
        console.log(`${globals.root}/memory/`);
        for (const d of domains) {
          const count = tree.listEntries(globals.bank, d).length;
          console.log(`  ${d}/     (${count} entries)`);
        }
        console.log(`\nTotal: ${total} memories`);
      }
    } else {
      const entries = tree.listEntries(globals.bank, browsePath);
      if (globals.format === "json") {
        const entryDicts = entries.map((e) => ({
          file: e.file_path,
          title: e.text.slice(0, 80),
          memory_id: e.id,
        }));
        console.log(JSON.stringify({ path: browsePath, entries: entryDicts }));
      } else {
        for (const e of entries) {
          console.log(`  ${e.file_path}  [${e.id}]`);
          console.log(`    ${e.text.slice(0, 80)}`);
        }
      }
    }
  });

// ── forget ──

program
  .command("forget")
  .description("Remove memories")
  .argument("[ids...]", "Memory IDs to delete")
  .option("--all", "Delete all in bank")
  .action((ids: string[], opts: Record<string, boolean>) => {
    const globals = program.opts();
    const tree = new ContextTree(globals.root);
    const search = new SearchEngine(path.join(globals.root, "_search.db"));
    let deleted = 0;

    if (opts.all) {
      const entries = tree.listEntries(globals.bank);
      for (const e of entries) {
        if (tree.delete(e.id)) {
          search.removeDocument(e.id);
          deleted++;
        }
      }
    } else {
      for (const mid of ids) {
        if (tree.delete(mid)) {
          search.removeDocument(mid);
          deleted++;
        }
      }
    }
    search.close();

    if (globals.format === "json") {
      console.log(JSON.stringify({ deleted_count: deleted }));
    } else {
      console.log(`Deleted ${deleted} memories`);
    }
  });

// ── export ──

program
  .command("export")
  .description("Export to AMA format")
  .option("-o, --output <file>", "Output file path")
  .action((opts: Record<string, string>) => {
    const globals = program.opts();
    const tree = new ContextTree(globals.root);
    const entries = tree.scanAll(globals.bank);

    const header = {
      _ama_version: 1,
      bank_id: globals.bank,
      memory_count: entries.length,
    };

    const lines: string[] = [JSON.stringify(header)];
    for (const e of entries) {
      const record: Record<string, unknown> = {
        id: e.id,
        text: e.text,
        fact_type: e.fact_type,
        tags: e.tags,
        created_at: e.created_at,
      };
      if (e.occurred_at) record.occurred_at = e.occurred_at;
      if (e.source) record.source = e.source;
      lines.push(JSON.stringify(record));
    }

    const output = lines.join("\n") + "\n";
    if (opts.output) {
      fs.writeFileSync(opts.output, output, "utf-8");
      console.log(`Exported ${entries.length} memories to ${opts.output}`);
    } else {
      process.stdout.write(output);
    }
  });

// ── health ──

program
  .command("health")
  .description("System health check")
  .action(() => {
    const globals = program.opts();
    const tree = new ContextTree(globals.root);
    const total = tree.count();
    const domains = tree.listDomains();

    if (globals.format === "json") {
      console.log(
        JSON.stringify({ healthy: true, total_memories: total, root: globals.root })
      );
    } else {
      console.log("Status: healthy");
      console.log(`Root: ${globals.root}`);
      console.log(`Memories: ${total}`);
      console.log(`Domains: ${domains.length > 0 ? domains.join(", ") : "(none)"}`);
    }
  });

// ── rebuild-index ──

program
  .command("rebuild-index")
  .description("Rebuild the search index")
  .action(() => {
    const globals = program.opts();
    const tree = new ContextTree(globals.root);
    const search = new SearchEngine(path.join(globals.root, "_search.db"));
    const count = search.buildIndex(tree);
    search.close();
    console.log(`Rebuilt index: ${count} entries`);
  });

// ── mcp ──

program
  .command("mcp")
  .description("Start MCP server")
  .option("--transport <type>", "Transport type (stdio|sse)", "stdio")
  .option("--port <n>", "SSE port", "8090")
  .action(async (opts: Record<string, string>) => {
    const globals = program.opts();
    await startMcpServer({
      root: globals.root,
      defaultBank: globals.bank,
      transport: opts.transport as "stdio" | "sse",
      port: parseInt(opts.port, 10),
    });
  });

program.parse();
