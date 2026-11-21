"""Sinh báo cáo Word hoàn chỉnh cho đồ án nhận dạng biển số xe Việt Nam.

Báo cáo được tạo hoàn toàn bằng ``python-docx`` từ dữ liệu thật trong
``results/`` và ``data/``. Sau khi sinh, dùng Microsoft Word (COM) để cập nhật
mục lục, danh mục hình/bảng và xuất PDF.

Chạy:
    python tools\\build_report_docx.py

Đầu ra:
    reports/BaoCao.docx
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
ASSETS = REPORTS / "assets"
OUT_DOCX = REPORTS / "BaoCao.docx"

BODY_FONT = "Times New Roman"
CODE_FONT = "Consolas"
BODY_SIZE = 13
TABLE_FONT = 9.5
CAPTION_SIZE = 12

FIGURE_COUNTER = 0
TABLE_COUNTER = 0


# ======================================================================
# Tiện ích định dạng
# ======================================================================
def _set_run_font(
    run,
    name: str = BODY_FONT,
    size: float | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    color: RGBColor | None = None,
) -> None:
    run.font.name = name
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), name)


def _style_font(
    style,
    name: str = BODY_FONT,
    size: float = BODY_SIZE,
    bold: bool = False,
    italic: bool = False,
    color: RGBColor | None = None,
) -> None:
    style.font.name = name
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.italic = italic
    if color is not None:
        style.font.color.rgb = color
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), name)
    lang = rpr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        rpr.append(lang)
    lang.set(qn("w:val"), "vi-VN")


def _add_field(paragraph, instruction: str, placeholder: str = "") -> None:
    """Chèn trường Word dạng phức hợp (begin/instr/separate/end)."""
    run_begin = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    fld_begin.set(qn("w:dirty"), "true")
    run_begin._r.append(fld_begin)

    run_instr = paragraph.add_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    run_instr._r.append(instr)

    run_sep = paragraph.add_run()
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    run_sep._r.append(fld_sep)

    if placeholder:
        run_text = paragraph.add_run(placeholder)

    run_end = paragraph.add_run()
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run_end._r.append(fld_end)


def _add_seq_field(paragraph, name: str, number: int) -> None:
    _add_field(paragraph, f"SEQ {name} \\* ARABIC", str(number))


def _add_page_field(paragraph, instruction: str) -> None:
    _add_field(paragraph, instruction, "1")


def _shade_cell(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.insert_element_before(
            shd,
            "w:noWrap",
            "w:tcMar",
            "w:textDirection",
            "w:tcFitText",
            "w:vAlign",
            "w:hideMark",
        )
    shd.set(qn("w:fill"), fill)


def _set_cell_margins(cell, top: int = 40, bottom: int = 40,
                      left: int = 70, right: int = 70) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.find(qn("w:tcMar"))
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.insert_element_before(
            tc_mar,
            "w:textDirection",
            "w:tcFitText",
            "w:vAlign",
            "w:hideMark",
        )
    for tag, value in (("top", top), ("bottom", bottom),
                       ("left", left), ("right", right)):
        node = tc_mar.find(qn(f"w:{tag}"))
        if node is None:
            node = OxmlElement(f"w:{tag}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def _set_table_borders(table, color: str = "808080", size: int = 6,
                       none: bool = False) -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.insert_element_before(
            borders,
            "w:shd",
            "w:tblLayout",
            "w:tblCellMar",
            "w:tblLook",
            "w:tblCaption",
            "w:tblDescription",
        )
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = borders.find(qn(f"w:{edge}"))
        if element is None:
            element = OxmlElement(f"w:{edge}")
            borders.append(element)
        if none:
            element.set(qn("w:val"), "nil")
        else:
            element.set(qn("w:val"), "single")
            element.set(qn("w:sz"), str(size))
            element.set(qn("w:space"), "0")
            element.set(qn("w:color"), color)


def _set_repeat_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    tr_pr.insert_element_before(
        header,
        "w:tblCellSpacing",
        "w:jc",
        "w:hidden",
        "w:ins",
        "w:del",
    )


def _set_row_cant_split(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    cant = OxmlElement("w:cantSplit")
    cant.set(qn("w:val"), "true")
    tr_pr.insert_element_before(
        cant,
        "w:trHeight",
        "w:tblHeader",
        "w:tblCellSpacing",
        "w:jc",
        "w:hidden",
        "w:ins",
        "w:del",
    )


def _set_col_widths(table, widths_cm: Sequence[float]) -> None:
    table.autofit = False
    tbl_pr = table._tbl.tblPr
    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.insert_element_before(
            layout,
            "w:tblCellMar",
            "w:tblLook",
            "w:tblCaption",
            "w:tblDescription",
        )
    layout.set(qn("w:type"), "fixed")
    grid = table._tbl.tblGrid
    for index, width in enumerate(widths_cm):
        if index < len(grid.gridCol_lst):
            grid.gridCol_lst[index].set(qn("w:w"), str(int(Cm(width).twips)))
    for row in table.rows:
        for index, width in enumerate(widths_cm):
            if index < len(row.cells):
                row.cells[index].width = Cm(width)


def _set_paragraph_border(paragraph, color: str = "BFBFBF",
                          size: int = 4) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    p_bdr = OxmlElement("w:pBdr")
    for edge in ("top", "left", "bottom", "right"):
        element = OxmlElement(f"w:{edge}")
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), str(size))
        element.set(qn("w:space"), "4")
        element.set(qn("w:color"), color)
        p_bdr.append(element)
    p_pr.insert_element_before(
        p_bdr,
        "w:shd",
        "w:tabs",
        "w:suppressAutoHyphens",
        "w:kinsoku",
        "w:wordWrap",
        "w:overflowPunct",
        "w:topLinePunct",
        "w:autoSpaceDE",
        "w:autoSpaceDN",
        "w:bidi",
        "w:adjustRightInd",
        "w:snapToGrid",
        "w:spacing",
        "w:ind",
        "w:contextualSpacing",
        "w:mirrorIndents",
        "w:suppressOverlap",
        "w:jc",
        "w:textDirection",
        "w:textAlignment",
        "w:textboxTightWrap",
        "w:outlineLvl",
        "w:divId",
        "w:cnfStyle",
        "w:rPr",
        "w:sectPr",
        "w:pPrChange",
    )


def _shade_paragraph(paragraph, fill: str = "F2F2F2") -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    p_pr.insert_element_before(
        shd,
        "w:tabs",
        "w:suppressAutoHyphens",
        "w:kinsoku",
        "w:wordWrap",
        "w:overflowPunct",
        "w:topLinePunct",
        "w:autoSpaceDE",
        "w:autoSpaceDN",
        "w:bidi",
        "w:adjustRightInd",
        "w:snapToGrid",
        "w:spacing",
        "w:ind",
        "w:contextualSpacing",
        "w:mirrorIndents",
        "w:suppressOverlap",
        "w:jc",
        "w:textDirection",
        "w:textAlignment",
        "w:textboxTightWrap",
        "w:outlineLvl",
        "w:divId",
        "w:cnfStyle",
        "w:rPr",
        "w:sectPr",
        "w:pPrChange",
    )


def _add_rich_runs(paragraph, text: str, size: float = BODY_SIZE,
                   font: str = BODY_FONT) -> None:
    """Thêm chữ, hỗ trợ **in đậm** và `mã` trong dấu huyền."""
    parts = re.split(r"(\*\*.*?\*\*|`[^`]*`)", text)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            run = paragraph.add_run(part[2:-2])
            _set_run_font(run, font, size, bold=True)
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            run = paragraph.add_run(part[1:-1])
            _set_run_font(run, CODE_FONT, max(9.0, size - 1.5))
        else:
            run = paragraph.add_run(part)
            _set_run_font(run, font, size)


def add_para(
    doc: Document,
    text: str = "",
    indent: bool = True,
    align=WD_ALIGN_PARAGRAPH.JUSTIFY,
    size: float = BODY_SIZE,
    space_before: float = 0,
    space_after: float = 6,
    line_spacing: float = 1.5,
    italic: bool = False,
    bold: bool = False,
    color: RGBColor | None = None,
    keep_with_next: bool = False,
) -> Any:
    p = doc.add_paragraph()
    p.paragraph_format.alignment = align
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = line_spacing
    p.paragraph_format.first_line_indent = Cm(1.0) if indent else Cm(0)
    p.paragraph_format.keep_with_next = keep_with_next
    if text:
        _add_rich_runs(p, text, size=size)
        if italic or bold or color is not None:
            for run in p.runs:
                if italic:
                    run.font.italic = True
                if bold:
                    run.font.bold = True
                if color is not None:
                    run.font.color.rgb = color
    return p


def add_center(
    doc: Document,
    text: str,
    size: float = BODY_SIZE,
    bold: bool = False,
    italic: bool = False,
    space_before: float = 0,
    space_after: float = 6,
    line_spacing: float = 1.2,
) -> Any:
    p = doc.add_paragraph()
    p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = line_spacing
    run = p.add_run(text)
    _set_run_font(run, BODY_FONT, size, bold=bold, italic=italic)
    return p


def add_bullets(doc: Document, items: Iterable[str], level: int = 0) -> None:
    for item in items:
        p = doc.add_paragraph()
        p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.left_indent = Cm(1.0 + 0.6 * level)
        p.paragraph_format.first_line_indent = Cm(-0.5)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.line_spacing = 1.5
        bullet = "• " if level == 0 else "– "
        run = p.add_run(bullet)
        _set_run_font(run, BODY_FONT, BODY_SIZE)
        _add_rich_runs(p, item)


def add_numbered(doc: Document, items: Iterable[str]) -> None:
    for index, item in enumerate(items, start=1):
        p = doc.add_paragraph()
        p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.left_indent = Cm(1.1)
        p.paragraph_format.first_line_indent = Cm(-0.6)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.line_spacing = 1.5
        run = p.add_run(f"{index}. ")
        _set_run_font(run, BODY_FONT, BODY_SIZE)
        _add_rich_runs(p, item)


def add_front_heading(doc: Document, text: str, page_break: bool = True) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.page_break_before = page_break
    p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(14)
    p.paragraph_format.line_spacing = 1.2
    p.paragraph_format.keep_with_next = True
    run = p.add_run(text.upper())
    _set_run_font(run, BODY_FONT, 16, bold=True)


def add_h1(doc: Document, text: str, page_break: bool = True) -> None:
    p = doc.add_paragraph(style="Heading 1")
    p.paragraph_format.page_break_before = page_break
    p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(14)
    p.paragraph_format.line_spacing = 1.2
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.first_line_indent = Cm(0)
    run = p.add_run(text)
    _set_run_font(run, BODY_FONT, 16, bold=True, color=RGBColor(0, 0, 0))


def add_h2(doc: Document, text: str, space_before: float = 12,
           space_after: float = 6) -> None:
    p = doc.add_paragraph(style="Heading 2")
    p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.25
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.first_line_indent = Cm(0)
    run = p.add_run(text)
    _set_run_font(run, BODY_FONT, 14, bold=True, color=RGBColor(0, 0, 0))


def add_h3(doc: Document, text: str) -> None:
    p = doc.add_paragraph(style="Heading 3")
    p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.25
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.first_line_indent = Cm(0)
    run = p.add_run(text)
    _set_run_font(run, BODY_FONT, 13, bold=True, italic=True,
                  color=RGBColor(0, 0, 0))


def add_formula(doc: Document, formula: str, number: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.left_indent = Cm(1.2)
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.2
    p.paragraph_format.tab_stops.add_tab_stop(Cm(16.0), WD_TAB_ALIGNMENT.RIGHT)
    run = p.add_run(formula)
    _set_run_font(run, BODY_FONT, 12.5, italic=True)
    run = p.add_run("\t(" + number + ")")
    _set_run_font(run, BODY_FONT, 12)


def add_code(doc: Document, code: str, caption: str | None = None,
             space_before: float = 4, space_after: float = 8) -> None:
    if caption:
        add_para(doc, caption, indent=False, align=WD_ALIGN_PARAGRAPH.LEFT,
                 size=11, italic=True, space_after=2, keep_with_next=True)
    p = doc.add_paragraph()
    p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.left_indent = Cm(0.5)
    p.paragraph_format.right_indent = Cm(0.5)
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.0
    p.paragraph_format.keep_together = len(code.rstrip("\n").split("\n")) <= 40
    _shade_paragraph(p, "F4F4F4")
    _set_paragraph_border(p)
    lines = code.rstrip("\n").split("\n")
    for index, line in enumerate(lines):
        run = p.add_run(line)
        _set_run_font(run, CODE_FONT, 9)
        if index < len(lines) - 1:
            run.add_break(WD_BREAK.LINE)


def add_caption(doc: Document, label: str, seq_name: str, text: str,
                table: bool = False) -> None:
    global FIGURE_COUNTER, TABLE_COUNTER
    if table:
        TABLE_COUNTER += 1
        number = TABLE_COUNTER
    else:
        FIGURE_COUNTER += 1
        number = FIGURE_COUNTER
    p = doc.add_paragraph()
    p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(8 if not table else 4)
    p.paragraph_format.line_spacing = 1.0
    p.paragraph_format.keep_with_next = table
    run = p.add_run(f"{label} ")
    _set_run_font(run, BODY_FONT, CAPTION_SIZE, bold=True)
    _add_seq_field(p, seq_name, number)
    run = p.add_run(": " + text)
    _set_run_font(run, BODY_FONT, CAPTION_SIZE, italic=True)


def add_figure(doc: Document, path: Path, caption: str,
               width_cm: float = 15.5) -> None:
    if not path.exists():
        add_para(doc, f"[Không tìm thấy hình: {path.name}]", indent=False,
                 align=WD_ALIGN_PARAGRAPH.CENTER, italic=True)
        return
    p = doc.add_paragraph()
    p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    p.paragraph_format.keep_with_next = True
    run = p.add_run()
    run.add_picture(str(path), width=Cm(width_cm))
    add_caption(doc, "Hình", "Hinh", caption, table=False)


def add_source_note(doc: Document, text: str) -> None:
    add_para(doc, text, indent=False, align=WD_ALIGN_PARAGRAPH.LEFT,
             size=9, italic=True, space_before=0, space_after=8,
             line_spacing=1.0, color=RGBColor(80, 80, 80))


def add_table(
    doc: Document,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    widths_cm: Sequence[float],
    caption: str | None = None,
    note: str | None = None,
    font_size: float = TABLE_FONT,
    header_fill: str = "D9E2F3",
    aligns: Sequence[str] | None = None,
    allow_split: bool = True,
    keep_together: bool = True,
) -> Any:
    if caption:
        add_caption(doc, "Bảng", "Bang", caption, table=True)
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    _set_table_borders(table)
    header_row = table.rows[0]
    _set_repeat_header(header_row)
    _set_row_cant_split(header_row)
    for index, header in enumerate(headers):
        cell = header_row.cells[index]
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        _shade_cell(cell, header_fill)
        _set_cell_margins(cell)
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.line_spacing = 1.0
        run = paragraph.add_run(str(header))
        _set_run_font(run, BODY_FONT, font_size, bold=True)
    for row_values in rows:
        row = table.add_row()
        if not allow_split or keep_together:
            _set_row_cant_split(row)
        for index, value in enumerate(row_values):
            cell = row.cells[index]
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            _set_cell_margins(cell)
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.line_spacing = 1.0
            if aligns and index < len(aligns):
                paragraph.alignment = {
                    "left": WD_ALIGN_PARAGRAPH.LEFT,
                    "center": WD_ALIGN_PARAGRAPH.CENTER,
                    "right": WD_ALIGN_PARAGRAPH.RIGHT,
                    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
                }.get(aligns[index], WD_ALIGN_PARAGRAPH.LEFT)
            else:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
            run = paragraph.add_run(str(value))
            _set_run_font(run, BODY_FONT, font_size)
    if keep_together:
        for row in table.rows[:-1]:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    paragraph.paragraph_format.keep_with_next = True
    _set_col_widths(table, widths_cm)
    if note:
        add_source_note(doc, note)
    return table


def setup_page(section) -> None:
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(3.0)
    section.right_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.0)
    section.header_distance = Cm(1.0)
    section.footer_distance = Cm(1.0)


def set_page_number_start(section, start: int = 1) -> None:
    sect_pr = section._sectPr
    pg_num = sect_pr.find(qn("w:pgNumType"))
    if pg_num is None:
        pg_num = OxmlElement("w:pgNumType")
        sect_pr.insert_element_before(
            pg_num,
            "w:cols",
            "w:formProt",
            "w:vAlign",
            "w:noEndnote",
            "w:titlePg",
            "w:textDirection",
            "w:bidi",
            "w:rtlGutter",
            "w:docGrid",
            "w:printerSettings",
        )
    pg_num.set(qn("w:start"), str(start))


def add_header_footer(section, header_text: str) -> None:
    section.header.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False
    header = section.header
    hp = header.paragraphs[0]
    hp.text = ""
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    hp.paragraph_format.space_after = Pt(0)
    run = hp.add_run(header_text)
    _set_run_font(run, BODY_FONT, 9, italic=True,
                  color=RGBColor(90, 90, 90))
    _set_paragraph_border(hp, color="BFBFBF", size=4)

    footer = section.footer
    fp = footer.paragraphs[0]
    fp.text = ""
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fp.paragraph_format.space_before = Pt(0)
    run = fp.add_run("Trang ")
    _set_run_font(run, BODY_FONT, 9)
    _add_page_field(fp, "PAGE")
    run = fp.add_run(" / ")
    _set_run_font(run, BODY_FONT, 9)
    _add_page_field(fp, "SECTIONPAGES")


def set_update_fields(doc: Document) -> None:
    settings = doc.settings.element
    update = settings.find(qn("w:updateFields"))
    if update is None:
        update = OxmlElement("w:updateFields")
        settings.append(update)
    update.set(qn("w:val"), "true")


def add_toc_field(doc: Document, instruction: str, placeholder: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.3
    _add_field(p, instruction, placeholder)
    for run in p.runs:
        _set_run_font(run, BODY_FONT, 11)


# ======================================================================
# Nạp dữ liệu
# ======================================================================
def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value * 100.0:.{digits}f}%"


def _num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def _ms(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.0f}"


def _prediction_display(row: dict[str, str]) -> str:
    """Chuỗi dự đoán thực tế để hiển thị, không dùng cờ predicted_plate."""
    text = (row.get("detected_text") or "").strip()
    return text if text else "—"


def _seg_display(row: dict[str, str]) -> str:
    """Số ký tự phân đoạn khớp trên số ký tự nhãn.

    Với dữ liệu thật, nhãn không có hộp ký tự nên evaluation dùng count_proxy:
    ``seg_matched`` bằng 0 nhưng ``seg_pred_count`` mới là số ký tự dự đoán.
    """
    try:
        gt_count = int(float(row.get("seg_gt_count") or 0))
    except ValueError:
        gt_count = 0
    if gt_count <= 0:
        return "—"
    if row.get("segmentation_method") == "count_proxy":
        try:
            matched = int(float(row.get("seg_pred_count") or 0))
        except ValueError:
            matched = 0
    else:
        try:
            matched = int(float(row.get("seg_matched") or 0))
        except ValueError:
            matched = 0
    return f"{matched}/{gt_count}"


def _align_substitutions(prediction: str, ground_truth: str) -> list[tuple[str, str]]:
    pred = prediction or ""
    gt = ground_truth or ""
    m, n = len(pred), len(gt)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            dp[i][j] = min(
                dp[i - 1][j - 1] + (pred[i - 1] != gt[j - 1]),
                dp[i - 1][j] + 1,
                dp[i][j - 1] + 1,
            )
    pairs: list[tuple[str, str]] = []
    i, j = m, n
    while i > 0 and j > 0:
        if dp[i][j] == dp[i - 1][j - 1] + (pred[i - 1] != gt[j - 1]):
            if pred[i - 1] != gt[j - 1]:
                pairs.append((gt[j - 1], pred[i - 1]))
            i -= 1
            j -= 1
        elif dp[i][j] == dp[i - 1][j] + 1:
            i -= 1
        else:
            j -= 1
    return pairs


def _wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _clean_prediction(text: str) -> str:
    return re.sub(r"[^A-Z0-9?]", "", (text or "").upper())


def _condition_stats(rows: Sequence[dict[str, str]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row.get("has_gt_plate") == "1":
            grouped[row["condition"]].append(row)
    stats: dict[str, dict[str, Any]] = {}
    for condition, items in grouped.items():
        count = len(items)
        exact = sum(1 for row in items if row.get("exact_match") == "1")
        detected = sum(1 for row in items if row.get("detection_correct") == "1")
        ca = statistics.fmean(float(row["char_accuracy"]) for row in items)
        elapsed = statistics.fmean(float(row["total_time_ms"]) for row in items)
        stats[condition] = {
            "count": count,
            "exact": exact,
            "detected": detected,
            "ca": ca,
            "time": elapsed,
        }
    return stats


def _status_counter(rows: Sequence[dict[str, str]]) -> Counter:
    return Counter(row["status"] for row in rows)


def _template_counts() -> dict[str, int]:
    labels = sorted(
        path.name for path in (ROOT / "data" / "templates").iterdir() if path.is_dir()
    )
    raw = 0
    files_per_label = Counter()
    for label in labels:
        count = len(
            [
                path
                for path in (ROOT / "data" / "templates" / label).iterdir()
                if path.suffix.lower() in {".png", ".jpg", ".jpeg"}
            ]
        )
        files_per_label[count] += 1
        raw += count
    return {
        "labels": len(labels),
        "raw": raw,
        "files_per_label_mode": files_per_label.most_common(1)[0][0],
        "full": 1550,
        "coarse": 216,
        "open_top": 45,
        "retained": 1505,
    }


def _code_lines() -> list[tuple[str, int]]:
    files = [
        "src/config.py",
        "src/io_utils.py",
        "src/preprocessing.py",
        "src/plate_detection.py",
        "src/plate_rectification.py",
        "src/character_segmentation.py",
        "src/character_recognition.py",
        "src/postprocessing.py",
        "src/evaluation.py",
        "src/pipeline.py",
        "src/__init__.py",
        "ui/app.py",
        "main.py",
    ]
    rows = []
    for name in files:
        path = ROOT / name
        rows.append((name, len(path.read_text(encoding="utf-8").splitlines())))
    return rows


def load_data() -> dict[str, Any]:
    results = ROOT / "results"
    data = {
        "user": {
            "rows": _read_csv(results / "user_final.csv"),
            "summary": _read_json(results / "user_final_summary.json"),
        },
        "special": {
            "rows": _read_csv(results / "user_special_final.csv"),
            "summary": _read_json(results / "user_special_final_summary.json"),
        },
        "dev": {
            "rows": _read_csv(results / "dev_after_final.csv"),
            "summary": _read_json(results / "dev_after_final_summary.json"),
        },
        "test": {
            "rows": _read_csv(results / "test_after_final.csv"),
            "summary": _read_json(results / "test_after_final_summary.json"),
        },
        "baseline": {
            "user": _read_json(results / "user_baseline_summary.json"),
            "dev": _read_json(results / "dev_summary.json"),
            "test": _read_json(results / "test_summary.json"),
        },
        "labels": _read_csv(ROOT / "data" / "labels.csv"),
        "user_labels": _read_csv(ROOT / "data" / "user_labels.csv"),
        "config_hash": _sha256(ROOT / "config.yaml"),
        "template_counts": _template_counts(),
        "code_lines": _code_lines(),
    }
    data["dev"]["condition_stats"] = _condition_stats(data["dev"]["rows"])
    data["test"]["condition_stats"] = _condition_stats(data["test"]["rows"])
    data["dev"]["status_counts"] = _status_counter(data["dev"]["rows"])
    data["test"]["status_counts"] = _status_counter(data["test"]["rows"])
    data["user"]["status_counts"] = _status_counter(data["user"]["rows"])
    data["special"]["status_counts"] = _status_counter(data["special"]["rows"])

    confusion = {"dev": Counter(), "test": Counter()}
    for split in ("dev", "test"):
        for row in data[split]["rows"]:
            if row.get("has_gt_plate") != "1":
                continue
            pred = _clean_prediction(row.get("detected_text", ""))
            gt = _clean_prediction(row.get("ground_truth", ""))
            for gt_char, pred_char in _align_substitutions(pred, gt):
                if gt_char != "?" and pred_char != "?":
                    confusion[split][(gt_char, pred_char)] += 1
    data["confusion"] = confusion
    return data


# ======================================================================
# Bìa và phần đầu
# ======================================================================
def _add_cover(doc: Document) -> None:
    add_center(doc, "TRƯỜNG ĐẠI HỌC [TÊN TRƯỜNG]", size=14, bold=True,
               space_before=18, space_after=4)
    add_center(doc, "KHOA [TÊN KHOA]", size=13, bold=True, space_after=10)
    line = doc.add_paragraph()
    line.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    line.paragraph_format.space_before = Pt(0)
    line.paragraph_format.space_after = Pt(26)
    run = line.add_run("───────────────  ❖  ───────────────")
    _set_run_font(run, BODY_FONT, 11, color=RGBColor(70, 70, 70))

    add_center(doc, "BÁO CÁO ĐỒ ÁN MÔN HỌC", size=15, bold=True,
               space_before=6, space_after=8)
    add_center(doc, "ĐỀ TÀI", size=12, bold=True, space_after=6)
    add_center(
        doc,
        "XÂY DỰNG HỆ THỐNG NHẬN DẠNG BIỂN SỐ XE VIỆT NAM\n"
        "BẰNG XỬ LÝ ẢNH TRUYỀN THỐNG",
        size=21,
        bold=True,
        space_before=4,
        space_after=10,
        line_spacing=1.25,
    )
    add_center(
        doc,
        "Ứng dụng Python, OpenCV và Template Matching",
        size=12,
        italic=True,
        space_after=34,
    )

    table = doc.add_table(rows=3, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    _set_table_borders(table, none=True)
    _set_col_widths(table, [5.4, 8.2])
    rows = [
        ("Giảng viên hướng dẫn:", ["[HỌ TÊN GIẢNG VIÊN]"]),
        (
            "Sinh viên thực hiện:",
            [
                "Nguyễn Đình Khải — B23DCCN420",
                "Nguyễn Trung Tường — B23DCCN909",
                "Bùi Văn Đạt — B23DCCN126",
            ],
        ),
        ("Lớp:", ["[LỚP]"]),
    ]
    for row, (label, values) in zip(table.rows, rows):
        row.cells[0].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        row.cells[1].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        _set_cell_margins(row.cells[0], top=60, bottom=60, left=40, right=40)
        _set_cell_margins(row.cells[1], top=60, bottom=60, left=40, right=40)
        p0 = row.cells[0].paragraphs[0]
        p0.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p0.paragraph_format.space_before = Pt(0)
        p0.paragraph_format.space_after = Pt(0)
        run = p0.add_run(label)
        _set_run_font(run, BODY_FONT, 13, bold=True)
        for index, value in enumerate(values):
            p1 = (
                row.cells[1].paragraphs[0]
                if index == 0
                else row.cells[1].add_paragraph()
            )
            p1.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p1.paragraph_format.space_before = Pt(0)
            p1.paragraph_format.space_after = Pt(0)
            run = p1.add_run(value)
            _set_run_font(run, BODY_FONT, 13)

    add_center(doc, "Tháng 11 năm 2026", size=13, bold=True,
               space_before=54, space_after=0)


def _add_declaration(doc: Document) -> None:
    add_front_heading(doc, "Lời cam đoan", page_break=False)
    add_para(
        doc,
        "Nhóm chúng tôi xin cam đoan báo cáo **“Xây dựng hệ thống nhận dạng biển "
        "số xe Việt Nam bằng xử lý ảnh truyền thống”** là kết quả tìm hiểu, thiết "
        "kế và triển khai của nhóm. Nội dung báo cáo không sao chép nguyên văn "
        "công trình của người khác; các tài liệu tham khảo đều được trích dẫn "
        "và ghi nguồn ở cuối báo cáo.",
    )
    add_para(
        doc,
        "Nhóm chúng tôi cam đoan các kết quả thực nghiệm được trình bày trung "
        "thực, được tính trực tiếp từ các tệp kết quả của chương trình: "
        "`results/user_final.csv`, `results/user_special_final.csv`, "
        "`results/dev_after_final.csv` và `results/test_after_final.csv`. "
        "Báo cáo không sử dụng số liệu tự tạo, không chỉnh sửa kết quả và "
        "không che giấu các trường hợp thất bại.",
        align=WD_ALIGN_PARAGRAPH.LEFT,
    )
    add_para(
        doc,
        "Hệ thống được xây dựng bằng Python và OpenCV, chỉ sử dụng các kỹ thuật "
        "xử lý ảnh truyền thống và Template Matching. Trong toàn bộ mã nguồn "
        "không sử dụng học máy, học sâu, YOLO, KNN, SVM, mô hình OCR học sẵn "
        "hoặc API nhận dạng bên ngoài.",
    )
    add_para(
        doc,
        "Nhóm chúng tôi nhận thức rõ rằng 14 ảnh thật do người dùng cung cấp đã "
        "được dùng trong quá trình tinh chỉnh tham số, nên kết quả 13/13 và 1/1 "
        "là kết quả hồi quy trên tập đã biết, **không phải độ chính xác trên "
        "một tập kiểm thử độc lập**. Các chỉ số PDR và CSA trên ảnh thật cũng "
        "chỉ là proxy theo sự hiện diện và số lượng ký tự, vì nhãn chưa có hộp "
        "bao biển số và hộp bao từng ký tự.",
    )
    add_para(
        doc,
        "Thành viên nhóm: Nguyễn Đình Khải (B23DCCN420), "
        "Nguyễn Trung Tường (B23DCCN909), Bùi Văn Đạt (B23DCCN126).",
        align=WD_ALIGN_PARAGRAPH.LEFT,
    )
    add_para(doc, "Nhóm chúng tôi xin chịu trách nhiệm về nội dung và tính trung "
             "thực của báo cáo này.", space_before=4, space_after=18)
    p = add_para(doc, "Đại diện nhóm", indent=False,
                 align=WD_ALIGN_PARAGRAPH.RIGHT, italic=True, space_after=2)
    p = add_para(doc, "(Ký và ghi rõ họ tên)", indent=False,
                 align=WD_ALIGN_PARAGRAPH.RIGHT, italic=True, space_after=36)
    add_para(doc, "Nguyễn Đình Khải", indent=False,
             align=WD_ALIGN_PARAGRAPH.RIGHT, bold=True, space_after=0)
    add_para(doc, "Tháng 11 năm 2026", indent=False,
             align=WD_ALIGN_PARAGRAPH.CENTER, italic=True, space_before=24,
             space_after=0)


def _add_acknowledgement(doc: Document) -> None:
    add_front_heading(doc, "Lời cảm ơn")
    add_para(
        doc,
        "Trong quá trình thực hiện đồ án, nhóm chúng tôi đã nhận được sự hướng "
        "dẫn, góp ý và động viên của quý thầy cô và bạn bè. Nhóm xin bày tỏ lòng "
        "biết ơn chân thành tới giảng viên hướng dẫn **[HỌ TÊN GIẢNG VIÊN]** đã "
        "định hướng đề tài, góp ý về phạm vi bài toán, cách đánh giá và cách "
        "trình bày kết quả thực nghiệm.",
    )
    add_para(
        doc,
        "Nhóm xin cảm ơn quý thầy cô trong Khoa [TÊN KHOA], Trường Đại học "
        "[TÊN TRƯỜNG] đã truyền đạt những kiến thức nền tảng về xử lý ảnh, "
        "thị giác máy tính và kỹ thuật phần mềm, tạo điều kiện để nhóm hoàn "
        "thành sản phẩm.",
    )
    add_para(
        doc,
        "Nhóm cũng xin cảm ơn các bạn trong lớp [LỚP] đã trao đổi, góp ý và "
        "hỗ trợ trong quá trình thử nghiệm. Những ý kiến phản biện đã giúp nhóm "
        "nhận ra nhiều hạn chế của hệ thống, đặc biệt là các trường hợp ảnh "
        "nghiêng mạnh, ký tự dính nhau và sự khác biệt giữa font template với "
        "font trên biển thật.",
    )
    add_para(
        doc,
        "Mặc dù đã cố gắng, báo cáo khó tránh khỏi thiếu sót. Nhóm mong nhận "
        "được góp ý của quý thầy cô để tiếp tục hoàn thiện hệ thống và phương "
        "pháp đánh giá trong các phiên bản sau.",
    )


def _add_abstract(doc: Document, data: dict[str, Any]) -> None:
    add_front_heading(doc, "Tóm tắt")
    add_para(
        doc,
        "Báo cáo trình bày việc xây dựng một hệ thống nhận dạng biển số xe "
        "Việt Nam từ ảnh tĩnh bằng xử lý ảnh truyền thống. Đầu vào là ảnh "
        "JPG/JPEG/PNG/WEBP có một biển số chính; đầu ra là chuỗi ký tự đã "
        "chuẩn hóa, hộp bao vùng biển, điểm tin cậy từng ký tự, trạng thái "
        "quyết định và các ảnh trung gian phục vụ kiểm tra.",
    )
    add_para(
        doc,
        "Pipeline gồm tám công đoạn: đọc và kiểm tra ảnh; tiền xử lý; phát hiện "
        "ứng viên biển bằng cạnh, morphology, contour và cụm thành phần giống "
        "ký tự; cắt và hiệu chỉnh phối cảnh; phân đoạn ký tự cho biển một dòng "
        "và hai dòng; chuẩn hóa ký tự về 32×48; nhận dạng bằng "
        "`TM_CCOEFF_NORMED` với bộ template đa font; và hậu xử lý chuỗi theo "
        "quy tắc định dạng. Hệ thống không dùng học máy, học sâu, YOLO, KNN, "
        "SVM, OCR học sẵn hay API nhận dạng bên ngoài.",
    )
    dev = data["dev"]["summary"]
    test = data["test"]["summary"]
    user = data["user"]["summary"]
    special = data["special"]["summary"]
    add_para(
        doc,
        f"Trên 13 ảnh thật thông thường, hệ thống nhận đúng toàn bộ chuỗi và "
        f"trả trạng thái `SUCCESS` ({_pct(user['exact_plate_accuracy'])}); ảnh "
        f"đặc biệt `8.jpg` cũng đúng ({special['exact_plate_matches']}/1). Tuy "
        f"nhiên, đây là tập đã dùng để tinh chỉnh, không phải holdout độc lập. "
        f"Trên tập tổng hợp, dev đạt PDR {_pct(dev['plate_detection_rate'])}, "
        f"CSA {_pct(dev['character_segmentation_accuracy'])}, CA "
        f"{_pct(dev['character_accuracy'])} và EPA "
        f"{_pct(dev['exact_plate_accuracy'])}; test đạt PDR "
        f"{_pct(test['plate_detection_rate'])}, CSA "
        f"{_pct(test['character_segmentation_accuracy'])}, CA "
        f"{_pct(test['character_accuracy'])} và EPA "
        f"{_pct(test['exact_plate_accuracy'])}. Mục tiêu tham chiếu EPA ≥ 70% "
        f"**chưa đạt** trên cả hai split.",
    )
    add_para(
        doc,
        "Báo cáo cũng trình bày kiến trúc mã nguồn, thiết kế cấu hình tập trung, "
        "giao diện Tkinter, bộ 78 bài kiểm thử pytest, các thực nghiệm bị loại, "
        "phân tích lỗi theo từng công đoạn và các giới hạn của phương pháp. "
        "Kết quả cho thấy Template Matching cổ điển có thể giải quyết tốt các "
        "ảnh biển rõ, nhưng còn yếu trên ảnh nghiêng mạnh, ký tự dính và sự "
        "lệch miền giữa template sinh từ font với ảnh thật.",
    )
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.first_line_indent = Cm(0)
    run = p.add_run("Từ khóa: ")
    _set_run_font(run, BODY_FONT, 12, bold=True)
    run = p.add_run(
        "nhận dạng biển số; xử lý ảnh truyền thống; OpenCV; Template Matching; "
        "phân đoạn ký tự; đánh giá thực nghiệm."
    )
    _set_run_font(run, BODY_FONT, 12, italic=True)


def _add_toc(doc: Document) -> None:
    add_front_heading(doc, "Mục lục")
    add_toc_field(
        doc,
        'TOC \\o "1-3" \\h \\z \\u',
        "Mục lục sẽ được cập nhật tự động bằng Microsoft Word.",
    )


def _add_abbreviations(doc: Document) -> None:
    add_front_heading(doc, "Danh mục từ viết tắt")
    rows = [
        ("ANPR", "Automatic Number Plate Recognition — nhận dạng biển số tự động"),
        ("API", "Application Programming Interface — giao diện lập trình ứng dụng"),
        ("CA", "Character Accuracy — độ chính xác ký tự"),
        ("CLAHE", "Contrast Limited Adaptive Histogram Equalization"),
        ("CLI", "Command Line Interface — giao diện dòng lệnh"),
        ("CSA", "Character Segmentation Accuracy — độ chính xác phân đoạn ký tự"),
        ("CSV", "Comma-Separated Values — tệp giá trị phân cách bằng dấu phẩy"),
        ("EPA", "Exact Plate Accuracy — độ chính xác chuỗi biển số đầy đủ"),
        ("FN / FP", "False Negative / False Positive — âm tính giả / dương tính giả"),
        ("IoU", "Intersection over Union — tỷ lệ giao trên hợp của hai hộp bao"),
        ("JSON", "JavaScript Object Notation — định dạng trao đổi dữ liệu"),
        ("ML / DL", "Machine Learning / Deep Learning — học máy / học sâu"),
        ("OCR", "Optical Character Recognition — nhận dạng ký tự quang học"),
        ("PDR", "Plate Detection Rate — tỷ lệ phát hiện đúng biển số"),
        ("ROI", "Region of Interest — vùng quan tâm"),
        ("TN / TP", "True Negative / True Positive — âm tính đúng / dương tính đúng"),
        ("UI", "User Interface — giao diện người dùng"),
        ("YAML", "YAML Ain't Markup Language — định dạng cấu hình"),
        (
            "TM_CCOEFF_NORMED",
            "Normalized cross-correlation — tương quan chéo chuẩn hóa của OpenCV",
        ),
    ]
    add_table(
        doc,
        ["Từ viết tắt", "Diễn giải"],
        rows,
        [4.0, 13.0],
        note=None,
        font_size=10,
        aligns=["center", "left"],
        allow_split=True,
    )


def _add_list_of_figures(doc: Document) -> None:
    add_front_heading(doc, "Danh mục hình")
    add_toc_field(
        doc,
        'TOC \\h \\z \\c "Hinh"',
        "Danh mục hình sẽ được cập nhật tự động bằng Microsoft Word.",
    )


def _add_list_of_tables(doc: Document) -> None:
    add_front_heading(doc, "Danh mục bảng")
    add_toc_field(
        doc,
        'TOC \\h \\z \\c "Bang"',
        "Danh mục bảng sẽ được cập nhật tự động bằng Microsoft Word.",
    )


# ======================================================================
# Chương 1
# ======================================================================
def _add_chapter1(doc: Document, data: dict[str, Any]) -> None:
    add_h1(doc, "CHƯƠNG 1. GIỚI THIỆU")

    add_h2(doc, "1.1. Đặt vấn đề")
    add_para(
        doc,
        "Nhận dạng biển số xe tự động (Automatic Number Plate Recognition — "
        "ANPR) là một bài toán kinh điển của thị giác máy tính, có nhiều ứng "
        "dụng trong quản lý bãi xe, kiểm soát giao thông, thu phí tự động và "
        "tìm kiếm phương tiện. Trong những năm gần đây, các mô hình học sâu "
        "đạt độ chính xác cao trên nhiều bộ dữ liệu lớn, nhưng chúng thường "
        "đòi hỏi lượng dữ liệu gán nhãn lớn, tài nguyên huấn luyện đáng kể và "
        "khó giải thích từng quyết định ở mức ký tự. Vì vậy, một pipeline xử "
        "lý ảnh truyền thống vẫn có giá trị trong bối cảnh học tập, trong các "
        "hệ thống nhúng tài nguyên hạn chế và trong những ứng dụng cần kiểm "
        "tra, hiệu chỉnh thủ công từng công đoạn.",
    )
    add_para(
        doc,
        "Biển số xe Việt Nam có nhiều dạng: biển một dòng dài, biển hai dòng "
        "vuông, biển có dải màu, biển gắn trên ô tô hoặc xe máy. Nền biển có "
        "thể sáng hoặc tối; ký tự có thể dùng nhiều kiểu font; ảnh thực tế "
        "thường bị nghiêng, thiếu sáng, mất nét, lóa sáng hoặc có vật thể che "
        "khuất. Những yếu tố này làm cho bài toán trở nên khó hơn nhiều so với "
        "việc nhận dạng một chuỗi ký tự in rõ trên nền trắng.",
    )
    add_para(
        doc,
        "Đồ án này xây dựng một hệ thống nhận dạng biển số xe Việt Nam từ ảnh "
        "tĩnh bằng **Python và OpenCV**, chỉ sử dụng các kỹ thuật xử lý ảnh "
        "truyền thống và **Template Matching**. Hệ thống không dùng học máy, "
        "học sâu, YOLO, KNN, SVM, mô hình OCR học sẵn hoặc API nhận dạng bên "
        "ngoài. Mục tiêu không chỉ là tạo ra một chương trình chạy được, mà "
        "còn là xây dựng một quy trình có thể quan sát, đo lường và giải thích "
        "được ở từng công đoạn.",
    )

    add_h2(doc, "1.2. Mục tiêu của đồ án")
    add_para(
        doc,
        "Mục tiêu tổng quát là thiết kế và triển khai một ứng dụng máy tính "
        "nhận dạng được chuỗi ký tự trên biển số xe Việt Nam từ một ảnh tĩnh, "
        "đồng thời đánh giá trung thực độ chính xác và các giới hạn của phương "
        "pháp. Các mục tiêu cụ thể gồm:",
    )
    add_numbered(
        doc,
        [
            "Xây dựng pipeline tám công đoạn từ đọc ảnh, tiền xử lý, phát hiện "
            "biển, hiệu chỉnh phối cảnh, phân đoạn ký tự, nhận dạng bằng "
            "template, hậu xử lý đến xuất kết quả.",
            "Cài đặt bộ template ký tự có quản lý phiên bản, sinh từ nhiều "
            "font và có cơ chế loại ảnh gần trùng để giảm chi phí tính toán.",
            "Xử lý được cả biển một dòng và hai dòng, kể cả trường hợp biển "
            "đặc biệt 10 ký tự có hai dòng cân bằng.",
            "Xây dựng giao diện desktop bằng Tkinter để chọn ảnh, xem ảnh "
            "trung gian, xem điểm tin cậy và lưu kết quả.",
            "Xây dựng bộ kiểm thử tự động bằng pytest cho các module quan "
            "trọng, đồng thời tạo công cụ đánh giá sinh CSV/JSON/Markdown.",
            "Đo và phân tích kết quả trên dữ liệu tổng hợp có nhãn hình học "
            "và trên 14 ảnh thật do người dùng cung cấp, nêu rõ mọi giả định "
            "và hạn chế.",
        ],
    )

    add_h2(doc, "1.3. Câu hỏi nghiên cứu")
    add_para(doc, "Báo cáo tập trung trả lời năm câu hỏi:")
    add_bullets(
        doc,
        [
            "**RQ1:** Pipeline truyền thống được thiết kế có chạy đúng end-to-end "
            "và tạo ra kết quả có cấu trúc, có thể kiểm tra được hay không?",
            "**RQ2:** Độ chính xác phát hiện, phân đoạn và nhận dạng trên dữ "
            "liệu tổng hợp đạt mức nào, và mức nào là điểm yếu chính?",
            "**RQ3:** Trên ảnh thật do người dùng cung cấp, hệ thống hoạt động "
            "ra sao, và kết quả đó có ý nghĩa thống kê gì?",
            "**RQ4:** Chi phí thời gian nằm ở công đoạn nào, có phù hợp với "
            "ứng dụng desktop tương tác không?",
            "**RQ5:** Hệ thống có đạt các mục tiêu tham chiếu của đặc tả "
            "(PDR ≥ 90%, CSA ≥ 85%, EPA ≥ 70%) hay không?",
        ],
    )

    add_h2(doc, "1.4. Phạm vi và giới hạn")
    add_para(
        doc,
        "Phạm vi đầu vào là ảnh tĩnh định dạng JPG, JPEG, PNG hoặc WEBP, có "
        "một biển số chính và kích thước tối thiểu 40 px ở cạnh ngắn. Hệ thống "
        "không xử lý video, không nhận dạng nhiều biển trong cùng một ảnh, "
        "không đọc chữ nước ngoài và không có chức năng xác minh pháp lý của "
        "biển số. Với ảnh quá mờ, biển bị che khuất hoặc ký tự không thể tách "
        "biệt, hệ thống được thiết kế để **từ chối** hoặc giữ ký tự `?` thay "
        "vì đoán bừa.",
    )
    add_para(
        doc,
        "Báo cáo không tuyên bố hệ thống thay thế được một giải pháp thương "
        "mại. Các kết quả trên ảnh thật chỉ mang tính kiểm chứng chức năng và "
        "hồi quy sau khi tinh chỉnh, không phải phép đo trên một tập kiểm thử "
        "độc lập. Đây là giới hạn quan trọng và được nhắc lại trong phần đánh "
        "giá.",
    )

    add_h2(doc, "1.5. Phương pháp tiếp cận")
    add_para(
        doc,
        "Hệ thống được tổ chức thành các module độc lập, mỗi module có đầu "
        "vào/đầu ra rõ ràng và có thể kiểm thử riêng. Luồng xử lý chính gồm: "
        "đọc và kiểm tra ảnh; chuyển xám, làm mờ, tăng tương phản cục bộ và "
        "tính cạnh; sinh ứng viên biển bằng morphology và contour; lọc, xếp "
        "hạng và thử tối đa tám ứng viên; cắt, hiệu chỉnh phối cảnh; phân đoạn "
        "ký tự theo dòng; chuẩn hóa ký tự; so khớp template; hậu xử lý chuỗi "
        "và quyết định trạng thái.",
    )
    add_para(
        doc,
        "Cách đánh giá được thiết kế để tránh các kết luận đẹp nhưng thiếu cơ "
        "sở. Với dữ liệu tổng hợp, nhãn có hộp bao biển và hộp bao từng ký tự, "
        "nên có thể tính PDR theo IoU, CSA theo IoU và CA/EPA theo chuỗi. Với "
        "ảnh thật, nhãn chỉ có chuỗi ký tự, nên PDR và CSA được tính bằng đại "
        "diện (proxy) theo sự hiện diện và số lượng ký tự; báo cáo ghi rõ điều "
        "này và không so sánh trực tiếp với các chỉ số dựa trên IoU.",
    )

    add_h2(doc, "1.6. Đóng góp chính")
    add_bullets(
        doc,
        [
            "Một pipeline hoàn chỉnh, có cấu hình tập trung, giao diện desktop, "
            "CLI, script chạy hàng loạt và bộ 78 bài kiểm thử pytest.",
            "Hai nguồn ứng viên biển được tách biệt: ứng viên hình học và ứng "
            "viên cụm ký tự; cơ chế mượn hộp bao hình học để báo cáo vị trí "
            "mà không thay đổi vùng cắt dùng cho nhận dạng.",
            "Quy tắc chấp nhận biển 10 ký tự chỉ khi hai dòng cân bằng, giúp "
            "tránh chuỗi giả do mảnh nhiễu ở mép biển.",
            "Prior số lỗ, biến thể chữ `4` hở đỉnh và rerank theo vị trí chỉ "
            "trong các ứng viên template đã chấm điểm, không tạo ký tự mới.",
            "Một quy trình đánh giá sinh CSV/JSON/Markdown, có thống kê theo "
            "điều kiện, theo công đoạn và có phân tích lỗi cụ thể.",
            "Một báo cáo nêu cả kết quả đạt được và các thất bại, với các "
            "tuyên bố được giới hạn đúng mức.",
        ],
    )

    add_h2(doc, "1.7. Thành viên và phân công công việc")
    add_para(
        doc,
        "Đồ án được thực hiện bởi ba thành viên. Cách phân công dưới đây bám "
        "theo module của hệ thống để mỗi thành viên chịu trách nhiệm một phần "
        "có đầu vào, đầu ra và bài kiểm thử riêng.",
    )
    add_table(
        doc,
        ["Thành viên", "MSSV", "Phụ trách chính", "Tỷ lệ"],
        [
            [
                "Nguyễn Đình Khải",
                "B23DCCN420",
                "Kiến trúc pipeline, phát hiện biển, hiệu chỉnh phối cảnh, "
                "cấu hình, CLI",
                "35%",
            ],
            [
                "Nguyễn Trung Tường",
                "B23DCCN909",
                "Phân đoạn ký tự, nhận dạng Template Matching, hậu xử lý, "
                "sinh template",
                "33%",
            ],
            [
                "Bùi Văn Đạt",
                "B23DCCN126",
                "Tiền xử lý, giao diện Tkinter, đánh giá, bộ kiểm thử, "
                "dữ liệu, báo cáo",
                "32%",
            ],
        ],
        widths_cm=[3.4, 3.0, 8.2, 1.8],
        caption="Phân công công việc của nhóm",
        aligns=["left", "center", "left", "center"],
    )
    add_para(
        doc,
        "Nguyễn Đình Khải giữ vai trò nhóm trưởng: chốt phạm vi, điều phối tiến "
        "độ, review chéo và chịu trách nhiệm bản nộp cuối. Tỷ lệ đóng góp phản "
        "ánh khối lượng mã nguồn và trách nhiệm tích hợp; chi tiết nhiệm vụ "
        "theo tuần được ghi trong tài liệu `docs/PHAN_CONG.md` của kho mã nguồn.",
    )

    add_h2(doc, "1.8. Cấu trúc báo cáo")
    add_para(
        doc,
        "Phần còn lại của báo cáo được tổ chức như sau. **Chương 2** trình bày "
        "cơ sở lý thuyết về xử lý ảnh, phát hiện contour, biến đổi phối cảnh, "
        "phân đoạn ký tự, Template Matching và các độ đo đánh giá. **Chương 3** "
        "phân tích yêu cầu, thiết kế kiến trúc, module, cấu hình, dữ liệu và "
        "giao diện. **Chương 4** mô tả chi tiết triển khai từng công đoạn, các "
        "quyết định kỹ thuật và độ phức tạp tính toán. **Chương 5** trình bày "
        "thực nghiệm, kết quả từng ảnh, so sánh với baseline, phân tích lỗi, "
        "các thực nghiệm bị loại và các đe dọa tính hợp lệ. **Chương 6** kết "
        "luận, nêu hạn chế và hướng phát triển. Cuối báo cáo là tài liệu tham "
        "khảo và các phụ lục về cấu hình, cài đặt, kiểm thử, lệnh tái lập và "
        "kích thước ảnh.",
    )


# ======================================================================
# Chương 2
# ======================================================================
def _add_chapter2(doc: Document, data: dict[str, Any]) -> None:
    add_h1(doc, "CHƯƠNG 2. CƠ SỞ LÝ THUYẾT VÀ CÔNG NGHỆ")

    add_h2(doc, "2.1. Ảnh số và các phép biến đổi cơ bản")
    add_para(
        doc,
        "Ảnh số là một ma trận điểm ảnh (pixel). Mỗi pixel trong ảnh màu BGR "
        "của OpenCV chứa ba giá trị kênh blue, green, red trong khoảng 0–255. "
        "Để giảm khối lượng tính toán và tận dụng thông tin cường độ, hệ thống "
        "chuyển ảnh sang ảnh xám theo công thức chuẩn:",
    )
    add_formula(
        doc,
        "Gray(x, y) = 0.299·R(x, y) + 0.587·G(x, y) + 0.114·B(x, y)",
        "2.1",
    )
    add_para(
        doc,
        "Ảnh xám vẫn giữ được cấu trúc hình học của ký tự và viền biển, đồng "
        "thời làm nổi bật tương phản giữa mực in và nền. Tuy nhiên, ảnh thực "
        "tế thường có ánh sáng không đều: vùng biển có thể tối trong khi nền "
        "sáng, hoặc ngược lại. Vì vậy, bên cạnh các phép biến đổi toàn cục, "
        "hệ thống sử dụng các phép biến đổi cục bộ để thích nghi với từng vùng "
        "ảnh.",
    )

    add_h2(doc, "2.2. Làm mờ, tăng tương phản và phát hiện cạnh")
    add_para(
        doc,
        "**Làm mờ Gaussian** thay giá trị mỗi pixel bằng trung bình có trọng "
        "số của các pixel lân cận, với trọng số giảm theo khoảng cách. Với "
        "nhân kích thước lẻ và độ lệch chuẩn σ, trọng số tại vị trí (x, y) "
        "tính theo:",
    )
    add_formula(
        doc,
        "G(x, y) = 1/(2πσ²) · exp(−(x² + y²)/(2σ²))",
        "2.2",
    )
    add_para(
        doc,
        "Trong hệ thống, ảnh được làm mờ nhẹ trước khi tính cạnh và trước khi "
        "so khớp template. Làm mờ giúp giảm nhiễu cảm biến, giảm ảnh hưởng của "
        "độ dày nét và làm cho phép tương quan ổn định hơn khi hai ảnh không "
        "trùng khít từng pixel.",
    )
    add_para(
        doc,
        "**CLAHE** (Contrast Limited Adaptive Histogram Equalization) chia "
        "ảnh thành các ô nhỏ, cân bằng histogram trong từng ô và giới hạn độ "
        "khuếch đại tương phản để tránh làm nổi nhiễu. Kết quả được nội suy "
        "song tuyến giữa các ô để tránh vệt chuyển tiếp. Trong cấu hình cuối, "
        "CLAHE được bật cho công đoạn phân đoạn ký tự và tắt cho tiền xử lý "
        "phát hiện, nhằm giữ đặc trưng cạnh ổn định trên ảnh tổng hợp.",
    )
    add_para(
        doc,
        "**Phát hiện cạnh Canny** gồm bốn bước: làm trơn ảnh; tính gradient "
        "theo hai hướng bằng toán tử Sobel; loại các điểm không phải cực đại "
        "địa phương (non-maximum suppression); và phân ngưỡng kép có trễ "
        "(hysteresis) để nối các cạnh yếu vào cạnh mạnh. Hệ thống dùng ngưỡng "
        "cố định 60/180 trong cấu hình cuối và có tùy chọn tính ngưỡng tự động "
        "theo trung vị ảnh.",
    )
    add_para(
        doc,
        "**Nhị phân hóa Otsu** chọn ngưỡng T sao cho phương sai giữa hai lớp "
        "foreground/background đạt cực đại:",
    )
    add_formula(
        doc,
        "σ²_b(T) = ω₀(T)·ω₁(T)·[μ₀(T) − μ₁(T)]²",
        "2.3",
    )
    add_para(
        doc,
        "Trong đó ω₀, ω₁ là tỷ lệ pixel của hai lớp và μ₀, μ₁ là giá trị "
        "trung bình tương ứng. Otsu phù hợp khi histogram có hai đỉnh tương "
        "đối rõ. Với ảnh có ánh sáng không đều, hệ thống còn tính thêm các "
        "phiên bản **adaptive threshold** với kích thước khối khác nhau; công "
        "đoạn phân đoạn sẽ thử nhiều phiên bản nhị phân và chọn phương án có "
        "điểm hợp lý hình học cao nhất.",
    )

    add_h2(doc, "2.3. Hình thái học và trích xuất contour")
    add_para(
        doc,
        "Các phép hình thái học (morphology) thao tác trên ảnh nhị phân bằng "
        "một phần tử cấu trúc (kernel). Phép giãn (dilation) mở rộng vùng "
        "trắng; phép co (erosion) thu hẹp vùng trắng; phép đóng (closing) là "
        "giãn sau co, có tác dụng nối các nét đứt và lấp lỗ nhỏ. Hệ thống dùng "
        "đóng với các kernel chữ nhật như 17×3, 25×5 và 15×7 để tạo nhiều bản "
        "đồ morphology khác nhau, phục vụ cả biển một dòng và hai dòng.",
    )
    add_para(
        doc,
        "Sau khi đóng, các thành phần liên thông được trích xuất bằng "
        "`findContours`. Mỗi contour được thay bằng hộp bao `boundingRect`, "
        "hoặc xấp xỉ đa giác bằng `approxPolyDP`. Thuật toán Douglas–Peucker "
        "trong `approxPolyDP` loại bớt các đỉnh trung gian sao cho sai lệch "
        "so với contour gốc không vượt quá epsilon; hệ thống đặt epsilon bằng "
        "2% chu vi contour. Nếu xấp xỉ cho ra bốn đỉnh và tứ giác có diện tích "
        "đủ lớn, tứ giác đó được dùng để hiệu chỉnh phối cảnh. Ngược lại, hệ "
        "thống dùng `minAreaRect` để ước lượng góc xoay và thực hiện deskew.",
    )
    add_para(
        doc,
        "Các contour được lọc theo nhiều tiêu chí: diện tích tương đối so với "
        "ảnh, tỷ lệ rộng/cao, độ đặc (diện tích contour chia diện tích hộp "
        "bao), mật độ cạnh và mức giống vùng chữ. Việc lọc sớm giúp giảm số "
        "ứng viên phải đưa qua phân đoạn và nhận dạng, vốn là các công đoạn "
        "tốn thời gian nhất.",
    )

    add_h2(doc, "2.4. Biến đổi phối cảnh")
    add_para(
        doc,
        "Biến đổi phối cảnh ánh xạ một tứ giác bất kỳ về hình chữ nhật thông "
        "qua ma trận đồng nhất 3×3 H. Với tọa độ thuần nhất, phép biến đổi "
        "được viết:",
    )
    add_formula(
        doc,
        "[x′, y′, w′]ᵀ = H · [x, y, 1]ᵀ,   u = x′/w′,   v = y′/w′",
        "2.4",
    )
    add_para(
        doc,
        "OpenCV cung cấp `getPerspectiveTransform` để tính H từ bốn cặp điểm "
        "tương ứng và `warpPerspective` để nội suy ảnh kết quả. Trong hệ thống, "
        "bốn góc của tứ giác biển được sắp xếp theo thứ tự trên-trái, trên-phải, "
        "dưới-phải, dưới-trái trước khi tính H. Ma trận nghịch đảo H⁻¹ được "
        "lưu lại để ánh xạ hộp bao ký tự từ ảnh biển đã hiệu chỉnh về ảnh gốc, "
        "phục vụ đánh giá CSA theo IoU.",
    )
    add_para(
        doc,
        "Trong trường hợp không tìm được tứ giác đủ tin cậy, hệ thống giữ "
        "nguyên vùng cắt theo hộp bao hoặc xoay nhẹ nếu góc nghiêng nằm trong "
        "khoảng 2,5°–18°. Cách dự phòng này giúp pipeline không bị dừng trên "
        "những ảnh mà contour biển không kín, nhưng cũng là một nguồn sai số "
        "trên ảnh nghiêng mạnh.",
    )

    add_h2(doc, "2.5. Phân đoạn ký tự")
    add_para(
        doc,
        "Phân đoạn ký tự là bước chuyển từ ảnh biển đã hiệu chỉnh sang danh "
        "sách các hộp bao ký tự theo thứ tự đọc. Hệ thống dùng hai tín hiệu "
        "chính: **projection profile** và **connected components**.",
    )
    add_bullets(
        doc,
        [
            "Projection ngang: cộng số pixel foreground theo từng hàng để tìm "
            "các dải có mật độ cao. Khoảng trống giữa hai dải được dùng để "
            "tách dòng.",
            "Projection dọc trong mỗi dòng: cộng số pixel foreground theo "
            "từng cột để tìm ranh giới giữa các ký tự.",
            "Connected components: gom các thành phần liên thông có kích "
            "thước, tỷ lệ và độ đặc giống ký tự; dùng làm phương án dự phòng "
            "khi projection gộp hai dòng sát nhau.",
            "Tách hộp quá rộng: nếu một hộp rộng gần gấp đôi chiều rộng trung "
            "vị, hệ thống tìm điểm thắt (valley) trong projection dọc để tách "
            "thành hai ký tự; nếu không có điểm thắt rõ, vẫn tách tại vị trí "
            "có projection thấp nhất quanh tâm khi hộp đủ rộng.",
        ],
    )
    add_para(
        doc,
        "Sau khi tách, các hộp được lọc theo chiều cao tương đối so với dòng, "
        "chiều rộng, diện tích, độ đặc và vị trí ở mép biển. Các hộp nằm sát "
        "mép và có kích thước bất thường thường là viền biển, ốc vít hoặc mảnh "
        "nhiễu, nên bị loại. Cuối cùng, hệ thống đánh giá tính hợp lý của toàn "
        "bộ phương án phân đoạn dựa trên số ký tự, độ đồng đều chiều cao, cấu "
        "trúc dòng và vị trí tương đối.",
    )

    add_h2(doc, "2.6. Template Matching")
    add_para(
        doc,
        "Template Matching so khớp một ảnh truy vấn nhỏ với từng mẫu trong bộ "
        "template bằng cách trượt mẫu qua ảnh và tính độ tương đồng tại mỗi vị "
        "trí. Vì ký tự đã được chuẩn hóa về cùng kích thước 32×48, phép so "
        "khớp chỉ cần một vị trí. Hệ thống dùng hệ số tương quan chéo chuẩn "
        "hóa `TM_CCOEFF_NORMED`:",
    )
    add_formula(
        doc,
        "R = Σ[T′(x,y)·I′(x,y)] / sqrt(ΣT′(x,y)² · ΣI′(x,y)²)",
        "2.5",
    )
    add_para(
        doc,
        "Trong đó T′ và I′ là template và ảnh truy vấn sau khi trừ giá trị "
        "trung bình. Hệ số này nằm trong khoảng −1 đến 1; giá trị càng cao "
        "thì cấu trúc nét càng tương đồng. Việc làm mờ Gaussian với σ = 2,0 "
        "trước khi tính tương quan giúp giảm nhạy cảm với độ dày nét và lệch "
        "căn chỉnh nhỏ.",
    )
    add_para(
        doc,
        "Bộ template được sinh từ nhiều font, nhiều biến thể độ đậm và được "
        "chuẩn hóa về cùng canvas. Để giảm thời gian, hệ thống dùng **hai "
        "tầng**: tầng đầu chấm nhanh trên một số template đại diện của mỗi "
        "nhãn; tầng hai chỉ chấm đầy đủ cho các nhãn có điểm cao nhất. Các "
        "nhãn không hợp lệ trên biển Việt Nam như `I, J, O, Q, W` bị loại khỏi "
        "danh sách chấm điểm để tránh nhầm với `1` và `0`. Prior số lỗ được "
        "dùng như một bằng chứng bổ sung: nếu số lỗ của ảnh truy vấn khác số "
        "lỗ trung bình của template ứng viên, điểm bị trừ; ngoại lệ được áp "
        "dụng khi ảnh truy vấn không có lỗ còn template có một lỗ, vì nhị phân "
        "có thể làm đứt nét mảnh.",
    )
    add_para(
        doc,
        "Một ký tự chỉ được khẳng định khi điểm cao nhất vượt ngưỡng 0,60 và "
        "khoảng cách top-1/top-2 vượt ngưỡng 0,035. Nếu không, ký tự được giữ "
        "là `?` với trạng thái `UNKNOWN` hoặc `AMBIGUOUS`. Đây là quyết định "
        "thiết kế quan trọng: hệ thống ưu tiên độ chính xác của những ký tự "
        "được khẳng định hơn là lấp đầy chuỗi bằng phỏng đoán.",
    )

    add_h2(doc, "2.7. Hậu xử lý và ràng buộc định dạng")
    add_para(
        doc,
        "Sau khi nhận dạng từng ký tự, hệ thống ghép chuỗi theo thứ tự đọc và "
        "chuẩn hóa về chữ hoa, chỉ giữ chữ số, chữ cái và dấu `?`. Chuỗi được "
        "kiểm tra theo biểu thức chính quy cấu hình:",
    )
    add_code(
        doc,
        "^[0-9]{2}[A-Z]{1,2}[0-9]{4,6}$",
        caption="Quy tắc định dạng biển số được dùng trong cấu hình",
    )
    add_para(
        doc,
        "Quy tắc này mang tính **cấu trúc**, không phải xác minh pháp lý: hai "
        "chữ số đầu là mã tỉnh, tiếp theo là một hoặc hai chữ cái series, sau "
        "đó là bốn đến sáu chữ số. Độ dài chuỗi được giới hạn trong khoảng "
        "7–10. Hệ thống không tự sửa ký tự, không đổi ký tự để chuỗi khớp "
        "regex và không tạo ký tự mới. Nếu chuỗi còn `?` hoặc không khớp quy "
        "tắc, trạng thái được hạ xuống `LOW_CONFIDENCE` hoặc `FORMAT_WARNING` "
        "tương ứng.",
    )
    add_para(
        doc,
        "Một bước rerank theo vị trí được áp dụng sau khi ghép chuỗi. Từ độ "
        "dài chuỗi, hệ thống suy ra kiểu ký tự kỳ vọng tại từng vị trí (chữ "
        "số hoặc chữ cái) và chỉ chọn lại trong danh sách ứng viên template "
        "đã được chấm điểm. Nếu ứng viên đúng kiểu có điểm thấp hơn ngưỡng "
        "hoặc hai ứng viên cùng kiểu quá sát nhau, hệ thống giữ nguyên quyết "
        "định từ chối thay vì ép đổi.",
    )

    add_h2(doc, "2.8. Các độ đo đánh giá")
    add_para(
        doc,
        "Để đánh giá khách quan, báo cáo dùng các độ đo sau. Với ảnh có nhãn "
        "hộp bao, chất lượng phát hiện được đo bằng IoU:",
    )
    add_formula(
        doc,
        "IoU(A, B) = |A ∩ B| / |A ∪ B|",
        "2.6",
    )
    add_para(
        doc,
        "Một hộp dự đoán được coi là đúng nếu IoU với hộp nhãn đạt ít nhất "
        "0,5. Với ảnh không có biển, một dự đoán có hộp hoặc chuỗi được coi "
        "là dương tính giả. Từ đó tính precision và recall:",
    )
    add_formula(
        doc,
        "Precision = TP/(TP + FP),   Recall = TP/(TP + FN)",
        "2.7",
    )
    add_para(
        doc,
        "**PDR** (Plate Detection Rate) là tỷ lệ ảnh có biển được phát hiện "
        "đúng theo IoU ≥ 0,5 trên tổng số ảnh có biển. **CSA** (Character "
        "Segmentation Accuracy) là trung bình theo ảnh của tỷ lệ hộp ký tự dự "
        "đoán ghép được với hộp nhãn ở IoU ≥ 0,5. Với ảnh thật chưa có hộp "
        "nhãn, CSA được thay bằng đại diện theo số lượng: số ký tự dự đoán "
        "khớp với số ký tự của chuỗi nhãn, và được ghi rõ là `count_proxy`.",
    )
    add_para(
        doc,
        "**CA** (Character Accuracy) được tính trên căn chỉnh Levenshtein giữa "
        "chuỗi dự đoán và chuỗi nhãn:",
    )
    add_formula(
        doc,
        "CA = M / (M + S + I + D)",
        "2.8",
    )
    add_para(
        doc,
        "Trong đó M là số ký tự khớp, S là số thay thế, I là số chèn và D là "
        "số xóa. **EPA** (Exact Plate Accuracy) là tỷ lệ ảnh mà chuỗi dự đoán "
        "sau chuẩn hóa trùng hoàn toàn với chuỗi nhãn. Báo cáo tính EPA trên "
        "các ảnh có biển (chỉ số chính) và trên toàn bộ ảnh (theo công thức "
        "của đặc tả), trong đó ảnh không biển chỉ đúng nếu hệ thống không trả "
        "chuỗi.",
    )
    add_para(
        doc,
        "Với các tỷ lệ nhỏ, khoảng tin cậy Wilson 95% được dùng để tránh diễn "
        "giải quá mức một con số điểm. Khoảng tin cậy được tính từ số lần "
        "thành công k trên n lần thử:",
    )
    add_formula(
        doc,
        "CI = (p + z²/(2n) ± z·sqrt(p(1−p)/n + z²/(4n²))) / (1 + z²/n)",
        "2.9",
    )
    add_para(
        doc,
        "Với z ≈ 1,96 cho mức tin cậy 95%. Khoảng tin cậy rộng trên các tập "
        "nhỏ là lý do báo cáo không tuyên bố độ chính xác tổng quát chỉ từ một "
        "vài chục ảnh.",
    )

    add_table(
        doc,
        ["Độ đo", "Ý nghĩa", "Đơn vị", "Ghi chú"],
        [
            ("PDR", "Tỷ lệ phát hiện đúng biển theo IoU ≥ 0,5", "%", "Chỉ ảnh có biển"),
            ("Precision", "TP/(TP+FP), có tính ảnh không biển", "%", "TP/FP/FN/TN"),
            ("Recall", "TP/(TP+FN)", "%", "Bằng PDR khi cùng ngưỡng"),
            ("CSA", "Trung bình tỷ lệ hộp ký tự ghép đúng", "%", "IoU hoặc count_proxy"),
            ("CA", "Tỷ lệ ký tự đúng trên căn chỉnh Levenshtein", "%", "M/(M+S+I+D)"),
            ("EPA", "Tỷ lệ chuỗi trùng hoàn toàn", "%", "Chỉ ảnh có biển"),
            ("Success Rate", "Tỷ lệ trạng thái SUCCESS trên toàn bộ ảnh", "%", "Gồm ảnh không biển"),
            ("Thời gian", "Thời gian xử lý trung bình mỗi ảnh", "ms", "Không gồm load template"),
        ],
        [2.6, 8.4, 1.8, 4.2],
        caption="Các độ đo được sử dụng trong báo cáo",
        font_size=9,
        aligns=["left", "left", "center", "left"],
    )

    add_h2(doc, "2.9. Công nghệ và công cụ sử dụng")
    add_para(
        doc,
        "Hệ thống được phát triển trên Windows 11, sử dụng Python 3.13.6 và "
        "các thư viện mã nguồn mở. Bảng dưới tóm tắt vai trò của từng thành "
        "phần.",
    )
    add_table(
        doc,
        ["Thành phần", "Phiên bản", "Vai trò"],
        [
            ("Python", "3.13.6", "Ngôn ngữ cài đặt toàn bộ hệ thống"),
            ("OpenCV", "4.10.0", "Đọc/ghi ảnh, xử lý ảnh, morphology, contour, warp, matchTemplate"),
            ("NumPy", "2.1.3", "Ma trận, thống kê, tính toán vector"),
            ("Pillow", "11.3.0", "Đọc ảnh WEBP, hỗ trợ hiển thị"),
            ("PyYAML", "6.0.3", "Đọc cấu hình YAML"),
            ("Tkinter", "Theo Python", "Giao diện desktop"),
            ("pytest", "8.3.4", "Kiểm thử tự động"),
            ("python-docx", "1.2.0", "Sinh báo cáo Word"),
            ("matplotlib", "3.11.1", "Vẽ biểu đồ kết quả"),
        ],
        [3.2, 2.4, 11.4],
        caption="Các thư viện và công cụ chính",
        font_size=9,
        aligns=["left", "center", "left"],
    )
    add_para(
        doc,
        "Việc chọn các thư viện này xuất phát từ yêu cầu của đề tài: OpenCV "
        "cung cấp đầy đủ các phép xử lý ảnh cổ điển và Template Matching; "
        "NumPy đảm bảo tính toán ma trận hiệu quả; Tkinter có sẵn trong Python "
        "nên không cần cài thêm giao diện đồ họa; pytest cho phép kiểm thử hồi "
        "quy nhanh. Không có thư viện học máy nào được sử dụng trong pipeline "
        "nhận dạng.",
    )


# ======================================================================
# Chương 3
# ======================================================================
def _add_chapter3(doc: Document, data: dict[str, Any]) -> None:
    add_h1(doc, "CHƯƠNG 3. PHÂN TÍCH VÀ THIẾT KẾ HỆ THỐNG")

    add_h2(doc, "3.1. Yêu cầu chức năng và phi chức năng")
    add_para(
        doc,
        "Hệ thống được thiết kế cho một người dùng cá nhân trên máy tính để "
        "bàn, có thể chọn ảnh, chạy nhận dạng, quan sát các ảnh trung gian và "
        "lưu kết quả. Các yêu cầu chức năng chính được liệt kê dưới đây.",
    )
    add_table(
        doc,
        ["Mã", "Yêu cầu chức năng", "Tiêu chí chấp nhận"],
        [
            ("F1", "Chọn và đọc ảnh JPG/JPEG/PNG/WEBP", "Ảnh hợp lệ được hiển thị; ảnh lỗi có thông báo"),
            ("F2", "Tiền xử lý và phát hiện vùng biển", "Có ảnh cạnh, nhị phân, danh sách ứng viên"),
            ("F3", "Cắt và hiệu chỉnh phối cảnh", "Ảnh biển thẳng hoặc crop dự phòng"),
            ("F4", "Phân đoạn ký tự một dòng/hai dòng", "Danh sách hộp ký tự theo thứ tự đọc"),
            ("F5", "Nhận dạng bằng Template Matching", "Mỗi ký tự có nhãn, điểm, margin, trạng thái"),
            ("F6", "Hậu xử lý và kiểm tra định dạng", "Chuỗi chuẩn hóa, cảnh báo, trạng thái"),
            ("F7", "Hiển thị và lưu kết quả", "Ảnh trung gian, CSV, ảnh debug"),
            ("F8", "Chạy hàng loạt và đánh giá", "Sinh CSV/JSON/Markdown từ nhãn"),
        ],
        [1.2, 7.4, 8.4],
        caption="Yêu cầu chức năng của hệ thống",
        font_size=9,
        aligns=["center", "left", "left"],
    )
    add_table(
        doc,
        ["Mã", "Yêu cầu phi chức năng", "Cách đáp ứng"],
        [
            ("N1", "Không dùng học máy/học sâu/OCR học sẵn", "Chỉ OpenCV và template thủ công"),
            ("N2", "Cấu hình tập trung, dễ tái lập", "Toàn bộ tham số trong config.yaml"),
            ("N3", "Có thể kiểm thử tự động", "78 bài pytest, chạy trong khoảng 12 giây"),
            ("N4", "Thời gian tương tác hợp lý", "Trung bình 1,36–1,86 giây/ảnh trên máy đo"),
            ("N5", "Kết quả trung thực, không đoán bừa", "Giữ `?`, từ chối khi điểm/margin thấp"),
            ("N6", "Chạy trên Windows không cần cài đặt phức tạp", "Python + requirements, có file .bat"),
        ],
        [1.2, 8.0, 7.8],
        caption="Yêu cầu phi chức năng của hệ thống",
        font_size=9,
        aligns=["center", "left", "left"],
    )

    add_h2(doc, "3.2. Kiến trúc tổng thể")
    add_para(
        doc,
        "Hệ thống được tổ chức theo kiến trúc hướng pipeline: mỗi công đoạn "
        "nhận kết quả của công đoạn trước, bổ sung thông tin và chuyển tiếp. "
        "Các module không phụ thuộc vào giao diện; giao diện Tkinter và CLI "
        "chỉ gọi lớp `LicensePlateRecognizer` trong `src/pipeline.py`. Nhờ "
        "vậy, cùng một pipeline có thể được dùng cho ảnh đơn, chạy hàng loạt "
        "và đánh giá tự động.",
    )
    add_figure(
        doc,
        ASSETS / "pipeline.png",
        "Sơ đồ pipeline tám công đoạn từ ảnh đầu vào đến kết quả có cấu trúc",
        width_cm=16.2,
    )
    add_para(
        doc,
        "Điểm đáng chú ý là pipeline không dừng ở ứng viên biển đầu tiên. "
        "Nó giữ tối đa tám ứng viên tốt nhất, thử cắt – phân đoạn – nhận dạng "
        "lần lượt và chọn kết quả có trạng thái ưu tiên cao nhất. Cách làm này "
        "tăng thời gian xử lý nhưng cải thiện độ bền khi ứng viên xếp hạng đầu "
        "là viền biển hoặc vùng nền.",
    )

    add_h2(doc, "3.3. Thiết kế các module")
    add_para(
        doc,
        "Mã nguồn được chia thành các module theo trách nhiệm. Bảng dưới liệt "
        "kê số dòng thực tế của từng tệp tại thời điểm lập báo cáo.",
    )
    responsibilities = {
        "src/config.py": "Đọc/kiểm tra YAML, dataclass cấu hình",
        "src/io_utils.py": "Đọc/ghi ảnh, chuẩn hóa đường dẫn, IoU, hình học",
        "src/preprocessing.py": "Grayscale, blur, CLAHE, Canny, Otsu/adaptive",
        "src/plate_detection.py": "Sinh, lọc, xếp hạng ứng viên biển",
        "src/plate_rectification.py": "Cắt ROI, tìm tứ giác, warp, deskew",
        "src/character_segmentation.py": "Tách dòng, tách ký tự, lọc hình học",
        "src/character_recognition.py": "Chuẩn hóa ký tự, template, chấm điểm",
        "src/postprocessing.py": "Ghép chuỗi, regex, rerank, trạng thái",
        "src/evaluation.py": "PDR/CSA/CA/EPA, CSV/JSON/Markdown",
        "src/pipeline.py": "Điều phối, thử ứng viên, debug, kết quả",
        "src/__init__.py": "Đánh dấu package Python",
        "ui/app.py": "Giao diện Tkinter",
        "main.py": "CLI, batch, đánh giá",
    }
    code_rows = [
        (name, str(lines), responsibilities.get(name, ""))
        for name, lines in data["code_lines"]
    ]
    total_lines = sum(lines for _, lines in data["code_lines"])
    code_rows.append(("Tổng", str(total_lines), "Toàn bộ mã nguồn chính"))
    add_table(
        doc,
        ["Tệp", "Số dòng", "Trách nhiệm chính"],
        code_rows,
        [5.0, 1.8, 10.2],
        caption="Phân chia module và số dòng mã nguồn",
        font_size=8.8,
        aligns=["left", "center", "left"],
    )
    add_para(
        doc,
        "Cách chia này giúp kiểm thử từng công đoạn độc lập. Ví dụ, có thể "
        "kiểm tra `segment_characters` trên một ảnh biển đã cắt sẵn mà không "
        "cần chạy phát hiện; hoặc kiểm tra `validate_format` với các chuỗi "
        "biên mà không cần ảnh. Nhờ đó, bộ kiểm thử chạy nhanh và ít phụ thuộc "
        "vào dữ liệu lớn.",
    )

    add_h2(doc, "3.4. Luồng dữ liệu và quy ước trạng thái")
    add_para(
        doc,
        "Mỗi lần chạy tạo ra một đối tượng `RecognitionResult` chứa: đường "
        "dẫn ảnh, kích thước ảnh, ứng viên được chọn, ảnh biển đã hiệu chỉnh, "
        "kết quả phân đoạn, danh sách dự đoán ký tự, kết quả văn bản, thời "
        "gian từng công đoạn, cảnh báo và danh sách các lần thử ứng viên. "
        "Cấu trúc này vừa đủ để hiển thị trên giao diện, vừa đủ để ghi CSV và "
        "tái tạo chẩn đoán.",
    )
    add_table(
        doc,
        ["Trạng thái", "Ý nghĩa", "Khi nào xảy ra"],
        [
            ("SUCCESS", "Nhận dạng thành công, chuỗi hợp lệ", "Tất cả ký tự OK, điểm/margin đạt, regex khớp"),
            ("FORMAT_WARNING", "Có chuỗi nhưng sai quy tắc", "Ký tự OK nhưng chuỗi không khớp regex/độ dài"),
            ("LOW_CONFIDENCE", "Không đủ tin cậy", "Có ký tự `?`, phân đoạn không OK, điểm thấp"),
            ("PLATE_NOT_FOUND", "Không tìm thấy biển", "Không có ứng viên hình học đủ điều kiện"),
            ("INVALID_IMAGE", "Ảnh không hợp lệ", "Không đọc được, quá nhỏ, quá lớn, sai kênh"),
            ("CONFIG_ERROR", "Lỗi cấu hình", "Template thiếu, tham số không hợp lệ"),
        ],
        [3.4, 5.4, 8.2],
        caption="Quy ước trạng thái của hệ thống",
        font_size=9,
        aligns=["left", "left", "left"],
    )
    add_para(
        doc,
        "Thứ tự ưu tiên khi chọn giữa các lần thử là `SUCCESS` > "
        "`FORMAT_WARNING` > `LOW_CONFIDENCE` > `PLATE_NOT_FOUND` > "
        "`INVALID_IMAGE` > `CONFIG_ERROR`. Nếu nhiều lần thử cùng trạng thái, "
        "hệ thống ưu tiên lần thử có điểm trung bình cao hơn và số ký tự hợp "
        "lệ nhiều hơn. Quy tắc này tránh việc một ứng viên xấu nhưng tình cờ "
        "tạo chuỗi ngắn lại được chọn thay cho ứng viên tốt.",
    )

    add_h2(doc, "3.5. Thiết kế cấu hình tập trung")
    add_para(
        doc,
        "Toàn bộ tham số thuật toán nằm trong `config.yaml`. Không có ngưỡng "
        "nào được viết cứng trong mã nguồn. Cách làm này cho phép tái lập thí "
        "nghiệm, so sánh cấu hình và tránh sửa nhiều nơi khi tinh chỉnh. Bảng "
        "dưới tóm tắt các nhóm cấu hình chính.",
    )
    add_table(
        doc,
        ["Nhóm", "Tham số tiêu biểu", "Mục đích"],
        [
            ("image", "max_side=1600, min_side=40", "Giới hạn kích thước và kiểm tra ảnh"),
            ("preprocessing", "blur, CLAHE, Canny 60/180, Otsu", "Tạo ảnh xám, cạnh, nhị phân"),
            ("detection", "kernel, area/ratio, score, top_k, max_candidates", "Sinh và xếp hạng ứng viên"),
            ("rectification", "padding 0,10, epsilon 0,02, deskew 2,5–18°", "Cắt và hiệu chỉnh phối cảnh"),
            ("segmentation", "plate_width=640, expected_chars=[7,9]", "Tách dòng, tách ký tự"),
            ("recognition", "32×48, TM_CCOEFF_NORMED, blur σ=2,0", "Chuẩn hóa và so khớp"),
            ("postprocessing", "regex, position_constraints, ngưỡng tin cậy", "Ghép chuỗi, rerank, trạng thái"),
            ("pipeline", "max_candidates_to_try=8, save_debug", "Điều phối và xuất debug"),
            ("evaluation", "iou_threshold=0,5", "Đánh giá"),
        ],
        [3.2, 8.2, 5.6],
        caption="Các nhóm cấu hình chính",
        font_size=8.8,
        aligns=["left", "left", "left"],
    )
    add_para(
        doc,
        "Cấu hình được kiểm tra khi khởi động: các giá trị âm, kernel chẵn, "
        "ngưỡng ngoài khoảng hợp lệ hoặc thiếu template bắt buộc sẽ tạo lỗi "
        "cấu hình thay vì chạy với giá trị mặc định ngầm. Điều này giúp phát "
        "hiện sớm các sửa đổi sai trong quá trình thử nghiệm.",
    )

    add_h2(doc, "3.6. Thiết kế dữ liệu vào và kết quả ra")
    add_para(
        doc,
        "Dữ liệu tổng hợp có nhãn gồm tên ảnh, chuỗi ground truth, loại biển, "
        "split, điều kiện, ghi chú, hộp bao biển (x1, y1, x2, y2) và danh sách "
        "hộp bao ký tự. Dữ liệu thật chỉ có tên ảnh, chuỗi, loại biển, split, "
        "điều kiện và ghi chú; không có hộp bao. Sự khác biệt này quyết định "
        "cách tính PDR/CSA trên hai loại dữ liệu.",
    )
    add_para(
        doc,
        "Kết quả đánh giá được ghi ra CSV theo từng ảnh, JSON tổng hợp và "
        "Markdown để đọc nhanh. CSV có 30 cột, chia thành bốn nhóm: thông tin "
        "ảnh và nhãn; kết quả phát hiện; kết quả ký tự và phân đoạn; thời gian "
        "và thông điệp. Các cột thời gian gồm `preprocess_ms`, `detection_ms`, "
        "`rectification_ms`, `segmentation_ms`, `recognition_ms`, "
        "`postprocessing_ms` và `total_time_ms`.",
    )
    add_table(
        doc,
        ["Nhóm cột", "Ví dụ", "Ý nghĩa"],
        [
            ("Ảnh và nhãn", "image_name, ground_truth, condition, has_gt_plate", "Định danh và điều kiện"),
            ("Phát hiện", "status, detected_text, predicted_plate, detection_correct, detection_iou", "Kết quả và IoU"),
            ("Ký tự", "exact_match, char_correct, char_substitutions, char_accuracy", "CA/EPA"),
            ("Phân đoạn", "seg_gt_count, seg_pred_count, seg_matched, segmentation_method", "CSA"),
            ("Thời gian", "preprocess_ms … total_time_ms", "Chi phí từng công đoạn"),
            ("Khác", "format_valid, mean_score, message", "Chẩn đoán"),
        ],
        [3.4, 8.4, 5.2],
        caption="Cấu trúc tệp kết quả CSV",
        font_size=8.8,
        aligns=["left", "left", "left"],
    )

    add_h2(doc, "3.7. Thiết kế giao diện và CLI")
    add_para(
        doc,
        "Giao diện Tkinter được thiết kế cho thao tác một ảnh: nút chọn ảnh, "
        "nút nhận dạng, vùng hiển thị ảnh gốc và ảnh biển đã cắt, vùng hiển "
        "thị nhị phân và dải ký tự, khu vực kết quả với chuỗi, trạng thái, "
        "điểm trung bình và thời gian. Người dùng có thể lưu ảnh debug và mở "
        "thư mục kết quả. Giao diện không chứa thuật toán; mọi xử lý được gọi "
        "qua pipeline để đảm bảo cùng một kết quả với CLI.",
    )
    add_para(
        doc,
        "CLI trong `main.py` hỗ trợ ba chế độ: nhận dạng một ảnh, nhận dạng "
        "một thư mục và đánh giá một split có nhãn. Chế độ đánh giá đọc "
        "`data/labels.csv`, chạy pipeline, tính các độ đo và ghi CSV/JSON. "
        "Các tệp `.bat` giúp người dùng Windows chạy giao diện, chạy batch và "
        "chạy đánh giá mà không cần nhớ lệnh.",
    )

    add_h2(doc, "3.8. Thiết kế kiểm thử")
    add_para(
        doc,
        "Bộ kiểm thử gồm 78 bài, chia theo module. Mục tiêu là bảo vệ các "
        "hành vi quan trọng: xử lý ảnh lỗi, lọc ứng viên, ánh xạ tọa độ, quy "
        "tắc phân đoạn, ngưỡng từ chối ký tự, regex, tính CA/EPA và pipeline "
        "end-to-end. Bảng dưới là số bài kiểm thử theo tệp.",
    )
    test_counts = [
        ("tests/test_config.py", 7),
        ("tests/test_detection.py", 7),
        ("tests/test_evaluation.py", 9),
        ("tests/test_pipeline.py", 8),
        ("tests/test_postprocessing.py", 16),
        ("tests/test_preprocessing.py", 7),
        ("tests/test_recognition.py", 12),
        ("tests/test_rectification.py", 5),
        ("tests/test_segmentation.py", 6),
        ("tests/test_ui.py", 1),
        ("Tổng", 78),
    ]
    add_table(
        doc,
        ["Tệp kiểm thử", "Số bài", "Nội dung chính"],
        [
            ("tests/test_config.py", "7", "Đọc YAML, kiểm tra giá trị, lỗi cấu hình"),
            ("tests/test_detection.py", "7", "Ứng viên, xếp hạng, chọn top-k"),
            ("tests/test_evaluation.py", "9", "IoU, Levenshtein, PDR/CSA/CA/EPA"),
            ("tests/test_pipeline.py", "8", "End-to-end, trạng thái, debug, batch"),
            ("tests/test_postprocessing.py", "16", "Regex, rerank, trạng thái, không đoán"),
            ("tests/test_preprocessing.py", "7", "Blur, CLAHE, Canny, Otsu, ảnh lỗi"),
            ("tests/test_recognition.py", "12", "Chuẩn hóa, template, từ chối, hole prior"),
            ("tests/test_rectification.py", "5", "Crop, warp, deskew, ánh xạ ngược"),
            ("tests/test_segmentation.py", "6", "Một dòng, hai dòng, 10 ký tự, thứ tự"),
            ("tests/test_ui.py", "1", "Smoke test giao diện trong tiến trình riêng"),
            ("Tổng", "78", "Chạy bằng pytest"),
        ],
        [5.0, 1.8, 10.2],
        caption="Phân bố bài kiểm thử theo module",
        font_size=8.8,
        aligns=["left", "center", "left"],
    )
    add_para(
        doc,
        "Kết quả chạy kiểm thử tại thời điểm lập báo cáo là **78 passed** "
        "trong 28,13 giây trên máy đo. Con số này chỉ xác nhận các hành vi đã "
        "được kiểm thử, không thay thế đánh giá độ chính xác trên dữ liệu.",
    )

    add_h2(doc, "3.9. Các quyết định thiết kế quan trọng")
    add_para(
        doc,
        "Một số quyết định dưới đây ảnh hưởng trực tiếp đến kết quả và được "
        "giải thích để người đọc có thể đánh giá tính hợp lý.",
    )
    add_bullets(
        doc,
        [
            "**Không đoán ký tự:** mọi ký tự không đạt ngưỡng đều thành `?`. "
            "Điều này làm EPA thấp hơn so với việc điền bừa, nhưng trung thực "
            "và an toàn hơn.",
            "**Hai nguồn ứng viên:** ứng viên hình học và ứng viên cụm ký tự "
            "được giữ riêng vì cùng vị trí nhưng chất lượng nhị phân khác "
            "nhau. Gộp chúng có thể làm mất phương án phân đoạn tốt.",
            "**Bbox hint:** khi ứng viên cụm ký tự nằm trong một ứng viên hình "
            "học, hộp báo cáo được mượn từ ứng viên hình học để IoU công bằng "
            "hơn; vùng cắt cho nhận dạng vẫn giữ nguyên.",
            "**Biển 10 ký tự:** chỉ chấp nhận khi hai dòng cân bằng 5/5. Quy "
            "tắc này sửa được lỗi tách 4/6 trên `5.webp` và vẫn nhận `8.jpg`.",
            "**Rerank theo vị trí:** chỉ chọn trong các ứng viên đã chấm điểm, "
            "không sinh ký tự mới; nếu không chắc, giữ `?`.",
            "**Cấu hình tập trung:** mọi ngưỡng nằm trong YAML, giúp tái lập "
            "và so sánh công bằng giữa các lần thử.",
        ],
    )


# ======================================================================
# Chương 4
# ======================================================================
def _add_chapter4(doc: Document, data: dict[str, Any]) -> None:
    add_h1(doc, "CHƯƠNG 4. TRIỂN KHAI HỆ THỐNG")

    add_h2(doc, "4.1. Môi trường và cấu trúc dự án")
    add_para(
        doc,
        "Dự án được đặt trong thư mục gốc của kho mã nguồn, chạy trên Windows 11 với "
        "Python 3.13.6. Cấu trúc thư mục được tổ chức như sau:",
    )
    add_code(
        doc,
        ".\n"
        "├── config.yaml              # toàn bộ tham số thuật toán\n"
        "├── main.py                  # CLI: ảnh đơn, batch, đánh giá\n"
        "├── run_ui.bat               # mở giao diện Tkinter\n"
        "├── run_user_batch.bat       # chạy batch ảnh thật\n"
        "├── run_user_eval.bat        # chạy đánh giá split user\n"
        "├── requirements.txt\n"
        "├── src/\n"
        "│   ├── config.py\n"
        "│   ├── io_utils.py\n"
        "│   ├── preprocessing.py\n"
        "│   ├── plate_detection.py\n"
        "│   ├── plate_rectification.py\n"
        "│   ├── character_segmentation.py\n"
        "│   ├── character_recognition.py\n"
        "│   ├── postprocessing.py\n"
        "│   ├── evaluation.py\n"
        "│   └── pipeline.py\n"
        "├── ui/app.py\n"
        "├── data/\n"
        "│   ├── user_images/         # 14 ảnh thật\n"
        "│   ├── samples/             # 52 ảnh tổng hợp\n"
        "│   ├── templates/           # 36 nhãn × 45 tệp\n"
        "│   ├── labels.csv\n"
        "│   └── user_labels.csv\n"
        "├── tests/                   # 78 bài pytest\n"
        "├── tools/                   # sinh dữ liệu, template, báo cáo\n"
        "├── results/                 # CSV, JSON, ảnh debug\n"
        "└── reports/                 # báo cáo và hình",
        caption="Cấu trúc thư mục chính của dự án",
    )
    add_para(
        doc,
        "Các thư viện được khóa phiên bản trong `requirements.txt`. Bộ template "
        "và dữ liệu tổng hợp được sinh bằng công cụ trong `tools/`, không được "
        "chỉnh sửa thủ công từng ảnh. Điều này giúp tái lập bộ dữ liệu và "
        "template từ mã nguồn.",
    )

    add_h2(doc, "4.2. Đọc ảnh và tiền xử lý")
    add_para(
        doc,
        "`preprocess` kiểm tra định dạng, kích thước và số kênh ảnh. Ảnh nhỏ "
        "hơn 40 px ở cạnh ngắn hoặc lớn hơn 60 megapixel bị từ chối với lỗi "
        "`INVALID_IMAGE`. Ảnh có cạnh dài vượt 1.600 px được thu nhỏ bằng nội "
        "suy `INTER_AREA`; hệ số scale được lưu lại để ánh xạ tọa độ về ảnh "
        "gốc. Ảnh 4 kênh được chuyển về BGR; ảnh xám được chuyển về BGR để "
        "thống nhất kiểu dữ liệu.",
    )
    add_para(
        doc,
        "Sau khi chuyển xám, ảnh được làm mờ Gaussian với kernel 5×5. Nếu "
        "`use_clahe` bật, CLAHE được áp dụng với clip limit 2,0 và lưới 8×8; "
        "nếu tắt, hệ thống vẫn tính độ lệch chuẩn của ảnh xám và phát cảnh "
        "báo khi tương phản thấp. Cạnh được tính bằng Canny với ngưỡng 60/180. "
        "Đồng thời, hệ thống tính hai phiên bản nhị phân: Otsu và adaptive "
        "Gaussian với block 11, hằng số 2. Cả hai được giữ lại để các công "
        "đoạn sau lựa chọn.",
    )
    add_figure(
        doc,
        ASSETS / "preprocess_panel.png",
        "Các ảnh trung gian của công đoạn tiền xử lý trên một ảnh thật",
        width_cm=15.6,
    )
    add_para(
        doc,
        "Hình trên cho thấy ảnh gốc, ảnh xám, ảnh cạnh và hai phiên bản nhị "
        "phân. Trên ảnh có nền sáng và biển tối, việc giữ cả hai cực tính "
        "giúp công đoạn phân đoạn chọn được phiên bản có mực ký tự là "
        "foreground. Đây là lý do hệ thống không cố định một cực tính duy nhất.",
    )

    add_h2(doc, "4.3. Phát hiện vùng biển số")
    add_para(
        doc,
        "Công đoạn phát hiện sinh nhiều bản đồ nhị phân từ cạnh và từ vùng mực, "
        "sau đó trích xuất contour và tạo ứng viên. Các kernel đóng chính là "
        "17×3, 25×5 và 15×7; ngoài ra có một bước đóng dọc 3×7 để nối hai dòng "
        "của biển vuông. Với nguồn mực, hệ thống lấy nghịch đảo của ảnh nhị "
        "phân adaptive, xóa các thành phần chạm biên và các đường kẻ dài, rồi "
        "đóng với kernel nhỏ để nối nét đứt.",
    )
    add_para(
        doc,
        "Mỗi contour được chuyển thành ứng viên sau khi kiểm tra các điều kiện "
        "hình học: diện tích tương đối nằm trong khoảng 0,0008–0,95; tỷ lệ "
        "rộng/cao nằm trong khoảng 1,10–7,0; độ đặc tối thiểu 0,30; mật độ "
        "cạnh nằm trong khoảng 0,02–0,40. Các ngưỡng này được chọn đủ rộng để "
        "bao phủ biển một dòng và hai dòng, nhưng vẫn loại được các vùng nền "
        "trống hoặc vật thể có hình dạng bất thường.",
    )
    add_para(
        doc,
        "Điểm của một ứng viên là tổ hợp có trọng số của bốn đặc trưng hình "
        "học và một đặc trưng giống văn bản:",
    )
    add_formula(
        doc,
        "S = (1 − w_t)·(0,35·S_ratio + 0,15·S_area + 0,30·S_edge + 0,15·S_fill) + w_t·S_text",
        "4.1",
    )
    add_para(
        doc,
        "Trong cấu hình cuối, `w_t = 0,20`. Điểm giống văn bản được ước lượng "
        "từ số thành phần giống ký tự trong vùng ứng viên. Ứng viên phải có "
        "`S_text ≥ 0,15` và tổng điểm `S ≥ 0,45` mới được coi là hợp lệ. Các "
        "ứng viên sau đó được hợp nhất nếu IoU vượt 0,45, sắp xếp giảm dần "
        "theo điểm và giữ tối đa 25 ứng viên; pipeline chỉ thử tối đa 8 ứng "
        "viên tốt nhất.",
    )
    add_para(
        doc,
        "Ngoài ứng viên hình học, hệ thống sinh **ứng viên cụm ký tự** bằng "
        "cách gom các thành phần liên thông giống ký tự theo hàng và theo "
        "khoảng cách. Nguồn này hữu ích khi viền biển bị mất hoặc biển được "
        "chụp cận cảnh đến mức morphology không tạo được contour kín. Hai "
        "nguồn ứng viên được giữ riêng vì cùng vị trí nhưng ảnh nhị phân có "
        "thể khác nhau; gộp chúng có thể làm mất phương án phân đoạn tốt.",
    )
    add_para(
        doc,
        "Khi một ứng viên cụm ký tự nằm gần như hoàn toàn trong một ứng viên "
        "hình học, hệ thống có thể mượn hộp bao hình học để báo cáo vị trí. "
        "Điều kiện là mức chứa tối thiểu 0,80, tỷ lệ diện tích không vượt 4,0 "
        "và điểm ứng viên hình học tối thiểu 0,50. Cơ chế này chỉ đổi tọa độ "
        "báo cáo; vùng cắt đưa vào nhận dạng vẫn là vùng cụm ký tự. Nhờ đó, "
        "chỉ số PDR phản ánh đúng hơn vị trí biển mà không hy sinh chất lượng "
        "nhị phân của ký tự.",
    )
    add_figure(
        doc,
        ASSETS / "candidates.png",
        "Các ứng viên biển được sinh và xếp hạng trên một ảnh thật",
        width_cm=11.4,
    )

    add_h2(doc, "4.4. Cắt và hiệu chỉnh phối cảnh")
    add_para(
        doc,
        "Vùng ứng viên được mở rộng thêm 10% theo cả chiều rộng và chiều cao "
        "trước khi cắt, nhằm hạn chế cắt mất viền hoặc góc biển khi hộp bao "
        "sát vào ký tự. Cần lưu ý: tham số `vertical_padding_ratio` có trong "
        "`config.yaml` nhưng hàm `rectify_plate` hiện chỉ truyền `padding_ratio` "
        "vào `crop_candidate`; vì vậy không được mô tả hệ thống là đã dùng "
        "padding dọc 6% riêng biệt. Đây là một điểm cần thống nhất giữa cấu "
        "hình và mã nguồn trong phiên bản sau.",
    )
    add_para(
        doc,
        "Trong vùng cắt, hệ thống tìm contour lớn nhất, kiểm tra diện tích "
        "tối thiểu 10% vùng cắt, xấp xỉ đa giác với epsilon bằng 2% chu vi và "
        "yêu cầu tứ giác lồi có bốn đỉnh. Nếu tứ giác có diện tích ít nhất "
        "45% diện tích vùng cắt, hệ thống sắp xếp bốn góc và gọi "
        "`getPerspectiveTransform` để đưa biển về hình chữ nhật. Kích thước "
        "đầu ra được tính từ độ dài các cạnh, có giới hạn để tránh ảnh quá "
        "lớn hoặc tỷ lệ bất thường.",
    )
    add_para(
        doc,
        "Nếu không tìm được tứ giác, hệ thống dùng `minAreaRect` để ước lượng "
        "góc xoay. Góc nhỏ hơn 2,5° được coi là không đáng kể; góc lớn hơn "
        "18° bị coi là quá lớn để xoay an toàn. Trong khoảng 2,5°–18°, ảnh "
        "được xoay bằng `warpAffine` với biên replication. Nếu vẫn thất bại, "
        "hệ thống giữ nguyên vùng cắt theo hộp bao và ghi cảnh báo. Ma trận "
        "thuận và nghịch trong cả ba trường hợp đều được lưu để ánh xạ tọa độ "
        "ký tự ngược về ảnh gốc.",
    )

    add_h2(doc, "4.5. Phân đoạn ký tự")
    add_para(
        doc,
        "Ảnh biển được thu về chiều rộng 640 px, chuyển xám, áp dụng CLAHE, "
        "làm mờ Gaussian 3×3. Hệ thống tính Otsu và nhiều phiên bản adaptive "
        "với các kích thước block khác nhau, sau đó thử cả hai cực tính. Mỗi "
        "phiên bản được kiểm tra tỷ lệ mực foreground; nếu quá thấp hoặc quá "
        "cao, phiên bản đó bị loại. Viền biển, ốc vít và các đốm nhiễu nhỏ "
        "được xóa bằng thành phần liên thông và các quy tắc hình học.",
    )
    add_para(
        doc,
        "Việc tách dòng ưu tiên projection ngang. Nếu projection chỉ cho một "
        "dải trong khi ảnh có dấu hiệu hai dòng, hệ thống dùng fallback bằng "
        "connected components: gom các thành phần theo tâm dọc, kiểm tra độ "
        "chồng ngang và độ chồng dọc, rồi tạo lại các dải dòng. Fallback này "
        "giúp xử lý các biển hai dòng bị dính hoặc chụp cận cảnh.",
    )
    add_para(
        doc,
        "Trong mỗi dòng, contour được tìm trên ảnh đã đóng nhỏ 2×2. Các hộp "
        "được lọc theo chiều cao tương đối (0,42–1,02 lần chiều cao dòng), "
        "chiều rộng (0,008–0,24 lần chiều rộng biển), diện tích tối thiểu và "
        "độ đặc tối thiểu. Các mảnh nhỏ cách nhau không quá 2 px được gộp. "
        "Hộp quá rộng được tách tại điểm thắt của projection dọc; nếu không có "
        "điểm thắt rõ nhưng hộp rộng ít nhất 1,6 lần chiều rộng trung vị, hệ "
        "thống vẫn tách tại vị trí projection thấp nhất quanh tâm. Các mảnh "
        "viền hoặc ốc vít ở mép bị loại nếu chiều cao hoặc chiều rộng bất "
        "thường so với trung vị của dòng.",
    )
    add_para(
        doc,
        "Độ hợp lý của toàn bộ phương án phân đoạn được tính bằng:",
    )
    add_formula(
        doc,
        "S_seg = 0,50·S_count + 0,25·S_height + 0,15·S_row + 0,10·(1 − f_edge)",
        "4.2",
    )
    add_para(
        doc,
        "Trong đó `S_count` bằng 1 nếu số ký tự nằm trong khoảng 7–9 hoặc là "
        "biển 10 ký tự cân bằng; `S_height` phản ánh độ đồng đều chiều cao; "
        "`S_row` kiểm tra cấu trúc 3–4 ký tự dòng trên và 4–5 ký tự dòng dưới; "
        "`f_edge` là tỷ lệ hộp chạm mép biển. Phương án có điểm cao nhất được "
        "chọn, với ưu tiên nhẹ cho Otsu khi điểm xấp xỉ nhau.",
    )
    add_para(
        doc,
        "Quy tắc chấp nhận số ký tự là 7–9. Biển 10 ký tự chỉ được chấp nhận "
        "khi có đúng hai dòng và hai dòng có cùng số ký tự, mỗi dòng ít nhất "
        "5 ký tự. Quy tắc này được thêm sau khi quan sát trường hợp `5.webp` "
        "bị tách thành 4/6 do một mảnh nhiễu ở mép; đồng thời vẫn cho phép "
        "`8.jpg` có 5/5. Nếu dòng dưới có ít hơn 4 ký tự, trạng thái phân đoạn "
        "bị hạ xuống `IMPLAUSIBLE`.",
    )
    add_figure(
        doc,
        ASSETS / "segmentation_panel.png",
        "Quá trình tách dòng và tách ký tự trên biển hai dòng",
        width_cm=15.2,
    )

    add_h2(doc, "4.6. Sinh template và nhận dạng ký tự")
    tc = data["template_counts"]
    raw_text = f"{tc['raw']:,}".replace(",", ".")
    retained_text = f"{tc['retained']:,}".replace(",", ".")
    full_text = f"{tc['full']:,}".replace(",", ".")
    add_para(
        doc,
        f"Bộ template hiện có **{tc['labels']} nhãn** (10 chữ số và 26 chữ cái), "
        f"mỗi nhãn {tc['files_per_label_mode']} tệp, tương ứng "
        f"**{raw_text} template thô**. Sau khi loại các ảnh gần trùng theo "
        f"ngưỡng khác biệt 0,005, còn **{retained_text} template**. Hệ thống "
        f"thêm {tc['open_top']} biến thể chữ `4` hở đỉnh được tạo thủ công, "
        f"nâng tổng số template được chấm điểm lên **{full_text}**. Bộ "
        f"template thô dùng cho tầng chấm nhanh gồm **{tc['coarse']}** mẫu "
        f"(6 mẫu mỗi nhãn).",
    )
    add_para(
        doc,
        "Template được sinh từ 15 font khác nhau, gồm các font đậm, thường, "
        "hẹp và có chân. Bộ font sinh template được chọn khác với bốn font "
        "dùng để sinh ảnh tổng hợp (Calibri, Verdana, Times New Roman, "
        "Trebuchet) nhằm giảm nguy cơ template khớp đúng font của tập kiểm "
        "thử. Đây là biện pháp phòng ngừa thiên lệch, không phải bảo đảm tuyệt "
        "đối vì các font có thể chia sẻ nhiều nét giống nhau.",
    )
    add_para(
        doc,
        "Mỗi ký tự được cắt sát hộp mực, thêm padding 2 px và kéo giãn về "
        "canvas 32×48 theo kiểu `stretch`. Việc kéo giãn làm mất tỷ lệ riêng "
        "của từng ký tự nhưng giảm mạnh ảnh hưởng của độ dày nét và sự khác "
        "biệt font. Ảnh được nhị phân hóa lại sau khi resize để giữ biên nét "
        "sắc. Trước khi tính tương quan, cả ảnh truy vấn và template được làm "
        "mờ Gaussian với σ = 2,0.",
    )
    add_para(
        doc,
        "Nhận dạng dùng hai tầng. Tầng một chấm điểm nhanh trên 6 template đại "
        "diện của mỗi nhãn, giữ lại 6 nhãn có điểm cao nhất. Tầng hai chấm đầy "
        "đủ trên toàn bộ template của các nhãn đó. Các nhãn `I, J, O, Q, W` bị "
        "loại khỏi danh sách chấm điểm vì không hợp lệ trên biển Việt Nam. "
        "Sau khi có điểm, prior số lỗ được áp dụng: nếu số lỗ của ảnh truy vấn "
        "khác số lỗ phổ biến của nhãn, điểm bị trừ 0,20; ngoại lệ là trường "
        "hợp ảnh truy vấn không có lỗ còn template có một lỗ, vì nhị phân có "
        "thể làm đứt nét mảnh.",
    )
    add_figure(
        doc,
        ASSETS / "template_grid.png",
        "Một phần bộ template ký tự được sinh từ nhiều font",
        width_cm=15.0,
    )
    add_para(
        doc,
        "Ký tự chỉ được khẳng định khi điểm cao nhất đạt 0,60 và margin "
        "top-1/top-2 đạt 0,035. Nếu không, ký tự được trả về `?` với trạng "
        "thái `UNKNOWN` hoặc `AMBIGUOUS`. Cơ chế từ chối này là trung tâm của "
        "triết lý thiết kế: thà thiếu ký tự còn hơn khẳng định sai.",
    )

    add_h2(doc, "4.7. Hậu xử lý chuỗi")
    add_para(
        doc,
        "Chuỗi được ghép từ danh sách dự đoán theo thứ tự đọc, giữ nguyên vị "
        "trí `?`. Hệ thống kiểm tra độ dài 7–10, tập ký tự `[A-Z0-9?]`, sự "
        "hiện diện của `?`, khớp regex `^[0-9]{2}[A-Z]{1,2}[0-9]{4,6}$`, tập "
        "chữ cái series hợp lệ và mã tỉnh 01–99. Các kiểm tra này không sửa "
        "chuỗi; chúng chỉ tạo danh sách vấn đề và quyết định trạng thái.",
    )
    add_para(
        doc,
        "Rerank theo vị trí suy ra kiểu ký tự kỳ vọng từ độ dài chuỗi. Với "
        "tổng số ký tự từ 7 đến 10, hệ thống thử hai giả thuyết: series một "
        "chữ cái hoặc hai chữ cái, chọn giả thuyết có ít xung đột kiểu nhất. "
        "Tại mỗi vị trí, nếu dự đoán hiện tại sai kiểu, hệ thống chỉ chọn lại "
        "trong danh sách ứng viên đã được chấm điểm, với điều kiện điểm đạt "
        "ngưỡng 0,60 và margin giữa hai ứng viên cùng kiểu đạt 0,02. Nếu "
        "không, giữ nguyên `?`. Cơ chế này không tạo ký tự mới và không đổi "
        "ký tự chỉ để chuỗi khớp regex.",
    )
    add_para(
        doc,
        "Trạng thái được quyết định theo thứ tự: không có dự đoán hoặc phân "
        "đoạn không OK → `LOW_CONFIDENCE`; có ký tự `?` → `LOW_CONFIDENCE`; "
        "chuỗi không hợp lệ → `FORMAT_WARNING`; điểm trung bình, điểm thấp "
        "nhất hoặc tỷ lệ ký tự tin cậy dưới ngưỡng → `LOW_CONFIDENCE`; còn "
        "lại → `SUCCESS`. Các ngưỡng cuối lần lượt là 0,60; 0,50 và 0,85.",
    )

    add_h2(doc, "4.8. Điều phối pipeline và chọn kết quả")
    add_para(
        doc,
        "`LicensePlateRecognizer` thực hiện tiền xử lý, phát hiện, sau đó lặp "
        "qua tối đa 8 ứng viên. Với mỗi ứng viên, pipeline cắt/hiệu chỉnh, "
        "phân đoạn, nhận dạng từng ký tự và hậu xử lý. Mỗi lần thử được lưu "
        "trong `CandidateAttempt` gồm ứng viên, ảnh hiệu chỉnh, kết quả phân "
        "đoạn, dự đoán ký tự, kết quả văn bản, trạng thái, lỗi và thời gian.",
    )
    add_para(
        doc,
        "Kết quả cuối được chọn theo trạng thái ưu tiên, sau đó theo điểm "
        "trung bình và số ký tự hợp lệ. Nếu không có ứng viên nào vượt qua "
        "kiểm tra hình học, pipeline trả `PLATE_NOT_FOUND` và không tạo kết "
        "quả nhận dạng giả. Nếu có ứng viên nhưng không cắt/hiệu chỉnh hoặc "
        "phân đoạn được, pipeline trả `LOW_CONFIDENCE` với chuỗi rỗng. Hai "
        "trường hợp này được phân biệt rõ trong CSV và trong giao diện.",
    )
    add_para(
        doc,
        "Khi `save_debug` bật, hệ thống ghi ảnh gốc, ảnh cạnh, nhị phân, các "
        "ứng viên, ảnh biển đã hiệu chỉnh, ảnh nhị phân phân đoạn, dải ký tự "
        "và ảnh từng ký tự. Các ảnh này là nguồn cho hình minh họa trong báo "
        "cáo và là công cụ chẩn đoán khi một ảnh thất bại.",
    )

    add_h2(doc, "4.9. Giao diện, CLI và chạy hàng loạt")
    add_para(
        doc,
        "Giao diện Tkinter gồm một cửa sổ chính với vùng chọn ảnh, vùng hiển "
        "thị kết quả và vùng ảnh trung gian. Người dùng có thể chọn ảnh, bấm "
        "nhận dạng, xem chuỗi, trạng thái, điểm trung bình, thời gian và lưu "
        "kết quả. Giao diện chạy trong luồng riêng để không chặn cửa sổ khi "
        "xử lý ảnh lớn. Ảnh hiển thị được thu nhỏ theo kích thước tối đa 760×560 "
        "nhưng kết quả nhận dạng vẫn tính trên ảnh gốc.",
    )
    add_figure(
        doc,
        ASSETS / "ui.png",
        "Giao diện Tkinter với kết quả nhận dạng ảnh 14.webp",
        width_cm=15.8,
    )
    add_para(
        doc,
        "CLI hỗ trợ ba lệnh chính: `recognize` cho một ảnh, `batch` cho một "
        "thư mục và `evaluate` cho một split có nhãn. Chế độ batch ghi CSV "
        "tổng hợp và có thể lưu debug cho từng ảnh. Các tệp `.bat` gọi CLI với "
        "tham số phù hợp, giúp người dùng không cần gõ lệnh dài.",
    )

    add_h2(doc, "4.10. Đánh giá và xuất kết quả")
    add_para(
        doc,
        "`evaluation.py` đọc nhãn, chạy hoặc nhận kết quả pipeline, tính các "
        "độ đo và ghi CSV/JSON/Markdown. Với mỗi ảnh, hàm `evaluate_row` xác "
        "định ảnh có biển hay không, ghép hộp dự đoán với hộp nhãn theo IoU, "
        "căn chỉnh chuỗi theo Levenshtein, tính CA, CSA và trạng thái. Hàm "
        "`compute_summary` tổng hợp PDR, precision, recall, F1, CA, CSA, EPA, "
        "success rate, failure rate, thời gian trung bình từng công đoạn và "
        "phân bố trạng thái.",
    )
    add_para(
        doc,
        "Một điểm cần giải thích khi đọc bảng thời gian: trung bình từng công "
        "đoạn chỉ tính trên các dòng có thời gian của công đoạn đó, trong khi "
        "tổng thời gian tính trên mọi dòng xử lý được. Với ảnh thất bại sớm, "
        "một số công đoạn không có thời gian nên mẫu số nhỏ hơn; với ảnh thử "
        "nhiều ứng viên, thời gian phân đoạn và nhận dạng được cộng dồn qua "
        "các lần thử. Ngoài ra, tổng thời gian còn gồm các khoảng chuyển tiếp "
        "không được quy vào công đoạn nào (dựng đối tượng kết quả, ánh xạ hộp "
        "ký tự, ghi nhận ứng viên). Vì vậy tổng các trung bình công đoạn không "
        "bắt buộc bằng thời gian trung bình toàn ảnh; chênh lệch quan sát được "
        "là 24–46 ms tùy tập. Báo cáo giữ nguyên cách tính này và không chuẩn "
        "hóa lại để tránh che mất chi phí thực.",
    )

    add_h2(doc, "4.11. Độ phức tạp và hiệu năng")
    add_para(
        doc,
        "Chi phí phát hiện phụ thuộc số contour sinh ra từ các bản đồ "
        "morphology và số ứng viên sau lọc. Chi phí phân đoạn phụ thuộc số "
        "phiên bản nhị phân, số dòng và số thành phần liên thông. Chi phí nhận "
        "dạng phụ thuộc số ký tự, số nhãn và số template được chấm. Với 36 "
        f"nhãn và {full_text} template, nếu chấm toàn bộ cho mọi ký tự thì "
        "chi phí rất lớn; cơ chế hai tầng giảm số phép so khớp xuống còn 6 "
        "template × 36 nhãn ở tầng một và toàn bộ template của 6 nhãn ở tầng "
        "hai.",
    )
    add_para(
        doc,
        "Trên máy đo, thời gian trung bình là 1.358,76 ms cho test, 1.498,09 "
        "ms cho dev và 1.863,94 ms cho 13 ảnh thật. Ảnh `8.jpg` mất 17.822,84 "
        "ms, chủ yếu do phát hiện (16.450,36 ms) trên ảnh 2560×1244. Thời gian "
        "load template khoảng 1.521,45 ms và không được tính trong thời gian "
        "từng ảnh. Đây là chi phí thực đo trên một CPU cụ thể, không phải "
        "benchmark tối ưu.",
    )


# ======================================================================
# Chương 5
# ======================================================================
def _add_chapter5(doc: Document, data: dict[str, Any]) -> None:
    add_h1(doc, "CHƯƠNG 5. THỰC NGHIỆM VÀ KẾT QUẢ")

    add_h2(doc, "5.1. Mục tiêu thực nghiệm và giao thức")
    add_para(
        doc,
        "Thực nghiệm được thiết kế để trả lời các câu hỏi ở mục 1.3, không "
        "chỉ để trình bày một vài ảnh đẹp. Ba nhóm dữ liệu được dùng: 13 ảnh "
        "thật thông thường, một ảnh thật đặc biệt `8.jpg`, và hai split tổng "
        "hợp dev/test, mỗi split 26 ảnh. Trên dữ liệu tổng hợp, nhãn có hộp "
        "bao biển và hộp bao ký tự nên PDR/CSA được tính theo IoU. Trên ảnh "
        "thật, nhãn chỉ có chuỗi nên PDR/CSA là proxy theo sự hiện diện và số "
        "lượng; báo cáo không đánh đồng hai loại chỉ số này.",
    )
    add_para(
        doc,
        "Mọi con số trong chương được đọc từ các tệp kết quả hiện hành: "
        "`results/user_final.csv`, `results/user_special_final.csv`, "
        "`results/dev_after_final.csv`, `results/test_after_final.csv` và các "
        "tệp JSON tổng hợp tương ứng. Cấu hình đo có SHA-256 "
        f"`{data['config_hash']}`. Thời gian được đo bằng `time.perf_counter` "
        "trên cùng một máy; không có hiệu chỉnh thời gian hoặc loại bỏ ảnh "
        "chậm.",
        align=WD_ALIGN_PARAGRAPH.LEFT,
    )
    add_para(
        doc,
        "Một điểm cần nêu trước: 14 ảnh thật đã được dùng để tinh chỉnh tham "
        "số, nên kết quả 13/13 và 1/1 là **kiểm tra hồi quy trên tập đã biết**, "
        "không phải độ chính xác trên holdout độc lập. Tập test tổng hợp cũng "
        "không hoàn toàn mù: hai ảnh `test_clear_001` và `test_no_plate_001` "
        "đã được xem trước khi chốt cấu hình. Các kết luận vì vậy được giới "
        "hạn ở mức mô tả hành vi trên dữ liệu hiện có, không phải tuyên bố "
        "năng lực tổng quát.",
    )

    add_h2(doc, "5.2. Dữ liệu, môi trường và cấu hình đo")
    add_para(
        doc,
        "Bộ tổng hợp gồm 52 ảnh, chia đều 26 ảnh cho dev và test. Mỗi split "
        "có 23 ảnh có biển và 3 ảnh không biển; 19 ảnh một dòng và 4 ảnh hai "
        "dòng. Các điều kiện gồm rõ, nghiêng, thiếu sáng, hai dòng, ký tự "
        "dính, chất lượng thấp, không biển và độ phân giải thấp. Ảnh được "
        "sinh với seed 2026 từ bốn font khác với font template.",
    )
    add_table(
        doc,
        ["Thuộc tính", "Dev", "Test", "Tổng"],
        [
            ("Số ảnh", "26", "26", "52"),
            ("Ảnh có biển", "23", "23", "46"),
            ("Ảnh không biển", "3", "3", "6"),
            ("Biển một dòng", "19", "19", "38"),
            ("Biển hai dòng", "4", "4", "8"),
        ],
        [6.6, 3.4, 3.4, 3.4],
        caption="Thành phần bộ dữ liệu tổng hợp",
        font_size=9.5,
        aligns=["left", "center", "center", "center"],
    )
    add_table(
        doc,
        ["Điều kiện", "Số ảnh mỗi split", "Mô tả"],
        [
            ("clear", "5", "Ánh sáng tốt, biển rõ, ít nhiễu"),
            ("tilted", "4", "Biển nghiêng hoặc phối cảnh mạnh"),
            ("low_light", "3", "Thiếu sáng, tương phản thấp"),
            ("two_line", "4", "Biển vuông hai dòng"),
            ("touching", "3", "Ký tự dính nhau"),
            ("low_quality", "3", "Mờ, nén, nhiễu"),
            ("no_plate", "3", "Ảnh không có biển"),
            ("low_resolution", "1", "Độ phân giải thấp"),
        ],
        [3.8, 3.6, 9.6],
        caption="Các điều kiện trong bộ dữ liệu tổng hợp",
        font_size=9.5,
        aligns=["left", "center", "left"],
    )
    add_para(
        doc,
        "Môi trường đo là Windows 11 Home 10.0.26300, Intel Core i5-13420H "
        "(8 nhân, 12 luồng), 15,8 GB RAM, Python 3.13.6, OpenCV 4.10.0, NumPy "
        "2.1.3. Đây là máy cá nhân, không phải máy chủ chuyên dụng; thời gian "
        "có thể thay đổi theo tải nền và phiên bản thư viện.",
    )

    add_h2(doc, "5.3. Kết quả trên ảnh thật")
    add_para(
        doc,
        "Bảng dưới là kết quả từng ảnh thật. Cột dự đoán giữ định dạng hiển "
        "thị của hệ thống; dấu `-` và `.` chỉ để đọc, không tham gia so khớp "
        "EPA. Cột Seg là proxy số ký tự phân đoạn được trên số ký tự của "
        "chuỗi nhãn, không phải IoU.",
    )
    real_rows = []
    for row in data["user"]["rows"]:
        real_rows.append(
            (
                row["image_name"],
                row["ground_truth"] or "—",
                _prediction_display(row),
                row["status"],
                _pct(float(row["char_accuracy"])) if row["char_accuracy"] else "—",
                _seg_display(row),
                _ms(float(row["total_time_ms"])),
            )
        )
    for row in data["special"]["rows"]:
        real_rows.append(
            (
                row["image_name"],
                row["ground_truth"] or "—",
                _prediction_display(row),
                row["status"],
                _pct(float(row["char_accuracy"])) if row["char_accuracy"] else "—",
                _seg_display(row),
                _ms(float(row["total_time_ms"])),
            )
        )
    add_table(
        doc,
        ["Ảnh", "GT", "Dự đoán", "Trạng thái", "CA", "Seg", "ms"],
        real_rows,
        [3.7, 2.5, 3.3, 3.0, 1.6, 1.4, 1.5],
        caption="Kết quả từng ảnh thật (13 ảnh user và 8.jpg)",
        font_size=8.2,
        aligns=["left", "left", "left", "center", "center", "center", "center"],
        note="Seg là count_proxy cho ảnh thật; không có hộp bao nhãn nên không tính IoU.",
    )
    user = data["user"]["summary"]
    special = data["special"]["summary"]
    add_para(
        doc,
        f"Trong 13 ảnh user, tất cả đều trả `SUCCESS`, CA 100%, EPA 100% và "
        f"thời gian trung bình {_ms(user['average_processing_time_ms'])} ms. "
        f"Ảnh `8.jpg` có 10 ký tự, được tách 5/5 và nhận đúng toàn bộ, nhưng "
        f"mất {_ms(special['average_processing_time_ms'])} ms vì ảnh lớn và "
        f"công đoạn phát hiện chiếm phần lớn thời gian. Kết quả này xác nhận "
        f"pipeline xử lý được cả biển 8–9 ký tự và biển đặc biệt 10 ký tự, "
        f"nhưng không chứng minh khả năng tổng quát vì tập đã được dùng để "
        f"tinh chỉnh.",
    )

    def _summary_rows(summary: dict[str, Any], with_plate: bool) -> list[tuple[str, str]]:
        exact_all = (
            summary["exact_plate_matches"] / summary["num_images"]
            if summary["num_images"]
            else 0.0
        )
        rows = [
            ("Số ảnh", str(summary["num_images"])),
            ("Số ảnh có biển", str(summary["num_with_plate"])),
            ("Số ảnh không biển", str(summary["num_without_plate"])),
        ]
        if with_plate:
            rows.extend(
                [
                    ("PDR", _pct(summary["plate_detection_rate"])),
                    ("Detection Precision", _pct(summary["detection_precision"])),
                    ("Detection Recall", _pct(summary["detection_recall"])),
                    ("Detection F1", _pct(summary["detection_f1"])),
                    ("TP / FP / FN / TN", f"{summary['detection_true_positive']} / {summary['detection_false_positive']} / {summary['detection_false_negative']} / {summary['detection_true_negative']}"),
                    ("CSA trung bình", _pct(summary["character_segmentation_accuracy"])),
                    ("CA", _pct(summary["character_accuracy"])),
                    ("CA trên tổng ký tự nhãn", _pct(summary["character_accuracy_over_gt"])),
                    ("Ký tự đúng / nhãn", f"{summary['character_correct']}/{summary['ground_truth_characters']}"),
                    ("EPA (ảnh có biển)", _pct(summary["exact_plate_accuracy"])),
                    ("EPA (toàn bộ ảnh)", _pct(exact_all)),
                ]
            )
        rows.extend(
            [
                ("Success Rate", _pct(summary["success_rate"])),
                ("Failure/Rejection Rate", _pct(summary["failure_rate"])),
                ("Thời gian trung bình", f"{_ms(summary['average_processing_time_ms'])} ms"),
                ("Trạng thái", ", ".join(f"{k} {v}" for k, v in sorted(summary["status_counts"].items()))),
            ]
        )
        return rows

    add_table(
        doc,
        ["Chỉ số", "Giá trị"],
        _summary_rows(user, True),
        [7.2, 9.8],
        caption="Tổng hợp chỉ số trên 13 ảnh thật split user",
        font_size=9.2,
        aligns=["left", "right"],
    )
    add_table(
        doc,
        ["Chỉ số", "Giá trị"],
        _summary_rows(special, True),
        [7.2, 9.8],
        caption="Tổng hợp chỉ số trên ảnh đặc biệt 8.jpg",
        font_size=9.2,
        aligns=["left", "right"],
    )

    add_h2(doc, "5.4. Kết quả trên tập dev")
    dev = data["dev"]["summary"]
    add_table(
        doc,
        ["Chỉ số", "Giá trị"],
        _summary_rows(dev, True),
        [7.2, 9.8],
        caption="Tổng hợp chỉ số trên tập dev (26 ảnh)",
        font_size=9.2,
        aligns=["left", "right"],
    )
    dev_rows = []
    for row in data["dev"]["rows"]:
        dev_rows.append(
            (
                row["image_name"],
                row["ground_truth"] or "—",
                _prediction_display(row),
                row["status"],
                _pct(float(row["char_accuracy"])) if row["char_accuracy"] else "—",
                _seg_display(row),
                f"{float(row['detection_iou']):.3f}" if row["detection_iou"] else "—",
                _ms(float(row["total_time_ms"])),
            )
        )
    add_table(
        doc,
        ["Ảnh", "GT", "Dự đoán", "Trạng thái", "CA", "Seg", "IoU", "ms"],
        dev_rows,
        [3.7, 2.3, 3.0, 3.0, 1.25, 1.2, 1.15, 1.4],
        caption="Kết quả từng ảnh trên tập dev",
        font_size=7.5,
        aligns=["left", "left", "left", "center", "center", "center", "center", "center"],
    )

    add_h2(doc, "5.5. Kết quả trên tập test")
    test = data["test"]["summary"]
    add_table(
        doc,
        ["Chỉ số", "Giá trị"],
        _summary_rows(test, True),
        [7.2, 9.8],
        caption="Tổng hợp chỉ số trên tập test (26 ảnh)",
        font_size=9.2,
        aligns=["left", "right"],
    )
    test_rows = []
    for row in data["test"]["rows"]:
        test_rows.append(
            (
                row["image_name"],
                row["ground_truth"] or "—",
                _prediction_display(row),
                row["status"],
                _pct(float(row["char_accuracy"])) if row["char_accuracy"] else "—",
                _seg_display(row),
                f"{float(row['detection_iou']):.3f}" if row["detection_iou"] else "—",
                _ms(float(row["total_time_ms"])),
            )
        )
    add_table(
        doc,
        ["Ảnh", "GT", "Dự đoán", "Trạng thái", "CA", "Seg", "IoU", "ms"],
        test_rows,
        [3.7, 2.3, 3.0, 3.0, 1.25, 1.2, 1.15, 1.4],
        caption="Kết quả từng ảnh trên tập test",
        font_size=7.5,
        aligns=["left", "left", "left", "center", "center", "center", "center", "center"],
    )
    add_para(
        doc,
        f"Tập test đạt PDR {_pct(test['plate_detection_rate'])}, precision "
        f"{_pct(test['detection_precision'])}, CSA "
        f"{_pct(test['character_segmentation_accuracy'])}, CA "
        f"{_pct(test['character_accuracy'])} và EPA "
        f"{_pct(test['exact_plate_accuracy'])} trên 23 ảnh có biển. So với dev, "
        f"PDR giảm 17,39 điểm phần trăm, CSA giảm 16,69 điểm, CA giảm 16,34 "
        f"điểm, còn EPA giữ nguyên 47,83%. Việc CA giảm nhưng EPA không đổi "
        f"cho thấy các lỗi ký tự tăng thêm rơi vào những ảnh vốn đã không "
        f"khớp hoàn chỉnh; số ảnh đúng hoàn toàn của test vẫn là 11/23, bằng "
        f"dev.",
    )

    add_h2(doc, "5.6. So sánh với baseline")
    add_para(
        doc,
        "Bảng dưới so sánh cấu hình cuối với baseline trước khi tinh chỉnh. "
        "Baseline dùng cùng pipeline nhưng tham số cũ; thời gian baseline thấp "
        "hơn một phần vì ít ứng viên và ít template hơn, không phải vì tối ưu "
        "thuật toán. Các số baseline được đọc từ "
        "`results/user_baseline_summary.json`, `results/dev_summary.json` và "
        "`results/test_summary.json`.",
        align=WD_ALIGN_PARAGRAPH.LEFT,
    )
    base_user = data["baseline"]["user"]
    base_dev = data["baseline"]["dev"]
    base_test = data["baseline"]["test"]
    comparison_rows = []
    for label, key in [
        ("PDR", "plate_detection_rate"),
        ("CSA", "character_segmentation_accuracy"),
        ("CA", "character_accuracy"),
        ("EPA", "exact_plate_accuracy"),
        ("Success Rate", "success_rate"),
        ("Thời gian (ms)", "average_processing_time_ms"),
    ]:
        if key == "average_processing_time_ms":
            comparison_rows.append(
                (
                    label,
                    _ms(base_user[key]),
                    _ms(user[key]),
                    _ms(base_dev[key]),
                    _ms(dev[key]),
                    _ms(base_test[key]),
                    _ms(test[key]),
                )
            )
        else:
            comparison_rows.append(
                (
                    label,
                    _pct(base_user[key]),
                    _pct(user[key]),
                    _pct(base_dev[key]),
                    _pct(dev[key]),
                    _pct(base_test[key]),
                    _pct(test[key]),
                )
            )
    add_table(
        doc,
        ["Chỉ số", "User trước", "User sau", "Dev trước", "Dev sau", "Test trước", "Test sau"],
        comparison_rows,
        [2.9, 2.3, 2.3, 2.3, 2.3, 2.3, 2.6],
        caption="So sánh baseline và cấu hình cuối",
        font_size=8.4,
        aligns=["left", "center", "center", "center", "center", "center", "center"],
        note="Baseline dùng tham số cũ; thời gian không so sánh trực tiếp vì khối lượng tính toán khác.",
    )
    add_para(
        doc,
        "Trên ảnh thật, cấu hình cuối cải thiện mạnh: EPA từ 7,69% lên 100%, "
        "success từ 7,69% lên 100%, CA từ 43,24% lên 100%. Trên dev, PDR và "
        "CSA giữ nguyên, CA tăng từ 82,86% lên 88,00%, EPA từ 34,78% lên "
        "47,83%, success từ 30,77% lên 65,38%. Trên test, PDR giảm từ 86,96% "
        "xuống 82,61% nhưng CSA tăng từ 78,80% lên 80,98%, CA từ 65,24% lên "
        "71,66%, EPA từ 30,43% lên 47,83%, success từ 26,92% lên 50,00%. Đánh "
        "đổi này cho thấy các thay đổi thiên về chất lượng phân đoạn/nhận dạng "
        "hơn là mở rộng phát hiện; đây là lý do PDR test giảm nhẹ.",
    )

    add_h2(doc, "5.7. Kết quả theo điều kiện")
    add_para(
        doc,
        "Bảng dưới thống kê theo điều kiện, chỉ tính các ảnh có biển. Cột "
        "“Đúng” là số ảnh khớp hoàn toàn; CA là trung bình cộng CA từng ảnh.",
    )
    for split_name, split_key in [("dev", "dev"), ("test", "test")]:
        stats = data[split_key]["condition_stats"]
        cond_rows = []
        order = [
            "clear",
            "tilted",
            "low_light",
            "two_line",
            "touching",
            "low_quality",
            "low_resolution",
        ]
        for cond in order:
            stat = stats.get(cond)
            if not stat:
                continue
            cond_rows.append(
                (
                    cond,
                    str(stat["count"]),
                    str(stat["detected"]),
                    str(stat["exact"]),
                    _pct(stat["ca"]),
                    _ms(stat["time"]),
                )
            )
        add_table(
            doc,
            ["Điều kiện", "Số ảnh", "Phát hiện đúng", "Khớp hoàn toàn", "CA trung bình", "Thời gian (ms)"],
            cond_rows,
            [3.4, 2.0, 2.8, 3.0, 2.8, 3.0],
            caption=f"Kết quả theo điều kiện trên tập {split_name}",
            font_size=8.8,
            aligns=["left", "center", "center", "center", "center", "center"],
        )
    add_figure(
        doc,
        ASSETS / "condition_chart.png",
        "Tỷ lệ khớp hoàn toàn theo điều kiện trên dev và test",
        width_cm=15.6,
    )
    add_para(
        doc,
        "Trên dev, biển hai dòng đạt 4/4, ảnh rõ đạt 4/5, trong khi ký tự dính "
        "đạt 0/3. Trên test, ảnh thiếu sáng đạt 3/3 và độ phân giải thấp đạt "
        "1/1, nhưng ký tự dính 0/3 và nghiêng chỉ 1/4. Điều kiện `touching` là "
        "điểm yếu nhất trên cả hai split; nguyên nhân là các ký tự dính làm "
        "projection dọc không tạo đủ điểm thắt, dẫn đến thiếu hộp hoặc gộp "
        "hộp. Điều kiện `tilted` trên test cũng yếu vì hai ảnh nghiêng mạnh "
        "không có ứng viên đạt IoU ≥ 0,5.",
    )

    add_h2(doc, "5.8. So sánh tổng hợp và biểu đồ")
    add_figure(
        doc,
        ASSETS / "metrics_chart.png",
        "So sánh PDR, CSA, CA, EPA và success rate giữa dev và test",
        width_cm=15.6,
    )
    add_para(
        doc,
        "Biểu đồ cho thấy khoảng cách lớn nhất giữa dev và test nằm ở PDR "
        "(100% so với 82,61%) và CSA (97,67% so với 80,98%). CA và EPA gần "
        "nhau hơn nhưng vẫn thấp hơn mục tiêu tham chiếu. Success rate của "
        "test chỉ 50%, nghĩa là một nửa số ảnh không kết thúc ở trạng thái "
        "`SUCCESS`; phần lớn là `LOW_CONFIDENCE` do còn ký tự `?` hoặc phân "
        "đoạn không đạt.",
    )

    add_h2(doc, "5.9. Thời gian xử lý")
    add_para(
        doc,
        "Bảng dưới là thời gian trung bình từng công đoạn. Đơn vị là mili "
        "giây. Tổng các cột công đoạn chênh 24–46 ms so với tổng trung bình "
        "do khác mẫu số và phần chi phí chuyển tiếp; xem giải thích ở mục 4.10.",
    )
    stage_labels = [
        ("preprocess", "Tiền xử lý"),
        ("detection", "Phát hiện"),
        ("rectification", "Hiệu chỉnh"),
        ("segmentation", "Phân đoạn"),
        ("recognition", "Nhận dạng"),
        ("postprocessing", "Hậu xử lý"),
    ]
    timing_rows = []
    for key, label in stage_labels:
        timing_rows.append(
            (
                label,
                _num(user["stage_average_time_ms"].get(key)),
                _num(special["stage_average_time_ms"].get(key)),
                _num(dev["stage_average_time_ms"].get(key)),
                _num(test["stage_average_time_ms"].get(key)),
            )
        )
    timing_rows.append(
        (
            "Tổng trung bình",
            _num(user["average_processing_time_ms"]),
            _num(special["average_processing_time_ms"]),
            _num(dev["average_processing_time_ms"]),
            _num(test["average_processing_time_ms"]),
        )
    )
    add_table(
        doc,
        ["Công đoạn", "User (13)", "8.jpg", "Dev", "Test"],
        timing_rows,
        [4.2, 3.2, 3.2, 3.2, 3.2],
        caption="Thời gian trung bình từng công đoạn (ms)",
        font_size=9.2,
        aligns=["left", "right", "right", "right", "right"],
        note="Không gồm thời gian load template (~1.521 ms). Số liệu làm tròn 2 chữ số thập phân.",
    )
    add_para(
        doc,
        "Nhận dạng là công đoạn tốn thời gian nhất trên cả bốn tập, dao động "
        "khoảng 874–981 ms. Phát hiện đứng thứ hai, khoảng 492–623 ms, riêng "
        "`8.jpg` lên tới 16.450 ms do ảnh lớn và nhiều ứng viên. Phân đoạn "
        "khoảng 121–279 ms. Hiệu chỉnh và hậu xử lý không đáng kể. Với mục "
        "đích tương tác desktop, mức 1,3–1,9 giây/ảnh là chấp nhận được cho "
        "thao tác một ảnh, nhưng chưa phù hợp cho luồng video thời gian thực.",
    )

    add_h2(doc, "5.10. Phân tích lỗi")
    add_h3(doc, "5.10.1. Lỗi phát hiện")
    add_para(
        doc,
        "Dev phát hiện đúng 23/23 ảnh có biển và không báo nhầm 3 ảnh không "
        "biển. Test phát hiện đúng 19/23; bốn ảnh sai là `test_tilted_001` "
        "(IoU 0), `test_tilted_004` (IoU 0), `test_touching_001` (IoU 0,4885) "
        "và `test_touching_002` (IoU 0,4315). Hai ảnh nghiêng mạnh không tạo "
        "được tứ giác biển hợp lệ; hai ảnh dính có hộp bao lệch và chỉ hơi "
        "dưới ngưỡng 0,5. `test_touching_003` vẫn phát hiện được với IoU 0,802 "
        "nhưng phân đoạn chỉ còn 1/8 box.",
    )
    add_para(
        doc,
        "Không có dương tính giả trên ảnh không biển ở cả hai split, nên "
        "precision đạt 100%. Tuy nhiên `test_no_plate_003` trả "
        "`LOW_CONFIDENCE` không có hộp thay vì `PLATE_NOT_FOUND`; về mặt đánh "
        "giá vẫn là âm đúng, nhưng trạng thái chưa gọn và có thể gây nhầm lẫn "
        "cho người dùng.",
    )
    add_h3(doc, "5.10.2. Lỗi phân đoạn")
    add_para(
        doc,
        "Bảng dưới liệt kê các ảnh có số hộp ký tự ghép được nhỏ hơn số ký "
        "tự nhãn. Đây là các ca làm giảm CSA.",
    )
    seg_rows = []
    for split_name, rows in [("dev", data["dev"]["rows"]), ("test", data["test"]["rows"])]:
        for row in rows:
            if row["has_gt_plate"] != "1" or row["seg_gt_count"] == "0":
                continue
            matched = int(row["seg_matched"])
            gt_count = int(row["seg_gt_count"])
            if matched < gt_count:
                seg_rows.append(
                    (
                        row["image_name"],
                        split_name,
                        f"{matched}/{gt_count}",
                        _pct(float(row["char_accuracy"])) if row["char_accuracy"] else "—",
                        row["status"],
                    )
                )
    add_table(
        doc,
        ["Ảnh", "Split", "Seg match/GT", "CA", "Trạng thái"],
        seg_rows,
        [5.2, 2.0, 3.2, 2.8, 3.8],
        caption="Các ảnh có phân đoạn thiếu hộp ký tự",
        font_size=8.8,
        aligns=["left", "center", "center", "center", "center"],
    )
    add_para(
        doc,
        "Các ảnh `touching` là điểm yếu rõ nhất: `test_touching_002` chỉ ghép "
        "được 1/8 box, `test_touching_003` 1/8, `test_touching_001` 5/8. "
        "Nguyên nhân là các ký tự dính tạo thành một thành phần liên thông "
        "lớn; projection dọc không có điểm thắt đủ sâu, và bước tách hộp rộng "
        "chỉ tách được một lần. Fallback bằng connected components giúp tách "
        "dòng nhưng không giải quyết triệt để việc tách ký tự trong cùng dòng.",
    )
    add_h3(doc, "5.10.3. Lỗi nhận dạng và nhầm lẫn ký tự")
    add_para(
        doc,
        "Dev có 154/175 ký tự đúng, 21 thay thế, 0 thêm, 0 xóa. Test có "
        "134/187 ký tự đúng, 24 thay thế, 0 thêm, 29 xóa. Số xóa trên test "
        "gồm 16 ký tự từ hai ảnh nghiêng mạnh không tạo được ký tự nào và 13 "
        "ký tự từ ba ảnh `touching` chỉ tạo được 1–5 ký tự; hệ thống không bịa "
        "thêm ký tự để đủ độ dài. Bảng dưới là các cặp nhầm lẫn khi hệ thống "
        "**khẳng định** một ký tự sai; các ký tự bị từ chối thành `?` không "
        "được tính vào bảng này.",
    )
    confusion_pairs = set(data["confusion"]["dev"]) | set(data["confusion"]["test"])
    confusion_rows = []
    for gt_char, pred_char in sorted(
        confusion_pairs,
        key=lambda pair: (
            -(data["confusion"]["dev"][pair] + data["confusion"]["test"][pair]),
            pair,
        ),
    ):
        confusion_rows.append(
            (
                f"{gt_char} → {pred_char}",
                str(data["confusion"]["dev"][(gt_char, pred_char)]),
                str(data["confusion"]["test"][(gt_char, pred_char)]),
            )
        )
    add_table(
        doc,
        ["Cặp (GT → dự đoán)", "Dev", "Test"],
        confusion_rows,
        [8.0, 4.5, 4.5],
        caption="Các cặp nhầm lẫn ký tự được khẳng định sai",
        font_size=9.2,
        aligns=["left", "center", "center"],
    )
    add_para(
        doc,
        "Lỗi chủ đạo là chữ số `1` bị nhận thành `2`, `T`, `Y` hoặc `X`, đặc "
        "biệt khi nét quá mảnh, mất một phần hoặc bị nghiêng. Các lỗi còn lại "
        "phân tán ở `8 → 6`, `8 → 3`, `9 → X`, `1 → 4`, `1 → Z`, `1 → A`. "
        "Không có cặp nhầm lẫn "
        "nào chiếm đa số tuyệt đối, nhưng `1` là ký tự rủi ro nhất vì cấu trúc "
        "đơn giản dễ tương quan với nhiều mẫu khác.",
    )
    add_para(
        doc,
        "Một số chuỗi sai tiêu biểu: `dev_tilted_001` đọc `1` thành `X`; "
        "`dev_low_light_001` đọc `1` thành `T`; `test_clear_005` đọc `1` "
        "thành `T`; `test_low_quality_001` đọc `1` thành `A`. Các chuỗi này "
        "không khớp regex nên trả `FORMAT_WARNING`. Hệ thống không tự sửa "
        "`X/T/A` thành `1` dù biết vị trí đó thường là chữ số, vì làm vậy sẽ "
        "làm sai lệch kết quả và che mất lỗi nhận dạng.",
    )
    add_h3(doc, "5.10.4. Trạng thái và từ chối")
    status_rows = []
    for label, summary in [
        ("User (13)", user),
        ("8.jpg", special),
        ("Dev (26)", dev),
        ("Test (26)", test),
    ]:
        counts = summary["status_counts"]
        status_rows.append(
            (
                label,
                str(counts.get("SUCCESS", 0)),
                str(counts.get("FORMAT_WARNING", 0)),
                str(counts.get("LOW_CONFIDENCE", 0)),
                str(counts.get("PLATE_NOT_FOUND", 0)),
            )
        )
    add_table(
        doc,
        ["Tập", "SUCCESS", "FORMAT_WARNING", "LOW_CONFIDENCE", "PLATE_NOT_FOUND"],
        status_rows,
        [3.2, 2.8, 3.8, 3.6, 3.6],
        caption="Phân bố trạng thái trên các tập dữ liệu",
        font_size=8.8,
        aligns=["left", "center", "center", "center", "center"],
    )
    add_para(
        doc,
        "Dev có 17 `SUCCESS`, 2 `FORMAT_WARNING`, 4 `LOW_CONFIDENCE` và 3 "
        "`PLATE_NOT_FOUND`. Test có 13 `SUCCESS`, 9 `LOW_CONFIDENCE`, 2 "
        "`FORMAT_WARNING` và 2 `PLATE_NOT_FOUND`. Nhiều ảnh có chuỗi gần đúng "
        "nhưng còn 1–2 ký tự `?`; hệ thống chủ động không đoán. Đây là hành "
        "vi đúng theo thiết kế, nhưng giải thích vì sao success rate thấp hơn "
        "CA và EPA.",
    )

    add_h2(doc, "5.11. Các thực nghiệm đã thử và bị loại")
    add_para(
        doc,
        "Không phải mọi thay đổi đều được giữ. Bảng dưới ghi lại các thực "
        "nghiệm quan trọng, kết quả quan sát và quyết định. Các dòng ghi “số "
        "liệu lịch sử” được đo trên cấu hình cũ, không so sánh trực tiếp với "
        "bảng kết quả cuối.",
    )
    experiment_rows = [
        ("Thêm template Calibri/Verdana/Times/Trebuchet (lần 1)", "CA proxy 81,14%; EPA 34,78%; 438 ms (lịch sử)", "Loại: thấp hơn baseline và chậm hơn"),
        ("Mở rộng template lần 2", "CA proxy 81,71%; 542 ms (lịch sử)", "Loại: không cải thiện, chậm hơn"),
        ("Bright-plate quad (Otsu + approxPolyDP)", "Hình học dev_tilted_002 đẹp hơn nhưng hỏng dev_clear_001/003, dev_tilted_004, dev_two_line_001", "Loại, giữ hiệu chỉnh Canny"),
        ("Tăng coarse_top_labels lên 10", "Top-1 exact 13/23; 9 SUCCESS (lịch sử)", "Không dùng: không tăng success đủ, tốn thời gian"),
        ("Tăng coarse_top_labels lên 36", "Top-1 exact 14/23; 9 SUCCESS; chậm ~4× (lịch sử)", "Không dùng: chậm, lợi ích nhỏ"),
        ("Fallback chấm lại full-res cho ký tự bị từ chối", "Sửa top-1 cho dev_tilted_001, dev_low_quality_001; không tăng SUCCESS", "Không dùng"),
        ("Padding dọc 6% chiều rộng", "Giảm cắt góc biển nghiêng", "Giữ trong cấu hình; chưa được truyền vào crop_candidate"),
        ("Vá phân đoạn (ước lượng bề rộng + tách valley)", "dev_touching_002 tăng số box; chỉ số tổng không giảm", "Giữ"),
        ("Chuẩn hóa 32×48, stretch, blur σ=2,0", "Cải thiện ổn định trên ảnh thật so với 24×36 giữ tỷ lệ", "Giữ"),
        ("Prior số lỗ", "Giảm nhầm 6/B, 0/D, 8/B", "Giữ"),
        ("Biến thể chữ 4 hở đỉnh", "Nhận đúng kiểu chữ 4 trên biển thật", "Giữ"),
        ("Rerank theo vị trí + position_min_margin=0,02", "Chọn đúng ứng viên cùng kiểu mà không tạo ký tự mới", "Giữ"),
        ("expected_chars=[7,9] + ngoại lệ 10 ký tự cân bằng", "Sửa hồi quy 5.webp (4/6 giả) và vẫn nhận 8.jpg (5/5)", "Giữ"),
        ("Bbox hint cho ứng viên cụm chữ", "Dev recall 82,61% → 100%; test recall 73,91% → 82,61%", "Giữ"),
    ]
    add_table(
        doc,
        ["Thực nghiệm", "Kết quả đo / quan sát", "Quyết định"],
        experiment_rows,
        [5.4, 7.6, 4.0],
        caption="Các thực nghiệm đã thử và quyết định",
        font_size=8.2,
        aligns=["left", "left", "left"],
        note="Các số ghi “lịch sử” không thuộc bảng kết quả cuối và không dùng để so sánh trực tiếp.",
    )

    add_h2(doc, "5.12. Đối chiếu mục tiêu tham chiếu")
    add_para(
        doc,
        "Đặc tả nêu các mục tiêu tham khảo trên bộ ảnh thuận lợi. Bảng dưới "
        "đối chiếu với kết quả thực đo trên dev và test.",
    )
    add_table(
        doc,
        ["Mục tiêu", "Ngưỡng", "Dev", "Test", "Kết luận"],
        [
            ("Detection Rate", "≥ 90%", _pct(dev["plate_detection_rate"]), _pct(test["plate_detection_rate"]), "Dev đạt; test chưa đạt"),
            ("Segmentation Accuracy", "≥ 85%", _pct(dev["character_segmentation_accuracy"]), _pct(test["character_segmentation_accuracy"]), "Dev đạt; test chưa đạt"),
            ("Exact Plate Accuracy", "≥ 70%", _pct(dev["exact_plate_accuracy"]), _pct(test["exact_plate_accuracy"]), "Chưa đạt ở cả hai split"),
        ],
        [4.4, 2.2, 2.6, 2.6, 5.2],
        caption="Đối chiếu với các mục tiêu tham chiếu của đặc tả",
        font_size=9.2,
        aligns=["left", "center", "center", "center", "left"],
    )
    add_para(
        doc,
        "Khoảng cách EPA còn khoảng 22 điểm phần trăm so với ngưỡng 70%. "
        "Nguyên nhân chính gồm: template từ font không khớp hoàn toàn font "
        "ảnh mẫu; nhiều ký tự bị từ chối bởi ngưỡng margin/score; phân đoạn "
        "yếu trên ảnh ký tự dính và một số ảnh nghiêng mạnh; và tập test có "
        "nhiều điều kiện khó hơn “ảnh thuận lợi” mà đặc tả giả định. Trên 13 "
        "ảnh thật, EPA là 13/13 và trên `8.jpg` là 1/1, nhưng đây là tập đã "
        "dùng để tinh chỉnh và chưa có hộp bao nhãn, nên **không thể coi là "
        "bằng chứng đạt mục tiêu EPA** trên dữ liệu mới.",
    )

    add_h2(doc, "5.13. Đe dọa tính hợp lệ và khoảng tin cậy")
    add_para(
        doc,
        "Các kết luận trong báo cáo chịu một số đe dọa. Thứ nhất, 14 ảnh thật "
        "đã được dùng để tinh chỉnh, nên kết quả 14/14 là hồi quy trên tập đã "
        "biết. Thứ hai, hai ảnh test đã được xem trước khi chốt cấu hình, nên "
        "test không hoàn toàn mù. Thứ ba, bộ tổng hợp được sinh từ bốn font và "
        "một quy trình render nhất định; kết quả có thể không chuyển sang ảnh "
        "thật ngoài trời. Thứ tư, cỡ mẫu nhỏ (23 ảnh có biển mỗi split) làm "
        "khoảng tin cậy rộng. Thứ năm, ảnh thật không có hộp bao nên PDR/CSA "
        "chỉ là proxy. Thứ sáu, thời gian phụ thuộc tải máy và không được đo "
        "lặp nhiều lần.",
    )
    add_para(
        doc,
        "Bảng dưới là khoảng tin cậy Wilson 95% cho một số tỷ lệ chính. "
        "Khoảng tin cậy được tính từ số lần thành công và số ảnh, không dùng "
        "xấp xỉ chuẩn.",
    )
    ci_rows = []
    for label, k, n in [
        ("User EPA", 13, 13),
        ("Dev EPA", 11, 23),
        ("Test EPA", 11, 23),
        ("Test PDR", 19, 23),
        ("Test success", 13, 26),
        ("EPA toàn bộ 26 ảnh test", 11, 26),
    ]:
        lo, hi = _wilson(k, n)
        ci_rows.append((label, f"{k}/{n}", _pct(k / n), f"{_pct(lo)} – {_pct(hi)}"))
    add_table(
        doc,
        ["Tỷ lệ", "k/n", "Điểm", "Khoảng tin cậy 95%"],
        ci_rows,
        [5.6, 2.8, 3.0, 5.6],
        caption="Khoảng tin cậy Wilson 95% cho các tỷ lệ chính",
        font_size=9.2,
        aligns=["left", "center", "center", "center"],
    )
    add_para(
        doc,
        "Ví dụ, EPA test 47,83% có khoảng tin cậy 29,24%–67,04%; ngưỡng 70% "
        "nằm ngoài khoảng này, nên kết luận “chưa đạt” là vững hơn so với chỉ "
        "nhìn con số điểm. Ngược lại, EPA user 100% có khoảng 77,19%–100%, "
        "cho thấy ngay cả kết quả hoàn hảo trên 13 ảnh cũng không bảo đảm "
        "100% trên dữ liệu mới.",
    )

    add_h2(doc, "5.14. Thảo luận")
    add_para(
        doc,
        "Kết quả cho thấy pipeline truyền thống có thể giải quyết tốt các ảnh "
        "biển rõ, đặc biệt khi viền biển kín và ký tự tách biệt. Trên dev, "
        "PDR 100% và CSA 97,67% chứng minh phần phát hiện và phân đoạn hoạt "
        "động đúng trong miền dữ liệu tổng hợp. Tuy nhiên, EPA chỉ 47,83% vì "
        "lỗi nhận dạng ký tự và việc từ chối các ký tự không chắc chắn. Trên "
        "test, PDR giảm còn 82,61% và CSA 80,98%, cho thấy các điều kiện khó "
        "như nghiêng mạnh và ký tự dính vẫn là nút thắt.",
    )
    add_para(
        doc,
        "Điểm mạnh của hệ thống là tính minh bạch: mỗi ký tự có điểm, margin, "
        "nhãn tốt nhất và nhãn thứ hai; mỗi ảnh có ảnh trung gian và thời gian "
        "từng công đoạn. Khi sai, có thể truy ngược đến phát hiện, phân đoạn "
        "hay nhận dạng. Điểm yếu là độ chính xác chưa đạt mục tiêu và độ bền "
        "trên ảnh thật ngoài miền tổng hợp chưa được chứng minh. Đây là cái "
        "giá của phương pháp cổ điển: ít dữ liệu huấn luyện, dễ giải thích, "
        "nhưng nhạy cảm với domain shift và điều kiện chụp.",
    )


# ======================================================================
# Chương 6
# ======================================================================
def _add_chapter6(doc: Document, data: dict[str, Any]) -> None:
    add_h1(doc, "CHƯƠNG 6. KẾT LUẬN VÀ HƯỚNG PHÁT TRIỂN")

    add_h2(doc, "6.1. Kết luận")
    user = data["user"]["summary"]
    special = data["special"]["summary"]
    dev = data["dev"]["summary"]
    test = data["test"]["summary"]
    add_para(
        doc,
        "Đồ án đã xây dựng được một hệ thống nhận dạng biển số xe Việt Nam "
        "hoàn chỉnh bằng xử lý ảnh truyền thống và Template Matching, đáp ứng "
        "các ràng buộc của đề tài: không dùng học máy, học sâu, YOLO, KNN, "
        "SVM, OCR học sẵn hay API nhận dạng bên ngoài. Hệ thống có pipeline "
        "tám công đoạn, cấu hình tập trung, giao diện Tkinter, CLI, chạy hàng "
        "loạt, bộ 78 bài kiểm thử và công cụ đánh giá sinh CSV/JSON/Markdown.",
    )
    add_para(
        doc,
        f"Về kết quả, 13 ảnh thật thông thường đạt "
        f"{user['exact_plate_matches']}/13 chuỗi chính xác, tất cả `SUCCESS`, "
        f"và ảnh đặc biệt `8.jpg` đạt {special['exact_plate_matches']}/1. Đây "
        f"là kết quả hồi quy sau khi dùng chính 14 ảnh này để tinh chỉnh, "
        f"không phải độ chính xác trên holdout độc lập. Trên tập tổng hợp, "
        f"dev đạt PDR {_pct(dev['plate_detection_rate'])}, CSA "
        f"{_pct(dev['character_segmentation_accuracy'])}, CA "
        f"{_pct(dev['character_accuracy'])} và EPA "
        f"{_pct(dev['exact_plate_accuracy'])}; test đạt PDR "
        f"{_pct(test['plate_detection_rate'])}, CSA "
        f"{_pct(test['character_segmentation_accuracy'])}, CA "
        f"{_pct(test['character_accuracy'])} và EPA "
        f"{_pct(test['exact_plate_accuracy'])}. Mục tiêu tham chiếu EPA ≥ 70% "
        f"**chưa đạt** trên cả hai split.",
    )
    add_para(
        doc,
        "Kết quả cho thấy phương pháp cổ điển có thể giải quyết tốt ảnh biển "
        "rõ, nhưng chưa đủ bền cho ảnh nghiêng mạnh, ký tự dính và sự lệch "
        "miền giữa template sinh từ font với ảnh thật. Điểm mạnh của hệ thống "
        "là tính minh bạch và khả năng chẩn đoán; điểm yếu là độ chính xác "
        "chuỗi còn khoảng 22 điểm phần trăm dưới mục tiêu và chưa có bằng "
        "chứng tổng quát hóa trên dữ liệu mới.",
    )

    add_h2(doc, "6.2. Hạn chế")
    add_numbered(
        doc,
        [
            "**14 ảnh thật không phải holdout độc lập.** Toàn bộ ảnh đã được "
            "dùng để tinh chỉnh phân đoạn/nhận dạng; 14/14 chỉ là kiểm tra hồi "
            "quy trên tập đã biết.",
            "**Chưa có hộp bao biển/ký tự cho ảnh thật.** PDR/CSA trên split "
            "user là proxy theo sự hiện diện và số lượng, không phải IoU.",
            "**EPA dưới mục tiêu** trên tập tổng hợp: 47,83% so với ngưỡng "
            "70%. Khoảng cách này chưa được thu hẹp trong phạm vi đồ án.",
            "**Lệch miền template.** Template sinh từ font không khớp hoàn "
            "toàn font trên biển thật; các biến thể thủ công chỉ giảm một phần "
            "khác biệt.",
            "**Phân đoạn yếu trên ký tự dính và một số ảnh nghiêng mạnh.** "
            "Projection dọc không tạo đủ điểm thắt; fallback hiện tại chưa tách "
            "được nhiều ký tự dính liền.",
            "**Từ chối nhiều ký tự.** Ngưỡng điểm/margin bảo vệ khỏi khẳng "
            "định sai nhưng làm tăng số `?`, kéo success rate xuống.",
            "**Cỡ mẫu nhỏ.** 23 ảnh có biển mỗi split tạo khoảng tin cậy rộng; "
            "các kết luận định lượng chỉ mang tính mô tả.",
            "**Test không hoàn toàn mù.** Hai ảnh test đã được xem trước khi "
            "chốt cấu hình; cần một tập mới chưa từng xem để đánh giá khách "
            "quan hơn.",
            "**Thời gian đo một lần.** Chưa lặp nhiều lần, chưa đo độ lệch "
            "chuẩn, chưa tách thời gian load template khỏi thời gian tương tác.",
            "**Quy tắc định dạng chỉ mang tính cấu trúc.** Regex không xác "
            "minh mã tỉnh, series hay tính hợp pháp của biển; `8.jpg` có series "
            "`MD7` không khớp quy ước thông thường nhưng vẫn được chấp nhận "
            "theo cấu trúc.",
            "**Cấu hình và mã chưa thống nhất hoàn toàn.** `vertical_padding_ratio` "
            "có trong YAML nhưng chưa được truyền vào `crop_candidate`; báo cáo "
            "không mô tả hệ thống là đã dùng padding dọc 6%.",
            "**Phạm vi hẹp.** Chỉ ảnh tĩnh, một biển chính; không xử lý video, "
            "nhiều biển, biển bị che khuất nặng hoặc chữ nước ngoài.",
        ],
    )

    add_h2(doc, "6.3. Hướng phát triển")
    add_numbered(
        doc,
        [
            "**Cải thiện phân đoạn ký tự dính** bằng distance transform kết hợp "
            "watershed hoặc tách theo mật độ điểm ảnh, vẫn trong phạm vi xử lý "
            "ảnh truyền thống.",
            "**Tăng cường hiệu chỉnh phối cảnh** bằng phát hiện đường thẳng "
            "Hough, ước lượng viền biển và kiểm tra tứ giác theo cả bốn cạnh "
            "thay vì chỉ contour lớn nhất.",
            "**Mở rộng bộ template có kiểm soát** từ các font thực tế và biến "
            "thể nét, nhưng vẫn giữ nguyên tắc không dùng học máy; đánh giá "
            "tác động lên cả độ chính xác và thời gian.",
            "**Hiệu chỉnh ngưỡng từ chối** theo phân bố điểm thực nghiệm, có "
            "thể dùng ngưỡng riêng cho từng nhóm ký tự và kiểm tra trên tập "
            "holdout mới.",
            "**Xây dựng tập ảnh thật có hộp bao** để đo PDR/CSA bằng IoU, "
            "không dùng proxy; tách tập hiệu chỉnh và tập kiểm thử độc lập.",
            "**Tối ưu hiệu năng** bằng song song hóa theo ứng viên, giảm số "
            "template ở tầng một, hoặc lưu cache đặc trưng; đo lặp nhiều lần "
            "và báo cáo độ lệch chuẩn.",
            "**Cải thiện giao diện** với hiển thị từng bước, so sánh ứng viên, "
            "cho phép người dùng sửa và ghi nhãn, nhưng không dùng sửa của "
            "người dùng để che kết quả tự động.",
            "**Mở rộng phạm vi** sang ảnh video, nhiều biển trong khung hình "
            "và biển bị che khuất một phần, với thiết kế module riêng.",
        ],
    )

    add_h2(doc, "6.4. Bài học kinh nghiệm")
    add_para(
        doc,
        "Bài học lớn nhất là chất lượng dữ liệu và cách đánh giá quan trọng "
        "không kém thuật toán. Một con số 100% trên tập đã dùng để tinh chỉnh "
        "không có cùng ý nghĩa với 100% trên tập mù. Việc tách rõ hai loại "
        "kết quả, ghi lại mọi thất bại và không tự sửa ký tự giúp báo cáo "
        "trung thực hơn, dù các con số kém đẹp hơn.",
    )
    add_para(
        doc,
        "Bài học thứ hai là các cải tiến nhỏ có thể tạo khác biệt lớn nếu "
        "đúng chỗ: quy tắc biển 10 ký tự cân bằng sửa một hồi quy cụ thể; bbox "
        "hint tăng recall phát hiện mà không đổi vùng cắt; prior số lỗ giảm "
        "nhầm lẫn giữa các ký tự có cấu trúc gần nhau. Tuy nhiên, các cải "
        "tiến này không thay thế được một bộ dữ liệu đa dạng và một phương "
        "pháp phân đoạn mạnh hơn.",
    )
    add_para(
        doc,
        "Bài học thứ ba là cần kiểm tra sự thống nhất giữa cấu hình, mã nguồn "
        "và báo cáo. Ví dụ `vertical_padding_ratio` tồn tại trong YAML nhưng "
        "chưa được dùng; nếu báo cáo chỉ đọc YAML sẽ mô tả sai hành vi thực. "
        "Việc đối chiếu mã nguồn với tài liệu là bước bắt buộc trước khi công "
        "bố kết quả.",
    )


# ======================================================================
# Tài liệu tham khảo
# ======================================================================
def _add_references(doc: Document) -> None:
    add_h1(doc, "TÀI LIỆU THAM KHẢO")
    references = [
        "Gonzalez, R. C., & Woods, R. E. (2018). Digital Image Processing "
        "(4th ed.). Pearson.",
        "Bradski, G. (2000). The OpenCV Library. Dr. Dobb's Journal of "
        "Software Tools, 25(11), 120–125.",
        "OpenCV Team. (2024). OpenCV 4.x Documentation. "
        "https://docs.opencv.org/4.x/",
        "Otsu, N. (1979). A Threshold Selection Method from Gray-Level "
        "Histograms. IEEE Transactions on Systems, Man, and Cybernetics, "
        "9(1), 62–66.",
        "Canny, J. (1986). A Computational Approach to Edge Detection. IEEE "
        "Transactions on Pattern Analysis and Machine Intelligence, 8(6), "
        "679–698.",
        "Zuiderveld, K. (1994). Contrast Limited Adaptive Histogram "
        "Equalization. In Graphics Gems IV (pp. 474–485). Academic Press.",
        "Douglas, D. H., & Peucker, T. K. (1973). Algorithms for the "
        "Reduction of the Number of Points Required to Represent a Digitized "
        "Line or Its Caricature. Cartographica, 10(2), 112–122.",
        "Duda, R. O., Hart, P. E., & Stork, D. G. (2001). Pattern "
        "Classification (2nd ed.). Wiley.",
        "Levenshtein, V. I. (1966). Binary Codes Capable of Correcting "
        "Deletions, Insertions, and Reversals. Soviet Physics Doklady, 10(8), "
        "707–710.",
        "Wilson, E. B. (1927). Probable Inference, the Law of Succession, and "
        "Statistical Inference. Journal of the American Statistical "
        "Association, 22(158), 209–212.",
        "Python Software Foundation. (2024). Python 3.13 Documentation. "
        "https://docs.python.org/3.13/",
        "pytest Development Team. (2024). pytest Documentation. "
        "https://docs.pytest.org/",
        "python-docx Development Team. (2024). python-docx Documentation. "
        "https://python-docx.readthedocs.io/",
        "Python Software Foundation. (2024). tkinter — Python interface to "
        "Tcl/Tk. https://docs.python.org/3/library/tkinter.html",
        "Bộ Công an. (2023). Thông tư 24/2023/TT-BCA quy định về cấp, thu hồi "
        "đăng ký, biển số xe cơ giới. Hà Nội.",
    ]
    for index, text in enumerate(references, start=1):
        p = doc.add_paragraph()
        p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.left_indent = Cm(1.0)
        p.paragraph_format.first_line_indent = Cm(-1.0)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing = 1.3
        run = p.add_run(f"[{index}] ")
        _set_run_font(run, BODY_FONT, 11, bold=True)
        run = p.add_run(text)
        _set_run_font(run, BODY_FONT, 11)


# ======================================================================
# Phụ lục
# ======================================================================
def _extract_config_sections(names: Sequence[str]) -> str:
    lines = (ROOT / "config.yaml").read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    current = None
    for line in lines:
        if line and not line.startswith((" ", "#")) and line.rstrip().endswith(":"):
            current = line.split(":", 1)[0]
        if current in names:
            output.append(line)
    return "\n".join(output).strip()


def _add_appendix_a(doc: Document) -> None:
    add_h1(doc, "PHỤ LỤC A. CẤU HÌNH CHÍNH")
    add_para(
        doc,
        "Dưới đây là trích đoạn các nhóm cấu hình quan trọng trong "
        "`config.yaml`. Tệp đầy đủ là nguồn duy nhất được dùng khi chạy hệ "
        "thống; các giá trị trong báo cáo không được sửa thủ công.",
    )
    add_code(
        doc,
        _extract_config_sections(["image", "preprocessing"]),
        caption="Nhóm cấu hình ảnh và tiền xử lý",
    )
    add_code(
        doc,
        _extract_config_sections(["detection"]),
        caption="Nhóm cấu hình phát hiện biển",
    )
    add_code(
        doc,
        _extract_config_sections(["rectification"]),
        caption="Nhóm cấu hình hiệu chỉnh phối cảnh",
    )
    add_code(
        doc,
        _extract_config_sections(["segmentation"]),
        caption="Nhóm cấu hình phân đoạn ký tự",
    )
    add_code(
        doc,
        _extract_config_sections(["recognition", "postprocessing", "pipeline"]),
        caption="Nhóm cấu hình nhận dạng, hậu xử lý và pipeline",
    )


def _add_appendix_b(doc: Document) -> None:
    add_h1(doc, "PHỤ LỤC B. CÀI ĐẶT VÀ CHẠY")
    add_para(
        doc,
        "Hệ thống được kiểm tra trên Windows 11 với Python 3.13.6. Các bước "
        "cài đặt và chạy như sau.",
    )
    add_h2(doc, "B.1. Cài đặt", space_before=8, space_after=4)
    add_code(
        doc,
        "cd vietnamese-license-plate-recognition\n"
        "python -m venv .venv\n"
        ".venv\\Scripts\\activate\n"
        "python -m pip install --upgrade pip\n"
        "python -m pip install -r requirements.txt",
        caption="Tạo môi trường ảo và cài đặt thư viện",
        space_before=2,
        space_after=5,
    )
    add_para(
        doc,
        "Nếu không dùng môi trường ảo, có thể cài trực tiếp vào Python hệ "
        "thống. Các gói chính gồm OpenCV, NumPy, Pillow, PyYAML và pytest. "
        "python-docx và matplotlib chỉ cần cho việc sinh báo cáo/biểu đồ, "
        "không cần cho ứng dụng nhận dạng.",
    )
    add_h2(doc, "B.2. Chạy giao diện", space_before=8, space_after=4)
    add_code(
        doc,
        "python main.py ui\n"
        "REM hoặc nhấp đúp run_ui.bat",
        caption="Mở giao diện Tkinter",
        space_before=2,
        space_after=5,
    )
    add_h2(doc, "B.3. Chạy CLI", space_before=8, space_after=4)
    add_code(
        doc,
        "python main.py recognize data\\user_images\\14.webp --save-debug\n"
        "python main.py batch data\\user_images --output-csv results\\batch.csv\n"
        "python main.py evaluate --labels data\\labels.csv --split dev",
        caption="Các lệnh CLI thường dùng",
        space_before=2,
        space_after=5,
    )
    add_para(
        doc,
        "Khi chạy `recognize` với `--save-debug`, ảnh trung gian được ghi vào "
        "`results/debug/<tên_ảnh>/`. Khi chạy `evaluate`, hệ thống đọc nhãn, "
        "chạy pipeline và ghi CSV/JSON/Markdown theo tham số.",
    )
    add_h2(doc, "B.4. Yêu cầu hệ thống", space_before=8, space_after=4)
    add_bullets(
        doc,
        [
            "Windows 10/11 64-bit (đã kiểm tra trên Windows 11 10.0.26300).",
            "Python 3.10 trở lên; khuyến nghị 3.13.6 như môi trường đo.",
            "RAM tối thiểu 8 GB; khuyến nghị 16 GB cho ảnh lớn.",
            "Không cần GPU, không cần kết nối Internet khi chạy.",
            "Microsoft Word chỉ cần để cập nhật mục lục và xuất PDF báo cáo.",
        ],
    )


def _add_appendix_c(doc: Document) -> None:
    add_h1(doc, "PHỤ LỤC C. KIỂM THỬ")
    add_para(
        doc,
        "Bộ kiểm thử được chạy bằng pytest. Lệnh và kết quả tại thời điểm lập "
        "báo cáo:",
    )
    add_code(
        doc,
        "python -m pytest -q\n"
        "78 passed in 28.13s",
        caption="Kết quả chạy kiểm thử",
    )
    add_table(
        doc,
        ["Nhóm kiểm thử", "Số bài", "Trọng tâm"],
        [
            ("Cấu hình", "7", "Đọc YAML, giá trị mặc định, lỗi cấu hình"),
            ("Tiền xử lý", "7", "Blur, CLAHE, Canny, Otsu, ảnh không hợp lệ"),
            ("Phát hiện", "7", "Ứng viên, lọc, xếp hạng, top-k"),
            ("Hiệu chỉnh", "5", "Crop, warp, deskew, ánh xạ ngược"),
            ("Phân đoạn", "6", "Một dòng, hai dòng, 10 ký tự, thứ tự đọc"),
            ("Nhận dạng", "12", "Chuẩn hóa, template, từ chối, hole prior"),
            ("Hậu xử lý", "16", "Regex, rerank, trạng thái, không đoán"),
            ("Đánh giá", "9", "IoU, Levenshtein, PDR/CSA/CA/EPA"),
            ("Pipeline", "8", "End-to-end, trạng thái, debug, batch"),
            ("Giao diện", "1", "Smoke test trong tiến trình riêng"),
            ("Tổng", "78", "Tất cả đều đạt"),
        ],
        [4.4, 1.8, 10.8],
        caption="Tóm tắt bộ kiểm thử theo nhóm",
        font_size=9.0,
        aligns=["left", "center", "left"],
    )
    add_para(
        doc,
        "Các bài kiểm thử không thay thế đánh giá độ chính xác. Chúng bảo vệ "
        "các hành vi lập trình (ví dụ không tạo ký tự mới, giữ `?`, xử lý ảnh "
        "lỗi) và giúp phát hiện hồi quy khi sửa mã. Đánh giá độ chính xác vẫn "
        "phải chạy trên dữ liệu có nhãn.",
    )


def _add_appendix_d(doc: Document, data: dict[str, Any]) -> None:
    add_h1(doc, "PHỤ LỤC D. LỆNH TÁI LẬP THỰC NGHIỆM")
    add_para(
        doc,
        "Các lệnh dưới đây tái lập bộ template, dữ liệu tổng hợp, kết quả "
        "đánh giá và hình minh họa. Chạy từ thư mục gốc của dự án.",
    )
    add_code(
        doc,
        "REM 1. Sinh template từ các font trên Windows\n"
        "python tools\\build_templates.py\n"
        "\n"
        "REM 2. Sinh dữ liệu tổng hợp dev/test (seed 2026)\n"
        "python tools\\build_synthetic_dataset.py\n"
        "\n"
        "REM 3. Đánh giá dev và test\n"
        "python main.py evaluate --labels data\\labels.csv --split dev "
        "--output-csv results\\dev_after_final.csv "
        "--summary-json results\\dev_after_final_summary.json\n"
        "python main.py evaluate --labels data\\labels.csv --split test "
        "--output-csv results\\test_after_final.csv "
        "--summary-json results\\test_after_final_summary.json\n"
        "\n"
        "REM 4. Đánh giá ảnh thật\n"
        "python main.py evaluate --labels data\\user_labels.csv --split user "
        "--samples-dir data\\user_images "
        "--output-csv results\\user_final.csv "
        "--summary-json results\\user_final_summary.json\n"
        "\n"
        "REM 5. Sinh hình và biểu đồ cho báo cáo\n"
        "python tools\\build_report_assets.py\n"
        "\n"
        "REM 6. Sinh báo cáo Word\n"
        "python tools\\build_report_docx.py",
        caption="Chuỗi lệnh tái lập chính",
    )
    add_para(
        doc,
        "Lưu ý: kết quả trong báo cáo được đo với cấu hình có SHA-256 "
        f"`{data['config_hash']}`. Nếu sửa `config.yaml`, cần chạy lại toàn bộ "
        "đánh giá và cập nhật báo cáo; không được dùng lại số cũ.",
    )


def _add_appendix_e(doc: Document, data: dict[str, Any]) -> None:
    from PIL import Image

    add_h1(doc, "PHỤ LỤC E. THÔNG TIN 14 ẢNH THẬT")
    add_para(
        doc,
        "Bảng dưới liệt kê kích thước, loại biển, điều kiện và chuỗi nhãn của "
        "14 ảnh thật. Kích thước được đọc trực tiếp từ tệp ảnh.",
    )
    rows = []
    for label in data["user_labels"]:
        path = ROOT / "data" / "user_images" / label["image_name"]
        try:
            with Image.open(path) as image:
                size = f"{image.width}×{image.height}"
        except OSError:
            size = "—"
        rows.append(
            (
                label["image_name"],
                size,
                label["plate_type"],
                label["condition"],
                label["ground_truth"],
                label.get("notes", ""),
            )
        )
    add_table(
        doc,
        ["Ảnh", "Kích thước", "Loại", "Điều kiện", "GT", "Ghi chú"],
        rows,
        [2.0, 2.6, 2.2, 2.8, 2.8, 4.6],
        caption="Thông tin 14 ảnh thật",
        font_size=8.2,
        aligns=["left", "center", "center", "left", "left", "left"],
        note="Ghi chú giữ nguyên nội dung trong data/user_labels.csv.",
    )
    add_para(
        doc,
        "`8.jpg` là ảnh lớn nhất (2560×1244) và có 10 ký tự. Nhãn ghi series "
        "`MD7` không khớp quy ước thông thường; chuỗi nén `17MD799999` vẫn "
        "khớp regex cấu trúc `2 số + 1–2 chữ + 4–6 số` nếu hiểu theo cách "
        "tách `17 + MD + 799999`. Điều này minh họa rằng regex chỉ kiểm tra "
        "cấu trúc, không xác minh tính hợp pháp của biển.",
    )


def _add_appendix_f(doc: Document) -> None:
    add_h1(doc, "PHỤ LỤC F. CẤU TRÚC KẾT QUẢ ĐẦU RA")
    add_para(
        doc,
        "Mỗi lần chạy có thể sinh ra các tệp sau:",
    )
    add_table(
        doc,
        ["Tệp / thư mục", "Nội dung"],
        [
            ("results/*.csv", "Kết quả từng ảnh: trạng thái, chuỗi, IoU, CA, CSA, thời gian"),
            ("results/*_summary.json", "Tổng hợp PDR, precision, recall, CA, CSA, EPA, success rate"),
            ("results/*_summary.md", "Bản đọc nhanh bằng Markdown"),
            ("results/debug/<ảnh>/", "Ảnh gốc, cạnh, nhị phân, ứng viên, biển, ký tự"),
            ("reports/assets/", "Hình và biểu đồ dùng trong báo cáo"),
            ("reports/BaoCao.docx", "Báo cáo Word"),
            ("reports/BaoCao.pdf", "Bản PDF để kiểm tra bố cục"),
        ],
        [5.0, 12.0],
        caption="Các tệp kết quả và vai trò",
        font_size=9.0,
        aligns=["left", "left"],
    )
    add_para(
        doc,
        "Tên tệp debug được tạo từ tên ảnh gốc, đã loại ký tự không hợp lệ. "
        "Với ảnh trùng tên, hệ thống thêm hậu tố để tránh ghi đè. Các tệp CSV "
        "dùng UTF-8 có BOM để mở đúng tiếng Việt trong Excel.",
    )


# ======================================================================
# Điểm vào
# ======================================================================
def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    data = load_data()

    doc = Document()
    doc.core_properties.title = (
        "Xây dựng hệ thống nhận dạng biển số xe Việt Nam bằng xử lý ảnh truyền thống"
    )
    doc.core_properties.subject = "Báo cáo đồ án môn học"
    doc.core_properties.author = (
        "Nguyễn Đình Khải; Nguyễn Trung Tường; Bùi Văn Đạt"
    )
    doc.core_properties.keywords = (
        "nhận dạng biển số, OpenCV, Template Matching, xử lý ảnh truyền thống"
    )
    doc.core_properties.comments = "Sinh tự động bằng python-docx từ dữ liệu thực nghiệm."

    normal = doc.styles["Normal"]
    _style_font(normal, BODY_FONT, BODY_SIZE)
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    for style_name, size in [
        ("Heading 1", 16),
        ("Heading 2", 14),
        ("Heading 3", 13),
    ]:
        style = doc.styles[style_name]
        _style_font(style, BODY_FONT, size, bold=True, color=RGBColor(0, 0, 0))
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.space_before = Pt(12)
        style.paragraph_format.space_after = Pt(6)
        style.paragraph_format.line_spacing = 1.25

    section1 = doc.sections[0]
    setup_page(section1)
    _add_cover(doc)

    section2 = doc.add_section(WD_SECTION.NEW_PAGE)
    setup_page(section2)
    set_page_number_start(section2, 1)
    add_header_footer(
        section2,
        "Báo cáo đồ án — Nhận dạng biển số xe Việt Nam",
    )

    _add_declaration(doc)
    _add_acknowledgement(doc)
    _add_abstract(doc, data)
    _add_toc(doc)
    _add_abbreviations(doc)
    _add_list_of_figures(doc)
    _add_list_of_tables(doc)

    _add_chapter1(doc, data)
    _add_chapter2(doc, data)
    _add_chapter3(doc, data)
    _add_chapter4(doc, data)
    _add_chapter5(doc, data)
    _add_chapter6(doc, data)
    _add_references(doc)
    _add_appendix_a(doc)
    _add_appendix_b(doc)
    _add_appendix_c(doc)
    _add_appendix_d(doc, data)
    _add_appendix_e(doc, data)
    _add_appendix_f(doc)

    set_update_fields(doc)
    doc.save(OUT_DOCX)
    print(f"Đã tạo {OUT_DOCX}")
    print(f"Số đoạn: {len(doc.paragraphs)}, số bảng: {len(doc.tables)}")
    print(f"SHA-256 cấu hình: {data['config_hash']}")


if __name__ == "__main__":
    main()
