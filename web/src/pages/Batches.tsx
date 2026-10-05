import { useState } from 'react';
import { Boxes } from 'lucide-react';
import { api, type Row } from '../api';
import { Card, Field } from '../components/kit';
import type { Act } from '../lib/types';

export default function Batches({ models, canWrite, act, done }: { models: Row[]; canWrite: boolean; act: Act; done: () => void }) {
  const [model, setModel] = useState('auto');
  const [inputs, setInputs] = useState('Explain private AI\nExplain tenant isolation');
  return (
    <Card title="Submit a batch">
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const requests = inputs
            .split('\n')
            .filter(Boolean)
            .map((content) => ({ model, messages: [{ role: 'user', content }] }));
          const r = await act(() => api('/api/batches', { requests }));
          if (r) done();
        }}
      >
        <Field label="Model">
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="auto">Auto · lowest configured price</option>
            {models
              .filter((m) => m.capability === 'chat')
              .map((m) => (
                <option value={m.id} key={m.id}>
                  {m.name}
                </option>
              ))}
          </select>
        </Field>
        <Field label="One prompt per line (up to 100)">
          <textarea rows={8} value={inputs} onChange={(e) => setInputs(e.target.value)} required />
        </Field>
        <button type="submit" className="primary" disabled={!canWrite}>
          <Boxes size={16} />
          Queue batch
        </button>
      </form>
      <p className="note">Runs are durable. Each item records success or failure. A server interruption requires review rather than automatic replay.</p>
    </Card>
  );
}
