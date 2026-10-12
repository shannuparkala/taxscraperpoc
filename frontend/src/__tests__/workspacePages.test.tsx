/**
 * Component tests for the dashboard, forms library, Industry Updates and
 * State Intelligence, with the API mocked. Each page is also run through axe.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import type { WorkspaceClient } from '../api/client';
import {
  axeViolations, calendarRules, dashboardConfig, formsLibrary, freezeTime, newsFeed, stateListing, stateProfile,
} from './workspaceFixtures';

const clients: WorkspaceClient[] = [];

vi.mock('../api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api/client')>();
  return {
    ...original,
    api: {
      reference: {
        calendar: vi.fn(async () => calendarRules),
        dashboard: vi.fn(async () => dashboardConfig),
        forms: vi.fn(async () => formsLibrary),
        states: vi.fn(async () => stateListing),
        state: vi.fn(async (code: string, year: number) => stateProfile(code, year)),
      },
      workspace: {
        clients: vi.fn(async () => [...clients]),
        createClient: vi.fn(async (body: Omit<WorkspaceClient, 'id'>) => {
          const row = { ...body, id: `c${clients.length + 1}` } as WorkspaceClient;
          clients.push(row);
          return row;
        }),
        updateClient: vi.fn(),
        deleteClient: vi.fn(),
        deadlines: vi.fn(async () => []),
        createDeadline: vi.fn(),
        updateDeadline: vi.fn(),
        deleteDeadline: vi.fn(),
      },
      updates: {
        feed: vi.fn(async () => newsFeed),
        bookmarks: vi.fn(async () => []),
        bookmark: vi.fn(),
        removeBookmark: vi.fn(),
        refresh: vi.fn(),
        summary: vi.fn(),
      },
      chat: { states: vi.fn(async () => []) },
    },
  };
});

const { api } = await import('../api/client');
const { TaxContextProvider } = await import('../context/TaxContext');
const { default: HomeDashboardPage } = await import('../pages/HomeDashboardPage');
const { default: FormsPage, filterForms, downloadFor } = await import('../pages/FormsPage');
const { default: UpdatesPage } = await import('../pages/UpdatesPage');
const { default: StateIntelPage } = await import('../pages/StateIntelPage');

const principal = { user_id: 'u1', username: 'associate', role: 'preparer', first_name: 'Avery' };

function renderAt(path: string, element: JSX.Element, routePath = '*') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <TaxContextProvider>
        <Routes><Route path={routePath} element={element} /></Routes>
      </TaxContextProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  freezeTime();
  clients.length = 0;
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

// ------------------------------------------------------------------- dashboard

describe('dashboard', () => {
  it('greets by first name and shows four countdown tiles, tools and the calendar', async () => {
    const { container } = renderAt('/', <HomeDashboardPage principal={principal} />);
    expect(await screen.findByRole('heading', { level: 1, name: /, Avery$/ })).toBeTruthy();
    const tiles = await screen.findAllByRole('listitem', { name: /days|Due today/ });
    expect(tiles.map((t) => t.getAttribute('aria-label')?.split(':')[0])).toEqual(
      ['October 15', 'March 15', 'April 15', 'September 15'], // nearest first
    );
    expect(screen.getByRole('navigation', { name: 'Quick links' })).toBeTruthy();
    expect(await screen.findByRole('grid', { name: 'October 2026' })).toBeTruthy();
    expect(screen.getByText(/exact obligation depends on the entity type/)).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it('keeps working when the news source fails', async () => {
    vi.mocked(api.updates.feed).mockRejectedValueOnce(new Error('feed down'));
    renderAt('/', <HomeDashboardPage principal={principal} />);
    expect(await screen.findByText(/feed down/)).toBeTruthy();
    expect(await screen.findByRole('grid', { name: 'October 2026' })).toBeTruthy();
    expect(screen.getAllByRole('listitem', { name: /days|Due today/ })).toHaveLength(4);
  });

  it('adds a client and shows their deadline on the calendar', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderAt('/', <HomeDashboardPage principal={principal} />);
    await user.click(await screen.findByRole('button', { name: 'Add client' }));
    await user.type(screen.getByLabelText('Client name'), 'Invented Test LLC');
    await user.selectOptions(screen.getByLabelText('Entity type'), 'individual');
    await user.selectOptions(screen.getByLabelText('Extension (current return)'), 'extended');
    await user.click(screen.getByRole('button', { name: 'Save client' }));

    expect((await screen.findAllByText('Invented Test LLC')).length).toBeGreaterThan(0);
    // Extended individual return for 2025: due Thursday October 15, 2026.
    const cell = await screen.findByRole('gridcell', { name: /October 15, 2026: 1 deadline/ });
    await user.click(cell);
    expect(await screen.findByText(/Invented Test LLC: Form 1040 extended due date/)).toBeTruthy();
    expect(screen.getAllByText(/Due within 7 days|Upcoming/).length).toBeGreaterThan(0);
  });
});

// ----------------------------------------------------------------------- forms

describe('forms library', () => {
  it('searches by number ignoring punctuation and by keyword', () => {
    const byNumber = filterForms(formsLibrary, { tab: 'all', query: '1120s', category: '', state: null });
    expect(byNumber.map((f) => f.form_number)).toContain('1120-S');
    const byWord = filterForms(formsLibrary, { tab: 'all', query: 'depreciation', category: '', state: null });
    expect(byWord.map((f) => f.form_number)).toContain('4562');
    const payroll = filterForms(formsLibrary, { tab: 'business', query: '', category: 'payroll', state: null });
    expect(payroll.length).toBeGreaterThan(3);
    expect(payroll.every((f) => f.category === 'payroll' && f.audience === 'business')).toBe(true);
  });

  it('state tab changes with the selected state', () => {
    const ca = filterForms(formsLibrary, { tab: 'state', query: '', category: '', state: 'CA' });
    expect(ca.length).toBeGreaterThan(0);
    expect(ca.every((f) => f.state === 'CA')).toBe(true);
    const tx = filterForms(formsLibrary, { tab: 'state', query: '', category: '', state: 'TX' });
    expect(tx.every((f) => f.state === 'TX')).toBe(true);
    expect(filterForms(formsLibrary, { tab: 'state', query: '', category: '', state: 'WY' })).toEqual([]);
  });

  it('links an earlier tax year to the IRS prior-year PDF', () => {
    const f1040 = formsLibrary.forms.find((f) => f.form_number === '1040')!;
    const revision = Number(f1040.latest_revision);
    expect(downloadFor(f1040, revision).url).toBe('https://www.irs.gov/pub/irs-pdf/f1040.pdf');
    expect(downloadFor(f1040, revision - 1).url).toBe(`https://www.irs.gov/pub/irs-prior/f1040--${revision - 1}.pdf`);
    expect(downloadFor(f1040, revision + 1).note).toMatch(/not published yet/);
  });

  it('shows the unverified-state fallback and agency link', async () => {
    const { container } = renderAt('/forms?tab=state&state=WY', <FormsPage />);
    expect(await screen.findByText('Forms not yet verified for this state')).toBeTruthy();
    const link = screen.getByRole('link', { name: /Wyoming revenue agency/ });
    expect(link.getAttribute('href')).toBe('https://revenue.wy.example.gov/');
    expect(await axeViolations(container)).toEqual([]);
  });

  it('renders tiles with official download links and a chatbot link', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderAt('/forms?q=4562', <FormsPage />);
    const download = await screen.findByRole('link', { name: /Download Form 4562/ });
    expect(download.getAttribute('href')).toMatch(/^https:\/\/www\.irs\.gov\/pub\/irs-(pdf|prior)\/f4562/);
    const ask = screen.getByRole('link', { name: /Ask the chatbot about this form/ });
    expect(ask.getAttribute('href')).toMatch(/^\/assistant\?q=/);
    await user.click(screen.getByRole('tab', { name: 'State' }));
    expect(screen.getByText(/Choose a state above/)).toBeTruthy();
  });
});

// --------------------------------------------------------------------- updates

describe('industry updates', () => {
  it('shows items from working sources and says which source failed', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { container } = renderAt('/updates', <UpdatesPage />);
    expect(await screen.findByRole('link', { name: /Treasury proposes regulations/ })).toBeTruthy();
    const sources = screen.getByRole('region', { name: 'Sources' });
    expect(within(sources).getByText('Could not be reached')).toBeTruthy();
    expect(within(sources).getAllByText(/Connect your .* account to enable/)).toHaveLength(2);
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByRole('tab', { name: 'Bloomberg Tax' }));
    expect(await screen.findByText(/Bloomberg Tax: Not connected/)).toBeTruthy();
  });
});

// -------------------------------------------------------------- state intel

describe('state intelligence', () => {
  it('loads the selected state with sourced fields and a chatbot link', async () => {
    const { container } = renderAt('/states/CA', <StateIntelPage />, '/states/:code');
    expect(await screen.findByText('California · 2026')).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Apportionment', selected: true })).toBeTruthy();
    expect(screen.getByText(/Single sales factor/)).toBeTruthy();
    const ask = screen.getByRole('link', { name: /Ask the chatbot about California apportionment/ });
    expect(ask.getAttribute('href')).toContain('state=CA');
    expect(localStorage.getItem('taxscraper_assistant_state')).toBe('CA'); // shared with the assistant
    expect(await axeViolations(container)).toEqual([]);
  });

  it('says not yet verified rather than borrowing data, and compares two states', async () => {
    renderAt('/states/CA?compare=WY', <StateIntelPage />, '/states/:code');
    expect(await screen.findByText('California · 2026')).toBeTruthy();
    expect(await screen.findByText('Wyoming · 2026')).toBeTruthy();
    expect(screen.getAllByText('Not yet verified').length).toBe(1);
    expect(screen.getAllByRole('link', { name: /Wyoming revenue agency/ }).length).toBeGreaterThan(0);
  });

  it('hides a field for a year its source does not cover', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderAt('/states/CA', <StateIntelPage />, '/states/:code');
    // Opens on the server's default year (2026), whose source does not cover the field.
    await screen.findByText('California · 2026');
    await user.click(screen.getByRole('tab', { name: 'Nexus' }));
    expect(screen.queryByText(/doing-business thresholds/)).toBeNull();
    await user.selectOptions(screen.getByLabelText('Tax year'), '2025');
    await screen.findByText('California · 2025');
    expect(screen.getByText(/doing-business thresholds/)).toBeTruthy();
  });
});
