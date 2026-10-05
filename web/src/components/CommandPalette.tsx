// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { ArrowRight, CornerDownLeft, FileText, Keyboard, LogOut, MoonStar, Plus, Search, Sparkles, X } from 'lucide-react';
import type { Row } from '../api';
import { fuzzyFilter } from '../lib/fuzzy';
import { navGroups, pageGroup, type Page } from '../lib/navGroups';
import { shortcutHelp } from '../lib/shortcuts';
import type { Collections } from '../lib/types';

export type Command = { id: string; group: string; label: string; hint?: string; icon?: ReactNode; keywords?: string; run: () => void };

const RESOURCE_KINDS: [string, string][] = [
  ['models', 'Model'],
  ['routers', 'Router'],
  ['knowledge', 'Knowledge base'],
  ['agents', 'Agent'],
  ['actions', 'Action'],
  ['mcp_servers', 'MCP server'],
  ['connectors', 'Connector'],
  ['workflows', 'Workflow'],
  ['prompts', 'Prompt'],
  ['policies', 'Guardrail'],
  ['evaluations', 'Evaluation'],
  ['recipes', 'Recipe'],
  ['jobs', 'Run'],
  ['approvals', 'Approval'],
];

const resourceName = (kind: string, r: Row) =>
  kind === 'jobs' ? `${r.type} run · ${r.status}` : kind === 'approvals' ? `${r.action || r.kind || 'Approval'} · ${r.status}` : r.name || r.id;

export function buildCommands({
  collections,
  navigate,
  open,
  create,
  ask,
  extra,
}: {
  collections: Collections;
  navigate: (p: Page) => void;
  open: (kind: string, id: string) => void;
  create: { page: Page; label: string; run: () => void }[];
  ask: (text: string) => void;
  extra: Command[];
}): { base: Command[]; ask: (q: string) => Command } {
  const pages: Command[] = navGroups.flatMap((g) =>
    g.children
      ? g.children.map((c) => ({ id: 'page:' + c.page, group: 'Pages', label: c.label, hint: g.label, keywords: c.blurb, icon: <ArrowRight size={15} />, run: () => navigate(c.page) }))
      : [{ id: 'page:' + g.page, group: 'Pages', label: g.label, icon: <ArrowRight size={15} />, run: () => navigate(g.page as Page) }],
  );
  const actions: Command[] = [
    ...create.map((c) => ({ id: 'create:' + c.page, group: 'Actions', label: 'Create ' + c.label, hint: pageGroup(c.page), icon: <Plus size={15} />, run: c.run })),
    ...extra,
  ];
  const resources: Command[] = RESOURCE_KINDS.flatMap(([kind, label]) =>
    (collections[kind] || []).slice(0, 200).map((r) => ({
      id: kind + ':' + r.id,
      group: 'Resources',
      label: resourceName(kind, r),
      hint: label,
      keywords: [r.id, r.description, r.provider, r.model].filter(Boolean).join(' '),
      icon: <FileText size={15} />,
      run: () => open(kind, r.id),
    })),
  );
  return {
    base: [...pages, ...actions, ...resources],
    ask: (q) => ({ id: 'ask', group: 'Ask', label: `Ask: “${q}”`, hint: 'Playground', icon: <Sparkles size={15} />, run: () => ask(q) }),
  };
}

export default function CommandPalette({ commands, ask, close }: { commands: Command[]; ask: (q: string) => Command; close: () => void }) {
  const [query, setQuery] = useState('');
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);

  const results = useMemo(() => {
    const q = query.trim();
    const hits = q ? fuzzyFilter(q, commands, (c) => `${c.label} ${c.hint || ''} ${c.keywords || ''}`, 40) : commands.filter((c) => c.group !== 'Resources').slice(0, 30);
    const order: string[] = [];
    for (const h of hits) if (!order.includes(h.group)) order.push(h.group);
    const grouped = order.flatMap((g) => hits.filter((h) => h.group === g));
    return q ? [...grouped, ask(q)] : grouped;
  }, [query, commands, ask]);

  useEffect(() => setIndex(0), [query]);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    input.current?.focus();
    return () => opener?.focus?.();
  }, []);
  useEffect(() => {
    list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView?.({ block: 'nearest' });
  }, [index]);

  const choose = (c: Command | undefined) => {
    if (!c) return;
    close();
    c.run();
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setIndex((i) => Math.min(results.length - 1, i + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setIndex((i) => Math.max(0, i - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      choose(results[index]);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      close();
    }
  };

  let lastGroup = '';
  return (
    <div className="palette-backdrop" onClick={close}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Command palette" onClick={(e) => e.stopPropagation()}>
        <div className="palette__search">
          <Search size={18} aria-hidden="true" />
          <input
            ref={input}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKey}
            placeholder="Search pages, resources and actions, or ask a question"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            aria-activedescendant={results[index] ? 'cmd-' + index : undefined}
            aria-label="Command"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd>Esc</kbd>
        </div>
        <ul id="palette-list" ref={list} role="listbox" aria-label="Results">
          {results.map((c, i) => {
            const header = c.group !== lastGroup ? c.group : '';
            lastGroup = c.group;
            return (
              <li key={c.id} role="presentation">
                {header && <div className="palette__group" role="presentation">{header}</div>}
                <div
                  id={'cmd-' + i}
                  role="option"
                  aria-selected={i === index}
                  className="palette__item"
                  onMouseMove={() => setIndex(i)}
                  onClick={() => choose(c)}
                >
                  <span className="palette__icon">{c.icon}</span>
                  <span className="palette__label">{c.label}</span>
                  {c.hint && <span className="palette__hint">{c.hint}</span>}
                  {i === index && <CornerDownLeft size={14} className="palette__enter" aria-hidden="true" />}
                </div>
              </li>
            );
          })}
          {!results.length && <li className="palette__empty">No matches</li>}
        </ul>
        <footer className="palette__foot">
          <span>
            <kbd>↑</kbd>
            <kbd>↓</kbd> to move
          </span>
          <span>
            <kbd>↵</kbd> to open
          </span>
          <span>
            <kbd>?</kbd> for shortcuts
          </span>
        </footer>
      </div>
    </div>
  );
}

export const paletteIcons = { theme: <MoonStar size={15} />, logout: <LogOut size={15} />, keys: <Keyboard size={15} /> };

export function ShortcutHelp({ close }: { close: () => void }) {
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape' || e.key === '?') close();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [close]);
  return (
    <div className="palette-backdrop" onClick={close}>
      <section className="palette shortcuts" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts" onClick={(e) => e.stopPropagation()}>
        <header className="kit-section__head">
          <h2>Keyboard shortcuts</h2>
          <button type="button" className="icon" aria-label="Close dialog" onClick={close}>
            <X size={18} />
          </button>
        </header>
        <dl>
          {shortcutHelp.map(([keys, text]) => (
            <div key={keys}>
              <dt>
                {keys.split('  or  ').map((k, i) => (
                  <span key={k}>
                    {i > 0 && <em> or </em>}
                    {k.split(' ').filter(Boolean).map((part) => (
                      <kbd key={part}>{part}</kbd>
                    ))}
                  </span>
                ))}
              </dt>
              <dd>{text}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
