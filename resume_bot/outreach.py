"""Draft one outreach email per job. LLM-written, dry-run capable."""
import os, json, re

SYSTEM = """You write short, specific job-application emails for one candidate.

RULES
- 120-160 words. No filler, no "I am writing to express my interest".
- Open with something concrete about THIS company's work, drawn from the context given.
- One sentence connecting a real project of the candidate's to this role's needs.
- Never invent facts, metrics, or experience not in the resume JSON.
- Plain, human, unexcited. No "passionate", "dynamic", "synergy", no exclamation marks.
- Close with a low-friction ask (a short call, or simply "happy to send more detail").

Return STRICT JSON: {"subject": "...", "body": "..."}
Subject: under 60 chars, concrete, no clickbait."""


def build_prompt(job, master, tailored, company_ctx=""):
    return f"""CANDIDATE:
{json.dumps({k: master[k] for k in ('name','headline','summary','skills')}, indent=2)}

MOST RELEVANT PROJECTS (in order): {tailored.get('project_order', [])[:3]}
WHY THEY FIT: {tailored.get('fit_rationale', '')}

ROLE: {job['title']} at {job['company']} ({job.get('location')})
COMPANY CONTEXT: {company_ctx[:1500] or '(none available)'}
JOB DESCRIPTION (excerpt): {(job.get('jd_text') or '')[:2000]}

Write the email. Return only the JSON object."""


def _stub(job, master, tailored):
    return {
        "subject": f"{master['name']} - {job['title']}",
        "body": (f"[DRY RUN] Hi,\n\nI'm applying for {job['title']} at {job['company']}. "
                 f"I build production GenAI systems - agentic RAG, document extraction and "
                 f"LLM evaluation harnesses - most recently an extraction platform running at "
                 f"95.4% mean field accuracy across 362 live submissions.\n\n"
                 f"Resume attached. Happy to send more detail.\n\n{master['name']}"),
        "_mode": "dry-run",
    }


def draft(job, master, tailored, company_ctx="", dry_run=None):
    if dry_run is None:
        dry_run = not os.getenv("ANTHROPIC_API_KEY")
    if dry_run:
        return _stub(job, master, tailored)

    from anthropic import Anthropic
    resp = Anthropic().messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"),
        max_tokens=900, system=SYSTEM,
        messages=[{"role": "user",
                   "content": build_prompt(job, master, tailored, company_ctx)}],
    )
    txt = re.sub(r"^```(?:json)?|```$", "", resp.content[0].text.strip(), flags=re.M).strip()
    out = json.loads(txt)
    out["_mode"] = "live"
    return out
