import { useEffect, type ReactNode } from 'react';
import { X, type LucideIcon } from 'lucide-react';

// Browse- and work-tier primitives (docs/design/APPLE-UX-CONTRACT.md). Styling lives in
// styles/apple-story.css and styles/nuvora.css.

type ToolbarProps = {
  search?: string;
  onSearchChange?: (value: string) => void;
  placeholder?: string;
  searchLabel?: string;
  trailing?: ReactNode;
};

export function Toolbar({ search, onSearchChange, placeholder = 'Search', searchLabel, trailing }: ToolbarProps) {
  return (
    <div className="toolbar-pill" role="search">
      {onSearchChange && (
        <input
          className="input-field"
          type="search"
          value={search ?? ''}
          placeholder={placeholder}
          aria-label={searchLabel ?? placeholder}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      )}
      {trailing && <div className="toolbar-pill__trailing">{trailing}</div>}
    </div>
  );
}

export function TableWrap({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={className ? `table-wrap ${className}` : 'table-wrap'}>{children}</div>;
}

type ListEmptyProps = { title: string; description?: ReactNode; action?: ReactNode; secondary?: ReactNode; icon?: LucideIcon };

export function ListEmpty({ title, description, action, secondary, icon: Icon }: ListEmptyProps) {
  return (
    <div className="list-empty">
      {Icon && (
        <span className="list-empty__icon" aria-hidden="true">
          <Icon size={20} strokeWidth={1.75} />
        </span>
      )}
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {(action || secondary) && (
        <div className="list-empty__actions">
          {action}
          {secondary}
        </div>
      )}
    </div>
  );
}

export function Skeleton({ rows = 3, label = 'Loading' }: { rows?: number; label?: string }) {
  return (
    <div className="skeleton-stack" role="status" aria-label={label}>
      {Array.from({ length: rows }, (_, i) => (
        <span key={i} className="skeleton" style={{ width: `${92 - ((i * 17) % 35)}%` }} />
      ))}
    </div>
  );
}

type CardProps = {
  title?: string;
  eyebrow?: string;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
};

export function Card({ title, eyebrow, actions, children, className }: CardProps) {
  return (
    <section className={['card', className].filter(Boolean).join(' ')}>
      {(title || eyebrow || actions) && (
        <header className="kit-section__head">
          <div>
            {eyebrow && <p className="kit-eyebrow">{eyebrow}</p>}
            {title && <h2 className="card-title">{title}</h2>}
          </div>
          {actions && <div className="kit-section__actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

const GOOD = new Set(['completed', 'approved', 'verified', 'enabled', 'passed', 'running']);
const BAD = new Set(['failed', 'rejected', 'unverified', 'expired', 'stopped']);
const WARN = new Set(['pending', 'waiting', 'waiting_approval', 'synthetic', 'needs_review']);

export function Badge({ value }: { value: string }) {
  const v = String(value ?? '');
  const tone = GOOD.has(v) ? ' good' : BAD.has(v) ? ' bad' : WARN.has(v) ? ' warn' : '';
  return <span className={'badge' + tone}>{v.replaceAll('_', ' ')}</span>;
}

export function Modal({ title, children, close }: { title: string; children: ReactNode; close: () => void }) {
  useEffect(() => {
    const cb = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    window.addEventListener('keydown', cb);
    return () => window.removeEventListener('keydown', cb);
  }, [close]);
  return (
    <div className="modal-backdrop" onClick={close}>
      <section className="modal" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <header className="kit-section__head">
          <h2>{title}</h2>
          <button type="button" className="icon" aria-label="Close dialog" onClick={close}>
            <X size={18} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
