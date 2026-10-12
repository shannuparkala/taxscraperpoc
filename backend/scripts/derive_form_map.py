"""Derive a line-number -> AcroForm field map from a blank IRS PDF.

IRS forms print the line number immediately to the left of the amount box it
labels: "5 Rental real estate ... Attach Schedule E . . . . . 5". Reading that
trailing token off each widget's row gives the mapping without a human squinting
at field names, which is how ``form_1040_filler`` was built and where two
mistakes crept in.

    cd backend && python -m scripts.derive_form_map app/resources/f1040s1_2025.pdf

The output is a starting point, not gospel. A derived map still needs a human to
confirm the handful of rows where the trailing token is ambiguous — the script
marks those rather than guessing, because a silently wrong map produces a form
that looks official and puts a number on the wrong line.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import fitz

#: A line label: 1, 2a, 8z, 24h. Anchored so "1040" and "2025" cannot match.
LINE_TOKEN = re.compile(r"^(\d{1,2}[a-z]?|[a-z])$")

#: Tokens that trail an amount box without labelling it.
NOISE = {"(", ")", ".", "$", "•", "|", "%"}


def row_before(page: fitz.Page, rect: fitz.Rect, words: list[Any]) -> list[str]:
    """Words on the widget's row, left of it, in reading order."""
    mid = (rect.y0 + rect.y1) / 2
    same = [w for w in words if w[1] - 3 <= mid <= w[3] + 3 and w[2] <= rect.x0 + 2]
    same.sort(key=lambda w: w[0])
    return [w[4] for w in same]


def line_for(tokens: list[str]) -> str | None:
    """The line number this box belongs to: the last label-shaped token."""
    for token in reversed(tokens):
        cleaned = token.strip("".join(NOISE)).strip()
        if not cleaned:
            continue
        if LINE_TOKEN.match(cleaned):
            return cleaned
        # A non-label word means we have walked past the label into prose.
        return None
    return None


def derive(path: Path) -> dict[str, Any]:
    document = fitz.open(path)
    mapping: dict[str, str] = {}
    ambiguous: list[dict[str, str]] = []
    collisions: dict[str, list[str]] = {}

    for page_number, page in enumerate(document):
        words = page.get_text("words")
        for widget in page.widgets():
            if widget.field_type_string != "Text":
                continue
            field = widget.field_name.split(".")[-1]
            tokens = row_before(page, widget.rect, words)
            line = line_for(tokens)
            row = " ".join(tokens)[-90:]

            if line is None:
                ambiguous.append({"field": field, "page": page_number, "row": row})
                continue
            if line in mapping:
                # Several boxes share a label on multi-column rows (Schedule D's
                # proceeds / cost / adjustment columns all sit on line "1b").
                collisions.setdefault(line, [mapping[line]]).append(field)
                continue
            mapping[line] = field

    return {
        "template": path.name,
        "form_title": document[0].get_text()[:80].strip().replace("\n", " "),
        "pages": len(document),
        "line_to_field": dict(sorted(mapping.items(), key=_line_sort)),
        "needs_review": {
            "multi_box_lines": {k: v for k, v in sorted(collisions.items())},
            "unlabelled_fields": ambiguous,
        },
    }


def _line_sort(item: tuple[str, str]) -> tuple[int, str]:
    match = re.match(r"^(\d+)", item[0])
    return (int(match.group(1)) if match else 999, item[0])


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)

    for arg in sys.argv[1:]:
        path = Path(arg)
        result = derive(path)
        out = path.parent / f"{path.stem}_map.json"
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        mapped = len(result["line_to_field"])
        multi = len(result["needs_review"]["multi_box_lines"])
        unlabelled = len(result["needs_review"]["unlabelled_fields"])
        print(
            f"{path.name:<26} {mapped:>3} lines mapped, "
            f"{multi} multi-box, {unlabelled} unlabelled  -> {out.name}"
        )


if __name__ == "__main__":
    main()
