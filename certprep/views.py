"""HTML rendering. Markup lives in ``templates/``; this module only fills
placeholders with values that have already been HTML-escaped."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from string import Template
from urllib.parse import quote

from certprep.catalog import Catalog, Exam
from certprep.reports import Report

DEFAULT_THEME = "microsoft"


def _json_for_script(value: object) -> str:
    """Serialise ``value`` for an inline ``<script type="application/json">``
    block, neutralising sequences that could close the tag early."""
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


class Renderer:
    """Loads templates once and renders pages into the shared layout."""

    def __init__(self, templates_dir: Path, catalog: Catalog) -> None:
        self._dir = templates_dir
        self._catalog = catalog
        self._cache: dict[str, Template] = {}

    def _template(self, name: str) -> Template:
        if name not in self._cache:
            self._cache[name] = Template((self._dir / name).read_text(encoding="utf-8"))
        return self._cache[name]

    def _page(
        self,
        title: str,
        content: str,
        *,
        theme: str = DEFAULT_THEME,
        styles: tuple[str, ...] = (),
        scripts: tuple[str, ...] = (),
        script_blocks: str = "",
        body_class: str = "",
    ) -> str:
        style_tags = "".join(f'<link rel="stylesheet" href="/static/css/{s}">\n' for s in styles)
        script_tags = "".join(
            f'<script type="module" src="/static/js/{s}"></script>\n' for s in scripts
        )
        return self._template("base.html").substitute(
            title=escape(title),
            theme=escape(theme),
            body_class=escape(body_class),
            styles=style_tags,
            content=content,
            script_blocks=script_blocks,
            scripts=script_tags,
        )

    # -- landing -----------------------------------------------------------
    def landing(self) -> str:
        groups = []
        for group in self._catalog.groups:
            cards = "".join(
                self._template("partials/exam_card.html").substitute(
                    href=escape(f"/exams/{e.slug}"), name=escape(e.name)
                )
                for e in group.exams
            )
            groups.append(
                self._template("partials/group.html").substitute(
                    title=escape(group.title),
                    blurb=escape(group.blurb),
                    minutes=group.duration_minutes,
                    cards=cards,
                )
            )
        content = self._template("landing.html").substitute(groups="".join(groups))
        return self._page("Practice Exams", content, styles=("landing.css",))

    # -- exam --------------------------------------------------------------
    def exam(self, exam: Exam) -> str:
        scoring = self._catalog.scoring
        config = {
            "slug": exam.slug,
            "name": exam.name,
            "durationSeconds": exam.duration_seconds,
            "passMark": scoring.pass_mark,
            "scaleMax": scoring.scale_max,
            "selection": exam.selection.to_client(),
            "questionsUrl": f"/api/exams/{exam.slug}/questions",
        }
        pills = "".join(f'<span class="pill">{escape(p)}</span>' for p in exam.pills(scoring))
        shown = exam.selection.shown_total
        content = self._template("exam.html").substitute(
            badge=escape(exam.badge),
            title=escape(exam.title),
            subtitle=escape(exam.subtitle),
            pills=pills,
            description=escape(exam.description),
            shown=shown,
            timer=f"{exam.duration_minutes}:00",
        )
        config_block = (
            f'<script id="exam-config" type="application/json">{_json_for_script(config)}</script>\n'
        )
        return self._page(
            exam.title,
            content,
            theme=exam.theme,
            styles=("exam.css", "proctor.css"),
            scripts=("exam/main.js",),
            script_blocks=config_block,
            body_class="exam-page",
        )

    # -- report ------------------------------------------------------------
    def report(self, report: Report) -> str:
        t = self._template
        s = report.summary
        stat_cards = t("partials/stats.html").substitute(
            attempts=s.attempts,
            average_score=s.average_score,
            average_percent=s.average_percent,
            pass_rate=s.pass_rate,
            pass_mark=self._catalog.scoring.pass_mark,
            flagged=s.flagged,
            flag_class=" flagcard" if s.flagged else "",
        )

        per_test_rows = (
            "".join(
                "<tr>"
                f"<td>{escape(b.test)}</td><td>{b.attempts}</td>"
                f"<td>{b.average_score}</td><td>{b.pass_rate}%</td>"
                f"<td>{self._flag_count(b.flagged)}</td></tr>"
                for b in report.per_test
            )
            or '<tr><td colspan="5" class="empty">No attempts yet.</td></tr>'
        )

        selected = report.selected_test
        filter_options = '<option value="">All tests</option>' + "".join(
            self._option(name, name == selected) for name in report.known_tests
        )
        add_options = (
            "".join(self._option(name, name == selected) for name in report.known_tests)
            or '<option value="">(no tests defined)</option>'
        )

        body_rows = "".join(self._result_row(r) for r in report.rows) or (
            '<tr><td colspan="9" class="empty">No results recorded for this filter yet.</td></tr>'
        )
        export_href = "/export.csv" + (f"?test={quote(selected)}" if selected else "")
        heading = f"All attempts — {escape(selected)}" if selected else "All attempts"
        page_state = {"selectedTest": selected, "shownCount": s.attempts}

        content = t("report.html").substitute(
            stat_cards=stat_cards,
            per_test_rows=per_test_rows,
            heading=heading,
            filter_options=filter_options,
            add_options=add_options,
            body_rows=body_rows,
            export_href=escape(export_href),
        )
        state_block = f'<script id="report-state" type="application/json">{_json_for_script(page_state)}</script>\n'
        return self._page(
            "Practice Exam Results",
            content,
            styles=("report.css",),
            scripts=("report.js",),
            script_blocks=state_block,
        )

    @staticmethod
    def _flag_count(count: int) -> str:
        return f'<strong class="flag-count">{count}</strong>' if count else "0"

    @staticmethod
    def _option(value: str, selected: bool) -> str:
        attr = " selected" if selected else ""
        return f'<option value="{escape(value)}"{attr}>{escape(value)}</option>'

    @staticmethod
    def _result_row(r) -> str:
        badge = (
            '<span class="pill pass">PASS</span>'
            if r.passed
            else '<span class="pill fail">FAIL</span>'
        )
        if r.flagged:
            note = f'<span class="pill flag">⚑ {escape(r.comments)}</span>'
            row_class = ' class="flagrow"'
        else:
            note = '<span class="ok">Clean</span>'
            row_class = ""
        return (
            f"<tr{row_class}><td>{escape(r.created_at.replace('T', ' '))}</td>"
            f"<td>{escape(r.surname)}, {escape(r.first_name)}</td>"
            f"<td>{escape(r.test)}</td><td>{r.correct}/{r.total}</td>"
            f"<td><strong>{r.score}</strong></td><td>{r.percent}%</td>"
            f"<td>{badge}</td><td>{note}</td>"
            f'<td class="noprint"><button type="button" class="del" '
            f'data-delete-id="{r.id}">Delete</button></td></tr>'
        )
