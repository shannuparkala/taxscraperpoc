"""The nine-stage processing pipeline.

    Upload → Classification → OCR → Masking → LLM → Validation
          → Review → Rehydration → Output

Stage ordering is the security design, not just a workflow. Masking sits between
OCR and the LLM, and rehydration sits after every model interaction has
finished. No stage may reach forward or backward past those two boundaries.

The orchestrator is deliberately the only component that sees both the raw text
and the masked text. Everything downstream of ``_stage_masking`` receives masked
content exclusively.
"""

from __future__ import annotations

import json
import re
import textwrap
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.audit import AuditAction, AuditLogger
from app.core.config import Settings, get_settings
from app.core.errors import AppError, PipelineError, UnreadableFileError
from app.core.logging import get_logger
from app.core.security import DecryptionKeyMismatchError, sha256_bytes
from app.core.tax_year import ResolvedYear
from app.core.tax_year import resolve as resolve_tax_year
from app.models.database_models import (
    Document,
    ExtractionResult,
    ReviewItem,
    UploadedFile,
    Workflow,
    WorkflowStageRun,
)
from app.models.enums import (
    STAGE_LABELS,
    WORKFLOW_STAGE_ORDER,
    DocumentType,
    FileStatus,
    ReviewReason,
    ReviewStatus,
    StageStatus,
    TaskKind,
    WorkflowStage,
    WorkflowStatus,
)
from app.services.carryover_repository import (
    CarryoverAudit,
    CarryoverKind,
    CarryoverRepository,
    taxpayer_key,
)
from app.services.classification_service import ClassificationService
from app.services.explanation_service import ExplanationStore
from app.services.figure_boxes import figure_words, locate
from app.services.gemini_service import GeminiService
from app.services.ingestion_service import IngestionService
from app.services.llm_egress_guard import build_guard
from app.services.llm_meter import DbLlmMeter, metered
from app.services.masking_service import MaskingService, MaskStyle
from app.services.model_router import RoutingSignals
from app.services.ocr_service import DocumentExtraction, OcrService
from app.services.output_generation_service import OutputGenerationService
from app.services.pii_detection_service import (
    DetectionConfig,
    PiiDetectionService,
    summarize_detections,
)
from app.services.prior_year_service import (
    PRIOR_YEAR_FIELDS,
    PriorYearService,
    upload_request,
)
from app.services.rehydration_service import RehydrationService
from app.services.tax_engine import tax_tables
from app.services.tax_engine.form_1040 import (
    AdditionalDeductionInputs,
    AdjustmentInputs,
    CapitalGainInputs,
    DeductionInputs,
    Form1040Calculator,
    IncomeInputs,
    PaymentInputs,
    TaxpayerProfile,
)
from app.services.tax_engine.form_7203 import (
    ShareholderBasisInputs,
    compute_form_7203,
)
from app.services.tax_engine.tax_tables import FilingStatusTax
from app.services.tax_validation_service import TaxValidationService
from app.services.taxpayer_profile_service import TaxpayerProfileService

logger = get_logger(__name__)


def _engine_money_fields() -> tuple[str, ...]:
    """Every monetary input the tax engine can consume.

    Derived from the engine's own dataclasses rather than written out by hand,
    because the two ends of this contract used to disagree silently: the prompt
    illustrated exactly one field name (``wages``), and recomputation read seven
    of them. ``federal_withheld`` was in neither, so ``total_payments`` was
    structurally always zero and the pipeline could not produce a refund for any
    return, however well the document was read. Adding a field to ``form_1040``
    now makes it requestable and consumable in one step.
    """
    names: list[str] = []
    for source in (
        IncomeInputs,
        CapitalGainInputs,
        AdjustmentInputs,
        DeductionInputs,
        AdditionalDeductionInputs,
        PaymentInputs,
    ):
        for entry in dataclass_fields(source):
            # `from __future__ import annotations` renders these as strings.
            if "Decimal" not in str(entry.type):
                continue  # e.g. DeductionInputs.force_itemize
            names.append(entry.name)
    return tuple(dict.fromkeys(names))


#: Shareholder-basis figures. Not engine inputs, so they are not derived by
#: _engine_money_fields, but the extraction prompt must still request them:
#: without the K-1 loan balances the Form 7203 gain cannot be computed at
#: all, and it appears on no other document.
SHAREHOLDER_BASIS_FIELDS: tuple[str, ...] = (
    "loan_balance_begin",
    "loan_balance_end",
    "stock_basis_begin",
    "debt_basis_begin",
    "distributions",
    "nondeductible_expenses",
)

ENGINE_MONEY_FIELDS: tuple[str, ...] = (
    *_engine_money_fields(),
    *SHAREHOLDER_BASIS_FIELDS,
)


#: Document types whose amounts describe a different tax year, or are not source
#: documents for the return at all.
#:
#: These are still extracted — a preparer compares this year against last year,
#: and the organizer's own figures are worth surfacing — but their amounts must
#: never be summed into the current year's totals. A prior-year return states a
#: full set of wages, interest, and withholding; folding those in would roughly
#: double the return while looking entirely plausible.
NON_SOURCE_DOCUMENT_TYPES: frozenset[str] = frozenset(
    {
        DocumentType.PRIOR_YEAR_RETURN.value,
        DocumentType.ENGAGEMENT_LETTER.value,
        DocumentType.CONSENT_FORM.value,
        DocumentType.CORRESPONDENCE.value,
        DocumentType.IRS_NOTICE.value,
    }
)

#: The exception to the rule above: fields a prior-year document is the *only*
#: correct source for.
#:
#: The blanket exclusion solved one problem and created its mirror image. Last
#: year's wages must not be summed into this year — but these figures are
#: *defined* as prior-year amounts, and the forms say so in their own line
#: labels: Schedule D lines 6 and 14 read "carryover ... from your Capital Loss
#: Carryover Worksheet", and Form 1040 line 26 reads "estimated tax payments
#: and amount applied from your prior return". No current-year document states
#: them, so excluding the whole document guaranteed they were always zero.
#:
#: On the sample return that shortfall was $4,511 of capital loss, which made
#: line 7a read 11,149 instead of 6,638 — a plausible number, on a return that
#: otherwise footed, arrived at by omission.
CARRYFORWARD_FIELDS: frozenset[str] = frozenset(
    {
        "short_term_loss_carryover",
        "long_term_loss_carryover",
        "prior_year_overpayment_applied",
    }
)

#: What to look for on each kind of document, appended to the per-document
#: prompt. Box numbers are stated explicitly because the model is reading OCR
#: output of a scanned form, where the label above a box is often on a different
#: line from its value and the association is easy to lose.
_EXTRACTION_HINTS: dict[str, str] = {
    DocumentType.W2.value: (
        "Box 1 is wages. Box 2 is federal_withheld. Box 17 is "
        "state_local_income_tax — that is the STATE income tax withheld, not a "
        "property tax and not a total.\n"
        "Box 7 is qualified_tips and box 12 code TT (or an overtime figure "
        "stated inside box 1) is qualified_overtime. Both are deductions on "
        "Schedule 1-A, new for 2025, and they are claimed on top of the "
        "standard deduction. A return that misses them loses the deduction "
        "entirely — on one sample, 2,905 of overtime pay."
    ),
    DocumentType.FORM_1099_INT.value: (
        "Box 1 is taxable_interest. Box 8 is tax_exempt_interest. Box 4 is "
        "federal_withheld."
    ),
    DocumentType.FORM_1099_DIV.value: (
        "Box 1a is ordinary_dividends. Box 1b is qualified_dividends. Box 2a "
        "total capital gain distributions is capital_gain_distributions — it "
        "belongs on Schedule D line 13 and appears on no 1099-B, so report it "
        "even when a brokerage statement also reports realised gains. Box 4 is "
        "federal_withheld."
    ),
    DocumentType.FORM_1099_B.value: (
        "Separate the gains by holding period: short_term_gain for the "
        "short-term total, long_term_gain for the long-term total, each with a "
        "leading minus for a loss. The two are taxed differently and must not "
        "be netted together. If only proceeds and cost basis are shown, report "
        "each transaction as a separate fact and do not net them yourself."
    ),
    DocumentType.FORM_1099_R.value: (
        "Box 1 is the gross distribution and box 2a is the taxable amount. Use "
        "ira_distributions / ira_taxable for an IRA, otherwise pensions / "
        "pensions_taxable. Box 4 is federal_withheld."
    ),
    DocumentType.FORM_1099_MISC.value: (
        "Box 1 rents is rental_income. Box 3 other income is other_income. "
        "Box 4 is federal_withheld."
    ),
    DocumentType.FORM_1099_NEC.value: (
        "Box 1 nonemployee compensation is business_income. Box 4 is "
        "federal_withheld."
    ),
    DocumentType.FORM_1099_G.value: (
        "Box 1 unemployment compensation is other_income. Box 4 is "
        "federal_withheld."
    ),
    DocumentType.FORM_1098.value: "Box 1 is mortgage_interest.",
    DocumentType.FORM_1098_E.value: "Box 1 is student_loan_interest.",
    DocumentType.FORM_1098_T.value: (
        "Report qualified tuition from box 1 and scholarships from box 5 as "
        "separate facts. Do not compute an education credit."
    ),
    DocumentType.FORM_5498.value: "Report IRA contributions as ira_deduction.",
    DocumentType.SCHEDULE_K1.value: (
        "Report each numbered box as its own fact, labelled with the box "
        "number. On Form 1120-S: box 1 ordinary business income and box 2 "
        "rental real estate both reach Schedule E, so report them as "
        "rental_income; box 7 is short_term_from_k1 and box 8a is "
        "long_term_from_k1. Use business_income only for a sole "
        "proprietorship, never for a K-1 — a shareholder's K-1 income is not "
        "subject to self-employment tax and reporting it as business_income "
        "would add one. "
        "Line I 'Loans from shareholder' has a beginning and an ending "
        "balance: report them as loan_balance_begin and loan_balance_end. A "
        "decrease between the two is a repayment, and repaying a loan whose "
        "basis has been reduced produces income that appears on no other "
        "document — omit these and the return silently loses it. Box 16 code "
        "C is nondeductible_expenses and box 16 code D is distributions; both "
        "reduce basis."
    ),
    DocumentType.BROKERAGE_STATEMENT.value: (
        "Report the 1099 summary figures: interest, dividends, and realised "
        "gain or loss. Ignore unrealised positions and account values."
    ),
    DocumentType.CLIENT_ORGANIZER.value: (
        "Report filing_status, qualifying_children, other_dependents, state, "
        "and any amounts the client has entered. Ignore blank prompts and "
        "printed instructions.\n"
        "Identity comes ONLY from the personal-information section at the top "
        "— the boxes headed Taxpayer and Spouse. An organizer also lists "
        "dependents, trustees, account holders and prior-year comparatives, and "
        "reporting a name or date of birth from any of those produces a return "
        "filed for the wrong person: on one workpaper this returned fourteen "
        "different taxpayer names and two unrelated pairs of birth dates, and "
        "the wrong pair was used.\n"
        "Report taxpayer_name with date_of_birth as a matched pair, and "
        "spouse_name with spouse_date_of_birth as a matched pair. If the "
        "taxpayer section gives a name but no date of birth, report the name "
        "and omit the date — do not borrow a date from elsewhere on the page. "
        "Report a dependent's date of birth as dependent_date_of_birth, never "
        "as date_of_birth.\n"
        "An organizer states the same money twice: a recap page carries a "
        "household total for a category, and later pages itemise the source "
        "forms behind it. Report ONLY the itemised per-form figures. Never "
        "report a recap, carry-forward or 'total' line as an amount — on one "
        "workpaper the wage recap (104,308 taxpayer + 58,500 spouse) and the "
        "two W-2 detail pages (118,453.63 and 46,213.60) were both reported, "
        "and the return doubled wages to 327,475 against a true 164,667. If "
        "you can see only a recap and no itemised detail, report the recap and "
        "list the missing detail in missing_information."
    ),
    DocumentType.PRIOR_YEAR_RETURN.value: (
        "This is LAST year's return. Report its figures so a preparer can "
        'compare, and mark every fact with "prior_year": true. Do not present '
        "them as this year's amounts.\n"
        "Four figures on it do carry into this year's return, and it is the "
        "only document that states them. Report these by name:\n"
        "- short_term_loss_carryover and long_term_loss_carryover, from the "
        "Capital Loss Carryover Worksheet (or Schedule D lines 6 and 14 of the "
        "return being carried from), as positive amounts.\n"
        "- prior_year_overpayment_applied, from the line reading 'amount you "
        "want applied to your estimated tax' (Form 1040 line 36).\n"
        "If the return shows none of these, say so rather than guessing."
    ),
}

_DEFAULT_EXTRACTION_HINT = (
    "Report every tax-relevant amount you can see, with the label printed "
    "beside it."
)

#: Identity facts the return needs, named canonically.
#:
#: These are as much a contract as ``ENGINE_MONEY_FIELDS``, and they were not
#: pinned: the model emitted ``name`` and ``address`` while the output stage
#: looked for ``taxpayer_name`` and ``street_address``, so the form went out
#: with an SSN and no name on it. ``ssn`` and ``state`` printed only because
#: those two happened to agree.
IDENTITY_FIELDS: tuple[str, ...] = (
    "taxpayer_name",
    "spouse_name",
    "ssn",
    "spouse_ssn",
    "street_address",
    "apartment",
    "city",
    "state",
    "zip_code",
    "date_of_birth",
    "spouse_date_of_birth",
)

#: Names the model reaches for anyway. Accepting them costs nothing and means a
#: prompt revision cannot silently blank the taxpayer's name again.
IDENTITY_FIELD_ALIASES: dict[str, str] = {
    "name": "taxpayer_name",
    "taxpayer": "taxpayer_name",
    "taxpayer_full_name": "taxpayer_name",
    "spouse": "spouse_name",
    "social_security_number": "ssn",
    "address": "street_address",
    "home_address": "street_address",
    "street": "street_address",
    "apt": "apartment",
    "apartment_number": "apartment",
    "town": "city",
    "zip": "zip_code",
    "postal_code": "zip_code",
    "dob": "date_of_birth",
    "birth_date": "date_of_birth",
    "spouse_dob": "spouse_date_of_birth",
}


def canonical_identity_field(name: str) -> str | None:
    """Map an extracted field name onto the canonical identity vocabulary."""
    key = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")
    if key in IDENTITY_FIELDS:
        return key
    return IDENTITY_FIELD_ALIASES.get(key)


def age_on(date_of_birth: Any, *, tax_year: int) -> int | None:
    """Age at the end of ``tax_year``, or None if the date is unusable.

    Drives both the age-65 addition to the standard deduction and the Schedule
    1-A senior deduction. The sample workpaper stated a 1952 date of birth and
    the pipeline discarded it, costing the taxpayer 2,000 on line 12e and 6,000
    on line 13b.
    """
    text = str(date_of_birth or "").strip()
    if not text:
        return None
    for pattern in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d/%m/%Y", "%m/%d/%y"):
        try:
            born = datetime.strptime(text, pattern)
        except ValueError:
            continue
        # The IRS treats someone born on 1 January as reaching the age on the
        # last day of the prior year; ages are otherwise taken at 31 December.
        age = tax_year - born.year
        if (born.month, born.day) == (1, 1):
            age += 1
        return age if 0 <= age <= 120 else None
    return None


#: Documents that describe a *business*, not the taxpayer personally.
#:
#: A profit-and-loss statement has lines labelled "Social Security" (the
#: employer's payroll tax) and "health" (the company's insurance premium).
#: Matched against personal field names they produced $25,428 of Social
#: Security benefits and a $6,282 adjustment on a return where the taxpayer
#: had neither.
BUSINESS_ENTITY_DOCUMENTS: frozenset[str] = frozenset(
    {
        DocumentType.PROFIT_AND_LOSS.value,
        DocumentType.BALANCE_SHEET.value,
        DocumentType.TRIAL_BALANCE.value,
        DocumentType.GENERAL_LEDGER.value,
        DocumentType.DEPRECIATION_SCHEDULE.value,
    }
)

#: The only engine fields a business statement may contribute — what actually
#: flows through to the personal return. Everything else on such a document
#: belongs to the entity and stops there.
#: Fields only certain forms can possibly report, as field -> the document
#: types allowed to state it.
#:
#: Deliberately small. This is an inverted allow-list -- a field absent from
#: this map is unrestricted -- because the dangerous direction is dropping
#: real money, not admitting a stray figure. Each entry has to be a fact
#: about what the form *is*, not a guess about what it usually contains.
#:
#: Basic 6 needed it: the extractor read 64,929 off a Form 1098 and reported
#: it as wages, which was then added to the W-2's 81,412.87 for a line 1a of
#: 146,342 and an adjusted gross income of 150,513 against a filed 75,582. A
#: 1098 is a mortgage interest statement; it has no wage box at all.
FIELD_SOURCE_DOCUMENTS: dict[str, frozenset[str]] = {
    "wages": frozenset(
        {
            DocumentType.W2.value,
            DocumentType.W2G.value,
            # Summary documents transcribe the W-2s and are the only source
            # when the forms themselves are missing or unreadable.
            DocumentType.CLIENT_ORGANIZER.value,
            DocumentType.UNKNOWN_WORKPAPER.value,
            DocumentType.CORRESPONDENCE.value,
            DocumentType.HANDWRITTEN_NOTES.value,
            DocumentType.PRIOR_YEAR_RETURN.value,
        }
    ),
    "mortgage_interest": frozenset(
        {
            DocumentType.FORM_1098.value,
            DocumentType.CLIENT_ORGANIZER.value,
            DocumentType.UNKNOWN_WORKPAPER.value,
            DocumentType.RECEIPT.value,
            DocumentType.PRIOR_YEAR_RETURN.value,
        }
    ),
}


BUSINESS_ENTITY_FIELDS: frozenset[str] = frozenset(
    {"business_income", "rental_income"}
)

#: Non-monetary facts taken from whichever document states them first.
_SCALAR_FIELDS: tuple[str, ...] = (
    "tax_year",
    "filing_status",
    "qualifying_children",
    "other_dependents",
    "state",
)


#: Document types whose whole purpose is to report money. If one of these is
#: classified and contributes no figure at all, the extraction failed on it --
#: and the return is still produced, still foots, and is quietly missing an
#: income source. Types that legitimately carry no amount are absent from this
#: set: consent forms and engagement letters state nothing, a 1095 reports
#: coverage rather than money, and a prior-year return is deliberately excluded
#: from the sums by NON_SOURCE_DOCUMENT_TYPES.
MONEY_BEARING_DOCUMENTS: frozenset[str] = frozenset(
    {
        DocumentType.W2.value,
        DocumentType.W2G.value,
        DocumentType.FORM_1099_INT.value,
        DocumentType.FORM_1099_DIV.value,
        DocumentType.FORM_1099_B.value,
        DocumentType.FORM_1099_R.value,
        DocumentType.FORM_1099_MISC.value,
        DocumentType.FORM_1099_NEC.value,
        DocumentType.FORM_1099_G.value,
        DocumentType.FORM_1099_S.value,
        DocumentType.FORM_1098.value,
        DocumentType.SCHEDULE_K1.value,
        DocumentType.BROKERAGE_STATEMENT.value,
    }
)


def detect_silent_documents(
    document_types: Iterable[str],
    field_provenance: dict[str, list[dict[str, str]]],
) -> list[str]:
    """Money-bearing documents that were classified and reported nothing.

    This is the failure that hides. On one workpaper fourteen documents were
    classified and the return came out with adjusted gross income of -75
    against a filed 92,758, carrying two review items -- because a return built
    from an empty extraction is well formed. The workflow-wide sufficiency
    check does not catch it either: one readable interest figure is enough to
    clear "no monetary field was extracted" while every other document
    contributed nothing.
    """
    contributed = {
        str(entry.get("document_type") or "")
        for contributions in field_provenance.values()
        for entry in contributions
    }
    return sorted(
        {
            document_type
            for document_type in document_types
            if document_type in MONEY_BEARING_DOCUMENTS
            and document_type not in contributed
        }
    )


#: A field is worth a second look when one document supplies this many separate
#: figures for it. Two is ordinary — a taxpayer and a spouse each have a W-2.
#: Three or more from a *single* document is the shape of a recap page being
#: summed with the detail it recaps.
_SUBTOTAL_RISK_CONTRIBUTIONS = 3


#: A client organizer is the taxpayer's own recap of the forms behind it, so
#: a figure it states for a field a source form also reports is the same
#: money written down twice.
ORGANIZER_SUMMARY_TYPES: frozenset[str] = frozenset({DocumentType.CLIENT_ORGANIZER.value})


def drop_organizer_restatements(
    totals: dict[str, Decimal],
    provenance: dict[str, list[dict[str, str]]],
) -> list[str]:
    """Remove an organizer's recap of a field a source form already reported.

    Basic 4's wages arrived as two contributions: 162,808 from the client
    organizer (its recap page, 104,308 taxpayer plus 58,500 spouse) and
    164,667.23 from the W-2s themselves. Both were summed, so Form 1040 line
    1a read 327,475.23 and adjusted gross income came out at 332,298 against
    a filed 166,749 -- the largest single error across the nine workpapers.

    The W-2 is the authoritative source and the organizer is a summary of it,
    which is the same judgement a preparer makes without thinking about it.
    No tolerance is involved: the organizer's figure is dropped only when a
    money-bearing source document reported the same field. An organizer that
    is the only source for a field keeps its figure.

    Returns the descriptions of what was dropped, for the reviewer.
    """
    dropped: list[str] = []
    for name, contributions in list(provenance.items()):
        sources = {str(c.get('document_type') or '') for c in contributions}
        if not (sources & ORGANIZER_SUMMARY_TYPES):
            continue
        if not (sources & MONEY_BEARING_DOCUMENTS):
            continue
        kept: list[dict[str, str]] = []
        removed = Decimal(0)
        for entry in contributions:
            if str(entry.get('document_type') or '') in ORGANIZER_SUMMARY_TYPES:
                try:
                    removed += Decimal(str(entry.get('amount')))
                except (ArithmeticError, ValueError):
                    kept.append(entry)
                else:
                    dropped.append(
                        f"{name}={entry.get('amount')} (client organizer recap; "
                        f'the source form reports it)'
                    )
            else:
                kept.append(entry)
        if removed and name in totals:
            totals[name] -= removed
            provenance[name] = kept
    return dropped


def silent_document_review_item(document_type: str) -> dict[str, str]:
    """The item raised for a money-bearing document that reported nothing."""
    label = document_type.replace("_", " ").upper()
    return {
        "title": f"A {label} was read but reported no figures",
        "description": (
            f"The workpaper contains a {label}, and nothing from it reached "
            f"the return. A {label} exists to report an amount, so either it "
            "was unreadable or the figure was missed -- and the return was "
            "still produced without it.\n\n"
            "Check the document and enter the missing figures, or confirm "
            "it genuinely reports nothing."
        ),
    }


def restated_subtotal_review_item(risk: dict[str, str]) -> dict[str, str]:
    """The item raised when one document may state both a total and its detail."""
    contributions = risk["contributions"].split(", ")
    return {
        "title": f"Check {risk['field'].replace('_', ' ')} for a double count",
        "description": (
            f"One {risk['document_type'].replace('_', ' ')} supplied "
            f"{len(contributions)} separate figures for {risk['field']}, "
            f"totalling {risk['total']}: {risk['contributions']}.\n\n"
            "Organizers and consolidated statements state the same money "
            "twice -- a recap page for a category, then the individual "
            "forms behind it -- and both were added. Confirm each figure "
            "is separate money. If one is a recap of the others, remove it."
        ),
        "field_name": risk["field"],
        "proposed_value": risk["total"],
    }


def detect_restated_subtotals(
    field_provenance: dict[str, list[dict[str, str]]],
) -> list[dict[str, str]]:
    """Fields where one document may have stated both a total and its detail.

    Measured on a real workpaper: a client organizer carried a wage recap on
    page 12 (104,308 taxpayer + 58,500 spouse) and transcribed the two W-2s on
    pages 13 and 14 (118,453.63 and 46,213.60). All four were reported as
    ``wages`` and summed to 327,475.23 against a true 164,667.23 — an adjusted
    gross income of 329,557 where the accountant filed 166,749.

    This reports the risk rather than resolving it. Deciding which subset is the
    recap needs a tolerance — the two halves above differ by 1.1%, so they are
    not equal — and a rule loose enough to catch it is loose enough to delete a
    real second job. A reviewer given the contributions settles it in seconds;
    a wrong automatic choice is silent and unrecoverable.
    """
    risks: list[dict[str, str]] = []
    for name, contributions in sorted(field_provenance.items()):
        by_document: dict[str, list[Decimal]] = {}
        for entry in contributions:
            try:
                amount = Decimal(str(entry.get("amount")))
            except (ArithmeticError, ValueError):
                continue
            by_document.setdefault(str(entry.get("document_type") or ""), []).append(
                amount
            )
        for document_type, amounts in sorted(by_document.items()):
            if len(amounts) < _SUBTOTAL_RISK_CONTRIBUTIONS:
                continue
            risks.append(
                {
                    "field": name,
                    "document_type": document_type,
                    "total": str(sum(amounts)),
                    "contributions": ", ".join(str(a) for a in amounts),
                }
            )
    return risks


def merge_extractions(
    per_document: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    """Combine per-document extraction payloads into one workflow payload.

    Monetary fields **sum** across documents: a taxpayer with three 1099-INTs
    has the total of all three, and taking the last one seen would silently drop
    the rest. Scalar facts take the first document that states them. Amounts
    from ``NON_SOURCE_DOCUMENT_TYPES`` are excluded from the sum but their facts
    are still carried through for the reviewer.
    """
    facts: list[Any] = []
    confidences: dict[str, Any] = {}
    flags: list[str] = []
    missing: list[str] = []
    mappings: list[Any] = []
    totals: dict[str, Decimal] = {}
    scalars: dict[str, Any] = {}
    #: engine field -> the contributions that summed to it, for traceability.
    provenance: dict[str, list[dict[str, str]]] = {}
    #: scalar/identity field -> every candidate value and where it came from.
    scalar_candidates: dict[str, list[dict[str, str]]] = {}
    #: (field, amount) already counted, for duplicate detection.
    counted: set[tuple[str, Decimal]] = set()
    duplicates: list[str] = []
    #: (document_type, field) -> page, harvested from the facts so the merged
    #: normalized values can still say which leaf they came off.
    page_index: dict[tuple[str, str], str] = {}

    for document_type, payload in per_document:
        if not isinstance(payload, dict):
            continue

        for fact in payload.get("extracted_tax_facts") or []:
            if isinstance(fact, dict):
                # Provenance: which classified document this fact came from.
                fact.setdefault("document_type", document_type)
                facts.append(fact)
                field_name = str(fact.get("field") or "").strip()
                page = fact.get("page")
                if field_name and page not in (None, ""):
                    page_index.setdefault((document_type, field_name), str(page))

        mappings.extend(payload.get("output_mapping_instructions") or [])
        flags.extend(str(f) for f in (payload.get("review_flags") or []))
        missing.extend(str(m) for m in (payload.get("missing_information") or []))

        scores = payload.get("confidence_scores")
        if isinstance(scores, dict):
            for key, value in scores.items():
                confidences.setdefault(key, value)

        normalized = payload.get("normalized_fields")
        if not isinstance(normalized, dict):
            continue

        # Every candidate is kept with the document that stated it, not just
        # the first one seen.
        #
        # A workpaper routinely contains other people's documents: partnership
        # K-1s naming other partners, joint brokerage statements, a dependent's
        # 1098-T. On one sample return that produced four different spouse names
        # and two different dates of birth, and first-wins picked a 1987 birth
        # date over the taxpayer's real 1954 one — losing both age-65 additions
        # and, with them, the whole standard deduction.
        #
        # Choosing between candidates needs to know which document each came
        # from (an organizer states this taxpayer's own details; a K-1 does
        # not), so selection is deferred to TaxpayerProfileService.
        for key in _SCALAR_FIELDS:
            value = normalized.get(key)
            if value not in (None, ""):
                scalar_candidates.setdefault(key, []).append(
                    {"document_type": document_type, "value": str(value)}
                )
                scalars.setdefault(key, value)

        # Identity, canonicalised so a synonym does not blank the form.
        for raw_key, value in normalized.items():
            canonical = canonical_identity_field(raw_key)
            if canonical and value not in (None, ""):
                scalar_candidates.setdefault(canonical, []).append(
                    {"document_type": document_type, "value": str(value)}
                )
                scalars.setdefault(canonical, value)

        carryforward_only = document_type in NON_SOURCE_DOCUMENT_TYPES
        permitted = BUSINESS_ENTITY_FIELDS if document_type in BUSINESS_ENTITY_DOCUMENTS else None

        for name in ENGINE_MONEY_FIELDS:
            amount = _amount(normalized.get(name))
            if amount is None:
                continue

            # A prior-year return contributes its carryforwards and nothing
            # else. Those are the figures it is the correct source for; its
            # wages and withholding describe a year already filed.
            if carryforward_only and name not in CARRYFORWARD_FIELDS:
                continue

            # A business statement describes the entity, not the taxpayer. Its
            # "Social Security" line is employer payroll tax and its "health"
            # line is the company's insurance expense; read as personal fields
            # they became $25,428 of benefits and a $6,282 adjustment that no
            # human ever claimed. Such documents may report what flows through
            # to the return and nothing else.
            if permitted is not None and name not in permitted:
                logger.info(
                    "Ignoring %s from a %s: business statements cannot report "
                    "personal income or deductions.",
                    name,
                    document_type,
                )
                continue

            # ...and a form cannot report a figure it has no box for.
            allowed_sources = FIELD_SOURCE_DOCUMENTS.get(name)
            if allowed_sources is not None and document_type not in allowed_sources:
                logger.info(
                    "Ignoring %s from a %s: that form does not report it.",
                    name,
                    document_type,
                )
                duplicates.append(
                    f"{name}={amount} ({document_type} does not report this field)"
                )
                continue

            # Workpapers routinely contain the same form twice — a client sends
            # a copy, or a statement is filed with its own summary page. Summing
            # blindly doubled the sample return's interest (213.50 on two pages
            # of the same 1099-INT became 427) and its K-1 receipts. An
            # identical amount for the same field is one figure seen twice, not
            # two figures.
            #
            # The signature deliberately excludes the document type. It used to
            # include it, which missed the most expensive version of exactly the
            # case the paragraph above describes: a *consolidated* broker 1099
            # states its capital gains on a summary page and again across the
            # per-lot detail pages, and the classifier — correctly — labels
            # those pages `1099_div` and `1099_b`. Keying on the type made the
            # two look like separate documents, so the sample return's long-term
            # gain arrived as 7,344.95 twice. That inflated Schedule D from
            # 11,149 to 19,388 and, through provisional income, moved taxable
            # Social Security from 4,500 to 7,844 — a wrong figure on line 6b
            # produced by an entirely correct §86 worksheet.
            #
            # The cost of the wider rule is a taxpayer with two genuinely
            # distinct accounts reporting the identical amount, to the cent, for
            # the same field. That is rare, it was already the accepted trade-off
            # within a document type, and it never passes silently: every drop
            # is recorded in ``duplicates_ignored`` and raises a review flag.
            signature = (name, amount)
            if signature in counted:
                logger.info(
                    "Skipping duplicate %s of %s (second source: %s)",
                    amount,
                    name,
                    document_type,
                )
                duplicates.append(f"{name}={amount} ({document_type})")
                continue
            counted.add(signature)

            totals[name] = totals.get(name, Decimal(0)) + amount

            # Which document each contribution came from. The sum alone cannot
            # answer "where did line 2b's 214 come from", and that question is
            # the whole of traceability: a preparer signing the return has to be
            # able to walk every figure back to a page. Recorded per
            # contribution, not per field, because a field is routinely the sum
            # of several documents.
            entry = {"document_type": document_type, "amount": str(amount)}
            # The page, when a fact from this document named the same field.
            # "Which document" is most of traceability; "which page" is the rest
            # of it, and it is the difference between a reviewer opening a
            # 37-page workpaper and opening it at the right leaf.
            page = page_index.get((document_type, name))
            if page:
                entry["page"] = str(page)
            provenance.setdefault(name, []).append(entry)

    # A client organizer recaps the forms behind it. Where a source form also
    # reported the field, its recap is the same money written twice.
    duplicates.extend(drop_organizer_restatements(totals, provenance))

    merged_normalized: dict[str, Any] = {k: str(v) for k, v in totals.items()}
    merged_normalized.update(scalars)

    return {
        "extracted_tax_facts": facts,
        "normalized_fields": merged_normalized,
        "field_provenance": provenance,
        "scalar_candidates": scalar_candidates,
        "confidence_scores": confidences,
        # Surfaced, not silent: dropping a duplicate is a judgement, and a
        # preparer who genuinely has two accounts paying identical interest
        # needs to see that one of them was treated as a repeat.
        "review_flags": sorted(
            set(flags) | ({"duplicate_amounts_ignored"} if duplicates else set())
        ),
        "duplicates_ignored": duplicates,
        "missing_information": sorted(set(missing)),
        "output_mapping_instructions": mappings,
    }


_EXTRACTION_SYSTEM_INSTRUCTION = """\
You are a US tax document extraction engine for a professional accounting firm.

You are reading a MASKED document. Names, identification numbers, addresses, and \
account numbers have been replaced with synthetic substitutes. Treat them as \
ordinary values, extract them as they appear, and never comment on them.

Extract only what is present. Never infer, estimate, or invent a value. If a \
field is unreadable or absent, list it in missing_information rather than \
guessing.

Do NOT perform final arithmetic. Report the figures you can see; totals are \
recomputed independently. If you do state a computed value, mark it clearly in \
calculations so it can be checked.

Respond with JSON only:
{
  "extracted_tax_facts": [
    {"field": "wages", "value": "34833.37", "label": "Box 1",
     "page": 3, "confidence": 0.95, "document_type": "w2"}
  ],
  "normalized_fields": {"wages": "34833.37"},
  "tax_workpaper_adjustments": [],
  "calculations": [],
  "assumptions": [],
  "missing_information": [],
  "confidence_scores": {"wages": 0.95},
  "review_flags": [],
  "output_mapping_instructions": [
    {"field": "wages", "target_form": "1040", "target_line": "1a"}
  ]
}

In normalized_fields use these exact names wherever the document supports them.
Report the amount as a plain number string, without currency symbols or commas,
and use a leading minus for a loss. Omit a name entirely rather than reporting
it as zero: an omitted field means "not present in this document", a zero means
"the document states zero", and the two produce different returns.

""" + "\n".join(
    textwrap.wrap(", ".join(ENGINE_MONEY_FIELDS), width=76)
) + """

Also report, when the document states them: tax_year, filing_status,
qualifying_children, and other_dependents.

For taxpayer identity use exactly these names, and copy the value as printed:

""" + "\n".join(
    textwrap.wrap(", ".join(IDENTITY_FIELDS), width=76)
) + """

date_of_birth drives age-based deductions, so report it whenever a document
shows it. Never invent an identity value that is not printed on the page."""


def _source_document_types(payload: dict[str, Any]) -> dict[str, str]:
    """Field name -> the document type that reported it.

    `field_provenance` records this per monetary contribution and
    `scalar_candidates` per identity field; between them they cover what
    extraction produced. A field summed from several documents keeps the
    first, because one `ExtractionResult` row can only point at one document —
    the workpaper's provenance sheet still lists every contribution.
    """
    sources: dict[str, str] = {}
    for group in (payload.get("field_provenance"), payload.get("scalar_candidates")):
        if not isinstance(group, dict):
            continue
        for name, entries in group.items():
            if name in sources or not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                document_type = str(entry.get("document_type") or "").strip()
                if document_type:
                    sources[str(name)] = document_type
                    break
    return sources


def _figure_box(
    document: Document | None, page: int | None, value: Any
) -> list[float] | None:
    """Where on its page an extracted figure sits, when that is unambiguous."""
    if document is None or page is None or not isinstance(document.layout, dict):
        return None
    for entry in document.layout.get("pages") or []:
        if isinstance(entry, dict) and entry.get("page") == page:
            return locate(value, entry.get("figures") or [])
    return None


def _pick_document(candidates: list[Document], page: int | None) -> Document | None:
    """Which of several documents of one type covers this page."""
    if not candidates:
        return None
    if page is not None:
        for candidate in candidates:
            if candidate.page_start <= page <= candidate.page_end:
                return candidate
    return candidates[0]


def _why_this_field_needs_checking(
    reason: ReviewReason,
    *,
    confidence: float,
    ocr_confidence: float | None,
    field_floor: float,
    ocr_floor: float,
) -> str:
    """The check that actually fired, in the numbers that fired it.

    This read "Extracted with {confidence} confidence, below the {field_floor}
    threshold" whatever the reason was, and two of the three reasons do not
    test that at all. A field read at 95% off a page whose OCR scored 41%
    produced "Extracted with 95% confidence, below the 90% threshold" — a
    sentence that contradicts itself — and handwriting, whose floor is 95%,
    produced "Extracted with 90% confidence, below the 90% threshold". Those
    are the majority of the items: sixty to ninety per workpaper. A reviewer
    who reads two of them stops reading the rest, which is the real cost.

    The branches mirror `assess_field_confidence` in the same order, because
    the first one to match there is the one that made the decision here.
    """
    if reason is ReviewReason.HANDWRITING_UNCERTAIN:
        return (
            f"This page is handwritten and the value was read with "
            f"{confidence:.0%} confidence. Handwriting has to clear 95% before "
            f"a figure is taken from it without a second look."
        )
    if ocr_confidence is not None and ocr_confidence < ocr_floor:
        return (
            f"The page this came off scored {ocr_confidence:.0%} mean word "
            f"confidence, under the {ocr_floor:.0%} floor, so every figure read "
            f"from it needs checking against the document. This one was "
            f"extracted at {confidence:.0%}."
        )
    return (
        f"Extracted with {confidence:.0%} confidence, below the "
        f"{field_floor:.0%} threshold."
    )


def _seniors_in_household(
    normalized: dict[str, Any],
    tax_year: int,
    *,
    filing_status: FilingStatusTax | None = None,
) -> int:
    """How many senior additions this return gets by the end of the tax year.

    The spouse counts only on a joint return — see
    `TaxpayerProfileResult.seniors`, which applies the same rule to the figure
    the engine actually consumes. This one feeds the explanation, and the two
    disagreeing would put a different household on the screen from the one in
    the arithmetic.
    """
    keys: tuple[str, ...] = ("date_of_birth", "spouse_date_of_birth")
    if filing_status is not FilingStatusTax.MARRIED_JOINT:
        keys = ("date_of_birth",)
    seniors = 0
    for key in keys:
        age = age_on(normalized.get(key), tax_year=tax_year)
        if age is not None and age >= 65:
            seniors += 1
    return seniors


def _summarize_pages(pages: list[int], *, limit: int = 12) -> str:
    """Render page numbers as compact ranges: ``1-4, 8, 16-37``.

    A reviewer needs to see *which* pages failed, but 28 comma-separated
    integers in a queue item is unreadable, so consecutive runs collapse.
    """
    if not pages:
        return "none"

    ordered = sorted(set(pages))
    runs: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for page in ordered[1:]:
        if page == previous + 1:
            previous = page
            continue
        runs.append((start, previous))
        start = previous = page
    runs.append((start, previous))

    rendered = [str(a) if a == b else f"{a}-{b}" for a, b in runs]
    if len(rendered) > limit:
        remaining = len(rendered) - limit
        return ", ".join(rendered[:limit]) + f", and {remaining} more"
    return ", ".join(rendered)


def _stage_note(stage: WorkflowStage, detail: dict[str, Any]) -> str:
    """One line of plain English about what a finished stage actually found.

    SECURITY: built from the stage's audit detail, which is counters only. It
    must stay that way — this string is shown to whoever is watching and is not
    covered by any later masking step.
    """
    if stage is WorkflowStage.OCR:
        pages = detail.get("page_count") or 0
        blocked = len(detail.get("blocked_pages") or [])
        low = len(detail.get("low_confidence_pages") or [])
        # Plain ASCII: these notes are logged as well as streamed, and the
        # Windows console encoding is not guaranteed to be UTF-8.
        label = "page" if pages == 1 else "pages"
        if blocked:
            return f"Read {pages} {label} - {blocked} could not be read at all"
        if low:
            return f"Read all {pages} {label} - {low} need checking"
        return (
            "Read the page clearly" if pages == 1
            else f"Read all {pages} pages clearly"
        )

    if stage is WorkflowStage.CLASSIFICATION:
        segments = detail.get("segments") or 0
        return f"Found {segments} separate document{'s' if segments != 1 else ''}"

    if stage is WorkflowStage.LLM_PROCESSING:
        facts = detail.get("facts_returned") or 0
        documents = detail.get("documents_extracted") or 0
        if detail.get("skipped"):
            return "Nothing readable to work from"
        return (
            f"Pulled {facts} figure{'s' if facts != 1 else ''} "
            f"from {documents} document{'s' if documents != 1 else ''}"
        )

    if stage is WorkflowStage.OUTPUT:
        artifacts = detail.get("artifacts") or 0
        return f"Wrote {artifacts} file{'s' if artifacts != 1 else ''}"

    return ""


@dataclass(slots=True)
class StageOutput:
    """What a stage produces, split into working data and auditable detail.

    SECURITY: the split is the point. A stage's ``value`` is its real output —
    masked page text, extraction payloads, computed returns — and must never be
    written to the audit log or the stage record. Only ``detail`` is persisted,
    and it is expected to hold counters and identifiers exclusively.

    Inferring detail from a stage's return value (the earlier design) silently
    wrote document content into the audit trail the moment a stage happened to
    return a dict. ``_run_stage`` now records nothing unless the stage
    deliberately supplies it.
    """

    value: Any = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StageOutcome:
    stage: WorkflowStage
    status: StageStatus
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0


@dataclass(slots=True)
class PipelineResult:
    workflow_id: str
    status: WorkflowStatus
    stages: list[StageOutcome] = field(default_factory=list)
    documents_detected: int = 0
    pii_masked: int = 0
    facts_extracted: int = 0
    review_items: int = 0
    overall_confidence: float = 0.0
    packages_generated: int = 0
    #: True when the run needs last year's return and did not get it. Surfaced
    #: so the UI can ask for the upload rather than burying it in the queue.
    prior_year_requested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "prior_year_requested": self.prior_year_requested,
            "documents_detected": self.documents_detected,
            "pii_masked": self.pii_masked,
            "facts_extracted": self.facts_extracted,
            "review_items": self.review_items,
            "overall_confidence": round(self.overall_confidence, 3),
            "packages_generated": self.packages_generated,
            "stages": [
                {
                    "stage": s.stage.value,
                    "status": s.status.value,
                    "duration_ms": s.duration_ms,
                    "detail": s.detail,
                    "error": s.error,
                }
                for s in self.stages
            ],
        }


class WorkflowOrchestrator:
    """Runs an uploaded file through the full pipeline."""

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
        audit: AuditLogger | None = None,
        gemini: GeminiService | None = None,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._audit = audit or AuditLogger(session)
        # Optional observer, called as each stage starts and finishes. Used by
        # the streaming endpoint so a three-minute wait shows what it is doing
        # instead of nothing at all.
        self._progress = progress
        self._ocr = OcrService(self._settings)
        self._classifier = ClassificationService()
        self._detector = PiiDetectionService(DetectionConfig())
        #: Per-run: the dataclasses handed to the calculator, kept so the
        #: output stage can render the schedules behind each total.
        self._engine_inputs: dict[str, Any] | None = None
        self._validator = TaxValidationService(self._settings)
        self._gemini = gemini
        self._working_copy: Path | None = None

    # ------------------------------------------------------------------ API

    def run(
        self,
        uploaded_file: UploadedFile,
        *,
        actor_id: str | None = None,
        tax_year: int | None = None,
    ) -> PipelineResult:
        """Execute every stage. Always cleans up the plaintext working copy."""
        workflow = Workflow(
            uploaded_file_id=uploaded_file.id,
            filing_id=uploaded_file.filing_id,
            status=WorkflowStatus.RUNNING.value,
            current_stage=WorkflowStage.UPLOAD.value,
            started_at=datetime.now(UTC),
            triggered_by=actor_id,
        )
        self._session.add(workflow)
        self._session.flush()

        self._audit.record(
            AuditAction.WORKFLOW_STARTED,
            actor_id=actor_id,
            entity_type="workflow",
            entity_id=workflow.id,
            payload={"uploaded_file_id": uploaded_file.id},
        )

        result = PipelineResult(
            workflow_id=workflow.id, status=WorkflowStatus.RUNNING
        )
        masker = MaskingService(
            self._session,
            workflow_id=workflow.id,
            filing_id=uploaded_file.filing_id,
            style=MaskStyle.SURROGATE,
            audit=self._audit,
        )

        try:
            # --- 1. Upload: materialise a decrypted working copy ----------
            extraction = self._run_stage(
                workflow, WorkflowStage.UPLOAD, result,
                lambda: self._stage_upload(uploaded_file, actor_id),
            )

            # --- 2 & 3. OCR then classification --------------------------
            # OCR must precede classification: the corpus is scanned, so there
            # is no text to classify until OCR has run.
            document_extraction = self._run_stage(
                workflow, WorkflowStage.OCR, result,
                lambda: self._stage_ocr(workflow, result),
            )
            segments = self._run_stage(
                workflow, WorkflowStage.CLASSIFICATION, result,
                lambda: self._stage_classification(workflow, document_extraction),
            )

            # --- 4. Masking — the privacy boundary ------------------------
            masked_pages = self._run_stage(
                workflow, WorkflowStage.MASKING, result,
                lambda: self._stage_masking(
                    workflow, document_extraction, segments, masker, result
                ),
            )

            # --- 5. LLM (masked content only) -----------------------------
            llm_payload = self._run_stage(
                workflow, WorkflowStage.LLM_PROCESSING, result,
                lambda: self._stage_llm(workflow, masked_pages, segments, masker),
            )

            # --- 6. Deterministic validation ------------------------------
            computed_return = self._run_stage(
                workflow, WorkflowStage.VALIDATION, result,
                lambda: self._stage_validation(
                    workflow, llm_payload, tax_year, result
                ),
            )

            # --- 7. Review routing ----------------------------------------
            self._run_stage(
                workflow, WorkflowStage.REVIEW, result,
                lambda: self._stage_review(workflow, result),
            )

            # --- 8 & 9. Rehydration then output ---------------------------
            rehydrator = RehydrationService(
                self._session, workflow_id=workflow.id, audit=self._audit
            )
            self._run_stage(
                workflow, WorkflowStage.REHYDRATION, result,
                lambda: StageOutput(
                    value=None, detail={"vault_entries": rehydrator.vault_size}
                ),
            )
            self._run_stage(
                workflow, WorkflowStage.OUTPUT, result,
                lambda: self._stage_output(workflow, computed_return, rehydrator, result),
            )

            workflow.status = (
                WorkflowStatus.AWAITING_REVIEW.value
                if result.review_items
                else WorkflowStatus.COMPLETED.value
            )
            result.status = WorkflowStatus(workflow.status)

        except Exception as exc:
            workflow.status = WorkflowStatus.FAILED.value
            # SECURITY: only our own error text is stored. AppError messages are
            # written for a client audience and never interpolate document
            # content; anything else contributes a type name only, because an
            # arbitrary exception's string can carry file content.
            if isinstance(exc, AppError):
                workflow.error_summary = exc.message
            else:
                workflow.error_summary = (
                    f"Processing failed during {workflow.current_stage} "
                    f"({type(exc).__name__}). No output package was produced."
                )
            result.status = WorkflowStatus.FAILED
            self._audit.record(
                AuditAction.WORKFLOW_FAILED,
                entity_type="workflow",
                entity_id=workflow.id,
                payload={
                    "stage": workflow.current_stage,
                    "error_type": type(exc).__name__,
                },
            )
            logger.error(
                "Workflow %s failed at %s: %s",
                workflow.id,
                workflow.current_stage,
                type(exc).__name__,
            )
            if not isinstance(exc, PipelineError):
                raise PipelineError(workflow.error_summary) from exc
            raise

        finally:
            # SECURITY: the decrypted working copy must not outlive the run.
            self._cleanup_working_copy()
            workflow.completed_at = datetime.now(UTC)
            workflow.progress_percent = 100.0 if result.status != WorkflowStatus.FAILED else (
                workflow.progress_percent
            )
            workflow.documents_detected = result.documents_detected
            workflow.pii_entities_masked = result.pii_masked
            workflow.review_items_open = result.review_items
            workflow.overall_confidence = result.overall_confidence

        self._audit.record(
            AuditAction.WORKFLOW_COMPLETED,
            entity_type="workflow",
            entity_id=workflow.id,
            payload=result.to_dict() | {"stages": len(result.stages)},
        )
        return result

    # ---------------------------------------------------------- stage runner

    def _run_stage(
        self,
        workflow: Workflow,
        stage: WorkflowStage,
        result: PipelineResult,
        operation: Any,
    ) -> Any:
        index = WORKFLOW_STAGE_ORDER.index(stage)
        workflow.current_stage = stage.value
        workflow.progress_percent = round(
            index / len(WORKFLOW_STAGE_ORDER) * 100, 1
        )

        run = WorkflowStageRun(
            workflow_id=workflow.id,
            stage=stage.value,
            stage_index=index,
            status=StageStatus.RUNNING.value,
            started_at=datetime.now(UTC),
        )
        self._session.add(run)
        self._session.flush()

        self._audit.record(
            AuditAction.WORKFLOW_STAGE_STARTED,
            entity_type="workflow",
            entity_id=workflow.id,
            payload={"stage": stage.value},
        )
        self._emit_progress(
            stage=stage,
            index=index,
            status="running",
            workflow_id=workflow.id,
        )

        started = time.monotonic()
        try:
            # Every model call inside the stage is charged to this return and
            # this stage - the cost panel's split comes from here.
            with metered(workflow_id=workflow.id, stage=stage.value):
                output = operation()
        except Exception as exc:
            run.status = StageStatus.FAILED.value
            run.error_message = f"{type(exc).__name__}"
            run.completed_at = datetime.now(UTC)
            run.duration_ms = int((time.monotonic() - started) * 1000)
            self._audit.record(
                AuditAction.WORKFLOW_STAGE_FAILED,
                entity_type="workflow",
                entity_id=workflow.id,
                payload={"stage": stage.value, "error_type": type(exc).__name__},
            )
            result.stages.append(
                StageOutcome(stage, StageStatus.FAILED, error=type(exc).__name__)
            )
            self._emit_progress(
                stage=stage,
                index=index,
                status="failed",
                workflow_id=workflow.id,
            )
            raise

        duration = int((time.monotonic() - started) * 1000)
        # SECURITY: fail closed. Only a stage that explicitly returns a
        # StageOutput contributes audit detail; anything else records nothing.
        # The previous behaviour — treating any returned dict as detail — wrote
        # masked page text and extraction payloads into the audit log, because
        # those stages happen to return dicts.
        if isinstance(output, StageOutput):
            detail = output.detail
            result_value: Any = output.value
        else:
            detail = {}
            result_value = output

        run.status = StageStatus.COMPLETED.value
        run.completed_at = datetime.now(UTC)
        run.duration_ms = duration
        run.detail = _summarize_detail(detail)

        self._audit.record(
            AuditAction.WORKFLOW_STAGE_COMPLETED,
            entity_type="workflow",
            entity_id=workflow.id,
            payload={"stage": stage.value, "duration_ms": duration, **run.detail},
        )
        result.stages.append(
            StageOutcome(stage, StageStatus.COMPLETED, run.detail, duration_ms=duration)
        )
        self._emit_progress(
            stage=stage,
            index=index,
            status="completed",
            workflow_id=workflow.id,
            # The FULL detail, not run.detail. _summarize_detail keeps only
            # scalars so that no document content reaches the persisted audit
            # record — which also strips `blocked_pages` and
            # `low_confidence_pages`, the two lists this note exists to report.
            # Reading the filtered copy meant both counts were always zero, so
            # a 55-page workpaper where every single page failed to read still
            # announced "Read all 55 pages clearly". _stage_note only ever
            # pulls named counters out of this dict, never free text.
            note=_stage_note(stage, detail),
        )
        return result_value

    def _emit_progress(
        self,
        *,
        stage: WorkflowStage,
        index: int,
        status: str,
        workflow_id: str,
        note: str = "",
    ) -> None:
        """Tell the observer where we are, if anyone is listening.

        SECURITY: carries the stage label, a percentage, and a note built from
        counters only — never extracted values or page text. It travels the same
        route as the audit detail and is held to the same rule.
        """
        if self._progress is None:
            return
        total = len(WORKFLOW_STAGE_ORDER)
        try:
            self._progress(
                {
                    "workflow_id": workflow_id,
                    "stage": stage.value,
                    "label": STAGE_LABELS.get(stage, stage.value),
                    "status": status,
                    "step": index + 1,
                    "steps": total,
                    "percent": round(
                        (index + (1 if status == "completed" else 0)) / total * 100
                    ),
                    "note": note,
                }
            )
        except Exception:  # pragma: no cover - a watcher must never break a run
            logger.debug("Progress observer raised; continuing the pipeline")

    # ---------------------------------------------------------------- stages

    def _stage_upload(self, uploaded_file: UploadedFile, actor_id: str | None) -> dict[str, Any]:
        ingestion = IngestionService(
            self._session, settings=self._settings, audit=self._audit
        )
        try:
            self._working_copy = ingestion.materialize(uploaded_file, actor_id=actor_id)
        except DecryptionKeyMismatchError as exc:
            # Retrying will never succeed, so mark the file rather than leaving
            # it in a state that invites the user to try again forever.
            #
            # The flag cannot be written here: this session is inside a write
            # transaction that is about to roll back, and a second connection
            # would block on SQLite's writer lock. The file id travels on the
            # error instead, and ``core.errors`` performs the write once the
            # request's transaction has been released.
            logger.error(
                "File %s cannot be decrypted with the current key.",
                uploaded_file.id,
            )
            raise UnreadableFileError(
                str(exc), details={"uploaded_file_id": uploaded_file.id}
            ) from exc

        uploaded_file.status = FileStatus.PROCESSING.value
        return StageOutput(
            value=None,
            detail={
                "size_bytes": uploaded_file.size_bytes,
                "extension": uploaded_file.extension,
            },
        )

    def _stage_ocr(self, workflow: Workflow, result: PipelineResult) -> StageOutput:
        if self._working_copy is None:
            raise PipelineError("No working copy is available for extraction.")

        extraction = self._ocr.extract(self._working_copy)

        if extraction.blocked_pages:
            self._audit.record(
                AuditAction.OCR_UNAVAILABLE,
                entity_type="workflow",
                entity_id=workflow.id,
                payload={
                    "blocked_pages": len(extraction.blocked_pages),
                    "total_pages": len(extraction.pages),
                },
            )
            # A page nobody could read is the single most consequential thing
            # that can happen to a return, because it is invisible downstream:
            # the extractor simply finds no income on it and the engine computes
            # a smaller, entirely well-formed return. This previously recorded
            # only the audit event above, so a 37-page workpaper read at 24%
            # produced a $0 return with an empty exceptions report. It must
            # reach a human.
            pages = extraction.blocked_pages
            self._add_review_item(
                workflow,
                reason=ReviewReason.OCR_UNAVAILABLE,
                title=(
                    f"{len(pages)} of {len(extraction.pages)} pages could not be "
                    "read"
                ),
                description=(
                    "No text layer and no usable OCR result for page(s) "
                    f"{_summarize_pages(pages)}. Any income, deduction, or "
                    "withholding reported only on those pages is missing from "
                    "the computed return. Confirm the source scan quality and "
                    "that a local OCR engine is installed before relying on "
                    "these figures."
                ),
                priority=1,
            )
            result.review_items += 1

        low_confidence = extraction.low_confidence_pages
        if low_confidence:
            self._add_review_item(
                workflow,
                reason=ReviewReason.LOW_CONFIDENCE,
                title=f"{len(low_confidence)} page(s) read below the confidence floor",
                description=(
                    f"Page(s) {_summarize_pages(low_confidence)} scored under "
                    f"{self._settings.ocr_min_confidence:.0f}% mean word "
                    "confidence. Values transcribed from them need verification "
                    "against the source document."
                ),
                priority=2,
            )
            result.review_items += 1

        if not extraction.blocked_pages:
            self._audit.record(
                AuditAction.OCR_PERFORMED,
                entity_type="workflow",
                entity_id=workflow.id,
                payload=extraction.summary(),
            )
        # summary() is counters only — safe as stage detail.
        return StageOutput(value=extraction, detail=extraction.summary())

    def _stage_classification(
        self, workflow: Workflow, extraction: DocumentExtraction
    ) -> StageOutput:
        classifications = self._classifier.classify_pages(extraction.page_texts)
        segments = self._classifier.segment(classifications)

        self._audit.record(
            AuditAction.DOCUMENT_CLASSIFIED,
            entity_type="workflow",
            entity_id=workflow.id,
            payload={
                "segments": len(segments),
                "types": sorted({s.document_type.value for s in segments}),
            },
        )
        return StageOutput(
            value=segments,
            detail={
                "segments": len(segments),
                "types": ",".join(sorted({s.document_type.value for s in segments})),
            },
        )

    def _stage_masking(
        self,
        workflow: Workflow,
        extraction: DocumentExtraction,
        segments: list[Any],
        masker: MaskingService,
        result: PipelineResult,
    ) -> StageOutput:
        """Detect and mask PII. Everything downstream sees only the output.

        SECURITY: this is the privacy boundary. If detection is impaired (no
        spaCy model), affected documents are flagged for review rather than
        being passed on under-masked.
        """
        masked_pages: dict[int, str] = {}
        # SECURITY: money-shaped words only, minus anything the detector
        # flagged - see figure_boxes. The drill-down's highlight box.
        figures_by_page: dict[int, list[dict[str, Any]]] = {}
        all_spans_count = 0
        detector_degraded = not self._detector.ner_available

        for page in extraction.pages:
            if not page.text.strip():
                masked_pages[page.page_number] = ""
                continue
            spans = self._detector.detect(page.text, page_number=page.page_number)
            masking = masker.mask_text(page.text, spans)
            masked_pages[page.page_number] = masking.masked_text
            figures_by_page[page.page_number] = figure_words(
                page.words, (span.text for span in spans)
            )
            all_spans_count += len(spans)

            if spans:
                self._audit.record(
                    AuditAction.PII_DETECTED,
                    entity_type="workflow",
                    entity_id=workflow.id,
                    payload={
                        "page": page.page_number,
                        **summarize_detections(spans),
                    },
                )

        result.pii_masked = all_spans_count

        # Reprocessing the same upload must replace its documents, not add to
        # them. Without this, each /process call appended a fresh row per
        # segment: a single 37-page PDF run three times reported "Documents
        # detected: 3", and validation then picked documents[0] — a stale row
        # from an earlier, possibly worse extraction — as the primary document
        # that every extracted fact was attributed to.
        superseded = (
            self._session.query(Document)
            .filter(Document.uploaded_file_id == workflow.uploaded_file_id)
            .all()
        )
        if superseded:
            logger.info(
                "Replacing %d document row(s) from a previous run of file %s",
                len(superseded),
                workflow.uploaded_file_id,
            )
            for stale in superseded:
                self._session.delete(stale)
            self._session.flush()

        # Persist a Document row per segment, holding masked text only.
        for segment in segments:
            page_texts = [
                masked_pages.get(p, "")
                for p in range(segment.page_start, segment.page_end + 1)
            ]
            combined = "\n\n".join(t for t in page_texts if t)
            source_pages = [
                p for p in extraction.pages
                if segment.page_start <= p.page_number <= segment.page_end
            ]

            document = Document(
                uploaded_file_id=workflow.uploaded_file_id,
                document_type=segment.document_type.value,
                classification_confidence=segment.confidence,
                classification_method=segment.method,
                page_start=segment.page_start,
                page_end=segment.page_end,
                page_count=segment.page_count,
                requires_ocr=any(p.is_scanned for p in source_pages),
                ocr_performed=any(
                    p.method.value.startswith("ocr") for p in source_pages
                ),
                ocr_engine=extraction.engine,
                ocr_mean_confidence=(
                    sum(p.mean_confidence for p in source_pages) / len(source_pages)
                    if source_pages
                    else None
                ),
                is_handwritten=any(p.has_handwriting_hint for p in source_pages),
                source_text_hash=sha256_bytes(combined.encode("utf-8")),
                layout={
                    "pages": [
                        {
                            **p.to_layout_dict(),
                            "figures": figures_by_page.get(p.page_number, []),
                        }
                        for p in source_pages
                    ]
                },
            )
            self._session.add(document)
            self._session.flush()

            # Write masked text to the masked zone for the review UI.
            masked_dir = self._settings.masked_zone_dir / workflow.id
            masked_dir.mkdir(parents=True, exist_ok=True)
            masked_path = masked_dir / f"{document.id}.txt"
            masked_path.write_text(combined, encoding="utf-8")
            document.masked_text_path = str(masked_path)
            # The same text split by page, so a figure's drill-down can open
            # the one page it came off. Masked zone, masked content only.
            (masked_dir / f"{document.id}.pages.json").write_text(
                json.dumps(
                    {
                        str(number): masked_pages.get(number, "")
                        for number in range(segment.page_start, segment.page_end + 1)
                    }
                ),
                encoding="utf-8",
            )

            if detector_degraded:
                self._add_review_item(
                    workflow,
                    document_id=document.id,
                    reason=ReviewReason.UNMASKED_PII_SUSPECTED,
                    title="Name detection was unavailable for this document",
                    description=(
                        "The spaCy NER model could not be loaded, so person and "
                        "organisation names were not detected. Verify the masked "
                        "preview before releasing any output. Fix with: "
                        "python -m spacy download en_core_web_sm"
                    ),
                    priority=1,
                )
                result.review_items += 1

        result.documents_detected = len(segments)
        # SECURITY: masked_pages holds document text and must stay out of the
        # audit record. Only counters are reported as detail.
        return StageOutput(
            value=masked_pages,
            detail={
                "documents": len(segments),
                "values_masked": all_spans_count,
                "pages": len(masked_pages),
                "detector_degraded": detector_degraded,
            },
        )

    def _stage_llm(
        self,
        workflow: Workflow,
        masked_pages: dict[int, str],
        segments: list[Any],
        masker: MaskingService,
    ) -> StageOutput:
        """Send masked content to the model, behind the egress guard."""
        gemini = self._gemini or GeminiService(
            settings=self._settings,
            guard=build_guard(masking_service=masker, audit=self._audit),
            audit=self._audit,
            meter=DbLlmMeter(self._session),
        )

        if not any(text.strip() for text in masked_pages.values()):
            logger.info("No readable text to send to the model")
            return StageOutput(
                value={
                    "extracted_tax_facts": [],
                    "normalized_fields": {},
                    "confidence_scores": {},
                    "review_flags": ["no_readable_text"],
                    "missing_information": [
                        "No text could be extracted from this file. Install "
                        "local OCR or supply a text-based document."
                    ],
                },
                detail={"skipped": True, "reason": "no_readable_text"},
            )

        handwriting = any(
            document.is_handwritten
            for document in self._session.query(Document).filter(
                Document.uploaded_file_id == workflow.uploaded_file_id
            )
        )

        # One call per classified document rather than one call for the upload.
        # A single 103,000-character prompt spanning eleven document types
        # returned six facts from a fully-read 37-page workpaper — the model
        # cannot hold a 1099-B, a 1098-T, an organizer and a prior-year return
        # in focus simultaneously. Per-document prompts are small enough to read
        # closely, carry a form-specific hint, and give every fact real
        # provenance.
        #
        # Sequential deliberately. Each call writes audit events and the audit
        # log is a hash chain: concurrent writers would interleave and break it.
        # Parallelising extraction requires a serialised audit writer first —
        # it is already on the README's production checklist.
        per_document: list[tuple[str, dict[str, Any]]] = []
        usage_totals: dict[str, int] = {}
        calls = 0

        for segment in segments:
            body = "\n\n".join(
                f"<<<PAGE {page}>>>\n{masked_pages.get(page, '')}"
                for page in range(segment.page_start, segment.page_end + 1)
                if masked_pages.get(page, "").strip()
            )
            if not body.strip():
                continue

            document_type = segment.document_type.value
            prompt = (
                f"Document type: {document_type}\n"
                f"Pages {segment.page_start}-{segment.page_end} of this upload.\n\n"
                f"{_EXTRACTION_HINTS.get(document_type, _DEFAULT_EXTRACTION_HINT)}\n\n"
                f"{body[:200_000]}"
            )

            response = gemini.generate_json(
                prompt=prompt,
                task=TaskKind.DOCUMENT_EXTRACTION,
                signals=RoutingSignals(
                    handwriting=handwriting,
                    approx_input_tokens=len(prompt) // 4,
                    batch_size=segment.page_count,
                ),
                system_instruction=_EXTRACTION_SYSTEM_INSTRUCTION,
                context=f"document_extraction:{document_type}",
            )
            calls += 1
            for key, value in response.usage_dict().items():
                if isinstance(value, int):
                    usage_totals[key] = usage_totals.get(key, 0) + value
            if isinstance(response.data, dict):
                per_document.append((document_type, response.data))

        # SECURITY-adjacent, and a correctness trap: a stub answers with an
        # empty extraction, so a run where every call was stubbed produces a
        # well-formed, entirely empty return package. It happened here -- the
        # API key is read relative to the working directory, so launching the
        # pipeline from the repository root instead of `backend/` silently
        # disabled the LLM and still wrote seven artifacts, a "completed"
        # workflow and zero review items. An operator has no way to tell that
        # from a taxpayer with no income.
        stubbed = int(usage_totals.get("stub", 0))
        if calls and stubbed == calls and self._settings.gemini_enabled:
            raise PipelineError(
                "Extraction is configured to use the LLM but all "
                f"{calls} calls returned offline stubs, so no figures were "
                "read from any document. Check that GEMINI_API_KEY is visible "
                "to the process (settings are read relative to the working "
                "directory) and that google-genai is installed in the "
                "interpreter that is running. No return was produced."
            )

        merged = merge_extractions(per_document)
        # Carried through so the validation stage can run each form's own
        # box-level checks. The merge flattens document boundaries, and a W-2
        # FICA tie-out is meaningless once three W-2s have been summed.
        merged["_per_document"] = [
            {"document_type": dtype, "normalized_fields": payload.get("normalized_fields") or {}}
            for dtype, payload in per_document
            if isinstance(payload, dict)
        ]
        workflow.llm_usage = usage_totals
        # SECURITY: `merged` holds extracted field values. Only usage metrics
        # and counters are auditable.
        return StageOutput(
            value=merged,
            detail={
                **usage_totals,
                "llm_calls": calls,
                "documents_extracted": len(per_document),
                "facts_returned": len(merged["extracted_tax_facts"]),
            },
        )

    def _stage_validation(
        self,
        workflow: Workflow,
        payload: dict[str, Any],
        tax_year: int | None,
        result: PipelineResult,
    ) -> StageOutput:
        """Validate the model's output and recompute the return."""
        reports = [self._validator.validate_extraction_schema(payload)]

        # --- Per-document box-level checks --------------------------------
        # W-2 FICA recomputation, 1099-DIV box 1b against 1a, 1099-B proceeds
        # less basis, depreciation and trial-balance recomputes. All of these
        # existed and were tested; none was ever called, so the live pipeline
        # had no box-level validation at all and a decimal-shifted withholding
        # box reached the return unchallenged.
        year_for_documents = tax_year or _infer_year(
            payload.get("normalized_fields") or {}
        ) or _assumed_return_year().year
        for entry in payload.get("_per_document") or []:
            if not isinstance(entry, dict):
                continue
            reports.append(
                self._validator.validate_document(
                    str(entry.get("document_type") or ""),
                    entry.get("normalized_fields") or {},
                    tax_year=year_for_documents,
                )
            )

        documents = list(
            self._session.query(Document).filter(
                Document.uploaded_file_id == workflow.uploaded_file_id
            )
        )
        primary_document = documents[0] if documents else None

        # Which Document row each fact actually came off.
        #
        # Every fact used `documents[0]` — whatever row the query happened to
        # return first. Two things followed. Each `ExtractionResult` claimed
        # provenance it did not have, and "which document and page did this
        # figure come off" is the question the workpaper exists to answer. And
        # `assess_field_confidence` read that one row's OCR score and
        # handwriting flag for *every* fact, so a single handwritten organizer
        # page at the head of the list flagged all 84 figures on Basic 7 as
        # needing review — most of them off pages that were read cleanly. A
        # queue of ninety items, nearly all of them wrong, is a queue nobody
        # reads.
        by_type: dict[str, list[Document]] = {}
        for row in documents:
            by_type.setdefault(str(row.document_type), []).append(row)
        source_types = _source_document_types(payload)

        # Persist each extracted fact.
        facts = payload.get("extracted_tax_facts") or []
        mapping = {
            str(m.get("field")): m
            for m in (payload.get("output_mapping_instructions") or [])
            if isinstance(m, dict)
        }
        confidences = payload.get("confidence_scores") or {}

        for fact in facts:
            if not isinstance(fact, dict):
                continue
            field_name = str(fact.get("field", "")).strip()
            if not field_name:
                continue

            try:
                confidence = float(
                    fact.get("confidence", confidences.get(field_name, 0.5))
                )
            except (TypeError, ValueError):
                confidence = 0.5

            target = mapping.get(field_name, {})
            source_page = _safe_int(fact.get("page"))
            # `primary_document` remains the fallback for a fact no
            # provenance entry claims, so a row is still written.
            document = (
                _pick_document(
                    by_type.get(source_types.get(field_name, ""), []), source_page
                )
                or primary_document
            )
            ocr_confidence = document.ocr_mean_confidence if document else None
            requires_review, reason = self._validator.assess_field_confidence(
                field_name=field_name,
                confidence=confidence,
                ocr_confidence=ocr_confidence,
                is_handwritten=bool(document and document.is_handwritten),
            )

            extraction = ExtractionResult(
                document_id=document.id if document else None,
                workflow_id=workflow.id,
                field_name=field_name,
                field_label=str(fact.get("label", ""))[:255] or None,
                masked_value=str(fact.get("value", "")),
                normalized_value=str(fact.get("value", ""))[:255],
                confidence=confidence,
                extraction_method="llm",
                source_page=source_page,
                source_bbox=_figure_box(document, source_page, fact.get("value")),
                target_form=str(target.get("target_form", "")) or None,
                target_line=str(target.get("target_line", "")) or None,
                requires_review=requires_review,
            )
            if document is not None:
                self._session.add(extraction)
                self._session.flush()

            if requires_review and reason is not None:
                self._add_review_item(
                    workflow,
                    document_id=document.id if document else None,
                    extraction_id=extraction.id if document else None,
                    reason=reason,
                    title=f"Verify {field_name}",
                    description=_why_this_field_needs_checking(
                        reason,
                        confidence=confidence,
                        ocr_confidence=ocr_confidence,
                        field_floor=self._settings.confidence_auto_approve,
                        ocr_floor=self._settings.ocr_min_confidence / 100.0,
                    ),
                    field_name=field_name,
                    proposed_value=str(fact.get("value", "")),
                    confidence=confidence,
                    source_page=source_page,
                )
                result.review_items += 1

        result.facts_extracted = len(facts)

        # Recompute the return from normalized fields.
        normalized = payload.get("normalized_fields") or {}
        computed_return = None
        reported = _reported_money_fields(normalized)

        if normalized and not reported:
            # Every monetary field defaulted. Computing anyway yields a fully
            # well-formed return of zeros — total income 0, tax 0, refund 0 —
            # which is indistinguishable from a real result for a taxpayer with
            # no income, and which the package then presents as the answer. That
            # is the workpaper equivalent of answering a tax question with no
            # sources, and it gets the same treatment: refuse.
            self._add_review_item(
                workflow,
                reason=ReviewReason.MISSING_REQUIRED_DATA,
                title="No monetary values were extracted; return not computed",
                description=(
                    "The extraction reported no amount for any field the tax "
                    "engine can consume, so no return was computed. This "
                    "usually means the source pages were not readable rather "
                    "than that the taxpayer had no income — check the OCR "
                    "exceptions on this workflow first."
                ),
                priority=1,
            )
            result.review_items += 1
            logger.warning(
                "Workflow %s: refusing to compute a return from zero extracted "
                "monetary fields.",
                workflow.id,
            )

        if reported:
            year = tax_year or _infer_year(normalized)
            if year is None:
                # No year on the request or in the documents. The configured
                # default is assumed - clamped to the years the engine holds
                # constants for - and never silently: a return computed for
                # the wrong year looks exactly like a right one (trap 13).
                assumed = _assumed_return_year()
                year = assumed.year
                clamp_note = (
                    f" The configured default is {assumed.configured}, but the "
                    f"engine has no {assumed.configured} rules yet, so the latest "
                    f"year it supports was used."
                    if assumed.clamped else ""
                )
                self._add_review_item(
                    workflow,
                    reason=ReviewReason.MISSING_REQUIRED_DATA,
                    title=f"Tax year assumed: {year}",
                    description=(
                        "No tax year was stated on the documents or chosen "
                        f"when the file was processed, so the return was "
                        f"computed for {year}.{clamp_note} Confirm the year "
                        "before relying on any figure."
                    ),
                    priority=2,
                )
                result.review_items += 1

            # --- Who is this taxpayer? -------------------------------
            # Resolved from every candidate the documents offered, weighted by
            # which documents are actually about this person. Reading a single
            # filing_status field left it undetermined on 7 of 7 real
            # workpapers while spouse names, SSNs and dates of birth sat
            # unused in the extraction.
            profile_result = TaxpayerProfileService().determine(
                normalized=normalized,
                candidates=payload.get("scalar_candidates") or {},
                tax_year=year,
                prior_year_status=str(
                    normalized.get("prior_year_filing_status") or ""
                ).strip() or None,
            )
            for item in profile_result.review_items:
                self._add_review_item(
                    workflow,
                    reason=ReviewReason.MISSING_REQUIRED_DATA,
                    title=item["title"],
                    description=item["description"],
                    field_name=item["field"],
                    priority=1,
                )
                result.review_items += 1

            # --- Filing status: resolve or refuse -------------------------
            # This used to read `... or FilingStatusTax.SINGLE`. The profile
            # service goes to real trouble to return None rather than guess —
            # its own docstring records that guessing cost one sample return
            # about 15,000 of standard deduction — and the caller supplied the
            # guess anyway, twenty lines below a gate that refuses outright to
            # compute from an empty extraction.
            #
            # An all-zero return is at least visibly empty. A return on the
            # wrong filing status is internally consistent, foots perfectly, and
            # is wrong in the standard deduction, every bracket and every
            # phase-out at once. It is indistinguishable from a correct return,
            # which is precisely why it must not be produced.
            status = profile_result.filing_status.value
            if status is None:
                self._add_review_item(
                    workflow,
                    reason=ReviewReason.MISSING_REQUIRED_DATA,
                    title="Filing status could not be determined; return not computed",
                    description=(
                        f"{profile_result.filing_status.evidence}. Filing status "
                        "sets the standard deduction, the bracket table and "
                        "nearly every phase-out, so no return was computed "
                        "rather than one on an assumed status. Confirm the "
                        "status on this workflow and reprocess."
                    ),
                    field_name="filing_status",
                    priority=1,
                )
                result.review_items += 1
                logger.warning(
                    "Workflow %s: refusing to compute a return without a "
                    "determined filing status.",
                    workflow.id,
                )
                merged = TaxValidationService.merge(reports)
                result.overall_confidence = merged.confidence
                return StageOutput(value=None, detail=merged.summary())

            logger.info(
                "Filing status: %s (%s)",
                status.value,
                profile_result.filing_status.evidence,
            )

            # Carryovers the prior year deposited. Applied only where this
            # year's documents said nothing: a figure the workpaper actually
            # states always wins over a remembered balance, because the
            # documents are the evidence and the repository is only a memory.
            carryover_key = taxpayer_key(
                identifier=str(normalized.get("ssn") or "").strip() or None,
                name=str(normalized.get("taxpayer_name") or "").strip() or None,
                dob=str(normalized.get("date_of_birth") or "").strip() or None,
            )
            carryover_audit: CarryoverAudit | None = None
            if carryover_key:
                repository = CarryoverRepository(
                    self._settings.output_zone_dir / "CarryoverRepository.json"
                )
                remembered = repository.engine_inputs(carryover_key, year)
                applied = {
                    name: value
                    for name, value in remembered.items()
                    if normalized.get(name) in (None, "")
                }
                normalized.update(applied)
                if applied:
                    carryover_audit = repository.audit(carryover_key, year)
                    logger.info(
                        "Applied %d carryover(s) from the prior year", len(applied)
                    )

            # --- Did we get last year's return? --------------------------
            # Some figures appear on no current-year document. If the prior
            # return is in the upload, harvest them; if it is not, ask for it
            # by name and say which numbers depend on it, rather than treating
            # unknown as zero and printing a return that foots.
            known_kinds: set[str] = set()
            if carryover_key:
                known_kinds = {
                    balance.kind
                    for balance in CarryoverRepository(
                        self._settings.output_zone_dir / "CarryoverRepository.json"
                    ).carryovers_into(carryover_key, year)
                }
            prior_year = PriorYearService().evaluate(
                normalized=normalized,
                document_types={d.document_type for d in documents},
                tax_year=year,
                already_known=known_kinds,
                workflow_id=workflow.id,
            )

            if prior_year.balances and carryover_key:
                CarryoverRepository(
                    self._settings.output_zone_dir / "CarryoverRepository.json"
                ).record(carryover_key, prior_year.balances)
                for name, value in {
                    field_name: str(balance.amount)
                    for field_name, kind in PRIOR_YEAR_FIELDS.items()
                    for balance in prior_year.balances
                    if balance.kind == kind
                }.items():
                    normalized.setdefault(name, value)
                logger.info(
                    "Recovered %d carryover(s) from the prior-year return",
                    len(prior_year.balances),
                )

            if prior_year.should_request_upload:
                request = upload_request(prior_year, year)
                self._add_review_item(
                    workflow,
                    reason=ReviewReason.MISSING_REQUIRED_DATA,
                    title=request["title"],
                    description=request["description"],
                    field_name=request["field"],
                    priority=1,
                )
                result.review_items += 1
                result.prior_year_requested = True

            # Form 7203 before the return, because its gain is an input to it.
            basis_result = self._apply_form_7203(workflow, normalized, carryover_key)
            if basis_result is not None:
                result.review_items += 1

            try:
                # Kept on the instance so the output stage can render the
                # schedules behind each Form 1040 total. Line 8 is one number;
                # the Schedule 1 that produced it has five, and Return1040
                # keeps only the total.
                self._engine_inputs = {
                    "profile": TaxpayerProfile(
                        tax_year=year,
                        filing_status=status,
                        # Age drives the line 12e addition and the Schedule 1-A
                        # senior deduction. The date of birth was already being
                        # extracted and thrown away, costing the sample return
                        # 8,000 of deductions between the two.
                        age_65_or_older=profile_result.seniors,
                        qualifying_children=profile_result.qualifying_children,
                        other_dependents=profile_result.other_dependents,
                        state_code=(str(normalized.get("state") or "").strip() or None),
                    ),
                    "income": _build_engine_inputs(IncomeInputs, normalized),
                    "capital_gains": _build_engine_inputs(CapitalGainInputs, normalized),
                    "adjustments": _build_engine_inputs(AdjustmentInputs, normalized),
                    "deductions": _build_engine_inputs(DeductionInputs, normalized),
                    "additional_deductions": _build_engine_inputs(
                        AdditionalDeductionInputs, normalized
                    ),
                    "payments": _build_engine_inputs(PaymentInputs, normalized),
                }
                computed_return = Form1040Calculator().compute(**self._engine_inputs)
                reports.append(
                    self._validator.validate_return(computed_return, normalized)
                )
                # Deposit what this return carries forward, so next year's run
                # can withdraw it. Best-effort: a bookkeeping failure must not
                # fail a return that computed correctly.
                if carryover_key:
                    try:
                        CarryoverRepository(
                            self._settings.output_zone_dir / "CarryoverRepository.json"
                        ).record_from_return(
                            carryover_key,
                            computed_return,
                            workflow_id=workflow.id,
                        )
                    except Exception as exc:  # pragma: no cover - non-critical
                        logger.warning(
                            "Could not record carryovers: %s", type(exc).__name__
                        )

                # Only warn about missing prior-year data the repository could
                # not supply either. Warning about a balance we already hold
                # trains the reviewer to dismiss the item.
                if carryover_audit is None:
                    result.review_items += self._flag_unavailable_prior_year(
                        workflow, normalized, documents
                    )

                for silent in detect_silent_documents(
                    (d.document_type for d in documents),
                    payload.get("field_provenance") or {},
                ):
                    self._add_review_item(
                        workflow,
                        reason=ReviewReason.MISSING_REQUIRED_DATA,
                        **silent_document_review_item(silent),
                        priority=1,
                    )

                for risk in detect_restated_subtotals(
                    payload.get("field_provenance") or {}
                ):
                    self._add_review_item(
                        workflow,
                        reason=ReviewReason.SOURCE_CONFLICT,
                        **restated_subtotal_review_item(risk),
                        priority=1,
                    )
                # Keep the inputs, not the rendered explanation — see
                # ExplanationStore. Best-effort: a return that computed cleanly
                # must not fail because its explanation could not be filed.
                try:
                    ExplanationStore(
                        self._settings.output_zone_dir / "explanations"
                    ).save(
                        workflow.id,
                        normalized=normalized,
                        field_provenance=payload.get("field_provenance") or {},
                        confidence_scores=payload.get("confidence_scores") or {},
                        profile={
                            "tax_year": year,
                            "filing_status": status.value,
                            "age_65_or_older": _seniors_in_household(
                                normalized, year, filing_status=status
                            ),
                            # Ages, not dates of birth: the store drops
                            # identity fields, and the graph engine needs an
                            # age rather than a count of seniors.
                            "taxpayer_age": age_on(
                                normalized.get("date_of_birth"), tax_year=year
                            ),
                            "spouse_age": age_on(
                                normalized.get("spouse_date_of_birth"), tax_year=year
                            ),
                            "qualifying_children": (
                                _safe_int(normalized.get("qualifying_children")) or 0
                            ),
                            "other_dependents": (
                                _safe_int(normalized.get("other_dependents")) or 0
                            ),
                            "state_code": (
                                str(normalized.get("state") or "").strip() or None
                            ),
                        },
                    )
                except Exception as exc:  # pragma: no cover - non-critical path
                    logger.warning(
                        "Could not persist explanation inputs: %s", type(exc).__name__
                    )
            except Exception as exc:
                logger.warning(
                    "Return recomputation skipped: %s: %s",
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )
                # Say so on the workflow. This branch used to log and move on,
                # so an engine failure produced a package with no return in it
                # and no review item explaining the hole — indistinguishable on
                # screen from a workpaper nothing could be read from. The
                # exception type is safe to show; its message is not, because
                # it can quote an extracted value.
                self._add_review_item(
                    workflow,
                    reason=ReviewReason.CALCULATION_MISMATCH,
                    title="The return could not be computed from these figures",
                    description=(
                        f"The tax engine stopped with {type(exc).__name__} part "
                        "way through, so no return was produced. The extracted "
                        "figures are listed on this workflow and were not "
                        "discarded. This is a defect rather than a missing "
                        "document: send the workflow id to support."
                    ),
                    priority=1,
                )
                result.review_items += 1
                reports.append(self._validator.validate_extraction_schema(payload))

        merged = TaxValidationService.merge(reports)
        result.overall_confidence = merged.confidence

        for issue in merged.issues:
            if issue.severity.value in {"error", "warning"}:
                self._add_review_item(
                    workflow,
                    reason=issue.review_reason,
                    title=issue.code.replace(".", ": ").replace("_", " ").title(),
                    description=issue.message,
                    field_name=issue.field_name,
                    proposed_value=issue.actual,
                    priority=1 if issue.severity.value == "error" else 3,
                )
                result.review_items += 1

        self._audit.record(
            AuditAction.VALIDATION_RUN,
            entity_type="workflow",
            entity_id=workflow.id,
            payload=merged.summary(),
        )
        # summary() is check counts and confidence — no field values.
        return StageOutput(value=computed_return, detail=merged.summary())

    def _apply_form_7203(
        self,
        workflow: Workflow,
        normalized: dict[str, Any],
        carryover_key: str | None,
    ) -> Any:
        """Compute the shareholder-loan repayment gain and put it on the return.

        This figure reaches a return through no other route. The K-1 states the
        loan balances and nothing else; the gain has to be computed, and even
        CCH ProSystem *fx* declines to carry it — it raises a diagnostic and
        leaves the number for a human to key onto Form 4797.

        Two things are deliberately not decided here. The **character** of the
        gain depends on whether the debt is a written note or an informal
        running balance, which no document reliably states, so the ordinary
        default is applied and flagged. And a missing opening **debt basis**
        makes the entire repayment taxable, which is the worst-case reading —
        also flagged, never silently taken as correct.

        Returns the computed form, or None when the K-1 reported no loan.
        """
        begin = _amount(normalized.get("loan_balance_begin"))
        end = _amount(normalized.get("loan_balance_end"))
        if begin is None or end is None or begin <= end:
            return None

        debt_basis = _amount(normalized.get("debt_basis_begin"))
        if debt_basis is None and carryover_key:
            remembered = CarryoverRepository(
                self._settings.output_zone_dir / "CarryoverRepository.json"
            ).carryovers_into(carryover_key, int(normalized.get("tax_year") or 0))
            for balance in remembered:
                if balance.kind == CarryoverKind.DEBT_BASIS:
                    debt_basis = balance.amount

        basis = compute_form_7203(
            ShareholderBasisInputs(
                stock_basis_begin=_amount(normalized.get("stock_basis_begin")) or Decimal(0),
                debt_basis_begin=debt_basis or Decimal(0),
                ordinary_business_income=_amount(normalized.get("rental_income")) or Decimal(0),
                distributions=_amount(normalized.get("distributions")) or Decimal(0),
                nondeductible_expenses=_amount(normalized.get("nondeductible_expenses")) or Decimal(0),
                loan_balance_begin=begin,
                loan_balance_end=end,
            )
        )
        if basis.reportable_gain <= Decimal(0):
            return basis

        if basis.is_ordinary:
            existing = _amount(normalized.get("other_gains")) or Decimal(0)
            normalized["other_gains"] = str(existing + basis.reportable_gain)
        else:
            existing = _amount(normalized.get("long_term_gain")) or Decimal(0)
            normalized["long_term_gain"] = str(existing + basis.reportable_gain)

        self._add_review_item(
            workflow,
            reason=ReviewReason.MISSING_REQUIRED_DATA,
            title="Shareholder loan repayment produced taxable income",
            description=(
                f"The K-1 shows shareholder loans falling from {begin} to {end}, "
                f"a repayment of {basis.principal_repaid}. Against a debt basis "
                f"of {basis.debt_basis_before_repayment}, "
                f"{basis.nontaxable_repayment} is a return of basis and "
                f"{basis.reportable_gain} is income, reported on "
                f"{basis.destination}.\n\n"
                "Confirm two things before filing:\n"
                "• Whether the loan is evidenced by a written note. If it is, "
                "the gain is capital, not ordinary, and belongs on Schedule D.\n"
                "• The opening debt basis, from the prior year's Form 7203 "
                "line 31. It is the figure this gain is most sensitive to.\n\n"
                + "\n".join(basis.warnings)
            ),
            field_name="loan_balance_end",
            priority=1,
        )
        logger.info(
            "Form 7203: repayment %s produced %s of %s income",
            basis.principal_repaid,
            basis.reportable_gain,
            "ordinary" if basis.is_ordinary else "capital",
        )
        return basis

    def _flag_unavailable_prior_year(
        self,
        workflow: Workflow,
        normalized: dict[str, Any],
        documents: list[Document],
    ) -> int:
        """Say when the return needed last year's figures and did not have them.

        Some Form 1040 inputs are stated on no current-year document. Schedule D
        lines 6 and 14 read "carryover from your Capital Loss Carryover
        Worksheet"; line 26 reads "amount applied from your prior return". When
        the prior return is not in the workpaper, those are not zero — they are
        *unknown*, and the two are not the same thing.

        Treating unknown as zero is what makes this dangerous rather than merely
        incomplete. The return still foots, still prints, and still looks
        finished. On the sample workpaper it understated the capital loss
        carryover by 4,511 and dropped 725 of payments, and every review item
        raised was about a street address. A preparer had no signal to go and
        fetch last year's return.

        Returns the number of review items raised.
        """
        if any(
            document.document_type == DocumentType.PRIOR_YEAR_RETURN.value
            for document in documents
        ):
            return 0

        missing: list[str] = []

        schedule_d_active = any(
            _amount(normalized.get(name))
            for name in (
                "short_term_gain",
                "long_term_gain",
                "capital_gain_distributions",
                "short_term_from_k1",
                "long_term_from_k1",
            )
        )
        carryover_stated = any(
            normalized.get(name) not in (None, "")
            for name in ("short_term_loss_carryover", "long_term_loss_carryover")
        )
        if schedule_d_active and not carryover_stated:
            missing.append(
                "a capital loss carryover (Schedule D lines 6 and 14) — this "
                "return reports investment activity, and any unused loss from "
                "last year reduces the gain reported here"
            )

        if normalized.get("prior_year_overpayment_applied") in (None, ""):
            missing.append(
                "an overpayment applied from the prior return (line 26) — a "
                "refund left with the IRS last year counts as a payment against "
                "this year's tax"
            )

        if not missing:
            return 0

        self._add_review_item(
            workflow,
            reason=ReviewReason.MISSING_REQUIRED_DATA,
            title="Prior-year return not provided",
            description=(
                "No prior-year return was found in this workpaper, so the "
                "following could not be determined and were treated as zero:\n\n"
                + "\n".join(f"• {item}" for item in missing)
                + "\n\nThese are not stated on any current-year document. Supply "
                "the prior-year return, or enter the figures directly, before "
                "relying on this return."
            ),
            field_name="short_term_loss_carryover",
            priority=1,
        )
        return 1

    def _stage_review(self, workflow: Workflow, result: PipelineResult) -> StageOutput:
        return StageOutput(
            value=None, detail={"review_items": result.review_items}
        )

    def _stage_output(
        self,
        workflow: Workflow,
        computed_return: Any,
        rehydrator: RehydrationService,
        result: PipelineResult,
    ) -> StageOutput:
        generator = OutputGenerationService(
            self._session, settings=self._settings, audit=self._audit
        )
        packages = generator.generate_package(
            workflow,
            computed_return=computed_return,
            rehydrator=rehydrator,
            engine_inputs=self._engine_inputs,
        )
        result.packages_generated = len(packages)
        return StageOutput(value=packages, detail={"artifacts": len(packages)})

    # --------------------------------------------------------------- helpers

    def _add_review_item(
        self,
        workflow: Workflow,
        *,
        reason: ReviewReason,
        title: str,
        description: str,
        document_id: str | None = None,
        extraction_id: str | None = None,
        field_name: str | None = None,
        proposed_value: str | None = None,
        confidence: float | None = None,
        source_page: int | None = None,
        priority: int = 3,
    ) -> ReviewItem:
        item = ReviewItem(
            workflow_id=workflow.id,
            document_id=document_id,
            extraction_id=extraction_id,
            reason=reason.value,
            status=ReviewStatus.PENDING.value,
            priority=priority,
            title=title[:255],
            description=description,
            field_name=field_name,
            proposed_value=proposed_value,
            confidence=confidence,
            source_page=source_page,
        )
        self._session.add(item)
        self._audit.record(
            AuditAction.REVIEW_ITEM_CREATED,
            entity_type="workflow",
            entity_id=workflow.id,
            payload={"reason": reason.value, "priority": priority},
        )
        return item

    def _cleanup_working_copy(self) -> None:
        """Delete the decrypted temp file.

        SECURITY: this is the only plaintext copy of the original on disk. It
        must go whether the run succeeded or failed, hence the ``finally``.
        """
        if self._working_copy is None:
            return
        try:
            self._working_copy.unlink(missing_ok=True)
            logger.debug("Removed working copy")
        except OSError as exc:  # pragma: no cover
            logger.error(
                "Could not remove the decrypted working copy (%s). Remove it "
                "manually from the tmp zone.",
                type(exc).__name__,
            )
        finally:
            self._working_copy = None


def _summarize_detail(detail: dict[str, Any]) -> dict[str, Any]:
    """Keep only scalar counters. SECURITY: prevents content in stage detail."""
    return {
        key: value
        for key, value in detail.items()
        if isinstance(value, (int, float, bool, str)) and len(str(value)) <= 200
    }


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _amount(value: Any) -> Decimal | None:
    """Parse an extracted money value, or ``None`` if it is not a number.

    Returns ``None`` rather than zero for anything unparseable, so that "the
    model did not report this" stays distinguishable from "the document says
    zero". The engine treats those identically, but the sufficiency check does
    not: a return whose every field defaulted to zero is an empty extraction,
    not a taxpayer with no income.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    text = str(value).strip()
    if not text:
        return None
    # Accounting negatives: (1,234.56) means -1234.56.
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if not cleaned or cleaned in {"-", ".", "-."}:
        return None
    try:
        parsed = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -abs(parsed) if negative else parsed


def _build_engine_inputs(source: type, normalized: dict[str, Any]) -> Any:
    """Populate one of the engine's input dataclasses from normalized fields.

    Generic over the dataclass so that every monetary field the engine declares
    is wired automatically. The previous hand-written mapping covered seven of
    them and silently dropped the rest, including all withholding.
    """
    kwargs: dict[str, Any] = {}
    for entry in dataclass_fields(source):
        if "Decimal" not in str(entry.type):
            continue
        parsed = _amount(normalized.get(entry.name))
        if parsed is not None:
            kwargs[entry.name] = parsed
    return source(**kwargs)


def _reported_money_fields(normalized: dict[str, Any]) -> list[str]:
    """Engine-consumable fields the extraction actually supplied a number for."""
    return [
        name
        for name in ENGINE_MONEY_FIELDS
        if _amount(normalized.get(name)) is not None
    ]


def _assumed_return_year() -> ResolvedYear:
    """The configured default year, clamped to the years the engine supports."""
    return resolve_tax_year(tax_tables.SUPPORTED_YEARS)


def _infer_year(fields: dict[str, Any]) -> int | None:
    for key in ("tax_year", "year", "taxable_year"):
        value = _safe_int(fields.get(key))
        if value and 1990 <= value <= 2100:
            return value
    return None


#: Keys are lower-cased with every non-alphanumeric character removed, so that
#: "Married Filing Jointly", "married_filing_jointly" and "MarriedFilingJointly"
#: all land on the same entry — and so that a form printing "Qualifying
#: Widow(er)" is not defeated by its parentheses.
_FILING_STATUS_ALIASES: dict[str, FilingStatusTax] = {
    "single": FilingStatusTax.SINGLE,
    "s": FilingStatusTax.SINGLE,
    "unmarried": FilingStatusTax.SINGLE,
    "joint": FilingStatusTax.MARRIED_JOINT,
    "marriedjoint": FilingStatusTax.MARRIED_JOINT,
    "marriedfilingjoint": FilingStatusTax.MARRIED_JOINT,
    "marriedfilingjointly": FilingStatusTax.MARRIED_JOINT,
    "mfj": FilingStatusTax.MARRIED_JOINT,
    "separate": FilingStatusTax.MARRIED_SEPARATE,
    "marriedseparate": FilingStatusTax.MARRIED_SEPARATE,
    "marriedfilingseparate": FilingStatusTax.MARRIED_SEPARATE,
    "marriedfilingseparately": FilingStatusTax.MARRIED_SEPARATE,
    "mfs": FilingStatusTax.MARRIED_SEPARATE,
    "headofhousehold": FilingStatusTax.HEAD_OF_HOUSEHOLD,
    "headhousehold": FilingStatusTax.HEAD_OF_HOUSEHOLD,
    "hoh": FilingStatusTax.HEAD_OF_HOUSEHOLD,
    "qualifyingsurvivingspouse": FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE,
    "survivingspouse": FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE,
    "qualifyingwidow": FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE,
    "qualifyingwidower": FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE,
    "qss": FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE,
}


def _infer_status(fields: dict[str, Any]) -> FilingStatusTax | None:
    """Map an extracted filing status onto the engine's enum.

    Returns ``None`` for anything absent or unrecognised rather than guessing.
    Filing status drives the standard deduction, the bracket table and most
    credit phase-outs, so quietly falling back to Single produces a materially
    wrong return that looks entirely ordinary. The sample workpaper states
    "Joint", which was not in the alias table and silently became Single —
    a roughly $15,000 error in the deduction alone.

    Bare "married" is deliberately unmapped: it does not distinguish joint from
    separate, and choosing for the taxpayer is exactly the guess to avoid.
    """
    raw = str(fields.get("filing_status", "")).strip().lower()
    if not raw:
        return None
    return _FILING_STATUS_ALIASES.get(re.sub(r"[^a-z0-9]+", "", raw))
