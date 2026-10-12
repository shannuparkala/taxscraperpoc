import { describe, expect, it } from 'vitest';

import { HolidayCalendar, type HolidayData } from '../lib/dates';
import {
  countdowns,
  currentReturnYearEnd,
  generateClientDeadlines,
  monthGrid,
  nominalDue,
  prioritizedCountdown,
  reminders,
  STATE_NOT_VERIFIED,
  taxYearBegins,
  urgency,
  weekRange,
  type ClientFacts,
  type CountdownTileRule,
  type EntityRule,
  type StateDueRules,
} from '../lib/deadlines';
import { lineForDay } from '../lib/motivation';
import holidayFile from '../../../backend/app/reference_data/calendar/legal_holidays.json';
import dueFile from '../../../backend/app/reference_data/calendar/federal_due_dates.json';
import caFile from '../../../backend/app/reference_data/state_intel/states/CA.json';
import txFile from '../../../backend/app/reference_data/state_intel/states/TX.json';
import motivationFile from '../../../backend/app/reference_data/dashboard/motivation.json';

const holidays = new HolidayCalendar(holidayFile.holidays as HolidayData[]);
const FEDERAL = dueFile.entity_types as unknown as EntityRule[];
const TILES = dueFile.countdown_tiles as CountdownTileRule[];
const CA = caFile.sections.filing.due_rules as unknown as StateDueRules;
const TX = txFile.sections.filing.due_rules as unknown as StateDueRules;

function client(overrides: Partial<ClientFacts> = {}): ClientFacts {
  return {
    id: 'c1', name: 'Example Co', entity_type: 's_corp', fiscal_year_end_month: 12,
    states: [], extension_status: 'not_extended', ...overrides,
  };
}

function generate(c: ClientFacts, today = '2026-10-07', fromYear = 2025, toYear = 2025) {
  return generateClientDeadlines(c, {
    today, fromYear, toYear, holidays, federal: FEDERAL, stateRules: { CA, TX },
  });
}

describe('countdown tiles', () => {
  it('counts to the next occurrence and rolls over once a date passes', () => {
    const result = countdowns(TILES, '2026-10-07', holidays);
    const byId = Object.fromEntries(result.map((c) => [c.id, c]));
    expect(byId.oct15.date).toBe('2026-10-15');
    expect(byId.oct15.days).toBe(8);
    expect(byId.mar15.date).toBe('2027-03-15'); // Monday
    expect(byId.apr15.date).toBe('2027-04-15');
    expect(byId.sep15.date).toBe('2027-09-15');
  });

  it('uses the adjusted date for a weekend deadline and keeps counting until it passes', () => {
    // 2026-03-15 is a Sunday: S corporation returns were due Monday March 16 (per the 1120-S instructions).
    const onSunday = countdowns(TILES, '2026-03-15', holidays).find((c) => c.id === 'mar15')!;
    expect(onSunday.date).toBe('2026-03-16');
    expect(onSunday.nominal).toBe('2026-03-15');
    expect(onSunday.movedBecause).toBe('Sunday');
    expect(onSunday.days).toBe(1);
    const dayAfter = countdowns(TILES, '2026-03-17', holidays).find((c) => c.id === 'mar15')!;
    expect(dayAfter.date).toBe('2027-03-15');
  });

  it('says due today and flags the last seven days', () => {
    const today = countdowns(TILES, '2027-04-15', holidays).find((c) => c.id === 'apr15')!;
    expect(today.days).toBe(0);
    expect(today.state).toBe('due_today');
    const soon = countdowns(TILES, '2027-04-09', holidays).find((c) => c.id === 'apr15')!;
    expect(soon.state).toBe('due_soon');
    const later = countdowns(TILES, '2027-04-07', holidays).find((c) => c.id === 'apr15')!;
    expect(later.state).toBe('upcoming');
  });

  it('crosses a leap day correctly', () => {
    const c = countdowns(TILES, '2028-02-28', holidays).find((x) => x.id === 'mar15')!;
    expect(c.date).toBe('2028-03-15');
    expect(c.days).toBe(16); // 28 Feb -> 29 Feb -> ... 15 Mar
  });

  it('moves April 15 2028 (a Saturday) past Emancipation Day observed Monday to Tuesday April 18', () => {
    const c = countdowns(TILES, '2028-04-16', holidays).find((x) => x.id === 'apr15')!;
    expect(c.date).toBe('2028-04-18');
    expect(c.movedBecause).toBe('Saturday');
    expect(c.days).toBe(2);
  });
});

describe('rule offsets', () => {
  it('turns offsets into dates for calendar and fiscal years', () => {
    expect(nominalDue('2025-12-31', { months_after_year_end: 3, day: 15 })).toBe('2026-03-15');
    expect(nominalDue('2025-12-31', { months_after_year_end: 4, day: 15 })).toBe('2026-04-15');
    expect(nominalDue('2025-12-31', { months_after_year_end: 9, day: 'last' })).toBe('2026-09-30');
    expect(nominalDue('2026-06-30', { months_after_year_end: 3, day: 15 })).toBe('2026-09-15');
    expect(nominalDue('2026-02-28', { months_after_year_end: 4, day: 15 })).toBe('2026-06-15');
    expect(nominalDue('2025-12-31', { fixed_month: 5, day: 15 })).toBe('2026-05-15');
    expect(nominalDue('2025-12-31', { months_after_year_end: 5, day: 1 })).toBe('2026-05-01');
  });

  it('knows when a tax year begins', () => {
    expect(taxYearBegins('2025-12-31')).toBe('2025-01-01');
    expect(taxYearBegins('2026-06-30')).toBe('2025-07-01');
    expect(taxYearBegins('2028-02-29')).toBe('2027-03-01');
  });
});

describe('federal deadlines per entity type', () => {
  const cases: [ClientFacts['entity_type'], string, string][] = [
    ['individual', '2026-04-15', '2026-10-15'],
    ['c_corp', '2026-04-15', '2026-10-15'],
    ['s_corp', '2026-03-16', '2026-09-15'],      // Mar 15 2026 is a Sunday
    ['partnership', '2026-03-16', '2026-09-15'],
    ['trust_estate', '2026-04-15', '2026-09-30'],
    ['exempt_org', '2026-05-15', '2026-11-16'],  // Nov 15 2026 is a Sunday
  ];

  it.each(cases)('%s: original %s, extended %s', (entity, original, extended) => {
    const plain = generate(client({ entity_type: entity })).deadlines;
    expect(plain).toHaveLength(1);
    expect(plain[0].date).toBe(original);
    expect(plain[0].type).toBe('federal');
    expect(plain[0].source?.url).toMatch(/^https:\/\/www\.irs\.gov\//);

    const ext = generate(client({ entity_type: entity, extension_status: 'extended' })).deadlines;
    expect(ext.map((d) => d.type)).toEqual(['federal', 'extension']);
    expect(ext[1].date).toBe(extended);
  });

  it('applies the June 30 C corporation exception only to years beginning before 2026', () => {
    const june = client({ entity_type: 'c_corp', fiscal_year_end_month: 6 });
    // FYE 2026-06-30 began 2025-07-01: 15th day of the 3rd month, 7-month extension.
    const before = generate({ ...june, extension_status: 'extended' }, '2026-07-15', 2026, 2026).deadlines;
    expect(before[0].date).toBe('2026-09-15');
    expect(before[1].date).toBe('2027-04-15');
    expect(before[0].source?.url).toContain('i7004');
    // FYE 2027-06-30 began 2026-07-01: the general 4th-month rule.
    const after = generate(june, '2026-07-15', 2027, 2027).deadlines;
    expect(after[0].date).toBe('2027-10-15');
  });

  it('names a fiscal year for the year it begins', () => {
    const d = generate(client({ fiscal_year_end_month: 6 }), '2026-10-07', 2026, 2026).deadlines[0];
    expect(d.taxYear).toBe(2025);
  });

  it('applies the extension status only to the return currently being prepared', () => {
    expect(currentReturnYearEnd(12, '2026-10-07')).toBe('2025-12-31');
    expect(currentReturnYearEnd(6, '2026-10-07')).toBe('2026-06-30');
    const both = generate(client({ extension_status: 'extended' }), '2026-10-07', 2025, 2026).deadlines;
    expect(both.filter((d) => d.type === 'extension').map((d) => d.taxYear)).toEqual([2025]);
  });
});

describe('state deadlines', () => {
  it('uses the state\'s own verified rules', () => {
    const { deadlines, gaps } = generate(client({ entity_type: 'c_corp', states: ['CA'], extension_status: 'extended' }));
    const ca = deadlines.filter((d) => d.state === 'CA');
    expect(ca.map((d) => d.date)).toEqual(['2026-04-15', '2026-11-16']); // Nov 15 2026 is a Sunday
    expect(ca[0].source?.url).toContain('ftb.ca.gov');
    expect(gaps).toEqual([]);
  });

  it('handles a fixed-date report (Texas franchise tax)', () => {
    const { deadlines } = generate(client({ entity_type: 'partnership', states: ['TX'] }));
    expect(deadlines.find((d) => d.state === 'TX')!.date).toBe('2026-05-15');
  });

  it('reports a gap instead of guessing for an unverified state or entity', () => {
    const { deadlines, gaps } = generate(client({ entity_type: 'trust_estate', states: ['CA', 'WY'] }));
    expect(deadlines.every((d) => d.state === null)).toBe(true);
    expect(gaps.map((g) => g.state)).toEqual(['CA', 'WY']);
    expect(gaps[0].message).toBe(STATE_NOT_VERIFIED);
  });

  it('reports a gap for a year the state rules do not cover', () => {
    const { gaps } = generate(client({ states: ['CA'] }), '2026-10-07', 2027, 2027);
    expect(gaps.map((g) => [g.state, g.taxYear])).toEqual([['CA', 2027]]);
  });
});

describe('classification and calendar helpers', () => {
  it('classifies urgency', () => {
    expect(urgency({ date: '2026-10-06' }, '2026-10-07')).toBe('overdue');
    expect(urgency({ date: '2026-10-07' }, '2026-10-07')).toBe('due_soon');
    expect(urgency({ date: '2026-10-14' }, '2026-10-07')).toBe('due_soon');
    expect(urgency({ date: '2026-10-15' }, '2026-10-07')).toBe('upcoming');
    expect(urgency({ date: '2026-10-01', done: true }, '2026-10-07')).toBe('done');
  });

  it('builds a Monday-first month grid and week range', () => {
    const grid = monthGrid(2026, 10);
    expect(grid).toHaveLength(42);
    expect(grid[0]).toBe('2026-09-28');
    expect(grid).toContain('2026-10-31');
    expect(weekRange('2026-10-07')).toEqual({ start: '2026-10-05', end: '2026-10-11' });
  });

  it('raises reminders at 14, 7 and 1 days', () => {
    const { deadlines } = generate(client({ entity_type: 'individual', extension_status: 'extended' }));
    const ext = deadlines.find((d) => d.type === 'extension')!; // 2026-10-15
    expect(reminders([ext], '2026-10-01').map((r) => r.days)).toEqual([14]);
    expect(reminders([ext], '2026-10-08').map((r) => r.days)).toEqual([7]);
    expect(reminders([ext], '2026-10-14').map((r) => r.days)).toEqual([1]);
    expect(reminders([ext], '2026-10-10')).toEqual([]);
  });
});

describe('daily line', () => {
  it('is stable for a date and changes between dates', () => {
    const a = lineForDay(motivationFile, '2026-10-07', 100);
    expect(lineForDay(motivationFile, '2026-10-07', 100)).toEqual(a);
    const texts = new Set(['2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04', '2026-10-05']
      .map((d) => lineForDay(motivationFile, d, 100).text));
    expect(texts.size).toBeGreaterThan(1);
  });

  it('draws from the deadline-season bank in the run-up to a deadline', () => {
    const line = lineForDay(motivationFile, '2027-04-01', 14);
    expect(line.season).toBe(true);
    expect(motivationFile.deadline_season).toContain(line.text);
    expect(lineForDay(motivationFile, '2027-04-01', 40).season).toBe(false);
  });
});

describe('countdown priority', () => {
  const custom = (id: string, date: string, extra: Partial<import('../lib/deadlines').Deadline> = {}) => ({
    id, date, nominal: date, movedBecause: '', type: 'custom' as const, title: `Task ${id}`,
    clientId: null, clientName: '', taxYear: null, form: null, state: null, source: null, done: false, ...extra,
  });

  it('puts a nearer deadline added on the calendar ahead of the standard dates', () => {
    const standard = countdowns(TILES, '2026-10-08', holidays);
    const items = prioritizedCountdown(standard, [custom('a', '2026-10-12')], '2026-10-08');
    expect(items[0]).toMatchObject({ kind: 'personal', label: 'Task a', days: 4, state: 'due_soon' });
    expect(items[1]).toMatchObject({ kind: 'standard', label: 'October 15', days: 7 });
    expect(items.map((i) => i.days)).toEqual([...items.map((i) => i.days)].sort((x, y) => x - y));
  });

  it('keeps an unfinished overdue custom deadline at the front, and drops done ones', () => {
    const standard = countdowns(TILES, '2026-10-08', holidays);
    const items = prioritizedCountdown(standard, [
      custom('late', '2026-10-01'), custom('done', '2026-10-09', { done: true }), custom('old', '2026-08-01'),
    ], '2026-10-08');
    expect(items[0]).toMatchObject({ label: 'Task late', days: -7, state: 'overdue' });
    expect(items.some((i) => i.label === 'Task done' || i.label === 'Task old')).toBe(false);
  });

  it('includes upcoming client deadlines but not ones already past', () => {
    const { deadlines } = generate(client({ entity_type: 'individual', extension_status: 'extended' }), '2026-10-08');
    const items = prioritizedCountdown([], deadlines, '2026-10-08');
    expect(items.map((i) => [i.label, i.date])).toEqual([['Form 1040 extended due date', '2026-10-15']]);
  });

  it('on the same day, the associate\'s own deadline comes before the standard date', () => {
    const standard = countdowns(TILES, '2026-10-08', holidays);
    const items = prioritizedCountdown(standard, [custom('same', '2026-10-15')], '2026-10-08');
    expect(items.slice(0, 2).map((i) => i.kind)).toEqual(['personal', 'standard']);
  });
});
