"""Review queue. Nothing leaves without passing through here."""
import json, pathlib, os
from rich.console import Console
from rich.table import Table
from . import db, send

console = Console()
DRAFTS = pathlib.Path(__file__).resolve().parent.parent / "output" / "drafts"


def _drafts():
    return sorted(DRAFTS.glob("*.json"),
                  key=lambda p: -json.loads(p.read_text()).get("score", 0))


def listing(n=40):
    t = Table(title="queued applications", show_lines=False)
    for c, s in [("id", "dim"), ("score", "bold"), ("company", "cyan"),
                 ("title", "white"), ("location", "dim"), ("mode", "yellow")]:
        t.add_column(c, style=s)
    for p in _drafts()[:n]:
        d = json.loads(p.read_text())
        t.add_row(str(d["job_id"]), f"{d['score']:.0f}", d["company"][:22],
                  d["title"][:38], (d.get("location") or "")[:20], d.get("mode", ""))
    console.print(t)
    console.print(f"\n{len(_drafts())} queued. "
                  f"[cyan]python -m resume_bot show <id>[/cyan] to inspect one.")


def show(job_id):
    p = DRAFTS / f"{job_id}.json"
    if not p.exists():
        console.print(f"[red]no draft {job_id}[/red]"); return
    d = json.loads(p.read_text())
    console.rule(f"{d['company']} - {d['title']}  (score {d['score']:.0f})")
    console.print(f"[dim]apply:[/dim] {d['apply_url']}")
    console.print(f"[dim]resume:[/dim] {d['resume']}")
    console.print(f"[dim]fit:[/dim] {d['fit']}")
    if d.get("gaps"):
        console.print(f"[yellow]gaps:[/yellow] {', '.join(d['gaps'])}")
    console.rule("email")
    console.print(f"[bold]Subject:[/bold] {d['subject']}\n")
    console.print(d["body"])


def approve(job_id, to_addr):
    """Explicit per-send approval. Bypasses AUTO_SEND, never the other rails."""
    d = json.loads((DRAFTS / f"{job_id}.json").read_text())
    con = db.connect()
    try:
        send.send_one(con, job_id, to_addr, d["subject"], d["body"],
                      attachment=d["resume"], force=True)
        con.execute("UPDATE jobs SET status='applied' WHERE id=?", (job_id,))
        con.commit()
        console.print(f"[green]sent to {to_addr}[/green]")
    except send.Blocked as e:
        console.print(f"[red]blocked: {e}[/red]")
    finally:
        con.close()
