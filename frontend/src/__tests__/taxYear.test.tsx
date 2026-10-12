/**
 * The shared tax year: the server's default until one is chosen, and each
 * section clamped to the years it holds rules for.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { yearWithin } from '../lib/taxYear';

const dashboard = vi.fn();

vi.mock('../api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api/client')>();
  return { ...original, api: { reference: { dashboard: () => dashboard() } } };
});

const { TaxContextProvider, useTaxContext } = await import('../context/TaxContext');

function Probe() {
  const { taxYear, setTaxYear } = useTaxContext();
  return (
    <>
      <output aria-label="year">{taxYear}</output>
      <button type="button" onClick={() => setTaxYear(2024)}>Pick 2024</button>
    </>
  );
}

function renderProbe() {
  return render(<MemoryRouter><TaxContextProvider><Probe /></TaxContextProvider></MemoryRouter>);
}

beforeEach(() => {
  sessionStorage.clear();
  dashboard.mockReset();
});
afterEach(cleanup);

describe('yearWithin', () => {
  it('keeps a covered year', () => {
    expect(yearWithin(2026, [2025, 2026])).toBe(2026);
  });
  it('falls back to the latest covered year before the chosen one', () => {
    expect(yearWithin(2027, [2021, 2025, 2026])).toBe(2026);
    expect(yearWithin(2026, [2024, 2025])).toBe(2025);
  });
  it('moves forward only when nothing earlier is covered', () => {
    expect(yearWithin(2020, [2025, 2026])).toBe(2025);
  });
  it('leaves the year alone when the section has not loaded its years', () => {
    expect(yearWithin(2026, [])).toBe(2026);
  });
});

describe('TaxContext year', () => {
  it("adopts the server's default year", async () => {
    dashboard.mockResolvedValue({ default_tax_year: 2026, supported_years: [2025, 2026] });
    renderProbe();
    expect((await screen.findByLabelText('year')).textContent).toBe(String(new Date().getFullYear()));
    await act(async () => {});
    expect(screen.getByLabelText('year').textContent).toBe('2026');
  });

  it('keeps a year the user chose this session over the default', async () => {
    sessionStorage.setItem('taxscraper_tax_year', '2025');
    dashboard.mockResolvedValue({ default_tax_year: 2026, supported_years: [2025, 2026] });
    renderProbe();
    await act(async () => {});
    expect(screen.getByLabelText('year').textContent).toBe('2025');
    expect(dashboard).not.toHaveBeenCalled();
  });

  it('a choice made while the default is loading is not overwritten', async () => {
    let answer: (value: unknown) => void = () => {};
    dashboard.mockReturnValue(new Promise((resolve) => { answer = resolve; }));
    renderProbe();
    act(() => screen.getByRole('button', { name: 'Pick 2024' }).click());
    await act(async () => answer({ default_tax_year: 2026, supported_years: [2025, 2026] }));
    expect(screen.getByLabelText('year').textContent).toBe('2024');
  });
});
