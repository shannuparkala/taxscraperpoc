"""Phase 3: every figure carries its provenance, and explain() walks it to source.

The property ``/trace-check`` checks on a real return, checked here on an
invented one: every line of every form terminates, through ``explain``, in a
document, an authority or a stated nil - and nothing else.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.services.tax_engine.graph import (
    Basis,
    Dependent,
    LeafKind,
    SourceFact,
    TaxpayerFacts,
    build_graph,
    compute_return,
)
from app.services.tax_engine.tax_tables import FilingStatusTax as Status

MONEY = {
    "wages": D(88000),
    "taxable_interest": D(1200),
    "ordinary_dividends": D(3000),
    "qualified_dividends": D(2000),
    "federal_withheld_w2": D(9100),
    "scha_l8a": D(14000),
    "scha_l5b": D(6200),
    "schd_l13": D(500),
    "illinois_tax_withheld": D(3300),
}


def _source(field: str, page: int, amount: D | None = None, doc: str = "doc-1") -> SourceFact:
    return SourceFact(
        field=field,
        document_id=doc,
        document_type="w2",
        page=page,
        confidence=D("0.96"),
        bbox=(D(10), D(20), D(60), D(30)),
        amount=amount,
    )


def _documented(**overrides: object) -> TaxpayerFacts:
    """A return on which every supplied figure names the page it came off."""
    fields: dict[str, object] = {
        "tax_year": 2025,
        "filing_status": Status.MARRIED_JOINT,
        "taxpayer_age": 44,
        "spouse_age": 41,
        "resident_state": "IL",
        "money": MONEY,
        "provenance": {
            name: _source(name, page) for page, name in enumerate(MONEY, start=1)
        },
    }
    fields.update(overrides)
    return TaxpayerFacts(**fields)  # type: ignore[arg-type]


def test_every_line_of_every_form_traces_to_a_document_an_authority_or_a_nil() -> None:
    result = compute_return(_documented())
    assert result.fileable

    for node_id in result.order:
        tree = result.explain(node_id)
        assert tree.leaves(), f"{node_id} rests on nothing"
        assert not tree.untraced(), (
            f"{node_id} bottoms out in "
            f"{[(leaf.node_id, leaf.leaf) for leaf in tree.untraced()]}"
        )


def test_every_line_carries_the_whole_provenance_record() -> None:
    """Formula with numbers, inputs as read, a reference, and its sources."""
    result = compute_return(_documented())
    graph = build_graph(result.facts)

    for line in result.lines:
        assert line.reference, line.node_id
        assert line.formula, line.node_id
        if line.amount:
            # Checkbox lines say what they are in words; a figure shows its
            # arithmetic in numbers, or it is a template that never ran.
            assert any(ch.isdigit() for ch in line.formula), line.node_id
        # What the node read is exactly what it declared, and nothing more.
        read = {input_id for input_id, _ in line.inputs}
        assert read <= set(graph[line.node_id].inputs), line.node_id

    # A figure resting on a document carries the document up to the total.
    assert result["f1040.l9"].sources
    assert {s.field for s in result["f1040.l9"].sources} >= {"wages", "taxable_interest"}


def test_a_source_fact_leaf_names_document_page_field_confidence_and_box() -> None:
    result = compute_return(_documented())
    leaf = next(
        node for node in result.explain("f1040.l1a").leaves()
        if node.node_id == "facts.wages"
    )
    assert leaf.leaf is LeafKind.SOURCE
    (source,) = leaf.result.sources
    assert (source.document_id, source.page, source.field) == ("doc-1", 1, "wages")
    assert source.confidence == D("0.96")
    assert source.bbox == (D(10), D(20), D(60), D(30))


def test_a_figure_summed_from_two_documents_names_both() -> None:
    """Two W-2s make one line 1a. Naming the first sends the reviewer to half."""
    first = _source("wages", 2, D(50000), doc="doc-a")
    second = _source("wages", 7, D(38000), doc="doc-b")
    result = compute_return(_documented(provenance={"wages": (first, second)}))

    leaf = result["facts.wages"]
    assert leaf.sources == (first, second)
    assert leaf.formula == "50,000 (w2 page 2) + 38,000 (w2 page 7) = 88,000"
    assert not leaf.flags
    assert result["f1040.l1a"].sources == (first, second)


def test_contributions_that_do_not_add_up_are_flagged() -> None:
    first = _source("wages", 2, D(50000), doc="doc-a")
    second = _source("wages", 7, D(30000), doc="doc-b")
    result = compute_return(_documented(provenance={"wages": (first, second)}))

    assert result["facts.wages"].flags == ("sources account for 80,000 of 88,000",)


def test_a_source_reached_down_several_paths_is_listed_once() -> None:
    result = compute_return(_documented())
    for line in result.lines:
        assert len(line.sources) == len(set(line.sources)), line.node_id


def test_a_figure_with_no_document_named_is_what_the_trace_finds() -> None:
    result = compute_return(_documented(provenance={}))
    untraced = {leaf.node_id: leaf.leaf for leaf in result.explain("f1040.l9").untraced()}
    assert untraced["facts.wages"] is LeafKind.SUPPLIED


def test_a_shared_subtree_is_expanded_once_and_named_everywhere() -> None:
    tree = compute_return(_documented()).explain("f1040.l37")
    expanded = [n.node_id for n in tree.walk() if not n.repeated and n.leaf is None]
    assert len(expanded) == len(set(expanded))
    assert any(n.repeated for n in tree.walk())


def test_an_unsupported_line_explains_down_to_the_line_that_raised() -> None:
    household = (
        Dependent("DEPENDENT_001", "child", age=8, qualifies_for_child_tax_credit=True),
    )
    result = compute_return(_documented(dependents=household))
    assert not result.fileable

    tree = result.explain("f1040.l24")
    assert tree.result.amount is None
    unsupported = [leaf.node_id for leaf in tree.untraced() if leaf.leaf is LeafKind.UNSUPPORTED]
    assert "f1040.l19" in unsupported


def test_explaining_a_line_the_return_does_not_have_is_an_error() -> None:
    with pytest.raises(KeyError):
        compute_return(_documented()).explain("f1040.l999")


def test_the_tree_serialises_with_the_record_on_every_node() -> None:
    body = compute_return(_documented()).explain("f1040.l11a").to_dict()
    assert body["node_id"] == "f1040.l11a"
    assert body["reference"]
    assert body["children"]

    def walk(node: dict) -> None:  # type: ignore[type-arg]
        assert {"formula", "inputs", "reference", "sources", "leaf"} <= set(node)
        for child in node["children"]:
            walk(child)

    walk(body)


def test_a_statutory_leaf_cites_an_https_authority() -> None:
    result = compute_return(_documented())
    statutory = [r for r in result.results.values() if r.basis is Basis.STATUTORY]
    assert statutory, "the return rests on no constant at all"
    for leaf in statutory:
        assert leaf.authority is not None
        assert leaf.authority.url.startswith("https://"), leaf.node_id
