"""The calculation graph's own guarantees, before any form is built on it.

These are the properties every form inherits: a node cannot read what it did
not declare, a cycle is caught when the graph is assembled rather than when a
taxpayer's facts arrive, a line that cannot be computed flags itself and
everything downstream without stopping the rest of the return, and no line ever
reports a figure without the arithmetic that produced it.

Every figure here is invented.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.services.tax_engine.graph import (
    Basis,
    Ctx,
    Graph,
    GraphError,
    Node,
    ReturnResult,
    SourceFact,
    TaxpayerFacts,
    UnknownMoneyField,
    evaluate,
    unsupported_node,
)
from app.services.tax_engine.tax_tables import FilingStatusTax as Status


def facts(**money: D) -> TaxpayerFacts:
    return TaxpayerFacts(
        tax_year=2025,
        filing_status=Status.SINGLE,
        taxpayer_age=40,
        money=dict(money),
    )


def node(node_id: str, compute, inputs: tuple[str, ...] = (), **kw) -> Node:
    return Node(
        id=node_id,
        form=kw.pop("form", "TestForm"),
        line=kw.pop("line", node_id.split(".")[-1]),
        label=kw.pop("label", node_id),
        compute=compute,
        inputs=inputs,
        **kw,
    )


def run(nodes: list[Node], **money: D) -> dict:
    return evaluate(Graph(nodes), facts(**money))


# ------------------------------------------------- reading facts


def test_a_fact_leaf_carries_the_document_it_was_read_from() -> None:
    fact = SourceFact(
        field="wages",
        document_id="doc-1",
        document_type="Form W-2",
        page=3,
        confidence=D("0.98"),
    )
    supplied = TaxpayerFacts(
        tax_year=2025,
        filing_status=Status.SINGLE,
        money={"wages": D(50000)},
        provenance={"wages": fact},
    )
    results = evaluate(
        Graph([node("t.l1", lambda ctx: ctx.total("facts.wages"), ("facts.wages",))]),
        supplied,
    )

    leaf = results["facts.wages"]
    assert leaf.basis is Basis.EXTRACTED
    assert leaf.sources == (fact,)
    assert "Form W-2 page 3" in leaf.formula
    # The consuming line inherits the source, which is what makes a figure on
    # the return clickable back to the page it came off.
    assert results["t.l1"].sources == (fact,)


def test_nothing_reported_is_not_the_same_fact_as_zero() -> None:
    """A document stating zero interest and no document mentioning it differ.

    Only the second is worth a reviewer's attention, so the leaf computes as 0
    and says so rather than passing as an ordinary figure.
    """
    results = run([node("t.l1", lambda ctx: ctx.total("facts.taxable_interest"),
                        ("facts.taxable_interest",))])

    leaf = results["facts.taxable_interest"]
    assert leaf.amount == 0
    assert leaf.flags == ("not reported",)
    assert "no document reported" in leaf.formula


def test_a_figure_under_a_name_no_form_declares_is_refused() -> None:
    """Trap 17 in miniature: a misspelled field reads as zero and is invisible."""
    with pytest.raises(UnknownMoneyField, match="wagez"):
        TaxpayerFacts(
            tax_year=2025, filing_status=Status.SINGLE, money={"wagez": D(50000)}
        )


# ------------------------------------------------- declared inputs


def test_a_node_cannot_read_an_input_it_did_not_declare() -> None:
    """The defect the declared-inputs design exists to make impossible.

    A compute that reaches a figure outside its own ``inputs`` produces a line
    that is right on the sample that was tested and wrong on the next one, with
    a provenance record that says otherwise.
    """
    nodes = [
        node("t.l1", lambda ctx: ctx.total("facts.wages"), ("facts.wages",)),
        # declares nothing, reads t.l1 anyway
        node("t.l2", lambda ctx: ctx["t.l1"], ()),
    ]
    with pytest.raises(GraphError, match="not in its declared inputs"):
        run(nodes, wages=D(100))


def test_an_input_that_is_not_a_node_is_caught_when_the_graph_is_built() -> None:
    with pytest.raises(GraphError, match="unknown input"):
        Graph([node("t.l1", lambda ctx: ctx["t.l99"], ("t.l99",))])


def test_a_cycle_is_caught_at_assembly_not_when_facts_arrive() -> None:
    """A taxpayer's return must never be what reveals the graph is malformed."""
    nodes = [
        node("t.l1", lambda ctx: ctx["t.l2"], ("t.l2",)),
        node("t.l2", lambda ctx: ctx["t.l1"], ("t.l1",)),
    ]
    with pytest.raises(GraphError, match="cycle in the graph"):
        Graph(nodes)


def test_duplicate_node_ids_are_refused() -> None:
    with pytest.raises(GraphError, match="duplicate node id"):
        Graph([node("t.l1", lambda ctx: D(0)), node("t.l1", lambda ctx: D(0))])


def test_feeds_into_is_inverted_from_the_declared_inputs() -> None:
    graph = Graph([
        node("t.l1", lambda ctx: ctx.total("facts.wages"), ("facts.wages",)),
        node("t.l2", lambda ctx: ctx.total("facts.tip_income"), ("facts.tip_income",)),
        node("t.l3", lambda ctx: ctx.total("t.l1", "t.l2"), ("t.l1", "t.l2")),
    ])

    assert graph.feeds_into("t.l1") == ("t.l3",)
    assert graph.feeds_into("t.l2") == ("t.l3",)
    assert graph.feeds_into("t.l3") == ()


# ------------------------------------------------- provenance


def test_every_line_records_its_arithmetic_with_the_operands_substituted() -> None:
    """A formula carrying symbols is a template that never ran.

    A reader checking a return in their hand cannot use "a + b".
    """
    results = run(
        [node("t.l1", lambda ctx: ctx.total("facts.wages", "facts.taxable_interest"),
              ("facts.wages", "facts.taxable_interest"))],
        wages=D(7410),
        taxable_interest=D(1236),
    )

    assert results["t.l1"].amount == D(8646)
    assert results["t.l1"].formula == "7,410 + 1,236 = 8,646"


def test_a_line_that_reports_a_figure_without_a_formula_is_refused() -> None:
    with pytest.raises(GraphError, match="without recording a formula"):
        run([node("t.l1", lambda ctx: D(999))])


def test_a_statutory_leaf_carries_its_authority_and_url() -> None:
    results = run([
        node("t.l1", lambda ctx: ctx.total("const.standard_deduction.single"),
             ("const.standard_deduction.single",))
    ])

    leaf = results["const.standard_deduction.single"]
    assert leaf.basis is Basis.STATUTORY
    assert leaf.authority is not None
    assert leaf.authority.url.startswith("https://")
    assert results["t.l1"].authority is leaf.authority


def test_a_constant_whose_authority_was_not_confirmed_flags_itself() -> None:
    """The 2025 standard deduction comes from the Act, not the instructions."""
    results = run([
        node("t.l1", lambda ctx: ctx.total("const.standard_deduction.single"),
             ("const.standard_deduction.single",))
    ])

    assert results["const.standard_deduction.single"].flags == (
        "authority not confirmed",
    )


def test_an_unknown_constant_is_an_error_not_a_zero() -> None:
    with pytest.raises(GraphError, match="no constant"):
        run([node("t.l1", lambda ctx: ctx.total("const.not_a_real_figure"),
                  ("const.not_a_real_figure",))])


# ------------------------------------------------- unsupported


def test_an_unsupported_line_has_no_amount_rather_than_a_zero() -> None:
    """Zero in a money column is itself a figure - trap 32.

    A renderer must be able to tell "we did not compute this" from "this is
    nil", and an amount of 0 cannot carry that difference.
    """
    results = run([
        unsupported_node("t.l1", "TestForm", "1", "Farm income", "Schedule F not built")
    ])

    assert results["t.l1"].amount is None
    assert results["t.l1"].unsupported
    assert results["t.l1"].basis is Basis.FLAGGED
    assert results["t.l1"].flags == ("Schedule F not built",)


def test_unsupported_propagates_downstream_without_any_node_handling_it() -> None:
    nodes = [
        unsupported_node("t.l1", "TestForm", "1", "Farm income", "Schedule F not built"),
        node("t.l2", lambda ctx: ctx.total("facts.wages"), ("facts.wages",)),
        node("t.l3", lambda ctx: ctx.total("t.l1", "t.l2"), ("t.l1", "t.l2")),
        node("t.l4", lambda ctx: ctx.total("t.l3"), ("t.l3",)),
    ]
    results = run(nodes, wages=D(50000))

    assert results["t.l2"].amount == D(50000), "an unrelated line still computes"
    assert results["t.l3"].amount is None
    assert "t.l1" in results["t.l3"].flags[0]
    assert results["t.l4"].amount is None, "and keeps propagating"


def test_the_rest_of_the_return_still_computes_around_an_unsupported_line() -> None:
    """Trap 30: refusing looks like the conservative choice and is not.

    A preparer cannot correct a return that does not exist.
    """
    nodes = [
        node("t.l1", lambda ctx: ctx.total("facts.wages"), ("facts.wages",)),
        unsupported_node("t.l2", "TestForm", "2", "Farm income", "Schedule F not built"),
        node("t.l3", lambda ctx: ctx.total("facts.taxable_interest"),
             ("facts.taxable_interest",)),
    ]
    graph = Graph(nodes)
    supplied = facts(wages=D(50000), taxable_interest=D(1200))
    result = ReturnResult(
        facts=supplied, results=evaluate(graph, supplied), order=graph.order
    )

    assert result.amount("t.l1") == D(50000)
    assert result.amount("t.l3") == D(1200)
    assert [line.node_id for line in result.unsupported] == ["t.l2"]
    assert result.fileable is False


def test_a_node_may_opt_out_of_an_unsupported_input_with_get() -> None:
    """Some lines genuinely do not need every input to produce their own."""
    nodes = [
        unsupported_node("t.l1", "TestForm", "1", "Farm income", "not built"),
        node(
            "t.l2",
            lambda ctx: ctx.explain("treated the unsupported line as nil") or ctx.get("t.l1"),
            ("t.l1",),
        ),
    ]
    results = run(nodes)

    assert results["t.l2"].amount == 0
    assert results["t.l2"].basis is Basis.COMPUTED


# ------------------------------------------------- evaluation


def test_each_node_is_evaluated_once_however_many_lines_consume_it() -> None:
    calls: list[str] = []

    def counted(ctx: Ctx) -> D:
        calls.append("t.l1")
        return ctx.total("facts.wages")

    nodes = [
        node("t.l1", counted, ("facts.wages",)),
        node("t.l2", lambda ctx: ctx.total("t.l1"), ("t.l1",)),
        node("t.l3", lambda ctx: ctx.total("t.l1"), ("t.l1",)),
        node("t.l4", lambda ctx: ctx.total("t.l2", "t.l3"), ("t.l2", "t.l3")),
    ]
    run(nodes, wages=D(100))

    assert calls == ["t.l1"]


def test_a_line_is_computed_before_the_line_that_consumes_it() -> None:
    """Declaration order is printing order; evaluation order comes from inputs."""
    nodes = [
        # l1 prints first but depends on l2, which prints second.
        node("t.l1", lambda ctx: ctx.total("t.l2"), ("t.l2",)),
        node("t.l2", lambda ctx: ctx.total("facts.wages"), ("facts.wages",)),
    ]
    results = run(nodes, wages=D(4200))

    assert results["t.l1"].amount == D(4200)


# ------------------------------------------------- entitlements, not people


def test_a_spouse_over_65_counts_only_on_a_joint_return() -> None:
    """Trap 33: the engine adds one senior amount per count.

    A spouse date of birth that failed to establish a marriage must not buy a
    second addition for a person the return says is not there.
    """
    joint = TaxpayerFacts(
        tax_year=2025,
        filing_status=Status.MARRIED_JOINT,
        taxpayer_age=70,
        spouse_age=68,
    )
    separate = TaxpayerFacts(
        tax_year=2025,
        filing_status=Status.MARRIED_SEPARATE,
        taxpayer_age=70,
        spouse_age=68,
    )
    single = TaxpayerFacts(
        tax_year=2025, filing_status=Status.SINGLE, taxpayer_age=70, spouse_age=68
    )

    assert joint.seniors == 2
    assert separate.seniors == 1, "on MFS each spouse takes their own"
    assert single.seniors == 1, "a spouse age on a single return buys nothing"


# ------------------------------------------------- printing order


def test_the_forms_print_in_the_order_a_reader_checks_them_in() -> None:
    """Registration order is alphabetical because the imports are linted.

    This used to rely on import order, and a lint autofix resorted the imports
    and put Illinois between Schedule 3 and Schedule A without anything
    failing. A return whose forms are out of order cannot be checked against
    the paper.
    """
    from app.services.tax_engine.graph import compute_return
    from app.services.tax_engine.graph.forms import PRINT_ORDER

    supplied = TaxpayerFacts(
        tax_year=2025,
        filing_status=Status.SINGLE,
        taxpayer_age=40,
        resident_state="IL",
        money={"wages": D(80000)},
    )
    printed = compute_return(supplied).forms

    assert printed == PRINT_ORDER
    assert printed[0] == "Form 1040"
    assert printed.index("Schedule 1") < printed.index("Schedule A")
    assert printed.index("Schedule D") < printed.index("Form IL-1040")


def test_every_registered_form_has_a_place_in_the_printing_order() -> None:
    """A form missing from PRINT_ORDER sorts to the end silently."""
    from app.services.tax_engine.graph import registered_forms
    from app.services.tax_engine.graph.forms import PRINT_ORDER

    assert set(registered_forms()) == set(PRINT_ORDER)
