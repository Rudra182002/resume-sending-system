"""Multi-agent application pipeline.

Each agent owns one job and one job only, reads and writes a shared context,
and fails in isolation - one agent breaking never kills the run.

  ResearchAgent  -> what does this company actually do?
  TailorAgent    -> retune the resume to this JD + that research
  RenderAgent    -> produce the ATS-safe PDF
  OutreachAgent  -> draft the email
  FormAgent      -> fill the portal form (submits only if APPLY_MODE says so)
  TrackerAgent   -> persist state, so a rerun resumes instead of repeating

Orchestrator runs them in order per job, several jobs in parallel, and writes
a per-agent trace the dashboard renders.
"""
import os, json, time, pathlib, traceback
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx
from . import db, tailor, render, enrich, outreach, llm

ROOT = pathlib.Path(__file__).resolve().parent.parent
DRAFTS = ROOT / "output" / "drafts"


@dataclass
class JobContext:
    job: dict
    research: str = ""
    tailored: dict = None
    resume_path: str = ""
    email: dict = None
    form: dict = None
    trace: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def log(self, agent, status, detail="", ms=0):
        self.trace.append({"agent": agent, "status": status,
                           "detail": str(detail)[:200], "ms": int(ms)})


class Agent:
    name = "agent"
    optional = False           # optional agents never fail the pipeline

    def should_run(self, ctx) -> bool:
        return True

    def execute(self, ctx) -> None:
        raise NotImplementedError

    def __call__(self, ctx):
        if not self.should_run(ctx):
            ctx.log(self.name, "skipped")
            return ctx
        t0 = time.time()
        try:
            self.execute(ctx)
            ctx.log(self.name, "ok", "", (time.time() - t0) * 1000)
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            ctx.log(self.name, "failed", msg, (time.time() - t0) * 1000)
            if not self.optional:
                ctx.errors.append(f"{self.name}: {msg}")
        return ctx


class ResearchAgent(Agent):
    """Reads the company's own site so tailoring has real context, not guesses."""
    name = "research"
    optional = True

    def should_run(self, ctx):
        return bool(ctx.job.get("url")) and ctx.job.get("source") not in (
            "remoteok", "arbeitnow", "remotive")

    def execute(self, ctx):
        dom = enrich.domain_from_url(ctx.job["url"])
        if not dom:
            return
        with httpx.Client(follow_redirects=True) as c:
            info = enrich.enrich(c, ctx.job["company"], f"https://{dom}")
        ctx.research = info.get("summary", "")
        if info.get("emails"):
            con = db.connect()
            for e in info["emails"]:
                db.add_contact(con, ctx.job["company"], e, role="Careers inbox")
            con.close()


class TailorAgent(Agent):
    """Retunes the resume to this specific JD. Refuses to invent facts."""
    name = "tailor"

    def execute(self, ctx):
        master = tailor.load_master()
        ctx.tailored = tailor.tailor(ctx.job, master, ctx.research)
        if ctx.tailored.get("_warning"):
            ctx.errors.append(ctx.tailored["_warning"])


class RenderAgent(Agent):
    name = "render"

    def should_run(self, ctx):
        return bool(ctx.tailored)

    def execute(self, ctx):
        master = tailor.load_master()
        ctx.resume_path = str(render.render(master, ctx.tailored, ctx.job))


class OutreachAgent(Agent):
    name = "outreach"
    optional = True

    def should_run(self, ctx):
        return bool(ctx.tailored)

    def execute(self, ctx):
        master = tailor.load_master()
        ctx.email = outreach.draft(ctx.job, master, ctx.tailored, ctx.research)


class FormAgent(Agent):
    """Fills the portal form. Submits only when APPLY_MODE permits."""
    name = "form"
    optional = True

    def should_run(self, ctx):
        from . import apply as apply_mod
        return (os.getenv("ENABLE_FORM_AGENT", "false").lower() == "true"
                and bool(ctx.resume_path)
                and apply_mod.detect_ats(ctx.job.get("apply_url")) is not None)

    def execute(self, ctx):
        from . import apply as apply_mod
        ctx.form = apply_mod.apply_to(ctx.job, ctx.resume_path)


class TrackerAgent(Agent):
    """Persists everything so a rerun resumes rather than repeats."""
    name = "tracker"

    def execute(self, ctx):
        DRAFTS.mkdir(parents=True, exist_ok=True)
        j = ctx.job
        con = db.connect()
        con.execute("""INSERT OR REPLACE INTO applications
                       (job_id,resume_path,tailor_notes,created_at)
                       VALUES (?,?,?,?)""",
                    (j["id"], ctx.resume_path,
                     (ctx.tailored or {}).get("fit_rationale", ""), db.now()))
        status = "applied" if (ctx.form or {}).get("submitted") else "queued"
        con.execute("UPDATE jobs SET status=? WHERE id=?", (status, j["id"]))
        con.execute("""INSERT INTO agent_runs (job_id, trace, errors, created_at)
                       VALUES (?,?,?,?)""",
                    (j["id"], json.dumps(ctx.trace), json.dumps(ctx.errors), db.now()))
        con.commit()
        (DRAFTS / f"{j['id']}.json").write_text(json.dumps({
            "job_id": j["id"], "company": j["company"], "title": j["title"],
            "location": j["location"], "score": j["score"],
            "apply_url": j["apply_url"], "resume": ctx.resume_path,
            "subject": (ctx.email or {}).get("subject", ""),
            "body": (ctx.email or {}).get("body", ""),
            "gaps": (ctx.tailored or {}).get("gaps", []),
            "fit": (ctx.tailored or {}).get("fit_rationale", ""),
            "mode": (ctx.tailored or {}).get("_mode", ""),
            "form": ctx.form, "trace": ctx.trace, "errors": ctx.errors,
            # keep the tailoring itself so the PDF can be re-rendered later
            # without paying for the model again
            "tailored": ctx.tailored,
        }, indent=2))
        con.close()


PIPELINE = [ResearchAgent(), TailorAgent(), RenderAgent(),
            OutreachAgent(), FormAgent(), TrackerAgent()]


class Orchestrator:
    def __init__(self, agents=None, workers=4):
        self.agents = agents or PIPELINE
        self.workers = workers

    def process(self, job):
        ctx = JobContext(job=dict(job))
        for agent in self.agents:
            agent(ctx)
        return ctx

    def run(self, limit=25, workers=None):
        con = db.connect()
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM jobs WHERE status='scored' ORDER BY score DESC LIMIT ?",
            (limit,))]
        con.close()
        results, workers = [], workers or self.workers
        with ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(self.process, j): j for j in rows}
            for f in as_completed(futs):
                try:
                    results.append(f.result())
                except Exception:
                    traceback.print_exc()
        return results


def summarise(results):
    from collections import Counter
    per = Counter()
    for ctx in results:
        for t in ctx.trace:
            per[f"{t['agent']}:{t['status']}"] += 1
    ok = sum(1 for c in results if not c.errors)
    return {"jobs": len(results), "clean": ok,
            "with_errors": len(results) - ok, "agents": dict(per)}
