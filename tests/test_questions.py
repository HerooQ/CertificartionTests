import unittest

from certprep.catalog import load_catalog
from certprep.config import Settings
from certprep.questions import validate_catalog, validate_question


class BundledContentTests(unittest.TestCase):
    def test_every_bank_is_valid(self):
        settings = Settings()
        problems = validate_catalog(load_catalog(settings.catalog_path), settings.questions_dir)
        self.assertEqual(problems, [])


class QuestionValidationTests(unittest.TestCase):
    good = {
        "id": "q1", "bucket": "M1", "domain": "D", "question": "Q?",
        "options": ["a", "b", "c"], "answer": [1], "explanation": "because",
    }  # fmt: skip

    def test_valid_question(self):
        self.assertEqual(validate_question(self.good), [])

    def test_detects_problems(self):
        cases = {
            "answer index out of range": {**self.good, "answer": [5]},
            "duplicate options": {**self.good, "options": ["a", "a", "c"]},
            "no correct answer": {**self.good, "answer": []},
            "every option is marked correct": {**self.good, "answer": [0, 1, 2]},
            "empty explanation": {**self.good, "explanation": " "},
            "missing 'id'": {k: v for k, v in self.good.items() if k != "id"},
        }
        for expected, question in cases.items():
            with self.subTest(expected):
                self.assertTrue(any(expected in p for p in validate_question(question)))


if __name__ == "__main__":
    unittest.main()
