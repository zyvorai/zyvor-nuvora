import { useState } from 'react';
import { api, type Row } from '../api';
import { Card, Field } from '../components/kit';
import ResourceTable from '../components/ResourceTable';
import type { Act } from '../lib/types';

function GuardrailTester({ act }: { act: Act }) {
  const [text, setText] = useState('Contact alex@example.com for the account');
  const [result, setResult] = useState<Row | null>(null);
  return (
    <Card title="Test the active policy">
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await act(() => api('/api/guardrails/check', { text }));
          if (r) setResult(r);
        }}
      >
        <Field label="Input or output text">
          <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
        <button type="submit" className="btn-secondary">
          Check policy
        </button>
      </form>
      {result && <pre>{JSON.stringify(result, null, 2)}</pre>}
      <p className="note">Deterministic topic, instruction-pattern, size, and PII rules. These checks do not guarantee detection of every harmful input.</p>
    </Card>
  );
}

export default function Guardrails({ rows, act }: { rows: Row[]; act: Act }) {
  return (
    <div className="stack-page">
      <ResourceTable rows={rows} columns={['name', 'redact_pii', 'detect_injection', 'daily_tokens', 'revision']} />
      <GuardrailTester act={act} />
    </div>
  );
}
