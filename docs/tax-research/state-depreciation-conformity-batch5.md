---
topic: State depreciation conformity, batch 5 (MT, NE, NV, NH, NJ), personal income tax, tax years 2021-2026
tax_years: 2021, 2022, 2023, 2024, 2025, 2026
figures_as_of: 2026-10-06
figures_source_url: per-state URLs below (state legislature / statute sites and state agency hosts)
status: verify
progress: COMPLETE. Montana, Nebraska, Nevada, New Hampshire and New Jersey done (6 rows each, 30 rows in the JSON). Replaces the earlier placeholder, which listed a different (now reassigned) set of states.
---

# State depreciation conformity, batch 5 (MT, NE, NV, NH, NJ)

Recorded 2026-10-06. Enacted law only. Scope is the personal income tax as it applies to a sole
proprietor, pass-through owner or rental owner. Federal reference figures come from
`docs/tax-research/depreciation-macrs-179-bonus-280f-2021-2026.md` and are not re-derived here.

Federal figures that a "conforming" state inherits (that note carries the IRS citations and its own
`verify` flags):

| Tax year | Federal bonus 168(k) | 179 limit | 179 phase-out start |
|---|---|---|---|
| 2021 | 100% | 1,050,000 | 2,620,000 |
| 2022 | 100% | 1,080,000 | 2,700,000 |
| 2023 | 80% | 1,160,000 | 2,890,000 |
| 2024 | 60% | 1,220,000 | 3,050,000 |
| 2025 | 100% acquired after 19 Jan 2025; 40% earlier (P.L. 119-21 s.70301 over Rev. Proc. 2024-40) | 2,500,000 (OBBBA s.70306; RP 2024-40 said 1,250,000) | 4,000,000 (RP 2024-40 said 3,130,000) |
| 2026 | 100% | 2,560,000 | 4,090,000 |

## How this was researched

- `ALLOWLIST_DOMAINS` in `tax_research_crawler.py` no longer exists (file deleted in the 2026-10-05
  rebuild). Agency hosts come from `backend/app/services/assistant/state_registry.py` (mtrevenue.gov,
  revenue.nebraska.gov, tax.nv.gov, revenue.nh.gov, nj.gov), plus each state's legislature or official
  code site. The registry lists only `mtrevenue.gov` for Montana, but the Department publishes forms
  from `revenue.mt.gov` and `revenuefiles.mt.gov`; I treated those as the same agency's hosts and
  flag it here for the owner.
- Bash and Edit are not usable in this session, so PDF text could not be extracted with PyMuPDF and
  each file update was a whole-file rewrite. `WebFetch` cannot parse PDFs, but the `Read` tool opens
  them without a `pages` argument, even a 48-page one (`pages` fails here: pdftoppm is missing).
- `verified` in the JSON is true only when every non-null cell was read from statute text or agency
  text in this session. Inferences from the absence of an adjustment, federal figures carried as
  "conforming", derived figures and adjacent-year carry are `false`. Result: MT 2025 and all six NV
  rows are `true`; the other 23 rows are `false`, each with the reason in `verify_note`.
- **Access blocks.** `nebraskalegislature.gov` refused every connection (ECONNREFUSED); the Nevada
  statute site (`leg.state.nv.us`) returned HTTP 403; every `revenue.nh.gov`, `gc.nh.gov` and
  `gencourt.state.nh.us` page and PDF returned HTTP 403; `pub.njleg.gov` (New Jersey legislature)
  refused connections. For those, the only evidence is the search-result excerpt of the official
  page, recorded below as "excerpt".

## Summary matrix

| State | Individual income tax | Bonus 2021-2024 | Bonus 2025 | Bonus 2026 | 179 | 168(n) |
|---|---|---|---|---|---|---|
| MT | yes | follows federal (inferred; verify) | follows federal (agency text) | follows federal (inferred; verify) | federal (inferred) | no add-back found |
| NE | yes | follows federal (agency page: no add-back since 2006) | follows federal (agency report; statute date unresolved) | follows federal (inferred; no change enacted found) | federal | flows through; LB 853 decoupling postponed |
| NV | **no** | n/a | n/a | n/a | n/a | n/a (Commerce Tax is on gross revenue) |
| NH | **no** wage/business income tax; I&D tax (interest and dividends only) repealed from 2025 | n/a personal; BPT: **none** (IRC without 168(k)) | same, OBBBA not adopted | same | BPT only: capped at 500,000 | BPT: not adopted (IRC fixed at 31 Dec 2018) |
| NJ | yes (Gross Income Tax) | **none** (50% allowance not allowed; 30% only if taken federally) | none (OBBBA not mentioned on the 10/25 form) | none | **25,000** cap (phase-out 200,000 derived) | not mentioned; no allowance in effect (unconfirmed) |

## Montana (MT)

Individual income tax: yes (rates 4.7% / 5.9% for 2025 and 4.7% / 5.65% for 2026 per the 2025 Form 2
instructions, p. 12 and p. 42, https://revenuefiles.mt.gov/files/Forms/Montana-Individual-Income-Tax-Return-Form-2-Instructions/2025_Montana_Individual_Income_Tax_Return_Form_2_Instructions.pdf).

- **Rule for 2025 (agency text, read in full 2026-10-06).** Schedule I line 19, p. 20: "Do not
  include any recoveries of capital expenditures through depreciation, depletion, or amortization.
  Depreciation, depletion, and amortization deductions must be the same for federal and Montana
  income tax purposes." Line 1 starts from federal adjusted gross income, and line 2 takes the
  federal standard or itemized deduction. The only depreciation addition is "Title plant
  amortization and depreciation - Code: AG" (p. 17). The instructions' list of 2025-session
  legislative changes (pp. i-ii: HB 845, SB 53, SB 93, SB 544; 2026: HB 129, HB 337) has no
  depreciation item. So Montana takes the federal 168(k) deduction, including the 100% rate for
  property acquired after 19 Jan 2025, and the federal 179 deduction.
- **Statute.** MCA 15-30-2101 defines the Internal Revenue Code as "the Internal Revenue Code of
  1986, as amended, or as it may be labeled or further amended", and references to its sections
  "as they may be otherwise labeled or further amended"; this is a rolling definition
  (https://mca.legmt.gov/bills/mca/title_0150/chapter_0300/part_0210/section_0010/0150-0300-0210-0010.html,
  last amended by Ch. 503, L. 2021). MCA 15-30-2120(2)(c), the current additions list, has one
  depreciation item, "depreciation or amortization taken on a title plant as defined in 33-25-105"
  (https://mca.legmt.gov/bills/mca/title_0150/chapter_0300/part_0210/section_0200/0150-0300-0210-0200.html).
  The statute names no 168(k), 168(n) or 179 modification. Amendment history shows 2025 chapters 545,
  586, 638, 675, 734 and 767 amended this section; I did not read each one.
- **Pre-2024 base.** MCA 15-30-2110 (2022 edition) made Montana AGI equal to federal AGI (IRC 62)
  plus listed additions; the only depreciation item was the same title plant addition
  (https://mca.legmt.gov/bills/2022/mca/title_0150/chapter_0300/part_0210/section_0100/0150-0300-0210-0100.html).
  The 2024 Form 2 changes sheet (https://revenue.mt.gov/files/Forms/Montana-Individual-Income-Tax-Return-Form-2/Form-2-Changes.pdf)
  says income tax simplification took effect for 2024 and that the Schedule I additions and
  subtractions are now to "federal taxable income".
- **Transition and basis.** The same sheet describes a one-time Transition Schedule (tax year 2024
  only) that "aligns federal and state reporting of capital losses, passive losses, and differing
  state and federal bases", elected by the due date of the 2024 Form 2 including extensions; without
  the election "beginning January 1, 2025, these items will default to the federal amount." The
  cause of the pre-2024 basis differences is **not stated in anything I read**. A calculator should
  not assume a Montana basis that differs from federal for 2025 and later; for 2021-2024 assets,
  check whether the taxpayer made the 2024 election. The 2025 instructions (p. ii) confirm the
  schedule was discontinued.
- **2026.** The 2025 instructions contain 2026 tax tables and the 2026 changes (HB 129, HB 337),
  none on depreciation. No 2026 Form 2 exists yet as of 2026-10-06. The 2026 row is an inference
  (rolling IRC definition, no decoupling found) and is `verified=false`.
- **Dead ends.** The 2011 SB 419 (decoupling temporary bonus depreciation, assets placed in service
  9 Sep 2010 to 31 Dec 2011) surfaced in search. Its page returned HTTP 404 and its enactment was not
  confirmed; it concerns 2010-2011 only and is not relied on. The Legislative Fiscal Division memo of
  10 Jun 2025 on H.R.1 (a House-stage summary, read) lists no depreciation provision, so it neither
  supports nor contradicts anything above.
- **Calculator rules.** (1) Use federal depreciation, 179 and bonus unchanged. (2) Add back title
  plant depreciation/amortization (code AG). (3) QBI deduction is not allowed (instructions, line 2
  text, p. 7) but that is not a depreciation rule. (4) Cannabis businesses may subtract expenses
  disallowed by IRC 280E (Schedule I line 20, p. 20). Not researched: the Montana corporate license
  tax and the pass-through entity (Form PTE) depreciation rule; no difference from the federal
  flow-through was seen but it was not checked.
- Rows: 2021-2024 and 2026 `verified=false`; 2025 `verified=true`.

## Nebraska (NE)

Individual income tax: yes (rates up to 5.20% for tax years beginning on or after 1 Jan 2025 per a
search excerpt of Neb. Rev. Stat. 77-2701.01; the page itself was not fetched).

- **Agency rule, all years 2021-2024 and the same flow-through for 2025.** Nebraska DOR page
  https://revenue.nebraska.gov/individuals/bonus-depreciation-and-enhanced-section-179-expense-deduction-nebraska-income-tax
  (read 2026-10-06): "taxpayers are not required to add-back any bonus depreciation or enhanced
  section 179 expense deduction taken on their federal return" for tax years beginning on and after
  1 Jan 2006. The only add-back regime was LB 1085 (2002) and LB 596 (2003): 85% of federal bonus
  on assets placed in service after 10 Sep 2001 and before 31 Dec 2005, and 100% of enhanced 179 for
  2003-2005, each recovered 20% a year from 2005/2006 (so fully recovered by 2010). It does not touch
  2021-2026 property. The page has no 179 limit, form line, or tax-year-2021+ content, so the 179
  limit in each row is the federal figure, inferred from "no add-back".
- **2025 (OBBBA layer).** Nebraska DOR, "Effects of the One Big Beautiful Bill Act on the State of
  Nebraska's Tax Revenue", 2 Sep 2025, read in full
  (https://revenue.nebraska.gov/sites/default/files/doc/research/Big%20Beautiful%20Bill%20-%2060%20Days%20Report%20-%20Final.pdf),
  prepared under Neb. Rev. Stat. 77-27,222: "Nebraska is a state of rolling conformity to the federal
  tax code"; "Nebraska individual income tax calculations begin with federal adjusted gross income
  (AGI); thus, any tax provisions that impact the calculation of federal AGI automatically affect the
  Nebraska individual income tax." It lists secs. 70301 (100% bonus for property "acquired and placed
  in service on or after January 20, 2025"), 70306 (179: "$2.5 million" with phase-out at "$4 million",
  inflation-indexed after 2025) and 70307 (100% for qualified production property built after 19 Jan
  2025 and before 1 Jan 2029, in service before 1 Jan 2031) and says they "result in less taxable
  income for owners of pass-through businesses, effectively lowering Nebraska tax receipts".
  Appendix A estimates General Fund effects by provision for FY2025-26 to FY2028-29. So the OBBBA
  layer controls for Nebraska 2025 on the agency's own account; Rev. Proc. 2024-40 is superseded.
- **Unresolved conflict on the statute's date.** A search excerpt of Neb. Rev. Stat. 77-2714 says the
  Code reference reads "as amended on January 1, 2024 and amendments thereto", and the Statement of
  Intent of LB 857 (2026) is excerpted as proposing to change the reference "from January 1, 2024 to
  January 1, 2026" and to make Nebraska a static-conformity state. If a fixed 1 Jan 2024 date really
  governed, OBBBA's 100% bonus and 168(n) would **not** reach 2025. DOR's report says the opposite.
  I could not fetch `nebraskalegislature.gov` (every request: `ECONNREFUSED 164.119.161.105:443`,
  retried on several URL forms), so the statute text is unread. A calculator should follow the DOR
  report for 2025 but a human should read 77-2714 and 77-2716 before relying on it.
- **2026 legislation (excerpts from nebraskalegislature.gov pages in search results, not fetched).**
  LB 853 (decouple from 168(n): add back 100% bonus on certain nonresidential structures, 2025-2028)
  and LB 857 (static conformity at 1 Jan 2026) were each reported "indefinitely postponed" on 17 Apr
  2026. DOR's 2026 legislative changes page (read,
  https://revenue.nebraska.gov/about/2026-nebraska-legislative-changes) has no depreciation or
  conformity item (only LB 748, 529 plans). The 2026 row therefore carries the 2025 treatment as the
  position absent any change and is `verified=false`.
- **Calculator rules.** Use federal depreciation, 179 and bonus unchanged; no Nebraska schedule.
  Corporate tax starts from federal taxable income and DOR names no difference. Section 70302 domestic
  R&E expensing also flows through AGI but is not depreciation. Not researched: the Nebraska
  pass-through elective entity tax (2022) depreciation treatment.
- Rows: all six `verified=false` (statute date unresolved; the cause for 2025 is the agency report
  versus the unread statute, for 2021-2024 the rolling label).

## Nevada (NV)

- **No individual income tax.** Nevada Department of Taxation,
  https://tax.nv.gov/about-nevada-department-of-taxation/income-tax-in-nevada/ (read 2026-10-06):
  "The State of Nevada does not impose a state income tax on individuals or participate in the
  administration of Federal Income Tax." and "Nevada residents do not pay state tax on income earned
  from salaries, wages, or similar compensation." The page is not year-specific and cites no
  constitutional or statutory authority, so the same sentence supports every row 2021-2026 and no
  year-specific statement exists. A sole proprietor, pass-through owner or rental owner has no Nevada
  depreciation, bonus or 179 computation, and OBBBA (P.L. 119-21) has no Nevada individual effect.
- **Entity level (differs, no depreciation rule).** Same page: "Nevada does have a Commerce Tax for
  businesses whose gross revenue exceeds $4 million in a fiscal year"
  (https://tax.nv.gov/tax-types/commerce-tax/, read: base is "gross revenue", rates vary by industry;
  it does not relate the base to federal taxable income). NRS 363C.045, seen only as a search excerpt
  of https://www.leg.state.nv.us/nrs/NRS-363C.html (fetch returned HTTP 403, NAC 363C also 403),
  defines gross revenue as the total amount realized "without deduction for the cost of goods sold or
  other expenses incurred, that contributes to the production of gross income". That implies no
  depreciation deduction in the Commerce Tax base; treat it as unverified until the statute is read.
  The Modified Business Tax (payroll, per the registry's hint) was not researched.
- Not found: the DOR Commerce Tax FAQ pages and return instructions did not contain the
  gross-revenue definition (the instructions URL redirected to the DOR home page).
- Rows: all six `verified=true` for the no-income-tax finding; the NRS excerpt is flagged inside
  `special_rules` only.

## New Hampshire (NH)

**All New Hampshire evidence is a search-result excerpt of an official page; no NH page could be
fetched (HTTP 403 on revenue.nh.gov, gc.nh.gov and gencourt.state.nh.us, including the PDFs). All six
rows are `verified=false`.**

- **Personal income tax.** New Hampshire has never taxed wages. Its Interest and Dividends Tax
  (RSA 77) reached only interest and dividends: 5% for tax periods ending before 31 Dec 2023, 4% for
  periods ending on or after 31 Dec 2023, 3% for periods ending on or after 31 Dec 2024, and "House
  Bill 2 ... repealed the Interest and Dividends Tax, effective January 1, 2025" (DRA,
  https://www.revenue.nh.gov/news-and-media/repeal-nh-interest-and-dividends-tax-now-effect,
  excerpt; also the 2025-001 technical information release on the same host). It has no depreciation
  computation, so `income_tax=false` in every row, with the I&D tax noted. The "no tax on wages"
  statement itself was not seen on a fetched page (excerpt of the registry-level DRA tax pages only).
- **Business Profits Tax (BPT, RSA 77-A), the tax that actually reaches a sole proprietor (NH-1040),
  partnership (NH-1065) or corporation (NH-1120).** Entity/business level, not a personal income tax,
  but it is the rule a NH depreciation calculator must apply:
  - RSA 77-A:3-b, I (excerpt of gc.nh.gov): "The United States Internal Revenue Code shall be applied
    without section 168(k) of such code." So **no bonus depreciation (0%)** for every year 2021-2026.
    DRA form instructions (NH-1040, NH-1065, NH-1120, NH-1041; excerpts) add that, because of the
    179 and bonus differences, "the regular depreciation allowed pursuant to IRC §167 and IRC §168
    may be different than that deducted on the federal return": a separate NH basis and schedule.
  - RSA 77-A:3-a (excerpt): IRC 179 "as provided in RSA 77-A:1, XX, except that for property placed
    in service on or after January 1, 2018, a business organization shall calculate expense deductions
    not to exceed $500,000." An instruction excerpt gives $100,000 for property placed in service in
    2017. So for 2021-2026 the NH 179 cap is **500,000**, not the federal 1,050,000 to 2,560,000 and
    not the OBBBA 2,500,000. The phase-out threshold is not stated in any text I could see; it is
    left null.
  - RSA 77-A:1, XX (excerpt): the IRC version is fixed by date: 31 Dec 2015 for periods beginning on
    or after 1 Jan 2017 and 31 Dec 2018 for periods beginning on or after 1 Jan 2020. So 2021-2026
    are all on the **31 Dec 2018** version; the conformity type is fixed (static).
  - DRA (excerpt of the 2026 tax-tips release and 2025/2026 form instructions): "For Business Tax
    purposes, New Hampshire is a static conformity state and has not adopted the provisions of the
    federal One Big Beautiful Bill Act ... remains tied to the Internal Revenue Code in effect on
    December 31, 2018." So the 2025 two-layer check ends with neither Rev. Proc. 2024-40 nor OBBBA
    governing the NH 179 limit; the statutory 500,000 cap does. 168(n) is not adopted.
  - **2026.** HB 1668 (2026), "relative to the application of the Internal Revenue Code to provisions
    of the business profits tax" (would have updated the IRC version), was reported "Inexpedient to
    Legislate" in the House on 19 Feb 2026. That status is from a secondary tracker's excerpt (legiscan
    and NHLA); the official bill page could not be read. HB 1531 (2024), allowing a BPT adjustment for
    168(k), also received "Inexpedient to Legislate" per a DRA bill-analysis excerpt.
- **Not researched:** the Business Enterprise Tax (RSA 77-E; its base is enterprise value, not net
  income), BPT rates, and the BPT filing threshold (an excerpt said 109,000 for 2026; not needed here).
- **Reading note.** The schema has no place for entity-level figures, so the BPT rule is described in
  `bonus_mechanics` and `special_rules` and the numeric columns stay null, to keep a personal-tax
  consumer from reading BPT numbers as personal-tax numbers.

## New Jersey (NJ)

Individual income tax: yes, the Gross Income Tax (GIT), which taxes income by category (net profits
from business; rents, royalties, patents and copyrights; partnership and S corporation shares; and
others). The depreciation rules below apply to those categories.

- **Primary source, read in full.** Division of Taxation, Gross Income Tax Depreciation Adjustment
  Worksheet GIT-DEP, **Revised 10/25**
  (https://www.nj.gov/treasury/taxation/pdf/current/gitdep.pdf, 6 pages) and **Revised 8/19** (read
  from the 2022 path https://www.nj.gov/treasury/taxation/pdf/partnership/2022/gitdep.pdf and the 2024 path
  https://nj.gov/treasury/unclaimed-property/treasury/taxation/pdf/other_forms/tgi-ee/2024/gitdep.pdf).
  The depreciation text of both revisions is identical except the 10/25 revision adds the affordable
  housing alternate depreciation. So the 8/19 text was the one published for the 2022 and 2024
  forms; 2021 and 2023 were not read.
- **Rule (all years).** "The Gross Income Tax Act was amended by P.L. 2004, c.65 to include Section
  5-1.2. This section applies to tax years beginning on or after January 1, 2004, and decouples the
  Gross Income Tax Act from some federal changes to depreciation and to IRC section 179 for assets
  placed in service on or after January 1, 2004." (The N.J.S.A. cite "54A:5-1.2" is my expansion of
  "Section 5-1.2" of the Gross Income Tax Act; the statute was not read.)
  - "The federal 30% Special Depreciation Allowance is allowed if the asset meets Internal Revenue
    Code requirements." (also if precluded federally by 179).
  - "The federal 50% Special Depreciation Allowance is **not** allowed."
  - "The maximum Section 179 deduction is $25,000. The federal reduced dollar limitation for asset
    cost applies and is calculated using the New Jersey maximum deduction of $25,000. There are no
    business income limitations. Unused deductions cannot be carried forward."
  - Part II column K: "The 30% special depreciation allowance is allowed only if it was taken for
    federal tax purposes. The 50% special depreciation allowance is not permitted." Columns I and J:
    NJ uses the same method and life as federal. Column E: NJ 179 capped at 25,000 "for all assets".
  - A NJ adjustment is required for assets placed in service on or after 1 Jan 2004 if federal 50%
    allowance or 179 was deducted; it is recomputed each later year until the asset is fully depreciated
    or disposed of, and also adjusts 179 recapture income and gain or loss on disposition. Unused
    adjustment cannot be carried forward, carried back or used against another category.
  - Reported on: net profits from business, a schedule attached to the NJ-1040; rents, royalties:
    NJ-BUS-1 Part IV; disposition gain or loss: Schedule NJ-DOP; partnership NJ-1065 line 13c or 15f
    (10/25; 13b or 15g under 8/19); S corporation CBT-100S Schedule K Part II line 7.
  - **Non-reporter rule (quoted in substance):** if the initially required adjustment was not reported
    (uncorrected error, or no NJ filing requirement), "the asset's New Jersey basis and allowable
    depreciation will be the same as for federal tax purposes" and no adjustment is required or
    allowable in later years.
  - Liberty Zone property: 179 max 60,000.
- **Statute and 179 date.** The Division's decoupling page
  (https://www.nj.gov/treasury/taxation/decouples2.shtml, read): P.L. 2002, c.40 "disallowed the use of
  federal bonus depreciation" for corporation business tax privilege periods starting on and after
  1 Jan 2002; P.L. 2004, c.65 "revised and extended federal bonus depreciation decoupling for
  Corporation Business Tax and for Gross Income Tax purposes" from taxable years beginning 1 Jan
  2004 or later, and "decouples both taxes from the federal calculation of section IRC 179 deductions.
  For New Jersey purposes IRC 179 deductions are now to be calculated pursuant to the federal
  Internal Revenue Code in effect on December 31, 2002." The conformity type is therefore selective
  (own income categories; federal method and life; fixed 2002 IRC for 179).
- **What is inferred, not stated.** (1) The forms name only the 30% and 50% rates. They never mention
  the 80/60/40% phase-down or the 100% rate (2017-2022, and again from 20 Jan 2025). Treating the
  100% bonus as not allowed rests on the Division's rule that 50% is not allowed, the Part II basis
  (federal basis less NJ 179 only) and the P.L. 2004 decoupling. It is nearly certain but not printed.
  (2) The 179 phase-out of **200,000** is derived: the form says the federal reduced-dollar limitation
  applies "using the New Jersey maximum deduction of $25,000", and 179 is read under the 31 Dec 2002
  Code; I did not read that Code and no NJ form prints 200,000. Left in the JSON as a derived value
  and flagged. (3) 168(n) is not mentioned anywhere; the 10/25 form (the first revision after
  P.L. 119-21) bases NJ depreciation on the federal method and life with no special allowance, so none
  is allowed in effect, but `decouples_168n` is null.
- **2025 layer check.** Rev. Proc. 2024-40 (179 at 1,250,000) and P.L. 119-21 (2,500,000, 100% bonus,
  168(n)) both fail to reach New Jersey: its 179 cap is the statutory 25,000 and it computes depreciation
  without a special allowance. The 10/25 revision (read) has no OBBBA language; the only 2025 change is
  below.
- **2025 change.** Part II(a), alternate depreciation for certain new affordable housing developments,
  "for tax years beginning on or after January 1, 2025": construction begins on or after 20 Mar 2024;
  at least 20% of units affordable; property taxes not abated or exempted under the Long Term Tax
  Exemption Law; no affordable-housing construction subsidy. Deductible share of eligible capital
  expenditure = (affordable units / total units) x 2, depreciated over a 10-year life using the federal
  method (Part II(a) column I: "Use 10-year life"). The adjustment is federal depreciation less the NJ
  alternate depreciation (line 5). The general instructions describe it by "privilege periods", which
  is corporation tax wording; the worksheet is used for GIT too, so it applies to an individual's
  rental owner.
- **2026.** No newer revision than 10/25 exists as of 2026-10-06. Search turned up NJ bills proposing
  that farm operators follow current federal depreciation (S2955, 2022 session; S2676 and A716, 2024
  session). No enactment was found, and `pub.njleg.gov` refused every connection, so the bill pages
  and their status are unread; absence of an enactment is not established.
- **Calculator rules.** (1) Federal depreciation, 179 and any bonus are first computed federally.
  (2) NJ basis = federal basis (before special allowance, 179, depreciation) less NJ 179 (cap 25,000
  per category). (3) NJ depreciation = federal method and life on that basis; no bonus. (4) Adjustment
  = federal depreciation (incl. bonus and 179) - NJ 179 - NJ depreciation, plus 179 recapture and
  disposition adjustments, one GIT-DEP per income category, re-run yearly until disposal. (5) Apply the
  non-reporter rule. (6) A calculator for a New Jersey owner of a pre-2004 asset needs no adjustment.
- Rows: all six `verified=false`, because of the inferences above (the forms and Division page that
  drive the 25,000 cap and the 50%-not-allowed rule were read in full).

## Open items for the owner

1. Read Neb. Rev. Stat. 77-2714 and 77-2716 on a reachable network, to resolve whether the Code
   reference is rolling (DOR) or dated 1 Jan 2024 (search excerpt). It decides whether Nebraska 2025
   gets the 100% bonus.
2. Fetch the New Hampshire RSA 77-A:1 XX, 3-a, 3-b text and the NH-1040/NH-1065 2025 instructions
   directly; every NH fetch returned 403. Also confirm whether the BPT 179 phase-out threshold is
   stated anywhere.
3. Confirm with NJ Division of Taxation (or the NJ-1040 instructions' business income section, which
   I did not read; the 1.5 MB PDF is saved in the session tool-results) that the 100% and 80/60/40%
   federal rates are disallowed on GIT-DEP, and that 168(n) is not allowed.
4. Montana: find the cause of the pre-2024 "differing state and federal bases" (probably in the 2023
   Form 2 instructions).
5. Nevada: read NRS 363C.045 to confirm that the Commerce Tax base has no depreciation deduction.
6. Decide whether `revenue.mt.gov` and `revenuefiles.mt.gov` should be added to the Montana entry in
   `state_registry.py` (the registry lists only `mtrevenue.gov`).
