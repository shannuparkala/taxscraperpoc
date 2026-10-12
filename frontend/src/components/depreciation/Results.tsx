/**
 * Below-the-fold results: how each headline number is computed, the
 * year-by-year schedule with a "why" for every row, the state treatment and
 * its reversal, method comparison, Form 4562 lines, the AI explanation and
 * every source.
 *
 * Every figure is a field of the server's result; the browser computes none.
 */

import { Fragment, useState } from 'react';
import {
  AlertTriangle, BookOpenCheck, ChevronRight, ExternalLink, FileSpreadsheet, GitCompareArrows,
  HelpCircle, Landmark, MapPinned, Scale, Sparkles, Table2,
} from 'lucide-react';

import type {
  AssetScheduleRow,
  DepreciationExplanation,
  DepreciationResult,
  DepreciationStateResult,
  ScheduleRow,
} from '../../api/client';
import { Badge, Spinner } from '../ui';
import { adjustmentLabel, money } from '../../lib/depreciationForm';
import { Panel, WhyCard } from './widgets';

interface Props {
  result: DepreciationResult;
  focus: string; // 'all' or an asset id
  onFocus: (id: string) => void;
  explanation: DepreciationExplanation | null;
  explaining: boolean;
  onExplain: () => void;
  onShowProvisional: () => void;
}

export default function Results({ result, focus, onFocus, explanation, explaining, onExplain, onShowProvisional }: Props) {
  const { summary, state } = result;
  const stateComputed = Boolean(state && (state.status === 'computed' || state.status === 'provisional'));

  return (
    <div className="dw-results">
      <Panel icon={<HelpCircle size={18} />} title="How each number is computed" subtitle="Click “Why?” on any card for the formula and rationale.">
        <div className="dw-why-grid">
          <WhyCard figure={summary.current_year} tone="accent" />
          <WhyCard figure={summary.ending_accumulated} />
          <WhyCard figure={summary.ending_cost} />
          <WhyCard figure={summary.ending_nbv} />
        </div>
      </Panel>

      <Schedule result={result} focus={focus} onFocus={onFocus} stateComputed={stateComputed} />

      {state && <StatePanel state={state} taxYear={result.tax_year} onShowProvisional={onShowProvisional} />}

      <Comparison result={result} />

      <Panel icon={<FileSpreadsheet size={18} />} title="Form 4562 reference" subtitle={`Where each ${result.tax_year} amount goes. A reference, not a completed form.`}>
        <div className="dw-table-wrap">
          <table className="dw-table">
            <thead><tr><th scope="col">Line</th><th scope="col">Description</th><th scope="col" className="num">Amount</th></tr></thead>
            <tbody>
              {result.form_4562.map((line) => (
                <tr key={`${line.line}-${line.label}`} className={line.line === '22' || line.line === '12' ? 'dw-row-em' : ''}>
                  <th scope="row"><span className="dw-line-badge">{line.line}</span></th>
                  <td>{line.label}</td>
                  <td className="num dw-num">{line.amount === '' ? '—' : money(line.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel
        icon={<Sparkles size={18} />}
        title="Plain-English explanation"
        subtitle="Written by AI from the figures above, with cited sources. It explains; it never computes."
        actions={
          <button type="button" className="btn" onClick={onExplain} disabled={explaining}>
            {explaining ? <Spinner /> : <Sparkles size={14} aria-hidden="true" />} {explanation?.text ? 'Explain again' : 'Explain this result'}
          </button>
        }
      >
        {!explanation && !explaining && <p className="dw-hint">Optional. Sends only the computed figures and asset classes — never your descriptions.</p>}
        {explanation?.text && (
          <div className="dw-explain">
            <span className="badge accent">Explanation · not a calculation</span>
            <p>{explanation.text}</p>
            <ol className="dw-sources">
              {explanation.citations.map((c) => (
                <li key={c.index}>
                  <a href={c.url} target="_blank" rel="noreferrer noopener">{c.title} <ExternalLink size={12} aria-hidden="true" /></a>
                  <span className="muted"> · {c.authority_label}</span>
                </li>
              ))}
            </ol>
          </div>
        )}
        {explanation && !explanation.text && <p className="dw-hint">{explanation.reason}</p>}
      </Panel>

      <Panel icon={<BookOpenCheck size={18} />} title="Sources and assumptions" subtitle="Every rule value used above, with where it came from.">
        <ul className="dw-bullets">{result.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
        {result.notes.map((n) => <p key={n} className="dw-hint">{n}</p>)}
        <div className="dw-table-wrap">
          <table className="dw-table dw-sources-table">
            <thead><tr><th scope="col">Rule</th><th scope="col">Source</th><th scope="col">Verified</th></tr></thead>
            <tbody>
              {result.sources.map((s) => (
                <tr key={s.key}>
                  <td>{s.label}</td>
                  <td>
                    {s.source_url ? <a href={s.source_url} target="_blank" rel="noreferrer noopener">{s.source_citation || s.source_url}</a> : s.source_citation}
                    {s.verify_note && !s.verified && <div className="dw-hint">{s.verify_note}</div>}
                  </td>
                  <td>{s.verified ? <Badge tone="success">{s.last_verified}</Badge> : <Badge tone="warning">not verified</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <p className="dw-disclaimer"><Scale size={14} aria-hidden="true" /> {result.disclaimer}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------

function Schedule({
  result, focus, onFocus, stateComputed,
}: {
  result: DepreciationResult; focus: string; onFocus: (id: string) => void; stateComputed: boolean;
}) {
  const [open, setOpen] = useState<number | null>(result.tax_year);
  const asset = result.assets.find((a) => a.id === focus) ?? null;
  const rows: (ScheduleRow | AssetScheduleRow)[] = asset ? asset.schedule : result.federal.schedule;
  const stateRows = new Map((result.state?.rows ?? []).map((r) => [r.year, r]));
  const showState = stateComputed && !asset;
  const start = asset ? Number(asset.placed_in_service.slice(0, 4)) : (rows[0]?.year ?? result.tax_year);

  return (
    <Panel
      icon={<Table2 size={18} />}
      title="Year-by-year depreciation"
      subtitle="Click any year to see how the amount is computed"
      actions={result.assets.length > 1 ? <AssetSwitch result={result} focus={focus} onFocus={onFocus} /> : undefined}
    >
      <div className="dw-table-wrap">
        <table className="dw-table dw-schedule">
          <caption className="sr-only">Depreciation by year{asset ? ` for ${asset.description || asset.class_label}` : ', all assets'}</caption>
          <thead>
            <tr>
              <th scope="col">Year</th>
              {asset && <th scope="col" className="num">Rate</th>}
              <th scope="col" className="num">Sec. 179</th>
              <th scope="col" className="num">Bonus</th>
              <th scope="col" className="num">MACRS</th>
              <th scope="col" className="num">Depreciation</th>
              <th scope="col" className="num">Cumulative</th>
              <th scope="col" className="num">Remaining basis</th>
              {showState && <th scope="col" className="num">{result.state!.code}</th>}
              {showState && <th scope="col" className="num">State adj.</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const isOpen = open === row.year;
              const selected = row.year === result.tax_year;
              const s = stateRows.get(row.year);
              const rate = 'rate' in row ? row.rate : null;
              const colSpan = 7 + (asset ? 1 : 0) + (showState ? 2 : 0);
              return (
                <Fragment key={row.year}>
                  <tr className={`dw-sched-row ${selected ? 'selected' : ''} ${isOpen ? 'open' : ''}`}>
                    <th scope="row">
                      <button type="button" className="dw-expand" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : row.year)}>
                        <ChevronRight size={15} aria-hidden="true" className="dw-chev" />
                        <span>Year {row.year - start + 1}</span> <span className="muted">({row.year})</span>
                        {selected && <span className="badge accent">Selected</span>}
                        {'capped' in row && row.capped && <span className="badge warning">§280F cap</span>}
                      </button>
                    </th>
                    {asset && <td className="num dw-num">{rate ? `${Number(rate).toFixed(2)}%` : '—'}</td>}
                    <td className="num dw-num muted-zero">{money(row.section_179)}</td>
                    <td className="num dw-num muted-zero">{money(row.bonus)}</td>
                    <td className="num dw-num muted-zero">{money(row.macrs)}</td>
                    <td className="num dw-num"><strong>{money(row.total)}</strong></td>
                    <td className="num dw-num dim">{money(row.cumulative)}</td>
                    <td className="num dw-num dim">{money(row.remaining)}</td>
                    {showState && <td className="num dw-num">{money(s?.state ?? '0')}</td>}
                    {showState && <td className="num dw-num">{s ? adjustmentLabel(s.adjustment) : '—'}</td>}
                  </tr>
                  {isOpen && (
                    <tr className="dw-why-row">
                      <td colSpan={colSpan}>
                        <div className="dw-why-box">
                          <strong>Why this amount?</strong>
                          <ol>{row.why.map((w, i) => <li key={i}>{w}</li>)}</ol>
                          {showState && s && Number(s.adjustment) !== 0 && (
                            <p className="dw-hint">
                              {result.state!.name}: federal {money(s.federal)} − state {money(s.state)} = {adjustmentLabel(s.adjustment)}.
                            </p>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">Total</th>
              {asset && <td />}
              <td colSpan={3} />
              <td className="num dw-num"><strong>{money(asset ? asset.total : result.federal.total)}</strong></td>
              <td colSpan={2} className="dw-check-cell">
                <span className={result.federal.check.ok ? 'ok' : 'bad'}>{result.federal.check.statement}</span>
              </td>
              {showState && <td className="num dw-num">{money(result.state!.total)}</td>}
              {showState && <td className="num">{result.state!.reverses ? 'Reverses to $0' : '—'}</td>}
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="dw-hint">Click any year to see <strong>Why this amount?</strong></p>
    </Panel>
  );
}

export function AssetSwitch({ result, focus, onFocus }: { result: DepreciationResult; focus: string; onFocus: (id: string) => void }) {
  return (
    <div className="dw-seg" role="tablist" aria-label="Choose an asset">
      <button type="button" role="tab" aria-selected={focus === 'all'} className={focus === 'all' ? 'on' : ''} onClick={() => onFocus('all')}>All assets</button>
      {result.assets.map((a, i) => (
        <button key={a.id} type="button" role="tab" aria-selected={focus === a.id} className={focus === a.id ? 'on' : ''} onClick={() => onFocus(a.id)}>
          {a.description || `Asset ${i + 1}`}
        </button>
      ))}
    </div>
  );
}

function StatePanel({ state, taxYear, onShowProvisional }: { state: DepreciationStateResult; taxYear: number; onShowProvisional: () => void }) {
  const computed = state.status === 'computed' || state.status === 'provisional';
  const max = Math.max(1, ...state.rows.map((r) => Math.abs(Number(r.adjustment))));
  return (
    <Panel
      icon={<MapPinned size={18} />}
      title={`${state.name} treatment`}
      subtitle={computed ? 'How the state differs from federal, and how the difference reverses' : undefined}
      actions={
        <div className="dw-badges">
          {state.status === 'computed' && <Badge tone="success">Verified rule</Badge>}
          {state.status === 'provisional' && <Badge tone="warning">Provisional</Badge>}
          {state.status === 'not_verified' && <Badge tone="warning">Not yet verified</Badge>}
          {state.status === 'no_income_tax' && <Badge tone="neutral">No income tax</Badge>}
          {state.changed_recently_years.length > 0 && (
            <Badge tone="purple"><AlertTriangle size={11} aria-hidden="true" /> Changed {state.changed_recently_years.join(', ')}</Badge>
          )}
        </div>
      }
    >
      <p className={`dw-state-msg ${state.status}`}>{state.message}</p>
      {state.status === 'not_verified' && state.provisional_available && (
        <button type="button" className="btn" onClick={onShowProvisional}>Show provisional state estimate</button>
      )}
      {computed && (
        <div className="dw-reversal" aria-label="State adjustment by year">
          {state.rows.map((r) => {
            const value = Number(r.adjustment);
            return (
              <div key={r.year} className={`dw-rev-row ${r.year === taxYear ? 'selected' : ''}`}>
                <span className="dw-rev-year">{r.year}</span>
                <span className="dw-rev-track">
                  <span className={`dw-rev-bar ${value >= 0 ? 'add' : 'sub'}`} style={{ width: `${(Math.abs(value) / max) * 50}%` }} />
                </span>
                <span className="dw-num dw-rev-val">{adjustmentLabel(r.adjustment)}</span>
                <span className="dw-num dim">cum. {money(r.cumulative_difference)}</span>
              </div>
            );
          })}
          <p className="dw-hint">Positive = add back to state income (state allows less now); negative = subtract later as the state recovers the same basis. {state.reverses ? 'The total nets to $0.' : ''}</p>
        </div>
      )}
      {(state.rule.summary || state.rule.source_url) && (
        <details className="dw-details">
          <summary><Landmark size={14} aria-hidden="true" /> The {taxYear} rule and its source</summary>
          {state.rule.summary && <p>{state.rule.summary}</p>}
          {state.rule.change_note && <p><strong>Recent change:</strong> {state.rule.change_note}</p>}
          {state.notes.map((n) => <p key={n}>{n}</p>)}
          {state.rule.source_url && (
            <p>Source: <a href={state.rule.source_url} target="_blank" rel="noreferrer noopener">{state.rule.source_citation || state.rule.source_url}</a>
              {state.rule.last_verified ? ` · verified ${state.rule.last_verified}` : ' · not verified'}</p>
          )}
          {state.rule.verify_note && <p className="dw-hint">{state.rule.verify_note}</p>}
        </details>
      )}
    </Panel>
  );
}

function Comparison({ result }: { result: DepreciationResult }) {
  const max = Math.max(1, ...result.comparison.map((c) => Number(c.federal_tax_year_deduction)));
  return (
    <Panel icon={<GitCompareArrows size={18} />} title="Method comparison" subtitle="Same total basis, different timing. Add marginal rates in the form to estimate the tax effect.">
      <div className="dw-compare">
        {result.comparison.map((c) => {
          const shown = c.key === result.primary_scenario;
          return (
            <div key={c.key} className={`dw-compare-row ${shown ? 'shown' : ''}`}>
              <div className="dw-compare-label">
                {c.label} {shown && <span className="badge accent">Shown</span>}
              </div>
              <div className="dw-compare-bar"><span style={{ width: `${(Number(c.federal_tax_year_deduction) / max) * 100}%` }} /></div>
              <dl className="dw-compare-figs">
                <div><dt>Federal {result.tax_year}</dt><dd className="dw-num">{money(c.federal_tax_year_deduction)}</dd></div>
                <div><dt>{result.state ? result.state.code : 'State'} {result.tax_year}</dt><dd className="dw-num">{money(c.state_tax_year_deduction)}</dd></div>
                <div><dt>Tax effect</dt><dd className="dw-num">{money(c.combined_tax_effect)}</dd></div>
                <div><dt>Carryforward</dt><dd className="dw-num">{money(c.federal_carryforward)}</dd></div>
              </dl>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}
