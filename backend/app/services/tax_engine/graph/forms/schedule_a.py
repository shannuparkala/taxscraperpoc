"""Schedule A (Form 1040) 2025 - Itemized Deductions.

Line wording from ``docs/tax-research/schedule-a-8889-qdcgt-2025-line-by-line.md``,
read off the primary PDF.

Line 17 feeds Form 1040 line 12e when the taxpayer itemizes.

**The SALT cap on line 5e is a 2025 figure, not the one people remember.** The
$10,000 cap is gone: OBBBA put it at $40,000 ($20,000 married filing
separately) under IRC 164(b)(7), phasing down at 30% of modified AGI over
$500,000 ($250,000 MFS) but never below $10,000 ($5,000). A return computed on
the old cap understates the deduction by up to $30,000 and looks entirely
ordinary.

**Line 5e has a second gate that is not about income at all.** Form 2555, Form
4563 or excluded Puerto Rico income means the phase-out worksheet applies
however far below the threshold modified AGI sits, because those exclusions are
added back for this test. The engine does not compute those exclusions, so a
return carrying one flags line 5e rather than quietly applying the full cap.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tax_engine.computations import medical_deduction, salt_cap_for
from app.services.tax_engine.graph.engine import register_form
from app.services.tax_engine.graph.evaluator import Ctx, fmt
from app.services.tax_engine.graph.facts import TaxpayerFacts
from app.services.tax_engine.graph.forms._common import (
    direct,
    node_id,
    reserved,
    subtotal,
)
from app.services.tax_engine.graph.nodes import ZERO, Node
from app.services.tax_engine.tax_tables import FilingStatusTax as Status

FORM = "Schedule A"
KEY = "scha"


def _n(line: str, label: str, compute, inputs: tuple[str, ...] = ()) -> Node:
    return Node(id=node_id(KEY, line), form=FORM, line=line, label=label,
                compute=compute, inputs=inputs)


def build(facts: TaxpayerFacts) -> list[Node]:
    year = facts.tax_year
    status = facts.filing_status
    mfs = status is Status.MARRIED_SEPARATE

    nodes: list[Node] = []
    add = nodes.append

    # -- Medical and Dental Expenses ------------------------------------

    add(direct(FORM, KEY, "1", "Medical and dental expenses"))

    def line_2(ctx: Ctx) -> Decimal:
        agi = ctx["f1040.l11b"]
        ctx.explain(f"{fmt(agi)} of adjusted gross income from Form 1040 line 11b")
        return agi

    add(_n("2", "Enter amount from Form 1040 line 11b", line_2, ("f1040.l11b",)))

    def line_3(ctx: Ctx) -> Decimal:
        agi = ctx["scha.l2"]
        floor_rate = ctx["const.medical_agi_floor"]
        floor = agi * floor_rate
        ctx.explain(f"{fmt(agi)} x 7.5% = {fmt(floor)}")
        return floor

    add(_n("3", "Multiply line 2 by 7.5% (0.075)", line_3,
           ("scha.l2", "const.medical_agi_floor")))

    def line_4(ctx: Ctx) -> Decimal:
        expenses, floor = ctx["scha.l1"], ctx["scha.l3"]
        allowed = medical_deduction(expenses, ctx["scha.l2"], year)
        ctx.explain(
            f"{fmt(expenses)} - {fmt(floor)} = {fmt(allowed)}"
            if allowed > ZERO
            else f"{fmt(floor)} of floor exceeds {fmt(expenses)} of expenses, so -0-"
        )
        return allowed

    add(_n("4", "Subtract line 3 from line 1. If line 3 is more than line 1, enter -0-",
           line_4, ("scha.l1", "scha.l2", "scha.l3")))

    # -- Taxes You Paid --------------------------------------------------

    add(direct(FORM, KEY, "5a",
               "State and local income taxes or general sales taxes (one or the other, not both)"))
    add(direct(FORM, KEY, "5b", "State and local real estate taxes"))
    add(direct(FORM, KEY, "5c", "State and local personal property taxes"))
    add(subtotal(FORM, KEY, "5d", "Add lines 5a through 5c", ("5a", "5b", "5c")))

    def line_5e(ctx: Ctx) -> Decimal:
        paid = ctx["scha.l5d"]
        modified_agi = ctx["f1040.l11b"]
        cap = salt_cap_for(year, status, modified_agi)
        allowed = min(paid, cap)
        threshold = ctx[
            "const.salt_phasedown_threshold_mfs" if mfs
            else "const.salt_phasedown_threshold"
        ]
        base_cap = ctx[
            "const.salt_cap_married_separate" if mfs else "const.salt_cap"
        ]
        if cap < base_cap:
            ctx.explain(
                f"the {fmt(base_cap)} cap phases down at 30% of the "
                f"{fmt(modified_agi - threshold)} by which modified AGI exceeds "
                f"{fmt(threshold)}, to {fmt(cap)}; smaller of that and "
                f"{fmt(paid)} paid = {fmt(allowed)}"
            )
        else:
            ctx.explain(
                f"smaller of {fmt(paid)} paid and the {fmt(cap)} cap = {fmt(allowed)}"
            )
        return allowed

    add(_n("5e",
           "Enter the smaller of line 5d or $40,000 ($20,000 if married filing separately)",
           line_5e,
           ("scha.l5d", "f1040.l11b", "const.salt_cap",
            "const.salt_cap_married_separate", "const.salt_phasedown_threshold",
            "const.salt_phasedown_threshold_mfs")))

    add(direct(FORM, KEY, "6", "Other taxes. List type and amount"))
    add(subtotal(FORM, KEY, "7", "Add lines 5e and 6", ("5e", "6")))

    # -- Interest You Paid -----------------------------------------------

    add(direct(FORM, KEY, "8a", "Home mortgage interest and points reported to you on Form 1098"))
    add(direct(FORM, KEY, "8b", "Home mortgage interest not reported to you on Form 1098"))
    add(direct(FORM, KEY, "8c", "Points not reported to you on Form 1098"))
    add(reserved(FORM, KEY, "8d"))
    add(subtotal(FORM, KEY, "8e", "Add lines 8a through 8c", ("8a", "8b", "8c")))
    add(direct(FORM, KEY, "9", "Investment interest. Attach Form 4952 if required"))
    add(subtotal(FORM, KEY, "10", "Add lines 8e and 9", ("8e", "9")))

    # -- Gifts to Charity -------------------------------------------------

    add(direct(FORM, KEY, "11", "Gifts by cash or check"))
    add(direct(FORM, KEY, "12", "Gifts other than by cash or check"))
    add(direct(FORM, KEY, "13", "Carryover from prior year"))
    add(subtotal(FORM, KEY, "14", "Add lines 11 through 13", ("11", "12", "13")))

    # -- Casualty, other, total -------------------------------------------

    add(direct(FORM, KEY, "15",
               "Casualty and theft loss(es) from a federally declared disaster. Attach Form 4684"))
    add(direct(FORM, KEY, "16", "Other itemized deductions. List type and amount"))
    add(subtotal(FORM, KEY, "17",
                 "Add the amounts in the far right column for lines 4 through 16. "
                 "These are your total itemized deductions",
                 ("4", "7", "10", "14", "15", "16")))

    def line_18(ctx: Ctx) -> Decimal:
        ctx.explain(
            "the election to itemize even though the total is less than the "
            "standard deduction; a checkbox, not a figure"
        )
        return ZERO

    add(_n("18", "Election to itemize deductions that are less than the standard deduction",
           line_18))

    return nodes


register_form(FORM, build)
