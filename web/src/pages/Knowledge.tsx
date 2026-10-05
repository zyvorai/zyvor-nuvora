import { useState, type FormEvent } from 'react';
import { ArrowRight, BookOpen, Search, Upload } from 'lucide-react';
import { api, type Row } from '../api';
import { Card, Field, ListEmpty } from '../components/kit';
import type { Act } from '../lib/types';

export default function Knowledge({ rows, canWrite, act }: { rows: Row[]; canWrite: boolean; act: Act }) {
  const [selected, setSelected] = useState('');
  const [name, setName] = useState('');
  const [text, setText] = useState('');
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<Row[]>([]);
  const [success, setSuccess] = useState('');
  const id = selected || rows[0]?.id || '';

  async function ingest(e: FormEvent) {
    e.preventDefault();
    const r = await act(() => api('/api/knowledge/' + id + '/ingest', { name, text }));
    if (r) {
      setSuccess(`${r.name}: ${String(r.digest).slice(0, 12)}… indexed`);
      setText('');
    }
  }

  async function retrieve(e: FormEvent) {
    e.preventDefault();
    const r = await act(() => api('/api/retrieve', { knowledge_ids: [id], query }));
    if (r) setResult(r.citations);
  }

  if (!id) return <ListEmpty icon={BookOpen} title="Create a knowledge base first" description="Use Create knowledge base above, then add documents." />;

  return (
    <div className="stack-page">
      <div className="kb-grid">
        {rows.map((k) => (
          <button type="button" key={k.id} className={'kb-card ' + (id === k.id ? 'chosen' : '')} onClick={() => setSelected(k.id)}>
            <BookOpen size={20} />
            <b>{k.name}</b>
            <small>{k.retrieval}</small>
            <span>
              Explore knowledge <ArrowRight size={14} />
            </span>
          </button>
        ))}
      </div>
      <div className="split">
        <Card title="Add a document">
          <form onSubmit={ingest}>
            <Field label="Document title">
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </Field>
            <Field label="Document text">
              <textarea value={text} onChange={(e) => setText(e.target.value)} rows={7} required />
            </Field>
            <div className="actions">
              <label className="buttonlike btn-secondary upload">
                <Upload size={16} />
                &nbsp;Load text file
                <input
                  type="file"
                  accept=".txt,.md,.csv,.json,.jsonl"
                  onChange={async (e) => {
                    const f = e.target.files?.[0];
                    if (f) {
                      setName(f.name);
                      setText(await f.text());
                    }
                  }}
                />
              </label>
              <button type="submit" className="primary" disabled={!canWrite}>
                Index document
              </button>
            </div>
            {success && (
              <p role="status" className="success">
                {success}
              </p>
            )}
          </form>
        </Card>
        <Card title="Inspect retrieval">
          <form onSubmit={retrieve}>
            <Field label="Search your knowledge">
              <input value={query} onChange={(e) => setQuery(e.target.value)} required />
            </Field>
            <button type="submit" className="btn-secondary">
              <Search size={15} />
              Retrieve evidence
            </button>
          </form>
          {result.map((r, i) => (
            <article className="citation" key={i}>
              <b>{r.document}</b>
              <p>{r.text}</p>
              <small>
                BM25 {Number(r.lexical_score).toFixed(3)} · Fusion {Number(r.score).toFixed(5)}
              </small>
            </article>
          ))}
        </Card>
      </div>
    </div>
  );
}
