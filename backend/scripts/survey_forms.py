"""Inventory the forms every accountant copy in the dataset actually contains.

The engine has been measured against one return. That is not evidence it
generalises, and this script replaces the assumption with a count: across every
prepared return in ``Files/``, which forms does a real preparer produce, and how
often? Only the top band of each page is read, because that is where a form
prints its own title.

    cd backend && python -m scripts.survey_forms
"""

from __future__ import annotations

import io
import json
import re
from collections import Counter
from pathlib import Path

import fitz
import pytesseract
from PIL import Image

from app.core.config import get_settings

ROOT = Path(__file__).resolve().parents[2]
FILES = ROOT / "Files"
OUT = ROOT / "data" / "learning" / "FormCoverageSurvey.json"
#: A form prints its own identity in the top-left corner. Cross-references to
#: other forms ("Qualified business income deduction from Form 8995") live in
#: body text further right and further down. Reading the whole header band
#: counted every 1040 as also containing Schedule A, Schedule D and Form 8995,
#: because the 1040 names them on its own face.
CORNER_WIDTH = 0.34
CORNER_HEIGHT = 0.10

#: OCR confusions seen in these scans: "51 040" for 1040, "L203" for 7203,
#: "62 5 1" for 6251. Applied only inside mostly-numeric tokens.
_CONFUSIONS = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5",
                             "B": "8", "Z": "2", "G": "6", "L": "7"})

FORMS: list[tuple[str, str]] = [
    ("Form 1040", r"1040\b"), ("Schedule 1-A", r"SCHEDULE\s*1-?A"),
    ("Schedule 1", r"SCHEDULE\s*1\b"), ("Schedule 2", r"SCHEDULE\s*2\b"),
    ("Schedule 3", r"SCHEDULE\s*3\b"), ("Schedule A", r"SCHEDULE\s*A\b"),
    ("Schedule B", r"SCHEDULE\s*B\b"), ("Schedule C", r"SCHEDULE\s*C\b"),
    ("Schedule D", r"SCHEDULE\s*D\b"), ("Schedule E", r"SCHEDULE\s*E\b"),
    ("Schedule F", r"SCHEDULE\s*F\b"), ("Schedule SE", r"SCHEDULE\s*SE\b"),
    ("Form 8949", r"\b8949\b"), ("Form 8995", r"\b8995"),
    ("Form 6251", r"\b6251\b"), ("Form 8582", r"\b8582\b"),
    ("Form 8801", r"\b8801\b"), ("Form 1116", r"\b1116\b"),
    ("Form 8960", r"\b8960\b"), ("Form 8959", r"\b8959\b"),
    ("Form 4562", r"\b4562\b"), ("Form 4797", r"\b4797\b"),
    ("Form 7203", r"\b7203\b"), ("Form 8812", r"\b8812\b"),
    ("Form 2210", r"\b2210\b"), ("Form 8283", r"\b8283\b"),
    ("Form 8889", r"\b8889\b"), ("Form 5329", r"\b5329\b"),
    ("Form 8606", r"\b8606\b"), ("Form 2441", r"\b2441\b"),
    ("Form 3800", r"\b3800\b"), ("Form 8863", r"\b8863\b"),
]
STATES: list[tuple[str, str]] = [
    ("CA", r"California|Form\s*540|\bFTB\b"), ("NY", r"New York|IT-201"),
    ("IL", r"Illinois|IL-1040"), ("WI", r"Wisconsin"),
    ("CO", r"Colorado|DR\s*0104"), ("VA", r"Virginia"),
    ("MN", r"Minnesota"), ("AZ", r"Arizona"), ("NJ", r"New Jersey"),
    ("GA", r"Georgia"), ("MA", r"Massachusetts"), ("OH", r"Ohio"),
]
FORM_RE = [(n, re.compile(p, re.IGNORECASE)) for n, p in FORMS]
STATE_RE = [(n, re.compile(p, re.IGNORECASE)) for n, p in STATES]


def _normalise(text: str) -> str:
    """Collapse OCR noise so a form number survives being misread."""
    out = []
    for token in text.split():
        digits = sum(c.isdigit() for c in token)
        if digits and digits >= len(token) - 2:
            token = token.translate(_CONFUSIONS)
        out.append(token)
    joined = " ".join(out)
    # "51 040" and "62 5 1" only become findable once the spaces inside a
    # broken number are closed up.
    return re.sub(r"(?<=\d)\s+(?=\d)", "", joined)


def corner_text(page: fitz.Page) -> str:
    box = fitz.Rect(0, 0, page.rect.width * CORNER_WIDTH,
                    page.rect.height * CORNER_HEIGHT)
    text = page.get_text(clip=box).strip()
    if len(text) <= 12:
        pixmap = page.get_pixmap(dpi=220, clip=box)
        try:
            text = pytesseract.image_to_string(
                Image.open(io.BytesIO(pixmap.tobytes("png")))
            )
        except Exception:  # noqa: BLE001 - a page that will not read is not fatal
            return ""
    return _normalise(" ".join(text.split()))


def survey(path: Path) -> dict[str, object]:
    document = fitz.open(path)
    forms: Counter[str] = Counter()
    states: Counter[str] = Counter()
    unread = 0
    for page in document:
        text = corner_text(page)
        if not text.strip():
            unread += 1
            continue
        for name, pattern in FORM_RE:
            if pattern.search(text):
                forms[name] += 1
        for code, pattern in STATE_RE:
            if pattern.search(text):
                states[code] += 1
    return {
        "pages": len(document),
        "pages_unread": unread,
        "forms": dict(forms.most_common()),
        "states": dict(states.most_common()),
    }


def main() -> None:
    settings = get_settings()
    if getattr(settings, "tesseract_cmd", None):
        pytesseract.pytesseract.tesseract_cmd = str(settings.tesseract_cmd)

    targets = sorted(
        p for p in FILES.glob("*.pdf")
        if "acc" in p.name.lower() or "acntnt" in p.name.lower()
    )
    results: dict[str, object] = {}
    frequency: Counter[str] = Counter()
    for path in targets:
        print(f"  {path.name} ...", flush=True)
        result = survey(path)
        results[path.name] = result
        for name in result["forms"]:  # type: ignore[union-attr]
            frequency[name] += 1

    payload = {
        "description": (
            "Forms appearing in each accountant-prepared return, counted by how "
            "many of the returns contain them."
        ),
        "returns_surveyed": len(targets),
        "form_frequency": dict(frequency.most_common()),
        "states_seen": sorted(
            {c for r in results.values() for c in r["states"]}  # type: ignore[index]
        ),
        "per_return": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\n{len(targets)} returns surveyed -> {OUT.name}\n")
    print(f"{'form':<16}{'in N of ' + str(len(targets)):>12}")
    for name, count in frequency.most_common():
        print(f"{name:<16}{count:>12}")
    print(f"\nstates seen: {payload['states_seen']}")


if __name__ == "__main__":
    main()
