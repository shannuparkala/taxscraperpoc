/**
 * What this return's model calls cost, pinned to the bottom corner.
 *
 * Collapsed it is one figure. Expanded it splits by stage and by model, with
 * tokens beside each, and says which price file the figures came from. Calls
 * the price file has no rate for are counted and named, never folded into the
 * total as zero - a partial figure must not pass for a whole one.
 */

import { useState } from 'react';

import { api, type CostBucket } from '../api/client';
import { useAsync } from '../hooks/useApi';
import { humanize } from './ui';

function usd(raw: string): string {
  const value = Number(raw);
  if (!Number.isFinite(value)) return raw;
  // Model calls cost fractions of a cent; two decimals would show $0.00.
  return value === 0 ? '$0' : value < 0.01
    ? `$${value.toFixed(4)}`
    : `$${value.toFixed(value < 1 ? 3 : 2)}`;
}

function tokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

function Rows({ title, buckets, label }: {
  title: string; buckets: CostBucket[]; label: (key: string) => string;
}) {
  if (!buckets.length) return null;
  return (
    <section>
      <h4>{title}</h4>
      <table className="cost-table">
        <tbody>
          {buckets.map((b) => (
            <tr key={b.key}>
              <td>
                {label(b.key)}
                <div className="subtle">
                  {b.calls} call{b.calls === 1 ? '' : 's'} · {tokens(b.input_tokens)} in
                  {b.cached_tokens > 0 && ` (${tokens(b.cached_tokens)} cached)`}
                  {' · '}{tokens(b.output_tokens + b.thinking_tokens)} out
                  {b.stub_calls > 0 && ` · ${b.stub_calls} offline`}
                  {b.failed_calls > 0 && ` · ${b.failed_calls} failed`}
                </div>
              </td>
              <td className="num">
                {usd(b.cost_usd)}
                {b.unpriced_calls > 0 && <div className="cost-warn">+{b.unpriced_calls} unpriced</div>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export default function CostMeter({ workflowId }: { workflowId: string }) {
  const [open, setOpen] = useState(false);
  const cost = useAsync(() => api.workflows.cost(workflowId), [workflowId]);
  const data = cost.data;
  if (!data) return null;

  const total = data.total;
  return (
    <aside className={`cost-meter${open ? ' open' : ''}`} aria-label="Model cost for this return">
      <button
        type="button"
        className="cost-head"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="cost-label">Model cost</span>
        <strong>{usd(total.cost_usd)}</strong>
        {total.unpriced_calls > 0 && <span className="cost-warn">+{total.unpriced_calls} unpriced</span>}
        <span className="chevron">{open ? '▾' : '▴'}</span>
      </button>

      {open && (
        <div className="cost-body">
          <div className="subtle">
            {total.calls} call{total.calls === 1 ? '' : 's'}
            {data.cost_per_page_usd !== null && ` · ${usd(data.cost_per_page_usd)} per page over ${data.pages} pages`}
          </div>
          {total.stub_calls > 0 && total.stub_calls === total.calls && (
            <div className="cost-warn">The model was off for this run - no calls were billed.</div>
          )}
          <Rows title="By stage" buckets={data.by_stage} label={humanize} />
          <Rows title="By model" buckets={data.by_model} label={(k) => k} />
          <div className="subtle cost-foot">
            Rates as of {data.prices_as_of.join(', ') || 'unknown'}
            {data.prices_source && (
              <> from <a href={data.prices_source} target="_blank" rel="noreferrer noopener">the provider’s price page</a></>
            )}
            . Fixed when each call was made.
            {' '}<button type="button" className="link-button" onClick={cost.reload}>Refresh</button>
          </div>
        </div>
      )}
    </aside>
  );
}
