"""Render a computed return into whatever shape a tax package imports.

One adapter, many maps. Adding a vendor means adding a JSON file to
``resources/export_maps`` — a target name, an output format, and a
``fact key -> vendor field`` table over the vocabulary in ``fact_set``. No
Python changes, no second pass over ``Return1040``, and no tax logic: every
figure written here was computed and checked upstream.

This mirrors ``schedule_filler``, which drives the IRS PDFs from derived
``*_map.json`` files for the same reason — a mapping expressed as data can be
diffed, reviewed by an accountant, and corrected without a deploy.

SECURITY: the rendered file contains real taxpayer identity. It is an
output-zone artifact: written to disk, role-gated on download, audited, and
never transmitted. This module deliberately has no HTTP client. Pushing an
export to a vendor API would be a new outbound path carrying full PII and is a
policy decision, not a refactor — see ``CLAUDE.md``, "The four zones".

Validation fails closed. A map naming a fact key that does not exist, or two
keys landing on one vendor field, is rejected at load rather than silently
writing a blank or the wrong figure into a return someone files.
"""

from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.core.errors import ExportMapError
from app.core.logging import get_logger
from app.services.export.fact_set import (
    EXPORT_FACT_KEYS,
    FACT_SET_VERSION,
    ReturnFactSet,
    vocabulary,
)

logger = get_logger(__name__)

MAPS_DIR = Path(__file__).resolve().parent.parent.parent / "resources" / "export_maps"

#: Layout of the map file itself — bumped when a map gains or loses a
#: top-level key. Distinct from ``FACT_SET_VERSION``, which versions the
#: vocabulary a map's ``fields`` may reference; a map can fall out of step
#: with either one independently.
MAP_SCHEMA_VERSION = 1

SUPPORTED_FORMATS = frozenset({"csv", "json", "xml"})

#: "exact" keeps the engine's own Decimal ("11221.98"). "whole_dollars" rounds
#: the way the IRS instructions permit and the prepared returns in the corpus
#: use. Neither ever emits thousands separators or parentheses: those are
#: presentation, and an import parser reads them as text.
MONEY_FORMATS = frozenset({"exact", "whole_dollars"})

CONTENT_TYPES = {
    "csv": "text/csv",
    "json": "application/json",
    "xml": "application/xml",
}

#: XML element names are constrained by the spec; a vendor field that is not a
#: legal name would produce a file no parser accepts.
_XML_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")

#: Filenames end up in shell history and backup indexes, so keep them plain.
_UNSAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9 ._-]+")


@dataclass(frozen=True, slots=True)
class ExportFile:
    """One rendered import file, ready for the output zone."""

    target: str
    label: str
    filename: str
    content: bytes
    content_type: str
    #: Vendor fields that received a value.
    fields_written: tuple[str, ...]
    #: Mapped fact keys this return did not state. Normal — a return without
    #: rental income has no line for it — but worth reporting, because a long
    #: list usually means the map was written against a different fact set.
    facts_absent: tuple[str, ...]


class ExportMap:
    """One vendor's field map, loaded and validated from JSON."""

    def __init__(self, data: dict[str, Any], *, source: str) -> None:
        self._source = source
        self.schema_version = data.get("schema_version")
        self.fact_set_version = data.get("fact_set_version")
        self.target = str(data.get("target") or "").strip()
        self.label = str(data.get("label") or self.target).strip()
        self.format = str(data.get("format") or "").strip().lower()
        self.extension = str(data.get("extension") or self.format).strip().lstrip(".")
        self.money = str(data.get("money") or "exact").strip().lower()
        self.xml_root = str(data.get("xml_root") or "TaxReturnExport").strip()
        self.xml_record = str(data.get("xml_record") or "Return").strip()
        self.fields = self._resolve_fields(data.get("fields"))
        self._validate()

    @staticmethod
    def _resolve_fields(raw: Any) -> dict[str, str]:
        """The ``fact key -> vendor field`` table.

        Omitted means "every fact, named as we name it" — the honest default
        for a target whose real format is not known yet. Spelling the whole
        vocabulary out in JSON would be a second list to keep in step with the
        engine, which is the drift this package exists to prevent.
        """
        if raw is None:
            return {key: key for key in vocabulary()}
        if not isinstance(raw, dict):
            raise ExportMapError("'fields' must be an object of fact key -> field")
        return {str(k): str(v) for k, v in raw.items()}

    def _validate(self) -> None:
        if self.schema_version != MAP_SCHEMA_VERSION:
            raise ExportMapError(
                f"map schema version {self.schema_version!r} is not "
                f"{MAP_SCHEMA_VERSION}"
            )
        if self.fact_set_version != FACT_SET_VERSION:
            raise ExportMapError(
                f"map targets fact set version {self.fact_set_version!r}, "
                f"this build produces {FACT_SET_VERSION}"
            )
        if not self.target:
            raise ExportMapError("map has no 'target'")
        if self.format not in SUPPORTED_FORMATS:
            raise ExportMapError(
                f"unsupported format {self.format!r}; "
                f"expected one of {sorted(SUPPORTED_FORMATS)}"
            )
        if self.money not in MONEY_FORMATS:
            raise ExportMapError(
                f"unsupported money format {self.money!r}; "
                f"expected one of {sorted(MONEY_FORMATS)}"
            )
        if not self.fields:
            raise ExportMapError("map has no fields")

        # SECURITY-adjacent correctness: a typo here writes a blank into a
        # return someone files, so it is an error and not a warning.
        unknown = sorted(set(self.fields) - EXPORT_FACT_KEYS)
        if unknown:
            raise ExportMapError(
                f"map references {len(unknown)} unknown fact key(s): "
                f"{', '.join(unknown[:10])}"
            )

        # Two facts on one vendor field means one of them is silently lost.
        seen: dict[str, str] = {}
        for fact_key, target_field in self.fields.items():
            if not target_field:
                raise ExportMapError(f"{fact_key!r} maps to an empty field name")
            if target_field in seen:
                raise ExportMapError(
                    f"{target_field!r} is mapped from both {seen[target_field]!r} "
                    f"and {fact_key!r}"
                )
            seen[target_field] = fact_key

        if self.format == "xml":
            for name in (self.xml_root, self.xml_record, *self.fields.values()):
                if not _XML_NAME_RE.match(name):
                    raise ExportMapError(f"{name!r} is not a valid XML element name")

    # ------------------------------------------------------------- rendering

    def _amount(self, raw: str) -> str:
        if self.money == "exact":
            return raw
        try:
            value = Decimal(raw)
        except (InvalidOperation, ValueError):
            # Not a number after all — a mis-declared money key. Pass the text
            # through rather than dropping the field.
            logger.warning("%s: %r is not an amount; written as text", self.target, raw)
            return raw
        return str(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))

    def _pairs(self, fact_set: ReturnFactSet) -> tuple[list[tuple[str, str]], list[str]]:
        """Vendor field / value pairs in map order, plus the facts not stated."""
        pairs: list[tuple[str, str]] = []
        absent: list[str] = []
        for fact_key, target_field in self.fields.items():
            raw = fact_set.get(fact_key)
            if raw is None:
                absent.append(fact_key)
                continue
            if fact_key in fact_set.money_keys:
                raw = self._amount(raw)
            pairs.append((target_field, raw))
        return pairs, absent

    def render(self, fact_set: ReturnFactSet) -> ExportFile:
        pairs, absent = self._pairs(fact_set)
        if self.format == "csv":
            content = self._render_csv(pairs)
        elif self.format == "json":
            content = self._render_json(pairs, fact_set)
        else:
            content = self._render_xml(pairs)

        safe_label = _UNSAFE_FILENAME_RE.sub("", self.label).strip() or self.target
        return ExportFile(
            target=self.target,
            label=self.label,
            filename=f"8 - Import - {safe_label} ({fact_set.tax_year}).{self.extension}",
            content=content,
            content_type=CONTENT_TYPES[self.format],
            fields_written=tuple(field for field, _ in pairs),
            facts_absent=tuple(absent),
        )

    def _render_csv(self, pairs: list[tuple[str, str]]) -> bytes:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["field", "value"])
        writer.writerows(pairs)
        return buffer.getvalue().encode("utf-8")

    def _render_json(
        self, pairs: list[tuple[str, str]], fact_set: ReturnFactSet
    ) -> bytes:
        document = {
            "target": self.target,
            "fact_set_version": fact_set.version,
            "tax_year": fact_set.tax_year,
            "fields": dict(pairs),
        }
        return json.dumps(document, indent=2).encode("utf-8")

    def _render_xml(self, pairs: list[tuple[str, str]]) -> bytes:
        root = ET.Element(self.xml_root, attrib={"version": str(FACT_SET_VERSION)})
        record = ET.SubElement(root, self.xml_record)
        for name, value in pairs:
            ET.SubElement(record, name).text = value
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def load_maps(directory: Path | None = None) -> list[ExportMap]:
    """Every valid map on disk, sorted by target.

    A malformed map is logged and skipped rather than raised: one bad vendor
    file must not cost the preparer the rest of the package, which is how
    ``_build_schedules`` treats a form that will not render.
    """
    directory = directory or MAPS_DIR
    if not directory.is_dir():
        return []

    maps: list[ExportMap] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            maps.append(ExportMap(data, source=path.name))
        except (ExportMapError, json.JSONDecodeError, OSError) as exc:
            logger.error("Export map %s not loaded: %s", path.name, exc)
    return sorted(maps, key=lambda m: m.target)


def render_exports(
    fact_set: ReturnFactSet,
    *,
    targets: set[str] | None = None,
    directory: Path | None = None,
) -> list[ExportFile]:
    """Render every configured target, or just the ones named."""
    files: list[ExportFile] = []
    for export_map in load_maps(directory):
        if targets is not None and export_map.target not in targets:
            continue
        try:
            rendered = export_map.render(fact_set)
        except Exception as exc:  # noqa: BLE001 - one target must not sink the rest
            logger.error(
                "Export target %s not rendered: %s", export_map.target, type(exc).__name__
            )
            continue
        logger.info(
            "Export %s: %d field(s) written, %d fact(s) not stated by this return",
            rendered.target,
            len(rendered.fields_written),
            len(rendered.facts_absent),
        )
        files.append(rendered)
    return files
