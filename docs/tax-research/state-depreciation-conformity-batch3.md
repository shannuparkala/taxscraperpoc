---
topic: State depreciation conformity, batch 3 of 6 (LA, ME, MD, MA, MI, MN, MS, MO, MT), personal income tax, tax years 2021-2026
tax_years: 2021, 2022, 2023, 2024, 2025, 2026
figures_as_of: 2026-10-05
figures_source_url: per-state URLs below (state revenue agency hosts, state legislature / statute hosts)
status: verify
progress: INCOMPLETE. LA and ME done; MD done through 2024 and partial for 2025-2026; MA, MI, MN, MS, MO, MT not started. Research stopped when the web tools hit a session limit (resets 10pm IST). Resume at Maryland 2025-2026, then MA onward.
---

# State depreciation conformity, batch 3 (LA, ME, MD, MA, MI, MN, MS, MO, MT)

Recorded 2026-10-05. Enacted law only. Scope is the personal income tax as it applies to a
sole proprietor, pass-through owner or rental owner; corporate rules are noted only where they
differ. Extends `docs/tax-research/depreciation-macrs-179-bonus-280f-2021-2026.md` and follows
`state-depreciation-conformity-batch2.md`. Machine-readable rows are in
`state-depreciation-conformity-batch3.json`.

Federal reference (IRS sources and their own `verify` flags are in the depreciation note):
bonus 2021 100%, 2022 100%, 2023 80%, 2024 60%, 2025 100% for property acquired after 19 Jan 2025
(40% earlier), 2026 100%; Section 179 limit / phase-out start 2021 1,050,000 / 2,620,000,
2022 1,080,000 / 2,700,000, 2023 1,160,000 / 2,890,000, 2024 1,220,000 / 3,050,000,
2025 2,500,000 / 4,000,000 (OBBBA; Rev. Proc. 2024-40 said 1,250,000 / 3,130,000),
2026 2,560,000 / 4,090,000. 168(n) qualified production property is new from OBBBA.

## How this was researched

- `ALLOWLIST_DOMAINS` in `tax_research_crawler.py` no longer exists (deleted in the 2026-10-05
  rebuild). Hosts used are the agency domains in `backend/app/services/assistant/state_registry.py`
  (revenue.louisiana.gov, dam.ldr.la.gov is LDR's document host; maine.gov; marylandtaxes.gov, which
  now 301-redirects to the Comptroller's own marylandcomptroller.gov) plus legislature sites.
- Unlike batch 2, the `Read` tool did decode agency PDFs (without a `pages` argument). The
  WebFetch summariser cannot read PDFs; the file it saves can be opened with `Read`. A booklet
  costs 30-150k tokens, so booklets were read only where a year-specific line was needed.
- `legis.la.gov` refused every connection (ECONNREFUSED), so Louisiana statute text was not read;
  statute citations are taken from LDR documents.
- `verified` means every non-null cell was read from an agency document or statute in this
  session. Unknown is `"unknown"`/null; no year is filled from an adjacent year.

## Louisiana (LA)

Individual income tax: yes (flat 3% from 2025; graduated before, per RIB 25-012).

- **2021, 2022: not determined.** Instructions for those years were not read. Only a 2002 LDR
  ruling is on hand: Revenue Ruling 02-009 (https://dam.ldr.la.gov/lawspolicies/RR02009.pdf,
  read) says the individual starting point is federal AGI and, because La. R.S. 47:293 had no
  depreciation modification, the federal additional first-year depreciation was followed. That is
  a 2002 position, not a 2021-2022 one. Search results also surfaced a 2018 bill (HB 22, Rep.
  Johnson) that would have made 168(k) depreciation and 179 expensing above 25,000 "inoperative";
  whether it became law could not be confirmed. The 2023 to 2025 forms below show no such
  adjustment, which argues against it being in force for individuals, but that is not proof for 2021-2022.
- **2023: federal bonus and 179 flow through.** The 2023 IT-540 instructions
  (https://dam.ldr.la.gov/taxforms/IT540i%20WEB(2023)%20INSTRUCTIONS.pdf, read) put federal AGI on
  Schedule E line 1; the only additions are lines 2A-2D (non-LA municipal interest, START
  refunds, pass-through-entity NOL). No depreciation line. Same for 2024
  (https://dam.ldr.la.gov/taxforms/IT540i%20WEB%20(2024)D18%20INSTRUCTIONS.pdf, read).
- **2025: new elective state full expensing.** Act 11 of the 2024 Third Extraordinary Session,
  codified at La. R.S. 47:297.25, applies to tax periods beginning on or after 1 Jan 2025
  (RIB 25-012, 7 Mar 2025, item 6, read:
  https://dam.ldr.la.gov/lawspolicies/RIB-25-012-Louisiana-Individual-Income-Tax-Reform-1.pdf;
  2025 instructions, read: https://dam.ldr.la.gov/taxforms/IT540i-WEB-2025.pdf). The taxpayer may
  deduct 100% of the cost of qualified property and qualified improvement property in the year
  placed in service, "qualified property" meaning 168(k) and 168(e)(6) "as in effect on
  January 1, 2024"; R&E expenditures use 174 as of 1 Jan 2024. Schedule E code 32E reports "the
  bonus depreciation amount that exceeds the depreciation claimed on your federal return"; in
  each later year Line 2E adds back the federal depreciation claimed on that property. Form
  R-90158 (Bonus Depreciation Schedule) must be attached. It may not duplicate federal depreciation.
- **168(n) / OBBBA.** The election's definition is frozen at 1 Jan 2024, so 168(n) property is
  outside it. Federal 168(n) and the 100% federal bonus still reach the return through federal
  AGI; no add-back line exists on the 2025 Schedule E. That `decouples_168n=false` is an inference
  from the absence of a line, and the 2025 change predates OBBBA (it is not a response to it).
- **2026: not published.** RIB 25-012 is titled "Effective for 2025 and Future Tax Years". No
  2026 instructions or 2026 session change was found; row marked `verified=false`.
- **Calculator rule:** for LA 2025, compute federal depreciation as filed; if the user elects
  state expensing, state deduction = 100% of cost minus federal depreciation for that property,
  with a later-year add-back of the federal depreciation. The election is by property.

## Maine (ME)

Individual income tax: yes (7.15% top rate per the 2026 summary; not otherwise sourced here).

- **Bonus: decoupled in every year 2021-2026.** Source: Maine Revenue Services, "Modifications
  Related to Bonus Depreciation & Section 179 Expensing", revised May 2022
  (https://www.maine.gov/revenue/sites/maine.gov.revenue/files/inline-files/Bonusdep_guidance_2022.pdf,
  read in full). Individuals add to federal AGI, under 36 MRSA 5122(1)(KK) (taxable years beginning
  on or after 1 Jan 2015), "the net increase in depreciation attributable to the depreciation
  deduction claimed ... under the Code, Section 168(k)", i.e. federal depreciation minus what would
  have been allowed without bonus, in the year placed in service. In each later year 5122(2)(RR)
  (years beginning on or after 1 Jan 2020) subtracts "the net increase in the depreciation deduction
  allowable under the Code, Sections 167 and 168 that would have been applicable ... had ... 168(k) not
  been claimed". Total subtractions cannot exceed the addition, remaining recapture is allowed on
  disposition, and gain or loss on sale is the federal figure. The guidance's worked example: a
  $100,000 five-year asset with 100% federal bonus has an $80,000 addition (100,000 less 20,000
  regular first-year MACRS), then subtractions of $32,000, $19,200, $11,520, $11,520, $5,760.
  No loss carryover of an unused subtraction. A calculator needs a parallel no-bonus schedule per asset.
- **Section 179: full conformity.** The same guidance says "For tax years after 2010, Maine law is in
  full conformity with IRC section 179" and that no 179 modification is needed for property placed
  in service in 2020 or after. Federal limits therefore apply.
- **Conformity type: fixed to a Code date.** MRS Tax Alert, Oct 2025 vol 35 iss 14
  (https://www.maine.gov/revenue/sites/maine.gov.revenue/files/inline-files/ta_october2025_vol35_iss14_0.pdf,
  read): "Maine conforms to the Internal Revenue Code ... as of December 31, 2024". The Code dates for
  tax years 2021-2023 were not read.
- **2025 and OBBBA, two layers.** The Legislature adjourned 25 Jun 2025, before OBBBA (4 Jul 2025).
  Under P.L. 2025, c. 336 the Governor directed the 2025 forms to: conform to Section 179 expensing,
  qualified disaster loss, qualified farm property, business interest and limited R&E amended
  returns; not conform to the higher standard deduction, accelerated depreciation for qualified
  production property (168(n)), bonus depreciation and R&E expensing for 2025 and later. The
  Alert's table prices bonus conformity at -102.8M for TY2025 and recommends "Do not adopt".
  The Legislature then acted in 2026: MRS, "2026 Session Legislation Enacted"
  (https://www.maine.gov/revenue/sites/maine.gov.revenue/files/inline-files/legischange26.pdf, read),
  P.L. 2025, c. 650, Pt. K, effective 29 Jul 2026: Title 36 references to the Code are updated to
  the Code as amended through 31 Dec 2025, "generally ... tax years beginning on or after January 1,
  2025"; a new addition modification, 36 MRSA 5122(1)(RR), equal to the net increase in depreciation
  attributable to the 168(n) deduction, recaptured ratably under 5122(2)(CCC); domestic R&E
  addition of 100% for 2025 and 70% for 2026 (small businesses excepted).
- **Special rules for a calculator:** pass-through owners scale the add-back and recapture by the
  passive-loss or at-risk percentage; a new partner gets no recapture of an earlier partner's
  add-back; employee business expense bonus on Form 2106 is added back; the Maine Capital Investment
  Credit (1.2% of the addition for property placed in service in years beginning 2020 and later per
  the May 2022 guidance) was removed as "expired" by the 2026 session law, expiry date not read.
- **Open:** 2026 section 179 indexed amounts (2,560,000 / 4,090,000) are assumed from the federal
  Code as of 31 Dec 2025; no Maine page states them.
- Side finding: Part 6 of the Maine guidance prints half-year MACRS percentage tables for 3-, 5-,
  7-, 10-, 15- and 20-year property (for example 20-year: 3.750, 7.219, 6.677, 6.177, 5.713 ...).
  That is a Maine agency copy of the Pub. 946 Table A-1 values the federal note could not read,
  usable as a cross-check against `MACRS_HALF_YEAR`, but it is not the IRS source.

## Maryland (MD)

Individual income tax: yes (state tax plus county/Baltimore City local tax, per `state_registry`).

- **Bonus 2021-2024: permanently decoupled for non-manufacturers.** Comptroller of Maryland,
  Administrative Release No. 38, "Decoupling from Federal Income Tax Laws", revised June 2022
  (https://www.marylandcomptroller.gov/content/dam/mdcomp/tax/legal-publications/administrative-releases/income-and-estate-tax/ar_it38.pdf,
  read in full; marylandtaxes.gov redirects there by 301). "A taxpayer that is not a manufacturing
  entity must determine the depreciation deduction provided by I.R.C. section 167(a) for tangible
  property without regard to the additional allowance under I.R.C. section 168(k)." The taxpayer
  "must add back ... the amount of additional deduction allowance under I.R.C. section 168(k) in the
  year the allowance is claimed, which amount the taxpayer then ratably subtracts ... in the
  subsequent years in accordance with the applicable property depreciation method for the duration of
  the applicable recovery period". It requires separate pro forma federal returns and Form 500DM, and
  applies to individuals, fiduciaries, corporations and pass-through entities (the entity allocates
  the adjustment on the K-1). Created by BRFA 2002 (Ch. 440) in TG 10-210.1 and 10-310.
- **Manufacturing-entity exception.** The 2017 More Jobs for Marylanders Act (SB 317) exempts
  "manufacturing entities" from the decoupling for property placed in service on or after 1 Jan
  2019: they take 167(a), 168(k) and 179 as federal, with no 500DM. The statutory definition of
  manufacturing entity was not read; a calculator must ask the user.
- **Section 179: state cap 25,000, phase-out 200,000.** AR IT-38: "may not exceed $25,000, subject to
  the phase-out threshold of $200,000", determined "without regard to any changes made to that
  section after December 31, 2002", made permanent by BRFA 2004 (all tax years beginning after 31 Dec
  2002), BRFA 2005, Ch. 587 of 2007, TG 10-210.1 as amended in the 2007 special session, and BRFA 2009.
  The dollar-for-dollar reduction above 200,000 is stated in II.A.1.
- **Heavy-duty SUVs:** apply the 280F limits as if rated 6,000 lb GVWR or less, for all taxpayers
  including manufacturers (TG 10-210.1(5)).
- **Conformity type: selective.** AR IT-38: "Generally, Maryland income tax laws conform to federal
  income tax laws, except where the Maryland Legislature has enacted legislation otherwise, or where
  Maryland is automatically decoupled due to revenue impact". TG 10-108: a federal change worth
  5,000,000 or more is decoupled for tax years beginning in the year of enactment unless the General
  Assembly acts; the following year the change flows through unless the Assembly legislates.
- **2025 and OBBBA (NOT fully read).** The Comptroller published "Tax Alert: Maryland Impacts of the
  One Big Beautiful Bill Act"
  (https://www.marylandcomptroller.gov/content/dam/mdcomp/tax/legal-publications/alerts/tax-alert-maryland-impacts-of-the-one-big-beautiful-bill-act.pdf)
  and a 2025 Form 500DM (https://www.marylandcomptroller.gov/content/dam/mdcomp/tax/forms/2025/500dm.pdf).
  Only search-result excerpts were seen: automatic decoupling for tax year 2025 from OBBBA's qualified
  production property allowance (168(n)), domestic R&E expensing and the business interest change; the
  OBBBA 179 increase (1.25M to 2.5M) does not apply and the state cap stays 25,000 less the amount of
  investment over 200,000; manufacturing entities conform to 100% bonus for property placed in service
  after 19 Jan 2025. Treat as a lead (`verified=false`), not a figure.
- **2026 (unresolved).** Search excerpts of 2026-session fiscal notes (HB 801 and others,
  mgaleg.maryland.gov) describe limiting a manufacturing entity's 168(k) allowance to 20% of adjusted
  basis for tax year 2026 and beyond and permanently decoupling from 168(n). Enactment was not confirmed
  and the fiscal note PDF could not be opened.
- **Next step for this state:** open the OBBBA tax alert and the 2025 Form 500DM instructions, then the
  2026 enacted chapter, and replace the `verified=false` 2025 and 2026 rows.
