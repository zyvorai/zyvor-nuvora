// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
export const pages = [
  'overview',
  'playground',
  'models',
  'routers',
  'knowledge',
  'connectors',
  'agents',
  'actions',
  'mcp_servers',
  'workflows',
  'prompts',
  'recipes',
  'jobs',
  'evaluations',
  'batches',
  'approvals',
  'policies',
  'usage',
  'audit',
  'users',
  'keys',
  'settings',
] as const;

export type Page = (typeof pages)[number];

export type NavLink = { page: Page; label: string; blurb: string };
export type NavGroup = { label: string; page?: Page; children?: NavLink[] };

export function isPage(value: string): value is Page {
  return (pages as readonly string[]).includes(value);
}

export function readPage(hash: string): Page {
  const value = hash.replace(/^#/, '').split('/')[0];
  return isPage(value) ? value : 'overview';
}

// "#agents/abc123" deep-links a resource drawer on its page.
export function readFocus(hash: string): string | undefined {
  const [, id] = hash.replace(/^#/, '').split('/');
  return id ? decodeURIComponent(id) : undefined;
}

// Menu blurbs are shorter than each page's hero lede in App.tsx; navGroups.test.ts
// guards that every routable page is reachable from the menu.
export const navGroups: NavGroup[] = [
  { label: 'Overview', page: 'overview' },
  {
    label: 'Workspace',
    children: [
      { page: 'playground', label: 'Playground', blurb: 'Ask a model, optionally grounded in a knowledge base, with cited evidence.' },
      { page: 'models', label: 'Models', blurb: 'OpenAI-compatible, Ollama and AWS endpoints, with operator pricing.' },
      { page: 'routers', label: 'Routers', blurb: 'Try a cheaper model first and escalate when the answer falls short.' },
      { page: 'knowledge', label: 'Knowledge', blurb: 'Index documents and inspect exactly what retrieval returns.' },
      { page: 'connectors', label: 'Connectors', blurb: 'Keep knowledge in sync with a website, S3 prefix or Confluence space.' },
    ],
  },
  {
    label: 'Build',
    children: [
      { page: 'agents', label: 'Agents', blurb: 'Bounded model and tool loops with registered tool schemas.' },
      { page: 'actions', label: 'API actions', blurb: 'Typed enterprise APIs; external writes wait for human approval.' },
      { page: 'mcp_servers', label: 'MCP servers', blurb: 'Remote tool servers for agents; writing tools wait for approval.' },
      { page: 'workflows', label: 'Workflows', blurb: 'Pinned DAGs with retrieval, generation and review steps.' },
      { page: 'prompts', label: 'Prompts', blurb: 'Versioned templates with variable validation.' },
      { page: 'recipes', label: 'Model studio', blurb: 'Export LoRA, distillation and quantization recipes for an external trainer.' },
    ],
  },
  {
    label: 'Operate',
    children: [
      { page: 'jobs', label: 'Runs', blurb: 'Every agent, workflow, evaluation and batch run, with its evidence.' },
      { page: 'evaluations', label: 'Evaluations', blurb: 'Contains/excludes suites and release verdicts.' },
      { page: 'batches', label: 'Batch inference', blurb: 'Queue up to 100 prompts as one durable run.' },
    ],
  },
  {
    label: 'Govern',
    children: [
      { page: 'approvals', label: 'Approvals', blurb: 'Exact-action decisions by a different person.' },
      { page: 'policies', label: 'Guardrails', blurb: 'Word, regex, PII, grounding and classifier checks on inputs and outputs.' },
      { page: 'usage', label: 'Usage & cost', blurb: 'Tokens, latency and estimated spend per model.' },
      { page: 'audit', label: 'Evidence', blurb: 'The hash-chained audit trail, verifiable and exportable.' },
      { page: 'users', label: 'Access', blurb: 'Workspace members and their roles.' },
      { page: 'keys', label: 'API keys', blurb: 'Scoped service tokens for scripts and the OpenAI-compatible API.' },
      { page: 'settings', label: 'Settings', blurb: 'Workspace, provider allow-list, budgets and appearance.' },
    ],
  },
];

export function pageLabel(page: Page): string {
  for (const g of navGroups) {
    if (g.page === page) return g.label;
    const c = g.children?.find((x) => x.page === page);
    if (c) return c.label;
  }
  return page;
}

export function pageGroup(page: Page): string {
  return navGroups.find((g) => g.page === page || g.children?.some((c) => c.page === page))?.label ?? '';
}
