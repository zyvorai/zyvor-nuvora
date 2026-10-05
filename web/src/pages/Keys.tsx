import { useEffect, useState, type FormEvent } from 'react';
import { Copy, KeyRound, Plus, Trash2 } from 'lucide-react';
import { ago, api, time, type Row } from '../api';
import { Badge, Card, Field, ListEmpty, Skeleton, TableWrap } from '../components/kit';
import { useToast } from '../components/Toasts';
import type { Act } from '../lib/types';

const LIFETIMES: [number, string][] = [
  [3600, '1 hour'],
  [86400, '1 day'],
  [86400 * 7, '7 days'],
  [86400 * 30, '30 days'],
];

export default function Keys({ principal, act, refresh }: { principal: Row; act: Act; refresh: number }) {
  const toast = useToast();
  const [tokens, setTokens] = useState<Row[] | null>(null);
  const [label, setLabel] = useState('');
  const [role, setRole] = useState('viewer');
  const [lifetime, setLifetime] = useState(86400);
  const [created, setCreated] = useState<Row | null>(null);
  const [confirm, setConfirm] = useState('');
  const canIssue = principal.role === 'admin' || principal.role === 'developer';

  useEffect(() => {
    api('/api/tokens')
      .then((r) => setTokens(r.tokens))
      .catch(() => setTokens([]));
  }, [refresh, created]);

  async function issue(e: FormEvent) {
    e.preventDefault();
    const r = await act(() => api('/api/tokens', { label, role, lifetime }), 'API key created');
    if (r) {
      setCreated(r);
      setLabel('');
    }
  }

  async function revoke(id: string) {
    const r = await act(() => api('/api/tokens/' + id, undefined, 'DELETE'), 'API key revoked');
    if (r) {
      setConfirm('');
      setTokens((t) => (t || []).filter((x) => x.id !== id));
    }
  }

  return (
    <div className="split keys">
      <Card title="Active keys" eyebrow={principal.role === 'admin' ? 'Everyone in this workspace' : 'Keys you created'}>
        {!tokens ? (
          <Skeleton rows={3} label="Loading keys" />
        ) : tokens.length ? (
          <TableWrap>
            <table>
              <thead>
                <tr>
                  <th>Label</th>
                  <th>Role</th>
                  {principal.role === 'admin' && <th>Owner</th>}
                  <th>Expires</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {tokens.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <b>{t.label || 'Untitled key'}</b>
                      <br />
                      <small className="muted">
                        <code>{t.id}</code> · created {ago(t.created)}
                      </small>
                    </td>
                    <td>
                      <Badge value={t.role} />
                    </td>
                    {principal.role === 'admin' && <td>{t.username}</td>}
                    <td title={time(t.expires)}>{time(t.expires)}</td>
                    <td>
                      {confirm === t.id ? (
                        <span className="confirm">
                          <button type="button" className="danger compact" onClick={() => revoke(t.id)}>
                            Revoke
                          </button>
                          <button type="button" className="link" onClick={() => setConfirm('')}>
                            Cancel
                          </button>
                        </span>
                      ) : (
                        <button type="button" className="btn-secondary compact danger-text" onClick={() => setConfirm(t.id)} aria-label={'Revoke ' + (t.label || t.id)}>
                          <Trash2 size={14} />
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        ) : (
          <ListEmpty icon={KeyRound} title="No active API keys" description="Create a scoped key for scripts, CI or the OpenAI-compatible endpoint." />
        )}
      </Card>
      <Card title="Create a key">
        {created && (
          <div className="secret-once" role="status">
            <b>Copy this key now. It is shown only once.</b>
            <code>{created.token}</code>
            <span className="secret-once__actions">
              <button
                type="button"
                className="btn-secondary compact"
                onClick={() =>
                  navigator.clipboard
                    .writeText(created.token)
                    .then(() => toast('Key copied'))
                    .catch(() => toast('Copy is unavailable in this browser', 'error'))
                }
              >
                <Copy size={14} />
                Copy key
              </button>
              <button type="button" className="link" onClick={() => setCreated(null)}>
                I saved it
              </button>
            </span>
          </div>
        )}
        {canIssue ? (
          <form onSubmit={issue}>
            <Field label="Label">
              <input value={label} maxLength={80} placeholder="CI pipeline" onChange={(e) => setLabel(e.target.value)} required />
            </Field>
            <div className="form-grid">
              <Field label="Key role">
                <select value={role} onChange={(e) => setRole(e.target.value)}>
                  <option value="viewer">viewer · read only</option>
                  <option value="developer">developer · can propose</option>
                </select>
              </Field>
              <Field label="Expires after">
                <select value={lifetime} onChange={(e) => setLifetime(Number(e.target.value))}>
                  {LIFETIMES.map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <button type="submit" className="primary">
              <Plus size={16} />
              Create key
            </button>
          </form>
        ) : (
          <p className="muted">Viewers and approvers cannot issue keys. Ask a developer or administrator.</p>
        )}
        <p className="note">
          Use a key as <code>Authorization: Bearer …</code> against <code>/api</code> or <code>/v1/chat/completions</code>. Keys can view or propose, never approve or administer.
        </p>
      </Card>
    </div>
  );
}
