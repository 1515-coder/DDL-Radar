from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from playwright.sync_api import (
    BrowserContext,
    Error,
    Page,
    Playwright,
    Request,
    Response,
    TimeoutError,
    sync_playwright,
)

HOME_URL = "https://www.icourse163.org/"
LOGIN_URL = "https://www.icourse163.org/home.htm"
COURSE_CENTER_URL = "https://www.icourse163.org/home.htm#/home/course"
DEFAULT_PROFILE_DIR = Path(".data/browser-profile")
LOGIN_MARKER = ".login-complete"
DEFAULT_HEADERS = {
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "DNT": "1",
}
SHANGHAI_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
INTERESTING_WORDS = (
    "course",
    "learn",
    "homework",
    "assignment",
    "quiz",
    "exam",
    "test",
    "deadline",
    "task",
    "term",
)


def _launch_context(
    playwright: Playwright, profile_dir: Path, *, headless: bool = True
) -> BrowserContext:
    return playwright.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=headless,
        channel="msedge",
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        extra_http_headers=DEFAULT_HEADERS,
        ignore_default_args=["--enable-automation"],
        args=["--disable-blink-features=AutomationControlled"],
    )


def login(url: str = LOGIN_URL, profile_dir: Path = DEFAULT_PROFILE_DIR) -> None:
    """在持久化浏览器配置中手动登录。"""
    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = _launch_context(playwright, profile_dir, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        print("请在浏览器中完成登录，并进入‘我的学习’页面。")
        input("确认课程页面能够正常显示后，回到这里按回车……")
        (profile_dir / LOGIN_MARKER).write_text(
            datetime.now().astimezone().isoformat(), encoding="utf-8"
        )
        context.close()
    print(f"持久化浏览器配置已保存到：{profile_dir}")


def validate_login(profile_dir: Path) -> bool:
    """验证配置是否仍能进入个人课程中心。"""
    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = _launch_context(playwright, profile_dir)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(COURSE_CENTER_URL, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(4_000)
            return page.locator("span.u-st-course_span2").first.is_visible(timeout=3_000)
        except (Error, TimeoutError):
            return False
        finally:
            context.close()


def login_until_authenticated(
    profile_dir: Path,
    wait_for_confirmation: Callable[[], None] | None = None,
    timeout_seconds: int = 300,
) -> bool:
    """打开登录页，在用户确认后验证；命令行兼容自动等待方式。"""
    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = _launch_context(playwright, profile_dir, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        # The root-page forced-login dialog can stall while requesting an SMS
        # code.  The desktop home page uses the current login component and is
        # also the entry point observed in successful browser sessions.
        page.goto(f"{LOGIN_URL}?forcelogin=true", wait_until="domcontentloaded")
        if wait_for_confirmation is not None:
            wait_for_confirmation()
        deadline = time.monotonic() + timeout_seconds
        verified = False
        while time.monotonic() < deadline:
            if wait_for_confirmation is None:
                page.wait_for_timeout(2_000)
            cookies = context.cookies()
            has_session = any(
                cookie["name"] in {"STUDY_SESS", "STUDY_INFO"} and "icourse163" in cookie["domain"]
                for cookie in cookies
            )
            if not has_session:
                if wait_for_confirmation is not None:
                    break
                continue
            try:
                page.goto(COURSE_CENTER_URL, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(4_000)
                verified = page.locator("span.u-st-course_span2").first.is_visible(timeout=3_000)
            except (Error, TimeoutError):
                verified = False
            if verified:
                (profile_dir / LOGIN_MARKER).write_text(
                    datetime.now().astimezone().isoformat(), encoding="utf-8"
                )
                break
            if wait_for_confirmation is not None:
                break
        context.close()
        return verified


class ResponseCollector:
    """将疑似课程或任务接口的 JSON 响应保存到本地。"""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.items: list[dict[str, Any]] = []
        self._seen: set[str] = set()

    def handle(self, response: Response) -> None:
        url_lower = response.url.lower()
        content_type = response.headers.get("content-type", "").lower()
        if "json" not in content_type:
            return
        if not any(word in url_lower for word in INTERESTING_WORDS):
            return

        try:
            payload = response.json()
        except (Error, ValueError, json.JSONDecodeError):
            return

        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256((response.url + serialized).encode("utf-8")).hexdigest()[:12]
        if digest in self._seen:
            return
        self._seen.add(digest)

        filename = f"response-{len(self.items) + 1:03d}-{digest}.json"
        (self.output_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.items.append(
            {
                "url": response.url,
                "status": response.status,
                "file": filename,
                "method": response.request.method,
                "post_data": response.request.post_data,
            }
        )
        print(f"捕获候选接口：{response.url}")

    def write_manifest(self) -> None:
        (self.output_dir / "manifest.json").write_text(
            json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _timestamp_ms_to_iso(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=SHANGHAI_TZ).isoformat()


def _write_course_summary(collector: ResponseCollector, output_dir: Path) -> int:
    target = next(
        (
            item
            for item in collector.items
            if "learnerCourseRpcBean.getMyLearnedCoursePanelList" in item["url"]
        ),
        None,
    )
    if target is None:
        return 0

    payload = json.loads((collector.output_dir / target["file"]).read_text(encoding="utf-8"))
    raw_courses = payload.get("result", {}).get("result", [])
    now_ms = int(datetime.now(tz=SHANGHAI_TZ).timestamp() * 1000)
    courses: list[dict[str, Any]] = []
    for raw_course in raw_courses:
        term = raw_course.get("termPanel") or {}
        school = raw_course.get("schoolPanel") or {}
        course_id = raw_course.get("id")
        term_id = term.get("id")
        school_short_name = school.get("shortName")
        if not (course_id and term_id and school_short_name):
            continue
        courses.append(
            {
                "name": raw_course.get("name"),
                "course_id": course_id,
                "term_id": term_id,
                "school": school.get("name"),
                "school_short_name": school_short_name,
                "start_at": _timestamp_ms_to_iso(term.get("startTime")),
                "end_at": _timestamp_ms_to_iso(term.get("endTime")),
                "is_active": (term.get("startTime") or 0) <= now_ms <= (term.get("endTime") or 0),
                "learned_lessons": raw_course.get("learnedCount"),
                "total_lessons": term.get("lessonsCount"),
                "learn_url": (
                    f"https://www.icourse163.org/learn/{school_short_name}-{course_id}"
                    f"?tid={term_id}#/learn/content"
                ),
            }
        )

    (output_dir / "courses.json").write_text(
        json.dumps(courses, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return len(courses)


def _write_deadline_summary(
    collector: ResponseCollector, courses: list[dict[str, Any]], output_dir: Path
) -> int:
    courses_by_term = {str(course["term_id"]): course for course in courses}
    deadlines: list[dict[str, Any]] = []
    seen: set[tuple[int | None, int]] = set()
    type_keys = {"quizs": "quiz", "homeworks": "assignment", "exams": "exam"}

    def walk(
        value: Any,
        course: dict[str, Any],
        task_type: str = "other",
        parent: dict[str, Any] | None = None,
    ) -> None:
        if isinstance(value, dict):
            deadline = value.get("deadline")
            if isinstance(deadline, int) and deadline > 0:
                task_id = value.get("id")
                unique_key = (task_id, deadline)
                if unique_key not in seen:
                    seen.add(unique_key)
                    used_try_count = value.get("usedTryCount")
                    user_score = value.get("userScore")
                    deadlines.append(
                        {
                            "course": course["name"],
                            "course_id": course["course_id"],
                            "term_id": course["term_id"],
                            "title": value.get("name")
                            or (parent or {}).get("name")
                            or "未命名任务",
                            "task_id": task_id,
                            "task_type": task_type,
                            "due_at": _timestamp_ms_to_iso(deadline),
                            "completed": bool(
                                (isinstance(used_try_count, int) and used_try_count > 0)
                                or user_score is not None
                            ),
                            "score": user_score,
                            "total_score": value.get("totalScore"),
                            "url": course["learn_url"],
                        }
                    )
            for key, child in value.items():
                child_type = type_keys.get(key, task_type)
                if key == "exam" and isinstance(child, dict):
                    child_type = "exam"
                walk(child, course, child_type, value)
        elif isinstance(value, list):
            for child in value:
                walk(child, course, task_type, parent)

    for item in collector.items:
        if "courseBean.getLastLearnedMocTermDto" not in item["url"]:
            continue
        form = parse_qs(item.get("post_data") or "")
        term_id = (form.get("termId") or [None])[0]
        course = courses_by_term.get(str(term_id))
        if course is None:
            continue
        payload = json.loads((collector.output_dir / item["file"]).read_text(encoding="utf-8"))
        walk(payload.get("result", {}).get("mocTermDto", {}), course)

    deadlines.sort(key=lambda item: item["due_at"] or "")
    (output_dir / "deadlines.json").write_text(
        json.dumps(deadlines, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if deadlines:
        with (output_dir / "deadlines.csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=deadlines[0].keys())
            writer.writeheader()
            writer.writerows(deadlines)
    return len(deadlines)


class Diagnostics:
    def __init__(self) -> None:
        self.console_errors: list[dict[str, str]] = []
        self.page_errors: list[str] = []
        self.failed_requests: list[dict[str, str | None]] = []
        self.http_errors: list[dict[str, str | int]] = []

    def attach_page(self, page: Page) -> None:
        page.on(
            "console",
            lambda message: (
                self.console_errors.append({"type": message.type, "text": message.text})
                if message.type in {"error", "warning"}
                else None
            ),
        )
        page.on("pageerror", lambda error: self.page_errors.append(str(error)))

    def handle_request_failed(self, request: Request) -> None:
        self.failed_requests.append({"url": request.url, "failure": request.failure})

    def handle_response(self, response: Response) -> None:
        if response.status >= 400:
            self.http_errors.append({"url": response.url, "status": response.status})

    def to_dict(self) -> dict[str, Any]:
        return {
            "console_errors": self.console_errors,
            "page_errors": self.page_errors,
            "failed_requests": self.failed_requests,
            "http_errors": self.http_errors,
        }


def _print_mooc_tab(page: Page) -> None:
    # 用户提供的元素：<span class="u-st-course_span2">MOOC课程<i ...>(10)</i></span>
    tab = page.locator("span.u-st-course_span2").first
    try:
        if tab.is_visible(timeout=3_000):
            text = re.sub(r"\s+", "", tab.inner_text())
            print(f"已识别课程分类：{text}")
            print("可以在浏览器中点击该分类，继续加载课程卡片。")
    except (Error, TimeoutError):
        print("当前页面尚未发现 MOOC 课程分类，请进入‘我的学习’后再操作。")


def discover_courses(
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    url: str = COURSE_CENTER_URL,
    output_root: Path = Path("artifacts"),
    diagnostics: bool = True,
) -> Path:
    """从个人中心 DOM 中发现课程号和跳转信息。"""
    if not (profile_dir / LOGIN_MARKER).exists():
        raise FileNotFoundError(f"未找到有效浏览器配置 {profile_dir}，请先执行 login 命令")

    stamp = datetime.now().astimezone().strftime("course-discovery-%Y%m%d-%H%M%S")
    output_dir = output_root / stamp
    output_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        context = _launch_context(playwright, profile_dir)
        collector = ResponseCollector(output_dir / "responses")
        context.on("response", collector.handle)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not any(
            "getMyLearnedCoursePanelList" in item["url"] for item in collector.items
        ):
            page.wait_for_timeout(250)

        tab = page.locator("span.u-st-course_span2").first
        try:
            if tab.is_visible(timeout=3_000):
                tab.click()
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and not any(
                    "getMyLearnedCoursePanelList" in item["url"] for item in collector.items
                ):
                    page.wait_for_timeout(250)
        except (Error, TimeoutError):
            pass

        candidates = page.evaluate(
            """
            () => {
              const interesting = /(?:course|learn|term|tid|cid|课程)/i;
              const nodes = [...document.querySelectorAll('a, [data-id], [data-course-id], '
                + '[data-cid], [data-tid], [data-term-id], [data-href], [onclick], '
                + '[class*="course" i]')];
              const results = [];
              for (const node of nodes) {
                const attrs = {};
                for (const attr of node.attributes || []) {
                  if (interesting.test(attr.name) || interesting.test(attr.value)
                      || ['href', 'onclick', 'id', 'class'].includes(attr.name)) {
                    attrs[attr.name] = attr.value;
                  }
                }
                const text = (node.innerText || '').replace(/\\s+/g, ' ').trim();
                const combined = text + ' ' + JSON.stringify(attrs);
                if (!interesting.test(combined)) continue;
                results.push({
                  tag: node.tagName.toLowerCase(),
                  text: text.slice(0, 300),
                  href: node.href || null,
                  attrs,
                  html: node.outerHTML.slice(0, 2000),
                });
              }
              return results;
            }
            """
        ) if diagnostics else []

        html = page.content() if diagnostics else ""
        id_patterns = {
            "learn_urls": sorted(
                set(re.findall(r"https?://[^\"'\\s<>]+/learn/[^\"'\\s<>]+", html))
            ),
            "course_ids": sorted(
                set(
                    re.findall(
                        r"(?:courseId|course_id|course-id|cid)[\"'\\s:=_-]+(\d{5,})",
                        html,
                        re.IGNORECASE,
                    )
                )
            ),
            "term_ids": sorted(
                set(
                    re.findall(
                        r"(?:termId|term_id|term-id|tid)[\"'\\s:=_-]+(\d{5,})", html, re.IGNORECASE
                    )
                )
            ),
        }

        if diagnostics:
            (output_dir / "course-center.html").write_text(html, encoding="utf-8")
            page.screenshot(path=output_dir / "course-center.png", full_page=True)
            (output_dir / "candidates.json").write_text(
                json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (output_dir / "ids.json").write_text(
                json.dumps(id_patterns, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        collector.write_manifest()
        course_count = _write_course_summary(collector, output_dir)
        context.close()

    print(
        f"课程发现完成，共找到 {len(candidates)} 个候选元素、"
        f"{len(collector.items)} 个候选接口、{course_count} 门课程：{output_dir}"
    )
    return output_dir


def probe_deadlines(
    courses_file: Path,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    output_root: Path = Path("artifacts"),
    diagnostics_enabled: bool = True,
) -> Path:
    """逐门打开在学课程并采集任务与截止时间候选接口。"""
    if not (profile_dir / LOGIN_MARKER).exists():
        raise FileNotFoundError(f"未找到有效浏览器配置 {profile_dir}，请先执行 login 命令")
    if not courses_file.exists():
        raise FileNotFoundError(f"未找到课程清单 {courses_file}，请先执行 discover 命令")

    courses = json.loads(courses_file.read_text(encoding="utf-8"))
    active_courses = [course for course in courses if course.get("is_active")]
    if not active_courses:
        raise RuntimeError("课程清单中没有正在进行的课程")

    stamp = datetime.now().astimezone().strftime("deadline-probe-%Y%m%d-%H%M%S")
    output_dir = output_root / stamp
    collector = ResponseCollector(output_dir / "responses")
    diagnostics = Diagnostics()
    pages_info: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        context = _launch_context(playwright, profile_dir)
        context.on("response", collector.handle)
        context.on("response", diagnostics.handle_response)
        context.on("requestfailed", diagnostics.handle_request_failed)

        opened_pages: list[tuple[int, dict[str, Any], Page]] = []
        for index, course in enumerate(active_courses, start=1):
            page = context.new_page()
            diagnostics.attach_page(page)
            print(f"正在分析：{course['name']}")
            try:
                wait_until = "domcontentloaded" if diagnostics_enabled else "commit"
                page.goto(course["learn_url"], wait_until=wait_until, timeout=30_000)
                opened_pages.append((index, course, page))
            except (Error, TimeoutError) as exc:
                pages_info.append(
                    {
                        "name": course["name"],
                        "course_id": course["course_id"],
                        "term_id": course["term_id"],
                        "requested_url": course["learn_url"],
                        "final_url": page.url,
                        "error": str(exc),
                    }
                )
                page.close()

        expected_responses = len(opened_pages)
        deadline = time.monotonic() + (15 if diagnostics_enabled else 10)
        while time.monotonic() < deadline:
            captured = sum(
                "courseBean.getLastLearnedMocTermDto" in item["url"] for item in collector.items
            )
            if captured >= expected_responses:
                break
            if opened_pages:
                opened_pages[0][2].wait_for_timeout(250)

        for index, course, page in opened_pages:
            try:
                if diagnostics_enabled:
                    (output_dir / f"course-{index}.html").write_text(
                        page.content(), encoding="utf-8"
                    )
                    page.screenshot(path=output_dir / f"course-{index}.png", full_page=True)
                pages_info.append(
                    {
                        "name": course["name"],
                        "course_id": course["course_id"],
                        "term_id": course["term_id"],
                        "requested_url": course["learn_url"],
                        "final_url": page.url,
                        "title": page.title(),
                        "frames": [frame.url for frame in page.frames],
                    }
                )
            except (Error, TimeoutError) as exc:
                pages_info.append({"name": course["name"], "error": str(exc)})
            finally:
                page.close()

        collector.write_manifest()
        deadline_count = _write_deadline_summary(collector, active_courses, output_dir)
        if diagnostics_enabled:
            (output_dir / "pages.json").write_text(
                json.dumps(pages_info, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (output_dir / "diagnostics.json").write_text(
                json.dumps(diagnostics.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
        context.close()

    print(
        f"DDL 探测完成，共分析 {len(active_courses)} 门在学课程、"
        f"捕获 {len(collector.items)} 个候选接口、解析 {deadline_count} 个任务：{output_dir}"
    )
    return output_dir


def scan(
    url: str = HOME_URL,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    output_root: Path = Path("artifacts"),
) -> Path:
    """加载已登录页面，收集候选接口响应和最终页面 HTML。"""
    if not (profile_dir / LOGIN_MARKER).exists():
        raise FileNotFoundError(f"未找到有效浏览器配置 {profile_dir}，请先执行 login 命令")

    stamp = datetime.now().astimezone().strftime("scan-%Y%m%d-%H%M%S")
    output_dir = output_root / stamp
    collector = ResponseCollector(output_dir)
    diagnostics = Diagnostics()

    with sync_playwright() as playwright:
        context = _launch_context(playwright, profile_dir, headless=False)
        context.on("response", collector.handle)
        context.on("response", diagnostics.handle_response)
        context.on("requestfailed", diagnostics.handle_request_failed)
        context.on("page", diagnostics.attach_page)
        page = context.pages[0] if context.pages else context.new_page()
        for open_page in context.pages:
            diagnostics.attach_page(open_page)
        page.goto(url, wait_until="domcontentloaded")
        _print_mooc_tab(page)
        print("请在浏览器中进入‘我的学习’，点击课程卡片及作业/测试入口。")
        input("浏览完成后回到这里按回车，结束采集……")

        pages_info: list[dict[str, Any]] = []
        for index, open_page in enumerate(context.pages, start=1):
            try:
                (output_dir / f"page-{index}.html").write_text(
                    open_page.content(), encoding="utf-8"
                )
                open_page.screenshot(path=output_dir / f"page-{index}.png", full_page=True)
                pages_info.append(
                    {
                        "url": open_page.url,
                        "title": open_page.title(),
                        "frames": [frame.url for frame in open_page.frames],
                        "user_agent": open_page.evaluate("navigator.userAgent"),
                        "webdriver": open_page.evaluate("navigator.webdriver"),
                    }
                )
            except Error as exc:
                pages_info.append({"url": open_page.url, "capture_error": str(exc)})
        (output_dir / "pages.json").write_text(
            json.dumps(pages_info, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output_dir / "diagnostics.json").write_text(
            json.dumps(diagnostics.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        collector.write_manifest()
        context.close()

    print(f"扫描完成，共保存 {len(collector.items)} 个候选响应：{output_dir}")
    return output_dir
