"""The tax & audit assistant: one question in, one checked answer out.

The flow, in order, and why each step is where it is:

1. **Mask, on request.** A question that starts with ``/mask`` has personal
   details replaced with surrogates before anything is built from it; a
   masking failure stops the question. Any other question is sent as typed,
   and the egress guard still blocks identifiers in it (``masking``).
2. **Route, then resolve the jurisdiction.** A small fast call (``router``)
   says what kind of question this is - which picks the answer policy - and
   whether it depends on state law. ``selected_state`` (already validated
   against the registry) applies only to a state-specific question; a state
   the question *names* always applies. Out-of-scope questions and ones that
   need a single clarifying question are answered here, with no grounded
   call. Whether the user switched states since the last turn is decided
   from the stored conversation, not guessed.
3. **Read official sources for calculations.** Single-year scenarios first
    discover primary documents through grounded search, then read the public
    HTML/PDF text with jurisdiction and redirect checks. The answer receives
    scrubbed source text, not model-written research notes. Missing material
    stops the calculation; existing unverified cached calculations are not reused.
4. **Answer, streamed.** One Gemini call with Google Search grounding writes
   the answer in markdown; each piece is passed to the reader as it arrives
   (``delta`` events), minus the hidden META line and with ``/mask``
   surrogates swapped back. The call goes through ``GeminiService`` and its
   egress guard. (Why one call: ``gemini_client``.)
5. **Validate at the end.** Grounding metadata arrives with the last chunk,
   so grounding, tax year and state consistency are checked when the stream
   ends. A failing draft is withdrawn from the screen (a ``replace`` event)
   and regenerated once with the failures spelled out; a second failure shows
   a safe fallback - never the failed draft.
6. **Cite, store, display.** Source markers are placed from grounding
   supports only, never inside a hypothetical example; the payload is stored
   as sent (masked under ``/mask``) and a restored copy is the ``final`` event.

There is no offline answer. With Gemini unconfigured the assistant says it is
unavailable: a stubbed tax answer would be a confident answer from nowhere.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, AuditLogger
from app.core.config import Settings, get_settings
from app.core.errors import EgressBlockedError, LlmError
from app.core.logging import get_logger
from app.models.database_models import (
    AssistantAnswerRecord,
    ChatMessage,
    ChatSession,
    Citation,
)
from app.services.assistant import (
    answer_text,
    formatter,
    prompt_builder,
    state_registry,
    validators,
)
from app.services.assistant.answer_cache import (
    AnswerCache,
    CacheKey,
    cacheable,
    normalise,
)
from app.services.assistant.answer_schema import Scope
from app.services.assistant.citations import (
    Resolver,
    annotate,
    build_citations,
    http_redirect_resolver,
    keep_known_markers,
    renumber_text,
)
from app.services.assistant.gemini_client import GroundedAnswerClient
from app.services.assistant.masking import (
    MaskedQuestion,
    QuestionMasker,
    StreamRestorer,
    parse_mask_command,
    restore_deep,
)
from app.services.assistant.official_sources import SourceVerifier
from app.services.assistant.prompt_builder import JurisdictionContext
from app.services.assistant.router import QuestionRouter, Route
from app.services.chat_attachment_service import ChatAttachmentService
from app.services.gemini_service import GeminiService, Grounding, StreamEvent
from app.services.llm_egress_guard import redact_blocking_patterns
from app.services.llm_meter import DbLlmMeter, MeterScope

logger = get_logger(__name__)

#: Two attempts: the first, and one regeneration told what failed.
MAX_ATTEMPTS = 2

#: One further attempt allowed when an attempt's *only* failure was that the
#: model skipped Google Search. That is a coin toss rather than a content
#: error - the same prompt searches on one run and not the next - so spending
#: the single content regeneration on it turned well-grounded questions into
#: fallbacks. Content failures (state, tax year) still get exactly one
#: regeneration.
GROUNDING_RETRIES = 1

#: Payload keys that are never un-masked: URLs and Google's own HTML.
_NO_RESTORE = frozenset({"citations", "official_links", "search_suggestions_html"})
#: Internal bookkeeping in a cached payload, never shown.
_INTERNAL = ("model_name",)

_DEFAULT_RESOLVER: Any = object()

#: One answer cache per process, shared by every request (``answer_cache``).
_SHARED_CACHE: AnswerCache | None = None


def shared_cache(settings: Settings) -> AnswerCache:
    global _SHARED_CACHE
    if _SHARED_CACHE is None:
        _SHARED_CACHE = AnswerCache(
            max_entries=settings.assistant_cache_max_entries,
            ttl_seconds=settings.assistant_cache_ttl_seconds,
        )
    return _SHARED_CACHE

#: The egress guard blocked an unmasked question: say what to do about it.
_BLOCKED_MESSAGE = (
    "Your question contains what looks like a Social Security, EIN, account "
    "or card number, or an email address, so I didn't send it. "
    "Remove it, or start your message with /mask to have personal details "
    "replaced before anything is sent."
)
_BLOCKED_MASKED_MESSAGE = (
    "I couldn't send that question safely, so I didn't send it. Try asking "
    "without names, numbers or addresses."
)


class AssistantService:
    def __init__(
        self,
        session: Session,
        *,
        gemini: GeminiService | None = None,
        audit: AuditLogger | None = None,
        settings: Settings | None = None,
        resolver: Resolver | None | Any = _DEFAULT_RESOLVER,
        today: Callable[[], date] | None = None,
        cache: AnswerCache | None = None,
        source_verifier: SourceVerifier | None = None,
    ) -> None:
        self._session = session
        self._audit = audit
        self._settings = settings or get_settings()
        self._client = GroundedAnswerClient(
            gemini or GeminiService(audit=audit, meter=DbLlmMeter(session)),
            self._settings,
        )
        if resolver is _DEFAULT_RESOLVER:
            resolver = (
                http_redirect_resolver(self._settings)
                if self._settings.assistant_resolve_source_urls
                else None
            )
        self._resolver: Resolver | None = resolver
        self._today = today or (lambda: datetime.now(UTC).date())
        self._cache = cache if cache is not None else shared_cache(self._settings)
        self._masker = QuestionMasker(session, audit=audit)
        self._router = QuestionRouter(self._client.gemini, self._settings)
        self._source_verifier = source_verifier or SourceVerifier(self._client.gemini, self._settings)
        self._attachments = ChatAttachmentService(session, audit=audit, settings=self._settings)

    # =====================================================================
    # Public
    # =====================================================================

    def answer(self, **kwargs: Any) -> dict[str, Any]:
        """Answer in one call. Same arguments as ``answer_events``."""
        final: dict[str, Any] | None = None
        for event in self.answer_events(**kwargs):
            if event["type"] == "final":
                final = event["answer"]
            elif event["type"] == "error":
                raise RuntimeError(event["message"])
        assert final is not None
        return final

    def answer_events(
        self,
        *,
        question: str,
        session_id: str | None = None,
        selected_state: str | None = None,
        tax_year: int | None = None,
        selected_tax_year: int | None = None,
        user_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield ``step``, ``delta`` and ``replace`` events, then one ``final`` (or ``error``).

        ``delta`` carries answer text to append; ``replace`` says the text
        shown so far was withdrawn (it failed a check, or the stream broke).
        """
        started = time.monotonic()
        today = self._today()
        yield _step("understanding", "Understanding your question…")

        mask_requested, question = parse_mask_command(question)
        try:
            masked = (
                self._masker.mask(question)
                if mask_requested
                else MaskedQuestion.unmasked(question)
            )
        # SECURITY: any masking failure stops the question; nothing is sent.
        except Exception:  # noqa: BLE001
            yield {
                "type": "error",
                "message": (
                    "I couldn't process that question safely, so I stopped "
                    "rather than send it anywhere."
                ),
            }
            return

        chat_session = self._resolve_session(masked.text, selected_state, session_id, user_id)
        has_history = (chat_session.message_count or 0) > 0
        history = self._history(chat_session)
        blocked = False
        route = Route()
        if self._client.available:
            try:
                route = self._router.route(
                    question=masked.text,
                    selected_state=selected_state,
                    history=history,
                    meter_scope=MeterScope(chat_session_id=chat_session.id, stage="chat_router"),
                )
            except EgressBlockedError:
                blocked = True
        context = prompt_builder.resolve_jurisdiction(
            selected_state=selected_state,
            question=question,
            previous_selected=chat_session.state_code if has_history else None,
            has_history=has_history,
            state_specific=route.state_specific,
            federal_too=route.federal_too,
        )
        if context.state_changed:
            yield _step("jurisdiction", formatter.state_change_notice(context))
        if masked.was_masked:
            yield _step(
                "masking",
                "Personal details in your question were replaced with "
                "placeholders before anything was sent.",
            )

        # Decided before the model runs, like the jurisdiction: a year the
        # question names wins, then the conversation's, then the one selected
        # in the app, then ``Settings.default_tax_year``.
        year_context = prompt_builder.resolve_tax_year(
            question=question,
            today=today,
            explicit=tax_year,
            carried=chat_session.tax_year if has_history else None,
            selected=selected_tax_year,
            default=self._settings.default_tax_year,
        )
        year = year_context.year
        attachment_text = self._attachments.masked_text_for(
            chat_session.id, max_chars=self._settings.assistant_max_attachment_chars
        )
        scope = MeterScope(chat_session_id=chat_session.id, stage="chat")

        attempts_log: list[list[str]] = []
        reply_model = ""
        source_count = 0
        first_token_ms: int | None = None
        payload: dict[str, Any]

        # A general, first-turn question asked again today is replayed. Never
        # one asked with /mask, with history or with attachments: its answer
        # depends on more than the key holds (``answer_cache``).
        cache_key: CacheKey | None = None
        if not (masked.was_masked or mask_requested or has_history or attachment_text):
            cache_key = CacheKey(
                question=normalise(masked.text),
                required=context.required,
                selection_ignored=context.selection_ignored,
                federal_too=context.federal_too,
                tax_year=year,
                answer_type=route.answer_type,
                model=self._settings.assistant_model,
                day=today.isoformat(),
            )
        cached = self._cache.get(cache_key) if cache_key is not None else None
        needs_source_text = route.answer_type == "scenario" and year is not None
        source_text_read = False
        if cached is not None:
            source_text_read = bool(cached.pop("official_source_text_read", False))
            if needs_source_text and not source_text_read:
                cached = None

        if not self._client.available:
            payload = formatter.unavailable(
                "The assistant isn't available: it needs a configured Gemini API "
                "key to search official sources, and it does not answer tax "
                "questions without them.",
                context=context,
            )
        elif blocked:
            payload = formatter.unavailable(
                _BLOCKED_MESSAGE if not mask_requested else _BLOCKED_MASKED_MESSAGE,
                context=context,
            )
        elif route.scope in (Scope.NON_TAX.value, Scope.NON_US_TAX.value):
            # Fixed text, no search: there is nothing to ground.
            payload = formatter.out_of_scope(Scope(route.scope), context=context)
        elif route.answer_type == "clarify":
            # One question back, no search: it states no tax fact.
            payload = formatter.clarify(route.clarifying_question, context=context)
        elif cached is not None:
            yield _step("cache", "This question was answered earlier today; showing that answer.")
            reply_model = str(cached.pop("model_name", "") or "")
            payload = cached
            payload["from_cache"] = True
        else:
            correction: list[str] | None = None
            payload = {}
            budget = MAX_ATTEMPTS
            official_source_text = ""
            if needs_source_text and year is not None:
                yield _step("searching", "Finding and reading current official sources...")
                research = prompt_builder.build_source_research(
                    question=masked.text, context=context, today=today,
                    tax_year=year_context, history=history,
                )
                try:
                    evidence = self._source_verifier.prepare(
                        research, year=year, question=masked.text,
                        meter_scope=MeterScope(chat_session_id=chat_session.id, stage="chat_source_research"),
                    )
                except EgressBlockedError:
                    payload = formatter.unavailable(
                        _BLOCKED_MESSAGE if not mask_requested else _BLOCKED_MASKED_MESSAGE, context=context,
                    )
                    budget = 0
                except LlmError:
                    payload = formatter.fallback(["official_sources_unavailable"], context=context)
                    budget = 0
                else:
                    if evidence.pages:
                        official_source_text = evidence.prompt_text()
                        source_text_read = True
                    else:
                        payload = formatter.fallback(["official_sources_unavailable"], context=context)
                        budget = 0
            grounding_retries = GROUNDING_RETRIES
            attempt = 0
            while attempt < budget:
                attempt += 1
                built = prompt_builder.build(
                    question=masked.text,
                    context=context,
                    today=today,
                    tax_year=year_context,
                    history=history,
                    attachment_text=attachment_text,
                    official_source_text=official_source_text,
                    correction=correction,
                    answer_type=route.answer_type,
                )
                yield _step("searching", _searching_message(context, attempt))
                meta_filter = answer_text.MetaFilter()
                restorer = StreamRestorer(masked.restore)
                shown = False
                done: StreamEvent | None = None
                try:
                    for event in self._client.stream_answer(
                        system_instruction=built.system,
                        prompt=built.prompt,
                        meter_scope=scope,
                    ):
                        if event.done:
                            done = event
                            piece = restorer.feed(meta_filter.flush()) + restorer.flush()
                        else:
                            piece = restorer.feed(meta_filter.feed(event.text))
                        if not piece:
                            continue
                        if not shown:
                            shown = True
                            if first_token_ms is None:
                                first_token_ms = int((time.monotonic() - started) * 1000)
                            yield _step("writing", "Writing the answer…")
                        yield {"type": "delta", "text": piece}
                    if done is None:
                        raise LlmError("The answer stream ended early.", details={"retryable": True})
                except EgressBlockedError:
                    payload = formatter.unavailable(
                        _BLOCKED_MESSAGE if not mask_requested else _BLOCKED_MASKED_MESSAGE,
                        context=context,
                    )
                    break
                except LlmError as exc:
                    if shown:
                        yield _withdrawn("The connection to the model dropped mid-answer.")
                    payload = formatter.unavailable(_provider_message(exc), context=context)
                    break

                reply_model = done.model_name
                source_count = len(done.grounding.sources)
                yield _step("checking", _checking_message(source_count))

                meta, body = answer_text.split_meta(done.text)
                body, follow_ups = answer_text.split_follow_ups(answer_text.clean(body))
                answer_scope = meta.scope or Scope.US_TAX.value
                year_text = answer_text.tax_year(meta, body, today=today)
                report = validators.validate(
                    body,
                    scope=answer_scope,
                    grounding=done.grounding,
                    context=context,
                    meta=meta,
                    year=year_context,
                )
                attempts_log.append(report.codes)

                if report.ok:
                    payload = self._answered(
                        body,
                        grounding=done.grounding,
                        scope=answer_scope,
                        answer_type=route.answer_type,
                        context=context,
                        tax_year=year_text,
                        tax_year_assumed=meta.assumed or year_context.assumed,
                        tax_year_missing=validators.missing_tax_year(body, year_text),
                        tax_year_requested=year,
                        tax_year_fallback=validators.fallback_year(meta, year_context),
                        follow_ups=follow_ups,
                        sensitive_identifier=masked.sensitive_identifier,
                        question=masked.text,
                    )
                    break

                if report.codes == ["ungrounded"] and grounding_retries > 0:
                    grounding_retries -= 1
                    budget += 1
                if attempt < budget:
                    if shown:
                        yield _withdrawn(
                            "That draft didn't pass the checks ("
                            + ", ".join(report.codes)
                            + "), so I've withdrawn it and I'm rewriting it."
                        )
                    else:
                        yield _step(
                            "retrying",
                            "That draft didn't pass the checks ("
                            + ", ".join(report.codes)
                            + "), so I'm regenerating it.",
                        )
                    correction = report.messages()
                    continue

                if shown:
                    yield _withdrawn("That draft didn't pass the checks twice.")
                payload = formatter.fallback(report.codes, context=context)
                if self._audit is not None:
                    self._audit.record(
                        AuditAction.CHAT_REFUSED,
                        entity_type="chat_session",
                        entity_id=chat_session.id,
                        payload={"issues": attempts_log, "states": list(context.required)},
                    )

        if cache_key is not None and cached is None and cacheable(payload):
            self._cache.put(cache_key, {
                **payload, "model_name": reply_model, "official_source_text_read": source_text_read,
            })

        latency_ms = int((time.monotonic() - started) * 1000)
        message_id = self._persist(
            chat_session,
            masked_question=masked.text,
            was_masked=masked.was_masked,
            context=context,
            year=year,
            carry_year=year_context.carries,
            payload=payload,
            attempts_log=attempts_log,
            model=reply_model,
            latency_ms=latency_ms,
        )

        _log(
            selected_state=context.selected,
            required_states=list(context.required),
            tax_year=payload.get("tax_year") or year,
            answer_type=payload.get("answer_type"),
            route=route.source,
            jurisdiction=route.jurisdiction,
            status=payload.get("status"),
            sources=[c.get("domain") for c in payload.get("citations", [])],
            source_count=source_count,
            validation=attempts_log,
            first_token_ms=first_token_ms,
            latency_ms=latency_ms,
            model=reply_model,
            masked=masked.was_masked,
            from_cache=cached is not None,
        )

        shown_payload = restore_deep(payload, masked.restore, skip=_NO_RESTORE)
        for key in _INTERNAL:
            shown_payload.pop(key, None)
        shown_payload.update(
            message_id=message_id,
            session_id=chat_session.id,
            was_masked=masked.was_masked,
            model=reply_model,
            latency_ms=latency_ms,
            first_token_ms=first_token_ms,
            attempts=len(attempts_log),
        )
        yield {"type": "final", "answer": shown_payload}

    def _answered(
        self,
        body: str,
        *,
        grounding: Grounding,
        scope: str,
        answer_type: str,
        context: JurisdictionContext,
        tax_year: str,
        tax_year_assumed: bool,
        tax_year_missing: bool,
        tax_year_requested: int | None,
        tax_year_fallback: int | None,
        follow_ups: list[str],
        sensitive_identifier: bool,
        question: str,
    ) -> dict[str, Any]:
        """Place grounded source markers in a checked answer and build its payload.

        A hypothetical example gets no marker: its numbers are invented, and
        a source number next to them would claim a source said them. A
        sentence stating a figure that no source passage covers is flagged
        rather than shown as if sourced.
        """
        annotated = annotate(body, grounding, skip=answer_text.example_ranges(body))
        citations, renumber, _ = build_citations(
            grounding, {"answer": annotated}, resolver=self._resolver
        )
        markdown, dropped = keep_known_markers(renumber_text(annotated, renumber), len(citations))
        if dropped:
            # By construction this never happens; if it does, a citation was
            # about to point at a source that is not listed.
            logger.warning("assistant.citations dropped %d marker(s) with no listed source", dropped)
        markdown, unsourced = answer_text.flag_unsourced_figures(markdown, question=question)
        return formatter.answered(
            markdown,
            unsourced_figures=unsourced,
            tax_year_missing=tax_year_missing,
            scope=scope,
            answer_type=answer_type,
            context=context,
            tax_year=tax_year,
            tax_year_assumed=tax_year_assumed,
            tax_year_requested=tax_year_requested,
            tax_year_fallback=tax_year_fallback,
            follow_ups=follow_ups,
            citations=citations,
            search_queries=grounding.queries,
            search_suggestions_html=grounding.search_suggestions_html,
            sensitive_identifier=sensitive_identifier,
        )

    # -- conversations ----------------------------------------------------

    def sessions(self, *, user_id: str | None = None, limit: int = 50) -> list[ChatSession]:
        stmt = (
            select(ChatSession)
            .order_by(ChatSession.last_message_at.desc().nullslast())
            .limit(limit)
        )
        if user_id:
            stmt = stmt.where(ChatSession.user_id == user_id)
        return list(self._session.execute(stmt).scalars())

    def turns(self, session_id: str) -> list[dict[str, Any]]:
        """Stored (question, answer payload) pairs, oldest first. Masked."""
        messages = self._session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        ).scalars()
        turns: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "user":
                turns.append({"id": message.id, "question": message.content, "answer": None})
                continue
            if not turns:
                continue
            record = self._session.execute(
                select(AssistantAnswerRecord).where(
                    AssistantAnswerRecord.message_id == message.id
                )
            ).scalar_one_or_none()
            if record is None:
                # A turn stored by the previous assistant, before structured
                # answers existed: show what it said, honestly labelled.
                payload = formatter.unavailable(
                    message.short_answer or message.content,
                    context=_empty_context(message.state_code),
                )
                payload["status"] = "legacy"
            else:
                payload = dict(record.payload)
            payload.update(message_id=message.id, session_id=session_id, was_masked=message.was_masked)
            turns[-1]["answer"] = payload
        return turns

    def delete_session(self, session_id: str) -> bool:
        row = self._session.get(ChatSession, session_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    # =====================================================================
    # Internals
    # =====================================================================

    def _resolve_session(
        self,
        question: str,
        selected_state: str | None,
        session_id: str | None,
        user_id: str | None,
    ) -> ChatSession:
        if session_id:
            existing = self._session.get(ChatSession, session_id)
            if existing is not None:
                return existing
        title = question.strip()
        chat_session = ChatSession(
            user_id=user_id,
            # Shown only to the authenticated user whose conversation it is.
            title=(title[:60] + "…") if len(title) > 60 else (title or "New conversation"),
            jurisdiction="state" if selected_state else "federal",
            state_code=selected_state,
        )
        self._session.add(chat_session)
        self._session.flush()
        return chat_session

    def _history(self, chat_session: ChatSession) -> list[tuple[str, str]]:
        """Recent turns for follow-ups.

        SECURITY: reads stored rows, which hold the *masked* question and the
        masked quick answer - safe to send as they are.
        """
        rows = (
            self._session.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == chat_session.id)
                .order_by(ChatMessage.created_at.desc())
                .limit(self._settings.assistant_history_turns * 2)
            )
            .scalars()
            .all()
        )
        turns = [(row.role, (row.short_answer or row.content or "").strip()) for row in reversed(rows)]
        # SECURITY: an assistant turn quotes public pages, which carry agency
        # phone numbers and emails the egress guard cannot tell from client
        # data (CLAUDE.md traps 5 and 36), so it gets the one-way scrub. A
        # user turn never does: that is the user's own text.
        return [
            (role, redact_blocking_patterns(text) if role == "assistant" else text)
            for role, text in turns
            if text
        ]

    def _persist(
        self,
        chat_session: ChatSession,
        *,
        masked_question: str,
        was_masked: bool,
        context: JurisdictionContext,
        year: int | None,
        carry_year: bool,
        payload: dict[str, Any],
        attempts_log: list[list[str]],
        model: str,
        latency_ms: int,
    ) -> str:
        level = str(payload.get("jurisdiction_level") or "federal")
        answer_year = _single_year(str(payload.get("tax_year") or "")) or year

        # SECURITY: the masked question is what is stored.
        self._session.add(
            ChatMessage(
                session_id=chat_session.id,
                role="user",
                content=masked_question,
                was_masked=was_masked,
                jurisdiction=level[:16],
                state_code=context.selected,
                tax_year=year,
            )
        )
        quick = str(payload.get("quick_answer") or "")
        message = ChatMessage(
            session_id=chat_session.id,
            role="assistant",
            content=quick,
            short_answer=quick,
            explanation=str(payload.get("why") or ""),
            confidence_level=str(payload.get("confidence") or ""),
            jurisdiction=level[:16],
            state_code=context.selected,
            tax_year=answer_year,
            model_name=model[:96],
            latency_ms=latency_ms,
            retrieval_hit_count=len(payload.get("citations") or []),
            was_masked=was_masked,
        )
        self._session.add(message)
        self._session.flush()

        self._session.add(
            AssistantAnswerRecord(
                message_id=message.id,
                status=str(payload.get("status")),
                category=str(payload.get("category") or "")[:48],
                attempts=max(1, len(attempts_log)),
                payload=payload,
                validation=attempts_log,
            )
        )
        for citation in payload.get("citations") or []:
            self._session.add(
                Citation(
                    message_id=message.id,
                    display_index=int(citation["index"]),
                    title=str(citation["title"])[:512],
                    source_url=str(citation["url"])[:1024],
                    authority_level=str(citation["authority"])[:32],
                    quoted_text=str(citation.get("supporting_text") or ""),
                )
            )

        chat_session.message_count = (chat_session.message_count or 0) + 2
        chat_session.last_message_at = datetime.now(UTC)
        # The conversation carries the selected state and year into the next
        # turn; a change of state on the next turn is detected against these.
        chat_session.state_code = context.selected
        chat_session.jurisdiction = "state" if context.selected else "federal"
        # Only a year somebody asked for carries into the next turn. The
        # selected or default year is re-read every turn, so changing the
        # year in the app takes effect on the next question.
        chat_session.tax_year = year if carry_year else None
        self._session.flush()
        return message.id


# ---------------------------------------------------------------------------


def _step(phase: str, message: str) -> dict[str, Any]:
    return {"type": "step", "phase": phase, "message": message}


def _withdrawn(message: str) -> dict[str, Any]:
    """The text streamed so far is withdrawn from the screen."""
    return {"type": "replace", "message": message}


def _searching_message(context: JurisdictionContext, attempt: int) -> str:
    names = [state_registry.require(code).name for code in context.required]
    where = f" for {' and '.join(names)}" if names else ""
    if attempt > 1:
        return f"Searching and reading sources again{where}…"
    return f"Searching and reading sources{where}…"


def _checking_message(source_count: int) -> str:
    if not source_count:
        return "Checking the answer…"
    return (
        f"Checking the answer against {source_count} source"
        f"{'' if source_count == 1 else 's'}…"
    )


def _provider_message(exc: LlmError) -> str:
    details = getattr(exc, "details", None) or {}
    if details.get("quota_scope") == "daily":
        return (
            "The assistant has used up today's model quota, so it can't look "
            "this up right now. Please try again tomorrow."
        )
    if details.get("retryable"):
        return (
            "The model provider is busy right now and didn't respond after "
            "several attempts. Please try again in a minute."
        )
    return (
        "The assistant couldn't reach the model provider (the request was "
        "rejected). An administrator should check the API key and the "
        "configured ASSISTANT_MODEL."
    )


def _single_year(text: str) -> int | None:
    import re

    years = set(re.findall(r"(?<!\d)(?:19|20)\d\d(?!\d)", text))
    return int(years.pop()) if len(years) == 1 else None


def _empty_context(selected: str | None) -> JurisdictionContext:
    return JurisdictionContext(
        selected=selected,
        named=(),
        required=(selected,) if selected else (),
        allowed=frozenset({selected}) if selected else None,
    )


def _log(**fields: Any) -> None:
    """One structured line per answer. SECURITY: no question or answer text.

    Sources are logged as domains only; the redaction filter is a backstop,
    not the reason this is safe.
    """
    fields["sources"] = sorted(
        {urlparse(f"https://{d}").hostname or "" for d in fields.get("sources") or [] if d}
    )
    logger.info("assistant.answer %s", json.dumps(fields, default=str, sort_keys=True))
