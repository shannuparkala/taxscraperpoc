# Form 1040 (2025) — line-by-line structure

Tax year: **2025** (returns filed in the 2026 filing season). Enacted law only;
nothing proposed is included below.

Two figures on this form are a direct hit on the "two layers" trap: the
standard-deduction amounts printed in the margin of page 2 are the **OBBBA**
(Pub. L. 119-21, §70102) amounts, not the Rev. Proc. 2024-40 amounts announced
in October 2024 ($15,000 / $30,000 / $22,500). The IRS reprinted the form with
the post-OBBBA figures baked in, so there is no discrepancy to reconcile on the
form itself — but a note or a prompt that cites Rev. Proc. 2024-40 alone for
2025 standard deduction would be wrong. Cross-checked against
`backend/app/tax_constants/2025.json` (`standard_deduction.single` /
`married_joint` / `head_of_household`): all three values match the form
exactly and are already attributed to OBBBA §63(c)(2) there, `verify: true`.
No engine change proposed — existing constants confirmed correct.

## Sources

- **Form 1040 (2025)**, U.S. Individual Income Tax Return — primary source for
  every line's official wording and its schedule/form cross-references. Read
  directly (both pages) via the PDF's extracted text, not a summary.
  https://www.irs.gov/pub/irs-pdf/f1040.pdf — Cat. No. 11320B, form footer
  reads "Created 9/5/25".
- **Instructions for Form 1040 (2025)** (general instructions, catalog no.
  24811V) — source for the "Rounding Off to Whole Dollars" rule.
  https://www.irs.gov/instructions/i1040gi (HTML) /
  https://www.irs.gov/pub/irs-pdf/i1040gi.pdf. Per a live web search snippet,
  this edition is dated Feb 25, 2026 on IRS.gov (post-filing-season update
  cycle); watch `https://www.irs.gov/forms-pubs/changes-to-the-2025-instructions-for-form-1040`
  for errata.

`figures_as_of: 2026-09-22` (date this note was written) for every figure
below unless stated otherwise. `figures_source_url` is the URL given for each
item.

## Rounding instruction — status: verify (wording only)

**Substance (high confidence):** whole-dollar rounding is optional but
all-or-nothing — if you round any amount on the return, every amount on the
return and its schedules must be rounded. Round to the nearest dollar; cents
of 50 or more round up, cents under 50 round down. When a line is the sum of
several amounts, keep the cents through the addition and round only the
final total.

**Verbatim text — not independently pinned in this session.** This tool's
web fetch of the general instructions produced two non-identical paraphrases
of the same section on two separate fetches (different example dollar
amounts each time), which means the underlying long document was likely
truncated before reaching the model that answered, not that the section
doesn't exist — a third fetch correctly reported that a *different*, shorter
document (Schedule B instructions) does **not** contain this section, which
the same tool got right. The general-instructions PDF is too large for this
environment's PDF reader (`pdftoppm`/poppler is not installed here, so the
`pages`-range path errors on any multi-page PDF over the tool's no-page-range
threshold; only the 2-page Form 1040 itself was small enough to read directly
as a document). Recommend re-confirming the exact sentence the next time
someone has either a working local PDF renderer or can open
`i1040gi.pdf` directly, and citing the specific page number then.
Citation for the rule as stated above: Instructions for Form 1040 (2025),
"Rounding Off to Whole Dollars" — https://www.irs.gov/instructions/i1040gi.
Schedule D and Form 8949 each carry their own, near-identical verbatim
version of this same rule on their own faces' instructions — quoted in
`docs/tax-research/schedule-b-d-8949-2025-line-by-line.md` — which corroborates
the substance above without resolving this item's open citation, since
those are each schedule's own paragraph, not this general-instructions one.

## Standard deduction amounts printed on the form (2025)

| Filing status | Amount | Authority |
|---|---|---|
| Single or Married filing separately | $15,750 | OBBBA, Pub. L. 119-21 §70102, amending IRC §63(c)(2) |
| Married filing jointly or Qualifying surviving spouse | $31,500 | same |
| Head of household | $23,625 | same |

Source: Form 1040 (2025) p.2 margin box "Standard deduction for—".
https://www.irs.gov/pub/irs-pdf/f1040.pdf. If a box is checked on line
12a-12d (someone can claim you/spouse as a dependent, spouse itemizes
separately, dual-status alien, born before Jan 2 1961, or blind), the form
says "see inst." — the additional-amount table for age/blindness lives in the
general instructions, not on the form itself; not pulled in this pass.

## Every numbered/lettered line, in order, with official wording and its feed

Wording is quoted from the form as printed; "→" shows what schedule/form the
line pulls from or attaches. Lines with no "→" are computed from other Form
1040 lines only.

### Above the numbered lines (structural, not money)
- Filing status checkboxes: Single / Married filing jointly / Married filing
  separately (MFS, enter spouse's SSN + name) / Head of household (HOH, enter
  qualifying child's name if not your dependent) / Qualifying surviving spouse
  (QSS).
- Nonresident/dual-status alien spouse treated as a U.S. resident — checkbox
  + name, "attach statement if required."
- Digital Assets question (Yes/No) — receipt or disposal of a digital asset
  during 2025.
- Dependents table (up to 4 named; a checkbox covers "more than four,"
  directing to the instructions) — each dependent has SSN, relationship,
  "lived with you more than half of 2025," full-time student / permanently
  and totally disabled, and which credit (child tax credit vs. credit for
  other dependents) is claimed for them.
- Checkbox: filing status MFS or HOH **and** lived apart from spouse the last
  6 months of 2025, or legally separated under a state decree, and did not
  live with spouse at year end — this is the gateway condition for treating
  an MFS/HOH filer as unmarried for certain computations.

### Income
- **1a** "Total amount from Form(s) W-2, box 1 (see instructions)"
- **1b** "Household employee wages not reported on Form(s) W-2"
- **1c** "Tip income not reported on line 1a (see instructions)"
- **1d** "Medicaid waiver payments not reported on Form(s) W-2 (see
  instructions)"
- **1e** "Taxable dependent care benefits from Form 2441, line 26" → Form 2441
- **1f** "Employer-provided adoption benefits from Form 8839, line 31" → Form
  8839
- **1g** "Wages from Form 8919, line 6" → Form 8919
- **1h** "Other earned income (see instructions). Enter type and amount:"
- **1i** "Nontaxable combat pay election (see instructions)" — informational;
  **excluded** from the 1z sum (see next line — 1z sums only 1a-1h)
- **1z** "Add lines 1a through 1h"
- **2a** "Tax-exempt interest" / **2b** "Taxable interest" — margin note
  "Attach Sch. B if required" covers 2a through 3b → **Schedule B line 4**
  feeds 2b; full Schedule B line-by-line wording is now in
  `docs/tax-research/schedule-b-d-8949-2025-line-by-line.md`.
- **3a** "Qualified dividends" / **3b** "Ordinary dividends" → **Schedule B
  line 6** feeds 3b (same note as above)
- **3c** (unlettered on face, follows 3b) "Check if your child's dividends
  are included in [1] Line 3a [2] Line 3b"
- **4a** "IRA distributions" / **4b** "Taxable amount"
- **4c** "Check if (see instructions) [1] Rollover [2] QCD [3]___"
- **5a** "Pensions and annuities" / **5b** "Taxable amount"
- **5c** "Check if (see instructions) [1] Rollover [2] PSO [3]___"
- **6a** "Social security benefits" / **6b** "Taxable amount"
- **6c** "If you elect to use the lump-sum election method, check here (see
  instructions)"
- **6d** "If you are married filing separately and lived apart from your
  spouse the entire year (see inst.), check here"
- **7a** "Capital gain or (loss). Attach Schedule D if required" → **Schedule
  D line 16 (gain), line 21 (loss, capped $3,000/$1,500), or -0- (zero)** —
  full detail, including the Form 8949→Schedule D box map and the capital-loss
  carryover worksheet, is in
  `docs/tax-research/schedule-b-d-8949-2025-line-by-line.md`.
- **7b** "Check if: [ ] Schedule D not required [ ] Includes child's capital
  gain or (loss)"
- **8** "Additional income from Schedule 1, line 10" → Schedule 1
- **9** "Add lines 1z, 2b, 3b, 4b, 5b, 6b, 7a, and 8. This is your **total
  income**"
- **10** "Adjustments to income from Schedule 1, line 26" → Schedule 1
- **11a** "Subtract line 10 from line 9. This is your **adjusted gross
  income**"

### Tax and Credits (page 2 — starts by repeating 11a as 11b)
- **11b** "Amount from line 11a (adjusted gross income)"
- **12a** "Someone can claim [ ] You as a dependent [ ] Your spouse as a
  dependent"
- **12b** "Spouse itemizes on a separate return"
- **12c** "You were a dual-status alien"
- **12d** "You: [ ] Were born before January 2, 1961 [ ] Are blind — Spouse:
  [ ] Was born before January 2, 1961 [ ] Is blind"
- **12e** "Standard deduction or itemized deductions (from Schedule A)" →
  Schedule A if itemizing
- **13a** "Qualified business income deduction from Form 8995 or Form
  8995-A" → Form 8995 / 8995-A
- **13b** "Additional deductions from Schedule 1-A, line 38" → Schedule 1-A
  (new for 2025 — OBBBA's above-the-line items: no tax on tips, no tax on
  overtime, senior deduction, auto-loan interest, etc.; matches the repo's
  recent "Implement Schedule 1-A" work)
- **14** "Add lines 12e, 13a, and 13b"
- **15** "Subtract line 14 from line 11b. If zero or less, enter -0-. This is
  your **taxable income**"
- **16** "Tax (see instructions). Check if any from Form(s): [1] 8814 [2]
  4972 [3]___" → Form 8814 and/or Form 4972 alter the line-16 computation;
  the unlabeled box 3 could not be confirmed against the extracted text in
  this pass — **status: verify** (historically Schedule J, income averaging
  for farmers/fishermen; not re-confirmed for 2025 here)
- **17** "Amount from Schedule 2, line 3" → Schedule 2 (AMT + excess advance
  PTC repayment subtotal)
- **18** "Add lines 16 and 17"
- **19** "Child tax credit or credit for other dependents from Schedule
  8812" → Schedule 8812
- **20** "Amount from Schedule 3, line 8" → Schedule 3 (nonrefundable
  credits subtotal)
- **21** "Add lines 19 and 20"
- **22** "Subtract line 21 from line 18. If zero or less, enter -0-"
- **23** "Other taxes, including self-employment tax, from Schedule 2, line
  21" → Schedule 2
- **24** "Add lines 22 and 23. This is your **total tax**"

### Payments and Refundable Credits
- **25a** "Form(s) W-2" (federal income tax withheld)
- **25b** "Form(s) 1099"
- **25c** "Other forms (see instructions)"
- **25d** "Add lines 25a through 25c"
- **26** "2025 estimated tax payments and amount applied from 2024 return" —
  plus a line to enter a former spouse's SSN if estimated payments were made
  jointly with them in 2025
- **27a** "Earned income credit (EIC)" → Schedule EIC attaches if there's a
  qualifying child ("If you have a qualifying child, you may need to attach
  Sch. EIC")
- **27b** "Clergy filing Schedule SE (see instructions)" → Schedule SE
- **27c** "If you do not want to claim the EIC, check here"
- **28** "Additional child tax credit (ACTC) from Schedule 8812. If you do
  not want to claim the ACTC, check here" → Schedule 8812
- **29** "American opportunity credit from Form 8863, line 8" → Form 8863
- **30** "Refundable adoption credit from Form 8839, line 13" → Form 8839
- **31** "Amount from Schedule 3, line 15" → Schedule 3 (refundable
  credits/other payments subtotal)
- **32** "Add lines 27a, 28, 29, 30, and 31. These are your total other
  payments and refundable credits"
- **33** "Add lines 25d, 26, and 32. These are your **total payments**"

### Refund
- **34** "If line 33 is more than line 24, subtract line 24 from line 33.
  This is the amount you overpaid"
- **35a** "Amount of line 34 you want refunded to you. If Form 8888 is
  attached, check here" → Form 8888 (refund allocation/bonds) if split
- **35b** "Routing number" / **35c** "Type: [ ] Checking [ ] Savings" /
  **35d** "Account number"
- **36** "Amount of line 34 you want applied to your 2026 estimated tax"

### Amount You Owe
- **37** "Subtract line 33 from line 24. This is the amount you owe. For
  details on how to pay, go to www.irs.gov/Payments or see instructions"
- **38** "Estimated tax penalty (see instructions)"

### Administrative (not numbered lines)
Third Party Designee; Sign Here (signature, date, occupation, Identity
Protection PIN box for each spouse, phone, email); Paid Preparer Use Only.

## Edge cases / interactions worth flagging for engine work

- **1z deliberately excludes 1i.** Nontaxable combat pay is an election
  disclosure, not income; summing it into 1z would overstate total income.
- **7b's "Schedule D not required" checkbox** means capital gain can flow to
  line 7a from Form 8949/Qualified Dividends and Capital Gain Tax Worksheet
  logic without a full Schedule D attachment in some cases — worth its own
  research pass if the engine needs the exact threshold conditions. Note this
  is a *different* condition from Form 8949's "Exception 1" (which governs
  whether Form 8949 itself is needed once Schedule D is already being filed);
  both live in `docs/tax-research/schedule-b-d-8949-2025-line-by-line.md`, but
  the exact 7b checkbox condition itself is still unconfirmed from primary
  text — see that note's open questions.
- **Line 16's "Tax (see instructions)"** is itself a worksheet dispatch (Tax
  Table, Tax Computation Worksheet, Qualified Dividends and Capital Gain Tax
  Worksheet, or Schedule D Tax Worksheet) — the form gives no formula, only
  "see instructions." Partially resolved:
  `docs/tax-research/schedule-b-d-8949-2025-line-by-line.md` now covers the
  Schedule D Tax Worksheet in full (47 lines, including the 2025 rate
  breakpoints) and the Schedule D lines (17/20/22) that choose between it and
  the Qualified Dividends and Capital Gain Tax Worksheet. The QDCGT Worksheet
  itself still hasn't been fetched — it lives in `i1040gi.pdf`, the same large
  document this note's rounding item couldn't get past.
- **Schedule 1-A is new for 2025** (OBBBA). Its own line-by-line detail is
  out of scope for this note — see the repo's Schedule 1-A implementation
  commit for what's already built; a dedicated research pass on Schedule
  1-A's 38 lines would be a natural follow-up if not already cached.

## Open questions / follow-ups

1. Verbatim text of "Rounding Off to Whole Dollars" — needs a direct primary
   read (see status above).
2. Line 16 checkbox 3 label — could not confirm from the extracted form text.
3. Schedule 1, 2, and 3's own line-by-line wording is now covered in
   `docs/tax-research/schedule-1-2-3-2025-line-by-line.md` (every line,
   sub-line, and Form-1040 cross-reference for all three, read directly off
   the primary PDFs). Schedule 1-A's line-by-line wording is still not
   covered by any note here.
4. Schedule B, Schedule D, and Form 8949's own line-by-line wording —
   including the capital-loss limitation, the capital-loss carryover
   worksheet, and how Form 8949 totals flow into Schedule D — is now covered
   in `docs/tax-research/schedule-b-d-8949-2025-line-by-line.md`. The
   Qualified Dividends and Capital Gain Tax Worksheet (Form 1040 line 16) is
   still not covered by any note here.

status: confirmed (line wording, schedule/form cross-references, standard
deduction amounts — all read directly off the primary PDF) / verify (rounding
verbatim text; line 16 box 3 label)
