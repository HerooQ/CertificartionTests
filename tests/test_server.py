"""End-to-end tests against a real server bound to an ephemeral port and a
throw-away database (the production results.db is never touched)."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from collections import namedtuple
from dataclasses import replace
from http import HTTPStatus
from pathlib import Path

from certprep.config import Settings
from certprep.server import Application, create_server

Response = namedtuple("Response", "status headers body")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        settings = replace(Settings(), host="127.0.0.1", port=0, db_path=Path(cls._tmp.name) / "t.db")
        cls.app = Application.create(settings)
        cls.httpd = create_server(cls.app)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.exam = next(iter(cls.app.catalog))

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls._tmp.cleanup()

    # -- helpers ---------------------------------------------------------
    def request(self, path, payload=None, raw=None, opener=None):
        data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method="POST" if data is not None else "GET")
        try:
            with (opener or urllib.request.build_opener()).open(req) as resp:
                return Response(resp.status, resp.headers, resp.read())
        except urllib.error.HTTPError as err:
            with err:
                return Response(err.code, err.headers, err.read())

    def post_json(self, path, payload):
        response = self.request(path, payload)
        return response.status, json.loads(response.body)

    def submission(self, **overrides):
        base = {"test": self.exam.name, "first_name": "Ada", "surname": "Lovelace", "correct": 40, "total": 50}
        return {**base, **overrides}

    # -- pages -----------------------------------------------------------
    def test_pages_render(self):
        for path in ("/", f"/exams/{self.exam.slug}", "/report", "/healthz"):
            with self.subTest(path):
                self.assertEqual(self.request(path).status, HTTPStatus.OK)

    def test_exam_page_embeds_config_and_security_headers(self):
        response = self.request(f"/exams/{self.exam.slug}")
        html = response.body.decode()
        self.assertIn('id="exam-config"', html)
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])

    def test_legacy_test_url_redirects(self):
        response = self.request("/tests/test2.html", opener=urllib.request.build_opener(NoRedirect))
        self.assertEqual(response.status, HTTPStatus.MOVED_PERMANENTLY)
        self.assertEqual(response.headers["Location"], "/exams/sc900-practice-2")

    def test_unknown_routes_404(self):
        for path in ("/nope", "/exams/missing", "/api/exams/missing/questions"):
            with self.subTest(path):
                self.assertEqual(self.request(path).status, HTTPStatus.NOT_FOUND)

    def test_static_files_served_with_correct_types_and_no_traversal(self):
        js = self.request("/static/js/exam/main.js")
        self.assertEqual(js.status, HTTPStatus.OK)
        self.assertIn("javascript", js.headers["Content-Type"])
        self.assertEqual(self.request("/static/../server.py").status, HTTPStatus.NOT_FOUND)
        self.assertEqual(self.request("/static/%2e%2e/config.py").status, HTTPStatus.NOT_FOUND)

    def test_question_bank_endpoint(self):
        bank = json.loads(self.request(f"/api/exams/{self.exam.slug}/questions").body)
        self.assertGreaterEqual(len(bank), self.exam.selection.shown_total)

    # -- API -------------------------------------------------------------
    def test_submit_recomputes_score_server_side(self):
        status, body = self.post_json("/api/submit", self.submission(score=1000, passed=True))
        self.assertEqual((status, body), (HTTPStatus.OK, {"ok": True}))
        row = self.app.db.list_results(self.exam.name)[0]
        self.assertEqual((row.score, row.percent, row.passed), (800, 80, True))

    def test_submit_validation(self):
        bad_payloads = [
            self.submission(first_name=""),
            self.submission(correct=51),
            self.submission(total=0),
            self.submission(correct="abc"),
            self.submission(first_name="x" * 500),
        ]
        for payload in bad_payloads:
            with self.subTest(payload):
                status, body = self.post_json("/api/submit", payload)
                self.assertEqual(status, HTTPStatus.BAD_REQUEST)
                self.assertFalse(body["ok"])

    def test_invalid_json_is_rejected(self):
        response = self.request("/api/submit", raw=b"{not json")
        self.assertEqual(response.status, HTTPStatus.BAD_REQUEST)

    def test_timer_survives_reload_and_resets_after_submit(self):
        who = {"test": self.exam.name, "first_name": "Timer", "surname": "Test"}
        first = self.post_json("/api/start", who)[1]
        again = self.post_json("/api/start", who)[1]
        self.assertLessEqual(again["remaining"], first["remaining"])
        self.assertEqual(first["duration"], self.exam.duration_seconds)
        self.post_json("/api/submit", {**who, "correct": 1, "total": 2})
        fresh = self.post_json("/api/start", who)[1]
        self.assertGreaterEqual(fresh["remaining"], self.exam.duration_seconds - 2)

    def test_manual_add_delete_and_export(self):
        self.post_json("/api/add", self.submission(first_name="Manual", comments="by hand"))
        row = next(r for r in self.app.db.list_results() if r.first_name == "Manual")
        csv_text = self.request("/export.csv").body.decode()
        self.assertIn("Manual", csv_text)
        status, body = self.post_json("/api/delete", {"id": row.id})
        self.assertEqual((status, body["deleted"]), (HTTPStatus.OK, 1))

    def test_import_endpoint(self):
        csv_bytes = f'Test,First name,Surname,Correct,Total\n"{self.exam.name}",Imp,Orted,10,20\n'.encode()
        response = self.request("/api/import", raw=csv_bytes)
        self.assertEqual(json.loads(response.body)["imported"], 1)


if __name__ == "__main__":
    unittest.main()
