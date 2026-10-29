"""All first-party files and identities below are synthetic and temporary."""

import base64
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from usage_tui.credentials import MAX_FILE_BYTES, CredentialResolutionError, CredentialResolver
from usage_tui.domain import Account, CredentialKind, FetchState, ProviderId
from usage_tui.storage import CredentialStore

NOW = datetime(2026, 10, 28, tzinfo=UTC)
FUTURE = datetime(2030, 1, 1, tzinfo=UTC)
ACCOUNT_ID = "00000000-0000-0000-0000-000000000001"
SCOPE = "https://auth.x.ai::synthetic-client"
LEGACY = "https://accounts.x.ai/sign-in"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("GROK_HOME", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)


@pytest.fixture
def samples():
    return json.loads((Path(__file__).parent / "fixtures" / "credentials.json").read_text())


def imported(tmp_path, data, *, grok=False, selector=None):
    path = tmp_path / "synthetic-auth.json"
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    return Account(
        ACCOUNT_ID,
        ProviderId.GROK_SUBSCRIPTION if grok else ProviderId.CLAUDE_SUBSCRIPTION,
        "Synthetic account",
        str(path),
        CredentialKind.GROK_AUTH_FILE if grok else CredentialKind.CLAUDE_CODE_FILE,
        credential_selector=selector,
    )


def resolver(store=None):
    return CredentialResolver(store, clock=lambda: NOW)


def assert_error(account, code, *, store=None, state=None):
    with pytest.raises(CredentialResolutionError) as captured:
        resolver(store).resolve(account)
    error = captured.value
    assert error.code == code
    assert error.diagnostic.code == code
    if state is not None:
        assert error.fetch_state == state
    assert "synthetic-" not in str(error)
    assert str(account.credential_ref) not in str(error)
    return error


def test_claude_readonly_capture_and_generation(tmp_path, samples):
    account = imported(tmp_path, samples["claude"])
    path = Path(account.credential_ref)
    before = path.read_bytes()
    instance = resolver()
    first = instance.resolve(account)
    assert first.provider == account.provider
    assert first.credential_kind == CredentialKind.CLAUDE_CODE_FILE
    assert first.secret == "synthetic-claude-access-only"
    assert first.expires_at == FUTURE
    assert first.user_id is None
    assert first.generation_fingerprint == instance.resolve(account).generation_fingerprint
    assert first.secret not in repr(first)
    assert first.generation_fingerprint not in repr(first)
    assert "synthetic-refresh" not in repr(first)
    assert path.read_bytes() == before
    assert path.stat().st_mode & 0o777 == 0o600
    samples["claude"]["claudeAiOauth"]["accessToken"] = "synthetic-replacement"
    path.write_text(json.dumps(samples["claude"]))
    second = instance.resolve(account)
    assert first.secret == "synthetic-claude-access-only"
    assert second.secret == "synthetic-replacement"
    assert second.generation_fingerprint != first.generation_fingerprint


@pytest.mark.parametrize(
    "provider,kind,env,directory,filename,sample",
    [
        (
            ProviderId.CLAUDE_SUBSCRIPTION,
            CredentialKind.CLAUDE_CODE_FILE,
            "CLAUDE_CONFIG_DIR",
            ".claude",
            ".credentials.json",
            "claude",
        ),
        (
            ProviderId.GROK_SUBSCRIPTION,
            CredentialKind.GROK_AUTH_FILE,
            "GROK_HOME",
            ".grok",
            "auth.json",
            "grok",
        ),
    ],
)
@pytest.mark.parametrize("override", [False, True])
def test_default_paths(
    tmp_path, monkeypatch, samples, provider, kind, env, directory, filename, sample, override
):
    root = tmp_path / ("synthetic-override" if override else directory)
    root.mkdir()
    path = root / filename
    path.write_text(json.dumps(samples[sample]))
    path.chmod(0o600)
    if override:
        monkeypatch.setenv(env, str(root))
    account = Account(ACCOUNT_ID, provider, "Synthetic", "default", kind)
    assert resolver().resolve(account).expires_at == FUTURE


def test_constructing_resolver_performs_no_io(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("construction must not probe external files or stores")

    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(Path, "home", forbidden)
    CredentialResolver()


@pytest.mark.parametrize(
    "scopes,code",
    [
        ([], "permission_denied"),
        (["user:inference"], "permission_denied"),
        ("user:profile", "schema_error"),
        ([True], "schema_error"),
        (None, "schema_error"),
    ],
)
def test_claude_scope_check(tmp_path, samples, scopes, code):
    samples["claude"]["claudeAiOauth"]["scopes"] = scopes
    assert_error(imported(tmp_path, samples["claude"]), code)


def test_absent_scope_and_expiry_remain_unknown(tmp_path):
    account = imported(tmp_path, {"claudeAiOauth": {"accessToken": "synthetic-access"}})
    assert resolver().resolve(account).expires_at is None


@pytest.mark.parametrize(
    "value,code",
    [
        (0, "schema_error"),
        (-1, "schema_error"),
        (True, "schema_error"),
        ("2030-01-01T00:00:00Z", "schema_error"),
        (int(NOW.timestamp() * 1000), "credential_expired"),
        (1, "credential_expired"),
    ],
)
def test_claude_expiry(tmp_path, samples, value, code):
    samples["claude"]["claudeAiOauth"]["expiresAt"] = value
    assert_error(imported(tmp_path, samples["claude"]), code)


def test_grok_modern_preference_and_explicit_legacy(tmp_path, samples):
    account = imported(tmp_path, samples["grok"], grok=True)
    result = resolver().resolve(account)
    assert result.secret == "synthetic-grok-access-only"
    assert result.user_id == "synthetic-user"
    assert result.expires_at == FUTURE
    assert result.provider == ProviderId.GROK_SUBSCRIPTION
    legacy = resolver().resolve(replace(account, credential_selector=LEGACY))
    assert legacy.secret == "synthetic-legacy-access"
    assert legacy.user_id == "synthetic-legacy-user"


def test_grok_ambiguous_profiles_require_exact_selector(tmp_path, samples):
    samples["grok"]["https://auth.x.ai::other-client"] = {"key": "synthetic-other"}
    account = imported(tmp_path, samples["grok"], grok=True)
    assert_error(account, "credential_selection_required")
    assert (
        resolver().resolve(replace(account, credential_selector=SCOPE)).user_id == "synthetic-user"
    )
    for selector in ("synthetic-client", "https://auth.x.ai::missing", "https://evil.invalid"):
        assert_error(
            replace(account, credential_selector=selector), "credential_selection_required"
        )


def test_grok_only_legacy_and_unknown_scopes(tmp_path, samples):
    account = imported(tmp_path, {LEGACY: samples["grok"][LEGACY]}, grok=True)
    assert resolver().resolve(account).secret == "synthetic-legacy-access"
    account = imported(tmp_path, {"https://auth.x.ai::": {"key": "synthetic-invalid"}}, grok=True)
    assert_error(account, "credential_selection_required")


@pytest.mark.parametrize("value", ["2030-01-01T02:00:00+02:00", 1893456000, 1893456000000])
def test_grok_expiry_formats(tmp_path, value):
    account = imported(tmp_path, {SCOPE: {"key": "synthetic-key", "expires_at": value}}, grok=True)
    assert resolver().resolve(account).expires_at == FUTURE


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2030-01-01T00:00:00.1234567Z", FUTURE.replace(microsecond=123456)),
        ("2030-01-01T02:00:00.12345678+02:00", FUTURE.replace(microsecond=123456)),
        ("2030-01-01t00:00:00.123456789z", FUTURE.replace(microsecond=123456)),
        ("2030-01-01T00:00:00.999999999Z", FUTURE.replace(microsecond=999999)),
        ("2030-01-01T00:00:00.000000000Z", FUTURE),
        ("9999-12-31T23:59:59.999999999Z", datetime.max.replace(tzinfo=UTC)),
    ],
)
def test_grok_nanosecond_expiry_floors_without_rewriting_file(tmp_path, value, expected):
    account = imported(
        tmp_path,
        {SCOPE: {"key": "synthetic-key", "expires_at": value, "refresh_token": "synthetic-unused"}},
        grok=True,
    )
    path = Path(account.credential_ref)
    before = path.read_bytes()
    result = resolver().resolve(account)
    assert result.expires_at == expected
    assert result.secret == "synthetic-key"
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "value",
    [
        "2030-01-01T00:00:00.1234567890Z",
        "2030-01-01T00:00:00.123456789",
        "2030-01-01T00:00:00.123456789+24:00",
        "2030-02-30T00:00:00.123456789Z",
        "2030-01-01T00:00:00.123456789Z trailing",
        "2030-01-01T00:00:60.123456789Z",
    ],
)
def test_grok_nanosecond_support_does_not_accept_invalid_dates(tmp_path, value):
    account = imported(tmp_path, {SCOPE: {"key": "synthetic-key", "expires_at": value}}, grok=True)
    assert_error(account, "schema_error")


def test_grok_submicrosecond_expiry_cannot_extend_lifetime(tmp_path):
    account = imported(
        tmp_path,
        {SCOPE: {"key": "synthetic-key", "expires_at": "2030-01-01T00:00:00.123456789Z"}},
        grok=True,
    )
    instance = CredentialResolver(clock=lambda: FUTURE.replace(microsecond=123456))
    with pytest.raises(CredentialResolutionError) as caught:
        instance.resolve(account)
    assert caught.value.code == "credential_expired"


@pytest.mark.parametrize(
    "value",
    [True, -1, 0, "2030-01-01", "2030-01-01T00:00:00", [], float("inf"), 10**1000],
)
def test_grok_invalid_expiry(tmp_path, value):
    account = imported(tmp_path, {SCOPE: {"key": "synthetic-key", "expires_at": value}}, grok=True)
    assert_error(account, "schema_error")


def test_grok_expired_and_absent_expiry(tmp_path):
    account = imported(
        tmp_path,
        {SCOPE: {"key": "synthetic-key", "expires_at": "2020-01-01T00:00:00Z"}},
        grok=True,
    )
    assert_error(account, "credential_expired")
    account = imported(tmp_path, {SCOPE: {"key": "synthetic-key"}}, grok=True)
    result = resolver().resolve(account)
    assert result.expires_at is None
    assert result.user_id is None


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {},
        {"claudeAiOauth": []},
        {"claudeAiOauth": {"accessToken": ""}},
        {"claudeAiOauth": {"accessToken": "synthetic\nkey"}},
        {"claudeAiOauth": {"accessToken": True}},
    ],
)
def test_malformed_claude_schema(tmp_path, data):
    assert_error(imported(tmp_path, data), "schema_error")


@pytest.mark.parametrize(
    "raw",
    [
        b"not json synthetic-private",
        b"\xff",
        b'{"claudeAiOauth":{},"claudeAiOauth":{}}',
        b"[" * 2000,
    ],
)
def test_malformed_json_is_safe(tmp_path, raw):
    account = imported(tmp_path, {})
    Path(account.credential_ref).write_bytes(raw)
    assert_error(account, "schema_error")


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o660, 0o400, 0o700, 0o4600])
def test_import_requires_exact_private_mode(tmp_path, samples, mode):
    account = imported(tmp_path, samples["claude"])
    path = Path(account.credential_ref)
    path.chmod(mode)
    assert_error(account, "unsafe_credential_file")
    assert path.stat().st_mode & 0o7777 == mode


def test_unsafe_descriptor_is_not_read(tmp_path, samples, monkeypatch):
    account = imported(tmp_path, samples["claude"])
    Path(account.credential_ref).chmod(0o644)

    def forbidden(*args):
        pytest.fail("unsafe descriptor must not be read")

    monkeypatch.setattr(os, "read", forbidden)
    assert_error(account, "unsafe_credential_file")


def test_import_rejects_other_owner(tmp_path, samples, monkeypatch):
    account = imported(tmp_path, samples["claude"])
    monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)
    assert_error(account, "unsafe_credential_file")


def test_import_rejects_nonregular_symlink_and_missing(tmp_path, samples):
    account = imported(tmp_path, samples["claude"])
    link = tmp_path / "link"
    link.symlink_to(account.credential_ref)
    assert_error(replace(account, credential_ref=str(link)), "unsafe_credential_file")
    directory = tmp_path / "directory"
    directory.mkdir(mode=0o700)
    assert_error(replace(account, credential_ref=str(directory)), "unsafe_credential_file")
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo, 0o600)
    assert_error(replace(account, credential_ref=str(fifo)), "unsafe_credential_file")
    assert_error(
        replace(account, credential_ref=str(tmp_path / "missing")), "credential_unavailable"
    )


def test_import_size_limit_and_no_mutation(tmp_path):
    account = imported(tmp_path, {})
    path = Path(account.credential_ref)
    path.write_bytes(b" " * (MAX_FILE_BYTES + 1))
    assert_error(account, "unsafe_credential_file")
    assert path.stat().st_size == MAX_FILE_BYTES + 1


def test_import_checks_descriptor_again_after_read(tmp_path, samples, monkeypatch):
    account = imported(tmp_path, samples["claude"])
    original = os.fstat
    calls = 0

    def changed(fd):
        nonlocal calls
        value = original(fd)
        calls += 1
        if calls == 1:
            return value
        return SimpleNamespace(
            st_size=value.st_size + 1,
            st_mtime_ns=value.st_mtime_ns,
            st_ctime_ns=value.st_ctime_ns,
            st_mode=value.st_mode,
            st_uid=value.st_uid,
        )

    monkeypatch.setattr(os, "fstat", changed)
    assert_error(account, "unsafe_credential_file")


@pytest.mark.parametrize(
    "provider,kind",
    [
        (ProviderId.CLAUDE_SUBSCRIPTION, CredentialKind.MANUAL_BEARER),
        (ProviderId.GROK_SUBSCRIPTION, CredentialKind.MANUAL_BEARER),
        (ProviderId.CLAUDE_PLATFORM, CredentialKind.CONSOLE_SESSION),
        (ProviderId.CLAUDE_SUBSCRIPTION, CredentialKind.API_KEY),
    ],
)
def test_manual_refs_preserve_binding(provider, kind):
    store = CredentialStore()
    ref = store.put(ACCOUNT_ID, "synthetic-manual-secret", persist=False)
    account = Account(
        ACCOUNT_ID,
        provider,
        "Synthetic",
        ref,
        kind,
        organization_id="synthetic-org" if provider == ProviderId.CLAUDE_PLATFORM else None,
    )
    result = resolver(store).resolve(account)
    assert result.provider == provider
    assert result.credential_kind == kind
    assert result.organization_id == account.organization_id
    assert result.secret == "synthetic-manual-secret"
    assert result.user_id is None
    assert result.expires_at is None
    assert result.secret not in repr(result)


def test_manual_replacement_changes_generation():
    store = CredentialStore()
    ref = store.put(ACCOUNT_ID, "synthetic-one", persist=False)
    account = Account(
        ACCOUNT_ID, ProviderId.GROK_SUBSCRIPTION, "Synthetic", ref, CredentialKind.MANUAL_BEARER
    )
    instance = resolver(store)
    first = instance.resolve(account)
    replacement = store.put(ACCOUNT_ID, "synthetic-two", persist=False)
    second = instance.resolve(replace(account, credential_ref=replacement))
    assert first.generation_fingerprint != second.generation_fingerprint
    changed_binding = instance.resolve(replace(account, provider=ProviderId.CLAUDE_SUBSCRIPTION))
    assert first.generation_fingerprint != changed_binding.generation_fingerprint
    assert first.provider == ProviderId.GROK_SUBSCRIPTION


def test_missing_manual_and_unconfigured_are_safe():
    store = CredentialStore()
    ref = store.put(ACCOUNT_ID, "synthetic-secret", persist=False)
    store.delete(ref)
    account = Account(
        ACCOUNT_ID, ProviderId.CLAUDE_SUBSCRIPTION, "Synthetic", ref, CredentialKind.MANUAL_BEARER
    )
    assert_error(account, "credential_unavailable", store=store)
    assert_error(account, "credential_unavailable")
    unconfigured = replace(account, credential_ref=None, credential_kind=None)
    assert_error(unconfigured, "credential_unavailable", state=FetchState.UNCONFIGURED)


@pytest.mark.parametrize("entry", [None, [], {}, {"key": ""}, {"key": True}])
def test_grok_selected_entry_requires_key(tmp_path, entry):
    account = imported(tmp_path, {SCOPE: entry}, grok=True)
    assert_error(account, "schema_error")


def test_grok_rejects_unsafe_identity_header(tmp_path):
    account = imported(
        tmp_path,
        {SCOPE: {"key": "synthetic-key", "user_id": "synthetic-user\r\nInjected:header"}},
        grok=True,
    )
    assert_error(account, "schema_error")


def jwt(claims):
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{payload}.c3ludGhldGlj"


def codex_data(**claims):
    return {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "access_token": jwt({"exp": int(FUTURE.timestamp()), **claims}),
            "account_id": "synthetic-selected-account",
            "refresh_token": "synthetic-refresh-never-used",
        },
        "last_refresh": "1900-01-01T00:00:00Z",
    }


def codex_import(tmp_path, data):
    path = tmp_path / "synthetic-codex-auth.json"
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    return Account(
        ACCOUNT_ID,
        ProviderId.CODEX_SUBSCRIPTION,
        "Synthetic Codex",
        str(path),
        CredentialKind.CODEX_AUTH_FILE,
    )


@pytest.mark.parametrize("override", [False, True, "empty"])
def test_codex_default_path(tmp_path, monkeypatch, override):
    root = tmp_path / ("override" if override is True else ".codex")
    root.mkdir()
    path = root / "auth.json"
    path.write_text(json.dumps(codex_data()))
    path.chmod(0o600)
    if override is True:
        monkeypatch.setenv("CODEX_HOME", str(root))
    elif override == "empty":
        monkeypatch.setenv("CODEX_HOME", "")
    monkeypatch.setenv("GROK_HOME", str(tmp_path / "must-not-use-grok"))
    account = Account(
        ACCOUNT_ID,
        ProviderId.CODEX_SUBSCRIPTION,
        "Synthetic",
        "default",
        CredentialKind.CODEX_AUTH_FILE,
    )
    assert resolver().resolve(account).expires_at == FUTURE


def test_codex_capture_redaction_and_selected_account_generation(tmp_path):
    data = codex_data()
    account = codex_import(tmp_path, data)
    path = Path(account.credential_ref)
    before = path.read_bytes()
    instance = resolver()
    first = instance.resolve(account)
    assert first.secret == data["tokens"]["access_token"]
    assert first.codex_account_id == "synthetic-selected-account"
    assert first.user_id is None
    assert first.expires_at == FUTURE
    assert first.generation_fingerprint == instance.resolve(account).generation_fingerprint
    for private in (first.secret, first.codex_account_id, first.generation_fingerprint):
        assert private not in repr(first)
    assert "synthetic-refresh" not in repr(first)
    assert path.read_bytes() == before
    data["tokens"]["account_id"] = "synthetic-other-account"
    path.write_text(json.dumps(data))
    second = instance.resolve(account)
    assert second.secret == first.secret
    assert second.codex_account_id != first.codex_account_id
    assert second.generation_fingerprint != first.generation_fingerprint


def test_codex_documented_id_token_fallback_only(tmp_path):
    data = codex_data()
    del data["tokens"]["account_id"]
    data["tokens"]["id_token"] = jwt(
        {
            "https://api.openai.com/auth": {"chatgpt_account_id": "synthetic-fallback"},
        }
    )
    assert resolver().resolve(codex_import(tmp_path, data)).codex_account_id == "synthetic-fallback"
    data["tokens"]["account_id"] = "synthetic-explicit"
    data["tokens"]["id_token"] = "malformed-unused-id-token"
    assert resolver().resolve(codex_import(tmp_path, data)).codex_account_id == "synthetic-explicit"


@pytest.mark.parametrize("value", [None, "", True, [], "a b", "a\r\nInjected:yes", "a" * 257])
def test_codex_invalid_explicit_account_never_falls_back(tmp_path, value):
    data = codex_data()
    data["tokens"]["account_id"] = value
    data["tokens"]["id_token"] = jwt(
        {
            "https://api.openai.com/auth": {"chatgpt_account_id": "synthetic-valid"},
        }
    )
    assert_error(codex_import(tmp_path, data), "schema_error")


@pytest.mark.parametrize(
    "claims",
    [
        {},
        {"chatgpt_account_id": "synthetic-wrong-level"},
        {"https://api.openai.com/auth": []},
        {"https://api.openai.com/auth": {"chatgpt_account_id": ""}},
    ],
)
def test_codex_missing_documented_identity(tmp_path, claims):
    data = codex_data()
    del data["tokens"]["account_id"]
    data["tokens"]["id_token"] = jwt(claims)
    assert_error(codex_import(tmp_path, data), "schema_error")


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("auth_mode", "api_key", "credential_mismatch"),
        ("OPENAI_API_KEY", "synthetic-api-key", "credential_mismatch"),
        ("OPENAI_API_KEY", True, "schema_error"),
        ("auth_mode", [], "schema_error"),
        ("tokens", None, "schema_error"),
        ("tokens", [], "schema_error"),
    ],
)
def test_codex_rejects_api_key_and_malformed_schema(tmp_path, field, value, code):
    data = codex_data()
    data[field] = value
    assert_error(codex_import(tmp_path, data), code)


@pytest.mark.parametrize("value", [None, "", True, [], "synthetic\naccess", "not-a-jwt", "a.!.b"])
def test_codex_rejects_malformed_access_token(tmp_path, value):
    data = codex_data()
    data["tokens"]["access_token"] = value
    assert_error(codex_import(tmp_path, data), "schema_error")


@pytest.mark.parametrize("value", [None, True, "1893456000", [], 0, -1, float("inf"), 10**1000])
def test_codex_rejects_malformed_expiry_as_auth_required(tmp_path, value):
    assert_error(
        codex_import(tmp_path, codex_data(exp=value)),
        "schema_error",
        state=FetchState.AUTH_REQUIRED,
    )


def test_codex_expired_and_absent_expiry(tmp_path):
    assert_error(
        codex_import(tmp_path, codex_data(exp=int(NOW.timestamp()))),
        "credential_expired",
        state=FetchState.AUTH_REQUIRED,
    )
    data = codex_data()
    data["tokens"]["access_token"] = jwt({})
    assert resolver().resolve(codex_import(tmp_path, data)).expires_at is None


def test_codex_file_only_never_reads_secret_store(tmp_path):
    class ForbiddenStore:
        def get(self, ref):
            pytest.fail("Codex file auth must not consult keyring")

    assert resolver(ForbiddenStore()).resolve(codex_import(tmp_path, codex_data())).codex_account_id


@pytest.mark.parametrize("mode", [0o644, 0o400])
def test_codex_preserves_private_file_requirement(tmp_path, mode):
    account = codex_import(tmp_path, codex_data())
    Path(account.credential_ref).chmod(mode)
    assert_error(account, "unsafe_credential_file")


def test_codex_does_not_fall_back_to_grok_schema(tmp_path):
    assert_error(codex_import(tmp_path, {SCOPE: {"key": "synthetic-grok"}}), "schema_error")


@pytest.mark.parametrize(
    "token", ["e30.bm90LWpzb24.c2ln", "e30.W10.c2ln", "e30.eyJleHAiOjEsImV4cCI6Mn0.c2ln"]
)
def test_codex_rejects_malformed_or_ambiguous_jwt_payload(tmp_path, token):
    data = codex_data()
    data["tokens"]["access_token"] = token
    assert_error(codex_import(tmp_path, data), "schema_error")


def test_codex_missing_file_never_uses_grok_or_keyring(tmp_path, monkeypatch):
    grok = tmp_path / "grok"
    grok.mkdir()
    (grok / "auth.json").write_text(json.dumps({SCOPE: {"key": "synthetic-grok"}}))
    (grok / "auth.json").chmod(0o600)
    monkeypatch.setenv("GROK_HOME", str(grok))
    account = Account(
        ACCOUNT_ID,
        ProviderId.CODEX_SUBSCRIPTION,
        "Synthetic",
        "default",
        CredentialKind.CODEX_AUTH_FILE,
    )
    assert_error(account, "credential_unavailable")
