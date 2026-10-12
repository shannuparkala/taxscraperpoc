"""Text, layout, and table extraction from documents.

Strategy, in order of preference:

1. **Embedded text layer** (PyMuPDF) — free, exact, no OCR error. Used whenever
   a page carries enough real text.
2. **Local OCR** (Tesseract via pytesseract) — for scanned pages. Runs on this
   host; the image never leaves.
3. **Blocked** — if neither is available the page is marked
   ``OCR_UNAVAILABLE`` and routed to a human.

SECURITY: there is deliberately no automatic cloud-OCR path. A scanned page
cannot be masked before it is read, so sending the image to a multimodal model
would hand a third party the unredacted document — precisely what this platform
exists to prevent. ``ALLOW_CLOUD_OCR_FALLBACK`` exists for operators who accept
that trade-off explicitly; it defaults to off, config refuses it in production
without review, and every use raises a CRITICAL audit event.

The real-world corpus that motivated this design is scanned tax organizers:
in a representative 37-page workpaper, 27 pages had no text layer at all.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT, Settings, get_settings
from app.core.errors import OcrUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)


class ExtractionMethod(str, Enum):
    TEXT_LAYER = "text_layer"
    OCR_TESSERACT = "ocr_tesseract"
    OCR_CLOUD = "ocr_cloud"
    NONE = "none"


#: A page with fewer than this many characters of embedded text is treated as
#: scanned. Tax forms are dense; a genuine text page clears this easily, while
#: a scan yields only stray artifacts from the imaging software.
_TEXT_LAYER_MIN_CHARS = 60

#: Below this ratio of alphanumeric characters the "text" is layout garbage.
_MIN_ALNUM_RATIO = 0.35

#: --- Overlay detection -----------------------------------------------------
#:
#: A character count answers "is there text on this page?" when the question is
#: "does this text layer cover the page?". They come apart on a scanned form
#: carrying a *partial* overlay: imaging software indexes the client's name,
#: SSN and address and leaves every dollar figure in the raster.
#:
#: Measured on Basic 5 Workpapers.pdf, 37 pages: nine pages carried 71-287
#: characters of pure identity over a full-page image, cleared the 60-character
#: bar, were scored at perfect confidence and skipped OCR. Those nine pages hold
#: 90 money-shaped values between them and their text layer supplied none — 44%
#: of the document's figures, including both W-2s. The pipeline computed an AGI
#: of -75 against a prepared 92,758 and raised one review item.
#:
#: So the test is coverage, not presence: if a page is mostly raster and its
#: text layer occupies a sliver of the page, the layer is an index of the image,
#: not a transcription of it, and the page must be read by OCR. On the failing
#: pages the text occupied 0.70%-3.07% of the page against ~100% image; a
#: genuinely digital form runs an order of magnitude higher.
_IMAGE_AREA_DOMINANT = 0.50
_TEXT_AREA_MIN_RATIO = 0.05

#: Tesseract page-segmentation modes, in the order they are tried.
#:
#: Mode 3 (fully automatic) is the primary. Mode 6 ("assume a single uniform
#: block of text") was the original choice and is wrong for tax forms, which are
#: sparse boxed layouts rather than prose: on a mostly-empty organizer page it
#: invents rows of noise, scoring 0.29 where mode 3 scores 0.93 on the same
#: page. Mode 6 is kept as a fallback because it does still win on dense ruled
#: schedules, where mode 3 discards about half the cells.
#:
#: Modes 4 and 11 were measured and rejected: 11 scores well only because it
#: extracts a sixth of the text, and 4 returned zero words on some pages.
_OCR_PRIMARY_PSM = 3
_OCR_FALLBACK_PSM = 6

#: A fallback pass must retain at least this share of the primary pass's words
#: before its confidence is allowed to win. Without it the "better" variant is
#: whichever one dropped the most content — high confidence about a page you
#: only read a sixth of is not an improvement, and a number that never made it
#: out of OCR cannot be flagged for review the way a misread one can.
_MIN_WORD_RETENTION = 0.60


@dataclass(slots=True)
class Word:
    """One recognised word with position and confidence."""

    text: str
    bbox: tuple[float, float, float, float]
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "bbox": list(self.bbox),
            "confidence": round(self.confidence, 3),
        }


@dataclass(slots=True)
class Table:
    """A detected table as a grid of cell strings."""

    rows: list[list[str]]
    bbox: tuple[float, float, float, float] | None = None
    page_number: int = 1

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self.rows), max((len(r) for r in self.rows), default=0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "bbox": list(self.bbox) if self.bbox else None,
            "page": self.page_number,
            "shape": list(self.shape),
        }


@dataclass(slots=True)
class PageExtraction:
    """Everything extracted from one page."""

    page_number: int
    text: str
    method: ExtractionMethod
    width: float = 0.0
    height: float = 0.0
    rotation: int = 0
    words: list[Word] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    mean_confidence: float = 1.0
    is_scanned: bool = False
    has_handwriting_hint: bool = False
    #: Clockwise degrees the page image had to be turned to read it. Non-zero
    #: means the scan was sideways or upside down; word boxes are mapped back
    #: to the original page, so this is reporting only.
    rotation_applied: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return (
            self.method is ExtractionMethod.NONE
            or self.mean_confidence < get_settings().ocr_min_confidence / 100.0
            or self.has_handwriting_hint
        )

    def to_layout_dict(self) -> dict[str, Any]:
        """Layout summary. SECURITY: callers must mask ``text``/``tables`` first."""
        return {
            "page": self.page_number,
            "method": self.method.value,
            "width": round(self.width, 2),
            "height": round(self.height, 2),
            "rotation": self.rotation,
            "rotation_applied": self.rotation_applied,
            "word_count": len(self.words),
            "table_count": len(self.tables),
            "mean_confidence": round(self.mean_confidence, 3),
            "is_scanned": self.is_scanned,
            "handwriting_hint": self.has_handwriting_hint,
            "warnings": self.warnings,
        }


@dataclass(slots=True)
class DocumentExtraction:
    """Result of extracting a whole file."""

    pages: list[PageExtraction] = field(default_factory=list)
    engine: str = "none"
    ocr_available: bool = False
    blocked_pages: list[int] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(
            f"<<<PAGE {p.page_number}>>>\n{p.text}" for p in self.pages if p.text
        )

    @property
    def page_texts(self) -> list[str]:
        return [p.text for p in self.pages]

    @property
    def mean_confidence(self) -> float:
        """Mean confidence over **every** page, counting unread pages as zero.

        This deliberately does not skip pages that produced no text. Averaging
        only over pages that happened to work let a 37-page workpaper whose 28
        scanned pages were unreadable report 1.0 — the 9 pages carrying a thin
        identity overlay each scored 1.0, so the document claimed full
        confidence while three quarters of it had never been read, and the
        pipeline went on to compute a return from it. Confidence has to describe
        the document, not the subset that succeeded.
        """
        if not self.pages:
            return 0.0
        return sum(p.mean_confidence for p in self.pages) / len(self.pages)

    @property
    def coverage(self) -> float:
        """Fraction of pages that yielded any text at all.

        Reported separately from confidence because they fail differently: a
        page can be read badly (low confidence) or not at all (low coverage),
        and only the second means the content is simply absent downstream.
        """
        if not self.pages:
            return 0.0
        return sum(1 for p in self.pages if p.text.strip()) / len(self.pages)

    @property
    def scanned_page_count(self) -> int:
        return sum(1 for p in self.pages if p.is_scanned)

    @property
    def low_confidence_pages(self) -> list[int]:
        """Pages read below the configured acceptance threshold."""
        floor = get_settings().ocr_min_confidence / 100.0
        return [
            p.page_number
            for p in self.pages
            if p.text.strip() and p.mean_confidence < floor
        ]

    def summary(self) -> dict[str, Any]:
        """Audit-safe. SECURITY: counters only, no page content."""
        return {
            "page_count": len(self.pages),
            "scanned_pages": self.scanned_page_count,
            "blocked_pages": self.blocked_pages,
            "low_confidence_pages": self.low_confidence_pages,
            "engine": self.engine,
            "ocr_available": self.ocr_available,
            "mean_confidence": round(self.mean_confidence, 3),
            "coverage": round(self.coverage, 3),
            "tables": sum(len(p.tables) for p in self.pages),
        }


class OcrService:
    """Extracts text and layout, preferring the embedded text layer."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._tesseract_checked = False
        self._tesseract_path: str | None = None

    # ------------------------------------------------------- engine probing

    @property
    def tesseract_available(self) -> bool:
        """True when a usable ``tesseract`` binary is on this host."""
        if self._tesseract_checked:
            return self._tesseract_path is not None

        self._tesseract_checked = True
        configured = self._settings.tesseract_cmd.strip()
        candidate = configured or shutil.which("tesseract")

        if not candidate:
            # Common Windows install locations, since winget does not always
            # add Tesseract to PATH. The UB-Mannheim package installs per-user
            # under LOCALAPPDATA when winget runs unelevated — which is the
            # default, and what the README's install command actually does — so
            # checking only the Program Files paths misses the documented
            # install and silently disables OCR for the whole pipeline.
            guesses = [
                # A copy vendored into the repo wins: on hosts where an
                # Application Control policy blocks executables under the user
                # profile, this is the only location that actually runs.
                str(PROJECT_ROOT / "Tesseract-OCR" / "tesseract.exe"),
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            ]
            local_appdata = os.environ.get("LOCALAPPDATA", "")
            if local_appdata:
                guesses.append(
                    str(Path(local_appdata) / "Programs" / "Tesseract-OCR" / "tesseract.exe")
                )
            for guess in guesses:
                if Path(guess).exists():
                    candidate = guess
                    break

        if not candidate or not Path(candidate).exists():
            logger.warning(
                "Tesseract not found. Scanned pages cannot be read locally and "
                "will be routed to human review. Install it with: "
                "winget install --id UB-Mannheim.TesseractOCR "
                "then set TESSERACT_CMD."
            )
            return False

        try:
            import pytesseract

            pytesseract.pytesseract.tesseract_cmd = candidate
            version = pytesseract.get_tesseract_version()
            self._tesseract_path = candidate
            logger.info("Tesseract %s available at %s", version, candidate)
            return True
        except Exception as exc:  # pragma: no cover - host dependent
            logger.warning(
                "Tesseract at %s is not usable (%s); scanned pages will be "
                "routed to human review.",
                candidate,
                type(exc).__name__,
            )
            return False

    # ------------------------------------------------------------------ API

    def extract(self, path: Path | str) -> DocumentExtraction:
        """Extract from any supported file type."""
        path = Path(path)
        suffix = path.suffix.lower()

        if suffix == ".pdf":
            return self.extract_pdf(path)
        if suffix in {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}:
            return self.extract_image(path)
        if suffix == ".docx":
            return self.extract_docx(path)
        if suffix in {".xlsx", ".xls"}:
            return self.extract_spreadsheet(path)
        if suffix in {".csv", ".txt"}:
            return self.extract_plaintext(path)

        raise OcrUnavailableError(f"No extractor is registered for '{suffix}'.")

    # ------------------------------------------------------------------ PDF

    def extract_pdf(self, path: Path) -> DocumentExtraction:
        import fitz  # PyMuPDF

        result = DocumentExtraction(ocr_available=self.tesseract_available)
        engines: set[str] = set()

        with fitz.open(path) as doc:
            for index, page in enumerate(doc, start=1):
                extraction = self._extract_pdf_page(page, index)
                engines.add(extraction.method.value)
                if extraction.method is ExtractionMethod.NONE:
                    result.blocked_pages.append(index)
                result.pages.append(extraction)

        result.engine = "+".join(sorted(e for e in engines if e != "none")) or "none"

        if result.blocked_pages:
            logger.warning(
                "%d of %d pages could not be read (no text layer, no local OCR)",
                len(result.blocked_pages),
                len(result.pages),
            )
        return result

    def _extract_pdf_page(self, page: Any, page_number: int) -> PageExtraction:
        import fitz

        rect = page.rect
        extraction = PageExtraction(
            page_number=page_number,
            text="",
            method=ExtractionMethod.NONE,
            width=float(rect.width),
            height=float(rect.height),
            rotation=int(getattr(page, "rotation", 0) or 0),
            # Starts at zero: a page we have not read yet is a page we have no
            # confidence in. Each success path below sets its own value, so
            # anything that falls through to a return keeps 0.0 rather than
            # inheriting the dataclass default of 1.0 and reporting a page that
            # was never read as perfectly read.
            mean_confidence=0.0,
        )

        # --- 1. Embedded text layer -------------------------------------
        # Accepted only when it actually covers the page. A partial overlay
        # scores 1.0 confidence on content it never transcribed, which is worse
        # than no text layer at all: no text layer routes the page to OCR,
        # while a partial one silently skips it.
        raw_text = page.get_text("text") or ""
        if self._is_usable_text(raw_text) and not self._is_partial_overlay(page):
            extraction.text = raw_text
            extraction.method = ExtractionMethod.TEXT_LAYER
            extraction.mean_confidence = 1.0
            extraction.words = self._words_from_text_layer(page)
            extraction.tables = self._tables_from_page(page, page_number)
            return extraction

        # --- 2. Local OCR -----------------------------------------------
        extraction.is_scanned = True
        if not self.tesseract_available:
            extraction.warnings.append(
                "No text layer and no local OCR engine; routed to human review."
            )
            return extraction

        try:
            # Render at configured DPI. The pixmap stays in memory on this host.
            zoom = self._settings.ocr_dpi / 72.0
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            image_bytes = pixmap.tobytes("png")
            floor = self._settings.ocr_min_confidence / 100.0

            page_size = (extraction.width, extraction.height)
            ocr = self._run_tesseract(
                image_bytes, scale=1.0 / zoom, psm=_OCR_PRIMARY_PSM
            )

            # A page that scores badly is usually not a bad scan — it is a scan
            # the reader is holding the wrong way up. Try orientation first,
            # because it is by far the largest single win: the sample corpus's
            # sideways 1099-B pages go from ~0.40 and zero recognisable amounts
            # to ~0.92 and 165 of them.
            if ocr["mean_confidence"] < floor:
                detected = self._detect_rotation(image_bytes)
                if detected:
                    turned = self._run_tesseract(
                        image_bytes,
                        scale=1.0 / zoom,
                        psm=_OCR_PRIMARY_PSM,
                        rotation=detected,
                        page_size=page_size,
                    )
                    if self._is_better(turned, ocr):
                        ocr = turned

            # Still poor: neither segmentation mode wins everywhere. The primary
            # reads sparse organizer pages far better, the fallback reads dense
            # ruled schedules better, so retry and keep whichever is stronger.
            # Both extra passes only run on pages already below the acceptance
            # threshold, which is where the extra second is worth spending.
            if ocr["mean_confidence"] < floor:
                alternate = self._run_tesseract(
                    image_bytes,
                    scale=1.0 / zoom,
                    psm=_OCR_FALLBACK_PSM,
                    rotation=ocr.get("rotation", 0),
                    page_size=page_size,
                )
                if self._is_better(alternate, ocr):
                    ocr = alternate

            extraction.text = ocr["text"]
            extraction.words = ocr["words"]
            extraction.mean_confidence = ocr["mean_confidence"]
            extraction.method = ExtractionMethod.OCR_TESSERACT
            extraction.rotation_applied = int(ocr.get("rotation", 0))
            extraction.has_handwriting_hint = ocr["handwriting_hint"]
            if extraction.rotation_applied:
                extraction.warnings.append(
                    f"Page was rotated {extraction.rotation_applied}° to read it."
                )
            if ocr["mean_confidence"] < floor:
                extraction.warnings.append(
                    f"Low OCR confidence ({ocr['mean_confidence']:.0%}); "
                    "values from this page need verification."
                )
        except Exception as exc:  # pragma: no cover - host dependent
            logger.warning(
                "OCR failed on page %d: %s", page_number, type(exc).__name__
            )
            extraction.warnings.append("OCR failed; routed to human review.")

        return extraction

    @staticmethod
    def _is_usable_text(text: str) -> bool:
        """Decide whether an embedded text layer is real content."""
        stripped = text.strip()
        if len(stripped) < _TEXT_LAYER_MIN_CHARS:
            return False
        alnum = sum(c.isalnum() for c in stripped)
        return (alnum / len(stripped)) >= _MIN_ALNUM_RATIO

    @staticmethod
    def _is_partial_overlay(page: Any) -> bool:
        """True when the text layer indexes a scan rather than transcribing it.

        Two measurements, both cheap and both taken from the page's own layout
        rather than from its content:

        * how much of the page is covered by raster image blocks, and
        * how much is covered by the bounding boxes of text-layer words.

        A scanned page with an identity overlay is ~100% image and under 5%
        text. A born-digital form is either not image-backed at all, or carries
        a full transcription whose word boxes cover a real share of the page.

        Returning True costs one OCR pass on a page that might not have needed
        it. Returning False wrongly costs every figure on the page, with no
        symptom until the return foots to something impossible — which is the
        asymmetry the whole masking policy is built around.
        """
        try:
            rect = page.rect
            page_area = float(rect.width) * float(rect.height)
            if page_area <= 0:
                return False

            image_area = 0.0
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") == 1:  # 1 is an image block
                    x0, y0, x1, y1 = block["bbox"]
                    image_area += float(x1 - x0) * float(y1 - y0)

            if image_area / page_area < _IMAGE_AREA_DOMINANT:
                return False  # not a scan; trust the layer

            text_area = sum(
                float(w[2] - w[0]) * float(w[3] - w[1]) for w in page.get_text("words")
            )
            return (text_area / page_area) < _TEXT_AREA_MIN_RATIO
        except Exception:  # pragma: no cover - layout parsing is host dependent
            # Unreadable layout is not evidence of a good text layer. Prefer the
            # OCR path, which is merely slower.
            logger.debug("Could not measure text coverage; treating as an overlay")
            return True

    @staticmethod
    def _words_from_text_layer(page: Any) -> list[Word]:
        words: list[Word] = []
        try:
            for x0, y0, x1, y1, text, *_ in page.get_text("words"):
                if text.strip():
                    words.append(
                        Word(text=text, bbox=(x0, y0, x1, y1), confidence=1.0)
                    )
        except Exception:  # pragma: no cover
            pass
        return words

    @staticmethod
    def _tables_from_page(page: Any, page_number: int) -> list[Table]:
        """Detect ruled tables. Present in trial balances and 1099 statements."""
        tables: list[Table] = []
        try:
            finder = page.find_tables()
        except Exception:  # pragma: no cover - PyMuPDF version dependent
            return tables

        for table in getattr(finder, "tables", []):
            try:
                grid = table.extract()
            except Exception:
                continue
            rows = [
                [(cell or "").strip() for cell in row]
                for row in grid
                if any((cell or "").strip() for cell in row)
            ]
            if rows:
                bbox = getattr(table, "bbox", None)
                tables.append(
                    Table(
                        rows=rows,
                        bbox=tuple(bbox) if bbox else None,
                        page_number=page_number,
                    )
                )
        return tables

    # --------------------------------------------------------------- images

    def extract_image(self, path: Path) -> DocumentExtraction:
        result = DocumentExtraction(ocr_available=self.tesseract_available)
        page = PageExtraction(
            page_number=1,
            text="",
            method=ExtractionMethod.NONE,
            is_scanned=True,
            mean_confidence=0.0,  # see _extract_pdf_page
        )

        if not self.tesseract_available:
            page.warnings.append(
                "Image upload requires local OCR; routed to human review."
            )
            result.pages.append(page)
            result.blocked_pages.append(1)
            return result

        try:
            from PIL import Image

            with Image.open(path) as image:
                page.width, page.height = float(image.width), float(image.height)
            ocr = self._run_tesseract(path.read_bytes(), scale=1.0)
            page.text = ocr["text"]
            page.words = ocr["words"]
            page.mean_confidence = ocr["mean_confidence"]
            page.has_handwriting_hint = ocr["handwriting_hint"]
            page.method = ExtractionMethod.OCR_TESSERACT
            result.engine = "ocr_tesseract"
        except Exception as exc:  # pragma: no cover
            logger.warning("Image OCR failed: %s", type(exc).__name__)
            page.warnings.append("OCR failed; routed to human review.")
            result.blocked_pages.append(1)

        result.pages.append(page)
        return result

    # ---------------------------------------------------------- Tesseract

    def _detect_rotation(self, image_bytes: bytes) -> int:
        """Clockwise degrees needed to make this page upright, or 0.

        Scanned workpapers routinely contain sideways pages — a brokerage
        statement fed through the scanner in landscape — and the PDF's own
        ``/Rotate`` says nothing about it, because the *content* is rotated
        rather than the page. Tesseract reads the turned glyphs as noise: in the
        sample corpus, five 1099-B pages scored around 0.40 and yielded not one
        recognisable amount, while the same pages read upright score 0.92 and
        surface 165 of them. Detection is cheap and only runs on pages that
        already scored badly.
        """
        import io

        import pytesseract
        from PIL import Image

        try:
            with Image.open(io.BytesIO(image_bytes)) as image:
                osd = pytesseract.image_to_osd(
                    image.convert("L"), output_type=pytesseract.Output.DICT
                )
            rotation = int(osd.get("rotate", 0)) % 360
            return rotation if rotation in {90, 180, 270} else 0
        except Exception as exc:  # pragma: no cover - OSD is best-effort
            # OSD needs a certain amount of text to work with and raises on
            # near-blank pages. That is not an error worth failing a page over.
            logger.debug("Orientation detection unavailable: %s", type(exc).__name__)
            return 0

    @staticmethod
    def _unrotate_bbox(
        bbox: tuple[float, float, float, float],
        *,
        rotation: int,
        width: float,
        height: float,
    ) -> tuple[float, float, float, float]:
        """Map a box from the rotated image back onto the original page.

        ``width``/``height`` are the *original* page dimensions. Without this,
        the review UI would highlight the wrong region on every rotated page —
        the text would be right and the box pointing somewhere else.
        """
        x0, y0, x1, y1 = bbox
        if rotation == 90:
            # Rotated clockwise 90: original (x, y) -> rotated (height - y, x).
            return (y0, height - x1, y1, height - x0)
        if rotation == 180:
            return (width - x1, height - y1, width - x0, height - y0)
        if rotation == 270:
            return (width - y1, x0, width - y0, x1)
        return bbox

    def _run_tesseract(
        self,
        image_bytes: bytes,
        *,
        scale: float,
        psm: int = _OCR_PRIMARY_PSM,
        rotation: int = 0,
        page_size: tuple[float, float] | None = None,
    ) -> dict[str, Any]:
        """Run OCR and return text, per-word boxes, and confidence.

        ``scale`` converts pixel coordinates back to PDF points so that bounding
        boxes line up with the original page for the review UI's highlight.
        ``psm`` selects the page-segmentation mode; see ``_OCR_PRIMARY_PSM``.
        ``rotation`` turns the image clockwise before reading it, and the
        resulting boxes are mapped back onto the unrotated page.
        """
        import io

        import pytesseract
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as image:
            image = image.convert("L")  # greyscale improves accuracy
            if rotation:
                # PIL rotates counter-clockwise; OSD reports clockwise.
                image = image.rotate(-rotation, expand=True)
            config = f"--oem 3 --psm {psm}"
            data = pytesseract.image_to_data(
                image,
                lang=self._settings.ocr_language,
                config=config,
                output_type=pytesseract.Output.DICT,
            )

        words: list[Word] = []
        confidences: list[float] = []
        lines: dict[tuple[int, int, int], list[str]] = {}

        for i, raw_text in enumerate(data.get("text", [])):
            text = (raw_text or "").strip()
            if not text:
                continue
            try:
                confidence = float(data["conf"][i])
            except (ValueError, TypeError, KeyError):
                confidence = -1.0
            if confidence < 0:
                continue

            x, y = data["left"][i] * scale, data["top"][i] * scale
            w, h = data["width"][i] * scale, data["height"][i] * scale
            bbox = (x, y, x + w, y + h)
            if rotation and page_size is not None:
                bbox = self._unrotate_bbox(
                    bbox,
                    rotation=rotation,
                    width=page_size[0],
                    height=page_size[1],
                )
            words.append(
                Word(
                    text=text,
                    bbox=bbox,
                    confidence=confidence / 100.0,
                )
            )
            confidences.append(confidence / 100.0)

            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(text)

        text = "\n".join(" ".join(parts) for _, parts in sorted(lines.items()))
        mean_confidence = (
            sum(confidences) / len(confidences) if confidences else 0.0
        )

        return {
            "text": text,
            "words": words,
            "mean_confidence": mean_confidence,
            "rotation": rotation,
            # Handwriting reads as many low-confidence words even when the page
            # overall scores acceptably; that pattern is the signal.
            "handwriting_hint": self._looks_handwritten(confidences),
        }

    @staticmethod
    def _is_better(candidate: dict[str, Any], incumbent: dict[str, Any]) -> bool:
        """Whether a second OCR pass genuinely improves on the first.

        Confidence alone is the wrong test. A segmentation mode that reads only
        the cleanest fragment of a page reports high confidence about almost
        nothing — measured on this corpus, one mode scored 0.52 against 0.31 by
        returning a sixth of the words. So a candidate must keep most of the
        incumbent's words before its confidence counts; and if it read
        materially *more* of the page at no cost in confidence, it wins on
        volume, because content that never came out of OCR cannot be flagged for
        review the way a misread value can.
        """
        candidate_words = len(candidate["words"])
        incumbent_words = len(incumbent["words"])

        if incumbent_words and candidate_words < incumbent_words * _MIN_WORD_RETENTION:
            return False
        if (
            candidate_words > incumbent_words
            and candidate["mean_confidence"] >= incumbent["mean_confidence"]
        ):
            return True
        return candidate["mean_confidence"] > incumbent["mean_confidence"]

    @staticmethod
    def _looks_handwritten(confidences: list[float]) -> bool:
        if len(confidences) < 12:
            return False
        low = sum(1 for c in confidences if c < 0.55)
        return (low / len(confidences)) > 0.35

    # ---------------------------------------------------- office / plain

    def extract_docx(self, path: Path) -> DocumentExtraction:
        from docx import Document as DocxDocument

        document = DocxDocument(str(path))
        parts = [p.text for p in document.paragraphs if p.text.strip()]

        tables: list[Table] = []
        for table in document.tables:
            rows = [
                [cell.text.strip() for cell in row.cells] for row in table.rows
            ]
            rows = [r for r in rows if any(r)]
            if rows:
                tables.append(Table(rows=rows, page_number=1))

        page = PageExtraction(
            page_number=1,
            text="\n".join(parts),
            method=ExtractionMethod.TEXT_LAYER,
            tables=tables,
        )
        return DocumentExtraction(pages=[page], engine="docx", ocr_available=True)

    def extract_spreadsheet(self, path: Path) -> DocumentExtraction:
        """Read a workbook, one PageExtraction per worksheet."""
        from openpyxl import load_workbook

        # data_only=True resolves formulas to their cached values, which is what
        # a workpaper reviewer sees and what the tax engine must reconcile.
        workbook = load_workbook(str(path), data_only=True, read_only=True)
        pages: list[PageExtraction] = []

        for index, sheet in enumerate(workbook.worksheets, start=1):
            rows: list[list[str]] = []
            for row in sheet.iter_rows(values_only=True):
                cells = ["" if v is None else str(v) for v in row]
                if any(c.strip() for c in cells):
                    rows.append(cells)

            text_lines = [f"[Sheet: {sheet.title}]"]
            text_lines.extend("\t".join(r) for r in rows)
            pages.append(
                PageExtraction(
                    page_number=index,
                    text="\n".join(text_lines),
                    method=ExtractionMethod.TEXT_LAYER,
                    tables=[Table(rows=rows, page_number=index)] if rows else [],
                )
            )

        workbook.close()
        if not pages:
            pages.append(
                PageExtraction(
                    page_number=1, text="", method=ExtractionMethod.TEXT_LAYER
                )
            )
        return DocumentExtraction(pages=pages, engine="openpyxl", ocr_available=True)

    def extract_plaintext(self, path: Path) -> DocumentExtraction:
        text = path.read_text(encoding="utf-8", errors="replace")
        page = PageExtraction(
            page_number=1, text=text, method=ExtractionMethod.TEXT_LAYER
        )
        return DocumentExtraction(pages=[page], engine="plaintext", ocr_available=True)
