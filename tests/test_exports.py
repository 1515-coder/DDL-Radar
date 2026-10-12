import csv
import io
import json
from zipfile import ZipFile

from mooc_deadlines.exports import export_csv, export_json, export_xlsx


def sample_data():
    course = {"name": "Python", "school": "示例大学", "course_id": 1, "term_id": 2}
    task = {
        "course": "Python",
        "title": "第一周测验",
        "task_type": "quiz",
        "due_at": "2026-10-10T20:00:00+08:00",
        "completed": False,
    }
    return {"account": {"name": "测试"}, "courses": [course], "deadlines": [task]}


def test_export_formats_are_valid() -> None:
    data = sample_data()
    assert json.loads(export_json(data).decode())["deadlines"][0]["title"] == "第一周测验"
    rows = list(csv.reader(io.StringIO(export_csv(data["deadlines"]).decode("utf-8-sig"))))
    assert rows[1][1] == "第一周测验"

    with ZipFile(io.BytesIO(export_xlsx(data["courses"], data["deadlines"]))) as workbook:
        assert "xl/worksheets/sheet1.xml" in workbook.namelist()
        assert "第一周测验" in workbook.read("xl/worksheets/sheet1.xml").decode()
