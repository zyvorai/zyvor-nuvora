// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { Cpu, FlaskConical, Plug, Route } from 'lucide-react';
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

export function Actions({ rows }: { rows: Row[] }) {
  return (
    <ResourceTable
      rows={rows}
      columns={['name', 'method', 'url', 'requires_approval', 'revision']}
      emptyIcon={Plug}
      emptyTitle="No connectors yet"
      emptyText="An administrator registers typed enterprise APIs here; agents call them as tools."
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
