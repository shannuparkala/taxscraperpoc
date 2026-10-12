"""Resolving a calculation graph, once, in topological order.

Evaluating a node produces its figure and its provenance in the same step.
Never a second pass that reconstructs the reasoning afterwards: a
reconstruction can disagree with what actually ran, and it reads as evidence
when it does. That is the defect ``calculation_trail.verify`` exists to catch in
the old engine; here it cannot arise.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal
from typing import Any

from app.services.tax_engine.graph.nodes import (
    ZERO,
    Basis,
    Node,
    NodeResult,
    SourceFact,
    UnsupportedItem,
    apply_rounding,
)
from app.services.tax_engine.tax_authority import Authority, Constant, constants_for

FACT_PREFIX = "facts."
CONST_PREFIX = "const."

Resolver = Callable[[str], NodeResult]


def fmt(amount: Decimal) -> str:
    """A figure as a reader would write it: 7,410 or 1,234.56, never 7410.00."""
    quantized = amount.quantize(Decimal("0.01"))
    if quantized == quantized.to_integral_value():
        return f"{quantized.to_integral_value():,}"
    return f"{quantized:,}"


class GraphError(ValueError):
    """The graph itself is wrong - a cycle, a dangling input, a duplicate id."""


def _is_leaf(node_id: str) -> bool:
    return node_id.startswith((FACT_PREFIX, CONST_PREFIX))


class Graph:
    """Every node of every form on one return."""

    def __init__(self, nodes: Iterable[Node]) -> None:
        self._nodes: dict[str, Node] = {}
        self._order: list[str] = []
        for node in nodes:
            if node.id in self._nodes:
                raise GraphError(f"duplicate node id {node.id!r}")
            self._nodes[node.id] = node
            self._order.append(node.id)
        self._validate()
        self._feeds = self._invert()

    def __contains__(self, node_id: str) -> bool:
        return node_id in self._nodes

    def __getitem__(self, node_id: str) -> Node:
        return self._nodes[node_id]

    def __len__(self) -> int:
        return len(self._nodes)

    @property
    def order(self) -> tuple[str, ...]:
        """Node ids in the order the forms print them."""
        return tuple(self._order)

    def feeds_into(self, node_id: str) -> tuple[str, ...]:
        """The lines that consume this figure.

        Derived by inverting ``inputs`` across the whole graph once, at
        assembly. It is the only cross-reference the declaration does not give
        directly.
        """
        return self._feeds.get(node_id, ())

    def _invert(self) -> dict[str, tuple[str, ...]]:
        out: dict[str, list[str]] = {}
        for node in self._nodes.values():
            for dep in node.inputs:
                out.setdefault(dep, []).append(node.id)
        return {key: tuple(value) for key, value in out.items()}

    def _validate(self) -> None:
        """Dangling inputs and cycles are build-time errors, not runtime ones.

        A taxpayer's facts must never be what reveals the graph is malformed.
        """
        for node in self._nodes.values():
            for dep in node.inputs:
                if not _is_leaf(dep) and dep not in self._nodes:
                    raise GraphError(f"{node.id} declares unknown input {dep!r}")

        visiting: set[str] = set()
        done: set[str] = set()

        def walk(node_id: str, path: tuple[str, ...]) -> None:
            if node_id in done:
                return
            if node_id in visiting:
                trail = " -> ".join([*path, node_id])
                raise GraphError(f"cycle in the graph: {trail}")
            visiting.add(node_id)
            for dep in self._nodes[node_id].inputs:
                if not _is_leaf(dep):
                    walk(dep, (*path, node_id))
            visiting.discard(node_id)
            done.add(node_id)

        for node_id in self._nodes:
            walk(node_id, ())


class Ctx:
    """What a node's ``compute`` is handed.

    Every figure reaches a node through here, and everything read through here
    is recorded. A node cannot quietly consult something it did not declare:
    ``__getitem__`` refuses an id that is not in the node's own ``inputs``.
    """

    def __init__(self, node: Node, resolve: Resolver) -> None:
        self.node = node
        self._resolve = resolve
        self._declared = frozenset(node.inputs)
        self.used: list[tuple[str, Decimal | None]] = []
        self.formula = ""
        self.authority: Authority | None = None
        self.sources: list[SourceFact] = []
        self.flags: list[str] = []

    def __getitem__(self, node_id: str) -> Decimal:
        """An input's figure. Raises if that input is unsupported.

        This is where unsupported-ness propagates: a node that reads a line the
        engine could not compute becomes unsupported itself, automatically,
        with no special case in its own body.
        """
        if node_id not in self._declared:
            raise GraphError(
                f"{self.node.id} read {node_id!r}, which is not in its declared "
                "inputs. Declare it, or do not use it."
            )
        result = self._resolve(node_id)
        self.used.append((node_id, result.amount))
        if result.authority is not None and self.authority is None:
            self.authority = result.authority
        self.sources.extend(result.sources)
        if result.amount is None:
            reason = result.flags[0] if result.flags else "unsupported"
            raise UnsupportedItem(
                f"depends on {node_id}, which is unsupported: {reason}",
                node_id=self.node.id,
            )
        return result.amount

    def get(self, node_id: str, default: Decimal = ZERO) -> Decimal:
        """An input's figure, or ``default`` when that input is unsupported."""
        try:
            return self[node_id]
        except UnsupportedItem:
            return default

    # -- arithmetic that records its own formula ------------------------

    def total(self, *node_ids: str) -> Decimal:
        amounts = [self[node_id] for node_id in node_ids]
        result = sum(amounts, ZERO)
        shown = [fmt(a) for a in amounts if a != ZERO] or ["0"]
        self.formula = f"{' + '.join(shown)} = {fmt(result)}"
        return result

    def less(self, minuend: str, *subtrahends: str) -> Decimal:
        base = self[minuend]
        taken = [self[node_id] for node_id in subtrahends]
        result = base - sum(taken, ZERO)
        shown = " - ".join(fmt(a) for a in taken) or "0"
        self.formula = f"{fmt(base)} - {shown} = {fmt(result)}"
        return result

    def lesser_of(self, *node_ids: str) -> Decimal:
        amounts = [self[node_id] for node_id in node_ids]
        result = min(amounts)
        self.formula = f"lesser of {', '.join(fmt(a) for a in amounts)} = {fmt(result)}"
        return result

    def greater_of(self, *node_ids: str) -> Decimal:
        amounts = [self[node_id] for node_id in node_ids]
        result = max(amounts)
        self.formula = f"greater of {', '.join(fmt(a) for a in amounts)} = {fmt(result)}"
        return result

    def floor_at_zero(self, amount: Decimal, *, because: str = "") -> Decimal:
        """The form's '-0-' instruction, recorded whichever way it lands.

        Both branches record. An exactly-zero subtraction is a real figure that
        a reader will want to check, and it used to fall between this method's
        test and its caller's and report no arithmetic at all.
        """
        shown = because or fmt(amount)
        if amount >= ZERO:
            self.formula = f"{shown} = {fmt(amount)}"
            return amount
        self.formula = f"{shown} is below zero, so -0- (the form says enter -0-)"
        return ZERO

    # -- recording ------------------------------------------------------

    def explain(self, formula: str) -> None:
        """Set the formula for a line the helpers above do not describe."""
        self.formula = formula

    def flag(self, message: str) -> None:
        self.flags.append(message)

    def unsupported(self, reason: str) -> Decimal:
        raise UnsupportedItem(reason, node_id=self.node.id)


def _fact_result(node_id: str, facts: Any) -> NodeResult:
    field = node_id[len(FACT_PREFIX) :]
    amount = facts.amount(field)
    sources: tuple[SourceFact, ...] = facts.sources(field)
    if amount is None:
        return NodeResult(
            node_id=node_id,
            form="facts",
            line=field,
            label=field,
            amount=ZERO,
            formula=f"no document reported {field}; entered as 0",
            basis=Basis.EXTRACTED,
            flags=("not reported",),
        )

    flags: list[str] = []
    if not sources:
        shown = f"{fmt(amount)} supplied as {field}"
    elif len(sources) == 1 and sources[0].amount in (None, amount):
        only = sources[0]
        shown = f"{fmt(amount)} read from {only.document_type} page {only.page}"
    else:
        parts = [
            f"{'?' if s.amount is None else fmt(s.amount)} "
            f"({s.document_type} page {s.page})"
            for s in sources
        ]
        shown = f"{' + '.join(parts)} = {fmt(amount)}"
        counted = [s.amount for s in sources if s.amount is not None]
        # The contributions are the figure's receipt. When they do not add up
        # to it, one of them is missing from the trail or the figure is not
        # the sum it claims to be - either way the reviewer has to know.
        if len(counted) == len(sources) and sum(counted, ZERO) != amount:
            flags.append(
                f"sources account for {fmt(sum(counted, ZERO))} of {fmt(amount)}"
            )
    return NodeResult(
        node_id=node_id,
        form="facts",
        line=field,
        label=field,
        amount=amount,
        formula=shown,
        basis=Basis.EXTRACTED,
        sources=sources,
        flags=tuple(flags),
    )


def _constant_result(node_id: str, year: int) -> NodeResult:
    path = node_id[len(CONST_PREFIX) :]
    year_constants = constants_for(year)
    parts = path.split(".")

    constant: Constant | None = None
    if len(parts) == 1:
        constant = year_constants.scalars.get(parts[0])
    elif len(parts) == 2:
        table = getattr(year_constants, parts[0], None)
        if isinstance(table, Mapping):
            found = table.get(parts[1])
            if isinstance(found, Constant):
                constant = found

    if constant is None:
        raise GraphError(f"no constant {path!r} for tax year {year}")

    return NodeResult(
        node_id=node_id,
        form="statute",
        line=path,
        label=constant.authority.citation,
        amount=constant.value,
        formula=f"{fmt(constant.value)} per {constant.authority.citation}",
        authority=constant.authority,
        basis=Basis.STATUTORY,
        flags=() if constant.verified else ("authority not confirmed",),
    )


def _run(node: Node, resolve: Resolver) -> NodeResult:
    ctx = Ctx(node, resolve)
    amount: Decimal | None
    try:
        amount = apply_rounding(node.compute(ctx), node.rounding)
        basis = Basis.COMPUTED
        flags = tuple(ctx.flags)
        formula = ctx.formula
        if not formula:
            raise GraphError(
                f"{node.id} computed {amount} without recording a formula. Use a "
                "ctx helper or ctx.explain(): a line with no arithmetic shown "
                "cannot be checked against the form it claims to be."
            )
    except UnsupportedItem as exc:
        amount = None
        basis = Basis.FLAGGED
        flags = (exc.reason, *ctx.flags)
        formula = f"not computed: {exc.reason}"

    return NodeResult(
        node_id=node.id,
        form=node.form,
        line=node.line,
        label=node.label,
        amount=amount,
        formula=formula,
        inputs=tuple(ctx.used),
        authority=ctx.authority,
        # The same fact reaches a total down several paths; list it once.
        sources=tuple(dict.fromkeys(ctx.sources)),
        basis=basis,
        flags=flags,
    )


def evaluate(graph: Graph, facts: Any) -> dict[str, NodeResult]:
    """Resolve every node once, memoised, in dependency order."""
    results: dict[str, NodeResult] = {}

    def resolve(node_id: str) -> NodeResult:
        cached = results.get(node_id)
        if cached is not None:
            return cached
        if node_id.startswith(FACT_PREFIX):
            built = _fact_result(node_id, facts)
        elif node_id.startswith(CONST_PREFIX):
            built = _constant_result(node_id, facts.tax_year)
        else:
            built = _run(graph[node_id], resolve)
        results[node_id] = built
        return built

    for node_id in graph.order:
        resolve(node_id)
    return results
