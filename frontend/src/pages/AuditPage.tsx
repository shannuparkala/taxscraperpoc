import { useState } from 'react';

import { api } from '../api/client';
import { useAction, useAsync } from '../hooks/useApi';
import {
  Badge, Card, Empty, ErrorBlock, Kpi, LoadingBlock, Notice,
  formatDate, formatRelative, humanize,
} from '../components/ui';

export default function AuditPage() {
  const [actionFilter, setActionFilter] = useState('');
  const [severityFilter, setSeverityFilter] = useState('');

  const events = useAsync(
    () => api.audit.events({
      action: actionFilter || undefined,
      severity: severityFilter || undefined,
      limit: 300,
    }),
    [actionFilter, severityFilter],
  );
  const actions = useAsync(() => api.audit.actions(), []);
  const verify = useAction(api.audit.verify);
  const [verifyResult, setVerifyResult] = useState<{
    chain_valid: boolean; events_checked: number; message: string;
  } | null>(null);

  const severityCounts = events.data?.items.reduce<Record<string, number>>((acc, e) => {
    acc[e.severity] = (acc[e.severity] ?? 0) + 1;
    return acc;
  }, {}) ?? {};

  return (
    <div className="stack">
      <div className="grid cols-4">
        <Kpi label="Events shown" value={events.data?.items.length ?? '—'} hint={`${events.data?.total ?? 0} total`} />
        <Kpi label="Critical" value={severityCounts.critical ?? 0} tone={severityCounts.critical ? 'danger' : ''} />
        <Kpi label="Warnings" value={severityCounts.warning ?? 0} tone={severityCounts.warning ? 'warn' : ''} />
        <Kpi
          label="Chain integrity"
          value={verifyResult ? (verifyResult.chain_valid ? 'Intact' : 'BROKEN') : 'Not checked'}
          hint={verifyResult ? `${verifyResult.events_checked} events verified` : 'Run a verification'}
          tone={verifyResult && !verifyResult.chain_valid ? 'danger' : verifyResult ? 'accent' : ''}
        />
      </div>

      <Notice kind="privacy">
        <strong>Audit events contain no client data.</strong> Payloads carry mask
        tokens, counters, and hashes only — never names, identifiers, or amounts
        tied to a person. Every event is hash-chained to its predecessor, so
        altering or deleting one is detectable.
      </Notice>

      {verifyResult && (
        <Notice kind={verifyResult.chain_valid ? 'success' : 'danger'}>
          {verifyResult.message}
        </Notice>
      )}

      <div className="toolbar">
        <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}>
          <option value="">All severities</option>
          <option value="info">Info</option>
          <option value="warning">Warning</option>
          <option value="critical">Critical</option>
        </select>

        <select value={actionFilter} onChange={(e) => setActionFilter(e.target.value)}>
          <option value="">All actions</option>
          {Object.entries(actions.data ?? {}).map(([action, count]) => (
            <option key={action} value={action}>{action} ({count})</option>
          ))}
        </select>

        <div className="spacer" />

        <button
          className="btn"
          disabled={verify.pending}
          onClick={async () => {
            const result = await verify.run();
            if (result) setVerifyResult(result);
          }}
        >
          {verify.pending ? 'Verifying…' : '🔗 Verify hash chain'}
        </button>
        <button className="btn ghost sm" onClick={events.reload}>↻</button>
      </div>

      <Card bodyClass="tight">
        {events.loading ? <LoadingBlock label="Loading audit trail…" />
          : events.error ? <ErrorBlock message={events.error} onRetry={events.reload} />
          : !events.data?.items.length ? (
            <Empty title="No audit events" hint="Events appear as soon as files are uploaded or processed." />
          ) : (
            <table>
              <thead>
                <tr>
                  <th className="num">Seq</th>
                  <th>Action</th>
                  <th>Severity</th>
                  <th>Entity</th>
                  <th>Detail</th>
                  <th>When</th>
                  <th>Hash</th>
                </tr>
              </thead>
              <tbody>
                {events.data.items.map((event) => (
                  <tr key={event.id}>
                    <td className="num mono">{event.sequence}</td>
                    <td className="mono" style={{ fontWeight: 550 }}>{event.action}</td>
                    <td>
                      {event.severity === 'info'
                        ? <span className="subtle">info</span>
                        : (
                          <Badge tone={event.severity === 'critical' ? 'danger' : 'warning'}>
                            {event.severity}
                          </Badge>
                        )}
                    </td>
                    <td className="subtle">
                      {event.entity_type ? humanize(event.entity_type) : '—'}
                      {event.entity_id && (
                        <div className="mono subtle">{event.entity_id.slice(0, 8)}</div>
                      )}
                    </td>
                    <td>
                      <PayloadCell payload={event.payload} />
                    </td>
                    <td className="subtle" title={formatDate(event.occurred_at)}>
                      {formatRelative(event.occurred_at)}
                    </td>
                    <td className="mono subtle">{event.event_hash.slice(0, 8)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </Card>
    </div>
  );
}

function PayloadCell({ payload }: { payload: Record<string, unknown> | null }) {
  if (!payload || Object.keys(payload).length === 0) {
    return <span className="subtle">—</span>;
  }
  const entries = Object.entries(payload).slice(0, 4);
  return (
    <div style={{ fontSize: 11.5 }}>
      {entries.map(([key, value]) => (
        <span key={key} className="token-chip">
          {key}: {formatValue(value)}
        </span>
      ))}
    </div>
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') {
    const text = JSON.stringify(value);
    return text.length > 40 ? `${text.slice(0, 40)}…` : text;
  }
  const text = String(value);
  return text.length > 40 ? `${text.slice(0, 40)}…` : text;
}
