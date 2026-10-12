# Illinois IL-1040 (2025) — line-by-line, Schedule ICR, Schedule IL-WIT

Tax year: **2025** (returns filed in the 2026 filing season; due April 15, 2026).
State of Illinois, enacted law only. All three forms below carry the revision
code **(R-12/25)** in their footers, i.e. this is the Illinois Department of
Revenue's current, final-for-filing edition of the 2025 forms — not a draft.

**No federal OBBBA/Rev. Proc. 2024-40 "two layers" issue applies to Illinois's
own numbers.** Illinois's flat rate (4.95%) has been unchanged since July 1,
2017, and its exemption allowance is set annually by the Illinois Department of
Revenue in the current-year instructions, independent of federal law. The one
place the two bodies of law touch is mechanical, not textual: IL-1040 Line 1 is
federal AGI, so an OBBBA-driven change to the federal number (see
`docs/tax-research/form-1040-2025-line-by-line.md`) flows into Illinois's base
income before any Illinois addition/subtraction is applied. Illinois does not
conform its own standard-deduction/exemption mechanism to the federal one —
Illinois has no itemized-vs-standard-deduction concept at all; see below.

`figures_as_of: 2026-09-22` for every figure in this note. `figures_source_url`
is given per item below; all are `tax.illinois.gov` (Illinois's allow-listed
agency host in `state_profiles.py` — domains are `tax.illinois.gov` and
`www2.illinois.gov`; `ilga.gov`, where the Illinois Compiled Statutes are
codified, is **not** on this product's `ALLOWLIST_DOMAINS`, so statute section
numbers below are given as commentary/orientation only, not as the cited
source — the cited source is always the Department's own page or form).

## Sources

- **2025 Form IL-1040**, Individual Income Tax Return (R-12/25). Primary
  source for every line's official wording on the return itself, both pages,
  read directly from the extracted PDF text.
  https://tax.illinois.gov/content/dam/soi/en/web/tax/forms/incometax/documents/currentyear/individual/il-1040.pdf
- **2025 Schedule ICR**, Illinois Credits (R-12/25), all 3 pages including the
  K-12 Education Expense Credit Worksheet, read directly from the extracted
  PDF text.
  https://tax.illinois.gov/content/dam/soi/en/web/tax/forms/incometax/documents/currentyear/individual/il-1040-schedule-icr.pdf
- **2025 Schedule IL-WIT**, Illinois Income Tax Withheld (R-12/25), read
  directly from the extracted PDF text.
  https://tax.illinois.gov/content/dam/soi/en/web/tax/forms/incometax/documents/currentyear/individual/il-1040-schedule-il-wit.pdf
- **2025 IL-1040 Instructions, Step 2 – Income**.
  https://tax.illinois.gov/forms/incometax/currentyear/individual/il-1040-instr/step-2---income.html
- **2025 IL-1040 Instructions, Step 4 – Exemptions** — source for the
  exemption-allowance table and the income-exception (phase-out) thresholds.
  https://tax.illinois.gov/forms/incometax/currentyear/individual/il-1040-instr/step-4---exemptions.html
- **2025 IL-1040 Instructions, Step 5 – Net Income and Tax**.
  https://tax.illinois.gov/forms/incometax/currentyear/individual/il-1040-instr/step-5---net-income-and-tax.html
- **Illinois Department of Revenue, Tax Rate Database — Income Tax** — source
  for the 4.95% rate and its July 1, 2017 effective date, independent of the
  form itself.
  https://tax.illinois.gov/research/taxrates/income.html

## Illinois flat income tax rate — status: confirmed

**4.95% (.0495)** of net income, for individuals, trusts, and estates, unchanged
since **July 1, 2017**. Confirmed two ways: on the face of Form IL-1040 Line 12
("Multiply Line 11 by 4.95% (.0495)") and independently on the Department's
Tax Rate Database page, which states the individual rate as "4.95 percent of
net income," effective July 1, 2017 (the same page gives 7% for corporations
and 4.95% for trusts/estates).
Sources: both URLs above (IL-1040 PDF; `research/taxrates/income.html`).
Corresponding statute (for orientation, not independently fetched from an
allow-listed host): 35 ILCS 5/201 — Illinois Income Tax Act, "Tax imposed."

## Illinois exemption allowance (2025) — status: confirmed

Not printed as a dollar figure on the form itself — Line 10a says "See
instructions" — the amount comes from the Step 4 instructions table:

| Filing status | Checked Step 1, Line C (someone can claim you/spouse as a dependent)? | Base income (Line 9 / Sch. NR Line 46) | Exemption amount (Line 10a) |
|---|---|---|---|
| Single* | No | any amount | **$2,850** |
| Single* | Yes | $2,850 or below | $2,850 |
| Single* | Yes | $2,851 or greater | $0 |
| Married filing jointly | No | any amount | **$5,700** |
| Married filing jointly | Yes — only one spouse | $2,850 or below | $5,700 |
| Married filing jointly | Yes — only one spouse | $2,851 or greater | $2,850 |
| Married filing jointly | Yes — both spouses | $5,700 or below | $5,700 |
| Married filing jointly | Yes — both spouses | $5,701 or greater | $0 |

`*` "Single filing status includes Single, Head of Household, Widowed, and
Married filing separately."

**Income Exceptions (full phase-out to zero, independent of the table above):**
"If your federal filing status is married filing jointly and your federal AGI
is greater than $500,000, you are not entitled to an exemption allowance on
Line 10. Enter 'zero' on Line 10. If your federal filing status is single, head
of household, married filing separately, or widowed and your federal AGI is
greater than $250,000, you are not entitled to an exemption allowance on Line
10. Enter 'zero' on Line 10."

**Age 65+ / blindness additions** (on the form, not the instructions page):
Line 10b — "Check if 65 or older: [ ] You + [ ] Spouse, # of checkboxes x
$1,000 ="; Line 10c — same structure for "Check if legally blind." Each
checked box is worth $1,000, stacking with the base exemption above.

**Dependent exemption** flows in separately at Line 10d from **Schedule
IL-E/EITC, Step 2, Line 1** (that schedule's own line-by-line detail is out of
scope for this note).

Source: Step 4 instructions page (URL above). Corresponding statute (same
caveat as the rate): 35 ILCS 5/204 — not independently fetched from an
allow-listed host.

## How federal AGI enters IL-1040

**Line 1**: "Federal adjusted gross income from your federal Form 1040 or
1040-SR, Line 11a." This is the *first number* on the Illinois return — every
later addition/subtraction (Schedule M), the Social-Security/retirement-income
subtraction (Line 5), and the exemption allowance's own income-exception test
above all key off this one imported figure or things computed from it.
Confirmed against `docs/tax-research/form-1040-2025-line-by-line.md`: federal
Form 1040 (2025) Line 11a is worded "Subtract line 10 from line 9. This is your
adjusted gross income" — so IL-1040's citation to "Line 11a" is the correct
2025 federal line label, not a stale reference to a prior year's numbering.

Step 2 instructions (HTML) phrase the same thing operationally: "Enter the
adjusted gross income from your federal return. If you are not required to
file a federal income tax return, use a federal Form 1040 as a worksheet to
determine your adjusted gross income."

Illinois then makes its own, wholly separate adjustments — it does **not**
import the federal standard deduction, itemized deductions, or federal
exemption/dependent mechanism at all; Illinois has no standard-vs-itemized
concept. Everything from Line 2 onward (tax-exempt interest add-back, Schedule
M additions/subtractions, the state's own exemption allowance above) is
Illinois-specific.

## Form IL-1040 (2025) — every numbered line, in order, with official wording

Wording is quoted from the form as printed; "→" shows what schedule/form the
line pulls from or sends its result to.

### Step 1: Personal Information (not numbered — structural)
- Taxpayer/spouse name, date of birth, SSN (full SSN required, "no partial
  SSN"); mailing address, apartment number, city/state/zip, foreign nation if
  applicable, county (Illinois only), email address.
- **B** Filing status: Single / Married filing jointly / Married filing
  separately / Widowed / Head of household.
- **C** Check if someone can claim you, or your spouse if filing jointly, as a
  dependent — separate You/Spouse boxes. (This checkbox is a direct input to
  the Step 4 exemption table above.)
- **D** Check the box if this applies to you during 2025: Nonresident (attach
  Sch. NR) / Part-year resident (attach Sch. NR).

### Step 2: Income
- **1** "Federal adjusted gross income from your federal Form 1040 or
  1040-SR, Line 11a."
- **2** "Federally tax-exempt interest and dividend income from your federal
  Form 1040 or 1040-SR, Line 2a."
- **3** "Other additions. Attach Sch. M." → Schedule M
- **4** "Total income. Add Lines 1 through 3."

### Step 3: Base Income
- **5** "Social Security benefits and certain retirement plan income if
  included in Line 1. (Generally on fed. Forms 1040/1040-SR, Lines 4b, 5b, and
  6b). Attach fed. Form 1040/1040-SR."
- **6** "Illinois Income Tax overpayment included in federal Form 1040 or
  1040-SR, Schedule 1, Ln. 1."
- **7** "Other subtractions. Attach Sch. M." → Schedule M
- **8** "Add Lines 5, 6, and 7. This is the total of your subtractions."
- **9** "Illinois base income. Subtract Line 8 from Line 4."

### Step 4: Exemptions (see full table above)
- **10a** "Enter the exemption amount for yourself and your spouse. See
  instructions."
- **10b** "Check if 65 or older: You + Spouse, # of checkboxes x $1,000 ="
- **10c** "Check if legally blind: You + Spouse, # of checkboxes x $1,000 ="
- **10d** "If you are claiming dependents, enter the amount from Schedule
  IL-E/EITC, Step 2, Line 1. Attach Sch. IL-E/EITC." → Schedule IL-E/EITC
- **10** "Exemption allowance. Add Lines 10a through 10d."

### Step 5: Net Income and Tax
- **11** "Residents: Net income: Subtract Line 10 from Line 9. Nonresidents
  and part-year residents: Enter the Illinois net income from Schedule NR.
  Attach Sch. NR." → Schedule NR (nonresidents/part-year)
- **12** "Residents: Multiply Line 11 by 4.95% (.0495). Cannot be less than
  zero. Nonresidents and part-year residents: Enter the tax from Schedule
  NR." → Schedule NR (nonresidents/part-year)
- **13** "Recapture of investment tax credits. Attach Sch. 4255." → Schedule
  4255
- **14** "Income tax. Add Lines 12 and 13. Cannot be less than zero."

### Step 6: Tax After Nonrefundable Credits
- **15** "Income tax paid to another state while an Illinois resident. Attach
  Sch. CR." → Schedule CR
- **16** "Property tax, K-12 education expense, and volunteer emergency
  worker credit amount from Schedule ICR. Attach Sch. ICR." → **Schedule ICR,
  Line 13** (see full detail below)
- **17** "Credit amount from Schedule 1299-C. Attach Sch. 1299-C." → Schedule
  1299-C
- **18** "Add Lines 15, 16, and 17. This is the total of your credits. Cannot
  exceed the tax amount on Line 14."
- **19** "Tax after nonrefundable credits. Subtract Line 18 from Line 14."

### Step 7: Other Taxes
- **20** "Household employment tax. See instructions."
- **21** "Use tax on internet, mail order, or other out-of-state purchases
  from UT Worksheet or UT Table in the instructions. Do not leave blank."
- **22** "Compassionate Use of Medical Cannabis Program Act and sale of
  assets by gaming licensee surcharges."
- **23** "Total Tax. Add Lines 19, 20, 21, and 22."

### Step 8: Payments and Refundable Credit (page 2 opens with 24)
- **24** "Total tax from Page 1, Line 23."
- **25** "Illinois Income Tax withheld. Attach Sch. IL-WIT." → **Schedule
  IL-WIT, Line 11** (see full detail below)
- **26** "Estimated payments from Forms IL-1040-ES and IL-505-I, including
  any overpayment applied from a prior year return."
- **27** "Pass-through withholding. Attach Sch. K-1-P or K-1-T." → Schedule
  K-1-P / K-1-T
- **28** "Pass-through entity tax credit. Attach Sch. K-1-P or K-1-T." →
  Schedule K-1-P / K-1-T
- **29** "Earned Income Tax credit from Sch. IL-E/EITC, Step 4, Line 9.
  Attach Sch. IL-E/EITC." → Schedule IL-E/EITC
- **30** "Child Tax credit from Sch. IL-E/EITC, Step 5, Line 12. Attach Sch.
  IL-E/EITC." → Schedule IL-E/EITC
- **31** "Total payments and refundable credit. Add Lines 25 through 30."

### Step 9: Total
- **32** "If Line 31 is greater than Line 24, subtract Line 24 from Line 31."
- **33** "If Line 24 is greater than Line 31, subtract Line 31 from Line 24."

### Step 10: Underpayment of Estimated Tax Penalty and Donations
- **34** "Late-payment penalty for underpayment of estimated tax. See
  instructions." Sub-checkboxes: **a** two-thirds of federal gross income
  from farming; **b** you or spouse 65+ and permanently living in a nursing
  home; **c** income not received evenly, annualized on Form IL-2210 (attach
  it); **d** not required to file an Illinois return in the previous tax year.
- **35** "Voluntary charitable donations. Attach Sch. G." → Schedule G
- **36** "Total penalty and donations. Add Lines 34 and 35."

### Step 11: Refund or Amount You Owe
- **37** "If you have an amount on Line 32 and this amount is greater than
  Line 36, subtract Line 36 from Line 32. This is your overpayment. Otherwise,
  go to Line 41."
- **38** "Amount from Line 37 you want refunded to you. Check one box on Line
  39. See instructions."
- **39** "I choose to receive my refund by **a** direct deposit [routing
  number, account number, Checking or Savings] **b** paper check."
- **40** "Amount to be credited forward. Subtract Line 38 from Line 37. See
  instructions."
- **41** "If you have an amount on Line 33, add Lines 33 and 36. If you have
  an amount on Line 32, and this amount is less than Line 36, subtract Line 32
  from Line 36. If Lines 32 and 33 are blank (zero), enter the amount from
  Line 36. This is the amount you owe. See instructions."

### Step 12: Health Insurance Checkbox and Signature
- **42** "Check this box and include your email address in Step 1 if IDOR
  may share your income and other information from this return with the
  Department of Insurance in order to determine your eligibility for
  affordable health insurance coverage through Get Covered Illinois, the
  state's Health Insurance Marketplace. See instructions." Sub-boxes: Self /
  Spouse / Dependent(s) need insurance.
- Signature block (both spouses if joint), Third Party Designee, Paid
  Preparer Use Only — administrative, not numbered as tax lines.

**Whole-dollar rule**: unlike the federal form (where rounding is optional),
every IL-1040 line is printed "(Whole dollars only)" with a fixed ".00" — cents
are not entered at all, not an optional round-or-don't choice.

## Schedule ICR (2025), Illinois Credits — every numbered line

IL Attachment No. 23. Gate: "You must complete Form IL-1040 through Line 14
and Schedule CR, if applicable, before completing this schedule. The total
amount of Illinois Property Tax Credit, K-12 Education Expense Credit, and
Volunteer Emergency Worker Credit cannot exceed tax due."

### Step 2: Figure your nonrefundable credit
- **1** "Enter the amount of tax from your Form IL-1040, Line 14." ← IL-1040
  Line 14
- **2** "Enter the amount of credit for tax paid to other states from your
  Form IL-1040, Line 15." ← IL-1040 Line 15 (Schedule CR)
- **3** "Subtract Line 2 from Line 1."

**Section A — Illinois Property Tax Credit** (see Publication 108)
- **4a** "Enter the total amount of Illinois Property Tax paid during the tax
  year for the real estate that includes your principal residence."
- **4b** County and property number of principal residence.
- **4c** County and property number of an adjoining lot, if included in 4a.
- **4d** County and property number of another adjoining lot, if included in
  4a.
- **4e** "Enter the portion of your tax bill that is deductible as a business
  expense on U.S. income tax forms or schedules, even if you did not take the
  federal deduction."
- **4f** "Subtract Line 4e from Line 4a."
- **4g** "Multiply Line 4f by 5% (.05)."
- **5** "Compare Lines 3 and 4g, and enter the lesser amount here."
- **6** "Subtract Line 5 from Line 3."

**Section B — K-12 Education Expense Credit** (see Publication 112; requires
the K-12 Education Expense Credit Worksheet, page 3, and receipts attached)
- **7a** "Enter the total amount of K-12 education expenses from Line 15 of
  the worksheet on Page 3 of this schedule."
- **7b** "You may not take a credit for the first $250 paid." (pre-printed
  $250.00)
- **7c** "Subtract Line 7b from Line 7a. If the result is negative, enter
  'zero.'"
- **7d** "Multiply Line 7c by 25% (.25). Compare the result and $750, and
  enter the lesser amount here." (so the K-12 credit is statutorily capped at
  $750 per return)
- **8** "Compare Lines 6 and 7d, and enter the lesser amount here."
- **9** "Subtract Line 8 from Line 6."

**Section C — Volunteer Emergency Worker Credit** (requires a Volunteer
Emergency Worker Credit Certificate from IDOR)
- **10a** Your certificate number. **10b** Spouse's certificate number.
- **10c** "Enter $500.00 if you, or your spouse if married filing jointly,
  were awarded the volunteer emergency worker credit. Enter $1,000.00 if
  married filing jointly, and both you and your spouse were awarded the
  credit."
- **11** "Compare Lines 9 and 10c, and enter the lesser amount here."
- **12** "Subtract Line 11 from Line 9."

**Section D — Total Nonrefundable Credit**
- **13** "Add Lines 5, 8, and 11. This is your nonrefundable credit amount.
  Enter this amount on Form IL-1040, Line 16." → **feeds IL-1040 Line 16**

### K-12 Education Expense Credit Worksheet (page 3)
- **14** Per-student table, columns A–G: Student's name; SSN; Grade (K-12
  only); School name (Illinois K-12 schools only, or "home school"); School
  city (Illinois cities only); School type (check one: P=Public,
  N=Non-public, H=Home school); Total tuition, book/lab fees. Rows a–j, with
  an instruction to attach a separate sheet in the same format if more than
  ten students.
- **15** "Add the amounts in Column G for Lines 14a through 14j (and the
  amounts from Column G of any additional pages you attached). This is the
  total amount of your qualified education expenses for this year. Enter this
  amount here and on Step 2, Line 7a of this schedule." → feeds back into
  Line 7a above.

## Schedule IL-WIT (2025), Illinois Income Tax Withheld — every line/column

IL Attachment No. 31. "If you have more than five withholding forms, complete
multiple copies of this schedule." Purpose line (from the instructions
search): "Attach a completed Schedule IL-WIT and all withholding forms (W-2s,
1099s, etc.) to support the amount you claim as Illinois Income Tax withheld
on Line 25."

**Column A form-type letter codes**: W-2=W, W-2G=WG, 1099-R=R, 1099-G=G,
1099-MISC=M, 1099-OID=O, 1099-DIV=D, 1099-INT=I, 1042-S=S, 1099-B=B,
1099-K=K, 1099-NEC=N.

**Step 1: Provide your withholding records** (taxpayer's own name/SSN header)
- Lines **1–5**, each a row with: Column A (Form type), Column B
  (Employer/Payer Identification Number), Column C (Federal Wages, Winnings,
  Gross Distributions, Compensation, etc.), Column D (Illinois Wages,
  Winnings, Gross Distributions, Compensation, etc.), Column E (Illinois
  Income Tax Withheld).

**Step 2: Provide spouse's withholding records** (spouse's name/SSN header)
- Lines **6–10**, same five columns A–E as Step 1.

**Step 3: Total Illinois withholding**
- **11** "Add the amounts in Column E for Lines 1 through 10 (and the amounts
  from Column E of any additional copies you attached). This is the total
  amount of your Illinois income tax withheld. Enter this amount here and on
  Form IL-1040, Line 25." → **feeds IL-1040 Line 25**

## Which IL-1040 line each schedule feeds — summary

| Schedule | Final line | Feeds IL-1040 line |
|---|---|---|
| Schedule ICR | Line 13 (Section D total) | **Line 16** — "Property tax, K-12 education expense, and volunteer emergency worker credit amount from Schedule ICR" |
| Schedule IL-WIT | Line 11 (Step 3 total) | **Line 25** — "Illinois Income Tax withheld" |

For completeness, the other schedules named on the face of IL-1040 (not
detailed line-by-line in this note): Schedule M → Lines 3 and 7; Schedule NR →
Lines 11–12 (nonresidents/part-year residents); Schedule CR → Line 15;
Schedule 4255 → Line 13; Schedule 1299-C → Line 17; Schedule IL-E/EITC →
Lines 10d, 29, 30; Schedule K-1-P or K-1-T → Lines 27–28; Form IL-2210 →
Line 34c; Schedule G → Line 35.

## Edge cases / interactions worth flagging

- **The Step 4 exemption table and the "Income Exceptions" phase-out are two
  separate tests.** The table alone can zero out the exemption at fairly low
  income when Step 1 Line C is checked (someone can claim the taxpayer as a
  dependent) — as low as $2,851 of base income for a single filer. The
  "Income Exceptions" paragraph is a *second*, independent full phase-out at
  much higher federal AGI ($250,000 single-type statuses / $500,000 MFJ) that
  applies regardless of the Line C checkbox. Both must be checked; either one
  can zero Line 10.
- **Schedule ICR's credits are ordered and each is capped against what's left
  of tax due**, not against Line 14 independently: Line 3 (tax net of the
  other-states credit) caps the property tax credit (Line 5), what's left
  after that (Line 6) caps the K-12 credit (Line 8), and what's left after
  *that* (Line 9) caps the volunteer emergency worker credit (Line 11). A
  return claiming all three cannot simply sum three independently-computed
  credit amounts — order matters and each subsequent credit can be
  compressed to zero by the ones ahead of it.
- **The K-12 credit has two caps of its own**: the first $250 of expense per
  return is non-creditable (7b), and the 25%-of-the-remainder result is
  further capped at $750 (7d) before it ever reaches the Line 6 tax-due cap.
- **IL-WIT is purely an aggregator** — it takes no input from IL-1040 itself
  (unlike ICR, which reads IL-1040 Lines 14–15 as inputs); it only sums
  Column E across every attached W-2/1099 and reports the total to Line 25.
- **Illinois has no standard/itemized deduction concept.** The federal
  Schedule A amount (see `docs/tax-research/schedule-a-8889-qdcgt-2025-line-by-line.md`)
  has no IL-1040 counterpart; Illinois's only income-reduction mechanisms
  after importing federal AGI are the Line 5–7 subtractions (Schedule M) and
  the Step 4 exemption allowance.

## Open questions / follow-ups

1. Schedule M (additions/subtractions), Schedule NR (nonresident/part-year
   apportionment), Schedule CR (credit for tax paid to other states), Schedule
   IL-E/EITC, and Schedule 1299-C each have their own line-by-line detail not
   covered here — natural follow-up notes if the engine needs them.
2. The Illinois Compiled Statutes citations given above (35 ILCS 5/201 for the
   rate, 35 ILCS 5/204 for the exemption) are stated for orientation only —
   `ilga.gov` is outside this product's `ALLOWLIST_DOMAINS`, so they were not
   independently fetched and verified against the codified text in this pass.
   The dollar/percentage figures themselves **are** confirmed directly against
   the Department's own current-year form and rate-database page.
3. Publication 108 (property tax credit) and Publication 112 (K-12 education
   expense credit), referenced on the face of Schedule ICR, were not
   separately fetched — the schedule's own line text was sufficient for the
   figures captured here (the $250 floor, the 5%/25% rates, the $750 cap).

status: confirmed (all IL-1040, Schedule ICR, and Schedule IL-WIT line wording,
the 4.95% rate, the exemption-allowance table and phase-outs, and the
schedule-to-line feeds — all read directly off primary `tax.illinois.gov`
PDF/HTML text) / verify (the two ILCS statute-section citations only, per
open question 2).
