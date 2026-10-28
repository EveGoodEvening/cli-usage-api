"""Private POSIX account configuration and explicitly secure secret storage.

No backend is consulted for session-only credentials. Persistent secrets use the
Linux Secret Service backend exclusively; backend errors never fall back to disk
or memory. Python strings cannot provide memory-zeroization guarantees.
"""

from __future__ import annotations

import fcntl
import json
import os
import stat
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import keyring
from keyring.backends.SecretService import Keyring as SecretServiceKeyring

from usage_tui.domain import Account, CredentialKind, ProviderId

MAX_FILE_BYTES = 1_048_576
_SERVICE = "usage-tui"
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
        "Cannot use account configuration. Check its schema and user-owned "
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


class AccountStore:
    """Version-one account config; mutate is the read/modify/write transaction.

    A stable sibling lock inode is held across reread and same-directory replace.
    Callbacks must be synchronous and return a tuple; callback exceptions leave
    configuration unchanged. ConfigCommittedError reports replacement with uncertain
    crash durability. save also refuses to overwrite an invalid config.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            root = os.environ.get("XDG_CONFIG_HOME")
            base = Path(root) if root and Path(root).is_absolute() else Path.home() / ".config"
            path = base / "usage-tui" / "accounts.json"
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

    def _read_config(
        self, directory: int
    ) -> tuple[tuple[Account, ...], tuple[tuple[str, str], ...]]:
        try:
            fd = os.open(
                self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
        except FileNotFoundError:
            return (), ()
        try:
            self._check_file(fd)
            with os.fdopen(fd, "rb", closefd=False) as source:
                content = source.read(MAX_FILE_BYTES + 1)
            if len(content) > MAX_FILE_BYTES:
                raise _config_error()
        finally:
            os.close(fd)
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
            try:
                os.fsync(directory)
            except OSError:
                raise ConfigCommittedError(accounts) from None
        finally:
            os.close(fd)
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass

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


class CredentialStore:
    """Opaque secret references; injected backends face the same exact-type policy.

    Session references are scoped to this instance and never contact a keyring.
    Persistent references survive instances, but carry neither secrets nor suffixes.
    Replacement creates a new reference; callers remove the old one after saving.
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

    def put(self, account_id: str, secret: str, *, persist: bool) -> str:
        if (
            not _uuid(account_id)
            or not isinstance(secret, str)
            or not secret
            or len(secret) > MAX_FILE_BYTES
            or type(persist) is not bool
        ):
            raise _credential_error()
        with self._lock:
            if not persist:
                ref = f"session:{uuid4()}"
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
        with self._lock:
            if parts[0] == "session":
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
        with self._lock:
            if parts[0] == "session":
                self._session.pop(ref, None)
                return
            try:
                backend = self._secure_backend()
                if backend.get_password(_SERVICE, ref) is not None:
                    backend.delete_password(_SERVICE, ref)
            except Exception:  # noqa: BLE001 - Redact arbitrary backend errors.
                raise _credential_error() from None
