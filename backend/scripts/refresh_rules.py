"""Propose updates to the depreciation rule data for human review.

    cd backend
    python -m scripts.refresh_rules --year 2027                 # federal figures for 2027
    python -m scripts.refresh_rules --year 2026 --states CA,NY  # also these states' conformity
    python -m scripts.refresh_rules --year 2027 --dry-run       # list the checks, call nothing

SECURITY/correctness - what this script will never do:

* **Overwrite rule data.** It writes a proposal report to
  ``docs/tax-research/rule-proposals/`` and nothing else. A person reads each
  flagged item against its cited source, edits the rule file (or the research
  rows and overrides for states), runs ``scripts.build_depreciation_rules``
  and the tests. The calculator's figures change only through that path.
* **Trust a figure without a source.** Each proposal records only the URLs
  Google Search grounding returned for that call; the model's own text never
  supplies a citation. A proposal with no grounding is marked
  ``ungrounded`` and must not be applied.
* **Send anything but the question.** Prompts hold the rule being checked and
  the current value; no client data exists in this script. Calls go through
  ``GeminiService``, so the egress guard, retries and metering apply.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

OUT_DIR = ROOT / "docs" / "tax-research" / "rule-proposals"

SYSTEM = (
    "You check one US tax rule value for a depreciation calculator. Search the web and rely only on "
    "primary sources: irs.gov (Revenue Procedures, Notices, form instructions, publications), the "
    "Internal Revenue Code, or the state's own revenue agency and legislature. Reply with ONE JSON "
    "object and nothing else, with keys: value (the figure or rule, or null if not yet published), "
    "tax_year (int), effective_note (string), source_citation (string naming the document), "
    "confidence ('high' if read in a primary source, otherwise 'low'). Never guess a figure that is "
    "not yet published; return null instead."
)


@dataclass
class Check:
    key: str
    question: str
    current: Any
    proposal: Any = None
    sources: list[dict[str, str]] = field(default_factory=list)
    status: str = "pending"  # same | changed | new | ungrounded | unparsed | not_published | error
    note: str = ""


def federal_checks(year: int, rules: Any) -> list[Check]:
    federal = rules.federal
    current_179 = federal["section_179"].get(str(year))
    current_caps = federal["luxury_auto_caps"].get(str(year))
    return [
        Check(
            f"section_179.{year}",
            f"For tax years beginning in {year}, what are the IRC section 179 maximum deduction "
            "(179(b)(1)), the phase-out threshold (179(b)(2)) and the SUV limit (179(b)(5)(A))? "
            "Give value as {\"limit\": int, \"phaseout_threshold\": int, \"suv_cap\": int}.",
            None if current_179 is None else {k: current_179[k] for k in ("limit", "phaseout_threshold", "suv_cap")},
        ),
        Check(
            f"luxury_auto_caps.{year}",
            f"What are the IRC section 280F depreciation limits for passenger automobiles placed in service in "
            f"calendar year {year}, with and without the section 168(k) allowance? Give value as "
            "{\"with_bonus\": [y1, y2, y3, later], \"without_bonus\": [y1, y2, y3, later]}.",
            None if current_caps is None else {k: current_caps[k] for k in ("with_bonus", "without_bonus")},
        ),
        Check(
            f"bonus.{year}",
            f"What is the IRC section 168(k) special depreciation allowance percentage for qualified property "
            f"placed in service in {year}, (a) acquired after January 19, 2025 and (b) acquired after "
            "September 27, 2017 and before January 20, 2025? Has any law enacted after July 4, 2025 changed it? "
            "Give value as {\"acquired_after_2025_01_19\": int, \"acquired_before_2025_01_20\": int}.",
            _current_bonus(year, rules),
        ),
        Check(
            f"qualified_production_property.{year}",
            "Has the IRC section 168(n) qualified production property allowance (construction beginning after "
            "Jan. 19, 2025 and before Jan. 1, 2029; placed in service after July 4, 2025 and before Jan. 1, 2031) "
            "been amended, extended or clarified by final regulations? Give value as "
            "{\"rate\": int, \"construction_begins_before\": \"YYYY-MM-DD\", \"placed_in_service_before\": \"YYYY-MM-DD\"}.",
            {k: federal["qualified_production_property"][k]
             for k in ("rate", "construction_begins_before", "placed_in_service_before")},
        ),
    ]


def _current_bonus(year: int, rules: Any) -> dict[str, Any]:
    after = rules.bonus_rate(date(2025, 6, 1), date(year, 6, 1))[0]
    before = rules.bonus_rate(date(2024, 6, 1), date(year, 6, 1))[0]
    return {"acquired_after_2025_01_19": int(after), "acquired_before_2025_01_20": int(before)}


def state_checks(year: int, codes: list[str], rules: Any) -> list[Check]:
    checks = []
    for code in codes:
        state = rules.state(code)
        if state is None:
            raise SystemExit(f"{code} is not on the calculator's allow-list")
        entry = state["years"].get(str(year), {})
        checks.append(Check(
            f"state.{code}.{year}",
            f"For {state['name']} personal income tax, tax years beginning in {year}: does the state follow federal "
            "IRC 168(k) bonus depreciation (full / none / partial, and how a disallowed amount is added back and "
            "recovered), the federal section 179 limits or its own, and IRC 168(n)? Did it change any of these in "
            f"{year} or {year - 1}? Use only {state['agency']} ({state['agency_url']}) or the state legislature. "
            "Give value as {\"bonus\": str, \"section_179\": str, \"decouples_168n\": bool|null, \"changed\": str}.",
            {"bonus": entry.get("bonus"), "section_179": entry.get("section_179"),
             "decouples_168n": entry.get("decouples_168n"), "status": entry.get("status")},
        ))
    return checks


def run_check(check: Check, gemini: Any, settings: Any) -> None:
    from app.models.enums import TaskKind
    from app.services.gemini_service import parse_json_response

    prompt = f"{check.question}\n\nThe calculator currently holds: {json.dumps(check.current)}"
    try:
        response = gemini.generate(
            prompt=prompt, task=TaskKind.CHAT_COMPLEX, system_instruction=SYSTEM,
            context="depreciation_rule_refresh", google_search=True,
            model=settings.assistant_model, temperature=0.0,
        )
    except Exception as exc:  # noqa: BLE001 - recorded in the report, never applied
        check.status, check.note = "error", f"{type(exc).__name__}: {exc}"
        return
    check.sources = [{"title": s.title, "url": s.url} for s in response.grounding.sources]
    try:
        data = parse_json_response(response.text or "")
    except Exception:  # noqa: BLE001
        data = {}
    if not data:
        check.status, check.note = "unparsed", (response.text or "")[:2000]
        return
    check.proposal = data
    check.note = f"{data.get('source_citation', '')} - {data.get('effective_note', '')} (confidence: {data.get('confidence')})"
    if not check.sources:
        check.status = "ungrounded"
    elif data.get("value") is None:
        check.status = "not_published"
    elif check.current is None:
        check.status = "new"
    else:
        check.status = "same" if _same(data.get("value"), check.current) else "changed"


def _same(proposed: Any, current: Any) -> bool:
    if isinstance(proposed, dict) and isinstance(current, dict):
        return all(_same(proposed.get(k), v) for k, v in current.items() if k in proposed)
    if isinstance(proposed, list) and isinstance(current, list):
        return [int(x) for x in proposed] == [int(x) for x in current]
    try:
        return float(proposed) == float(current)
    except (TypeError, ValueError):
        return str(proposed).strip().lower() == str(current).strip().lower()


def write_report(year: int, checks: list[Check]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).date().isoformat()
    base = OUT_DIR / f"refresh-{year}-{stamp}"
    base.with_suffix(".json").write_text(json.dumps([asdict(c) for c in checks], indent=1), encoding="utf-8")
    flagged = [c for c in checks if c.status not in ("same",)]
    lines = [
        f"# Depreciation rule refresh - {year} (run {stamp})",
        "",
        (
            "Proposals only. **Nothing here has been applied.** For each flagged item: open the cited source, "
            "confirm the figure, then edit `backend/app/tax_rules/depreciation/federal_rules.json` (federal) or "
            "the state research rows / `state_conformity_overrides.json` (states), run "
            "`python -m scripts.build_depreciation_rules` and the depreciation tests."
        ),
        "",
        f"{len(checks)} checks; {len(flagged)} need review.",
        "",
        "| Check | Status | Current | Proposed | Note | Sources (from grounding) |",
        "|---|---|---|---|---|---|",
    ]
    for c in checks:
        sources = "<br>".join(f"[{s['title'] or s['url']}]({s['url']})" for s in c.sources) or "none"
        proposed = json.dumps((c.proposal or {}).get("value")) if c.proposal else ""
        lines.append(f"| `{c.key}` | **{c.status}** | `{json.dumps(c.current)}` | `{proposed}` | "
                     f"{c.note.replace('|', '/')[:300]} | {sources} |")
    base.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return base.with_suffix(".md")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, required=True, help="tax year to check")
    parser.add_argument("--states", default="", help="comma-separated state codes, or ALL")
    parser.add_argument("--dry-run", action="store_true", help="list the checks without calling the model")
    args = parser.parse_args(argv)

    from app.services.depreciation.rules import DepreciationRules

    rules = DepreciationRules()
    checks = federal_checks(args.year, rules)
    codes = list(rules.state_codes) if args.states.upper() == "ALL" else [c.strip().upper() for c in args.states.split(",") if c.strip()]
    checks += state_checks(args.year, codes, rules)

    if args.dry_run:
        for check in checks:
            print(f"{check.key}: current={json.dumps(check.current)}")
        return 0

    from app.core.audit import AuditLogger
    from app.core.config import get_settings
    from app.core.db import init_database, session_scope
    from app.services.gemini_service import GeminiService
    from app.services.llm_egress_guard import EgressGuard

    settings = get_settings()
    init_database()
    with session_scope() as session:
        audit = AuditLogger(session)
        gemini = GeminiService(guard=EgressGuard(audit=audit), audit=audit)
        if not gemini.enabled:
            print("Gemini is not configured (GEMINI_API_KEY); nothing was checked.", file=sys.stderr)
            return 2
        for check in checks:
            run_check(check, gemini, settings)
            print(f"{check.key}: {check.status}")
    report = write_report(args.year, checks)
    print(f"Report: {report} (nothing was applied)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
