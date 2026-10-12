"""Schedule 1 (Form 1040) 2025 - Additional Income and Adjustments to Income.

Line wording and routing from
``docs/tax-research/schedule-1-2-3-2025-line-by-line.md``, read off the primary
PDF (Cat. No. 71479F, created 7/25/25).

Part I line 10 feeds Form 1040 line 8. Part II line 26 feeds Form 1040 line 10.

Two things on this form are easy to get wrong and are handled explicitly below:
the unnumbered 1099-K reconciliation entry above Part I is **not** part of the
line 10 sum, and line 10 combines lines 1 through 7 **and 9** - not 1 through 9,
because 8a-8z roll up through 9 and would otherwise be counted twice.
"""

from __future__ import annotations

from app.services.tax_engine.graph.engine import register_form
from app.services.tax_engine.graph.facts import TaxpayerFacts
from app.services.tax_engine.graph.forms._common import (
    carried,
    direct,
    from_form,
    lettered,
    reserved,
    subtotal,
)
from app.services.tax_engine.graph.nodes import Node

FORM = "Schedule 1"
KEY = "sch1"

#: Line 8a-8z, "Other income". Parenthesised entries on the form face are
#: negative figures, not a different kind of line - they are entered signed.
OTHER_INCOME: tuple[tuple[str, str], ...] = (
    ("a", "Net operating loss"),
    ("b", "Gambling"),
    ("c", "Cancellation of debt"),
    ("d", "Foreign earned income exclusion from Form 2555"),
    ("e", "Income from Form 8853"),
    ("f", "Income from Form 8889"),
    ("g", "Alaska Permanent Fund dividends"),
    ("h", "Jury duty pay"),
    ("i", "Prizes and awards"),
    ("j", "Activity not engaged in for profit income"),
    ("k", "Stock options"),
    ("l", "Income from the rental of personal property"),
    ("m", "Olympic and Paralympic medals and USOC prize money"),
    ("n", "Section 951(a) inclusion"),
    ("o", "Section 951A(a) inclusion"),
    ("p", "Section 461(l) excess business loss adjustment"),
    ("q", "Taxable distributions from an ABLE account"),
    ("r", "Scholarship and fellowship grants not reported on Form W-2"),
    ("s", "Nontaxable amount of Medicaid waiver payments on Form 1040 line 1a or 1d"),
    ("t", "Pension or annuity from a nonqualified deferred compensation plan"),
    ("u", "Wages earned while incarcerated"),
    ("v", "Digital assets received as ordinary income not reported elsewhere"),
    ("z", "Other income. List type and amount"),
)

#: Line 24a-24z, "Other adjustments".
OTHER_ADJUSTMENTS: tuple[tuple[str, str], ...] = (
    ("a", "Jury duty pay"),
    ("b", "Deductible expenses related to income from the rental of personal property"),
    ("c", "Nontaxable amount of the value of Olympic and Paralympic medals"),
    ("d", "Reforestation amortization and expenses"),
    ("e", "Repayment of supplemental unemployment benefits under the Trade Act of 1974"),
    ("f", "Contributions to section 501(c)(18)(D) pension plans"),
    ("g", "Contributions by certain chaplains to section 403(b) plans"),
    ("h", "Attorney fees and court costs for unlawful discrimination claims"),
    ("i", "Attorney fees and court costs in connection with an IRS award"),
    ("j", "Housing deduction from Form 2555"),
    ("k", "Excess deductions of section 67(e) expenses from Schedule K-1"),
    ("z", "Other adjustments. List type and amount"),
)


def build(facts: TaxpayerFacts) -> list[Node]:
    nodes: list[Node] = []
    add = nodes.append

    # -- Part I, Additional Income --------------------------------------

    # Above Part I and deliberately outside the line 10 sum: the 1099-K
    # reconciliation entry is a disclosure of amounts reported elsewhere, and
    # adding it would double-count income already on another line.
    add(direct(FORM, KEY, "1099k", "Form 1099-K amounts reported in error (reconciliation)"))

    add(direct(FORM, KEY, "1", "Taxable refunds, credits, or offsets of state and local income taxes"))
    add(direct(FORM, KEY, "2a", "Alimony received"))
    add(from_form(FORM, KEY, "3", "Business income or (loss). Attach Schedule C", "Schedule C"))
    add(direct(FORM, KEY, "4", "Other gains or (losses)"))
    add(from_form(FORM, KEY, "5",
                  "Rental real estate, royalties, partnerships, S corporations, trusts",
                  "Schedule E"))
    add(from_form(FORM, KEY, "6", "Farm income or (loss). Attach Schedule F", "Schedule F"))
    add(direct(FORM, KEY, "7", "Unemployment compensation"))

    nodes.extend(lettered(FORM, KEY, "8", OTHER_INCOME))
    add(subtotal(FORM, KEY, "9", "Total other income. Add lines 8a through 8z",
                 tuple(f"8{letter}" for letter, _ in OTHER_INCOME)))

    # 1 through 7 and 9 - not 1 through 9. 8a-8z roll up through 9.
    add(subtotal(FORM, KEY, "10",
                 "Combine lines 1 through 7 and 9. This is your additional income",
                 ("1", "2a", "3", "4", "5", "6", "7", "9")))

    # -- Part II, Adjustments to Income ---------------------------------

    add(direct(FORM, KEY, "11", "Educator expenses"))
    add(direct(FORM, KEY, "12",
               "Certain business expenses of reservists, performing artists, and fee-basis officials"))
    add(carried(FORM, KEY, "13",
                "Health savings account deduction. Attach Form 8889", "f8889.l13"))
    add(from_form(FORM, KEY, "14",
                  "Moving expenses for members of the Armed Forces. Attach Form 3903",
                  "Form 3903"))
    add(from_form(FORM, KEY, "15",
                  "Deductible part of self-employment tax. Attach Schedule SE",
                  "Schedule SE"))
    add(direct(FORM, KEY, "16", "Self-employed SEP, SIMPLE, and qualified plans"))
    add(direct(FORM, KEY, "17", "Self-employed health insurance deduction"))
    add(direct(FORM, KEY, "18", "Penalty on early withdrawal of savings"))
    add(direct(FORM, KEY, "19a", "Alimony paid"))
    add(direct(FORM, KEY, "20", "IRA deduction"))
    add(direct(FORM, KEY, "21", "Student loan interest deduction"))
    add(reserved(FORM, KEY, "22"))
    add(direct(FORM, KEY, "23", "Archer MSA deduction"))

    nodes.extend(lettered(FORM, KEY, "24", OTHER_ADJUSTMENTS))
    add(subtotal(FORM, KEY, "25", "Total other adjustments. Add lines 24a through 24z",
                 tuple(f"24{letter}" for letter, _ in OTHER_ADJUSTMENTS)))

    add(subtotal(FORM, KEY, "26",
                 "Add lines 11 through 23 and 25. These are your adjustments to income",
                 ("11", "12", "13", "14", "15", "16", "17", "18", "19a",
                  "20", "21", "22", "23", "25")))

    return nodes


register_form(FORM, build)
