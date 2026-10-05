import { Play } from 'lucide-react';
import { api, type Row } from '../api';
import ResourceTable from '../components/ResourceTable';
import type { Act } from '../lib/types';

export default function Evaluations({ rows, canWrite, act, onQueued }: { rows: Row[]; canWrite: boolean; act: Act; onQueued: () => void }) {
  return (
    <ResourceTable
      rows={rows}
      columns={['name', 'model', 'cases', 'pass_threshold']}
      renderAction={(r) => (
        <button
          type="button"
          className="btn-secondary"
          disabled={!canWrite}
          onClick={() => act(() => api('/api/evaluations/' + r.id + '/run', {})).then((j) => j && onQueued())}
        >
          <Play size={14} />
          Evaluate
        </button>
      )}
    />
  );
}
