"""Integrity of the depreciation rule data: tables, sources, states.

These tests read the JSON rule files directly. A rule file that fails here
would produce wrong schedules everywhere, so it is checked before any
arithmetic is.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.assistant import state_registry
from app.services.depreciation.rules import DepreciationRules, UnsupportedYearError


@pytest.fixture(scope="module")
def rules() -> DepreciationRules:
    return DepreciationRules()


# --- MACRS tables -------------------------------------------------------------

def test_every_macrs_table_column_sums_to_exactly_100_percent(rules: DepreciationRules) -> None:
    for table_id, table in rules.tables["tables"].items():
        columns = table.get("periods") or table["months"]
        for column, values in columns.items():
            assert sum(Decimal(v) for v in values) == Decimal(100), f"{table_id}[{column}]"


def test_recovery_tables_have_recovery_period_plus_one_rows(rules: DepreciationRules) -> None:
    """Half-year and mid-quarter tables spill into one extra year."""
    for table_id, table in rules.tables["tables"].items():
        for period, values in (table.get("periods") or {}).items():
            assert len(values) == int(period) + 1, f"{table_id}[{period}]"


def test_mid_month_tables_have_the_published_row_counts(rules: DepreciationRules) -> None:
    residential = rules.tables["tables"]["residential_mm"]["months"]
    # Table A-6: placed in service January-June ends in year 28, July-December in year 29.
    assert all(len(residential[str(m)]) == 28 for m in range(1, 7))
    assert all(len(residential[str(m)]) == 29 for m in range(7, 13))
    nonresidential = rules.tables["tables"]["nonresidential_mm"]["months"]
    assert all(len(nonresidential[str(m)]) == 40 for m in range(1, 13))


def test_tables_match_spot_values_printed_in_pub_946(rules: DepreciationRules) -> None:
    t = rules.tables["tables"]
    assert t["gds_hy"]["periods"]["5"] == ["20.00", "32.00", "19.20", "11.52", "11.52", "5.76"]
    assert t["gds_hy"]["periods"]["7"][:2] == ["14.29", "24.49"]
    assert t["gds_mq4"]["periods"]["5"][:3] == ["5.00", "38.00", "22.80"]
    assert t["residential_mm"]["months"]["1"][:2] == ["3.485", "3.636"]
    assert t["nonresidential_mm"]["months"]["1"][0] == "2.461"
    assert t["nonresidential_mm"]["months"]["3"][0] == "2.033"
    assert t["sl_hy"]["periods"]["5"] == ["10.0", "20.0", "20.0", "20.0", "20.0", "10.0"]


def test_macrs_tables_carry_their_source(rules: DepreciationRules) -> None:
    assert rules.tables["source_url"].startswith("https://www.irs.gov/")
    assert rules.tables["source_citation"]
    assert rules.tables["last_verified"]


# --- Federal rule entries -----------------------------------------------------

def _entries(node, path=""):
    """Every dict in the federal file that holds a value and so needs a source."""
    if isinstance(node, dict):
        if "source_url" in node or "source_citation" in node:
            yield path, node
        for key, value in node.items():
            if not key.startswith("_"):
                yield from _entries(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _entries(value, f"{path}[{index}]")


def test_every_federal_rule_entry_has_a_source_and_verification_date(rules: DepreciationRules) -> None:
    entries = list(_entries(rules.federal))
    assert len(entries) >= 20
    for path, entry in entries:
        assert entry.get("source_url", "").startswith("https://"), path
        assert entry.get("source_citation"), path
        assert entry.get("last_verified"), path
        assert "verified" in entry, path


def test_every_supported_year_has_179_and_auto_cap_entries(rules: DepreciationRules) -> None:
    for year in rules.supported_years:
        assert str(year) in rules.federal["section_179"]
        assert str(year) in rules.federal["luxury_auto_caps"]
    assert len(rules.supported_years) >= 6  # the last five years plus the current one


def test_every_asset_class_is_sourced(rules: DepreciationRules) -> None:
    for cls in rules.classes.values():
        assert cls.ref.source_url.startswith("https://"), cls.key
        assert cls.ref.source_citation, cls.key
        assert cls.ref.last_verified, cls.key


def test_unsupported_year_is_refused_not_guessed(rules: DepreciationRules) -> None:
    with pytest.raises(UnsupportedYearError, match="not supported"):
        rules.section_179(2020)
    with pytest.raises(UnsupportedYearError):
        rules.auto_caps(2027, with_bonus=True)


# --- State conformity table ---------------------------------------------------

EXPECTED_CODES = {j.code for j in state_registry.JURISDICTIONS if j.kind != "territory"}


def test_all_50_states_and_dc_have_an_entry_for_every_supported_year(rules: DepreciationRules) -> None:
    assert set(rules.state_codes) == EXPECTED_CODES
    assert len(EXPECTED_CODES) == 51
    for code in EXPECTED_CODES:
        years = rules.state(code)["years"]
        assert set(years) == {str(y) for y in rules.supported_years}, code


def test_every_state_entry_records_its_source_and_status(rules: DepreciationRules) -> None:
    for code in rules.state_codes:
        for year, entry in rules.state(code)["years"].items():
            assert entry["status"] in ("verified", "unverified", "no_income_tax"), (code, year)
            assert entry["source_url"].startswith("http"), (code, year)
            assert entry["source_citation"], (code, year)
            if entry["status"] == "verified":
                assert entry["last_verified"], (code, year)
            assert "bonus" in entry and "section_179" in entry
            assert entry["conformity"]["type"]


def test_states_without_an_individual_income_tax_are_recorded_as_such(rules: DepreciationRules) -> None:
    for code in ("AK", "FL", "NV", "SD", "TX", "WA", "WY"):
        assert rules.state_entry(code, 2025)["status"] == "no_income_tax", code


def test_puerto_rico_is_not_on_the_calculator_allow_list(rules: DepreciationRules) -> None:
    assert rules.state("PR") is None
