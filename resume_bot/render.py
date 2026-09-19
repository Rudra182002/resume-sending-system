"""Render a tailored resume to ATS-safe PDF.

Single column, real text, standard fonts, no tables in the content flow -
multi-column and graphical layouts are the usual reason parsers mangle resumes.
"""
import pathlib, re
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                HRFlowable, KeepTogether)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "resumes"

NAME = ParagraphStyle("name", fontName="Helvetica-Bold", fontSize=16, leading=19,
                      spaceAfter=2)
HEAD = ParagraphStyle("head", fontName="Helvetica", fontSize=9, leading=12,
                      textColor=colors.HexColor("#333333"))
SEC = ParagraphStyle("sec", fontName="Helvetica-Bold", fontSize=9.5, leading=12,
                     spaceBefore=7, spaceAfter=2.5,
                     textColor=colors.HexColor("#1a1a1a"))
BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=8.4, leading=10.6,
                      spaceAfter=2)
ROLE = ParagraphStyle("role", fontName="Helvetica-Bold", fontSize=9.2, leading=11.6,
                      spaceBefore=5)
PROJ = ParagraphStyle("proj", fontName="Helvetica-Bold", fontSize=8.8, leading=11,
                      spaceBefore=4, textColor=colors.HexColor("#222222"))
BULLET = ParagraphStyle("bullet", fontName="Helvetica", fontSize=8.3, leading=10.4,
                        leftIndent=10, bulletIndent=2, spaceAfter=1.5)


def _esc(t):
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:48]


def render(master, tailored, job, outdir=None, compact=False):
    outdir = pathlib.Path(outdir or OUT)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"{_slug(job['company'])}__{_slug(job['title'])}__{job['id']}.pdf"

    doc = SimpleDocTemplate(str(path), pagesize=LETTER,
                            leftMargin=0.55 * inch, rightMargin=0.55 * inch,
                            topMargin=0.45 * inch, bottomMargin=0.45 * inch,
                            title=f"{master['name']} - {job['title']}",
                            author=master["name"])
    S = []
    S.append(Paragraph(_esc(master["name"].upper()), NAME))
    S.append(Paragraph(_esc(master["headline"]), HEAD))
    S.append(Paragraph(" | ".join(_esc(x) for x in
             [master["location"], master["phone"], master["email"], master["linkedin"]]), HEAD))
    S.append(Spacer(1, 4))
    S.append(HRFlowable(width="100%", thickness=0.6,
                        color=colors.HexColor("#999999"), spaceAfter=2))

    S.append(Paragraph("PROFESSIONAL SUMMARY", SEC))
    S.append(Paragraph(_esc(tailored.get("summary") or master["summary"]), BODY))

    # Skills, reordered so the groups this JD cares about read first.
    S.append(Paragraph("TECHNICAL SKILLS", SEC))
    order = tailored.get("skills_order") or list(master["skills"].keys())
    for g in order:
        if g in master["skills"]:
            S.append(Paragraph(
                f"<b>{_esc(g)}:</b> {_esc(', '.join(master['skills'][g]))}", BODY))

    # Experience, with projects reordered per relevance.
    S.append(Paragraph("WORK EXPERIENCE", SEC))
    porder = tailored.get("project_order") or []
    rewrites = tailored.get("bullet_rewrites") or {}
    for e in master["experience"]:
        S.append(Paragraph(
            f"{_esc(e['role'])} &nbsp;|&nbsp; {_esc(e['company'])} "
            f"<font color='#555555'>({_esc(e['start'])} - {_esc(e['end'])})</font>", ROLE))
        projs = sorted(e["projects"],
                       key=lambda p: porder.index(p["name"]) if p["name"] in porder else 99)
        for p in projs:
            block = [Paragraph(
                f"{_esc(p['name'])} <font color='#666666' size='7.6'>{_esc(p['tech'])}</font>", PROJ)]
            for b in rewrites.get(p["name"]) or p["bullets"]:
                block.append(Paragraph(_esc(b), BULLET, bulletText="•"))
            S.append(KeepTogether(block))

    if not compact:
        S.append(Paragraph("ACADEMIC PROJECTS", SEC))
    for p in ([] if compact else master["projects"]):
        S.append(Paragraph(
            f"{_esc(p['name'])} <font color='#666666' size='7.6'>{_esc(p['tech'])}</font>", PROJ))
        for b in p["bullets"]:
            S.append(Paragraph(_esc(b), BULLET, bulletText="•"))

    S.append(Paragraph("EDUCATION", SEC))
    for ed in master["education"][:2]:
        S.append(Paragraph(
            f"<b>{_esc(ed['degree'])}</b>, {_esc(ed['institution'])} "
            f"<font color='#555555'>({_esc(ed['year'])}, {_esc(ed['grade'])})</font>", BODY))
    S.append(Paragraph("<b>Achievements:</b> " +
                       _esc(" • ".join(master["achievements"])), BODY))

    doc.build(S)

    # One page is the target. If it spilled, rebuild once without academic projects.
    if not compact:
        from pypdf import PdfReader
        if len(PdfReader(str(path)).pages) > 1:
            return render(master, tailored, job, outdir, compact=True)
    return path
