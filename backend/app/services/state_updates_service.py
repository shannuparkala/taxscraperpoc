"""What a state's revenue agency has published recently.

The panel shows the reader what changed recently, straight from the agency,
beside the assistant's answers - "Texas raised the threshold last month" is
exactly the kind of fact worth seeing at the source.

How it works, and why in that order:

1. Fetch the agency's own newsroom or bulletins page and read its links.
2. Score those links for whether they look like a published item rather than
   site furniture, and keep the best handful.
3. Fetch *those* pages concurrently, under one deadline, and take each item's
   headline, summary and date from the item itself.

Step three is the point. The headline on a listing page is an anchor label
somebody wrote for a sidebar; it is often truncated, sometimes just "Read
more", and it carries no date. Taking the summary from the item's own page
costs a handful of parallel fetches and produces something a reader can act
on. Every item carries the URL it came from, because an update the reader
cannot open is a rumour.

SECURITY: every URL goes through ``PublicWebFetcher``, so the scheme
allow-list and the SSRF checks apply, and the host must be on the state's own
allow-listed domains. Nothing here reads client data, and nothing here is sent
to a model — this is a reading panel, not a source for an answer. Answers are
grounded through Google Search, never through this panel.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import urlparse

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.services.assistant import state_registry
from app.services.assistant.state_registry import Jurisdiction
from app.services.public_web_fetcher import PublicWebFetcher

logger = get_logger(__name__)

#: Items shown in the panel.
_MAX_ITEMS = 6
#: Candidate links considered before fetching. Wider than ``_MAX_ITEMS``
#: because some candidates turn out to be PDFs, redirects or empty pages.
_MAX_CANDIDATES = 10
#: Whole-operation ceiling. The panel is secondary to the conversation and must
#: never be the reason a page feels slow.
_DEADLINE_SECONDS = 12.0

#: Anchor labels that are navigation, not news.
_FURNITURE = re.compile(
    r"(?i)^\s*(?:read more|more|next|previous|home|contact(?: us)?|about"
    r"|search|sign in|log ?in|register|subscribe|español|espanol|back"
    r"|view all|see all|all news|news|press releases?|newsroom|media"
    r"|privacy|accessibility|site ?map|help|faq|forms?|careers?)\s*$"
)

#: Path fragments that mark a published item on an agency site.
_ITEM_PATHS = (
    "/news", "/press", "/release", "/bulletin", "/notice", "/alert",
    "/announcement", "/tax-alert", "/tip", "/publication", "/ruling",
    "/legislation", "/law-change", "/whats-new", "/media",
)

_MONTHS = (  # noqa: SIM905 - one prose line beats a twelve-element literal
    "january february march april may june july august september october "
    "november december"
).split()

_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    re.compile(
        r"\b(" + "|".join(_MONTHS) + r")\w*\.?\s+(\d{1,2}),?\s+(\d{4})\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),
)


@dataclass(slots=True)
class StateUpdate:
    """One published item."""

    headline: str
    summary: str
    url: str
    #: ISO date, when the item states one. Empty when it does not — which is
    #: honest and common, and better than showing the fetch time as if it were
    #: a publication date.
    published: str = ""
    source: str = ""


@dataclass(slots=True)
class StateUpdatesResult:
    state_code: str
    state_name: str
    agency: str
    agency_url: str
    updates_url: str
    items: list[StateUpdate]
    fetched_at: str
    #: True when these items came from the cache rather than a fresh fetch.
    from_cache: bool = False
    #: Set when nothing could be fetched. The panel shows this instead of an
    #: empty list, because "nothing published" and "we could not look" are
    #: different facts and only one of them is reassuring.
    error: str = ""


class _Cache:
    """Per-state TTL cache. An agency newsroom does not change every minute.

    In-process and bounded, like the page cache: this is a latency cache in
    front of somebody else's website, and being a guest on fifty state
    government sites means not refetching each of them per page load.
    """

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = max(ttl_seconds, 0.0)
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, StateUpdatesResult]] = {}

    def get(self, key: str) -> StateUpdatesResult | None:
        if self._ttl <= 0:
            return None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= time.monotonic():
                del self._entries[key]
                return None
            return value

    def put(self, key: str, value: StateUpdatesResult) -> None:
        if self._ttl <= 0:
            return
        with self._lock:
            self._entries[key] = (time.monotonic() + self._ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_CACHE: _Cache | None = None
_CACHE_LOCK = threading.Lock()


def _cache(settings: Settings) -> _Cache:
    global _CACHE
    with _CACHE_LOCK:
        if _CACHE is None:
            _CACHE = _Cache(settings.state_updates_cache_ttl_seconds)
        return _CACHE


class StateUpdatesService:
    """Reads a state agency's published updates."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        fetcher: PublicWebFetcher | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._fetcher = fetcher or PublicWebFetcher(self._settings)

    def for_state(self, state_code: str, *, refresh: bool = False) -> StateUpdatesResult:
        profile = state_registry.get(state_code)
        if profile is None:
            raise ValueError(f"{state_code!r} is not a state this app knows about.")

        cache = _cache(self._settings)
        if not refresh:
            cached = cache.get(profile.code)
            if cached is not None:
                return _as_cached(cached)

        result = self._fetch(profile)
        # A failed fetch is cached too, briefly by virtue of the same TTL:
        # without it, a state whose site is down is refetched on every
        # keystroke that reopens the panel.
        cache.put(profile.code, result)
        return result

    # -- internals --------------------------------------------------------

    def _fetch(self, profile: Jurisdiction) -> StateUpdatesResult:
        deadline = time.monotonic() + _DEADLINE_SECONDS
        base = _blank(profile)

        try:
            listing = self._fetcher.fetch(
                profile.updates_url, follow_links=True, use_cache=True
            )
        except Exception as exc:
            logger.info(
                "Could not read %s updates from %s (%s)",
                profile.code, profile.updates_url, type(exc).__name__,
            )
            base.error = (
                f"{profile.agency.name}'s updates page could not be reached just "
                "now. The link below still works."
            )
            return base

        candidates = self._rank(listing, profile)
        if not candidates:
            base.error = (
                f"I could not pick out individual items from {profile.agency.name}'s "
                "updates page. Open it directly to see what is new."
            )
            return base

        items: list[StateUpdate] = []
        try:
            for result in self._fetcher.fetch_many(
                [url for url, _ in candidates[:_MAX_CANDIDATES]],
                use_cache=True,
                deadline=deadline,
            ):
                if not result.ok or result.source is None:
                    continue
                page = result.source
                headline = _headline(page.title, dict(candidates).get(result.url, ""))
                if not headline:
                    continue
                items.append(
                    StateUpdate(
                        headline=headline,
                        summary=_summary(page.content, headline),
                        url=page.url,
                        published=_published(page.content),
                        source=profile.agency.name,
                    )
                )
                if len(items) >= _MAX_ITEMS:
                    break
        except Exception:
            logger.exception("Reading %s update items failed", profile.code)

        if not items:
            base.error = (
                f"{profile.agency.name} publishes updates here, but none of them "
                "could be read just now."
            )
            return base

        # Dated items first, newest first; undated ones keep the agency's own
        # ordering behind them. Sorting undated items in among dated ones would
        # imply a date they do not have.
        items.sort(key=lambda item: (item.published == "", _sort_key(item.published)))
        base.items = items[:_MAX_ITEMS]
        return base

    def _rank(self, listing: object, profile: Jurisdiction) -> list[tuple[str, str]]:
        """Candidate (url, anchor text) pairs, most item-like first."""
        allowed = set(profile.domains)
        titles: dict[str, str] = dict(getattr(listing, "link_titles", {}) or {})
        listing_url = str(getattr(listing, "url", ""))

        scored: list[tuple[float, str, str]] = []
        for url in getattr(listing, "discovered_links", []) or []:
            if url == listing_url or url == profile.updates_url:
                continue
            host = urlparse(url).netloc.lower()
            if host not in allowed:
                continue

            label = (titles.get(url) or "").strip()
            lowered = url.lower()
            path_signal = sum(1.0 for fragment in _ITEM_PATHS if fragment in lowered)

            # A furniture *label* is only disqualifying when the URL does not
            # itself look like a published item. "Read more" is the single
            # most common way an agency links its own news item, and dropping
            # those left nothing to show — which is the whole reason this
            # service reads the item page rather than trusting the label.
            if _FURNITURE.match(label) and path_signal <= 0:
                continue

            score = path_signal
            # A year in the path is a strong signal of a dated publication.
            if re.search(r"/20\d{2}(?:/|-|$)", lowered):
                score += 1.5
            # A real headline is a sentence; a nav label is a word or two.
            if 20 <= len(label) <= 220:
                score += 1.5
            elif label:
                score += 0.25
            if lowered.endswith(".pdf"):
                # Readable, but the summary comes out worse than from HTML.
                score -= 0.5
            if score <= 0:
                continue
            scored.append((score, url, label))

        scored.sort(key=lambda row: row[0], reverse=True)
        seen: set[str] = set()
        ordered: list[tuple[str, str]] = []
        for _, url, label in scored:
            if url in seen:
                continue
            seen.add(url)
            ordered.append((url, label))
        return ordered


def _blank(profile: Jurisdiction) -> StateUpdatesResult:
    return StateUpdatesResult(
        state_code=profile.code,
        state_name=profile.name,
        agency=profile.agency.name,
        agency_url=profile.agency.url,
        updates_url=profile.updates_url,
        items=[],
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def _as_cached(result: StateUpdatesResult) -> StateUpdatesResult:
    return StateUpdatesResult(
        state_code=result.state_code,
        state_name=result.state_name,
        agency=result.agency,
        agency_url=result.agency_url,
        updates_url=result.updates_url,
        items=list(result.items),
        fetched_at=result.fetched_at,
        from_cache=True,
        error=result.error,
    )


def _headline(page_title: str, anchor_label: str) -> str:
    """The item's own title, falling back to the label that linked to it.

    Agency page titles are frequently suffixed with the department name, which
    is the same on every item and tells the reader nothing.
    """
    title = (page_title or "").strip()
    title = re.split(r"\s+[|–—]\s+", title)[0].strip()
    if 8 <= len(title) <= 220:
        return title
    label = (anchor_label or "").strip()
    return label[:220] if len(label) >= 8 else title[:220]


#: Press-release furniture that precedes the actual news.
#:
#: An agency item opens with the department name, "FOR IMMEDIATE RELEASE", a
#: date, the headline again, and a datelined city. All of that is what renders
#: in the panel as the summary, so the reader sees "Texas Comptroller of
#: Public Accounts FOR IMMEDIATE RELEASE September 14, 2026 <the headline they
#: just read> (AUSTIN) —" before a single word of substance.
_RELEASE_FURNITURE = re.compile(
    r"(?i)\bfor\s+immediate\s+release\b|\bpress\s+release\b"
)

#: A dateline — "(AUSTIN) —". Everything before it on an agency release is
#: masthead, so the news starts after it.
_DATELINE = re.compile(r"\(\s*[A-Z][A-Za-z .'\-]{2,30}\s*\)\s*[\u2014\u2013-]\s*")

#: A date opening a line, left behind once the furniture above is removed.
_LEADING_DATE = re.compile(r"^[A-Z][a-z]+\s+\d{1,2},?\s+\d{4}\s*")


def _summary(content: str, headline: str = "") -> str:
    """The first couple of sentences of the item, trimmed of its masthead."""
    text = re.sub(r"\s+", " ", (content or "").strip())
    if not text:
        return ""

    dateline = _DATELINE.search(text[:600])
    if dateline:
        # Everything up to the dateline is masthead. The news starts after it.
        text = text[dateline.end() :].strip()
    else:
        # No dateline: drop the release furniture, the date it was followed
        # by, and any repeat of the headline — which the reader has already
        # read, directly above this summary.
        furniture = _RELEASE_FURNITURE.search(text[:300])
        if furniture:
            text = _LEADING_DATE.sub("", text[furniture.end() :].strip())
        if headline:
            text = text.replace(headline, " ", 1)
        # Leading side only. Stripping the trailing side too removes the final
        # full stop from every summary that reaches this branch.
        text = re.sub(r"\s+", " ", text).lstrip(" .;:-\u2013\u2014").strip()

    if not text:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", text)
    summary = ""
    for sentence in sentences:
        if len(summary) + len(sentence) > 320:
            break
        summary = f"{summary} {sentence}".strip()
        if len(summary) > 160:
            break
    return summary or text[:320]


def _published(content: str) -> str:
    """An ISO date from the item's text, or empty.

    Only the first plausible date in the first part of the page is considered:
    agency pages carry unrelated dates further down — filing deadlines, rate
    effective dates — and one of those presented as the publication date is
    worse than no date.
    """
    head = (content or "")[:600]
    today = datetime.now(UTC).date()

    for pattern in _DATE_PATTERNS:
        match = pattern.search(head)
        if not match:
            continue
        try:
            parsed = _to_date(match)
        except (ValueError, IndexError):
            continue
        # A date far in the future is a deadline, not a publication date.
        if parsed and date(2015, 1, 1) <= parsed <= today:
            return parsed.isoformat()
    return ""


def _to_date(match: re.Match[str]) -> date | None:
    groups = match.groups()
    if groups[0].isdigit() and len(groups[0]) == 4:            # 2026-03-09
        return date(int(groups[0]), int(groups[1]), int(groups[2]))
    if groups[0].isdigit():                                     # 03/09/2026
        return date(int(groups[2]), int(groups[0]), int(groups[1]))
    month = _MONTHS.index(groups[0].lower()) + 1
    return date(int(groups[2]), month, int(groups[1]))


def _sort_key(published: str) -> str:
    """Newest first for dated items; stable for undated ones."""
    if not published:
        return ""
    # Invert so a plain ascending sort puts later dates first.
    return "".join(chr(ord("9") - int(ch)) if ch.isdigit() else ch for ch in published)
