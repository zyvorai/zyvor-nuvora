// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { useState, type FormEvent } from 'react';
import { ImageIcon } from 'lucide-react';
import { api, money, type Row } from '../api';
import { Badge, Card, Field } from './kit';
import type { Act } from '../lib/types';

export const IMAGE_SIZES = ['1024x1024', '1024x1792', '1792x1024', '512x512', '256x256'];

export function ImageStudio({ models, canWrite, act }: { models: Row[]; canWrite: boolean; act: Act }) {
  const imageModels = models.filter((m) => m.capability === 'image' && m.enabled !== false);
  const [model, setModel] = useState('auto');
  const [prompt, setPrompt] = useState('');
  const [size, setSize] = useState(IMAGE_SIZES[0]);
  const [n, setN] = useState(1);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Row[]>([]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const r = await act(() => api('/api/images', { model, prompt, size, n }));
    setBusy(false);
    if (r) setResults((prev) => [{ ...r, prompt }, ...prev].slice(0, 10));
  }

  return (
    <div className="stack-page">
      <Card title="Generate images">
        <form onSubmit={submit}>
          <div className="form-grid">
            <Field label="Model">
              <select value={model} onChange={(e) => setModel(e.target.value)}>
                <option value="auto">Auto · lowest image price</option>
                {imageModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Size">
              <select value={size} onChange={(e) => setSize(e.target.value)}>
                {IMAGE_SIZES.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </Field>
            <Field label="Images">
              <input type="number" min={1} max={4} value={n} onChange={(e) => setN(Number(e.target.value))} />
            </Field>
          </div>
          <Field label="Prompt">
            <textarea rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} required maxLength={4000} />
          </Field>
          <button type="submit" className="primary" disabled={!canWrite || busy}>
            <ImageIcon size={16} />
            {busy ? 'Generating…' : 'Generate'}
          </button>
          <p className="note">Prompts pass the workspace guardrail first. Images are stored as private artifacts that expire (seven days by default) and every generation is metered and audited.</p>
        </form>
      </Card>
      {results.map((r, i) => (
        <Card key={i} title={r.prompt.slice(0, 80)} eyebrow={`${r.size} · ${money(r.cost)} · ${r.latency_ms} ms`}>
          {r.evidence_class && <Badge value={r.evidence_class} />}
          <div className="image-grid">
            {r.images.map((img: Row) => (
              <a key={img.id} href={img.url} target="_blank" rel="noreferrer">
                <img src={img.url} alt={r.prompt.slice(0, 120)} loading="lazy" />
              </a>
            ))}
          </div>
        </Card>
      ))}
    </div>
  );
}
