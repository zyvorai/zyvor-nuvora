// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { BookOpen, Columns2, Copy, MessageSquarePlus, RotateCcw, Settings2, Sparkles, Square, Trash2 } from 'lucide-react';
import { ago, api, money, stream, type Row } from '../api';
import { Badge, Card, Field, ListEmpty } from '../components/kit';
import { useToast } from '../components/Toasts';
import type { Act } from '../lib/types';

type Answer = { model: string; content: string; meta?: Row; error?: string; streaming?: boolean; stopped?: boolean };
type Turn = { role: 'user'; content: string; citations?: Row[] } | { role: 'assistant'; answers: Answer[] };
type Conversation = { id: string; title: string; model: string; compare: string; kb: string; turns: Turn[]; updated: number };
type Settings = { temperature: number; max_tokens: number; system: string; stream: boolean; cache: boolean };

const DEFAULTS: Settings = { temperature: 0, max_tokens: 1024, system: '', stream: true, cache: true };
const STARTER = 'How does Keep protect an agent?';
const HISTORY = 20;

const fresh = (model = 'auto', kb = ''): Conversation => ({
  id: Math.random().toString(36).slice(2, 10),
  title: 'New conversation',
  model,
  compare: '',
  kb,
  turns: [],
  updated: Date.now() / 1000,
});

function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback;
  } catch {
    return fallback;
  }
}

function loadChats(key: string): Conversation[] {
  try {
    const value = JSON.parse(localStorage.getItem(key) || '[]');
    return Array.isArray(value) && value.length ? value : [fresh()];
  } catch {
    return [fresh()];
  }
}

export default function Playground({
  models,
  routers = [],
  knowledge,
  canWrite,
  act,
  principal,
  seed,
}: {
  models: Row[];
  routers?: Row[];
  knowledge: Row[];
  canWrite: boolean;
  act: Act;
  principal?: Row;
  seed?: { text: string };
}) {
  const toast = useToast();
  const owner = principal ? `${principal.tenant}:${principal.username}` : 'local';
  const chatKey = 'nuvora-chats:' + owner;
  const settingsKey = 'nuvora-playground:' + owner;
  const [chats, setChats] = useState<Conversation[]>(() => loadChats(chatKey));
  const [activeId, setActiveId] = useState(() => chats[0].id);
  const [settings, setSettings] = useState<Settings>(() => load(settingsKey, DEFAULTS));
  const [message, setMessage] = useState(STARTER);
  const [showSettings, setShowSettings] = useState(false);
  const [focusCitation, setFocusCitation] = useState<number | null>(null);
  const controllers = useRef<AbortController[]>([]);
  const threadEnd = useRef<HTMLDivElement>(null);
  const active = chats.find((c) => c.id === activeId) || chats[0];
  const [retrieving, setRetrieving] = useState(false);
  const busy = retrieving || active.turns.some((t) => t.role === 'assistant' && t.answers.some((a) => a.streaming));
  const chatModels = useMemo(() => models.filter((m) => m.capability === 'chat'), [models]);
  const modelName = (id: string) => (id === 'auto' ? 'Auto' : id.startsWith('router:') ? 'Router · ' + (routers.find((r) => 'router:' + r.id === id)?.name || id) : chatModels.find((m) => m.id === id)?.name || id);

  useEffect(() => {
    try {
      const stored = chats
        .filter((c) => c.turns.length)
        .slice(0, 30)
        .map((c) => ({ ...c, turns: c.turns.map((t) => (t.role === 'assistant' ? { ...t, answers: t.answers.map((a) => ({ ...a, streaming: false })) } : t)) }));
      localStorage.setItem(chatKey, JSON.stringify(stored));
    } catch {
      /* storage full or unavailable: conversations stay in memory */
    }
  }, [chats, chatKey]);

  useEffect(() => {
    try {
      localStorage.setItem(settingsKey, JSON.stringify(settings));
    } catch {
      /* ignore */
    }
  }, [settings, settingsKey]);

  const seeded = useRef<{ text: string } | undefined>(undefined);
  useEffect(() => {
    if (!seed || seeded.current === seed || !canWrite) return;
    seeded.current = seed;
    const conv = active.turns.length ? fresh(active.model, active.kb) : active;
    if (conv !== active) {
      setChats((all) => [conv, ...all]);
      setActiveId(conv.id);
    }
    setMessage('');
    generate(conv, seed.text, []);
  }, [seed, canWrite]);

  useEffect(() => {
    threadEnd.current?.scrollIntoView?.({ block: 'nearest' });
  }, [active.turns.length]);

  useEffect(() => () => controllers.current.forEach((c) => c.abort()), []);

  const update = (id: string, fn: (c: Conversation) => Conversation) => setChats((all) => all.map((c) => (c.id === id ? fn(c) : c)));
  const patchAnswer = (id: string, turn: number, slot: number, fn: (a: Answer) => Answer) =>
    update(id, (c) => ({
      ...c,
      turns: c.turns.map((t, i) => (i === turn && t.role === 'assistant' ? { ...t, answers: t.answers.map((a, j) => (j === slot ? fn(a) : a)) } : t)),
    }));

  const lastCitations = useMemo(() => {
    for (let i = active.turns.length - 1; i >= 0; i--) {
      const t = active.turns[i];
      if (t.role === 'user') return t.citations || [];
    }
    return [];
  }, [active.turns]);

  function history(turns: Turn[]) {
    const out: Row[] = [];
    for (const t of turns) {
      if (t.role === 'user') out.push({ role: 'user', content: t.content });
      else if (t.answers[0]?.content) out.push({ role: 'assistant', content: t.answers[0].content });
    }
    return out.slice(-HISTORY);
  }

  async function generate(conv: Conversation, question: string, prior: Turn[]) {
    let citations: Row[] = [];
    if (conv.kb) {
      setRetrieving(true);
      const r = await act(() => api('/api/retrieve', { knowledge_ids: [conv.kb], query: question }));
      setRetrieving(false);
      if (!r) return;
      citations = r.citations || [];
    }
    const system =
      settings.system.trim() ||
      (conv.kb ? 'Answer using the supplied evidence. Cite sources as [1], [2]. If evidence is absent, say so.' : 'Be helpful and precise.');
    const evidence = citations.length
      ? '\nEvidence:\n' + citations.map((c, i) => `[${i + 1}] ${c.document} (chunk ${c.index}): ${c.text}`).join('\n')
      : '';
    const messages = [{ role: 'system', content: system }, ...history(prior), { role: 'user', content: question + evidence }];
    const targets = [conv.model, ...(conv.compare ? [conv.compare] : [])];
    const turnIndex = prior.length + 1;
    update(conv.id, (c) => ({
      ...c,
      title: c.turns.length ? c.title : question.slice(0, 60),
      updated: Date.now() / 1000,
      turns: [...prior, { role: 'user', content: question, citations }, { role: 'assistant', answers: targets.map((model) => ({ model, content: '', streaming: true })) }],
    }));
    setFocusCitation(null);
    const sources = citations.slice(0, 20).map((c) => String(c.text));
    await Promise.all(targets.map((model, slot) => answer(conv.id, turnIndex, slot, model, messages, sources)));
  }

  async function answer(id: string, turn: number, slot: number, model: string, messages: Row[], sources: string[] = []) {
    const body = { model, messages, temperature: settings.temperature, max_tokens: settings.max_tokens, cache: settings.cache, ...(sources.length ? { sources } : {}) };
    const controller = new AbortController();
    controllers.current.push(controller);
    try {
      if (settings.stream) {
        await stream(
          '/api/chat/stream',
          body,
          ({ event, data }) => {
            if (event === 'start') patchAnswer(id, turn, slot, (a) => ({ ...a, model: data.model, meta: { ...a.meta, name: data.name, routing: data.routing } }));
            else if (event === 'delta') patchAnswer(id, turn, slot, (a) => ({ ...a, content: a.content + data.text }));
            else if (event === 'done') patchAnswer(id, turn, slot, (a) => ({ ...a, streaming: false, meta: { ...a.meta, ...data } }));
            else if (event === 'error') patchAnswer(id, turn, slot, (a) => ({ ...a, streaming: false, error: data.error }));
          },
          controller.signal,
        );
        patchAnswer(id, turn, slot, (a) => ({ ...a, streaming: false }));
      } else {
        const r = await api('/api/chat', body);
        patchAnswer(id, turn, slot, (a) => ({ ...a, content: r.content, streaming: false, model: r.model || model, meta: r }));
      }
    } catch (e) {
      const aborted = controller.signal.aborted;
      patchAnswer(id, turn, slot, (a) => ({ ...a, streaming: false, stopped: aborted, error: aborted ? undefined : e instanceof Error ? e.message : String(e) }));
    } finally {
      controllers.current = controllers.current.filter((c) => c !== controller);
    }
  }

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    const question = message.trim();
    if (!question || busy || !canWrite) return;
    setMessage('');
    await generate(active, question, active.turns);
  }

  function regenerate() {
    const turns = active.turns;
    const lastUser = turns.map((t) => t.role).lastIndexOf('user');
    if (lastUser < 0 || busy) return;
    const question = (turns[lastUser] as { content: string }).content;
    generate(active, question, turns.slice(0, lastUser));
  }

  function stop() {
    controllers.current.forEach((c) => c.abort());
  }

  function newChat() {
    const existing = chats.find((c) => !c.turns.length);
    if (existing) setActiveId(existing.id);
    else {
      const next = fresh(active.model, active.kb);
      setChats((all) => [next, ...all]);
      setActiveId(next.id);
    }
    setMessage(STARTER);
  }

  function remove(id: string) {
    setChats((all) => {
      const rest = all.filter((c) => c.id !== id);
      const next = rest.length ? rest : [fresh()];
      if (id === activeId) setActiveId(next[0].id);
      return next;
    });
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast('Copied to clipboard');
    } catch {
      toast('Copy is unavailable in this browser', 'error');
    }
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit();
  };

  const sorted = [...chats].sort((a, b) => b.updated - a.updated);

  return (
    <div className="playground">
      <aside className="card chat-rail" aria-label="Conversations">
        <button type="button" className="btn-secondary chat-rail__new" onClick={newChat}>
          <MessageSquarePlus size={16} />
          New conversation
        </button>
        <ul>
          {sorted.map((c) => (
            <li key={c.id} className={c.id === active.id ? 'active' : ''}>
              <button type="button" className="chat-rail__item" onClick={() => setActiveId(c.id)} aria-current={c.id === active.id ? 'true' : undefined}>
                <span>{c.title}</span>
                <small>
                  {c.turns.filter((t) => t.role === 'user').length} turns · {ago(c.updated)}
                </small>
              </button>
              {c.turns.length > 0 && (
                <button type="button" className="icon" aria-label={'Delete conversation ' + c.title} onClick={() => remove(c.id)}>
                  <Trash2 size={14} />
                </button>
              )}
            </li>
          ))}
        </ul>
        <p className="small muted">Stored in this browser only.</p>
      </aside>

      <Card
        title="Ask your model"
        className="chat-main"
        actions={
          <div className="popover-anchor">
            <button
              type="button"
              className={'btn-secondary compact' + (active.compare ? ' on' : '')}
              aria-pressed={!!active.compare}
              onClick={() => {
                const other = chatModels.find((m) => m.id !== active.model)?.id || 'auto';
                update(active.id, (c) => ({ ...c, compare: c.compare ? '' : other }));
              }}
            >
              <Columns2 size={15} />
              Compare
            </button>
            <button type="button" className="icon" aria-label="Generation settings" aria-expanded={showSettings} onClick={() => setShowSettings((s) => !s)}>
              <Settings2 size={17} />
            </button>
            {showSettings && (
              <div className="popover" role="dialog" aria-label="Generation settings">
                <Field label={`Temperature · ${settings.temperature.toFixed(1)}`}>
                  <input type="range" min={0} max={2} step={0.1} value={settings.temperature} onChange={(e) => setSettings({ ...settings, temperature: Number(e.target.value) })} />
                </Field>
                <Field label="Max output tokens">
                  <input type="number" min={1} max={8192} value={settings.max_tokens} onChange={(e) => setSettings({ ...settings, max_tokens: Math.min(8192, Math.max(1, Number(e.target.value) || 1)) })} />
                </Field>
                <Field label="System prompt">
                  <textarea rows={3} value={settings.system} placeholder="Default: grounded or helpful assistant" onChange={(e) => setSettings({ ...settings, system: e.target.value })} />
                </Field>
                <label className="check">
                  <input type="checkbox" checked={settings.stream} onChange={(e) => setSettings({ ...settings, stream: e.target.checked })} />
                  Stream responses
                </label>
                <label className="check">
                  <input type="checkbox" checked={settings.cache} onChange={(e) => setSettings({ ...settings, cache: e.target.checked })} />
                  Use response cache
                </label>
                <button type="button" className="link" onClick={() => setSettings(DEFAULTS)}>
                  Reset to defaults
                </button>
              </div>
            )}
          </div>
        }
      >
        <div className="thread" aria-live="polite">
          {!active.turns.length && (
            <div className="thread-empty">
              <Sparkles size={22} aria-hidden="true" />
              <p>Ask anything. Ground it in a knowledge base to see the exact passages behind the answer.</p>
              <div className="suggestions">
                {[STARTER, 'Summarize the approval policy in three bullets.', 'What evidence does a workflow run keep?'].map((s) => (
                  <button key={s} type="button" className="chip" onClick={() => setMessage(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {active.turns.map((t, i) =>
            t.role === 'user' ? (
              <div key={i} className="bubble user">
                <p>{t.content}</p>
                {!!t.citations?.length && (
                  <div className="cite-row" aria-label="Sources">
                    {t.citations.map((c, n) => (
                      <span key={n} className="cite-chip" tabIndex={0} onMouseEnter={() => setFocusCitation(n)} onFocus={() => setFocusCitation(n)}>
                        [{n + 1}] {c.document}
                        <span className="cite-card" role="tooltip">
                          <strong>{c.document}</strong>
                          <span>{String(c.text).slice(0, 280)}</span>
                          <small>
                            Chunk {c.index} · {String(c.digest).slice(0, 12)}…
                          </small>
                        </span>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div key={i} className={'answers' + (t.answers.length > 1 ? ' compare-grid' : '')}>
                {t.answers.map((a, slot) => (
                  <div key={slot} className="answer">
                    <div className="kit-section__head">
                      <h3>Response</h3>
                      <span className="answer-model">{a.meta?.name || modelName(a.model)}</span>
                      {a.meta?.evidence_class && <Badge value={a.meta.evidence_class} />}
                    </div>
                    {a.error ? (
                      <p role="alert" className="error">
                        {a.error}
                      </p>
                    ) : (
                      <p className={a.streaming ? 'streaming' : ''}>{a.content || (a.streaming ? 'Thinking…' : '')}</p>
                    )}
                    {!a.streaming && !a.error && (
                      <div className="answer-foot">
                        <span className="small muted">
                          {a.stopped
                            ? 'Stopped'
                            : [a.meta?.cached ? 'Cache hit' : 'Fresh response', money(a.meta?.cost || 0), a.meta?.routing, a.meta?.latency_ms != null ? a.meta.latency_ms + ' ms' : '', a.meta?.usage ? `${(a.meta.usage.prompt_tokens || 0) + (a.meta.usage.completion_tokens || 0)} tokens` : '', a.meta?.grounding ? `Grounding ${a.meta.grounding.score}` : '', a.meta?.escalations ? `${a.meta.escalations.length} escalation(s)` : '']
                                .filter(Boolean)
                                .join(' · ')}
                        </span>
                        <span className="answer-actions">
                          <button type="button" className="icon" aria-label="Copy answer" onClick={() => copy(a.content)}>
                            <Copy size={14} />
                          </button>
                          {i === active.turns.length - 1 && slot === 0 && canWrite && (
                            <button type="button" className="icon" aria-label="Regenerate" onClick={regenerate}>
                              <RotateCcw size={14} />
                            </button>
                          )}
                        </span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ),
          )}
          <div ref={threadEnd} />
        </div>

        <form onSubmit={submit} className="composer">
          <div className="form-grid">
            <Field label="Model">
              <select value={active.model} onChange={(e) => update(active.id, (c) => ({ ...c, model: e.target.value }))}>
                <option value="auto">Auto · lowest configured price</option>
                {chatModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
                {routers.map((r) => (
                  <option key={r.id} value={'router:' + r.id}>
                    Router · {r.name}
                  </option>
                ))}
              </select>
            </Field>
            {active.compare ? (
              <Field label="Compare with">
                <select value={active.compare} onChange={(e) => update(active.id, (c) => ({ ...c, compare: e.target.value }))}>
                  <option value="auto">Auto · lowest configured price</option>
                  {chatModels.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
                  {routers.map((r) => (
                    <option key={r.id} value={'router:' + r.id}>
                      Router · {r.name}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}
            <Field label="Grounding">
              <select value={active.kb} onChange={(e) => update(active.id, (c) => ({ ...c, kb: e.target.value }))}>
                <option value="">No knowledge base</option>
                {knowledge.map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Your question">
            <textarea rows={3} value={message} onChange={(e) => setMessage(e.target.value)} onKeyDown={onKey} required />
          </Field>
          <div className="composer__actions">
            <span className="small muted">⌘↵ to send{active.turns.length ? ` · ${Math.min(HISTORY, history(active.turns).length)} prior messages in context` : ''}</span>
            {busy ? (
              <button type="button" className="btn-secondary" onClick={stop}>
                <Square size={14} />
                Stop
              </button>
            ) : (
              <button type="submit" className="primary" disabled={!canWrite}>
                <Sparkles size={16} />
                Generate answer
              </button>
            )}
          </div>
        </form>
      </Card>

      <Card title="Evidence sources" className="chat-evidence">
        {lastCitations.length ? (
          lastCitations.map((c, i) => (
            <article className={'citation' + (focusCitation === i ? ' focused' : '')} key={i}>
              <span className="kit-eyebrow">Source {i + 1}</span>
              <h3>{c.document}</h3>
              <p>{c.text}</p>
              <small>
                Chunk {c.index} · {c.source}
                {c.score != null ? ` · score ${Number(c.score).toFixed(3)}` : ''}
              </small>
              <code>{String(c.digest).slice(0, 20)}…</code>
            </article>
          ))
        ) : (
          <ListEmpty icon={BookOpen} title="Ground your answer" description="Select a knowledge base to retrieve cited passages." />
        )}
        <p className="note">Offline demo is a transport and workflow fixture. It echoes supplied text; it does not reason or produce a grounded AI answer.</p>
      </Card>
    </div>
  );
}
