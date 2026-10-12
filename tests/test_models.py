from datetime import UTC, datetime

from mooc_deadlines.models import Course, Deadline, TaskType


def test_deadline_serialization() -> None:
    deadline = Deadline(
        course=Course(name="示例课程", course_id="42"),
        title="第一单元测验",
        task_type=TaskType.QUIZ,
        due_at=datetime(2026, 10, 5, 23, 59, tzinfo=UTC),
        completed=False,
    )

    result = deadline.to_dict()

    assert result["course"]["name"] == "示例课程"
    assert result["task_type"] == "quiz"
    assert result["due_at"] == "2026-10-05T23:59:00+00:00"
