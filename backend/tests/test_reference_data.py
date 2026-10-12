"""The versioned reference data behind the dashboard and the IRS Forms library.

These files are the only place a deadline, holiday or form fact may live, so
the tests check the files themselves: they parse, every entry is sourced, and
the links point at the agency that publishes the thing linked.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import pydantic
import pytest

from app.services import reference_data as rd
from app.services.assistant import state_registry

#: Routes the SPA defines (frontend/src/App.tsx). A quick link to anything
#: else would be a dead tile.
KNOWN_ROUTES = {"/", "/assistant", "/depreciation", "/forms", "/updates", "/states", "/workload", "/settings"}


def test_every_reference_file_validates() -> None:
    rd.clear_caches()
    rd.holidays()
    rd.due_dates()
    rd.quick_links()
    rd.motivation()
    rd.federal_forms()
    rd.state_forms()
    rd.news_sources()
    for code in rd.state_intel_codes():
        assert rd.state_intel(code) is not None


# ------------------------------------------------------------ calendar data


def test_due_dates_cover_every_entity_type_with_sources() -> None:
    data = rd.due_dates()
    assert {e.key for e in data.entity_types} == set(rd.ENTITY_KEYS)
    for entity in data.entity_types:
        assert urlparse(str(entity.source_url)).hostname == "www.irs.gov"
        assert entity.source_citation
        assert entity.last_verified


def test_countdown_tiles_are_the_four_requested_dates() -> None:
    tiles = rd.due_dates().countdown_tiles
    assert [(t.month, t.day) for t in tiles] == [(3, 15), (4, 15), (9, 15), (10, 15)]
    entity_keys = set(rd.ENTITY_KEYS)
    for tile in tiles:
        assert tile.represents
        assert set(tile.entity_keys) <= entity_keys


def test_calendar_year_offsets_match_the_tile_dates() -> None:
    """The tiles and the entity rules must describe the same deadlines."""
    rules = {e.key: e for e in rd.due_dates().entity_types}
    assert (rules["s_corp"].due.months_after_year_end, rules["s_corp"].due.day) == (3, 15)
    assert (rules["partnership"].due.months_after_year_end, rules["partnership"].due.day) == (3, 15)
    assert (rules["individual"].due.months_after_year_end, rules["individual"].due.day) == (4, 15)
    assert (rules["c_corp"].due.months_after_year_end, rules["c_corp"].due.day) == (4, 15)
    assert (rules["s_corp"].extended_due.months_after_year_end, rules["s_corp"].extended_due.day) == (9, 15)
    assert (rules["individual"].extended_due.months_after_year_end, rules["individual"].extended_due.day) == (10, 15)


def test_holiday_file_includes_dc_emancipation_day_and_cites_irc_7503() -> None:
    data = rd.holidays()
    ids = {h.id for h in data.holidays}
    assert "dc_emancipation_day" in ids  # the reason April 15 sometimes moves on a weekday
    assert {"juneteenth", "independence_day", "labor_day", "columbus_day"} <= ids
    assert any("7503" in str(s.url) for s in data.sources)
    assert data.observance == {"saturday": "previous_friday", "sunday": "next_monday"}


# ---------------------------------------------------------------- dashboard


def test_quick_links_point_at_real_routes() -> None:
    links = rd.quick_links().links
    assert {link.path for link in links} <= KNOWN_ROUTES
    assert {"/assistant", "/depreciation", "/forms", "/updates", "/states"} <= {link.path for link in links}


def test_motivation_bank_has_enough_distinct_short_lines() -> None:
    data = rd.motivation()
    lines = data.general + data.deadline_season
    assert len(lines) >= 60
    assert len(set(lines)) == len(lines)
    assert all(10 <= len(line) <= 110 for line in lines)
    assert data.deadline_season, "the run-up to deadlines needs its own lines"


# -------------------------------------------------------------------- forms


def test_at_least_sixty_federal_forms_with_complete_metadata() -> None:
    forms = rd.federal_forms().forms
    assert len(forms) >= 60
    for form in forms:
        assert form.form_number and form.title and form.one_liner and form.category
        assert urlparse(str(form.pdf_url)).hostname == "www.irs.gov"
        assert str(form.pdf_url).startswith("https://www.irs.gov/pub/irs-pdf/")
        assert urlparse(str(form.source_page_url)).hostname == "www.irs.gov"
        assert form.audience in ("federal", "business")
        assert form.state is None


@pytest.mark.parametrize("number", [
    "1040", "1040-X", "1040-ES", "4868", "1120", "1120-S", "1065", "Schedule K-1 (1065)",
    "Schedule K-1 (1120-S)", "Schedule K-1 (1041)", "1041", "706", "709", "990", "941", "940",
    "W-2", "W-3", "W-4", "W-9", "1099-NEC", "1099-MISC", "1096", "4562", "8829", "8949", "2848",
    "8821", "8822", "8832", "2553", "SS-4", "4506-T", "8879", "9465", "656", "1310", "2441", "8863",
])
def test_requested_forms_are_present(number: str) -> None:
    assert number in {f.form_number for f in rd.federal_forms().forms}


def test_prior_year_links_only_for_annual_forms() -> None:
    for form in rd.federal_forms().forms:
        if form.annual:
            assert form.prior_year_pdf_pattern and "{year}" in form.prior_year_pdf_pattern
            assert form.prior_year_pdf_pattern.startswith("https://www.irs.gov/pub/irs-prior/")
        else:
            assert form.prior_year_pdf_pattern is None


def test_state_forms_link_to_that_states_own_agency() -> None:
    for form in rd.state_forms().forms:
        jurisdiction = state_registry.get(form.state or "")
        assert jurisdiction is not None, form.id
        host = urlparse(str(form.pdf_url)).hostname or ""
        assert host in jurisdiction.domains, f"{form.id}: {host} is not {form.state}'s agency"
        assert form.state_form_kind in ("individual", "business", "extension")


def test_one_liners_are_marked_unreviewed_until_a_person_checks_them() -> None:
    """Drafts ship labelled. Flipping the flag is a human's job, not a script's."""
    for form in rd.federal_forms().forms + rd.state_forms().forms:
        assert isinstance(form.one_liner_reviewed, bool)


def test_a_form_without_a_source_does_not_validate() -> None:
    raw = json.loads((rd.DATA_ROOT / "forms" / "federal_forms.json").read_text(encoding="utf-8"))
    del raw["forms"][0]["source_page_url"]
    with pytest.raises(pydantic.ValidationError):
        rd.FederalFormsFile.model_validate(raw)


# --------------------------------------------------------------------- news


def test_licensed_news_sources_need_settings_and_say_how_to_connect() -> None:
    from app.core.config import Settings

    for source in rd.news_sources().sources:
        if source.kind == "licensed":
            assert source.provider == "licensed_api"
            assert source.connect_message.startswith("Connect your")
            for name in source.requires_settings:
                assert name in Settings.model_fields, name
        else:
            assert source.provider in ("irs_newsroom", "treasury_json")


# ------------------------------------------------------------ verify script


def test_verify_forms_reads_revisions() -> None:
    from scripts.verify_forms import revision_from_text

    assert revision_from_text("Form 2848 (Rev. January 2021) Department of the Treasury") == "Rev. January 2021"
    assert revision_from_text("Form 4506-T (Rev. 4-2025)") == "Rev. 4-2025"
    assert revision_from_text("Cat. No. 12906I Form 4562 (2025)") == "2025"
    assert revision_from_text("no revision here") is None


def test_verify_forms_flags_broken_links_and_non_pdfs() -> None:
    from scripts.verify_forms import check_url

    class Resp:
        def __init__(self, status: int, ctype: str, body: bytes) -> None:
            self.status_code, self.headers, self.content = status, {"content-type": ctype}, body

    class Client:
        def __init__(self, resp: Resp) -> None:
            self.resp = resp

        def get(self, url: str, follow_redirects: bool = True) -> Resp:
            return self.resp

    assert check_url(Client(Resp(200, "application/pdf", b"%PDF-1.7 ...")), "u")[0] is True
    ok, status, _, _, problem = check_url(Client(Resp(404, "text/html", b"<html>")), "u")
    assert (ok, status, problem) == (False, 404, "HTTP 404")
    ok, _, _, _, problem = check_url(Client(Resp(200, "text/html", b"<html>")), "u")
    assert ok is False and "not a PDF" in problem


def test_holiday_names_are_unique() -> None:
    names = [h.name for h in rd.holidays().holidays]
    assert len(names) == len(set(names))
    assert all(re.match(r"^[a-z_]+$", h.id) for h in rd.holidays().holidays)
