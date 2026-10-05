// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { useEffect, useState, type FormEvent } from 'react';
import { ArrowRight, Search } from 'lucide-react';
import { api, type Row } from '../api';
import type { Collections } from '../lib/types';
import { Field } from './kit';
import { WorkflowBuilder } from './WorkflowCanvas';
import CaseEditor, { cleanCase, type EvalCase } from './CaseEditor';
import PolicyFields from './PolicyFields';
import VariantEditor from './VariantEditor';
import { topoOrder, type Step } from '../lib/dag';
import { formatMeta, parseMeta, splitGroups } from '../lib/meta';

const KEYS: Record<string, string[]> = {
  actions: ['url', 'method', 'key_env', 'description'],
  models: ['provider', 'base_url', 'upstream_model', 'key_env', 'region', 'input_price', 'output_price', 'cached_input_price', 'capability', 'enabled', 'vision'],
  routers: ['models', 'judge_model', 'min_score'],
  knowledge: ['embedding_model', 'rerank_model', 'ocr_model', 'transcription_model'],
  agents: ['model', 'system_prompt', 'knowledge_ids', 'tools', 'max_steps', 'summarize_memory'],
  mcp_servers: ['url', 'key_env', 'readonly', 'tools'],
  connectors: ['type', 'knowledge_id', 'url', 'depth', 'max_pages', 'bucket', 'prefix', 'region', 'space', 'username', 'key_env', 'metadata', 'groups', 'interval_minutes'],
  prompts: ['template', 'variants'],
  policies: ['redact_pii', 'detect_injection', 'max_chars', 'daily_tokens', 'blocked_topics', 'word_filters', 'regex_filters', 'pii_entities', 'grounding_threshold', 'classifier_model', 'classifier_categories', 'classifier_threshold', 'cache_ttl'],
  recipes: ['model', 'method', 'dataset', 'dataset_id', 'teacher_model', 'rank', 'epochs'],
  evaluations: ['model', 'pass_threshold', 'judge_model', 'knowledge_ids'],
  workflows: [],
};

export function toolLabel(name: string, info?: Row): string {
  const description: string = info?.description || '';
  if (name.startsWith('mcp_') && description.startsWith('[MCP ')) return `${description.slice(5, description.indexOf(']')).split(' · ')[0]} · ${name.split('_').slice(2).join('_')}`;
  return name.replaceAll('_', ' ');
}

export function connectorKeys(type: string | undefined): string[] {
  if (type === 's3') return ['type', 'knowledge_id', 'bucket', 'prefix', 'region', 'max_pages'];
  if (type === 'confluence') return ['type', 'knowledge_id', 'url', 'space', 'key_env', 'username', 'max_pages'];
  return ['type', 'knowledge_id', 'url', 'depth', 'max_pages'];
}

export function createLabel(kind: string): string {
  if (kind === 'knowledge') return 'knowledge base';
  if (kind === 'policies') return 'policy';
  if (kind === 'actions') return 'action';
  if (kind === 'mcp_servers') return 'MCP server';
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
    url: kind === 'connectors' ? '' : 'https://api.internal.example/status',
    type: 'web',
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
  const [metaText, setMetaText] = useState(formatMeta(existing?.metadata));
  const [groupText, setGroupText] = useState((existing?.groups || []).join(', '));
  const metaError = kind === 'connectors' ? parseMeta(metaText).error : undefined;
  const [tools, setTools] = useState<string[]>(['knowledge_search', 'list_models', 'memory_read', 'memory_search', 'memory_write']);
  const [toolInfo, setToolInfo] = useState<Record<string, Row>>({});
  const [presets, setPresets] = useState<Row[]>([]);
  const [found, setFound] = useState<Row[] | null>(null);
  const [discovering, setDiscovering] = useState(false);
  useEffect(() => {
    if (kind === 'agents')
      api('/api/tools')
        .then((r) => {
          setTools(Object.keys(r.tools));
          setToolInfo(r.tools);
        })
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
      for (const k of kind === 'connectors' ? connectorKeys(data.type) : KEYS[kind] || []) if (data[k] !== undefined && data[k] !== '') body[k] = data[k];
      if (kind === 'connectors') {
        body.type = data.type || 'web';
        const { meta, error: bad } = parseMeta(metaText);
        if (bad) throw new Error(bad);
        body.metadata = meta;
        body.groups = splitGroups(groupText);
        body.interval_minutes = data.interval_minutes ? Number(data.interval_minutes) : null;
      }
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
                <option>transcription</option>
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
            <Field label="USD / million cached input tokens (optional)">
              <input
                type="number"
                step="any"
                min={0}
                value={data.cached_input_price ?? ''}
                onChange={(e) => set('cached_input_price', e.target.value === '' ? null : Number(e.target.value))}
              />
            </Field>
          </div>
          <label className="check">
            <input type="checkbox" checked={!!data.enabled} onChange={(e) => set('enabled', e.target.checked)} />
            Enabled for routing
          </label>
          {data.capability === 'chat' && (
            <label className="check">
              <input type="checkbox" checked={!!data.vision} onChange={(e) => set('vision', e.target.checked)} />
              Accepts images (vision)
            </label>
          )}
        </>
      )}
      {kind === 'mcp_servers' && (
        <>
          {field('url', 'MCP endpoint (Streamable HTTP) · host must be allowed by the operator')}
          {field('key_env', 'Secret environment reference (optional)')}
          <label className="check">
            <input type="checkbox" checked={!!data.readonly} onChange={(e) => set('readonly', e.target.checked)} />
            Read-only server: run its tools without approval
          </label>
          {existing?.available?.length ? (
            <fieldset className="policy-group">
              <legend>Tools agents may use</legend>
              <div className="check-list">
                {existing.available.map((t: string) => (
                  <label key={t}>
                    <input
                      type="checkbox"
                      checked={(data.tools || []).includes(t)}
                      onChange={(e) => set('tools', e.target.checked ? [...(data.tools || []), t] : (data.tools || []).filter((x: string) => x !== t))}
                    />
                    {t}
                  </label>
                ))}
              </div>
            </fieldset>
          ) : (
            <p className="note">Saving connects to the server and lists its tools. Edit the server afterwards to choose which tools agents may call.</p>
          )}
        </>
      )}
      {kind === 'connectors' && (
        <>
          <div className="form-grid">
            <Field label="Source">
              <select value={data.type || 'web'} onChange={(e) => setData({ ...data, type: e.target.value, url: e.target.value === 's3' ? undefined : '' })} disabled={!!existing}>
                <option value="web">Website crawl</option>
                <option value="s3">S3 prefix</option>
                <option value="confluence">Confluence space</option>
              </select>
            </Field>
            <Field label="Knowledge base">
              <select value={data.knowledge_id || ''} onChange={(e) => set('knowledge_id', e.target.value)} required>
                <option value="">Choose…</option>
                {(collections.knowledge || []).map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          {(data.type || 'web') === 'web' && (
            <>
              {field('url', 'Start URL · host must be in NUVORA_CONNECTOR_HOSTS')}
              <div className="form-grid">
                <Field label="Link depth (0–3)">
                  <input type="number" min={0} max={3} value={data.depth ?? 1} onChange={(e) => set('depth', Number(e.target.value))} />
                </Field>
                <Field label="Page limit">
                  <input type="number" min={1} max={200} value={data.max_pages ?? 25} onChange={(e) => set('max_pages', Number(e.target.value))} />
                </Field>
              </div>
              <p className="note">Same host only; robots.txt and its crawl delay are honoured; redirects are not followed.</p>
            </>
          )}
          {data.type === 's3' && (
            <div className="form-grid">
              {field('bucket', 'Bucket')}
              <Field label="Prefix (optional)">
                <input value={data.prefix || ''} onChange={(e) => set('prefix', e.target.value)} />
              </Field>
              <Field label="Region (optional)">
                <input value={data.region || ''} onChange={(e) => set('region', e.target.value)} />
              </Field>
              <Field label="Object limit">
                <input type="number" min={1} max={500} value={data.max_pages ?? 100} onChange={(e) => set('max_pages', Number(e.target.value))} />
              </Field>
            </div>
          )}
          {data.type === 'confluence' && (
            <>
              {field('url', 'Confluence base URL · host must be in NUVORA_CONNECTOR_HOSTS')}
              <div className="form-grid">
                {field('space', 'Space key')}
                <Field label="Page limit">
                  <input type="number" min={1} max={500} value={data.max_pages ?? 100} onChange={(e) => set('max_pages', Number(e.target.value))} />
                </Field>
                <Field label="Token environment reference">
                  <input value={data.key_env || ''} placeholder="NUVORA_SECRET_CONFLUENCE" onChange={(e) => set('key_env', e.target.value)} required />
                </Field>
                <Field label="Account email (Cloud basic auth; empty for a bearer token)">
                  <input value={data.username || ''} onChange={(e) => set('username', e.target.value)} />
                </Field>
              </div>
            </>
          )}
          <div className="form-grid">
            <Field label="Sync every (minutes, empty for manual)">
              <input type="number" min={15} max={10080} value={data.interval_minutes ?? ''} onChange={(e) => set('interval_minutes', e.target.value === '' ? null : Number(e.target.value))} />
            </Field>
            <Field label="Visible to groups (comma-separated; empty for everyone)">
              <input value={groupText} onChange={(e) => setGroupText(e.target.value)} />
            </Field>
          </div>
          <Field label="Metadata added to every document · key=value per line">
            <textarea rows={3} value={metaText} onChange={(e) => setMetaText(e.target.value)} aria-invalid={!!metaError} />
          </Field>
          {metaError && <p className="note danger-text">{metaError}</p>}
        </>
      )}
      {kind === 'routers' && (
        <>
          <fieldset className="policy-group">
            <legend>Tiers, cheapest first (select in order)</legend>
            <div className="check-list">
              {chatModels.map((m) => {
                const tiers: string[] = data.models || [];
                const at = tiers.indexOf(m.id);
                return (
                  <label key={m.id}>
                    <input
                      type="checkbox"
                      checked={at >= 0}
                      onChange={(e) => set('models', e.target.checked ? [...tiers, m.id] : tiers.filter((x) => x !== m.id))}
                    />
                    {at >= 0 ? `${at + 1}. ` : ''}
                    {m.name}
                  </label>
                );
              })}
            </div>
          </fieldset>
          <div className="form-grid">
            <Field label="Judge model (optional)">
              <select value={data.judge_model || ''} onChange={(e) => set('judge_model', e.target.value || null)}>
                <option value="">Heuristics only · empty or hedged answers escalate</option>
                {chatModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Escalate below judge score">
              <input type="number" min={0} max={1} step={0.05} value={data.min_score ?? 0.7} onChange={(e) => set('min_score', Number(e.target.value))} />
            </Field>
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
      {kind === 'knowledge' && (
        <div className="form-grid">
          <Field label="OCR for images and scanned PDFs">
            <select value={data.ocr_model || ''} onChange={(e) => set('ocr_model', e.target.value)}>
              <option value="">Local Tesseract (ocr extra)</option>
              {chatModels
                .filter((m) => m.vision || m.provider === 'demo')
                .map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
            </select>
          </Field>
          <Field label="Audio transcription">
            <select value={data.transcription_model || ''} onChange={(e) => set('transcription_model', e.target.value)}>
              <option value="">None · audio uploads refused</option>
              {(collections.models || [])
                .filter((m) => m.capability === 'transcription')
                .map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
            </select>
          </Field>
        </div>
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
                {toolLabel(t, toolInfo[t])}
              </label>
            ))}
          </div>
          {field('max_steps', 'Maximum model steps', 'number')}
          <label className="check">
            <input type="checkbox" checked={!!data.summarize_memory} onChange={(e) => set('summarize_memory', e.target.checked)} />
            Summarize each run into long-term memory (a different person approves each summary)
          </label>
        </>
      )}
      {kind === 'prompts' && (
        <>
          <Field label="Prompt template · {{variable}} syntax">
            <textarea rows={7} value={data.template} onChange={(e) => set('template', e.target.value)} required />
          </Field>
          <VariantEditor variants={data.variants || []} onChange={(v) => set('variants', v)} />
        </>
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
          <Field label="Response cache lifetime (seconds)">
            <input type="number" min={30} max={86400} value={data.cache_ttl ?? 300} onChange={(e) => set('cache_ttl', Number(e.target.value))} />
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
          <Field label="Training dataset">
            <select value={data.dataset_id || ''} onChange={(e) => set('dataset_id', e.target.value || undefined)}>
              <option value="">None · export only</option>
              {(collections.datasets || []).map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} · {d.records} {d.format} records
                </option>
              ))}
            </select>
          </Field>
          {data.method === 'distillation' && (
            <Field label="Teacher model (answers each prompt)">
              <select value={data.teacher_model || ''} onChange={(e) => set('teacher_model', e.target.value)} required>
                <option value="">Choose…</option>
                {chatModels
                  .filter((m) => m.id !== data.model)
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
              </select>
            </Field>
          )}
          <div className="form-grid">
            <Field label="LoRA rank">
              <input type="number" min={1} max={256} value={data.rank ?? 16} onChange={(e) => set('rank', Number(e.target.value))} />
            </Field>
            <Field label="Epochs">
              <input type="number" min={1} max={50} value={data.epochs ?? 3} onChange={(e) => set('epochs', Number(e.target.value))} />
            </Field>
          </div>
          <Field label="Dataset path for an external trainer (optional)">
            <input value={data.dataset || ''} onChange={(e) => set('dataset', e.target.value)} />
          </Field>
          <p className="note">With a dataset and a configured trainer, LoRA, QLoRA and distillation recipes train from Nuvora and register the result as a model. Evaluation and quantization recipes are export only.</p>
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
