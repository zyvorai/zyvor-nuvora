import { useState, type FormEvent } from 'react';
import { ArrowRight } from 'lucide-react';
import type { Row } from '../api';
import type { Collections } from '../lib/types';
import { Field } from './kit';

const KEYS: Record<string, string[]> = {
  actions: ['url', 'method', 'key_env', 'description'],
  models: ['provider', 'base_url', 'upstream_model', 'key_env', 'region', 'input_price', 'output_price', 'capability'],
  knowledge: ['embedding_model'],
  agents: ['model', 'system_prompt', 'knowledge_ids', 'tools', 'max_steps'],
  prompts: ['template', 'expected_revision'],
  policies: ['redact_pii', 'detect_injection', 'max_chars', 'daily_tokens', 'blocked_topics'],
  recipes: ['model', 'method', 'dataset', 'rank', 'epochs'],
  evaluations: ['model', 'pass_threshold'],
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
  const [data, setData] = useState<Row>(
    existing
      ? { name: existing.name, template: existing.template, expected_revision: existing.revision }
      : {
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
        }
  );
  const [json, setJSON] = useState(
    kind === 'actions'
      ? JSON.stringify({ type: 'object', properties: { query: { type: 'string' } }, required: [] }, null, 2)
      : kind === 'workflows'
        ? JSON.stringify([{ id: 'answer', type: 'generate', model: firstModel, depends_on: ['input'] }], null, 2)
        : JSON.stringify([{ input: 'Explain private AI', contains: ['AI'], excludes: [] }], null, 2)
  );
  const [error, setError] = useState('');
  const set = (k: string, v: unknown) => setData({ ...data, [k]: v });

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
      if (kind === 'actions') body.input_schema = JSON.parse(json);
      if (kind === 'workflows') body.steps = JSON.parse(json);
      if (kind === 'evaluations') body.cases = JSON.parse(json);
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
          <div className="form-grid">
            <Field label="Provider">
              <select value={data.provider} onChange={(e) => set('provider', e.target.value)}>
                {['openai', 'ollama', 'bedrock', 'demo'].map((p) => (
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
          {data.provider !== 'demo' && data.provider !== 'bedrock' && field('base_url', 'Base URL · host must be allowed by the operator')}
          {field('upstream_model', 'Upstream model identifier')}
          {data.provider === 'bedrock' ? field('region', 'AWS region') : field('key_env', 'Secret environment reference (optional)')}
          <div className="form-grid">
            {field('input_price', 'USD / million input tokens', 'number')}
            {field('output_price', 'USD / million output tokens', 'number')}
          </div>
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
      {['agents', 'recipes', 'evaluations'].includes(kind) && modelSelect}
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
            {['knowledge_search', 'list_models', 'memory_read', 'memory_write', ...(collections.actions || []).map((a) => 'action_' + a.id)].map((t) => (
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
      {['evaluations', 'workflows'].includes(kind) && (
        <>
          <Field label={kind === 'workflows' ? 'Workflow steps (JSON)' : 'Test cases (JSON)'}>
            <textarea className="code-input" rows={12} value={json} onChange={(e) => setJSON(e.target.value)} required />
          </Field>
          {kind === 'evaluations' && field('pass_threshold', 'Required pass fraction (0–1)', 'number')}
          <p className="note">
            {kind === 'workflows'
              ? 'Steps: retrieve, generate, template, condition, approval, extract. Dependencies must precede each step.'
              : 'Assertions use contains / excludes. Inspect run evidence for the release verdict.'}
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
