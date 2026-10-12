"""Reading the model's markdown answer: the hidden META line, cleanup, parts.

The answer is one grounded, streamed markdown reply. Two things in it are for
software, not the reader, and are taken out here:

* a first line ``META: tax_year=2025; assumed=yes; fallback=no; scope=us_tax``,
  which says which tax year the figures apply to, whether that is an earlier
  year than the one asked for (its figures not yet published), and whether
  the question was in scope.
  It comes *first* so the stream can hold back one line and then pass
  everything else straight through;
* a closing ``### To tailor this`` list of at most two questions, which the
  UI shows as a prompt for the reader rather than as part of the answer.

Everything the model writes that looks like a citation - ``[3]``, ``[cite:
2]``, a URL, a "Sources" section - is removed: citations are built only from
grounding metadata (``citations``). A hypothetical example is located so no
source marker is ever placed inside it - invented numbers are not sourced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

#: ``META: tax_year=2025; assumed=yes; scope=us_tax``, tolerating markdown
#: decoration around it.
_META_LINE = re.compile(r"^[\s*_`>#-]*META[ \t]*:[ \t]*(?P<body>[^\n]*?)[\s*_`]*$", re.IGNORECASE)
#: ``key=value`` pairs; a value runs to the next ``key=`` (separated by ";" or
#: ","), so "tax_year=2024, 2025" keeps both years.
_META_PAIR = re.compile(r"(\w+)[ \t]*=[ \t]*(.+?)(?=[ \t]*(?:[;,][ \t]*\w+[ \t]*=|;|$))")
#: How much text to hold back waiting for the META line before giving up on it.
_META_WAIT_CHARS = 240

#: Citation-looking things the model was told not to write.
_MODEL_MARKERS = re.compile(r"[ \t]*\[(?:cite:[ \t]*)?\d{1,3}(?:[ \t]*,[ \t]*\d{1,3})*\]", re.IGNORECASE)
_MD_LINK = re.compile(r"\[([^\]\n]+)\]\((?:https?://|www\.)[^)\s]+\)")
_URL = re.compile(r"\(?\b(?:https?://|www\.)[^\s)\]]+\)?")
_HEADING = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.*)$", re.MULTILINE)
_SOURCES_HEADING = re.compile(r"^(?:sources|references|citations|works cited)\b", re.IGNORECASE)
_FOLLOW_UP_HEADING = re.compile(
    r"^(?:to tailor this|to make this more precise|follow[- ]up questions?|questions for you)",
    re.IGNORECASE,
)
_LIST_ITEM = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+(.*\S)")

#: A year a person might mean as a tax year, not glued to letters or digits:
#: "CP2000" and "Form 1099" are not years.
_YEAR = re.compile(r"(?<![\w-])(19[89]\d|20\d\d)(?![\w-])")
#: A sentence stating a figure: money, a percentage, or a calendar date.
FIGURE = re.compile(
    r"\$[ \t]?\d|\d(?:\.\d+)?[ \t]?%|\b(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)[ \t]+\d{1,2}\b"
)

#: How many follow-up questions are ever shown.
MAX_FOLLOW_UPS = 2


@dataclass(frozen=True, slots=True)
class Meta:
    tax_year: str = ""
    assumed: bool = False
    scope: str = ""
    found: bool = False
    #: The model says the requested year's figures are not published and it
    #: answered with an earlier year's (``validators.check_tax_year``).
    fallback: bool = False

    @property
    def years(self) -> tuple[int, ...]:
        return tuple(int(y) for y in _YEAR.findall(self.tax_year))


def parse_meta(line: str) -> Meta | None:
    match = _META_LINE.match(line.strip())
    if not match:
        return None
    pairs = {key.lower(): value.strip().strip("`*") for key, value in _META_PAIR.findall(match["body"])}
    years = _YEAR.findall(pairs.get("tax_year", ""))
    return Meta(
        tax_year=_join_years(years),
        assumed=pairs.get("assumed", "").lower() in {"yes", "true", "y"},
        scope=pairs.get("scope", "").lower(),
        found=True,
        fallback=pairs.get("fallback", "").lower() in {"yes", "true", "y"},
    )


def split_meta(text: str) -> tuple[Meta, str]:
    """The META line (if the first non-empty line is one) and the rest."""
    stripped = text.lstrip()
    first, _, rest = stripped.partition("\n")
    meta = parse_meta(first)
    if meta is None:
        return Meta(), text
    return meta, rest.lstrip("\n")


class MetaFilter:
    """Pass streamed text through, minus a leading META line.

    Holds text back only until the first line is complete (or long enough
    that it clearly is not META), so the reader waits a few tokens at most.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._decided = False
        #: The blank line after META can arrive in a later chunk than the
        #: META line itself; it is dropped until the answer's first text.
        self._leading = True
        self.meta = Meta()

    def feed(self, piece: str) -> str:
        if self._decided:
            return self._lead(piece)
        self._buffer += piece
        stripped = self._buffer.lstrip()
        if "\n" not in stripped and len(stripped) < _META_WAIT_CHARS:
            return ""
        self._decided = True
        self.meta, rest = split_meta(self._buffer)
        self._buffer = ""
        return self._lead(rest)

    def _lead(self, piece: str) -> str:
        if self._leading and self.meta.found:
            piece = piece.lstrip("\n")
            self._leading = not piece
        return piece

    def flush(self) -> str:
        if self._decided:
            return ""
        self._decided = True
        self.meta, rest = split_meta(self._buffer)
        self._buffer = ""
        return rest


def clean(text: str) -> str:
    """Remove everything the model wrote that pretends to be a citation.

    Also any META line that was not the first line (the stream filter only
    holds back the first), so metadata never reaches the stored answer.
    """
    text = "\n".join(line for line in text.split("\n") if not _META_LINE.match(line.strip()))
    text = _MD_LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    text = _MODEL_MARKERS.sub("", text)
    text = _drop_sections(text, _SOURCES_HEADING)
    text = re.sub(r"(?<=\S)[ \t]+([.,;:])", r"\1", text)
    text = collapse_inner_spaces(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


#: A list item's marker and the spaces after it: "*   ", "  - ", "3. ".
_LIST_PREFIX = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+")


def collapse_inner_spaces(text: str) -> str:
    """Collapse runs of spaces between words, and nothing else.

    Leading indentation is list nesting, and the spaces after a list marker
    are list syntax: Gemini writes ``*   item``, and collapsing that to
    ``* item`` changed the text grounding supports quote, so their markers
    either went missing (and the figure showed "[?]") or were placed between
    the bullet and a ``**bold**`` label - an empty bullet holding "4Federal".
    """
    out = []
    for line in text.split("\n"):
        head = _LIST_PREFIX.match(line)
        cut = head.end() if head else 0
        out.append(line[:cut] + re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", line[cut:]))
    return "\n".join(out)


def split_follow_ups(text: str) -> tuple[str, list[str]]:
    """The answer without its "To tailor this" section, and that section's questions."""
    questions: list[str] = []
    for start, end in _sections(text, _FOLLOW_UP_HEADING):
        for line in text[start:end].splitlines()[1:]:
            item = _LIST_ITEM.match(line)
            if item:
                questions.append(item.group(1).strip().strip("*_").strip())
    return _drop_sections(text, _FOLLOW_UP_HEADING).strip(), questions[:MAX_FOLLOW_UPS]


def example_ranges(text: str) -> list[tuple[int, int]]:
    """Character ranges of sections whose heading names an example."""
    return _sections(text, re.compile(r".*\bexamples?\b", re.IGNORECASE))


def first_paragraph(text: str) -> str:
    """The lead paragraph: what history replay and the legacy layout see."""
    for block in re.split(r"\n[ \t]*\n", text):
        block = block.strip()
        if block and not _HEADING.match(block):
            return _MODEL_MARKERS.sub("", block).strip()
    return ""


def tax_year(meta: Meta, text: str, *, today: date) -> str:
    """The tax year(s) the answer applies to: META first, else the text."""
    if meta.tax_year:
        return meta.tax_year
    years = [y for y in _YEAR.findall(text) if 1980 <= int(y) <= today.year + 1]
    return _join_years(years) if 0 < len(set(years)) <= 2 else ""


def has_figures(text: str) -> bool:
    return FIGURE.search(text) is not None


#: The flag placed after a figure no source passage was matched to. The UI
#: renders it as a "not matched to a source" chip.
UNSOURCED = "[?]"
_CITED = re.compile(r"\[\d{1,2}\]")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
#: A sentence boundary. Source markers sit *after* the full stop ("taxable.
#: [1] Next"), so a boundary is never placed before a marker - only after
#: it, or after a full stop with no marker following.
_SENTENCE_END = re.compile(r"(?<=[.!?])[ \t]+(?!\[(?:\d|\?))|(?<=\d\]|\?\])[ \t]+(?=\S)")


def flag_unsourced_figures(text: str, *, question: str) -> tuple[str, int]:
    """Flag each sentence that states a figure no grounding support covers.

    A rate, amount or deadline with no source marker is exactly the claim a
    reader most needs to check, and grounding does not cover every sentence
    the model writes - so it is labelled rather than shown as if sourced.
    Not flagged: anything inside a hypothetical example (invented on
    purpose), a sentence whose numbers all came from the user's question,
    worked arithmetic (a line with "="), headings and table rows.

    Returns the text and how many sentences were flagged.
    """
    asked = {_digits(n) for n in _NUMBER.findall(question)}
    skip = example_ranges(text)
    out: list[str] = []
    flagged = 0
    offset = 0
    for line in text.splitlines(keepends=True):
        start = offset
        offset += len(line)
        body = line.rstrip("\r\n")
        ending = line[len(body):]
        if (
            not body.strip()
            or _HEADING.match(body)
            or body.lstrip().startswith("|")
            or "=" in body
            or any(s <= start < e for s, e in skip)
        ):
            out.append(line)
            continue
        if _TALLY_LINE.match(body):
            # "AGI: $78,000" in a worked calculation is derived, not a claim.
            out.append(line)
            continue
        sentences = _merge_abbreviations(_SENTENCE_END.split(body))
        rebuilt: list[str] = []
        for sentence in sentences:
            numbers = {_digits(n) for n in _NUMBER.findall(sentence)}
            if (
                FIGURE.search(sentence)
                and not _CITED.search(sentence)
                and UNSOURCED not in sentence
                and not numbers <= asked
            ):
                sentence = sentence.rstrip() + " " + UNSOURCED
                flagged += 1
            rebuilt.append(sentence)
        out.append(" ".join(rebuilt) + ending)
    return "".join(out), flagged


def _digits(number: str) -> str:
    return number.replace(",", "")


#: A full stop that ends an abbreviation, not a sentence: "U.S.", "v.",
#: "Rev. Proc.", "No.", "e.g.".
_ABBREVIATION = re.compile(
    r"(?:\b[A-Z]\.){1,3}$|\b(?:v|vs|No|Nos|Inc|Co|Corp|Rev|Proc|Rul|Reg|Regs|Sec|St|Pub|Ct|"
    r"Cir|Mr|Mrs|Ms|Dr|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|e\.g|i\.e|etc|approx)\.$"
)
#: A list line that is only "label: figure", as in a worked calculation.
_TALLY_LINE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+[^:\n]{1,80}:[ \t]*[−-]?[ \t]*\$?[\d,.]+%?[ \t]*$")


def _merge_abbreviations(parts: list[str]) -> list[str]:
    merged: list[str] = []
    for part in parts:
        if merged and _ABBREVIATION.search(merged[-1].rstrip()):
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged


# ---------------------------------------------------------------------------


def _join_years(years: list[str]) -> str:
    unique = sorted(set(years))
    return " and ".join(unique)


def _sections(text: str, title: re.Pattern[str]) -> list[tuple[int, int]]:
    """(start, end) of each section whose heading text matches ``title``.

    A section runs to the next heading of the same or a higher level.
    """
    headings = list(_HEADING.finditer(text))
    ranges: list[tuple[int, int]] = []
    for index, heading in enumerate(headings):
        name = heading.group(2).strip().strip("*_ ").strip()
        if not title.match(name):
            continue
        level = len(heading.group(1))
        end = len(text)
        for later in headings[index + 1 :]:
            if len(later.group(1)) <= level:
                end = later.start()
                break
        ranges.append((heading.start(), end))
    return ranges


def _drop_sections(text: str, title: re.Pattern[str]) -> str:
    for start, end in reversed(_sections(text, title)):
        text = text[:start] + text[end:]
    return text
