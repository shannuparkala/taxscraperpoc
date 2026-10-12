import { describe, expect, it } from 'vitest';

import {
  HolidayCalendar,
  addDays,
  addMonths,
  daysInMonth,
  daysLabel,
  diffDays,
  formatLong,
  greetingFor,
  holidaysInYear,
  hourIn,
  isLeapYear,
  nthWeekday,
  parseISO,
  todayIn,
  weekday,
} from '../lib/dates';
import holidayFile from '../../../backend/app/reference_data/calendar/legal_holidays.json';
import type { HolidayData } from '../lib/dates';

const HOLIDAYS = holidayFile.holidays as HolidayData[];
const calendar = new HolidayCalendar(HOLIDAYS);

describe('calendar arithmetic', () => {
  it('knows leap years, including the century rules', () => {
    expect(isLeapYear(2024)).toBe(true);
    expect(isLeapYear(2026)).toBe(false);
    expect(isLeapYear(1900)).toBe(false);
    expect(isLeapYear(2000)).toBe(true);
    expect(daysInMonth(2028, 2)).toBe(29);
    expect(daysInMonth(2027, 2)).toBe(28);
  });

  it('counts calendar days across a year boundary and a leap day', () => {
    expect(diffDays('2027-12-31', '2028-01-01')).toBe(1);
    expect(diffDays('2028-02-28', '2028-03-01')).toBe(2); // Feb 29 exists
    expect(diffDays('2027-02-28', '2027-03-01')).toBe(1);
    expect(diffDays('2026-10-07', '2027-04-15')).toBe(190);
    expect(diffDays('2027-04-15', '2026-10-07')).toBe(-190);
  });

  it('is unaffected by daylight-saving changes (it never uses instants)', () => {
    // US clocks change on 2027-03-14 and 2027-11-07; a 23- or 25-hour day is still one day.
    expect(diffDays('2027-03-13', '2027-03-15')).toBe(2);
    expect(diffDays('2027-11-06', '2027-11-08')).toBe(2);
  });

  it('adds days and clamps months', () => {
    expect(addDays('2028-02-28', 1)).toBe('2028-02-29');
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01');
    expect(addMonths('2027-01-31', 1)).toBe('2027-02-28');
    expect(addMonths('2028-01-31', 1)).toBe('2028-02-29');
    expect(addMonths('2026-06-30', 7)).toBe('2027-01-30');
    expect(addMonths('2026-03-15', -12)).toBe('2025-03-15');
  });

  it('rejects impossible dates', () => {
    expect(() => parseISO('2027-02-29')).toThrow();
    expect(() => parseISO('2027-13-01')).toThrow();
    expect(() => parseISO('April 15')).toThrow();
  });

  it('numbers weekdays Monday first', () => {
    expect(weekday('2027-04-12')).toBe(0); // Monday
    expect(weekday('2027-04-17')).toBe(5); // Saturday
    expect(weekday('2027-04-18')).toBe(6); // Sunday
  });

  it('formats a calendar date without shifting it by a time zone', () => {
    expect(formatLong('2027-04-15', 'en-US')).toBe('Thursday, April 15, 2027');
  });

  it('labels day counts', () => {
    expect(daysLabel(0)).toBe('Due today');
    expect(daysLabel(1)).toBe('1 day');
    expect(daysLabel(12)).toBe('12 days');
    expect(daysLabel(-3)).toBe('3 days overdue');
  });
});

describe("the user's today", () => {
  // 2027-04-15T05:30Z: still April 14 on the US west coast, already the 15th in Tokyo.
  const instant = new Date(Date.UTC(2027, 3, 15, 5, 30));

  it('reads the wall-clock date in the given zone', () => {
    expect(todayIn('America/Los_Angeles', instant)).toBe('2027-04-14');
    expect(todayIn('America/New_York', instant)).toBe('2027-04-15');
    expect(todayIn('Asia/Tokyo', instant)).toBe('2027-04-15');
    expect(todayIn('UTC', instant)).toBe('2027-04-15');
  });

  it('greets by local hour', () => {
    expect(hourIn('America/Los_Angeles', instant)).toBe(22);
    expect(greetingFor(hourIn('America/Los_Angeles', instant))).toBe('Good evening');
    expect(greetingFor(hourIn('Asia/Tokyo', instant))).toBe('Good afternoon');
    expect(greetingFor(8)).toBe('Good morning');
    expect(greetingFor(3)).toBe('Good evening');
    expect(greetingFor(12)).toBe('Good afternoon');
  });
});

describe('legal holidays (from legal_holidays.json)', () => {
  it('finds nth and last weekdays', () => {
    expect(nthWeekday(2027, 1, 0, 3)).toBe('2027-01-18'); // MLK Day
    expect(nthWeekday(2027, 5, 0, -1)).toBe('2027-05-31'); // Memorial Day
    expect(nthWeekday(2027, 11, 3, 4)).toBe('2027-11-25'); // Thanksgiving
  });

  it('matches OPM\'s published 2026 schedule', () => {
    // OPM federal holidays 2026, plus DC Emancipation Day (Thu Apr 16).
    const expected = [
      '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-16', '2026-05-25', '2026-06-19',
      '2026-07-03', // July 4 is a Saturday: observed Friday
      '2026-09-07', '2026-10-12', '2026-11-11', '2026-11-26', '2026-12-25',
    ];
    expect([...holidaysInYear(HOLIDAYS, 2026).keys()].sort()).toEqual(expected);
  });

  it('observes a Saturday New Year on the previous Friday, in the prior year', () => {
    // 2028-01-01 is a Saturday -> observed Friday 2027-12-31.
    expect(holidaysInYear(HOLIDAYS, 2027).get('2027-12-31')).toBe("New Year's Day");
    expect(holidaysInYear(HOLIDAYS, 2028).has('2027-12-31')).toBe(false);
  });

  it('includes Inauguration Day only in inauguration years', () => {
    expect(holidaysInYear(HOLIDAYS, 2029).get('2029-01-20')).toBe('Inauguration Day (DC area)'); // a Saturday: not moved
    expect([...holidaysInYear(HOLIDAYS, 2027).values()]).not.toContain('Inauguration Day (DC area)');
  });

  it('applies Juneteenth only from 2021', () => {
    expect(holidaysInYear(HOLIDAYS, 2020).has('2020-06-19')).toBe(false);
    expect(holidaysInYear(HOLIDAYS, 2021).has('2021-06-18')).toBe(true); // Saturday -> Friday
  });

  it('moves a due date past weekends and holidays (IRC 7503)', () => {
    expect(calendar.nextBusinessDay('2027-04-15')).toBe('2027-04-15'); // Thursday
    expect(calendar.nextBusinessDay('2027-04-17')).toBe('2027-04-19'); // Saturday -> Monday
    // 2028: the 15th is a Saturday and Emancipation Day (Sun 16th) is observed Mon 17th -> Tue 18th.
    expect(calendar.nextBusinessDay('2028-04-15')).toBe('2028-04-18');
    // 2022: April 15 was Emancipation Day observed (Apr 16 was a Saturday), so returns were due Mon 18th.
    expect(calendar.nextBusinessDay('2022-04-15')).toBe('2022-04-18');
    expect(calendar.reasonClosed('2022-04-15')).toBe('District of Columbia Emancipation Day');
    // 2011: the same thing happened.
    expect(calendar.nextBusinessDay('2011-04-15')).toBe('2011-04-18');
    // Columbus Day 2029 is Monday Oct 8; Oct 15 2029 is a Monday business day.
    expect(calendar.nextBusinessDay('2029-10-15')).toBe('2029-10-15');
  });
});
