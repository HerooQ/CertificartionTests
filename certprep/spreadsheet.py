"""Minimal spreadsheet reader (``.xlsx`` / ``.csv`` / ``.tsv``) using only the
standard library, so importing results never requires openpyxl or pandas."""

from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
import zipfile

XLSX_MAGIC = b"PK\x03\x04"
FALLBACK_SHEET = "xl/worksheets/sheet1.xml"
TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "latin-1")


class SpreadsheetError(ValueError):
    """Raised when a file cannot be interpreted as a spreadsheet."""


def parse_spreadsheet(data: bytes) -> list[list[str]]:
    """Return rows of cell text from raw ``.xlsx`` or delimited-text bytes."""
    if data[:4] == XLSX_MAGIC:
        try:
            return read_xlsx(data)
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
            raise SpreadsheetError(f"could not read workbook: {exc}") from exc
    text = _decode_text(data)
    first_line = text.splitlines()[0] if text.strip() else ""
    delimiter = "\t" if first_line.count("\t") > first_line.count(",") else ","
    return list(csv.reader(io.StringIO(text), delimiter=delimiter))


def _decode_text(data: bytes) -> str:
    for encoding in TEXT_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def read_xlsx(data: bytes) -> list[list[str]]:
    """Read the first worksheet of an ``.xlsx`` file into rows of strings."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        shared = _read_shared_strings(archive, names)
        sheet_path = _first_sheet_path(archive, names)
        sheet = ET.fromstring(archive.read(sheet_path))

    rows: list[list[str]] = []
    for row in (el for el in sheet.iter() if _local(el.tag) == "row"):
        cells: dict[int, str] = {}
        next_index = 0
        for cell in (c for c in row if _local(c.tag) == "c"):
            index = _column_index(cell.attrib.get("r", ""))
            index = next_index if index is None else index
            next_index = index + 1
            cells[index] = _cell_text(cell, shared)
        width = max(cells) + 1 if cells else 0
        rows.append([cells.get(i, "") for i in range(width)])
    return rows


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _column_index(ref: str) -> int | None:
    """``'C7'`` -> 2 (zero-based column), ``None`` if the reference is missing."""
    match = re.match(r"([A-Za-z]+)", ref or "")
    if not match:
        return None
    index = 0
    for char in match.group(1).upper():
        index = index * 26 + (ord(char) - 64)
    return index - 1


def _read_shared_strings(archive: zipfile.ZipFile, names: set[str]) -> list[str]:
    if "xl/sharedStrings.xml" not in names:
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(t.text or "" for t in si.iter() if _local(t.tag) == "t")
        for si in root
        if _local(si.tag) == "si"
    ]


def _first_sheet_path(archive: zipfile.ZipFile, names: set[str]) -> str:
    """Resolve the first worksheet via workbook relationships, with fallbacks."""
    target = FALLBACK_SHEET
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = [el for el in workbook.iter() if _local(el.tag) == "sheet"]
        rel_id = next(
            (v for k, v in sheets[0].attrib.items() if _local(k) == "id"), None
        ) if sheets else None
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {rel.attrib.get("Id"): rel.attrib.get("Target") for rel in rels}
        resolved = targets.get(rel_id)
        if resolved:
            resolved = resolved.lstrip("/")
            target = resolved if resolved.startswith("xl/") else "xl/" + resolved
    except (KeyError, ET.ParseError):
        pass
    if target not in names:
        candidates = sorted(
            n for n in names if n.startswith("xl/worksheets/") and n.endswith(".xml")
        )
        if not candidates:
            raise SpreadsheetError("workbook contains no worksheets")
        target = candidates[0]
    return target


def _cell_text(cell: ET.Element, shared: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(x.text or "" for x in cell.iter() if _local(x.tag) == "t")
    raw = next((x.text or "" for x in cell if _local(x.tag) == "v"), "")
    if cell_type == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return ""
    return raw
