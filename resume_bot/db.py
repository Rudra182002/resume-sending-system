"""SQLite store. One row per job posting, deduped on (source, external_id)."""
import sqlite3, json, pathlib, datetime

DB_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "jobs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY,
    source        TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    company       TEXT NOT NULL,
    company_slug  TEXT,
    title         TEXT NOT NULL,
    location      TEXT,
    remote        INTEGER DEFAULT 0,
    url           TEXT,
    apply_url     TEXT,
    jd_text       TEXT,
    salary        TEXT,
    posted_at     TEXT,
    fetched_at    TEXT NOT NULL,
    score         REAL,
    score_reasons TEXT,
    status        TEXT NOT NULL DEFAULT 'new',
    UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_score  ON jobs(score DESC);

CREATE TABLE IF NOT EXISTS applications (
    id           INTEGER PRIMARY KEY,
    job_id       INTEGER NOT NULL REFERENCES jobs(id),
    resume_path  TEXT,
    tailor_notes TEXT,
    created_at   TEXT NOT NULL,
    submitted_at TEXT,
    UNIQUE(job_id)
);

-- Addresses we must never contact again (bounces, opt-outs, manual blocks).
CREATE TABLE IF NOT EXISTS suppression (
    email      TEXT PRIMARY KEY,
    reason     TEXT,
    created_at TEXT NOT NULL
);

-- People/addresses per company: who we found, where, and whether we mailed them.
CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY,
    company     TEXT NOT NULL,
    email       TEXT NOT NULL,
    name        TEXT,
    role        TEXT,
    source      TEXT,              -- careers-page | alert | manual
    verified    INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL,
    UNIQUE(company, email)
);
CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company);

CREATE TABLE IF NOT EXISTS agent_runs (
    id         INTEGER PRIMARY KEY,
    job_id     INTEGER REFERENCES jobs(id),
    trace      TEXT,
    errors     TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_job ON agent_runs(job_id);

CREATE TABLE IF NOT EXISTS sent_log (
    id         INTEGER PRIMARY KEY,
    job_id     INTEGER REFERENCES jobs(id),
    to_email   TEXT NOT NULL,
    subject    TEXT,
    sent_at    TEXT NOT NULL,
    status     TEXT
);
"""

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def upsert_jobs(con, jobs):
    """Insert new postings, ignore ones we've already seen. Returns count inserted."""
    inserted = 0
    for j in jobs:
        try:
            con.execute(
                """INSERT OR IGNORE INTO jobs
                   (source, external_id, company, company_slug, title, location,
                    remote, url, apply_url, jd_text, salary, posted_at, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (j["source"], str(j["external_id"]), j["company"], j.get("company_slug"),
                 j["title"], j.get("location"), int(bool(j.get("remote"))),
                 j.get("url"), j.get("apply_url"), j.get("jd_text"),
                 j.get("salary"), j.get("posted_at"), now()),
            )
            inserted += con.total_changes > 0 and 1 or 0
        except sqlite3.Error:
            continue
    con.commit()
    return con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

def add_contact(con, company, email, name=None, role=None, source="careers-page", verified=0):
    con.execute("""INSERT OR IGNORE INTO contacts
                   (company,email,name,role,source,verified,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (company, email.lower().strip(), name, role, source, verified, now()))
    con.commit()


def counts(con):
    rows = con.execute("SELECT status, COUNT(*) c FROM jobs GROUP BY status").fetchall()
    return {r["status"]: r["c"] for r in rows}
