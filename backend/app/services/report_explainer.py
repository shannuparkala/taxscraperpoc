"""Plain-English wording for a report's lines, written by a model and checked.

The engine computes; the model is only allowed to *describe*. One call per
report asks for a sentence or two per line, and every reply passes
``explanation_validator`` against that line's provenance before it is shown. A
reply that introduces any number the line did not state is rejected, and the
line keeps the engine's deterministic wording - rule 3: the model never
produces a figure, not even in a sentence.

What goes out is line labels, formulas and amounts: engine output, with no
names, no identifiers and no document text. It still travels through
``GeminiService``, whose egress guard checks the serialised payload first.

The model's replies are cached per workflow under a fingerprint of the lines
they describe, so the same return downloaded twice reads the same and costs
one call. Validation runs on every load, not only when the reply was fetched:
tightening the validator applies to replies already on disk.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.models.enums import TaskKind
from app.services.calculation_report import Explanation, engine_explanation
from app.services.explanation_validator import allowed_numbers, validate_explanation
from app.services.tax_engine.graph import NodeResult

if TYPE_CHECKING:
    from app.services.gemini_service import GeminiService

logger = get_logger(__name__)

#: Bump when the prompt changes, so cached replies to the old one are refetched.
PROMPT_VERSION = "1"

#: One call covers a return; a pathological one is cut here rather than sent whole.
MAX_LINES = 120

SYSTEM_INSTRUCTION = """\
You explain lines of a computed US individual tax return to a reader with no \
tax background.

For each line you are given its label from the form, its amount, the arithmetic \
the engine performed, and the figures it read. Write one or two short sentences \
saying what the line is and how its amount was reached.

Hard rules:
- Use only numbers listed in that line's "numbers". Never round, estimate, \
add, subtract or introduce any other number, dollar amount, percentage, year or \
line number. Never spell a number out in words.
- If a sentence would need any other number, write it without numbers.
- Do not give advice. Do not say whether the figure is right.

Reply with JSON only: {"explanations": {"<id>": "<text>", ...}}, one entry per \
line id you were given."""


@dataclass(frozen=True, slots=True)
class ExplainedBatch:
    explanations: dict[str, Explanation]
    #: For the report: which model wrote these, or why none did.
    note: str


def _line_payload(line: NodeResult, tax_year: int) -> dict[str, Any]:
    return {
        "id": line.node_id,
        "form": line.form,
        "line": line.line,
        "label": line.label,
        "amount": str(line.amount),
        "arithmetic": line.formula,
        "reads": [[input_id, None if amt is None else str(amt)] for input_id, amt in line.inputs],
        "reference": line.reference,
        "numbers": sorted({str(n) for n in _allowed(line, tax_year)}, key=lambda v: float(v)),
    }


def _allowed(line: NodeResult, tax_year: int) -> frozenset[Any]:
    """What a sentence about this line may cite: exactly its provenance."""
    return allowed_numbers(
        line.amount,
        [amount for _, amount in line.inputs],
        line.formula,
        line.label,
        line.form,
        line.line,
        line.reference,
        tax_year,
    )


class ReportExplainer:
    def __init__(self, gemini: GeminiService | None, cache_dir: Path) -> None:
        self._gemini = gemini
        self._cache_dir = cache_dir

    def explain(
        self, workflow_id: str, lines: Sequence[NodeResult], tax_year: int
    ) -> ExplainedBatch:
        lines = tuple(lines)[:MAX_LINES]
        if not lines:
            return ExplainedBatch({}, "no computed lines to explain")

        payload = [_line_payload(line, tax_year) for line in lines]
        fingerprint = hashlib.sha256(
            json.dumps({"v": PROMPT_VERSION, "lines": payload}, sort_keys=True).encode()
        ).hexdigest()

        raw, model = self._cached(workflow_id, fingerprint)
        note = f"written by {model}, each checked against the line's own figures"
        if raw is None:
            raw, model, note = self._fetch(payload)
            if raw is not None and model:
                self._store(workflow_id, fingerprint, raw, model)
                note = f"written by {model}, each checked against the line's own figures"

        out: dict[str, Explanation] = {}
        for line in lines:
            text = (raw or {}).get(line.node_id)
            if not isinstance(text, str):
                continue
            problems = validate_explanation(text, _allowed(line, tax_year))
            if problems:
                out[line.node_id] = Explanation(
                    engine_explanation(line), by="engine", rejected=tuple(problems)
                )
            else:
                out[line.node_id] = Explanation(text.strip(), by="model")
        return ExplainedBatch(out, note)

    # -------------------------------------------------------------- model

    def _fetch(
        self, payload: list[dict[str, Any]]
    ) -> tuple[dict[str, Any] | None, str, str]:
        if self._gemini is None or not self._gemini.enabled:
            return None, "", "the language model is off; the engine's own wording is shown"
        try:
            response = self._gemini.generate_json(
                prompt=json.dumps({"lines": payload}, indent=1),
                task=TaskKind.RETURN_EXPLANATION,
                system_instruction=SYSTEM_INSTRUCTION,
                context="calculation_report_explanations",
            )
        except Exception as exc:  # noqa: BLE001 - see below; type is logged and shown
            # The report must not fail for want of prose. The type is logged and
            # shown - trap 28: a swallowed failure here looks like a working
            # feature that simply chose the engine's wording every time.
            logger.warning(
                "Report explanations unavailable: %s", type(exc).__name__
            )
            return None, "", (
                f"the language model call failed ({type(exc).__name__}); the "
                "engine's own wording is shown"
            )
        if response.is_stub:
            return None, "", "the language model is off; the engine's own wording is shown"
        explanations = response.data.get("explanations")
        if not isinstance(explanations, dict):
            return None, "", "the language model's reply was not usable; the engine's own wording is shown"
        return explanations, response.model_name, ""

    # -------------------------------------------------------------- cache

    def _path(self, workflow_id: str) -> Path:
        return self._cache_dir / f"{workflow_id}.json"

    def _cached(self, workflow_id: str, fingerprint: str) -> tuple[dict[str, Any] | None, str]:
        path = self._path(workflow_id)
        if not path.exists():
            return None, ""
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, ""
        if stored.get("fingerprint") != fingerprint:
            return None, ""
        explanations = stored.get("explanations")
        if not isinstance(explanations, dict):
            return None, ""
        return explanations, str(stored.get("model") or "the language model")

    def _store(
        self, workflow_id: str, fingerprint: str, raw: dict[str, Any], model: str
    ) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._path(workflow_id).write_text(
                json.dumps(
                    {"fingerprint": fingerprint, "model": model, "explanations": raw},
                    indent=1,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Report explanations not cached: %s", type(exc).__name__)
