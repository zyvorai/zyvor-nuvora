import { useEffect, useState } from 'react';
import { FileText } from 'lucide-react';
import { api, type Row } from '../api';
import { Card, Field } from '../components/kit';
import ResourceTable from '../components/ResourceTable';
import type { Act } from '../lib/types';

function PromptPreview({ prompt, act, canWrite, edit }: { prompt: Row; act: Act; canWrite: boolean; edit: () => void }) {
  const [variables, setVariables] = useState<Record<string, string>>({});
  const [rendered, setRendered] = useState('');
  useEffect(() => {
    setVariables({});
    setRendered('');
  }, [prompt.id]);
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
      <form
        className="prompt-render"
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await act(() => api('/api/prompts/' + prompt.id + '/render', { variables }));
          if (r) setRendered(r.text);
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
      {rendered && <pre>{rendered}</pre>}
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
}: {
  rows: Row[];
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
        rows={rows}
        columns={['name', 'variables', 'revision']}
        renderAction={(r) => (
          <button type="button" className="btn-secondary" onClick={() => onSelect(r)}>
            Render
          </button>
        )}
        emptyIcon={FileText}
        emptyTitle="No prompts yet"
        emptyText="Version the instructions that matter, with {{variables}} validated at render time."
      />
      {current && <PromptPreview prompt={current} act={act} canWrite={canWrite} edit={onEdit} />}
    </div>
  );
}
