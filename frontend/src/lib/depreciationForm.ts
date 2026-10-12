/**
 * Pure helpers for the depreciation form: blank rows, request building,
 * formatting. No arithmetic on tax figures happens in the browser - the
 * server computes everything; this file only shapes inputs and prints
 * outputs.
 */

import type { DepreciationAssetInput, DepreciationRequest } from '../api/client';

/**
 * The reduced-rate bonus election (40% instead of 100%), read from the rule
 * data: its rate and the placed-in-service years it is available for. No
 * year is written into the page.
 */
export function reducedBonusElection(federal: Record<string, unknown>): { rate: number; years: number[] } | null {
  const rules = (federal.bonus_rules ?? []) as { reduced_rate_election?: { rate: number; tax_years: number[] } }[];
  const election = rules.find((rule) => rule.reduced_rate_election)?.reduced_rate_election;
  return election ? { rate: election.rate, years: election.tax_years } : null;
}

export interface CalculatorForm {
  taxYear: number;
  state: string | null;
  method: string;
  assets: DepreciationAssetInput[];
  taxableIncome: string;
  totalPurchases: string;
  carryover: string;
  federalRate: string;
  stateRate: string;
  includeProvisional: boolean;
}

let counter = 0;

export function blankAsset(taxYear: number): DepreciationAssetInput {
  counter += 1;
  // Mid-year: a new row should not trip the mid-quarter convention or sit on
  // the Jan. 19, 2025 bonus cutoff before the user has entered a real date.
  const day = `${taxYear}-06-01`;
  return {
    id: `asset-${Date.now().toString(36)}-${counter}`,
    description: '',
    asset_class: 'computers',
    cost: '',
    placed_in_service: day,
    acquired: day,
    business_use_pct: '100',
    land_value: '0',
    recovery_years: null,
    section_179_amount: null,
    elect_out_bonus: false,
    elect_reduced_bonus: false,
    clean_vehicle_credit: '0',
    suv_cap_exempt: false,
    qpp_elect: false,
    qpp_construction_began: null,
    convention: null,
  };
}

const blank = (value: string | null | undefined): string | null => {
  const trimmed = (value ?? '').replace(/[$,\s]/g, '');
  return trimmed === '' ? null : trimmed;
};

/** Is the form complete enough to send? Returns the first problem, or ''. */
export function formProblem(form: CalculatorForm): string {
  if (form.assets.length === 0) return 'Add an asset to calculate.';
  for (const [index, asset] of form.assets.entries()) {
    const label = asset.description || `Asset ${index + 1}`;
    const cost = Number(blank(asset.cost));
    if (!blank(asset.cost) || !Number.isFinite(cost) || cost <= 0) return `${label}: enter a cost basis.`;
    if (!asset.placed_in_service) return `${label}: enter the date placed in service.`;
  }
  return '';
}

export function toRequest(form: CalculatorForm): DepreciationRequest {
  return {
    tax_year: form.taxYear,
    state: form.state,
    method: form.method,
    include_provisional_state: form.includeProvisional,
    taxable_business_income: blank(form.taxableIncome),
    total_179_purchases: blank(form.totalPurchases),
    section_179_carryover: blank(form.carryover) ?? '0',
    federal_marginal_rate: blank(form.federalRate),
    state_marginal_rate: blank(form.stateRate),
    assets: form.assets.map((asset) => ({
      ...asset,
      cost: blank(asset.cost) ?? '0',
      land_value: blank(asset.land_value) ?? '0',
      clean_vehicle_credit: blank(asset.clean_vehicle_credit) ?? '0',
      business_use_pct: blank(asset.business_use_pct) ?? '100',
      section_179_amount: blank(asset.section_179_amount),
      acquired: asset.acquired || null,
      recovery_years: asset.asset_class === 'other' ? asset.recovery_years || '7' : null,
      qpp_construction_began: asset.qpp_construction_began || null,
      convention: asset.convention || null,
    })),
  };
}

export function money(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  const amount = Number(value);
  if (!Number.isFinite(amount)) return '—';
  const text = Math.abs(amount).toLocaleString('en-US', { maximumFractionDigits: 0 });
  return amount < 0 ? `−$${text}` : `$${text}`;
}

/** Sign-aware label for a state adjustment: positive adds back, negative subtracts. */
export function adjustmentLabel(value: string): string {
  const amount = Number(value);
  if (!amount) return '—';
  return amount > 0 ? `+${money(value)} add back` : `${money(String(-amount))} subtract`;
}

/**
 * Group the digits of a typed amount with commas as the user types:
 * "1234567.5" -> "1,234,567.5". Anything that is not a digit or the first
 * decimal point is dropped, and at most two decimals are kept. Display only:
 * ``toRequest`` strips the commas again before anything is sent.
 */
export function groupDigits(raw: string): string {
  const cleaned = raw.replace(/[^\d.]/g, '');
  const dot = cleaned.indexOf('.');
  const whole = (dot === -1 ? cleaned : cleaned.slice(0, dot)).replace(/^0+(?=\d)/, '');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  if (dot === -1) return grouped;
  const cents = cleaned.slice(dot + 1).replace(/\./g, '').slice(0, 2);
  return `${grouped || '0'}.${cents}`;
}

/**
 * Where the caret belongs after ``groupDigits`` reformats: after the same
 * number of digits (and decimal point) that preceded it before.
 */
export function caretAfterGrouping(formatted: string, significantBefore: number): number {
  if (significantBefore <= 0) return 0;
  let seen = 0;
  for (let index = 0; index < formatted.length; index += 1) {
    if (formatted[index] !== ',') seen += 1;
    if (seen === significantBefore) return index + 1;
  }
  return formatted.length;
}

/** Changing the acquisition date carries the placed-in-service date with it
 * while the two are still the same (or PIS is empty). Once the user sets a
 * different placed-in-service date, the link is broken and stays broken. */
export function withAcquired(asset: DepreciationAssetInput, acquired: string): DepreciationAssetInput {
  const linked = !asset.placed_in_service || asset.placed_in_service === (asset.acquired ?? '');
  return linked && acquired
    ? { ...asset, acquired, placed_in_service: acquired }
    : { ...asset, acquired };
}

/** Move dates that sat in the old tax year into the new one (a year change re-targets the form). */
export function shiftYear(asset: DepreciationAssetInput, from: number, to: number): DepreciationAssetInput {
  const move = (value: string | null | undefined) =>
    value && value.startsWith(`${from}-`) ? `${to}${value.slice(4)}` : value ?? null;
  return { ...asset, placed_in_service: move(asset.placed_in_service) ?? '', acquired: move(asset.acquired) };
}
