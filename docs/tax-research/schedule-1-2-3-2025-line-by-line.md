# Schedule 1, 2, and 3 (Form 1040, 2025) — line-by-line structure

Tax year: **2025** (returns filed in the 2026 filing season). Enacted law only;
nothing proposed is included below.

Companion note to `form-1040-2025-line-by-line.md`, which covers the 1040
face only and explicitly deferred these three schedules ("Worth a follow-up
note per schedule if the engine needs their internals").

## Sources

- **Schedule 1 (Form 1040) 2025**, Additional Income and Adjustments to
  Income. https://www.irs.gov/pub/irs-pdf/f1040s1.pdf — Cat. No. 71479F,
  form footer "Created 7/25/25" (three weeks after OBBBA's 7/4/25
  enactment).
- **Schedule 2 (Form 1040) 2025**, Additional Taxes.
  https://www.irs.gov/pub/irs-pdf/f1040s2.pdf — Cat. No. 71478U, footer
  "Created 5/8/25" (**before** OBBBA enactment — see caveat below).
- **Schedule 3 (Form 1040) 2025**, Additional Credits and Payments.
  https://www.irs.gov/pub/irs-pdf/f1040s3.pdf — Cat. No. 71480G, footer
  "Created 11/17/25".

All three read directly from the extracted PDF text (both pages of each),
not a summary or a third-party transcription.

`figures_as_of: 2026-09-22` (date this note was written). `figures_source_url`
is the applicable schedule's URL above.

## Two-layer check (Rev. Proc. 2024-40 vs. OBBBA)

None of the three schedules prints an inflation-adjusted dollar figure on
its face (unlike Form 1040's standard-deduction margin box). The **only**
dollar amount printed anywhere on the three forms is the static $150,000
sales-price threshold on Schedule 2, line 15 — a fixed statutory number, not
inflation-indexed — so there is no Rev. Proc. 2024-40-vs-OBBBA figure to
reconcile on these forms' faces themselves.

That does **not** mean the schedules are untouched by OBBBA: several lines
are cross-references into forms whose *internals* OBBBA changed (Form 6251's
AMT exemption/phaseout under OBBBA §70307 feeds Schedule 2 line 2; the §30D
clean-vehicle credit OBBBA §70501 terminated for post-9/30/2025 acquisitions
feeds Schedule 2 lines 1b/1c and Schedule 3 lines 6f/6m). Schedule 2's own
PDF predates the enactment date by about two months, which is consistent
with its face wording being unaffected (additions/other-taxes structure, not
a rate or threshold) rather than evidence the IRS missed something — but it
is flagged here so nobody assumes the two-layer risk was checked for the
forms *behind* these lines. Not researched further in this pass.

## Schedule 1 (Form 1040) 2025 — Additional Income and Adjustments to Income

Attachment Sequence No. 01.

**Unnumbered reconciliation line** (above Part I, informational only — not
summed into any total): "For 2025, enter the amount reported to you on
Form(s) 1099-K that was included in error or for personal items sold at a
loss." Followed by: "Note: The remaining amounts reported to you on Form(s)
1099-K should be reported elsewhere on your return depending on the nature
of the transaction. See www.irs.gov/1099k."

### Part I — Additional Income
- **1** "Taxable refunds, credits, or offsets of state and local income taxes"
- **2a** "Alimony received" / **b** "Date of original divorce or separation
  agreement (see instructions)"
- **3** "Business income or (loss). Attach Schedule C" → Schedule C
- **4** "Other gains or (losses). Check if any from Form(s): [ ] 4797 [ ]
  4684" → Form 4797 / Form 4684
- **5** "Rental real estate, royalties, partnerships, S corporations,
  trusts, etc. Attach Schedule E" → Schedule E
- **6** "Farm income or (loss). Attach Schedule F" → Schedule F
- **7** "Unemployment compensation. If you repaid a 2025 overpayment (see
  instructions), check here and enter amount repaid:"
- **8** "Other income:" (header for 8a–8z)
  - **a** "Net operating loss" *(printed with surrounding parentheses —
    negative entry)*
  - **b** "Gambling"
  - **c** "Cancellation of debt"
  - **d** "Foreign earned income exclusion from Form 2555" *(parentheses)* →
    Form 2555
  - **e** "Income from Form 8853" → Form 8853
  - **f** "Income from Form 8889" → Form 8889
  - **g** "Alaska Permanent Fund dividends"
  - **h** "Jury duty pay"
  - **i** "Prizes and awards"
  - **j** "Activity not engaged in for profit income"
  - **k** "Stock options"
  - **l** "Income from the rental of personal property if you engaged in the
    rental for profit but were not in the business of renting such
    property"
  - **m** "Olympic and Paralympic medals and USOC prize money (see
    instructions)"
  - **n** "Section 951(a) inclusion (see instructions)"
  - **o** "Section 951A(a) inclusion (see instructions)"
  - **p** "Section 461(l) excess business loss adjustment"
  - **q** "Taxable distributions from an ABLE account (see instructions)"
  - **r** "Scholarship and fellowship grants not reported on Form W-2"
  - **s** "Nontaxable amount of Medicaid waiver payments included on Form
    1040, line 1a or 1d" *(parentheses)*
  - **t** "Pension or annuity from a nonqualified deferred compensation plan
    or a nongovernmental section 457 plan"
  - **u** "Wages earned while incarcerated"
  - **v** "Digital assets received as ordinary income not reported
    elsewhere. See instructions"
  - **z** "Other income. List type and amount:" (write-in)
- **9** "Total other income. Add lines 8a through 8z"
- **10** "Combine lines 1 through 7 and 9. This is your additional income.
  Enter here and on Form 1040, 1040-SR, or 1040-NR, line 8" → **Form 1040
  line 8**

### Part II — Adjustments to Income
- **11** "Educator expenses"
- **12** "Certain business expenses of reservists, performing artists, and
  fee-basis government officials. Attach Form 2106" → Form 2106
- **13** "Health savings account deduction. Attach Form 8889" → Form 8889
- **14** "Moving expenses for members of the Armed Forces. Attach Form 3903.
  If claiming only storage fees (see instructions), check here" → Form 3903
- **15** "Deductible part of self-employment tax. Attach Schedule SE" →
  Schedule SE
- **16** "Self-employed SEP, SIMPLE, and qualified plans"
- **17** "Self-employed health insurance deduction"
- **18** "Penalty on early withdrawal of savings"
- **19a** "Alimony paid" / **b** "Recipient's SSN" / **c** "Date of original
  divorce or separation agreement (see instructions)"
- **20** "IRA deduction. If you are married filing separately and lived
  apart from your spouse for the entire year (see instructions), check
  here"
- **21** "Student loan interest deduction"
- **22** "Reserved for future use"
- **23** "Archer MSA deduction"
- **24** "Other adjustments:" (header for 24a–24z)
  - **a** "Jury duty pay (see instructions)"
  - **b** "Deductible expenses related to income reported on line 8l from
    the rental of personal property engaged in for profit"
  - **c** "Nontaxable amount of the value of Olympic and Paralympic medals
    and USOC prize money reported on line 8m"
  - **d** "Reforestation amortization and expenses"
  - **e** "Repayment of supplemental unemployment benefits under the Trade
    Act of 1974"
  - **f** "Contributions to section 501(c)(18)(D) pension plans"
  - **g** "Contributions by certain chaplains to section 403(b) plans"
  - **h** "Attorney fees and court costs for actions involving certain
    unlawful discrimination claims (see instructions)"
  - **i** "Attorney fees and court costs you paid in connection with an
    award from the IRS for information you provided that helped the IRS
    detect tax law violations"
  - **j** "Housing deduction from Form 2555" → Form 2555
  - **k** "Excess deductions of section 67(e) expenses from Schedule K-1
    (Form 1041)" → Schedule K-1 (Form 1041)
  - **z** "Other adjustments. List type and amount:" (write-in)
- **25** "Total other adjustments. Add lines 24a through 24z"
- **26** "Add lines 11 through 23 and 25. These are your adjustments to
  income. Enter here and on Form 1040, 1040-SR, or 1040-NR, line 10" →
  **Form 1040 line 10**

## Schedule 2 (Form 1040) 2025 — Additional Taxes

Attachment Sequence No. 02.

### Part I — Tax
- **1** "Additions to tax:" (header for 1a–1y)
  - **a** "Excess advance premium tax credit repayment. Attach Form 8962" →
    Form 8962
  - **b** "Repayment of new clean vehicle credit(s) transferred to a
    registered dealer from Schedule A (Form 8936), Part II. Attach Form
    8936 and Schedule A (Form 8936)"
  - **c** "Repayment of previously owned clean vehicle credit(s) transferred
    to a registered dealer from Schedule A (Form 8936), Part IV. Attach
    Form 8936 and Schedule A (Form 8936)"
  - **d** "Recapture of net EPE from Form 4255, line 2a, column (l)" → Form
    4255
  - **e** "Excessive payments (EPs) on gross EPE from Form 4255. Check
    applicable box and enter amount. See instructions. (i) Line 1a (ii)
    Line 1c (iii) Line 1d (iv) Line 2a"
  - **f** "20% EP from Form 4255. Check applicable box and enter amount. See
    instructions. (i) Line 1a (ii) Line 1c (iii) Line 1d (iv) Line 2a"
  - **y** "Other additions to tax (see instructions):"
- **1z** "Add lines 1a through 1y"
- **2** "Alternative minimum tax. Attach Form 6251" → Form 6251
- **3** "Add lines 1z and 2. Enter here and on Form 1040, 1040-SR, or
  1040-NR, line 17" → **Form 1040 line 17**

### Part II — Other Taxes
- **4** "Self-employment tax. Attach Schedule SE. Check if any exemption
  from (see instructions): [1] 4361 [2] 4029 [3]___" → Schedule SE
- **5** "Social security and Medicare tax on unreported tip income. Attach
  Form 4137" → Form 4137
- **6** "Uncollected social security and Medicare tax on wages. Attach Form
  8919" → Form 8919
- **7** "Total additional social security and Medicare tax. Add lines 5 and
  6"
- **8** "Additional tax on IRAs or other tax-favored accounts. Attach Form
  5329 if required. If not required, check here" → Form 5329
- **9** "Household employment taxes. Attach Schedule H" → Schedule H
- **10** "Reserved for future use"
- **11** "Additional Medicare Tax. Attach Form 8959" → Form 8959
- **12** "Net investment income tax. Attach Form 8960" → Form 8960
- **13** "Uncollected social security and Medicare or RRTA tax on tips or
  group-term life insurance from Form W-2, box 12"
- **14** "Interest on tax due on installment income from the sale of
  certain residential lots and timeshares"
- **15** "Interest on the deferred tax on gain from certain installment
  sales with a sales price over $150,000" — the one static dollar figure on
  any of these three schedules; not inflation-indexed. Cited provisionally
  to IRC §453A — **status: verify** (subsection not independently
  cross-checked against Cornell/uscode this pass)
- **16** "Recapture of low-income housing credit. Attach Form 8611" → Form
  8611

*(page break — "continued on page 2")*

- **17** "Other additional taxes:" (header for 17a–17z)
  - **a** "Recapture of other credits. List type, form number, and amount:"
  - **b** "Recapture of federal mortgage subsidy. If you sold your home,
    see instructions"
  - **c** "Additional tax on HSA distributions. Attach Form 8889" → Form
    8889
  - **d** "Additional tax on an HSA because you didn't remain an eligible
    individual. Attach Form 8889" → Form 8889
  - **e** "Additional tax on Archer MSA distributions. Attach Form 8853" →
    Form 8853
  - **f** "Additional tax on Medicare Advantage MSA distributions. Attach
    Form 8853" → Form 8853
  - **g** "Recapture of a charitable contribution deduction related to a
    fractional interest in tangible personal property"
  - **h** "Income you received from a nonqualified deferred compensation
    plan that fails to meet the requirements of section 409A"
  - **i** "Compensation you received from a nonqualified deferred
    compensation plan described in section 457A"
  - **j** "Section 72(m)(5) excess benefits tax"
  - **k** "Golden parachute payments"
  - **l** "Tax on accumulation distribution of trusts"
  - **m** "Excise tax on insider stock compensation from an expatriated
    corporation"
  - **n** "Look-back interest under section 167(g) or 460(b) from Form 8697
    or 8866" → Form 8697 / Form 8866
  - **o** "Tax on non-effectively connected income for any part of the year
    you were a nonresident alien from Form 1040-NR"
  - **p** "Any interest from Form 8621, line 16f, relating to distributions
    from, and dispositions of, stock of a section 1291 fund" → Form 8621
  - **q** "Any interest from Form 8621, line 24" → Form 8621
  - **z** "Any other taxes. List type and amount:"
- **18** "Total additional taxes. Add lines 17a through 17z"
- **19** "Recapture of net EPE from Form 4255, line 1d, column (l)" → Form
  4255
- **20** "Section 965 net tax liability installment from Form 965-A" → Form
  965-A — **not** an addend in line 21 (see edge cases)
- **21** "Add lines 4, 7 through 16, 18, and 19. These are your total other
  taxes. Enter here and on Form 1040 or 1040-SR, line 23; or Form 1040-NR,
  line 23b" → **Form 1040 line 23** (1040-NR: its own line 23b)

## Schedule 3 (Form 1040) 2025 — Additional Credits and Payments

Attachment Sequence No. 03.

### Part I — Nonrefundable Credits
- **1** "Foreign tax credit. Attach Form 1116 if required" → Form 1116
- **2** "Credit for child and dependent care expenses from Form 2441, line
  11. Attach Form 2441" → Form 2441
- **3** "Education credits from Form 8863, line 19" → Form 8863
- **4** "Retirement savings contributions credit. Attach Form 8880" → Form
  8880
- **5a** "Residential clean energy credit from Form 5695, line 15" → Form
  5695
- **5b** "Energy efficient home improvement credit from Form 5695, line 32"
  → Form 5695
- **6** "Other nonrefundable credits:" (header for 6a–6z)
  - **a** "General business credit. Attach Form 3800" → Form 3800
  - **b** "Credit for prior year minimum tax. Attach Form 8801" → Form 8801
  - **c** "Adoption credit. Attach Form 8839" → Form 8839
  - **d** "Credit for the elderly or disabled. Attach Schedule R" → Schedule
    R
  - **e** "Reserved for future use"
  - **f** "Clean vehicle credit. Attach Form 8936" → Form 8936
  - **g** "Mortgage interest credit. Attach Form 8396" → Form 8396
  - **h** "District of Columbia first-time homebuyer credit. Attach Form
    8859" → Form 8859
  - **i** "Qualified electric vehicle credit. Attach Form 8834" → Form 8834
  - **j** "Alternative fuel vehicle refueling property credit. Attach Form
    8911" → Form 8911
  - **k** "Credit to holders of tax credit bonds. Attach Form 8912" → Form
    8912
  - **l** "Amount on Form 8978, line 14. See instructions" → Form 8978
  - **m** "Credit for previously owned clean vehicles. Attach Form 8936" →
    Form 8936
  - **z** "Other nonrefundable credits. List type and amount:"
- **7** "Total other nonrefundable credits. Add lines 6a through 6z"
- **8** "Add lines 1 through 4, 5a, 5b, and 7. Enter here and on Form 1040,
  1040-SR, or 1040-NR, line 20" → **Form 1040 line 20**

### Part II — Other Payments and Refundable Credits
- **9** "Net premium tax credit. Attach Form 8962" → Form 8962
- **10** "Amount paid with request for extension to file (see
  instructions)"
- **11** "Excess social security and tier 1 RRTA tax withheld"
- **12** "Credit for federal tax on fuels. Attach Form 4136" → Form 4136
- **13** "Other payments or refundable credits:" (header for 13a–13z)
  - **a** "Form 2439"
  - **b** "Section 1341 credit for repayment of amounts included in income
    from earlier years"
  - **c** "Net elective payment election amount from Form 3800, Part III,
    line 6, column (j)" → Form 3800
  - **d** "Deferred amount of net 965 tax liability (see instructions)"
  - **z** "Other refundable credits (see instructions):"
- **14** "Total other payments or refundable credits. Add lines 13a through
  13z"
- **15** "Add lines 9 through 12 and 14. Enter here and on Form 1040,
  1040-SR, or 1040-NR, line 31" → **Form 1040 line 31**

## How the three schedules' subtotals reach Form 1040 (summary)

| Schedule | Line | Subtotal | Form 1040 line |
|---|---|---|---|
| Schedule 1 | 10 | Additional income | 8 |
| Schedule 1 | 26 | Adjustments to income | 10 |
| Schedule 2 | 3 | Tax (AMT + excess APTC repayment, etc.) | 17 |
| Schedule 2 | 21 | Total other taxes | 23 (1040-NR → 23b) |
| Schedule 3 | 8 | Nonrefundable credits | 20 |
| Schedule 3 | 15 | Other payments/refundable credits | 31 |

Cross-checked against `form-1040-2025-line-by-line.md`'s reading of the 1040
face (its lines 8, 10, 17, 20, 23, 31) — every cross-reference matches
exactly in both directions; no discrepancy found.

## Edge cases / interactions worth flagging for engine work

- **Schedule 1's 1099-K reconciliation line is unnumbered and excluded from
  the Part I total.** It sits above Part I, has no line number, and is not
  one of the addends in line 10's "Combine lines 1 through 7 and 9" — the
  same shape as Form 1040's 1z-excludes-1i pattern: a value can be *on* the
  form and still not *in* the sum.
- **Negative-entry lines print with parentheses on the form face**, not a
  literal minus sign: Schedule 1 lines 8a (NOL), 8d (foreign earned income
  exclusion), 8s (nontaxable Medicaid waiver amount). Output meant to mirror
  the form should use the same convention.
- **Schedule 2 line 21's sum formula skips line 20.** "Add lines 4, 7
  through 16, 18, and 19" excludes line 20 (Section 965 net tax liability
  installment from Form 965-A) even though line 20 sits directly above line
  21 in the same visual block. A naive "sum everything above the total
  line" implementation would silently include it and overstate total other
  taxes.
- **Schedule 2 line 21 forks by form.** Form 1040/1040-SR routes to line
  23; Form 1040-NR routes to its own line 23b, not line 23. Relevant only
  if the engine ever supports 1040-NR.
- **Several Schedule 2/3 lines are repayment/recapture mechanisms for a
  credit OBBBA terminated going forward** — Schedule 2 lines 1b/1c
  (clean-vehicle credit transferred-to-dealer repayment) and Schedule 3
  lines 6f/6m (clean vehicle credit / previously-owned clean vehicle
  credit). OBBBA §70501 ended the §30D clean-vehicle credit for vehicles
  acquired after September 30, 2025; the lines remain on the 2025 form
  because a return can cover a vehicle placed in service before that date,
  or a repayment triggered by an earlier-year credit. Not researched
  further here — flag if the engine handles vehicle credits.
- **The AMT/foreign-tax-credit/general-business-credit lines are
  cross-references only.** The two-layer OBBBA-vs-Rev.-Proc.-2024-40 risk
  for AMT exemption amounts and phase-out thresholds (Schedule 2 line 2 →
  Form 6251) and any dollar thresholds inside Form 1116, Form 3800, Form
  8801 (Schedule 3 lines 1, 6a, 6b) lives inside those attached forms, not
  in Schedule 2/3's own wording. None of that was pulled in this pass.

## Open questions / follow-ups

1. Schedule 2 line 15's IRC citation (§453A) — taken from the form text
   only, not cross-checked against Cornell LII or uscode.house.gov.
2. OBBBA's effect on the forms/worksheets these schedules point to (Form
   6251, Form 8936 / Schedule A (Form 8936), Form 1116, Form 3800) — out of
   scope here; each would need its own narrow research pass.
3. Schedule 1-A (new for 2025, OBBBA's above-the-line items) remains
   uncovered by either this note or `form-1040-2025-line-by-line.md` — still
   a follow-up.

status: confirmed (line wording, line numbering, sub-line lettering, and
every Form-1040 cross-reference — all read directly off the three
primary-source PDFs and cross-checked against the existing Form 1040 note)
/ verify (Schedule 2 line 15's specific IRC subsection cite only)
