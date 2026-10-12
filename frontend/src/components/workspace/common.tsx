/**
 * Building blocks shared by the dashboard, forms, updates and state pages.
 *
 * `Section` is the contract every data-backed panel follows: a loading state,
 * an error state with a retry, an empty state - and an error boundary, so a
 * panel that throws while rendering takes down only itself, never the page.
 */

import { Component, useId, useRef, type ErrorInfo, type KeyboardEvent, type ReactNode } from 'react';

import { ErrorBlock, LoadingBlock } from '../ui';

// ------------------------------------------------------------ error boundary

interface BoundaryState { error: Error | null }

export class SectionBoundary extends Component<{ title: string; children: ReactNode }, BoundaryState> {
  state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // No data in the message: just which panel failed.
    console.error(`Section "${this.props.title}" failed to render`, error.name, info.componentStack?.split('\n')[1]);
  }

  render() {
    if (this.state.error) {
      return (
        <div role="alert" className="notice danger">
          <span className="notice-icon" aria-hidden="true">✕</span>
          <div>
            <strong>{this.props.title} could not be shown.</strong>
            <div>The rest of the page still works.</div>
            <button type="button" className="btn sm" style={{ marginTop: 8 }} onClick={() => this.setState({ error: null })}>
              Try again
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

// -------------------------------------------------------------------- panel

export function Section({
  title, headingLevel = 2, actions, loading, error, onRetry, empty, emptyText, className = '', children, id,
}: {
  title: string;
  headingLevel?: 2 | 3;
  actions?: ReactNode;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  empty?: boolean;
  emptyText?: string;
  className?: string;
  children?: ReactNode;
  id?: string;
}) {
  const generated = useId();
  const headingId = id ?? generated;
  const Heading = headingLevel === 2 ? 'h2' : 'h3';
  let body: ReactNode = children;
  if (loading) body = <LoadingBlock label={`Loading ${title.toLowerCase()}…`} />;
  else if (error) body = <ErrorBlock message={error} onRetry={onRetry} />;
  else if (empty) body = <p className="ws-note">{emptyText ?? 'Nothing to show yet.'}</p>;
  return (
    <section className={`ws-panel ${className}`} aria-labelledby={headingId}>
      <header>
        <Heading id={headingId}>{title}</Heading>
        <span className="spacer" />
        {actions}
      </header>
      <SectionBoundary title={title}>{body}</SectionBoundary>
    </section>
  );
}

// --------------------------------------------------------------------- tabs

export interface TabDef { key: string; label: string; badge?: ReactNode }

/** WAI-ARIA tabs: arrow keys move between tabs, Home/End jump to the ends. */
export function Tabs({
  tabs, value, onChange, label, idPrefix,
}: {
  tabs: TabDef[]; value: string; onChange: (key: string) => void; label: string; idPrefix: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next = -1;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    if (next >= 0) {
      event.preventDefault();
      onChange(tabs[next].key);
      refs.current[next]?.focus();
    }
  };
  return (
    <div className="ws-tabs" role="tablist" aria-label={label}>
      {tabs.map((tab, index) => (
        <button
          key={tab.key}
          ref={(node) => { refs.current[index] = node; }}
          type="button"
          role="tab"
          id={`${idPrefix}-tab-${tab.key}`}
          aria-selected={tab.key === value}
          aria-controls={`${idPrefix}-panel`}
          tabIndex={tab.key === value ? 0 : -1}
          className="ws-tab"
          onClick={() => onChange(tab.key)}
          onKeyDown={(event) => onKey(event, index)}
        >
          {tab.label}{tab.badge != null && <> {tab.badge}</>}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ idPrefix, active, children }: { idPrefix: string; active: string; children: ReactNode }) {
  return (
    <div role="tabpanel" id={`${idPrefix}-panel`} aria-labelledby={`${idPrefix}-tab-${active}`} tabIndex={0}>
      {children}
    </div>
  );
}

// ------------------------------------------------------------- state select

export function StateSelect({
  states, value, onChange, label = 'State', includeNone = true, noneLabel = 'Select a state', id,
}: {
  states: { code: string; name: string }[];
  value: string | null;
  onChange: (code: string | null) => void;
  label?: string;
  includeNone?: boolean;
  noneLabel?: string;
  id?: string;
}) {
  const generated = useId();
  const selectId = id ?? generated;
  return (
    <div className="field">
      <label htmlFor={selectId}>{label}</label>
      <select id={selectId} value={value ?? ''} onChange={(event) => onChange(event.target.value || null)}>
        {includeNone && <option value="">{noneLabel}</option>}
        {[...states].sort((a, b) => a.name.localeCompare(b.name)).map((state) => (
          <option key={state.code} value={state.code}>{state.name}</option>
        ))}
      </select>
    </div>
  );
}

export function ExternalLink({ href, children, className }: { href: string; children: ReactNode; className?: string }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={className}>
      {children}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}
