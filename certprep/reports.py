"""Aggregation and export of recorded results."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from certprep.database import StoredResult

CSV_HEADER = (
    "Timestamp", "First name", "Surname", "Test", "Correct", "Total",
    "Score /1000", "Percent", "Passed", "Comments",
)  # fmt: skip


@dataclass(frozen=True)
class ExamBreakdown:
    test: str
    attempts: int
    average_score: int
    pass_rate: int
    flagged: int


@dataclass(frozen=True)
class Summary:
    attempts: int
    average_score: int
    average_percent: int
    pass_rate: int
    flagged: int


@dataclass(frozen=True)
class Report:
    """Everything the report page needs, independent of presentation."""

    selected_test: str | None
    known_tests: list[str]
    rows: list[StoredResult]
    summary: Summary
    per_test: list[ExamBreakdown] = field(default_factory=list)


def _mean(values: list[int]) -> int:
    return round(sum(values) / len(values)) if values else 0


def summarise(rows: list[StoredResult]) -> Summary:
    return Summary(
        attempts=len(rows),
        average_score=_mean([r.score for r in rows]),
        average_percent=_mean([r.percent for r in rows]),
        pass_rate=round(sum(r.passed for r in rows) / len(rows) * 100) if rows else 0,
        flagged=sum(r.flagged for r in rows),
    )


def build_report(
    all_rows: list[StoredResult],
    catalog_names: list[str],
    selected_test: str | None = None,
) -> Report:
    """Build the report. Per-test figures always cover every attempt (they are
    the overview); the headline summary honours the selected-test filter."""
    known = list(catalog_names)
    known.extend(r.test for r in all_rows if r.test not in known)
    if selected_test not in known:
        selected_test = None
    rows = [r for r in all_rows if r.test == selected_test] if selected_test else all_rows

    grouped: dict[str, list[StoredResult]] = {}
    for row in all_rows:
        grouped.setdefault(row.test, []).append(row)
    per_test = [
        ExamBreakdown(
            test=test,
            attempts=len(items),
            average_score=_mean([r.score for r in items]),
            pass_rate=round(sum(r.passed for r in items) / len(items) * 100),
            flagged=sum(r.flagged for r in items),
        )
        for test, items in grouped.items()
    ]
    return Report(selected_test, known, rows, summarise(rows), per_test)


def export_csv(rows: list[StoredResult]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADER)
    for r in rows:
        writer.writerow([
            r.created_at, r.first_name, r.surname, r.test, r.correct, r.total,
            r.score, r.percent, "Yes" if r.passed else "No", r.comments,
        ])  # fmt: skip
    return buffer.getvalue().encode("utf-8")
