from __future__ import annotations

import argparse
import base64
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Error, sync_playwright

from .accounts import AccountStore
from .browser import _launch_context
from .paths import project_root
from .secure_profile import open_secure_profile
from .security import MasterPassword

PROJECT_ROOT = project_root()
STATUS_FILE = PROJECT_ROOT / ".data" / "material-status.json"
COURSEWARE_API = "https://zy-eclass.bit.edu.cn/api/course/{course_id}/coursewares"
DOWNLOAD_API = "https://zy-eclass.bit.edu.cn/api/uploads/reference/{reference_id}/blob"


def write_status(state: str, message: str, **extra: Any) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"state": state, "message": message, **extra}, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(STATUS_FILE)


def _latest_courses(root: Path) -> list[dict[str, Any]]:
    candidates = sorted(
        (path / "courses.json" for path in root.glob("yanhe-extract-*") if (path / "courses.json").exists()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("请先刷新延河课堂数据，再下载课程资料")
    return json.loads(candidates[0].read_text(encoding="utf-8"))


def _safe_name(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return (cleaned[:120] or fallback).strip()


def _catalog_path(root: Path) -> Path:
    return root / "material-catalog.json"


def _save_catalog(root: Path, items: list[dict[str, Any]]) -> None:
    target = _catalog_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_catalog(root: Path) -> list[dict[str, Any]]:
    target = _catalog_path(root)
    if not target.exists():
        raise FileNotFoundError("请先扫描课程资料")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise TypeError("课程资料清单格式异常")
    return [item for item in payload if isinstance(item, dict)]


def _items_from_payload(
    payload: Any, course: dict[str, Any], seen: set[str]
) -> list[dict[str, Any]]:
    """Normalize downloadable uploads from one courseware response."""
    course_id = str(course.get("zhiyuan_id") or "")
    activities = payload.get("activities", []) if isinstance(payload, dict) else []
    if not isinstance(activities, list):
        return []
    items: list[dict[str, Any]] = []
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        uploads = activity.get("uploads") or []
        if not isinstance(uploads, list):
            continue
        for upload in uploads:
            if not isinstance(upload, dict):
                continue
            reference_id = str(upload.get("reference_id") or "")
            downloadable = upload.get("allow_download") or upload.get("origin_allow_download")
            if (
                not reference_id
                or reference_id in seen
                or not downloadable
                or upload.get("deleted")
                or str(upload.get("source") or "").lower() == "elrc"
            ):
                continue
            seen.add(reference_id)
            items.append(
                {
                    "course": course.get("name") or f"课程-{course_id}",
                    "course_id": course_id,
                    "activity": activity.get("title") or "课程资料",
                    "reference_id": reference_id,
                    "name": upload.get("name") or f"资料-{reference_id}",
                    "size": upload.get("size"),
                    "url": DOWNLOAD_API.format(reference_id=reference_id),
                }
            )
    return items


def _material_items(
    context: Any,
    courses: list[dict[str, Any]],
    report: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    query = {
        "conditions": '{"category":null,"itemsSortBy":{"predicate":"chapter","reverse":false},"ignore_activity_types":["lesson"]}',
        "page": 1,
        "page_size": 100,
    }
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    attempted = 0
    unauthorized = 0
    for index, course in enumerate(courses, start=1):
        write_status(
            "scanning",
            f"正在检查课程资料（{index}/{len(courses)}）…",
            courses_scanned=index - 1,
            courses_total=len(courses),
        )
        course_id = str(course.get("zhiyuan_id") or "")
        if not course_id:
            if report is not None:
                report.append({"course": course.get("name"), "status": "missing-course-id"})
            continue
        attempted += 1
        entry = {
            "course": course.get("name") or f"课程-{course_id}",
            "course_id": course_id,
        }
        try:
            response = context.request.get(
                COURSEWARE_API.format(course_id=course_id), params=query
            )
        except Error as exc:
            entry.update(status="request-error", error=str(exc).split("Call log:", 1)[0].strip())
            if report is not None:
                report.append(entry)
            continue
        entry["http_status"] = response.status
        if response.status in {401, 403}:
            unauthorized += 1
            entry["status"] = "unauthorized"
            if report is not None:
                report.append(entry)
            continue
        if not response.ok:
            entry["status"] = "http-error"
            if report is not None:
                report.append(entry)
            continue
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            entry["status"] = "invalid-json"
            if report is not None:
                report.append(entry)
            continue
        course_items = _items_from_payload(payload, course, seen)
        items.extend(course_items)
        entry.update(status="ok", files=len(course_items))
        if report is not None:
            report.append(entry)
    if attempted and unauthorized == attempted:
        raise PermissionError("智园课堂认证已失效，请重新认证后再扫描课程资料")
    return items


def run(account_id: str, scan_only: bool = False) -> None:
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
        if "yanhe" not in account.sources:
            raise PermissionError("此账号未启用延河课堂采集")
        courses = [
            course
            for course in _latest_courses(store.artifacts_path(account))
            if course.get("is_active")
        ]
        artifacts_root = store.artifacts_path(account)
        if scan_only:
            report: list[dict[str, Any]] = []
            with (
                open_secure_profile(store.profile_path(account), master_key) as profile_dir,
                sync_playwright() as playwright,
            ):
                context = _launch_context(playwright, profile_dir)
                try:
                    items = _material_items(context, courses, report)
                finally:
                    context.close()
            _save_catalog(artifacts_root, items)
            (artifacts_root / "material-scan-report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            public_items = [
                {
                    key: item.get(key)
                    for key in ("course", "course_id", "activity", "reference_id", "name", "size")
                }
                for item in items
            ]
            write_status(
                "ready",
                f"找到 {len(items)} 个可下载文件"
                + (
                    f"，{sum(item.get('status') != 'ok' for item in report)} 门课程读取失败"
                    if any(item.get("status") != "ok" for item in report)
                    else ""
                ),
                items=public_items,
            )
            return

        selected_payload = os.environ.pop("DDL_RADAR_MATERIAL_IDS", "[]")
        selected_ids = {
            str(value) for value in json.loads(selected_payload) if isinstance(value, (str, int))
        }
        if not selected_ids:
            raise ValueError("请至少选择一个文件")
        items = [
            item
            for item in _load_catalog(artifacts_root)
            if str(item.get("reference_id")) in selected_ids
        ]
        if not items:
            raise ValueError("所选课程资料已失效，请重新扫描")
        output_root = PROJECT_ROOT / "downloads" / _safe_name(account.name, account.id)
        output_root.mkdir(parents=True, exist_ok=True)
        manifest: list[dict[str, Any]] = []
        with (
            open_secure_profile(store.profile_path(account), master_key) as profile_dir,
            sync_playwright() as playwright,
        ):
                context = _launch_context(playwright, profile_dir)
                try:
                    total = len(items)
                    for index, item in enumerate(items, start=1):
                        write_status(
                            "downloading",
                            f"正在下载课程资料（{index}/{total}）…",
                            files_done=index - 1,
                            files_total=total,
                        )
                        course_dir = output_root / _safe_name(item["course"], item["course_id"])
                        course_dir.mkdir(parents=True, exist_ok=True)
                        target = course_dir / _safe_name(item["name"], item["reference_id"])
                        if target.exists() and item.get("size") == target.stat().st_size:
                            manifest.append({**item, "path": str(target), "status": "existing"})
                            continue
                        response = context.request.get(item["url"])
                        if not response.ok:
                            manifest.append({**item, "status": f"http-{response.status}"})
                            continue
                        target.write_bytes(response.body())
                        manifest.append({**item, "path": str(target), "status": "downloaded"})
                finally:
                    context.close()

        manifest_path = output_root / "download-manifest.json"
        manifest_path.write_text(
            json.dumps(
                {"generated_at": datetime.now().astimezone().isoformat(), "files": manifest},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        downloaded = sum(item["status"] in {"downloaded", "existing"} for item in manifest)
        failed = len(manifest) - downloaded
        message = f"课程资料已保存：{downloaded} 个文件"
        if failed:
            message += f"，{failed} 个失败"
        write_status(
            "complete",
            message,
            path=str(output_root),
            downloaded=downloaded,
            failed=failed,
        )
    except Exception as exc:  # noqa: BLE001 - 子进程必须把错误返回界面
        write_status("error", str(exc))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True)
    parser.add_argument("--scan-only", action="store_true")
    args = parser.parse_args()
    run(args.account, args.scan_only)


if __name__ == "__main__":
    main()
