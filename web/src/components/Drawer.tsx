// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { useEffect, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

export default function Drawer({
  title,
  eyebrow,
  actions,
  children,
  close,
}: {
  title: string;
  eyebrow?: string;
  actions?: ReactNode;
  children: ReactNode;
  close: () => void;
}) {
  const panel = useRef<HTMLElement>(null);
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    const onKey = (e: KeyboardEvent) => {
      const dialogs = document.querySelectorAll('[aria-modal="true"]');
      if (dialogs[dialogs.length - 1] !== panel.current) return;
      if (e.key === 'Escape') {
        e.stopPropagation();
        closeRef.current();
      }
      if (e.key !== 'Tab' || !panel.current) return;
      const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      opener?.focus?.();
    };
  }, []);
  return (
    <div className="drawer-backdrop" onClick={close}>
      <aside ref={panel} className="drawer" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <header className="drawer__head">
          <div>
            {eyebrow && <p className="kit-eyebrow">{eyebrow}</p>}
            <h2>{title}</h2>
          </div>
          <div className="kit-section__actions">
            {actions}
            <button type="button" className="icon" aria-label="Close panel" onClick={close}>
              <X size={18} />
            </button>
          </div>
        </header>
        <div className="drawer__body">{children}</div>
      </aside>
    </div>
  );
}
