// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react';
import type { Row } from '../api';
import { layout, STEP_TYPES, topoOrder, type Step } from '../lib/dag';
import { IMAGE_SIZES } from './ImageStudio';
import type { Collections } from '../lib/types';
import { Field } from './kit';

export type StepStatus = 'completed' | 'waiting' | 'failed' | 'skipped' | 'pending';

const W = 156;
const H = 54;
const GX = 64;
const GY = 22;
const PAD = 14;

const TONE: Record<string, string> = {
  input: 'graphite',
  retrieve: 'green',
  generate: 'blue',
  template: 'graphite',
  condition: 'amber',
  extract: 'cyan',
  action: 'purple',
  approval: 'red',
  handoff: 'cyan',
  generate_image: 'purple',
};

const STATUS_LABEL: Record<StepStatus, string> = {
  completed: 'Completed',
  waiting: 'Waiting for a decision',
  failed: 'Failed',
  skipped: 'Skipped',
  pending: 'Not started',
};

export function stepStatuses(job: Row | undefined): Record<string, StepStatus> {
  if (!job) return {};
  const out: Record<string, StepStatus> = { input: 'completed' };
  const outputs = job.checkpoint?.outputs || {};
  for (const t of job.trace || []) if (t.step) out[t.step] = 'completed';
  for (const [k, v] of Object.entries(outputs)) if (v && typeof v === 'object' && (v as Row).skipped) out[k] = 'skipped';
  const steps: Step[] = job.spec?.steps || [];
  const idx = job.checkpoint?.index;
  if (typeof idx === 'number' && steps[idx]) {
    if (job.status === 'waiting_approval' || job.status === 'waiting_external') out[steps[idx].id] = 'waiting';
    else if (job.status === 'failed') out[steps[idx].id] = 'failed';
  }
  return out;
}

export default function WorkflowCanvas({
  steps,
  status,
  selected,
  onSelect,
  label = 'Workflow graph',
}: {
  steps: Step[];
  status?: Record<string, StepStatus>;
  selected?: string;
  onSelect?: (id: string) => void;
  label?: string;
}) {
  const g = useMemo(() => layout(steps), [steps]);
  const pos = new Map(g.nodes.map((n) => [n.id, { x: PAD + n.layer * (W + GX), y: PAD + n.row * (H + GY) }]));
  const layerOf = new Map(g.nodes.map((n) => [n.id, n.layer]));
  const long = g.edges.some((e) => (layerOf.get(e.to) ?? 0) - (layerOf.get(e.from) ?? 0) > 1);
  const width = PAD * 2 + g.layers * W + (g.layers - 1) * GX;
  const nodesBottom = PAD + g.rows * H + (g.rows - 1) * GY;
  const height = nodesBottom + PAD + (long ? GY : 0);
  return (
    <div className="dag-scroll">
      <svg className="dag" viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label={`${label}: ${steps.map((s) => s.id).join(', ')}`}>
        <defs>
          <marker id="dag-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0 10 5 0 10z" className="dag__arrow" />
          </marker>
        </defs>
        {g.edges.map((e) => {
          const a = pos.get(e.from);
          const b = pos.get(e.to);
          if (!a || !b) return null;
          const x1 = a.x + W;
          const y1 = a.y + H / 2;
          const x2 = b.x - 2;
          const y2 = b.y + H / 2;
          const mid = (x1 + x2) / 2;
          const skips = (layerOf.get(e.to) ?? 0) - (layerOf.get(e.from) ?? 0) > 1;
          const low = nodesBottom + GY / 2;
          const d = skips
            ? `M${x1} ${y1} C${x1 + 32} ${y1} ${x1 + 32} ${low} ${x1 + 64} ${low} L${x2 - 64} ${low} C${x2 - 32} ${low} ${x2 - 32} ${y2} ${x2} ${y2}`
            : `M${x1} ${y1} C${mid} ${y1} ${mid} ${y2} ${x2} ${y2}`;
          const done = status?.[e.from] === 'completed' && !!status?.[e.to] && status[e.to] !== 'pending';
          return (
            <g key={e.from + '>' + e.to}>
              <path d={d} className={'dag__edge' + (e.conditional ? ' conditional' : '') + (done ? ' done' : '')} markerEnd="url(#dag-arrow)" />
              {e.conditional && (
                <text x={mid} y={(y1 + y2) / 2 - 6} textAnchor="middle" className="dag__when">
                  when true
                </text>
              )}
            </g>
          );
        })}
        {g.nodes.map((n) => {
          const p = pos.get(n.id)!;
          const s = status?.[n.id];
          const interactive = !!onSelect && n.id !== 'input';
          return (
            <g
              key={n.id}
              transform={`translate(${p.x} ${p.y})`}
              className={['dag__node', TONE[n.type] || 'graphite', s || '', selected === n.id ? 'selected' : '', interactive ? 'interactive' : ''].join(' ')}
              onClick={interactive ? () => onSelect!(n.id) : undefined}
              onKeyDown={interactive ? (e) => (e.key === 'Enter' || e.key === ' ') && onSelect!(n.id) : undefined}
              tabIndex={interactive ? 0 : undefined}
              role={interactive ? 'button' : undefined}
              aria-label={interactive ? `Step ${n.id}, ${n.type}${s ? ', ' + STATUS_LABEL[s] : ''}` : undefined}
            >
              <rect width={W} height={H} rx="12" className="dag__box" />
              <rect width="4" height={H - 20} x="10" y="10" rx="2" className="dag__stripe" />
              <text x="24" y="23" className="dag__id">
                {n.id.length > 16 ? n.id.slice(0, 15) + '…' : n.id}
              </text>
              <text x="24" y="40" className="dag__type">
                {n.type}
              </text>
              {s && s !== 'pending' && (
                <g transform={`translate(${W - 22} 14)`} className={'dag__status ' + s}>
                  <circle r="7" cx="4" cy="4" />
                  {s === 'completed' && <path d="M0.8 4.2 3 6.4 7.2 1.8" />}
                  {s === 'waiting' && <path d="M4 1.5v3l2 1.2" />}
                  {s === 'failed' && <path d="M1.5 1.5l5 5m0-5-5 5" />}
                </g>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function blank(type: string, collections: Collections, existing: Step[]): Step {
  let n = existing.length + 1;
  while (existing.some((s) => s.id === `${type}_${n}`)) n++;
  const last = existing[existing.length - 1]?.id;
  const step: Step = { id: `${type}_${n}`, type, depends_on: [last || 'input'] };
  if (type === 'generate') step.model = (collections.models || []).find((m) => m.capability === 'chat')?.id || '';
  if (type === 'retrieve') step.knowledge_id = collections.knowledge?.[0]?.id || '';
  if (type === 'generate_image') {
    step.model = (collections.models || []).find((m) => m.capability === 'image')?.id || '';
    step.prompt = `{{${last || 'input'}}}`;
    step.size = '1024x1024';
  }
  if (type === 'template') step.template = '{{input}}';
  if (type === 'condition') step.contains = '';
  if (type === 'extract') step.fields = ['summary'];
  if (type === 'handoff') {
    step.action = '';
    step.inputs = { summary: `{{${last || 'input'}}}` };
    step.timeout_hours = 72;
  }
  if (type === 'action') {
    step.action_id = collections.actions?.[0]?.id || '';
    step.arguments = {};
  }
  return step;
}

function HandoffInputs({ value, onChange }: { value: Row; onChange: (v: Row) => void }) {
  const [text, setText] = useState(JSON.stringify(value, null, 2));
  const [bad, setBad] = useState(false);
  return (
    <textarea
      className="code-input"
      rows={4}
      value={text}
      aria-invalid={bad}
      onChange={(e) => {
        setText(e.target.value);
        try {
          const v = JSON.parse(e.target.value);
          const ok = v && typeof v === 'object' && !Array.isArray(v);
          setBad(!ok);
          if (ok) onChange(v);
        } catch {
          setBad(true);
        }
      }}
    />
  );
}

export function WorkflowBuilder({ steps, onChange, collections }: { steps: Step[]; onChange: (steps: Step[]) => void; collections: Collections }) {
  const [selected, setSelected] = useState<string | undefined>(steps[0]?.id);
  const [adding, setAdding] = useState<string>('generate');
  const index = steps.findIndex((s) => s.id === selected);
  const step = steps[index];
  const ordered = topoOrder(steps);
  const update = (patch: Partial<Step>) => {
    let next = steps.map((s, i) => (i === index ? { ...s, ...patch } : s));
    if (patch.id && patch.id !== step.id) {
      const from = step.id;
      const to = patch.id;
      next = next.map((s) => ({ ...s, depends_on: s.depends_on?.map((d) => (d === from ? to : d)), when: s.when === from ? to : s.when }));
      setSelected(to);
    }
    onChange(next);
  };
  const move = (delta: number) => {
    const next = [...steps];
    const [s] = next.splice(index, 1);
    next.splice(index + delta, 0, s);
    onChange(next);
  };
  const remove = () => {
    const id = step.id;
    const next = steps
      .filter((s) => s.id !== id)
      .map((s) => ({ ...s, depends_on: (s.depends_on || []).filter((d) => d !== id), when: s.when === id ? undefined : s.when }));
    onChange(next);
    setSelected(next[Math.max(0, index - 1)]?.id);
  };
  const add = () => {
    const s = blank(adding, collections, steps);
    onChange([...steps, s]);
    setSelected(s.id);
  };
  const earlier = step ? ['input', ...steps.slice(0, index).map((s) => s.id)] : [];
  const conditions = step ? steps.slice(0, index).filter((s) => s.type === 'condition') : [];

  return (
    <div className="builder">
      <WorkflowCanvas steps={steps} selected={selected} onSelect={setSelected} label="Workflow builder" />
      {!ordered && <p className="error" role="alert">Steps reference a later or missing step. Reorder them so every dependency comes first.</p>}
      <div className="builder__bar">
        <Field label="Add step">
          <select value={adding} onChange={(e) => setAdding(e.target.value)}>
            {STEP_TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </Field>
        <button type="button" className="btn-secondary compact" onClick={add} disabled={steps.length >= 30}>
          <Plus size={14} />
          Add
        </button>
      </div>
      {step && (
        <fieldset className="builder__step">
          <legend>
            Step {index + 1} of {steps.length}
          </legend>
          <div className="form-grid">
            <Field label="Step id">
              <input value={step.id} pattern="[a-z][a-z0-9_]{0,31}" onChange={(e) => update({ id: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_').slice(0, 32) })} />
            </Field>
            <Field label="Step type">
              <select value={step.type} onChange={(e) => onChange(steps.map((s, i) => (i === index ? { ...blank(e.target.value, collections, steps), id: s.id, depends_on: s.depends_on, when: s.when } : s)))}>
                {STEP_TYPES.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </Field>
          </div>
          <div className="builder__deps" role="group" aria-label="Depends on">
            <span>Depends on</span>
            {earlier.map((d) => (
              <label key={d} className="check">
                <input
                  type="checkbox"
                  checked={(step.depends_on || []).includes(d)}
                  onChange={(e) => update({ depends_on: e.target.checked ? [...(step.depends_on || []), d] : (step.depends_on || []).filter((x) => x !== d) })}
                />
                {d}
              </label>
            ))}
          </div>
          {conditions.length > 0 && (
            <Field label="Run only when condition is true">
              <select value={step.when || ''} onChange={(e) => update({ when: e.target.value || undefined })}>
                <option value="">Always</option>
                {conditions.map((c) => (
                  <option key={c.id}>{c.id}</option>
                ))}
              </select>
            </Field>
          )}
          {step.type === 'generate' && (
            <>
              <Field label="Model">
                <select value={String(step.model || '')} onChange={(e) => update({ model: e.target.value })}>
                  {(collections.models || [])
                    .filter((m) => m.capability === 'chat')
                    .map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                </select>
              </Field>
              <Field label="Instruction (optional)">
                <textarea rows={2} value={String(step.instruction || '')} onChange={(e) => update({ instruction: e.target.value || undefined })} />
              </Field>
            </>
          )}
          {step.type === 'generate_image' && (
            <>
              <Field label="Image model">
                <select value={String(step.model || '')} onChange={(e) => update({ model: e.target.value })}>
                  {(collections.models || [])
                    .filter((m) => m.capability === 'image')
                    .map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                </select>
              </Field>
              <Field label="Prompt template · {{step}} inserts an earlier output">
                <textarea rows={2} value={String(step.prompt || '')} onChange={(e) => update({ prompt: e.target.value })} />
              </Field>
              <Field label="Size">
                <select value={String(step.size || '1024x1024')} onChange={(e) => update({ size: e.target.value })}>
                  {IMAGE_SIZES.map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </Field>
            </>
          )}
          {step.type === 'retrieve' && (
            <Field label="Knowledge base">
              <select value={String(step.knowledge_id || '')} onChange={(e) => update({ knowledge_id: e.target.value })}>
                {(collections.knowledge || []).map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {step.type === 'template' && (
            <Field label="Template · {{step_id}} inserts an earlier output">
              <textarea rows={3} value={String(step.template || '')} onChange={(e) => update({ template: e.target.value })} />
            </Field>
          )}
          {step.type === 'condition' && (
            <Field label="True when the context contains">
              <input value={String(step.contains || '')} onChange={(e) => update({ contains: e.target.value })} />
            </Field>
          )}
          {step.type === 'extract' && (
            <Field label="Fields to extract (comma-separated)">
              <input
                value={((step.fields as string[]) || []).join(', ')}
                onChange={(e) => update({ fields: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })}
              />
            </Field>
          )}
          {step.type === 'action' && (
            <Field label="Connector">
              <select value={String(step.action_id || '')} onChange={(e) => update({ action_id: e.target.value })}>
                {(collections.actions || []).map((a: Row) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {step.type === 'handoff' && (
            <>
              <div className="form-grid">
                <Field label="Zyntra action">
                  <input value={String(step.action || '')} onChange={(e) => update({ action: e.target.value })} placeholder="restart_service" required />
                </Field>
                <Field label="Scenario (optional)">
                  <input value={String(step.scenario || '')} onChange={(e) => update({ scenario: e.target.value || undefined })} />
                </Field>
              </div>
              <Field label="Inputs (JSON object · strings may use {{step_id}})">
                <HandoffInputs value={(step.inputs as Row) || {}} onChange={(inputs) => update({ inputs })} />
              </Field>
              <Field label="Give up after (hours)">
                <input type="number" min={1} max={720} value={Number(step.timeout_hours ?? 72)} onChange={(e) => update({ timeout_hours: Number(e.target.value) })} />
              </Field>
              <p className="note">Creates a Zyntra proposal and pauses as waiting_external. Zyntra’s own approvers decide; the run resumes with their result.</p>
            </>
          )}
          {step.type === 'approval' && <p className="note">Pauses the run until a different person approves the exact context digest.</p>}
          <div className="builder__actions">
            <button type="button" className="icon" aria-label="Move step earlier" disabled={index === 0} onClick={() => move(-1)}>
              <ArrowUp size={15} />
            </button>
            <button type="button" className="icon" aria-label="Move step later" disabled={index === steps.length - 1} onClick={() => move(1)}>
              <ArrowDown size={15} />
            </button>
            <button type="button" className="btn-secondary compact danger-text" onClick={remove} disabled={steps.length <= 1}>
              <Trash2 size={14} />
              Remove step
            </button>
          </div>
        </fieldset>
      )}
    </div>
  );
}
