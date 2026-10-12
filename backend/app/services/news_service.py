"""Industry Updates: IRS and Treasury news, plus licensed sources when configured.

What this shows, and what it never does:

* **Public sources** (IRS, Treasury) are U.S. government works. Each item is
  title, date, source, an excerpt of at most ``EXCERPT_CHARS`` characters
  taken from the agency's *own* summary line, and the link. The full text
  is never fetched or reproduced; the reader follows the link.
* **Licensed sources** (Bloomberg Tax, Thomson Reuters) are copyrighted and
  paywalled. They are never scraped. They are reachable only through the app
  owner's licensed API, configured by environment variable, and are
  reported as ``not_connected`` until it is. A licensed item carries a
  headline, date and link only.
* **Failure is per source.** One source timing out or changing its markup
  produces an error on that source's status; the others still render. The
  page never depends on every source being up.

Caching and politeness: each source is fetched at most once per
``news_min_fetch_interval_seconds`` whoever asks, results are kept in memory
and refreshed in the background every ``news_refresh_seconds``. Items are
de-duplicated by normalized URL and then by normalized title across sources
(the same announcement often appears on both IRS and Treasury pages).

Topics are assigned by keyword lists in ``reference_data/news/sources.json`` -
deterministic, no model.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.tls import httpx_verify
from app.services import reference_data
from app.services.reference_data import NewsSourceConfig

logger = get_logger(__name__)

EXCERPT_CHARS = 280
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_MAX_BYTES = 3 * 1024 * 1024

#: Hosts each public provider may fetch from. A data-file edit cannot point a
#: provider somewhere else.
_ALLOWED_HOSTS = {
    "irs_newsroom": ("www.irs.gov",),
    "treasury_json": ("home.treasury.gov",),
}


@dataclass(slots=True)
class NewsItem:
    id: str
    source: str
    source_name: str
    title: str
    url: str
    published: str  # ISO date, or "" when the source gave none
    excerpt: str
    topics: list[str] = field(default_factory=list)
    reference: str = ""  # e.g. "IR-2026-120"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SourceStatus:
    key: str
    name: str
    kind: str
    homepage: str
    state: str  # ok | error | not_connected | disabled | pending
    message: str = ""
    last_updated: str | None = None  # ISO datetime (UTC) of the last successful fetch
    item_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Fetch(Protocol):
    def __call__(self, url: str, headers: dict[str, str] | None = None) -> httpx.Response: ...


class NewsProvider(Protocol):
    def fetch(self, source: NewsSourceConfig, get: Fetch, today: date) -> list[NewsItem]: ...


class ProviderUnavailable(Exception):
    """The source cannot be used (not configured); not an error to log loudly."""


# --------------------------------------------------------------- helpers


def normalize_url(url: str) -> str:
    parts = urlparse(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunparse((parts.scheme.lower() or "https", parts.netloc.lower(), path, "", "", ""))


def item_id(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()[:16]


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Whole-word match; a trailing ``*`` makes the keyword a stem ("corporat*")."""
    stem = keyword.endswith("*")
    body = re.escape(keyword.rstrip("*").lower())
    return re.compile(rf"(?<![a-z0-9]){body}" + ("" if stem else r"(?![a-z0-9])"))


def assign_topics(text: str, topics: list[reference_data.NewsTopic]) -> list[str]:
    lowered = text.lower()
    return [t.key for t in topics if any(_keyword_pattern(k).search(lowered) for k in t.keywords)]


def dedupe(items: list[NewsItem]) -> list[NewsItem]:
    """Keep the first of any items sharing a URL or a title (case/punctuation-insensitive)."""
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    kept: list[NewsItem] = []
    for item in items:
        url_key = normalize_url(item.url)
        title_key = normalize_title(item.title)
        if url_key in seen_urls or (title_key and title_key in seen_titles):
            continue
        seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        kept.append(item)
    return kept


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def parse_us_date(text: str) -> str:
    """'Oct. 7, 2026' / 'October 7, 2026' / 'Sept. 30, 2026' -> '2026-10-07', else ''."""
    match = re.search(r"([A-Z][a-z]{2,8})\.?[ \t]+(\d{1,2}),[ \t]*(\d{4})", text or "")
    if not match:
        return ""
    month = _MONTHS.get(match.group(1)[:3].lower())
    if not month:
        return ""
    try:
        return date(int(match.group(3)), month, int(match.group(2))).isoformat()
    except ValueError:
        return ""


# ------------------------------------------------------------- providers


class IrsNewsroomProvider:
    """The IRS monthly news-release listing pages.

    Each release is a teaser heading linking to the release, followed by an
    abstract that begins "IR-2026-120, Oct. 7, 2026 — <the agency's own summary>".
    """

    def urls(self, source: NewsSourceConfig, today: date) -> list[str]:
        prev = date(today.year - 1, 12, 1) if today.month == 1 else date(today.year, today.month - 1, 1)
        names = ["january", "february", "march", "april", "may", "june", "july", "august",
                 "september", "october", "november", "december"]
        return [
            u.replace("{prev_month_name}", names[prev.month - 1]).replace("{prev_month_year}", str(prev.year))
            for u in source.urls
        ]

    def fetch(self, source: NewsSourceConfig, get: Fetch, today: date) -> list[NewsItem]:
        items: list[NewsItem] = []
        errors = 0
        urls = self.urls(source, today)
        for url in urls:
            try:
                response = get(url)
            except httpx.HTTPError:
                errors += 1
                continue
            if response.status_code != 200:
                errors += 1  # the prior month page may not exist yet early in a month
                continue
            items.extend(self.parse(response.text, url, source))
        if errors == len(urls):
            raise RuntimeError("no IRS news page could be read")
        return items

    @staticmethod
    def parse(html: str, base_url: str, source: NewsSourceConfig) -> list[NewsItem]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        items: list[NewsItem] = []
        for teaser in soup.select("div.field_pup_media_document_teaser"):
            link = teaser.find("a", href=True)
            if not link:
                continue
            title = link.get_text(" ", strip=True)
            url = urljoin(base_url, str(link.get("href") or ""))
            abstract_node = teaser.find_next("div", class_="field--name-field-pup-description-abstract")
            abstract = abstract_node.get_text(" ", strip=True) if abstract_node else ""
            reference = ""
            ref = re.match(r"(IR-\d{4}-\d+)", abstract)
            if ref:
                reference = ref.group(1)
            published = parse_us_date(abstract[:60])
            summary = re.sub(r"^IR-\d{4}-\d+,[^—–-]*[—–-][ \t]*", "", abstract)
            items.append(NewsItem(
                id=item_id(url), source=source.key, source_name=source.name, title=title, url=url,
                published=published, excerpt=excerpt(summary), reference=reference,
            ))
        return items


class TreasuryJsonProvider:
    """The press-release data the Treasury site's own news widget loads."""

    def fetch(self, source: NewsSourceConfig, get: Fetch, today: date) -> list[NewsItem]:
        response = get(source.urls[0])
        response.raise_for_status()
        return self.parse(response.json(), source)

    @staticmethod
    def parse(payload: dict[str, Any], source: NewsSourceConfig) -> list[NewsItem]:
        items: list[NewsItem] = []
        for bucket in ("homepagePressReleases", "rightRail"):
            for entry in payload.get(bucket, []) or []:
                if not isinstance(entry, dict):
                    continue
                if entry.get("categorySlug") not in (None, "press-releases", "statements-remarks"):
                    continue
                title = str(entry.get("title") or "").strip()
                link = str(entry.get("url") or "").strip()
                if not title or not link:
                    continue
                url = urljoin("https://home.treasury.gov/", link)
                published = str(entry.get("date") or "")[:10]
                items.append(NewsItem(
                    id=item_id(url), source=source.key, source_name=source.name, title=title, url=url,
                    published=published if re.match(r"\d{4}-\d{2}-\d{2}$", published) else "",
                    excerpt=excerpt(str(entry.get("description") or "")),
                ))
        return items


class LicensedApiProvider:
    """A licensed news API, reached only with the owner's credentials.

    The response mapping is deliberately minimal - headline, date, link - and
    expects ``{"items": [{"title", "url", "published"}]}``. Each vendor's real
    API differs; adapt ``parse`` to the vendor's documented schema when the
    licence is in place. No excerpt is taken from a licensed source: that is
    the publisher's content and the licence decides what may be shown.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def configured(self, source: NewsSourceConfig) -> bool:
        return all(getattr(self._settings, name, "") for name in source.requires_settings)

    def fetch(self, source: NewsSourceConfig, get: Fetch, today: date) -> list[NewsItem]:
        if not self.configured(source):
            raise ProviderUnavailable(source.connect_message)
        url_setting, key_setting = source.requires_settings[0], source.requires_settings[1]
        # SECURITY: the key goes in a header to the configured endpoint only and is never logged.
        response = get(getattr(self._settings, url_setting),
                       headers={"Authorization": f"Bearer {getattr(self._settings, key_setting)}"})
        response.raise_for_status()
        return self.parse(response.json(), source)

    @staticmethod
    def parse(payload: Any, source: NewsSourceConfig) -> list[NewsItem]:
        items: list[NewsItem] = []
        for entry in (payload or {}).get("items", []) if isinstance(payload, dict) else []:
            title, url = str(entry.get("title") or ""), str(entry.get("url") or "")
            if not title or not url.startswith("https://"):
                continue
            items.append(NewsItem(
                id=item_id(url), source=source.key, source_name=source.name, title=title, url=url,
                published=str(entry.get("published") or "")[:10], excerpt="",
            ))
        return items


# --------------------------------------------------------------- service


@dataclass
class _SourceCache:
    items: list[NewsItem] = field(default_factory=list)
    last_success: datetime | None = None
    last_attempt: float = 0.0
    state: str = "pending"
    message: str = ""


class NewsService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        fetch: Fetch | None = None,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
    ) -> None:
        self._settings = settings or get_settings()
        self._fetch = fetch or self._http_get
        self._clock = clock
        self._today = today
        self._cache: dict[str, _SourceCache] = {}
        self._lock = threading.Lock()
        self._refreshing = threading.Lock()
        self._providers: dict[str, NewsProvider] = {
            "irs_newsroom": IrsNewsroomProvider(),
            "treasury_json": TreasuryJsonProvider(),
            "licensed_api": LicensedApiProvider(self._settings),
        }

    # -- fetching

    def _http_get(self, url: str, headers: dict[str, str] | None = None) -> httpx.Response:
        with httpx.Client(timeout=_TIMEOUT, verify=httpx_verify(self._settings), follow_redirects=True,
                          headers={"User-Agent": self._settings.outbound_user_agent}) as client:
            response = client.get(url, headers=headers or {})
            if len(response.content) > _MAX_BYTES:
                raise httpx.HTTPError("response too large")
            return response

    def _guarded_get(self, provider_key: str) -> Fetch:
        allowed = _ALLOWED_HOSTS.get(provider_key)

        def get(url: str, headers: dict[str, str] | None = None) -> httpx.Response:
            # SECURITY: public providers fetch only from their agency's host.
            if allowed is not None and urlparse(url).hostname not in allowed:
                raise httpx.HTTPError(f"host not allowed for {provider_key}")
            return self._fetch(url, headers)

        return get

    def refresh_source(self, source: NewsSourceConfig, *, force: bool = False) -> None:
        cache = self._cache.setdefault(source.key, _SourceCache())
        now = self._clock()
        if not force and cache.last_attempt and now - cache.last_attempt < self._settings.news_min_fetch_interval_seconds:
            return
        cache.last_attempt = now
        provider = self._providers[source.provider]
        try:
            items = provider.fetch(source, self._guarded_get(source.provider), self._today())
        except ProviderUnavailable as exc:
            cache.state, cache.message, cache.items = "not_connected", str(exc), []
            return
        except Exception as exc:  # noqa: BLE001 - one source failing must not break the feed
            # Class name only: an exception message can echo a URL with a key in it.
            logger.warning("News source %s failed (%s)", source.key, type(exc).__name__)
            cache.state = "error"
            cache.message = "This source could not be reached; showing the last items fetched, if any."
            return
        topics = reference_data.news_sources().topics
        for item in items:
            item.topics = assign_topics(f"{item.title} {item.excerpt}", topics)
        with self._lock:
            cache.items = dedupe(items)
            cache.last_success = datetime.now(UTC)
            cache.state, cache.message = "ok", ""
        logger.info("News source %s refreshed: %d item(s)", source.key, len(cache.items))

    def refresh_all(self, *, force: bool = False) -> None:
        if not self._refreshing.acquire(blocking=False):
            return  # a refresh is already running
        try:
            for source in reference_data.news_sources().sources:
                if self._settings.news_enabled or source.kind == "licensed":
                    self.refresh_source(source, force=force)
        finally:
            self._refreshing.release()

    def refresh_in_background(self) -> None:
        threading.Thread(target=self.refresh_all, name="news-refresh", daemon=True).start()

    def is_stale(self) -> bool:
        if not self._cache:
            return True
        oldest = min((c.last_attempt for c in self._cache.values()), default=0.0)
        return self._clock() - oldest > self._settings.news_refresh_seconds

    # -- reading

    def statuses(self) -> list[SourceStatus]:
        out: list[SourceStatus] = []
        for source in reference_data.news_sources().sources:
            cache = self._cache.get(source.key)
            if source.kind == "public" and not self._settings.news_enabled:
                state, message = "disabled", "Fetching is turned off (NEWS_ENABLED=false). Visit the source directly."
            elif cache is None:
                state, message = "pending", "Not fetched yet."
            else:
                state, message = cache.state, cache.message
            out.append(SourceStatus(
                key=source.key, name=source.name, kind=source.kind, homepage=str(source.homepage),
                state=state, message=message,
                last_updated=cache.last_success.isoformat() if cache and cache.last_success else None,
                item_count=len(cache.items) if cache else 0,
            ))
        return out

    def items(
        self,
        *,
        source: str | None = None,
        topic: str | None = None,
        start: date | None = None,
        end: date | None = None,
        limit: int = 100,
    ) -> list[NewsItem]:
        with self._lock:
            pool = [item for cache in self._cache.values() for item in cache.items]
        pool.sort(key=lambda i: (i.published or "0000-00-00"), reverse=True)
        pool = dedupe(pool)
        if source:
            pool = [i for i in pool if i.source == source]
        if topic:
            pool = [i for i in pool if topic in i.topics]
        if start:
            pool = [i for i in pool if i.published and i.published >= start.isoformat()]
        if end:
            pool = [i for i in pool if i.published and i.published <= end.isoformat()]
        return pool[:limit]

    def find(self, item_id_: str) -> NewsItem | None:
        with self._lock:
            for cache in self._cache.values():
                for item in cache.items:
                    if item.id == item_id_:
                        return item
        return None


_service: NewsService | None = None


def get_news_service() -> NewsService:
    global _service
    if _service is None:
        _service = NewsService()
    return _service


def reset_news_service(service: NewsService | None = None) -> None:
    global _service
    _service = service


class BackgroundRefresher:
    """Refreshes the feed every ``news_refresh_seconds`` for the life of the process."""

    def __init__(self, service: NewsService, interval: float) -> None:
        self._service = service
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="news-background", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._service.refresh_all()
            except Exception as exc:  # noqa: BLE001
                logger.warning("News background refresh failed (%s)", type(exc).__name__)
            self._stop.wait(self._interval)
