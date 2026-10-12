"""Shared node builders for the schedules.

Schedules 1, 2 and 3 are mostly the same three shapes repeated: a figure
entered directly, a figure carried from another form, and a subtotal. Writing
each of their ~175 lines out by hand would bury the handful that are not
mechanical, so the shapes live here and each schedule is a table of its lines.
The table is the form.

**Field naming.** A direct-entry line's fact is named after the line it sits on
- ``sch1_l8g`` is Schedule 1 line 8g. Field names are a contract with two ends
and the ends drift (trap 17), so on a schedule of write-in lines the name that
cannot drift is the line number itself: an extractor that finds a figure for
Schedule 1 line 8g has exactly one place to put it.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tax_engine.graph.evaluator import Ctx, fmt
from app.services.tax_engine.graph.facts import MONEY_FIELDS
from app.services.tax_engine.graph.nodes import ZERO, Node, pending_form_node


def node_id(form_key: str, line: str) -> str:
    return f"{form_key}.l{line}"


def field_name(form_key: str, line: str) -> str:
    return f"{form_key}_l{line}"


def declare(form_key: str, form: str, line: str, label: str) -> str:
    """Add a direct-entry line's field to the engine's vocabulary."""
    name = field_name(form_key, line)
    MONEY_FIELDS.setdefault(name, f"{form} line {line} - {label}")
    return name


def direct(form: str, form_key: str, line: str, label: str) -> Node:
    """A line entered from a document rather than computed.

    Nothing reported is zero, and the node says so rather than passing as an
    ordinary figure: a line nobody filled and a line filled with nil are
    different facts, and only the first is worth a reviewer's attention.
    """
    declare(form_key, form, line, label)
    source = f"facts.{field_name(form_key, line)}"

    def compute(ctx: Ctx) -> Decimal:
        amount = ctx[source]
        ctx.explain(f"{fmt(amount)} entered on {form} line {line}")
        return amount

    return Node(
        id=node_id(form_key, line),
        form=form,
        line=line,
        label=label,
        compute=compute,
        inputs=(source,),
    )


def named(form: str, form_key: str, line: str, label: str, field: str) -> Node:
    """A direct-entry line whose fact has a descriptive name of its own.

    Most schedule lines are write-ins with no natural name, so ``direct`` names
    their field after the line. A few lines *are* a figure the vocabulary
    already has a word for - Schedule B line 1 is taxable interest, Schedule
    IL-WIT column E is Illinois withholding - and coining a second name for
    those would give one figure two spellings, with the one the extractor fills
    a coin toss. Trap 17 with extra steps.
    """
    MONEY_FIELDS.setdefault(field, f"{form} line {line} - {label}")
    source = f"facts.{field}"

    def compute(ctx: Ctx) -> Decimal:
        amount = ctx[source]
        ctx.explain(f"{fmt(amount)} entered on {form} line {line}")
        return amount

    return Node(id=node_id(form_key, line), form=form, line=line, label=label,
                compute=compute, inputs=(source,))


def from_form(
    form: str,
    form_key: str,
    line: str,
    label: str,
    source_form: str,
    *,
    required: bool = False,
) -> Node:
    """A line carried from a form this engine has not built."""
    return pending_form_node(
        node_id(form_key, line),
        form,
        line,
        label,
        source_form=source_form,
        required=required,
    )


def subtotal(
    form: str, form_key: str, line: str, label: str, parts: tuple[str, ...]
) -> Node:
    """A line that adds other lines of the same schedule."""
    inputs = tuple(node_id(form_key, part) for part in parts)

    def compute(ctx: Ctx) -> Decimal:
        return ctx.total(*inputs)

    return Node(
        id=node_id(form_key, line),
        form=form,
        line=line,
        label=label,
        compute=compute,
        inputs=inputs,
    )


def carried(
    form: str, form_key: str, line: str, label: str, source_node: str
) -> Node:
    """A line that restates a figure computed elsewhere in the graph."""

    def compute(ctx: Ctx) -> Decimal:
        amount = ctx[source_node]
        ctx.explain(f"{fmt(amount)} carried from {source_node}")
        return amount

    return Node(
        id=node_id(form_key, line),
        form=form,
        line=line,
        label=label,
        compute=compute,
        inputs=(source_node,),
    )


def reserved(form: str, form_key: str, line: str) -> Node:
    """A line the IRS prints as "Reserved for future use".

    It gets a node so the form's line list stays complete and a later year can
    fill it without the renumbering looking like a new line appearing.
    """

    def compute(ctx: Ctx) -> Decimal:
        ctx.explain("reserved for future use on the 2025 form, so -0-")
        return ZERO

    return Node(
        id=node_id(form_key, line),
        form=form,
        line=line,
        label="Reserved for future use",
        compute=compute,
    )


def lettered(
    form: str,
    form_key: str,
    prefix: str,
    entries: tuple[tuple[str, str], ...],
) -> list[Node]:
    """The a-through-z write-in block under a header line."""
    return [
        direct(form, form_key, f"{prefix}{letter}", label)
        for letter, label in entries
    ]
