/**
 * Depreciation calculator - a live workspace.
 *
 * Two modes, chosen at the top:
 *
 * * **Single asset** - inputs in order (jurisdiction and year, asset
 *   details, elections, optional limits) on the left; a live summary, the
 *   calculation tape (the engine's own steps, line by line) and the
 *   jurisdiction map on the right; the schedule, state treatment,
 *   comparison and sources below.
 * * **Import an asset list** - a guided flow: jurisdiction and year first,
 *   then the upload, the lives, and the report (``AdditionsImport``).
 *
 * The tax year is the shared one (``TaxContext``), so the calculator, the
 * forms library, State Intelligence and the assistant agree. The state is
 * pre-filled from the map selection shared with the assistant and checked
 * against this calculator's allow-list (50 states and DC).
 *
 * All arithmetic happens on the server, in a deterministic engine. The page
 * recalculates as the form changes; the AI explanation is a separate,
 * explicit request.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, ChevronDown, ClipboardList, Download, FileDown, FileSpreadsheet, FileText, Gauge, Landmark,
  Plus, Receipt, RotateCcw, Sparkles, Trash2, TrendingDown, MapPinned, Calculator, ToggleRight,
} from 'lucide-react';

import {
  api,
  ApiError,
  type DepreciationExplanation,
  type DepreciationResult,
  type DepreciationRules,
  type StateProfile,
} from '../api/client';
import AdditionsImport from '../components/depreciation/AdditionsImport';
import AssetEditor from '../components/depreciation/AssetEditor';
import Results, { AssetSwitch } from '../components/depreciation/Results';
import { KeyValue, Label, MoneyInput, Panel, PercentInput, Tape, Toggle } from '../components/depreciation/widgets';
import StateMap from '../components/assistant/StateMap';
import { ErrorBlock, Kpi, LoadingBlock } from '../components/ui';
import { useTaxContext } from '../context/TaxContext';
import { adjustmentLabel, blankAsset, formProblem, money, shiftYear, toRequest, type CalculatorForm } from '../lib/depreciationForm';
import { readSelectedState, writeSelectedState } from '../lib/selectedState';
import { yearWithin } from '../lib/taxYear';
import '../styles/workspace.css';
import '../styles/depreciation.css';

const METHOD_FOR: Record<string, string> = {
  'true,true': 'section_179_bonus',
  'true,false': 'section_179',
  'false,true': 'bonus',
  'false,false': 'macrs',
};

const STATUS_LABEL = { live: 'Live', working: 'Calculating…', input: 'Needs input', error: 'Check inputs' } as const;
const STATUS_TONE = { live: 'live', working: 'info', input: 'neutral', error: 'danger' } as const;

function freshForm(rules: DepreciationRules, year: number): CalculatorForm {
  const remembered = readSelectedState();
  return {
    taxYear: year,
    state: rules.states.some((s) => s.code === remembered) ? remembered : null,
    method: 'section_179_bonus',
    assets: [blankAsset(year)],
    taxableIncome: '',
    totalPurchases: '',
    carryover: '',
    federalRate: '',
    stateRate: '',
    includeProvisional: false,
  };
}

export default function DepreciationPage() {
  const { taxYear: sharedYear, setTaxYear } = useTaxContext();
  const [rules, setRules] = useState<DepreciationRules | null>(null);
  const [rulesError, setRulesError] = useState('');
  const [profiles, setProfiles] = useState<StateProfile[]>([]);
  const [form, setForm] = useState<CalculatorForm | null>(null);
  const [mode, setMode] = useState<'single' | 'import'>('single');
  // Mounted on first use, then kept: switching modes never loses an import.
  const [importUsed, setImportUsed] = useState(false);
  const [active, setActive] = useState(0);
  const [focus, setFocus] = useState('all');
  const [result, setResult] = useState<DepreciationResult | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [calculating, setCalculating] = useState(false);
  const [explanation, setExplanation] = useState<DepreciationExplanation | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const sequence = useRef(0);
  const exportButton = useRef<HTMLButtonElement>(null);
  const exportMenu = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.depreciation
      .rules()
      .then((loaded) => {
        setRules(loaded);
        setForm(freshForm(loaded, yearWithin(sharedYear, loaded.supported_years)));
      })
      .catch((caught) => setRulesError(caught instanceof Error ? caught.message : String(caught)));
    api.chat.states().then(setProfiles).catch(() => setProfiles([]));
    // Loading runs once; the shared year is followed by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The shared year is the calculator's year, within the years the rules cover.
  const year = rules ? yearWithin(sharedYear, rules.supported_years) : sharedYear;
  useEffect(() => {
    setForm((prior) => (prior && prior.taxYear !== year
      ? { ...prior, taxYear: year, assets: prior.assets.map((a) => shiftYear(a, prior.taxYear, year)) }
      : prior));
    setExplanation(null);
  }, [year]);

  const allowedCodes = useMemo(() => new Set(rules?.states.map((s) => s.code) ?? []), [rules]);
  const mapProfiles = useMemo(() => profiles.filter((p) => allowedCodes.has(p.code)), [profiles, allowedCodes]);
  const sortedStates = useMemo(() => [...(rules?.states ?? [])].sort((a, b) => a.name.localeCompare(b.name)), [rules]);
  const stateInfo = rules?.states.find((s) => s.code === form?.state) ?? null;

  const update = useCallback((change: Partial<CalculatorForm>) => {
    setForm((prior) => (prior ? { ...prior, ...change } : prior));
    setExplanation(null);
  }, []);

  const selectState = useCallback((code: string | null) => {
    if (code && !allowedCodes.has(code)) return; // e.g. Puerto Rico from the shared map
    writeSelectedState(code);
    update({ state: code, includeProvisional: false });
  }, [allowedCodes, update]);

  // --- Live recalculation -------------------------------------------------

  const request = useMemo(() => (form ? toRequest(form) : null), [form]);
  const problem = form ? formProblem(form) : '';

  useEffect(() => {
    if (!request || problem) {
      setResult(null);
      setErrors([]);
      return;
    }
    const mine = ++sequence.current;
    setCalculating(true);
    const timer = window.setTimeout(() => {
      api.depreciation
        .calculate(request)
        .then((computed) => {
          if (mine !== sequence.current) return;
          setResult(computed);
          setErrors([]);
        })
        .catch((caught: unknown) => {
          if (mine !== sequence.current) return;
          setResult(null);
          if (caught instanceof ApiError) {
            const details = caught.details as { errors?: string[]; fields?: { location: string[]; problem: string }[] };
            setErrors(details.errors ?? details.fields?.map((f) => `${f.location.slice(1).join(' › ')}: ${f.problem}`) ?? [caught.message]);
          } else {
            setErrors([caught instanceof Error ? caught.message : String(caught)]);
          }
        })
        .finally(() => {
          if (mine === sequence.current) setCalculating(false);
        });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [request, problem]);

  // Keep the focused asset valid as assets come and go.
  useEffect(() => {
    if (!form) return;
    if (form.assets.length === 1) setFocus(form.assets[0].id);
    else if (focus !== 'all' && !form.assets.some((a) => a.id === focus)) setFocus('all');
    if (active >= form.assets.length) setActive(form.assets.length - 1);
  }, [form, focus, active]);

  // Export menu: first item focused on open; arrows move, Escape and a click outside close it.
  useEffect(() => {
    if (!exportOpen) return;
    const items = () => Array.from(exportMenu.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? []);
    items()[0]?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setExportOpen(false);
        exportButton.current?.focus();
      } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const list = items();
        const at = list.indexOf(document.activeElement as HTMLButtonElement);
        const next = event.key === 'ArrowDown' ? (at + 1) % list.length : (at - 1 + list.length) % list.length;
        list[next]?.focus();
      }
    };
    const onPointer = (event: MouseEvent) => {
      if (!exportMenu.current?.contains(event.target as Node) && !exportButton.current?.contains(event.target as Node)) {
        setExportOpen(false);
      }
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onPointer);
    };
  }, [exportOpen]);

  const explain = useCallback(async () => {
    if (!request) return;
    setExplaining(true);
    try {
      setExplanation(await api.depreciation.explain(request));
    } catch (caught) {
      setExplanation({ available: true, text: '', citations: [], reason: caught instanceof Error ? caught.message : String(caught) });
    } finally {
      setExplaining(false);
    }
  }, [request]);

  const exportFile = useCallback(async (kind: 'csv' | 'pdf') => {
    setExportOpen(false);
    exportButton.current?.focus();
    if (!request) return;
    try {
      await (kind === 'csv' ? api.depreciation.exportCsv(request) : api.depreciation.exportPdf(request));
    } catch (caught) {
      setErrors([caught instanceof Error ? caught.message : String(caught)]);
    }
  }, [request]);

  if (rulesError) return <ErrorBlock message={rulesError} onRetry={() => window.location.reload()} />;
  if (!rules || !form) return <LoadingBlock label="Loading depreciation rules…" />;

  const use179 = form.method === 'section_179' || form.method === 'section_179_bonus';
  const useBonus = form.method === 'bonus' || form.method === 'section_179_bonus';
  const setElection = (next179: boolean, nextBonus: boolean) => update({ method: METHOD_FOR[`${next179},${nextBonus}`] });
  const status = errors.length ? 'error' : problem ? 'input' : calculating ? 'working' : result ? 'live' : 'input';
  const activeAsset = form.assets[Math.min(active, form.assets.length - 1)];
  const activeResult = result?.assets.find((a) => a.id === activeAsset.id) ?? null;
  const focusAsset = result?.assets.find((a) => a.id === focus) ?? null;
  const statusForYear = stateInfo?.status_by_year[String(form.taxYear)];
  const state = result?.state;
  const stateComputed = state && (state.status === 'computed' || state.status === 'provisional');
  const single = mode === 'single';

  return (
    <div className="dw">
      {/* ------------------------------------------------------------ header */}
      <header className="dw-header">
        <div>
          <nav className="dw-crumbs" aria-label="Breadcrumb"><span>Calculators</span><span aria-hidden="true">›</span><strong>Depreciation</strong></nav>
          <div className="dw-title">
            <span className="dw-hero-tile" aria-hidden="true"><TrendingDown size={22} /></span>
            <div>
              <h1>Depreciation Calculator</h1>
              <p>Federal and state depreciation from published rules: Section 179, then bonus, then MACRS. Every figure comes from the engine, with its steps on the tape.</p>
            </div>
          </div>
        </div>
        {single && (
          <div className="dw-header-actions">
            <span className={`badge ${STATUS_TONE[status]} dw-status ${status}`} role="status" aria-live="polite">
              <span className="dw-dot" aria-hidden="true" />{STATUS_LABEL[status]}
            </span>
            <button type="button" className="btn ghost" onClick={() => { setForm(freshForm(rules, year)); setActive(0); setExplanation(null); }}>
              <RotateCcw size={15} aria-hidden="true" /> Reset
            </button>
            <div className="dw-menu">
              <button ref={exportButton} type="button" className="btn primary" aria-haspopup="menu" aria-expanded={exportOpen}
                disabled={!result} onClick={() => setExportOpen((o) => !o)}>
                <Download size={15} aria-hidden="true" /> Export <ChevronDown size={14} aria-hidden="true" />
              </button>
              {exportOpen && (
                <div className="dw-menu-pop" role="menu" ref={exportMenu} aria-label="Export">
                  <button type="button" role="menuitem" onClick={() => void exportFile('csv')}><FileDown size={14} aria-hidden="true" /> CSV schedule</button>
                  <button type="button" role="menuitem" onClick={() => void exportFile('pdf')}><FileText size={14} aria-hidden="true" /> PDF report</button>
                </div>
              )}
            </div>
          </div>
        )}
      </header>

      {/* -------------------------------------------------------------- mode */}
      <div className="ws-tabs dw-modes" role="tablist" aria-label="Calculator mode">
        <button type="button" role="tab" id="dw-tab-single" aria-controls="dw-panel-single" aria-selected={single}
          className="ws-tab" onClick={() => setMode('single')}>
          <Calculator size={14} aria-hidden="true" /> Single asset
        </button>
        <button type="button" role="tab" id="dw-tab-import" aria-controls="dw-panel-import" aria-selected={!single}
          className="ws-tab" onClick={() => { setMode('import'); setImportUsed(true); }}>
          <FileSpreadsheet size={14} aria-hidden="true" /> Import an asset list
        </button>
      </div>

      <div role="tabpanel" id="dw-panel-import" aria-labelledby="dw-tab-import" hidden={single}>
        {importUsed && <AdditionsImport rules={rules} defaultYear={year} onYear={setTaxYear} />}
      </div>

      <div role="tabpanel" id="dw-panel-single" aria-labelledby="dw-tab-single" hidden={!single} className="dw-results">
        <div className="dw-layout">
          {/* ----------------------------------------------------------- inputs */}
          <div className="dw-col">
            <Panel icon={<Landmark size={18} />} title="Jurisdiction and tax year" subtitle="The rules every figure below is computed under">
              <div className="dw-row2">
                <div className="dw-field">
                  <Label htmlFor="dw-year" info={`Shared with the forms library, State Intelligence and the assistant. Rules are verified for ${rules.supported_years[0]}–${rules.supported_years.at(-1)}; other years are refused rather than guessed.`}>Tax year</Label>
                  <select id="dw-year" value={form.taxYear} onChange={(e) => setTaxYear(Number(e.target.value))}>
                    {[...rules.supported_years].reverse().map((y) => <option key={y} value={y}>{y}</option>)}
                  </select>
                </div>
                <div className="dw-field">
                  <Label htmlFor="dw-state" info="Pre-filled from the map. Each state's rule is shown with its source; a state without a verified rule for the year says so instead of borrowing another's.">State</Label>
                  <select id="dw-state" value={form.state ?? ''} onChange={(e) => selectState(e.target.value || null)}>
                    <option value="">Federal only</option>
                    {sortedStates.map((s) => (
                      <option key={s.code} value={s.code}>{s.name}{s.changed_recently_years.length ? ' • rules changed' : ''}</option>
                    ))}
                  </select>
                </div>
              </div>
              {stateInfo && (
                <div className="dw-badges" style={{ marginTop: 0 }}>
                  {statusForYear === 'verified' && <span className="badge success">{form.taxYear} rule verified</span>}
                  {statusForYear === 'unverified' && <span className="badge warning">{form.taxYear} rule not yet verified</span>}
                  {statusForYear === 'no_income_tax' && <span className="badge neutral">No individual income tax</span>}
                  {stateInfo.changed_recently_years.length > 0 && <span className="badge purple">Changed {stateInfo.changed_recently_years.join(', ')}</span>}
                </div>
              )}
            </Panel>

            <Panel
              icon={<ClipboardList size={18} />}
              title="Asset details"
              subtitle="Enter every asset placed in service this year — the Section 179 phase-out and the mid-quarter test depend on all of them"
            >
              <div className="dw-asset-tabs">
                {/* A tablist may hold only tabs, so "Add asset" sits beside it. */}
                <div className="dw-asset-tablist" role="tablist" aria-label="Assets">
                  {form.assets.map((asset, index) => (
                    <button key={asset.id} type="button" role="tab" aria-selected={index === active}
                      className={index === active ? 'on' : ''} onClick={() => setActive(index)}>
                      {asset.description || `Asset ${index + 1}`}
                    </button>
                  ))}
                </div>
                <button type="button" className="dw-tab-add" onClick={() => { update({ assets: [...form.assets, blankAsset(form.taxYear)] }); setActive(form.assets.length); }}>
                  <Plus size={14} aria-hidden="true" /> Add asset
                </button>
              </div>
              <AssetEditor
                key={activeAsset.id}
                asset={activeAsset}
                classes={rules.asset_classes}
                rules={rules}
                use179={use179}
                useBonus={useBonus}
                result={activeResult}
                onChange={(changed) => update({ assets: form.assets.map((a) => (a.id === changed.id ? changed : a)) })}
              />
              {form.assets.length > 1 && (
                <button type="button" className="btn ghost sm" onClick={() => update({ assets: form.assets.filter((a) => a.id !== activeAsset.id) })}>
                  <Trash2 size={14} aria-hidden="true" /> Remove this asset
                </button>
              )}
            </Panel>

            <Panel icon={<ToggleRight size={18} />} title="Elections" subtitle="Applied in this order: Section 179, then bonus on what is left, then MACRS on the rest">
              <div className="dw-elections">
                <div className="dw-election">
                  <div>
                    <div className="dw-label"><strong>Section 179 expensing</strong></div>
                    <p className="dw-hint">Taken first, up to the annual limit and your business income.</p>
                  </div>
                  <Toggle checked={use179} onChange={(v) => setElection(v, useBonus)} label="Section 179 expensing" />
                </div>
                <div className="dw-election">
                  <div>
                    <div className="dw-label"><strong>Bonus depreciation</strong></div>
                    <p className="dw-hint">Then Sec. 168(k) on what is left; MACRS on the rest.</p>
                  </div>
                  <Toggle checked={useBonus} onChange={(v) => setElection(use179, v)} label="Bonus depreciation" />
                </div>
              </div>
            </Panel>

            <Panel icon={<Gauge size={18} />} title="Limits and tax rates" subtitle="Optional — the Section 179 income limit, phase-out, and tax-effect estimates">
              <div className="dw-row2">
                <div className="dw-field">
                  <Label htmlFor="dw-income" info="Section 179 cannot exceed taxable income from the active conduct of your trade or business; the excess carries forward.">Taxable business income</Label>
                  <MoneyInput id="dw-income" value={form.taxableIncome} onChange={(v) => update({ taxableIncome: v })} placeholder="Not limited" />
                </div>
                <div className="dw-field">
                  <Label htmlFor="dw-purchases" info="Total cost of Section 179 property placed in service this year, if more than the assets entered here. Drives the phase-out.">Total 179 property this year</Label>
                  <MoneyInput id="dw-purchases" value={form.totalPurchases} onChange={(v) => update({ totalPurchases: v })} placeholder="Assets entered" />
                </div>
                <div className="dw-field">
                  <Label htmlFor="dw-carry" info="Disallowed Section 179 from last year's Form 4562 line 13.">Section 179 carryover in</Label>
                  <MoneyInput id="dw-carry" value={form.carryover} onChange={(v) => update({ carryover: v })} placeholder="0" />
                </div>
                <div className="dw-field">
                  <Label htmlFor="dw-fed" info="Used only to estimate the tax effect of each method.">Federal marginal rate</Label>
                  <PercentInput id="dw-fed" value={form.federalRate} onChange={(v) => update({ federalRate: v })} />
                </div>
                <div className="dw-field">
                  <Label htmlFor="dw-strate">State marginal rate</Label>
                  <PercentInput id="dw-strate" value={form.stateRate} onChange={(v) => update({ stateRate: v })} />
                </div>
              </div>
            </Panel>

            {errors.length > 0 && (
              <div className="notice danger" role="alert">
                <AlertTriangle size={16} aria-hidden="true" />
                <div><strong>Some inputs need attention</strong><ul>{errors.map((e) => <li key={e}>{e}</li>)}</ul></div>
              </div>
            )}
          </div>

          {/* -------------------------------------------------------- live side */}
          <aside className="dw-col dw-side" aria-label="Live results">
            <Panel
              icon={<Sparkles size={18} />}
              title="Live summary"
              subtitle={result ? `Tax year ${result.tax_year} · ${result.primary_label}` : `Tax year ${form.taxYear}`}
            >
              {result ? (
                <>
                  <div className="dw-kpis">
                    <div className="kpi accent wide">
                      <div className="kpi-label">Current-year depreciation</div>
                      <div className="kpi-value">{money(result.summary.current_year.value)}</div>
                    </div>
                    {state && (
                      <Kpi
                        label={`${state.name} deduction`}
                        value={stateComputed ? money(state.tax_year_deduction) : '—'}
                        hint={stateComputed
                          ? (state.tax_year_adjustment && Number(state.tax_year_adjustment) ? adjustmentLabel(state.tax_year_adjustment) : 'Same as federal')
                          : state.status === 'no_income_tax' ? 'No income tax' : 'Not yet verified'}
                      />
                    )}
                    <Kpi label={result.summary.ending_nbv.label} value={money(result.summary.ending_nbv.value)} />
                  </div>
                  <div className="dw-summary">
                    <KeyValue label={result.summary.ending_cost.label} value={money(result.summary.ending_cost.value)} />
                    <KeyValue label={result.summary.ending_accumulated.label} value={<span className="accent">{money(result.summary.ending_accumulated.value)}</span>} />
                    {Number(result.federal.carryforward) > 0 && <KeyValue label="Section 179 carryforward" value={money(result.federal.carryforward)} />}
                    {result.warnings.length > 0 && (
                      <ul className="dw-warnings">{result.warnings.map((w) => <li key={w}><AlertTriangle size={13} aria-hidden="true" /> {w}</li>)}</ul>
                    )}
                  </div>
                </>
              ) : (
                <p className="dw-hint">{problem || 'Results appear here as soon as the asset has a cost and a date.'}</p>
              )}
            </Panel>

            <Panel
              icon={<Receipt size={18} />}
              title="Calculation tape"
              subtitle={`Step-by-step for tax year ${form.taxYear}, straight from the engine`}
              actions={result && result.assets.length > 1 ? <AssetSwitch result={result} focus={focus} onFocus={setFocus} /> : undefined}
            >
              {result ? <Tape sections={focusAsset ? focusAsset.tape : result.tape} /> : <p className="dw-hint">The tape fills in once there is a result.</p>}
            </Panel>

            <Panel icon={<MapPinned size={18} />} title="Jurisdiction map" subtitle="Click a state to apply its rules">
              <StateMap profiles={mapProfiles} selected={form.state} onSelect={selectState} />
              {(() => {
                const changed = sortedStates.filter((s) => s.changed_recently_years.includes(form.taxYear));
                if (!changed.length) return null;
                return (
                  <div className="dw-recent">
                    <span className="dw-eyebrow">Changed their rules for {form.taxYear}</span>
                    <div className="dw-chips">
                      {changed.map((s) => (
                        <button key={s.code} type="button" className={`dw-chip-btn ${form.state === s.code ? 'on' : ''}`}
                          title={s.change_notes[String(form.taxYear)] || s.name} aria-pressed={form.state === s.code}
                          onClick={() => selectState(s.code)}>{s.code}</button>
                      ))}
                    </div>
                  </div>
                );
              })()}
            </Panel>
          </aside>
        </div>

        {result && (
          <Results
            result={result}
            focus={focus}
            onFocus={setFocus}
            explanation={explanation}
            explaining={explaining}
            onExplain={() => void explain()}
            onShowProvisional={() => update({ includeProvisional: true })}
          />
        )}
      </div>
    </div>
  );
}
