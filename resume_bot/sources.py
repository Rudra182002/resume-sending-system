"""Job sources. All public, documented, keyless endpoints - no scraping, no ToS risk."""
import json, re, html, time, hashlib
import httpx

UA = {"User-Agent": "Mozilla/5.0 (compatible; job-pipeline/0.1; +personal-jobsearch)"}
TIMEOUT = httpx.Timeout(25.0, connect=10.0)


def _clean(raw_html: str) -> str:
    if not raw_html:
        return ""
    txt = re.sub(r"<[^>]+>", " ", html.unescape(raw_html))
    return re.sub(r"\s+", " ", txt).strip()


def _get(client, url):
    r = client.get(url, headers=UA, timeout=TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    return r


# ---------- ATS boards (company's own posting, richest JD text) ----------

def greenhouse(client, slug):
    d = _get(client, f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true").json()
    out = []
    for j in d.get("jobs", []):
        out.append({
            "source": "greenhouse", "external_id": j["id"], "company_slug": slug,
            "company": slug.replace("-", " ").title(),
            "title": j.get("title", ""),
            "location": (j.get("location") or {}).get("name"),
            "url": j.get("absolute_url"), "apply_url": j.get("absolute_url"),
            "jd_text": _clean(j.get("content", "")),
            "posted_at": j.get("updated_at"),
        })
    return out


def lever(client, slug):
    d = _get(client, f"https://api.lever.co/v0/postings/{slug}?mode=json").json()
    out = []
    for j in d:
        cat = j.get("categories") or {}
        sal = j.get("salaryRange") or {}
        out.append({
            "source": "lever", "external_id": j["id"], "company_slug": slug,
            "company": slug.replace("-", " ").title(),
            "title": j.get("text", ""), "location": cat.get("location"),
            "remote": "remote" in (cat.get("location") or "").lower(),
            "url": j.get("hostedUrl"), "apply_url": j.get("applyUrl") or j.get("hostedUrl"),
            "jd_text": (j.get("descriptionPlain", "") + " " + j.get("additionalPlain", "")).strip(),
            "salary": f"{sal.get('min')}-{sal.get('max')} {sal.get('currency')}" if sal.get("min") else None,
            "posted_at": j.get("createdAt"),
        })
    return out


def ashby(client, slug):
    d = _get(client, f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true").json()
    out = []
    for j in d.get("jobs", []):
        out.append({
            "source": "ashby", "external_id": j.get("id"), "company_slug": slug,
            "company": slug.replace("-", " ").title(),
            "title": j.get("title", ""), "location": j.get("location"),
            "remote": bool(j.get("isRemote")),
            "url": j.get("jobUrl"), "apply_url": j.get("applyUrl") or j.get("jobUrl"),
            "jd_text": _clean(j.get("descriptionHtml") or j.get("descriptionPlain") or ""),
            "salary": json.dumps(j.get("compensation")) if j.get("compensation") else None,
            "posted_at": j.get("publishedAt"),
        })
    return out


# ---------- Aggregators (no slug needed, wide net) ----------

def arbeitnow(client, pages=3):
    out, url = [], "https://www.arbeitnow.com/api/job-board-api"
    for _ in range(pages):
        d = _get(client, url).json()
        for j in d.get("data", []):
            out.append({
                "source": "arbeitnow", "external_id": j.get("slug"),
                "company": j.get("company_name", ""), "title": j.get("title", ""),
                "location": j.get("location"), "remote": bool(j.get("remote")),
                "url": j.get("url"), "apply_url": j.get("url"),
                "jd_text": _clean(j.get("description", "")),
                "posted_at": str(j.get("created_at")),
            })
        url = (d.get("links") or {}).get("next")
        if not url:
            break
    return out


def remoteok(client):
    d = _get(client, "https://remoteok.com/api").json()
    out = []
    for j in d[1:] if d and isinstance(d[0], dict) and "legal" in str(d[0]).lower() else d:
        if not isinstance(j, dict) or not j.get("id"):
            continue
        out.append({
            "source": "remoteok", "external_id": j.get("id"),
            "company": j.get("company", ""), "title": j.get("position", ""),
            "location": j.get("location") or "Remote", "remote": True,
            "url": j.get("url"), "apply_url": j.get("apply_url") or j.get("url"),
            "jd_text": _clean(j.get("description", "")),
            "salary": j.get("salary"), "posted_at": j.get("date"),
        })
    return out


def remotive(client, queries=("machine learning", "ai engineer", "llm", "nlp", "data scientist")):
    out = []
    for q in queries:
        try:
            d = _get(client, f"https://remotive.com/api/remote-jobs?search={httpx.QueryParams({'q': q})['q']}").json()
        except Exception:
            continue
        for j in d.get("jobs", []):
            out.append({
                "source": "remotive", "external_id": j.get("id"),
                "company": j.get("company_name", ""), "title": j.get("title", ""),
                "location": j.get("candidate_required_location"), "remote": True,
                "url": j.get("url"), "apply_url": j.get("url"),
                "jd_text": _clean(j.get("description", "")),
                "salary": j.get("salary"), "posted_at": j.get("publication_date"),
            })
        time.sleep(0.3)
    return out


# ---------- Official aggregator APIs (free keys; skipped when unset) ----------

def adzuna(client, app_id, app_key, country="in", pages=3,
           queries=("ai engineer", "machine learning engineer", "llm", "data scientist")):
    """Adzuna jobseeker API - broad India coverage. https://developer.adzuna.com"""
    out = []
    for q in queries:
        for page in range(1, pages + 1):
            url = (f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
                   f"?app_id={app_id}&app_key={app_key}&results_per_page=50"
                   f"&what={q.replace(' ', '%20')}&content-type=application/json")
            try:
                d = _get(client, url).json()
            except Exception:
                break
            for j in d.get("results", []):
                out.append({
                    "source": "adzuna", "external_id": j.get("id"),
                    "company": (j.get("company") or {}).get("display_name", ""),
                    "title": j.get("title", ""),
                    "location": (j.get("location") or {}).get("display_name"),
                    "url": j.get("redirect_url"), "apply_url": j.get("redirect_url"),
                    "jd_text": _clean(j.get("description", "")),
                    "salary": str(j.get("salary_min") or "") or None,
                    "posted_at": j.get("created"),
                })
            if len(d.get("results", [])) < 50:
                break
    return out


def jooble(client, api_key, keywords=("ai engineer", "machine learning"), location="India"):
    """Jooble API - POST based. https://jooble.org/api/about"""
    out = []
    for kw in keywords:
        try:
            r = client.post(f"https://jooble.org/api/{api_key}",
                            json={"keywords": kw, "location": location},
                            headers={**UA, "Content-Type": "application/json"}, timeout=TIMEOUT)
            r.raise_for_status()
            d = r.json()
        except Exception:
            continue
        for j in d.get("jobs", []):
            out.append({
                "source": "jooble", "external_id": j.get("id"),
                "company": j.get("company", ""), "title": j.get("title", ""),
                "location": j.get("location"), "url": j.get("link"),
                "apply_url": j.get("link"), "jd_text": _clean(j.get("snippet", "")),
                "salary": j.get("salary"), "posted_at": j.get("updated"),
            })
    return out


def careerjet(client, affid, keywords="ai engineer", location="India", pages=3):
    """Careerjet public search API. https://www.careerjet.com/partners/api/"""
    out = []
    for page in range(1, pages + 1):
        url = (f"http://public.api.careerjet.net/search?affid={affid}"
               f"&keywords={keywords.replace(' ', '%20')}&location={location}"
               f"&pagesize=99&page={page}&user_ip=1.2.3.4&user_agent=api&locale_code=en_IN")
        try:
            d = _get(client, url).json()
        except Exception:
            break
        for j in d.get("jobs", []):
            out.append({
                "source": "careerjet",
                "external_id": hashlib.md5((j.get("url") or "").encode()).hexdigest()[:16],
                "company": j.get("company", ""), "title": j.get("title", ""),
                "location": j.get("locations"), "url": j.get("url"),
                "apply_url": j.get("url"), "jd_text": _clean(j.get("description", "")),
                "salary": j.get("salary"), "posted_at": j.get("date"),
            })
        if not d.get("jobs"):
            break
    return out
