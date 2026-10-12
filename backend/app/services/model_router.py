"""Model tier selection.

Routing rules, per the platform's cost/quality policy:

===============================  =====================================
Task                             Tier
===============================  =====================================
simple chatbot query             Flash
complex / multi-state query      Pro
ambiguous handwriting            Pro (or Flash when OCR was confident)
high-volume extraction           Flash-Lite
final tax position memo          Pro + RAG citations
deterministic calculation        **no model** — local tax engine
===============================  =====================================

Escalation is dynamic as well as static: a task that normally runs on Flash is
promoted to Pro when upstream confidence is poor, when the question spans
multiple jurisdictions, or when a first attempt returned a low-confidence
answer.

SECURITY: a deterministic calculation must never be routed to a model.
``assert_not_arithmetic`` makes that a hard error rather than a convention, so a
future caller cannot quietly ask the LLM to do the maths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.models.enums import ModelTier, TaskKind

logger = get_logger(__name__)


#: Baseline tier per task, before any escalation signal is considered.
_BASE_TIER: dict[TaskKind, ModelTier] = {
    TaskKind.CHAT_SIMPLE: ModelTier.FLASH,
    TaskKind.CHAT_COMPLEX: ModelTier.PRO,
    TaskKind.CLASSIFICATION: ModelTier.FLASH_LITE,
    TaskKind.BULK_EXTRACTION: ModelTier.FLASH_LITE,
    TaskKind.DOCUMENT_EXTRACTION: ModelTier.FLASH,
    TaskKind.HANDWRITING_INTERPRETATION: ModelTier.PRO,
    TaskKind.TAX_REASONING: ModelTier.PRO,
    TaskKind.TAX_MEMO: ModelTier.PRO,
    TaskKind.TEMPLATE_INFERENCE: ModelTier.FLASH,
    TaskKind.RETURN_EXPLANATION: ModelTier.FLASH,
}

_TIER_ORDER: tuple[ModelTier, ...] = (
    ModelTier.FLASH_LITE,
    ModelTier.FLASH,
    ModelTier.PRO,
)


@dataclass(slots=True)
class RoutingSignals:
    """Context that can promote or demote the baseline tier."""

    #: Upstream confidence (OCR quality, rules-classification score).
    upstream_confidence: float | None = None
    #: Number of distinct jurisdictions in play. >1 implies multi-state work.
    jurisdiction_count: int = 1
    #: True when the source page is handwritten or OCR flagged it.
    handwriting: bool = False
    #: True when a prior attempt produced a low-confidence answer.
    retry_after_low_confidence: bool = False
    #: Approximate input size; very large contexts favour the stronger model.
    approx_input_tokens: int = 0
    #: True when the answer will be filed or given to a client.
    client_facing: bool = False
    #: Number of items in a batch. Large batches favour the cheap tier.
    batch_size: int = 1


@dataclass(slots=True)
class RoutingDecision:
    tier: ModelTier
    model_name: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"tier": self.tier.value, "model": self.model_name, "reason": self.reason}


class ArithmeticRoutingError(RuntimeError):
    """Raised when a caller tries to route a calculation to a model."""


class ModelRouter:
    """Chooses a model tier and resolves it to a configured model name."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def model_name(self, tier: ModelTier) -> str:
        match tier:
            case ModelTier.PRO:
                return self._settings.gemini_model_pro
            case ModelTier.FLASH:
                return self._settings.gemini_model_flash
            case ModelTier.FLASH_LITE:
                return self._settings.gemini_model_flash_lite

    def route(
        self, task: TaskKind, signals: RoutingSignals | None = None
    ) -> RoutingDecision:
        signals = signals or RoutingSignals()
        tier = _BASE_TIER[task]
        reasons: list[str] = [f"base tier for {task.value}"]

        def promote(reason: str) -> None:
            nonlocal tier
            index = _TIER_ORDER.index(tier)
            if index < len(_TIER_ORDER) - 1:
                tier = _TIER_ORDER[index + 1]
                reasons.append(reason)

        def demote(reason: str) -> None:
            nonlocal tier
            index = _TIER_ORDER.index(tier)
            if index > 0:
                tier = _TIER_ORDER[index - 1]
                reasons.append(reason)

        # --- promotions -----------------------------------------------
        if signals.retry_after_low_confidence:
            promote("retry after low-confidence answer")
        if signals.jurisdiction_count > 1:
            promote(f"multi-jurisdiction ({signals.jurisdiction_count} states)")
        if signals.handwriting and (signals.upstream_confidence or 0) < 0.85:
            promote("handwriting with uncertain OCR")
        if (
            signals.upstream_confidence is not None
            and signals.upstream_confidence < self._settings.confidence_escalate
        ):
            promote(f"upstream confidence {signals.upstream_confidence:.2f} below threshold")
        if signals.client_facing and task is not TaskKind.CHAT_SIMPLE:
            promote("client-facing output")
        if signals.approx_input_tokens > 120_000:
            promote("very large context")

        # --- demotions ------------------------------------------------
        # A large batch of clean, high-confidence pages does not need Flash.
        if (
            signals.batch_size >= 25
            and (signals.upstream_confidence or 1.0) >= 0.92
            and not signals.handwriting
            and task in {TaskKind.BULK_EXTRACTION, TaskKind.CLASSIFICATION}
        ):
            demote(f"large clean batch ({signals.batch_size} items)")

        decision = RoutingDecision(
            tier=tier, model_name=self.model_name(tier), reason="; ".join(reasons)
        )
        logger.debug("Routed %s -> %s (%s)", task.value, tier.value, decision.reason)
        return decision

    @staticmethod
    def assert_not_arithmetic(task: TaskKind, *, operation: str = "") -> None:
        """Refuse to route a deterministic calculation to a model.

        SECURITY / correctness: the tax engine owns every figure that reaches a
        return. A model may propose and explain; it may not compute. Enforcing
        this in code stops the rule eroding as the codebase grows.
        """
        raise ArithmeticRoutingError(
            f"Calculation '{operation or task.value}' must be performed by "
            "app.services.tax_engine, not by a language model. LLM arithmetic "
            "is never authoritative in this platform."
        )
