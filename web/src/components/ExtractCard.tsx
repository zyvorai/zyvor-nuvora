// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { useState, type FormEvent } from 'react';
import { ScanText } from 'lucide-react';
import { api, type Row } from '../api';
import { Card, Field } from './kit';
import type { Act } from '../lib/types';

export const FIELD_TYPES = ['string', 'number', 'integer', 'boolean', 'date'];

export function parseFields(text: string): { fields: Record<string, { type: string; description: string }>; error?: string } {
  const fields: Record<string, { type: string; description: string }> = {};
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    const m = line.match(/^([a-z][a-z0-9_]{0,63})\s*(?::\s*([a-z]+))?\s*(?:[-—]\s*(.*))?$/);
    if (!m) return { fields, error: `Use "name: type - description" on each line (got "${line}")` };
    const type = m[2] || 'string';
    if (!FIELD_TYPES.includes(type)) return { fields, error: `Unknown type "${type}"; use ${FIELD_TYPES.join(', ')}` };
    fields[m[1]] = { type, description: (m[3] || '').slice(0, 500) };
  }
  const count = Object.keys(fields).length;
  if (!count || count > 30) return { fields, error: 'Define 1–30 fields' };
  return { fields };
}

export function ExtractCard({ docs, models, canWrite, act }: { docs: Row[]; models: Row[]; canWrite: boolean; act: Act }) {
  const [doc, setDoc] = useState('');
  const [spec, setSpec] = useState('invoice_number: string - Invoice identifier\ntotal: number - Amount due\ndue_date: date');
  const [model, setModel] = useState('auto');
  const [threshold, setThreshold] = useState(0.7);
  const [review, setReview] = useState(true);
  const parsed = parseFields(spec);
  const chat = models.filter((m) => m.capability === 'chat' && m.enabled !== false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (parsed.error) return;
    await act(
      () => api('/api/extract', { document_id: doc || docs[0]?.id, fields: parsed.fields, model, min_confidence: threshold, review }),
      'Extraction queued · see Runs',
    );
  }

  return (
    <Card title="Extract fields" eyebrow="Blueprint">
      {docs.length === 0 ? (
        <p className="muted">Index a document (including scanned PDFs or images) to extract structured fields from it.</p>
      ) : (
        <form onSubmit={submit}>
          <div className="form-grid">
            <Field label="Document">
              <select value={doc || docs[0]?.id} onChange={(e) => setDoc(e.target.value)}>
                {docs.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Model">
              <select value={model} onChange={(e) => setModel(e.target.value)}>
                <option value="auto">Lowest configured price</option>
                {chat.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Fields · one per line: name: type - description">
            <textarea value={spec} onChange={(e) => setSpec(e.target.value)} rows={4} aria-invalid={!!parsed.error} />
          </Field>
          {parsed.error && <p className="note danger-text">{parsed.error}</p>}
          <div className="form-grid">
            <Field label="Review fields below confidence">
              <input type="number" min={0} max={1} step={0.05} value={threshold} onChange={(e) => setThreshold(Number(e.target.value))} />
            </Field>
            <label className="check">
              <input type="checkbox" checked={review} onChange={(e) => setReview(e.target.checked)} />
              Send low-confidence results to an approver
            </label>
          </div>
          <button type="submit" className="btn-secondary" disabled={!canWrite || !!parsed.error}>
            <ScanText size={15} />
            Extract
          </button>
        </form>
      )}
    </Card>
  );
}
