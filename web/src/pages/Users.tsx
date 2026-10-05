import { useEffect, useState } from 'react';
import { KeyRound } from 'lucide-react';
import { api, type Row } from '../api';
import { Badge, Card, Field, ListEmpty } from '../components/kit';
import type { Act } from '../lib/types';

export default function Users({ principal, act, refresh }: { principal: Row; act: Act; refresh: number }) {
  const [users, setUsers] = useState<Row[]>([]);
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState('developer');
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
        {users.map((u) => (
          <div className="list-row" key={u.username}>
            <span className="avatar">{u.username[0].toUpperCase()}</span>
            <div>
              <b>{u.username}</b>
            </div>
            <Badge value={u.role} />
          </div>
        ))}
      </Card>
      <Card title="Add a member">
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const r = await act(() => api('/api/users', { username: name, password, role }));
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
        <p className="note">Developers can propose. Approvers can decide. An author can never approve their own proposal.</p>
      </Card>
    </div>
  );
}
