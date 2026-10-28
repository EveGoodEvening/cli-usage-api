# Usage TUI

A local terminal dashboard project for subscription usage and Claude Platform credit
balances. **The current implementation provides Python domain, local storage,
credential-resolution, and fixed-origin HTTP transport libraries, not a working
dashboard or live provider integration.** There is no usable `usage` CLI, TUI,
offline demo, interactive account manager, or provider adapter yet. The console
entry point declared in package metadata targets a later implementation; do not
invoke it at this stage.

## Original goal and scope

终端 TUI，近实时查看 Claude 订阅 5h / 每周 / Fable 用量；Claude Platform
普通购买余额和赠送余额；GPT 订阅每周用量；GrokBuild / GrokChat 用量、剩余与
重置时间；支持连接账号或管理密钥。不做网页或 statusline。

The intended application is read-only and local: one terminal dashboard, not a web
server, statusline, inference client, or spending dashboard. Near-real-time means
bounded periodic observations, not provider push or an availability guarantee.

## What exists versus what is planned

C01 provides `src/` package metadata, declared runtime/development dependencies, and
frozen domain contracts: provider/account identities, credential kinds and resolved
credential values, exact money and quota values, metrics/grants/snapshots, provenance,
safe error types, validation helpers, and schema serialization. Domain tests are
source artifacts, not proof that checks have passed. Verification and chunk closure
are recorded only from exercised evidence in [PLAN.md](PLAN.md).

The C01 review correction bounds percentage representations before exact arithmetic:
at most 4,096 input string characters, 1,024 Decimal coefficient digits, and a stored
Decimal exponent from −1,000 through +1,000. Unsupported representations raise
`DomainError`, including through serialized snapshots. These bounds prevent a tiny
scientific-notation value from requesting enormous decimal expansion; a JSON byte
limit alone is insufficient. Supported percentages remain exact, including values
above 100%; remaining is exactly `max(0, 100 - used)`, not a rounded or capped used
value. C01 verification and closure are recorded in PLAN.md.

C02 adds library-level account/config persistence and credential storage. C03 adds
read-only Linux credential-file resolution and guarded HTTP transport; see below.
Provider adapters, polling, offline demo, interactive account management, terminal
UI, and CLI integration remain **planned, not current support**:

| Requested metric | Intended meaning and source | Current live status |
|---|---|---|
| Claude 5h / weekly | Subscription used/remaining percentages and server reset from private OAuth usage | No adapter or authenticated acceptance yet |
| Claude Fable weekly | Model-scoped weekly subset; not extra capacity and not an Opus/Sonnet alias | Plan/response dependent; no adapter yet |
| Platform purchased / promotional | Separate totals across relevant credit grants, with per-grant expiry; authoritative overall total kept separately | Private Console credits contract researched; no adapter or live acceptance yet |
| Ordinary ChatGPT weekly | Actual chat-model subscription usage/remaining/reset | **Upstream contract unresolved**, not just missing credentials |
| Grok shared pool / Build / Chat | Aggregate included allowance and validated same-payload product consumption shares | Private direct billing contract researched; no adapter or live acceptance yet |

Grok product shares must not become independent `100 - share` allowances. Remaining
and reset refer to the shared pool only when unified billing is established. Credit
grants expire rather than reset weekly. Missing fields are unknown, not zero. API
spend is not credit balance; API usage is not subscription allowance. WHAM/Codex is
not a fallback for ordinary ChatGPT weekly chat usage. No requested live metric is
currently claimed as working or accepted.

## Development setup (Python libraries)

Requirements: Python 3.11+ and [uv](https://docs.astral.sh/uv/). The initial target for
the libraries is Linux/POSIX; cross-platform credential import is not supported.

The repository includes `uv.lock`. Install the locked development environment from
the repository root:

```sh
uv sync --locked --group dev
```

This is an environment setup command, not a claim that the full verification gate
has passed. Library modules are `usage_tui.domain`, `usage_tui.storage`,
`usage_tui.credentials`, and `usage_tui.transport`; do not run the future console
entry point. Transport alone does not fetch or normalize any requested metric.

## Local storage library (C02)

`AccountStore(path=None)` uses
`$XDG_CONFIG_HOME/usage-tui/accounts.json`, falling back to
`~/.config/usage-tui/accounts.json`. An explicit path supports isolated callers.
Schema version `1` contains account metadata and opaque credential references,
never credential values. `load()` returns accounts; `save(accounts)` replaces a
validated complete set. For read-modify-write changes use `mutate(change)`, which
locks and rereads before applying the callback, rather than a stale `load`/`save`
pair. A callback exception leaves the stored configuration unchanged.

Manual-secret references must use the store's opaque reference format; inline
manual credentials and persisted references bound to another account are rejected.
External first-party file references are preserved without opening those files;
the credential resolver performs read-time permission and schema validation.

On supported POSIX/Linux systems the store uses a private `0700` directory,
`0600` config/lock files, a separate advisory lock, and atomic same-directory
replacement. Config reads are limited to 1 MiB. Unsafe file ownership/permissions,
symlinks, hardlinks, malformed data, and unsupported schema versions raise a safe
`ConfigError`; an existing invalid configuration is not overwritten. These are
cooperating-writer locks, not protection against hostile code running as your user.

A failure after atomic replacement (such as a directory-sync failure) can report
an error after the new config is already visible; atomic visibility is not a
guarantee that every failed save left the previous version in place.

`CredentialStore().put(account_id, secret, persist=False)` explicitly selects
instance-local memory and returns an opaque `session:` reference. It does not
access the OS keyring and cannot survive the store instance/process. With
`persist=True`, the store lazily uses only the supported Linux Secret Service
backend, returning a nonsecret `keyring:` reference. Null, fail, plaintext,
chained, unrecognized, and subclassed backends are rejected; unavailable or locked
keyring operations raise `CredentialError`, never silently fall back to memory
or plaintext. `get(ref)` retrieves and `delete(ref)` removes this tool's stored
credential; neither operates on external Claude/Grok login files or revokes a
remote session. Deleting account metadata and deleting its local secret are
separate library operations, not an interactive account-removal workflow yet.

No real-keyring acceptance or C02 check outcome is claimed here. Python cannot
guarantee memory zeroization, and a reference is not itself a secret-management
permission boundary. Masked prompts, account-removal confirmation, and cancellation
of in-flight provider work are later integrations.

## Credential resolution and transport libraries (C03)

`CredentialResolver(credential_store=None, *, clock=None).resolve(account)`
captures a credential once for a fetch attempt and returns a frozen
`ResolvedCredential` bound to the account's explicit
provider and credential kind. The secret is excluded from its representation;
identity, expiry, selected organization, and a nonsecret generation fingerprint
are separate metadata. A fingerprint is not a token suffix for display or logging.
Manual credentials are retrieved through `CredentialStore` opaque references,
not treated as inline account configuration. Local API-key storage does not enable
subscription metrics or Console balances, and the unresolved ChatGPT capability
must not resolve a saved credential or invoke transport.

Linux first-party imports are literal local paths (absolute or relative), not
commands or URLs. The explicit `default` reference selects these default files
only when resolving an account, not when constructing the resolver:

- Claude Code: `$CLAUDE_CONFIG_DIR/.credentials.json`, otherwise
  `~/.claude/.credentials.json`, or an explicit local file reference. Resolution
  reads `claudeAiOauth.accessToken`; optional expiry is Unix milliseconds. If
  scopes are present they must permit `user:profile`. Inference-only setup tokens
  and API keys are not substitutes for an eligible profile-scoped credential.
- Grok: `$GROK_HOME/auth.json`, otherwise `~/.grok/auth.json`, or an explicit
  local file reference. Resolution uses the selected `https://auth.x.ai::<client-id>`
  entry; the legacy `https://accounts.x.ai/sign-in` entry is a fallback only when
  unambiguous. Multiple matching identities require a saved nonsecret scope
  selector; no account is silently chosen. An optional `user_id` comes from that
  same selected entry. Unknown expiry is not evidence of freshness.

Imported files must be regular, effective-user-owned files with exact `0600` mode
on supported Linux, with bounded reads of at most 1 MiB. Unsafe permissions,
symlinks, malformed schema,
expired credentials, and ambiguous profiles produce safe errors, not fallback
credentials. Resolution does not chmod, write, refresh, or delete first-party
files, run login commands, or copy refresh tokens into app storage. Sign in or
renew credentials with the first-party tool outside this application. Fixtures
are synthetic; they do not establish authenticated compatibility.

`Transport(*, http_transport=None, clock=None)` accepts an injected in-memory HTTP
transport and clock for isolated callers; URL guards remain in force with either.
It needs no persistent client lifecycle: each read creates and closes its client.
`Transport.get_json(provider, path, credential=resolved)` is an async read-only JSON
boundary. Before constructing authentication headers or opening a socket it checks
the resolved provider binding, credential kind, and exact allowlisted path:

| Provider | Fixed HTTPS origin and permitted path | Credential and authentication |
|---|---|---|
| Claude subscription | `https://api.anthropic.com/api/oauth/usage` | `claude_code_file` or `manual_bearer`; Bearer plus `anthropic-beta: oauth-2025-04-20` |
| Claude Platform | `https://platform.claude.com/api/organizations` and `/api/organizations/{id}/prepaid/credits`, with ID `[A-Za-z0-9-]{1,64}` | `console_session` only; `Cookie: sessionKey=<value>` |
| Grok subscription | `https://cli-chat-proxy.grok.com/v1/billing?format=credits` | `grok_auth_file` or `manual_bearer`; Bearer, `x-xai-token-auth: xai-grok-cli`, and `x-userid` only from the same resolved credential when present |
| Ordinary ChatGPT | None | No transport request; upstream contract unresolved |

All other paths, origins, credential-kind/provider combinations, and API keys are
rejected for these reads. There is no user-configurable base URL. Console accepts
only a cookie value, not a full Cookie header or HAR; invalid cookie delimiters
and controls are rejected. Treat a `sessionKey` as a high-sensitivity session, not
a limited API key. A later connection UI must warn before accepting it and require
explicit organization selection; transport does not discover or select accounts.

Production transport verifies TLS, uses GET only, disables redirects and implicit
proxy/netrc environment use, and does not persist server cookies between requests.
Requests include JSON acceptance and the installed-package User-Agent, not an
invented upstream client identity. Connect timeout is 5 seconds, with a 10-second
overall request deadline and a streamed 1 MiB response limit. JSON shape validation
and metric interpretation belong to future adapters. Safe `TransportError` values
carry only fetch state, fixed code, optional HTTP status and retry time, never a
response body, secret, credential path, or arbitrary exception text. A valid 429
`Retry-After` is preserved with a minimum 60-second deadline; scheduler retry/backoff
is a later integration, not part of this library's polling behavior.

No account setup or key-management command works at this stage. Do not paste
credentials into chat, issues, shell arguments, documentation, or fixtures. No
browser extraction, token refresh protocol, live-provider acceptance, or real
OS-keyring acceptance is claimed. Private HTTP routes and product fields remain
version-sensitive, not official public API guarantees. Researched sources and
exact contracts are in PLAN.md §§4 and 7; ordinary ChatGPT weekly quota still needs
a defensible read-only request/authentication and metric contract.

See [SECURITY.md](SECURITY.md) for current limitations and planned controls,
[CHANGELOG.md](CHANGELOG.md) for delivered changes, and PLAN.md for the only progress
tracker and the separate code/live acceptance matrix.
