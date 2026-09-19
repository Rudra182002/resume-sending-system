"""Parse job-alert emails out of your own inbox over IMAP.

Covers LinkedIn / Naukri / foundit without touching those sites: you subscribe to
their alerts, they mail you, we read YOUR mailbox. Their delivery channel, your
credentials, nothing automated pointed at their servers.

Setup: create job alerts on each site, then filter them into one IMAP folder
(e.g. "JobAlerts") so we read a narrow, predictable slice of your mail.
"""
import imaplib, email, re, html, os, hashlib, time
from email.header import decode_header

# Verified against a real mailbox - these are the addresses actually used.
SENDERS = {
    "linkedin": ["jobalerts-noreply@linkedin.com", "jobs-noreply@linkedin.com",
                 "jobs-listings@linkedin.com"],
    "naukri":   ["naukrialerts@naukri.com", "info@naukri.com", "alerts@naukri.com"],
    "foundit":  ["opportunities@foundit.in", "updates@alerts.foundit.in",
                 "info@alerts.foundit.in", "jobmessenger@monsterindia.com"],
}

CITY_RE = re.compile(
    r"\b(Bengaluru|Bangalore|Hyderabad|Pune|Kolkata|Chennai|Mumbai|Navi Mumbai|"
    r"Delhi|New Delhi|Gurugram|Gurgaon|Noida|Ahmedabad|Jaipur|Kochi|Coimbatore|"
    r"Indore|Chandigarh|Thiruvananthapuram|Bhubaneswar|Nagpur|Vadodara|India)\b")

JOB_LINK = {
    "linkedin": re.compile(r"https://www\.linkedin\.com/(?:comm/)?jobs/view/(\d+)"),
    "naukri":   re.compile(r"https?://(?:www\.)?naukri\.com/(?:job-listings-|jobs/)[\w\-]+"),
    "foundit":  re.compile(r"https?://(?:www\.)?(?:foundit\.in|monsterindia\.com)/"
                           r"(?:job|srp|seeker)/[\w\-/]+"),
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
        # Take a generous window, drop any tag fragment the slice cut in half,
        # then strip tags. A 400-char window used to slice mid-tag, leaving raw
        # HTML like '<p class="text-system-...' as the company name.
        tail = body[m.end():m.end() + 2500]
        tail = re.sub(r"<[^>]*>", " ", tail)     # complete tags
        tail = re.sub(r"<[^>]*$", " ", tail)     # trailing half-tag
        tail = re.sub(r"^[^<]*?>", " ", tail)    # leading half-tag
        tail = re.sub(r"&[a-z]+;|&#\d+;", " ", tail)
        tail = re.sub(r"\s+", " ", html.unescape(tail)).strip()
        bits = [b.strip(" ·|•-") for b in re.split(r"[·|•]|\s{2,}", tail)
                if b.strip(" ·|•-") and "<" not in b and len(b.strip()) > 1][:2]
        # LinkedIn packs "Company City (Mode)" into one string. Split the city
        # and work-mode back out so location scoring has something to use.
        company, location = (bits[0] if bits else ""), (bits[1] if len(bits) > 1 else "")
        mm = re.search(r"\((On-?site|Remote|Hybrid)\)\s*$", company, re.I)
        mode = mm.group(1) if mm else ""
        if mm:
            company = company[:mm.start()].strip()
        cm = CITY_RE.search(company)
        if cm:
            location = (company[cm.start():].strip() + (f" ({mode})" if mode else "")).strip()
            company = company[:cm.start()].strip(" ,-")
        elif mode:
            location = mode
        key = (label.lower(), (bits[0] if bits else "").lower())
        if key in seen:
            continue
        seen.add(key)
        jobs.append({
            "source": f"alert:{site}",
            "external_id": hashlib.md5(url.split("?")[0].encode()).hexdigest()[:16],
            "title": label,
            "company": company,
            "location": location,
            "url": url.split("?")[0], "apply_url": url.split("?")[0],
            "jd_text": "",          # filled later by matching against ATS data
        })
    return jobs


def fetch(host=None, user=None, password=None, folder="INBOX", days=None,
          limit=200, verbose=False):
    host = host or os.getenv("IMAP_HOST", "imap.gmail.com")
    user = user or os.getenv("IMAP_USER")
    password = password or os.getenv("IMAP_PASS")
    if not (user and password):
        return []
    days = int(days or os.getenv("IMAP_DAYS", "7"))

    # Gmail throttles rapid repeat IMAP sessions: SEARCH starts returning empty
    # rather than erroring. Retry with backoff before believing a zero.
    for attempt in range(3):
        out, searched = _harvest(host, user, password, folder, days, limit, verbose)
        if out or not searched:
            return out
        if attempt < 2:
            time.sleep(8 * (attempt + 1))
    return out


def _harvest(host, user, password, folder, days, limit, verbose=False):
    """Returns (jobs, n_messages_searched). searched==0 means nothing matched at
    all, which is different from 'matched but extracted nothing'."""
    out, searched = [], 0
    M = imaplib.IMAP4_SSL(host)
    M.login(user, password)
    # readonly: never let a harvest change flags on the user's real mailbox
    M.select(folder, readonly=True)
    try:
        import datetime
        since = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%d-%b-%Y")
        for site, addrs in SENDERS.items():
            for addr in addrs:
                typ, data = M.search(None, f'(SINCE {since} FROM "{addr}")')
                if typ != "OK" or not data[0]:
                    continue
                ids = data[0].split()[-limit:]          # newest N only
                searched += len(ids)
                if verbose:
                    print(f"    {site}/{addr}: {len(ids)} messages")
                for num in ids:
                    # BODY.PEEK[] does not set \Seen. Plain RFC822 does, which
                    # would mark hundreds of the user's emails as read.
                    typ, raw = M.fetch(num, "(BODY.PEEK[])")
                    if typ != "OK" or not raw or not isinstance(raw[0], tuple):
                        continue
                    try:
                        msg = email.message_from_bytes(raw[0][1])
                        out.extend(_extract(site, _body(msg)))
                    except Exception:
                        continue
    finally:
        try:
            M.close()
        except Exception:
            pass
        M.logout()
    return out, searched


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
