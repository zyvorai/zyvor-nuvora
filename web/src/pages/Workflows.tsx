// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { Play, Workflow } from 'lucide-react';
import type { Row } from '../api';
import ResourceTable from '../components/ResourceTable';
import { usePageActions } from '../lib/pageContext';

export default function Workflows({ rows }: { rows: Row[] }) {
  const page = usePageActions();
  return (
    <div className="stack-page">
      <ResourceTable
        rows={rows}
        columns={['name', 'revision', 'steps']}
        renderAction={(r) => (
          <button type="button" className="btn-secondary" onClick={() => page.open?.(r)}>
            <Play size={14} />
            Open workflow
          </button>
        )}
        emptyIcon={Workflow}
        emptyTitle="No workflows yet"
        emptyText="Chain retrieval, generation, extraction and human review into a pinned, checkpointed DAG."
      />
    </div>
  );
}
