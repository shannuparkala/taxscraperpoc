"""Domain enumerations shared by ORM models, Pydantic schemas, and services."""

from __future__ import annotations

from enum import Enum


class FilingStatus(str, Enum):
    """Lifecycle of a tax return. Drives the dashboard status breakdown."""

    DRAFT = "draft"
    IN_REVIEW = "in_review"
    AWAITING_CLIENT_INFO = "awaiting_client_info"
    READY_TO_FILE = "ready_to_file"
    FILED = "filed"
    REJECTED = "rejected"
    AMENDED = "amended"


class FilingType(str, Enum):
    """Return type. Maps to the primary federal form."""

    INDIVIDUAL = "individual"          # 1040
    PARTNERSHIP = "partnership"        # 1065
    S_CORP = "s_corp"                  # 1120-S
    C_CORP = "c_corp"                  # 1120
    TRUST_ESTATE = "trust_estate"      # 1041
    PAYROLL = "payroll"                # 941 / 940
    SALES_TAX = "sales_tax"
    STATE_LOCAL = "state_local"
    OTHER = "other"


PRIMARY_FORM_BY_FILING_TYPE: dict[FilingType, str] = {
    FilingType.INDIVIDUAL: "1040",
    FilingType.PARTNERSHIP: "1065",
    FilingType.S_CORP: "1120-S",
    FilingType.C_CORP: "1120",
    FilingType.TRUST_ESTATE: "1041",
    FilingType.PAYROLL: "941",
    FilingType.SALES_TAX: "",
    FilingType.STATE_LOCAL: "",
    FilingType.OTHER: "",
}


class DocumentType(str, Enum):
    """Classification of a single document inside an upload."""

    W2 = "w2"
    W2G = "w2g"
    FORM_1099_INT = "1099_int"
    FORM_1099_DIV = "1099_div"
    FORM_1099_B = "1099_b"
    FORM_1099_R = "1099_r"
    FORM_1099_MISC = "1099_misc"
    FORM_1099_NEC = "1099_nec"
    FORM_1099_G = "1099_g"
    FORM_1099_S = "1099_s"
    FORM_1099_SA = "1099_sa"
    FORM_1098 = "1098"                 # mortgage interest
    FORM_1098_T = "1098_t"             # tuition
    FORM_1098_E = "1098_e"             # student loan interest
    FORM_1095 = "1095"                 # health coverage
    FORM_5498 = "5498"                 # IRA contributions
    SCHEDULE_K1 = "k1"
    BROKERAGE_STATEMENT = "brokerage_statement"
    TRIAL_BALANCE = "trial_balance"
    GENERAL_LEDGER = "general_ledger"
    DEPRECIATION_SCHEDULE = "depreciation_schedule"
    BALANCE_SHEET = "balance_sheet"
    PROFIT_AND_LOSS = "profit_and_loss"
    PRIOR_YEAR_RETURN = "prior_year_return"
    CLIENT_ORGANIZER = "client_organizer"
    ENGAGEMENT_LETTER = "engagement_letter"
    CONSENT_FORM = "consent_form"
    CORRESPONDENCE = "correspondence"
    IRS_NOTICE = "irs_notice"
    HANDWRITTEN_NOTES = "handwritten_notes"
    RECEIPT = "receipt"
    UNKNOWN_WORKPAPER = "unknown_workpaper"


#: Document types that carry taxpayer-level identity data and therefore always
#: get the strictest masking treatment.
IDENTITY_BEARING_DOCUMENTS: frozenset[DocumentType] = frozenset(
    {
        DocumentType.W2,
        DocumentType.SCHEDULE_K1,
        DocumentType.CLIENT_ORGANIZER,
        DocumentType.PRIOR_YEAR_RETURN,
        DocumentType.CONSENT_FORM,
        DocumentType.ENGAGEMENT_LETTER,
    }
)


class FileStatus(str, Enum):
    UPLOADED = "uploaded"
    QUARANTINED = "quarantined"        # failed validation / suspicious
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    PURGED = "purged"                  # retention policy removed the bytes


class WorkflowStage(str, Enum):
    """The nine pipeline stages, in execution order.

    The UI timeline renders these directly, so order matters.
    """

    UPLOAD = "upload"
    CLASSIFICATION = "classification"
    OCR = "ocr"
    MASKING = "masking"
    LLM_PROCESSING = "llm_processing"
    VALIDATION = "validation"
    REVIEW = "review"
    REHYDRATION = "rehydration"
    OUTPUT = "output"


#: What each stage is called when a person is watching it happen.
#:
#: The enum values are internal names ("llm_processing", "rehydration") and mean
#: nothing to someone waiting on a progress bar. These are phrased as the work
#: being done, in the order it happens, so the wait is legible rather than
#: mysterious.
STAGE_LABELS: dict[WorkflowStage, str] = {
    WorkflowStage.UPLOAD: "Opening your file",
    WorkflowStage.CLASSIFICATION: "Working out what each document is",
    WorkflowStage.OCR: "Reading the pages",
    WorkflowStage.MASKING: "Hiding personal details before anything is sent",
    WorkflowStage.LLM_PROCESSING: "Pulling the figures off each document",
    WorkflowStage.VALIDATION: "Checking the maths and calculating the return",
    WorkflowStage.REVIEW: "Deciding what needs a human to look at it",
    WorkflowStage.REHYDRATION: "Putting your real details back",
    WorkflowStage.OUTPUT: "Writing your results",
}


#: Execution order, which is what every position-derived number is built from:
#: ``stage_index``, ``progress_percent``, the UI timeline, and the streaming
#: progress bar.
#:
#: OCR genuinely runs *before* classification — the corpus is scanned, so there
#: is no text to classify until OCR has produced some. This tuple used to list
#: them the other way round, so the two stages reported positions 2 and 3 in the
#: wrong order and progress visibly jumped backwards from 33% to 11% mid-run.
WORKFLOW_STAGE_ORDER: tuple[WorkflowStage, ...] = (
    WorkflowStage.UPLOAD,
    WorkflowStage.OCR,
    WorkflowStage.CLASSIFICATION,
    WorkflowStage.MASKING,
    WorkflowStage.LLM_PROCESSING,
    WorkflowStage.VALIDATION,
    WorkflowStage.REVIEW,
    WorkflowStage.REHYDRATION,
    WorkflowStage.OUTPUT,
)


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    BLOCKED = "blocked"                # e.g. OCR unavailable


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
    ESCALATED = "escalated"


class ReviewReason(str, Enum):
    """Why an item was routed to a human. Shown as a badge in the queue."""

    LOW_CONFIDENCE = "low_confidence"
    HANDWRITING_UNCERTAIN = "handwriting_uncertain"
    OCR_UNAVAILABLE = "ocr_unavailable"
    TAX_AMBIGUITY = "tax_ambiguity"
    SOURCE_CONFLICT = "source_conflict"
    MISSING_REQUIRED_DATA = "missing_required_data"
    CALCULATION_MISMATCH = "calculation_mismatch"
    UNMASKED_PII_SUSPECTED = "unmasked_pii_suspected"
    TEMPLATE_APPROVAL = "template_approval"
    SCHEMA_VIOLATION = "schema_violation"
    MATERIAL_AMOUNT = "material_amount"


class Jurisdiction(str, Enum):
    FEDERAL = "federal"
    STATE = "state"
    LOCAL = "local"
    MULTI_STATE = "multi_state"


class AuthorityLevel(str, Enum):
    """How authoritative a stored source is.

    Recorded on ``RagDocument`` rows (chat attachments are ``FIRM_INTERNAL``)
    and used by the workpaper's rule citations.
    """

    STATUTORY = "statutory"            # Internal Revenue Code (26 U.S.C.)
    REGULATORY = "regulatory"          # Treasury Regulations (26 C.F.R.)
    OFFICIAL_GUIDANCE = "official_guidance"   # IRS pubs, instructions, rulings
    JUDICIAL = "judicial"              # Tax Court and other opinions
    STATE_OFFICIAL = "state_official"  # state DOR guidance
    SECONDARY = "secondary"            # AICPA, The Tax Adviser, commentary
    FIRM_INTERNAL = "firm_internal"    # firm memos


#: Numeric weight applied to retrieval scores. Higher wins ties.
AUTHORITY_WEIGHT: dict[AuthorityLevel, float] = {
    AuthorityLevel.STATUTORY: 1.00,
    AuthorityLevel.REGULATORY: 0.95,
    AuthorityLevel.OFFICIAL_GUIDANCE: 0.90,
    AuthorityLevel.JUDICIAL: 0.80,
    AuthorityLevel.STATE_OFFICIAL: 0.85,
    AuthorityLevel.SECONDARY: 0.55,
    AuthorityLevel.FIRM_INTERNAL: 0.50,
}

#: Authority levels considered primary. Used to enforce the "secondary sources
#: never override primary authority" rule.
PRIMARY_AUTHORITIES: frozenset[AuthorityLevel] = frozenset(
    {
        AuthorityLevel.STATUTORY,
        AuthorityLevel.REGULATORY,
        AuthorityLevel.OFFICIAL_GUIDANCE,
        AuthorityLevel.JUDICIAL,
        AuthorityLevel.STATE_OFFICIAL,
    }
)


class SourceType(str, Enum):
    WEB_PAGE = "web_page"
    PDF = "pdf"
    HTML = "html"
    IRS_PUBLICATION = "irs_publication"
    FORM_INSTRUCTION = "form_instruction"
    REGULATION = "regulation"
    STATUTE = "statute"
    COURT_OPINION = "court_opinion"
    FAQ = "faq"
    NEWS = "news"
    STATE_GUIDANCE = "state_guidance"
    FIRM_MEMO = "firm_memo"
    INTERNAL_REVENUE_MANUAL = "internal_revenue_manual"


class RagDocumentStatus(str, Enum):
    PENDING = "pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"
    STALE = "stale"                    # source changed since last index


class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"      # no reliable source found


class ModelTier(str, Enum):
    FLASH_LITE = "flash_lite"
    FLASH = "flash"
    PRO = "pro"


class TaskKind(str, Enum):
    """What the caller wants the model to do. Input to the model router."""

    CHAT_SIMPLE = "chat_simple"
    CHAT_COMPLEX = "chat_complex"
    CLASSIFICATION = "classification"
    BULK_EXTRACTION = "bulk_extraction"
    DOCUMENT_EXTRACTION = "document_extraction"
    HANDWRITING_INTERPRETATION = "handwriting_interpretation"
    TAX_REASONING = "tax_reasoning"
    TAX_MEMO = "tax_memo"
    TEMPLATE_INFERENCE = "template_inference"
    #: Plain-English wording for computed lines. Every number in the reply is
    #: checked against the line's provenance before it is shown.
    RETURN_EXPLANATION = "return_explanation"


class TemplateStatus(str, Enum):
    PROPOSED = "proposed"              # learned, not yet reviewed
    APPROVED = "approved"              # reviewer signed off; usable in prod
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class OutputArtifactType(str, Enum):
    #: The deliverable itself: the computed return rendered onto the official
    #: IRS Form 1040. Everything else in the package supports or explains it.
    TAX_RETURN_FORM = "tax_return_form"
    #: One schedule rendered onto its official IRS form.
    TAX_RETURN_SCHEDULE = "tax_return_schedule"
    #: Form 1040 and every schedule merged in filing order — the document a
    #: preparer actually signs and files, rather than a folder to assemble.
    COMPLETE_RETURN = "complete_return"
    #: The computed return rendered for import into another tax package, one
    #: per configured target. Machine-readable, not something a preparer reads.
    TAX_SOFTWARE_EXPORT = "tax_software_export"
    COMPLETED_WORKPAPER = "completed_workpaper"
    SUMMARY_REPORT = "summary_report"
    REVIEW_NOTES = "review_notes"
    EXCEPTION_LIST = "exception_list"
    TRACEABILITY_MATRIX = "traceability_matrix"
    AUDIT_LOG = "audit_log"
    FULL_PACKAGE = "full_package"
