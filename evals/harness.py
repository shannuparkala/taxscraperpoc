"""Scoring an eval case: extraction, calculation and end-to-end, separately.

Three questions that fail independently, so they are scored independently:

- **Extraction** - did the pipeline read the right figures off the documents?
  The pipeline's facts against the case's verified ``inputs``.
- **Calculation** - given the *right* figures, does the engine produce the
  filed return? The case's verified ``inputs`` and ``household`` go straight
  into the engine, bypassing extraction entirely, and the result is compared
  with the verified ``lines``. Target: 100%.
- **End to end** - the pipeline's return against the verified ``lines``. This is
  the number a user experiences, and it is reported as it is, not rounded up.

A line the engine would not compute is *unsupported*: it is neither correct nor
wrong, and it is counted separately. The failure that matters most is a line
that is wrong **and** carries no flag - a silent error - and every report leads
with those.

Pure: no database, no pipeline. ``runner.py`` produces the observations this
module scores.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ZERO = Decimal(0)


# ------------------------------------------------------------------- cases


@dataclass(frozen=True)
class ExpectedLine:
    node: str
    amount: Decimal
    verified: bool


@dataclass(frozen=True)
class ExpectedInput:
    field: str
    amount: Decimal
    verified: bool


@dataclass(frozen=True)
class ExpectedFlag:
    """A signal the pipeline must raise. See ``flag_matches`` for the kinds."""

    kind: str
    match: str = ""
    node: str = ""
    field: str = ""

    def describe(self) -> str:
        target = self.match or self.node or self.field
        return f"{self.kind}: {target}" if target else self.kind


@dataclass(frozen=True)
class Case:
    id: str
    tax_year: int
    kind: str
    path: Path
    source: Mapping[str, str]
    household: Mapping[str, Any]
    inputs: tuple[ExpectedInput, ...]
    lines: tuple[ExpectedLine, ...]
    expected_flags: tuple[ExpectedFlag, ...]
    tolerance: Decimal | None = None
    notes: str = ""

    @property
    def synthetic(self) -> bool:
        return str(self.source.get("workpaper", "")).startswith("synthetic:")

    @property
    def calculable(self) -> bool:
        """Calculation needs every input verified: a guessed input scores nothing."""
        return bool(self.household) and bool(self.inputs) and all(
            i.verified for i in self.inputs
        )


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"not an amount: {value!r}") from exc


def load_case(path: Path) -> Case:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Case(
        id=str(raw["id"]),
        tax_year=int(raw["tax_year"]),
        kind=str(raw.get("kind", "reconciled")),
        path=path,
        source=raw.get("source") or {},
        household=raw.get("household") or {},
        inputs=tuple(
            ExpectedInput(str(i["field"]), _decimal(i["amount"]), bool(i.get("verified")))
            for i in raw.get("inputs") or []
        ),
        lines=tuple(
            ExpectedLine(str(line["node"]), _decimal(line["amount"]), bool(line.get("verified")))
            for line in raw.get("lines") or []
        ),
        expected_flags=tuple(
            ExpectedFlag(
                kind=str(f["kind"]),
                match=str(f.get("match", "")),
                node=str(f.get("node", "")),
                field=str(f.get("field", "")),
            )
            for f in raw.get("expected_flags") or []
        ),
        tolerance=_decimal(raw["tolerance"]) if raw.get("tolerance") is not None else None,
        notes=str(raw.get("notes", "")),
    )


def discover(*roots: Path) -> list[Case]:
    cases: list[Case] = []
    for root in roots:
        if root.exists():
            cases.extend(load_case(p) for p in sorted(root.glob("*/expected.json")))
    return cases


# ------------------------------------------------------------------ scores


@dataclass
class LineScore:
    """One layer's comparison of computed figures against expected ones."""

    correct: list[str] = field(default_factory=list)
    #: (id, expected, got) - got is None when the figure was absent.
    wrong: list[tuple[str, Decimal, Decimal | None]] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    #: Wrong figures on lines that carried no flag. The worst outcome there is.
    silent: list[str] = field(default_factory=list)
    unverified_skipped: int = 0
    skipped_reason: str = ""

    @property
    def scored(self) -> int:
        return len(self.correct) + len(self.wrong)

    @property
    def accuracy(self) -> float | None:
        return None if not self.scored else len(self.correct) / self.scored

    def to_dict(self) -> dict[str, Any]:
        return {
            "accuracy": self.accuracy,
            "correct": len(self.correct),
            "wrong": [[i, str(e), None if g is None else str(g)] for i, e, g in self.wrong],
            "unsupported": self.unsupported,
            "silent_errors": self.silent,
            "unverified_skipped": self.unverified_skipped,
            "skipped_reason": self.skipped_reason,
        }


def _close(a: Decimal, b: Decimal, tolerance: Decimal) -> bool:
    return abs(a - b) <= tolerance


def score_lines(
    expected: Iterable[ExpectedLine],
    computed: Mapping[str, Decimal | None],
    *,
    flagged: set[str],
    tolerance: Decimal,
) -> LineScore:
    """Expected return lines against a computed return.

    ``computed`` maps node id to amount (None = unsupported); a node missing
    from it entirely is wrong, not unsupported - the engine does not have the
    line at all. ``flagged`` is every node carrying a flag, for spotting the
    wrong ones that do not.
    """
    score = LineScore()
    for line in expected:
        if not line.verified:
            score.unverified_skipped += 1
            continue
        if line.node in computed and computed[line.node] is None:
            score.unsupported.append(line.node)
            continue
        got = computed.get(line.node)
        if got is not None and _close(got, line.amount, tolerance):
            score.correct.append(line.node)
        else:
            score.wrong.append((line.node, line.amount, got))
            if line.node not in flagged:
                score.silent.append(line.node)
    return score


def score_inputs(
    expected: Iterable[ExpectedInput],
    extracted: Mapping[str, Decimal],
    *,
    tolerance: Decimal,
) -> LineScore:
    """Verified document figures against what the pipeline read."""
    score = LineScore()
    for item in expected:
        if not item.verified:
            score.unverified_skipped += 1
            continue
        got = extracted.get(item.field)
        if got is not None and _close(got, item.amount, tolerance):
            score.correct.append(item.field)
        else:
            score.wrong.append((item.field, item.amount, got))
    return score


# ------------------------------------------------------------------- flags


@dataclass(frozen=True)
class Observations:
    """What a pipeline run raised, in the forms a flag can take."""

    review_items: tuple[str, ...] = ()        # "title - description"
    unsupported: tuple[str, ...] = ()         # graph node ids
    unplaced: tuple[str, ...] = ()            # pipeline field names
    layout_warnings: tuple[str, ...] = ()
    fileable: bool = True


def flag_matches(flag: ExpectedFlag, seen: Observations) -> bool:
    """Whether a run raised the signal a flag asks for.

    Kinds:
      review_item     a review item whose title or description matches ``match``
                      (a case-insensitive regular expression)
      unsupported     graph line ``node`` is marked unsupported
      unplaced        pipeline field ``field`` was read and placed on no line
      layout_warning  a page warning matching ``match`` (rotation, for one)
      not_fileable    the return is marked not fileable
    """
    pattern = re.compile(flag.match, re.IGNORECASE) if flag.match else None
    if flag.kind == "review_item":
        return pattern is not None and any(pattern.search(t) for t in seen.review_items)
    if flag.kind == "unsupported":
        return flag.node in seen.unsupported
    if flag.kind == "unplaced":
        return flag.field in seen.unplaced
    if flag.kind == "layout_warning":
        return pattern is not None and any(pattern.search(w) for w in seen.layout_warnings)
    if flag.kind == "not_fileable":
        return not seen.fileable
    raise ValueError(f"unknown flag kind {flag.kind!r}")


@dataclass
class FlagScore:
    hit: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float | None:
        total = len(self.hit) + len(self.missed)
        return None if not total else len(self.hit) / total

    def to_dict(self) -> dict[str, Any]:
        return {"rate": self.rate, "hit": self.hit, "missed": self.missed}


def score_flags(expected: Iterable[ExpectedFlag], seen: Observations) -> FlagScore:
    score = FlagScore()
    for flag in expected:
        (score.hit if flag_matches(flag, seen) else score.missed).append(flag.describe())
    return score


# -------------------------------------------------------------- the result


@dataclass
class CaseResult:
    case_id: str
    kind: str
    calculation: LineScore = field(default_factory=LineScore)
    extraction: LineScore = field(default_factory=LineScore)
    end_to_end: LineScore = field(default_factory=LineScore)
    flags: FlagScore = field(default_factory=FlagScore)
    cost_usd: Decimal | None = None
    unpriced_calls: int = 0
    llm_calls: int = 0
    seconds: float | None = None
    workflow_id: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case": self.case_id,
            "kind": self.kind,
            "calculation": self.calculation.to_dict(),
            "extraction": self.extraction.to_dict(),
            "end_to_end": self.end_to_end.to_dict(),
            "flags": self.flags.to_dict(),
            "cost_usd": None if self.cost_usd is None else str(self.cost_usd),
            "unpriced_calls": self.unpriced_calls,
            "llm_calls": self.llm_calls,
            "seconds": self.seconds,
            "workflow_id": self.workflow_id,
            "error": self.error,
        }


def headline(results: Iterable[CaseResult]) -> dict[str, Any]:
    """Suite-wide figures: pooled over lines, not averaged over cases.

    Pooling means a case with forty lines weighs more than a case with four,
    which is what "accuracy" should mean. Averaging per case lets one easy case
    hide a hard one.
    """
    results = list(results)

    def pooled(layer: str) -> dict[str, Any]:
        correct = sum(len(getattr(r, layer).correct) for r in results)
        wrong = sum(len(getattr(r, layer).wrong) for r in results)
        return {
            "accuracy": None if not correct + wrong else correct / (correct + wrong),
            "correct": correct,
            "scored": correct + wrong,
            "unsupported": sum(len(getattr(r, layer).unsupported) for r in results),
            "silent_errors": sum(len(getattr(r, layer).silent) for r in results),
            "unverified_skipped": sum(getattr(r, layer).unverified_skipped for r in results),
        }

    hit = sum(len(r.flags.hit) for r in results)
    missed = sum(len(r.flags.missed) for r in results)
    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    seconds = [r.seconds for r in results if r.seconds is not None]
    return {
        "cases": len(results),
        "calculation": pooled("calculation"),
        "extraction": pooled("extraction"),
        "end_to_end": pooled("end_to_end"),
        "flags": {"rate": None if not hit + missed else hit / (hit + missed),
                  "hit": hit, "expected": hit + missed},
        "cost_usd": {"total": str(sum(costs, ZERO).quantize(Decimal("0.0001"))),
                     "mean": str((sum(costs, ZERO) / len(costs)).quantize(Decimal("0.0001")))
                     if costs else None},
        "seconds": {"total": round(sum(seconds), 1),
                    "mean": round(sum(seconds) / len(seconds), 1) if seconds else None},
        "errors": [r.case_id for r in results if r.error],
    }


def regressions(previous: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    """Every per-case metric that got worse since the last recorded run.

    Compared case by case, so a gain on one case cannot hide a loss on another.
    A case that is new, or a layer that was not run this time, is not a
    regression - there is nothing to fall from.
    """
    found: list[str] = []
    for case_id, now in current.items():
        before = previous.get(case_id)
        if not before:
            continue
        for layer in ("calculation", "extraction", "end_to_end"):
            a, b = before[layer].get("accuracy"), now[layer].get("accuracy")
            if a is not None and b is not None and b < a:
                found.append(f"{case_id}: {layer} {a:.1%} -> {b:.1%}")
            if len(now[layer].get("silent_errors", [])) > len(before[layer].get("silent_errors", [])):
                found.append(f"{case_id}: {layer} gained a silent error")
        a, b = before["flags"].get("rate"), now["flags"].get("rate")
        if a is not None and b is not None and b < a:
            found.append(f"{case_id}: flags {a:.0%} -> {b:.0%}")
        if now.get("error") and not before.get("error"):
            found.append(f"{case_id}: now errors ({now['error'][:80]})")
    return found
