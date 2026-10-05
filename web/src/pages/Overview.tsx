import { Activity, ArrowRight, BookOpen, Bot, Cpu, KeyRound, ShieldCheck, Wallet } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api, money, time, type Row } from '../api';
import { AreaChart, Donut, Sparkline } from '../components/charts';
import { Badge, Card, ListEmpty } from '../components/kit';
import type { Page } from '../lib/navGroups';
import type { Collections } from '../lib/types';
import Onboarding from '../components/Onboarding';

const layers: [typeof Cpu, string, string, Page][] = [
  [Cpu, 'Model layer', 'Local, hosted, or your own endpoint', 'models'],
  [BookOpen, 'Knowledge layer', 'Retrieved evidence with source digests', 'knowledge'],
  [Bot, 'Agent layer', 'Registered tools and bounded execution', 'agents'],
  [ShieldCheck, 'Control layer', 'Separate approval and audit evidence', 'approvals'],
];

export default function Overview({
  overview,
  collections,
  principal,
  pendingApprovals,
  onNavigate,
  onInspectRun,
  refresh = 0,
}: {
  overview: Row;
  collections: Collections;
  principal: Row;
  pendingApprovals: number;
  onNavigate: (p: Page) => void;
  onInspectRun: (run: Row) => void;
  refresh?: number;
}) {
  const [series, setSeries] = useState<Row | null>(null);
  const [stats, setStats] = useState<Row | null>(null);
  useEffect(() => {
    let live = true;
    api('/api/usage/series?days=14')
      .then((r) => live && setSeries(r))
      .catch(() => {});
    api('/api/runs/stats')
      .then((r) => live && setStats(r))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [refresh]);
  const days: Row[] = series?.days || [];
  const runsPerDay = days.map((d) => (collections.jobs || []).filter((j) => new Date(j.created * 1000).toISOString().slice(0, 10) === d.date).length);
  const verified = Boolean(overview.audit?.valid);
  const figures: [string, string | number, number[] | null][] = [
    ['Models', overview.counts?.models || 0, null],
    ['Knowledge bases', overview.counts?.knowledge || 0, null],
    ['Runs', overview.counts?.jobs || 0, days.length ? runsPerDay : null],
    ['Tokens', overview.usage?.tokens?.toLocaleString() || 0, days.length ? days.map((d) => d.tokens) : null],
  ];
  const tones: Record<string, string> = { completed: 'green', failed: 'red', rejected: 'red', waiting_approval: 'amber', queued: 'blue', running: 'cyan' };
  return (
    <div className="overview">
      <header className="hero">
        <p className="eyebrow">Nuvora · Workspace overview</p>
        <h1>Intelligence, with a chain of evidence.</h1>
        <p>Connect a model. Ground an answer. Approve the next step. Everything you build, in one accountable workspace.</p>
        <div className="overview-hero-row">
          <span className={`overview-status ${pendingApprovals ? 'tone-warn' : verified ? 'tone-ok' : 'tone-idle'}`} role="status">
            <i />
            {pendingApprovals ? `${pendingApprovals} decision${pendingApprovals === 1 ? '' : 's'} waiting` : verified ? 'Audit chain verified' : 'Checking audit chain'}
          </span>
          <button type="button" className="primary" onClick={() => onNavigate('playground')}>
            Open playground
          </button>
          <button type="button" className="overview-link" onClick={() => onNavigate(pendingApprovals ? 'approvals' : 'agents')}>
            {pendingApprovals ? 'Review approvals ›' : 'Run an agent ›'}
          </button>
        </div>
      </header>

      <Onboarding collections={collections} overview={overview} principal={principal} onNavigate={onNavigate} />

      <section className="overview-stage" aria-labelledby="overview-stage-title">
        <div className="overview-stage__head">
          <h2 id="overview-stage-title">Your intelligence stack</h2>
          <span className="overview-live">
            <i />
            Tenant isolated · {principal.tenant}
          </span>
        </div>
        <div className="stack-flow">
          {layers.map(([Icon, label, text, id]) => (
            <button type="button" key={id} onClick={() => onNavigate(id)}>
              <Icon size={22} strokeWidth={1.75} />
              <b>{label}</b>
              <span>{text}</span>
              <small>Open ›</small>
            </button>
          ))}
        </div>
        <div className="apple-metric-band">
          {figures.map(([label, value, trend]) => (
            <div key={label}>
              <span>{label}</span>
              <b>{value}</b>
              {trend && <Sparkline values={trend} label={`${label} per day, last 14 days`} />}
            </div>
          ))}
        </div>
      </section>

      <div className="grid">
        <Card
          className="span2"
          title="Recent runs"
          actions={
            <button type="button" className="link" onClick={() => onNavigate('jobs')}>
              View all <ArrowRight size={14} />
            </button>
          }
        >
          {overview.recent_jobs?.length ? (
            <div>
              {overview.recent_jobs.slice(0, 5).map((j: Row) => (
                <button type="button" className="list-row" key={j.id} onClick={() => onInspectRun(j)}>
                  <span className="run-icon">
                    <Activity size={16} />
                  </span>
                  <div>
                    <b>{j.name}</b>
                    <small>{time(j.created)}</small>
                  </div>
                  <Badge value={j.status} />
                </button>
              ))}
            </div>
          ) : (
            <ListEmpty
              icon={Activity}
              title="Ready for your first run"
              description="Try the knowledge investigator in Agents."
              action={
                <button type="button" className="primary" onClick={() => onNavigate('agents')}>
                  Run an agent
                </button>
              }
            />
          )}
        </Card>
        <Card title="Workspace posture">
          <div className="posture">
            <div>
              <ShieldCheck size={18} />
              <span>Audit chain integrity</span>
              <Badge value={verified ? 'verified' : 'unverified'} />
            </div>
            <div>
              <KeyRound size={18} />
              <span>Access boundary</span>
              <b>{principal.tenant}</b>
            </div>
            <div>
              <Wallet size={18} />
              <span>Recorded inference spend</span>
              <b>{money(overview.usage?.cost)}</b>
            </div>
          </div>
          <p className="note">Evaluation release. Offline demo results are synthetic. Connect a real provider to run model inference.</p>
        </Card>
        <Card
          className="span2"
          title="Inference, last 14 days"
          actions={
            <button type="button" className="link" onClick={() => onNavigate('usage')}>
              Usage & cost <ArrowRight size={14} />
            </button>
          }
        >
          {series ? (
            <AreaChart
              height={160}
              labels={days.map((d) => new Date(d.date + 'T00:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' }))}
              series={[
                { label: 'Requests', values: days.map((d) => d.requests), tone: 'blue' },
                { label: 'Cache hits', values: days.map((d) => d.cache_hits), tone: 'green' },
              ]}
              title="Requests and cache hits per day"
            />
          ) : null}
        </Card>
        <Card title="Run outcomes">
          {stats?.total ? (
            <>
              <Donut label={`${stats.total} runs by status`} parts={Object.entries(stats.by_status as Record<string, number>).map(([k, v]) => ({ label: k.replaceAll('_', ' '), value: v, tone: tones[k] || 'graphite' }))} />
              <p className="small muted">
                Median {stats.p50_seconds ?? '—'}s · p95 {stats.p95_seconds ?? '—'}s, {stats.timing}
              </p>
            </>
          ) : (
            <ListEmpty title="No runs yet" description="Outcomes appear after the first agent, workflow or evaluation run." />
          )}
        </Card>
      </div>
    </div>
  );
}
