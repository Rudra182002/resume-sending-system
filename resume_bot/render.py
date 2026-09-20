"""Render a tailored resume to ATS-safe PDF, styled to match the master document.

Design follows Rudrabha_Chakraborty_Resume.pdf: A4, navy accent, centred
letterspaced name, ruled section headers, navy project titles with italic tech
stacks, bolded metrics, a bordered education table, and live mailto/URL links.

Still ATS-safe: single column, real text, standard fonts, no text in tables
except the education grid (which parsers handle fine).
"""
import pathlib, re
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                HRFlowable, KeepTogether, Table, TableStyle)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "resumes"

NAVY = colors.HexColor("#1F3864")
NAVY_MID = colors.HexColor("#2E5496")
RULE = colors.HexColor("#8EA9DB")
GREY = colors.HexColor("#595959")
INK = colors.HexColor("#1A1A1A")

NAME = ParagraphStyle("name", fontName="Helvetica-Bold", fontSize=19, leading=22,
                      textColor=NAVY, alignment=TA_CENTER, spaceAfter=3)
TAG = ParagraphStyle("tag", fontName="Helvetica-Bold", fontSize=9.5, leading=12,
                     textColor=INK, alignment=TA_CENTER, spaceAfter=2)
CONTACT = ParagraphStyle("contact", fontName="Helvetica", fontSize=8.6, leading=11,
                         textColor=INK, alignment=TA_CENTER, spaceAfter=1)
SEC = ParagraphStyle("sec", fontName="Helvetica-Bold", fontSize=9.4, leading=11,
                     textColor=NAVY, spaceBefore=4.2, spaceAfter=1)
BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=8.2, leading=9.8,
                      textColor=INK, alignment=TA_JUSTIFY, spaceAfter=1.5)
ROLE = ParagraphStyle("role", fontName="Helvetica-Bold", fontSize=9.4, leading=11.4,
                      textColor=INK, spaceBefore=3)
PROJ = ParagraphStyle("proj", fontName="Helvetica-Bold", fontSize=8.5, leading=10.1,
                      textColor=NAVY_MID, spaceBefore=2.4, spaceAfter=1)
BULLET = ParagraphStyle("bullet", fontName="Helvetica", fontSize=8.1, leading=9.7,
                        textColor=INK, leftIndent=9, bulletIndent=1,
                        alignment=TA_JUSTIFY, spaceAfter=1.5)

# Numbers carry the evidence, so they get weight - as in the master document.
METRIC = re.compile(
    r"(?<![\w>])("
    r"\d{1,3}(?:\.\d+)?%"            # 95.4%
    r"|\d+\+"                         # 55+
    r"|\d{2,4}\s+live\s+submissions" # 362 live submissions
    r")(?![\w<])")


def _esc(t):
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _bold_metrics(text):
    return METRIC.sub(r"<b>\1</b>", text)


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:48]


def _rule(w=0.9):
    return HRFlowable(width="100%", thickness=w, color=RULE,
                      spaceBefore=0.5, spaceAfter=2.2)


def _spaced(title):
    """Letterspace a heading without welding the words together - a plain
    ' '.join() turned 'PROFESSIONAL SUMMARY' into 'PROFESSIONALSUMMARY'."""
    out = []
    for ch in title.upper():
        out.append("&nbsp;&nbsp;&nbsp;" if ch == " " else _esc(ch))
    return " ".join(out)


def _section(title):
    return [Paragraph(_spaced(title), SEC), _rule()]


MAX_PROJECTS = 2   # a one-page resume leads with the most relevant, not all


def render(master, tailored, job, outdir=None, compact=False):
    outdir = pathlib.Path(outdir or OUT)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"{_slug(job['company'])}__{_slug(job['title'])}__{job['id']}.pdf"

    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=9.5 * mm, bottomMargin=8.5 * mm,
        title=f"{master['name']} - {job['title']}", author=master["name"],
        subject=f"Application for {job['title']} at {job['company']}")
    S = []

    # ---- header ----
    S.append(Paragraph(_esc(master["name"].upper()), NAME))
    S.append(Paragraph(_esc(master["headline"]), TAG))
    li = master["linkedin"]
    li_url = li if li.startswith("http") else "https://" + li
    S.append(Paragraph(
        f'{_esc(master["location"])} &nbsp;|&nbsp; {_esc(master["phone"])} &nbsp;|&nbsp; '
        f'<link href="mailto:{master["email"]}" color="#1155CC">'
        f'<u>{_esc(master["email"])}</u></link> &nbsp;|&nbsp; '
        f'<link href="{li_url}" color="#1155CC"><u>{_esc(li)}</u></link>', CONTACT))
    S.append(Spacer(1, 3))

    # ---- summary ----
    S += _section("Professional Summary")
    S.append(Paragraph(_bold_metrics(_esc(tailored.get("summary") or master["summary"])), BODY))

    # ---- skills ----
    S += _section("Technical Skills")
    order = [g for g in (tailored.get("skills_order") or []) if g in master["skills"]]
    order += [g for g in master["skills"] if g not in order]
    for g in order:
        S.append(Paragraph(
            f'<font color="#1F3864"><b>{_esc(g)}:</b></font> '
            f'{_esc(", ".join(master["skills"][g]))}', BODY))

    # ---- experience ----
    S += _section("Work Experience")
    porder = tailored.get("project_order") or []
    rewrites = tailored.get("bullet_rewrites") or {}
    for e in master["experience"]:
        hdr = Table(
            [[Paragraph(f'{_esc(e["role"])} &nbsp;|&nbsp; '
                        f'<font color="#2E5496">{_esc(e["company"])}</font>', ROLE),
              Paragraph(f'<para align="right"><b>{_esc(e["start"])} to {_esc(e["end"])}</b></para>',
                        ROLE)]],
            colWidths=[118 * mm, 64 * mm])
        hdr.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                 ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                 ("TOPPADDING", (0, 0), (-1, -1), 2),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
        S.append(hdr)
        projs = sorted(e["projects"],
                       key=lambda p: porder.index(p["name"]) if p["name"] in porder else 99)
        for p in projs:
            block = [Paragraph(
                f'{_esc(p["name"])} &nbsp;&nbsp;'
                f'<font color="#595959" size="7.8"><i>{_esc(p["tech"])}</i></font>', PROJ)]
            for b in (rewrites.get(p["name"]) or p["bullets"]):
                block.append(Paragraph(_bold_metrics(_esc(b)), BULLET, bulletText="•"))
            S.append(KeepTogether(block))

    # ---- standalone projects ----
    if True:
        S += _section("Projects")
        # Same treatment as work projects: the tailor may reorder these and
        # rewrite their bullets. They were previously pinned to master text.
        aps = sorted(master["projects"],
                     key=lambda x: porder.index(x["name"]) if x["name"] in porder else 99)
        # Compact keeps the section but shows fewer - losing the whole section
        # was worse than losing the least relevant entry in it.
        aps = aps[:(1 if compact else MAX_PROJECTS)]
        for ap in aps:
            S.append(Paragraph(
                f'{_esc(ap["name"])} &nbsp;&nbsp;'
                f'<font color="#595959" size="7.8"><i>{_esc(ap["tech"])}</i></font>', PROJ))
            for b in (rewrites.get(ap["name"]) or ap["bullets"]):
                S.append(Paragraph(_bold_metrics(_esc(b)), BULLET, bulletText="•"))

    # ---- education table ----
    S += _section("Education")
    head = ["Year", "Degree / Examination", "Institution / Board", "CGPA / Percentage"]
    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=8, leading=10, textColor=INK)
    cellb = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold")
    headc = ParagraphStyle("headc", parent=cell, fontName="Helvetica-Bold",
                           textColor=colors.white)
    data = [[Paragraph(h, headc) for h in head]]
    for ed in master["education"]:
        data.append([Paragraph(_esc(ed["year"]), cell),
                     Paragraph(_esc(ed["degree"]), cellb),
                     Paragraph(_esc(ed["institution"]), cell),
                     Paragraph(_esc(ed["grade"]), cell)])
    t = Table(data, colWidths=[16 * mm, 52 * mm, 80 * mm, 34 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B4C6E7")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]))
    S.append(t)
    S.append(Spacer(1, 3))
    S.append(Paragraph(
        f'<b>Achievements:</b> {_esc("   •   ".join(master["achievements"]))}', BODY))

    doc.build(S)

    if not compact:
        from pypdf import PdfReader
        if len(PdfReader(str(path)).pages) > 1:
            return render(master, tailored, job, outdir, compact=True)
    return path
