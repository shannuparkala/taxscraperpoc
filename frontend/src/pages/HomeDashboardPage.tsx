/**
 * The associate's home: greeting, countdowns, tools, news, and their clients'
 * deadlines on a calendar.
 *
 * Every date is computed in the browser from the server's rule files by the
 * pure engine in lib/deadlines.ts, against "today" in the user's own time
 * zone (lib/dates.ts). Each panel loads and fails on its own; one data source
 * being down never blanks the page.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { api, type PrincipalInfo, type StateIntelProfile } from '../api/client';
import DeadlineCalendar from '../components/dashboard/DeadlineCalendar';
import { ClientManager, CustomDeadlineForm } from '../components/dashboard/ClientManager';
import { CountdownTiles, Greeting, QuickLinks, WhatsNew } from '../components/dashboard/Overview';
import { Section, SectionBoundary } from '../components/workspace/common';
import { useTaxContext } from '../context/TaxContext';
import { useAsync } from '../hooks/useApi';
import { HolidayCalendar, hourIn, parseISO, todayIn, userTimeZone } from '../lib/dates';
import {
  countdowns as computeCountdowns, generateClientDeadlines, prioritizedCountdown, type Deadline, type StateDueRules,
  type StateGap,
} from '../lib/deadlines';
import { lineForDay } from '../lib/motivation';
import '../styles/workspace.css';

/** The current instant, refreshed every minute so the greeting and "today" roll over on their own. */
function useNow(intervalMs = 60_000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

export default function HomeDashboardPage({ principal }: { principal: PrincipalInfo }) {
  const { stateCode, taxYear } = useTaxContext();
  const now = useNow();
  const timeZone = userTimeZone();
  const today = todayIn(timeZone, now);
  const hour = hourIn(timeZone, now);

  const rules = useAsync(() => api.reference.calendar(), []);
  const config = useAsync(() => api.reference.dashboard(), []);
  const listing = useAsync(() => api.reference.states(), []);
  const clients = useAsync(() => api.workspace.clients(), []);
  const custom = useAsync(() => api.workspace.deadlines(), []);

  const clientStates = useMemo(
    () => [...new Set((clients.data ?? []).flatMap((c) => c.states))].sort(),
    [clients.data],
  );
  const latestYear = Math.max(...(listing.data?.supported_years ?? [parseISO(today).y]));
  const stateRules = useAsync(async () => {
    // A state the server cannot describe simply has no rules here; the engine
    // turns that into a "not verified" gap rather than a guessed date.
    const settled = await Promise.allSettled(clientStates.map((code) => api.reference.state(code, latestYear)));
    const out: Record<string, StateDueRules | null> = {};
    settled.forEach((result, i) => {
      out[clientStates[i]] = result.status === 'fulfilled' ? (result.value as StateIntelProfile).due_rules : null;
    });
    return out;
  }, [clientStates.join(','), latestYear]);

  const holidays = useMemo(
    () => (rules.data ? new HolidayCalendar(rules.data.holidays.holidays) : null),
    [rules.data],
  );

  const countdowns = useMemo(
    () => (rules.data && holidays ? computeCountdowns(rules.data.due_dates.countdown_tiles, today, holidays) : []),
    [rules.data, holidays, today],
  );
  const nearest = countdowns.length ? Math.min(...countdowns.map((c) => c.days)) : null;
  const line = config.data ? lineForDay(config.data.motivation, today, nearest) : { text: '', season: false };

  const { deadlines, gaps } = useMemo(() => {
    const all: Deadline[] = [];
    const allGaps: StateGap[] = [];
    if (!rules.data || !holidays) return { deadlines: all, gaps: allGaps };
    const y = parseISO(today).y;
    for (const client of clients.data ?? []) {
      const result = generateClientDeadlines(client, {
        today, fromYear: y - 2, toYear: y + 1, holidays,
        federal: rules.data.due_dates.entity_types, stateRules: stateRules.data ?? {},
      });
      all.push(...result.deadlines);
      allGaps.push(...result.gaps);
    }
    const names = new Map((clients.data ?? []).map((c) => [c.id, c.name]));
    for (const item of custom.data ?? []) {
      all.push({
        id: `custom:${item.id}`, date: item.due_date, nominal: item.due_date, movedBecause: '', type: 'custom',
        title: item.kind === 'task' ? `Task: ${item.title}` : item.title,
        clientId: item.client_id, clientName: item.client_id ? names.get(item.client_id) ?? '' : '',
        taxYear: null, form: null, state: null, source: null, done: item.done,
      });
    }
    return { deadlines: all, gaps: allGaps };
  }, [rules.data, holidays, clients.data, custom.data, stateRules.data, today]);

  // The associate's own deadlines compete with the standard dates: nearest first.
  const countdownItems = useMemo(
    () => prioritizedCountdown(countdowns, deadlines, today),
    [countdowns, deadlines, today],
  );

  const toggleDone = useCallback(async (deadline: Deadline) => {
    const id = deadline.id.replace(/^custom:/, '');
    const item = (custom.data ?? []).find((c) => c.id === id);
    if (!item) return;
    await api.workspace.updateDeadline(id, { ...item, done: !item.done });
    custom.reload();
  }, [custom]);

  const stateOptions = (listing.data?.states ?? []).map((s) => ({ code: s.code, name: s.name }));
  const firstName = principal.first_name || principal.username;
  const calendarError = rules.error || clients.error;

  return (
    <div className="ws">
      <div className="dash">
        <Greeting
          firstName={firstName} hour={hour} today={today} line={line.text} season={line.season}
          taxYear={taxYear} next={countdownItems[0] ?? null}
        />

        <CountdownTiles
          items={countdownItems}
          note={rules.data?.due_dates.countdown_note ?? ''}
          loading={rules.loading}
          error={rules.error}
          onRetry={rules.reload}
        />

        <QuickLinks
          links={config.data?.quick_links ?? []}
          loading={config.loading}
          error={config.error}
          onRetry={config.reload}
        />

        <SectionBoundary title="What's new"><WhatsNew /></SectionBoundary>

        <div className="dash-clients" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <ClientManager
            clients={clients.data ?? []}
            states={stateOptions}
            gaps={gaps}
            loading={clients.loading}
            error={clients.error}
            onRetry={clients.reload}
            onChanged={() => { clients.reload(); custom.reload(); }}
            defaultState={stateCode}
            today={today}
          />
          <Section title="Add a deadline or task" loading={false} error={custom.error} onRetry={custom.reload}>
            <CustomDeadlineForm clients={clients.data ?? []} onSaved={custom.reload} today={today} />
          </Section>
        </div>

        {calendarError ? (
          <Section title="Calendar" className="dash-calendar" error={calendarError}
            onRetry={() => { rules.reload(); clients.reload(); }} />
        ) : rules.loading || clients.loading ? (
          <Section title="Calendar" className="dash-calendar" loading />
        ) : (
          <SectionBoundary title="Calendar">
            <DeadlineCalendar deadlines={deadlines} today={today} onToggleDone={(d) => void toggleDone(d)} />
          </SectionBoundary>
        )}
      </div>
    </div>
  );
}
