"""Form 8889 (2025) - Health Savings Accounts (HSAs).

Line wording from ``docs/tax-research/schedule-a-8889-qdcgt-2025-line-by-line.md``,
read off the primary PDF.

Line 13 feeds Schedule 1 line 13 (the HSA deduction). Lines 16 and 20 feed
Schedule 1 line 8f as income. Lines 17b and 21 feed Schedule 2's other-taxes
block.

**The figures here come from a different revenue procedure.** HSA and HDHP
limits are set by Rev. Proc. 2024-25, months before Rev. Proc. 2024-40 sets the
general inflation adjustments. Reaching for the usual authority gives a figure
that does not exist. OBBBA made the telehealth safe harbor permanent for 2025;
its Bronze/Catastrophic and direct-primary-care provisions are 2026 and are not
live here.

**Line 3 is a monthly limit, not an annual one.** Someone covered for part of
the year gets that fraction of the limit unless the last-month rule applies -
and the last-month rule has a testing period whose failure is line 18's income
plus line 21's 10% tax. The engine does not know coverage months, so line 3
takes the full annual limit and flags it.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tax_engine.graph.engine import register_form
from app.services.tax_engine.graph.evaluator import Ctx, fmt
from app.services.tax_engine.graph.facts import MONEY_FIELDS, TaxpayerFacts
from app.services.tax_engine.graph.forms._common import direct, node_id, subtotal
from app.services.tax_engine.graph.nodes import ZERO, Node

FORM = "Form 8889"
KEY = "f8889"

#: Age at which the catch-up contribution becomes available. IRC 223(b)(3)(B).
CATCH_UP_AGE = 55

MONEY_FIELDS.setdefault(
    "f8889_family_coverage",
    "Form 8889 line 1 - 1 when HDHP coverage was family, 0 when self-only",
)


def _n(line: str, label: str, compute, inputs: tuple[str, ...] = ()) -> Node:
    return Node(id=node_id(KEY, line), form=FORM, line=line, label=label,
                compute=compute, inputs=inputs)


def build(facts: TaxpayerFacts) -> list[Node]:
    family = bool(facts.money.get("f8889_family_coverage"))
    limit_key = (
        "const.hsa_contribution_limit_family" if family
        else "const.hsa_contribution_limit_self_only"
    )
    age = facts.taxpayer_age

    nodes: list[Node] = []
    add = nodes.append

    def line_1(ctx: Ctx) -> Decimal:
        ctx.explain(
            f"{'family' if family else 'self-only'} high-deductible health "
            "plan coverage; a checkbox, not a figure"
        )
        return ZERO

    add(_n("1", "Check the box to indicate your coverage under a high-deductible health plan",
           line_1))

    add(direct(FORM, KEY, "2", "HSA contributions you made for 2025"))

    def line_3(ctx: Ctx) -> Decimal:
        limit = ctx[limit_key]
        ctx.flag(
            "the annual limit was taken in full; this line is a monthly limit "
            "and no document in this workpaper states the months of HDHP "
            "coverage, so a part-year plan is overstated here"
        )
        ctx.explain(
            f"{fmt(limit)} annual limit for "
            f"{'family' if family else 'self-only'} coverage"
        )
        return limit

    add(_n("3", "Contribution limit for the months you were an eligible individual",
           line_3, (limit_key,)))

    add(direct(FORM, KEY, "4", "Archer MSA contributions for 2025"))

    def line_5(ctx: Ctx) -> Decimal:
        remaining = ctx["f8889.l3"] - ctx["f8889.l4"]
        return ctx.floor_at_zero(
            remaining, because=f"{fmt(ctx['f8889.l3'])} - {fmt(ctx['f8889.l4'])}"
        )

    add(_n("5", "Subtract line 4 from line 3. If zero or less, enter -0-", line_5,
           ("f8889.l3", "f8889.l4")))

    def line_6(ctx: Ctx) -> Decimal:
        amount = ctx["f8889.l5"]
        ctx.explain(f"{fmt(amount)} from line 5, with no spouse allocation")
        return amount

    add(_n("6", "Enter the amount from line 5, allocated between spouses if both have HDHPs",
           line_6, ("f8889.l5",)))

    def line_7(ctx: Ctx) -> Decimal:
        if age is None:
            ctx.flag("no date of birth was read, so no catch-up contribution was allowed")
            ctx.explain("age unknown, so -0-")
            return ZERO
        if age < CATCH_UP_AGE:
            ctx.explain(f"age {age} is under {CATCH_UP_AGE}, so -0-")
            return ZERO
        amount = ctx["const.hsa_catch_up"]
        ctx.explain(f"age {age} is {CATCH_UP_AGE} or older, so {fmt(amount)}")
        return amount

    add(_n("7", "Additional contribution amount if you were age 55 or older", line_7,
           ("const.hsa_catch_up",)))

    add(subtotal(FORM, KEY, "8", "Add lines 6 and 7", ("6", "7")))
    add(direct(FORM, KEY, "9", "Employer contributions made to your HSAs for 2025"))
    add(direct(FORM, KEY, "10", "Qualified HSA funding distributions"))
    add(subtotal(FORM, KEY, "11", "Add lines 9 and 10", ("9", "10")))

    def line_12(ctx: Ctx) -> Decimal:
        remaining = ctx["f8889.l8"] - ctx["f8889.l11"]
        return ctx.floor_at_zero(
            remaining, because=f"{fmt(ctx['f8889.l8'])} - {fmt(ctx['f8889.l11'])}"
        )

    add(_n("12", "Subtract line 11 from line 8. If zero or less, enter -0-", line_12,
           ("f8889.l8", "f8889.l11")))

    add(_n("13", "HSA deduction. Enter the smaller of line 2 or line 12",
           lambda ctx: ctx.lesser_of("f8889.l2", "f8889.l12"),
           ("f8889.l2", "f8889.l12")))

    # -- Part II, Distributions ------------------------------------------

    add(direct(FORM, KEY, "14a", "Total distributions you received in 2025 from all HSAs"))
    add(direct(FORM, KEY, "14b",
               "Distributions included on line 14a that you rolled over to another HSA"))

    def line_14c(ctx: Ctx) -> Decimal:
        return ctx.less("f8889.l14a", "f8889.l14b")

    add(_n("14c", "Subtract line 14b from line 14a", line_14c,
           ("f8889.l14a", "f8889.l14b")))

    add(direct(FORM, KEY, "15", "Qualified medical expenses paid using HSA distributions"))

    def line_16(ctx: Ctx) -> Decimal:
        taxable = ctx["f8889.l14c"] - ctx["f8889.l15"]
        return ctx.floor_at_zero(
            taxable, because=f"{fmt(ctx['f8889.l14c'])} - {fmt(ctx['f8889.l15'])}"
        )

    add(_n("16", "Taxable HSA distributions. Subtract line 15 from line 14c", line_16,
           ("f8889.l14c", "f8889.l15")))

    def line_17a(ctx: Ctx) -> Decimal:
        ctx.explain(
            "the exception checkbox for distributions made after death, "
            "disability or age 65; a checkbox, not a figure"
        )
        return ZERO

    add(_n("17a", "Exceptions to the additional 20% tax", line_17a))

    def line_17b(ctx: Ctx) -> Decimal:
        taxable = ctx["f8889.l16"]
        rate = ctx["const.hsa_nonqualified_distribution_rate"]
        tax = taxable * rate
        ctx.explain(f"{fmt(taxable)} x 20% = {fmt(tax)}")
        return tax

    add(_n("17b", "Additional 20% tax on taxable HSA distributions", line_17b,
           ("f8889.l16", "const.hsa_nonqualified_distribution_rate")))

    # -- Part III, Testing-period failures --------------------------------

    add(direct(FORM, KEY, "18", "Last-month rule income"))
    add(direct(FORM, KEY, "19", "Qualified HSA funding distribution income"))
    add(subtotal(FORM, KEY, "20", "Total income. Add lines 18 and 19", ("18", "19")))

    def line_21(ctx: Ctx) -> Decimal:
        income = ctx["f8889.l20"]
        rate = ctx["const.hsa_coverage_failure_rate"]
        tax = income * rate
        ctx.explain(f"{fmt(income)} x 10% = {fmt(tax)}")
        return tax

    add(_n("21", "Additional tax. Multiply line 20 by 10% (0.10)", line_21,
           ("f8889.l20", "const.hsa_coverage_failure_rate")))

    return nodes


register_form(FORM, build)
