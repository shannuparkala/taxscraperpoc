"""Citations, built only from what Google Search grounding returned.

The model never writes a URL that reaches the reader. Every citation is a
``GroundingSource`` the API reported for the research call, optionally with
its Google redirect resolved one hop to the page it points at. If grounding
returned nothing there are no citations - and the validators reject the
answer.

The flow:

1. **Annotate.** Grounding supports are spans of the streamed answer. Each
   span gets ``[n]`` markers (n = the source's position in the grounding
   metadata, from 1) inserted after it - except inside a hypothetical
   example, whose invented numbers no source supports.
2. **Collect.** The markers that survive into the answer say which sources it
   actually rests on. A marker that does not name a returned source is
   dropped, never shown.
3. **Resolve and classify.** Grounding URIs are short-lived ``vertexaisearch``
   redirects whose title is just a domain. One redirect hop (headers only)
   recovers the real page URL, so a stored answer's sources still open later
   and each source's authority - IRS, statute/regulation, the state's own
   agency, court, secondary, other - can be judged from its host.
4. **Renumber.** Sources are listed strongest-authority first and the answer's
   markers are rewritten to that numbering.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.tls import httpx_verify
from app.services.assistant import state_registry
from app.services.assistant.answer_text import collapse_inner_spaces
from app.services.gemini_service import Grounding

logger = get_logger(__name__)

#: The only host a redirect is ever requested from.
_REDIRECT_HOST = "vertexaisearch.cloud.google.com"

#: Authority tiers, strongest first. The order is the display order.
AUTHORITY_LABELS: dict[str, str] = {
    "irs": "IRS",
    "statute_regulation": "Statute / regulation",
    "state_agency": "State agency",
    "court": "Court",
    "government": "Government",
    "secondary": "Professional / secondary",
    "other": "Other",
}
_RANK = {key: rank for rank, key in enumerate(AUTHORITY_LABELS)}

_STATUTE_HOSTS = (
    "ecfr.gov", "federalregister.gov", "uscode.house.gov", "law.cornell.edu",
    "govinfo.gov", "congress.gov", "treasury.gov", "home.treasury.gov",
)
_COURT_HOSTS = (
    "ustaxcourt.gov", "supremecourt.gov", "uscourts.gov", "courtlistener.com",
)
_SECONDARY_HOSTS = (
    "aicpa.org", "aicpa-cima.com", "thetaxadviser.com", "journalofaccountancy.com",
    "taxnotes.com", "bloombergtax.com", "tax.thomsonreuters.com", "taxfoundation.org",
    "kpmg.com", "pwc.com", "ey.com", "deloitte.com", "salestaxinstitute.com",
)

_STATE_BY_DOMAIN: dict[str, str] = {
    domain.removeprefix("www."): j.code
    for j in state_registry.JURISDICTIONS
    for domain in j.domains
}

#: A marker group: [3], [3, 5] or [3,5].
_MARKERS = re.compile(r"\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")
#: A run of single-number markers, possibly space-separated.
_RUN = re.compile(r"\[\d{1,2}\](?:[ \t]*\[\d{1,2}\])+")

#: Anything the model wrote that looks like a URL. Stripped from displayed
#: text: the only URLs a reader sees are the grounded citations.
URL_PATTERN = re.compile(r"\(?https?://[^\s)\]]+\)?")


@dataclass(slots=True)
class Citation:
    index: int
    title: str
    url: str
    domain: str
    authority: str
    authority_label: str
    state_code: str | None
    supporting_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "title": self.title,
            "url": self.url,
            "domain": self.domain,
            "authority": self.authority,
            "authority_label": self.authority_label,
            "state_code": self.state_code,
            "supporting_text": self.supporting_text,
        }


Resolver = Callable[[list[str]], dict[str, str]]


# ---------------------------------------------------------------------------
# 1. Annotate the research notes
# ---------------------------------------------------------------------------


def annotate(
    notes: str, grounding: Grounding, *, skip: list[tuple[int, int]] | None = None
) -> str:
    """Insert ``[n]`` after each span grounding says a source supports.

    Any ``[n]`` the model wrote itself is removed first: only grounding gets
    to say what supports what. No marker is placed inside a ``skip`` range
    (character offsets into ``notes`` once those markers are removed).
    """
    text = _MARKERS.sub("", notes)
    skip = skip or []
    insertions: dict[int, set[int]] = {}
    # A support quotes the raw stream; the body has been cleaned since. Both
    # are compared without markdown emphasis, list markers or repeated
    # spaces, and each match is mapped back to a position in the body.
    flat, where = _flatten(text)
    cursor = 0
    for support in grounding.supports:
        span = _LIST_HEAD.sub("", _flatten(_MARKERS.sub("", support.text))[0]).strip()
        if len(span) < 2:
            continue
        # Supports come in the order of the text: look from the last match on,
        # so a phrase that repeats is cited where this support is.
        found = flat.find(span, cursor)
        if found < 0:
            found = flat.find(span)
        if found < 0:
            continue
        cursor = found + 1
        start = where[found]
        end = _after_emphasis(text, where[found + len(span) - 1] + 1)
        if _at_line_start(text, end):
            continue
        if any(s <= start < e or s < end <= e for s, e in skip):
            continue
        insertions.setdefault(end, set()).update(
            i + 1 for i in support.source_indices
        )
    if not insertions:
        return text
    pieces: list[str] = []
    cursor = 0
    for position in sorted(insertions):
        pieces.append(text[cursor:position])
        pieces.append(" " + "".join(f"[{n}]" for n in sorted(insertions[position])))
        cursor = position
    pieces.append(text[cursor:])
    return "".join(pieces)


#: Markdown that changes how text looks, not what it says.
_EMPHASIS = frozenset("*_`")
#: A list marker at the start of a flattened span.
_LIST_HEAD = re.compile(r"^\s*(?:[-+]|\d+[.)])\s+")


def _flatten(text: str) -> tuple[str, list[int]]:
    """``text`` without emphasis characters and with runs of whitespace as
    one space, plus the position in ``text`` of every character kept."""
    chars: list[str] = []
    where: list[int] = []
    for position, char in enumerate(text):
        if char in _EMPHASIS:
            continue
        if char.isspace():
            if not chars or chars[-1] == " ":
                continue
            char = " "
        chars.append(char)
        where.append(position)
    return "".join(chars), where


def _after_emphasis(text: str, position: int) -> int:
    """Past a closing ``**``/``_``/backtick, so a marker never splits markup."""
    while position < len(text) and text[position] in _EMPHASIS:
        position += 1
    return position


def _at_line_start(text: str, position: int) -> bool:
    """Nothing but indentation, a list marker or emphasis before ``position``
    on its line - where a marker would start a bullet with "4Federal"."""
    line = text[text.rfind("\n", 0, position) + 1 : position]
    return re.fullmatch(r"[ \t]*(?:(?:[-*+]|\d+[.)])[ \t]*)?[*_`]*", line) is not None


# ---------------------------------------------------------------------------
# 2-4. Collect, resolve, classify, renumber
# ---------------------------------------------------------------------------


def classify(url: str, title: str = "") -> tuple[str, str | None]:
    """``(authority, state_code)`` for a source, judged from its host.

    A Google redirect hides the host, so its title - which grounding sets to
    the source's domain - is used in its place.
    """
    host = (urlparse(url).hostname or "").lower()
    if host == _REDIRECT_HOST and title and "." in title and " " not in title:
        host = title.lower()
    host = host.removeprefix("www.")

    if _host_matches(host, ("irs.gov",)):
        return "irs", None
    if _host_matches(host, _COURT_HOSTS):
        return "court", None
    if _host_matches(host, _STATUTE_HOSTS):
        return "statute_regulation", None
    for domain, code in _STATE_BY_DOMAIN.items():
        if host == domain or host.endswith("." + domain):
            return "state_agency", code
    government = host.endswith((".gov", ".us")) or ".state." in host
    # State legislatures publish the code itself - statutes.capitol.texas.gov,
    # legislature.mi.gov, leg.state.nv.us - which is primary authority.
    if government and any(
        marker in host for marker in ("legis", "statute", "capitol", "leg.", "revisor")
    ):
        return "statute_regulation", None
    if government:
        return "government", None
    if _host_matches(host, _SECONDARY_HOSTS):
        return "secondary", None
    return "other", None


def build_citations(
    grounding: Grounding,
    answer_fields: dict[str, str],
    *,
    resolver: Resolver | None = None,
) -> tuple[list[Citation], dict[int, int], dict[str, list[int]]]:
    """Citations for an answer, the marker renumbering, and per-field sources.

    ``answer_fields`` maps a field key (``"why"``, ``"considerations.2"``) to
    its text, with markers in grounding's numbering. Returns the citations
    numbered from 1 in display order, ``{old marker: new marker}``, and
    ``{field_key: [new markers]}``.
    """
    if grounding.is_empty:
        return [], {}, {}
    count = len(grounding.sources)

    used: dict[str, set[int]] = {}
    for key, value in answer_fields.items():
        numbers = {n for n in _numbers(value) if 1 <= n <= count}
        if numbers:
            used[key] = numbers

    cited = sorted({n for numbers in used.values() for n in numbers})
    # No surviving markers: every returned source is still real, and listing
    # them beats listing nothing. Per-field attribution is then unknown.
    keep = cited or list(range(1, count + 1))

    resolved: dict[str, str] = {}
    if resolver is not None:
        try:
            resolved = resolver([grounding.sources[n - 1].url for n in keep])
        except Exception as exc:  # noqa: BLE001 - resolution is a nicety
            logger.info("Grounding redirect resolution failed (%s)", type(exc).__name__)

    supporting = _supporting_text(grounding)
    drafts = []
    for number in keep:
        source = grounding.sources[number - 1]
        url = resolved.get(source.url, source.url)
        authority, state_code = classify(url, source.title)
        host = (urlparse(url).hostname or "").removeprefix("www.")
        domain = host if host != _REDIRECT_HOST else source.title
        drafts.append((number, url, authority, state_code, domain, source.title))

    drafts.sort(key=lambda d: (_RANK[d[2]], d[0]))
    renumber = {old: new for new, (old, *_rest) in enumerate(drafts, start=1)}

    citations = [
        Citation(
            index=renumber[old],
            title=_title(title, url, domain),
            url=url,
            domain=domain,
            authority=authority,
            authority_label=AUTHORITY_LABELS[authority],
            state_code=state_code,
            supporting_text=supporting.get(old, "")[:300],
        )
        for old, url, authority, state_code, domain, title in drafts
    ]
    by_field = {key: sorted(renumber[n] for n in numbers) for key, numbers in used.items()}
    return citations, renumber, by_field


def renumber_text(text: str, mapping: dict[int, int]) -> str:
    """Rewrite every marker to the display numbering.

    A marker with no mapping - one that named no returned source - is
    removed rather than shown.
    """
    def swap(match: re.Match[str]) -> str:
        numbers = []
        for part in match.group(1).split(","):
            new = mapping.get(int(part))
            if new and new not in numbers:
                numbers.append(new)
        return "".join(f"[{n}]" for n in numbers)

    swapped = _MARKERS.sub(swap, text)
    # Adjacent groups ("[10] [1]") read as one run, in order: "[1][10]".
    swapped = _RUN.sub(
        lambda m: "".join(
            f"[{n}]" for n in sorted({int(x) for x in re.findall(r"\d+", m.group())})
        ),
        swapped,
    )
    # A dropped marker leaves "claim ." behind; close the gap. Only spaces
    # between words collapse: indentation and list markers are markdown.
    return re.sub(r"[ \t]+([.,;:])", r"\1", collapse_inner_spaces(swapped)).strip()


def keep_known_markers(text: str, count: int) -> tuple[str, int]:
    """Remove any marker that names no listed source; say how many went.

    Every marker in a displayed answer must open a source in the list below
    it. ``renumber_text`` already guarantees that for markers it mapped; this
    is the last check before display, so a bug upstream shows up as a log
    line rather than as a citation chip pointing nowhere.
    """
    dropped = 0

    def check(match: re.Match[str]) -> str:
        nonlocal dropped
        kept = [n for n in (int(p) for p in match.group(1).split(",")) if 1 <= n <= count]
        dropped += len(match.group(1).split(",")) - len(kept)
        return "".join(f"[{n}]" for n in kept)

    return _MARKERS.sub(check, text), dropped


def strip_urls(text: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", URL_PATTERN.sub("", text)).strip()


def http_redirect_resolver(settings: Settings) -> Resolver:
    """Resolve grounding redirects one hop, concurrently, headers only.

    SECURITY: a request is only ever made to the grounding redirect host, so
    this cannot be steered into fetching an arbitrary URL. The target page
    itself is never requested.
    """
    timeout = settings.assistant_resolve_timeout_seconds

    def resolve(urls: list[str]) -> dict[str, str]:
        targets = [u for u in urls if (urlparse(u).hostname or "") == _REDIRECT_HOST]
        if not targets:
            return {}

        def one(url: str) -> tuple[str, str | None]:
            try:
                with (
                    httpx.Client(
                        timeout=timeout, follow_redirects=False, verify=httpx_verify(settings)
                    ) as client,
                    client.stream("GET", url) as response,
                ):
                    location = response.headers.get("location", "")
            except httpx.HTTPError as exc:
                logger.info("Could not resolve a grounding redirect (%s)", type(exc).__name__)
                return url, None
            parsed = urlparse(location)
            if parsed.scheme == "https" and parsed.hostname and not parsed.username:
                return url, location
            return url, None

        with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
            return {url: final for url, final in pool.map(one, targets) if final}

    return resolve


# ---------------------------------------------------------------------------


def _host_matches(host: str, suffixes: tuple[str, ...]) -> bool:
    return any(host == s or host.endswith("." + s) for s in suffixes)


def _numbers(text: str) -> list[int]:
    return [
        int(part)
        for match in _MARKERS.finditer(text or "")
        for part in match.group(1).split(",")
    ]


def _supporting_text(grounding: Grounding) -> dict[int, str]:
    """The first span each source supports, keyed by marker number."""
    first: dict[int, str] = {}
    for support in grounding.supports:
        span = _MARKERS.sub("", support.text).strip()
        for index in support.source_indices:
            first.setdefault(index + 1, span)
    return first


def _title(title: str, url: str, domain: str) -> str:
    """Grounding titles are usually just a domain; add the page path."""
    if title and title != domain and " " in title:
        return title
    path = urlparse(url).path.strip("/")
    if not path or (urlparse(url).hostname or "") == _REDIRECT_HOST:
        return domain or title
    tail = path.split("/")[-1].replace("-", " ").replace("_", " ")
    tail = re.sub(r"\.(html?|aspx|php|pdf)$", "", tail, flags=re.IGNORECASE)
    return f"{domain} - {tail}" if tail else domain
