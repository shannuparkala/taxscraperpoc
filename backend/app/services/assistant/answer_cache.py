"""Reusing an answer to the same question asked again the same day.

Suggestion chips and common questions ("what is the standard deduction?") are
asked over and over, and each one costs a grounded call and ten seconds or
more. A checked answer is kept, in this process's memory, and replayed when
the same question is asked again under the same conditions.

What makes two questions "the same" is deliberately strict - the key is the
normalised question text plus everything that shaped the answer: the states
it must cover, whether a selected state was set aside, the tax year, the
answer type, the model, and *today's date*. The date is in the key because
the prompt tells the model what today is (deadlines, the most recent filing
year), so an answer is never replayed on a later day.

What is never cached or served from the cache:

* a question asked with ``/mask`` - it is about somebody, not a general
  question, and its restore map belongs to one request;
* a question with conversation history or attachments - its answer depends
  on context the key does not capture;
* anything but a clean ``answered`` payload - fallbacks, refusals, outages
  and answers with flagged figures are worth asking again.

It is a per-process LRU with a TTL, not shared infrastructure: a restart
empties it, which costs one fresh answer per question.
"""

from __future__ import annotations

import copy
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CacheKey:
    question: str
    required: tuple[str, ...]
    selection_ignored: bool
    federal_too: bool
    tax_year: int | None
    answer_type: str
    model: str
    day: str


def normalise(question: str) -> str:
    """Case, spacing and trailing punctuation do not make a different question."""
    text = re.sub(r"\s+", " ", question.strip().lower())
    return text.rstrip(" ?.!")


class AnswerCache:
    def __init__(self, *, max_entries: int, ttl_seconds: float) -> None:
        self._max = max_entries
        self._ttl = ttl_seconds
        self._items: OrderedDict[CacheKey, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._max > 0 and self._ttl > 0

    def get(self, key: CacheKey) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            stored_at, payload = item
            if time.monotonic() - stored_at > self._ttl:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return copy.deepcopy(payload)

    def put(self, key: CacheKey, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._items[key] = (time.monotonic(), copy.deepcopy(payload))
            self._items.move_to_end(key)
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


def cacheable(payload: dict[str, Any]) -> bool:
    """Only a clean answer is worth replaying."""
    return (
        payload.get("status") == "answered"
        and bool(payload.get("citations"))
        and not payload.get("unsourced_figures")
        and not payload.get("tax_year_missing")
    )
