from __future__ import annotations

import argparse
import getpass
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Error, sync_playwright

from mooc_deadlines.accounts import AccountStore, LocalAccount
from mooc_deadlines.browser import _launch_context
from mooc_deadlines.materials import (
    _latest_courses,
    _material_items,
    _save_catalog,
    write_status,
)
from mooc_deadlines.paths import project_root
from mooc_deadlines.secure_profile import open_secure_profile
from mooc_deadlines.security import MasterPassword

PROJECT_ROOT = project_root()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="用智园课堂接口重新提取延河当前学期的课程资料"
    )
    parser.add_argument("--account", help="本地账号 ID；省略时交互选择")
    parser.add_argument("--all-terms", action="store_true", help="扫描历史学期课程")
    parser.add_argument("--login", action="store_true", help="扫描前先打开 Edge 重新认证")
    return parser.parse_args()


def unlock() -> bytes | None:
    security = MasterPassword(PROJECT_ROOT / ".data")
    if not security.configured:
        return None
    if security.unlock_from_cache():
        return security.key
    password = getpass.getpass("软件加密密码（不会显示）：")
    return security.unlock(password, remember_for=None)


def choose_account(store: AccountStore, account_id: str | None) -> LocalAccount:
    if account_id:
        return store.get(account_id)
    accounts = [account for account in store.list() if "yanhe" in account.sources]
    if not accounts:
        raise RuntimeError("没有启用延河课堂的本地账号")
    if len(accounts) == 1:
        print(f"使用账号：{accounts[0].name}")
        return accounts[0]
    print("请选择账号：")
    for index, account in enumerate(accounts, start=1):
        print(f"  {index}. {account.name}")
    while True:
        raw = input("序号：").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(accounts):
            return accounts[int(raw) - 1]
        print("请输入列表中的序号。")


def authenticate(context: Any, course: dict[str, Any]) -> None:
    page = context.pages[0] if context.pages else context.new_page()
    url = course.get("learn_url") or (
        f"https://zy-eclass.bit.edu.cn/course/{course['zhiyuan_id']}/courseware"
    )
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    print("\n请在打开的 Edge 中完成智园课堂认证，并进入任意课程的课件页。")
    input("认证完成后回到此 PowerShell 按回车，Python 将直接读取接口……")


def save_results(
    artifacts_root: Path,
    courses: list[dict[str, Any]],
    items: list[dict[str, Any]],
    report: list[dict[str, Any]],
) -> Path:
    stamp = datetime.now().astimezone().strftime("material-extract-%Y%m%d-%H%M%S")
    output = artifacts_root / stamp
    output.mkdir(parents=True, exist_ok=True)
    (output / "courses.json").write_text(
        json.dumps(courses, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "materials.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _save_catalog(artifacts_root, items)
    (artifacts_root / "material-scan-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output


def scan(context: Any, courses: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    report: list[dict[str, Any]] = []
    items = _material_items(context, courses, report)
    return items, report


def main() -> None:
    args = parse_args()
    master_key = unlock()
    store = AccountStore(PROJECT_ROOT, master_key)
    account = choose_account(store, args.account)
    artifacts_root = store.artifacts_path(account)
    all_courses = _latest_courses(artifacts_root)
    courses = [
        course
        for course in all_courses
        if course.get("zhiyuan_id") and (args.all_terms or course.get("is_active"))
    ]
    if not courses:
        raise RuntimeError("没有可扫描的课程，请先在界面刷新延河课堂数据")
    scope = "全部学期" if args.all_terms else "当前学期"
    print(f"准备扫描{scope} {len(courses)} 门课程，每门课程请求一次课件接口。")

    items: list[dict[str, Any]]
    report: list[dict[str, Any]]
    with (
        open_secure_profile(store.profile_path(account), master_key) as profile_dir,
        sync_playwright() as playwright,
    ):
        context = _launch_context(playwright, profile_dir, headless=not args.login)
        try:
            if args.login:
                authenticate(context, courses[0])
            try:
                items, report = scan(context, courses)
            except PermissionError:
                context.close()
                context = _launch_context(playwright, profile_dir, headless=False)
                authenticate(context, courses[0])
                items, report = scan(context, courses)
        finally:
            try:
                context.close()
            except Error:
                pass

    output = save_results(artifacts_root, courses, items, report)
    ok_courses = sum(entry.get("status") == "ok" for entry in report)
    failed_courses = len(report) - ok_courses
    public_items = [
        {
            key: item.get(key)
            for key in ("course", "course_id", "activity", "reference_id", "name", "size")
        }
        for item in items
    ]
    message = f"找到 {len(items)} 个可下载文件"
    if failed_courses:
        message += f"，{failed_courses} 门课程读取失败"
    write_status("ready", message, items=public_items)
    print(f"\n提取完成：{ok_courses} 门课程接口成功，找到 {len(items)} 个可下载文件。")
    if failed_courses:
        print(f"另有 {failed_courses} 门课程读取失败，详情见 report.json。")
    print(f"结果：{output.resolve()}")
    print("课程资料清单也已同步到网页前端。")


if __name__ == "__main__":
    main()
