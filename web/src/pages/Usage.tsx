// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { useEffect, useState } from 'react';
import { Download } from 'lucide-react';
import { api, download, money, type Row } from '../api';
import { AreaChart, BarList, Donut, Gauge, type Series } from '../components/charts';
import { Card, ListEmpty, Skeleton, TableWrap } from '../components/kit';

type Metric = 'requests' | 'tokens' | 'cost' | 'latency_ms';

const METRICS: [Metric, string][] = [
  ['requests', 'Requests'],
  ['tokens', 'Tokens'],
  ['cost', 'Cost'],
  ['latency_ms', 'Latency'],
];

const fmt: Record<Metric, (v: number) => string> = {
  requests: (v) => v.toLocaleString(),
  tokens: (v) => v.toLocaleString(),
  cost: (v) => money(v),
  latency_ms: (v) => `${Math.round(v)} ms`,
};

function csv(records: Row[]): string {
  const cols = ['created', 'model', 'input_tokens', 'output_tokens', 'latency_ms', 'cost', 'cached'];
  const esc = (v: unknown) => {
    const s = String(v ?? '');
    return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
  };
  return [cols.join(','), ...records.map((r) => cols.map((c) => esc(c === 'created' ? new Date(r.created * 1000).toISOString() : r[c])).join(','))].join('\n');
}

export default function Usage({ refresh }: { refresh: number }) {
  const [data, setData] = useState<Row | null>(null);
  const [series, setSeries] = useState<Row | null>(null);
  const [days, setDays] = useState(14);
  const [metric, setMetric] = useState<Metric>('requests');
  const [error, setError] = useState('');
  useEffect(() => {
    api('/api/usage')
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [refresh]);
  useEffect(() => {
    api('/api/usage/series?days=' + days)
      .then(setSeries)
      .catch((e) => setError(String(e)));
  }, [days, refresh]);

  const figures: [string, string | number][] = [
    ['Requests', data?.requests || 0],
    ['Tokens', (data?.tokens || 0).toLocaleString()],
    ['Recorded cost', money(data?.cost)],
    ['Cache hits', data?.cache_hits || 0],
  ];
  const daysRows: Row[] = series?.days || [];
  const labels = daysRows.map((d) => new Date(d.date + 'T00:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' }));
  const chartSeries: Series[] = [{ label: METRICS.find((m) => m[0] === metric)![1], values: daysRows.map((d) => d[metric] || 0), tone: 'blue' }];
  if (metric === 'requests') chartSeries.push({ label: 'Cache hits', values: daysRows.map((d) => d.cache_hits || 0), tone: 'green' });
  const models: Row[] = series?.models || [];
  const requests = data?.requests || 0;
  const hits = data?.cache_hits || 0;
  const budget = series?.budget;

  return (
    <div className="stack-page">
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="apple-metric-band">
        {figures.map(([k, v]) => (
          <div key={k}>
            <span>{k}</span>
            <b>{v}</b>
          </div>
        ))}
      </div>

      <Card
        title="Activity"
        actions={
          <div className="chart-controls">
            <div className="tabs" role="tablist" aria-label="Metric">
              {METRICS.map(([id, label]) => (
                <button key={id} type="button" role="tab" aria-selected={metric === id} onClick={() => setMetric(id)}>
                  {label}
                </button>
              ))}
            </div>
            <select aria-label="Time range" value={days} onChange={(e) => setDays(Number(e.target.value))}>
              <option value={7}>7 days</option>
              <option value={14}>14 days</option>
              <option value={30}>30 days</option>
              <option value={90}>90 days</option>
            </select>
          </div>
        }
      >
        {series ? <AreaChart labels={labels} series={chartSeries} format={fmt[metric]} title={`${chartSeries[0].label} per day, last ${days} days`} /> : <Skeleton rows={5} label="Loading activity" />}
      </Card>

      <div className="grid usage-grid">
        <Card title="By model" eyebrow={`Last ${days} days`}>
          {models.length ? (
            <BarList items={models.map((m) => ({ label: m.name || m.model, value: metric === 'latency_ms' ? m.latency_ms : m[metric] || 0 }))} format={fmt[metric]} />
          ) : (
            <ListEmpty title="No model traffic" description="Requests appear here per model." />
          )}
        </Card>
        <Card title="Cache">
          <Donut
            label={`${hits} of ${requests} requests served from cache`}
            parts={[
              { label: 'Cache', value: hits, tone: 'green' },
              { label: 'Provider', value: Math.max(0, requests - hits), tone: 'blue' },
            ]}
          />
        </Card>
        <Card title="Daily token budget">
          {budget ? (
            <>
              <p className="budget-figure">
                <b>{(budget.used_24h || 0).toLocaleString()}</b> / {(budget.limit || 0).toLocaleString()} tokens
              </p>
              <Gauge value={budget.used_24h || 0} max={budget.limit || 0} label="the 24-hour guardrail budget" />
              <p className="note">Requests beyond the budget are refused until usage falls out of the rolling 24-hour window.</p>
            </>
          ) : (
            <Skeleton rows={2} label="Loading budget" />
          )}
        </Card>
      </div>

      <Card
        title="Inference ledger"
        actions={
          <div className="kit-section__actions">
            <button type="button" className="btn-secondary compact" disabled={!data?.records?.length} onClick={() => download('nuvora-usage.csv', csv(data?.records || []), 'text/csv')}>
              <Download size={14} />
              CSV
            </button>
            <button type="button" className="btn-secondary compact" onClick={() => download('nuvora-usage.json', data)}>
              <Download size={14} />
              JSON
            </button>
          </div>
        }
      >
        <TableWrap>
          {data?.records?.length ? (
            <table>
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Tokens in / out</th>
                  <th>Latency</th>
                  <th>Cost</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {data.records.map((r: Row) => (
                  <tr key={r.id}>
                    <td>{models.find((m) => m.model === r.model)?.name || r.model}</td>
                    <td>
                      {r.input_tokens} / {r.output_tokens}
                    </td>
                    <td>{Number(r.latency_ms).toFixed(0)} ms</td>
                    <td>{money(r.cost)}</td>
                    <td>{r.cached ? 'Cache' : 'Provider'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <ListEmpty
              title="No inference yet"
              description="Ask a question in Playground to record the first request."
              action={
                <a className="buttonlike primary" href="#playground">
                  Open playground
                </a>
              }
            />
          )}
        </TableWrap>
        <p className="note">Costs use operator-configured rates. This ledger is an estimate, not a provider invoice. Embedding usage is not yet included.</p>
      </Card>
    </div>
  );
}
