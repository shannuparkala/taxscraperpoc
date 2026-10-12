"""Pydantic request and response models for the HTTP API.

SECURITY: response models are allow-lists. Building them field by field, rather
than dumping ORM objects, is what guarantees ``encrypted_value`` and other
vault columns can never be serialized to a client by accident.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


# ===========================================================================
# Files
# ===========================================================================


class UploadedFileOut(ApiModel):
    id: str
    filing_id: str | None = None
    original_filename: str
    content_type: str
    extension: str
    size_bytes: int
    content_hash: str
    status: str
    is_encrypted: bool
    file_metadata: dict[str, Any] | None = None
    #: Why a file was rejected or quarantined, so the UI can explain itself
    #: instead of just showing a status badge.
    validation_notes: str | None = None
    created_at: datetime
    # SECURITY: stored_filename is deliberately absent. Exposing the on-disk
    # name would let a client probe the raw zone.


class FileListResponse(ApiModel):
    items: list[UploadedFileOut]
    total: int
    page: int = 1
    page_size: int = 50


# ===========================================================================
# Workflows
# ===========================================================================


class StageRunOut(ApiModel):
    stage: str
    stage_index: int
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    detail: dict[str, Any] | None = None
    error_message: str | None = None


class DocumentOut(ApiModel):
    id: str
    document_type: str
    classification_confidence: float
    classification_method: str
    page_start: int
    page_end: int
    page_count: int
    is_handwritten: bool
    requires_ocr: bool
    ocr_performed: bool
    ocr_engine: str | None = None
    ocr_mean_confidence: float | None = None


class ExtractionOut(ApiModel):
    id: str
    field_name: str
    field_label: str | None = None
    #: TOKENIZED — masked value only, never the original.
    masked_value: str | None = None
    confidence: float
    extraction_method: str
    source_page: int | None = None
    target_form: str | None = None
    target_line: str | None = None
    validation_status: str | None = None
    requires_review: bool


class WorkflowOut(ApiModel):
    id: str
    uploaded_file_id: str
    filing_id: str | None = None
    status: str
    current_stage: str
    progress_percent: float
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_summary: str | None = None
    documents_detected: int
    pii_entities_masked: int
    review_items_open: int
    overall_confidence: float | None = None
    llm_usage: dict[str, Any] | None = None
    created_at: datetime
    #: The uploaded file this run processed. "Which file was this?" is the first
    #: thing a preparer asks of a list of runs, and a truncated workflow id
    #: cannot answer it.
    source_filename: str | None = None


class WorkflowDetailOut(WorkflowOut):
    stages: list[StageRunOut] = Field(default_factory=list)
    documents: list[DocumentOut] = Field(default_factory=list)
    extractions: list[ExtractionOut] = Field(default_factory=list)
    output_packages: list[OutputPackageOut] = Field(default_factory=list)


class ProcessRequest(ApiModel):
    tax_year: int | None = Field(default=None, ge=1990, le=2100)
    filing_id: str | None = None


class MaskedPreviewOut(ApiModel):
    """What the LLM actually saw, for the UI's transparency panel."""

    document_id: str
    document_type: str
    page_start: int
    page_end: int
    masked_text: str
    token_count: int
    #: token -> surrogate. SECURITY: never includes original values.
    token_map: dict[str, str] = Field(default_factory=dict)


class OutputPackageOut(ApiModel):
    id: str
    artifact_type: str
    filename: str
    content_type: str
    size_bytes: int
    is_rehydrated: bool
    tokens_rehydrated: int
    download_count: int
    created_at: datetime
    # SECURITY: stored_path is never exposed.


# ===========================================================================
# Dashboard
# ===========================================================================


class StatusCount(ApiModel):
    key: str
    label: str
    count: int


class ConfidenceBucket(ApiModel):
    label: str
    lower: float
    upper: float
    count: int


class RecentUploadOut(ApiModel):
    id: str
    original_filename: str
    extension: str
    size_bytes: int
    status: str
    created_at: datetime


class RecentChatOut(ApiModel):
    id: str
    session_id: str
    #: TOKENIZED — the stored question is already masked.
    question: str
    confidence_level: str | None = None
    created_at: datetime


class ExceptionOut(ApiModel):
    id: str
    workflow_id: str | None = None
    reason: str
    title: str
    priority: int
    confidence: float | None = None
    created_at: datetime


class AuditPreviewOut(ApiModel):
    sequence: int
    action: str
    severity: str
    entity_type: str | None = None
    occurred_at: datetime


class DashboardSummaryOut(ApiModel):
    total_returns: int
    total_filed: int
    by_status: list[StatusCount]
    by_tax_year: list[StatusCount]
    by_filing_type: list[StatusCount]
    workflows_running: int
    workflows_awaiting_review: int
    open_review_items: int
    documents_processed: int
    pii_entities_masked: int
    confidence_distribution: list[ConfidenceBucket]
    recent_uploads: list[RecentUploadOut]
    recent_chats: list[RecentChatOut]
    exceptions: list[ExceptionOut]
    audit_preview: list[AuditPreviewOut]
    knowledge_sources: int
    generated_at: datetime


# ===========================================================================
# Chat
# ===========================================================================


class StateRefOut(ApiModel):
    code: str
    name: str


class StateSectionOut(ApiModel):
    state_code: str
    heading: str
    content: str


class ReferenceOut(ApiModel):
    kind: str
    label: str
    description: str = ""


class NextStepOut(ApiModel):
    action: str
    deadline: str = ""


class ProfessionalHelpOut(ApiModel):
    recommended: bool = False
    reason: str = ""


class AssistantCitationOut(ApiModel):
    """A source Google Search grounding returned for this answer."""

    index: int
    title: str
    url: str
    domain: str
    authority: str
    authority_label: str
    state_code: str | None = None
    supporting_text: str = ""


class OfficialLinkOut(ApiModel):
    """An agency home page from the state registry. Not a citation."""

    state_code: str
    label: str
    url: str


class AssistantAnswerOut(ApiModel):
    """One assistant reply.

    ``status`` is ``answered``, ``declined`` (an evasion request, answered
    with the legal alternatives), ``clarify`` (one question back, because the
    answer depends on it), ``out_of_scope``, ``fallback`` (two generations
    failed validation; nothing unverified is shown), ``unavailable`` (no
    model, or the provider failed) or ``legacy`` (a turn stored by an earlier
    assistant).

    A current answer is ``answer_markdown``, shaped to the question. The
    sectioned fields (``why``, ``example``, ``references`` ...) are what
    answers stored before the streaming rebuild hold, and stay so those
    conversations still render.
    """

    message_id: str
    session_id: str
    status: str
    scope: str = "us_tax"
    category: str = "other"
    selected_state: str | None = None
    #: Set when the user switched states since the previous turn.
    state_change_notice: str = ""
    jurisdiction_level: str = "federal"
    states: list[StateRefOut] = Field(default_factory=list)
    spans_states: bool = False
    tax_year: str = ""
    tax_year_assumed: bool = False
    tax_year_note: str = ""
    #: The year the answer had to be for, and whether it fell back to an
    #: earlier year whose figures are published (``tax_year`` is that year).
    tax_year_requested: int | None = None
    tax_year_fallback: bool = False
    quick_answer: str
    #: The whole answer, in markdown, with display-numbered source markers.
    answer_markdown: str = ""
    #: fact, how_to, scenario, case_news, dispute, multi_state, clarify ...
    answer_type: str = ""
    #: The Google searches the model actually ran for this answer.
    search_queries: list[str] = Field(default_factory=list)
    #: Sentences stating a figure that no source passage was matched to; each
    #: carries a ``[?]`` flag in ``answer_markdown``.
    unsourced_figures: int = 0
    #: Replayed from an identical question answered earlier today.
    from_cache: bool = False
    #: The answer states figures but not the tax year they are for (flagged
    #: with a note rather than regenerated).
    tax_year_missing: bool = False
    why: str = ""
    example: str = ""
    state_sections: list[StateSectionOut] = Field(default_factory=list)
    facts_relied_on: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    references: list[ReferenceOut] = Field(default_factory=list)
    next_steps: list[NextStepOut] = Field(default_factory=list)
    considerations: list[str] = Field(default_factory=list)
    recent_or_pending_changes: list[str] = Field(default_factory=list)
    unverified_points: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    professional_help: ProfessionalHelpOut = Field(default_factory=ProfessionalHelpOut)
    confidence: str = "medium"
    citations: list[AssistantCitationOut] = Field(default_factory=list)
    #: Answer field key ("why", "considerations.2") -> citation numbers.
    section_citations: dict[str, list[int]] = Field(default_factory=dict)
    #: Google's search-suggestions chip; its terms require showing it.
    search_suggestions_html: str = ""
    official_links: list[OfficialLinkOut] = Field(default_factory=list)
    validation_issues: list[str] = Field(default_factory=list)
    disclaimer: str = ""
    #: True when personal details in the question were masked before use.
    was_masked: bool = False
    model: str = ""
    latency_ms: int = 0
    #: Milliseconds until the first answer text was streamed, if any was.
    first_token_ms: int | None = None
    attempts: int = 0


class ChatSessionOut(ApiModel):
    id: str
    title: str
    jurisdiction: str
    state_code: str | None = None
    tax_year: int | None = None
    message_count: int
    last_message_at: datetime | None = None
    created_at: datetime


# ===========================================================================
# Review
# ===========================================================================


class ReviewItemOut(ApiModel):
    id: str
    workflow_id: str | None = None
    document_id: str | None = None
    extraction_id: str | None = None
    reason: str
    status: str
    priority: int
    title: str
    description: str | None = None
    field_name: str | None = None
    #: TOKENIZED — masked snippet only.
    masked_source_snippet: str | None = None
    proposed_value: str | None = None
    corrected_value: str | None = None
    confidence: float | None = None
    source_page: int | None = None
    source_bbox: list[Any] | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    reviewer_notes: str | None = None
    created_at: datetime


class ReviewQueueResponse(ApiModel):
    items: list[ReviewItemOut]
    total: int
    pending: int


class ReviewDecisionRequest(ApiModel):
    notes: str | None = Field(default=None, max_length=4000)


class ReviewEditRequest(ReviewDecisionRequest):
    corrected_value: str = Field(min_length=0, max_length=4000)


# ===========================================================================
# Templates
# ===========================================================================


class LearnedTemplateOut(ApiModel):
    id: str
    name: str
    input_document_type: str
    output_document_type: str
    filing_type: str
    tax_year: int | None = None
    status: str
    version: int
    rules: list[Any]
    sample_evidence: list[Any] | None = None
    pair_count: int
    support: float
    confidence: float
    times_applied: int
    approved_by: str | None = None
    approved_at: datetime | None = None
    created_at: datetime


class LearnTemplatesRequest(ApiModel):
    directory: str | None = None
    max_pairs: int = Field(default=20, ge=1, le=100)


class LearningReportOut(ApiModel):
    pairs_found: int
    pairs_processed: int
    pairs_unreadable: int
    templates_proposed: int
    rules_inferred: int
    notes: list[str] = Field(default_factory=list)


# ===========================================================================
# Audit
# ===========================================================================


class AuditEventOut(ApiModel):
    id: str
    sequence: int
    action: str
    severity: str
    actor_id: str | None = None
    actor_role: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    payload: dict[str, Any] | None = None
    occurred_at: datetime
    event_hash: str


class AuditListResponse(ApiModel):
    items: list[AuditEventOut]
    total: int
    chain_valid: bool
    broken_sequences: list[int] = Field(default_factory=list)


# ===========================================================================
# Settings
# ===========================================================================


class SettingsOut(ApiModel):
    """Operational configuration.

    SECURITY: contains no secret values. API keys are reported only as a
    boolean "configured" flag — never echoed, not even partially masked.
    """

    app_env: str
    app_version: str
    gemini_configured: bool
    gemini_enabled: bool
    model_flash: str
    model_pro: str
    model_flash_lite: str
    assistant_model: str = ""
    egress_guard_enabled: bool
    egress_guard_mode: str
    ocr_available: bool
    ocr_engine_path_configured: bool
    allow_cloud_ocr_fallback: bool
    spacy_ner_available: bool
    tax_files_dir: str
    max_upload_mb: int
    allowed_extensions: list[str]
    confidence_auto_approve: float
    confidence_escalate: float
    calc_tolerance_dollars: float
    retention_raw_days: int
    retention_masked_days: int
    retention_audit_days: int
    rate_limit_enabled: bool
    auth_disabled: bool
    supported_tax_years: list[int]
    verified_tax_years: list[int]


class HealthOut(ApiModel):
    status: str
    version: str
    database: bool
    ocr: bool
    ner: bool
    llm: bool
    warnings: list[str] = Field(default_factory=list)


# Resolve the forward reference used in WorkflowDetailOut.
WorkflowDetailOut.model_rebuild()


# ===========================================================================
# Explainability
# ===========================================================================


class RuleCitationOut(ApiModel):
    title: str
    url: str
    kind: str


class TaxRuleOut(ApiModel):
    id: str
    title: str
    plain_english: str
    irc_section: str
    citations: list[RuleCitationOut]
    jurisdiction: str
    effective_from: int
    effective_to: int | None
    #: False when the statutory cite is not confirmed against primary text.
    #: Surfaced so the UI can mark it, never silently presented as confirmed.
    verified: bool
    notes: str


class OperandOut(ApiModel):
    """One input to a line, with where it came from."""

    label: str
    amount: str
    provenance: str
    role: str
    field_name: str
    documents: list[str]
    detail: str


class LineExplanationOut(ApiModel):
    line: str
    label: str
    amount: str
    section: str
    section_title: str
    rule: TaxRuleOut
    formula: str
    narrative: str
    operands: list[OperandOut]
    provenance: str
    status: str
    confidence: float | None
    arithmetic_checked: bool
    source_documents: list[str]
    note: str


class ExplanationSectionOut(ApiModel):
    key: str
    title: str
    lines: list[LineExplanationOut]


class ExplanationOut(ApiModel):
    """The full "How We Arrived Here" payload for one computed return."""

    tax_year: int
    filing_status: str
    deduction_method: str
    summary: dict[str, str]
    sections: list[ExplanationSectionOut]
    lines: list[LineExplanationOut]
    rules_applied: list[TaxRuleOut]
    assumptions: list[str]
    warnings: list[str]
    unverified_citations: list[str]


class AssistantQueryRequest(ApiModel):
    """A question for the assistant.

    ``selected_state`` is the state clicked on the map. It is structured
    input, validated here against the registry's allow-list (50 states, DC,
    Puerto Rico); anything else is rejected with a 422 rather than guessed at.
    """

    question: str = Field(min_length=3, max_length=8000)
    session_id: str | None = None
    selected_state: str | None = Field(default=None, max_length=8)
    #: Forces the year, over anything the question says (API callers, evals).
    tax_year: int | None = Field(default=None, ge=1980, le=2100)
    #: The year selected in the app. Like ``selected_state`` it is context,
    #: not a demand: a year the question names wins over it.
    selected_tax_year: int | None = Field(default=None, ge=1980, le=2100)

    @field_validator("selected_state")
    @classmethod
    def _known_state(cls, value: str | None) -> str | None:
        from app.services.assistant.state_registry import ALLOWED_CODES

        if value is None or not value.strip():
            return None
        code = value.strip().upper()
        if code not in ALLOWED_CODES:
            raise ValueError(
                "selected_state must be the two-letter code of a US state, DC or PR"
            )
        return code


# ===========================================================================
# Authentication
# ===========================================================================


class LoginRequest(ApiModel):
    """Sign-in credentials.

    The password bound is generous rather than strict: rejecting a long
    passphrase at the schema layer would be a validation error that tells an
    attacker their guess was the wrong *shape*, and it punishes the users doing
    the right thing.
    """

    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)


class TokenOut(ApiModel):
    """A bearer token and the little the UI needs to render a session.

    SECURITY: carries no password hash, no user id beyond what the token
    already states, and no claim the token does not itself carry signed.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    username: str
    role: str


class PrincipalOut(ApiModel):
    """The caller, as the server understands them."""

    user_id: str
    username: str
    role: str
    #: First name for the dashboard greeting: the first word of the user's
    #: full name when one is on record, otherwise the username.
    first_name: str = ""


class QuotaOut(ApiModel):
    """Today's usage against the daily ceilings.

    Shown so a tester who is turned away can see why, and an operator can see
    what the deployment is spending without reading the database.
    """

    day: str
    groups: dict[str, dict[str, int]]


# ===========================================================================
# Chatbot workspace
# ===========================================================================


class AgencyOut(ApiModel):
    name: str
    url: str
    administers: str = ""


class StateProfileOut(ApiModel):
    """One jurisdiction, as the map, the selector and the state panel need it.

    Structure only - agencies, links and features. No rates or thresholds:
    those come from grounded answers, with a source and a year.
    """

    code: str
    name: str
    kind: str
    agency: str
    agency_url: str
    agencies: list[AgencyOut] = Field(default_factory=list)
    updates_url: str
    taxes_wage_income: bool
    has_statewide_sales_tax: bool
    business_tax: str = ""
    features: list[str] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)


class StateUpdateOut(ApiModel):
    headline: str
    summary: str
    url: str
    #: ISO date, or empty when the item does not state one.
    published: str = ""
    source: str = ""


class StateUpdatesOut(ApiModel):
    state_code: str
    state_name: str
    agency: str
    agency_url: str
    updates_url: str
    items: list[StateUpdateOut] = Field(default_factory=list)
    fetched_at: str = ""
    from_cache: bool = False
    #: Populated when nothing could be fetched. "Nothing published" and "we
    #: could not look" are different facts and the panel must not conflate
    #: them into an empty list.
    error: str = ""


class AttachmentOut(ApiModel):
    document_id: str
    file_id: str
    filename: str
    size_bytes: int = 0
    page_count: int = 0
    chunk_count: int = 0
    #: How many values were tokenized before anything left the machine.
    masked_value_count: int = 0
    extraction_confidence: float = 1.0
    coverage: float = 1.0
    needs_review: bool = False
    note: str = ""


class SuggestionsOut(ApiModel):
    suggestions: list[str] = Field(default_factory=list)


class AssistantTurnOut(ApiModel):
    id: str
    #: The stored question, which is the **masked** text.
    question: str
    answer: AssistantAnswerOut | None = None


class ChatConversationOut(ApiModel):
    """A conversation plus its turns, for reloading from the sidebar.

    Stored turns are masked: a reloaded conversation shows placeholders where
    the person typed a name, and ``was_masked`` lets the UI say so.
    """

    session: ChatSessionOut
    turns: list[AssistantTurnOut] = Field(default_factory=list)
    attachments: list[AttachmentOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Calculation-graph provenance
# ---------------------------------------------------------------------------


class SourceFactOut(ApiModel):
    """Where one figure was read. Document, page and box - never the page text."""

    field: str
    document_id: str
    document_type: str
    page: int
    confidence: str
    #: [x0, y0, x1, y1] in PDF points, or None when not located unambiguously.
    bbox: list[str] | None = None
    amount: str | None = None
    extraction_id: str = ""


class AuthorityOut(ApiModel):
    citation: str
    url: str
    kind: str


class GraphLineOut(ApiModel):
    """One evaluated line. ``amount`` None means unsupported, never zero."""

    node_id: str
    form: str
    line: str
    label: str
    amount: str | None
    formula: str
    reference: str
    inputs: list[list[str | None]] = Field(default_factory=list)
    authority: AuthorityOut | None = None
    sources: list[SourceFactOut] = Field(default_factory=list)
    basis: str
    flags: list[str] = Field(default_factory=list)


class UnplacedFigureOut(ApiModel):
    field: str
    amount: str
    reason: str
    #: False only when the graph computes the figure itself or it is not a
    #: Form 1040 input; otherwise the return is missing money and not fileable.
    blocks_filing: bool = True


class GraphReturnOut(ApiModel):
    """Every line of every form the graph computed for this workflow."""

    tax_year: int
    filing_status: str
    #: False while any line is unsupported or any read figure is unplaced.
    fileable: bool
    forms: list[str]
    unsupported: list[str]
    unverified_authorities: list[str]
    lines: list[GraphLineOut]
    #: Figures the pipeline read that no graph line takes. Shown, not dropped.
    unplaced: list[UnplacedFigureOut] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ExplainNodeOut(GraphLineOut):
    """``explain(node_id)``: one line and, recursively, what it was computed from."""

    leaf: str | None = None
    repeated: bool = False
    children: list[ExplainNodeOut] = Field(default_factory=list)


class FigureBoxOut(ApiModel):
    text: str
    bbox: list[float]


class SourcePageOut(ApiModel):
    """One page of a source document, as the masked zone holds it.

    SECURITY: masked text and money-shaped figure boxes only. There is no
    route that returns the page image or the unmasked text.
    """

    document_id: str
    document_type: str
    page: int
    page_start: int
    page_end: int
    width: float
    height: float
    masked_text: str
    #: True when this run predates per-page text and ``masked_text`` is the
    #: whole document. The UI says so rather than implying it is one page.
    whole_document: bool = False
    figures: list[FigureBoxOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# LLM cost
# ---------------------------------------------------------------------------


class CostBucketOut(ApiModel):
    key: str
    calls: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    thinking_tokens: int
    cost_usd: str
    #: Calls the price file had no rate for. Not in ``cost_usd``.
    unpriced_calls: int
    stub_calls: int
    failed_calls: int


class WorkflowCostOut(ApiModel):
    """What this return's model calls cost, by stage and by model."""

    workflow_id: str
    total: CostBucketOut
    by_stage: list[CostBucketOut]
    by_model: list[CostBucketOut]
    pages: int
    cost_per_page_usd: str | None
    prices_as_of: list[str]
    prices_source: str
