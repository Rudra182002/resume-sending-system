"""Print a one-screen run summary for the Actions job summary panel."""
import pathlib, sys

# python scripts/summary.py puts scripts/ on the path, not the repo root
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from resume_bot import db

con = db.connect()


def n(sql):
    return con.execute(sql).fetchone()[0]


status = lambda s: n("SELECT COUNT(*) FROM jobs WHERE status='%s'" % s)

print("## Daily pipeline run\n")
print(f"| metric | count |")
print(f"|---|---|")
print(f"| jobs seen | {n('SELECT COUNT(*) FROM jobs'):,} |")
print(f"| matched | {status('scored'):,} |")
print(f"| queued for you | {status('queued'):,} |")
print(f"| applied | {status('applied'):,} |")
print(f"| companies | {n('SELECT COUNT(DISTINCT company) FROM jobs'):,} |")
print()
print("### Freshest matches\n")
rows = con.execute(
    "SELECT company, title, location FROM jobs WHERE status='queued' "
    "ORDER BY score DESC LIMIT 8").fetchall()
for r in rows:
    print(f"- **{r['company']}** — {r['title']} · {r['location'] or ''}")
con.close()
