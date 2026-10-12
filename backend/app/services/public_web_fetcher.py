"""Fetching public web pages safely, for the state updates panel.

This used to be the ingestion half of a crawler that fed a local retrieval
index. The assistant now grounds through Google Search, so what remains is the
part the state updates panel needs: fetch one listing page, then a handful of
item pages concurrently.

SECURITY considerations for outbound fetching:

* **Allow-listed schemes only** (``http``/``https``).
* **SSRF protection** - the resolved host must not be a private, loopback, or
  link-local address. ``_assert_safe_url`` runs on *every* URL this module
  touches, on the sequential and the concurrent path alike.
* **Size cap** while streaming, so a hostile server cannot exhaust memory.
* **Politeness** - a delay between sequential requests and a per-host cap on
  concurrent ones, because we are a guest on fifty state government sites.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import queue
import re
import socket
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.core.tls import httpx_verify

logger = get_logger(__name__)

_MAX_FETCH_BYTES = 25 * 1024 * 1024  # 25 MB
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_MAX_CONCURRENCY = 4
_PER_HOST_CONCURRENCY = 2
_CONNECT_TIMEOUT_SECONDS = 3.0
_READ_TIMEOUT_SECONDS = 8.0

#: How often the concurrent batch checks whether the caller has stopped it.
#: Small enough that early exit feels immediate, large enough to be free.
_STOP_POLL_SECONDS = 0.05
#: Grace period for the fetch worker to unwind after cancellation. The thread is
#: a daemon, so a straggler can never keep the process alive.
_STOP_JOIN_SECONDS = 0.5

#: Page furniture that adds noise to retrieval without adding meaning.
_BOILERPLATE_SELECTORS = (
    "script", "style", "nav", "header", "footer", "aside", "noscript",
    "form", "button", "iframe", "svg",
)

_BOILERPLATE_TEXT = re.compile(
    r"(?i)^\s*(?:skip to main content|an official website of the united states"
    r" government|share facebook|print|page last reviewed or updated"
    r"|subscribe to.*|follow us on.*)\s*$",
    re.MULTILINE,
)


@dataclass(slots=True)
class FetchedSource:
    url: str
    title: str
    content: str
    content_type: str
    fetched_at: datetime
    status_code: int = 200
    discovered_links: list[str] = None  # type: ignore[assignment]
    #: Discovered link -> its anchor text.
    #:
    #: The crawler ranks links by URL alone and does not need this. A listing
    #: page does: "what did this agency publish this week" is answered by the
    #: anchor text, and a bare URL list throws away the only headline the
    #: listing page carries.
    link_titles: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.discovered_links is None:
            self.discovered_links = []
        if self.link_titles is None:
            self.link_titles = {}


@dataclass(slots=True)
class FetchResult:
    """Outcome of one concurrent fetch.

    A failure is carried, not raised: one unreachable site must not abort the
    whole research phase. ``error`` holds an exception class name only — never
    response bodies, which are untrusted third-party content.
    """

    url: str
    source: FetchedSource | None = None
    error: str | None = None
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        return self.source is not None


# ---------------------------------------------------------------------------
# Page cache
# ---------------------------------------------------------------------------


class PageCache:
    """Bounded, thread-safe TTL cache of fetched pages, keyed by URL.

    Repeated and near-identical questions hit the same handful of IRS and
    Cornell pages, and refetching them is the single most wasteful part of the
    research path.

    SECURITY: this only ever holds *public* tax authority fetched from the
    crawler's domain allow-list. No masked-zone content, no raw client data, and
    nothing is written to disk. It is a latency cache, not a store of record —
    entries are keyed by the post-redirect request URL and expire on a TTL so
    the index cannot silently drift from what the IRS is currently publishing.
    """

    def __init__(self, *, ttl_seconds: float, max_entries: int) -> None:
        self._ttl = max(ttl_seconds, 0.0)
        self._max_entries = max(max_entries, 0)
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, FetchedSource]] = {}

    def get(self, url: str) -> FetchedSource | None:
        if self._ttl <= 0 or self._max_entries <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(url)
            if entry is None:
                return None
            expires_at, source = entry
            if expires_at <= now:
                del self._entries[url]
                return None
            # Refresh recency for the LRU eviction below.
            del self._entries[url]
            self._entries[url] = entry
            return source

    def put(self, url: str, source: FetchedSource) -> None:
        if self._ttl <= 0 or self._max_entries <= 0:
            return
        expires_at = time.monotonic() + self._ttl
        with self._lock:
            self._entries.pop(url, None)
            self._entries[url] = (expires_at, source)
            while len(self._entries) > self._max_entries:
                # dicts preserve insertion order, so the first key is the least
                # recently used.
                self._entries.pop(next(iter(self._entries)))

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"entries": len(self._entries), "max_entries": self._max_entries}


_PAGE_CACHE: PageCache | None = None
_PAGE_CACHE_LOCK = threading.Lock()


def get_page_cache(settings: Settings | None = None) -> PageCache:
    """Process-wide page cache. Built once from settings."""
    global _PAGE_CACHE
    with _PAGE_CACHE_LOCK:
        if _PAGE_CACHE is None:
            settings = settings or get_settings()
            _PAGE_CACHE = PageCache(
                ttl_seconds=settings.outbound_cache_ttl_seconds,
                max_entries=settings.outbound_cache_max_entries,
            )
        return _PAGE_CACHE


class _HostLimiter:
    """Caps how many requests may be in flight against a single host.

    Politeness has to survive parallelism. The sequential path expressed it as a
    delay between requests, but a delay applied to a concurrent batch just
    serialises it again — and most research URLs share one host (irs.gov), so
    that would have thrown away the entire speed-up.

    A cap on *simultaneous connections per host* is the standard crawler answer
    and the more meaningful limit: it bounds the load placed on any one site
    while still letting different hosts overlap freely. The default is below what
    a browser opens for a page.
    """

    def __init__(self, per_host: int) -> None:
        self._per_host = max(per_host, 1)
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._lock = asyncio.Lock()

    async def semaphore(self, host: str) -> asyncio.Semaphore:
        async with self._lock:
            existing = self._semaphores.get(host)
            if existing is None:
                existing = asyncio.Semaphore(self._per_host)
                self._semaphores[host] = existing
            return existing


class PublicWebFetcher:
    """Fetches and cleans public web pages."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._last_fetch = 0.0

    # ------------------------------------------------------------- safety

    @staticmethod
    def _assert_safe_url(url: str) -> None:
        """Reject unsafe fetch targets.

        SECURITY: this is SSRF protection. Without it, an operator (or an
        attacker who reaches the ingest endpoint) could point the server at
        ``http://169.254.169.254/`` and exfiltrate cloud credentials, or probe
        internal services that are not otherwise reachable.
        """
        parsed = urlparse(url)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise ValidationError(
                f"Only http and https URLs may be ingested (got '{parsed.scheme}')."
            )
        if not parsed.hostname:
            raise ValidationError("The URL has no hostname.")

        try:
            infos = socket.getaddrinfo(parsed.hostname, None)
        except socket.gaierror as exc:
            raise ValidationError(
                f"The hostname '{parsed.hostname}' could not be resolved."
            ) from exc

        for info in infos:
            address = ipaddress.ip_address(info[4][0])
            if (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_reserved
                or address.is_multicast
            ):
                logger.warning(
                    "Blocked ingestion of a non-public address for host %s",
                    parsed.hostname,
                )
                raise ValidationError(
                    "That URL resolves to a private or internal address, which "
                    "cannot be ingested."
                )

    def _respect_delay(self) -> None:
        elapsed = time.monotonic() - self._last_fetch
        remaining = self._settings.outbound_fetch_delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_fetch = time.monotonic()

    # ------------------------------------------------------------ fetching

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self._settings.outbound_user_agent,
            "Accept": "text/html,application/pdf,application/xhtml+xml,*/*",
        }

    def fetch(
        self, url: str, *, follow_links: bool = False, use_cache: bool = False
    ) -> FetchedSource:
        """Retrieve and clean a single URL.

        SECURITY: ``_assert_safe_url`` runs before anything else, including
        before the cache is consulted, so a URL that would be rejected today can
        never be served from an entry created earlier.
        """
        self._assert_safe_url(url)

        if use_cache:
            cached = get_page_cache(self._settings).get(url)
            if cached is not None:
                logger.debug("Page cache hit")
                return cached

        self._respect_delay()

        headers = self._headers()

        try:
            with httpx.Client(
                timeout=30.0,
                follow_redirects=True,
                headers=headers,
                verify=httpx_verify(self._settings),
            ) as client:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()

                    payload = bytearray()
                    for chunk in response.iter_bytes():
                        payload.extend(chunk)
                        if len(payload) > _MAX_FETCH_BYTES:
                            raise ValidationError(
                                f"Source exceeds the {_MAX_FETCH_BYTES // 1024 // 1024} MB "
                                "fetch limit."
                            )
                    body = bytes(payload)
                    final_url = str(response.url)
                    status = response.status_code
        except httpx.HTTPStatusError as exc:
            raise ValidationError(
                f"The source returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.RequestError as exc:
            raise ValidationError(
                f"The source could not be reached ({type(exc).__name__})."
            ) from exc

        source = self._build_source(
            body, final_url, content_type, status, follow_links
        )
        if use_cache:
            get_page_cache(self._settings).put(url, source)
            if source.url != url:
                get_page_cache(self._settings).put(source.url, source)
        return source

    @classmethod
    def _build_source(
        cls,
        body: bytes,
        final_url: str,
        content_type: str,
        status: int,
        follow_links: bool,
    ) -> FetchedSource:
        """Parse a downloaded body into a :class:`FetchedSource`.

        Shared by the sync and concurrent paths so both clean and classify
        content identically.
        """
        link_titles: dict[str, str] = {}
        if "pdf" in content_type or final_url.lower().endswith(".pdf"):
            title, text = cls._parse_pdf(body, final_url)
            links: list[str] = []
        else:
            title, text, links, link_titles = cls._parse_html(
                body, final_url, follow_links
            )

        return FetchedSource(
            url=final_url,
            title=title,
            content=text,
            content_type=content_type,
            fetched_at=datetime.now(UTC),
            status_code=status,
            discovered_links=links,
            link_titles=link_titles,
        )

    # -------------------------------------------------------- concurrent

    def fetch_many(
        self,
        urls: Sequence[str],
        *,
        follow_links: bool = False,
        use_cache: bool = True,
        max_concurrency: int | None = None,
        deadline: float | None = None,
        stop: threading.Event | None = None,
    ) -> Iterator[FetchResult]:
        """Fetch ``urls`` concurrently, yielding each result as it lands.

        ``deadline`` is an ``time.monotonic()`` timestamp for the whole batch.
        When it passes, outstanding fetches are cancelled and the iterator ends —
        the caller keeps whatever arrived rather than failing. ``stop`` lets the
        caller end the batch early once it has collected enough good sources.

        SECURITY: every URL still goes through ``_assert_safe_url`` inside the
        worker before any connection is opened. Parallelism changes the schedule,
        not the checks.
        """
        if not urls:
            return

        internal_stop = threading.Event()
        results: queue.Queue[FetchResult | None] = queue.Queue()

        def stopped() -> bool:
            return internal_stop.is_set() or (stop is not None and stop.is_set())

        def runner() -> None:
            try:
                asyncio.run(
                    self._fetch_all_async(
                        list(urls),
                        follow_links=follow_links,
                        use_cache=use_cache,
                        max_concurrency=(
                            max_concurrency or _MAX_CONCURRENCY
                        ),
                        deadline=deadline,
                        stopped=stopped,
                        sink=results.put,
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.error(
                    "Concurrent fetch batch failed (%s)", type(exc).__name__
                )
            finally:
                results.put(None)

        worker = threading.Thread(
            target=runner, name="research-fetch", daemon=True
        )
        worker.start()
        try:
            while True:
                item = results.get()
                if item is None:
                    break
                yield item
        finally:
            # A consumer that abandons the iterator (deadline reached, enough
            # sources, client disconnected) must not leave fetches running. The
            # watcher inside the loop cancels in-flight requests promptly, so
            # this join is short by design — the answer must not wait on it.
            internal_stop.set()
            worker.join(timeout=_STOP_JOIN_SECONDS)

    async def _fetch_all_async(
        self,
        urls: list[str],
        *,
        follow_links: bool,
        use_cache: bool,
        max_concurrency: int,
        deadline: float | None,
        stopped: Callable[[], bool],
        sink: Callable[[FetchResult], None],
    ) -> None:
        limits = httpx.Limits(
            max_connections=max_concurrency,
            max_keepalive_connections=max_concurrency,
        )
        timeout = httpx.Timeout(
            connect=_CONNECT_TIMEOUT_SECONDS,
            read=_READ_TIMEOUT_SECONDS,
            write=_READ_TIMEOUT_SECONDS,
            pool=_CONNECT_TIMEOUT_SECONDS,
        )
        semaphore = asyncio.Semaphore(max_concurrency)
        host_limiter = _HostLimiter(_PER_HOST_CONCURRENCY)
        cache = get_page_cache(self._settings) if use_cache else None

        def remaining() -> float | None:
            if deadline is None:
                return None
            return deadline - time.monotonic()

        async with httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            follow_redirects=True,
            headers=self._headers(),
            verify=httpx_verify(self._settings),
        ) as client:

            async def one(url: str) -> None:
                if stopped():
                    return
                left = remaining()
                if left is not None and left <= 0:
                    return
                try:
                    # SECURITY: SSRF check, on this path too. getaddrinfo blocks,
                    # so it runs in a thread rather than stalling the loop — but
                    # it always runs, and always before a connection is opened.
                    await asyncio.to_thread(self._assert_safe_url, url)
                except ValidationError as exc:
                    sink(FetchResult(url=url, error=type(exc).__name__))
                    return

                if cache is not None:
                    cached = cache.get(url)
                    if cached is not None:
                        sink(FetchResult(url=url, source=cached, from_cache=True))
                        return

                # Bounded globally, and bounded again per host so a batch that
                # happens to be all irs.gov stays a civil number of connections.
                per_host = await host_limiter.semaphore(
                    urlparse(url).hostname or ""
                )
                async with semaphore, per_host:
                    if stopped():
                        return
                    left = remaining()
                    if left is not None and left <= 0:
                        return
                    try:
                        source = await asyncio.wait_for(
                            self._fetch_one_async(
                                client, url, follow_links=follow_links
                            ),
                            timeout=left,
                        )
                    except TimeoutError:
                        sink(FetchResult(url=url, error="Timeout"))
                        return
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        sink(FetchResult(url=url, error=type(exc).__name__))
                        return

                if cache is not None:
                    cache.put(url, source)
                    if source.url != url:
                        cache.put(source.url, source)
                sink(FetchResult(url=url, source=source))

            tasks = [asyncio.create_task(one(url)) for url in urls]

            async def watch_stop() -> None:
                """Turn the caller's stop flag into prompt cancellation.

                Checking ``stopped()`` only between fetches would leave the
                consumer waiting on whatever is already in flight — exactly the
                stall the deadline exists to prevent.
                """
                while not stopped():
                    if all(task.done() for task in tasks):
                        return
                    await asyncio.sleep(_STOP_POLL_SECONDS)

            # The watcher returns when the batch is done or the caller stopped
            # it; the timeout covers the deadline. All three exits land here.
            watcher = asyncio.create_task(watch_stop())
            left = remaining()
            done_timeout = None if left is None else max(left, 0.0)
            try:
                await asyncio.wait_for(watcher, timeout=done_timeout)
            except (TimeoutError, asyncio.CancelledError):
                pass

            pending = [task for task in tasks if not task.done()]
            if pending:
                logger.info(
                    "Research batch ended early (deadline or enough sources); "
                    "cancelling %d outstanding fetch(es).",
                    len(pending),
                )
                for task in pending:
                    task.cancel()
            await asyncio.gather(*pending, watcher, return_exceptions=True)

    async def _fetch_one_async(
        self, client: httpx.AsyncClient, url: str, *, follow_links: bool
    ) -> FetchedSource:
        """Download and clean one URL on the concurrent path."""
        try:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()

                payload = bytearray()
                async for chunk in response.aiter_bytes():
                    payload.extend(chunk)
                    if len(payload) > _MAX_FETCH_BYTES:
                        raise ValidationError(
                            f"Source exceeds the {_MAX_FETCH_BYTES // 1024 // 1024} MB "
                            "fetch limit."
                        )
                body = bytes(payload)
                final_url = str(response.url)
                status = response.status_code
        except httpx.HTTPStatusError as exc:
            raise ValidationError(
                f"The source returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.RequestError as exc:
            raise ValidationError(
                f"The source could not be reached ({type(exc).__name__})."
            ) from exc

        # Parsing a large regulation with lxml is CPU-bound; keep it off the
        # event loop so it cannot delay the other in-flight fetches.
        return await asyncio.to_thread(
            self._build_source, body, final_url, content_type, status, follow_links
        )

    # ------------------------------------------------------------- parsing

    @staticmethod
    def _parse_html(
        body: bytes, url: str, follow_links: bool
    ) -> tuple[str, str, list[str], dict[str, str]]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(body, "lxml")

        for metadata_script in soup.find_all("script", type="application/ld+json"):
            try:
                metadata = json.loads(metadata_script.get_text())
            except (TypeError, ValueError):
                continue
            pending: list[object] = [metadata]
            while pending:
                item = pending.pop()
                if isinstance(item, dict):
                    if str(item.get("isAccessibleForFree", "")).lower() == "false":
                        raise ValidationError(
                            "This source requires licensed access and cannot be "
                            "ingested as public tax guidance."
                        )
                    pending.extend(item.values())
                elif isinstance(item, list):
                    pending.extend(item)

        for selector in _BOILERPLATE_SELECTORS:
            for element in soup.find_all(selector):
                element.decompose()

        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        heading = soup.find("h1")
        if heading and heading.get_text(strip=True):
            title = heading.get_text(strip=True)

        # Prefer the main content region; fall back to the body.
        main = (
            soup.find("main")
            or soup.find("article")
            or soup.find(attrs={"role": "main"})
            or soup.body
            or soup
        )

        # separator="\n" keeps block boundaries, which the chunker needs to
        # split on paragraphs rather than mid-sentence.
        text = main.get_text(separator="\n", strip=True)
        text = _BOILERPLATE_TEXT.sub("", text)
        text = re.sub(r"\n{3,}", "\n\n", text)

        links: list[str] = []
        link_titles: dict[str, str] = {}
        if follow_links:
            base = urlparse(url)
            for anchor in main.find_all("a", href=True):
                absolute = urljoin(url, anchor["href"])
                parsed = urlparse(absolute)
                # Stay on the same host: following off-site links from irs.gov
                # would pull in unrelated and unvetted content.
                if parsed.scheme in _ALLOWED_SCHEMES and parsed.netloc == base.netloc:
                    clean = absolute.split("#")[0]
                    links.append(clean)
                    label = anchor.get_text(" ", strip=True)
                    # Keep the longest label seen for a URL: listing pages
                    # often link the same item from a thumbnail with no text
                    # and again from the headline.
                    if label and len(label) > len(link_titles.get(clean, "")):
                        link_titles[clean] = label[:300]
            links = list(dict.fromkeys(links))

        return (title or url, text, links, link_titles)

    @staticmethod
    def _parse_pdf(body: bytes, url: str) -> tuple[str, str]:
        import io

        import fitz

        parts: list[str] = []
        title = url.rsplit("/", 1)[-1]
        try:
            with fitz.open(stream=io.BytesIO(body), filetype="pdf") as doc:
                metadata_title = (doc.metadata or {}).get("title") or ""
                if metadata_title.strip():
                    title = metadata_title.strip()
                for page in doc:
                    text = page.get_text("text")
                    if text.strip():
                        parts.append(text)
        except Exception as exc:
            logger.error("PDF parse failed for %s: %s", url, type(exc).__name__)
            raise ValidationError("The PDF source could not be parsed.") from exc

        return (title, re.sub(r"\n{3,}", "\n\n", "\n\n".join(parts)))
