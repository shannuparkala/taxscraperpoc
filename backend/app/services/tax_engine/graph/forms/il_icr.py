"""Schedule ICR (2025) - Illinois Credits.

Line wording from ``docs/tax-research/il-1040-icr-il-wit-2025-line-by-line.md``,
read off the primary PDF (R-12/25).

Line 13 feeds IL-1040 line 16.

**Every credit on this schedule is nonrefundable and they queue.** Line 3 is
the tax available to absorb them; each credit takes the lesser of itself and
what is left, and lines 6, 9 and 12 carry the remaining room forward to the
next credit. Computing each credit against the full tax instead of the
remaining room lets the three together exceed the tax, which produces a
refund Illinois does not give.

**The K-12 credit has a floor, a rate and a cap, in that order.** The first
$250 of expense earns nothing, a quarter of the rest is the credit, and the
credit stops at $750. Applying the cap before the floor, or the rate to the
whole expense, are both wrong and both land near enough to look right.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tax_engine.graph.engine import register_form
from app.services.tax_engine.graph.evaluator import Ctx, fmt
from app.services.tax_engine.graph.facts import MONEY_FIELDS, TaxpayerFacts
from app.services.tax_engine.graph.forms._common import direct, node_id, subtotal
from app.services.tax_engine.graph.nodes import ZERO, Node

FORM = "Schedule ICR"
KEY = "ilicr"
STATE = "IL"

MONEY_FIELDS.setdefault(
    "ilicr_volunteer_certificates",
    "Schedule ICR line 10a/10b - number of volunteer emergency worker "
    "certificates held (0, 1 or 2)",
)


def _n(line: str, label: str, compute, inputs: tuple[str, ...] = ()) -> Node:
    return Node(id=node_id(KEY, line), form=FORM, line=line, label=label,
                compute=compute, inputs=inputs)


def build(facts: TaxpayerFacts) -> list[Node]:
    if not facts.files_in(STATE):
        return []

    nodes: list[Node] = []
    add = nodes.append

    def line_1(ctx: Ctx) -> Decimal:
        amount = ctx["il1040.l14"]
        ctx.explain(f"{fmt(amount)} of Illinois income tax from IL-1040 line 14")
        return amount

    add(_n("1", "Enter the amount of tax from your Form IL-1040, Line 14", line_1,
           ("il1040.l14",)))

    add(direct(FORM, KEY, "2",
               "Credit for tax paid to other states from IL-1040 Line 15"))

    def line_3(ctx: Ctx) -> Decimal:
        remaining = ctx["ilicr.l1"] - ctx["ilicr.l2"]
        return ctx.floor_at_zero(
            remaining, because=f"{fmt(ctx['ilicr.l1'])} - {fmt(ctx['ilicr.l2'])}"
        )

    add(_n("3", "Subtract Line 2 from Line 1", line_3, ("ilicr.l1", "ilicr.l2")))

    # -- Property tax credit ---------------------------------------------

    add(direct(FORM, KEY, "4a", "Total Illinois Property Tax paid during the tax year"))
    add(direct(FORM, KEY, "4e",
               "Portion of the tax bill deductible as a business expense"))

    def line_4f(ctx: Ctx) -> Decimal:
        return ctx.less("ilicr.l4a", "ilicr.l4e")

    add(_n("4f", "Subtract Line 4e from Line 4a", line_4f, ("ilicr.l4a", "ilicr.l4e")))

    def line_4g(ctx: Ctx) -> Decimal:
        base = ctx["ilicr.l4f"]
        rate = ctx["const.il_property_tax_credit_rate"]
        credit = base * rate
        ctx.explain(f"{fmt(base)} x 5% = {fmt(credit)}")
        return credit

    add(_n("4g", "Multiply Line 4f by 5% (.05)", line_4g,
           ("ilicr.l4f", "const.il_property_tax_credit_rate")))

    add(_n("5", "Compare Lines 3 and 4g, and enter the lesser amount here",
           lambda ctx: ctx.lesser_of("ilicr.l3", "ilicr.l4g"),
           ("ilicr.l3", "ilicr.l4g")))

    def line_6(ctx: Ctx) -> Decimal:
        remaining = ctx["ilicr.l3"] - ctx["ilicr.l5"]
        return ctx.floor_at_zero(
            remaining, because=f"{fmt(ctx['ilicr.l3'])} - {fmt(ctx['ilicr.l5'])}"
        )

    add(_n("6", "Subtract Line 5 from Line 3", line_6, ("ilicr.l3", "ilicr.l5")))

    # -- K-12 education expense credit ------------------------------------

    add(direct(FORM, KEY, "7a", "Total K-12 education expenses from the worksheet"))

    def line_7b(ctx: Ctx) -> Decimal:
        floor = ctx["const.il_k12_credit_floor"]
        ctx.explain(f"{fmt(floor)}, which earns no credit")
        return floor

    add(_n("7b", "You may not take a credit for the first $250 paid", line_7b,
           ("const.il_k12_credit_floor",)))

    def line_7c(ctx: Ctx) -> Decimal:
        remaining = ctx["ilicr.l7a"] - ctx["ilicr.l7b"]
        return ctx.floor_at_zero(
            remaining, because=f"{fmt(ctx['ilicr.l7a'])} - {fmt(ctx['ilicr.l7b'])}"
        )

    add(_n("7c", "Subtract Line 7b from Line 7a. If the result is negative, enter -0-",
           line_7c, ("ilicr.l7a", "ilicr.l7b")))

    def line_7d(ctx: Ctx) -> Decimal:
        base = ctx["ilicr.l7c"]
        rate = ctx["const.il_k12_credit_rate"]
        cap = ctx["const.il_k12_credit_cap"]
        credit = min(base * rate, cap)
        ctx.explain(
            f"{fmt(base)} x 25% = {fmt(base * rate)}, capped at {fmt(cap)} "
            f"= {fmt(credit)}"
        )
        return credit

    add(_n("7d", "Multiply Line 7c by 25% (.25). Compare the result and $750, "
           "and enter the lesser amount", line_7d,
           ("ilicr.l7c", "const.il_k12_credit_rate", "const.il_k12_credit_cap")))

    add(_n("8", "Compare Lines 6 and 7d, and enter the lesser amount here",
           lambda ctx: ctx.lesser_of("ilicr.l6", "ilicr.l7d"),
           ("ilicr.l6", "ilicr.l7d")))

    def line_9(ctx: Ctx) -> Decimal:
        remaining = ctx["ilicr.l6"] - ctx["ilicr.l8"]
        return ctx.floor_at_zero(
            remaining, because=f"{fmt(ctx['ilicr.l6'])} - {fmt(ctx['ilicr.l8'])}"
        )

    add(_n("9", "Subtract Line 8 from Line 6", line_9, ("ilicr.l6", "ilicr.l8")))

    # -- Volunteer emergency worker credit ---------------------------------

    def line_10c(ctx: Ctx) -> Decimal:
        holders = facts.money.get("ilicr_volunteer_certificates") or ZERO
        if holders <= ZERO:
            ctx.explain("no volunteer emergency worker certificate, so -0-")
            return ZERO
        amount = ctx["const.il_volunteer_emergency_worker_credit"]
        ctx.explain(f"{fmt(amount)} for a certificated volunteer emergency worker")
        return amount

    add(_n("10c", "Enter $500.00 if you, or your spouse if filing jointly, hold a "
           "volunteer emergency worker certificate", line_10c,
           ("const.il_volunteer_emergency_worker_credit",)))

    add(_n("11", "Compare Lines 9 and 10c, and enter the lesser amount here",
           lambda ctx: ctx.lesser_of("ilicr.l9", "ilicr.l10c"),
           ("ilicr.l9", "ilicr.l10c")))

    def line_12(ctx: Ctx) -> Decimal:
        remaining = ctx["ilicr.l9"] - ctx["ilicr.l11"]
        return ctx.floor_at_zero(
            remaining, because=f"{fmt(ctx['ilicr.l9'])} - {fmt(ctx['ilicr.l11'])}"
        )

    add(_n("12", "Subtract Line 11 from Line 9", line_12, ("ilicr.l9", "ilicr.l11")))

    add(subtotal(FORM, KEY, "13",
                 "Add Lines 5, 8, and 11. This is your nonrefundable credit amount",
                 ("5", "8", "11")))

    return nodes


register_form(FORM, build)
