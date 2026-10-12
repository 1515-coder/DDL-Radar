from __future__ import annotations

import json
import re
from html import unescape
from typing import Any

from playwright.sync_api import BrowserContext, Error

ECLASS_COURSES_API = "https://zy-eclass.bit.edu.cn/api/courses"
YANHE_MESSAGES_API = "https://aita.yanhekt.cn/messageapi/api/msg/lists"

SECTION_DEFINITIONS = (
    ("activities", "activities", "章节", {"fields": "id,title,type,uploads,course_id", "no-intercept": "true", "sub_course_id": 0}),
    ("classroom-list", "classrooms", "课堂", {}),
    ("interactions", "interactions", "互动", {"conditions": '{"category":"all","itemsSortBy":{"predicate":"created_at","reverse":true}}'}),
    ("group-sets", "group_sets", "分组学习", {"preload_id": 0}),
    ("notes", "notes", "笔记", {"conditions": '{"activity_ids":[],"keyword":""}', "page": 1, "page_size": 100}),
    ("correction-books", "correction_books", "练习本", {"conditions": '{"keyword":""}', "page": 1, "page_size": 100}),
    ("topic-categories", "topic_categories", "讨论", {"conditions": '{"itemsSortBy":{"predicate":"created_at","reverse":true},"is_in_progress":true}', "page": 1, "page_size": 100}),
)
SECTION_ENDPOINTS = {definition[0] for definition in SECTION_DEFINITIONS}

SECTION_PATHS = {
    "章节": "learning-activity",
    "课堂": "classroom",
    "互动": "interaction",
    "分组学习": "group-set#/",
    "笔记": "notebook#/",
    "练习本": "correction-books",
    "讨论": "forum",
}


def _plain_text(value: Any) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(value))
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _items(payload: Any, collection: str) -> list[dict[str, Any]]:
    value = payload.get(collection, []) if isinstance(payload, dict) else []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _normalize_item(
    raw: dict[str, Any], course: dict[str, Any], category: str
) -> dict[str, Any]:
    course_id = str(course.get("zhiyuan_id") or "")
    title = (
        raw.get("title")
        or raw.get("name")
        or raw.get("subject")
        or raw.get("description")
        or f"{category}项目"
    )
    content = raw.get("content") or raw.get("body") or raw.get("remark") or ""
    count = None
    for key in ("group_count", "member_count", "student_count", "count"):
        if raw.get(key) is not None:
            count = raw.get(key)
            break
    return {
        "source": "yanhe",
        "course": course.get("name") or f"课程-{course_id}",
        "course_id": course_id,
        "category": category,
        "activity_type": raw.get("type"),
        "id": str(raw.get("id") or ""),
        "title": _plain_text(title),
        "content": _plain_text(content),
        "count": count,
        "upload_count": len(raw.get("uploads") or [])
        if isinstance(raw.get("uploads"), list)
        else 0,
        "created_at": raw.get("created_at") or raw.get("updated_at"),
        "url": f"https://zy-eclass.bit.edu.cn/course/{course_id}/{SECTION_PATHS[category]}",
    }


def extract_course_sections(
    context: BrowserContext,
    courses: list[dict[str, Any]],
    report: list[dict[str, Any]] | None = None,
    selected: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Inspect every supported section for every selected course, retaining empty counts."""
    content: list[dict[str, Any]] = []
    for course in courses:
        course_id = str(course.get("zhiyuan_id") or "")
        if not course_id:
            continue
        for endpoint, collection, category, params in SECTION_DEFINITIONS:
            if selected is not None and endpoint not in selected:
                continue
            response = context.request.get(
                f"{ECLASS_COURSES_API}/{course_id}/{endpoint}", params=params
            )
            entry: dict[str, Any] = {
                "course": course.get("name"),
                "course_id": course_id,
                "endpoint": endpoint,
                "category": category,
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
                entry.update(ok=False, error="invalid-json")
                if report is not None:
                    report.append(entry)
                continue
            raw_items = _items(payload, collection)
            entry["items"] = len(raw_items)
            if report is not None:
                report.append(entry)
            content.extend(_normalize_item(item, course, category) for item in raw_items)
    return content

