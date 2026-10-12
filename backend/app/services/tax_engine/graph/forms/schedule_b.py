"""Schedule B (Form 1040) 2025 - Interest and Ordinary Dividends.

Line wording from ``docs/tax-research/schedule-b-d-8949-2025-line-by-line.md``,
read off the primary PDF (Cat. No. 17146N).

Line 4 feeds Form 1040 line 2b. Line 6 feeds Form 1040 line 3b.

Lines 1 and 5 are the per-payer detail rows. The engine carries their total
rather than each payer, because a payer's name is taxpayer data and the figure
the return turns on is the sum. Parts I and II are only *required* above $1,500
of interest or dividends, but computing them below that threshold costs nothing
and keeps line 2b traceable to the same place on every return.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tax_engine.graph.engine import register_form
from app.services.tax_engine.graph.evaluator import Ctx, fmt
from app.services.tax_engine.graph.facts import TaxpayerFacts
from app.services.tax_engine.graph.forms._common import direct, named, subtotal
from app.services.tax_engine.graph.nodes import ZERO, Node

FORM = "Schedule B"
KEY = "schb"

#: Parts I and II are required above this much interest or ordinary dividends.
#: Not indexed - a static figure in the form's own instructions.
FILING_THRESHOLD = Decimal(1500)


def build(facts: TaxpayerFacts) -> list[Node]:
    nodes: list[Node] = []
    add = nodes.append

    # -- Part I, Interest -----------------------------------------------

    add(named(FORM, KEY, "1", "Interest from each payer (total of the listed rows)",
               "taxable_interest"))
    add(subtotal(FORM, KEY, "2", "Add the amounts on line 1", ("1",)))
    add(direct(FORM, KEY, "3",
               "Excludable interest on series EE and I U.S. savings bonds issued after 1989"))

    def line_4(ctx: Ctx) -> Decimal:
        total = ctx["schb.l2"] - ctx["schb.l3"]
        return ctx.floor_at_zero(
            total, because=f"{fmt(ctx['schb.l2'])} - {fmt(ctx['schb.l3'])}"
        )

    add(Node(id="schb.l4", form=FORM, line="4",
             label="Subtract line 3 from line 2. Enter the result here and on Form 1040 line 2b",
             compute=line_4, inputs=("schb.l2", "schb.l3")))

    # -- Part II, Ordinary Dividends -------------------------------------

    add(named(FORM, KEY, "5", "Ordinary dividends from each payer (total of the listed rows)",
               "ordinary_dividends"))
    add(subtotal(FORM, KEY, "6",
                 "Add the amounts on line 5. Enter the total here and on Form 1040 line 3b",
                 ("5",)))

    # -- Part III, Foreign Accounts and Trusts ---------------------------
    #
    # 7a, 7b and 8 are yes/no disclosures with no figure. They are carried as
    # nodes so the form's line list stays complete, and they answer 0 because
    # the graph deals in figures - the disclosure itself is not the engine's
    # to make, and a return that needs FinCEN Form 114 says so here.

    def disclosure(line: str, label: str, triggered: bool) -> Node:
        def compute(ctx: Ctx) -> Decimal:
            if triggered:
                ctx.flag(
                    "this return reports enough interest or dividends that "
                    "Part III must be answered before filing"
                )
            ctx.explain("a yes/no disclosure, not a figure")
            return ZERO

        return Node(id=f"{KEY}.l{line}", form=FORM, line=line, label=label,
                    compute=compute)

    reportable = (
        (facts.money.get("taxable_interest") or ZERO) > FILING_THRESHOLD
        or (facts.money.get("ordinary_dividends") or ZERO) > FILING_THRESHOLD
    )
    add(disclosure("7a", "Financial interest in or signature authority over a foreign account",
                   reportable))
    add(disclosure("7b", "Countries in which the foreign financial account is located", False))
    add(disclosure("8", "Distribution from, or grantor of or transferor to, a foreign trust",
                   False))

    return nodes


register_form(FORM, build)
