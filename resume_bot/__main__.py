import sys
from . import pipeline, review, ingest, score


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    arg = sys.argv[2] if len(sys.argv) > 2 else None

    if cmd == "run":
        pipeline.run(limit=int(arg) if arg else None)
    elif cmd == "ingest":
        ingest.run()
    elif cmd == "score":
        print(score.run(rescore_queued=(arg == "all")))
    elif cmd == "review":
        review.listing()
    elif cmd == "show":
        review.show(int(arg))
    elif cmd == "approve":
        review.approve(int(arg), sys.argv[3])
    elif cmd == "dash":
        from . import webapp
        port = int(arg) if arg else 8777
        print(f"dashboard -> http://127.0.0.1:{port}   (ctrl-c to stop)")
        webapp.serve(port=port)
    elif cmd == "doctor":
        from . import doctor
        doctor.run()
    elif cmd == "harvest":
        # local alias: a bare `score` import here would shadow the module-level
        # one for the whole function and break every other branch.
        from . import alerts, db
        import collections
        al = alerts.fetch(days=int(arg) if arg else 400, limit=40, verbose=True)
        print(f"extracted {len(al)}", dict(collections.Counter(j["source"] for j in al)))
        if al:
            con = db.connect()
            print("matched to ATS rows:", alerts.backfill_jd(con, al))
            db.upsert_jobs(con, al)
            print("scoring:", score.run())
    elif cmd == "apply":
        from . import apply as apply_mod
        apply_mod.run(limit=int(arg) if arg else 10)
    elif cmd == "agents":
        from . import agents
        o = agents.Orchestrator(workers=int(sys.argv[3]) if len(sys.argv) > 3 else 4)
        res = o.run(limit=int(arg) if arg else 25)
        import json
        print(json.dumps(agents.summarise(res), indent=2))
    elif cmd == "prune":
        from . import prune
        prune.run()
    elif cmd == "rerender":
        from . import rerender
        rerender.run()
    else:
        print("usage: python -m resume_bot {run [n]|ingest|score [all]|review|"
              "show <id>|approve <id> <email>|dash [port]|doctor|harvest [days]|"
              "apply [n]|agents [n] [workers]|rerender|prune}")


if __name__ == "__main__":
    main()
