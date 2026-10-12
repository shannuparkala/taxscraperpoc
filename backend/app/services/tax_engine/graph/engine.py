"""Assembling the forms into one graph and running it.

The form order here is the order the forms print, which is also the order a
reviewer reads them in. It is not the evaluation order - that comes from the
declared inputs, and a schedule computed late in the list still feeds a line
near the top of Form 1040.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from app.services.tax_engine.graph.evaluator import Graph, evaluate
from app.services.tax_engine.graph.facts import TaxpayerFacts
from app.services.tax_engine.graph.nodes import Node
from app.services.tax_engine.graph.result import ReturnResult

#: Each entry builds the nodes of one form for one taxpayer. Registered in the
#: order the forms print. A form is added by ``/implement-form``.
FormBuilder = Callable[[TaxpayerFacts], Iterable[Node]]

_BUILDERS: list[tuple[str, FormBuilder]] = []


def register_form(name: str, builder: FormBuilder) -> None:
    """Add a form to every return this engine computes."""
    if any(existing == name for existing, _ in _BUILDERS):
        raise ValueError(f"form {name!r} is already registered")
    _BUILDERS.append((name, builder))


def registered_forms() -> tuple[str, ...]:
    return tuple(name for name, _ in _BUILDERS)


def _print_index(name: str) -> int:
    """Where a form sits in printing order; unlisted forms sort to the end."""
    from app.services.tax_engine.graph.forms import PRINT_ORDER

    try:
        return PRINT_ORDER.index(name)
    except ValueError:
        return len(PRINT_ORDER)


def build_graph(facts: TaxpayerFacts) -> Graph:
    """Every node of every registered form, in printing order.

    Sorted by ``PRINT_ORDER`` rather than by the order the modules imported:
    import order is alphabetical because the imports are linted, and a return
    that prints Illinois between Schedule 3 and Schedule A is not a return
    anyone can check against the paper.
    """
    nodes: list[Node] = []
    for name, builder in sorted(_BUILDERS, key=lambda entry: _print_index(entry[0])):
        nodes.extend(builder(facts))
    return Graph(nodes)


def compute_return(facts: TaxpayerFacts) -> ReturnResult:
    """The whole engine: typed facts in, every line of every form out."""
    graph = build_graph(facts)
    results = evaluate(graph, facts)
    return ReturnResult(facts=facts, results=results, order=graph.order)
