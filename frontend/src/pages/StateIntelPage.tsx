/**
 * State Intelligence: one state's apportionment, nexus, federal conformity,
 * rates and filing requirements for the selected tax year - or two side by side.
 *
 * Everything shown carries its source and the date it was checked. A section
 * that has not been verified for the year says "Not yet verified" and links
 * the agency; nothing is filled in from another state or a model.
 * Federal Conformity is the depreciation calculator's own table.
 */

import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { MessageSquare } from 'lucide-react';

import { api, type StateIntelProfile, type StateSectionData } from '../api/client';
import { ExternalLink, Section, StateSelect, TabPanel, Tabs } from '../components/workspace/common';
import { assistantLink, useTaxContext } from '../context/TaxContext';
import { yearWithin } from '../lib/taxYear';
import { useAsync } from '../hooks/useApi';
import { formatShort } from '../lib/dates';
import '../styles/workspace.css';

const SECTION_TABS = [
  { key: 'apportionment', label: 'Apportionment' },
  { key: 'nexus', label: 'Nexus' },
  { key: 'conformity', label: 'Federal Conformity' },
  { key: 'rates', label: 'Tax Rates' },
  { key: 'filing', label: 'Filing Requirements' },
];

const TOPIC_QUESTIONS: Record<string, string> = {
  apportionment: 'How does {state} apportion multistate business income for tax year {year}, and how are sales of services sourced?',
  nexus: 'What creates income tax and sales tax nexus in {state} for tax year {year}, including economic nexus thresholds and P.L. 86-272?',
  conformity: 'How does {state} conform to the Internal Revenue Code for tax year {year}, and what does it decouple from (bonus depreciation, Section 179, 163(j), 174)?',
  rates: 'What are the {state} individual, corporate and sales tax rates for tax year {year}?',
  filing: 'What are the {state} filing requirements, due dates, extensions and PTET options for tax year {year}?',
};

export default function StateIntelPage() {
  const { code } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { stateCode, setStateCode, taxYear, setTaxYear } = useTaxContext();
  const listing = useAsync(() => api.reference.states(), []);
  const [tab, setTab] = useState(params.get('tab') ?? 'apportionment');
  const compareCode = params.get('compare');

  const states = listing.data?.states ?? [];
  const years = listing.data?.supported_years ?? [];
  const year = yearWithin(taxYear, years);
  const selected = code?.toUpperCase() ?? null;
  const covered = (c: string | null) => !!c && states.some((s) => s.code === c);

  // The URL is the source of truth on this page; keep the shared selection in step with it.
  useEffect(() => {
    if (selected && selected !== stateCode) setStateCode(selected);
  }, [selected, stateCode, setStateCode]);
  useEffect(() => {
    if (!selected && stateCode && covered(stateCode)) navigate(`/states/${stateCode}`, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, stateCode, states.length]);

  const choose = (next: string | null) => {
    setStateCode(next);
    navigate(next ? `/states/${next}${compareCode ? `?compare=${compareCode}` : ''}` : '/states');
  };
  const setCompare = (next: string | null) => {
    const updated = new URLSearchParams(params);
    if (next) updated.set('compare', next);
    else updated.delete('compare');
    setParams(updated);
  };

  return (
    <div className="ws">
      <Section title="State Intelligence" className="si-hero" loading={listing.loading} error={listing.error} onRetry={listing.reload}>
        <p className="si-lead">
          Apportionment, nexus, federal conformity, rates and filing requirements for the 50 states and DC.
          Every figure carries its source and the date it was checked.
        </p>
        <div className="ws-filters">
          <StateSelect states={states} value={covered(selected) ? selected : null} onChange={choose} label="State" />
          <div className="field">
            <label htmlFor="si-year">Tax year</label>
            <select id="si-year" value={year} onChange={(e) => setTaxYear(Number(e.target.value))}>
              {[...years].sort((a, b) => b - a).map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
          <StateSelect states={states.filter((s) => s.code !== selected)} value={compareCode} onChange={setCompare}
            label="Compare with" noneLabel="No comparison" />
        </div>
        {selected && !covered(selected) && states.length > 0 && (
          <p className="ws-note" role="status" style={{ marginTop: 10 }}>
            {selected} is not covered here (State Intelligence covers the 50 states and DC). Choose a state above.
          </p>
        )}
        {!selected && <p className="ws-note" style={{ marginTop: 10 }}>Choose a state to see its profile.</p>}
      </Section>

      {selected && covered(selected) && (
        <>
          <Tabs tabs={SECTION_TABS} value={tab} onChange={setTab} label="State topics" idPrefix="si" />
          <TabPanel idPrefix="si" active={tab}>
            {compareCode && covered(compareCode) ? (
              <div className="compare-grid">
                <StateColumn code={selected} year={year} tab={tab} compact />
                <StateColumn code={compareCode} year={year} tab={tab} compact />
              </div>
            ) : (
              <StateColumn code={selected} year={year} tab={tab} />
            )}
          </TabPanel>
          <p className="ws-disclaimer">{listing.data?.disclaimer}</p>
        </>
      )}
    </div>
  );
}

function StateColumn({ code, year, tab, compact = false }: { code: string; year: number; tab: string; compact?: boolean }) {
  const profile = useAsync(() => api.reference.state(code, year), [code, year]);
  return (
    <Section
      title={profile.data ? `${profile.data.name} · ${year}` : code}
      loading={profile.loading}
      error={profile.error}
      onRetry={profile.reload}
    >
      {profile.data && <StateBody profile={profile.data} tab={tab} compact={compact} />}
    </Section>
  );
}

function StateBody({ profile, tab, compact }: { profile: StateIntelProfile; tab: string; compact: boolean }) {
  const section = profile.sections.find((s) => s.key === tab) ?? profile.sections[0];
  const verifiedCount = profile.sections.filter((s) => s.status === 'verified').length;
  const provisionalCount = profile.sections.filter((s) => s.status === 'provisional').length;
  const question = TOPIC_QUESTIONS[section.key].replace('{state}', profile.name).replace('{year}', String(profile.tax_year));
  return (
    <div className="stack">
      <div className="si-head">
        <span className="si-code" aria-hidden="true">{profile.code}</span>
        <div className="si-head-main">
          <div className="ws-note">
            Agency: <ExternalLink href={profile.agency.url}>{profile.agency.name}</ExternalLink>
          </div>
          <div className="si-facts">
            {profile.quick_facts.map((f) => <span key={f} className="ws-chip">{f}</span>)}
            <span className={`ws-chip ${verifiedCount === profile.sections.length ? 'success' : 'warning'}`}>
              {verifiedCount} of {profile.sections.length} topics verified for {profile.tax_year}
            </span>
            {provisionalCount > 0 && (
              <span className="ws-chip warning">{provisionalCount} provisional</span>
            )}
          </div>
        </div>
      </div>
      <SectionView section={section} compact={compact} />
      <div className="ws-btn-row">
        <Link to={assistantLink(question, profile.code)} className="ws-link-btn">
          <MessageSquare size={14} aria-hidden="true" /> Ask the chatbot about {profile.name} {section.label.toLowerCase()}
        </Link>
        <Link to={`/forms?tab=state&state=${profile.code}`} className="ws-note">{profile.code} forms</Link>
        {section.key === 'conformity' && <Link to="/depreciation" className="ws-note">Open the depreciation calculator</Link>}
      </div>
    </div>
  );
}

export function SectionView({ section, compact = false }: { section: StateSectionData; compact?: boolean }) {
  if (section.status === 'not_verified') {
    return (
      <div className="si-unverified">
        <strong>Not yet verified</strong>
        {section.message}{' '}
        {section.agency.url && <ExternalLink href={section.agency.url}>{section.agency.name}</ExternalLink>}
      </div>
    );
  }
  return (
    <div>
      {section.status === 'provisional' && (
        <div className="notice warning" role="note" style={{ marginBottom: 8 }}>
          <span className="notice-icon" aria-hidden="true">⚠</span>
          <div><strong>Provisional.</strong> {section.message}</div>
        </div>
      )}
      <div className="ws-note" style={{ marginBottom: 6 }}>
        {section.label} · as of {section.as_of ? formatShort(section.as_of) : '—'}
        {section.shared_with === 'depreciation_calculator' && ' · same table the depreciation calculator uses'}
      </div>
      <table className="si-table">
        <caption className="sr-only">{section.label}</caption>
        <tbody>
          {section.fields.map((field) => (
            <tr key={field.key}>
              <th scope="row">{field.label}</th>
              <td>
                {field.value}
                <span className="si-src">
                  <ExternalLink href={field.source_url}>{compact ? 'Source' : field.source_citation}</ExternalLink>
                  {field.verification === 'provisional' ? ' · researched ' : ' · checked '}{formatShort(field.last_verified)}
                  {field.verification === 'automated_page_match' && (
                    <span className="ws-chip info" style={{ marginLeft: 6 }}
                      title="Found on the state's own page by the research script; not yet read by a person.">
                      Auto-checked
                    </span>
                  )}
                </span>
                {field.quote && (
                  <details className="si-quote">
                    <summary>What the page says</summary>
                    <blockquote>{field.quote}</blockquote>
                  </details>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
