import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools" / "extract_yanhe.py"
SPEC = importlib.util.spec_from_file_location("extract_yanhe", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_normalize_course_uses_current_api_identifiers() -> None:
    course = MODULE.normalize_course(
        {
            "Id": 115414,
            "Title": "示例课程",
            "Teacher": "示例教师",
            "information": '{"kcwybm":"2026-CODE","zhiyuan_id":23380}',
            "progress": {"subjectNum": 8},
        }
    )

    assert course["course_id"] == "115414"
    assert course["zhiyuan_id"] == "23380"
    assert course["course_code"] == "2026-CODE"
    assert course["task_count"] == 8


def test_normalize_course_accepts_missing_course_code() -> None:
    course = MODULE.normalize_course(
        {"Id": 116322, "Title": "实验课", "zhiyuan_id": "23492", "information": "{}"}
    )

    assert course["zhiyuan_id"] == "23492"
    assert course["course_code"] is None
