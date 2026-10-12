from datetime import UTC, datetime

from mooc_deadlines.yanhe import (
    _task,
    current_term_name,
    extract_announcements,
    extract_deadlines,
    extract_todos,
    normalize_course,
)


def test_course_ids_are_taken_from_current_response() -> None:
    course = normalize_course(
        {
            "Id": 12,
            "Title": "电路",
            "information": '{"kcwybm":"NEW-CODE","zhiyuan_id":34567}',
            "progress": {"learnNum": 1, "subjectNum": 2},
        }
    )
    assert course["course_code"] == "NEW-CODE"
    assert course["zhiyuan_id"] == "34567"
    assert "/course/34567/" in course["learn_url"]


def test_deadline_normalization() -> None:
    course = {"name": "电路", "zhiyuan_id": "34567"}
    task = _task(
        {"id": 9, "title": "第一周作业", "deadline": "2026-10-10T15:59:00Z"},
        course,
        "assignment",
        "homework",
    )
    assert task is not None
    assert task["course_id"] == "34567"
    assert task["completed"] is False


class _Response:
    def __init__(self, payload=None, status=200) -> None:
        self._payload = payload or {}
        self.status = status
        self.ok = status == 200

    def json(self):
        return self._payload


class _Requests:
    def get(self, url, params=None):
        if "/api/todos" in url:
            return _Response(
                {
                    "todo_list": [
                        {
                            "id": 8,
                            "course_id": 34567,
                            "title": "待交作业",
                            "type": "homework",
                            "end_time": "2026-11-29T15:59:00Z",
                        },
                        {
                            "id": 9,
                            "course_id": 99999,
                            "title": "其他学期任务",
                            "type": "exam",
                            "end_time": "2026-12-01T15:59:00Z",
                        },
                    ]
                }
            )
        if url.endswith("homework-activities"):
            return _Response(
                {
                    "homework_activities": [
                        {
                            "id": 1,
                            "title": "作业",
                            "deadline": "2026-10-10T15:59:00Z",
                            "score": 0,
                        }
                    ]
                }
            )
        if url.endswith("exam-list"):
            return _Response(status=403)
        return _Response({"questionnaires": []})


class _Context:
    request = _Requests()


def test_deadline_extraction_keeps_partial_success_and_reports_failures() -> None:
    report = []
    deadlines = extract_deadlines(
        _Context(), [{"name": "课程", "zhiyuan_id": "34567"}], report
    )

    assert len(deadlines) == 1
    assert deadlines[0]["score"] == 0
    assert [item["status"] for item in report] == [200, 403, 200]


def test_current_term_name() -> None:
    assert current_term_name(datetime(2026, 10, 11, tzinfo=UTC)) == "2026-2027-1"
    assert current_term_name(datetime(2027, 1, 10, tzinfo=UTC)) == "2026-2027-1"
    assert current_term_name(datetime(2027, 3, 1, tzinfo=UTC)) == "2026-2027-2"


def test_global_todos_are_filtered_to_selected_courses() -> None:
    deadlines = extract_todos(
        _Context(), [{"name": "课程", "zhiyuan_id": "34567"}]
    )

    assert len(deadlines) == 1
    assert deadlines[0]["task_id"] == "8"
    assert deadlines[0]["completed"] is False


class _AnnouncementRequests:
    def get(self, url, params=None):
        if url.endswith("/api/courses/34567/bulletins"):
            return _Response(
                {
                    "bulletins": [
                        {
                            "id": 7,
                            "course_id": 34567,
                            "title": "调课通知",
                            "content": "<p>本周课程调整到周五。</p>",
                            "created_at": "2026-10-11T08:00:00+08:00",
                        }
                    ]
                }
            )
        return _Response(status=404)


class _AnnouncementContext:
    request = _AnnouncementRequests()


def test_announcement_feeds_are_normalized_without_course_page_requests() -> None:
    report = []
    announcements = extract_announcements(
        _AnnouncementContext(),
        [{"name": "电路", "zhiyuan_id": "34567"}],
        report,
    )

    assert len(announcements) == 1
    course_notice = announcements[0]
    assert course_notice["source"] == "yanhe"
    assert course_notice["course"] == "电路"
    assert course_notice["content"] == "本周课程调整到周五。"
    assert course_notice["url"].endswith("/course/34567/bulletin")
    assert len(report) == 1
    assert report[0]["endpoint"] == "bulletins"
