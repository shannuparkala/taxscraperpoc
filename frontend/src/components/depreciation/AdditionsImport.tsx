/**
 * Current-year additions from a spreadsheet, as a guided flow:
 *
 *   1. Jurisdiction and tax year (Federal and the shared year by default).
 *   2. Upload - disabled until step 1 is confirmed, because every life and
 *      figure depends on it. A template is offered; problems are listed by
 *      row and column.
 *   3. Lives - each asset's MACRS class, decided for that year and
 *      jurisdiction (the AI's suggestion with its reason, or the file's own
 *      life). The user can change any of them.
 *   4. Report - the engine's figures: Section 179, then bonus on what is
 *      left, then MACRS, federal and (with a state) under the state's rules.
 *
 * Changing the year or jurisdiction after an upload recomputes everything;
 * a new year decides the lives again, and asks first when that would replace
 * lives the user chose. A result is never left on screen for inputs it was
 * not computed from. Every figure is the server's; nothing here does
 * arithmetic beyond formatting.
 */

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Check, Download, FileSpreadsheet, Pencil, Sparkles, Upload } from 'lucide-react';

import {
  api,
  ApiError,
  type AdditionAssetInput,
  type AdditionImport,
  type AdditionImportRow,
  type AdditionReport,
  type AdditionReportRequest,
  type DepreciationRules,
  type LifePrediction,
} from '../../api/client';
import { Spinner } from '../ui';
import { InfoTip, Label, Panel, money2 } from './widgets';

interface Props {
  rules: DepreciationRules;
  /** The shared tax year, already within the rules' years. */
  defaultYear: number;
  /** Writes the year back to the shared selection, so every section agrees. */
  onYear: (year: number) => void;
}

interface Setup {
  year: number;
  state: string | null;
}

interface Choice {
  /** "class|recovery years" - years only for the "other" class. */
  life: string;
  /** The user picked this life; a new year asks before replacing it. */
  chosen: boolean;
  elect179: boolean;
  electBonus: boolean;
  workVehicle: boolean;
}

const SOURCE_LABEL: Record<string, string> = {
  ai: 'AI', description: 'From description', file: 'From file', none: 'Choose',
};

const lifeKey = (p: LifePrediction) => (p.asset_class ? `${p.asset_class}|${p.recovery_years ?? ''}` : '');

/** The file's own problems, plus whether the asset belongs to the year chosen now. */
function rowIssues(row: AdditionImportRow, year: number): { column: string; message: string }[] {
  const issues = [...(row.issues ?? [])];
  const acquiredYear = row.acquired ? Number(row.acquired.slice(0, 4)) : null;
  if (acquiredYear !== null && acquiredYear !== year) {
    issues.push({ column: 'Date Acquired', message: `acquired in ${acquiredYear}, not a ${year} addition` });
  }
  return issues;
}

export default function AdditionsImport({ rules, defaultYear, onYear }: Props) {
  const id = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  // Step 1: what is being edited, and what the rest of the flow was computed for.
  const [draft, setDraft] = useState<Setup>({ year: defaultYear, state: null });
  const [setup, setSetup] = useState<Setup | null>(null);
  const [editingSetup, setEditingSetup] = useState(true);
  const [business, setBusiness] = useState('');
  const [importing, setImporting] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState('');
  const [data, setData] = useState<AdditionImport | null>(null);
  const [predictions, setPredictions] = useState<LifePrediction[]>([]);
  const [message, setMessage] = useState('');
  const [choices, setChoices] = useState<Choice[]>([]);
  const [view, setView] = useState<'lives' | 'report'>('lives');
  const [relifing, setRelifing] = useState(false);
  // The report and the exact request it was computed from: a report is shown
  // only for the inputs on screen, never for the previous ones.
  const [report, setReport] = useState<{ key: string; value: AdditionReport } | null>(null);
  const [reportErrors, setReportErrors] = useState<{ key: string; errors: string[] } | null>(null);
  const [exporting, setExporting] = useState(false);
  // After an upload, step 2 folds to one line until another list is wanted.
  const [replacing, setReplacing] = useState(false);
  const sequence = useRef(0);

  // Until step 1 is confirmed, follow the shared year.
  useEffect(() => {
    if (!setup) setDraft((d) => ({ ...d, year: defaultYear }));
  }, [defaultYear, setup]);

  const stateName = (code: string | null) => (code ? rules.states.find((s) => s.code === code)?.name ?? code : 'Federal only');
  const sortedStates = useMemo(() => [...rules.states].sort((a, b) => a.name.localeCompare(b.name)), [rules]);
  const options = useMemo(() => {
    const out: { value: string; label: string }[] = [];
    for (const c of rules.asset_classes) {
      if (c.qpp) continue;
      if (c.recovery_years) out.push({ value: `${c.key}|`, label: `${c.recovery_years}-yr · ${c.label}` });
      else for (const years of c.allowed_recovery_years) out.push({ value: `${c.key}|${years}`, label: `${years}-yr · Other` });
    }
    return out;
  }, [rules]);
  const classInfo = useMemo(() => new Map(rules.asset_classes.map((c) => [c.key, c])), [rules]);

  // ------------------------------------------------------------------ step 1

  const applySetup = useCallback(async () => {
    const next = { ...draft };
    if (data && setup && next.year !== setup.year) {
      const chosen = choices.filter((c) => c.chosen).length;
      if (chosen && !window.confirm(
        `Changing the tax year to ${next.year} decides every asset's life again for ${next.year}. `
        + `The ${chosen} ${chosen === 1 ? 'life' : 'lives'} you chose will be replaced. Continue?`,
      )) return;
    }
    const yearChanged = !setup || next.year !== setup.year;
    setSetup(next);
    setEditingSetup(false);
    onYear(next.year);
    if (!data || !yearChanged) return;
    // A new year: decide the lives again for it. A new state alone changes
    // no life (no state in the rule data has its own recovery periods) - the
    // report below recomputes the state's figures.
    setRelifing(true);
    try {
      const fresh = await api.depreciation.additionLives({
        tax_year: next.year, state: next.state, business_activity: business,
        assets: data.rows.map((r) => ({ description: r.description, life_in_file: r.life_in_file })),
      });
      setPredictions(fresh.predictions);
      setMessage(fresh.message);
      setChoices((prior) => prior.map((c, i) => ({ ...c, life: lifeKey(fresh.predictions[i]), chosen: false })));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setRelifing(false);
    }
  }, [draft, data, setup, choices, business, onYear]);

  // ------------------------------------------------------------------ step 2

  const upload = useCallback(async (file: File) => {
    if (!setup) return;
    setImporting(true);
    setError('');
    try {
      const imported = await api.depreciation.importAdditions(file, {
        taxYear: setup.year, state: setup.state, businessActivity: business,
      });
      setData(imported);
      setPredictions(imported.rows.map((r) => r.prediction));
      setMessage(imported.message);
      setChoices(imported.rows.map((row) => ({
        life: lifeKey(row.prediction), chosen: false, elect179: true, electBonus: true, workVehicle: false,
      })));
      setView('lives');
      setReport(null);
      setReplacing(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setImporting(false);
    }
  }, [setup, business]);

  // ------------------------------------------------------------- steps 3-4

  const rows = useMemo(() => (data && setup ? data.rows.map((row, index) => ({
    row, index, choice: choices[index], prediction: predictions[index] ?? row.prediction, issues: rowIssues(row, setup.year),
  })) : []), [data, setup, choices, predictions]);
  const included = useMemo(() => rows.filter((r) => !r.issues.length && r.choice?.life), [rows]);
  const needLife = rows.filter((r) => !r.issues.length && !r.choice?.life).length;
  const unusable = rows.filter((r) => r.issues.length);

  const request = useMemo<AdditionReportRequest | null>(() => {
    if (!setup || !included.length || relifing) return null;
    const assets: AdditionAssetInput[] = included.map(({ row, choice }) => {
      const [assetClass, years] = choice.life.split('|');
      return {
        asset_id: row.asset_id, description: row.description, acquired: row.acquired!, cost: row.cost!,
        asset_class: assetClass, recovery_years: years || null,
        elect_179: choice.elect179, elect_bonus: choice.electBonus, suv_cap_exempt: choice.workVehicle,
      };
    });
    return { tax_year: setup.year, state: setup.state, assets };
  }, [setup, included, relifing]);
  const requestKey = request ? JSON.stringify(request) : '';

  // Recompute on the server whenever a life, an election, the year or the
  // state changes - keyed on the request's content, so a re-render that
  // changes nothing sends nothing.
  useEffect(() => {
    if (!request) return;
    const mine = ++sequence.current;
    const key = requestKey;
    const timer = window.setTimeout(() => {
      api.depreciation.additionsReport(request)
        .then((computed) => { if (mine === sequence.current) setReport({ key, value: computed }); })
        .catch((caught: unknown) => {
          if (mine !== sequence.current) return;
          const details = caught instanceof ApiError ? (caught.details as { errors?: string[] }) : undefined;
          setReportErrors({ key, errors: details?.errors ?? [caught instanceof Error ? caught.message : String(caught)] });
        });
    }, 250);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey]);

  const current = report && report.key === requestKey ? report.value : null;
  const errors = reportErrors && reportErrors.key === requestKey ? reportErrors.errors : [];
  const computing = Boolean(request) && !current && !errors.length;

  const exportFile = useCallback(async () => {
    if (!request) return;
    setExporting(true);
    try {
      await api.depreciation.exportAdditions(request);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setExporting(false);
    }
  }, [request]);

  const change = (index: number, patch: Partial<Choice>) =>
    setChoices((prior) => prior.map((c, i) => (i === index ? { ...c, ...patch } : c)));

  const eligible = useCallback((life: string, kind: 'sec179' | 'bonus') => {
    const cls = classInfo.get(life.split('|')[0]);
    return Boolean(kind === 'sec179' ? cls?.section_179_eligible : cls?.bonus_eligible);
  }, [classInfo]);

  // "All" boxes act on the assets in the report that can take the election.
  const electable = useMemo(() => ({
    sec179: included.filter((r) => eligible(r.choice.life, 'sec179')).map((r) => r.index),
    bonus: included.filter((r) => eligible(r.choice.life, 'bonus')).map((r) => r.index),
  }), [included, eligible]);
  const setAll = (indexes: number[], patch: Partial<Choice>) =>
    setChoices((prior) => prior.map((c, i) => (indexes.includes(i) ? { ...c, ...patch } : c)));


  const step = !setup || editingSetup ? 1 : !data ? 2 : view === 'lives' ? 3 : 4;
  const stepClass = (n: number) => `dw-step ${n === step ? 'current' : n < step ? 'done' : 'locked'}`;
  const figuresFor = (index: number) => {
    const position = included.findIndex((r) => r.index === index);
    return position >= 0 && current ? current.rows[position] ?? null : null;
  };
  const stateGroup = Boolean(setup?.state);

  return (
    <Panel
      icon={<FileSpreadsheet size={18} />}
      title="Import an asset list"
      subtitle="Choose the jurisdiction and year, upload the list, review each life, then read the report. AI suggests lives only; the engine computes every figure."
    >
      <ol className="dw-steps">
        {/* ----------------------------------------------------------- 1 */}
        <li className={stepClass(1)} aria-current={step === 1 ? 'step' : undefined}>
          <div className="dw-step-head">
            <span className="dw-step-num" aria-hidden="true">{step > 1 ? <Check size={14} /> : 1}</span>
            <h3>Jurisdiction and tax year</h3>
          </div>
          {step === 1 ? (
            <>
              <div className="dw-step-grid" style={{ marginTop: 16 }}>
                <div className="dw-field">
                  <Label htmlFor={`${id}-year`} info={`Rules are verified for ${rules.supported_years[0]}–${rules.supported_years.at(-1)}.`}>Tax year</Label>
                  <select id={`${id}-year`} value={draft.year} onChange={(e) => setDraft({ ...draft, year: Number(e.target.value) })}>
                    {[...rules.supported_years].reverse().map((y) => <option key={y} value={y}>{y}</option>)}
                  </select>
                </div>
                <div className="dw-field">
                  <Label htmlFor={`${id}-state`} info="Federal only, or a state: the state's figures use its own verified rules for the year, never another's.">Jurisdiction</Label>
                  <select id={`${id}-state`} value={draft.state ?? ''} onChange={(e) => setDraft({ ...draft, state: e.target.value || null })}>
                    <option value="">Federal only</option>
                    {sortedStates.map((s) => (
                      <option key={s.code} value={s.code}>
                        Federal + {s.name}{s.status_by_year[String(draft.year)] !== 'verified' && s.status_by_year[String(draft.year)] !== 'no_income_tax' ? ' (rules not yet verified)' : ''}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="dw-step-actions">
                <button type="button" className="btn primary" onClick={() => void applySetup()}>
                  {data ? 'Apply and recompute' : 'Continue'}
                </button>
                {setup && <button type="button" className="btn ghost" onClick={() => { setDraft(setup); setEditingSetup(false); }}>Cancel</button>}
              </div>
            </>
          ) : setup && (
            <div className="dw-step-actions">
              <span className="dw-step-summary"><strong>{stateName(setup.state) === 'Federal only' ? 'Federal' : `Federal + ${stateName(setup.state)}`}</strong> · tax year <strong>{setup.year}</strong></span>
              <button type="button" className="btn ghost sm" onClick={() => setEditingSetup(true)}><Pencil size={13} aria-hidden="true" /> Change</button>
            </div>
          )}
        </li>

        {/* ----------------------------------------------------------- 2 */}
        <li className={stepClass(2)} aria-current={step === 2 ? 'step' : undefined}>
          <div className="dw-step-head">
            <span className="dw-step-num" aria-hidden="true">{data && step > 2 ? <Check size={14} /> : 2}</span>
            <h3>Upload the asset list</h3>
          </div>
          {!setup || editingSetup ? (
            <p className="dw-hint" id={`${id}-locked`}>Choose the jurisdiction and tax year first - each asset's life and every figure depend on them.</p>
          ) : data && !replacing ? (
            <div className="dw-step-actions">
              <span className="dw-step-summary"><strong>{data.rows.length}</strong> {data.rows.length === 1 ? 'row' : 'rows'} read from the upload.</span>
              <button type="button" className="btn ghost sm" onClick={() => setReplacing(true)}><Upload size={13} aria-hidden="true" /> Upload a different list</button>
            </div>
          ) : (
            <div style={{ marginTop: 16 }}>
              <div className="dw-step-grid">
                <div className="dw-field">
                  <Label htmlFor={`${id}-business`} info="Optional. Helps the AI pick the right activity class (e.g. a dealership's shop equipment is 5-year).">Business type</Label>
                  <input id={`${id}-business`} type="text" maxLength={120} value={business}
                    placeholder="e.g. Vehicle dealership with service department" onChange={(e) => setBusiness(e.target.value)} />
                </div>
              </div>
              <input ref={fileInput} type="file" hidden accept=".xlsx,.xlsm,.csv"
                onChange={(e) => { const file = e.target.files?.[0]; if (file) void upload(file); e.target.value = ''; }} />
              <div
                className={`dropzone ${dragging ? 'dragging' : ''}`}
                role="button" tabIndex={0} aria-busy={importing}
                aria-label={importing ? 'Reading the file and deciding lives' : 'Upload an Excel or CSV asset list'}
                onClick={() => !importing && fileInput.current?.click()}
                onKeyDown={(e) => { if ((e.key === 'Enter' || e.key === ' ') && !importing) { e.preventDefault(); fileInput.current?.click(); } }}
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => { e.preventDefault(); setDragging(false); const file = e.dataTransfer.files?.[0]; if (file && !importing) void upload(file); }}
              >
                <span className="dz-icon" aria-hidden="true">{importing ? <Spinner /> : <Upload size={24} />}</span>
                <span className="dz-title">{importing ? 'Reading the list and deciding lives…' : data ? 'Upload a different list' : 'Drop an asset list here, or choose a file'}</span>
                <span className="dz-hint">Excel (.xlsx) or CSV with Asset #, Description, Date Acquired and Cost; a Life column is optional.</span>
              </div>
              <div className="dw-step-actions">
                <button type="button" className="btn sm" onClick={() => void api.depreciation.additionsTemplate().catch((c) => setError(String(c)))}>
                  <Download size={14} aria-hidden="true" /> Download template
                </button>
                {data && <button type="button" className="btn ghost sm" onClick={() => setReplacing(false)}>Keep the current list</button>}
              </div>
            </div>
          )}
          {error && (
            <div className="notice danger" role="alert" style={{ marginTop: 12 }}>
              <AlertTriangle size={16} aria-hidden="true" /><div><strong>Could not import</strong><p>{error}</p></div>
            </div>
          )}
          {unusable.length > 0 && step >= 3 && (
            <div className="notice warning" style={{ marginTop: 12 }}>
              <AlertTriangle size={16} aria-hidden="true" />
              <div>
                <strong>{unusable.length} {unusable.length === 1 ? 'row is' : 'rows are'} left out of the report</strong>
                <ul className="dw-issues">
                  {unusable.map(({ row, issues }) => (
                    <li key={row.row}>Row {row.row}{row.asset_id ? ` (asset ${row.asset_id})` : ''}: {issues.map((i) => `${i.column} - ${i.message}`).join('; ')}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </li>

        {/* ----------------------------------------------------------- 3 */}
        <li className={stepClass(3)} aria-current={step === 3 ? 'step' : undefined}>
          <div className="dw-step-head">
            <span className="dw-step-num" aria-hidden="true">{step > 3 ? <Check size={14} /> : 3}</span>
            <h3>Review each asset's life</h3>
          </div>
          {step === 3 && data && setup && (
            <div style={{ marginTop: 16 }}>
              {(message || relifing) && (
                <div className="notice info" role="status"><Sparkles size={16} aria-hidden="true" /><div><p>{relifing ? `Deciding lives for ${setup.year}…` : message}</p></div></div>
              )}
              <p className="dw-hint">
                Lives for {setup.year}. Each suggestion shows its reason; change any that are wrong.
                {needLife > 0 && <strong> {needLife} still {needLife === 1 ? 'needs' : 'need'} a life.</strong>}
              </p>
              <div className="dw-table-wrap" style={{ marginTop: 12 }}>
                <table className="dw-table dw-import-table">
                  <thead>
                    <tr><th>Asset #</th><th className="dw-desc">Description</th><th>Date acquired</th><th className="num">Cost</th><th>Life</th></tr>
                  </thead>
                  <tbody>
                    {rows.map(({ row, index, choice, prediction: p, issues }) => (
                      <tr key={row.row} className={issues.length ? 'dw-import-bad' : ''}>
                        <td>{row.asset_id}</td>
                        <td className="dw-desc">{row.description}{issues.length > 0 && <div className="dw-import-problem">{issues.map((i) => `${i.column}: ${i.message}`).join('; ')}</div>}</td>
                        <td>{row.acquired ?? '—'}</td>
                        <td className="num">{row.cost ? money2(row.cost) : '—'}</td>
                        <td>
                          <div className="dw-import-life">
                            <select aria-label={`Life for asset ${row.asset_id}`} aria-describedby={`${id}-why-${index}`}
                              value={choice?.life ?? ''} disabled={issues.length > 0 || relifing}
                              onChange={(e) => change(index, { life: e.target.value, chosen: true })}>
                              <option value="">Choose a life…</option>
                              {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                            </select>
                            <span className={`badge ${choice?.chosen ? 'info' : p.source === 'none' ? 'warning' : p.source === 'ai' ? 'accent' : 'neutral'}`}>
                              {choice?.chosen ? 'Changed' : SOURCE_LABEL[p.source]}
                            </span>
                          </div>
                          <div className="dw-reason" id={`${id}-why-${index}`}>
                            {choice?.chosen ? 'Chosen by you.' : p.reason}{!choice?.chosen && p.confidence ? ` Confidence: ${p.confidence}.` : ''}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="dw-step-actions">
                <button type="button" className="btn primary" disabled={!included.length || relifing} onClick={() => setView('report')}>
                  Show the report{included.length ? ` (${included.length} ${included.length === 1 ? 'asset' : 'assets'})` : ''}
                </button>
              </div>
            </div>
          )}
        </li>

        {/* ----------------------------------------------------------- 4 */}
        <li className={stepClass(4)} aria-current={step === 4 ? 'step' : undefined}>
          <div className="dw-step-head">
            <span className="dw-step-num" aria-hidden="true">4</span>
            <h3>Report</h3>
          </div>
          {step === 4 && setup && (
            <div style={{ marginTop: 16 }}>
              <div className="dw-step-actions" style={{ marginTop: 0, marginBottom: 12 }}>
                <button type="button" className="btn" onClick={() => setView('lives')}><Pencil size={14} aria-hidden="true" /> Back to lives</button>
                <button type="button" className="btn primary" onClick={() => void exportFile()}
                  disabled={!current || exporting}>
                  <FileSpreadsheet size={15} aria-hidden="true" /> {exporting ? 'Exporting…' : 'Export Excel'}
                </button>
              </div>
              <ReportNotices report={current} errors={errors} setup={setup} />
              <p className="dw-hint" role="status" aria-live="polite" style={{ marginBottom: 8 }}>
                {computing ? <><Spinner /> Computing…</> : current ? `Figures for ${current.rows.length} ${current.rows.length === 1 ? 'asset' : 'assets'}, tax year ${current.tax_year}.` : ''}
              </p>
              <div className="dw-table-wrap" aria-busy={computing}>
                <table className="dw-table dw-import-table dw-report">
                  <thead>
                    <tr className="dw-group">
                      {/* Empty spacer cells are data cells, not headers without names. */}
                      <td className="dw-pin" /><td className="dw-pin dw-desc" /><td colSpan={3} />
                      <th colSpan={4} className="dw-fed">Federal</th>
                      {stateGroup && <th colSpan={4} className="dw-st">{stateName(setup.state)}</th>}
                    </tr>
                    <tr>
                      <th className="dw-pin">Asset #</th><th className="dw-pin dw-desc">Description</th><th>Life</th><th className="num">Cost</th>
                      <th className="dw-col-check">
                        Elections
                        <div className="dw-elect dw-all">
                          <AllBox label="All Sec 179" total={electable.sec179.length}
                            on={electable.sec179.filter((i) => choices[i].elect179).length}
                            onChange={(on) => setAll(electable.sec179, { elect179: on })} />
                          <AllBox label="All bonus" total={electable.bonus.length}
                            on={electable.bonus.filter((i) => choices[i].electBonus).length}
                            onChange={(on) => setAll(electable.bonus, { electBonus: on })} />
                        </div>
                      </th>
                      <th className="num dw-fed">Sec 179</th><th className="num dw-fed">Bonus</th><th className="num dw-fed">MACRS</th><th className="num dw-fed">Total</th>
                      {stateGroup && <>
                        <th className="num dw-st">Sec 179</th>
                        <th className="num dw-st">
                          <span className="dw-th-tip">
                            Bonus
                            {current?.state?.status === 'computed' && !current.state.bonus_allowed && <span className="badge warning sm">Not allowed</span>}
                            {current?.state?.bonus_note && <span className="dw-tip-below"><InfoTip text={current.state.bonus_note} /></span>}
                          </span>
                        </th>
                        <th className="num dw-st">MACRS</th><th className="num dw-st">Total</th>
                      </>}
                    </tr>
                  </thead>
                  <tbody>
                    {/* Rows and their elections stay put while the report is recomputed;
                        only the figures go blank until the new ones arrive - never stale. */}
                    {included.map(({ row, index, choice }) => {
                      const figure = figuresFor(index);
                      const cls = classInfo.get(choice.life.split('|')[0]);
                      const can179 = Boolean(cls?.section_179_eligible);
                      const canBonus = Boolean(cls?.bonus_eligible);
                      const label = `${row.asset_id} ${row.description}`.trim();
                      return (
                        <tr key={row.row}>
                          <td className="dw-pin">{row.asset_id}</td>
                          <td className="dw-pin dw-desc">{row.description}</td>
                          <td className="dw-life">{figure ? `${figure.life}-yr` : '—'}</td>
                          <td className="num">{money2(row.cost!)}</td>
                          <td className="dw-col-check">
                            <div className="dw-elect">
                              <label className="dw-check">
                                <input type="checkbox" checked={can179 && choice.elect179} disabled={!can179}
                                  aria-describedby={!can179 ? `${id}-no179-${index}` : undefined}
                                  onChange={(e) => change(index, { elect179: e.target.checked })} />
                                Sec 179<span className="sr-only"> for {label}</span>
                              </label>
                              <label className="dw-check">
                                <input type="checkbox" checked={canBonus && choice.electBonus} disabled={!canBonus}
                                  aria-describedby={!canBonus ? `${id}-nobonus-${index}` : undefined}
                                  onChange={(e) => change(index, { electBonus: e.target.checked })} />
                                Bonus<span className="sr-only"> for {label}</span>
                              </label>
                              {cls?.suv_cap && (
                                <label className="dw-check" title="Cargo vans, work trucks and similar are outside the heavy-SUV Section 179 cap">
                                  <input type="checkbox" checked={choice.workVehicle} onChange={(e) => change(index, { workVehicle: e.target.checked })} />
                                  Work vehicle<span className="sr-only"> for {label}</span>
                                </label>
                              )}
                            </div>
                            {!can179 && <div className="dw-hint" id={`${id}-no179-${index}`}>{figure?.sec179_reason || 'Not section 179 property.'}</div>}
                            {!canBonus && <div className="dw-hint" id={`${id}-nobonus-${index}`}>{figure?.bonus_reason || 'Not qualified property for bonus.'}</div>}
                          </td>
                          <td className="num dw-fed">{figure ? money2(figure.federal.sec179) : '—'}</td>
                          <td className="num dw-fed">{figure ? money2(figure.federal.bonus) : '—'}</td>
                          <td className="num dw-fed">{figure ? money2(figure.federal.macrs) : '—'}</td>
                          <td className="num dw-fed dw-total">{figure ? money2(figure.federal.total) : '—'}</td>
                          {stateGroup && <>
                            <td className="num dw-st">{figure?.state ? money2(figure.state.sec179) : '—'}</td>
                            <td className="num dw-st">{figure?.state ? money2(figure.state.bonus) : '—'}</td>
                            <td className="num dw-st">{figure?.state ? money2(figure.state.macrs) : '—'}</td>
                            <td className="num dw-st dw-total">{figure?.state ? money2(figure.state.total) : '—'}</td>
                          </>}
                        </tr>
                      );
                    })}
                  </tbody>
                  {current && !computing && (
                    <tfoot>
                      <tr>
                        <td className="dw-pin" /><th className="dw-pin dw-desc">Total ({current.rows.length} {current.rows.length === 1 ? 'asset' : 'assets'})</th>
                        <td /><td className="num">{money2(current.totals.cost)}</td>
                        <td />
                        <td className="num dw-fed">{money2(current.totals.federal.sec179)}</td>
                        <td className="num dw-fed">{money2(current.totals.federal.bonus)}</td>
                        <td className="num dw-fed">{money2(current.totals.federal.macrs)}</td>
                        <td className="num dw-fed">{money2(current.totals.federal.total)}</td>
                        {stateGroup && <>
                          <td className="num dw-st">{current.totals.state ? money2(current.totals.state.sec179) : '—'}</td>
                          <td className="num dw-st">{current.totals.state ? money2(current.totals.state.bonus) : '—'}</td>
                          <td className="num dw-st">{current.totals.state ? money2(current.totals.state.macrs) : '—'}</td>
                          <td className="num dw-st">{current.totals.state ? money2(current.totals.state.total) : '—'}</td>
                        </>}
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
            </div>
          )}
        </li>
      </ol>
    </Panel>
  );
}

/** A select-all box: ticked when every eligible asset is, mixed when some are. */
function AllBox({ label, total, on, onChange }: {
  label: string; total: number; on: number; onChange: (on: boolean) => void;
}) {
  const all = total > 0 && on === total;
  return (
    <label className="dw-check">
      <input
        type="checkbox" checked={all} disabled={!total}
        ref={(el) => { if (el) el.indeterminate = on > 0 && !all; }}
        onChange={() => onChange(!all)}
      />
      {label}
    </label>
  );
}

function ReportNotices({ report, errors, setup }: { report: AdditionReport | null; errors: string[]; setup: Setup }) {
  return (
    <div className="dw-notices" style={{ marginBottom: 12 }}>
      {errors.length > 0 && (
        <div className="notice danger" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          <div><strong>Some assets need attention</strong><ul>{errors.map((e) => <li key={e}>{e}</li>)}</ul></div>
        </div>
      )}
      {report?.state && report.state.status !== 'computed' && (
        <div className="notice warning">
          <AlertTriangle size={16} aria-hidden="true" />
          <div><strong>{report.state.name}: no state figures</strong><p>{report.state.message}</p></div>
        </div>
      )}
      {report && report.elect_out_classes.length > 0 && (
        <div className="notice info" role="status">
          <Sparkles size={16} aria-hidden="true" />
          <div><p>
            Bonus is elected out for all {report.elect_out_classes.map((p) => `${p}-year`).join(', ')} property placed in
            service in {setup.year}: the election is made by class (IRC 168(k)(7)), so it covers every asset with that life.
          </p></div>
        </div>
      )}
      {report?.state && report.state.status === 'computed' && report.state.bonus_note && (
        <div className="notice info"><Sparkles size={16} aria-hidden="true" /><div><p>{report.state.bonus_note}</p></div></div>
      )}
      {report && (
        <p className="dw-hint">
          Tax year {setup.year}: Section 179 first, then bonus on the basis left, then MACRS on the rest. {report.life_basis}
          {' '}An asset list carries no business income, so the Section 179 income limit is not applied here.
          {report.section_179 && Number(report.section_179.reduction) > 0 && (
            <> Section 179 limit {money2(report.section_179.limit)} reduced by {money2(report.section_179.reduction)} for purchases over {money2(report.section_179.threshold)}.</>
          )}
        </p>
      )}
      {report?.warnings.map((w) => (
        <div key={w} className="notice warning"><AlertTriangle size={16} aria-hidden="true" /><div><p>{w}</p></div></div>
      ))}
    </div>
  );
}
