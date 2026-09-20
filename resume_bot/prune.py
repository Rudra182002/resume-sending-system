"""Keep the database small enough to sync.

Full JD text is only needed while a job is being scored and tailored. Once a
job is rejected the text is dead weight - it was 53 of 71 MB here, which is
past what GitHub will accept as a single file.

Rejected rows are kept (they carry the dedupe key so we do not re-ingest the
same posting) but their JD is truncated to a short excerpt, enough to re-judge
roughly if the targeting policy changes.
"""
import os, pathlib
from . import db

KEEP_CHARS = 400
ROOT = pathlib.Path(__file__).resolve().parent.parent


def run(keep_chars=KEEP_CHARS, verbose=True):
    path = ROOT / "data" / "jobs.db"
    before = path.stat().st_size if path.exists() else 0
    con = db.connect()

    n = con.execute(
        "SELECT COUNT(*) FROM jobs WHERE status='rejected' AND LENGTH(jd_text) > ?",
        (keep_chars,)).fetchone()[0]
    con.execute(
        "UPDATE jobs SET jd_text = substr(jd_text, 1, ?) "
        "WHERE status='rejected' AND LENGTH(jd_text) > ?", (keep_chars, keep_chars))

    # agent traces pile up per run and are only useful for the latest attempt
    stale = con.execute(
        """DELETE FROM agent_runs WHERE id NOT IN
           (SELECT MAX(id) FROM agent_runs GROUP BY job_id)""").rowcount
    con.commit()
    con.execute("VACUUM")
    con.close()

    after = path.stat().st_size if path.exists() else 0
    if verbose:
        print(f"truncated JD on {n:,} rejected rows, dropped {stale:,} old agent traces")
        print(f"database {before/1048576:.1f} MB -> {after/1048576:.1f} MB")
    return after
