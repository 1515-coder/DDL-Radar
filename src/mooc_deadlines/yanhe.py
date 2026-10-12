from __future__ import annotations

import json
import math
import re
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Error

AITA_COURSES_API = (
    "https://aita.yanhekt.cn/personal/courseapi/vlabpassportapi/"
    "v1/account-profile/course"
)
ECLASS_API = "https://zy-eclass.bit.edu.cn/api/courses"
ECLASS_TODOS_API = "https://zy-eclass.bit.edu.cn/api/todos?no-intercept=true"
YANHE_WORKBENCH_URL = "https://aita.yanhekt.cn/workbenchAi?tenant_code=21"


def _json_object(response: Any, label: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except (Error, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}返回了空内容或非 JSON 数据") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"{label}返回格式异常")
    return payload


def _aita_result(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("params", {}).get("result")
    if not isinstance(result, dict):
        raise PermissionError("延河课堂登录状态无效")
    return result


def normalize_course(raw: dict[str, Any]) -> dict[str, Any]:
    information: dict[str, Any] = {}
    try:
        value = raw.get("information") or "{}"
        information = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        pass
    zhiyuan_id = raw.get("zhiyuan_id") or information.get("zhiyuan_id")
    return {
        "source": "yanhe",
        "name": raw.get("Title") or "未命名课程",
        "course_id": str(raw.get("Id") or ""),
        "zhiyuan_id": str(zhiyuan_id) if zhiyuan_id else None,
        "course_code": information.get("kcwybm"),
        "school": raw.get("KkxyName") or "北京理工大学",
        "teacher": raw.get("Teacher") or "",
        "term": raw.get("TermName"),
        "is_active": False,
        "learned_lessons": raw.get("progress", {}).get("learnNum", 0),
        "total_lessons": raw.get("progress", {}).get("subjectNum", 0),
        "learn_url": (
            f"https://zy-eclass.bit.edu.cn/course/{zhiyuan_id}/homework"
            if zhiyuan_id
            else None
        ),
    }


def current_term_name(now: datetime | None = None) -> str:
    """Return the conventional BIT academic term for the current local date."""
    current = now or datetime.now().astimezone()
    if current.month >= 8:
        return f"{current.year}-{current.year + 1}-1"
    if current.month <= 2:
        return f"{current.year - 1}-{current.year}-1"
    return f"{current.year - 1}-{current.year}-2"


def discover_courses(context: BrowserContext, per_page: int = 50) -> list[dict[str, Any]]:
    """Read every current course page on each extraction; IDs are never fixed."""
    first_response = context.request.get(
        AITA_COURSES_API, params={"nowpage": 1, "per-page": per_page}
    )
    if not first_response.ok:
        raise PermissionError("延河课堂登录状态无效")
    try:
        first = _aita_result(_json_object(first_response, "延河课程接口"))
    except (TypeError, ValueError) as exc:
        raise PermissionError("延河课堂课程接口未返回有效数据，请重新认证") from exc
    total = int(first.get("total") or 0)
    raw_courses = list(first.get("data") or [])
    actual_page_size = int(first.get("per-page") or len(raw_courses) or per_page)
    for page_number in range(2, max(1, math.ceil(total / actual_page_size)) + 1):
        response = context.request.get(
            AITA_COURSES_API, params={"nowpage": page_number, "per-page": per_page}
        )
        if response.ok:
            try:
                raw_courses.extend(
                    _aita_result(_json_object(response, "延河课程接口")).get("data") or []
                )
            except (PermissionError, TypeError, ValueError):
                continue
    courses = [normalize_course(item) for item in raw_courses if isinstance(item, dict)]
    courses = list({course["course_id"]: course for course in courses}.values())
    expected_term = current_term_name()
    available_terms = {course.get("term") for course in courses if course.get("term")}
    active_term = expected_term if expected_term in available_terms else max(available_terms, default=None)
    for course in courses:
        course["is_active"] = course.get("term") == active_term
    return courses


def extract_todos(
    context: BrowserContext, courses: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Read the global pending-task feed in one request and keep selected courses only."""
    response = context.request.get(ECLASS_TODOS_API)
    if not response.ok:
        raise PermissionError("智园课堂登录状态无效")
    try:
        payload = _json_object(response, "智园待办接口")
    except (TypeError, ValueError) as exc:
        raise TypeError(str(exc)) from exc
    raw_items = payload.get("todo_list", []) if isinstance(payload, dict) else []
    if not isinstance(raw_items, list):
        raise TypeError("智园待办接口返回格式异常")
    by_id = {str(course.get("zhiyuan_id")): course for course in courses}
    type_map = {
        "homework": ("assignment", "homework"),
        "exam": ("exam", "exam#/"),
        "questionnaire": ("quiz", "questionnaire#/"),
        "quiz": ("quiz", "questionnaire#/"),
    }
    deadlines: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        course_id = str(raw.get("course_id") or "")
        course = by_id.get(course_id)
        due_at = raw.get("end_time")
        mapping = type_map.get(str(raw.get("type") or "").lower())
        if course is None or not due_at or mapping is None:
            continue
        task_type, section = mapping
        deadlines.append(
            {
                "source": "yanhe",
                "course": course["name"],
                "course_id": course_id,
                "task_id": str(raw.get("id") or ""),
                "title": raw.get("title") or "未命名任务",
                "task_type": task_type,
                "due_at": due_at,
                "completed": False,
                "score": None,
                "total_score": None,
                "url": f"https://zy-eclass.bit.edu.cn/course/{course_id}/{section}",
            }
        )
    return deadlines


def _task(
    raw: dict[str, Any], course: dict[str, Any], task_type: str, section: str
) -> dict[str, Any] | None:
    due_at = raw.get("deadline") or raw.get("end_time") or raw.get("closed_time")
    if not due_at:
        return None
    submitted = bool(
        raw.get("submitted")
        or raw.get("user_submit_count")
        or raw.get("final_score") is not None
        or raw.get("user_submission")
    )
    course_id = course["zhiyuan_id"]
    score = raw.get("final_score")
    if score is None:
        score = raw.get("score")
    return {
        "source": "yanhe",
        "course": course["name"],
        "course_id": course_id,
        "task_id": str(raw.get("id") or ""),
        "title": raw.get("title") or raw.get("name") or "未命名任务",
        "task_type": task_type,
        "due_at": due_at,
        "completed": submitted,
        "score": score,
        "total_score": raw.get("total_score"),
        "url": f"https://zy-eclass.bit.edu.cn/course/{course_id}/{section}",
    }


def extract_deadlines(
    context: BrowserContext,
    courses: list[dict[str, Any]],
    report: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    definitions = (
        ("homework-activities", "homework_activities", "assignment", "homework"),
        ("exam-list", "exams", "exam", "exam#/"),
        ("questionnaire-list", "questionnaires", "quiz", "questionnaire#/"),
    )
    deadlines: list[dict[str, Any]] = []
    query = {
        "conditions": '{"itemsSortBy":{"predicate":"module","reverse":false}}',
        "page": 1,
        "page_size": 100,
        "reloadPage": "true",
    }
    for course in courses:
        course_id = course.get("zhiyuan_id")
        if not course_id:
            continue
        for endpoint, collection, task_type, section in definitions:
            response = context.request.get(f"{ECLASS_API}/{course_id}/{endpoint}", params=query)
            result = {
                "course_id": course_id,
                "endpoint": endpoint,
                "status": response.status,
                "ok": response.ok,
                "items": 0,
            }
            if not response.ok:
                if report is not None:
                    report.append(result)
                continue
            try:
                payload = _json_object(response, "智园课程任务接口")
            except (TypeError, ValueError) as exc:
                result["ok"] = False
                result["error"] = str(exc)
                if report is not None:
                    report.append(result)
                continue
            raw_items = payload.get(collection, [])
            if not isinstance(raw_items, list):
                raw_items = []
            result["items"] = len(raw_items)
            if report is not None:
                report.append(result)
            for raw in raw_items:
                item = _task(raw, course, task_type, section)
                if item is not None:
                    deadlines.append(item)
    return deadlines


def _plain_text(value: Any) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(value))
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _normalize_announcement(
    raw: dict[str, Any], source: str, course_names: dict[str, str]
) -> dict[str, Any]:
    course_value = raw.get("course") if isinstance(raw.get("course"), dict) else {}
    course_id = str(
        raw.get("course_id")
        or raw.get("courseId")
        or course_value.get("id")
        or ""
    )
    title = (
        raw.get("title")
        or raw.get("name")
        or raw.get("subject")
        or raw.get("notice_title")
        or "未命名公告"
    )
    content = (
        raw.get("content")
        or raw.get("body")
        or raw.get("description")
        or raw.get("summary")
        or raw.get("notice_content")
        or ""
    )
    published_at = (
        raw.get("published_at")
        or raw.get("publish_at")
        or raw.get("publish_time")
        or raw.get("created_at")
        or raw.get("created_time")
        or raw.get("create_time")
    )
    course = (
        raw.get("course_name")
        or raw.get("courseName")
        or course_value.get("name")
        or course_names.get(course_id)
        or ("学校公告" if source == "zhiyuan-school" else "平台公告")
    )
    if course_id:
        url = f"https://zy-eclass.bit.edu.cn/course/{course_id}/bulletin"
    elif source == "yanhe":
        url = YANHE_WORKBENCH_URL
    else:
        url = "https://zy-eclass.bit.edu.cn/"
    return {
        "source": source,
        "id": str(raw.get("id") or raw.get("bulletin_id") or raw.get("notice_id") or ""),
        "course": course,
        "course_id": course_id or None,
        "title": _plain_text(title),
        "content": _plain_text(content),
        "published_at": published_at,
        "url": raw.get("url") or raw.get("link") or url,
    }


def extract_announcements(
    context: BrowserContext,
    courses: list[dict[str, Any]],
    report: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Read the actual bulletin section for every selected course."""
    course_names = {
        str(course.get("zhiyuan_id")): str(course.get("name") or "")
        for course in courses
        if course.get("zhiyuan_id")
    }
    announcements: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    query = {"conditions": '{"start_date":"","end_date":"","keyword":""}'}
    for course in courses:
        course_id = str(course.get("zhiyuan_id") or "")
        if not course_id:
            continue
        response = context.request.get(
            f"{ECLASS_API}/{course_id}/bulletins", params=query
        )
        entry: dict[str, Any] = {
            "course_id": course_id,
            "endpoint": "bulletins",
            "status": response.status,
            "ok": response.ok,
            "items": 0,
        }
        if not response.ok:
            if report is not None:
                report.append(entry)
            continue
        try:
            payload = response.json()
        except (Error, ValueError, json.JSONDecodeError):
            entry["ok"] = False
            entry["error"] = "invalid-json"
            if report is not None:
                report.append(entry)
            continue
        raw_items = payload.get("bulletins", []) if isinstance(payload, dict) else []
        if not isinstance(raw_items, list):
            raw_items = []
        entry["items"] = len(raw_items)
        if report is not None:
            report.append(entry)
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            item = _normalize_announcement(
                {**raw, "course_id": course_id}, "yanhe", course_names
            )
            identity = ("yanhe", item["id"], f"{item['title']}|{item['published_at']}")
            if identity in seen:
                continue
            seen.add(identity)
            announcements.append(item)
    announcements.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)
    return announcements


def save_snapshot(
    courses: list[dict[str, Any]],
    deadlines: list[dict[str, Any]],
    output_root: Path,
    announcements: list[dict[str, Any]] | None = None,
    request_report: list[dict[str, Any]] | None = None,
    course_content: list[dict[str, Any]] | None = None,
) -> Path:
    stamp = datetime.now().astimezone().strftime("yanhe-extract-%Y%m%d-%H%M%S")
    output_dir = output_root / stamp
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "courses.json").write_text(
        json.dumps(courses, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "deadlines.json").write_text(
        json.dumps(deadlines, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if announcements is not None:
        (output_dir / "announcements.json").write_text(
            json.dumps(announcements, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    (output_dir / "request-report.json").write_text(
        json.dumps(request_report or [], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if course_content is not None:
        (output_dir / "course-content.json").write_text(
            json.dumps(course_content, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return output_dir
