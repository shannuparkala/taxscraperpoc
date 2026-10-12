/**
 * The one date module. Every date the dashboard, calendar and countdowns show
 * goes through here.
 *
 * Two rules keep it correct:
 *
 * 1. **Calendar dates, not instants.** A due date is a day on the calendar
 *    ("2027-04-15"), held as an ISO string. Arithmetic runs on `Date.UTC`
 *    day numbers, so daylight-saving changes, leap years and the time of day
 *    can never move a count by one. "Days until" is the difference between
 *    two calendar dates, never `(deadline - now) / 86_400_000`.
 * 2. **"Today" is the user's today.** The only place an instant becomes a
 *    date is `todayIn`, which reads the wall-clock date in the user's time
 *    zone. At 11pm in Los Angeles it is still yesterday in UTC terms, and the
 *    countdown must agree with the user's wall calendar.
 *
 * Holiday rules come from the server's data file (legal_holidays.json); this
 * module only evaluates them.
 */

export type ISODate = string; // YYYY-MM-DD

export interface Ymd { y: number; m: number; d: number } // m is 1-12

const DAY_MS = 86_400_000;

// ------------------------------------------------------------------ basics

export function userTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

export function pad(n: number): string {
  return String(n).padStart(2, '0');
}

export function toISO({ y, m, d }: Ymd): ISODate {
  return `${String(y).padStart(4, '0')}-${pad(m)}-${pad(d)}`;
}

export function parseISO(iso: ISODate): Ymd {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) throw new Error(`Not an ISO date: ${iso}`);
  const value = { y: Number(match[1]), m: Number(match[2]), d: Number(match[3]) };
  if (value.m < 1 || value.m > 12 || value.d < 1 || value.d > daysInMonth(value.y, value.m)) {
    throw new Error(`Not a calendar date: ${iso}`);
  }
  return value;
}

export function isLeapYear(y: number): boolean {
  return (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
}

export function daysInMonth(y: number, m: number): number {
  return [31, isLeapYear(y) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1];
}

/** Day number since the epoch for a calendar date. Time zones never enter. */
function dayNumber(iso: ISODate): number {
  const { y, m, d } = parseISO(iso);
  return Math.round(Date.UTC(y, m - 1, d) / DAY_MS);
}

function fromDayNumber(n: number): ISODate {
  const date = new Date(n * DAY_MS);
  return toISO({ y: date.getUTCFullYear(), m: date.getUTCMonth() + 1, d: date.getUTCDate() });
}

export function addDays(iso: ISODate, days: number): ISODate {
  return fromDayNumber(dayNumber(iso) + days);
}

/** Calendar days from `from` to `to` (positive when `to` is later). */
export function diffDays(from: ISODate, to: ISODate): number {
  return dayNumber(to) - dayNumber(from);
}

/** Add months, clamping the day to the target month's length (Jan 31 + 1 = Feb 28/29). */
export function addMonths(iso: ISODate, months: number): ISODate {
  const { y, m, d } = parseISO(iso);
  const index = y * 12 + (m - 1) + months;
  const ty = Math.floor(index / 12);
  const tm = (index % 12) + 1;
  return toISO({ y: ty, m: tm, d: Math.min(d, daysInMonth(ty, tm)) });
}

export function endOfMonth(y: number, m: number): ISODate {
  return toISO({ y, m, d: daysInMonth(y, m) });
}

/** 0 = Monday ... 6 = Sunday. */
export function weekday(iso: ISODate): number {
  const { y, m, d } = parseISO(iso);
  return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
}

export function isWeekend(iso: ISODate): boolean {
  return weekday(iso) >= 5;
}

export function compareISO(a: ISODate, b: ISODate): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

// ------------------------------------------------------------- user's today

/** The calendar date it is right now on the user's wall clock. */
export function todayIn(timeZone: string = userTimeZone(), now: Date = new Date()): ISODate {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(now);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  return `${get('year')}-${get('month')}-${get('day')}`;
}

/** The hour (0-23) on the user's wall clock. */
export function hourIn(timeZone: string = userTimeZone(), now: Date = new Date()): number {
  const hour = new Intl.DateTimeFormat('en-US', { timeZone, hour: 'numeric', hourCycle: 'h23' }).format(now);
  return Number(hour) % 24;
}

export function greetingFor(hour: number): 'Good morning' | 'Good afternoon' | 'Good evening' {
  if (hour >= 5 && hour < 12) return 'Good morning';
  if (hour >= 12 && hour < 17) return 'Good afternoon';
  return 'Good evening';
}

// -------------------------------------------------------------- formatting

/** "Thursday, April 15, 2027" - formatted as a calendar date, never shifted by a zone. */
export function formatLong(iso: ISODate, locale?: string): string {
  const { y, m, d } = parseISO(iso);
  return new Intl.DateTimeFormat(locale, {
    timeZone: 'UTC', weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
  }).format(new Date(Date.UTC(y, m - 1, d)));
}

/** "Apr 15, 2027". */
export function formatShort(iso: ISODate, locale?: string): string {
  const { y, m, d } = parseISO(iso);
  return new Intl.DateTimeFormat(locale, {
    timeZone: 'UTC', year: 'numeric', month: 'short', day: 'numeric',
  }).format(new Date(Date.UTC(y, m - 1, d)));
}

export function formatMonthYear(y: number, m: number, locale?: string): string {
  return new Intl.DateTimeFormat(locale, { timeZone: 'UTC', month: 'long', year: 'numeric' })
    .format(new Date(Date.UTC(y, m - 1, 1)));
}

/** An instant (ISO datetime from the server) shown in the user's time zone. */
export function formatInstant(isoInstant: string, timeZone: string = userTimeZone(), locale?: string): string {
  const date = new Date(isoInstant);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat(locale, {
    timeZone, year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  }).format(date);
}

export function daysLabel(days: number): string {
  if (days === 0) return 'Due today';
  if (days === 1) return '1 day';
  if (days === -1) return '1 day overdue';
  if (days < 0) return `${-days} days overdue`;
  return `${days} days`;
}

// ---------------------------------------------------------------- holidays

export interface HolidayRuleData {
  type: 'fixed' | 'nth_weekday';
  month: number;
  day?: number | null;
  weekday?: number | null;
  n?: number | null;
  every_years?: number | null;
  base_year?: number | null;
}

export interface HolidayData {
  id: string;
  name: string;
  rule: HolidayRuleData;
  observed: boolean | 'sunday_only';
  effective_from?: number | null;
}

/** The nth weekday of a month (n = -1 for the last). */
export function nthWeekday(y: number, m: number, wd: number, n: number): ISODate {
  if (n > 0) {
    const first = weekday(toISO({ y, m, d: 1 }));
    const day = 1 + ((wd - first + 7) % 7) + (n - 1) * 7;
    return toISO({ y, m, d: day });
  }
  const lastDay = daysInMonth(y, m);
  const last = weekday(toISO({ y, m, d: lastDay }));
  return toISO({ y, m, d: lastDay - ((last - wd + 7) % 7) });
}

function actualDate(holiday: HolidayData, y: number): ISODate | null {
  const { rule } = holiday;
  if (holiday.effective_from && y < holiday.effective_from) return null;
  if (rule.every_years && rule.base_year != null && (y - rule.base_year) % rule.every_years !== 0) return null;
  if (rule.type === 'fixed') return toISO({ y, m: rule.month, d: rule.day ?? 1 });
  return nthWeekday(y, rule.month, rule.weekday ?? 0, rule.n ?? 1);
}

function observedDate(holiday: HolidayData, actual: ISODate): ISODate {
  const wd = weekday(actual);
  if (holiday.observed === true) {
    if (wd === 5) return addDays(actual, -1); // Saturday -> Friday
    if (wd === 6) return addDays(actual, 1); // Sunday -> Monday
  } else if (holiday.observed === 'sunday_only' && wd === 6) {
    return addDays(actual, 1);
  }
  return actual;
}

/**
 * Observed legal holidays falling in calendar year `y`, date -> name.
 *
 * Includes the next year's New Year's Day when it is observed on Friday
 * December 31 of `y`.
 */
export function holidaysInYear(holidays: HolidayData[], y: number): Map<ISODate, string> {
  const out = new Map<ISODate, string>();
  for (const year of [y, y + 1]) {
    for (const holiday of holidays) {
      const actual = actualDate(holiday, year);
      if (!actual) continue;
      const observed = observedDate(holiday, actual);
      if (parseISO(observed).y === y) out.set(observed, holiday.name);
    }
  }
  return out;
}

export class HolidayCalendar {
  private cache = new Map<number, Map<ISODate, string>>();

  constructor(private readonly holidays: HolidayData[]) {}

  nameOf(iso: ISODate): string | undefined {
    const { y } = parseISO(iso);
    if (!this.cache.has(y)) this.cache.set(y, holidaysInYear(this.holidays, y));
    return this.cache.get(y)!.get(iso);
  }

  isBusinessDay(iso: ISODate): boolean {
    return !isWeekend(iso) && this.nameOf(iso) === undefined;
  }

  /** The date itself if it is a business day, otherwise the next one (IRC 7503). */
  nextBusinessDay(iso: ISODate): ISODate {
    let current = iso;
    for (let i = 0; i < 14 && !this.isBusinessDay(current); i += 1) current = addDays(current, 1);
    return current;
  }

  /** Why a date is not a business day, for the "moved because" note. */
  reasonClosed(iso: ISODate): string {
    const holiday = this.nameOf(iso);
    if (holiday) return holiday;
    if (weekday(iso) === 5) return 'Saturday';
    if (weekday(iso) === 6) return 'Sunday';
    return '';
  }
}
