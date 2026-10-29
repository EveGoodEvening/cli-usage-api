"""Account transactions use actual isolated config and session credentials."""

import os
import stat
from dataclasses import replace
from uuid import uuid4

import pytest

from cli_usage_api.accounts import AccountFlowError, AccountService
from cli_usage_api.credentials import CredentialResolver
from cli_usage_api.domain import Account, CredentialKind, ProviderId
from cli_usage_api.storage import AccountStore, CredentialError, CredentialStore


@pytest.fixture
def services(tmp_path):
    store = AccountStore(tmp_path / "private" / "accounts.json")
    credentials = CredentialStore()
    return store, credentials, AccountService(store, credentials)


def account(**kwargs):
    return Account(str(uuid4()), ProviderId.CLAUDE_SUBSCRIPTION, "Synthetic", **kwargs)


def test_create_update_toggle_remove(services):
    store, _, service = services
    original = account()
    assert service.save(original) == (original,)
    edited = replace(original, label="Renamed", enabled=False)
    assert service.save(edited, original=original) == (edited,)
    assert service.remove(edited) == ()
    assert store.load() == ()


def test_secret_replace_and_delete_never_enters_config(services):
    store, credentials, service = services
    original = account(
        credential_kind=CredentialKind.MANUAL_BEARER, credential_ref=f"session:{uuid4()}"
    )
    saved = service.save(original, secret="synthetic-first")[0]
    old_ref = saved.credential_ref
    assert credentials.get(old_ref) == "synthetic-first"
    saved = service.save(saved, original=saved, secret="synthetic-second")[0]
    with pytest.raises(CredentialError):
        credentials.get(old_ref)
    assert credentials.get(saved.credential_ref) == "synthetic-second"
    config = store.path.read_text()
    assert "synthetic-first" not in config and "synthetic-second" not in config
    cleared = replace(saved, credential_kind=None, credential_ref=None)
    service.save(cleared, original=saved)
    with pytest.raises(CredentialError):
        credentials.get(saved.credential_ref)


def test_blank_replacement_preserves_reference(services):
    _, credentials, service = services
    draft = account(
        credential_kind=CredentialKind.MANUAL_BEARER, credential_ref=f"session:{uuid4()}"
    )
    saved = service.save(draft, secret="synthetic-old")[0]
    renamed = service.save(replace(saved, label="New label"), original=saved)[0]
    assert renamed.credential_ref == saved.credential_ref
    assert credentials.get(renamed.credential_ref) == "synthetic-old"


def test_external_file_never_deleted_on_remove_or_detach(services, tmp_path):
    _, _, service = services
    external = tmp_path / "external.json"
    external.write_text("synthetic external data")
    original = account(
        credential_kind=CredentialKind.CLAUDE_CODE_FILE, credential_ref=str(external)
    )
    service.save(original)
    detached = replace(original, credential_kind=None, credential_ref=None)
    service.save(detached, original=original)
    assert external.read_text() == "synthetic external data"
    service.save(original, original=detached)
    service.remove(original)
    assert external.read_text() == "synthetic external data"


def test_mutation_conflict_cleans_new_reference(services):
    store, credentials, service = services
    original = account(
        credential_kind=CredentialKind.MANUAL_BEARER, credential_ref=f"session:{uuid4()}"
    )
    original = service.save(original, secret="synthetic-old")[0]
    other = replace(original, label="Concurrent edit")
    store.mutate(lambda _: (other,))
    refs_before = dict(credentials._session)
    with pytest.raises(AccountFlowError):
        service.save(original, original=original, secret="synthetic-new")
    assert credentials._session == refs_before
    assert store.load() == (other,)


def test_config_failure_cleans_new_reference(services, monkeypatch):
    store, credentials, service = services

    def fail(_):
        raise RuntimeError("DO-NOT-DISPLAY synthetic secret")

    monkeypatch.setattr(store, "mutate", fail)
    with pytest.raises(AccountFlowError) as error:
        service.save(
            account(
                credential_kind=CredentialKind.MANUAL_BEARER, credential_ref=f"session:{uuid4()}"
            ),
            secret="synthetic-secret",
        )
    assert "DO-NOT-DISPLAY" not in str(error.value)
    assert not credentials._session


def test_persistent_failure_is_safe_no_silent_session_fallback(services):
    store, _, service = services

    class RefusingCredentials:
        def put(self, *_args, **_kwargs):
            raise RuntimeError("DO-NOT-DISPLAY secret backend detail")

    service.credentials = RefusingCredentials()
    with pytest.raises(AccountFlowError) as error:
        service.save(
            account(credential_kind=CredentialKind.API_KEY, credential_ref=f"session:{uuid4()}"),
            secret="synthetic",
            persist=True,
        )
    assert "DO-NOT-DISPLAY" not in str(error.value)
    assert "session only" in str(error.value)
    assert store.load() == ()


def test_cleanup_failure_reports_committed_config(services):
    store, credentials, service = services
    draft = account(
        credential_kind=CredentialKind.MANUAL_BEARER, credential_ref=f"session:{uuid4()}"
    )
    saved = service.save(draft, secret="synthetic-old")[0]

    class FailingDelete:
        def delete(self, _ref):
            raise RuntimeError("secret error")

    service.credentials = FailingDelete()
    with pytest.raises(AccountFlowError, match="Config saved") as error:
        service.remove(saved)
    assert error.value.updated == ()
    assert store.load() == ()
    assert credentials.get(saved.credential_ref) == "synthetic-old"


def test_explicit_persistence_forwarded_and_old_reference_deleted(services):
    _, _, service = services

    class FakeEncryptedStore:
        def __init__(self):
            self.entries = {}
            self.modes = []

        def put(self, account_id, secret, *, persist):
            self.modes.append(persist)
            ref = f"keyring:{account_id}:{uuid4()}"
            self.entries[ref] = secret
            return ref

        def delete(self, ref):
            self.entries.pop(ref, None)

    fake = FakeEncryptedStore()
    service.credentials = fake
    draft = account(credential_kind=CredentialKind.API_KEY, credential_ref=f"session:{uuid4()}")
    first = service.save(draft, secret="synthetic-first", persist=True)[0]
    second = service.save(first, original=first, secret="synthetic-second", persist=True)[0]
    assert fake.modes == [True, True]
    assert first.credential_ref not in fake.entries
    assert fake.entries == {second.credential_ref: "synthetic-second"}


@pytest.mark.parametrize("operation", ["add", "replace", "remove", "detach"])
def test_directory_sync_failure_preserves_committed_credentials(services, monkeypatch, operation):
    store, credentials, service = services
    draft = account(
        credential_kind=CredentialKind.MANUAL_BEARER, credential_ref=f"session:{uuid4()}"
    )
    original = None if operation == "add" else service.save(draft, secret="synthetic-old")[0]
    fsync = os.fsync
    directories = []

    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directories.append(fd)
            raise OSError("synthetic-sensitive-directory-error")
        fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory)
    with pytest.raises(AccountFlowError, match="crash durability") as error:
        if operation == "remove":
            service.remove(original)
        elif operation == "detach":
            service.save(
                replace(original, credential_kind=None, credential_ref=None), original=original
            )
        else:
            service.save(original or draft, original=original, secret="synthetic-new")
    committed = AccountStore(store.path).load()
    assert directories
    assert error.value.updated == committed
    assert "synthetic-sensitive" not in str(error.value)
    if operation == "remove":
        assert committed == ()
    elif operation == "detach":
        assert committed[0].credential_ref is None
    else:
        assert CredentialResolver(credentials).resolve(committed[0]).secret == "synthetic-new"
    if original is not None:
        assert credentials.get(original.credential_ref) == "synthetic-old"
    assert "synthetic-new" not in store.path.read_text()
    assert "synthetic-old" not in store.path.read_text()


def test_codex_external_file_never_uses_secret_store(services, tmp_path):
    store, _, service = services

    class ForbiddenCredentials:
        def __getattr__(self, _name):
            pytest.fail("Codex external-file flow touched the secret store")

    service.credentials = ForbiddenCredentials()
    external = tmp_path / "auth.json"
    external.write_text("synthetic external data")
    original = Account(
        str(uuid4()),
        ProviderId.CODEX_SUBSCRIPTION,
        "Codex",
        credential_kind=CredentialKind.CODEX_AUTH_FILE,
        credential_ref=str(external),
        enabled=False,
    )
    service.save(original)
    enabled = replace(original, enabled=True)
    service.save(enabled, original=original)
    detached = replace(enabled, credential_kind=None, credential_ref=None)
    service.save(detached, original=enabled)
    service.remove(detached)
    assert store.load() == ()
    assert external.read_text() == "synthetic external data"
