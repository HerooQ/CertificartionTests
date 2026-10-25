import unittest

from certprep.catalog import CatalogError, load_catalog, parse_catalog
from certprep.config import Settings
from certprep.scoring import ScoringPolicy, round_half_up


class ScoringTests(unittest.TestCase):
    policy = ScoringPolicy(scale_max=1000, pass_mark=700)

    def test_round_half_up_matches_javascript(self):
        self.assertEqual(round_half_up(2.5), 3)  # Python's round() gives 2
        self.assertEqual(round_half_up(0.49), 0)

    def test_scaled_score_and_pass_boundary(self):
        self.assertEqual(self.policy.scaled(35, 50), 700)
        self.assertTrue(self.policy.passed(700))
        self.assertFalse(self.policy.passed(self.policy.scaled(34, 50)))

    def test_percent(self):
        self.assertEqual(self.policy.percent(1, 3), 33)

    def test_rejects_non_positive_total(self):
        with self.assertRaises(ValueError):
            self.policy.scaled(1, 0)


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(Settings().catalog_path)

    def test_bundled_catalog_loads(self):
        self.assertEqual(len(list(self.catalog)), 5)

    def test_lookups(self):
        exam = self.catalog.by_slug("aws-final")
        self.assertIsNotNone(exam)
        self.assertIs(self.catalog.by_name(exam.name), exam)
        self.assertIs(self.catalog.by_legacy_file("aws-final.html"), exam)

    def test_aws_exam_shows_unscored_questions(self):
        sel = self.catalog.by_slug("aws-final").selection
        self.assertEqual((sel.scored_total, sel.unscored, sel.shown_total), (50, 15, 65))

    def test_duration_is_per_group_with_default(self):
        self.assertEqual(self.catalog.duration_for(self.catalog.by_slug("sc900-practice-1").name), 45 * 60)
        self.assertEqual(self.catalog.duration_for(self.catalog.by_slug("aws-final").name), 90 * 60)
        self.assertEqual(self.catalog.duration_for("legacy unknown exam"), 45 * 60)

    def test_rejects_duplicate_slugs(self):
        exam = {
            "slug": "a", "name": "A", "title": "A",
            "selection": {"strategy": "balanced", "scored": 5},
        }  # fmt: skip
        raw = {"groups": [{"id": "g", "title": "G", "theme": "aws", "durationMinutes": 1, "exams": [exam, exam]}]}
        with self.assertRaises(CatalogError):
            parse_catalog(raw)

    def test_rejects_unknown_strategy(self):
        exam = {"slug": "a", "name": "A", "title": "A", "selection": {"strategy": "nope", "scored": 5}}
        raw = {"groups": [{"id": "g", "title": "G", "theme": "aws", "durationMinutes": 1, "exams": [exam]}]}
        with self.assertRaises(CatalogError):
            parse_catalog(raw)


if __name__ == "__main__":
    unittest.main()
