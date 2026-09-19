import sys
from . import pipeline, review, ingest, score

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == "run":       pipeline.run(limit=int(arg) if arg else None)
    elif cmd == "ingest":  ingest.run()
    elif cmd == "score":   print(score.run())
    elif cmd == "doctor":
        from . import doctor; doctor.run()
    elif cmd == "review":  review.listing()
    elif cmd == "show":    review.show(int(arg))
    elif cmd == "approve": review.approve(int(arg), sys.argv[3])
    elif cmd == "dash":
        from . import webapp
        print("dashboard -> http://127.0.0.1:8777   (ctrl-c to stop)")
        webapp.serve(port=int(arg) if arg else 8777)
    else:
        print("usage: python -m resume_bot {run [n]|ingest|score|review|show <id>|approve <id> <email>|dash|doctor}")

if __name__ == "__main__":
    main()
