// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { useCallback, useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react';
import { ArrowRight, BookOpen, CheckCircle2, FileText, Loader2, Search, Trash2, TriangleAlert, Upload } from 'lucide-react';
import { ago, api, type Row } from '../api';
import { Card, Field, ListEmpty } from '../components/kit';
import type { Act } from '../lib/types';
import { usePageActions } from '../lib/pageContext';

const ACCEPT = '.txt,.md,.markdown,.json,.csv,.html,.htm,.docx,.pdf';
const MAX_BYTES = 20 * 1024 * 1024;

type Item = { key: string; name: string; state: 'queued' | 'uploading' | 'done' | 'error'; note?: string };

export function fileType(contentType: string | undefined): string {
  const t = contentType || 'text/plain';
  if (t.includes('wordprocessingml')) return 'DOCX';
  if (t === 'application/pdf') return 'PDF';
  if (t === 'text/html') return 'HTML';
  if (t === 'text/markdown') return 'MD';
  if (t === 'text/csv') return 'CSV';
  if (t === 'application/json') return 'JSON';
  return 'TEXT';
}

export function bytes(n: number | undefined): string {
  if (!n) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

async function base64(file: File): Promise<string> {
  const data = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  for (let i = 0; i < data.length; i += 0x8000) binary += String.fromCharCode(...data.subarray(i, i + 0x8000));
  return btoa(binary);
}

export default function Knowledge({ rows, canWrite, act, refresh }: { rows: Row[]; canWrite: boolean; act: Act; refresh: number }) {
  const [selected, setSelected] = useState('');
  const [docs, setDocs] = useState<Row[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [dragging, setDragging] = useState(false);
  const [paste, setPaste] = useState(false);
  const [name, setName] = useState('');
  const [text, setText] = useState('');
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<Row[]>([]);
  const [confirm, setConfirm] = useState('');
  const input = useRef<HTMLInputElement>(null);
  const id = selected || rows[0]?.id || '';
  const page = usePageActions();

  const load = useCallback(() => {
    if (!id) return;
    api('/api/knowledge/' + id + '/documents')
      .then((r) => setDocs(r.items))
      .catch(() => setDocs([]));
  }, [id]);
  useEffect(load, [load, refresh]);

  async function uploadFiles(files: File[]) {
    if (!files.length || !canWrite) return;
    const queued = files.map((f, i) => ({ key: `${Date.now()}-${i}-${f.name}`, name: f.name, state: 'queued' as const }));
    setItems((prev) => [...queued, ...prev].slice(0, 12));
    const update = (key: string, patch: Partial<Item>) => setItems((prev) => prev.map((x) => (x.key === key ? { ...x, ...patch } : x)));
    for (const [i, file] of files.entries()) {
      const key = queued[i].key;
      if (file.size > MAX_BYTES) {
        update(key, { state: 'error', note: 'Larger than 20 MB' });
        continue;
      }
      update(key, { state: 'uploading' });
      try {
        const r = await api('/api/knowledge/' + id + '/upload', { name: file.name, content_type: file.type, content_base64: await base64(file) });
        update(key, { state: 'done', note: `${r.characters?.toLocaleString() ?? ''} characters · ${String(r.digest).slice(0, 10)}…` });
      } catch (e) {
        update(key, { state: 'error', note: String(e instanceof Error ? e.message : e) });
      }
    }
    load();
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    uploadFiles(Array.from(e.dataTransfer.files));
  }

  async function ingest(e: FormEvent) {
    e.preventDefault();
    const r = await act(() => api('/api/knowledge/' + id + '/ingest', { name, text }), 'Document indexed');
    if (r) {
      setText('');
      setName('');
      load();
    }
  }

  async function retrieve(e: FormEvent) {
    e.preventDefault();
    const r = await act(() => api('/api/retrieve', { knowledge_ids: [id], query }));
    if (r) setResult(r.citations);
  }

  async function remove(doc: Row) {
    const r = await act(() => api('/api/documents/' + doc.id, undefined, 'DELETE'), `Deleted ${doc.name}`);
    setConfirm('');
    if (r) load();
  }

  if (!id)
    return (
      <ListEmpty
        icon={BookOpen}
        title="Create a knowledge base first"
        description="A knowledge base holds documents with content digests. Retrieval cites the exact passages it used."
        action={
          page.create && (
            <button type="button" className="primary" onClick={page.create}>
              Create knowledge base
            </button>
          )
        }
      />
    );

  const kb = rows.find((r) => r.id === id);
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

      <Card title="Add documents" eyebrow={kb?.name}>
        <div
          className={'dropzone' + (dragging ? ' over' : '') + (canWrite ? '' : ' disabled')}
          onDragOver={(e) => {
            e.preventDefault();
            if (canWrite) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <Upload size={26} />
          <b>Drop files to index them</b>
          <small>PDF, Word (.docx), HTML, Markdown, CSV, JSON or text · up to 20 MB each</small>
          <div className="actions">
            <button type="button" className="primary" disabled={!canWrite} onClick={() => input.current?.click()}>
              Choose files
            </button>
            <button type="button" className="btn-secondary" disabled={!canWrite} onClick={() => setPaste((v) => !v)} aria-expanded={paste}>
              Paste text
            </button>
          </div>
          <input
            ref={input}
            type="file"
            multiple
            hidden
            accept={ACCEPT}
            aria-label="Upload documents"
            onChange={(e) => {
              uploadFiles(Array.from(e.target.files || []));
              e.target.value = '';
            }}
          />
        </div>
        {items.length > 0 && (
          <ul className="upload-list" aria-label="Uploads">
            {items.map((x) => (
              <li key={x.key} className={x.state}>
                {x.state === 'done' ? <CheckCircle2 size={15} /> : x.state === 'error' ? <TriangleAlert size={15} /> : <Loader2 size={15} className={x.state === 'uploading' ? 'spin' : ''} />}
                <b>{x.name}</b>
                <small>{x.state === 'queued' ? 'Waiting' : x.state === 'uploading' ? 'Extracting and indexing…' : x.note}</small>
              </li>
            ))}
          </ul>
        )}
        {paste && (
          <form onSubmit={ingest} className="paste-form">
            <Field label="Document title">
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </Field>
            <Field label="Document text">
              <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} required />
            </Field>
            <button type="submit" className="primary" disabled={!canWrite}>
              Index document
            </button>
          </form>
        )}
      </Card>

      <div className="split">
        <Card title="Documents" eyebrow={`${docs.length} in this knowledge base`}>
          {docs.length === 0 ? (
            <p className="muted">No documents yet. Drop a file above to index it.</p>
          ) : (
            <ul className="doc-list">
              {docs.map((d) => (
                <li key={d.id}>
                  <FileText size={16} />
                  <div>
                    <b>{d.name}</b>
                    <small>
                      <span className="type-badge">{fileType(d.content_type)}</span> {bytes(d.bytes)} · {d.chunks} chunks · {ago(d.updated)} · <code>{String(d.digest).slice(0, 10)}</code>
                    </small>
                  </div>
                  {canWrite &&
                    (confirm === d.id ? (
                      <span className="confirm">
                        <button type="button" className="danger compact" onClick={() => remove(d)}>
                          Delete
                        </button>
                        <button type="button" className="link" onClick={() => setConfirm('')}>
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button type="button" className="icon" aria-label={'Delete ' + d.name} onClick={() => setConfirm(d.id)}>
                        <Trash2 size={15} />
                      </button>
                    ))}
                </li>
              ))}
            </ul>
          )}
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
                {r.rerank_score !== undefined && <> · Rerank {Number(r.rerank_score).toFixed(2)}</>}
              </small>
            </article>
          ))}
        </Card>
      </div>
    </div>
  );
}
