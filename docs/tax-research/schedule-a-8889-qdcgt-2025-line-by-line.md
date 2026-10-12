# Schedule A, Form 8889, and the Qualified Dividends and Capital Gain Tax Worksheet (2025) — line-by-line

Tax year: **2025** (returns filed in the 2026 filing season). Enacted law only.
Both 2025 layers apply here and are **not** the same layer for every line: Rev.
Proc. 2024-40 (October 2024) still controls the QDCGT Worksheet's capital-gains
breakpoints untouched, while the One Big Beautiful Bill Act (OBBBA, Pub. L.
119-21, 4 July 2025) directly overwrote the SALT cap on Schedule A. Both
Schedule A and Form 8889 were **reprinted** with 2025 figures already baked
into the form face (same pattern the existing `form-1040-2025-line-by-line.md`
note found for the standard deduction) — see each part below for what that
means for citation.

No existing note in `docs/tax-research/` covered any of these three topics;
they were only referenced as pointers from `form-1040-2025-line-by-line.md`
and `schedule-1-2-3-2025-line-by-line.md`. This is new research, not an
extension.

## Sources

- **Schedule A (Form 1040) 2025**, read directly off the primary PDF (all text
  extracted, not summarized). Cat. No. 17145C, footer "Created 11/20/25".
  https://www.irs.gov/pub/irs-pdf/f1040sa.pdf
- **2025 Instructions for Schedule A (Form 1040)**, fetched as HTML.
  https://www.irs.gov/instructions/i1040sca
- **Form 8889 (2025)**, read directly off the primary PDF. Cat. No. 37621P,
  footer "Created 3/28/25". https://www.irs.gov/pub/irs-pdf/f8889.pdf
- **2025 Instructions for Form 8889**, fetched as HTML.
  https://www.irs.gov/instructions/i8889
- **Publication 526** (Charitable Contributions), fetched as HTML, for the
  AGI-percentage limit table. https://www.irs.gov/publications/p526
- **Tax Topic 409** (Capital Gains and Losses), fetched as HTML, for the 2025
  capital-gains rate breakpoints. https://www.irs.gov/taxtopics/tc409
- **26 U.S. Code § 164** (state and local tax deduction), Cornell LII, for the
  current statutory SALT-cap text. https://www.law.cornell.edu/uscode/text/26/164
- **26 U.S. Code § 223** (HSAs), Cornell LII, for the telehealth safe-harbor
  text. https://www.law.cornell.edu/uscode/text/26/223
- Cross-checked against `backend/app/tax_constants/2025.json` and
  `backend/app/services/tax_engine/tax_authority.py` (see "Engine cross-check"
  under each part).

**Environment limitation, reproduced from the existing `form-1040` note and
now confirmed a second time in a separate session:** this tool's PDF reader
needs `pdftoppm`/poppler to page through any PDF over ~10 pages, and poppler
is not installed here — `Read` on a saved copy of Rev. Proc. 2024-40 failed
with `pdftoppm is not installed`. `WebFetch`'s own PDF path independently
fails on anything longer than a couple of pages (it reported Schedule A and
Form 8889 as "unreadable binary" even though `Read` parsed both cleanly once
downloaded — `Read` has real PDF text extraction for short documents;
`WebFetch`'s summarizing model does not reliably have it for long ones). This
blocked direct reads of **Rev. Proc. 2024-40** and **`i1040gi.pdf`** (the
Form 1040 general instructions, where the QDCGT Worksheet's verbatim text
lives) — five separately-worded `WebFetch` attempts against the HTML mirror
of `i1040gi` all confirmed the worksheet heading exists in the page but could
not surface its content. Where a figure below rests on a shorter HTML
surrogate (Tax Topic 409, Pub. 526) instead of the underlying Rev. Proc./PDF
itself, that is stated.

`figures_as_of: 2026-09-22` for every figure below unless stated otherwise.

---

## Part 1 — Schedule A (Form 1040), Itemized Deductions

### The two-layer trap, resolved on this form

The $10,000 SALT cap most people still remember is **gone for 2025**. Line 5e
on the printed 2025 form itself reads "the smaller of line 5d or **$40,000**
($20,000 if married filing separately)" with a MAGI phase-out trigger printed
right on the form face — this is OBBBA, not Rev. Proc. 2024-40 (which never
set a SALT cap figure at all; the old $10,000 was a flat TCJA number, never
inflation-indexed). Cornell LII's current rendering of the Code places this at
**26 U.S.C. § 164(b)(7)** (added/restated by OBBBA — see "Engine cross-check"
below for a wrinkle on the paragraph number), reading in relevant part:

> § 164(b)(7)(A): $40,000 for 2025, $40,400 for 2026, then 101% of the prior
> year's amount for 2027-2029, reverting to $10,000 for 2030 and after.
> § 164(b)(7)(B)(i): "the applicable limitation amount shall be reduced by 30
> percent of the excess (if any) of the taxpayer's modified adjusted gross
> income over the threshold amount."
> § 164(b)(7)(B)(ii): threshold amount $500,000 for 2025 ($505,000 for 2026,
> then similarly indexed).
> § 164(b)(7)(B)(iii): "The reduction... shall not result in the applicable
> limitation amount being less than $10,000."
> Effective for taxable years beginning after December 31, 2024 — i.e. 2025 is
> the first year this applies.

MFS gets half of every figure in that chain ($20,000 cap, $250,000 threshold,
$10,000 → floors at $5,000), confirmed both on the form face and in the
instructions.

### Every line, official wording, in order (from the primary PDF)

**Medical and Dental Expenses** — caution: "Do not include expenses
reimbursed or paid by others."
- **1** "Medical and dental expenses (see instructions)"
- **2** "Enter amount from Form 1040 or 1040-SR, line 11b"
- **3** "Multiply line 2 by 7.5% (0.075)"
- **4** "Subtract line 3 from line 1. If line 3 is more than line 1, enter -0-"

**Taxes You Paid**
- **5** "State and local taxes (SALT)."
  - **a** "State and local income taxes or general sales taxes. You may
    include either income taxes or general sales taxes on line 5a, but not
    both. If you elect to include general sales taxes instead of income
    taxes, check this box"
  - **b** "State and local real estate taxes (see instructions)"
  - **c** "State and local personal property taxes"
  - **d** "Add lines 5a through 5c"
  - **e** "Enter the smaller of line 5d or $40,000 ($20,000 if married filing
    separately). If Form 1040 or 1040-SR, line 11b is more than $500,000
    ($250,000 if married filing separately), or if you completed Form 2555,
    Form 4563, or excluded income from Puerto Rico, see instructions"
- **6** "Other taxes. List type and amount:"
- **7** "Add lines 5e and 6"

**Interest You Paid** — caution: "Your mortgage interest deduction may be
limited. See instructions."
- **8** "Home mortgage interest and points. If you didn't use all of your home
  mortgage loan(s) to buy, build, or improve your home, see instructions and
  check this box"
  - **a** "Home mortgage interest and points reported to you on Form 1098. See
    instructions if limited"
  - **b** "Home mortgage interest not reported to you on Form 1098. See
    instructions if limited. If paid to the person from whom you bought the
    home, see instructions and show that person's name, identifying no., and
    address"
  - **c** "Points not reported to you on Form 1098. See instructions for
    special rules"
  - **d** "Reserved for future use"
  - **e** "Add lines 8a through 8c"
- **9** "Investment interest. Attach Form 4952 if required. See instructions"
- **10** "Add lines 8e and 9"

**Gifts to Charity** — caution: "If you made a gift and got a benefit for it,
see instructions."
- **11** "Gifts by cash or check. If you made any gift of $250 or more, see
  instructions"
- **12** "Other than by cash or check. If you made any gift of $250 or more,
  see instructions. You must attach Form 8283 if over $500"
- **13** "Carryover from prior year"
- **14** "Add lines 11 through 13"

**Casualty and Theft Losses**
- **15** "Casualty and theft loss(es) from a federally declared disaster
  (other than net qualified disaster losses). Attach Form 4684 and enter the
  amount from line 18 of that form. See instructions"

**Other Itemized Deductions**
- **16** "Other—from list in instructions. List type and amount:"

**Total Itemized Deductions**
- **17** "Add the amounts in the far right column for lines 4 through 16.
  Also, enter this amount on Form 1040 or 1040-SR, line 12e" → **Form 1040
  line 12e**
- **18** "If you elect to itemize deductions even though they are less than
  your standard deduction, check this box"

Top-of-form caution not tied to a numbered line: "If you are claiming a net
qualified disaster loss on Form 4684, see the instructions for line 16."

### Thresholds and limits, with authority

| Item | 2025 figure | Authority |
|---|---|---|
| Medical/dental AGI floor | 7.5% of AGI | IRC §213(a) (permanent since the Consolidated Appropriations Act, 2021; unaffected by OBBBA) |
| SALT cap | $40,000 ($20,000 MFS) | IRC §164(b)(7)(A), OBBBA — see above |
| SALT phase-out rate | 30% of MAGI over threshold | IRC §164(b)(7)(B)(i) |
| SALT phase-out threshold | $500,000 ($250,000 MFS) | IRC §164(b)(7)(B)(ii) |
| SALT floor (cap never drops below) | $10,000 ($5,000 MFS) | IRC §164(b)(7)(B)(iii) |
| Mortgage acquisition debt (post-12/15/2017) | $750,000 ($375,000 MFS) | Sch. A instructions, "Home Mortgage Interest" (TCJA figure, made permanent by OBBBA per secondary reporting — **status: verify** on the "permanent" characterization only; the dollar figure itself is unchanged and long-settled) |
| Mortgage acquisition debt (grandfathered, pre-12/16/2017) | $1,000,000 ($500,000 MFS) | same |
| Charitable, cash/ordinary-income property to 50%-limit (public) orgs | 60% / 50% of AGI respectively | IRC §170(b)(1)(G) (cash), Pub. 526 (ordinary-income property) |
| Charitable, capital-gain property to 50%-limit orgs | 30% of AGI | Pub. 526 |
| Charitable, cash/ordinary-income property to non-50%-limit orgs (e.g. most private foundations) | 30% of AGI | Sch. A instructions + Pub. 526 (both quote this figure directly) |
| Charitable, capital-gain property to non-50%-limit orgs | 20% of AGI | same |
| Charitable substantiation — written acknowledgment required | Gifts of $250+ | Sch. A instructions |
| Charitable substantiation — Form 8283 required | Deduction over $500 | Sch. A instructions, form line 12 |
| Charitable substantiation — qualified appraisal required | Deduction over $5,000 ($500 for certain clothing/household items) | Sch. A instructions |
| Casualty/theft loss — per-event floor | $100 | Sch. A instructions ("the amount of each separate casualty or theft loss is more than $100") |
| Casualty/theft loss — aggregate AGI floor | 10% of AGI | Sch. A instructions |
| Casualty/theft loss — disaster requirement | Federally declared disaster only | Sch. A instructions, quoted verbatim above; form's own caution line |
| Overall ("Pease"-style) limitation on itemized deductions | **None for 2025** | Sch. A instructions state no such limitation exists this year |

**Not yet in effect for 2025 — both confirmed only via secondary reporting,
flagged `status: verify`, included here so nobody re-derives them as already
live:**
- A new 0.5%-of-AGI floor under which charitable deductions are not
  deductible at all, and a new cap limiting the value of itemized deductions
  in the 37% bracket to 35 cents per dollar instead of 37 — both OBBBA
  provisions, both **effective for tax years beginning after December 31,
  2025**, i.e. first apply to **2026** returns. The Schedule A instructions'
  own silence on any floor or top-bracket haircut for 2025 corroborates this
  (primary-source confirmation that neither is live yet), but the specific
  "2026" effective date itself is web-search-sourced, not read from bill
  text.
- OBBBA lets **state**-declared disasters (not just federally declared ones)
  qualify for the casualty-loss deduction, but not until 2026 either, per the
  same secondary reporting.

### Edge cases / interactions

- **Line 5a's income-tax-vs-sales-tax election is mutually exclusive** — the
  checkbox on 5a itself says so ("You may include either income taxes or
  general sales taxes on line 5a, but not both").
- **Line 5e's MAGI trigger has a second gate that isn't about MAGI at all:**
  "or if you completed Form 2555, Form 4563, or excluded income from Puerto
  Rico, see instructions" — someone with foreign-earned-income or
  Puerto-Rico-source exclusions must work the phase-out worksheet regardless
  of how far below $500,000 their MAGI is, because those exclusions are added
  back for this test.
- **Line 8's "didn't use all of your home mortgage loan(s) to buy, build, or
  improve your home" checkbox** is the post-TCJA acquisition-debt trap — HELOC
  or cash-out proceeds not used for the home itself are not deductible
  interest, and checking this box signals the limitation applies.
- **Line 18** is the itemize-anyway election (below standard deduction) — a
  real box on the form, not just theoretical; relevant to MFS returns where
  the other spouse itemizes (line 12b on Form 1040 forces this).
- **Line 16 allow-list is exhaustive**, not illustrative: gambling losses
  (limited to winnings), casualty/theft losses of *income-producing* property,
  federal estate tax attributable to income in respect of a decedent,
  amortizable bond premium, ordinary loss on certain contingent/
  inflation-indexed debt instruments, claim-of-right repayments over $3,000,
  certain unrecovered pension investment, and impairment-related work
  expenses of a disabled person. Explicitly **not** deductible here: raffle/
  lottery/bingo tickets, political contributions, country club dues, value of
  volunteered services, blood donations, gifts to foreign organizations, and
  tuition.

### Engine cross-check

`backend/app/tax_constants/2025.json` already carries a full SALT-cap block
(`salt_cap`, `salt_cap_married_separate`, `salt_cap_floor(_mfs)`,
`salt_phasedown_rate`, `salt_phasedown_threshold(_mfs)`) with the exact
figures above. `salt_cap` and `salt_cap_married_separate` are the only two
still marked **`"verify": true`**; the other four already cite `SCH_A_2025`
(defined in `tax_authority.py` but, per a repo-wide grep, not yet referenced
by any constant before this — it was wired to instructions only). This
research **independently confirms** both `verify: true` values ($40,000 /
$20,000) against the form face, the instructions, and Cornell's statutory
text, so a human can now flip both to `verify: false`/confirmed.

One thing worth a second look before doing that: every SALT entry's
`"imposed_by"` reads `"164(b)(6)"`, but Cornell LII's current rendering of
the Code places this language at **§164(b)(7)**, not (b)(6) — one secondary
source described OBBBA as amending "(b)(6)" directly while Cornell's live
text shows it at "(b)(7)"; this is exactly the kind of renumbering a bill
amendment can cause and this note did not independently resolve which is
right against the enrolled bill text. Flagging, not changing.
`medical_agi_floor` (0.075, IRC §213(a)) and `charitable_agi_ceiling_cash`
(0.60, IRC §170(b)(1)(G)) already match this research exactly with no
`verify` flag — no change proposed. **No mortgage-interest-cap constant and
no non-cash charitable ceiling tiers (50%/30%/20%) exist in the engine at
all** — flagging as a gap, not proposing entries, since it's unclear whether
the engine currently computes a mortgage-interest limitation or a
property-type-specific charitable ceiling.

---

## Part 2 — Form 8889, Health Savings Accounts (HSAs)

### The two-layer trap here is different from Schedule A's

The dollar limits on the form ($4,300 / $8,550 / HDHP deductible and
out-of-pocket figures) are **not** Rev. Proc. 2024-40 figures at all — HSA
limits are set annually by a **separate** revenue procedure under the
distinct indexing formula in IRC §223(g), issued months earlier in the year
(Rev. Proc. 2024-25, released May 2024). OBBBA did **not** change any of
these dollar amounts for 2025. What OBBBA *did* change, effective for 2025,
is eligibility law, not the contribution ceiling: **26 U.S.C. §223(c)(2)(E)**
now makes the telehealth/remote-care HDHP safe harbor **permanent** — Cornell
LII's current text reads "A plan shall not fail to be treated as a high
deductible health plan by reason of failing to have a deductible for
telehealth and other remote care services," with the prior sunset language
removed. This matters because the temporary, COVID-era version of that same
safe harbor had already lapsed once before (for plan years beginning in 2023)
and was on a path to lapse again for plan years beginning after 12/31/2024 —
i.e., for calendar-year 2025 HDHPs — absent a fix; OBBBA supplied that fix
before the gap took effect. (**Status: verify** on the exact prior
sunset-date wording — Cornell's fetch came back slightly garbled on that one
clause — the "now permanent" conclusion itself is solid.)

Two further OBBBA HSA changes are **not yet effective for 2025**, confirmed
only via secondary reporting (`status: verify`): ACA Bronze/Catastrophic
marketplace plans becoming HSA-compatible, and direct-primary-care
arrangements not counting as disqualifying coverage — both begin **January 1,
2026**. Do not apply either to a 2025 Form 8889.

### Every line, official wording, in order (from the primary PDF)

**Part I — HSA Contributions and Deduction** ("If you are filing jointly and
both you and your spouse each have separate HSAs, complete a separate Part I
for each spouse.")
- **1** "Check the box to indicate your coverage under a high-deductible
  health plan (HDHP) during 2025. See instructions" — boxes: Self-only /
  Family
- **2** "HSA contributions you made for 2025 (or those made on your behalf),
  including those made by the unextended due date of your tax return that
  were for 2025. Do not include employer contributions, contributions
  through a cafeteria plan, or rollovers. See instructions"
- **3** "If you were under age 55 at the end of 2025 and, on the first day of
  every month during 2025, you were, or were considered, an eligible
  individual with the same coverage, enter $4,300 ($8,550 for family
  coverage). All others, see the instructions for the amount to enter"
- **4** "Enter the amount you and your employer contributed to your Archer
  MSAs for 2025 from Form 8853, lines 1 and 2. If you or your spouse had
  family coverage under an HDHP at any time during 2025, also include any
  amount contributed to your spouse's Archer MSAs"
- **5** "Subtract line 4 from line 3. If zero or less, enter -0-"
- **6** "Enter the amount from line 5. But if you and your spouse each have
  separate HSAs and had family coverage under an HDHP at any time during
  2025, see the instructions for the amount to enter"
- **7** "If you were age 55 or older at the end of 2025, married, and you or
  your spouse had family coverage under an HDHP at any time during 2025,
  enter your additional contribution amount. See instructions"
- **8** "Add lines 6 and 7"
- **9** "Employer contributions made to your HSAs for 2025"
- **10** "Qualified HSA funding distributions"
- **11** "Add lines 9 and 10"
- **12** "Subtract line 11 from line 8. If zero or less, enter -0-"
- **13** "HSA deduction (see instructions)" → **Schedule 1, line 13** ("Health
  savings account deduction. Attach Form 8889" — confirmed against
  `schedule-1-2-3-2025-line-by-line.md`)

**Part II — HSA Distributions**
- **14a** "Total distributions you received in 2025 from all HSAs (see
  instructions)"
- **14b** "Distributions included on line 14a that you rolled over to another
  HSA. Also include any excess contributions (and the earnings on those
  excess contributions) included on line 14a that were withdrawn by the due
  date of your return. See instructions"
- **14c** "Subtract line 14b from line 14a"
- **15** "Qualified medical expenses paid using HSA distributions (see
  instructions)"
- **16** "Taxable HSA distributions. Subtract line 15 from line 14c. If zero
  or less, enter -0-. Also, include this amount in the total on Schedule 1
  (Form 1040), Part I, line 8f" → **Schedule 1, line 8f** (income)
- **17a** "If any of the distributions included on line 16 meet any of the
  Exceptions to the Additional 20% Tax (see instructions), check here"
- **17b** "Additional 20% tax (see instructions). Enter 20% (0.20) of the
  distributions included on line 16 that are subject to the additional 20%
  tax. Also, include this amount in the total on Schedule 2 (Form 1040), Part
  II, line 17c" → **Schedule 2, line 17c**

**Part III — Income and Additional Tax for Failure To Maintain HDHP
Coverage**
- **18** "Last-month rule"
- **19** "Qualified HSA funding distribution"
- **20** "Total income. Add lines 18 and 19. Include this amount on Schedule
  1 (Form 1040), Part I, line 8f" → **Schedule 1, line 8f**
- **21** "Additional tax. Multiply line 20 by 10% (0.10). Include this amount
  in the total on Schedule 2 (Form 1040), Part II, line 17d" → **Schedule 2,
  line 17d**

Preliminary instruction not on a numbered line: "Before you begin: Complete
Form 8853, Archer MSAs and Long-Term Care Insurance Contracts, if required."

### Thresholds and limits, with authority

| Item | 2025 figure | Authority |
|---|---|---|
| Contribution limit, self-only HDHP | $4,300 | Form 8889 line 3 (printed on form); Rev. Proc. 2024-25 |
| Contribution limit, family HDHP | $8,550 | same |
| Catch-up contribution, age 55+ | $1,000 | IRC §223(b)(3)(B) — fixed by statute, **not** inflation-indexed; i8889 instructions quote it directly |
| HDHP minimum annual deductible, self-only | $1,650 | i8889 instructions; Rev. Proc. 2024-25 |
| HDHP minimum annual deductible, family | $3,300 | same |
| HDHP maximum annual out-of-pocket, self-only | $8,300 | same |
| HDHP maximum annual out-of-pocket, family | $16,600 | same |
| Additional tax, non-qualified distribution (line 17b) | 20% | Form 8889 line 17b (printed); exceptions for death, disability, or age 65 |
| Additional tax, failure to maintain HDHP / last-month-rule failure (line 21) | 10% | Form 8889 line 21 (printed) |

### Edge cases / interactions

- **Line 3's $4,300/$8,550 only applies to a filer under 55 with the *same*
  coverage on the first of every month all year** — anyone who changed
  coverage tier mid-year or turned 55 is explicitly routed to the
  instructions' worksheet for a prorated figure instead.
- **Lines 9-11 (employer contributions, including cafeteria-plan/Section 125
  amounts, and IRA-to-HSA qualified funding distributions) reduce the room
  left for a deductible contribution — they are subtracted, not separately
  deducted.** An account holder cannot deduct what the employer already put
  in pretax.
- **Two distinct penalty regimes, easy to conflate:** Part II's 20% (line
  17b) taxes a *distribution* not spent on qualified medical expenses; Part
  III's 10% (line 21) taxes *income* recognized because the "last-month
  rule" full-year testing period was violated (claimed a full year's
  contribution by being HDHP-eligible only on December 1, then lost
  eligibility before December 31 of the following year). These are
  different triggers, different rates, and feed different Schedule 2 lines
  (17c vs. 17d).
- **Married filing jointly with both spouses HSA-eligible on separate
  accounts requires a separate Part I, Part II, and Part III for *each*
  spouse** — stated three times on the form, once per part.
- **Line 16's taxable distribution and Part III's line 20 total income both
  route to the same place, Schedule 1, line 8f** — they are added together
  there, not kept separate, which matters if reconciling Schedule 1 line 8f
  back to its sources.

### Engine cross-check

**No HSA-related constant exists anywhere in `backend/app/tax_constants/2025.json`** —
a search for `4300`, `8550`, HSA contribution/catch-up, and HDHP
deductible/out-of-pocket figures returned nothing. If the engine computes
Form 8889 today, it is either hard-coding these figures elsewhere outside the
authority-tracked constants file, or not yet modeling the HSA deduction limit
at all. Proposed additions (values above; mark `"verify": false` only after a
human independently confirms Rev. Proc. 2024-25's own text, which this note
could not fetch directly — see Sources):

```json
"hsa_contribution_limit_self_only": {"value": "4300", "authority": "<new Authority: Rev. Proc. 2024-25>", "imposed_by": "223(b)(2)(A)", "verify": false},
"hsa_contribution_limit_family": {"value": "8550", "authority": "<same>", "imposed_by": "223(b)(2)(B)", "verify": false},
"hsa_catchup_contribution": {"value": "1000", "authority": {"citation": "IRC §223(b)(3)(B)", "url": "https://www.law.cornell.edu/uscode/text/26/223", "kind": "IRC"}, "verify": false},
"hdhp_min_deductible_self_only": {"value": "1650", "authority": "<Rev. Proc. 2024-25>", "imposed_by": "223(c)(2)(A)", "verify": false},
"hdhp_min_deductible_family": {"value": "3300", "authority": "<same>", "imposed_by": "223(c)(2)(A)", "verify": false},
"hdhp_max_out_of_pocket_self_only": {"value": "8300", "authority": "<same>", "imposed_by": "223(c)(2)(A)", "verify": false},
"hdhp_max_out_of_pocket_family": {"value": "16600", "authority": "<same>", "imposed_by": "223(c)(2)(A)", "verify": false},
"hsa_excess_distribution_additional_tax_rate": {"value": "0.20", "authority": {"citation": "IRC §223(f)(4)", "url": "https://www.law.cornell.edu/uscode/text/26/223", "kind": "IRC"}, "verify": false},
"hsa_hdhp_failure_additional_tax_rate": {"value": "0.10", "authority": {"citation": "IRC §223(b)(8)(B)", "url": "https://www.law.cornell.edu/uscode/text/26/223", "kind": "IRC"}, "verify": false}
```

`tax_authority.py` would need a new `RP_2024_25` `Authority` (citation "Rev.
Proc. 2024-25 (2025 HSA/HDHP inflation adjustments)", url
`https://www.irs.gov/pub/irs-drop/rp-24-25.pdf`, kind "Revenue Procedure") —
not added here per this skill's constraints.

---

## Part 3 — Qualified Dividends and Capital Gain Tax Worksheet (Form 1040 instructions, Line 16)

**Verbatim line-by-line text could not be obtained this session** — see the
environment-limitation note under Sources. This is the same gap both existing
notes (`form-1040-2025-line-by-line.md` and
`schedule-b-d-8949-2025-line-by-line.md`) already flagged as open; five
further attempts this session (direct PDF, PDF via saved-copy `Read`, full
HTML fetch, HTML fetch narrowed to "lines 1-6 only") all failed the same way
— the tool consistently confirms the worksheet heading exists in
`i1040gi` but cannot surface its body text. Treat this as a stable,
reproducible limitation of this environment rather than something worth
re-attempting without a different tool (a local PDF renderer, or a person
with the physical instructions).

### What is confirmed anyway

**When it applies** (already established in `schedule-b-d-8949-2025-line-by-line.md`,
restated here for completeness): used whenever a filer has qualified
dividends (Form 1040 line 3a) or capital gain distributions without a full
Schedule D, **and** has no 28%-rate gain or unrecaptured §1250 gain — either
of those instead forces the 47-line Schedule D Tax Worksheet (already fully
captured in that note).

**Mechanics** (general description from well-established, stable
year-over-year structure — **not a verbatim quote**, flagged explicitly
because it is not primary-sourced this session): the worksheet computes
taxable income net of qualified dividends and net capital gain to find the
"ordinary" portion, taxes that portion at ordinary rates via the Tax Table or
Tax Computation Worksheet, and taxes the preferential (dividends + capital
gain) portion at 0%, 15%, or 20% depending on where each dollar of it falls
relative to the breakpoints below, stacked on top of the ordinary income.

**2025 rate breakpoints** (direct fetch, Tax Topic 409 — corroborated a
second, independent way below):

| Filing status | 0% rate up to | 15% rate up to | 20% rate above |
|---|---|---|---|
| Single | $48,350 | $533,400 | $533,400 |
| Married filing jointly / Qualifying surviving spouse | $96,700 | $600,050 | $600,050 |
| Married filing separately | $48,350 | $300,000 | $300,000 |
| Head of household | $64,750 | $566,700 | $566,700 |

**OBBBA layer check for this specific worksheet — the answer is the opposite
of Schedule A's:** OBBBA left the capital-gains rate *structure* untouched
(0%/15%/20%, permanently retained, per multiple converging reports); no
statutory change to these breakpoints for 2025. **Rev. Proc. 2024-40 remains
the controlling authority here** — unlike the SALT cap, this is a case where
citing only Rev. Proc. 2024-40 for 2025 is *correct*, not a trap.

### Engine cross-check — strong independent confirmation

`backend/app/tax_constants/2025.json`'s `capital_gain_brackets` (authority
`RP_2024_40`, no `verify` flag) contains **exactly** the four rows above for
all four filing statuses, including the two figures ($300,000 MFS and
$566,700 HOH) this note could only single-source from Tax Topic 409. Two
independent sources now agree on every figure — upgrade all four rows from
"single-sourced" to confirmed. No engine change proposed; existing constants
already correct.

### Feed

QDCGT Worksheet's final line → **Form 1040 line 16** ("Tax (see
instructions)"). The exact final line number within the worksheet is unknown
pending the verbatim text (open question below).

---

## Cross-reference table (money flow)

| Line | Feeds | Note |
|---|---|---|
| Schedule A line 17 | Form 1040 line 12e | Only if itemizing beats the standard deduction (or line 18 is checked) |
| Form 8889 line 13 | Schedule 1 line 13 | HSA deduction, adjustment to income |
| Form 8889 line 16 | Schedule 1 line 8f | Taxable HSA distribution, added to income |
| Form 8889 line 17b | Schedule 2 line 17c | Additional 20% tax |
| Form 8889 line 20 | Schedule 1 line 8f | Same target as line 16 — both land on 8f |
| Form 8889 line 21 | Schedule 2 line 17d | Additional 10% tax (different line from 17b) |
| QDCGT Worksheet (final line) | Form 1040 line 16 | Alternative to Tax Table / Tax Computation Worksheet / Schedule D Tax Worksheet |

## Open questions / follow-ups

1. QDCGT Worksheet's verbatim line-by-line text — not obtained (environment
   limitation, reproduced a second time; see Sources).
2. `imposed_by: "164(b)(6)"` on the engine's four already-correct SALT
   sub-constants vs. Cornell LII's current placement of this text at
   §164(b)(7) — flagged for a human, not resolved here.
3. Whether the engine computes a mortgage-interest acquisition-debt
   limitation or non-cash charitable AGI ceilings (30%/20%) at all — no
   corresponding constants found either way.
4. Rev. Proc. 2024-25 itself (HSA/HDHP figures' actual source document) was
   never directly fetched — the dollar figures rest on the Form 8889
   instructions' own restatement plus one corroborating web search, not a
   primary read of the Revenue Procedure text.
5. OBBBA's exact effective-date clause for the §223(c)(2)(E) telehealth
   safe-harbor fix came back slightly garbled from Cornell — the "now
   permanent" conclusion is solid; the precise prior-law sunset date it
   replaced is not independently confirmed.
6. The 2026-effective OBBBA items noted in passing (0.5% charitable floor,
   37%-bracket itemized haircut, state-declared-disaster casualty losses,
   HSA-eligible Bronze/Catastrophic plans) are all single-sourced via general
   web search, included only so nobody re-derives them as live for 2025.

status: confirmed (Schedule A and Form 8889 line wording and every 2025
dollar figure printed on either form — read directly off the primary PDFs;
SALT cap mechanics — cross-confirmed via Cornell LII statutory text and the
existing engine constants; QDCGT capital-gains breakpoints — cross-confirmed
via Tax Topic 409 and the existing engine constants) / verify (QDCGT
Worksheet's verbatim text — not obtained; the §164(b)(6) vs (b)(7) paragraph
number; the six 2026-effective OBBBA items listed above; Rev. Proc. 2024-25
not directly fetched)
