---
topic: Depreciation calculator rules (MACRS, Section 179, bonus 168(k), QPP 168(n), 280F caps, Illinois conformity)
tax_years: 2021, 2022, 2023, 2024, 2025, 2026
figures_as_of: 2026-10-05
figures_source_url: https://www.irs.gov/instructions/i4562
status: verify
---

# Depreciation: MACRS, Section 179, bonus 168(k), QPP 168(n), 280F caps (2021-2026)

Recorded 2026-10-05. Enacted law only; nothing proposed is included. The two
"2025 layers" are kept separate in every table below: Rev. Proc. 2024-40
(October 2024) set 2025 inflation adjustments; OBBBA (Pub. L. 119-21, 4 July
2025) then superseded the Section 179 amounts and the bonus-depreciation rate
for 2025.

`status: verify` because (a) Pub. 946 Appendix A could not be read in this
session (see MACRS section), (b) the section 168(n) detail rests on IRS
search-result excerpts of Notice 2026-16 rather than the full notice, (c) bonus
rates for 2021-2022 were not independently fetched, and (d) Illinois Section
179 conformity is not stated in the source read. Each is repeated under "Open
items". Everything else was read from the cited IRS page.

## How the sources were read

IRS PDFs (rp-xx-xx.pdf, i4562--YYYY.pdf, Pub. 946 PDF) returned unparseable
binary to the fetch tool. Figures below therefore come from IRS HTML pages
(instructions, Pub. 463, Internal Revenue Bulletin pages) or from IRS-domain
search excerpts of the Revenue Procedure text. The `Read` column in each table
says which. Where one search excerpt contradicted itself (Rev. Proc. 2023-14,
see 280F) the figure was re-sought and the contradiction is recorded.

`ALLOWLIST_DOMAINS` in `tax_research_crawler.py` no longer exists (the file was
deleted in the 2026-10-05 assistant rebuild). The nearest current list is
`_STATUTE_HOSTS` and the IRS tier in
`backend/app/services/assistant/citations.py`. Every host used here is on it
(irs.gov, law.cornell.edu, govinfo.gov) or is Illinois's agency host in
`state_registry` (tax.illinois.gov).

## 1. Section 179 expensing (IRC 179)

The rule: a taxpayer may elect to expense the cost of section 179 property in
the year placed in service, up to a dollar limit that is reduced dollar for
dollar by the cost of section 179 property placed in service above a threshold.
SUVs are capped separately.

| Tax year | Max deduction 179(b)(1) | Phase-out starts 179(b)(2) | SUV cap 179(b)(5)(A) | Authority | Read |
|---|---|---|---|---|---|
| 2021 | $1,050,000 | $2,620,000 | $26,200 | Rev. Proc. 2020-45 https://www.irs.gov/pub/irs-drop/rp-20-45.pdf | IRS search excerpt of RP text |
| 2022 | $1,080,000 | $2,700,000 | $27,000 | Rev. Proc. 2021-45 https://www.irs.gov/irb/2021-48_IRB | IRB page, read |
| 2023 | $1,160,000 | $2,890,000 | $28,900 | Rev. Proc. 2022-38 https://www.irs.gov/pub/irs-drop/rp-22-38.pdf | IRS search excerpt of RP text |
| 2024 | $1,220,000 | $3,050,000 | $30,500 | Rev. Proc. 2023-34 sec. 3.25 https://www.irs.gov/irb/2023-48_IRB | IRB page, read |
| 2025, layer 1 (Rev. Proc. 2024-40, **superseded**) | $1,250,000 | $3,130,000 | $31,300 | Rev. Proc. 2024-40 https://www.irs.gov/pub/irs-drop/rp-24-40.pdf | IRS search excerpt of RP text |
| **2025, layer 2 (OBBBA, controls)** | **$2,500,000** | **$4,000,000** | **$31,300** | Pub. L. 119-21 sec. 70306, amending IRC 179(b)(1), (b)(2); https://www.law.cornell.edu/uscode/text/26/179 ; confirmed by 2025 Instructions for Form 4562 https://www.irs.gov/instructions/i4562 | Cornell text and IRS instructions, read |
| 2026 | $2,560,000 | $4,090,000 | $32,000 | Rev. Proc. 2025-32 sec. 4.24 https://www.irs.gov/irb/2025-45_IRB | IRB page, read |

Notes
- OBBBA effective date: property placed in service in taxable years beginning
  after December 31, 2024 (Pub. L. 119-21 sec. 70306(c), as quoted on the
  Cornell page for 179). So 2024 stays at $1,220,000; there is no retroactive
  change to 2021-2024.
- OBBBA text on Cornell states the statutory SUV base as $25,000 and
  inflation adjustment from "calendar year 2024" for taxable years beginning
  after 2025. The 2025 SUV figure of $31,300 is what the 2025 Form 4562
  instructions and Pub. 463 (2025) print, so use $31,300 for 2025; 2026 is
  $32,000 per Rev. Proc. 2025-32.
- Dollar-for-dollar phase-out: the limit reaches zero when cost placed in
  service equals the max deduction plus the threshold (for 2025 layer 2,
  $6,500,000; for 2026, $6,650,000). That arithmetic is derived, not quoted.
- Section 179 is also limited to taxable income from the active conduct of a
  trade or business (179(b)(3)); not fetched in this session, flagged for the
  engine author to read at the Cornell URL above.

## 2. Bonus depreciation, IRC 168(k)

The rule: for qualified property (generally MACRS property with recovery
period of 20 years or less, computer software, water utility property, and
certain other property), the first-year deduction includes an allowance of the
applicable percentage of adjusted basis, taken before regular MACRS on the
remainder.

| Placed in service | Percentage | Authority | Read |
|---|---|---|---|
| 2021 | 100% | IRC 168(k)(6)(A) pre-OBBBA schedule | **Not fetched this session. Verify.** |
| 2022 | 100% | same | **Not fetched this session. Verify.** |
| 2023 | 80% | IRC 168(k)(6)(A), https://www.govinfo.gov/content/pkg/USCODE-2024-title26/html/USCODE-2024-title26-subtitleA-chap1-subchapB-partVI-sec168.htm | govinfo US Code 2024 ed., read via fetch summary |
| 2024 | 60% | same | same |
| 2025, acquired **before** Jan 20, 2025 | 40% (60% long production period property and certain aircraft) | same; Pub. 946 (2025) and 2025 Instructions for Form 4562 https://www.irs.gov/instructions/i4562 | IRS HTML, read |
| **2025, acquired after Jan 19, 2025** | **100%** (election available: 40%, or 60% for long production period property and certain aircraft, for property placed in service in the first taxable year ending after Jan 19, 2025) | Pub. L. 119-21 sec. 70301; Notice 2026-11 https://www.irs.gov/pub/irs-drop/n-26-11.pdf ; 2025 Instructions for Form 4562 | Instructions read; Notice via IRS search excerpt |
| 2026 and later, acquired after Jan 19, 2025 | 100%, permanent | Notice 2026-11 | IRS search excerpt |
| (superseded) 2026 under the pre-OBBBA schedule | 20% | IRC 168(k)(6)(A) as in the 2024 US Code | read, but **do not use** for property acquired after Jan 19, 2025 |

Notes
- The dividing line is **acquisition date, not placed-in-service date.**
  Notice 2026-11, as excerpted: property is not treated as acquired after
  January 19, 2025 if a written binding contract for the acquisition was
  entered into before that date. A 2025 asset acquired January 10 under a
  binding contract gets 40%, not 100%, even if placed in service in June.
- Revenue Procedure 2026-15 (below) states: "Section 168(k), as amended by
  Public Law 119-21 ... applies to property acquired and placed in service
  after January 19, 2025." That sentence is the fastest cite for the split.
- The govinfo fetch summary printed internally inconsistent end dates for the
  2023 row ("before Jan 1, 2023"). The percentages (80/60/40/20) are
  consistent with Pub. 946 (2025) for the 2025 row, but read the statute text
  on Cornell before coding the dates.
- Bonus depreciation is taken before the 280F cap analysis and the regular MACRS
  percentage is then applied to the **remaining** basis.

### Per-asset report selections and filing elections

status: confirmed
figures_as_of: 2026-10-11
figures_source_url: https://www.irs.gov/publications/p946

Publication 946 (2025), chapter 3, "How Can You Elect Not To Claim an
Allowance?", confirms that a bonus opt-out covers all property in the class
placed in service during the tax year. Chapter 2, "Dollar Limits", permits
allocating Section 179 among individual qualifying assets within the shared
limit. These election mechanics are distinct; no rates or limits change here.

Owner-requested additions-report behavior (2026-10-11): Section 179 and bonus
checkboxes remain independent per asset, including assets with the same life.
The report and Excel export compute those selections together, retaining the
shared Section 179 limit and mid-quarter test. Mixed bonus choices within a
class are explicitly marked "Planning only" with a warning to reconcile the
class-wide election before filing. Only classes whose eligible imported assets
all have bonus off are listed as elected out. The standard calculator retains
its class-wide bonus election behavior.

## 3. Qualified production property, IRC 168(n) (new, OBBBA)

The rule (OBBBA sec. 70307, adding 168(n)): a 100% special depreciation
allowance for **qualified production property**, which is nonresidential real
property used as an integral part of a qualified production activity.

| Element | Value | Authority | Read |
|---|---|---|---|
| Allowance | 100% of adjusted basis (election to claim it, per the 4562 instructions "you can elect") | 2025 Instructions for Form 4562 https://www.irs.gov/instructions/i4562 ; Notice 2026-16 https://www.irs.gov/pub/irs-drop/n-26-16.pdf | Instructions read; notice via IRS search excerpt |
| Construction begins | after Jan 19, 2025 and before Jan 1, 2029 | Notice 2026-16 | IRS search excerpt |
| Placed in service | after July 4, 2025 and before Jan 1, 2031, in the US or a US territory | Notice 2026-16; Instructions for Form 4562 (placed in service after July 4, 2025) | same |
| Recapture | If within 10 years of placed-in-service the property ceases to be used as an integral part of a qualified production activity and is put to another productive use, IRC 1245 applies as if disposed of | Notice 2026-16 | IRS search excerpt |

Open on this row: the full definition of "qualified production activity", the
original-use and lease rules, and the exclusion of office, lodging, parking and
similar space were **not read**. Notice 2026-16 is interim guidance announcing
proposed regulations (it is not final). Do not build the eligibility test from
this note; read Notice 2026-16 and 168(n) at
https://www.law.cornell.edu/uscode/text/26/168 first.

## 4. Section 280F caps on passenger automobiles

The rule: depreciation (including 179 and bonus) on a passenger automobile is
capped by year. Table 1 applies when the 168(k) additional first-year
deduction applies (the first-year cap includes an extra $8,000 for
168(k)(2)(F)(i)). Table 2 applies when it does not. These are the owner
limits for autos of 6,000 pounds GVWR or less (the 6,000-pound line comes
from the 4562 instructions' definition of listed passenger automobiles; the
exact GVWR wording was not quoted).

| Placed in service | Table | 1st year | 2nd | 3rd | Each later | Authority | Read |
|---|---|---|---|---|---|---|---|
| 2021 | 1 (with 168(k)) | $18,200 | $16,400 | $9,800 | $5,860 | Rev. Proc. 2021-31 https://www.irs.gov/irb/2021-34_IRB | IRB page, read |
| 2021 | 2 (without) | $10,200 | $16,400 | $9,800 | $5,860 | same | same |
| 2022 | 1 | $19,200 | $18,000 | $10,800 | $6,460 | Rev. Proc. 2022-17 https://www.irs.gov/irb/2022-13_IRB | IRB page, read |
| 2022 | 2 | $11,200 | $18,000 | $10,800 | $6,460 | same | same |
| 2023 | 1 | $20,200 | $19,500 | $11,700 | $6,960 | Rev. Proc. 2023-14 https://www.irs.gov/pub/irs-drop/rp-23-14.pdf | IRS search excerpt of RP text (see note) |
| 2023 | 2 | $12,200 | $19,500 | $11,700 | $6,960 | same | **Verify.** First-year $12,200 appeared in a search excerpt that mislabelled it; later years assumed equal to Table 1 as in every other year |
| 2024 | 1 | $20,400 | $19,800 | $11,900 | $7,160 | Rev. Proc. 2024-13 https://www.irs.gov/irb/2024-09_IRB | IRB page, read |
| 2024 | 2 | $12,400 | $19,800 | $11,900 | $7,160 | same | same |
| 2025 | 1 | $20,200 | $19,600 | $11,800 | $7,060 | Rev. Proc. 2025-16 https://www.irs.gov/pub/irs-drop/rp-25-16.pdf ; Pub. 463 (2025) https://www.irs.gov/publications/p463 | Pub. 463 (2025) read |
| 2025 | 2 | $12,200 | $19,600 | $11,800 | $7,060 | same | same |
| 2026 | 1 | $20,300 | $19,800 | $11,900 | $7,160 | Rev. Proc. 2026-15 (23 Mar 2026) https://www.irs.gov/irb/2026-13_IRB | IRB page, read |
| 2026 | 2 | $12,300 | $19,800 | $11,900 | $7,160 | same | same |

Notes
- **2025 two-layer check.** Rev. Proc. 2025-16 (January 2025) predates OBBBA.
  Pub. 463 (2025), published after OBBBA, still prints $20,200 / $19,600 /
  $11,800 / $7,060, and Rev. Proc. 2026-15 states that Table 1 applies "regardless
  of whether the 168(k) additional first year depreciation deduction is allowed
  under former 168(k) or 168(k) as amended by the OBBBA". So OBBBA did **not**
  change the 280F caps. The 280F cap is separate from the bonus rate: with
  100% bonus a $60,000 auto still gets only the Table 1 first-year amount.
- 2023 contradiction: one search excerpt listed "$12,200 / $19,500 / $11,700 /
  $6,960" under the with-168(k) label. A second, targeted excerpt gave
  $20,200 / $19,500 / $11,700 / $6,960 for Table 1. The $8,000 difference
  between Table 1 and Table 2 in 2021, 2022, 2024, 2025 and 2026 supports
  the second. Re-read the IRB 2023-6 page (Rev. Proc. 2023-14 begins at p. 466)
  before coding 2023.
- 2026 inflation factor: Rev. Proc. 2025-32 and 2026-15 state the 280F(a)
  amounts are multiplied by 0.23468 and added to the 2018 limits after
  rounding to the nearest $100 (excerpt, not read in full).
- Lessee income-inclusion tables exist in each Rev. Proc. (Table 3); not
  recorded here.

## 5. MACRS percentage tables (Pub. 946 Appendix A)

The rule: MACRS rates follow IRC 168(b)-(c): 200% declining balance for 3-,
5-, 7- and 10-year property, 150% for 15- and 20-year property, each switching
to straight line when that is larger, under the half-year convention, or
mid-quarter if more than 40% of the year's depreciable basis (other than
property disposed of in the year) is placed in service in the last 3 months;
residential rental (27.5 years) and nonresidential real property (39 years)
use straight line and the mid-month convention.

**This session could not read Appendix A.** The Pub. 946 HTML page truncates
before the appendix, the Form 4562 instructions HTML truncates before Tables
A-E, and the PDFs do not parse. **No percentage in Appendix A is recorded here
as confirmed**, and nothing was recalled in their place.

What was confirmed about the tables:
- The mid-quarter test, from Pub. 946 (2025) https://www.irs.gov/publications/p946 :
  "The mid-quarter convention applies if more than 40% of the total depreciable
  basis of all property (other than section 1245 property disposed of during
  the year) placed in service during the tax year is placed in service during
  the last 3 months of the tax year."
- The Form 4562 instructions say the depreciation tables are "optional Tables A
  through E" and refer to Pub. 946 for the complete tables
  https://www.irs.gov/instructions/i4562 .
- Pub. 946 Appendix A is the intended source: Table A-1 (half-year), A-2 to A-5
  (mid-quarter by quarter), A-6 (27.5-year mid-month), A-7a (39-year
  mid-month). The table numbering comes from the fetch tool's description of
  the page, not from the table itself.

### Engine cross-check (read, not verified)

`backend/app/services/tax_engine/computations.py`, `MACRS_HALF_YEAR`
(lines 1150-1168), holds 3-, 5-, 7-, 10- and 15-year half-year tables at four
decimals, comment-attributed to "IRS Pub. 946, Table A-1". Gaps relative to this
topic, all of which would make a recomputed depreciation schedule disagree with a
correct return and surface as review items:

- No 20-year table, no mid-quarter tables, no 27.5-year or 39-year mid-month
  tables. `macrs_depreciation` takes only `recovery_years` and
  `year_in_service`; it has no convention parameter.
- No Section 179, bonus, or 280F handling. A first-year line with bonus or 179
  taken (the common case for 2025 acquisitions after Jan 19) recomputes as
  regular MACRS on full basis and will mismatch the stated amount by up to the
  whole bonus. Recomputation should take basis net of 179 and bonus.
- No check that mid-quarter should apply (the 40% test above), so a
  year with heavy Q4 purchases would use the wrong table silently.
- The 15-year table is the only one where the row count (16 values) and
  alternating 0.059/0.0591 pattern are easy to mistype; a human should compare
  every row with Appendix A once the tables can be read.

## 6. Illinois conformity (Illinois only; no other state is covered)

Scope: the task named "state conformity" without a state. Illinois is the only
state the engine implements (IL-1040, IL-ICR, IL-WIT), so Illinois was
researched from tax.illinois.gov. **No other state's rule is stated or implied
here.** For any other state, this note says nothing and the answer must come
from that state's agency.

| Item | Rule | Authority | Read |
|---|---|---|---|
| Form | Form IL-4562, Special Depreciation, is filed by taxpayers who file an income or replacement tax return and report special depreciation on federal Form 4562 or 2106; its purpose is to reverse federal bonus depreciation (30, 40, 50, 60, 80 or 100%, IRC 168(k) and (n)) | 2025 Form IL-4562 Instructions https://tax.illinois.gov/forms/incometax/currentyear/iit-bit-shared-forms/il-4562-instr.html | read |
| Federal 100% acquired after Jan 19, 2025, tax year 2025 | Enter "the amount of federal depreciation you would have claimed for this taxable year had you made the election under IRC Section 168(k)(7)" (i.e., depreciation as if bonus had been declined) | same | read |
| Tax years beginning on or after Jan 1, 2026, 168(n) property | "For property placed in service after July 4, 2025, and before January 1, 2031 ... enter the amount of federal depreciation you would have claimed for this taxable year had you not made the election to claim bonus depreciation under IRC Section 168(n)(6)" | same | read |
| Public Act 104-0453 | Amended IITA Section 203 "to decouple Illinois from federal 100 percent bonus depreciation claimed under IRC Section 168(n)", for tax years beginning on or after Jan 1, 2026; reported on IL-4562 Line 16 | Illinois Informational Bulletin FY 2026-15, December 2025 https://tax.illinois.gov/research/publications/bulletins/fy-2026-15.html | read |
| Carryover | Illinois does not allow carryover of an unused federal-bonus depreciation subtraction year to year | IL-4562 instructions, as excerpted by search result https://tax.illinois.gov/content/dam/soi/en/web/tax/forms/incometax/documents/2023/miscellaneous/il-4562-instr.pdf | search excerpt |
| Section 179 | **Not stated** in the 2025 IL-4562 instructions or the bulletin | n/a | open |

Notes
- The 2025 instructions and the bulletin describe the decoupling in slightly
  different words (the instructions cite 168(k)(7) for 2025 and 168(n)(6) for
  2026+; the bulletin names only 168(n)). Illinois has long required an
  addition for federal 168(k) bonus (the form's purpose line lists 30-100%), so
  the 2025 addition for 168(k) bonus is not new; the Public Act 104-0453
  change is new for 168(n) property starting 2026. Read the form line
  captions before coding, because the summaries above came through a fetch
  summariser.
- A federal 2025 return with bonus depreciation therefore produces an
  Illinois addition on Schedule M (individuals) in the same year and a
  subtraction as the basis is depreciated in later years, with no carryover of
  an unused subtraction.

## Proposed engine constants (not applied)

Do not edit `tax_authority.py` from this note. Suggested entries if the engine
gains a depreciation module, all `verified=False` until a human has checked each
pairing against primary text:

```python
# Section 179, 2025 (OBBBA layer controls; RP 2024-40 layer superseded)
"sec179_max_2025":      C(2500000, OBBBA_179, "179(b)(1)", verified=False,
                          note="Pub. L. 119-21 s.70306; RP 2024-40 said 1,250,000")
"sec179_phaseout_2025": C(4000000, OBBBA_179, "179(b)(2)", verified=False)
"sec179_suv_2025":      C(31300,   I4562_2025, "179(b)(5)(A)", verified=False)
# 2026
"sec179_max_2026":      C(2560000, RP_2025_32, "179(b)(1)", verified=False)
"sec179_phaseout_2026": C(4090000, RP_2025_32, "179(b)(2)", verified=False)
"sec179_suv_2026":      C(32000,   RP_2025_32, "179(b)(5)(A)", verified=False)
# 280F, Table 1 (with bonus) 2025 and 2026, first-year
"sec280f_y1_bonus_2025": C(20200, RP_2025_16, "280F(a)", verified=False)
"sec280f_y1_bonus_2026": C(20300, RP_2026_15, "280F(a)", verified=False)
```

Authorities needed: `OBBBA_179` = Pub. L. 119-21 sec. 70306,
https://www.law.cornell.edu/uscode/text/26/179 (kind "IRC");
`I4562_2025` = https://www.irs.gov/instructions/i4562 (kind "Form Instruction");
`RP_2025_32` = https://www.irs.gov/pub/irs-drop/rp-25-32.pdf;
`RP_2025_16` = https://www.irs.gov/pub/irs-drop/rp-25-16.pdf;
`RP_2026_15` = https://www.irs.gov/irb/2026-13_IRB (the IRB page was read; no
rp-26-15.pdf URL was confirmed).

Because bonus percentage turns on acquisition date, it should be modelled as a
rule keyed by (acquisition date, placed-in-service year), not as one constant
per year.

## Open items

1. **Pub. 946 Appendix A tables unread.** Compare every row of the engine's
   `MACRS_HALF_YEAR` against Appendix A; add 20-year, mid-quarter and mid-month
   tables only from a readable copy. A human with the PDF is the fastest route.
2. **2021-2022 bonus (100%) not fetched.** Read IRC 168(k)(6)(A) on Cornell.
3. **168(n) definition and election mechanics.** Read Notice 2026-16 in full.
4. **2023 280F Table 2** and the 2023 Table 1 reconciliation (IRB 2023-6, p. 466).
5. **179(b)(3) taxable-income limit and carryforward** not fetched.
6. **Illinois Section 179 conformity** unstated in sources read; also the
   pre-2025 IL-4562 treatment per year was not read year by year.
7. **No other state researched.** A state-conformity feature needs the same read per
   state agency, using only that state's own pages.
