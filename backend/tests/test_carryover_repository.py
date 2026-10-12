"""Carryovers must survive the year boundary, and never be invented.

The failure this closes: Schedule D carryovers and the prior-year overpayment
appear on no current-year document, so a pipeline reading only this year's
workpaper reported them as zero. On the CS-2 sample that understated the capital
loss carryover by 4,511 and dropped 725 of payments, on a return that otherwise
footed.
"""

from __future__ import annotations

import json
from decimal import Decimal as D

import pytest

from app.services.carryover_repository import (
    CarryoverBalance,
    CarryoverKind,
    CarryoverRepository,
    Origin,
    taxpayer_key,
)
from app.services.tax_engine.form_1040 import (
    CapitalGainInputs,
    Form1040Calculator,
    IncomeInputs,
    PaymentInputs,
    TaxpayerProfile,
)
from app.services.tax_engine.tax_tables import FilingStatusTax


@pytest.fixture(name="repo")
def _repo(tmp_path):
    return CarryoverRepository(tmp_path / "CarryoverRepository.json")


def _balance(kind: str, amount: D, to_year: int = 2025) -> CarryoverBalance:
    return CarryoverBalance(
        kind=kind, amount=amount, to_year=to_year, origin=Origin.MANUAL_ENTRY
    )


# --- Identity -------------------------------------------------------------


def test_the_key_is_stable_and_does_not_contain_the_identifier():
    first = taxpayer_key(identifier="412-88-7364")
    assert first == taxpayer_key(identifier="412-88-7364")
    assert "412" not in first
    assert "7364" not in first
    assert first != taxpayer_key(identifier="412-88-7365")


def test_name_and_dob_are_a_fallback_key():
    key = taxpayer_key(name="Dawn Salza", dob="1959-08-29")
    assert key
    assert key == taxpayer_key(name="  dawn salza ", dob="1959-08-29")
    assert key != taxpayer_key(name="Dawn Salza", dob="1960-08-29")


def test_no_key_without_something_stable_to_key_on():
    """A collision here would hand one taxpayer another's carryovers."""
    assert taxpayer_key() is None
    assert taxpayer_key(name="Dawn Salza") is None
    assert taxpayer_key(dob="1959-08-29") is None


# --- Round trip -----------------------------------------------------------


def test_a_return_deposits_what_it_carries_forward(repo):
    """A 2024 loss year should fund 2025's Schedule D."""
    result = Form1040Calculator().compute(
        profile=TaxpayerProfile(tax_year=2024, filing_status=FilingStatusTax.SINGLE),
        income=IncomeInputs(taxable_interest=D(500)),
        capital_gains=CapitalGainInputs(short_term_gain=D(-7511)),
        payments=PaymentInputs(
            federal_withheld=D(1000), apply_overpayment_to_next_year=D(725)
        ),
    )
    recorded = repo.record_from_return("key-1", result, workflow_id="wf-9")

    kinds = {b.kind for b in recorded}
    assert CarryoverKind.SHORT_TERM_CAPITAL_LOSS in kinds
    assert CarryoverKind.OVERPAYMENT_APPLIED in kinds
    assert all(b.to_year == 2025 for b in recorded)
    assert all(b.origin == Origin.COMPUTED_RETURN for b in recorded)
    # Provenance has to name the line, not just say "computed".
    assert any("Schedule D line 6" in b.origin_detail for b in recorded)


def test_next_year_withdraws_them_as_engine_fields(repo):
    repo.record(
        "key-1",
        [
            _balance(CarryoverKind.SHORT_TERM_CAPITAL_LOSS, D(4511)),
            _balance(CarryoverKind.OVERPAYMENT_APPLIED, D(725)),
        ],
    )
    fields = repo.engine_inputs("key-1", 2025)
    assert fields["short_term_loss_carryover"] == "4511"
    assert fields["prior_year_overpayment_applied"] == "725"
    # Nothing leaks into the wrong year.
    assert repo.engine_inputs("key-1", 2026) == {}
    assert repo.engine_inputs("key-1", 2024) == {}


def test_carryovers_are_scoped_to_one_taxpayer(repo):
    repo.record("key-a", [_balance(CarryoverKind.SHORT_TERM_CAPITAL_LOSS, D(4511))])
    assert repo.engine_inputs("key-a", 2025)
    assert repo.engine_inputs("key-b", 2025) == {}


def test_rerunning_a_year_replaces_rather_than_doubles(repo):
    for _ in range(3):
        repo.record("key-1", [_balance(CarryoverKind.SHORT_TERM_CAPITAL_LOSS, D(4511))])
    assert repo.engine_inputs("key-1", 2025)["short_term_loss_carryover"] == "4511"
    assert len(repo.carryovers_into("key-1", 2025)) == 1


def test_an_absent_balance_is_absent_not_zero(repo):
    """The caller must tell 'nothing carried' apart from 'we do not know'."""
    assert repo.carryovers_into("nobody", 2025) == []
    assert "short_term_loss_carryover" not in repo.engine_inputs("nobody", 2025)


def test_the_cs2_gap_closes_when_the_prior_year_is_known(repo):
    """End to end: the two figures that made CS-2 miss, restored from memory."""
    repo.record(
        "cs2",
        [
            _balance(CarryoverKind.SHORT_TERM_CAPITAL_LOSS, D(4511)),
            _balance(CarryoverKind.OVERPAYMENT_APPLIED, D(725)),
        ],
    )
    remembered = repo.engine_inputs("cs2", 2025)

    result = Form1040Calculator().compute(
        profile=TaxpayerProfile(
            tax_year=2025, filing_status=FilingStatusTax.SINGLE, age_65_or_older=1
        ),
        income=IncomeInputs(
            taxable_interest=D(214),
            qualified_dividends=D(1793),
            ordinary_dividends=D(5012),
            social_security=D(27648),
            rental_income=D(161),
        ),
        capital_gains=CapitalGainInputs(
            short_term_gain=D(-894),
            short_term_loss_carryover=D(remembered["short_term_loss_carryover"]),
            long_term_gain=D(7345),
            capital_gain_distributions=D(4698),
        ),
        payments=PaymentInputs(
            prior_year_overpayment_applied=D(
                remembered["prior_year_overpayment_applied"]
            ),
            apply_overpayment_to_next_year=D(725),
        ),
    )

    def line(number: str) -> D:
        return next(entry.amount for entry in result.lines if entry.number == number)

    # Schedule D lands on the accountant's figure once the carryover is applied.
    assert line("7") == D("6638.00")
    # And the payments line stops being zero.
    assert result.total_payments == D("725.00")


# --- Robustness -----------------------------------------------------------


def test_a_corrupt_repository_does_not_take_down_a_return(tmp_path):
    path = tmp_path / "CarryoverRepository.json"
    path.write_text("{ this is not json", encoding="utf-8")
    repo = CarryoverRepository(path)

    assert repo.carryovers_into("key-1", 2025) == []
    repo.record("key-1", [_balance(CarryoverKind.SHORT_TERM_CAPITAL_LOSS, D(1))])
    assert repo.engine_inputs("key-1", 2025)


def test_one_malformed_entry_does_not_hide_the_others(repo, tmp_path):
    repo.record("key-1", [_balance(CarryoverKind.SHORT_TERM_CAPITAL_LOSS, D(4511))])

    path = tmp_path / "CarryoverRepository.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["taxpayers"]["key-1"]["balances"].append({"kind": "broken", "amount": "abc"})
    path.write_text(json.dumps(data), encoding="utf-8")

    assert repo.engine_inputs("key-1", 2025)["short_term_loss_carryover"] == "4511"


def test_the_repository_holds_no_plaintext_identity(repo, tmp_path):
    result = Form1040Calculator().compute(
        profile=TaxpayerProfile(tax_year=2024, filing_status=FilingStatusTax.SINGLE),
        income=IncomeInputs(taxable_interest=D(500)),
        capital_gains=CapitalGainInputs(short_term_gain=D(-7511)),
    )
    repo.record_from_return(taxpayer_key(identifier="412-88-7364"), result)

    written = (tmp_path / "CarryoverRepository.json").read_text(encoding="utf-8")
    assert "412-88-7364" not in written
    assert "412" not in written
