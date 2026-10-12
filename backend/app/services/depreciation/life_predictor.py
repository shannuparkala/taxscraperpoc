"""Predicting each asset's life (MACRS class) from its description.

This is the only place a model touches the additions report, and it decides
one thing: which of the engine's asset classes an asset belongs to, which
fixes its recovery period. Every amount is computed afterwards by the engine
from that class (CLAUDE.md rule 9) - the model never sees a cost, a date or
an asset number, and nothing it writes is used as a figure.

In order, per asset:

1. **A life already in the file** is the preparer's decision: it is mapped to
   a class deterministically, with no model call.
2. **The model** classifies the rest, from the redacted description, choosing
   only from the engine's classes (a JSON schema enum).
3. **A period the description states** ("(39-Year)") beats the model when
   they disagree - the preparer wrote it down.
4. **Nothing invented on failure.** With the model unavailable or its reply
   unusable, the asset is left unclassified for the user to choose; a guessed
   life would flow straight into every figure on the report.

SECURITY: descriptions are client data. Identifiers and names are replaced
with ``[REDACTED]`` before anything is sent (the prose PII detector, the same
precise profile as the assistant's ``/mask``), and the call goes through
``GeminiService`` and its egress guard like every other.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.core.errors import EgressBlockedError, LlmError
from app.core.logging import get_logger
from app.models.enums import TaskKind
from app.services.assistant.masking import chat_spans
from app.services.depreciation.rules import DepreciationRules
from app.services.gemini_service import GeminiService, parse_json_response
from app.services.llm_meter import MeterScope
from app.services.pii_detection_service import DetectionConfig, PiiDetectionService

logger = get_logger(__name__)

#: Descriptions per model call. One call per batch, in order.
BATCH = 60
#: Classes the model may choose. Qualified production property needs an
#: election and construction dates no description carries.
_EXCLUDED = frozenset({"qualified_production"})
_OTHER_YEARS = ("3", "5", "7", "10", "15", "20")
#: "(39-Year)", "15-Year", "5 yr", "27.5-year".
_STATED_PERIOD = re.compile(r"\b(\d{1,2}(?:\.5)?)[ -]?(?:year|yr)s?\b", re.IGNORECASE)
_GVWR = re.compile(r"GVWR[^0-9]{0,6}([\d,]{4,6})|([\d,]{4,6})\s*(?:lb|lbs|pounds)?\s*GVWR", re.IGNORECASE)
_LAND = re.compile(r"\bland improvement|parking|paving|sidewalk|fenc|landscap|curb\b", re.IGNORECASE)
_VEHICLE = re.compile(r"\b(vehicle|truck|van|car|pickup|suv)\b", re.IGNORECASE)
_FURNITURE = re.compile(r"\b(furniture|fixture|desk|chair|table|cabinet)", re.IGNORECASE)
_TECH = re.compile(r"\b(computer|laptop|tablet|copier|printer|server|technology|office equipment|phone)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class LifePrediction:
    asset_class: str | None
    #: Only for the "other" class.
    recovery_years: str | None
    #: The recovery period this classification gives ("5", "27.5", ...).
    life: str | None
    #: "file" | "description" | "ai" | "none"
    source: str
    confidence: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_class": self.asset_class,
            "recovery_years": self.recovery_years,
            "life": self.life,
            "source": self.source,
            "confidence": self.confidence,
            "reason": self.reason,
        }


class _Item(BaseModel):
    index: int
    asset_class: str
    recovery_years: str = ""
    confidence: str = "medium"
    reason: str = Field(default="", max_length=300)


class _Reply(BaseModel):
    assets: list[_Item]


@cache
def _system() -> str:
    return (Path(__file__).parent / "prompts" / "life_system.md").read_text(encoding="utf-8")


class LifePredictor:
    def __init__(self, gemini: GeminiService, settings: Settings, rules: DepreciationRules) -> None:
        self._gemini = gemini
        self._settings = settings
        self._rules = rules
        self._detector = PiiDetectionService(
            DetectionConfig(mask_organizations=False, enable_columnar=False, recase_all_caps=False)
        )

    @property
    def available(self) -> bool:
        return self._gemini.enabled

    def predict(
        self,
        descriptions: list[str],
        given_lives: list[str | None],
        *,
        tax_year: int,
        jurisdiction: str | None = None,
        business_activity: str = "",
        meter_scope: MeterScope | None = None,
    ) -> tuple[list[LifePrediction], str]:
        """One prediction per description, and a message when the model could not help.

        Runs only once the tax year and jurisdiction are chosen (the import's
        first step), against the asset classes the rules hold for that year.
        ``jurisdiction`` is the state, or None for federal only. The class is
        the federal MACRS class either way: in this calculator's rule data no
        state changes a recovery period - states differ in Section 179 and
        bonus, which the report applies afterwards.
        """
        self._rules.require_year(tax_year)
        if jurisdiction is not None and self._rules.state(jurisdiction) is None:
            raise ValueError(f"Unsupported jurisdiction {jurisdiction}")
        out: list[LifePrediction | None] = [None] * len(descriptions)
        ask: list[int] = []
        for index, (description, given) in enumerate(zip(descriptions, given_lives)):
            if given:
                out[index] = self._from_life(given, description, source="file",
                                             reason="Life taken from the uploaded file.")
            else:
                ask.append(index)

        message = ""
        if ask and not self.available:
            message = "AI life prediction is not available (no Gemini API key), so choose each life yourself."
        elif ask:
            for start in range(0, len(ask), BATCH):
                batch = ask[start : start + BATCH]
                try:
                    replies = self._ask(batch, descriptions, business_activity, tax_year, meter_scope)
                except EgressBlockedError:
                    message = ("Some descriptions could not be sent safely, so their lives were not "
                               "predicted; choose them yourself.")
                    continue
                except (LlmError, ValidationError, ValueError) as exc:
                    logger.warning("depreciation.life batch failed (%s)", type(exc).__name__)
                    message = "AI life prediction failed for some assets; choose their lives yourself."
                    continue
                for index, item in replies.items():
                    out[index] = self._checked(item, descriptions[index])

        filled = [
            p if p is not None else LifePrediction(None, None, None, "none", "", "Choose the life.")
            for p in out
        ]
        logger.info(
            "depreciation.life %s",
            {"assets": len(descriptions), "asked": len(ask),
             "by_source": {s: sum(1 for p in filled if p.source == s) for s in ("file", "ai", "description", "none")}},
        )
        return filled, message

    # ------------------------------------------------------------------ model

    def _ask(
        self, batch: list[int], descriptions: list[str], activity: str, tax_year: int,
        scope: MeterScope | None,
    ) -> dict[int, _Item]:
        classes = [key for key in self._rules.classes if key not in _EXCLUDED]
        listing = "\n".join(
            f"- `{c.key}`: {c.label} ({c.recovery_years or 'choose 3/5/7/10/15/20'}-year)"
            + (f" - {c.note}" if c.note else "")
            for c in self._rules.classes.values()
            if c.key in classes
        )
        lines = "\n".join(f"{n}. {self._redact(descriptions[i])}" for n, i in enumerate(batch, start=1))
        business = (
            f"# Business type (given by the user)\n\n{self._redact(activity)}\n\n" if activity.strip()
            else "# Business type\n\nNot given: infer it from the asset list as a whole.\n\n"
        )
        prompt = (
            f"# Tax year\n\n{tax_year} additions: assets placed in service during {tax_year}.\n\n"
            f"# Asset classes\n\n{listing}\n\n{business}# Assets\n\n<<<ASSETS\n{lines}\nASSETS>>>\n\n"
            "Classify every asset. `index` is the number before the description."
        )
        schema = {
            "type": "object",
            "properties": {
                "assets": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer"},
                            "asset_class": {"type": "string", "enum": classes},
                            "recovery_years": {"type": "string", "enum": ["", *_OTHER_YEARS]},
                            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                            "reason": {"type": "string"},
                        },
                        "required": ["index", "asset_class", "recovery_years", "confidence", "reason"],
                    },
                }
            },
            "required": ["assets"],
        }
        response = self._gemini.generate(
            prompt=prompt,
            task=TaskKind.CHAT_SIMPLE,
            system_instruction=_system(),
            context="depreciation_life",
            response_json_schema=schema,
            model=self._settings.depreciation_life_model,
            temperature=0.0,
            thinking_level=self._settings.depreciation_life_thinking_level or None,
            meter_scope=scope,
        )
        reply = _Reply.model_validate(parse_json_response(response.text or "{}"))
        return {batch[item.index - 1]: item for item in reply.assets if 1 <= item.index <= len(batch)}

    def _redact(self, description: str) -> str:
        """SECURITY: identifiers and names out before the description leaves."""
        spans, _ = chat_spans(description, self._detector.detect(description))
        text = description
        for span in sorted(spans, key=lambda s: s.start, reverse=True):
            text = text[: span.start] + "[REDACTED]" + text[span.end :]
        return " ".join(text.split())[:300]

    # ------------------------------------------------------------- checking

    def _checked(self, item: _Item, description: str) -> LifePrediction:
        cls = self._rules.classes.get(item.asset_class)
        if cls is None or cls.key in _EXCLUDED:
            return LifePrediction(None, None, None, "none", "", "Choose the life.")
        years = None
        if cls.recovery_years is None:
            years = item.recovery_years if item.recovery_years in cls.allowed_recovery_years else None
            if years is None:
                return LifePrediction(None, None, None, "none", "", "Choose the life.")
        life = cls.recovery_years or years
        stated = _stated_period(description)
        if stated and stated != life:
            return self._from_life(
                stated, description, source="description",
                reason=f"The description states {stated}-year property.",
            )
        return LifePrediction(cls.key, years, life, "ai", item.confidence, item.reason.strip())

    def _from_life(self, life: str, description: str, *, source: str, reason: str) -> LifePrediction:
        """A class for a life someone already decided, chosen without a model."""
        cls, years = class_for_life(life, description)
        if cls is None:
            return LifePrediction(None, None, None, "none", "", f"No asset class has a {life}-year life; choose one.")
        confidence = "high"
        if cls == "other" and _VEHICLE.search(description) and life == "5":
            confidence, reason = "medium", reason + " Check the vehicle's weight (GVWR)."
        return LifePrediction(cls, years, life, source, confidence, reason)


def class_for_life(life: str, description: str) -> tuple[str | None, str | None]:
    """(class, recovery years for "other") for a given life. No model."""
    try:
        value = Decimal(str(life).strip())
    except ArithmeticError:
        return None, None
    text = format(value.normalize(), "f")
    if text == "39":
        return "nonresidential", None
    if text == "27.5":
        return "residential_rental", None
    if text == "15":
        return ("land_improvements" if _LAND.search(description) else "qip"), None
    if text == "7":
        return ("furniture" if _FURNITURE.search(description) else "machinery"), None
    if text == "5":
        if _VEHICLE.search(description):
            weight = _gvwr(description)
            if weight is not None:
                return ("heavy_vehicle" if weight > 6000 else "passenger_vehicle"), None
        if _TECH.search(description):
            return "computers", None
        return "other", "5"
    if text in _OTHER_YEARS:
        return "other", text
    return None, None


def _stated_period(description: str) -> str | None:
    match = _STATED_PERIOD.search(description)
    if not match:
        return None
    return format(Decimal(match.group(1)).normalize(), "f")


def _gvwr(description: str) -> int | None:
    match = _GVWR.search(description)
    if not match:
        return None
    digits = (match.group(1) or match.group(2) or "").replace(",", "")
    return int(digits) if digits.isdigit() else None
