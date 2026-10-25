import sqlite3
import tempfile
import unittest
from pathlib import Path

from certprep.database import Database, NewResult


def make_result(**overrides):
    base = dict(
        test="T", first_name="Ada", surname="Lovelace", correct=40, total=50,
        score=800, percent=80, passed=True,
    )  # fmt: skip
    return NewResult(**{**base, **overrides})


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "test.db"
        self.db = Database(self.path)
        self.db.initialize()

    def test_insert_and_list_round_trip(self):
        self.db.insert_result(make_result(comments="CHEATING FLAGGED"))
        [row] = self.db.list_results()
        self.assertEqual((row.surname, row.score, row.passed), ("Lovelace", 800, True))
        self.assertTrue(row.flagged)

    def test_filter_by_test_and_delete(self):
        self.db.insert_result(make_result(test="A"))
        keep = self.db.insert_result(make_result(test="B"))
        self.assertEqual(len(self.db.list_results("A")), 1)
        self.assertEqual(self.db.delete_results("A"), 1)
        self.assertEqual([r.id for r in self.db.list_results()], [keep])
        self.assertEqual(self.db.delete_result(keep), 1)

    def test_attempt_deadline_is_stamped_once(self):
        first = self.db.start_attempt("T", "Ada", "L", duration=600, now=1000.0)
        later = self.db.start_attempt("T", "Ada", "L", duration=600, now=1100.0)
        self.assertEqual((first.remaining, later.remaining), (600, 500))

    def test_clock_never_goes_negative(self):
        self.db.start_attempt("T", "Ada", "L", duration=60, now=0.0)
        self.assertEqual(self.db.start_attempt("T", "Ada", "L", duration=60, now=999.0).remaining, 0)

    def test_closing_attempt_gives_retake_a_fresh_clock(self):
        self.db.start_attempt("T", "Ada", "L", duration=600, now=0.0)
        self.db.close_attempt("T", "Ada", "L")
        self.assertEqual(self.db.start_attempt("T", "Ada", "L", duration=600, now=500.0).remaining, 600)

    def test_initialize_upgrades_legacy_database_without_losing_rows(self):
        legacy = Path(self._tmp.name) / "legacy.db"
        with sqlite3.connect(legacy) as con:
            con.execute(
                """CREATE TABLE results (id INTEGER PRIMARY KEY AUTOINCREMENT, test TEXT NOT NULL,
                   first_name TEXT NOT NULL, surname TEXT NOT NULL, correct INTEGER NOT NULL,
                   total INTEGER NOT NULL, score INTEGER NOT NULL, percent INTEGER NOT NULL,
                   passed INTEGER NOT NULL, domains TEXT, created_at TEXT NOT NULL)"""
            )
            con.execute(
                "INSERT INTO results VALUES (1,'T','Old','Row',1,2,500,50,0,'{}','2024-01-01T00:00:00')"
            )
        con.close()
        db = Database(legacy)
        db.initialize()
        db.initialize()  # idempotent
        [row] = db.list_results()
        self.assertEqual((row.first_name, row.comments), ("Old", ""))


if __name__ == "__main__":
    unittest.main()
