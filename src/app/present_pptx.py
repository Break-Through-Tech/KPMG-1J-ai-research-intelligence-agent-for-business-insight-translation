# Turns a saved presentation (src/app/present.py) into a PowerPoint file: a title slide,
# one slide per outline slide with its speaker notes and likely questions in the notes
# pane (so they show in Presenter View), and a presenter-only "Watch out for" slide.
# Built from the saved deck, edits included; no LLM call.
#
# It's a clean, editable starting point in KPMG blue, not a designed deck.

from datetime import datetime, timezone
from io import BytesIO

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

from src.translation.present_prompts import AUDIENCE_LABELS

KPMG_BLUE = RGBColor(0x00, 0x33, 0x8D)
INK = RGBColor(0x1F, 0x23, 0x2B)
MUTED = RGBColor(0x5F, 0x66, 0x73)
WARN = RGBColor(0x8A, 0x4B, 0x08)
FONT = "Arial"

WIDTH, HEIGHT = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.7)

FOOTER = "Draft, generated from a research brief. Check before presenting."
DRAFT_LINE = "DRAFT: the research brief behind these slides hasn't been approved. Not for client use."


def _text(frame, text, size, color=INK, bold=False):
    frame.word_wrap = True
    para = frame.paragraphs[0]
    para.text = ""
    run = para.add_run()
    run.text = text
    run.font.name, run.font.size, run.font.bold = FONT, Pt(size), bold
    run.font.color.rgb = color
    return para


def _box(slide, left, top, width, height, text, size, **style):
    box = slide.shapes.add_textbox(left, top, width, height)
    _text(box.text_frame, text, size, **style)
    return box


def _bullet(para, indent=Emu(Inches(0.3))):
    """A real bulleted paragraph (a • with a hanging indent), not a typed character."""
    p_pr = para._p.get_or_add_pPr()
    p_pr.set("marL", str(int(indent)))
    p_pr.set("indent", str(-int(indent)))
    for tag in ("a:buNone", "a:buChar", "a:buAutoNum"):
        for old in p_pr.findall(qn(tag)):
            p_pr.remove(old)
    char = p_pr.makeelement(qn("a:buChar"), {"char": "•"})
    p_pr.append(char)


def _frame(slide, number=None):
    """The accent bar and footer every content slide has."""
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, WIDTH, Inches(0.12))
    bar.fill.solid()
    bar.fill.fore_color.rgb = KPMG_BLUE
    bar.line.fill.background()
    _box(slide, MARGIN, HEIGHT - Inches(0.55), Inches(10), Inches(0.35), FOOTER, 10, color=MUTED)
    if number is not None:
        _box(slide, WIDTH - MARGIN - Inches(0.8), HEIGHT - Inches(0.55), Inches(0.8), Inches(0.35),
             str(number), 10, color=MUTED)


def _content_slide(prs, title, bullets, number, kicker=""):
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    _frame(slide, number)
    top = Inches(0.55)
    if kicker and kicker.strip().lower() != (title or "").strip().lower():
        _box(slide, MARGIN, top, Inches(11), Inches(0.35), kicker.upper(), 12, color=KPMG_BLUE, bold=True)
        top += Inches(0.4)
    _box(slide, MARGIN, top, WIDTH - 2 * MARGIN, Inches(1.0), title or "Untitled slide", 30,
         color=KPMG_BLUE, bold=True)

    body = slide.shapes.add_textbox(MARGIN, top + Inches(1.25), WIDTH - 2 * MARGIN, HEIGHT - top - Inches(2.2))
    frame = body.text_frame
    frame.word_wrap = True
    for i, line in enumerate(bullets):
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        run = para.add_run()
        run.text = line
        run.font.name, run.font.size = FONT, Pt(20)
        run.font.color.rgb = INK
        para.space_after = Pt(10)
        _bullet(para)
    return slide


def _notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


def slide_notes(slide):
    """What the presenter sees in Presenter View for one outline slide."""
    parts = []
    if slide.get("notes"):
        parts.append(slide["notes"].strip())
    if slide.get("minutes"):
        parts.append(f"Planned time: {slide['minutes']} min")
    questions = slide.get("questions") or []
    if questions:
        parts.append("They might ask:")
        for q in questions:
            parts.append(f"Q: {q.get('question', '')}\nA: {q.get('answer') or '(no suggested answer)'}")
    return "\n\n".join(parts)


def build_pptx(deck, query, brief_status, today=None):
    """The deck as .pptx bytes. brief_status is the brief's current review status."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = WIDTH, HEIGHT

    # title slide
    title = prs.slides.add_slide(prs.slide_layouts[6])
    _frame(title)
    _box(title, MARGIN, Inches(2.0), WIDTH - 2 * MARGIN, Inches(2.0), query, 36, color=KPMG_BLUE, bold=True)
    audience = AUDIENCE_LABELS.get(deck.get("audience"), deck.get("audience", ""))
    day = today or datetime.now(timezone.utc).date()
    when = f"{day:%B} {day.day}, {day.year}"
    _box(title, MARGIN, Inches(4.2), Inches(11), Inches(0.5),
         f"{audience} · {deck.get('minutes', '')} minutes · {when}", 18, color=MUTED)
    if brief_status != "approved":
        _box(title, MARGIN, Inches(5.0), WIDTH - 2 * MARGIN, Inches(0.6), DRAFT_LINE, 16, color=WARN, bold=True)

    for number, item in enumerate(deck.get("slides", []), start=1):
        slide = _content_slide(prs, item.get("title", ""), item.get("bullets", []), number,
                               kicker=item.get("section", ""))
        _notes(slide, slide_notes(item))

    watch_outs = deck.get("watch_outs") or []
    if watch_outs:
        slide = _content_slide(prs, "Watch out for", watch_outs, None, kicker="Presenter only")
        _notes(slide, "Presenter only: delete this slide before sharing the deck.")

    out = BytesIO()
    prs.save(out)
    return out.getvalue()
