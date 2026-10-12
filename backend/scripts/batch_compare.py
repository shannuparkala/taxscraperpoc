"""Score the batch run against the accountant-prepared returns.

Pairs each workpaper's computed return with its accountant copy and compares the
headline Form 1040 lines. Ground truth comes from the CCH "Return Summary" page
rather than the filled 1040, because that page OCRs reliably and the form does
not — see ``read_return_summary``.

Only lines present on both sides are scored. A line the benchmark could not
supply is reported as "no benchmark", never as a failure: scoring the engine
against a figure we could not read would invent errors.

    cd backend && python -m scripts.batch_compare
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytesseract

from app.core.config import get_settings
from scripts.read_return_summary import read_summary

ROOT = Path(__file__).resolve().parents[2]
FILES = ROOT / "Files"
LEARNING = ROOT / "data" / "learning"
BATCH = LEARNING / "BatchRun.json"
OUT = LEARNING / "BatchComparison.json"

#: Lines the Return Summary supplies, in the order a reader scans them.
SCORED = ["11", "12", "13b", "15", "16", "25", "26", "34", "36", "37"]

LABELS = {
    "11": "Adjusted gross income",
    "12": "Standard/itemized deduction",
    "13b": "Additional deductions",
    "15": "Taxable income",
    "16": "Tax",
    "25": "Withholding",
    "26": "Estimated payments",
    "34": "Overpaid",
    "36": "Applied to next year",
    "37": "Amount owed",
}

#: Whole dollars. A cent of disagreement is the engine carrying cents where the
#: form uses dollars (ERR-005), not a different answer.
TOLERANCE = Decimal(1)


def case_key(name: str) -> str:
    lowered = name.lower().replace(".pdf", "")
    for pattern, label in (
        (r"cs\s*2", "CS 2"), (r"cs\s*3", "CS 3"), (r"cs\s*1", "CS 1"),
        (r"david miller", "David Miller"), (r"basic 10", "Basic 10"),
        (r"basic 4", "Basic 4"), (r"basic 5", "Basic 5"),
        (r"basic 6", "Basic 6"), (r"basic 7", "Basic 7"), (r"basic 9", "Basic 9"),
    ):
        if re.search(pattern, lowered):
            return label
    return name


def accountant_copies() -> dict[str, Path]:
    return {
        case_key(p.name): p
        for p in FILES.glob("*.pdf")
        if "acc" in p.name.lower() or "acntnt" in p.name.lower()
    }


def compare_one(ours: dict[str, Any], copy: Path) -> dict[str, Any]:
    benchmark = read_summary(copy)
    truth: dict[str, Decimal] = benchmark["lines"]  # type: ignore[assignment]
    lines: dict[str, str] = ours.get("lines") or {}

    rows: list[dict[str, Any]] = []
    matched = compared = 0
    for line in SCORED:
        expected = truth.get(line)
        got_raw = lines.get(line)
        got = Decimal(got_raw) if got_raw is not None else None

        if expected is None:
            verdict = "no benchmark"
        elif got is None:
            verdict = "not produced"
            compared += 1
        else:
            compared += 1
            if abs(got - expected) <= TOLERANCE:
                verdict = "match"
                matched += 1
            else:
                verdict = "differs"
        rows.append(
            {
                "line": line,
                "label": LABELS[line],
                "ours": str(got) if got is not None else None,
                "accountant": str(expected) if expected is not None else None,
                "delta": str(got - expected) if (got is not None and expected is not None) else None,
                "verdict": verdict,
            }
        )

    return {
        "accountant_copy": copy.name,
        "benchmark_pages": benchmark["summary_pages"],
        "benchmark_filing_status": benchmark["filing_status"],
        "our_filing_status": ours.get("filing_status"),
        "lines_compared": compared,
        "lines_matched": matched,
        "accuracy": round(100 * matched / compared, 1) if compared else None,
        "rows": rows,
    }


def main() -> None:
    settings = get_settings()
    if getattr(settings, "tesseract_cmd", None):
        pytesseract.pytesseract.tesseract_cmd = str(settings.tesseract_cmd)

    if not BATCH.exists():
        print("No BatchRun.json — run scripts.batch_run first.")
        raise SystemExit(1)

    batch = json.loads(BATCH.read_text(encoding="utf-8"))["cases"]
    copies = accountant_copies()

    results: dict[str, Any] = {}
    total_compared = total_matched = 0

    for workpaper, ours in sorted(batch.items()):
        key = case_key(workpaper)
        copy = copies.get(key)
        if copy is None:
            results[key] = {"error": f"no accountant copy paired with {workpaper}"}
            continue
        if not ours.get("computed_return"):
            results[key] = {
                "accountant_copy": copy.name,
                "error": "no return computed",
                "status": ours.get("status"),
                "review_items": len(ours.get("review_items") or []),
            }
            continue

        print(f"  comparing {key} ...", flush=True)
        record = compare_one(ours, copy)
        record["status"] = ours.get("status")
        record["review_items"] = len(ours.get("review_items") or [])
        results[key] = record
        total_compared += record["lines_compared"]
        total_matched += record["lines_matched"]

    payload = {
        "description": (
            "Engine output scored against accountant-prepared returns. Ground "
            "truth is the CCH Return Summary page; lines it could not supply "
            "are excluded rather than counted as failures."
        ),
        "tolerance_dollars": str(TOLERANCE),
        "overall": {
            "lines_compared": total_compared,
            "lines_matched": total_matched,
            "accuracy": round(100 * total_matched / total_compared, 1)
            if total_compared
            else None,
        },
        "cases": results,
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\n{'case':<16}{'status':<18}{'matched':>9}{'compared':>10}{'accuracy':>10}")
    for key, record in sorted(results.items()):
        if "error" in record:
            print(f"{key:<16}{record.get('status', 'n/a'):<18}{'-':>9}{'-':>10}   {record['error']}")
            continue
        print(
            f"{key:<16}{record['status']:<18}{record['lines_matched']:>9}"
            f"{record['lines_compared']:>10}{record['accuracy']:>9}%"
        )
    overall = payload["overall"]["accuracy"]
    print(f"\nOVERALL: {total_matched}/{total_compared} = {overall}%  -> {OUT.name}")


if __name__ == "__main__":
    main()
