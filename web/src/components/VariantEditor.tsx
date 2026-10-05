// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { Plus, Trash2 } from 'lucide-react';
import { Field } from './kit';

export type Variant = { name: string; template: string; weight: number };

export function controlShare(variants: { weight?: unknown }[]): number {
  return 100 - variants.reduce((sum, v) => sum + (Number(v.weight) || 0), 0);
}

export default function VariantEditor({ variants, onChange }: { variants: Variant[]; onChange: (v: Variant[]) => void }) {
  const patch = (i: number, p: Partial<Variant>) => onChange(variants.map((v, j) => (j === i ? { ...v, ...p } : v)));
  const control = controlShare(variants);
  return (
    <fieldset className="policy-group">
      <legend>Variants (A/B)</legend>
      <p className="note">
        The main template is the control and serves {control}% of renders. The same user keeps the same variant for a revision. Variants must use the same variables.
      </p>
      {control < 0 && <p className="error">Variant traffic adds up to more than 100%.</p>}
      {variants.map((v, i) => (
        <div className="case-card" key={i}>
          <div className="form-grid">
            <Field label="Variant name">
              <input value={v.name} pattern="[a-z0-9_\-]{1,40}" onChange={(e) => patch(i, { name: e.target.value })} required />
            </Field>
            <Field label="Traffic %">
              <input type="number" min={0} max={100} step={1} value={v.weight} onChange={(e) => patch(i, { weight: Number(e.target.value) })} />
            </Field>
          </div>
          <Field label="Variant template">
            <textarea rows={4} value={v.template} onChange={(e) => patch(i, { template: e.target.value })} required />
          </Field>
          <button type="button" className="link danger-text" onClick={() => onChange(variants.filter((_, j) => j !== i))}>
            <Trash2 size={13} /> Remove variant
          </button>
        </div>
      ))}
      <button
        type="button"
        className="btn-secondary compact"
        disabled={variants.length >= 5}
        onClick={() => onChange([...variants, { name: `variant-${variants.length + 1}`, template: '', weight: 0 }])}
      >
        <Plus size={14} /> Add variant
      </button>
    </fieldset>
  );
}
