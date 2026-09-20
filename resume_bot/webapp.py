"""Local tracking dashboard. Binds to 127.0.0.1 only - this data stays on your machine.

    ./.venv/bin/python -m resume_bot dash     ->  http://127.0.0.1:8777
"""
import json, pathlib, os, re, datetime
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from . import db, send, llm, identity, llm

ROOT = pathlib.Path(__file__).resolve().parent
DRAFTS = ROOT.parent / "output" / "drafts"
app = FastAPI(title="Resume Tracker")
tpl = Jinja2Templates(directory=str(ROOT / "templates"))


def _age(ts):
    if not ts:
        return None
    import time
    return max(0.0, (time.time() - ts) / 86400.0)


def _agelabel(ts):
    d = _age(ts)
    if d is None:
        return ("\u2014", "muted")
    if d < 1:
        return ("today", "fresh")
    if d < 2:
        return ("1d", "fresh")
    if d <= 7:
        return (f"{d:.0f}d", "fresh")
    if d <= 30:
        return (f"{d:.0f}d", "")
    return (f"{d:.0f}d", "old")


def _stats(con):
    c = db.counts(con)
    today = datetime.date.today().isoformat()
    return {
        "total_jobs": con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
        "matched": c.get("scored", 0) + c.get("queued", 0) + c.get("applied", 0),
        "queued": c.get("queued", 0),
        "applied": c.get("applied", 0),
        "contacts": con.execute("SELECT COUNT(*) FROM contacts").fetchone()[0],
        "emails_sent": con.execute(
            "SELECT COUNT(*) FROM sent_log WHERE status='sent'").fetchone()[0],
        "sent_today": con.execute(
            "SELECT COUNT(*) FROM sent_log WHERE status='sent' AND date(sent_at)=?",
            (today,)).fetchone()[0],
        "cap": int(os.getenv("MAX_EMAILS_PER_DAY", "20")),
        "auto_send": os.getenv("AUTO_SEND", "false").lower() == "true",
        "live_llm": llm.configured(),
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    con = db.connect()
    stats = _stats(con)
    by_source = con.execute(
        """SELECT source, COUNT(*) n,
                  SUM(CASE WHEN status IN ('queued','applied') THEN 1 ELSE 0 END) acted
           FROM jobs GROUP BY source ORDER BY n DESC""").fetchall()
    recent = con.execute(
        """SELECT j.id,j.company,j.title,j.location,j.score,j.status,j.source,j.apply_url,
                  j.posted_ts, a.created_at, a.resume_path
           FROM jobs j JOIN applications a ON a.job_id=j.id
           ORDER BY a.created_at DESC LIMIT 60""").fetchall()
    timeline = con.execute(
        """SELECT date(created_at) d, COUNT(*) n FROM applications
           GROUP BY d ORDER BY d DESC LIMIT 14""").fetchall()
    con.close()
    return tpl.TemplateResponse(request, "dash.html", {
        "tab": "overview", "stats": stats,
        "by_source": by_source, "recent": recent, "timeline": timeline, "agelabel": _agelabel})


@app.get("/applications", response_class=HTMLResponse)
def applications(request: Request, status: str = "", q: str = "", age: str = ""):
    con = db.connect()
    sql = """SELECT j.id,j.company,j.title,j.location,j.score,j.status,j.source,
                    j.apply_url,j.posted_ts,a.created_at,a.resume_path,a.submitted_at
             FROM jobs j JOIN applications a ON a.job_id=j.id WHERE 1=1"""
    args = []
    if status:
        sql += " AND j.status=?"; args.append(status)
    if q:
        sql += " AND (lower(j.company) LIKE ? OR lower(j.title) LIKE ?)"
        args += [f"%{q.lower()}%"] * 2
    cutoffs = {"today": 1, "week": 7, "month": 30}
    if age in cutoffs:
        import time
        sql += " AND j.posted_ts IS NOT NULL AND j.posted_ts >= ?"
        args.append(int(time.time() - cutoffs[age] * 86400))
    elif age == "older":
        import time
        sql += " AND (j.posted_ts IS NULL OR j.posted_ts < ?)"
        args.append(int(time.time() - 30 * 86400))
    sql += " ORDER BY j.posted_ts DESC NULLS LAST, a.created_at DESC LIMIT 400"
    rows = con.execute(sql, args).fetchall()
    stats = _stats(con); con.close()
    return tpl.TemplateResponse(request, "dash.html", {
        "tab": "applications", "stats": stats,
        "rows": rows, "status": status, "q": q, "age": age,
        "agelabel": _agelabel})


@app.get("/contacts", response_class=HTMLResponse)
def contacts(request: Request):
    con = db.connect()
    rows = con.execute(
        """SELECT c.*, (SELECT COUNT(*) FROM sent_log s WHERE s.to_email=c.email
                        AND s.status='sent') mailed
           FROM contacts c ORDER BY c.company""").fetchall()
    supp = con.execute("SELECT * FROM suppression ORDER BY created_at DESC").fetchall()
    stats = _stats(con); con.close()
    return tpl.TemplateResponse(request, "dash.html", {
        "tab": "contacts", "stats": stats,
        "rows": rows, "supp": supp, "agelabel": _agelabel})


@app.get("/mail", response_class=HTMLResponse)
def mail(request: Request):
    con = db.connect()
    rows = con.execute(
        """SELECT s.*, j.company, j.title FROM sent_log s
           LEFT JOIN jobs j ON j.id=s.job_id ORDER BY s.sent_at DESC LIMIT 300""").fetchall()
    stats = _stats(con); con.close()
    return tpl.TemplateResponse(request, "dash.html", {
        "tab": "mail", "stats": stats, "rows": rows, "agelabel": _agelabel})


@app.get("/job/{job_id}", response_class=HTMLResponse)
def job(request: Request, job_id: int):
    con = db.connect()
    j = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    a = con.execute("SELECT * FROM applications WHERE job_id=?", (job_id,)).fetchone()
    d = None
    p = DRAFTS / f"{job_id}.json"
    if p.exists():
        d = json.loads(p.read_text())
    cts = con.execute("SELECT * FROM contacts WHERE lower(company) LIKE ?",
                      (f"%{(j['company'] or '').lower()[:14]}%",)).fetchall() if j else []
    ar = con.execute("SELECT * FROM agent_runs WHERE job_id=? ORDER BY id DESC LIMIT 1",
                     (job_id,)).fetchone()
    trace = json.loads(ar["trace"]) if ar and ar["trace"] else []
    agent_errors = json.loads(ar["errors"]) if ar and ar["errors"] else []
    stats = _stats(con); con.close()
    return tpl.TemplateResponse(request, "dash.html", {
        "tab": "job", "stats": stats,
        "j": j, "a": a, "d": d, "contacts": cts,
        "trace": trace, "agent_errors": agent_errors, "agelabel": _agelabel})


PROFILE = identity.profile()


@app.get("/work", response_class=HTMLResponse)
def work(request: Request):
    """Focused queue-working view: one job at a time, everything copyable."""
    con = db.connect()
    row = con.execute(
        """SELECT j.*, a.resume_path FROM jobs j JOIN applications a ON a.job_id=j.id
           WHERE j.status='queued' ORDER BY j.score DESC LIMIT 1""").fetchone()
    remaining = con.execute(
        "SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0]
    d = None
    if row:
        fp = DRAFTS / f"{row['id']}.json"
        if fp.exists():
            d = json.loads(fp.read_text())
    stats = _stats(con); con.close()
    return tpl.TemplateResponse(request, "dash.html", {
        "tab": "work", "stats": stats, "j": row, "d": d,
        "remaining": remaining, "profile": PROFILE, "agelabel": _agelabel})


@app.post("/work/{job_id}/{action}")
def work_action(job_id: int, action: str):
    """applied | skip - either way we advance to the next job."""
    con = db.connect()
    if action == "applied":
        con.execute("UPDATE jobs SET status='applied' WHERE id=?", (job_id,))
        con.execute("UPDATE applications SET submitted_at=? WHERE job_id=?",
                    (db.now(), job_id))
    else:
        con.execute("UPDATE jobs SET status='skipped' WHERE id=?", (job_id,))
    con.commit(); con.close()
    return RedirectResponse("/work", status_code=303)


@app.get("/setup", response_class=HTMLResponse)
def setup(request: Request):
    """Page that hands over the autofill bookmarklet."""
    import urllib.parse
    js = (ROOT / "static" / "autofill.js").read_text()
    payload = ("window.__RB_PROFILE__=" + json.dumps(identity.autofill()) + ";" + js)
    # collapse the comment header and newlines so it fits a bookmarklet URL
    payload = re.sub(r"/\*.*?\*/", "", payload, flags=re.S)
    payload = re.sub(r"\n\s*", " ", payload)
    href = "javascript:" + urllib.parse.quote(payload, safe="")
    con = db.connect(); stats = _stats(con); con.close()
    return tpl.TemplateResponse(request, "dash.html", {
        "tab": "setup", "stats": stats, "bookmarklet": href,
        "profile": identity.autofill(), "agelabel": _agelabel})


@app.get("/resume/{job_id}")
def resume(job_id: int, download: int = 0):
    """Serve the tailored PDF for this job - inline so it previews in the tab."""
    con = db.connect()
    row = con.execute("SELECT a.resume_path, j.company, j.title FROM applications a "
                      "JOIN jobs j ON j.id=a.job_id WHERE a.job_id=?", (job_id,)).fetchone()
    con.close()
    if not row or not row["resume_path"]:
        return HTMLResponse("<p>No resume rendered for this job yet.</p>", status_code=404)
    fp = pathlib.Path(row["resume_path"])
    if not fp.exists():
        return HTMLResponse(f"<p>Missing file: {fp}</p>", status_code=404)
    safe = re.sub(r"[^A-Za-z0-9]+", "_", f"{row['company']}_{row['title']}")[:60]
    return FileResponse(
        str(fp), media_type="application/pdf",
        filename=f"Rudrabha_Chakraborty_{safe}.pdf",
        content_disposition_type="attachment" if download else "inline")


@app.post("/mark/{job_id}")
def mark(job_id: int, status: str = Form(...)):
    con = db.connect()
    con.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
    if status == "applied":
        con.execute("UPDATE applications SET submitted_at=? WHERE job_id=?",
                    (db.now(), job_id))
    con.commit(); con.close()
    return RedirectResponse(f"/job/{job_id}", status_code=303)


@app.post("/suppress")
def do_suppress(email: str = Form(...), reason: str = Form("manual")):
    con = db.connect(); send.suppress(con, email, reason); con.close()
    return RedirectResponse("/contacts", status_code=303)


def serve(host="127.0.0.1", port=8777):
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="warning")
