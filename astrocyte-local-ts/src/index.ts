/**
 * @astrocyteai/local — Zero-infrastructure memory for AI coding agents.
 *
 * Context Tree + SQLite FTS5 search. No database, no embeddings, no API keys.
 */

export { ContextTree } from "./context-tree.js";
export { SearchEngine } from "./search.js";
export { startMcpServer } from "./mcp-server.js";
export type { MemoryEntry, SearchHit, RetainResult } from "./types.js";
