/**
 * The deadline engine: pure, deterministic, no network, no clock.
 *
 * Inputs are the rule files the server serves (federal_due_dates.json,
 * legal_holidays.json, each state's due_rules) plus the client's own facts.
 * `today` is always passed in - computed once by `dates.todayIn` in the
 * user's time zone - so the same inputs give the same output in a test, on a
 * server in UTC and in a browser in Honolulu.
 *
 * Nothing here states a date the rule files do not imply. A state with no
 * verified due rules for the year yields a *gap* ("State rules not yet
 * verified"), never a borrowed federal or neighbouring-state date.
 */

import {
  HolidayCalendar,
  addMonths,
  compareISO,
  diffDays,
  endOfMonth,
  parseISO,
  toISO,
  weekday,
  addDays,
  type ISODate,
} from './dates';

// --------------------------------------------------------------- rule types

export interface DueOffset {
  months_after_year_end?: number | null;
  fixed_month?: number | null;
  day: number | 'last';
}

export interface EntityException {
  id: string;
  when: { year_end_month?: number; tax_year_begins_before?: string };
  due: DueOffset;
  extended_due: DueOffset;
  note: string;
  source_url: string;
  source_citation: string;
}

export interface EntityRule {
  key: EntityType;
  label: string;
  return_form: string;
  extension_form: string;
  due: DueOffset;
  extended_due: DueOffset;
  exceptions: EntityException[];
  source_url: string;
  source_citation: string;
  extension_source_url: string;
  last_verified: string;
}

export interface CountdownTileRule {
  id: string;
  month: number;
  day: number;
  label: string;
  represents: string;
  entity_keys: string[];
  form_numbers: string[];
}

export interface StateDueRules {
  years: number[];
  source_url: string;
  source_citation: string;
  last_verified: string;
  entities: Partial<Record<EntityType, {
    form: string;
    due: DueOffset;
    extended_due: DueOffset;
    june_30?: { due: DueOffset; extended_due: DueOffset } | null;
    note?: string;
  }>>;
}

export type EntityType = 'individual' | 'c_corp' | 's_corp' | 'partnership' | 'trust_estate' | 'exempt_org';

export interface ClientFacts {
  id: string;
  name: string;
  entity_type: EntityType;
  fiscal_year_end_month: number;
  states: string[];
  extension_status: 'not_extended' | 'extended';
}

export type DeadlineType = 'federal' | 'state' | 'extension' | 'custom';
export type Urgency = 'overdue' | 'due_soon' | 'upcoming' | 'done';

export interface Deadline {
  id: string;
  /** The date the obligation is actually due (after weekend/holiday moves). */
  date: ISODate;
  /** The date the rule names, before any move. */
  nominal: ISODate;
  movedBecause: string;
  type: DeadlineType;
  title: string;
  clientId: string | null;
  clientName: string;
  taxYear: number | null;
  form: string | null;
  state: string | null;
  source: { url: string; citation: string } | null;
  done?: boolean;
}

export interface StateGap {
  clientId: string;
  clientName: string;
  state: string;
  taxYear: number;
  message: string;
}

export const STATE_NOT_VERIFIED = 'State rules not yet verified for this year';

// ------------------------------------------------------------ date from rule

/** The last day of the tax year that ends in `month` of `year`. */
export function yearEnd(year: number, month: number): ISODate {
  return endOfMonth(year, month);
}

/** The day a tax year ending `end` begins (the day after the prior year end). */
export function taxYearBegins(end: ISODate): ISODate {
  return addDays(addMonths(end, -12), 1);
}

/** Apply a rule offset to a year end, before any weekend/holiday move. */
export function nominalDue(end: ISODate, offset: DueOffset): ISODate {
  const { y } = parseISO(end);
  let target: { y: number; m: number };
  if (offset.fixed_month) {
    target = { y: y + 1, m: offset.fixed_month };
  } else {
    const moved = parseISO(addMonths(toISO({ ...parseISO(end), d: 1 }), offset.months_after_year_end ?? 0));
    target = { y: moved.y, m: moved.m };
  }
  if (offset.day === 'last') return endOfMonth(target.y, target.m);
  const day = Math.min(offset.day, parseISO(endOfMonth(target.y, target.m)).d);
  return toISO({ y: target.y, m: target.m, d: day });
}

export interface AdjustedDate { date: ISODate; nominal: ISODate; movedBecause: string }

export function adjust(nominal: ISODate, holidays: HolidayCalendar): AdjustedDate {
  const date = holidays.nextBusinessDay(nominal);
  return { date, nominal, movedBecause: date === nominal ? '' : holidays.reasonClosed(nominal) };
}

/** The federal rule for an entity's tax year, applying any exception that matches. */
export function federalRuleFor(rule: EntityRule, end: ISODate): {
  due: DueOffset; extended_due: DueOffset; source_url: string; source_citation: string; note: string;
} {
  const { m } = parseISO(end);
  for (const exception of rule.exceptions ?? []) {
    const when = exception.when;
    if (when.year_end_month && when.year_end_month !== m) continue;
    if (when.tax_year_begins_before && compareISO(taxYearBegins(end), when.tax_year_begins_before) >= 0) continue;
    return { due: exception.due, extended_due: exception.extended_due,
      source_url: exception.source_url, source_citation: exception.source_citation, note: exception.note };
  }
  return { due: rule.due, extended_due: rule.extended_due,
    source_url: rule.source_url, source_citation: rule.source_citation, note: '' };
}

// ---------------------------------------------------------------- countdown

export interface Countdown {
  id: string;
  label: string;
  represents: string;
  formNumbers: string[];
  nominal: ISODate;
  date: ISODate;
  movedBecause: string;
  days: number;
  state: 'due_today' | 'due_soon' | 'upcoming';
}

/**
 * Days to the next occurrence of each tile's date.
 *
 * The count runs to the *adjusted* date: if April 15 is a Saturday the
 * deadline is Monday the 17th, so on the 16th the tile still reads 1 day.
 * Once the adjusted date has passed the tile rolls to next year.
 */
export function countdowns(tiles: CountdownTileRule[], today: ISODate, holidays: HolidayCalendar): Countdown[] {
  const { y } = parseISO(today);
  return tiles.map((tile) => {
    let year = y;
    let adjusted = adjust(toISO({ y: year, m: tile.month, d: tile.day }), holidays);
    if (compareISO(adjusted.date, today) < 0) {
      year += 1;
      adjusted = adjust(toISO({ y: year, m: tile.month, d: tile.day }), holidays);
    }
    const days = diffDays(today, adjusted.date);
    return {
      id: tile.id,
      label: tile.label,
      represents: tile.represents,
      formNumbers: tile.form_numbers,
      nominal: adjusted.nominal,
      date: adjusted.date,
      movedBecause: adjusted.movedBecause,
      days,
      state: days === 0 ? 'due_today' : days <= 7 ? 'due_soon' : 'upcoming',
    };
  });
}

/** One tile in the dashboard countdown: a standard date or one of the associate's own deadlines. */
export interface CountdownItem {
  id: string;
  kind: 'standard' | 'personal';
  date: ISODate;
  nominal: ISODate;
  movedBecause: string;
  days: number;
  state: 'overdue' | 'due_today' | 'due_soon' | 'upcoming';
  /** Standard tiles: "April 15". Personal: the deadline's title. */
  label: string;
  /** Standard tiles: what the date commonly represents. Personal: client name, if any. */
  detail: string;
  type: DeadlineType | null;
  formNumbers: string[];
  state_code: string | null;
}

/** How far back an unfinished custom deadline still counts as "needs attention". */
export const OVERDUE_LOOKBACK_DAYS = 30;

/**
 * The countdown, nearest first.
 *
 * The associate's own deadlines (clients' generated dates and anything added
 * by hand) compete with the four standard dates on one rule: whichever is
 * sooner comes first. On the same day, the associate's own deadline goes
 * before the generic date. A custom deadline that is past due and not marked
 * done stays at the front (overdue) for 30 days; generated client dates that
 * have passed are not repeated here - they cannot be marked done, and the
 * calendar already flags them.
 */
export function prioritizedCountdown(
  standard: Countdown[], personal: Deadline[], today: ISODate,
): CountdownItem[] {
  const items: CountdownItem[] = standard.map((c) => ({
    id: `std:${c.id}`, kind: 'standard', date: c.date, nominal: c.nominal, movedBecause: c.movedBecause,
    days: c.days, state: c.state, label: c.label, detail: c.represents, type: null,
    formNumbers: c.formNumbers, state_code: null,
  }));
  for (const d of personal) {
    if (d.done) continue;
    const days = diffDays(today, d.date);
    const keep = days >= 0 || (d.type === 'custom' && days >= -OVERDUE_LOOKBACK_DAYS);
    if (!keep) continue;
    items.push({
      id: `own:${d.id}`, kind: 'personal', date: d.date, nominal: d.nominal, movedBecause: d.movedBecause, days,
      state: days < 0 ? 'overdue' : days === 0 ? 'due_today' : days <= 7 ? 'due_soon' : 'upcoming',
      label: d.title, detail: d.clientName, type: d.type, formNumbers: d.form ? [d.form] : [], state_code: d.state,
    });
  }
  return items.sort((a, b) => a.days - b.days
    || (a.kind === b.kind ? 0 : a.kind === 'personal' ? -1 : 1)
    || a.label.localeCompare(b.label));
}

// --------------------------------------------------------- client deadlines

export interface GenerateOptions {
  today: ISODate;
  /** Generate for tax years ending in these calendar years. */
  fromYear: number;
  toYear: number;
  holidays: HolidayCalendar;
  federal: EntityRule[];
  /** state code -> its due rules, only for states whose file has them. */
  stateRules: Record<string, StateDueRules | null | undefined>;
}

/**
 * The tax year an extension status applies to: the most recent tax year that
 * has ended by `today`. ("Extended" on a client means the return being worked
 * on now, not every year on the calendar.)
 */
export function currentReturnYearEnd(fyeMonth: number, today: ISODate): ISODate {
  const { y } = parseISO(today);
  const thisYear = yearEnd(y, fyeMonth);
  return compareISO(thisYear, today) < 0 ? thisYear : yearEnd(y - 1, fyeMonth);
}

export function generateClientDeadlines(
  client: ClientFacts,
  options: GenerateOptions,
): { deadlines: Deadline[]; gaps: StateGap[] } {
  const federal = options.federal.find((rule) => rule.key === client.entity_type);
  const deadlines: Deadline[] = [];
  const gaps: StateGap[] = [];
  if (!federal) return { deadlines, gaps };
  const currentEnd = currentReturnYearEnd(client.fiscal_year_end_month, options.today);

  for (let year = options.fromYear; year <= options.toYear; year += 1) {
    const end = yearEnd(year, client.fiscal_year_end_month);
    const taxYear = parseISO(taxYearBegins(end)).y; // a fiscal year is named for the year it begins
    const extended = client.extension_status === 'extended' && end === currentEnd;
    const rule = federalRuleFor(federal, end);
    const original = adjust(nominalDue(end, rule.due), options.holidays);
    const extendedDue = adjust(nominalDue(end, rule.extended_due), options.holidays);
    const base = { clientId: client.id, clientName: client.name, taxYear, state: null };
    const fedSource = { url: rule.source_url, citation: rule.source_citation };

    if (extended) {
      deadlines.push({
        ...base, id: `${client.id}:fed:${year}:orig`, ...original, type: 'federal', form: federal.return_form,
        title: `Form ${federal.return_form} original due date (extension filed) - any tax due is still payable`,
        source: fedSource,
      });
      deadlines.push({
        ...base, id: `${client.id}:fed:${year}:ext`, ...extendedDue, type: 'extension', form: federal.return_form,
        title: `Form ${federal.return_form} extended due date`,
        source: { url: federal.extension_source_url, citation: `Form ${federal.extension_form} automatic extension` },
      });
    } else {
      deadlines.push({
        ...base, id: `${client.id}:fed:${year}:orig`, ...original, type: 'federal', form: federal.return_form,
        title: `Form ${federal.return_form} due (or extend with Form ${federal.extension_form})`,
        source: fedSource,
      });
    }

    for (const state of client.states) {
      const rules = options.stateRules[state];
      const entity = rules && rules.years.includes(taxYear) ? rules.entities[client.entity_type] : undefined;
      if (!rules || !entity) {
        if (!gaps.some((g) => g.state === state && g.taxYear === taxYear)) {
          gaps.push({ clientId: client.id, clientName: client.name, state, taxYear, message: STATE_NOT_VERIFIED });
        }
        continue;
      }
      const offsets = client.fiscal_year_end_month === 6 && entity.june_30 ? entity.june_30 : entity;
      const stateOriginal = adjust(nominalDue(end, offsets.due), options.holidays);
      const stateSource = { url: rules.source_url, citation: rules.source_citation };
      const stateBase = { ...base, state, form: entity.form, source: stateSource };
      if (extended) {
        const stateExtended = adjust(nominalDue(end, offsets.extended_due), options.holidays);
        deadlines.push({ ...stateBase, id: `${client.id}:${state}:${year}:orig`, ...stateOriginal, type: 'state',
          title: `${state} ${entity.form} original due date (extended) - tax due is still payable` });
        deadlines.push({ ...stateBase, id: `${client.id}:${state}:${year}:ext`, ...stateExtended, type: 'extension',
          title: `${state} ${entity.form} extended due date` });
      } else {
        deadlines.push({ ...stateBase, id: `${client.id}:${state}:${year}:orig`, ...stateOriginal, type: 'state',
          title: `${state} ${entity.form} due` });
      }
    }
  }
  return { deadlines, gaps };
}

// ------------------------------------------------------------- classifying

export function urgency(deadline: Pick<Deadline, 'date' | 'done'>, today: ISODate): Urgency {
  if (deadline.done) return 'done';
  const days = diffDays(today, deadline.date);
  if (days < 0) return 'overdue';
  if (days <= 7) return 'due_soon';
  return 'upcoming';
}

export function sortDeadlines(list: Deadline[]): Deadline[] {
  return [...list].sort((a, b) => compareISO(a.date, b.date) || a.clientName.localeCompare(b.clientName)
    || a.title.localeCompare(b.title));
}

/** Monday-to-Sunday week containing `today`. */
export function weekRange(today: ISODate): { start: ISODate; end: ISODate } {
  const start = addDays(today, -weekday(today));
  return { start, end: addDays(start, 6) };
}

export function inRange(list: Deadline[], start: ISODate, end: ISODate): Deadline[] {
  return sortDeadlines(list.filter((d) => compareISO(d.date, start) >= 0 && compareISO(d.date, end) <= 0));
}

/** In-app reminders: deadlines exactly 14, 7 or 1 days away. */
export const REMINDER_DAYS = [14, 7, 1] as const;

export function reminders(list: Deadline[], today: ISODate): { deadline: Deadline; days: number }[] {
  return sortDeadlines(list)
    .filter((d) => !d.done)
    .map((deadline) => ({ deadline, days: diffDays(today, deadline.date) }))
    .filter(({ days }) => (REMINDER_DAYS as readonly number[]).includes(days));
}

/** The 6x7 grid of dates shown for a month, Monday first. */
export function monthGrid(y: number, m: number): ISODate[] {
  const first = toISO({ y, m, d: 1 });
  const start = addDays(first, -weekday(first));
  return Array.from({ length: 42 }, (_, i) => addDays(start, i));
}
