// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { useEffect, useState } from 'react';
import { FileText } from 'lucide-react';
import { api, type Row } from '../api';
import { Card, Field } from '../components/kit';
import ResourceTable from '../components/ResourceTable';
import type { Act } from '../lib/types';
import { controlShare } from '../components/VariantEditor';

function PromptPreview({ prompt, act, canWrite, edit, evaluations, onQueued }: { prompt: Row; act: Act; canWrite: boolean; edit: () => void; evaluations: Row[]; onQueued: () => void }) {
  const [variables, setVariables] = useState<Record<string, string>>({});
  const [rendered, setRendered] = useState('');
  const [served, setServed] = useState('');
  const [suite, setSuite] = useState('');
  const [target, setTarget] = useState('');
  const variants: Row[] = prompt.variants || [];
  useEffect(() => {
    setVariables({});
    setRendered('');
    setServed('');
    setTarget(prompt.variables[0] || '');
  }, [prompt.id, prompt.variables]);
  return (
    <Card
      title={prompt.name + ' · revision ' + prompt.revision}
      actions={
        <button type="button" className="btn-secondary" disabled={!canWrite} onClick={edit}>
          Edit revision
        </button>
      }
    >
      <pre>{prompt.template}</pre>
      {variants.length > 0 && (
        <ul className="variant-list" aria-label="Variants">
          <li>
            <b>control</b> · {controlShare(variants)}% of traffic
          </li>
          {variants.map((v) => (
            <li key={v.name}>
              <b>{v.name}</b> · {v.weight}% · <code>{v.template.slice(0, 120)}</code>
            </li>
          ))}
        </ul>
      )}
      <form
        className="prompt-render"
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await act(() => api('/api/prompts/' + prompt.id + '/render', { variables }));
          if (r) {
            setRendered(r.text);
            setServed(r.variant);
          }
        }}
      >
        {prompt.variables.map((v: string) => (
          <Field key={v} label={v}>
            <input value={variables[v] || ''} onChange={(e) => setVariables({ ...variables, [v]: e.target.value })} required />
          </Field>
        ))}
        <button type="submit" className="btn-secondary">
          Render prompt
        </button>
      </form>
      {rendered && (
        <>
          {variants.length > 0 && <p className="note">Served variant: {served}</p>}
          <pre>{rendered}</pre>
        </>
      )}
      {variants.length > 0 && (
        <form
          className="prompt-render"
          aria-label="Run experiment"
          onSubmit={async (e) => {
            e.preventDefault();
            const others = Object.fromEntries(prompt.variables.filter((v: string) => v !== target).map((v: string) => [v, variables[v] || '']));
            const job = await act(() => api('/api/prompts/' + prompt.id + '/experiment', { evaluation: suite, variable: target, variables: others }), 'Experiment queued');
            if (job) onQueued();
          }}
        >
          <Field label="Evaluation suite">
            <select value={suite} onChange={(e) => setSuite(e.target.value)} required>
              <option value="">Choose a suite</option>
              {evaluations.map((ev) => (
                <option key={ev.id} value={ev.id}>
                  {ev.name}
                </option>
              ))}
            </select>
          </Field>
          {prompt.variables.length > 1 && (
            <Field label="Case input fills">
              <select value={target} onChange={(e) => setTarget(e.target.value)}>
                {prompt.variables.map((v: string) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </Field>
          )}
          <button type="submit" className="btn-secondary" disabled={!canWrite || !suite}>
            Run experiment
          </button>
          <p className="note">Runs every case against each variant and picks a winner only if it beats the control.</p>
        </form>
      )}
    </Card>
  );
}

export default function Prompts({
  rows,
  canWrite,
  act,
  selected,
  onSelect,
  onEdit,
  evaluations = [],
  onQueued = () => undefined,
}: {
  rows: Row[];
  evaluations?: Row[];
  onQueued?: () => void;
  canWrite: boolean;
  act: Act;
  selected: Row | null;
  onSelect: (r: Row) => void;
  onEdit: () => void;
}) {
  const current = selected ? rows.find((r) => r.id === selected.id) || selected : null;
  return (
    <div className="stack-page">
      <ResourceTable
        rows={rows.map((r) => ({ ...r, variant_count: (r.variants || []).length }))}
        columns={['name', 'variables', 'variant_count', 'revision']}
        renderAction={(r) => (
          <button type="button" className="btn-secondary" onClick={() => onSelect(r)}>
            Render
          </button>
        )}
        emptyIcon={FileText}
        emptyTitle="No prompts yet"
        emptyText="Version the instructions that matter, with {{variables}} validated at render time."
      />
      {current && <PromptPreview prompt={current} act={act} canWrite={canWrite} edit={onEdit} evaluations={evaluations} onQueued={onQueued} />}
    </div>
  );
}
