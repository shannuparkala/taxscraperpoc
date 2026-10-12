"""Form builders. Importing the package registers every form with the engine.

**Registration order is not printing order.** Imports here are sorted, so the
order forms happen to register in is alphabetical and means nothing. The order
a finished return prints its forms in is ``PRINT_ORDER`` below, and
``build_graph`` sorts by it. Relying on import order for this worked until a
lint autofix resorted the imports and silently put Illinois in the middle of
the federal return.

Printing order is not evaluation order either - that comes from each node's
declared inputs, so a schedule near the bottom of this list still feeds a line
near the top of Form 1040.
"""

from __future__ import annotations

from app.services.tax_engine.graph.forms import (  # noqa: F401
    form_1040,
    form_8889,
    form_8949,
    il_1040,
    il_icr,
    il_wit,
    qdcgt_worksheet,
    schedule_1,
    schedule_2,
    schedule_3,
    schedule_a,
    schedule_b,
    schedule_d,
)

#: The order a finished return prints its forms: Form 1040, then its numbered
#: schedules, then its lettered ones, then the attached forms and worksheets,
#: then the state return. A form missing from this list sorts to the end.
PRINT_ORDER: tuple[str, ...] = (
    "Form 1040",
    "Schedule 1",
    "Schedule 2",
    "Schedule 3",
    "Schedule A",
    "Schedule B",
    "Schedule D",
    "Form 8949",
    "Form 8889",
    "Qualified Dividends and Capital Gain Tax Worksheet",
    "Form IL-1040",
    "Schedule ICR",
    "Schedule IL-WIT",
)

#: Every state whose forms this engine can build. The import-time vocabulary
#: pass walks these, because a state form only builds its nodes for a return
#: filed in that state and would otherwise never declare the fields it
#: consumes.
STATES_WITH_FORMS: tuple[str, ...] = ("IL",)
