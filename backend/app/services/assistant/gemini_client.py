"""The model call behind every answer: one grounded, streamed reply.

It goes through ``GeminiService``, which stays the only path to the model:
the egress guard, retries before the first token, timeouts, rate-limit
pacing, audit and cost metering all live there.

**History (CLAUDE.md trap 35).** The first rebuilt assistant used one call
with Search grounding *and* a response schema; against the live API the JSON
intermittently lost spans and the model sometimes skipped searching. The fix
was two calls - grounded free-text research, then schema-constrained
structuring with no tools - which was reliable but slow: two long
generations in series (median 34 s, nothing on screen until the end), and a
fixed eleven-section layout for every question.

Now there is one call again, and it is grounded *free text* - the
provider's well-trodden path, which searched on twelve of twelve probe calls
in the trap-35 investigation. The answer streams to the reader as it is
written; the markdown is not schema-constrained, so there is no JSON to
corrupt. What the schema used to carry that software needs (tax year, scope)
is one META line the model writes first (``answer_text``). Grounding still
arrives only with the last chunk, so ``validators`` check it at the end and a
draft that fails is withdrawn and regenerated.
"""

from __future__ import annotations

from collections.abc import Iterator

from app.core.config import Settings
from app.models.enums import TaskKind
from app.services.gemini_service import GeminiService, StreamEvent
from app.services.llm_meter import MeterScope


class GroundedAnswerClient:
    def __init__(self, gemini: GeminiService, settings: Settings) -> None:
        self._gemini = gemini
        self._settings = settings

    @property
    def gemini(self) -> GeminiService:
        """The gateway, for the router's small classification call."""
        return self._gemini

    @property
    def available(self) -> bool:
        """True when a real model call is possible.

        There is no offline answer: a stubbed tax answer is a well-formed
        answer from nowhere, which is worse than saying the assistant is
        unavailable.
        """
        return self._gemini.enabled

    def stream_answer(
        self, *, system_instruction: str, prompt: str, meter_scope: MeterScope | None = None
    ) -> Iterator[StreamEvent]:
        """Text deltas, then a ``done`` event with the grounding.

        Raises ``LlmError`` / ``EgressBlockedError``.
        """
        yield from self._gemini.stream_events(
            prompt=prompt,
            task=TaskKind.CHAT_COMPLEX,
            system_instruction=system_instruction,
            context="assistant_answer",
            google_search=True,
            model=self._settings.assistant_model,
            temperature=self._settings.assistant_temperature,
            thinking_level=self._settings.assistant_thinking_level or None,
            meter_scope=meter_scope,
        )
