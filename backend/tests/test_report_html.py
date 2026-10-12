"""The standalone HTML report must be safe to open and faithful to the screen.

Its content is model-extracted document text, so the two failures that matter
are an unescaped value becoming markup and a rule URL becoming a script link in
a file someone opens years later with no application around it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.services.explanation_service import (
    FlowSection,
    LineExplanation,
    Operand,
    Provenance,
    ReturnExplanation,
    ValidationStatus,
)
from app.services.report_html_service import render_return_report, report_filename
from app.tax_knowledge.rule_citations import Citation, TaxRule

RULE = TaxRule(
    id="test_rule",
    title="Standard deduction",
    plain_english="A flat amount a filer may subtract.",
    irc_section="IRC §63(c)",
    citations=(
        Citation("Publication 501", "https://www.irs.gov/pub501"),
        Citation("Hostile", "javascript:alert(1)"),
    ),
)


def _explanation(label: str = "Wages, salaries, tips") -> ReturnExplanation:
    line = LineExplanation(
        line="1a",
        label=label,
        amount=Decimal(125000),
        section=FlowSection.INCOME,
        rule=RULE,
        formula="w2_wages",
        narrative="Wages reported on one W-2.",
        operands=[
            Operand(
                label="W-2 wages",
                amount=Decimal(125000),
                provenance=Provenance.SOURCE_DOCUMENT,
                documents=("w2",),
                detail="Box 1",
            )
        ],
        provenance=Provenance.SOURCE_DOCUMENT,
        status=ValidationStatus.VERIFIED,
        arithmetic_checked=True,
    )
    return ReturnExplanation(
        tax_year=2025,
        filing_status="married_filing_jointly",
        deduction_method="standard",
        summary={
            "filing_status": "Married filing jointly",
            "total_income": "125000",
            "adjusted_gross_income": "125000",
            "deduction_method": "standard",
            "deductions": "30000",
            "taxable_income": "95000",
            "credits": "0",
            "total_tax": "12345.67",
            "payments": "15000",
            "refund": "2654.33",
            "amount_owed": "0",
            "applied_to_next_year": "0",
        },
        lines=[line],
        assumptions=[],
        warnings=[],
        unverified_citations=[],
    )


def _render(explanation: ReturnExplanation) -> str:
    return render_return_report(
        explanation,
        source_filename="workpaper.pdf",
        workflow_id="wf-1",
        generated_at=datetime(2026, 4, 15, 12, 0, tzinfo=UTC),
    )


@pytest.mark.security
def test_extracted_text_cannot_become_markup() -> None:
    html = _render(_explanation('<img src=x onerror="alert(1)">'))

    assert "<img" not in html
    assert '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;' in html


@pytest.mark.security
def test_only_http_citation_links_survive() -> None:
    html = _render(_explanation())

    assert "javascript:" not in html
    assert "https://www.irs.gov/pub501" in html


def test_report_is_self_contained() -> None:
    html = _render(_explanation())

    assert html.startswith("<!doctype html>")
    assert "<script" not in html
    # No external fetch: a stored report must render with no network at all.
    assert 'src="http' not in html
    assert "<link" not in html


def test_report_carries_the_figures_the_screen_shows() -> None:
    html = _render(_explanation())

    assert "$125,000" in html
    assert "$12,345.67" in html
    assert "Wages, salaries, tips" in html
    assert "Publication 501" in html


def test_filename_identifies_the_return_and_stays_path_safe() -> None:
    name = report_filename(_explanation(), '../../Client "Smith" 2025.pdf')

    assert name == "tax-report-Client-Smith-2025-2025.html"
