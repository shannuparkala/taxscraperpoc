import { describe, expect, it } from 'vitest';

import {
  adjustmentLabel, blankAsset, caretAfterGrouping, formProblem, groupDigits, money, shiftYear, toRequest,
  withAcquired, type CalculatorForm,
} from '../lib/depreciationForm';

function form(overrides: Partial<CalculatorForm> = {}): CalculatorForm {
  return {
    taxYear: 2026,
    state: 'CA',
    method: 'bonus',
    assets: [{ ...blankAsset(2026), cost: '$100,000' }],
    taxableIncome: '',
    totalPurchases: '',
    carryover: '',
    federalRate: '',
    stateRate: '',
    includeProvisional: false,
    ...overrides,
  };
}

describe('depreciation form helpers', () => {
  it('strips currency formatting and turns blanks into null', () => {
    const request = toRequest(form({ taxableIncome: ' 50,000 ' }));
    expect(request.assets[0].cost).toBe('100000');
    expect(request.taxable_business_income).toBe('50000');
    expect(request.total_179_purchases).toBeNull();
    expect(request.section_179_carryover).toBe('0');
  });

  it('only sends a recovery period for the "other" class', () => {
    const other = toRequest(form({ assets: [{ ...blankAsset(2026), cost: '1', asset_class: 'other', recovery_years: '10' }] }));
    expect(other.assets[0].recovery_years).toBe('10');
    expect(toRequest(form()).assets[0].recovery_years).toBeNull();
  });

  it('defaults a new asset to mid-year, clear of the mid-quarter test and the 2025 bonus cutoff', () => {
    const asset = blankAsset(2025);
    expect(asset.placed_in_service).toBe('2025-06-01');
    expect(asset.acquired).toBe('2025-06-01');
  });

  it('moves dates with the tax year', () => {
    const moved = shiftYear({ ...blankAsset(2025), acquired: '2024-12-01' }, 2025, 2026);
    expect(moved.placed_in_service).toBe('2026-06-01');
    expect(moved.acquired).toBe('2024-12-01'); // only dates in the old tax year move
  });

  it('says what is missing before calculating', () => {
    expect(formProblem(form({ assets: [{ ...blankAsset(2026) }] }))).toMatch(/cost basis/);
    expect(formProblem(form())).toBe('');
  });

  it('formats money and signed adjustments', () => {
    expect(money('1234567')).toBe('$1,234,567');
    expect(money('-80000')).toBe('−$80,000');
    expect(adjustmentLabel('80000')).toBe('+$80,000 add back');
    expect(adjustmentLabel('-16000')).toBe('$16,000 subtract');
    expect(adjustmentLabel('0')).toBe('—');
  });

  it('groups cost basis digits with commas as typed', () => {
    expect(groupDigits('1234567')).toBe('1,234,567');
    expect(groupDigits('1,2345')).toBe('12,345');
    expect(groupDigits('$ 100000')).toBe('100,000');
    expect(groupDigits('999')).toBe('999');
    expect(groupDigits('0012')).toBe('12');
    expect(groupDigits('1234.567')).toBe('1,234.56');
    expect(groupDigits('1.2.3')).toBe('1.23');
    expect(groupDigits('abc')).toBe('');
    // And the request still carries the plain number.
    expect(toRequest(form({ assets: [{ ...blankAsset(2026), cost: groupDigits('2500000') }] })).assets[0].cost)
      .toBe('2500000');
  });

  it('keeps the caret after the same digits when commas are inserted', () => {
    // Typed "1234|" -> "1,234|": four digits before the caret, caret at 5.
    expect(caretAfterGrouping('1,234', 4)).toBe(5);
    // Caret after the first digit of "1,234,567".
    expect(caretAfterGrouping('1,234,567', 1)).toBe(1);
    expect(caretAfterGrouping('1,234,567', 2)).toBe(3);
    expect(caretAfterGrouping('1,234', 0)).toBe(0);
  });

  it('copies the acquisition date into placed-in-service until they diverge', () => {
    const asset = blankAsset(2026);
    const moved = withAcquired(asset, '2026-03-15');
    expect(moved.placed_in_service).toBe('2026-03-15');
    const changed = { ...moved, placed_in_service: '2026-04-01' };
    const later = withAcquired(changed, '2026-02-01');
    expect(later.acquired).toBe('2026-02-01');
    expect(later.placed_in_service).toBe('2026-04-01');
    expect(withAcquired({ ...asset, placed_in_service: '' }, '2026-05-05').placed_in_service).toBe('2026-05-05');
  });

  it('sends a selected convention and null for automatic', () => {
    const auto = toRequest(form());
    expect(auto.assets[0].convention).toBeNull();
    const chosen = toRequest(form({ assets: [{ ...blankAsset(2026), cost: '1000', convention: 'MQ' }] }));
    expect(chosen.assets[0].convention).toBe('MQ');
  });
});
