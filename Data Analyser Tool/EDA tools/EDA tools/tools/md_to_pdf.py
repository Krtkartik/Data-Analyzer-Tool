"""Markdown to PDF converter for the project README.

Builds a styled, printable A4 document from ``README.md``: cover page, an
auto-generated table of contents with page numbers, running footer, syntax-free
code blocks, zebra tables and inline formatting.

Dependencies: reportlab only. A TrueType font with wide Unicode coverage is
located at runtime (DejaVu, which ships with matplotlib, is preferred so that
box-drawing, arrows, Greek letters and math operators render correctly).

Usage:
    python tools/md_to_pdf.py                 # README.md -> README.pdf
    python tools/md_to_pdf.py IN.md OUT.pdf   # explicit paths
    python tools/md_to_pdf.py --no-tests      # skip the smoke-test run
"""

from __future__ import annotations

import html
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import List, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parent.parent

INK = colors.HexColor("#1d3557")
ACCENT = colors.HexColor("#2a9df4")
CRIMSON = colors.HexColor("#e63946")
CODE_BG = colors.HexColor("#f5f7fa")
CODE_EDGE = colors.HexColor("#dbe2ea")
CODE_INK = colors.HexColor("#1f2933")
CODE_LINK = colors.HexColor("#0b5394")
TABLE_HEAD_BG = colors.HexColor("#1d3557")
TABLE_GRID = colors.HexColor("#d8dee6")
TABLE_ZEBRA = colors.HexColor("#f4f7fb")
MUTED = colors.HexColor("#5b6770")

PAGE_MARGIN = 16 * mm
BODY_WIDTH = A4[0] - 2 * PAGE_MARGIN

SKIP_SECTIONS = {"table of contents"}


# --------------------------------------------------------------------------- #
# Fonts
# --------------------------------------------------------------------------- #
FONT_SOURCES = {
    "body": ["DejaVuSans.ttf", "arial.ttf", "segoeui.ttf"],
    "body-bold": ["DejaVuSans-Bold.ttf", "arialbd.ttf", "segoeuib.ttf"],
    "body-italic": ["DejaVuSans-Oblique.ttf", "ariali.ttf", "segoeuii.ttf"],
    "body-bolditalic": ["DejaVuSans-BoldOblique.ttf", "arialbi.ttf", "segoeuiz.ttf"],
    "code": ["DejaVuSansMono.ttf", "cour.ttf", "consola.ttf"],
    "code-bold": ["DejaVuSansMono-Bold.ttf", "courbd.ttf", "consolab.ttf"],
    "code-italic": ["DejaVuSansMono-Oblique.ttf", "courio.ttf", "consolai.ttf"],
    "code-bolditalic": ["DejaVuSansMono-BoldOblique.ttf", "courbi.ttf", "consolaz.ttf"],
}


def _font_directories() -> List[Path]:
    directories: List[Path] = []
    try:
        import matplotlib

        directories.append(Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf")
    except Exception:
        pass
    windir = os.environ.get("WINDIR")
    if windir:
        directories.append(Path(windir) / "Fonts")
    directories.append(Path("C:/Windows/Fonts"))
    return [d for d in directories if d.is_dir()]


def register_fonts() -> str:
    """Register the document font families. Returns the code face name."""
    directories = _font_directories()
    resolved: dict = {}
    for key, filenames in FONT_SOURCES.items():
        for directory in directories:
            for filename in filenames:
                candidate = directory / filename
                if candidate.is_file():
                    resolved[key] = str(candidate)
                    break
            if key in resolved:
                break

    if len(resolved) < len(FONT_SOURCES):
        body, code = "Helvetica", "Courier"
        bold, italic, bolditalic = "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"
    else:
        aliases = {
            "body": "MD",
            "body-bold": "MD-Bold",
            "body-italic": "MD-Italic",
            "body-bolditalic": "MD-BoldItalic",
            "code": "MDC",
            "code-bold": "MDC-Bold",
            "code-italic": "MDC-Italic",
            "code-bolditalic": "MDC-BoldItalic",
        }
        for key, alias in aliases.items():
            pdfmetrics.registerFont(TTFont(alias, resolved[key]))
        body, bold, italic, bolditalic = "MD", "MD-Bold", "MD-Italic", "MD-BoldItalic"
        code = "MDC"
        pdfmetrics.registerFontFamily(body, normal=body, bold=bold, italic=italic, boldItalic=bolditalic)
        pdfmetrics.registerFontFamily(
            code,
            normal=code,
            bold="MDC-Bold",
            italic="MDC-Italic",
            boldItalic="MDC-BoldItalic",
        )

    register_fonts.body = body
    register_fonts.bold = bold
    register_fonts.italic = italic
    register_fonts.bolditalic = bolditalic
    register_fonts.code = code
    return code


def _core14(key: str) -> str:
    return {
        "body": "Helvetica",
        "body-bold": "Helvetica-Bold",
        "body-italic": "Helvetica-Oblique",
        "body-bolditalic": "Helvetica-BoldOblique",
        "code": "Courier",
        "code-bold": "Courier-Bold",
        "code-italic": "Courier-Oblique",
        "code-bolditalic": "Courier-BoldOblique",
    }[key]


# --------------------------------------------------------------------------- #
# Styles
# --------------------------------------------------------------------------- #
def build_styles() -> dict:
    body = register_fonts.body
    code = register_fonts.code
    return {
        "cover_title": ParagraphStyle(
            "cover_title", fontName=body, fontSize=23, leading=28, textColor=colors.white, spaceAfter=6
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub", fontName=body, fontSize=10.5, leading=15, textColor=colors.HexColor("#d6e4f0")
        ),
        "cover_meta": ParagraphStyle(
            "cover_meta", fontName=body, fontSize=9, leading=13, textColor=INK
        ),
        "cover_meta_key": ParagraphStyle(
            "cover_meta_key", fontName=register_fonts.bold, fontSize=9, leading=13, textColor=MUTED
        ),
        "h1": ParagraphStyle("H1", fontName=body, fontSize=19, leading=23, textColor=INK, spaceBefore=2, spaceAfter=10),
        "h2": ParagraphStyle(
            "H2", fontName=body, fontSize=14.5, leading=18, textColor=INK, spaceBefore=16, spaceAfter=7
        ),
        "h3": ParagraphStyle(
            "H3", fontName=body, fontSize=11.8, leading=15, textColor=ACCENT, spaceBefore=12, spaceAfter=5
        ),
        "h4": ParagraphStyle(
            "H4", fontName=body, fontSize=10.2, leading=13, textColor=MUTED, spaceBefore=9, spaceAfter=4
        ),
        "body": ParagraphStyle(
            "body", fontName=body, fontSize=9.2, leading=13.4, textColor=colors.HexColor("#1b1b1b"), spaceAfter=7
        ),
        "bullet": ParagraphStyle(
            "bullet", fontName=body, fontSize=9.2, leading=13.2, textColor=colors.HexColor("#1b1b1b"), spaceAfter=3
        ),
        "quote": ParagraphStyle(
            "quote", fontName=register_fonts.italic, fontSize=9, leading=13, leftIndent=10, textColor=MUTED, spaceAfter=7
        ),
        "code": ParagraphStyle(
            "code", fontName=code, fontSize=7.3, leading=9.2, textColor=CODE_INK
        ),
        "cell": ParagraphStyle(
            "cell", fontName=body, fontSize=7.2, leading=9.2, textColor=colors.HexColor("#1b1b1b")
        ),
        "cell_head": ParagraphStyle(
            "cell_head", fontName=register_fonts.bold, fontSize=7.2, leading=9.2, textColor=colors.white
        ),
        "toc_head": ParagraphStyle("toc_head", fontName=body, fontSize=17, leading=21, textColor=INK, spaceAfter=12),
    }


# --------------------------------------------------------------------------- #
# Markdown parsing
# --------------------------------------------------------------------------- #
@dataclass
class Block:
    kind: str
    text: str = ""
    level: int = 0
    rows: List[List[str]] = field(default_factory=list)
    lines: List[str] = field(default_factory=list)
    anchor: str = ""


def slugify(text: str) -> str:
    plain = re.sub(r"[^\w\s-]", "", text.strip().lower())
    return re.sub(r"[\s_]+", "-", plain).strip("-")


def _is_table_separator(line: str) -> bool:
    return bool(re.match(r"^\|[\s:|-]+\|?$", line.strip())) and "-" in line


def split_table_row(line: str) -> List[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    cells: List[str] = []
    buffer: List[str] = []
    escaped = False
    for char in body:
        if escaped:
            buffer.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
            buffer.append(char)
        elif char == "|":
            cells.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(char)
    cells.append("".join(buffer).strip())
    return [cell.replace("\\|", "|") for cell in cells]


def _starts_block(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith("```"):
        return True
    if re.match(r"^#{1,6}\s", stripped):
        return True
    if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
        return True
    if re.match(r"^([-*+])\s+", line) or re.match(r"^(\d+)[.)]\s+", line):
        return True
    if stripped.startswith(">"):
        return True
    if stripped.startswith("|") and _is_table_separator(stripped):
        return True
    return False


def parse_blocks(lines: List[str]) -> List[Block]:
    blocks: List[Block] = []
    index = 0
    total = len(lines)
    while index < total:
        raw = lines[index].rstrip()
        stripped = raw.strip()

        if not stripped:
            index += 1
            continue

        if stripped.startswith("```"):
            index += 1
            buffer: List[str] = []
            while index < total and not lines[index].strip().startswith("```"):
                buffer.append(lines[index].rstrip())
                index += 1
            index += 1
            blocks.append(Block("code", lines=buffer))
            continue

        if stripped.startswith("|") and index + 1 < total and _is_table_separator(lines[index + 1]):
            header = split_table_row(stripped)
            index += 2
            body_rows: List[List[str]] = []
            while index < total and lines[index].strip().startswith("|"):
                body_rows.append(split_table_row(lines[index]))
                index += 1
            blocks.append(Block("table", rows=[header] + body_rows))
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            blocks.append(
                Block(
                    "heading",
                    text=heading.group(2).strip(),
                    level=len(heading.group(1)),
                    anchor=slugify(heading.group(2)),
                )
            )
            index += 1
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            blocks.append(Block("hr"))
            index += 1
            continue

        bullet = re.match(r"^(\s*)([-*+])\s+(.*)$", raw)
        if bullet:
            text = bullet.group(3).strip()
            depth = min(len(bullet.group(1)) // 2, 3)
            index += 1
            while index < total and lines[index].strip() and not _starts_block(lines[index]):
                text += " " + lines[index].strip()
                index += 1
            blocks.append(Block("bullet", text=text, level=depth))
            continue

        numbered = re.match(r"^(\s*)(\d+)[.)]\s+(.*)$", raw)
        if numbered:
            text = numbered.group(3).strip()
            depth = min(len(numbered.group(1)) // 2, 3)
            index += 1
            while index < total and lines[index].strip() and not _starts_block(lines[index]):
                text += " " + lines[index].strip()
                index += 1
            blocks.append(Block("number", text=text, level=depth))
            continue

        if stripped.startswith(">"):
            quoted = [re.sub(r"^>\s?", "", stripped)]
            index += 1
            while index < total and lines[index].strip().startswith(">"):
                quoted.append(re.sub(r"^>\s?", "", lines[index].strip()))
                index += 1
            blocks.append(Block("quote", text=" ".join(quoted)))
            continue

        paragraph = [stripped]
        index += 1
        while index < total and lines[index].strip() and not _starts_block(lines[index]):
            paragraph.append(lines[index].strip())
            index += 1
        blocks.append(Block("para", text=" ".join(paragraph)))

    return blocks


# --------------------------------------------------------------------------- #
# Inline markdown -> reportlab markup
# --------------------------------------------------------------------------- #
INLINE_RE = re.compile(
    r"(?P<code>`+[^`]+`+)"
    r"|(?P<link>\[[^\]]*\]\([^)]*\))"
    r"|(?P<autolink><https?://[^>]+>)"
    r"|(?P<bolditalic>\*\*\*[^*]+\*\*\*)"
    r"|(?P<bold>\*\*[^*]+\*\*)"
    r"|(?P<italic>\*[^*\s][^*]*\*)"
    r"|(?P<strike>~~[^~]+~~)"
)


def render_inline(text: str, nested: bool = False) -> str:
    code_face = register_fonts.code
    pieces: List[str] = []
    cursor = 0
    for match in INLINE_RE.finditer(text):
        pieces.append(html.escape(text[cursor : match.start()], quote=False))
        kind = match.lastgroup
        raw = match.group()
        if kind == "code":
            body = html.escape(raw.strip("`"), quote=False)
            pieces.append(f'<font face="{code_face}" color="{CODE_LINK.hexval()}">{body}</font>')
        elif kind == "link" and not nested:
            label, url = re.match(r"\[([^\]]*)\]\(([^)]*)\)", raw).groups()
            inner = render_inline(label, nested=True)
            pieces.append(f'<link href="{html.escape(url, quote=True)}" color="{CODE_LINK.hexval()}">{inner}</link>')
        elif kind == "autolink":
            url = raw[1:-1]
            pieces.append(f'<link href="{url}" color="{CODE_LINK.hexval()}">{url}</link>')
        elif kind == "bolditalic":
            pieces.append(f"<b><i>{render_inline(raw[3:-3], True)}</i></b>")
        elif kind == "bold":
            pieces.append(f"<b>{render_inline(raw[2:-2], True)}</b>")
        elif kind == "italic":
            pieces.append(f"<i>{render_inline(raw[1:-1], True)}</i>")
        elif kind == "strike":
            pieces.append(f"<strike>{render_inline(raw[2:-2], True)}</strike>")
        else:
            pieces.append(html.escape(raw, quote=False))
        cursor = match.end()
    pieces.append(html.escape(text[cursor:], quote=False))
    return "".join(pieces)


# --------------------------------------------------------------------------- #
# Flowables
# --------------------------------------------------------------------------- #
class Rule(Flowable):
    def __init__(self, color=CRIMSON, thickness=1.1, space=5.0):
        super().__init__()
        self.color = color
        self.thickness = thickness
        self.space = space
        self.width = 0

    def wrap(self, avail_width, avail_height):
        self.width = avail_width
        return (avail_width, self.space + self.thickness)

    def draw(self):
        canvas = self.canv
        canvas.setStrokeColor(self.color)
        canvas.setLineWidth(self.thickness)
        canvas.line(0, self.space / 2, self.width, self.space / 2)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #def _column_widths(rows: List[List[str]], available: float) -> List[float]:
    columns = max(len(row) for row in rows)
    weights = []
    for position in range(columns):
        longest = max((len(row[position]) for row in rows if position < len(row)), default=4)
        weights.append(float(min(max(longest, 6), 62)))
    total = sum(weights)
    widths = [available * weight / total for weight in weights]
    floor = 16 * mm
    for _ in range(3):
        deficit = sum(floor - width for width in widths if width < floor)
        if deficit <= 0:
            break
        donors = [index for index, width in enumerate(widths) if width > floor]
        if not donors:
            break
        pool = sum(widths[index] - floor for index in donors)
        for index in donors:
            widths[index] -= deficit * (widths[index] - floor) / pool
        widths = [max(width, floor) for width in widths]
    scale = available / sum(widths)
    return [width * scale for width in widths]


def render_table(block: Block, styles: dict) -> Table:
    rows = [row + [""] * (max(len(r) for r in block.rows) - len(row)) for row in block.rows]
    widths = _column_widths(rows, BODY_WIDTH)
    data = []
    for position, row in enumerate(rows):
        style = styles["cell_head"] if position == 0 else styles["cell"]
        data.append([Paragraph(render_inline(cell), style) for cell in row])

    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEAD_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, TABLE_GRID),
        ("LINEBEFORE", (0, 0), (-1, -1), 0.4, TABLE_GRID),
        ("BOX", (0, 0), (-1, -1), 0.4, TABLE_GRID),
    ]
    for position in range(1, len(rows)):
        if position % 2 == 0:
            commands.append(("BACKGROUND", (0, position), (-1, position), TABLE_ZEBRA))
    table.setStyle(TableStyle(commands))
    return table


def render_code(block: Block, styles: dict) -> Table:
    text = "\n".join(block.lines) if block.lines else ""
    pre = Preformatted(text, styles["code"], maxLineLength=104)
    table = Table([[pre]], colWidths=[BODY_WIDTH], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
                ("BOX", (0, 0), (-1, -1), 0.5, CODE_EDGE),
                ("LINEBEFORE", (0, 0), (0, -1), 2.4, ACCENT),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


BULLET_GLYPHS = ["\u25cf", "\u25cb", "\u25aa"]
BULLET_INDENT = 12


def render_blocks(blocks: List[Block], styles: dict) -> List[Flowable]:
    story: List[Flowable] = []
    counters = [0, 0, 0, 0]
    for block in blocks:
        if block.kind == "heading":
            if block.text.strip().lower() in SKIP_SECTIONS:
                continue
            level = min(max(block.level - 1, 1), 4)
            anchor = f'<a name="{block.anchor}"/>' if block.anchor else ""
            story.append(Spacer(1, 2 if level > 1 else 0))
            story.append(Paragraph(anchor + render_inline(block.text), styles[f"h{level}"]))
        elif block.kind == "para":
            story.append(Paragraph(render_inline(block.text), styles["body"]))
        elif block.kind == "bullet":
            counters[0] = 0
            glyph = BULLET_GLYPHS[min(block.level, len(BULLET_GLYPHS) - 1)]
            indent = 8 + block.level * BULLET_INDENT
            style = ParagraphStyle(
                f"bullet{block.level}",
                parent=styles["bullet"],
                leftIndent=indent,
                firstLineIndent=-9,
                bulletIndent=indent - 9,
            )
            body = render_inline(block.text)
            story.append(Paragraph(f'<font color="#2a9df4">{glyph}</font>&nbsp;{body}', style))
        elif block.kind == "number":
            counters[block.level] += 1
            for deeper in range(block.level + 1, 4):
                counters[deeper] = 0
            label = ".".join(str(counters[level]) for level in range(block.level + 1))
            indent = 10 + block.level * BULLET_INDENT
            style = ParagraphStyle(
                f"number{block.level}",
                parent=styles["bullet"],
                leftIndent=indent,
                firstLineIndent=-13,
            )
            body = render_inline(block.text)
            story.append(Paragraph(f'<b>{label}</b>&nbsp;{body}', style))
        elif block.kind == "quote":
            story.append(
                Paragraph(
                    f'<font color="#e63946">|</font>&nbsp;{render_inline(block.text)}', styles["quote"]
                )
            )
        elif block.kind == "code":
            story.append(Spacer(1, 3))
            story.append(render_code(block, styles))
            story.append(Spacer(1, 5))
        elif block.kind == "table":
            story.append(Spacer(1, 3))
            story.append(render_table(block, styles))
            story.append(Spacer(1, 6))
        elif block.kind == "hr":
            story.append(Spacer(1, 4))
            story.append(Rule())
            story.append(Spacer(1, 6))
    return story


# --------------------------------------------------------------------------- #
# Document template
# --------------------------------------------------------------------------- #
class ReadmeDoc(BaseDocTemplate):
    def __init__(self, filename: str, styles: dict, title: str, **kwargs):
        super().__init__(
            filename,
            pagesize=A4,
            leftMargin=PAGE_MARGIN,
            rightMargin=PAGE_MARGIN,
            topMargin=17 * mm,
            bottomMargin=16 * mm,
            title=title,
            author="Smart Data Quality Analyzer & Automated EDA Tool",
            subject="Project README",
            **kwargs,
        )
        self.styles = styles
        self.doc_title = title
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="body",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=self._decorate)])

    def _decorate(self, canvas, doc):
        canvas.saveState()
        if doc.page == 1:
            canvas.setFillColor(INK)
            canvas.rect(0, A4[1] - 12 * mm, A4[0], 12 * mm, stroke=0, fill=1)
            canvas.setFillColor(ACCENT)
            canvas.rect(0, A4[1] - 14.6 * mm, A4[0], 2.6 * mm, stroke=0, fill=1)
        else:
            canvas.setFont(register_fonts.body, 7.4)
            canvas.setFillColor(MUTED)
            canvas.drawString(PAGE_MARGIN, A4[1] - 12 * mm, self.doc_title)
            canvas.setStrokeColor(TABLE_GRID)
            canvas.setLineWidth(0.5)
            canvas.line(PAGE_MARGIN, A4[1] - 13.6 * mm, A4[0] - PAGE_MARGIN, A4[1] - 13.6 * mm)
            canvas.line(PAGE_MARGIN, 13.4 * mm, A4[0] - PAGE_MARGIN, 13.4 * mm)
            canvas.drawString(PAGE_MARGIN, 9.6 * mm, "Generated from README.md")
            canvas.drawRightString(A4[0] - PAGE_MARGIN, 9.6 * mm, f"Page {doc.page}")
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph):
            match = re.match(r"^H(\d)$", flowable.style.name)
            if match:
                level = int(match.group(1)) - 1
                self.notify("TOCEntry", (level, flowable.getPlainText(), self.page))


# --------------------------------------------------------------------------- #
# Cover page + contents
# --------------------------------------------------------------------------- #
def cover_story(title: str, subtitle: str, meta_pairs: List[Tuple[str, str]], styles: dict) -> List[Flowable]:
    story: List[Flowable] = [Spacer(1, 42 * mm)]
    story.append(Paragraph(html.escape(title), styles["cover_title"]))
    story.append(Rule(color=ACCENT, thickness=2.2, space=7))
    story.append(Spacer(1, 5))
    story.append(Paragraph(render_inline(subtitle), styles["cover_sub"]))
    story.append(Spacer(1, 26 * mm))

    rows = []
    for key, value in meta_pairs:
        rows.append(
            [
                Paragraph(html.escape(key), styles["cover_meta_key"]),
                Paragraph(render_inline(value), styles["cover_meta"]),
            ]
        )
    table = Table(rows, colWidths=[38 * mm, BODY_WIDTH - 38 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, TABLE_GRID),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 14 * mm))
    story.append(
        Paragraph(
            "Pipeline: Upload &#8594; Profile &#8594; Quality &#8594; Cleaning &#8594; EDA "
            "&#8594; Insights &#8594; Score &#8594; Report",
            styles["cover_meta"],
        )
    )
    return story


def contents_story(styles: dict) -> List[Flowable]:
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(
            "toc0", fontName=register_fonts.bold, fontSize=9.6, leading=17, textColor=INK, leftIndent=0, firstLineIndent=0
        ),
        ParagraphStyle(
            "toc1", fontName=register_fonts.body, fontSize=8.8, leading=14, textColor=MUTED, leftIndent=14
        ),
        ParagraphStyle("toc2", fontName=register_fonts.body, fontSize=8.4, leading=13, textColor=MUTED, leftIndent=28),
    ]
    toc.dotsMinLevel = 0
    return [Paragraph("Contents", styles["toc_head"]), Rule(color=ACCENT, space=6), Spacer(1, 4), toc]


# --------------------------------------------------------------------------- #
# Smoke test runner (for the cover metadata)
# --------------------------------------------------------------------------- #
def run_smoke_tests() -> Tuple[str, str]:
    script = ROOT / "tests" / "test_pipeline.py"
    if not script.is_file():
        return "not found", ""
    try:
        completed = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=600,
        )
    except Exception as exc:  # pragma: no cover
        return f"could not run ({type(exc).__name__})", ""
    match = re.search(r"PASSED:\s*(\d+)\s+FAILED:\s*(\d+)", completed.stdout or "")
    if not match:
        return "no result reported", ""
    passed, failed = int(match.group(1)), int(match.group(2))
    verdict = "all passing" if failed == 0 else f"{failed} failing"
    return f"{passed} checks &mdash; {verdict}", f"python tests/test_pipeline.py"


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def build(source: Path, target: Path, run_tests: bool = True) -> Path:
    text = source.read_text(encoding="utf-8")
    blocks = parse_blocks(text.splitlines())
    styles = build_styles()

    doc_title = next(
        (block.text for block in blocks if block.kind == "heading" and block.level == 1),
        source.stem,
    )
    subtitle = next(
        (
            block.text
            for block in blocks
            if block.kind == "para" and "Version" in block.text
        ),
        "Project documentation",
    )
    version_match = re.search(r"Version\s*([0-9][0-9.]*)", subtitle)
    version = version_match.group(1) if version_match else "1.0.0"
    tests_line, tests_cmd = run_smoke_tests() if run_tests else ("not run", "")

    meta_pairs = [
        ("Application", html.escape(doc_title)),
        ("Version", version),
        ("Source", f"<font face='{register_fonts.code}'>{source.name}</font> &mdash; {len(text.splitlines())} lines, {len(text.split()):,} words"),
        ("Stack", "Python 3 &middot; Streamlit &middot; pandas &middot; NumPy &middot; Plotly &middot; reportlab"),
        ("Modules", "11 pipeline modules, ~3,500 lines, plus a 27-case smoke suite"),
    ]
    if tests_cmd:
        meta_pairs.append(("Smoke tests", f"{tests_line} &mdash; <font face='{register_fonts.code}'>{tests_cmd}</font>"))
    meta_pairs.append(("Generated", date.today().strftime("%d %B %Y")))

    story: List[Flowable] = []
    story += cover_story(doc_title, subtitle, meta_pairs, styles)
    story.append(PageBreak())
    story += contents_story(styles)
    story.append(PageBreak())

    body_blocks = [block for block in blocks if not (block.kind == "heading" and block.level == 1)]
    story += render_blocks(body_blocks, styles)

    document = ReadmeDoc(str(target), styles, f"{doc_title} &mdash; README")
    document.multiBuild(story)
    return target


def main(argv: List[str]) -> int:
    args = [arg for arg in argv if not arg.startswith("--")]
    run_tests = "--no-tests" not in argv
    source = Path(args[0]) if args else ROOT / "README.md"
    target = Path(args[1]) if len(args) > 1 else source.with_suffix(".pdf")
    if not source.is_file():
        print(f"source not found: {source}", file=sys.stderr)
        return 2
    build(source, target, run_tests=run_tests)
    size_kb = target.stat().st_size / 1024
    print(f"wrote {target} ({size_kb:,.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
