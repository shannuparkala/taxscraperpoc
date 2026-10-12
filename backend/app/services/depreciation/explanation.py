"""A plain-English, grounded explanation of a result the engine already computed.

The model explains; it never computes. Three things enforce that:

* It receives only the computed facts - class labels, years, and the
  engine's figures - never the user's free-text asset descriptions (which
  could hold anything) and never a request to work something out.
* Its reply is checked: every dollar amount and percentage it states must
  be one that appears in the facts it was given. A reply that introduces a
  number is regenerated once and then replaced by a fallback; it is never
  shown.
* It must be grounded (CLAUDE.md rule 6). Citations are built only from the
  Google Search grounding metadata through the assistant's ``citations``
  module; with no sources the explanation is withheld.

Every call goes through ``GeminiService`` - the egress guard, retries,
metering and audit all apply.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.enums import TaskKind
from app.services.assistant import citations
from app.services.gemini_service import GeminiService

logger = get_logger(__name__)

SYSTEM_INSTRUCTION = """\
You explain a US tax depreciation result to a reader with no tax background.
A deterministic calculator has ALREADY computed every number. Your job is only
to explain, in plain English, what the numbers mean and which rules produced
them.

Hard rules:
- Do not calculate, estimate, round, add or restate any number that is not
  written in the FACTS block. Every dollar amount, percentage and year you
  write must appear in FACTS exactly. If you are unsure, leave the number out.
- Search the web for the IRS (and, if a state is named, that state's revenue
  agency) pages describing the rules involved, and base the explanation on
  them. Prefer irs.gov and the state's own agency site.
- If the state rules are marked not verified or the state has no income tax,
  say so plainly; do not describe that state's rules from memory.
- 120 to 220 words, plain text, no headings, no bullet lists, no advice to
  take a particular action. End with one sentence noting this is general
  information, not tax advice.
"""

_MONEY = re.compile(r"\$\s?([0-9][0-9,]*(?:\.[0-9]+)?)")
_PERCENT = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s?%")


def facts_for(result: dict[str, Any]) -> dict[str, Any]:
    """The computed facts the model may talk about. No free text from the user."""
    state = result.get("state")
    first = result["federal"]["first_year"]
    return {
        "tax_year": result["tax_year"],
        "method": result["primary_label"],
        "federal_deduction_this_year": _fmt(first["total"]),
        "federal_breakdown": {
            "section_179": _fmt(first["section_179"]),
            "bonus_depreciation": _fmt(first["bonus"]),
            "section_168n_allowance": _fmt(first["special"]),
            "regular_macrs": _fmt(first["macrs"]),
        },
        "section_179_carryforward": _fmt(result["federal"]["carryforward"]),
        "assets": [
            {
                "class": a["class_label"],
                "placed_in_service": a["placed_in_service"][:7],
                "depreciable_basis": _fmt(a["business_basis"]),
                "business_use_percent": f"{float(a['business_use_pct']):g}%",
                "recovery_period_years": a["recovery_years"],
                "system_and_method": f"{a['system']} {a['method']}",
                "convention": {"HY": "half-year", "MQ": "mid-quarter", "MM": "mid-month"}[a["convention"]],
                "section_179": _fmt(a["section_179_allowed"]),
                "bonus_rate": f"{float(a['bonus_rate']):g}%",
                "bonus": _fmt(a["bonus"]),
                "deduction_this_year": _fmt(a["tax_year_deduction"]),
            }
            for a in result["assets"]
        ],
        "state": None if not state else {
            "name": state["name"],
            "status": state["status"],
            "message": state["message"],
            "state_deduction_this_year": _fmt(state.get("tax_year_deduction")),
            "state_adjustment_this_year": _fmt(state.get("tax_year_adjustment")),
            "rule_summary": state["rule"]["summary"] if state["status"] in ("computed", "provisional") else "",
        },
        "warnings": result["warnings"],
    }


def _fmt(value: Any) -> str | None:
    if value is None or value == "":
        return None
    amount = float(value)
    return f"-${-amount:,.0f}" if amount < 0 else f"${amount:,.0f}"


def _numbers(text: str) -> tuple[set[str], set[str]]:
    money = {m.replace(",", "").split(".")[0] for m in _MONEY.findall(text)}
    percent = {f"{float(p):g}" for p in _PERCENT.findall(text)}
    return money, percent


def unsupported_numbers(explanation: str, facts_text: str) -> list[str]:
    """Dollar amounts and percentages in ``explanation`` that ``facts_text`` lacks."""
    allowed_money, allowed_percent = _numbers(facts_text)
    money, percent = _numbers(explanation)
    return sorted({f"${m}" for m in money - allowed_money} | {f"{p}%" for p in percent - allowed_percent})


class DepreciationExplainer:
    def __init__(self, gemini: GeminiService, settings: Settings) -> None:
        self._gemini = gemini
        self._settings = settings

    def explain(self, result: dict[str, Any]) -> dict[str, Any]:
        if not self._gemini.enabled:
            return {
                "available": False,
                "text": "",
                "citations": [],
                "reason": "The explanation service is unavailable (Gemini is not configured). "
                          "The calculation above does not depend on it.",
            }
        facts = facts_for(result)
        facts_text = json.dumps(facts, indent=1)
        prompt = (
            "FACTS (computed by the calculator; the only numbers you may use):\n"
            f"{facts_text}\n\n"
            "Explain this result for someone with no tax background: what was deducted this year "
            "and why, how the rest is recovered over time, and - if a state is given - how the "
            "state treatment differs and reverses."
        )
        reason = ""
        for attempt in (1, 2):
            try:
                response = self._gemini.generate(
                    prompt=prompt,
                    task=TaskKind.CHAT_COMPLEX,
                    system_instruction=SYSTEM_INSTRUCTION,
                    context="depreciation_explanation",
                    google_search=True,
                    model=self._settings.assistant_model,
                    temperature=self._settings.assistant_temperature,
                )
            except Exception as exc:  # noqa: BLE001 - reported, never shown as an answer
                logger.warning("Depreciation explanation call failed (%s)", type(exc).__name__)
                reason = "The explanation service did not respond."
                continue
            text = (response.text or "").strip()
            if not text:
                reason = "The explanation came back empty."
                continue
            extra = unsupported_numbers(text, facts_text)
            if extra:
                # Logged by count only: the numbers are the user's figures.
                logger.info("Explanation attempt %d introduced %d unsupported number(s)", attempt, len(extra))
                reason = "The explanation stated figures the calculator did not produce, so it was withheld."
                continue
            if response.grounding.is_empty:
                reason = "No sources could be confirmed for the explanation, so it was withheld."
                continue
            annotated = citations.annotate(text, response.grounding)
            cited, renumber, _ = citations.build_citations(response.grounding, {"text": annotated})
            if not cited:
                reason = "No sources could be confirmed for the explanation, so it was withheld."
                continue
            return {
                "available": True,
                "text": citations.renumber_text(annotated, renumber),
                "citations": [c.to_dict() for c in cited],
                "reason": "",
            }
        return {"available": True, "text": "", "citations": [], "reason": reason or "No explanation could be produced."}
