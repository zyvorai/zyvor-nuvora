// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { ShieldCheck } from 'lucide-react';
import { api, time, type Row } from '../api';
import { Badge, Card, ListEmpty } from '../components/kit';
import type { Act } from '../lib/types';

export default function Approvals({ rows, principal, canApprove, act }: { rows: Row[]; principal: Row; canApprove: boolean; act: Act }) {
  const decide = (a: Row, decision: 'approved' | 'rejected') => act(() => api('/api/approvals/' + a.id + '/decide', { decision, digest: a.digest }));
  return (
    <Card title="Human decisions">
      {rows.length ? (
        rows.map((a) => {
          const own = a.proposer === principal.username;
          return (
            <div className="approval" key={a.id}>
              <div className="kit-section__head">
                <div>
                  <h3>{a.name}</h3>
                  <span className="muted">
                    Proposed by {a.proposer} · Expires {time(a.expires)}
                  </span>
                </div>
                <Badge value={a.status} />
              </div>
              <pre>{JSON.stringify(a.action, null, 2)}</pre>
              <p className="small muted">
                Action fingerprint: <code>{a.digest}</code>
              </p>
              {a.status === 'pending' && (
                <div className="actions">
                  <button type="button" className="primary" disabled={!canApprove || own} onClick={() => decide(a, 'approved')}>
                    Approve exact action
                  </button>
                  <button type="button" className="btn-secondary" disabled={!canApprove || own} onClick={() => decide(a, 'rejected')}>
                    Reject
                  </button>
                  {own && <small className="muted">A different person must decide.</small>}
                </div>
              )}
            </div>
          );
        })
      ) : (
        <ListEmpty icon={ShieldCheck} title="No decisions waiting" description="Workflow review steps, memory writes and external actions appear here."
          action={
            <a className="buttonlike btn-secondary" href="#workflows">
              Start a reviewed workflow
            </a>
          }
        />
      )}
    </Card>
  );
}
