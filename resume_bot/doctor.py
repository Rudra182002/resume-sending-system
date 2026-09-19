"""`python -m resume_bot doctor` - check every integration and say exactly what's missing."""
import os, pathlib, imaplib, smtplib, ssl
import httpx
from dotenv import load_dotenv
from rich.console import Console

console = Console()
ROOT = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OK, WARN, BAD = "[green]OK[/green]", "[yellow]--[/yellow]", "[red]XX[/red]"


def _row(state, name, detail=""):
    console.print(f"  {state}  {name:<26} [dim]{detail}[/dim]")


def check_llm():
    console.print("\n[bold]LLM (resume tailoring)[/bold]")
    k = os.getenv("ANTHROPIC_API_KEY") or ""
    o = os.getenv("OPENAI_API_KEY") or ""
    base = os.getenv("ANTHROPIC_BASE_URL") or os.getenv("ANTHROPIC_API_BASE") or ""
    if not (k or o):
        _row(BAD, "no key set", "console.anthropic.com -> API Keys -> Create Key")
        return
    if k and not k.startswith("sk-ant-"):
        from urllib.parse import urlparse
        host = urlparse(base).netloc if base else "(no base url)"
        _row(WARN, "key is not a console key", f"routes via {host}")
        _row(WARN, "", "a personal sk-ant-... key is the supported setup")
        return
    _row(OK, "key format valid", f"model {os.getenv('LLM_MODEL') or 'claude-sonnet-5'}")


def check_adzuna():
    console.print("\n[bold]Adzuna (India long tail - biggest coverage win)[/bold]")
    i, k = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not (i and k):
        _row(BAD, "not configured", "free: developer.adzuna.com/signup  (~3 min)")
        _row(WARN, "", "then ADZUNA_APP_ID + ADZUNA_APP_KEY in .env")
        return
    try:
        url = (f"https://api.adzuna.com/v1/api/jobs/in/search/1?app_id={i}&app_key={k}"
               "&results_per_page=1&what=ai%20engineer&content-type=application/json")
        r = httpx.get(url, timeout=20)
        if r.status_code == 200:
            _row(OK, "authenticated", f"{r.json().get('count', '?')} India jobs match 'ai engineer'")
        else:
            _row(BAD, f"rejected ({r.status_code})", r.text[:70])
    except Exception as e:
        _row(BAD, "unreachable", type(e).__name__)


def check_simple_key(label, env, signup, probe=None):
    console.print(f"\n[bold]{label}[/bold]")
    v = os.getenv(env)
    if not v:
        _row(BAD, "not configured", signup)
        return
    _row(OK, "key present", "(verified on next ingest)")


def check_imap():
    console.print("\n[bold]IMAP (LinkedIn / Naukri / foundit alert emails)[/bold]")
    host = os.getenv("IMAP_HOST", "imap.gmail.com")
    user, pw = os.getenv("IMAP_USER"), os.getenv("IMAP_PASS")
    if not (user and pw):
        _row(BAD, "not configured", "1. create job alerts on LinkedIn/Naukri/foundit")
        _row(WARN, "", "2. Google Account -> Security -> App passwords")
        _row(WARN, "", "3. IMAP_USER + IMAP_PASS in .env")
        return
    try:
        M = imaplib.IMAP4_SSL(host); M.login(user, pw)
        folder = os.getenv("IMAP_FOLDER", "INBOX")
        typ, _ = M.select(folder)
        found = {}
        from .alerts import SENDERS
        for site, addrs in SENDERS.items():
            n = 0
            for a in addrs:
                t, d = M.search(None, f'(FROM "{a}")')
                if t == "OK" and d[0]:
                    n += len(d[0].split())
            found[site] = n
        M.close(); M.logout()
        _row(OK, "login succeeded", f"folder {folder}")
        for site, n in found.items():
            _row(OK if n else WARN, f"  {site} alerts", f"{n} emails found"
                 if n else "none - create an alert on that site")
    except Exception as e:
        _row(BAD, "login failed", f"{type(e).__name__}: {str(e)[:60]}")
        _row(WARN, "", "Gmail needs an App Password, not your login password")


def check_smtp():
    console.print("\n[bold]SMTP (outreach sending)[/bold]")
    user, pw = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
    frm = os.getenv("FROM_EMAIL")
    if not (user and pw and frm):
        _row(BAD, "not configured", "a dedicated domain is safer than your main inbox")
        return
    try:
        with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"),
                          int(os.getenv("SMTP_PORT", "587")), timeout=20) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(user, pw)
        _row(OK, "login succeeded", f"from {frm}")
    except Exception as e:
        _row(BAD, "login failed", f"{type(e).__name__}: {str(e)[:60]}")
    _row(OK if os.getenv("AUTO_SEND", "false").lower() == "true" else WARN,
         "AUTO_SEND", os.getenv("AUTO_SEND", "false") + "  (cap "
         + os.getenv("MAX_EMAILS_PER_DAY", "20") + "/day)")


def run():
    console.rule("[bold]resume_bot doctor")
    if not (ROOT / ".env").exists():
        console.print("[red]no .env file[/red] - run: cp .env.example .env")
    check_llm()
    check_adzuna()
    check_simple_key("Jooble", "JOOBLE_API_KEY", "free key: jooble.org/api/about")
    check_simple_key("Careerjet", "CAREERJET_AFFID", "free affid: careerjet.com/partners/api")
    check_imap()
    check_smtp()
    console.rule()
