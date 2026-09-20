"""Identity is loaded from data/master_resume.json, never hardcoded.

That file is gitignored so the repository can be published without shipping
anyone's contact details. data/master_resume.example.json shows the shape.
"""
import json, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
MASTER = ROOT / "data" / "master_resume.json"
EXAMPLE = ROOT / "data" / "master_resume.example.json"


def load():
    path = MASTER if MASTER.exists() else EXAMPLE
    if not path.exists():
        raise FileNotFoundError(
            "No data/master_resume.json. Copy data/master_resume.example.json "
            "and fill it in.")
    return json.loads(path.read_text())


def profile():
    """Flat field map used for form filling and the dashboard copy panel."""
    m = load()
    name = m.get("name", "")
    first, _, last = name.partition(" ")
    li = m.get("linkedin", "")
    return {
        "Full name": name,
        "First name": first,
        "Last name": last,
        "Email": m.get("email", ""),
        "Phone": m.get("phone", ""),
        "LinkedIn": li if li.startswith("http") else (f"https://{li}" if li else ""),
        "Location": m.get("location", ""),
        "Notice period": m.get("notice_period", "As per current role"),
        "Experience": m.get("experience_years", ""),
    }


def autofill():
    """Flat map the browser autofill script consumes."""
    m = load()
    name = m.get("name", "")
    first, _, last = name.partition(" ")
    li = m.get("linkedin", "")
    exp = m.get("experience", [])
    cur = exp[0] if exp else {}
    edu = (m.get("education") or [{}])[0]
    return {
        "first_name": first, "last_name": last, "full_name": name,
        "email": m.get("email", ""), "phone": m.get("phone", ""),
        "linkedin": li if li.startswith("http") else (f"https://{li}" if li else ""),
        "github": m.get("github", ""), "portfolio": m.get("portfolio", ""),
        "location": m.get("location", ""),
        "notice": m.get("notice_period", "As per current role"),
        "experience": m.get("experience_years", ""),
        "current_company": cur.get("company", ""),
        "title": cur.get("role", ""),
        "current_ctc": m.get("current_ctc", ""),
        "expected_ctc": m.get("expected_ctc", ""),
        "education": edu.get("institution", ""),
        "degree": edu.get("degree", ""),
    }


def form_fields():
    """Keys the ATS form filler expects."""
    p = profile()
    return {
        "first_name": p["First name"], "last_name": p["Last name"],
        "full_name": p["Full name"], "email": p["Email"],
        "phone": re.sub(r"[^0-9+]", "", p["Phone"]),
        "linkedin": p["LinkedIn"], "location": p["Location"],
    }
