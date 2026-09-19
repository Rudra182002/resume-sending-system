"""Crawl arbitrary company sites for careers pages, embedded ATS boards, and
published application addresses.

Built for the long tail - Indian startups that never appear on a public ATS
board. For each domain:
  1. find the careers page (common paths, then homepage links)
  2. sniff for an embedded ATS (greenhouse/lever/ashby/workable/recruitee/zoho)
     -> if found we get the slug and use that ATS's real API, full JD and all
  3. otherwise scrape visible role titles off the page
  4. collect role-based addresses the company publishes for applicants

robots.txt is honoured on every fetch. Only published role addresses are kept -
never guessed personal ones.
"""
import re, html, pathlib, yaml
import httpx
from . import enrich

HEADERS = enrich.HEADERS
TIMEOUT = httpx.Timeout(18.0, connect=7.0)
SEEDS = pathlib.Path(__file__).resolve().parent.parent / "config" / "companies.yaml"

# Slug patterns for ATS widgets embedded in a company's own careers page.
ATS_PATTERNS = {
    "greenhouse": [r"boards\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_\-]+)",
                   r"job-boards\.greenhouse\.io/([a-z0-9_\-]+)"],
    "lever":      [r"jobs\.lever\.co/([a-z0-9_\-]+)", r"api\.lever\.co/v0/postings/([a-z0-9_\-]+)"],
    "ashby":      [r"jobs\.ashbyhq\.com/([a-z0-9_\-]+)"],
    "workable":   [r"apply\.workable\.com/([a-z0-9_\-]+)"],
    "recruitee":  [r"([a-z0-9_\-]+)\.recruitee\.com"],
    "zoho":       [r"([a-z0-9_\-]+)\.zohorecruit\.(?:com|in)"],
}

CAREER_HINT = re.compile(r"(career|job|join|hiring|we-?are-?hiring|opening|vacanc)", re.I)
# Deliberately conservative: role titles we'd actually consider.
TITLE_HINT = re.compile(
    r"\b((?:senior\s+|sr\.?\s+|lead\s+)?(?:ai|ml|machine learning|data|software|backend|"
    r"full[\s\-]?stack|research|applied|platform|genai|llm|nlp)\s+"
    r"(?:engineer|scientist|developer|architect)[a-z0-9 ,\-/()]{0,40})", re.I)


def _get(client, url):
    if not enrich.allowed(url):
        return None
    try:
        r = client.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)
        if r.status_code == 200 and "text/html" in r.headers.get("content-type", ""):
            return r.text
    except Exception:
        pass
    return None


def find_careers_url(client, base):
    """Common paths first, then any careers-ish link on the homepage."""
    for path in ("/careers", "/jobs", "/careers/", "/join-us", "/work-with-us",
                 "/company/careers", "/about/careers", "/hiring"):
        if _get(client, base + path):
            return base + path
    home = _get(client, base)
    if not home:
        return None
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', home, re.S | re.I):
        href, label = m.group(1), re.sub(r"<[^>]+>", "", m.group(2))
        if CAREER_HINT.search(href) or CAREER_HINT.search(label):
            if href.startswith("http"):
                return href if base.split("//")[-1].split("/")[0] in href else None
            return base + ("" if href.startswith("/") else "/") + href
    return None


def sniff_ats(page_html):
    for ats, pats in ATS_PATTERNS.items():
        for pat in pats:
            m = re.search(pat, page_html, re.I)
            if m:
                slug = m.group(1).lower()
                if slug not in ("embed", "www", "job_board", "jobs"):
                    return ats, slug
    return None, None


def scrape_titles(page_html, limit=25):
    text = re.sub(r"<[^>]+>", " ", html.unescape(page_html))
    text = re.sub(r"\s+", " ", text)
    out, seen = [], set()
    for m in TITLE_HINT.finditer(text):
        t = re.sub(r"\s+", " ", m.group(1)).strip(" ,-/")
        k = t.lower()
        if k not in seen and 6 < len(t) < 70:
            seen.add(k); out.append(t)
        if len(out) >= limit:
            break
    return out


def crawl_one(client, name, domain):
    base = domain.rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base
    res = {"company": name, "domain": base, "careers_url": None,
           "ats": None, "slug": None, "titles": [], "emails": []}

    careers = find_careers_url(client, base)
    if not careers:
        return res
    res["careers_url"] = careers
    page = _get(client, careers)
    if not page:
        return res

    ats, slug = sniff_ats(page)
    if ats:
        res["ats"], res["slug"] = ats, slug     # structured JDs available
    else:
        res["titles"] = scrape_titles(page)

    for m in enrich.ROLE_ADDRS.finditer(page):
        a = m.group(1).lower()
        if a not in res["emails"]:
            res["emails"].append(a)
    return res


def crawl(companies=None, workers=8):
    """companies: [{name, domain}] - defaults to config/companies.yaml"""
    import concurrent.futures as cf
    if companies is None:
        companies = yaml.safe_load(SEEDS.read_text()) if SEEDS.exists() else []
    out = []
    with httpx.Client(follow_redirects=True) as client:
        with cf.ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(crawl_one, client, c["name"], c["domain"]): c
                    for c in companies}
            for f in cf.as_completed(futs):
                try:
                    out.append(f.result())
                except Exception:
                    pass
    return out
