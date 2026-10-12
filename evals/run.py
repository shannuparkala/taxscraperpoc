"""``make eval``: score every case, write ``evals/REPORT.md``, fail on regression.

    python -m evals.run                    # every case, full pipeline
    python -m evals.run --calc-only        # engine only: fast, no model, no OCR
    python -m evals.run --case basic-5     # one case (repeatable)
    python -m evals.run --update-baseline  # accept this run as the new baseline

Cases come from two places:

- ``evals/cases/<id>/``      real workpaper/return pairs - gitignored, client data
- ``evals/synthetic/<id>/``  invented adversarial cases - committed

Exit status is 1 when any case scored worse than the recorded baseline on any
layer, gained a silent error, or started erroring; with ``--require-targets`` it
is also 1 when a Phase 6.7 target is missed. The first run records the
baseline. The report says, before anything else, how many lines were *not*
scored because nobody has verified them yet - an accuracy over three verified
lines is not an accuracy over a return.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
REAL = ROOT / "evals" / "cases"
SYNTHETIC = ROOT / "evals" / "synthetic"
REPORT = ROOT / "evals" / "REPORT.md"
BASELINE = ROOT / "evals" / ".baseline.json"
LAST = ROOT / "evals" / ".last.json"
EVAL_DATA = ROOT / "data" / "evals"


def _isolate() -> None:
    """Point the app at the eval database and zones before it is imported.

    A benchmark run writes workflows, review items and ledger rows. Written to
    the working database they would bury a preparer's real queue (trap 31), so
    everything goes under ``data/evals/`` instead. ``.env`` is still read - the
    Gemini key and Tesseract path come from it - which is why the working
    directory becomes ``backend/``.
    """
    for zone in ("raw", "masked", "output", "tmp", "vector"):
        (EVAL_DATA / zone).mkdir(parents=True, exist_ok=True)
    os.environ["DATA_DIR"] = str(EVAL_DATA)
    for name, zone in (
        ("RAW_ZONE_DIR", "raw"), ("MASKED_ZONE_DIR", "masked"),
        ("OUTPUT_ZONE_DIR", "output"), ("TMP_ZONE_DIR", "tmp"),
        ("VECTOR_STORE_DIR", "vector"),
    ):
        os.environ[name] = str(EVAL_DATA / zone)
    os.environ["DATABASE_URL"] = f"sqlite:///{(EVAL_DATA / 'eval.db').as_posix()}"
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    sys.path.insert(0, str(ROOT))


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.1%}"


def _targets(summary: dict[str, Any]) -> list[tuple[str, bool | None, str]]:
    calc = summary["calculation"]
    flags = summary["flags"]
    silent = sum(summary[layer]["silent_errors"] for layer in ("calculation", "end_to_end"))
    return [
        ("Calculation accuracy 100%",
         None if calc["accuracy"] is None else calc["accuracy"] == 1.0,
         f"{calc['correct']}/{calc['scored']} verified lines"),
        ("Every expected flag raised (unsupported items included)",
         None if flags["rate"] is None else flags["rate"] == 1.0,
         f"{flags['hit']}/{flags['expected']}"),
        ("No silent errors", silent == 0, f"{silent} wrong line(s) with no flag"),
    ]


def render(results: list[Any], summary: dict[str, Any], regressions: list[str],
           *, calc_only: bool, baseline_recorded: bool) -> str:
    unverified = sum(
        summary[layer]["unverified_skipped"] for layer in ("calculation", "end_to_end")
    )
    out = [
        "# Eval report",
        "",
        (
            f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC} over {summary['cases']} case(s)"
            + (" - calculation only, no pipeline run" if calc_only else "") + "."
        ),
        "",
        (
            "Real-corpus figures in this file are client data: it is gitignored "
            "and stays that way."
        ),
        "",
        "## Read this first",
        "",
        (
            f"- **{unverified} expected line(s) were not scored** because they are "
            "not verified yet. They cannot pass or fail."
        ),
        f"- Cases that errored: {', '.join(summary['errors']) or 'none'}.",
        (
            "- Accuracy is pooled over lines, not averaged over cases, so an easy "
            "case cannot hide a hard one."
        ),
        (
            "- Nothing here was tuned to these cases. A fix that makes one case "
            "pass should be a fix to a rule, with its own unit test, not to the case."
        ),
        "",
        "## Regressions against the baseline",
        "",
    ]
    if baseline_recorded:
        out.append("No baseline existed; this run was recorded as the baseline.")
    else:
        out += [f"- {r}" for r in regressions] or ["None."]

    out += ["", "## Targets (Phase 6.7)", "", "| Target | Status | Detail |", "|---|---|---|"]
    for name, met, detail in _targets(summary):
        status = "not measured" if met is None else ("MET" if met else "**MISSED**")
        out.append(f"| {name} | {status} | {detail} |")

    out += ["", "## Suite", "", "| Layer | Accuracy | Correct / scored | Unsupported | Silent errors |",
            "|---|---|---|---|---|"]
    for layer in ("extraction", "calculation", "end_to_end"):
        s = summary[layer]
        out.append(f"| {layer.replace('_', ' ')} | {_pct(s['accuracy'])} | "
                   f"{s['correct']}/{s['scored']} | {s['unsupported']} | {s['silent_errors']} |")
    out += [
        "",
        (
            f"Flags: {_pct(summary['flags']['rate'])} ({summary['flags']['hit']}/"
            f"{summary['flags']['expected']}). Model cost: ${summary['cost_usd']['total']} "
            f"total, ${summary['cost_usd']['mean'] or '-'} per case. Time: "
            f"{summary['seconds']['total']}s total, {summary['seconds']['mean'] or '-'}s per case."
        ),
        "",
        "## Cases",
        "",
        "| Case | Kind | Extraction | Calculation | End to end | Flags | Cost | Time |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        def cell(score: Any) -> str:
            if score.skipped_reason and not score.scored:
                return f"skipped ({score.skipped_reason})"
            return f"{_pct(score.accuracy)} ({len(score.correct)}/{score.scored})"

        out.append(
            f"| {r.case_id} | {r.kind} | {cell(r.extraction)} | {cell(r.calculation)} | "
            f"{cell(r.end_to_end)} | {_pct(r.flags.rate)} | "
            f"{'-' if r.cost_usd is None else '$' + str(r.cost_usd.quantize(Decimal('0.0001')))} | "
            f"{'-' if r.seconds is None else f'{r.seconds}s'} |"
        )

    out += ["", "## Findings, case by case", ""]
    for r in results:
        lines: list[str] = []
        if r.error:
            lines.append(f"- errored: {r.error}")
        for layer_name in ("calculation", "end_to_end", "extraction"):
            score = getattr(r, layer_name)
            for node, expected, got in score.wrong:
                silent = " **(no flag - silent)**" if node in score.silent else ""
                lines.append(f"- {layer_name.replace('_', ' ')}: `{node}` expected {expected}, "
                             f"got {'nothing' if got is None else got}{silent}")
            for node in score.unsupported:
                lines.append(f"- {layer_name.replace('_', ' ')}: `{node}` unsupported (flagged)")
        for flag in r.flags.missed:
            lines.append(f"- flag not raised: {flag}")
        if lines:
            out += [f"### {r.case_id}", "", *lines, ""]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score the eval cases.")
    parser.add_argument("--case", action="append", default=[], help="only this case id")
    parser.add_argument("--calc-only", action="store_true", help="engine only, no pipeline")
    parser.add_argument("--no-real", action="store_true", help="skip evals/cases")
    parser.add_argument("--no-synthetic", action="store_true", help="skip evals/synthetic")
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--require-targets", action="store_true")
    args = parser.parse_args(argv)

    _isolate()
    from evals.harness import CaseResult, discover, headline, regressions
    from evals.runner import calculate, run_pipeline

    roots = [] if args.no_real else [REAL]
    roots += [] if args.no_synthetic else [SYNTHETIC]
    cases = [c for c in discover(*roots) if not args.case or c.id in args.case]
    if not cases:
        print("No eval cases found. Real cases are added with /add-eval-case.")
        return 0

    from app.core.db import init_database

    init_database()
    results = []
    for case in cases:
        result = CaseResult(case.id, case.kind)
        print(f"- {case.id}: ", end="", flush=True)
        try:
            calculate(case, result)
            if not args.calc_only:
                run_pipeline(case, result)
        except Exception as exc:  # noqa: BLE001 - one case must not cost the rest
            # The type only: a message from deep in the pipeline can carry a
            # value off a client document, and this line reaches the report.
            result.error = type(exc).__name__
        print(result.error or "done", flush=True)
        results.append(result)

    summary = headline(results)
    current = {r.case_id: r.to_dict() for r in results}
    previous = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    found = regressions(previous, current)
    record_baseline = args.update_baseline or not BASELINE.exists()

    REPORT.write_text(
        render(results, summary, found, calc_only=args.calc_only,
               baseline_recorded=not previous),
        encoding="utf-8",
    )
    LAST.write_text(json.dumps(current, indent=2), encoding="utf-8")
    if record_baseline:
        BASELINE.write_text(json.dumps({**previous, **current}, indent=2), encoding="utf-8")

    print(f"\nReport: {REPORT.relative_to(ROOT)}")
    for regression in found:
        print(f"REGRESSION {regression}")
    missed = [name for name, met, _ in _targets(summary) if met is False]
    for name in missed:
        print(f"TARGET MISSED {name}")
    if found and not args.update_baseline:
        return 1
    if args.require_targets and missed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
