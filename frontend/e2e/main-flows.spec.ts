/**
 * Main flows, end to end: greeting and countdown, add a client and see the
 * deadline, download a form, click a state and open State Intelligence, the
 * responsive dashboard order, and axe (including colour contrast, which jsdom
 * cannot check) on each new page.
 */

import { expect, test, type Page } from '@playwright/test';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const AXE_PATH = require.resolve('axe-core/axe.min.js');

// 2026-10-07 15:00 UTC: Wednesday morning in New York (the configured time zone).
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-10-07T15:00:00Z'));
});

async function axe(page: Page): Promise<string[]> {
  await page.addScriptTag({ path: AXE_PATH });
  return page.evaluate(async () => {
    // @ts-expect-error injected global
    const result = await window.axe.run(document.querySelector('main'), { rules: { region: { enabled: false } } });
    return result.violations.flatMap((v: { id: string; nodes: { target: string[]; any: { message: string }[] }[] }) =>
      v.nodes.map((n) => `${v.id}: ${n.target.join(' ')} - ${n.any[0]?.message ?? ''}`));
  });
}

test('dashboard greets the user and counts down to the four deadlines', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1, name: /^Good morning/ })).toBeVisible();
  const tiles = page.getByRole('listitem').filter({ hasText: /days|Due today/ }).filter({ has: page.locator('.tile-days') });
  await expect(tiles).toHaveCount(4);
  await expect(page.getByLabel(/^October 15: 8 days/)).toBeVisible();
  await expect(page.getByLabel(/^March 15: 159 days/)).toBeVisible();
  await expect(page.locator('.greet-date')).toHaveText('Wednesday, October 7, 2026');
  expect(await axe(page)).toEqual([]);
});

test('add a client and see the deadline appear', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Add client' }).click();
  await page.getByLabel('Client name').fill('E2E Invented Client');
  await page.getByLabel('Entity type').selectOption('individual');
  await page.getByLabel('Add a state').selectOption('CA');
  await page.getByLabel('Extension (current return)').selectOption('extended');
  await page.getByRole('button', { name: 'Save client' }).click();
  await expect(page.getByText('E2E Invented Client', { exact: true }).first()).toBeVisible();

  // Extended 2025 return: federal and California both due Thursday October 15, 2026.
  const cell = page.getByRole('gridcell', { name: /October 15, 2026: 2 deadlines/ });
  await expect(cell).toBeVisible();
  await cell.click();
  await expect(page.getByText(/E2E Invented Client: Form 1040 extended due date/)).toBeVisible();
  await expect(page.getByText(/E2E Invented Client: CA 540 extended due date/)).toBeVisible();
  await expect(page.getByText('This week (Oct 5, 2026 – Oct 11, 2026)')).toBeVisible();
});

test('download a form from the agency', async ({ page }) => {
  await page.goto('/forms');
  await page.getByLabel('Search by form number or keyword').fill('w-9');
  const download = page.getByRole('link', { name: /Download Form W-9/ });
  await expect(download).toHaveAttribute('href', 'https://www.irs.gov/pub/irs-pdf/fw9.pdf');
  await expect(download).toHaveAttribute('target', '_blank');
  // Click it and confirm the browser heads to irs.gov (the request is stopped so no network is used).
  await page.context().route('https://www.irs.gov/**', (route) => route.fulfill({ status: 200, contentType: 'application/pdf', body: '%PDF-1.7' }));
  const [popup] = await Promise.all([page.waitForEvent('popup'), download.click()]);
  expect(popup.url()).toBe('https://www.irs.gov/pub/irs-pdf/fw9.pdf');
  expect(await axe(page)).toEqual([]);
});

test('pick a state and open State Intelligence', async ({ page }) => {
  await page.goto('/states');
  await page.getByRole('combobox', { name: 'State', exact: true }).selectOption('CA');
  await expect(page).toHaveURL(/\/states\/CA$/);
  // Opens on the server's default year (DEFAULT_TAX_YEAR).
  await expect(page.getByText('California · 2026')).toBeVisible();
  await page.getByRole('tab', { name: 'Federal Conformity' }).click();
  await expect(page.getByText(/same table the depreciation calculator uses/)).toBeVisible();
  expect(await axe(page)).toEqual([]);

  // The selection follows into the forms library.
  await page.goto('/forms?tab=state');
  await expect(page.getByRole('combobox', { name: 'State', exact: true })).toHaveValue('CA');
  await expect(page.getByRole('link', { name: /Download Form 540/ })).toBeVisible();
});

test('researched but unconfirmed conformity is shown as provisional, with its source', async ({ page }) => {
  await page.goto('/states/NJ');
  await page.getByRole('tab', { name: 'Federal Conformity' }).click();
  await expect(page.getByText('Provisional.', { exact: true })).toBeVisible();
  await expect(page.getByText(/not yet confirmed/)).toBeVisible();
});

test('an auto-checked fact shows the state page text it was matched against', async ({ page }) => {
  await page.goto('/states/TX');
  // These facts were verified for 2025; the page opens on 2026.
  await page.getByLabel('Tax year').selectOption('2025');
  await expect(page.getByText('5 of 5 topics verified for 2025')).toBeVisible();
  const field = page.locator('tr', { has: page.getByText('Auto-checked') }).first();
  await expect(field.getByRole('link')).toHaveAttribute('href', /comptroller\.texas\.gov/);
  await field.getByText('What the page says').click();
  await expect(field.locator('.si-quote blockquote')).toHaveText(/.{40,}/);
  expect(await axe(page)).toEqual([]);
});

test('a state whose agency could not be read says so instead of showing anything', async ({ page }) => {
  await page.goto('/states/IN');
  await page.getByLabel('Tax year').selectOption('2025');
  await expect(page.getByText('0 of 5 topics verified for 2025')).toBeVisible();
  await expect(page.getByText('Not yet verified', { exact: true })).toBeVisible();
});

test('the state map is gone and return preparation is disabled', async ({ page }) => {
  await page.goto('/map');
  await expect(page).toHaveURL(/\/states$/);
  const nav = page.getByRole('navigation').first();
  await expect(nav.getByRole('link', { name: /State map/ })).toHaveCount(0);
  await expect(nav.getByRole('link', { name: /Prepare a return|Coming soon/ })).toHaveCount(0);
  await expect(nav.locator('[aria-disabled="true"]')).toHaveText('Coming soon');
});

test('a deadline added on the calendar that is sooner leads the countdown', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('textbox', { name: 'Deadline or task' }).fill('E2E file 1099s');
  await page.getByLabel('Date', { exact: true }).fill('2026-10-12');
  await page.getByRole('button', { name: 'Add to calendar' }).click();
  const first = page.locator('.cd-tile').first();
  await expect(first).toContainText('E2E file 1099s');
  await expect(first).toContainText('5');
  // The standard October 15 date is still there, after it (an earlier test's client may share that day,
  // and a client's own deadline goes before the generic date on the same day).
  await expect(page.locator('.cd-tile.standard').first()).toContainText('October 15');
});

test('updates page works with the feed turned off', async ({ page }) => {
  await page.goto('/updates');
  await expect(page.getByText(/Connect your Bloomberg Tax account to enable/)).toBeVisible();
  await expect(page.getByText(/Fetching off/).first()).toBeVisible();
  expect(await axe(page)).toEqual([]);
});

test.describe('responsive dashboard', () => {
  test('mobile stacks greeting, countdowns, quick links, then calendar, without sideways scroll', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/');
    await expect(page.getByRole('grid')).toBeVisible();
    const top = async (selector: string) => (await page.locator(selector).boundingBox())!.y;
    const order = [await top('.dash-greet'), await top('.dash-tiles'), await top('.dash-links'), await top('.dash-calendar')];
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    // Name what sticks out, so a failure on another platform (CI is Linux
    // Chrome) says which element to fix rather than only how far it overflows.
    const offenders = await page.evaluate(() => [...document.querySelectorAll('body *')]
      .map((el) => ({ el, r: el.getBoundingClientRect() }))
      .filter(({ r }) => r.width > 0 && r.right > window.innerWidth + 0.5)
      .slice(0, 8)
      .map(({ el, r }) => `${el.tagName.toLowerCase()}.${String(el.className).trim().replace(/\s+/g, '.')} right=${Math.round(r.right)} w=${Math.round(r.width)}`));
    expect(overflow, offenders.join('\n')).toBeLessThanOrEqual(0);
  });

  test('desktop puts the calendar beside the greeting', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/');
    await expect(page.getByRole('grid')).toBeVisible();
    const greet = (await page.locator('.dash-greet').boundingBox())!;
    const calendar = (await page.locator('.dash-calendar').boundingBox())!;
    expect(calendar.x).toBeGreaterThan(greet.x + greet.width - 1);
    expect(Math.abs(calendar.y - greet.y)).toBeLessThan(40);
  });
});

test('new pages pass axe in dark mode too', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  for (const path of ['/', '/forms', '/updates', '/states/CA', '/states/NJ', '/depreciation']) {
    await page.goto(path);
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('main .spinner')).toHaveCount(0);
    expect(await axe(page), path).toEqual([]);
  }
});

// Dark is the default, so the light theme needs its own contrast pass.
test('pages pass axe in light mode, the non-default theme', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('taxscraper_theme', 'light'));
  for (const path of ['/', '/forms', '/updates', '/states/CA', '/states/NJ', '/depreciation']) {
    await page.goto(path);
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('main .spinner')).toHaveCount(0);
    expect(await axe(page), path).toEqual([]);
  }
});

// Invented assets only. The file has lives, so no model is asked (Gemini is off here).
const ASSET_LIST = [
  'Asset #,Asset Desription,Date Acquired,Cost,Life',
  '101,Laptops,03/02/2026,7500,5',
  '103,CNC milling machine,03/15/2026,100000,7',
  '105,Warehouse building,01/10/2026,390000,39',
  '107,Old forklift,11/04/2025,30000,7',
].join('\n');

for (const scheme of ['dark', 'light'] as const) {
  test(`the guided import: year and jurisdiction first, then upload, lives and report (${scheme})`, async ({ page }) => {
    if (scheme === 'light') await page.addInitScript(() => localStorage.setItem('taxscraper_theme', 'light'));
    await page.goto('/depreciation');
    await page.getByRole('tab', { name: /Import an asset list/ }).click();
    const panel = page.getByRole('tabpanel', { name: /Import an asset list/ });
    await expect(panel.getByText(/Choose the jurisdiction and tax year first/)).toBeVisible();
    await expect(panel.locator('input[type=file]')).toHaveCount(0);
    await expect(panel.getByLabel('Tax year')).toHaveValue('2026');
    await panel.getByLabel('Jurisdiction').selectOption('CA');
    await panel.getByRole('button', { name: 'Continue' }).click();
    await panel.locator('input[type=file]').setInputFiles({ name: 'additions.csv', mimeType: 'text/csv', buffer: Buffer.from(ASSET_LIST) });
    await expect(panel.getByText(/Old forklift|asset 107/).first()).toBeVisible();
    await expect(panel.getByText(/Date Acquired - acquired in 2025, not a 2026 addition/)).toBeVisible();
    await panel.getByRole('button', { name: /Show the report/ }).click();
    const report = panel.locator('table.dw-report');
    await expect(report.locator('tfoot')).toContainText('Total (3 assets)');
    await expect(panel.getByText(/California does not allow federal bonus/)).toBeVisible();
    expect(await axe(page)).toEqual([]);

    // Bonus and 179 off for the machine: recomputed live, the class-wide election out said once.
    const machine = report.locator('tbody tr', { hasText: 'CNC milling machine' });
    await machine.getByRole('checkbox', { name: /Sec 179 for 103/ }).uncheck();
    await machine.getByRole('checkbox', { name: /Bonus for 103/ }).uncheck();
    await expect(panel.getByText(/Bonus is elected out for all 7-year property/)).toBeVisible();
    await expect(machine.locator('td.dw-fed.dw-total')).toHaveText('$14,290.00');

    await page.setViewportSize({ width: 375, height: 812 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
}

test('reduced motion turns transitions off', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/forms');
  const duration = await page.locator('.ws-link-btn').first().evaluate((el) => getComputedStyle(el).transitionDuration);
  expect(parseFloat(duration)).toBeLessThan(0.001);
});

test('calendar is keyboard navigable', async ({ page }) => {
  await page.goto('/');
  const today = page.getByRole('gridcell', { name: /October 7, 2026, today/ });
  await today.focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('gridcell', { name: /October 8, 2026/ })).toBeFocused();
  await page.keyboard.press('ArrowDown');
  await expect(page.getByRole('gridcell', { name: /October 15, 2026/ })).toBeFocused();
  await expect(page.getByRole('heading', { name: 'Thursday, October 15, 2026' })).toBeVisible();
});
