"""Read public primary sources before generating a calculation answer."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import ValidationError as AppValidationError
from app.core.tls import httpx_verify
from app.models.enums import TaskKind
from app.services.assistant import state_registry
from app.services.assistant.citations import Resolver, http_redirect_resolver
from app.services.assistant.prompt_builder import BuiltPrompt, JurisdictionContext
from app.services.gemini_service import GeminiService
from app.services.llm_egress_guard import redact_blocking_patterns
from app.services.llm_meter import MeterScope
from app.services.public_web_fetcher import FetchedSource, PageCache, PublicWebFetcher

_FEDERAL_DOMAINS = (
    "irs.gov", "treasury.gov", "ecfr.gov", "federalregister.gov",
    "uscode.house.gov", "congress.gov", "govinfo.gov",
)
_MAX_BYTES = 8 * 1024 * 1024
_MAX_REDIRECTS = 3
_MAX_PAGES = 4
_MAX_FETCHES = 6
_PAGE_CHARS = 16000


def official_url(url: str, context: JurisdictionContext) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
            return False
    except ValueError:
        return False
    host = (parsed.hostname or "").rstrip(".").lower()
    domains = (*_FEDERAL_DOMAINS, *(
        domain for code in context.required for domain in state_registry.require(code).domains
    ))
    return any(host == domain or host.endswith("." + domain) for domain in domains)


class OfficialSourceReader:
    def __init__(
        self, settings: Settings | None = None, *, transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport
        self._cache = PageCache(
            ttl_seconds=self._settings.outbound_cache_ttl_seconds,
            max_entries=_MAX_FETCHES,
        )

    def read(self, url: str, context: JurisdictionContext) -> FetchedSource | None:
        cache = self._cache
        try:
            with httpx.Client(
                timeout=httpx.Timeout(8.0, connect=3.0),
                follow_redirects=False,
                verify=httpx_verify(self._settings),
                headers={"User-Agent": self._settings.outbound_user_agent},
                transport=self._transport,
            ) as client:
                for redirect in range(_MAX_REDIRECTS + 1):
                    # SECURITY: authorize and resolve every hop, including cache hits.
                    if not official_url(url, context):
                        return None
                    PublicWebFetcher._assert_safe_url(url)
                    cached = cache.get(url)
                    if cached is not None:
                        return cached if official_url(cached.url, context) else None
                    with client.stream("GET", url) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location or redirect == _MAX_REDIRECTS:
                                return None
                            url = urljoin(url, location)
                            continue
                        response.raise_for_status()
                        content_type = response.headers.get("content-type", "").lower()
                        if not any(kind in content_type for kind in ("html", "pdf", "text/plain")):
                            return None
                        body = bytearray()
                        for chunk in response.iter_bytes():
                            body.extend(chunk)
                            if len(body) > _MAX_BYTES:
                                return None
                    source = PublicWebFetcher._build_source(
                        bytes(body), url, content_type, response.status_code, follow_links=True,
                    )
                    if not source.content.strip():
                        return None
                    cache.put(url, source)
                    return source
        except (httpx.HTTPError, AppValidationError, ValueError, RuntimeError):
            return None
        return None


@dataclass(slots=True)
class SourceEvidence:
    pages: list[FetchedSource] = field(default_factory=list)

    def prompt_text(self) -> str:
        records = [
            {
                "url": redact_blocking_patterns(page.url),
                "title": redact_blocking_patterns(page.title),
                "retrieved_at": page.fetched_at.isoformat(),
                "text": redact_blocking_patterns(page.content[:_PAGE_CHARS]),
            }
            for page in self.pages
        ]
        return json.dumps(records, ensure_ascii=True)


class SourceVerifier:
    def __init__(
        self, gemini: GeminiService, settings: Settings | None = None, *,
        reader: OfficialSourceReader | None = None, resolver: Resolver | None = None,
    ) -> None:
        self._gemini = gemini
        self._settings = settings or get_settings()
        self._reader = reader or OfficialSourceReader(self._settings)
        self._resolver = resolver or http_redirect_resolver(self._settings)

    def prepare(
        self, built: BuiltPrompt, *, year: int, question: str = "", meter_scope: MeterScope | None = None,
    ) -> SourceEvidence:
        response = self._gemini.generate(
            prompt=built.prompt,
            system_instruction=built.system,
            task=TaskKind.CHAT_COMPLEX,
            context="assistant_source_research",
            google_search=True,
            model=self._settings.assistant_model,
            temperature=0.0,
            thinking_level=self._settings.assistant_thinking_level or None,
            meter_scope=meter_scope,
        )
        redirects = [
            source.url for source in response.grounding.sources
            if urlparse(source.url).hostname == "vertexaisearch.cloud.google.com"
        ]
        resolved = self._resolver(redirects) if redirects else {}
        candidates: dict[str, str] = {}
        withholding = bool(re.search(r"\bwithhold(?:ing|held)?\b", question, re.IGNORECASE))
        for source in response.grounding.sources:
            url = resolved.get(source.url, source.url)
            if official_url(url, built.context) and (withholding or not _withholding_source(url, source.title)):
                candidates[url] = source.title
        pages: list[FetchedSource] = []
        visited: set[str] = set()
        while candidates and len(visited) < _MAX_FETCHES and len(pages) < _MAX_PAGES:
            url = max(candidates, key=lambda candidate: _priority(candidate, candidates[candidate], year))
            candidates.pop(url)
            visited.add(url)
            page = self._reader.read(url, built.context)
            if page is None:
                continue
            pages.append(page)
            for link in page.discovered_links:
                title = page.link_titles.get(link, "")
                if not withholding and _withholding_source(link, title):
                    continue
                if link not in visited and official_url(link, built.context) and _priority(link, title, year) >= 10:
                    candidates.setdefault(link, title)
        for code in built.context.required:
            domains = state_registry.require(code).domains
            if not any(
                any((urlparse(page.url).hostname or "").removeprefix("www.") == domain
                    or (urlparse(page.url).hostname or "").endswith("." + domain) for domain in domains)
                for page in pages
            ):
                return SourceEvidence()
        pages.sort(key=lambda page: _priority(page.url, page.title, year), reverse=True)
        return SourceEvidence(pages=pages)


def _withholding_source(url: str, title: str) -> bool:
    return bool(re.search(r"withhold|(?:^|[/_-])wh(?:[/_.-]|$)", url + " " + title, re.IGNORECASE))


def _priority(url: str, title: str, year: int) -> int:
    text = (url + " " + title).lower()
    score = 10 if re.search(rf"(?<!\d){year}(?!\d)", text) else 0
    if re.search(r"revis|correct|updated|(?:^|[/_.-])rev(?:[/_.-]|$)", text):
        score += 8
    if re.search(r"rate|schedule|deduction|exemption|instruction|publication", text):
        score += 4
    return score