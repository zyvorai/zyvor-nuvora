// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import type { Row } from '../api';

// Writable fields per collection; mirrors Platform.validate so duplicates pass validation.
export const FIELDS: Record<string, string[]> = {
  models: ['provider', 'upstream_model', 'base_url', 'key_env', 'region', 'capability', 'input_price', 'output_price', 'cached_input_price', 'enabled', 'vision'],
  routers: ['models', 'strategy', 'judge_model', 'min_score'],
  knowledge: ['embedding_model', 'rerank_model', 'ocr_model', 'transcription_model'],
  agents: ['model', 'knowledge_ids', 'tools', 'max_steps', 'system_prompt', 'summarize_memory'],
  mcp_servers: ['url', 'key_env', 'readonly', 'tools'],
  prompts: ['template', 'variants'],
  policies: ['max_chars', 'daily_tokens', 'blocked_topics', 'redact_pii', 'detect_injection', 'word_filters', 'regex_filters', 'pii_entities', 'grounding_threshold', 'classifier_model', 'classifier_categories', 'classifier_threshold', 'cache_ttl'],
  workflows: ['steps'],
  evaluations: ['model', 'cases', 'pass_threshold', 'judge_model', 'knowledge_ids'],
  recipes: ['model', 'method', 'dataset', 'rank', 'epochs'],
  actions: ['url', 'method', 'key_env', 'description', 'input_schema'],
};

export const DRAWER_KINDS = [...Object.keys(FIELDS), 'approvals'];
export const ADMIN_KINDS = ['models', 'policies', 'actions', 'mcp_servers'];
export const RUNNABLE: Record<string, { field: string; label: string; button: string; placeholder: string } | null> = {
  agents: { field: 'message', label: 'Task', button: 'Run agent', placeholder: 'Explain Keep' },
  workflows: { field: 'text', label: 'Workflow input', button: 'Start workflow', placeholder: 'Explain Keep isolation' },
  evaluations: null,
};

export function duplicateBody(kind: string, row: Row): Row {
  const body: Row = { name: `${row.name} copy`.slice(0, 120) };
  for (const k of FIELDS[kind] || []) if (row[k] !== undefined) body[k] = row[k];
  return body;
}

export function singular(kind: string): string {
  const names: Record<string, string> = {
    knowledge: 'Knowledge base',
    policies: 'Guardrail policy',
    actions: 'Connector',
    models: 'Model',
    agents: 'Agent',
    prompts: 'Prompt',
    workflows: 'Workflow',
    evaluations: 'Evaluation',
    recipes: 'Recipe',
    routers: 'Router',
    mcp_servers: 'MCP server',
    approvals: 'Approval',
    jobs: 'Run',
  };
  return names[kind] || kind;
}
