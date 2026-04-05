/**
 * LLM-curated retain for local Context Tree.
 *
 * When an LLM provider is available, the LLM decides:
 * - What action to take: ADD, UPDATE, MERGE, SKIP, DELETE
 * - Which domain to store in (instead of just using the first tag)
 * - What memory_layer to assign (fact, observation, model)
 *
 * Falls back to simple mechanical retain when no LLM is configured.
 */

import type { ContextTree } from "./context-tree.js";
import type { SearchEngine } from "./search.js";

export interface LLMProvider {
  complete(options: {
    messages: Array<{ role: string; content: string }>;
    maxTokens?: number;
    temperature?: number;
  }): Promise<{ text: string }>;
}

export interface CurationDecision {
  action: "add" | "update" | "merge" | "skip" | "delete";
  domain: string;
  content: string;
  memory_layer: "fact" | "observation" | "model";
  reasoning: string;
  target_id?: string;
}

const CURATION_PROMPT = `You are a memory curation agent for a local Context Tree. Analyze the new content and decide how to store it.

## Existing memories (most similar):
{existing}

## Context Tree domains currently in use:
{domains}

## New content:
{content}

## Decide:
1. action: "add" (new info), "update" (replace existing), "merge" (combine with existing), "skip" (redundant), "delete" (contradicts old)
2. domain: Which Context Tree directory to store in (e.g., "preferences", "architecture", "decisions"). Use an existing domain if appropriate, or suggest a new one.
3. memory_layer: "fact" (raw info), "observation" (pattern/insight), "model" (consolidated understanding)
4. content: The processed text to store (may rewrite for clarity)
5. reasoning: Brief explanation

Respond with JSON:
{"action": "add", "domain": "preferences", "content": "...", "memory_layer": "fact", "reasoning": "...", "target_id": null}`;

export async function curateLocalRetain(options: {
  content: string;
  bankId: string;
  tree: ContextTree;
  search: SearchEngine;
  llmProvider: LLMProvider;
  contextLimit?: number;
}): Promise<CurationDecision> {
  const { content, bankId, tree, search, llmProvider, contextLimit = 5 } = options;

  // Get existing similar memories for context
  const existingHits = search.search(content, bankId, { limit: contextLimit });
  let existingText: string;
  if (existingHits.length > 0) {
    existingText = existingHits
      .map(
        (h) =>
          `- [${h.id}] (${h.domain}/${h.file_path}) score=${h.score.toFixed(2)}: ${h.text.slice(0, 200)}`
      )
      .join("\n");
  } else {
    existingText = "(no existing memories)";
  }

  // Get current domains
  const domains = tree.listDomains(bankId);
  const domainsText = domains.length > 0 ? domains.join(", ") : "(none yet)";

  const prompt = CURATION_PROMPT.replace("{existing}", existingText)
    .replace("{domains}", domainsText)
    .replace("{content}", content);

  try {
    const completion = await llmProvider.complete({
      messages: [{ role: "user", content: prompt }],
      maxTokens: 500,
      temperature: 0,
    });
    return parseResponse(completion.text, content);
  } catch {
    return {
      action: "add",
      domain: "general",
      content,
      memory_layer: "fact",
      reasoning: "LLM curation failed, defaulting to ADD",
    };
  }
}

export function parseResponse(
  response: string,
  originalContent: string
): CurationDecision {
  try {
    let text = response.trim();

    // Extract from code block if present
    if (text.includes("```")) {
      const start = text.indexOf("```") + 3;
      let contentStart = start;
      if (text.slice(start).startsWith("json")) {
        contentStart = start + 4;
      }
      const end = text.indexOf("```", contentStart);
      if (end > contentStart) {
        text = text.slice(contentStart, end).trim();
      }
    }

    const data = JSON.parse(text);
    if (typeof data !== "object" || data === null) {
      throw new Error("Expected JSON object");
    }

    let action = (data.action || "add").toLowerCase();
    if (!["add", "update", "merge", "skip", "delete"].includes(action)) {
      action = "add";
    }

    let memoryLayer = (data.memory_layer || "fact").toLowerCase();
    if (!["fact", "observation", "model"].includes(memoryLayer)) {
      memoryLayer = "fact";
    }

    // Sanitize domain name
    let domain = (data.domain || "general").toLowerCase().trim();
    domain = domain.replace(/ /g, "-").replace(/\//g, "-");
    if (!domain) domain = "general";

    return {
      action: action as CurationDecision["action"],
      domain,
      content: data.content || originalContent,
      memory_layer: memoryLayer as CurationDecision["memory_layer"],
      reasoning: data.reasoning || "",
      target_id: data.target_id || undefined,
    };
  } catch {
    return {
      action: "add",
      domain: "general",
      content: originalContent,
      memory_layer: "fact",
      reasoning: "Failed to parse LLM response",
    };
  }
}
