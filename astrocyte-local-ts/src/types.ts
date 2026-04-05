/**
 * Shared types for astrocyte-local.
 * Matches the Context Tree format spec in docs/context-tree-format.md.
 */

export interface MemoryEntry {
  id: string;
  bank_id: string;
  text: string;
  domain: string;
  file_path: string;
  memory_layer: "fact" | "observation" | "model";
  fact_type: "world" | "experience" | "observation";
  tags: string[];
  created_at: string; // ISO 8601
  updated_at: string;
  occurred_at?: string;
  recall_count: number;
  last_recalled_at?: string;
  source?: string;
  metadata: Record<string, string | number | boolean | null>;
}

export interface SearchHit {
  id: string;
  text: string;
  score: number; // 0.0 - 1.0 normalized
  bank_id: string;
  domain: string;
  file_path: string;
  memory_layer?: string;
  fact_type?: string;
  tags: string[];
  occurred_at?: string;
  metadata?: Record<string, string | number | boolean | null>;
}

export interface RetainResult {
  stored: boolean;
  memory_id: string;
  domain: string;
  file: string;
  error?: string;
}

export interface RecallResult {
  hits: SearchHit[];
  total: number;
}

export interface BrowseResult {
  path: string;
  domains: string[];
  entries: Array<{
    file: string;
    title: string;
    memory_id: string;
    recall_count: number;
  }>;
  total_memories: number;
}

export interface LocalConfig {
  default_bank_id: string;
  expose_reflect: boolean;
  expose_forget: boolean;
  root: string;
}
