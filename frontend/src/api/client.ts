/**
 * Typed API client for the TaxScraper backend.
 *
 * All network access goes through `request()`, which gives one place to attach
 * auth, normalise error shapes, and keep the UI from having to know the
 * backend's error envelope.
 */

import type { HolidayData } from '../lib/dates';
import type {
  ClientFacts, CountdownTileRule, EntityRule, EntityType, StateDueRules,
} from '../lib/deadlines';
import type { MotivationBank } from '../lib/motivation';

const BASE = import.meta.env.VITE_API_BASE ?? '';

/**
 * Where the bearer token lives.
 *
 * `localStorage` rather than a cookie because the API is on a different origin
 * in every deployed configuration, and a cross-site cookie would need SameSite
 * relaxed to None — which is a bigger surface than a token this code attaches
 * deliberately to requests it makes itself.
 */
const TOKEN_KEY = 'taxscraper_token';

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null; // private mode, or storage blocked
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* the session simply will not survive a reload */
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* nothing to clear */
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string = 'error',
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  // Bearer token is only present when the backend runs with AUTH_DISABLED=false.
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(
      'Cannot reach the backend. Is it running on port 8000?',
      0,
      'network_error',
    );
  }

  if (response.status === 204) return undefined as T;

  const isJson = response.headers
    .get('content-type')
    ?.includes('application/json');
  const payload = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    const envelope = (payload as { error?: { message?: string; code?: string; details?: Record<string, unknown> } })?.error;
    throw new ApiError(
      envelope?.message ?? `Request failed (${response.status})`,
      response.status,
      envelope?.code ?? 'error',
      envelope?.details ?? {},
    );
  }
  return payload as T;
}

const get = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined });
const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'PUT', body: JSON.stringify(body) });
const del = <T>(path: string) => request<T>(path, { method: 'DELETE' });

// ===========================================================================
// Server-Sent Events (assistant progress, workpaper pipeline progress)
// ===========================================================================

export interface AssistantStep { phase: string; message: string }
export interface AssistantStreamHandlers {
  onStep?: (step: AssistantStep) => void;
  /** Answer text to append, as the model writes it. */
  onDelta?: (text: string) => void;
  /** The text streamed so far was withdrawn (it failed a check, or the stream broke). */
  onReplace?: (message: string) => void;
  onFinal?: (answer: AssistantAnswer) => void;
  onError?: (message: string) => void;
}

/**
 * POST to an SSE endpoint and dispatch parsed events. Uses fetch + a stream
 * reader because EventSource only supports GET and cannot send a JSON body.
 */
/**
 * Read a server-sent-event stream, calling `onEvent` for each `data:` record.
 *
 * Shared by the chat and the workpaper pipeline: both send JSON objects with a
 * `type` discriminator over the same transport, and the only thing that differs
 * between them is what they do with each event.
 */
async function readEventStream(
  path: string,
  payload: unknown,
  onEvent: (event: Record<string, unknown>) => void,
  onError: (message: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers = new Headers({ 'Content-Type': 'application/json' });
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal,
    });
  } catch {
    onError('Cannot reach the backend. Is it running on port 8000?');
    return;
  }

  if (!response.ok || !response.body) {
    onError(`Request failed (${response.status})`);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const dispatch = (raw: string) => {
    // An SSE record: one or more lines; we only emit `data:` payloads.
    const dataLines = raw
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trim());
    if (dataLines.length === 0) return;
    const json = dataLines.join('\n');
    if (!json || json === '{}') return;

    try {
      onEvent(JSON.parse(json) as Record<string, unknown>);
    } catch {
      /* a malformed record is skipped rather than killing the stream */
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE records are separated by a blank line.
    let boundary = buffer.indexOf('\n\n');
    while (boundary !== -1) {
      dispatch(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf('\n\n');
    }
  }
}

async function streamAssistant(
  payload: AssistantQuery,
  handlers: AssistantStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  await readEventStream(
    '/api/chat/stream',
    payload,
    (event) => {
      switch (event.type) {
        case 'step':
          handlers.onStep?.({
            phase: String(event.phase ?? ''),
            message: String(event.message ?? ''),
          });
          break;
        case 'delta':
          handlers.onDelta?.(String(event.text ?? ''));
          break;
        case 'replace':
          handlers.onReplace?.(String(event.message ?? ''));
          break;
        case 'final':
          handlers.onFinal?.(event.answer as AssistantAnswer);
          break;
        case 'error':
          handlers.onError?.(String(event.message ?? 'Something went wrong.'));
          break;
      }
    },
    (message) => handlers.onError?.(message),
    signal,
  );
}

/** One stage of the workpaper pipeline, as the user watches it run. */
export interface PipelineProgress {
  stage: string;
  label: string;
  status: 'running' | 'completed' | 'failed';
  step: number;
  steps: number;
  percent: number;
  note: string;
}

export interface PipelineDone {
  workflow_id: string;
  status: string;
  documents: number;
  facts: number;
  review_items: number;
  packages: number;
}

async function streamProcess(
  fileId: string,
  taxYear: number | undefined,
  handlers: {
    onProgress?: (progress: PipelineProgress) => void;
    onDone?: (result: PipelineDone) => void;
    onError?: (message: string) => void;
  },
  signal?: AbortSignal,
): Promise<void> {
  await readEventStream(
    `/api/workflows/${fileId}/process/stream`,
    { tax_year: taxYear ?? null },
    (event) => {
      if (event.type === 'stage') {
        handlers.onProgress?.(event as unknown as PipelineProgress);
      } else if (event.type === 'done') {
        handlers.onDone?.(event as unknown as PipelineDone);
      } else if (event.type === 'error') {
        handlers.onError?.(String(event.message ?? 'Processing failed.'));
      }
    },
    (message) => handlers.onError?.(message),
    signal,
  );
}

// ===========================================================================
// Types (mirror backend/app/schemas/api.py)
// ===========================================================================

export interface StatusCount { key: string; label: string; count: number }
export interface ConfidenceBucket { label: string; lower: number; upper: number; count: number }

export interface RecentUpload {
  id: string; original_filename: string; extension: string;
  size_bytes: number; status: string; created_at: string;
}
export interface RecentChat {
  id: string; session_id: string; question: string;
  confidence_level: string | null; created_at: string;
}
export interface ExceptionItem {
  id: string; workflow_id: string | null; reason: string; title: string;
  priority: number; confidence: number | null; created_at: string;
}
export interface AuditPreview {
  sequence: number; action: string; severity: string;
  entity_type: string | null; occurred_at: string;
}

export interface DashboardSummary {
  total_returns: number;
  total_filed: number;
  by_status: StatusCount[];
  by_tax_year: StatusCount[];
  by_filing_type: StatusCount[];
  workflows_running: number;
  workflows_awaiting_review: number;
  open_review_items: number;
  documents_processed: number;
  pii_entities_masked: number;
  confidence_distribution: ConfidenceBucket[];
  recent_uploads: RecentUpload[];
  recent_chats: RecentChat[];
  exceptions: ExceptionItem[];
  audit_preview: AuditPreview[];
  knowledge_sources: number;
  generated_at: string;
}

export interface UploadedFile {
  id: string; filing_id: string | null; original_filename: string;
  content_type: string; extension: string; size_bytes: number;
  content_hash: string; status: string; is_encrypted: boolean;
  file_metadata: Record<string, unknown> | null;
  validation_notes: string | null; created_at: string;
}

export interface StageRun {
  stage: string; stage_index: number; status: string;
  started_at: string | null; completed_at: string | null;
  duration_ms: number | null; detail: Record<string, unknown> | null;
  error_message: string | null;
}

export interface DocumentInfo {
  id: string; document_type: string; classification_confidence: number;
  classification_method: string; page_start: number; page_end: number;
  page_count: number; is_handwritten: boolean; requires_ocr: boolean;
  ocr_performed: boolean; ocr_engine: string | null;
  ocr_mean_confidence: number | null;
}

export interface Extraction {
  id: string; field_name: string; field_label: string | null;
  masked_value: string | null; confidence: number; extraction_method: string;
  source_page: number | null; target_form: string | null;
  target_line: string | null; validation_status: string | null;
  requires_review: boolean;
}

export interface OutputPackage {
  id: string; artifact_type: string; filename: string; content_type: string;
  size_bytes: number; is_rehydrated: boolean; tokens_rehydrated: number;
  download_count: number; created_at: string;
}

export interface Workflow {
  id: string; uploaded_file_id: string; filing_id: string | null;
  status: string; current_stage: string; progress_percent: number;
  started_at: string | null; completed_at: string | null;
  error_summary: string | null; documents_detected: number;
  pii_entities_masked: number; review_items_open: number;
  overall_confidence: number | null;
  llm_usage: Record<string, unknown> | null; created_at: string;
  source_filename?: string | null;
  stages?: StageRun[]; documents?: DocumentInfo[];
  extractions?: Extraction[]; output_packages?: OutputPackage[];
}


// --- Explainability -------------------------------------------------------

export interface RuleCitation { title: string; url: string; kind: string }

export interface TaxRule {
  id: string; title: string; plain_english: string; irc_section: string;
  citations: RuleCitation[]; jurisdiction: string;
  effective_from: number; effective_to: number | null;
  /** False when the statutory cite is unconfirmed — the UI must mark it. */
  verified: boolean; notes: string;
}

export type Provenance =
  | 'source_document' | 'computed' | 'prior_year'
  | 'election' | 'taxpayer_profile' | 'assumption';

export type LineStatus = 'verified' | 'computed' | 'needs_review';

export interface Operand {
  label: string; amount: string; provenance: Provenance;
  role: 'add' | 'subtract' | 'info'; field_name: string;
  documents: string[]; detail: string;
}

export interface LineExplanation {
  line: string; label: string; amount: string;
  section: string; section_title: string;
  rule: TaxRule; formula: string; narrative: string;
  operands: Operand[]; provenance: Provenance; status: LineStatus;
  confidence: number | null; arithmetic_checked: boolean;
  source_documents: string[]; note: string;
}

export interface ExplanationSection {
  key: string; title: string; lines: LineExplanation[];
}

export interface Explanation {
  tax_year: number; filing_status: string; deduction_method: string;
  summary: Record<string, string>;
  sections: ExplanationSection[];
  lines: LineExplanation[];
  rules_applied: TaxRule[];
  assumptions: string[];
  warnings: string[];
  unverified_citations: string[];
}

// --- Calculation graph provenance -----------------------------------------

export interface SourceFact {
  field: string; document_id: string; document_type: string; page: number;
  confidence: string;
  /** [x0, y0, x1, y1] in PDF points; null when not located unambiguously. */
  bbox: string[] | null;
  amount: string | null; extraction_id: string;
}

export interface GraphLine {
  node_id: string; form: string; line: string; label: string;
  /** null means the engine would not compute this line - never show it as 0. */
  amount: string | null;
  formula: string; reference: string;
  inputs: (string | null)[][];
  authority: { citation: string; url: string; kind: string } | null;
  sources: SourceFact[]; basis: string; flags: string[];
}

export type LeafKind =
  | 'source' | 'statutory' | 'not_reported' | 'nil'
  | 'supplied' | 'unsupported' | 'standalone';

export interface ExplainNode extends GraphLine {
  leaf: LeafKind | null; repeated: boolean; children: ExplainNode[];
}

export interface GraphReturn {
  tax_year: number; filing_status: string; fileable: boolean;
  forms: string[]; unsupported: string[]; unverified_authorities: string[];
  lines: GraphLine[];
  unplaced: { field: string; amount: string; reason: string; blocks_filing: boolean }[];
  notes: string[];
}

export interface SourcePage {
  document_id: string; document_type: string; page: number;
  page_start: number; page_end: number; width: number; height: number;
  masked_text: string; whole_document: boolean;
  figures: { text: string; bbox: number[] }[];
}

// --- LLM cost ----------------------------------------------------------------

export interface CostBucket {
  key: string; calls: number;
  input_tokens: number; output_tokens: number;
  cached_tokens: number; thinking_tokens: number;
  /** Decimal string, USD. Excludes unpriced calls. */
  cost_usd: string;
  unpriced_calls: number; stub_calls: number; failed_calls: number;
}

export interface WorkflowCost {
  workflow_id: string; total: CostBucket;
  by_stage: CostBucket[]; by_model: CostBucket[];
  pages: number; cost_per_page_usd: string | null;
  prices_as_of: string[]; prices_source: string;
}

export interface MaskedPreview {
  document_id: string; document_type: string; page_start: number;
  page_end: number; masked_text: string; token_count: number;
  token_map: Record<string, string>;
}

/** A source returned by Google Search grounding for this answer. */
export interface AssistantCitation {
  index: number; title: string; url: string; domain: string;
  authority: string; authority_label: string;
  state_code: string | null; supporting_text: string;
}

export type AssistantStatus =
  | 'answered' | 'declined' | 'clarify' | 'out_of_scope' | 'fallback' | 'unavailable' | 'legacy';

/** One assistant reply. Every reply, including a fallback, has this shape. */
export interface AssistantAnswer {
  message_id: string; session_id: string;
  status: AssistantStatus; scope: string; category: string;
  selected_state: string | null;
  /** Set when the user switched states since the previous turn. */
  state_change_notice: string;
  jurisdiction_level: string;
  states: { code: string; name: string }[];
  spans_states: boolean;
  tax_year: string; tax_year_assumed: boolean; tax_year_note: string;
  /** The year the answer had to be for; `tax_year_fallback` means it uses an earlier year's figures. */
  tax_year_requested?: number | null; tax_year_fallback?: boolean;
  quick_answer: string;
  /** The whole answer in markdown, shaped to the question. Empty on turns stored before it existed. */
  answer_markdown: string;
  /** fact, how_to, scenario, case_news, dispute, multi_state, clarify ... */
  answer_type: string;
  /** The Google searches the model ran for this answer. */
  search_queries: string[];
  why: string; example: string;
  state_sections: { state_code: string; heading: string; content: string }[];
  facts_relied_on: string[]; assumptions: string[];
  references: { kind: string; label: string; description: string }[];
  next_steps: { action: string; deadline: string }[];
  considerations: string[];
  recent_or_pending_changes: string[];
  unverified_points: string[];
  follow_up_questions: string[];
  professional_help: { recommended: boolean; reason: string };
  confidence: string;
  citations: AssistantCitation[];
  /** Answer field key ("why", "considerations.2") -> citation numbers. */
  section_citations: Record<string, number[]>;
  search_suggestions_html: string;
  /** Agency home pages from the state registry. Not citations. */
  official_links: { state_code: string; label: string; url: string }[];
  validation_issues: string[];
  disclaimer: string;
  was_masked: boolean;
  model: string; latency_ms: number; attempts: number;
  /** Milliseconds until the first answer text streamed, when any did. */
  first_token_ms?: number | null;
  /** Sentences stating a figure that no source passage was matched to; each is marked [?]. */
  unsourced_figures?: number;
  /** Replayed from an identical question answered earlier today. */
  from_cache?: boolean;
}

export interface AssistantQuery {
  question: string;
  session_id?: string | null;
  /** The state clicked on the map; validated server-side. */
  selected_state?: string | null;
  /** Forces the year over anything the question says. */
  tax_year?: number | null;
  /** The year selected in the app: context, like the state. A year the question names wins. */
  selected_tax_year?: number | null;
}

export interface StateProfile {
  code: string; name: string; kind: string;
  agency: string; agency_url: string;
  agencies: { name: string; url: string; administers: string }[];
  updates_url: string;
  taxes_wage_income: boolean; has_statewide_sales_tax: boolean;
  business_tax: string;
  /** Structural features, e.g. "Community property state". No figures. */
  features: string[];
  hints: string[];
}

export interface StateUpdate {
  headline: string; summary: string; url: string;
  published: string; source: string;
}

export interface StateUpdates {
  state_code: string; state_name: string; agency: string;
  agency_url: string; updates_url: string; items: StateUpdate[];
  fetched_at: string; from_cache: boolean; error: string;
}

export interface Attachment {
  document_id: string; file_id: string; filename: string;
  size_bytes: number; page_count: number; chunk_count: number;
  masked_value_count: number; extraction_confidence: number;
  coverage: number; needs_review: boolean; note: string;
}

export interface AssistantTurn {
  id: string;
  /** The stored question, which is the masked text. */
  question: string;
  answer: AssistantAnswer | null;
}

export interface ChatConversation {
  session: ChatSession;
  turns: AssistantTurn[];
  attachments: Attachment[];
}

export interface ChatSession {
  id: string; title: string; jurisdiction: string; state_code: string | null;
  tax_year: number | null; message_count: number;
  last_message_at: string | null; created_at: string;
}

export interface ReviewItem {
  id: string; workflow_id: string | null; document_id: string | null;
  extraction_id: string | null; reason: string; status: string;
  priority: number; title: string; description: string | null;
  field_name: string | null; masked_source_snippet: string | null;
  proposed_value: string | null; corrected_value: string | null;
  confidence: number | null; source_page: number | null;
  source_bbox: unknown[] | null; reviewed_by: string | null;
  reviewed_at: string | null; reviewer_notes: string | null; created_at: string;
}

export interface AuditEvent {
  id: string; sequence: number; action: string; severity: string;
  actor_id: string | null; actor_role: string | null;
  entity_type: string | null; entity_id: string | null;
  payload: Record<string, unknown> | null; occurred_at: string;
  event_hash: string;
}

export interface LearnedTemplate {
  id: string; name: string; input_document_type: string;
  output_document_type: string; filing_type: string; tax_year: number | null;
  status: string; version: number; rules: unknown[];
  sample_evidence: unknown[] | null; pair_count: number; support: number;
  confidence: number; times_applied: number; approved_by: string | null;
  approved_at: string | null; created_at: string;
}

export interface AppSettings {
  app_env: string; app_version: string; gemini_configured: boolean;
  gemini_enabled: boolean; model_flash: string; model_pro: string;
  model_flash_lite: string; assistant_model: string;
  egress_guard_enabled: boolean;
  egress_guard_mode: string; ocr_available: boolean;
  ocr_engine_path_configured: boolean; allow_cloud_ocr_fallback: boolean;
  spacy_ner_available: boolean; tax_files_dir: string; max_upload_mb: number;
  allowed_extensions: string[]; confidence_auto_approve: number;
  confidence_escalate: number; calc_tolerance_dollars: number;
  retention_raw_days: number; retention_masked_days: number;
  retention_audit_days: number; rate_limit_enabled: boolean;
  auth_disabled: boolean; supported_tax_years: number[];
  verified_tax_years: number[];
}

export interface Health {
  status: string; version: string; database: boolean; vector_store: boolean;
  ocr: boolean; ner: boolean; llm: boolean; warnings: string[];
}

// ===========================================================================
// Endpoints
// ===========================================================================

export interface Token {
  access_token: string; token_type: string; expires_in_minutes: number;
  username: string; role: string;
}

export interface PrincipalInfo {
  user_id: string; username: string; role: string;
  /** First name for the greeting; the username when no name is on record. */
  first_name?: string;
}

export interface QuotaGroup {
  used: number; limit: number; remaining: number;
  global_used: number; global_limit: number; global_remaining: number;
}

export interface Quota {
  day: string;
  groups: Record<string, QuotaGroup>;
}

/**
 * Download an artifact through an authenticated request.
 *
 * A plain `<a href>` cannot carry the Authorization header, so with auth
 * enabled every download link 401s while looking to the user like a broken
 * file. Fetching the bytes and handing them to the browser as an object URL is
 * what makes the link work at all once the deployment is not in dev mode.
 */
export async function downloadArtifact(
  workflowId: string,
  artifactType: string,
  fallbackName: string,
): Promise<void> {
  return downloadFrom(
    `/api/workflows/${workflowId}/download?artifact_type=${encodeURIComponent(artifactType)}`,
    fallbackName,
  );
}

async function downloadFrom(path: string, fallbackName: string): Promise<void> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const response = await fetch(`${BASE}${path}`, { headers });
  if (!response.ok) {
    throw new ApiError(
      response.status === 401 || response.status === 403
        ? 'Your session has expired. Sign in again to download.'
        : `Download failed (${response.status})`,
      response.status,
      'download_failed',
    );
  }

  // Prefer the filename the server set; it carries the artifact's real name.
  const disposition = response.headers.get('content-disposition') ?? '';
  const matched = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  const name = matched ? decodeURIComponent(matched[1]) : fallbackName;

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Revoked on the next tick: revoking synchronously races the click in Safari.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

// ===========================================================================
// Depreciation calculator
// ===========================================================================

export interface RuleSource {
  key: string; label: string; source_citation: string; source_url: string;
  last_verified: string | null; verified: boolean; verify_note: string;
}

export interface DepreciationAssetClass {
  key: string; label: string; recovery_years: string | null; allowed_recovery_years: string[];
  section_179_eligible: boolean; bonus_eligible: boolean; listed: boolean; real_property: boolean;
  suv_cap: boolean; qpp: boolean; note: string; source: RuleSource;
}

export interface DepreciationStateInfo {
  code: string; name: string; business_tax: string;
  status_by_year: Record<string, string>;
  changed_recently_years: number[];
  change_notes: Record<string, string>;
}

export interface DepreciationRules {
  supported_years: number[];
  default_year: number;
  methods: { key: string; label: string }[];
  asset_classes: DepreciationAssetClass[];
  states: DepreciationStateInfo[];
  federal: Record<string, unknown>;
  rules_version: string;
}

/** One asset of the current-year additions report, its life already chosen. */
export interface AdditionAssetInput {
  asset_id: string; description: string; acquired: string; cost: string;
  asset_class: string; recovery_years?: string | null;
  /** Section 179 is elected asset by asset. */
  elect_179: boolean;
  /** Bonus is claimed unless elected out; an election out covers the asset's whole class. */
  elect_bonus: boolean;
  suv_cap_exempt: boolean;
}

export interface AdditionReportRequest {
  tax_year: number; state: string | null; assets: AdditionAssetInput[];
}

/** First-year amounts in one jurisdiction, in the order the Code applies them. */
export interface AdditionGroup {
  sec179: string; bonus: string; macrs: string; total: string;
}

/** One computed row - every figure is the depreciation engine's. */
export interface AdditionReportRow {
  asset_id: string; description: string; acquired: string; cost: string;
  life: string; asset_class: string; class_label: string; convention: string;
  elect_179: boolean; elect_bonus: boolean;
  sec179_eligible: boolean; sec179_reason: string;
  bonus_eligible: boolean; bonus_reason: string;
  /** False when the class-wide election out took bonus off this asset. */
  bonus_applied: boolean;
  bonus_rate: string;
  /** "179", "Bonus", "179+Bonus" or "MACRS only". */
  elections: string;
  federal: AdditionGroup & { macrs_rate: string };
  /** The selected state's regime over the same elections; null when it has no verified rule. */
  state: (AdditionGroup & { addback: string }) | null;
}

export interface AdditionReportState {
  code: string; name: string; status: string; message: string;
  bonus_mode: string; bonus_allowed: boolean; bonus_note: string;
  section_179_mode: string; source_url: string; source_citation: string; notes: string[];
}

export interface AdditionReport {
  tax_year: number;
  state: AdditionReportState | null;
  rows: AdditionReportRow[];
  totals: {
    cost: string;
    federal: AdditionGroup;
    state: (AdditionGroup & { adjustment: string }) | null;
  };
  summary: { life: string; cost: string; depreciation: string }[];
  /** Recovery periods whose bonus was elected out (the election covers the whole class). */
  elect_out_classes: string[];
  section_179: {
    limit: string; threshold: string; total_cost: string; reduction: string;
    dollar_limit: string; elected: string; deduction: string;
  } | null;
  warnings: string[];
  life_basis: string;
}

/** What the model (or the file, or the description) said each asset's life is. */
export interface LifePrediction {
  asset_class: string | null; recovery_years: string | null; life: string | null;
  source: 'file' | 'ai' | 'description' | 'none'; confidence: string; reason: string;
}

export interface AdditionImportRow {
  row: number; asset_id: string; description: string;
  acquired: string | null; cost: string | null; life_in_file: string | null;
  prediction: LifePrediction;
  /** Every reason the row cannot be used, as text - including "not a <year> addition". */
  problems: string[];
  /** What is wrong with the file itself, by column. The year check is the screen's, for the year chosen now. */
  issues: { column: string; message: string }[];
}

export interface AdditionImport {
  tax_year: number; state: string | null; message: string;
  rows: AdditionImportRow[]; report: AdditionReport | null; report_errors: string[];
}

export interface DepreciationAssetInput {
  id: string; description: string; asset_class: string; cost: string;
  placed_in_service: string; acquired?: string | null; business_use_pct: string;
  land_value: string; recovery_years?: string | null; section_179_amount?: string | null;
  elect_out_bonus: boolean; elect_reduced_bonus: boolean; clean_vehicle_credit: string;
  suv_cap_exempt: boolean; qpp_elect: boolean; qpp_construction_began?: string | null;
  /** 'HY' | 'MQ' | 'MM' to force a convention; null applies the law's test. */
  convention?: string | null;
}

export interface DepreciationRequest {
  tax_year: number; state: string | null; method: string;
  assets: DepreciationAssetInput[];
  taxable_business_income?: string | null; total_179_purchases?: string | null;
  section_179_carryover?: string; federal_marginal_rate?: string | null;
  state_marginal_rate?: string | null; include_provisional_state: boolean;
}

export interface ScheduleRow {
  year: number; section_179: string; bonus: string; special: string; macrs: string; total: string;
  cumulative: string; remaining: string; why: string[];
}

export interface AssetScheduleRow extends ScheduleRow {
  index: number; rate: string | null; capped: boolean;
}

export interface TapeLine {
  label: string; value: string; op: '' | '+' | '-' | 'x' | '=' | 'T';
  kind: 'money' | 'percent' | 'rate'; emphasis: boolean; note: string;
}

export interface TapeSection { title: string; lines: TapeLine[] }

export interface HeadlineFigure { label: string; value: string; why: string[] }

export interface FirstYear {
  section_179: string; bonus: string; special: string; macrs: string; carryover_used: string; total: string;
}

export interface DepreciationAssetResult {
  id: string; description: string; asset_class: string; class_label: string;
  recovery_years: string; system: string; method: string; convention: string;
  table: string; table_column: string; placed_in_service: string; cost: string;
  land_value: string; business_use_pct: string; business_basis: string;
  section_179_elected: string; section_179_allowed: string; section_179_carryforward: string;
  bonus_rate: string; bonus: string; special_allowance: string; macrs_basis: string;
  tax_year_deduction: string; total: string; schedule: AssetScheduleRow[]; tape: TapeSection[]; notes: string[];
  /** True when the user selected the convention rather than the 40% test. */
  convention_selected: boolean;
}

export interface StateScheduleRow {
  year: number; federal: string; state: string; adjustment: string; cumulative_difference: string;
}

export interface DepreciationStateResult {
  code: string; name: string;
  status: 'computed' | 'provisional' | 'not_verified' | 'no_income_tax';
  message: string; provisional_available: boolean; rows: StateScheduleRow[];
  tax_year_deduction: string | null; tax_year_adjustment: string | null; total: string | null;
  carryforward: string; reverses: boolean;
  rule: {
    summary: string; status: string; source_url: string; source_citation: string;
    last_verified: string | null; verify_note: string; change_note: string;
    conformity: { type: string; date: string | null } | null;
    bonus: Record<string, unknown> | null; section_179: Record<string, unknown> | null;
    decouples_168n: boolean | null;
  };
  changed_recently_years: number[];
  notes: string[];
}

export interface ComparisonRow {
  key: string; label: string; federal_tax_year_deduction: string; federal_first_year: FirstYear;
  federal_carryforward: string; state_tax_year_deduction: string | null;
  federal_tax_effect: string | null; state_tax_effect: string | null; combined_tax_effect: string | null;
  schedule: { year: number; total: string }[];
}

export interface DepreciationResult {
  tax_year: number; method: string; primary_scenario: string; primary_label: string;
  supported_years: number[];
  assets: DepreciationAssetResult[];
  summary: {
    current_year: HeadlineFigure; ending_cost: HeadlineFigure;
    ending_accumulated: HeadlineFigure; ending_nbv: HeadlineFigure;
  };
  tape: TapeSection[];
  federal: {
    schedule: ScheduleRow[]; tax_year_deduction: string; first_year: FirstYear; basis: string;
    total: string; carryforward: string;
    check: { depreciable_basis: string; scheduled: string; section_179_carryforward: string; ok: boolean; statement: string };
    conventions: Record<string, string>; q4_share: Record<string, string>;
  };
  section_179: Record<string, Record<string, unknown>>;
  state: DepreciationStateResult | null;
  comparison: ComparisonRow[];
  form_4562: { line: string; label: string; amount: string }[];
  warnings: string[]; notes: string[]; assumptions: string[];
  sources: RuleSource[];
  disclaimer: string;
}

export interface DepreciationExplanation {
  available: boolean; text: string; reason: string;
  citations: { index: number; title: string; url: string; domain: string; authority_label: string }[];
}

/** POST a JSON body and save the response as a file (exports need the inputs). */
async function downloadPost(path: string, body: unknown, fallbackName: string): Promise<void> {
  const headers = new Headers({ 'Content-Type': 'application/json' });
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`${BASE}${path}`, { method: 'POST', headers, body: JSON.stringify(body) });
  if (!response.ok) {
    throw new ApiError(`Download failed (${response.status})`, response.status, 'download_failed');
  }
  const disposition = response.headers.get('content-disposition') ?? '';
  const matched = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = matched ? decodeURIComponent(matched[1]) : fallbackName;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}


// ===========================================================================
// Dashboard, forms library, Industry Updates, State Intelligence
// ===========================================================================

export interface CalendarRules {
  holidays: { version: string; last_verified: string; holidays: HolidayData[];
    sources: { id: string; title: string; url: string }[] };
  due_dates: { version: string; last_verified: string; entity_types: EntityRule[];
    countdown_tiles: CountdownTileRule[]; countdown_note: string };
}

export interface QuickLink { id: string; label: string; description: string; path: string; icon: string }

export interface DashboardConfig {
  quick_links: QuickLink[];
  motivation: MotivationBank;
  /** The year every section opens on until one is chosen (server `DEFAULT_TAX_YEAR`). */
  default_tax_year: number;
  supported_years: number[];
}

export interface FormEntry {
  id: string; form_number: string; title: string; one_liner: string; one_liner_reviewed: boolean;
  category: string; audience: 'federal' | 'business' | 'state'; state: string | null;
  state_form_kind?: 'individual' | 'business' | 'extension' | null; tax_year?: number | null;
  annual: boolean; source_page_url: string; pdf_url: string; prior_year_pdf_pattern: string | null;
  latest_revision: string | null; last_verified: string | null;
  link_status?: 'ok' | 'broken' | 'host_refused_check' | null;
}

export interface FormsLibrary {
  version: string;
  categories: { key: string; label: string }[];
  forms: FormEntry[];
  state_forms: FormEntry[];
  states_with_forms: string[];
  state_agencies: Record<string, { name: string; agency: string; agency_url: string }>;
  supported_years: number[];
}

export interface StateField {
  key: string; label: string; value: string; source_url: string; source_citation: string; last_verified: string;
  /** manual: a person read the source. automated_page_match: found on the state's own page by the
   *  research script. provisional: researched at the state's source but not yet confirmed. */
  verification?: 'manual' | 'automated_page_match' | 'provisional';
  /** For automated matches: the page's own text that matched. */
  quote?: string | null;
}

export interface StateSectionData {
  key: 'apportionment' | 'nexus' | 'conformity' | 'rates' | 'filing';
  label: string; status: 'verified' | 'provisional' | 'not_verified'; message: string; as_of: string | null;
  fields: StateField[]; agency: { name: string; url: string }; shared_with?: string;
}

export interface StateIntelProfile {
  code: string; name: string; tax_year: number; supported_years: number[];
  agency: { name: string; url: string }; quick_facts: string[];
  sections: StateSectionData[]; due_rules: StateDueRules | null; disclaimer: string;
}

export interface StateIntelListing {
  supported_years: number[];
  states: { code: string; name: string;
    coverage: Record<string, { verified_fields: number; conformity_verified: boolean }> }[];
  disclaimer: string;
}

export interface WorkspaceClient extends ClientFacts { notes: string }

export interface ClientInput {
  name: string; entity_type: EntityType; fiscal_year_end_month: number; states: string[];
  extension_status: 'not_extended' | 'extended'; notes: string;
}

export interface CustomDeadline {
  id: string; title: string; due_date: string; client_id: string | null; kind: 'deadline' | 'task'; done: boolean;
}

export type CustomDeadlineInput = Omit<CustomDeadline, 'id'>;

export interface NewsItem {
  id: string; source: string; source_name: string; title: string; url: string;
  published: string; excerpt: string; topics: string[]; reference: string;
}

export interface NewsSourceStatus {
  key: string; name: string; kind: 'public' | 'licensed'; homepage: string;
  state: 'ok' | 'error' | 'not_connected' | 'disabled' | 'pending'; message: string;
  last_updated: string | null; item_count: number;
}

export interface NewsFeed {
  items: NewsItem[]; sources: NewsSourceStatus[]; topics: { key: string; label: string }[];
  last_updated: string | null;
}

export interface NewsBookmark { id: string; item_id: string; source: string; title: string; url: string; published: string }

export interface NewsSummary {
  available: boolean; text: string; reason: string; label: string; source_url: string; source_name: string;
}

export const api = {
  dashboard: {
    summary: () => get<DashboardSummary>('/api/dashboard/summary'),
  },

  files: {
    list: () => get<{ items: UploadedFile[]; total: number }>('/api/files'),
    get: (id: string) => get<UploadedFile>(`/api/files/${id}`),
    upload: async (file: File, filingId?: string) => {
      const form = new FormData();
      form.append('file', file);
      if (filingId) form.append('filing_id', filingId);
      return request<UploadedFile>('/api/files/upload', {
        method: 'POST',
        body: form,
      });
    },
  },

  workflows: {
    list: () => get<Workflow[]>('/api/workflows'),
    get: (id: string) => get<Workflow>(`/api/workflows/${id}`),
    explanation: (id: string) =>
      get<Explanation>(`/api/workflows/${id}/explanation`),
    graph: (id: string) => get<GraphReturn>(`/api/workflows/${id}/graph`),
    cost: (id: string) => get<WorkflowCost>(`/api/workflows/${id}/cost`),
    explain: (id: string, nodeId: string) =>
      get<ExplainNode>(
        `/api/workflows/${id}/graph/explain/${encodeURIComponent(nodeId)}`,
      ),
    sourcePage: (id: string, documentId: string, page: number) =>
      get<SourcePage>(
        `/api/workflows/${id}/documents/${encodeURIComponent(documentId)}/pages/${page}`,
      ),
    process: (fileId: string, taxYear?: number) =>
      post<Workflow>(`/api/workflows/${fileId}/process`, { tax_year: taxYear ?? null }),
    processStream: (
      fileId: string,
      taxYear: number | undefined,
      handlers: Parameters<typeof streamProcess>[2],
      signal?: AbortSignal,
    ) => streamProcess(fileId, taxYear, handlers, signal),
    maskedPreview: (id: string) =>
      get<MaskedPreview[]>(`/api/workflows/${id}/masked-preview`),
    audit: (id: string) =>
      get<{ items: AuditEvent[]; total: number; chain_valid: boolean }>(
        `/api/workflows/${id}/audit`,
      ),
    outputs: (id: string) => get<OutputPackage[]>(`/api/workflows/${id}/outputs`),
    // Not a URL: a plain link cannot carry the bearer token. See downloadArtifact.
    download: (id: string, artifactType = 'full_package', fallbackName = 'download') =>
      downloadArtifact(id, artifactType, fallbackName),
    // The results screen as one standalone HTML file, built on request rather
    // than stored — it always reflects the tax logic currently in force.
    downloadReport: (id: string, fallbackName = 'tax-report.html') =>
      downloadFrom(`/api/workflows/${id}/report.html`, fallbackName),
    // The calculation report: every line, worksheet, source document and
    // cross-check, built from the calculation graph on request.
    downloadCalculationReport: (id: string, format: 'pdf' | 'json') =>
      downloadFrom(
        `/api/workflows/${id}/graph/report.${format}`,
        `calculation-report.${format}`,
      ),
  },

  chat: {
    query: (payload: AssistantQuery) => post<AssistantAnswer>('/api/chat/query', payload),
    stream: (
      payload: AssistantQuery,
      handlers: AssistantStreamHandlers,
      signal?: AbortSignal,
    ) => streamAssistant(payload, handlers, signal),
    createSession: (selectedState?: string | null) =>
      post<ChatSession>(
        `/api/chat/sessions${selectedState ? `?selected_state=${encodeURIComponent(selectedState)}` : ''}`,
      ),
    sessions: () => get<ChatSession[]>('/api/chat/sessions'),
    conversation: (id: string) =>
      get<ChatConversation>(`/api/chat/sessions/${id}`),
    deleteConversation: (id: string) =>
      del<{ deleted: boolean }>(`/api/chat/sessions/${id}`),

    // --- Documents attached to one conversation ---------------------------
    attachments: (id: string) =>
      get<Attachment[]>(`/api/chat/sessions/${id}/attachments`),
    attach: (id: string, file: File) => {
      const body = new FormData();
      body.append('file', file);
      return request<Attachment>(`/api/chat/sessions/${id}/attachments`, {
        method: 'POST',
        body,
      });
    },
    detach: (id: string, documentId: string) =>
      del<{ deleted: boolean }>(
        `/api/chat/sessions/${id}/attachments/${documentId}`,
      ),

    // --- States -----------------------------------------------------------
    states: () => get<StateProfile[]>('/api/chat/states'),
    state: (code: string) => get<StateProfile>(`/api/chat/states/${code}`),
    stateUpdates: (code: string, refresh = false) =>
      get<StateUpdates>(
        `/api/chat/states/${code}/updates${refresh ? '?refresh=true' : ''}`,
      ),

    suggestions: (params: { state?: string | null; session?: string | null } = {}) => {
      const query = new URLSearchParams();
      if (params.state) query.set('state_code', params.state);
      if (params.session) query.set('session_id', params.session);
      const suffix = query.toString();
      return get<{ suggestions: string[] }>(
        `/api/chat/suggestions${suffix ? `?${suffix}` : ''}`,
      );
    },
  },

  depreciation: {
    rules: () => get<DepreciationRules>('/api/depreciation/rules'),
    calculate: (payload: DepreciationRequest) =>
      post<DepreciationResult>('/api/depreciation/calculate', payload),
    explain: (payload: DepreciationRequest) =>
      post<DepreciationExplanation>('/api/depreciation/explain', payload),
    exportCsv: (payload: DepreciationRequest) =>
      downloadPost('/api/depreciation/export/csv', payload, `depreciation-${payload.tax_year}.csv`),
    exportPdf: (payload: DepreciationRequest) =>
      downloadPost('/api/depreciation/export/pdf', payload, `depreciation-${payload.tax_year}.pdf`),
    /** Upload an asset list; each asset's life is predicted, every figure computed. */
    /** The year and jurisdiction come first: lives are decided for them, never assumed at upload. */
    importAdditions: (file: File, options: { taxYear: number; state: string | null; businessActivity: string }) => {
      const body = new FormData();
      body.append('file', file);
      body.append('tax_year', String(options.taxYear));
      if (options.state) body.append('state', options.state);
      if (options.businessActivity.trim()) body.append('business_activity', options.businessActivity.trim());
      return request<AdditionImport>('/api/depreciation/additions/import', { method: 'POST', body });
    },
    /** Lives decided again for a new year or jurisdiction - only for rows the user has not chosen. */
    additionLives: (payload: {
      tax_year: number; state: string | null; business_activity: string;
      assets: { description: string; life_in_file: string | null }[];
    }) => post<{ tax_year: number; state: string | null; message: string; predictions: LifePrediction[] }>(
      '/api/depreciation/additions/lives', payload,
    ),
    additionsReport: (payload: AdditionReportRequest) =>
      post<AdditionReport>('/api/depreciation/additions/report', payload),
    additionsTemplate: () => downloadFrom('/api/depreciation/additions/template', 'Asset-Additions-Template.xlsx'),
    exportAdditions: (payload: AdditionReportRequest) =>
      downloadPost('/api/depreciation/additions/export', payload, `CY-Addition-Dep-Summary-${payload.tax_year}.xlsx`),
  },

  review: {
    // `workflowId` matters more than it looks: the queue returns the oldest
    // 100 of every pending item in the database, so a caller that wants one
    // run's items and filters client-side gets none of them once the queue is
    // a few hundred deep. The endpoint has always supported the filter.
    queue: (status = 'pending', workflowId?: string) =>
      get<{ items: ReviewItem[]; total: number; pending: number }>(
        `/api/review/queue?status=${status}`
          + (workflowId ? `&workflow_id=${encodeURIComponent(workflowId)}` : ''),
      ),
    approve: (id: string, notes?: string) =>
      post<ReviewItem>(`/api/review/${id}/approve`, { notes: notes ?? null }),
    reject: (id: string, notes?: string) =>
      post<ReviewItem>(`/api/review/${id}/reject`, { notes: notes ?? null }),
    edit: (id: string, correctedValue: string, notes?: string) =>
      post<ReviewItem>(`/api/review/${id}/edit`, {
        corrected_value: correctedValue,
        notes: notes ?? null,
      }),
  },

  templates: {
    list: () => get<LearnedTemplate[]>('/api/templates'),
    pairs: () =>
      get<{ directory: string; pair_count: number; pairs: { pair: string; input_ext: string }[] }>(
        '/api/templates/pairs',
      ),
    learn: (maxPairs = 20) =>
      post<{
        pairs_found: number; pairs_processed: number; pairs_unreadable: number;
        templates_proposed: number; rules_inferred: number; notes: string[];
      }>('/api/templates/learn', { max_pairs: maxPairs }),
    approve: (id: string, notes?: string) =>
      post<LearnedTemplate>(`/api/templates/${id}/approve`, { notes: notes ?? null }),
    reject: (id: string, notes?: string) =>
      post<LearnedTemplate>(`/api/templates/${id}/reject`, { notes: notes ?? null }),
  },

  audit: {
    events: (params: { action?: string; severity?: string; limit?: number } = {}) => {
      const query = new URLSearchParams();
      if (params.action) query.set('action', params.action);
      if (params.severity) query.set('severity', params.severity);
      query.set('limit', String(params.limit ?? 200));
      return get<{ items: AuditEvent[]; total: number; chain_valid: boolean; broken_sequences: number[] }>(
        `/api/audit/events?${query}`,
      );
    },
    verify: () =>
      get<{ chain_valid: boolean; events_checked: number; broken_sequences: number[]; message: string }>(
        '/api/audit/verify',
      ),
    actions: () => get<Record<string, number>>('/api/audit/actions'),
  },

  settings: {
    get: () => get<AppSettings>('/api/settings'),
    health: () => get<Health>('/api/settings/health'),
    quota: () => get<Quota>('/api/settings/quota'),
  },

  auth: {
    login: async (username: string, password: string) => {
      const result = await post<Token>('/api/auth/login', { username, password });
      setToken(result.access_token);
      return result;
    },
    me: () => get<PrincipalInfo>('/api/auth/me'),
    logout: () => clearToken(),
  },
  reference: {
    calendar: () => get<CalendarRules>('/api/reference/calendar'),
    dashboard: () => get<DashboardConfig>('/api/reference/dashboard'),
    forms: () => get<FormsLibrary>('/api/reference/forms'),
    states: () => get<StateIntelListing>('/api/reference/states'),
    state: (code: string, year: number) =>
      get<StateIntelProfile>(`/api/reference/states/${encodeURIComponent(code)}?year=${year}`),
  },

  workspace: {
    clients: () => get<WorkspaceClient[]>('/api/workspace/clients'),
    createClient: (body: ClientInput) => post<WorkspaceClient>('/api/workspace/clients', body),
    updateClient: (id: string, body: ClientInput) => put<WorkspaceClient>(`/api/workspace/clients/${id}`, body),
    deleteClient: (id: string) => del<void>(`/api/workspace/clients/${id}`),
    deadlines: () => get<CustomDeadline[]>('/api/workspace/deadlines'),
    createDeadline: (body: CustomDeadlineInput) => post<CustomDeadline>('/api/workspace/deadlines', body),
    updateDeadline: (id: string, body: CustomDeadlineInput) =>
      put<CustomDeadline>(`/api/workspace/deadlines/${id}`, body),
    deleteDeadline: (id: string) => del<void>(`/api/workspace/deadlines/${id}`),
  },

  updates: {
    feed: (params: { source?: string; topic?: string; start?: string; end?: string; limit?: number } = {}) => {
      const query = new URLSearchParams();
      for (const [key, value] of Object.entries(params)) if (value) query.set(key, String(value));
      return get<NewsFeed>(`/api/updates${query.toString() ? `?${query}` : ''}`);
    },
    refresh: () => post<{ accepted: boolean }>('/api/updates/refresh'),
    bookmarks: () => get<NewsBookmark[]>('/api/updates/bookmarks'),
    bookmark: (itemId: string) => post<NewsBookmark>('/api/updates/bookmarks', { item_id: itemId }),
    removeBookmark: (id: string) => del<void>(`/api/updates/bookmarks/${id}`),
    summary: (itemId: string) => post<NewsSummary>(`/api/updates/${encodeURIComponent(itemId)}/summary`),
  },
};
