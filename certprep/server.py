"""HTTP layer: routing, request validation and response helpers.

Built on :mod:`http.server` so the project has no third-party dependencies.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import re
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from certprep.catalog import Catalog, load_catalog
from certprep.config import Settings
from certprep.database import Database, NewResult
from certprep.importer import ImportSummary, import_rows, template_csv
from certprep.questions import load_bank_text
from certprep.reports import build_report, export_csv
from certprep.spreadsheet import SpreadsheetError, parse_spreadsheet
from certprep.views import Renderer

log = logging.getLogger("certprep")

MAX_NAME_LENGTH = 100
MAX_COMMENT_LENGTH = 500
HTML = "text/html; charset=utf-8"
JSON = "application/json"
CSV = "text/csv; charset=utf-8"

# Windows' registry can map .js to text/plain, which breaks ES modules.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(self)",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
}


class HttpError(Exception):
    """Raised by handlers to produce a specific HTTP error response."""

    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Application:
    """Wires the long-lived collaborators together once at start-up."""

    settings: Settings
    catalog: Catalog
    db: Database
    renderer: Renderer

    @classmethod
    def create(cls, settings: Settings) -> Application:
        catalog = load_catalog(settings.catalog_path)
        db = Database(settings.db_path)
        db.initialize()
        return cls(settings, catalog, db, Renderer(settings.templates_dir, catalog))


# -- request payload helpers -----------------------------------------------
def _text(payload: dict, key: str, *, required: bool = True, limit: int = MAX_NAME_LENGTH) -> str:
    value = str(payload.get(key) or "").strip()
    if required and not value:
        raise HttpError(HTTPStatus.BAD_REQUEST, f"missing {key.replace('_', ' ')}")
    if len(value) > limit:
        raise HttpError(HTTPStatus.BAD_REQUEST, f"{key.replace('_', ' ')} is too long")
    return value


def _integer(payload: dict, key: str) -> int:
    try:
        return int(payload.get(key))
    except (TypeError, ValueError):
        raise HttpError(HTTPStatus.BAD_REQUEST, f"{key} must be a whole number") from None


def _mark(payload: dict) -> tuple[int, int]:
    correct, total = _integer(payload, "correct"), _integer(payload, "total")
    if total <= 0 or not 0 <= correct <= total:
        raise HttpError(HTTPStatus.BAD_REQUEST, "bad correct/total")
    return correct, total


# -- routing ---------------------------------------------------------------
GET_ROUTES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^/(?:index\.html)?$"), "landing"),
    (re.compile(r"^/exams/(?P<slug>[a-z0-9-]+)$"), "exam_page"),
    (re.compile(r"^/tests/(?P<filename>[\w.-]+\.html)$"), "legacy_exam_redirect"),
    (re.compile(r"^/report$"), "report"),
    (re.compile(r"^/export\.csv$"), "export"),
    (re.compile(r"^/import_template\.csv$"), "import_template"),
    (re.compile(r"^/api/exams/(?P<slug>[a-z0-9-]+)/questions$"), "questions"),
    (re.compile(r"^/static/(?P<path>.+)$"), "static_file"),
    (re.compile(r"^/healthz$"), "health"),
]
POST_ROUTES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^/api/start$"), "api_start"),
    (re.compile(r"^/api/submit$"), "api_submit"),
    (re.compile(r"^/api/add$"), "api_add"),
    (re.compile(r"^/api/delete$"), "api_delete"),
    (re.compile(r"^/api/import$"), "api_import"),
]


class RequestHandler(BaseHTTPRequestHandler):
    app: Application  # injected by ``make_handler``
    server_version = "CertPrep"
    sys_version = ""

    # -- dispatch -----------------------------------------------------------
    def do_GET(self) -> None:
        self._dispatch(GET_ROUTES)

    def do_POST(self) -> None:
        self._dispatch(POST_ROUTES)

    def _dispatch(self, routes: list[tuple[re.Pattern[str], str]]) -> None:
        url = urlparse(self.path)
        self.query = parse_qs(url.query)
        try:
            for pattern, name in routes:
                match = pattern.match(url.path)
                if match:
                    getattr(self, name)(**match.groupdict())
                    return
            raise HttpError(HTTPStatus.NOT_FOUND, "Not found")
        except HttpError as err:
            self._error(err)
        except Exception:  # noqa: BLE001 - last-resort guard; details go to the log
            log.exception("Unhandled error serving %s", self.path)
            self._error(HttpError(HTTPStatus.INTERNAL_SERVER_ERROR, "Internal server error"))

    # -- response helpers ---------------------------------------------------
    def _send(
        self,
        status: HTTPStatus,
        body: str | bytes,
        content_type: str = HTML,
        headers: dict[str, str] | None = None,
        cache: str = "no-store",
    ) -> None:
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", cache)
        for key, value in {**SECURITY_HEADERS, **(headers or {})}.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, data: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send(status, json.dumps(data), JSON)

    def _error(self, err: HttpError) -> None:
        if urlparse(self.path).path.startswith("/api/"):
            self._json({"ok": False, "error": err.message}, err.status)
        else:
            self._send(err.status, err.message, "text/plain; charset=utf-8")

    def _read_body(self, limit: int) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            raise HttpError(HTTPStatus.BAD_REQUEST, "bad Content-Length") from None
        if length > limit:
            raise HttpError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request body too large")
        return self.rfile.read(length) if length else b""

    def _read_json(self) -> dict:
        raw = self._read_body(self.app.settings.max_json_bytes)
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            raise HttpError(HTTPStatus.BAD_REQUEST, "invalid JSON") from None
        if not isinstance(data, dict):
            raise HttpError(HTTPStatus.BAD_REQUEST, "expected a JSON object")
        return data

    def _query(self, key: str) -> str | None:
        return (self.query.get(key) or [None])[0] or None

    # -- pages --------------------------------------------------------------
    def landing(self) -> None:
        self._send(HTTPStatus.OK, self.app.renderer.landing())

    def exam_page(self, slug: str) -> None:
        exam = self.app.catalog.by_slug(slug)
        if exam is None:
            raise HttpError(HTTPStatus.NOT_FOUND, "Unknown exam")
        self._send(HTTPStatus.OK, self.app.renderer.exam(exam))

    def legacy_exam_redirect(self, filename: str) -> None:
        """Keep links to the old ``/tests/testN.html`` pages working."""
        exam = self.app.catalog.by_legacy_file(filename)
        if exam is None:
            raise HttpError(HTTPStatus.NOT_FOUND, "Unknown exam")
        self._send(
            HTTPStatus.MOVED_PERMANENTLY, "", "text/plain", {"Location": f"/exams/{exam.slug}"}
        )

    def report(self) -> None:
        rows = self.app.db.list_results()
        report = build_report(rows, self.app.catalog.names, self._query("test"))
        self._send(HTTPStatus.OK, self.app.renderer.report(report))

    def health(self) -> None:
        self._json({"ok": True})

    # -- downloads ----------------------------------------------------------
    def export(self) -> None:
        rows = self.app.db.list_results(self._query("test"))
        self._send(
            HTTPStatus.OK,
            export_csv(rows),
            CSV,
            {"Content-Disposition": "attachment; filename=exam_results.csv"},
        )

    def import_template(self) -> None:
        example = next(iter(self.app.catalog)).name
        self._send(
            HTTPStatus.OK,
            template_csv(example),
            CSV,
            {"Content-Disposition": "attachment; filename=import_template.csv"},
        )

    def questions(self, slug: str) -> None:
        if self.app.catalog.by_slug(slug) is None:
            raise HttpError(HTTPStatus.NOT_FOUND, "Unknown exam")
        bank = load_bank_text(self.app.settings.questions_dir, slug)
        if bank is None:
            raise HttpError(HTTPStatus.NOT_FOUND, "Question bank not found")
        self._send(HTTPStatus.OK, bank, JSON)

    def static_file(self, path: str) -> None:
        root = self.app.settings.static_dir.resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HttpError(HTTPStatus.NOT_FOUND, "Not found")
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(HTTPStatus.OK, target.read_bytes(), content_type, cache="no-cache")

    # -- JSON API -----------------------------------------------------------
    def api_start(self) -> None:
        """Return (and lazily create) the authoritative clock for an attempt."""
        data = self._read_json()
        test = _text(data, "test", required=False, limit=300)
        clock = self.app.db.start_attempt(
            test,
            _text(data, "first_name"),
            _text(data, "surname"),
            self.app.catalog.duration_for(test),
        )
        self._json({"ok": True, "remaining": clock.remaining, "duration": clock.duration})

    def api_submit(self) -> None:
        data = self._read_json()
        first, surname = _text(data, "first_name"), _text(data, "surname")
        test = _text(data, "test", limit=300)
        correct, total = _mark(data)
        scoring = self.app.catalog.scoring
        scaled = scoring.scaled(correct, total)
        domains = data.get("domains")
        self.app.db.insert_result(
            NewResult(
                test=test,
                first_name=first,
                surname=surname,
                correct=correct,
                total=total,
                score=scaled,
                percent=scoring.percent(correct, total),
                passed=scoring.passed(scaled),
                domains=domains if isinstance(domains, dict) else {},
                comments=_text(data, "comments", required=False, limit=MAX_COMMENT_LENGTH),
            )
        )
        self.app.db.close_attempt(test, first, surname)
        self._json({"ok": True})

    def api_add(self) -> None:
        """Manually record an attempt (e.g. one that failed to save)."""
        data = self._read_json()
        correct, total = _mark(data)
        scoring = self.app.catalog.scoring
        scaled = scoring.scaled(correct, total)
        self.app.db.insert_result(
            NewResult(
                test=_text(data, "test", limit=300),
                first_name=_text(data, "first_name"),
                surname=_text(data, "surname"),
                correct=correct,
                total=total,
                score=scaled,
                percent=scoring.percent(correct, total),
                passed=scoring.passed(scaled),
                comments=_text(data, "comments", required=False, limit=MAX_COMMENT_LENGTH),
            )
        )
        self._json({"ok": True})

    def api_delete(self) -> None:
        data = self._read_json()
        if data.get("all"):
            deleted = self.app.db.delete_results(str(data.get("test") or "") or None)
        elif data.get("id") is not None:
            deleted = self.app.db.delete_result(_integer(data, "id"))
        else:
            raise HttpError(HTTPStatus.BAD_REQUEST, "no id")
        self._json({"ok": True, "deleted": deleted})

    def api_import(self) -> None:
        body = self._read_body(self.app.settings.max_upload_bytes)
        if not body:
            raise HttpError(HTTPStatus.BAD_REQUEST, "empty file")
        try:
            rows = parse_spreadsheet(body)
        except SpreadsheetError as exc:
            raise HttpError(HTTPStatus.BAD_REQUEST, str(exc)) from None
        summary: ImportSummary = import_rows(
            rows, self.app.db, self.app.catalog.scoring, self._query("test") or ""
        )
        status = HTTPStatus.OK if summary.ok else HTTPStatus.BAD_REQUEST
        self._json(summary.to_dict(), status)

    # -- logging ------------------------------------------------------------
    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        log.info("%s - %s", self.address_string(), format % args)


def make_handler(app: Application) -> type[RequestHandler]:
    """Bind ``app`` to a handler class (``http.server`` instantiates per request)."""
    return type("BoundRequestHandler", (RequestHandler,), {"app": app})


def create_server(app: Application) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((app.settings.host, app.settings.port), make_handler(app))

