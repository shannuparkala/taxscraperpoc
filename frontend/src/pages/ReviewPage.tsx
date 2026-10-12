import { useState } from 'react';

import { api, type ReviewItem } from '../api/client';
import { useAction, useAsync } from '../hooks/useApi';
import {
  Badge, Card, ConfidenceMeter, Empty, ErrorBlock, LoadingBlock, Notice,
  formatRelative, humanize, statusTone,
} from '../components/ui';

const REASON_HELP: Record<string, string> = {
  low_confidence: 'The extraction scored below the auto-approve threshold.',
  handwriting_uncertain: 'Handwritten content — OCR flagged low character confidence.',
  ocr_unavailable: 'No text layer and no local OCR engine; the page could not be read.',
  tax_ambiguity: 'More than one defensible tax treatment applies.',
  source_conflict: 'Two source documents disagree on this value.',
  missing_required_data: 'A field required to complete the return is absent.',
  calculation_mismatch: 'A recomputation disagreed with the extracted figure.',
  unmasked_pii_suspected: 'Masking may be incomplete — verify before releasing output.',
  template_approval: 'A learned transformation template needs sign-off.',
  schema_violation: 'The model returned a malformed response.',
  material_amount: 'The amount is material enough to warrant a second look.',
};

export default function ReviewPage() {
  const [statusFilter, setStatusFilter] = useState('pending');
  const [selected, setSelected] = useState<ReviewItem | null>(null);

  const queue = useAsync(() => api.review.queue(statusFilter), [statusFilter]);

  return (
    <div className="stack">
      <div className="toolbar">
        {['pending', 'approved', 'rejected', 'edited'].map((status) => (
          <button
            key={status}
            className={`btn sm ${statusFilter === status ? 'primary' : ''}`}
            onClick={() => { setStatusFilter(status); setSelected(null); }}
          >
            {humanize(status)}
          </button>
        ))}
        <div className="spacer" />
        {queue.data && (
          <span className="subtle">
            {queue.data.pending} pending of {queue.data.total} total
          </span>
        )}
        <button className="btn sm ghost" onClick={queue.reload}>↻</button>
      </div>

      {queue.loading ? <LoadingBlock label="Loading review queue…" />
        : queue.error ? <ErrorBlock message={queue.error} onRetry={queue.reload} />
        : !queue.data?.items.length ? (
          <Card>
            <Empty
              icon="✓"
              title={`No ${statusFilter} items`}
              hint={
                statusFilter === 'pending'
                  ? 'Everything has been reviewed. Items appear here when confidence is low or a validation check fails.'
                  : 'Nothing in this category yet.'
              }
            />
          </Card>
        ) : (
          <div className="grid sidebar-split">
            <Card title={`${humanize(statusFilter)} items`} bodyClass="tight">
              <table>
                <thead>
                  <tr>
                    <th>Priority</th><th>Item</th><th>Reason</th>
                    <th>Confidence</th><th>Raised</th>
                  </tr>
                </thead>
                <tbody>
                  {queue.data.items.map((item) => (
                    <tr
                      key={item.id}
                      className="clickable"
                      onClick={() => setSelected(item)}
                      style={selected?.id === item.id
                        ? { background: 'var(--accent-light)' } : undefined}
                    >
                      <td>
                        <Badge tone={item.priority <= 2 ? 'danger' : 'neutral'}>
                          P{item.priority}
                        </Badge>
                      </td>
                      <td>
                        <div style={{ fontWeight: 550 }}>{item.title}</div>
                        {item.field_name && (
                          <div className="subtle mono">{item.field_name}</div>
                        )}
                      </td>
                      <td><Badge tone="warning">{humanize(item.reason)}</Badge></td>
                      <td><ConfidenceMeter value={item.confidence} /></td>
                      <td className="subtle">{formatRelative(item.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>

            {selected ? (
              <ReviewDetail
                item={selected}
                onDone={() => { setSelected(null); queue.reload(); }}
              />
            ) : (
              <Card title="Review detail">
                <Empty title="Select an item" hint="Choose a row to inspect and decide." />
              </Card>
            )}
          </div>
        )}
    </div>
  );
}

function ReviewDetail({ item, onDone }: { item: ReviewItem; onDone: () => void }) {
  const [notes, setNotes] = useState('');
  const [corrected, setCorrected] = useState(item.proposed_value ?? '');
  const [mode, setMode] = useState<'view' | 'edit'>('view');

  const approve = useAction(api.review.approve);
  const reject = useAction(api.review.reject);
  const edit = useAction(api.review.edit);

  const pending = approve.pending || reject.pending || edit.pending;
  const decided = item.status !== 'pending';
  const error = approve.error ?? reject.error ?? edit.error;

  return (
    <Card title="Review detail">
      <div className="stack">
        <div>
          <h3>{item.title}</h3>
          <div className="row" style={{ gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
            <Badge tone={statusTone(item.status)}>{humanize(item.status)}</Badge>
            <Badge tone="warning">{humanize(item.reason)}</Badge>
            <Badge tone={item.priority <= 2 ? 'danger' : 'neutral'}>
              Priority {item.priority}
            </Badge>
          </div>
        </div>

        <Notice kind="info">{REASON_HELP[item.reason] ?? item.description ?? ''}</Notice>

        {item.description && item.description !== REASON_HELP[item.reason] && (
          <div>
            <div className="subtle" style={{ marginBottom: 3 }}>Detail</div>
            <div style={{ fontSize: 13 }}>{item.description}</div>
          </div>
        )}

        <dl className="detail-list">
          <dt>Field</dt>
          <dd className="mono">{item.field_name ?? '—'}</dd>
          <dt>Confidence</dt>
          <dd><ConfidenceMeter value={item.confidence} /></dd>
          <dt>Source page</dt>
          <dd>{item.source_page ?? '—'}</dd>
          <dt>Raised</dt>
          <dd>{formatRelative(item.created_at)}</dd>
        </dl>

        {/* Side-by-side: source snippet vs proposed output */}
        <div className="side-by-side">
          <div>
            <div className="subtle" style={{ marginBottom: 5 }}>
              Source (masked)
            </div>
            <div className="masked-preview" style={{ maxHeight: 190 }}>
              {item.masked_source_snippet || '(no snippet captured)'}
            </div>
          </div>
          <div>
            <div className="subtle" style={{ marginBottom: 5 }}>
              Proposed output value
            </div>
            {mode === 'edit' ? (
              <textarea
                value={corrected}
                onChange={(e) => setCorrected(e.target.value)}
                style={{ minHeight: 190 }}
              />
            ) : (
              <div className="masked-preview" style={{ maxHeight: 190 }}>
                {item.corrected_value || item.proposed_value || '(none proposed)'}
              </div>
            )}
          </div>
        </div>

        <Notice kind="privacy">
          Values shown are masked substitutes. Real values are restored only when
          the final output package is generated.
        </Notice>

        {!decided && (
          <>
            <div className="field">
              <label>Reviewer notes</label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Why are you approving, editing, or rejecting this?"
                style={{ minHeight: 62 }}
              />
            </div>

            {error && <Notice kind="danger">{error}</Notice>}

            <div className="row" style={{ gap: 8 }}>
              {mode === 'view' ? (
                <>
                  <button
                    className="btn success"
                    disabled={pending}
                    onClick={async () => {
                      if (await approve.run(item.id, notes)) onDone();
                    }}
                  >
                    ✓ Approve
                  </button>
                  <button className="btn" disabled={pending} onClick={() => setMode('edit')}>
                    ✎ Edit value
                  </button>
                  <button
                    className="btn danger"
                    disabled={pending}
                    onClick={async () => {
                      if (await reject.run(item.id, notes)) onDone();
                    }}
                  >
                    ✕ Reject
                  </button>
                </>
              ) : (
                <>
                  <button
                    className="btn accent"
                    disabled={pending}
                    onClick={async () => {
                      if (await edit.run(item.id, corrected, notes)) onDone();
                    }}
                  >
                    ✓ Save correction
                  </button>
                  <button className="btn ghost" disabled={pending} onClick={() => setMode('view')}>
                    Cancel
                  </button>
                </>
              )}
            </div>
          </>
        )}

        {decided && (
          <Notice kind="success">
            Decided: <strong>{humanize(item.status)}</strong>
            {item.reviewed_at && ` · ${formatRelative(item.reviewed_at)}`}
            {item.reviewer_notes && <div style={{ marginTop: 4 }}>{item.reviewer_notes}</div>}
          </Notice>
        )}
      </div>
    </Card>
  );
}
