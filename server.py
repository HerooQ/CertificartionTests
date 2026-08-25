#!/usr/bin/env python3
"""
SC-900 Practice Test server.
Pure Python standard library (no pip installs). Requires Python 3.7+.

Run:  python3 server.py
Then open the printed URL. Students take the tests from that URL so their
first name, surname and mark are written to results.db (SQLite).
Trainer report + CSV export live at /report.
"""
import http.server
import socketserver
import sqlite3
import json
import csv
import io
import os
import datetime
import html as htmlmod
import time
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET
import re

def _urlq(s):
    return urllib.parse.quote(str(s or ""))

PORT = 8000
ROOT = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.join(ROOT, "tests")
DB_PATH = os.path.join(ROOT, "results.db")

# Tests are organised into groups (rendered as sections on the landing page).
# Each group has its own server-enforced exam length.
TEST_GROUPS = [
    {
            "group": "AWS Cloud Computing",
            "blurb": "Certified Cloud Practitioner (CLF-C02)",
            "duration": 90 * 60,          # 90-minute exams (real CLF-C02 length)
            "tests": [
                ("AWS Practice Test 1 (Modules 5-8)", "aws-test1.html"),
                ("AWS Certified Cloud Practitioner - Final Exam (CLF-C02)", "aws-final.html"),
            ],
    },
    {
        "group": "Microsoft SC-900",
        "blurb": "Security, Compliance &amp; Identity Fundamentals",
        "duration": 45 * 60,          # 45-minute exams
        "tests": [
            ("Practice Test 1 (Modules 1-6)",  "test1.html"),
            ("Practice Test 2 (Modules 1-12)", "test2.html"),
            ("Practice Test 3 (Modules 1-18)", "test3.html"),
        ],
    },
    
]

# Flat lookups derived from the groups above.
EXAM_DURATION_SECONDS = 45 * 60       # fallback for any unknown test
TEST_FILES = {}
DURATIONS = {}
for _g in TEST_GROUPS:
    for _name, _fn in _g["tests"]:
        TEST_FILES[_name] = _fn
        DURATIONS[_name] = _g["duration"]

# database
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            test        TEXT NOT NULL,
            first_name  TEXT NOT NULL,
            surname     TEXT NOT NULL,
            correct     INTEGER NOT NULL,
            total       INTEGER NOT NULL,
            score       INTEGER NOT NULL,     -- scaled /1000
            percent     INTEGER NOT NULL,
            passed      INTEGER NOT NULL,      -- 1/0
            domains     TEXT,                  -- JSON per-domain breakdown
            comments    TEXT,                  -- proctoring notes ("" = clean; else flagged)
            created_at  TEXT NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS attempts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            test        TEXT NOT NULL,
            first_name  TEXT NOT NULL,
            surname     TEXT NOT NULL,
            started_at  TEXT NOT NULL,
            ends_at     REAL NOT NULL,        -- epoch seconds (authoritative deadline)
            duration    INTEGER NOT NULL,
            submitted   INTEGER NOT NULL DEFAULT 0
        )
    """)
    # Migrate older databases that predate the comments column.
    cols = [r[1] for r in con.execute("PRAGMA table_info(results)").fetchall()]
    if "comments" not in cols:
        con.execute("ALTER TABLE results ADD COLUMN comments TEXT")
    con.commit()
    con.close()

def insert_result(d):
    con = db()
    con.execute(
        """INSERT INTO results
           (test, first_name, surname, correct, total, score, percent, passed, domains, comments, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            str(d.get("test", "")),
            str(d.get("first_name", "")).strip(),
            str(d.get("surname", "")).strip(),
            int(d.get("correct", 0)),
            int(d.get("total", 0)),
            int(d.get("score", 0)),
            int(d.get("percent", 0)),
            1 if d.get("passed") else 0,
            json.dumps(d.get("domains", {})),
            str(d.get("comments", "") or "").strip(),
            datetime.datetime.now().isoformat(timespec="seconds"),
        ),
    )
    con.commit()
    con.close()

def start_attempt(test, first, surname):
    """Return the authoritative seconds remaining for this student's attempt.
    The deadline is stamped once and reused, so reloading or reopening the tab
    cannot reset the clock. A brand-new attempt is only created after the
    previous one for the same (test, name) has been submitted."""
    now = time.time()
    test = str(test)
    first = str(first).strip()
    surname = str(surname).strip()
    duration = DURATIONS.get(test, EXAM_DURATION_SECONDS)
    con = db()
    row = con.execute(
        """SELECT * FROM attempts
           WHERE test=? AND first_name=? AND surname=? AND submitted=0
           ORDER BY id DESC LIMIT 1""",
        (test, first, surname),
    ).fetchone()
    if row:
        ends_at = row["ends_at"]
    else:
        ends_at = now + duration
        con.execute(
            """INSERT INTO attempts
               (test, first_name, surname, started_at, ends_at, duration, submitted)
               VALUES (?,?,?,?,?,?,0)""",
            (test, first, surname,
             datetime.datetime.now().isoformat(timespec="seconds"),
             ends_at, duration),
        )
        con.commit()
    con.close()
    remaining = int(round(ends_at - now))
    return {"ok": True, "remaining": max(0, remaining), "duration": duration}

def mark_submitted(test, first, surname):
    """Close the open attempt so a later retake gets a fresh deadline."""
    con = db()
    con.execute(
        """UPDATE attempts SET submitted=1
           WHERE test=? AND first_name=? AND surname=? AND submitted=0""",
        (str(test), str(first).strip(), str(surname).strip()),
    )
    con.commit()
    con.close()

def all_results():
    con = db()
    rows = con.execute("SELECT * FROM results ORDER BY created_at DESC, id DESC").fetchall()
    con.close()
    return rows

def delete_result(rid):
    """Delete a single attempt by its row id. Returns number of rows removed."""
    con = db()
    cur = con.execute("DELETE FROM results WHERE id=?", (int(rid),))
    con.commit()
    n = cur.rowcount
    con.close()
    return n

def delete_results(selected_test=None):
    """Delete all attempts, or all attempts for one test. Returns rows removed."""
    con = db()
    if selected_test:
        cur = con.execute("DELETE FROM results WHERE test=?", (str(selected_test),))
    else:
        cur = con.execute("DELETE FROM results")
    con.commit()
    n = cur.rowcount
    con.close()
    return n

# ---- spreadsheet import (standard library only: no openpyxl/pandas needed) ----
def _localname(tag):
    return tag.split("}", 1)[-1]

def _col_index(cellref):
    m = re.match(r"([A-Za-z]+)", cellref or "")
    if not m:
        return None
    n = 0
    for ch in m.group(1).upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1

def read_xlsx(data):
    """Read the first worksheet of an .xlsx file into a list of row lists.
    Uses only zipfile + ElementTree, so no third-party packages are needed."""
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())

    shared = []
    if "xl/sharedStrings.xml" in names:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root:
            if _localname(si.tag) != "si":
                continue
            shared.append("".join(
                (t.text or "") for t in si.iter() if _localname(t.tag) == "t"))

    # Resolve the first worksheet target (fall back to sheet1.xml).
    target = "xl/worksheets/sheet1.xml"
    try:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        sheets = [e for e in wb.iter() if _localname(e.tag) == "sheet"]
        rid = None
        if sheets:
            for k, v in sheets[0].attrib.items():
                if _localname(k) == "id":
                    rid = v
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        idmap = {rel.attrib.get("Id"): rel.attrib.get("Target") for rel in rels}
        tgt = idmap.get(rid)
        if tgt:
            tgt = tgt.lstrip("/")
            target = tgt if tgt.startswith("xl/") else "xl/" + tgt
    except Exception:
        pass
    if target not in names:
        cands = sorted(n for n in names
                       if n.startswith("xl/worksheets/") and n.endswith(".xml"))
        if cands:
            target = cands[0]

    sheet = ET.fromstring(z.read(target))
    rows = []
    for row in sheet.iter():
        if _localname(row.tag) != "row":
            continue
        cells, maxc, seq = {}, -1, 0
        for c in row:
            if _localname(c.tag) != "c":
                continue
            ci = _col_index(c.attrib.get("r", ""))
            if ci is None:
                ci = seq
            seq = ci + 1
            t = c.attrib.get("t")
            if t == "inlineStr":
                val = "".join((x.text or "") for x in c.iter()
                              if _localname(x.tag) == "t")
            else:
                vtext = ""
                for x in c:
                    if _localname(x.tag) == "v":
                        vtext = x.text or ""
                        break
                if t == "s":
                    try:
                        val = shared[int(vtext)]
                    except Exception:
                        val = ""
                else:
                    val = vtext
            cells[ci] = val
            maxc = max(maxc, ci)
        rows.append([cells.get(i, "") for i in range(maxc + 1)])
    return rows

def parse_spreadsheet(data):
    """Return a list of row lists from raw .xlsx or .csv/.tsv bytes."""
    if data[:4] == b"PK\x03\x04":          # xlsx is a zip archive
        return read_xlsx(data)
    text = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except Exception:
            text = None
    if text is None:
        text = data.decode("utf-8", "replace")
    lines = text.splitlines()
    delim = "\t" if (lines and lines[0].count("\t") > lines[0].count(",")) else ","
    return [r for r in csv.reader(io.StringIO(text), delimiter=delim)]

_HEADER_SYNONYMS = {
    "test":       ["test", "exam", "test name", "paper"],
    "first_name": ["first name", "first", "firstname", "given name", "first names"],
    "surname":    ["surname", "last name", "lastname", "family name", "last"],
    "name":       ["name", "student", "full name", "student name", "candidate"],
    "correct":    ["correct", "marks", "correct answers", "score correct", "right", "raw"],
    "total":      ["total", "out of", "questions", "total questions", "max", "no. questions"],
    "score":      ["score", "scaled", "scaled score", "score /1000", "scaled /1000"],
    "percent":    ["percent", "percentage", "%", "pct"],
    "comments":   ["comments", "comment", "notes", "note"],
}

def _norm_header(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower()).strip(" .:_-")

def _map_headers(header_row):
    mapping = {}
    for idx, cell in enumerate(header_row):
        h = _norm_header(cell)
        for key, syns in _HEADER_SYNONYMS.items():
            if h in syns and key not in mapping:
                mapping[key] = idx
    return mapping

def import_rows(rows, default_test=""):
    """Insert attempts from parsed spreadsheet rows. Everyone is imported clean
    (empty comments) unless the sheet has a Comments column with a value.
    Returns a summary dict."""
    default_test = str(default_test or "").strip()
    # Find the header row within the first few rows.
    header_idx, mapping = None, {}
    for i, row in enumerate(rows[:8]):
        m = _map_headers(row)
        if ("first_name" in m or "name" in m) and (
                "test" in m or "score" in m or "correct" in m or default_test):
            header_idx, mapping = i, m
            break
    if header_idx is None:
        return {"ok": False, "error":
                "Couldn't find a header row. Expected columns like "
                "Test, First name, Surname, Correct, Total."}

    imported, skipped, errors = 0, 0, []

    def cell(row, key):
        j = mapping.get(key)
        return (row[j].strip() if j is not None and j < len(row) and row[j] is not None else "")

    for n, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if not any((str(c).strip() for c in row)):
            continue  # blank line
        test = cell(row, "test") or default_test
        first = cell(row, "first_name")
        surname = cell(row, "surname")
        if not first and "name" in mapping:      # combined name column
            raw = cell(row, "name")
            if "," in raw:                        # "Surname, First"
                surname, first = [p.strip() for p in raw.split(",", 1)]
            elif raw:
                parts = raw.split()
                first = parts[0]
                surname = " ".join(parts[1:])
        if not test or not first or not surname:
            skipped += 1
            errors.append(f"Row {n}: missing test or name")
            continue

        def as_int(v):
            v = str(v).strip().replace("%", "")
            if v == "":
                return None
            try:
                return int(round(float(v)))
            except Exception:
                return None

        correct = as_int(cell(row, "correct"))
        total = as_int(cell(row, "total"))
        score = as_int(cell(row, "score"))

        if correct is not None and total and total > 0:
            correct = max(0, min(correct, total))
            score = round(correct / total * 1000)
            percent = round(correct / total * 100)
        elif score is not None:
            total = total if total and total > 0 else 50
            percent = round(score / 10)
            correct = round(score / 1000 * total)
        else:
            skipped += 1
            errors.append(f"Row {n}: no Correct/Total or Score")
            continue

        insert_result({
            "test": test, "first_name": first, "surname": surname,
            "correct": correct, "total": total, "score": score,
            "percent": percent, "passed": 1 if score >= 700 else 0,
            "domains": {}, "comments": cell(row, "comments"),  # blank => clean
        })
        imported += 1

    return {"ok": True, "imported": imported, "skipped": skipped,
            "errors": errors[:10]}

def import_template_csv():
    example_test = next(iter(TEST_FILES.keys()), "Practice Test 1 (Modules 1-6)")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Test", "First name", "Surname", "Correct", "Total", "Comments"])
    w.writerow([example_test, "Ada", "Lovelace", 42, 50, ""])
    w.writerow([example_test, "Alan", "Turing", 47, 50, ""])
    return buf.getvalue().encode("utf-8")

# pages
def landing_page():
    groups_html = ""
    for g in TEST_GROUPS:
        mins = g["duration"] // 60
        cards = "".join(
            f'<a class="tcard" href="/tests/{fn}"><span class="tt">{htmlmod.escape(name)}</span>'
            f'<span class="go">Start →</span></a>'
            for name, fn in g["tests"]
        )
        groups_html += (
            f'<div class="group">'
            f'<div class="ghead"><span class="gname">{htmlmod.escape(g["group"])}</span>'
            f'<span class="gblurb">{g["blurb"]} · {mins}-minute exams</span></div>'
            f'{cards}</div>'
        )
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Practice Exams</title>
<style>{BASE_CSS}
.group{{margin:22px 0 8px}}
.ghead{{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;border-bottom:2px solid var(--line);padding-bottom:8px;margin-bottom:6px}}
.gname{{font-weight:800;font-size:18px}}
.gblurb{{color:var(--muted);font-size:13px;font-weight:600}}
.tcard{{display:flex;justify-content:space-between;align-items:center;text-decoration:none;color:var(--ink);
 background:#fff;border:1px solid var(--line);border-radius:12px;padding:20px 24px;margin:12px 0;transition:.12s}}
.tcard:hover{{border-color:var(--azure);background:#f5fbff}}
.tcard .tt{{font-weight:700;font-size:17px}} .tcard .go{{color:var(--azure);font-weight:700}}
</style></head><body><div class="wrap">
<div><span class="logo"><i style="background:var(--red)"></i><i style="background:var(--green)"></i>
<i style="background:var(--blue)"></i><i style="background:var(--yellow)"></i></span>
<span class="tag">CERTIFICATION PRACTICE EXAMS</span></div>
<h1>Choose a practice test</h1>
<p class="sub">Enter your name on the test intro screen, your mark is recorded automatically when you submit.</p>
{groups_html}
</div></body></html>"""

def _comment_of(r):
    try:
        return (r["comments"] or "").strip()
    except (IndexError, KeyError):
        return ""

def report_page(selected_test=None):
    all_rows = all_results()
    # Known tests for the filter dropdown: everything defined, plus any legacy
    # names that appear in the data.
    known = list(TEST_FILES.keys())
    for r in all_rows:
        if r["test"] not in known:
            known.append(r["test"])

    if selected_test and selected_test in known:
        rows = [r for r in all_rows if r["test"] == selected_test]
    else:
        selected_test = None
        rows = all_rows

    total_attempts = len(rows)
    flagged = sum(1 for r in rows if _comment_of(r))
    # summary stats (reflect the current filter)
    if total_attempts:
        avg_pct = round(sum(r["percent"] for r in rows) / total_attempts)
        avg_score = round(sum(r["score"] for r in rows) / total_attempts)
        pass_rate = round(sum(r["passed"] for r in rows) / total_attempts * 100)
    else:
        avg_pct = avg_score = pass_rate = 0

    # per-test summary is always across everything (it IS the overview)
    per_test = {}
    for r in all_rows:
        t = r["test"]
        s = per_test.setdefault(t, {"n": 0, "pass": 0, "score": 0, "flag": 0})
        s["n"] += 1; s["pass"] += r["passed"]; s["score"] += r["score"]
        if _comment_of(r):
            s["flag"] += 1

    stat_cards = f"""
      <div class="stat"><div class="statn">{total_attempts}</div><div class="statl">Attempts recorded</div></div>
      <div class="stat"><div class="statn">{avg_score}<span class="u">/1000</span></div><div class="statl">Average scaled score</div></div>
      <div class="stat"><div class="statn">{avg_pct}<span class="u">%</span></div><div class="statl">Average correct</div></div>
      <div class="stat"><div class="statn">{pass_rate}<span class="u">%</span></div><div class="statl">Pass rate (≥700)</div></div>
      <div class="stat{' flagcard' if flagged else ''}"><div class="statn">{flagged}</div><div class="statl">Flagged for cheating</div></div>
    """

    per_test_rows = "".join(
        f'<tr><td>{htmlmod.escape(t)}</td><td>{s["n"]}</td>'
        f'<td>{round(s["score"]/s["n"])}</td>'
        f'<td>{round(s["pass"]/s["n"]*100)}%</td>'
        f'<td>{("<strong style=\'color:#8a2410\'>"+str(s["flag"])+"</strong>") if s["flag"] else "0"}</td></tr>'
        for t, s in per_test.items()
    ) or '<tr><td colspan="5" class="empty">No attempts yet.</td></tr>'

    # filter dropdown
    opts = '<option value="">All tests</option>' + "".join(
        f'<option value="{htmlmod.escape(t)}"{" selected" if t == selected_test else ""}>'
        f'{htmlmod.escape(t)}</option>'
        for t in known
    )
    # options for the manual "add record" form (a real test must be chosen)
    add_opts = "".join(
        f'<option value="{htmlmod.escape(t)}"'
        f'{" selected" if t == selected_test else ""}>{htmlmod.escape(t)}</option>'
        for t in known
    ) or '<option value="">(no tests defined)</option>'

    body_rows = ""
    for r in rows:
        badge = '<span class="pill pass">PASS</span>' if r["passed"] else '<span class="pill fail">FAIL</span>'
        when = htmlmod.escape(r["created_at"].replace("T", " "))
        note = _comment_of(r)
        if note:
            note_cell = f'<span class="pill flag">⚑ {htmlmod.escape(note)}</span>'
            rowcls = ' class="flagrow"'
        else:
            note_cell = '<span class="ok">Clean</span>'
            rowcls = ''
        body_rows += (
            f"<tr{rowcls}><td>{when}</td>"
            f"<td>{htmlmod.escape(r['surname'])}, {htmlmod.escape(r['first_name'])}</td>"
            f"<td>{htmlmod.escape(r['test'])}</td>"
            f"<td>{r['correct']}/{r['total']}</td>"
            f"<td><strong>{r['score']}</strong></td>"
            f"<td>{r['percent']}%</td>"
            f"<td>{badge}</td>"
            f"<td>{note_cell}</td>"
            f'<td class="noprint"><button class="del" onclick="delRow({r["id"]})">Delete</button></td></tr>'
        )
    if not body_rows:
        body_rows = '<tr><td colspan="9" class="empty">No results recorded for this filter yet.</td></tr>'

    export_href = "/export.csv" + (f"?test={_urlq(selected_test)}" if selected_test else "")
    heading = f"All attempts — {htmlmod.escape(selected_test)}" if selected_test else "All attempts"

    sel_js = "null" if not selected_test else json.dumps(selected_test)
    delete_js = (
        "<script>\n"
        "var SELECTED_TEST=" + sel_js + ";\n"
        "var SHOWN_COUNT=" + str(total_attempts) + ";\n"
        "function delRow(id){\n"
        "  if(!confirm('Delete this attempt permanently? This cannot be undone.')) return;\n"
        "  fetch('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({id:id})})\n"
        "    .then(function(r){return r.json();})\n"
        "    .then(function(j){ if(j&&j.ok){ location.reload(); } else { alert('Delete failed.'); } })\n"
        "    .catch(function(){ alert('Delete failed \u2014 is the server running?'); });\n"
        "}\n"
        "function delAllShown(){\n"
        "  if(SHOWN_COUNT===0){ alert('There are no attempts to delete.'); return; }\n"
        "  var what = SELECTED_TEST ? ('all '+SHOWN_COUNT+' attempts for \\''+SELECTED_TEST+'\\'')"
        " : ('ALL '+SHOWN_COUNT+' attempts across every test');\n"
        "  if(!confirm('Delete '+what+'? This cannot be undone.')) return;\n"
        "  if(!confirm('Are you sure? This permanently removes '+what+'.')) return;\n"
        "  fetch('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({all:true,test:SELECTED_TEST})})\n"
        "    .then(function(r){return r.json();})\n"
        "    .then(function(j){ if(j&&j.ok){ location.href = SELECTED_TEST ?"
        " ('/report?test='+encodeURIComponent(SELECTED_TEST)) : '/report'; }"
        " else { alert('Delete failed.'); } })\n"
        "    .catch(function(){ alert('Delete failed \u2014 is the server running?'); });\n"
        "}\n"
        "</script>"
    )

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Practice Exam Results</title>
<style>{BASE_CSS}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin:18px 0}}
.stat{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px 20px}}
.stat.flagcard{{border-color:#e0902f;background:#fff7ec}}
.statn{{font-size:30px;font-weight:800}} .statn .u{{font-size:15px;font-weight:600;color:var(--gray)}}
.statl{{color:var(--gray);font-size:13px;margin-top:2px}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden}}
th,td{{text-align:left;padding:11px 14px;font-size:14px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{background:var(--light);font-size:12px;letter-spacing:.4px;text-transform:uppercase;color:var(--gray)}}
tr:last-child td{{border-bottom:none}}
.flagrow{{background:#fff7ec}}
.pill{{font-size:11px;font-weight:800;border-radius:6px;padding:2px 9px;display:inline-block}}
.pill.pass{{background:#e3f0cf;color:#3f5c00}} .pill.fail{{background:#fdd8d3;color:#8a2410}}
.pill.flag{{background:#fbe0c4;color:#8a4a10;font-weight:700;white-space:normal;line-height:1.4}}
.ok{{color:var(--muted);font-size:13px}}
.del{{background:#fdd8d3;color:#8a2410;border:1px solid #f3b6ab;border-radius:6px;padding:5px 11px;
 font-family:inherit;font-size:12px;font-weight:700;cursor:pointer}}
.del:hover{{background:#f9c2b9}}
.btnlink.danger{{background:#c0392b;color:#fff}} .btnlink.danger:hover{{background:#a5301f}}
.empty{{color:var(--muted);text-align:center;padding:26px}}
.toolbar{{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:6px 0 18px}}
.filterbar{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:8px 0 2px}}
.filterbar select{{font-family:inherit;font-size:14px;padding:8px 12px;border:1px solid var(--line);
 border-radius:8px;background:#fff;color:var(--ink);font-weight:600}}
.filterbar label{{font-size:13px;color:var(--gray);font-weight:700}}
.autolbl{{display:inline-flex;align-items:center;gap:7px;font-size:13px;color:var(--gray);font-weight:700}}
.autolbl input{{width:16px;height:16px}}
.addbox{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:0 16px;margin:6px 0 20px}}
.addbox summary{{cursor:pointer;font-weight:700;padding:14px 0;font-size:14px;color:var(--azure)}}
.addbox[open] summary{{border-bottom:1px solid var(--line);margin-bottom:14px}}
.addgrid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;padding-bottom:6px}}
.addgrid label{{display:flex;flex-direction:column;gap:4px;font-size:12px;font-weight:700;color:var(--gray)}}
.addgrid label.wide{{grid-column:1/-1}}
.addgrid input,.addgrid select{{font-family:inherit;font-size:14px;padding:8px 10px;border:1px solid var(--line);
 border-radius:8px;background:#fff;color:var(--ink);font-weight:600}}
.addfoot{{display:flex;align-items:center;gap:12px;padding:4px 0 16px}}
@media print{{.noprint{{display:none}}}}
</style></head><body><div class="wrap">
<div class="noprint"><a class="btnlink ghostlink" href="/">← Tests</a></div>
<h1>Results report</h1>
<p class="sub">All recorded attempts across the SC-900 and AWS practice tests. Flagged rows indicate possible cheating detected during a proctored attempt.</p>
<div class="stats">{stat_cards}</div>

<h2>By test</h2>
<table><thead><tr><th>Test</th><th>Attempts</th><th>Avg score</th><th>Pass rate</th><th>Flagged</th></tr></thead>
<tbody>{per_test_rows}</tbody></table>

<h2>{heading}</h2>
<div class="filterbar noprint">
  <label for="testfilter">Filter by test</label>
  <select id="testfilter" onchange="if(this.value){{location.href='/report?test='+encodeURIComponent(this.value)}}else{{location.href='/report'}}">{opts}</select>
</div>
<div class="toolbar noprint">
  <a class="btnlink" href="{export_href}">⬇ Export CSV</a>
  <button class="btnlink ghostlink" onclick="window.print()">🖨 Print</button>
  <button class="btnlink danger" onclick="delAllShown()">🗑 Delete all shown</button>
  <label class="autolbl"><input type="checkbox" id="autochk"> Auto-refresh (10s)</label>
</div>
<details class="addbox noprint" id="addbox">
  <summary>➕ Add a record manually</summary>
  <p class="sub" style="margin:.2em 0 12px">Use this if an attempt didn't save (e.g. a student lost connection). The scaled score, %, and pass/fail are worked out for you from correct ÷ total.</p>
  <div class="addgrid">
    <label class="wide">Test<select id="a_test">{add_opts}</select></label>
    <label>First name<input id="a_first" autocomplete="off"></label>
    <label>Surname<input id="a_surname" autocomplete="off"></label>
    <label>Correct<input id="a_correct" type="number" min="0" step="1"></label>
    <label>Total<input id="a_total" type="number" min="1" step="1" value="50"></label>
    <label class="wide">Comments (optional)<input id="a_comments" autocomplete="off" placeholder="e.g. added by hand — submit failed"></label>
  </div>
  <div class="addfoot">
    <button class="btnlink" onclick="addRecord()">Save record</button>
    <span id="a_msg" class="ok"></span>
  </div>
</details>
<details class="addbox noprint" id="importbox">
  <summary>📥 Import from a spreadsheet (Excel or CSV)</summary>
  <p class="sub" style="margin:.2em 0 12px">Upload an <strong>.xlsx</strong> or <strong>.csv</strong> with columns <em>Test, First name, Surname, Correct, Total</em> (Comments optional). Everyone is imported clean unless a Comments column has a value. <a href="/import_template.csv">Download a template</a>.</p>
  <div class="addgrid">
    <label class="wide">Spreadsheet file<input type="file" id="imp_file" accept=".xlsx,.csv,.tsv,.txt"></label>
    <label class="wide">Default test — used for rows whose Test cell is blank (optional)
      <select id="imp_test"><option value="">— none —</option>{add_opts}</select></label>
  </div>
  <div class="addfoot">
    <button class="btnlink" onclick="importFile()">Import file</button>
    <span id="imp_msg" class="ok"></span>
  </div>
</details>
<table><thead><tr><th>When</th><th>Student</th><th>Test</th><th>Correct</th><th>Score</th><th>%</th><th>Result</th><th>Proctoring</th><th class="noprint">Actions</th></tr></thead>
<tbody>{body_rows}</tbody></table>
{delete_js}
<script>
(function(){{
  /* ---- manual add ---- */
  function v(id){{ var e=document.getElementById(id); return e?e.value:''; }}
  function msg(t){{ var m=document.getElementById('a_msg'); if(m) m.textContent=t; }}
  window.addRecord=function(){{
    var t=v('a_test'), f=v('a_first').trim(), s=v('a_surname').trim();
    var c=parseInt(v('a_correct'),10), tot=parseInt(v('a_total'),10);
    if(!t){{ msg('Choose a test.'); return; }}
    if(!f||!s){{ msg('Enter first name and surname.'); return; }}
    if(isNaN(c)||isNaN(tot)||tot<=0||c<0||c>tot){{ msg('Check correct/total (0 \u2264 correct \u2264 total).'); return; }}
    msg('Saving\u2026');
    fetch('/api/add',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{test:t,first_name:f,surname:s,correct:c,total:tot,comments:v('a_comments')}})}})
      .then(function(r){{return r.json();}})
      .then(function(j){{ if(j&&j.ok){{ location.reload(); }} else {{ msg('Save failed.'); }} }})
      .catch(function(){{ msg('Save failed \u2014 is the server running?'); }});
  }};

  /* ---- import from spreadsheet ---- */
  function impMsg(t){{ var m=document.getElementById('imp_msg'); if(m) m.textContent=t; }}
  window.importFile=function(){{
    var fi=document.getElementById('imp_file');
    if(!fi||!fi.files||!fi.files[0]){{ impMsg('Choose a file first.'); return; }}
    var file=fi.files[0];
    var dt=document.getElementById('imp_test').value;
    impMsg('Importing\u2026');
    file.arrayBuffer().then(function(buf){{
      var url='/api/import?name='+encodeURIComponent(file.name)+(dt?('&test='+encodeURIComponent(dt)):'');
      return fetch(url,{{method:'POST',headers:{{'Content-Type':'application/octet-stream'}},body:buf}});
    }}).then(function(r){{return r.json();}}).then(function(j){{
      if(j&&j.ok){{
        impMsg('Imported '+j.imported+(j.skipped?(' \u2014 skipped '+j.skipped+' (see below)'):'')+'.');
        if(j.errors&&j.errors.length){{ console.log('Import skipped:',j.errors); }}
        setTimeout(function(){{ location.reload(); }}, 1000);
      }} else {{ impMsg('Import failed: '+((j&&j.error)||'unknown format')); }}
    }}).catch(function(){{ impMsg('Import failed \u2014 is the server running?'); }});
  }};

  /* ---- auto-refresh every 10s (paused while you're editing) ---- */
  var KEY='report_autorefresh';
  function on(){{ try{{ return localStorage.getItem(KEY)!=='0'; }}catch(e){{ return true; }} }}
  function setOn(x){{ try{{ localStorage.setItem(KEY, x?'1':'0'); }}catch(e){{}} }}
  var chk=document.getElementById('autochk');
  if(chk){{ chk.checked=on(); chk.addEventListener('change',function(){{ setOn(chk.checked); }}); }}
  function busy(){{
    var boxes=document.querySelectorAll('details.addbox');
    for(var i=0;i<boxes.length;i++){{ if(boxes[i].open) return true; }}  // a panel is open
    var a=document.activeElement;
    if(a && /^(INPUT|SELECT|TEXTAREA)$/.test(a.tagName)) return true;
    if(window.getSelection && String(window.getSelection())) return true;
    return false;
  }}
  setInterval(function(){{
    if(on() && !busy()) location.reload();
  }}, 10000);
}})();
</script>
</div></body></html>"""

def export_csv(selected_test=None):
    rows = all_results()
    if selected_test:
        rows = [r for r in rows if r["test"] == selected_test]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Timestamp", "First name", "Surname", "Test", "Correct", "Total",
                "Score /1000", "Percent", "Passed", "Comments"])
    for r in rows:
        w.writerow([r["created_at"], r["first_name"], r["surname"], r["test"],
                    r["correct"], r["total"], r["score"], r["percent"],
                    "Yes" if r["passed"] else "No", _comment_of(r)])
    return buf.getvalue().encode("utf-8")

BASE_CSS = """
:root{--red:#F25022;--green:#7FBA00;--blue:#00A4EF;--yellow:#FFB900;--azure:#0078D4;--ink:#242424;--gray:#605E5C;--muted:#8A8886;--light:#F3F2F1;--line:#E1DFDD;}
*{box-sizing:border-box}
body{margin:0;font-family:'Segoe UI',system-ui,-apple-system,Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:#faf9f8;line-height:1.5}
.wrap{max-width:960px;margin:0 auto;padding:28px}
.logo{display:inline-grid;grid-template-columns:14px 14px;grid-gap:3px;vertical-align:middle;margin-right:10px}
.logo i{width:14px;height:14px;display:block}
h1{font-size:26px;margin:.2em 0}h2{font-size:18px;margin:1.1em 0 .4em}
.sub{color:var(--gray);font-size:15px}
.tag{font-size:12px;color:var(--muted);font-weight:700;letter-spacing:1px}
.btnlink{display:inline-block;text-decoration:none;background:var(--azure);color:#fff;border:none;border-radius:8px;
 padding:10px 18px;font-weight:700;font-size:14px;font-family:inherit;cursor:pointer}
.btnlink:hover{background:#106ebe}
.ghostlink{background:var(--light);color:var(--ink)}.ghostlink:hover{background:#e8e6e4}
"""

# Proctoring webcam widget. Injected into every served test page (before </body>)
# so all tests get it without editing each HTML file. Purely a simulation aid:
# the feed stays in the browser and is never uploaded or recorded anywhere.
# Note: getUserMedia only works over HTTPS or localhost -- fine via ngrok.
PROCTOR_SNIPPET = """
<style>
#proctorCam{position:fixed;top:14px;right:14px;z-index:9999;width:200px;
  background:#111;border:1px solid #333;border-radius:10px;overflow:hidden;
  box-shadow:0 6px 22px rgba(0,0,0,.35);font-family:'Segoe UI',system-ui,sans-serif;
  display:none}
#proctorCam.show{display:block}
#proctorCam video{display:block;width:100%;height:150px;object-fit:cover;
  background:#000;transform:scaleX(-1)}
#proctorCam .pc-bar{display:flex;align-items:center;gap:6px;padding:5px 8px;
  background:#1b1b1b;color:#eee;font-size:11px;font-weight:600}
#proctorCam .pc-dot{width:8px;height:8px;border-radius:50%;background:#e60000;
  animation:pcblink 1.2s infinite}
#proctorCam .pc-rec{color:#ff6b6b;font-weight:800;letter-spacing:.5px}
#proctorCam .pc-name{margin-left:auto;color:#bbb;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;max-width:110px}
@keyframes pcblink{0%,49%{opacity:1}50%,100%{opacity:.15}}
#proctorToast{position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:10000;
  background:#8a1c10;color:#fff;font-family:'Segoe UI',system-ui,sans-serif;font-weight:700;
  font-size:14px;padding:12px 18px;border-radius:10px;box-shadow:0 6px 22px rgba(0,0,0,.35);
  display:none;max-width:90vw;text-align:center}
#proctorToast.show{display:block;animation:pctoast .25s ease}
@keyframes pctoast{from{opacity:0;transform:translate(-50%,-8px)}to{opacity:1;transform:translate(-50%,0)}}
#rulesScreen ul{margin:10px 0 0;padding-left:20px}
#rulesScreen li{margin:7px 0}
#rulesScreen .warn{color:#8a2410;font-weight:700}
#rulesScreen .ack{display:flex;align-items:flex-start;gap:9px;margin:18px 0 4px;font-weight:600}
#rulesScreen .ack input{margin-top:3px;width:17px;height:17px}
@media print{#proctorCam,#proctorToast{display:none!important}}
</style>
<div id="proctorCam" aria-hidden="true">
  <video id="proctorVideo" autoplay playsinline muted></video>
  <div class="pc-bar"><span class="pc-dot"></span><span class="pc-rec">REC</span>
    <span class="pc-name" id="proctorName">Candidate</span></div>
</div>
<div id="proctorToast" role="alert"></div>
<script>
(function(){
  var box=document.getElementById('proctorCam');
  var video=document.getElementById('proctorVideo');
  var nameEl=document.getElementById('proctorName');
  var toast=document.getElementById('proctorToast');
  var stream=null, tracking=false, toastTimer=null;
  var methods={};   // label -> count of violations

  function currentName(){
    try{ if(typeof STUDENT!=='undefined' && STUDENT){
      return ((STUDENT.first||'')+' '+(STUDENT.surname||'')).trim(); } }catch(e){}
    return '';
  }
  function label(){ var n=currentName(); if(n) nameEl.textContent=n; }

  /* ---- camera ---- */
  function camReady(){
    return !!(stream && stream.getTracks && stream.getTracks().some(function(t){
      return t.readyState==='live'; }));
  }
  function ensureCamera(){
    if(camReady()){ return Promise.resolve(true); }
    if(!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia){
      return Promise.resolve(false);
    }
    return navigator.mediaDevices.getUserMedia({video:{width:320,height:240},audio:false})
      .then(function(s){ stream=s; video.srcObject=s; return true; })
      .catch(function(){ return false; });
  }
  function stopCamera(){
    if(stream){ stream.getTracks().forEach(function(t){t.stop();}); stream=null; }
  }

  /* ---- widget show/hide follows exam & results ---- */
  var exam=document.getElementById('exam');
  var results=document.getElementById('results');
  function visible(el){ return el && !el.classList.contains('hidden'); }
  function syncCam(){
    if(visible(exam)||visible(results)){ box.classList.add('show'); label(); }
    else { box.classList.remove('show'); }
    if(visible(results)){ stopTracking(); }   // exam is over
  }
  var obs=new MutationObserver(syncCam);
  if(exam) obs.observe(exam,{attributes:true,attributeFilter:['class']});
  if(results) obs.observe(results,{attributes:true,attributeFilter:['class']});

  /* ---- cheating watcher ---- */
  function showToast(msg){
    toast.textContent='\u26A0 '+msg+' \u2014 this has been flagged.';
    toast.classList.add('show');
    if(toastTimer) clearTimeout(toastTimer);
    toastTimer=setTimeout(function(){ toast.classList.remove('show'); }, 4000);
  }
  function flag(kind){
    if(!tracking) return;
    methods[kind]=(methods[kind]||0)+1;
    showToast(kind);
  }
  var lastHidden=0;
  function onVisibility(){
    if(!tracking) return;
    if(document.visibilityState==='hidden'){
      lastHidden=Date.now();
      flag('Switched tab or minimised the window');
    }
  }
  function onBlur(){
    if(!tracking) return;
    // Ignore the blur that rides along with a tab switch we already logged.
    if(Date.now()-lastHidden < 600) return;
    flag('Left the exam window (another app or window)');
  }
  function onFsChange(){
    if(!tracking) return;
    var fs=document.fullscreenElement||document.webkitFullscreenElement;
    if(!fs){ flag('Exited full-screen'); }
  }
  function startTracking(){
    methods={}; tracking=true; lastHidden=0;
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('blur', onBlur);
    document.addEventListener('fullscreenchange', onFsChange);
    document.addEventListener('webkitfullscreenchange', onFsChange);
  }
  function stopTracking(){
    tracking=false;
    document.removeEventListener('visibilitychange', onVisibility);
    window.removeEventListener('blur', onBlur);
    document.removeEventListener('fullscreenchange', onFsChange);
    document.removeEventListener('webkitfullscreenchange', onFsChange);
  }
  function buildComments(){
    var keys=Object.keys(methods);
    if(!keys.length) return '';
    var parts=keys.map(function(k){
      var n=methods[k]; return k+(n>1?(' ('+n+'\u00D7)'):'');
    });
    return 'CHEATING FLAGGED \u2014 '+parts.join('; ');
  }

  /* ---- attach comments to the submit request, whatever triggers it ---- */
  var _fetch=window.fetch;
  window.fetch=function(url,opts){
    try{
      var u=(typeof url==='string')?url:(url&&url.url)||'';
      if(u.indexOf('/api/submit')>-1 && opts && opts.body){
        var payload=JSON.parse(opts.body);
        payload.comments=buildComments();
        opts=Object.assign({},opts,{body:JSON.stringify(payload)});
        stopTracking();   // don't count the fullscreen-exit that submit itself causes
        return _fetch.call(this,url,opts);
      }
    }catch(e){}
    return _fetch.apply(this,arguments);
  };

  /* ---- rules screen (built here so no per-test HTML edits are needed) ---- */
  var rules=null;
  function buildRules(){
    var intro=document.getElementById('intro');
    if(!intro || document.getElementById('rulesScreen')) return;
    rules=document.createElement('div');
    rules.id='rulesScreen';
    rules.className='card hidden';
    rules.innerHTML=
      '<div><span class="tag">PROCTORED EXAM RULES</span></div>'+
      '<h1 style="margin:.2em 0">Before you begin</h1>'+
      '<p class="sub">This attempt is proctored. Please read the rules, your '+
      'webcam is on and the following are automatically detected and recorded '+
      'against your result:</p>'+
      '<ul>'+
        '<li><span class="warn">Stay in full-screen</span> for the entire exam. '+
          'Leaving full-screen is flagged.</li>'+
        '<li><span class="warn">Do not switch tabs, minimise, or open other apps '+
          'or windows.</span> Doing so is flagged with the method used.</li>'+
        '<li><span class="warn">Keep your camera on</span> with your face visible '+
          'throughout.</li>'+
        '<li>The timer keeps running the whole time, leaving the exam does '+
          '<strong>not</strong> pause it.</li>'+
      '</ul>'+
      '<label class="ack"><input type="checkbox" id="ackChk">'+
        '<span>I understand these rules and agree that any of the above will be '+
        'recorded and flagged as a possible cheating attempt.</span></label>'+
      '<div style="margin-top:14px;display:flex;gap:10px;flex-wrap:wrap">'+
        '<button class="ghost" id="rulesBack">\u2190 Back</button>'+
        '<button class="primary" id="rulesBegin" disabled>Begin exam \u2192</button>'+
      '</div>';
    intro.parentNode.insertBefore(rules, intro.nextSibling);
    var chk=rules.querySelector('#ackChk');
    var beginBtn=rules.querySelector('#rulesBegin');
    chk.addEventListener('change', function(){ beginBtn.disabled=!chk.checked; });
    beginBtn.addEventListener('click', function(){
      if(chk.disabled) return;
      rules.classList.add('hidden');
      if(typeof window.startExam==='function'){
        startTracking();       // arm the watcher, then go fullscreen + show exam
        window.startExam();
        // If fullscreen didn't take (browser blocked it), that's on the student;
        // any later exit/tab-switch is still flagged.
        label();
      }
    });
    rules.querySelector('#rulesBack').addEventListener('click', function(){
      rules.classList.add('hidden');
      stopCamera();
      intro.classList.remove('hidden');
      window.scrollTo(0,0);
    });
  }
  function showRules(){
    buildRules();
    document.getElementById('intro').classList.add('hidden');
    if(rules){
      var chk=rules.querySelector('#ackChk'); var b=rules.querySelector('#rulesBegin');
      if(chk){ chk.checked=false; } if(b){ b.disabled=true; }
      rules.classList.remove('hidden');
    }
    window.scrollTo(0,0);
  }

  /* ---- gate Start-exam: name + camera, THEN rules (fullscreen comes later) ---- */
  function installGate(){
    window.beginExam=function(){
      var fEl=document.getElementById('fname'), sEl=document.getElementById('sname');
      var f=(fEl&&fEl.value||''), s=(sEl&&sEl.value||'');
      if(!f.trim()||!s.trim()){
        alert('Please enter your first name and surname before starting the exam.');
        return;
      }
      try{ STUDENT={first:f.trim(), surname:s.trim()}; }catch(e){}
      ensureCamera().then(function(ok){
        if(!ok){
          alert('This is a proctored exam and requires camera access.\\n\\n'+
                'Please allow the camera when prompted (or enable it in your '+
                'browser\\'s site settings) and click Start exam again.\\n\\n'+
                'If you opened this over a plain http:// address, use the '+
                'https:// (ngrok) link instead \\u2014 browsers only allow the '+
                'camera on secure links.');
          return;
        }
        label();
        showRules();
      });
    };
  }

  function addNotice(){
    var intro=document.getElementById('intro');
    if(!intro || document.getElementById('camNotice')) return;
    var p=document.createElement('p');
    p.id='camNotice'; p.className='sub';
    p.style.cssText='margin-top:10px;color:#8a2410;font-weight:600';
    p.innerHTML='This is a proctored, full-screen exam; your '+
                'camera is required. Review the rules before beginning.';
    var nb=intro.querySelector('.namebox');
    if(nb && nb.parentNode){ nb.parentNode.insertBefore(p, nb.nextSibling); }
    else { intro.appendChild(p); }
  }

  function boot(){ installGate(); addNotice(); buildRules(); syncCam(); }
  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded', boot);
  } else { boot(); }
})();
</script>
"""

def inject_proctor(html_bytes):
    """Insert the webcam widget just before </body> (falls back to append)."""
    try:
        text = html_bytes.decode("utf-8")
    except Exception:
        return html_bytes
    idx = text.rfind("</body>")
    if idx == -1:
        text = text + PROCTOR_SNIPPET
    else:
        text = text[:idx] + PROCTOR_SNIPPET + text[idx:]
    return text.encode("utf-8")

# http
class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        sel_test = (qs.get("test", [None])[0]) or None
        if path == "/" or path == "/index.html":
            return self._send(200, landing_page())
        if path == "/report":
            return self._send(200, report_page(sel_test))
        if path == "/export.csv":
            return self._send(200, export_csv(sel_test), "text/csv; charset=utf-8",
                              {"Content-Disposition": "attachment; filename=exam_results.csv"})
        if path == "/import_template.csv":
            return self._send(200, import_template_csv(), "text/csv; charset=utf-8",
                              {"Content-Disposition": "attachment; filename=import_template.csv"})
        if path.startswith("/tests/"):
            fn = os.path.basename(path)
            fp = os.path.join(TESTS_DIR, fn)
            if os.path.isfile(fp) and fn.endswith(".html"):
                with open(fp, "rb") as f:
                    return self._send(200, inject_proctor(f.read()))
            return self._send(404, "Not found", "text/plain")
        return self._send(404, "Not found", "text/plain")

    def do_POST(self):
        post_path = urllib.parse.urlparse(self.path).path
        if post_path == "/api/import":
            try:
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                default_test = (qs.get("test", [""])[0]) or ""
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else b""
                if not body:
                    return self._send(400, json.dumps({"ok": False, "error": "empty file"}),
                                      "application/json")
                rows = parse_spreadsheet(body)
                summary = import_rows(rows, default_test)
                code = 200 if summary.get("ok") else 400
                return self._send(code, json.dumps(summary), "application/json")
            except Exception as e:
                return self._send(500, json.dumps({"ok": False, "error": str(e)}),
                                  "application/json")
        if self.path == "/api/add":
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length) or b"{}")
                first = str(data.get("first_name", "")).strip()
                surname = str(data.get("surname", "")).strip()
                test = str(data.get("test", "")).strip()
                if not first or not surname or not test:
                    return self._send(400, json.dumps({"ok": False, "error": "missing test or name"}),
                                      "application/json")
                correct = int(data.get("correct", 0))
                total = int(data.get("total", 0))
                if total <= 0 or correct < 0 or correct > total:
                    return self._send(400, json.dumps({"ok": False, "error": "bad correct/total"}),
                                      "application/json")
                score = round(correct / total * 1000)
                percent = round(correct / total * 100)
                insert_result({
                    "test": test, "first_name": first, "surname": surname,
                    "correct": correct, "total": total, "score": score,
                    "percent": percent, "passed": 1 if score >= 700 else 0,
                    "domains": {}, "comments": str(data.get("comments", "") or "").strip(),
                })
                return self._send(200, json.dumps({"ok": True}), "application/json")
            except Exception as e:
                return self._send(500, json.dumps({"ok": False, "error": str(e)}),
                                  "application/json")
        if self.path == "/api/delete":
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length) or b"{}")
                if data.get("all"):
                    n = delete_results(data.get("test") or None)
                elif data.get("id") is not None:
                    n = delete_result(data.get("id"))
                else:
                    return self._send(400, json.dumps({"ok": False, "error": "no id"}),
                                      "application/json")
                return self._send(200, json.dumps({"ok": True, "deleted": n}),
                                  "application/json")
            except Exception as e:
                return self._send(500, json.dumps({"ok": False, "error": str(e)}),
                                  "application/json")
        if self.path == "/api/start":
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length) or b"{}")
                if not data.get("first_name") or not data.get("surname"):
                    return self._send(400, json.dumps({"ok": False, "error": "missing name"}),
                                      "application/json")
                info = start_attempt(data.get("test", ""),
                                     data.get("first_name", ""),
                                     data.get("surname", ""))
                return self._send(200, json.dumps(info), "application/json")
            except Exception as e:
                return self._send(500, json.dumps({"ok": False, "error": str(e)}),
                                  "application/json")
        if self.path == "/api/submit":
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length) or b"{}")
                if not data.get("first_name") or not data.get("surname"):
                    return self._send(400, json.dumps({"ok": False, "error": "missing name"}),
                                      "application/json")
                insert_result(data)
                mark_submitted(data.get("test", ""),
                               data.get("first_name", ""),
                               data.get("surname", ""))
                return self._send(200, json.dumps({"ok": True}), "application/json")
            except Exception as e:
                return self._send(500, json.dumps({"ok": False, "error": str(e)}),
                                  "application/json")
        return self._send(404, "Not found", "text/plain")

    def log_message(self, fmt, *args):
        # concise console logging
        print("  %s - %s" % (self.address_string(), fmt % args))

def main():
    init_db()
    os.chdir(ROOT)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("", PORT), Handler) as httpd:
        httpd.daemon_threads = True
        print("=" * 60)
        print("  Certification practice test server is running")
        print("  Open:     http://localhost:%d/" % PORT)
        print("  Report:   http://localhost:%d/report" % PORT)
        print("  Database: %s" % DB_PATH)
        print("  Press Ctrl+C to stop.")
        print("=" * 60)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")

if __name__ == "__main__":
    main()
