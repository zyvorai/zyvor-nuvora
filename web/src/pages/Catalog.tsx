import { api, download, money, type Row } from '../api';
import ResourceTable from '../components/ResourceTable';
import type { Act } from '../lib/types';

export function Models({ rows }: { rows: Row[] }) {
  return (
    <ResourceTable
      rows={rows}
      columns={['name', 'provider', 'upstream_model', 'capability', 'enabled']}
      renderAction={(r) => <span className="muted small">{money(r.input_price)} / 1M input</span>}
    />
  );
}

export function Actions({ rows }: { rows: Row[] }) {
  return (
    <ResourceTable
      rows={rows}
      columns={['name', 'method', 'url', 'requires_approval', 'revision']}
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
