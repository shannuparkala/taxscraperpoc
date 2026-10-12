# Schedule B, Schedule D, and Form 8949 (Form 1040, 2025) — line-by-line structure

Tax year: **2025** (returns filed in the 2026 filing season). Enacted law only;
nothing proposed is included below.

Companion note to `form-1040-2025-line-by-line.md`, which documents Form
1040's own lines 2a/2b, 3a/3b and 7a/7b but explicitly deferred Schedule B,
Schedule D and Form 8949's internals ("worth its own research pass"). This
note also partially closes that note's open item on line 16's worksheet
dispatch — see "Which Form 1040 lines each feeds," below.

## Sources

- **Schedule B (Form 1040) 2025**, Interest and Ordinary Dividends.
  https://www.irs.gov/pub/irs-pdf/f1040sb.pdf — Cat. No. 17146N, footer
  "Created 4/23/25". Attachment Sequence No. 08.
- **Schedule D (Form 1040) 2025**, Capital Gains and Losses.
  https://www.irs.gov/pub/irs-pdf/f1040sd.pdf — Cat. No. 11338H, footer
  "Created 10/6/25". Attachment Sequence No. 12.
- **Instructions for Schedule D (Form 1040) (2025)**.
  https://www.irs.gov/pub/irs-pdf/i1040sd.pdf (also
  https://www.irs.gov/instructions/i1040sd) — Catalog Number 24331I, dated
  **Dec 11, 2025** on the document itself — more than 5 months after OBBBA's
  4 July 2025 enactment, which matters for the two-layer check below.
- **Form 8949 (2025)**, Sales and Other Dispositions of Capital Assets.
  https://www.irs.gov/pub/irs-pdf/f8949.pdf — Cat. No. 37768Z, footer
  "Created 5/5/25". Attachment Sequence No. 12A.
- **Instructions for Form 8949 (2025)**.
  https://www.irs.gov/pub/irs-pdf/i8949.pdf (also
  https://www.irs.gov/instructions/i8949) — Catalog Number 59421Z, dated
  **Jan 20, 2026** — the most recently revised primary source used in this
  note.

All five read directly from the extracted PDF text (every page of each), not
a summary or third-party transcription. Method note for future passes: this
tool's web fetch cannot parse these PDFs directly (it reports raw
FlateDecode stream data and refuses to guess), but it does save the binary
alongside its reply; reading that saved file with the file-reading tool
extracts clean text with no `pages` parameter needed, for documents up to at
least 16 pages (the Schedule D instructions). The earlier form-1040 note's
finding that this environment can't get past a poppler/page-range error on a
large PDF was recorded against `i1040gi.pdf` specifically (the *general*
Form 1040 instructions, materially longer); it was not retested here and may
still hold for that document.

`figures_as_of: 2026-09-22` (date this note was written) for every figure
below unless stated otherwise. `figures_source_url` is the URL given for
each source above, matched by document.

## Two-layer check (Rev. Proc. 2024-40 vs. OBBBA)

Two kinds of dollar figures appear across these three forms:

- **The capital-loss limitation ($3,000 / $1,500 MFS, IRC §1211(b))** is a
  fixed statutory number, not inflation-indexed. Neither Rev. Proc. 2024-40
  nor OBBBA touches it — there is no two-layer question for this figure, in
  any year. Confirmed against Schedule D Part III, line 21, and the "Capital
  Losses" section of the Schedule D instructions (both quoted below).
- **The 0%/15%/20% preferential capital-gain rate breakpoints** (used in the
  Schedule D Tax Worksheet, line 15/19/26) **are** inflation-indexed
  annually under IRC §1(j)(5). Rev. Proc. 2024-40 set the 2025 figures in
  October 2024. Because the Schedule D instructions used here are dated
  **Dec 11, 2025** — 5+ months after OBBBA — the breakpoints printed in the
  worksheet already reflect whatever OBBBA did or didn't do to this
  provision; no separate reconciliation against Rev. Proc. 2024-40 is
  needed, because the post-OBBBA primary source is the one in hand.
  **Result: the printed breakpoints ($48,350 / $96,700 / $48,350 / $64,750
  for the 0% ceiling; $533,400 / $600,050 / $300,000 / $566,700 for the 20%
  floor, single / MFJ / MFS / HoH respectively) are identical, dollar for
  dollar, to Rev. Proc. 2024-40's original figures already in
  `backend/app/tax_constants/2025.json` (`capital_gain_brackets`, authority
  `RP_2024_40`).** OBBBA did not override the capital-gains rate structure
  for 2025 — confirmed by reading the post-OBBBA primary text itself, not
  inferred from its absence from OBBBA news coverage.

**Engine cross-check, no change proposed:** `capital_loss_deduction` ($3,000,
IRC §1211(b)), `capital_loss_deduction_mfs` ($1,500, IRC §1211(b)), and
`capital_gain_brackets` (authority `RP_2024_40`) in
`backend/app/tax_constants/2025.json` all match the primary text read in
this session exactly. Existing constants confirmed correct.

## Schedule B — Interest and Ordinary Dividends

### Part I — Interest
- **1** "List name of payer. If any interest is from a seller-financed
  mortgage and the buyer used the property as a personal residence, see the
  instructions and list this interest first. Also, show that buyer's social
  security number and address:" — Amount column, multiple payer rows.
- **2** "Add the amounts on line 1"
- **3** "Excludable interest on series EE and I U.S. savings bonds issued
  after 1989. Attach Form 8815" → Form 8815
- **4** "Subtract line 3 from line 2. Enter the result here and on Form 1040
  or 1040-SR, line 2b" → **Form 1040 line 2b**
  - Note printed directly under line 4: **"If line 4 is over $1,500, you
    must complete Part III."**

### Part II — Ordinary Dividends
- **5** "List name of payer:" — Amount column, multiple payer rows.
- **6** "Add the amounts on line 5. Enter the total here and on Form 1040 or
  1040-SR, line 3b" → **Form 1040 line 3b**
  - Note printed directly under line 6: **"If line 6 is over $1,500, you
    must complete Part III."**

Margin notes on both parts point to "the Instructions for Form 1040, line
2b" / "line 3b" respectively, and instruct that if a Form 1099-INT,
1099-OID, or 1099-DIV (or substitute statement) was received from a
brokerage firm, list the firm's name as payer and enter the total shown on
that form.

### Part III — Foreign Accounts and Trusts
Gateway sentence, quoted in full: **"You must complete this part if you (a)
had over $1,500 of taxable interest or ordinary dividends; (b) had a foreign
account; or (c) received a distribution from, or were a grantor of, or a
transferor to, a foreign trust."**

- **7a** "At any time during 2025, did you have a financial interest in or
  signature authority over a financial account (such as a bank account,
  securities account, or brokerage account) located in a foreign country?
  See instructions" [Yes/No]. Sub-question, same line: "If 'Yes,' are you
  required to file FinCEN Form 114, Report of Foreign Bank and Financial
  Accounts (FBAR), to report that financial interest or signature authority?
  See FinCEN Form 114 and its instructions for filing requirements and
  exceptions to those requirements" [Yes/No] → FinCEN Form 114
- **7b** "If you are required to file FinCEN Form 114, list the name(s) of
  the foreign country(-ies) where the financial account(s) is (are)
  located:"
- **8** "During 2025, did you receive a distribution from, or were you the
  grantor of, or transferor to, a foreign trust? If 'Yes,' you may have to
  file Form 3520. See instructions" [Yes/No] → Form 3520

Caution box (Part III margin): failure to file FinCEN Form 114 when
required "may result in substantial penalties," and Form 8938 (Statement of
Specified Foreign Financial Assets) may also be required — Schedule B does
not itself determine the Form 8938 threshold.

**Nothing in Part III feeds a Form 1040 line number.** It is disclosure
only (three Yes/No questions plus a country list); its consequence is
whether FinCEN Form 114 / Form 8938 / Form 3520 must be filed as separate,
non-1040 filings.

## Form 8949 — Sales and Other Dispositions of Capital Assets

Purpose, quoted: "Use Form 8949 to report sales and exchanges of capital
assets. Form 8949 allows you and the IRS to reconcile amounts that were
reported to you and the IRS on Form 1099-B, Form 1099-DA, or Form 1099-S (or
substitute statements) with the amounts you report on your return." (2025
Instructions for Form 8949, "Purpose of Form.") **Form 8949 never feeds a
Form 1040 line directly — only Schedule D.**

### Part I — Short-Term (property held ≤ 1 year, generally)
Boxes — check exactly one per copy of Part I, verbatim:
- **(A)** "Short-term transactions reported on Form(s) 1099-B showing basis
  was reported to the IRS"
- **(B)** "Short-term transactions reported on Form(s) 1099-B showing basis
  was not reported to the IRS"
- **(C)** "Short-term transactions, other than digital asset transactions,
  not reported to you on Form 1099-B or Form 1099-DA"
- **(G)** "Short-term transactions reported on Form(s) 1099-DA showing
  basis was reported to the IRS"
- **(H)** "Short-term transactions reported on Form(s) 1099-DA showing
  basis was not reported to the IRS"
- **(I)** "Short-term digital asset transactions not reported to you on
  Form 1099-DA or Form 1099-B"

### Part II — Long-Term (property held > 1 year, generally)
Same structure, boxes D/E/F mirror A/B/C and J/K/L mirror G/H/I, substituting
"Long-term" for "Short-term."

### Columns (both parts, identical)
(a) Description of property; (b) Date acquired; (c) Date sold or disposed
of; (d) Proceeds (sales price); (e) Cost or other basis; (f) Code(s) from
instructions; (g) Amount of adjustment; (h) Gain or (loss) — "Subtract
column (e) from column (d) and combine the result with column (g)."

### Line 1 (transaction rows) and Line 2 (totals)
Each part has one numbered data section (unlabeled row "1" for individual
transactions) and:
- **2** "Totals. Add the amounts in columns (d), (e), (g), and (h) (subtract
  negative amounts). Enter each total here and include on your Schedule D,
  **line 1b** (if Box A or Box G above is checked), **line 2** (if Box B or
  Box H above is checked), or **line 3** (if Box C or Box I above is
  checked)" [Part I]; the identical sentence for Part II reads **line 8b**
  (D/J), **line 9** (E/K), **line 10** (F/L).

Note printed under both totals lines: if Box A/G (or D/J) is checked but the
IRS-reported basis was wrong, still enter the IRS-reported basis in column
(e) and correct it with an adjustment in column (g) — don't just overwrite
column (e).

### How Form 8949 totals flow into Schedule D — the box map

| Form 8949 part | Box | Meaning | → Schedule D line |
|---|---|---|---|
| I (short-term) | A or G | 1099-B/1099-DA, basis reported to IRS, no adjustment needed | **1b** |
| I | B or H | 1099-B/1099-DA, basis **not** reported to IRS | **2** |
| I | C or I | No 1099-B/1099-DA received (C = non-digital-asset; I = digital asset) | **3** |
| II (long-term) | D or J | 1099-B/1099-DA, basis reported to IRS, no adjustment needed | **8b** |
| II | E or K | 1099-B/1099-DA, basis **not** reported to IRS | **9** |
| II | F or L | No 1099-B/1099-DA received (F = non-digital-asset; L = digital asset) | **10** |

Each Schedule D line's own columns (d)/(e)/(g)/(h) simply restate the
matching Form 8949 total — Schedule D does not re-derive gain/loss from raw
transaction data itself except on lines 1a/8a (see Exception 1).

### Exception 1 — skip Form 8949 entirely
Quoted from the 2025 Instructions for Form 8949: **"Form 8949 isn't required
for certain transactions. You may be able to aggregate those transactions
and report them directly on either line 1a (for short-term transactions) or
line 8a (for long-term transactions) of Schedule D. This option applies only
to transactions (other than sales of collectibles) for which: You received a
Form 1099-B (or substitute statement) that shows basis was reported to the
IRS and doesn't show any adjustments in box 1f or 1g; The Ordinary box in
box 2 on Form 1099-B isn't checked; You received a Form 1099-DA (or
substitute statement) that shows basis was reported to the IRS and doesn't
show any adjustments in box 1h or 1i; The Ordinary box in box 6 on Form
1099-DA isn't checked; You don't need to make any adjustments to the basis
or type of gain (or loss) reported on Form 1099-B or Form 1099-DA (or
substitute statement), or to your gain (or loss); and You aren't electing to
defer income due to an investment in a QOF and aren't terminating deferral
from an investment in a QOF."** If used, no Form 8949 and no attached
statement is required for those transactions; Exception 1 and Exception 2
(below) can be combined.

**Exception 2** (summarized): instead of one row per transaction, attach a
statement in the same column format and enter combined totals on Part I/II
with the applicable box checked, code "M" in column (f). Not available for
QOF gain-deferral elections. A further **"Special provision"** lets certain
corporations, partnerships, securities dealers and exempt organizations
(not individuals, "except in rare circumstances") enter bare summary totals
with "Available upon request" in column (a) when a box's transaction count
exceeds five.

### Column (f) adjustment codes (condensed from the full table)

| Code | Trigger (condensed) |
|---|---|
| B | 1099-B/1099-DA basis shown is wrong |
| C | Disposed of a collectible |
| D | Accrued market discount shown in 1099-B box 1f / 1099-DA box 1h |
| E | Selling expenses, option premiums, or digital-asset transaction costs not reflected on the 1099 |
| H | Main-home sale, gain partly or fully excludable under §121 |
| L | Nondeductible loss (personal-use property, related-party sale, etc.) other than a wash sale |
| M | Multiple transactions reported on one summarized row (Exception 2 / special provision) |
| N | Received the 1099 as a nominee for the actual owner |
| O | Any adjustment not covered by another code (incl. contingent payment debt instrument, §1231 QOF bookkeeping rows) |
| P | Nonresident alien/foreign trust/estate/corporation selling a U.S.-trade-or-business partnership interest |
| Q | QSB (§1202) stock — partial gain exclusion |
| R | Postponing gain under a rollover election (e.g., QSB stock rollover) |
| S | §1244 small-business-stock loss exceeding the ordinary-loss cap |
| T | 1099-B box 2 / 1099-DA box 6 short-/long-term characterization is wrong |
| W | Nondeductible wash-sale loss |
| X | DC Zone asset / qualified community asset gain exclusion |
| Y | Recognizing gain previously deferred into a QOF |
| Z | Electing to defer gain by investing in a QOF |

Multiple codes on one row are entered in alphabetical order with no
separator, e.g. "BOQ."

### New for 2025 — digital assets
"What's New" in both the Schedule D and Form 8949 instructions: **boxes
G/H/I (short-term) and J/K/L (long-term)** are new, tied to the new **Form
1099-DA** broker information return for digital-asset dispositions. "Do not
use box C to report short-term digital asset transactions" / "Do not use
box F to report digital asset transactions" — C and F are now reserved for
non-digital-asset, non-1099-reported dispositions only. A digital asset
"acquired after 2025" becomes a *covered security* for broker basis-reporting
purposes going forward (Instructions for Form 8949, "Column (e)—Cost or
Other Basis").

## Schedule D — Capital Gains and Losses

Top of form (before Part I): **"Did you dispose of any investment(s) in a
qualified opportunity fund during the tax year?"** [Yes/No] — "If 'Yes,'
attach Form 8949 and see its instructions for additional requirements for
reporting your gain or loss."

### Part I — Short-Term Capital Gains and Losses (generally held ≤ 1 year)
Columns: (d) Proceeds; (e) Cost (or other basis); (g) Adjustments to
gain/loss from Form(s) 8949, Part I, line 2, column (g); (h) Gain or (loss).

- **1a** "Totals for all short-term transactions reported on Form 1099-B or
  Form 1099-DA for which basis was reported to the IRS and for which you
  have no adjustments (see instructions). However, if you choose to report
  all these transactions on Form 8949, leave this line blank and go to line
  1b" → Exception 1 destination
- **1b** "Totals for all transactions reported on Form(s) 8949 with Box A or
  Box G checked" → Form 8949 Part I
- **2** "Totals for all transactions reported on Form(s) 8949 with Box B or
  Box H checked" → Form 8949 Part I
- **3** "Totals for all transactions reported on Form(s) 8949 with Box C or
  Box I checked" → Form 8949 Part I
- **4** "Short-term gain from Form 6252 and short-term gain or (loss) from
  Forms 4684, 6781, and 8824" → Forms 6252, 4684, 6781, 8824
- **5** "Net short-term gain or (loss) from partnerships, S corporations,
  estates, and trusts from Schedule(s) K-1" → Schedule(s) K-1
- **6** "Short-term capital loss carryover. Enter the amount, if any, from
  line 8 of your Capital Loss Carryover Worksheet in the instructions"
  (entered in parentheses) → Capital Loss Carryover Worksheet line 8
- **7** "Net short-term capital gain or (loss). Combine lines 1a through 6
  in column (h). If you have any long-term capital gains or losses, go to
  Part II below. Otherwise, go to Part III on the back"

### Part II — Long-Term Capital Gains and Losses (generally held > 1 year)
Same column structure, referencing Form(s) 8949, Part II, line 2, column
(g).

- **8a** mirrors 1a for long-term, "leave this line blank and go to line 8b"
- **8b** "Totals for all transactions reported on Form(s) 8949 with Box D or
  Box J checked"
- **9** "Totals for all transactions reported on Form(s) 8949 with Box E or
  Box K checked"
- **10** "Totals for all transactions reported on Form(s) 8949 with Box F or
  Box L checked"
- **11** "Gain from Form 4797, Part I; long-term gain from Forms 2439 and
  6252; and long-term gain or (loss) from Forms 4684, 6781, and 8824" →
  Forms 4797, 2439, 6252, 4684, 6781, 8824
- **12** "Net long-term gain or (loss) from partnerships, S corporations,
  estates, and trusts from Schedule(s) K-1"
- **13** "Capital gain distributions. See the instructions" → sourced from
  Form 1099-DIV, box 2a (per the instructions' "Capital Gain Distributions"
  section)
- **14** "Long-term capital loss carryover. Enter the amount, if any, from
  line 13 of your Capital Loss Carryover Worksheet in the instructions"
  (entered in parentheses) → Capital Loss Carryover Worksheet line 13
- **15** "Net long-term capital gain or (loss). Combine lines 8a through 14
  in column (h). Then, go to Part III on the back"

### Part III — Summary (the capital-loss-limitation and dispatch logic)
- **16** "Combine lines 7 and 15 and enter the result." Three-way dispatch,
  quoted: "If line 16 is a **gain**, enter the amount from line 16 on Form
  1040, 1040-SR, or 1040-NR, line 7a. Then, go to line 17 below. • If line
  16 is a **loss**, skip lines 17 through 20 below. Then, go to line 21.
  Also be sure to complete line 22. • If line 16 is **zero**, skip lines 17
  through 21 below and enter -0- on Form 1040, 1040-SR, or 1040-NR, line 7a.
  Then, go to line 22."
- **17** "Are lines 15 and 16 both gains?" Yes → line 18. No → skip 18-21, go
  to 22.
- **18** "If you are required to complete the 28% Rate Gain Worksheet (see
  instructions), enter the amount, if any, from line 7 of that worksheet"
- **19** "If you are required to complete the Unrecaptured Section 1250 Gain
  Worksheet (see instructions), enter the amount, if any, from line 18 of
  that worksheet"
- **20** "Are lines 18 and 19 both zero or blank and you are not filing Form
  4952?" **Yes** → "Complete the Qualified Dividends and Capital Gain Tax
  Worksheet in the instructions for Form 1040, line 16. Don't complete
  lines 21 and 22 below." **No** → "Complete the Schedule D Tax Worksheet in
  the instructions. Don't complete lines 21 and 22 below."
- **21** "If line 16 is a loss, enter here and on Form 1040, 1040-SR, or
  1040-NR, line 7a, the **smaller** of: • The loss on line 16; or •
  **($3,000)**, or if married filing separately, **($1,500)**." Note: "When
  figuring which amount is smaller, treat both amounts as positive numbers."
  → **Form 1040 line 7a** (this is the capital-loss-limitation line)
- **22** "Do you have qualified dividends on Form 1040, 1040-SR, or 1040-NR,
  line 3a?" **Yes** → "Complete the Qualified Dividends and Capital Gain Tax
  Worksheet in the instructions for Form 1040, line 16." **No** → "Complete
  the rest of Form 1040, 1040-SR, or 1040-NR."

### Capital Losses — the $3,000/$1,500 rule, narrative form
Quoted from the Instructions for Schedule D, "Capital Losses": **"You can
deduct capital losses up to the amount of your capital gains plus $3,000
($1,500 if married filing separately). You may be able to use capital
losses that exceed this limit in future years... Be sure to report all of
your capital gains and losses even if you can't use all of your losses in
2025."** Authority: IRC §1211(b) (fixed statutory dollar amount — see
two-layer check above).

### Capital Loss Carryover Worksheet — Lines 6 and 14 (verbatim)

Gate condition, quoted: **"Use this worksheet to figure your capital loss
carryovers from 2024 to 2025 if your 2024 Schedule D, line 21, is a loss and
(a) that loss is a smaller loss than the loss on your 2024 Schedule D, line
16; or (b) if the amount on your 2024 Form 1040, 1040-SR or 1040-NR, line 15
would be less than zero if you could enter a negative amount on that line.
Otherwise, you don't have any carryovers."** Divorce/separation note, same
section: if a married couple who once filed jointly now files separately,
"any capital loss carryover from the joint return can be deducted only on
the return of the spouse who actually had the loss."

| Line | Text | Feeds |
|---|---|---|
| 1 | Amount from 2024 Form 1040/1040-SR/1040-NR, line 15 (parenthesized if it would've been negative) | — |
| 2 | 2024 Schedule D, line 21 loss, as a positive amount | — |
| 3 | Combine lines 1 and 2; if ≤0, enter -0- | — |
| 4 | Smaller of line 2 or line 3 | — |
| — | Gate: "If line 7 of your 2024 Schedule D is a loss, go to line 5; otherwise, enter -0- on line 5 and go to line 9." | — |
| 5 | 2024 Schedule D line 7 loss, as a positive amount | — |
| 6 | Gain from 2024 Schedule D line 15 (0 if a loss) | — |
| 7 | Add lines 4 and 6 | — |
| 8 | **Short-term capital loss carryover for 2025.** Line 5 − line 7; if ≤0, enter -0- | **→ Schedule D, line 6** |
| — | Gate: "If line 15 of your 2024 Schedule D is a loss, go to line 9; otherwise, skip lines 9 through 13." | — |
| 9 | 2024 Schedule D line 15 loss, as a positive amount | — |
| 10 | Gain from 2024 Schedule D line 7 (0 if a loss) | — |
| 11 | Line 4 − line 5; if ≤0, enter -0- | — |
| 12 | Add lines 10 and 11 | — |
| 13 | **Long-term capital loss carryover for 2025.** Line 9 − line 12; if ≤0, enter -0- | **→ Schedule D, line 14** |

Character is preserved separately: short-term carryover only ever populates
line 6 (Part I); long-term carryover only ever populates line 14 (Part II).
A caveat also folded in here: "If you excluded canceled debt from income in
2025, see Pub. 4681" (interacts with basis/loss figures, not researched
further).

**Carryover forward, to 2026** (Schedule D instructions, "Line 21"),
quoted: **"You have a capital loss carryover from 2025 to 2026 if you have a
loss on line 16 and either: • That loss is more than the loss on line 21;
or • The amount on Form 1040, 1040-SR, or 1040-NR, line 15, would be less
than zero if you could enter a negative amount on that line."** The 2026
carryover itself is computed on the *2026* Instructions for Schedule D's
version of this same worksheet — not knowable from the 2025 form.

### 28% Rate Gain Worksheet (line 18) and Unrecaptured Section 1250 Gain Worksheet (line 19) — summarized
Both are "keep for your records" worksheets, not filed. The **28% Rate Gain
Worksheet** (7 lines) is required when line 17 is "Yes" and the filer
reported a collectibles gain/loss or a §1202 QSB-stock exclusion (code "Q")
on Form 8949 Part II; it nets collectibles gain against long-term capital
loss carryovers and Schedule D line 7 losses. The **Unrecaptured Section
1250 Gain Worksheet** (18 lines) is required when line 17 is "Yes" and the
filer disposed of depreciated real property held > 1 year, received
installment payments on such property, or was passed unrecaptured §1250
gain on a Schedule K-1 / 1099-DIV / Form 2439. Neither worksheet's own
figures were transcribed line-by-line in this pass (edge cases, not the
capital-loss-limitation core of this note) — revisit narrowly if the engine
ever needs collectibles or depreciation-recapture handling.

### Schedule D Tax Worksheet vs. Qualified Dividends and Capital Gain Tax Worksheet
This is the dispatcher Form 1040's own note (`form-1040-2025-line-by-line.md`)
flagged as unresolved ("Line 16's 'Tax (see instructions)' is itself a
worksheet dispatch... not resolved in this note"). Schedule D lines 17/20/22
**are** that dispatch logic when Schedule D is filed at all:

- Line 20 "No" (28%-rate or unrecaptured-1250 gain present, or Form 4952
  line 4g in use) → **Schedule D Tax Worksheet** (47 lines).
- Line 20 "Yes," or line 17 "No," or line 22 "Yes" with no Schedule D 28%/1250
  amounts → **Qualified Dividends and Capital Gain Tax Worksheet** (lives in
  the *Form 1040* instructions — not the Schedule D instructions — and was
  **not** fetched in this pass; the earlier form-1040 note's environment
  limitation on `i1040gi.pdf` may still apply, see "Method note" above).
- The Schedule D Tax Worksheet's own gate (its header text, quoted):
  "Complete this worksheet only if line 18 or line 19 of Schedule D is more
  than zero and lines 15 and 16 of Schedule D are gains or if you file Form
  4952 and you have an amount on line 4g, even if you don't need to file
  Schedule D. Otherwise, complete the Qualified Dividends and Capital Gain
  Tax Worksheet..." Its own exception: neither worksheet applies (use the
  Form 1040 line-16 instructions directly instead) if "Line 15 or line 16 of
  Schedule D is zero or less and you have no qualified dividends... or...
  Form 1040, 1040-SR, or 1040-NR, line 15, is zero or less."
- Its final line, **47**: "Tax on all taxable income (including capital
  gains and qualified dividends). Enter the smaller of line 45 or line 46.
  Also, include this amount on Form 1040, 1040-SR, or 1040-NR, line 16."
  → **Form 1040 line 16**.
- **2025 rate breakpoints, printed on the worksheet** (lines 15/19/26,
  taxable-income cutoffs, see two-layer check above):

  | Filing status | 0% ceiling (line 15) | line 19 cutoff | 20% floor (line 26) |
  |---|---|---|---|
  | Single | $48,350 | $197,300 | $533,400 |
  | Married filing jointly / QSS | $96,700 | $394,600 | $600,050 |
  | Married filing separately | $48,350 | $197,300 | $300,000 |
  | Head of household | $64,750 | $197,300 | $566,700 |

  (15% applies between the 0% ceiling and 20% floor.) Line 19's cutoff feeds
  the worksheet's 25% unrecaptured-§1250-gain layer (lines 35-40), not the
  ordinary 0/15/20% capital-gain split — read as printed; not independently
  re-derived from §1(h)/(j) in this pass.

### Rounding (Schedule D and Form 8949 each carry their own statement)
Schedule D instructions, verbatim: "You can round off cents to whole dollars
on your Schedule D. If you do round to whole dollars, you must round all
amounts. To round, drop amounts under 50 cents and increase amounts from 50
to 99 cents to the next dollar. For example, $1.39 becomes $1 and $2.50
becomes $3." Form 8949 instructions, verbatim: "You can round off cents to
whole dollars on Form 8949. If you do round to whole dollars, round all
amounts. To round, drop cent amounts under 50 cents and increase cent
amounts over 49 cents to the next dollar. For example, $1.49 becomes $1 and
$1.50 becomes $2." Both round half up and both are all-or-nothing, matching
the substance already recorded (from the general Form 1040 instructions) in
`form-1040-2025-line-by-line.md` — this does not replace that note's still-open
verbatim-citation item for the *general* instructions' own wording, since
these are each schedule's own separate rounding paragraph, not the one that
note was chasing.

## Which Form 1040 lines each feeds — summary

| Source | Line | → Form 1040 |
|---|---|---|
| Schedule B | line 4 (net taxable interest) | line 2b |
| Schedule B | line 6 (net ordinary dividends) | line 3b |
| Schedule B | Part III (7a/7b/8) | none — disclosure only (FinCEN 114 / Form 8938 / Form 3520 triggers) |
| Form 8949 | (both parts) | none directly — feeds Schedule D only |
| Schedule D | line 16 if gain | line 7a |
| Schedule D | line 21 if loss (capped at $3,000/$1,500) | line 7a |
| Schedule D | line 16 if zero | line 7a (as "-0-") |
| Schedule D | line 13 (cap. gain distributions) | sourced from 1099-DIV box 2a; not itself a 1040 line |
| Schedule D Tax Worksheet | line 47 | line 16 (tax) |
| *(reverse feed)* | Form 1040 line 3a (qualified dividends) | → Schedule D line 22 gateway, and into both the Schedule D Tax Worksheet and the QDCGT Worksheet |

## Open questions / follow-ups

1. Qualified Dividends and Capital Gain Tax Worksheet's own line-by-line
   text (lives in `i1040gi.pdf`, not fetched this session — carries forward
   the same environment limitation the form-1040 note recorded).
2. 28% Rate Gain Worksheet and Unrecaptured Section 1250 Gain Worksheet:
   gate conditions recorded, full line text not transcribed (collectibles /
   depreciation-recapture edge cases).
3. Form 1040 line 7b's exact "Schedule D not required" condition (as
   opposed to Form 8949's Exception 1, which is a different, narrower
   condition about whether *8949 itself* is needed) — still not confirmed
   from primary text; the form-1040 note flagged this as open and it remains
   open here too.
4. Form 1099-B and Form 1099-DA's own box numbering (referenced throughout
   Form 8949's instructions, e.g. box 1e/1g for basis, box 12/2 for
   "basis reported to IRS") was not independently pulled from those forms'
   own instructions — only as described secondhand inside the Form 8949 and
   Schedule D instructions. Worth its own pass if the extraction pipeline
   ever needs to map 1099-B/1099-DA boxes directly.

status: confirmed (all line wording for Schedule B, Schedule D Parts I-III,
and Form 8949 Parts I-II, read directly off the primary PDFs; the Form
8949→Schedule D box map; the Capital Loss Carryover Worksheet; the $3,000/
$1,500 limitation; the capital-gain rate breakpoints cross-checked against
the engine's existing constants) / verify (Schedule D Tax Worksheet line 19's
exact statutory basis; items in "Open questions" above)
