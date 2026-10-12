import pytest

from mooc_deadlines.accounts import AccountStore


def test_account_names_are_encrypted_and_profiles_are_isolated(tmp_path) -> None:
    store = AccountStore(tmp_path)

    first = store.create("我的账号")
    second = store.create("学校账号", ["yanhe"])

    assert [account.name for account in store.list()] == ["我的账号", "学校账号"]
    assert first.profile_dir != second.profile_dir
    assert first.sources == ["mooc", "yanhe"]
    assert second.sources == ["yanhe"]
    assert "我的账号".encode() not in store.path.read_bytes()


def test_unreadable_registry_is_backed_up_and_legacy_account_is_recovered(tmp_path) -> None:
    store = AccountStore(tmp_path)
    legacy_profile = tmp_path / ".data" / "browser-profile"
    legacy_profile.mkdir(parents=True)
    (legacy_profile / ".login-complete").touch()
    store.path.write_bytes(b"not a DPAPI payload")

    recovered_store = AccountStore(tmp_path)

    assert [account.name for account in recovered_store.list()] == ["原账号"]
    assert len(list((tmp_path / ".data").glob("accounts.unreadable-*.dat"))) == 1


def test_account_requires_at_least_one_source(tmp_path) -> None:
    store = AccountStore(tmp_path)

    with pytest.raises(ValueError, match="至少选择一个"):
        store.create("空平台", [])
