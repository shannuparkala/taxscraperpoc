---
topic: State depreciation conformity, batch 4 (MA, MI, MN, MS, MO), personal income tax, tax years 2021-2026
tax_years: 2021, 2022, 2023, 2024, 2025, 2026
figures_as_of: 2026-10-06
figures_source_url: per state below (agency and legislature pages; see each section)
status: verify
progress: All five states done (MA, MI, MN, MS, MO). Rows are in state-depreciation-conformity-batch4.json (valid JSON list of 30 rows, rewritten after each state).
---

# State depreciation conformity, batch 4 (MA, MI, MN, MS, MO)

Recorded 2026-10-06. This file replaces the earlier placeholder, which listed NE, NV, NH, NJ, NM, NY, NC, ND and OH
(since reassigned). Enacted law only. Federal reference figures (bonus rates, 179 limits) are in
`docs/tax-research/depreciation-macrs-179-bonus-280f-2021-2026.md` and are not restated here except where a state's cell
equals one.

Sources: `ALLOWLIST_DOMAINS` in `tax_research_crawler.py` no longer exists (file deleted in the 2026-10-05 rebuild).
Agency hosts come from `backend/app/services/assistant/state_registry.py`: MA mass.gov; MI michigan.gov; MN
revenue.state.mn.us; MO dor.mo.gov; MS dor.ms.gov. Legislature or statute hosts (malegislature.gov, legislature.mi.gov,
revisor.mn.gov, revisor.mo.gov and documents.house.mo.gov, legislature.ms.gov) are not in the registry and are cited only
as the brief's "official statute site".

Tooling notes for the whole batch:
- `mass.gov`, `michigan.gov` and `legislature.mi.gov` returned HTTP 403 to every WebFetch, and `malegislature.gov`
  refused the connection. Cells for MA and MI therefore rest on agency-domain search-result excerpts, never full text,
  and carry verified=false.
- `revenue.state.mn.us` HTML pages redirect to a third-party bot-challenge host (perfdrive.com). I did not follow it.
  Its PDFs download, and the Read tool opens them from the saved tool-result file (no `pages` argument; with `pages`
  it needs poppler, which is not installed). A full Read of a 25-page booklet costs roughly 25-75k tokens because each
  page is also returned as an image.
- `revisor.mn.gov` statute pages fetch normally, including year editions (`/statutes/2022/cite/290.0131`).
- `dor.ms.gov` pages and PDFs fetch; `billstatus.ls.state.ms.us` fails TLS verification ("unable to verify the first
  certificate") and Justia returns 403, so the Mississippi statute text itself was not read.
- Missouri: every `dor.mo.gov` fetch returned 403, `revisor.mo.gov` and `senate.mo.gov` refused the connection
  (ECONNREFUSED), but `documents.house.mo.gov` bill PDFs fetch. WebFetch saves the PDF binary to the tool-results folder
  and the Read tool then opens it (see the Missouri section for what that gave).

## Massachusetts (MA)

Status: verify. All six rows verified=false (excerpts only).

### Rule in plain terms

- Income tax: yes (personal income tax under G.L. c. 62).
- Bonus, IRC 168(k): none, all six years. Massachusetts depreciation is computed under IRC 168 as if the taxpayer elected
  not to claim the bonus allowance, in the placed-in-service year and every later year. Differences are reported on
  Massachusetts Schedule X line 6 (2025 Form 1 instructions, excerpt). There is no add-back-and-spread schedule; the
  recovery comes through regular depreciation on a separate Massachusetts basis.
  Source: https://www.mass.gov/technical-information-release/tir-03-25-depreciable-business-assets-modifications-for-decoupling-from-federal-bonus-depreciation
  (TIR 03-25, excerpt); TIR 18-14 excerpt: MA "follows the current Code with respect to Code section 168, except 168(k)".
- Section 179: Massachusetts adopts the federal 179 rules and their inflation adjustments, with one exception, 2025-2026
  (below). Excerpted maximums: 2023 1,160,000 (2023 Form 1 instructions), 2024 1,220,000 (2024 Form 1 instructions),
  2025 1,250,000 with phase-out 3,130,000 (2025 Form 1 instructions). For 2021 and 2022 no MA document stating the figure
  was seen; the rows carry the federal amounts (1,050,000/2,620,000 and 1,080,000/2,700,000), flagged as assumed.
- Conformity type: fixed to a Code date, with named exceptions. Personal income tax followed the Code as amended on
  1 Jan 2005 before TY2022 (TIR 23-1 excerpt); the Code as amended on 1 Jan 2022 for TY2022-2023 (FY23 Budget, TIR 23-1);
  the Code as amended on 1 Jan 2024 for TY2024 onward (G.L. c.62 s.1(c) as amended by St. 2024 c.140 ss.251 and 264;
  TIR 24-14). Selected sections follow the Code currently in effect (62(a)(1), 72, 105, 106, 108(f)(5), 139C, 223,
  274(m), 274(n), 401-420 and others, per the c.62 s.1(c) excerpt).

### 2025 and 2026, after P.L. 119-21

- 168(n) qualified production property: not allowed for tax years beginning on or after 1 Jan 2025 and before
  1 Jan 2027. The federal deduction is added back in computing MA AGI.
- Section 179: calculate "without regard to the amendments made by P.L. 119-21" for the same window. So 2025 uses
  1,250,000 / 3,130,000 (the Rev. Proc. 2024-40 amounts, per the 2025 Form 1 instructions excerpt), not the federal
  2,500,000 / 4,000,000. 2026: the pre-OBBBA indexed figure is not stated in anything read; the row is null. Do not use the
  federal 2,560,000 / 4,090,000.
- Mechanism: the FY2026 final mid-year Supplemental Budget (malegislature.gov lists it as Acts of 2026 chapter 101;
  text not read) and DOR TIR 26-4, which began as a "Working Draft TIR". Conformity to 168(n) and the 179 amendments is
  delayed to tax years beginning on or after 1 Jan 2027. Also delayed to 2027: the 163(j)(8)(A)(v) depreciation
  add-back to ATI. 174 and 174A conform from 1 Jan 2026. Relief: no interest or penalty on underpayment attributable to
  the changes; a taxpayer who filed a 2025 return on the federal figures may file an amended return within 90 days of
  enactment.
- 168(k) 100% bonus: no effect on MA (decoupled).

### Open items

1. Read TIR 26-4 and Acts of 2026 ch. 101 in full. The enactment date and the exact statutory wording of the 179 delay
   are unconfirmed.
2. 2026 pre-OBBBA 179 limit and phase-out: unknown. Check the 2026 Form 1 instructions when published.
3. 2021 and 2022 MA 179 figures: not seen in an MA document.
4. Whether MA's 2021 "Code as of 2005" rule would change any 179 figure: the excerpts say 179 follows the current Code,
   which is why 2021 carries the federal amounts, but this is unconfirmed.
5. Corporate excise: the excerpts describe the same 168(k) decoupling; no difference for entities found, not studied.

### Citations (all search excerpts)

- TIR 03-25: https://www.mass.gov/technical-information-release/tir-03-25-depreciable-business-assets-modifications-for-decoupling-from-federal-bonus-depreciation
- TIR 18-14: https://www.mass.gov/technical-information-release/tir-18-14-impact-of-selected-provisions-of-the-federal-tax-cuts-and-jobs-act-on-massachusetts-personal-income-tax-under-chapter-62
- TIR 23-1: https://www.mass.gov/technical-information-release/tir-23-1-tax-provisions-in-the-fiscal-year-2023-budget-including-massachusetts-personal-income-tax-code-update
- TIR 24-14: https://www.mass.gov/technical-information-release/tir-24-14-tax-provisions-in-the-fiscal-year-2025-budget
- TIR 26-4: https://www.mass.gov/technical-information-release/tir-26-4-massachusetts-conformity-to-certain-provisions-in-public-law-no-119-21
- Working Draft TIR (FY26 supplemental): https://www.mass.gov/technical-information-release/working-draft-tir-tax-provisions-in-the-fiscal-year-2026-final-mid-year-supplemental-appropriation-bill
- Form 1 instructions: https://www.mass.gov/doc/2023-form-1-instructions/download ; https://www.mass.gov/doc/2024-form-1-instructions/download ; https://www.mass.gov/doc/2025-form-1-instructions/download
- G.L. c.62 s.1(c): https://malegislature.gov/Laws/GeneralLaws/PartI/TitleIX/Chapter62/Section1 (excerpt)
- Acts of 2026 ch. 101: https://malegislature.gov/Laws/SessionLaws/Acts/2026/Chapter101 (listed only, not read)

## Michigan (MI)

Status: verify. All six rows verified=false (agency and legislature excerpts only).

### Rule in plain terms

- Income tax: yes (Income Tax Act, MCL 206). Starting point is federal AGI.
- Two different regimes, do not mix them up. The Corporate Income Tax is decoupled from 168(k): bonus is added back and
  the base is "computed as though section 168(k) is not in effect" (Treasury CIT FAQ Corporate Tax Base 2, 6 and 16,
  https://www.michigan.gov/taxes/questions/cit/corporate/corporate-tax-base-2--the-cit-is-decoupled-from-federal-bonus-depreciation--consequently-taxpayers-).
  That applies to corporations under the CIT. A sole proprietor, rental owner or pass-through owner files under the
  individual income tax.
- 2021-2024, individuals: federal bonus (100/100/80/60%) and the federal 179 limit flow through federal AGI. I found no
  Michigan add-back line for the individual return. This is an inference from absence, not a Treasury statement, hence
  verified=false and conformity_type "unknown" (the MCL 206.4 Code-date wording for these years was not read).
- 2025 onward: Public Act 24 of 2025 (House Bill 4961), signed 7 Oct 2025, decouples individuals, flow-through entities
  and corporations from several P.L. 119-21 changes for tax years beginning after 31 Dec 2024. Treasury notice
  "Decoupling Michigan Income Taxes from Certain Internal Revenue Code Provisions", 25 Feb 2026:
  https://www.michigan.gov/treasury/reference/taxpayer-notices/2026/02/25/decoupling-michigan-income-taxes-from-certain-internal-revenue-code-provisions
  - Bonus 168(k), individual income tax and the flow-through entity tax: "doesn't fully decouple"; 168(k) applies as in
    effect on 31 Dec 2024 (pre-OBBBA). 2025 is therefore 40%, and 2026 would be 20% (my derivation from the pre-OBBBA
    schedule, not printed in the excerpt). The taxpayer reports an addition equal to the federal depreciation deduction
    minus the depreciation allowed under pre-OBBBA 168(k), including regular depreciation. Treasury's example: a 10,000
    asset deducted 100% federally; Michigan allows 4,000 bonus plus 600 MACRS, so the addition is 5,400.
  - Section 179: computed as in effect on 31 Dec 2024, so the 2025 maximum is 1,250,000 and the phase-out 3,130,000, not
    2,500,000 / 4,000,000. Treasury's example: 2,000,000 of property and a 2,000,000 federal 179 deduction gives an
    addition of 675,000 (the excerpt does not explain why this is less than the 750,000 excess; read the notice).
  - 168(n): AGI and FTI are computed as if 168(n) were not in effect, with adjustment to the federally determined figure.
  - MCL 206.30(1)(ee), per a statute excerpt: 163(j), 168(k), 174 and 179 apply as in effect on 31 Dec 2024 for tax years
    2025-2028. That is the source for treating 2026 the same way; the end date 2028 is from the excerpt only.
- Conformity type: MCL 206.4, per a chapter-206 excerpt, defines the Internal Revenue Code as the code in effect on
  1 Jan 2025 or, at the taxpayer's option, in effect for the tax year. That reads as rolling with a taxpayer option, then
  overridden for the named provisions by PA 24. Read for 2025 only.

### Open items

1. Read the Treasury notice, MCL 206.4 and MCL 206.30(1)(ee) in full. Whether the 2028 end date is in the statute text.
2. The 2026 pre-OBBBA 179 limit and phase-out (null in the row). Do not substitute 2,560,000 / 4,090,000.
3. How the disallowed excess recovers in later years (Michigan basis versus federal basis): not read.
4. The 675,000 versus 750,000 mismatch in Treasury's 179 example.
5. Pre-2025 individual treatment: confirm from the 2021-2024 MI-1040 Schedule 1 instructions that no bonus add-back exists.
6. Michigan city income taxes (Detroit and others) are not covered.

### Citations (search excerpts)

- Treasury notice 25 Feb 2026: URL above.
- MCL 206.30: https://legislature.mi.gov/Laws/MCL?objectName=MCL-206-30
- MCL chapter 206 (206.4 definition): https://capitol.legislature.mi.gov/documents/mcl/pdf/mcl-chap206.pdf
- Senate Fiscal Agency analysis of HB 4961: https://legislature.mi.gov/documents/2025-2026/billanalysis/Senate/pdf/2025-SFA-4961-G.pdf
- CIT FAQ: URL above.

## Minnesota (MN)

Status: confirmed for the bonus mechanics (statute text and the Department's own analysis were read); the federal 179
dollar amounts are copied from the federal note (status verify), so the row notes say so. All six rows verified=true.

### Rule in plain terms

- Income tax: yes (individual income tax, Minn. Stat. ch. 290).
- Bonus, IRC 168(k), all six years: Minnesota is partial. "80 percent of the depreciation deduction allowed under section
  168(k) of the Internal Revenue Code is an addition" (290.0131 subd. 9;
  https://www.revisor.mn.gov/statutes/2022/cite/290.0131, fetched 2026-10-06). In each of the next five tax years, "an
  amount equal to one-fifth of the delayed depreciation is a subtraction" (290.0132 subd. 9;
  https://www.revisor.mn.gov/statutes/2022/cite/290.0132). Delayed depreciation is the addition minus the positive value of
  any NOL generated in the year of the addition, and cannot be below zero. Worked out: 20% of the federal bonus deduction is
  kept in year 1, and 16% of it is subtracted in each of the following five years (my arithmetic on the statute).
  S corporation shareholders and corporations use the parallel sections 290.0133 subd. 11 and 12.
- A rule in subd. 9 limits the 168(k) deduction where the same activity has an unallowed loss (my reading of a fetch
  summary; read the statute text before building it).
- Section 179: Minnesota conforms to the federal limit and phase-out for property placed in service after 31 Dec 2019. The
  addition in 290.0131 subd. 10 is limited to "property placed in service before January 1, 2020": 80% of the amount by which
  the deduction allowed under the dollar limits of 179 exceeds the deduction allowable under 179 as amended through
  31 Dec 2003 (that is the old 25,000 / 200,000 limits), with one-fifth subtractions for five years under 290.0132 subd. 14.
  A calculator must still apply those subtractions on 2021-2024 returns for 2016-2019 property. A search excerpt said
  Minnesota "limits section 179 to 25,000", which is the pre-2020 rule and is wrong for 2020 onward; a second excerpt
  (DOR "Section 179 Expensing Addition" page, not fetchable) said the addition is not required for property placed in service
  after 31 Dec 2019. The 2019 "Section 179 Full Conformity" federal update is cited at
  https://www.revenue.state.mn.us/sites/default/files/2019-02/hf0235(sf0575)_1.pdf (search result only).
- Conformity type: fixed. 290.01 subd. 31: Code "as amended through December 31, 2018" (2021 and 2022 editions, with the
  290.0111 items), "as amended through May 1, 2023" (2023 and 2024 editions; the 2023 conformity act may affect tax years
  2017-2022 for specified federal changes), and "as amended through May 1, 2026" (Laws 2026 ch. 128).
  Federal 179 and bonus rates follow the Code at those dates, and the statutory 179 indexation is inside the Code, so the
  federal annual amounts apply.

### 2025 and 2026, after P.L. 119-21 (two layers)

- Before Laws 2026 ch. 128 the Minnesota IRC date was 1 May 2023, so OBBBA was not Minnesota law for TY2025. A Dec 2025
  DOR revenue estimate ("Revised for November 2025 Forecast, Federal Update: Public Law 119-21") says it assumes "an 80%
  addition and corresponding subtractions over five years" for bonus and "full conformity, consistent with current law" for
  179. Read from https://www.revenue.state.mn.us/sites/default/files/2025-12/federal-update-pl-119-21-5.pdf.
- Enacted: Session Laws 2026 chapter 128 (H.F. 2438), DOR analysis dated 26 May 2026
  (https://www.revenue.state.mn.us/sites/default/files/2026-05/hf2438sf2082-enacted-otb.pdf, read in full). Quotes:
  "The bill updates references to the Internal Revenue Code to May 1, 2026, adopting the provisions of P.L. 119-21 with
  certain modifications." Bonus: "Effective beginning with tax year 2025." "The bill conforms to the extension of bonus
  depreciation in P.L. 119-21, requiring an 80% addition for property defined in Section 168(k) of the Internal Revenue Code.
  The addition does not apply to qualified production property." Retroactive effect language, from ch. 128 secs. 1-3, 30 on
  revisor.mn.gov: "the changes incorporated by federal changes are effective retroactively at the same time the changes were
  effective for federal purposes."
- Therefore: 168(n) is not decoupled (decouples_168n false): qualified production property takes the full federal allowance
  with no Minnesota addition. 168(k) property: 80% addition, five-year subtraction, for 2025 and 2026. 179: the fiscal table's
  line "Increased dollar limitation for Section 179 expensing (beginning TY25)" is not shaded as decoupled, so the OBBBA
  limits apply (2,500,000 / 4,000,000 for 2025; 2,560,000 / 4,090,000 for 2026, from the federal note).
- Domestic research (174A) additions apply to C corporations only, not individuals.
- A search excerpt of a DOR page titled "2025 Federal Nonconformity for Income Tax" said Minnesota had not conformed to
  H.R. 1. That predates ch. 128 and is superseded; the page itself could not be fetched.

### Open items

1. The text of ch. 128 sections amending 290.0131 subd. 9 and 10 was not visible in the fetch excerpt. The bonus and QPP
   statements come from the Department's analysis, which is the agency's own statement, not the session-law text.
2. The 179 dollar amounts for 2025 and 2026 are the federal ones. No Minnesota document read names them.
3. Whether the 2025-2026 enacted ch. 128 text keeps the subd. 9 loss limitation unchanged.
4. Minnesota's pass-through entity tax (re-enacted through TY2027) and Schedule M1M line numbers are not covered.
5. The 2021 and 2022 statute editions were read; the 2021-2022 IRC-date retroactive updates by the 2023 act were not
   examined line by line.

### Citations

- https://www.revisor.mn.gov/statutes/2022/cite/290.0131 (subd. 9, 10); https://www.revisor.mn.gov/statutes/2022/cite/290.0132 (subd. 9, 14)
- https://www.revisor.mn.gov/statutes/2021/cite/290.01 ; .../2022/... ; .../2023/... ; .../2024/... (subd. 31)
- https://www.revisor.mn.gov/laws/2026/0/128/ (Laws 2026 ch. 128; IRC date and effective-date language)
- https://www.revenue.state.mn.us/sites/default/files/2026-05/hf2438sf2082-enacted-otb.pdf (DOR analysis, 26 May 2026)
- https://www.revenue.state.mn.us/sites/default/files/2025-12/federal-update-pl-119-21-5.pdf (DOR estimate, 15 Dec 2025)

## Mississippi (MS)

Status: verify for 2021, 2022, 2025, 2026 (verified=false); 2023 and 2024 verified=true on the agency's Income Tax Notice
80-23-003, which was read in full. The statute text (Miss. Code Ann. 27-7-17) was not read.

### Rule in plain terms

- Income tax: yes. Individuals are taxed on the Mississippi return from federal-schedule figures plus adjustments
  (Schedule N). Pass-through entities and S corporations pass income to owners; a sole proprietor reports on Schedule C.
- 2021 and 2022: no bonus. Mississippi does not allow the federal special depreciation allowance. The Mississippi
  Form 4562 "will compute ... depreciation deduction without taking into account any special depreciation allowance
  (generally line 14 of Federal Form 4562)". The difference is an addition, and "additional depreciation expense for
  purposes of this state due to the basis adjustment not being made" is a deduction (2021 corporate booklet, Form 83-122
  lines 6 and 13, p. 16, https://www.dor.ms.gov/sites/default/files/tax-forms/business/83100218.pdf). For an individual,
  the 2022 booklet (p. 10 and 16, https://www.dor.ms.gov/sites/default/files/tax-forms/individual/80100221.pdf) says the
  difference is recorded on Schedule N, "e.g., bonus depreciation adjustment - Schedule C-1", or by an attached
  reconciliation. So Mississippi bonus is 0% for 2021-2022 and the full basis is depreciated.
- 2021 section 179: the corporate booklet says "Section 179 expensing amounts increased from $500,000 to $1,000,000" under
  the TCJA changes Mississippi follows. The phase-out and any indexing are not stated; the federal indexed 2021 figures
  would be 1,050,000 / 2,620,000. The rows carry 1,000,000 and a null phase-out.
- HB 1356 (2021 session) amended 27-7-17: for aircraft, equipment, engines and other aviation parts and tools, bonus
  depreciation conforms to the federal rates and the reasonable allowance is no less than 100% (2021 corporate booklet,
  What's New, p. 3). No effective date was stated in the excerpt.
- 2023 onward, state 100% bonus: Income Tax Notice 80-23-003 (20 Oct 2023;
  https://www.dor.ms.gov/sites/default/files/news/Depreciation%20Notice%20Draft%2010-20-23.pdf, read in full):
  "For tax years beginning after December 31, 2022, expenditures for business assets that are qualified property or
  qualified improvement property shall be eligible for one hundred percent (100%) bonus depreciation and may be deducted as
  an expense incurred by the taxpayer during the tax year in which the property was placed in service." "Qualified property"
  means 26 USC 168(k), and "qualified improvement property" means 168(e)(6), each "as it existed on January 1, 2021".
  A taxpayer "may elect to take a bonus depreciation deduction ... and/or to depreciate the expenditures in accordance with
  26 USCS Section 168". The election is by the return due date including extensions and "is irrevocable unless a change in
  method is allowed by the Commissioner". "The total of any depreciation method or combination of methods used cannot
  exceed one hundred percent (100%) of the cost". "None of the provisions mentioned above shall nullify or otherwise alter
  the treatment of depreciation expenses for any tax year prior to 2023."
  This is a state rate, not a federal pass-through. It is 100% for 2023 (federal 80%), 2024 (federal 60%) and 2025
  regardless of the 19 Jan 2025 acquisition split. HB 1733 (signed 27 Mar 2023) is the enacting law.
- Section 179, 2023 onward: "A taxpayer may also elect to treat the cost of any Section 179 property ... as an expense ...
  Mississippi's treatment of the deduction shall conform to the provisions of 26 USCS Section 179 in effect for that year."
  That is rolling for 179. Amounts used: the federal limits for each year (2023 1,160,000 / 2,890,000; 2024
  1,220,000 / 3,050,000; 2025 2,500,000 / 4,000,000; 2026 2,560,000 / 4,090,000), which are inferences from "in effect
  for that year", not Mississippi-printed numbers.
- Conformity type: selective. The 168(k) and 168(e)(6) definitions are frozen at 1 Jan 2021; 179 is rolling.

### 2025 and 2026, after P.L. 119-21

- The 2025 Pass-Through Entity instructions (Form 84-100-22, Rev. 01/26, November 2025;
  https://www.dor.ms.gov/sites/default/files/tax-forms/business/2025%20PTE%20INSTRUCTIONS%2084-100%20-%20Final%20%2001.14.2026.pdf,
  read in full), Form 84-122 line 8: the Mississippi Form 4562 "will compute the apportionable and/or allocable depreciation
  deduction according to Mississippi statutes in effect in the year the business assets were placed in service.
  Expenditures for business assets placed in service after December 31, 2022, are eligible for 100% bonus depreciation."
  Its New Legislation section lists no depreciation change, and the DOR 2025 legislation page (HB 1 is income tax rate only)
  lists none. No Mississippi response to P.L. 119-21 was found for 2025.
- 168(n) qualified production property: no source read addresses it. It is not "qualified property" under 168(k) as it
  existed on 1 Jan 2021, so the 100% state rule does not name it. decouples_168n is null.
- 2026: no booklet, notice or session law was read. A search surfaced SB 3163 (2026 Regular Session, topic unknown), and
  billstatus.ls.state.ms.us failed TLS so it could not be opened.
- The notice's last sentence, "These provisions shall remain in effect unless there are any changes to the federal Internal
  Revenue Code sections mentioned above", is ambiguous for 2025 now that OBBBA changed 168(k) and 179. The 2025 booklet
  still applies the 100% rule, which is the best evidence read.

### Open items

1. Read Miss. Code Ann. 27-7-17 as amended by HB 1733 (and any 2024-2026 amendment) from an official host that works.
2. Whether a 2026 session law changed depreciation, 179 or federal conformity (SB 3163 topic unknown).
3. 168(n) treatment: unknown. Confirm with DOR before applying any rule.
4. How an individual elects the 100% bonus: the notice names the corporate (83-122) and pass-through (84-122) check boxes;
   the individual route (Schedule N / C-1) was only seen for the pre-2023 adjustment.
5. 2021-2022 individual-specific text: 179 amount, whether indexed, and the phase-out.
6. Whether "in effect for that year" gives 2,500,000 / 4,000,000 for 2025, and the 2026 figures.
7. The 2025 individual booklet was fetched (2.4 MB) but not read.

### Citations

- Notice 80-23-003: https://www.dor.ms.gov/news/depreciation-notice and the PDF above (read in full).
- 2021 corporate booklet: https://www.dor.ms.gov/sites/default/files/tax-forms/business/83100218.pdf (read in full).
- 2022 individual booklet: https://www.dor.ms.gov/sites/default/files/tax-forms/individual/80100221.pdf (read in full).
- 2025 PTE booklet: URL above (read in full). 2025 Form 83-122: https://www.dor.ms.gov/sites/default/files/tax-forms/business/83122258.pdf (form only: line 6 "Federal special depreciation allowance", line 13, the two election check boxes).
- DOR 2025 legislation page: https://www.dor.ms.gov/forms-resources/laws-regulations/2025-legislation

## Missouri (MO)

Status: verify. All six rows verified=false. The primary text read is the General Assembly's own bill text reproducing
RSMo 143.121; no Department of Revenue instruction or codified-statute page could be fetched, and nothing was read that
post-dates P.L. 119-21 except agency search excerpts.

### Rule in plain terms

- Income tax: yes (individual income tax, RSMo ch. 143). The Missouri adjusted gross income of a resident individual "shall
  be the taxpayer's federal adjusted gross income subject to the modifications in this section" (143.121.1).
- Bonus, IRC 168(k), all six years: Missouri follows the federal bonus. The only modification for IRC 168 in 143.121 is
  for property "purchased on or after July 1, 2002, but before July 1, 2003" (the 30% allowance of the Job Creation and
  Worker Assistance Act of 2002): 143.121.2(3) adds back the excess over IRC 168 "as in effect on January 1, 2002",
  143.121.3(7) subtracts the shortfall in later years, and 143.121.3(9) subtracts on a sale any addition not yet recovered.
  There is no add-back for any later bonus, so Missouri depreciation equals federal depreciation, there is no separate
  Missouri basis, and the federal rate applies: 100% (2021, 2022), 80% (2023), 60% (2024), 2025 100% for property
  acquired after 19 Jan 2025 and 40% before, 2026 100% (rates from the federal note, not restated by Missouri).
  Source: https://documents.house.mo.gov/billtracking/bills251/hlrbillspdf/1683H.02P.pdf (HCS HBs 594 & 508, perfected,
  1st Regular Session, 103rd G.A.; the unbolded text is existing law; read in full 2026-10-06 via the Read tool on the saved
  PDF).
- Section 179: no Missouri modification exists in 143.121 (read in full: subsections 2 and 3 list every addition and
  subtraction), so the federal 179 deduction on the federal return flows through. Amounts are the federal ones from the
  federal note: 2021 1,050,000 / 2,620,000; 2022 1,080,000 / 2,700,000; 2023 1,160,000 / 2,890,000; 2024 1,220,000 /
  3,050,000; 2025 2,500,000 / 4,000,000 (P.L. 119-21 s.70306); 2026 2,560,000 / 4,090,000 (Rev. Proc. 2025-32). They are
  applied because Missouri has no 179 modification, not because a Missouri document prints them.
- Conformity type: rolling. The statute starts from federal AGI and cites the Code "as amended" (for example 143.121.2(2),
  2(4), 2(6)). The sole fixed-date reference is the 1 Jan 2002 comparison for the 2002-2003 property rule.
  This is my reading of the statute's structure; no Missouri document read states "rolling conformity" in those words
  (a search-engine summary and a third-party chart said so; those are leads only).
- Entities: the 2025 MO-1120 instructions excerpt shows the same 2002-2003 line (line 8, 143.121.3(7)); no corporate
  difference found. 143.431 (corporations) was not read.

### 2025 and 2026, after P.L. 119-21

- No Missouri statute or Department notice decoupling from P.L. 119-21 depreciation was found. Because Missouri is
  rolling and has no 168(k), 168(n) or 179 modification, the 100% bonus, the OBBBA 179 limits and 168(n) qualified production
  property reach Missouri through federal AGI. decouples_168n is therefore false, as an inference from the absence of a
  modification.
- Missouri changes found for 2025 and later that are not depreciation: 100% subtraction of "all income reported as a capital
  gain for federal income tax purposes" for tax years beginning on or after 1 Jan 2025 (143.121.3(14), from HB 594; DOR news
  release excerpt agrees); elimination of the federal income tax deduction from tax year 2026 (search excerpt of a DOR
  page, not read).
- DOR excerpts say the OBBBA tips, overtime, car-loan-interest and senior deductions are not available on the Missouri
  return, because they are federal below-AGI deductions with no Missouri counterpart. That does not touch depreciation.
- 2026 regular session: bills touching 143.121 exist (HB 2975 repeals 143.011, 143.021 and 143.121 with a referendum clause;
  SB 994; HB 1754), and a truly agreed 2026 joint resolution (LR 6854). I could not read the Senate ones and did not read
  the others. Whether any enacted bill changed depreciation is unknown.

### Special rules a depreciation calculator must apply

1. 2002-2003 property rule (above). For personal property of 20 years or less it will be fully recovered, but a disposal
   still triggers 143.121.3(9). The residential rental and nonresidential real property classes were not eligible for the
   federal bonus, so no effect on them (my reasoning).
2. Missouri NOL (143.121.2(4)): the federal NOL deduction is added back to the extent it is carried forward more than
   twenty years or backward more than two years (excluding 172(b)(1)(G) and 172(i)); Missouri allows the disallowed amount
   for up to twenty years. A loss created by 100% bonus or 179 is therefore carried on a separate Missouri schedule (Form
   MO-5090 is the Department's "New Operating Loss Addition Modification Sheet"; not read). My reading.
3. 163(j) (143.121.2(6) and 3(11), tax years from 2018): interest not deducted because of 163(j) is subtracted in the year
   it is disallowed and added back in the year it is later deducted federally, so Missouri does not apply the 163(j) cap.
   The 163(j) depreciation-in-ATI rules therefore do not matter for Missouri AGI.
4. Capital gain subtraction (2025 on): applies to income "reported as a capital gain for federal income tax purposes".
   Section 1245 and unrecaptured 1250 recapture are ordinary or special-rate income, so applying the subtraction to the
   sale of depreciated property needs the Department's view; see open item 3.

### Open items

1. Read RSMo 143.121 on revisor.mo.gov (refused) or DOR's 2025 and 2026 instructions (403) to confirm the current text and
   that no 2025-2026 amendment added a depreciation, 168(n) or 179 modification. The bill text read predates P.L. 119-21.
2. Whether any 2026-session bill that was truly agreed and finally passed touches depreciation, 179 or Code conformity.
3. Whether net 1231 gain and 1245 recapture are covered by the 2025 capital gain subtraction.
4. Earlier versions of 143.121 for 2021-2024 (the rows apply the 2025 text to those years).
5. Missouri 143.431 (corporations) and the 12 CSR 10-2 rules on depreciation were not read.
6. The DOR's Form MO-A depreciation line number: a search summary said line 14, not confirmed.

### Citations

- RSMo 143.121 as reproduced in HCS HBs 594 & 508 (perfected): https://documents.house.mo.gov/billtracking/bills251/hlrbillspdf/1683H.02P.pdf
- DOR (search excerpts only; fetches 403): https://dor.mo.gov/forms/MO-1040%20Instructions_2025.pdf ; https://dor.mo.gov/forms/MO-1120%20Instructions_2025.pdf ; https://dor.mo.gov/business/corporate/depreciation/ ; https://dor.mo.gov/taxation/individual/tax-types/income/year-changes/ ; https://dor.mo.gov/news/newsitem/uuid/15044650-59dd-48f4-975a-01988d485255
- 2026 session leads, not read: https://documents.house.mo.gov/billtracking/bills261/hlrbillspdf/6241H.03I.pdf (HB 2975); https://www.senate.mo.gov/26info/pdf-bill/perf/SB994.pdf
