"""The associate's clients and hand-added deadlines, for the dashboard calendar.

Deadlines are *not* computed here: the browser's deadline engine derives them
from each client's entity type, year end, states and extension status using
the same rule files the countdown tiles read. This router only stores the
inputs.

SECURITY/privacy: client names, notes and custom deadline titles are
encrypted at rest and never logged - log lines carry counts and ids only.
Every query is scoped to the caller's own rows; another associate's id
returns 404, not 403, so ids cannot be probed.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.api.deps import DbSession, role_required
from app.core.config import Role
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.core.security import Principal, decrypt_text, encrypt_text
from app.models.database_models import CustomDeadline, WorkspaceClient
from app.services.assistant import state_registry
from app.services.reference_data import ENTITY_KEYS

logger = get_logger(__name__)

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

EntityType = Literal["individual", "c_corp", "s_corp", "partnership", "trust_estate", "exempt_org"]
assert set(EntityType.__args__) == set(ENTITY_KEYS)  # type: ignore[attr-defined]


class ClientIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=200)]
    entity_type: EntityType
    fiscal_year_end_month: Annotated[int, Field(ge=1, le=12)] = 12
    states: list[str] = []
    extension_status: Literal["not_extended", "extended"] = "not_extended"
    notes: Annotated[str, Field(max_length=2000)] = ""

    @field_validator("name")
    @classmethod
    def _no_identifiers(cls, value: str) -> str:
        # SECURITY: the calendar needs a display name, nothing more. A value
        # shaped like an SSN or EIN is refused rather than stored.
        if re.search(r"\b\d{3}-?\d{2}-?\d{4}\b|\b\d{2}-\d{7}\b", value):
            raise ValueError("Use a name, not an SSN or EIN.")
        return value.strip()

    @field_validator("states")
    @classmethod
    def _valid_states(cls, value: list[str]) -> list[str]:
        codes = []
        for code in value:
            code = code.strip().upper()
            if state_registry.get(code) is None:
                raise ValueError(f"{code} is not a supported state")
            if code not in codes:
                codes.append(code)
        return codes


class ClientOut(BaseModel):
    id: str
    name: str
    entity_type: str
    fiscal_year_end_month: int
    states: list[str]
    extension_status: str
    notes: str


class CustomDeadlineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(min_length=1, max_length=200)]
    due_date: date
    client_id: str | None = None
    kind: Literal["deadline", "task"] = "deadline"
    done: bool = False


class CustomDeadlineOut(BaseModel):
    id: str
    title: str
    due_date: str
    client_id: str | None
    kind: str
    done: bool


def _client_out(row: WorkspaceClient) -> ClientOut:
    return ClientOut(
        id=row.id,
        name=decrypt_text(row.name_encrypted),
        entity_type=row.entity_type,
        fiscal_year_end_month=row.fiscal_year_end_month,
        states=list(row.states or []),
        extension_status=row.extension_status,
        notes=decrypt_text(row.notes_encrypted) if row.notes_encrypted else "",
    )


def _deadline_out(row: CustomDeadline) -> CustomDeadlineOut:
    return CustomDeadlineOut(
        id=row.id, title=decrypt_text(row.title_encrypted), due_date=row.due_date,
        client_id=row.client_id, kind=row.kind, done=row.done,
    )


def _own_client(session: DbSession, principal: Principal, client_id: str) -> WorkspaceClient:
    row = session.get(WorkspaceClient, client_id)
    if row is None or row.owner_id != principal.user_id:
        raise NotFoundError("No such client.")
    return row


# ------------------------------------------------------------------ clients


@router.get("/clients", response_model=list[ClientOut])
def list_clients(session: DbSession, principal: Principal = role_required(Role.READONLY)) -> list[ClientOut]:
    rows = session.scalars(
        select(WorkspaceClient).where(WorkspaceClient.owner_id == principal.user_id)
        .order_by(WorkspaceClient.created_at)
    ).all()
    return sorted((_client_out(r) for r in rows), key=lambda c: c.name.lower())


@router.post("/clients", response_model=ClientOut, status_code=201)
def create_client(payload: ClientIn, session: DbSession,
                  principal: Principal = role_required(Role.PREPARER)) -> ClientOut:
    row = WorkspaceClient(
        owner_id=principal.user_id,
        name_encrypted=encrypt_text(payload.name),
        entity_type=payload.entity_type,
        fiscal_year_end_month=payload.fiscal_year_end_month,
        states=payload.states,
        extension_status=payload.extension_status,
        notes_encrypted=encrypt_text(payload.notes) if payload.notes else None,
    )
    session.add(row)
    session.flush()
    logger.info("Workspace client created (%s, %d state(s))", payload.entity_type, len(payload.states))
    return _client_out(row)


@router.put("/clients/{client_id}", response_model=ClientOut)
def update_client(client_id: str, payload: ClientIn, session: DbSession,
                  principal: Principal = role_required(Role.PREPARER)) -> ClientOut:
    row = _own_client(session, principal, client_id)
    row.name_encrypted = encrypt_text(payload.name)
    row.entity_type = payload.entity_type
    row.fiscal_year_end_month = payload.fiscal_year_end_month
    row.states = payload.states
    row.extension_status = payload.extension_status
    row.notes_encrypted = encrypt_text(payload.notes) if payload.notes else None
    session.flush()
    return _client_out(row)


@router.delete("/clients/{client_id}", status_code=204)
def delete_client(client_id: str, session: DbSession,
                  principal: Principal = role_required(Role.PREPARER)) -> Response:
    row = _own_client(session, principal, client_id)
    # Explicit, not only the FK cascade: SQLite enforces cascades only with
    # foreign_keys=ON, which a test database may not set.
    for deadline in session.scalars(select(CustomDeadline).where(CustomDeadline.client_id == row.id)):
        session.delete(deadline)
    session.delete(row)
    return Response(status_code=204)


# --------------------------------------------------------- custom deadlines


@router.get("/deadlines", response_model=list[CustomDeadlineOut])
def list_custom_deadlines(session: DbSession,
                          principal: Principal = role_required(Role.READONLY)) -> list[CustomDeadlineOut]:
    rows = session.scalars(
        select(CustomDeadline).where(CustomDeadline.owner_id == principal.user_id)
        .order_by(CustomDeadline.due_date)
    ).all()
    return [_deadline_out(r) for r in rows]


@router.post("/deadlines", response_model=CustomDeadlineOut, status_code=201)
def create_custom_deadline(payload: CustomDeadlineIn, session: DbSession,
                           principal: Principal = role_required(Role.PREPARER)) -> CustomDeadlineOut:
    if payload.client_id:
        _own_client(session, principal, payload.client_id)
    row = CustomDeadline(
        owner_id=principal.user_id, client_id=payload.client_id, due_date=payload.due_date.isoformat(),
        title_encrypted=encrypt_text(payload.title), kind=payload.kind, done=payload.done,
    )
    session.add(row)
    session.flush()
    return _deadline_out(row)


@router.put("/deadlines/{deadline_id}", response_model=CustomDeadlineOut)
def update_custom_deadline(deadline_id: str, payload: CustomDeadlineIn, session: DbSession,
                           principal: Principal = role_required(Role.PREPARER)) -> CustomDeadlineOut:
    row = session.get(CustomDeadline, deadline_id)
    if row is None or row.owner_id != principal.user_id:
        raise NotFoundError("No such deadline.")
    if payload.client_id:
        _own_client(session, principal, payload.client_id)
    row.title_encrypted = encrypt_text(payload.title)
    row.due_date = payload.due_date.isoformat()
    row.client_id = payload.client_id
    row.kind = payload.kind
    row.done = payload.done
    session.flush()
    return _deadline_out(row)


@router.delete("/deadlines/{deadline_id}", status_code=204)
def delete_custom_deadline(deadline_id: str, session: DbSession,
                           principal: Principal = role_required(Role.PREPARER)) -> Response:
    row = session.get(CustomDeadline, deadline_id)
    if row is None or row.owner_id != principal.user_id:
        raise NotFoundError("No such deadline.")
    session.delete(row)
    return Response(status_code=204)
