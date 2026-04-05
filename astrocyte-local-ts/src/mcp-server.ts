/**
 * MCP server — exposes Context Tree as MCP tools.
 *
 * See docs/mcp-tools.md for tool schemas.
 *
 * Usage:
 *   npx @astrocyteai/local --root .astrocyte
 *   astrocyte-local-mcp --root .astrocyte
 */

// TODO: Implement in Phase 1
// - memory_retain
// - memory_recall
// - memory_browse (unique to local)
// - memory_forget
// - memory_banks
// - memory_health
// - Optional: memory_reflect (requires LLM config)

export async function startMcpServer(root: string): Promise<void> {
  // Placeholder
  console.log(`Astrocyte Local MCP server starting with root: ${root}`);
}
