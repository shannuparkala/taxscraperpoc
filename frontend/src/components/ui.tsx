/** Shared presentational components. */

import type { ReactNode } from 'react';

// ---------------------------------------------------------------- primitives

export function Card({
  title, subtitle, actions, children, bodyClass = '',
}: {
  title?: string; subtitle?: string; actions?: ReactNode;
  children: ReactNode; bodyClass?: string;
}) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="card-header">
          {title && (
            <div className="card-heading">
              <h2>{title}</h2>
              {subtitle && <div className="card-subtitle">{subtitle}</div>}
            </div>
          )}
          {actions && <div className="header-actions">{actions}</div>}
        </div>
      )}
      <div className={`card-body ${bodyClass}`}>{children}</div>
    </section>
  );
}

export function Kpi({
  label, value, hint, tone = '',
}: {
  label: string; value: ReactNode; hint?: string; tone?: '' | 'accent' | 'warn' | 'danger';
}) {
  return (
    <div className={`kpi ${tone}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {hint && <div className="kpi-hint">{hint}</div>}
    </div>
  );
}

export type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'purple' | 'accent';

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function Notice({
  kind = 'info', icon, children,
}: {
  kind?: 'info' | 'warning' | 'danger' | 'success' | 'privacy';
  icon?: string; children: ReactNode;
}) {
  const defaultIcon = {
    info: 'ℹ', warning: '⚠', danger: '✕', success: '✓', privacy: '🔒',
  }[kind];
  return (
    <div className={`notice ${kind}`}>
      <span className="notice-icon">{icon ?? defaultIcon}</span>
      <div>{children}</div>
    </div>
  );
}

export function Empty({
  icon = '○', title, hint,
}: { icon?: string; title: string; hint?: string }) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <div className="empty-title">{title}</div>
      {hint && <div className="empty-hint">{hint}</div>}
    </div>
  );
}

export function Spinner() {
  return <span className="spinner" aria-label="Loading" />;
}

export function LoadingBlock({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="empty">
      <Spinner />
      <div className="empty-hint" style={{ marginTop: 10 }}>{label}</div>
    </div>
  );
}

export function ErrorBlock({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Notice kind="danger">
      <strong>Something went wrong.</strong>
      <div style={{ marginTop: 3 }}>{message}</div>
      {onRetry && (
        <button className="btn sm" style={{ marginTop: 9 }} onClick={onRetry}>
          Try again
        </button>
      )}
    </Notice>
  );
}

// ------------------------------------------------------------------- charts

export function BarChart({
  data, tone,
}: {
  data: { label: string; count: number }[];
  tone?: (label: string, index: number) => string;
}) {
  const max = Math.max(...data.map((d) => d.count), 1);
  if (!data.length) return <Empty title="No data yet" />;
  return (
    <div>
      {data.map((d, i) => (
        <div className="bar-row" key={d.label}>
          <div className="bar-label truncate" title={d.label}>{d.label}</div>
          <div className="bar-track">
            <div
              className={`bar-fill ${tone?.(d.label, i) ?? ''}`}
              style={{ width: `${(d.count / max) * 100}%` }}
            />
          </div>
          <div className="bar-value">{d.count}</div>
        </div>
      ))}
    </div>
  );
}

export function ConfidenceMeter({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="subtle">—</span>;
  const pct = Math.round(value * 100);
  const color =
    pct >= 90 ? 'var(--success)' : pct >= 75 ? 'var(--warning)' : 'var(--danger)';
  return (
    <span className="confidence-meter">
      <span className="confidence-track">
        <span className="confidence-fill" style={{ width: `${pct}%`, background: color }} />
      </span>
      <span style={{ fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>{pct}%</span>
    </span>
  );
}

// ----------------------------------------------------------------- pipeline

const STAGE_LABELS: Record<string, string> = {
  upload: 'Upload',
  classification: 'Classification',
  ocr: 'OCR',
  masking: 'Masking',
  llm_processing: 'AI Processing',
  validation: 'Validation',
  review: 'Review',
  rehydration: 'Rehydration',
  output: 'Output',
};

export const STAGE_ORDER = [
  'upload', 'classification', 'ocr', 'masking', 'llm_processing',
  'validation', 'review', 'rehydration', 'output',
];

export function PipelineTimeline({
  stages,
}: {
  stages: { stage: string; status: string; duration_ms: number | null }[];
}) {
  const byStage = new Map(stages.map((s) => [s.stage, s]));
  return (
    <div className="pipeline">
      {STAGE_ORDER.map((stage, index) => {
        const run = byStage.get(stage);
        const status = run?.status ?? 'pending';
        const done = status === 'completed';
        const symbol =
          status === 'completed' ? '✓'
          : status === 'failed' ? '✕'
          : status === 'blocked' ? '!'
          : String(index + 1);
        return (
          <div className="pipeline-step" key={stage}>
            {index > 0 && (
              <div className={`pipeline-connector ${done ? 'done' : ''}`} />
            )}
            <div className="pipeline-node">
              <div className={`pipeline-dot ${status}`}>{symbol}</div>
              <div className="pipeline-label">{STAGE_LABELS[stage]}</div>
              {run?.duration_ms != null && run.duration_ms > 0 && (
                <div className="pipeline-duration">{formatDuration(run.duration_ms)}</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------ helpers

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const seconds = Math.floor((Date.now() - then) / 1000);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function humanize(value: string): string {
  return value
    .replace(/[._]/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function statusTone(status: string): Tone {
  switch (status) {
    case 'completed': case 'filed': case 'approved': case 'indexed':
    case 'ready_to_file': case 'healthy':
      return 'success';
    case 'running': case 'processing': case 'in_review': case 'indexing':
      return 'info';
    case 'awaiting_review': case 'pending': case 'draft':
    case 'awaiting_client_info': case 'proposed': case 'degraded':
      return 'warning';
    case 'failed': case 'rejected': case 'unhealthy': case 'quarantined':
      return 'danger';
    case 'amended': case 'edited': case 'escalated':
      return 'purple';
    default:
      return 'neutral';
  }
}

export function authorityTone(level: string | null): Tone {
  switch (level) {
    case 'statutory': return 'purple';
    case 'regulatory': return 'info';
    case 'official_guidance': case 'state_official': return 'accent';
    case 'judicial': return 'warning';
    default: return 'neutral';
  }
}

export function confidenceTone(level: string): Tone {
  switch (level) {
    case 'high': return 'success';
    case 'medium': return 'warning';
    case 'low': return 'danger';
    default: return 'neutral';
  }
}
