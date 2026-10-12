"""The workpaper must survive the values extraction actually produces.

Regression for a live defect that hit the whole sample corpus. The Source
Documents sheet prints every extracted field's value, and not every extracted
field is money: a filing status, a taxpayer name and a date of birth all land in
the same table. The amount column coerced each one with
``float(Decimal(str(value)))``, so a single name raised ``InvalidOperation``,
the caller's ``except Exception`` logged "Consolidated workpaper not built" and
returned None, and every package in the corpus shipped without its workpaper.

The lesson generalises past this sheet: a renderer fed extraction output is
being fed transcription, and transcription is "1,234.00", "$5,000", "(320)" and
"N/A" as often as it is a clean decimal.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

import app.services as services_package
from app.models.enums import OutputArtifactType
from app.services.consolidated_workpaper import (
    ConsolidatedWorkpaperBuilder,
    WorkpaperInputs,
    build_consolidated_workpaper,
)
from app.services.tax_engine.form_1040 import (
    Form1040Calculator,
    IncomeInputs,
    PaymentInputs,
    TaxpayerProfile,
)
from app.services.tax_engine.tax_tables import FilingStatusTax


def _engine_inputs() -> dict[str, object]:
    return {
        "profile": TaxpayerProfile(
            tax_year=2025, filing_status=FilingStatusTax.SINGLE
        ),
        "income": IncomeInputs(wages=Decimal(83704)),
        "payments": PaymentInputs(federal_withheld=Decimal(12666)),
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,234.00", 1234.0),
        ("$5,000", 5000.0),
        ("(320)", -320.0),
        ("  8 250.50 ", 8250.5),
        ("-893.86", -893.86),
        (Decimal("42.5"), 42.5),
        (7, 7.0),
    ],
)
def test_the_numbers_a_page_is_transcribed_into_still_parse(text, expected) -> None:
    assert ConsolidatedWorkpaperBuilder._number(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text", ["A TAXPAYER", "married_joint", "01/02/1958", "N/A", "", None, "—"]
)
def test_a_value_that_is_not_money_is_not_forced_to_be(text) -> None:
    """None, not zero. Zero in a money column is a figure; this is not one."""
    assert ConsolidatedWorkpaperBuilder._number(text) is None


def test_a_name_in_the_provenance_table_does_not_cost_the_workbook() -> None:
    """The defect exactly: one non-numeric row, and no workpaper at all."""
    inputs = _engine_inputs()
    content = build_consolidated_workpaper(
        WorkpaperInputs(
            computed_return=Form1040Calculator().compute(**inputs),  # type: ignore[arg-type]
            engine_inputs=inputs,
            identity={"taxpayer_name": "A TAXPAYER"},
            field_provenance={
                "wages": [
                    {"document_type": "w2", "amount": "83,704.00", "page": "3"}
                ],
                # The rows that used to abort the build.
                "taxpayer_name": [
                    {"document_type": "w2", "amount": "A TAXPAYER", "page": "3"}
                ],
                "filing_status": [
                    {
                        "document_type": "client_organizer",
                        "amount": "Single",
                        "page": "1",
                    }
                ],
            },
            review_items=[],
            documents=[{"document_type": "w2", "pages": 1, "confidence": 0.97}],
            confidence_scores={"wages": 0.98},
            workflow_id="wf-test",
        )
    )

    # An xlsx is a zip; this asserts a real workbook came back rather than None.
    assert content[:2] == b"PK"
    assert len(content) > 5_000


def test_every_artifact_type_named_in_a_service_is_a_real_member() -> None:
    """`OutputArtifactType.WORKPAPER` is not a member, and nothing said so.

    The reference sat immediately *after* a `try` whose body always raised, so
    it was unreachable for the life of the feature. The moment the Decimal
    coercion above was fixed, the builder succeeded, the `AttributeError`
    escaped — it is outside the `except` — and the whole output stage failed
    where it had previously only logged. Two bugs in a row behind one broad
    `except`; this pins the second kind.
    """
    services = Path(services_package.__file__).parent
    pattern = re.compile(r"OutputArtifactType\.([A-Z][A-Z_]*)")

    missing: list[str] = []
    for path in sorted(services.rglob("*.py")):
        for name in pattern.findall(path.read_text(encoding="utf-8")):
            if not hasattr(OutputArtifactType, name):
                missing.append(f"{path.name}: OutputArtifactType.{name}")

    assert not missing, "; ".join(missing)
