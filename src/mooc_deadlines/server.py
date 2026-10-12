from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
import webbrowser
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .accounts import AccountStore, LocalAccount
from .exports import export_csv, export_json, export_xlsx
from .materials import STATUS_FILE as MATERIAL_STATUS_FILE
from .materials import write_status as write_material_status
from .paths import project_root, resource_root
from .worker import LOGIN_CONFIRM_FILE, STATUS_FILE, write_status

PROJECT_ROOT = project_root()
WEB_ROOT = resource_root() / "web"

_selected_account: LocalAccount | None = None
_account_store = AccountStore(PROJECT_ROOT)
_worker_process: subprocess.Popen[bytes] | None = None
_material_process: subprocess.Popen[bytes] | None = None


def _latest_file(root: Path, directory_prefix: str, filename: str) -> Path | None:
    if not root.exists():
        return None
    candidates = sorted(
        (
            path / filename
            for path in root.glob(f"{directory_prefix}-*")
            if (path / filename).exists()
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _read_json(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def dashboard_data(account: LocalAccount) -> dict[str, Any]:
    root = _account_store.artifacts_path(account)
    courses_path = _latest_file(root, "course-discovery", "courses.json")
    deadlines_path = _latest_file(root, "deadline-probe", "deadlines.json")
    yanhe_courses_path = _latest_file(root, "yanhe-extract", "courses.json")
    yanhe_deadlines_path = _latest_file(root, "yanhe-extract", "deadlines.json")
    announcements_path = _latest_file(root, "yanhe-extract", "announcements.json")
    course_content_path = _latest_file(root, "yanhe-extract", "course-content.json")
    mooc_courses = _read_json(courses_path) if "mooc" in account.sources else []
    mooc_deadlines = _read_json(deadlines_path) if "mooc" in account.sources else []
    yanhe_courses = _read_json(yanhe_courses_path) if "yanhe" in account.sources else []
    yanhe_deadlines = _read_json(yanhe_deadlines_path) if "yanhe" in account.sources else []
    announcements = _read_json(announcements_path) if "yanhe" in account.sources else []
    course_content = _read_json(course_content_path) if "yanhe" in account.sources else []
    courses = mooc_courses + yanhe_courses
    deadlines = mooc_deadlines + yanhe_deadlines
    course_paths = []
    deadline_paths = []
    if "mooc" in account.sources:
        course_paths.append(courses_path)
        deadline_paths.append(deadlines_path)
    if "yanhe" in account.sources:
        course_paths.append(yanhe_courses_path)
        deadline_paths.append(yanhe_deadlines_path)
    course_times = [path.stat().st_mtime for path in course_paths if path is not None]
    deadline_times = [path.stat().st_mtime for path in deadline_paths if path is not None]
    return {
        "courses": courses,
        "deadlines": deadlines,
        "announcements": announcements,
        "course_content": course_content,
        "sources": {
            "courses_updated_at": max(course_times, default=None),
            "deadlines_updated_at": max(deadline_times, default=None),
        },
        "account": {"id": account.id, "name": account.name, "sources": account.sources},
    }


def _read_status() -> dict[str, str]:
    if not STATUS_FILE.exists():
        return {"state": "idle", "message": ""}
    return json.loads(STATUS_FILE.read_text(encoding="utf-8"))


def _read_material_status() -> dict[str, Any]:
    if not MATERIAL_STATUS_FILE.exists():
        return {"state": "idle", "message": ""}
    return json.loads(MATERIAL_STATUS_FILE.read_text(encoding="utf-8"))


def _worker_environment(master_key: bytes | None) -> dict[str, str] | None:
    if master_key is None:
        return None
    environment = os.environ.copy()
    environment["DDL_RADAR_SESSION_KEY"] = base64.b64encode(master_key).decode("ascii")
    return environment


def _launch_worker(
    account: LocalAccount,
    force_login: bool = False,
    master_key: bytes | None = None,
    extras: list[str] | None = None,
) -> bool:
    global _worker_process
    if _worker_process is not None and _worker_process.poll() is None:
        return False
    if _material_process is not None and _material_process.poll() is None:
        return False
    if getattr(sys, "frozen", False):
        command = [sys.executable, "_worker", "--account", account.id]
    else:
        command = [sys.executable, "-m", "mooc_deadlines.worker", "--account", account.id]
    if force_login:
        command.append("--force-login")
    for extra in extras or []:
        command.extend(("--extra", extra))
    write_status("starting", "正在启动独立采集进程…")
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    _worker_process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        creationflags=creation_flags,
        env=_worker_environment(master_key),
    )
    return True


def _launch_material_worker(
    account: LocalAccount,
    master_key: bytes | None = None,
    *,
    scan_only: bool = False,
    reference_ids: list[str] | None = None,
) -> bool:
    global _material_process
    if _material_process is not None and _material_process.poll() is None:
        return False
    if _worker_process is not None and _worker_process.poll() is None:
        return False
    if getattr(sys, "frozen", False):
        command = [sys.executable, "_materials", "--account", account.id]
    else:
        command = [sys.executable, "-m", "mooc_deadlines.materials", "--account", account.id]
    if scan_only:
        command.append("--scan-only")
    write_material_status("starting", "正在准备课程资料…")
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    environment = _worker_environment(master_key) or os.environ.copy()
    if reference_ids is not None:
        environment["DDL_RADAR_MATERIAL_IDS"] = json.dumps(reference_ids)
    _material_process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        creationflags=creation_flags,
        env=environment,
    )
    return True


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _send_download(self, content: bytes, content_type: str, filename: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _read_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(content_length) or b"{}")

    def do_GET(self) -> None:
        if self.path.startswith("/api/export?"):
            if _selected_account is None:
                self._send_json({"error": "请先选择账号"}, HTTPStatus.UNAUTHORIZED)
                return
            export_format = self.path.partition("format=")[2].partition("&")[0].lower()
            data = dashboard_data(_selected_account)
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            if export_format == "json":
                self._send_download(
                    export_json(data),
                    "application/json; charset=utf-8",
                    f"mooc-ddl-{stamp}.json",
                )
            elif export_format == "csv":
                self._send_download(
                    export_csv(data["deadlines"]),
                    "text/csv; charset=utf-8",
                    f"mooc-ddl-{stamp}.csv",
                )
            elif export_format == "xlsx":
                self._send_download(
                    export_xlsx(data["courses"], data["deadlines"]),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    f"mooc-ddl-{stamp}.xlsx",
                )
            else:
                self._send_json({"error": "不支持的导出格式"}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/accounts":
            try:
                accounts = _account_store.list()
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.FORBIDDEN)
                return
            self._send_json(
                {
                    "accounts": [
                        {"id": account.id, "name": account.name, "sources": account.sources}
                        for account in accounts
                    ],
                    "selected": (
                        {
                            "id": _selected_account.id,
                            "name": _selected_account.name,
                            "sources": _selected_account.sources,
                        }
                        if _selected_account
                        else None
                    ),
                }
            )
            return
        if self.path == "/api/data":
            if _selected_account is None:
                self._send_json({"error": "请先选择账号"}, HTTPStatus.UNAUTHORIZED)
                return
            self._send_json(dashboard_data(_selected_account))
            return
        if self.path == "/api/status":
            self._send_json(_read_status())
            return
        if self.path == "/api/materials/status":
            self._send_json(_read_material_status())
            return
        super().do_GET()

    def do_POST(self) -> None:
        global _selected_account
        body = self._read_body()
        if self.path == "/api/account/select":
            try:
                account = _account_store.get(str(body.get("id", "")))
            except KeyError:
                self._send_json({"error": "账号不存在"}, HTTPStatus.NOT_FOUND)
                return
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            _selected_account = account
            cached_data = dashboard_data(account)
            has_cached_data = bool(cached_data["courses"] or cached_data["deadlines"])
            self._send_json(
                {"state": "selected", "has_cached_data": has_cached_data},
            )
            return

        if self.path == "/api/account/new":
            try:
                sources = body.get("sources")
                if not isinstance(sources, list):
                    sources = None
                account = _account_store.create(str(body.get("name", "新账号")), sources)
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            _selected_account = account
            if not _launch_worker(account, force_login=True):
                self._send_json(_read_status(), HTTPStatus.CONFLICT)
                return
            self._send_json(
                {
                    "state": "login",
                    "account": {
                        "id": account.id,
                        "name": account.name,
                        "sources": account.sources,
                    },
                },
                HTTPStatus.ACCEPTED,
            )
            return

        if self.path == "/api/refresh":
            if _selected_account is None:
                self._send_json({"error": "请先选择账号"}, HTTPStatus.UNAUTHORIZED)
                return
            extras = body.get("extras")
            if not isinstance(extras, list):
                extras = []
            if not _launch_worker(
                _selected_account, extras=[str(value) for value in extras]
            ):
                self._send_json(_read_status(), HTTPStatus.CONFLICT)
                return
            self._send_json({"state": "starting", "message": "已开始刷新"}, HTTPStatus.ACCEPTED)
            return

        if self.path == "/api/login/confirm":
            status = _read_status()
            stage = status.get("login_stage")
            if status.get("state") != "login" or not stage:
                self._send_json({"error": "当前没有等待确认的认证"}, HTTPStatus.CONFLICT)
                return
            LOGIN_CONFIRM_FILE.parent.mkdir(parents=True, exist_ok=True)
            LOGIN_CONFIRM_FILE.write_text(
                json.dumps({"stage": stage}, ensure_ascii=False), encoding="utf-8"
            )
            self._send_json({"state": "confirmed", "stage": stage})
            return

        if self.path in {"/api/materials/scan", "/api/materials/start"}:
            if _selected_account is None:
                self._send_json({"error": "请先选择账号"}, HTTPStatus.UNAUTHORIZED)
                return
            if "yanhe" not in _selected_account.sources:
                self._send_json(
                    {"error": "此账号未启用延河课堂采集"}, HTTPStatus.BAD_REQUEST
                )
                return
            reference_ids = body.get("reference_ids")
            if self.path.endswith("/start") and not isinstance(reference_ids, list):
                self._send_json({"error": "请至少选择一个文件"}, HTTPStatus.BAD_REQUEST)
                return
            if not _launch_material_worker(
                _selected_account,
                scan_only=self.path.endswith("/scan"),
                reference_ids=(
                    [str(value) for value in reference_ids]
                    if isinstance(reference_ids, list)
                    else None
                ),
            ):
                self._send_json(_read_material_status(), HTTPStatus.CONFLICT)
                return
            self._send_json(
                {"state": "starting", "message": "正在准备课程资料…"},
                HTTPStatus.ACCEPTED,
            )
            return

        if self.path == "/api/materials/open":
            status = _read_material_status()
            raw_path = status.get("path")
            if not raw_path:
                self._send_json({"error": "没有可打开的下载目录"}, HTTPStatus.NOT_FOUND)
                return
            target = Path(str(raw_path)).resolve()
            downloads_root = (PROJECT_ROOT / "downloads").resolve()
            if not target.is_dir() or downloads_root not in target.parents:
                self._send_json({"error": "下载目录无效"}, HTTPStatus.BAD_REQUEST)
                return
            os.startfile(target)  # type: ignore[attr-defined]
            self._send_json({"path": str(target)})
            return

        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        return


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    if not WEB_ROOT.exists():
        raise FileNotFoundError(f"前端目录不存在：{WEB_ROOT}")
    write_status("idle", "请选择账号")
    server: ThreadingHTTPServer | None = None
    last_error: OSError | None = None
    for candidate_port in range(port, port + 20):
        try:
            server = ThreadingHTTPServer((host, candidate_port), DashboardHandler)
            port = candidate_port
            break
        except OSError as exc:
            last_error = exc
    if server is None:
        raise RuntimeError(
            f"无法启动本地服务，端口 {port}–{port + 19} 均不可用：{last_error}"
        ) from last_error
    url = f"http://{host}:{port}"
    print(f"本地仪表盘已启动：{url}")
    print("按 Ctrl+C 停止服务。")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
