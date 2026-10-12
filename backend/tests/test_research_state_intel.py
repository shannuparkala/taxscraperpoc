"""The checks that decide whether a researched State Intelligence field is kept.

The model proposes; these functions decide, against the state's own page. No
network: pages come from a fake cache.
"""

from __future__ import annotations

from typing import Any

from scripts.research_state_intel import (
    SectionResult,
    allowed_host,
    numbers,
    page_snippet,
    tokens,
    verify,
)

NJ_DOMAINS = ("nj.gov", "www.nj.gov", "state.nj.us")


def test_only_the_states_own_hosts_count() -> None:
    assert allowed_host("www.nj.gov", "NJ", "New Jersey", NJ_DOMAINS)
    assert allowed_host("www.ftb.ca.gov", "CA", "California", ())
    assert allowed_host("leginfo.legislature.ca.gov", "CA", "California", ())
    assert allowed_host("tax.illinois.gov", "IL", "Illinois", ())
    assert allowed_host("www.ilga.gov", "IL", "Illinois", ())          # explicit legislature host
    assert not allowed_host("www.ftb.ca.gov", "NJ", "New Jersey", NJ_DOMAINS)  # another state
    assert not allowed_host("taxfoundation.org", "NJ", "New Jersey", NJ_DOMAINS)
    assert not allowed_host("www.avalara.com", "NJ", "New Jersey", NJ_DOMAINS)
    assert not allowed_host("newjersey-tax.com", "NJ", "New Jersey", NJ_DOMAINS)  # look-alike, not .gov
    assert not allowed_host("", "NJ", "New Jersey", NJ_DOMAINS)


def test_numbers_normalise_formatting() -> None:
    assert numbers("6.625% on $100,000 and 1.400%") == {"6.625", "100000", "1.4"}
    assert numbers("no figures") == set()


class FakePages:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    def get(self, url: str) -> dict[str, Any] | None:
        text = self.pages.get(url)
        if text is None:
            return None
        page_tokens = tokens(text)
        index: dict[str, list[int]] = {}
        for i, tok in enumerate(page_tokens):
            index.setdefault(tok, []).append(i)
        return {"final": url, "title": "Official page", "text": text, "tokens": page_tokens,
                "index": index, "numbers": numbers(text)}


OFFICIAL = "https://www.nj.gov/treasury/taxation/rates.shtml"
PAGE = ("Sales and Use Tax. The State of New Jersey's Sales and Use Tax rate is 6.625%. "
        "Corporations use a single sales factor with market-based sourcing for services.")


def run(raw: dict[str, Any], section: str = "rates", pages: dict[str, str] | None = None,
        grounding: list[str] | None = None) -> Any:
    result = SectionResult("NJ", section)
    verify(result, [raw], "NJ", "New Jersey", NJ_DOMAINS, FakePages(pages or {OFFICIAL: PAGE}), grounding or [])
    return result.proposals[0]


def test_a_field_whose_figures_and_phrases_are_on_the_official_page_is_kept() -> None:
    p = run({"key": "sales", "years": [2025, 2026], "value": "The state rate is 6.625%.",
             "source_url": OFFICIAL, "evidence": ["Sales and Use Tax rate", "6.625%"]})
    assert p.accepted, p.reason
    assert p.matched_url == OFFICIAL
    assert "6.625%" in p.snippet  # the page's own words, cut by the script


def test_a_figure_the_page_does_not_state_is_rejected() -> None:
    p = run({"key": "sales", "years": [2025], "value": "The state rate is 7%.",
             "source_url": OFFICIAL, "evidence": ["Sales and Use Tax rate"]})
    assert not p.accepted
    assert "figures not on" in p.reason


def test_a_secondary_source_never_counts_even_if_it_agrees() -> None:
    other = "https://taxfoundation.org/nj"
    p = run({"key": "sales", "years": [2025], "value": "The state rate is 6.625%.",
             "source_url": other, "evidence": ["Sales and Use Tax rate"]}, pages={other: PAGE})
    assert not p.accepted
    assert "not an official NJ host" in p.reason


def test_a_grounding_page_can_prove_a_field_when_the_named_url_fails() -> None:
    p = run({"key": "method", "years": [2026], "value": "Single sales factor apportionment.",
             "source_url": "https://www.nj.gov/made-up-page", "evidence": ["single sales factor", "market-based sourcing"]},
            section="apportionment", grounding=[OFFICIAL])
    assert p.accepted
    assert p.matched_url == OFFICIAL


def test_wording_alone_needs_two_phrases() -> None:
    p = run({"key": "method", "years": [2026], "value": "Three-factor apportionment.",
             "source_url": OFFICIAL, "evidence": ["single sales factor", "three-factor formula"]}, section="apportionment")
    assert not p.accepted


def test_unknown_keys_and_years_outside_the_range_are_dropped() -> None:
    assert run({"key": "made_up", "years": [2025], "value": "x 6.625%", "source_url": OFFICIAL,
                "evidence": ["6.625%"]}).reason == "unknown key"
    assert run({"key": "sales", "years": [2019], "value": "6.625%", "source_url": OFFICIAL,
                "evidence": ["6.625%"]}).reason == "missing years, value or evidence"


def test_snippet_falls_back_to_text_around_a_phrase() -> None:
    table = "FORM LIST " + "NJ-1040 Resident Return NJ-1040NR Nonresident Return " * 40
    assert "NJ-1040NR Nonresident" in page_snippet(table, ["NJ-1040NR Nonresident"], set())


def test_a_page_for_one_tax_year_proves_only_that_year() -> None:
    from scripts.research_state_intel import pinned_years

    assert pinned_years({"years": [2025, 2026], "matched_url": "https://tax.colorado.gov/DR0104EZ_2025.pdf",
                         "matched_title": ""}) == [2025]
    assert pinned_years({"years": [2025, 2026], "matched_url": "https://tax.colorado.gov/guide",
                         "matched_title": "Income tax guide"}) == [2025, 2026]
    assert pinned_years({"years": [2026], "matched_url": "https://x.gov/2025-and-2026-rates",
                         "matched_title": ""}) == [2026]


def test_one_phrase_and_a_trivial_figure_prove_nothing() -> None:
    # "1" is on almost every page; it once let a sourcing rule pass off an unrelated FAQ.
    p = run({"key": "sourcing", "years": [2026], "value": "Rule 1: services are sourced by benefit received.",
             "source_url": OFFICIAL, "evidence": ["market-based sourcing", "benefit received"]},
            section="apportionment", pages={OFFICIAL: PAGE + " Item 1."})
    assert not p.accepted


def test_the_figure_must_sit_beside_the_evidence() -> None:
    page = ("The Sales and Use Tax rate applies to retail sales of tangible property in this state. "
            "Unrelated table: 6.625 appears here without context in another part of the page entirely.")
    p = run({"key": "sales", "years": [2025], "value": "The state rate is 6.625%.", "source_url": OFFICIAL,
             "evidence": ["Sales and Use Tax rate", "retail sales"]}, pages={OFFICIAL: page})
    assert not p.accepted
    assert "beside the evidence" in p.reason


def test_every_date_in_the_value_must_be_on_the_page() -> None:
    page = ("Individual Income Tax. Filing Due Date - April 15. If you owe tax, 90% of the tax liability must be "
            "paid by April 15th to avoid penalties, with an automatic six-month extension to October 15.")
    p = run({"key": "business_due", "years": [2025], "source_url": OFFICIAL,
             "value": "C corporation returns are due May 15, extended to November 15, if 90% is paid.",
             "evidence": ["90% of the tax liability", "automatic six-month extension"]},
            section="filing", pages={OFFICIAL: page})
    assert not p.accepted
    assert "dates not on" in p.reason


def test_percentages_count_as_key_figures() -> None:
    from scripts.research_state_intel import key_numbers, numbers

    assert key_numbers(numbers("pay 90% by the 15th"), "pay 90% by the 15th") == {"90"}


def test_dates_match_with_ordinal_suffixes() -> None:
    from scripts.research_state_intel import date_on_page

    assert date_on_page("April 15", "must be paid by April 15th to avoid penalties")
    assert date_on_page("October 15", "until October 15, 2026")
    assert not date_on_page("May 15", "Filing Due Date - April 15")
    assert not date_on_page("May 1", "due May 15")
