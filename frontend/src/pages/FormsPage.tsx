/**
 * IRS Forms library: federal, business and state forms as tiles.
 *
 * Every download goes to the publishing agency's own URL - nothing is
 * re-hosted, so the user always gets the agency's current file. Form
 * metadata comes from reference_data/forms/*.json; a state without verified
 * entries shows "Forms not yet verified for this state" and the agency link,
 * never another state's forms.
 */

import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Download, ExternalLink as ExternalIcon, MessageSquare } from 'lucide-react';

import { api, type FormEntry, type FormsLibrary } from '../api/client';
import { ExternalLink, Section, StateSelect, TabPanel, Tabs } from '../components/workspace/common';
import { assistantLink, useTaxContext } from '../context/TaxContext';
import { yearWithin } from '../lib/taxYear';
import { useAsync } from '../hooks/useApi';
import '../styles/workspace.css';

export type FormsTab = 'all' | 'federal' | 'business' | 'state';

const TABS: { key: FormsTab; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'federal', label: 'Federal' },
  { key: 'business', label: 'Business' },
  { key: 'state', label: 'State' },
];

function normalize(value: string): string {
  return value.toLowerCase().replace(/[\s\-–—()]/g, '');
}

/** Search by form number (ignoring spaces, dashes and brackets) or by words in the title and description. */
export function matchesQuery(form: FormEntry, query: string): boolean {
  const q = query.trim();
  if (!q) return true;
  if (normalize(form.form_number).includes(normalize(q))) return true;
  const haystack = `${form.title} ${form.one_liner} ${form.category}`.toLowerCase();
  return q.toLowerCase().split(/\s+/).every((word) => haystack.includes(word));
}

export function filterForms(
  library: FormsLibrary,
  { tab, query, category, state }: { tab: FormsTab; query: string; category: string; state: string | null },
): FormEntry[] {
  const stateForms = state ? library.state_forms.filter((f) => f.state === state) : [];
  let pool: FormEntry[];
  if (tab === 'federal') pool = library.forms.filter((f) => f.audience === 'federal');
  else if (tab === 'business') pool = library.forms.filter((f) => f.audience === 'business');
  else if (tab === 'state') pool = stateForms;
  else pool = [...library.forms, ...stateForms];
  return pool.filter((f) => (!category || f.category === category) && matchesQuery(f, query));
}

/** The year-appropriate link for an annual form, and what to tell the user about it. */
export function downloadFor(form: FormEntry, year: number): { url: string; note: string } {
  const revisionYear = form.latest_revision && /^\d{4}$/.test(form.latest_revision) ? Number(form.latest_revision) : null;
  if (form.audience === 'state') {
    if (form.tax_year && form.tax_year !== year) {
      return { url: form.pdf_url, note: `This link is the ${form.tax_year} form. Check the agency for ${year}.` };
    }
    return { url: form.pdf_url, note: '' };
  }
  if (!form.annual || revisionYear === null) {
    return { url: form.pdf_url, note: form.latest_revision ? `Current revision (${form.latest_revision}).` : '' };
  }
  if (year < revisionYear && form.prior_year_pdf_pattern) {
    return { url: form.prior_year_pdf_pattern.replace('{year}', String(year)), note: `${year} version from IRS prior-year forms.` };
  }
  if (year > revisionYear) {
    return { url: form.pdf_url, note: `The ${year} form is not published yet; this is the ${revisionYear} form.` };
  }
  return { url: form.pdf_url, note: '' };
}

export default function FormsPage() {
  const [params, setParams] = useSearchParams();
  const { stateCode, setStateCode, taxYear, setTaxYear } = useTaxContext();
  const library = useAsync(() => api.reference.forms(), []);
  const [tab, setTab] = useState<FormsTab>((params.get('tab') as FormsTab) || 'all');
  const [query, setQuery] = useState(params.get('q') ?? '');
  const [category, setCategory] = useState('');

  // A link may name the state (e.g. from a calendar deadline); it becomes the shared selection.
  const linkedState = params.get('state');
  useEffect(() => {
    if (linkedState) setStateCode(linkedState);
  }, [linkedState, setStateCode]);

  const data = library.data;
  const years = data?.supported_years ?? [];
  const year = yearWithin(taxYear, years);
  const state = stateCode && data?.state_agencies[stateCode] ? stateCode : null;
  const stateOptions = data ? Object.entries(data.state_agencies).map(([code, s]) => ({ code, name: s.name })) : [];

  const results = useMemo(
    () => (data ? filterForms(data, { tab, query, category, state }) : []),
    [data, tab, query, category, state],
  );
  const stateVerified = state ? data?.states_with_forms.includes(state) : false;

  const updateQuery = (value: string) => {
    setQuery(value);
    const next = new URLSearchParams(params);
    if (value) next.set('q', value);
    else next.delete('q');
    setParams(next, { replace: true });
  };

  return (
    <div className="ws">
      <Section title="IRS Forms library" loading={library.loading} error={library.error} onRetry={library.reload}>
        {data && (
          <>
            <div className="ws-filters" role="search" style={{ marginBottom: 12 }}>
              <div className="field grow">
                <label htmlFor="forms-search">Search by form number or keyword</label>
                <input id="forms-search" type="search" value={query} placeholder="e.g. 4562, depreciation, W-9"
                  onChange={(e) => updateQuery(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="forms-category">Category</label>
                <select id="forms-category" value={category} onChange={(e) => setCategory(e.target.value)}>
                  <option value="">All categories</option>
                  {data.categories.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
                </select>
              </div>
              <div className="field">
                <label htmlFor="forms-year">Tax year</label>
                <select id="forms-year" value={year} onChange={(e) => setTaxYear(Number(e.target.value))}>
                  {[...years].sort((a, b) => b - a).map((y) => <option key={y} value={y}>{y}</option>)}
                </select>
              </div>
              <StateSelect states={stateOptions} value={state} onChange={setStateCode} label="State" noneLabel="No state" />
            </div>

            <Tabs tabs={TABS} value={tab} onChange={(k) => setTab(k as FormsTab)} label="Form groups" idPrefix="forms" />
            <TabPanel idPrefix="forms" active={tab}>
              <div style={{ paddingTop: 12 }}>
                {(tab === 'state' || tab === 'all') && state && !stateVerified && (
                  <div className="si-unverified" style={{ marginBottom: 12 }} role="status">
                    <strong>Forms not yet verified for this state</strong>
                    Find {data.state_agencies[state].name} forms at{' '}
                    <ExternalLink href={data.state_agencies[state].agency_url}>{data.state_agencies[state].agency}</ExternalLink>.
                  </div>
                )}
                {tab === 'state' && !state && (
                  <p className="ws-note">Choose a state above to see its forms.</p>
                )}
                <p className="ws-note" aria-live="polite">{results.length} form{results.length === 1 ? '' : 's'}</p>
                {results.length === 0 && (tab !== 'state' || stateVerified) ? (
                  <p className="ws-note">No forms match. Try a form number such as 1065 or a word such as payroll.</p>
                ) : (
                  <ul className="form-grid" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                    {results.map((form) => (
                      <FormTile key={form.id} form={form} year={year}
                        categoryLabel={data.categories.find((c) => c.key === form.category)?.label ?? form.category}
                        agencyName={form.state ? data.state_agencies[form.state]?.agency : undefined} />
                    ))}
                  </ul>
                )}
              </div>
            </TabPanel>
          </>
        )}
      </Section>
    </div>
  );
}

function FormTile({
  form, year, categoryLabel, agencyName,
}: { form: FormEntry; year: number; categoryLabel: string; agencyName?: string }) {
  const { url, note } = downloadFor(form, year);
  const broken = form.link_status === 'broken';
  const where = form.state ? (agencyName ?? 'the agency site') : 'IRS.gov';
  const question = `What is Form ${form.form_number} (${form.title}) used for, who must file it, and when is it due?`;
  return (
    <li className="form-tile">
      <div className="ft-top">
        <span className="form-badge">{form.form_number}</span>
        {form.state && <span className="ws-chip purple">{form.state}</span>}
      </div>
      <h3>{form.title}</h3>
      <p>{form.one_liner}</p>
      <div className="ft-meta">
        <span className="ws-chip">{categoryLabel}</span>
        {form.latest_revision && <span className="ws-chip info">{/^\d{4}$/.test(form.latest_revision) ? `${form.latest_revision} revision` : form.latest_revision}</span>}
        {!form.one_liner_reviewed && (
          <span className="ws-chip warning" title="This description is a draft awaiting review against the form's instructions.">
            Description pending review
          </span>
        )}
      </div>
      {note && <span className="ws-note">{note}</span>}
      {broken && (
        <span className="ws-note" style={{ color: 'var(--danger)' }}>
          The PDF link failed its last check. Use the {where} page instead.
        </span>
      )}
      <div className="ft-actions">
        <a className="ws-link-btn primary" href={url} target="_blank" rel="noopener noreferrer"
          aria-disabled={broken ? 'true' : undefined} tabIndex={broken ? -1 : undefined}
          aria-label={`Download Form ${form.form_number} (PDF, opens ${where})`}>
          <Download size={14} aria-hidden="true" /> Download
        </a>
        <a className="ws-link-btn" href={form.source_page_url} target="_blank" rel="noopener noreferrer"
          aria-label={`Open on ${form.state ? 'agency site' : 'IRS.gov'}: Form ${form.form_number} (opens in a new tab)`}>
          <ExternalIcon size={14} aria-hidden="true" /> Open on {form.state ? 'agency site' : 'IRS.gov'}
        </a>
        <Link to={assistantLink(question, form.state)} className="ws-note">
          <MessageSquare size={13} aria-hidden="true" /> Ask the chatbot about this form
        </Link>
      </div>
      {form.last_verified && <span className="ws-note">Link checked {form.last_verified}</span>}
    </li>
  );
}
