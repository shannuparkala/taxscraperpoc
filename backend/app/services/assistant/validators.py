"""Checks every generated answer must pass before it is kept.

The answer streams to the reader while it is written, so these run when the
stream ends. A draft that fails is withdrawn from the screen and regenerated
once with the failures spelled out; a second failure shows a safe fallback -
never the failed draft. (Owner's decision 2026-10-09, "Option A": stream
first, verify at the end, withdraw on failure. Grounding metadata arrives on
the stream's last chunk only, so there is no earlier point to check it.)

* **Grounding** - an in-scope answer has at least one source from Google
  Search grounding. No sources means the model answered from memory.
* **Tax year** - the year an answer is for is decided before the model runs
  (``prompt_builder.resolve_tax_year``). An answer whose META year is a
  different year is regenerated unless it declares ``fallback=yes`` - the
  requested year's figures are not published, an earlier year's are given
  and the first sentence says so - and the server then adds its own notice
  (owner's decision 2026-10-11: never present 2025 figures as 2026). An
  answer that states a figure but *no* year is still only flagged
  (``missing_tax_year``), not regenerated: in the first eval of the router,
  four regenerations for this alone cost 15-30 s each and produced the same
  answer with a year added.
* **Arithmetic** - every calculation step the answer shows adds up, and the
  first sentence gives the same result as the total line
  (``arithmetic.check``; owner's decision 2026-10-11: regenerate once, then
  the fallback). It recomputes the answer's own numbers only.
* **State consistency** - the answer names every state the jurisdiction
  context requires, does not build itself on a state it was not asked about,
  gives each state of a multi-state answer its own heading, and does not
  pick a state on its own when none applies.

Issue messages are written here, never copied from model output, because
they are fed back into the regeneration prompt.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from app.services.assistant import arithmetic, state_registry
from app.services.assistant.answer_schema import Scope
from app.services.assistant.answer_text import Meta, has_figures
from app.services.assistant.prompt_builder import JurisdictionContext, TaxYearContext
from app.services.gemini_service import Grounding

_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.*)$", re.MULTILINE)
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    message: str


@dataclass(slots=True)
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def codes(self) -> list[str]:
        return [issue.code for issue in self.issues]

    def messages(self) -> list[str]:
        return [issue.message for issue in self.issues]


def validate(
    text: str,
    *,
    scope: str,
    grounding: Grounding,
    context: JurisdictionContext,
    meta: Meta | None = None,
    year: TaxYearContext | None = None,
) -> ValidationReport:
    report = ValidationReport()
    if not text.strip():
        report.issues.append(Issue("empty_answer", "The answer was empty."))
        return report

    if scope in (Scope.NON_TAX.value, Scope.NON_US_TAX.value):
        # Out-of-scope replies are replaced with fixed text by the formatter,
        # so there is nothing in them left to check.
        return report

    if scope == Scope.EVASION_REQUEST.value:
        # An evasion refusal is checked for its sources only: it explains why
        # not and what is legal instead, and is not obliged to recite the state.
        report.issues.extend(check_grounding(grounding))
        return report

    report.issues.extend(check_grounding(grounding))
    report.issues.extend(check_states(text, context))
    if meta is not None and year is not None:
        report.issues.extend(check_tax_year(meta, year))
    report.issues.extend(check_arithmetic(text))
    return report


def check_arithmetic(text: str) -> list[Issue]:
    """Every step the answer shows adds up, and the lead states the same
    result as the total line (``arithmetic``). It recomputes only the
    answer's own expressions; it never supplies a figure."""
    return [Issue(finding.code, finding.message) for finding in arithmetic.check(text)]


def check_grounding(grounding: Grounding) -> list[Issue]:
    if grounding.is_empty:
        return [
            Issue(
                "ungrounded",
                "The answer was not grounded: use Google Search and base every "
                "fact on what the search returns.",
            )
        ]
    return []


def check_tax_year(meta: Meta, year: TaxYearContext) -> list[Issue]:
    """The answer's figures are for the year it had to answer for.

    An earlier year is allowed only when declared (``fallback=yes``): that is
    the honest answer when an agency has not published the year's figures,
    and the formatter says so on screen. An answer with no year at all is not
    this check's business (``missing_tax_year``).
    """
    if not year.enforced or not meta.years or year.year in meta.years:
        return []
    assert year.year is not None
    if meta.fallback and max(meta.years) < year.year:
        return []
    found = ", ".join(map(str, meta.years))
    return [
        Issue(
            "wrong_tax_year",
            f"The answer had to be for tax year {year.year} but gave figures for {found}. "
            f"Give {year.year} figures. If the agency has not published {year.year} figures "
            "for this, say so in the first sentence, give the latest published year's, and "
            "write fallback=yes in the META line.",
        )
    ]


def fallback_year(meta: Meta, year: TaxYearContext) -> int | None:
    """The earlier year a declared fallback answer is for, or None."""
    if not (year.enforced and meta.fallback and meta.years) or year.year in meta.years:
        return None
    assert year.year is not None
    return max(meta.years) if max(meta.years) < year.year else None


def missing_tax_year(text: str, tax_year: str) -> bool:
    """The answer states a figure but not which tax year it is for."""
    return not tax_year and has_figures(text)


def check_states(text: str, context: JurisdictionContext) -> list[Issue]:
    issues: list[Issue] = []
    framed = _framed_states(text)

    if context.allowed is None:
        # No state applies: the model must not build the answer on one.
        if framed:
            issues.append(
                Issue(
                    "guessed_state",
                    "No state applies to this question, but the answer is built on "
                    + ", ".join(_name(c) for c in sorted(framed))
                    + ". Answer the federal rule; if state treatment matters, say "
                    "that it varies and offer to look up the reader's state.",
                )
            )
        return issues

    mentioned = set(state_registry.find_states(text))
    for code in context.required:
        if code not in mentioned and not _mentions_code(text, code):
            issues.append(
                Issue(
                    "state_not_named",
                    f"The answer never names {_name(code)}. Say explicitly that "
                    f"it applies to {_name(code)}.",
                )
            )

    stray = sorted(framed - context.allowed)
    if stray:
        issues.append(
            Issue(
                "wrong_state",
                "The answer is built on the rules of "
                + ", ".join(_name(c) for c in stray)
                + ", which the question is not about. Answer for "
                + ", ".join(_name(c) for c in context.required)
                + " only.",
            )
        )

    lead = _lead(text)
    lead_states = set(state_registry.find_states(lead))
    if lead_states and not lead_states & set(context.required) and lead_states - context.allowed:
        issues.append(
            Issue(
                "wrong_state",
                "The opening answer is about "
                + ", ".join(_name(c) for c in sorted(lead_states))
                + " instead of "
                + ", ".join(_name(c) for c in context.required)
                + ".",
            )
        )

    if context.is_multi_state:
        headed = {code for heading in _HEADING.findall(text) for code in state_registry.find_states(heading)}
        missing = [c for c in context.required if c not in headed]
        if missing:
            issues.append(
                Issue(
                    "multi_state_unlabeled",
                    "Give each state its own `###` section headed with its name; "
                    "missing: " + ", ".join(_name(c) for c in missing) + ".",
                )
            )
    return issues


def _framed_states(text: str) -> set[str]:
    """States the answer is built on: named in a heading, or in two or more sentences.

    A single passing mention ("unlike Nevada, ...") is contrast, not framing.
    """
    framed = {code for heading in _HEADING.findall(text) for code in state_registry.find_states(heading)}
    counts: Counter[str] = Counter()
    for sentence in _SENTENCES.split(text):
        counts.update(set(state_registry.find_states(sentence)))
    framed |= {code for code, count in counts.items() if count >= 2}
    return framed


def _lead(text: str) -> str:
    for block in re.split(r"\n[ \t]*\n", text):
        if block.strip() and not _HEADING.match(block.strip()):
            return block
    return ""


def _mentions_code(text: str, code: str) -> bool:
    return re.search(rf"(?<![A-Za-z]){code}(?![A-Za-z])", text) is not None


def _name(code: str) -> str:
    state = state_registry.get(code)
    return state.name if state else code
