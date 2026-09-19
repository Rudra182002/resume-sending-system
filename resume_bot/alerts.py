"""Parse job-alert emails out of your own inbox over IMAP.

Covers LinkedIn / Naukri / foundit without touching those sites: you subscribe to
their alerts, they mail you, we read YOUR mailbox. Their delivery channel, your
credentials, nothing automated pointed at their servers.

Setup: create job alerts on each site, then filter them into one IMAP folder
(e.g. "JobAlerts") so we read a narrow, predictable slice of your mail.
"""
import imaplib, email, re, html, os, hashlib
from email.header import decode_header

SENDERS = {
    "linkedin": ["jobalerts-noreply@linkedin.com", "jobs-noreply@linkedin.com",
                 "jobs-listings@linkedin.com"],
    "naukri":   ["info@naukri.com", "alerts@naukri.com", "jobalerts@naukri.com"],
    "foundit":  ["alerts@foundit.in", "noreply@foundit.in", "jobs@foundit.in"],
}

JOB_LINK = {
    "linkedin": re.compile(r"https://www\.linkedin\.com/(?:comm/)?jobs/view/(\d+)"),
    "naukri":   re.compile(r"https://www\.naukri\.com/job-listings-([\w\-]+)"),
    "foundit":  re.compile(r"https://www\.foundit\.in/(?:job|srp)/[\w\-/]+"),
}


def _decode(s):
    if not s:
        return ""
    parts = decode_header(s)
    return "".join(p.decode(enc or "utf-8", "ignore") if isinstance(p, bytes) else p
                   for p, enc in parts)


def _body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    return part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", "ignore")
                except Exception:
                    continue
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", "ignore")
                except Exception:
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(
            msg.get_content_charset() or "utf-8", "ignore")
    except Exception:
        return ""


def _extract(site, body):
    """Pull (title, company, location, url) tuples out of one alert email."""
    jobs, seen = [], set()
    # Anchor tags carry the job title; the company usually sits in the next cell.
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', body, re.S | re.I):
        url, label = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        label = re.sub(r"\s+", " ", html.unescape(label)).strip()
        if not JOB_LINK[site].search(url) or len(label) < 3:
            continue
        if label.lower() in ("view job", "apply", "see all jobs", "view all"):
            continue
        tail = re.sub(r"<[^>]+>", " ", body[m.end():m.end() + 400])
        tail = re.sub(r"\s+", " ", html.unescape(tail)).strip()
        bits = [b.strip() for b in re.split(r"[·|•]|\s{2,}", tail) if b.strip()][:2]
        key = (label.lower(), (bits[0] if bits else "").lower())
        if key in seen:
            continue
        seen.add(key)
        jobs.append({
            "source": f"alert:{site}",
            "external_id": hashlib.md5(url.split("?")[0].encode()).hexdigest()[:16],
            "title": label,
            "company": bits[0] if bits else "",
            "location": bits[1] if len(bits) > 1 else "",
            "url": url.split("?")[0], "apply_url": url.split("?")[0],
            "jd_text": "",          # filled later by matching against ATS data
        })
    return jobs


def fetch(host=None, user=None, password=None, folder="INBOX", days=3, limit=200):
    host = host or os.getenv("IMAP_HOST", "imap.gmail.com")
    user = user or os.getenv("IMAP_USER")
    password = password or os.getenv("IMAP_PASS")
    if not (user and password):
        return []

    out = []
    M = imaplib.IMAP4_SSL(host)
    M.login(user, password)
    M.select(folder)
    try:
        import datetime
        since = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%d-%b-%Y")
        for site, addrs in SENDERS.items():
            for addr in addrs:
                typ, data = M.search(None, f'(SINCE {since} FROM "{addr}")')
                if typ != "OK" or not data[0]:
                    continue
                for num in data[0].split()[-limit:]:
                    typ, raw = M.fetch(num, "(RFC822)")
                    if typ != "OK":
                        continue
                    msg = email.message_from_bytes(raw[0][1])
                    out.extend(_extract(site, _body(msg)))
    finally:
        M.close(); M.logout()
    return out


def backfill_jd(con, alert_jobs):
    """Alert emails carry no JD. Match each against ATS rows we already hold so the
    tailor gets real text - and so we apply via the company's own board, not the portal."""
    matched = 0
    for j in alert_jobs:
        if not j["company"] or not j["title"]:
            continue
        row = con.execute(
            """SELECT jd_text, apply_url FROM jobs
               WHERE lower(company) LIKE ? AND lower(title) LIKE ?
                 AND jd_text IS NOT NULL AND length(jd_text) > 400 LIMIT 1""",
            (f"%{j['company'].lower()[:18]}%", f"%{j['title'].lower()[:22]}%")).fetchone()
        if row:
            j["jd_text"] = row["jd_text"]
            j["apply_url"] = row["apply_url"]      # prefer the ATS front door
            matched += 1
    return matched
