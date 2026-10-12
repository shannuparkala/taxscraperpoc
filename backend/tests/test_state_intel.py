"""State Intelligence: every state exists, every field is sourced, gaps say so.

The invariant (CLAUDE.md rule 7): a state page never shows another state's
rule or a guess. A field appears for a year only when that state's own file
lists the year; otherwise the section reads "Not yet verified".
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from app.services import reference_data as rd
from app.services import state_intel_service as svc
from app.services.assistant import state_registry
from app.services.depreciation.rules import get_rules
from scripts.research_state_intel import allowed_host

FIFTY_PLUS_DC = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM",
    "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY",
}



def test_all_fifty_states_and_dc_have_a_file() -> None:
    assert set(rd.state_intel_codes()) == FIFTY_PLUS_DC


@pytest.mark.parametrize("year", rd.SUPPORTED_YEARS)
@pytest.mark.parametrize("code", sorted(FIFTY_PLUS_DC))
def test_every_state_loads_its_own_profile_for_every_year(code: str, year: int) -> None:
    profile = svc.profile(code, year)
    assert profile is not None
    assert profile["code"] == code
    assert profile["tax_year"] == year
    assert [s["key"] for s in profile["sections"]] == list(svc.SECTION_ORDER)
    assert profile["disclaimer"]
    for section in profile["sections"]:
        if section["status"] == "not_verified":  # provisional sections carry fields, like verified ones
            assert section["fields"] == []
            assert svc.NOT_VERIFIED in section["message"]
            assert section["agency"]["url"], "an unverified section must still link the agency"
        else:
            assert section["fields"]
            for field in section["fields"]:
                assert field["source_url"].startswith("https://")
                assert field["source_citation"]
                assert field["last_verified"]


@pytest.mark.parametrize("code", sorted(FIFTY_PLUS_DC))
def test_fields_cite_only_that_states_own_sources(code: str) -> None:
    data = rd.state_intel(code)
    assert data is not None and data.code == code
    jurisdiction = state_registry.get(code)
    for name in rd.STATE_SECTIONS:
        for field in data.sections[name].fields:
            host = urlparse(str(field.source_url)).hostname or ""
            # The same rule the research script applies: the state's own agency or legislature.
            assert allowed_host(host, code, jurisdiction.name, jurisdiction.domains),                 f"{code}.{name}.{field.key} cites {host}"
            assert set(field.years) <= set(rd.SUPPORTED_YEARS)


def test_a_field_is_hidden_for_a_year_it_was_not_verified_for() -> None:
    # California's doing-business thresholds are published for 2025 only.
    shown_2025 = {f["key"] for s in svc.profile("CA", 2025)["sections"] for f in s["fields"]}
    shown_2026 = {f["key"] for s in svc.profile("CA", 2026)["sections"] for f in s["fields"]}
    assert "income_economic_nexus" in shown_2025
    assert "income_economic_nexus" not in shown_2026


def test_an_unverified_state_shows_not_verified_not_a_neighbour(monkeypatch: pytest.MonkeyPatch) -> None:
    empty = rd.StateIntelFile(code="WY", name="Wyoming",
                              sections={name: rd.StateSection() for name in rd.STATE_SECTIONS})
    monkeypatch.setattr(svc.reference_data, "state_intel", lambda code: empty if code == "WY" else None)
    profile = svc.profile("WY", 2026)
    stored = [s for s in profile["sections"] if s["key"] != "conformity"]
    assert all(s["status"] == "not_verified" and s["fields"] == [] for s in stored)
    assert all(s["agency"]["url"] for s in stored)


def test_automated_fields_carry_their_page_match() -> None:
    for code in sorted(FIFTY_PLUS_DC):
        data = rd.state_intel(code)
        for name in rd.STATE_SECTIONS:
            for field in data.sections[name].fields:
                if field.verification == "automated_page_match":
                    assert field.quote and len(field.quote) >= 40, f"{code}.{name}.{field.key} has no usable page text"


@pytest.mark.parametrize("year", rd.SUPPORTED_YEARS)
@pytest.mark.parametrize("code", sorted(FIFTY_PLUS_DC))
def test_conformity_matches_the_depreciation_calculators_table(code: str, year: int) -> None:
    """One source of truth: the conformity tab is read from state_conformity.json."""
    entry = get_rules().state_entry(code, year)
    section = next(s for s in svc.profile(code, year)["sections"] if s["key"] == "conformity")
    assert section["shared_with"] == "depreciation_calculator"
    if not svc.conformity_is_verified(entry):
        # Unverified, or "no income tax" left undated by the researcher on purpose:
        # shown as provisional (labelled, with the state's own source) when the
        # research exists, never as verified.
        if entry and entry.get("source_url") and entry.get("summary"):
            assert section["status"] == "provisional"
            assert "not yet confirmed" in section["message"]
            assert all(f["source_url"] == entry["source_url"] for f in section["fields"])
            assert all(f["verification"] == "provisional" for f in section["fields"])
        else:
            assert section["status"] == "not_verified"
        return
    assert section["status"] == "verified"
    assert section["as_of"] == entry["last_verified"]
    by_key = {f["key"]: f for f in section["fields"]}
    assert by_key["summary"]["value"] == entry["summary"]
    if entry["conformity"].get("date"):
        assert by_key["date"]["value"] == entry["conformity"]["date"]
    assert all(f["source_url"] == entry["source_url"] for f in section["fields"])


def test_unsupported_year_and_unknown_state_return_nothing() -> None:
    assert svc.profile("CA", 2019) is None
    assert svc.profile("ZZ", 2026) is None


def test_due_rules_are_offered_only_for_their_years() -> None:
    assert svc.profile("CA", 2026)["due_rules"]["entities"]["c_corp"]["extended_due"]["months_after_year_end"] == 11
    assert svc.profile("WY", 2026)["due_rules"] is None


def test_refresh_script_builds_questions_without_calling_anything() -> None:
    from scripts.refresh_state_intel import build

    proposals = build(2026, ["CA", "WY"], ["rates", "nexus"])
    assert [p.key for p in proposals] == ["CA.rates.2026", "CA.nexus.2026", "WY.rates.2026", "WY.nexus.2026"]
    assert all("tax year 2026" in p.question for p in proposals)
    assert proposals[0].current and not proposals[2].current
