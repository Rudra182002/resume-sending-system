"""Pull postings from every configured source into SQLite."""
import os, pathlib, yaml, httpx
from dotenv import load_dotenv
from rich.console import Console
from . import sources, db, alerts

load_dotenv()

console = Console()
CFG = pathlib.Path(__file__).resolve().parent.parent / "config" / "targets.yaml"


def run(skip_ats=False):
    targets = yaml.safe_load(CFG.read_text()) if CFG.exists() else {}
    all_jobs, stats = [], {}

    with httpx.Client(follow_redirects=True) as client:
        if not skip_ats:
            for ats, slugs in targets.items():
                fn = getattr(sources, ats)
                ok = dead = 0
                for slug in slugs or []:
                    try:
                        jobs = fn(client, slug)
                        all_jobs.extend(jobs)
                        ok += len(jobs)
                    except Exception:
                        dead += 1          # slug retired or board private - fine
                stats[ats] = ok
                if dead:
                    console.print(f"  [dim]{ats}: {dead} slug(s) unreachable, skipped[/dim]")

        # Keyed aggregators - broad India coverage. Silently skipped when unset.
        if os.getenv("ADZUNA_APP_ID") and os.getenv("ADZUNA_APP_KEY"):
            try:
                j = sources.adzuna(client, os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY"))
                all_jobs.extend(j); stats["adzuna"] = len(j)
            except Exception as e:
                stats["adzuna"] = f"failed ({type(e).__name__})"
        if os.getenv("JOOBLE_API_KEY"):
            try:
                j = sources.jooble(client, os.getenv("JOOBLE_API_KEY"))
                all_jobs.extend(j); stats["jooble"] = len(j)
            except Exception as e:
                stats["jooble"] = f"failed ({type(e).__name__})"
        if os.getenv("CAREERJET_AFFID"):
            try:
                j = sources.careerjet(client, os.getenv("CAREERJET_AFFID"))
                all_jobs.extend(j); stats["careerjet"] = len(j)
            except Exception as e:
                stats["careerjet"] = f"failed ({type(e).__name__})"

        for name, fn in (("arbeitnow", sources.arbeitnow),
                         ("remoteok", sources.remoteok),
                         ("remotive", sources.remotive)):
            try:
                jobs = fn(client)
                all_jobs.extend(jobs)
                stats[name] = len(jobs)
            except Exception as e:
                stats[name] = f"failed ({type(e).__name__})"

    con = db.connect()

    # LinkedIn / Naukri / foundit, read from your own alert mailbox.
    try:
        al = alerts.fetch(folder=os.getenv("IMAP_FOLDER", "INBOX"))
        if al:
            m = alerts.backfill_jd(con, al)
            all_jobs.extend(al)
            stats["alerts(li/naukri/foundit)"] = f"{len(al)} ({m} matched to ATS JD)"
    except Exception as e:
        stats["alerts"] = f"failed ({type(e).__name__})"

    before = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    total = db.upsert_jobs(con, all_jobs)
    console.print(f"\n[bold]fetched[/bold] {len(all_jobs)} postings  "
                  f"[bold]new[/bold] {total - before}  [bold]in db[/bold] {total}")
    for k, v in stats.items():
        console.print(f"  {k:12s} {v}")
    con.close()
    return total
