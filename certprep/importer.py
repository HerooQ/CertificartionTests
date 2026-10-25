"""Bulk-import attempts from a parsed spreadsheet."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from certprep.database import Database, NewResult
from certprep.scoring import ScoringPolicy, round_half_up

HEADER_SCAN_ROWS = 8
DEFAULT_TOTAL = 50
MAX_REPORTED_ERRORS = 10

HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "test": ("test", "exam", "test name", "paper"),
    "first_name": ("first name", "first", "firstname", "given name", "first names"),
    "surname": ("surname", "last name", "lastname", "family name", "last"),
    "name": ("name", "student", "full name", "student name", "candidate"),
    "correct": ("correct", "marks", "correct answers", "score correct", "right", "raw"),
    "total": ("total", "out of", "questions", "total questions", "max", "no. questions"),
    "score": ("score", "scaled", "scaled score", "score /1000", "scaled /1000"),
    "percent": ("percent", "percentage", "%", "pct"),
    "comments": ("comments", "comment", "notes", "note"),
}


@dataclass
class ImportSummary:
    ok: bool
    imported: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        if not self.ok:
            return {"ok": False, "error": self.error}
        return {
            "ok": True,
            "imported": self.imported,
            "skipped": self.skipped,
            "errors": self.errors[:MAX_REPORTED_ERRORS],
        }


def normalise_header(cell: object) -> str:
    return re.sub(r"\s+", " ", str(cell or "").strip().lower()).strip(" .:_-")


def map_headers(header_row: list[str]) -> dict[str, int]:
    """Map canonical field names to column indexes using header synonyms."""
    mapping: dict[str, int] = {}
    for index, cell in enumerate(header_row):
        header = normalise_header(cell)
        for key, synonyms in HEADER_SYNONYMS.items():
            if header in synonyms and key not in mapping:
                mapping[key] = index
    return mapping


def _find_header(rows: list[list[str]], default_test: str) -> tuple[int, dict[str, int]] | None:
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        mapping = map_headers(row)
        has_name = "first_name" in mapping or "name" in mapping
        has_mark = "test" in mapping or "score" in mapping or "correct" in mapping or default_test
        if has_name and has_mark:
            return index, mapping
    return None


def _as_int(value: object) -> int | None:
    text = str(value).strip().replace("%", "")
    if not text:
        return None
    try:
        return round_half_up(float(text))
    except ValueError:
        return None


def _split_name(raw: str) -> tuple[str, str]:
    """Split ``"Surname, First"`` or ``"First Last"`` into (first, surname)."""
    if "," in raw:
        surname, first = (part.strip() for part in raw.split(",", 1))
        return first, surname
    parts = raw.split()
    return (parts[0], " ".join(parts[1:])) if parts else ("", "")


def import_rows(
    rows: list[list[str]],
    db: Database,
    scoring: ScoringPolicy,
    default_test: str = "",
) -> ImportSummary:
    """Insert one result per usable row. Rows are imported clean (empty
    comments) unless the sheet has a Comments column with a value."""
    default_test = (default_test or "").strip()
    header = _find_header(rows, default_test)
    if header is None:
        return ImportSummary(
            ok=False,
            error=(
                "Couldn't find a header row. Expected columns like "
                "Test, First name, Surname, Correct, Total."
            ),
        )
    header_index, mapping = header
    summary = ImportSummary(ok=True)

    def cell(row: list[str], key: str) -> str:
        column = mapping.get(key)
        if column is None or column >= len(row) or row[column] is None:
            return ""
        return str(row[column]).strip()

    for line_no, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if not any(str(c).strip() for c in row):
            continue
        test = cell(row, "test") or default_test
        first, surname = cell(row, "first_name"), cell(row, "surname")
        if not first and "name" in mapping:
            first, surname = _split_name(cell(row, "name"))
        if not (test and first and surname):
            summary.skipped += 1
            summary.errors.append(f"Row {line_no}: missing test or name")
            continue

        correct, total, score = (_as_int(cell(row, k)) for k in ("correct", "total", "score"))
        if correct is not None and total and total > 0:
            correct = max(0, min(correct, total))
            score = scoring.scaled(correct, total)
            percent = scoring.percent(correct, total)
        elif score is not None:
            total = total if total and total > 0 else DEFAULT_TOTAL
            percent = round_half_up(score / scoring.scale_max * 100)
            correct = round_half_up(score / scoring.scale_max * total)
        else:
            summary.skipped += 1
            summary.errors.append(f"Row {line_no}: no Correct/Total or Score")
            continue

        db.insert_result(
            NewResult(
                test=test,
                first_name=first,
                surname=surname,
                correct=correct,
                total=total,
                score=score,
                percent=percent,
                passed=scoring.passed(score),
                comments=cell(row, "comments"),
            )
        )
        summary.imported += 1
    return summary


def template_csv(example_test: str) -> str:
    """CSV template offered for download on the report page."""
    return (
        "Test,First name,Surname,Correct,Total,Comments\n"
        f'"{example_test}",Ada,Lovelace,42,50,\n'
        f'"{example_test}",Alan,Turing,47,50,\n'
    )
