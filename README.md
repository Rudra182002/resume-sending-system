# Resume Sending System

A multi-agent job application pipeline. It ingests postings from nine sources,
scores them against a profile, researches each company, rewrites the resume for
the specific job description, renders an ATS-safe PDF, and tracks every
application in a local dashboard.

Built because searching job boards by hand does not scale, and because sending
the same generic resume to two thousand companies does not work.

```
14,470 postings ingested  ->  ~2,000 matched  ->  tailored per JD  ->  tracked
```

## How it works

Six agents share a context and fail in isolation, so one broken step never
takes down a run.

| Agent | Responsibility |
|---|---|
| `research` | Reads the company's own site for real context |
| `tailor` | Rewrites the resume against this JD, facts frozen |
| `render` | Produces a one-page ATS-safe PDF |
| `outreach` | Drafts the application email |
| `form` | Fills the ATS form (off by default) |
| `tracker` | Persists state so a rerun resumes rather than repeats |

```bash
python -m resume_bot agents 50 6    # 50 jobs, 6 workers
```

## Sources

Public, documented endpoints only. No scraping, no ToS risk.

- **ATS boards** — Greenhouse, Lever, Ashby (full JD text and direct apply URLs)
- **Aggregators** — Adzuna, Jooble, Careerjet, Arbeitnow, RemoteOK, Remotive
- **Alert email** — LinkedIn / Naukri / foundit job alerts parsed from your own
  IMAP mailbox, read-only, using `BODY.PEEK[]` so nothing is marked read
- **Long-tail crawler** — finds careers pages on arbitrary company domains,
  detects embedded ATS widgets, and honours `robots.txt` per RFC 9309

## Tailoring, with guardrails

The prompt's rule is **facts frozen, framing free**: every sentence may be
rewritten, nothing that happened may change. Three validators enforce it rather
than trusting the model.

- `verify_no_fabrication` — every number in generated prose must already exist
  in the master resume, and flagged numbers are quoted in context
- `verify_structure` — exact bullet count per project, bullet length within
  60–160% of the original, no invented projects or skill groups
- `verify_voice` — rejects resume cliches

On any violation the generated text is discarded and the verified original kept.

## Scoring

Deterministic and cheap, so the model only ever sees jobs that clear the bar.

- **Title tiers** — current role / lateral move / wider net, weighted so a
  lower-tier match never outranks a real one
- **Location** — an allowlist, because enumerating foreign place names is a
  losing game ("Remote - California" defeated three blocklists)
- **Freshness** — response rates collapse with posting age. Live ATS boards are
  exempt, since a filled role leaves their API; aggregators cache, so age is
  meaningful there
- **Direct employer signal** — companies running their own ATS board outrank
  staffing listings, using positive evidence rather than agency name-matching

## Dashboard

```bash
python -m resume_bot dash          # http://127.0.0.1:8777
```

Binds to loopback only. Overview with source breakdown and a 14-day timeline,
a focused apply view with click-to-copy fields and an inline PDF preview,
filtering by status and posting age, contacts, and a send log.

## Setup

```bash
./setup.sh
cp data/master_resume.example.json data/master_resume.json   # fill this in
cp .env.example .env                                          # add an API key
python -m resume_bot doctor                                   # verify wiring
```

Provider-agnostic: Anthropic, OpenAI, any OpenAI-compatible endpoint, or Azure
OpenAI, auto-detected from `.env`. Without a key everything still runs in
dry-run against real data.

## Commands

```
ingest              pull from every configured source
score [all]         rank against the profile
agents [n] [w]      full pipeline across n jobs
harvest [days]      parse job-alert email
apply [n]           fill ATS forms (prepare mode by default)
rerender            rebuild PDFs with the current template
dash [port]         tracking dashboard
doctor              check every integration
```

## Safety

Sending is off unless `AUTO_SEND=true`, and every send passes a kill switch, a
suppression list, an already-contacted check, and a daily cap. Form submission
is off unless `APPLY_MODE` says otherwise, and refuses any form with unanswered
custom questions. A pre-commit hook blocks credential-shaped strings.

Only addresses a company publishes for applicants are ever collected — never
guessed personal addresses, which bounce and wreck deliverability.

## Stack

Python 3.12 · FastAPI · SQLite · ReportLab · Playwright · httpx · Anthropic and
OpenAI SDKs
