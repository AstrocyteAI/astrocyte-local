/**
 * Context Tree — hierarchical markdown file storage.
 *
 * Stores memories as .md files with YAML frontmatter in a
 * domain-based directory structure. See docs/context-tree-format.md.
 */

import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import YAML from "yaml";
import type { MemoryEntry } from "./types.js";

export class ContextTree {
  private memoryDir: string;

  constructor(private root: string) {
    this.memoryDir = path.join(root, "memory");
    fs.mkdirSync(this.memoryDir, { recursive: true });
  }

  store(options: {
    content: string;
    bank_id: string;
    domain?: string;
    tags?: string[];
    memory_layer?: "fact" | "observation" | "model";
    fact_type?: "world" | "experience" | "observation";
    occurred_at?: string;
    source?: string;
    metadata?: Record<string, string | number | boolean | null>;
  }): MemoryEntry {
    const id = randomUUID().replace(/-/g, "").slice(0, 12);
    const now = new Date().toISOString();
    const domain = options.domain || "general";
    const domainDir = path.join(this.memoryDir, domain);
    fs.mkdirSync(domainDir, { recursive: true });

    const filename = this.makeFilename(options.content);
    let filePath = path.join(domainDir, `${filename}.md`);
    let counter = 2;
    while (fs.existsSync(filePath)) {
      filePath = path.join(domainDir, `${filename}-${counter}.md`);
      counter++;
    }

    const relPath = path.relative(this.memoryDir, filePath);

    const entry: MemoryEntry = {
      id,
      bank_id: options.bank_id,
      text: options.content,
      domain,
      file_path: relPath,
      memory_layer: options.memory_layer || "fact",
      fact_type: options.fact_type || "world",
      tags: options.tags || [],
      created_at: now,
      updated_at: now,
      occurred_at: options.occurred_at,
      recall_count: 0,
      source: options.source,
      metadata: options.metadata || {},
    };

    this.writeEntry(filePath, entry);
    return entry;
  }

  read(entryId: string): MemoryEntry | null {
    for (const entry of this.scanAll()) {
      if (entry.id === entryId) return entry;
    }
    return null;
  }

  update(entryId: string, content: string): MemoryEntry | null {
    for (const mdFile of this.allMdFiles()) {
      const entry = this.readFile(mdFile);
      if (entry && entry.id === entryId) {
        entry.text = content;
        entry.updated_at = new Date().toISOString();
        this.writeEntry(mdFile, entry);
        return entry;
      }
    }
    return null;
  }

  delete(entryId: string): boolean {
    for (const mdFile of this.allMdFiles()) {
      const entry = this.readFile(mdFile);
      if (entry && entry.id === entryId) {
        fs.unlinkSync(mdFile);
        // Remove empty domain directories
        const parent = path.dirname(mdFile);
        if (parent !== this.memoryDir) {
          try {
            const remaining = fs.readdirSync(parent);
            if (remaining.length === 0) fs.rmdirSync(parent);
          } catch {}
        }
        return true;
      }
    }
    return false;
  }

  recordRecall(entryId: string): void {
    for (const mdFile of this.allMdFiles()) {
      const entry = this.readFile(mdFile);
      if (entry && entry.id === entryId) {
        entry.recall_count++;
        entry.last_recalled_at = new Date().toISOString();
        this.writeEntry(mdFile, entry);
        return;
      }
    }
  }

  listDomains(bankId?: string): string[] {
    if (!fs.existsSync(this.memoryDir)) return [];
    const domains: string[] = [];
    for (const d of fs.readdirSync(this.memoryDir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      if (!d.isDirectory() || d.name.startsWith("_")) continue;
      if (!bankId) {
        domains.push(d.name);
      } else {
        const domainPath = path.join(this.memoryDir, d.name);
        const files = fs.readdirSync(domainPath).filter((f) => f.endsWith(".md"));
        for (const f of files) {
          const entry = this.readFile(path.join(domainPath, f));
          if (entry && entry.bank_id === bankId) {
            domains.push(d.name);
            break;
          }
        }
      }
    }
    return domains;
  }

  listEntries(bankId: string, domain?: string): MemoryEntry[] {
    const searchDir = domain ? path.join(this.memoryDir, domain) : this.memoryDir;
    if (!fs.existsSync(searchDir)) return [];
    const entries: MemoryEntry[] = [];
    for (const mdFile of this.allMdFiles(searchDir)) {
      const entry = this.readFile(mdFile);
      if (entry && entry.bank_id === bankId) entries.push(entry);
    }
    return entries;
  }

  scanAll(bankId?: string): MemoryEntry[] {
    if (!fs.existsSync(this.memoryDir)) return [];
    const entries: MemoryEntry[] = [];
    for (const mdFile of this.allMdFiles()) {
      const entry = this.readFile(mdFile);
      if (entry && (!bankId || entry.bank_id === bankId)) entries.push(entry);
    }
    return entries;
  }

  count(bankId?: string): number {
    return this.scanAll(bankId).length;
  }

  // ── Internal ──

  private makeFilename(content: string): string {
    let slug = content.slice(0, 50).toLowerCase().trim();
    slug = slug.replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    return slug || "memory";
  }

  private writeEntry(filePath: string, entry: MemoryEntry): void {
    const frontmatter: Record<string, unknown> = {
      id: entry.id,
      bank_id: entry.bank_id,
      memory_layer: entry.memory_layer,
      fact_type: entry.fact_type,
      tags: entry.tags,
      created_at: entry.created_at,
      updated_at: entry.updated_at,
      recall_count: entry.recall_count,
    };
    if (entry.occurred_at) frontmatter.occurred_at = entry.occurred_at;
    if (entry.last_recalled_at) frontmatter.last_recalled_at = entry.last_recalled_at;
    if (entry.source) frontmatter.source = entry.source;
    if (Object.keys(entry.metadata).length > 0) frontmatter.metadata = entry.metadata;

    const fmStr = YAML.stringify(frontmatter);
    fs.writeFileSync(filePath, `---\n${fmStr}---\n\n${entry.text}\n`, "utf-8");
  }

  private readFile(filePath: string): MemoryEntry | null {
    try {
      const content = fs.readFileSync(filePath, "utf-8");
      if (!content.startsWith("---")) return null;

      const parts = content.split("---");
      if (parts.length < 3) return null;

      const fm = YAML.parse(parts[1]) || {};
      const text = parts.slice(2).join("---").trim();
      const relPath = path.relative(this.memoryDir, filePath);
      const domain = path.dirname(filePath) === this.memoryDir ? "general" : path.basename(path.dirname(filePath));

      return {
        id: fm.id || "",
        bank_id: fm.bank_id || "",
        text,
        domain,
        file_path: relPath,
        memory_layer: fm.memory_layer || "fact",
        fact_type: fm.fact_type || "world",
        tags: fm.tags || [],
        created_at: fm.created_at || "",
        updated_at: fm.updated_at || "",
        occurred_at: fm.occurred_at,
        recall_count: fm.recall_count || 0,
        last_recalled_at: fm.last_recalled_at,
        source: fm.source,
        metadata: fm.metadata || {},
      };
    } catch {
      return null;
    }
  }

  private *allMdFiles(dir?: string): Generator<string> {
    const searchDir = dir || this.memoryDir;
    if (!fs.existsSync(searchDir)) return;
    for (const entry of fs.readdirSync(searchDir, { withFileTypes: true })) {
      const fullPath = path.join(searchDir, entry.name);
      if (entry.isDirectory() && !entry.name.startsWith("_")) {
        yield* this.allMdFiles(fullPath);
      } else if (entry.isFile() && entry.name.endsWith(".md")) {
        yield fullPath;
      }
    }
  }
}
