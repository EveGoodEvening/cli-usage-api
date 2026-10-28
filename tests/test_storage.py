"""Synthetic private config, transaction and hostile filesystem behavior."""

import json
import multiprocessing
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from usage_tui.domain import Account, CredentialKind, ProviderId, new_account_id
from usage_tui.storage import MAX_FILE_BYTES, AccountStore, ConfigError

ACCOUNT_ID = "00000000-0000-4000-8000-000000000001"


def account(**changes):
    return replace(Account(ACCOUNT_ID, ProviderId.CLAUDE_SUBSCRIPTION, "Synthetic"), **changes)


@pytest.fixture
def store(tmp_path):
    return AccountStore(tmp_path / "private" / "accounts.json")


def write_config(store, content):
    store.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    store.path.write_bytes(content)
    store.path.chmod(0o600)


def _concurrent_append(path, ready, start, label):
    store = AccountStore(path)
    # Deliberately start with the same stale view; mutate must reread under flock.
    assert store.load() == ()
    ready.put(label)
    if not start.wait(10):
        raise RuntimeError("Synthetic start timeout")
    store.mutate(lambda accounts: (*accounts, account(id=new_account_id(), label=label)))


def test_default_paths_are_lazy_and_xdg_aware(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    store = AccountStore()
    assert store.path == tmp_path / "xdg" / "usage-tui" / "accounts.json"
    assert not store.path.parent.exists()
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative-is-not-xdg")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    assert AccountStore().path == tmp_path / "home" / ".config" / "usage-tui" / "accounts.json"


def test_private_roundtrip_and_crud(store):
    assert store.load() == ()
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700
    store.save((account(),))
    assert store.load() == (account(),)
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE((store.path.parent / ".accounts.json.lock").stat().st_mode) == 0o600
    assert store.mutate(lambda items: (replace(items[0], label="Changed", enabled=False),)) == (
        account(label="Changed", enabled=False),
    )
    assert store.mutate(lambda _: ()) == ()
    assert store.load() == ()


def test_manual_secrets_are_references_only(store):
    ref = f"keyring:{ACCOUNT_ID}:00000000-0000-4000-8000-000000000002"
    expected = account(credential_ref=ref, credential_kind=CredentialKind.MANUAL_BEARER)
    store.save((expected,))
    assert store.load() == (expected,)
    for ref in (
        "synthetic-secret",
        "keyring:invalid",
        f"keyring:{new_account_id()}:{new_account_id()}",
    ):
        with pytest.raises(ConfigError):
            store.save((account(credential_ref=ref, credential_kind=CredentialKind.MANUAL_BEARER),))
    assert store.load() == (expected,)


def test_external_reference_is_not_read_or_mutated(store, tmp_path):
    external = tmp_path / "synthetic-first-party.json"
    external.write_text("synthetic secret is never opened")
    expected = account(
        credential_ref=str(external), credential_kind=CredentialKind.CLAUDE_CODE_FILE
    )
    store.save((expected,))
    assert store.load() == (expected,)
    store.mutate(lambda _: ())
    assert external.read_text() == "synthetic secret is never opened"
    assert "synthetic secret" not in store.path.read_text()


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not-json",
        b"\xff",
        b"[]",
        b"null",
        b'{"schema_version":2,"accounts":[]}',
        b'{"schema_version":true,"accounts":[]}',
        b'{"schema_version":1,"accounts":null}',
        b'{"schema_version":1,"accounts":[],"secret":"synthetic"}',
        b'{"schema_version":1,"schema_version":1,"accounts":[]}',
        b'{"schema_version":1,"accounts":[NaN]}',
        b'{"schema_version":1,"accounts":[{"id":"synthetic-secret"}]}',
        b"[" * 2000,
    ],
)
def test_bad_config_cannot_be_overwritten(store, content):
    write_config(store, content)
    for operation in (store.load, lambda: store.save(()), lambda: store.mutate(lambda _: ())):
        with pytest.raises(ConfigError) as error:
            operation()
        assert "synthetic" not in str(error.value)
        assert store.path.read_bytes() == content


def test_duplicate_ids_and_unknown_account_fields(store):
    with pytest.raises(ConfigError):
        store.save((account(), account()))
    data = {"schema_version": 1, "accounts": [dict(account().to_dict(), secret="synthetic")]}
    write_config(store, json.dumps(data).encode())
    with pytest.raises(ConfigError):
        store.load()


@pytest.mark.parametrize("mode", [0o644, 0o660, 0o700, 0o400])
def test_unsafe_config_modes(store, mode):
    store.save(())
    store.path.chmod(mode)
    with pytest.raises(ConfigError):
        store.load()
    assert stat.S_IMODE(store.path.stat().st_mode) == mode


def test_unsafe_parent_is_not_repaired(store):
    store.path.parent.mkdir(mode=0o755)
    with pytest.raises(ConfigError):
        store.save(())
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o755


@pytest.mark.parametrize("target", ["config", "lock", "parent", "ancestor"])
def test_symlinks_are_rejected(store, tmp_path, target):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    if target == "parent":
        store.path.parent.symlink_to(real, target_is_directory=True)
    elif target == "ancestor":
        link = tmp_path / "link"
        link.symlink_to(real, target_is_directory=True)
        store = AccountStore(link / "private" / "accounts.json")
    else:
        store.path.parent.mkdir(mode=0o700)
        secret = real / "untouched"
        secret.write_text("synthetic")
        secret.chmod(0o600)
        path = store.path if target == "config" else store.path.parent / ".accounts.json.lock"
        path.symlink_to(secret)
    with pytest.raises(ConfigError):
        store.save(())
    if target in {"config", "lock"}:
        assert secret.read_text() == "synthetic"


def test_hardlinks_nonregular_and_oversized_config(store, tmp_path):
    store.save(())
    os.link(store.path, tmp_path / "hardlink")
    with pytest.raises(ConfigError):
        store.load()
    store.path.unlink()
    os.mkfifo(store.path, mode=0o600)
    with pytest.raises(ConfigError):
        store.load()
    store.path.unlink()
    write_config(store, b" " * (MAX_FILE_BYTES + 1))
    with pytest.raises(ConfigError):
        store.load()


def test_foreign_ownership_is_rejected(store, monkeypatch):
    store.save(())
    monkeypatch.setattr(os, "getuid", lambda: store.path.stat().st_uid + 1)
    with pytest.raises(ConfigError):
        store.load()


def test_save_size_and_result_type_are_bounded(store):
    store.save(())
    with pytest.raises(ConfigError):
        store.save([account()])
    with pytest.raises(ConfigError):
        store.mutate(lambda _: None)
    huge = tuple(account(id=new_account_id(), label="x" * 80) for _ in range(5000))
    with pytest.raises(ConfigError):
        store.save(huge)
    assert store.load() == ()


@pytest.mark.parametrize("stage", ["replace", "fsync"])
def test_atomic_failure_keeps_old_config_and_cleans_temporary(store, monkeypatch, stage):
    store.save((account(),))
    before = store.path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("synthetic-sensitive-failure")

    monkeypatch.setattr(os, stage, fail)
    with pytest.raises(ConfigError) as error:
        store.save((account(label="Changed"),))
    assert "synthetic-sensitive" not in str(error.value)
    assert store.path.read_bytes() == before
    assert sorted(path.name for path in store.path.parent.iterdir()) == [
        ".accounts.json.lock",
        "accounts.json",
    ]


def test_cancelled_callback_leaves_config_and_releases_lock(store):
    store.save((account(),))

    def cancel(_):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        store.mutate(cancel)
    assert AccountStore(store.path).load() == (account(),)
    store.mutate(lambda _: ())


def test_concurrent_process_mutations_reread_after_lock(store):
    store.save(())
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    start = context.Event()
    children = [
        context.Process(target=_concurrent_append, args=(str(store.path), ready, start, label))
        for label in ("One", "Two", "Three")
    ]
    try:
        for child in children:
            child.start()
        assert {ready.get(timeout=10) for _ in children} == {"One", "Two", "Three"}
        start.set()
        for child in children:
            child.join(timeout=10)
            assert child.exitcode == 0
        assert {item.label for item in store.load()} == {"One", "Two", "Three"}
    finally:
        start.set()
        for child in children:
            if child.is_alive():
                child.terminate()
            child.join(timeout=5)
        ready.close()
        ready.join_thread()


def test_foreign_config_owner_is_rejected_even_with_private_directory(store, monkeypatch):
    store.save(())
    config_inode = store.path.stat().st_ino
    original = os.fstat

    def foreign_config(fd):
        info = original(fd)
        if info.st_ino == config_inode:
            values = list(info)
            values[4] = os.getuid() + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(os, "fstat", foreign_config)
    with pytest.raises(ConfigError):
        store.load()


def test_unencodable_config_text_is_safe_and_non_destructive(store):
    store.save((account(),))
    with pytest.raises(ConfigError):
        store.save(
            (
                account(
                    credential_ref="/synthetic/\ud800",
                    credential_kind=CredentialKind.CLAUDE_CODE_FILE,
                ),
            )
        )
    assert store.load() == (account(),)
