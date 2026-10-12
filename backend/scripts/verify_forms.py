"""Check every form link in the IRS Forms library against the agency's server.

    cd backend
    python -m scripts.verify_forms                    # check, print a report, exit 1 on any broken link
    python -m scripts.verify_forms --update           # also record revision + last_verified in the data files
    python -m scripts.verify_forms --prior-years 2024 # also check the irs-prior link for each annual form
    python -m scripts.verify_forms --only 1040,W-2    # a subset, by form number

For each form it fetches ``pdf_url`` and requires HTTP 200, a PDF content
type and a body that starts with ``%PDF``. It then reads the first page and
extracts the revision printed on the form ("Rev. December 2024", or the
tax year in the footer of an annual form), and reports a *revision change*
when that differs from ``latest_revision`` in the data file.

What it never does: download a copy for the app to serve. The library links
to the agency's own URL so a user always gets the current revision; this
script only proves the link still works and notices when the form moved on.

Run it on a schedule (the README has the cron line) and before each filing
season. A non-zero exit means a link is broken - fix the data file, never
point the link at a mirror.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

DATA_DIR = ROOT / "backend" / "app" / "reference_data" / "forms"
FILES = ("federal_forms.json", "state_forms.json")

#: Politeness between requests to one agency. irs.gov serves these from a CDN,
#: but the state sites often do not.
DELAY_SECONDS = 0.4
TIMEOUT_SECONDS = 30.0
USER_AGENT = "TaxScraperFormsCheck/1.0 (link verification; no content is re-hosted)"

_REV_PATTERNS = (
    # "(Rev. December 2024)", "Rev. 12-2024", "(Rev. January 2026)"
    re.compile(r"\(?Rev\.?\s+((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})", re.IGNORECASE),
    re.compile(r"\(?Rev\.?\s+(\d{1,2}[-/]\d{4})", re.IGNORECASE),
)
#: Annual forms print the tax year in the footer: "Form 4562 (2025)",
#: "Schedule C (Form 1040) 2025", or in a large header box.
_YEAR_FOOTER = re.compile(r"(?:Form|Schedule)\s+[\w-]+(?:\s+\(Form\s+[\w-]+\))?\s+\(?((?:19|20)\d{2})\)?")


@dataclass
class Result:
    file: str
    form_number: str
    state: str | None
    url: str
    ok: bool
    status: int | None
    content_type: str
    revision: str | None
    previous_revision: str | None
    problem: str = ""
    #: The host answered 401/403/429 to an identified automated client. That
    #: says nothing about whether a person's browser gets the file, so it is
    #: reported separately and does not fail the run - check those by hand.
    refused: bool = False

    @property
    def revision_changed(self) -> bool:
        return bool(self.ok and self.revision and self.previous_revision and self.revision != self.previous_revision)


def extract_revision(pdf: bytes) -> str | None:
    """The revision printed on the form's first page, or None if unreadable."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf))
        text = (reader.pages[0].extract_text() or "") if reader.pages else ""
    except Exception:  # noqa: BLE001 - an unreadable PDF is reported, not fatal
        return None
    return revision_from_text(text)


def revision_from_text(text: str) -> str | None:
    text = re.sub(r"[ \t]+", " ", text)
    for pattern in _REV_PATTERNS:
        match = pattern.search(text)
        if match:
            return f"Rev. {match.group(1)}"
    years = Counter(m.group(1) for m in _YEAR_FOOTER.finditer(text))
    if years:
        return years.most_common(1)[0][0]
    return None


def check_url(client: Any, url: str) -> tuple[bool, int | None, str, bytes, str]:
    try:
        response = client.get(url, follow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        return False, None, "", b"", type(exc).__name__
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    body = response.content
    if response.status_code != 200:
        return False, response.status_code, content_type, b"", f"HTTP {response.status_code}"
    if "pdf" not in content_type and not body.startswith(b"%PDF"):
        return False, response.status_code, content_type, b"", f"not a PDF ({content_type or 'no content type'})"
    if not body.startswith(b"%PDF"):
        return False, response.status_code, content_type, b"", "body is not a PDF"
    return True, response.status_code, content_type, body, ""


REFUSED_STATUSES = frozenset({401, 403, 429})


def check_page(client: Any, url: str) -> int | None:
    """Status of the form's landing page ("Open on IRS.gov"); it must be 200 as well."""
    if not url:
        return None
    try:
        return int(client.get(url, follow_redirects=True).status_code)
    except Exception:  # noqa: BLE001
        return None


def load(name: str) -> dict[str, Any]:
    path = DATA_DIR / name
    if not path.exists():
        return {"forms": []}
    return json.loads(path.read_text(encoding="utf-8"))


def run(only: set[str], prior_years: list[int], update: bool) -> list[Result]:
    import httpx

    from app.core.tls import httpx_verify

    results: list[Result] = []
    today = datetime.now(UTC).date().isoformat()
    with httpx.Client(
        timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}, verify=httpx_verify()
    ) as client:
        for name in FILES:
            data = load(name)
            changed = False
            for form in data.get("forms", []):
                if only and form["form_number"] not in only:
                    continue
                ok, status, ctype, body, problem = check_url(client, form["pdf_url"])
                revision = extract_revision(body) if ok else None
                page_status = check_page(client, form.get("source_page_url") or "")
                if page_status != 200:
                    ok = False
                    problem = (problem + "; " if problem else "") + f"source page {page_status or 'unreachable'}"
                refused = not ok and status in REFUSED_STATUSES and page_status in (200, *REFUSED_STATUSES)
                result = Result(
                    name, form["form_number"], form.get("state"), form["pdf_url"], ok, status,
                    ctype, revision, form.get("latest_revision"), problem, refused,
                )
                results.append(result)
                print(f"{'OK ' if ok else 'BAD'} {form.get('state') or 'US'} {form['form_number']:<24} "
                      f"{revision or '-':<20} {problem}", flush=True)
                if update:
                    form["link_status"] = "ok" if ok else ("host_refused_check" if refused else "broken")
                    if ok:
                        form["last_verified"] = today
                        if revision:
                            form["latest_revision"] = revision
                    changed = True
                time.sleep(DELAY_SECONDS)

                pattern = form.get("prior_year_pdf_pattern")
                for year in prior_years if pattern else []:
                    url = pattern.format(year=year)
                    ok_p, status_p, ctype_p, _body, problem_p = check_url(client, url)
                    results.append(Result(name, f"{form['form_number']} ({year})", form.get("state"), url,
                                          ok_p, status_p, ctype_p, None, None, problem_p))
                    if not ok_p:
                        print(f"BAD prior-year {form['form_number']} {year}: {problem_p}", flush=True)
                    time.sleep(DELAY_SECONDS)
            if update and changed:
                (DATA_DIR / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return results


def report(results: list[Result]) -> str:
    broken = [r for r in results if not r.ok and not r.refused]
    refused = [r for r in results if r.refused]
    revised = [r for r in results if r.revision_changed]
    lines = [
        f"# Forms link check - {datetime.now(UTC).date().isoformat()}",
        "",
        (
            f"Checked {len(results)} link(s): {len(results) - len(broken) - len(refused)} OK, "
            f"{len(broken)} broken, {len(refused)} refused by host, {len(revised)} revision change(s)."
        ),
        "",
    ]
    if broken:
        lines += ["## Broken", "", "| Form | State | URL | Problem |", "|---|---|---|---|"]
        lines += [f"| {r.form_number} | {r.state or 'US'} | {r.url} | {r.problem} |" for r in broken]
        lines.append("")
    if refused:
        lines += ["## Host refused the automated check (verify in a browser)", "",
                  "| Form | State | URL | Problem |", "|---|---|---|---|"]
        lines += [f"| {r.form_number} | {r.state or 'US'} | {r.url} | {r.problem} |" for r in refused]
        lines.append("")
    if revised:
        lines += ["## Revision changed", "", "| Form | Was | Now |", "|---|---|---|"]
        lines += [f"| {r.form_number} | {r.previous_revision} | {r.revision} |" for r in revised]
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--update", action="store_true", help="write revision and last_verified into the data files")
    parser.add_argument("--prior-years", default="", help="comma-separated years to check irs-prior links for")
    parser.add_argument("--only", default="", help="comma-separated form numbers")
    parser.add_argument("--report", default="", help="also write the Markdown report to this path")
    args = parser.parse_args(argv)

    only = {f.strip() for f in args.only.split(",") if f.strip()}
    years = [int(y) for y in args.prior_years.split(",") if y.strip()]
    results = run(only, years, args.update)
    text = report(results)
    print()
    print(text)
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    return 1 if any(not r.ok and not r.refused for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
