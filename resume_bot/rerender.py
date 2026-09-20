"""Re-render every stored resume with the current template.

Uses the tailored content saved in the draft when it is there; otherwise falls
back to the verified master content so the document is still correct, just not
JD-specific. Never calls the model.
"""
import json, pathlib
from . import db, tailor, render

ROOT = pathlib.Path(__file__).resolve().parent.parent
DRAFTS = ROOT / "output" / "drafts"


def run(verbose=True):
    master = tailor.load_master()
    con = db.connect()
    rows = [dict(r) for r in con.execute(
        """SELECT j.* FROM jobs j JOIN applications a ON a.job_id=j.id""")]
    done = fallback = failed = 0
    for job in rows:
        fp = DRAFTS / f"{job['id']}.json"
        t, had = None, False
        if fp.exists():
            try:
                d = json.loads(fp.read_text())
                t = d.get("tailored")
                had = bool(t and t.get("summary"))
            except Exception:
                t = None
        if not had:
            t = {"summary": master["summary"], "skills_order": [],
                 "project_order": [], "bullet_rewrites": {}}
            fallback += 1
        try:
            pdf = render.render(master, t, job)
            con.execute("UPDATE applications SET resume_path=? WHERE job_id=?",
                        (str(pdf), job["id"]))
            if fp.exists():
                d = json.loads(fp.read_text()); d["resume"] = str(pdf)
                fp.write_text(json.dumps(d, indent=2))
            done += 1
        except Exception as e:
            failed += 1
            if verbose:
                print(f"  failed {job['company'][:22]}: {type(e).__name__}: {e}")
    con.commit(); con.close()
    if verbose:
        print(f"re-rendered {done}  (master fallback: {fallback})  failed {failed}")
    return done
