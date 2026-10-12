# TaxScraper

A US tax automation platform with two products on one backend:

1. **Workpaper automation** — scanned accounting workpapers in, reviewed tax
   package out.
2. **Tax & audit assistant** — click a state on the map and ask a federal,
   state, multi-state, case or dispute question; answers are grounded with
   Google Search, cited, dated to a tax year, and checked before they are shown.

The governing constraint is that **no real taxpayer data ever reaches a
third-party language model**. Everything below follows from that.

---

## Quick start

```bash
python -m pip install -r backend/requirements.txt
python -m spacy download en_core_web_sm
cp backend/.env.example backend/.env
```

Generate real encryption keys before doing anything else:

```bash
cd backend && python -c "from cryptography.fernet import Fernet; import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(64)); print('FILE_ENCRYPTION_KEY=' + Fernet.generate_key().decode()); print('VAULT_ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
```

Paste those three lines into `backend/.env`, then run the two services:

```bash
cd backend && uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

The UI is at http://localhost:5173, the API docs at http://localhost:8000/docs,
and a readiness report with actionable warnings at
http://localhost:8000/api/settings/health.

### Optional but recommended

| Dependency | Why | Without it |
| --- | --- | --- |
| **Tesseract OCR** | The sample corpus is scanned images with no text layer | Scanned pages are marked `OCR_UNAVAILABLE` and routed to human review — never silently sent to a cloud OCR service |
| **Gemini API key** | Extraction, and every assistant answer | The pipeline runs on deterministic stubs; the assistant says it is unavailable rather than answer from nowhere |

```bash
winget install --id UB-Mannheim.TesseractOCR
```

Then set `TESSERACT_CMD` in `backend/.env` if it is not on `PATH`.

---

## The privacy model

Data moves in one direction. This is the core invariant, not a guideline.

```
RAW ────────► MASKED ────────► LLM ────────► (results) ────────► OUTPUT
encrypted     tokenized        external                          rehydrated
at rest       surrogates       (Gemini)                          locally
```

* **Raw zone** — Fernet-encrypted originals. Only `ingestion_service`,
  `ocr_service`, and `rehydration_service` may read it.
* **Masked zone** — the only zone whose contents may leave the host.
* **Token vault** — `original ↔ token ↔ surrogate`, encrypted under a *separate*
  key from the file zone, so one compromised key does not yield both the
  documents and the identities behind them.
* **Output zone** — rehydrated deliverables. Never sent outbound; downloads are
  role-gated and audited.

### Why surrogates instead of `[REDACTED]`

Substituting `PERSON_001` into a W-2 produces text no tax form ever contained,
and extraction quality drops sharply — the model loses the cue that box (e)
holds a name. Each value is instead replaced with a realistic substitute drawn
from a range that **cannot correspond to a real person**:

| Type | Surrogate range | Why it is provably fake |
| --- | --- | --- |
| SSN | `666-xx-xxxx` | The SSA has never issued area 666 |
| EIN | `00-xxxxxxx` | Not an IRS campus prefix |
| Phone | `555-01xx` | Reserved for fiction |
| Email | `@example.com` | Reserved by RFC 2606; unregistrable |
| Routing | fails the ABA checksum | Cannot route funds |
| Card | fails Luhn | Cannot be processed |

A leaked surrogate points at nobody. The egress guard also recognises these
ranges structurally, which is what lets the chatbot mask per request without a
workflow-scoped allow-list.

### Defence in depth

1. `pii_detection_service` — regex + structural validators (SSN issuance rules,
   ABA checksum, Luhn), spaCy NER for names, and **columnar rules** for tax
   forms, which put a label above or below its value rather than beside it.
2. `masking_service` — tokenizes and substitutes; the vault keeps the mapping.
3. `llm_egress_guard` — re-scans every serialized outbound payload and refuses
   to transmit when it finds unmasked PII. This is the backstop for a detection
   miss, and it fails closed.
4. `core/logging.py` — a redaction filter on the root logger.
5. `core/audit.py` — rejects any audit payload containing patterned PII.

---

## Correctness model

**The model proposes; the tax engine decides.** No figure reaching an output
package is produced by a language model.

* `services/tax_engine/` computes in `Decimal` with explicit IRS-convention
  rounding (`ROUND_HALF_UP`, not banker's).
* Any LLM figure disagreeing with the deterministic recomputation beyond
  `CALC_TOLERANCE_DOLLARS` becomes a review item, and the computed value wins.
* `ModelRouter.assert_not_arithmetic` makes "ask the model to add these up" a
  hard error rather than a convention that erodes.
* Unknown tax years raise instead of falling back to the nearest year — a return
  computed on the wrong year's brackets looks right and is wrong.

---

## Pipeline

```
Upload → Classification → OCR → Masking → LLM → Validation → Review → Rehydration → Output
```

Masking sits between OCR and the model; rehydration sits after all model
interaction. No stage may reach across those two boundaries.

Each stage returns a `StageOutput(value, detail)`. Only `detail` is persisted to
the audit log, and it carries counters exclusively — a stage's working data
(masked page text, extracted fields) is never recorded.

### Reading the document

A scanned workpaper often carries a thin text layer holding just the client's
name and address, which makes it *look* readable while every figure stays in the
image. OCR therefore reports two numbers, not one: **coverage** (how much of the
document produced text at all) and **confidence** (how well that text scored).
Pages that read badly are retried under a second segmentation mode, and the
result is kept only if it holds onto the content rather than winning on
confidence by discarding it.

Unreadable and low-confidence pages become review items with the page ranges
named. **If no monetary field was extracted, no return is computed** — an
all-zero return is well-formed and indistinguishable from a real one, so the
pipeline refuses it the same way the chatbot refuses an unsourced answer.

### Extraction

One model call per *classified document*, not per upload: a single prompt
spanning eleven document types reads none of them closely. Each call carries a
form-specific hint (which box maps to which field) and the results are merged —
repeated forms **sum**, so three 1099-INTs give the total of all three.

Amounts from a prior-year return are surfaced for comparison but never summed
in. Its figures are a complete, plausible set, and folding them into the current
year roughly doubles the return without looking wrong.

---

## Tax & audit assistant

The `/assistant` workspace: conversations on the left, the chat in the middle,
a US map on the right. Clicking a state sets `selected_state`, which is sent
with every question as structured input. It applies to state and local
questions; a federal question gets the federal answer whatever is selected.

Answers stream token by token, shaped to the question: a rate is a sentence
or two, a notice gets numbered steps with deadlines, a case gets a summary and
why it matters. Progress steps are shown as each stage really starts.

Single-year calculation questions have an additional verification step: a short
grounded search locates official documents, then the server reads their HTML
or PDF text, including linked current-year revisions. That primary text is
passed to the answering model instead of relying on search snippets for the
inputs. The reader checks the jurisdiction and every redirect, caps downloads,
and scrubs public contact details before any text goes back to the model.
Unreadable or missing official material stops the calculation with an explicit
message; it is not presented as proof that a year's rules are unpublished.
This adds latency to calculations, not ordinary factual or procedural answers.

**Masking is on request.** Start a message with `/mask` and names and
identifiers are replaced with placeholders before anything is sent (and put
back in what you see). Without it the question is sent as typed; the egress
guard still blocks SSNs, EINs, card and account numbers and email addresses,
and says to remove them or use `/mask`. Attached documents are always masked.

### Setup

All configuration is environment variables in `backend/.env` (see
`backend/.env.example`). The ones that matter here:

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Required for answers. Never logged or serialized. |
| `GEMINI_ENABLED` | `false` turns the assistant off (it says so) |
| `ASSISTANT_MODEL` | The model that answers - **the only place it is named** |
| `ASSISTANT_THINKING_LEVEL` | Thinking level for the answer call; the largest term in time to first token |
| `ASSISTANT_ROUTER_MODEL`, `ASSISTANT_ROUTER_THINKING_LEVEL` | The small model that classifies each question first; empty turns routing off |
| `ASSISTANT_CACHE_MAX_ENTRIES`, `ASSISTANT_CACHE_TTL_SECONDS` | Same-day replay of general questions; `0` turns it off |
| `ASSISTANT_TEMPERATURE` | Default `0.2`; low on purpose |
| `ASSISTANT_HISTORY_TURNS` | Prior turns replayed for follow-ups |
| `ASSISTANT_RESOLVE_SOURCE_URLS` | Resolve grounding redirect links to the real page (one header-only hop to Google's redirect host) |
| `GEMINI_TIMEOUT_SECONDS`, `GEMINI_MAX_RETRIES` | Per-call timeout and retry-with-backoff, shared with the pipeline |
| `STATE_UPDATES_ENABLED` | The state panel's "recent updates" fetcher |

**Changing the model:** set `ASSISTANT_MODEL` and restart. It must support
Google Search grounding (Gemini 3 series or later). Run the eval set
afterwards - see below.

Calculation source discovery also resolves Google's grounding redirects so it
can read the original documents, independently of the display-link setting.

### How an answer is produced

```
request ─► validate selected_state (allow-list: 50 states, DC, PR) ─► /mask? mask
        ─► route (small model, JSON): scope · answer type · depends on state law?
             ├─ out of scope ─► fixed text            (no search)
             ├─ needs one fact ─► one clarifying question (no search)
             └─ same question today ─► cached answer
        ─► resolve jurisdiction: named state = demand; selected state only if state-specific
           ─► single-year calculation: grounded source discovery + official HTML/PDF reading
             missing material: stop; never calculate from an unverified cached answer
        ─► one Gemini call + Google Search grounding, streamed (delta events)
             META line held back · /mask surrogates swapped back as it streams
        ─► at the end: grounding · tax year · state consistency
             └─ fail: withdraw the draft (replace event), regenerate once ─ fail again: fallback
        ─► source markers from grounding supports only (never in an example)
           figures no source covers are flagged [?] ─► store ─► final event
```

Code lives in `backend/app/services/assistant/`:

| Module | Job |
| --- | --- |
| `state_registry` | The jurisdiction allow-list; agencies, official domains, structural features (no income tax, community property, local income tax...). **No rates or thresholds.** |
| `router` + `prompts/router_system.md` | Classifies the question; deterministic overrides (a named state, state-tax words) beat the model |
| `prompt_builder` + `prompts/*.md` | Resolves which states an answer must cover and renders the prompt, including the answer policy for the question's type (`prompts/policy_*.md`) |
| `official_sources` + `prompts/source_research.md` | Calculation-only primary-source discovery and bounded reading; accepts metadata URLs and official-page links only, checks each redirect, and supplies scrubbed document text |
| `gemini_client` | The one streamed, grounded call, through `GeminiService` (egress guard, retries before the first token, metering). Explains why it is one call |
| `answer_text` | The hidden META line, removing anything citation-like the model wrote, follow-ups, examples, unsourced-figure flags |
| `validators` | The end-of-stream checks. A wrong-state answer is never left on screen |
| `citations` | Places markers from grounding supports, resolves redirects, ranks sources by authority |
| `formatter` | One response shape for every outcome (answered, declined, clarify, out of scope, fallback, unavailable) |
| `masking` | `/mask`: masks the question for prose, restores the user's own words in what is displayed, including mid-stream |
| `answer_cache` | Same-day replay of general first-turn questions |
| `assistant_service` | Orchestration, persistence, one structured log line per answer (route, state, year, sources, validation, time to first token, latency - never text) |

### Tests and evals

```bash
cd backend && python -m pytest tests/test_assistant.py tests/test_assistant_arithmetic.py tests/test_assistant_sources.py tests/test_assistant_masking.py -q
cd ..
python -m evals.assistant.run_eval --label after-my-change    # live: real Gemini + Search
python -m evals.assistant.run_eval --compare baseline after-my-change
python -m evals.assistant.run_eval --case ca-rates            # one case
python -m evals.assistant.run_eval --masking-only             # offline /mask cases
```

The live eval (`evals/assistant/eval_set.json`) covers facts,
how-tos, scenarios, cases and news, disputes, multi-state moves and edge
cases, plus 12 offline masking cases, and reports time to first token, total
time, words against each answer type's budget, a correctness rubric,
state-correctness, citation validity, cited hypotheticals, uncited figures,
follow-up count, and tokens per case. Run it after changing a prompt, a
policy or a model; unit tests cannot catch provider behaviour.

---

## Depreciation calculator

### Importing an asset list (current-year additions)

**Import Excel** on `/depreciation` takes the firm's additions list - an
`.xlsx` or `.csv` whose first sheet has a header row with Asset #, Description,
Date Acquired and Cost (columns are found by name; a Life column, if present,
is used as given) - and returns the "CY Addition Dep Summary" workbook in the
firm's own layout: Asset # · Asset Desription · Date Acquired · Cost · Life ·
Federal Depreciation - Bonus · Federal Depreciation - MACRS · State
Depreciation - Sec 179, SUM totals five rows below the last asset, the
"Federal" cost/depreciation summary by life, and IRS Pub. 946 Table A-1.

- **AI predicts the life only.** Each description (identifiers redacted; no
  amounts or dates sent) is classified into one of the engine's asset classes
  following Rev. Proc. 87-56 - specific asset classes first, otherwise the
  business activity's class (for example 57.0, distributive trades: 5-year for
  a dealership's shop equipment). The optional *Business type* field helps.
  Every prediction shows its reason; change any life before exporting.
- **Everything else is the engine.** Bonus at the rate for the acquisition
  date and class, the first-year Pub. 946 MACRS rate (half-year or the
  mid-quarter test over all the assets; mid-month for buildings), and the
  selected state's Section 179 under its verified regime. Tick or untick
  *Elect* per asset; mark heavy *work vehicles* outside the SUV cap.
- The workbook carries the template's formulas (`=+D2`, `=D2*20%`, `SUMIF` by
  life) with the engine's rates inside them and recalculates on open; the
  screen totals round once, as Excel's `SUM` does, so they agree to the cent.
- Settings: `DEPRECIATION_LIFE_MODEL`, `DEPRECIATION_LIFE_THINKING_LEVEL`.
  Without a Gemini key the import still works; every life is left for you.

`/depreciation` is a live workspace. You enter one or more business or rental assets, and it shows the deduction year by year for the selected tax year, at federal level and for the state picked on the map. The map selection is shared with the assistant.

### The design rule

**All arithmetic is deterministic code.** Gemini never computes a deduction. The engine lives in `backend/app/services/depreciation/` and makes no network calls and uses no randomness. It applies the rules in a fixed order:

1. Section 179, including the phase-out, the business income limit with carryforward, and the SUV cap.
2. Bonus depreciation (§168(k)), at the rate set by the acquisition and placed-in-service dates, or the §168(n) allowance.
3. The mid-quarter test. Each asset's "Method and convention" field defaults to *Automatic (40% test)*. You can instead choose half-year or mid-quarter for personal property; buildings are always mid-month. A chosen convention is applied as given, and the results warn when it differs from what the 40% test requires. Mid-quarter still uses the placed-in-service quarter to pick its table.
4. MACRS from the Pub. 946 tables.
5. §280F limits.

The state treatment is either the same engine run with the state's parameters, or the federal schedule plus addbacks and the later recovery of those addbacks. Either way, the state difference reverses to zero over the asset's life.

**Gemini does only two things:**

- **The explanation.** "Explain this result" writes a plain-English explanation, grounded in Google Search, of figures the engine already produced. It never sees the asset descriptions, and it is withheld if it states any dollar amount or percentage the engine did not produce.
- **The refresh script.** `scripts/refresh_rules` proposes rule updates for human review.

### Where the rules live

All rules are versioned JSON in `backend/app/tax_rules/depreciation/`. Every entry carries `source_url`, `source_citation`, `last_verified` and `verified`.

| File | Contents |
|---|---|
| `macrs_tables.json` | Pub. 946 Appendix A tables A-1 to A-12. Generated from the PDF; do not edit by hand. |
| `federal_rules.json` | Section 179 limits, bonus rules keyed by acquisition date, §168(n), §280F caps, mid-quarter test, Form 4562 line layout by year |
| `asset_classes.json` | Recovery period, method and eligibility for each class |
| `state_conformity.json` | 50 states + DC × every supported year. Generated from the cited research rows in `docs/tax-research/state-depreciation-conformity-batch*.json` plus the reviewed mechanics in `state_conformity_overrides.json`. |

**Supported years:** 2021–2026. Any other year is refused with a message; the calculator does not guess.

**State statuses:**

- **verified:** applied.
- **no_income_tax:** says so, and names any entity-level tax the calculator does not compute.
- **unverified:** shows "State rules not yet verified for this year" next to the full federal result. The user can open a clearly labelled provisional estimate built from that state's own researched rule.

Another state's rules are never substituted.

### Rounding

Each asset's deduction for a year is computed exactly, then rounded half-up to whole dollars at the end of that year's computation. The final year absorbs the rounding difference, so every schedule totals its basis to the dollar. The tape shows any rounding adjustment.

### Commands

```bash
cd backend && python -m scripts.build_depreciation_rules        # regenerate tables + state table (fails on any table not summing to 100%)
cd backend && python -m pytest tests/test_depreciation_*.py -q  # rules, engine, properties, API, exports, validation
cd frontend && npm test                                         # UI: map pre-fill, year change, exports, a11y
cd backend && python -m scripts.refresh_rules --year 2027 --dry-run
```

`docs/validation.md` records the cross-checks: 25 scenarios against Pub. 946 worked examples and the Rev. Procs., plus 54 against an independent first-principles computation.

### Yearly rule update checklist

Do this each autumn, once the IRS publishes the next year's inflation adjustments, and again after any tax legislation.

1. **Run the proposer:** `python -m scripts.refresh_rules --year <next> --states ALL`. It writes `docs/tax-research/rule-proposals/refresh-<year>-<date>.md` and never edits rule data. Treat every `changed`, `new` or `ungrounded` row as a lead, not an answer.
2. **New Section 179 limits.** Take these from the annual inflation Rev. Proc. (section "Election to Expense Certain Depreciable Assets"; for 2026 it was Rev. Proc. 2025-32 §4.24). Add the year under `section_179` in `federal_rules.json`, with the Rev. Proc. URL.
3. **New §280F caps.** These come from the auto-limits Rev. Proc. (usually Q1; for 2026 it was Rev. Proc. 2026-15). Add Tables 1 and 2 under `luxury_auto_caps`.
4. **Bonus and §168(n).** Check the Form 4562 instructions "What's New" and any Notices for changes. Extend `rate_by_placed_in_service_year` or add a rule keyed by acquisition date.
5. **Form 4562 layout.** If the new form renumbers lines (the 2025 form moved residential rental from line 19h to 19i), add a layout.
6. **MACRS tables.** If a new Pub. 946 is published, re-extract it with `docs/tax-research/sources/extract_p946.py`, rerun the build script, and diff `macrs_tables.json`. The tables have not changed in decades, so any diff is a red flag.
7. **State legislation.** For each state, check the agency's guidance on federal conformity for the new year: a conformity-date bill, a bonus or §179 decoupling, or a §168(n) addback. Add research rows (with `source_url` and `verified`) for the new year using the `research-tax-rule` skill, then add an override only where the mechanics need one.
8. **Add the year** to `supported_years` in `federal_rules.json` and `SUPPORTED_YEARS` in `scripts/build_depreciation_rules.py`. Rebuild, then run the depreciation tests and `docs/validation.md`'s scenarios. Update `last_verified` on every entry you re-read.

---

## Dashboard, IRS Forms, Industry Updates and State Intelligence

Four sections for tax associates, sharing one state-and-year selection with the assistant and the depreciation calculator:

| Route | What it is |
|---|---|
| `/` **Dashboard** (the new home) | Greeting and a daily line, countdowns to March 15 / April 15 / September 15 / October 15, quick links, the three latest updates, the associate's clients, and a deadline calendar |
| `/forms` **IRS Forms** | Federal, business and state form tiles: search, category and tax-year filters, download from the agency, and "Ask the chatbot about this form" |
| `/updates` **Industry Updates** | IRS and Treasury news; Bloomberg Tax and Thomson Reuters only through a licensed connection |
| `/states`, `/states/:code` **State Intelligence** | Apportionment, nexus, federal conformity, rates and filing requirements per state and year, plus a two-state compare (`?compare=NY`) |

The old workload dashboard moved from `/dashboard` to `/workload` (the old URL redirects). The standalone state map was removed (`/map` redirects to State Intelligence; the assistant keeps its own map), and return preparation (`/prepare`) is listed as a disabled "Coming soon" entry while it is in development.

**Shared selection.** The selected state is stored under the key the assistant and the calculator already used, so a click anywhere follows everywhere. The tax year is kept for the browser session (`frontend/src/context/TaxContext.tsx`). Links into the assistant (`/assistant?q=...&state=XX`) only *pre-fill* the question; the user sends it. The state still goes through the assistant's own allow-list.

### The rules these sections keep

- **No tax facts in UI code.** Deadlines, holidays, form metadata, news sources, state facts and the motivational lines are versioned JSON under `backend/app/reference_data/`. Each file is validated by a Pydantic schema on load (`app/services/reference_data.py`), and every fact carries `source_url` and `last_verified`.
- **Gemini never supplies a number or date shown as fact.** It does two things here:
  - `scripts/refresh_state_intel` proposes updates for a person to review.
  - The Industry Updates "AI summary" button writes a short summary. It is labelled *AI-generated summary*, sits beside the original link, is built only from the agency's own headline and excerpt, and is withheld if it states a number that text does not contain.
- **Dates are calendar dates in the user's time zone.** `frontend/src/lib/dates.ts` is the only date module. "Today" is the user's wall-clock date, and day counts are differences between calendar dates, never 24-hour blocks. `frontend/src/lib/deadlines.ts` is the pure deadline engine. Both are unit tested across year ends, leap days, weekends, federal holidays, DC Emancipation Day and time zones.
- **Gaps are said, not filled.** A state without verified data shows "Not yet verified" or "Forms not yet verified for this state" with the agency link. The calendar shows "State rules not yet verified" for that client and state instead of a borrowed date.
- **Federal Conformity has one source.** It is read from the depreciation calculator's `state_conformity.json`, so the two can never disagree. An entry counts as verified only if it is dated.
- **Each panel loads and fails on its own.** One source failing never blanks the page: panels have their own loading, empty and error states, plus an error boundary.

### Setup and environment

No new service is required. These are optional settings (in `backend/.env`):

| Variable | Default | Purpose |
|---|---|---|
| `NEWS_ENABLED` | `true` | Background fetch of the IRS and Treasury pages. `false` shows the sources' own links instead |
| `NEWS_REFRESH_SECONDS` | `1800` | How often the background job refreshes |
| `NEWS_MIN_FETCH_INTERVAL_SECONDS` | `300` | Per-source rate limit, whoever asks |
| `BLOOMBERG_TAX_API_URL`, `BLOOMBERG_TAX_API_KEY` | empty | Licensed Bloomberg Tax feed. Disabled while empty |
| `THOMSON_REUTERS_API_URL`, `THOMSON_REUTERS_API_KEY` | empty | Licensed Thomson Reuters feed. Disabled while empty |

Keys are read only on the server and never reach the browser.

Clients on the calendar keep only a display name, entity type, year-end month, states, extension status and notes. The name and notes are Fernet-encrypted at rest and never logged. There is no SSN, EIN or bank field, and a name shaped like an SSN or EIN is refused. No client data is seeded.

### Sources used for the public feeds

- **IRS.** The IRS does not publish a news RSS URL that could be confirmed on irs.gov (its e-News is email). The feed therefore reads the official monthly listing pages, `irs.gov/newsroom/news-releases-for-current-month` plus the previous month. These listings are allowed by robots.txt.
- **Treasury.** `home.treasury.gov/rss.xml` carries site content, not press releases. The feed reads `home.treasury.gov/news-data/widgets/latest.json`, the data Treasury's own press-release widget loads. robots.txt allows all paths.

Each item shows only the title, date, source, an excerpt of at most 280 characters from the agency's own summary, and the link.

### Enabling Bloomberg Tax or Thomson Reuters

These publishers are copyrighted and paywalled. The app never scrapes them. To connect one:

1. Obtain API access under a licence that permits showing headlines and links to your users.
2. Set the two environment variables above and restart the backend.
3. Adapt `LicensedApiProvider.parse` in `backend/app/services/news_service.py` to the vendor's documented response. It currently expects `{"items": [{"title", "url", "published"}]}`.

No excerpt is ever taken from a licensed source. Until the variables are set, the tab says "Connect your Bloomberg Tax account to enable" and the rest of the page works.

### Adding or changing a form

1. Add an entry to `backend/app/reference_data/forms/federal_forms.json`, or `state_forms.json` for a state. Each entry has:
   - `form_number`, `title`, `one_liner`, `category`, `audience` and `state`
   - `source_page_url` and `pdf_url`, which must be the agency's own URLs, never a re-hosted copy
   - `annual` and `prior_year_pdf_pattern` (IRS: `https://www.irs.gov/pub/irs-prior/<slug>--{year}.pdf`)
   - `one_liner_reviewed: false`
2. Run `cd backend && python -m scripts.verify_forms --update --only "<number>"`. It checks HTTP 200, a PDF content type and a `%PDF` body, records the revision printed on the form and `last_verified`, and also checks the landing page.
3. Have a person check the one-liner against the form's instructions, then set `one_liner_reviewed: true`. Until then the tile is labelled "Description pending review".
4. `python -m pytest tests/test_reference_data.py -q`.

`verify_forms` runs weekly in CI (`.github/workflows/forms-links.yml`) and exits non-zero on a broken link. Some state sites (ftb.ca.gov) refuse automated clients with 403. Those links are reported separately as "refused by host" and must be checked in a browser.

### Updating state data each year

**Bulk research (all states).** Run `python -m scripts.research_state_intel --states ALL`, then `--apply --run <date>`. It researches each section with Gemini and Google Search grounding, then fetches the state's own agency or legislature page itself. A field is kept only if all of these hold on that page:

- every number in the value appears on it;
- at least two distinctive evidence phrases appear (one, if the model gave only one);
- every month-day date in the value appears (a due date the page never states is rejected);
- the quoted sentence holds a matched phrase and, when the value has a key figure (a percentage, a decimal or a number of three or more digits), that figure too.

If the page URL or title names exactly one tax year, the field is limited to that year. `--reverify --run <run>` re-checks stored proposals against the current rules with no model calls, so tightening a rule never needs a new research run.

Some agency sites answer scripted requests with a bot challenge (Cloudflare, Akamai, Imperva). The challenge is never bypassed. Where the page opened normally in a browser, the same checks were run in the page and recorded. Indiana, Louisiana, Missouri and Utah could not be read at all, so they show "Not yet verified".

Kept fields are stored with `verification: automated_page_match` and the page text that matched. The UI labels them "Auto-checked" and can show "What the page says". Hand-verified fields always win over automated ones. Proposals, accepted and rejected with reasons, stay in `docs/tax-research/state-intel-proposals/<run>/`.

Treat auto-checked fields as strong leads. Prioritise a person's review of rates and due dates before filing season. Give each parallel process its own `DATABASE_URL` (the audit log is a hash chain).

**One field at a time:**


State facts live in `backend/app/reference_data/state_intel/states/<CODE>.json`, one file for each of the 50 states and DC. Each field lists the tax `years` its source covers. A field shows for a year only if that year is listed.

1. Run `cd backend && python -m scripts.refresh_state_intel --year <year> --states ALL`. It uses Gemini with Google Search grounding to propose each section and compares the proposal with what the file holds. It writes `docs/tax-research/state-intel-proposals/state-intel-<year>-<date>.md` and **applies nothing**.
2. For each `new` or `review` row, open the cited page on the state's own agency or legislature site and confirm the rule. Then add the year to the field's `years`, or add a new field with `source_url`, `source_citation` and `last_verified`. Never apply an `ungrounded` row.
3. If due dates changed, update the state's `filing.due_rules` (used by the calendar).
4. Federal Conformity is refreshed through the depreciation calculator's own process (`scripts/refresh_rules --states`). See its checklist above.
5. Add the year to `SUPPORTED_YEARS` in `app/services/reference_data.py`.
6. `python -m pytest tests/test_state_intel.py tests/test_reference_data.py -q`. Among other things, these check that every field cites that state's own domain.

### Yearly review checklist

Do this each autumn, and again after any federal or state tax legislation.

1. **Federal due dates** (`calendar/federal_due_dates.json`):
   - Re-read "When To File" in the Form 1040, 1120, 1120-S, 1065, 1041 and 990 instructions, and the Form 7004 "Extension Period".
   - The June 30 C-corporation exception ends for tax years beginning in 2026. Check whether it is still needed.
   - Update `last_verified`.
2. **Holidays** (`calendar/legal_holidays.json`): check for a new federal or DC legal holiday (IRC 7503). Then run `npm test`, which pins OPM's published schedule.
3. **Forms:**
   - Run `verify_forms --update --prior-years <last year>`.
   - Review every revision change and every broken link.
   - Add new forms, and remove retired ones (1120-W and 1023 were removed on 2026-10-07: no PDF on irs.gov).
4. **State Intelligence:** follow "Updating state data each year" for every state you can verify; say so for the rest.
5. **News sources:**
   - Confirm the IRS listing pages and the Treasury JSON still parse. `tests/test_news_service.py` fixtures show the expected shapes.
   - Re-read each publisher's terms if licensed feeds are on.
6. **Motivational lines** (`dashboard/motivation.json`): add lines freely. Keep them original and short.
7. **Default tax year** (`DEFAULT_TAX_YEAR`, `app/core/config.py`): the one setting every product opens on - the shared year selector, the depreciation calculator, the assistant when a question names no year, and a workpaper whose documents state none. Move it to the new year once that year's rules are in. Each product clamps it to the years its own rules cover (`app/core/tax_year.py`), so moving it early never shows a year without rules; a workpaper that has to fall back raises a "Tax year assumed" review item.

### Tests

```bash
cd backend && python -m pytest tests/test_reference_data.py tests/test_state_intel.py tests/test_news_service.py tests/test_workspace_api.py -q
cd frontend && npm test                      # dates, deadline engine, motivation, page components + axe
cd frontend && npx playwright test           # e2e in installed Edge (E2E_BROWSER=chrome for Chrome)
cd backend && python -m scripts.verify_forms # live link check (network)
```

The Playwright run starts its own backend on port 8001 with a throwaway database, and turns the news feed and Gemini off, so it makes no outside calls. It covers the main flows:

- the greeting and countdown render
- adding a client makes its deadline appear
- downloading a form
- clicking a state, then opening State Intelligence
- the mobile and desktop layouts
- keyboard navigation of the calendar
- reduced motion
- axe, including colour contrast, in light and dark mode

---

## Commands

```bash
cd backend && python -m pytest -q                  # full suite
python -m evals.assistant.run_eval                 # assistant, live (needs a key)
cd backend && python -m pytest -m security -q      # privacy invariants only
cd backend && python -m ruff check app tests
cd backend && python -m mypy app
cd frontend && npm run typecheck
cd frontend && npm test && npx playwright test
```

`tests/test_security_invariants.py` and `tests/test_encryption_persistence.py`
are guard rails. If a change breaks one, the change is wrong — not the test.

---

## Sample corpus

Set `TAX_FILES_DIR` to a folder where each input workpaper has a matching output
whose filename contains `copy`:

```
Basic 5 Workpapers.pdf   →   Basic 5 Accountant Copy.pdf
```

The Settings page can then infer field mappings from those pairs. Learned
templates start as **proposals**; only a reviewer can approve one, and only
approved templates influence a client's return.

---

## Operational notes

* **Key rotation destroys access to existing data.** Changing
  `FILE_ENCRYPTION_KEY` makes previously uploaded files unreadable; they are
  marked `quarantined` with an explanation and must be re-uploaded. Without
  explicit keys, a persistent development seed is written to
  `data/.dev_key_seed` so encrypted data survives restarts.
* **Production refuses unsafe configuration.** `APP_ENV=production` will not
  start with auth disabled, the egress guard off, or missing encryption keys.
* **SQLite is for local development.** Point `DATABASE_URL` at PostgreSQL for
  anything else; no code changes are required.
* **Tax tables are provisional** for years the IRS has not yet published final
  figures for. The Settings page shows which years are verified.

---

## Not production-ready without

This is a working platform, not a filing service. Before real client data:

* Replace `AUTH_DISABLED` with real authentication and per-client authorisation.
* Move the synchronous `/process` endpoint onto a task queue.
* Serialise audit writes, or move the chain to a single-writer service.
* Have a licensed practitioner verify every rate table and computation against
  current IRS guidance.
* Complete a security review covering key management and retention in your
  actual deployment environment.
