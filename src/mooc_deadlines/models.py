from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class TaskType(StrEnum):
    ASSIGNMENT = "assignment"
    QUIZ = "quiz"
    EXAM = "exam"
    OTHER = "other"


@dataclass(slots=True)
class Course:
    name: str
    url: str | None = None
    course_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Deadline:
    course: Course
    title: str
    task_type: TaskType
    due_at: datetime | None
    url: str | None = None
    completed: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["task_type"] = self.task_type.value
        result["due_at"] = self.due_at.isoformat() if self.due_at else None
        return result
