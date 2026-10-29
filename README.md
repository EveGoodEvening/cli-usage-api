# Usage TUI

A local, read-only terminal dashboard for subscription usage and Claude Platform
credit balances. No web server or statusline.

**Status:** Offline demo and local account workflows are verified. Authenticated
provider reads and real OS-keyring persistence remain unverified. Provider
integrations use private, version-sensitive APIs.

## Quick start

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and an interactive terminal.
Linux/POSIX is the supported credential-import and persistence target.

```sh
uv sync --locked
uv run usage --demo   # Offline demo
uv run usage          # Live dashboard
```

Demo uses fictional data without reading account configuration, credentials, or
keyring, and makes no network requests. Use `--demo --scenario errors` to preview
error states. In live mode, press `a` to connect accounts.

| Key | Action |
|---|---|
| `a` | Manage accounts |
| `r` | Request refresh; retry limits still apply |
| Enter on a metric | View details and provenance |
| `?` | Help |
| Escape | Back / cancel |
| `q` / Ctrl-C | Quit dashboard / exit from any screen |

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

Missing values stay unknown, never zero. Failed reads retain last-known values
with freshness/error indicators; passing a reset does not invent new allowance.
Polling defaults to 60 seconds and is configurable from 30–3600 seconds.

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
refreshes tokens. Renew expired credentials through the first-party tool.
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

Legacy ChatGPT profiles require `uv run usage accounts migrate-chatgpt-to-codex`.
After explicit confirmation, replacements are disabled and credentials detached;
old keyring secrets remain unmanaged. Configure a Codex file reference, then enable.

## Credential safety

- Never put secrets in arguments, environment variables, labels, chat, or issues.
- Persistent manual-secret storage requires an unlocked, supported Linux Secret
  Service keyring. Plaintext and alternative backends are rejected.
- If secure storage is unavailable, choose **session only** in the TUI. Secrets
  disappear when the process exits; there is no silent storage fallback.
- Removing an account or stored key does not revoke its remote session.

Account metadata lives at `$XDG_CONFIG_HOME/usage-tui/accounts.json`, falling back
to `~/.config/usage-tui/accounts.json`; credential values are stored separately.
See [SECURITY.md](SECURITY.md) for boundaries and limitations.

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
