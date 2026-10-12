"""LLM spend across returns and chats, from the ``llm_calls`` ledger.

What ``/cost-report`` runs. Prints per-return averages, cost per page, the split
by stage and model, the stub and failure rates, and savings ideas ranked by how
much of the spend each one could touch. Identifies returns by workflow id only;
nothing here reads document content.

    cd backend && python -m scripts.cost_report            # all time
    cd backend && python -m scripts.cost_report --days 30
    cd backend && python -m scripts.cost_report --json

Costs are what each call cost when it was made, at the price file's rates of
that date. Calls the price file had no rate for are counted as unpriced and
left out of every dollar figure - the report says how many.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.db import init_database, session_scope
from app.models.database_models import Document, LlmCall, Workflow
from app.services.llm_meter import price_book

ZERO = Decimal(0)


@dataclass
class Totals:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    thinking_tokens: int = 0
    cost: Decimal = ZERO
    unpriced: int = 0
    stubs: int = 0
    failed: int = 0

    def add(self, row: LlmCall) -> None:
        self.calls += 1
        self.input_tokens += row.input_tokens
        self.output_tokens += row.output_tokens
        self.cached_tokens += row.cached_tokens
        self.thinking_tokens += row.thinking_tokens
        self.stubs += int(row.stub)
        self.failed += int(not row.succeeded)
        if row.cost_usd is None:
            self.unpriced += 1
        else:
            self.cost += Decimal(row.cost_usd)

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "thinking_tokens": self.thinking_tokens,
            "cost_usd": str(self.cost),
            "unpriced_calls": self.unpriced,
            "stub_calls": self.stubs,
            "failed_calls": self.failed,
        }


@dataclass
class Report:
    since: str
    overall: Totals = field(default_factory=Totals)
    by_stage: dict[str, Totals] = field(default_factory=lambda: defaultdict(Totals))
    by_model: dict[str, Totals] = field(default_factory=lambda: defaultdict(Totals))
    by_tier: dict[str, Totals] = field(default_factory=lambda: defaultdict(Totals))
    returns: dict[str, Totals] = field(default_factory=lambda: defaultdict(Totals))
    chats: dict[str, Totals] = field(default_factory=lambda: defaultdict(Totals))
    unattributed: Totals = field(default_factory=Totals)
    pages: dict[str, int] = field(default_factory=dict)
    prices_as_of: set[str] = field(default_factory=set)
    #: What the input tokens that were *not* served from cache cost - the part
    #: prompt caching could reduce. Priced per row from the price file.
    uncached_input_cost: Decimal = ZERO


def _distribution(values: list[Decimal]) -> dict[str, str]:
    if not values:
        return {}
    ordered = sorted(values)
    p90 = ordered[min(len(ordered) - 1, round(0.9 * (len(ordered) - 1)))]
    return {
        "mean": str(sum(ordered, ZERO) / len(ordered)),
        "median": str(statistics.median(ordered)),
        "p90": str(p90),
        "max": str(ordered[-1]),
    }


def build(days: int | None) -> Report:
    init_database()
    since = datetime.now(UTC) - timedelta(days=days) if days else None
    report = Report(since=since.isoformat() if since else "all time")
    book = price_book()
    with session_scope() as session:
        query = select(LlmCall)
        if since is not None:
            query = query.where(LlmCall.created_at >= since)
        for row in session.execute(query).scalars():
            report.overall.add(row)
            report.by_stage[row.stage].add(row)
            report.by_model[row.model].add(row)
            report.by_tier[row.tier or "unknown"].add(row)
            if row.workflow_id:
                report.returns[row.workflow_id].add(row)
            elif row.chat_session_id:
                report.chats[row.chat_session_id].add(row)
            else:
                report.unattributed.add(row)
            if row.prices_as_of:
                report.prices_as_of.add(row.prices_as_of)
            rate = book.rate(
                row.model, on=row.created_at.date(), prompt_tokens=row.input_tokens
            )
            if rate is not None and not row.stub:
                report.uncached_input_cost += (
                    Decimal(row.input_tokens - row.cached_tokens) * rate.input
                    / book.per_tokens
                )

        for workflow_id in report.returns:
            workflow = session.get(Workflow, workflow_id)
            if workflow is None:
                continue
            last = max(
                (d.page_end for d in session.execute(
                    select(Document).where(
                        Document.uploaded_file_id == workflow.uploaded_file_id
                    )
                ).scalars()),
                default=0,
            )
            if last:
                report.pages[workflow_id] = last
    return report


def savings(report: Report) -> list[dict[str, str]]:
    """Ideas ranked by the share of spend each could touch, with the risk."""
    total = report.overall.cost or Decimal(1)
    ideas: list[tuple[Decimal, dict[str, str]]] = []

    def share(cost: Decimal) -> str:
        return f"{(cost / total * 100):.0f}% of priced spend"

    extraction = sum(
        (t.cost for s, t in report.by_stage.items() if "llm" in s or "extraction" in s), ZERO
    )
    if extraction:
        ideas.append((extraction, {
            "idea": "Crop each page to the form region before extraction, and do not "
                    "re-send pages already extracted on a re-run.",
            "touches": share(extraction),
            "risk": "Medium - a crop that misses a box drops a figure silently; "
                    "gate it on the classifier's confidence and keep full-page as fallback.",
        }))

    if (
        report.uncached_input_cost
        and report.overall.cached_tokens < 0.1 * report.overall.input_tokens
    ):
        input_cost = report.uncached_input_cost
        ideas.append((input_cost, {
            "idea": "Put the system instruction and field schema first and identical in "
                    "every extraction call so implicit prompt caching applies "
                    f"(cached now: {report.overall.cached_tokens:,} of "
                    f"{report.overall.input_tokens:,} input tokens).",
            "touches": share(input_cost),
            "risk": "None to accuracy - the prompt content is unchanged, only its order.",
        }))

    for tier, totals in report.by_tier.items():
        if tier == "pro" and totals.cost:
            ideas.append((totals.cost, {
                "idea": "Route classification and bulk extraction off the Pro tier; keep Pro "
                        "for handwriting and tax reasoning.",
                "touches": share(totals.cost),
                "risk": "Medium - measure field accuracy on the eval cases before switching.",
            }))

    report_stage = report.by_stage.get("calculation_report")
    if report_stage and report_stage.cost:
        ideas.append((report_stage.cost, {
            "idea": "Report explanations are cached per return; if the same return is "
                    "re-extracted often, the cache misses. Consider explaining only the "
                    "headline lines.",
            "touches": share(report_stage.cost),
            "risk": "Low - the engine's own wording is the fallback for every line.",
        }))

    ideas.sort(key=lambda item: item[0], reverse=True)
    return [idea for _, idea in ideas]


def as_dict(report: Report) -> dict[str, Any]:
    per_return = list(report.returns.values())
    per_page = [
        report.returns[w].cost / pages for w, pages in report.pages.items() if pages
    ]
    return {
        "window": report.since,
        "prices_as_of": sorted(report.prices_as_of),
        "overall": report.overall.to_dict(),
        "stub_rate": (
            f"{report.overall.stubs / report.overall.calls:.1%}" if report.overall.calls else "n/a"
        ),
        "failure_rate": (
            f"{report.overall.failed / report.overall.calls:.1%}" if report.overall.calls else "n/a"
        ),
        "returns": {
            "count": len(per_return),
            "cost_usd": _distribution([t.cost for t in per_return]),
            "input_tokens": _distribution([Decimal(t.input_tokens) for t in per_return]),
            "output_tokens": _distribution(
                [Decimal(t.output_tokens + t.thinking_tokens) for t in per_return]
            ),
            "calls": _distribution([Decimal(t.calls) for t in per_return]),
            "cost_per_page_usd": _distribution(per_page),
            "pages_known_for": len(per_page),
        },
        "chats": {
            "count": len(report.chats),
            "cost_usd": _distribution([t.cost for t in report.chats.values()]),
        },
        "unattributed": report.unattributed.to_dict(),
        "by_stage": {k: v.to_dict() for k, v in sorted(report.by_stage.items())},
        "by_model": {k: v.to_dict() for k, v in sorted(report.by_model.items())},
        "by_tier": {k: v.to_dict() for k, v in sorted(report.by_tier.items())},
        "savings": savings(report),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=None, help="only the last N days")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    body = as_dict(build(args.days))
    if args.json:
        print(json.dumps(body, indent=2))
        return

    overall = body["overall"]
    print(f"LLM spend - {body['window']} - rates as of {', '.join(body['prices_as_of']) or 'n/a'}")
    print(
        f"  {overall['calls']} calls, ${overall['cost_usd']} priced, "
        f"{overall['unpriced_calls']} unpriced, stub rate {body['stub_rate']}, "
        f"failure rate {body['failure_rate']}"
    )
    returns = body["returns"]
    print(f"\nPer return ({returns['count']} returns)")
    for name in ("cost_usd", "cost_per_page_usd", "calls", "input_tokens", "output_tokens"):
        dist = returns[name]
        if dist:
            print(f"  {name:<20} " + "  ".join(f"{k} {v}" for k, v in dist.items()))
    print(f"\nChats: {body['chats']['count']} sessions  {body['chats']['cost_usd']}")
    for section in ("by_stage", "by_model", "by_tier"):
        print(f"\n{section.replace('_', ' ').title()}")
        for key, t in body[section].items():
            print(
                f"  {key:<32} {t['calls']:>6} calls  ${t['cost_usd']:<12} "
                f"in {t['input_tokens']:,} (cached {t['cached_tokens']:,})  "
                f"out {t['output_tokens'] + t['thinking_tokens']:,}"
            )
    print("\nSavings ideas, largest first")
    for idea in body["savings"] or [{"idea": "no priced spend yet", "touches": "", "risk": ""}]:
        print(f"  - {idea['idea']}\n    touches {idea['touches']}; risk: {idea['risk']}")


if __name__ == "__main__":
    main()
