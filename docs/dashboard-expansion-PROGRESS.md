# Dashboard / Forms / Updates / State Intelligence — progress log

Persisted incrementally so an interrupted run can resume.

Started 2026-10-07 on branch `assistant-rebuild-gemini-grounded`.

## Decisions
- "Federal confirmation" → built as **Federal Conformity**; reads
  `backend/app/tax_rules/depreciation/state_conformity.json` directly (one source of truth).
- Date logic + deadline engine live in the frontend (`lib/dates.ts`, `lib/deadlines.ts`), pure,
  driven by rules JSON served from `backend/app/reference_data/`.
- Old workload dashboard moves `/dashboard` → `/workload`; new Dashboard is `/`.
- Client names encrypted at rest (Fernet), never logged; no SSN/bank fields exist.

## Status
- [x] reference data: holidays, filing deadlines, quick links, motivation bank (backend/app/reference_data)
- [x] forms library data + verify_forms (107 federal, 14 state; 1099-B PDF 404 at irs.gov; FTB refuses bots -> manual check)
- [x] news sources + updates service (services/news_service.py, api/routes_updates.py)
- [x] state intelligence data + refresh_state_intel (services/state_intel_service.py, scripts/refresh_state_intel.py)
- [x] backend clients/custom deadlines CRUD (api/routes_clients.py, api/routes_reference.py); backend tests green
- [x] frontend context, pages, tests (75 vitest incl. axe; 11 Playwright e2e in Edge)
- [x] README, CLAUDE.md, CI (frontend + e2e jobs, weekly forms-links workflow)

## State intel verified (2026-10-07)
CA (all four sections), IL (nexus, rates, filing), TX (nexus, franchise, filing), FL (nexus, rates, corp filing),
WA (nexus, B&O), NY (PTET only - tax.ny.gov PDFs/pages hard to extract). Other 45: empty -> "Not yet verified".
Unreachable from this host: floridarevenue.com via curl (used WebFetch), ilga.gov, govdelivery.
Feeds: IRS has no confirmable RSS -> parse https://www.irs.gov/newsroom/news-releases-for-current-month (+ prior month page);
Treasury -> https://home.treasury.gov/news-data/widgets/latest.json (its own press-release widget data; robots allows /).

Done 2026-10-07. Full backend suite green; frontend typecheck + build green.

## Round 2 (2026-10-08) - user feedback
1. State map section removed (/map redirects to /states; quick link removed).
2. State Intelligence for all states: scripts/research_state_intel.py (research notes -> structured fields ->
   accepted only if figures + evidence phrases are found on the state's own page). Full run in progress:
   8 processes, run dir docs/tax-research/state-intel-proposals/2026-10-08/ (resumable with --resume,
   per-process DATABASE_URL in scratchpad rdb/rN.db). Apply with:
   `python -m scripts.research_state_intel --apply --run 2026-10-08`.
   Conformity: unverified-but-researched entries now shown as "provisional".
3. "Prepare a return" -> disabled "Coming soon" nav entry; /prepare shows a Coming soon card.
4. Countdown = standard dates + user's own deadlines, nearest first (lib/deadlines.prioritizedCountdown).

## Round 2 status after power cut (2026-10-08)
- Acceptance rule tightened (>=2 evidence phrases; key figure must sit in the page sentence shown).
  `--reverify --run 2026-10-08` re-checks stored proposals with no model calls (41 states done, rest resumed).
- Bot-blocked states verified in the browser with the same rule (scratchpad browser_results/{MA,MI,NH,KS}.json,
  merged via scratchpad merge_browser.py AFTER reverify). IN, LA, MO, UT unreachable (connection refused /
  Cloudflare block or challenge) - left "Not yet verified".
- Reruns: rerun-apportionment (OK), rerun-filing (PA, VT), rerun3-apportionment (DE), rerun3-rates (MT).
- Next: apply main run, then reruns; then a fill pass for empty sections; then tests + e2e.

## Round 2 status (2026-10-09)
- Date rule added: every month-day date in a value must be on the matched page (Colorado's
  "C corporation ... May 15" had passed on an individual-only page). Percentages count as key figures.
- Reverify under the date rule done for the main run (IA re-done separately - it was missing from the
  process groups) and reruns. Fill pass (fill-<ST>-5x run dirs) done and reverified.
- Apply order: 2026-10-08, rerun-apportionment, rerun-filing, rerun3-apportionment, rerun3-rates, fill-*.
  merge_browser.py must run after any reverify of 2026-10-08 (reverify resets browser acceptances).
- Applied (2026-10-09): all runs above + fill2-{DC,MS,MT,OR}. 2025: 36 of 51 complete (188 verified sections), 2026: 26 complete; DE filing returned no research notes three times;
  IN/LA/MO/UT unreadable (bot block), AZ/HI/RI/KS gaps are Cloudflare checkbox challenges (not bypassed),
  OH codes.ohio.gov refused. Backend suite, vitest 79/79, Playwright 15/15 green (2 new State Intel e2e tests).
