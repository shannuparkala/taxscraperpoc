"""Schedule D (Form 1040) 2025 - Capital Gains and Losses.

Line wording from ``docs/tax-research/schedule-b-d-8949-2025-line-by-line.md``,
read off the primary PDF (Cat. No. 11338H) and the December 2025 instructions.

Line 16 (or line 21 when 16 is a loss) feeds Form 1040 line 7a.

**The capital loss limitation is the point of Part III.** A net capital loss is
deductible against other income only up to $3,000, or $1,500 on married filing
separately - IRC 1211(b), a fixed statutory figure that neither Rev. Proc.
2024-40 nor OBBBA touched. The rest carries forward. Entering the whole loss on
Form 1040 line 7 is the error this part exists to prevent, and it is invisible
on the finished return because the figure looks like an ordinary capital loss.

**Carryovers are entered as negatives** on lines 6 and 14. A carryover entered
positive turns a loss into income of the same size, which is a swing of twice
the figure and reads as an ordinary gain.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tax_engine.graph.engine import register_form
from app.services.tax_engine.graph.evaluator import Ctx, fmt
from app.services.tax_engine.graph.facts import TaxpayerFacts
from app.services.tax_engine.graph.forms import form_8949
from app.services.tax_engine.graph.forms._common import direct, from_form, node_id
from app.services.tax_engine.graph.nodes import ZERO, Node
from app.services.tax_engine.tax_tables import FilingStatusTax as Status

FORM = "Schedule D"
KEY = "schd"

SHORT_TERM = ("1a", "1b", "2", "3", "4", "5", "6")
LONG_TERM = ("8a", "8b", "9", "10", "11", "12", "13", "14")


def _combine(line: str, label: str, parts: tuple[str, ...]) -> Node:
    """Combine, not add: these lines carry losses and the form says "combine"."""
    inputs = tuple(node_id(KEY, part) for part in parts)

    def compute(ctx: Ctx) -> Decimal:
        return ctx.total(*inputs)

    return Node(id=node_id(KEY, line), form=FORM, line=line, label=label,
                compute=compute, inputs=inputs)


def _from_8949(line: str, label: str) -> Node:
    """A line that totals the Form 8949 boxes which land on it."""
    inputs = form_8949.feeds(node_id(KEY, line))

    def compute(ctx: Ctx) -> Decimal:
        return ctx.total(*inputs)

    return Node(id=node_id(KEY, line), form=FORM, line=line, label=label,
                compute=compute, inputs=inputs)


def _branch(line: str, label: str, note: str) -> Node:
    """A yes/no dispatch question on the form face, which carries no figure."""

    def compute(ctx: Ctx) -> Decimal:
        ctx.explain(note)
        return ZERO

    return Node(id=node_id(KEY, line), form=FORM, line=line, label=label,
                compute=compute)


def build(facts: TaxpayerFacts) -> list[Node]:
    nodes: list[Node] = []
    add = nodes.append

    # -- Part I, Short-Term ---------------------------------------------

    add(direct(FORM, KEY, "1a",
               "Totals for short-term transactions reported on Form 1099-B with basis "
               "reported and no adjustments (Exception 1 - Form 8949 not required)"))
    add(_from_8949("1b", "Totals for transactions reported on Form(s) 8949 with Box A or G"))
    add(_from_8949("2", "Totals for transactions reported on Form(s) 8949 with Box B or H"))
    add(_from_8949("3", "Totals for transactions reported on Form(s) 8949 with Box C or I"))
    add(direct(FORM, KEY, "4",
               "Short-term gain from Form 6252 and short-term gain or (loss) from "
               "Forms 4684, 6781, and 8824"))
    add(direct(FORM, KEY, "5",
               "Net short-term gain or (loss) from partnerships, S corporations, "
               "estates, and trusts, from Schedule(s) K-1"))
    add(direct(FORM, KEY, "6",
               "Short-term capital loss carryover from the Capital Loss Carryover "
               "Worksheet (enter as a negative)"))
    add(_combine("7", "Net short-term capital gain or (loss). Combine lines 1a through 6",
                 SHORT_TERM))

    # -- Part II, Long-Term ---------------------------------------------

    add(direct(FORM, KEY, "8a",
               "Totals for long-term transactions reported on Form 1099-B with basis "
               "reported and no adjustments (Exception 1)"))
    add(_from_8949("8b", "Totals for transactions reported on Form(s) 8949 with Box D or J"))
    add(_from_8949("9", "Totals for transactions reported on Form(s) 8949 with Box E or K"))
    add(_from_8949("10", "Totals for transactions reported on Form(s) 8949 with Box F or L"))
    add(from_form(FORM, KEY, "11",
                  "Gain from Form 4797, Part I; long-term gain from Forms 2439 and 6252; "
                  "and gain or (loss) from Forms 4684, 6781, and 8824", "Form 4797"))
    add(direct(FORM, KEY, "12",
               "Net long-term gain or (loss) from partnerships, S corporations, "
               "estates, and trusts, from Schedule(s) K-1"))
    add(direct(FORM, KEY, "13", "Capital gain distributions"))
    add(direct(FORM, KEY, "14",
               "Long-term capital loss carryover from the Capital Loss Carryover "
               "Worksheet (enter as a negative)"))
    add(_combine("15", "Net long-term capital gain or (loss). Combine lines 8a through 14",
                 LONG_TERM))

    # -- Part III, Summary ----------------------------------------------

    add(_combine("16", "Combine lines 7 and 15 and enter the result", ("7", "15")))

    add(_branch("17", "Are lines 15 and 16 both gains?",
                "a dispatch question: yes goes to line 18, no goes to line 22"))
    add(from_form(FORM, KEY, "18", "28% Rate Gain Worksheet amount", "28% Rate Gain Worksheet"))
    add(from_form(FORM, KEY, "19", "Unrecaptured Section 1250 Gain Worksheet amount",
                  "Unrecaptured Section 1250 Gain Worksheet"))
    add(_branch("20", "Are lines 18 and 19 both zero or blank?",
                "a dispatch question: yes uses the Qualified Dividends and Capital "
                "Gain Tax Worksheet, no uses the Schedule D Tax Worksheet"))

    def line_21(ctx: Ctx) -> Decimal:
        combined = ctx["schd.l16"]
        if combined >= ZERO:
            ctx.explain(
                f"line 16 is {fmt(combined)}, not a loss, so line 21 does not apply"
            )
            return ZERO
        cap = ctx[
            "const.capital_loss_deduction_mfs"
            if facts.filing_status is Status.MARRIED_SEPARATE
            else "const.capital_loss_deduction"
        ]
        allowed = min(-combined, cap)
        carried = -combined - allowed
        if carried > ZERO:
            ctx.flag(
                f"{fmt(carried)} of capital loss exceeds the annual limit and "
                "carries forward to next year"
            )
        ctx.explain(
            f"a net loss of {fmt(-combined)}, limited to the smaller of that "
            f"and {fmt(cap)} under IRC 1211(b) = ({fmt(allowed)})"
        )
        return -allowed

    add(Node(
        id="schd.l21", form=FORM, line="21",
        label="If line 16 is a loss, enter the smaller of the loss or $3,000 "
              "($1,500 if married filing separately)",
        compute=line_21,
        inputs=("schd.l16", "const.capital_loss_deduction",
                "const.capital_loss_deduction_mfs"),
    ))

    add(_branch("22", "Do you have qualified dividends on Form 1040 line 3a?",
                "a dispatch question: yes uses the Qualified Dividends and Capital "
                "Gain Tax Worksheet, no uses the Tax Table or Tax Computation Worksheet"))

    # Not a printed line. Schedule D's instruction is "enter on Form 1040 line 7"
    # from line 16 when it is a gain and from line 21 when it is a loss, which is
    # one figure reached two ways; naming it keeps Form 1040 line 7a's provenance
    # to a single input instead of re-deciding the branch there.
    def to_1040(ctx: Ctx) -> Decimal:
        combined = ctx["schd.l16"]
        if combined >= ZERO:
            ctx.explain(f"{fmt(combined)} of net gain from line 16")
            return combined
        limited = ctx["schd.l21"]
        ctx.explain(f"{fmt(limited)}, the deductible part of the loss, from line 21")
        return limited

    add(Node(
        id="schd.to_1040_l7", form=FORM, line="16/21",
        label="Amount carried to Form 1040 line 7a",
        compute=to_1040, inputs=("schd.l16", "schd.l21"),
    ))

    return nodes


register_form(FORM, build)
