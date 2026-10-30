"""AccountOperations: curated HTTP account writes, prepare records, locking and throttles.

Synthetic login files in private temp dirs, an in-memory host and fake discovery;
no network and no real keyring (discovery of the real backend fails every test).
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from cli_usage_api import storage
from cli_usage_api.credentials import CredentialResolver
from cli_usage_api.domain import Account, CredentialKind, ProviderId
from cli_usage_api.operations import AccountOperations, OperationError
from cli_usage_api.providers.console import OrganizationChoice
from cli_usage_api.storage import AccountStore, ConfigCommittedError, CredentialStore

SECRET = "sk-ant-sid01-synthetic-session-never-echo"
BEARER = "synthetic-bearer-never-echo"
ORG = "11111111-aaaa-4bbb-8ccc-222222222222"
ORG2 = "33333333-aaaa-4bbb-8ccc-444444444444"
MODERN = "https://auth.x.ai::user-secretish-1"
MODERN2 = "https://auth.x.ai::user-secretish-2"
LEGACY = "https://accounts.x.ai/sign-in"


class Clock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


class Host:
    """The AccountHost protocol, recording every notification."""

    def __init__(self, accounts=()) -> None:
        self.accounts = tuple(accounts)
        self.account_lock = asyncio.Lock()
        self.calls: list[tuple[tuple[Account, ...], object]] = []
        self.reconnects: list[str] = []
        self.fail = False

    async def accounts_changed(self, accounts, *, invalidate=None):
        self.calls.append((tuple(accounts), invalidate))
        self.accounts = tuple(accounts)
        if self.fail:
            raise RuntimeError("synthetic host failure")

    async def reconnect(self, account_id):
        self.reconnects.append(account_id)


class FakeEncrypted:
    def __init__(self) -> None:
        self.values = {}

    def set_password(self, service, username, password):
        self.values[service, username] = password

    def get_password(self, service, username):
        return self.values.get((service, username))

    def delete_password(self, service, username):
        del self.values[service, username]


WORK = (OrganizationChoice(ORG, "Work org"),)


class Discovery:
    def __init__(self, choices=WORK) -> None:
        self.choices = tuple(choices)
        self.seen = []
        self.error: Exception | None = None
        self.delay = 0.0

    async def __call__(self, credential):
        self.seen.append(credential.secret)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.choices


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    def no_keyring():
        raise RuntimeError("no real keyring in tests")

    monkeypatch.setattr(storage.keyring, "get_keyring", no_keyring)
    dirs = {}
    for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "GROK_HOME"):
        directory = tmp_path / name
        directory.mkdir(mode=0o700)
        monkeypatch.setenv(name, str(directory))
        dirs[name] = directory
    config = tmp_path / "config"
    config.mkdir(mode=0o700)
    return SimpleNamespace(tmp=tmp_path, dirs=dirs, store=AccountStore(config / "accounts.json"))


def _jwt(exp: int) -> str:
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{part({'alg': 'none'})}.{part({'exp': exp})}.sig"


def write(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    return path


def codex_login(path, *, hours=6):
    exp = int((datetime.now(UTC) + timedelta(hours=hours)).timestamp())
    return write(path, {"tokens": {"access_token": _jwt(exp), "account_id": "acct-1"}})


def grok_login(path, scopes=(MODERN, LEGACY)):
    later = (datetime.now(UTC) + timedelta(hours=6)).isoformat()
    return write(path, {scope: {"key": "grok-key", "expires_at": later} for scope in scopes})


def make(env, accounts=(), *, discovery=None, credentials=None, clock=None):
    if accounts:
        env.store.save(tuple(accounts))
    credentials = credentials if credentials is not None else CredentialStore()
    host = Host(env.store.load())
    ops = AccountOperations(
        host=host,
        account_store=env.store,
        credential_store=credentials,
        resolver=CredentialResolver(credentials),
        console_discovery=discovery,
        monotonic=clock if clock is not None else Clock(),
    )
    return ops, host, credentials


def account(provider=ProviderId.CLAUDE_SUBSCRIPTION, label="Synthetic", **kwargs):
    return Account(id=str(uuid4()), provider=provider, label=label, **kwargs)


async def fails(coro, status, code):
    with pytest.raises(OperationError) as caught:
        await coro
    assert (caught.value.status, caught.value.code) == (status, code)
    # Curated: no chained context that could carry input or backend text.
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ or caught.value.__context__ is None
    return caught.value


def codex_body(reference="default", **extra):
    return {
        "provider": "codex_subscription",
        "label": "Codex",
        "source": {"credential_kind": "codex_auth_file", "reference": reference},
        **extra,
    }


# --- file kinds ---------------------------------------------------------------------


async def test_create_file_kinds_default_and_absolute(env):
    codex_login(env.dirs["CODEX_HOME"] / "auth.json")
    custom = codex_login(env.tmp / "custom" / "auth.json")
    ops, host, _ = make(env)
    created = await ops.create(codex_body())
    assert created.warning is None
    assert created.account.credential_ref == "default"
    assert created.accounts == env.store.load() == host.accounts
    assert host.calls[-1][1] == frozenset({created.account.id})
    other = await ops.create(codex_body(str(custom), poll_interval_seconds=120, enabled=False))
    assert other.account.credential_ref == str(custom)
    assert other.account.poll_interval_seconds == 120 and other.account.enabled is False
    assert [item.id for item in env.store.load()] == [created.account.id, other.account.id]


@pytest.mark.parametrize(
    "reference",
    [
        "relative/auth.json",
        "/tmp/creds.json",
        "/proc/1/auth.json",
        "/a/../auth.json",
        "//x/auth.json",
    ],
)
async def test_create_rejects_bad_references(env, reference):
    ops, host, _ = make(env)
    await fails(ops.create(codex_body(reference)), 422, "invalid_reference")
    assert host.calls == [] and env.store.load() == ()


async def test_unreadable_file_is_credential_unavailable_and_expired_commits(env):
    ops, host, _ = make(env)
    await fails(ops.create(codex_body()), 422, "credential_unavailable")
    # Wrong permissions collapse to the same code over HTTP.
    login = codex_login(env.dirs["CODEX_HOME"] / "auth.json")
    login.chmod(0o644)
    await fails(ops.create(codex_body()), 422, "credential_unavailable")
    assert env.store.load() == ()
    codex_login(login, hours=-1).chmod(0o600)
    result = await ops.create(codex_body())
    assert result.warning == "credential_expired"
    assert env.store.load() == (result.account,)
    assert len(host.calls) == 1


async def test_claude_file_create(env):
    later = int((datetime.now(UTC) + timedelta(hours=6)).timestamp() * 1000)
    write(
        env.dirs["CLAUDE_CONFIG_DIR"] / ".credentials.json",
        {"claudeAiOauth": {"accessToken": "tok", "expiresAt": later}},
    )
    ops, _, _ = make(env)
    result = await ops.create(
        {
            "provider": "claude_subscription",
            "label": "Claude",
            "source": {"credential_kind": "claude_code_file", "reference": "default"},
        }
    )
    assert result.account.credential_kind == CredentialKind.CLAUDE_CODE_FILE


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"provider": "codex_subscription", "label": "x"}, 400, "invalid_request"),
        ({**codex_body(), "extra": 1}, 400, "invalid_request"),
        ({**codex_body(), "label": "   "}, 422, "invalid_label"),
        ({**codex_body(), "label": "x" * 1025}, 422, "invalid_label"),
        ({**codex_body(), "label": "a\ud800"}, 400, "invalid_request"),
        ({**codex_body(), "poll_interval_seconds": 29}, 422, "invalid_poll_interval"),
        ({**codex_body(), "poll_interval_seconds": True}, 400, "invalid_request"),
        ({**codex_body(), "poll_interval_seconds": 60.0}, 400, "invalid_request"),
        ({**codex_body(), "enabled": 1}, 400, "invalid_request"),
        ({**codex_body(), "provider": "chatgpt"}, 400, "invalid_request"),
        (
            {
                **codex_body(),
                "source": {"credential_kind": "api_key", "secret": "x", "persist": False},
            },
            422,
            "invalid_kind",
        ),
        (
            {**codex_body(), "source": {"credential_kind": "codex_auth_file", "secret": "x"}},
            400,
            "invalid_request",
        ),
    ],
)
async def test_create_validation(env, body, status, code):
    ops, host, _ = make(env)
    await fails(ops.create(body), status, code)
    assert host.calls == []


async def test_no_credential_create_and_too_many(env, monkeypatch):
    ops, _, _ = make(env)
    result = await ops.create({"provider": "grok_subscription", "label": "none", "source": None})
    assert result.account.credential_kind is None
    monkeypatch.setattr("cli_usage_api.accounts.MAX_ACCOUNTS", 1)
    await fails(
        ops.create({"provider": "grok_subscription", "label": "two", "source": None}),
        422,
        "too_many_accounts",
    )


# --- secret kinds -------------------------------------------------------------------


async def test_manual_bearer_session_and_keep_and_detach(env):
    ops, host, credentials = make(env)
    body = {
        "provider": "claude_subscription",
        "label": "Bearer",
        "source": {"credential_kind": "manual_bearer", "secret": BEARER, "persist": False},
    }
    result = await ops.create(body)
    ref = result.account.credential_ref
    assert ref.startswith("session:") and credentials.get(ref) == BEARER
    assert BEARER not in repr(result) and BEARER not in json.dumps(ops.config_view(result.account))
    revision = ops.revision(result.account)
    # Same kind without a secret keeps the ref; a rename keeps scheduler state.
    kept = await ops.update(
        result.account.id,
        revision,
        {"label": "Renamed", "source": {"credential_kind": "manual_bearer"}},
    )
    assert kept.account.credential_ref == ref
    assert host.calls[-1][1] == frozenset({result.account.id})
    renamed = await ops.update(kept.account.id, ops.revision(kept.account), {"label": "Again"})
    assert host.calls[-1][1] == frozenset()
    assert renamed.account.label == "Again"
    # Detach deletes the owned secret.
    detached = await ops.update(renamed.account.id, ops.revision(renamed.account), {"source": None})
    assert detached.account.credential_kind is None and detached.account.credential_ref is None
    assert not credentials.session_present(ref)
    assert host.calls[-1][1] == frozenset({result.account.id})


@pytest.mark.parametrize(
    ("source", "code"),
    [
        ({"credential_kind": "manual_bearer", "secret": BEARER}, "persist_required"),
        ({"credential_kind": "manual_bearer", "persist": False}, "secret_required"),
        ({"credential_kind": "manual_bearer"}, "secret_required"),
        (
            {"credential_kind": "manual_bearer", "secret": "Bearer x y", "persist": False},
            "invalid_secret",
        ),
        (
            {"credential_kind": "manual_bearer", "secret": "x" * 16_385, "persist": False},
            "invalid_secret",
        ),
    ],
)
async def test_secret_rules(env, source, code):
    ops, _, _ = make(env)
    error = await fails(
        ops.create({"provider": "claude_subscription", "label": "x", "source": source}), 422, code
    )
    assert BEARER not in repr(error) and BEARER not in str(error)


async def test_persist_true_without_keyring_is_503_and_never_downgrades(env):
    ops, host, credentials = make(env)
    await ops.start()
    assert ops.secure_store_available is False
    body = {
        "provider": "claude_subscription",
        "label": "x",
        "source": {"credential_kind": "api_key", "secret": BEARER, "persist": True},
    }
    await fails(ops.create(body), 503, "secure_store_unavailable")
    assert env.store.load() == () and credentials._session == {} and host.calls == []


async def test_persist_true_with_keyring_stores_there(env, monkeypatch):
    monkeypatch.setattr(storage, "_SECURE_BACKEND_TYPES", (FakeEncrypted,))
    monkeypatch.setattr(storage.sys, "platform", "linux")
    backend = FakeEncrypted()
    ops, _, _ = make(env, credentials=CredentialStore(backend))
    await ops.start()
    assert ops.secure_store_available is True
    result = await ops.create(
        {
            "provider": "claude_subscription",
            "label": "x",
            "source": {"credential_kind": "api_key", "secret": BEARER, "persist": True},
        }
    )
    assert result.account.credential_ref.startswith("keyring:")
    assert list(backend.values.values()) == [BEARER]


# --- Grok prepare -------------------------------------------------------------------


def grok_prepare(**extra):
    return {"provider": "grok_subscription", "credential_kind": "grok_auth_file", **extra}


def grok_create(prepare_id, choice_id="c1"):
    return {
        "provider": "grok_subscription",
        "label": "Grok",
        "source": {
            "credential_kind": "grok_auth_file",
            "prepare_id": prepare_id,
            "choice_id": choice_id,
        },
    }


async def test_grok_prepare_is_opaque_and_explicit(env):
    login = grok_login(env.dirs["GROK_HOME"] / "auth.json")
    ops, host, _ = make(env)
    prepared = await ops.prepare(grok_prepare(reference="default"))
    assert prepared["kind"] == "grok_scope" and prepared["expires_in"] == 300
    assert prepared["choices"] == [
        {"id": "c1", "label": None, "legacy": False, "current": False},
        {"id": "c2", "label": None, "legacy": True, "current": False},
    ]
    text = json.dumps(prepared)
    assert "x.ai" not in text and "secretish" not in text and "grok-key" not in text
    await fails(
        ops.create(
            {
                "provider": "grok_subscription",
                "label": "Grok",
                "source": {"credential_kind": "grok_auth_file"},
            }
        ),
        422,
        "selection_required",
    )
    await fails(ops.create(grok_create("wrong-id")), 410, "prepare_expired")
    await fails(ops.create(grok_create(prepared["prepare_id"], "c9")), 422, "invalid_choice")
    # The chosen selector disappears from the file before commit.
    grok_login(login, scopes=(LEGACY,))
    await fails(ops.create(grok_create(prepared["prepare_id"])), 410, "prepare_expired")
    grok_login(login)
    result = await ops.create(grok_create(prepared["prepare_id"]))
    assert result.account.credential_selector == MODERN
    assert host.accounts == (result.account,)
    # Consumed: a record cannot be reused.
    await fails(ops.create(grok_create(prepared["prepare_id"])), 410, "prepare_expired")
    # Edit: current scope is a display hint only.
    again = await ops.prepare(
        {
            "account_id": result.account.id,
            "revision": ops.revision(result.account),
            "credential_kind": "grok_auth_file",
        }
    )
    assert [choice["current"] for choice in again["choices"]] == [True, False]


async def test_grok_prepare_unparseable_or_missing_is_credential_unavailable(env):
    ops, _, _ = make(env)
    await fails(ops.prepare(grok_prepare(reference="default")), 422, "credential_unavailable")
    path = env.dirs["GROK_HOME"] / "auth.json"
    for raw in ('{"a": 1, "a": 2}', "[" * 5000, "{}", '{"x": NaN}'):
        path.write_text(raw)
        path.chmod(0o600)
        await fails(ops.prepare(grok_prepare(reference="default")), 422, "credential_unavailable")
    assert ops._records == {}


async def test_prepare_ttl_and_eviction(env):
    grok_login(env.dirs["GROK_HOME"] / "auth.json")
    clock = Clock()
    ops, _, _ = make(env, clock=clock)
    first = await ops.prepare(grok_prepare(reference="default"))
    clock.value += 301
    await fails(ops.create(grok_create(first["prepare_id"])), 410, "prepare_expired")
    assert ops._records == {}
    ids = [(await ops.prepare(grok_prepare(reference="default")))["prepare_id"] for _ in range(5)]
    assert len(ops._records) == 4
    await fails(ops.create(grok_create(ids[0])), 410, "prepare_expired")
    assert (await ops.create(grok_create(ids[-1]))).account.credential_selector == MODERN


# --- Console prepare ----------------------------------------------------------------


def console_prepare(**extra):
    return {
        "provider": "claude_platform",
        "credential_kind": "console_session",
        "secret": SECRET,
        **extra,
    }


def console_create(prepare_id, choice_id="c1", persist=False):
    return {
        "provider": "claude_platform",
        "label": "Console",
        "source": {
            "credential_kind": "console_session",
            "prepare_id": prepare_id,
            "choice_id": choice_id,
            "persist": persist,
        },
    }


async def test_console_prepare_singleton_is_explicit_and_session_save(env):
    discovery = Discovery()
    ops, host, credentials = make(env, discovery=discovery)
    prepared = await ops.prepare(console_prepare())
    assert discovery.seen == [SECRET]
    assert prepared["choices"] == [
        {"id": "c1", "label": "Work org", "legacy": False, "current": False}
    ]
    assert SECRET not in json.dumps(prepared) and ORG not in json.dumps(prepared)
    (record,) = ops._records.values()
    temp = record.temp_ref
    assert credentials.session_present(temp)
    # Nothing is saved or auto-selected until an explicit choice is submitted.
    assert env.store.load() == () and host.calls == []
    await fails(
        ops.create(
            {
                "provider": "claude_platform",
                "label": "Console",
                "source": {
                    "credential_kind": "console_session",
                    "prepare_id": prepared["prepare_id"],
                },
            }
        ),
        422,
        "selection_required",
    )
    source = console_create(prepared["prepare_id"])
    del source["source"]["persist"]
    await fails(ops.create(source), 422, "persist_required")
    result = await ops.create(console_create(prepared["prepare_id"]))
    saved = result.account
    assert saved.id == record.account_id and saved.organization_id == ORG
    assert saved.credential_ref.startswith("session:") and saved.credential_ref != temp
    assert credentials.get(saved.credential_ref) == SECRET
    assert not credentials.session_present(temp)
    assert ops._records == {}


async def test_console_nameless_org_never_sends_its_id(env):
    discovery = Discovery((OrganizationChoice(ORG, ORG), OrganizationChoice(ORG2, "Named")))
    ops, _, _ = make(env, discovery=discovery)
    prepared = await ops.prepare(console_prepare())
    assert [choice["label"] for choice in prepared["choices"]] == [None, "Named"]
    assert ORG not in json.dumps(prepared) and ORG2 not in json.dumps(prepared)


async def test_console_failures_delete_temp_ref(env):
    discovery = Discovery()
    discovery.error = RuntimeError(SECRET)
    clock = Clock()
    ops, _, credentials = make(env, discovery=discovery, clock=clock)
    error = await fails(ops.prepare(console_prepare()), 502, "discovery_failed")
    assert SECRET not in repr(error)
    assert credentials._session == {} and ops._records == {}
    discovery.error = None
    discovery.choices = ()
    clock.value += 11
    await fails(ops.prepare(console_prepare()), 422, "no_choices")
    assert credentials._session == {} and ops._records == {}


async def test_console_discovery_timeout(env):
    discovery = Discovery()
    discovery.delay = 5
    ops, _, credentials = make(env, discovery=discovery)
    ops.DISCOVERY_SECONDS = 0.05
    await fails(ops.prepare(console_prepare()), 502, "discovery_failed")
    assert credentials._session == {}


async def test_console_without_discovery_and_missing_secret(env):
    ops, _, _ = make(env)
    await fails(ops.prepare(console_prepare()), 502, "discovery_failed")
    body = console_prepare()
    del body["secret"]
    await fails(ops.prepare(body), 422, "secret_required")
    await fails(ops.prepare(console_prepare(secret="Cookie: a=b")), 422, "invalid_secret")


async def test_discovery_throttles(env):
    discovery = Discovery()
    clock = Clock()
    ops, _, _ = make(env, discovery=discovery, clock=clock)
    await ops.prepare(console_prepare())
    busy = await fails(ops.prepare(console_prepare()), 409, "discovery_busy")
    assert busy.retry_after == 10
    for _ in range(5):
        clock.value += 10
        await ops.prepare(console_prepare())
    clock.value += 10
    budget = await fails(ops.prepare(console_prepare()), 409, "discovery_busy")
    assert budget.retry_after == 600 - 60
    clock.value += 600
    await ops.prepare(console_prepare())
    # One at a time: a running discovery makes the next request busy.
    discovery.delay = 0.2
    clock.value += 600
    running = asyncio.create_task(ops.prepare(console_prepare()))
    await asyncio.sleep(0.05)
    clock.value += 20
    concurrent = await fails(ops.prepare(console_prepare()), 409, "discovery_busy")
    assert concurrent.retry_after >= 1
    await running


async def test_console_persist_retry_and_org_only_edit(env):
    discovery = Discovery((OrganizationChoice(ORG, "One"), OrganizationChoice(ORG2, "Two")))
    clock = Clock()
    ops, host, credentials = make(env, discovery=discovery, clock=clock)
    prepared = await ops.prepare(console_prepare())
    await fails(
        ops.create(console_create(prepared["prepare_id"], persist=True)),
        503,
        "secure_store_unavailable",
    )
    # The record is kept, so a session-only retry needs no re-entry of the key.
    created = (await ops.create(console_create(prepared["prepare_id"]))).account
    ref = created.credential_ref
    clock.value += 11
    edit = await ops.prepare(
        {
            "account_id": created.id,
            "revision": ops.revision(created),
            "credential_kind": "console_session",
        }
    )
    assert discovery.seen[-1] == SECRET
    assert [choice["current"] for choice in edit["choices"]] == [True, False]
    assert ops._records[edit["prepare_id"]].temp_ref is None
    patch = {
        "source": {
            "credential_kind": "console_session",
            "prepare_id": edit["prepare_id"],
            "choice_id": "c2",
        }
    }
    updated = await ops.update(created.id, ops.revision(created), patch)
    assert updated.account.organization_id == ORG2
    assert updated.account.credential_ref == ref and credentials.get(ref) == SECRET
    assert host.calls[-1][1] == frozenset({created.id})


async def test_record_bound_to_revision(env):
    discovery = Discovery()
    ops, _, _ = make(env, discovery=discovery)
    prepared = await ops.prepare(console_prepare())
    created = (await ops.create(console_create(prepared["prepare_id"]))).account
    ops._discovery_starts.clear()
    edit = await ops.prepare(
        {
            "account_id": created.id,
            "revision": ops.revision(created),
            "credential_kind": "console_session",
        }
    )
    renamed = (await ops.update(created.id, ops.revision(created), {"label": "New"})).account
    patch = {
        "source": {
            "credential_kind": "console_session",
            "prepare_id": edit["prepare_id"],
            "choice_id": "c1",
        }
    }
    await fails(ops.update(renamed.id, ops.revision(renamed), patch), 410, "prepare_expired")
    # A create record cannot edit an account, and vice versa.
    ops._discovery_starts.clear()
    fresh = await ops.prepare(console_prepare())
    patch["source"].update(prepare_id=fresh["prepare_id"], persist=False)
    await fails(ops.update(renamed.id, ops.revision(renamed), patch), 410, "prepare_expired")


# --- revisions, conflicts, remove, reorder --------------------------------------------


async def test_revision_mismatch_resyncs_then_409(env):
    first, second = account(label="First"), account(label="Second")
    ops, host, _ = make(env, (first, second))
    stale = ops.revision(first)
    # Another process edits the config file.
    env.store.save((replace(first, label="Elsewhere"), second))
    await fails(ops.update(first.id, stale, {"label": "Mine"}), 409, "conflict")
    assert host.calls == [((replace(first, label="Elsewhere"), second), frozenset())]
    await fails(ops.update(str(uuid4()), stale, {}), 404, "not_found")
    await fails(ops.remove(first.id, "0" * 32), 409, "conflict")
    # No further resync call when the host already matches the file.
    assert len(host.calls) == 1


async def test_noop_patch_is_a_revision_checked_save(env):
    item = account()
    ops, host, _ = make(env, (item,))
    result = await ops.update(item.id, ops.revision(item), {})
    assert result.account == item and host.calls[-1][1] == frozenset()


async def test_remove_and_reorder(env):
    first, second, third = account(label="1"), account(label="2"), account(label="3")
    ops, host, _ = make(env, (first, second, third))
    ordered = await ops.reorder({"ids": [third.id, first.id, second.id]})
    assert ordered.accounts == (third, first, second) == env.store.load()
    assert host.calls[-1] == ((third, first, second), frozenset())
    await fails(ops.reorder({"ids": [first.id, first.id, second.id]}), 409, "conflict")
    await fails(ops.reorder({"ids": [first.id]}), 409, "conflict")
    await fails(ops.reorder({"ids": ["not-a-uuid"]}), 400, "invalid_request")
    await fails(ops.reorder({"ids": [first.id.upper()]}), 400, "invalid_request")
    await fails(ops.reorder({"ids": [str(uuid4())] * 101}), 400, "invalid_request")
    await fails(ops.reorder({"ids": "x"}), 400, "invalid_request")
    await fails(ops.reorder({}), 400, "invalid_request")
    removed = await ops.remove(first.id, ops.revision(first))
    assert removed.account is None and removed.accounts == (third, second)
    assert host.calls[-1] == ((third, second), frozenset({first.id}))


async def test_committed_uncertain_notifies_once_with_warning(env):
    item = account()
    ops, host, _ = make(env, (item,))
    real = env.store.mutate

    def uncertain(change):
        raise ConfigCommittedError(real(change))

    env.store.mutate = uncertain
    result = await ops.update(item.id, ops.revision(item), {"label": "Renamed"})
    assert result.warning == "committed_uncertain"
    assert result.account.label == "Renamed"
    assert len(host.calls) == 1


async def test_host_failure_after_commit_is_a_warning(env):
    item = account()
    ops, host, _ = make(env, (item,))
    host.fail = True
    result = await ops.update(item.id, ops.revision(item), {"label": "Renamed"})
    assert result.warning == "host_refresh_failed"
    assert env.store.load()[0].label == "Renamed"


async def test_config_error_is_503(env):
    ops, _, _ = make(env)
    env.store.path.write_text("{")
    env.store.path.chmod(0o600)
    await fails(ops.update(str(uuid4()), "0" * 32, {}), 503, "config_unavailable")


# --- ordering, cancellation, shutdown ---------------------------------------------------


async def test_cancelled_request_still_commits_and_publishes_in_order(env):
    first, second = account(label="First"), account(label="Second")
    ops, host, _ = make(env, (first, second))
    await host.account_lock.acquire()
    a = asyncio.create_task(ops.update(first.id, ops.revision(first), {"label": "A"}))
    for _ in range(200):
        if ops._commits:
            break
        await asyncio.sleep(0.01)
    assert ops._commits
    a.cancel()
    b = asyncio.create_task(ops.update(second.id, ops.revision(second), {"label": "B"}))
    await asyncio.sleep(0.1)
    host.account_lock.release()
    with pytest.raises(asyncio.CancelledError):
        await a
    result = await b
    assert [tuple(item.label for item in call[0]) for call in host.calls] == [
        ("A", "Second"),
        ("A", "B"),
    ]
    assert result.accounts == env.store.load() == host.accounts


async def test_cancelled_secret_replacement_commits_with_its_secret(env):
    ops, host, credentials = make(env)
    created = await ops.create(
        {
            "provider": "claude_subscription",
            "label": "Bearer",
            "source": {"credential_kind": "manual_bearer", "secret": BEARER, "persist": False},
        }
    )
    old = created.account
    replacement = "synthetic-replacement-never-echo"
    await host.account_lock.acquire()
    task = asyncio.create_task(
        ops.update(
            old.id,
            ops.revision(old),
            {
                "source": {
                    "credential_kind": "manual_bearer",
                    "secret": replacement,
                    "persist": False,
                }
            },
        )
    )
    for _ in range(200):
        if ops._commits:
            break
        await asyncio.sleep(0.01)
    assert ops._commits
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    host.account_lock.release()
    for _ in range(200):
        if not ops._commits:
            break
        await asyncio.sleep(0.01)
    (saved,) = env.store.load()
    # The shielded commit still owned the secret: the new ref is real, the old is gone.
    assert saved.credential_ref != old.credential_ref
    assert credentials.get(saved.credential_ref) == replacement
    assert not credentials.session_present(old.credential_ref)
    assert host.accounts == (saved,)


async def test_tui_style_writer_blocks_http_commit(env):
    first, second = account(label="First"), account(label="Second")
    ops, host, _ = make(env, (first, second))
    async with host.account_lock:
        http = asyncio.create_task(ops.update(second.id, ops.revision(second), {"label": "Web"}))
        await asyncio.sleep(0.1)
        # The TUI calls the service synchronously while holding the lock.
        updated = ops.service.save(replace(first, label="TUI"), original=first)
        await host.accounts_changed(updated, invalidate=frozenset())
        assert not http.done() and len(host.calls) == 1
    await http
    assert host.accounts == env.store.load()
    assert [item.label for item in host.accounts] == ["TUI", "Web"]


async def test_aclose_awaits_commits_and_deletes_temp_refs(env):
    item = account()
    ops, host, credentials = make(env, (item,), discovery=Discovery())
    await ops.prepare(console_prepare())
    assert credentials._session
    await host.account_lock.acquire()
    task = asyncio.create_task(ops.update(item.id, ops.revision(item), {"label": "Late"}))
    for _ in range(200):
        if ops._commits:
            break
        await asyncio.sleep(0.01)
    asyncio.get_running_loop().call_later(0.1, host.account_lock.release)
    await ops.aclose()
    assert task.done() and host.accounts[0].label == "Late"
    assert credentials._session == {} and ops._records == {}
    await ops.aclose()


# --- reconnect and file-read bounds -------------------------------------------------


async def test_reconnect_is_coalesced_and_checks_credentials(env):
    codex_login(env.dirs["CODEX_HOME"] / "auth.json")
    clock = Clock()
    item = account(
        ProviderId.CODEX_SUBSCRIPTION,
        credential_kind=CredentialKind.CODEX_AUTH_FILE,
        credential_ref="default",
        poll_interval_seconds=45,
    )
    broken = account(credential_kind=CredentialKind.CLAUDE_CODE_FILE, credential_ref="default")
    ops, host, _ = make(env, (item, broken), clock=clock)
    await ops.reconnect(item.id)
    await ops.reconnect(item.id)
    clock.value += 44
    await ops.reconnect(item.id)
    assert host.reconnects == [item.id]
    clock.value += 2
    await ops.reconnect(item.id)
    assert host.reconnects == [item.id, item.id]
    await fails(ops.reconnect(broken.id), 422, "credential_unavailable")
    await fails(ops.reconnect(str(uuid4())), 404, "not_found")
    assert host.reconnects == [item.id, item.id]


async def test_concurrent_reconnects_coalesce(env):
    codex_login(env.dirs["CODEX_HOME"] / "auth.json")
    item = account(
        ProviderId.CODEX_SUBSCRIPTION,
        credential_kind=CredentialKind.CODEX_AUTH_FILE,
        credential_ref="default",
    )
    ops, host, _ = make(env, (item,))
    await asyncio.gather(*(ops.reconnect(item.id) for _ in range(5)))
    assert host.reconnects == [item.id]


async def test_failed_reconnect_releases_its_reservation(env):
    clock = Clock()
    item = account(
        ProviderId.CODEX_SUBSCRIPTION,
        credential_kind=CredentialKind.CODEX_AUTH_FILE,
        credential_ref="default",
    )
    ops, host, _ = make(env, (item,), clock=clock)
    await fails(ops.reconnect(item.id), 422, "credential_unavailable")
    codex_login(env.dirs["CODEX_HOME"] / "auth.json")
    await ops.reconnect(item.id)
    assert host.reconnects == [item.id]


async def test_cancelled_console_prepare_leaves_no_session_secret(env):
    discovery = Discovery()
    discovery.delay = 5
    ops, _, credentials = make(env, discovery=discovery)
    task = asyncio.create_task(ops.prepare(console_prepare()))
    for _ in range(200):
        if discovery.seen:
            break
        await asyncio.sleep(0.01)
    assert credentials._session
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert credentials._session == {} and ops._records == {}


async def test_console_prepare_secret_is_deleted_on_expiry_without_another_write(env):
    ops, _, credentials = make(env, discovery=Discovery())
    ops.PREPARE_TTL = 0.05
    await ops.prepare(console_prepare())
    assert credentials._session and ops._records
    await asyncio.sleep(0.2)
    assert credentials._session == {} and ops._records == {}


async def test_file_reads_are_bounded_to_two(env):
    ops, _, _ = make(env)
    release = threading.Event()
    lock = threading.Lock()
    state = {"now": 0, "max": 0}

    def probe():
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        release.wait(5)
        with lock:
            state["now"] -= 1

    tasks = [asyncio.create_task(ops._file_read(probe)) for _ in range(5)]
    await asyncio.sleep(0.2)
    # A cancelled waiter does not free its slot while its thread still runs.
    tasks[0].cancel()
    await asyncio.sleep(0.1)
    assert state["max"] == 2
    release.set()
    await asyncio.gather(*tasks[1:])
    deadline = time.monotonic() + 5
    while state["now"] and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert state["max"] == 2


# --- Claude subscription prepaid-credits organization ------------------------------


class Recording(Discovery):
    """Discovery that also records the organization the credential carried."""

    def __init__(self, choices=WORK) -> None:
        super().__init__(choices)
        self.organizations = []

    async def __call__(self, credential):
        self.organizations.append(credential.organization_id)
        return await super().__call__(credential)


def claude_login(env, token="claude-file-token"):
    later = int((datetime.now(UTC) + timedelta(hours=6)).timestamp() * 1000)
    return write(
        env.dirs["CLAUDE_CONFIG_DIR"] / ".credentials.json",
        {"claudeAiOauth": {"accessToken": token, "expiresAt": later}},
    )


def credits_prepare(**extra):
    return {
        "provider": "claude_subscription",
        "credential_kind": "claude_code_file",
        "reference": "default",
        **extra,
    }


def claude_create(**source):
    return {
        "provider": "claude_subscription",
        "label": "Claude",
        "source": {"credential_kind": "claude_code_file", "reference": "default", **source},
    }


def by_provider(claude=None, console=None):
    found = {}
    if claude is not None:
        found[ProviderId.CLAUDE_SUBSCRIPTION] = claude
    if console is not None:
        found[ProviderId.CLAUDE_PLATFORM] = console
    return found


async def test_claude_credits_prepare_is_explicit_and_binds_the_choice(env):
    claude_login(env)
    discovery = Recording()
    ops, host, _ = make(env, discovery=by_provider(claude=discovery))
    prepared = await ops.prepare(credits_prepare())
    assert prepared["kind"] == "claude_organization"
    assert prepared["choices"] == [
        {"id": "c1", "label": "Work org", "legacy": False, "current": False}
    ]
    # The profile read is unscoped and nothing is saved or selected by discovery.
    assert discovery.seen == ["claude-file-token"] and discovery.organizations == [None]
    assert ORG not in json.dumps(prepared) and env.store.load() == () and host.calls == []
    # A save without the choice never auto-selects even the single organization.
    plain = await ops.create(claude_create())
    assert plain.account.organization_id is None
    selected = await ops.create(claude_create(prepare_id=prepared["prepare_id"], choice_id="c1"))
    assert selected.account.organization_id == ORG
    assert selected.account.poll_interval_seconds == 180
    assert host.calls[-1][1] == frozenset({selected.account.id})
    view = ops.config_view(selected.account)
    assert view["organization_selected"] is True and ORG not in json.dumps(view)
    assert ops._records == {}


async def test_claude_credits_nameless_org_and_empty_profile(env):
    claude_login(env)
    discovery = Recording((OrganizationChoice(ORG, ORG),))
    clock = Clock()
    ops, _, _ = make(env, discovery=by_provider(claude=discovery), clock=clock)
    prepared = await ops.prepare(credits_prepare())
    assert prepared["choices"][0]["label"] is None and ORG not in json.dumps(prepared)
    discovery.choices = ()
    clock.value += 11
    await fails(ops.prepare(credits_prepare()), 422, "no_choices")


async def test_claude_credits_choice_is_bound_to_the_login_that_was_read(env):
    claude_login(env)
    other = claude_login(env)  # same default file; a custom path is a different login
    custom = write(env.tmp / "other" / ".credentials.json", json.loads(other.read_text()))
    ops, _, _ = make(env, discovery=by_provider(claude=Recording()))
    prepared = await ops.prepare(credits_prepare())
    await fails(
        ops.create(
            {
                "provider": "claude_subscription",
                "label": "Claude",
                "source": {
                    "credential_kind": "claude_code_file",
                    "reference": str(custom),
                    "prepare_id": prepared["prepare_id"],
                    "choice_id": "c1",
                },
            }
        ),
        410,
        "prepare_expired",
    )
    await fails(
        ops.create(claude_create(prepare_id=prepared["prepare_id"], choice_id="c9")),
        422,
        "invalid_choice",
    )
    await fails(
        ops.create(claude_create(prepare_id=prepared["prepare_id"])), 422, "selection_required"
    )
    await fails(
        ops.create(
            claude_create(prepare_id=prepared["prepare_id"], choice_id="c1", organization="keep")
        ),
        400,
        "invalid_request",
    )


async def test_claude_credits_manual_bearer_digest_binding(env):
    discovery = Recording()
    clock = Clock()
    ops, _, credentials = make(env, discovery=by_provider(claude=discovery), clock=clock)
    prepared = await ops.prepare(
        {
            "provider": "claude_subscription",
            "credential_kind": "manual_bearer",
            "secret": BEARER,
        }
    )
    assert discovery.seen == [BEARER]
    # The typed bearer is not kept after discovery; the record holds only a digest.
    assert credentials._session == {}
    (record,) = ops._records.values()
    assert record.temp_ref is None and BEARER.encode() not in record.secret_digest

    def body(secret):
        return {
            "provider": "claude_subscription",
            "label": "Bearer",
            "source": {
                "credential_kind": "manual_bearer",
                "secret": secret,
                "persist": False,
                "prepare_id": prepared["prepare_id"],
                "choice_id": "c1",
            },
        }

    await fails(ops.create(body("different-bearer-value")), 410, "prepare_expired")
    created = (await ops.create(body(BEARER))).account
    assert created.organization_id == ORG and credentials.get(created.credential_ref) == BEARER
    # Rediscovery with the saved bearer (edit, no secret) is bound to the saved ref.
    clock.value += 11
    edit = await ops.prepare(
        {
            "account_id": created.id,
            "revision": ops.revision(created),
            "credential_kind": "manual_bearer",
        }
    )
    assert discovery.seen[-1] == BEARER and discovery.organizations[-1] is None
    assert edit["choices"][0]["current"] is True
    await fails(
        ops.update(
            created.id,
            ops.revision(created),
            {
                "source": {
                    "credential_kind": "manual_bearer",
                    "secret": "another-bearer-value",
                    "persist": False,
                    "prepare_id": edit["prepare_id"],
                    "choice_id": "c1",
                }
            },
        ),
        410,
        "prepare_expired",
    )


async def test_claude_credits_changed_login_requires_reselect(env):
    claude_login(env)
    custom = write(
        env.tmp / "other" / ".credentials.json",
        json.loads((env.dirs["CLAUDE_CONFIG_DIR"] / ".credentials.json").read_text()),
    )
    saved = account(
        credential_kind=CredentialKind.CLAUDE_CODE_FILE,
        credential_ref="default",
        organization_id=ORG,
        poll_interval_seconds=180,
    )
    ops, host, _ = make(env, [saved])

    def source(reference, **extra):
        return {"source": {"credential_kind": "claude_code_file", "reference": reference, **extra}}

    await fails(
        ops.update(saved.id, ops.revision(saved), source(str(custom))),
        422,
        "organization_reselect_required",
    )
    await fails(
        ops.update(saved.id, ops.revision(saved), source(str(custom), organization="keep")),
        422,
        "organization_reselect_required",
    )
    await fails(
        ops.update(saved.id, ops.revision(saved), source("default", organization="other")),
        400,
        "invalid_request",
    )
    assert env.store.load() == (saved,) and host.calls == []
    # The same login keeps the saved organization, implicitly or explicitly.
    kept = (await ops.update(saved.id, ops.revision(saved), source("default"))).account
    assert kept.organization_id == ORG
    kept = (
        await ops.update(kept.id, ops.revision(kept), source("default", organization="keep"))
    ).account
    assert kept.organization_id == ORG
    cleared = (
        await ops.update(kept.id, ops.revision(kept), source(str(custom), organization="none"))
    ).account
    assert cleared.organization_id is None
    # A rename keeps the organization and scheduler state.
    renamed = (await ops.update(kept.id, ops.revision(cleared), {"label": "Renamed"})).account
    assert renamed.organization_id is None and host.calls[-1][1] == frozenset()


async def test_claude_api_key_never_carries_a_credits_organization(env):
    saved = account(
        credential_kind=CredentialKind.CLAUDE_CODE_FILE,
        credential_ref="default",
        organization_id=ORG,
    )
    ops, _, _ = make(env, [saved])
    await fails(
        ops.update(
            saved.id,
            ops.revision(saved),
            {
                "source": {
                    "credential_kind": "api_key",
                    "secret": "sk-ant-api-synthetic",
                    "persist": False,
                    "organization": "keep",
                }
            },
        ),
        400,
        "invalid_request",
    )
    updated = (
        await ops.update(
            saved.id,
            ops.revision(saved),
            {
                "source": {
                    "credential_kind": "api_key",
                    "secret": "sk-ant-api-synthetic",
                    "persist": False,
                }
            },
        )
    ).account
    assert updated.credential_kind == CredentialKind.API_KEY and updated.organization_id is None
    await fails(
        ops.prepare(
            {
                "account_id": saved.id,
                "revision": ops.revision(updated),
                "credential_kind": "api_key",
            }
        ),
        422,
        "invalid_kind",
    )


async def test_discovery_mapping_routes_per_provider_and_shares_the_throttle(env):
    claude_login(env)
    claude, console = Recording(), Discovery()
    clock = Clock()
    ops, _, _ = make(env, discovery=by_provider(claude=claude, console=console), clock=clock)
    await ops.prepare(credits_prepare())
    busy = await fails(ops.prepare(console_prepare()), 409, "discovery_busy")
    assert busy.retry_after == 10
    clock.value += 11
    await ops.prepare(console_prepare())
    assert claude.seen == ["claude-file-token"] and console.seen == [SECRET]
    # A bare callable is the Console discovery only.
    legacy, _, _ = make(env, discovery=console)
    await fails(legacy.prepare(credits_prepare()), 502, "discovery_failed")
    only_claude, _, _ = make(env, discovery=by_provider(claude=claude))
    await fails(only_claude.prepare(console_prepare()), 502, "discovery_failed")


async def test_claude_credits_prepare_failures_leave_no_secret(env):
    discovery = Recording()
    discovery.error = RuntimeError(BEARER)
    ops, _, credentials = make(env, discovery=by_provider(claude=discovery))
    error = await fails(
        ops.prepare(
            {
                "provider": "claude_subscription",
                "credential_kind": "manual_bearer",
                "secret": BEARER,
            }
        ),
        502,
        "discovery_failed",
    )
    assert BEARER not in repr(error)
    assert credentials._session == {} and ops._records == {}
    await fails(ops.prepare(credits_prepare()), 409, "discovery_busy")
    ops._discovery_starts.clear()
    # No login file: a curated code, and the reference-less manual kind needs a secret.
    await fails(ops.prepare(credits_prepare()), 422, "credential_unavailable")
    ops._discovery_starts.clear()
    await fails(
        ops.prepare({"provider": "claude_subscription", "credential_kind": "manual_bearer"}),
        422,
        "secret_required",
    )
    await fails(ops.prepare(credits_prepare(secret=BEARER)), 400, "invalid_request")


# --- OpenAI Platform ------------------------------------------------------------------


OPENAI_ORG = "org-SyntheticOrg1234"
OPENAI_SESSION = "sess-synthetic-dashboard-session-never-echo"


def openai_create(**extra):
    return {
        "provider": "openai_platform",
        "label": "OpenAI",
        "organization_id": OPENAI_ORG,
        "source": {
            "credential_kind": "openai_platform_session",
            "secret": OPENAI_SESSION,
            "persist": False,
        },
        **extra,
    }


async def test_openai_create_session_and_required_organization(env):
    ops, host, credentials = make(env)
    created = (await ops.create(openai_create(organization_id=f"  {OPENAI_ORG} "))).account
    assert created.provider == ProviderId.OPENAI_PLATFORM
    assert created.credential_kind == CredentialKind.OPENAI_PLATFORM_SESSION
    assert created.organization_id == OPENAI_ORG
    assert created.poll_interval_seconds == 300
    assert credentials.get(created.credential_ref) == OPENAI_SESSION
    view = ops.config_view(created)
    assert view["storage"] == "session" and view["organization_selected"] is True
    text = json.dumps(view)
    assert OPENAI_ORG not in text and OPENAI_SESSION not in text
    body = openai_create()
    del body["organization_id"]
    await fails(ops.create(body), 422, "organization_required")
    for bad in ("org-short", "SyntheticOrg1234", "org-has space1234", 7):
        await fails(
            ops.create(openai_create(organization_id=bad)),
            422 if bad != 7 else 400,
            "invalid_organization" if bad != 7 else "invalid_request",
        )
    # Never accepted for another provider.
    await fails(ops.create({**codex_body(), "organization_id": OPENAI_ORG}), 400, "invalid_request")
    # Without a credential the organization is still required metadata.
    bare = (await ops.create(openai_create(source=None))).account
    assert bare.credential_kind is None and bare.organization_id == OPENAI_ORG
    assert len(host.calls) == 2


@pytest.mark.parametrize(
    "secret",
    [
        "sk-proj-synthetic-api-key-value-0000",
        "Bearer sess-synthetic-dashboard-session",
        "Cookie: a=sess-synthetic-dashboard-session",
        '{"sensitive_id": "sess-synthetic-dashboard"}',
        "sess-short",
        "sess-synthetic\nsecond-line-value-0000",
    ],
)
async def test_openai_rejects_non_session_secrets(env, secret):
    ops, host, credentials = make(env)
    body = openai_create()
    body["source"]["secret"] = secret
    error = await fails(ops.create(body), 422, "invalid_secret")
    assert secret not in repr(error)
    assert env.store.load() == () and host.calls == [] and credentials._session == {}


async def test_openai_only_session_kind_and_persist_needs_secure_store(env):
    ops, _, _ = make(env)
    for kind in ("api_key", "manual_bearer", "console_session"):
        body = openai_create()
        body["source"]["credential_kind"] = kind
        await fails(ops.create(body), 422, "invalid_kind")
    body = openai_create()
    body["source"]["persist"] = True
    await fails(ops.create(body), 503, "secure_store_unavailable")
    await fails(
        ops.prepare({"provider": "openai_platform", "credential_kind": "openai_platform_session"}),
        422,
        "invalid_kind",
    )
    # The session kind is never accepted for another provider.
    await fails(
        ops.create(
            {
                "provider": "claude_subscription",
                "label": "x",
                "source": {
                    "credential_kind": "openai_platform_session",
                    "secret": OPENAI_SESSION,
                    "persist": False,
                },
            }
        ),
        422,
        "invalid_kind",
    )


async def test_openai_update_organization_rebinds_and_keeps_otherwise(env):
    ops, host, credentials = make(env)
    created = (await ops.create(openai_create())).account
    renamed = (await ops.update(created.id, ops.revision(created), {"label": "Renamed"})).account
    assert renamed.organization_id == OPENAI_ORG and host.calls[-1][1] == frozenset()
    moved = (
        await ops.update(
            renamed.id, ops.revision(renamed), {"organization_id": "org-AnotherOrg5678"}
        )
    ).account
    assert moved.organization_id == "org-AnotherOrg5678"
    assert moved.credential_ref == created.credential_ref
    assert host.calls[-1][1] == frozenset({created.id})
    # Keeping the saved session (no secret) and detaching both keep the organization.
    kept = (
        await ops.update(
            moved.id,
            ops.revision(moved),
            {"source": {"credential_kind": "openai_platform_session"}},
        )
    ).account
    assert kept.credential_ref == created.credential_ref
    assert kept.organization_id == "org-AnotherOrg5678"
    detached = (await ops.update(kept.id, ops.revision(kept), {"source": None})).account
    assert detached.credential_kind is None and detached.organization_id == "org-AnotherOrg5678"
    assert not credentials.session_present(created.credential_ref)
    await fails(
        ops.update(detached.id, ops.revision(detached), {"organization_id": "nope"}),
        422,
        "invalid_organization",
    )


async def test_claude_credits_change_keeps_a_hidden_saved_file(env):
    claude_login(env)
    custom = write(
        env.tmp / "hidden" / ".credentials.json",
        json.loads((env.dirs["CLAUDE_CONFIG_DIR"] / ".credentials.json").read_text()),
    )
    saved = account(
        credential_kind=CredentialKind.CLAUDE_CODE_FILE,
        credential_ref=str(custom),
        poll_interval_seconds=180,
    )
    discovery = Recording()
    ops, host, _ = make(env, [saved], discovery=by_provider(claude=discovery))
    # Discovery and save both use the saved path without the page ever naming it.
    prepared = await ops.prepare(
        {
            "account_id": saved.id,
            "revision": ops.revision(saved),
            "credential_kind": "claude_code_file",
        }
    )
    selected = (
        await ops.update(
            saved.id,
            ops.revision(saved),
            {
                "source": {
                    "credential_kind": "claude_code_file",
                    "prepare_id": prepared["prepare_id"],
                    "choice_id": "c1",
                }
            },
        )
    ).account
    assert selected.credential_ref == str(custom) and selected.organization_id == ORG
    assert host.calls[-1][1] == frozenset({saved.id})
    cleared = (
        await ops.update(
            selected.id,
            ops.revision(selected),
            {"source": {"credential_kind": "claude_code_file", "organization": "none"}},
        )
    ).account
    assert cleared.credential_ref == str(custom) and cleared.organization_id is None
    # Other file kinds still need an explicit reference.
    codex = account(
        ProviderId.CODEX_SUBSCRIPTION,
        credential_kind=CredentialKind.CODEX_AUTH_FILE,
        credential_ref="default",
    )
    ops, _, _ = make(env, [cleared, codex])
    await fails(
        ops.update(
            codex.id, ops.revision(codex), {"source": {"credential_kind": "codex_auth_file"}}
        ),
        422,
        "invalid_reference",
    )
