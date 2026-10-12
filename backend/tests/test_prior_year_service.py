"""Last year's return must be harvested when present and asked for when not.

Missing prior-year data was the largest single error source across the nine-case
batch. On the one return that decomposes exactly it accounted for 5,502 of a
9,241 overstatement of AGI, and the pipeline raised no item mentioning it.
"""

from __future__ import annotations

from decimal import Decimal as D

from app.models.enums import DocumentType
from app.services.carryover_repository import CarryoverKind
from app.services.prior_year_service import PriorYearService, upload_request

INVESTMENTS = {"long_term_gain": "7345", "short_term_gain": "-894"}


def evaluate(normalized=None, types=(), year=2025, known=None):
    return PriorYearService().evaluate(
        normalized=normalized or {},
        document_types=set(types),
        tax_year=year,
        already_known=set(known or ()),
    )


# --- When it is missing ---------------------------------------------------


def test_investments_without_a_carryover_figure_ask_for_last_year():
    outcome = evaluate(normalized=INVESTMENTS)
    assert not outcome.found
    assert outcome.should_request_upload
    assert "short_term_loss_carryover" in outcome.missing


def test_the_request_names_the_document_and_what_depends_on_it():
    outcome = evaluate(normalized=INVESTMENTS)
    request = upload_request(outcome, 2025)

    assert "2024 tax return" in request["title"]
    # A reviewer must be able to act without reading the code.
    assert "capital loss" in request["description"]
    assert "treated as zero" in request["description"]


def test_a_shareholder_loan_without_basis_asks_too():
    """Without opening debt basis the whole repayment is taxed."""
    outcome = evaluate(normalized={"loan_balance_begin": "43302", "loan_balance_end": "36842"})
    assert "debt_basis_begin" in outcome.missing


def test_a_balance_already_in_the_repository_is_not_asked_for_again():
    outcome = evaluate(
        normalized=INVESTMENTS,
        known=(
            CarryoverKind.SHORT_TERM_CAPITAL_LOSS,
            CarryoverKind.OVERPAYMENT_APPLIED,
        ),
    )
    assert outcome.missing == []
    assert not outcome.should_request_upload


def test_a_figure_stated_this_year_is_not_asked_for():
    outcome = evaluate(
        normalized={
            **INVESTMENTS,
            "short_term_loss_carryover": "4511",
            "prior_year_overpayment_applied": "725",
        }
    )
    assert outcome.missing == []


# --- When it is present ---------------------------------------------------


def test_a_prior_year_return_is_harvested_into_balances():
    outcome = evaluate(
        normalized={
            "short_term_loss_carryover": "4511",
            "prior_year_overpayment_applied": "725",
            "debt_basis_begin": "6641",
        },
        types=(DocumentType.PRIOR_YEAR_RETURN.value,),
    )
    assert outcome.found
    kinds = {b.kind: b.amount for b in outcome.balances}
    assert kinds[CarryoverKind.SHORT_TERM_CAPITAL_LOSS] == D(4511)
    assert kinds[CarryoverKind.OVERPAYMENT_APPLIED] == D(725)
    assert kinds[CarryoverKind.DEBT_BASIS] == D(6641)
    assert not outcome.should_request_upload


def test_balances_record_where_they_came_from():
    outcome = evaluate(
        normalized={"short_term_loss_carryover": "4511"},
        types=(DocumentType.PRIOR_YEAR_RETURN.value,),
    )
    balance = outcome.balances[0]
    assert balance.origin == "prior_year_document"
    assert "prior-year return" in balance.origin_detail
    assert balance.to_year == 2025


def test_zero_and_unreadable_values_are_not_recorded_as_balances():
    """A zero carryover is not a carryover; it is an absence."""
    outcome = evaluate(
        normalized={"short_term_loss_carryover": "0", "long_term_loss_carryover": "abc"},
        types=(DocumentType.PRIOR_YEAR_RETURN.value,),
    )
    assert outcome.balances == []


def test_carryovers_are_stored_positive_whichever_sign_they_arrive_with():
    outcome = evaluate(
        normalized={"short_term_loss_carryover": "-4511"},
        types=(DocumentType.PRIOR_YEAR_RETURN.value,),
    )
    assert outcome.balances[0].amount == D(4511)


def test_a_return_with_nothing_to_carry_still_asks_only_about_payments():
    """Asking for a document that cannot change the answer trains people to ignore it."""
    outcome = evaluate(normalized={"wages": "50000"})
    assert "short_term_loss_carryover" not in outcome.missing
    assert outcome.missing == ["prior_year_overpayment_applied"]
