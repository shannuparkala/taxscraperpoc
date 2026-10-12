import { useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import { useAsync } from '../hooks/useApi';
import {
  BarChart, Badge, Card, Empty, ErrorBlock, Kpi, LoadingBlock, Notice,
  formatBytes, formatRelative, humanize, statusTone,
} from '../components/ui';

export default function DashboardPage() {
  const navigate = useNavigate();
  const { data, loading, error, reload } = useAsync(() => api.dashboard.summary(), []);

  if (loading) return <LoadingBlock label="Loading dashboard…" />;
  if (error) return <ErrorBlock message={error} onRetry={reload} />;
  if (!data) return null;

  const activeStatuses = data.by_status.filter((s) => s.count > 0);
  const activeTypes = data.by_filing_type.filter((t) => t.count > 0);

  return (
    <div className="stack">
      {/* Quick actions */}
      <div className="toolbar">
        <button className="btn primary" onClick={() => navigate('/workpapers')}>
          ⬆ Upload tax workpaper
        </button>
        <button className="btn" onClick={() => navigate('/chat')}>
          ◈ Ask tax query
        </button>
        <button className="btn" onClick={() => navigate('/review')}>
          ◐ Review generated output
        </button>
        <button className="btn" onClick={() => navigate('/workpapers')}>
          ⬇ Download completed package
        </button>
        <div className="spacer" />
        <button className="btn ghost sm" onClick={reload}>↻ Refresh</button>
      </div>

      {/* KPIs */}
      <div className="grid cols-4">
        <Kpi
          label="Total returns"
          value={data.total_returns}
          hint={`${data.total_filed} filed`}
        />
        <Kpi
          label="Documents processed"
          value={data.documents_processed}
          hint={`${data.workflows_running} workflow(s) running`}
          tone="accent"
        />
        <Kpi
          label="Values masked"
          value={data.pii_entities_masked.toLocaleString()}
          hint="Never sent to the AI model"
          tone="accent"
        />
        <Kpi
          label="Open exceptions"
          value={data.open_review_items}
          hint={`${data.workflows_awaiting_review} workflow(s) awaiting review`}
          tone={data.open_review_items > 0 ? 'warn' : ''}
        />
      </div>

      <Notice kind="privacy">
        <strong>Privacy model.</strong> Uploaded documents are encrypted at rest.
        Sensitive values are replaced with synthetic substitutes before any AI
        processing, and real values are restored locally only when the final
        output package is generated. The language model never receives real
        taxpayer data.
      </Notice>

      {/* Status breakdowns */}
      <div className="grid cols-3">
        <Card title="Returns by status">
          {activeStatuses.length ? (
            <BarChart
              data={activeStatuses.map((s) => ({ label: s.label, count: s.count }))}
              tone={(label) =>
                label === 'Filed' ? 'success'
                : label === 'Rejected' ? 'danger'
                : label === 'In Review' ? 'warning'
                : ''
              }
            />
          ) : (
            <Empty title="No filings yet" hint="Create a filing to see status here." />
          )}
        </Card>

        <Card title="Returns by filing type">
          {activeTypes.length ? (
            <BarChart data={activeTypes.map((t) => ({ label: t.label, count: t.count }))} />
          ) : (
            <Empty title="No filings yet" />
          )}
        </Card>

        <Card title="Returns by tax year">
          {data.by_tax_year.length ? (
            <BarChart data={data.by_tax_year.map((y) => ({ label: y.label, count: y.count }))} />
          ) : (
            <Empty title="No filings yet" />
          )}
        </Card>
      </div>

      {/* Confidence + exceptions */}
      <div className="grid split-even">
        <Card title="Extraction confidence distribution">
          {data.confidence_distribution.some((b) => b.count > 0) ? (
            <>
              <BarChart
                data={data.confidence_distribution.map((b) => ({
                  label: b.label, count: b.count,
                }))}
                tone={(label) =>
                  label.startsWith('Very high') || label.startsWith('High') ? 'success'
                  : label.startsWith('Medium') ? 'warning'
                  : 'danger'
                }
              />
              <div className="subtle" style={{ marginTop: 10 }}>
                Fields below the auto-approve threshold are routed to the review
                queue rather than accepted automatically.
              </div>
            </>
          ) : (
            <Empty
              title="No extractions yet"
              hint="Process a workpaper to populate this chart."
            />
          )}
        </Card>

        <Card
          title="Workflow exceptions"
          actions={
            data.exceptions.length > 0 ? (
              <button className="btn sm" onClick={() => navigate('/review')}>
                Open queue
              </button>
            ) : undefined
          }
        >
          {data.exceptions.length ? (
            <div className="stack" style={{ gap: 8 }}>
              {data.exceptions.slice(0, 6).map((item) => (
                <div key={item.id} className="row" style={{ alignItems: 'flex-start' }}>
                  <Badge tone={item.priority <= 2 ? 'danger' : 'warning'}>
                    P{item.priority}
                  </Badge>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div className="truncate" style={{ fontWeight: 550 }}>{item.title}</div>
                    <div className="subtle">
                      {humanize(item.reason)} · {formatRelative(item.created_at)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <Empty icon="✓" title="No open exceptions" hint="Everything has been reviewed." />
          )}
        </Card>
      </div>

      {/* Recent activity */}
      <div className="grid cols-3">
        <Card title="Recent uploads" bodyClass="tight">
          {data.recent_uploads.length ? (
            <table>
              <tbody>
                {data.recent_uploads.map((file) => (
                  <tr key={file.id}>
                    <td>
                      <div className="truncate" style={{ maxWidth: 180 }} title={file.original_filename}>
                        {file.original_filename}
                      </div>
                      <div className="subtle">
                        {formatBytes(file.size_bytes)} · {formatRelative(file.created_at)}
                      </div>
                    </td>
                    <td style={{ width: 1 }}>
                      <Badge tone={statusTone(file.status)}>{humanize(file.status)}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty title="No uploads yet" hint="Upload a workpaper to begin." />
          )}
        </Card>

        <Card title="Recent chatbot questions" bodyClass="tight">
          {data.recent_chats.length ? (
            <table>
              <tbody>
                {data.recent_chats.map((chat) => (
                  <tr key={chat.id} className="clickable" onClick={() => navigate('/chat')}>
                    <td>
                      <div className="truncate" style={{ maxWidth: 220 }} title={chat.question}>
                        {chat.question}
                      </div>
                      <div className="subtle">{formatRelative(chat.created_at)}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty title="No questions yet" hint="Ask the tax chatbot a question." />
          )}
        </Card>

        <Card
          title="Audit trail preview"
          actions={<button className="btn sm" onClick={() => navigate('/audit')}>View all</button>}
          bodyClass="tight"
        >
          {data.audit_preview.length ? (
            <table>
              <tbody>
                {data.audit_preview.map((event) => (
                  <tr key={event.sequence}>
                    <td>
                      <div className="mono truncate" style={{ maxWidth: 190 }}>
                        {event.action}
                      </div>
                      <div className="subtle">{formatRelative(event.occurred_at)}</div>
                    </td>
                    <td style={{ width: 1 }}>
                      {event.severity !== 'info' && (
                        <Badge tone={event.severity === 'critical' ? 'danger' : 'warning'}>
                          {event.severity}
                        </Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty title="No events yet" />
          )}
        </Card>
      </div>

      <div className="subtle" style={{ textAlign: 'right' }}>
        {data.knowledge_sources} knowledge source(s) indexed ·
        Generated {formatRelative(data.generated_at)}
      </div>
    </div>
  );
}
