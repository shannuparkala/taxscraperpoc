"""The depreciation engine: golden cases, boundaries and properties.

Golden values are worked by hand from the rule files (and, where the IRS
prints one, from Pub. 946 - see test_depreciation_validation.py). The
property tests use a seeded generator, so a failure always reproduces.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from app.services.depreciation.engine import (
    SCENARIOS,
    AssetInput,
    CalculationInput,
    InputError,
    compute,
    validate,
)
from app.services.depreciation.rules import DepreciationRules, UnsupportedYearError
from app.services.depreciation.service import calculate

RULES = DepreciationRules()


def asset(**overrides) -> AssetInput:
    base = {
        "id": "a1", "description": "", "asset_class": "computers", "cost": D(100000),
        "placed_in_service": date(2026, 3, 1), "acquired": date(2026, 2, 1),
    }
    base.update(overrides)
    return AssetInput(**base)


def run(*assets: AssetInput, method: str = "bonus", tax_year: int = 2026, **kwargs) -> dict:
    return calculate(CalculationInput(tax_year=tax_year, assets=tuple(assets), method=method, **kwargs), RULES)


def totals(result: dict) -> list[int]:
    return [int(row["total"]) for row in result["federal"]["schedule"]]


# --- Golden cases -------------------------------------------------------------

def test_5_year_property_with_100_percent_bonus_in_2026_deducts_everything_in_year_one() -> None:
    result = run(asset())
    assert result["federal"]["tax_year_deduction"] == "100000"
    assert result["assets"][0]["bonus_rate"] == "100"
    assert result["federal"]["check"]["ok"]


def test_electing_out_of_bonus_gives_the_table_a1_percentages() -> None:
    result = run(asset(), method="macrs")
    assert totals(result) == [20000, 32000, 19200, 11520, 11520, 5760]


def test_7_year_schedule_sums_to_exactly_the_basis() -> None:
    result = run(asset(asset_class="furniture", cost=D(123457)), method="macrs")
    assert sum(totals(result)) == 123457
    assert len(totals(result)) == 8


@pytest.mark.parametrize(
    ("purchases", "dollar_limit"),
    [
        (D(4_090_000), D(2_560_000)),   # at the threshold: no reduction
        (D(4_090_001), D(2_559_999)),   # one dollar over: reduced by one dollar
        (D(5_000_000), D(1_650_000)),   # dollar for dollar
        (D(6_650_000), D(0)),           # limit + threshold: fully phased out
        (D(9_000_000), D(0)),           # never below zero
    ],
)
def test_section_179_phase_out_for_2026(purchases: D, dollar_limit: D) -> None:
    result = run(asset(cost=D(3_000_000), asset_class="machinery"), method="section_179", total_179_purchases=purchases)
    s179 = result["section_179"]["2026"]
    assert s179["line_1_limit"] == "2560000" and s179["line_3_threshold"] == "4090000"
    assert D(s179["line_5_dollar_limit"]) == dollar_limit
    assert D(result["assets"][0]["section_179_elected"]) == min(dollar_limit, D(3_000_000))


def test_basis_exactly_at_the_179_limit_is_fully_expensed() -> None:
    result = run(asset(cost=D(2_560_000), asset_class="machinery"), method="section_179")
    assert result["federal"]["tax_year_deduction"] == "2560000"
    assert result["federal"]["carryforward"] == "0"


def test_passenger_car_first_year_cap_with_and_without_bonus_2026() -> None:
    car = asset(asset_class="passenger_vehicle", cost=D(80000))
    with_bonus = run(car, method="bonus")
    without = run(car, method="macrs")
    assert with_bonus["federal"]["tax_year_deduction"] == "20300"  # Rev. Proc. 2026-15 Table 1
    assert without["federal"]["tax_year_deduction"] == "12300"     # Table 2 (20% of 80,000 = 16,000, capped)
    for result in (with_bonus, without):
        assert sum(totals(result)) == 80000  # the rest is recovered after the recovery period


def test_heavy_suv_section_179_is_capped_at_the_suv_limit() -> None:
    suv = asset(asset_class="heavy_vehicle", cost=D(90000))
    result = run(suv, method="section_179")
    assert result["assets"][0]["section_179_elected"] == "32000"  # Rev. Proc. 2025-32
    exempt = run(asset(asset_class="heavy_vehicle", cost=D(90000), suv_cap_exempt=True), method="section_179")
    assert exempt["assets"][0]["section_179_elected"] == "90000"


def test_residential_rental_january_uses_mid_month_and_excludes_land() -> None:
    building = asset(asset_class="residential_rental", cost=D(350000), land_value=D(50000),
                     placed_in_service=date(2026, 1, 10), acquired=date(2026, 1, 5))
    result = run(building, method="macrs")
    rows = totals(result)
    assert result["assets"][0]["business_basis"] == "300000"
    assert rows[0] == 10455   # 300,000 x 3.485%
    assert rows[1] == 10908   # 300,000 x 3.636%
    assert sum(rows) == 300000
    assert result["assets"][0]["convention"] == "MM"


def test_mid_quarter_trigger_just_under_and_just_over_40_percent() -> None:
    def year(q4_cost: int, q1_cost: int) -> dict:
        return run(
            asset(id="q1", cost=D(q1_cost), placed_in_service=date(2026, 2, 1), acquired=date(2026, 1, 1)),
            asset(id="q4", cost=D(q4_cost), placed_in_service=date(2026, 11, 1), acquired=date(2026, 10, 1)),
            method="macrs",
        )
    under = year(q4_cost=40000, q1_cost=60000)   # exactly 40%: not more than 40%
    over = year(q4_cost=40001, q1_cost=59999)
    assert under["federal"]["conventions"]["2026"] == "HY"
    assert over["federal"]["conventions"]["2026"] == "MQ"
    assert any("Mid-quarter convention applied" in w for w in over["warnings"])


def test_mid_quarter_test_uses_basis_after_179_but_before_bonus() -> None:
    # All basis in Q4, but Section 179 expenses the Q4 asset entirely: no MQ.
    result = run(
        asset(id="q1", cost=D(10000), asset_class="furniture", placed_in_service=date(2026, 2, 1), acquired=date(2026, 1, 1),
              section_179_amount=D(0)),
        asset(id="q4", cost=D(50000), placed_in_service=date(2026, 11, 1), acquired=date(2026, 10, 1)),
        method="section_179",
    )
    assert result["federal"]["conventions"]["2026"] == "HY"


# --- Selected convention ------------------------------------------------------

def test_selected_mid_quarter_uses_the_quarter_table_regardless_of_the_40_percent_test() -> None:
    # A lone Q1 asset: the test says half-year, the user chose mid-quarter.
    result = run(asset(convention="MQ"), method="macrs")
    one = result["assets"][0]
    assert one["convention"] == "MQ" and one["convention_selected"]
    assert totals(result) == [35000, 26000, 15600, 11010, 11010, 1380]   # Table A-2, Q1
    assert sum(totals(result)) == 100000
    assert any("mid-quarter convention used as selected" in w and "calls for half-year" in w
               for w in result["warnings"])
    assert "MQ convention, selected" in str(one["tape"])


def test_selected_half_year_overrides_a_required_mid_quarter() -> None:
    result = run(asset(placed_in_service=date(2026, 11, 1), acquired=date(2026, 10, 1), convention="HY"),
                 method="macrs")
    assert result["federal"]["conventions"]["2026"] == "MQ"   # what the law's test says
    assert result["assets"][0]["convention"] == "HY"          # what was applied
    assert totals(result)[0] == 20000                         # Table A-1, half-year
    assert any("calls for mid-quarter" in w for w in result["warnings"])
    # The automatic-MQ message is not shown: no asset used the test's result.
    assert not any("Mid-quarter convention applied" in w for w in result["warnings"])


def test_selecting_what_the_test_requires_is_silent() -> None:
    result = run(asset(convention="HY"), method="macrs")
    assert totals(result) == [20000, 32000, 19200, 11520, 11520, 5760]
    assert not any("as selected" in w for w in result["warnings"])
    assert result["assets"][0]["convention_selected"]


def test_mixed_conventions_in_one_year_are_flagged() -> None:
    result = run(asset(id="a", convention="MQ"), asset(id="b"), method="macrs")
    assert [a["convention"] for a in result["assets"]] == ["MQ", "HY"]
    assert any("more than one convention" in w for w in result["warnings"])


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"convention": "MM"}, "mid-month convention applies only"),
        ({"asset_class": "residential_rental", "cost": D(300000), "convention": "HY"}, "buildings use the mid-month"),
        ({"convention": "XX"}, "convention must be"),
    ],
)
def test_impossible_convention_selections_are_input_errors(overrides: dict, message: str) -> None:
    with pytest.raises(InputError, match=message):
        validate(CalculationInput(tax_year=2026, assets=(asset(**overrides),)), RULES)


def test_selected_mid_month_on_a_building_matches_the_automatic_result() -> None:
    building = {"asset_class": "nonresidential", "cost": D(390000),
                "placed_in_service": date(2026, 1, 10), "acquired": date(2026, 1, 5)}
    assert totals(run(asset(**building, convention="MM"), method="macrs")) == \
        totals(run(asset(**building), method="macrs"))


def test_decoupled_state_adds_back_80000_and_recovers_exactly_80000() -> None:
    result = run(asset(), method="bonus", state="CA")  # California 2026: verified, no bonus
    state = result["state"]
    assert state["status"] == "computed"
    adjustments = [int(r["adjustment"]) for r in state["rows"]]
    assert adjustments[0] == 80000
    assert -sum(adjustments[1:]) == 80000
    assert state["reverses"]


def test_business_use_below_100_prorates_basis() -> None:
    result = run(asset(business_use_pct=D(60)), method="macrs")
    assert result["assets"][0]["business_basis"] == "60000"
    assert totals(result)[0] == 12000


def test_listed_property_at_or_below_50_percent_gets_ads_straight_line_and_no_bonus() -> None:
    car = asset(asset_class="passenger_vehicle", cost=D(30000), business_use_pct=D(50))
    result = run(car, method="section_179_bonus")
    a = result["assets"][0]
    assert a["system"] == "ADS" and a["method"] == "SL"
    assert a["bonus"] == "0" and a["section_179_elected"] == "0"
    assert totals(result)[0] == 1500  # 15,000 x 10% (Table A-8)
    over = run(asset(asset_class="passenger_vehicle", cost=D(30000), business_use_pct=D(51)), method="macrs")
    assert over["assets"][0]["system"] == "GDS"


def test_section_179_limited_by_taxable_income_carries_forward() -> None:
    result = run(asset(), method="section_179", taxable_business_income=D(30000))
    assert result["federal"]["tax_year_deduction"] == "30000"
    assert result["federal"]["carryforward"] == "70000"
    assert any("$70,000 carried forward" in w for w in result["warnings"])
    assert result["federal"]["check"]["ok"]


def test_zero_taxable_income_defers_all_section_179() -> None:
    result = run(asset(), method="section_179", taxable_business_income=D(0))
    assert result["federal"]["tax_year_deduction"] == "0"
    assert result["federal"]["carryforward"] == "100000"


def test_prior_year_carryover_is_deducted_within_the_income_limit() -> None:
    result = run(asset(cost=D(10000)), method="section_179", section_179_carryover=D(5000),
                 taxable_business_income=D(12000))
    s179 = result["section_179"]["2026"]
    assert s179["line_12_deduction"] == "12000" and s179["line_13_carryforward"] == "3000"
    assert result["federal"]["first_year"]["carryover_used"] == "2000"


def test_election_out_of_bonus_applies_to_the_whole_class() -> None:
    result = run(asset(id="a", elect_out_bonus=True), asset(id="b"), method="bonus")
    assert all(a["bonus"] == "0" for a in result["assets"])


def test_qualified_production_property_gets_the_168n_allowance_when_dates_qualify() -> None:
    plant = asset(asset_class="qualified_production", cost=D(1_000_000), placed_in_service=date(2026, 3, 1),
                  acquired=date(2025, 3, 1), qpp_elect=True, qpp_construction_began=date(2025, 3, 1))
    assert run(plant)["federal"]["tax_year_deduction"] == "1000000"
    early = asset(asset_class="qualified_production", cost=D(1_000_000), placed_in_service=date(2026, 3, 1),
                  acquired=date(2024, 3, 1), qpp_elect=True, qpp_construction_began=date(2024, 6, 1))
    assert run(early)["assets"][0]["special_allowance"] == "0"


def test_clean_vehicle_credit_reduces_basis() -> None:
    result = run(asset(asset_class="heavy_vehicle", cost=D(70000), clean_vehicle_credit=D(7500)), method="macrs")
    assert result["assets"][0]["business_basis"] == "62500"


# --- Boundaries ---------------------------------------------------------------

def test_acquired_january_19_vs_20_2025() -> None:
    def rate(acquired: date) -> str:
        return run(asset(placed_in_service=date(2025, 6, 1), acquired=acquired), tax_year=2025)["assets"][0]["bonus_rate"]
    assert rate(date(2025, 1, 19)) == "40"
    assert rate(date(2025, 1, 20)) == "100"


def test_reduced_40_percent_election_for_2025() -> None:
    result = run(asset(placed_in_service=date(2025, 6, 1), acquired=date(2025, 3, 1), elect_reduced_bonus=True), tax_year=2025)
    assert result["assets"][0]["bonus_rate"] == "40"


def test_pre_2025_acquisition_placed_in_service_in_2026_gets_20_percent() -> None:
    result = run(asset(placed_in_service=date(2026, 2, 1), acquired=date(2024, 12, 1)))
    assert result["assets"][0]["bonus_rate"] == "20"


def test_worked_example_179_then_20_percent_bonus_then_macrs() -> None:
    """A 7-year machine acquired Dec. 10, 2024 under a binding contract and placed in service
    Feb. 1, 2026: pre-OBBBA acquisition, so 20% bonus (TCJA phase-down for 2026).

    Bonus only:  20% x 100,000 = 20,000; MACRS 14.29% x 80,000 = 11,432; first year 31,432.
    179 of 30,000 first: bonus 20% x 70,000 = 14,000; MACRS 14.29% x 56,000 = 8,002.40 -> 8,002;
    first year 30,000 + 14,000 + 8,002 = 52,002.
    """
    machine = asset(asset_class="machinery", placed_in_service=date(2026, 2, 1), acquired=date(2024, 12, 10))
    bonus_only = run(machine, method="bonus")["federal"]["schedule"][0]
    assert (bonus_only["section_179"], bonus_only["bonus"], bonus_only["macrs"], bonus_only["total"]) == (
        "0", "20000", "11432", "31432")
    ordered = run(replace(machine, section_179_amount=D(30000)), method="section_179_bonus")
    first = ordered["federal"]["schedule"][0]
    assert (first["section_179"], first["bonus"], first["macrs"], first["total"]) == (
        "30000", "14000", "8002", "52002")


def test_the_reduced_bonus_election_is_refused_outside_its_years() -> None:
    with pytest.raises(InputError, match="40% election is available only for property placed in service in 2025"):
        validate(CalculationInput(tax_year=2026, assets=(asset(elect_reduced_bonus=True),)), RULES)


def test_december_31_vs_january_1_placement() -> None:
    dec = run(asset(placed_in_service=date(2025, 12, 31), acquired=date(2025, 12, 1)), method="macrs", tax_year=2026)
    jan = run(asset(placed_in_service=date(2026, 1, 1), acquired=date(2025, 12, 1)), method="macrs", tax_year=2026)
    assert dec["federal"]["schedule"][0]["year"] == 2025 and dec["federal"]["conventions"]["2025"] == "MQ"
    assert jan["federal"]["schedule"][0]["year"] == 2026 and jan["federal"]["conventions"]["2026"] == "HY"
    assert dec["federal"]["tax_year_deduction"] == "38000"  # year 2 of Table A-5
    assert jan["federal"]["tax_year_deduction"] == "20000"


def test_mid_year_state_change_turns_on_the_acquisition_date() -> None:
    """Delaware 2026: pre-2025 law applies only to property acquired after Dec. 31, 2025."""
    before = run(asset(acquired=date(2025, 12, 31), placed_in_service=date(2026, 3, 1)), state="DE")
    after = run(asset(acquired=date(2026, 1, 1), placed_in_service=date(2026, 3, 1)), state="DE")
    assert before["state"]["tax_year_adjustment"] == "0"
    assert int(after["state"]["tax_year_adjustment"]) > 0  # state allows 20% bonus, federal 100%


def test_unsupported_tax_year_is_refused() -> None:
    with pytest.raises(UnsupportedYearError):
        run(asset(placed_in_service=date(2019, 3, 1), acquired=date(2019, 3, 1)), tax_year=2019)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"cost": D(-1)}, "greater than zero"),
        ({"business_use_pct": D(0)}, "business use"),
        ({"business_use_pct": D(101)}, "business use"),
        ({"acquired": date(2026, 4, 1)}, "acquisition date"),
        ({"placed_in_service": date(2027, 1, 1), "acquired": date(2026, 1, 1)}, "after tax year"),
        ({"asset_class": "residential_rental", "land_value": D(200000)}, "land value cannot exceed"),
        ({"asset_class": "computers", "land_value": D(10)}, "only to buildings"),
        ({"asset_class": "other"}, "recovery period"),
    ],
)
def test_invalid_inputs_are_rejected(overrides: dict, message: str) -> None:
    with pytest.raises(InputError) as caught:
        validate(CalculationInput(tax_year=2026, assets=(asset(**overrides),)), RULES)
    assert message in str(caught.value).lower() or message in str(caught.value)


def test_invalid_state_code_is_rejected() -> None:
    with pytest.raises(InputError, match="not a supported state"):
        validate(CalculationInput(tax_year=2026, assets=(asset(),), state="ZZ"), RULES)


# --- Properties (seeded) ---------------------------------------------------------

CLASSES = ["computers", "furniture", "machinery", "qip", "passenger_vehicle", "heavy_vehicle",
           "residential_rental", "nonresidential", "land_improvements"]


def random_asset(rng: random.Random, index: int, year: int) -> AssetInput:
    cls = rng.choice(CLASSES)
    cost = D(rng.randint(1_000, 3_000_000))
    pis = date(year, rng.randint(1, 12), rng.randint(1, 28))
    acquired = date(pis.year, rng.randint(1, pis.month), 1)
    land = D(rng.randint(0, int(cost) // 3)) if cls in ("residential_rental", "nonresidential") else D(0)
    use = D(rng.choice([100, 100, 80, 60, 51, 50, 30]))
    return AssetInput(id=f"r{index}", description="", asset_class=cls, cost=cost, placed_in_service=pis,
                      acquired=acquired, business_use_pct=use, land_value=land)


def random_request(rng: random.Random) -> CalculationInput:
    year = rng.choice(RULES.supported_years)
    assets = tuple(random_asset(rng, i, year) for i in range(rng.randint(1, 4)))
    income = rng.choice([None, D(0), D(rng.randint(0, 2_000_000))])
    return CalculationInput(tax_year=year, assets=assets, method=rng.choice(list(SCENARIOS)),
                            taxable_business_income=income)


@pytest.mark.parametrize("seed", range(150))
def test_schedule_properties_hold_for_random_inputs(seed: int) -> None:
    rng = random.Random(seed)
    request = random_request(rng)
    computation = compute(request, RULES, SCENARIOS[request.method])
    for a in computation.assets:
        rows = [row.total for row in a.rows]
        assert all(value >= 0 for value in rows), "never negative"
        assert sum(rows) <= a.business_basis, "never more than basis"
        assert sum(rows) + a.section_179_carryforward == a.business_basis, "totals to basis"
    # Deterministic: the same input gives the same output.
    again = compute(request, RULES, SCENARIOS[request.method])
    assert [[r.to_dict() for r in a.rows] for a in again.assets] == [[r.to_dict() for r in a.rows] for a in computation.assets]


@pytest.mark.parametrize("seed", range(40))
def test_depreciation_is_monotonic_in_cost(seed: int) -> None:
    rng = random.Random(1000 + seed)
    cls = rng.choice(["computers", "furniture", "machinery", "residential_rental", "nonresidential"])
    year = rng.choice(RULES.supported_years)
    pis = date(year, rng.randint(1, 12), 1)
    low, high = sorted(rng.sample(range(1_000, 900_000), 2))

    def first_and_total(cost: int) -> tuple[D, D]:
        request = CalculationInput(tax_year=year, method="macrs", assets=(
            AssetInput(id="m", description="", asset_class=cls, cost=D(cost), placed_in_service=pis, acquired=pis),))
        result = compute(request, RULES, SCENARIOS["macrs"])
        return result.assets[0].rows[0].total, result.total

    first_low, total_low = first_and_total(low)
    first_high, total_high = first_and_total(high)
    assert first_high >= first_low and total_high >= total_low
