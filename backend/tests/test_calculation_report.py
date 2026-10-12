"""Phase 4: the calculation report, its model-written wording, and the gate on it.

The validator tests are the ones to read first. A model explanation is allowed
to *describe* a line and never to add a figure to it - rule 3 - and "about
84,000" is a figure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from app.services.calculation_report import (
    HEADLINE,
    Explanation,
    build_report,
    engine_explanation,
    explained_lines,
)
from app.services.calculation_report_pdf import render_html, render_pdf
from app.services.explanation_validator import (
    allowed_numbers,
    numbers_in,
    validate_explanation,
)
from app.services.graph_provenance_service import (
    DocumentRow,
    ExtractionRow,
    UnplacedFigure,
    WorkflowReturn,
)
from app.services.report_explainer import ReportExplainer
from app.services.tax_engine.graph import (
    Dependent,
    SourceFact,
    TaxpayerFacts,
    compute_return,
)
from app.services.tax_engine.graph.forms import PRINT_ORDER
from app.services.tax_engine.tax_tables import FilingStatusTax as Status

# ------------------------------------------------------------- validator

ALLOWED = allowed_numbers(D(83800), [D(88000), D(4200)], "88,000 - 4,200 = 83,800", "line 11a")


@pytest.mark.parametrize(
    "text",
    [
        "Your income of $88,000, less 4,200 of adjustments, leaves 83,800.",
        "88000.00 minus 4200 is 83,800.00.",
        "This is line 11a: adjusted gross income.",
        "Adjusted gross income is your income after adjustments.",
    ],
)
def test_provenance_numbers_pass_in_any_spelling(text: str) -> None:
    assert validate_explanation(text, ALLOWED) == []


@pytest.mark.parametrize(
    ("text", "offender"),
    [
        ("That is about 84,000.", "84,000"),
        ("The standard deduction of $15,750 then applies.", "$15,750"),
        ("Roughly 5% of income was adjusted away.", "5%"),
        ("Your income was about fifty thousand dollars.", "thousand"),
        ("In 2024 this would have differed.", "2024"),
    ],
)
def test_any_number_outside_the_provenance_is_rejected(text: str, offender: str) -> None:
    assert offender in validate_explanation(text, ALLOWED)


def test_a_negative_is_described_by_its_size() -> None:
    allowed = allowed_numbers(D(-3000))
    assert validate_explanation("A loss of 3,000 is carried here.", allowed) == []


def test_an_empty_explanation_is_not_an_explanation() -> None:
    assert validate_explanation("   ", ALLOWED) == ["empty explanation"]


def test_numbers_are_read_as_values() -> None:
    assert numbers_in("$1,234.50 and 7 and 12%") == [D("1234.50"), D(7), D(12)]


# ------------------------------------------------------------- fixtures

MONEY = {
    "wages": D(88000),
    "taxable_interest": D(1200),
    "ordinary_dividends": D(3000),
    "qualified_dividends": D(2000),
    "federal_withheld_w2": D(9100),
}


def _source(field_name: str, extraction_id: str, page: int, amount: D) -> SourceFact:
    return SourceFact(
        field=field_name,
        document_id="doc-w2" if field_name != "taxable_interest" else "doc-int",
        document_type="w2" if field_name != "taxable_interest" else "1099_int",
        page=page,
        confidence=D("0.97"),
        amount=amount,
        extraction_id=extraction_id,
    )


def _loaded(*, dependents: tuple[Dependent, ...] = (), unplaced: tuple[UnplacedFigure, ...] = ()) -> WorkflowReturn:
    facts = TaxpayerFacts(
        tax_year=2025,
        filing_status=Status.SINGLE,
        taxpayer_age=40,
        dependents=dependents,
        money=MONEY,
        provenance={
            "wages": _source("wages", "x-wages", 1, D(88000)),
            "taxable_interest": _source("taxable_interest", "x-int", 3, D(1200)),
            "ordinary_dividends": _source("ordinary_dividends", "x-div", 2, D(3000)),
            "qualified_dividends": _source("qualified_dividends", "x-qd", 2, D(2000)),
            "federal_withheld_w2": _source("federal_withheld_w2", "x-fw", 1, D(9100)),
        },
    )
    return WorkflowReturn(
        result=compute_return(facts),
        unplaced=unplaced,
        notes=(),
        documents=(
            DocumentRow("doc-w2", "w2", 1, 2, ocr_mean_confidence=0.93),
            DocumentRow("doc-int", "1099_int", 3, 3, ocr_mean_confidence=0.71),
        ),
        extractions=(
            ExtractionRow("x-wages", "wages", "doc-w2", "w2", 1, 0.97),
            ExtractionRow("x-fw", "federal_withheld", "doc-w2", "w2", 1, 0.96),
            ExtractionRow("x-div", "ordinary_dividends", "doc-w2", "w2", 2, 0.95),
            ExtractionRow("x-qd", "qualified_dividends", "doc-w2", "w2", 2, 0.95),
            ExtractionRow("x-int", "taxable_interest", "doc-int", "1099_int", 3, 0.62, requires_review=True),
            ExtractionRow("x-name", "taxpayer_name", "doc-w2", "w2", 1, 0.99),
        ),
    )


def _report(loaded: WorkflowReturn | None = None, **kwargs: Any) -> Any:
    return build_report(loaded or _loaded(), workflow_id="wf-1", generated_at="today", **kwargs)


# ------------------------------------------------------------- 4.1 / 4.2


def test_forms_come_in_official_order_line_by_line_with_every_part() -> None:
    report = _report()
    order = [s.form for s in report.forms]
    assert order == [f for f in PRINT_ORDER if f in order]

    form_1040 = report.forms[0]
    assert form_1040.form == "Form 1040" and form_1040.used
    loaded = _loaded()
    assert [line.node_id for line in form_1040.lines] == [
        line.node_id for line in loaded.result.form("Form 1040")
    ]
    line_1a = next(line for line in form_1040.lines if line.node_id == "f1040.l1a")
    assert line_1a.amount == D(88000)
    assert line_1a.formula
    assert [i.node_id for i in line_1a.inputs] == ["facts.wages"]
    assert line_1a.sources[0].document_id == "doc-w2"
    assert line_1a.reference


def test_a_schedule_the_return_does_not_use_is_named_not_printed() -> None:
    schedule_1 = next(s for s in _report().forms if s.form == "Schedule 1")
    assert not schedule_1.used
    assert schedule_1.lines == ()


def test_a_worksheet_is_reported_in_full_when_a_line_used_it() -> None:
    (worksheet,) = _report().worksheets
    assert worksheet.form == "Qualified Dividends and Capital Gain Tax Worksheet"
    loaded = _loaded()
    assert len(worksheet.lines) == len(loaded.result.form(worksheet.form))
    assert all(section.form != worksheet.form for section in _report().forms)


# ------------------------------------------------------------- 4.3


def test_each_document_lists_what_was_read_and_where_it_was_used() -> None:
    documents = {d.document_id: d for d in _report().documents}
    w2 = {f.field: f for f in documents["doc-w2"].fields}

    assert "f1040.l1a" in w2["wages"].used_on
    assert w2["wages"].amount == D(88000)


@pytest.mark.security
def test_a_read_the_return_does_not_use_carries_no_value() -> None:
    """An unused row may be a name or a date of birth. The report is a deliverable."""
    documents = {d.document_id: d for d in _report().documents}
    name = next(f for f in documents["doc-w2"].fields if f.field == "taxpayer_name")
    assert name.amount is None
    assert name.used_on == ()
    assert name.note


# ------------------------------------------------------------- 4.4


def test_validation_names_what_disagrees_is_missing_or_was_read_poorly() -> None:
    loaded = _loaded(
        dependents=(Dependent("DEPENDENT_001", "child", age=8, qualifies_for_child_tax_credit=True),),
        unplaced=(UnplacedFigure("business_income", D(12000), "Schedule C is not built"),),
    )
    summary = {key: str(loaded.result.amount(node_id) or 0) for _, node_id, key in HEADLINE if key}
    summary["total_income"] = "1"  # the pipeline disagrees on one figure
    report = _report(loaded, pipeline_summary=summary)
    checks = {c.name: c for c in report.validation.checks}

    agreement = checks["The graph engine agrees with the pipeline's calculator"]
    assert agreement.passed is False
    assert any("f1040.l9" in f for f in agreement.findings)

    assert checks["Every figure read is on a line"].passed is False
    assert checks["Every figure traces to a document, an authority or a stated nil"].passed
    assert not report.fileable

    assert "f1040.l19" in {n for n, _, _ in report.validation.unsupported}
    assert [r.field for r in report.validation.low_confidence] == ["taxable_interest"]


def test_the_cross_check_says_when_it_could_not_run() -> None:
    checks = {c.name: c for c in _report().validation.checks}
    assert checks["The graph engine agrees with the pipeline's calculator"].passed is None


# ------------------------------------------------------------- 4.5


@dataclass
class FakeGemini:
    replies: dict[str, str]
    enabled: bool = True
    calls: int = 0
    prompts: list[str] = field(default_factory=list)
    fail: Exception | None = None

    def generate_json(self, *, prompt: str, **_: Any) -> Any:
        self.calls += 1
        self.prompts.append(prompt)
        if self.fail is not None:
            raise self.fail

        @dataclass
        class Reply:
            data: dict[str, Any]
            model_name: str = "test-model"
            is_stub: bool = False

        return Reply({"explanations": dict(self.replies)})


def test_a_model_explanation_is_shown_only_if_it_adds_no_number(tmp_path: Path) -> None:
    loaded = _loaded()
    gemini = FakeGemini(
        {
            "f1040.l1a": "Your wages of 88,000 from your W-2 go here.",
            "f1040.l9": "All your income adds up to about 92,000.",
        }
    )
    batch = ReportExplainer(gemini, tmp_path).explain(  # type: ignore[arg-type]
        "wf-1", explained_lines(loaded), 2025
    )

    assert batch.explanations["f1040.l1a"] == Explanation(
        "Your wages of 88,000 from your W-2 go here.", by="model"
    )
    rejected = batch.explanations["f1040.l9"]
    assert rejected.by == "engine"
    assert rejected.rejected == ("92,000",)
    assert rejected.text == engine_explanation(loaded.result["f1040.l9"])

    report = _report(loaded, explanations=batch.explanations)
    check = next(
        c for c in report.validation.checks if c.name.startswith("Explanations use only")
    )
    assert check.passed is False
    assert check.findings == ("f1040.l9: introduced 92,000",)


def test_replies_are_cached_and_revalidated(tmp_path: Path) -> None:
    loaded = _loaded()
    gemini = FakeGemini({"f1040.l1a": "Wages of 88,000."})
    explainer = ReportExplainer(gemini, tmp_path)  # type: ignore[arg-type]
    explainer.explain("wf-1", explained_lines(loaded), 2025)
    explainer.explain("wf-1", explained_lines(loaded), 2025)
    assert gemini.calls == 1, "the same return is explained once"

    # A reply already on disk is still checked: tampering, or a tighter
    # validator, applies without refetching.
    path = tmp_path / "wf-1.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["explanations"]["f1040.l1a"] = "Wages of 90,000."
    path.write_text(json.dumps(stored), encoding="utf-8")
    batch = explainer.explain("wf-1", explained_lines(loaded), 2025)
    assert batch.explanations["f1040.l1a"].by == "engine"
    assert gemini.calls == 1


def test_a_failed_model_call_leaves_the_engine_wording_and_says_why(tmp_path: Path) -> None:
    gemini = FakeGemini({}, fail=RuntimeError("boom"))
    batch = ReportExplainer(gemini, tmp_path).explain(  # type: ignore[arg-type]
        "wf-1", explained_lines(_loaded()), 2025
    )
    assert batch.explanations == {}
    assert "RuntimeError" in batch.note


def test_with_the_model_off_nothing_is_sent(tmp_path: Path) -> None:
    gemini = FakeGemini({"f1040.l1a": "x"}, enabled=False)
    batch = ReportExplainer(gemini, tmp_path).explain(  # type: ignore[arg-type]
        "wf-1", explained_lines(_loaded()), 2025
    )
    assert gemini.calls == 0
    assert "off" in batch.note


@pytest.mark.security
def test_the_explanation_prompt_carries_no_document_or_extraction_ids(tmp_path: Path) -> None:
    gemini = FakeGemini({})
    ReportExplainer(gemini, tmp_path).explain(  # type: ignore[arg-type]
        "wf-1", explained_lines(_loaded()), 2025
    )
    (prompt,) = gemini.prompts
    for identifier in ("doc-w2", "doc-int", "x-wages", "x-int", "wf-1"):
        assert identifier not in prompt


# ------------------------------------------------------------- 4.6


def test_the_pdf_renders_every_section() -> None:
    import fitz

    loaded = _loaded(
        dependents=(Dependent("DEPENDENT_001", "child", age=8, qualifies_for_child_tax_credit=True),)
    )
    pdf = render_pdf(_report(loaded))
    assert pdf.startswith(b"%PDF")
    document = fitz.open(stream=pdf, filetype="pdf")
    text = "".join(page.get_text() for page in document)
    for heading in (
        "Calculation report - tax year 2025",
        "1. Forms, line by line",
        "2. Worksheets",
        "3. Source documents",
        "4. Validation",
    ):
        assert heading in text
    # An unsupported line prints as such, never as a zero.
    assert "not computed" in text


def test_the_json_export_round_trips() -> None:
    body = json.loads(json.dumps(_report().to_dict()))
    assert body["tax_year"] == 2025
    assert body["forms"][0]["form"] == "Form 1040"
    assert {"forms", "worksheets", "documents", "validation", "headline"} <= set(body)


def test_the_html_escapes_what_it_prints() -> None:
    loaded = _loaded(unplaced=(UnplacedFigure("business_income", D(1), "<script>"),))
    html = render_html(_report(loaded))
    assert "<script>" not in html


# ------------------------------------------------------------- routes


def test_the_report_routes_export_json_and_pdf(client, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from tests.test_graph_provenance_service import _seed_workflow

    workflow_id, _ = _seed_workflow(tmp_path / "output")

    as_json = client.get(f"/api/workflows/{workflow_id}/graph/report.json")
    assert as_json.status_code == 200
    body = as_json.json()
    assert body["workflow_id"] == workflow_id
    assert body["forms"][0]["lines"]

    as_pdf = client.get(f"/api/workflows/{workflow_id}/graph/report.pdf")
    assert as_pdf.status_code == 200
    assert as_pdf.headers["content-type"] == "application/pdf"
    assert as_pdf.content.startswith(b"%PDF")

    events = client.get(f"/api/workflows/{workflow_id}/audit").json()["items"]
    kinds = {e["payload"].get("artifact_type") for e in events if e.get("payload")}
    assert {"calculation_report_json", "calculation_report_pdf"} <= kinds
