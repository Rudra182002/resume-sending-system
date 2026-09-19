# Resume Sending System

Daily job pipeline: ingest → score → enrich → tailor → render → review → send.

## Setup

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env     # then fill it in
```

### Required
- `ANTHROPIC_API_KEY` — personal key from console.anthropic.com. Without it the
  whole pipeline still runs in dry-run: real jobs, real PDFs, stubbed LLM output.

### Optional, but they widen coverage a lot
- `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` — best India coverage
- `JOOBLE_API_KEY`, `CAREERJET_AFFID`
- `IMAP_USER` / `IMAP_PASS` — reads LinkedIn/Naukri/foundit **alert emails** from
  your own inbox. Gmail needs an App Password. Create alerts on those sites first.

## Use

```bash
python -m resume_bot run          # full pipeline
python -m resume_bot run 25       # cap at 25
python -m resume_bot review       # queued applications
python -m resume_bot show 1713    # inspect one draft
python -m resume_bot approve 1713 careers@company.com   # explicit send
```

## Scheduling

`crontab -e` holds `0 9 * * * /home/rudra/Resume_Sending_System/run_daily.sh`.

WSL caveat: cron only fires while WSL is running. If the machine is off at 9am the
run is skipped. For guaranteed firing use Windows Task Scheduler →
`wsl.exe -d Ubuntu -e /home/rudra/Resume_Sending_System/run_daily.sh`.

## Safety rails

Sending is off by default (`AUTO_SEND=false`) and every send checks, in order:
kill switch → suppression list → already-contacted → daily cap → SMTP configured.
Sends are spaced 20-55s apart. `approve` bypasses only the kill switch.

Resume tailoring is guarded: every number in generated prose must already exist in
`data/master_resume.json`, or the text falls back to the verified original.

## Layout

| file | role |
|---|---|
| `sources.py` | 9 job sources, all official/keyless-or-free |
| `alerts.py`  | IMAP reader for LinkedIn/Naukri/foundit alert mail |
| `ingest.py`  | fetch + dedupe into SQLite |
| `score.py`   | deterministic matcher (no LLM spend) |
| `enrich.py`  | company context, robots.txt respected |
| `tailor.py`  | LLM resume tailoring + fabrication guard |
| `render.py`  | ATS-safe single-page PDF |
| `outreach.py`| email drafting |
| `send.py`    | SMTP + rails |
| `review.py`  | approval queue |

## Deliberately not included

No LinkedIn/Naukri/foundit scraping — those get accounts restricted, and they're
the accounts recruiters reach you on. Coverage comes via their own alert emails
plus official aggregator APIs instead.

No guessed contact addresses. Only addresses companies publish for applicants
(`careers@`, `jobs@`). Guessed addresses bounce, and bounces wreck deliverability.
