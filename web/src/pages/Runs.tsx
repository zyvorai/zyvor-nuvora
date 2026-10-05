import { useState } from 'react';
import { ArrowRight } from 'lucide-react';
import { download, type Row } from '../api';
import { Card } from '../components/kit';
import ResourceTable from '../components/ResourceTable';

export default function Runs({ rows, focus }: { rows: Row[]; focus?: string }) {
  const [selected, setSelected] = useState<string | undefined>(focus);
  const run = rows.find((j) => j.id === selected);
  return (
    <div className="stack-page">
      <ResourceTable
        rows={rows}
        columns={['name', 'type', 'status', 'created']}
        onRow={(r) => setSelected(r.id)}
        emptyTitle="No runs yet"
        emptyText="Run an agent, workflow, evaluation or batch to see its evidence here."
        renderAction={(r) => (
          <button type="button" className="link" onClick={() => setSelected(r.id)}>
            Inspect <ArrowRight size={14} />
          </button>
        )}
      />
      {run && (
        <Card
          title="Run evidence"
          eyebrow={run.name}
          actions={
            <button type="button" className="btn-secondary" onClick={() => download('nuvora-run-' + run.id + '.json', run)}>
              Export evidence
            </button>
          }
        >
          <pre>{JSON.stringify(run, null, 2)}</pre>
        </Card>
      )}
    </div>
  );
}
