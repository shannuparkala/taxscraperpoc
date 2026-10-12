/**
 * The tax year a section shows, given the shared selection and the years
 * that section holds rules for.
 *
 * Mirrors the server's `core/tax_year.resolve`: the chosen year if covered,
 * else the latest covered year before it, else the earliest covered year
 * after it. A section never shows a year it has no rules for, and never
 * jumps forward past what was chosen while an earlier year is available.
 */
export function yearWithin(year: number, supported: readonly number[]): number {
  if (!supported.length || supported.includes(year)) return year;
  const sorted = [...supported].sort((a, b) => a - b);
  const earlier = sorted.filter((y) => y < year);
  return earlier.length ? earlier[earlier.length - 1] : sorted[0];
}
