import { useState, type FormEvent } from 'react';
import { api, setCSRF, type Row } from '../api';

const WRONG = 'Wrong username or password.';

function message(e: unknown): string {
  const text = e instanceof Error ? e.message : String(e);
  if (/wrong tenant|sign in required/i.test(text)) return WRONG;
  if (/failed to fetch|networkerror|unexpected token/i.test(text)) return 'Could not reach the workspace. Check the URL and try again.';
  return text;
}

export default function Login({ onLogin }: { onLogin: (principal: Row) => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [tenant, setTenant] = useState('default');
  const [showTenant, setShowTenant] = useState(false);
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
    try {
      const r = await api('/api/login', { tenant: tenant.trim() || 'default', username: user, password });
      setCSRF(r.csrf);
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

  return (
    <div className="login-shell">
      <div className="login-info">
        <img src="/zyvor-mark.svg" alt="Zyvor" className="login-logo" />
        <p className="eyebrow">Nuvora · Zyvor</p>
        <h1>Your models. Your knowledge. Your control.</h1>
        <p>
          Nuvora is a private AI workspace: connect your own model endpoints, ground answers in your documents, run
          tool-using agents, and keep every consequential action behind a human approval.
        </p>
        <p className="login-host">
          Connecting to <code>{host}</code>
        </p>
      </div>
      <form className="card login-card" onSubmit={submit} noValidate>
        <h1>Sign in.</h1>
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
            autoFocus
            autoComplete="username"
            disabled={busy}
            aria-invalid={Boolean(error)}
          />
        </label>
        <label className="tokenbox">
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              clear();
            }}
            autoComplete="current-password"
            disabled={busy}
            aria-invalid={Boolean(error)}
          />
        </label>
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
    </div>
  );
}
