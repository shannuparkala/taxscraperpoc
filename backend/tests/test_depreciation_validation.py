"""Cross-checks recorded in docs/validation.md.

Two independent sources:

1. **IRS Pub. 946 (2025) worked examples** - the figures the IRS prints,
   page references in each test's docstring.
2. **A first-principles MACRS computation** written here from the statute's
   method (declining balance switching to straight line, with the
   half-year / mid-quarter / mid-month fractions), sharing no code or table
   with the engine. The IRS tables round percentages to 2-3 decimals, so the
   two agree within that rounding, not to the dollar.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from app.services.depreciation.engine import AssetInput, CalculationInput
from app.services.depreciation.rules import DepreciationRules
from app.services.depreciation.service import calculate

RULES = DepreciationRules()


def run(*assets: AssetInput, method: str = "macrs", tax_year: int = 2025, **kwargs) -> dict:
    return calculate(CalculationInput(tax_year=tax_year, assets=tuple(assets), method=method, **kwargs), RULES)


def a(**kwargs) -> AssetInput:
    kwargs.setdefault("id", "x")
    kwargs.setdefault("description", "")
    kwargs.setdefault("acquired", kwargs["placed_in_service"])
    return AssetInput(**kwargs)


def schedule(result: dict, asset_id: str | None = None) -> list[int]:
    rows = (next(x for x in result["assets"] if x["id"] == asset_id)["schedule"]) if asset_id else result["federal"]["schedule"]
    return [int(r["total"]) for r in rows]


# --- 1. Pub. 946 worked examples -------------------------------------------------

def test_p946_office_furniture_half_year() -> None:
    """Pub. 946 ch. 4 'MACRS Worksheet' example: $10,000 7-year furniture, Aug. 11, 2025, Table A-1."""
    result = run(a(asset_class="furniture", cost=D(10000), placed_in_service=date(2025, 8, 11)))
    assert schedule(result) == [1429, 2449, 1749, 1249, 893, 892, 893, 446]


def test_p946_nonresidential_building_march_excludes_land() -> None:
    """Pub. 946 ch. 4 Example 1: building + land $120,000 (land $20,000), March, Table A-7a: 2,033 / 2,564 / 2,564."""
    result = run(a(asset_class="nonresidential", cost=D(120000), land_value=D(20000), placed_in_service=date(2025, 3, 8)))
    assert schedule(result)[:3] == [2033, 2564, 2564]
    assert result["assets"][0]["business_basis"] == "100000"


def test_p946_mid_quarter_three_assets() -> None:
    """Pub. 946 ch. 4 Example 2: machine $4,000 (Jan), furniture $1,000 (Sept), computer $5,000 (Oct): mid-quarter.

    Year 1: 1,000 / 107 / 250. Year 2: 857 / 255 / 1,900.
    """
    result = run(
        a(id="machine", asset_class="machinery", cost=D(4000), placed_in_service=date(2025, 1, 15)),
        a(id="furniture", asset_class="furniture", cost=D(1000), placed_in_service=date(2025, 9, 15)),
        a(id="computer", asset_class="computers", cost=D(5000), placed_in_service=date(2025, 10, 15)),
    )
    assert result["federal"]["conventions"]["2025"] == "MQ"
    assert schedule(result, "machine")[:2] == [1000, 857]
    assert schedule(result, "furniture")[:2] == [107, 255]
    assert schedule(result, "computer")[:2] == [250, 1900]


def test_p946_mid_quarter_single_december_asset() -> None:
    """Pub. 946 ch. 4 'Mid-quarter convention used' example: $10,000 5-year, Dec. 2, 2022: 500 / 3,800 / 2,280 / 1,368 (full year)."""
    result = run(a(asset_class="computers", cost=D(10000), placed_in_service=date(2022, 12, 2), acquired=date(2022, 11, 1)), tax_year=2022)
    assert schedule(result)[:4] == [500, 3800, 2280, 1368]


def test_p946_special_allowance_40_percent_2025() -> None:
    """Pub. 946 ch. 3 example: $450,000 placed in service Jan. 7, 2025, acquired before Jan. 20, 2025: 40% = $180,000."""
    result = run(a(asset_class="machinery", cost=D(450000), placed_in_service=date(2025, 1, 7), acquired=date(2024, 11, 1)), method="bonus")
    assert result["assets"][0]["bonus"] == "180000"
    assert result["assets"][0]["macrs_basis"] == "270000"


def test_p946_section_179_dollar_limit_2025() -> None:
    """Pub. 946 ch. 2 example: $2,500,000 machinery + $25,000 saw in 2025; the maximum deduction is $2,500,000."""
    result = run(
        a(id="machinery", asset_class="machinery", cost=D(2_500_000), placed_in_service=date(2025, 3, 1), section_179_amount=D(2_475_000)),
        a(id="saw", asset_class="machinery", cost=D(25000), placed_in_service=date(2025, 3, 1), section_179_amount=D(25000)),
        method="section_179",
    )
    assert result["section_179"]["2025"]["line_12_deduction"] == "2500000"
    machinery = next(x for x in result["assets"] if x["id"] == "machinery")
    assert machinery["macrs_basis"] == "25000"


def test_p946_section_179_phase_out_jane_ash() -> None:
    """Pub. 946 ch. 2 example: Jane Ash, $4,050,000 of machinery in 2025: limit reduced to $2,450,000."""
    result = run(a(asset_class="machinery", cost=D(4_050_000), placed_in_service=date(2025, 3, 1)), method="section_179")
    assert result["section_179"]["2025"]["line_5_dollar_limit"] == "2450000"


def test_p946_section_179_fully_phased_out_at_6_5_million() -> None:
    """Pub. 946 ch. 2: 'If the cost ... during 2025 is $6,500,000 or more, you cannot take a section 179 deduction.'"""
    result = run(a(asset_class="machinery", cost=D(6_500_000), placed_in_service=date(2025, 3, 1)), method="section_179")
    assert result["section_179"]["2025"]["line_5_dollar_limit"] == "0"


def test_p946_suv_cap_2025() -> None:
    """Pub. 946 ch. 2: 'You cannot elect to expense more than $31,300 of the cost of any heavy SUV ... 2025.'"""
    result = run(a(asset_class="heavy_vehicle", cost=D(70000), placed_in_service=date(2025, 3, 1)), method="section_179")
    assert result["assets"][0]["section_179_elected"] == "31300"


def test_p946_car_below_the_280f_limit() -> None:
    """Pub. 946 ch. 5 example: $14,500 car, Apr. 15, 2025, elected out of bonus: $2,900, below the $12,200 limit."""
    result = run(a(asset_class="passenger_vehicle", cost=D(14500), placed_in_service=date(2025, 4, 15)))
    assert schedule(result)[0] == 2900


def test_p946_heavy_pickup_section_179_then_table_a1() -> None:
    """Pub. 946 ch. 5 (Ellen Rye): $18,000 pickup over 6,000 lb, June 2021, $10,000 Section 179,
    then 200% DB over 5 years: depreciation for 2021-2024 totals $6,618."""
    result = run(
        a(asset_class="heavy_vehicle", cost=D(18000), placed_in_service=date(2021, 6, 1), section_179_amount=D(10000)),
        method="section_179", tax_year=2024,
    )
    rows = result["assets"][0]["schedule"]
    macrs_2021_to_2024 = sum(int(r["macrs"]) for r in rows[:4])
    assert macrs_2021_to_2024 == 6618
    assert result["assets"][0]["section_179_elected"] == "10000"


# --- Rev. Proc. golden figures ---------------------------------------------------

@pytest.mark.parametrize(("year", "with_bonus", "without"), [
    (2021, 18200, 10200), (2022, 19200, 11200), (2023, 20200, 12200),
    (2024, 20400, 12400), (2025, 20200, 12200), (2026, 20300, 12300),
])
def test_280f_first_year_caps_by_year(year: int, with_bonus: int, without: int) -> None:
    """Rev. Procs. 2021-31, 2022-17, 2023-14, 2024-13, 2025-16, 2026-15, Tables 1 and 2."""
    car = a(asset_class="passenger_vehicle", cost=D(90000), placed_in_service=date(year, 6, 1),
            acquired=date(year, 2, 1) if year != 2025 else date(2025, 3, 1))
    assert run(car, method="bonus", tax_year=year)["federal"]["tax_year_deduction"] == str(with_bonus)
    assert run(car, method="macrs", tax_year=year)["federal"]["tax_year_deduction"] == str(without)


def test_rev_proc_2019_13_safe_harbor_shape() -> None:
    """Rev. Proc. 2019-13 method: after a capped 100% bonus year, years 2-6 apply the table rate to basis less the year-1 cap."""
    result = run(a(asset_class="passenger_vehicle", cost=D(60000), placed_in_service=date(2026, 3, 1), acquired=date(2026, 2, 1)),
                 method="bonus", tax_year=2026)
    rows = schedule(result)
    assert rows[0] == 20300
    assert rows[1] == round((60000 - 20300) * 0.32)  # 12,704, below the 19,800 cap
    assert sum(rows) == 60000


# --- 2. First-principles MACRS (independent of the tables) -------------------------

FRACTION = {"HY": 0.5, "MQ1": 0.875, "MQ2": 0.625, "MQ3": 0.375, "MQ4": 0.125}


def formula_macrs(basis: float, years: int, multiple: float, convention: str) -> list[float]:
    """IRC 168(b): declining balance, switching to straight line when larger."""
    f = FRACTION[convention]
    rate = multiple / years
    out: list[float] = []
    remaining = basis
    life_left = float(years)
    for year in range(years + 1):
        portion = f if year == 0 else 1.0
        db = remaining * rate * portion
        sl = remaining / life_left * portion if life_left > 0 else remaining
        amount = min(remaining, max(db, sl)) if year < years else remaining
        out.append(amount)
        remaining -= amount
        life_left -= portion
    return out


def formula_mid_month(basis: float, years: float, month: int) -> list[float]:
    annual = basis / years
    first = annual * (12.5 - month) / 12
    out = [first]
    remaining = basis - first
    while remaining > annual:
        out.append(annual)
        remaining -= annual
    out.append(remaining)
    return out


@pytest.mark.parametrize("period,multiple,cls", [
    ("3", 2.0, "other"), ("5", 2.0, "computers"), ("7", 2.0, "furniture"),
    ("10", 2.0, "other"), ("15", 1.5, "land_improvements"), ("20", 1.5, "other"),
])
@pytest.mark.parametrize("month,convention", [(6, "HY"), (2, "MQ1"), (5, "MQ2"), (8, "MQ3"), (11, "MQ4")])
def test_table_schedules_match_first_principles(period: str, multiple: float, cls: str, month: int, convention: str) -> None:
    basis = 100000
    pis = date(2024, month, 15)
    assets = [a(id="target", asset_class=cls, cost=D(basis), placed_in_service=pis,
                recovery_years=period if cls == "other" else None)]
    if convention in ("MQ1", "MQ2", "MQ3"):
        # Mid-quarter applies to the whole year only when Q4 holds more than
        # 40% of the basis, so a large fourth-quarter asset switches it on.
        assets.append(a(id="q4", asset_class="computers", cost=D(500000), placed_in_service=date(2024, 11, 15)))
    result = run(*assets, tax_year=2024)
    assert result["federal"]["conventions"]["2024"] == ("HY" if convention == "HY" else "MQ")
    engine = schedule(result, "target")
    formula = formula_macrs(basis, int(period), multiple, convention)
    assert sum(engine) == basis
    # The IRS tables round to two decimals and force each column to 100%,
    # moving a single year by up to ~0.014% of basis (7-year, Q2, final
    # year: 3.34% printed vs 3.326% exact). A wrong table or column is off by
    # whole percentage points, so 0.02% still catches every real error.
    for got, want in zip(engine, formula):
        assert abs(got - want) <= basis * 0.0002 + 1, (period, convention, engine, [round(x) for x in formula])


@pytest.mark.parametrize("cls,years", [("residential_rental", 27.5), ("nonresidential", 39.0)])
@pytest.mark.parametrize("month", range(1, 13))
def test_mid_month_tables_match_first_principles(cls: str, years: float, month: int) -> None:
    basis = 1_000_000
    result = run(a(asset_class=cls, cost=D(basis), placed_in_service=date(2024, month, 10)), tax_year=2024)
    engine = schedule(result)
    formula = formula_mid_month(basis, years, month)
    assert sum(engine) == basis
    # The IRS builds these tables from the annual rate rounded to three
    # decimals (2.564% for 39-year) and splits the remainder between the
    # first and last years by months in service: January year 1 is 2.461%
    # printed vs 2.457% exact, about 0.004% of basis. 27.5-year alternates
    # 3.636 / 3.637. A wrong month column is off by ~0.2% a year.
    for got, want in zip(engine, formula):
        assert abs(got - want) <= basis * 0.00004 + 1, (cls, month, got, want)
