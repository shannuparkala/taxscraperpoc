"""Form 8949 (2025) - Sales and Other Dispositions of Capital Assets.

Line wording and the box map from
``docs/tax-research/schedule-b-d-8949-2025-line-by-line.md``, read off the
primary PDF (Cat. No. 37768Z).

This form is a transaction ledger, not a fixed set of lines: Part I and Part II
each hold a line 1 of individual sales and a line 2 that totals them, and which
Schedule D line the total reaches depends on the box checked at the top of the
part. So the nodes here are the **box totals**, one per checkbox, named for the
box:

    f8949.p1.l2a   Part I line 2, Box A    short-term, basis reported to the IRS
    f8949.p1.l2b   Part I line 2, Box B    short-term, basis not reported
    f8949.p1.l2c   Part I line 2, Box C    short-term, no 1099-B
    f8949.p2.l2d   Part II line 2, Box D   long-term, basis reported
    f8949.p2.l2e   Part II line 2, Box E   long-term, basis not reported
    f8949.p2.l2f   Part II line 2, Box F   long-term, no 1099-B

New for 2025, boxes G through L cover digital assets reported on Form 1099-DA
and land on the same Schedule D lines as A through F respectively. They are
separate boxes on the form and separate nodes here, because a digital-asset
sale and a stock sale reaching the same Schedule D line is a fact a reviewer
may want to see, and collapsing them loses it.

**These are gain or loss, already netted** - column (h), which is proceeds less
basis plus the column (g) adjustment. Proceeds and basis are not carried as
separate lines because Schedule D consumes only the netted figure.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tax_engine.graph.engine import register_form
from app.services.tax_engine.graph.evaluator import Ctx, fmt
from app.services.tax_engine.graph.facts import MONEY_FIELDS, TaxpayerFacts
from app.services.tax_engine.graph.nodes import Node

FORM = "Form 8949"

#: (box, part, holding period, what the box means, the Schedule D line it feeds)
BOXES: tuple[tuple[str, int, str, str, str], ...] = (
    ("a", 1, "short", "Box A - short-term, basis reported to the IRS", "schd.l1b"),
    ("b", 1, "short", "Box B - short-term, basis not reported to the IRS", "schd.l2"),
    ("c", 1, "short", "Box C - short-term, not reported on Form 1099-B", "schd.l3"),
    ("d", 2, "long", "Box D - long-term, basis reported to the IRS", "schd.l8b"),
    ("e", 2, "long", "Box E - long-term, basis not reported to the IRS", "schd.l9"),
    ("f", 2, "long", "Box F - long-term, not reported on Form 1099-B", "schd.l10"),
    ("g", 1, "short", "Box G - short-term digital assets, basis reported", "schd.l1b"),
    ("h", 1, "short", "Box H - short-term digital assets, basis not reported", "schd.l2"),
    ("i", 1, "short", "Box I - short-term digital assets, no Form 1099-DA", "schd.l3"),
    ("j", 2, "long", "Box J - long-term digital assets, basis reported", "schd.l8b"),
    ("k", 2, "long", "Box K - long-term digital assets, basis not reported", "schd.l9"),
    ("l", 2, "long", "Box L - long-term digital assets, no Form 1099-DA", "schd.l10"),
)


def box_node_id(box: str) -> str:
    part = next(p for b, p, _, _, _ in BOXES if b == box)
    return f"f8949.p{part}.l2{box}"


def box_field(box: str) -> str:
    return f"f8949_l2{box}"


def feeds(schedule_d_line: str) -> tuple[str, ...]:
    """Every Form 8949 box total that lands on one Schedule D line."""
    return tuple(box_node_id(b) for b, _, _, _, target in BOXES if target == schedule_d_line)


def build(facts: TaxpayerFacts) -> list[Node]:
    nodes: list[Node] = []

    for box, part, period, label, target in BOXES:
        field = box_field(box)
        MONEY_FIELDS.setdefault(
            field, f"Form 8949 Part {part} line 2, {label} - net gain or (loss)"
        )
        source = f"facts.{field}"

        def compute(ctx: Ctx, source: str = source, target: str = target) -> Decimal:
            amount = ctx[source]
            ctx.explain(f"{fmt(amount)} of net gain or (loss), carried to {target}")
            return amount

        nodes.append(
            Node(
                id=box_node_id(box),
                form=FORM,
                line=f"Part {part} line 2, box {box.upper()}",
                label=label,
                compute=compute,
                inputs=(source,),
                notes=f"feeds {target}",
            )
        )

    return nodes


register_form(FORM, build)
