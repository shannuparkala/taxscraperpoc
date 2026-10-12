"""The pieces a calculation graph is built from.

One node per line of one form. A node declares what it needs, computes from
nothing else, and returns a figure together with the record of how it got there.
No node reads a database, calls a model, touches the network or looks at global
state: given the same ``TaxpayerFacts`` the graph returns the same result on any
machine, which is what lets a review say "the tax is wrong" rather than "the tax
is different today".

See the ``tax-architecture`` skill for the contract this implements.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any

from app.services.tax_engine.tax_authority import Authority

ZERO = Decimal(0)


class Rounding(str, Enum):
    """Where a form says to round, and to what.

    Never round mid-computation and then again at the end. The Form 1040
    rounding rule applies to *entries*, so a worksheet feeding a line keeps its
    cents until the line it feeds is entered.
    """

    NONE = "none"
    #: ROUND_HALF_UP, not Python's default banker's rounding, which gives a
    #: different answer on exactly the figures a reviewer spot-checks.
    DOLLARS = "dollars"


def apply_rounding(amount: Decimal, rounding: Rounding) -> Decimal:
    if rounding is Rounding.DOLLARS:
        return amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return amount


class Basis(str, Enum):
    """Where a figure came from. Mirrors ``TrailRow.basis``."""

    EXTRACTED = "extracted"
    COMPUTED = "computed"
    STATUTORY = "statutory"
    FLAGGED = "flagged"


class UnsupportedItem(Exception):
    """This node cannot compute the line, and will not approximate it.

    Raising does not refuse the return. The node's amount becomes ``None``,
    every node downstream of it inherits the flag, the rest of the return
    computes, and the package is marked not fileable naming the lines that are
    unsupported. See trap 30: refusing looks like the conservative choice and is
    not, because a preparer cannot correct a return that does not exist.
    """

    def __init__(self, reason: str, *, node_id: str = "") -> None:
        self.reason = reason
        self.node_id = node_id
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class SourceFact:
    """A figure read off a document, with enough to open the page it came from.

    ``document_id`` is the document that *reported* this field - not the first
    document in the workflow, and not the first row an unordered query returned.
    That field decides which page a reviewer is sent to and whose OCR confidence
    flags the figure. Trap 34 is what getting it wrong costs.
    """

    field: str
    document_id: str
    document_type: str
    page: int
    confidence: Decimal = Decimal(1)
    #: (x0, y0, x1, y1) in PDF points on ``page``, when a figure box on that
    #: page matched the value exactly once. None is "not located", never a guess.
    bbox: tuple[Decimal, Decimal, Decimal, Decimal] | None = None
    #: This document's contribution to the field. A field is routinely the sum
    #: of several documents - two W-2s make one line 1a - and the leaf has to
    #: show each of them, not just the first.
    amount: Decimal | None = None
    #: The ``ExtractionResult`` row this was read into, when one exists.
    extraction_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "document_id": self.document_id,
            "document_type": self.document_type,
            "page": self.page,
            "confidence": str(self.confidence),
            "bbox": None if self.bbox is None else [str(v) for v in self.bbox],
            "amount": None if self.amount is None else str(self.amount),
            "extraction_id": self.extraction_id,
        }


@dataclass(frozen=True, slots=True)
class NodeResult:
    """One evaluated line, and everything needed to audit it.

    ``amount`` is ``None`` exactly when the line is unsupported. Renderers must
    show that as unsupported and never as zero - zero in a money column is
    itself a figure, which is trap 32.
    """

    node_id: str
    form: str
    line: str
    label: str
    amount: Decimal | None
    #: The arithmetic with operands substituted: "7,410 + 1,236 = 8,646".
    #: Never symbols - a reader checking a return in their hand cannot use them.
    formula: str
    inputs: tuple[tuple[str, Decimal | None], ...] = ()
    authority: Authority | None = None
    sources: tuple[SourceFact, ...] = ()
    basis: Basis = Basis.COMPUTED
    flags: tuple[str, ...] = ()

    @property
    def unsupported(self) -> bool:
        return self.amount is None

    @property
    def reference(self) -> str:
        """Where the rule for this figure is written.

        The statutory authority when the line rests on one; otherwise the form
        line itself, whose instructions are the rule. Never empty - a figure
        with no stated reference is one a reviewer cannot check.
        """
        if self.authority is not None:
            return self.authority.citation
        if self.form in ("facts", "statute"):
            return self.label
        return f"{self.form}, line {self.line}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "form": self.form,
            "line": self.line,
            "label": self.label,
            "amount": None if self.amount is None else str(self.amount),
            "formula": self.formula,
            "reference": self.reference,
            "inputs": [
                [nid, None if amt is None else str(amt)] for nid, amt in self.inputs
            ],
            "authority": None if self.authority is None else self.authority.to_dict(),
            "sources": [s.to_dict() for s in self.sources],
            "basis": self.basis.value,
            "flags": list(self.flags),
        }


#: What a node's ``compute`` is handed. Defined in ``evaluator`` to avoid a
#: cycle; nodes only need the callable shape.
Compute = Callable[[Any], Decimal]


@dataclass(frozen=True, slots=True)
class Node:
    """One line of one form.

    ``inputs`` is *declared*, not discovered from the body. It is what makes the
    graph a graph: the topological order, the cycle check, the backward
    cross-reference and the drill-down tree all come from it. A ``compute`` that
    reaches a figure outside its own ``inputs`` is the defect this design exists
    to make impossible - it is how a line ends up right on the sample that was
    tested and wrong on the next one, with provenance that says otherwise.
    """

    id: str
    form: str
    line: str
    label: str
    compute: Compute
    inputs: tuple[str, ...] = ()
    #: Key into the year's constants, for a line whose figure is statutory.
    authority: str = ""
    rounding: Rounding = Rounding.NONE
    #: Set when this line exists on the form but is not implemented. The node
    #: is still present: a line absent from the graph is indistinguishable, on
    #: the rendered return, from a line that computed zero.
    unsupported_reason: str = ""
    notes: str = ""


def unsupported_node(
    node_id: str, form: str, line: str, label: str, reason: str
) -> Node:
    """A line the form has and this engine does not compute."""

    def _raise(ctx: Any) -> Decimal:
        raise UnsupportedItem(reason, node_id=node_id)

    return Node(
        id=node_id,
        form=form,
        line=line,
        label=label,
        compute=_raise,
        unsupported_reason=reason,
    )


def pending_form_node(
    node_id: str,
    form: str,
    line: str,
    label: str,
    *,
    source_form: str,
    required: bool,
) -> Node:
    """A line fed by a form this engine has not built yet.

    The distinction that makes incremental building safe: a line fed by a
    schedule the taxpayer does not use is **zero**, and a line fed by a
    schedule they do use is **unsupported**. Collapsing the two either buries
    a real gap under a plausible zero, or makes every simple return
    unfileable because Schedule F exists.

    ``required`` is decided by the form builder, which can see the facts.
    """
    if required:

        def _raise(ctx: Any) -> Decimal:
            raise UnsupportedItem(
                f"{source_form} feeds this line and is not implemented, and "
                "this return has figures that belong on it",
                node_id=node_id,
            )

        return Node(
            id=node_id,
            form=form,
            line=line,
            label=label,
            compute=_raise,
            unsupported_reason=f"{source_form} not implemented",
        )

    def _nil(ctx: Any) -> Decimal:
        ctx.explain(f"nothing on this return feeds {source_form}, so -0-")
        return ZERO

    return Node(id=node_id, form=form, line=line, label=label, compute=_nil)


@dataclass
class FormGraph:
    """The nodes of one form, in the order the form prints them."""

    form: str
    nodes: list[Node] = field(default_factory=list)

    def add(self, node: Node) -> Node:
        self.nodes.append(node)
        return node
