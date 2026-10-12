"""Deciding, before the answer, what kind of question this is and where it applies.

One small, fast call (``ASSISTANT_ROUTER_MODEL``, JSON schema, no tools)
classifies the question:

* **scope** - out-of-scope questions get fixed text and no grounded call;
* **answer_type** - which answer policy shapes the reply (a fact is one to
  three sentences; a notice gets numbered steps with deadlines; a case gets
  a summary and why it matters). A fixed eleven-section layout for every
  question was the most-reported problem with the previous assistant;
* **jurisdiction** - ``federal``, ``state`` or ``both``. A selected state
  used to be imposed on every question, so "summarize this Treasury release"
  with Delaware selected came back framed around Delaware. Now an explicitly
  federal question is answered federally and does not mention the selected
  state; a state or local question is answered for it; and a question that
  exists at both levels without saying which ("what are the income tax
  rates?") gets the federal answer and the selected state's, each labelled -
  treating it as federal-only dropped the state the user picked, which the
  first eval of this router showed. A *named* state is always a demand
  (CLAUDE.md rule 7).

The model's classification is a suggestion that deterministic rules can
override: a state named in the question, or words that are about state and
local tax ("sales tax", "my state", "here"), make the question
state-specific whatever the router said. If the router fails or is switched
off, the answer still goes ahead with the general policy and the old
jurisdiction behaviour (the selected state applies) - routing is an
optimisation, never a reason to refuse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.core.errors import LlmError
from app.core.logging import get_logger
from app.models.enums import TaskKind
from app.services.assistant import state_registry
from app.services.gemini_service import GeminiService, parse_json_response
from app.services.llm_meter import MeterScope

logger = get_logger(__name__)

AnswerType = Literal["fact", "how_to", "scenario", "case_news", "dispute", "multi_state", "clarify"]

#: The policy used when the router could not run.
GENERAL = "general"

#: Words that make a question about state or local tax whatever the router
#: says. Kept to unambiguous ones: "resident" alone is federal too
#: (nonresident aliens), so it is not here.
_STATE_WORDS = re.compile(
    r"\b(?:state|states'|state's|local|city|county|municipal|municipality|borough|"
    r"sales[ -]tax|use[ -]tax|property[ -]tax|franchise[ -]tax|gross[ -]receipts|"
    r"here|my state|this state|in-state|out-of-state|reciprocity|withholding allowance certificate)\b",
    re.IGNORECASE,
)
#: "state" in phrases that are federal: "United States", "state of the
#: union", "statement", "state(s) of emergency" never mean a state's tax law.
_FEDERAL_STATE_PHRASES = re.compile(
    r"\bunited states\b|\bstate of emergency\b|\bstate of the union\b|\bstate-of-the-art\b",
    re.IGNORECASE,
)


Jurisdiction = Literal["federal", "state", "both"]


class _RouterReply(BaseModel):
    scope: Literal["us_tax", "non_tax", "non_us_tax", "evasion_request"]
    answer_type: AnswerType
    jurisdiction: Jurisdiction
    clarifying_question: str = Field(default="", max_length=300)


@dataclass(frozen=True, slots=True)
class Route:
    scope: str = "us_tax"
    answer_type: str = GENERAL
    #: ``None`` when unknown (router off or failed): the selected state applies.
    jurisdiction: str | None = None
    clarifying_question: str = ""
    #: Why this route: "router", "router+override", "fallback".
    source: str = "fallback"

    @property
    def state_specific(self) -> bool | None:
        """Whether a selected state applies; ``None`` when unknown."""
        if self.jurisdiction is None:
            return None
        return self.jurisdiction != "federal"

    @property
    def federal_too(self) -> bool:
        """Answer both levels: the question does not say which it means."""
        return self.jurisdiction == "both"


@cache
def _system() -> str:
    return (Path(__file__).parent / "prompts" / "router_system.md").read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    schema = _RouterReply.model_json_schema()
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        if isinstance(prop, dict):
            prop.pop("title", None)
            prop.pop("default", None)
    return schema


class QuestionRouter:
    def __init__(self, gemini: GeminiService, settings: Settings) -> None:
        self._gemini = gemini
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self._settings.assistant_router_model) and self._gemini.enabled

    def route(
        self,
        *,
        question: str,
        selected_state: str | None,
        history: list[tuple[str, str]],
        meter_scope: MeterScope | None = None,
    ) -> Route:
        """Classify ``question`` (already masked if the user asked for it)."""
        named = state_registry.find_states(question)
        if not self.enabled:
            return apply_overrides(Route(), question=question, named=named, selected=selected_state)

        selected = state_registry.get(selected_state)
        conversation = "\n".join(
            f"{'User' if role == 'user' else 'Assistant'}: {text[:400]}" for role, text in history[-2:]
        )
        prompt = (
            f"Selected state on the map: {selected.name if selected else 'none'}\n"
            + (f"Earlier conversation:\n{conversation}\n" if conversation else "Earlier conversation: none\n")
            + f"Question:\n<<<\n{question.strip()}\n>>>"
        )
        try:
            response = self._gemini.generate(
                prompt=prompt,
                task=TaskKind.CHAT_SIMPLE,
                system_instruction=_system(),
                context="assistant_router",
                response_json_schema=_schema(),
                model=self._settings.assistant_router_model,
                temperature=0.0,
                thinking_level=self._settings.assistant_router_thinking_level or None,
                meter_scope=meter_scope,
            )
            reply = _RouterReply.model_validate(parse_json_response(response.text or "{}"))
        except (ValidationError, ValueError, LlmError) as exc:
            # The provider failed or replied with something unusable: answer
            # anyway with the general policy. Deliberately narrow - a broad
            # except here would also swallow our own bugs and make a dead
            # router look like a working one (CLAUDE.md traps 25 and 28).
            # EgressBlockedError is not caught: the answer call would be
            # blocked by the same guard, and the service says so.
            logger.warning("assistant.router unusable (%s); using the general policy", type(exc).__name__)
            return apply_overrides(Route(), question=question, named=named, selected=selected_state)

        route = Route(
            scope=reply.scope,
            answer_type=reply.answer_type,
            jurisdiction=reply.jurisdiction,
            clarifying_question=reply.clarifying_question.strip(),
            source="router",
        )
        return apply_overrides(route, question=question, named=named, selected=selected_state)


def apply_overrides(route: Route, *, question: str, named: list[str], selected: str | None) -> Route:
    """Deterministic rules that beat the router's guess."""
    jurisdiction = route.jurisdiction
    answer_type = route.answer_type
    source = route.source
    clarifying = route.clarifying_question

    if named:
        # A named state is a demand (rule 7).
        if jurisdiction != "state":
            jurisdiction, source = "state", _overridden(source)
        if len(named) > 1 and answer_type in (GENERAL, "fact", "how_to"):
            answer_type, source = "multi_state", _overridden(source)
    elif selected and jurisdiction == "federal" and _mentions_state_tax(question):
        jurisdiction, source = "state", _overridden(source)
    elif not selected and jurisdiction == "both":
        # "Both" means federal and the selected state; with none selected
        # there is only the federal answer (and a follow-up asking which).
        jurisdiction = "federal"

    if answer_type == "clarify" and not clarifying:
        # Nothing to ask: answer instead, with the general policy.
        answer_type, source = GENERAL, _overridden(source)

    return Route(
        scope=route.scope,
        answer_type=answer_type,
        jurisdiction=jurisdiction,
        clarifying_question=clarifying,
        source=source,
    )


def _mentions_state_tax(question: str) -> bool:
    return _STATE_WORDS.search(_FEDERAL_STATE_PHRASES.sub(" ", question)) is not None


def _overridden(source: str) -> str:
    return source if source.endswith("+override") else f"{source}+override"
