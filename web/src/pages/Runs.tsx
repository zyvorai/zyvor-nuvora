// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { useState } from 'react';
import { Activity, ArrowRight, Bot, CheckCircle2, CircleDashed, Clock3, Download, ShieldCheck, Wrench, XCircle } from 'lucide-react';
import { ago, api, download, money, time, type Row } from '../api';
import { Badge, Card } from '../components/kit';
import ResourceTable from '../components/ResourceTable';
import WorkflowCanvas, { stepStatuses } from '../components/WorkflowCanvas';
import { CaseResults } from '../components/CaseEditor';
import type { Act } from '../lib/types';

type Entry = { key: string; icon: typeof Activity; tone: string; title: string; detail?: string; status: string };

function timeline(run: Row): Entry[] {
  if (run.type === 'workflow') {
    const status = stepStatuses(run);
    return (run.spec?.steps || []).map((s: Row) => {
      const st = status[s.id] || (run.status === 'completed' ? 'completed' : 'pending');
      return {
        key: s.id,
        icon: st === 'completed' ? CheckCircle2 : st === 'waiting' ? Clock3 : st === 'failed' ? XCircle : CircleDashed,
        tone: st === 'completed' ? 'green' : st === 'waiting' ? 'amber' : st === 'failed' ? 'red' : 'graphite',
        title: s.id,
        detail: s.type,
        status: st,
      };
    });
  }
  if (run.type === 'evaluation') {
    return (run.result?.cases || []).map((c: Row, i: number) => ({
      key: String(i),
      icon: c.passed ? CheckCircle2 : XCircle,
      tone: c.passed ? 'green' : 'red',
      title: `Case ${i + 1}`,
      detail: c.input,
      status: c.passed ? 'passed' : 'failed',
    }));
  }
  return (run.trace || []).map((t: Row, i: number) => ({
    key: String(i),
    icon: t.type === 'tool' ? Wrench : t.type === 'model' ? Bot : Activity,
    tone: t.type === 'tool' ? 'purple' : 'blue',
    title: t.type === 'tool' ? `Tool · ${String(t.tool || '').replaceAll('_', ' ')}` : t.type === 'model' ? `Model call ${t.step}` : String(t.step ?? t.type ?? 'Step'),
    detail: t.type === 'model' ? [t.evidence_class, t.cost != null ? money(t.cost) : ''].filter(Boolean).join(' · ') : t.error || t.status,
    status: t.error ? 'failed' : 'completed',
  }));
}

function Inspector({ run, approvals, principal, canApprove, act }: { run: Row; approvals: Row[]; principal: Row; canApprove: boolean; act: Act }) {
  const [raw, setRaw] = useState(false);
  const approval = run.status === 'waiting_approval' ? approvals.find((a) => a.id === run.checkpoint?.approval && a.status === 'pending') : undefined;
  const own = approval?.proposer === principal.username;
  const entries = timeline(run);
  const answer = run.result?.answer;
  return (
    <Card
      title="Run evidence"
      eyebrow={run.name}
      actions={
        <button type="button" className="btn-secondary" onClick={() => download('nuvora-run-' + run.id + '.json', run)}>
          <Download size={15} />
          Export evidence
        </button>
      }
    >
      <div className="run-head">
        <Badge value={run.status} />
        <span className="small muted">
          {run.type} · queued {ago(run.created)} · updated <span title={time(run.updated)}>{ago(run.updated)}</span> · <code>{run.id}</code>
        </span>
      </div>

      {approval && (
        <div className="approval-inline" role="region" aria-label="Approval required">
          <ShieldCheck size={20} aria-hidden="true" />
          <div>
            <b>{approval.name}</b>
            <span>
              Proposed by {approval.proposer} · expires {time(approval.expires)} · digest <code>{String(approval.digest).slice(0, 12)}…</code>
            </span>
            {approval.action?.preview && <pre className="approval-inline__preview">{String(approval.action.preview).slice(0, 600)}</pre>}
          </div>
          {canApprove && !own ? (
            <span className="approval-inline__actions">
              <button type="button" className="primary compact" onClick={() => act(() => api(`/api/approvals/${approval.id}/decide`, { decision: 'approved', digest: approval.digest }), 'Approved · run resumed')}>
                Approve
              </button>
              <button type="button" className="btn-secondary compact danger-text" onClick={() => act(() => api(`/api/approvals/${approval.id}/decide`, { decision: 'rejected', digest: approval.digest }), 'Rejected · run stopped')}>
                Reject
              </button>
            </span>
          ) : (
            <span className="small muted">{own ? 'You proposed this; a different person must decide.' : 'An approver must decide.'}</span>
          )}
        </div>
      )}

      {run.type === 'workflow' && run.spec?.steps && <WorkflowCanvas steps={run.spec.steps} status={stepStatuses(run)} label="Run progress" />}

      {run.type === 'evaluation' && run.result && (
        <div className="verdict">
          <b className={run.result.release_allowed ? 'green' : 'red'}>{run.result.release_allowed ? 'Release allowed' : 'Release blocked'}</b>
          <span>
            Score {Math.round((run.result.score || 0) * 100)}% · threshold {Math.round((run.result.threshold || 0) * 100)}% · {run.result.grading}
          </span>
        </div>
      )}

      {run.type === 'evaluation' && run.result?.cases?.length > 0 && <CaseResults cases={run.result.cases} />}

      {entries.length > 0 && run.type !== 'evaluation' && (
        <ol className="timeline" aria-label="Run steps">
          {entries.map((e) => (
            <li key={e.key}>
              <span className={'timeline__dot ' + e.tone}>
                <e.icon size={14} aria-hidden="true" />
              </span>
              <div>
                <b>{e.title}</b>
                {e.detail && <span>{e.detail}</span>}
              </div>
              <Badge value={e.status} />
            </li>
          ))}
        </ol>
      )}

      {answer && (
        <div className="answer">
          <h3>Answer</h3>
          <p>{answer}</p>
        </div>
      )}
      {run.result?.error && (
        <p role="alert" className="error">
          {run.result.error}
        </p>
      )}

      <button type="button" className="link" aria-expanded={raw} onClick={() => setRaw((r) => !r)}>
        {raw ? 'Hide' : 'Show'} full evidence JSON
      </button>
      {raw && <pre className="code-block">{JSON.stringify(run, null, 2)}</pre>}
    </Card>
  );
}

export default function Runs({
  rows,
  focus,
  approvals = [],
  principal,
  canApprove = false,
  act,
}: {
  rows: Row[];
  focus?: string;
  approvals?: Row[];
  principal: Row;
  canApprove?: boolean;
  act: Act;
}) {
  const [selected, setSelected] = useState<string | undefined>(focus);
  const run = rows.find((j) => j.id === selected);
  return (
    <div className="stack-page">
      <ResourceTable
        rows={rows}
        columns={['name', 'type', 'status', 'created']}
        onRow={(r) => setSelected(r.id)}
        emptyTitle="No runs yet"
        emptyText="Run an agent, workflow, evaluation or batch to see its evidence here."
        emptyIcon={Activity}
        emptyAction={
          <>
            <a className="buttonlike primary" href="#agents">
              Run an agent
            </a>
            <a className="buttonlike btn-secondary" href="#workflows">
              Start a workflow
            </a>
          </>
        }
        renderAction={(r) => (
          <button type="button" className="link" onClick={() => setSelected(r.id)}>
            Inspect <ArrowRight size={14} />
          </button>
        )}
      />
      {run && <Inspector run={run} approvals={approvals} principal={principal} canApprove={canApprove} act={act} />}
    </div>
  );
}
