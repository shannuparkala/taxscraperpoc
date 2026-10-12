"""Form 7203 must reproduce the accountant's own worksheet.

The benchmark is the CS-2 accountant copy, which prints every line of the form.
Matching it end to end is the point: this figure reaches the return through no
other route, and the reference software declines to carry it at all.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.services.tax_engine.form_7203 import (
    DebtCharacter,
    ShareholderBasisInputs,
    compute_form_7203,
)


@pytest.fixture(name="cs2")
def _cs2() -> ShareholderBasisInputs:
    """Salza Communications, Inc. — the figures printed on the prepared form."""
    return ShareholderBasisInputs(
        stock_basis_begin=D(0),
        debt_basis_begin=D(6641),
        ordinary_business_income=D(161),
        nondeductible_expenses=D(1189),
        losses_and_deductions=D(100),
        loan_balance_begin=D(43302),
        loan_balance_end=D(36842),
        character=DebtCharacter.OPEN_ACCOUNT,
    )


def test_cs2_reproduces_the_accountant_worksheet(cs2):
    result = compute_form_7203(cs2)

    # Part I — income cannot cover the nondeductible expenses, so basis floors.
    assert result.stock_basis_begin == D(0)
    assert result.stock_basis_end == D(0)

    # Part II Section A — the loan movement is the repayment.
    assert result.loan_balance_begin == D(43302)
    assert result.principal_repaid == D(6460)
    assert result.loan_balance_end == D(36842)

    # Part II Section B — line 25 on the prepared form reads .153365.
    assert result.basis_ratio == D("0.153365")
    assert result.nontaxable_repayment == D(991)

    # Part II Section C — the figure the whole form exists to produce.
    assert result.reportable_gain == D(5469)
    assert result.destination == "Form 4797 Part II (ordinary)"


def test_character_decides_where_the_gain_goes(cs2):
    ordinary = compute_form_7203(cs2)
    assert ordinary.is_ordinary
    assert "4797" in ordinary.destination

    cs2.character = DebtCharacter.FORMAL_NOTE
    capital = compute_form_7203(cs2)
    assert not capital.is_ordinary
    assert "Schedule D" in capital.destination
    # The amount is identical; only where it lands changes.
    assert capital.reportable_gain == ordinary.reportable_gain


def test_full_basis_makes_the_repayment_tax_free():
    result = compute_form_7203(
        ShareholderBasisInputs(
            debt_basis_begin=D(43302),
            loan_balance_begin=D(43302),
            loan_balance_end=D(36842),
        )
    )
    assert result.nontaxable_repayment == D(6460)
    assert result.reportable_gain == D(0)


def test_no_repayment_produces_no_gain():
    result = compute_form_7203(
        ShareholderBasisInputs(
            debt_basis_begin=D(6641),
            loan_balance_begin=D(43302),
            loan_balance_end=D(43302),
        )
    )
    assert result.principal_repaid == D(0)
    assert result.reportable_gain == D(0)


def test_a_loan_increase_is_not_a_negative_repayment():
    result = compute_form_7203(
        ShareholderBasisInputs(
            debt_basis_begin=D(6641),
            loan_balance_begin=D(36842),
            loan_balance_end=D(43302),
        )
    )
    assert result.principal_repaid == D(0)
    assert result.reportable_gain == D(0)


def test_missing_opening_basis_is_flagged_not_silently_assumed():
    """Zero basis makes the whole repayment taxable; that must be visible."""
    result = compute_form_7203(
        ShareholderBasisInputs(
            debt_basis_begin=D(0),
            loan_balance_begin=D(43302),
            loan_balance_end=D(36842),
        )
    )
    assert result.reportable_gain == D(6460)
    assert any("Opening debt basis was not supplied" in w for w in result.warnings)


def test_the_gain_is_always_explained(cs2):
    result = compute_form_7203(cs2)
    joined = " ".join(result.warnings)
    assert "No document states this figure" in joined
    assert "5469" in joined or "5,469" in joined


def test_stock_basis_absorbs_before_debt_basis():
    """Reversing the order overstates debt basis and understates the gain."""
    inputs = ShareholderBasisInputs(
        stock_basis_begin=D(5000),
        debt_basis_begin=D(10000),
        ordinary_business_income=D(1000),
        nondeductible_expenses=D(2000),
        loan_balance_begin=D(10000),
        loan_balance_end=D(10000),
    )
    result = compute_form_7203(inputs)
    # 5,000 + 1,000 income, less 2,000 nondeductible, all absorbed by stock.
    assert result.stock_basis_end == D(4000)
    # Debt basis is untouched, because stock basis covered the expenses.
    assert result.debt_basis_end == D(10000)


def test_excess_nondeductible_expenses_reduce_debt_basis():
    inputs = ShareholderBasisInputs(
        stock_basis_begin=D(0),
        debt_basis_begin=D(10000),
        ordinary_business_income=D(100),
        nondeductible_expenses=D(1100),
        loan_balance_begin=D(10000),
        loan_balance_end=D(10000),
    )
    result = compute_form_7203(inputs)
    assert result.stock_basis_end == D(0)
    # 1,100 of expenses, 100 absorbed by stock basis; 1,000 hits debt basis.
    assert result.debt_basis_end == D(9000)


def test_serialization_is_json_safe(cs2):
    import json

    payload = compute_form_7203(cs2).to_dict()
    json.dumps(payload)
    assert payload["reportable_gain"] == "5469"
    assert payload["destination"] == "Form 4797 Part II (ordinary)"
    for key, value in payload.items():
        if key not in {"warnings"}:
            assert isinstance(value, str), key
