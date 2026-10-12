from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from playwright.sync_api import Error, sync_playwright

from mooc_deadlines.yanhe import discover_courses, extract_deadlines, save_snapshot

COURSES_PAGE = "https://aita.yanhekt.cn/workbenchAi?tenant_code=21"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="用真实登录态验证延河课堂课程和任务接口")
    parser.add_argument(
        "--profile", type=Path, default=Path(".data/web-probe-profile"), help="浏览器登录目录"
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts"), help="验证结果目录")
    return parser.parse_args()


def wait_for_login(message: str) -> None:
    print(message)
    print("认证完成后回到此窗口按回车，Python 将直接读取接口；无需逐页打开课程。")
    input()


def read_courses(context: Any, page: Any) -> list[dict[str, Any]]:
    try:
        return discover_courses(context)
    except PermissionError:
        page.goto(COURSES_PAGE, wait_until="domcontentloaded", timeout=30_000)
        wait_for_login("请在 Edge 中完成延河课堂认证，并停留在课程列表页。")
        return discover_courses(context)


def read_deadlines(
    context: Any, page: Any, courses: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    report: list[dict[str, Any]] = []
    deadlines = extract_deadlines(context, courses, report)
    if report and any(item["ok"] for item in report):
        return deadlines, report

    mapped = next((course for course in courses if course.get("learn_url")), None)
    if mapped is None:
        return deadlines, report
    page.goto(mapped["learn_url"], wait_until="domcontentloaded", timeout=30_000)
    wait_for_login("请在 Edge 中完成智园课堂认证。")
    report = []
    return extract_deadlines(context, courses, report), report


def main() -> None:
    args = parse_args()
    args.profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=args.profile,
            channel="msedge",
            headless=False,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            courses = read_courses(context, page)
            deadlines, report = read_deadlines(context, page, courses)
        except Error as exc:
            raise RuntimeError(f"浏览器或网络访问失败：{exc}") from exc
        finally:
            try:
                context.close()
            except Error:
                pass

    output_dir = save_snapshot(courses, deadlines, args.output)
    successful = [item for item in report if item["ok"]]
    failed = [item for item in report if not item["ok"]]
    summary = {
        "courses": len(courses),
        "courses_with_zhiyuan_id": sum(bool(course.get("zhiyuan_id")) for course in courses),
        "requests": len(report),
        "successful_requests": len(successful),
        "failed_requests": len(failed),
        "tasks": len(deadlines),
        "task_types": dict(Counter(item["task_type"] for item in deadlines)),
        "http_statuses": dict(Counter(str(item["status"]) for item in report)),
    }
    (output_dir / "validation-report.json").write_text(
        json.dumps({"summary": summary, "requests": report}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"验证结果：{output_dir.resolve()}")


if __name__ == "__main__":
    main()
