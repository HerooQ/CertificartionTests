"""Question banks: loading and structural validation.

Banks live in ``data/questions/<exam-slug>.json`` as a list of objects::

    {"id": "...", "bucket": "M3", "domain": "Label shown to students",
     "question": "...", "options": ["...", "..."], "answer": [1],
     "explanation": "..."}

``answer`` holds zero-based indexes into ``options``; more than one index makes
the item a multiple-response question.
"""

from __future__ import annotations

import json
from pathlib import Path

from certprep.catalog import Catalog, Exam

REQUIRED_FIELDS = ("id", "bucket", "domain", "question", "options", "answer", "explanation")
MIN_OPTIONS = 2


def load_bank_text(questions_dir: Path, slug: str) -> bytes | None:
    """Raw JSON bytes for an exam's bank, or ``None`` if it does not exist."""
    path = questions_dir / f"{slug}.json"
    return path.read_bytes() if path.is_file() else None


def validate_question(q: dict) -> list[str]:
    """Return a list of human-readable problems with one question (empty = valid)."""
    qid = q.get("id", "<no id>")
    problems = [f"{qid}: missing '{f}'" for f in REQUIRED_FIELDS if f not in q]
    if problems:
        return problems
    options, answer = q["options"], q["answer"]
    if len(options) < MIN_OPTIONS:
        problems.append(f"{qid}: needs at least {MIN_OPTIONS} options")
    if len(set(options)) != len(options):
        problems.append(f"{qid}: duplicate options")
    if not answer:
        problems.append(f"{qid}: no correct answer")
    elif len(set(answer)) != len(answer):
        problems.append(f"{qid}: duplicate answer indexes")
    elif not all(isinstance(i, int) and 0 <= i < len(options) for i in answer):
        problems.append(f"{qid}: answer index out of range")
    elif len(answer) == len(options):
        problems.append(f"{qid}: every option is marked correct")
    for text_field in ("question", "explanation"):
        if not str(q[text_field]).strip():
            problems.append(f"{qid}: empty {text_field}")
    return problems


def validate_bank(exam: Exam, bank: list[dict]) -> list[str]:
    """Validate a whole bank against the exam's selection rules."""
    problems: list[str] = []
    ids = [q.get("id") for q in bank]
    if len(set(ids)) != len(ids):
        problems.append(f"{exam.slug}: duplicate question ids")
    for q in bank:
        problems.extend(validate_question(q))

    per_bucket: dict[str, int] = {}
    for q in bank:
        per_bucket[q.get("bucket", "")] = per_bucket.get(q.get("bucket", ""), 0) + 1

    selection = exam.selection
    if selection.strategy == "planned":
        for bucket, counts in selection.plan.items():
            need = counts["scored"] + counts["unscored"]
            have = per_bucket.get(bucket, 0)
            if have < need:
                problems.append(f"{exam.slug}: bucket {bucket} has {have} questions, plan needs {need}")
    elif len(bank) < selection.scored:
        problems.append(f"{exam.slug}: bank has {len(bank)} questions, exam needs {selection.scored}")
    return problems


def validate_catalog(catalog: Catalog, questions_dir: Path) -> list[str]:
    """Validate every exam's bank. Used by ``python -m certprep validate`` and CI."""
    problems: list[str] = []
    for exam in catalog:
        raw = load_bank_text(questions_dir, exam.slug)
        if raw is None:
            problems.append(f"{exam.slug}: question bank file is missing")
            continue
        try:
            bank = json.loads(raw)
        except json.JSONDecodeError as exc:
            problems.append(f"{exam.slug}: invalid JSON ({exc})")
            continue
        problems.extend(validate_bank(exam, bank))
    return problems
