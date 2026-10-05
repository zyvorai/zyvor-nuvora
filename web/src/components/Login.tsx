import { useState, type FormEvent, type KeyboardEvent } from 'react';
import { BookOpenCheck, Cpu, Eye, EyeOff, Fingerprint, ShieldCheck, UserCheck, Workflow } from 'lucide-react';
import { api, setCSRF, type Row } from '../api';

const WRONG = 'Wrong username or password.';
const REMEMBER = 'nuvora-login';

function message(e: unknown): string {
  const text = e instanceof Error ? e.message : String(e);
  const status = (e as { status?: number })?.status;
  if (status === 429 || /too many/i.test(text)) return 'Too many attempts. Wait five minutes, then try again.';
  if (/wrong tenant|sign in required/i.test(text)) return WRONG;
  if (/failed to fetch|networkerror|unexpected token|load failed/i.test(text)) return 'Could not reach the workspace. Check the URL and try again.';
  return text;
}

function remembered(): { tenant: string; username: string } {
  try {
    const v = JSON.parse(localStorage.getItem(REMEMBER) || '{}');
    return { tenant: typeof v.tenant === 'string' && v.tenant ? v.tenant : 'default', username: typeof v.username === 'string' ? v.username : '' };
  } catch {
    return { tenant: 'default', username: '' };
  }
}

const CHAIN = [
  { icon: Cpu, label: 'Model', hash: 'a3f1' },
  { icon: BookOpenCheck, label: 'Knowledge', hash: '9c0e' },
  { icon: Workflow, label: 'Agent', hash: '51bd' },
  { icon: UserCheck, label: 'Approval', hash: 'e72a' },
  { icon: Fingerprint, label: 'Evidence', hash: '0d4c' },
];

function EvidenceChain() {
  return (
    <ol className="login-chain" aria-label="Every answer and action is chained to its evidence">
      {CHAIN.map(({ icon: Icon, label, hash }, i) => (
        <li key={label} style={{ animationDelay: `${i * 0.6}s` }}>
          <span className="login-chain__node">
            <Icon size={18} strokeWidth={1.75} aria-hidden="true" />
          </span>
          <b>{label}</b>
          <code>sha256:{hash}…</code>
        </li>
      ))}
    </ol>
  );
}

export default function Login({ onLogin }: { onLogin: (principal: Row) => void }) {
  const initial = remembered();
  const [username, setUsername] = useState(initial.username);
  const [password, setPassword] = useState('');
  const [tenant, setTenant] = useState(initial.tenant);
  const [showTenant, setShowTenant] = useState(false);
  const [reveal, setReveal] = useState(false);
  const [caps, setCaps] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const host = window.location.host || window.location.hostname;

  async function submit(e: FormEvent) {
    e.preventDefault();
    const user = username.trim();
    if (!user || !password) {
      setError(WRONG);
      return;
    }
    setBusy(true);
    setError('');
    const space = tenant.trim() || 'default';
    try {
      const r = await api('/api/login', { tenant: space, username: user, password });
      setCSRF(r.csrf);
      try {
        localStorage.setItem(REMEMBER, JSON.stringify({ tenant: space, username: user }));
      } catch {
        /* storage may be unavailable */
      }
      onLogin(r.principal);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  const clear = () => {
    if (error) setError('');
  };
  const capsCheck = (e: KeyboardEvent<HTMLInputElement>) => setCaps(e.getModifierState?.('CapsLock') ?? false);

  return (
    <div className="login-split">
      <aside className="login-hero">
        <div className="login-hero__inner">
          <img src="/zyvor-mark.svg" alt="Zyvor" className="login-logo" />
          <p className="eyebrow">Nuvora · Zyvor</p>
          <h1>
            Your models. Your knowledge. <em>Your control.</em>
          </h1>
          <p className="login-hero__lede">
            A private AI workspace: connect your own model endpoints, ground answers in your documents, run tool-using
            agents, and keep every consequential action behind a human approval.
          </p>
          <EvidenceChain />
          <ul className="login-proof">
            <li>
              <BookOpenCheck size={15} aria-hidden="true" /> Cited answers
            </li>
            <li>
              <UserCheck size={15} aria-hidden="true" /> Author ≠ approver
            </li>
            <li>
              <ShieldCheck size={15} aria-hidden="true" /> Hash-chained evidence
            </li>
          </ul>
        </div>
      </aside>
      <section className="login-pane">
        <form className="card login-card" onSubmit={submit} noValidate>
          <h1>Sign in.</h1>
          <p className="login-host">
            Connecting to <code>{host}</code>
          </p>
          {showTenant && (
            <label className="tokenbox">
              Workspace
              <input
                value={tenant}
                onChange={(e) => {
                  setTenant(e.target.value);
                  clear();
                }}
                autoComplete="organization"
                disabled={busy}
              />
            </label>
          )}
          <label className="tokenbox">
            Username
            <input
              value={username}
              onChange={(e) => {
                setUsername(e.target.value);
                clear();
              }}
              autoFocus={!initial.username}
              autoComplete="username"
              disabled={busy}
              aria-invalid={Boolean(error)}
            />
          </label>
          <label className="tokenbox">
            Password
            <span className="password-field">
              <input
                type={reveal ? 'text' : 'password'}
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  clear();
                }}
                onKeyUp={capsCheck}
                onKeyDown={capsCheck}
                autoFocus={Boolean(initial.username)}
                autoComplete="current-password"
                disabled={busy}
                aria-invalid={Boolean(error)}
              />
              <button
                type="button"
                className="icon password-toggle"
                aria-label={reveal ? 'Hide password' : 'Show password'}
                aria-pressed={reveal}
                onClick={() => setReveal((v) => !v)}
              >
                {reveal ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </span>
          </label>
          {caps && <p className="login-caps">Caps Lock is on.</p>}
          {error ? (
            <p className="login-error" role="alert" aria-live="assertive">
              {error}
            </p>
          ) : null}
          <button type="submit" className="primary" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
          {!showTenant && (
            <button type="button" className="login-workspace" onClick={() => setShowTenant(true)}>
              Workspace: <b>{tenant}</b> · Change
            </button>
          )}
        </form>
        <p className="login-foot">Private by deployment. Accountable by design.</p>
      </section>
    </div>
  );
}
