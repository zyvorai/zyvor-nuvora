import { useEffect, useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { api, download, time, type Row } from '../api';
import { Card, TableWrap } from '../components/kit';

export default function Audit({ refresh }: { refresh: number }) {
  const [data, setData] = useState<Row | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    api('/api/audit')
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [refresh]);
  return (
    <Card
      title="Audit evidence"
      actions={
        <button type="button" className="btn-secondary" onClick={() => download('nuvora-audit.json', data)}>
          Export chain
        </button>
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
        <span>{data?.verification?.events || 0} events</span>
      </div>
      <TableWrap>
        <table>
          <thead>
            <tr>
              <th>Sequence</th>
              <th>Action</th>
              <th>Actor</th>
              <th>Time</th>
              <th>Digest</th>
            </tr>
          </thead>
          <tbody>
            {data?.events
              ?.slice()
              .reverse()
              .map((e: Row) => (
                <tr key={e.seq}>
                  <td>{e.seq}</td>
                  <td>{e.action}</td>
                  <td>{e.actor}</td>
                  <td>{time(e.time)}</td>
                  <td>
                    <code>{String(e.digest).slice(0, 16)}…</code>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </TableWrap>
      <p className="note">Hash chaining detects changes to exported events. It is not a signature or protection against a host administrator rewriting the entire database.</p>
    </Card>
  );
}
