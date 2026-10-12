from __future__ import annotations

import io
import shutil
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .security import dpapi_protect, dpapi_unprotect

ARCHIVE_SUFFIX = ".secure"
RUNTIME_PREFIX = ".browser-runtime-"
CACHE_PARTS = {
    "BrowserMetrics",
    "Cache",
    "CacheStorage",
    "Code Cache",
    "Crashpad",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    "EdgeOptimizationGuideModelsManifest",
    "GPUCache",
    "GrShaderCache",
    "Safe Browsing",
    "ShaderCache",
    "SmartScreen",
    "component_crx_cache",
    "extensions_crx_cache",
    "optimization_guide_model_store",
}


def archive_path(profile_dir: Path) -> Path:
    return profile_dir.with_name(profile_dir.name + ARCHIVE_SUFFIX)


def _validate_profile_path(profile_dir: Path) -> Path:
    resolved = profile_dir.resolve()
    if resolved.name != "browser-profile":
        raise ValueError(f"拒绝处理非浏览器配置目录：{resolved}")
    return resolved


def _zip_directory(source: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source)
            if (
                path.is_file()
                and not path.is_symlink()
                and not CACHE_PARTS.intersection(relative.parts)
            ):
                try:
                    archive.write(path, relative.as_posix())
                except FileNotFoundError:
                    # Chromium may remove transient files after rglob discovers
                    # them (notably Service Worker cache indexes) while the
                    # browser process is winding down. They are safe to omit.
                    continue
    return buffer.getvalue()


def _extract_archive(payload: bytes, destination: Path) -> None:
    root = destination.resolve()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for member in archive.infolist():
            target = (root / member.filename).resolve()
            if root not in target.parents and target != root:
                raise ValueError("浏览器配置归档包含非法路径")
        archive.extractall(root)


def _seal_directory(source: Path, target: Path, master_key: bytes) -> None:
    encrypted = dpapi_protect(_zip_directory(source), master_key)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(encrypted)
    # Verify both encryption and ZIP integrity before replacing or deleting anything.
    verified = dpapi_unprotect(temporary.read_bytes(), master_key)
    with zipfile.ZipFile(io.BytesIO(verified)) as archive:
        if archive.testzip() is not None:
            raise ValueError("浏览器配置加密归档校验失败")
    temporary.replace(target)


def seal_plain_profile(profile_dir: Path, master_key: bytes) -> bool:
    """Encrypt a legacy plaintext profile, then remove it only after verification."""
    profile_dir = _validate_profile_path(profile_dir)
    if not profile_dir.exists():
        return False
    target = archive_path(profile_dir)
    _seal_directory(profile_dir, target, master_key)
    shutil.rmtree(profile_dir)
    return True


def seal_known_profiles(project_root: Path, master_key: bytes) -> int:
    data_root = (project_root / ".data").resolve()
    if data_root.exists():
        for runtime in data_root.rglob(f"{RUNTIME_PREFIX}*"):
            resolved = runtime.resolve()
            if runtime.is_dir() and data_root in resolved.parents:
                # Chromium cache entries can disappear while rmtree walks the
                # stale profile. Cleanup is best-effort and must not prevent
                # the user from unlocking otherwise valid local data.
                shutil.rmtree(resolved, ignore_errors=True)
    candidates = [project_root / ".data" / "browser-profile"]
    accounts_root = project_root / ".data" / "accounts"
    if accounts_root.exists():
        candidates.extend(path / "browser-profile" for path in accounts_root.iterdir() if path.is_dir())
    return sum(seal_plain_profile(path, master_key) for path in candidates if path.exists())


@contextmanager
def open_secure_profile(profile_dir: Path, master_key: bytes | None) -> Iterator[Path]:
    """Open an encrypted profile in a short-lived directory and reseal it on exit."""
    if master_key is None:
        profile_dir.mkdir(parents=True, exist_ok=True)
        yield profile_dir
        return

    profile_dir = _validate_profile_path(profile_dir)
    seal_plain_profile(profile_dir, master_key)
    target = archive_path(profile_dir)
    runtime_parent = profile_dir.parent
    runtime = Path(tempfile.mkdtemp(prefix=RUNTIME_PREFIX, dir=runtime_parent))
    try:
        if target.exists():
            payload = dpapi_unprotect(target.read_bytes(), master_key)
            _extract_archive(payload, runtime)
        yield runtime
    finally:
        try:
            _seal_directory(runtime, target, master_key)
        finally:
            shutil.rmtree(runtime, ignore_errors=True)
