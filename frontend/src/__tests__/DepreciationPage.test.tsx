/**
 * The depreciation workspace against a real engine result (fixtures captured
 * from the backend), with the API mocked.
 */

import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import resultFixture from './fixtures/result.json';
import rulesFixture from './fixtures/rules.json';
import { MemoryRouter } from 'react-router-dom';

import { SELECTED_STATE_KEY } from '../lib/selectedState';
import { axeViolations } from './workspaceFixtures';

const calculate = vi.fn();
const exportCsv = vi.fn();
const exportPdf = vi.fn();
const explain = vi.fn();

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    api: {
      depreciation: {
        rules: () => Promise.resolve(rulesFixture),
        calculate: (...args: unknown[]) => calculate(...args),
        exportCsv: (...args: unknown[]) => exportCsv(...args),
        exportPdf: (...args: unknown[]) => exportPdf(...args),
        explain: (...args: unknown[]) => explain(...args),
      },
      reference: {
        // The shared year selector's default (DEFAULT_TAX_YEAR on the server).
        dashboard: () => Promise.resolve({ default_tax_year: 2026, supported_years: [2025, 2026] }),
      },
      chat: {
        states: () => Promise.resolve([
          { code: 'CA', name: 'California' },
          { code: 'TX', name: 'Texas' },
          { code: 'PR', name: 'Puerto Rico' },
        ]),
      },
    },
  };
});

// Imported after the mock is registered.
const { default: DepreciationPage } = await import('../pages/DepreciationPage');
const { TaxContextProvider } = await import('../context/TaxContext');

async function renderPage() {
  const view = render(<MemoryRouter><TaxContextProvider><DepreciationPage /></TaxContextProvider></MemoryRouter>);
  await screen.findByRole('heading', { name: 'Depreciation Calculator' });
  return view;
}

async function enterCost(value = '100000') {
  const cost = screen.getByLabelText('Cost basis');
  fireEvent.change(cost, { target: { value } });
  await waitFor(() => expect(calculate).toHaveBeenCalled(), { timeout: 2000 });
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear(); // the shared tax year lives here
  // Echo the request's asset id, as the backend does, so the page can match
  // result rows to the form's assets.
  calculate.mockReset().mockImplementation((request: { assets: { id: string }[] }) => Promise.resolve({
    ...resultFixture,
    assets: resultFixture.assets.map((asset, i) => ({ ...asset, id: request.assets[i]?.id ?? asset.id })),
  }));
  exportCsv.mockReset().mockResolvedValue(undefined);
  exportPdf.mockReset().mockResolvedValue(undefined);
  explain.mockReset();
});

afterEach(() => cleanup());

describe('DepreciationPage', () => {
  it('pre-fills the state from the map selection shared with the assistant', async () => {
    localStorage.setItem(SELECTED_STATE_KEY, 'CA');
    await renderPage();
    expect((screen.getByLabelText('State') as HTMLSelectElement).value).toBe('CA');
  });

  it('drops a remembered state the calculator does not support', async () => {
    localStorage.setItem(SELECTED_STATE_KEY, 'PR');
    await renderPage();
    expect((screen.getByLabelText('State') as HTMLSelectElement).value).toBe('');
  });

  it('a map click fills the state field and is shared back to the assistant', async () => {
    await renderPage();
    const texas = await screen.findByRole('button', { name: 'Texas' });
    fireEvent.click(texas);
    expect((screen.getByLabelText('State') as HTMLSelectElement).value).toBe('TX');
    expect(localStorage.getItem(SELECTED_STATE_KEY)).toBe('TX');
  });

  it('recalculates when the tax year changes', async () => {
    await renderPage();
    await enterCost();
    calculate.mockClear();
    fireEvent.change(screen.getByLabelText('Tax year'), { target: { value: '2024' } });
    await waitFor(() => expect(calculate).toHaveBeenCalled(), { timeout: 2000 });
    const request = calculate.mock.calls.at(-1)![0];
    expect(request.tax_year).toBe(2024);
    expect(request.assets[0].placed_in_service.startsWith('2024-')).toBe(true);
  });

  it('shows the engine numbers in the summary, tape and schedule', async () => {
    await renderPage();
    await enterCost();
    await screen.findByText('Calculation tape');
    expect(screen.getAllByText('$100,000').length).toBeGreaterThan(0);
    const tape = screen.getByRole('table', { name: 'Calculation tape' });
    const assetTape = resultFixture.assets[0].tape;
    const lastLine = assetTape.at(-1)!.lines.at(-1)!;
    expect(within(tape).getAllByText(lastLine.label).length).toBeGreaterThan(0);
    // The selected tax year row is marked.
    expect(screen.getAllByText('Selected').length).toBeGreaterThan(0);
  });

  it('expanding a year shows why the amount is what it is', async () => {
    await renderPage();
    await enterCost();
    // The selected tax year (year 1 here) opens by default; open year 2.
    const selected = await screen.findByRole('button', { name: /Year 1/ });
    expect(selected.getAttribute('aria-expanded')).toBe('true');
    const yearTwo = screen.getByRole('button', { name: /Year 2/ });
    expect(yearTwo.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(yearTwo);
    expect(yearTwo.getAttribute('aria-expanded')).toBe('true');
    const reason = resultFixture.assets[0].schedule[1].why[0];
    expect(await screen.findByText(reason)).toBeTruthy();
  });

  it('exports with exactly the inputs used for the on-screen result', async () => {
    await renderPage();
    await enterCost();
    await screen.findByText('Calculation tape');
    fireEvent.click(screen.getByRole('button', { name: /Export/ }));
    fireEvent.click(screen.getByRole('menuitem', { name: /CSV/ }));
    await waitFor(() => expect(exportCsv).toHaveBeenCalled());
    expect(exportCsv.mock.calls[0][0]).toEqual(calculate.mock.calls.at(-1)![0]);
    fireEvent.click(screen.getByRole('button', { name: /Export/ }));
    fireEvent.click(screen.getByRole('menuitem', { name: /PDF/ }));
    await waitFor(() => expect(exportPdf).toHaveBeenCalled());
  });

  it('the election switches map to the calculation method', async () => {
    await renderPage();
    await enterCost();
    calculate.mockClear();
    const s179 = screen.getByRole('switch', { name: 'Section 179 expensing' });
    expect(s179.getAttribute('aria-checked')).toBe('true');
    await act(async () => { fireEvent.click(s179); });
    await waitFor(() => expect(calculate).toHaveBeenCalled(), { timeout: 2000 });
    expect(calculate.mock.calls.at(-1)![0].method).toBe('bonus');
  });

  it('shows the cost basis with commas and sends the plain number', async () => {
    await renderPage();
    await enterCost('1234567');
    expect((screen.getByLabelText('Cost basis') as HTMLInputElement).value).toBe('1,234,567');
    expect(calculate.mock.calls.at(-1)![0].assets[0].cost).toBe('1234567');
  });

  it('a new acquisition date fills the placed-in-service date until that is changed', async () => {
    await renderPage();
    const acquired = screen.getByLabelText('Date acquired') as HTMLInputElement;
    const placed = screen.getByLabelText('Placed-in-service date') as HTMLInputElement;
    fireEvent.change(acquired, { target: { value: '2026-03-15' } });
    expect(placed.value).toBe('2026-03-15');
    fireEvent.change(placed, { target: { value: '2026-04-01' } });
    fireEvent.change(acquired, { target: { value: '2026-02-01' } });
    expect(placed.value).toBe('2026-04-01');
  });

  it('a selected convention is sent with the asset; automatic sends none', async () => {
    await renderPage();
    await enterCost();
    expect(calculate.mock.calls.at(-1)![0].assets[0].convention).toBeNull();
    const convention = screen.getByLabelText('Method and convention') as HTMLSelectElement;
    expect([...convention.options].find((o) => o.value === 'MM')?.disabled).toBe(true);
    calculate.mockClear();
    fireEvent.change(convention, { target: { value: 'MQ' } });
    await waitFor(() => expect(calculate).toHaveBeenCalled(), { timeout: 2000 });
    expect(calculate.mock.calls.at(-1)![0].assets[0].convention).toBe('MQ');
  });

  it('meets accessibility basics: labelled controls, switches and live status', async () => {
    await renderPage();
    for (const field of screen.getAllByRole('textbox')) {
      const id = field.getAttribute('id');
      const labelled = (id && document.querySelector(`label[for="${id}"]`)) || field.getAttribute('aria-label');
      expect(labelled, `unlabelled input ${field.outerHTML}`).toBeTruthy();
    }
    for (const select of screen.getAllByRole('combobox')) {
      const id = select.getAttribute('id');
      expect(id && document.querySelector(`label[for="${id}"]`)).toBeTruthy();
    }
    for (const toggle of screen.getAllByRole('switch')) {
      expect(toggle.getAttribute('aria-label')).toBeTruthy();
      expect(['true', 'false']).toContain(toggle.getAttribute('aria-checked'));
    }
    expect(screen.getByRole('status')).toBeTruthy();
  });

  it('orders the inputs: jurisdiction and year, asset details, elections - and the tax year is the shared one', async () => {
    const { container } = await renderPage();
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(headings.slice(0, 4)).toEqual(['Jurisdiction and tax year', 'Asset details', 'Elections', 'Limits and tax rates']);
    expect((screen.getByLabelText('Tax year') as HTMLSelectElement).value).toBe('2026');
    fireEvent.change(screen.getByLabelText('Tax year'), { target: { value: '2025' } });
    expect(sessionStorage.getItem('taxscraper_tax_year')).toBe('2025');
    // No reassurance banner on an empty form; one status indicator only.
    expect(screen.queryByText('All inputs look good')).toBeNull();
    expect(screen.getAllByRole('status')).toHaveLength(1);
    expect(await axeViolations(container)).toEqual([]);
  });

  it('switches to the import flow and keeps it when switching back', async () => {
    await renderPage();
    expect(screen.getByRole('tab', { name: /Single asset/ }).getAttribute('aria-selected')).toBe('true');
    fireEvent.click(screen.getByRole('tab', { name: /Import an asset list/ }));
    const panel = screen.getByRole('tabpanel', { name: /Import an asset list/ });
    expect(within(panel).getByText(/Choose the jurisdiction and tax year first/)).toBeTruthy();
    fireEvent.change(within(panel).getByLabelText('Jurisdiction'), { target: { value: 'CA' } });
    fireEvent.click(screen.getByRole('tab', { name: /Single asset/ }));
    fireEvent.click(screen.getByRole('tab', { name: /Import an asset list/ }));
    expect((within(panel).getByLabelText('Jurisdiction') as HTMLSelectElement).value).toBe('CA');
  });

  it('the export menu opens on its first item and closes with Escape', async () => {
    await renderPage();
    await enterCost();
    const exportButton = await screen.findByRole('button', { name: /Export/ });
    await waitFor(() => expect(exportButton).toHaveProperty('disabled', false));
    fireEvent.click(exportButton);
    const items = screen.getAllByRole('menuitem');
    expect(document.activeElement).toBe(items[0]);
    fireEvent.keyDown(document, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(items[1]);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
    expect(document.activeElement).toBe(exportButton);
  });
});
