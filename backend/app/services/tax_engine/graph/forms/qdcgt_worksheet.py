"""Qualified Dividends and Capital Gain Tax Worksheet (2025) - Form 1040 line 16.

**Status of the line wording: verify.** This worksheet lives inside
``i1040gi.pdf``, which no tool in this environment could read past its first
pages, so unlike every other form here its line-by-line text was not pinned to
primary source. See the open questions in
``docs/tax-research/schedule-a-8889-qdcgt-2025-line-by-line.md``.

What *is* confirmed is the part that decides the number: the 2025 preferential
rate breakpoints, read off the Schedule D instructions
(0%/15%/20% at $48,350/$533,400 single, $96,700/$600,050 joint,
$48,350/$300,000 married filing separately, $64,750/$566,700 head of
household), and the fact that OBBBA did not touch them. The labels below
describe each step in the engine's own words rather than claiming to quote the
IRS, which is the honest way round: a made-up quotation of a line label reads
exactly like a real one.

**The qualified slice stacks on top of ordinary income.** It is not taxed at
the rate its own size would suggest - a small qualified dividend on a large
ordinary income is taxed at 15% or 20%, not 0%. Applying the brackets to the
qualified amount alone is the classic error, and it understates tax on exactly
the returns where the figure is large.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tax_engine.computations import (
    tax_table_lookup,
    tax_with_capital_gains,
)
from app.services.tax_engine.graph.engine import register_form
from app.services.tax_engine.graph.evaluator import Ctx, fmt
from app.services.tax_engine.graph.facts import TaxpayerFacts
from app.services.tax_engine.graph.forms._common import node_id
from app.services.tax_engine.graph.nodes import ZERO, Node
from app.services.tax_engine.tax_authority import constants_for

FORM = "Qualified Dividends and Capital Gain Tax Worksheet"
KEY = "qdcgtw"

#: How far the engine's own decomposition may sit from the reconciled
#: implementation before the line is flagged rather than trusted. One cent:
#: these are two routes to the same figure, not an estimate.
TOLERANCE = Decimal("0.01")


def _n(line: str, label: str, compute, inputs: tuple[str, ...] = ()) -> Node:
    return Node(id=node_id(KEY, line), form=FORM, line=line, label=label,
                compute=compute, inputs=inputs)


def _breakpoints(year: int, status) -> tuple[Decimal, Decimal]:
    """The taxable-income points where the 0% rate ends and 20% begins."""
    brackets = constants_for(year).capital_gain_brackets[status.value]
    zero_ends = brackets[0][1] or ZERO
    fifteen_ends = brackets[1][1] or ZERO
    return Decimal(zero_ends), Decimal(fifteen_ends)


def build(facts: TaxpayerFacts) -> list[Node]:
    year = facts.tax_year
    status = facts.filing_status
    zero_ends, fifteen_ends = _breakpoints(year, status)

    nodes: list[Node] = []
    add = nodes.append

    def line_1(ctx: Ctx) -> Decimal:
        amount = ctx["f1040.l15"]
        ctx.explain(f"{fmt(amount)} of taxable income from Form 1040 line 15")
        return amount

    add(_n("1", "Taxable income from Form 1040 line 15", line_1, ("f1040.l15",)))

    def line_2(ctx: Ctx) -> Decimal:
        amount = ctx["f1040.l3a"]
        ctx.explain(f"{fmt(amount)} of qualified dividends from Form 1040 line 3a")
        return amount

    add(_n("2", "Qualified dividends from Form 1040 line 3a", line_2, ("f1040.l3a",)))

    def line_3(ctx: Ctx) -> Decimal:
        long_term = ctx["schd.l15"]
        if long_term <= ZERO:
            ctx.explain(
                f"Schedule D line 15 is {fmt(long_term)}, not a net gain, so -0-"
            )
            return ZERO
        ctx.explain(f"{fmt(long_term)} of net long-term capital gain from Schedule D line 15")
        return long_term

    add(_n("3", "Net long-term capital gain from Schedule D line 15", line_3,
           ("schd.l15",)))

    def line_4(ctx: Ctx) -> Decimal:
        total = ctx.total("qdcgtw.l2", "qdcgtw.l3")
        return min(total, ctx["qdcgtw.l1"]) if total > ctx["qdcgtw.l1"] else total

    add(_n("4", "Total income taxed at preferential rates. Add lines 2 and 3", line_4,
           ("qdcgtw.l2", "qdcgtw.l3", "qdcgtw.l1")))

    def line_5(ctx: Ctx) -> Decimal:
        ordinary = ctx["qdcgtw.l1"] - ctx["qdcgtw.l4"]
        return ctx.floor_at_zero(
            ordinary, because=f"{fmt(ctx['qdcgtw.l1'])} - {fmt(ctx['qdcgtw.l4'])}"
        )

    add(_n("5", "Ordinary income. Subtract line 4 from line 1", line_5,
           ("qdcgtw.l1", "qdcgtw.l4")))

    def line_6(ctx: Ctx) -> Decimal:
        ordinary, qualified = ctx["qdcgtw.l5"], ctx["qdcgtw.l4"]
        headroom = zero_ends - ordinary
        at_zero = max(ZERO, min(qualified, headroom))
        ctx.explain(
            f"the 0% rate runs to {fmt(zero_ends)} of taxable income; "
            f"{fmt(ordinary)} of that is ordinary income, leaving "
            f"{fmt(max(ZERO, headroom))} of room, so {fmt(at_zero)} is taxed at 0%"
        )
        return at_zero

    add(_n("6", "Amount of the preferential income taxed at 0%", line_6,
           ("qdcgtw.l5", "qdcgtw.l4")))

    def line_7(ctx: Ctx) -> Decimal:
        ordinary, qualified = ctx["qdcgtw.l5"], ctx["qdcgtw.l4"]
        at_zero = ctx["qdcgtw.l6"]
        stacked_from = max(ordinary, zero_ends)
        headroom = fifteen_ends - stacked_from
        at_fifteen = max(ZERO, min(qualified - at_zero, headroom))
        ctx.explain(
            f"the 15% rate runs to {fmt(fifteen_ends)}; after {fmt(at_zero)} at "
            f"0% and {fmt(ordinary)} of ordinary income, {fmt(at_fifteen)} is "
            "taxed at 15%"
        )
        return at_fifteen

    add(_n("7", "Amount of the preferential income taxed at 15%", line_7,
           ("qdcgtw.l5", "qdcgtw.l4", "qdcgtw.l6")))

    def line_8(ctx: Ctx) -> Decimal:
        remainder = ctx["qdcgtw.l4"] - ctx["qdcgtw.l6"] - ctx["qdcgtw.l7"]
        at_twenty = max(ZERO, remainder)
        ctx.explain(
            f"{fmt(ctx['qdcgtw.l4'])} preferential income - {fmt(ctx['qdcgtw.l6'])} "
            f"at 0% - {fmt(ctx['qdcgtw.l7'])} at 15% = {fmt(at_twenty)} taxed at 20%"
        )
        return at_twenty

    add(_n("8", "Amount of the preferential income taxed at 20%", line_8,
           ("qdcgtw.l4", "qdcgtw.l6", "qdcgtw.l7")))

    def line_9(ctx: Ctx) -> Decimal:
        ordinary = ctx["qdcgtw.l5"]
        if ordinary <= ZERO:
            ctx.explain("no ordinary income, so -0-")
            return ZERO
        tax = tax_table_lookup(ordinary, year, status)
        ctx.explain(f"tax on {fmt(ordinary)} of ordinary income = {fmt(tax)}")
        return tax

    add(_n("9", "Tax on the ordinary income on line 5", line_9, ("qdcgtw.l5",)))

    def line_10(ctx: Ctx) -> Decimal:
        at_fifteen, at_twenty = ctx["qdcgtw.l7"], ctx["qdcgtw.l8"]
        ordinary_tax = ctx["qdcgtw.l9"]
        preferential = at_fifteen * Decimal("0.15") + at_twenty * Decimal("0.20")
        total = ordinary_tax + preferential

        # Cross-check against the implementation that is reconciled to filed
        # returns. These are two routes to one figure; if they disagree, the
        # decomposition shown above is not the arithmetic that produced the
        # tax, and saying so is better than printing a tidy sum that is wrong.
        reconciled = tax_with_capital_gains(
            taxable_income=ctx["qdcgtw.l1"],
            qualified_income=ctx["qdcgtw.l4"],
            year=year,
            status=status,
        )
        if abs(total - reconciled) > TOLERANCE:
            ctx.flag(
                f"this worksheet's decomposition reaches {fmt(total)} but the "
                f"reconciled preferential-rate computation reaches "
                f"{fmt(reconciled)}; the deterministic figure wins and the "
                "difference needs a human before filing"
            )
            total = reconciled

        ctx.explain(
            f"{fmt(ordinary_tax)} on ordinary income + {fmt(at_fifteen)} x 15% "
            f"+ {fmt(at_twenty)} x 20% = {fmt(total)}"
        )
        return total

    add(_n("10", "Tax. Add the tax on ordinary income and on each preferential slice",
           line_10,
           ("qdcgtw.l7", "qdcgtw.l8", "qdcgtw.l9", "qdcgtw.l1", "qdcgtw.l4")))

    def line_11(ctx: Ctx) -> Decimal:
        taxable = ctx["qdcgtw.l1"]
        worksheet = ctx["qdcgtw.l10"]
        flat = tax_table_lookup(taxable, year, status) if taxable > ZERO else ZERO
        lower = min(worksheet, flat)
        ctx.explain(
            f"smaller of {fmt(worksheet)} from this worksheet and {fmt(flat)} "
            f"from the Tax Table on the whole {fmt(taxable)} = {fmt(lower)}"
        )
        return lower

    add(_n("11",
           "Tax on all taxable income. Enter the smaller of this worksheet's tax "
           "or the tax on the whole amount, here and on Form 1040 line 16",
           line_11, ("qdcgtw.l1", "qdcgtw.l10")))

    return nodes


register_form(FORM, build)
