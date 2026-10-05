// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Braces, Copy, Download, Pencil, Play, Trash2 } from 'lucide-react';
import { ago, api, download, time, type Row } from '../api';
import { diffLines, pretty } from '../lib/diff';
import { ADMIN_KINDS, duplicateBody, FIELDS, RUNNABLE, singular } from '../lib/resources';
import type { Act } from '../lib/types';
import Drawer from './Drawer';
import { Badge, Field, ListEmpty, Skeleton } from './kit';
import { useToast } from './Toasts';

type Tab = 'overview' | 'history' | 'diff' | 'json';

const HIDDEN = new Set(['id', 'name', 'created', 'updated', 'revision', 'tenant']);

function value(v: unknown): ReactNode {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (Array.isArray(v)) return v.length ? (typeof v[0] === 'object' ? `${v.length} items` : v.join(', ')) : 'None';
  if (typeof v === 'object') return `${Object.keys(v as object).length} fields`;
  return String(v);
}

export default function ResourceDrawer({
  kind,
  row,
  principal,
  act,
  close,
  onEdit,
  onRun,
  children,
}: {
  kind: string;
  row: Row;
  principal: Row;
  act: Act;
  close: () => void;
  onEdit: (row: Row) => void;
  onRun: (jobId: string) => void;
  children?: ReactNode;
}) {
  const toast = useToast();
  const [tab, setTab] = useState<Tab>('overview');
  const [versions, setVersions] = useState<Row[] | null>(null);
  const [pair, setPair] = useState<[number, number] | null>(null);
  const [runText, setRunText] = useState(RUNNABLE[kind]?.placeholder || '');
  const [queued, setQueued] = useState('');
  const [confirm, setConfirm] = useState(false);
  const writable = kind in FIELDS;
  const role = principal.role;
  const canEdit = writable && (role === 'admin' || (role === 'developer' && !ADMIN_KINDS.includes(kind)));
  const canDelete = writable && role === 'admin';
  const canRun = kind in RUNNABLE && (role === 'admin' || role === 'developer');

  useEffect(() => {
    if (!writable || (tab !== 'history' && tab !== 'diff') || versions) return;
    let live = true;
    api(`/api/${kind}/${row.id}/versions`)
      .then((r) => {
        if (!live) return;
        const items = [...r.items].sort((a: Row, b: Row) => (b.snapshot?.revision || 0) - (a.snapshot?.revision || 0));
        setVersions(items);
        if (items.length > 1) setPair([1, 0]);
      })
      .catch(() => live && setVersions([]));
    return () => {
      live = false;
    };
  }, [tab, kind, row.id, writable, versions]);

  useEffect(() => setVersions(null), [row.revision]);

  const diff = useMemo(() => {
    if (!versions || !pair) return [];
    return diffLines(pretty(versions[pair[0]]?.snapshot), pretty(versions[pair[1]]?.snapshot));
  }, [versions, pair]);

  async function run() {
    const spec = RUNNABLE[kind];
    const r = await act(() => api(`/api/${kind}/${row.id}/run`, spec ? { [spec.field]: runText } : {}), `${singular(kind)} run queued`);
    if (r) setQueued(r.id);
  }

  async function duplicate() {
    const r = await act(() => api('/api/' + kind, duplicateBody(kind, row)), `Duplicated ${row.name}`);
    if (r) window.location.hash = `${kind}/${r.id}`;
  }

  async function remove() {
    const r = await act(() => api(`/api/${kind}/${row.id}`, undefined, 'DELETE'), `Deleted ${row.name}`);
    if (r) close();
  }

  const facts = Object.entries(row).filter(([k]) => !HIDDEN.has(k));
  const tabs: [Tab, string][] = [
    ['overview', 'Overview'],
    ...(writable ? ([['history', 'History'], ['diff', 'Diff']] as [Tab, string][]) : []),
    ['json', 'JSON'],
  ];

  return (
    <Drawer
      title={row.name || row.action || row.id}
      eyebrow={`${singular(kind)} · revision ${row.revision ?? 1}`}
      close={close}
      actions={
        canEdit && (
          <button type="button" className="btn-secondary compact" onClick={() => onEdit(row)}>
            <Pencil size={14} />
            Edit
          </button>
        )
      }
    >
      <div className="tabs" role="tablist" aria-label="Resource views">
        {tabs.map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <div className="drawer-section" role="tabpanel" aria-label="Overview">
          {children}
          {kind in RUNNABLE && (
            <form
              className="drawer-run"
              onSubmit={(e) => {
                e.preventDefault();
                run();
              }}
            >
              {RUNNABLE[kind] && (
                <Field label={RUNNABLE[kind]!.label}>
                  <textarea rows={3} value={runText} onChange={(e) => setRunText(e.target.value)} required />
                </Field>
              )}
              <button type="submit" className="primary" disabled={!canRun}>
                <Play size={15} />
                {RUNNABLE[kind]?.button || 'Run evaluation'}
              </button>
              {queued && (
                <p role="status" className="success">
                  Queued.{' '}
                  <button type="button" className="link" onClick={() => onRun(queued)}>
                    Inspect run {queued}
                  </button>
                </p>
              )}
            </form>
          )}
          <dl className="facts">
            {facts.map(([k, v]) => (
              <div key={k}>
                <dt>{k.replaceAll('_', ' ')}</dt>
                <dd>{k === 'status' ? <Badge value={String(v)} /> : value(v)}</dd>
              </div>
            ))}
            <div>
              <dt>id</dt>
              <dd>
                <code>{row.id}</code>
              </dd>
            </div>
            {row.created && (
              <div>
                <dt>created</dt>
                <dd title={time(row.created)}>{ago(row.created)}</dd>
              </div>
            )}
            {row.updated && (
              <div>
                <dt>updated</dt>
                <dd title={time(row.updated)}>{ago(row.updated)}</dd>
              </div>
            )}
          </dl>
          {(writable && (canEdit || canDelete)) && (
            <div className="drawer-actions">
              {canEdit && (
                <button type="button" className="btn-secondary" onClick={duplicate}>
                  <Copy size={15} />
                  Duplicate
                </button>
              )}
              {canDelete &&
                (confirm ? (
                  <span className="confirm">
                    Delete {row.name}?
                    <button type="button" className="danger compact" onClick={remove}>
                      Delete
                    </button>
                    <button type="button" className="link" onClick={() => setConfirm(false)}>
                      Cancel
                    </button>
                  </span>
                ) : (
                  <button type="button" className="btn-secondary danger-text" onClick={() => setConfirm(true)}>
                    <Trash2 size={15} />
                    Delete
                  </button>
                ))}
            </div>
          )}
        </div>
      )}

      {tab === 'history' && (
        <div className="drawer-section" role="tabpanel" aria-label="History">
          {!versions ? (
            <Skeleton rows={4} label="Loading history" />
          ) : versions.length ? (
            <ol className="version-list">
              {versions.map((v, i) => (
                <li key={v.id}>
                  <span className="version-list__rev">r{v.snapshot?.revision}</span>
                  <div>
                    <b>{i === 0 ? 'Current revision' : `Revision ${v.snapshot?.revision}`}</b>
                    <small>
                      {v.actor || 'unknown'} · <span title={time(v.created)}>{ago(v.created)}</span>
                    </small>
                  </div>
                  {i < versions.length - 1 && (
                    <button
                      type="button"
                      className="link"
                      onClick={() => {
                        setPair([i + 1, i]);
                        setTab('diff');
                      }}
                    >
                      Compare with r{versions[i + 1].snapshot?.revision}
                    </button>
                  )}
                </li>
              ))}
            </ol>
          ) : (
            <ListEmpty title="No history recorded" description="Revisions appear here each time this resource is saved." />
          )}
        </div>
      )}

      {tab === 'diff' && (
        <div className="drawer-section" role="tabpanel" aria-label="Diff">
          {!versions ? (
            <Skeleton rows={4} label="Loading revisions" />
          ) : versions.length < 2 ? (
            <ListEmpty title="Only one revision" description="Edit this resource to compare revisions side by side." />
          ) : (
            <>
              <div className="form-grid">
                {(['From', 'To'] as const).map((label, side) => (
                  <Field key={label} label={label}>
                    <select
                      value={pair?.[side] ?? 0}
                      onChange={(e) => {
                        const next: [number, number] = [...(pair || [1, 0])] as [number, number];
                        next[side] = Number(e.target.value);
                        setPair(next);
                      }}
                    >
                      {versions.map((v, i) => (
                        <option key={v.id} value={i}>
                          Revision {v.snapshot?.revision}
                        </option>
                      ))}
                    </select>
                  </Field>
                ))}
              </div>
              <div className="diff" role="region" aria-label="Revision differences">
                {diff.map((l, i) => (
                  <div key={i} className={l.op}>
                    {l.text || ' '}
                  </div>
                ))}
              </div>
              <p className="small muted">
                {diff.filter((l) => l.op === 'add').length} added · {diff.filter((l) => l.op === 'del').length} removed
              </p>
            </>
          )}
        </div>
      )}

      {tab === 'json' && (
        <div className="drawer-section" role="tabpanel" aria-label="JSON">
          <div className="drawer-actions">
            <button
              type="button"
              className="btn-secondary compact"
              onClick={() =>
                navigator.clipboard
                  .writeText(JSON.stringify(row, null, 2))
                  .then(() => toast('JSON copied'))
                  .catch(() => toast('Copy is unavailable in this browser', 'error'))
              }
            >
              <Braces size={14} />
              Copy JSON
            </button>
            <button type="button" className="btn-secondary compact" onClick={() => download(`nuvora-${kind}-${row.id}.json`, row)}>
              <Download size={14} />
              Download
            </button>
          </div>
          <pre className="code-block">{JSON.stringify(row, null, 2)}</pre>
        </div>
      )}
    </Drawer>
  );
}
