"""SMTP sender with the rails that keep an outreach account alive.

Enforced on every send: global kill switch (AUTO_SEND), daily cap, suppression
list, per-address once-only, inter-send jitter, and a hard dry-run default.
"""
import os, smtplib, ssl, time, random, mimetypes, pathlib
from email.message import EmailMessage
from . import db


class Blocked(Exception):
    pass


def suppressed(con, addr):
    return con.execute("SELECT 1 FROM suppression WHERE email=?",
                       (addr.lower(),)).fetchone() is not None


def suppress(con, addr, reason="manual"):
    con.execute("INSERT OR REPLACE INTO suppression VALUES (?,?,?)",
                (addr.lower(), reason, db.now()))
    con.commit()


def sent_today(con):
    return con.execute(
        "SELECT COUNT(*) FROM sent_log WHERE date(sent_at)=date('now') AND status='sent'"
    ).fetchone()[0]


def already_contacted(con, addr):
    return con.execute("SELECT 1 FROM sent_log WHERE to_email=? AND status='sent'",
                       (addr.lower(),)).fetchone() is not None


def _build(to_addr, subject, body, attachment=None):
    msg = EmailMessage()
    msg["From"] = f"{os.getenv('FROM_NAME','')} <{os.getenv('FROM_EMAIL')}>"
    msg["To"] = to_addr
    msg["Subject"] = subject
    if os.getenv("REPLY_TO"):
        msg["Reply-To"] = os.getenv("REPLY_TO")
    msg.set_content(body)
    if attachment:
        p = pathlib.Path(attachment)
        ctype, _ = mimetypes.guess_type(p.name)
        maj, _, sub = (ctype or "application/pdf").partition("/")
        msg.add_attachment(p.read_bytes(), maintype=maj, subtype=sub, filename=p.name)
    return msg


def send_one(con, job_id, to_addr, subject, body, attachment=None, force=False):
    to_addr = to_addr.lower().strip()
    cap = int(os.getenv("MAX_EMAILS_PER_DAY", "20"))
    auto = os.getenv("AUTO_SEND", "false").lower() == "true"

    if not auto and not force:
        raise Blocked("AUTO_SEND=false - nothing sent. Approve via the review queue.")
    if suppressed(con, to_addr):
        raise Blocked(f"{to_addr} is on the suppression list")
    if already_contacted(con, to_addr):
        raise Blocked(f"{to_addr} already contacted - never mail the same address twice")
    if sent_today(con) >= cap:
        raise Blocked(f"daily cap reached ({cap})")
    if not os.getenv("SMTP_USER") or not os.getenv("FROM_EMAIL"):
        raise Blocked("SMTP not configured")

    msg = _build(to_addr, subject, body, attachment)
    ctx = ssl.create_default_context()
    with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"),
                      int(os.getenv("SMTP_PORT", "587")), timeout=30) as s:
        s.starttls(context=ctx)
        s.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
        s.send_message(msg)

    con.execute("INSERT INTO sent_log (job_id,to_email,subject,sent_at,status) VALUES (?,?,?,?,?)",
                (job_id, to_addr, subject, db.now(), "sent"))
    con.commit()
    time.sleep(random.uniform(20, 55))     # human-ish spacing, not a burst
    return True
