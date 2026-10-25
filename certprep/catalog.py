"""Exam catalogue: the groups, exams and selection rules defined in ``catalog.json``."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from certprep.scoring import ScoringPolicy

DEFAULT_DURATION_SECONDS = 45 * 60
STRATEGIES = ("balanced", "planned")


class CatalogError(ValueError):
    """Raised when ``catalog.json`` is malformed."""


@dataclass(frozen=True)
class Selection:
    """How a paper is assembled from a question bank.

    ``balanced`` draws ``scored`` questions round-robin across buckets;
    ``planned`` takes an explicit scored/unscored count from each bucket.
    """

    strategy: str
    scored: int = 0
    plan: dict[str, dict[str, int]] = field(default_factory=dict)
    bucket_label: str = "domain"

    @property
    def unscored(self) -> int:
        return sum(bucket["unscored"] for bucket in self.plan.values())

    @property
    def scored_total(self) -> int:
        if self.strategy == "planned":
            return sum(bucket["scored"] for bucket in self.plan.values())
        return self.scored

    @property
    def shown_total(self) -> int:
        return self.scored_total + self.unscored

    def to_client(self) -> dict:
        return {
            "strategy": self.strategy,
            "scored": self.scored_total,
            "plan": self.plan,
            "bucketLabel": self.bucket_label,
        }


@dataclass(frozen=True)
class Exam:
    slug: str
    name: str
    title: str
    subtitle: str
    description: str
    badge: str
    theme: str
    duration_seconds: int
    selection: Selection
    scope: str = ""
    legacy_file: str = ""

    @property
    def duration_minutes(self) -> int:
        return self.duration_seconds // 60

    def pills(self, scoring: ScoringPolicy) -> list[str]:
        """Short facts shown on the exam intro screen."""
        sel = self.selection
        if sel.unscored:
            pills = [
                f"{sel.shown_total} questions",
                f"{sel.scored_total} scored + {sel.unscored} unscored",
                f"{self.duration_minutes}-minute timer",
                f"Scaled /{scoring.scale_max}",
                f"Pass = {scoring.pass_mark}",
            ]
        else:
            pills = [
                f"{sel.shown_total} questions",
                f"Scored out of {scoring.scale_max}",
                f"Pass = {scoring.pass_mark}",
                f"{self.duration_minutes}-minute timer",
            ]
        if self.scope:
            pills.append(self.scope)
        return pills


@dataclass(frozen=True)
class ExamGroup:
    id: str
    title: str
    blurb: str
    theme: str
    duration_seconds: int
    exams: tuple[Exam, ...]

    @property
    def duration_minutes(self) -> int:
        return self.duration_seconds // 60


@dataclass(frozen=True)
class Catalog:
    scoring: ScoringPolicy
    groups: tuple[ExamGroup, ...]

    def __iter__(self) -> Iterator[Exam]:
        for group in self.groups:
            yield from group.exams

    def by_slug(self, slug: str) -> Exam | None:
        return next((e for e in self if e.slug == slug), None)

    def by_name(self, name: str) -> Exam | None:
        return next((e for e in self if e.name == name), None)

    def by_legacy_file(self, filename: str) -> Exam | None:
        return next((e for e in self if e.legacy_file and e.legacy_file == filename), None)

    @property
    def names(self) -> list[str]:
        return [e.name for e in self]

    def duration_for(self, name: str) -> int:
        """Server-enforced exam length; unknown (legacy) names get a default."""
        exam = self.by_name(name)
        return exam.duration_seconds if exam else DEFAULT_DURATION_SECONDS


def _parse_selection(raw: dict, where: str) -> Selection:
    strategy = raw.get("strategy")
    if strategy not in STRATEGIES:
        raise CatalogError(f"{where}: strategy must be one of {STRATEGIES}")
    plan = {
        bucket: {"scored": int(v["scored"]), "unscored": int(v.get("unscored", 0))}
        for bucket, v in raw.get("plan", {}).items()
    }
    selection = Selection(
        strategy=strategy,
        scored=int(raw.get("scored", 0)),
        plan=plan,
        bucket_label=raw.get("bucketLabel", "domain"),
    )
    if selection.scored_total <= 0:
        raise CatalogError(f"{where}: selection must score at least one question")
    if strategy == "planned" and not plan:
        raise CatalogError(f"{where}: planned selection needs a plan")
    return selection


def parse_catalog(raw: dict) -> Catalog:
    """Build a validated :class:`Catalog` from decoded JSON."""
    scoring_raw = raw.get("scoring", {})
    scoring = ScoringPolicy(
        scale_max=int(scoring_raw.get("scaleMax", 1000)),
        pass_mark=int(scoring_raw.get("passMark", 700)),
    )
    groups: list[ExamGroup] = []
    seen_slugs: set[str] = set()
    seen_names: set[str] = set()
    for g in raw.get("groups", []):
        duration = int(g["durationMinutes"]) * 60
        exams = []
        for e in g["exams"]:
            where = f"exam {e.get('slug', '?')}"
            if e["slug"] in seen_slugs or e["name"] in seen_names:
                raise CatalogError(f"{where}: duplicate slug or name")
            seen_slugs.add(e["slug"])
            seen_names.add(e["name"])
            exams.append(
                Exam(
                    slug=e["slug"],
                    name=e["name"],
                    title=e["title"],
                    subtitle=e.get("subtitle", ""),
                    description=e.get("description", g.get("description", "")),
                    badge=e.get("badge", g.get("badge", g["title"].upper())),
                    theme=g["theme"],
                    duration_seconds=duration,
                    selection=_parse_selection(e["selection"], where),
                    scope=e.get("scope", ""),
                    legacy_file=e.get("legacyFile", ""),
                )
            )
        groups.append(
            ExamGroup(
                id=g["id"],
                title=g["title"],
                blurb=g.get("blurb", ""),
                theme=g["theme"],
                duration_seconds=duration,
                exams=tuple(exams),
            )
        )
    if not groups:
        raise CatalogError("catalog defines no exam groups")
    return Catalog(scoring=scoring, groups=tuple(groups))


def load_catalog(path: Path) -> Catalog:
    with open(path, encoding="utf-8") as fh:
        return parse_catalog(json.load(fh))
