"""Industry Updates with mocked feeds: parsing, de-duplication, failure isolation.

No test makes a network call - every fetch goes through an injected fake.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.core.config import get_settings
from app.services import reference_data as rd
from app.services.news_service import (
    IrsNewsroomProvider,
    NewsItem,
    NewsService,
    TreasuryJsonProvider,
    assign_topics,
    dedupe,
    excerpt,
    parse_us_date,
)

IRS_HTML = """
<html><body><article>
<div class="field--item"><div class="field_pup_media_document_teaser"><h2>
  <a href="/newsroom/irs-announces-new-guidance-for-employers"><span>IRS announces new guidance for employers</span></a>
</h2></div>
<div class="field field--name-field-pup-description-abstract">IR-2026-120, Oct. 7, 2026 — The Internal Revenue Service today issued guidance on payroll withholding.</div>
</div>
<div class="field--item"><div class="field_pup_media_document_teaser"><h2>
  <a href="/newsroom/second-release"><span>Charities reminded of exempt organization filing</span></a>
</h2></div>
<div class="field field--name-field-pup-description-abstract">IR-2026-119, Sept. 30, 2026 — Reminder for exempt organizations.</div>
</div>
</article></body></html>
"""

TREASURY_JSON = {
    "homepagePressReleases": [
        {"categorySlug": "press-releases", "date": "2026-10-06", "title": "Treasury issues proposed regulations",
         "url": "/news/press-releases/sb0651/", "description": "Proposed rule on clean energy credits."},
        {"categorySlug": "featured-stories", "date": "2026-10-05", "title": "Not a press release",
         "url": "/news/featured-stories/x/", "description": ""},
    ],
    "rightRail": [
        # Same announcement as the IRS item, different site: de-duplicated by title.
        {"categorySlug": "press-releases", "date": "2026-10-07", "title": "IRS announces new guidance for employers",
         "url": "/news/press-releases/sb0652/", "description": "Duplicate."},
    ],
}


def _source(key: str):
    return next(s for s in rd.news_sources().sources if s.key == key)


class FakeFetch:
    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str] | None = None) -> httpx.Response:
        self.calls.append(url)
        for prefix, result in self.routes.items():
            if url.startswith(prefix):
                if isinstance(result, Exception):
                    raise result
                if isinstance(result, dict):
                    return httpx.Response(200, json=result, request=httpx.Request("GET", url))
                return httpx.Response(200, text=str(result), request=httpx.Request("GET", url))
        return httpx.Response(404, text="", request=httpx.Request("GET", url))


@pytest.fixture()
def enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEWS_ENABLED", "true")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


def test_irs_listing_parses_title_date_reference_and_agency_excerpt() -> None:
    items = IrsNewsroomProvider.parse(IRS_HTML, "https://www.irs.gov/newsroom/news-releases-for-current-month", _source("irs"))
    assert [i.title for i in items] == ["IRS announces new guidance for employers",
                                         "Charities reminded of exempt organization filing"]
    first = items[0]
    assert first.url == "https://www.irs.gov/newsroom/irs-announces-new-guidance-for-employers"
    assert first.published == "2026-10-07"
    assert first.reference == "IR-2026-120"
    assert first.excerpt == "The Internal Revenue Service today issued guidance on payroll withholding."
    assert items[1].published == "2026-09-30"


def test_irs_urls_include_the_previous_month_across_a_year_boundary() -> None:
    urls = IrsNewsroomProvider().urls(_source("irs"), date(2027, 1, 3))
    assert urls[1] == "https://www.irs.gov/newsroom/news-releases-for-december-2026"


def test_treasury_json_keeps_press_releases_only() -> None:
    items = TreasuryJsonProvider.parse(TREASURY_JSON, _source("treasury"))
    titles = [i.title for i in items]
    assert "Not a press release" not in titles
    assert items[0].url == "https://home.treasury.gov/news/press-releases/sb0651/"
    assert items[0].published == "2026-10-06"


def test_dedupe_by_url_and_by_title() -> None:
    def item(url: str, title: str) -> NewsItem:
        return NewsItem(id=url, source="irs", source_name="IRS", title=title, url=url, published="", excerpt="")

    kept = dedupe([
        item("https://a.gov/x", "Same Story"),
        item("https://a.gov/x/", "Different title"),  # same URL after normalization
        item("https://b.gov/y", "same story!"),       # same title after normalization
        item("https://c.gov/z", "Other"),
    ])
    assert [k.url for k in kept] == ["https://a.gov/x", "https://c.gov/z"]


def test_excerpt_is_short_and_never_the_full_text() -> None:
    long = "word " * 200
    assert len(excerpt(long)) <= 281
    assert excerpt(long).endswith("…")


def test_dates_parse_from_agency_formats() -> None:
    assert parse_us_date("IR-2026-1, Sept. 30, 2026 — x") == "2026-09-30"
    assert parse_us_date("October 1, 2026") == "2026-10-01"
    assert parse_us_date("no date") == ""


def test_topics_are_whole_word_keyword_matches() -> None:
    topics = rd.news_sources().topics
    assert "payroll" in assign_topics("New withholding tables for employers", topics)
    assert "exempt_organizations" in assign_topics("Charities reminded", topics)
    # "act" must not match "action"
    assert "legislation_regulation" not in assign_topics("Enforcement action announced", topics)


def test_one_failing_source_does_not_break_the_others(enabled) -> None:
    fetch = FakeFetch({
        "https://www.irs.gov/": httpx.ConnectTimeout("slow"),
        "https://home.treasury.gov/": TREASURY_JSON,
    })
    service = NewsService(enabled, fetch=fetch, today=lambda: date(2026, 10, 7))
    service.refresh_all(force=True)
    states = {s.key: s.state for s in service.statuses()}
    assert states["irs"] == "error"
    assert states["treasury"] == "ok"
    assert states["bloomberg_tax"] == "not_connected"
    assert states["thomson_reuters"] == "not_connected"
    assert any(i.source == "treasury" for i in service.items())


def test_cross_source_duplicates_are_removed_in_the_merged_feed(enabled) -> None:
    fetch = FakeFetch({
        "https://www.irs.gov/newsroom/news-releases-for-current-month": IRS_HTML,
        "https://home.treasury.gov/": TREASURY_JSON,
    })
    service = NewsService(enabled, fetch=fetch, today=lambda: date(2026, 10, 7))
    service.refresh_all(force=True)
    titles = [i.title for i in service.items()]
    assert titles.count("IRS announces new guidance for employers") == 1
    assert service.items(source="treasury")[0].source == "treasury"
    assert all(i.published >= "2026-10-01" for i in service.items(start=date(2026, 10, 1)))


def test_licensed_sources_stay_disabled_without_credentials(enabled) -> None:
    fetch = FakeFetch({})
    service = NewsService(enabled, fetch=fetch, today=lambda: date(2026, 10, 7))
    service.refresh_source(_source("bloomberg_tax"), force=True)
    status = next(s for s in service.statuses() if s.key == "bloomberg_tax")
    assert status.state == "not_connected"
    assert status.message == "Connect your Bloomberg Tax account to enable"
    assert fetch.calls == [], "an unconfigured licensed source must not be contacted"


def test_licensed_source_is_used_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMSON_REUTERS_API_URL", "https://api.example.com/news")
    monkeypatch.setenv("THOMSON_REUTERS_API_KEY", "test-key")
    get_settings.cache_clear()
    payload = {"items": [{"title": "Headline", "url": "https://tr.example.com/a", "published": "2026-10-01"}]}
    fetch = FakeFetch({"https://api.example.com/": payload})
    service = NewsService(get_settings(), fetch=fetch, today=lambda: date(2026, 10, 7))
    service.refresh_source(_source("thomson_reuters"), force=True)
    items = service.items(source="thomson_reuters")
    assert [i.title for i in items] == ["Headline"]
    assert items[0].excerpt == "", "no publisher text is taken from a licensed source"
    get_settings.cache_clear()


def test_public_providers_cannot_fetch_other_hosts(enabled) -> None:
    fetch = FakeFetch({"https://evil.example.com/": TREASURY_JSON})
    service = NewsService(enabled, fetch=fetch)
    get = service._guarded_get("treasury_json")
    with pytest.raises(httpx.HTTPError):
        get("https://evil.example.com/latest.json")
    assert fetch.calls == []


def test_fetches_are_rate_limited_per_source(enabled) -> None:
    now = [1000.0]
    fetch = FakeFetch({"https://home.treasury.gov/": TREASURY_JSON})
    service = NewsService(enabled, fetch=fetch, clock=lambda: now[0], today=lambda: date(2026, 10, 7))
    source = _source("treasury")
    service.refresh_source(source)
    service.refresh_source(source)  # inside the minimum interval: skipped
    assert len(fetch.calls) == 1
    now[0] += enabled.news_min_fetch_interval_seconds + 1
    service.refresh_source(source)
    assert len(fetch.calls) == 2


def test_disabled_feed_reports_disabled_and_fetches_nothing() -> None:
    fetch = FakeFetch({})
    service = NewsService(get_settings(), fetch=fetch)  # NEWS_ENABLED=false in tests
    service.refresh_all(force=True)
    states = {s.key: s.state for s in service.statuses()}
    assert states["irs"] == "disabled" and states["treasury"] == "disabled"
    assert fetch.calls == []
