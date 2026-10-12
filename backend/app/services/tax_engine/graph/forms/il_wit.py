"""Schedule IL-WIT (2025) - Illinois Income Tax Withheld.

Line wording from ``docs/tax-research/il-1040-icr-il-wit-2025-line-by-line.md``,
read off the primary PDF (R-12/25).

Line 11 feeds IL-1040 line 25.

The form is a table: one row per withholding document, with the Illinois tax
withheld in column E, and line 11 adds that column. The engine carries the
column total rather than each row, because the rows hold employer names and
identification numbers and the figure the return turns on is the sum.

**Illinois withholding is not federal withholding.** They sit in different
boxes on the same W-2, and a return that takes box 2 for both overstates the
state payment by roughly the ratio of the two rates - which produces a refund
that looks plausible.
"""

from __future__ import annotations

from app.services.tax_engine.graph.engine import register_form
from app.services.tax_engine.graph.facts import TaxpayerFacts
from app.services.tax_engine.graph.forms._common import named, subtotal
from app.services.tax_engine.graph.nodes import Node

FORM = "Schedule IL-WIT"
KEY = "ilwit"
STATE = "IL"


def build(facts: TaxpayerFacts) -> list[Node]:
    if not facts.files_in(STATE):
        return []

    return [
        named(FORM, KEY, "colE",
              "Illinois tax withheld, column E of every withholding row",
              "illinois_tax_withheld"),
        subtotal(FORM, KEY, "11",
                 "Add the amounts in Column E. This is your total Illinois "
                 "income tax withheld",
                 ("colE",)),
    ]


register_form(FORM, build)
