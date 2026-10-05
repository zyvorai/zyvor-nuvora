// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { useEffect, useState } from 'react';
import { KeyRound, Trash2 } from 'lucide-react';
import { api, type Row } from '../api';
import { Badge, Card, Field, ListEmpty } from '../components/kit';
import type { Act } from '../lib/types';
import { splitGroups } from '../lib/meta';

export default function Users({ principal, act, refresh }: { principal: Row; act: Act; refresh: number }) {
  const [users, setUsers] = useState<Row[]>([]);
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState('developer');
  const [confirm, setConfirm] = useState('');
  const admins = users.filter((u) => u.role === 'admin').length;
  const reload = () =>
    api('/api/users')
      .then((r) => setUsers(r.users))
      .catch(() => {});
  useEffect(() => {
    if (principal.role === 'admin')
      api('/api/users')
        .then((r) => setUsers(r.users))
        .catch(() => {});
  }, [refresh, principal.role]);
  if (principal.role !== 'admin')
    return <ListEmpty icon={KeyRound} title="Administrator access required" description="Ask your workspace administrator to manage users." />;
  return (
    <div className="split">
      <Card title="Workspace members">
        {users.map((u) => {
          const self = u.username === principal.username;
          const lastAdmin = u.role === 'admin' && admins <= 1;
          return (
            <div className="list-row member" key={u.username}>
              <span className="avatar">{u.username[0].toUpperCase()}</span>
              <div>
                <b>
                  {u.username}
                  {self && <span className="muted small"> · you</span>}
                </b>
                {lastAdmin && <small>Last administrator</small>}
                {u.source === 'sso' && <small>SSO · role and groups re-sync from the identity provider at each sign-in</small>}
                {u.source === 'sso' ? (
                  u.groups?.length > 0 && <small>Groups: {u.groups.join(', ')}</small>
                ) : (
                  <input
                    className="inline-input"
                    aria-label={'Groups for ' + u.username}
                    placeholder="Groups for document access, comma-separated"
                    defaultValue={(u.groups || []).join(', ')}
                    onBlur={(e) => {
                      const next = splitGroups(e.target.value);
                      if (next.join(',') !== (u.groups || []).join(',')) act(() => api('/api/users/' + encodeURIComponent(u.username), { groups: next }), `Groups saved for ${u.username}`).then((r) => r && reload());
                    }}
                  />
                )}
              </div>
              {self || lastAdmin ? (
                <Badge value={u.role} />
              ) : (
                <select
                  aria-label={'Role for ' + u.username}
                  value={u.role}
                  onChange={(e) => act(() => api('/api/users/' + encodeURIComponent(u.username), { role: e.target.value }), `${u.username} is now ${e.target.value}`).then((r) => r && reload())}
                >
                  {['viewer', 'developer', 'approver', 'admin'].map((r) => (
                    <option key={r}>{r}</option>
                  ))}
                </select>
              )}
              {!self && !lastAdmin &&
                (confirm === u.username ? (
                  <span className="confirm">
                    <button
                      type="button"
                      className="danger compact"
                      onClick={() =>
                        act(() => api('/api/users/' + encodeURIComponent(u.username), undefined, 'DELETE'), `Removed ${u.username}`).then((r) => {
                          setConfirm('');
                          if (r) reload();
                        })
                      }
                    >
                      Remove
                    </button>
                    <button type="button" className="link" onClick={() => setConfirm('')}>
                      Cancel
                    </button>
                  </span>
                ) : (
                  <button type="button" className="icon" aria-label={'Remove ' + u.username} onClick={() => setConfirm(u.username)}>
                    <Trash2 size={15} />
                  </button>
                ))}
            </div>
          );
        })}
      </Card>
      <Card title="Add a member">
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const r = await act(() => api('/api/users', { username: name, password, role }), `Added ${name}`);
            if (r) {
              setName('');
              setPassword('');
            }
          }}
        >
          <Field label="Username">
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </Field>
          <Field label="Initial password (12+ characters)">
            <input type="password" minLength={12} value={password} onChange={(e) => setPassword(e.target.value)} required />
          </Field>
          <Field label="Role">
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              {['viewer', 'developer', 'approver', 'admin'].map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </Field>
          <button type="submit" className="primary">
            Create member
          </button>
        </form>
        <p className="note">Developers can propose. Approvers can decide. An author can never approve their own proposal. Role changes apply to open sessions immediately. Removing a member ends their sessions and keys.</p>
      </Card>
    </div>
  );
}
