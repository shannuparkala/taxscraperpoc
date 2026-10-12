---
topic: State depreciation conformity, batch 6 (NM, NY, NC, ND, OH), personal income tax, tax years 2021-2026
tax_years: 2021, 2022, 2023, 2024, 2025, 2026
figures_as_of: 2026-10-06
figures_source_url: per-state URLs below (state agency hosts and state legislature / statute sites)
status: verify
progress: COMPLETE for the batch. NM, NY, NC, ND, OH done (6 rows each, 30 rows in the JSON). Open items are listed per state. Replaces the earlier placeholder, which listed a different (now reassigned) set of states.
---

# State depreciation conformity, batch 6 (NM, NY, NC, ND, OH)

Recorded 2026-10-06. Enacted law only. Scope is the personal income tax as it applies to a sole
proprietor, pass-through owner or rental owner. Federal reference figures come from
`docs/tax-research/depreciation-macrs-179-bonus-280f-2021-2026.md` and are not re-derived here.

Federal figures that a "conforming" state inherits:

| Tax year | Federal bonus 168(k) | 179 limit | 179 phase-out start |
|---|---|---|---|
| 2021 | 100% | 1,050,000 | 2,620,000 |
| 2022 | 100% | 1,080,000 | 2,700,000 |
| 2023 | 80% | 1,160,000 | 2,890,000 |
| 2024 | 60% | 1,220,000 | 3,050,000 |
| 2025 | 100% acquired after 19 Jan 2025; 40% earlier (P.L. 119-21 s.70301 over Rev. Proc. 2024-40) | 2,500,000 (OBBBA s.70306; RP 2024-40 said 1,250,000) | 4,000,000 (RP 2024-40 said 3,130,000) |
| 2026 | 100% | 2,560,000 | 4,090,000 |

## How this is researched

- `ALLOWLIST_DOMAINS` in `tax_research_crawler.py` no longer exists (file deleted in the 2026-10-05
  rebuild). Agency hosts come from `backend/app/services/assistant/state_registry.py`: NM
  tax.newmexico.gov, NY tax.ny.gov, NC ncdor.gov, ND tax.nd.gov, OH tax.ohio.gov. Legislature or
  official statute sites are added per state and named where used (NY: nysenate.gov; ND: ndlegis.gov).
- NM's PIT-ADJ instructions are served from realfile.tax.newmexico.gov, a subdomain of the Department's
  host that is not itself in the registry; treated as the same agency's host. Flag for the owner.
- Ohio's current forms are served from dam.assets.ohio.gov (an Ohio state asset host that is not in
  the registry), linked from tax.ohio.gov. Same flag. FindLaw was used once as a lead for the text of
  R.C. 5747.01 because codes.ohio.gov refused the connection; it is a secondary source.
- This session has no Bash or Edit tool, so each JSON update is a whole-file rewrite. `Read` takes
  only local paths, but `WebFetch` saves PDFs it cannot parse under the session `tool-results`
  folder and prints the path; `Read` on that path then returns the full text.
- `verified` is true only when every non-null cell was read from statute or agency text for that
  year. Inference, federal figures carried as "conforming", derived figures and adjacent-year carry
  are false, with the reason in `verify_note`.
- HTML pages came through the `WebFetch` summariser, which returns quotations but can garble
  structure (its paragraph numbering of NY Tax Law 612(b) was wrong and is not relied on). PDFs read
  with `Read` are the raw text.
- Access blocks: every nmlegis.gov page and PDF, ncleg.gov statute pages, and Justia returned HTTP 403;
  codes.ohio.gov and the Ohio LIS site refused the connection.

## Summary matrix

| State | Bonus 2021-2024 | Bonus 2025 | Bonus 2026 | 179 | 168(n) |
|---|---|---|---|---|---|
| NM | follows federal (no adjustment on PIT-ADJ; 2021 read, 2022-24 inferred) | follows federal (2025 PIT-ADJ read) | follows federal for individuals; corporate decoupled by SB 151 | federal | flows through for individuals; corporate decoupled 2026 |
| NY | **none**: add back federal depreciation on 168(k) property, subtract NY depreciation as if acquired 10 Sep 2001 | none (100% bonus also disallowed) | none | federal (no modification found; inferred) | **decoupled** from tax years beginning 1 Jan 2025 (Notice N-26-1) |
| NC | **85% add-back, 20% a year for five years** (15% allowed in year 1) | same, applied to the 100% / 40% federal bonus and 168(n) | same (FAQ: decoupling unchanged) | **own limit 25,000 / 200,000**, 85% add-back of the excess, 20% x 5 | **decoupled** (same add-back); IRC date moved to 5 Jul 2025 by SL 2026-31 |
| ND | follows federal (no adjustment in statute or ND-1SA; 2021-2024 forms read) | follows federal (2025 ND-1SA read) | follows federal (no 2026 form) | federal | follows (no adjustment) |
| OH | **5/6 add-back, 1/5 a year for five years** (1/6 allowed in year 1); 2/3 or 6/6 variants | same 5/6 rule on 168(k) at any bonus rate | same (carried) | add back 5/6 of 179 above the amount under the law as of 31 Dec 2002 (FAQ: 25,000) | follows 168(n) (no add-back; secondary), subject to the 2025 election under SB 9 |

## New Mexico (NM)

Individual income tax: yes. Starting point is federal adjusted gross income (TRD Personal Income Tax
Overview, https://www.tax.newmexico.gov/individuals/personal-income-tax-information-overview/:
"Personal income tax in New Mexico starts with the Federally Adjusted Gross Income (FAGI) from your
federal return").

- **Rule 2021 and 2025 (agency text, both read in full 2026-10-06).** The PIT-ADJ is the only
  schedule through which a taxpayer can modify FAGI, and the instructions say: "Do not add any amounts
  to Schedule PIT-ADJ that are not listed on this schedule. If an item is not listed, it is not a valid
  New Mexico addition, exemption, or deduction for this schedule."
  - 2021 additions are lines 1-4 and 2025 additions are lines 1-5; none concerns depreciation, 168(k),
    179 or 168(n). 2021: https://realfile.tax.newmexico.gov/2021pit-adj-ins.pdf ; 2025:
    https://realfile.tax.newmexico.gov/2025pit-adj-ins.pdf (lines 1-6 and 7-28).
  - So the federal bonus and 179 deductions flow into FAGI unchanged, and a sole proprietor or rental
    owner keeps one depreciation schedule for federal and New Mexico.
- **Conformity type.** A search-result excerpt of NMSA 7-2-2 reads: "'adjusted gross income' means
  adjusted gross income as defined in Section 62 of the Internal Revenue Code, as that section may be
  amended or renumbered." That is rolling. The statute page itself (nmlegis.gov, Justia) returned HTTP
  403, so it is excerpt-only. The 2025 PIT-ADJ line 26 repeats the phrase for IRC 280E ("as that
  section may be amended or renumbered"), which does read on the agency page.
- **2022, 2023, 2024.** No form was read. The result is carried from 2021 and 2025 only because the
  statute is rolling and both read forms have no depreciation line. Marked unverified.
- **OBBBA response.** TRD lists no individual guidance that I could find. SB 151 (2026 regular session,
  "Corporate Income Tax Changes", signed 11 Mar 2026 per a Governor's release in search results)
  decouples the *corporate* income and franchise tax from P.L. 119-21 first-year bonus depreciation,
  qualified production property (168(n)) and the business interest limitation, for taxable years
  beginning on or after 1 Jan 2026; the bonus provision runs "until July 1, 2036" per an excerpt of the
  analysis. The excerpts give revenue estimates for FY27 and FY28 (at least 55.8 million to 60.8
  million, then at least 111 million to 121 million). No personal-income-tax decoupling appeared in
  any excerpt, but the bill text could not be read, so one cannot be excluded.
- **Calculator rules.** (1) Individuals: use federal depreciation as-is, no state schedule, no add-back.
  (2) A C corporation (or an entity taxed as one) from 2026: no bonus; NM depreciation without 168(k)
  and 168(n). (3) NM NOL is separate: only against a federal NOL, no carryback, 19-year carryforward
  for losses incurred on or after 1 Jan 2013 (2025 PIT-ADJ line 8).
- **Open.** Read the 2022-2024 and 2026 PIT-ADJ instructions when published; read SB 151 as enrolled
  (final/SB0151.pdf) to confirm the corporate-only scope; read NMSA 7-2-2 from an accessible host.

Rows: 6 for NM, all `verified=false`.

## New York (NY)

Individual income tax: yes (resident return IT-201, nonresident IT-203; NYC residents also pay NYC
personal income tax on the state base, per the Department's COVID FAQ wording that changes "apply to
the New York State and New York City personal income tax").

- **Bonus 168(k): none, every year 2021-2026.** 2025 Form IT-398 (read in full), General instructions:
  "For tax years beginning after December 31, 2002, NYS does not allow the federal special
  depreciation deduction for Internal Revenue Code IRC § 168(k) property [except for resurgence zone
  property and New York liberty zone property described in IRC § 1400L(b)(2)], placed in service inside
  or outside NYS after May 31, 2003. Instead, you are allowed a NYS depreciation deduction determined
  under IRC § 167, as that section would have applied to the property if it had been acquired on
  September 10, 2001."
  https://www.tax.ny.gov/pdf/current_forms/it/it398_fill_in.pdf
  - Mechanics: add back the **whole federal depreciation deduction** on the 168(k) property each year
    (IT-225 addition **A-209**, IT-398 column G) and subtract the **NY depreciation** (subtraction
    **S-213**, column F). NY depreciation uses the convention from federal Form 4562 column E and "any
    consistent depreciation method that would have been allowed under IRC § 167 ... without regard to
    § 168(k)"; depreciable basis is cost less the amount expensed under 179. On disposition the
    difference between total federal and total NY depreciation is subtracted (**S-214**, Part 2).
  - This covers any bonus rate, so it also covers the 100% bonus for property acquired after 19 Jan
    2025: NY does not allow it.
  - 2022, 2023 and 2024 IT-225-I (read via the summariser) carry the same A-209 / S-213 / S-214 text:
    https://www.tax.ny.gov/forms/html-instructions/2022/it/it225i-2022.htm, .../2023/it/it225i-2023.htm,
    .../2024/it/it225i-2024.htm. 2021: the HTML URL returned 404 and the PDF was not read, so 2021
    rests on the statute's "after December 31, 2002" and the later years.
  - Passive activities: the modifications are made "for the full amounts allowable as a federal
    depreciation deduction (100%), even though the activity may be subject to federal loss deduction
    limitations" (IT-398, citing Tax Law 612(b)(8) and (c)(16)).
  - Partnerships: IT-398 is completed by the partnership, not each partner; partners take their
    distributive share. An electing NY S corporation passes the depreciation to the shareholder.
- **Conformity type.** Tax Law 607(a), read twice on nysenate.gov, https://www.nysenate.gov/legislation/laws/TAX/607 :
  references to the IRC of 1986 "and amendments thereto ... as the same may be or become effective at
  any time or from time to time for the taxable year. Provided however, for taxable years beginning
  before January first, two thousand twenty-two, any amendments made to the internal revenue code of
  nineteen hundred eighty-six after March first, two thousand twenty shall not apply to this article."
  So **2021 is fixed at 1 Mar 2020**; **2022 onward is rolling** (the Department's FAQ: "For tax years
  beginning on or after January 1, 2022, any changes to the Internal Revenue Code after March 1, 2020,
  will apply to the New York State and New York City personal income tax, unless a specific
  modification is otherwise required." https://www.tax.ny.gov/pit/cares-act-faq.htm).
- **Special rule, 2021: qualified improvement property.** The same FAQ: "New York State personal
  income tax does not conform to the federal changes to QIP depreciation" (the CARES Act 15-year
  MACRS / 20-year ADS class lives), for tax years beginning before 1 Jan 2022; for 2020-2021 differences
  are reported on Form IT-558. Open: how NY treats QIP placed in service 2018-2021 from 2022 onward
  was not found.
- **Section 179.** No 179 modification appears in the 2022-2025 depreciation modification lists, so
  the federal limit is inferred to apply (2025: the OBBBA 2,500,000 / 4,000,000 flows through under the
  rolling rule). No NY sentence states this, hence unverified. NY's own 179 figure: none found.
- **OBBBA response (2025, 2026).** Notice N-26-1, 16 Jun 2026, https://www.tax.ny.gov/forms/n-notices/n-26-1.htm
  (via the summariser): under the 2026-2027 budget NY "does not conform" to 168(n) accelerated
  depreciation for qualified production property and to the OBBBA R&E expensing (174/174A), for tax
  years beginning on or after 1 Jan 2025. 168(n): add back the full federal deduction (A-209), subtract
  depreciation "calculated as if the special depreciation election had not been made" (S-213). R&E:
  add back in full (A-225), subtract over 60 months (S-221 for expenses paid or incurred on or after
  1 Jan 2025, S-222 for earlier). Penalty and interest relief is available for timely filed or amended
  returns reporting the modifications. The 2025 IT-225-I (published before the notice) does not
  mention P.L. 119-21.
- **A-223.** New in the 2025 instructions as read: an institutional real estate investor (owns 10 or
  more residential properties of no more than two dwelling units in NYS, manages pooled funds as
  fiduciary, 30,000,000 or more in assets under management) adds back federal depreciation on those
  properties and gets no NY depreciation (Tax Law 208.9(c-4); IT-398 "Special rules"). Rarely relevant
  to a sole proprietor; the start year was not confirmed.
- **Not researched.** NYC unincorporated business tax (applies to sole proprietors and partnerships in
  NYC) and the corporation franchise tax (Form CT-399).
- **Open.** Read the 2021 IT-225-I; read Tax Law 612(b) and the 2026-27 budget bill text for the
  168(n) paragraph and any sunset; read the 2026 IT-398 when issued.

Rows: 6 for NY, all `verified=false` (179 conformity is an inference; HTML pages through the summariser).

## North Carolina (NC)

Individual income tax: yes (2021 5.25%, 2022 4.99%, 2023 4.75%, 2024 4.5%, 2025 4.25%, from the
D-401 booklets). Static (fixed-date) IRC conformity, confirmed by the Department: "North Carolina is
a static conformity state. As a static conformity state, the North Carolina General Assembly must
enact legislation to align its income tax laws with the Code." (NCDOR FAQs Regarding Recent Session
Law Changes, 11 Sep 2026, Q10, https://www.ncdor.gov/faqs-recent-session-law-changes/open).

- **Bonus: decoupled with an 85% add-back and a five-year 20% give-back, 2021-2026.** Every D-401
  booklet read in full (2021, 2022, 2023, 2024, 2025; Instructions for D-400 Schedule S, line 3):
  "North Carolina did not adopt the [100%] bonus depreciation provisions in IRC sections 168(k) or
  168(n) for property placed in service for tax year [Y]. You must add 85% of the amount of bonus
  depreciation deducted on your federal return ... you may deduct 20% of the amount added back in
  the first five taxable years beginning with tax year [Y+1]." Net effect, in year 1: 15% of the
  federal bonus is allowed; 17% (20% x 85%) of the federal bonus comes back in each of the next five
  years. URLs:
  - 2021 https://www.ncdor.gov/2021-d-401-individual-income-tax-instructions/open
  - 2022 https://www.ncdor.gov/2022-d-401-individual-income-tax-instructions/open
  - 2023 https://www.ncdor.gov/2023-d-401-individual-income-tax-instructions/open
  - 2024 https://www.ncdor.gov/2024-d-401-individual-income-tax-instructions/open
  - 2025 https://www.ncdor.gov/2025-d-401-individual-income-tax-instructions/open
  - Agency topic pages (not re-read): https://www.ncdor.gov/taxes-forms/individual-income-tax/filing-topics/adjustment-bonus-depreciation
    and .../bonus-asset-basis.
  - The deduction line is Schedule S line 23 (columns for each of the five prior years); 2024 form
    columns cover 2019-2023 add-backs. Line numbers shift by year (2021 booklet: line 22).
- **Section 179: own limit.** Schedule S line 4: NC did not adopt the higher federal expense limits;
  NC dollar limit **$25,000** and investment limit **$200,000**. Add back 85% of (federal 179
  deduction minus 179 computed with the NC limits) and deduct 20% a year for five years (line 24).
  The federal limits in the table above (1,050,000 ... 2,500,000 ... 2,560,000) therefore do not apply
  in NC for any year.
- **Basis rule.** NC basis in bonus property differs from federal basis; on disposition the
  difference is adjusted on Schedule S (add the excess of federal basis over state basis, deduct the
  excess of state basis over federal basis; line numbers vary by year). A transferee of property with
  carryover federal basis adds the transferor's remaining bonus deductions to basis and the transferor
  takes no further deductions (G.S. 105-153.6(e), (f), as cited in the booklets, Schedule S line 21
  or 22). Statute text was not read (ncleg.gov returned HTTP 403).
- **IRC reference date by year (booklets):** tax years 2021 and 2022, 1 Apr 2021; 2023 and 2024,
  1 Jan 2023; 2025 booklet, 1 Jan 2023 (printed before the 2026 session law).
- **OBBBA response (2025, 2026).** Session Law 2026-31 (SB 595, signed 2 Jul 2026) moved the IRC
  reference from 1 Jan 2023 to **5 Jul 2025** and reached back to taxable years beginning before
  1 Jan 2026 (FAQ A3, A5: "should file (or amend)" the 2025 return). FAQ Q12 says that after the Act
  federal changes effective on or before 5 Jul 2025, including the One Big Beautiful Bill Act, enter
  AGI "to the extent North Carolina conforms". Q44: "Has the NC decoupling adjustment for bonus
  depreciation changed? No." So the 85% / 20% x 5 rule is applied to the 100% bonus and the 168(n)
  allowance. The Act adds a decoupling from IRC 174A(a) domestic R&E expensing: add back 80%, deduct
  25% in each of the next four years (FAQ Q17-Q18; Schedule S line 15 and line 40 for 2023-2025;
  effective for tax years beginning on or after 1 Jan 2022 for taxpayers who elect retroactive
  application, and on or after 1 Jan 2025 otherwise). The OBBBA tips, overtime, car-loan interest and
  senior deductions do not reduce NC taxable income (Q14, Q15). The FAQ is silent on 179; the 25,000 /
  200,000 limits come from the 2025 booklet and are carried as unchanged.
- **Effective tax year of the new reference date.** FAQ A3-A5 and A12 apply Session Law 2026-31 to
  taxable years beginning before 1 Jan 2026, which includes 2025. I did not read SL 2026-31 itself,
  so the exact start year for the 5 Jul 2025 reference is taken from the FAQ wording. 2026 NC
  returns will be published in January 2027 (FAQ A5 Note).
- **Open.** Read SL 2026-31 (https://www.ncleg.gov/EnactedLegislation/SessionLaws/PDF/2025-2026/SL2026-31.pdf)
  and G.S. 105-153.6 to confirm the 2025 start year and that 179 is unchanged; read the NCDOR notice
  of 23 Jul 2026 (updated 29 Jul 2026) directly; read the 2026 instructions when published; confirm
  whether a pass-through owner reports the add-back on the entity or the owner return (not researched;
  NC taxed-PTE adjustments appear on Schedule S lines 14 and 38 for 2024).

Rows: 6 for NC. 2021-2024 `verified=true` (agency booklet read in full for each year; statute not
read). 2025 and 2026 `verified=false` (notice by summariser, 179 and start-year inferences, no 2026 form).

## North Dakota (ND)

Individual income tax: yes (N.D.C.C. 57-38-30.3; brackets in the 2025 statute text read: 0% to
44,725, 1.95% to 225,975, 2.50% above, single). Perpetual (rolling) federal conformity.

- **Statute (ndlegis.gov, chapter 57-38, read in full 2026-10-06 as current text; no historical
  version retrieved):**
  - 57-38-01(13): "Taxable income" means "the taxable income as computed ... for federal income tax
    purposes under the United States Internal Revenue Code of 1954, as amended" plus or minus the
    adjustments the chapter provides. 57-38-01(5): references to the IRC of 1954 or 1986 "as amended"
    mean the 1986 Code, as amended.
  - 57-38-30.3(1): "A taxpayer computing the tax under this section is only eligible for those
    adjustments or credits that are specifically provided for in this section."
  - 57-38-30.3(2): "North Dakota taxable income" means "the federal taxable income of an individual,
    estate, or trust as computed under the Internal Revenue Code of 1986, as amended, adjusted as
    follows" and then lists a-t (US obligation interest, qualified investment fund, 40% capital-gain
    and qualified-dividend exclusion, lump-sum distribution, military pay, organ donor, tribal income,
    social security, and so on). **No subdivision touches depreciation, 168(k), 168(n) or 179.**
  - 57-38-01(5)(a)-(c) keep 1983-1989 ACRS and section 168(f)(8) lease nonadoption rules; they affect
    only pre-1990 property. 57-38-01.2 (the old individual adjustments section) was repealed by S.L.
    2009 ch. 545 s.32, which is why the adjustments now sit only in 57-38-30.3(2).
  - 57-38-01.3 (corporate adjustments) also has no depreciation adjustment.
  - The Department's Individual Income Tax History page (read through the summariser) says: "North
    Dakota income tax law was perpetually federalized for tax years beginning after December 31, 1988."
- **Forms (Schedule ND-1SA, read in full for 2021, 2022, 2023, 2024, 2025):** additions are only a
  lump-sum distribution (Form 4972) and a loss from an S corporation taxed as a C corporation
  (2023 onward; 2021-2022 had none); subtractions are renaissance zone, new or expanding business,
  organ donor, workforce recruitment, stillborn child, National Guard / Reserve pay (2021-2022), college
  reimbursement and income from an S corporation taxed as a C corporation. No depreciation line in any
  year. URLs: https://www.tax.nd.gov/sites/www/files/documents/forms/individual/2021-iit/schedule-nd-1sa-2021.pdf,
  .../2022-iit/schedule-nd-1sa-2022.pdf, .../2023-iit/schedule-nd-1sa-2023.pdf,
  .../2024-iit/28710-schedule-nd-1sa-2024.pdf, .../2025-iit/28710-schedule-nd-1sa-2025.pdf.
- **Result.** Federal bonus (100%, 100%, 80%, 60%, 100%/40% in 2025, 100% in 2026), 168(n) and the
  federal 179 limit (table above) flow through unchanged. The start is federal *taxable* income, so
  there is no separate ND depreciation schedule; a sole proprietor uses the federal Form 4562.
- **OBBBA response (2025, 2026).** No ND decoupling found: the 2025 statute text and form have no
  adjustment and no ND notice on P.L. 119-21 was located. A search excerpt attributed to tax.nd.gov
  describes the starting point as perpetually conforming so OBBBA changes flow in; that page was
  not found in a fetch, so it is a lead only. The Legislative Assembly meets in odd-numbered years;
  a 2025-session bill touching 57-38-30.3(2) was not searched for by bill number.
- **Entity rules.** Pass-through income is taxed to the owners (57-38-08; single-member LLC
  disregarded, 57-38-07.2); a nonresident partner's modifications follow the distributive share
  (57-38-08.1(3)(c)). Sole proprietors may claim the new or expanding business exemption (ch. 40-57.1)
  and the renaissance zone exemption on ND-1SA.
- **Open.** Retrieve historic statute text for 2021-2024 (the chapter read is current text); read the
  2025 ND-1 booklet and any Tax Commissioner guidance on P.L. 119-21 (the 7.8 MB 2025 booklet
  was saved but its text could not be extracted by the summariser, and was not read in full); read
  the 2026 forms when issued.

Rows: 6 for ND. 2021-2025 `verified=true` (statute plus the year's ND-1SA read in full). 2026
`verified=false` (no 2026 form).

## Ohio (OH)

Individual income tax: yes (R.C. chapter 5747; school district income tax separately, SD 100). 2025
brackets from the booklet: 0% to 26,050, 2.75% to 100,000, 3.125% above; business income deduction on
the first 250,000 ($125,000 married filing separately) with the rest taxed at a flat 3% (2025 IT 1040
instruction booklet pp.11, 18, 26-27).

- **Bonus 168(k): add 5/6, deduct 1/5 a year for five years.** Agency text, 2025 booklet Schedule of
  Adjustments line 9 (p.20, read in full): "Add 5/6 of your bonus depreciation allowed under Internal
  Revenue Code section 168(k). Also add 5/6 of your depreciation expense allowed under Internal Revenue
  Code section 179 less the amount that would have been allowed under section 179 as it existed on Dec.
  31, 2002. Replace '5/6' with '2/3' for employers who increased their Ohio income taxes withheld by at
  least 10% over the previous year. Replace '5/6' with '6/6' for taxpayers who incur a net operating loss
  for federal income tax purposes if the loss was a result of the 168(k) and/or 179 depreciation
  expenses." Line 27 (p.22-23): deduct "1/5 of prior year 5/6 add-backs, 1/2 of prior year 2/3
  add-backs, AND 1/6 of prior year 6/6 add-backs ... The deduction must be taken in equal increments
  in consecutive tax years and any unused portion from any given tax year is not eligible to be carried
  forward." Net default: 1/6 (16.67%) of the federal bonus is allowed in year 1, and 1/6 of it comes
  back in each of the next five years.
  - 2025 Schedule of Adjustments (read): addition line 9 "Internal Revenue Code 168(k) and 179
    depreciation expense add-back"; deduction line 27 "Deduction of prior year 168(k) and 179
    depreciation add-backs"; line 11 "Federal conformity additions"; line 31 "Federal conformity
    deductions". https://dam.assets.ohio.gov/image/upload/v1767098956/tax.ohio.gov/forms/ohio_individual/individual/2025/scheduleofadjustments.pdf
  - Statute (via FindLaw, current as of 1 Jan 2026): R.C. 5747.01(A)(17) 5/6 add-back, with 2/3 for
    taxable years beginning in 2012 or later where withholding rose 10% or more, no add-back where the
    withholding increase equals or exceeds the depreciation, and "the entire" amount if a net operating
    loss results; (A)(18) the one-fifth, one-half and one-sixth deductions.
    https://codes.findlaw.com/oh/title-lvii-taxation/oh-rev-code-sect-5747-01.html . The official
    site (codes.ohio.gov) refused the connection.
  - Agency FAQ (tax.ohio.gov, Income - Bonus Depreciation; search excerpt, fetch 404): "The amount
    subject to the add-back is the taxpayer's total 179 expense less $25,000 plus all of the taxpayer's
    168(k) depreciation expense."
- **Section 179.** Ohio adds back 5/6 of 179 expense above the amount allowed under the 179 text as of
  31 Dec 2002. The agency FAQ excerpt calls the deductible base $25,000; the 200,000 investment
  threshold in the JSON is the 2002 federal figure and is not stated by Ohio (flagged in
  `verify_note`). The federal limits in the table above do not set the Ohio base.
- **Special rules for a calculator.** (1) No add-back for 168(k)/179 depreciation passed through from a
  pass-through entity (PTE) in which the taxpayer owns less than 5%, or for an employer whose Ohio
  withholding rose by at least its total 168(k)/179 expense (booklet p.20). (2) The deduction is
  suspended in any year with a federal NOL, NOL carryback or NOL carryforward and carried to the next
  year without one; it is allowed even after the asset is sold (p.23, p.63). (3) The adjustment is
  not "business income" and is not entered on the Schedule of Business Income (agency FAQ excerpt),
  while the 2025 booklet's Schedule E example reduces business income by bonus depreciation
  (p.12, Ellen), so bonus lowers the business income that qualifies for the 250,000 deduction and
  3% rate, and the 5/6 add-back is taxed as nonbusiness income at the graduated rates. That
  interaction is my reading of those two statements, not an agency sentence. (4) Pass-through and
  fiduciary filers (IT 4708, IT 4738, IT 1041, IT 1140) make their own add-back, and the owner's IT K-1
  carries the depreciation worksheet; a deduction on an IT K-1 must agree with the owner's prior
  add-back (p.23). (5) Nonresident and part-year filers apportion the depreciation adjustment by
  business in IT NRC Sections II-III (property 20%, payroll 20%, sales 60%). (6) The Commercial Activity
  Tax is a gross receipts tax with no depreciation computation (not researched).
- **Conformity type.** Static (fixed-date) conformity under R.C. 5701.11, updated by annual bills,
  with a taxpayer election. Conformity table at tax.ohio.gov/individual/file-now/ohio-conformity-updates
  (search excerpt, not fetched): tax year 2021 prior effective date 31 Mar 2021, conformity date 17 Feb
  2022; 2022 prior 17 Feb 2022, conformity 15 Mar 2023; 2023 no conformity legislation needed; 2024
  prior 15 Mar 2023, conformity 7 Mar 2025; 2025 prior 7 Mar 2025, conformity 5 Mar 2026. The add-back
  stands apart from the date because R.C. 5747.01(A)(17) is a separate adjustment.
- **OBBBA response (2025, 2026).** Senate Bill 9 (136th General Assembly), signed 5 Mar 2026 with
  immediate effect (EY, 9 Mar 2026; OSCPA excerpts), updates R.C. 5701.11 to 5 Mar 2026 and brings in
  IRC changes after 7 Mar 2025. A taxpayer with a tax year ending after 7 Mar 2025 and before 5 Mar
  2026 may irrevocably elect, on the 2025 return, to apply all IRC provisions effective in that year.
  Without the election the 7 Mar 2025 version applies, which predates P.L. 119-21 (4 Jul 2025). The
  secondary summary says Ohio follows the new 168(n) allowance and 174A R&E expensing but keeps the
  168(k) and 179 add-back, citing R.C. 5747.01(A)(17) and (18). The 168(n) conclusion is consistent
  with the statute naming only 168(k) and 179, but the bill text was not read. The 2025 booklet was
  printed on 27 Nov 2025, before SB 9, so its lines 11 and 31 point to tax.ohio.gov/conformity for
  the election adjustments. House Bill 96 (2025) also lowered the nonbusiness rate to 3.125% for 2025
  and, per summaries read, a flat 2.75% for 2026.
- **Open.** Read the 2021-2024 booklets (the 2024 one is at
  https://dam.assets.ohio.gov/image/upload/v1735920104/tax.ohio.gov/forms/ohio_individual/individual/2024/it1040-booklet.pdf)
  and the FAQ page directly; read SB 9 as enrolled and the 5701.11 election text; read the Department
  guidance on conformity for 168(n); confirm the $25,000 and 200,000 179 figures against the 2002
  federal text; read the 2026 forms when issued.

Rows: 6 for OH, all `verified=false` (statute via FindLaw, FAQ via search excerpt, SB 9 not read; only
the 2025 add-back and give-back mechanics were read from agency text).
