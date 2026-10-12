"""Accuracy fixes traced from a return that came out wrong in six ways.

The sample workpaper (Basic CS 2) produced a Form 1040 whose printed
components did not add up to its own total income, reported a business's
payroll-tax expense as the taxpayer's Social Security benefits, left the
taxable portion of those benefits blank, doubled two figures, and went out with
an SSN and no name on it. Each defect gets a test.

Every figure below is checkable by hand against the prepared return: total
income 20,653, deductions 23,750, taxable income nil, overpayment 725.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.services.tax_engine.computations import (
    capital_loss_carryover,
    schedule_d,
    senior_deduction,
    taxable_social_security,
)
from app.services.tax_engine.form_1040 import (
    CapitalGainInputs,
    DeductionInputs,
    Form1040Calculator,
    IncomeInputs,
    PaymentInputs,
    TaxpayerProfile,
)
from app.services.tax_engine.tax_tables import FilingStatusTax as Status
from app.services.workflow_orchestrator import (
    age_on,
    canonical_identity_field,
    merge_extractions,
)


def _sample_return():  # type: ignore[no-untyped-def]
    """The prepared return, from its own source figures.

    Lines 7a and 8 were once handed in as finished totals — 6,638 and 5,630 —
    because nothing explained where they came from. They are derived here from
    the schedules the preparer actually worked, so the fixture proves the
    arithmetic instead of asserting the answer:

    * 7a from Schedule D, whose short-term half is a 894 loss on the 1099-B
      *plus a 4,511 short-term loss carried in from the prior year*, and whose
      long-term half is a 7,345 gain plus 4,698 of capital gain distributions
      that appear only on Form 1099-DIV.
    * 8 from Schedule 1: line 4 carries 5,469 of ordinary gain from Form 4797
      (a shareholder loan repayment measured against prior-year debt basis on
      Form 7203), and line 5 carries 161 of S corporation income via
      Schedule E.
    """
    return Form1040Calculator().compute(
        profile=TaxpayerProfile(
            tax_year=2025, filing_status=Status.SINGLE, age_65_or_older=1
        ),
        income=IncomeInputs(
            taxable_interest=D("213.50"),
            ordinary_dividends=D("5012.35"),
            qualified_dividends=D("1792.68"),
            social_security=D(27648),
            other_gains=D(5469),
            rental_income=D(161),
        ),
        capital_gains=CapitalGainInputs(
            short_term_gain=D(-894),
            short_term_loss_carryover=D(4511),
            long_term_gain=D(7345),
            capital_gain_distributions=D(4698),
        ),
        payments=PaymentInputs(
            prior_year_overpayment_applied=D(725),
            apply_overpayment_to_next_year=D(725),
        ),
    )


def _lines(result) -> dict[str, int]:  # type: ignore[no-untyped-def]
    return {line.number: round(line.amount) for line in result.lines}


# ------------------------------------------------- §86 social security


def test_taxable_social_security_matches_the_prepared_return() -> None:
    """Line 6b is computed, never read: no document states it.

    Form SSA-1099 reports the gross benefit and is silent on the taxable
    portion, because that depends on the rest of the return. Waiting for a
    document to supply 6b left it blank and dropped $27,648 of income.
    """
    taxable = taxable_social_security(
        benefits=D(27648), other_income=D(17494), year=2025, status=Status.SINGLE
    )

    assert round(taxable) == 3159


def test_benefits_below_the_base_threshold_are_untaxed() -> None:
    assert taxable_social_security(
        benefits=D(20000), other_income=D(5000), year=2025, status=Status.SINGLE
    ) == 0


def test_taxable_benefits_never_exceed_eighty_five_percent() -> None:
    """§86's hard ceiling, regardless of how large other income gets."""
    taxable = taxable_social_security(
        benefits=D(27648), other_income=D(500000), year=2025, status=Status.SINGLE
    )

    assert taxable <= D(27648) * D("0.85")
    assert round(taxable) == round(27648 * 0.85)


def test_tax_exempt_interest_raises_provisional_income() -> None:
    """§86 counts municipal interest even though the return does not tax it."""
    without = taxable_social_security(
        benefits=D(27648), other_income=D(17494), year=2025, status=Status.SINGLE
    )
    with_muni = taxable_social_security(
        benefits=D(27648), other_income=D(17494),
        tax_exempt_interest=D(5000), year=2025, status=Status.SINGLE
    )

    assert with_muni > without


def test_an_explicit_taxable_amount_is_not_overwritten() -> None:
    """A preparer's own 6b beats recomputation from partial facts."""
    result = Form1040Calculator().compute(
        profile=TaxpayerProfile(tax_year=2025, filing_status=Status.SINGLE),
        income=IncomeInputs(
            social_security=D(27648), social_security_taxable=D(9999)
        ),
    )

    assert _lines(result)["6b"] == 9999


# ------------------------------------------------------ senior deduction


def test_age_65_gives_both_deductions_not_one() -> None:
    """They are separate provisions and both apply.

    Line 12e carries the long-standing age addition to the standard deduction
    (15,750 + 2,000); line 13b carries the 2025 Schedule 1-A senior deduction
    (6,000). Treating them as one understated deductions by 6,000.
    """
    lines = _lines(_sample_return())

    assert lines["12"] == 17750
    assert lines["13b"] == 6000
    assert lines["14"] == 23750


def test_senior_deduction_absent_below_65() -> None:
    result = Form1040Calculator().compute(
        profile=TaxpayerProfile(tax_year=2025, filing_status=Status.SINGLE),
        income=IncomeInputs(wages=D(50000)),
    )

    assert "13b" not in _lines(result)


def test_senior_deduction_phases_out_on_high_income() -> None:
    assert senior_deduction(
        seniors=1, modified_agi=D(175000), year=2025, status=Status.SINGLE
    ) == 0


def test_senior_deduction_did_not_exist_in_2024() -> None:
    assert senior_deduction(
        seniors=1, modified_agi=D(20000), year=2024, status=Status.SINGLE
    ) == 0


# ------------------------------------------------------ the form must foot


def test_printed_components_sum_to_total_income() -> None:
    """Regression: business, rental and other income had no line of their own.

    They were summed into line 9 but never emitted, so the figures printed on
    the form added up to less than the total printed above them — 19,235
    against a stated 20,518.
    """
    lines = _lines(_sample_return())
    components = lines["2b"] + lines["3b"] + lines["6b"] + lines["7"] + lines["8"]

    assert components == lines["9"] == 20653


def test_sample_return_reproduces_every_headline_figure() -> None:
    lines = _lines(_sample_return())

    assert lines["6a"] == 27648
    assert lines["6b"] == 3159
    assert lines["8"] == 5630
    assert lines["9"] == 20653
    assert lines["11"] == 20653
    assert lines["15"] == 0        # deductions exceed income
    assert lines["24"] == 0        # no tax
    assert lines["26"] == 725      # estimated payments
    assert lines["33"] == 725
    assert lines["34"] == 725      # overpaid


# --------------------------------------------------------- merge defects


def test_the_same_form_filed_twice_is_counted_once() -> None:
    """Regression: interest of 213.50 on two copies of one 1099-INT read 427."""
    merged = merge_extractions(
        [
            ("1099_int", {"normalized_fields": {"taxable_interest": "213.50"}}),
            ("1099_int", {"normalized_fields": {"taxable_interest": "213.50"}}),
        ]
    )

    assert merged["normalized_fields"]["taxable_interest"] == "213.50"
    assert merged["duplicates_ignored"]


def test_genuinely_different_amounts_still_sum() -> None:
    """Deduplication must not swallow a second real account."""
    merged = merge_extractions(
        [
            ("1099_int", {"normalized_fields": {"taxable_interest": "213.50"}}),
            ("1099_int", {"normalized_fields": {"taxable_interest": "88.25"}}),
        ]
    )

    assert merged["normalized_fields"]["taxable_interest"] == "301.75"
    assert not merged["duplicates_ignored"]


def test_a_business_statement_cannot_report_personal_income() -> None:
    """Regression: a P&L's payroll-tax line became Social Security benefits.

    A profit-and-loss statement has a row labelled "Social Security" — the
    employer's share of payroll tax — and one labelled "health". Matched on
    name they produced $25,428 of benefits and a $6,282 adjustment for a
    taxpayer who had neither.
    """
    merged = merge_extractions(
        [
            ("k1", {"normalized_fields": {"social_security": "27648.00"}}),
            (
                "profit_and_loss",
                {
                    "normalized_fields": {
                        "social_security": "25428.00",
                        "self_employed_health_insurance": "6281.90",
                        "business_income": "610.45",
                    }
                },
            ),
        ]
    )
    fields = merged["normalized_fields"]

    assert fields["social_security"] == "27648.00"
    assert "self_employed_health_insurance" not in fields
    assert fields["business_income"] == "610.45", "business income still flows"


# ------------------------------------------------------------- identity


@pytest.mark.parametrize(
    ("emitted", "canonical"),
    [
        ("name", "taxpayer_name"),
        ("address", "street_address"),
        ("dob", "date_of_birth"),
        ("zip", "zip_code"),
        ("Taxpayer Name", "taxpayer_name"),
        ("ssn", "ssn"),
    ],
)
def test_identity_synonyms_are_canonicalised(emitted: str, canonical: str) -> None:
    """Regression: the form went out with an SSN and no name.

    Extraction emitted `name` and `address`; the output stage looked for
    `taxpayer_name` and `street_address`. Only `ssn` and `state` happened to
    agree, so only those two printed.
    """
    assert canonical_identity_field(emitted) == canonical


def test_money_fields_are_not_mistaken_for_identity() -> None:
    assert canonical_identity_field("wages") is None
    assert canonical_identity_field("taxable_interest") is None


def test_identity_survives_the_merge() -> None:
    merged = merge_extractions(
        [
            (
                "client_organizer",
                {
                    "normalized_fields": {
                        "name": "ALEX MORGAN",
                        "address": "1 EXAMPLE WAY",
                        "zip": "94000",
                    }
                },
            )
        ]
    )
    fields = merged["normalized_fields"]

    assert fields["taxpayer_name"] == "ALEX MORGAN"
    assert fields["street_address"] == "1 EXAMPLE WAY"
    assert fields["zip_code"] == "94000"


# ------------------------------------------------------------------ age


@pytest.mark.parametrize(
    ("born", "expected"),
    [
        ("06/22/1952", 73),
        ("1952-06-22", 73),
        ("01/01/1961", 65),   # born on 1 January: aged on 31 December prior
        ("01/02/1961", 64),   # one day later, not yet 65
        ("06/22/1990", 35),
    ],
)
def test_age_at_year_end(born: str, expected: int) -> None:
    assert age_on(born, tax_year=2025) == expected


@pytest.mark.parametrize("bad", ["", None, "not a date", "13/45/2020"])
def test_unusable_dates_of_birth_yield_no_age(bad: object) -> None:
    """Guessing an age would silently grant or deny 8,000 of deductions."""
    assert age_on(bad, tax_year=2025) is None


# ------------------------------------------------- overpayment election


def test_overpayment_can_be_carried_forward_instead_of_refunded() -> None:
    """Regression: line 35a printed 725 for a taxpayer who applied it forward.

    Whether an overpayment is refunded or carried to next year's estimated tax
    is the taxpayer's election. It is on no source document and cannot be
    derived, so defaulting to "refund it" quietly contradicted the return.
    """
    result = Form1040Calculator().compute(
        profile=TaxpayerProfile(tax_year=2025, filing_status=Status.SINGLE),
        income=IncomeInputs(taxable_interest=D(100)),
        payments=PaymentInputs(
            estimated_payments=D(725), apply_overpayment_to_next_year=D(725)
        ),
    )
    lines = _lines(result)

    assert lines["34"] == 725, "still overpaid by 725"
    assert lines["36"] == 725, "carried to next year"
    assert "35a" not in lines, "nothing is refunded"
    assert result.refund == 0


def test_a_partial_election_splits_between_refund_and_carry_forward() -> None:
    result = Form1040Calculator().compute(
        profile=TaxpayerProfile(tax_year=2025, filing_status=Status.SINGLE),
        income=IncomeInputs(taxable_interest=D(100)),
        payments=PaymentInputs(
            estimated_payments=D(725), apply_overpayment_to_next_year=D(500)
        ),
    )
    lines = _lines(result)

    assert lines["35a"] == 225
    assert lines["36"] == 500
    assert lines["35a"] + lines["36"] == lines["34"]


def test_carrying_forward_more_than_the_overpayment_is_capped() -> None:
    """You cannot apply forward money you did not overpay."""
    result = Form1040Calculator().compute(
        profile=TaxpayerProfile(tax_year=2025, filing_status=Status.SINGLE),
        income=IncomeInputs(taxable_interest=D(100)),
        payments=PaymentInputs(
            estimated_payments=D(725), apply_overpayment_to_next_year=D(99999)
        ),
    )
    lines = _lines(result)

    assert lines["36"] == 725
    assert "35a" not in lines


def test_without_an_election_the_overpayment_is_refunded() -> None:
    """The default must not change: silence means refund."""
    result = Form1040Calculator().compute(
        profile=TaxpayerProfile(tax_year=2025, filing_status=Status.SINGLE),
        income=IncomeInputs(taxable_interest=D(100)),
        payments=PaymentInputs(estimated_payments=D(725)),
    )
    lines = _lines(result)

    assert lines["35a"] == 725
    assert "36" not in lines


# ------------------------------- Pub 915 Worksheet 1 conformance


def test_mfs_living_apart_uses_the_single_thresholds() -> None:
    """Regression: a separated filer was taxed on 20,250 of nothing.

    The thresholds were hard-coded to zero for every married-filing-separately
    return, which is the rule for someone who lived WITH their spouse. A filer
    who lived apart for the whole year uses the single amounts, and on these
    figures that is the difference between 20,250 and nil.
    """
    apart = taxable_social_security(
        benefits=D(27648), other_income=D(10000), year=2025,
        status=Status.MARRIED_SEPARATE, lived_apart_from_spouse=True,
    )
    together = taxable_social_security(
        benefits=D(27648), other_income=D(10000), year=2025,
        status=Status.MARRIED_SEPARATE, lived_apart_from_spouse=False,
    )

    assert apart == 0
    assert round(together) == 20250


def test_living_apart_defaults_to_false() -> None:
    """The unanswered case must be the higher-tax reading, never the lower."""
    assert taxable_social_security(
        benefits=D(27648), other_income=D(10000), year=2025,
        status=Status.MARRIED_SEPARATE,
    ) > 0


def test_form_2555_and_8839_exclusions_raise_provisional_income() -> None:
    """Worksheet line 5 adds excluded income back before the thresholds.

    Foreign earned income and adoption benefits are excluded from tax but not
    from this test, so omitting them understates the taxable benefit.
    """
    without = taxable_social_security(
        benefits=D(27648), other_income=D(17494), year=2025, status=Status.SINGLE
    )
    with_exclusions = taxable_social_security(
        benefits=D(27648), other_income=D(17494), exclusions=D(15000),
        year=2025, status=Status.SINGLE,
    )

    assert round(without) == 3159
    assert round(with_exclusions) == 14970


def test_adjustments_exceeding_income_leave_nothing_taxable() -> None:
    """Worksheet line 8: 'Is line 7 less than line 6? No — stop.'"""
    assert taxable_social_security(
        benefits=D(27648), other_income=D(5000), adjustments=D(99999),
        year=2025, status=Status.SINGLE,
    ) == 0


def test_student_loan_interest_does_not_reduce_provisional_income() -> None:
    """Worksheet line 7 is Schedule 1 lines 11-20, 23 and 25.

    Student loan interest is line 21 — outside that range. Subtracting it
    understated provisional income and so understated the taxable benefit.
    """
    from app.services.tax_engine.form_1040 import AdjustmentInputs
    from app.services.tax_engine.form_1040 import (
        _provisional_income_adjustments as line_7,
    )

    assert line_7(AdjustmentInputs(student_loan_interest=D(2500))) == 0
    assert line_7(AdjustmentInputs(self_employment_tax_deduction=D(2500))) == 2500


# ------------------------------------------------- Schedule D and carryovers


def test_schedule_d_reproduces_the_prepared_return() -> None:
    """Line 7a is 6,638, and two of its four parts come from outside the year.

    Netting the 1099-B alone gives 6,451. Adding the capital gain
    distributions, which are reported only on Form 1099-DIV, gives 11,149 —
    the figure this engine used to produce, and coincidentally the *California*
    Schedule D total, which is why it looked defensible. The federal figure
    differs from it by exactly the 4,511 short-term loss carried in from the
    prior year.
    """
    result = schedule_d(
        short_term_gain=D(-894),
        short_term_loss_carryover=D(4511),
        long_term_gain=D(7345),
        capital_gain_distributions=D(4698),
        year=2025,
        status=Status.SINGLE,
    )

    assert result.short_term_net == D(-5405)
    assert result.long_term_net == D(12043)
    assert result.net == D(6638)
    assert result.reportable == D(6638)
    assert result.limited is False


def test_capital_gain_distributions_reach_line_7a() -> None:
    """1099-DIV box 2a lands on Schedule D line 13, not on any 1099-B.

    Treating line 7a as a single extracted figure meant a taxpayer whose only
    capital income was fund distributions reported no capital gain at all.
    """
    result = schedule_d(
        capital_gain_distributions=D(4698), year=2025, status=Status.SINGLE
    )

    assert result.net == D(4698)
    assert result.long_term_net == D(4698)


def test_a_negative_carryover_cannot_add_income() -> None:
    """Carryovers are entered positive and subtracted.

    A caller who passes the prior year's loss with its own sign would otherwise
    have it added back as a gain, turning a loss into income.
    """
    result = schedule_d(
        long_term_gain=D(1000),
        long_term_loss_carryover=D(-500),
        year=2025,
        status=Status.SINGLE,
    )

    assert result.net == D(1000)


def test_capital_loss_beyond_the_cap_is_limited_and_carried() -> None:
    result = schedule_d(
        short_term_gain=D(-10000), year=2025, status=Status.SINGLE
    )

    assert result.net == D(-10000)
    assert result.reportable == D(-3000)
    assert result.limited is True


def test_carryover_is_absorbed_by_short_term_loss_first() -> None:
    """§1212(b): the loss keeps its character, and the 3,000 comes off the
    short-term half before the long-term half.

    A flat "everything past 3,000 carries" rule gets the total right and the
    split wrong, which then produces the wrong answer *next* year, where the
    two halves are taxed at different rates.
    """
    result = schedule_d(
        short_term_gain=D(-5000),
        long_term_gain=D(-4000),
        year=2025,
        status=Status.SINGLE,
    )
    short, long = capital_loss_carryover(
        schedule_d=result,
        taxable_income=D(50000),
        year=2025,
        status=Status.SINGLE,
    )

    assert short == D(2000)   # 5,000 less the whole 3,000 deduction
    assert long == D(4000)    # untouched


def test_a_deduction_that_income_cannot_absorb_carries_too() -> None:
    """When deductions already exceed income, the 3,000 is never used, so the
    full 9,000 carries rather than 6,000.

    The worksheet's line 1 says to enclose a loss in parentheses, so it wants
    taxable income *before* Form 1040 line 15 floors it at zero. Feeding it the
    floored zero spends the deduction on paper and carries 3,000 too little —
    silently, and again every following year, since the shortfall compounds.
    """
    result = schedule_d(
        short_term_gain=D(-9000), year=2025, status=Status.SINGLE
    )

    unabsorbed = capital_loss_carryover(
        schedule_d=result, taxable_income=D(-5000), year=2025, status=Status.SINGLE
    )
    assert unabsorbed == (D(9000), D(0))

    # And where there *is* income to absorb it, the 3,000 is used.
    absorbed = capital_loss_carryover(
        schedule_d=result, taxable_income=D(50000), year=2025, status=Status.SINGLE
    )
    assert absorbed == (D(6000), D(0))


def test_a_gain_carries_nothing_forward() -> None:
    result = schedule_d(long_term_gain=D(5000), year=2025, status=Status.SINGLE)

    assert capital_loss_carryover(
        schedule_d=result, taxable_income=D(1000), year=2025, status=Status.SINGLE
    ) == (D(0), D(0))


# ------------------------------------------------- Schedule 1 composition


def test_schedule_1_line_8_carries_four_distinct_lines() -> None:
    """5,630 is not one number. It is 5,469 of Form 4797 ordinary gain on
    Schedule 1 line 4 plus 161 of S corporation income on line 5.

    They used to share a single ``other_income`` field, so the return footed
    while pointing at the wrong schedule — a difference a reviewer cannot see
    but the IRS can.
    """
    result = Form1040Calculator().compute(
        profile=TaxpayerProfile(
            tax_year=2025, filing_status=Status.SINGLE, age_65_or_older=1
        ),
        income=IncomeInputs(other_gains=D(5469), rental_income=D(161)),
    )

    assert _lines(result)["8"] == 5630


def test_prior_year_overpayment_is_part_of_line_26() -> None:
    """Line 26 reads "estimated tax payments *and amount applied from* the
    prior return". The sample taxpayer made no estimated payment at all: the
    entire 725 is last year's overpayment carried in.
    """
    result = Form1040Calculator().compute(
        profile=TaxpayerProfile(tax_year=2025, filing_status=Status.SINGLE),
        income=IncomeInputs(wages=D(30000)),
        payments=PaymentInputs(
            estimated_payments=D(200), prior_year_overpayment_applied=D(725)
        ),
    )

    line_26 = result.line("26")
    assert line_26 is not None
    assert round(line_26.amount) == 925
    assert "725" in line_26.note


def test_schedule_d_detail_wins_over_a_supplied_total() -> None:
    """When both arrive, the schedule is authoritative and the disagreement is
    surfaced rather than silently resolved."""
    result = Form1040Calculator().compute(
        profile=TaxpayerProfile(tax_year=2025, filing_status=Status.SINGLE),
        income=IncomeInputs(capital_gain_loss=D(11149)),
        capital_gains=CapitalGainInputs(
            short_term_gain=D(-894),
            short_term_loss_carryover=D(4511),
            long_term_gain=D(7345),
            capital_gain_distributions=D(4698),
        ),
    )

    assert _lines(result)["7"] == 6638
    assert any("Schedule D computes" in w for w in result.warnings)


# ----------------------------------------------- generalisation across returns


def _tax_chain(*, agi, deduction_taken, preferential, status, year=2025):
    """Deduction -> taxable income -> tax, the part the engine owns.

    Driven from AGI rather than from an income breakdown because the benchmark
    is a CCH Return Summary, which states totals and not their composition.
    Asserting a composition we cannot see would be fitting the test to the
    answer; asserting the chain is checking the rules.
    """
    from app.services.tax_engine.computations import tax_with_capital_gains

    taxable = max(D(0), D(agi) - D(deduction_taken))
    tax = tax_with_capital_gains(
        taxable_income=taxable,
        qualified_income=D(preferential),
        year=year,
        status=status,
    )
    return taxable, tax


def test_engine_generalises_to_a_second_prepared_return() -> None:
    """Basic 6, a different taxpayer with a different return shape.

    Where Basic 5 turns on a §199A deduction, this one turns on preferential
    income: 700 of qualified dividends inside 59,832 of taxable income, which is
    worth exactly 49 of tax and is the whole difference between matching the
    prepared return and missing it.

    Run against the same code as Basic 5 with no changes — which is the point of
    the test. The figures are from the accountant copy's Return Summary.
    """
    taxable, tax = _tax_chain(
        agi=75582, deduction_taken=15750, preferential=700, status=Status.SINGLE
    )

    assert taxable == D(59832)
    assert tax == D(8027)


def test_the_same_chain_reproduces_basic_5() -> None:
    """The first return, through the identical code path."""
    taxable, tax = _tax_chain(
        agi=92758, deduction_taken=15750 + 2905, preferential=0, status=Status.SINGLE
    )

    assert taxable == D(74103)
    assert tax == D(11222)


def test_preferential_income_is_what_separates_the_two_returns() -> None:
    """Without the qualified-dividend rate, Basic 6 misses by 49.

    Small enough to dismiss as rounding, which is exactly why it is worth a
    test: a reviewer who cross-foots against the client's own software finds
    every line agreeing except the tax, and spends an hour on it.
    """
    from app.services.tax_engine.computations import tax_table_lookup

    all_ordinary = tax_table_lookup(D(59832), 2025, Status.SINGLE)

    assert all_ordinary == D(8076)
    assert all_ordinary - D(8027) == D(49)


# ------------------------------------------------ implausible SALT, hidden by the cap


def test_state_tax_far_above_agi_is_flagged_even_though_the_cap_hides_it() -> None:
    """The cap turns any misread into exactly 40,000, which looks deliberate.

    On the Basic 5 sample the engine itemised exactly the cap against an AGI of
    92,757 — a 43% combined state and local rate, which no state levies. Because
    the deduction comes out at the cap whatever the input was, checking the
    deduction can never catch this; only the ratio to income can.
    """
    result = Form1040Calculator().compute(
        profile=TaxpayerProfile(tax_year=2025, filing_status=Status.SINGLE),
        income=IncomeInputs(wages=D("91932.90"), taxable_interest=D("1013.52")),
        deductions=DeductionInputs(state_local_income_tax=D(45000)),
    )

    assert result.deduction_taken == D("40000.00")
    assert any("exceeds any combined state and local rate" in w
               for w in result.warnings), result.warnings


def test_a_genuine_high_tax_state_itemiser_is_not_flagged() -> None:
    """The check must not cry wolf on the returns it is meant to let through."""
    result = Form1040Calculator().compute(
        profile=TaxpayerProfile(tax_year=2025, filing_status=Status.MARRIED_JOINT),
        income=IncomeInputs(wages=D(300000)),
        deductions=DeductionInputs(
            state_local_income_tax=D(28000),
            real_estate_tax=D(12000),
            mortgage_interest=D(18000),
        ),
    )

    assert result.deduction_taken == D("58000.00")
    assert not any("combined state and local rate" in w for w in result.warnings)
