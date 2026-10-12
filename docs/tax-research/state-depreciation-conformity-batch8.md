---
topic: State depreciation conformity, batch 8 (SD, TN, TX, UT, VT), personal income tax, tax years 2021-2026
tax_years: 2021, 2022, 2023, 2024, 2025, 2026
figures_as_of: 2026-10-06
figures_source_url: per-state URLs below (state agency hosts and state legislature / statute sites)
status: verify
progress: COMPLETE. SD, TN, TX, UT, VT done (6 rows each, 30 in the JSON). UT is all verified=false (legislature host unreachable); TN/TX/VT 2026 and TN 2025 are verified=false.
---

# State depreciation conformity, batch 8 (SD, TN, TX, UT, VT)

Recorded 2026-10-06. Enacted law only. Scope is the personal income tax as it applies to a sole proprietor,
pass-through owner or rental owner. Federal reference figures come from
`docs/tax-research/depreciation-macrs-179-bonus-280f-2021-2026.md` and are not re-derived here.

| Tax year | Federal bonus 168(k) | 179 limit | 179 phase-out start |
|---|---|---|---|
| 2021 | 100% | 1,050,000 | 2,620,000 |
| 2022 | 100% | 1,080,000 | 2,700,000 |
| 2023 | 80% | 1,160,000 | 2,890,000 |
| 2024 | 60% | 1,220,000 | 3,050,000 |
| 2025 | 100% acquired after 19 Jan 2025; 40% earlier (P.L. 119-21 s.70301 over Rev. Proc. 2024-40) | 2,500,000 (OBBBA s.70306; RP 2024-40 said 1,250,000) | 4,000,000 (RP 2024-40 said 3,130,000) |
| 2026 | 100% | 2,560,000 | 4,090,000 |

## How this is researched

- `ALLOWLIST_DOMAINS` in `tax_research_crawler.py` no longer exists (file deleted in the 2026-10-05 rebuild).
  Agency hosts come from `backend/app/services/assistant/state_registry.py`: SD dor.sd.gov, TN tn.gov /
  www.tn.gov, TX comptroller.texas.gov, UT tax.utah.gov, VT tax.vermont.gov. Legislature or statute sites are
  named where used (Texas Register at sos.state.tx.us for TX). TN's help center (revenue.support.tn.gov) is a
  tn.gov subdomain run by the same agency. Utah's income tax site incometax.utah.gov is a Tax Commission site not
  literally in the registry (tax.utah.gov is); treated as the same agency.
- This session has no Bash tool. `WebFetch` saves PDFs it cannot parse under the session `tool-results`
  folder; `Read` on that path with no `pages` argument returns the text. Huge PDFs (the 7.4 MB Tennessee
  Franchise & Excise Tax Manual) were not read. `statutes.capitol.texas.gov` returned only its navigation page.
  `le.utah.gov` (Utah Legislature) and `legislature.vermont.gov` statute pages refused every connection and most
  `tax.utah.gov` PDFs returned HTTP 403 or 404.
- `verified` is true only when the key cells (bonus, conformity, 179 conformity) were read from statute or agency
  text for that year. Federal limits for a state that conforms are carried as inherited and say so, following
  batch 7.
- A state with no individual income tax gets `income_tax=false`, `bonus="unknown"` (the enum has no n/a) and
  `conformity_type="n/a"`, as in batch 2 (Florida). Where the entity-level tax has its own rule (TN excise, TX
  franchise) that rule is described in `bonus_mechanics` and the `bonus` enum reflects it.

## Summary matrix

| State | Individual income tax | Bonus | 179 | Entity-level note |
|---|---|---|---|---|
| SD | none | n/a | n/a | no corporate income tax either |
| TN | none (Hall tax repealed from 1 Jan 2021) | excise tax: none for assets purchased through 2022; TCJA schedule 80/60/40/20% for 2023-2026 purchases, 0% from 2027 (NOT the OBBBA 100%) | follows federal return; OBBBA amounts not addressed | 6.5% excise tax on LLCs, LPs, corporations |
| TX | none | franchise COGS: none through TY2024 (2007 IRC); follows federal return, incl. 100% bonus, from TY2025 (2026 report) | 2007 IRC 25,000/200,000 through TY2024; federal from TY2025 | margin tax; sole proprietors and natural-person GPs exempt |
| UT | yes | follows federal (rolling), incl. OBBBA 100% for 2025-2026 (unverified: statute unreadable) | follows federal | no entity-level difference found |
| VT | yes | none, all years: add back federal depreciation minus normal MACRS in year 1, subtract the difference later (no spread) | follows federal; OBBBA amounts inferred | 168(n) also denied from TY2025 |

## South Dakota (SD)

No individual or corporate income tax in any of 2021-2026. Agency text (read 2026-10-06):
"South Dakota is one of seven states that does not impose a state income tax." (https://dor.sd.gov/individuals/taxes/)
and "South Dakota does not impose a corporate income tax." (https://dor.sd.gov/businesses/taxes/).
A calculator should compute no South Dakota depreciation adjustment; federal depreciation stands alone.
The bank franchise tax on financial institutions is outside the scope of a sole proprietor, pass-through
or rental owner. Both pages are undated, so the rule is read as standing; no source suggesting an income tax
was enacted for 2021-2026 was found. verified=true for all six rows.

## Tennessee (TN)

**Personal income tax: none for 2021-2026.** TN DOR: "The Hall Income tax was repealed for tax periods that begin
on January 1, 2021, or later" (https://www.tn.gov/revenue/taxes/hall-income-tax.html, read 2026-10-06). The Hall tax
reached only interest from bonds and notes and dividends from stock, never wages or business profit.

**Entity-level excise tax (6.5% of net earnings)** applies to corporations, limited partnerships, LLCs and
business trusts (https://www.tn.gov/revenue/taxes/franchise---excise-tax.html; the page does not list sole
proprietorships or general partnerships). That is where depreciation conformity bites for a pass-through owner.

- **Assets purchased on or before 31 Dec 2022 (so all of tax years 2021 and 2022):** bonus depreciation disallowed.
  Notice #23-07: "For assets purchased on or before December 31, 2022, bonus depreciation deductions continue to be
  disallowed." Add back the disallowed 168 depreciation and deduct MACRS on the added-back basis in later years,
  with a basis adjustment to gain or loss on sale (2024 FAE174 instructions, Sch. J lines 6, 20, 21).
- **Assets purchased on or after 1 Jan 2023:** Pub. Ch. 377 (2023) coupled to the TCJA bonus schedule, if bonus is
  taken federally: 80% (2023), 60% (2024), 40% (2025), 20% (2026), 0% (2027 and after) (Notice #23-07; restated in
  Notice #25-36).
- **OBBBA (P.L. 119-21) response:** none. Notice #25-36 (Dec 2025): "Tennessee remains coupled with the TCJA bonus
  depreciation provisions ... taxpayers must continue to apply the bonus depreciation applicable percentages set
  forth in the TCJA bonus depreciation schedule." Worked example: USD 50,000 asset placed in service 1 Aug 2025,
  100% federal, 40% allowed, add back USD 30,000 on Sch. J line 3, depreciate it under MACRS on line 16. Qualified
  production property (IRC 168(n)) gets no bonus at all and is depreciated as federal MACRS nonresidential real
  property. Citation in the notice: Tenn. Code Ann. 67-4-2006(a)(12).
- **Legislative check:** 2025 summaries list only Pub. Ch. 343 and 455 for F&E; 2026 summaries list only Pub. Ch. 616
  (eff. 1 Jul 2026) and Pub. Ch. 1009 (eff. 1 Jan 2027). Neither touches depreciation. A TSCPA page (secondary) says
  SB 32 / HB 477, which would allow a 40% annual bonus election for 2026 purchases, died in committee.
- **Section 179:** TN ET-3 (search excerpt, direct fetch 403): "Internal Revenue Code (IRC) Section 179 depreciation
  expense may be deducted for Tennessee excise tax purposes to the same extent that it was deducted on the
  corresponding federal income tax return." Partner-level 179 limits are disregarded; the entity applies the limit
  (FAE174 instructions Sch. J1). Whether the OBBBA 2,500,000 / 4,000,000 amounts carry through for 2025 is not
  stated anywhere found, so the 2025 and 2026 rows are verified=false.

Open: TN 2021-2024 rows say verified=true because the bonus cells were read in full from agency PDFs; the 179 cell
rests on the ET-3 excerpt and inherited federal figures. The notice uses "purchased"; the federal phase-down turns on
placed-in-service date, and a purchase and in-service straddling a year end is not resolved by the notice.

## Texas (TX)

**Personal income tax: none.** No agency sentence was found saying so in those words; the Comptroller's tax list has no
such tax and its Fiscal Notes cite Tex. Const. art. VIII s.24-a (voter approval needed for a net income tax on natural
persons). Depreciation matters only to the entity-level **franchise (margin) tax**, and only if the entity takes the
cost-of-goods-sold (COGS) deduction. Sole proprietorships (except single-member LLCs) and general partnerships wholly
owned by natural persons are not taxable entities (Franchise Tax Overview 98-806,
https://comptroller.texas.gov/taxes/publications/98-806.php). Report year N covers the accounting year ending in N-1
(Comptroller reports/payments FAQ), so tax year 2025 = the 2026 report.

- **Tax years 2021-2024 (report years 2022-2025): fixed 2007 IRC.** Comptroller COGS FAQ: "For 2025 Report Years and
  earlier ... both [section 179 and bonus depreciation] are based on the IRC of 1986 in effect for the federal tax
  year beginning on Jan. 1, 2007 ... Federal bonus depreciation is not allowed for Texas COGS because the Economic
  Stimulus Act of 2008 ... became part of the IRC after Jan. 1, 2007." Section 179 under that Code: limit USD 25,000,
  phase-out threshold USD 200,000 (same FAQ). 34 TAC 3.588(d)(6)(D): "For franchise tax reports prior to the 2026
  report ... the 2007 Internal Revenue Code is used when determining allowable depreciation amounts."
- **Tax year 2025 (2026 report) onward: federal depreciation.** News release 1 Dec 2025 and Tax Policy memo
  (STAR 202512012M): Texas aligns with the OBBBA bonus rules because the Comptroller found the statute permits current
  IRC for depreciation. FAQ: "A taxable entity may include in its COGS depreciation reported on its federal tax return
  to the extent associated with and necessary for the production of goods" including federal bonus and section 179;
  an entity "generally must use the same methods it uses on its current federal return" (no opt-out). Rule 3.587
  effective 1 Mar 2026 (amounts from the federal return use federal law in effect for that federal year unless the
  statute or rule references the IRC); Rule 3.588 amendments adopted without change, effective 21 Jun 2026 (Texas
  Register 12 Jun 2026): subparagraph (A) current federal law for 2026 and later reports.
- **One-time net depreciation adjustment (2026 report only):** per qualifying asset, the difference between
  depreciation claimed federally and depreciation claimed for Texas COGS; the asset must have been placed in service
  before the accounting-year begin date on the 2026 report, not disposed of, and associated with and necessary for the
  production of goods. Conflict: the proposed-rule summary said unused amounts carry forward to consecutive reports;
  the adoption-notice summary quotes the Comptroller as saying there is "not a carryforward provision in COGS for
  unused costs". Unresolved.
- **Tax year 2026 (2027 report):** the rule is open-ended ("beginning with 2026 reports"), so 100% bonus and the 2026
  federal 179 amounts are carried, verified=false (no 2027-report guidance existed on 2026-10-06).
- Not resolved: statutes.capitol.texas.gov would not load, so Tax Code 171.0001(9) and 171.1012(c)(6) are quoted via
  the Comptroller's and Register's own paraphrase, and 168(n) qualified production property is inferred to flow
  through (no carve-out found).

## Utah (UT)

**Individual income tax: yes** (flat rate; the Tax Commission chairman's May 2026 deck says S.B. 60 cuts the top rate
from 4.50% to 4.45%). **All six rows are verified=false**: the Utah Legislature host (le.utah.gov, IP 204.113.30.13x)
refused every connection and most tax.utah.gov documents returned HTTP 403 or 404, so no Utah statute or rule text
was read. What was read:

- **Rolling conformity (search excerpt of statute):** Utah Code 59-10-103: IRC references include "any corresponding
  or comparable provisions of the Internal Revenue Code as amended, redesignated, or reenacted"; individual federal
  taxable income is the IRC section 63 figure and adjusted gross income the section 62 figure, adjusted under
  59-10-114 and 59-10-115. So Utah follows 168(k) and 179 as they stand each year unless decoupled by statute.
- **Agency form:** the TC-40A supplemental schedule for tax year 2025 (https://incometax.utah.gov/tc-40a/) lists
  additions (codes 51-69) and subtractions (71-90) and none is for depreciation, bonus depreciation or section 179.
  Only the 2025 page was available; 2021-2024 are carried from statute-level rolling conformity plus no decoupling
  found, which is why they are verified=false.
- **OBBBA conforming effect (agency presentation, off-agency host):** Tax Commission Chairman J. Valentine, Utah
  Taxpayers Association, May 2026, slide 9, "Conforming Effects of HR1 ... Automatic Tax Cuts": "100% bonus
  depreciation: $95.4 million in 2026", "Increased limitation on depreciable assets: $7 million in 2026", "Qualified
  production property depreciation: $32 million in 2026", "Full expensing of R and E expenditures: $101.5 million
  in 2026". The slide deck says its summaries are not the Commission's final position. Together with the lack of a
  TC-40A addback, this supports Utah following the OBBBA 168(k), 179 and 168(n) changes from tax year 2025 without
  a decoupling adjustment.
- **H.B. 557 (2024 general session, "Income Tax Deduction Amendments"):** introduced text would let a taxpayer who
  claims federal bonus on qualified property subtract the difference between the federal bonus allowed and "the
  federal bonus depreciation that would have been allowed ... for the 2022 taxable year", with a later add-back, and
  has retrospective operation (amends Utah Code 59-7-106 and 59-10-114; the fiscal note estimates USD 29 million
  FY2025 and USD 35 million FY2026). Whether it was enacted could not be read. Inference: it was not, because (i) the
  2025 TC-40A has no such line and (ii) the Commission deck counts 100% bonus as a new 2026 cost. A calculator should
  not apply the subtraction without reading the enrolled bill.
- **2026 session:** S.B. 60 (rate), H.B. 77 (taxpayer credit alignment) passed; H.B. 587 (income tax amendments with an
  addition for domestic research and experimental expenditures and an amortized subtraction) is not on the
  chairman's passed list and its fate is unconfirmed. None of these changes 168(k) or 179.
- **Notice UT-26-03** (secondary mention only): Utah does not conform to the OBBBA Schedule 1-A personal deductions
  for 2023-2026. Not a depreciation rule.

Leads rejected as sources: a vendor conformity sheet (proware-cpa.biz) and crosslinktax.com both say Utah conforms to
bonus and 179; they agree with the above but are not primary.

## Vermont (VT)

**Individual income tax: yes. Bonus depreciation: none, all years.** 32 V.S.A. 5811(21), as quoted in the Department's
Technical Bulletin TB-44 (issued 22 Jan 2009, read in full): "'Taxable income' means federal taxable income determined
without regard to Section 168(k) of the Internal Revenue Code". Vermont had already disallowed bonus for C
corporations from 2002 (5811(18)(A)). The Compliance Corner page says the rule applies for "2008 and forward" and that
depreciation "must be recomputed for the Vermont return as if bonus depreciation did not exist" (fetch summary).

- **Mechanics (TB-44, restated on 2024 and 2025 Schedule IN-112 instructions, both read in full):** in the year the
  asset is placed in service, add the difference between depreciation calculated using the federal bonus and
  standard MACRS (IN-112 Part I addition line 4: "Vermont does not recognize the bonus depreciation allowed under
  federal law"). In later years subtract the difference between standard MACRS and federal depreciation (line 9,
  "Adjustment for Bonus Depreciation on Prior Year Property"). There is no spread over N years: keep two depreciation
  schedules. Worked example in TB-44: 5-year computers USD 15,000, federal MACRS 1,500 plus bonus 7,500 = 9,000 against
  Vermont 3,000, adjustment 6,000 (old 50% bonus rate; the mechanics are the same at 100%).
- **Pass-through owners:** the entity's Schedule K-1VT carries the bonus adjustment (lines 8aA/8bA everywhere; 8aB/8bB
  Vermont-sourced). On IN-112 for 2025, include the part of lines 8aA, 8bA, 38A for assets placed in service in the
  current year on line 4 and prior years on line 9. Nonresident owners filing IN-113 use federal K-1 amounts before the
  disallowance. Gain or loss on disposition is recomputed with Vermont depreciation (different Vermont and federal
  basis). 2025 K-1VT instructions, read in full.
- **Section 179:** TB-44: "Vermont law did not decouple from IRC Section 179 provisions ... The treatment of assets must
  be consistent at both the federal and state level ... You cannot utilize the bonus depreciation for Federal purposes
  and use Section 179 for Vermont purposes." K-1VT Part III lines 23A/23B pass the federal 179 deduction through with
  no Vermont 179 adjustment line. Limit and phase-out: federal figures carried as inherited; no Vermont page prints
  them.
- **Conformity type: fixed date, relinked annually.** 32 V.S.A. 5824 adopts the Code as of a stated date. Dates found:
  heading into the 2026 session, "the IRC in effect on December 31, 2024 for tax years beginning on or after January 1,
  2024"; H. 933 sec. 60 moved it to 31 Dec 2025 effective for tax years beginning on or after 1 Jan 2025 (law-firm
  article, secondary). A cached copy of 5824 in a search result read "as in effect on December 31, 2022"; dates for
  2021-2023 are not confirmed.
- **OBBBA response (Act 164 / H. 933, 2026):** agency OBBBA page: the act "retroactively applies to tax years beginning
  on or after January 1, 2025", conforming to P.L. 119-21 but decoupling from IRC 174A (domestic R&E, for large
  businesses), IRC 168(n) qualified production property, and the section 250 deduction. Because 168(k) was already
  disregarded, 168(n) is denied on top of it; QPP is therefore presumably depreciated as ordinary nonresidential real
  property (inference). Beginning with 2026, an add-back of the IRC 1202 exclusion and conformity to NCTI/FDDEI.
  Penalty and interest relief for conformity changes; extended due date 15 Oct 2026. The Department's "2025 Vermont
  Income Tax Form Instructions Federal Conformity Supplement" was not read.
- **Row status:** 2021-2025 verified=true on the bonus rule (standing statute and read instructions); the 179 limit is
  inherited and the OBBBA 179 amounts for 2025 and 2026 are an inference. 2026 is verified=false.

## Open questions for a reviewer

1. Utah: read the enrolled H.B. 557 (2024) and Utah Code 59-10-114 on le.utah.gov from a network that can reach it;
   until then all Utah rows are unverified.
2. Texas: confirm whether an unused 2026-report one-time depreciation adjustment carries forward (proposed and adopted
   summaries disagree) and open Tax Code 171.0001(9) / 171.1012(c)(6) directly.
3. Tennessee: no source addresses 179 under the OBBBA for the excise tax; the 2025-2026 limits are inferred.
4. Vermont: confirm the annual IRC link-up date for 2021-2023 from 32 V.S.A. 5824 history, and read the 2025 Federal
   Conformity Supplement for the QPP treatment.
