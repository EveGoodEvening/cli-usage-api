"""Read-only, token-authenticated HTTP API over published usage snapshots.

The API exposes only nonsecret account metadata and the latest in-memory
snapshot per account; it never manages accounts or reveals credential
references, selectors or organization IDs. Every response is JSON with fixed
error codes and security headers. Request bodies are never read.

Bearer tokens are compared by SHA-256 digest with ``hmac.compare_digest`` over
every stored digest. The token file is re-checked (one no-follow stat at most
once per second) so creation and revocation apply without a restart; a token
file that cannot be read fails closed. A valid token is verified first and
never touches the failed-authentication limiter, so unauthenticated traffic
cannot lock out token holders; only missing or invalid tokens are limited per
client and globally with bounded memory.

An explicitly allowed unauthenticated demo (loopback only, decided by the CLI)
stays open only while the token file is readable and holds zero tokens; creating
a token switches the running server to bearer authentication within a second.

One-process mode (``usage --api``) embeds the same ASGI app in the dashboard's
event loop: ``AppHub`` mirrors the snapshots and account list the TUI shows (so a
TUI session-only credential feeds the API through the one scheduler), and
``EmbeddedServer`` serves it on a pre-bound socket without signal handlers or
terminal logging. The API never starts, stops or reconfigures the scheduler.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import hmac
import ipaddress
import json
import logging
import math
import re
import signal
import socket
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Protocol
from urllib.parse import urlsplit

import uvicorn
from starlette.datastructures import Headers
from starlette.types import Receive, Scope, Send

from cli_usage_api.demo import DemoSource
from cli_usage_api.domain import Account, Snapshot, format_timestamp
from cli_usage_api.scheduler import freshness
from cli_usage_api.storage import (
    API_TOKEN_PREFIX,
    ApiTokenStore,
    ConfigError,
    api_token_digest,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
MAX_PATH_LENGTH = 512
MAX_TOKEN_LENGTH = 256
FAILURE_WINDOW_SECONDS = 60.0
PER_CLIENT_FAILURES = 10
GLOBAL_FAILURES = 100
MAX_TRACKED_CLIENTS = 10_000
TOKEN_RELOAD_SECONDS = 1.0

_ALLOWED_METHODS = "GET, HEAD, OPTIONS"
_SECURITY_HEADERS = (
    (b"cache-control", b"no-store"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
)
_TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_-]+")
_HOST_LABELS = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?")
_ACCOUNT_PATH = "/api/v1/accounts/"


class OriginError(ValueError):
    """A configured CORS origin is not an exact http(s) origin."""


def package_version() -> str:
    try:
        return version("cli-usage-api")
    except PackageNotFoundError:
        return "0.0.0"


def normalize_origin(value: str) -> str:
    """Return the serialized ``scheme://host[:port]`` origin or raise OriginError.

    Scheme and host are lowercased and default ports dropped, matching how
    browsers serialize the Origin header. Paths, queries, fragments, user info,
    wildcards and the opaque ``null`` origin are rejected.
    """
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 2048
        or "*" in value
        or any(ord(char) <= 32 or ord(char) == 127 or char == "\\" for char in value)
    ):
        raise OriginError
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise OriginError from None
    scheme = parts.scheme.lower()
    if (
        scheme not in {"http", "https"}
        or parts.path
        or parts.query
        or parts.fragment
        or "?" in value
        or "#" in value
        or parts.username is not None
        or parts.password is not None
        or "@" in parts.netloc
        or not parts.hostname
    ):
        raise OriginError
    host = parts.hostname.lower()
    if ":" in host:
        try:
            host = f"[{ipaddress.IPv6Address(host).compressed}]"
        except ValueError:
            raise OriginError from None
    elif not _HOST_LABELS.fullmatch(host) or ".." in host or len(host) > 253:
        raise OriginError
    if port is not None and port != {"http": 80, "https": 443}[scheme]:
        if not 1 <= port <= 65535:
            raise OriginError
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def is_loopback_host(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


class Clock(Protocol):
    def __call__(self) -> float: ...


class TokenVerifier:
    """Constant-time digest matching with cheap, fail-closed reload on file change."""

    def __init__(self, store: ApiTokenStore, *, monotonic: Clock = time.monotonic) -> None:
        self._store = store
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._digests: tuple[bytes, ...] = ()
        self._signature: object = object()
        self._checked: float | None = None
        self._empty = False
        self._reload(force=True)

    @property
    def count(self) -> int:
        return len(self._digests)

    def anonymous_allowed(self) -> bool:
        """True only while the token file was read successfully and holds no tokens.

        An unreadable token file is fail-closed, never "no tokens".
        """
        with self._lock:
            self._reload()
            return self._empty

    def _reload(self, *, force: bool = False) -> None:
        now = self._monotonic()
        if not force and self._checked is not None and now - self._checked < TOKEN_RELOAD_SECONDS:
            return
        self._checked = now
        signature = self._store.signature()
        if not force and signature == self._signature:
            return
        try:
            tokens = self._store.load()
        except ConfigError:
            # Fail closed and retry on the next check, even without a new signature.
            self._digests = ()
            self._signature = object()
            self._empty = False
            return
        self._digests = tuple(bytes.fromhex(item.sha256) for item in tokens)
        self._empty = not self._digests
        self._signature = signature

    def verify(self, token: str | None) -> bool:
        with self._lock:
            self._reload()
            digests = self._digests
        presented = bytes.fromhex(api_token_digest(token if isinstance(token, str) else ""))
        matched = False
        for digest in digests:
            matched |= hmac.compare_digest(presented, digest)
        return (
            matched
            and isinstance(token, str)
            and token.startswith(API_TOKEN_PREFIX)
            and len(token) <= MAX_TOKEN_LENGTH
            and _TOKEN_SHAPE.fullmatch(token[len(API_TOKEN_PREFIX) :]) is not None
        )


class FailureLimiter:
    """Sliding-window failed-authentication limits with bounded client tracking."""

    def __init__(
        self,
        *,
        monotonic: Clock = time.monotonic,
        per_client: int = PER_CLIENT_FAILURES,
        global_limit: int = GLOBAL_FAILURES,
        window: float = FAILURE_WINDOW_SECONDS,
        max_clients: int = MAX_TRACKED_CLIENTS,
    ) -> None:
        self._monotonic = monotonic
        self._per_client = per_client
        self._global_limit = global_limit
        self._window = window
        self._max_clients = max_clients
        self._clients: OrderedDict[str, deque[float]] = OrderedDict()
        self._global: deque[float] = deque()

    def _prune(self, events: deque[float], now: float) -> None:
        while events and events[0] <= now - self._window:
            events.popleft()

    def _retry(self, events: deque[float], now: float) -> int:
        return max(1, math.ceil(events[0] + self._window - now))

    def retry_after(self, key: str) -> int | None:
        """Seconds until another attempt is accepted, or None when not limited."""
        now = self._monotonic()
        self._prune(self._global, now)
        events = self._clients.get(key)
        if events is not None:
            self._prune(events, now)
            if not events:
                del self._clients[key]
            elif len(events) >= self._per_client:
                return self._retry(events, now)
        if len(self._global) >= self._global_limit:
            return self._retry(self._global, now)
        return None

    def record(self, key: str) -> None:
        now = self._monotonic()
        events = self._clients.pop(key, None)
        if events is None:
            events = deque()
            while len(self._clients) >= self._max_clients:
                self._clients.popitem(last=False)
        self._prune(events, now)
        events.append(now)
        self._clients[key] = events
        self._global.append(now)
        self._prune(self._global, now)

    @property
    def tracked_clients(self) -> int:
        return len(self._clients)


class SnapshotSource(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class SnapshotHub:
    """Latest published snapshot per configured account, held in memory only.

    The source (live Scheduler or DemoSource) is created on start inside the
    serving event loop and stopped on shutdown. Accounts are fixed at startup.
    """

    def __init__(
        self,
        *,
        mode: str,
        accounts: Iterable[Account],
        source_factory: Callable[[Callable[[Snapshot], None]], SnapshotSource],
        now: Callable[[], datetime] | None = None,
        close: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        if mode not in {"live", "demo"}:
            raise ValueError("Unknown API mode.")
        self.mode = mode
        self.accounts = tuple(accounts)
        self._ids = {account.id for account in self.accounts}
        self._source_factory = source_factory
        self._now = now if now is not None else (lambda: datetime.now(UTC))
        self._close = close
        self.snapshots: dict[str, Snapshot] = {}
        self.source: SnapshotSource | None = None
        self._stopped = False

    def now(self) -> datetime:
        return self._now()

    def publish(self, snapshot: Snapshot) -> None:
        if not self._stopped and snapshot.account_id in self._ids:
            self.snapshots[snapshot.account_id] = snapshot

    async def start(self) -> None:
        if self._stopped:
            raise RuntimeError("Snapshot hub is stopped.")
        if self.source is None:
            self.source = self._source_factory(self.publish)
            await self.source.start()

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        if self.source is not None:
            await self.source.stop()
        if self._close is not None:
            await self._close()


def live_hub(accounts: Sequence[Account], scheduler_factory) -> SnapshotHub:
    """Compose the production scheduler; ``scheduler_factory`` is a cli.LiveFactory."""
    accounts = tuple(accounts)
    return SnapshotHub(
        mode="live",
        accounts=accounts,
        source_factory=lambda publish: scheduler_factory(accounts, publish=publish),
        close=getattr(scheduler_factory, "aclose", None),
    )


def demo_hub(scenario: str = "healthy", *, monotonic: Clock = time.monotonic) -> SnapshotHub:
    """Packaged synthetic data only; no account config, credentials or transport.

    Demo time is the fixture clock, advanced by elapsed process time purely for
    presentation (like the TUI's countdown tick); it never fabricates refreshes.
    """
    source = DemoSource(scenario=scenario, publish=lambda snapshot: hub.publish(snapshot))
    last = [monotonic()]

    def now() -> datetime:
        current = monotonic()
        if current > last[0]:
            source.tick(current - last[0])
            last[0] = current
        return source.clock.now()

    hub = SnapshotHub(
        mode="demo",
        accounts=source.accounts,
        source_factory=lambda publish: source,
        now=now,
    )
    return hub


class AppHub:
    """Mirror of a running dashboard's accounts and accepted snapshots.

    Fed by ``UsageApp`` observer callbacks: ``publish`` for every snapshot the TUI
    accepts and ``accounts_changed`` when accounts are added, edited, removed or
    toggled. Like the TUI, an account change discards held snapshots, so removed
    accounts' observations are not retained. ``start``/``stop`` never touch the
    app's scheduler; stopping only detaches the mirror.
    """

    def __init__(
        self, *, mode: str, accounts: Iterable[Account], now: Callable[[], datetime]
    ) -> None:
        if mode not in {"live", "demo"}:
            raise ValueError("Unknown API mode.")
        self.mode = mode
        self.accounts: tuple[Account, ...] = tuple(accounts)
        self._ids = {account.id for account in self.accounts}
        self._now = now
        self.snapshots: dict[str, Snapshot] = {}
        self._stopped = False

    @classmethod
    def attach(cls, app) -> AppHub:
        """Observe ``app`` (a UsageApp); it must not have started yet."""
        hub = cls(mode=app.mode, accounts=app.accounts, now=app.now)
        for snapshot in app.snapshots.values():
            hub.publish(snapshot)
        app.add_observer(hub)
        return hub

    def now(self) -> datetime:
        return self._now()

    def publish(self, snapshot: Snapshot) -> None:
        if not self._stopped and snapshot.account_id in self._ids:
            self.snapshots[snapshot.account_id] = snapshot

    def accounts_changed(self, accounts: Iterable[Account]) -> None:
        if self._stopped:
            return
        self.accounts = tuple(accounts)
        self._ids = {account.id for account in self.accounts}
        self.snapshots = {}

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self._stopped = True
        self.snapshots = {}


def account_view(hub: SnapshotHub | AppHub, account: Account, now: datetime) -> dict[str, Any]:
    interval = account.effective_poll_interval_seconds
    snapshot = hub.snapshots.get(account.id) if account.enabled else None
    view: dict[str, Any] = {
        "account": {
            "id": account.id,
            "provider": account.provider.value,
            "label": account.label,
            "enabled": account.enabled,
            "credential_kind": (
                None if account.credential_kind is None else account.credential_kind.value
            ),
            "poll_interval_seconds": interval,
        },
        "snapshot": None,
        "freshness": None,
    }
    if snapshot is not None:
        data = snapshot.to_dict()
        data["organization_id"] = None
        view["snapshot"] = data
        view["freshness"] = asdict(freshness(snapshot, now, interval))
    return view


def _client_key(scope: Scope, headers: Headers, trust_proxy: bool) -> str:
    if trust_proxy:
        values = ",".join(headers.getlist("x-forwarded-for"))
        entries = [entry.strip() for entry in values.split(",") if entry.strip()]
        if entries:
            try:
                return ipaddress.ip_address(entries[-1]).compressed
            except ValueError:
                pass
    client = scope.get("client")
    if client and isinstance(client[0], str):
        return client[0]
    return "unknown"


def _bearer(headers: Headers) -> str | None:
    values = headers.getlist("authorization")
    if len(values) != 1:
        return None
    scheme, _, token = values[0].partition(" ")
    if scheme.casefold() != "bearer" or not token or len(token) > MAX_TOKEN_LENGTH:
        return None
    return token.strip(" ") or None


class UsageApi:
    """Single dispatch ASGI application; every response passes through ``_send``."""

    def __init__(
        self,
        hub: SnapshotHub | AppHub,
        *,
        verifier: TokenVerifier | None,
        allowed_origins: Iterable[str] = (),
        trust_proxy: bool = False,
        limiter: FailureLimiter | None = None,
        allow_unauthenticated: bool = False,
    ) -> None:
        if (verifier is None or allow_unauthenticated) and hub.mode != "demo":
            raise ValueError("Live API mode requires token authentication.")
        self.hub = hub
        self.verifier = verifier
        self.allow_unauthenticated = allow_unauthenticated
        self.allowed_origins = frozenset(normalize_origin(item) for item in allowed_origins)
        self.trust_proxy = trust_proxy
        self.limiter = limiter if limiter is not None else FailureLimiter()
        self.version = package_version()
        self.startup_failed = False

    @property
    def auth_mode(self) -> str:
        """Current mode; an allowed unauthenticated demo turns "token" once one exists."""
        return "none" if self._anonymous() else "token"

    def _anonymous(self) -> bool:
        if self.verifier is None:
            return True
        return self.allow_unauthenticated and self.verifier.anonymous_allowed()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
        elif scope["type"] == "http":
            await self._http(scope, send)

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                try:
                    await self.hub.start()
                except Exception:  # noqa: BLE001 - Never log arbitrary source exceptions.
                    self.startup_failed = True
                    await send(
                        {"type": "lifespan.startup.failed", "message": "Usage source failed."}
                    )
                    return
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                with contextlib.suppress(Exception):
                    await self.hub.stop()
                await send({"type": "lifespan.shutdown.complete"})
                return

    def _cors_origin(self, headers: Headers) -> str | None:
        values = headers.getlist("origin")
        if len(values) != 1:
            return None
        try:
            origin = normalize_origin(values[0])
        except OriginError:
            return None
        return values[0] if origin in self.allowed_origins and origin == values[0] else None

    async def _send(
        self,
        send: Send,
        method: str,
        status: int,
        payload: dict[str, Any] | None,
        *,
        origin: str | None = None,
        extra: Sequence[tuple[bytes, bytes]] = (),
    ) -> None:
        body = (
            b""
            if payload is None
            else json.dumps(
                payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
        )
        headers = [*_SECURITY_HEADERS, (b"vary", b"Origin"), *extra]
        if payload is not None:
            headers.append((b"content-type", b"application/json; charset=utf-8"))
        headers.append((b"content-length", str(len(body)).encode("ascii")))
        if origin is not None:
            headers.append((b"access-control-allow-origin", origin.encode("ascii")))
            # Let the frontend read rate-limit and challenge headers cross-origin.
            headers.append((b"access-control-expose-headers", b"Retry-After, WWW-Authenticate"))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": b"" if method == "HEAD" else body})

    async def _http(self, scope: Scope, send: Send) -> None:
        method = scope.get("method", "GET")
        started = False

        async def tracked(message) -> None:
            nonlocal started
            started = True
            await send(message)

        try:
            await self._dispatch(scope, method, tracked)
        except Exception:  # noqa: BLE001 - Curated body; never echo exception text.
            if not started:
                await self._send(send, method, 500, {"error": "internal_error"})

    async def _dispatch(self, scope: Scope, method: str, send: Send) -> None:
        headers = Headers(scope=scope)
        origin = self._cors_origin(headers)
        path = scope.get("path", "")
        raw_path = scope.get("raw_path") or b""
        if method == "OPTIONS":
            if "origin" not in headers:
                await self._send(
                    send, method, 204, None, extra=((b"allow", b"GET, HEAD, OPTIONS"),)
                )
            elif origin is None:
                await self._send(send, method, 403, {"error": "forbidden_origin"})
            else:
                await self._send(
                    send,
                    method,
                    204,
                    None,
                    origin=origin,
                    extra=(
                        (b"access-control-allow-headers", b"Authorization"),
                        (b"access-control-allow-methods", _ALLOWED_METHODS.encode("ascii")),
                        (b"access-control-max-age", b"600"),
                    ),
                )
            return
        if method not in {"GET", "HEAD"}:
            await self._send(
                send,
                method,
                405,
                {"error": "method_not_allowed"},
                origin=origin,
                extra=((b"allow", _ALLOWED_METHODS.encode("ascii")),),
            )
            return
        if len(path) > MAX_PATH_LENGTH or len(raw_path) > MAX_PATH_LENGTH:
            await self._send(send, method, 404, {"error": "not_found"}, origin=origin)
            return
        if path == "/healthz":
            await self._send(send, method, 200, {"status": "ok"}, origin=origin)
            return
        anonymous = self._anonymous()
        # Verify first: a valid token always passes and never consults the
        # limiter, so floods of bad requests cannot lock out token holders.
        if (
            not anonymous
            and self.verifier is not None
            and not self.verifier.verify(_bearer(headers))
        ):
            key = _client_key(scope, headers, self.trust_proxy)
            retry = self.limiter.retry_after(key)
            if retry is not None:
                await self._send(
                    send,
                    method,
                    429,
                    {"error": "rate_limited"},
                    origin=origin,
                    extra=((b"retry-after", str(retry).encode("ascii")),),
                )
                return
            self.limiter.record(key)
            await self._send(
                send,
                method,
                401,
                {"error": "unauthorized"},
                origin=origin,
                extra=((b"www-authenticate", b"Bearer"),),
            )
            return
        payload = self._route(path, "none" if anonymous else "token")
        if payload is None:
            await self._send(send, method, 404, {"error": "not_found"}, origin=origin)
        else:
            await self._send(send, method, 200, payload, origin=origin)

    def _route(self, path: str, auth_mode: str) -> dict[str, Any] | None:
        hub = self.hub
        if path == "/api/v1/session":
            return {
                "mode": hub.mode,
                "version": self.version,
                "server_time": format_timestamp(hub.now()),
                "auth": auth_mode,
            }
        if path == "/api/v1/dashboard":
            now = hub.now()
            return {
                "mode": hub.mode,
                "server_time": format_timestamp(now),
                "accounts": [account_view(hub, account, now) for account in hub.accounts],
            }
        if path.startswith(_ACCOUNT_PATH):
            account_id = path[len(_ACCOUNT_PATH) :]
            for account in hub.accounts:
                if account.id == account_id:
                    return account_view(hub, account, hub.now())
        return None


def create_app(
    hub: SnapshotHub | AppHub,
    token_store: ApiTokenStore | None,
    allowed_origins: Iterable[str] = (),
    *,
    trust_proxy: bool = False,
    limiter: FailureLimiter | None = None,
    monotonic: Clock = time.monotonic,
    allow_unauthenticated: bool = False,
) -> UsageApi:
    """Build the ASGI app.

    ``token_store=None`` means permanently unauthenticated reads (demo only).
    ``allow_unauthenticated=True`` (demo only) serves without authentication
    only while ``token_store`` holds zero tokens, rechecked on reload.
    """
    verifier = None if token_store is None else TokenVerifier(token_store, monotonic=monotonic)
    return UsageApi(
        hub,
        verifier=verifier,
        allowed_origins=allowed_origins,
        trust_proxy=trust_proxy,
        limiter=limiter if limiter is not None else FailureLimiter(monotonic=monotonic),
        allow_unauthenticated=allow_unauthenticated,
    )


class _Server(uvicorn.Server):
    """Graceful SIGINT/SIGTERM shutdown without re-raising the signal afterward.

    Repeated signals do not force-exit: shutdown is already bounded by the
    graceful-shutdown timeout and the scheduler's bounded stop.
    """

    def handle_exit(self, sig, frame) -> None:
        self.should_exit = True

    @contextlib.contextmanager
    def capture_signals(self):
        if threading.current_thread() is not threading.main_thread():
            yield
            return
        handled = (signal.SIGINT, signal.SIGTERM)
        original = {sig: signal.signal(sig, self.handle_exit) for sig in handled}
        try:
            yield
        finally:
            for sig, handler in original.items():
                signal.signal(sig, handler)


class ServeError(RuntimeError):
    """The server or its usage source failed to start; carries no detail."""


class BindError(OSError):
    """The listening socket could not be created; carries no OS detail."""


class AddressInUseError(BindError):
    """The requested host/port is already in use (EADDRINUSE)."""


def bind_socket(host: str, port: int) -> socket.socket:
    """Bind one listening socket for ``host``.

    ``localhost`` is bound explicitly as IPv4 ``127.0.0.1``: resolvers commonly
    list ``::1`` first, and the IPv6 socket is ``IPV6_V6ONLY``, so clients using
    ``127.0.0.1`` could not connect. Use ``--host ::1`` for IPv6 loopback.
    """
    if host.casefold() == "localhost":
        host = "127.0.0.1"
    try:
        infos = socket.getaddrinfo(
            host.strip("[]"), port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE
        )
        family, _, _, _, address = infos[0]
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            sock.bind(address)
            sock.listen(128)
            sock.setblocking(False)
            sock.set_inheritable(True)
        except BaseException:
            sock.close()
            raise
        return sock
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            raise AddressInUseError from None
        raise BindError from None
    except (IndexError, UnicodeError):
        raise BindError from None


async def serve(app: UsageApi, sock: socket.socket, services: Sequence[Any] = ()) -> None:
    """Serve on a pre-bound socket in this loop; always stop the source afterward.

    ``services`` (``async start(None)``/``async stop()``, e.g. keepalive) run in the
    same loop and stop before the usage source.
    """
    config = uvicorn.Config(
        app,
        lifespan="on",
        server_header=False,
        proxy_headers=False,
        access_log=False,
        log_level="warning",
        date_header=True,
        timeout_graceful_shutdown=5,
    )
    server = _Server(config)
    started = []
    try:
        for service in services:
            await service.start(None)
            started.append(service)
        await server.serve(sockets=[sock])
    except SystemExit:
        # uvicorn calls sys.exit(STARTUP_FAILURE) when lifespan startup fails;
        # surface our curated error instead. Any other exit propagates.
        if not app.startup_failed:
            raise
    finally:
        for service in reversed(started):
            with contextlib.suppress(Exception):
                await service.stop()
        sock.close()
        await app.hub.stop()
    if app.startup_failed:
        raise ServeError


def run(app: UsageApi, sock: socket.socket, services: Sequence[Any] = ()) -> None:
    asyncio.run(serve(app, sock, services))


_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi")


def silence_uvicorn_logging() -> None:
    """The TUI owns the terminal: uvicorn records must never reach stderr.

    Without handlers, records would propagate to the root logger and Python's
    last-resort handler would print warnings over the dashboard.
    """
    for name in _UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(handler, logging.NullHandler) for handler in logger.handlers):
            logger.addHandler(logging.NullHandler())
        logger.propagate = False
        logger.setLevel(logging.CRITICAL + 1)


class _EmbeddedUvicorn(uvicorn.Server):
    """No signal handlers: the host app (Textual) owns Ctrl-C and shutdown."""

    @contextlib.contextmanager
    def capture_signals(self):
        yield

    def handle_exit(self, sig, frame) -> None:
        self.should_exit = True


class EmbeddedServer:
    """Serve a ``UsageApi`` as a task in the dashboard's own event loop.

    The socket is bound by the caller before the TUI starts, so bind errors are
    reported before the terminal switches modes. Lifespan is off: the API never
    starts or stops the app's scheduler. A server failure is reported through
    ``on_failure``/the host app's notification, never by crashing the dashboard.
    """

    SHUTDOWN_SECONDS = 3.0

    def __init__(self, app: UsageApi, sock: socket.socket, *, address: str) -> None:
        self.api = app
        self.address = address
        self._sock = sock
        self._server: _EmbeddedUvicorn | None = None
        self._task: asyncio.Task | None = None
        self._stopping = False
        self.failed = False

    @property
    def note(self) -> str:
        if self.failed:
            return f"API {self.address} 已停止"
        if self._task is None or self._stopping:
            return ""
        auth = "无认证（本机演示）" if self.api.auth_mode == "none" else "令牌认证"
        return f"API {self.address} {auth}"

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, host=None) -> None:
        if self._task is not None:
            raise RuntimeError("Embedded API already started.")
        silence_uvicorn_logging()
        config = uvicorn.Config(
            self.api,
            lifespan="off",
            server_header=False,
            proxy_headers=False,
            access_log=False,
            log_config=None,
            log_level="critical",
            date_header=True,
            timeout_graceful_shutdown=2,
        )
        self._server = _EmbeddedUvicorn(config)
        self._task = asyncio.create_task(self._run(host), name="usage-embedded-api")
        # Let the listener attach (create_server on a pre-bound socket is immediate).
        for _ in range(50):
            if self._server.started or self._task.done():
                break
            await asyncio.sleep(0.01)

    async def _run(self, host) -> None:
        try:
            await self._server.serve(sockets=[self._sock])
        except asyncio.CancelledError:
            raise
        except (Exception, SystemExit):  # noqa: BLE001, S110 - uvicorn may sys.exit; never crash.
            pass
        if not self._stopping:
            self.failed = True
            with contextlib.suppress(Exception):
                self._sock.close()
            if host is not None:
                with contextlib.suppress(Exception):
                    host.notify(
                        "只读 API 服务已意外停止；仪表盘继续运行。重启 usage --api 以恢复。",
                        title="API",
                        severity="error",
                        timeout=30,
                    )

    async def stop(self) -> None:
        self._stopping = True
        try:
            if self._server is not None:
                self._server.should_exit = True
            if self._task is not None and not self._task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(self._task), self.SHUTDOWN_SECONDS)
                except TimeoutError:
                    self._server.force_exit = True
                    self._task.cancel()
                    with contextlib.suppress(BaseException):
                        await self._task
        finally:
            self._sock.close()
            await self.api.hub.stop()
