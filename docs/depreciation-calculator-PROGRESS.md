# Depreciation calculator: status

Status as of 2026-10-07: **built and tested.** See README "Depreciation calculator" for the design and the yearly checklist, and `docs/validation.md` for the cross-checks.

## Where things are

- **Engine** (pure, Decimal): `backend/app/services/depreciation/`.
  - `engine.py`: Section 179, then bonus or §168(n), then the mid-quarter test, MACRS and §280F.
  - `state.py`: state regimes, and addback with later recovery.
  - `tape.py`: the calculation tape and the "why" for each row.
  - `service.py`: the full result.
  - `exports.py`: CSV and PDF.
  - `explanation.py`: the grounded explanation, checked so it introduces no number of its own.
- **Rule data:** `backend/app/tax_rules/depreciation/*.json`, generated or edited only through `backend/scripts/build_depreciation_rules.py`.
- **State research:** the cited rows in `docs/tax-research/state-depreciation-conformity-batch1..9.json` and `.md`. All 51 jurisdictions are researched for 2021–2026.
- **API:** `backend/app/api/routes_depreciation.py` (`/api/depreciation/{rules,calculate,export/csv,export/pdf,explain}`).
- **UI:** `frontend/src/pages/DepreciationPage.tsx`, `frontend/src/components/depreciation/`, `frontend/src/styles/depreciation.css`.
- **Rule refresh:** `backend/scripts/refresh_rules.py`. It writes proposals to `docs/tax-research/rule-proposals/` and never edits rule data.
- **Tests:**
  - Backend, 352: `backend/tests/test_depreciation_*.py`.
  - Frontend, 15: `frontend/src/__tests__/`, run with `npm test`.

## State data quality (306 jurisdiction-years)

| Status | Count | What it means |
|---|---|---|
| verified | 80 | Read in the state's own statute, form or guidance |
| no_income_tax | 54 | No individual income tax: AK, FL, NH, NV, SD, TN, TX, WA, WY |
| unverified | 172 | Researched; the rule rests on agency search excerpts or summaries because the agency site or PDF could not be read |

Unverified rows show "State rules not yet verified for this year" next to the federal result. The user can open a provisional estimate built from that state's own researched rule. The reason for each row is in its `verify_note` field and in the batch notes.

**Fully verified, all six years:** DC, DE, MN.

**Partly verified:** AZ, CA, LA, MD, ME, MS, MT, NC, ND, OK, OR, PA, SC, VA, VT, WI, WV.

**No year verified:** AL, AR, CO, CT, GA, HI, IA, ID, IL, IN, KS, KY, MA, MI, MO, NE, NJ, NM, NY, OH, RI, UT.

## Known gaps to close next

- **Unverified state rows.** Raise them to verified by reading each state's primary source. The research notes list the exact documents that were blocked.
- **Federal entries marked `verified: false`:**
  - the Rev. Proc. 2019-13 safe-harbor mechanics;
  - the clean-vehicle-credit basis rule;
  - the recapture note.
- **Not modelled:**
  - short tax years;
  - dispositions and recapture amounts;
  - changes in business use after year 1;
  - ADS elections other than listed property;
  - Ohio's 2/3 and 6/6 addback variants;
  - entity-level state taxes (franchise, B&O, BPT);
  - married-filing-separately Section 179 allocation.
