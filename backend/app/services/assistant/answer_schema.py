"""Vocabulary shared by the assistant's answers, and the fixed disclaimer.

Answers are streamed markdown, not schema-constrained JSON: a fixed schema
gave every answer the same eleven sections whether the question was "what is
the standard deduction" or a multi-state residency dispute, and producing it
needed a second, blocking model call. What remains structured is decided
outside the prose - the scope and answer type (``router``), the tax year (the
answer's hidden META line, ``answer_text``), and the sources (grounding
metadata, ``citations``).

The model is never asked for URLs or for the disclaimer: citations come only
from grounding, and the disclaimer is fixed server text, so it reads the same
on every answer.
"""

from __future__ import annotations

from enum import Enum


class Scope(str, Enum):
    US_TAX = "us_tax"
    NON_TAX = "non_tax"
    NON_US_TAX = "non_us_tax"
    EVASION_REQUEST = "evasion_request"


class JurisdictionLevel(str, Enum):
    FEDERAL = "federal"
    STATE = "state"
    FEDERAL_AND_STATE = "federal_and_state"
    MULTI_STATE = "multi_state"
    NONE = "none"


#: Fixed, short, and the same on every answer.
DISCLAIMER = (
    "General information, not legal, tax or financial advice. Using this "
    "assistant does not create an attorney-client or CPA-client relationship."
)
