import { useEffect, useMemo, useState } from 'react';
import { Download, ShieldCheck, X } from 'lucide-react';
import { api, download, time, type Row } from '../api';
import { Card, ListEmpty, TableWrap } from '../components/kit';

type Filters = { actor: string; action: string; since: string; until: string };
const EMPTY: Filters = { actor: '', action: '', since: '', until: '' };

function stamp(date: string, endOfDay = false): string {
  if (!date) return '';
  const d = new Date(date + (endOfDay ? 'T23:59:59' : 'T00:00:00'));
  return String(Math.floor(d.getTime() / 1000));
}

export function auditCSV(events: Row[]): string {
  const esc = (v: unknown) => {
    const s = typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v ?? '');
    return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
  };
  const cols = ['seq', 'time', 'actor', 'action', 'target', 'detail', 'digest', 'previous'];
  return [cols.join(','), ...events.map((e) => cols.map((c) => esc(c === 'time' ? new Date(e.time * 1000).toISOString() : e[c])).join(','))].join('\n');
}

export default function Audit({ refresh }: { refresh: number }) {
  const [data, setData] = useState<Row | null>(null);
  const [error, setError] = useState('');
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [applied, setApplied] = useState<Filters>(EMPTY);
  const [all, setAll] = useState<Row[]>([]);

  const query = useMemo(() => {
    const q = new URLSearchParams();
    if (applied.actor) q.set('actor', applied.actor);
    if (applied.action) q.set('action', applied.action);
    if (applied.since) q.set('since', stamp(applied.since));
    if (applied.until) q.set('until', stamp(applied.until, true));
    return q.toString();
  }, [applied]);

  useEffect(() => {
    api('/api/audit' + (query ? '?' + query : ''))
      .then((r) => {
        setData(r);
        if (!query) setAll(r.events || []);
      })
      .catch((e) => setError(String(e)));
  }, [refresh, query]);

  const actors = [...new Set(all.map((e) => e.actor))].sort();
  const families = [...new Set(all.map((e) => String(e.action).split('.')[0]))].sort();
  const events: Row[] = (data?.events || []).slice().reverse();
  const filtered = Boolean(query);
  const set = (k: keyof Filters, v: string) => {
    const next = { ...filters, [k]: v };
    setFilters(next);
    if (k !== 'since' && k !== 'until') setApplied(next);
  };

  return (
    <Card
      title="Audit evidence"
      actions={
        <div className="kit-section__actions">
          <button type="button" className="btn-secondary compact" disabled={!events.length} onClick={() => download(`nuvora-audit${filtered ? '-filtered' : ''}.csv`, auditCSV(events), 'text/csv')}>
            <Download size={14} />
            CSV
          </button>
          <button type="button" className="btn-secondary compact" onClick={() => download(`nuvora-audit${filtered ? '-filtered' : ''}.json`, { ...data, filters: applied })}>
            <Download size={14} />
            Export chain
          </button>
        </div>
      }
    >
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="chain-status">
        <ShieldCheck size={22} />
        <b>{data ? (data.verification?.valid ? 'Chain verified' : 'Chain broken') : 'Checking chain…'}</b>
        <span>
          {filtered ? `${events.length} of ${data?.verification?.events || 0} events` : `${data?.verification?.events || 0} events`}
        </span>
      </div>
      <form
        className="filters"
        role="search"
        aria-label="Filter audit events"
        onSubmit={(e) => {
          e.preventDefault();
          setApplied(filters);
        }}
      >
        <label>
          <span>Actor</span>
          <select value={filters.actor} onChange={(e) => set('actor', e.target.value)}>
            <option value="">Anyone</option>
            {actors.map((a) => (
              <option key={a}>{a}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Action</span>
          <select value={filters.action} onChange={(e) => set('action', e.target.value)}>
            <option value="">All actions</option>
            {families.map((a) => (
              <option key={a} value={a}>
                {a}.*
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>From</span>
          <input type="date" value={filters.since} onChange={(e) => set('since', e.target.value)} />
        </label>
        <label>
          <span>To</span>
          <input type="date" value={filters.until} onChange={(e) => set('until', e.target.value)} />
        </label>
        <button type="submit" className="btn-secondary compact">
          Apply
        </button>
        {filtered && (
          <button
            type="button"
            className="link"
            onClick={() => {
              setFilters(EMPTY);
              setApplied(EMPTY);
            }}
          >
            <X size={14} />
            Clear
          </button>
        )}
      </form>
      <TableWrap>
        {events.length ? (
          <table>
            <thead>
              <tr>
                <th>Sequence</th>
                <th>Action</th>
                <th>Actor</th>
                <th>Target</th>
                <th>Time</th>
                <th>Digest</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e: Row) => (
                <tr key={e.seq}>
                  <td>{e.seq}</td>
                  <td>{e.action}</td>
                  <td>{e.actor}</td>
                  <td>
                    <code>{String(e.target ?? '').slice(0, 20)}</code>
                  </td>
                  <td>{time(e.time)}</td>
                  <td>
                    <code>{String(e.digest).slice(0, 16)}…</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <ListEmpty title={filtered ? 'No matching events' : 'No events yet'} description={filtered ? 'Try a wider date range or another actor.' : 'Sessions, changes, runs and decisions appear here.'} />
        )}
      </TableWrap>
      <p className="note">Hash chaining detects changes to exported events. It is not a signature or protection against a host administrator rewriting the entire database. Filtered exports are a view; verify against the full chain.</p>
    </Card>
  );
}
