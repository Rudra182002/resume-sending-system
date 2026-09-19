"""Automated application form filling.

Three modes, set by APPLY_MODE in .env:
  prepare  (default) - fill every field, screenshot, STOP before submit.
                       You review the screenshot and click submit yourself.
  confirm            - fill, screenshot, and submit only jobs you pre-approved
                       by marking them status='approved' in the dashboard.
  auto               - fill and submit unattended. Read the warning below.

WARNING on 'auto': Greenhouse, Lever and Ashby ToS prohibit automated
submission, and they run bot detection. A flag on your email address follows
you across every company using that ATS, not just the one you tripped it on.
Custom questions ("why this company?", "notice period?") cannot be answered
well generically, and a human opens those. High volume here is not free.
"""
import os, re, pathlib, time, random, json
from . import db

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHOTS = ROOT / "output" / "applications"

PROFILE = {
    "first_name": "Rudrabha", "last_name": "Chakraborty",
    "full_name": "Rudrabha Chakraborty",
    "email": "crudrabha@gmail.com", "phone": "+917439968388",
    "linkedin": "https://linkedin.com/in/rudrabha-chakraborty-2b02551b7",
    "location": "Kolkata, India",
}

# Per-ATS selectors, tried in order; first that exists wins.
FIELDS = {
    "greenhouse": {
        "first_name": ["#first_name", "input[name='first_name']", "input[autocomplete='given-name']"],
        "last_name":  ["#last_name", "input[name='last_name']", "input[autocomplete='family-name']"],
        "email":      ["#email", "input[name='email']", "input[type='email']"],
        "phone":      ["#phone", "input[name='phone']", "input[type='tel']"],
        "resume":     ["input[type='file']"],
        "submit":     ["#submit_app", "button[type='submit']", "input[type='submit']"],
    },
    "lever": {
        "full_name":  ["input[name='name']"],
        "email":      ["input[name='email']"],
        "phone":      ["input[name='phone']"],
        "linkedin":   ["input[name='urls[LinkedIn]']", "input[name='urls[Linkedin]']"],
        "resume":     ["input[name='resume']", "input[type='file']"],
        "submit":     ["button[type='submit']", ".template-btn-submit"],
    },
    "ashby": {
        "full_name":  ["input[name='_systemfield_name']", "input[aria-label*='Name']"],
        "email":      ["input[name='_systemfield_email']", "input[type='email']"],
        "phone":      ["input[name='_systemfield_phone']", "input[type='tel']"],
        "resume":     ["input[type='file']"],
        "submit":     ["button[type='submit']"],
    },
}


def detect_ats(url):
    u = (url or "").lower()
    if "greenhouse" in u:
        return "greenhouse"
    if "lever.co" in u:
        return "lever"
    if "ashbyhq" in u:
        return "ashby"
    return None


def _fill_first(page, selectors, value):
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.count() and el.is_visible(timeout=1500):
                el.fill(value, timeout=4000)
                return sel
        except Exception:
            continue
    return None


def _upload(page, selectors, path):
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.count():
                el.set_input_files(path, timeout=8000)
                return sel
        except Exception:
            continue
    return None


def unanswered_questions(page):
    """Custom questions we did NOT fill - the ones that decide the application."""
    found = []
    try:
        for sel in ["textarea", "select"]:
            for i in range(min(page.locator(sel).count(), 12)):
                el = page.locator(sel).nth(i)
                if not el.is_visible():
                    continue
                val = (el.input_value() or "").strip() if sel == "textarea" else ""
                if val:
                    continue
                label = ""
                for attr in ("aria-label", "name", "id", "placeholder"):
                    label = el.get_attribute(attr) or ""
                    if label:
                        break
                found.append(f"{sel}: {label[:70]}")
    except Exception:
        pass
    return found


def apply_to(job, resume_path, mode=None, headless=True):
    """Fill one application. Returns a result dict; never submits unless mode='auto'
    (or 'confirm' and the job was pre-approved)."""
    from playwright.sync_api import sync_playwright

    mode = mode or os.getenv("APPLY_MODE", "prepare").lower()
    ats = detect_ats(job.get("apply_url"))
    SHOTS.mkdir(parents=True, exist_ok=True)
    res = {"job_id": job["id"], "company": job["company"], "title": job["title"],
           "ats": ats, "mode": mode, "filled": {}, "questions": [],
           "submitted": False, "screenshot": None, "error": None}

    if not ats:
        res["error"] = f"unrecognised ATS: {job.get('apply_url')}"
        return res

    fields = FIELDS[ats]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=headless,
                                    args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1280, "height": 1600})
        page = ctx.new_page()
        try:
            page.goto(job["apply_url"], timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)          # let React forms mount

            for key, selectors in fields.items():
                if key in ("submit", "resume"):
                    continue
                val = PROFILE.get(key)
                if not val:
                    continue
                hit = _fill_first(page, selectors, val)
                if hit:
                    res["filled"][key] = hit

            if resume_path and pathlib.Path(resume_path).exists():
                hit = _upload(page, fields["resume"], str(resume_path))
                if hit:
                    res["filled"]["resume"] = hit

            page.wait_for_timeout(1200)
            res["questions"] = unanswered_questions(page)

            shot = SHOTS / f"{job['id']}_{re.sub(r'[^a-z0-9]+','-',job['company'].lower())[:28]}.png"
            page.screenshot(path=str(shot), full_page=True)
            res["screenshot"] = str(shot)

            if mode == "auto" or (mode == "confirm" and job.get("status") == "approved"):
                if res["questions"]:
                    res["error"] = (f"{len(res['questions'])} unanswered custom question(s) "
                                    "- refusing to submit a half-filled application")
                else:
                    for sel in fields["submit"]:
                        try:
                            btn = page.locator(sel).first
                            if btn.count() and btn.is_visible():
                                btn.click(timeout=8000)
                                page.wait_for_timeout(4000)
                                res["submitted"] = True
                                break
                        except Exception:
                            continue
                    time.sleep(random.uniform(8, 20))   # don't hammer the ATS
        except Exception as e:
            res["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        finally:
            ctx.close(); browser.close()
    return res


def run(limit=10, mode=None, headless=True):
    con = db.connect()
    rows = con.execute(
        """SELECT j.*, a.resume_path FROM jobs j JOIN applications a ON a.job_id=j.id
           WHERE j.status='queued' AND j.apply_url IS NOT NULL
           ORDER BY j.score DESC LIMIT ?""", (limit,)).fetchall()
    out = []
    for r in rows:
        job = dict(r)
        res = apply_to(job, job.get("resume_path"), mode=mode, headless=headless)
        out.append(res)
        if res["submitted"]:
            con.execute("UPDATE jobs SET status='applied' WHERE id=?", (job["id"],))
            con.execute("UPDATE applications SET submitted_at=? WHERE job_id=?",
                        (db.now(), job["id"]))
            con.commit()
        print(f"  {res['company'][:20]:20s} {res['ats'] or '?':10s} "
              f"filled={len(res['filled'])} questions={len(res['questions'])} "
              f"submitted={res['submitted']} {res['error'] or ''}")
    (ROOT / "output" / "apply_report.json").write_text(json.dumps(out, indent=2))
    return out
