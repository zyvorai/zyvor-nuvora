// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { Send, Webhook } from 'lucide-react';
import { api, type Row } from '../api';
import ResourceTable from '../components/ResourceTable';
import type { Act } from '../lib/types';

export default function Webhooks({ rows, isAdmin, act }: { rows: Row[]; isAdmin: boolean; act: Act }) {
  return (
    <ResourceTable
      rows={rows}
      columns={['name', 'url', 'format', 'events', 'enabled', 'last_status']}
      emptyIcon={Webhook}
      emptyTitle="No webhooks yet"
      emptyText="HMAC-signed POSTs (or Slack/Teams/email shapes) for jobs, approvals, ingest, sync and guardrail blocks."
      renderAction={(r) => (
        <button type="button" className="btn-secondary" disabled={!isAdmin} onClick={() => act(() => api('/api/webhooks/' + r.id + '/test', {}), 'Test delivery sent')}>
          <Send size={14} />
          Test
        </button>
      )}
    />
  );
}
