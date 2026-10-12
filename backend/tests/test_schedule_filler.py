"""The schedules must carry the same figures as the Form 1040 they support.

These schedules add no tax logic — every number was already computed for the
1040 and then discarded. So the test that matters is not "is the arithmetic
right" but "did the figure land on the line the accountant put it on", which is
checked by reading the values back out of the filled PDFs.
"""

from __future__ import annotations

import json
from decimal import Decimal as D

import fitz
import pytest

from app.services.schedule_filler import (
    RESOURCES,
    TEMPLATES,
    _money,
    render_schedules,
)
from app.services.tax_engine.form_1040 import (
    AdjustmentInputs,
    CapitalGainInputs,
    DeductionInputs,
    Form1040Calculator,
    IncomeInputs,
    PaymentInputs,
    TaxpayerProfile,
)
from app.services.tax_engine.tax_tables import FilingStatusTax

STEMS = {
    "Schedule 1": "f1040s1",
    "Schedule 1-A": "f1040s1a",
    "Schedule 2": "f1040s2",
    "Schedule 3": "f1040s3",
    "Schedule A": "f1040sa",
    "Schedule B": "f1040sb",
    "Schedule D": "f1040sd",
}


def _cs2_return(**overrides):
    profile = TaxpayerProfile(
        tax_year=2025, filing_status=FilingStatusTax.SINGLE, age_65_or_older=1
    )
    income = IncomeInputs(
        taxable_interest=D(214),
        qualified_dividends=D(1793),
        ordinary_dividends=D(5012),
        social_security=D(27648),
        other_gains=D(5469),
        rental_income=D(161),
    )
    capital_gains = CapitalGainInputs(
        short_term_gain=D(-894),
        short_term_loss_carryover=D(4511),
        long_term_gain=D(7345),
        capital_gain_distributions=D(4698),
    )
    adjustments = AdjustmentInputs()
    deductions = overrides.get("deductions", DeductionInputs())
    payments = overrides.get("payments", PaymentInputs())
    result = Form1040Calculator().compute(
        profile=profile,
        income=income,
        adjustments=adjustments,
        deductions=deductions,
        payments=payments,
        capital_gains=capital_gains,
    )
    return {
        "result": result,
        "income": income,
        "adjustments": adjustments,
        "deductions": deductions,
        "capital_gains": capital_gains,
        "payments": payments,
        "profile": profile,
    }


def _cs2_return_with_business(amount):
    """The same taxpayer with Schedule C income, so Schedule 2 has content."""
    inputs = _cs2_return()
    inputs["income"].business_income = amount
    inputs["result"] = Form1040Calculator().compute(
        profile=inputs["profile"],
        income=inputs["income"],
        adjustments=inputs["adjustments"],
        deductions=inputs["deductions"],
        payments=inputs["payments"],
        capital_gains=inputs["capital_gains"],
    )
    return inputs


def _read_back(schedule) -> dict[str, str]:
    """Line number -> printed value, read out of the filled PDF."""
    stem = STEMS[schedule.name]
    mapping = json.loads(
        (RESOURCES / f"{stem}_2025_map.json").read_text(encoding="utf-8")
    )["line_to_field"]
    reverse = {field: line for line, field in mapping.items()}

    values: dict[str, str] = {}
    with fitz.open(stream=schedule.content, filetype="pdf") as document:
        for page in document:
            for widget in page.widgets():
                short = (widget.field_name or "").split(".")[-1]
                if widget.field_value and short in reverse:
                    values[reverse[short]] = widget.field_value
    return values


@pytest.fixture(name="schedules")
def _schedules():
    return {s.name: s for s in render_schedules(**_cs2_return())}


# --- Templates ------------------------------------------------------------


def test_every_template_and_its_map_are_present():
    for key, template in TEMPLATES.items():
        assert template.available, f"{key} template or map missing from resources"


def test_maps_were_derived_not_guessed():
    """Each map must carry the review metadata the deriver emits."""
    for template in TEMPLATES.values():
        data = json.loads(
            (RESOURCES / f"{template.stem}_2025_map.json").read_text(encoding="utf-8")
        )
        assert data["line_to_field"], template.stem
        assert "needs_review" in data, template.stem


# --- Values ---------------------------------------------------------------


def test_schedule_1_matches_the_accountant(schedules):
    values = _read_back(schedules["Schedule 1"])
    assert values["4"] == "5,469"    # Form 4797 other gains
    assert values["5"] == "161"      # Schedule E
    assert values["10"] == "5,630"   # carries to Form 1040 line 8


def test_schedule_d_matches_the_accountant(schedules):
    values = _read_back(schedules["Schedule D"])
    assert values["6"] == "4,511"      # short-term loss carried in
    assert values["7"] == "(5,405)"    # net short-term
    assert values["13"] == "4,698"     # capital gain distributions
    assert values["15"] == "12,043"    # net long-term
    assert values["16"] == "6,638"     # carries to Form 1040 line 7a


def test_schedule_b_matches_the_accountant(schedules):
    values = _read_back(schedules["Schedule B"])
    assert values["4"] == "214"        # carries to Form 1040 line 2b
    assert values["6"] == "5,012"      # carries to Form 1040 line 3b


def test_schedule_1a_matches_the_accountant(schedules):
    values = _read_back(schedules["Schedule 1-A"])
    assert values["31"] == "20,653"
    assert values["32"] == "75,000"
    assert values["33"] == "(54,347)"  # below the threshold, so no phase-out
    assert values["38"] == "6,000"     # carries to Form 1040 line 13b


def test_schedule_totals_agree_with_the_form_1040_they_support(schedules):
    """A schedule that disagrees with its own 1040 line is worse than none."""
    bundle = _cs2_return()
    result = bundle["result"]

    assert _read_back(schedules["Schedule 1"])["10"] == _money(
        result.line("8").amount
    )
    assert _read_back(schedules["Schedule D"])["16"] == _money(
        result.line("7").amount
    )


# --- Which schedules appear ----------------------------------------------


def test_schedule_a_is_omitted_when_the_standard_deduction_wins(schedules):
    """Including the losing side of the comparison would misstate the return."""
    assert "Schedule A" not in schedules


def test_schedule_a_appears_when_itemizing():
    bundle = _cs2_return(
        deductions=DeductionInputs(
            mortgage_interest=D(19000),
            state_local_income_tax=D(9000),
            charitable_cash=D(2000),
        )
    )
    rendered = {s.name: s for s in render_schedules(**bundle)}
    assert bundle["result"].deduction_method == "itemized"
    assert "Schedule A" in rendered
    values = _read_back(rendered["Schedule A"])
    assert values["8a"] == "19,000"
    assert values["14"] == "2,000"


def test_an_empty_schedule_is_not_produced():
    """A blank Schedule B says the preparer did not know whether it applied."""
    profile = TaxpayerProfile(tax_year=2025, filing_status=FilingStatusTax.SINGLE)
    income = IncomeInputs(wages=D(50000))
    result = Form1040Calculator().compute(
        profile=profile, income=income, payments=PaymentInputs()
    )
    rendered = {
        s.name
        for s in render_schedules(
            result=result,
            income=income,
            adjustments=AdjustmentInputs(),
            deductions=DeductionInputs(),
            capital_gains=CapitalGainInputs(),
            payments=PaymentInputs(),
            profile=profile,
        )
    }
    assert "Schedule B" not in rendered
    assert "Schedule D" not in rendered


def test_a_mismatched_tax_year_renders_nothing():
    """Filling a 2024 return onto a 2025 form looks official and is wrong."""
    profile = TaxpayerProfile(tax_year=2024, filing_status=FilingStatusTax.SINGLE)
    income = IncomeInputs(taxable_interest=D(500))
    result = Form1040Calculator().compute(
        profile=profile, income=income, payments=PaymentInputs()
    )
    assert (
        render_schedules(
            result=result,
            income=income,
            adjustments=AdjustmentInputs(),
            deductions=DeductionInputs(),
            capital_gains=CapitalGainInputs(),
            payments=PaymentInputs(),
            profile=profile,
        )
        == []
    )


# --- Formatting -----------------------------------------------------------


def test_negatives_are_parenthesised_not_signed():
    assert _money(D(-5405)) == "(5,405)"
    assert _money(D(5405)) == "5,405"
    assert _money(D(0)) == "0"


def test_filenames_sort_into_filing_order(schedules):
    names = sorted(s.filename for s in schedules.values())
    assert names[0].startswith("1.1 - Schedule 1 ")
    assert "Schedule D" in names[-1]


def test_schedule_filenames_do_not_collide_with_the_package_guides():
    """A delivered package held both "2 - START HERE.md" and "2 - Schedule 1"."""
    names = [s.filename for s in render_schedules(**_cs2_return())]
    assert all(name.startswith("1.") for name in names)
    assert len(set(names)) == len(names)


# --- Schedules 2 and 3 ----------------------------------------------------


def test_no_schedule_2_when_there_are_no_other_taxes(schedules):
    """CS-2 has no self-employment income; an empty Schedule 2 is not a form."""
    assert "Schedule 2" not in schedules


def test_schedule_2_carries_self_employment_tax_to_line_23():
    rendered = {
        s.name: s
        for s in render_schedules(**_cs2_return_with_business(D(40000)))
    }
    values = _read_back(rendered["Schedule 2"])
    result = _cs2_return_with_business(D(40000))["result"]
    assert values["4"] == _money(result.other_taxes)   # self-employment tax
    assert values["21"] == _money(result.other_taxes)  # total -> Form 1040 line 23
    assert result.other_taxes > D(0)


def test_schedule_3_reports_other_credits_without_the_child_tax_credit():
    """Line 19 already carries the CTC; repeating it here doubles the credit."""
    rendered = {
        s.name: s
        for s in render_schedules(
            **_cs2_return(payments=PaymentInputs(other_nonrefundable_credits=D(300)))
        )
    }
    values = _read_back(rendered["Schedule 3"])
    assert values["6z"] == "300"
    assert values["8"] == "300"  # carries to Form 1040 line 20


def test_no_schedule_3_without_other_credits(schedules):
    assert "Schedule 3" not in schedules
