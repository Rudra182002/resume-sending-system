"""Tailor the master resume to one JD.

Hard rule: the model may REORDER, RE-EMPHASISE and RE-WORD what is already in
master_resume.json. It may not invent employers, dates, metrics or technologies.
verify_no_fabrication() enforces the numeric half of that automatically.
"""
import json, os, re, pathlib, hashlib
from . import llm

ROOT = pathlib.Path(__file__).resolve().parent.parent
MASTER = ROOT / "data" / "master_resume.json"

SYSTEM = """You are a senior technical recruiter who rewrites one engineer's resume
so a specific hiring manager reads it and thinks "this person has already solved my problem."

THE ONE INVIOLABLE RULE
Facts are frozen. Framing is free.
You may rewrite every sentence. You may not change what happened.

FROZEN (copy exactly, never alter, never invent):
  employers, job titles, dates, every number, every percentage, every metric,
  every named technology, every named product, degrees, institutions.
  If it is not in the master resume JSON, it does not exist. No exceptions,
  not even a plausible-sounding one.

FREE (rewrite aggressively):
  sentence structure, verbs, emphasis, ordering, which detail leads, what the
  work is CALLED, which problem it is framed as solving.

STRUCTURE IS FIXED
  - Same employers, same order, same dates.
  - Same projects under each employer. You may reorder them; you may not add,
    merge, drop or rename them.
  - EXACTLY the same number of bullets per project as the master. Not one more,
    not one fewer.
  - Each rewritten bullet stays within roughly 80-130% of the original length.

TECHNIQUES - use all of them

1. VOCABULARY MIRRORING. Read the JD's nouns and use theirs for the same thing.
   If they say "retrieval pipeline", do not say "extraction flow". If they say
   "evals", do not say "regression harness". Same work, their words.

2. DOMAIN TRANSLATION. He works in commercial insurance. Most readers do not.
   Restate the insurance specifics as the general engineering problem, then keep
   the domain as colour.
     insurance-native: "carrier loss runs with no shared format"
     for a fintech:    "high-variance third-party documents with no shared schema"
   The facts (hybrid BM25 + dense, 55+ routes, 95.4%, 362 submissions) never move.

3. PROBLEM-FIRST FRAMING. Open each bullet with the problem or the outcome, not
   the tool. "Built X using Y" is weak. "Turned <hard problem> into <result> by
   <approach>" is strong. The master bullets already do this - preserve it.

4. METRIC PLACEMENT. The strongest number goes in the first sentence of the
   summary and in the first bullet of the first project. 95.4% across 362 live
   submissions is his best evidence; it should be impossible to miss.

5. SENIORITY CALIBRATION. He has ~1.5 years. Never claim leadership, ownership
   of teams, or architecture authority he does not have. Write as someone who
   shipped hard things, not someone who ran an org. Confidence comes from
   specifics, not from adjectives.

6. GAP HONESTY. If the JD wants something he lacks, say nothing about it in the
   resume body and record it in "gaps". Never imply adjacent experience covers it.

VOICE
  Plain, concrete, unexcited. Past tense. Active voice.
  BANNED: passionate, dynamic, synergy, leverage (as a verb), spearheaded,
  results-driven, detail-oriented, cutting-edge, state-of-the-art, robust,
  seamless, utilize, ecosystem, journey, deep dive, rockstar, ninja, guru.
  No exclamation marks. No em-dash pile-ups. No sentence that could appear on
  any other engineer's resume.

THE TEST
  Before returning, ask of every bullet: could this sentence appear unchanged on
  a different engineer's resume? If yes, it is too generic - rewrite it with the
  specific system, constraint or number that only he has.

Return STRICT JSON, no prose, no code fence:
{
  "summary": "<3-4 sentences, retargeted, leading with the strongest relevant metric>",
  "skills_order": ["<skill group names from the master, most relevant first>"],
  "featured_keywords": ["<<=12 terms taken from the JD that he genuinely has>"],
  "project_order": ["<exact project names from the master, most relevant first>"],
  "bullet_rewrites": {"<exact project name>": ["<rewritten bullet>", ...]},
  "fit_rationale": "<2 sentences a hiring manager would accept, no hedging>",
  "gaps": ["<what the JD asks for that he genuinely lacks>"],
  "positioning": "<1 sentence: the angle you took and why>"
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

def verify_structure(tailored, master):
    """The prompt says structure is fixed. Check it, don't trust it."""
    problems = []
    real = {p["name"]: p for e in master["experience"] for p in e["projects"]}
    for name, bullets in (tailored.get("bullet_rewrites") or {}).items():
        if name not in real:
            problems.append(f"unknown project invented: {name!r}")
            continue
        want, got = len(real[name]["bullets"]), len(bullets)
        if want != got:
            problems.append(f"{name}: {got} bullets, master has {want}")
        for i, b in enumerate(bullets):
            if i >= want:
                break
            o = len(real[name]["bullets"][i])
            if not (0.6 * o <= len(b) <= 1.6 * o):
                problems.append(f"{name} bullet {i+1}: length {len(b)} vs {o}")
    for n in (tailored.get("project_order") or []):
        if n not in real:
            problems.append(f"project_order names unknown project: {n!r}")
    for g in (tailored.get("skills_order") or []):
        if g not in master["skills"]:
            problems.append(f"skills_order names unknown group: {g!r}")
    return problems


BANNED = ("passionate", "dynamic", "synergy", "spearhead", "results-driven",
          "detail-oriented", "cutting-edge", "state-of-the-art", "seamless",
          "utilize", "rockstar", "ninja", "guru", "deep dive")


def verify_voice(tailored):
    prose = " ".join([tailored.get("summary", ""), tailored.get("fit_rationale", "")]
                     + [b for bs in (tailored.get("bullet_rewrites") or {}).values()
                        for b in bs]).lower()
    return [w for w in BANNED if w in prose]


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
        dry_run = not llm.configured()

    if dry_run:
        out = _stub(job, master)
        out["_mode"] = "dry-run"
        return out

    out = llm.complete(SYSTEM, build_user_prompt(job, master, company_ctx),
                       max_tokens=2000)
    out["_mode"] = f"live:{llm.provider()}"

    invented = verify_no_fabrication(out, master)
    if invented:
        out["_warning"] = f"BLOCKED: numbers not in master: {invented}"
        out["summary"] = master["summary"]      # fall back to the verified original
        out["bullet_rewrites"] = {}
        return out

    structural = verify_structure(out, master)
    if structural:
        # Structure broke: keep the safe parts (ordering), drop the rewrites.
        out["_warning"] = "structure drift: " + "; ".join(structural[:3])
        out["bullet_rewrites"] = {}

    banned = verify_voice(out)
    if banned:
        out["_voice_warning"] = f"banned words present: {banned}"
    return out
