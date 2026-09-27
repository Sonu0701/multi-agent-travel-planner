"""Generate a polished PDF version of the final travel plan, with an embedded
cost-breakdown chart parsed from the budget agent's output.

Two things this file specifically works around:
  1. ReportLab's default font (Helvetica) only covers Latin-1, so ₹, en-dashes,
     bullets, ≈/≤ and most emoji render as empty boxes. We register DejaVu
     Sans instead — it ships inside the `matplotlib` package already, so no
     extra font files need to live in the project.
  2. LLM-written itineraries are full of markdown tables. Left as plain text
     those collapse into unreadable squished pipe-separated lines, so we
     detect and render them as real ReportLab Table flowables.
"""

import io
import os
import re
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # headless backend — required inside Streamlit's server process
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image as RLImage,
    ListFlowable,
    ListItem,
    HRFlowable,
    Table,
    TableStyle,
)

from budget_utils import parse_budget_breakdown, _split_row, _is_separator_row

PRIMARY_COLOR = colors.HexColor("#6366f1")
CHART_COLORS = ["#6366f1", "#8b5cf6", "#ec4899", "#f59e0b", "#10b981", "#3b82f6", "#ef4444"]

# ---------------------------------------------------------------------------
# Unicode font registration (DejaVu Sans, bundled with matplotlib)
# ---------------------------------------------------------------------------

_FONT_DIR = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
_FONT_FILES = {
    "UniSans": "DejaVuSans.ttf",
    "UniSans-Bold": "DejaVuSans-Bold.ttf",
    "UniSans-Italic": "DejaVuSans-Oblique.ttf",
    "UniSans-BoldItalic": "DejaVuSans-BoldOblique.ttf",
}

_fonts_registered = False
_supported_codepoints = None


def _ensure_fonts_registered():
    """Register the Unicode font with ReportLab and cache which codepoints it
    actually has glyphs for, so we can strip anything unsupported (rare color
    emoji, mostly) instead of letting it render as a tofu box."""
    global _fonts_registered, _supported_codepoints
    if _fonts_registered:
        return

    for name, filename in _FONT_FILES.items():
        pdfmetrics.registerFont(TTFont(name, os.path.join(_FONT_DIR, filename)))
    pdfmetrics.registerFontFamily(
        "UniSans",
        normal="UniSans",
        bold="UniSans-Bold",
        italic="UniSans-Italic",
        boldItalic="UniSans-BoldItalic",
    )

    from fontTools.ttLib import TTFont as FTFont
    ft = FTFont(os.path.join(_FONT_DIR, _FONT_FILES["UniSans"]))
    _supported_codepoints = set(ft.getBestCmap().keys())
    _fonts_registered = True


def _sanitize_unicode(text: str) -> str:
    """Drop characters the embedded font has no glyph for. DejaVu Sans covers
    ₹, en/em-dashes, bullets, ≈, ≤, × and most dingbats (including ✈) — this
    only strips the rarer multi-codepoint color emoji that would otherwise
    show up as empty boxes."""
    _ensure_fonts_registered()
    return "".join(ch for ch in text if ch in "\n\t" or ord(ch) in _supported_codepoints)


def _escape(text: str) -> str:
    """Sanitize unsupported unicode, escape ReportLab's mini-XML special
    characters, then translate simple **bold** / *italic* markdown."""
    text = _sanitize_unicode(text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    return text


def _build_styles():
    styles = getSampleStyleSheet()
    for name in ("Normal", "BodyText", "Title", "Heading1", "Heading2", "Heading3", "Italic"):
        if name in styles.byName:
            styles[name].fontName = "UniSans"
    for name in ("Title", "Heading1", "Heading2", "Heading3"):
        styles[name].fontName = "UniSans-Bold"
    styles.add(ParagraphStyle(name="MetaLine", fontName="UniSans", fontSize=9, textColor=colors.grey, spaceAfter=2))
    styles.add(ParagraphStyle(name="TableHeader", fontName="UniSans-Bold", fontSize=8, textColor=colors.white, leading=10))
    styles.add(ParagraphStyle(name="TableCell", fontName="UniSans", fontSize=8, leading=10))
    return styles


# ---------------------------------------------------------------------------
# Cost breakdown chart
# ---------------------------------------------------------------------------


def build_cost_chart_image(breakdown: dict):
    """Render a pie chart of the cost breakdown to an in-memory PNG buffer.
    Returns None if there's nothing to chart. Shared by the PDF export and
    the on-screen Streamlit chart so both stay visually consistent.
    """
    if not breakdown:
        return None

    labels = list(breakdown.keys())
    values = list(breakdown.values())

    fig, ax = plt.subplots(figsize=(4.5, 4.5))
    ax.pie(
        values,
        labels=labels,
        autopct="%1.0f%%",
        colors=[CHART_COLORS[i % len(CHART_COLORS)] for i in range(len(labels))],
        textprops={"fontsize": 9},
    )
    ax.set_title("Estimated Cost Breakdown", fontsize=12, fontweight="bold")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, transparent=True)
    plt.close(fig)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Markdown-lite -> ReportLab flowables (headings, bullets, real tables)
# ---------------------------------------------------------------------------


def _is_table_line(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2


def _build_table_flowable(rows: list, styles, avail_width) -> Table:
    header, *body = rows
    n_cols = len(header)
    col_width = avail_width / n_cols

    def cell(text, header=False):
        style = styles["TableHeader"] if header else styles["TableCell"]
        return Paragraph(_escape(text), style)

    data = [[cell(h, header=True) for h in header]]
    for row in body:
        row = (row + [""] * n_cols)[:n_cols]  # defensively pad ragged rows
        data.append([cell(c) for c in row])

    table = Table(data, colWidths=[col_width] * n_cols, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), PRIMARY_COLOR),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _markdown_lite_to_flowables(text: str, styles, avail_width) -> list:
    """Small markdown-ish renderer: headings (#), bullets (-/*), horizontal
    rules (---), real tables (| a | b |), and plain paragraphs otherwise.
    Not a full markdown parser — good enough for LLM-generated plan text.
    """
    flowables = []
    bullet_buffer = []
    lines = (text or "").splitlines()
    i = 0

    def flush_bullets():
        if bullet_buffer:
            items = [ListItem(Paragraph(b, styles["Normal"])) for b in bullet_buffer]
            flowables.append(ListFlowable(items, bulletType="bullet", leftIndent=16))
            bullet_buffer.clear()

    while i < len(lines):
        line = lines[i].strip()

        if not line:
            flush_bullets()
            flowables.append(Spacer(1, 6))
            i += 1
            continue

        if _is_table_line(line):
            flush_bullets()
            table_lines = []
            while i < len(lines) and _is_table_line(lines[i].strip()):
                table_lines.append(lines[i].strip())
                i += 1
            rows = [_split_row(l) for l in table_lines]
            rows = [r for r in rows if not _is_separator_row(r)]
            if len(rows) >= 2:
                flowables.append(_build_table_flowable(rows, styles, avail_width))
                flowables.append(Spacer(1, 10))
            else:
                for r in rows:
                    flowables.append(Paragraph(_escape(" | ".join(r)), styles["Normal"]))
            continue

        if line == "---":
            flush_bullets()
            flowables.append(Spacer(1, 4))
            flowables.append(HRFlowable(width="100%", color=colors.HexColor("#e5e7eb")))
            flowables.append(Spacer(1, 8))
            i += 1
            continue

        if line.startswith("### "):
            flush_bullets()
            flowables.append(Paragraph(_escape(line[4:]), styles["Heading3"]))
        elif line.startswith("## "):
            flush_bullets()
            flowables.append(Paragraph(_escape(line[3:]), styles["Heading2"]))
        elif line.startswith("# "):
            flush_bullets()
            flowables.append(Paragraph(_escape(line[2:]), styles["Heading1"]))
        elif line.startswith(("- ", "* ")):
            bullet_buffer.append(_escape(line[2:]))
        else:
            flush_bullets()
            flowables.append(Paragraph(_escape(line), styles["Normal"]))
        i += 1

    flush_bullets()
    return flowables


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_pdf(
    user_query: str,
    final_response: str,
    budget_results: str = "",
    selected_agents=None,
) -> bytes:
    """Build the full travel plan PDF and return it as bytes, ready for st.download_button."""
    _ensure_fonts_registered()
    selected_agents = selected_agents or []

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )

    styles = _build_styles()
    story = []

    # --- Header ---
    story.append(Paragraph("Your Travel Plan", styles["Title"]))
    if user_query:
        story.append(Paragraph(f"<i>{_escape(user_query)}</i>", styles["Normal"]))
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            f"Generated {datetime.now().strftime('%d %b %Y, %I:%M %p')}"
            + (f" &middot; Agents used: {_escape(', '.join(selected_agents))}" if selected_agents else ""),
            styles["MetaLine"],
        )
    )
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", color=PRIMARY_COLOR, thickness=2))
    story.append(Spacer(1, 14))

    # --- Cost breakdown chart (only if the budget text was parseable) ---
    breakdown = parse_budget_breakdown(budget_results)
    chart_buf = build_cost_chart_image(breakdown)
    if chart_buf:
        story.append(Paragraph("Cost Breakdown", styles["Heading2"]))
        story.append(RLImage(chart_buf, width=3.2 * inch, height=3.2 * inch))
        story.append(Spacer(1, 16))

    # --- Main itinerary / final plan ---
    story.append(Paragraph("Itinerary", styles["Heading2"]))
    story.extend(_markdown_lite_to_flowables(final_response, styles, doc.width))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()