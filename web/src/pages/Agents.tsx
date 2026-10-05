import { useState } from 'react';
import { Bot, Play } from 'lucide-react';
import { api, type Row } from '../api';
import { Card, Field } from '../components/kit';
import ResourceTable from '../components/ResourceTable';
import type { Act } from '../lib/types';

function AgentRunner({ agent, act, canWrite }: { agent: Row; act: Act; canWrite: boolean }) {
  const [message, setMessage] = useState('Explain Keep and human approval');
  const [result, setResult] = useState<Row | null>(null);
  return (
    <Card title={agent.name} eyebrow="Run agent">
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await act(() => api('/api/agents/' + agent.id + '/run', { message }));
          if (r) setResult(r);
        }}
      >
        <Field label="Task">
          <textarea rows={3} value={message} onChange={(e) => setMessage(e.target.value)} required />
        </Field>
        <button type="submit" className="primary" disabled={!canWrite}>
          <Play size={15} />
          Run agent
        </button>
        {result && (
          <p role="status" className="success">
            Run queued: <a href="#jobs">inspect {result.id}</a>
          </p>
        )}
      </form>
      <p className="note">
        Tools: {agent.tools.join(', ')}. Maximum {agent.max_steps} model steps. Memory writes pause for a different human’s approval.
      </p>
    </Card>
  );
}

export default function Agents({ rows, canWrite, act }: { rows: Row[]; canWrite: boolean; act: Act }) {
  const [details, setDetails] = useState<Row | null>(null);
  return (
    <div className="stack-page">
      <ResourceTable
        rows={rows}
        columns={['name', 'model', 'tools', 'max_steps']}
        emptyIcon={Bot}
        emptyTitle="No agents yet"
        emptyText="An agent pairs a model with registered tools and a step limit. Writes and external actions wait for approval."
        renderAction={(r) => (
          <button type="button" className="btn-secondary" disabled={!canWrite} onClick={() => setDetails(r)}>
            <Play size={14} />
            Open agent
          </button>
        )}
      />
      {details && <AgentRunner key={details.id} agent={details} canWrite={canWrite} act={act} />}
    </div>
  );
}
