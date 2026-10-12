"""What the engine returns: every line of every form, each with its provenance."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from app.services.tax_engine.graph.facts import TaxpayerFacts
from app.services.tax_engine.graph.nodes import Basis, NodeResult

if TYPE_CHECKING:
    from app.services.tax_engine.graph.explain import Explanation


@dataclass(frozen=True, slots=True)
class ReturnResult:
    """A computed return.

    A return with unsupported lines is still a return. It renders, a preparer
    can read it, and the lines that could not be computed are named rather than
    shown as zero. What it is not is fileable - ``fileable`` is False and
    ``unsupported`` says which lines are why. Refusing to produce anything is a
    different failure, not a safer one: a preparer cannot correct a return that
    does not exist. Trap 30.
    """

    facts: TaxpayerFacts
    #: Every evaluated node, keyed by node id.
    results: dict[str, NodeResult]
    #: Node ids in the order the forms print them.
    order: tuple[str, ...]

    # -- lookup ---------------------------------------------------------

    def __getitem__(self, node_id: str) -> NodeResult:
        return self.results[node_id]

    def get(self, node_id: str) -> NodeResult | None:
        return self.results.get(node_id)

    def amount(self, node_id: str) -> Decimal | None:
        """The figure on one line, or None when that line is unsupported."""
        found = self.results.get(node_id)
        return None if found is None else found.amount

    def explain(self, node_id: str) -> Explanation:
        """The full tree under one figure, down to documents and authorities."""
        from app.services.tax_engine.graph.explain import explain

        return explain(self.results, node_id)

    def form(self, form: str) -> tuple[NodeResult, ...]:
        """Every line of one form, in the order the form prints them."""
        return tuple(
            self.results[node_id]
            for node_id in self.order
            if self.results[node_id].form == form
        )

    @property
    def forms(self) -> tuple[str, ...]:
        """Every form this return touched, first-printed first."""
        seen: list[str] = []
        for node_id in self.order:
            name = self.results[node_id].form
            if name not in seen:
                seen.append(name)
        return tuple(seen)

    @property
    def lines(self) -> tuple[NodeResult, ...]:
        """Every computed line of every form, in official order."""
        return tuple(self.results[node_id] for node_id in self.order)

    # -- what a reviewer needs to see first ------------------------------

    @property
    def unsupported(self) -> tuple[NodeResult, ...]:
        """Lines the engine would not compute, in form order."""
        return tuple(line for line in self.lines if line.unsupported)

    @property
    def fileable(self) -> bool:
        """False while any line is unsupported.

        Deliberately not a judgement about materiality. A line the engine could
        not compute may be worth nothing or may be the whole return, and the
        engine is not the thing that can tell the difference.
        """
        return not self.unsupported

    @property
    def flagged(self) -> tuple[NodeResult, ...]:
        """Every line carrying a flag, including supported ones.

        A constant whose authority was never confirmed flags the lines that
        rest on it without making them unsupported.
        """
        return tuple(line for line in self.lines if line.flags)

    @property
    def unverified_authorities(self) -> tuple[str, ...]:
        """Statutory figures used here whose authority pairing was not checked."""
        out: list[str] = []
        for line in self.results.values():
            if line.basis is Basis.STATUTORY and line.flags:
                out.append(line.node_id)
        return tuple(sorted(set(out)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "tax_year": self.facts.tax_year,
            "filing_status": self.facts.filing_status.value,
            "fileable": self.fileable,
            "forms": list(self.forms),
            "unsupported": [line.node_id for line in self.unsupported],
            "unverified_authorities": list(self.unverified_authorities),
            "lines": [line.to_dict() for line in self.lines],
        }
