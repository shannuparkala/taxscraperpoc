---
topic: State depreciation conformity, batch 7 (OK, OR, PA, RI, SC), personal income tax, tax years 2021-2026
tax_years: 2021, 2022, 2023, 2024, 2025, 2026
figures_as_of: 2026-10-06
figures_source_url: per-state URLs below (state agency hosts and state legislature / statute sites)
status: verify
progress: COMPLETE. OK, OR, PA, RI and SC done (6 rows each, 30 in the JSON). SC upgraded to agency-text verified for 2021-2025 on 2026-10-06; RI remains unverified (agency and legislature hosts blocked).
---

# State depreciation conformity, batch 7 (OK, OR, PA, RI, SC)

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
  Agency hosts come from `backend/app/services/assistant/state_registry.py`: OK oklahoma.gov, OR oregon.gov
  (www.oregon.gov), PA revenue.pa.gov (the Department's pages now live under www.pa.gov/agencies/revenue,
  which is not itself in the registry; treated as the same agency), RI tax.ri.gov, SC dor.sc.gov.
  Legislature or statute sites are named where used (www.scstatehouse.gov for SC). For RI, the Secretary of
  State's official rules site (rules.sos.ri.gov) is used for the regulation text; it is not in the registry either.
- This session has no Bash tool. `WebFetch` saves PDFs it cannot parse under the session `tool-results`
  folder and prints the path; `Read` on that path with NO `pages` argument returns the full text and page
  images (a `pages` argument fails because pdftoppm is missing). A full read of a 25-page packet is large, so
  only the needed PDFs were read in full. Do not use `Read` on a PDF speculatively: the 2025 Oregon OR-ASC
  instructions were read in full and had nothing on depreciation.
- Access blocks: OSCN (oscn.net) HTTP 502 and Justia HTTP 403 (OK); olis.oregonlegislature.gov and
  oregonlegislature.gov refused the connection, retried 2026-10-06 (OR); legis.state.pa.us refused (PA);
  tax.ri.gov returned HTTP 403 and webserver.rilegislature.gov / webserver.rilin.state.ri.us / www.rilegislature.gov
  refused the connection, retried 2026-10-06 (RI). So codified or enrolled text was not read for OR, PA and RI,
  and RI agency PDFs were seen only as search summaries. SC statute text on scstatehouse.gov and all SC DOR
  PDFs loaded.
- `verified` is true only when every key cell (bonus, conformity, 179 conformity) was read from statute or
  agency text for that year. Inference, federal figures carried as "conforming", and adjacent-year carry are
  false or noted in `verify_note`. The 179 limit and phase-out cells for a state that conforms are the federal
  figures carried as inherited; that is stated in each `verify_note`.

## Summary matrix

| State | Bonus 2021 | Bonus 2022-2025 | Bonus 2026 | 179 | 168(n) |
|---|---|---|---|---|---|
| OK | follows federal (inferred) | Oklahoma's own elective 100% expensing: deduct 100% of cost, add back federal depreciation each year | same | conforms to federal | no decoupling found |
| OR | follows federal | follows federal (2022 100%, 2023 80%, 2024 60%, 2025 100%/40%) | **disallowed** (SB 1507, 5 Jun 2026): add back, subtract over life; referendum status unconfirmed | follows federal | not addressed |
| PA | **none** | **none** | **none** | own 25,000 / 200,000 through 2022; federal limits from tax years beginning 1 Jan 2023 (Act 53 of 2022) | **not incorporated** |
| RI | **none** (add back, subtract later) | **none**; 2025 also decoupled from the H.R.1 179 increase | **none**; permanent H.R.1 decoupling codified for FY2027 | federal limit through 2024; 2025 pre-H.R.1 amount; 2026 unclear | disallowed via the 44-61-1 catch-all (inferred) |
| SC | **none** (add back line e, extra depreciation later) | **none**; IRC date 31 Dec of the year before the tax year through 2025 (2020, 2021, 2022, 2023, 2024) | **none**; IRC date still 31 Dec 2024 | conforms at the adopted date; 2025 does not follow OBBBA 2.5 million | not adopted (12-6-50(4)) |

## Oklahoma (OK)

Individual income tax: yes (2025 top rate 4.75%, Form 511 packet p.38). Starting point is federal AGI
(Form 511 line 1). Rolling federal conformity: 68 O.S. 2358.6A(A)(1) defines "Internal Revenue Code" as "the
federal Internal Revenue Code of 1986, as amended"; the general definition in 68 O.S. 2353 reads "as the same
may be amended ... applicable to the taxable year" (search-result excerpt, not read at the statute site).

- **Rule for 2022 onward (statute read in full, enrolled HB 3418 and SB 602).** Oklahoma has its own 100%
  expensing election, not a federal-bonus follow or decouple. 68 O.S. 2358.6A(B)(1): "For purposes of computing
  income tax for taxable years beginning after December 31, 2021, the cost of expenditures for business assets
  that are qualified property or qualified improvement property covered under Section 168 of the Internal Revenue
  Code shall be eligible for one hundred percent (100%) bonus depreciation and may be deducted as an expense
  incurred by the taxpayer during the taxable year during which the property is placed in service,
  notwithstanding any changes to federal law related to amortization of cost recovery beginning on or after
  January 1, 2023, and shall permanently remain fully and immediately deductible". SB 602 (2023) added:
  "If a taxpayer elects immediate and full expensing ... any depreciation calculated and claimed pursuant to
  this section shall in no event be a duplication of any depreciation or bonus depreciation allowed or permitted
  on the federal income tax return of the taxpayer. For income tax returns filed on or after January 1, 2023,
  federal taxable income shall be increased by the amount of depreciation received under the Internal Revenue
  Code for the qualified property ... for which the election has been made ... for the year in which the
  property was placed in service." Effective 1 Nov 2023. Taxpayers who filed before 1 Oct 2023 without the
  increase had to amend by 30 Jun 2024 with no penalty or interest. URLs:
  https://www.oklegislature.gov/cf_pdf/2021-22%20ENR/hB/HB3418%20ENR.PDF and
  https://www.oklegislature.gov/cf_pdf/2023-24%20ENR/SB/SB602%20ENR.PDF
- **Definitions.** "Qualified property" has the meaning in IRC 168(k) "as the Code existed on January 1, 2021"
  for property placed in service after 31 Dec 2021; "qualified improvement property" has the meaning in IRC
  168(e)(6) as of 1 Jan 2021.
- **Election is irrevocable** ((B)(3) as amended): the choice between immediate expensing and amortizing "is
  irrevocable unless specifically allowed for by the Oklahoma Tax Commission".
- **Later-year add-back.** Emergency rule 710:50-15-69.1, adopted 27 Sep 2022 (read in full, 8 pages): "If this
  option is taken, amounts that are depreciated for federal income tax purposes in future tax years shall be
  added back to Oklahoma taxable income in the year the depreciation is claimed." The emergency rule was
  effective only through 14 Sep 2023 "unless superseded"; the permanent rule was not read.
  https://oklahoma.gov/content/dam/ok/en/tax/documents/resources/rules-and-policies/agency-rules/emergency-rules/2022-Chapter50EmerRuleIncome.pdf
- **Section 179.** 2358.6A(C)(1): "To conform to Section 179 of the Internal Revenue Code, taxpayers shall be
  allowed to immediately deduct as an expense the cost of certain depreciable business assets in the tax year in
  which the property is placed in service", and (C)(2) lets taxpayers elect 179 treatment for taxable years
  beginning after 31 Dec 2021. No Oklahoma-specific dollar limit or phase-out is stated, so the federal 179
  amounts apply (carried as inherited).
- **Forms.** 2022 Form 511 packet (read in full): no bonus-depreciation subtraction or add-back line; Schedule
  511-A line 15 was "Miscellaneous: Other subtractions". 2025 packet (read in full): Schedule 511-A line 15
  "Oklahoma Bonus Depreciation Deduction" and Schedule 511-B line 8 "Oklahoma Bonus Depreciation Add-back" (p.19,
  p.21). https://oklahoma.gov/content/dam/ok/en/tax/documents/forms/individuals/current/511-Pkt.pdf and
  https://oklahoma.gov/content/dam/ok/en/tax/documents/forms/individuals/past-year/2022/511-Pkt-2022.pdf
  The 2021, 2023 and 2024 packets were not read.
- **2021.** The expensing election starts with taxable years beginning after 31 Dec 2021, and Oklahoma starts
  from federal AGI, so the federal 100% bonus is inferred to flow through. Marked unverified.
- **OBBBA response.** None found: no OTC guidance on P.L. 119-21 located, the 2025 "What's new" list has no
  depreciation item, and Schedules 511-A through 511-C carry no 168(n) or OBBBA adjustment. With a rolling
  definition and a federal-AGI start, the OBBBA 179 amounts and 100% federal bonus flow through. A secondary
  search summary of the OTC corporate and partnership instructions (Forms 512, 514) said the Oklahoma
  subtraction is not allowed where 100% federal bonus was claimed; that is a lead only, not read.
- **Calculator rules.** (1) Taxpayer makes the election per property; Oklahoma depreciation of elected property
  = 100% of cost in the placed-in-service year, zero afterward. (2) Add back federal depreciation on elected
  property every year it is claimed (bonus, 179 or regular MACRS), per 2358.6A(B)(2) and rule 710:50-15-69.1.
  (3) Property that qualifies only because of post-2020 changes to 168(k) may fall outside the frozen
  definition; the Commission does not say. (4) Section 168(n) property: 39-year nonresidential property is
  not 168(k) property under the 2021 text (my reading), so federal 168(n) flows through AGI. (5) Pass-through
  entities elect at entity level and add back at the distributive share (710:50-19-5 and 710:50-21-1(c), in the
  emergency rule). (6) Oklahoma NOL is separately determined (2025 packet p.5). (7) Swine and poultry
  producers: 7-year accelerated Oklahoma depreciation, then add back federal depreciation (Sch 511-C misc adj 3;
  Sch 511-B misc add 2). (8) Qualified refinery property expensing is a separate pass-through allocation.
- **Open.** Read the 2021, 2023, 2024 packets; read the permanent rule replacing 710:50-15-69.1 and the OTC
  guidance on how the subtraction is computed when federal bonus is 100%; read the codified 2358.6a and 2353 at
  the OSCN site; check 2024-2026 session bills touching 2358.6a or IRC conformity.

Rows: 6 for OK. 2022, 2023, 2025 `verified=true`; 2021, 2024, 2026 `verified=false`.

## Oregon (OR)

Individual income tax: yes (Form OR-40 full-year resident; OR-40-N nonresident; OR-40-P part-year).

- **Conformity type: selective.** 2025 Publication OR-17 (read through a search summary, not in full):
  "Oregon has a rolling tie to changes made to the definition of federal taxable income" and, for all other
  purposes, Oregon is tied to federal income tax law "as amended and in effect on December 31, 2023".
  https://www.oregon.gov/dor/forms/FormsPubs/publication-or-17_101-431_2025.pdf . ORS 316.007 states the
  legislative intent to make the Oregon personal income tax "identical in effect" to the federal measure of
  taxable income of individuals (search excerpt). Because depreciation is part of computing federal taxable
  income, federal bonus and 179 changes flow through automatically, which is why SB 1507 had to legislate a
  disallowance for 2026. The fixed dates for the "other purposes" category in 2021-2023 are not known.
- **2021 to 2025: follows federal bonus and 179.** 2023 Schedule OR-DEPR Instructions (read in full, 2 pages):
  "MACRS is effective for assets placed in service on or after January 1, 1987 (see exception below for assets
  placed in service during 2009 and 2010). The method and life will be the same as you used on the federal
  return. If you elect to expense the cost of qualifying assets under IRC Section 179, the election and amount
  is also effective for Oregon purposes." Exception: "Oregon didn't adopt changes made to IRC Section 168(k)
  (bonus depreciation) or to any expensing limits under IRC Section 179" for assets placed in service 1 Jan 2009
  to 31 Dec 2010. "Oregon is currently tied to federal law, but there are historical disconnects."
  https://www.oregon.gov/dor/forms/FormsPubs/schedule-or-depr-instructions_101-025-1_2023.pdf
  Applied to 2021-2023 as written; 2024 and 2025 are not covered by a year-specific agency page I read.
- **Special rules (Schedule OR-DEPR).** (1) Used for assets first placed in service outside Oregon, assets
  subject to apportionment, and assets placed in service in years when Oregon was disconnected. Full-year
  residents report a net addition on Schedule OR-ASC with addition code 152 and a net subtraction with code
  354; nonresident and part-year filers complete two schedules (federal amount, Oregon amount) and use
  Schedule OR-ASC-NP. (2) Oregon basis of an asset first placed in service outside Oregon is generally the
  lower of federal unadjusted basis or FMV when brought into Oregon (unadjusted basis is before credits
  reducing basis, depletion, amortization and 179). (3) Credits that reduce only the federal basis cause a
  depreciation difference. (4) A partnership return uses the same schedule (OR-65). (5) Search summary of OR-17
  names codes 152 (depreciation difference), 153 (federal depreciation disconnect) and 154 (gain or loss on sale
  with a different Oregon basis); only 152 and 354 were read.
- **2025 and OBBBA.** No Oregon text on 2025 depreciation was read; the rolling tie to federal taxable income
  implies the OBBBA 100% bonus (acquired after 19 Jan 2025) and the 2,500,000 / 4,000,000 179 amounts flow
  through. The 2025 Schedule OR-ASC instructions (read in full) list new tip, overtime and vehicle-loan
  interest subtractions but no depreciation, bonus or 168(n) item. Oregon follows federal for 2025 unless an
  act says otherwise; none found for 2025.
- **2026: SB 1507.** DOR 2026 Summary of Legislation (agency page, re-read 2026-10-06): SB 1507, Oregon Laws 2026
  chapter 142, effective 5 Jun 2026, "disconnects Oregon tax laws from some of the federal tax code changes in
  H.R. 1 (2025), including the federal deduction for vehicle loan interest, qualified small business stock
  exclusion, and disallows bonus depreciation for tax years 2026 and later. Other connections to federal tax
  code are updated to December 31, 2025, or to January 1, 2026." The page adds: "On April 10, 2026, chief
  petitioners filed a referendum petition that proposes to repeal portions of SB 1507 that disconnect from
  certain provisions of federal tax code. Signatures for the petition are due by June 4, 2026." No other entry
  on that page mentions depreciation, 179 or 168.
  https://www.oregon.gov/dor/pages/2026-summary-of-legislation.aspx
  Mechanics (secondary sources only; the enrolled bill on olis.oregonlegislature.gov refused the connection
  again): Baker Tilly (https://www.bakertilly.com/insights/oregon-2026-tax-law-changes) says the addition is the
  difference between the 168(k) deduction applicable to the tax year and the 168(k) deduction "as amended and in
  effect on December 1, 2017", for tax years beginning, or property placed in service, on or after 1 Jan 2026;
  search summaries add a corresponding subtraction over the asset's remaining depreciable life. The 1 Dec 2017
  version of 168(k) was the pre-TCJA phase-down (50% for 2017), which expired for property placed in service
  after 2019, so the net Oregon bonus for 2026 property appears to be zero (my reading, from memory of the PATH
  Act schedule, not read here).
- **Referendum.** A "No Tax Clawback" signature drive needed 78,116 signatures by 4 Jun 2026 and was reported
  as struggling in late May (Oregon Capital Chronicle and OPB, 26-27 May 2026; secondary). Under the Oregon
  referendum rule as reported, a qualifying petition suspends the act until a vote. The Oregon Secretary of
  State initiatives/referendums page (https://sos.oregon.gov/elections/pages/initiatives-referendums-referrals.aspx,
  read 2026-10-06 through a summariser) listed no 2026 referendum petition on SB 1507, only 2030 and 2032
  initiative petitions and a 2026 recall; the separate referendum 2026-302 on transportation funding is a
  different measure. That is suggestive that SB 1507 was not suspended, but it is not conclusive (the IRR
  database was not queried). This remains the main open item for the 2026 row.
- **179 and 168(n).** Nothing found changing 179 or 168(n) for Oregon. The 2026 row carries the federal 179
  figures as inherited with `verified=false`.
- **Open.** Read SB 1507 as enrolled (ORS sections and the exact 2017 reference), the 2026 Schedule
  OR-DEPR instructions when issued, the referendum outcome (SoS IRR database), and a 2021 / 2022 / 2024 / 2025
  OR-DEPR edition; confirm the fixed IRC date for tax years 2021-2023.

Rows: 6 for OR. 2021, 2022, 2023 `verified=true` (2023 OR-DEPR text); 2024, 2025, 2026 `verified=false`.

## Pennsylvania (PA)

Individual income tax: yes, but it is a classified tax: eight income classes, no netting of losses across
classes, and no federal taxable income starting point. Business income (net profits) of a sole proprietor is
computed on PA-40 Schedule C, rents and royalties in their own class. So there is no "rolling" or "fixed"
conformity date for the PIT as a whole; PA follows the IRC only where its own law says so. Coded here as
`selective`. Corporate net income tax is a different regime (Act 72 of 2018 and Act 45 of 2025 cited for MACRS)
and is not covered.

- **Bonus depreciation: none, every year.** DOR PIT guide, "Net Income (Loss) from the Operation of a Business,
  Profession or Farm" (HTML, via summariser): "Bonus depreciation is not allowed for PA PIT purposes" and "The
  federal elections for bonus depreciation do not apply for PA PIT purposes." Depreciation: "Any depreciation
  method may be used as long as it is generally accepted and consistently used", MACRS deductions "at the time
  the property is placed in service or under the IRC of 1986, whichever is earlier"; where federal and PA basis
  differ, straight-line is "adjusted accordingly".
  https://www.pa.gov/agencies/revenue/forms-and-publications/pa-personal-income-tax-guide/net-income-loss-from-the-operation-of-a-business,-profession-or-farm
- **OBBBA (2025) response.** DOR's comparison page for the TCJA and OBBBA (agency HTML, read through a
  summariser; the cells below are quoted): bonus depreciation, TCJA row and OBBBA row, PA PIT: "N/A - Bonus
  depreciation is not allowed in calculating taxable income." Qualified production property (168(n)), PA PIT:
  the same "N/A" statement, so PA does not incorporate 168(n). Section 179, TCJA row: "For tax years beginning
  prior to 1/1/2023, the changes to Section 179 have no effect"; OBBBA row: "For tax years beginning 1/1/2023 and
  after, Act 53 of 2022 changed PA PIT law to incorporate" (the cell is cut off in my copy).
  https://www.pa.gov/agencies/revenue/resources/tax-law-policies-bulletins-notices/tax-cuts-and-jobs-one-big-beautiful-bill-acts
- **Section 179 (Personal Income Tax Bulletin 2023-02, issued 3 Aug 2023, read in full, 8 pages).** The PA
  deduction is under 72 P.S. 7303(a.3) and "is tied to the deduction permitted under Section 179 ... depending
  upon when the § 179 Property is placed in service". "For § 179 Property placed in service before 2023, the PA
  PIT dollar limitation is based upon earlier of the IRC § 179 dollar limitation at the time the § 179 Property
  was placed in service or the IRC § 179 dollar limitation in effect in 2003": 1997 $18,000; 1998 $18,500; 1999
  $19,000; 2000 $20,000; 2001-02 $24,000; 2003-22 $25,000. "Act 53 of 2022 ... amended the PA PIT law to increase
  the PA PIT dollar limitation to match the FIT dollar limitation ... § 179 Property placed in service in tax
  years beginning on or after January 1, 2023 ... $1,000,000 subject to an annual inflation adjustment", reduced
  dollar-for-dollar above "$2,500,000 subject to an annual inflation adjustment". The pre-2023 phase-out
  threshold is not in the bulletin; the DOR comparison page (via search snippet) gives it as 200,000 ("the
  expensing limitation remains at $25,000 with a phaseout beginning at $200,000"). The bulletin's base
  figures are the TCJA ones. Whether PA's 2025 and 2026 limits are the OBBBA 2,500,000 / 4,000,000 (federal
  statute) or the indexed 1,000,000 / 2,500,000 base is not answered by the text I read; the 2025 and 2026 rows
  carry the federal OBBBA figures and say so.
  https://www.pa.gov/content/dam/copapwp-pagov/en/revenue/documents/taxlawpoliciesbulletinsnotices/taxbulletins/pit/documents/pit_bulletin_2023-02.pdf
- **179 mechanics.** Business expense usable "only ... to offset gain from net profits, or Schedule C income";
  it "cannot be used to offset gain from any other PA PIT income class". Limited to PA net profits, applied
  "after all other business-related expenses and losses", and "cannot reduce the taxpayer's PA PIT taxable net
  profits below zero". Excess carries over indefinitely, added to current-year elected cost up to the dollar
  limitation. A taxpayer may claim the PA 179 deduction even without a federal 179 election. Cost not expensed
  is depreciated with "normal PA PIT depreciation rules", straight-line where the expensed amount differs from
  federal.
- **Pass-through owners.** The election is made at entity level and followed by partners and shareholders; the
  dollar and business income limits apply at both entity and owner level; entity carryover stays with the
  entity; nonresident owners' share is apportioned by the entity's business income apportionment percentage; the
  owner's pass-through 179 deduction beyond the owner's dollar limit is lost and the owner adds it back to K-1
  net business income (Examples 4 and 5 of the bulletin).
- **Rental owners.** PA rents and royalties are their own class (PA-40 Schedule E). Because the 179 deduction
  offsets only Schedule C net profits, a rental owner has no PA 179 offset against rent (my reading of the
  bulletin, not an agency sentence). Bonus is disallowed in either class.
- **Not read.** Tax Reform Code of 1971 section 303 as codified (legis.state.pa.us refused the connection); Act
  53 of 2022 text; the PA-40 Schedule C instructions per year; whether PA ever issued 2025-specific guidance
  on the 179 amount.
- **Open.** Confirm from Act 53's text whether the 2025-26 PA 179 limit follows OBBBA amounts; confirm the
  pre-2023 200,000 phase-out from the statute or bulletin PIT 2012-05 (superseded); read the PA-40 Schedule C
  instructions for each year.

Rows: 6 for PA. 2021 and 2022 `verified=true` (limits from the bulletin; phase-out figure from the DOR page);
2023-2026 `verified=false` (inherited or ambiguous 179 figures).

## Rhode Island (RI)

Individual income tax: yes (RI-1040 resident, RI-1040NR nonresident). Starting point is federal AGI with RI
Schedule M modifications; coded `rolling` with specific decouplings (the statute itself was not read).
`tax.ri.gov` PDFs and pages returned HTTP 403 to `WebFetch` and the legislature hosts refused the connection,
retried on 2026-10-06, so everything about forms and statutes below comes from search summaries of agency pages
plus the Secretary of State's regulation site, which did load.

- **Bonus depreciation: none, every year.** RIGL 44-61-1, as summarised from a search result of the
  legislature's statute page: the bonus depreciation of the Job Creation and Worker Assistance Act of 2002
  (P.L. 107-147) and JGTRRA 2003, "or any subsequent federal enactment", is not allowed for Rhode Island; "In the
  year that those assets are placed in service and in all subsequent years, depreciation for Rhode Island tax
  purposes shall be allowed on those assets as it would have been computed prior to the enactment of the Job
  Creation and Worker Assistance Act of 2002." (A second search result on 2026-10-06 repeats the same sentence
  and adds that gain on later disposition is computed on a basis consistent with the Rhode Island depreciation.)
  Because of the "any subsequent federal enactment" wording the TCJA and OBBBA bonus are covered; I could not
  read the clause in the statute site. Mechanics per the DOR Schedule M summary: add the federal bonus back on
  RI Schedule M page 2 line 2d; in later years, when federal depreciation is less than what Rhode Island would
  have allowed, subtract the difference on Schedule M page 1 line 1i. Keep a separate Rhode Island depreciation
  schedule and compute gain or loss on sale from it. The 2025 Schedule M lines read: "Bonus depreciation taken
  on the Federal return that has not yet been subtracted from Rhode Island income under RIGL 44-61-1" and
  "Section 179 depreciation taken on the Federal return that has not yet been subtracted from Rhode Island under
  RIGL 44-61-1.1".
  https://tax.ri.gov/sites/g/files/xkgbur541/files/2026-01/2025%20RI%20Schedule%20M_w.pdf
- **Section 179 to 2024.** The Rhode Island 2003 limit was $25,000 (JGTRRA increase disallowed); a DOR page, via
  summary, says legislation of July 2013 set Rhode Island to conform to the federal 179 amounts for all assets
  placed in service (44-61-1.1). So 2021 to 2024 follow the federal limits (inherited figures in the rows).
- **2025: H.R.1 decoupling.** FY2026 enacted budget; RIGL 44-30-12(b)(9) (via search summary) adds to federal
  AGI "the amount of any income, deduction or allowance that would be subject to federal income tax for the
  taxable years beginning on or before January 1, 2025, but for the enactment of" P.L. 119-21. Regulation
  280-RICR-20-55-16 (emergency, effective 15 Dec 2025 to 16 Apr 2026) and the proposed permanent 280-RICR-20-55-17
  (effective 16 Apr 2026 per the rule page; statutory basis RIGL 44-1-4, 44-30-95 and 44-30-12(b)(9)), read
  through a summariser on rules.sos.ri.gov twice: "Increased dollar limitations for expensing of certain
  depreciable business assets in 26 U.S.C. section 179(b), as amended by section 70306"; a sole proprietor whose
  return "includes an additional deduction for depreciation of assets under 26 U.S.C. section 179(b) than what was
  allowed prior to the enactment of H.R.1 must add back the additional depreciation on the RI Schedule HR1 -
  Individual"; partners and S corporation owners report on Schedule K-1, section II, line 7. Applicable years:
  "For the taxable year beginning on or before January 1, 2025, there shall be added to federal adjusted gross
  income the amount of any income, deduction or allowance that would be subject to federal income tax but for the
  Congressional enactment of H.R.1", described as "the 2025 tax year and all tax years prior to 2025". Also
  decoupled: qualified sound recording productions under 168(k) and 181 (section 70434), and the business
  interest limitation. The add-backs flow to Schedule M as increasing modifications. The regulation text read
  gives no dollar figure for "what was allowed prior to the enactment". A DOR report (via search listing, not
  read) puts the H.R.1 179 figures at 2.5 million and 4 million with the decoupling worth 2.8 million of the
  78.8 million tax-year-2025 decoupling revenue.
  https://rules.sos.ri.gov/regulations/part/280-20-55-16 and
  https://rules.sos.ri.gov/regulations/part/280-20-55-17
- **Dollar figures for 2025.** My inference for the pre-H.R.1 amount is the Rev. Proc. 2024-40 figures (1,250,000
  and 3,130,000). They are not printed in anything I read, so the JSON leaves the 2025 limit and phase-out as
  null.
- **168(n).** Not named in the personal income tax regulation. 44-61-1's "any subsequent federal enactment"
  would disallow it as bonus depreciation, but that is my reading of the statute summary.
- **2026.** The FY2027 budget (H 7127 Substitute A, as amended, Article 6 section 1) codifies permanent
  H.R.1 decoupling in RIGL chapter 44-6.6, including the increased 179(b) dollar limitations (House Fiscal
  Advisory Staff and Senate Fiscal Office summaries; Division of Taxation 2026 Summary of Legislative Changes of
  22 Jul 2026, listed but not fetchable). One source gives the effective date of part of the package as tax years
  beginning on or after 1 Jan 2027, and research and development expensing as beginning with tax year 2026.
  The first tax year of the 179 decoupling is therefore unconfirmed and the 2026 179 limit and phase-out are
  null.
- **Calculator rules.** (1) Bonus: add back 100% of any federal bonus on Schedule M; recompute depreciation
  without bonus; subtract later-year catch-up. (2) 179: add back the amount above the allowed Rhode Island
  limit on Schedule HR1 - Individual for 2025; carry as federal for 2021-2024. (3) Keep separate basis for
  gain or loss. (4) Pass-through owners take the add-back from K-1 section II line 7.
- **Open.** Read RIGL 44-61-1, 44-61-1.1, 44-30-12(b)(9) and chapter 44-6.6 at the legislature's site; read the
  2025 Schedule HR1 instructions for the dollar limit; find the effective tax year of the 179 decoupling
  and the 2026 limit; read the 2021-2024 Schedule M lines. These need a host that is not blocked from this
  environment (a manual download, then Read, would work).

Rows: 6 for RI, all `verified=false` (agency PDFs blocked; statute not read).

## South Carolina (SC)

Individual income tax: yes (SC1040; top rate 6% for 2025 per the 2025 instructions' search summary). Starting
point is federal taxable income (SC1040 line 1), with SC additions (lines a to e) and subtractions (lines f to
w). **Conformity type: fixed.** S.C. Code 12-6-40(A)(1) (read at scstatehouse.gov 2026-10-06, current text):
"Internal Revenue Code" means the Code "as amended through December 31, 2024", and the date is reset by the
General Assembly, normally each year, plus an automatic extension of adopted sections that expire and are
extended by Congress. Agency instructions state the date for each tax year (all read in full 2026-10-06):

| Tax year | IRC date | Where stated |
|---|---|---|
| 2021 | 31 Dec 2020 | 2021 packet, "New for 2021 - Conformity" p.3 and instructions p.11 |
| 2022 | 31 Dec 2021 | 2022 instructions p.1 |
| 2023 | 31 Dec 2022 | 2023 instructions p.1 |
| 2024 | 31 Dec 2023 | 2024 instructions p.1 |
| 2025 | 31 Dec 2024 | 2025 instructions p.1; Information Letter 26-4 |
| 2026 | 31 Dec 2024 unless a 2026 act changes it (none found) | codified 12-6-40 as fetched |

- **Bonus depreciation: none, every year.** S.C. Code 12-6-50 (read at scstatehouse.gov, items 1-20 in full):
  item (4) "Sections 78, 85(c), 86, 87, 168(k), 168(l), 168(m), 168(n) relating to bonus depreciation, 196, and
  280C" are "specifically not adopted by this State". The instructions for every year 2021 to 2025 (line v, and
  line e) say: "South Carolina does not recognize bonus depreciation in IRC Section 168(k). With or without
  bonus depreciation, the depreciable life of the property is the same for federal and state purposes. For the
  tax year the property is placed in service, a taxpayer must add back, on line e of the SC1040, the difference
  between the depreciation deduction allowed for federal purposes and the deduction that would have been allowed
  without bonus depreciation. The South Carolina adjusted basis will then be greater than the federal adjusted
  basis. For all other years of the depreciable life of the property, an additional depreciation deduction is
  available for South Carolina purposes." Page cites: 2021 p.18 (line v) and p.13 (line e); 2022 p.9 and p.3;
  2023 p.12 and p.4; 2024 p.12 and p.4; 2025 p.12 and p.4. The add-back is therefore of the bonus portion only
  (the whole bonus amount, 100% of it), not of regular MACRS. URLs: 2021
  https://dor.sc.gov/sites/dor/files/forms/IITPacket_2021.pdf ; 2022
  https://dor.sc.gov/forms-site/Forms/SC1040inst_2022.pdf ; 2023
  https://dor.sc.gov/forms-site/Forms/SC1040inst_2023.pdf ; 2024
  https://dor.sc.gov/forms-site/Forms/SC1040Instr_2024.pdf ; 2025
  https://dor.sc.gov/sites/dor/files/forms/SC1040Instr_2025.pdf
- **OBBBA response (2025).** Information Letter 26-4 (Revised, 30 Jan 2026, read in full, 2 pages), footnote 3:
  "OBBBA also made modifications to section 168(k) of the IRC and section 304(b) of the Taxpayer Certainty and
  Disaster Relief Act of 2020 that will take effect for the 2025 tax year. South Carolina specifically does not
  adopt these provisions. S.C. Code Ann. 12-6-50 ... Therefore, taxpayers claiming these provisions will continue
  to make these adjustments on their South Carolina return." Item 8: "Business Assets. The amount taxpayers may
  expense under IRC Section 179 increased to $2.5 million from $1 million." "The Department will issue updated
  guidance once the Legislature addresses conformity." The 2025 instructions p.5 also add a general line e
  bullet: "Add back any federal deductions resulting from IRC sections that South Carolina does not adopt."
  https://dor.sc.gov/income-tax-south-carolina-internal-revenue-code-conformity-update
- **Section 179.** Not on the 12-6-50 not-adopted list (items 1-20 read; none mentions 179, expensing or
  depreciable business assets), so SC follows 179 at the IRC date for the year. That gives, as the federal
  indexed figure at that date: 2021 1,050,000 / 2,620,000; 2022 1,080,000 / 2,700,000; 2023 1,160,000 /
  2,890,000; 2024 1,220,000 / 3,050,000 (the limits for the tax year itself were all published before the
  adopted date). SC prints none of these numbers, so they are derived. For 2025 SC is at the Code as of 31 Dec
  2024 and has not adopted the OBBBA 2,500,000 / 4,000,000; the JSON carries the Rev. Proc. 2024-40 indexed
  amounts 1,250,000 / 3,130,000 as my derivation, flagged in `verify_note`. For 2026 the figure is unknown
  (null).
- **168(n).** 12-6-50(4) lists 168(n) as not adopted. The OBBBA qualified production property allowance is a
  new 168(n) added after the 31 Dec 2024 Code date, so it is outside the adopted Code in any case; the 2025 line
  e instruction on unadopted sections would require the add-back (my reading, not an agency sentence naming
  production property).
- **Other adjustments a calculator must apply (from the instructions).** (1) Capital Investment Tax Credit
  property (qualifying investments after 30 Jun 1998): reduce the SC basis by the credit claimed and add back
  the resulting reduction in depreciation (line e). (2) 12-6-50(19) Section 199A is not adopted: add back the
  QBI deduction (line e). (3) 12-6-50(5B) Section 163(j) business interest limitation is not adopted (statute
  only; no instruction line read). (4) 2021 and 2022 only: business meals deducted in full under 274(n)
  federally are added back because SC allows 50%. (5) Gain or loss: adjust to reflect any difference between SC
  and federal basis (line e and line v lists, every year). (6) NOL: add back a federal NOL larger than the SC NOL;
  no carryback. (7) Out-of-state rental or business income and losses are taken out on lines h and b, so
  depreciation on out-of-state property does not reach SC taxable income. (8) The elective 3% flat rate on
  pass-through "active trade or business income" (I-335, SC1040 lines l and 8) was not read; depreciation
  adjustments would feed that base.
- **2026.** H. 5167 (introduced 11 Feb 2026, would move the date to 31 Dec 2025) was still in House Ways and
  Means on the bill page. H. 3368 (an overtime-exclusion bill whose section 1 would move the date to 31 Dec 2025)
  failed second reading in the Senate on 31 Mar 2026, 16 to 27, per the bill page. The codified section still
  reads 31 Dec 2024. S. 507 became Act 63 of 2025 (approved 22 May 2025, per a search result; it set the 2024
  date and the expired-section extension). So 2026 is carried at 31 Dec 2024, `verified=false`, because
  the session calendar was not checked.
- **Open.** An SC DOR statement of the 2025 179 amount; any 2026-session conformity act or later special
  session; 2026 SC1040 instructions when issued; I-335 treatment of depreciation adjustments.

Rows: 6 for SC. 2021-2025 `verified=true` (conformity date and bonus add-back read from agency text each year;
179 dollar figures derived and flagged); 2026 `verified=false`.
