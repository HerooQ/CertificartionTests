# Certification Practice Tests — with results database & report

This bundle turns your practice tests into a small system that
records every student's **first name, surname and mark** into a database, and
gives you a **report** of all results (viewable in the browser and exportable to CSV).

It now covers **two certifications**, shown as separate groups on the landing page:

- **Microsoft SC-900** — three practice tests (45-minute exams).
- **AWS Cloud Computing (Certified Cloud Practitioner, CLF-C02)** — two practice
  tests (90-minute exams) — see the "AWS tests" section below.

No installs required — it uses only Python's standard library. You just need
**Python 3.7+** (already on macOS/Linux; on Windows install from python.org).

## What's inside

```
sc900/
├── server.py        ← the app (serves tests + saves results + report)
├── results.db       ← SQLite database (starts empty; created automatically)
├── README.md        ← this file
├── tests/
│   ├── test1.html      ← SC-900 Practice Test 1 (Modules 1–6)
│   ├── test2.html      ← SC-900 Practice Test 2 (Modules 1–12)
│   ├── test3.html      ← SC-900 Practice Test 3 (Modules 1–18)
│   ├── aws-test1.html  ← AWS Practice Test 1 (course Modules 5–8)
│   └── aws-final.html  ← AWS Certified Cloud Practitioner — Final Exam (CLF-C02)
└── transform.py        ← (reference only) the script used to add name capture
```

## How to run it

1. Open a terminal / command prompt in this `sc900` folder.
2. Run:

   ```
   python3 server.py
   ```
   (On Windows, if `python3` isn't found, use `python server.py`.)

3. You'll see:

   ```
   Open:     http://localhost:8000/
   Report:   http://localhost:8000/report
   ```

4. Open **http://localhost:8000/** in a browser.

## How students take a test

- From the landing page they pick a test.
- On the intro screen they **enter their first name and surname** (both required),
  then click *Start exam*.
- When they submit, their result is saved automatically. They'll see
  "Result saved to the database ✓" on the results screen.

> Students on **other computers** on the same network can reach it too — give them
> `http://YOUR-IP:8000/` (find your machine's IP with `ipconfig` on Windows or
> `ifconfig`/`ip addr` on macOS/Linux). They must go through this address, not by
> opening the HTML file directly, for their mark to be recorded.

## The report (for you)

Go to **http://localhost:8000/report**. It shows:

- Summary cards: total attempts, average scaled score, average % correct, pass
  rate, and **number flagged for cheating**.
- A per-test breakdown (attempts, average score, pass rate, flagged count for each test).
- A full table of every attempt: date/time, student, test, correct/total, scaled
  score, percent, PASS/FAIL, and a **Proctoring** column (either "Clean" or the
  cheating flag with the method used).
- A **"Filter by test"** dropdown so you can view just one test's attempts instead
  of scrolling through all of them.
- **Export CSV** button (respects the current test filter, and includes the
  Comments column) and a **Print** button.

## Proctoring & anti-cheating

Every attempt runs in a lightweight "proctored" mode, purely to simulate the real
exam experience:

- **Webcam required.** After entering their name and clicking *Start exam*, the
  student is asked to allow their camera. The exam will not start until they do —
  the live feed then sits in the top-right with a red "REC" indicator and their
  name. (The feed stays in their browser; nothing is uploaded or recorded.)
- **Rules screen.** Between the name entry and the test, a rules page explains the
  conditions and requires the student to tick "I understand" before the *Begin
  exam* button unlocks. Fullscreen is entered from that button click.
- **Cheating detection.** During the exam the browser watches for, and flags, the
  student:
  - **exiting full-screen**,
  - **switching tabs or minimising the window**, and
  - **leaving the exam window** (opening another app or window).

  Each time, a warning banner appears on screen ("… — this has been flagged"), and
  the behaviour is recorded. When they submit, the flags are saved to the database
  in a **`comments`** column (e.g. *"CHEATING FLAGGED — Exited full-screen (2×);
  Switched tab or minimised the window"*). Clean attempts store an empty comment.

> **Important:** because the camera is mandatory and browsers only allow it over a
> secure connection, everyone must use the **https:// ngrok link**. A plain
> `http://` LAN address will block the camera (and therefore the exam start).
>
> Note that this is a browser-based deterrent, not tamper-proof invigilation — a
> determined user could disable JavaScript or use another device. It's designed to
> make the practice feel like the real thing and to surface obvious slips.

## Where the data lives

Everything is stored in `results.db` (SQLite). It persists between runs. To start
fresh, stop the server and delete `results.db` — a new empty one is created on the
next launch. You can also open `results.db` in any SQLite tool (e.g. DB Browser for
SQLite) if you want to query it directly. The table is `results`.

## The AWS tests (Cloud Practitioner / CLF-C02)

The **AWS Cloud Computing** group has two tests. Both follow the **real CLF-C02
format**, which differs from the SC-900 tests:

- **65 questions in 90 minutes** (the timer is enforced server-side, exactly like
  the SC-900 tests).
- **50 of the 65 questions are scored; 15 are unscored "pretest" questions.**
  Students can't tell which is which — just like the real exam. Only the 50 scored
  questions count toward the mark.
- Score is reported as a **scaled score out of 1000, pass = 700**. As with the
  SC-900 mocks, all scored questions are weighted equally (so 35 of 50 correct =
  700). Multiple-response questions must be fully correct to earn the point.

**AWS Practice Test 1 (Modules 5–8)** covers the four course modules from your
slides, and the 50 scored questions are spread evenly across them:

| Module | Topic                              | Scored | Unscored |
|--------|------------------------------------|--------|----------|
| 5      | Compute, Storage & Databases       | 13     | 4        |
| 6      | Integration & DevOps               | 12     | 4        |
| 7      | AI/ML, Analytics & Migration       | 13     | 4        |
| 8      | Billing, Pricing & Support         | 12     | 3        |

**AWS Final Exam (CLF-C02)** covers the whole exam, with the 50 scored questions
**distributed across the four official domains by their real weightings** — so the
practice mix matches what the actual exam emphasises:

| Domain | Name                          | Weight | Scored | Unscored |
|--------|-------------------------------|--------|--------|----------|
| 1      | Cloud Concepts                | 24%    | 12     | 4        |
| 2      | Security and Compliance       | 30%    | 15     | 4        |
| 3      | Cloud Technology and Services | 34%    | 17     | 5        |
| 4      | Billing, Pricing, and Support | 12%    | 6      | 2        |

Each attempt draws a fresh random paper from a larger bank and reshuffles the
question and answer order. The results screen shows a **per-module** (Test 1) or
**per-domain** (Final) breakdown so students can see exactly where to revise.

### Adding or editing AWS questions

The AWS question banks live in the build files (`bank_modules.py`, `bank_final.py`)
and are compiled into the two HTML files by `build_aws.py`. To add questions, add
entries to the relevant `QUESTIONS` list (keep the `"b"` bucket key — e.g. `"M5"`
or `"D2"` — so the balancing works) and re-run `python3 build_aws.py`. The script
validates counts and answer indices before writing the HTML. You can also edit the
`QUESTIONS_ALL` array directly inside `tests/aws-test1.html` / `tests/aws-final.html`
if you prefer.

## Notes on the SC-900 question pools

Each SC-900 test draws a **balanced random selection of 50 questions** from a larger
bank, then shuffles both the question order and the answer options each attempt:

| Test   | Question bank | Shown per attempt |
|--------|---------------|-------------------|
| Test 1 | 54 questions  | 50 (only 4 rotate out — little variety) |
| Test 2 | 92 questions  | 50 (good variety) |
| Test 3 | 130 questions | 50 (good variety) |

So it is a genuine pool, not a fixed 50 — but Test 1's bank is only slightly larger
than 50, so it feels nearly identical each attempt. Add more questions to Test 1's
`QUESTIONS_ALL` array if you want more variation there.

## Changing the port

If port 8000 is busy, open `server.py` and change `PORT = 8000` near the top.
