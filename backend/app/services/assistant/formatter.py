"""Builds the response the UI renders, for every outcome.

Every reply - an answer, an out-of-scope redirect, a safe fallback, an outage
- has the same shape, so the UI has one renderer and the stored payload one
schema. Text the reader sees is assembled here:

* model text has anything citation-like stripped (``answer_text.clean``):
  the only sources shown are grounded citations, built in ``citations``;
* the disclaimer, the out-of-scope wording, the fallback wording and the
  state-change notice are fixed server text, never model output;
* official agency links come from the state registry, are labelled as such,
  and are never presented as citations.

Payloads produced here are still *masked*. The service stores them as they
are and un-masks a copy for display.
"""

from __future__ import annotations

from typing import Any

from app.services.assistant import state_registry
from app.services.assistant.answer_schema import DISCLAIMER, JurisdictionLevel, Scope
from app.services.assistant.answer_text import first_paragraph
from app.services.assistant.citations import Citation
from app.services.assistant.prompt_builder import JurisdictionContext

STATUS_ANSWERED = "answered"
STATUS_DECLINED = "declined"
STATUS_OUT_OF_SCOPE = "out_of_scope"
STATUS_FALLBACK = "fallback"
STATUS_UNAVAILABLE = "unavailable"
STATUS_CLARIFY = "clarify"

_NON_TAX = (
    "I can only help with US tax questions - federal, state and local tax, "
    "business tax, and tax notices, audits and disputes. Ask me one of those "
    "and I'll look it up."
)
_NON_US = (
    "I only cover US tax law - federal, state, local and US territories. For "
    "another country's tax rules, its own tax authority or a local tax adviser "
    "is the right source."
)
_UNSOURCED_NOTE = (
    "Figures marked [?] were not matched to a specific passage in the sources "
    "below. Check them there before relying on them."
)
_NO_YEAR_NOTE = (
    "This answer gives figures without saying which tax year they are for. "
    "Check the year on the sources below before relying on them."
)
_SENSITIVE_NOTE = (
    "Please don't share Social Security numbers, bank or card numbers, or "
    "other identifiers here. They were hidden before your question was sent, "
    "and you never need them to get an answer."
)


def answered(
    markdown: str,
    *,
    scope: str,
    answer_type: str,
    context: JurisdictionContext,
    tax_year: str,
    tax_year_assumed: bool,
    follow_ups: list[str],
    citations: list[Citation],
    search_queries: list[str],
    search_suggestions_html: str,
    sensitive_identifier: bool,
    unsourced_figures: int = 0,
    tax_year_missing: bool = False,
    tax_year_requested: int | None = None,
    tax_year_fallback: int | None = None,
) -> dict[str, Any]:
    """The payload for an answer that passed every check.

    ``markdown`` is the cleaned answer with display-numbered source markers.
    """
    if scope in (Scope.NON_TAX.value, Scope.NON_US_TAX.value):
        return out_of_scope(Scope(scope), context=context)

    states = [{"code": code, "name": _name(code)} for code in context.required]
    notes = [_SENSITIVE_NOTE] if sensitive_identifier else []
    if unsourced_figures:
        notes.append(_UNSOURCED_NOTE)
    if tax_year_missing:
        notes.append(_NO_YEAR_NOTE)
    year_note = ""
    if tax_year_fallback is not None and tax_year_requested is not None:
        # Written here, not by the model: the one sentence that must never be
        # missing when an earlier year's figures answer a later year's question.
        year_note = (
            f"No {tax_year_requested} figures were found for this question, so this answer "
            f"uses {tax_year_fallback} figures. Check whether {tax_year_requested} figures "
            "have been published before relying on them."
        )
        notes.insert(0, year_note)
    return _base(
        status=STATUS_DECLINED if scope == Scope.EVASION_REQUEST.value else STATUS_ANSWERED,
        context=context,
        scope=scope or Scope.US_TAX.value,
        category=answer_type or "other",
        answer_type=answer_type,
        jurisdiction_level=_level(states),
        states=states,
        tax_year=tax_year,
        tax_year_assumed=tax_year_assumed and bool(tax_year),
        tax_year_note=year_note,
        tax_year_requested=tax_year_requested,
        tax_year_fallback=tax_year_fallback is not None,
        quick_answer=first_paragraph(markdown),
        answer_markdown=markdown,
        considerations=notes,
        follow_up_questions=follow_ups,
        unsourced_figures=unsourced_figures,
        tax_year_missing=tax_year_missing,
        confidence="high" if not (unsourced_figures or tax_year_missing or year_note) else "medium",
        citations=[c.to_dict() for c in citations],
        search_queries=search_queries,
        search_suggestions_html=search_suggestions_html,
    )


def clarify(question: str, *, context: JurisdictionContext) -> dict[str, Any]:
    """A reply that only asks the one thing the answer depends on."""
    return _base(
        status=STATUS_CLARIFY,
        context=context,
        category="clarify",
        answer_type="clarify",
        quick_answer=question,
        answer_markdown=question,
        states=[],
        jurisdiction_level=JurisdictionLevel.NONE.value,
        official_links=[],
    )


def out_of_scope(scope: Scope, *, context: JurisdictionContext) -> dict[str, Any]:
    return _base(
        status=STATUS_OUT_OF_SCOPE,
        context=context,
        scope=scope.value,
        category="out_of_scope",
        quick_answer=_NON_US if scope is Scope.NON_US_TAX else _NON_TAX,
        states=[],
        jurisdiction_level=JurisdictionLevel.NONE.value,
        official_links=[],
    )


def fallback(issue_codes: list[str], *, context: JurisdictionContext) -> dict[str, Any]:
    """What is shown when two attempts both failed validation."""
    names = _names(context.required)
    if "official_sources_unavailable" in issue_codes:
        quick = (
            "I couldn't read the current official material needed to verify this calculation, "
            "so I haven't calculated a tax amount."
        )
    elif {"ungrounded"} >= set(issue_codes):
        quick = (
            "I couldn't confirm this from an authoritative source, so I'm not "
            "going to guess."
        )
    elif set(issue_codes) & {
        "missing_state", "wrong_state", "state_not_named",
        "multi_state_unlabeled", "guessed_state", "unknown_state",
    }:
        quick = (
            f"I couldn't produce an answer I could verify applies to {names}, "
            "so I've stopped rather than risk giving you another state's rules."
            if names
            else "I couldn't produce an answer I could verify, so I've stopped "
            "rather than guess which state's rules apply."
        )
    else:
        quick = (
            "I couldn't produce an answer I could verify this time, so I'm not "
            "showing one. Please try again, or rephrase the question."
        )
    why = (
        "Every answer is checked for real sources, a stated tax year, and the "
        "right jurisdiction before it is shown. This one did not pass twice."
    )
    if "official_sources_unavailable" in issue_codes:
        why = "A missing or unreadable source does not mean the requested year's rules are unpublished. Please try again."
    if context.required:
        why += " The official agency pages below are the authoritative place to check."
    return _base(
        status=STATUS_FALLBACK,
        context=context,
        quick_answer=quick,
        why=why,
        confidence="low",
        validation_issues=list(dict.fromkeys(issue_codes)),
    )


def unavailable(message: str, *, context: JurisdictionContext) -> dict[str, Any]:
    return _base(
        status=STATUS_UNAVAILABLE,
        context=context,
        quick_answer=message,
        confidence="low",
    )


# ---------------------------------------------------------------------------


def _base(*, status: str, context: JurisdictionContext, **values: Any) -> dict[str, Any]:
    states = values.pop("states", None)
    if states is None:
        states = [{"code": code, "name": _name(code)} for code in context.required]
    payload: dict[str, Any] = {
        "status": status,
        "scope": "us_tax",
        "category": "other",
        "selected_state": context.selected,
        "state_change_notice": state_change_notice(context),
        "jurisdiction_level": (
            JurisdictionLevel.STATE.value if context.required else JurisdictionLevel.FEDERAL.value
        ),
        "states": states,
        "spans_states": len(states) > 1,
        "tax_year": "",
        "tax_year_assumed": False,
        "tax_year_note": "",
        "tax_year_requested": None,
        "tax_year_fallback": False,
        "quick_answer": "",
        "answer_markdown": "",
        "answer_type": "",
        "search_queries": [],
        "unsourced_figures": 0,
        "from_cache": False,
        "tax_year_missing": False,
        "why": "",
        "example": "",
        "state_sections": [],
        "facts_relied_on": [],
        "assumptions": [],
        "references": [],
        "next_steps": [],
        "considerations": [],
        "recent_or_pending_changes": [],
        "unverified_points": [],
        "follow_up_questions": [],
        "professional_help": {"recommended": False, "reason": ""},
        "confidence": "medium",
        "citations": [],
        "section_citations": {},
        "search_suggestions_html": "",
        "official_links": _official_links(context),
        "validation_issues": [],
        "disclaimer": DISCLAIMER,
    }
    payload.update(values)
    return payload


def _level(states: list[dict[str, str]]) -> str:
    if len(states) > 1:
        return JurisdictionLevel.MULTI_STATE.value
    if states:
        return JurisdictionLevel.FEDERAL_AND_STATE.value
    return JurisdictionLevel.FEDERAL.value


def state_change_notice(context: JurisdictionContext) -> str:
    if not context.state_changed:
        return ""
    before = _name(context.previous_selected) if context.previous_selected else "federal (no state)"
    after = _name(context.selected) if context.selected else "federal (no state)"
    return f"This answer now applies to {after} - you switched from {before}."


def _official_links(context: JurisdictionContext) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for code in context.required:
        state = state_registry.get(code)
        if state is None:
            continue
        for agency in state.agencies:
            links.append({"state_code": code, "label": agency.name, "url": agency.url})
    return links


def _name(code: str | None) -> str:
    state = state_registry.get(code)
    return state.name if state else (code or "")


def _names(codes: tuple[str, ...]) -> str:
    names = [_name(code) for code in codes]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]
