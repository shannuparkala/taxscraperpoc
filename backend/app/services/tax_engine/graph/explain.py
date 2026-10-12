"""``explain(node_id)``: one figure, walked all the way down to where it came from.

The tree is built from what each node *recorded* while it ran - its
``NodeResult.inputs`` - never from a second pass that re-derives the reasoning.
A reconstruction can disagree with what actually ran and reads as evidence when
it does; the recorded inputs cannot.

Every branch ends in a leaf, and the kind of leaf is the point:

    source        read off a document - carries document, page, field,
                  confidence and, when one was located, a bounding box
    statutory     fixed by an authority with a citation and a URL
    not_reported  no document reported the figure, so the line entered 0
    nil           a line that read nothing and entered -0-, saying why - a
                  form the return does not use, a line reserved this year
    supplied      a figure with no document named - traceable to nothing
    unsupported   the engine would not compute this line
    standalone    a line that read nothing and still produced a figure

The first four are what a clean return bottoms out in. The last three are what
``/trace-check`` exists to find.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.services.tax_engine.graph.evaluator import CONST_PREFIX, FACT_PREFIX
from app.services.tax_engine.graph.nodes import NodeResult


class LeafKind(str, Enum):
    SOURCE = "source"
    STATUTORY = "statutory"
    NOT_REPORTED = "not_reported"
    NIL = "nil"
    SUPPLIED = "supplied"
    UNSUPPORTED = "unsupported"
    STANDALONE = "standalone"


#: Leaves a figure may legitimately rest on.
TRACED_LEAVES = frozenset(
    {LeafKind.SOURCE, LeafKind.STATUTORY, LeafKind.NOT_REPORTED, LeafKind.NIL}
)


@dataclass(frozen=True, slots=True)
class Explanation:
    """One node of the tree: a line, and the lines it was computed from."""

    result: NodeResult
    children: tuple[Explanation, ...] = ()
    #: Set on a leaf; None on a line computed from other lines.
    leaf: LeafKind | None = None
    #: This node was already expanded higher up the same tree. Its subtree is
    #: not repeated - a total that feeds six lines would otherwise appear six
    #: times - but it is still named, so the reader sees every input.
    repeated: bool = False

    @property
    def node_id(self) -> str:
        return self.result.node_id

    def walk(self) -> Iterator[Explanation]:
        """Every node in the tree, depth first, repeated ones included."""
        yield self
        for child in self.children:
            yield from child.walk()

    def leaves(self) -> tuple[Explanation, ...]:
        """Each distinct leaf this figure rests on, first-reached first."""
        seen: dict[str, Explanation] = {}
        for node in self.walk():
            if node.leaf is not None and not node.repeated:
                seen.setdefault(node.node_id, node)
        return tuple(seen.values())

    def untraced(self) -> tuple[Explanation, ...]:
        """Leaves that are neither a document, an authority nor a stated nil."""
        return tuple(leaf for leaf in self.leaves() if leaf.leaf not in TRACED_LEAVES)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.result.to_dict(),
            "leaf": None if self.leaf is None else self.leaf.value,
            "repeated": self.repeated,
            "children": [child.to_dict() for child in self.children],
        }


def _leaf_kind(result: NodeResult) -> LeafKind | None:
    if result.node_id.startswith(FACT_PREFIX):
        if "not reported" in result.flags:
            return LeafKind.NOT_REPORTED
        return LeafKind.SOURCE if result.sources else LeafKind.SUPPLIED
    if result.node_id.startswith(CONST_PREFIX):
        return LeafKind.STATUTORY
    if result.inputs:
        return None
    if result.amount is None:
        return LeafKind.UNSUPPORTED
    # A figure out of nothing is the case worth finding; a stated -0- is not.
    return LeafKind.NIL if result.amount == 0 else LeafKind.STANDALONE


def explain(results: Mapping[str, NodeResult], node_id: str) -> Explanation:
    """The full tree under one figure, down to documents and authorities.

    Raises ``KeyError`` for an id the return does not have: asking to explain
    a line that does not exist is a caller's mistake, and answering with an
    empty tree would read as "this figure rests on nothing".
    """
    expanded: set[str] = set()

    def build(current: str) -> Explanation:
        result = results[current]
        kind = _leaf_kind(result)
        if current in expanded:
            return Explanation(result=result, leaf=kind, repeated=True)
        expanded.add(current)
        if kind is not None:
            return Explanation(result=result, leaf=kind)
        # A node that read one input twice recorded it twice; show it once.
        inputs = dict.fromkeys(input_id for input_id, _ in result.inputs)
        return Explanation(
            result=result,
            children=tuple(build(input_id) for input_id in inputs),
        )

    return build(node_id)
