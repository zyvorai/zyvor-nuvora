// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { Plus, Trash2 } from 'lucide-react';
import type { Row } from '../api';
import { Field } from './kit';

export type EvalCase = { input: string; contains?: string[]; excludes?: string[]; judge?: { criteria: string; min_score?: number }; grounded?: boolean };

const list = (v: string) =>
  v
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);

// Drops empty optional fields so the stored suite stays minimal and diffable.
export function cleanCase(c: EvalCase): EvalCase {
  const out: EvalCase = { input: c.input, contains: c.contains || [], excludes: c.excludes || [] };
  if (c.judge && c.judge.criteria.trim()) out.judge = { criteria: c.judge.criteria.trim(), min_score: c.judge.min_score ?? 0.7 };
  if (c.grounded) out.grounded = true;
  return out;
}

export function caseKinds(c: EvalCase): string[] {
  return [
    (c.contains?.length || c.excludes?.length) && 'assertions',
    c.judge && 'judge',
    c.grounded && 'grounded',
  ].filter(Boolean) as string[];
}

export default function CaseEditor({ cases, onChange, hasKnowledge }: { cases: EvalCase[]; onChange: (next: EvalCase[]) => void; hasKnowledge: boolean }) {
  const update = (i: number, patch: Partial<EvalCase>) => onChange(cases.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  return (
    <div className="case-editor">
      {cases.map((c, i) => (
        <fieldset key={i} className="case-card">
          <legend>
            Case {i + 1}
            {caseKinds(c).map((k) => (
              <span key={k} className="type-badge">
                {k}
              </span>
            ))}
          </legend>
          <Field label="Input">
            <textarea rows={2} value={c.input} onChange={(e) => update(i, { input: e.target.value })} required />
          </Field>
          <div className="form-grid">
            <Field label="Must contain (comma-separated)">
              <input value={(c.contains || []).join(', ')} onChange={(e) => update(i, { contains: list(e.target.value) })} />
            </Field>
            <Field label="Must not contain">
              <input value={(c.excludes || []).join(', ')} onChange={(e) => update(i, { excludes: list(e.target.value) })} />
            </Field>
          </div>
          <label className="check">
            <input type="checkbox" checked={!!c.judge} onChange={(e) => update(i, { judge: e.target.checked ? { criteria: '', min_score: 0.7 } : undefined })} />
            Grade with an LLM judge
          </label>
          {c.judge && (
            <div className="form-grid">
              <Field label="Judge criteria">
                <textarea rows={2} value={c.judge.criteria} onChange={(e) => update(i, { judge: { ...c.judge!, criteria: e.target.value } })} required maxLength={2000} />
              </Field>
              <Field label="Minimum judge score (0–1)">
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  value={c.judge.min_score ?? 0.7}
                  onChange={(e) => update(i, { judge: { ...c.judge!, min_score: Number(e.target.value) } })}
                />
              </Field>
            </div>
          )}
          <label className="check" title={hasKnowledge ? '' : 'Select knowledge bases for this suite first'}>
            <input type="checkbox" checked={!!c.grounded} disabled={!hasKnowledge && !c.grounded} onChange={(e) => update(i, { grounded: e.target.checked })} />
            Answer must be grounded in the selected knowledge
          </label>
          {cases.length > 1 && (
            <button type="button" className="link danger-text" onClick={() => onChange(cases.filter((_, j) => j !== i))}>
              <Trash2 size={13} /> Remove case
            </button>
          )}
        </fieldset>
      ))}
      <button type="button" className="btn-secondary compact" disabled={cases.length >= 100} onClick={() => onChange([...cases, { input: '', contains: [], excludes: [] }])}>
        <Plus size={14} /> Add case
      </button>
    </div>
  );
}

export function CaseResults({ cases }: { cases: Row[] }) {
  const pct = (v: number) => `${Math.round(v * 100)}%`;
  return (
    <div className="table-wrap">
      <table className="case-results" aria-label="Per-case results">
        <thead>
          <tr>
            <th>#</th>
            <th>Input</th>
            <th>Assertions</th>
            <th>Judge</th>
            <th>Grounded</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c, i) => (
            <tr key={i}>
              <td>{i + 1}</td>
              <td title={c.answer}>{c.input}</td>
              <td className={c.checks?.assertions ? 'green' : 'red'}>{c.checks?.assertions ? 'pass' : 'fail'}</td>
              <td>
                {c.judge ? (
                  <span className={c.checks?.judge ? 'green' : 'red'} title={c.judge.reason}>
                    {pct(c.judge.score)} / {pct(c.judge.min_score)}
                    <small className="muted"> {c.judge.reason}</small>
                  </span>
                ) : (
                  '—'
                )}
              </td>
              <td>
                {c.grounded ? (
                  <span className={c.checks?.grounded ? 'green' : 'red'} title={c.grounded.reason}>
                    {pct(c.grounded.score)} · {c.grounded.passages} passages
                    <small className="muted"> {c.grounded.reason}</small>
                  </span>
                ) : (
                  '—'
                )}
              </td>
              <td className={c.passed ? 'green' : 'red'}>{c.passed ? 'passed' : 'failed'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
