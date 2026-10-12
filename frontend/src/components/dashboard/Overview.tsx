/** Greeting, deadline countdown tiles, quick links and the "what's new" widget. */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight, Calculator, FileText, Folder, Landmark, Newspaper, Sparkles, type LucideIcon,
} from 'lucide-react';

import { api, type QuickLink } from '../../api/client';
import { useAsync } from '../../hooks/useApi';
import { daysLabel, formatLong, formatShort, greetingFor, type ISODate } from '../../lib/dates';
import type { CountdownItem } from '../../lib/deadlines';
import { ExternalLink, Section } from '../workspace/common';

export function Greeting({
  firstName, hour, today, line, season, taxYear, next,
}: {
  firstName: string; hour: number; today: ISODate; line: string; season: boolean;
  taxYear: number;
  /** The nearest countdown item, shown as the hero's headline figure. */
  next?: CountdownItem | null;
}) {
  return (
    <section className="ws-panel greet dash-greet" aria-labelledby="greeting-heading">
      <div className="greet-main">
        <div className="greet-eyebrow">
          <span className="badge live"><span className="pulse-dot" aria-hidden="true" />Tax year {taxYear}</span>
          <span className="greet-date">{formatLong(today)}</span>
        </div>
        <h1 id="greeting-heading">{greetingFor(hour)}{firstName ? `, ${firstName}` : ''}</h1>
        {line && (
          <p className="greet-line" data-season={season ? 'deadline' : 'general'}>{line}</p>
        )}
      </div>
      <div className="greet-side">
        {next && (
          <div className={`greet-next ${next.state}`}>
            <span className="eyebrow">Next deadline</span>
            <strong className="num">
              {next.days === 0 ? 'Today'
                : `${Math.abs(next.days)} ${Math.abs(next.days) === 1 ? 'day' : 'days'}${next.days < 0 ? ' overdue' : ''}`}
            </strong>
            <span className="greet-next-what">
              {next.label}{next.kind === 'standard' ? '' : next.detail ? ` · ${next.detail}` : ''}
            </span>
          </div>
        )}
        <Link to="/assistant" className="btn primary greet-cta">
          <Sparkles size={16} aria-hidden="true" /> Ask the assistant
        </Link>
      </div>
    </section>
  );
}

const TYPE_LABEL: Record<string, string> = {
  federal: 'Federal', state: 'State', extension: 'Extension', custom: 'Your deadline',
};

/** How many tiles show before "Show more". */
export const COUNTDOWN_VISIBLE = 4;

/**
 * The countdown: the four standard dates and the associate's own deadlines in
 * one list, nearest first (see `prioritizedCountdown`). A deadline added on the
 * calendar that is sooner than the next standard date pushes it back.
 */
export function CountdownTiles({
  items, note, loading, error, onRetry,
}: {
  items: CountdownItem[]; note: string; loading: boolean; error: string | null; onRetry: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? items : items.slice(0, COUNTDOWN_VISIBLE);
  const hidden = items.length - shown.length;
  return (
    <Section
      title="Deadline countdown"
      className="dash-tiles"
      loading={loading}
      error={error}
      onRetry={onRetry}
      actions={items.length > COUNTDOWN_VISIBLE && (
        <button type="button" className="btn ghost sm" aria-expanded={expanded} onClick={() => setExpanded((v) => !v)}>
          {expanded ? 'Show fewer' : `Show ${hidden} more`}
        </button>
      )}
    >
      <ul className="tiles" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {shown.map((c) => (
          <li key={c.id} className={`cd-tile ${c.state} ${c.kind}`}
            aria-label={`${c.kind === 'personal' ? `${c.label}${c.detail ? `, ${c.detail}` : ''}` : c.label}: ${daysLabel(c.days)}.${c.kind === 'standard' ? ` ${c.detail}` : ''}`}>
            <span className="tile-label">
              {c.kind === 'personal' ? formatShort(c.date) : c.label}
              {c.kind === 'personal' && c.type && <span className="ws-chip accent" style={{ marginLeft: 6 }}>{TYPE_LABEL[c.type]}</span>}
            </span>
            <span className="tile-days num">
              {c.days === 0 ? 'Due today' : Math.abs(c.days)}
              {c.days !== 0 && (
                <span className="tile-unit">
                  {' '}{Math.abs(c.days) === 1 ? 'day' : 'days'}{c.days < 0 ? ' overdue' : ' left'}
                </span>
              )}
            </span>
            {c.state === 'overdue' && <span className="ws-chip danger">Overdue</span>}
            {c.state === 'due_soon' && <span className="ws-chip warning">Within 7 days</span>}
            {c.state === 'due_today' && <span className="ws-chip danger">Due today</span>}
            {c.kind === 'personal' ? (
              <>
                <span className="tile-what"><strong>{c.label}</strong></span>
                {c.detail && <span className="ws-note">{c.detail}</span>}
              </>
            ) : (
              <>
                <span className="tile-what">{c.detail}</span>
                <span className="ws-note">Due {formatShort(c.date)}</span>
              </>
            )}
            {c.movedBecause && (
              <span className="tile-moved">
                {formatShort(c.nominal)} falls on a {c.movedBecause === 'Saturday' || c.movedBecause === 'Sunday'
                  ? c.movedBecause : `legal holiday (${c.movedBecause})`}; due the next business day.
              </span>
            )}
            {c.formNumbers.length > 0 && (
              <Link
                to={`/forms?${c.state_code ? `tab=state&state=${c.state_code}&` : ''}q=${encodeURIComponent(c.formNumbers[0])}`}
                className="tile-forms"
              >
                Forms: {c.formNumbers.join(', ')}
              </Link>
            )}
          </li>
        ))}
      </ul>
      <p className="ws-note" style={{ marginTop: 10 }}>
        Your own deadlines and the standard dates, nearest first. {note}
      </p>
    </Section>
  );
}

const ICONS: Record<string, LucideIcon> = {
  sparkle: Sparkles, calculator: Calculator, 'file-text': FileText, newspaper: Newspaper,
  landmark: Landmark, folder: Folder,
};

export function QuickLinks({
  links, loading, error, onRetry,
}: { links: QuickLink[]; loading: boolean; error: string | null; onRetry: () => void }) {
  return (
    <Section title="Tools" className="dash-links" loading={loading} error={error} onRetry={onRetry}
      empty={!links.length} emptyText="No quick links are configured.">
      <nav aria-label="Quick links" className="quick-links">
        {links.map((link) => {
          const Icon = ICONS[link.icon] ?? Folder;
          return (
            <Link key={link.id} to={link.path} className="quick-link" data-icon={link.icon}>
              <span className="ql-icon" aria-hidden="true"><Icon size={18} /></span>
              <span className="ql-body">
                <strong>{link.label}</strong>
                <span>{link.description}</span>
                <span className="ql-go" aria-hidden="true">Open <ArrowRight size={13} /></span>
              </span>
            </Link>
          );
        })}
      </nav>
    </Section>
  );
}

export function WhatsNew() {
  const feed = useAsync(() => api.updates.feed({ limit: 3 }), []);
  const items = feed.data?.items ?? [];
  return (
    <Section
      title="What's new"
      className="dash-news"
      loading={feed.loading}
      error={feed.error}
      onRetry={feed.reload}
      empty={!items.length}
      emptyText="No updates fetched yet. The feed refreshes in the background; check Industry Updates for each source's status."
      actions={<Link to="/updates" className="ws-note">All updates</Link>}
    >
      <ul className="news-list">
        {items.map((item) => (
          <li key={item.id}>
            <div className="news-meta">
              <span className="ws-chip info">{item.source_name}</span>
              {item.published && <span className="num">{formatShort(item.published)}</span>}
            </div>
            <ExternalLink href={item.url} className="news-title">{item.title}</ExternalLink>
          </li>
        ))}
      </ul>
    </Section>
  );
}
