"""SQLite persistence for exam results and server-side attempt timers."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    test        TEXT    NOT NULL,
    first_name  TEXT    NOT NULL,
    surname     TEXT    NOT NULL,
    correct     INTEGER NOT NULL,
    total       INTEGER NOT NULL,
    score       INTEGER NOT NULL,   -- scaled score
    percent     INTEGER NOT NULL,
    passed      INTEGER NOT NULL,   -- 1 / 0
    domains     TEXT,               -- JSON per-domain breakdown
    comments    TEXT,               -- proctoring notes ('' = clean)
    created_at  TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    test        TEXT    NOT NULL,
    first_name  TEXT    NOT NULL,
    surname     TEXT    NOT NULL,
    started_at  TEXT    NOT NULL,
    ends_at     REAL    NOT NULL,   -- epoch seconds: the authoritative deadline
    duration    INTEGER NOT NULL,
    submitted   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_attempts_open
    ON attempts (test, first_name, surname, submitted);
CREATE INDEX IF NOT EXISTS idx_results_test ON results (test);
"""


@dataclass(frozen=True)
class NewResult:
    """A finished attempt, ready to be stored."""

    test: str
    first_name: str
    surname: str
    correct: int
    total: int
    score: int
    percent: int
    passed: bool
    domains: dict = field(default_factory=dict)
    comments: str = ""


@dataclass(frozen=True)
class StoredResult:
    """A row read back from the ``results`` table."""

    id: int
    test: str
    first_name: str
    surname: str
    correct: int
    total: int
    score: int
    percent: int
    passed: bool
    comments: str
    created_at: str

    @property
    def flagged(self) -> bool:
        """True when proctoring recorded any suspicious behaviour."""
        return bool(self.comments)


@dataclass(frozen=True)
class AttemptClock:
    """Authoritative time remaining for an in-progress attempt."""

    remaining: int
    duration: int


class Database:
    """Thin repository over a SQLite file. Each call opens a short-lived
    connection, which keeps the threaded HTTP server free of shared state."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=10)) as con:
            con.row_factory = sqlite3.Row
            with con:  # commit on success, roll back on error
                yield con

    # -- schema -----------------------------------------------------------
    def initialize(self) -> None:
        """Create tables and upgrade databases created by older versions."""
        with self._connect() as con:
            con.executescript(SCHEMA)
            columns = {row["name"] for row in con.execute("PRAGMA table_info(results)")}
            if "comments" not in columns:
                con.execute("ALTER TABLE results ADD COLUMN comments TEXT")

    # -- results ----------------------------------------------------------
    def insert_result(self, result: NewResult) -> int:
        with self._connect() as con:
            cur = con.execute(
                """INSERT INTO results
                   (test, first_name, surname, correct, total, score, percent,
                    passed, domains, comments, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    result.test,
                    result.first_name.strip(),
                    result.surname.strip(),
                    result.correct,
                    result.total,
                    result.score,
                    result.percent,
                    int(result.passed),
                    json.dumps(result.domains),
                    result.comments.strip(),
                    _now_iso(),
                ),
            )
            return int(cur.lastrowid)

    def list_results(self, test: str | None = None) -> list[StoredResult]:
        query = "SELECT * FROM results"
        params: tuple = ()
        if test:
            query += " WHERE test = ?"
            params = (test,)
        query += " ORDER BY created_at DESC, id DESC"
        with self._connect() as con:
            return [_to_stored(row) for row in con.execute(query, params)]

    def delete_result(self, result_id: int) -> int:
        with self._connect() as con:
            return con.execute("DELETE FROM results WHERE id = ?", (result_id,)).rowcount

    def delete_results(self, test: str | None = None) -> int:
        """Delete every result, or only those for ``test``. Returns rows removed."""
        with self._connect() as con:
            if test:
                return con.execute("DELETE FROM results WHERE test = ?", (test,)).rowcount
            return con.execute("DELETE FROM results").rowcount

    # -- attempt timers ---------------------------------------------------
    def start_attempt(
        self,
        test: str,
        first_name: str,
        surname: str,
        duration: int,
        now: float | None = None,
    ) -> AttemptClock:
        """Return the authoritative time remaining for this student's attempt.

        The deadline is stamped once and then reused, so reloading or reopening
        the tab cannot reset the clock. A new attempt is only created once the
        previous one for the same (test, name) has been submitted.
        """
        now = time.time() if now is None else now
        first_name, surname = first_name.strip(), surname.strip()
        with self._connect() as con:
            row = con.execute(
                """SELECT ends_at FROM attempts
                   WHERE test=? AND first_name=? AND surname=? AND submitted=0
                   ORDER BY id DESC LIMIT 1""",
                (test, first_name, surname),
            ).fetchone()
            if row:
                ends_at = row["ends_at"]
            else:
                ends_at = now + duration
                con.execute(
                    """INSERT INTO attempts
                       (test, first_name, surname, started_at, ends_at, duration, submitted)
                       VALUES (?,?,?,?,?,?,0)""",
                    (test, first_name, surname, _now_iso(), ends_at, duration),
                )
        remaining = max(0, round(ends_at - now))
        return AttemptClock(remaining=remaining, duration=duration)

    def close_attempt(self, test: str, first_name: str, surname: str) -> None:
        """Close the open attempt so a later retake gets a fresh deadline."""
        with self._connect() as con:
            con.execute(
                """UPDATE attempts SET submitted=1
                   WHERE test=? AND first_name=? AND surname=? AND submitted=0""",
                (test, first_name.strip(), surname.strip()),
            )


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _to_stored(row: sqlite3.Row) -> StoredResult:
    return StoredResult(
        id=row["id"],
        test=row["test"],
        first_name=row["first_name"],
        surname=row["surname"],
        correct=row["correct"],
        total=row["total"],
        score=row["score"],
        percent=row["percent"],
        passed=bool(row["passed"]),
        comments=(row["comments"] or "").strip(),
        created_at=row["created_at"],
    )
