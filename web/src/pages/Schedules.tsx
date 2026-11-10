// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { CalendarClock, Play } from 'lucide-react';
import { api, type Row } from '../api';
import ResourceTable from '../components/ResourceTable';
import type { Act } from '../lib/types';

export default function Schedules({ rows, canWrite, act }: { rows: Row[]; canWrite: boolean; act: Act }) {
  return (
    <ResourceTable
      rows={rows}
      columns={['name', 'agent', 'every_minutes', 'cron', 'enabled', 'last_run']}
      emptyIcon={CalendarClock}
      emptyTitle="No schedules yet"
      emptyText="Run an agent on an interval or a 5-field cron. The worker checks about once a minute and enqueues due runs."
      renderAction={(r) => (
        <button type="button" className="btn-secondary" disabled={!canWrite} onClick={() => act(() => api('/api/schedules/' + r.id + '/run', {}), 'Schedule queued')}>
          <Play size={14} />
          Run now
        </button>
      )}
    />
  );
}
