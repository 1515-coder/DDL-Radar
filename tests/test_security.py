from datetime import timedelta

from mooc_deadlines.security import MasterPassword


def test_master_password_encrypts_and_caches_key_for_one_day(tmp_path) -> None:
    security = MasterPassword(tmp_path)
    security.configure("correct horse battery staple")
    encrypted = security.encrypt(b"login-token")

    assert b"correct horse" not in security.config_path.read_bytes()
    assert b"login-token" not in encrypted

    reopened = MasterPassword(tmp_path)
    assert reopened.unlock_from_cache()
    assert reopened.decrypt(encrypted) == b"login-token"


def test_wrong_master_password_is_rejected(tmp_path) -> None:
    security = MasterPassword(tmp_path)
    security.configure("right password")
    security.clear_cache()

    try:
        security.unlock("wrong password")
    except PermissionError:
        pass
    else:
        raise AssertionError("wrong password unexpectedly unlocked local data")


def test_master_password_can_skip_persistent_cache(tmp_path) -> None:
    security = MasterPassword(tmp_path)
    key = security.configure("session only", remember_for=None)

    assert not security.cache_path.exists()
    reopened = MasterPassword(tmp_path)
    assert not reopened.unlock_from_cache()
    assert reopened.unlock_with_key(key) == key


def test_master_password_supports_week_cache(tmp_path) -> None:
    security = MasterPassword(tmp_path)
    security.configure("remember one week", remember_for=timedelta(days=7))

    reopened = MasterPassword(tmp_path)
    assert reopened.unlock_from_cache()
