"""Propose State Intelligence updates for human review. Never applies them.

    cd backend
    python -m scripts.refresh_state_intel --year 2026 --states CA,NY        # these states, all sections
    python -m scripts.refresh_state_intel --year 2026 --states ALL --sections rates,nexus
    python -m scripts.refresh_state_intel --year 2027 --states CA --dry-run # list the questions only

For each state and section it asks Gemini, with Google Search grounding, for
the current rule from the state's own revenue agency or legislature, and puts
the answer next to what ``reference_data/state_intel/states/<CODE>.json``
holds for that year. The report lands in
``docs/tax-research/state-intel-proposals/``.

What it will never do (the same contract as ``scripts.refresh_rules``):

* **Write the data files.** A person opens each cited source, confirms the
  rule, edits the state's JSON (adding the year to ``years`` or adding a new
  field with ``source_url``, ``source_citation`` and ``last_verified``), and
  runs ``pytest tests/test_state_intel.py``.
* **Trust a claim without grounding.** Sources come only from the grounding
  metadata; a proposal with none is marked ``ungrounded``.
* **Send client data.** Prompts hold the state, year, section and the current
  public text; calls go through ``GeminiService`` and its egress guard.

Federal Conformity is not asked here: it is the depreciation calculator's
table, refreshed by ``scripts.refresh_rules --states``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

OUT_DIR = ROOT / "docs" / "tax-research" / "state-intel-proposals"

SYSTEM = (
    "You check one section of a US state tax reference page for tax associates. Search the web and rely "
    "only on the state's own revenue agency site or legislature (statutes, regulations, official "
    "publications, form instructions). Reply with ONE JSON object and nothing else, with keys: "
    "fields (a list of {key, label, value, source_citation}), changed_from_current (bool), "
    "change_summary (string), confidence ('high' only if read in a primary source, else 'low'). "
    "State every figure with the tax year it applies to. Never guess a figure that is not published; "
    "omit the field instead. Write values in plain English, at most three sentences each."
)

QUESTIONS = {
    "apportionment": (
        "How does {name} apportion multistate business income for tax year {year}: the formula "
        "(single sales factor, three-factor, other), how sales of services and intangibles are sourced "
        "(market-based or cost of performance), special industry rules, and the apportionment form? "
        "Use keys: method, sourcing, special_industries, forms."
    ),
    "nexus": (
        "For {name}, tax year {year}: income/franchise tax nexus standards (physical presence, any "
        "economic nexus threshold with amounts), sales tax economic nexus threshold, the state's "
        "treatment of P.L. 86-272, and notable state positions. Use keys: income_economic_nexus, "
        "sales_economic_nexus, pl_86_272, notable_positions."
    ),
    "rates": (
        "For {name}, tax year {year}: individual income tax rates (or none), corporate income or "
        "franchise tax rate(s) and minimums, state sales and use tax rate and how local rates apply, "
        "and other notable business taxes. Use keys: individual, corporate, sales, other_business."
    ),
    "filing": (
        "For {name}, tax year {year}: who must file, original due dates and extension rules for "
        "individuals, C corporations, S corporations and partnerships, composite returns, any "
        "pass-through entity tax (PTET) election and its deadline, withholding and estimated payment "
        "rules, and the key forms. Use keys: individual_due, business_due, composite, ptet, "
        "estimates, key_forms."
    ),
}


@dataclass
class Proposal:
    key: str
    state: str
    section: str
    question: str
    current: list[dict[str, Any]]
    proposal: dict[str, Any] | None = None
    sources: list[dict[str, str]] = field(default_factory=list)
    status: str = "pending"  # same | review | new | ungrounded | unparsed | error
    note: str = ""


def build(year: int, codes: list[str], sections: list[str]) -> list[Proposal]:
    from app.services import reference_data
    from app.services.assistant import state_registry

    proposals = []
    for code in codes:
        data = reference_data.state_intel(code)
        if data is None:
            raise SystemExit(f"{code} has no State Intelligence file")
        jurisdiction = state_registry.get(code)
        agency = f"{jurisdiction.agency.name} ({jurisdiction.agency.url})" if jurisdiction else "the state agency"
        for section in sections:
            current = [
                {"key": f.key, "value": f.value, "source_citation": f.source_citation}
                for f in data.sections[section].fields if year in f.years
            ]
            question = QUESTIONS[section].format(name=data.name, year=year) + f" Prefer {agency}."
            proposals.append(Proposal(f"{code}.{section}.{year}", code, section, question, current))
    return proposals


def run(proposal: Proposal, gemini: Any, settings: Any) -> None:
    from app.models.enums import TaskKind
    from app.services.gemini_service import parse_json_response
    from app.services.llm_egress_guard import redact_blocking_patterns

    prompt = (
        f"{proposal.question}\n\nThe reference page currently holds (public text): "
        f"{redact_blocking_patterns(json.dumps(proposal.current))}"
    )
    try:
        response = gemini.generate(
            prompt=prompt, task=TaskKind.CHAT_COMPLEX, system_instruction=SYSTEM,
            context="state_intel_refresh", google_search=True,
            model=settings.assistant_model, temperature=0.0,
        )
    except Exception as exc:  # noqa: BLE001 - recorded in the report, never applied
        proposal.status, proposal.note = "error", type(exc).__name__
        return
    proposal.sources = [{"title": s.title, "url": s.url} for s in response.grounding.sources]
    try:
        data = parse_json_response(response.text or "")
    except Exception:  # noqa: BLE001
        data = {}
    if not data:
        proposal.status, proposal.note = "unparsed", (response.text or "")[:1500]
        return
    proposal.proposal = data
    proposal.note = f"{data.get('change_summary', '')} (confidence: {data.get('confidence')})"
    if not proposal.sources:
        proposal.status = "ungrounded"
    elif not proposal.current:
        proposal.status = "new"
    elif data.get("changed_from_current"):
        proposal.status = "review"
    else:
        proposal.status = "same"


def write_report(year: int, proposals: list[Proposal]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).date().isoformat()
    base = OUT_DIR / f"state-intel-{year}-{stamp}"
    base.with_suffix(".json").write_text(json.dumps([asdict(p) for p in proposals], indent=1), encoding="utf-8")
    lines = [
        f"# State Intelligence refresh - {year} (run {stamp})",
        "",
        (
            "Proposals only. **Nothing here has been applied.** For each item marked `new` or `review`: open the "
            "cited sources, confirm the rule on the agency's own page, then edit "
            "`backend/app/reference_data/state_intel/states/<CODE>.json` (add the year to `years`, or add a field "
            "with `source_url`, `source_citation` and `last_verified`) and run `pytest tests/test_state_intel.py`. "
            "`ungrounded` items must not be applied."
        ),
        "",
        "| Item | Status | Current | Proposed | Note | Sources (from grounding) |",
        "|---|---|---|---|---|---|",
    ]
    for p in proposals:
        sources = "<br>".join(f"[{s['title'] or s['url']}]({s['url']})" for s in p.sources) or "none"
        current = "<br>".join(f"{c['key']}: {c['value']}" for c in p.current) or "(not verified)"
        proposed = "<br>".join(
            f"{f.get('key')}: {f.get('value')}" for f in ((p.proposal or {}).get("fields") or []) if isinstance(f, dict)
        )
        lines.append(f"| `{p.key}` | **{p.status}** | {current.replace('|', '/')[:600]} | "
                     f"{proposed.replace('|', '/')[:600]} | {p.note.replace('|', '/')[:300]} | {sources} |")
    base.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return base.with_suffix(".md")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--states", required=True, help="comma-separated codes, or ALL")
    parser.add_argument("--sections", default="apportionment,nexus,rates,filing")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from app.services import reference_data

    codes = (reference_data.state_intel_codes() if args.states.upper() == "ALL"
             else [c.strip().upper() for c in args.states.split(",") if c.strip()])
    sections = [s.strip() for s in args.sections.split(",") if s.strip()]
    unknown = set(sections) - set(QUESTIONS)
    if unknown:
        raise SystemExit(f"unknown section(s): {sorted(unknown)}")
    proposals = build(args.year, codes, sections)

    if args.dry_run:
        for p in proposals:
            print(f"{p.key}: {len(p.current)} verified field(s) now\n  {p.question}")
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
        for p in proposals:
            run(p, gemini, settings)
            print(f"{p.key}: {p.status}", flush=True)
    print(f"Report: {write_report(args.year, proposals)} (nothing was applied)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
