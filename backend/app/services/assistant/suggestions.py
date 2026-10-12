"""Starter questions shown above the composer.

Deterministic, and derived from structure only: the selected state's
features (from the registry), whether a document is attached, and whether a
conversation is under way. No figures, so nothing here can go stale.
"""

from __future__ import annotations

from app.services.assistant import state_registry
from app.services.assistant.state_registry import Feature

_OPENING = (
    "What is the standard deduction for my filing status this year?",
    "I got an IRS CP2000 notice. What should I do?",
    "When does a remote seller have to collect sales tax in another state?",
    "Can I deduct a home office if I'm self-employed?",
)

_WITH_DOCUMENT = (
    "Summarize this document in plain English.",
    "What action is required, and by when?",
    "What should I be concerned about here?",
)

_FOLLOW_UP = (
    "What would change this answer?",
    "What do I need to do next?",
    "Explain that more simply.",
)


def suggestions_for(
    *,
    state_code: str | None = None,
    has_attachments: bool = False,
    has_history: bool = False,
    limit: int = 4,
) -> list[str]:
    picked: list[str] = []
    if has_attachments:
        picked.extend(_WITH_DOCUMENT)
    if has_history:
        picked.extend(_FOLLOW_UP)

    state = state_registry.get(state_code)
    if state is not None:
        picked.extend(_for_state(state))
    picked.extend(_OPENING)
    return list(dict.fromkeys(picked))[:limit]


def _for_state(state: state_registry.Jurisdiction) -> list[str]:
    name = state.name
    out: list[str] = []
    if Feature.NO_WAGE_INCOME_TAX in state.features:
        out.append(f"{name} has no income tax on wages - what state taxes do I still owe?")
    else:
        out.append(f"Do I have to file a {name} return if I moved out mid-year?")
    if state.business_tax:
        out.append(f"Who has to pay the {state.business_tax}?")
    if Feature.LOCAL_INCOME_TAX in state.features:
        out.append(f"Do I owe local income tax in {name}?")
    if Feature.COMMUNITY_PROPERTY in state.features:
        out.append(f"How does {name} community property law affect married filing separately?")
    if state.has_statewide_sales_tax:
        out.append(f"When does an out-of-state seller have to collect {name} sales tax?")
    out.append(f"I received a notice from the {state.agency.name}. What are my options?")
    return out
