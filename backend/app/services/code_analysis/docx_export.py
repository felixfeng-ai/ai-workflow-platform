from __future__ import annotations

from datetime import datetime
from io import BytesIO

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

FONT_NAME = "Microsoft YaHei"
BLACK = RGBColor(0, 0, 0)
WHITE = RGBColor(255, 255, 255)
HEADER_FILL = "1F4E79"
ALT_FILL = "F2F2F2"
BORDER_COLOR = "D9D9D9"


def _set_run_font(run, *, size: float = 10.5, bold: bool = False, color=BLACK) -> None:
    run.font.name = FONT_NAME
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), FONT_NAME)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), FONT_NAME)
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT_NAME)


def _style_paragraph(paragraph, *, before: float = 0, after: float = 6, line: float = 1.15) -> None:
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(before)
    fmt.space_after = Pt(after)
    fmt.line_spacing = line


def _add_text(paragraph, text: str, *, size: float = 10.5, bold: bool = False) -> None:
    run = paragraph.add_run(text)
    _set_run_font(run, size=size, bold=bold)


def _set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def _set_cell_margins(cell, top: int = 90, start: int = 100, bottom: int = 90, end: int = 100) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for edge, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def _set_table_borders(table) -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = f"w:{edge}"
        node = borders.find(qn(tag))
        if node is None:
            node = OxmlElement(tag)
            borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), "4")
        node.set(qn("w:space"), "0")
        node.set(qn("w:color"), BORDER_COLOR)


def _set_repeat_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def _remove_paragraph_borders(element) -> None:
    p_pr = element.get_or_add_pPr()
    borders = p_pr.find(qn("w:pBdr"))
    if borders is not None:
        p_pr.remove(borders)


def _format_table(table, *, header: bool = True, font_size: float = 9.5) -> None:
    _set_table_borders(table)
    table.autofit = True
    for row_index, row in enumerate(table.rows):
        if header and row_index == 0:
            _set_repeat_header(row)
        for cell in row.cells:
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            _set_cell_margins(cell)
            if header and row_index == 0:
                _set_cell_shading(cell, HEADER_FILL)
            elif row_index % 2 == 0:
                _set_cell_shading(cell, ALT_FILL)
            for paragraph in cell.paragraphs:
                _style_paragraph(paragraph, after=0, line=1.05)
                for run in paragraph.runs:
                    _set_run_font(
                        run,
                        size=font_size,
                        bold=header and row_index == 0,
                        color=WHITE if header and row_index == 0 else BLACK,
                    )


def _add_table(
    doc,
    headers: list[str],
    rows: list[list[str]],
    widths: list[float] | None = None,
    *,
    font_size: float = 9.5,
):
    table = doc.add_table(rows=1, cols=len(headers))
    for index, text in enumerate(headers):
        table.rows[0].cells[index].text = text
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            cells[index].text = value
    if widths:
        for row in table.rows:
            for index, width in enumerate(widths):
                row.cells[index].width = Inches(width)
    _format_table(table, font_size=font_size)
    doc.add_paragraph()
    return table


def _add_bullets(doc, values: list[str], empty_text: str = "无") -> None:
    if not values:
        values = [empty_text]
    for value in values:
        paragraph = doc.add_paragraph(style="List Bullet")
        _style_paragraph(paragraph, after=3, line=1.15)
        _add_text(paragraph, str(value))


def _add_section_heading(doc, text: str) -> None:
    paragraph = doc.add_paragraph(style="Heading 1")
    _style_paragraph(paragraph, before=12, after=6, line=1.1)
    _add_text(paragraph, text, size=15, bold=True)
    paragraph.paragraph_format.keep_with_next = True


def _add_footer(doc) -> None:
    section = doc.sections[0]
    footer = section.footer
    paragraph = footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_text(paragraph, "VeyaWork 雅秩 · 代码分析报告 · ", size=8.5)
    run = paragraph.add_run()
    _set_run_font(run, size=8.5)
    fld_char1 = OxmlElement("w:fldChar")
    fld_char1.set(qn("w:fldCharType"), "begin")
    instr_text = OxmlElement("w:instrText")
    instr_text.set(qn("xml:space"), "preserve")
    instr_text.text = "PAGE"
    fld_char2 = OxmlElement("w:fldChar")
    fld_char2.set(qn("w:fldCharType"), "end")
    run._r.append(fld_char1)
    run._r.append(instr_text)
    run._r.append(fld_char2)


def _configure_styles(doc) -> None:
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.orientation = WD_ORIENT.PORTRAIT
    section.top_margin = Inches(0.8)
    section.bottom_margin = Inches(0.75)
    section.left_margin = Inches(0.85)
    section.right_margin = Inches(0.85)

    normal = doc.styles["Normal"]
    normal.font.name = FONT_NAME
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = BLACK
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_NAME)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15

    title = doc.styles["Title"]
    title.font.name = FONT_NAME
    title.font.size = Pt(22)
    title.font.bold = True
    title.font.color.rgb = BLACK
    title._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_NAME)
    title.paragraph_format.space_before = Pt(0)
    title.paragraph_format.space_after = Pt(6)
    _remove_paragraph_borders(title._element)

    heading = doc.styles["Heading 1"]
    heading.font.name = FONT_NAME
    heading.font.size = Pt(15)
    heading.font.bold = True
    heading.font.color.rgb = BLACK
    heading._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_NAME)

    for style_name in ("List Bullet", "Table Grid"):
        style = doc.styles[style_name]
        style.font.name = FONT_NAME
        style.font.color.rgb = BLACK


def build_code_analysis_docx(
    report: dict,
    *,
    project_name: str,
    status: str,
    created_at: datetime | None = None,
) -> bytes:
    """把结构化分析报告渲染为可下载的 Word 文档。"""
    doc = Document()
    _configure_styles(doc)
    doc.core_properties.title = f"{project_name} 代码分析报告"
    doc.core_properties.subject = "代码提交分析报告"
    doc.core_properties.author = "VeyaWork 雅秩"

    title = doc.add_paragraph(style="Title")
    _add_text(title, "代码分析报告", size=22, bold=True)

    subtitle = doc.add_paragraph()
    _style_paragraph(subtitle, after=8, line=1.1)
    _add_text(subtitle, f"{project_name} · {report.get('branch', '')}", size=12.5, bold=True)

    intro = doc.add_paragraph()
    _style_paragraph(intro, after=10, line=1.2)
    _add_text(intro, str(report.get("summary") or "本次提交未提供摘要。"), size=11)

    created = created_at.strftime("%Y-%m-%d %H:%M") if created_at else "未记录"
    _add_section_heading(doc, "报告范围")
    _add_table(
        doc,
        ["项目", "仓库", "分支", "提交范围"],
        [
            [
                project_name,
                str(report.get("repo_full_name") or ""),
                str(report.get("branch") or ""),
                f"{str(report.get('before_sha') or '')[:10]} → {str(report.get('after_sha') or '')[:10]}",
            ]
        ],
        widths=[1.25, 2.0, 1.45, 2.0],
    )
    meta = doc.add_paragraph()
    _style_paragraph(meta, after=8)
    _add_text(meta, f"报告状态：{status}    生成时间：{created}", size=9.5)

    scale = report.get("change_scale") or {}
    _add_section_heading(doc, "变更概览")
    _add_table(
        doc,
        ["提交", "文件", "新增行", "删除行", "涉及语言"],
        [
            [
                str(scale.get("commits", 0)),
                str(scale.get("files", 0)),
                str(scale.get("additions", 0)),
                str(scale.get("deletions", 0)),
                "、".join((scale.get("languages") or {}).keys()) or "未识别",
            ]
        ],
        widths=[0.8, 0.8, 1.0, 1.0, 3.1],
    )

    _add_section_heading(doc, "Commit 摘要")
    commit_rows = [
        [
            str(commit.get("sha") or "")[:10],
            str(commit.get("author") or ""),
            str(commit.get("message") or ""),
        ]
        for commit in report.get("commits") or []
    ]
    if commit_rows:
        _add_table(doc, ["SHA", "作者", "提交说明"], commit_rows, widths=[1.0, 1.1, 4.6])
    else:
        _add_text(doc.add_paragraph(), "本次提交范围未提供 Commit 详情。")

    _add_section_heading(doc, "功能点")
    points = report.get("functional_points") or []
    if points:
        for item in points:
            paragraph = doc.add_paragraph()
            _style_paragraph(paragraph, before=5, after=2)
            _add_text(paragraph, str(item.get("title") or "未命名功能点"), size=11, bold=True)
            paragraph.paragraph_format.keep_with_next = True
            body = doc.add_paragraph()
            _style_paragraph(body, after=3)
            _add_text(body, str(item.get("description") or ""))
            files = item.get("files") or []
            if files:
                evidence = doc.add_paragraph()
                _style_paragraph(evidence, after=5)
                _add_text(evidence, f"相关文件：{', '.join(map(str, files))}", size=9)
    else:
        _add_text(doc.add_paragraph(), "报告未识别出明确功能点。")

    _add_section_heading(doc, "边界与接口")
    boundaries = report.get("boundaries") or []
    if boundaries:
        _add_table(
            doc,
            ["模块", "边界类型", "说明", "证据"],
            [
                [
                    str(item.get("module") or ""),
                    str(item.get("boundary_type") or ""),
                    str(item.get("description") or ""),
                    "、".join(map(str, item.get("evidence") or [])),
                ]
                for item in boundaries
            ],
            widths=[1.2, 0.9, 2.7, 1.9],
        )
    else:
        _add_text(doc.add_paragraph(), "未识别到接口或模块边界变化。")

    _add_section_heading(doc, "状态管理")
    states = report.get("state_management") or []
    if states:
        _add_table(
            doc,
            ["区域", "机制", "风险", "证据"],
            [
                [
                    str(item.get("area") or ""),
                    str(item.get("mechanism") or ""),
                    str(item.get("risk") or ""),
                    "、".join(map(str, item.get("evidence") or [])),
                ]
                for item in states
            ],
            widths=[1.2, 1.3, 2.7, 1.5],
        )
    else:
        _add_text(doc.add_paragraph(), "未识别到明确的状态管理变化。")

    _add_section_heading(doc, "数据结构与影响范围")
    data_structures = report.get("data_structures") or []
    data_paragraph = doc.add_paragraph()
    _style_paragraph(data_paragraph, after=4)
    _add_text(
        data_paragraph,
        f"数据结构：{'、'.join(map(str, data_structures)) if data_structures else '未识别到数据结构变化。'}",
    )
    impact = report.get("impact") or {}
    _add_text(doc.add_paragraph(), "直接影响", size=11, bold=True)
    _add_bullets(doc, [str(item) for item in impact.get("direct") or []])
    _add_text(doc.add_paragraph(), "间接影响", size=11, bold=True)
    _add_bullets(doc, [str(item) for item in impact.get("indirect") or []])
    contracts = impact.get("external_contracts") or []
    if contracts:
        _add_text(doc.add_paragraph(), "外部契约", size=11, bold=True)
        _add_bullets(doc, [str(item) for item in contracts])

    _add_section_heading(doc, "安全发现")
    scans = report.get("security_scans") or {}
    scan_text = doc.add_paragraph()
    _style_paragraph(scan_text, after=4)
    _add_text(
        scan_text,
        f"Secret 扫描：{scans.get('secret_scan', '未运行')}    Semgrep：{scans.get('semgrep', '未运行')}",
        size=9.5,
    )
    findings = report.get("security_findings") or []
    if findings:
        _add_table(
            doc,
            ["级别", "标题", "文件位置", "来源", "建议"],
            [
                [
                    str(item.get("severity") or ""),
                    str(item.get("title") or ""),
                    f"{item.get('file') or ''}:{item.get('line') or ''}",
                    str(item.get("source") or ""),
                    str(item.get("recommendation") or ""),
                ]
                for item in findings
            ],
            widths=[0.7, 1.35, 1.55, 0.8, 2.3],
            font_size=8.5,
        )
    else:
        _add_text(
            doc.add_paragraph(),
            "没有确定性安全命中项。这不代表代码绝对安全，仍需人工复核。",
        )

    _add_section_heading(doc, "测试缺口")
    _add_bullets(doc, [str(item) for item in report.get("test_gaps") or []], "未检测到明显测试缺口。")

    _add_section_heading(doc, "人工复核清单")
    _add_bullets(doc, [str(item) for item in report.get("review_checklist") or []])

    _add_section_heading(doc, "未知项与限制")
    _add_text(doc.add_paragraph(), "未知项", size=11, bold=True)
    _add_bullets(doc, [str(item) for item in report.get("unknowns") or []], "无")
    _add_text(doc.add_paragraph(), "报告限制", size=11, bold=True)
    _add_bullets(doc, [str(item) for item in report.get("limitations") or []], "无")

    _add_footer(doc)
    output = BytesIO()
    doc.save(output)
    return output.getvalue()
