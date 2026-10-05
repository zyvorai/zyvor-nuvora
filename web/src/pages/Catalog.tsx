// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { useState } from 'react';
import { Cpu, FlaskConical, Plug, RefreshCw, Route, Server } from 'lucide-react';
import { Card, Field } from '../components/kit';
import { api, download, money, type Row } from '../api';
import ResourceTable from '../components/ResourceTable';
import type { Act } from '../lib/types';

export function Models({ rows }: { rows: Row[] }) {
  return (
    <ResourceTable
      rows={rows}
      columns={['name', 'provider', 'upstream_model', 'capability', 'enabled']}
      renderAction={(r) => <span className="muted small">{money(r.input_price)} / 1M input</span>}
      emptyIcon={Cpu}
      emptyTitle="Connect your first model"
      emptyText="Add an OpenAI-compatible, Ollama or AWS endpoint. Credentials stay in environment variables, never in the catalog."
    />
  );
}

export function Routers({ rows, models }: { rows: Row[]; models: Row[] }) {
  const name = (id: string) => models.find((m) => m.id === id)?.name || id;
  return (
    <ResourceTable
      rows={rows.map((r) => ({ ...r, tiers: (r.models || []).map(name).join(' → '), judge: r.judge_model ? name(r.judge_model) : 'heuristics only' }))}
      columns={['name', 'tiers', 'judge', 'min_score', 'revision']}
      emptyIcon={Route}
      emptyTitle="No routers yet"
      emptyText="List two to five chat models, cheapest first. Select the router as router:<id> in Playground or the API."
    />
  );
}

function OpenAPIImport({ act }: { act: Act }) {
  const [spec, setSpec] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [keyEnv, setKeyEnv] = useState('');
  const [result, setResult] = useState<Row | null>(null);
  const [error, setError] = useState('');
  return (
    <Card title="Import from OpenAPI">
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setError('');
          let parsed: unknown;
          try {
            parsed = JSON.parse(spec);
          } catch {
            setError('Paste an OpenAPI 3 document as JSON.');
            return;
          }
          const r = await act(() => api('/api/actions/import-openapi', { spec: parsed, ...(baseUrl ? { base_url: baseUrl } : {}), ...(keyEnv ? { key_env: keyEnv } : {}) }), 'OpenAPI imported');
          if (r) setResult(r);
        }}
      >
        <Field label="OpenAPI 3 document (JSON)">
          <textarea className="code-input" rows={6} value={spec} onChange={(e) => setSpec(e.target.value)} required />
        </Field>
        <div className="form-grid">
          <Field label="Base URL (optional; defaults to the first server)">
            <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          </Field>
          <Field label="Secret environment reference (optional)">
            <input value={keyEnv} placeholder="NUVORA_SECRET_..." onChange={(e) => setKeyEnv(e.target.value)} />
          </Field>
        </div>
        {error && <p className="error">{error}</p>}
        <button type="submit" className="btn-secondary">
          Import operations
        </button>
      </form>
      {result && (
        <div className="guard-verdict" role="status">
          <strong>
            {result.created.length} imported, {result.skipped.length} skipped
          </strong>
          {result.skipped.length > 0 && (
            <ul>
              {result.skipped.map((s: Row) => (
                <li key={s.operation}>
                  {s.operation}: {s.reason}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <p className="note">GET operations with query parameters and POST operations with a flat JSON body become actions. POST actions always wait for approval.</p>
    </Card>
  );
}

export function Actions({ rows, act, isAdmin }: { rows: Row[]; act?: Act; isAdmin?: boolean }) {
  return (
    <div className="stack-page">
      <ResourceTable
        rows={rows}
        columns={['name', 'method', 'url', 'requires_approval', 'revision']}
        emptyIcon={Plug}
        emptyTitle="No API actions yet"
        emptyText="An administrator registers typed enterprise APIs here, or imports them from OpenAPI; agents call them as tools."
      />
      {isAdmin && act && <OpenAPIImport act={act} />}
    </div>
  );
}

export function syncSummary(r: Row): string {
  const x = r.last_result;
  if (!x) return 'never synced';
  return `${x.added} added · ${x.updated} updated · ${x.unchanged} unchanged · ${x.removed} removed` + (x.failed ? ` · ${x.failed} failed` : '');
}

export function Connectors({ rows, knowledge, act, isAdmin, onQueued }: { rows: Row[]; knowledge: Row[]; act: Act; isAdmin: boolean; onQueued: () => void }) {
  const kb = (id: string) => knowledge.find((k) => k.id === id)?.name || id;
  const source = (r: Row) => (r.type === 's3' ? `s3://${r.bucket}/${r.prefix || ''}` : r.type === 'confluence' ? `${r.url} · ${r.space}` : r.url);
  return (
    <ResourceTable
      rows={rows.map((r) => ({
        ...r,
        knowledge: kb(r.knowledge_id),
        source: source(r),
        schedule: r.interval_minutes ? `every ${r.interval_minutes} min` : 'manual',
        last_sync: syncSummary(r),
      }))}
      columns={['name', 'type', 'source', 'knowledge', 'schedule', 'last_sync']}
      renderAction={(r) =>
        isAdmin ? (
          <button
            type="button"
            className="btn-secondary compact"
            onClick={async (e) => {
              e.stopPropagation();
              if (await act(() => api(`/api/connectors/${r.id}/sync`, {}), 'Sync queued · see Runs')) onQueued();
            }}
          >
            <RefreshCw size={14} />
            Sync now
          </button>
        ) : null
      }
      emptyIcon={RefreshCw}
      emptyTitle="No connectors yet"
      emptyText="An administrator connects a website (hosts allowed by the operator), an S3 prefix or a Confluence space to a knowledge base."
    />
  );
}

export function McpServers({ rows }: { rows: Row[] }) {
  return (
    <ResourceTable
      rows={rows.map((r) => ({ ...r, enabled_tools: (r.tools || []).length + ' of ' + (r.available || []).length, mode: r.readonly ? 'read-only' : 'approval required' }))}
      columns={['name', 'url', 'mode', 'enabled_tools', 'revision']}
      emptyIcon={Server}
      emptyTitle="No MCP servers yet"
      emptyText="An administrator connects a Model Context Protocol server over HTTP, then chooses which of its tools agents may call."
    />
  );
}

export function Recipes({ rows, act }: { rows: Row[]; act: Act }) {
  return (
    <div className="stack-page">
      <p className="note">Recipes export configuration for an external trainer. Nuvora does not execute GPU training, distillation, or quantization in this release.</p>
      <ResourceTable
        rows={rows}
        columns={['name', 'method', 'model', 'status']}
        emptyIcon={FlaskConical}
        emptyTitle="No recipes yet"
        emptyText="Describe a LoRA, QLoRA, distillation or quantization run and export it for your external trainer."
        renderAction={(r) => (
          <button
            type="button"
            className="btn-secondary"
            onClick={() => act(() => api('/api/recipes/' + r.id + '/export', {})).then((v) => v && download('nuvora-recipe.json', v))}
          >
            Export recipe
          </button>
        )}
      />
    </div>
  );
}
