import { useState } from 'react';
import { Play } from 'lucide-react';
import { api, type Row } from '../api';
import { Badge, Card, Field } from '../components/kit';
import ResourceTable from '../components/ResourceTable';
import type { Act } from '../lib/types';

function RunWorkflow({ workflow, act, canWrite }: { workflow: Row; act: Act; canWrite: boolean }) {
  const [text, setText] = useState('Explain Keep isolation');
  const [queued, setQueued] = useState('');
  return (
    <Card title={workflow.name} eyebrow={`Revision ${workflow.revision}`}>
      <div className="workflow-steps">
        {workflow.steps.map((s: Row, i: number) => (
          <div key={s.id}>
            <span>{String(i + 1).padStart(2, '0')}</span>
            <b>{s.id}</b>
            <Badge value={s.type} />
          </div>
        ))}
      </div>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await act(() => api('/api/workflows/' + workflow.id + '/run', { text }));
          if (r) setQueued(r.id);
        }}
      >
        <Field label="Workflow input">
          <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} required />
        </Field>
        <button type="submit" className="primary" disabled={!canWrite}>
          <Play size={15} />
          Start workflow
        </button>
        {queued && (
          <p role="status" className="success">
            Queued. <a href="#jobs">Inspect run {queued}</a>
          </p>
        )}
      </form>
    </Card>
  );
}

export default function Workflows({ rows, canWrite, act }: { rows: Row[]; canWrite: boolean; act: Act }) {
  const [details, setDetails] = useState<Row | null>(null);
  return (
    <div className="stack-page">
      <ResourceTable rows={rows} columns={['name', 'revision', 'steps']} onRow={setDetails} />
      {details && <RunWorkflow key={details.id} workflow={details} act={act} canWrite={canWrite} />}
    </div>
  );
}
