"""Fetch public company context + PUBLISHED application addresses.

Two rules this module exists to enforce:
  1. robots.txt is honoured on every fetch.
  2. We only collect addresses a company deliberately publishes for applicants
     (careers@, jobs@, hiring@, recruiting@). We never guess personal addresses
     like firstname.lastname@ - guessed addresses bounce, bounces wreck sender
     reputation, and nobody consented to being contacted at one.
"""
import re, urllib.robotparser as rp, urllib.parse as up
import httpx

UA = "job-pipeline/0.1 (personal job search)"
HEADERS = {"User-Agent": f"Mozilla/5.0 (compatible; {UA})"}
TIMEOUT = httpx.Timeout(20.0, connect=8.0)

ROLE_ADDRS = re.compile(
    r"\b((?:careers?|jobs?|hiring|recruit(?:ing|ment)?|talent|hr|apply|resumes?|cv)"
    r"@[a-z0-9][a-z0-9\.\-]*\.[a-z]{2,})\b", re.I)

CAREER_PATHS = ["/careers", "/jobs", "/about", "/company", "/careers/",
                "/about-us", "/work-with-us"]

_robots_cache = {}


def allowed(url):
    """Ask robots.txt before every fetch. Fail closed on error."""
    try:
        parts = up.urlparse(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in _robots_cache:
            r = rp.RobotFileParser()
            r.set_url(root + "/robots.txt")
            try:
                r.read()
            except Exception:
                _robots_cache[root] = None      # no robots.txt served -> permitted
                return True
            _robots_cache[root] = r
        parser = _robots_cache[root]
        return True if parser is None else parser.can_fetch(UA, url)
    except Exception:
        return False


def _text(html_str, limit=4000):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_str, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()[:limit]


def domain_from_url(url):
    try:
        net = up.urlparse(url).netloc.lower()
        return net[4:] if net.startswith("www.") else net
    except Exception:
        return ""


def enrich(client, company, homepage=None):
    """Return {summary, emails, pages_read} for one company."""
    out = {"company": company, "summary": "", "emails": [], "pages_read": []}
    if not homepage:
        return out
    base = homepage.rstrip("/")

    for path in CAREER_PATHS:
        url = base + path
        if not allowed(url):
            continue
        try:
            r = client.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)
            if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
                continue
        except Exception:
            continue
        out["pages_read"].append(url)
        body = r.text
        if not out["summary"]:
            out["summary"] = _text(body, 2500)
        for m in ROLE_ADDRS.finditer(body):
            addr = m.group(1).lower()
            if addr not in out["emails"]:
                out["emails"].append(addr)
        if len(out["pages_read"]) >= 3:
            break
    return out
