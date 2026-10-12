from __future__ import annotations

import ctypes
import json
import threading
import uuid
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .secure_profile import archive_path
from .security import dpapi_protect, dpapi_unprotect

AVAILABLE_SOURCES = ("mooc", "yanhe")


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[DataBlob, Any]:
    buffer = ctypes.create_string_buffer(data)
    return DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _protect(data: bytes) -> bytes:
    source, source_buffer = _blob(data)
    output = DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), "MOOC DDL accounts", None, None, None, 0, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)
        del source_buffer


def _unprotect(data: bytes) -> bytes:
    source, source_buffer = _blob(data)
    output = DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)
        del source_buffer


@dataclass(slots=True)
class LocalAccount:
    id: str
    name: str
    profile_dir: str
    artifacts_dir: str
    sources: list[str] = field(default_factory=lambda: list(AVAILABLE_SOURCES))


class AccountStore:
    def __init__(self, project_root: Path, master_key: bytes | None = None) -> None:
        self.project_root = project_root
        self.data_root = project_root / ".data"
        self.path = self.data_root / "accounts.dat"
        self._lock = threading.RLock()
        self.master_key = master_key
        self.data_root.mkdir(parents=True, exist_ok=True)
        self._ensure_legacy_account()

    def _load(self) -> list[LocalAccount]:
        if not self.path.exists():
            return []
        try:
            encrypted = self.path.read_bytes()
            try:
                clear = dpapi_unprotect(encrypted, self.master_key)
            except OSError:
                if self.master_key is None:
                    raise
                # One-time migration from the earlier DPAPI-only registry.
                clear = dpapi_unprotect(encrypted)
                raw = json.loads(clear.decode("utf-8"))
                accounts = [LocalAccount(**item) for item in raw]
                self._save(accounts)
                return accounts
            raw = json.loads(clear.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            if self.master_key is not None:
                raise PermissionError("无法解密本地账号数据") from None
            return self._recover_unreadable_registry()
        return [LocalAccount(**item) for item in raw]

    def _save(self, accounts: list[LocalAccount]) -> None:
        payload = json.dumps([asdict(account) for account in accounts], ensure_ascii=False)
        temporary_path = self.path.with_suffix(".tmp")
        temporary_path.write_bytes(dpapi_protect(payload.encode("utf-8"), self.master_key))
        temporary_path.replace(self.path)

    def _recover_unreadable_registry(self) -> list[LocalAccount]:
        """Archive an unreadable DPAPI blob and rebuild entries from useful local data."""
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        backup_path = self.data_root / f"accounts.unreadable-{timestamp}.dat"
        self.path.replace(backup_path)

        accounts: list[LocalAccount] = []
        legacy_profile = self.data_root / "browser-profile"
        if (legacy_profile / ".login-complete").exists() or archive_path(legacy_profile).exists():
            accounts.append(
                LocalAccount(
                    id="legacy",
                    name="原账号",
                    profile_dir=".data/browser-profile",
                    artifacts_dir="artifacts",
                )
            )

        accounts_root = self.data_root / "accounts"
        if accounts_root.exists():
            recovered_number = 1
            for account_root in sorted(path for path in accounts_root.iterdir() if path.is_dir()):
                profile = account_root / "browser-profile"
                artifacts = account_root / "artifacts"
                has_login = (profile / ".login-complete").exists() or archive_path(profile).exists()
                has_results = any(artifacts.glob("**/deadlines.json")) or any(
                    artifacts.glob("**/courses.json")
                )
                if not (has_login or has_results):
                    continue
                accounts.append(
                    LocalAccount(
                        id=account_root.name,
                        name=f"恢复账号 {recovered_number}",
                        profile_dir=f".data/accounts/{account_root.name}/browser-profile",
                        artifacts_dir=f".data/accounts/{account_root.name}/artifacts",
                    )
                )
                recovered_number += 1

        self._save(accounts)
        return accounts

    def _ensure_legacy_account(self) -> None:
        if self.path.exists():
            return
        accounts: list[LocalAccount] = []
        legacy_profile = self.project_root / ".data" / "browser-profile"
        if (legacy_profile / ".login-complete").exists() or archive_path(legacy_profile).exists():
            accounts.append(
                LocalAccount(
                    id="legacy",
                    name="原账号",
                    profile_dir=".data/browser-profile",
                    artifacts_dir="artifacts",
                )
            )
        self._save(accounts)

    def list(self) -> list[LocalAccount]:
        with self._lock:
            unique: dict[str, LocalAccount] = {}
            for account in self._load():
                unique.setdefault(account.name, account)
            return list(unique.values())

    def get(self, account_id: str) -> LocalAccount:
        with self._lock:
            account = next((item for item in self._load() if item.id == account_id), None)
            if account is None:
                raise KeyError("账号不存在")
            return account

    @staticmethod
    def _sources(values: list[str] | None) -> list[str]:
        selected = [source for source in AVAILABLE_SOURCES if source in (values or [])]
        if not selected:
            raise ValueError("请至少选择一个采集平台")
        return selected

    def create(self, name: str, sources: list[str] | None = None) -> LocalAccount:
        with self._lock:
            clean_name = name.strip()[:40] or "新账号"
            selected_sources = self._sources(
                list(AVAILABLE_SOURCES) if sources is None else sources
            )
            accounts = self._load()
            existing = next((item for item in accounts if item.name == clean_name), None)
            if existing is not None:
                existing.sources = selected_sources
                self._save(accounts)
                return existing
            account_id = uuid.uuid4().hex
            account = LocalAccount(
                id=account_id,
                name=clean_name,
                profile_dir=f".data/accounts/{account_id}/browser-profile",
                artifacts_dir=f".data/accounts/{account_id}/artifacts",
                sources=selected_sources,
            )
            accounts.append(account)
            self._save(accounts)
            self.profile_path(account).mkdir(parents=True, exist_ok=True)
            self.artifacts_path(account).mkdir(parents=True, exist_ok=True)
            return account

    def profile_path(self, account: LocalAccount) -> Path:
        return self.project_root / account.profile_dir

    def artifacts_path(self, account: LocalAccount) -> Path:
        return self.project_root / account.artifacts_dir
