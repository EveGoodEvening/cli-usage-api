"""Account transactions use actual isolated config and session credentials."""

import os
import stat
from dataclasses import replace
from uuid import uuid4

import pytest

from cli_usage_api import accounts as accounts_module
from cli_usage_api.accounts import (
    FILE_KINDS,
    KINDS,
    MAX_ACCOUNTS,
    AccountFlowError,
    AccountService,
    allowed_kinds,
    credential_identity,
    grok_scopes,
    storage_class,
    validate_reference,
    validate_secret,
)
from cli_usage_api.credentials import CredentialResolver
from cli_usage_api.domain import (
    Account,
    CredentialKind,
    ProviderId,
    default_poll_interval_seconds,
)
from cli_usage_api.storage import AccountStore, ConfigError, CredentialError, CredentialStore


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


def test_reorder_persists_permutation_without_credential_effects(services):
    store, _, service = services

    class ForbiddenCredentials:
        def __getattr__(self, _name):
            pytest.fail("reorder touched the secret store")

    first, second, third = (service.save(account())[-1] for _ in range(3))
    service.credentials = ForbiddenCredentials()
    order = [third.id, first.id, second.id]
    assert service.reorder(order) == (third, first, second)
    assert store.load() == (third, first, second)


@pytest.mark.parametrize("shape", ["stale", "duplicate", "partial", "extra", "type"])
def test_reorder_rejects_non_permutations_without_writing(services, shape):
    store, _, service = services
    first, second = (service.save(account())[-1] for _ in range(2))
    ids = {
        "stale": [second.id, str(uuid4())],
        "duplicate": [first.id, first.id],
        "partial": [second.id],
        "extra": [second.id, first.id, str(uuid4())],
        "type": f"{second.id}{first.id}",
    }[shape]
    before = store.path.read_bytes()
    with pytest.raises(AccountFlowError, match="changed elsewhere") as error:
        service.reorder(ids)
    assert error.value.code == "conflict"
    assert error.value.updated is None
    assert store.path.read_bytes() == before


def test_reorder_committed_uncertain_reports_updated(services, monkeypatch):
    store, _, service = services
    first, second = (service.save(account())[-1] for _ in range(2))
    fsync = os.fsync

    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("synthetic-directory-error")
        fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory)
    with pytest.raises(AccountFlowError) as error:
        service.reorder((second.id, first.id))
    assert error.value.code == "committed_uncertain"
    assert error.value.updated == (second, first)
    assert AccountStore(store.path).load() == (second, first)


def test_stale_original_is_conflict_and_rolls_back_new_reference(services):
    store, credentials, service = services
    original = service.save(
        account(credential_kind=CredentialKind.MANUAL_BEARER, credential_ref=f"session:{uuid4()}"),
        secret="synthetic-old",
    )[0]
    other = replace(original, label="Concurrent edit")
    store.mutate(lambda _: (other,))
    before = dict(credentials._session)
    with pytest.raises(AccountFlowError) as error:
        service.save(original, original=original, secret="synthetic-new")
    assert str(error.value) == "Account changed elsewhere; reopen the form."
    assert error.value.code == "conflict"
    assert credentials._session == before
    with pytest.raises(AccountFlowError) as error:
        service.remove(original)
    assert str(error.value) == "Account changed elsewhere; reopen the manager."
    assert error.value.code == "conflict"
    assert store.load() == (other,)


def test_conflict_rollback_failure_is_credential_cleanup_failed(services):
    store, _, service = services
    original = service.save(account())[0]
    store.mutate(lambda _: (replace(original, label="Concurrent edit"),))

    class FailingDelete(CredentialStore):
        def delete(self, ref):
            raise CredentialError("DO-NOT-DISPLAY")

    service.credentials = FailingDelete()
    with pytest.raises(AccountFlowError) as error:
        service.save(original, original=original, secret="synthetic-new")
    assert error.value.code == "credential_cleanup_failed"
    assert error.value.updated is None
    assert "DO-NOT-DISPLAY" not in str(error.value)


def test_persist_without_secure_backend_is_secure_store_unavailable(services, monkeypatch):
    store, credentials, service = services

    def unavailable():
        raise CredentialError("DO-NOT-DISPLAY")

    monkeypatch.setattr(credentials, "_secure_backend", unavailable)
    with pytest.raises(AccountFlowError) as error:
        service.save(
            account(credential_kind=CredentialKind.API_KEY, credential_ref=f"session:{uuid4()}"),
            secret="synthetic",
            persist=True,
        )
    assert error.value.code == "secure_store_unavailable"
    assert isinstance(error.value.__context__, CredentialError)
    assert "DO-NOT-DISPLAY" not in str(error.value)
    assert not credentials._session  # Never downgraded to session storage.
    assert store.load() == ()


def test_config_error_is_config_unavailable(services, monkeypatch):
    store, credentials, service = services
    saved = service.save(account())[0]

    def fail(_change):
        raise ConfigError("synthetic")

    monkeypatch.setattr(store, "mutate", fail)
    for operation in (
        lambda: service.save(
            account(credential_kind=CredentialKind.MANUAL_BEARER, credential_ref="session:x"),
            secret="synthetic",
        ),
        lambda: service.remove(saved),
        lambda: service.reorder([saved.id]),
    ):
        with pytest.raises(AccountFlowError) as error:
            operation()
        assert error.value.code == "config_unavailable"
        assert error.value.updated is None
    assert not credentials._session


def test_other_store_failure_is_save_failed(services, monkeypatch):
    store, _, service = services

    def fail(_change):
        raise RuntimeError("DO-NOT-DISPLAY")

    monkeypatch.setattr(store, "mutate", fail)
    with pytest.raises(AccountFlowError) as error:
        service.save(account())
    assert error.value.code == "save_failed"
    assert "DO-NOT-DISPLAY" not in str(error.value)


def test_cleanup_failure_code_carries_updated(services):
    store, _, service = services
    saved = service.save(
        account(credential_kind=CredentialKind.MANUAL_BEARER, credential_ref=f"session:{uuid4()}"),
        secret="synthetic-old",
    )[0]

    class FailingDelete:
        def delete(self, _ref):
            raise RuntimeError("secret error")

    service.credentials = FailingDelete()
    with pytest.raises(AccountFlowError) as error:
        service.remove(saved)
    assert error.value.code == "cleanup_failed"
    assert error.value.updated == () == store.load()


def test_account_limit_rejects_creation_beyond_maximum(services, monkeypatch):
    store, credentials, service = services
    monkeypatch.setattr(accounts_module, "MAX_ACCOUNTS", 3)
    saved = [service.save(account())[-1] for _ in range(3)]
    with pytest.raises(AccountFlowError, match=r"Too many accounts \(limit 3\)") as error:
        service.save(
            account(credential_kind=CredentialKind.MANUAL_BEARER, credential_ref="session:x"),
            secret="synthetic",
        )
    assert error.value.code == "too_many_accounts"
    assert not credentials._session
    assert store.load() == tuple(saved)
    # Editing an existing account at the limit is still allowed.
    renamed = replace(saved[0], label="Renamed")
    assert service.save(renamed, original=saved[0])[0] == renamed


def test_hundred_and_first_account_is_rejected(services):
    store, _, service = services
    accounts = tuple(account() for _ in range(MAX_ACCOUNTS))
    store.mutate(lambda _: accounts)
    with pytest.raises(AccountFlowError) as error:
        service.save(account())
    assert error.value.code == "too_many_accounts"
    assert str(error.value) == "Too many accounts (limit 100)."
    assert store.load() == accounts


def test_allowed_kinds_follow_display_order_and_exclude_codex_keys():
    assert allowed_kinds(ProviderId.CODEX_SUBSCRIPTION) == (CredentialKind.CODEX_AUTH_FILE,)
    assert allowed_kinds(ProviderId.OPENAI_PLATFORM) == (CredentialKind.OPENAI_PLATFORM_SESSION,)
    no_keys = {ProviderId.CODEX_SUBSCRIPTION, ProviderId.OPENAI_PLATFORM}
    for provider in ProviderId:
        kinds = allowed_kinds(provider)
        assert list(kinds) == [kind for kind in KINDS if kind in kinds]
        assert (CredentialKind.API_KEY in kinds) == (provider not in no_keys)
        # The OpenAI session is never offered for (or accepted by) another provider.
        assert (CredentialKind.OPENAI_PLATFORM_SESSION in kinds) == (
            provider == ProviderId.OPENAI_PLATFORM
        )


def test_openai_session_secret_rules_reject_keys_headers_and_har_text():
    token = "sess-" + "A1b2C3d4" * 4
    kind = CredentialKind.OPENAI_PLATFORM_SESSION
    assert validate_secret(kind, token) == token
    # Surrounding whitespace is the only thing removed.
    assert validate_secret(kind, f"  {token}\n") == token
    for value in (
        None,
        "",
        "short-token",
        "x" * 4097,
        "sk-proj-" + "a" * 40,
        "Bearer " + token,
        "bearer" + token,
        "Cookie: __Secure-next-auth=" + token,
        "Authorization: Bearer " + token,
        token[:10] + " " + token[10:],
        token[:10] + "\r\n" + token[10:],
        '{"sensitive_id": "' + token + '"}',
        '{"log": {"entries": []}}',
        token + ";other=1",
    ):
        with pytest.raises(AccountFlowError) as error:
            validate_secret(kind, value)
        assert error.value.code == "invalid_secret"
        assert token not in str(error.value)
    with pytest.raises(AccountFlowError):
        validate_secret(kind, token, maximum=len(token) - 1)


def test_openai_session_account_keeps_secret_out_of_config(services):
    store, credentials, service = services
    secret = "sess-" + "s" * 30
    openai = Account(
        id=str(uuid4()),
        provider=ProviderId.OPENAI_PLATFORM,
        label="Synthetic OpenAI",
        credential_kind=CredentialKind.OPENAI_PLATFORM_SESSION,
        credential_ref=f"session:{uuid4()}",
        organization_id="org-Synthetic01",
        poll_interval_seconds=default_poll_interval_seconds(ProviderId.OPENAI_PLATFORM),
    )
    saved = service.save(openai, secret=secret)[0]
    assert saved.poll_interval_seconds == 300
    assert saved.organization_id == "org-Synthetic01"
    assert credentials.get(saved.credential_ref) == secret
    assert secret not in store.path.read_text()
    assert storage_class(saved) == "session"
    # Changing only the organization is a new connection identity.
    moved = replace(saved, organization_id="org-Synthetic02")
    assert credential_identity(moved) != credential_identity(saved)


@pytest.mark.parametrize(
    ("kind", "reference"),
    [
        (CredentialKind.CODEX_AUTH_FILE, "default"),
        (CredentialKind.CODEX_AUTH_FILE, "/home/user/.codex/auth.json"),
        (CredentialKind.GROK_AUTH_FILE, "/data/grok/auth.json"),
        (CredentialKind.CLAUDE_CODE_FILE, "/root/.claude/.credentials.json"),
        (CredentialKind.CLAUDE_CODE_FILE, "/procfs/.credentials.json"),
    ],
)
def test_validate_reference_accepts_default_and_normalized_login_paths(kind, reference):
    assert validate_reference(kind, reference) == reference


@pytest.mark.parametrize(
    ("kind", "reference"),
    [
        (CredentialKind.CODEX_AUTH_FILE, "relative/auth.json"),
        (CredentialKind.CODEX_AUTH_FILE, "auth.json"),
        (CredentialKind.CODEX_AUTH_FILE, "/home/user/.codex/other.json"),
        (CredentialKind.CODEX_AUTH_FILE, "/home/user/.codex/.credentials.json"),
        (CredentialKind.CLAUDE_CODE_FILE, "/home/user/.claude/auth.json"),
        (CredentialKind.CODEX_AUTH_FILE, "/home/user/../user/auth.json"),
        (CredentialKind.CODEX_AUTH_FILE, "/home/./user/auth.json"),
        (CredentialKind.CODEX_AUTH_FILE, "//home/user/auth.json"),
        (CredentialKind.CODEX_AUTH_FILE, "/home//user/auth.json"),
        (CredentialKind.CODEX_AUTH_FILE, "/home/user/auth.json/"),
        (CredentialKind.CODEX_AUTH_FILE, "/proc/self/root/auth.json"),
        (CredentialKind.CODEX_AUTH_FILE, "/sys/auth.json"),
        (CredentialKind.CODEX_AUTH_FILE, "/dev/fd/auth.json"),
        (CredentialKind.CODEX_AUTH_FILE, "/home/\ud800/auth.json"),
        (CredentialKind.CODEX_AUTH_FILE, "/home/a\nb/auth.json"),
        (CredentialKind.CODEX_AUTH_FILE, "/home/a\x7fb/auth.json"),
        (CredentialKind.CODEX_AUTH_FILE, "/" + "a" * 4096 + "/auth.json"),
        (CredentialKind.CODEX_AUTH_FILE, ""),
        (CredentialKind.CODEX_AUTH_FILE, "/"),
        (CredentialKind.CODEX_AUTH_FILE, None),
        (CredentialKind.CODEX_AUTH_FILE, b"/home/user/auth.json"),
        (CredentialKind.MANUAL_BEARER, "default"),
    ],
)
def test_validate_reference_rejects_unsafe_or_wrong_basename(kind, reference):
    with pytest.raises(AccountFlowError) as error:
        validate_reference(kind, reference)
    assert error.value.code == "invalid_reference"
    if kind in FILE_KINDS:
        expected = ".credentials.json" if kind == CredentialKind.CLAUDE_CODE_FILE else "auth.json"
        assert str(error.value) == f"Choose default or an absolute path to {expected}."


def test_validate_secret_uses_transport_token_rules():
    assert validate_secret(CredentialKind.MANUAL_BEARER, "abc.DEF-123") == "abc.DEF-123"
    for kind, value in (
        (CredentialKind.MANUAL_BEARER, ""),
        (CredentialKind.MANUAL_BEARER, "has space"),
        (CredentialKind.MANUAL_BEARER, "Bearer\ttoken"),
        (CredentialKind.API_KEY, "café"),
        (CredentialKind.API_KEY, None),
        (CredentialKind.CONSOLE_SESSION, "a;b"),
        (CredentialKind.CONSOLE_SESSION, 'a"b'),
    ):
        with pytest.raises(AccountFlowError) as error:
            validate_secret(kind, value)
        assert error.value.code == "invalid_secret"
    assert validate_secret(CredentialKind.API_KEY, "a;b") == "a;b"
    assert validate_secret(CredentialKind.API_KEY, "x" * 5, maximum=5) == "xxxxx"
    with pytest.raises(AccountFlowError):
        validate_secret(CredentialKind.API_KEY, "x" * 6, maximum=5)


def test_grok_scopes_lists_only_selectable_keys_in_order():
    raw = (
        b'{"https://auth.x.ai::b":{"key":"k"},"other":{},"https://auth.x.ai::":{},'
        b'"https://accounts.x.ai/sign-in":{"key":"l"},"https://auth.x.ai::a":1}'
    )
    assert grok_scopes(raw) == (
        "https://auth.x.ai::b",
        "https://accounts.x.ai/sign-in",
        "https://auth.x.ai::a",
    )
    assert grok_scopes(b"{}") == ()


@pytest.mark.parametrize(
    "raw",
    [
        b"[" * 100_000 + b"]" * 100_000,
        b'{"a":{' * 50_000 + b"}" * 100_000,
        b'{"https://auth.x.ai::a":1,"https://auth.x.ai::a":2}',
        b'{"x":NaN}',
        b"[]",
        b"not json",
        b"\xff\xfe",
    ],
)
def test_grok_scopes_rejects_malformed_files(raw):
    with pytest.raises(AccountFlowError) as error:
        grok_scopes(raw)
    assert error.value.code == "invalid_credential_file"
    assert error.value.__context__ is None


def test_storage_class_and_credential_identity():
    file_account = account(
        credential_kind=CredentialKind.CLAUDE_CODE_FILE, credential_ref="default"
    )
    session = account(
        credential_kind=CredentialKind.MANUAL_BEARER, credential_ref=f"session:{uuid4()}"
    )
    keyring_account = account(
        credential_kind=CredentialKind.API_KEY, credential_ref=f"keyring:{uuid4()}:{uuid4()}"
    )
    assert storage_class(file_account) == "external_file"
    assert storage_class(session) == "session"
    assert storage_class(keyring_account) == "keyring"
    assert storage_class(account()) == "none"
    renamed = replace(session, label="Other", enabled=False, poll_interval_seconds=120)
    assert credential_identity(renamed) == credential_identity(session)
    assert credential_identity(replace(session, credential_ref=f"session:{uuid4()}")) != (
        credential_identity(session)
    )
    assert credential_identity(file_account) == (
        ProviderId.CLAUDE_SUBSCRIPTION,
        CredentialKind.CLAUDE_CODE_FILE,
        "default",
        None,
        None,
    )
