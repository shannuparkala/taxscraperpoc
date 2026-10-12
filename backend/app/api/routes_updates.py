"""Industry Updates: the feed, source status, bookmarks and an optional AI summary.

The AI summary is the only model call. It is built from the item's title and
the agency's own excerpt - public text, scrubbed with
``redact_blocking_patterns`` like any other public source (CLAUDE.md trap 5) -
and it is:

* labelled AI-generated wherever it is shown, with the original link beside it;
* short and in the model's own words, never a reconstruction of the article;
* withheld if it states a number the title and excerpt do not contain.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import DbSession, GeminiDep, SettingsDep, rate_limit, role_required
from app.core.config import Role
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.core.rate_limit import enforce
from app.core.security import DEV_PRINCIPAL_ID, Principal
from app.models.database_models import NewsBookmark
from app.models.enums import TaskKind
from app.services import reference_data
from app.services.llm_egress_guard import redact_blocking_patterns
from app.services.news_service import get_news_service

logger = get_logger(__name__)

router = APIRouter(prefix="/api/updates", tags=["updates"])

SUMMARY_LABEL = "AI-generated summary"
SUMMARY_SYSTEM = (
    "You write a two-sentence plain-English summary of a public tax news item for a tax associate. "
    "Use only the TITLE and EXCERPT given. Use your own words; do not quote. Do not add facts, dates, "
    "figures or advice that are not in the text. If the text is too short to summarize, reply with "
    "one sentence saying what the item is about."
)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _client(request: Request, principal: Principal) -> str:
    if principal.user_id != DEV_PRINCIPAL_ID:
        return principal.user_id
    return request.client.host if request.client else "unknown"


def _burst(request: Request, principal: Principal = role_required(Role.READONLY)) -> None:
    enforce("updates", _client(request, principal))


@router.get("", dependencies=[Depends(_burst)])
def feed(
    source: str | None = Query(default=None),
    topic: str | None = Query(default=None),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    principal: Principal = role_required(Role.READONLY),
) -> dict[str, Any]:
    service = get_news_service()
    if service.is_stale():
        # Never block the page on a slow agency site: the first visit gets
        # whatever is cached (possibly nothing, with status "pending") and the
        # refresh lands for the next request.
        service.refresh_in_background()
    config = reference_data.news_sources()
    statuses = service.statuses()
    updated = [s.last_updated for s in statuses if s.last_updated]
    return {
        "items": [i.to_dict() for i in service.items(source=source, topic=topic, start=start, end=end, limit=limit)],
        "sources": [s.to_dict() for s in statuses],
        "topics": [{"key": t.key, "label": t.label} for t in config.topics],
        "last_updated": max(updated) if updated else None,
    }


@router.post("/refresh", dependencies=[Depends(_burst)])
def refresh(principal: Principal = role_required(Role.PREPARER)) -> dict[str, Any]:
    """Ask for a refresh now. Still bounded by the per-source minimum interval."""
    get_news_service().refresh_in_background()
    return {"accepted": True}


# ---------------------------------------------------------------- bookmarks


class BookmarkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str


@router.get("/bookmarks")
def list_bookmarks(session: DbSession, principal: Principal = role_required(Role.READONLY)) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(NewsBookmark).where(NewsBookmark.owner_id == principal.user_id).order_by(NewsBookmark.created_at.desc())
    ).all()
    return [
        {"id": r.id, "item_id": r.item_id, "source": r.source, "title": r.title, "url": r.url, "published": r.published}
        for r in rows
    ]


@router.post("/bookmarks", status_code=201)
def add_bookmark(payload: BookmarkIn, session: DbSession,
                 principal: Principal = role_required(Role.READONLY)) -> dict[str, Any]:
    item = get_news_service().find(payload.item_id)
    if item is None:
        raise NotFoundError("That update is no longer in the feed.")
    existing = session.scalars(select(NewsBookmark).where(
        NewsBookmark.owner_id == principal.user_id, NewsBookmark.item_id == item.id)).first()
    row = existing or NewsBookmark(owner_id=principal.user_id, item_id=item.id, source=item.source,
                                   title=item.title[:500], url=item.url[:1000], published=item.published)
    if existing is None:
        session.add(row)
        session.flush()
    return {"id": row.id, "item_id": row.item_id, "source": row.source, "title": row.title,
            "url": row.url, "published": row.published}


@router.delete("/bookmarks/{bookmark_id}", status_code=204)
def delete_bookmark(bookmark_id: str, session: DbSession,
                    principal: Principal = role_required(Role.READONLY)) -> Response:
    row = session.get(NewsBookmark, bookmark_id)
    if row is None or row.owner_id != principal.user_id:
        raise NotFoundError("No such bookmark.")
    session.delete(row)
    return Response(status_code=204)


# ------------------------------------------------------------------ summary


def unsupported_numbers(summary: str, source_text: str) -> set[str]:
    allowed = {n.replace(",", "") for n in _NUMBER.findall(source_text)}
    return {n.replace(",", "") for n in _NUMBER.findall(summary)} - allowed


@router.post("/{item_id}/summary", dependencies=[rate_limit("chat")])
def summarize(item_id: str, gemini: GeminiDep, settings: SettingsDep,
              principal: Principal = role_required(Role.READONLY)) -> dict[str, Any]:
    item = get_news_service().find(item_id)
    if item is None:
        raise NotFoundError("That update is no longer in the feed.")
    base = {"label": SUMMARY_LABEL, "source_url": item.url, "source_name": item.source_name}
    if item.source not in ("irs", "treasury"):
        # A licensed publisher's text is not ours to paraphrase.
        return {**base, "available": False, "text": "", "reason": "Summaries are offered for public sources only."}
    if not gemini.enabled:
        return {**base, "available": False, "text": "", "reason": "The summary service is unavailable."}
    source_text = redact_blocking_patterns(f"TITLE: {item.title}\nEXCERPT: {item.excerpt}")
    try:
        response = gemini.generate(
            prompt=source_text, task=TaskKind.CHAT_SIMPLE, system_instruction=SUMMARY_SYSTEM,
            context="news_summary", model=settings.assistant_model, temperature=0.2,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("News summary failed (%s)", type(exc).__name__)
        return {**base, "available": False, "text": "", "reason": "The summary service did not respond."}
    text = (response.text or "").strip()
    if not text or unsupported_numbers(text, source_text):
        return {**base, "available": False, "text": "",
                "reason": "The summary could not be checked against the item, so it was withheld. Read the original."}
    return {**base, "available": True, "text": text[:600], "reason": ""}
