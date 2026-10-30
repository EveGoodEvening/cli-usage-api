"""CLI contracts with isolated HOME and synthetic credentials; no real keyring/network."""

from __future__ import annotations

import asyncio
import builtins
import getpass
import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from cli_usage_api import cli
from cli_usage_api.accounts import AccountFlowError
from cli_usage_api.domain import Account, CredentialKind, ProviderId
from cli_usage_api.providers.console import OrganizationChoice
from cli_usage_api.storage import (
    AccountStore,
    ConfigCommittedError,
    ConfigError,
    CredentialError,
    CredentialStore,
)

SECRET = "synthetic-cli-secret-never-display"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "config"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("GROK_HOME", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(home / "codex"))
    return home


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No CLI test may reach an upstream: discovery is always injected synthetically."""
    from cli_usage_api.transport import Transport

    async def refuse(self, *args, **kwargs):
        pytest.fail("CLI tests must not perform network requests")

    monkeypatch.setattr(Transport, "get_json", refuse)


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

    def secure_available(self):
        return True

    def session_present(self, ref):
        return isinstance(ref, str) and ref.startswith("session:") and ref in self.values


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

    def run_demo(app):
        async def exercise():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert "DEMO" in str(app.banner.content)
                await pilot.press("a")
                assert app.screen.readonly
                await pilot.press("ctrl+c")

        asyncio.run(exercise())

    monkeypatch.setattr(cli.UsageApp, "run", run_demo)
    assert cli.main(["--demo", "--scenario", scenario]) == 0


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
        ["add", "--provider", "openai-platform"],
        ["key", "set", "local-id"],
        ["remove", "local-id"],
        ["migrate-chatgpt-to-codex"],
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
    assert cli.main(["accounts", "add", "--provider", "codex-subscription"]) == 0
    (item,) = AccountStore().load()
    assert item.provider == ProviderId.CODEX_SUBSCRIPTION
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


@pytest.mark.parametrize(
    "provider", [name for name in cli.PROVIDER_NAMES if name != "openai-platform"]
)
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
    # Claude manual bearer; decline optional discovery, then the final replacement.
    answers(monkeypatch, "3", "no", "no")
    assert cli.main(["accounts", "key", "set", item.id]) == 0
    assert AccountStore().load() == (item,)
    assert credentials.values == {} and credentials.persisted == []


def test_secret_set_replace_delete_never_reveals(monkeypatch, credentials, capsys):
    item = account()
    seed(item)
    for _ in range(2):
        answers(monkeypatch, "3", "no", "yes")
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


CREDITS_ORG = "0f1e2d3c-4b5a-4987-8a6b-5c4d3e2f1a0b"
OPENAI_ORG = "org-Synthetic0rg1234"
OPENAI_SESSION = "sess-SyntheticDashboardSession0123456789"


def subscription_discovery(monkeypatch, result, observed=None):
    """Inject a synthetic Claude subscription profile discovery; nothing else is reachable."""

    async def discover(credential):
        if observed is not None:
            observed.append(credential)
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(
        cli,
        "build_providers",
        lambda transport, resolver: {
            ProviderId.CLAUDE_SUBSCRIPTION: SimpleNamespace(discover_organizations=discover)
        },
    )


def test_claude_credits_organization_is_explicitly_selected(monkeypatch, credentials, capsys):
    item = account()
    seed(item)
    observed = []
    subscription_discovery(
        monkeypatch, (OrganizationChoice(CREDITS_ORG, "Synthetic team"),), observed
    )
    answers(monkeypatch, "3", "yes", "1", "yes")
    assert cli.main(["accounts", "key", "set", item.id]) == 0
    (updated,) = AccountStore().load()
    assert updated.organization_id == CREDITS_ORG
    assert updated.credential_kind == CredentialKind.MANUAL_BEARER
    # The profile read is unscoped: no saved organization travels with discovery.
    (credential,) = observed
    assert credential.provider == ProviderId.CLAUDE_SUBSCRIPTION
    assert credential.organization_id is None and credential.secret == SECRET
    output = capsys.readouterr().out
    assert "Optional prepaid credits" in output and "Synthetic team" in output
    assert "No organization — skip the prepaid credits read" in output
    assert SECRET not in output
    # The temporary discovery session secret is gone; only the keyring copy remains.
    assert list(credentials.values) == [updated.credential_ref]


def test_claude_credits_single_result_is_not_autoselected(monkeypatch, credentials):
    item = account()
    seed(item)
    subscription_discovery(monkeypatch, (OrganizationChoice(CREDITS_ORG, "Synthetic"),))
    answers(monkeypatch, "3", "yes", "")
    assert cli.main(["accounts", "key", "set", item.id]) == 2
    assert AccountStore().load() == (item,)
    assert credentials.values == {} and not credentials.persisted


def test_claude_credits_no_organization_choice_skips_credits(monkeypatch, credentials):
    item = account()
    seed(item)
    subscription_discovery(monkeypatch, (OrganizationChoice(CREDITS_ORG, "Synthetic"),))
    answers(monkeypatch, "3", "yes", "2", "yes")
    assert cli.main(["accounts", "key", "set", item.id]) == 0
    (updated,) = AccountStore().load()
    assert updated.organization_id is None
    assert updated.credential_kind == CredentialKind.MANUAL_BEARER


def test_claude_credits_declined_discovery_makes_no_request(monkeypatch, credentials, capsys):
    item = account()
    seed(item)
    subscription_discovery(monkeypatch, AssertionError("discovery must not run"))
    answers(monkeypatch, "3", "no", "yes")
    assert cli.main(["accounts", "key", "set", item.id]) == 0
    (updated,) = AccountStore().load()
    assert updated.organization_id is None
    assert "only the usage request" in capsys.readouterr().out


@pytest.mark.parametrize(("keep", "expected"), [("yes", CREDITS_ORG), ("no", None)])
def test_claude_saved_credits_organization_is_kept_only_explicitly(
    monkeypatch, credentials, keep, expected
):
    # Same kind and reference, no new secret: the login is unchanged.
    item = account(
        organization_id=CREDITS_ORG,
        credential_kind=CredentialKind.CLAUDE_CODE_FILE,
        credential_ref="default",
    )
    seed(item)
    subscription_discovery(monkeypatch, AssertionError("discovery must not run"))
    monkeypatch.setattr(cli.CredentialResolver, "resolve", lambda self, draft: object())
    answers(monkeypatch, "2", "default", "no", keep, "yes")
    assert cli.main(["accounts", "key", "set", item.id]) == 0
    (updated,) = AccountStore().load()
    assert updated.organization_id == expected
    assert updated.credential_kind == CredentialKind.CLAUDE_CODE_FILE


@pytest.mark.parametrize(
    ("original", "kind_answer", "reference"),
    [
        # A newly entered bearer is always a new login.
        (
            {
                "credential_kind": CredentialKind.MANUAL_BEARER,
                "credential_ref": "KEYRING",
            },
            "3",
            None,
        ),
        # File -> manual bearer: the kind changed.
        (
            {"credential_kind": CredentialKind.CLAUDE_CODE_FILE, "credential_ref": "default"},
            "3",
            None,
        ),
        # Same file kind, different login file.
        (
            {"credential_kind": CredentialKind.CLAUDE_CODE_FILE, "credential_ref": "default"},
            "2",
            "/srv/other/.credentials.json",
        ),
    ],
)
def test_claude_credits_organization_is_not_kept_across_a_login_change(
    monkeypatch, credentials, capsys, original, kind_answer, reference
):
    item = account(organization_id=CREDITS_ORG, **original)
    if item.credential_ref == "KEYRING":
        item = replace(item, credential_ref=f"keyring:{item.id}:{uuid4()}")
    seed(item)
    subscription_discovery(monkeypatch, AssertionError("discovery must not run"))
    monkeypatch.setattr(cli.CredentialResolver, "resolve", lambda self, draft: object())
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return next(iterator)

    iterator = iter([kind_answer, *([reference] if reference else []), "no", "yes", "yes", "yes"])
    monkeypatch.setattr(builtins, "input", ask)
    assert cli.main(["accounts", "key", "set", item.id]) == 0
    (updated,) = AccountStore().load()
    assert updated.organization_id is None
    assert not any("Keep the saved prepaid-credits organization" in p for p in prompts)
    assert "The login changed" in capsys.readouterr().out


def test_claude_edit_without_source_change_keeps_credits_organization(monkeypatch, credentials):
    item = account(organization_id=CREDITS_ORG)
    seed(item)
    subscription_discovery(monkeypatch, AssertionError("discovery must not run"))
    answers(monkeypatch, "Renamed", "", "yes", "no", "yes")
    assert cli.main(["accounts", "edit", item.id]) == 0
    (updated,) = AccountStore().load()
    assert updated.organization_id == CREDITS_ORG and updated.label == "Renamed"


def test_claude_credits_empty_profile_selects_nothing(monkeypatch, credentials, capsys):
    item = account()
    seed(item)
    subscription_discovery(monkeypatch, ())
    answers(monkeypatch, "3", "yes", "yes")
    assert cli.main(["accounts", "key", "set", item.id]) == 0
    (updated,) = AccountStore().load()
    assert updated.organization_id is None
    assert "reported no organization" in capsys.readouterr().out


def test_claude_credits_discovery_failure_is_curated(monkeypatch, credentials, capsys):
    from cli_usage_api.domain import FetchState
    from cli_usage_api.transport import TransportError

    item = account()
    seed(item)
    subscription_discovery(
        monkeypatch, TransportError(FetchState.AUTH_REQUIRED, "credential_expired")
    )
    answers(monkeypatch, "3", "yes")
    assert cli.main(["accounts", "key", "set", item.id]) == 3
    assert AccountStore().load() == (item,)
    assert credentials.values == {} and not credentials.persisted
    captured = capsys.readouterr()
    assert "Organization discovery failed" in captured.err
    assert SECRET not in captured.out + captured.err


def test_claude_api_key_offers_no_credits_discovery(monkeypatch, credentials, capsys):
    item = account()
    seed(item)
    subscription_discovery(monkeypatch, AssertionError("discovery must not run"))
    answers(monkeypatch, "4", "yes")
    assert cli.main(["accounts", "key", "set", item.id]) == 0
    assert "Optional prepaid credits" not in capsys.readouterr().out


def test_live_factory_exposes_per_provider_discovery():
    factory = cli.LiveFactory(CredentialStore())
    discovery = factory.organization_discovery
    assert set(discovery) == {ProviderId.CLAUDE_PLATFORM, ProviderId.CLAUDE_SUBSCRIPTION}
    assert discovery[ProviderId.CLAUDE_PLATFORM] == factory.console_discovery
    assert (
        discovery[ProviderId.CLAUDE_SUBSCRIPTION]
        == factory.providers[ProviderId.CLAUDE_SUBSCRIPTION].discover_organizations
    )
    asyncio.run(factory.aclose())


def warned_getpass(monkeypatch, capsys, value=OPENAI_SESSION):
    """A hidden prompt that records whether the warning was already printed."""
    seen = []

    def prompt(text):
        seen.append(capsys.readouterr().out)
        return value

    monkeypatch.setattr(cli.getpass, "getpass", prompt)
    return seen


def test_openai_add_prints_warning_before_hidden_input(monkeypatch, credentials, capsys):
    seen = warned_getpass(monkeypatch, capsys)
    answers(monkeypatch, f"  {OPENAI_ORG}  ", "Fictional platform", "", "yes", "2", "yes")
    assert cli.main(["accounts", "add", "--provider", "openai-platform"]) == 0
    (item,) = AccountStore().load()
    assert item.provider == ProviderId.OPENAI_PLATFORM
    assert item.organization_id == OPENAI_ORG
    assert item.credential_kind == CredentialKind.OPENAI_PLATFORM_SESSION
    assert item.poll_interval_seconds == 300
    assert item.credential_ref in credentials.persisted
    assert credentials.get(item.credential_ref) == OPENAI_SESSION
    (before,) = seen
    assert "platform.openai.com dashboard session key" in before
    assert "full dashboard access" in before and "HAR file" in before
    assert "API keys (sk-...) do not work" in before
    assert "sessionKey value" not in before
    after = capsys.readouterr().out
    assert OPENAI_SESSION not in before + after
    assert OPENAI_SESSION not in AccountStore().path.read_text()


def test_openai_without_credential_still_requires_organization(monkeypatch, credentials):
    answers(monkeypatch, OPENAI_ORG, "Fictional", "300", "yes", "1", "yes")
    assert cli.main(["accounts", "add", "--provider", "openai-platform"]) == 0
    (item,) = AccountStore().load()
    assert item.organization_id == OPENAI_ORG and item.credential_kind is None


@pytest.mark.parametrize(
    "organization", ["", "org-short", "sk-proj-abcdefghijkl", "org_abcdefghij"]
)
def test_openai_invalid_organization_is_refused_before_secret(
    monkeypatch, credentials, capsys, organization
):
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: pytest.fail("No secret read"))
    answers(monkeypatch, organization)
    assert cli.main(["accounts", "add", "--provider", "openai-platform"]) == 2
    assert AccountStore().load() == ()
    assert "org- followed by 8-64" in capsys.readouterr().err


@pytest.mark.parametrize(
    "value",
    [
        f"Bearer {OPENAI_SESSION}",
        f"Cookie: session={OPENAI_SESSION}",
        f'{{"sensitive_id": "{OPENAI_SESSION}"}}',
        "sess-short",
        "sess-has internal-space-0123456789",
        OPENAI_SESSION + "\r\nX-Injected: 1",
    ],
)
def test_openai_invalid_session_input_is_rejected(monkeypatch, credentials, capsys, value):
    item = account(ProviderId.OPENAI_PLATFORM, organization_id=OPENAI_ORG)
    seed(item)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: value)
    answers(monkeypatch, "2", "")
    assert cli.main(["accounts", "key", "set", item.id]) == 2
    assert AccountStore().load() == (item,)
    assert credentials.values == {}
    captured = capsys.readouterr()
    assert OPENAI_SESSION not in captured.out + captured.err


def test_openai_unavailable_keyring_fails_before_secret_prompt(monkeypatch, capsys):
    item = account(ProviderId.OPENAI_PLATFORM, organization_id=OPENAI_ORG)
    seed(item)
    store = CredentialStore()
    monkeypatch.setattr(cli, "CredentialStore", lambda: store)
    monkeypatch.setattr(
        store, "_secure_backend", lambda: (_ for _ in ()).throw(CredentialError(SECRET))
    )
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: pytest.fail("No secret read"))
    answers(monkeypatch, "2", "")
    assert cli.main(["accounts", "key", "set", item.id]) == 3
    assert AccountStore().load() == (item,)
    captured = capsys.readouterr()
    assert "TUI" in captured.err and "session-only" in captured.err
    assert SECRET not in captured.out + captured.err


def test_openai_key_set_can_change_organization(monkeypatch, credentials, capsys):
    item = account(ProviderId.OPENAI_PLATFORM, organization_id=OPENAI_ORG)
    seed(item)
    warned_getpass(monkeypatch, capsys)
    answers(monkeypatch, "2", "org-AnotherSynthetic9", "yes")
    assert cli.main(["accounts", "key", "set", item.id]) == 0
    (updated,) = AccountStore().load()
    assert updated.organization_id == "org-AnotherSynthetic9"
    assert credentials.get(updated.credential_ref) == OPENAI_SESSION


def test_openai_key_delete_keeps_required_organization(monkeypatch, credentials):
    account_id = str(uuid4())
    ref = credentials.put(account_id, OPENAI_SESSION, persist=True)
    item = Account(
        id=account_id,
        provider=ProviderId.OPENAI_PLATFORM,
        label="Synthetic",
        organization_id=OPENAI_ORG,
        credential_kind=CredentialKind.OPENAI_PLATFORM_SESSION,
        credential_ref=ref,
    )
    seed(item)
    answers(monkeypatch, "yes")
    assert cli.main(["accounts", "key", "delete", item.id]) == 0
    (cleared,) = AccountStore().load()
    assert cleared.credential_kind is None and cleared.credential_ref is None
    assert cleared.organization_id == OPENAI_ORG
    assert ref not in credentials.values


def test_openai_offers_only_its_session_kind(monkeypatch, credentials, capsys):
    item = account(ProviderId.OPENAI_PLATFORM, organization_id=OPENAI_ORG)
    seed(item)
    answers(monkeypatch, "3")
    assert cli.main(["accounts", "key", "set", item.id]) == 2
    output = capsys.readouterr().out
    assert "OpenAI Platform dashboard session key" in output
    for other in ("Manual bearer", "API key —", "Console session", "External"):
        assert other not in output


def test_grok_scope_is_explicit_and_external_file_survives(isolated_home, monkeypatch, credentials):
    # Custom references must name the login file itself (auth.json for Grok).
    (isolated_home / "grok-login").mkdir()
    path = isolated_home / "grok-login" / "auth.json"
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
    from cli_usage_api.storage import CredentialError

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
    answers(monkeypatch, "3", "no", "yes")
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
        runpy.run_module("cli_usage_api", run_name="__main__")
    assert error.value.code == 3
    assert calls == [True]


def legacy_config():
    other = account()
    AccountStore().save((other,))
    path = AccountStore().path
    records = []
    for kind in (CredentialKind.MANUAL_BEARER, CredentialKind.API_KEY):
        item = account()
        record = replace(
            item, credential_kind=kind, credential_ref=f"keyring:{item.id}:{uuid4()}"
        ).to_dict()
        record["provider"] = "chatgpt_subscription"
        records.append(record)
    path.write_text(json.dumps({"schema_version": 1, "accounts": [other.to_dict(), *records]}))
    return path, other, records


def forbid_credentials(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Migration must not construct or use a credential store")

    monkeypatch.setattr(cli, "CredentialStore", forbidden)


@pytest.mark.parametrize("reply", ["no", "\x1b", KeyboardInterrupt(), EOFError()])
def test_migration_decline_cancel_preserves_bytes(monkeypatch, reply):
    path, _, _ = legacy_config()
    before = path.read_bytes()
    forbid_credentials(monkeypatch)

    def respond(_prompt):
        if isinstance(reply, BaseException):
            raise reply
        return reply

    monkeypatch.setattr(builtins, "input", respond)
    assert cli.main(["accounts", "migrate-chatgpt-to-codex"]) == 0
    assert path.read_bytes() == before


@pytest.mark.parametrize("stream", ["stdin", "stdout"])
def test_migration_non_tty_preserves_bytes(monkeypatch, terminal_boundary, stream):
    path, _, _ = legacy_config()
    before = path.read_bytes()
    forbid_credentials(monkeypatch)
    monkeypatch.setattr(cli, "_tty", terminal_boundary)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: stream != "stdin")
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: stream != "stdout")
    assert cli.main(["accounts", "migrate-chatgpt-to-codex"]) == 2
    assert path.read_bytes() == before


def test_migration_affirms_whole_set_without_credentials(monkeypatch, capsys):
    _, other, records = legacy_config()
    forbid_credentials(monkeypatch)
    answers(monkeypatch, "yes")
    assert cli.main(["accounts", "migrate-chatgpt-to-codex"]) == 0
    current = AccountStore().load()
    assert current[0] == other
    assert {item.id for item in current[1:]} == {record["id"] for record in records}
    for item in current[1:]:
        assert item.provider == ProviderId.CODEX_SUBSCRIPTION and not item.enabled
        assert item.credential_kind is None and item.credential_ref is None
        assert item.organization_id is None and item.credential_selector is None
    output = capsys.readouterr().out
    assert "retained" in output and "disabled" in output and "detached" in output
    assert "keyring:" not in output
    assert cli.main(["accounts", "migrate-chatgpt-to-codex"]) == 0


def test_migration_changed_set_is_not_written(monkeypatch):
    path, _, _ = legacy_config()
    forbid_credentials(monkeypatch)
    changed = None

    def respond(_prompt):
        nonlocal changed
        data = json.loads(path.read_text())
        record = dict(data["accounts"][-1], id=str(uuid4()))
        record["credential_ref"] = f"keyring:{record['id']}:{uuid4()}"
        data["accounts"].append(record)
        path.write_text(json.dumps(data))
        changed = path.read_bytes()
        return "yes"

    monkeypatch.setattr(builtins, "input", respond)
    assert cli.main(["accounts", "migrate-chatgpt-to-codex"]) == 2
    assert path.read_bytes() == changed


def test_migration_committed_warning_is_truthful(monkeypatch, capsys):
    legacy_config()
    forbid_credentials(monkeypatch)
    migrate = AccountStore.migrate_legacy_chatgpt_to_codex

    def committed(self, **kwargs):
        raise ConfigCommittedError(migrate(self, **kwargs))

    monkeypatch.setattr(AccountStore, "migrate_legacy_chatgpt_to_codex", committed)
    answers(monkeypatch, "yes")
    assert cli.main(["accounts", "migrate-chatgpt-to-codex"]) == 2
    assert all(
        item.provider != ProviderId.CLAUDE_SUBSCRIPTION for item in AccountStore().load()[1:]
    )
    error = capsys.readouterr().err
    assert "Migration saved" in error and "durability" in error


def test_codex_key_set_uses_file_only(monkeypatch, credentials, tmp_path, capsys):
    root = tmp_path / "codex-private"
    root.mkdir(mode=0o700)
    path = root / "auth.json"
    path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {"access_token": "e30.e30.c2ln", "account_id": "synthetic-account"},
            }
        )
    )
    path.chmod(0o600)
    monkeypatch.setenv("CODEX_HOME", str(root))
    item = account(ProviderId.CODEX_SUBSCRIPTION, enabled=False)
    seed(item)
    answers(monkeypatch, "2", "", "yes")
    assert cli.main(["accounts", "key", "set", item.id]) == 0
    (saved,) = AccountStore().load()
    assert saved.credential_kind == CredentialKind.CODEX_AUTH_FILE
    assert saved.credential_ref == "default" and not saved.enabled
    assert not credentials.values and not credentials.deleted and not credentials.persisted
    output = capsys.readouterr().out
    assert "Manual bearer" not in output and "API key —" not in output
    assert "e30.e30.c2ln" not in output


def test_old_provider_spelling_is_rejected(capsys):
    assert cli.main(["accounts", "add", "--provider", "chatgpt-subscription"]) == 2
    assert "Invalid command" in capsys.readouterr().err


# --- usage api ------------------------------------------------------------------


class ServeCapture:
    """Replace binding/serving so CLI composition is observable without a socket."""

    def __init__(self, monkeypatch, *, bind_error=False):
        from cli_usage_api import api as api_server

        self.app = None
        self.bound = None
        self.closed_sockets = 0

        def bind(host, port):
            if bind_error:
                raise api_server.BindError
            self.bound = (host, port)
            return SimpleNamespace(close=lambda: None)

        def run(app, sock, services=()):
            self.app = app
            self.services = tuple(services)

        monkeypatch.setattr(api_server, "bind_socket", bind)
        monkeypatch.setattr(api_server, "run", run)


def make_api_token():
    from cli_usage_api.storage import ApiTokenStore

    return ApiTokenStore().create("cli-test")[0]


def forbid_live(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Demo API must not construct or read live services")

    for name in (
        "AccountStore",
        "CredentialStore",
        "CredentialResolver",
        "Transport",
        "LiveFactory",
    ):
        monkeypatch.setattr(cli, name, forbidden)


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*.example.com",
        "https://app.example.com/",
        "https://app.example.com/path",
        "ftp://app.example.com",
        "app.example.com",
        "null",
    ],
)
def test_api_serve_rejects_invalid_origins(monkeypatch, capsys, origin):
    ServeCapture(monkeypatch)
    make_api_token()
    assert cli.main(["api", "serve", "--allow-origin", origin]) == 2
    err = capsys.readouterr().err
    assert "--allow-origin must be an exact" in err
    # One fixed message regardless of input; the rejected value is not echoed back.
    assert len(err.strip().splitlines()) == 1
    assert "/path" not in err and "ftp" not in err


@pytest.mark.parametrize("port", ["0", "65536", "-1", "abc", "80.5", "٣"])
def test_api_serve_rejects_invalid_ports(monkeypatch, capsys, port):
    ServeCapture(monkeypatch)
    assert cli.main(["api", "serve", "--demo", "--port", port]) == 2
    assert "--port must be an integer from 1 to 65535" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["api", "serve", "--scenario", "errors"], "--scenario requires --demo"),
        (["api", "serve", "--demo", "--debug-log", "/tmp/x"], "cannot be combined with --demo"),
        (["api", "serve", "--debug-provider", "grok-subscription"], "requires --debug-log"),
        (["--demo", "api", "serve"], "--demo cannot be combined"),
        (["--debug-log", "/tmp/x", "api", "serve"], "only to the live dashboard"),
        (["api", "serve", "--host", "bad host"], "--host must be"),
    ],
)
def test_api_serve_argument_combinations(monkeypatch, capsys, args, message):
    ServeCapture(monkeypatch)
    assert cli.main(args) == 2
    assert message in capsys.readouterr().err


def test_api_serve_demo_loopback_without_tokens_is_unauthenticated(monkeypatch, capsys):
    capture = ServeCapture(monkeypatch)
    forbid_live(monkeypatch)
    assert cli.main(["api", "serve", "--demo", "--scenario", "errors", "--port", "9999"]) == 0
    assert capture.bound == ("127.0.0.1", 9999)
    assert capture.app.auth_mode == "none"
    assert capture.app.hub.mode == "demo"
    out = capsys.readouterr().out
    assert "without authentication" in out and "loopback" in out


def test_api_serve_loopback_demo_requires_token_once_one_is_created(monkeypatch, capsys):
    import time

    import httpx

    capture = ServeCapture(monkeypatch)
    forbid_live(monkeypatch)
    assert cli.main(["api", "serve", "--demo"]) == 0
    app = capture.app
    assert cli.main(["api", "token", "create", "--label", "later"]) == 0
    token = next(line for line in capsys.readouterr().out.splitlines() if line.startswith("usk_"))

    async def probe():
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as client:
            # The running server rechecks the token file at most once per second.
            deadline = time.monotonic() + 5
            while True:
                anonymous = await client.get("/api/v1/session")
                if anonymous.status_code == 401 or time.monotonic() > deadline:
                    break
                await asyncio.sleep(0.1)
            session = await client.get(
                "/api/v1/session", headers={"Authorization": f"Bearer {token}"}
            )
            return anonymous, session

    anonymous, session = asyncio.run(probe())
    assert anonymous.status_code == 401
    assert session.status_code == 200
    assert session.json()["auth"] == "token"


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.2"])
def test_api_serve_demo_non_loopback_requires_tokens(monkeypatch, capsys, host):
    capture = ServeCapture(monkeypatch)
    forbid_live(monkeypatch)
    assert cli.main(["api", "serve", "--demo", "--host", host]) == 2
    assert "No API tokens configured" in capsys.readouterr().err
    assert capture.bound is None


def test_api_serve_demo_with_tokens_requires_them(monkeypatch, capsys):
    capture = ServeCapture(monkeypatch)
    make_api_token()
    forbid_live(monkeypatch)
    assert cli.main(["api", "serve", "--demo", "--host", "0.0.0.0"]) == 0
    assert capture.app.verifier is not None and capture.app.verifier.count == 1
    out = capsys.readouterr().out
    assert "browsers on other origins are blocked by CORS" in out


def test_api_serve_live_requires_tokens_even_on_loopback(monkeypatch, capsys):
    capture = ServeCapture(monkeypatch)

    def forbidden(*args, **kwargs):
        pytest.fail("No live services before the token check")

    monkeypatch.setattr(cli, "LiveFactory", forbidden)
    assert cli.main(["api", "serve"]) == 2
    assert "No API tokens configured" in capsys.readouterr().err
    assert capture.bound is None


def test_api_serve_live_composes_factory_and_origins(monkeypatch, capsys):
    capture = ServeCapture(monkeypatch)
    make_api_token()
    item = account(enabled=False)
    seed(item)
    built = []

    class FakeFactory:
        def __init__(self, credentials):
            built.append(credentials)
            self.resolver = SimpleNamespace(store=credentials)
            self.console_discovery = None
            self.organization_discovery = None

        async def aclose(self):
            pass

    monkeypatch.setattr(cli, "LiveFactory", FakeFactory)
    assert (
        cli.main(
            [
                "api",
                "serve",
                "--host",
                "0.0.0.0",
                "--port",
                "8080",
                "--trust-proxy",
                "--allow-origin",
                "HTTPS://Usage.Example.com:443",
                "--allow-origin",
                "https://usage.example.com",
                "--allow-origin",
                "http://localhost:5173",
            ]
        )
        == 0
    )
    assert len(built) == 1
    app = capture.app
    assert app.hub.mode == "live"
    assert app.hub.accounts == (item,)
    assert app.trust_proxy is True
    assert app.allowed_origins == {"https://usage.example.com", "http://localhost:5173"}
    # Writes are on by default and share the resolver's credential store.
    operations = app.operations
    assert operations is not None and operations.host is app.hub
    assert operations.credentials is built[0]
    assert operations.resolver.store is built[0]
    out = capsys.readouterr().out
    assert (
        "1 account(s) loaded. Account changes over the API are ENABLED for every API token "
        "(use --read-only to disable)." in out
    )
    assert "Credentials are resolved by the server process only." in out
    assert "restart serve after changing accounts" not in out


def test_api_serve_read_only_has_no_operations(monkeypatch, capsys):
    capture = ServeCapture(monkeypatch)
    make_api_token()
    assert cli.main(["api", "serve", "--read-only"]) == 0
    assert capture.app.operations is None
    assert capture.app.hub.mode == "live"
    out = capsys.readouterr().out
    assert "0 account(s) loaded. API is read-only (--read-only)." in out
    assert "ENABLED" not in out
    assert "Add accounts with usage accounts add --provider ..., then restart serve." in out


def test_api_serve_zero_accounts_points_to_the_web(monkeypatch, capsys):
    capture = ServeCapture(monkeypatch)
    make_api_token()
    assert cli.main(["api", "serve"]) == 0
    assert capture.app.operations is not None
    out = capsys.readouterr().out
    assert "No accounts configured. Add accounts in the web UI or with usage accounts add" in out


def test_api_serve_demo_is_always_read_only(monkeypatch):
    capture = ServeCapture(monkeypatch)
    forbid_live(monkeypatch)
    monkeypatch.setattr(
        cli, "AccountOperations", lambda **kwargs: pytest.fail("demo must not build operations")
    )
    assert cli.main(["api", "serve", "--demo"]) == 0
    assert capture.app.operations is None


def test_real_live_factory_shares_credentials_with_operations(monkeypatch):
    capture = ServeCapture(monkeypatch)
    make_api_token()
    assert cli.main(["api", "serve"]) == 0
    operations = capture.app.operations
    assert operations.resolver._store is operations.credentials
    assert operations.service.credentials is operations.credentials
    # The web host receives every explicit discovery, not only the Console's.
    assert set(operations.console_discovery) == {
        ProviderId.CLAUDE_PLATFORM,
        ProviderId.CLAUDE_SUBSCRIPTION,
    }


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--read-only"], "require --api"),
        (["--read-only", "accounts", "list"], "apply only to the dashboard"),
    ],
)
def test_dashboard_read_only_requires_api(monkeypatch, capsys, args, message):
    monkeypatch.setattr(cli.UsageApp, "run", lambda app: pytest.fail("TUI must not start"))
    assert cli.main(args) == 2
    assert message in capsys.readouterr().err


def test_read_only_parses_on_both_entry_points():
    parser = cli._parser()
    assert parser.parse_args(["api", "serve", "--read-only"]).serve_read_only is True
    assert parser.parse_args(["api", "serve"]).serve_read_only is False
    assert parser.parse_args(["--api", "--read-only"]).dashboard_read_only is True
    assert parser.parse_args([]).dashboard_read_only is False


def test_api_serve_bind_failure_is_curated(monkeypatch, capsys):
    ServeCapture(monkeypatch, bind_error=True)
    assert cli.main(["api", "serve", "--demo"]) == 3
    assert "Cannot listen" in capsys.readouterr().err


def test_api_serve_real_source_startup_failure_is_curated(monkeypatch, capsys):
    """Real uvicorn on a real 127.0.0.1:0 socket; only the demo source is made to fail."""
    from cli_usage_api import api as api_server

    real_bind = api_server.bind_socket
    bound = []

    def bind_ephemeral(host, port):
        sock = real_bind(host, 0)
        bound.append(sock)
        return sock

    class FailingDemoSource(api_server.DemoSource):
        async def start(self):
            raise RuntimeError("synthetic secret startup detail")

    monkeypatch.setattr(api_server, "bind_socket", bind_ephemeral)
    monkeypatch.setattr(api_server, "DemoSource", FailingDemoSource)
    assert cli.main(["api", "serve", "--demo"]) == 3
    captured = capsys.readouterr()
    assert "API server failed to start its usage source." in captured.err
    assert "synthetic secret startup detail" not in captured.out + captured.err
    assert "usage api stopped." not in captured.out
    assert bound and bound[0].fileno() == -1


def test_api_serve_real_socket_bind_conflict(monkeypatch, capsys):
    import socket

    from cli_usage_api import api as api_server

    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    try:
        port = holder.getsockname()[1]
        with pytest.raises(api_server.AddressInUseError):
            api_server.bind_socket("127.0.0.1", port)
        sock = api_server.bind_socket("127.0.0.1", 0)
        sock.close()
        # The CLI reports EADDRINUSE distinctly from other bind failures.
        assert cli.main(["api", "serve", "--demo", "--port", str(port)]) == 3
        err = capsys.readouterr().err
        assert "already in use" in err and "--port" in err
    finally:
        holder.close()


def test_api_bind_localhost_is_reachable_over_ipv4():
    import socket

    from cli_usage_api import api as api_server

    sock = api_server.bind_socket("localhost", 0)
    try:
        assert sock.family == socket.AF_INET
        host, port = sock.getsockname()
        assert host == "127.0.0.1"
        sock.setblocking(True)
        with socket.create_connection(("127.0.0.1", port), timeout=5):
            peer, _ = sock.accept()
            peer.close()
    finally:
        sock.close()


def test_api_serve_non_local_host_bind_failure_message(monkeypatch, capsys):
    make_api_token()
    # TEST-NET-3 is never assigned to this host, so bind fails with EADDRNOTAVAIL.
    assert cli.main(["api", "serve", "--demo", "--host", "203.0.113.1", "--port", "8787"]) == 3
    err = capsys.readouterr().err
    assert "Cannot listen" in err and "local address" in err and "already in use" not in err


def test_api_token_create_refuses_without_tty(monkeypatch, capsys, terminal_boundary):
    from cli_usage_api.storage import ApiTokenStore

    monkeypatch.setattr(cli, "_tty", terminal_boundary)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    assert cli.main(["api", "token", "create"]) == 2
    assert "requires a TTY" in capsys.readouterr().err
    assert ApiTokenStore().load() == ()


def test_api_token_lifecycle(monkeypatch, capsys):
    from cli_usage_api.storage import ApiTokenStore, api_token_digest

    assert cli.main(["api", "token", "list"]) == 0
    assert "No API tokens" in capsys.readouterr().out
    assert cli.main(["api", "token", "create", "--label", "laptop"]) == 0
    out = capsys.readouterr().out
    token = next(line for line in out.splitlines() if line.startswith("usk_"))
    assert out.count(token) == 1
    assert "shown only once" in out
    assert (
        "This token can add, edit and remove accounts unless the server runs with --read-only."
        in out
    )
    (record,) = ApiTokenStore().load()
    assert record.label == "laptop"
    assert record.sha256 == api_token_digest(token)
    assert token not in ApiTokenStore().path.read_text()
    assert cli.main(["api", "token", "list"]) == 0
    listing = capsys.readouterr().out
    assert record.id in listing and "laptop" in listing
    assert record.sha256 not in listing and token not in listing
    assert cli.main(["api", "token", "revoke", "f" * 32]) == 2
    assert "API token not found" in capsys.readouterr().err
    answers(monkeypatch, "n")
    assert cli.main(["api", "token", "revoke", record.id]) == 0
    assert len(ApiTokenStore().load()) == 1
    answers(monkeypatch, "yes")
    assert cli.main(["api", "token", "revoke", record.id]) == 0
    assert ApiTokenStore().load() == ()
    assert "revoked" in capsys.readouterr().out


def test_api_token_limit_has_curated_message(monkeypatch, capsys):
    from cli_usage_api.storage import MAX_API_TOKENS, ApiTokenStore

    store = ApiTokenStore()
    for index in range(MAX_API_TOKENS):
        store.create(f"t{index}")
    assert cli.main(["api", "token", "create", "--label", "one-too-many"]) == 2
    captured = capsys.readouterr()
    assert "revoke unused tokens" in captured.err.casefold()
    assert "usage api token revoke" in captured.err
    assert "Cannot read/write config" not in captured.err
    assert "usk_" not in captured.out + captured.err
    assert len(ApiTokenStore().load()) == MAX_API_TOKENS


def test_api_token_revoke_requires_tty(monkeypatch, capsys, terminal_boundary):
    from cli_usage_api.storage import ApiTokenStore

    make_api_token()
    monkeypatch.setattr(cli, "_tty", terminal_boundary)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    (record,) = ApiTokenStore().load()
    assert cli.main(["api", "token", "revoke", record.id]) == 2
    assert len(ApiTokenStore().load()) == 1


def test_api_token_list_does_not_require_tty(monkeypatch, capsys, terminal_boundary):
    make_api_token()
    monkeypatch.setattr(cli, "_tty", terminal_boundary)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    assert cli.main(["api", "token", "list"]) == 0
    assert "cli-test" in capsys.readouterr().out


def test_api_unknown_arguments_are_not_echoed(capsys):
    assert cli.main(["api", "serve", "--token", "usk_pasted_secret_value"]) == 2
    captured = capsys.readouterr()
    assert "usk_pasted_secret_value" not in captured.out + captured.err


@pytest.mark.parametrize(
    ("kind_answer", "provider", "reference", "basename"),
    [
        ("2", ProviderId.CODEX_SUBSCRIPTION, "/srv/codex/other.json", "auth.json"),
        ("2", ProviderId.CODEX_SUBSCRIPTION, "/srv/../srv/codex/auth.json", "auth.json"),
        ("2", ProviderId.CLAUDE_SUBSCRIPTION, "/srv/claude/auth.json", ".credentials.json"),
        ("2", ProviderId.GROK_SUBSCRIPTION, "/proc/self/root/auth.json", "auth.json"),
        ("2", ProviderId.GROK_SUBSCRIPTION, "relative/auth.json", "auth.json"),
    ],
)
def test_custom_reference_must_name_the_login_file(
    monkeypatch, credentials, capsys, kind_answer, provider, reference, basename
):
    item = account(provider)
    seed(item)
    answers(monkeypatch, kind_answer, reference)
    assert cli.main(["accounts", "key", "set", item.id]) == 2
    assert AccountStore().load() == (item,)
    assert capsys.readouterr().err.strip() == f"Choose default or an absolute path to {basename}."


@pytest.mark.parametrize(
    ("code", "context", "exit_code", "hint"),
    [
        ("conflict", None, 2, False),
        ("config_unavailable", ConfigError("x"), 2, False),
        ("committed_uncertain", ConfigCommittedError(()), 2, False),
        ("secure_store_unavailable", CredentialError("x"), 3, True),
        ("cleanup_failed", RuntimeError("x"), 3, True),
        ("credential_cleanup_failed", RuntimeError("x"), 3, True),
        ("save_failed", ConfigError("x"), 3, False),
        ("too_many_accounts", None, 3, False),
        ("invalid_reference", None, 3, False),
        # Unclassified errors keep the original context-based mapping.
        ("failed", None, 3, False),
        ("failed", ConfigError("x"), 2, False),
        ("failed", CredentialError("x"), 3, True),
    ],
)
def test_account_flow_exit_codes_follow_error_code(
    monkeypatch, capsys, code, context, exit_code, hint
):
    def fail(args):
        if context is None:
            raise AccountFlowError("Curated message.", code=code)
        try:
            raise context
        except Exception:  # noqa: BLE001 - Build the same context as AccountService.
            raise AccountFlowError("Curated message.", code=code) from None

    monkeypatch.setattr(cli, "_accounts", fail)
    assert cli.main(["accounts", "list"]) == exit_code
    err = capsys.readouterr().err
    assert err.startswith("Curated message.\n")
    assert ("encrypted OS-keyring persistence" in err) == hint
