// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Plus, X } from 'lucide-react';
import { api, setCSRF, type Row } from './api';
import Nav from './components/Nav';
import PageHero, { type HeroTint } from './components/PageHero';
import Login from './components/Login';
import CreateForm, { createLabel } from './components/CreateForm';
import { Modal } from './components/kit';
import { ChangePassword, NotificationBell, ProfileMenu } from './components/Account';
import { notifications } from './lib/notifications';
import Keys from './pages/Keys';
import Settings from './pages/Settings';
import { ToastProvider, useToast } from './components/Toasts';
import CommandPalette, { buildCommands, paletteIcons, ShortcutHelp } from './components/CommandPalette';
import { shortcutHandler } from './lib/shortcuts';
import { PageContext } from './lib/pageContext';
import { DRAWER_KINDS } from './lib/resources';
import ResourceDrawer from './components/ResourceDrawer';
import WorkflowCanvas, { stepStatuses } from './components/WorkflowCanvas';
import { pageLabel, readFocus, readPage, type Page } from './lib/navGroups';
import type { Act, Collections } from './lib/types';
import { applyTheme, readStoredTheme, toggleTheme, type Theme } from './theme';
import Overview from './pages/Overview';
import Playground from './pages/Playground';
import Knowledge from './pages/Knowledge';
import Agents from './pages/Agents';
import Workflows from './pages/Workflows';
import Runs from './pages/Runs';
import Evaluations, { ScoreTrend, scoreHistory } from './pages/Evaluations';
import Approvals from './pages/Approvals';
import Guardrails from './pages/Guardrails';
import Prompts from './pages/Prompts';
import Batches from './pages/Batches';
import Usage from './pages/Usage';
import Audit from './pages/Audit';
import Users from './pages/Users';
import { Actions, Models, Recipes, Routers } from './pages/Catalog';

const pageHero: Partial<Record<Page, { title: string; lede: string; tint?: HeroTint }>> = {
  playground: { title: 'Ask. Ground. Verify.', lede: 'Choose a model, optionally ground it in a knowledge base, and see the exact passages behind every answer.' },
  models: { title: 'Choose the model. Keep the control.', lede: 'OpenAI-compatible, Ollama and optional AWS endpoints on an operator allowlist. Credentials stay in the environment, never in the catalog.' },
  routers: { title: 'Pay for the big model only when you need it.', lede: 'A cascade tries the cheapest model first and escalates when the answer is empty, hedged or scored low by a judge model. Every attempt is metered.', tint: 'amber' },
  knowledge: { title: 'Answers start with evidence.', lede: 'Index documents with content digests, then inspect exactly what BM25 and vector fusion retrieve before a model sees it.', tint: 'green' },
  agents: { title: 'Give intelligence a purpose.', lede: 'Bounded model and tool loops with registered schemas. Memory writes and external actions pause for a different human.', tint: 'purple' },
  actions: { title: 'Connect the systems you trust.', lede: 'Typed enterprise APIs registered by an administrator. Writes wait for an exact-argument approval and never retry on their own.', tint: 'purple' },
  workflows: { title: 'From a question to an approved outcome.', lede: 'Pinned DAG revisions with retrieval, generation, extraction and human review steps, checkpointed between nodes.', tint: 'purple' },
  prompts: { title: 'Version the instructions that matter.', lede: 'Templates with declared variables, optimistic revision edits and retained snapshots.' },
  recipes: { title: 'Prepare your next model.', lede: 'Export LoRA, QLoRA, distillation and quantization recipes for an external trainer. No GPU job runs here.', tint: 'amber' },
  jobs: { title: 'Every step, in view.', lede: 'Agent, workflow, evaluation and batch runs with their tool traces, checkpoints and exportable evidence.', tint: 'green' },
  evaluations: { title: 'Measure before you promote.', lede: 'Phrase assertions, LLM-judge criteria and groundedness checks with pass thresholds and release verdicts, comparable across revisions.', tint: 'green' },
  batches: { title: 'Run many prompts as one.', lede: 'Queue up to 100 prompts as one durable run. Each item records its own success or failure.' },
  approvals: { title: 'The decision stays with you.', lede: 'Exact actions, their proposer, expiry and fingerprint. An author can never approve their own proposal.', tint: 'red' },
  policies: { title: 'A consistent boundary for every model.', lede: 'Words, topics, regex filters, PII entities, grounding and an optional classifier model, applied to inputs and outputs, with a daily token budget.', tint: 'red' },
  usage: { title: 'Know what intelligence costs.', lede: 'Tokens, latency and estimated spend per request, priced at operator-configured rates.', tint: 'amber' },
  audit: { title: 'Trace the action back to its evidence.', lede: 'A hash-chained audit trail for every session, change, run and decision in this workspace.', tint: 'red' },
  keys: { title: 'Keys that can only do enough.', lede: 'Scoped, expiring service tokens for scripts, CI and the OpenAI-compatible API. They can view or propose, never approve.', tint: 'amber' },
  settings: { title: 'Your workspace, as deployed.', lede: 'Account, appearance and the server configuration this workspace runs under.' },
  users: { title: 'The right access. The right workspace.', lede: 'Viewers read, developers propose, approvers decide, administrators manage. Every workspace is isolated.' },
};

const COLLECTIONS = ['models', 'routers', 'knowledge', 'agents', 'actions', 'workflows', 'prompts', 'policies', 'evaluations', 'recipes', 'jobs', 'approvals'];
const CREATABLE: Page[] = ['models', 'routers', 'agents', 'actions', 'knowledge', 'workflows', 'prompts', 'policies', 'evaluations', 'recipes'];
const ADMIN_ONLY: Page[] = ['models', 'policies', 'actions'];

export default function App() {
  return (
    <ToastProvider>
      <Console />
    </ToastProvider>
  );
}

type Editor = { kind: Page; existing: Row | null };

function Console() {
  const toast = useToast();
  const [principal, setPrincipal] = useState<Row | null>(null);
  const [ready, setReady] = useState(false);
  const [page, setPage] = useState<Page>(() => readPage(window.location.hash));
  const [theme, setTheme] = useState<Theme>(() => {
    const t = readStoredTheme();
    applyTheme(t);
    return t;
  });
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [palette, setPalette] = useState(false);
  const [help, setHelp] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [askSeed, setAskSeed] = useState<{ text: string } | undefined>();
  const [focus, setFocus] = useState<string | undefined>(() => readFocus(window.location.hash));
  const [collections, setCollections] = useState<Collections>({});
  const [overview, setOverview] = useState<Row>({});
  const [prompt, setPrompt] = useState<Row | null>(null);

  useEffect(() => {
    api('/api/session')
      .then((r) => {
        setCSRF(r.csrf);
        setPrincipal(r.principal);
      })
      .catch(() => {})
      .finally(() => setReady(true));
  }, []);

  useEffect(() => {
    const onHashChange = () => {
      setPage(readPage(window.location.hash));
      setFocus(readFocus(window.location.hash));
      setError('');
      setPrompt(null);
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    if (!principal) return;
    let live = true;
    Promise.all(COLLECTIONS.map(async (k) => [k, (await api('/api/' + k)).items] as const))
      .then((pairs) => {
        if (live) setCollections(Object.fromEntries(pairs));
      })
      .catch((e) => {
        if (live) setError(String(e));
      });
    api('/api/overview')
      .then((r) => {
        if (live) setOverview(r);
      })
      .catch((e) => {
        if (live) setError(String(e));
      });
    return () => {
      live = false;
    };
  }, [principal, refresh]);

  useEffect(() => {
    if (!principal) return;
    const timer = setInterval(() => setRefresh((r) => r + 1), 5000);
    return () => clearInterval(timer);
  }, [principal]);

  const reload = () => setRefresh((r) => r + 1);
  const navigate = useCallback((next: Page) => {
    if (window.location.hash.slice(1) === next) setPage(next);
    else window.location.hash = next;
  }, []);
  const openResource = useCallback((kind: string, id: string) => {
    window.location.hash = kind + '/' + encodeURIComponent(id);
  }, []);
  const closeResource = useCallback(() => {
    const base = readPage(window.location.hash);
    window.history.replaceState(null, '', '#' + base);
    setFocus(undefined);
  }, []);
  const createRef = useRef<() => void>(() => {});

  useEffect(() => {
    if (!principal) return;
    const onKey = shortcutHandler({
      palette: () => setPalette(true),
      create: () => createRef.current(),
      help: () => setHelp(true),
      go: navigate,
    });
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [principal, navigate]);

  const logout = () =>
    act(async () => {
      await api('/api/logout', {});
      setPrincipal(null);
      setCollections({});
    });

  const role = principal?.role;
  const allowedCreate = useMemo(
    () => CREATABLE.filter((k) => (role === 'admin' || role === 'developer') && (!ADMIN_ONLY.includes(k) || role === 'admin')),
    [role],
  );
  const openCreate = useCallback(
    (kind: Page) => {
      setPrompt(null);
      setError('');
      setEditor({ kind, existing: null });
    },
    [],
  );
  const commands = useMemo(
    () =>
      buildCommands({
        collections,
        navigate,
        open: openResource,
        create: allowedCreate.map((k) => ({
          page: k,
          label: createLabel(k),
          run: () => {
            navigate(k);
            openCreate(k);
          },
        })),
        ask: (text) => {
          setAskSeed({ text });
          navigate('playground');
        },
        extra: [
          { id: 'theme', group: 'Actions', label: 'Toggle dark mode', icon: paletteIcons.theme, run: () => setTheme((t) => toggleTheme(t)) },
          { id: 'shortcuts', group: 'Actions', label: 'Keyboard shortcuts', icon: paletteIcons.keys, run: () => setHelp(true) },
          { id: 'logout', group: 'Actions', label: 'Log out', icon: paletteIcons.logout, run: () => logout() },
        ],
      }),
    [collections, navigate, openResource, allowedCreate, openCreate],
  );

  const act: Act = async (fn, success) => {
    setError('');
    try {
      const r = await fn();
      reload();
      if (success) toast(success);
      return r;
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setError(message);
      return null;
    }
  };

  if (!ready) return <div className="loading">Connecting to your workspace…</div>;
  if (!principal)
    return (
      <Login
        onLogin={(p) => {
          setPrincipal(p);
          setReady(true);
        }}
      />
    );

  const canWrite = principal.role === 'admin' || principal.role === 'developer';
  const canApprove = principal.role === 'admin' || principal.role === 'approver';
  const pending = (collections.approvals || []).filter((a) => a.status === 'pending').length;
  const rows = collections[page] || [];
  const canCreate = allowedCreate.includes(page);
  createRef.current = () => {
    if (canCreate) openCreate(page);
  };
  const hero = pageHero[page];
  const pageActions = {
    createLabel: createLabel(page),
    create: canCreate ? () => openCreate(page) : undefined,
    open: DRAWER_KINDS.includes(page) ? (r: Row) => openResource(page, r.id) : undefined,
  };
  const drawerRow = focus && DRAWER_KINDS.includes(page) ? rows.find((r) => r.id === focus) : undefined;

  const body: Record<Page, ReactNode> = {
    overview: (
      <Overview
        overview={overview}
        collections={collections}
        refresh={refresh}
        principal={principal}
        pendingApprovals={pending}
        onNavigate={navigate}
        onInspectRun={(run) => openResource('jobs', run.id)}
      />
    ),
    playground: <Playground models={collections.models || []} routers={collections.routers || []} knowledge={collections.knowledge || []} canWrite={canWrite} act={act} principal={principal} seed={askSeed} />,
    models: <Models rows={rows} />,
    routers: <Routers rows={rows} models={collections.models || []} />,
    knowledge: <Knowledge rows={rows} canWrite={canWrite} act={act} refresh={refresh} />,
    agents: <Agents rows={rows} canWrite={canWrite} act={act} />,
    actions: <Actions rows={rows} />,
    workflows: <Workflows rows={rows} />,
    prompts: <Prompts rows={rows} canWrite={canWrite} act={act} selected={prompt} onSelect={setPrompt} onEdit={() => prompt && setEditor({ kind: 'prompts', existing: prompt })} evaluations={collections.evaluations || []} onQueued={() => navigate('jobs')} />,
    recipes: <Recipes rows={rows} act={act} />,
    jobs: (
      <Runs
        key={page === 'jobs' ? focus : undefined}
        rows={rows}
        focus={page === 'jobs' ? focus : undefined}
        approvals={collections.approvals || []}
        principal={principal}
        canApprove={canApprove}
        act={act}
      />
    ),
    evaluations: <Evaluations rows={rows} jobs={collections.jobs || []} canWrite={canWrite} act={act} onQueued={() => navigate('jobs')} />,
    batches: <Batches models={collections.models || []} canWrite={canWrite} act={act} done={() => navigate('jobs')} />,
    approvals: <Approvals rows={rows} principal={principal} canApprove={canApprove} act={act} />,
    policies: <Guardrails rows={rows} act={act} />,
    usage: <Usage refresh={refresh} />,
    audit: <Audit refresh={refresh} />,
    users: <Users principal={principal} act={act} refresh={refresh} />,
    keys: <Keys principal={principal} act={act} refresh={refresh} />,
    settings: <Settings principal={principal} theme={theme} onTheme={(t) => {
          applyTheme(t);
          setTheme(t);
        }} onPassword={() => setPasswordOpen(true)} />,
  };


  return (
    <>
      <Nav
        page={page}
        setPage={navigate}
        theme={theme}
        onToggleTheme={() => setTheme((t) => toggleTheme(t))}
        onSearch={() => setPalette(true)}
        account={
          <>
            <NotificationBell notes={notifications(collections, principal)} seenKey={`nuvora-seen:${principal.tenant}:${principal.username}`} />
            <ProfileMenu principal={principal} onPassword={() => setPasswordOpen(true)} onShortcuts={() => setHelp(true)} onLogout={logout} />
          </>
        }
        pendingApprovals={pending}
      />
      <main>
        {error && (
          <div role="alert" className="error global-error">
            {error}
            <button type="button" className="icon" aria-label="Dismiss error" onClick={() => setError('')}>
              <X size={16} />
            </button>
          </div>
        )}
        <div key={page}>
          {hero && (
            <PageHero
              eyebrow={pageLabel(page)}
              title={hero.title}
              lede={hero.lede}
              tint={hero.tint}
              action={
                canCreate ? (
                  <button
                    type="button"
                    className="primary"
                    onClick={() => openCreate(page)}
                  >
                    <Plus size={16} />
                    Create {createLabel(page)}
                  </button>
                ) : undefined
              }
            />
          )}
          <PageContext.Provider value={pageActions}>{body[page]}</PageContext.Provider>
        </div>
        <footer className="app-footer">
          <span>Nuvora · Zyvor Platform</span>
          <span>Private by deployment. Accountable by design.</span>
          <span>Evaluation release · 0.2.0</span>
        </footer>
      </main>
      {drawerRow && (
        <ResourceDrawer
          key={page + drawerRow.id}
          kind={page}
          row={drawerRow}
          principal={principal}
          act={act}
          close={closeResource}
          onEdit={(row) => {
            setError('');
            setEditor({ kind: page, existing: row });
          }}
          onRun={(id) => openResource('jobs', id)}
        >
          {page === 'workflows' && <WorkflowPreview workflow={drawerRow} jobs={collections.jobs || []} />}
          {page === 'evaluations' && <ScoreTrend runs={scoreHistory(collections.jobs || [], drawerRow.id)} />}
        </ResourceDrawer>
      )}
      {editor && (
        <Modal title={editor.existing ? 'Edit ' + createLabel(editor.kind) : 'Create ' + createLabel(editor.kind)} close={() => setEditor(null)}>
          <>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <CreateForm
              kind={editor.kind}
              collections={collections}
              existing={editor.existing}
              save={(body) =>
                act(
                  () => api('/api/' + editor.kind + (editor.existing ? '/' + editor.existing.id : ''), body),
                  editor.existing ? 'Saved a new revision' : 'Created ' + createLabel(editor.kind),
                ).then((r) => {
                  if (r) {
                    setEditor(null);
                    setPrompt(null);
                  }
                })
              }
            />
          </>
        </Modal>
      )}
      {palette && <CommandPalette commands={commands.base} ask={commands.ask} close={() => setPalette(false)} />}
      {help && <ShortcutHelp close={() => setHelp(false)} />}
      {passwordOpen && (
        <Modal title="Change password" close={() => setPasswordOpen(false)}>
          <ChangePassword
            done={() => {
              setPasswordOpen(false);
              toast('Password changed · other sessions signed out');
            }}
          />
        </Modal>
      )}
    </>
  );
}

function WorkflowPreview({ workflow, jobs }: { workflow: Row; jobs: Row[] }) {
  const last = jobs.find((j) => j.type === 'workflow' && j.target === workflow.id);
  return (
    <div className="workflow-preview">
      <WorkflowCanvas steps={workflow.steps || []} status={last ? stepStatuses(last) : undefined} />
      <p className="small muted">
        {workflow.steps?.length || 0} steps · pinned at revision {workflow.revision}
        {last ? ` · latest run ${last.status.replaceAll('_', ' ')}` : ' · not run yet'}
      </p>
    </div>
  );
}
