"""Form 1040 as calculation-graph nodes.

Line wording and ordering come from
``docs/tax-research/form-1040-2025-line-by-line.md``, read off the primary PDF.

Every figure below is invented except where a test says it is checking a
reconciled benchmark, and those figures are already in the repository's test
suite.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.services.tax_engine.graph import (
    Basis,
    Dependent,
    Rounding,
    SourceFact,
    TaxpayerFacts,
    build_graph,
    compute_return,
)
from app.services.tax_engine.graph.nodes import apply_rounding
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


# ------------------------------------------------- shape


def test_every_line_of_the_form_has_a_node() -> None:
    """A line absent from the graph is indistinguishable from a line of zero.

    Trap 9 and trap 32: a well-formed return of zeros reads exactly like a real
    one, so the form's own line list is the checklist.
    """
    printed = [
        "1a", "1b", "1c", "1d", "1e", "1f", "1g", "1h", "1i", "1z",
        "2a", "2b", "3a", "3b", "4a", "4b", "5a", "5b", "6a", "6b",
        "7a", "8", "9", "10", "11a", "11b", "12e", "13a", "13b", "14",
        "15", "16", "17", "18", "19", "20", "21", "22", "23", "24",
        "25a", "25b", "25c", "25d", "26", "27a", "27b", "28", "29", "30",
        "31", "32", "33", "34", "35a", "36", "37", "38",
    ]
    result = compute_return(facts())
    present = [line.line for line in result.form("Form 1040")]

    assert present == printed


def test_the_lines_are_in_the_order_the_form_prints_them() -> None:
    result = compute_return(facts())
    lines = [line.line for line in result.form("Form 1040")]

    assert lines.index("9") < lines.index("11a") < lines.index("15")
    assert lines.index("15") < lines.index("16") < lines.index("24")
    assert lines.index("33") < lines.index("34") < lines.index("37")


# ------------------------------------------------- income


def test_line_1z_excludes_the_combat_pay_election_on_line_1i() -> None:
    """1i is an election disclosure, not income.

    Summing it into 1z overstates total income, and the form's own wording is
    "Add lines 1a through 1h".
    """
    result = compute_return(
        facts(money={"wages": D(60000), "nontaxable_combat_pay": D(9000)})
    )

    assert result.amount("f1040.l1i") == D(9000)
    assert result.amount("f1040.l1z") == D(60000)
    assert result.amount("f1040.l9") == D(60000)


def test_line_1z_adds_every_one_of_its_eight_components() -> None:
    money = {
        "wages": D(1),
        "household_employee_wages": D(2),
        "tip_income": D(4),
        "medicaid_waiver_payments": D(8),
        "dependent_care_benefits": D(16),
        "employer_adoption_benefits": D(32),
        "wages_from_form_8919": D(64),
        "other_earned_income": D(128),
    }
    result = compute_return(facts(money=money))

    assert result.amount("f1040.l1z") == D(255), "a missing component is a power of two"


def test_total_income_adds_the_eight_lines_the_form_names() -> None:
    money = {
        "wages": D(50000),
        "taxable_interest": D(1000),
        "ordinary_dividends": D(2000),
        "ira_taxable": D(3000),
        "pensions_taxable": D(4000),
        "capital_gain_or_loss": D(5000),
    }
    result = compute_return(facts(money=money))

    assert result.amount("f1040.l9") == D(65000)


def test_a_capital_loss_reduces_total_income() -> None:
    result = compute_return(
        facts(money={"wages": D(91933), "capital_gain_or_loss": D(-189)})
    )

    assert result.amount("f1040.l9") == D(91744)


# ------------------------------------------------- social security


def test_line_6b_is_computed_rather_than_read_from_any_document() -> None:
    """Form SSA-1099 reports the gross benefit and is silent on the taxable part.

    It depends on the rest of the return, so waiting for a document to supply
    it leaves the line blank and drops the whole benefit out of income.
    """
    result = compute_return(
        facts(
            taxpayer_age=70,
            money={
                "social_security_benefits": D(27648),
                "taxable_interest": D("213.50"),
                "ordinary_dividends": D("5012.35"),
                "capital_gain_or_loss": D(6638),
                "pensions_taxable": D(5630),
            },
        )
    )

    taxable = result.amount("f1040.l6b")
    assert taxable is not None and taxable > 0
    assert taxable < D(27648) * D("0.85") + 1, "IRC 86 caps the taxable part at 85%"
    assert result[("f1040.l6b")].basis is Basis.COMPUTED


def test_benefits_with_no_other_income_are_untaxed() -> None:
    result = compute_return(
        facts(taxpayer_age=70, money={"social_security_benefits": D(20000)})
    )

    assert result.amount("f1040.l6b") == 0
    assert "no benefits" not in result["f1040.l6b"].formula


def test_no_benefits_reported_gives_a_zero_that_says_why() -> None:
    result = compute_return(facts(money={"wages": D(50000)}))

    assert result.amount("f1040.l6b") == 0
    assert "no benefits reported" in result["f1040.l6b"].formula


def test_tax_exempt_interest_raises_the_taxable_portion_of_benefits() -> None:
    """IRC 86 counts municipal interest even though the return does not tax it."""
    base = {"social_security_benefits": D(27648), "taxable_interest": D(17494)}
    without = compute_return(facts(taxpayer_age=70, money=dict(base)))
    with_muni = compute_return(
        facts(taxpayer_age=70, money={**base, "tax_exempt_interest": D(5000)})
    )

    assert with_muni.amount("f1040.l6b") > without.amount("f1040.l6b")
    assert with_muni.amount("f1040.l2b") == without.amount("f1040.l2b")


# ------------------------------------------------- standard deduction, per status


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (Status.SINGLE, D(15750)),
        (Status.MARRIED_JOINT, D(31500)),
        (Status.MARRIED_SEPARATE, D(15750)),
        (Status.HEAD_OF_HOUSEHOLD, D(23625)),
    ],
)
def test_the_standard_deduction_differs_by_filing_status(status, expected) -> None:
    """A single-status test proves the least interesting case."""
    result = compute_return(facts(status, money={"wages": D(80000)}))

    assert result.amount("f1040.l12e") == expected


@pytest.mark.parametrize("status", STATUSES)
def test_an_additional_amount_is_added_for_age_65_or_older(status) -> None:
    under = compute_return(facts(status, taxpayer_age=64, money={"wages": D(80000)}))
    over = compute_return(facts(status, taxpayer_age=65, money={"wages": D(80000)}))

    assert over.amount("f1040.l12e") > under.amount("f1040.l12e")


def test_age_65_is_the_endpoint_and_64_does_not_qualify() -> None:
    at = compute_return(facts(taxpayer_age=65, money={"wages": D(80000)}))
    below = compute_return(facts(taxpayer_age=64, money={"wages": D(80000)}))

    assert below.amount("f1040.l12e") == D(15750)
    assert at.amount("f1040.l12e") > D(15750)


def test_a_spouse_over_65_adds_nothing_unless_the_return_is_joint() -> None:
    """Trap 33: the additional amount is per entitlement, not per person alive."""
    joint = compute_return(
        facts(Status.MARRIED_JOINT, taxpayer_age=70, spouse_age=70,
              money={"wages": D(80000)})
    )
    separate = compute_return(
        facts(Status.MARRIED_SEPARATE, taxpayer_age=70, spouse_age=70,
              money={"wages": D(80000)})
    )

    assert joint.amount("f1040.l12e") - D(31500) == 2 * (
        separate.amount("f1040.l12e") - D(15750)
    )


def test_blindness_adds_on_the_same_entitlement_rule() -> None:
    sighted = compute_return(facts(money={"wages": D(80000)}))
    blind = compute_return(facts(taxpayer_blind=True, money={"wages": D(80000)}))

    assert blind.amount("f1040.l12e") > sighted.amount("f1040.l12e")


# ------------------------------------------------- the -0- instruction


def test_taxable_income_below_zero_is_entered_as_nil_not_as_a_negative() -> None:
    result = compute_return(facts(money={"wages": D(5000)}))

    assert result.amount("f1040.l15") == 0
    assert "enter -0-" in result["f1040.l15"].formula


def test_tax_after_credits_below_zero_is_entered_as_nil() -> None:
    result = compute_return(facts(money={"wages": D(5000)}))

    assert result.amount("f1040.l22") == 0


def test_a_refund_and_an_amount_owed_are_never_both_positive() -> None:
    for wages, withheld in ((D(80000), D(20000)), (D(80000), D(1000)), (D(0), D(0))):
        result = compute_return(
            facts(money={"wages": wages, "federal_withheld_w2": withheld})
        )
        refund = result.amount("f1040.l34")
        owed = result.amount("f1040.l37")
        assert not (refund > 0 and owed > 0), (wages, withheld)


def test_an_overpayment_applied_forward_comes_out_of_the_refund() -> None:
    result = compute_return(
        facts(
            money={
                "wages": D(80000),
                "federal_withheld_w2": D(20000),
                "amount_applied_to_next_year": D(500),
            }
        )
    )

    assert result.amount("f1040.l35a") == result.amount("f1040.l34") - D(500)


# ------------------------------------------------- unsupported lines


def test_a_schedule_that_is_built_carries_its_own_subtotal() -> None:
    result = compute_return(facts(money={"wages": D(50000)}))

    assert result.amount("f1040.l8") == result.amount("sch1.l10")
    assert result["f1040.l8"].formula == "0 carried from sch1.l10"
    assert result.fileable


def test_a_form_nobody_feeds_is_zero_and_says_so() -> None:
    """Form 8995 is not built, and this return has no business income."""
    result = compute_return(facts(money={"wages": D(50000)}))

    assert result.amount("f1040.l13a") == 0
    assert "nothing on this return feeds Form 8995" in result["f1040.l13a"].formula
    assert result.fileable


def test_a_schedule_this_taxpayer_needs_is_unsupported_not_zero() -> None:
    """Dependents mean Schedule 8812, which is not built.

    Reporting zero there would be a credit silently dropped, which is the
    failure a well-formed return of zeros hides.
    """
    result = compute_return(
        facts(
            dependents=(Dependent(name_token="DEPENDENT_001", relationship="daughter", age=7),),
            money={"wages": D(50000)},
        )
    )

    assert result.amount("f1040.l19") is None
    assert result.amount("f1040.l28") is None
    assert result.fileable is False
    assert "Schedule 8812" in result["f1040.l19"].flags[0]


def test_an_unsupported_line_propagates_to_every_line_that_consumes_it() -> None:
    result = compute_return(
        facts(
            dependents=(Dependent(name_token="DEPENDENT_001", relationship="son", age=4),),
            money={"wages": D(50000), "federal_withheld_w2": D(3000)},
        )
    )

    # 19 feeds 21, which feeds 22, which feeds 24.
    for node_id in ("f1040.l21", "f1040.l22", "f1040.l24"):
        assert result.amount(node_id) is None, node_id


def test_the_rest_of_the_return_still_computes_around_an_unsupported_line() -> None:
    """Trap 30: a preparer cannot correct a return that does not exist."""
    result = compute_return(
        facts(
            dependents=(Dependent(name_token="DEPENDENT_001", relationship="son", age=4),),
            money={"wages": D(50000), "taxable_interest": D(800)},
        )
    )

    assert result.amount("f1040.l9") == D(50800)
    assert result.amount("f1040.l11a") == D(50800)
    assert result.amount("f1040.l15") is not None
    assert result.amount("f1040.l16") is not None
    assert [line.line for line in result.unsupported] == ["19", "21", "22", "24", "28",
                                                          "32", "33", "34", "35a", "37"]


# ------------------------------------------------- provenance


def test_every_computed_line_shows_its_arithmetic_with_operands_substituted() -> None:
    result = compute_return(
        facts(money={"wages": D(7410), "taxable_interest": D(1236)})
    )

    for line in result.form("Form 1040"):
        assert line.formula, f"{line.node_id} reported a figure with no arithmetic"
        # The real property: a substituted formula contains figures. A template
        # that never ran carries symbols and no digits.
        assert any(ch.isdigit() for ch in line.formula), line.node_id

    assert result["f1040.l9"].formula == "7,410 + 1,236 = 8,646"


def test_a_figure_read_off_a_document_carries_the_page_it_came_from() -> None:
    fact = SourceFact(
        field="wages",
        document_id="doc-7",
        document_type="Form W-2",
        page=2,
        confidence=D("0.97"),
    )
    supplied = TaxpayerFacts(
        tax_year=2025,
        filing_status=Status.SINGLE,
        taxpayer_age=40,
        money={"wages": D(50000)},
        provenance={"wages": fact},
    )
    result = compute_return(supplied)

    assert result["f1040.l1a"].sources == (fact,)
    assert result["f1040.l9"].sources == (fact,), "and it carries up to the total"


def test_the_standard_deduction_line_cites_the_authority_that_sets_it() -> None:
    result = compute_return(facts(money={"wages": D(80000)}))
    line = result["f1040.l12e"]

    assert line.authority is not None
    assert line.authority.url.startswith("https://")


def test_lines_resting_on_an_unconfirmed_constant_are_reported() -> None:
    """The 2025 standard deduction comes from the Act, not the instructions."""
    result = compute_return(facts(money={"wages": D(80000)}))

    assert "const.standard_deduction.single" in result.unverified_authorities


def test_feeds_into_is_available_for_every_line_that_is_consumed() -> None:
    graph = build_graph(facts(money={"wages": D(50000)}))

    assert "f1040.l9" in graph.feeds_into("f1040.l1z")
    assert graph.feeds_into("f1040.l24") == ("f1040.l34", "f1040.l37")


# ------------------------------------------------- rounding


def test_whole_dollar_rounding_rounds_a_half_up_not_to_even() -> None:
    """Python's default is banker's rounding, which differs on exactly .50.

    That is the figure a reviewer spot-checks.
    """
    assert apply_rounding(D("1234.50"), Rounding.DOLLARS) == D(1235)
    assert apply_rounding(D("1235.50"), Rounding.DOLLARS) == D(1236)
    assert D("1234.50").quantize(D(1)) == D(1234), "the default would round down"
    assert apply_rounding(D("1234.49"), Rounding.DOLLARS) == D(1234)
    assert apply_rounding(D("1234.50"), Rounding.NONE) == D("1234.50")


def test_the_form_carries_cents_so_a_figure_stays_checkable() -> None:
    """Whole-dollar rounding is optional and all-or-nothing on this form."""
    result = compute_return(
        facts(money={"wages": D("50000.49"), "taxable_interest": D("0.51")})
    )

    assert result.amount("f1040.l9") == D("50001.00")


# ------------------------------------------------- the reconciled benchmark


def test_the_basic_5_shape_reproduces_the_filed_return_bar_schedule_1a() -> None:
    """Basic 5's figures, from the accountant copy, through the graph.

    The filed return's taxable income is 74,103 and its tax is 11,222. This
    engine reaches 77,008, and the whole 2,905 difference is line 13b - the
    qualified overtime deduction on Schedule 1-A, which is not built. The gap
    being *exactly* the missing line is what says the rest is wired correctly.
    """
    result = compute_return(
        facts(
            taxpayer_age=43,
            money={
                "wages": D(91933),
                "taxable_interest": D(1014),
                "capital_gain_or_loss": D(-189),
                "federal_withheld_w2": D(12666),
            },
        )
    )

    assert result.amount("f1040.l9") == D(92758), "total income ties"
    assert result.amount("f1040.l11a") == D(92758), "AGI ties"
    assert result.amount("f1040.l12e") == D(15750), "standard deduction ties"
    assert result.amount("f1040.l13b") == 0, "Schedule 1-A is not built yet"
    assert result.amount("f1040.l15") == D(74103) + D(2905)
    assert result.amount("f1040.l25d") == D(12666), "withholding ties"


def test_tax_below_the_table_ceiling_uses_the_tax_table_not_the_rate_schedule() -> None:
    """Basic 5 reconciles only through the table; the two do not agree."""
    from app.services.tax_engine.computations import (
        tax_on_ordinary_income,
        tax_table_lookup,
    )

    taxable = D(74103)
    table = tax_table_lookup(taxable, 2025, Status.SINGLE)
    schedule = tax_on_ordinary_income(taxable, 2025, Status.SINGLE)

    assert table != schedule, "if these agree the test has stopped proving anything"
    assert table == D(11222), "the figure on the filed return"
