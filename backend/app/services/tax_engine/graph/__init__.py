"""The deterministic tax engine, v2: typed facts in, every line of every form out.

One node per line of one form, each declaring what it needs and returning its
figure together with the record of how it got there. No node calls a model,
reads a database or touches the network. The ``tax-architecture`` skill is the
contract; this package implements it.

    facts = TaxpayerFacts(tax_year=2025, filing_status=..., money={...})
    result = compute_return(facts)
    result.amount("f1040.l11")      # adjusted gross income
    result.unsupported              # lines the engine would not compute
    result.fileable                 # False while any line is unsupported
    result.explain("f1040.l24")     # the tree under one figure, to its sources

This sits beside the original ``form_1040.Form1040Calculator`` rather than
replacing it, so the two can be run against each other on the reconciled
benchmarks while forms are migrated one at a time.
"""

from __future__ import annotations

from app.services.tax_engine.graph import forms as _forms
from app.services.tax_engine.graph.engine import (
    build_graph,
    compute_return,
    register_form,
    registered_forms,
)
from app.services.tax_engine.graph.evaluator import (
    Ctx,
    Graph,
    GraphError,
    evaluate,
    fmt,
)
from app.services.tax_engine.graph.explain import (
    TRACED_LEAVES,
    Explanation,
    LeafKind,
    explain,
)
from app.services.tax_engine.graph.facts import (
    MONEY_FIELDS,
    Dependent,
    TaxpayerFacts,
    UnknownMoneyField,
)
from app.services.tax_engine.graph.nodes import (
    Basis,
    FormGraph,
    Node,
    NodeResult,
    Rounding,
    SourceFact,
    UnsupportedItem,
    unsupported_node,
)
from app.services.tax_engine.graph.result import ReturnResult


def _declare_vocabulary_and_validate() -> None:
    """Build the graph once, at import, on a taxpayer with no figures.

    Two things have to be true before the first real return arrives, and both
    are settled here.

    **The vocabulary must be complete.** A form declares the money fields it
    consumes, but it declares them while building - and ``TaxpayerFacts``
    checks its keys at construction, which is earlier. Without this pass, the
    first return supplying a Schedule D figure is rejected for using a field
    name no form has gotten around to declaring yet.

    **The graph must be well formed.** A cycle or a dangling input is a defect
    in the engine, and a taxpayer's return must never be what reveals it. This
    runs the same ``Graph`` validation the real path runs, at import, so the
    process fails to start rather than failing on someone's return.
    """
    from app.services.tax_engine.tax_authority import available_years
    from app.services.tax_engine.tax_tables import FilingStatusTax

    year = max(available_years())
    for state in (None, *_forms.STATES_WITH_FORMS):
        build_graph(
            TaxpayerFacts(
                tax_year=year,
                filing_status=FilingStatusTax.SINGLE,
                resident_state=state,
            )
        )


_declare_vocabulary_and_validate()


__all__ = [
    "MONEY_FIELDS",
    "TRACED_LEAVES",
    "Basis",
    "Ctx",
    "Dependent",
    "Explanation",
    "FormGraph",
    "Graph",
    "GraphError",
    "LeafKind",
    "Node",
    "NodeResult",
    "ReturnResult",
    "Rounding",
    "SourceFact",
    "TaxpayerFacts",
    "UnknownMoneyField",
    "UnsupportedItem",
    "build_graph",
    "compute_return",
    "evaluate",
    "explain",
    "fmt",
    "register_form",
    "registered_forms",
    "unsupported_node",
]
