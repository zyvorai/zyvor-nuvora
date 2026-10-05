import { Activity, ArrowRight, BookOpen, Bot, Cpu, KeyRound, ShieldCheck, Wallet } from 'lucide-react';
import { money, time, type Row } from '../api';
import { Badge, Card, ListEmpty } from '../components/kit';
import type { Page } from '../lib/navGroups';

const layers: [typeof Cpu, string, string, Page][] = [
  [Cpu, 'Model layer', 'Local, hosted, or your own endpoint', 'models'],
  [BookOpen, 'Knowledge layer', 'Retrieved evidence with source digests', 'knowledge'],
  [Bot, 'Agent layer', 'Registered tools and bounded execution', 'agents'],
  [ShieldCheck, 'Control layer', 'Separate approval and audit evidence', 'approvals'],
];

export default function Overview({
  overview,
  principal,
  pendingApprovals,
  onNavigate,
  onInspectRun,
}: {
  overview: Row;
  principal: Row;
  pendingApprovals: number;
  onNavigate: (p: Page) => void;
  onInspectRun: (run: Row) => void;
}) {
  const verified = Boolean(overview.audit?.valid);
  const figures: [string, string | number][] = [
    ['Models', overview.counts?.models || 0],
    ['Knowledge bases', overview.counts?.knowledge || 0],
    ['Agent runs', overview.counts?.jobs || 0],
    ['Tokens', overview.usage?.tokens?.toLocaleString() || 0],
  ];
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
          {figures.map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              <b>{value}</b>
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
            <ListEmpty title="Ready for your first run" description="Try the knowledge investigator in Agents." />
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
      </div>
    </div>
  );
}
