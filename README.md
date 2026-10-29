# CLIUsageAPI

A local, read-only terminal dashboard for subscription usage and Claude Platform
credit balances, with an optional token-protected read-only HTTP API and a separate
web frontend. No statusline.

**Status:** Offline demo and local account workflows are verified. Authenticated
provider reads and real OS-keyring persistence remain unverified. Provider
integrations use private, version-sensitive APIs.

## Quick start

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/) 0.13.5+, and an interactive terminal.
Linux/POSIX is the supported credential-import and persistence target.

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
| Claude subscription | 5-hour, weekly, and model-scoped Fable weekly usage |
| Claude Platform | Purchased, promotional, and authoritative total credit balances; grant expiry |
| Codex | Weekly (7-day) quota, plus reported optional windows such as 5-hour usage |
| Grok | Shared-pool usage and GrokBuild / GrokChat consumption shares |

Codex quota is **not ordinary ChatGPT chat usage**. Fable is a weekly subset, not
extra capacity. Grok product shares are not independent allowances; remaining and
reset require confirmed shared-pool semantics. Credit expiry is not a quota reset.

Missing values stay unknown. Grok's private weekly schema has one bounded exception:
with an explicit weekly period and valid reset, omitted percentage scalars mean
zero; explicit null/invalid values and absent products remain unknown. Product
shares need not sum to the aggregate. Codex hides `plan_type`, `allowed`, and
`limit_reached`; quota percentages and reset times remain visible.

Failed reads retain last-known values with freshness/error indicators; passing a
reset does not invent new allowance. Claude subscription automatically polls no
more often than every **3 minutes**, including existing 60-second configurations;
longer configured intervals are honored. Other providers retain the 60-second
default and configurable 30–3600-second interval. Claude 429 retries start at
3 minutes, then 6, 12, and 15 minutes (plus jitter); longer configured intervals or
server `Retry-After` win. `r` requests an earlier observation, but never bypasses
retry deadlines. Restart a running dashboard to use the new policy.

## Connect accounts

Sign in through the first-party tools outside this app, then press `a` in the live
dashboard:

- **Claude:** run `claude`, then `/login`. Choose **External Claude Code file**.
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

For file sources, use `default` or an absolute path to a private, user-owned `0600`
file. The app never modifies or deletes first-party login files, runs login, or
refreshes tokens. Renew expired credentials through the first-party tool; on an
unattended host, the separate opt-in `usage-keepalive` loop invokes each official CLI
shortly before its stored expiry so that CLI renews its own file (see
[docs/deploy-railway.md](docs/deploy-railway.md)).
API keys do not enable subscription metrics or Console balances.

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
`claude-platform`, and `grok-subscription`. Mutating commands require an interactive
TTY; credentials are entered through masked prompts, never command arguments.
Run `uv run usage --help` for command help.
`accounts list` shows the effective polling interval; saved values below Claude's
3-minute floor are preserved in configuration but do not shorten automatic polls.

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
- If secure storage is unavailable, choose **session only** in the TUI. Secrets
  disappear when the process exits; there is no silent storage fallback.
- Removing an account or stored key does not revoke its remote session.

Account metadata lives at `$XDG_CONFIG_HOME/cli-usage-api/accounts.json`, falling back
to `~/.config/cli-usage-api/accounts.json`; credential values are stored separately.
See [SECURITY.md](SECURITY.md) for boundaries and limitations.

## Read-only HTTP API

`usage api serve` runs headless (no TUI) and serves the same usage data as JSON. It
only reads: there are no endpoints for adding, editing or removing accounts.

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
- Endpoints: `/healthz`, `/api/v1/session`, `/api/v1/dashboard`,
  `/api/v1/accounts/{id}`. Only `GET`/`HEAD`/`OPTIONS` are accepted.
- Browsers on another origin need `--allow-origin https://frontend.example`
  (exact origin, repeatable; no wildcard). `--trust-proxy` makes failed-auth limiting
  use the right-most `X-Forwarded-For` entry; use it only behind a trusted reverse
  proxy such as Railway.
- Account configuration is read once at startup: restart `serve` after changing
  accounts. Credential sources are resolved per poll, as in the dashboard.
- Headless `serve` cannot use TUI session-only secrets. Without an OS keyring
  (for example in a container) it reads only file-backed Claude Code / Codex / Grok
  logins; use one-process mode below for Claude Platform there.
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

`usage --api` runs the read-only API inside the dashboard process: one scheduler, and
the API serves exactly the snapshots the TUI shows. Accounts added, edited, removed,
enabled or disabled in the TUI's account manager appear in `/api/v1/dashboard`
immediately, and a **session-only** credential entered in that TUI (for example a
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

## Web frontend

[`web/`](web/) is a separate static Vite/React app that signs in with the API base
URL and a token and polls `/api/v1/dashboard`. It deploys to Vercel, Cloudflare or
Railway; see [web/README.md](web/README.md). For local development, run
`uv run usage api serve --demo --allow-origin http://localhost:5173` and
`npm run dev` in `web/`.

## Railway deployment (backend)

The root [`Dockerfile`](Dockerfile) builds an image with Python 3.12, this project,
Node.js 22 and pinned Claude Code, Codex and Grok Build CLIs, then runs
`sleep infinity`. Attach a volume at `/data` (`HOME=/data/home`), then
`railway ssh` in to log in to each CLI, add accounts, create a token, and start
`usage --api --api-host 0.0.0.0 --api-port "$PORT" --allow-origin https://<frontend> --trust-proxy --keepalive`
in tmux (one process; a session-only Claude Platform `sessionKey` entered in that TUI
feeds the API until the process exits). Headless `usage api serve` plus a separate
`usage-keepalive` remain available for file-backed logins only.
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
