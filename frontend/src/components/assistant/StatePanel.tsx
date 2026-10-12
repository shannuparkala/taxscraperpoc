/**
 * The right-hand panel: pick a state, read what is true of it, see what changed.
 *
 * Collapsed by default, because the conversation is the product and a panel
 * open on first load takes a third of the screen to say nothing yet.
 *
 * Every figure is shown with the date it was recorded and a link to the
 * agency page it came from. That is not decoration: a nexus threshold read as
 * current when it is two years old is how somebody concludes they have no
 * filing obligation, and this panel would be the thing that told them.
 */

import { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, MapPinned } from 'lucide-react';

import { api, type StateProfile, type StateUpdates } from '../../api/client';
import StateMap from './StateMap';

interface Props {
  profiles: StateProfile[];
  selected: string | null;
  onSelect: (code: string | null) => void;
  open: boolean;
  onToggle: () => void;
}

export default function StatePanel({
  profiles, selected, onSelect, open, onToggle,
}: Props) {
  const profile = profiles.find((item) => item.code === selected) ?? null;

  return (
    <aside className={`state-panel ${open ? 'open' : 'collapsed'}`}>
      <button
        type="button"
        className="state-panel-handle"
        onClick={onToggle}
        aria-expanded={open}
        aria-label={open ? 'Hide state panel' : 'Show state panel'}
        title={open ? 'Hide the state panel' : 'Show the state panel'}
      >
        {open ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        {!open && (
          <span className="state-panel-handle-label">
            {selected ? selected : 'States'}
          </span>
        )}
      </button>

      {open && (
        <div className="state-panel-body">
          <header className="state-panel-head">
            <MapPinned size={18} aria-hidden="true" />
            <h3>Jurisdiction</h3>
          </header>

          <StateMap
            profiles={profiles}
            selected={selected}
            onSelect={onSelect}
          />

          {profile && <StateFacts profile={profile} />}
          {profile && <StateUpdatesList key={profile.code} profile={profile} />}
        </div>
      )}
    </aside>
  );
}

function StateFacts({ profile }: { profile: StateProfile }) {
  return (
    <section className="state-facts">
      <h4>{profile.name}</h4>
      {profile.agencies.map((agency) => (
        <a
          key={agency.url}
          className="state-agency"
          href={agency.url}
          target="_blank"
          rel="noreferrer noopener"
        >
          {agency.name}
          {agency.administers ? ` (${agency.administers})` : ''} ↗
        </a>
      ))}

      <dl>
        <Fact
          label="Income tax"
          value={profile.taxes_wage_income ? 'Taxes wage income' : 'No income tax on wages'}
        />
        <Fact
          label="Sales tax"
          value={profile.has_statewide_sales_tax ? 'Statewide sales tax' : 'No statewide sales tax'}
        />
        {profile.business_tax && <Fact label="Business tax" value={profile.business_tax} />}
      </dl>

      {(profile.features.length > 0 || profile.hints.length > 0) && (
        <ul className="state-notes">
          {profile.features.map((feature) => (
            <li key={feature}>{feature}</li>
          ))}
          {profile.hints.map((hint) => (
            <li key={hint}>{hint}</li>
          ))}
        </ul>
      )}
      <p className="state-figures-note">
        Rates and thresholds are not shown here: they change every year. Ask, and
        the answer will cite a current source and say which tax year it applies to.
      </p>
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

/**
 * Today's updates for the selected state.
 *
 * Fetched only when the section is expanded. A state selection is a cheap,
 * frequent action — clicking around the map should not fire a network request
 * per tile at somebody else's government website.
 */
function StateUpdatesList({ profile }: { profile: StateProfile }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<{
    loading: boolean;
    data: StateUpdates | null;
    error: string;
  }>({ loading: false, data: null, error: '' });

  /**
   * Whether a fetch has already been started for this state.
   *
   * A ref rather than a look at `state`, because the guard cannot depend on
   * the thing it sets. The first version had `state.loading` in both the
   * guard and the dependency list: setting loading re-ran the effect, whose
   * cleanup flipped `cancelled`, so the in-flight response was discarded and
   * the panel sat on "Reading…" forever while the request had returned 200.
   *
   * The component is keyed on the state code, so this resets when the user
   * picks a different state.
   */
  const started = useRef(false);

  useEffect(() => {
    if (!open || started.current) return;
    started.current = true;

    let cancelled = false;
    setState({ loading: true, data: null, error: '' });
    api.chat
      .stateUpdates(profile.code)
      .then((data) => {
        if (!cancelled) setState({ loading: false, data, error: '' });
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setState({
          loading: false,
          data: null,
          error: caught instanceof Error ? caught.message : String(caught),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [open, profile.code]);

  const refresh = () => {
    started.current = true;
    setState({ loading: true, data: null, error: '' });
    api.chat
      .stateUpdates(profile.code, true)
      .then((data) => setState({ loading: false, data, error: '' }))
      .catch((caught: unknown) =>
        setState({
          loading: false,
          data: null,
          error: caught instanceof Error ? caught.message : String(caught),
        }),
      );
  };

  return (
    <section className="state-updates">
      <button
        type="button"
        className="state-updates-toggle"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span>Today’s {profile.code} tax updates</span>
        <span className="chevron">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div className="state-updates-body">
          {state.loading && <p className="muted">Reading {profile.agency}…</p>}

          {state.error && <p className="muted">{state.error}</p>}

          {state.data?.error && <p className="muted">{state.data.error}</p>}

          {state.data?.items.map((item) => (
            <article key={item.url} className="update-item">
              <a href={item.url} target="_blank" rel="noreferrer noopener">
                {item.headline}
              </a>
              <div className="update-meta">
                {item.published ? (
                  <span>{item.published}</span>
                ) : (
                  <span className="muted">Undated</span>
                )}
                {item.source && <span>{item.source}</span>}
              </div>
              {item.summary && <p>{item.summary}</p>}
            </article>
          ))}

          <div className="state-updates-foot">
            <a
              href={state.data?.updates_url ?? profile.updates_url}
              target="_blank"
              rel="noreferrer noopener"
            >
              All {profile.code} updates ↗
            </a>
            {state.data && (
              <button type="button" className="btn ghost sm" onClick={refresh}>
                {state.data.from_cache ? 'Refresh' : 'Refetch'}
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
