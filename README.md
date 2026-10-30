# CLIUsageAPI

A local terminal dashboard for subscription usage and prepaid credit balances
(Claude subscription, Claude Platform, OpenAI Platform), with an optional token-protected HTTP API (usage data plus account
management) and a separate web frontend. Provider reads are read-only. No statusline.

**Status:** Offline demo and local account workflows are verified. Authenticated
provider reads and real OS-keyring persistence remain unverified. Provider
integrations use private, version-sensitive APIs.

## Quick start

Use Python **3.12.16** (selected by `.python-version`), [uv](https://docs.astral.sh/uv/)
**0.13.6** (enforced by `pyproject.toml`), and an interactive terminal.
Linux/POSIX is the supported credential-import and persistence target. Package API
compatibility remains Python 3.11+, not a security endorsement of older patch releases.
uv 0.13.6 includes the selected interpreter in its download catalog; an existing
`.venv` must also use that patched interpreter. See the
[CA and deployment policy](docs/deploy-railway.md#ca-事件版本锁定与更新).

```sh
uv sync --locked
uv run usage --demo   # Offline demo
uv run usage          # Live dashboard
```

Runtime dependencies are locked in `uv.lock`; isolated build dependencies, including
Hatchling and its editable-build helper, are separately pinned and hash-checked in
`pyproject.toml`. Keep build isolation enabled. uv currently prints an experimental
build-hash warning; it does not disable enforcement. See [build trust boundaries](SECURITY.md#build-and-dependency-trust).

Demo uses fictional data without reading account configuration, credentials, or
keyring, and makes no network requests. Use `--demo --scenario errors` to preview
error states. In live mode, press `a` to connect accounts.

| Key | Action |
|---|---|
| `a` | Manage accounts |
| `r` | Request refresh; retry limits still apply |
| Enter on a metric | View details and provenance |
| `?` | Help |
| Ctrl-P → Theme | Choose a theme; selection is saved automatically |
| Escape | Back / cancel |
| `q` / Ctrl-C | Quit dashboard / exit from any screen |

The initial theme is **nord**. Live and demo mode share the last selected theme in
`$XDG_CONFIG_HOME/cli-usage-api/settings.json` (default:
`~/.config/cli-usage-api/settings.json`). This separate, nonsecret UI preference never
changes account configuration or credentials. Unreadable settings or an unavailable
theme produce a warning and fall back to nord; save failures are also reported.

## Metrics

| Provider | Displayed metrics |
|---|---|
| Claude subscription | 5-hour, weekly, and model-scoped Fable weekly usage; optional prepaid credits balance (Claude 已购 credits 余额) when an organization is selected |
| Claude Platform | Purchased, promotional, and authoritative total credit balances; grant expiry |
| Codex | Weekly (7-day) quota, plus reported optional windows such as 5-hour usage, and a Codex credits balance (or Unlimited) when reported |
| Grok | Shared-pool usage and GrokBuild / GrokChat consumption shares |
| OpenAI Platform | Available prepaid credit balance, plus paid-available balance when reported |

Codex quota is **not ordinary ChatGPT chat usage**. Fable is a weekly subset, not
extra capacity. Grok product shares are not independent allowances; remaining and
reset require confirmed shared-pool semantics. Credit expiry is not a quota reset.

Missing values stay unknown. Grok's private weekly schema has one bounded exception:
with an explicit weekly period and valid reset, omitted percentage scalars mean
zero; explicit null/invalid values and absent products remain unknown. Product
shares need not sum to the aggregate. Codex hides `plan_type`, `allowed`, and
`limit_reached`; quota percentages and reset times remain visible.

Codex credits come from the same usage response: a non-currency amount shown as
`<amount> credits` rounded half-even to two decimals (e.g. `137.50 credits`; the API
JSON keeps the exact value; never converted to money or given an expiry), or
`不限量` / Unlimited. Like the official client, no row appears when the account has no
credits. Claude subscription extra usage (spend in the current billing period
against an optional monthly cap) is parsed from the existing usage response into
snapshots, the debug log and the HTTP API (`claude.subscription.extra_usage`), but
is deliberately **not displayed** in the TUI or web UI for now.

The Claude prepaid credits balance is read only for an account whose organization
was explicitly selected: each refresh then reads usage first and, only after a
successful usage response, makes one read-only prepaid-credits request. A failed
credits request leaves the usage rows fresh, marks the credit row unknown and the
account partial; its retry deadline is honored. Promotional credit is already part
of that balance (expiry is shown as detail, not a reset), and it is never combined
with Claude Platform balances or derived from extra usage.

OpenAI Platform shows the dashboard's reported `total_available` (and
`total_paid_available` when present), never granted minus used. The payload names no
currency; USD is an assumption matching the official dashboard. The TUI and web round
OpenAI amounts half-even to cents and note `服务端金额已舍入到分 / rounded to cents`
when that changed the value; the API JSON keeps the exact amount.

Failed reads retain last-known values with freshness/error indicators; passing a
reset does not invent new allowance. Claude subscription automatically polls no
more often than every **3 minutes** and OpenAI Platform no more often than every
**5 minutes**, including existing shorter configurations; longer configured
intervals are honored. Other providers retain the 60-second default and configurable 30–3600-second interval. Claude 429 retries start at
3 minutes, then 6, 12, and 15 minutes (plus jitter); longer configured intervals or
server `Retry-After` win. `r` requests an earlier observation, but never bypasses
retry deadlines. Restart a running dashboard to use the new policy.

## Connect accounts

Sign in through the first-party tools outside this app, then press `a` in the live
dashboard, use the `usage accounts` commands below, or add accounts in the
[web UI](#account-management-over-http) when the API runs with writes enabled:

- **Claude:** run `claude`, then `/login`. Choose **External Claude Code file**.
  Optionally press Discover to read your profile's organization and explicitly
  select it to add the prepaid credits balance (one extra read-only request per
  refresh); it is never selected automatically. Choose no organization to skip it.
- **Claude Platform:** choose **Console session (not an API key)**. A `sessionKey`
  is a **high-sensitivity account session**: enter only your own cookie value in
  the masked prompt, never a password, full Cookie header, or HAR file. Discover
  organizations and explicitly select one, even if only one is available.
- **Codex:** set `cli_auth_credentials_store = "file"` in Codex's `config.toml`,
  then run `codex login` with ChatGPT sign-in. Choose **External Codex auth file**.
  Only file-backed login is supported—not manual tokens, API keys, or keyring-only
  login. See the [Codex authentication guide](https://developers.openai.com/codex/auth).
- **Grok:** run `grok login`. Choose **External Grok auth file** and explicitly
  select the intended identity/scope.
- **OpenAI Platform:** enter your organization ID (`org-…`, from platform.openai.com
  settings), then choose **OpenAI Platform dashboard session key (not an API key)**.
  This is a **high-sensitivity account session**: it grants full dashboard access
  (billing, purchases, creating API keys). Paste only the token value in the masked
  prompt — never a password, full Cookie/Authorization header, or HAR file. It
  expires within days and cannot be refreshed by this app: paste a new one when the
  account shows authentication required. API keys (`sk-…`) do not work. Stored only
  in the OS keyring or kept for the session; the app makes one read-only GET.

For file sources, use `default` or a normalized absolute path to a private,
user-owned `0600` regular file named `.credentials.json` (Claude Code) or
`auth.json` (Codex, Grok), outside `/proc`, `/sys` and `/dev`; previously saved
references that do not match keep working but cannot be re-entered. The app never modifies or deletes first-party login files, runs login, or
refreshes tokens. Renew expired credentials through the first-party tool; on an
unattended host, the separate opt-in `usage-keepalive` loop invokes each official CLI
shortly before its stored expiry so that CLI renews its own file (see
[docs/deploy-railway.md](docs/deploy-railway.md)).
API keys do not enable subscription metrics, Console balances, or OpenAI Platform balances.

In the account manager (`a`), Shift+↑/↓ (or Ctrl+↑/↓) moves the selected account and
mouse drag reorders; the order is saved to `accounts.json` and the dashboard, the API
and the web UI follow it. Read-only and demo managers ignore moves.

### CLI account management

```sh
uv run usage accounts list
uv run usage accounts add --provider codex-subscription
uv run usage accounts edit ACCOUNT_ID
uv run usage accounts remove ACCOUNT_ID
uv run usage accounts key set ACCOUNT_ID
uv run usage accounts key delete ACCOUNT_ID
```

Use the ID from `accounts list`. Other provider choices are `claude-subscription`,
`claude-platform`, `grok-subscription`, and `openai-platform`. Mutating commands require an interactive
TTY; credentials are entered through masked prompts, never command arguments.
Run `uv run usage --help` for command help.
`accounts list` shows the effective polling interval; saved values below Claude's
3-minute or OpenAI Platform's 5-minute floor are preserved in configuration but do not
shorten automatic polls.

Legacy ChatGPT profiles require `uv run usage accounts migrate-chatgpt-to-codex`.
After explicit confirmation, replacements are disabled and credentials detached;
old keyring secrets remain unmanaged. Configure a Codex file reference, then enable.

## Debug log

To investigate malformed or missing provider data, start the live dashboard with a
debug log file (output never goes to the terminal):

```sh
uv run usage --debug-log ~/usage-debug.jsonl                      # all providers
uv run usage --debug-log ~/usage-debug.jsonl \
  --debug-provider codex-subscription --debug-provider grok-subscription
```

`--debug-provider` is repeatable (`claude-subscription`, `claude-platform`,
`codex-subscription`, `grok-subscription`) and requires `--debug-log`; neither
works with `--demo` or account commands. The file is appended as JSON lines
(`ts`, `provider`, `event`): `http_response` (path, status, byte length, decoded
body with exact numbers, or bounded raw text when not JSON), `http_error`
(diagnostic code, fetch state, status, or only an exception type name), and
`snapshot` (account ID, fetch state, diagnostic, and every metric's state, detail,
quota, reset, balance and share as parsed). The parent directory must exist; the
file is created `0600`, and symlinks, non-regular files and group/other-readable
files are refused.

> **Warning:** the log contains raw provider response bodies, which may include
> personal data such as email addresses or account IDs. Request headers are never
> logged; values under secret-looking keys, JWT-like strings and the request's own
> credential values are redacted best-effort. Keep the file private, and review it
> before sharing.

## Credential safety

- Never put secrets in arguments, environment variables, labels, chat, or issues.
- Persistent manual-secret storage requires an unlocked, supported Linux Secret
  Service keyring. Plaintext and alternative backends are rejected.
- If secure storage is unavailable, choose **session only** in the TUI or web UI.
  Secrets disappear when that process (TUI or API server) exits; there is no silent
  storage fallback.
- Removing an account or stored key does not revoke its remote session.

Account metadata lives at `$XDG_CONFIG_HOME/cli-usage-api/accounts.json`, falling back
to `~/.config/cli-usage-api/accounts.json`; credential values are stored separately.
See [SECURITY.md](SECURITY.md) for boundaries and limitations.

## HTTP API

`usage api serve` runs headless (no TUI) and serves the same usage data as JSON.
Unless started with `--read-only`, any API token can also add, edit, reorder and
remove accounts (see [account management](#account-management-over-http)); demo is
always read-only.

```sh
uv run usage api token create --label web    # TTY only; the token is printed once
uv run usage api serve                       # live mode, default 127.0.0.1:8787
uv run usage api serve --demo                # fictional data, no live files/network
```

- Every endpoint except `GET /healthz` requires `Authorization: Bearer <token>`.
  Live mode refuses to start without a configured token. Demo bound to a loopback
  host may run without tokens; once any token exists, demo requires it too.
- Only the SHA-256 hash of each token is stored, in `api_tokens.json` beside
  `accounts.json`. `usage api token list` shows IDs/labels/creation times;
  `usage api token revoke ID` takes effect in a running server within about a second.
- Read endpoints (`GET`/`HEAD`): `/healthz`, `/api/v1/session`, `/api/v1/dashboard`,
  `/api/v1/accounts` (nonsecret account configuration) and `/api/v1/accounts/{id}`.
  Session and account-list responses carry `capabilities` (`writable`,
  `secure_store_available`). Dashboard order is the saved account order.
- Browsers on another origin need `--allow-origin https://frontend.example`
  (exact origin, repeatable; no wildcard). `--trust-proxy` makes failed-auth limiting
  use the right-most `X-Forwarded-For` entry; use it only behind a trusted reverse
  proxy such as Railway.
- Account changes made over the API apply immediately. Changes made with
  `usage accounts` in another process apply on the next API write, a conflict
  reload or a restart (the server does not watch `accounts.json`). Credential
  sources are resolved per poll, as in the dashboard.
- Headless `serve` cannot use TUI session-only secrets, but a secret submitted over
  the API with session-only storage lives in the `serve` process. Without an OS
  keyring (for example in a container), add Claude Platform through the web UI as
  session-only and re-enter it after each restart, or use one-process mode below.
- `usage api serve --keepalive [--keepalive-cli NAME ...] [--keepalive-claude-mode
  hybrid|status|model]` (live only) also runs `usage-keepalive` in the server process
  and prints its log lines.

### One-process mode: dashboard + API (+ keepalive)

```sh
uv run usage --api                                   # TUI and API, 127.0.0.1:8787
uv run usage --api --api-host 0.0.0.0 --api-port 9000 \
  --allow-origin https://frontend.example --trust-proxy --keepalive
uv run usage --demo --api                            # fictional data; loopback, no token
```

`usage --api` runs the API inside the dashboard process: one scheduler, and the API
serves exactly the snapshots the TUI shows. Accounts added, edited, reordered, removed,
enabled or disabled in the TUI's account manager appear in `/api/v1/dashboard`
immediately, and account changes made over HTTP (unless `--read-only`) appear in the
TUI immediately, and a **session-only** credential entered in that TUI (for example a
Claude Platform Console `sessionKey` on a host without a keyring) feeds the API too.
It lasts only as long as the process: re-enter it after every restart. The token,
CORS and `--trust-proxy` rules are the same as `usage api serve`; live mode needs at
least one token. The socket is bound before the TUI starts, so a busy port fails with
a normal error. The banner shows `API host:port`; an API failure is a notification,
not a crash, and uvicorn never writes to the terminal.
`--keepalive` (live only, also on `usage api serve`) runs `usage-keepalive` in the same
process, holding its single-instance lock; it logs only to
`~/.local/state/usage-keepalive/keepalive.log`, and `ALERT` lines appear as TUI
warnings. Quitting the TUI stops the API, keepalive and scheduler together: keepalive
starts no further command, kills the official CLI command in flight (its whole process
group; that attempt counts as neither success nor failure, so a Claude `auth status`
interrupted by quitting never escalates to the Haiku request), and the lock is
released only after its worker thread has returned. Grok scopes an enabled saved
account selects explicitly in the default login file are never marked stale; the TUI
updates that set when accounts change. A no-selector account adds nothing, because the
reader's default scope is already never marked stale.

### Account management over HTTP

Writes need a token and a live server without `--read-only`; startup prints whether
they are ENABLED. Every token is a full-write token, so tokens created before this
feature gain write access on upgrade: use `--read-only` when tokens are shared widely.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/accounts` | Create an account (`201`) |
| `POST` | `/api/v1/accounts/prepare` | Read Grok scopes or discover Console organizations for an explicit choice |
| `PUT` | `/api/v1/accounts/order` | Save a full permutation of account IDs |
| `PATCH` | `/api/v1/accounts/{id}` | Edit label, interval, enabled or credential source (`If-Match` revision required) |
| `DELETE` | `/api/v1/accounts/{id}` | Remove an account and secrets this tool stored (`If-Match` required) |
| `POST` | `/api/v1/accounts/{id}/reconnect` | Request an earlier read; retry limits still apply |

- Bodies are JSON (≤ 64 KiB, 10 s), strict and whitelisted; errors are fixed codes
  such as `{"error":"conflict"}`. A stale revision or reorder list returns `409`.
- Secrets go only in the request body and are never returned. Choose `persist: true`
  (OS keyring only; `503 secure_store_unavailable` when none is available, never a
  silent fallback) or `persist: false` (kept in the server process until it exits).
- Responses never include custom paths (only `custom`), Grok selectors, Console
  organization IDs or credential references. File references follow the basename
  rule above. Grok scopes and Console organizations must be chosen explicitly.
- Removing an account never deletes first-party login files or revokes remote
  sessions. Keepalive covers only default login files that existed when the server
  started, never custom paths.

In one-process mode, web edits update the TUI immediately (dashboard and an open
account manager). See [SECURITY.md](SECURITY.md) for the threat model and
[web/README.md](web/README.md) for the web screens.

## Web frontend

[`web/`](web/) is a separate static Vite/React app that signs in with the API base
URL and a token, polls `/api/v1/dashboard`, and, when the server allows writes,
manages and reorders accounts in its accounts view. It deploys to Vercel, Cloudflare or
Railway; see [web/README.md](web/README.md). For local development, run
`uv run usage api serve --demo --allow-origin http://localhost:5173` and
`npm run dev` in `web/`.

## Railway deployment (backend)

The root [`Dockerfile`](Dockerfile) builds an image with Python 3.12, this project,
Node.js 22 and pinned Claude Code, Codex and Grok Build CLIs, then runs
`sleep infinity`. Attach a volume at `/data` (`HOME=/data/home`), then
`railway ssh` in to log in to each CLI and create a token. The recommended flow then
sets the service's custom start command to
`/usr/bin/tini -- /usr/local/bin/usage-entrypoint usage api serve --host 0.0.0.0 --port 8787 --allow-origin https://<frontend> --trust-proxy --keepalive`,
redeploys, and adds accounts in the web UI (Claude Platform and OpenAI Platform only
as session-only, re-entered after each redeploy). One-process `usage --api` in tmux remains an
alternative.
Step-by-step instructions (Chinese) and sources are in
[docs/deploy-railway.md](docs/deploy-railway.md). The image has been built and
smoke-tested locally only; no Railway deployment or in-container login is verified.

## Development

```sh
uv sync --locked --group dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/tui_smoke.py
```

The terminal smoke harness exercises both demo scenarios, normal quit, Ctrl-C,
resize, and terminal restoration with isolated HOME/XDG state—not live providers.

[PLAN.md](PLAN.md) records contracts and exercised acceptance;
[CHANGELOG.md](CHANGELOG.md) records delivered changes.
