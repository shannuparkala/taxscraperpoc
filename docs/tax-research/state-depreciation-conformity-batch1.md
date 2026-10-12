---
topic: State depreciation conformity, batch 1 of 6 (AL, AK, AZ, AR, CA, CO, CT, DE, DC), personal income tax, tax years 2021-2026
tax_years: 2021, 2022, 2023, 2024, 2025, 2026
figures_as_of: 2026-10-05
figures_source_url: per-state URLs below (state statute sites and state agency hosts)
status: verify
---

# State depreciation conformity, batch 1 (AL, AK, AZ, AR, CA, CO, CT, DE, DC)

Recorded 2026-10-05. Enacted law only. Scope is the personal income tax as it
applies to a sole proprietor, pass-through owner or rental owner. Corporate rules
are noted only where they differ. Federal reference figures are taken from
`docs/tax-research/depreciation-macrs-179-bonus-280f-2021-2026.md` (same date,
which carries the IRS citations and its own `verify` flags) and are not re-derived
here.

Two federal layers for 2025: Rev. Proc. 2024-40 (Section 179 $1,250,000 /
$3,130,000, bonus 40% for property acquired before 20 Jan 2025) and then Pub. L.
119-21 (OBBBA) sec. 70301 (100% bonus, property acquired after 19 Jan 2025),
sec. 70306 (Section 179 $2,500,000 / $4,000,000) and sec. 70307 (new IRC 168(n)
qualified production property, 100%, property placed in service after 4 Jul 2025).
Where a state "conforms", the federal figures for the year are the state figures:

| Tax year | Federal bonus 168(k) | Federal 179 limit | Federal 179 phase-out start |
|---|---|---|---|
| 2021 | 100% | 1,050,000 | 2,620,000 |
| 2022 | 100% | 1,080,000 | 2,700,000 |
| 2023 | 80% | 1,160,000 | 2,890,000 |
| 2024 | 60% | 1,220,000 | 3,050,000 |
| 2025 | 100% (acquired after 19 Jan 2025); 40% earlier | 2,500,000 (OBBBA; RP 2024-40 said 1,250,000) | 4,000,000 (OBBBA; RP 2024-40 said 3,130,000) |
| 2026 | 100% | 2,560,000 | 4,090,000 |

## How this was researched, and what could not be read

- `ALLOWLIST_DOMAINS` in `tax_research_crawler.py` no longer exists (deleted in the
  2026-10-05 assistant rebuild). Hosts used: each state's agency domain from
  `backend/app/services/assistant/state_registry.py` (revenue.alabama.gov, tax.alaska.gov,
  azdor.gov, dfa.arkansas.gov, ftb.ca.gov, tax.colorado.gov, portal.ct.gov,
  revenue.delaware.gov / revenuefiles.delaware.gov, otr.cfo.dc.gov) and each
  state's legislature / official code site (azleg.gov, leginfo.legislature.ca.gov,
  leg.colorado.gov, delcode.delaware.gov, legis.delaware.gov, code.dccouncil.gov,
  alison.legislature.state.al.us, codeofarrules.arkansas.gov). The registry is
  not a source of tax rules and was used for hosts only.
- **Access limits.** ftb.ca.gov, azdor.gov, tax.colorado.gov and
  content.leg.colorado.gov returned HTTP 403 to the fetch tool. cga.ct.gov and
  codeofarrules.arkansas.gov refused the connection. Agency PDFs (CT, DE TIM,
  AR, AL OBBBA summary, DC booklets) came back as undecodable binary. For those,
  the only evidence is a search-result excerpt of the agency-domain document,
  recorded below as "agency excerpt". An agency excerpt is the agency's text as
  relayed by a search summary, not a page read in full.
- **`verified` meaning in the JSON.** `true` only when every non-null cell in the
  row was read from statute text or an agency HTML page fetched in this session.
  Anything resting on an agency excerpt, or on an inference the note spells out,
  is `false`. Unknown cells are `null` / `"unknown"`, never filled from an
  adjacent year or another state.
- Secondary sources (Tax Notes headline for Alabama) were used for a lead only
  and are not cited as authority.

## Summary matrix (bonus 168(k) treatment, personal income tax)

| State | Individual income tax | Bonus 2021-2024 | Bonus 2025 | Bonus 2026 | 179 | 168(n) |
|---|---|---|---|---|---|---|
| AL | yes | follows federal (verify) | follows federal (verify) | follows federal (verify; 2026 bill lead open) | federal (verify) | not decoupled found (verify) |
| AK | **no** | n/a | n/a | n/a | n/a | n/a |
| AZ | yes | full (net-zero add/subtract) | full | full | federal | adds back 168(n) from tax years beginning after 31 Dec 2025 |
| AR | yes | **none** | none | none | own $25,000/$200,000 in 2021; IRC 179 as of 1 Jan 2022 from 2022 | not adopted |
| CA | yes | **none** | none | none | $25,000 / $200,000 | not in CA law (IRC date 1 Jan 2025) |
| CO | yes | full (verify) | full (verify) | full (verify) | federal (verify) | not decoupled (HB26-1222 died) |
| CT | yes | **add back 100%, subtract 25%/yr over 4 yrs** | same | same | **add back 80%, subtract 25%/yr over 4 yrs** | individual rule not found |
| DE | yes | full | full | **partial: 20% for property acquired and placed in service after 31 Dec 2025** | federal | decoupled for property acquired and placed in service after 31 Dec 2025 |
| DC | yes | **none** | none | none | $25,000 limit | decoupled (temporary law, see open items) |

## Alabama (AL)

Individual income tax: yes (Alabama taxes individual business income; not
separately sourced here because the question concerns depreciation).

- **2008 decoupling.** Act 2008-549 decoupled from the bonus depreciation and the
  additional Section 179 of the federal Economic Stimulus Act of 2008 only
  (agency excerpt of the 2009 Form 20S instructions,
  https://www.revenue.alabama.gov/wp-content/uploads/2021/10/09f20sinstr-1.pdf,
  read 2026-10-05). The 2023 Form 65 instructions (fetched, readable,
  https://www.revenue.alabama.gov/wp-content/uploads/2024/01/23f65instr.pdf) still
  describe only that decoupling: "the provisions of the 2008 Federal Economic
  Stimulus Act or the additional Section 179 expense deduction ... as allowed by
  the 2008 Federal Economic Stimulus Act", and say Alabama income tax laws "are
  similar, but not identical". I found no other depreciation decoupling in those
  instructions or in the search results; that is absence of evidence, not a
  statement by ADOR that Alabama follows later bonus acts.
- **OBBBA.** ADOR's OBBBA Executive Summary with Appendix A
  (https://www.revenue.alabama.gov/wp-content/uploads/2025/11/OBBBA-Executive-Summary_FinalwAppendixA_10.31.25.pdf,
  binary, **not read**; excerpt only) lists IRC 168(k) against Ala. Code 40-18-33
  and 168(n) against 40-16-1(3), and says Alabama "conforms to certain federal
  provisions on a rolling basis". The ADOR page
  https://www.revenue.alabama.gov/tax-policy/obbba/ (read) covers R&E (Act
  2025-400, decouples 174 retroactively to expenditures on or after 1 Jan 2024),
  vehicle interest, charitable and Trump accounts, and says nothing on 168(k),
  168(n) or 179.
- **Open lead.** A Tax Notes headline, "Alabama House Panel Approves Decoupling
  From Federal Bonus Depreciation" (paywalled, 403), suggests a bill that I could
  not identify. 2026 Regular Session HB565 (Rep. Garrett,
  https://alison.legislature.state.al.us/files/pdf/SearchableInstruments/2026RS/HB565-int.pdf)
  appeared in a search but its PDF could not be read, so it is **not** linked to
  the headline. Alabama 2026 bonus must be rechecked on the Legislature's site.
- Calculator rule: assets placed in service in 2008 under the Economic Stimulus
  Act need a separate Alabama basis and Alabama-allowed depreciation (add back
  the federal bonus and additional 179, subtract Alabama-allowed depreciation),
  per the Form 65 instructions above. Relevant only to long-lived real property
  still being depreciated.
- All Alabama rows are `verified=false`.

## Alaska (AK)

- No individual income tax: "The State of Alaska currently does not have an
  individual income tax, therefore no employee withholding for state income tax is
  required." https://tax.alaska.gov/programs/programs/index.aspx?10001 (read
  2026-10-05). Verified.
- Corporate (differs; not studied for depreciation): "Alaska levies a corporate
  income tax on Alaska taxable income which is based on federal taxable income
  with certain Alaska adjustments." https://tax.alaska.gov/programs/programs/index.aspx?60380
  A calculator for a sole proprietor, pass-through owner or rental owner has no
  Alaska depreciation computation to do. Whether a C corporation follows federal
  bonus/179 was not researched.

## Arizona (AZ)

Individual income tax: yes.

- **Conformity type: fixed to a January 1 date, updated each year**, with named
  retroactive acts. A.R.S. 43-105, https://www.azleg.gov/ars/43/00105.htm (read
  2026-10-05): TY2021 IRC "in effect on March 11, 2021" plus P.L. 117-6 and
  117-58; TY2022 "January 1, 2022"; TY2023 "January 1, 2023"; TY2024 "January 1,
  2024"; TY2025 "January 1, 2025 ... and including those provisions of Public Law
  119-21 that are retroactively effective during taxable years beginning from and
  after December 31, 2024 through December 31, 2025"; TY2026 "in effect on
  January 1, 2026 ... excluding any changes to the code enacted after January 1,
  2026". The 2022-2024 paragraphs also adopt the retroactive provisions of P.L.
  119-21 for those years (statute text; none concern 168(k) as far as read).
- **Bonus: full conformity for tax years beginning after 31 Dec 2016.** A.R.S.
  43-1021 para 11 adds back "the amount of any depreciation allowance allowed
  pursuant to section 167(a) ... to the extent not previously added"
  (https://www.azleg.gov/ars/43/01021.htm) and 43-1022 para 17(e) subtracts, "in
  taxable years beginning from and after December 31, 2016, ... the depreciation
  allowable pursuant to section 167(a) ... computed as if the additional allowance
  for depreciation had been the full amount allowed pursuant to section 168(k)"
  (https://www.azleg.gov/ars/43/01022.htm). Net effect is the federal deduction.
  Earlier sub-paragraphs: 0% (as if 168(k)(7) election) before 2013 through 2013;
  10% for 2014-2015; 55% for 2016. Read-through of "the add-back and subtraction
  net to zero" is my reading of the two paragraphs together; the AZDOR page
  https://azdor.gov/about/legal-research/conformity-irc (403) was seen only as a
  search excerpt and describes the older opt-out computation.
- **Section 179:** no Arizona modification in 43-1021 or 43-1022 as read; AZDOR
  excerpt says Arizona conformed to 179 from 1 Jan 2013 ($25,000 cap removed).
  So 179 follows the IRC as defined in 43-105 for the year.
- **168(n):** 43-1021 para 17: "For taxable years beginning from and after
  December 31, 2025, the amount of the special depreciation allowance for
  qualified production property allowed pursuant to section 168(n) ... to the
  extent not previously added." So 2026 decouples; the year-of-addition recovery
  (a matching subtraction) was **not found** in 43-1022 paragraphs 17-26 as read.
- **2025:** the statute's 168(n) addition starts 2026. Whether the 2025 IRC
  definition ("retroactively effective" provisions of P.L. 119-21) takes in
  168(n) for 2025 is not stated; 2025 `decouples_168n` is null. The 2025 100%
  bonus and $2,500,000 179 rest on reading "retroactively effective" as including
  sec. 70301 and 70306; ADOR's search excerpt agrees ("The definition of IRC for
  Tax Year 2025 has been updated to include the provisions of Public Law 119-21
  that became retroactively effective during TY 2025"). Marked `verified=false`.
- Changed recently: yes (2025 IRC definition and 2026 168(n) addition). Bill
  summaries HB4152 / HB4168 (57th Leg. 2R) appeared in search; their status was
  not checked.

## Arkansas (AR)

Individual income tax: yes.

- **Bonus: none.** "No bonus depreciation is allowed for Arkansas income tax
  purposes." Arkansas adopts "Internal Revenue Code Sections 167 and 168(a)-(j) as
  in effect on January 1, 2019, for tax years beginning on or after January 1,
  2019" (ACA 26-51-428 per DFA), https://www.dfa.arkansas.gov/office/taxes/income-tax-administration/corporation-income-tax/corporate-faqs/
  (HTML fetched 2026-10-05; a corporate FAQ, but ACA 26-51-428 is the general
  depreciation section, and no individual-specific rule was found). Earlier
  Arkansas instruction text: Act 372 of 2009 adopted sections 167, 168(a)-(j),
  179 and 179A as of 1 Jan 2009 (agency excerpt).
- **Section 179:** IRC 179 "as in effect on January 1, 2022" for tax years
  beginning on or after 1 Jan 2022 (same FAQ). DFA excerpts of the 2022-2025
  instructions: 2022 $1,080,000 / $2,700,000 ("raised from $25,000 per year ...
  phaseout raised from $200,000"); 2024 $1,220,000 / $3,050,000; 2025 $1,250,000
  / $3,130,000. These equal the federal Rev. Proc. amounts, so **OBBBA's
  $2,500,000 is not adopted for 2025**. 2021 is the pre-2022 Arkansas limit
  ($25,000 / $200,000). 2023 ($1,160,000 / $2,890,000) is **derived** from the
  federal indexing and not seen in an Arkansas document. 2026: unknown, no 2026
  instruction published as of this date.
- One excerpt's text said the 2025 deduction "phases out ... until hitting $0 at
  $4,270,000". 3,130,000 + 1,250,000 is 4,380,000 (4,270,000 is the 2024 figure),
  so that sentence is wrong or mis-summarised; use 4,380,000 (derived).
- **168(n):** not in 168(a)-(j) and enacted after 1 Jan 2019, so not adopted
  (structural; no AR document states it).
- Statute text itself (arkleg / codeofarrules) could not be reached; all Arkansas
  rows `verified=false`.

## California (CA)

Individual income tax: yes (also the Franchise Tax Board forms for pass-throughs).

- **Conformity: fixed.** R&TC 17024.5(a)(1) (read 2026-10-05,
  https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=RTC&sectionNum=17024.5):
  "(P) taxable years beginning on or after January 1, 2015, and on or before
  December 31, 2024 ... January 1, 2015"; "(Q) taxable years beginning on or
  after January 1, 2025 ... January 1, 2025". Amended by Stats. 2026, ch. 236
  (SB 1435), effective 14 Sep 2026, applicable to taxable years beginning on or
  after 1 Jan 2025.
- **Bonus: none.** R&TC 17250(a)(11): "Section 168(k) of the Internal Revenue Code,
  relating to special allowance for certain property, shall not apply"
  (https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=RTC&sectionNum=17250).
  17250 was repealed and re-added by SB 1435 for taxable years beginning on or
  after 1 Jan 2025. The pre-2025 text of 17250 was **not read**; California's
  nonconformity for 2021-2024 rests on the FTB 3885A instruction excerpts and the
  current statute. Depreciation is computed as if no bonus was claimed; the
  difference is tracked on FTB 3885A.
- **Section 179: not conforming.** R&TC 17255(a) "$25,000" and (b) reduction by
  the excess of 179 property cost over "$200,000" (fully phased out at $225,000,
  derived), plus (g)/(h) excluding the 2016 appropriations act and TCJA changes to
  179 (https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=RTC&sectionNum=17255).
  Amended by Stats. 2025, ch. 231 (SB 711), effective 1 Oct 2025. OBBBA's 179
  increase is therefore irrelevant for California.
- **168(n) / OBBBA:** P.L. 119-21 (4 Jul 2025) postdates the 1 Jan 2025
  conformity date, so 168(n) and the new 179 amounts are not California law for
  2025 or 2026 (derived from the date; neither text names 168(n)). SB 1435 digest
  (https://leginfo.legislature.ca.gov/faces/billNavClient.xhtml?bill_id=202520260SB1435):
  conforms to the IRC as of 1 Jan 2025; business interest limit not applicable
  for personal income tax from 2025.
- Other 17250(a) items a calculator must carry: 168(e)(6) qualified improvement
  property "shall not apply" (QIP is 39-year, not 15-year, in California), and
  168(g)(1)(F)/(G), 168(j), 168(l), 168(m) do not apply. State schedule: FTB 3885A
  (individuals, estates, trusts, pass-throughs), per the FTB instruction excerpts.
- 2025 and 2026 rows `verified=true`; 2021-2024 rows `verified=false`.

## Colorado (CO)

Individual income tax: yes.

- **Bonus and 168(n): no Colorado decoupling enacted as of 2026-10-05.**
  HB26-1222 would have added back 168(k) excess over pre-OBBBA allowance and
  168(n) depreciation "for tax years beginning January 1, 2027 or later" (subtract
  starting 2028, carryforward up to 10 years); status "Lost", Senate Finance
  postponed indefinitely 11 May 2026 (https://leg.colorado.gov/bills/hb26-1222,
  read). HB25B-1001 (signed 28 Aug 2025) only continues the 199A QBI add-back
  (https://leg.colorado.gov/bills/HB25B-1001, read). HB26-1289 (signed 3 Jun 2026)
  does not touch 168(k), 168(n), 179 or 174 (https://leg.colorado.gov/bills/hb26-1289,
  read).
- Conformity type rolling and the 179 follow-the-federal rule rest on an agency
  excerpt ("Colorado's state tax base begins with federal taxable income") and on
  the bill text above; C.R.S. 39-22-104 and the tax.colorado.gov pages (403) were
  not read. No Colorado 179 limit was found. All Colorado rows `verified=false`.
- If HB26-1222's 2027 start is reintroduced, 2027 changes; nothing applies to
  2021-2026.

## Connecticut (CT)

Individual income tax: yes.

- **Bonus: add back 100% of the 168(k) deduction** for property placed in service
  after 27 Sep 2017, taxable years beginning on or after 1 Jan 2017; **subtract 25%
  of the added-back amount in each of the four succeeding taxable years**
  (Conn. Gen. Stat. 12-701(a)(20), agency excerpts of OCG-5 and SN 2018(9.1),
  https://portal.ct.gov/-/media/DRS/Publications/OCG/OCG5BonusDepreciationNoticepdf.pdf?la=en
  and the 2025 CT-1040 instructions,
  https://portal.ct.gov/-/media/drs/forms/2025/income/2025-ct-1040-instructions_1225.pdf;
  PDFs unreadable; 2025 CT-1040 Schedule 1 has an addition line and a 25%
  subtraction line, per the excerpt). A year's subtraction covers additions from
  the four preceding years, so 2021 still subtracts 25% of the 2017 (after 27 Sep),
  2018, 2019 and 2020 additions. Passes through partnerships and S corporations
  to individuals (Schedule CT K-1).
- **Section 179: add back 80% of the federal deduction**, taxable years on or
  after 1 Jan 2018; subtract 25% of the amount added back in each of the four
  succeeding years (agency excerpts as above; the excerpt says "25% of the Section
  179 federal deduction that was added back", read here as 25% of the 80%).
  Federal limit applies first.
- **Conformity:** starts from federal AGI; type recorded as rolling with statutory
  modifications (not stated in a source read).
- **2025 and 2026:** the DRS 2026 developments page
  (https://portal.ct.gov/drs/miscellaneous-taxes/other-tax-page/state-tax-developments/2026-developments,
  read) records that the legislation "decouples the deduction from gross income
  relative thereto allowed under Conn. Gen. Stat. 12-217 from the provisions of IRC
  168(n)" for the **corporation business tax** from the 2026 income year (also
  corroborated by the OLR analysis of sSB 84, excerpt). The 2025 Income Tax and
  November Special Session pages (read) have nothing on depreciation. No personal
  income tax change for 168(n) was found, so individual 168(n) treatment is
  `null` (unknown), not "no".
- Statute site cga.ct.gov refused connections; all CT rows `verified=false`.

## Delaware (DE)

Individual income tax: yes.

- **Conformity: rolling.** 30 Del. C. 1105: "federal adjusted gross income as
  defined in the laws of the United States as the same are or shall become
  effective for any taxable year" (https://delcode.delaware.gov/title30/c011/sc02/index.html,
  read 2026-10-05). Modifications in 1106(a)-(c) mention no depreciation, 168 or
  179.
- **2021-2025 individuals: no depreciation modification; follows federal bonus
  and 179.** (Statute read as above; TIM 2025-02 excerpt says individuals are
  affected only for property placed in service after 31 Dec 2025.)
- **2026 change (HB 255, 85 Del. Laws ch. 231; signed 19 Nov 2025; section 2
  effective 1 Jan 2026; further amended in 85 Del. Laws ch. 426).** 30 Del. C.
  1106(d): "(1) For property acquired and placed in service after December 31, 2025,
  and before January 1, 2031, which would otherwise be eligible for expensing under
  70301 of P.L. 119-21, to continue the amortization and depreciation of such
  property under the [IRC] provisions in effect immediately before the enactment of
  70301 ... (2) For qualified production property, as defined in 70307 of P.L.
  119-21, acquired and placed in service after December 31, 2025, and before
  January 1, 2031, to continue ... under the [IRC] provisions in effect immediately
  before the enactment of 70307". Source for the rate: TIM 2025-02 (23 Dec 2025,
  https://revenuefiles.delaware.gov/2025/TIMs/HB_255_TIM.pdf, PDF unreadable;
  agency excerpt) states individual bonus continues under the TCJA schedule: 40%
  (2025), 20% (2026), 0% (2027 and later). The statute says "acquired **and**
  placed in service after 31 Dec 2025"; the TIM excerpt says "placed in
  service". Property acquired earlier (federal 100% if after 19 Jan 2025) and
  placed in service in 2026 is not within the statute's words, so Delaware
  follows the federal 100% for it.
- Section 179: not decoupled (HB 255 touches 70301 and 70307 only; the 70306 179
  increase flows through). Corporate difference: C corporations decouple from the
  100% allowance for property placed in service after 19 Jan 2025 (HB 255
  synopsis, https://legis.delaware.gov/BillDetail/142718, read) - not relevant to a
  pass-through owner.
- Rows `verified=true`; the 20% figure comes from the TIM excerpt plus the
  statute's reference to pre-OBBBA law and is flagged in `verify_note`.

## District of Columbia (DC)

Individual income tax: yes (D-40). DC also levies an unincorporated business
franchise tax on unincorporated businesses (form D-30, 2025 booklet at
https://otr.cfo.dc.gov/sites/default/files/dc/sites/otr/publication/attachments/2025_D30_Book_Final_wLinks_02232026.pdf,
not read); the depreciation rules there were not confirmed. Lead only.

- **Bonus: none, since taxable years beginning after 31 Dec 2008.** D.C. Code
  47-1803.03(a)(7): "No deduction shall be allowed for the special depreciation
  allowance under section 168(k) of the Internal Revenue Code of 1986"; and
  (b-3)(2)(A) for individuals (https://code.dccouncil.gov/us/dc/council/code/sections/47-1803.03,
  read 2026-10-05). The effective-date note cites D.C. Law 17-219 sec. 7114:
  "taxable years beginning after December 31, 2008". Depreciation is therefore the
  ordinary allowance on full basis, as if no bonus was claimed (my reading of
  "reasonable allowance" remaining while the special allowance is denied); DC
  basis differs from federal basis.
- **Section 179:** 47-1803.03(a)(18) "the lesser of $25,000 or the actual cost";
  (b-3)(2)(B) for individuals "$25,000 (or $40,000 in the case of a Qualified High
  Technology Company)". The text read states **no phase-out threshold**, so
  `sec179_phaseout` is null.
- **Conformity type:** 47-1801.04 defines the Internal Revenue Code of 1986 by
  enactment date, "which provisions shall apply on the same dates that they are
  effective for federal tax purposes" (https://code.dccouncil.gov/us/dc/council/code/sections/47-1801.04,
  read). No cutoff date, so conformity is automatic (recorded "rolling") with
  line-item decouplings. Not stated in so many words.
- **2025-2026 and OBBBA:** D.C. Act 26-214 (emergency, effective 3 Dec 2025,
  https://code.dccouncil.gov/us/dc/council/acts/26-214) and D.C. Law 26-89 (D.C.
  Income and Franchise Tax Conformity and Revision Temporary Amendment Act of 2025,
  effective 12 Feb 2026, expires after 225 days,
  https://code.dccouncil.gov/us/dc/council/laws/26-89) add: "No deduction shall be
  allowed for the special depreciation allowance under 168(n)", plus 168(k) and the
  $25,000 limit, applicable to taxable years beginning after 31 Dec 2024. OTR's
  2025 D-41 booklet (excerpt) states DC does not allow 168(k), 168(n) or the
  additional 179 on the DC return. The current text of 47-1803.03 does **not**
  carry 168(n); only the temporary law does, and 225 days from 12 Feb 2026 is about
  25 Sep 2026 (derived), before today. Whether a permanent act or a further emergency
  act is in force was not found. So 2026 `decouples_168n` is null.
- Rows `verified=true` where only permanent statute text is relied on.

## Proposed engine entries

None. These are per-state rules and per-year constants with different authority
paths, not single constants for `tax_authority.py`. If a state depreciation
module is built, every cell below should enter as `verified=False` until a human
has checked it against primary text, and the `verified=false` rows here need the
agency instruction (CT, AR, AL, CO) read from a page the tool could decode.

## Open items

1. **Alabama 2026**: identify the bonus-decoupling bill behind the Tax Notes
   headline and its status; read ADOR's OBBBA Appendix A and Ala. Code 40-18-33
   directly. All Alabama rows are unverified.
2. **Colorado**: read C.R.S. 39-22-104 and tax.colorado.gov income tax topics on
   depreciation and 179 from an accessible copy; confirm no 179 limit exists.
3. **Connecticut**: read Conn. Gen. Stat. 12-701(a)(20) (the 80% / 25% and 100% /
   25% rules and the exact base of the 25%); find whether the personal income tax
   decoupled from 168(n) in 2026.
4. **Arkansas**: read ACA 26-51-428 and the 2026 instructions (179 amount for
   2026, individual-return adjustment form). 2023 179 figures are derived.
5. **Arizona**: confirm the 168(n) subtraction (recovery) paragraph in 43-1022 and
   whether 168(n) is in or out of the 2025 definition.
6. **DC**: whether a permanent act replaced D.C. Law 26-89 (expired about 25 Sep
   2026); phase-out threshold for the $25,000 179 limit; D-30 unincorporated
   business depreciation.
7. **California**: read the pre-2025 text of R&TC 17250 and 17255 and the FTB
   3885A instructions for 2021-2024 (all 403 here).
8. **Federal 2021-2022 bonus (100%) and 2021/2023 179 amounts** carry the earlier
   note's `verify` flags.
