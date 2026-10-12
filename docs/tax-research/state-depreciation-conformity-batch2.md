---
topic: State depreciation conformity, batch 2 of 6 (FL, GA, HI, ID, IL, IN, IA, KS, KY), personal income tax, tax years 2021-2026
tax_years: 2021, 2022, 2023, 2024, 2025, 2026
figures_as_of: 2026-10-05
figures_source_url: per-state URLs below (state revenue agency hosts, state legislature / statute hosts)
status: verify
---

# State depreciation conformity, batch 2 (FL, GA, HI, ID, IL, IN, IA, KS, KY)

Recorded 2026-10-05. Enacted law only. Scope is the personal income tax as it applies
to a sole proprietor, pass-through owner or rental owner; the corporate rule is noted
only where it differs. This note extends
`docs/tax-research/depreciation-macrs-179-bonus-280f-2021-2026.md` (Illinois section 6
there) and follows the conventions of
`docs/tax-research/state-depreciation-conformity-batch1.md`.

Federal reference figures (IRS citations and their own `verify` flags are in the
depreciation note above and are not re-derived here). "Conforms" below means the
federal figure for the year applies:

| Tax year | Federal bonus 168(k) | Federal 179 limit | Federal 179 phase-out start |
|---|---|---|---|
| 2021 | 100% | 1,050,000 | 2,620,000 |
| 2022 | 100% | 1,080,000 | 2,700,000 |
| 2023 | 80% | 1,160,000 | 2,890,000 |
| 2024 | 60% | 1,220,000 | 3,050,000 |
| 2025 | 100% (acquired after 19 Jan 2025); 40% earlier | 2,500,000 (OBBBA; Rev. Proc. 2024-40 said 1,250,000) | 4,000,000 (OBBBA; Rev. Proc. 2024-40 said 3,130,000) |
| 2026 | 100% | 2,560,000 | 4,090,000 |

Two federal layers for 2025: Rev. Proc. 2024-40 and then Pub. L. 119-21 (OBBBA) sec.
70301 (100% bonus), sec. 70306 (179 at 2,500,000 / 4,000,000) and sec. 70307 (new IRC
168(n) qualified production property, QPP). Where a state conformity date falls
between the two layers, the state figure follows the date, not the federal "latest".

## How this was researched, and what could not be read

- `ALLOWLIST_DOMAINS` in `tax_research_crawler.py` no longer exists (deleted in the
  2026-10-05 assistant rebuild; see batch 1). Hosts used are each state's agency
  domain from `backend/app/services/assistant/state_registry.py` (floridarevenue.com,
  dor.georgia.gov, tax.hawaii.gov, tax.idaho.gov, tax.illinois.gov, in.gov,
  revenue.iowa.gov, ksrevenue.gov, revenue.ky.gov) and each state's legislature or
  official statute site (leg.state.fl.us, gov.georgia.gov / opb.georgia.gov /
  legis.ga.gov, capitol.hawaii.gov, files.hawaii.gov, legislature.idaho.gov, ilga.gov,
  iga.in.gov, legis.iowa.gov, ksrevisor.gov, kslegislature.gov, apps.legislature.ky.gov).
  The registry is not a source of tax rules and was used for hosts only.
- **No shell was available**, so no PDF could be decoded. The fetch tool returns
  undecodable binary for agency PDFs (every Georgia, Illinois form, Iowa, Kentucky
  and Florida PDF). For those the only evidence is a search-result excerpt of the
  agency-domain document, recorded below as "agency excerpt". An excerpt is the
  agency's text as relayed by a search summary, not a page read in full.
- **Hosts that refused or blocked this session:** ilga.gov (connection refused),
  in.gov / secure.in.gov / iga.in.gov (refused or empty), ksrevenue.gov (refused),
  legislature.idaho.gov (refused), capitol.hawaii.gov and files.hawaii.gov (HTTP 403),
  data.capitol.hawaii.gov (HTTP 522). Indiana, Hawaii and Illinois statute text were
  therefore not read at all; their rules rest on agency excerpts.
- Fetch summaries were produced by a small model and sometimes paraphrased; where a
  quoted phrase below came through a fetch summary of an HTML page it is marked
  "read (summary)". Statements marked "read" were the page text as returned.
- **`verified` meaning in the JSON.** `true` only when every non-null cell in the row
  was read from statute text or an agency HTML page fetched in this session. Anything
  resting on an agency excerpt, a secondary lead, or an inference spelled out here is
  `false`. Unknown cells are `null` / `"unknown"`, never filled from an adjacent year
  or another state. Only Florida rows are `verified=true`.
- Secondary sources used for leads only and never cited as authority: Wilson Lewis,
  Windham Brannon, Warren Averett (Georgia HB 1199), RSM and EY (Idaho HB 559), Drake
  KB, Tax Foundation, COST chart, Beancount blog. A cell that rests only on one of
  those is `verified=false`; none of the final cells rests only on them, but the
  Georgia 2025 HB 1199 date and the Idaho 2025 conformity date were first found there
  and then matched to an agency excerpt.

## Summary matrix (personal income tax; bonus 168(k))

| State | Individual income tax | Bonus 2021-2026 | 179 | Conformity | 168(n) |
|---|---|---|---|---|---|
| FL | **no** | n/a (corporate only) | n/a | n/a | n/a |
| GA | yes | **none** all years | federal dollar amounts; no real-property 179 | fixed annual date | not found for the new 168(n) (open) |
| HI | yes | **none** all years | **own $25,000 / $200,000** | fixed annual date (31 Dec prior year) | 2025 outside the 31 Dec 2024 date; 2026 open |
| ID | yes | **none** all years (63-3022O) | federal (to extent claimed federally) | fixed annual date (1 Jan) | **decoupled for 2025** (HB 559) |
| IL | yes | **none** all years: add back 100%, subtract depreciation as if no bonus | federal (inferred) | rolling | **decoupled from tax years beginning 2026** (P.A. 104-0453); not 2025 |
| IN | yes | **none** all years: add back, deduct later | **own $25,000 cap**, federal phase-out | fixed (dates conflict in excerpts) | **disallowed**; QPP depreciated 39-yr; codes 120 (2025) / 157 (2026+) |
| IA | yes | **full** for tax years beginning on or after 1 Jan 2021; older assets keep Iowa basis | federal from 2020 | rolling (2023+ read) | not found |
| KS | yes | **full** (no state modification found) plus a **Kansas expensing deduction** from 2021 | federal | rolling | not found |
| KY | yes | **none**, IRC 168 frozen at 31 Dec 2001 | **own $100,000, no phase-out** from 2020 ($25,000 / $200,000 before) | fixed reference date, depreciation carved out | disallowed structurally |

## Florida (FL)

- **Individual income tax: none.** Fla. Dept. of Revenue, "The State of Florida does
  not have a personal income tax."
  https://floridarevenue.com/taxes/compliance/Pages/violations.aspx (read, 2026-10-05).
  The same page set (https://floridarevenue.com/taxes/Pages/default.aspx, read) lists
  corporate income tax, reemployment tax and sales and use tax and no personal income
  tax. Constitutional basis, Fla. Const. art. VII s. 5(a), was seen only in a search
  excerpt (the flsenate.gov and leg.state.fl.us constitution pages truncated before
  Article VII), so it is not relied on. All six years: `income_tax=false`.
- A calculator for a sole proprietor, partnership owner or rental owner has no Florida
  depreciation computation. Florida does not tax pass-through income to the individual.
- **Corporate rule (differs; for C corporations, and S corporations only on income that
  bears federal tax).** https://floridarevenue.com/taxes/taxesfees/Pages/corporate.aspx
  (read): S corporations that pay federal income tax on Line 23c of Form 1120S must
  file. Section 220.13 (http://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0200-0299/0220/Sections/0220.13.html,
  read summary): add back 100% of bonus depreciation for property placed in service
  "after December 31, 2007, and before January 1, 2027", then subtract one-seventh of
  the addition in each of the following six years (the FDOR TIP excerpt says seven
  equal parts beginning with the year of the addition). 220.13 has no 168(n) text. The
  FDOR TIPs 25C01-01 and 26C01-01 (adoption of the 2025 and 2026 IRC for corporate
  tax; PDFs unreadable) were not read; the corporate treatment of 168(n) is therefore
  unknown. This is not an individual rule and is not in the JSON rows beyond a note.
- Bonus is `"unknown"` in the JSON only because the enum has no "not applicable".

## Georgia (GA)

Individual income tax: yes (not separately sourced; the questions concern depreciation).

- **Bonus: none, every year.** DOR page "Income Tax Federal Tax Changes"
  (https://dor.georgia.gov/taxes/tax-rules-and-policies/income-tax-federal-tax-changes,
  read 2026-10-05): "Georgia has also not adopted the following: 30%, 50%, and 100%
  bonus depreciation rules, I.R.C. Section 168(k)", and the 2020 note that for tax years
  beginning on or after 1 Jan 2019 Georgia adopted the CARES Act 15-year life for
  qualified improvement property "but Georgia has not adopted bonus depreciation". The
  same page lists "50% bonus depreciation in connection with disasters federally
  declared after 2007, I.R.C. Section 168(n)" as not adopted; that is the **old**
  168(n) (disaster property), not the OBBBA qualified production property provision of
  the same number.
- **Mechanics.** 2025 Georgia Form 4562 instructions (Rev. 08/01/25 then Rev. 07/08/26,
  https://dor.georgia.gov/document/document/2025-4562-depreciation-amortization-including-information-listed-property/download;
  PDF unreadable, **agency excerpt**): depreciation is computed one way for federal and
  another for Georgia, the current-year federal Form 4562 is attached, and federal
  depreciation is added back on the "other addition" line of the return. The matching
  subtraction line for Georgia depreciation was not seen. Georgia "does not allow any
  additional depreciation benefits provided by I.R.C. Section 168(k), 1400L,
  1400N(d)(1), and certain other provisions" (excerpt).
- **Section 179.** Page above (read): 2021 "Georgia has adopted the increased I.R.C.
  Section 179 deduction of $1,050,000 as well as the $2,620,000 phaseout", and "Georgia
  has not, however, adopted the Section 179 deduction for certain real property".
  Form 4562 instruction excerpts: 2022 $1,080,000 (limit) / $2,700,000 (threshold);
  2023 $1,160,000; 2024 $1,220,000 (the 2023 and 2024 phase-out figures were not seen;
  the federal figures in the table above are not substituted); 2025 **$2,500,000 /
  $4,000,000** in the Rev. 07/08/26 instructions. An earlier excerpt of the Rev.
  08/01/25 instructions showed $1,250,000 / $3,130,000 for 2025, the pre-OBBBA
  figures. The July 2026 revision is the one that post-dates HB 1199 (signed
  20 Mar 2026), so 2025 is recorded at $2,500,000 / $4,000,000 with that conflict
  stated. 2026: no Georgia document found; limit null.
- **Conformity: fixed to a date, updated by an annual bill, with exceptions.** From the
  DOR page (read): HB 1320 (signed 2 May 2022) tax years beginning on or after 1 Jan
  2021, federal law "enacted on or before January 1, 2022"; HB 95 / SB 56 (signed 2 May
  2023) "enacted on or before January 1, 2022" for tax years from 1 Jan 2022; HB 1162
  (signed 22 Apr 2024) tax years from 1 Jan 2023, federal law "enacted on or before
  January 1, 2024". 2024: HB 290 (effective 14 May 2025, tax years from 1 Jan 2024,
  federal law through 1 Jan 2025), from the DOR 2025 Summary of Enacted Legislation
  (PDF, search excerpt only). 2025: HB 1199 (signed 20 Mar 2026), "federal law enacted
  on or before January 1, 2026" per the DOR 2026 Employer's Withholding Tax Guide
  (excerpt) and the Governor's release
  https://gov.georgia.gov/press-releases/2026-03-20/gov-kemp-signs-major-tax-relief-bills-hardworking-georgians
  (read: "aligns Georgia's Internal Revenue Code with federal tax law"; no depreciation
  detail). Tax-year applicability "beginning on or after 1 Jan 2025" came from a
  secondary summary only. 2026 is recorded as the date currently enacted (1 Jan 2026);
  a 2027 bill may move it.
- **168(n) QPP:** not stated in any Georgia document found. DOR's wording ("does not allow
  any additional depreciation benefits provided by 168(k) ... and certain other
  provisions") suggests a decoupling but does not name the new 168(n). `decouples_168n`
  is null for 2025 and 2026.
- **Special rules for a calculator:** (1) no 179 on qualified real property (read);
  (2) QIP uses the 15-year life from 2019 with no bonus (read); (3) Georgia basis and
  depreciation differ from federal, so a separate Georgia asset schedule is needed.
- All Georgia rows `verified=false`.

## Hawaii (HI)

Individual income tax: yes (also the general excise tax on gross receipts, a separate
tax not covered here).

- **Bonus: none, every year.** HRS 235-2.4: section 168 is operative "except that
  sections 168(j) ..., 168(k) (relating to the special allowance for certain property
  acquired during the period specified therein), and 168(m)" are not operative
  (search excerpts of the DOTAX compilation of Chapter 235 as of 12/31/2025,
  https://files.hawaii.gov/tax/legal/hrs/hrs_235.pdf; PDF and capitol.hawaii.gov
  statute pages returned 403). Instructions for Form N-11 (2025,
  https://files.hawaii.gov/tax/forms/current/n11ins.pdf, excerpt): Hawaii did not adopt
  "bonus depreciation, increased IRC section 179 deduction (Hawaii limit is $25,000),
  and inclusion of off-the-shelf computer software as property qualifying for the IRC
  section 179 deduction"; the taxpayer must complete a federal Form 4562 for Hawaii
  purposes, attach it, make the necessary adjustment for the depreciation difference
  and attach the worksheet. Exact add-back and subtraction lines were not seen.
- **Section 179: own limit.** $25,000 aggregate cost, and the reduction begins when
  the cost of 179 property exceeds $200,000 (excerpt of the HRS wording "shall not
  exceed $25,000 ... shall exceed $200,000", and the 2024 and 2025 N-11 / N-40
  instructions). A DOTAX announcement excerpt (Announcement 2003-10) says the $25,000
  limit applies to property placed in service after the 2002 tax year. Phase-out is
  dollar for dollar (derived from the federal 179(b)(2) mechanics, not quoted).
- **Conformity: fixed, advanced by an annual act to 31 December of the prior year.**
  Dates: 2022 31 Dec 2021 (excerpt of the statute text); 2023 31 Dec 2022 (Act 56, SLH
  2023); 2025 **31 Dec 2024** (Act 123, SB 1464 CD1 / HB 1145, signed 29 May 2025,
  applies to taxable years beginning after 31 Dec 2024; Legislature measure-status
  page excerpt); 2026 **31 Dec 2025** (Act 35, HB 2329, effective 26 May 2026, applies
  to taxable years beginning after 31 Dec 2025; DOTAX announcement 26-06 excerpt, page
  403). 2021 and 2024 dates are inferred from the amendment series ("the 2021
  amendment applies to taxable years beginning after December 31, 2020", and the 2024
  amendment likewise) and are not quoted.
- **OBBBA / 168(n).** 168(n) was enacted 4 Jul 2025, after the 31 Dec 2024 date, so it
  is not part of Hawaii's IRC for 2025 (derived from the dates, not a stated rule).
  Act 35 amended 235-2.3(b), 235-2.4 and 235-2.45 in response to OBBBA, but the
  excerpts do not say whether 168(n) was made non-operative. The 12/31/2025 compilation
  lists only 168(j), (k) and (m) as non-operative. 2026 `decouples_168n` is null.
- All Hawaii rows `verified=false`.

## Idaho (ID)

Individual income tax: yes.

- **Bonus: none, every year.** "Bonus depreciation (section 168(k)) is a separate issue
  and Idaho doesn't conform to that section", https://tax.idaho.gov/governance/statutes/irc/
  (read). Idaho Code 63-3022O (agency page https://tax.idaho.gov/bonus-depreciation/,
  read, cites it as "Adjustment - Property acquired after September 10, 2001"): for
  2008-2009 acquisitions "Idaho conforms to the federal bonus depreciation provisions.
  The amounts you use for federal purposes will also be used for Idaho"; otherwise
  depreciation is computed separately and the differences reported. Statute excerpt of
  H0559 (2026) and 63-3022O: depreciation, adjusted basis and gain or loss on
  depreciable property "acquired after December 31, 2009 shall be computed without
  regard to subsections (k) and (n) of section 168" (search excerpt of
  https://legislature.idaho.gov/statutesrules/idstat/title63/t63ch30/sect63-3022o/ and
  https://legislature.idaho.gov/wp-content/uploads/sessioninfo/2026/legislation/H0559.pdf;
  the site refused connections). Mechanics: a separate Idaho depreciation computation
  with additions (federal bonus claimed) and subtractions (Idaho depreciation not
  claimed federally); `addback_pct` 100 is derived from "computed without regard to".
- **Section 179:** "You can claim the IRC section 179 expense on your Idaho return to
  the extent you claim this deduction on your federal income tax return" (agency
  excerpt, 2024-25 instructions), so the federal amounts apply for the year. The
  conformity page (read) notes the 2018 increase to $1 million was adopted.
- **Conformity: fixed to 1 January of the tax year, updated annually.** Read at
  https://tax.idaho.gov/governance/statutes/irc/: 2021 1 Jan 2021, 2022 1 Jan 2022,
  2023 1 Jan 2023, 2024 1 Jan 2024. 2025: **1 Jan 2026** (H.B. 559, signed 10 Feb 2026,
  retroactive to 1 Jan 2025; agency instruction excerpt "Idaho conforms to the IRC as of
  January 1, 2026, with notable exceptions including bonus depreciation"; the page
  itself does not carry 2025-2026). 2026: 1 Jan 2026 as enacted (derived).
- **168(n) and OBBBA (2025).** HB 559 adopts the OBBBA 179 increase ($2,500,000 /
  $4,000,000; secondary, consistent with the IRC date) but decouples from 168(n).
  Idaho 2025 Form 39R instructions (excerpt, tax.idaho.gov): for QPP "construction
  begins after January 19, 2025, and before January 1, 2029 ... placed in service
  before January 1, 2031" the taxpayer completes a separate Form 4562 or calculation
  "as if you hadn't claimed the special depreciation allowance". `decouples_168n` true
  for 2025 and 2026.
- **Special rules:** the 2008-2009 acquisition exception above; keep a separate Idaho
  asset schedule for every post-2009 asset.
- All Idaho rows `verified=false` (agency excerpts and unreachable statute host).

## Illinois (IL)

Individual income tax: yes (IL-1040). Builds on section 6 of the depreciation note.

- **Bonus: none; add back 100%, subtract depreciation as if no bonus.** 2025 Form
  IL-4562 instructions
  https://tax.illinois.gov/forms/incometax/currentyear/iit-bit-shared-forms/il-4562-instr.html
  (read, summary): the form reverses bonus allowed under 168(k) and (n) (30, 40, 50,
  60, 80 or 100%); Line 1 is the special depreciation claimed on federal Form 4562
  Lines 14 and 25 for property acquired after 10 Sep 2001; Line 2 individuals' Form
  2106; the total goes on Schedule M. Subtraction lines by federal rate: 30% (Lines
  7a/7b), 40% for property placed in service after 31 Dec 2024 and before 20 Jan 2025
  or in the first taxable year ending after 19 Jan 2025 (Lines 9a/9b; "for taxpayers
  who claimed 40 percent bonus depreciation federally for eligible property placed in
  service prior to January 1, 2025, no subtraction is allowed" on those lines), 50%
  (Lines 11a/11b), 60% for property placed in service after 31 Dec 2023 and before 1 Jan
  2025 (Lines 12a/12b), 80% for property placed in service after 31 Dec 2022 and before
  1 Jan 2024 (Lines 14a/14b), and 100% (Line 16: "the amount of federal depreciation
  you would have claimed for this taxable year had you made the election under IRC
  Section 168(k)(7)"). A search excerpt of the form says the 30% line multiplies the
  entered depreciation by 42.9 percent (the ratio of the bonus to the remaining basis);
  the multipliers for the other percentages were not seen and the form PDF would not
  decode. Statute: 35 ILCS 5/203 as excerpted by search (statute site refused
  connections): addition for "taxable years 2001 through 2025" of "the bonus
  depreciation deduction taken on the taxpayer's federal income tax return ... under
  subsection (k) of Section 168"; "for taxable years 2026 and thereafter ... (k) or (n)";
  subtraction, for the year of the bonus and each later year, of the depreciation
  "that would be allowed on that property if the taxpayer had made the election under
  Section 168(k)(7) or Section 168(n)(6) ... to not claim bonus depreciation".
  Recovery is therefore over the asset's own recovery period, not a fixed N years;
  `recovery_years` is null.
- **Section 179:** not stated. Individuals reporting 179 on Form 2106 report only the
  bonus part on IL-4562 (instructions, read), and no 179 line appeared in Schedule M or
  IL-4562, so Illinois appears to follow the federal 179 deduction; that is an
  inference. `sec179_conforms=true` is flagged unverified.
- **Conformity: rolling.** 35 ILCS 5/102 (search excerpt): federal terms mean the
  Internal Revenue Code "as such Code, laws and statutes are in effect for the taxable
  year". Not read in full.
- **2025 (OBBBA layer).** The federal 100% bonus acquired after 19 Jan 2025 is added back
  in full on Line 16 under the existing 168(k) addition; this is not a change. 168(n)
  QPP is **not** added back for tax year 2025 (the 2025 range in 203 names only (k)).
- **2026.** Public Act 104-0453 amended IITA 203 "to decouple Illinois from federal 100
  percent bonus depreciation claimed under IRC Section 168(n)" for tax years beginning
  on or after 1 Jan 2026 (Informational Bulletin FY 2026-15, December 2025,
  https://tax.illinois.gov/research/publications/bulletins/fy-2026-15.html, read).
  IL-4562 Line 16 for 2026: depreciation "had you not made the election to claim bonus
  depreciation on your federal return"; for property placed in service after 4 Jul
  2025 and before 1 Jan 2031 the 168(n)(6) election governs (instructions, read).
- **Special rules:** (1) in the final depreciation year (asset sold or fully depreciated)
  reverse all prior additions and subtractions (Lines 3 and 18); (2) no carryover of an
  unused subtraction (existing note, agency excerpt of the 2023 instructions); (3) for
  a passenger automobile where the federal bonus pushes depreciation past the 280F
  cap, Illinois subtractions use the regular depreciation percentages even if total
  Illinois depreciation exceeds the cap, and on disposition all additions and
  subtractions reverse; (4) individuals using Form 2106 split 179 from special
  depreciation.
- All Illinois rows `verified=false` (statute not read; 2021-2022 mechanics rest on the
  2025 instructions' wording that covers property placed in service after 10 Sep 2001).

## Indiana (IN)

Individual income tax: yes. **Statute and bulletin text could not be read**: in.gov,
secure.in.gov and iga.in.gov refused connections or returned only a header. Everything
below is from agency-domain search excerpts of Information Bulletin 118 and the add-backs
page; every Indiana row is `verified=false`.

- **Bonus: none.** IC 6-3-1-3.5(b) and IC 6-3-1-33 (bonus defined as the part of the
  depreciation allowance attributable to the 168(k) additional first-year allowance);
  taxpayers must "add or subtract an amount necessary to make their adjusted gross
  income equal to the amount computed without applying any bonus depreciation"
  (excerpt of https://www.in.gov/dor/files/ib118.pdf; also
  https://www.in.gov/dor/i-am-a/individual/indiana-add-backs/). The excerpt also says
  this decoupling dates from 2002. Mechanics: add back in the first year the federal
  bonus; in later years deduct the extra depreciation that federal basis no longer
  carries. `addback_pct` 100 is derived from "equal to the amount computed without".
  Reporting code 105 for 179 and bonus add-backs and deductions.
- **Section 179: own $25,000 cap.** "Indiana caps the overall Indiana Section 179
  Allowance at $25,000 against such property"; the first-year difference is an add-back
  and later years allow the difference in depreciation; "Indiana follows the federal
  phase-out thresholds" (IB 118 excerpt; the excerpt quotes "$2,500,000 ... adjusted for
  inflation as opposed to the pre-2003 $200,000 threshold", an older base figure, so
  the per-year Indiana threshold is not recorded: `sec179_phaseout` null).
- **Conformity: fixed to a date.** IT-40 booklet excerpts (forms.in.gov) say for 2024
  that Indiana had not conformed to IRC changes after 1 Jan 2024, and for 2025 after
  1 Jan 2023; an IC 6-3-1-11 excerpt says "in effect on January 1, 2023". These
  conflict and are recorded as unverified; the dates for 2021-2023 were not found.
- **168(n) QPP: disallowed.** IB 118 is now titled "Bonus Depreciation, Section 179
  Expensing, and Qualified Production Property Treatment" (search listing). A taxpayer who
  elected 168(n) expensing adds back the expensing in the year placed in service and
  deducts depreciation computed as if no election had been made in later years; for
  Indiana the property is depreciated as nonresidential real property, straight line
  over 39 years, mid-month. Use "Code 120" for 2025 only and "Code 157" for 2026 and
  later. Senate Enrolled Act 243 (2026) extended the decoupling to QPP "beginning in
  taxable year 2026" (excerpt). Why Code 120 exists for 2025 if the decoupling began in
  2026 was not resolved; for 2025 the 31 Dec 2022-style date in the booklets would
  also exclude a July 2025 provision. `decouples_168n` true for both years, unverified.

## Iowa (IA)

Individual income tax: yes.

- **Bonus: full for tax years beginning on or after 1 Jan 2021.** IA 4562A instructions
  (agency excerpts of https://revenue.iowa.gov/media/2741/download and
  https://revenue.iowa.gov/media/4407/download, PDFs unreadable): "For tax years
  beginning on or after January 1, 2021, Iowa fully conforms with bonus depreciation
  under IRC section 168(k). No adjustments are required on this form for property
  placed in service during a tax year that begins on or after January 1, 2021 if bonus
  depreciation was taken on the property for federal purposes."
- **Property placed in service before tax year 2021 keeps Iowa-basis depreciation.** The
  agency page "Conformity with the Internal Revenue Code"
  https://revenue.iowa.gov/taxes/tax-guidance/individual-income-tax/1040-expanded-instructions/conformity-irc
  (read) lists "depreciation for certain assets placed in service before tax year 2021,
  section 179 special election deductions, and the business interest expense limitation"
  as examples of differences. A calculator therefore needs the IA 4562A / 4562B
  adjustment for each pre-2021 asset (no new bonus add-back from 2021).
- **Section 179: conforms from 2020.** "For tax years beginning on or after January 1,
  2020, Iowa fully conforms to the federal section 179 deduction and special Iowa
  treatment for excess section 179 deductions received from pass-throughs is not
  available" (IA 4562A excerpt). One search summary said increased expensing applies for
  assets placed in service "on or after January 1, 2023"; that conflicts with the 2020
  statement and was not confirmed. Federal amounts are recorded.
- **Conformity: rolling.** "For tax years beginning on or after January 1, 2023, the
  starting point for taxation is federal taxable income. Iowa has also adopted rolling
  conformity ... except as specified by Iowa law" (page above, read). For 2021 and 2022
  `rolling` rests on a fetch summary of Iowa Code 422.3(5) (for tax years on or after
  1 Jan 2020, "the Internal Revenue Code of 1986, as amended") at
  https://www.legis.iowa.gov/docs/code/2026/422.html, which was not clean.
- **2025-2026 / OBBBA:** no Iowa decoupling from 168(k), 168(n) or 179 found in the
  agency pages, the OBBBA withholding page
  (https://revenue.iowa.gov/taxes/tax-guidance/withholding-tax/impact-one-big-beautiful-bill-act-employee-withholding,
  read; it covers tips, overtime, car-loan interest and the senior deduction only) or
  the 2025 IA 4562A excerpt. This is absence of evidence; `decouples_168n` is null.
  SF 551 (2023) was an introduced decoupling bill and was not enacted as far as the
  agency pages show. Not verified.
- All Iowa rows `verified=false`.

## Kansas (KS)

Individual income tax: yes.

- **Bonus and 179: no state modification found; plus a state expensing deduction.**
  K.S.A. 79-32,117(a): "Kansas adjusted gross income of an individual means such
  individual's federal adjusted gross income for the taxable year, with the
  modifications specified in this section"
  (https://ksrevisor.gov/statutes/chapters/ch79/079_032_0117.html, read, summary). The
  summary of the modifications found none for 168 or 179 (only handicapped-access
  and swine and habitat items), history to L. 2024 ch. 1 sec. 18 (Special Session). This
  is a negative reading of a fetch summary and is why bonus is "full" unverified.
- **Kansas expensing deduction, K.S.A. 79-32,143a** (https://ksrevisor.gov/statutes/chapters/ch79/079_032_0143a.html,
  read, summary; history ends L. 2021 ch. 93 sec. 13): for 2013-2020 only corporations
  and banking entities; "A taxpayer may elect to take an expense deduction from Kansas
  net income" for taxable years beginning after 31 Dec 2020 (all taxpayers). Amount
  (search excerpt of the statute and K-120EX): the depreciable cost of the property for
  federal purposes less the sum of the 168(k) bonus claimed and the 179 deduction
  claimed, multiplied by an applicable factor from a table by recovery period (2.5 to
  25 years) and method (factors .075 to .449). Qualified property: tangible MACRS
  property and computer software placed in service in Kansas, excluding residential
  rental property, nonresidential real property, railroad grading or tunnel bore and
  property with a recovery period over 25 years. Claim only in the year placed in
  service (2025 K-120EX excerpt). Recapture as Kansas income on a sale during the
  recovery period; an excess over Kansas net income is a Kansas NOL (79-32,143). K-120EX
  forms exist for 2021 through 2025 (search listing of ksrevenue.gov); the factor
  table itself was not copied and must be read before coding.
- **Conformity: rolling** (structural, from "federal adjusted gross income for the
  taxable year"; no fixed-date IRC definition appeared in the text read).
- **2025-2026 / 168(n):** no Kansas statute or notice naming 168(n) or changing
  depreciation after OBBBA was found (searches of ksrevenue.gov, ksrevisor.gov,
  kslegislature.gov; HB 2231 (2025) concerns personal exemptions and apportionment,
  and SB 296 (2025) was only seen as a proposal to amend 79-32,117). `decouples_168n`
  null. Secondary leads say Kansas conforms to 168(n); not accepted.
- All Kansas rows `verified=false`.

## Kentucky (KY)

Individual income tax: yes.

- **Bonus: none, every year.** KRS 141.0101 (search excerpt of
  https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=57945; the page itself
  returned an undecodable PDF): for property placed in service after 10 Sep 2001 "only
  the depreciation deduction allowed under Section 168 of the Internal Revenue Code in
  effect on December 31, 2001, exclusive of any amendments made subsequent to that
  date, shall be allowed". So no bonus, and any MACRS change after 2001 (for example the
  15-year life for qualified improvement property) is also outside Kentucky law; that
  second point is derived from the reference date, not stated by DOR. KRS 141.010(21)
  applies the updated IRC date "except for depreciation differences per KRS 141.0101".
  DOR corporation and partnership instructions (revenue.ky.gov excerpts): any taxpayer
  that elected MACRS bonus or 179 above the Kentucky limit "will have a different
  depreciation and IRC section 179 expense deduction for Kentucky". Mechanics: keep a
  Kentucky basis and depreciation schedule, add back federal depreciation and 179,
  subtract Kentucky depreciation; the form line names were not read.
- **Section 179: own limit.** DOR Form 720 instructions (10-20), excerpt
  https://revenue.ky.gov/Forms/Form%20720%20Instructions%20(10-20).pdf: for property
  placed in service after 10 Sep 2001 and before 1 Jan 2020, $25,000 maximum and
  $200,000 threshold; for property placed in service on or after 1 Jan 2020,
  "$100,000 and the phase-out threshold does not apply". The statute excerpt says the
  2020-and-later rule is the 179 allowed under the IRC "in effect on December 31, 2003",
  which is a $100,000 limit under that Code; the Dec 2003 Code also had a $400,000
  threshold, so the DOR statement that no threshold applies conflicts with the statute
  wording on that one point. `sec179_phaseout` is null.
- **Conformity: fixed reference date, updated each session.** Search excerpts of DOR
  instructions: 2021 31 Dec 2021 (HB 8), 2022 31 Dec 2022 (HB 360), 2023 31 Dec 2023
  (HB 8, 2024 RS); 2024 31 Dec 2023 (implied by HB 775, which moved it from 31 Dec 2023
  to 31 Dec 2024 for tax years beginning on or after 1 Jan 2025); 2025 **31 Dec 2024**
  (HB 775, 2025 RS, LRC bill page read: "update the Internal Revenue Code reference
  date", date not on the page); 2026 **31 Dec 2025** (HB 757, 2026 RS, enacted as Acts
  ch. 161 after veto override on 14 Apr 2026; https://apps.legislature.ky.gov/record/26rs/hb757.html,
  read). HB 757 also decouples from the OBBBA tips, overtime and vehicle-loan items; no
  depreciation text was found in the digest.
- **168(n):** disallowed structurally (Section 168 frozen at 2001). No Kentucky text names
  168(n).
- All Kentucky rows `verified=false`.

## Proposed engine entries

None. These are per-state, per-year rules with different authority paths, not single
constants for `tax_authority.py`. If a state depreciation module is built, enter every
cell as `verified=False` until a human has checked it against primary text, and read the
agency instruction (Georgia, Illinois, Indiana, Iowa, Kentucky, Hawaii) from a decoded
copy first.

## Open items

1. **Illinois:** read 35 ILCS 5/203(a)(2)(D-5), (D-10) and 5/102 from ilga.gov; get every
   IL-4562 multiplier (only 42.9% for 30% was seen); confirm no 179 modification.
2. **Indiana:** read IB 118, IC 6-3-1-3.5, IC 6-3-1-11 (conformity date by year, and the
   conflict between the 2024 and 2025 booklet excerpts), SEA 243 (2026) and why Code
   120 exists for 2025.
3. **Hawaii:** read HRS 235-2.3, 235-2.4 (current) and Act 35 (2026) from a host that
   answers; decide 168(n) for 2026 and whether Act 35 touched 179; get the N-11
   adjustment line names.
4. **Georgia:** read the 2025 Form 4562 instructions (Rev. 07/08/26) from a decoded copy
   for 2026 179 amounts and the new 168(n); find the Georgia subtraction line; confirm
   the 2023 and 2024 phase-out figures; read HB 1199 and HB 290 text.
5. **Idaho:** read 63-3004, 63-3022O and H0559 from legislature.idaho.gov for the
   exact 2025 text, the Idaho 2026 conformity date, and the 2025 form 39R instruction.
6. **Iowa:** confirm 422.3(5) for 2021-2022, the 179 conflict (2020 versus 2023), and
   whether any 2025-2026 act decoupled from 168(n) or the OBBBA 179 increase.
7. **Kansas:** read the factor table in 143a and K-120EX for 2025/2026; confirm no
   2025-2026 depreciation change and the status of SB 296 (2025).
8. **Kentucky:** read KRS 141.0101 and 141.010(21) text, resolve the 179 threshold
   conflict, and find the Kentucky form lines for the depreciation difference.
9. **Florida:** corporate treatment of 168(n) (TIP 25C01-01 and 26C01-01) if a C
   corporation module is ever built; constitutional text of art. VII s. 5(a).
10. Federal inputs (2021-2022 bonus, 2021/2023 179) carry the `verify` flags of the
    depreciation note.
