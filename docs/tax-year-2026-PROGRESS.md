# Tax year 2026, depreciation import rework, bonus toggle - progress log

Persisted incrementally so an interrupted run can resume. Branch
`tax-year-2026-depreciation`, cut 2026-10-11 from `assistant-streaming-quality`
after the owner's restyle was committed as `68a51dc`.

## Owner decisions (2026-10-11)

1. One default tax year, `DEFAULT_TAX_YEAR` = 2026, clamped per product.
2. Multi-asset report: a Federal group (Sec 179 | Bonus | MACRS | Total) and,
   when a state is chosen, a State group computed under that state's regime.
   The elections are made per asset on the federal return. Template columns
   A-E stay as they are.
3. 2026 state depreciation conformity (37 unverified states) is a follow-up
   branch, not this one.
4. The 1040/workpaper engine for 2026 is out of scope; its fallback clamps to
   2025 and raises a "Tax year assumed" review item.
5. Assistant arithmetic check: on failure, regenerate once, then show the fallback.

## Commits

- [x] 1 `c058c5e` default year: one setting, clamped, assistant year resolution + declared fallback
- [x] 2 report logic: 179 -> bonus -> MACRS per jurisdiction, per-asset bonus election, lives after jurisdiction/year
- [x] 3 UI restructure and guided import stepper
- [x] 4 bonus toggle in the report (select-all, class-wide election out, export)
- [x] 5 assistant arithmetic check, rate-question policy, citation rendering fixes

## Verified 2026 figures (already in `federal_rules.json`, re-checked 2026-10-11)

- Sec 179: $2,560,000 limit, phase-out from $4,090,000, SUV cap $32,000 (Rev. Proc. 2025-32 sec. 4.24)
- Bonus: 100% for property acquired after Jan 19, 2025 (Notice 2026-11); 20% for earlier acquisitions placed in service in 2026
- Sec 280F 2026: $20,300 / $19,800 / $11,900 / $7,160; $12,300 first year without bonus (Rev. Proc. 2026-15)
- Maine 2026 (assistant case): standard deduction $15,700 single (revised May 20, 2026 from $15,300), exemption $5,300, brackets 5.8% / 6.75% from $27,400 / 7.15% from $64,850

## Unverified, left flagged

- 37 states without a verified 2026 conformity entry (`state_conformity.json`)
- `luxury_auto_100pct_safe_harbor`, `clean_vehicle_credit_basis`, `recapture_note`, 2026 Form 4562 layout (all `verified: false` already)

## Notes

- ESLint has no `eslint.config.*` (ESLint 10 installed), so `npm run lint` fails before this branch too; typecheck + vitest + Playwright are the frontend gates.
- ruff/mypy have pre-existing findings; each commit is checked to add none in the files it touches.

## Commit 2 findings

- Worked examples confirmed against the engine (tests in `test_depreciation_additions.py`
  and `test_depreciation_engine.py`). One correction to the plan: CA 2026 MACRS on 75,000 is
  10,718 (the engine rounds to whole dollars), so the CA total is 35,718, not 35,717.50.
- The engine rounds basis to whole dollars, so a cost with cents (12,000.50) gets 12,001 of
  Section 179. The workbook writes formulas only when the cost is whole dollars; otherwise the
  engine's amounts as values, so screen and file never disagree.
- The import endpoint now requires `tax_year`; `POST /additions/lives` re-decides lives for a
  new year or jurisdiction without a re-upload.

## Commit 3 findings

- The import tab panel's `display: flex` beat the `hidden` attribute, so both modes showed at once;
  `.dw [hidden] { display: none !important }` fixes the class of bug for the page.
- Screen-reader-only labels inside a horizontally scrolled table escaped the scroll box (no
  containing block) and widened the phone layout to 563px; `.dw-table-wrap { position: relative }`.
- The report request was rebuilt on every render, so each render restarted the debounce and dropped
  the pending result; memoized and keyed on the request's content.
- The engine's "no taxable business income" warning fired on every import (an asset list has no
  income); the report drops it via the shared `NO_INCOME_LIMIT_WARNING` and the screen states it once.

## Commit 4 findings

- Excel recalculation (pywin32, CalculateFullRebuild) of a synthetic CA report with mixed elections:
  no formula errors, every federal and state cell equal to the screen to the cent.
- Hiding the table rows while recomputing made the election boxes disappear after every click;
  rows and controls now stay, only the figures blank until the new report arrives.
- A select-all component defined inside the render function remounted on every render (focus lost);
  moved to module level.

## Live eval after commit 5 (2026-10-11, label `tax-year-2026`): 46/52 (was 50/51)

- me-rate-75k-2026 FAILED: full schedule now listed, but still the superseded $15,300 deduction, and the
  headline ($3,436.35) disagreed with the last step ($3,411.70). The check missed it (no "Total" line);
  fixed afterwards to fall back to the last step's result. The stale revision is NOT fixed - next idea:
  a state search start "<state> <year> individual income tax rate schedule revised" for rate questions.
- 4 length-budget failures (wa-capital-gains, tx-sales-nexus, edge-no-state-state-dependent,
  edge-mask-ssn): the router classed them how_to (were fact/clarify); possibly the router_system edit,
  possibly variance - re-run those cases to tell.
- 3 drafts withdrawn (nh-interest-dividends, edge-names-other-state, edge-federal-question-with-state);
  the eval does not record why - re-ask and read the replace event (suspect wrong_tax_year).
