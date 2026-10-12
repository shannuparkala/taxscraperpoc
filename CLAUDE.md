# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

TaxScraper is a US tax automation platform. It ingests accounting workpapers
(mostly scanned PDFs), extracts tax facts, computes and validates a return
deterministically, and produces a reviewed output package — while guaranteeing
that no real taxpayer PII ever reaches a third-party LLM.

Three products share one backend:
1. **Workpaper automation** — input documents to output tax package.
2. **Tax & audit assistant** — the flagship. A chat workspace at
   `/assistant` with a US map: the clicked state is sent as `selected_state`.
   It answers federal, state, multi-state, case and dispute questions from
   **one streamed Gemini call with Google Search grounding**: the markdown
   answer reaches the reader token by token, shaped to the question (a fact
   is a sentence, a notice gets steps), and is checked when the stream ends
   (sources, tax year, state consistency). A draft that fails is withdrawn
   from the screen and regenerated once, then replaced by a safe fallback
   rather than shown wrong. Sources are built from grounding metadata only.
   Rebuilt 2026-10-05 (two calls, fixed JSON layout) and again 2026-10-09
   for speed and adaptive answers (`docs/assistant-streaming-PROGRESS.md`).
   Code: `app/services/assistant/`; README "Tax & audit assistant".

3. **Depreciation calculator** - `/depreciation`, a live workspace: assets in,
   federal and selected-state schedules out, with a calculation tape that shows
   the engine's own steps. All arithmetic is the deterministic engine in
   `app/services/depreciation/`; rules are versioned JSON in
   `app/tax_rules/depreciation/` (every entry sourced, `verified` flagged);
   Gemini only explains computed figures (grounded, number-checked),
   proposes rule updates via `scripts/refresh_rules` (never applied
   automatically), and - for an imported asset list - predicts each asset's
   life (its MACRS class) for the user to review. "Import Excel" turns an
   asset list into the firm's "CY Addition Dep Summary" workbook
   (`addition_import`, `life_predictor`, `addition_report`). README
   "Depreciation calculator" has the yearly checklist.

4. **Associate workspace** - `/` dashboard (countdowns, client deadline
   calendar), `/forms`, `/updates`, `/states` (State Intelligence).
   Every fact is versioned JSON in `app/reference_data/` loaded through
   `services/reference_data.py`; dates are computed in the browser by
   `frontend/src/lib/dates.ts` + `lib/deadlines.ts` (pure, in the user's time
   zone). State Intelligence's Federal Conformity tab reads the depreciation
   calculator's `state_conformity.json` - one source of truth. README
   "Dashboard, IRS Forms, Industry Updates and State Intelligence" has the
   yearly checklist.

## Layout

```
backend/          FastAPI service
  app/api/        HTTP routes (thin — no business logic)
  app/core/       config, security, audit, db, errors, rate limiting
  app/models/     SQLAlchemy ORM tables
  app/schemas/    Pydantic request/response + LLM contracts
  app/repositories/  data access (the only layer that touches the session)
  app/services/   business logic, one service per pipeline stage
  app/services/tax_engine/  deterministic tax math (no LLM, ever)
  app/services/assistant/  the tax & audit assistant: state_registry (the
                      52-jurisdiction allow-list, agencies, domains, structural
                      features — never figures), prompt_builder + prompts/,
                      gemini_client, answer_text (META line, cleanup,
                      follow-ups), answer_schema, validators, citations,
                      formatter, masking, assistant_service
  app/tax_knowledge/  rule_citations (the workpaper explanation's authority)
  tests/
frontend/         Vite + React + TypeScript SPA
data/             gitignored storage zones (raw|masked|output|tmp|vector)
Files/            client workpaper corpus — gitignored, REAL PII
legacy/           pre-rewrite standalone scripts, kept for reference only
docs/             architecture, security model, tax logic notes
```

## The four zones

Data moves in one direction only. This is the core invariant.

```
RAW ────► MASKED ────► LLM ────► (results) ────► OUTPUT
(encrypted)  (tokenized)  (external)              (rehydrated)
```

- **Raw zone** — Fernet-encrypted originals. Readable only by
  `ingestion_service`, `ocr_service`, `rehydration_service`.
- **Masked zone** — tokenized text/tables. The *only* zone whose contents may
  be sent outbound.
- **LLM zone** — Gemini. Receives masked content exclusively.
- **Output zone** — rehydrated deliverables. Never sent outbound.

The token vault (original ↔ token ↔ surrogate) is separately encrypted and
**must never be serialized into an LLM prompt**. There is no code path that
should ever join the vault to an outbound payload.

## Non-negotiable rules

1. **Never send unmasked content to any LLM.** Every outbound call goes through
   `gemini_service`, which runs `llm_egress_guard` on the serialized payload
   first. Do not add a call path that bypasses it. **One owner-approved
   exception (2026-10-09): assistant chat questions are masked only when the
   user starts the message with `/mask`.** Default masking turned title-case
   phrases and case names into invented people and the model answered a
   garbled question. The egress guard still runs on every unmasked question,
   so an SSN/EIN/ITIN, card or account number or an email blocks the send and
   the reply tells the user to remove it or use `/mask`. Phone numbers and
   street addresses are advisory-only in the guard: without `/mask` they are
   sent, as names are. Workpaper documents and chat
   attachments are always masked; this exception is the typed question only.
   See `assistant/masking.py` and `tests/test_assistant_masking.py`.
2. **Never log PII.** Log tokens (`TAXPAYER_001`), never values. Audit events
   carry token references only. `core/logging.py` installs a redaction filter as
   a backstop, but do not rely on it — do not pass PII to a logger.
3. **Never let the LLM produce a final number.** The LLM extracts and proposes;
   `services/tax_engine/` computes. Any LLM figure that disagrees with the
   deterministic recomputation beyond `CALC_TOLERANCE_DOLLARS` becomes a review
   item — the deterministic value wins.
4. **When unsure whether a field is sensitive, mask it.** False positives cost a
   reviewer ten seconds; false negatives are a client data breach.
5. **No secrets in code.** Everything through `core/config.py` ← environment.
   `.env.example` is committed; `.env` never is.
6. **Grounded or nothing.** The assistant must not answer from model priors.
   Every US-tax answer needs at least one source from Google Search grounding
   metadata; citations are built *only* from that metadata (the model never
   writes a URL a reader sees). No sources after the allowed attempts means a
   fallback that says it could not confirm — never an unsourced answer, and
   never an offline stub (with Gemini unconfigured the assistant says it is
   unavailable). **Streaming (owner's decision 2026-10-09):** grounding
   arrives with the last chunk, so an answer is shown while it streams and
   checked at the end; a draft that fails is withdrawn (`replace` event) and
   never left on screen. The draft renders without source markers; markers
   are placed by the server from grounding supports, never inside a
   hypothetical example.
7. **Never answer a state question from another jurisdiction's law.** A
   federal rule delivered under a state question is wrong in the way most
   likely to be acted on, and the citation makes it look checked. The
   jurisdiction is decided before the answering model is involved
   (`prompt_builder.resolve_jurisdiction`): a *named* state is a demand; a
   *selected* state (structured input validated against the registry)
   applies only when the question depends on state law - decided by the
   router (`assistant/router.py`) with deterministic overrides (a named
   state, or state/local tax words, always make it state-specific). The
   reverse failure is just as real: a federal question with Delaware
   selected came back framed around Delaware, with Delaware regulations
   cited that did not answer it. When the router cannot run, the selected
   state applies, as before. The result is handed to the model as a hard
   constraint and checked afterwards by `validators.check_states` (which now
   also rejects a federal answer built on a state). A wrong-state answer is
   regenerated once, then replaced by a fallback.
8. **No tax figure lives in code on the assistant side.** Rates, brackets,
   thresholds and deadlines come from grounded answers, each with the tax
   year it applies to. `state_registry` holds structure only (agencies,
   domains, "no income tax on wages", "community property"), handed to the
   model as reminders to verify, never as citable authority. The
   deterministic tax engine's constants are a different product and stay.

9. **Depreciation figures come from the engine, never the model or the
   browser.** The calculator's tape, "Why?" cards and exports render engine
   fields; the explanation is withheld if it states a number the engine did
   not produce. A state without a verified rule for the year shows "State
   rules not yet verified for this year" - never another state's rules.
   Rule data changes only through the JSON files and the build script.
   **The one classification a model may make** is an imported asset's life:
   `life_predictor` picks one of the engine's asset classes (a schema enum)
   from a redacted description - no cost, date or asset number is sent - and
   the engine computes every amount from that class. A period the
   description states beats the model, a life in the file is used without
   it, a failed call leaves the life for the user to choose (never a
   default), and the review table shows the model's reason on each life.

## Traps that have already bitten

These are real regressions that shipped and were fixed. Each has a test; read
the test before changing the surrounding code.

1. **Encryption keys must be stable across restarts.** Deriving a dev key from
   an in-process random value made every previously uploaded file undecryptable
   after a restart, surfacing far away as a pipeline failure. The seed is
   persisted at `data/.dev_key_seed`. See `tests/test_encryption_persistence.py`.
2. **Stage return values are not audit detail.** `_run_stage` once inferred
   audit detail from whatever a stage returned, which wrote masked page text and
   extracted fields into the audit log. Stages return `StageOutput(value,
   detail)`; anything else records nothing (fails closed).
3. **Do not scan `json.dumps` output in the egress guard.** JSON escaping turns
   a newline into `\` + `n`, and the `n` merges into the next token, so a
   correctly masked `\nalice@example.com` scans as `nalice@example.com` and
   blocks a clean payload. The guard walks the structure instead.
4. **The guard must recognise our own surrogates.** Chat masks per request, so
   there is no workflow allow-list. Surrogates are recognised structurally by
   their reserved ranges (SSN 666, EIN 00, `@example.com`, 555-01xx). Look-alike
   domains such as `example-mail.com` are registrable and must stay blocked.
5. **Retrieved public sources need contact redaction, not exemption.** IRS pages
   carry office emails; the guard cannot tell them from client data. Prompt
   assembly runs `redact_blocking_patterns` over source passages. Never use that
   helper on client document text — that goes through `MaskingService` so values
   stay recoverable at output.
6. **Regexes over document text must not cross newlines.** Use `[ \t]`, not
   `\s`. `\s` let an address pattern swallow the next line's form label and
   silently exempt an employer name from masking.
7. **A partial text layer is worse than none.** The scanned corpus carries a
   thin overlay holding only the client's name and address. Nine of 37 pages
   cleared `_TEXT_LAYER_MIN_CHARS`, so the document looked readable while every
   dollar figure stayed locked in the image layer. `winget` installs Tesseract
   per-user under `LOCALAPPDATA`, not Program Files — probing only Program Files
   silently disables OCR for the whole pipeline.
8. **Confidence must cover the pages you did not read.** `mean_confidence`
   averaged only over pages that produced text, and unread pages defaulted to
   `1.0`, so a workpaper read at 24% reported full confidence and the engine
   computed a return from it. Unread pages score zero and `coverage` is reported
   separately. See `tests/test_extraction_integrity.py`.
9. **Never emit a return computed from an empty extraction.** Zero income and
   zero tax is a well-formed return, indistinguishable from a real one, and it
   shipped as a finished package with an empty exceptions report. If no
   monetary field was extracted, refuse and raise a review item — the same rule
   as the assistant's grounding check on the chat side.
10. **Extract per classified document, not per upload.** One 103k-character
    prompt spanning eleven document types returned six facts. The classifier
    already produces segments; use them, with a form-specific hint per type.
    Keep it sequential — those calls write audit events and the audit log is a
    hash chain that concurrent writers would corrupt.
11. **Prior-year figures must never be summed into this year.** A workpaper
    routinely includes last year's return. Its wages and withholding are a
    complete, plausible set, so folding them in roughly doubles the return
    without looking wrong. `NON_SOURCE_DOCUMENT_TYPES` excludes them from the
    merge while still surfacing the facts for comparison.
12. **A scanned page can be sideways while the PDF says it is not.** Five
    1099-B pages in the sample corpus are rotated 90° with `/Rotate` set to 0.
    Tesseract read the turned glyphs as noise — 0.40 confidence, zero
    recognisable amounts — and the whole brokerage statement contributed
    nothing. OCR now runs OSD on any page below the confidence floor and
    retries rotated, mapping word boxes back to page coordinates.
13. **Never default a filing status.** `_infer_status` silently fell back to
    Single for anything it did not recognise, and the sample workpaper states
    "Joint" — a ~$15,000 error in the standard deduction alone, on a return
    that looks entirely ordinary. It returns `None` now and the caller raises a
    review item. Bare "married" stays unmapped: it does not distinguish joint
    from separate.
14. **Never latch a dependency failure permanently.** Both `_load_spacy` and
    the Gemini client cached *failure* for the life of the process — one blip
    and name masking or the whole LLM path stayed off with no retry, curable
    only by a restart nobody knew was needed. Cache successes; back off and
    retry failures.
15. **A health check that reads config is not a health check.** `/health`
    reported `llm: true` whenever an API key was set, while every call fell
    back to a stub because `google-genai` was missing from the venv the server
    actually runs from. Probe the thing the runtime path depends on.
16. **There is more than one virtualenv here.** The server runs from `.venv`,
    which was missing `google-genai`, `truststore`, and the spaCy model that
    `backend/venv` had. Symptoms were "AI not configured" in chat and silent
    name-masking loss. Install into the interpreter that actually serves.
17. **Field names are a contract with two ends.** The extraction prompt named
    one field and recomputation consumed seven; `federal_withheld` was in
    neither, so `total_payments` was structurally always zero and no return
    could ever produce a refund. `ENGINE_MONEY_FIELDS` derives the vocabulary
    from the engine's own dataclasses so the two cannot drift.
18–24, 28, 29. **Retired with the retrieval assistant.** These traps were
    about the local-corpus retriever, the crawler and its triage, all deleted
    in the 2026-10-05 rebuild. Their tests went with them. What still applies:
    a default value is the value almost every request uses, so test with what
    the UI actually sends; a broad `except` around a collaborator call hides
    `AttributeError`s — read the log line once before believing the path
    works; `uvicorn --reload` can miss a fix, so restart before concluding it
    failed; and refusing is not a safe default — a *selected* state is
    context that cannot make a federal question unanswerable, while a
    *named* state is a demand.
25. **`LlmResponse` has no `model` attribute.** The old `chat_service` read
    `response.model`, which raised `AttributeError` inside the `try` and fell
    through to the source-quoting fallback — so every successful Gemini chat
    answer was generated, paid for and discarded, and the offline path looked
    like normal behaviour. A broad `except` around a whole generate-and-parse
    block hides this class of bug; keep the fallback, but read fields through
    `_model_label` so a rename cannot reintroduce it.
26. **Do not write regexes through a shell heredoc.** A non-raw Python string
    inside a heredoc double-unescapes: `\b` became a literal backspace byte
    and `\s` became backslash-s. Both compiled, matched nothing, and the
    state-updates panel silently rendered a press-release masthead as its
    summary. Use the file tools for anything containing a backslash. See
    `tests/test_state_panel_and_attachments.py::test_the_state_updates_regexes_actually_compiled`.
    It bit again during the assistant rebuild — twice, on `"\n"` and on a
    test string — so use the file tools, not heredocs, for any edit with a
    backslash in it.
27. **A masking surrogate must never reach the reader.** Somebody asked about
    "John", the surrogate "Joseph Bennett" went to the model — correct — and
    the reply explained the Substantial Presence Test for Joseph Bennett. The
    arithmetic was right and the answer was about a person who does not exist.
    `ChatService` now builds a reverse map from the masking spans (whose
    offsets index the *original* text, so it needs no vault access and cannot
    reach beyond one request) and applies it to what is displayed, never to
    what is stored — the stored row stays masked because `_history` replays it
    to the model. Two things made the first fix insufficient: a model handed
    "Joseph Bennett" writes "Joseph", so surrogate *parts* map too; and a
    surrogate arrives split across stream chunks, so `_Rehydrator` holds back
    the tail and will not cut inside a partial match. Cutting mid-surrogate
    emitted "John Bennett" — half the user's name and half invented, which is
    worse than either. The assistant no longer streams text, so only
    `masking.restore_text` remains (`_Rehydrator` went with the stream). See
    `tests/test_assistant.py::test_identifiers_are_masked_before_the_model_and_restored_for_display`.
28. **Triage was dead for the life of the feature, and nothing said so.**
    `research_triage` read `chunk.final_score`; the retriever calls the field
    `score`. Every call raised `AttributeError`, a broad
    `except Exception: return None` swallowed it, and the deep-research crawl
    therefore never ran once — while `live_source_count` kept reporting
    non-zero from pages an *earlier* crawl had left in the index, so it looked
    like it was working. A bare `except` around a collaborator call needs the
    log line read at least once before the path is believed. The other half of
    the same lesson: `uvicorn --reload` did not pick the fix up, and the
    symptom was identical to the bug; restart before concluding a fix failed.
29. **Refusing is not the safe default — it is just a different failure.** The
    jurisdiction check refused every question naming a state the corpus has no
    passage for: forty-six states, including `"Montana has no sales tax — what
    do I still have to file?"`, which this application *generates as a
    suggestion chip* and then declined. The invariant worth keeping is
    narrower than the refusal was: **never ground a state answer in another
    state's law**, which is enforced by filtering other states out of the
    retrieved set. What remains — the federal rule, the multi-state framework,
    and the state's own structural facts — answers most state questions
    provided the answer says which part is missing, so the gap became a fact
    the prompt and the reply both carry. Two traps inside it: gate the gap on
    `state_code`, not on `state_is_explicit`, or a *selected* state never gets
    the instruction and never triggers the crawl that would fill it; and a
    suggestion is a promise the question is answerable, so
    `test_a_suggested_question_is_always_answerable` asserts it for every
    generated suggestion across twelve states.
30. **A workpaper with no W-2 used to produce no return, and most of the
    corpus has no W-2.** Introduced in `9ea4273`, which is also where traps 31
    and 32 come from — one commit took the corpus from "files with review
    items" to "files nothing, for the wrong stated reason, with no workpaper".
    `TaxpayerProfileService._filing_status` would only
    conclude Single from the absence of a spouse when a *witness* said so — a
    document in `_STATUS_BEARING_DOCUMENTS` (organizer, prior-year return,
    W-2, engagement letter, consent form, IRS notice) that had supplied one of
    the taxpayer's own identity fields. CS 2 is an S-corp/K-1 case with no W-2
    and Basic 4's identity came off 1099s, so `witnesses` was empty, the
    status was undetermined and the orchestrator refused the return — *after*
    OCR, classification and extraction had all succeeded. The screen then said
    "Not enough was readable", which was the wrong reason: 38 figures had been
    read.

    Refusing looks like the conservative choice and is not. A preparer cannot
    correct a return that does not exist, and measured over the corpus the
    refusals took three of nine workpapers (Basic 4, Basic 9, CS 2).
    `_filing_status` refused in three different places and all three now
    resolve to single with a flag:

    - **step 3**, one uncorroborated spouse name. Basic 9's only spouse signal
      is a single name on a single page. It is still not a joint return — that
      remains the expensive error, and `_not_a_married_return` in the tests is
      the property those cases defend — but single is checkable, overstates
      the tax rather than understating it, and a joint return could not be
      filed from those documents anyway because it needs the spouse's SSN.
    - **step 4**, dependents and no spouse. Head of household needs two facts
      about the household that no form reports, so it is never assumed; single
      takes the smaller of the two standard deductions, and the review item
      names the two questions to ask.
    - **steps 5/5b**, absence of a spouse on paperwork with no spouse box.

    What must hold instead is that the inference is never silent and never
    wins over better evidence. Each is a test in
    `tests/test_taxpayer_profile.py`: a stated status, a carried prior-year
    status and a corroborated spouse all still beat it; every inference stays
    below `_RAISE_REVIEW_BELOW` so `_raise_review_items` always speaks, and at
    or below `_FLAGGED_SINGLE_CONFIDENCE` the item is titled "Confirm filing
    status **before filing**"; the evidence string names the specific weakness
    rather than the generic one; and step 6 survives for a workpaper that
    identifies *nobody*, which is a different thing from a household we cannot
    describe.

    This is a *tax-correctness* boundary, so the history matters. Trap 13
    records that defaulting to Single cost one sample return about $15,000 of
    standard deduction, and the old
    `test_identity_from_a_brokerage_form_alone_is_still_undetermined` locked
    the 1099 case down in as many words: "absence of a spouse on a form that
    has no spouse box is not evidence of anything." That is true, and it is
    still not a reason to produce nothing. Two prior authors made the call the
    other way and it was reversed on the owner's explicit instruction, not
    quietly. If it is ever reversed again, that test — now
    `test_identity_from_a_brokerage_form_alone_files_but_never_silently` — is
    the thing to change first, deliberately.
31. **One empty branch, several causes — so say which one.** The pipeline
    refuses in more than one place (no monetary field read, no filing status,
    a missing prior-year return) and each refusal writes a review item naming
    itself. `HomePage` rendered a single hard-coded card for all of them: "Not
    enough was readable. No tax figures could be read from this file." On the
    filing-status refusal every figure *had* been read, so the screen sent the
    preparer to check the OCR on a workpaper whose OCR was fine. `NoReturn`
    now renders the workflow's own blocking review items, filtered to the
    titles that say a refusal ("… not computed", "… could not …") — the rest
    of the queue is figures to verify on a return that *did* compute, and
    ninety of those would bury the one line that matters. A fixed string
    standing in for a reason is a bug even when the string is reassuring.

    Fetching them has one trap. `/api/review/queue` returns the oldest 100 of
    every pending item in the database — 1,872 of them in the dev database —
    so asking for the queue and filtering by `workflow_id` in the browser
    returns nothing at all for the run that just finished, and the card
    silently falls back to "no reason was recorded". The endpoint takes
    `workflow_id`; pass it.

    The same defect in miniature, on the item that fires most:
    `assess_field_confidence` has three checks and the review item described
    only one of them, so a field read at 95% off a page whose OCR scored 41%
    said "Extracted with 95% confidence, below the 90% threshold", and
    handwriting — floor 95% — said "below the 90% threshold" at 90%. Sixty to
    ninety self-contradicting items per workpaper, which is how a reviewer
    learns to ignore the queue. `_why_this_field_needs_checking` mirrors the
    three branches in order; see `tests/test_review_item_reasons.py`.
32. **A renderer fed extraction output is being fed transcription.** The
    workpaper's Source Documents sheet prints every extracted field's value,
    and not every extracted field is money — a filing status, a name and a
    date of birth land in the same table. The amount column coerced each with
    `float(Decimal(str(value)))`, so one name raised `InvalidOperation`, the
    caller's `except Exception` logged "Consolidated workpaper not built" and
    returned `None`, and **every** document in the sample corpus shipped a
    package with no workpaper in it. `_number` returns `None` rather than zero
    for a non-figure, because zero in a money column is itself a figure. The
    log line had been there all along and named neither the sheet nor the
    value; it now carries `exc_info`. Transcription is "1,234.00", "$5,000",
    "(320)" and "N/A" at least as often as it is a clean decimal.

    There was a **second** defect directly behind it, which is the part worth
    remembering. `_build_consolidated_workpaper` returned
    `OutputArtifactType.WORKPAPER`, which is not a member — it is
    `COMPLETED_WORKPAPER` — and that line sits *after* the `try`, so fixing
    the coercion made the builder succeed, the `AttributeError` escaped, and
    the whole output stage failed where it had previously only logged. A
    branch that has never once run is not tested code, whatever it looks
    like; expect the next thing along it to be broken too, and re-run the
    corpus rather than the one file you were chasing.
    `test_every_artifact_type_named_in_a_service_is_a_real_member` pins the
    class of typo. See `tests/test_consolidated_workpaper_robustness.py`.
33. **Turning a refusal into an answer switches on code that never ran.**
    Trap 30 made an uncorroborated spouse name resolve to single instead of
    refusing. Two things downstream had been written against the refusal and
    were wrong the moment it stopped happening, and neither would have shown
    up as an error:

    - `TaxpayerProfileResult.seniors` counted everyone over 65 and the engine
      adds one senior amount per count, so a spouse date of birth that had
      *failed* to establish a marriage still bought a second addition — about
      2,000 of deduction for a person the return says is not there. It now
      counts entitlements: the spouse only on a joint return, not on married
      filing separately (each takes their own) and not on qualifying
      surviving spouse (the additional amount is the survivor's alone).
      `_seniors_in_household` in the orchestrator had the same bug and feeds
      the explanation, so the screen and the arithmetic would have described
      different households.
    - `build_identity_from_facts` copies whatever extraction found, so
      `Form1040Filler` would have printed the spouse's name and SSN in the
      boxes at the top of a *single* return. `fill` drops those three boxes
      unless the status is joint or separate; the workpaper's heading does the
      same.

    The general form: when a guard stops refusing, everything it was
    protecting starts executing. Grep for the fields the refusal made
    unreachable — here `spouse_*` — and check each consumer, because the type
    checker cannot see this and the tests did not cover it.
34. **`documents[0]` was the source of every extracted fact.** The persist
    loop set `document = primary_document` for all of them, so each
    `ExtractionResult` recorded provenance it did not have — and "which
    document and page did this figure come off" is the question the workpaper
    exists to answer, on the sheet a preparer signs against. The knock-on was
    bigger than the mislabelling: `assess_field_confidence` reads that row's
    `ocr_mean_confidence` and `is_handwritten`, so one handwritten organizer
    page at the head of an unordered query result marked all 84 figures on
    Basic 7 as needing review, most of them off pages read cleanly. Ninety
    queue items, nearly all wrong, is a queue nobody reads — and the banner
    counting them is the first thing on the screen. `_source_document_types`
    maps each field to the document type that reported it, from
    `field_provenance` and `scalar_candidates`, and `_pick_document` splits
    several documents of one type by page. Measured on Basic 7: 99 review
    items before, 29 after — a per-fact flag rate of 98% down to 32%, on runs
    with comparable extraction counts. See
    `tests/test_extraction_integrity.py`.

35. **Search grounding plus a response schema in one call is not reliable.**
    The Gemini API accepts both on one request, and the first version of the
    rebuilt assistant used them together. Against the live API it failed two
    ways, intermittently, on every Flash model tried (3.6, 3.7, 3.8): the JSON
    came back with a span missing from the middle (`"next_steps":.",`) about
    one call in four to six, and the model sometimes skipped searching and
    answered a well-known question from memory with no grounding metadata.
    The first full eval run passed 27 of 40, and all 13 failures were these.
    Grounded *free text* searched on twelve of twelve probe calls, and schema
    output *without* tools is constrained decoding. So every attempt is two
    calls: research (search on, notes) then structure (schema, no tools), with
    grounding supports marked into the notes as `[n]` so citations survive.
    The same 40 cases then passed 40/40, every one on its first attempt.
    **Superseded 2026-10-09:** two long generations in series meant a 34 s
    median with nothing on screen until the end. Now each attempt is one
    grounded *free-text* call, streamed - the path that searched 12/12 - and
    what the schema carried for software (tax year, scope) is a one-line
    `META:` header the stream holds back (`answer_text.MetaFilter`). Do not
    put the response schema back on the grounded call. See
    `assistant/gemini_client.py`.
36. **Model output that goes back out needs the source scrub.** It quotes
    public pages, which carry agency emails the egress guard rightly blocks
    (trap 5). This was the research notes when there were two calls; now it
    is the assistant turns replayed as history (`_history`). Scrub only the
    assistant's turns with `redact_blocking_patterns` - never the user's own
    text and never client document text.
37. **A skipped search is a coin toss, not a content error.** The same prompt
    searched on one run and not the next, so spending the single content
    regeneration on it turned well-grounded questions into fallbacks. An
    attempt whose *only* failure is `ungrounded` gets one extra attempt
    (`GROUNDING_RETRIES`); state and tax-year failures still get exactly one
    regeneration. Giving the model concrete opening searches in
    the prompt (`_search_starts`) also helped.
38. **A deadline can move twice.** April 15, 2028 is a Saturday, and DC
    Emancipation Day (Sunday the 16th) is observed Monday the 17th, so
    returns are due Tuesday the 18th - not Monday, which is what the first
    hand-written test expected. IRC 7503 counts *observed* DC legal holidays.
    Never hand-compute an expected deadline; check it against the holiday
    file the engine reads (see `frontend/src/__tests__/dates.test.ts`).
39. **"no_income_tax" is not the same as verified.** Several conformity
    entries say `no_income_tax` with `last_verified: null` because the
    researcher could not confirm that year (the agency site returned 403).
    State Intelligence treats an undated entry as "Not yet verified"
    (`state_intel_service.conformity_is_verified`). The global stylesheet
    also already owns `.tile` and `.update-item` (the assistant's state
    panel); new sections use `cd-tile` / `upd-item`, and a collision showed up
    only as overlapping layout, not as an error.
40. **A page that mentions the words is not a page that states the fact.**
    The first bulk State Intelligence run kept a field when one evidence
    phrase and every number in it appeared somewhere on the state's page. A
    Michigan depreciation FAQ "confirmed" an unrelated field, and Colorado's
    individual-filing page "confirmed" a C-corporation due date of May 15
    that it never states - the only number in a date is the day, and "15"
    is on every tax page. `research_state_intel.verify` now needs two
    phrases, every month-day date on the page, and the key figure inside the
    quoted sentence. `--reverify` re-checks stored runs with no model calls;
    use it after any rule change. See `tests/test_research_state_intel.py`.
41. **A fake that lacks a method makes a broad `except` look like a feature.**
    The first router caught every exception and fell back to the general
    policy. The test fake had no `generate`, so every route raised
    `AttributeError`, fell back, and all 96 tests passed with the router never
    having run once - trap 28 again, in a new module. The router now catches
    only `LlmError` and bad replies, and the fake answers router calls. When a
    collaborator call is "optional", assert in a test that it actually ran.
42. **An eval that does not meter reports a cost of zero.** `run_eval` built
    `GeminiService()` without the meter, so every case cost "$0" and the
    first baseline has no token counts. It now meters as the API route does
    (`deps.get_gemini_service`). Separately, `llm_prices.json` has no price
    for `gemini-3.8-flash`, and the meter deliberately never estimates - so
    compare runs on tokens, and add the price when it is published.
43. **Time to first token is thinking plus search, not generation.** With
    default thinking the answer call spent ~1,500 tokens thinking before the
    first word; `thinking_level=low` halved time to first token with the same
    eval correctness and, unexpectedly, no skipped searches (4 with default).
    What remains (~9 s) is the router (~1.4 s) and Google Search itself.
    Re-run the A/B (`ASSISTANT_THINKING_LEVEL`) after any model change.
44. **Three totals for one tax, each looking checked.** A Maine answer
    (2026-10-11) led with $3,374.88, totalled its steps to $3,411.70 and
    noted $3,411.50 - and used the September 2025 standard deduction Maine
    had revised in May 2026. Nothing checked the model's own arithmetic.
    `assistant/arithmetic.py` now recomputes every step the answer shows and
    compares the lead with the total line (regenerate once, then the
    fallback); it never supplies a figure (rule 8), leaves alone anything it
    cannot parse, and puts only numbers - never model words - in the
    correction. A superseded source cannot be caught deterministically; the
    prompt asks for the latest revision and the state search includes the
    year. The same answer also showed "4Federal": `clean()` collapsed
    `*   item` to `* item`, so grounding spans stopped matching and one
    landed between a bullet and `**bold**`. Marker placement now matches on
    flattened text and never inserts at a line start. See
    `tests/test_assistant_arithmetic.py`.
45. **One default year, set once.** The shared selector, the depreciation
    calculator, the assistant and the workpaper pipeline each worked out
    "the current year" from the clock, and disagreed (2025 vs 2026).
    `DEFAULT_TAX_YEAR` is the only source; each product clamps it to the
    years its rules cover (`core/tax_year.py`), and an assumed or clamped
    year is always said - a review item on a workpaper, `fallback=yes` and
    a server-written notice on an assistant answer. Do not add another
    `today.year - 1`.

## Conventions

- Python 3.11, `from __future__ import annotations`, full type hints.
- Pydantic v2 for every boundary (HTTP, LLM I/O, config).
- Services are classes with constructor-injected dependencies; routes stay thin.
- Money is `Decimal` inside the tax engine, never `float`. Serialize as string.
- Errors: raise `core.errors.AppError` subclasses; the handler maps to HTTP.
- Mark security-relevant code with a `# SECURITY:` comment explaining the
  invariant, so a later reader knows what not to "simplify".
- Frontend look and feel follows `frontend/DESIGN.md` (obsidian, dark-first;
  emerald = verified/primary, cyan = AI/intelligence, amber = deadlines only;
  Inter for prose, JetBrains Mono for figures and pill labels). Colours are
  tokens in the two blocks at the top of `src/styles.css`; e2e runs axe
  contrast in both themes, so check a new colour pairing there first.

## Commands

```bash
# Backend
python -m pip install -r backend/requirements.txt
python -m spacy download en_core_web_sm
cd backend && uvicorn app.main:app --reload --port 8000

# Tests / QA
cd backend && python -m pytest -q
cd backend && python -m pytest -m security -q     # privacy invariants only
cd backend && python -m ruff check app tests
cd backend && python -m mypy app

# Frontend
cd frontend && npm install && npm run dev
```

## External dependencies

- **Tesseract OCR** is required — the sample corpus is scanned images with no
  text layer. `winget install --id UB-Mannheim.TesseractOCR`, then set
  `TESSERACT_CMD`. Without it, scanned pages are marked `OCR_UNAVAILABLE` and
  routed to human review. They are **not** auto-sent to a cloud OCR service.
- **Gemini API key** is optional. With `GEMINI_ENABLED=false` the app runs fully
  on deterministic stubs — useful for CI and offline demos.
- **Gemini with Google Search grounding** is required for the assistant;
  without a key it says it is unavailable. `ASSISTANT_MODEL` is the only place
  its model is named.
- **Outbound network** from this host is used by the state updates panel
  (`public_web_fetcher`: SSRF checks, the state's own domains only, per-host
  politeness) and, when `ASSISTANT_RESOLVE_SOURCE_URLS` is on, one
  header-only request per citation to Google's grounding redirect host.
  `STATE_UPDATES_ENABLED=false` makes the panel show the agency's own links
  rather than an empty list — "nothing published" and "we could not look"
  are different facts. No test makes a network call.

## Testing notes

- Tests must never contain real PII. There is no `tests/fixtures/synthetic.py`
  despite earlier guidance here; write clearly invented values inline, and
  prefer the reserved surrogate ranges the egress guard already recognises
  (SSN 666-xx-xxxx, `@example.com`, 555-01xx).
- `tests/test_security_invariants.py` is the guard rail suite: masking
  round-trip, egress guard, log redaction, vault isolation. If a change breaks
  one of those, the change is wrong — not the test.
- `tests/test_assistant.py` is the assistant's equivalent, with Gemini
  mocked: state allow-list and detection, jurisdiction resolution, prompt
  contents, schema, every validator, citations from grounding only,
  regenerate-once and fallback, state switching, tax-year carry-over, and the
  privacy boundary (masking before egress through the real gateway, no text
  in logs, an attachment never reaching another conversation).
  `tests/test_state_panel_and_attachments.py` covers the kept state updates
  panel and attachment storage.
- `python -m evals.assistant.run_eval` runs the 40-case eval set against the
  live API and writes `evals/assistant/REPORT.md`. Unit tests cannot catch
  provider behaviour (trap 35 passed every mocked test); run the eval after
  changing a prompt or `ASSISTANT_MODEL`.
