"""Schedule 3 (Form 1040) 2025 - Additional Credits and Payments.

Line wording and routing from
``docs/tax-research/schedule-1-2-3-2025-line-by-line.md``, read off the primary
PDF (Cat. No. 71480G, created 11/17/25).

Part I line 8 feeds Form 1040 line 20 (nonrefundable credits). Part II line 15
feeds Form 1040 line 31 (other payments and refundable credits). The two halves
must not be mixed: a nonrefundable credit can only reduce tax to zero, and a
refundable one can produce a refund on its own.
"""

from __future__ import annotations

from app.services.tax_engine.graph.engine import register_form
from app.services.tax_engine.graph.facts import TaxpayerFacts
from app.services.tax_engine.graph.forms._common import (
    direct,
    from_form,
    lettered,
    subtotal,
)
from app.services.tax_engine.graph.nodes import Node

FORM = "Schedule 3"
KEY = "sch3"

#: Line 6a-6z, "Other nonrefundable credits". 6e is reserved for 2025 and is
#: carried as a write-in line rather than dropped, so the letters keep their
#: meaning if it is filled in a later year.
OTHER_NONREFUNDABLE: tuple[tuple[str, str], ...] = (
    ("a", "General business credit. Attach Form 3800"),
    ("b", "Credit for prior year minimum tax. Attach Form 8801"),
    ("c", "Adoption credit. Attach Form 8839"),
    ("d", "Credit for the elderly or disabled. Attach Schedule R"),
    ("e", "Reserved for future use"),
    ("f", "Clean vehicle credit. Attach Form 8936"),
    ("g", "Mortgage interest credit. Attach Form 8396"),
    ("h", "District of Columbia first-time homebuyer credit. Attach Form 8859"),
    ("i", "Qualified electric vehicle credit. Attach Form 8834"),
    ("j", "Alternative fuel vehicle refueling property credit. Attach Form 8911"),
    ("k", "Credit to holders of tax credit bonds. Attach Form 8912"),
    ("l", "Amount on Form 8978, line 14"),
    ("m", "Credit for previously owned clean vehicles. Attach Form 8936"),
    ("z", "Other nonrefundable credits. List type and amount"),
)

#: Line 13a-13z, "Other payments or refundable credits".
OTHER_REFUNDABLE: tuple[tuple[str, str], ...] = (
    ("a", "Form 2439"),
    ("b", "Section 1341 credit for repayment of amounts included in income from earlier years"),
    ("c", "Net elective payment election amount from Form 3800, Part III, line 6, column (j)"),
    ("d", "Deferred amount of net 965 tax liability"),
    ("z", "Other refundable credits"),
)


def build(facts: TaxpayerFacts) -> list[Node]:
    nodes: list[Node] = []
    add = nodes.append

    # -- Part I, Nonrefundable Credits ----------------------------------

    add(from_form(FORM, KEY, "1",
                  "Foreign tax credit. Attach Form 1116 if required", "Form 1116"))
    add(from_form(FORM, KEY, "2",
                  "Credit for child and dependent care expenses from Form 2441, line 11",
                  "Form 2441"))
    add(from_form(FORM, KEY, "3",
                  "Education credits from Form 8863, line 19", "Form 8863"))
    add(from_form(FORM, KEY, "4",
                  "Retirement savings contributions credit. Attach Form 8880", "Form 8880"))
    add(from_form(FORM, KEY, "5a",
                  "Residential clean energy credit from Form 5695, line 15", "Form 5695"))
    add(from_form(FORM, KEY, "5b",
                  "Energy efficient home improvement credit from Form 5695, line 32",
                  "Form 5695"))

    nodes.extend(lettered(FORM, KEY, "6", OTHER_NONREFUNDABLE))
    add(subtotal(FORM, KEY, "7",
                 "Total other nonrefundable credits. Add lines 6a through 6z",
                 tuple(f"6{letter}" for letter, _ in OTHER_NONREFUNDABLE)))

    add(subtotal(FORM, KEY, "8", "Add lines 1 through 4, 5a, 5b, and 7",
                 ("1", "2", "3", "4", "5a", "5b", "7")))

    # -- Part II, Other Payments and Refundable Credits -----------------

    add(from_form(FORM, KEY, "9",
                  "Net premium tax credit. Attach Form 8962", "Form 8962"))
    add(direct(FORM, KEY, "10", "Amount paid with request for extension to file"))
    add(direct(FORM, KEY, "11", "Excess social security and tier 1 RRTA tax withheld"))
    add(from_form(FORM, KEY, "12",
                  "Credit for federal tax on fuels. Attach Form 4136", "Form 4136"))

    nodes.extend(lettered(FORM, KEY, "13", OTHER_REFUNDABLE))
    add(subtotal(FORM, KEY, "14",
                 "Total other payments or refundable credits. Add lines 13a through 13z",
                 tuple(f"13{letter}" for letter, _ in OTHER_REFUNDABLE)))

    add(subtotal(FORM, KEY, "15", "Add lines 9 through 12 and 14",
                 ("9", "10", "11", "12", "14")))

    return nodes


register_form(FORM, build)
