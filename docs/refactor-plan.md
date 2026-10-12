# Tax App Refactor Plan

Read one phase at a time via `/phase N`. Stop and report after each phase.

## Guiding architecture
- LLMs only: document classification, field extraction into structured JSON,
  organizer interpretation, the chatbot, and plain-English explanations.
- All tax arithmetic, thresholds, phase-outs, and form-to-form flows are deterministic code.
- Constants live in `tax_constants/<year>.json`, each with a citation. Values from
  2025 legislation (including the One Big Beautiful Bill Act) are `"verify": true`
  until confirmed against the 2025 IRS instructions.
- Money uses Decimal or integer cents; rounding follows the official forms.
- Work on branch `refactor/tax-engine-v2`.

## Phase 1 — Remove dead code
1. Run `/audit-deadcode`. Review `docs/deadcode-report.md` with me.
2. After approval, delete approved items and unused dependencies.
3. Confirm: build passes, tests pass, and a sample return's output is byte-identical to before.
4. Anything referenced dynamically stays on the "human review" list.

## Phase 2 — Deterministic tax engine
1. Input: typed `TaxpayerFacts`. Output: `ReturnResult` with every line of every form.
2. Each form line is a node in a calculation graph (see the `tax-architecture` skill).
3. Priority order (forms my eval cases use first): Form 1040; Schedules 1, 2, 3, A, B, D;
   Form 8949; Form 8889; Qualified Dividends and Capital Gain Tax Worksheet;
   IL-1040, Schedule ICR, Schedule IL-WIT. Then: Schedules C, E, SE; Forms 8995, 8812,
   2441, 8863, 8962; Schedule D Tax Worksheet; 2025 legislative provisions.
4. Use `/research-tax-rule` before each form and `/implement-form` to build it.
5. Unsupported situations raise `UnsupportedItem`; never approximate.

## Phase 3 — Provenance
1. Every node result carries a provenance record (formula, inputs, reference, sources).
2. Source facts carry document, page, field, confidence, and bounding box when available.
3. `explain(node_id)` returns the full tree to source documents.
4. UI: every figure is clickable and drills down to the source page with the field highlighted.
5. Verify with `/trace-check sample` and `/trace-check <case>`.

## Phase 4 — Calculation report
1. Line-by-line breakdown of Form 1040 and every schedule, in official form order:
   value, formula, inputs, source.
2. Full detail of every worksheet used.
3. Source-document index: what was extracted from each document and where it was used.
4. Validation section: cross-checks run, results, low-confidence extractions, unsupported flags.
5. LLM explanations may only use numbers present in provenance (enforced by a validator).
6. Export as PDF and JSON.

## Phase 5 — LLM cost meter
1. One client wrapper for all LLM calls records model, input/output/cached tokens
   (from the API's usage fields), stage, and return id.
2. Prices in a config file, not hard-coded.
3. Bottom-corner panel in the return view: total cost for this return, expandable by stage and model.
4. `/cost-report` gives per-return averages, cost per page, and savings ideas.

## Phase 6 — Benchmark harness
1. `/add-eval-case <id>` for each of my ~10 workpaper/return pairs; I verify each `expected.json`.
2. `make eval` scores extraction, calculation, and end-to-end accuracy separately,
   plus cost and latency, writing `evals/REPORT.md` and failing CI on regression.
3. Engine unit tests at every threshold and phase-out edge, for each filing status.
4. Property tests: tax never negative; more income never lowers pre-credit tax;
   refund and amount owed never both nonzero; every line has provenance.
5. Include IRS MeF ATS test scenarios for tax year 2025 Form 1040 if placed in `evals/irs_ats/`.
6. Adversarial cases: rotated pages, poor scans, duplicates, a W-2c, another person's
   document, missing pages. The expected result is a correct flag, not a guess.
7. Targets: 100% calculation accuracy, 100% of unsupported items flagged. Report
   end-to-end accuracy honestly and don't overfit to specific cases.

---

# Notes added while scaffolding the commands

Everything above this line is the plan as written. Everything below is a note
about the ground it has to land on, added 2026-09-22. `/phase N` reads only the
numbered section it was asked for; these notes are for the reader.

## Open questions, to settle before the phase that hits them

**Phase 2 / Guiding architecture - `tax_constants/<year>.json` against the
module that already does this.** `backend/app/services/tax_engine/tax_authority.py`
already holds every figure as a `Constant` with an `Authority` (citation, URL,
kind) and a `verified` flag, and `tax_tables` derives its lookup dicts from it,
so there is exactly one place a figure can come from. Its own docstring explains
why the indirection exists: 2025 needed two sources for figures that normally
come from one, and a table of bare numbers cannot express that. Moving to JSON
gives editability and loses the typed authority objects and the import-time
checking. Three options: keep the module and treat `"verify": true` as the
existing `verified=False`; move to JSON and load it into the same dataclasses;
or generate the JSON from the module for the UI and keep the module canonical.
Not decided here.

**Phase 2.5 - `UnsupportedItem` against "prefer a flagged return over a
refusal".** The plan says unsupported situations raise and never approximate.
The owner's standing instruction, and CLAUDE.md trap 30, is that a flagged
return beats no return: refusing looks conservative and is not, because a
preparer cannot correct a return that does not exist. The working rule written
into the `tax-architecture` skill is that `UnsupportedItem` marks *that node*
unsupported, every downstream node inherits the flag, the rest of the return
still computes, and the package is marked not-fileable with the unsupported
lines named. Approximation never happens either way. Confirm or change this.

**Phase 1.3 - "byte-identical" needs a definition.** The harness that would
capture a baseline is Phase 6. Output is written per run under a workflow UUID
(`data/output/<workflow_id>/...`), so raw bytes will differ between two runs of
unchanged code. Read it as: the same figures on the same lines with the same
provenance, compared after normalising run ids, timestamps and paths.

**Phase 6.2 - CI cannot hold the eval cases.** The workpaper/return pairs in
`Files/` are real client PII and gitignored, and the expected figures are taken
off real prepared returns. `make eval` therefore runs locally against the real
corpus; CI runs the engine unit tests and the property tests (6.3, 6.4), which
use invented values. See `/add-eval-case` for the split that keeps this true.

## What already exists that these phases touch

- `backend/app/services/tax_engine/` - `computations.py`, `form_1040.py`,
  `form_7203.py`, `tax_tables.py`, `tax_authority.py`, `calculation_trail.py`.
  Phase 2 is a rewrite of this module, not a greenfield build.
- `calculation_trail.py` already produces a `TrailRow` per line carrying source,
  formula, authority, `feeds_into`, `derived_from` and `basis`, and a `verify`
  that recomputes each row against the engine. That is most of Phase 3's
  provenance record, built by hand per line rather than derived from a graph.
- Reconciled benchmarks: CS 2 (Line 6b correct; open gaps are Form 7203,
  schedule rendering, rounding) and Basic 5 (QBI plus the Tax Table, not the
  rate schedule). Any engine change is measured against these first.
