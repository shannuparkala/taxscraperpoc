---
topic: State depreciation conformity, batch 9 (VA, WA, WV, WI, WY), personal income tax, tax years 2021-2026
tax_years: 2021, 2022, 2023, 2024, 2025, 2026
figures_as_of: 2026-10-07
figures_source_url: per-state URLs below (state agency hosts and state legislature / statute sites)
status: verify
progress: COMPLETE. VA, WA, WV, WI, WY done (6 rows each, 30 in the JSON). verified=false rows: VA 2022 and 2026, WV 2025 and 2026, WI 2026, WY 2026.
---

# State depreciation conformity, batch 9 (VA, WA, WV, WI, WY)

Recorded 2026-10-07. Enacted law only. Scope is the personal income tax as it applies to a sole proprietor,
pass-through owner or rental owner. Federal reference figures (carried as inherited where a state conforms) come
from `docs/tax-research/depreciation-macrs-179-bonus-280f-2021-2026.md` and the same table as batch 8:

| Tax year | Federal bonus 168(k) | 179 limit | 179 phase-out start |
|---|---|---|---|
| 2021 | 100% | 1,050,000 | 2,620,000 |
| 2022 | 100% | 1,080,000 | 2,700,000 |
| 2023 | 80% | 1,160,000 | 2,890,000 |
| 2024 | 60% | 1,220,000 | 3,050,000 |
| 2025 | 100% acquired after 19 Jan 2025; 40% earlier (P.L. 119-21 s.70301 over Rev. Proc. 2024-40) | 2,500,000 (OBBBA s.70306; RP 2024-40 said 1,250,000) | 4,000,000 (RP 2024-40 said 3,130,000) |
| 2026 | 100% | 2,560,000 | 4,090,000 |

## How this is researched

- `ALLOWLIST_DOMAINS` in `tax_research_crawler.py` no longer exists (deleted in the 2026-10-05 rebuild). Agency hosts
  come from `backend/app/services/assistant/state_registry.py`: VA tax.virginia.gov, WA dor.wa.gov, WV tax.wv.gov,
  WI revenue.wi.gov, WY revenue.wyo.gov. Statute and legislature sites used where named (law.lis.virginia.gov,
  app.leg.wa.gov, wvlegislature.gov bill pages, wyoleg.gov).
- No Bash tool this session. WebFetch cannot parse most agency PDFs; Read on a saved PDF works but renders every page
  (a 56-page booklet or 94-slide deck is expensive; two-page forms are cheap). `code.wvlegislature.gov` and
  `bills.wvlegislature.gov` redirected every request to an unrelated FBI page, so the West Virginia Code itself was
  not read (bill text on www.wvlegislature.gov was). `docs.legis.wisconsin.gov` refused connections. `www.revenue.wi.gov`
  failed DNS over https but loads over http.
- `verified` is true only when the key cells (bonus, conformity, 179) were read from statute or agency text for that
  year. Federal 179 dollar figures for a conforming state are inherited and say so.

## Summary matrix

| State | Individual income tax | Bonus | 179 | Entity-level note |
|---|---|---|---|---|
| VA | yes | none, all years: recompute without bonus, add back / subtract difference (no spread) | follows federal 2021-2024; decoupled from OBBBA increase 2025+ (2025: 1,250,000 / 3,130,000 inferred; 2026 unknown) | PTET election permanent (2026) |
| WA | none (9.9% on AGI over 1M from 2028 only) | n/a | n/a | B&O gross receipts, no depreciation deduction; capital gains excise tax exempts depreciable business assets |
| WV | yes | follows federal, no Schedule M line, 2021-2024; 2025 pre-OBBBA 40% (unverified reading); 2026 OBBBA 100% | follows federal; 2025 pre-OBBBA 1,250,000; 2026 2,560,000 | corporate side not researched |
| WI | yes | none, all years: Wisconsin-only depreciation, Schedule I addback and later adjustments | follows federal limits for the year placed in service, incl. OBBBA 2,500,000 / 4,000,000 for 2025 | 168(n) not adopted |
| WY | none | n/a | n/a | no corporate income tax either |

## Virginia (VA)

**Tax year 2021-2026, personal income tax, enacted law (as of 2026-10-07).**

- **Bonus (all years): none.** Va. Code 58.1-301 B excludes "the special depreciation allowance for certain property
  provided for under 168(k), 168(l), 168(m), 168(n), 1400L, and 1400N"
  (https://law.lis.virginia.gov/vacode/title58.1/chapter3/section58.1-301/, read 2026-10-07). Department: "Virginia
  tax law doesn't recognize this bonus depreciation... recalculate depreciation on these assets to determine the
  amount of your Virginia deduction. If your Virginia deduction is less than your federal deduction, you'll add back
  the difference" (https://www.tax.virginia.gov/additions). Tax Bulletin 16-1 adds the reverse: if the Virginia
  calculation is greater than the federal, the difference is a subtraction. There is no spread: the whole
  difference is added in the year of the claim and recovered through normal depreciation on the Virginia basis.
  The 100% federal bonus restored by OBBBA does not flow through; Tax Bulletin 26-1 lists bonus among the
  "existing exceptions ... for Taxable Year 2025 and thereafter".
- **Conformity type by year.** 2021: fixed 2021-12-31 (Tax Bulletin 22-1,
  https://www.tax.virginia.gov/laws-rules-decisions/tax-bulletins/22-1). 2022: fixed 2022-12-31 (Tax Bulletin 23-1;
  PDF unreadable, date from a search summary, so the 2022 row is verified=false). 2023-2024: rolling
  (HB 2193 / SB 1405, taxable years beginning on and after 2023-01-01), but Virginia deconforms from federal changes
  enacted after 2023-01-01 that move General Fund revenue by more than 15 million dollars (indexed from 2024)
  (https://www.tax.virginia.gov/laws-rules-decisions/legislative-summaries/23-65). 2025: the 2025 Appropriation Act
  (HB 1600, ch. 725) paused rolling conformity for amendments enacted 2025-01-01 to 2026-12-31; the 2026 Amendments
  (HB 29, ch. 7, effective 2026-02-20) then set a fixed date of 2025-12-31 and conformed to most of P.L. 119-21
  (Tax Bulletin 26-1, https://www.tax.virginia.gov/laws-rules-decisions/tax-bulletins/26-1). 2026: same statute,
  with automatic conformity only for extenders.
- **Section 179.** 2021-2024: conforms to the federal limit and phase-out (Tax Bulletin 16-1: the PATH Act
  permanent, indexed 179 "flows through to the Virginia individual income tax return"). Dollar figures are the
  federal ones above. **2025 onward: decoupled from P.L. 119-21 s.70306** (Va. Code 58.1-301 B item 12) "for Taxable
  Years 2025 and thereafter". Virginia uses the pre-OBBBA limit: "calculate depreciation ... as if the 2025 H.R. 1
  changes had not been enacted" (Bulletin 26-1). For 2025 that is 1,250,000 / 3,130,000 (Rev. Proc. 2024-40; inferred,
  not stated by Virginia). For 2026 the pre-OBBBA limit is unpublished, so null.
- **168(n) qualified production property:** excluded (statute list and the Department's 2026 Legislative Summary,
  https://www.tax.virginia.gov/sites/default/files/inline-files/2026-legislative-summary.pdf). Also deconformed:
  174A domestic research expensing.
- **Calculator rules:** keep a separate Virginia depreciation schedule and basis (gain or loss on sale uses the
  Virginia basis); the bonus recompute covers 168(k) and the older 168(l), (m), 1400L, 1400N allowances.
- **Open:** 2022 conformity date (Bulletin 23-1) and the 2025 Form 760 / Form 502 instructions would confirm the
  2025 dollar limit and the exact Schedule ADJ addition code; both are PDFs the fetch tool could not parse.

## Washington (WA)

**No individual income tax for 2021-2026; no depreciation adjustment exists.** WA DOR: "Washington does not currently
have an individual income tax." (https://dor.wa.gov/taxes-rates/income-tax, read 2026-10-07). Bonus is recorded as
"unknown" and conformity "n/a" because the enum has no n/a (same convention as batch 8).

- **B&O tax (entity level, any sole proprietor or pass-through):** a gross-receipts tax. "Because it is based on gross
  income, businesses cannot deduct expenses such as labor, materials, taxes, or other costs of doing business."
  (https://dor.wa.gov/taxes-rates/business-occupation-tax). Depreciation, bonus and 179 never enter it.
- **Capital gains excise tax (RCW 82.87, enacted 2021 by ESSB 5096, gains from 2022):** 7% on long-term capital
  gains from sale of stocks, bonds, business interests and other assets. It starts from federal net long-term capital
  gain "as of July 25, 2021, or such subsequent date as the department may provide by rule" (RCW 82.87.020). It
  exempts real estate and assets "depreciable under 26 U.S.C. Sec. 167(a)(1) ... or that qualif[y] for expensing
  under 26 U.S.C. Sec. 179" (RCW 82.87.050, https://app.leg.wa.gov/RCW/default.aspx?cite=82.87.050). So selling
  depreciated equipment or rental real estate creates no Washington tax and no Washington basis computation. Rate
  tiers and the 2025 standard deduction (278,000) are on the DOR page and are not depreciation inputs.
- **2025-2026:** no Washington response to P.L. 119-21 is needed. **ESSB 6346 (2026 c 238)** enacts a 9.9% income tax
  on individuals and joint filers with adjusted gross income above 1,000,000 dollars from 2028-01-01 (first returns
  April 2029); it does not reach 2026. Its treatment of federal depreciation was not researched (outside the window)
  and is an open item for a calculator that goes to 2028.
- **Open:** verify that no Washington B&O deduction has been added for equipment; none was found.

## West Virginia (WV)

**Tax year 2021-2026, personal income tax. Follows federal depreciation; the conformity window is what changes.**

- **Mechanics.** West Virginia starts from federal AGI ("The starting point for the West Virginia income tax return is
  your federal adjusted gross income", 2025 IT-140 instructions p.24,
  https://tax.wv.gov/Documents/PIT/2025/it140.PersonalIncomeTaxFormsAndInstructions.2025.pdf). I read Schedule M for
  every year 2021-2025 (2021 https://tax.wv.gov/Documents/TaxForms/2021/it140.schedule-M.pdf; 2022
  .../PIT/2022/it140.schedule-M.2022.pdf; 2023 .../PIT/2023/it140.schedule-M.2023.pdf; 2024
  .../PIT/2024/it140.schedule-M.2024.pdf; 2025 .../PIT/2025/it140.Schedule-M.2025.pdf). None has an addition or
  subtraction for depreciation, bonus or 179; the only business-related addback line is "Other income deducted from
  federal adjusted gross income but subject to state tax", illustrated with IRC 199. So federal 168(k) and 179 flow
  through for 2021-2024 (100%, 100%, 80%, 60% bonus; federal 179 limits in the table). Nonresident/part-year
  allocation "use the federal adjusted basis of your property in all computations" (2025 instructions p.31).
- **Conformity statute, W. Va. Code 11-21-9(a)** (read only through bill text; the Code site was unreachable). The
  2025 text (HB 2024, 2025 RS): amendments to US law "after December 31, 2023, but prior to January 1, 2025, shall be
  given effect... but no amendment to the laws of the United States made on or after January 1, 2025, may be given
  any effect", with prior years' law "fully preserved". That is a fixed date, re-set every year by the Legislature.
  The 2021-2024 dates in the JSON are inferred from this one-year-lag pattern and are not statute-verified; they do
  not change the answer because the TCJA/PATH Act 168(k)/179 rules predate all of them.
- **2025: unresolved.** Under the 2025 text, P.L. 119-21 (4 July 2025) is after the 2024-12-31 window, so West
  Virginia bonus for 2025 would be the pre-OBBBA 40% and 179 would be 1,250,000 / 3,130,000. SB 400 (2026 RS, Chapter
  279, approved 2026-03-02, effective 2026-02-23) moved the window to "after December 31, 2024, but prior to January
  1, 2026" and says amendments enacted in 2026 are retroactive "to the extent allowable under federal income tax
  law" while "taxable years that began prior to January 1, 2026" keep the law in effect for each year "except as
  provided in this section". I read that as leaving 2025 on the old window, but no Tax Division text confirms it, so
  the 2025 row is verified=false. Sources: https://www.wvlegislature.gov/bill_status/bills_text.cfm?billdoc=hb2024+enr.htm&yr=2025&sesstype=RS&i=2024
  and https://www.wvlegislature.gov/Bill_Text_HTML/2026_SESSIONS/RS/bills/sb400%20sub1.pdf.
- **2026:** SB 400 gives effect to federal amendments through 2025-12-31, so OBBBA (100% bonus after 2025-01-19,
  179 at 2,560,000 / 4,090,000, 168(n)) applies. No depreciation exclusion appears in the bill; no 2026 forms yet, so
  verified=false.
- **Calculator rules:** no West Virginia depreciation schedule needed for 2021-2024; for 2025 flag for review (two
  possible answers); for 2026 follow federal. WV is a one-year-lag fixed-date state, so a post-2026 federal change
  needs a new West Virginia bill.
- **Open:** the Tax Division's own statement on 2025 treatment of OBBBA; the 2026 Schedule M; the West Virginia
  Code text of 11-21-9 for 2021-2024.

## Wisconsin (WI)

**Tax year 2021-2026, personal income tax. No bonus in any year; 179 follows federal law for the year the property is
placed in service, so OBBBA's larger 179 applies from 2025.**

- **Bonus: none.** WI DOR, Section 179 and Depreciation Adjustments (http://www.revenue.wi.gov/Pages/FAQS/ise-crpsec179.aspx,
  page dated 2026-01-06, read 2026-10-07): "bonus depreciation is not allowed for Wisconsin purposes". For
  2025 the agency's own deck states: "Wisconsin computes depreciation and amortization using IRC in effect on January 1,
  2014, with certain exceptions", "Wisconsin has not adopted federal bonus depreciation provisions" and "has not
  adopted provisions in the federal One Big Beautiful Bill (OBBB)" (Wisconsin Tax Update - Fall 2025, R. 11/03/2025,
  slide 15, https://www.revenue.wi.gov/Documents/2025-Tax-Update-One-Slide.pdf). Mechanics (Schedule I instructions,
  as relayed in search summaries for 2021-2025): recompute depreciation on the Wisconsin basis; the difference
  between federal depreciation with bonus and Wisconsin depreciation is a Schedule I addition for the year claimed,
  with another Schedule I adjustment each year until the asset is fully depreciated for both. No spread; it is a
  full-difference addback that reverses over the asset's life.
- **Conformity type.** Fixed IRC date with automatic-follow exceptions, so "selective" for 2025-2026 and "fixed"
  before: 2021 and 2022 returns use the IRC enacted as of 2020-12-31; 2023, 2024 and 2025 use 2022-12-31 (agency
  instructions per search summaries; slide 15 for 2025). 2026: no change found.
- **Section 179.** "Wisconsin follows the same maximum dollar and business income limitations allowed for federal tax
  purposes", and the Wisconsin 179 election may differ from the federal election (Wisconsin-only Form 4562 marked
  "Revised for Wisconsin"; disallowed 179 carries forward). The deck (slides 16, 18) lists "IRC 179, 179A, 179B,
  179C, 179D, and 179E ... WI follows federal law in effect for federal purposes for the year in which the property
  is placed in service" and "IRC 179 - the OBBB increased the expense limit to $2.5 million (up from $1 million) and
  the phaseout threshold to $4 million (up from $2.5 million), and adopts future annual adjustments for inflation".
  So Wisconsin 2025 = 2,500,000 / 4,000,000, unlike Virginia and (for 2025) West Virginia. 2026 carries the federal
  2,560,000 / 4,090,000 by the same rule (verified=false: no Wisconsin-published 2026 amount).
- **168(n):** "Wisconsin has not adopted" it for 2025 (slide 24), along with 163(j), 174/174A/41/280C and 460(e) items.
- **Calculator rules:** run a Wisconsin-only depreciation schedule (IRC as of 2014-01-01, no bonus); keep a separate
  Wisconsin basis for gain or loss on disposition; 179 may be elected differently for Wisconsin and can substitute for
  the missing bonus. 2025 Act 15 (rate change, retirement subtraction, film credits) does not affect depreciation.
- **Open:** a Wisconsin 2026 conformity act (the Legislative Fiscal Bureau priced adopting 100% bonus at 585 million
  dollars for 2025-26 in October 2025, https://docs.legis.wisconsin.gov/misc/lfb/misc/208_federal_tax_law_changes_enacted_in_p_l_119_21_the_one_big_beautiful_bill_act_of_2025_that_could_be_considered_to_modify_state_tax_liability_10_8_2025.pdf,
  but no enactment was found); the 2021-2024 Schedule I instruction PDFs were not opened.

## Wyoming (WY)

**No individual or corporate income tax in 2021-2026 on the evidence read; no depreciation adjustment.** The Wyoming
Legislature's Legislative Service Office deck "Wyoming Statutory Tax Structure: Title 39" (3 June 2025) tabulates
"Individual Income Tax 0% (Note Art. 15, Sec. 18)" and "Corporate Income Tax 0%", each with FY24 collections of $0
(slide 9, https://wyoleg.gov/InterimCommittee/2025/03-202506032-01WyomingtaxstructureratesandcollectionsJune32025.pdf).
The 1999 Tax Reform 2000 Committee report states "Wyoming does not have a state individual or corporate income tax"
(https://wyoleg.gov/InterimCommittee/2020/03-2020052615-01TaxReform2000ExecSummary.pdf). The state's taxes are
property, severance, sales/use (4% statewide), fuel and excise; none start from federal taxable income. The Wyoming
Department of Revenue's own pages (revenue.wyo.gov divisions and FAQs) list Excise, Mineral, Property, Liquor and
Administrative divisions but make no express "no income tax" statement, so the statement rests on the legislature's
document. 2026 is verified=false: a search of wyoleg.gov found no income-tax enactment but no 2026 enacted-law
document was read. A calculator should apply no Wyoming depreciation adjustment.
