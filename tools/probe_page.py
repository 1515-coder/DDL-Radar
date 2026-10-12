from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import re
import threading
import time
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import Error, Request, TimeoutError, sync_playwright

from mooc_deadlines.accounts import AccountStore
from mooc_deadlines.browser import _launch_context
from mooc_deadlines.paths import project_root
from mooc_deadlines.secure_profile import open_secure_profile
from mooc_deadlines.security import MasterPassword
from mooc_deadlines.yanhe import YANHE_WORKBENCH_URL

DEFAULT_URL = YANHE_WORKBENCH_URL
SENSITIVE_KEYS = {"token", "password", "access_token", "refresh_token", "authorization"}


def redact_url(value: str) -> str:
    parts = urlsplit(value)
    query = [
        (key, "[REDACTED]" if key.lower() in SENSITIVE_KEYS else item_value)
        for key, item_value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def redact_post_data(value: str | None) -> str | None:
    if not value:
        return value
    return re.sub(
        r"(?i)((?:token|password|access_token|refresh_token|authorization)=)[^&]*",
        r"\1[REDACTED]",
        value,
    )


class NetworkCollector:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.response_dir = output_dir / "responses"
        self.response_dir.mkdir(parents=True, exist_ok=True)
        self.manifest: list[dict[str, Any]] = []
        self.seen: set[str] = set()

    def handle_finished(self, request: Request) -> None:
        response = request.response()
        if response is None:
            return
        content_type = response.headers.get("content-type", "").lower()
        item: dict[str, Any] = {
            "url": redact_url(response.url),
            "status": response.status,
            "method": request.method,
            "resource_type": request.resource_type,
            "content_type": content_type,
        }
        if request.method == "POST":
            item["post_data"] = redact_post_data(request.post_data)

        if "json" in content_type or request.resource_type in {"xhr", "fetch"}:
            try:
                body = response.body()
                if len(body) <= 10 * 1024 * 1024:
                    digest = hashlib.sha256(response.url.encode() + body).hexdigest()[:12]
                    if digest not in self.seen:
                        self.seen.add(digest)
                        suffix = ".json" if "json" in content_type else ".txt"
                        filename = f"response-{len(self.seen):03d}-{digest}{suffix}"
                        target = self.response_dir / filename
                        if suffix == ".json":
                            payload = json.loads(body.decode("utf-8"))
                            target.write_text(
                                json.dumps(payload, ensure_ascii=False, indent=2),
                                encoding="utf-8",
                            )
                        else:
                            target.write_bytes(body)
                        item["file"] = filename
            except (Error, UnicodeDecodeError, ValueError, json.JSONDecodeError):
                pass
        self.manifest.append(item)

    def save(self) -> None:
        (self.output_dir / "network.json").write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def page_inventory(target: Any) -> dict[str, Any]:
    return target.evaluate(
        r"""
        () => ({
          title: document.title,
          url: location.href,
          text: document.body?.innerText || '',
          links: [...document.querySelectorAll('a')].map((node) => ({
            text: (node.innerText || '').replace(/\s+/g, ' ').trim(),
            href: node.href,
            title: node.title || null,
            className: node.className || null,
          })),
          buttons: [...document.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"]')].map((node) => ({
            tag: node.tagName.toLowerCase(),
            text: (node.innerText || node.value || '').replace(/\s+/g, ' ').trim(),
            id: node.id || null,
            className: node.className || null,
          })),
          inputs: [...document.querySelectorAll('input, select, textarea')].map((node) => ({
            tag: node.tagName.toLowerCase(),
            type: node.type || null,
            name: node.name || null,
            id: node.id || null,
            placeholder: node.placeholder || null,
          })),
          dataNodes: [...document.querySelectorAll('[data-id], [data-course-id], [data-task-id], [ng-bind], [ng-repeat]')].map((node) => ({
            tag: node.tagName.toLowerCase(),
            text: (node.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 500),
            html: node.outerHTML.slice(0, 3000),
          })),
        })
        """
    )


def save_checkpoint(page: Any, output_dir: Path, index: int) -> dict[str, Any]:
    html = page.content()
    inventory = page_inventory(page)
    (output_dir / f"checkpoint-{index}.html").write_text(html, encoding="utf-8")
    (output_dir / f"checkpoint-{index}.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    frame_summaries: list[dict[str, Any]] = []
    for frame_index, frame in enumerate(page.frames, start=1):
        try:
            frame_html = frame.content()
            frame_inventory = page_inventory(frame)
            frame_prefix = f"checkpoint-{index}-frame-{frame_index}"
            (output_dir / f"{frame_prefix}.html").write_text(frame_html, encoding="utf-8")
            (output_dir / f"{frame_prefix}.json").write_text(
                json.dumps(frame_inventory, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            frame_summaries.append(
                {
                    "index": frame_index,
                    "name": frame.name,
                    "url": redact_url(frame.url),
                    "html_file": f"{frame_prefix}.html",
                    "inventory_file": f"{frame_prefix}.json",
                    "course_ids": sorted(set(re.findall(r"/course/(\d+)", frame_html))),
                }
            )
        except Error as exc:
            frame_summaries.append(
                {
                    "index": frame_index,
                    "name": frame.name,
                    "url": redact_url(frame.url),
                    "error": str(exc),
                }
            )

    return {
        "index": index,
        "url": redact_url(page.url),
        "title": page.title(),
        "frames": frame_summaries,
        "course_ids": sorted(set(re.findall(r"/course/(\d+)", html))),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集完整网页结构和 JSON 接口响应")
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="要分析的网页地址")
    parser.add_argument(
        "--profile", type=Path, default=Path(".data/web-probe-profile"), help="独立登录配置目录"
    )
    parser.add_argument(
        "--saved-account",
        action="store_true",
        help="复用软件中已加密保存的延河账号和登录状态",
    )
    parser.add_argument("--account", help="复用指定的本地账号 ID")
    parser.add_argument("--output", type=Path, default=Path("artifacts"), help="结果根目录")
    return parser.parse_args()


def saved_profile(account_id: str | None) -> tuple[Any, str]:
    root = project_root()
    security = MasterPassword(root / ".data")
    key = None
    if security.configured:
        if security.unlock_from_cache():
            key = security.key
        else:
            key = security.unlock(
                getpass.getpass("软件加密密码（不会显示）："), remember_for=None
            )
    store = AccountStore(root, key)
    accounts = [account for account in store.list() if "yanhe" in account.sources]
    if account_id:
        account = store.get(account_id)
    elif len(accounts) == 1:
        account = accounts[0]
    else:
        if not accounts:
            raise RuntimeError("没有启用延河课堂的本地账号")
        for index, candidate in enumerate(accounts, start=1):
            print(f"  {index}. {candidate.name}")
        while True:
            selected = input("请选择账号序号：").strip()
            if selected.isdigit() and 1 <= int(selected) <= len(accounts):
                account = accounts[int(selected) - 1]
                break
            print("请输入列表中的序号。")
    return open_secure_profile(store.profile_path(account), key), account.name


def main() -> None:
    args = parse_args()
    stamp = datetime.now().astimezone().strftime("web-probe-%Y%m%d-%H%M%S")
    output_dir = args.output / stamp
    output_dir.mkdir(parents=True, exist_ok=True)
    collector = NetworkCollector(output_dir)
    if args.saved_account or args.account:
        profile_context, account_name = saved_profile(args.account)
        print(f"复用账号：{account_name}")
    else:
        args.profile.mkdir(parents=True, exist_ok=True)
        profile_context = nullcontext(args.profile)

    with profile_context as profile_dir, sync_playwright() as playwright:
        context = _launch_context(playwright, profile_dir, headless=False)
        context.on("requestfinished", collector.handle_finished)
        # Keep one inert tab alive while SSO replaces or closes the visible login tab.
        # Without it, a transient zero-page state closes the persistent browser and
        # the probe mistakes an authentication redirect for the user finishing.
        sentinel_page = context.pages[0] if context.pages else context.new_page()
        sentinel_page.goto("about:blank")
        page = context.new_page()
        try:
            page.goto(args.url, wait_until="commit", timeout=20_000)
        except (Error, TimeoutError) as exc:
            print(f"首次打开未完成：{exc}")

        print("请在 Edge 中完成登录并进入要分析的页面。")
        print("请依次进入正确的课程公告、作业、考试/测试页面，并各点开一项。")
        print("脚本会持续记录 JSON/XHR 响应，不记录 Cookie 和请求头。")
        print("页面加载完整后，回到此窗口按回车保存全部内容……")

        stop_event = threading.Event()

        def wait_for_enter() -> None:
            try:
                input()
            finally:
                stop_event.set()

        threading.Thread(target=wait_for_enter, daemon=True).start()
        page_indexes: dict[int, int] = {}
        checkpoints: dict[int, dict[str, Any]] = {}
        next_checkpoint = 0.0
        try:
            while not stop_event.is_set():
                try:
                    open_pages = [
                        open_page
                        for open_page in context.pages
                        if open_page is not sentinel_page and not open_page.is_closed()
                    ]
                except Error:
                    open_pages = []
                if not open_pages:
                    # SSO providers may close the initiating tab before opening the
                    # authenticated destination. The sentinel tab keeps the context
                    # alive, so wait for the replacement instead of ending the probe.
                    try:
                        sentinel_page.wait_for_timeout(250)
                    except Error:
                        print("浏览器已关闭，开始保存已采集内容。")
                        break
                    continue
                if time.monotonic() >= next_checkpoint:
                    for open_page in open_pages:
                        page_key = id(open_page)
                        index = page_indexes.setdefault(page_key, len(page_indexes) + 1)
                        try:
                            checkpoints[index] = save_checkpoint(open_page, output_dir, index)
                        except Error:
                            continue
                    next_checkpoint = time.monotonic() + 3
                try:
                    open_pages[-1].wait_for_timeout(250)
                except Error:
                    continue
        except KeyboardInterrupt:
            stop_event.set()

        pages: list[dict[str, Any]] = list(checkpoints.values())
        try:
            final_pages = [
                open_page
                for open_page in context.pages
                if open_page is not sentinel_page and not open_page.is_closed()
            ]
        except Error:
            final_pages = []
        for open_page in final_pages:
            index = page_indexes.setdefault(id(open_page), len(page_indexes) + 1)
            try:
                page_summary = save_checkpoint(open_page, output_dir, index)
                open_page.screenshot(
                    path=output_dir / f"page-{index}.png", full_page=True, timeout=60_000
                )
                pages = [item for item in pages if item["index"] != index]
                pages.append(page_summary)
            except (Error, TimeoutError) as exc:
                if not any(item["index"] == index for item in pages):
                    pages.append({"index": index, "url": open_page.url, "error": str(exc)})

        collector.save()
        (output_dir / "pages.json").write_text(
            json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        try:
            context.close()
        except Error:
            pass

    print(f"采集完成：{output_dir.resolve()}")
    print(f"保存了 {len(pages)} 个页面、{len(collector.manifest)} 条网络响应记录。")


if __name__ == "__main__":
    main()
