// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { Gauge, Play } from 'lucide-react';
import { api, type Row } from '../api';
import { AreaChart, Sparkline } from '../components/charts';
import ResourceTable from '../components/ResourceTable';
import type { Act } from '../lib/types';

// Completed evaluation runs for one suite, oldest first.
export function scoreHistory(jobs: Row[], evaluationId: string): Row[] {
  return jobs
    .filter((j) => j.type === 'evaluation' && j.target === evaluationId && j.status === 'completed' && typeof j.result?.score === 'number')
    .sort((a, b) => a.created - b.created);
}

export function ScoreTrend({ runs }: { runs: Row[] }) {
  if (!runs.length) return <p className="small muted">No completed runs yet. Run this suite to start a score trend.</p>;
  const last = runs[runs.length - 1].result;
  return (
    <div className="score-trend">
      <p className="verdict">
        <b className={last.release_allowed ? 'green' : 'red'}>{Math.round(last.score * 100)}%</b>
        <span>
          latest score · {last.release_allowed ? 'release allowed' : 'release blocked'} · {runs.length} run{runs.length === 1 ? '' : 's'}
        </span>
      </p>
      {runs.length > 1 && (
        <AreaChart
          height={140}
          labels={runs.map((r) => new Date(r.created * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }))}
          series={[{ label: 'Score', values: runs.map((r) => Math.round(r.result.score * 100)), tone: 'green' }]}
          format={(v) => `${v}%`}
          title="Evaluation score per run"
        />
      )}
    </div>
  );
}

export default function Evaluations({ rows, jobs = [], canWrite, act, onQueued }: { rows: Row[]; jobs?: Row[]; canWrite: boolean; act: Act; onQueued: () => void }) {
  return (
    <ResourceTable
      rows={rows}
      columns={['name', 'model', 'cases', 'pass_threshold']}
      emptyIcon={Gauge}
      emptyTitle="Measure before you promote"
      emptyText="An evaluation suite checks answers with phrase assertions, an LLM judge and groundedness against your knowledge, then gives a release verdict."
      renderAction={(r) => {
        const runs = scoreHistory(jobs, r.id);
        const last = runs[runs.length - 1]?.result;
        return (
          <span className="eval-action">
            {runs.length > 1 && <Sparkline values={runs.map((j) => j.result.score)} label={`${r.name} score trend`} width={72} height={24} />}
            {last && <b className={last.release_allowed ? 'green' : 'red'}>{Math.round(last.score * 100)}%</b>}
            <button
              type="button"
              className="btn-secondary"
              disabled={!canWrite}
              onClick={() => act(() => api('/api/evaluations/' + r.id + '/run', {})).then((j) => j && onQueued())}
            >
              <Play size={14} />
              Evaluate
            </button>
          </span>
        );
      }}
    />
  );
}
