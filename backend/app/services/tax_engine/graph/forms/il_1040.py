"""Form IL-1040 (2025) - Illinois Individual Income Tax Return.

Line wording from ``docs/tax-research/il-1040-icr-il-wit-2025-line-by-line.md``,
read off the primary PDF (R-12/25).

Line 1 takes federal adjusted gross income straight off Form 1040 line 11a, so
every federal figure that moves AGI moves the Illinois tax too. Schedule ICR
line 13 feeds line 16; Schedule IL-WIT line 11 feeds line 25.

**The exemption allowance is a cliff, not a taper.** $2,850 ($5,700 filing
jointly) drops to nothing the moment federal AGI passes $250,000 ($500,000
jointly). There is no phase-out range: a dollar of extra income at the
threshold costs the whole allowance, which is the kind of edge a test has to
sit exactly on.

**Line 12 cannot be less than zero and neither can line 14.** Illinois says so
on the form face. A negative base income produces no refund of tax never paid.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tax_engine.graph.engine import register_form
from app.services.tax_engine.graph.evaluator import Ctx, fmt
from app.services.tax_engine.graph.facts import TaxpayerFacts
from app.services.tax_engine.graph.forms._common import (
    carried,
    direct,
    node_id,
    subtotal,
)
from app.services.tax_engine.graph.nodes import ZERO, Node

FORM = "Form IL-1040"
KEY = "il1040"
STATE = "IL"


def _n(line: str, label: str, compute, inputs: tuple[str, ...] = ()) -> Node:
    return Node(id=node_id(KEY, line), form=FORM, line=line, label=label,
                compute=compute, inputs=inputs)


def build(facts: TaxpayerFacts) -> list[Node]:
    if not facts.files_in(STATE):
        return []

    joint = facts.is_joint
    exemption_key = (
        "const.il_exemption_allowance_joint" if joint
        else "const.il_exemption_allowance"
    )
    cutoff_key = (
        "const.il_exemption_cutoff_agi_joint" if joint
        else "const.il_exemption_cutoff_agi"
    )

    nodes: list[Node] = []
    add = nodes.append

    # -- Step 2, Income ---------------------------------------------------

    add(carried(FORM, KEY, "1",
                "Federal adjusted gross income from your federal Form 1040, Line 11a",
                "f1040.l11a"))
    add(direct(FORM, KEY, "2",
               "Federally tax-exempt interest and dividend income"))
    add(direct(FORM, KEY, "3", "Other additions. Attach Schedule M"))
    add(subtotal(FORM, KEY, "4", "Total income. Add Lines 1 through 3", ("1", "2", "3")))

    # -- Step 3, Base Income ----------------------------------------------

    add(direct(FORM, KEY, "5",
               "Social Security benefits and certain retirement plan income "
               "included in Line 1"))
    add(direct(FORM, KEY, "6",
               "Illinois Income Tax overpayment included in federal Form 1040"))
    add(direct(FORM, KEY, "7", "Other subtractions. Attach Schedule M"))
    add(subtotal(FORM, KEY, "8",
                 "Add Lines 5, 6, and 7. This is the total of your subtractions",
                 ("5", "6", "7")))

    def line_9(ctx: Ctx) -> Decimal:
        return ctx.less("il1040.l4", "il1040.l8")

    add(_n("9", "Illinois base income. Subtract Line 8 from Line 4", line_9,
           ("il1040.l4", "il1040.l8")))

    # -- Step 4, Exemptions ------------------------------------------------

    def line_10a(ctx: Ctx) -> Decimal:
        federal_agi = ctx["f1040.l11a"]
        cutoff = ctx[cutoff_key]
        allowance = ctx[exemption_key]
        if federal_agi > cutoff:
            ctx.explain(
                f"federal AGI of {fmt(federal_agi)} is above {fmt(cutoff)}, so "
                f"the {fmt(allowance)} exemption allowance is not available"
            )
            return ZERO
        ctx.explain(
            f"{fmt(allowance)} exemption allowance, available because federal "
            f"AGI of {fmt(federal_agi)} does not exceed {fmt(cutoff)}"
        )
        return allowance

    add(_n("10a", "Exemption amount for yourself and your spouse", line_10a,
           ("f1040.l11a", exemption_key, cutoff_key)))

    def _boxes(count: int):
        def compute(ctx: Ctx) -> Decimal:
            per_box = ctx["const.il_exemption_age_or_blind"]
            amount = per_box * count
            ctx.explain(f"{count} box(es) x {fmt(per_box)} = {fmt(amount)}")
            return amount

        return compute

    add(_n("10b", "Check if 65 or older: number of checkboxes x $1,000",
           _boxes(facts.seniors), ("const.il_exemption_age_or_blind",)))
    add(_n("10c", "Check if legally blind: number of checkboxes x $1,000",
           _boxes(facts.blind_count), ("const.il_exemption_age_or_blind",)))
    add(direct(FORM, KEY, "10d",
               "Dependent exemption from Schedule IL-E/EITC"))
    add(subtotal(FORM, KEY, "10", "Exemption allowance. Add Lines 10a through 10d",
                 ("10a", "10b", "10c", "10d")))

    # -- Step 5, Net Income and Tax ----------------------------------------

    def line_11(ctx: Ctx) -> Decimal:
        net = ctx["il1040.l9"] - ctx["il1040.l10"]
        return ctx.floor_at_zero(
            net, because=f"{fmt(ctx['il1040.l9'])} - {fmt(ctx['il1040.l10'])}"
        )

    add(_n("11", "Net income. Subtract Line 10 from Line 9", line_11,
           ("il1040.l9", "il1040.l10")))

    def line_12(ctx: Ctx) -> Decimal:
        net = ctx["il1040.l11"]
        rate = ctx["const.il_flat_rate"]
        tax = net * rate
        tax = max(tax, ZERO)
        ctx.explain(f"{fmt(net)} x 4.95% = {fmt(tax)}")
        return tax

    add(_n("12", "Multiply Line 11 by 4.95% (.0495). Cannot be less than zero",
           line_12, ("il1040.l11", "const.il_flat_rate")))

    add(direct(FORM, KEY, "13",
               "Recapture of investment tax credits. Attach Schedule 4255"))

    def line_14(ctx: Ctx) -> Decimal:
        tax = ctx["il1040.l12"] + ctx["il1040.l13"]
        return ctx.floor_at_zero(
            tax, because=f"{fmt(ctx['il1040.l12'])} + {fmt(ctx['il1040.l13'])}"
        )

    add(_n("14", "Income tax. Add Lines 12 and 13. Cannot be less than zero",
           line_14, ("il1040.l12", "il1040.l13")))

    # -- Step 6, Tax After Nonrefundable Credits ---------------------------

    add(direct(FORM, KEY, "15",
               "Income tax paid to another state while an Illinois resident"))
    add(carried(FORM, KEY, "16",
                "Property tax, K-12 education expense, and volunteer emergency "
                "worker credits from Schedule ICR",
                "ilicr.l13"))
    add(direct(FORM, KEY, "17", "Credit amount from Schedule 1299-C"))

    def line_18(ctx: Ctx) -> Decimal:
        total = ctx.total("il1040.l15", "il1040.l16", "il1040.l17")
        available = ctx["il1040.l14"]
        if total > available:
            ctx.explain(
                f"credits of {fmt(total)} exceed the {fmt(available)} of tax "
                "they can offset, so they are limited to the tax"
            )
            return available
        return total

    add(_n("18", "Add Lines 15, 16, and 17. Cannot exceed Line 14", line_18,
           ("il1040.l15", "il1040.l16", "il1040.l17", "il1040.l14")))

    def line_19(ctx: Ctx) -> Decimal:
        remaining = ctx["il1040.l14"] - ctx["il1040.l18"]
        return ctx.floor_at_zero(
            remaining, because=f"{fmt(ctx['il1040.l14'])} - {fmt(ctx['il1040.l18'])}"
        )

    add(_n("19", "Tax after nonrefundable credits. Subtract Line 18 from Line 14",
           line_19, ("il1040.l14", "il1040.l18")))

    # -- Step 7, Other Taxes ------------------------------------------------

    add(direct(FORM, KEY, "20", "Household employment tax"))
    add(direct(FORM, KEY, "21",
               "Use tax on internet, mail order, or other out-of-state purchases"))
    add(direct(FORM, KEY, "22",
               "Compassionate Use of Medical Cannabis Program Act and sale of "
               "assets by gaming licensee surcharges"))
    add(subtotal(FORM, KEY, "23", "Total Tax. Add Lines 19, 20, 21, and 22",
                 ("19", "20", "21", "22")))

    # -- Step 8, Payments and Refundable Credit ----------------------------

    add(carried(FORM, KEY, "24", "Total tax from Page 1, Line 23", "il1040.l23"))
    add(carried(FORM, KEY, "25",
                "Illinois Income Tax withheld. Attach Schedule IL-WIT", "ilwit.l11"))
    add(direct(FORM, KEY, "26",
               "Estimated payments from Forms IL-1040-ES and IL-505-I"))
    add(direct(FORM, KEY, "27",
               "Pass-through withholding. Attach Schedule K-1-P or K-1-T"))
    add(direct(FORM, KEY, "28",
               "Pass-through entity tax credit. Attach Schedule K-1-P or K-1-T"))
    add(direct(FORM, KEY, "29",
               "Earned Income Tax credit from Schedule IL-E/EITC"))
    add(direct(FORM, KEY, "30", "Child Tax credit from Schedule IL-E/EITC"))
    add(subtotal(FORM, KEY, "31",
                 "Total payments and refundable credit. Add Lines 25 through 30",
                 ("25", "26", "27", "28", "29", "30")))

    # -- Step 9, Total -------------------------------------------------------

    def line_32(ctx: Ctx) -> Decimal:
        paid, owed = ctx["il1040.l31"], ctx["il1040.l24"]
        if paid <= owed:
            ctx.explain(
                f"payments of {fmt(paid)} do not exceed the {fmt(owed)} of tax, "
                "so there is no overpayment"
            )
            return ZERO
        ctx.explain(f"{fmt(paid)} - {fmt(owed)} = {fmt(paid - owed)}")
        return paid - owed

    add(_n("32", "If Line 31 is greater than Line 24, subtract Line 24 from Line 31",
           line_32, ("il1040.l31", "il1040.l24")))

    def line_33(ctx: Ctx) -> Decimal:
        owed, paid = ctx["il1040.l24"], ctx["il1040.l31"]
        if owed <= paid:
            ctx.explain(
                f"the {fmt(owed)} of tax does not exceed payments of "
                f"{fmt(paid)}, so nothing is owed"
            )
            return ZERO
        ctx.explain(f"{fmt(owed)} - {fmt(paid)} = {fmt(owed - paid)}")
        return owed - paid

    add(_n("33", "If Line 24 is greater than Line 31, subtract Line 31 from Line 24",
           line_33, ("il1040.l24", "il1040.l31")))

    # -- Step 10, Penalty and Donations --------------------------------------

    add(direct(FORM, KEY, "34",
               "Late-payment penalty for underpayment of estimated tax"))
    add(direct(FORM, KEY, "35",
               "Voluntary charitable donations. Attach Schedule G"))
    add(subtotal(FORM, KEY, "36", "Total penalty and donations. Add Lines 34 and 35",
                 ("34", "35")))

    # -- Step 11, Refund or Amount You Owe -----------------------------------

    def line_37(ctx: Ctx) -> Decimal:
        overpaid, taken = ctx["il1040.l32"], ctx["il1040.l36"]
        remaining = overpaid - taken
        if remaining <= ZERO:
            ctx.explain(
                f"the {fmt(taken)} of penalty and donations absorbs the whole "
                f"{fmt(overpaid)} overpayment"
            )
            return ZERO
        ctx.explain(f"{fmt(overpaid)} - {fmt(taken)} = {fmt(remaining)}")
        return remaining

    add(_n("37", "Overpayment remaining after penalty and donations", line_37,
           ("il1040.l32", "il1040.l36")))

    add(direct(FORM, KEY, "38", "Amount from Line 37 you want refunded to you"))

    def line_40(ctx: Ctx) -> Decimal:
        remaining = ctx["il1040.l37"] - ctx["il1040.l38"]
        return ctx.floor_at_zero(
            remaining, because=f"{fmt(ctx['il1040.l37'])} - {fmt(ctx['il1040.l38'])}"
        )

    add(_n("40", "Amount to be credited forward. Subtract Line 38 from Line 37",
           line_40, ("il1040.l37", "il1040.l38")))

    def line_41(ctx: Ctx) -> Decimal:
        return ctx.total("il1040.l33", "il1040.l36")

    add(_n("41", "Amount you owe. Add Lines 33 and 36", line_41,
           ("il1040.l33", "il1040.l36")))

    return nodes


register_form(FORM, build)
