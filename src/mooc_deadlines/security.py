from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import os
from ctypes import wintypes
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

KDF_ITERATIONS = 600_000
CACHE_LIFETIME = timedelta(days=1)
VERIFIER_CONTEXT = b"DDL Radar master password verifier v1"


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[DataBlob, Any]:
    buffer = ctypes.create_string_buffer(data)
    return DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def dpapi_protect(data: bytes, entropy: bytes | None = None) -> bytes:
    source, source_buffer = _blob(data)
    entropy_blob, entropy_buffer = _blob(entropy) if entropy else (None, None)
    output = DataBlob()
    entropy_pointer = ctypes.byref(entropy_blob) if entropy_blob is not None else None
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), "DDL Radar local secret", entropy_pointer, None, None, 0,
        ctypes.byref(output),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)
        del source_buffer, entropy_buffer


def dpapi_unprotect(data: bytes, entropy: bytes | None = None) -> bytes:
    source, source_buffer = _blob(data)
    entropy_blob, entropy_buffer = _blob(entropy) if entropy else (None, None)
    output = DataBlob()
    entropy_pointer = ctypes.byref(entropy_blob) if entropy_blob is not None else None
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, entropy_pointer, None, None, 0, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)
        del source_buffer, entropy_buffer


def derive_key(password: str, salt: bytes) -> bytes:
    if not password:
        raise ValueError("软件加密密码不能为空")
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, KDF_ITERATIONS, 32)


class MasterPassword:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.config_path = data_root / "security.json"
        self.cache_path = data_root / "unlock.cache"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self._key: bytes | None = None

    @property
    def configured(self) -> bool:
        return self.config_path.exists()

    @property
    def unlocked(self) -> bool:
        return self._key is not None

    @property
    def key(self) -> bytes:
        if self._key is None:
            raise PermissionError("本地数据尚未解锁")
        return self._key

    def _read_config(self) -> dict[str, Any]:
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def configure(
        self, password: str, remember_for: timedelta | None = CACHE_LIFETIME
    ) -> bytes:
        if self.configured:
            raise RuntimeError("软件加密密码已经设置")
        salt = os.urandom(16)
        key = derive_key(password, salt)
        verifier = hmac.new(key, VERIFIER_CONTEXT, hashlib.sha256).digest()
        self.config_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "salt": base64.b64encode(salt).decode("ascii"),
                    "verifier": base64.b64encode(verifier).decode("ascii"),
                    "kdf": "PBKDF2-HMAC-SHA256",
                    "iterations": KDF_ITERATIONS,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self._key = key
        self._update_cache(remember_for)
        return key

    def unlock(
        self, password: str, remember_for: timedelta | None = CACHE_LIFETIME
    ) -> bytes:
        config = self._read_config()
        salt = base64.b64decode(config["salt"])
        key = derive_key(password, salt)
        expected = base64.b64decode(config["verifier"])
        actual = hmac.new(key, VERIFIER_CONTEXT, hashlib.sha256).digest()
        if not hmac.compare_digest(actual, expected):
            raise PermissionError("软件加密密码错误")
        self._key = key
        self._update_cache(remember_for)
        return key

    def unlock_with_key(self, key: bytes) -> bytes:
        """Accept a verified session key without writing it to disk."""
        config = self._read_config()
        expected = base64.b64decode(config["verifier"])
        actual = hmac.new(key, VERIFIER_CONTEXT, hashlib.sha256).digest()
        if not hmac.compare_digest(actual, expected):
            raise PermissionError("软件会话密钥无效")
        self._key = key
        return key

    def unlock_from_cache(self) -> bool:
        if not self.configured or not self.cache_path.exists():
            return False
        try:
            payload = json.loads(dpapi_unprotect(self.cache_path.read_bytes()).decode("utf-8"))
            expires_at = datetime.fromisoformat(payload["expires_at"])
            if datetime.now(UTC) >= expires_at:
                self.clear_cache()
                return False
            key = base64.b64decode(payload["key"])
            config = self._read_config()
            expected = base64.b64decode(config["verifier"])
            actual = hmac.new(key, VERIFIER_CONTEXT, hashlib.sha256).digest()
            if not hmac.compare_digest(actual, expected):
                self.clear_cache()
                return False
            self._key = key
            return True
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            self.clear_cache()
            return False

    def _update_cache(self, lifetime: timedelta | None) -> None:
        if lifetime is None:
            self.cache_path.unlink(missing_ok=True)
            return
        payload = json.dumps(
            {
                "key": base64.b64encode(self.key).decode("ascii"),
                "expires_at": (datetime.now(UTC) + lifetime).isoformat(),
            }
        ).encode("utf-8")
        self.cache_path.write_bytes(dpapi_protect(payload))

    def clear_cache(self) -> None:
        self._key = None
        self.cache_path.unlink(missing_ok=True)

    def encrypt(self, data: bytes) -> bytes:
        return dpapi_protect(data, self.key)

    def decrypt(self, data: bytes) -> bytes:
        return dpapi_unprotect(data, self.key)
