"""scripts.refresh_rules proposes; it never writes rule data."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.depreciation.rules import RULES_DIR, DepreciationRules
from app.services.gemini_service import Grounding, GroundingSource, LlmResponse
from scripts import refresh_rules


class FakeGemini:
    enabled = True

    def __init__(self, text: str, grounding: Grounding) -> None:
        self.text, self.grounding = text, grounding

    def generate(self, **kwargs: Any) -> LlmResponse:
        assert kwargs["google_search"] is True
        return LlmResponse(text=self.text, grounding=self.grounding)


IRS = Grounding(sources=[GroundingSource("https://www.irs.gov/pub/irs-drop/rp-25-32.pdf", "irs.gov")])


def _digest() -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(RULES_DIR).glob("*.json")}


def test_a_changed_figure_is_flagged_and_nothing_is_written(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(refresh_rules, "OUT_DIR", tmp_path)
    before = _digest()
    rules = DepreciationRules()
    check = refresh_rules.federal_checks(2026, rules)[0]
    reply = '{"value": {"limit": 2600000, "phaseout_threshold": 4090000, "suv_cap": 32000}, "tax_year": 2026, ' \
            '"source_citation": "Rev. Proc. X", "confidence": "high"}'
    refresh_rules.run_check(check, FakeGemini(reply, IRS), get_settings())
    assert check.status == "changed"
    report = refresh_rules.write_report(2026, [check])
    assert "Nothing here has been applied" in report.read_text(encoding="utf-8")
    assert _digest() == before  # the rule files are untouched


def test_matching_figure_is_same() -> None:
    check = refresh_rules.federal_checks(2026, DepreciationRules())[0]
    reply = '{"value": {"limit": 2560000, "phaseout_threshold": 4090000, "suv_cap": 32000}, "confidence": "high"}'
    refresh_rules.run_check(check, FakeGemini(reply, IRS), get_settings())
    assert check.status == "same"


def test_a_proposal_without_grounding_is_marked_ungrounded() -> None:
    check = refresh_rules.federal_checks(2026, DepreciationRules())[0]
    reply = '{"value": {"limit": 1, "phaseout_threshold": 2, "suv_cap": 3}}'
    refresh_rules.run_check(check, FakeGemini(reply, Grounding()), get_settings())
    assert check.status == "ungrounded"


def test_unpublished_year_is_not_guessed() -> None:
    check = refresh_rules.federal_checks(2027, DepreciationRules())[0]
    assert check.current is None
    refresh_rules.run_check(check, FakeGemini('{"value": null}', IRS), get_settings())
    assert check.status == "not_published"


def test_dry_run_lists_checks_without_calling_anything(capsys) -> None:
    assert refresh_rules.main(["--year", "2026", "--states", "CA,TX", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "section_179.2026" in out and "state.CA.2026" in out and "state.TX.2026" in out
