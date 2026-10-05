import { useEffect, useState } from 'react';
import { api, download, money, type Row } from '../api';
import { Card, ListEmpty, TableWrap } from '../components/kit';

export default function Usage({ refresh }: { refresh: number }) {
  const [data, setData] = useState<Row | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    api('/api/usage')
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [refresh]);
  const figures: [string, string | number][] = [
    ['Requests', data?.requests || 0],
    ['Tokens', (data?.tokens || 0).toLocaleString()],
    ['Recorded cost', money(data?.cost)],
    ['Cache hits', data?.cache_hits || 0],
  ];
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
        title="Inference ledger"
        actions={
          <button type="button" className="btn-secondary" onClick={() => download('nuvora-usage.json', data)}>
            Export
          </button>
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
                    <td>{r.model}</td>
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
            <ListEmpty title="No inference yet" description="Ask a question in Playground to record the first request." />
          )}
        </TableWrap>
        <p className="note">Costs use operator-configured rates. This ledger is an estimate, not a provider invoice. Embedding usage is not yet included.</p>
      </Card>
    </div>
  );
}
