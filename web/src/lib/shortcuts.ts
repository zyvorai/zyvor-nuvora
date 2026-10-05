import { pageLabel, type Page } from './navGroups';

// "g" then a letter navigates; single keys open palette, create and help.
export const goKeys: Record<string, Page> = {
  o: 'overview',
  p: 'playground',
  m: 'models',
  k: 'knowledge',
  a: 'agents',
  w: 'workflows',
  r: 'jobs',
  e: 'evaluations',
  v: 'approvals',
  u: 'usage',
  d: 'audit',
  s: 'settings',
};

export const shortcutHelp: [string, string][] = [
  ['⌘K  or  /', 'Open the command palette'],
  ['c', 'Create on the current page'],
  ['?', 'Show keyboard shortcuts'],
  ['Esc', 'Close a dialog or drawer'],
  ...Object.entries(goKeys).map(([k, page]) => [`g ${k}`, `Go to ${pageLabel(page)}`] as [string, string]),
];

export type ShortcutHandlers = {
  palette: () => void;
  create: () => void;
  help: () => void;
  go: (page: Page) => void;
};

function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
}

// Returns a keydown handler holding the pending "g" prefix state.
export function shortcutHandler(h: ShortcutHandlers): (e: KeyboardEvent) => void {
  let pendingG = 0;
  return (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      h.palette();
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return;
    if (document.querySelector('[aria-modal="true"]')) return;
    const now = Date.now();
    if (pendingG && now - pendingG < 1200) {
      pendingG = 0;
      const page = goKeys[e.key.toLowerCase()];
      if (page) {
        e.preventDefault();
        h.go(page);
      }
      return;
    }
    if (e.key === 'g') pendingG = now;
    else if (e.key === '/') {
      e.preventDefault();
      h.palette();
    } else if (e.key === '?') h.help();
    else if (e.key === 'c') h.create();
  };
}
