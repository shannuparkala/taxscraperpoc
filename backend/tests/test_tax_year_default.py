"""The default tax year: one setting, clamped per product, never silent.

``Settings.default_tax_year`` (``DEFAULT_TAX_YEAR``) is the only place the
default is set (owner's decision 2026-10-11). Each product clamps it to the
years its rules cover; the workpaper pipeline, which has 2024-2025 constants
only, says so in a review item when it has to assume a year.
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.core.tax_year import resolve, resolve_default_year


def test_the_default_is_2026_and_comes_from_settings() -> None:
    assert get_settings().default_tax_year == 2026
    assert resolve_default_year([2021, 2022, 2023, 2024, 2025, 2026]) == 2026


def test_the_environment_overrides_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEFAULT_TAX_YEAR", "2025")
    get_settings.cache_clear()
    assert resolve_default_year([2024, 2025, 2026]) == 2025


@pytest.mark.parametrize(
    ("supported", "configured", "expected", "clamped"),
    [
        ([2025, 2026], 2026, 2026, False),
        ([2024, 2025], 2026, 2025, True),       # the 1040 engine today: latest year before
        ([2021, 2023, 2026], 2025, 2023, True),  # a gap: still the latest earlier year
        ([2027, 2028], 2026, 2027, True),        # nothing earlier: the earliest supported
    ],
)
def test_clamping(supported: list[int], configured: int, expected: int, clamped: bool) -> None:
    resolved = resolve(supported, configured)
    assert (resolved.year, resolved.clamped, resolved.configured) == (expected, clamped, configured)


def test_a_product_with_no_years_has_no_default() -> None:
    with pytest.raises(ValueError):
        resolve([], 2026)


def test_the_depreciation_calculator_opens_on_the_configured_year(client, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.get("/api/depreciation/rules").json()["default_year"] == 2026
    monkeypatch.setenv("DEFAULT_TAX_YEAR", "2024")
    get_settings.cache_clear()
    assert client.get("/api/depreciation/rules").json()["default_year"] == 2024


def test_the_shared_year_selector_gets_the_default_from_the_server(client) -> None:
    body = client.get("/api/reference/dashboard").json()
    assert body["default_tax_year"] == 2026
    assert 2026 in body["supported_years"]


def test_a_workpaper_with_no_stated_year_assumes_the_engines_latest_year() -> None:
    """The engine holds 2024-2025 constants, so the 2026 default clamps to 2025 - and says so."""
    from app.services.tax_engine import tax_tables
    from app.services.workflow_orchestrator import _assumed_return_year

    assumed = _assumed_return_year()
    assert assumed.year == max(tax_tables.SUPPORTED_YEARS) == 2025
    assert assumed.clamped and assumed.configured == 2026


def test_the_reduced_bonus_election_years_come_from_the_rule_data() -> None:
    from decimal import Decimal

    from app.services.depreciation.rules import get_rules

    rate, years = get_rules().reduced_bonus_election()
    assert (rate, years) == (Decimal(40), (2025,))
