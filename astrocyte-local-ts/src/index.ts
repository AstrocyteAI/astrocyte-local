/**
 * @astrocyteai/local — Zero-infrastructure memory for AI coding agents.
 *
 * Context Tree + SQLite FTS5 search. No database, no embeddings, no API keys.
 */

export { ContextTree } from "./context-tree.js";
export { SearchEngine } from "./search.js";
export { createMcpServer, startMcpServer } from "./mcp-server.js";
export type { McpServerOptions } from "./mcp-server.js";
export { curateLocalRetain, parseResponse } from "./curated-retain.js";
export type { LLMProvider, CurationDecision } from "./curated-retain.js";
export { LocalRecallCache, LocalTieredRetriever } from "./tiered-retrieval.js";
export type {
  MemoryEntry,
  SearchHit,
  RetainResult,
  RecallResult,
  BrowseResult,
  LocalConfig,
} from "./types.js";
