/**
 * The daily line on the dashboard: deterministic by calendar date, so a
 * refresh shows the same line all day, and drawn from the more encouraging
 * "deadline season" bank in the run-up to a countdown deadline.
 */

import type { ISODate } from './dates';

export interface MotivationBank {
  deadline_window_days: number;
  general: string[];
  deadline_season: string[];
}

/** A small stable string hash (FNV-1a). The same date always maps to the same line. */
export function hashString(value: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/**
 * @param daysToNextDeadline days to the nearest countdown deadline (from the
 *   countdown engine), or null if unknown.
 */
export function lineForDay(bank: MotivationBank, today: ISODate, daysToNextDeadline: number | null): {
  text: string; season: boolean;
} {
  const season = daysToNextDeadline !== null
    && daysToNextDeadline >= 0
    && daysToNextDeadline <= bank.deadline_window_days
    && bank.deadline_season.length > 0;
  const pool = season ? bank.deadline_season : bank.general;
  if (pool.length === 0) return { text: '', season: false };
  return { text: pool[hashString(today) % pool.length], season };
}
