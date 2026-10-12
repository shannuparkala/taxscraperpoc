"""The schedules and worksheets that feed Form 1040.

Line wording and routing come from the notes under ``docs/tax-research/``, each
read off the primary PDF. Every figure below is invented.

The tests are grouped by the thing that is easy to get wrong rather than by
form, because that is what they are for: a schedule that merely adds up its own
lines does not need defending, and the handful of places where the form's own
arithmetic is counter-intuitive do.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.services.tax_engine.graph import TaxpayerFacts, build_graph, compute_return
from app.services.tax_engine.graph.forms import form_8949
from app.services.tax_engine.tax_tables import FilingStatusTax as Status

STATUSES = [
    Status.SINGLE,
    Status.MARRIED_JOINT,
    Status.MARRIED_SEPARATE,
    Status.HEAD_OF_HOUSEHOLD,
]


def facts(status: Status = Status.SINGLE, **kw) -> TaxpayerFacts:
    money = kw.pop("money", {})
    kw.setdefault("taxpayer_age", 40)
    return TaxpayerFacts(tax_year=2025, filing_status=status, money=money, **kw)


# ================================================== Schedule 1


def test_schedule_1_line_10_does_not_count_the_write_ins_twice() -> None:
    """"Combine lines 1 through 7 and 9" - not 1 through 9.

    Lines 8a-8z roll up through line 9, so summing 1 through 9 counts every
    write-in twice. On a return whose other income is mostly write-ins that
    doubles additional income and still foots.
    """
    result = compute_return(
        facts(money={"sch1_l7": D(4000), "sch1_l8h": D(300), "sch1_l8i": D(700)})
    )

    assert result.amount("sch1.l9") == D(1000)
    assert result.amount("sch1.l10") == D(5000)


def test_the_1099k_reconciliation_line_stays_out_of_additional_income() -> None:
    """It discloses amounts reported elsewhere; adding it double-counts them."""
    without = compute_return(facts(money={"sch1_l7": D(4000)}))
    with_1099k = compute_return(
        facts(money={"sch1_l7": D(4000), "sch1_l1099k": D(9000)})
    )

    assert with_1099k.amount("sch1.l10") == without.amount("sch1.l10")


def test_schedule_1_subtotals_reach_the_form_1040_lines_that_name_them() -> None:
    result = compute_return(
        facts(money={"sch1_l7": D(4000), "sch1_l21": D(1500)})
    )

    assert result.amount("f1040.l8") == result.amount("sch1.l10") == D(4000)
    assert result.amount("f1040.l10") == result.amount("sch1.l26") == D(1500)
    assert result.amount("f1040.l11a") == result.amount("f1040.l9") - D(1500)


# ================================================== Schedule 2


def test_schedule_2_line_21_skips_the_section_965_installment_on_line_20() -> None:
    """Its own wording is "Add lines 4, 7 through 16, 18, and 19".

    The section 965 installment is reported on line 20 and settled separately.
    Summing 4 through 20 is the obvious reading and overstates the tax.
    """
    graph = build_graph(facts())

    assert "sch2.l20" in graph, "the line exists on the form"
    assert "sch2.l20" not in graph["sch2.l21"].inputs
    assert "sch2.l19" in graph["sch2.l21"].inputs
    assert "sch2.l18" in graph["sch2.l21"].inputs

    result = compute_return(facts(money={"sch2_l13": D(500)}))
    assert result.amount("sch2.l21") == D(500)
    assert result.amount("f1040.l23") == D(500)


def test_schedule_2_separates_the_tax_half_from_the_other_taxes_half() -> None:
    """Line 3 lands on Form 1040 line 17; line 21 on line 23, after credits.

    Mixing them lets a nonrefundable credit wipe out self-employment tax.
    """
    result = compute_return(
        facts(money={"wages": D(90000), "sch2_l1a": D(400), "sch2_l13": D(900)})
    )

    assert result.amount("f1040.l17") == D(400)
    assert result.amount("f1040.l23") == D(900)
    assert result.amount("f1040.l18") == result.amount("f1040.l16") + D(400)


# ================================================== Schedule 3


def test_a_nonrefundable_credit_cannot_take_tax_below_zero() -> None:
    result = compute_return(
        facts(money={"wages": D(20000), "sch3_l6a": D(999999)})
    )

    assert result.amount("f1040.l22") == 0
    assert result.amount("f1040.l24") == 0


def test_a_refundable_credit_can_produce_a_refund_on_its_own() -> None:
    """Which is the whole difference between Part I and Part II."""
    result = compute_return(
        facts(money={"wages": D(20000), "sch3_l13a": D(5000)})
    )

    assert result.amount("f1040.l31") == D(5000)
    assert result.amount("f1040.l34") > 0


# ================================================== Schedule B


def test_savings_bond_interest_is_excluded_before_line_2b() -> None:
    result = compute_return(
        facts(money={"taxable_interest": D(4000), "schb_l3": D(1500)})
    )

    assert result.amount("schb.l4") == D(2500)
    assert result.amount("f1040.l2b") == D(2500)


def test_schedule_b_uses_the_vocabulary_form_1040_already_had() -> None:
    """One figure, one field name. Trap 17 with extra steps otherwise."""
    result = compute_return(facts(money={"taxable_interest": D(1014)}))

    assert result.amount("schb.l1") == D(1014)
    assert result.amount("f1040.l2b") == D(1014)


def test_part_three_is_flagged_once_interest_passes_the_filing_threshold() -> None:
    quiet = compute_return(facts(money={"taxable_interest": D(1500)}))
    loud = compute_return(facts(money={"taxable_interest": D("1500.01")}))

    assert quiet["schb.l7a"].flags == ()
    assert loud["schb.l7a"].flags != ()


# ================================================== Form 8949 and Schedule D


def test_each_form_8949_box_lands_on_the_schedule_d_line_the_map_names() -> None:
    assert form_8949.feeds("schd.l1b") == ("f8949.p1.l2a", "f8949.p1.l2g")
    assert form_8949.feeds("schd.l9") == ("f8949.p2.l2e", "f8949.p2.l2k")


def test_a_digital_asset_box_reaches_the_same_line_as_its_securities_twin() -> None:
    """New for 2025: boxes G-L mirror A-F for Form 1099-DA reporting."""
    securities = compute_return(facts(money={"f8949_l2a": D(5000)}))
    digital = compute_return(facts(money={"f8949_l2g": D(5000)}))

    assert securities.amount("schd.l1b") == digital.amount("schd.l1b") == D(5000)


def test_short_and_long_term_are_netted_separately_before_being_combined() -> None:
    result = compute_return(
        facts(money={"f8949_l2a": D(-4000), "f8949_l2d": D(10000)})
    )

    assert result.amount("schd.l7") == D(-4000)
    assert result.amount("schd.l15") == D(10000)
    assert result.amount("schd.l16") == D(6000)


@pytest.mark.parametrize(
    ("status", "cap"),
    [
        (Status.SINGLE, D(3000)),
        (Status.MARRIED_JOINT, D(3000)),
        (Status.MARRIED_SEPARATE, D(1500)),
        (Status.HEAD_OF_HOUSEHOLD, D(3000)),
    ],
)
def test_a_net_capital_loss_is_limited_and_the_rest_carries_forward(status, cap) -> None:
    """IRC 1211(b). Entering the whole loss on Form 1040 line 7 is the error
    this part of Schedule D exists to prevent, and it looks entirely ordinary.
    """
    result = compute_return(facts(status, money={"f8949_l2a": D(-20000)}))

    assert result.amount("schd.l16") == D(-20000)
    assert result.amount("schd.l21") == -cap
    assert result.amount("f1040.l7a") == -cap
    assert "carries forward" in result["schd.l21"].flags[0]


@pytest.mark.parametrize("status", STATUSES)
def test_a_loss_at_exactly_the_limit_is_fully_deductible(status) -> None:
    cap = D(1500) if status is Status.MARRIED_SEPARATE else D(3000)
    at = compute_return(facts(status, money={"f8949_l2a": -cap}))
    over = compute_return(facts(status, money={"f8949_l2a": -(cap + D("0.01"))}))

    assert at.amount("f1040.l7a") == -cap
    assert at["schd.l21"].flags == ()
    assert over.amount("f1040.l7a") == -cap
    assert over["schd.l21"].flags != ()


def test_a_net_gain_goes_to_form_1040_whole_and_unlimited() -> None:
    result = compute_return(facts(money={"f8949_l2d": D(75000)}))

    assert result.amount("f1040.l7a") == D(75000)
    assert result.amount("schd.l21") == 0


def test_a_carryover_entered_positive_would_turn_a_loss_into_income() -> None:
    """The form says enter it as a negative, and the sign is the whole figure.

    Kept as a test rather than a comment because the failure is silent: a
    carryover with the wrong sign swings the return by twice the amount and
    still foots.
    """
    correct = compute_return(facts(money={"schd_l6": D(-4511)}))
    wrong_sign = compute_return(facts(money={"schd_l6": D(4511)}))

    assert correct.amount("schd.l7") == D(-4511)
    assert wrong_sign.amount("schd.l7") == D(4511)
    assert wrong_sign.amount("schd.l7") - correct.amount("schd.l7") == D(9022)


def test_capital_gain_distributions_only_reach_the_return_through_schedule_d() -> None:
    """They appear on Form 1099-DIV and nowhere on Form 8949."""
    result = compute_return(facts(money={"schd_l13": D(4698)}))

    assert result.amount("schd.l15") == D(4698)
    assert result.amount("f1040.l7a") == D(4698)


# ================================================== Schedule A


def test_only_medical_expenses_above_seven_and_a_half_percent_of_agi_count() -> None:
    result = compute_return(
        facts(money={"wages": D(100000), "scha_l1": D(10000)})
    )

    assert result.amount("scha.l3") == D(7500)
    assert result.amount("scha.l4") == D(2500)


def test_medical_expenses_below_the_floor_give_nil_not_a_negative() -> None:
    result = compute_return(
        facts(money={"wages": D(100000), "scha_l1": D(5000)})
    )

    assert result.amount("scha.l4") == 0


@pytest.mark.parametrize(
    ("status", "cap"),
    [
        (Status.SINGLE, D(40000)),
        (Status.MARRIED_JOINT, D(40000)),
        (Status.MARRIED_SEPARATE, D(20000)),
        (Status.HEAD_OF_HOUSEHOLD, D(40000)),
    ],
)
def test_the_salt_cap_is_the_2025_figure_not_the_one_people_remember(status, cap) -> None:
    """OBBBA replaced the $10,000 cap. A return computed on the old one
    understates the deduction by up to $30,000 and looks entirely ordinary.
    """
    result = compute_return(
        facts(status, money={"wages": D(200000), "scha_l5a": D(60000)})
    )

    assert result.amount("scha.l5d") == D(60000)
    assert result.amount("scha.l5e") == cap


def test_salt_below_the_cap_is_deducted_in_full() -> None:
    result = compute_return(
        facts(money={"wages": D(200000), "scha_l5a": D(12000), "scha_l5b": D(6000)})
    )

    assert result.amount("scha.l5e") == D(18000)


def test_the_salt_cap_phases_down_above_the_threshold_but_never_below_the_floor() -> None:
    """30% of modified AGI over $500,000, floored at $10,000."""
    below = compute_return(
        facts(money={"wages": D(500000), "scha_l5a": D(60000)})
    )
    above = compute_return(
        facts(money={"wages": D(600000), "scha_l5a": D(60000)})
    )
    far_above = compute_return(
        facts(money={"wages": D(5000000), "scha_l5a": D(60000)})
    )

    assert below.amount("scha.l5e") == D(40000)
    assert above.amount("scha.l5e") == D(40000) - D(100000) * D("0.30")
    assert far_above.amount("scha.l5e") == D(10000), "the floor holds"


def test_total_itemized_deductions_add_only_the_far_right_column() -> None:
    """Lines 4, 7, 10, 14, 15 and 16 - not every line on the form.

    Adding 5d as well as 5e, or 8a-8c as well as 8e, double-counts.
    """
    result = compute_return(
        facts(money={
            "wages": D(100000),
            "scha_l1": D(10000),      # -> line 4 = 2,500
            "scha_l5a": D(9000),      # -> line 5e = 9,000, line 7 = 9,000
            "scha_l8a": D(12000),     # -> line 8e = 12,000, line 10 = 12,000
            "scha_l11": D(3000),      # -> line 14 = 3,000
        })
    )

    assert result.amount("scha.l17") == D(2500) + D(9000) + D(12000) + D(3000)


def test_the_return_itemizes_only_when_schedule_a_is_worth_more() -> None:
    small = compute_return(facts(money={"wages": D(100000), "scha_l5a": D(9000)}))
    large = compute_return(facts(money={"wages": D(100000), "scha_l5a": D(30000)}))

    assert small.amount("f1040.l12e") == D(15750), "the standard deduction wins"
    assert small["f1040.l12e"].flags != (), "and the return says Schedule A was worked"
    assert large.amount("f1040.l12e") == D(30000)


# ================================================== Form 8889


@pytest.mark.parametrize(
    ("family", "limit"), [(0, D(4300)), (1, D(8550))]
)
def test_the_hsa_contribution_limit_follows_the_coverage_type(family, limit) -> None:
    """Rev. Proc. 2024-25, not the revenue procedure that sets everything else."""
    result = compute_return(
        facts(money={"f8889_family_coverage": D(family), "f8889_l2": D(9000)})
    )

    assert result.amount("f8889.l3") == limit
    assert result.amount("f8889.l13") == limit


def test_the_catch_up_contribution_starts_at_fifty_five_not_sixty_five() -> None:
    under = compute_return(facts(taxpayer_age=54, money={"f8889_l2": D(9000)}))
    at = compute_return(facts(taxpayer_age=55, money={"f8889_l2": D(9000)}))

    assert under.amount("f8889.l7") == 0
    assert at.amount("f8889.l7") == D(1000)
    assert at.amount("f8889.l3") == under.amount("f8889.l3"), "the limit itself is unchanged"


def test_the_hsa_deduction_is_the_smaller_of_what_was_paid_and_what_is_allowed() -> None:
    modest = compute_return(facts(money={"f8889_l2": D(1000)}))
    over = compute_return(facts(money={"f8889_l2": D(9000)}))

    assert modest.amount("f8889.l13") == D(1000)
    assert over.amount("f8889.l13") == D(4300)


def test_employer_contributions_reduce_what_the_taxpayer_may_deduct() -> None:
    result = compute_return(facts(money={"f8889_l2": D(4300), "f8889_l9": D(3000)}))

    assert result.amount("f8889.l12") == D(1300)
    assert result.amount("f8889.l13") == D(1300)


def test_the_hsa_deduction_reaches_adjusted_gross_income() -> None:
    result = compute_return(facts(money={"wages": D(80000), "f8889_l2": D(4300)}))

    assert result.amount("sch1.l13") == D(4300)
    assert result.amount("f1040.l11a") == D(80000) - D(4300)


def test_a_distribution_not_spent_on_medical_care_is_taxed_and_penalised() -> None:
    result = compute_return(
        facts(money={"f8889_l14a": D(5000), "f8889_l15": D(3000)})
    )

    assert result.amount("f8889.l16") == D(2000)
    assert result.amount("f8889.l17b") == D(400), "20% under IRC 223(f)(4)(A)"


def test_a_rollover_is_not_a_distribution() -> None:
    result = compute_return(
        facts(money={"f8889_l14a": D(5000), "f8889_l14b": D(5000)})
    )

    assert result.amount("f8889.l14c") == 0
    assert result.amount("f8889.l16") == 0


# ================================================== QDCGT worksheet


def test_the_preferential_slice_stacks_on_top_of_ordinary_income() -> None:
    """A small qualified dividend on a large ordinary income is not taxed at 0%.

    Applying the brackets to the qualified amount alone is the classic error,
    and it understates tax on exactly the returns where the figure is large.
    """
    result = compute_return(
        facts(money={
            "wages": D(200000),
            "qualified_dividends": D(10000),
            "ordinary_dividends": D(10000),
        })
    )

    assert result.amount("qdcgtw.l6") == 0, "no room left at 0%"
    assert result.amount("qdcgtw.l7") == D(10000), "all of it at 15%"


def test_the_zero_rate_fills_only_the_room_below_the_first_breakpoint() -> None:
    result = compute_return(
        facts(money={
            "wages": D(60000),
            "qualified_dividends": D(10000),
            "ordinary_dividends": D(10000),
        })
    )

    # Taxable income 54,250; ordinary 44,250; the 0% band ends at 48,350.
    assert result.amount("qdcgtw.l5") == D(44250)
    assert result.amount("qdcgtw.l6") == D(48350) - D(44250)
    assert result.amount("qdcgtw.l7") == D(10000) - (D(48350) - D(44250))


@pytest.mark.parametrize(
    ("status", "zero_ends"),
    [
        (Status.SINGLE, D(48350)),
        (Status.MARRIED_JOINT, D(96700)),
        (Status.MARRIED_SEPARATE, D(48350)),
        (Status.HEAD_OF_HOUSEHOLD, D(64750)),
    ],
)
def test_the_zero_rate_breakpoint_differs_by_filing_status(status, zero_ends) -> None:
    result = compute_return(
        facts(status, money={"qualified_dividends": D(400000),
                             "ordinary_dividends": D(400000)})
    )

    assert result.amount("qdcgtw.l6") == zero_ends


def test_the_worksheet_never_costs_more_than_the_tax_table() -> None:
    """Its last line takes the smaller of the two, which is the point of it."""
    result = compute_return(
        facts(money={"wages": D(60000), "qualified_dividends": D(10000),
                     "ordinary_dividends": D(10000)})
    )

    assert result.amount("qdcgtw.l11") <= result.amount("qdcgtw.l10")
    assert result.amount("f1040.l16") == result.amount("qdcgtw.l11")


def test_a_long_term_loss_does_not_put_the_return_on_the_worksheet() -> None:
    """The tax is the same either way, but the provenance must not claim a
    worksheet the return had no reason to run.
    """
    result = compute_return(
        facts(money={"wages": D(91933), "f8949_l2d": D(-153)})
    )

    assert "worksheet" not in result["f1040.l16"].formula.lower()
    assert "Tax Table" not in result["f1040.l16"].label


def test_the_worksheet_decomposition_agrees_with_the_reconciled_computation() -> None:
    """Two routes to one figure. If they part, the shown arithmetic is fiction."""
    for wages, qualified in ((D(60000), D(10000)), (D(300000), D(80000)),
                             (D(20000), D(5000)), (D(700000), D(200000))):
        result = compute_return(
            facts(money={"wages": wages, "qualified_dividends": qualified,
                         "ordinary_dividends": qualified})
        )
        assert result["qdcgtw.l10"].flags == (), (wages, qualified)
