// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { useState } from 'react';
import { ShieldAlert } from 'lucide-react';
import { api, type Row } from '../api';
import { Card, Field } from '../components/kit';
import ResourceTable from '../components/ResourceTable';
import type { Act } from '../lib/types';

function GuardrailTester({ act }: { act: Act }) {
  const [text, setText] = useState('Contact alex@example.com for the account');
  const [sources, setSources] = useState('');
  const [result, setResult] = useState<Row | null>(null);
  return (
    <Card title="Test the active policy">
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const list = sources.split('\n---\n').map((s) => s.trim()).filter(Boolean);
          const r = await act(() => api('/api/guardrails/check', list.length ? { text, sources: list } : { text }));
          if (r) setResult(r);
        }}
      >
        <Field label="Input or output text">
          <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
        <Field label="Sources for the grounding check (optional; separate with a line of ---)">
          <textarea rows={2} value={sources} onChange={(e) => setSources(e.target.value)} />
        </Field>
        <button type="submit" className="btn-secondary">
          Check policy
        </button>
      </form>
      {result && (
        <div className="guard-verdict" role="status">
          <strong>{result.allowed ? 'Allowed' : 'Refused'}</strong>
          {result.reasons?.length > 0 && (
            <ul>
              {result.reasons.map((r: string) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
          {result.grounding && (
            <span>
              Grounding {result.grounding.score} (needs {result.grounding.threshold})
            </span>
          )}
          {result.text !== text && <pre>{result.text}</pre>}
        </div>
      )}
      <p className="note">Runs word, topic, injection, size, regex and PII rules, the grounding check and the classifier model if one is set. Deterministic rules don't catch every harmful input.</p>
    </Card>
  );
}

export default function Guardrails({ rows, act }: { rows: Row[]; act: Act }) {
  return (
    <div className="stack-page">
      <ResourceTable
        rows={rows}
        columns={['name', 'detect_injection', 'grounding_threshold', 'classifier_model', 'daily_tokens', 'revision']}
        emptyIcon={ShieldAlert}
        emptyTitle="No guardrail policy"
        emptyText="Without a policy, inputs and outputs pass unchecked. Add topic, PII, size and budget rules."
      />
      <GuardrailTester act={act} />
    </div>
  );
}
