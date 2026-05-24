#!/usr/bin/env python3
"""Convert project markdown reports to PDF using fpdf2 native API.

Parses markdown directly (no HTML intermediary) to avoid fpdf2's
write_html() limitations with complex table structures.

Usage:
    python scripts/md2pdf.py                    # both reports
    python scripts/md2pdf.py docs/week3-report.md  # single file
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# ---------------------------------------------------------------------------
# Font setup
# ---------------------------------------------------------------------------
ARIAL_UNICODE = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
USE_UNICODE_FONT = os.path.exists(ARIAL_UNICODE)


class ReportPDF(FPDF):
    """Custom PDF with header/footer and markdown rendering helpers."""

    def __init__(self, title: str = ""):
        super().__init__()
        self.doc_title = title
        self.set_auto_page_break(auto=True, margin=20)

        if USE_UNICODE_FONT:
            self.add_font("ArialUni", "", ARIAL_UNICODE)
            self.add_font("ArialUni", "B", ARIAL_UNICODE)
            self.add_font("ArialUni", "I", ARIAL_UNICODE)
            self._font_family = "ArialUni"
        else:
            self._font_family = "Helvetica"

    # -- header / footer ---------------------------------------------------

    def header(self):
        self.set_font(self._font_family, "B", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, self.doc_title, align="L")
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font(self._font_family, "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    # -- primitives --------------------------------------------------------

    def _set_body(self, size: int = 10):
        self.set_font(self._font_family, "", size)
        self.set_text_color(0, 0, 0)

    def _set_bold(self, size: int = 10):
        self.set_font(self._font_family, "B", size)
        self.set_text_color(0, 0, 0)

    def _set_italic(self, size: int = 10):
        self.set_font(self._font_family, "I", size)
        self.set_text_color(0, 0, 0)

    def _set_code(self, size: int = 9):
        if USE_UNICODE_FONT:
            self.set_font(self._font_family, "", size)
        else:
            self.set_font("Courier", "", size)
        self.set_text_color(0, 0, 0)

    def _write_rich_text(self, text: str, size: int = 10):
        """Write text with inline **bold** and *italic* and `code` spans."""
        # Split on bold, italic, and code markers
        # Process inline formatting tokens
        parts = re.split(r'(\*\*.*?\*\*|\*.*?\*|`[^`]+`)', text)
        for part in parts:
            if part.startswith("**") and part.endswith("**"):
                self._set_bold(size)
                self.write(5, part[2:-2])
            elif part.startswith("*") and part.endswith("*"):
                self._set_italic(size)
                self.write(5, part[1:-1])
            elif part.startswith("`") and part.endswith("`"):
                self._set_code(size - 1)
                self.write(5, part[1:-1])
            else:
                self._set_body(size)
                self.write(5, part)
        self._set_body(size)

    # -- block-level renderers ---------------------------------------------

    def add_heading(self, level: int, text: str):
        sizes = {1: 18, 2: 14, 3: 12}
        sz = sizes.get(level, 11)
        if level <= 2:
            self.ln(4)
        self._set_bold(sz)
        # Strip inline markers for headings
        clean = re.sub(r'[*`]', '', text)
        self.multi_cell(0, sz * 0.6, clean)
        if level == 1:
            # underline
            self.set_draw_color(0, 0, 0)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.ln(3)
        self.ln(3)

    def add_paragraph(self, text: str):
        self._write_rich_text(text, 10)
        self.ln(7)

    def add_hr(self):
        y = self.get_y()
        self.set_draw_color(180, 180, 180)
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.ln(5)

    def add_code_block(self, lines: list[str]):
        self.set_fill_color(245, 245, 245)
        self._set_code(8)
        x0 = self.l_margin
        w = self.w - self.l_margin - self.r_margin
        for line in lines:
            # Truncate very long lines
            if len(line) > 100:
                line = line[:97] + "..."
            self.set_x(x0)
            self.cell(w, 4.5, "  " + line, fill=True)
            self.ln(4.5)
        self._set_body()
        self.ln(3)

    def add_bullet(self, text: str, indent: int = 0):
        x0 = self.l_margin + indent * 5
        self.set_x(x0)
        self._set_body(10)
        self.write(5, "  \u2022  ")
        self._write_rich_text(text, 10)
        self.ln(6)

    def add_numbered_item(self, num: str, text: str):
        self._set_body(10)
        self.write(5, f"  {num} ")
        self._write_rich_text(text, 10)
        self.ln(6)

    def add_blockquote(self, text: str):
        self.set_fill_color(240, 240, 240)
        self.set_x(self.l_margin + 5)
        self._set_italic(10)
        w = self.w - self.l_margin - self.r_margin - 10
        self.multi_cell(w, 5, text, fill=True)
        self._set_body()
        self.ln(3)

    def add_table(self, headers: list[str], rows: list[list[str]], alignments: list[str] | None = None):
        """Render a markdown table with auto-sized columns."""
        if not headers:
            return

        n_cols = len(headers)
        usable_w = self.w - self.l_margin - self.r_margin

        # Clean inline markdown from cells
        def clean_cell(c: str) -> str:
            c = re.sub(r'\*\*(.*?)\*\*', r'\1', c)
            c = re.sub(r'\*(.*?)\*', r'\1', c)
            c = re.sub(r'`([^`]*)`', r'\1', c)
            c = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', c)  # links
            return c.strip()

        clean_headers = [clean_cell(h) for h in headers]
        clean_rows = [[clean_cell(c) for c in row] for row in rows]

        # Estimate column widths based on content
        col_widths = []
        for i in range(n_cols):
            max_len = len(clean_headers[i])
            for row in clean_rows:
                if i < len(row):
                    max_len = max(max_len, len(row[i]))
            col_widths.append(max_len)

        # Scale to fit page
        total_chars = sum(col_widths) or 1
        col_ws = [(cw / total_chars) * usable_w for cw in col_widths]

        # Ensure minimum width
        min_w = 12
        for i in range(n_cols):
            if col_ws[i] < min_w:
                col_ws[i] = min_w

        # Re-scale if total exceeds usable width
        total_w = sum(col_ws)
        if total_w > usable_w:
            factor = usable_w / total_w
            col_ws = [w * factor for w in col_ws]

        row_h = 6

        # Determine alignment per column
        aligns = []
        if alignments:
            for a in alignments:
                if ":" in a and a.endswith(":"):
                    aligns.append("C")
                elif a.endswith(":"):
                    aligns.append("R")
                else:
                    aligns.append("L")
        else:
            aligns = ["L"] * n_cols

        # Pad aligns to match columns
        while len(aligns) < n_cols:
            aligns.append("L")

        # Header
        self.set_fill_color(70, 130, 180)
        self._set_bold(8)
        self.set_text_color(255, 255, 255)
        for i, h in enumerate(clean_headers):
            self.cell(col_ws[i], row_h, h[:40], border=1, fill=True, align=aligns[i])
        self.ln(row_h)

        # Rows
        self._set_body(8)
        self.set_text_color(0, 0, 0)
        fill = False
        for row in clean_rows:
            if self.get_y() + row_h > self.h - self.b_margin:
                self.add_page()
                # Re-draw header on new page
                self.set_fill_color(70, 130, 180)
                self._set_bold(8)
                self.set_text_color(255, 255, 255)
                for i, h in enumerate(clean_headers):
                    self.cell(col_ws[i], row_h, h[:40], border=1, fill=True, align=aligns[i])
                self.ln(row_h)
                self._set_body(8)
                self.set_text_color(0, 0, 0)
                fill = False

            if fill:
                self.set_fill_color(245, 245, 250)
            else:
                self.set_fill_color(255, 255, 255)

            for i in range(n_cols):
                val = row[i] if i < len(row) else ""
                self.cell(col_ws[i], row_h, val[:50], border=1, fill=True, align=aligns[i])
            self.ln(row_h)
            fill = not fill

        self.ln(4)

    def add_image_if_exists(self, img_ref: str, base_dir: Path):
        """Try to embed a PNG/JPG image referenced in markdown."""
        # Extract filename from ![alt](filename)
        img_path = base_dir / img_ref
        if img_path.exists() and img_path.suffix.lower() in (".png", ".jpg", ".jpeg"):
            usable_w = self.w - self.l_margin - self.r_margin
            try:
                # Check if enough space, else new page
                if self.get_y() + 80 > self.h - self.b_margin:
                    self.add_page()
                self.image(str(img_path), x=self.l_margin, w=min(usable_w, 170))
                self.ln(5)
            except Exception:
                self._set_italic(8)
                self.write(5, f"[Image: {img_ref}]")
                self.ln(5)
        else:
            self._set_italic(8)
            self.set_text_color(100, 100, 100)
            self.write(5, f"[Image: {img_ref}]")
            self.set_text_color(0, 0, 0)
            self._set_body()
            self.ln(5)


# ---------------------------------------------------------------------------
# Markdown parser (line-oriented, good enough for these reports)
# ---------------------------------------------------------------------------

def parse_and_render(pdf: ReportPDF, md_text: str, base_dir: Path):
    """Parse markdown text and render into the PDF."""
    lines = md_text.split("\n")
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # Blank line
        if not line.strip():
            i += 1
            continue

        # Horizontal rule
        if re.match(r'^-{3,}$', line.strip()) or re.match(r'^\*{3,}$', line.strip()):
            pdf.add_hr()
            i += 1
            continue

        # Heading
        m = re.match(r'^(#{1,4})\s+(.*)', line)
        if m:
            level = len(m.group(1))
            pdf.add_heading(level, m.group(2))
            i += 1
            continue

        # Code block (fenced)
        if line.strip().startswith("```"):
            code_lines = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            pdf.add_code_block(code_lines)
            continue

        # Table detection: line with |
        if "|" in line and i + 1 < n and re.match(r'^[\s|:\-]+$', lines[i + 1]):
            # Parse header
            header_cells = [c.strip() for c in line.split("|")]
            header_cells = [c for c in header_cells if c]  # remove empty from leading/trailing |

            # Parse alignment row
            align_row = lines[i + 1]
            align_cells = [c.strip() for c in align_row.split("|")]
            align_cells = [c for c in align_cells if c.strip("-: ")]

            # Parse data rows
            data_rows = []
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                cells = [c.strip() for c in lines[i].split("|")]
                cells = [c for c in cells if c or cells.index(c) not in (0, len(cells)-1)]
                # Better: split by | and trim first/last if empty
                raw = lines[i].split("|")
                if raw and not raw[0].strip():
                    raw = raw[1:]
                if raw and not raw[-1].strip():
                    raw = raw[:-1]
                cells = [c.strip() for c in raw]
                data_rows.append(cells)
                i += 1

            pdf.add_table(header_cells, data_rows, align_cells if align_cells else None)
            continue

        # Image
        img_m = re.match(r'!\[([^\]]*)\]\(([^)]+)\)', line.strip())
        if img_m:
            pdf.add_image_if_exists(img_m.group(2), base_dir)
            i += 1
            continue

        # Blockquote
        if line.strip().startswith(">"):
            quote_text = line.strip().lstrip("> ").strip()
            i += 1
            while i < n and lines[i].strip().startswith(">"):
                quote_text += " " + lines[i].strip().lstrip("> ").strip()
                i += 1
            pdf.add_blockquote(quote_text)
            continue

        # Unordered list
        list_m = re.match(r'^(\s*)[-*]\s+(.*)', line)
        if list_m:
            indent = len(list_m.group(1)) // 2
            pdf.add_bullet(list_m.group(2), indent)
            i += 1
            continue

        # Ordered list
        ol_m = re.match(r'^(\d+)\.\s+(.*)', line)
        if ol_m:
            pdf.add_numbered_item(ol_m.group(1) + ".", ol_m.group(2))
            i += 1
            continue

        # Regular paragraph — accumulate consecutive non-blank non-special lines
        para_lines = [line.strip()]
        i += 1
        while i < n:
            nl = lines[i]
            if not nl.strip():
                break
            if re.match(r'^#{1,4}\s', nl):
                break
            if nl.strip().startswith("```"):
                break
            if nl.strip().startswith("|") and i + 1 < n and re.match(r'^[\s|:\-]+$', lines[i + 1]):
                break
            if re.match(r'^-{3,}$', nl.strip()):
                break
            if re.match(r'^[-*]\s+', nl.strip()):
                break
            if re.match(r'^\d+\.\s+', nl):
                break
            if re.match(r'^>\s', nl):
                break
            if re.match(r'!\[', nl.strip()):
                break
            para_lines.append(nl.strip())
            i += 1

        pdf.add_paragraph(" ".join(para_lines))

    return pdf


def convert_md_to_pdf(md_path: Path, pdf_path: Path):
    """Convert a single markdown file to PDF."""
    text = md_path.read_text(encoding="utf-8")
    base_dir = md_path.parent

    # Extract title from first H1
    title_m = re.search(r'^#\s+(.*)', text, re.MULTILINE)
    title = title_m.group(1) if title_m else md_path.stem

    pdf = ReportPDF(title=title)
    pdf.alias_nb_pages()
    pdf.add_page()

    parse_and_render(pdf, text, base_dir)

    pdf.output(str(pdf_path))
    print(f"  {pdf_path}  ({pdf_path.stat().st_size / 1024:.0f} KB)")


def main():
    targets = []

    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            p = Path(arg)
            if not p.is_absolute():
                p = ROOT / p
            targets.append(p)
    else:
        # Default: both week reports
        for name in ("week3-report.md", "week4-report.md"):
            p = DOCS / name
            if p.exists():
                targets.append(p)

    if not targets:
        print("No markdown files found to convert.")
        sys.exit(1)

    print("Converting markdown to PDF...")
    for md_path in targets:
        if not md_path.exists():
            print(f"  SKIP {md_path} (not found)")
            continue
        pdf_path = md_path.with_suffix(".pdf")
        convert_md_to_pdf(md_path, pdf_path)

    print("Done.")


if __name__ == "__main__":
    main()
