from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

TASK_COLUMNS = {
    "course": "课程",
    "title": "任务",
    "task_type": "类型",
    "due_at": "截止时间",
    "completed": "是否完成",
    "score": "得分",
    "total_score": "总分",
    "course_id": "课程 ID",
    "term_id": "学期 ID",
    "task_id": "任务 ID",
    "url": "课程链接",
}
COURSE_COLUMNS = {
    "name": "课程",
    "school": "学校",
    "start_at": "开始时间",
    "end_at": "结束时间",
    "is_active": "正在进行",
    "learned_lessons": "已学课时",
    "total_lessons": "总课时",
    "course_id": "课程 ID",
    "term_id": "学期 ID",
    "learn_url": "课程链接",
}


def _display_value(key: str, value: Any) -> Any:
    if isinstance(value, bool):
        if key == "completed":
            return "是" if value else "否"
        return "是" if value else "否"
    return "" if value is None else value


def export_json(data: dict[str, Any]) -> bytes:
    payload = {
        "account": data.get("account"),
        "exported_at": datetime.now().astimezone().isoformat(),
        "courses": data.get("courses", []),
        "deadlines": data.get("deadlines", []),
        "announcements": data.get("announcements", []),
        "course_content": data.get("course_content", []),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def export_csv(deadlines: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(TASK_COLUMNS.values())
    for task in deadlines:
        writer.writerow([_display_value(key, task.get(key)) for key in TASK_COLUMNS])
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _sheet_xml(rows: list[list[Any]]) -> str:
    xml_rows: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells: list[str] = []
        for column_index, value in enumerate(row, start=1):
            reference = f"{_column_name(column_index)}{row_index}"
            style = ' s="1"' if row_index == 1 else ""
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{reference}"{style}><v>{value}</v></c>')
            else:
                text = escape(str(value))
                cells.append(
                    f'<c r="{reference}" t="inlineStr"{style}><is><t>{text}</t></is></c>'
                )
        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    last_column = _column_name(max((len(row) for row in rows), default=1))
    last_row = max(len(rows), 1)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:{last_column}{last_row}"/><sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews><cols>'
        f'<col min="1" max="{len(rows[0]) if rows else 1}" width="18" customWidth="1"/>'
        f'</cols><sheetData>{"".join(xml_rows)}</sheetData>'
        f'<autoFilter ref="A1:{last_column}{last_row}"/></worksheet>'
    )


def export_xlsx(courses: list[dict[str, Any]], deadlines: list[dict[str, Any]]) -> bytes:
    task_rows = [list(TASK_COLUMNS.values())] + [
        [_display_value(key, task.get(key)) for key in TASK_COLUMNS] for task in deadlines
    ]
    course_rows = [list(COURSE_COLUMNS.values())] + [
        [_display_value(key, course.get(key)) for key in COURSE_COLUMNS] for course in courses
    ]
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '</Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="任务" sheetId="1" r:id="rId1"/>'
            '<sheet name="课程" sheetId="2" r:id="rId2"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>',
        )
        archive.writestr(
            "xl/styles.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="11"/><name val="Microsoft YaHei"/></font>'
            '<font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Microsoft YaHei"/></font></fonts>'
            '<fills count="3"><fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="gray125"/></fill>'
            '<fill><patternFill patternType="solid"><fgColor rgb="FF10233F"/><bgColor indexed="64"/></patternFill></fill></fills>'
            '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
            '<cellXfs count="2"><xf fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            '</styleSheet>',
        )
        archive.writestr("xl/worksheets/sheet1.xml", _sheet_xml(task_rows))
        archive.writestr("xl/worksheets/sheet2.xml", _sheet_xml(course_rows))
    return output.getvalue()
