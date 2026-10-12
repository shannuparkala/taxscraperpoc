/**
 * Month calendar of the associate's client deadlines.
 *
 * Type (federal / state / extension / custom) is shown by a letter as well as
 * a colour, and urgency (overdue / due within 7 days) by an outline style plus
 * a text label in the day list - never by colour alone.
 */

import { useMemo, useState, type KeyboardEvent } from 'react';
import { Link } from 'react-router-dom';
import { ChevronLeft, ChevronRight } from 'lucide-react';

import { addDays, daysLabel, diffDays, formatLong, formatMonthYear, formatShort, parseISO, type ISODate } from '../../lib/dates';
import {
  inRange, monthGrid, reminders, sortDeadlines, urgency, weekRange, type Deadline, type DeadlineType, type Urgency,
} from '../../lib/deadlines';
import { ExternalLink } from '../workspace/common';

const TYPE_META: Record<DeadlineType, { letter: string; label: string }> = {
  federal: { letter: 'F', label: 'Federal' },
  state: { letter: 'S', label: 'State' },
  extension: { letter: 'E', label: 'Extension' },
  custom: { letter: 'C', label: 'Custom' },
};

const URGENCY_LABEL: Record<Urgency, string> = {
  overdue: 'Overdue', due_soon: 'Due within 7 days', upcoming: 'Upcoming', done: 'Done',
};

export default function DeadlineCalendar({
  deadlines, today, onToggleDone,
}: {
  deadlines: Deadline[];
  today: ISODate;
  onToggleDone?: (deadline: Deadline) => void;
}) {
  const start = parseISO(today);
  const [view, setView] = useState({ y: start.y, m: start.m });
  const [selected, setSelected] = useState<ISODate>(today);

  const byDay = useMemo(() => {
    const map = new Map<ISODate, Deadline[]>();
    for (const d of deadlines) map.set(d.date, [...(map.get(d.date) ?? []), d]);
    return map;
  }, [deadlines]);

  const grid = monthGrid(view.y, view.m);
  const week = weekRange(today);
  const thisWeek = inRange(deadlines.filter((d) => !d.done), week.start, week.end);
  const overdue = sortDeadlines(deadlines.filter((d) => urgency(d, today) === 'overdue')).filter(
    (d) => diffDays(d.date, today) <= 30, // recent misses, not years of history
  );
  const dueReminders = reminders(deadlines, today);
  const dayList = sortDeadlines(byDay.get(selected) ?? []);

  const move = (months: number) => {
    const index = view.y * 12 + (view.m - 1) + months;
    setView({ y: Math.floor(index / 12), m: (index % 12) + 1 });
  };
  const goToday = () => {
    setView({ y: start.y, m: start.m });
    setSelected(today);
  };
  const onGridKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const deltas: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
    const delta = deltas[event.key];
    if (delta === undefined) return;
    event.preventDefault();
    const next = addDays(selected, delta);
    setSelected(next);
    const p = parseISO(next);
    if (p.y !== view.y || p.m !== view.m) setView({ y: p.y, m: p.m });
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLButtonElement>(`[data-date="${next}"]`)?.focus();
    });
  };

  return (
    <section className="ws-panel dash-calendar" aria-labelledby="calendar-heading">
      <div className="week-summary" aria-live="polite">
        <h3>This week ({formatShort(week.start)} – {formatShort(week.end)})</h3>
        {thisWeek.length === 0 ? (
          <p className="ws-note" style={{ margin: 0 }}>No client deadlines this week.</p>
        ) : (
          <ul className="deadline-list">
            {thisWeek.slice(0, 5).map((d) => (
              <li key={d.id} className="ws-note">
                <strong>{formatShort(d.date)}</strong> · {d.clientName || 'Custom'} — {d.title}
              </li>
            ))}
            {thisWeek.length > 5 && <li className="ws-note">and {thisWeek.length - 5} more</li>}
          </ul>
        )}
        {overdue.length > 0 && (
          <p className="ws-note" style={{ margin: '6px 0 0', color: 'var(--danger)' }}>
            {overdue.length} overdue in the last 30 days.
          </p>
        )}
      </div>

      {dueReminders.length > 0 && (
        <div className="notice warning" role="status" style={{ marginBottom: 10 }}>
          <span className="notice-icon" aria-hidden="true">⏰</span>
          <div>
            <strong>Reminders</strong>
            <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
              {dueReminders.map(({ deadline, days }) => (
                <li key={deadline.id}>{deadline.clientName || 'Custom'}: {deadline.title} — in {daysLabel(days)}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <div className="cal-head">
        <h2 id="calendar-heading">{formatMonthYear(view.y, view.m)}</h2>
        <button type="button" className="btn ghost sm" onClick={() => move(-1)} aria-label="Previous month">
          <ChevronLeft size={16} aria-hidden="true" />
        </button>
        <button type="button" className="btn sm" onClick={goToday}>Today</button>
        <button type="button" className="btn ghost sm" onClick={() => move(1)} aria-label="Next month">
          <ChevronRight size={16} aria-hidden="true" />
        </button>
      </div>

      <div className="cal-grid" role="grid" aria-labelledby="calendar-heading" onKeyDown={onGridKey}>
        <div role="row" style={{ display: 'contents' }}>
          {['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].map((d) => (
            <div key={d} className="cal-dow" role="columnheader" aria-label={d}>{d.slice(0, 3)}</div>
          ))}
        </div>
        {[0, 1, 2, 3, 4, 5].map((week) => (
          <div key={week} role="row" style={{ display: 'contents' }}>
        {grid.slice(week * 7, week * 7 + 7).map((date) => {
          const items = byDay.get(date) ?? [];
          const inMonth = parseISO(date).m === view.m;
          const counts = items.reduce<Record<string, number>>((acc, d) => {
            acc[d.type] = (acc[d.type] ?? 0) + 1;
            return acc;
          }, {});
          const worst = items.some((d) => urgency(d, today) === 'overdue') ? 'overdue'
            : items.some((d) => urgency(d, today) === 'due_soon') ? 'due_soon' : '';
          const label = `${formatLong(date)}${date === today ? ', today' : ''}: ${
            items.length ? `${items.length} deadline${items.length > 1 ? 's' : ''}${worst ? `, ${URGENCY_LABEL[worst]}` : ''}` : 'no deadlines'}`;
          return (
            <button
              key={date}
              type="button"
              role="gridcell"
              data-date={date}
              className={`cal-day ${inMonth ? '' : 'other-month'} ${date === today ? 'today' : ''}`}
              aria-selected={date === selected}
              tabIndex={date === selected ? 0 : -1}
              onClick={() => setSelected(date)}
            >
              {/* The name comes from this text, so the visible digits and letters need no aria-label. */}
              <span className="sr-only">{label}</span>
              <span className="cal-num" aria-hidden="true">{parseISO(date).d}</span>
              <span className="cal-marks" aria-hidden="true">
                {(Object.keys(counts) as DeadlineType[]).map((type) => (
                  <span key={type} className={`mark ${type} ${worst}`}>
                    {TYPE_META[type].letter}{counts[type] > 1 ? counts[type] : ''}
                  </span>
                ))}
              </span>
            </button>
          );
        })}
          </div>
        ))}
      </div>

      <div className="legend" aria-label="Legend">
        {(Object.keys(TYPE_META) as DeadlineType[]).map((type) => (
          <span key={type}><span className={`mark ${type}`}>{TYPE_META[type].letter}</span>{TYPE_META[type].label}</span>
        ))}
        <span><span className="mark custom overdue">!</span>Solid outline: overdue</span>
        <span><span className="mark custom due_soon">7</span>Dashed outline: due within 7 days</span>
      </div>

      <div style={{ marginTop: 14 }}>
        <h3 style={{ fontSize: 13.5, marginBottom: 8 }} id="day-heading">{formatLong(selected)}</h3>
        {dayList.length === 0 ? (
          <p className="ws-note">No deadlines on this day.</p>
        ) : (
          <ul className="deadline-list" aria-labelledby="day-heading">
            {dayList.map((d) => (
              <DeadlineItem key={d.id} deadline={d} today={today} onToggleDone={onToggleDone} />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function DeadlineItem({
  deadline, today, onToggleDone,
}: { deadline: Deadline; today: ISODate; onToggleDone?: (deadline: Deadline) => void }) {
  const [showSource, setShowSource] = useState(false);
  const level = urgency(deadline, today);
  const meta = TYPE_META[deadline.type];
  const days = diffDays(today, deadline.date);
  return (
    <li className={`deadline-item ${level}`}>
      <div className="di-top">
        <span className={`mark ${deadline.type}`} aria-hidden="true">{meta.letter}</span>
        <span className="ws-chip">{meta.label}</span>
        <span className={`ws-chip ${level === 'overdue' ? 'danger' : level === 'due_soon' ? 'warning' : ''}`}>
          {URGENCY_LABEL[level]}{level !== 'done' ? ` · ${daysLabel(days)}` : ''}
        </span>
        {deadline.state && <span className="ws-chip purple">{deadline.state}</span>}
      </div>
      <div className="di-title">{deadline.clientName ? `${deadline.clientName}: ` : ''}{deadline.title}</div>
      {deadline.movedBecause && (
        <div className="ws-note">
          Rule date {formatShort(deadline.nominal)} is a {deadline.movedBecause}; due the next business day.
        </div>
      )}
      <div className="di-links">
        {deadline.form && (
          <Link to={`/forms?${deadline.state ? `tab=state&state=${deadline.state}&` : ''}q=${encodeURIComponent(deadline.form)}`}>
            {deadline.state ? `${deadline.state} ` : ''}Form {deadline.form}
          </Link>
        )}
        {deadline.state && <Link to={`/states/${deadline.state}`}>{deadline.state} State Intelligence</Link>}
        {deadline.source && (
          <button type="button" className="btn ghost sm" aria-expanded={showSource} onClick={() => setShowSource((v) => !v)}>
            {showSource ? 'Hide source' : 'Source'}
          </button>
        )}
        {deadline.type === 'custom' && onToggleDone && (
          <button type="button" className="btn ghost sm" onClick={() => onToggleDone(deadline)}>
            {deadline.done ? 'Mark not done' : 'Mark done'}
          </button>
        )}
      </div>
      {showSource && deadline.source && (
        <div className="source-pop">
          {deadline.source.citation}{' '}
          <ExternalLink href={deadline.source.url}>Open source</ExternalLink>
        </div>
      )}
    </li>
  );
}
