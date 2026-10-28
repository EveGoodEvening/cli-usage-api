# Usage TUI

A planned local terminal dashboard for subscription usage and Claude Platform credit
balances. **The current C01 implementation is a Python package/domain library, not a
working dashboard or live integration.** There is no usable `usage` CLI, TUI, offline
demo, account manager, provider fetch, or credential backend yet. The console entry
point declared in package metadata targets a later implementation; do not invoke it
at this stage.

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

Storage, credential import, fixed-origin HTTP transport, provider adapters, polling,
offline demo, account management, terminal UI, and CLI integration belong to later
chunks. Their requirements below are **planned, not current support**:

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

## Development setup (domain library only)

Requirements: Python 3.11+ and [uv](https://docs.astral.sh/uv/). The initial target for
the eventual application is Linux/POSIX; cross-platform credential import has not
been implemented or established.

The repository includes `uv.lock`. Install the locked development environment from
the repository root:

```sh
uv sync --locked --group dev
```

This is an environment setup command, not a claim that the full verification gate
has passed. Import library code from `usage_tui.domain`; do not run the
future console entry point. Dependency declarations for Textual, HTTP, and keyring
alone do not implement UI, network access, or secure secret persistence.

## Authentication and private-contract boundaries

No account setup or key-management command works at C01. Do not paste credentials
into chat, issues, shell arguments, documentation, or fixtures.

The planned Claude subscription integration uses an existing eligible Claude Code
login or an explicit bearer; inference-only setup tokens and API keys are not
interchangeable with a profile-scoped usage credential. Planned Grok integration
references an existing first-party login or explicit subscription bearer, not an
xAI API/management key. First-party login and any token renewal remain outside this
tool; browser credential extraction is out of scope.

The planned Platform integration uses the user's own high-sensitivity `sessionKey`
for `platform.claude.com` and an explicitly selected organization with billing-read
rights. That session must never go to Claude subscription endpoints. No passwords,
arbitrary Cookie headers, or HAR imports are part of the design. Future local API-key
storage does not enable subscription metrics or Console balance retrieval.

Private HTTP routes and product fields are version-sensitive, not official public
API guarantees. Researched source revisions and exact contracts are in PLAN.md
§§4 and 7. No real account was authenticated by the documented research. Ordinary
ChatGPT weekly quota needs a defensible read-only endpoint/authentication and metric
semantics before it can be implemented; storing a key would not solve that gap.

See [SECURITY.md](SECURITY.md) for current limitations and planned controls,
[CHANGELOG.md](CHANGELOG.md) for delivered changes, and PLAN.md for the only progress
tracker and the separate code/live acceptance matrix.
