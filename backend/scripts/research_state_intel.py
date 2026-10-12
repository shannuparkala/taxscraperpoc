"""Research State Intelligence for every state, keeping only what its own page shows.

    cd backend
    python -m scripts.research_state_intel --states ALL                 # research, write proposals
    python -m scripts.research_state_intel --states CA,NY --sections rates
    python -m scripts.research_state_intel --states ALL --resume        # skip states already done in this run
    python -m scripts.research_state_intel --apply                      # merge checked fields into the data files

How a field earns its place - the model proposes, the agency's page decides:

1. **Research** (Gemini + Google Search grounding, free text - the pattern the
   assistant uses, CLAUDE.md trap 35): notes on one section for one state,
   tax years 2025 and 2026, each fact with the official page it came from.
2. **Structure** (JSON schema, no tools): each field as a value, the years it
   applies to, the source URL, and two to four short *evidence phrases* -
   distinctive wording that should appear on that page. The model is never
   asked to quote: verbatim reproduction trips the provider's recitation
   filter and returns nothing.
3. **Verify** (this script, no model): fetch the named page and every page
   Google's grounding metadata returned, and accept the field only if
   - the page is on the state's own agency or legislature host
     (``allowed_host``) - another state's site or a secondary source never
     counts, whatever it says;
   - every number in the value appears on that page; and
   - at least two evidence phrases appear on it (one, if the value carries a
     figure that also matched).
   The sentence the script then quotes back (``quote``) is cut from the
   fetched page by the script itself, around the matched phrases.

Accepted fields are written with ``verification: automated_page_match`` so
the UI can label them and show the page text that matched. Hand-verified
fields (``verification`` absent or ``manual``) are never overwritten. What
fails a check stays out and the UI keeps saying "Not yet verified".
Proposals, accepted and rejected with the reason, are kept under
``docs/tax-research/state-intel-proposals/<run>/`` so a run can be audited and
resumed. No client data exists here; every call goes through
``GeminiService`` and its egress guard.

Parallel runs: give each process its own ``DATABASE_URL`` - the audit log is a
hash chain and concurrent writers to one database would corrupt it (trap 10).
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

STATES_DIR = ROOT / "backend" / "app" / "reference_data" / "state_intel" / "states"
OUT_ROOT = ROOT / "docs" / "tax-research" / "state-intel-proposals"
YEARS = (2025, 2026)
AUTOMATED = "automated_page_match"

#: The canonical fields per section. The model may only fill these keys.
SECTIONS: dict[str, dict[str, tuple[str, str]]] = {
    "apportionment": {
        "method": ("Apportionment method", "the formula used to apportion multistate business income (single sales factor, three-factor, double-weighted sales, etc.)"),
        "sourcing": ("Sales sourcing (services and intangibles)", "market-based sourcing or cost of performance for receipts from services and intangibles"),
        "special_industries": ("Special industry rules", "industries with their own apportionment formula"),
        "forms": ("Forms", "the form or schedule used to compute apportionment"),
    },
    "nexus": {
        "income_nexus": ("Income/franchise tax nexus", "what creates income or franchise tax nexus, including any economic nexus or bright-line threshold with its amounts"),
        "sales_economic_nexus": ("Sales/use tax: economic nexus", "the remote seller economic nexus threshold (sales amount and any transaction count) and measurement period"),
        "pl_86_272": ("P.L. 86-272", "the state's stated position on P.L. 86-272 protection"),
    },
    "rates": {
        "individual": ("Individual income tax", "individual income tax rate(s) or bracket rates, or that there is no individual income tax"),
        "corporate": ("Corporate income/franchise tax", "corporate income or franchise tax rate(s) and any minimum tax"),
        "sales": ("Sales and use tax", "the state sales and use tax rate and whether local jurisdictions add rates"),
        "other_business": ("Other notable business taxes", "gross receipts, franchise, margin or other notable business taxes"),
    },
    "filing": {
        "individual_due": ("Individual due date and extension", "when individual returns are due for calendar-year filers and how extensions work"),
        "business_due": ("Business due dates and extensions", "corporate and pass-through return due dates and extension rules"),
        "ptet": ("Pass-through entity tax (PTET)", "whether an elective pass-through entity tax exists, the rate and how and when to elect"),
        "composite": ("Composite returns", "composite or group nonresident returns for pass-through entities"),
        "estimates": ("Withholding and estimated payments", "estimated tax payment requirements and nonresident withholding for pass-throughs"),
        "key_forms": ("Key forms", "the main individual, corporate and pass-through return forms"),
    },
}

#: Official legislature or agency hosts whose names carry neither the state's
#: name nor its postal code as a label.
EXTRA_HOSTS: dict[str, tuple[str, ...]] = {
    "AK": ("akleg.gov",), "AZ": ("azleg.gov",), "DC": ("dccouncil.gov",), "FL": ("flsenate.gov",),
    "IL": ("ilga.gov",), "KS": ("ksrevisor.org", "ksrevisor.gov", "kslegislature.gov"), "MA": ("malegislature.gov", "mass.gov"),
    "NC": ("ncleg.gov",), "ND": ("ndlegis.gov",), "NM": ("nmlegis.gov",), "NY": ("nysenate.gov",),
    "OK": ("oklegislature.gov", "oscn.net"), "PA": ("palegis.us",), "RI": ("rilegislature.gov",),
    "SC": ("scstatehouse.gov",), "SD": ("sdlegislature.gov",), "WV": ("wvlegislature.gov",),
    "WY": ("wyoleg.gov",),
}

RESEARCH_SYSTEM = """\
You research US state tax facts for tax associates. Search the web and rely
ONLY on the state's own revenue agency website or the state legislature /
official code website - never another state's site, law or accounting firms,
Tax Foundation, Avalara, Wikipedia or news. Write concise notes. For each
topic give the fact with every figure exactly as published, which of tax
years 2025 and 2026 it applies to (say so if it changed between them), and
the full URL of the official page it is stated on. Write "not found" for a
topic you cannot support from an official page. Do not quote at length.
"""

STRUCTURE_SYSTEM = """\
Convert research notes into JSON. Use only facts in the notes that name an
official URL; drop "not found" topics. For each field give: key (one of the
allowed keys), years (subset of [2025, 2026]; two entries with the same key
if the value differs between years), value (plain English, at most two
sentences, figures exactly as in the notes), source_url (the official URL
from the notes), and evidence: two to four SHORT distinctive phrases (2 to 6
words each, e.g. "single sales factor", "6.625%", "market-based sourcing")
that the official page itself would contain. Never invent a URL.
"""

STRUCTURE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "years": {"type": "array", "items": {"type": "integer"}},
                    "value": {"type": "string"},
                    "source_url": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["key", "years", "value", "source_url", "evidence"],
            },
        },
    },
    "required": ["fields"],
}

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/128.0 Safari/537.36 TaxScraperResearch/1.0")


# ------------------------------------------------------------- checks


def allowed_host(host: str, code: str, name: str, registry_domains: tuple[str, ...]) -> bool:
    """Is ``host`` the state's own agency or legislature?"""
    host = (host or "").lower().removeprefix("www.")
    if not host:
        return False
    for domain in registry_domains:
        domain = domain.lower().removeprefix("www.")
        if host == domain or host.endswith("." + domain):
            return True
    if any(host == d or host.endswith("." + d) for d in EXTRA_HOSTS.get(code, ())):
        return True
    if not host.endswith((".gov", ".us")):
        return False
    labels = host.split(".")
    compact = name.lower().replace(" ", "")
    return code.lower() in labels or any(compact in label for label in labels)


_PUNCT = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"',
                        "–": "-", "—": "-", " ": " ", "‑": "-"})


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9%$]+(?:[.,][0-9]+)*", text.lower().translate(_PUNCT))


def numbers(text: str) -> set[str]:
    found = set()
    for raw in re.findall(r"\d[\d,]*(?:\.\d+)?", text.translate(_PUNCT)):
        value = raw.replace(",", "").rstrip(".")
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        found.add(value)
    return found


def key_numbers(value_numbers: set[str], value: str = "") -> set[str]:
    """Figures that identify a fact (rates, amounts, years) rather than a list index.

    Any percentage counts, however short ("90%" of the liability is a fact).
    """
    percents = numbers(" ".join(re.findall(r"\d[\d,]*(?:\.\d+)?[ \t]?%", value)))
    return {n for n in value_numbers if "." in n or len(n) >= 3} | percents


_MONTHS = ("January|February|March|April|May|June|July|August|September|October|November|December")
_DATE = re.compile(rf"\b(?:{_MONTHS})[ \t]+\d{{1,2}}(?:st|nd|rd|th)?\b")


def date_phrases(value: str) -> list[str]:
    """Month-and-day phrases in a value ("May 15"). Each must appear on the page as written:
    a due date is the fact most likely to be acted on, and "15" alone is on every page.
    (Once a C corporation "May 15" passed off a page that only gave April 15 for individuals.)"""
    return [re.sub(r"(?:st|nd|rd|th)$", "", m.group(0)) for m in _DATE.finditer(value)]


def date_on_page(date: str, page_text: str) -> bool:
    """"April 15" matches "April 15", "April 15th" and "April  15," - not "April 150"."""
    month, day = date.split()
    return re.search(rf"\b{month}\W+{day}(?:st|nd|rd|th)?(?!\d)", page_text, re.IGNORECASE) is not None


def phrase_positions(phrase: str, page_tokens: list[str], index: dict[str, list[int]]) -> list[int]:
    """Start positions of ``phrase`` as a contiguous token run in the page."""
    wanted = tokens(phrase)
    if not wanted:
        return []
    hits = []
    for start in index.get(wanted[0], []):
        if page_tokens[start:start + len(wanted)] == wanted:
            hits.append(start)
    return hits


def page_snippet(page_text: str, phrases: list[str], value_numbers: set[str]) -> str:
    """The page's own sentence(s) with the most matched phrases and figures."""
    sentences = re.split(r"(?<=[.;:])[ \t\r\n]+", re.sub(r"[ \t\r\n]+", " ", page_text))
    wanted = [tokens(p) for p in phrases if tokens(p)]
    best, best_score = "", 0
    for sentence in sentences:
        # A real sentence: a bare "25." matched on a number alone proves nothing to a reader.
        if not 40 <= len(sentence) <= 600:
            continue
        sentence_tokens = tokens(sentence)
        joined = " " + " ".join(sentence_tokens) + " "
        phrase_hits = sum(1 for w in wanted if " " + " ".join(w) + " " in joined)
        if not phrase_hits:
            continue
        score = 2 * phrase_hits + len(value_numbers & numbers(sentence))
        if score > best_score:
            best, best_score = sentence.strip(), score
    if not best:
        # No sentence-sized match (tables, run-on PDF text): the text around the first phrase.
        flat = re.sub(r"[ \t\r\n]+", " ", page_text)
        for phrase in phrases:
            words = [re.escape(w) for w in phrase.split() if w]
            match = re.search(r"\W+".join(words), flat, re.IGNORECASE) if words else None
            if match:
                start = max(0, match.start() - 160)
                best = ("…" if start else "") + flat[start:match.end() + 200].strip() + "…"
                break
    return best[:500]


# ------------------------------------------------------------ fetching


class PageCache:
    def __init__(self) -> None:
        import httpx

        from app.core.tls import httpx_verify

        self._client = httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True,
                                    headers={"User-Agent": BROWSER_UA, "Accept-Language": "en-US"},
                                    verify=httpx_verify())
        self._pages: dict[str, Any] = {}

    def get(self, url: str) -> dict[str, Any] | None:
        """{final, title, text, tokens, index} or None."""
        if url in self._pages:
            return self._pages[url]
        result = None
        try:
            response = self._client.get(url)
            body = response.content[: 20 * 1024 * 1024]
            if response.status_code == 200:
                ctype = response.headers.get("content-type", "").lower()
                final = str(response.url)
                if "pdf" in ctype or body[:4] == b"%PDF":
                    from pypdf import PdfReader

                    reader = PdfReader(io.BytesIO(body))
                    text = " ".join((p.extract_text() or "") for p in reader.pages[:150])
                    meta_title = reader.metadata.title if reader.metadata and reader.metadata.title else ""
                    title = str(meta_title or "") or final
                else:
                    from bs4 import BeautifulSoup

                    soup = BeautifulSoup(response.text, "html.parser")
                    for tag in soup(["script", "style", "noscript"]):
                        tag.decompose()
                    title = (soup.title.get_text(" ", strip=True) if soup.title else "") or final
                    text = soup.get_text(" ", strip=True)
                page_tokens = tokens(text)
                index: dict[str, list[int]] = {}
                for i, tok in enumerate(page_tokens):
                    index.setdefault(tok, []).append(i)
                result = {"final": final, "title": title[:200], "text": text, "tokens": page_tokens,
                          "index": index, "numbers": numbers(text)}
        except Exception:  # noqa: BLE001 - an unreadable page simply cannot verify anything
            result = None
        self._pages[url] = result
        time.sleep(0.3)  # politeness
        return result


# ------------------------------------------------------------ research


@dataclass
class Proposal:
    key: str
    years: list[int]
    value: str
    source_url: str
    evidence: list[str]
    accepted: bool = False
    reason: str = ""
    matched_url: str = ""
    matched_title: str = ""
    matched_phrases: list[str] = field(default_factory=list)
    snippet: str = ""


@dataclass
class SectionResult:
    state: str
    section: str
    notes: str = ""
    proposals: list[Proposal] = field(default_factory=list)
    grounding_urls: list[str] = field(default_factory=list)
    error: str = ""


def research_notes(gemini: Any, settings: Any, name: str, code: str, agency: str, section: str) -> tuple[str, list[str]]:
    from app.models.enums import TaskKind

    topics = "; ".join(desc for _label, desc in SECTIONS[section].values())
    prompt = (f"{name} ({code}). Official agency: {agency}. Tax years 2025 and 2026.\n"
              f"Topics: {topics}.\nStart with the {name} revenue department's own pages.")
    response = gemini.generate(
        prompt=prompt, task=TaskKind.CHAT_COMPLEX, system_instruction=RESEARCH_SYSTEM,
        context="state_intel_research", google_search=True,
        model=settings.assistant_model, temperature=0.0,
    )
    return response.text or "", [s.url for s in response.grounding.sources]


def structure(gemini: Any, settings: Any, notes: str, section: str) -> list[dict[str, Any]]:
    from app.models.enums import TaskKind
    from app.services.gemini_service import parse_json_response
    from app.services.llm_egress_guard import redact_blocking_patterns

    keys = "\n".join(f'- "{k}": {desc}' for k, (_label, desc) in SECTIONS[section].items())
    response = gemini.generate(
        # The notes quote public pages, which carry agency emails and phones (trap 36).
        prompt=f"Allowed keys:\n{keys}\n\nNOTES:\n{redact_blocking_patterns(notes)}",
        task=TaskKind.CHAT_COMPLEX, system_instruction=STRUCTURE_SYSTEM,
        context="state_intel_structure", response_json_schema=STRUCTURE_SCHEMA,
        model=settings.assistant_model, temperature=0.0,
    )
    try:
        data = parse_json_response(response.text or "")
    except Exception:  # noqa: BLE001
        data = {}
    fields = data.get("fields") if isinstance(data, dict) else None
    return fields if isinstance(fields, list) else []


def verify(result: SectionResult, raw_fields: list[dict[str, Any]], code: str, name: str,
           domains: tuple[str, ...], pages: PageCache, resolved: list[str]) -> None:
    for raw in raw_fields:
        if not isinstance(raw, dict):
            continue
        proposal = Proposal(
            key=str(raw.get("key") or ""),
            years=sorted({int(y) for y in raw.get("years") or [] if y in YEARS}),
            value=str(raw.get("value") or "").strip(),
            source_url=str(raw.get("source_url") or "").strip(),
            evidence=[str(e) for e in raw.get("evidence") or [] if str(e).strip()][:4],
        )
        result.proposals.append(proposal)
        if proposal.key not in SECTIONS[result.section]:
            proposal.reason = "unknown key"
            continue
        if not proposal.years or not proposal.value or not proposal.evidence:
            proposal.reason = "missing years, value or evidence"
            continue
        value_numbers = numbers(proposal.value)
        reasons: list[str] = []
        for url in dict.fromkeys(u for u in [proposal.source_url, *resolved] if u.startswith("http")):
            host = urlparse(url).hostname or ""
            if not allowed_host(host, code, name, domains):
                reasons.append(f"not an official {code} host: {host}")
                continue
            page = pages.get(url)
            if page is None:
                reasons.append(f"unreadable: {url}")
                continue
            if not allowed_host(urlparse(page["final"]).hostname or "", code, name, domains):
                reasons.append(f"redirected off {code}: {page['final']}")
                continue
            missing = value_numbers - page["numbers"]
            if missing:
                reasons.append(f"figures not on {host}: {sorted(missing)[:6]}")
                continue
            matched = [p for p in proposal.evidence if phrase_positions(p, page["tokens"], page["index"])]
            # Two phrases, always: a figure such as "1" or "15" is on almost any page,
            # so a figure plus one phrase proved nothing (it once accepted a sourcing
            # rule off a depreciation FAQ).
            if not matched or len(matched) < min(2, len(proposal.evidence)):
                reasons.append(f"evidence not on {host} ({len(matched)}/{len(proposal.evidence)})")
                continue
            missing_dates = [d for d in date_phrases(proposal.value) if not date_on_page(d, page["text"])]
            if missing_dates:
                reasons.append(f"dates not on {host}: {missing_dates[:4]}")
                continue
            snippet = page_snippet(page["text"], matched, value_numbers)
            key = key_numbers(value_numbers, proposal.value)
            if len(snippet) < 40 or (key and not key & numbers(snippet)):
                # The page's own sentence must carry a phrase AND the value's figure.
                reasons.append(f"figure not stated beside the evidence on {host}")
                continue
            proposal.accepted = True
            proposal.matched_url, proposal.matched_title = page["final"], page["title"]
            proposal.matched_phrases = matched
            proposal.snippet = snippet
            break
        if not proposal.accepted:
            proposal.reason = "; ".join(dict.fromkeys(reasons))[:500] or "no official page to check"


def research_state(code: str, sections: list[str], gemini: Any, settings: Any, pages: PageCache,
                   resolver: Any) -> list[SectionResult]:
    from app.services.assistant import state_registry

    jurisdiction = state_registry.require(code)
    agency = f"{jurisdiction.agency.name} ({jurisdiction.agency.url})"
    results = []
    for section in sections:
        result = SectionResult(code, section)
        try:
            notes, grounding = research_notes(gemini, settings, jurisdiction.name, code, agency, section)
            if not grounding:  # a skipped search is a coin toss (trap 37): one more try
                notes, grounding = research_notes(gemini, settings, jurisdiction.name, code, agency, section)
            result.notes = notes
            mapping = resolver(grounding) if grounding else {}
            resolved = [mapping.get(u, u) for u in grounding]
            result.grounding_urls = resolved
            raw_fields = structure(gemini, settings, notes, section) if notes.strip() else []
            verify(result, raw_fields, code, jurisdiction.name, jurisdiction.domains, pages, resolved)
        except Exception as exc:  # noqa: BLE001 - recorded, the run continues
            result.error = type(exc).__name__
        accepted = sum(p.accepted for p in result.proposals)
        print(f"  {code}.{section}: {accepted}/{len(result.proposals)} accepted"
              f"{' ERROR ' + result.error if result.error else ''}", flush=True)
        results.append(result)
    return results


# ------------------------------------------------------------ applying


def pinned_years(proposal: dict[str, Any]) -> list[int]:
    """The proposal's years, narrowed to the one tax year its matched page is for.

    A value matched on "DR0104EZ_2025.pdf" proves 2025, not 2026, whatever the
    model said. When the page's URL or title names exactly one supported year,
    only that year is kept.
    """
    where = f"{proposal.get('matched_url', '')} {proposal.get('matched_title', '')}"
    named = {y for y in YEARS if re.search(rf"(?<!\d){y}(?!\d)", where)}
    years = list(proposal["years"])
    return [y for y in years if y in named] if len(named) == 1 else years


def clean_title(title: str, url: str) -> str:
    title = re.sub(r"[ \t\r\n]+", " ", title or "").strip()
    return (title or urlparse(url).hostname or url)[:160]


def refresh_snippets(results: list[dict[str, Any]], pages: PageCache) -> None:
    """Re-cut the page text for accepted fields whose stored snippet is too thin to show."""
    for result in results:
        for p in result["proposals"]:
            if not p["accepted"] or len(p.get("snippet") or "") >= 40:
                continue
            page = pages.get(p["matched_url"])
            if page is not None:
                p["snippet"] = page_snippet(page["text"], p.get("matched_phrases") or p["evidence"], numbers(p["value"]))


def apply(run_dir: Path, today: str) -> None:
    """Merge accepted fields into the state files; hand-verified fields always win."""
    pages: PageCache | None = None
    for path in sorted(run_dir.glob("*.json")):
        results = json.loads(path.read_text(encoding="utf-8"))
        if any(p["accepted"] and len(p.get("snippet") or "") < 40 for r in results for p in r["proposals"]):
            pages = pages or PageCache()
            refresh_snippets(results, pages)
            path.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
        state_path = STATES_DIR / f"{path.stem}.json"
        data = json.loads(state_path.read_text(encoding="utf-8"))
        added = 0
        for result in results:
            if result.get("error"):
                continue  # keep whatever an earlier run established
            section = data["sections"][result["section"]]
            manual_fields = [f for f in section["fields"] if f.get("verification", "manual") == "manual"]
            manual = {(f["key"], y) for f in manual_fields for y in f["years"]}
            section["fields"] = manual_fields
            seen: set[tuple[str, int]] = set()
            for p in result["proposals"]:
                if not p["accepted"]:
                    continue
                years = sorted(y for y in pinned_years(p) if (p["key"], y) not in manual and (p["key"], y) not in seen)
                if not years or len(p.get("snippet") or "") < 40:
                    continue  # nothing a reader could check the value against
                seen.update((p["key"], y) for y in years)
                section["fields"].append({
                    "key": p["key"], "label": SECTIONS[result["section"]][p["key"]][0],
                    "value": p["value"], "years": years, "source_url": p["matched_url"],
                    "source_citation": clean_title(p["matched_title"], p["matched_url"]),
                    "last_verified": today, "verification": AUTOMATED, "quote": p["snippet"],
                })
                added += 1
            order = list(SECTIONS[result["section"]])
            section["fields"].sort(key=lambda f: (order.index(f["key"]) if f["key"] in order else 99, f["years"]))
        state_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{path.stem}: {added} field(s) applied")


def reverify(run_dir: Path, codes: list[str] | None = None) -> None:
    """Re-check every stored proposal against the current rules. Pages only; no model calls."""
    from app.services.assistant import state_registry

    pages = PageCache()
    for path in sorted(run_dir.glob("*.json")):
        if codes and path.stem not in codes:
            continue
        jurisdiction = state_registry.require(path.stem)
        results = json.loads(path.read_text(encoding="utf-8"))
        before = sum(p["accepted"] for r in results for p in r["proposals"])
        for r in results:
            raw = [{"key": p["key"], "years": p["years"], "value": p["value"], "source_url": p["source_url"],
                    "evidence": p["evidence"]} for p in r["proposals"]]
            fresh = SectionResult(r["state"], r["section"])
            verify(fresh, raw, jurisdiction.code, jurisdiction.name, jurisdiction.domains, pages, r["grounding_urls"])
            r["proposals"] = [asdict(p) for p in fresh.proposals]
        after = sum(p["accepted"] for r in results for p in r["proposals"])
        path.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{path.stem}: {before} -> {after} accepted", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--states", default="")
    parser.add_argument("--sections", default=",".join(SECTIONS))
    parser.add_argument("--resume", action="store_true", help="skip states with a result file in this run")
    parser.add_argument("--apply", action="store_true", help="merge accepted fields from the run into the data files")
    parser.add_argument("--run", default="", help="run directory name (default: today's date)")
    parser.add_argument("--reverify", action="store_true", help="re-check stored proposals under the current rules")
    args = parser.parse_args(argv)

    today = datetime.now(UTC).date().isoformat()
    run_dir = OUT_ROOT / (args.run or today)
    if args.reverify:
        reverify(run_dir, [c.strip().upper() for c in args.states.split(",") if c.strip()] or None)
        return 0
    if args.apply:
        apply(run_dir, today)
        return 0

    from app.services import reference_data

    codes = (reference_data.state_intel_codes() if args.states.upper() == "ALL"
             else [c.strip().upper() for c in args.states.split(",") if c.strip()])
    sections = [s.strip() for s in args.sections.split(",") if s.strip()]
    run_dir.mkdir(parents=True, exist_ok=True)

    from app.core.audit import AuditLogger
    from app.core.config import get_settings
    from app.core.db import init_database, session_scope
    from app.services.assistant.citations import http_redirect_resolver
    from app.services.gemini_service import GeminiService
    from app.services.llm_egress_guard import EgressGuard

    settings = get_settings()
    init_database()
    pages = PageCache()
    resolver = http_redirect_resolver(settings)
    for code in codes:
        out = run_dir / f"{code}.json"
        if args.resume and out.exists():
            continue
        print(code, flush=True)
        with session_scope() as session:  # one session per state: audit events commit as it goes
            audit = AuditLogger(session)
            gemini = GeminiService(guard=EgressGuard(audit=audit), audit=audit)
            if not gemini.enabled:
                print("Gemini is not configured (GEMINI_API_KEY); nothing was researched.", file=sys.stderr)
                return 2
            results = research_state(code, sections, gemini, settings, pages, resolver)
        out.write_text(json.dumps([asdict(r) for r in results], indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Proposals in {run_dir}. Review, then: python -m scripts.research_state_intel --apply --run {run_dir.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
