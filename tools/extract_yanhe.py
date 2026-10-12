from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Error, Page, TimeoutError, sync_playwright

COURSES_URL = (
    "https://aita.yanhekt.cn/personal/courseapi/vlabpassportapi/"
    "v1/account-profile/course"
)
COURSES_PAGE = "https://aita.yanhekt.cn/workbenchAi?tenant_code=21"


def _result(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("params", {}).get("result")
    if not isinstance(result, dict):
        raise TypeError(f"课程接口返回格式异常：{payload.get('message', '缺少 result')}")
    return result


def normalize_course(raw: dict[str, Any]) -> dict[str, Any]:
    information: dict[str, Any] = {}
    value = raw.get("information")
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                information = parsed
        except json.JSONDecodeError:
            pass
    elif isinstance(value, dict):
        information = value

    zhiyuan_id = raw.get("zhiyuan_id") or information.get("zhiyuan_id")
    return {
        "source": "yanhe",
        "name": raw.get("Title") or raw.get("title") or "未命名课程",
        "course_id": str(raw.get("Id") or raw.get("id") or ""),
        "zhiyuan_id": str(zhiyuan_id) if zhiyuan_id is not None else None,
        "course_code": information.get("kcwybm") or raw.get("course_code"),
        "teacher": raw.get("Teacher") or raw.get("teacher") or "",
        "term": raw.get("TermName") or raw.get("term_name"),
        "task_count": raw.get("progress", {}).get("subjectNum")
        if isinstance(raw.get("progress"), dict)
        else None,
    }


def _fetch_json(page: Page, url: str) -> dict[str, Any]:
    payload = page.evaluate(
        """
        async (url) => {
          const response = await fetch(url, { credentials: 'include' });
          if (!response.ok) throw new Error(`HTTP ${response.status}: ${url}`);
          return await response.json();
        }
        """,
        url,
    )
    if not isinstance(payload, dict):
        raise TypeError("课程接口没有返回 JSON 对象")
    return payload


def discover_courses(page: Page, per_page: int = 50) -> list[dict[str, Any]]:
    """Every call reads the current full course list; no course ID is cached or fixed."""
    first = _result(_fetch_json(page, f"{COURSES_URL}?nowpage=1&per-page={per_page}"))
    total = int(first.get("total") or 0)
    raw_courses = list(first.get("data") or [])
    page_count = max(1, math.ceil(total / per_page))
    for page_number in range(2, page_count + 1):
        result = _result(
            _fetch_json(page, f"{COURSES_URL}?nowpage={page_number}&per-page={per_page}")
        )
        raw_courses.extend(result.get("data") or [])

    courses: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_courses:
        if not isinstance(raw, dict):
            continue
        course = normalize_course(raw)
        identity = course["course_id"] or course["zhiyuan_id"] or course["name"]
        if identity in seen:
            continue
        seen.add(identity)
        courses.append(course)
    return courses


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="实时提取延河课堂全部课程及课程代码")
    parser.add_argument(
        "--profile", type=Path, default=Path(".data/web-probe-profile"), help="登录状态目录"
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts"), help="结果目录")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stamp = datetime.now().astimezone().strftime("yanhe-courses-%Y%m%d-%H%M%S")
    output_dir = args.output / stamp
    output_dir.mkdir(parents=True, exist_ok=True)
    args.profile.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=args.profile,
            channel="msedge",
            headless=True,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(COURSES_PAGE, wait_until="domcontentloaded", timeout=30_000)
            courses = discover_courses(page)
        except (Error, TimeoutError) as exc:
            raise RuntimeError("延河登录状态已失效，请先用网页探测工具重新登录") from exc
        finally:
            context.close()

    target = output_dir / "courses.json"
    target.write_text(json.dumps(courses, ensure_ascii=False, indent=2), encoding="utf-8")
    usable = sum(bool(course["zhiyuan_id"]) for course in courses)
    print(f"实时读取 {len(courses)} 门课程，其中 {usable} 门包含智园课程 ID。")
    print(f"结果：{target.resolve()}")


if __name__ == "__main__":
    main()
