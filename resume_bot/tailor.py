"""Tailor the master resume to one JD.

Hard rule: the model may REORDER, RE-EMPHASISE and RE-WORD what is already in
master_resume.json. It may not invent employers, dates, metrics or technologies.
verify_no_fabrication() enforces the numeric half of that automatically.
"""
import json, os, re, pathlib, hashlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
MASTER = ROOT / "data" / "master_resume.json"

SYSTEM = """You tailor one candidate's resume to a specific job description.

ABSOLUTE RULES
- Use ONLY facts present in the master resume JSON. Never invent employers, titles,
  dates, metrics, technologies or outcomes.
- Never change any number, percentage, date or company name.
- You may reorder projects/bullets, rewrite wording for emphasis, and select which
  skills to surface first.
- Mirror the job's vocabulary ONLY where the candidate genuinely has that experience.
- If the candidate lacks something the job wants, stay silent. Do not imply it.

Return STRICT JSON:
{
  "summary": "<3-4 line summary retargeted to this role>",
  "skills_order": ["<skill group names, most relevant first>"],
  "featured_keywords": ["<<=12 terms from the JD the candidate genuinely has>"],
  "project_order": ["<project names, most relevant first>"],
  "bullet_rewrites": {"<project name>": ["<rewritten bullet>", ...]},
  "fit_rationale": "<2 sentences: why this candidate fits this specific role>",
  "gaps": ["<honest list of what the JD asks for that he lacks>"]
}"""


def load_master():
    return json.loads(MASTER.read_text())


def build_user_prompt(job, master, company_ctx=""):
    jd = (job["jd_text"] or "")[:6000]
    return f"""MASTER RESUME (source of truth):
{json.dumps(master, indent=2)}

TARGET ROLE
Company: {job['company']}
Title: {job['title']}
Location: {job.get('location')}
{('Company context: ' + company_ctx) if company_ctx else ''}

JOB DESCRIPTION:
{jd}

Tailor the resume for this role. Return only the JSON object."""


# ---------- fabrication guard ----------

NUM = re.compile(r"\b\d+(?:\.\d+)?%?\b")

def verify_no_fabrication(tailored, master):
    """Every number in generated prose must already exist in the master resume."""
    allowed = set(NUM.findall(json.dumps(master)))
    prose = " ".join(
        [tailored.get("summary", ""), tailored.get("fit_rationale", "")]
        + [b for bs in tailored.get("bullet_rewrites", {}).values() for b in bs]
    )
    invented = [n for n in NUM.findall(prose) if n not in allowed]
    return invented


# ---------- dry-run stub ----------

def _stub(job, master):
    """Deterministic fake output so the whole pipeline is testable with no API key."""
    jd = (job["jd_text"] or "").lower()
    groups = list(master["skills"].keys())
    groups.sort(key=lambda g: -sum(1 for s in master["skills"][g] if s.split()[0].lower() in jd))
    projects = [p["name"] for e in master["experience"] for p in e["projects"]]
    projects.sort(key=lambda n: -sum(1 for w in n.lower().split() if w in jd))
    hits = [k for k in ("rag", "llm", "agentic", "python", "fastapi", "azure", "evaluation",
                        "retrieval", "prompt", "docker", "embedding", "langchain") if k in jd]
    return {
        "summary": master["summary"],
        "skills_order": groups,
        "featured_keywords": hits[:12],
        "project_order": projects,
        "bullet_rewrites": {},
        "fit_rationale": f"[DRY RUN] Matched on {len(hits)} JD keywords for {job['title']} at {job['company']}.",
        "gaps": ["[DRY RUN] no gap analysis without a live model"],
    }


def tailor(job, master=None, company_ctx="", dry_run=None):
    master = master or load_master()
    if dry_run is None:
        dry_run = not os.getenv("ANTHROPIC_API_KEY")

    if dry_run:
        out = _stub(job, master)
        out["_mode"] = "dry-run"
        return out

    from anthropic import Anthropic
    client = Anthropic()
    resp = client.messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"),
        max_tokens=2000,
        system=SYSTEM,
        messages=[{"role": "user", "content": build_user_prompt(job, master, company_ctx)}],
    )
    text = resp.content[0].text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    out = json.loads(text)
    out["_mode"] = "live"

    invented = verify_no_fabrication(out, master)
    if invented:
        out["_warning"] = f"BLOCKED: model introduced numbers not in master: {invented}"
        out["summary"] = master["summary"]      # fall back to the verified original
        out["bullet_rewrites"] = {}
    return out
