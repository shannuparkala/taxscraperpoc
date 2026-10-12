import { api } from '../api/client';
import { useAction, useAsync } from '../hooks/useApi';
import {
  Badge, Card, Empty, ErrorBlock, LoadingBlock, Notice, humanize,
} from '../components/ui';

export default function SettingsPage() {
  const settings = useAsync(() => api.settings.get(), []);
  const health = useAsync(() => api.settings.health(), []);
  const pairs = useAsync(() => api.templates.pairs(), []);
  const templates = useAsync(() => api.templates.list(), []);

  const learn = useAction(api.templates.learn);
  const approve = useAction(api.templates.approve);
  const reject = useAction(api.templates.reject);

  if (settings.loading) return <LoadingBlock label="Loading settings…" />;
  if (settings.error) return <ErrorBlock message={settings.error} onRetry={settings.reload} />;
  const config = settings.data;
  if (!config) return null;

  return (
    <div className="stack">
      {/* Health */}
      <Card
        title="System health"
        actions={<button className="btn sm ghost" onClick={health.reload}>↻</button>}
      >
        <div className="grid cols-4" style={{ marginBottom: 14 }}>
          <Capability label="Database" ok={health.data?.database} />
          <Capability label="Vector store" ok={health.data?.vector_store} />
          <Capability
            label="Local OCR"
            ok={health.data?.ocr}
            hint={health.data?.ocr ? 'Tesseract available' : 'Tesseract not installed'}
          />
          <Capability
            label="Name detection"
            ok={health.data?.ner}
            hint={health.data?.ner ? 'spaCy model loaded' : 'spaCy model missing'}
          />
        </div>

        {health.data?.warnings.length ? (
          <div className="stack" style={{ gap: 8 }}>
            {health.data.warnings.map((warning, index) => (
              <Notice key={index} kind="warning">{warning}</Notice>
            ))}
          </div>
        ) : (
          <Notice kind="success">All systems nominal.</Notice>
        )}
      </Card>

      {/* Privacy posture — the most important panel on this page */}
      <Card title="Privacy and security posture">
        <div className="grid split-even">
          <dl className="detail-list">
            <dt>LLM egress guard</dt>
            <dd>
              <Badge tone={config.egress_guard_enabled ? 'success' : 'danger'}>
                {config.egress_guard_enabled ? `Enabled (${config.egress_guard_mode})` : 'DISABLED'}
              </Badge>
            </dd>

            <dt>Cloud OCR fallback</dt>
            <dd>
              <Badge tone={config.allow_cloud_ocr_fallback ? 'danger' : 'success'}>
                {config.allow_cloud_ocr_fallback ? 'Enabled — raw images may leave the host' : 'Disabled'}
              </Badge>
            </dd>

            <dt>Authentication</dt>
            <dd>
              <Badge tone={config.auth_disabled ? 'warning' : 'success'}>
                {config.auth_disabled ? 'Disabled (development)' : 'Enabled'}
              </Badge>
            </dd>

            <dt>Rate limiting</dt>
            <dd>
              <Badge tone={config.rate_limit_enabled ? 'success' : 'warning'}>
                {config.rate_limit_enabled ? 'Enabled' : 'Disabled'}
              </Badge>
            </dd>

            <dt>Environment</dt>
            <dd><Badge tone="neutral">{humanize(config.app_env)}</Badge></dd>
          </dl>

          <div>
            <Notice kind="privacy">
              <strong>What the model can see.</strong> Only masked content. The
              egress guard re-scans every outbound payload for unmasked
              identifiers and refuses to transmit when it finds any.
            </Notice>
            <div style={{ marginTop: 10 }}>
              <Notice kind="info">
                Secrets are never returned by the API — the Gemini key is
                reported only as configured or not. Change it in{' '}
                <span className="mono">backend/.env</span> and restart.
              </Notice>
            </div>
          </div>
        </div>
      </Card>

      {/* Model routing */}
      <Card title="AI model routing">
        <div className="grid split-even">
          <dl className="detail-list">
            <dt>Gemini API key</dt>
            <dd>
              <Badge tone={config.gemini_configured ? 'success' : 'warning'}>
                {config.gemini_configured ? 'Configured' : 'Not configured'}
              </Badge>
            </dd>
            <dt>Generation enabled</dt>
            <dd>
              <Badge tone={config.gemini_enabled ? 'success' : 'neutral'}>
                {config.gemini_enabled ? 'Yes' : 'No'}
              </Badge>
            </dd>
            <dt>Flash (default)</dt>
            <dd className="mono">{config.model_flash}</dd>
            <dt>Pro (escalation)</dt>
            <dd className="mono">{config.model_pro}</dd>
            <dt>Flash-Lite (batch)</dt>
            <dd className="mono">{config.model_flash_lite}</dd>
            <dt>Assistant</dt>
            <dd className="mono">{config.assistant_model} + Google Search grounding</dd>
          </dl>

          <div>
            <h3 style={{ marginBottom: 7 }}>Routing rules</h3>
            <table>
              <tbody>
                <tr><td>Assistant question</td><td><Badge tone="info">Assistant model + Search grounding</Badge></td></tr>
                <tr><td>Ambiguous handwriting</td><td><Badge tone="purple">Pro</Badge></td></tr>
                <tr><td>High-volume extraction</td><td><Badge tone="neutral">Flash-Lite</Badge></td></tr>
                <tr><td>Final tax position memo</td><td><Badge tone="purple">Pro</Badge></td></tr>
                <tr>
                  <td><strong>Any calculation</strong></td>
                  <td><Badge tone="success">Local tax engine — never a model</Badge></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </Card>

      {/* Template learning */}
      <Card
        title="Input-to-output template learning"
        actions={
          <button
            className="btn sm accent"
            disabled={learn.pending}
            onClick={async () => {
              await learn.run(20);
              templates.reload();
            }}
          >
            {learn.pending ? 'Analysing…' : '▶ Learn from sample corpus'}
          </button>
        }
      >
        <div className="stack">
          <div className="subtle">
            Corpus directory: <span className="mono">{config.tax_files_dir}</span>
            {pairs.data && ` · ${pairs.data.pair_count} input/output pair(s) discovered`}
          </div>

          {learn.error && <Notice kind="danger">{learn.error}</Notice>}

          {pairs.data?.pairs.length ? (
            <div>
              {pairs.data.pairs.map((pair) => (
                <span className="token-chip" key={pair.pair}>
                  {pair.pair} ({pair.input_ext})
                </span>
              ))}
            </div>
          ) : (
            <Notice kind="info">
              No pairs found. Set <span className="mono">TAX_FILES_DIR</span> to a
              folder where each workpaper has a matching output file whose name
              contains "copy".
            </Notice>
          )}

          {templates.data?.length ? (
            <table>
              <thead>
                <tr>
                  <th>Template</th><th>Input type</th><th className="num">Rules</th>
                  <th className="num">Pairs</th><th>Status</th><th />
                </tr>
              </thead>
              <tbody>
                {templates.data.map((template) => (
                  <tr key={template.id}>
                    <td style={{ fontWeight: 550 }}>{template.name}</td>
                    <td className="subtle">{humanize(template.input_document_type)}</td>
                    <td className="num">{template.rules.length}</td>
                    <td className="num">{template.pair_count}</td>
                    <td>
                      <Badge tone={
                        template.status === 'approved' ? 'success'
                        : template.status === 'rejected' ? 'danger' : 'warning'
                      }>
                        {humanize(template.status)}
                      </Badge>
                    </td>
                    <td style={{ width: 1, whiteSpace: 'nowrap' }}>
                      {template.status === 'proposed' && (
                        <>
                          <button
                            className="btn sm success"
                            disabled={approve.pending}
                            onClick={async () => { await approve.run(template.id); templates.reload(); }}
                          >
                            ✓ Approve
                          </button>{' '}
                          <button
                            className="btn sm ghost"
                            disabled={reject.pending}
                            onClick={async () => { await reject.run(template.id); templates.reload(); }}
                          >
                            ✕
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty
              title="No templates learned yet"
              hint="Run the analysis to infer field mappings from paired sample documents."
            />
          )}

          <Notice kind="warning">
            Learned templates start as proposals. Only an approved template
            influences a client's return.
          </Notice>
        </div>
      </Card>

      {/* Thresholds, storage, retention */}
      <div className="grid cols-3">
        <Card title="Confidence thresholds">
          <dl className="detail-list">
            <dt>Auto-approve at or above</dt>
            <dd>{Math.round(config.confidence_auto_approve * 100)}%</dd>
            <dt>Escalate below</dt>
            <dd>{Math.round(config.confidence_escalate * 100)}%</dd>
            <dt>Calculation tolerance</dt>
            <dd>${config.calc_tolerance_dollars.toFixed(2)}</dd>
          </dl>
          <div className="subtle" style={{ marginTop: 9 }}>
            Anything below auto-approve is routed to the review queue.
          </div>
        </Card>

        <Card title="File handling">
          <dl className="detail-list">
            <dt>Max upload size</dt>
            <dd>{config.max_upload_mb} MB</dd>
            <dt>Accepted types</dt>
            <dd className="mono" style={{ fontSize: 11.5 }}>
              {config.allowed_extensions.join(' ')}
            </dd>
          </dl>
          <div className="subtle" style={{ marginTop: 9 }}>
            Executables are rejected regardless of extension; content is verified
            against magic bytes.
          </div>
        </Card>

        <Card title="Retention policy">
          <dl className="detail-list">
            <dt>Raw documents</dt>
            <dd>{config.retention_raw_days} days ({(config.retention_raw_days / 365).toFixed(1)} yr)</dd>
            <dt>Masked artifacts</dt>
            <dd>{config.retention_masked_days} days</dd>
            <dt>Audit log</dt>
            <dd>{config.retention_audit_days} days</dd>
          </dl>
          <div className="subtle" style={{ marginTop: 9 }}>
            Raw retention defaults to seven years, matching IRS record
            requirements.
          </div>
        </Card>
      </div>

      <Card title="Tax year coverage">
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          {config.supported_tax_years.map((year) => (
            <Badge key={year} tone={config.verified_tax_years.includes(year) ? 'success' : 'warning'}>
              {year} {config.verified_tax_years.includes(year) ? '· verified' : '· provisional'}
            </Badge>
          ))}
        </div>
        <div style={{ marginTop: 10 }}>
          <Notice kind="warning">
            Provisional years use projected figures. Confirm them against the
            applicable IRS revenue procedure before filing.
          </Notice>
        </div>
      </Card>
    </div>
  );
}

function Capability({
  label, ok, hint,
}: { label: string; ok: boolean | undefined; hint?: string }) {
  return (
    <div>
      <div className="subtle">{label}</div>
      <div style={{ marginTop: 4 }}>
        <Badge tone={ok === undefined ? 'neutral' : ok ? 'success' : 'warning'}>
          {ok === undefined ? 'Checking…' : ok ? '✓ Available' : '✕ Unavailable'}
        </Badge>
      </div>
      {hint && <div className="subtle" style={{ marginTop: 3 }}>{hint}</div>}
    </div>
  );
}
