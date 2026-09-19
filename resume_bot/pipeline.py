"""Daily run: ingest -> score -> enrich -> tailor -> render -> queue drafts."""
import os, json, pathlib, datetime
import httpx
from dotenv import load_dotenv
from rich.console import Console
from . import db, ingest, score, tailor, render, enrich, outreach

load_dotenv()
console = Console()
ROOT = pathlib.Path(__file__).resolve().parent.parent
DRAFTS = ROOT / "output" / "drafts"


def run(limit=None, dry_run=None, skip_ingest=False):
    if dry_run is None:
        dry_run = not os.getenv("ANTHROPIC_API_KEY")
    limit = limit or int(os.getenv("MAX_TAILORED_PER_DAY", "200"))
    DRAFTS.mkdir(parents=True, exist_ok=True)
    started = datetime.datetime.now()

    if not skip_ingest:
        console.rule("[bold]1. ingest")
        ingest.run()

    console.rule("[bold]2. score")
    console.print(score.run())

    con = db.connect()
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM jobs WHERE status='scored' ORDER BY score DESC LIMIT ?", (limit,))]
    console.rule(f"[bold]3. tailor + render  ({len(rows)} jobs, "
                 f"{'DRY RUN' if dry_run else 'LIVE'})")

    master = tailor.load_master()
    made, failed, flagged = 0, 0, 0
    with httpx.Client(follow_redirects=True) as client:
        for job in rows:
            try:
                ctx = ""
                if job.get("url"):
                    dom = enrich.domain_from_url(job["url"])
                    if dom and job["source"] not in ("remoteok", "arbeitnow"):
                        ctx = enrich.enrich(client, job["company"],
                                            f"https://{dom}").get("summary", "")

                t = tailor.tailor(job, master, ctx, dry_run=dry_run)
                if t.get("_warning"):
                    flagged += 1
                    console.print(f"  [yellow]{t['_warning'][:90]}[/yellow]")

                pdf = render.render(master, t, job)
                mail = outreach.draft(job, master, t, ctx, dry_run=dry_run)

                (DRAFTS / f"{job['id']}.json").write_text(json.dumps({
                    "job_id": job["id"], "company": job["company"], "title": job["title"],
                    "location": job["location"], "score": job["score"],
                    "apply_url": job["apply_url"], "resume": str(pdf),
                    "subject": mail["subject"], "body": mail["body"],
                    "gaps": t.get("gaps", []), "fit": t.get("fit_rationale", ""),
                    "mode": t.get("_mode"),
                }, indent=2))

                con.execute(
                    """INSERT OR REPLACE INTO applications
                       (job_id,resume_path,tailor_notes,created_at) VALUES (?,?,?,?)""",
                    (job["id"], str(pdf), t.get("fit_rationale", ""), db.now()))
                con.execute("UPDATE jobs SET status='queued' WHERE id=?", (job["id"],))
                con.commit()          # per-job: an interrupted run must not lose state
                made += 1
            except Exception as e:
                failed += 1
                console.print(f"  [red]{job['company'][:20]}: {type(e).__name__}: {e}[/red]")
    con.commit()

    console.rule("[bold]done")
    console.print(f"queued [bold]{made}[/bold] applications  "
                  f"failed {failed}  fabrication-flagged {flagged}  "
                  f"in {(datetime.datetime.now()-started).seconds}s")
    console.print(f"review: [cyan]python -m resume_bot review[/cyan]")
    con.close()
    return made
