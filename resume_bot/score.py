"""Rank postings against the profile. Deterministic and cheap - no LLM spend here.
The LLM only ever sees jobs that clear this bar."""
import pathlib, yaml, re
from . import db

CFG = pathlib.Path(__file__).resolve().parent.parent / "config" / "profile.yaml"


def load_profile():
    return yaml.safe_load(CFG.read_text())


def score_job(job, p):
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
        pts += 22; why.append("adjacent title")
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

    if job["remote"] or any(l in loc for l in p["locations_ok"]):
        pts += 8; why.append("location ok")
    else:
        pts -= 25; why.append("location mismatch")

    # Junior-friendly signals - he has 1.5 yrs, so seniority language is a real filter.
    if re.search(r"\b(1\+|2\+|0-2|1-3|2-4|entry|junior|new grad)\s*year", jd):
        pts += 10; why.append("junior-friendly")
    if re.search(r"\b(5\+|6\+|7\+|8\+|10\+)\s*year", jd):
        pts -= 12; why.append("seniority gap")

    if len(jd) < 400:
        pts -= 8; why.append("thin JD")

    return max(0, min(100, pts)), why


def run():
    p = load_profile()
    con = db.connect()
    rows = con.execute("SELECT * FROM jobs WHERE score IS NULL").fetchall()
    for r in rows:
        s, why = score_job(r, p)
        status = "scored" if s >= p["min_score"] else "rejected"
        con.execute("UPDATE jobs SET score=?, score_reasons=?, status=? WHERE id=?",
                    (s, "; ".join(why), status, r["id"]))
    con.commit()
    stats = con.execute(
        "SELECT status, COUNT(*) c FROM jobs GROUP BY status").fetchall()
    con.close()
    return {r["status"]: r["c"] for r in stats}
