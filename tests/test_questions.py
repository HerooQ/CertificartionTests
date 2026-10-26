import unittest

from certprep.catalog import load_catalog
from certprep.config import Settings
from certprep.questions import validate_catalog, validate_question


class BundledContentTests(unittest.TestCase):
    def test_every_bank_is_valid(self):
        settings = Settings()
        problems = validate_catalog(load_catalog(settings.catalog_path), settings.questions_dir)
        self.assertEqual(problems, [])


GOOD_QUESTION = {
    "id": "q1", "bucket": "M1", "domain": "D", "question": "Q?",
    "options": ["a", "b", "c"], "answer": [1], "explanation": "because",
}  # fmt: skip


class QuestionValidationTests(unittest.TestCase):
    def test_valid_question(self):
        self.assertEqual(validate_question(GOOD_QUESTION), [])

    def test_detects_problems(self):
        cases = {
            "answer index out of range": {**GOOD_QUESTION, "answer": [5]},
            "duplicate options": {**GOOD_QUESTION, "options": ["a", "a", "c"]},
            "no correct answer": {**GOOD_QUESTION, "answer": []},
            "every option is marked correct": {**GOOD_QUESTION, "answer": [0, 1, 2]},
            "empty explanation": {**GOOD_QUESTION, "explanation": " "},
            "missing 'id'": {k: v for k, v in GOOD_QUESTION.items() if k != "id"},
        }
        for expected, question in cases.items():
            with self.subTest(expected):
                self.assertTrue(any(expected in p for p in validate_question(question)))


if __name__ == "__main__":
    unittest.main()
