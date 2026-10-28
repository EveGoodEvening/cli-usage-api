# Usage TUI

A local terminal dashboard project for subscription usage and Claude Platform credit
balances. **The current implementation provides Python domain and local storage
libraries, not a working dashboard or live integration.** There is no usable `usage`
CLI, TUI, offline demo, interactive account manager, credential importer, or provider
fetch yet. The console entry point declared in package metadata targets a later
implementation; do not invoke it at this stage.

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

C02 adds library-level account/config persistence and credential storage; see the
local-storage section below. Credential import, fixed-origin HTTP transport,
provider adapters, polling, offline demo, interactive account management, terminal
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

## Development setup (domain and storage libraries)

Requirements: Python 3.11+ and [uv](https://docs.astral.sh/uv/). The initial target for
the eventual application is Linux/POSIX; cross-platform credential import has not
been implemented or established.

The repository includes `uv.lock`. Install the locked development environment from
the repository root:

```sh
uv sync --locked --group dev
```

This is an environment setup command, not a claim that the full verification gate
has passed. Import library code from `usage_tui.domain` and `usage_tui.storage`;
do not run the future console entry point. Dependency declarations for Textual and
HTTP alone do not implement UI or network access.

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
their read-time permission validation belongs to the later credential resolver.

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
permission boundary. Credential import, masked prompts, account-removal
confirmation, and cancellation of in-flight provider work are later integrations.

## Authentication and private-contract boundaries

No account setup or key-management command works at this stage. Storage is available
only through the Python library. Do not paste credentials into chat, issues, shell
arguments, documentation, or fixtures.

The planned Claude subscription integration uses an existing eligible Claude Code
login or an explicit bearer; inference-only setup tokens and API keys are not
interchangeable with a profile-scoped usage credential. Planned Grok integration
references an existing first-party login or explicit subscription bearer, not an
xAI API/management key. First-party login and any token renewal remain outside this
tool; browser credential extraction is out of scope.

The planned Platform integration uses the user's own high-sensitivity `sessionKey`
for `platform.claude.com` and an explicitly selected organization with billing-read
rights. That session must never go to Claude subscription endpoints. No passwords,
arbitrary Cookie headers, or HAR imports are part of the design. Local API-key
storage does not enable subscription metrics or Console balance retrieval.

Private HTTP routes and product fields are version-sensitive, not official public
API guarantees. Researched source revisions and exact contracts are in PLAN.md
§§4 and 7. No real account was authenticated by the documented research. Ordinary
ChatGPT weekly quota needs a defensible read-only endpoint/authentication and metric
semantics before it can be implemented; storing a key would not solve that gap.

See [SECURITY.md](SECURITY.md) for current limitations and planned controls,
[CHANGELOG.md](CHANGELOG.md) for delivered changes, and PLAN.md for the only progress
tracker and the separate code/live acceptance matrix.
