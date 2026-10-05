import { useEffect, useRef, useState, type FormEvent, type ReactNode, type RefObject } from 'react';
import { Bell, Check, KeyRound, Keyboard, LogOut, Settings, ShieldCheck } from 'lucide-react';
import { ago, api, type Row } from '../api';
import { passwordStrength, type Note } from '../lib/notifications';
import { Field } from './kit';

function useDismiss(ref: RefObject<HTMLElement | null>, open: boolean, close: () => void) {
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [ref, open, close]);
}

export function NotificationBell({ notes, seenKey }: { notes: Note[]; seenKey: string }) {
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState(() => Number(localStorage.getItem(seenKey) || 0));
  const [highlight, setHighlight] = useState(seen);
  const ref = useRef<HTMLDivElement>(null);
  const close = () => setOpen(false);
  useDismiss(ref, open, close);
  const unread = notes.filter((n) => n.time > seen).length;
  const toggle = () => {
    if (!open) {
      const now = Date.now() / 1000;
      setHighlight(seen);
      setSeen(now);
      try {
        localStorage.setItem(seenKey, String(now));
      } catch {
        /* ignore */
      }
    }
    setOpen((o) => !o);
  };
  return (
    <div className="menu-anchor" ref={ref}>
      <button type="button" className="theme-toggle bell" aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'} aria-expanded={open} onClick={toggle}>
        <Bell size={16} strokeWidth={1.75} />
        {unread > 0 && <span className="bell__count">{unread > 9 ? '9+' : unread}</span>}
      </button>
      {open && (
        <div className="menu notifications" role="dialog" aria-label="Notifications">
          <header>
            <b>Notifications</b>
            <span className="small muted">{notes.length ? `${notes.length} recent` : ''}</span>
          </header>
          {notes.length ? (
            <ul>
              {notes.map((n) => (
                <li key={n.id} className={n.time > highlight ? 'unread' : ''}>
                  <a href={n.href} onClick={close}>
                    <i className={'note-dot ' + n.tone} aria-hidden="true" />
                    <span>
                      <b>{n.title}</b>
                      <small>
                        {n.detail} · {ago(n.time)}
                      </small>
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="menu__empty">
              <Check size={16} aria-hidden="true" /> You’re all caught up.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function ProfileMenu({
  principal,
  onPassword,
  onShortcuts,
  onLogout,
}: {
  principal: Row;
  onPassword: () => void;
  onShortcuts: () => void;
  onLogout: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const close = () => setOpen(false);
  useDismiss(ref, open, close);
  const item = (icon: ReactNode, label: string, run: () => void) => (
    <button
      type="button"
      role="menuitem"
      onClick={() => {
        close();
        run();
      }}
    >
      {icon}
      {label}
    </button>
  );
  return (
    <div className="menu-anchor" ref={ref}>
      <button type="button" className="workspace-chip profile-trigger" aria-haspopup="menu" aria-expanded={open} aria-label={`Account: ${principal.username}`} onClick={() => setOpen((o) => !o)}>
        <span className="avatar sm" aria-hidden="true">
          {String(principal.username || '?')[0].toUpperCase()}
        </span>
        {principal.tenant} · {principal.role}
      </button>
      {open && (
        <div className="menu profile" role="menu" aria-label="Account">
          <header>
            <span className="avatar" aria-hidden="true">
              {String(principal.username || '?')[0].toUpperCase()}
            </span>
            <span>
              <b>{principal.username}</b>
              <small>
                {principal.role} in {principal.tenant}
              </small>
            </span>
          </header>
          {item(<ShieldCheck size={15} />, 'Change password', onPassword)}
          {item(<KeyRound size={15} />, 'API keys', () => (window.location.hash = 'keys'))}
          {item(<Settings size={15} />, 'Settings', () => (window.location.hash = 'settings'))}
          {item(<Keyboard size={15} />, 'Keyboard shortcuts', onShortcuts)}
          <hr />
          {item(<LogOut size={15} />, 'Log out', onLogout)}
        </div>
      )}
    </div>
  );
}

export function ChangePassword({ done }: { done: () => void }) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const strength = passwordStrength(next);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError('');
    if (next.length < 12) return setError('Use at least 12 characters.');
    if (next !== confirm) return setError('The new passwords do not match.');
    setBusy(true);
    try {
      await api('/api/password', { current, new: next });
      done();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="password-form">
      <Field label="Current password">
        <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
      </Field>
      <Field label="New password">
        <input type="password" autoComplete="new-password" minLength={12} maxLength={256} value={next} onChange={(e) => setNext(e.target.value)} required />
      </Field>
      {next && (
        <div className={'strength s' + strength.score} aria-live="polite">
          <span className="strength__bar">
            <i />
          </span>
          <small>{strength.label}</small>
        </div>
      )}
      <Field label="Confirm new password">
        <input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
      </Field>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <p className="note">Changing your password signs out your other sessions. This session stays signed in.</p>
      <div className="actions">
        <button type="submit" className="primary" disabled={busy}>
          {busy ? 'Saving…' : 'Change password'}
        </button>
      </div>
    </form>
  );
}
