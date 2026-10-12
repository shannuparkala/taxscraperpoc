"""Schedule 2 (Form 1040) 2025 - Additional Taxes.

Line wording and routing from
``docs/tax-research/schedule-1-2-3-2025-line-by-line.md``, read off the primary
PDF (Cat. No. 71478U, created 5/8/25 - which is before OBBBA, so anything this
schedule points at under the Act is worth checking at the form it points to).

Part I line 3 feeds Form 1040 line 17. Part II line 21 feeds Form 1040 line 23.

**Line 21 deliberately skips line 20.** Its own wording is "Add lines 4, 7
through 16, 18, and 19" - the section 965 installment on line 20 is reported
there and settled separately, not added into total other taxes. Summing 4
through 20 looks like the obvious reading and overstates the tax.
"""

from __future__ import annotations

from app.services.tax_engine.graph.engine import register_form
from app.services.tax_engine.graph.facts import TaxpayerFacts
from app.services.tax_engine.graph.forms._common import (
    direct,
    from_form,
    lettered,
    reserved,
    subtotal,
)
from app.services.tax_engine.graph.nodes import Node

FORM = "Schedule 2"
KEY = "sch2"

#: Line 1a-1y, "Additions to tax".
ADDITIONS: tuple[tuple[str, str], ...] = (
    ("a", "Excess advance premium tax credit repayment. Attach Form 8962"),
    ("b", "Repayment of new clean vehicle credit(s) transferred to a registered dealer"),
    ("c", "Repayment of previously owned clean vehicle credit(s) transferred to a dealer"),
    ("d", "Recapture of net EPE from Form 4255, line 2a, column (l)"),
    ("e", "Excessive payments (EPs) on gross EPE from Form 4255"),
    ("f", "20% EP from Form 4255"),
    ("y", "Other additions to tax"),
)

#: Line 17a-17z, "Other additional taxes".
OTHER_TAXES: tuple[tuple[str, str], ...] = (
    ("a", "Recapture of other credits"),
    ("b", "Recapture of federal mortgage subsidy"),
    ("c", "Additional tax on HSA distributions. Attach Form 8889"),
    ("d", "Additional tax on an HSA because you didn't remain an eligible individual"),
    ("e", "Additional tax on Archer MSA distributions. Attach Form 8853"),
    ("f", "Additional tax on Medicare Advantage MSA distributions. Attach Form 8853"),
    ("g", "Recapture of a charitable contribution deduction (fractional interest)"),
    ("h", "Income from a nonqualified deferred compensation plan that fails section 409A"),
    ("i", "Compensation from a nonqualified deferred compensation plan (section 457A)"),
    ("j", "Section 72(m)(5) excess benefits tax"),
    ("k", "Golden parachute payments"),
    ("l", "Tax on accumulation distribution of trusts"),
    ("m", "Excise tax on insider stock compensation from an expatriated corporation"),
    ("n", "Look-back interest under section 167(g) or 460(b) from Form 8697 or 8866"),
    ("o", "Tax on non-effectively connected income for a nonresident alien period"),
    ("p", "Interest from Form 8621, line 16f"),
    ("q", "Interest from Form 8621, line 24"),
    ("z", "Any other taxes. List type and amount"),
)


def build(facts: TaxpayerFacts) -> list[Node]:
    nodes: list[Node] = []
    add = nodes.append

    # -- Part I, Tax ----------------------------------------------------

    nodes.extend(lettered(FORM, KEY, "1", ADDITIONS))
    add(subtotal(FORM, KEY, "1z", "Add lines 1a through 1y",
                 tuple(f"1{letter}" for letter, _ in ADDITIONS)))
    add(from_form(FORM, KEY, "2",
                  "Alternative minimum tax. Attach Form 6251", "Form 6251"))
    add(subtotal(FORM, KEY, "3", "Add lines 1z and 2", ("1z", "2")))

    # -- Part II, Other Taxes -------------------------------------------

    add(from_form(FORM, KEY, "4",
                  "Self-employment tax. Attach Schedule SE", "Schedule SE"))
    add(from_form(FORM, KEY, "5",
                  "Social security and Medicare tax on unreported tip income. Attach Form 4137",
                  "Form 4137"))
    add(from_form(FORM, KEY, "6",
                  "Uncollected social security and Medicare tax on wages. Attach Form 8919",
                  "Form 8919"))
    add(subtotal(FORM, KEY, "7",
                 "Total additional social security and Medicare tax. Add lines 5 and 6",
                 ("5", "6")))
    add(from_form(FORM, KEY, "8",
                  "Additional tax on IRAs or other tax-favored accounts. Attach Form 5329",
                  "Form 5329"))
    add(from_form(FORM, KEY, "9",
                  "Household employment taxes. Attach Schedule H", "Schedule H"))
    add(reserved(FORM, KEY, "10"))
    add(from_form(FORM, KEY, "11",
                  "Additional Medicare Tax. Attach Form 8959", "Form 8959"))
    add(from_form(FORM, KEY, "12",
                  "Net investment income tax. Attach Form 8960", "Form 8960"))
    add(direct(FORM, KEY, "13",
               "Uncollected social security and Medicare or RRTA tax on tips or group-term life"))
    add(direct(FORM, KEY, "14",
               "Interest on tax due on installment income from the sale of certain residential lots"))
    add(direct(FORM, KEY, "15",
               "Interest on the deferred tax on gain from certain installment sales over $150,000"))
    add(from_form(FORM, KEY, "16",
                  "Recapture of low-income housing credit. Attach Form 8611", "Form 8611"))

    nodes.extend(lettered(FORM, KEY, "17", OTHER_TAXES))
    add(subtotal(FORM, KEY, "18", "Total additional taxes. Add lines 17a through 17z",
                 tuple(f"17{letter}" for letter, _ in OTHER_TAXES)))

    add(from_form(FORM, KEY, "19",
                  "Recapture of net EPE from Form 4255, line 1d, column (l)", "Form 4255"))
    add(from_form(FORM, KEY, "20",
                  "Section 965 net tax liability installment from Form 965-A", "Form 965-A"))

    # "Add lines 4, 7 through 16, 18, and 19" - line 20 is not in the sum.
    add(subtotal(FORM, KEY, "21",
                 "Add lines 4, 7 through 16, 18, and 19. These are your total other taxes",
                 ("4", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16",
                  "18", "19")))

    return nodes


register_form(FORM, build)
