// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { Plus, X } from 'lucide-react';
import type { Row } from '../api';
import { Field } from './kit';

export const PII_ENTITIES = ['email', 'phone', 'card', 'ssn', 'ipv4', 'iban'];
export const CLASSIFIER_CATEGORIES = ['hate', 'violence', 'sexual', 'self_harm', 'misconduct', 'prompt_attack'];

type Filter = { name: string; pattern: string; action: string };

export function splitList(value: string): string[] {
  return value
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function PolicyFields({ data, set, chatModels }: { data: Row; set: (k: string, v: unknown) => void; chatModels: Row[] }) {
  const entities: Record<string, string> | null = data.pii_entities ?? null;
  const filters: Filter[] = data.regex_filters ?? [];
  const categories: string[] = data.classifier_categories ?? [];
  const realModels = chatModels.filter((m) => m.provider !== 'demo');
  const setEntity = (name: string, action: string) => {
    const next = { ...(entities || {}) };
    if (action === 'off') delete next[name];
    else next[name] = action;
    set('pii_entities', next);
  };
  const setFilter = (i: number, patch: Partial<Filter>) => set('regex_filters', filters.map((f, j) => (j === i ? { ...f, ...patch } : f)));

  return (
    <>
      <Field label="Blocked words (comma-separated, whole words)">
        <input value={(data.word_filters ?? []).join(', ')} onChange={(e) => set('word_filters', splitList(e.target.value))} />
      </Field>

      <fieldset className="policy-group">
        <legend>Sensitive information</legend>
        {entities === null ? (
          <p className="note">
            Masking emails and account numbers with the basic rule.{' '}
            <button type="button" className="link" onClick={() => set('pii_entities', { email: 'mask', card: 'mask' })}>
              Choose entity types
            </button>
          </p>
        ) : (
          <div className="pii-grid">
            {PII_ENTITIES.map((name) => (
              <label key={name}>
                <span>{name}</span>
                <select aria-label={`${name} action`} value={entities[name] ?? 'off'} onChange={(e) => setEntity(name, e.target.value)}>
                  <option value="off">off</option>
                  <option value="mask">mask</option>
                  <option value="block">block</option>
                </select>
              </label>
            ))}
          </div>
        )}
      </fieldset>

      <fieldset className="policy-group">
        <legend>Regex filters</legend>
        {filters.map((f, i) => (
          <div className="filter-row" key={i}>
            <input aria-label="Filter name" placeholder="name" value={f.name} onChange={(e) => setFilter(i, { name: e.target.value })} />
            <input aria-label="Filter pattern" placeholder="pattern, e.g. TCK-\d+" className="code-input" value={f.pattern} onChange={(e) => setFilter(i, { pattern: e.target.value })} />
            <select aria-label="Filter action" value={f.action} onChange={(e) => setFilter(i, { action: e.target.value })}>
              <option value="mask">mask</option>
              <option value="block">block</option>
            </select>
            <button type="button" className="link danger-text" aria-label="Remove filter" onClick={() => set('regex_filters', filters.filter((_, j) => j !== i))}>
              <X size={14} />
            </button>
          </div>
        ))}
        <button type="button" className="btn-secondary compact" disabled={filters.length >= 20} onClick={() => set('regex_filters', [...filters, { name: '', pattern: '', action: 'mask' }])}>
          <Plus size={14} /> Add filter
        </button>
      </fieldset>

      <Field label="Grounding threshold (0–1; blank turns it off)">
        <input
          type="number"
          min={0}
          max={1}
          step={0.05}
          value={data.grounding_threshold ?? ''}
          onChange={(e) => set('grounding_threshold', e.target.value === '' ? null : Number(e.target.value))}
        />
      </Field>

      <fieldset className="policy-group">
        <legend>Classifier model</legend>
        <Field label="Model">
          <select value={data.classifier_model ?? ''} onChange={(e) => set('classifier_model', e.target.value || null)}>
            <option value="">None (deterministic rules only)</option>
            {realModels.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </Field>
        {data.classifier_model && (
          <>
            <div className="check-list">
              {CLASSIFIER_CATEGORIES.map((c) => (
                <label key={c}>
                  <input
                    type="checkbox"
                    checked={categories.includes(c)}
                    onChange={(e) => set('classifier_categories', e.target.checked ? [...categories, c] : categories.filter((x) => x !== c))}
                  />
                  {c.replaceAll('_', ' ')}
                </label>
              ))}
            </div>
            <Field label="Flag at confidence">
              <input type="number" min={0.05} max={1} step={0.05} value={data.classifier_threshold ?? 0.5} onChange={(e) => set('classifier_threshold', Number(e.target.value))} />
            </Field>
            <p className="note">The classifier checks each prompt and each full answer. If it can't give a verdict, the request is refused.</p>
          </>
        )}
      </fieldset>
    </>
  );
}
