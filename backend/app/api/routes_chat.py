"""The tax & audit assistant: asking, conversations, attachments, states.

Routes stay thin. Answering lives in ``services/assistant``; this module only
validates input (``selected_state`` against the registry's allow-list happens
in ``AssistantQueryRequest``), wires dependencies, and serialises.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import StreamingResponse

from app.api.deps import (
    AuditDep,
    DbSession,
    GeminiDep,
    SettingsDep,
    rate_limit,
    role_required,
)
from app.core.config import Role
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.security import Principal
from app.models.database_models import ChatSession
from app.schemas.api import (
    AgencyOut,
    AssistantAnswerOut,
    AssistantQueryRequest,
    AssistantTurnOut,
    AttachmentOut,
    ChatConversationOut,
    ChatSessionOut,
    StateProfileOut,
    StateUpdatesOut,
    SuggestionsOut,
)
from app.services.assistant import state_registry
from app.services.assistant.assistant_service import AssistantService
from app.services.assistant.state_registry import Jurisdiction
from app.services.assistant.suggestions import suggestions_for
from app.services.chat_attachment_service import ChatAttachmentService
from app.services.state_updates_service import StateUpdatesService

logger = get_logger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ===========================================================================
# Asking
# ===========================================================================


@router.post("/query", response_model=AssistantAnswerOut, dependencies=[rate_limit("chat")])
def query(
    payload: AssistantQueryRequest,
    session: DbSession,
    audit: AuditDep,
    gemini: GeminiDep,
    settings: SettingsDep,
    principal: Principal = role_required(Role.READONLY),
) -> AssistantAnswerOut:
    """Answer one question, grounded in Google Search, in the fixed layout.

    SECURITY: the question is masked inside the service before it is used
    for anything - the prompt, storage, or logs.
    """
    service = AssistantService(session, gemini=gemini, audit=audit, settings=settings)
    answer = service.answer(
        question=payload.question,
        session_id=payload.session_id,
        selected_state=payload.selected_state,
        tax_year=payload.tax_year,
        selected_tax_year=payload.selected_tax_year,
        user_id=principal.user_id,
    )
    return AssistantAnswerOut.model_validate(answer)


@router.post("/stream", dependencies=[rate_limit("chat")])
def query_stream(
    payload: AssistantQueryRequest,
    session: DbSession,
    audit: AuditDep,
    gemini: GeminiDep,
    settings: SettingsDep,
    principal: Principal = role_required(Role.READONLY),
) -> StreamingResponse:
    """The same answer as ``/query``, streamed as Server-Sent Events.

    Emits ``step`` records as each stage really starts, ``delta`` records
    carrying answer text as the model writes it, a ``replace`` record if the
    text shown so far is withdrawn (it failed a check at the end of the
    stream, or the stream broke), then one ``final`` record holding the
    checked answer with its sources (or one ``error``).
    """
    service = AssistantService(session, gemini=gemini, audit=audit, settings=settings)

    def event_stream():
        try:
            for event in service.answer_events(
                question=payload.question,
                session_id=payload.session_id,
                selected_state=payload.selected_state,
                tax_year=payload.tax_year,
                selected_tax_year=payload.selected_tax_year,
                user_id=principal.user_id,
            ):
                if event["type"] == "final":
                    event = {
                        "type": "final",
                        "answer": AssistantAnswerOut.model_validate(event["answer"]).model_dump(),
                    }
                yield _sse(event)
            # The answer is written inside the generator, so commit here: by
            # the time the dependency closes the session the body is sent.
            session.commit()
        except Exception:
            logger.exception("Answering a question failed")
            session.rollback()
            yield _sse(
                {
                    "type": "error",
                    "message": (
                        "Something went wrong while answering. Nothing was sent "
                        "anywhere it should not have been. Please try again."
                    ),
                }
            )
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Without this a buffering proxy holds the stream until the end.
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


# ===========================================================================
# Conversations
# ===========================================================================


@router.get("/sessions", response_model=list[ChatSessionOut])
def list_sessions(
    session: DbSession,
    principal: Principal = role_required(Role.READONLY),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ChatSessionOut]:
    service = AssistantService(session)
    return [
        ChatSessionOut.model_validate(row)
        for row in service.sessions(user_id=principal.user_id, limit=limit)
    ]


@router.get("/sessions/{session_id}", response_model=ChatConversationOut)
def get_conversation(
    session_id: str,
    session: DbSession,
    principal: Principal = role_required(Role.READONLY),
) -> ChatConversationOut:
    row = session.get(ChatSession, session_id)
    if row is None:
        raise NotFoundError("No such conversation.")
    turns = AssistantService(session).turns(session_id)
    return ChatConversationOut(
        session=ChatSessionOut.model_validate(row),
        turns=[AssistantTurnOut.model_validate(turn) for turn in turns],
        attachments=[
            AttachmentOut.model_validate(item, from_attributes=True)
            for item in ChatAttachmentService(session).list_for(session_id)
        ],
    )


@router.delete("/sessions/{session_id}")
def delete_conversation(
    session_id: str,
    session: DbSession,
    principal: Principal = role_required(Role.PREPARER),
) -> dict[str, bool]:
    if not AssistantService(session).delete_session(session_id):
        raise NotFoundError("No such conversation.")
    return {"deleted": True}


# ===========================================================================
# Attachments
# ===========================================================================


@router.post(
    "/sessions/{session_id}/attachments",
    response_model=AttachmentOut,
    dependencies=[rate_limit("upload")],
)
def attach_document(
    session_id: str,
    session: DbSession,
    audit: AuditDep,
    file: UploadFile = File(...),
    principal: Principal = role_required(Role.PREPARER),
) -> AttachmentOut:
    """Attach a document to a conversation so questions can be asked of it.

    SECURITY: the file is encrypted at rest, its text is tokenized before it
    is stored, and only that masked text ever reaches a prompt - and only in
    this conversation. See ``chat_attachment_service``.
    """
    if not file.filename:
        raise ValidationError("That upload had no filename.")
    summary = ChatAttachmentService(session, audit=audit).attach(
        session_id=session_id,
        filename=file.filename,
        stream=file.file,
        content_type=file.content_type or "application/octet-stream",
        actor_id=principal.user_id,
    )
    return AttachmentOut.model_validate(summary, from_attributes=True)


@router.post("/sessions", response_model=ChatSessionOut)
def create_session(
    session: DbSession,
    selected_state: str | None = Query(default=None, max_length=8),
    principal: Principal = role_required(Role.PREPARER),
) -> ChatSessionOut:
    """An empty conversation, so a document can be attached before asking."""
    state = state_registry.get(selected_state) if selected_state else None
    if selected_state and state is None:
        raise ValidationError("selected_state must be a US state, DC or PR.")
    row = ChatSession(
        user_id=principal.user_id,
        title="New conversation",
        jurisdiction="state" if state else "federal",
        state_code=state.code if state else None,
    )
    session.add(row)
    session.flush()
    return ChatSessionOut.model_validate(row)


@router.get("/sessions/{session_id}/attachments", response_model=list[AttachmentOut])
def list_attachments(
    session_id: str,
    session: DbSession,
    principal: Principal = role_required(Role.READONLY),
) -> list[AttachmentOut]:
    return [
        AttachmentOut.model_validate(item, from_attributes=True)
        for item in ChatAttachmentService(session).list_for(session_id)
    ]


@router.delete("/sessions/{session_id}/attachments/{document_id}")
def remove_attachment(
    session_id: str,
    document_id: str,
    session: DbSession,
    audit: AuditDep,
    principal: Principal = role_required(Role.PREPARER),
) -> dict[str, bool]:
    if not ChatAttachmentService(session, audit=audit).remove(
        session_id=session_id, document_id=document_id
    ):
        raise NotFoundError("That document is not attached to this conversation.")
    return {"deleted": True}


# ===========================================================================
# States
# ===========================================================================


@router.get("/states", response_model=list[StateProfileOut])
def list_states(principal: Principal = role_required(Role.READONLY)) -> list[StateProfileOut]:
    """Every jurisdiction a question may be asked about. Feeds map and panel."""
    return [_state_out(state) for state in state_registry.JURISDICTIONS]


@router.get("/states/{state_code}", response_model=StateProfileOut)
def get_state(
    state_code: str, principal: Principal = role_required(Role.READONLY)
) -> StateProfileOut:
    state = state_registry.get(state_code)
    if state is None:
        raise NotFoundError(f"{state_code} is not a state this app covers.")
    return _state_out(state)


@router.get("/states/{state_code}/updates", response_model=StateUpdatesOut)
def state_updates(
    state_code: str,
    settings: SettingsDep,
    refresh: bool = Query(default=False),
    principal: Principal = role_required(Role.READONLY),
) -> StateUpdatesOut:
    """What the state's revenue agency has published recently.

    With ``STATE_UPDATES_ENABLED=false`` this returns the agency's links and
    an explanation instead - "nothing published" and "we could not look" are
    different facts.
    """
    state = state_registry.get(state_code)
    if state is None:
        raise NotFoundError(f"{state_code} is not a state this app covers.")
    if not settings.state_updates_enabled:
        return StateUpdatesOut(
            state_code=state.code,
            state_name=state.name,
            agency=state.agency.name,
            agency_url=state.agency.url,
            updates_url=state.updates_url,
            items=[],
            error=(
                "Live updates are switched off on this deployment. "
                f"{state.agency.name} publishes them at the link below."
            ),
        )
    result = StateUpdatesService(settings).for_state(state.code, refresh=refresh)
    return StateUpdatesOut.model_validate(result, from_attributes=True)


@router.get("/suggestions", response_model=SuggestionsOut)
def suggestions(
    session: DbSession,
    state_code: str | None = Query(default=None, max_length=8),
    session_id: str | None = Query(default=None),
    principal: Principal = role_required(Role.READONLY),
) -> SuggestionsOut:
    """Starter questions for this state and conversation."""
    has_history = False
    has_attachments = False
    if session_id:
        row = session.get(ChatSession, session_id)
        has_history = bool(row and row.message_count)
        has_attachments = bool(ChatAttachmentService(session).list_for(session_id))
    return SuggestionsOut(
        suggestions=suggestions_for(
            state_code=state_code,
            has_attachments=has_attachments,
            has_history=has_history,
        )
    )


def _state_out(state: Jurisdiction) -> StateProfileOut:
    return StateProfileOut(
        code=state.code,
        name=state.name,
        kind=state.kind,
        agency=state.agency.name,
        agency_url=state.agency.url,
        agencies=[
            AgencyOut(name=a.name, url=a.url, administers=a.administers)
            for a in state.agencies
        ],
        updates_url=state.updates_url,
        taxes_wage_income=state.taxes_wage_income,
        has_statewide_sales_tax=state.has_statewide_sales_tax,
        business_tax=state.business_tax,
        features=state.feature_labels,
        hints=list(state.hints),
    )
