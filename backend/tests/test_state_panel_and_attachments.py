"""The two assistant features the rebuild kept: the state updates panel and
documents attached to a conversation.

Ported from the previous assistant's test suite when its answering logic was
removed; the features they defend did not change. Invented values only - the
notice below is fabricated and its SSN is the one the security suite uses.
"""

from __future__ import annotations

import io
from typing import Any

import pytest

from app.services.assistant import state_registry

_NOTICE = (
    "NOTICE OF PROPOSED ASSESSMENT\n\n"
    "Taxpayer: Dolores Ashworth\n"
    "Account: 412-88-7364\n"
    "Email: dolores.ashworth@northwind-example.test\n\n"
    "Our records show unreported sales of $184,200 for the period ending "
    "31 March 2026. Tax of $11,512 is proposed, plus interest.\n\n"
    "You must respond in writing within 30 days of the date of this notice. "
    "If you do not respond the assessment becomes final and collection "
    "begins.\n"
)


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------


def _conversation(session: Any) -> str:
    from app.models.database_models import ChatSession

    row = ChatSession(title="New conversation")
    session.add(row)
    session.flush()
    return row.id


def _attach(session: Any, text: str = _NOTICE, name: str = "notice.txt"):
    from app.services.chat_attachment_service import ChatAttachmentService

    session_id = _conversation(session)
    summary = ChatAttachmentService(session).attach(
        session_id=session_id,
        filename=name,
        stream=io.BytesIO(text.encode("utf-8")),
        content_type="text/plain",
    )
    return session_id, summary


@pytest.mark.security
def test_an_attachment_is_stored_with_its_values_tokenized(session: Any) -> None:
    """SECURITY: the stored text is the only thing a prompt can ever include."""
    from app.services.chat_attachment_service import ChatAttachmentService

    session_id, summary = _attach(session)
    assert summary.masked_value_count > 0

    stored = ChatAttachmentService(session).masked_text_for(session_id, max_chars=10_000)
    assert "Dolores" not in stored
    assert "412-88-7364" not in stored
    assert "dolores.ashworth@northwind-example.test" not in stored
    # The tax facts must survive, or the document is useless to ask about.
    assert "184,200" in stored
    assert "30 days" in stored


@pytest.mark.security
def test_attachment_text_is_scoped_to_its_own_conversation(session: Any) -> None:
    from app.services.chat_attachment_service import ChatAttachmentService

    _attach(session)
    other = _conversation(session)
    assert ChatAttachmentService(session).masked_text_for(other, max_chars=10_000) == ""


def test_attachment_text_is_truncated_to_the_budget(session: Any) -> None:
    from app.services.chat_attachment_service import ChatAttachmentService

    session_id, _ = _attach(session)
    text = ChatAttachmentService(session).masked_text_for(session_id, max_chars=120)
    assert len(text) <= 120 + len("\n[... truncated ...]")
    assert text.endswith("[... truncated ...]")


def test_an_unreadable_attachment_is_refused_rather_than_stored_empty(session: Any) -> None:
    from app.core.errors import ValidationError
    from app.services.chat_attachment_service import ChatAttachmentService

    with pytest.raises(ValidationError):
        ChatAttachmentService(session).attach(
            session_id=_conversation(session),
            filename="empty.txt",
            stream=io.BytesIO(b"   "),
            content_type="text/plain",
        )


def test_an_unsupported_file_type_says_what_is_supported(session: Any) -> None:
    from app.core.errors import ValidationError
    from app.services.chat_attachment_service import ChatAttachmentService

    with pytest.raises(ValidationError, match="PDF"):
        ChatAttachmentService(session).attach(
            session_id=_conversation(session),
            filename="photo.heic",
            stream=io.BytesIO(b"not really an image"),
            content_type="image/heic",
        )


@pytest.mark.security
def test_removing_an_attachment_needs_the_right_conversation(session: Any) -> None:
    from app.services.chat_attachment_service import ChatAttachmentService

    session_id, summary = _attach(session)
    attachments = ChatAttachmentService(session)
    other = _conversation(session)

    assert not attachments.remove(session_id=other, document_id=summary.document_id)
    assert attachments.remove(session_id=session_id, document_id=summary.document_id)
    assert attachments.list_for(session_id) == []


# ---------------------------------------------------------------------------
# State updates panel
# ---------------------------------------------------------------------------


class _StubFetcher:
    """Serves canned pages. Asserts nothing leaves the process."""

    def __init__(self, pages: dict[str, Any]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    def fetch(self, url: str, **_: object) -> Any:
        self.requested.append(url)
        if url not in self.pages:
            raise RuntimeError("unreachable")
        return self.pages[url]

    def fetch_many(self, urls, **_: object):
        from app.services.public_web_fetcher import FetchResult

        for url in urls:
            self.requested.append(url)
            page = self.pages.get(url)
            yield FetchResult(url=url, source=page, error=None if page else "RuntimeError")


def _page(url: str, title: str, content: str, links: dict[str, str] | None = None):
    from datetime import UTC, datetime

    from app.services.public_web_fetcher import FetchedSource

    return FetchedSource(
        url=url,
        title=title,
        content=content,
        content_type="text/html",
        fetched_at=datetime.now(UTC),
        discovered_links=list((links or {}).keys()),
        link_titles=dict(links or {}),
    )


@pytest.fixture()
def fresh_cache():
    import app.services.state_updates_service as module

    with module._CACHE_LOCK:
        module._CACHE = None
    yield


def test_state_updates_take_headline_and_date_from_the_item_itself(fresh_cache) -> None:
    from app.services.state_updates_service import StateUpdatesService

    state = state_registry.require("TX")
    item_url = "https://comptroller.texas.gov/about/media-center/news/2026/rate.php"
    fetcher = _StubFetcher(
        {
            state.updates_url: _page(
                state.updates_url, "News", "Latest news",
                {item_url: "Read more", state.agency.url: "Home"},
            ),
            item_url: _page(
                item_url,
                "Comptroller announces a local rate change | Texas Comptroller",
                "March 9, 2026. The Comptroller announced a local rate change "
                "effective 1 July. Sellers should update their systems.",
            ),
        }
    )
    result = StateUpdatesService(fetcher=fetcher).for_state("TX")
    assert not result.error, result.error
    assert len(result.items) == 1
    item = result.items[0]
    assert item.headline == "Comptroller announces a local rate change"
    assert item.published == "2026-03-09"
    assert item.url == item_url
    assert result.agency == "Texas Comptroller of Public Accounts"


def test_state_updates_say_they_could_not_look_rather_than_showing_nothing(fresh_cache) -> None:
    """An empty list reads as "this state published nothing", which is a lie."""
    from app.services.state_updates_service import StateUpdatesService

    result = StateUpdatesService(fetcher=_StubFetcher({})).for_state("OH")
    assert result.items == []
    assert "could not be reached" in result.error
    assert result.updates_url.startswith("https://")


@pytest.mark.security
def test_state_updates_never_follow_a_link_off_the_agencys_own_domain(fresh_cache) -> None:
    from app.services.state_updates_service import StateUpdatesService

    state = state_registry.require("OH")
    offsite = "https://news.example.test/ohio/2026/tax-change"
    fetcher = _StubFetcher(
        {
            state.updates_url: _page(
                state.updates_url, "Tax alerts", "Alerts",
                {offsite: "Ohio raises a threshold, reports Example News"},
            )
        }
    )
    StateUpdatesService(fetcher=fetcher).for_state("OH")
    assert offsite not in fetcher.requested


def test_an_update_summary_is_the_news_not_the_masthead() -> None:
    from app.services.state_updates_service import _summary

    dateline = _summary(
        "Texas Comptroller of Public Accounts FOR IMMEDIATE RELEASE "
        "September 14, 2026 Comptroller Announces a Rate Change (AUSTIN) - "
        "The Comptroller today announced a local rate change effective 1 July.",
        "Comptroller Announces a Rate Change",
    )
    assert dateline.startswith("The Comptroller today announced")
    assert "IMMEDIATE RELEASE" not in dateline

    plain = _summary("The Commissioner announced a change. It takes effect July 1.", "A change")
    assert plain == "The Commissioner announced a change. It takes effect July 1."


def test_the_state_updates_regexes_actually_compiled() -> None:
    r"""CLAUDE.md trap 26: a heredoc once turned ``\b`` into a backspace byte."""
    from app.services.state_updates_service import (
        _DATELINE,
        _LEADING_DATE,
        _RELEASE_FURNITURE,
    )

    for pattern in (_RELEASE_FURNITURE, _DATELINE, _LEADING_DATE):
        assert "\x08" not in pattern.pattern, pattern.pattern
        assert "\\\\" not in pattern.pattern, pattern.pattern


def test_every_registry_url_is_https_and_on_its_own_domains() -> None:
    """The updates panel only follows links on the state's own domains."""
    from urllib.parse import urlparse

    for state in state_registry.JURISDICTIONS:
        urls = [state.updates_url, *(agency.url for agency in state.agencies)]
        for url in urls:
            parsed = urlparse(url)
            assert parsed.scheme == "https", url
            assert parsed.hostname in state.domains or (
                parsed.hostname or ""
            ).removeprefix("www.") in state.domains, (state.code, url)
