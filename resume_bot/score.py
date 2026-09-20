"""Rank postings against the profile. Deterministic and cheap - no LLM spend here.
The LLM only ever sees jobs that clear this bar."""
import pathlib, yaml, re
from . import db

CFG = pathlib.Path(__file__).resolve().parent.parent / "config" / "profile.yaml"


def known_employers(con):
    """Companies we have positive evidence are direct employers: they run their
    own ATS board, or we crawled a real careers page on their own domain.
    A positive signal beats blocklisting agency names - the name list is endless
    and always one variant behind."""
    names = set()
    for r in con.execute("SELECT DISTINCT company FROM jobs "
                         "WHERE source IN ('greenhouse','lever','ashby')"):
        if r["company"]:
            names.add(r["company"].lower().strip())
    try:
        import yaml
        seeds = yaml.safe_load(
            (pathlib.Path(__file__).resolve().parent.parent /
             "config" / "companies.yaml").read_text()) or []
        for c in seeds:
            if isinstance(c, dict) and c.get("name"):
                names.add(c["name"].lower().strip())
    except Exception:
        pass
    for r in con.execute("SELECT DISTINCT company FROM contacts"):
        if r["company"]:
            names.add(r["company"].lower().strip())
    return names


def load_profile():
    return yaml.safe_load(CFG.read_text())


_MODE_WORDS = re.compile(
    r"\b(remote|hybrid|on[\s\-]?site|in[\s\-]?office|work from home|wfh|flexible|"
    r"full[\s\-]?time|part[\s\-]?time|contract|multiple locations|various)\b", re.I)
_GLOBAL = {"", "anywhere", "worldwide", "global", "distributed", "any", "emea/apac"}


def _location_tier(job, L, jd):
    """india | remote_india | remote_global | reject"""
    loc = (job["location"] or "").lower()
    if any(c in loc for c in L["india_cities"]):
        return "india", "India onsite/hybrid"

    # No location at all (common in alert emails). Unknown is not foreign -
    # don't reject on absence of evidence, just don't reward it either.
    if not loc.strip():
        # No location field. Fall back to the JD/company text before trusting it -
        # "Sii Poland" with a blank location is not an India-open role.
        blob = f"{(job['company'] or '')} {jd[:1500]}".lower()
        if any(c in blob for c in ("india", "bengaluru", "bangalore", "hyderabad",
                                   "gurugram", "pune", "mumbai", "chennai", "noida")):
            return "remote_india", "India named, location field empty"
        foreign_named = any(f in blob for f in (
            "poland", "germany", "united states", "canada", "united kingdom",
            "netherlands", "spain", "france", "brazil", "mexico", "singapore",
            "australia", "philippines", "vietnam", "romania", "portugal"))
        if foreign_named:
            return "reject", "foreign market named, no India signal"
        return "remote_global", "location not stated"

    # Remove work-mode words and separators; whatever remains is geography.
    residue = _MODE_WORDS.sub(" ", loc)
    residue = re.sub(r"[^a-z ]+", " ", residue)
    residue = re.sub(r"\s+", " ", residue).strip()

    # A bare work-mode with no geography ("Hybrid", "Distributed") tells us
    # nothing. Only trust it if the JD actually names India.
    if residue in _GLOBAL:
        jd_india = any(c in jd for c in ("india", "bengaluru", "bangalore",
                                         "hyderabad", "gurugram", "pune"))
        if jd_india:
            return "remote_india", "remote, India named in JD"
        if not (job["remote"] or "remote" in loc or "anywhere" in loc
                or "worldwide" in loc):
            # e.g. bare "Hybrid" - hybrid to WHICH office? India unproven.
            return "reject", "work-mode only, no geography, India not named"
        return "remote_global", "remote, no geography stated"

    return "reject", "foreign geography"


def score_job(job, p, employers=None):
    title = (job["title"] or "").lower()
    jd = (job["jd_text"] or "").lower()
    loc = (job["location"] or "").lower()
    company = (job["company"] or "").lower()
    pts, why = 0, []

    for bad in p["exclude_companies"]:
        if bad in company:
            return 0, ["excluded company"]
    for bad in p["exclude_title_terms"]:
        if bad in title:
            return 0, [f"excluded title term: {bad}"]

    # Title match dominates - wrong role is unrecoverable no matter what the JD says.
    if any(t in title for t in p["target_titles"]["strong"]):
        pts += 45; why.append("strong title")
    elif any(t in title for t in p["target_titles"]["ok"]):
        pts += 24; why.append("adjacent title")
    elif any(t in title for t in p["target_titles"].get("fallback", [])):
        # Wider net. Deliberately low so an analyst role never outranks an
        # engineering one - these are options, not the target.
        pts += 8; why.append("fallback title (step down from current role)")
    else:
        return 0, ["title mismatch"]

    core = sum(1 for s in p["skills"]["core"] if s in jd)
    stack = sum(1 for s in p["skills"]["stack"] if s in jd)
    dom = sum(1 for s in p["skills"]["domain"] if s in jd)
    pts += min(core * 4, 28); why.append(f"{core} core skills")
    pts += min(stack * 2, 14); why.append(f"{stack} stack skills")
    pts += min(dom * 3, 12)
    if dom:
        why.append(f"{dom} domain terms")

    # India-primary location model.
    L = p["locations"]
    if any(b in jd or b in loc for b in L["blocked"]):
        return 0, ["closed to India-based applicants"]

    # Allowlist, not blocklist. Enumerating every foreign place name is a losing
    # game ("Remote - California" slipped a blocklist three times). Instead:
    # strip the work-mode words and see what geography is LEFT. India or nothing
    # passes; anything else names a market that isn't yours.
    tier, note = _location_tier(job, L, jd)
    if tier == "reject":
        return 0, [f"scoped to another market ({job['location']})"]
    pts += {"india": 26, "remote_india": 22, "remote_global": 9}[tier]
    why.append(note)

    # Junior-friendly signals - he has 1.5 yrs, so seniority language is a real filter.
    if re.search(r"\b(1\+|2\+|0-2|1-3|2-4|entry|junior|new grad)\s*year", jd):
        pts += 10; why.append("junior-friendly")
    if re.search(r"\b(5\+|6\+|7\+|8\+|10\+)\s*year", jd):
        pts -= 12; why.append("seniority gap")

    if len(jd) < 400:
        pts -= 8; why.append("thin JD")

    # Staffing firm rather than the employer - one more layer between you and
    # the hiring manager, and often the same role listed by several agencies.
    if any(m in company for m in p.get("recruiter_markers", [])):
        pts -= 18; why.append("recruiter/staffing listing")

    # Positive evidence of a direct employer outranks name-pattern guessing.
    if employers:
        c = company.strip()
        if c in employers or any(c.startswith(e[:18]) for e in employers if len(e) > 6):
            pts += 14; why.append("verified direct employer")

    return max(0, min(100, pts)), why


def run():
    p = load_profile()
    con = db.connect()
    employers = known_employers(con)
    rows = con.execute("SELECT * FROM jobs WHERE score IS NULL").fetchall()
    for r in rows:
        s, why = score_job(r, p, employers)
        status = "scored" if s >= p["min_score"] else "rejected"
        con.execute("UPDATE jobs SET score=?, score_reasons=?, status=? WHERE id=?",
                    (s, "; ".join(why), status, r["id"]))
    con.commit()
    stats = con.execute(
        "SELECT status, COUNT(*) c FROM jobs GROUP BY status").fetchall()
    con.close()
    return {r["status"]: r["c"] for r in stats}
