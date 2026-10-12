/**
 * The guided import: jurisdiction and year first, upload only after that,
 * lives decided for the chosen year (AI suggestions with their reason), the
 * report recomputed on the server - and never shown for inputs it was not
 * computed from.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import type { AdditionImport, AdditionReport, AdditionReportRequest, DepreciationRules } from '../api/client';
import { axeViolations } from './workspaceFixtures';

const report = (request: AdditionReportRequest, bonus = '12000.00'): AdditionReport => ({
  tax_year: request.tax_year,
  state: request.state ? {
    code: request.state, name: request.state === 'CA' ? 'California' : 'Wisconsin', status: 'computed',
    message: 'Rules applied.', bonus_mode: request.state === 'CA' ? 'none' : 'follow',
    bonus_allowed: request.state !== 'CA',
    bonus_note: request.state === 'CA' ? 'California does not allow federal bonus depreciation for 2026; the basis is depreciated under MACRS instead.' : '',
    section_179_mode: 'follow', source_url: '', source_citation: '', notes: [],
  } : null,
  rows: request.assets.map((a) => ({
    asset_id: a.asset_id, description: a.description, acquired: a.acquired, cost: a.cost,
    life: a.asset_class === 'nonresidential' ? '39' : a.asset_class === 'machinery' ? '7' : '5',
    asset_class: a.asset_class, class_label: 'Other', convention: 'HY',
    elect_179: a.elect_179, elect_bonus: a.elect_bonus,
    sec179_eligible: a.asset_class !== 'nonresidential',
    sec179_reason: a.asset_class === 'nonresidential' ? 'Buildings are not section 179 property.' : '',
    bonus_eligible: a.asset_class !== 'nonresidential',
    bonus_reason: a.asset_class === 'nonresidential' ? '39-year property: the recovery period is over 20 years, so it is not qualified property.' : '',
    bonus_applied: a.elect_bonus, bonus_rate: '100', elections: 'Bonus',
    federal: { sec179: '0.00', bonus, macrs: '0.00', total: bonus, macrs_rate: '20' },
    state: request.state ? { sec179: '0', bonus: '0', macrs: '2400', total: '2400', addback: '0' } : null,
  })),
  totals: {
    cost: '12000.00',
    federal: { sec179: '0.00', bonus, macrs: '0.00', total: bonus },
    state: request.state ? { sec179: '0', bonus: '0', macrs: '2400', total: '2400', adjustment: '0' } : null,
  },
  summary: [{ life: '5', cost: '12000.00', depreciation: bonus }],
  elect_out_classes: [...new Set(request.assets.filter((a) => !a.elect_bonus && a.asset_class !== 'nonresidential')
    .map((a) => (a.asset_class === 'machinery' ? '7' : '5')))]
    .filter((life) => !request.assets.some((asset) => asset.elect_bonus
      && asset.asset_class !== 'nonresidential' && (asset.asset_class === 'machinery' ? '7' : '5') === life)),
  section_179: null, warnings: [],
  life_basis: `Lives are federal MACRS recovery periods (Rev. Proc. 87-56) for ${request.tax_year}.`,
});

const imported = (year: number): AdditionImport => ({
  tax_year: year, state: null, message: '', report_errors: [], report: null,
  rows: [
    {
      row: 2, asset_id: '101', description: 'Shop Equipment - Lift', acquired: '2026-04-30', cost: '12000.00',
      life_in_file: null, problems: [], issues: [],
      prediction: { asset_class: 'other', recovery_years: '5', life: '5', source: 'ai', confidence: 'high',
        reason: '57.0 distributive trades: dealership shop equipment.' },
    },
    {
      row: 3, asset_id: '102', description: 'Desk', acquired: null, cost: null, life_in_file: null,
      problems: ['no readable date acquired', 'no cost'],
      issues: [{ column: 'Date Acquired', message: 'no readable date acquired' }, { column: 'Cost', message: 'no cost' }],
      prediction: { asset_class: null, recovery_years: null, life: null, source: 'none', confidence: '', reason: 'Choose the life.' },
    },
  ],
});

const importAdditions = vi.fn(async (_file: File, options: { taxYear: number }) => imported(options.taxYear));
const additionsReport = vi.fn(async (request: AdditionReportRequest) => report(request));
const exportAdditions = vi.fn(async (_payload: unknown) => undefined);
const additionLives = vi.fn(async (payload: { tax_year: number; state: string | null }) => ({
  tax_year: payload.tax_year, state: payload.state, message: '',
  predictions: [
    { asset_class: 'computers', recovery_years: null, life: '5', source: 'ai' as const, confidence: 'medium', reason: 'Office technology.' },
    { asset_class: null, recovery_years: null, life: null, source: 'none' as const, confidence: '', reason: 'Choose the life.' },
  ],
}));
const additionsTemplate = vi.fn(async () => undefined);

vi.mock('../api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api/client')>();
  return {
    ...original,
    api: { depreciation: { importAdditions, additionsReport, exportAdditions, additionLives, additionsTemplate } },
  };
});

const rules = {
  supported_years: [2025, 2026], default_year: 2026, methods: [], federal: {}, rules_version: 'x',
  states: [
    { code: 'CA', name: 'California', business_tax: '', status_by_year: { 2025: 'verified', 2026: 'verified' }, changed_recently_years: [], change_notes: {} },
    { code: 'WI', name: 'Wisconsin', business_tax: '', status_by_year: { 2025: 'verified', 2026: 'unverified' }, changed_recently_years: [], change_notes: {} },
  ],
  asset_classes: [
    { key: 'computers', label: 'Computers and office equipment', recovery_years: '5', allowed_recovery_years: [],
      section_179_eligible: true, bonus_eligible: true, listed: false, real_property: false, suv_cap: false, qpp: false, note: '', source: {} },
    { key: 'other', label: 'Other', recovery_years: null, allowed_recovery_years: ['3', '5', '7'],
      section_179_eligible: true, bonus_eligible: true, listed: false, real_property: false, suv_cap: false, qpp: false, note: '', source: {} },
    { key: 'machinery', label: 'Machinery and equipment', recovery_years: '7', allowed_recovery_years: [],
      section_179_eligible: true, bonus_eligible: true, listed: false, real_property: false, suv_cap: false, qpp: false, note: '', source: {} },
    { key: 'nonresidential', label: 'Nonresidential building', recovery_years: '39', allowed_recovery_years: [],
      section_179_eligible: false, bonus_eligible: false, listed: false, real_property: true, suv_cap: false, qpp: false, note: '', source: {} },
  ],
} as unknown as DepreciationRules;

const onYear = vi.fn();

beforeEach(() => { vi.spyOn(window, 'confirm').mockReturnValue(true); });
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.restoreAllMocks(); });

async function renderImport() {
  const { default: AdditionsImport } = await import('../components/depreciation/AdditionsImport');
  return render(<AdditionsImport rules={rules} defaultYear={2026} onYear={onYear} />);
}

async function upload() {
  const input = document.querySelector('input[type=file]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(['x'], 'assets.xlsx')] } });
  await screen.findByText('Shop Equipment - Lift');
}

async function continueToUpload() {
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByRole('button', { name: /Upload an Excel or CSV asset list/ });
}

describe('AdditionsImport', () => {
  it('starts at Federal and the shared year, and keeps the upload locked until step 1 is done', async () => {
    const { container } = await renderImport();
    expect((screen.getByLabelText('Tax year') as HTMLSelectElement).value).toBe('2026');
    expect((screen.getByLabelText('Jurisdiction') as HTMLSelectElement).value).toBe('');
    expect(screen.queryByRole('button', { name: /Upload an Excel or CSV asset list/ })).toBeNull();
    expect(document.querySelector('input[type=file]')).toBeNull();
    expect(screen.getByText(/Choose the jurisdiction and tax year first/)).toBeTruthy();
    expect(screen.getByText('Jurisdiction and tax year').closest('li')!.getAttribute('aria-current')).toBe('step');
    await continueToUpload();
    expect(onYear).toHaveBeenCalledWith(2026);
    expect(await axeViolations(container)).toEqual([]);
  });

  it('sends the chosen year and jurisdiction with the upload', async () => {
    await renderImport();
    fireEvent.change(screen.getByLabelText('Tax year'), { target: { value: '2025' } });
    fireEvent.change(screen.getByLabelText('Jurisdiction'), { target: { value: 'CA' } });
    await continueToUpload();
    await upload();
    expect(importAdditions).toHaveBeenCalledWith(expect.any(File), { taxYear: 2025, state: 'CA', businessActivity: '' });
    expect(onYear).toHaveBeenCalledWith(2025);
  });

  it('shows each AI life with its reason as text, and unusable rows by column', async () => {
    const { container } = await renderImport();
    await continueToUpload();
    await upload();
    const select = screen.getByLabelText('Life for asset 101') as HTMLSelectElement;
    expect(select.value).toBe('other|5');
    // The reason is on screen, not hidden in a tooltip.
    expect(screen.getByText(/57.0 distributive trades: dealership shop equipment/)).toBeTruthy();
    expect(select.getAttribute('aria-describedby')).toBeTruthy();
    expect(screen.getByText(/Row 3 \(asset 102\): Date Acquired - no readable date acquired; Cost - no cost/)).toBeTruthy();
    expect(screen.getByLabelText('Life for asset 102')).toHaveProperty('disabled', true);
    expect(await axeViolations(container)).toEqual([]);
  });

  it('shows the report only for the inputs on screen, and exports the same request', async () => {
    let release: () => void = () => {};
    await renderImport();
    await continueToUpload();
    await upload();
    fireEvent.click(screen.getByRole('button', { name: /Show the report/ }));
    await screen.findByText('$12,000.00', { selector: 'td.dw-total' });

    // A life change: the old figures leave the screen until the new ones arrive.
    additionsReport.mockImplementationOnce((request) => new Promise((resolve) => { release = () => resolve(report(request, '7000.00')); }));
    fireEvent.click(screen.getByRole('button', { name: /Back to lives/ }));
    fireEvent.change(screen.getByLabelText('Life for asset 101'), { target: { value: 'computers|' } });
    expect(screen.getByText('Changed')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Show the report/ }));
    await screen.findByText(/Computing/);
    expect(screen.queryByText('$12,000.00', { selector: 'td.dw-total' })).toBeNull();
    await waitFor(() => expect(additionsReport.mock.calls.at(-1)![0].assets[0].asset_class).toBe('computers'));
    await act(async () => { release(); });
    await screen.findByText('$7,000.00', { selector: 'td.dw-total' });
    const request = additionsReport.mock.calls.at(-1)![0];
    expect(request.assets).toHaveLength(1);
    expect(request.assets[0]).toMatchObject({ asset_class: 'computers', elect_179: true, elect_bonus: true });

    fireEvent.click(screen.getByRole('button', { name: /Export Excel/ }));
    await waitFor(() => expect(exportAdditions).toHaveBeenCalledWith(request));
  });

  it('every election box is named for its asset', async () => {
    await renderImport();
    await continueToUpload();
    await upload();
    fireEvent.click(screen.getByRole('button', { name: /Show the report/ }));
    expect(await screen.findByRole('checkbox', { name: 'Sec 179 for 101 Shop Equipment - Lift' })).toBeTruthy();
  });

  it('a new state recomputes the figures without deciding lives again', async () => {
    await renderImport();
    await continueToUpload();
    await upload();
    fireEvent.click(screen.getByRole('button', { name: /Show the report/ }));
    await screen.findByText('$12,000.00', { selector: 'td.dw-total' });
    fireEvent.click(screen.getByRole('button', { name: /Change/ }));
    fireEvent.change(screen.getByLabelText('Jurisdiction'), { target: { value: 'CA' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply and recompute' }));
    await screen.findByText(/California does not allow federal bonus/);
    expect(additionsReport.mock.calls.at(-1)![0].state).toBe('CA');
    expect(additionLives).not.toHaveBeenCalled();
    const table = screen.getByRole('table');
    expect(within(table).getByText('California')).toBeTruthy();
  });

  it('a new year decides the lives again, asking first when that replaces lives the user chose', async () => {
    await renderImport();
    await continueToUpload();
    await upload();
    fireEvent.change(screen.getByLabelText('Life for asset 101'), { target: { value: 'other|7' } });

    // Cancelled: nothing changes.
    vi.mocked(window.confirm).mockReturnValueOnce(false);
    fireEvent.click(screen.getByRole('button', { name: /Change/ }));
    fireEvent.change(screen.getByLabelText('Tax year'), { target: { value: '2025' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply and recompute' }));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('The 1 life you chose will be replaced'));
    expect(additionLives).not.toHaveBeenCalled();

    // Confirmed: lives decided for 2025, and the 2026 asset is now out of the year.
    fireEvent.click(screen.getByRole('button', { name: 'Apply and recompute' }));
    await waitFor(() => expect(additionLives).toHaveBeenCalledWith(expect.objectContaining({ tax_year: 2025 })));
    await screen.findByText(/Date Acquired: acquired in 2026, not a 2025 addition/);
    expect(onYear).toHaveBeenLastCalledWith(2025);
  });

  it('offers the upload template', async () => {
    await renderImport();
    await continueToUpload();
    fireEvent.click(screen.getByRole('button', { name: /Download template/ }));
    await waitFor(() => expect(additionsTemplate).toHaveBeenCalled());
  });
});

// ---------------------------------------------------------------------------
// The bonus election, alongside Section 179
// ---------------------------------------------------------------------------

const fileRow = (n: number, id: string, description: string, cls: string, life: string) => ({
  row: n, asset_id: id, description, acquired: '2026-03-15', cost: '10000.00', life_in_file: life,
  problems: [], issues: [],
  prediction: { asset_class: cls, recovery_years: null, life, source: 'file' as const, confidence: 'high', reason: 'Life taken from the uploaded file.' },
});

const mixed: AdditionImport = {
  tax_year: 2026, state: null, message: '', report_errors: [], report: null,
  rows: [
    fileRow(2, '201', 'Lathe', 'machinery', '7'),
    fileRow(3, '202', 'Forklift', 'machinery', '7'),
    fileRow(4, '203', 'Laptop', 'computers', '5'),
    fileRow(5, '204', 'Warehouse', 'nonresidential', '39'),
  ],
};

async function toReport(state = '') {
  importAdditions.mockResolvedValueOnce(mixed);
  await renderImport();
  if (state) fireEvent.change(screen.getByLabelText('Jurisdiction'), { target: { value: state } });
  await continueToUpload();
  const input = document.querySelector('input[type=file]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(['x'], 'assets.xlsx')] } });
  await screen.findByText('Lathe');
  fireEvent.click(screen.getByRole('button', { name: /Show the report/ }));
  await screen.findByRole('checkbox', { name: 'Bonus for 201 Lathe' });
  await screen.findByText('Figures for 4 assets, tax year 2026.');
}

const box = (name: string) => screen.getByRole('checkbox', { name }) as HTMLInputElement;
const lastRequest = () => additionsReport.mock.calls.at(-1)![0];
const electionsOf = (key: 'elect_179' | 'elect_bonus') =>
  Object.fromEntries(lastRequest().assets.map((a) => [a.asset_id, a[key]]));

describe('bonus election in the report', () => {
  it('has a bonus box per asset next to Section 179, sent with the report request', async () => {
    await toReport();
    expect(box('Sec 179 for 203 Laptop').checked).toBe(true);
    expect(box('Bonus for 203 Laptop').checked).toBe(true);
    fireEvent.click(box('Bonus for 203 Laptop'));
    await waitFor(() => expect(electionsOf('elect_bonus')['203']).toBe(false));
    fireEvent.click(box('Sec 179 for 203 Laptop'));
    await waitFor(() => expect(electionsOf('elect_179')['203']).toBe(false));
  });

  it('changing bonus affects only the selected asset, even within the same class', async () => {
    await toReport();
    fireEvent.click(box('Bonus for 201 Lathe'));
    expect(box('Bonus for 201 Lathe').checked).toBe(false);
    expect(box('Bonus for 202 Forklift').checked).toBe(true);
    expect(box('Bonus for 203 Laptop').checked).toBe(true);
    expect(box('All bonus').indeterminate).toBe(true);
    await waitFor(() => expect(electionsOf('elect_bonus')).toMatchObject({ 201: false, 202: true, 203: true }));
    fireEvent.click(box('Bonus for 201 Lathe'));
    await waitFor(() => expect(electionsOf('elect_bonus')).toMatchObject({ 201: true, 202: true, 203: true }));
  });

  it('select all and clear all act on the eligible assets, with a mixed state in between', async () => {
    await toReport();
    const all179 = box('All Sec 179');
    const allBonus = box('All bonus');
    expect(all179.checked).toBe(true);
    fireEvent.click(box('Sec 179 for 201 Lathe'));
    expect(all179.indeterminate).toBe(true);
    fireEvent.click(all179); // mixed -> all
    expect(box('Sec 179 for 201 Lathe').checked && box('Sec 179 for 203 Laptop').checked).toBe(true);
    fireEvent.click(allBonus); // all -> none
    expect(box('Bonus for 201 Lathe').checked || box('Bonus for 203 Laptop').checked).toBe(false);
    await waitFor(() => expect(electionsOf('elect_bonus')).toMatchObject({ 201: false, 202: false, 203: false }));
    fireEvent.click(allBonus); // none -> all
    expect(box('Bonus for 203 Laptop').checked).toBe(true);
  });

  it('preserves individual 179 and bonus choices when revisiting lives and exporting', async () => {
    await toReport();
    fireEvent.click(box('Sec 179 for 201 Lathe'));
    fireEvent.click(box('Bonus for 202 Forklift'));
    expect(box('Sec 179 for 202 Forklift').checked).toBe(true);
    expect(box('Bonus for 201 Lathe').checked).toBe(true);
    expect(box('All Sec 179').indeterminate).toBe(true);
    expect(box('All bonus').indeterminate).toBe(true);
    expect(screen.getByRole('button', { name: /Export Excel/ })).toHaveProperty('disabled', true);
    await waitFor(() => {
      expect(electionsOf('elect_179')).toMatchObject({ 201: false, 202: true, 203: true });
      expect(electionsOf('elect_bonus')).toMatchObject({ 201: true, 202: false, 203: true });
    });
    await screen.findByText('Figures for 4 assets, tax year 2026.');
    fireEvent.click(screen.getByRole('button', { name: /Back to lives/ }));
    fireEvent.click(screen.getByRole('button', { name: /Show the report/ }));
    expect(box('Sec 179 for 201 Lathe').checked).toBe(false);
    expect(box('Sec 179 for 202 Forklift').checked).toBe(true);
    expect(box('Bonus for 201 Lathe').checked).toBe(true);
    expect(box('Bonus for 202 Forklift').checked).toBe(false);
    const request = lastRequest();
    fireEvent.click(screen.getByRole('button', { name: /Export Excel/ }));
    await waitFor(() => expect(exportAdditions).toHaveBeenCalledWith(request));
  });

  it('an ineligible asset has disabled boxes and says why', async () => {
    await toReport();
    await screen.findByText(/over 20 years/); // the server's reason, once the report is in
    const bonus = box('Bonus for 204 Warehouse');
    const s179 = box('Sec 179 for 204 Warehouse');
    expect(bonus.disabled && s179.disabled).toBe(true);
    expect(bonus.checked || s179.checked).toBe(false);
    expect(document.getElementById(bonus.getAttribute('aria-describedby')!)!.textContent).toMatch(/over 20 years/);
    expect(document.getElementById(s179.getAttribute('aria-describedby')!)!.textContent).toMatch(/not section 179 property/);
  });

  it('marks the state bonus column when the state does not allow bonus, and says why', async () => {
    await toReport('CA');
    expect(await screen.findByText('Not allowed')).toBeTruthy();
    const tip = screen.getAllByRole('button', { name: 'More information' }).at(-1)!;
    fireEvent.mouseEnter(tip);
    expect(screen.getByRole('tooltip').textContent).toMatch(/California does not allow federal bonus/);
    // The election is federal; the state applies its own rule to it.
    expect(box('Bonus for 203 Laptop').checked).toBe(true);
  });
});
