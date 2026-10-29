"""Backend-injected tests: never discover or contact a real system keyring."""

import json
from dataclasses import replace

import pytest
from keyring.backends import fail, null

from cli_usage_api import storage
from cli_usage_api.domain import Account, CredentialKind, ProviderId
from cli_usage_api.storage import AccountStore, CredentialError, CredentialStore

ACCOUNT_ID = "00000000-0000-4000-8000-000000000001"
SECRET = "synthetic-test-secret-not-a-real-token"


class FakeEncrypted:
    """Only tests explicitly whitelist this in-memory stand-in."""

    def __init__(self):
        self.values = {}
        self.calls = []
        self.failure = None

    def _called(self, operation):
        self.calls.append(operation)
        if self.failure == operation:
            raise RuntimeError(SECRET)

    def set_password(self, service, username, password):
        self._called("set")
        self.values[service, username] = password

    def get_password(self, service, username):
        self._called("get")
        return self.values.get((service, username))

    def delete_password(self, service, username):
        self._called("delete")
        del self.values[service, username]


class FakePlaintext(FakeEncrypted):
    priority = 9999


@pytest.fixture(autouse=True)
def no_real_keyring(monkeypatch):
    def forbidden():
        raise AssertionError("A test tried discovering the real keyring")

    monkeypatch.setattr(storage.keyring, "get_keyring", forbidden)


@pytest.fixture
def encrypted(monkeypatch):
    monkeypatch.setattr(storage, "_SECURE_BACKEND_TYPES", (FakeEncrypted,))
    monkeypatch.setattr(storage.sys, "platform", "linux")
    return FakeEncrypted()


def test_session_mode_never_discovers_keyring_and_is_instance_local():
    store = CredentialStore()
    ref = store.put(ACCOUNT_ID, SECRET, persist=False)
    assert ref.startswith("session:")
    assert SECRET not in ref
    assert store.get(ref) == SECRET
    with pytest.raises(CredentialError):
        CredentialStore().get(ref)
    store.delete(ref)
    store.delete(ref)
    with pytest.raises(CredentialError):
        store.get(ref)


def test_session_mode_works_with_rejected_backend():
    store = CredentialStore(backend=null.Keyring())
    ref = store.put(ACCOUNT_ID, SECRET, persist=False)
    assert store.get(ref) == SECRET
    store.delete(ref)


def test_persistent_roundtrip_uses_namespaced_opaque_reference(encrypted):
    store = CredentialStore(backend=encrypted)
    ref = store.put(ACCOUNT_ID, SECRET, persist=True)
    assert ref.startswith(f"keyring:{ACCOUNT_ID}:")
    assert SECRET not in ref
    assert encrypted.values == {("cli-usage-api", ref): SECRET}
    assert CredentialStore(backend=encrypted).get(ref) == SECRET
    store.delete(ref)
    store.delete(ref)
    with pytest.raises(CredentialError):
        store.get(ref)


def test_replacing_secret_does_not_overwrite_old_reference(encrypted):
    store = CredentialStore(encrypted)
    old = store.put(ACCOUNT_ID, SECRET, persist=True)
    new = store.put(ACCOUNT_ID, "synthetic-replacement", persist=True)
    assert new != old
    assert store.get(old) == SECRET
    assert store.get(new) == "synthetic-replacement"
    store.delete(old)
    assert store.get(new) == "synthetic-replacement"


def test_secret_never_enters_account_config(encrypted, tmp_path):
    credentials = CredentialStore(encrypted)
    ref = credentials.put(ACCOUNT_ID, SECRET, persist=True)
    expected = Account(
        ACCOUNT_ID,
        ProviderId.CLAUDE_SUBSCRIPTION,
        "Synthetic",
        credential_ref=ref,
        credential_kind=CredentialKind.MANUAL_BEARER,
    )
    config = AccountStore(tmp_path / "private" / "accounts.json")
    config.save((expected,))
    assert SECRET not in config.path.read_text()
    assert json.loads(config.path.read_text())["accounts"][0]["credential_ref"] == ref
    assert config.load() == (expected,)
    session_ref = credentials.put(ACCOUNT_ID, "synthetic-session", persist=False)
    config.mutate(lambda accounts: (replace(accounts[0], credential_ref=session_ref),))
    assert "synthetic-session" not in config.path.read_text()


@pytest.mark.parametrize("backend_factory", [null.Keyring, fail.Keyring, FakePlaintext])
def test_null_failed_plaintext_and_subclass_backends_rejected(encrypted, backend_factory):
    store = CredentialStore(backend_factory())
    with pytest.raises(CredentialError) as error:
        store.put(ACCOUNT_ID, SECRET, persist=True)
    assert SECRET not in str(error.value)
    assert not store._session
    ref = f"keyring:{ACCOUNT_ID}:00000000-0000-4000-8000-000000000002"
    for operation in (lambda: store.get(ref), lambda: store.delete(ref)):
        with pytest.raises(CredentialError):
            operation()


def test_chain_is_rejected_even_when_containing_secure_backend(encrypted):
    class Chain:
        backends = (encrypted,)
        priority = 9999

    with pytest.raises(CredentialError):
        CredentialStore(Chain()).put(ACCOUNT_ID, SECRET, persist=True)
    assert encrypted.calls == []


def test_default_backend_is_lazy_and_still_validated(encrypted, monkeypatch):
    calls = []

    def discover():
        calls.append(True)
        return encrypted

    monkeypatch.setattr(storage.keyring, "get_keyring", discover)
    store = CredentialStore()
    assert not calls
    session = store.put(ACCOUNT_ID, SECRET, persist=False)
    assert store.get(session) == SECRET
    assert not calls
    ref = store.put(ACCOUNT_ID, SECRET, persist=True)
    assert calls
    assert store.get(ref) == SECRET
    monkeypatch.setattr(storage.keyring, "get_keyring", lambda: FakePlaintext())
    with pytest.raises(CredentialError):
        store.get(ref)


@pytest.mark.parametrize("operation", ["set", "get", "delete"])
def test_locked_backend_failures_are_safe_and_never_fall_back(encrypted, operation):
    store = CredentialStore(encrypted)
    ref = store.put(ACCOUNT_ID, SECRET, persist=True)
    encrypted.failure = operation
    action = {
        "set": lambda: store.put(ACCOUNT_ID, SECRET, persist=True),
        "get": lambda: store.get(ref),
        "delete": lambda: store.delete(ref),
    }[operation]
    with pytest.raises(CredentialError) as error:
        action()
    assert SECRET not in str(error.value)
    assert SECRET not in repr(error.value)
    assert error.value.__suppress_context__
    assert store._session == {}


def test_unavailable_default_backend_has_safe_guidance(monkeypatch):
    def fail_discovery():
        raise RuntimeError(SECRET)

    monkeypatch.setattr(storage.keyring, "get_keyring", fail_discovery)
    with pytest.raises(CredentialError, match="session-only") as error:
        CredentialStore().put(ACCOUNT_ID, SECRET, persist=True)
    assert SECRET not in str(error.value)


def test_unimplemented_platform_is_rejected(encrypted, monkeypatch):
    monkeypatch.setattr(storage.sys, "platform", "win32")
    with pytest.raises(CredentialError):
        CredentialStore(encrypted).put(ACCOUNT_ID, SECRET, persist=True)
    assert not encrypted.calls


@pytest.mark.parametrize(
    "ref", [None, "", SECRET, "file:/tmp/synthetic", "session:bad", "keyring:bad:bad"]
)
def test_malformed_references_fail_before_backend_access(encrypted, ref):
    store = CredentialStore(encrypted)
    for operation in (store.get, store.delete):
        with pytest.raises(CredentialError) as error:
            operation(ref)
        assert SECRET not in str(error.value)
    assert not encrypted.calls


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": "not-a-uuid"},
        {"secret": ""},
        {"secret": None},
        {"secret": "x" * (storage.MAX_FILE_BYTES + 1)},
        {"persist": 1},
    ],
)
def test_invalid_put_never_reaches_backend(encrypted, changes):
    arguments = {"account_id": ACCOUNT_ID, "secret": SECRET, "persist": True} | changes
    with pytest.raises(CredentialError):
        CredentialStore(encrypted).put(**arguments)
    assert not encrypted.calls


@pytest.mark.parametrize("invalid", [None, "", 42, "x" * (storage.MAX_FILE_BYTES + 1)])
def test_backend_returned_secret_must_be_valid(encrypted, invalid):
    store = CredentialStore(encrypted)
    ref = store.put(ACCOUNT_ID, SECRET, persist=True)
    encrypted.values["cli-usage-api", ref] = invalid
    with pytest.raises(CredentialError):
        store.get(ref)


def test_secure_available_reports_exact_backend_type_without_raising(encrypted, monkeypatch):
    class Chain:
        backends = (encrypted,)
        priority = 9999

    assert CredentialStore(encrypted).secure_available() is True
    for backend in (FakePlaintext(), Chain(), null.Keyring(), fail.Keyring()):
        assert CredentialStore(backend).secure_available() is False
    # The default discovery failing (autouse fixture raises) is unavailable, not an error.
    assert CredentialStore().secure_available() is False
    monkeypatch.setattr(storage.sys, "platform", "darwin")
    assert CredentialStore(encrypted).secure_available() is False
    assert encrypted.calls == []  # Probing never stores, reads or deletes anything.


def test_session_present_only_for_live_session_refs(encrypted):
    store = CredentialStore(encrypted)
    ref = store.put(ACCOUNT_ID, SECRET, persist=False)
    persistent = store.put(ACCOUNT_ID, SECRET, persist=True)
    assert store.session_present(ref) is True
    assert store.session_present(persistent) is False
    assert CredentialStore().session_present(ref) is False
    for invalid in (None, 1, "", "session:", "default", f"session:{ACCOUNT_ID}"):
        assert store.session_present(invalid) is False
    store.delete(ref)
    assert store.session_present(ref) is False
    assert encrypted.calls == ["set"]


def test_put_always_mints_a_fresh_reference(encrypted):
    store = CredentialStore(encrypted)
    refs = [store.put(ACCOUNT_ID, SECRET, persist=persist) for persist in (False, True) * 20]
    assert len(set(refs)) == len(refs)


def test_blocked_backend_never_delays_session_reads(monkeypatch):
    import threading

    entered = threading.Event()
    release = threading.Event()

    class Blocking(FakeEncrypted):
        def set_password(self, service, username, password):
            entered.set()
            assert release.wait(10)
            super().set_password(service, username, password)

    monkeypatch.setattr(storage, "_SECURE_BACKEND_TYPES", (Blocking,))
    monkeypatch.setattr(storage.sys, "platform", "linux")
    store = CredentialStore(Blocking())
    ref = store.put(ACCOUNT_ID, SECRET, persist=False)
    errors = []

    def persist():
        try:
            store.put(ACCOUNT_ID, SECRET, persist=True)
        except Exception as error:  # noqa: BLE001 - Report to the main thread.
            errors.append(error)

    worker = threading.Thread(target=persist)
    worker.start()
    try:
        assert entered.wait(10)
        done = threading.Event()
        results = []

        def read():
            results.append((store.get(ref), store.session_present(ref)))
            store.delete(store.put(ACCOUNT_ID, "other", persist=False))
            done.set()

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        # The session operations finish while set_password is still blocked.
        assert done.wait(5)
        assert worker.is_alive()
        assert results == [(SECRET, True)]
    finally:
        release.set()
        worker.join(10)
    assert not errors
