import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from certprep.database import Database, NewResult
from certprep.importer import import_rows
from certprep.reports import build_report, export_csv
from certprep.scoring import ScoringPolicy
from certprep.spreadsheet import parse_spreadsheet

POLICY = ScoringPolicy()


def minimal_xlsx(rows: list[list[str]]) -> bytes:
    """Build the smallest valid workbook (inline strings) for parser tests."""
    cells = "".join(
        "<row>"
        + "".join(
            f'<c r="{chr(65 + c)}{r + 1}" t="inlineStr"><is><t>{value}</t></is></c>'
            for c, value in enumerate(row)
        )
        + "</row>"
        for r, row in enumerate(rows)
    )
    sheet = f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{cells}</sheetData></worksheet>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()


class ImportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.db.initialize()

    def test_csv_import_scores_rows(self):
        data = b"Test,First name,Surname,Correct,Total\nExam,Ada,Lovelace,35,50\nExam,Bad,Row,,\n"
        summary = import_rows(parse_spreadsheet(data), self.db, POLICY)
        self.assertEqual((summary.imported, summary.skipped), (1, 1))
        [row] = self.db.list_results()
        self.assertEqual((row.score, row.percent, row.passed), (700, 70, True))

    def test_combined_name_column_and_default_test(self):
        data = b"Name,Score\n\"Turing, Alan\",900\n"
        summary = import_rows(parse_spreadsheet(data), self.db, POLICY, default_test="Exam")
        self.assertEqual(summary.imported, 1)
        [row] = self.db.list_results()
        self.assertEqual((row.first_name, row.surname, row.correct, row.total), ("Alan", "Turing", 45, 50))

    def test_missing_header_is_reported(self):
        summary = import_rows(parse_spreadsheet(b"a,b\n1,2\n"), self.db, POLICY)
        self.assertFalse(summary.ok)

    def test_xlsx_import(self):
        header = ["Test", "First name", "Surname", "Correct", "Total"]
        xlsx = minimal_xlsx([header, ["Exam", "Grace", "Hopper", "50", "50"]])
        summary = import_rows(parse_spreadsheet(xlsx), self.db, POLICY)
        self.assertEqual(summary.imported, 1)
        self.assertEqual(self.db.list_results()[0].score, 1000)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.db.initialize()
        for test, score, comments in (("A", 800, ""), ("A", 500, "CHEATING FLAGGED"), ("B", 900, "")):
            self.db.insert_result(
                NewResult(test, "F", "S", score // 20, 50, score, score // 10, score >= 700, comments=comments)
            )

    def test_summary_honours_filter_but_breakdown_does_not(self):
        report = build_report(self.db.list_results(), ["A", "B"], selected_test="A")
        self.assertEqual((report.summary.attempts, report.summary.flagged, report.summary.pass_rate), (2, 1, 50))
        self.assertEqual(sorted(b.test for b in report.per_test), ["A", "B"])

    def test_unknown_filter_falls_back_to_all(self):
        report = build_report(self.db.list_results(), ["A", "B"], selected_test="nope")
        self.assertIsNone(report.selected_test)
        self.assertEqual(report.summary.attempts, 3)

    def test_legacy_test_names_still_listed(self):
        report = build_report(self.db.list_results(), ["Only A"])
        self.assertEqual(report.known_tests[0], "Only A")
        self.assertEqual(sorted(report.known_tests[1:]), ["A", "B"])

    def test_csv_export(self):
        lines = export_csv(self.db.list_results("A")).decode().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("Timestamp,First name"))


if __name__ == "__main__":
    unittest.main()
