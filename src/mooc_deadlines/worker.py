from __future__ import annotations

import argparse
import base64
import json
import os
import time
from typing import Any

from playwright.sync_api import Error, sync_playwright

from .accounts import AccountStore
from .browser import (
    _launch_context,
    discover_courses,
    login_until_authenticated,
    probe_deadlines,
    validate_login,
)
from .paths import project_root
from .sections import SECTION_ENDPOINTS, extract_course_sections
from .secure_profile import open_secure_profile
from .security import MasterPassword
from .yanhe import ECLASS_API, YANHE_WORKBENCH_URL
from .yanhe import discover_courses as discover_yanhe_courses
from .yanhe import extract_announcements as extract_yanhe_announcements
from .yanhe import extract_deadlines as extract_yanhe_deadlines
from .yanhe import save_snapshot as save_yanhe_snapshot

PROJECT_ROOT = project_root()
STATUS_FILE = PROJECT_ROOT / ".data" / "worker-status.json"
LOGIN_CONFIRM_FILE = PROJECT_ROOT / ".data" / "login-confirm.json"


def write_status(state: str, message: str, **details: Any) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"state": state, "message": message, **details}, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(STATUS_FILE)


def wait_for_login_confirmation(stage: str, message: str) -> None:
    """Pause authentication until the user confirms it in the desktop UI."""
    LOGIN_CONFIRM_FILE.unlink(missing_ok=True)
    write_status("login", message, login_stage=stage, requires_confirmation=True)
    while True:
        try:
            payload = json.loads(LOGIN_CONFIRM_FILE.read_text(encoding="utf-8"))
            if payload.get("stage") == stage:
                LOGIN_CONFIRM_FILE.unlink(missing_ok=True)
                write_status("validating", "正在验证认证状态…")
                return
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        # Keep the browser open without repeatedly requesting a platform endpoint.
        time.sleep(0.25)


def friendly_error(exc: Exception) -> str:
    text = str(exc)
    if "Expecting value" in text or "JSON" in text:
        return "平台接口暂时返回了空数据，请稍后重试；若仍失败，请重新认证"
    if "ERR_NETWORK_ACCESS_DENIED" in text:
        return "浏览器进程无法访问网络，请在普通 CMD 或 PowerShell 中重新启动本程序"
    if "Target page, context or browser has been closed" in text:
        return "登录窗口被关闭，请重新选择账号"
    return text.split("Call log:", maxsplit=1)[0].strip()


def _read_yanhe(
    profile_dir: Any, artifacts_dir: Any, extras: set[str]
) -> tuple[int, int, int, int, int, int]:
    """Read Yanhe data, opening the correct login pages only when required."""
    with sync_playwright() as playwright:
        context = _launch_context(playwright, profile_dir)
        try:
            try:
                courses = discover_yanhe_courses(context)
            except PermissionError:
                context.close()
                context = _launch_context(playwright, profile_dir, headless=False)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(YANHE_WORKBENCH_URL, wait_until="domcontentloaded", timeout=30_000)
                wait_for_login_confirmation("yanhe", "请在 Edge 中完成延河课堂认证")
                try:
                    courses = discover_yanhe_courses(context)
                except PermissionError:
                    raise PermissionError("延河课堂认证未通过，请确认登录完成后重试") from None

            active_courses = [course for course in courses if course.get("is_active")]
            report: list[dict[str, Any]] = []
            deadlines = extract_yanhe_deadlines(context, active_courses, report)
            if report and not any(item["ok"] for item in report):
                mapped = next((course for course in courses if course.get("learn_url")), None)
                if mapped is None:
                    raise PermissionError("没有可用于智园认证的课程")
                context.close()
                context = _launch_context(playwright, profile_dir, headless=False)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(mapped["learn_url"], wait_until="domcontentloaded", timeout=30_000)
                modules_url = f"{ECLASS_API}/{mapped['zhiyuan_id']}/modules"
                wait_for_login_confirmation("zhiyuan", "请在 Edge 中完成智园课堂认证")
                if not context.request.get(modules_url).ok:
                    raise PermissionError("智园课堂认证未通过，请确认登录完成后重试")
                report = []
                deadlines = extract_yanhe_deadlines(context, active_courses, report)

            announcement_report: list[dict[str, Any]] = []
            announcements = None
            if "bulletins" in extras:
                announcements = extract_yanhe_announcements(
                    context, active_courses, announcement_report
                )
            section_report: list[dict[str, Any]] = []
            section_extras = extras & SECTION_ENDPOINTS
            course_content = None
            if section_extras:
                course_content = extract_course_sections(
                    context, active_courses, section_report, section_extras
                )
            save_yanhe_snapshot(
                courses,
                deadlines,
                artifacts_dir,
                announcements,
                report + announcement_report + section_report,
                course_content,
            )
            failed = sum(
                not item["ok"] for item in report + announcement_report + section_report
            )
            return (
                len(courses),
                len(active_courses),
                len(deadlines),
                failed,
                len(announcements or []),
                len(course_content or []),
            )
        finally:
            try:
                context.close()
            except Error:
                pass


def run(
    account_id: str, force_login: bool = False, extras: set[str] | None = None
) -> None:
    security = MasterPassword(PROJECT_ROOT / ".data")
    master_key = None
    if security.configured:
        encoded_session_key = os.environ.pop("DDL_RADAR_SESSION_KEY", None)
        if encoded_session_key:
            master_key = security.unlock_with_key(base64.b64decode(encoded_session_key))
        elif security.unlock_from_cache():
            master_key = security.key
        else:
            write_status("error", "软件加密密码已过期，请重新打开程序解锁")
            return
    store = AccountStore(PROJECT_ROOT, master_key)
    try:
        account = store.get(account_id)
        artifacts_dir = store.artifacts_path(account)
        messages: list[str] = []
        with open_secure_profile(store.profile_path(account), master_key) as profile_dir:
            _run_sources(
                account, profile_dir, artifacts_dir, messages, force_login, extras or set()
            )

        write_status("complete", "数据已更新：" + "；".join(messages))
    except Exception as exc:  # noqa: BLE001 - 独立进程必须把错误写回前端
        write_status("error", friendly_error(exc))


def _run_sources(
    account: Any,
    profile_dir: Any,
    artifacts_dir: Any,
    messages: list[str],
    force_login: bool,
    extras: set[str],
) -> None:
    if "mooc" in account.sources:
        if force_login:
            if not login_until_authenticated(
                profile_dir,
                lambda: wait_for_login_confirmation(
                    "mooc", "请在 Edge 中完成中国大学 MOOC 登录"
                ),
            ):
                write_status("error", "中国大学 MOOC 登录未通过，请确认登录完成后重试")
                return
        else:
            write_status("validating", "正在验证中国大学 MOOC 登录状态…")
            if not validate_login(profile_dir) and not login_until_authenticated(
                profile_dir,
                lambda: wait_for_login_confirmation(
                    "mooc", "请在 Edge 中重新登录中国大学 MOOC"
                ),
            ):
                write_status("error", "中国大学 MOOC 登录未通过，请确认登录完成后重试")
                return

        write_status("running", "正在读取中国大学 MOOC 课程…")
        discovery_dir = discover_courses(
            profile_dir=profile_dir, output_root=artifacts_dir, diagnostics=False
        )
        courses: list[dict[str, Any]] = json.loads(
            (discovery_dir / "courses.json").read_text(encoding="utf-8")
        )
        if not courses:
            write_status("error", "中国大学 MOOC 未读取到课程，请重新登录")
            return
        write_status("running", "正在提取中国大学 MOOC 作业和测验…")
        probe_deadlines(
            courses_file=discovery_dir / "courses.json",
            profile_dir=profile_dir,
            output_root=artifacts_dir,
            diagnostics_enabled=False,
        )
        messages.append(f"MOOC {len(courses)} 门课程")

    if "yanhe" in account.sources:
        write_status("running", "正在读取延河课堂课程和待办…")
        try:
            (
                course_count,
                active_count,
                deadline_count,
                failed_count,
                announcement_count,
                content_count,
            ) = _read_yanhe(profile_dir, artifacts_dir, extras)
            message = (
                f"延河识别 {course_count} 门课程，"
                f"当前学期 {active_count} 门、{deadline_count} 项待办"
            )
            if "bulletins" in extras:
                message += f"、{announcement_count} 条公告"
            if extras & SECTION_ENDPOINTS:
                message += f"、{content_count} 项课程内容"
            if failed_count:
                message += f"，{failed_count} 个课程接口无权限"
            messages.append(message)
        except PermissionError as exc:
            messages.append(str(exc))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True)
    parser.add_argument("--force-login", action="store_true")
    parser.add_argument("--extra", action="append", default=[])
    args = parser.parse_args()
    run(args.account, args.force_login, set(args.extra))


if __name__ == "__main__":
    main()
