"""Scoring policy shared by live submissions, manual entry and spreadsheet import."""

from __future__ import annotations

import math
from dataclasses import dataclass


def round_half_up(value: float) -> int:
    """Round .5 upwards, matching JavaScript's ``Math.round``.

    Python's built-in ``round`` uses banker's rounding, which would disagree
    with the browser-side score shown to the student.
    """
    return math.floor(value + 0.5)


@dataclass(frozen=True)
class ScoringPolicy:
    """Maps a raw ``correct / total`` mark onto the exam's scaled score."""

    scale_max: int = 1000
    pass_mark: int = 700

    def scaled(self, correct: int, total: int) -> int:
        _require_positive(total)
        return round_half_up(correct / total * self.scale_max)

    @staticmethod
    def percent(correct: int, total: int) -> int:
        _require_positive(total)
        return round_half_up(correct / total * 100)

    def passed(self, scaled_score: int) -> bool:
        return scaled_score >= self.pass_mark


def _require_positive(total: int) -> None:
    if total <= 0:
        raise ValueError("total must be positive")
