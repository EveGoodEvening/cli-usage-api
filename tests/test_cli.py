"""CLI contracts with isolated HOME and synthetic credentials; no real keyring/network."""

from __future__ import annotations

import builtins
import getpass
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from usage_tui import cli
from usage_tui.domain import Account, CredentialKind, ProviderId
from usage_tui.providers.console import OrganizationChoice
from usage_tui.storage import AccountStore, ConfigCommittedError, ConfigError, CredentialStore

SECRET = "synthetic-cli-secret-never-display"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "config"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("GROK_HOME", raising=False)
    return home


@pytest.fixture(autouse=True)
def terminal_boundary(monkeypatch):
    real_tty = cli._tty
    # Behavior tests do not depend on pytest's replaceable capture streams.
    monkeypatch.setattr(cli, "_tty", lambda: True)
    return real_tty


class MemoryCredentials(CredentialStore):
    """Synthetic secure-persistence boundary, never an actual keyring backend."""

    def __init__(self):
        super().__init__()
        self.values = {}
        self.persisted = []
        self.deleted = []

    def put(self, account_id, secret, *, persist):
        ref = f"keyring:{account_id}:{uuid4()}" if persist else f"session:{uuid4()}"
        self.values[ref] = secret
        if persist:
            self.persisted.append(ref)
        return ref

    def get(self, ref):
        return self.values[ref]

    def delete(self, ref):
        self.deleted.append(ref)
        self.values.pop(ref, None)


@pytest.fixture
def credentials(monkeypatch):
    store = MemoryCredentials()
    monkeypatch.setattr(cli, "CredentialStore", lambda: store)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: SECRET)
    return store


def answers(monkeypatch, *values):
    iterator = iter(values)
    monkeypatch.setattr(builtins, "input", lambda prompt: next(iterator))


def account(provider=ProviderId.CLAUDE_SUBSCRIPTION, **kwargs):
    return Account(id=str(uuid4()), provider=provider, label="Synthetic", **kwargs)


def seed(item):
    AccountStore().save((item,))
    return item.id


def test_help_never_constructs_services(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Help must not construct live services")

    monkeypatch.setattr(cli, "AccountStore", forbidden)
    monkeypatch.setattr(cli, "LiveFactory", forbidden)
    assert cli.main(["--help"]) == 0
    assert "accounts" in capsys.readouterr().out


@pytest.mark.parametrize("scenario", ["healthy", "errors"])
def test_demo_has_no_live_construction(monkeypatch, scenario):
    calls = []

    def forbidden(*args, **kwargs):
        pytest.fail("Demo must not construct or read live services")

    for name in (
        "AccountStore",
        "CredentialStore",
        "CredentialResolver",
        "Transport",
        "LiveFactory",
    ):
        monkeypatch.setattr(cli, name, forbidden)
    monkeypatch.setattr(
        cli,
        "UsageApp",
        lambda **kwargs: SimpleNamespace(run=lambda: calls.append(kwargs)),
    )
    assert cli.main(["--demo", "--scenario", scenario]) == 0
    assert calls == [{"mode": "demo", "scenario": scenario}]


def test_live_passes_real_composition_to_app(monkeypatch):
    item = account()
    seed(item)
    calls = []
    monkeypatch.setattr(
        cli,
        "UsageApp",
        lambda **kwargs: SimpleNamespace(run=lambda: calls.append(kwargs)),
    )
    assert cli.main([]) == 0
    kwargs = calls[0]
    assert kwargs["mode"] == "live"
    assert kwargs["accounts"] == (item,)
    factory = kwargs["scheduler_factory"]
    assert isinstance(factory, cli.LiveFactory)
    assert factory.resolver._store is kwargs["credential_store"]
    assert set(factory.providers) == set(ProviderId)
    assert (
        factory.console_discovery
        == factory.providers[ProviderId.CLAUDE_PLATFORM].discover_organizations
    )


async def test_factory_scheduler_and_close_contract():
    factory = cli.LiveFactory(CredentialStore())
    scheduler = factory((), publish=lambda snapshot: None)
    assert scheduler._resolver is factory.resolver
    assert scheduler._providers is factory.providers
    await factory.aclose()
    await factory.aclose()
    assert scheduler._closed
    with pytest.raises(RuntimeError, match="closed"):
        factory((), publish=lambda snapshot: None)


@pytest.mark.parametrize(
    "args",
    [
        ["--scenario", "errors"],
        ["--demo", "accounts", "list"],
        ["accounts"],
        ["accounts", "add", "--provider", "invalid"],
        ["accounts", "key", "set", "id", "--token", SECRET],
        ["--api-key", SECRET],
    ],
)
def test_usage_errors_do_not_echo_arguments(args, capsys):
    assert cli.main(args) == 2
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    assert "--help" in captured.err or "--demo" in captured.err


def test_list_empty_and_nonsecret_metadata(monkeypatch, capsys, terminal_boundary):
    monkeypatch.setattr(cli, "_tty", terminal_boundary)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: False)
    assert cli.main(["accounts", "list"]) == 0
    assert "No accounts" in capsys.readouterr().out
    item = account(
        credential_kind=CredentialKind.MANUAL_BEARER,
        credential_ref=f"keyring:{uuid4()}:{uuid4()}",
    )
    item = replace(item, credential_ref=f"keyring:{item.id}:{uuid4()}")
    seed(item)
    assert cli.main(["accounts", "list"]) == 0
    output = capsys.readouterr().out
    assert item.id in output and item.label in output
    assert "manual_bearer" in output
    assert item.credential_ref not in output


@pytest.mark.parametrize(
    "action",
    [
        ["add", "--provider", "claude-platform"],
        ["key", "set", "local-id"],
        ["remove", "local-id"],
    ],
)
@pytest.mark.parametrize("stream", ["stdin", "stdout"])
def test_mutations_refuse_non_tty_without_getpass(
    monkeypatch, action, stream, capsys, terminal_boundary
):
    monkeypatch.setattr(cli, "_tty", terminal_boundary)
    # Patch the current call-phase streams, not fixture-setup capture objects.
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: stream != "stdin")
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: stream != "stdout")
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: pytest.fail("No secret read"))
    assert cli.main(["accounts", *action]) == 2
    assert "TTY" in capsys.readouterr().err
    assert AccountStore().load() == ()


def test_profile_add_edit_remove(monkeypatch, credentials):
    answers(monkeypatch, "My profile", "90", "no", "1", "yes")
    assert cli.main(["accounts", "add", "--provider", "chatgpt-subscription"]) == 0
    (item,) = AccountStore().load()
    assert item.provider == ProviderId.CHATGPT_SUBSCRIPTION
    assert item.label == "My profile" and not item.enabled
    assert item.poll_interval_seconds == 90 and item.credential_ref is None
    answers(monkeypatch, "Renamed", "30", "yes", "no", "yes")
    assert cli.main(["accounts", "edit", item.id]) == 0
    (edited,) = AccountStore().load()
    assert edited.label == "Renamed" and edited.enabled
    answers(monkeypatch, "no")
    assert cli.main(["accounts", "remove", item.id]) == 0
    assert AccountStore().load() == (edited,)
    answers(monkeypatch, "yes")
    assert cli.main(["accounts", "remove", item.id]) == 0
    assert AccountStore().load() == ()


@pytest.mark.parametrize("provider", list(cli.PROVIDER_NAMES))
def test_explicit_provider_spellings(monkeypatch, credentials, provider):
    answers(monkeypatch, "Fictional", "60", "yes", "1", "yes")
    assert cli.main(["accounts", "add", "--provider", provider]) == 0
    (item,) = AccountStore().load()
    assert item.provider == cli.PROVIDER_NAMES[provider]


@pytest.mark.parametrize("cancel", ["\x1b", KeyboardInterrupt(), EOFError()])
def test_cancel_before_commit_changes_nothing(monkeypatch, credentials, cancel):
    item = account()
    seed(item)

    def stop(prompt):
        if isinstance(cancel, BaseException):
            raise cancel
        return cancel

    monkeypatch.setattr(builtins, "input", stop)
    assert cli.main(["accounts", "edit", item.id]) == 0
    assert AccountStore().load() == (item,)
    assert not credentials.persisted


def test_cancel_secret_form_does_not_persist(monkeypatch, credentials):
    item = account()
    seed(item)
    answers(monkeypatch, "3", "no")  # Claude manual bearer; decline final replacement.
    assert cli.main(["accounts", "key", "set", item.id]) == 0
    assert AccountStore().load() == (item,)
    assert credentials.values == {} and credentials.persisted == []


def test_secret_set_replace_delete_never_reveals(monkeypatch, credentials, capsys):
    item = account()
    seed(item)
    for _ in range(2):
        answers(monkeypatch, "3", "yes")
        assert cli.main(["accounts", "key", "set", item.id]) == 0
    (updated,) = AccountStore().load()
    assert updated.credential_kind == CredentialKind.MANUAL_BEARER
    assert len(credentials.persisted) == 2
    assert credentials.persisted[0] in credentials.deleted
    assert credentials.get(updated.credential_ref) == SECRET
    assert SECRET not in AccountStore().path.read_text()
    answers(monkeypatch, "yes")
    assert cli.main(["accounts", "key", "delete", item.id]) == 0
    (cleared,) = AccountStore().load()
    assert cleared.credential_kind is None and cleared.credential_ref is None
    assert not credentials.values
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err


def test_local_api_key_is_explicitly_unsupported(monkeypatch, credentials, capsys):
    item = account()
    seed(item)
    answers(monkeypatch, "4", "yes")
    assert cli.main(["accounts", "key", "set", item.id]) == 0
    (updated,) = AccountStore().load()
    assert updated.credential_kind == CredentialKind.API_KEY
    assert "no usage reads enabled" in capsys.readouterr().out


def test_console_discovery_uses_canonical_callable_and_explicit_choice(
    monkeypatch,
    credentials,
    capsys,
):
    item = account(ProviderId.CLAUDE_PLATFORM)
    seed(item)
    observed = []

    async def discover(credential):
        observed.append(credential)
        return (OrganizationChoice("org-one", "Synthetic organization"),)

    monkeypatch.setattr(
        cli,
        "build_providers",
        lambda transport, resolver: {
            ProviderId.CLAUDE_PLATFORM: SimpleNamespace(discover_organizations=discover)
        },
    )
    answers(monkeypatch, "2", "yes", "1", "yes")
    assert cli.main(["accounts", "key", "set", item.id]) == 0
    (updated,) = AccountStore().load()
    assert updated.organization_id == "org-one"
    assert observed[0].secret == SECRET
    assert observed[0].provider == ProviderId.CLAUDE_PLATFORM
    output = capsys.readouterr().out
    assert "High-sensitivity" in output and "sessionKey value" in output
    assert SECRET not in output


def test_console_single_result_is_not_autoselected(monkeypatch, credentials):
    item = account(ProviderId.CLAUDE_PLATFORM)
    seed(item)

    async def discover(credential):
        return (OrganizationChoice("org-one", "Synthetic"),)

    monkeypatch.setattr(
        cli,
        "build_providers",
        lambda transport, resolver: {
            ProviderId.CLAUDE_PLATFORM: SimpleNamespace(discover_organizations=discover)
        },
    )
    answers(monkeypatch, "2", "yes", "")
    assert cli.main(["accounts", "key", "set", item.id]) == 2
    assert AccountStore().load() == (item,)
    assert credentials.values == {}


def test_grok_scope_is_explicit_and_external_file_survives(isolated_home, monkeypatch, credentials):
    path = isolated_home / "grok-auth.json"
    path.write_text('{"https://auth.x.ai::synthetic":{"key":"synthetic-token"}}')
    path.chmod(0o600)
    item = account(ProviderId.GROK_SUBSCRIPTION)
    seed(item)
    answers(monkeypatch, "2", str(path), "1", "yes")
    assert cli.main(["accounts", "key", "set", item.id]) == 0
    (updated,) = AccountStore().load()
    assert updated.credential_selector == "https://auth.x.ai::synthetic"
    answers(monkeypatch, "yes")
    assert cli.main(["accounts", "remove", item.id]) == 0
    assert path.exists()
    assert not credentials.persisted


def test_missing_account_is_safe_error(capsys):
    assert cli.main(["accounts", "edit", SECRET]) == 2
    assert SECRET not in capsys.readouterr().err


def test_unavailable_keyring_never_saves_session_ref(monkeypatch, capsys):
    from usage_tui.storage import CredentialError

    item = account()
    seed(item)
    store = CredentialStore()
    monkeypatch.setattr(cli, "CredentialStore", lambda: store)
    monkeypatch.setattr(
        store, "_secure_backend", lambda: (_ for _ in ()).throw(CredentialError(SECRET))
    )
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: SECRET)
    answers(monkeypatch, "3", "yes")
    assert cli.main(["accounts", "key", "set", item.id]) == 3
    assert AccountStore().load() == (item,)
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err


def test_config_error_is_exit_two_and_redacted(monkeypatch, capsys):
    def fail(self):
        raise ConfigError(SECRET)

    monkeypatch.setattr(AccountStore, "load", fail)
    assert cli.main(["accounts", "list"]) == 2
    assert SECRET not in capsys.readouterr().err


def test_committed_warning_retains_new_and_old_credentials(monkeypatch, credentials, capsys):
    item = account()
    old = credentials.put(item.id, "synthetic-old", persist=True)
    item = replace(item, credential_kind=CredentialKind.MANUAL_BEARER, credential_ref=old)
    seed(item)
    mutate = AccountStore.mutate

    def committed(self, change):
        updated = mutate(self, change)
        raise ConfigCommittedError(updated)

    monkeypatch.setattr(AccountStore, "mutate", committed)
    answers(monkeypatch, "3", "yes")
    assert cli.main(["accounts", "key", "set", item.id]) == 2
    (updated,) = AccountStore().load()
    assert updated.credential_ref != old
    assert credentials.get(updated.credential_ref) == SECRET
    assert credentials.get(old) == "synthetic-old"
    output = capsys.readouterr()
    assert "Config saved" in output.err and "durability" in output.err
    assert "no config change" not in output.err.lower()
    assert SECRET not in output.out + output.err


def test_getpass_echo_fallback_is_refused(monkeypatch, credentials):
    def fallback(prompt):
        import warnings

        warnings.warn("synthetic fallback", getpass.GetPassWarning)
        pytest.fail("Must not read echoed input")

    item = account()
    seed(item)
    monkeypatch.setattr(cli.getpass, "getpass", fallback)
    answers(monkeypatch, "3")
    assert cli.main(["accounts", "key", "set", item.id]) == 2
    assert AccountStore().load() == (item,)


@pytest.mark.parametrize("value", ["", "has spaces", "bad\r\nheader", "Cookie: sessionKey=bad"])
def test_invalid_secret_input_is_exit_two(monkeypatch, credentials, value):
    item = account()
    seed(item)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: value)
    answers(monkeypatch, "3")
    assert cli.main(["accounts", "key", "set", item.id]) == 2
    assert AccountStore().load() == (item,)
    assert credentials.values == {}


def test_invalid_console_cookie_is_rejected_before_discovery(monkeypatch, credentials):
    item = account(ProviderId.CLAUDE_PLATFORM)
    seed(item)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "value;another-cookie=bad")
    answers(monkeypatch, "2")
    assert cli.main(["accounts", "key", "set", item.id]) == 2
    assert AccountStore().load() == (item,)
    assert credentials.values == {}


def test_escape_in_secret_cancels_without_persistence(monkeypatch, credentials):
    item = account()
    seed(item)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "\x1b")
    answers(monkeypatch, "3")
    assert cli.main(["accounts", "key", "set", item.id]) == 0
    assert AccountStore().load() == (item,)
    assert credentials.values == {}


def test_module_entrypoint_uses_same_main(monkeypatch):
    import runpy

    calls = []
    monkeypatch.setattr(cli, "main", lambda: calls.append(True) or 3)
    with pytest.raises(SystemExit) as error:
        runpy.run_module("usage_tui", run_name="__main__")
    assert error.value.code == 3
    assert calls == [True]
