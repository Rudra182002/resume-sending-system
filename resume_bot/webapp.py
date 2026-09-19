"""Local tracking dashboard. Binds to 127.0.0.1 only - this data stays on your machine.

    ./.venv/bin/python -m resume_bot dash     ->  http://127.0.0.1:8777
"""
import json, pathlib, os, datetime
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from . import db, send, llm, llm

ROOT = pathlib.Path(__file__).resolve().parent
DRAFTS = ROOT.parent / "output" / "drafts"
app = FastAPI(title="Resume Tracker")
tpl = Jinja2Templates(directory=str(ROOT / "templates"))


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
                  a.created_at, a.resume_path
           FROM jobs j JOIN applications a ON a.job_id=j.id
           ORDER BY a.created_at DESC LIMIT 60""").fetchall()
    timeline = con.execute(
        """SELECT date(created_at) d, COUNT(*) n FROM applications
           GROUP BY d ORDER BY d DESC LIMIT 14""").fetchall()
    con.close()
    return tpl.TemplateResponse(request, "dash.html", {
        "tab": "overview", "stats": stats,
        "by_source": by_source, "recent": recent, "timeline": timeline})


@app.get("/applications", response_class=HTMLResponse)
def applications(request: Request, status: str = "", q: str = ""):
    con = db.connect()
    sql = """SELECT j.id,j.company,j.title,j.location,j.score,j.status,j.source,
                    j.apply_url,a.created_at,a.resume_path,a.submitted_at
             FROM jobs j JOIN applications a ON a.job_id=j.id WHERE 1=1"""
    args = []
    if status:
        sql += " AND j.status=?"; args.append(status)
    if q:
        sql += " AND (lower(j.company) LIKE ? OR lower(j.title) LIKE ?)"
        args += [f"%{q.lower()}%"] * 2
    sql += " ORDER BY a.created_at DESC LIMIT 400"
    rows = con.execute(sql, args).fetchall()
    stats = _stats(con); con.close()
    return tpl.TemplateResponse(request, "dash.html", {
        "tab": "applications", "stats": stats,
        "rows": rows, "status": status, "q": q})


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
        "rows": rows, "supp": supp})


@app.get("/mail", response_class=HTMLResponse)
def mail(request: Request):
    con = db.connect()
    rows = con.execute(
        """SELECT s.*, j.company, j.title FROM sent_log s
           LEFT JOIN jobs j ON j.id=s.job_id ORDER BY s.sent_at DESC LIMIT 300""").fetchall()
    stats = _stats(con); con.close()
    return tpl.TemplateResponse(request, "dash.html", {
        "tab": "mail", "stats": stats, "rows": rows})


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
    stats = _stats(con); con.close()
    return tpl.TemplateResponse(request, "dash.html", {
        "tab": "job", "stats": stats,
        "j": j, "a": a, "d": d, "contacts": cts})


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
