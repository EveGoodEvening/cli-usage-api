"""One-process mode: the dashboard hosts the read-only API and keepalive in its loop.

Real sockets on 127.0.0.1 and real Textual apps (headless). Keepalive uses fake
login files and fake official CLIs on PATH; no browsers, keyring or network.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
import stat
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from textual.widgets._toast import Toast

from cli_usage_api import api, cli, keepalive
from cli_usage_api.app import UsageApp
from cli_usage_api.domain import (
    Account,
    FetchState,
    Metric,
    MetricId,
    MetricState,
    ProviderId,
    QuotaValue,
    Snapshot,
    SourceKind,
    SourceRef,
)
from cli_usage_api.storage import ApiTokenStore

FIRST = "11111111-1111-4111-8111-111111111111"
SECOND = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "config"))
    for variable in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "GROK_HOME"):
        monkeypatch.setenv(variable, str(tmp_path / variable))
    monkeypatch.setattr(cli, "_tty", lambda: True)
    return home


def account(account_id=FIRST, label="Claude main", **kwargs):
    return Account(id=account_id, provider=ProviderId.CLAUDE_SUBSCRIPTION, label=label, **kwargs)


def snapshot(account_id, used="12.5"):
    metric = Metric(
        id=MetricId.CLAUDE_FIVE_HOUR,
        label="Claude 5h",
        state=MetricState.READY,
        source=SourceRef(SourceKind.OFFLINE_DEMO, "test"),
        quota=QuotaValue(used_percent=used),
    )
    return Snapshot(
        account_id=account_id,
        metrics=(metric,),
        grants=(),
        fetch_state=FetchState.OK,
        attempted_at=NOW,
        fetched_at=NOW,
    )


class FakeScheduler:
    def __init__(self, events, publish):
        self.events = events
        self.publish = publish

    async def start(self):
        self.events.append("scheduler.start")

    async def refresh(self, account_id=None):
        self.events.append("scheduler.refresh")

    async def update_accounts(self, accounts):
        self.events.append("scheduler.update")

    async def stop(self):
        self.events.append("scheduler.stop")


class FakeFactory:
    def __init__(self, events):
        self.events = events
        self.scheduler = None

    def __call__(self, accounts, *, publish):
        self.scheduler = FakeScheduler(self.events, publish)
        return self.scheduler

    async def aclose(self):
        self.events.append("factory.close")


def embed(app, token_store=None, *, allow_unauthenticated=False):
    sock = api.bind_socket("127.0.0.1", 0)
    port = sock.getsockname()[1]
    usage_api = api.create_app(
        api.AppHub.attach(app),
        token_store,
        allow_unauthenticated=allow_unauthenticated,
    )
    server = api.EmbeddedServer(usage_api, sock, address=f"127.0.0.1:{port}")
    app.add_service(server)
    return server, f"http://127.0.0.1:{port}"


def client(base):
    return httpx.AsyncClient(base_url=base, trust_env=False, timeout=5)


def port_free(base):
    port = int(base.rsplit(":", 1)[1])
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) != 0


async def test_demo_api_serves_the_snapshots_the_tui_shows(tmp_path):
    store = ApiTokenStore()
    app = UsageApp(mode="demo")
    server, base = embed(app, store, allow_unauthenticated=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert server.running
        async with client(base) as http:
            health = await http.get("/healthz")
            dashboard = await http.get("/api/v1/dashboard")
            session = await http.get("/api/v1/session")
        assert health.json() == {"status": "ok"}
        assert dashboard.status_code == 200
        body = dashboard.json()
        assert body["mode"] == "demo"
        assert [item["account"]["id"] for item in body["accounts"]] == [
            item.id for item in app.accounts
        ]
        served = {
            item["account"]["id"]: item["snapshot"]
            for item in body["accounts"]
            if item["snapshot"] is not None
        }
        assert served
        for account_id, data in served.items():
            assert data == {**app.snapshots[account_id].to_dict(), "organization_id": None}
        assert session.json()["auth"] == "none"
        # The TUI shows where the API listens.
        assert f"API {base.removeprefix('http://')}" in str(app.banner.content)
        await pilot.press("q")
    # The API stopped with the app: the task finished and the port is released.
    assert not server.running
    assert port_free(base)


async def test_live_api_requires_tokens_and_tracks_account_changes():
    events = []
    factory = FakeFactory(events)
    store = ApiTokenStore()
    token, _ = store.create("embedded")
    first, second = account(FIRST), account(SECOND, "Second")
    app = UsageApp(mode="live", accounts=(first, second), scheduler_factory=factory)
    server, base = embed(app, store)
    async with app.run_test() as pilot:
        factory.scheduler.publish(snapshot(FIRST))
        factory.scheduler.publish(snapshot(SECOND, used="40"))
        await pilot.pause()
        headers = {"Authorization": f"Bearer {token}"}
        async with client(base) as http:
            assert (await http.get("/api/v1/dashboard")).status_code == 401
            wrong = await http.get("/api/v1/dashboard", headers={"Authorization": "Bearer usk_x"})
            assert wrong.status_code == 401
            body = (await http.get("/api/v1/dashboard", headers=headers)).json()
            assert [item["account"]["id"] for item in body["accounts"]] == [FIRST, SECOND]
            assert all(item["snapshot"] is not None for item in body["accounts"])

            # Edit + removal in the TUI: the API reflects the new list immediately,
            # and, like the TUI, holds no observation from before the change.
            await app.accounts_changed((replace(first, label="Renamed"),))
            changed = (await http.get("/api/v1/dashboard", headers=headers)).json()
            assert [item["account"]["id"] for item in changed["accounts"]] == [FIRST]
            assert changed["accounts"][0]["account"]["label"] == "Renamed"
            assert changed["accounts"][0]["snapshot"] is None
            removed = await http.get(f"/api/v1/accounts/{SECOND}", headers=headers)
            assert removed.status_code == 404
            assert SECOND not in server.api.hub.snapshots

            # A late snapshot from a removed account is ignored; a new one is served.
            factory.scheduler.publish(snapshot(SECOND))
            factory.scheduler.publish(snapshot(FIRST, used="77"))
            await pilot.pause()
            single = (await http.get(f"/api/v1/accounts/{FIRST}", headers=headers)).json()
            assert single["snapshot"]["metrics"][0]["quota"]["used_percent"] == "77"
            assert (await http.get(f"/api/v1/accounts/{SECOND}", headers=headers)).status_code == (
                404
            )

            # Added and disabled accounts appear at once; disabled ones carry no snapshot.
            added = account(SECOND, "Added", enabled=False)
            await app.accounts_changed((first, added))
            listed = (await http.get("/api/v1/dashboard", headers=headers)).json()
            assert [item["account"]["label"] for item in listed["accounts"]] == [
                "Claude main",
                "Added",
            ]
            assert listed["accounts"][1]["account"]["enabled"] is False
        assert "令牌认证" in str(app.banner.content)
        await pilot.press("ctrl+c")
    # The API never drove the scheduler, and stopped before the scheduler/factory.
    assert events.count("scheduler.start") == 1
    assert events[-2:] == ["scheduler.stop", "factory.close"]
    assert not server.running
    assert port_free(base)


async def test_api_server_failure_is_a_notification_not_a_crash(capfd):
    app = UsageApp(mode="demo")
    sock = api.bind_socket("127.0.0.1", 0)
    sock.close()  # The listener cannot attach to a closed socket.
    usage_api = api.create_app(api.AppHub.attach(app), None)
    server = api.EmbeddedServer(usage_api, sock, address="127.0.0.1:1")
    app.add_service(server)
    async with app.run_test(notifications=True) as pilot:
        for _ in range(50):
            await pilot.pause(0.05)
            if app.screen.query(Toast):
                break
        assert server.failed
        toasts = " ".join(str(toast.render()) for toast in app.screen.query(Toast))
        assert "API" in toasts
        await pilot.pause(1.1)
        assert "API 127.0.0.1:1 已停止" in str(app.banner.content)
        assert app.is_running
        await pilot.press("q")
    captured = capfd.readouterr()
    assert captured.err == "" and "uvicorn" not in captured.out.casefold()


def _jwt(exp: int) -> str:
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{part({'alg': 'none'})}.{part({'exp': exp})}.sig"


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    """A Codex login inside the refresh window and a fake ``codex`` that does nothing."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "codex-calls"
    script = bin_dir / "codex"
    script.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\nexit 0\n')
    script.chmod(0o700)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    login = tmp_path / "CODEX_HOME" / "auth.json"
    login.parent.mkdir(mode=0o700)
    expiry = int((datetime.now(UTC) + timedelta(seconds=120)).timestamp())
    login.write_text(json.dumps({"tokens": {"access_token": _jwt(expiry)}}))
    return calls, login


def keepalive_log(home):
    path = home / ".local" / "state" / "usage-keepalive" / "keepalive.log"
    return path.read_text() if path.exists() else ""


def test_dashboard_keepalive_runs_in_process_and_stops_on_exit(
    fake_codex, isolated_home, monkeypatch
):
    calls, _ = fake_codex
    seen = {}

    def run(app):
        async def exercise():
            async with app.run_test() as pilot:
                deadline = time.monotonic() + 10
                while not calls.exists() and time.monotonic() < deadline:
                    await pilot.pause(0.05)
                seen["note"] = str(app.banner.content)
                # The lock is held for the process lifetime.
                with pytest.raises(keepalive.KeepaliveError):
                    keepalive.InstanceLock().__enter__()
                await pilot.press("q")

        asyncio.run(exercise())

    monkeypatch.setattr(cli.UsageApp, "run", run)
    assert cli.main(["--keepalive", "--keepalive-cli", "codex"]) == 0
    assert calls.read_text().splitlines()[0] == "doctor --json"
    assert "keepalive codex" in seen["note"]
    log = keepalive_log(isolated_home)
    assert "keepalive started for codex" in log
    assert "codex not_advanced via=doctor" in log
    assert log.rstrip().endswith("keepalive stopped")
    # Released on shutdown.
    with keepalive.InstanceLock():
        pass
    log_path = isolated_home / ".local/state/usage-keepalive/keepalive.log"
    assert stat.S_IMODE(os.stat(log_path).st_mode) == 0o600


def test_dashboard_keepalive_alert_becomes_a_tui_warning(tmp_path, monkeypatch, capfd):
    login = tmp_path / "CODEX_HOME" / "auth.json"
    login.parent.mkdir(mode=0o700)
    login.write_text("{}")  # Present but unusable: keepalive alerts at once.
    seen = {}

    def run(app):
        async def exercise():
            async with app.run_test(notifications=True) as pilot:
                for _ in range(100):
                    await pilot.pause(0.05)
                    if app.screen.query(Toast):
                        break
                seen["toasts"] = [str(toast.render()) for toast in app.screen.query(Toast)]
                await pilot.press("q")

        asyncio.run(exercise())

    monkeypatch.setattr(cli.UsageApp, "run", run)
    assert cli.main(["--keepalive", "--keepalive-cli", "codex"]) == 0
    assert any("ALERT" in text and "codex" in text for text in seen["toasts"])
    # Nothing is written to the terminal the TUI owns.
    captured = capfd.readouterr()
    assert "ALERT" not in captured.out + captured.err


def test_api_serve_keepalive_prints_and_stops(fake_codex, isolated_home, monkeypatch, capsys):
    calls, _ = fake_codex
    ApiTokenStore().create("serve")

    async def fake_serve(app, sock, services=()):
        for service in services:
            await service.start(None)
        deadline = time.monotonic() + 10
        while not calls.exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        for service in reversed(services):
            await service.stop()
        sock.close()
        await app.hub.stop()

    monkeypatch.setattr(api, "serve", fake_serve)
    monkeypatch.setattr(api, "bind_socket", lambda host, port: socket.socket())
    assert cli.main(["api", "serve", "--keepalive", "--keepalive-claude-mode", "status"]) == 0
    out = capsys.readouterr().out
    assert "keepalive running for codex" in out
    assert "keepalive started for codex" in out and "keepalive stopped" in out
    assert "keepalive started for codex" in keepalive_log(isolated_home)
    with keepalive.InstanceLock():
        pass


def test_keepalive_refusals_happen_before_the_tui(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.UsageApp, "run", lambda app: pytest.fail("TUI must not start after a refusal")
    )
    # No login files exist in the isolated environment.
    assert cli.main(["--keepalive"]) == 2
    assert "No official CLI login files found" in capsys.readouterr().err


def test_keepalive_lock_held_is_curated(fake_codex, monkeypatch, capsys):
    monkeypatch.setattr(
        cli.UsageApp, "run", lambda app: pytest.fail("TUI must not start after a refusal")
    )
    with keepalive.InstanceLock():
        assert cli.main(["--keepalive"]) == 2
    assert "already running" in capsys.readouterr().err


def test_keepalive_lock_is_held_until_the_worker_returns(fake_codex, monkeypatch):
    """stop() bounds its wait, but the instance lock outlives a worker still running."""
    logs = []
    service = cli.KeepaliveService(["codex"], None, (), echo=False, log_file=logs.append)
    entered, release = threading.Event(), threading.Event()

    def stubborn(argv):  # Ignores the stop request, like an unkillable command.
        entered.set()
        release.wait(30)
        return 0

    service.keepalive._run = stubborn
    monkeypatch.setattr(cli.KeepaliveService, "STOP_SECONDS", 0.1)
    lock = cli._keepalive_lock(service)
    lock.__enter__()
    loop = asyncio.new_event_loop()
    exiting = None
    try:

        async def scenario():
            await service.start(None)
            assert await asyncio.to_thread(entered.wait, 10)
            await service.stop()

        loop.run_until_complete(scenario())
        assert "keepalive stopped" not in logs
        exiting = threading.Thread(target=lock.__exit__, args=(None, None, None))
        exiting.start()
        time.sleep(0.3)
        assert exiting.is_alive()  # Waiting for the worker, still holding the lock.
        with pytest.raises(keepalive.KeepaliveError):
            keepalive.InstanceLock().__enter__()
        release.set()
        exiting.join(10)
        assert not exiting.is_alive()
    finally:
        release.set()
        if exiting is None:
            lock.__exit__(None, None, None)
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()
    with keepalive.InstanceLock():
        pass
    assert logs[-1] == "keepalive stopped" and logs.count("keepalive stopped") == 1
    assert "codex attempt_stopped via=doctor" in logs


def test_keepalive_stop_kills_a_long_running_cli(fake_codex, tmp_path):
    calls, _ = fake_codex
    pid_file = tmp_path / "codex.pid"
    script = tmp_path / "bin" / "codex"
    script.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\necho $$ > "{pid_file}"\nexec sleep 60\n')
    logs = []
    service = cli.KeepaliveService(["codex"], None, (), echo=False, log_file=logs.append)
    elapsed = {}

    async def scenario():
        await service.start(None)
        deadline = time.monotonic() + 10
        while not (pid_file.exists() and pid_file.read_text().strip()):
            assert time.monotonic() < deadline
            await asyncio.sleep(0.02)
        started = time.monotonic()
        await service.stop()
        elapsed["stop"] = time.monotonic() - started

    with cli._keepalive_lock(service):
        asyncio.run(scenario())
    assert elapsed["stop"] < 5
    assert service.keepalive.wait_idle(0)
    pid = int(pid_file.read_text())
    stat_file = Path(f"/proc/{pid}/stat")

    def alive():
        try:
            return stat_file.read_text().rsplit(")", 1)[1].split()[0] not in {"Z", "X"}
        except OSError:
            return False

    deadline = time.monotonic() + 5
    while alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not alive()
    assert logs[-1] == "keepalive stopped"
    assert "codex attempt_stopped via=doctor" in logs
    assert not any("retry_in" in line or "ALERT" in line for line in logs)


def _grok_login(tmp_path):
    login = tmp_path / "GROK_HOME" / "auth.json"
    login.parent.mkdir(mode=0o700, exist_ok=True)
    later = (datetime.now(UTC) + timedelta(hours=6)).isoformat()
    login.write_text(
        json.dumps(
            {
                "https://accounts.x.ai/sign-in": {"key": "k", "expires_at": later},
                "https://auth.x.ai::abc": {"key": "k", "expires_at": later},
            }
        )
    )
    return login


def grok(account_id, selector=None, ref="default"):
    return Account(
        id=account_id,
        provider=ProviderId.GROK_SUBSCRIPTION,
        label="grok",
        credential_ref=ref,
        credential_kind="grok_auth_file",
        credential_selector=selector,
    )


def test_keepalive_service_protects_only_explicit_selectors(tmp_path):
    _grok_login(tmp_path)
    accounts = (grok(FIRST, "https://auth.x.ai::abc"), grok(SECOND))
    service = cli.KeepaliveService(["grok"], None, accounts, echo=False, log_file=[].append)
    target = service.keepalive.targets[0]
    assert target.protected == frozenset({"https://auth.x.ai::abc"})
    # A no-selector account adds nothing (not the legacy scope).
    service.accounts_changed((grok(SECOND),))
    assert target.protected == frozenset()


def test_dashboard_account_changes_update_protected_grok_scopes(tmp_path, monkeypatch):
    _grok_login(tmp_path)
    seen = {}

    def run(app):
        async def exercise():
            async with app.run_test() as pilot:
                service = next(
                    item for item in app._observers if isinstance(item, cli.KeepaliveService)
                )
                target = service.keepalive.targets[0]
                seen["before"] = target.protected
                await app.accounts_changed((grok(FIRST, "https://auth.x.ai::abc"),))
                seen["after"] = target.protected
                await pilot.press("q")

        asyncio.run(exercise())

    monkeypatch.setattr(cli.UsageApp, "run", run)
    assert cli.main(["--keepalive", "--keepalive-cli", "grok"]) == 0
    assert seen == {"before": frozenset(), "after": frozenset({"https://auth.x.ai::abc"})}


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--api-port", "9000"], "require --api"),
        (["--api-host", "0.0.0.0"], "require --api"),
        (["--allow-origin", "https://app.example.com"], "require --api"),
        (["--trust-proxy"], "require --api"),
        (["--demo", "--keepalive"], "cannot be combined with --demo"),
        (["--keepalive-cli", "codex"], "require --keepalive"),
        (["--keepalive-claude-mode", "status"], "require --keepalive"),
        (["--api", "accounts", "list"], "apply only to the dashboard"),
        (["--keepalive", "api", "serve"], "apply only to the dashboard"),
        (["--keepalive-cli", "codex", "accounts", "list"], "apply only to the dashboard"),
        (
            ["--keepalive-claude-mode", "status", "api", "token", "list"],
            "apply only to the dashboard",
        ),
        (["--demo", "--api", "--api-port", "0"], "--api-port must be"),
        (["--demo", "--api", "--api-host", "bad host"], "--api-host must be"),
        (["--demo", "--api", "--allow-origin", "*"], "--allow-origin must be"),
        (["api", "serve", "--demo", "--keepalive"], "cannot be combined with --demo"),
        (["api", "serve", "--keepalive-cli", "grok"], "require --keepalive"),
        (["--api"], "No API tokens configured"),
        (["--demo", "--api", "--api-host", "0.0.0.0"], "No API tokens configured"),
    ],
)
def test_dashboard_option_validation(monkeypatch, capsys, args, message):
    monkeypatch.setattr(
        cli.UsageApp, "run", lambda app: pytest.fail("TUI must not start after a refusal")
    )
    assert cli.main(args) == 2
    captured = capsys.readouterr()
    assert message in captured.err
    assert "Traceback" not in captured.out + captured.err


def test_dashboard_api_bind_conflict_exits_before_the_tui(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.UsageApp, "run", lambda app: pytest.fail("TUI must not start after a bind error")
    )
    holder = api.bind_socket("127.0.0.1", 0)
    try:
        port = holder.getsockname()[1]
        assert cli.main(["--demo", "--api", "--api-port", str(port)]) == 3
    finally:
        holder.close()
    err = capsys.readouterr().err
    assert "already in use" in err and "--api-port" in err


def test_dashboard_api_composes_with_the_running_app(monkeypatch):
    seen = {}

    def run(app):
        server = next(item for item in app.services if isinstance(item, api.EmbeddedServer))
        seen["server"] = server
        seen["address"] = server.address
        seen["auth"] = server.api.auth_mode
        seen["origins"] = server.api.allowed_origins
        seen["trust_proxy"] = server.api.trust_proxy

    monkeypatch.setattr(cli.UsageApp, "run", run)
    assert (
        cli.main(
            [
                "--demo",
                "--api",
                "--api-host",
                "localhost",
                "--api-port",
                str(_free_port()),
                "--allow-origin",
                "https://APP.example.com:443",
                "--trust-proxy",
            ]
        )
        == 0
    )
    assert seen["address"].startswith("127.0.0.1:")
    assert seen["auth"] == "none"
    assert seen["origins"] == frozenset({"https://app.example.com"})
    assert seen["trust_proxy"] is True
    # The pre-bound socket is closed when the dashboard returns.
    assert seen["server"]._sock.fileno() == -1


def test_live_dashboard_api_with_token(monkeypatch):
    ApiTokenStore().create("live")
    seen = {}

    def run(app):
        seen["mode"] = app.mode
        server = next(item for item in app.services if isinstance(item, api.EmbeddedServer))
        seen["auth"] = server.api.auth_mode
        seen["hub_mode"] = server.api.hub.mode

    monkeypatch.setattr(cli.UsageApp, "run", run)
    assert cli.main(["--api", "--api-port", str(_free_port())]) == 0
    assert seen == {"mode": "live", "auth": "token", "hub_mode": "live"}


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
