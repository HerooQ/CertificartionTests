# CertPrep — Proctored Certification Practice Exams

[![CI](https://github.com/HerooQ/CertificartionTests/actions/workflows/ci.yml/badge.svg)](https://github.com/HerooQ/CertificartionTests/actions/workflows/ci.yml)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Dependencies: none](https://img.shields.io/badge/runtime%20dependencies-none-brightgreen)
![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)

A self-hosted exam platform for running **Microsoft SC-900** and **AWS Certified
Cloud Practitioner (CLF-C02)** practice tests for a group of learners. It mirrors
the real exam experience; timed papers, scaled scoring, unscored pretest items,
webcam proctoring and gives the trainer a live results report.

It runs on the **Python standard library only** (no `pip install`) with a
vanilla ES-module front end (no build step).

## Features

- **Realistic exam formats** — SC-900 (50 questions / 45 min) and CLF-C02
  (65 questions / 90 min, of which 15 are unscored pretest items the candidate
  cannot identify). Scaled score out of 1000, pass mark 700.
- **Two paper-building strategies** - *balanced* (round-robin across course
  modules) and *planned* (exact scored/unscored counts per module or by the real
  exam-domain weightings). Every attempt is a fresh random paper with shuffled
  questions and options.
- **Server-enforced timer** - the deadline is stamped server-side once, so
  reloading or reopening the tab cannot reset the clock.
- **Proctoring signals** - mandatory webcam preview, rules acknowledgement, and
  detection of full-screen exits, tab switches and window blur. Violations are
  stored with the result. The camera feed never leaves the browser.
- **Trainer report** - per-test breakdown, filtering, CSV export, manual entry,
  Excel/CSV import (parsed without third-party libraries) and deletion.
- **Per-vendor theming** via CSS design tokens (`data-theme`).

## Quick start

```bash
python -m certprep serve          # http://localhost:8000
```

| URL | Purpose |
| --- | --- |
| `/` | Choose a practice test |
| `/exams/<slug>` | Take an exam, e.g. `/exams/sc900-practice-2` |
| `/report` | Trainer report (filter, export, import, delete) |

Browsers only allow the camera on `localhost` or HTTPS. To let learners on other
machines take an exam, expose the server over HTTPS (for example with an
[ngrok](https://ngrok.com) tunnel to port 8000).

Other commands:

```bash
python -m certprep serve --port 9000   # custom port
python -m certprep validate            # lint the catalog and every question bank
```

### Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `CERTPREP_HOST` | `0.0.0.0` | Interface to bind |
| `CERTPREP_PORT` | `8000` | Port |
| `CERTPREP_DB` | `./results.db` | SQLite results database |
| `CERTPREP_DATA_DIR` | `./data` | Catalog and question banks |

## Project layout

```
certprep/
  cli.py          command-line entry point (serve / validate)
  server.py       HTTP routing, request validation, security headers
  catalog.py      exam groups, selection rules and durations (data/catalog.json)
  questions.py    question-bank loading and validation
  database.py     SQLite repository: results + server-side attempt timers
  scoring.py      scaled-score policy shared by every code path
  importer.py     spreadsheet import (header detection, name splitting)
  spreadsheet.py  dependency-free .xlsx / .csv reader
  reports.py      aggregation and CSV export
  views.py        template rendering (all output escaped)
  templates/      HTML templates
  static/
    css/          design tokens, exam, report, proctoring styles
    js/exam/      paper.js, scoring.js, clock.js, proctor.js, view.js, ...
    js/report.js
data/
  catalog.json    exams, durations, themes, selection rules
  questions/      one JSON bank per exam
tests/            Python unit + end-to-end tests, and tests/js for the front end
```

Design notes:

- **Content is data.** Exams and questions are JSON; adding an exam never
  requires touching code. `python -m certprep validate` checks every bank
  (duplicate options, bad answer indexes, buckets too small for the plan…) and
  runs in CI.
- **Pure core, thin shell.** Paper assembly (`paper.js`) and marking
  (`scoring.js`) are pure functions with an injectable RNG; the DOM layer is
  separate. The server recomputes score, percentage and pass/fail from
  `correct/total` rather than trusting client-supplied values.
- **Safe by default.** Strict Content-Security-Policy (no inline scripts or
  styles), `textContent`-only rendering, escaped templates, request-size limits,
  path-traversal-safe static serving and parameterised SQL.
- **Backwards compatible.** The SQLite schema upgrades in place, and the old
  `/tests/testN.html` URLs redirect to the new routes.

## Adding or editing questions

Each bank is a JSON array in `data/questions/<exam-slug>.json`:

```json
{
  "id": "sc900-practice-2-001",
  "bucket": "M3",
  "domain": "Concepts (security, compliance & identity)",
  "question": "Which technology protects data in transit?",
  "options": ["BitLocker", "TLS/HTTPS", "A hash", "A banned-password list"],
  "answer": [1],
  "explanation": "TLS/HTTPS encrypts data moving across the network."
}
```

- `answer` is a list of zero-based option indexes; more than one makes the item
  multiple-response (must be answered exactly).
- `bucket` is what the selection rules balance on (`M5`, `D2`, …); `domain` is
  the label shown in the per-domain breakdown.

Then run `python -m certprep validate`.

To add a whole exam, append an entry to `data/catalog.json` and drop its bank
into `data/questions/`.

## Testing

```bash
python -m unittest discover -s tests -t .   # 39 Python tests (unit + HTTP end-to-end)
npm test                                    # front-end unit tests (Node 21+, no dependencies)
```

The end-to-end tests start the real server on an ephemeral port with a
throw-away database.

## Limitations

- Scoring happens in the browser and the question bank (including correct
  answers) is delivered to the client. That is fine for friendly practice runs
  but not for high-stakes testing; a hardened version would grade server-side.
- Proctoring is a deterrent, not tamper-proof invigilation — a determined user
  could disable JavaScript or use a second device.
- Results are identified by first name + surname; there is no authentication.

## Privacy

`results.db` holds learners' names and marks. Treat it as personal data: keep it
out of public repositories and back it up like any other data store.

## License

[MIT](LICENSE)
