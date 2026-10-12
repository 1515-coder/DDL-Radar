import io
import shutil
import zipfile
from pathlib import Path

from mooc_deadlines.secure_profile import (
    _zip_directory,
    archive_path,
    open_secure_profile,
    seal_known_profiles,
    seal_plain_profile,
)


def test_plain_profile_is_encrypted_and_restored_only_temporarily(tmp_path) -> None:
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    (profile / "Cookies").write_text("session-cookie", encoding="utf-8")
    key = b"k" * 32

    assert seal_plain_profile(profile, key)
    assert not profile.exists()
    assert b"session-cookie" not in archive_path(profile).read_bytes()

    with open_secure_profile(profile, key) as runtime:
        assert (runtime / "Cookies").read_text(encoding="utf-8") == "session-cookie"
        (runtime / "Local Storage").write_text("login-state", encoding="utf-8")

    assert not profile.exists()
    with open_secure_profile(profile, key) as runtime:
        assert (runtime / "Local Storage").read_text(encoding="utf-8") == "login-state"


def test_unlock_cleanup_removes_crashed_runtime_profile(tmp_path) -> None:
    runtime = tmp_path / ".data" / "accounts" / "id" / ".browser-runtime-stale"
    runtime.mkdir(parents=True)
    (runtime / "Cookies").write_text("leftover", encoding="utf-8")

    seal_known_profiles(tmp_path, b"k" * 32)

    assert not runtime.exists()


def test_unlock_cleanup_tolerates_chromium_cache_race(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / ".data" / "accounts" / "id" / ".browser-runtime-stale"
    runtime.mkdir(parents=True)
    original_rmtree = shutil.rmtree
    calls = []

    def simulated_cache_race(path, *args, **kwargs):
        calls.append(kwargs.get("ignore_errors"))
        if not kwargs.get("ignore_errors"):
            raise FileNotFoundError(3, "The system cannot find the path specified", path)
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr("mooc_deadlines.secure_profile.shutil.rmtree", simulated_cache_race)

    seal_known_profiles(tmp_path, b"k" * 32)

    assert calls == [True]
    assert not runtime.exists()


def test_profile_archive_ignores_chromium_cache_storage(tmp_path) -> None:
    profile = tmp_path / "browser-profile"
    cache = profile / "Default" / "Service Worker" / "CacheStorage" / "entry"
    cache.mkdir(parents=True)
    (cache / "the-real-index").write_text("transient", encoding="utf-8")
    (profile / "Cookies").write_text("session-cookie", encoding="utf-8")

    with zipfile.ZipFile(io.BytesIO(_zip_directory(profile))) as archive:
        assert archive.namelist() == ["Cookies"]


def test_profile_archive_tolerates_file_removed_during_write(tmp_path, monkeypatch) -> None:
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    disappearing = profile / "volatile-file"
    disappearing.write_text("temporary", encoding="utf-8")
    stable = profile / "Cookies"
    stable.write_text("session-cookie", encoding="utf-8")
    original_write = zipfile.ZipFile.write

    def remove_before_write(self, filename, arcname=None, *args, **kwargs):
        if Path(filename) == disappearing:
            disappearing.unlink()
        return original_write(self, filename, arcname, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "write", remove_before_write)

    with zipfile.ZipFile(io.BytesIO(_zip_directory(profile))) as archive:
        assert archive.namelist() == ["Cookies"]
