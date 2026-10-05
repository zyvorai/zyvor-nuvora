import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Plus, X } from 'lucide-react';
import { api, setCSRF, type Row } from './api';
import Nav from './components/Nav';
import PageHero, { type HeroTint } from './components/PageHero';
import Login from './components/Login';
import CreateForm, { createLabel } from './components/CreateForm';
import { Modal } from './components/kit';
import { pageLabel, readPage, type Page } from './lib/navGroups';
import type { Act, Collections } from './lib/types';
import { applyTheme, readStoredTheme, toggleTheme, type Theme } from './theme';
import Overview from './pages/Overview';
import Playground from './pages/Playground';
import Knowledge from './pages/Knowledge';
import Agents from './pages/Agents';
import Workflows from './pages/Workflows';
import Runs from './pages/Runs';
import Evaluations from './pages/Evaluations';
import Approvals from './pages/Approvals';
import Guardrails from './pages/Guardrails';
import Prompts from './pages/Prompts';
import Batches from './pages/Batches';
import Usage from './pages/Usage';
import Audit from './pages/Audit';
import Users from './pages/Users';
import { Actions, Models, Recipes } from './pages/Catalog';

const pageHero: Partial<Record<Page, { title: string; lede: string; tint?: HeroTint }>> = {
  playground: { title: 'Ask. Ground. Verify.', lede: 'Choose a model, optionally ground it in a knowledge base, and see the exact passages behind every answer.' },
  models: { title: 'Choose the model. Keep the control.', lede: 'OpenAI-compatible, Ollama and optional Bedrock endpoints on an operator allowlist. Credentials stay in the environment, never in the catalog.' },
  knowledge: { title: 'Answers start with evidence.', lede: 'Index documents with content digests, then inspect exactly what BM25 and vector fusion retrieve before a model sees it.', tint: 'green' },
  agents: { title: 'Give intelligence a purpose.', lede: 'Bounded model and tool loops with registered schemas. Memory writes and external actions pause for a different human.', tint: 'purple' },
  actions: { title: 'Connect the systems you trust.', lede: 'Typed enterprise APIs registered by an administrator. Writes wait for an exact-argument approval and never retry on their own.', tint: 'purple' },
  workflows: { title: 'From a question to an approved outcome.', lede: 'Pinned DAG revisions with retrieval, generation, extraction and human review steps, checkpointed between nodes.', tint: 'purple' },
  prompts: { title: 'Version the instructions that matter.', lede: 'Templates with declared variables, optimistic revision edits and retained snapshots.' },
  recipes: { title: 'Prepare your next model.', lede: 'Export LoRA, QLoRA, distillation and quantization recipes for an external trainer. No GPU job runs here.', tint: 'amber' },
  jobs: { title: 'Every step, in view.', lede: 'Agent, workflow, evaluation and batch runs with their tool traces, checkpoints and exportable evidence.', tint: 'green' },
  evaluations: { title: 'Measure before you promote.', lede: 'Contains and excludes suites with pass thresholds and release verdicts, comparable across revisions.', tint: 'green' },
  batches: { title: 'Run many prompts as one.', lede: 'Queue up to 100 prompts as one durable run. Each item records its own success or failure.' },
  approvals: { title: 'The decision stays with you.', lede: 'Exact actions, their proposer, expiry and fingerprint. An author can never approve their own proposal.', tint: 'red' },
  policies: { title: 'A consistent boundary for every model.', lede: 'Topic, instruction-override, size and PII rules applied to inputs and outputs, with a daily token budget.', tint: 'red' },
  usage: { title: 'Know what intelligence costs.', lede: 'Tokens, latency and estimated spend per request, priced at operator-configured rates.', tint: 'amber' },
  audit: { title: 'Trace the action back to its evidence.', lede: 'A hash-chained audit trail for every session, change, run and decision in this workspace.', tint: 'red' },
  users: { title: 'The right access. The right workspace.', lede: 'Viewers read, developers propose, approvers decide, administrators manage. Every workspace is isolated.' },
};

const COLLECTIONS = ['models', 'knowledge', 'agents', 'actions', 'workflows', 'prompts', 'policies', 'evaluations', 'recipes', 'jobs', 'approvals'];
const CREATABLE: Page[] = ['models', 'agents', 'actions', 'knowledge', 'workflows', 'prompts', 'policies', 'evaluations', 'recipes'];
const ADMIN_ONLY: Page[] = ['models', 'policies', 'actions'];

export default function App() {
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
  const [modal, setModal] = useState(false);
  const [collections, setCollections] = useState<Collections>({});
  const [overview, setOverview] = useState<Row>({});
  const [prompt, setPrompt] = useState<Row | null>(null);
  const [runFocus, setRunFocus] = useState<string | undefined>();

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

  const act: Act = async (fn) => {
    setError('');
    try {
      const r = await fn();
      reload();
      return r;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
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
  const canCreate = CREATABLE.includes(page) && canWrite && (!ADMIN_ONLY.includes(page) || principal.role === 'admin');
  const hero = pageHero[page];

  const body: Record<Page, ReactNode> = {
    overview: (
      <Overview
        overview={overview}
        principal={principal}
        pendingApprovals={pending}
        onNavigate={navigate}
        onInspectRun={(run) => {
          setRunFocus(run.id);
          navigate('jobs');
        }}
      />
    ),
    playground: <Playground models={collections.models || []} knowledge={collections.knowledge || []} canWrite={canWrite} act={act} />,
    models: <Models rows={rows} />,
    knowledge: <Knowledge rows={rows} canWrite={canWrite} act={act} />,
    agents: <Agents rows={rows} canWrite={canWrite} act={act} />,
    actions: <Actions rows={rows} />,
    workflows: <Workflows rows={rows} canWrite={canWrite} act={act} />,
    prompts: <Prompts rows={rows} canWrite={canWrite} act={act} selected={prompt} onSelect={setPrompt} onEdit={() => setModal(true)} />,
    recipes: <Recipes rows={rows} act={act} />,
    jobs: <Runs key={runFocus} rows={rows} focus={runFocus} />,
    evaluations: <Evaluations rows={rows} canWrite={canWrite} act={act} onQueued={() => navigate('jobs')} />,
    batches: <Batches models={collections.models || []} canWrite={canWrite} act={act} done={() => navigate('jobs')} />,
    approvals: <Approvals rows={rows} principal={principal} canApprove={canApprove} act={act} />,
    policies: <Guardrails rows={rows} act={act} />,
    usage: <Usage refresh={refresh} />,
    audit: <Audit refresh={refresh} />,
    users: <Users principal={principal} act={act} refresh={refresh} />,
  };

  const editing = page === 'prompts' && prompt;

  return (
    <>
      <Nav
        page={page}
        setPage={navigate}
        theme={theme}
        onToggleTheme={() => setTheme((t) => toggleTheme(t))}
        onLogout={() =>
          act(async () => {
            await api('/api/logout', {});
            setPrincipal(null);
            setCollections({});
          })
        }
        tenant={principal.tenant}
        role={principal.role}
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
                    onClick={() => {
                      setPrompt(null);
                      setModal(true);
                    }}
                  >
                    <Plus size={16} />
                    Create {createLabel(page)}
                  </button>
                ) : undefined
              }
            />
          )}
          {body[page]}
        </div>
        <footer className="app-footer">
          <span>Nuvora · Zyvor Platform</span>
          <span>Private by deployment. Accountable by design.</span>
          <span>Evaluation release · 0.1.0</span>
        </footer>
      </main>
      {modal && (
        <Modal title={editing ? 'Edit prompt revision' : 'Create ' + createLabel(page)} close={() => setModal(false)}>
          <>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <CreateForm
              kind={page}
              collections={collections}
              existing={editing ? prompt : null}
              save={(body) =>
                act(() => api('/api/' + page + (editing ? '/' + prompt.id : ''), body)).then((r) => {
                  if (r) {
                    setModal(false);
                    setPrompt(null);
                  }
                })
              }
            />
          </>
        </Modal>
      )}
    </>
  );
}
