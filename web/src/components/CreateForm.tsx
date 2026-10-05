// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { useEffect, useState, type FormEvent } from 'react';
import { ArrowRight, Search } from 'lucide-react';
import { api, type Row } from '../api';
import type { Collections } from '../lib/types';
import { Field } from './kit';
import { WorkflowBuilder } from './WorkflowCanvas';
import CaseEditor, { cleanCase, type EvalCase } from './CaseEditor';
import PolicyFields from './PolicyFields';
import { topoOrder, type Step } from '../lib/dag';

const KEYS: Record<string, string[]> = {
  actions: ['url', 'method', 'key_env', 'description'],
  models: ['provider', 'base_url', 'upstream_model', 'key_env', 'region', 'input_price', 'output_price', 'capability', 'enabled'],
  knowledge: ['embedding_model', 'rerank_model'],
  agents: ['model', 'system_prompt', 'knowledge_ids', 'tools', 'max_steps'],
  prompts: ['template'],
  policies: ['redact_pii', 'detect_injection', 'max_chars', 'daily_tokens', 'blocked_topics', 'word_filters', 'regex_filters', 'pii_entities', 'grounding_threshold', 'classifier_model', 'classifier_categories', 'classifier_threshold'],
  recipes: ['model', 'method', 'dataset', 'rank', 'epochs'],
  evaluations: ['model', 'pass_threshold', 'judge_model', 'knowledge_ids'],
  workflows: [],
};

export function createLabel(kind: string): string {
  if (kind === 'knowledge') return 'knowledge base';
  if (kind === 'policies') return 'policy';
  if (kind === 'actions') return 'connector';
  return kind.slice(0, -1);
}

export default function CreateForm({
  kind,
  collections,
  existing,
  save,
}: {
  kind: string;
  collections: Collections;
  existing: Row | null;
  save: (body: Row) => void;
}) {
  const chatModels = (collections.models || []).filter((m) => m.capability === 'chat');
  const firstModel = chatModels[0]?.id || '';
  const defaults: Row = {
    name: '',
    provider: 'openai',
    base_url: 'http://127.0.0.1:8000/v1',
    upstream_model: '',
    capability: 'chat',
    input_price: 0,
    output_price: 0,
    model: firstModel,
    tools: ['knowledge_search'],
    url: 'https://api.internal.example/status',
    knowledge_ids: [],
    max_steps: 5,
    template: 'Answer {{question}} using {{evidence}}.',
    redact_pii: true,
    detect_injection: true,
    max_chars: 100000,
    daily_tokens: 1000000,
    blocked_topics: [],
    method: kind === 'actions' ? 'GET' : 'lora',
    dataset: './data/train.jsonl',
    pass_threshold: 1,
    enabled: true,
  };
  const [data, setData] = useState<Row>(existing ? { ...defaults, ...existing, expected_revision: existing.revision } : defaults);
  const sampleJSON: Record<string, unknown> = {
    actions: existing?.input_schema ?? { type: 'object', properties: { query: { type: 'string' } }, required: [] },
    workflows: existing?.steps ?? [{ id: 'answer', type: 'generate', model: firstModel, depends_on: ['input'] }],
    evaluations: existing?.cases ?? [{ input: 'Explain private AI', contains: ['AI'], excludes: [], judge: { criteria: 'Explains that data stays inside the operator boundary.', min_score: 0.7 } }],
  };
  const [json, setJSON] = useState(JSON.stringify(sampleJSON[kind] ?? sampleJSON.evaluations, null, 2));
  const [error, setError] = useState('');
  const [visual, setVisual] = useState(kind === 'workflows' || kind === 'evaluations');
  const steps: Step[] | null = (() => {
    try {
      const v = JSON.parse(json);
      return Array.isArray(v) ? v : null;
    } catch {
      return null;
    }
  })();
  const set = (k: string, v: unknown) => setData({ ...data, [k]: v });
  const [tools, setTools] = useState<string[]>(['knowledge_search', 'list_models', 'memory_read', 'memory_write']);
  const [presets, setPresets] = useState<Row[]>([]);
  const [found, setFound] = useState<Row[] | null>(null);
  const [discovering, setDiscovering] = useState(false);
  useEffect(() => {
    if (kind === 'agents')
      api('/api/tools')
        .then((r) => setTools(Object.keys(r.tools)))
        .catch(() => undefined);
    if (kind === 'models' && !existing)
      api('/api/models/presets')
        .then((r) => setPresets(r.presets))
        .catch(() => undefined);
  }, [kind, existing]);

  async function discover() {
    setDiscovering(true);
    setError('');
    try {
      const r = await api('/api/models/discover', { provider: data.provider, base_url: data.base_url, key_env: data.key_env || undefined });
      setFound(r.models);
      if (r.models.length && !data.upstream_model) setData({ ...data, upstream_model: r.models[0].id, capability: r.models[0].capability });
    } catch (err) {
      setError(String(err));
      setFound(null);
    } finally {
      setDiscovering(false);
    }
  }

  function field(k: string, label: string, type = 'text') {
    return (
      <Field label={label}>
        <input
          type={type}
          step={type === 'number' ? 'any' : undefined}
          value={data[k] ?? ''}
          onChange={(e) => set(k, type === 'number' ? Number(e.target.value) : e.target.value)}
          required={!['key_env', 'region'].includes(k)}
        />
      </Field>
    );
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    setError('');
    try {
      const body: Row = { name: data.name };
      for (const k of KEYS[kind] || []) if (data[k] !== undefined) body[k] = data[k];
      if (existing) body.expected_revision = existing.revision;
      if (kind === 'actions') body.input_schema = JSON.parse(json);
      if (kind === 'workflows') {
        const parsed = JSON.parse(json);
        body.steps = (Array.isArray(parsed) && topoOrder(parsed)) || parsed;
      }
      if (kind === 'evaluations') {
        const parsed = JSON.parse(json);
        body.cases = Array.isArray(parsed) ? parsed.map((c: EvalCase) => cleanCase(c)) : parsed;
      }
      save(body);
    } catch (err) {
      setError(String(err));
    }
  }

  const modelSelect = (
    <Field label="Model">
      <select value={data.model} onChange={(e) => set('model', e.target.value)} required>
        {chatModels.map((m) => (
          <option key={m.id} value={m.id}>
            {m.name}
            {m.provider === 'demo' ? ' · demo' : ''}
          </option>
        ))}
      </select>
    </Field>
  );

  return (
    <form onSubmit={submit}>
      {field('name', 'Name')}
      {kind === 'actions' && (
        <>
          {field('url', 'API URL · host must be on the operator allowlist')}
          <Field label="HTTP method">
            <select value={data.method} onChange={(e) => set('method', e.target.value)}>
              <option>GET</option>
              <option>POST</option>
            </select>
          </Field>
          {field('key_env', 'Secret environment reference (optional)')}
          <Field label="Typed input schema (JSON)">
            <textarea className="code-input" rows={8} value={json} onChange={(e) => setJSON(e.target.value)} />
          </Field>
          <p className="note">POST calls always pause for a different human’s approval of the exact arguments. No automatic write retries.</p>
        </>
      )}
      {kind === 'models' && (
        <>
          {presets.length > 0 && (
            <Field label="Start from a preset">
              <select
                defaultValue=""
                onChange={(e) => {
                  const pr = presets.find((x) => x.id === e.target.value);
                  if (pr) setData({ ...data, provider: pr.provider, base_url: pr.base_url, key_env: pr.key_env, name: data.name || pr.label });
                  setFound(null);
                }}
              >
                <option value="">Custom</option>
                {presets.map((pr) => (
                  <option key={pr.id} value={pr.id}>
                    {pr.label}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <div className="form-grid">
            <Field label="Provider">
              <select value={data.provider === 'bedrock' ? 'aws' : data.provider} onChange={(e) => set('provider', e.target.value)}>
                {['openai', 'ollama', 'aws', 'demo'].map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            </Field>
            <Field label="Capability">
              <select value={data.capability} onChange={(e) => set('capability', e.target.value)}>
                <option>chat</option>
                <option>embedding</option>
              </select>
            </Field>
          </div>
          {data.provider !== 'demo' && data.provider !== 'aws' && data.provider !== 'bedrock' && field('base_url', 'Base URL · host must be allowed by the operator')}
          {found && found.length > 0 ? (
            <Field label="Upstream model">
              <select
                value={data.upstream_model}
                onChange={(e) => {
                  const m = found.find((x) => x.id === e.target.value);
                  setData({ ...data, upstream_model: e.target.value, capability: m?.capability || data.capability });
                }}
              >
                {found.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id} · {m.capability}
                  </option>
                ))}
              </select>
            </Field>
          ) : (
            field('upstream_model', 'Upstream model identifier')
          )}
          {(data.provider === 'openai' || data.provider === 'ollama') && (
            <button type="button" className="btn-secondary compact" onClick={discover} disabled={discovering || !data.base_url}>
              <Search size={14} />
              {discovering ? 'Discovering…' : 'Discover models from this endpoint'}
            </button>
          )}
          {found && !found.length && <p className="note">The endpoint answered but listed no models.</p>}
          {data.provider === 'aws' || data.provider === 'bedrock' ? field('region', 'AWS region') : field('key_env', 'Secret environment reference (optional)')}
          <div className="form-grid">
            {field('input_price', 'USD / million input tokens', 'number')}
            {field('output_price', 'USD / million output tokens', 'number')}
          </div>
          <label className="check">
            <input type="checkbox" checked={!!data.enabled} onChange={(e) => set('enabled', e.target.checked)} />
            Enabled for routing
          </label>
        </>
      )}
      {kind === 'knowledge' && (
        <Field label="Embedding model">
          <select value={data.embedding_model || ''} onChange={(e) => set('embedding_model', e.target.value)}>
            <option value="">Offline lexical retrieval</option>
            {(collections.models || [])
              .filter((m) => m.capability === 'embedding')
              .map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
          </select>
        </Field>
      )}
      {kind === 'knowledge' && (
        <Field label="Rerank model (optional)">
          <select value={data.rerank_model || ''} onChange={(e) => set('rerank_model', e.target.value)}>
            <option value="">No rerank · fused BM25 order</option>
            {chatModels.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </Field>
      )}
      {['agents', 'recipes', 'evaluations'].includes(kind) && modelSelect}
      {kind === 'evaluations' && (
        <div className="form-grid">
          <Field label="Judge model (defaults to the model under test)">
            <select value={data.judge_model || ''} onChange={(e) => set('judge_model', e.target.value)}>
              <option value="">Same as model under test</option>
              {chatModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Knowledge for grounded cases">
            <select multiple value={data.knowledge_ids} onChange={(e) => set('knowledge_ids', Array.from(e.target.selectedOptions).map((o) => o.value))}>
              {(collections.knowledge || []).map((k) => (
                <option key={k.id} value={k.id}>
                  {k.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
      )}
      {kind === 'agents' && (
        <>
          <Field label="System instruction">
            <textarea rows={4} value={data.system_prompt || ''} onChange={(e) => set('system_prompt', e.target.value)} />
          </Field>
          <Field label="Knowledge bases">
            <select
              multiple
              value={data.knowledge_ids}
              onChange={(e) => set('knowledge_ids', Array.from(e.target.selectedOptions).map((o) => o.value))}
            >
              {(collections.knowledge || []).map((k) => (
                <option key={k.id} value={k.id}>
                  {k.name}
                </option>
              ))}
            </select>
          </Field>
          <div className="check-list">
            {[...tools, ...(collections.actions || []).map((a) => 'action_' + a.id)].map((t) => (
              <label key={t}>
                <input
                  type="checkbox"
                  checked={data.tools.includes(t)}
                  onChange={(e) => set('tools', e.target.checked ? [...data.tools, t] : data.tools.filter((x: string) => x !== t))}
                />
                {t.replaceAll('_', ' ')}
              </label>
            ))}
          </div>
          {field('max_steps', 'Maximum model steps', 'number')}
        </>
      )}
      {kind === 'prompts' && (
        <Field label="Prompt template · {{variable}} syntax">
          <textarea rows={7} value={data.template} onChange={(e) => set('template', e.target.value)} required />
        </Field>
      )}
      {kind === 'policies' && (
        <>
          <div className="check-list">
            {['redact_pii', 'detect_injection'].map((k) => (
              <label key={k}>
                <input type="checkbox" checked={data[k]} onChange={(e) => set(k, e.target.checked)} />
                {k.replaceAll('_', ' ')}
              </label>
            ))}
          </div>
          {field('max_chars', 'Maximum characters', 'number')}
          {field('daily_tokens', 'Daily token budget', 'number')}
          <Field label="Denied topics (comma-separated)">
            <input
              value={data.blocked_topics.join(',')}
              onChange={(e) =>
                set(
                  'blocked_topics',
                  e.target.value
                    .split(',')
                    .map((s) => s.trim())
                    .filter(Boolean)
                )
              }
            />
          </Field>
          <PolicyFields data={data} set={set} chatModels={chatModels} />
        </>
      )}
      {kind === 'recipes' && (
        <>
          <Field label="Recipe method">
            <select value={data.method} onChange={(e) => set('method', e.target.value)}>
              {['lora', 'qlora', 'distillation', 'evaluation', 'quantization'].map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </Field>
          {field('dataset', 'External trainer dataset path')}
          <p className="note">Configuration export only. No GPU job is executed.</p>
        </>
      )}
      {(kind === 'workflows' || kind === 'evaluations') && (
        <div className="tabs" role="tablist" aria-label={kind === 'workflows' ? 'Workflow editor' : 'Case editor'}>
          <button type="button" role="tab" aria-selected={visual} onClick={() => steps && setVisual(true)} disabled={!steps}>
            {kind === 'workflows' ? 'Visual builder' : 'Case editor'}
          </button>
          <button type="button" role="tab" aria-selected={!visual} onClick={() => setVisual(false)}>
            JSON
          </button>
        </div>
      )}
      {kind === 'workflows' && visual && steps && <WorkflowBuilder steps={steps} collections={collections} onChange={(next) => setJSON(JSON.stringify(next, null, 2))} />}
      {kind === 'evaluations' && visual && steps && (
        <>
          <CaseEditor cases={steps as unknown as EvalCase[]} hasKnowledge={(data.knowledge_ids || []).length > 0} onChange={(next) => setJSON(JSON.stringify(next, null, 2))} />
          {field('pass_threshold', 'Required pass fraction (0–1)', 'number')}
        </>
      )}
      {['evaluations', 'workflows'].includes(kind) && !(visual && steps) && (
        <>
          <Field label={kind === 'workflows' ? 'Workflow steps (JSON)' : 'Test cases (JSON)'}>
            <textarea className="code-input" rows={12} value={json} onChange={(e) => setJSON(e.target.value)} required />
          </Field>
          {kind === 'evaluations' && field('pass_threshold', 'Required pass fraction (0–1)', 'number')}
          <p className="note">
            {kind === 'workflows'
              ? 'Steps: retrieve, generate, template, condition, approval, extract, action, handoff (Zyntra). Dependencies must precede each step.'
              : 'Each case can combine contains / excludes assertions, an LLM judge with criteria and min_score, and grounded: true (needs knowledge). Inspect run evidence for per-case reasons.'}
          </p>
        </>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="submit" className="primary">
          {existing ? 'Save new revision' : 'Create resource'}
          <ArrowRight size={15} />
        </button>
      </div>
    </form>
  );
}
