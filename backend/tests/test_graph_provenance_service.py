"""A workflow's stored figures, turned into the graph's facts with their sources.

Two vocabularies meet in the adapter, and trap 17 is what happens when a field
falls between them: the figure is absent from the return and nothing says so.
The first test holds the mapping exhaustive; the rest hold that a figure keeps
the document, page and box it was read from on the way across.
"""

from __future__ import annotations

import io
import json
from decimal import Decimal as D
from typing import Any

import pytest

from app.services.graph_provenance_service import (
    FIELD_MAP,
    NOT_PLACED,
    WITHHOLDING,
    DocumentRow,
    ExtractionRow,
    build_facts,
)
from app.services.tax_engine.graph import MONEY_FIELDS, compute_return
from app.services.workflow_orchestrator import ENGINE_MONEY_FIELDS


def test_every_pipeline_money_field_is_placed_or_says_why_not() -> None:
    accounted = set(FIELD_MAP) | set(NOT_PLACED) | {WITHHOLDING}
    missing = sorted(set(ENGINE_MONEY_FIELDS) - accounted)
    assert not missing, f"map these, or list them in NOT_PLACED: {missing}"
    assert not set(FIELD_MAP) & set(NOT_PLACED)


def test_every_mapped_target_is_a_field_the_graph_reads() -> None:
    unknown = sorted(set(FIELD_MAP.values()) - set(MONEY_FIELDS))
    assert not unknown


DOCUMENTS = [
    DocumentRow("doc-w2a", "w2", 1, 2),
    DocumentRow("doc-w2b", "w2", 3, 3),
    DocumentRow("doc-int", "1099_int", 4, 4),
]

ROWS = [
    ExtractionRow("x-1", "wages", "doc-w2a", "w2", 2, 0.97, [10, 20, 60, 30]),
    ExtractionRow("x-2", "wages", "doc-w2b", "w2", 3, 0.88, None),
    ExtractionRow("x-3", "federal_withheld", "doc-w2a", "w2", 2, 0.95, None),
    ExtractionRow("x-4", "federal_withheld", "doc-int", "1099_int", 4, 0.9, None),
    ExtractionRow("x-5", "taxable_interest", "doc-int", "1099_int", 4, 0.99, None),
]


def _stored(**normalized: Any) -> dict[str, Any]:
    return {
        "normalized": {
            "wages": "50000",
            "federal_withheld": "6100",
            "taxable_interest": "320",
            "qualifying_children": "2",
            **normalized,
        },
        "field_provenance": {
            "wages": [
                {"document_type": "w2", "amount": "30000", "page": "2"},
                {"document_type": "w2", "amount": "20000", "page": "3"},
            ],
            "federal_withheld": [
                {"document_type": "w2", "amount": "6000", "page": "2"},
                {"document_type": "1099_int", "amount": "100", "page": "4"},
            ],
            "taxable_interest": [
                {"document_type": "1099_int", "amount": "320", "page": "4"},
            ],
        },
        "confidence_scores": {},
        "profile": {
            "tax_year": 2025,
            "filing_status": "married_joint",
            "taxpayer_age": 67,
            "spouse_age": 60,
            "qualifying_children": 2,
            "other_dependents": 0,
            "state_code": None,
        },
    }


def test_each_contribution_keeps_its_document_page_confidence_and_box() -> None:
    built = build_facts(_stored(), ROWS, DOCUMENTS)
    wages = built.facts.sources("wages")

    assert built.facts.amount("wages") == D(50000)
    assert [(s.document_id, s.page, s.amount) for s in wages] == [
        ("doc-w2a", 2, D(30000)),
        ("doc-w2b", 3, D(20000)),
    ]
    assert wages[0].bbox == (D(10), D(20), D(60), D(30))
    assert wages[0].confidence == D("0.97")
    assert wages[0].extraction_id == "x-1"
    assert wages[1].bbox is None, "no box is recorded rather than a guessed one"


def test_withholding_is_split_by_the_form_that_reported_it() -> None:
    built = build_facts(_stored(), ROWS, DOCUMENTS)
    assert built.facts.amount("federal_withheld_w2") == D(6000)
    assert built.facts.amount("federal_withheld_1099") == D(100)
    assert built.facts.amount("federal_withheld_other") is None
    assert built.facts.source("federal_withheld_1099").document_id == "doc-int"  # type: ignore[union-attr]


def test_withholding_no_document_claims_goes_to_25c_and_says_so() -> None:
    stored = _stored(federal_withheld="6500")
    built = build_facts(stored, ROWS, DOCUMENTS)
    assert built.facts.amount("federal_withheld_other") == D(400)
    assert any("line 25c" in note for note in built.notes)


def test_a_count_beside_the_figures_is_not_read_as_money() -> None:
    built = build_facts(_stored(), ROWS, DOCUMENTS)
    assert "qualifying_children" not in {u.field for u in built.unplaced}
    assert len(built.facts.dependents) == 2


def test_a_figure_no_graph_line_takes_is_surfaced_not_dropped() -> None:
    built = build_facts(_stored(business_income="12000"), ROWS, DOCUMENTS)
    (unplaced,) = built.unplaced
    assert (unplaced.field, unplaced.amount) == ("business_income", D(12000))
    assert "Schedule C" in unplaced.reason


def test_a_return_missing_read_income_is_not_fileable() -> None:
    """A graph return without the business income looks finished. It is not."""
    from app.services.graph_provenance_service import WorkflowReturn

    stored = _stored(business_income="12000")
    stored["profile"]["qualifying_children"] = 0  # keep Schedule 8812 out of it
    built = build_facts(stored, ROWS, DOCUMENTS)
    assert not built.notes
    missing = WorkflowReturn(compute_return(built.facts), built.unplaced, built.notes)
    assert missing.result.fileable, "the graph alone cannot see the gap"
    assert not missing.fileable

    # Shareholder basis is not a Form 1040 input; leaving it off loses nothing.
    stored = _stored(distributions="4000")
    stored["profile"]["qualifying_children"] = 0
    basis = build_facts(stored, ROWS, DOCUMENTS)
    (unplaced,) = basis.unplaced
    assert not unplaced.blocks_filing
    assert WorkflowReturn(compute_return(basis.facts), basis.unplaced, basis.notes).fileable


def test_a_loss_carryover_enters_schedule_d_as_a_negative() -> None:
    built = build_facts(_stored(long_term_loss_carryover="3000"), ROWS, DOCUMENTS)
    assert built.facts.amount("schd_l14") == D(-3000)


def test_ages_come_from_the_profile_and_only_the_joint_spouse_counts() -> None:
    built = build_facts(_stored(), ROWS, DOCUMENTS)
    assert (built.facts.taxpayer_age, built.facts.spouse_age) == (67, 60)
    assert built.facts.seniors == 1


def test_a_run_recorded_before_ages_uses_the_count_and_says_so() -> None:
    stored = _stored()
    stored["profile"].pop("taxpayer_age")
    stored["profile"].pop("spouse_age")
    stored["profile"]["age_65_or_older"] = 1
    built = build_facts(stored, ROWS, DOCUMENTS)
    assert built.facts.seniors == 1
    assert any("Ages were not recorded" in note for note in built.notes)


def test_the_adapted_facts_trace_to_the_documents_on_the_return() -> None:
    result = compute_return(build_facts(_stored(), ROWS, DOCUMENTS).facts)
    documents = {s.document_id for s in result["f1040.l9"].sources}
    assert documents == {"doc-w2a", "doc-w2b", "doc-int"}


# ---------------------------------------------------------------- routes


def _seed_workflow(tmp_output: Any) -> tuple[str, str]:
    """A workflow, a document with a figure box, and stored engine inputs."""
    from app.core.db import init_database, session_scope
    from app.models.database_models import (
        Document,
        ExtractionResult,
        UploadedFile,
        Workflow,
    )

    init_database()
    with session_scope() as session:
        upload = UploadedFile(
            original_filename="invented.pdf",
            stored_filename="invented.bin",
            content_type="application/pdf",
            extension=".pdf",
            size_bytes=1,
            content_hash="0" * 64,
        )
        session.add(upload)
        session.flush()
        workflow = Workflow(uploaded_file_id=upload.id)
        session.add(workflow)
        session.flush()
        document = Document(
            uploaded_file_id=upload.id,
            document_type="w2",
            page_start=1,
            page_end=2,
            page_count=2,
            layout={
                "pages": [
                    {
                        "page": 2,
                        "width": 612.0,
                        "height": 792.0,
                        "figures": [{"text": "50,000.00", "bbox": [10, 20, 60, 30]}],
                    }
                ]
            },
        )
        session.add(document)
        session.flush()
        session.add(
            ExtractionResult(
                document_id=document.id,
                workflow_id=workflow.id,
                field_name="wages",
                masked_value="50000",
                confidence=0.97,
                source_page=2,
                source_bbox=[10, 20, 60, 30],
            )
        )
        workflow_id, document_id = workflow.id, document.id

    stored = _stored()
    stored["field_provenance"] = {
        "wages": [{"document_type": "w2", "amount": "50000", "page": "2"}]
    }
    stored["normalized"] = {"wages": "50000"}
    (tmp_output / "explanations").mkdir(parents=True, exist_ok=True)
    (tmp_output / "explanations" / f"{workflow_id}.json").write_text(
        json.dumps(stored), encoding="utf-8"
    )
    return workflow_id, document_id


@pytest.fixture()
def seeded(tmp_path: Any) -> tuple[str, str]:
    return _seed_workflow(tmp_path / "output")


def test_the_graph_route_returns_every_line_with_its_sources(client, seeded) -> None:  # type: ignore[no-untyped-def]
    workflow_id, document_id = seeded
    body = client.get(f"/api/workflows/{workflow_id}/graph").json()

    line = next(row for row in body["lines"] if row["node_id"] == "f1040.l1a")
    assert line["amount"] == "50000"
    (source,) = line["sources"]
    assert source["document_id"] == document_id
    assert source["page"] == 2
    assert source["bbox"] == ["10", "20", "60", "30"]


def test_the_explain_route_walks_a_total_to_its_document(client, seeded) -> None:  # type: ignore[no-untyped-def]
    workflow_id, document_id = seeded
    tree = client.get(f"/api/workflows/{workflow_id}/graph/explain/f1040.l9").json()

    def leaves(node: dict) -> list[dict]:  # type: ignore[type-arg]
        if not node["children"]:
            return [node]
        return [leaf for child in node["children"] for leaf in leaves(child)]

    wages = next(leaf for leaf in leaves(tree) if leaf["node_id"] == "facts.wages")
    assert wages["leaf"] == "source"
    assert wages["sources"][0]["document_id"] == document_id

    missing = client.get(f"/api/workflows/{workflow_id}/graph/explain/f1040.l999")
    assert missing.status_code == 404


def test_the_source_page_route_serves_the_masked_zone_only(client, seeded) -> None:  # type: ignore[no-untyped-def]
    workflow_id, document_id = seeded
    page = client.get(
        f"/api/workflows/{workflow_id}/documents/{document_id}/pages/2"
    ).json()
    assert page["figures"] == [{"text": "50,000.00", "bbox": [10.0, 20.0, 60.0, 30.0]}]
    assert (page["width"], page["height"]) == (612.0, 792.0)

    outside = client.get(f"/api/workflows/{workflow_id}/documents/{document_id}/pages/9")
    assert outside.status_code == 404


@pytest.mark.security
def test_a_processed_document_page_holds_no_original_values(client) -> None:  # type: ignore[no-untyped-def]
    """End to end: the drill-down's page is the masked zone and nothing more."""
    from tests.test_security_invariants import FORBIDDEN_LITERALS, SENSITIVE_DOCUMENT

    upload = client.post(
        "/api/files/upload",
        files={"file": ("w2.txt", io.BytesIO(SENSITIVE_DOCUMENT.encode()), "text/plain")},
    ).json()
    workflow = client.post(
        f"/api/workflows/{upload['id']}/process", json={"tax_year": 2025}
    ).json()
    detail = client.get(f"/api/workflows/{workflow['id']}").json()
    assert detail["documents"], "the pipeline produced no document to open"

    for document in detail["documents"]:
        for number in range(document["page_start"], document["page_end"] + 1):
            page = client.get(
                f"/api/workflows/{workflow['id']}/documents/{document['id']}/pages/{number}"
            ).json()
            body = json.dumps(page)
            for literal in FORBIDDEN_LITERALS:
                assert literal not in body


@pytest.mark.security
def test_the_pipeline_keeps_figure_boxes_and_no_identifier(client) -> None:  # type: ignore[no-untyped-def]
    """A text-layer PDF through the real masking stage.

    The wage figure comes out with a box on its page; the SSN beside it, in
    the surrogate range and money-free in shape, leaves no trace in the layout.
    """
    import fitz

    pdf = fitz.open()
    page = pdf.new_page()
    lines = [
        "2025 Form W-2 Wage and Tax Statement",
        "Employee social security number 666-12-3456",
        "Employer identification number 00-1234567",
        "Box 1 Wages, tips, other compensation 52,340.00",
        "Box 2 Federal income tax withheld 6,120.00",
        "Box 3 Social security wages 52,340.00",
        "Employee address 100 Main Street Springfield IL 62701",
    ] * 3
    for index, text in enumerate(lines):
        page.insert_text((72, 72 + 18 * index), text, fontsize=10)
    body = pdf.tobytes()
    pdf.close()

    upload = client.post(
        "/api/files/upload",
        files={"file": ("invented-w2.pdf", io.BytesIO(body), "application/pdf")},
    ).json()
    workflow = client.post(
        f"/api/workflows/{upload['id']}/process", json={"tax_year": 2025}
    ).json()
    detail = client.get(f"/api/workflows/{workflow['id']}").json()

    figures: list[str] = []
    for document in detail["documents"]:
        response = client.get(
            f"/api/workflows/{workflow['id']}/documents/{document['id']}/pages/1"
        ).json()
        figures.extend(f["text"] for f in response["figures"])
        serialised = json.dumps(response)
        for literal in ("666-12-3456", "666123456", "00-1234567"):
            assert literal not in serialised

    assert "52,340.00" in figures
    assert "6,120.00" in figures
    # Only figures have boxes: no identifier, ZIP or year survives as one.
    assert set(figures) == {"52,340.00", "6,120.00"}
