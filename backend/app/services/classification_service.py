"""Document classification and multi-document segmentation.

A single uploaded workpaper PDF is rarely one document. A 40-page tax organizer
typically contains an organizer, several W-2s, brokerage statements, and
correspondence. The pipeline must split it before extraction, because the field
schema for a W-2 has nothing in common with the schema for a trial balance.

Two stages:

1. **Deterministic rules** — scored keyword and regex signals per document type.
   Fast, explainable, no LLM, and it works on the raw text before masking.
2. **LLM fallback** — only for pages the rules cannot place, and only ever on
   *masked* text.

SECURITY: stage 1 runs pre-masking (it must, to segment the document), which is
fine because it is local and deterministic. Stage 2 runs post-masking and is the
only stage permitted to see network egress.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.models.enums import DocumentType

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Signal:
    """A weighted piece of evidence for a document type."""

    pattern: re.Pattern[str]
    weight: float
    #: Matching this alone is conclusive (e.g. a form's official title).
    decisive: bool = False


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


#: Signals per document type. Weights are additive; ``decisive`` short-circuits.
#: Derived from the actual header text these forms carry.
_SIGNALS: dict[DocumentType, tuple[Signal, ...]] = {
    DocumentType.W2: (
        Signal(_rx(r"\bw-?2\s+wage\s+and\s+tax\s+statement\b"), 1.0, decisive=True),
        Signal(_rx(r"\bwages,?\s+tips,?\s+other\s+compensation\b"), 0.6),
        Signal(_rx(r"\bsocial\s+security\s+(?:wages|tips)\b"), 0.4),
        Signal(_rx(r"\bmedicare\s+wages\s+and\s+tips\b"), 0.4),
        Signal(_rx(r"\bemployer\s+identification\s+number\b"), 0.2),
    ),
    DocumentType.FORM_1099_INT: (
        Signal(_rx(r"\bform\s+1099-?int\b"), 1.0, decisive=True),
        Signal(_rx(r"\binterest\s+income\b"), 0.5),
        Signal(_rx(r"\bearly\s+withdrawal\s+penalty\b"), 0.4),
        Signal(_rx(r"\btax-?exempt\s+interest\b"), 0.3),
    ),
    DocumentType.FORM_1099_DIV: (
        Signal(_rx(r"\bform\s+1099-?div\b"), 1.0, decisive=True),
        Signal(_rx(r"\bdividends\s+and\s+distributions\b"), 0.7),
        Signal(_rx(r"\b(?:total\s+)?ordinary\s+dividends\b"), 0.5),
        Signal(_rx(r"\bqualified\s+dividends\b"), 0.4),
        Signal(_rx(r"\bcapital\s+gain\s+distr"), 0.3),
    ),
    DocumentType.FORM_1099_B: (
        Signal(_rx(r"\bform\s+1099-?b\b"), 1.0, decisive=True),
        Signal(
            _rx(r"\bproceeds\s+from\s+broker\s+and\s+barter\s+exchange\b"),
            1.0,
            decisive=True,
        ),
        Signal(_rx(r"\b(?:short|long)-?term\s+transactions?\b"), 0.4),
        Signal(_rx(r"\bcost\s+or\s+other\s+basis\b"), 0.4),
        Signal(_rx(r"\bwash\s+sale\s+loss\s+disallowed\b"), 0.4),
        Signal(_rx(r"\bcusip\b"), 0.2),
    ),
    DocumentType.FORM_1099_R: (
        Signal(_rx(r"\bform\s+1099-?r\b"), 1.0, decisive=True),
        Signal(
            _rx(r"\bdistributions\s+from\s+pensions,?\s+annuities\b"), 0.8
        ),
        Signal(_rx(r"\bgross\s+distribution\b"), 0.4),
        Signal(_rx(r"\bdistribution\s+code\b"), 0.3),
    ),
    DocumentType.FORM_1099_MISC: (
        Signal(_rx(r"\bform\s+1099-?misc\b"), 1.0, decisive=True),
        Signal(_rx(r"\bmiscellaneous\s+(?:income|information)\b"), 0.6),
        Signal(_rx(r"\brents\b.*\broyalties\b"), 0.3),
    ),
    DocumentType.FORM_1099_NEC: (
        Signal(_rx(r"\bform\s+1099-?nec\b"), 1.0, decisive=True),
        Signal(_rx(r"\bnonemployee\s+compensation\b"), 0.8),
    ),
    DocumentType.FORM_1099_G: (
        Signal(_rx(r"\bform\s+1099-?g\b"), 1.0, decisive=True),
        Signal(_rx(r"\bcertain\s+government\s+payments\b"), 0.7),
        Signal(_rx(r"\bunemployment\s+compensation\b"), 0.5),
    ),
    DocumentType.FORM_1098: (
        Signal(_rx(r"\bform\s+1098\b(?!-)"), 1.0, decisive=True),
        Signal(_rx(r"\bmortgage\s+interest\s+statement\b"), 0.9),
        Signal(_rx(r"\bmortgage\s+interest\s+received\s+from\s+payer\b"), 0.5),
        Signal(_rx(r"\boutstanding\s+mortgage\s+principal\b"), 0.4),
    ),
    DocumentType.FORM_1098_T: (
        Signal(_rx(r"\bform\s+1098-?t\b"), 1.0, decisive=True),
        Signal(_rx(r"\btuition\s+statement\b"), 0.8),
        Signal(_rx(r"\bqualified\s+tuition\s+and\s+related\s+expenses\b"), 0.5),
    ),
    DocumentType.FORM_1098_E: (
        Signal(_rx(r"\bform\s+1098-?e\b"), 1.0, decisive=True),
        Signal(_rx(r"\bstudent\s+loan\s+interest\s+statement\b"), 0.8),
    ),
    DocumentType.FORM_1095: (
        Signal(_rx(r"\bform\s+1095-?[abc]\b"), 1.0, decisive=True),
        Signal(_rx(r"\bhealth\s+(?:insurance\s+marketplace|coverage)\s+statement\b"), 0.7),
    ),
    DocumentType.FORM_5498: (
        Signal(_rx(r"\bform\s+5498\b"), 1.0, decisive=True),
        Signal(_rx(r"\bira\s+contribution\s+information\b"), 0.8),
    ),
    DocumentType.SCHEDULE_K1: (
        Signal(_rx(r"\bschedule\s+k-?1\b"), 1.0, decisive=True),
        Signal(_rx(r"\bpartner'?s?\s+share\s+of\s+income,?\s+deductions\b"), 0.8),
        Signal(_rx(r"\bshareholder'?s?\s+share\s+of\s+income\b"), 0.8),
        Signal(_rx(r"\bbeneficiary'?s?\s+share\s+of\s+income\b"), 0.7),
    ),
    DocumentType.BROKERAGE_STATEMENT: (
        Signal(_rx(r"\bconsolidated\s+(?:form\s+)?1099\b"), 0.9),
        Signal(_rx(r"\b(?:brokerage|investment)\s+(?:account\s+)?statement\b"), 0.7),
        Signal(_rx(r"\brealized\s+gain(?:s)?\s+(?:and|/)\s+loss(?:es)?\b"), 0.5),
        Signal(_rx(r"\bportfolio\s+summary\b"), 0.4),
    ),
    DocumentType.TRIAL_BALANCE: (
        Signal(_rx(r"\btrial\s+balance\b"), 1.0, decisive=True),
        Signal(_rx(r"\b(?:unadjusted|adjusted)\s+trial\s+balance\b"), 1.0, decisive=True),
        Signal(_rx(r"\bdebit\b.{0,40}\bcredit\b"), 0.4),
        Signal(_rx(r"\baccount\s+(?:no\.?|number|code)\b.{0,40}\bdescription\b"), 0.3),
    ),
    DocumentType.GENERAL_LEDGER: (
        Signal(_rx(r"\bgeneral\s+ledger\b"), 1.0, decisive=True),
        Signal(_rx(r"\bg/?l\s+detail\b"), 0.6),
        Signal(_rx(r"\bbeginning\s+balance\b.{0,60}\bending\s+balance\b"), 0.4),
    ),
    DocumentType.DEPRECIATION_SCHEDULE: (
        Signal(_rx(r"\bdepreciation\s+(?:schedule|report|detail)\b"), 1.0, decisive=True),
        Signal(_rx(r"\baccumulated\s+depreciation\b"), 0.5),
        Signal(_rx(r"\b(?:macrs|section\s+179|bonus\s+depreciation)\b"), 0.5),
        Signal(_rx(r"\bplaced\s+in\s+service\b"), 0.4),
    ),
    DocumentType.BALANCE_SHEET: (
        Signal(_rx(r"\bbalance\s+sheet\b"), 1.0, decisive=True),
        Signal(_rx(r"\btotal\s+(?:assets|liabilities)\b"), 0.5),
        Signal(_rx(r"\b(?:stockholders?|shareholders?|owners?)'?\s+equity\b"), 0.4),
    ),
    DocumentType.PROFIT_AND_LOSS: (
        Signal(_rx(r"\b(?:profit\s+and\s+loss|income\s+statement)\b"), 1.0, decisive=True),
        Signal(_rx(r"\bp\s*&\s*l\b"), 0.7),
        Signal(_rx(r"\bcost\s+of\s+goods\s+sold\b"), 0.5),
        Signal(_rx(r"\bgross\s+(?:profit|margin)\b"), 0.4),
        Signal(_rx(r"\bnet\s+(?:income|loss)\b"), 0.3),
    ),
    DocumentType.PRIOR_YEAR_RETURN: (
        Signal(_rx(r"\bu\.?s\.?\s+individual\s+income\s+tax\s+return\b"), 0.8),
        Signal(_rx(r"\bform\s+1040\b"), 0.6),
        Signal(_rx(r"\b(?:prior|previous)[- ]year\s+(?:return|comparison)\b"), 0.7),
        Signal(_rx(r"\bcopy\s+of\s+(?:your\s+)?(?:federal|state)\s+return\b"), 0.5),
    ),
    DocumentType.CLIENT_ORGANIZER: (
        Signal(_rx(r"\btax\s+organizer\b"), 1.0, decisive=True),
        Signal(_rx(r"\bclient\s+organizer\b"), 1.0, decisive=True),
        Signal(_rx(r"\bquestions?\s+(?:answered|and\s+answers)\b"), 0.4),
        Signal(_rx(r"\bplease\s+(?:complete|review|provide)\b"), 0.3),
        Signal(_rx(r"\bworksheets?:\s*basic\s+data\b"), 0.6),
    ),
    DocumentType.ENGAGEMENT_LETTER: (
        Signal(_rx(r"\bengagement\s+letter\b"), 1.0, decisive=True),
        Signal(_rx(r"\bterms\s+of\s+(?:our\s+)?engagement\b"), 0.7),
        Signal(_rx(r"\bscope\s+of\s+services\b"), 0.4),
    ),
    DocumentType.CONSENT_FORM: (
        Signal(_rx(r"\bconsent\s+to\s+(?:disclose|use)\b"), 1.0, decisive=True),
        Signal(_rx(r"\bsection\s+7216\b"), 0.8),
        Signal(_rx(r"\bdisclosure\s+of\s+tax\s+return\s+information\b"), 0.6),
    ),
    DocumentType.IRS_NOTICE: (
        Signal(_rx(r"\bnotice\s+(?:number\s+)?cp\d{2,4}\b"), 1.0, decisive=True),
        Signal(_rx(r"\bletter\s+\d{3,4}[a-z]?\b"), 0.5),
        Signal(_rx(r"\binternal\s+revenue\s+service\b.{0,80}\bnotice\b"), 0.6),
        Signal(_rx(r"\bamount\s+due\b.{0,40}\bby\b"), 0.3),
    ),
    DocumentType.CORRESPONDENCE: (
        Signal(_rx(r"^\s*from:.*$", ), 0.4),
        Signal(_rx(r"\bsubject:\s*\S"), 0.4),
        Signal(_rx(r"\bsent:\s*\w"), 0.3),
        Signal(_rx(r"\b(?:dear|regards|sincerely)\b"), 0.2),
    ),
    DocumentType.RECEIPT: (
        Signal(_rx(r"\breceipt\b"), 0.6),
        Signal(_rx(r"\b(?:subtotal|sales\s+tax|total\s+due)\b"), 0.3),
        Signal(_rx(r"\bthank\s+you\s+for\s+your\s+(?:business|purchase)\b"), 0.4),
    ),
}

#: Score at or above which a rules-based classification is trusted.
_RULES_CONFIDENCE_FLOOR = 0.55
#: Score below which the LLM fallback is consulted (on masked text only).
_LLM_FALLBACK_CEILING = 0.55


@dataclass(slots=True)
class PageClassification:
    page_number: int
    document_type: DocumentType
    confidence: float
    method: str = "rules"
    matched_signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page_number,
            "document_type": self.document_type.value,
            "confidence": round(self.confidence, 3),
            "method": self.method,
        }


@dataclass(slots=True)
class DocumentSegment:
    """A run of consecutive pages forming one logical document."""

    document_type: DocumentType
    page_start: int
    page_end: int
    confidence: float
    method: str = "rules"

    @property
    def page_count(self) -> int:
        return self.page_end - self.page_start + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_type": self.document_type.value,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "page_count": self.page_count,
            "confidence": round(self.confidence, 3),
            "method": self.method,
        }


class ClassificationService:
    """Classifies pages and groups them into logical documents."""

    def __init__(self, gemini: Any | None = None) -> None:
        # Optional; when absent, low-confidence pages stay UNKNOWN_WORKPAPER and
        # are routed to review rather than guessed at.
        self._gemini = gemini

    # ------------------------------------------------------------ scoring

    def classify_page(self, text: str, page_number: int = 1) -> PageClassification:
        """Score a single page against every document type's signals."""
        if not text or not text.strip():
            return PageClassification(
                page_number, DocumentType.UNKNOWN_WORKPAPER, 0.0, "empty"
            )

        # Headers carry the form title; weight the top of the page higher.
        header = text[:1500]
        best_type = DocumentType.UNKNOWN_WORKPAPER
        best_score = 0.0
        best_matches: list[str] = []

        for document_type, signals in _SIGNALS.items():
            score = 0.0
            matches: list[str] = []
            decisive_hit = False

            for signal in signals:
                in_header = bool(signal.pattern.search(header))
                in_body = in_header or bool(signal.pattern.search(text))
                if not in_body:
                    continue
                # A title match in the header is worth more than a stray body hit.
                weight = signal.weight * (1.0 if in_header else 0.6)
                score += weight
                matches.append(signal.pattern.pattern[:48])
                if signal.decisive and in_header:
                    decisive_hit = True

            if decisive_hit:
                score = max(score, 0.95)
            if score > best_score:
                best_score, best_type, best_matches = score, document_type, matches

        return PageClassification(
            page_number=page_number,
            document_type=best_type if best_score > 0 else DocumentType.UNKNOWN_WORKPAPER,
            confidence=min(best_score, 1.0),
            method="rules",
            matched_signals=best_matches[:6],
        )

    def classify_pages(self, page_texts: list[str]) -> list[PageClassification]:
        return [
            self.classify_page(text, index)
            for index, text in enumerate(page_texts, start=1)
        ]

    # ------------------------------------------------------- segmentation

    def segment(
        self, classifications: list[PageClassification]
    ) -> list[DocumentSegment]:
        """Group consecutive pages of the same type into documents.

        Continuation pages (a 1099-B running over four pages) usually score low
        because only the first page carries the title. A low-confidence page
        following a confident one is treated as a continuation rather than a new
        document — otherwise a single statement fragments into four.
        """
        if not classifications:
            return []

        segments: list[DocumentSegment] = []
        current: DocumentSegment | None = None

        for page in classifications:
            confident = page.confidence >= _RULES_CONFIDENCE_FLOOR
            is_continuation = (
                current is not None
                and not confident
                and page.document_type
                in (current.document_type, DocumentType.UNKNOWN_WORKPAPER)
            )
            same_type = current is not None and page.document_type == current.document_type

            if current is not None and (is_continuation or same_type):
                current.page_end = page.page_number
                current.confidence = max(current.confidence, page.confidence)
                continue

            if current is not None:
                segments.append(current)
            current = DocumentSegment(
                document_type=page.document_type,
                page_start=page.page_number,
                page_end=page.page_number,
                confidence=page.confidence,
                method=page.method,
            )

        if current is not None:
            segments.append(current)
        return segments

    # -------------------------------------------------------- LLM fallback

    def classify_masked_text(
        self, masked_text: str, page_number: int = 1
    ) -> PageClassification:
        """Ask the model to classify a page the rules could not place.

        SECURITY: ``masked_text`` must already have passed through
        ``MaskingService``. This method never receives raw document text — see
        ``workflow_orchestrator`` for the call ordering.
        """
        if self._gemini is None:
            return PageClassification(
                page_number, DocumentType.UNKNOWN_WORKPAPER, 0.0, "unavailable"
            )

        from app.models.enums import TaskKind

        choices = ", ".join(t.value for t in DocumentType)
        prompt = (
            "Classify this US tax workpaper page into exactly one category.\n"
            f"Categories: {choices}\n\n"
            "Respond with JSON: "
            '{"document_type": "<category>", "confidence": <0-1>, '
            '"reason": "<short>"}\n\n'
            "Note: names, identifiers and amounts have been replaced with "
            "synthetic substitutes. Classify by structure and labels.\n\n"
            f"--- PAGE {page_number} ---\n{masked_text[:6000]}"
        )

        try:
            response = self._gemini.generate_json(
                prompt=prompt, task=TaskKind.CLASSIFICATION
            )
            raw_type = str(response.data.get("document_type", "")).strip()
            document_type = DocumentType(raw_type)
            confidence = float(response.data.get("confidence", 0.5))
            return PageClassification(
                page_number, document_type, min(max(confidence, 0.0), 1.0), "llm"
            )
        except (ValueError, KeyError, AttributeError) as exc:
            logger.info(
                "LLM classification returned an unusable result (%s)",
                type(exc).__name__,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("LLM classification failed: %s", type(exc).__name__)

        return PageClassification(
            page_number, DocumentType.UNKNOWN_WORKPAPER, 0.0, "llm_failed"
        )

    @staticmethod
    def needs_llm_fallback(classification: PageClassification) -> bool:
        return classification.confidence < _LLM_FALLBACK_CEILING
