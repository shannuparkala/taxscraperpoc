"""Authority behind every computed Form 1040 line.

The tax engine decides *what* a line is. This module records *why* — the Code
section that requires it, the IRS publication a preparer would open to check it,
and a plain-English statement of the rule that a non-specialist can read.

Two properties matter more than completeness:

1. **Every citation points at a real, addressable source.** A URL that 404s is
   worse than no citation, because it looks like evidence.
2. **Uncertainty is declared, not smoothed over.** ``verified=False`` marks a
   rule whose statutory cite could not be confirmed against primary text — most
   often 2025 provisions still settling after the One Big Beautiful Bill Act.
   The UI shows those differently and the audit package flags them. Guessing a
   section number and presenting it in the same typeface as a confirmed one is
   how an explainability feature becomes a liability.

Adding a rule: cite the section that *imposes* the treatment, not the one that
merely mentions it, and prefer the form instruction over a topic page — the
instruction is what the preparer is actually working from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.enums import Jurisdiction


@dataclass(frozen=True, slots=True)
class Citation:
    """One addressable authority."""

    title: str
    url: str
    #: "IRC", "Treas. Reg.", "Publication", "Form Instruction", "Public Law".
    kind: str = "Publication"

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class TaxRule:
    """The authority and plain-English meaning behind one computation."""

    id: str
    #: Short name a preparer would recognise: "Taxable Social Security".
    title: str
    #: The rule stated so a non-specialist understands it. No jargon, no cites.
    plain_english: str
    #: Primary statutory hook, e.g. "IRC §86". Empty when purely arithmetic.
    irc_section: str = ""
    citations: tuple[Citation, ...] = ()
    jurisdiction: Jurisdiction = Jurisdiction.FEDERAL
    #: First tax year the rule as stated applies to.
    effective_from: int = 2018
    #: Last tax year, when the provision sunsets. None means open-ended.
    effective_to: int | None = None
    #: False when the statutory cite is not confirmed against primary text.
    verified: bool = True
    notes: str = ""

    def applies_to(self, year: int) -> bool:
        if year < self.effective_from:
            return False
        return self.effective_to is None or year <= self.effective_to

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "plain_english": self.plain_english,
            "irc_section": self.irc_section,
            "citations": [c.to_dict() for c in self.citations],
            "jurisdiction": self.jurisdiction.value,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "verified": self.verified,
            "notes": self.notes,
        }


# --- Frequently reused citations -------------------------------------------

_F1040_INSTR = Citation(
    "Form 1040 Instructions",
    "https://www.irs.gov/instructions/i1040gi",
    "Form Instruction",
)
_PUB_17 = Citation(
    "Publication 17 — Your Federal Income Tax",
    "https://www.irs.gov/publications/p17",
)
_PUB_550 = Citation(
    "Publication 550 — Investment Income and Expenses",
    "https://www.irs.gov/publications/p550",
)
_PUB_501 = Citation(
    "Publication 501 — Dependents, Standard Deduction, and Filing Information",
    "https://www.irs.gov/publications/p501",
)
_PUB_915 = Citation(
    "Publication 915 — Social Security and Equivalent Railroad Retirement Benefits",
    "https://www.irs.gov/publications/p915",
)
_SCH_B = Citation(
    "Schedule B Instructions — Interest and Ordinary Dividends",
    "https://www.irs.gov/instructions/i1040sb",
    "Form Instruction",
)
_SCH_D = Citation(
    "Schedule D Instructions — Capital Gains and Losses",
    "https://www.irs.gov/instructions/i1040sd",
    "Form Instruction",
)
_SCH_1 = Citation(
    "Schedule 1 — Additional Income and Adjustments to Income",
    "https://www.irs.gov/forms-pubs/about-schedule-1-form-1040",
    "Form Instruction",
)
_SCH_A = Citation(
    "Schedule A Instructions — Itemized Deductions",
    "https://www.irs.gov/instructions/i1040sca",
    "Form Instruction",
)
_OBBBA = Citation(
    "One Big Beautiful Bill Act, Pub. L. 119-21",
    "https://www.congress.gov/bill/119th-congress/house-bill/1",
    "Public Law",
)


def _irc(section: str, anchor: str) -> Citation:
    """A Cornell LII link, which is stable and free to read."""
    return Citation(
        f"IRC §{section}",
        f"https://www.law.cornell.edu/uscode/text/26/{anchor}",
        "IRC",
    )


# --- The registry ----------------------------------------------------------

RULES: dict[str, TaxRule] = {
    rule.id: rule
    for rule in (
        TaxRule(
            id="gross_income",
            title="Gross income",
            plain_english=(
                "Money you received during the year counts as income unless a "
                "specific rule says it does not."
            ),
            irc_section="IRC §61",
            citations=(_irc("61", "61"), _PUB_17, _F1040_INSTR),
        ),
        TaxRule(
            id="wages",
            title="Wages and salaries",
            plain_english=(
                "Everything your employer paid you for working goes on the "
                "return. Box 1 of each Form W-2 is that number."
            ),
            irc_section="IRC §61(a)(1)",
            citations=(_irc("61", "61"), _F1040_INSTR),
        ),
        TaxRule(
            id="tax_exempt_interest",
            title="Tax-exempt interest",
            plain_english=(
                "Interest from most state and local government bonds is not "
                "taxed. It is still reported, because a few other calculations "
                "look at it — including how much of your Social Security is "
                "taxable."
            ),
            irc_section="IRC §103",
            citations=(_irc("103", "103"), _PUB_550),
        ),
        TaxRule(
            id="taxable_interest",
            title="Taxable interest",
            plain_english=(
                "Interest a bank or broker paid you is income. Each payer sends "
                "a Form 1099-INT showing the amount."
            ),
            irc_section="IRC §61(a)(4)",
            citations=(_irc("61", "61"), _SCH_B, _PUB_550),
        ),
        TaxRule(
            id="qualified_dividends",
            title="Qualified dividends",
            plain_english=(
                "Some dividends are taxed at lower rates than ordinary income "
                "because you held the stock long enough. They are counted once, "
                "inside ordinary dividends, and shown separately so the lower "
                "rate can be applied."
            ),
            irc_section="IRC §1(h)(11)",
            citations=(_irc("1", "1"), _PUB_550),
        ),
        TaxRule(
            id="ordinary_dividends",
            title="Ordinary dividends",
            plain_english=(
                "A dividend is a share of a company's profits paid to you. Box "
                "1a of Form 1099-DIV is the total for the year."
            ),
            irc_section="IRC §61(a)(7)",
            citations=(_irc("61", "61"), _SCH_B, _PUB_550),
        ),
        TaxRule(
            id="ira_distributions",
            title="IRA distributions",
            plain_english=(
                "Money taken out of a traditional IRA is usually taxed, because "
                "it was not taxed when it went in. If you made non-deductible "
                "contributions, part of the withdrawal comes back tax-free."
            ),
            irc_section="IRC §408(d)",
            citations=(
                _irc("408", "408"),
                Citation(
                    "Publication 590-B — Distributions from IRAs",
                    "https://www.irs.gov/publications/p590b",
                ),
            ),
        ),
        TaxRule(
            id="pensions",
            title="Pensions and annuities",
            plain_english=(
                "Pension and annuity payments are taxed, except for any part "
                "that is simply returning money you already paid tax on."
            ),
            irc_section="IRC §72",
            citations=(
                _irc("72", "72"),
                Citation(
                    "Publication 575 — Pension and Annuity Income",
                    "https://www.irs.gov/publications/p575",
                ),
            ),
        ),
        TaxRule(
            id="social_security_taxable",
            title="Taxable Social Security benefits",
            plain_english=(
                "Social Security is not automatically taxed. The IRS adds up "
                "your other income plus half your benefits. If that total stays "
                "under a set amount, none of your benefits are taxed. Above it, "
                "part becomes taxable — at most 85% of what you received, never "
                "all of it."
            ),
            irc_section="IRC §86",
            citations=(
                _irc("86", "86"),
                _PUB_915,
                Citation(
                    "Notice 703 — Read This To See If Your Benefits May Be Taxable",
                    "https://www.irs.gov/pub/irs-pdf/n703.pdf",
                ),
                _F1040_INSTR,
            ),
            notes=(
                "Thresholds in §86(c) are fixed by statute and have never been "
                "indexed for inflation."
            ),
        ),
        TaxRule(
            id="capital_gains",
            title="Capital gain or loss",
            plain_english=(
                "When you sell an investment for more than you paid, the profit "
                "is taxed. Losses cancel out gains. Things held over a year get "
                "better rates than things held briefly."
            ),
            irc_section="IRC §§1211, 1222",
            citations=(_irc("1222", "1222"), _SCH_D, _PUB_550),
        ),
        TaxRule(
            id="capital_loss_limit",
            title="Capital loss limitation",
            plain_english=(
                "If your investment losses are bigger than your gains, you can "
                "subtract only $3,000 of the excess from other income this year "
                "($1,500 if married filing separately). The rest waits for next "
                "year — it is not lost."
            ),
            irc_section="IRC §1211(b)",
            citations=(_irc("1211", "1211"), _SCH_D),
        ),
        TaxRule(
            id="capital_loss_carryover",
            title="Capital loss carryover",
            plain_english=(
                "Losses you could not use this year carry forward to future "
                "years, keeping their short-term or long-term character."
            ),
            irc_section="IRC §1212(b)",
            citations=(_irc("1212", "1212"), _SCH_D),
        ),
        TaxRule(
            id="schedule_1_income",
            title="Additional income",
            plain_english=(
                "Income that does not fit the main lines — business profit, "
                "rental income, gains on business property — is totalled on "
                "Schedule 1 and carried onto the front page as one number."
            ),
            irc_section="IRC §61",
            citations=(_SCH_1, _F1040_INSTR),
        ),
        TaxRule(
            id="adjustments",
            title="Adjustments to income",
            plain_english=(
                "A short list of deductions you get whether or not you itemize "
                "— things like retirement contributions, student loan interest "
                "and part of self-employment tax. They come off before your AGI."
            ),
            irc_section="IRC §62(a)",
            citations=(_irc("62", "62"), _SCH_1),
        ),
        TaxRule(
            id="agi",
            title="Adjusted gross income",
            plain_english=(
                "Your total income minus the short list of adjustments. This is "
                "the number many other tax rules are measured against, so it "
                "matters well beyond this line."
            ),
            irc_section="IRC §62",
            citations=(_irc("62", "62"), _F1040_INSTR),
        ),
        TaxRule(
            id="standard_deduction",
            title="Standard deduction",
            plain_english=(
                "A flat amount everyone may subtract, no receipts required. It "
                "is larger if you are 65 or older, or blind."
            ),
            irc_section="IRC §63(c)",
            citations=(_irc("63", "63"), _PUB_501),
        ),
        TaxRule(
            id="additional_standard_deduction",
            title="Additional standard deduction for age or blindness",
            plain_english=(
                "If you are 65 or older, or blind, your standard deduction goes "
                "up. You count for each one that applies to you."
            ),
            irc_section="IRC §63(f)",
            citations=(_irc("63", "63"), _PUB_501),
            notes="Age is tested as born before January 2 of the year after the tax year.",
        ),
        TaxRule(
            id="itemized_deductions",
            title="Itemized deductions",
            plain_english=(
                "Instead of the flat amount, you can add up certain real "
                "expenses — medical bills above a threshold, state taxes, "
                "mortgage interest, donations. You take whichever is bigger."
            ),
            irc_section="IRC §63(d)",
            citations=(_irc("63", "63"), _SCH_A),
        ),
        TaxRule(
            id="senior_deduction",
            title="Additional deduction for taxpayers 65 and older",
            plain_english=(
                "For 2025 through 2028 there is an extra deduction for people "
                "aged 65 or older, on top of the larger standard deduction they "
                "already get. It shrinks as income rises and disappears "
                "entirely for higher earners."
            ),
            irc_section="Pub. L. 119-21 §70103",
            citations=(
                _OBBBA,
                Citation(
                    "About Schedule 1-A (Form 1040)",
                    "https://www.irs.gov/forms-pubs/about-form-1040",
                    "Form Instruction",
                ),
            ),
            effective_from=2025,
            effective_to=2028,
            verified=False,
            notes=(
                "Section number within P.L. 119-21 not confirmed against "
                "enrolled text. Confirm before relying on the cite in a filing."
            ),
        ),
        TaxRule(
            id="taxable_income",
            title="Taxable income",
            plain_english=(
                "What is left after deductions come off your AGI. This is the "
                "number the tax rates are actually applied to. It never goes "
                "below zero."
            ),
            irc_section="IRC §63(a)",
            citations=(_irc("63", "63"), _F1040_INSTR),
        ),
        TaxRule(
            id="ordinary_rates",
            title="Tax rates",
            plain_english=(
                "Income is taxed in slices. The first slice is taxed at the "
                "lowest rate, the next slice a bit higher, and so on. A raise "
                "never costs you money — only the slice above the line is taxed "
                "at the higher rate."
            ),
            irc_section="IRC §1",
            citations=(_irc("1", "1"), _F1040_INSTR),
        ),
        TaxRule(
            id="preferential_rates",
            title="Rates on qualified dividends and long-term gains",
            plain_english=(
                "Long-term investment profits and qualified dividends are taxed "
                "at lower rates than wages — often 0%, 15%, or 20%."
            ),
            irc_section="IRC §1(h)",
            citations=(
                _irc("1", "1"),
                _SCH_D,
                Citation(
                    "Topic 409 — Capital Gains and Losses",
                    "https://www.irs.gov/taxtopics/tc409",
                ),
            ),
        ),
        TaxRule(
            id="child_tax_credit",
            title="Child tax credit",
            plain_english=(
                "A credit for each qualifying child, which comes straight off "
                "the tax you owe. It phases out once income passes a threshold."
            ),
            irc_section="IRC §24",
            citations=(
                _irc("24", "24"),
                Citation(
                    "Schedule 8812 Instructions — Credits for Qualifying Children",
                    "https://www.irs.gov/instructions/i1040s8",
                    "Form Instruction",
                ),
            ),
        ),
        TaxRule(
            id="nonrefundable_credits",
            title="Nonrefundable credits",
            plain_english=(
                "These credits can reduce your tax bill to zero, but no "
                "further. If a credit is bigger than your tax, the extra is not "
                "paid out to you."
            ),
            irc_section="IRC §26",
            citations=(_irc("26", "26"), _F1040_INSTR),
        ),
        TaxRule(
            id="self_employment_tax",
            title="Self-employment tax",
            plain_english=(
                "If you work for yourself, you pay both halves of Social "
                "Security and Medicare — the part an employee pays and the part "
                "an employer would have paid. Half of it is deductible."
            ),
            irc_section="IRC §1401",
            citations=(
                _irc("1401", "1401"),
                Citation(
                    "Schedule SE Instructions — Self-Employment Tax",
                    "https://www.irs.gov/instructions/i1040sse",
                    "Form Instruction",
                ),
            ),
        ),
        TaxRule(
            id="total_tax",
            title="Total tax",
            plain_english=(
                "Your tax after credits, plus any extra taxes such as "
                "self-employment tax. This is what you owe for the year, before "
                "counting what you already paid."
            ),
            citations=(_F1040_INSTR,),
        ),
        TaxRule(
            id="withholding",
            title="Federal income tax withheld",
            plain_english=(
                "Tax already taken out of your pay and other income during the "
                "year and sent to the IRS on your behalf."
            ),
            irc_section="IRC §31",
            citations=(_irc("31", "31"), _F1040_INSTR),
        ),
        TaxRule(
            id="estimated_payments",
            title="Estimated tax payments",
            plain_english=(
                "Payments you made yourself during the year, plus any refund "
                "from last year that you chose to leave with the IRS to cover "
                "this year."
            ),
            irc_section="IRC §6654",
            citations=(_irc("6654", "6654"), _F1040_INSTR),
        ),
        TaxRule(
            id="overpayment",
            title="Overpayment",
            plain_english=(
                "You paid more during the year than you owed. The difference is "
                "yours — you can have it refunded, or leave it with the IRS to "
                "count toward next year."
            ),
            irc_section="IRC §6402",
            citations=(_irc("6402", "6402"), _F1040_INSTR),
        ),
        TaxRule(
            id="applied_to_next_year",
            title="Overpayment applied to next year",
            plain_english=(
                "Instead of taking your refund now, you can leave it with the "
                "IRS as a head start on next year's tax. This is your choice — "
                "nothing in your documents decides it."
            ),
            irc_section="IRC §6402(b)",
            citations=(_irc("6402", "6402"), _F1040_INSTR),
        ),
        TaxRule(
            id="amount_owed",
            title="Amount you owe",
            plain_english=(
                "You paid less during the year than you owed, so the difference "
                "is due with the return."
            ),
            irc_section="IRC §6151",
            citations=(_irc("6151", "6151"), _F1040_INSTR),
        ),
        TaxRule(
            id="arithmetic",
            title="Form arithmetic",
            plain_english=(
                "This line is a subtotal — the form adds up the lines above it. "
                "No separate tax rule applies."
            ),
            citations=(_F1040_INSTR,),
        ),
    )
}


def get_rule(rule_id: str) -> TaxRule | None:
    return RULES.get(rule_id)


def rules_for_year(year: int) -> list[TaxRule]:
    """Every rule in force for a tax year, for the compliance panel."""
    return sorted(
        (r for r in RULES.values() if r.applies_to(year)), key=lambda r: r.title
    )


def unverified_rule_ids() -> frozenset[str]:
    """Rules whose statutory cite is not confirmed. Surfaced, never hidden."""
    return frozenset(r.id for r in RULES.values() if not r.verified)
