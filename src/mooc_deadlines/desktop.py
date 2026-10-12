from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .accounts import AccountStore, LocalAccount
from .exports import export_csv, export_json, export_xlsx
from .paths import project_root, resource_root
from .secure_profile import seal_known_profiles
from .security import MasterPassword
from .server import (
    _launch_material_worker,
    _launch_worker,
    _read_material_status,
    _read_status,
    dashboard_data,
)
from .worker import LOGIN_CONFIRM_FILE


class DesktopApi:
    def __init__(self) -> None:
        self.root = project_root()
        self._security = MasterPassword(self.root / ".data")
        self._security.unlock_from_cache()
        self._account_store: AccountStore | None = None
        if not self._security.configured or self._security.unlocked:
            self._account_store = AccountStore(
                self.root, self._security.key if self._security.configured else None
            )
            if self._security.configured:
                seal_known_profiles(self.root, self._security.key)
        self.selected: LocalAccount | None = None

    def _store(self) -> AccountStore:
        if self._account_store is None:
            raise PermissionError("请先输入软件加密密码")
        return self._account_store

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        body = body or {}
        try:
            if method == "GET" and path == "/api/security":
                return self._ok(
                    {
                        "configured": self._security.configured,
                        "unlocked": self._security.unlocked,
                    }
                )
            if method == "POST" and path == "/api/security/unlock":
                password = str(body.get("password", ""))
                remember_options = {
                    "none": None,
                    "day": timedelta(days=1),
                    "week": timedelta(days=7),
                }
                remember_for = remember_options.get(str(body.get("remember", "none")))
                if self._security.configured:
                    self._security.unlock(password, remember_for)
                else:
                    self._security.configure(password, remember_for)
                self._account_store = AccountStore(self.root, self._security.key)
                seal_known_profiles(self.root, self._security.key)
                return self._ok({"configured": True, "unlocked": True})
            if method == "GET" and path == "/api/accounts":
                accounts = self._store().list()
                return self._ok(
                    {
                        "accounts": [
                            {
                                "id": account.id,
                                "name": account.name,
                                "sources": account.sources,
                            }
                            for account in accounts
                        ],
                        "selected": self._account_dict(self.selected),
                    }
                )
            if method == "GET" and path == "/api/data":
                if self.selected is None:
                    return self._error("请先选择账号", 401)
                return self._ok(dashboard_data(self.selected))
            if method == "GET" and path == "/api/status":
                return self._ok(_read_status())
            if method == "GET" and path == "/api/materials/status":
                return self._ok(_read_material_status())
            if method == "POST" and path == "/api/account/select":
                self.selected = self._store().get(str(body.get("id", "")))
                data = dashboard_data(self.selected)
                return self._ok(
                    {
                        "state": "selected",
                        "has_cached_data": bool(data["courses"] or data["deadlines"]),
                    }
                )
            if method == "POST" and path == "/api/account/new":
                sources = body.get("sources")
                if not isinstance(sources, list):
                    sources = None
                self.selected = self._store().create(
                    str(body.get("name", "新账号")), sources
                )
                if not _launch_worker(
                    self.selected, force_login=True, master_key=self._security.key
                ):
                    return self._error("已有采集任务正在运行", 409)
                return self._ok(
                    {"state": "login", "account": self._account_dict(self.selected)}, 202
                )
            if method == "POST" and path == "/api/refresh":
                if self.selected is None:
                    return self._error("请先选择账号", 401)
                extras = body.get("extras")
                if not isinstance(extras, list):
                    extras = []
                if not _launch_worker(
                    self.selected,
                    master_key=self._security.key,
                    extras=[str(value) for value in extras],
                ):
                    return self._error("已有采集任务正在运行", 409)
                return self._ok({"state": "starting", "message": "已开始刷新"}, 202)
            if method == "POST" and path == "/api/login/confirm":
                status = _read_status()
                stage = status.get("login_stage")
                if status.get("state") != "login" or not stage:
                    return self._error("当前没有等待确认的认证", 409)
                LOGIN_CONFIRM_FILE.parent.mkdir(parents=True, exist_ok=True)
                LOGIN_CONFIRM_FILE.write_text(
                    json.dumps({"stage": stage}, ensure_ascii=False), encoding="utf-8"
                )
                return self._ok({"state": "confirmed", "stage": stage})
            if method == "POST" and path in {"/api/materials/scan", "/api/materials/start"}:
                if self.selected is None:
                    return self._error("请先选择账号", 401)
                if "yanhe" not in self.selected.sources:
                    return self._error("此账号未启用延河课堂采集", 400)
                reference_ids = body.get("reference_ids")
                if path.endswith("/start") and not isinstance(reference_ids, list):
                    return self._error("请至少选择一个文件", 400)
                if not _launch_material_worker(
                    self.selected,
                    master_key=self._security.key,
                    scan_only=path.endswith("/scan"),
                    reference_ids=(
                        [str(value) for value in reference_ids]
                        if isinstance(reference_ids, list)
                        else None
                    ),
                ):
                    return self._error("课程资料任务正在运行", 409)
                return self._ok({"state": "starting", "message": "正在准备课程资料…"}, 202)
            if method == "POST" and path == "/api/materials/open":
                status = _read_material_status()
                raw_path = status.get("path")
                if not raw_path:
                    return self._error("没有可打开的下载目录", 404)
                target = Path(str(raw_path)).resolve()
                downloads_root = (self.root / "downloads").resolve()
                if not target.is_dir() or downloads_root not in target.parents:
                    return self._error("下载目录无效", 400)
                os.startfile(target)  # type: ignore[attr-defined]
                return self._ok({"path": str(target)})
            return self._error("接口不存在", 404)
        except KeyError:
            return self._error("账号不存在", 404)
        except PermissionError as exc:
            return self._error(str(exc), 401)
        except Exception as exc:  # noqa: BLE001 - 错误需要返回本地界面
            return self._error(str(exc), 500)

    def export_data(self, export_format: str) -> dict[str, Any]:
        if self.selected is None:
            return self._error("请先选择账号", 401)
        data = dashboard_data(self.selected)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        output_dir = self.root / "exports"
        output_dir.mkdir(parents=True, exist_ok=True)
        exporters = {
            "json": lambda: export_json(data),
            "csv": lambda: export_csv(data["deadlines"]),
            "xlsx": lambda: export_xlsx(data["courses"], data["deadlines"]),
        }
        exporter = exporters.get(export_format)
        if exporter is None:
            return self._error("不支持的导出格式", 400)
        target = output_dir / f"mooc-ddl-{stamp}.{export_format}"
        target.write_bytes(exporter())
        return self._ok({"path": str(target)})

    @staticmethod
    def _account_dict(account: LocalAccount | None) -> dict[str, Any] | None:
        return (
            {"id": account.id, "name": account.name, "sources": account.sources}
            if account
            else None
        )

    @staticmethod
    def _ok(payload: Any, status: int = 200) -> dict[str, Any]:
        return {"ok": True, "status": status, "payload": payload}

    @staticmethod
    def _error(message: str, status: int) -> dict[str, Any]:
        return {"ok": False, "status": status, "payload": {"error": message}}


def run() -> None:
    import webview

    page = (resource_root() / "web" / "index.html").resolve()
    if not page.exists():
        raise FileNotFoundError(f"前端文件不存在：{page}")
    webview.create_window(
        "DDL Radar",
        url=page.as_uri(),
        js_api=DesktopApi(),
        width=1280,
        height=820,
        min_size=(900, 620),
    )
    webview.start(debug=False)
