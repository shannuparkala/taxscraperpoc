/**
 * End-to-end tests for the main flows, in a real browser.
 *
 *   cd frontend && npx playwright test
 *
 * Starts its own backend (port 8001, a throwaway SQLite file, auth off, Gemini
 * off, the news feed off so nothing reaches the network) and a Vite server
 * (port 5174) proxying to it, so it never touches the developer's database or
 * a running dev server. Uses the installed Microsoft Edge (or Chrome with
 * E2E_BROWSER=chrome), so no browser download is needed.
 */

import { defineConfig } from '@playwright/test';
import path from 'node:path';
import os from 'node:os';

const python = JSON.stringify(path.resolve(process.cwd(), '..', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'));
const dbFile = path.join(os.tmpdir(), `taxscraper-e2e-${process.pid}.db`).replace(/\\/g, '/');

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:5174',
    channel: process.env.E2E_BROWSER === 'chrome' ? 'chrome' : 'msedge',
    timezoneId: 'America/New_York',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --host 127.0.0.1 --port 8001`,
      cwd: '../backend',
      url: 'http://127.0.0.1:8001/api/health',
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        DATABASE_URL: `sqlite:///${dbFile}`,
        AUTH_DISABLED: 'true',
        GEMINI_ENABLED: 'false',
        GEMINI_API_KEY: '',
        NEWS_ENABLED: 'false',
        STATE_UPDATES_ENABLED: 'false',
        RATE_LIMIT_ENABLED: 'false',
        DAILY_QUOTA_ENABLED: 'false',
      },
    },
    {
      command: 'npx vite --host 127.0.0.1 --port 5174 --strictPort',
      url: 'http://127.0.0.1:5174',
      reuseExistingServer: false,
      timeout: 120_000,
      env: { API_PROXY_TARGET: 'http://127.0.0.1:8001' },
    },
  ],
});
