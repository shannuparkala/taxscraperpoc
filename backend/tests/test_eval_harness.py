"""Phase 6.2: the harness's own tests - the part of ``make eval`` CI can run.

The real cases are client data and never reach CI, so the scoring logic is
proven here on invented figures instead: a harness that scores wrongly is
worse than none, because its report is what everyone reads.
"""

from __future__ import annotations

import json
import re
import sys
from decimal import Decimal as D
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.harness import (
    CaseResult,
    ExpectedFlag,
    ExpectedLine,
    Observations,
    discover,
    headline,
    load_case,
    regressions,
    score_flags,
    score_inputs,
    score_lines,
)
from evals.harness import ExpectedInput as In

SYNTHETIC = ROOT / "evals" / "synthetic"


# ------------------------------------------------------------ line scoring


def test_lines_are_scored_correct_wrong_unsupported_or_unverified() -> None:
    expected = [
        ExpectedLine("f1040.l9", D(100), True),
        ExpectedLine("f1040.l11a", D(90), True),
        ExpectedLine("f1040.l19", D(2000), True),
        ExpectedLine("f1040.l24", D(7), False),
        ExpectedLine("f1040.l99", D(1), True),
    ]
    computed = {"f1040.l9": D("100.40"), "f1040.l11a": D(95), "f1040.l19": None}
    score = score_lines(expected, computed, flagged={"f1040.l19"}, tolerance=D("0.50"))

    assert score.correct == ["f1040.l9"]
    assert [w[0] for w in score.wrong] == ["f1040.l11a", "f1040.l99"]
    assert score.unsupported == ["f1040.l19"], "unsupported is neither right nor wrong"
    assert score.unverified_skipped == 1, "an unverified line cannot pass or fail"
    assert score.silent == ["f1040.l11a", "f1040.l99"]
    assert score.accuracy == pytest.approx(1 / 3)


def test_a_wrong_line_that_carries_a_flag_is_not_silent() -> None:
    score = score_lines(
        [ExpectedLine("f1040.l11a", D(90), True)], {"f1040.l11a": D(95)},
        flagged={"f1040.l11a"}, tolerance=D(0),
    )
    assert score.wrong and not score.silent


def test_inputs_missing_from_extraction_are_wrong_not_skipped() -> None:
    score = score_inputs(
        [In("wages", D(50000), True), In("taxable_interest", D(320), True)],
        {"wages": D(50000)}, tolerance=D(1),
    )
    assert score.correct == ["wages"]
    assert score.wrong == [("taxable_interest", D(320), None)]


# ------------------------------------------------------------------- flags


def test_every_flag_kind_matches_what_it_names() -> None:
    seen = Observations(
        review_items=("3 page(s) read below the confidence floor - ...",),
        unsupported=("f1040.l19",),
        unplaced=("short_term_gain",),
        layout_warnings=("Page was rotated 90° to read it.",),
        fileable=False,
    )
    flags = [
        ExpectedFlag("review_item", match="below the confidence FLOOR"),
        ExpectedFlag("unsupported", node="f1040.l19"),
        ExpectedFlag("unplaced", field="short_term_gain"),
        ExpectedFlag("layout_warning", match="rotated"),
        ExpectedFlag("not_fileable"),
        ExpectedFlag("review_item", match="duplicate"),
    ]
    score = score_flags(flags, seen)
    assert len(score.hit) == 5
    assert score.missed == ["review_item: duplicate"]


def test_an_unknown_flag_kind_is_an_error_not_a_miss() -> None:
    with pytest.raises(ValueError):
        score_flags([ExpectedFlag("vibes")], Observations())


# -------------------------------------------------------------- regression


def _result(case_id: str, correct: int, wrong: int, silent: int = 0) -> dict:  # type: ignore[type-arg]
    r = CaseResult(case_id, "reconciled")
    r.calculation.correct = [f"c{i}" for i in range(correct)]
    r.calculation.wrong = [(f"w{i}", D(1), D(2)) for i in range(wrong)]
    r.calculation.silent = [f"w{i}" for i in range(silent)]
    return r.to_dict()


def test_a_drop_on_any_case_is_a_regression_even_if_another_improves() -> None:
    before = {"a": _result("a", 9, 1), "b": _result("b", 5, 5)}
    after = {"a": _result("a", 8, 2), "b": _result("b", 10, 0)}
    found = regressions(before, after)
    assert found == ["a: calculation 90.0% -> 80.0%"]


def test_a_new_silent_error_is_a_regression_at_equal_accuracy() -> None:
    found = regressions({"a": _result("a", 9, 1, silent=0)}, {"a": _result("a", 9, 1, silent=1)})
    assert found == ["a: calculation gained a silent error"]


def test_a_new_case_is_not_a_regression() -> None:
    assert regressions({}, {"a": _result("a", 0, 5)}) == []


def test_accuracy_is_pooled_over_lines_not_averaged_over_cases() -> None:
    easy, hard = CaseResult("easy", "r"), CaseResult("hard", "r")
    easy.calculation.correct = ["x"]
    hard.calculation.correct = ["y"] * 1
    hard.calculation.wrong = [(f"z{i}", D(1), D(2)) for i in range(9)]
    assert headline([easy, hard])["calculation"]["accuracy"] == pytest.approx(2 / 11)


# ------------------------------------------------------------ calculation


def test_the_calculation_layer_scores_the_engine_from_verified_inputs(tmp_path: Path) -> None:
    from evals.runner import calculate

    from app.services.tax_engine.tax_authority import constants_for

    standard = constants_for(2025).standard_deduction["single"]
    standard = standard.value if hasattr(standard, "value") else standard
    case_dir = tmp_path / "calc-1"
    case_dir.mkdir()
    (case_dir / "expected.json").write_text(json.dumps({
        "id": "calc-1", "tax_year": 2025, "kind": "reconciled",
        "source": {"workpaper": "n/a"},
        "household": {"filing_status": "single", "taxpayer_age": 40},
        "inputs": [{"field": "wages", "amount": "50000", "verified": True}],
        "lines": [
            {"node": "f1040.l11a", "amount": "50000", "verified": True},
            {"node": "f1040.l15", "amount": str(D(50000) - standard), "verified": True},
            {"node": "f1040.l9", "amount": "1", "verified": True},
        ],
    }), encoding="utf-8")
    (case,) = discover(tmp_path)
    result = CaseResult(case.id, case.kind)
    calculate(case, result)
    assert result.calculation.correct == ["f1040.l11a", "f1040.l15"]
    assert [w[0] for w in result.calculation.wrong] == ["f1040.l9"]


def test_calculation_waits_until_every_input_is_verified(tmp_path: Path) -> None:
    from evals.runner import calculate

    case_dir = tmp_path / "calc-2"
    case_dir.mkdir()
    (case_dir / "expected.json").write_text(json.dumps({
        "id": "calc-2", "tax_year": 2025, "source": {},
        "household": {"filing_status": "single"},
        "inputs": [{"field": "wages", "amount": "50000", "verified": False}],
        "lines": [{"node": "f1040.l11a", "amount": "50000", "verified": True}],
    }), encoding="utf-8")
    (case,) = discover(tmp_path)
    result = CaseResult(case.id, case.kind)
    calculate(case, result)
    assert result.calculation.scored == 0
    assert result.calculation.skipped_reason == "1 input(s) not verified"


# ------------------------------------------------------ synthetic cases


def test_every_synthetic_case_loads_and_names_a_builder() -> None:
    from evals.synthetic.build import BUILDERS

    cases = discover(SYNTHETIC)
    assert len(cases) >= 7
    for case in cases:
        assert case.kind == "adversarial"
        assert case.synthetic
        assert case.source["workpaper"].removeprefix("synthetic:") in BUILDERS
        assert case.expected_flags or case.inputs, case.id


@pytest.mark.security
def test_synthetic_workpapers_carry_only_surrogate_identifiers(tmp_path: Path) -> None:
    """Invented, and in the ranges the egress guard recognises as invented."""
    import fitz
    from evals.synthetic.build import BUILDERS, build

    for name in BUILDERS:
        text = "".join(page.get_text() for page in fitz.open(build(name, tmp_path)))
        for ssn in re.findall(r"\b\d{3}-\d{2}-\d{4}\b", text):
            assert ssn.startswith("666-"), (name, "SSN outside the surrogate range")
        for ein in re.findall(r"\b\d{2}-\d{7}\b", text):
            assert ein.startswith("00-"), (name, "EIN outside the surrogate range")


def test_no_committed_eval_file_carries_a_real_case() -> None:
    """``evals/cases`` is gitignored; nothing committed may point into ``Files/``."""
    for path in (ROOT / "evals").rglob("*"):
        if path.is_file() and "cases" not in path.parts and path.suffix in {".json", ".md", ".py"}:
            if path.name in {"REPORT.md"}:
                continue
            body = path.read_text(encoding="utf-8")
            assert "Files/" not in body and "Files\\" not in body, path
    assert load_case  # imported for the public surface; used by discover
