"""The Illinois return: IL-1040, Schedule ICR and Schedule IL-WIT.

Line wording from ``docs/tax-research/il-1040-icr-il-wit-2025-line-by-line.md``,
read off the Department's own PDFs (R-12/25). Every figure below is invented.

The first test in this file is the one that matters most and is not about
arithmetic at all: a state's forms must not appear on a return filed somewhere
else. CLAUDE.md rule 7 is about the chatbot answering a state question from
another state's law; the same mistake on the engine side is worse, because the
lines look worked.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.services.tax_engine.graph import TaxpayerFacts, compute_return
from app.services.tax_engine.tax_tables import FilingStatusTax as Status

IL_FORMS = ("Form IL-1040", "Schedule ICR", "Schedule IL-WIT")


def facts(status: Status = Status.SINGLE, state: str | None = "IL", **kw) -> TaxpayerFacts:
    money = kw.pop("money", {})
    kw.setdefault("taxpayer_age", 40)
    return TaxpayerFacts(
        tax_year=2025, filing_status=status, resident_state=state, money=money, **kw
    )


# ================================================== jurisdiction


def test_a_return_filed_outside_illinois_carries_no_illinois_lines() -> None:
    """The lines would look worked, which is worse than their being absent."""
    elsewhere = compute_return(facts(state="TX", money={"wages": D(80000)}))
    federal_only = compute_return(facts(state=None, money={"wages": D(80000)}))

    for result in (elsewhere, federal_only):
        assert not any(form in result.forms for form in IL_FORMS)
        assert result.get("il1040.l12") is None


def test_an_illinois_return_carries_all_three_illinois_forms() -> None:
    result = compute_return(facts(money={"wages": D(80000)}))

    for form in IL_FORMS:
        assert form in result.forms


def test_residency_is_matched_without_regard_to_case() -> None:
    lower = compute_return(facts(state="il", money={"wages": D(80000)}))

    assert "Form IL-1040" in lower.forms


# ================================================== IL-1040


def test_illinois_starts_from_federal_adjusted_gross_income() -> None:
    """Line 1 takes Form 1040 line 11a, so a federal change moves Illinois too."""
    result = compute_return(
        facts(money={"wages": D(80000), "f8889_l2": D(4300)})
    )

    assert result.amount("f1040.l11a") == D(80000) - D(4300)
    assert result.amount("il1040.l1") == result.amount("f1040.l11a")


def test_the_flat_rate_is_applied_to_net_income_not_to_base_income() -> None:
    result = compute_return(facts(money={"wages": D(80000)}))

    assert result.amount("il1040.l9") == D(80000)
    assert result.amount("il1040.l11") == D(80000) - D(2850)
    assert result.amount("il1040.l12") == (D(80000) - D(2850)) * D("0.0495")


def test_retirement_income_subtracted_by_illinois_lowers_the_state_tax_only() -> None:
    """Illinois does not tax most retirement income; the federal return does."""
    without = compute_return(
        facts(money={"wages": D(40000), "pensions_taxable": D(30000)})
    )
    with_subtraction = compute_return(
        facts(money={"wages": D(40000), "pensions_taxable": D(30000),
                     "il1040_l5": D(30000)})
    )

    assert with_subtraction.amount("f1040.l9") == without.amount("f1040.l9")
    assert with_subtraction.amount("il1040.l9") == D(40000)
    assert with_subtraction.amount("il1040.l12") < without.amount("il1040.l12")


@pytest.mark.parametrize(
    ("status", "allowance"),
    [
        (Status.SINGLE, D(2850)),
        (Status.MARRIED_JOINT, D(5700)),
        (Status.MARRIED_SEPARATE, D(2850)),
        (Status.HEAD_OF_HOUSEHOLD, D(2850)),
    ],
)
def test_the_exemption_allowance_depends_on_filing_status(status, allowance) -> None:
    result = compute_return(facts(status, money={"wages": D(80000)}))

    assert result.amount("il1040.l10a") == allowance


def test_the_exemption_allowance_is_a_cliff_not_a_taper() -> None:
    """A dollar of extra income at the threshold costs the whole allowance."""
    at = compute_return(facts(money={"wages": D(250000)}))
    over = compute_return(facts(money={"wages": D("250000.01")}))

    assert at.amount("il1040.l10a") == D(2850)
    assert over.amount("il1040.l10a") == 0
    assert "not available" in over["il1040.l10a"].formula


def test_the_cliff_sits_twice_as_high_on_a_joint_return() -> None:
    at = compute_return(
        facts(Status.MARRIED_JOINT, money={"wages": D(500000)})
    )
    over = compute_return(
        facts(Status.MARRIED_JOINT, money={"wages": D("500000.01")})
    )

    assert at.amount("il1040.l10a") == D(5700)
    assert over.amount("il1040.l10a") == 0


def test_age_and_blindness_each_add_a_thousand_per_checked_box() -> None:
    plain = compute_return(facts(money={"wages": D(80000)}))
    senior = compute_return(facts(taxpayer_age=70, money={"wages": D(80000)}))
    both = compute_return(
        facts(Status.MARRIED_JOINT, taxpayer_age=70, spouse_age=70,
              taxpayer_blind=True, money={"wages": D(80000)})
    )

    assert plain.amount("il1040.l10b") == 0
    assert senior.amount("il1040.l10b") == D(1000)
    assert both.amount("il1040.l10b") == D(2000)
    assert both.amount("il1040.l10c") == D(1000)


def test_a_spouse_over_65_adds_a_box_only_on_a_joint_return() -> None:
    """The same entitlement rule as the federal additional amount. Trap 33."""
    joint = compute_return(
        facts(Status.MARRIED_JOINT, taxpayer_age=70, spouse_age=70,
              money={"wages": D(80000)})
    )
    separate = compute_return(
        facts(Status.MARRIED_SEPARATE, taxpayer_age=70, spouse_age=70,
              money={"wages": D(80000)})
    )

    assert joint.amount("il1040.l10b") == D(2000)
    assert separate.amount("il1040.l10b") == D(1000)


def test_negative_net_income_produces_no_tax_and_no_refund_of_tax_never_paid() -> None:
    result = compute_return(facts(money={"wages": D(1000)}))

    assert result.amount("il1040.l11") == 0
    assert result.amount("il1040.l12") == 0
    assert result.amount("il1040.l14") == 0


def test_illinois_withholding_is_not_federal_withholding() -> None:
    """They are different boxes on the same W-2."""
    result = compute_return(
        facts(money={"wages": D(80000), "federal_withheld_w2": D(9000),
                     "illinois_tax_withheld": D(3600)})
    )

    assert result.amount("il1040.l25") == D(3600)
    assert result.amount("f1040.l25d") == D(9000)


def test_a_state_refund_and_a_state_balance_are_never_both_positive() -> None:
    for withheld in (D(0), D(3000), D(9000)):
        result = compute_return(
            facts(money={"wages": D(80000), "illinois_tax_withheld": withheld})
        )
        assert not (result.amount("il1040.l32") > 0 and result.amount("il1040.l33") > 0)


def test_penalty_and_donations_come_out_of_the_overpayment_before_the_refund() -> None:
    result = compute_return(
        facts(money={"wages": D(80000), "illinois_tax_withheld": D(6000),
                     "il1040_l35": D(100)})
    )

    assert result.amount("il1040.l36") == D(100)
    assert result.amount("il1040.l37") == result.amount("il1040.l32") - D(100)


# ================================================== Schedule ICR


def test_the_property_tax_credit_is_five_percent_of_the_tax_paid() -> None:
    result = compute_return(
        facts(money={"wages": D(80000), "ilicr_l4a": D(8000)})
    )

    assert result.amount("ilicr.l4g") == D(400)
    assert result.amount("ilicr.l5") == D(400)
    assert result.amount("il1040.l16") == result.amount("ilicr.l13")


def test_a_business_portion_of_the_property_tax_bill_earns_no_credit() -> None:
    result = compute_return(
        facts(money={"wages": D(80000), "ilicr_l4a": D(8000), "ilicr_l4e": D(3000)})
    )

    assert result.amount("ilicr.l4f") == D(5000)
    assert result.amount("ilicr.l4g") == D(250)


def test_the_k12_credit_applies_its_floor_then_its_rate_then_its_cap() -> None:
    """Any other order lands near enough to look right and is wrong."""
    result = compute_return(
        facts(money={"wages": D(80000), "ilicr_l7a": D(2250)})
    )

    assert result.amount("ilicr.l7c") == D(2000), "the first 250 earns nothing"
    assert result.amount("ilicr.l7d") == D(500), "a quarter of the rest"


def test_the_k12_credit_stops_at_its_cap() -> None:
    result = compute_return(
        facts(money={"wages": D(80000), "ilicr_l7a": D(20000)})
    )

    assert result.amount("ilicr.l7d") == D(750)


def test_k12_expenses_below_the_floor_earn_nothing_rather_than_a_negative() -> None:
    result = compute_return(
        facts(money={"wages": D(80000), "ilicr_l7a": D(200)})
    )

    assert result.amount("ilicr.l7c") == 0
    assert result.amount("ilicr.l7d") == 0


def test_the_credits_queue_and_together_cannot_exceed_the_tax() -> None:
    """Each takes the lesser of itself and the room the last one left.

    Computing each against the full tax lets the three exceed it, which is a
    refund Illinois does not give.
    """
    result = compute_return(
        facts(money={
            "wages": D(20000),          # a small Illinois tax
            "ilicr_l4a": D(100000),     # a property tax credit far larger
            "ilicr_l7a": D(20000),      # and a K-12 credit on top
            "ilicr_volunteer_certificates": D(1),
        })
    )

    tax = result.amount("il1040.l14")
    assert result.amount("ilicr.l13") <= tax
    assert result.amount("il1040.l19") == 0
    assert result.amount("il1040.l18") <= tax


def test_the_volunteer_emergency_worker_credit_needs_a_certificate() -> None:
    without = compute_return(facts(money={"wages": D(80000)}))
    with_cert = compute_return(
        facts(money={"wages": D(80000), "ilicr_volunteer_certificates": D(1)})
    )

    assert without.amount("ilicr.l10c") == 0
    assert with_cert.amount("ilicr.l10c") == D(500)
    assert with_cert.amount("ilicr.l13") == D(500)


def test_schedule_icr_reads_the_tax_it_is_offsetting_from_il1040() -> None:
    result = compute_return(
        facts(money={"wages": D(80000), "ilicr_l4a": D(8000)})
    )

    assert result.amount("ilicr.l1") == result.amount("il1040.l14")


# ================================================== provenance


def test_every_illinois_line_shows_its_arithmetic() -> None:
    result = compute_return(
        facts(money={"wages": D(80000), "illinois_tax_withheld": D(3600),
                     "ilicr_l4a": D(8000)})
    )

    for form in IL_FORMS:
        for line in result.form(form):
            assert line.formula, f"{line.node_id} reported a figure with no arithmetic"
            assert any(ch.isdigit() for ch in line.formula), line.node_id


def test_the_illinois_rate_and_exemption_cite_the_department_that_sets_them() -> None:
    result = compute_return(facts(money={"wages": D(80000)}))

    for node_id in ("il1040.l12", "il1040.l10a"):
        line = result[node_id]
        assert line.authority is not None, node_id
        assert line.authority.url.startswith("https://"), node_id


def test_the_illinois_constants_are_reported_as_unconfirmed() -> None:
    """Their ILCS citations could not be checked: ilga.gov is off the allow-list.

    The figures came off the Department's own form and rate page, which is why
    they are used at all - but the pairing is not confirmed, and a return that
    rests on them says so rather than looking settled.
    """
    result = compute_return(facts(money={"wages": D(80000)}))

    assert "const.il_flat_rate" in result.unverified_authorities
    assert "const.il_exemption_allowance" in result.unverified_authorities
