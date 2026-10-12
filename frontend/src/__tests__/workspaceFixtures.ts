/**
 * Fixtures for the dashboard / forms / updates / state pages, built from the
 * same reference-data files the server serves, so a component test exercises
 * the real rules rather than a hand-written copy of them.
 */

import axe from 'axe-core';
import { vi } from 'vitest';

import holidayFile from '../../../backend/app/reference_data/calendar/legal_holidays.json';
import dueFile from '../../../backend/app/reference_data/calendar/federal_due_dates.json';
import quickLinks from '../../../backend/app/reference_data/dashboard/quick_links.json';
import motivation from '../../../backend/app/reference_data/dashboard/motivation.json';
import federalForms from '../../../backend/app/reference_data/forms/federal_forms.json';
import stateForms from '../../../backend/app/reference_data/forms/state_forms.json';
import caFile from '../../../backend/app/reference_data/state_intel/states/CA.json';
import type {
  CalendarRules, DashboardConfig, FormsLibrary, NewsFeed, StateIntelListing, StateIntelProfile,
} from '../api/client';

export const calendarRules = { holidays: holidayFile, due_dates: dueFile } as unknown as CalendarRules;

export const dashboardConfig = {
  quick_links: quickLinks.links, motivation, default_tax_year: 2026, supported_years: [2025, 2026],
} as unknown as DashboardConfig;

const STATES: [string, string][] = [['CA', 'California'], ['NY', 'New York'], ['TX', 'Texas'], ['WY', 'Wyoming']];

export const formsLibrary = {
  version: federalForms.version,
  categories: federalForms.categories,
  forms: federalForms.forms,
  state_forms: stateForms.forms,
  states_with_forms: [...new Set(stateForms.forms.map((f) => f.state))].sort(),
  state_agencies: Object.fromEntries(STATES.map(([code, name]) => [code, {
    name, agency: `${name} revenue agency`, agency_url: `https://revenue.${code.toLowerCase()}.example.gov/`,
  }])),
  supported_years: [2025, 2026],
} as unknown as FormsLibrary;

export const stateListing: StateIntelListing = {
  supported_years: [2025, 2026],
  states: STATES.map(([code, name]) => ({ code, name, coverage: {} })),
  disclaimer: 'General information only, not tax advice.',
};

function caSections(year: number) {
  const pick = (key: string, label: string) => {
    const fields = (caFile.sections as Record<string, { fields: { years: number[] }[] }>)[key].fields
      .filter((f) => f.years.includes(year)) as unknown as StateIntelProfile['sections'][number]['fields'];
    return {
      key, label, status: fields.length ? 'verified' : 'not_verified',
      message: fields.length ? '' : `Not yet verified for ${year}. Check the agency directly.`,
      as_of: fields.length ? '2026-10-07' : null, fields,
      agency: { name: 'California Franchise Tax Board', url: 'https://www.ftb.ca.gov/' },
    };
  };
  return [
    pick('apportionment', 'Apportionment'),
    pick('nexus', 'Nexus'),
    {
      key: 'conformity', label: 'Federal Conformity', status: 'verified', message: '', as_of: '2026-10-05',
      shared_with: 'depreciation_calculator',
      agency: { name: 'California Franchise Tax Board', url: 'https://www.ftb.ca.gov/' },
      fields: [{ key: 'type', label: 'Conformity type', value: 'Fixed-date (static) conformity',
        source_url: 'https://leginfo.legislature.ca.gov/', source_citation: 'R&TC 17024.5', last_verified: '2026-10-05' }],
    },
    pick('rates', 'Tax Rates'),
    pick('filing', 'Filing Requirements'),
  ] as StateIntelProfile['sections'];
}

export function stateProfile(code: string, year: number): StateIntelProfile {
  if (code === 'CA') {
    return {
      code: 'CA', name: 'California', tax_year: year, supported_years: [2025, 2026],
      agency: { name: 'California Franchise Tax Board', url: 'https://www.ftb.ca.gov/' },
      quick_facts: ['Community property state'], sections: caSections(year),
      due_rules: caFile.sections.filing.due_rules as unknown as StateIntelProfile['due_rules'],
      disclaimer: 'General information only, not tax advice.',
    };
  }
  const name = STATES.find(([c]) => c === code)?.[1] ?? code;
  const agency = { name: `${name} revenue agency`, url: `https://revenue.${code.toLowerCase()}.example.gov/` };
  return {
    code, name, tax_year: year, supported_years: [2025, 2026], agency, quick_facts: [],
    sections: ['apportionment', 'nexus', 'conformity', 'rates', 'filing'].map((key) => ({
      key, label: key, status: 'not_verified', message: `Not yet verified for ${year}. Check the agency directly.`,
      as_of: null, fields: [], agency,
    })) as StateIntelProfile['sections'],
    due_rules: null, disclaimer: 'General information only, not tax advice.',
  };
}

export const newsFeed: NewsFeed = {
  items: [
    { id: 'a1', source: 'treasury', source_name: 'U.S. Treasury', title: 'Treasury proposes regulations',
      url: 'https://home.treasury.gov/news/press-releases/sb0651/', published: '2026-10-06',
      excerpt: 'Proposed rule.', topics: ['legislation_regulation'], reference: '' },
  ],
  sources: [
    { key: 'irs', name: 'IRS', kind: 'public', homepage: 'https://www.irs.gov/newsroom', state: 'error',
      message: 'This source could not be reached; showing the last items fetched, if any.', last_updated: null, item_count: 0 },
    { key: 'treasury', name: 'U.S. Treasury', kind: 'public', homepage: 'https://home.treasury.gov/', state: 'ok',
      message: '', last_updated: '2026-10-07T12:00:00+00:00', item_count: 1 },
    { key: 'bloomberg_tax', name: 'Bloomberg Tax', kind: 'licensed', homepage: 'https://pro.bloombergtax.com/',
      state: 'not_connected', message: 'Connect your Bloomberg Tax account to enable', last_updated: null, item_count: 0 },
    { key: 'thomson_reuters', name: 'Thomson Reuters', kind: 'licensed', homepage: 'https://tax.thomsonreuters.com/',
      state: 'not_connected', message: 'Connect your Thomson Reuters account to enable', last_updated: null, item_count: 0 },
  ],
  topics: [{ key: 'legislation_regulation', label: 'Legislation and regulation' }],
  last_updated: '2026-10-07T12:00:00+00:00',
};

/** A fixed instant: mid-afternoon UTC on 2026-10-07, which is October 7 from UTC-12 to UTC+8. */
export const NOW = new Date(Date.UTC(2026, 9, 7, 15, 0));

export function freezeTime(): void {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
}

/**
 * axe-core accessibility check. Colour contrast is off because jsdom does not
 * lay out or paint; contrast is covered by the token pairs in styles.css and
 * the Playwright run in a real browser.
 */
export async function axeViolations(container: Element): Promise<string[]> {
  const result = await axe.run(container, {
    rules: { 'color-contrast': { enabled: false }, region: { enabled: false } },
  });
  return result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`);
}
