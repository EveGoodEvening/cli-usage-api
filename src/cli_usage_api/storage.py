"""Private POSIX account configuration and explicitly secure secret storage.

No backend is consulted for session-only credentials. Persistent secrets use the
Linux Secret Service backend exclusively; backend errors never fall back to disk
or memory. Python strings cannot provide memory-zeroization guarantees.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import keyring
from keyring.backends.SecretService import Keyring as SecretServiceKeyring

from cli_usage_api.domain import (
    Account,
    CredentialKind,
    DomainError,
    ProviderId,
    format_timestamp,
    parse_timestamp,
    sanitize_text,
)

MAX_FILE_BYTES = 1_048_576
_SERVICE = "cli-usage-api"
_SECURE_BACKEND_TYPES = (SecretServiceKeyring,)
_FILE_KINDS = {
    CredentialKind.CLAUDE_CODE_FILE,
    CredentialKind.GROK_AUTH_FILE,
    CredentialKind.CODEX_AUTH_FILE,
}


class ConfigError(ValueError):
    """A safe configuration failure, without paths or file contents."""


class ConfigCommittedError(ConfigError):
    """Replacement committed, but crash durability could not be confirmed."""

    def __init__(self, accounts: tuple[Account, ...]) -> None:
        super().__init__(
            "Account configuration changed, but crash durability could not be confirmed."
        )
        self.accounts = accounts


class CredentialError(ValueError):
    """A safe credential failure, without secrets or backend exception text."""


def _config_error() -> ConfigError:
    return ConfigError(
        "Cannot use local configuration. Check its schema and user-owned "
        "0700 directory / 0600 regular files; configuration was not repaired automatically."
    )


def _migration_error() -> ConfigError:
    return ConfigError(
        "Legacy ChatGPT profiles require explicit migration. Run "
        "usage accounts migrate-chatgpt-to-codex, then configure a file-backed Codex login. "
        "Migration disables profiles and detaches credentials; old keyring secrets are retained."
    )


def _credential_error() -> CredentialError:
    return CredentialError(
        "Credential unavailable. Unlock and select the Linux Secret Service keyring, "
        "or explicitly use session-only storage and reconnect."
    )


def _uuid(value: str) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, AttributeError, TypeError):
        return False


def _reference(ref: str) -> tuple[str, ...]:
    if not isinstance(ref, str):
        raise _credential_error()
    parts = tuple(ref.split(":"))
    if len(parts) == 2 and parts[0] == "session" and _uuid(parts[1]):
        return parts
    if len(parts) == 3 and parts[0] == "keyring" and all(_uuid(p) for p in parts[1:]):
        return parts
    raise _credential_error()


def _accounts(value: object) -> tuple[Account, ...]:
    if type(value) is not tuple or not all(isinstance(item, Account) for item in value):
        raise _config_error()
    if len({item.id for item in value}) != len(value):
        raise _config_error()
    for item in value:
        if item.credential_ref is None:
            continue
        if item.credential_kind in _FILE_KINDS:
            if any(ord(char) < 32 or ord(char) == 127 for char in item.credential_ref):
                raise _config_error()
        else:
            try:
                parts = _reference(item.credential_ref)
            except CredentialError:
                raise _config_error() from None
            if parts[0] == "keyring" and parts[1] != item.id:
                raise _config_error()
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _config_error()
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise _config_error()


class _ConfigFile:
    """Shared private file I/O; callers own schema and commit-error semantics."""

    def __init__(self, path: str | Path | None, filename: str) -> None:
        if path is None:
            root = os.environ.get("XDG_CONFIG_HOME")
            base = Path(root) if root and Path(root).is_absolute() else Path.home() / ".config"
            path = base / "cli-usage-api" / filename
        self.path = Path(os.path.abspath(path))
        self._thread_lock = threading.RLock()

    @contextmanager
    def _directory(self) -> Iterator[int]:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            # Walk with directory descriptors so ancestor symlinks are not followed.
            for component in self.path.parent.parts[1:]:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise _config_error()
            yield fd
        finally:
            os.close(fd)

    @staticmethod
    def _check_file(fd: int) -> None:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or info.st_size > MAX_FILE_BYTES
        ):
            raise _config_error()

    @contextmanager
    def _locked(self) -> Iterator[int]:
        try:
            with self._thread_lock, self._directory() as directory:
                fd = os.open(
                    f".{self.path.name}.lock",
                    os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                    0o600,
                    dir_fd=directory,
                )
                try:
                    self._check_file(fd)
                    fcntl.flock(fd, fcntl.LOCK_EX)
                    yield directory
                finally:
                    os.close(fd)
        except OSError:
            raise _config_error() from None

    def _read_content(self, directory: int) -> bytes | None:
        try:
            fd = os.open(
                self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
        except FileNotFoundError:
            return None
        try:
            self._check_file(fd)
            with os.fdopen(fd, "rb", closefd=False) as source:
                content = source.read(MAX_FILE_BYTES + 1)
            if len(content) > MAX_FILE_BYTES:
                raise _config_error()
        finally:
            os.close(fd)
        return content

    def _replace(self, directory: int, content: bytes) -> None:
        temporary = f".{self.path.name}.{uuid4()}.tmp"
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        try:
            with os.fdopen(fd, "wb", closefd=False) as target:
                target.write(content)
                target.flush()
                os.fsync(fd)
            os.replace(temporary, self.path.name, src_dir_fd=directory, dst_dir_fd=directory)
        finally:
            os.close(fd)
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass


class AccountStore(_ConfigFile):
    """Version-one account config; mutate is the read/modify/write transaction.

    A stable sibling lock inode is held across reread and same-directory replace.
    Callbacks must be synchronous and return a tuple; callback exceptions leave
    configuration unchanged. ConfigCommittedError reports replacement with uncertain
    crash durability. save also refuses to overwrite an invalid config.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(path, "accounts.json")

    def _read_config(
        self, directory: int
    ) -> tuple[tuple[Account, ...], tuple[tuple[str, str], ...]]:
        content = self._read_content(directory)
        if content is None:
            return (), ()
        try:
            data = json.loads(
                content, object_pairs_hook=_unique_object, parse_constant=_reject_constant
            )
            if (
                type(data) is not dict
                or set(data) != {"schema_version", "accounts"}
                or type(data["schema_version"]) is not int
                or data["schema_version"] != 1
                or type(data["accounts"]) is not list
            ):
                raise _config_error()
            accounts = []
            legacy = []
            for record in data["accounts"]:
                if type(record) is dict and record.get("provider") == "chatgpt_subscription":
                    # Validate the historical shape with ordinary domain/reference rules,
                    # without exposing a legacy provider or allowing its secrets into Codex.
                    if record.get("credential_kind") not in (
                        None,
                        CredentialKind.MANUAL_BEARER,
                        CredentialKind.API_KEY,
                    ):
                        raise _config_error()
                    old = Account.from_dict({**record, "provider": ProviderId.CLAUDE_SUBSCRIPTION})
                    _accounts((old,))
                    legacy.append((old.id, old.label))
                    accounts.append(
                        replace(
                            old,
                            provider=ProviderId.CODEX_SUBSCRIPTION,
                            enabled=False,
                            credential_kind=None,
                            credential_ref=None,
                            credential_selector=None,
                            organization_id=None,
                        )
                    )
                else:
                    accounts.append(Account.from_dict(record))
            return _accounts(tuple(accounts)), tuple(legacy)
        except (ValueError, TypeError, RecursionError, UnicodeError):
            raise _config_error() from None

    def _read(self, directory: int) -> tuple[Account, ...]:
        accounts, legacy = self._read_config(directory)
        if legacy:
            raise _migration_error()
        return accounts

    def legacy_chatgpt_profiles(self) -> tuple[tuple[str, str], ...]:
        """List validated local migration targets without accessing credentials."""
        with self._locked() as directory:
            _, legacy = self._read_config(directory)
            return legacy

    def migrate_legacy_chatgpt_to_codex(
        self, *, confirmed_account_ids: tuple[str, ...]
    ) -> tuple[Account, ...]:
        """Detach and disable the complete explicitly confirmed legacy profile set.

        Old keyring entries remain retained and unmanaged. No credential backend or
        imported file is accessed. ConfigCommittedError carries committed accounts
        when replacement succeeded but directory durability could not be confirmed.
        """
        with self._locked() as directory:
            accounts, legacy = self._read_config(directory)
            if (
                type(confirmed_account_ids) is not tuple
                or not all(isinstance(item, str) for item in confirmed_account_ids)
                or len(set(confirmed_account_ids)) != len(confirmed_account_ids)
                or set(confirmed_account_ids) != {item[0] for item in legacy}
            ):
                raise ConfigError(
                    "Legacy profile selection changed. List profiles and confirm again."
                )
            if legacy:
                self._write(directory, accounts)
            return accounts

    def _write(self, directory: int, accounts: tuple[Account, ...]) -> None:
        accounts = _accounts(accounts)
        try:
            content = json.dumps(
                {"schema_version": 1, "accounts": [item.to_dict() for item in accounts]},
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (ValueError, UnicodeError):
            raise _config_error() from None
        if len(content) > MAX_FILE_BYTES:
            raise _config_error()
        self._replace(directory, content)
        try:
            os.fsync(directory)
        except OSError:
            raise ConfigCommittedError(accounts) from None

    def load(self) -> tuple[Account, ...]:
        with self._locked() as directory:
            return self._read(directory)

    def save(self, accounts: tuple[Account, ...]) -> None:
        with self._locked() as directory:
            self._read(directory)
            self._write(directory, accounts)

    def mutate(
        self, change: Callable[[tuple[Account, ...]], tuple[Account, ...]]
    ) -> tuple[Account, ...]:
        with self._locked() as directory:
            accounts = change(self._read(directory))
            self._write(directory, accounts)
            return accounts


class SettingsStore(_ConfigFile):
    """Nonsecret UI preferences, independent of accounts and credential stores."""

    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(path, "settings.json")

    @staticmethod
    def _theme(value: object) -> str:
        if not isinstance(value, str) or not 1 <= len(value) <= 128:
            raise _config_error()
        return value

    def _read(self, directory: int) -> str | None:
        content = self._read_content(directory)
        if content is None:
            return None
        try:
            data = json.loads(
                content, object_pairs_hook=_unique_object, parse_constant=_reject_constant
            )
            if (
                type(data) is not dict
                or set(data) != {"schema_version", "theme"}
                or type(data["schema_version"]) is not int
                or data["schema_version"] != 1
            ):
                raise _config_error()
            return self._theme(data["theme"])
        except (ValueError, TypeError, RecursionError, UnicodeError):
            raise _config_error() from None

    def load_theme(self) -> str | None:
        with self._locked() as directory:
            return self._read(directory)

    def save_theme(self, theme: str) -> None:
        theme = self._theme(theme)
        content = json.dumps({"schema_version": 1, "theme": theme}).encode("utf-8")
        with self._locked() as directory:
            self._read(directory)
            self._replace(directory, content)
            os.fsync(directory)


class CredentialStore:
    """Opaque secret references; injected backends face the same exact-type policy.

    Session references are scoped to this instance and never contact a keyring.
    Persistent references survive instances, but carry neither secrets nor suffixes.
    Every put mints a fresh reference and never reuses one, so a secret never
    changes behind an unchanged reference; callers remove the old one after saving.
    ``_lock`` guards only the session dict: keyring backends serialize themselves,
    and a slow or blocked backend call must not delay session reads.
    """

    def __init__(self, backend: object | None = None) -> None:
        self._backend = backend
        self._session: dict[str, str] = {}
        self._lock = threading.RLock()

    def _secure_backend(self) -> object:
        try:
            backend = self._backend if self._backend is not None else keyring.get_keyring()
            if sys.platform != "linux" or type(backend) not in _SECURE_BACKEND_TYPES:
                raise _credential_error()
            return backend
        except Exception:  # noqa: BLE001 - Redact arbitrary backend errors.
            raise _credential_error() from None

    def secure_available(self) -> bool:
        """Whether the exact secure backend type is selected; stores nothing, never falls back.

        This reflects only the backend type, so a later persistent put can still fail.
        """
        try:
            self._secure_backend()
        except Exception:  # noqa: BLE001 - Any backend failure means unavailable.
            return False
        return True

    def session_present(self, ref: object) -> bool:
        if not isinstance(ref, str) or not ref.startswith("session:"):
            return False
        with self._lock:
            return ref in self._session

    def put(self, account_id: str, secret: str, *, persist: bool) -> str:
        if (
            not _uuid(account_id)
            or not isinstance(secret, str)
            or not secret
            or len(secret) > MAX_FILE_BYTES
            or type(persist) is not bool
        ):
            raise _credential_error()
        if not persist:
            ref = f"session:{uuid4()}"
            with self._lock:
                self._session[ref] = secret
            return ref
        ref = f"keyring:{account_id}:{uuid4()}"
        try:
            self._secure_backend().set_password(_SERVICE, ref, secret)
        except Exception:  # noqa: BLE001 - Redact arbitrary backend errors.
            raise _credential_error() from None
        return ref

    def get(self, ref: str) -> str:
        parts = _reference(ref)
        if parts[0] == "session":
            with self._lock:
                secret = self._session.get(ref)
        else:
            try:
                secret = self._secure_backend().get_password(_SERVICE, ref)
            except Exception:  # noqa: BLE001 - Redact arbitrary backend errors.
                raise _credential_error() from None
        if not isinstance(secret, str) or not secret or len(secret) > MAX_FILE_BYTES:
            raise _credential_error()
        return secret

    def delete(self, ref: str) -> None:
        parts = _reference(ref)
        if parts[0] == "session":
            with self._lock:
                self._session.pop(ref, None)
            return
        try:
            backend = self._secure_backend()
            if backend.get_password(_SERVICE, ref) is not None:
                backend.delete_password(_SERVICE, ref)
        except Exception:  # noqa: BLE001 - Redact arbitrary backend errors.
            raise _credential_error() from None


API_TOKEN_PREFIX = "usk_"
MAX_API_TOKENS = 100
_TOKEN_ID = re.compile(r"[0-9a-f]{32}")
_TOKEN_HASH = re.compile(r"[0-9a-f]{64}")


class ApiTokenLimitError(ConfigError):
    """The token file already holds MAX_API_TOKENS tokens; nothing was written."""


def api_token_digest(token: str) -> str:
    """SHA-256 hex digest of a presented bearer token; only digests are ever stored."""
    return hashlib.sha256(token.encode("utf-8", "surrogatepass")).hexdigest()


@dataclass(frozen=True, slots=True)
class ApiToken:
    """Nonsecret API token metadata. The token itself is never stored or recoverable."""

    id: str
    label: str
    sha256: str
    created_at: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, str)
            or not _TOKEN_ID.fullmatch(self.id)
            or not isinstance(self.sha256, str)
            or not _TOKEN_HASH.fullmatch(self.sha256)
            or not isinstance(self.label, str)
            or not 1 <= len(self.label) <= 80
            or sanitize_text(self.label, max_length=80) != self.label
        ):
            raise _config_error()
        try:
            if format_timestamp(parse_timestamp(self.created_at)) != self.created_at:
                raise _config_error()
        except DomainError:
            raise _config_error() from None


class ApiTokenStore(_ConfigFile):
    """Private API bearer-token digests beside the account configuration.

    The file holds only SHA-256 digests plus nonsecret metadata, using the shared
    private, locked and atomically replaced file primitives. signature() is a cheap
    no-follow stat so a running server can reload after creation or revocation.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(path, "api_tokens.json")

    def _read(self, directory: int) -> tuple[ApiToken, ...]:
        content = self._read_content(directory)
        if content is None:
            return ()
        try:
            data = json.loads(
                content, object_pairs_hook=_unique_object, parse_constant=_reject_constant
            )
            if (
                type(data) is not dict
                or set(data) != {"schema_version", "tokens"}
                or type(data["schema_version"]) is not int
                or data["schema_version"] != 1
                or type(data["tokens"]) is not list
                or len(data["tokens"]) > MAX_API_TOKENS
            ):
                raise _config_error()
            tokens = []
            for record in data["tokens"]:
                if type(record) is not dict or set(record) != {
                    "id",
                    "label",
                    "sha256",
                    "created_at",
                }:
                    raise _config_error()
                tokens.append(ApiToken(**record))
        except (ValueError, TypeError, RecursionError, UnicodeError):
            raise _config_error() from None
        if len({item.id for item in tokens}) != len(tokens) or len(
            {item.sha256 for item in tokens}
        ) != len(tokens):
            raise _config_error()
        return tuple(tokens)

    def _write(self, directory: int, tokens: tuple[ApiToken, ...]) -> None:
        content = json.dumps(
            {
                "schema_version": 1,
                "tokens": [
                    {
                        "id": item.id,
                        "label": item.label,
                        "sha256": item.sha256,
                        "created_at": item.created_at,
                    }
                    for item in tokens
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self._replace(directory, content)
        os.fsync(directory)

    def load(self) -> tuple[ApiToken, ...]:
        with self._locked() as directory:
            return self._read(directory)

    def signature(self) -> tuple[int, ...] | None:
        """Identify the current file version without reading it; None when absent."""
        try:
            info = os.stat(self.path, follow_symlinks=False)
        except FileNotFoundError:
            return None
        except OSError:
            return (-1,)
        return (info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_size, info.st_mode)

    def create(self, label: str | None = None) -> tuple[str, ApiToken]:
        """Generate a token, persist only its digest and return the token once."""
        label = sanitize_text(label or "", max_length=80) or "token"
        token = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
        record = ApiToken(
            id=uuid4().hex,
            label=label,
            sha256=api_token_digest(token),
            created_at=format_timestamp(datetime.now(UTC).replace(microsecond=0)),
        )
        with self._locked() as directory:
            tokens = self._read(directory)
            if len(tokens) >= MAX_API_TOKENS:
                raise ApiTokenLimitError(
                    f"At most {MAX_API_TOKENS} API tokens are supported; revoke unused tokens."
                )
            self._write(directory, (*tokens, record))
        return token, record

    def revoke(self, token_id: str) -> bool:
        """Remove one token by ID; False when no such token exists."""
        with self._locked() as directory:
            tokens = self._read(directory)
            kept = tuple(item for item in tokens if item.id != token_id)
            if len(kept) == len(tokens):
                return False
            self._write(directory, kept)
            return True
