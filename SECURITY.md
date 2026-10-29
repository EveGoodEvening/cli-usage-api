# Security boundaries

## Current implementation: terminal dashboard and production CLI

This repository supplies package/domain, local storage, credential-resolution,
fixed-origin HTTP transport, Claude subscription, Console balance/discovery, Grok
billing, provider-registry, polling/freshness and offline-source libraries, a
Textual account manager/dashboard, and the production `usage` CLI. The corrected
scope is **Codex quota**, not ordinary ChatGPT chat usage. The atomic Codex cutover
is complete under PLAN.md §11: final integrated offline verification, four
independent implementation reviews and both final split reviews passed cleanly,
with no fixes required. No authenticated provider or real OS-keyring acceptance
is claimed. Exact exercised evidence remains in [PLAN.md](PLAN.md).

Domain records are not a secure storage service. A credential value excluded from a
representation is not encrypted or erased from process memory. Do not serialize
secrets into account references, labels, snapshots, provenance, or diagnostics. Use
synthetic data when exercising the domain library. Python cannot guarantee memory
zeroization.

Do not submit tokens, cookies, passwords, credential files, raw provider responses,
HAR files, or identifying account/billing data in issues, chat, or commits. Security
reports should describe the affected component and reproduction with synthetic data;
remove authentication and identity information before sharing. If a credential is
exposed, revoke or replace it through the relevant first-party service.

## Read-only HTTP API, web frontend and container deployment (PLAN.md §15)

Scope and threat model for `usage api serve`, the embedded `usage --api` mode,
`web/` and the root `Dockerfile`.
Implementation follows the PLAN.md §15 frozen contract; verification status is
recorded there, and no Railway deployment or authenticated live read is claimed.

**Assets.** Usage/balance snapshots and account labels (personal data), API bearer
tokens, and, on a container host, the first-party CLI login files on the volume.

**Boundaries and controls.**

- Read-only surface: only `GET`/`HEAD`/`OPTIONS`; no account, credential, token or
  configuration mutation over HTTP. Request bodies are not read. Unknown methods
  return `405`; unauthenticated unknown `/api/` paths return `401`, not `404`, so
  paths cannot be enumerated. `/healthz` is the only public path.
- Authentication: `Authorization: Bearer` only, never query strings or cookies.
  Tokens are `usk_` + 32 random bytes (URL-safe), shown once at creation in a TTY,
  and stored only as SHA-256 hashes in a private (`0700` directory / `0600` file),
  locked, atomically replaced `api_tokens.json`. Comparison uses
  `hmac.compare_digest` over every stored hash. The token file is re-read when its
  mtime changes (checked at most once per second), so revocation needs no restart.
  Live mode refuses to start without tokens; only loopback-bound demo may run
  unauthenticated, and only while the token file is readable and empty (rechecked
  per reload); creating a token enables auth without a restart. `--host localhost`
  binds `127.0.0.1`.
- Brute force: failed authentication is limited per client (10 per 60 s) and
  globally (100 per 60 s) with `429` and `Retry-After`; tracked clients are capped.
  A valid token is verified first and never consults or consumes the limiter, so a
  failed-auth flood cannot lock out legitimate token holders (256-bit tokens make
  the limiter a noise control, not the guessing defense). Cross-origin responses
  expose `Retry-After` and `WWW-Authenticate` to allowed origins.
  The client key is the socket peer, or with `--trust-proxy` the right-most
  `X-Forwarded-For` entry. Enable `--trust-proxy` only behind a proxy that sets that
  header; otherwise clients can choose their own limiter key. Railway's edge is
  reported (forum moderator answer, not formal documentation) to overwrite
  forwarding headers; this is unverified for this deployment.
- Browser access: CORS is granted only to exactly configured origins, never `*`
  and never with credentials. Every response carries `Cache-Control: no-store`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: DENY` and a `default-src 'none'; frame-ancestors 'none'` CSP.
  CORS is not authentication: a non-browser client with a valid token can read data.
- Data minimization: responses omit credential references/selectors and
  organization IDs (snapshot `organization_id` is nulled). Errors are fixed codes
  such as `{"error":"unauthorized"}` and never echo input. The server does not log
  `Authorization` headers.
- Transport security: the server speaks plain HTTP. Bind to loopback locally; on a
  network host terminate TLS in front of it (Railway's public domain does this).
  A token sent over plain HTTP on an untrusted network can be captured.
- Frontend: tokens live in `sessionStorage` by default, or `localStorage` only when
  "remember" is chosen; any script running on the frontend origin could read them,
  so the static app avoids `dangerouslySetInnerHTML` and ships a strict CSP. Logout
  clears both stores but does not revoke the token server-side; use
  `usage api token revoke`.
- Container host: the image contains no credentials. Login files, account
  configuration and token hashes live under `HOME=/data/home` (`0700`) on the
  volume; interactive bash shells use `umask 077`. There is no OS keyring, so
  manual/Console secrets cannot persist; Claude Platform works there only as a
  session-only credential in one-process mode (below).
  Anyone with `railway ssh` or volume access can read the first-party CLI logins,
  which are password-equivalent. The CLI versions are pinned; Grok's artifact
  checksums were computed on first download because xAI publishes none, so they
  detect later changes but do not establish the original artifact's authenticity.
  Claude Code and Grok self-updaters are disabled by non-secret environment flags.
- One-process mode (`usage --api`, PLAN.md §15.7): the API runs as a task in the
  dashboard's event loop and serves an observer mirror (`AppHub`) of the snapshots
  and account list the TUI shows; it never starts, stops or reconfigures the
  scheduler. The token, CORS, header and limiter controls above are the same code;
  live mode still requires a token. Consequence: a **session-only** credential
  entered in that TUI, including a Claude Platform Console `sessionKey`, now feeds a
  network-reachable API. The API returns only the same minimized views (no session,
  reference or organization ID), but the high-sensitivity account session sits in the
  memory of a process on a public host; anyone with shell or process-memory access
  there (for example `railway ssh`) may obtain it. It is lost on restart, redeploy or
  exit, expires upstream on its own schedule, is not renewed by keepalive, and local
  removal does not revoke it. On account changes the mirror drops all held snapshots
  (as the TUI does), so removed accounts' observations are not retained or served.
  uvicorn installs no signal handlers and its loggers are silenced (no handlers reach
  the terminal); the socket is bound before the TUI starts. The process still serves
  plain HTTP: terminate TLS in front of it.
- `--keepalive` (dashboard or `api serve`, live only) runs the opt-in
  `usage-keepalive` loop in the same process under its single-instance lock. It
  spawns the official CLIs (no TTY, output discarded) so they renew their own login
  files; logs (no token values) go to the private keepalive log only, plus stdout in
  headless `serve`; in the TUI, `ALERT` lines become notifications. Saved Grok
  accounts' selected scopes (or the legacy scope when none is selected) are protected
  from being marked stale.
- Local removal of a token or account never revokes provider sessions.

## Implemented C12 entry and CLI secret boundary

- `usage` and `python -m usage_tui` compose the live dashboard with one shared
  account store, credential store, resolver and provider/scheduler factory. The
  factory exposes the canonical bound async Console discovery callable; app
  teardown stops its source before awaiting factory cleanup, which stops any
  created schedulers. Transport HTTP clients are request-scoped, not leaked
  shared clients. Config load failures do not replace the existing file. Dashboard
  per-account failures stay in the UI; they are not a reason to substitute demo
  data. `--demo` branches before live dependency construction and reads the
  packaged synthetic scenario plus separate nonsecret UI theme preferences, never
  real accounts, keyring or credential files.
- Account/key commands accept opaque account IDs and nonsecret provider selection,
  not secret arguments or secret-bearing environment-variable configuration.
  CLI manual entry uses `getpass` and refuses echoed-input fallback. Every mutating
  account command requires TTY stdin and stdout; list remains noninteractive-safe.
  Replacement/deletion is confirmed. Ctrl-C, EOF or Escape then Enter cancels CLI
  prompts with status 0 and no pending writes; the TUI handles Escape directly.
  Do not pipe secrets, enable shell tracing or record the terminal session.
- CLI key persistence requires the exact supported encrypted Linux Secret Service
  backend; a locked/unsupported backend returns actionable guidance, not plaintext
  or ephemeral storage presented as durable. Explicit session-only entry is a TUI
  choice and shares the running app's credential store/resolver. It is lost on
  exit, regardless of whether nonsecret account metadata remains.
- API-key storage is local-only and does not authorize subscription or Console
  requests. Console `sessionKey` entry remains a high-sensitivity account-session
  operation, never a password, full Cookie header, HAR import or limited API key.
  Imported first-party files are read-only; local removal does not revoke remote
  sessions or delete those files.
- Exit status 0 denotes success/normal dashboard quit, 2 usage/config/secret-input
  errors, and 3 credential/backend/provider-connection failures. Errors must remain
  fixed safe messages, not raw exceptions, file contents or upstream bodies.
- The production-entry PTY harness uses isolated temporary HOME/XDG state and
  synthetic demo scenarios. It does not establish live metric, real-keyring or
  authenticated acceptance. Its captures must be sanitized and its child process
  bounded, killed/reaped on failure, and terminal settings restored.
- UI theme preferences live in `settings.json` beside `accounts.json`, with a
  private `0700` directory, `0600` files, a stable sibling lock, and atomic
  replacement. Live/demo modes share preferences, not account data. Startup never
  rewrites the stored theme; unavailable themes or invalid settings warn and use
  nord. Failed saves warn without crashing the dashboard or claiming persistence.

## Implemented C11 dashboard boundary

- `UsageApp` is a terminal UI, not a web service or a new HTTP/authentication
  implementation. Live access is supplied explicitly through an injected source
  factory; the dashboard must not infer credentials from account labels or bypass
  the provider/transport restrictions above. The CLI supplies production composition.
- Demo mode constructs the packaged offline source, not live stores, credential
  resolution, transport, or clients. Its account screen is read-only. The DEMO
  banner and synthetic Codex warning distinguish examples from authenticated support;
  demo samples are never a fallback for a failed live request.
- Rendered labels, diagnostic/detail text, organization/grant identifiers, and
  provenance must be treated as display data, with control-character removal,
  bounded lengths, and markup disabled. Do not add raw response/exception display,
  credential suffixes, clipboard actions, or secret-bearing notifications.
- Successful-observation time is distinct from attempt time. Stale and last-known
  labels survive errors; a local countdown tick performs no provider request and
  cannot zero usage or infer a new period. Passed resets await refresh, while
  grant expiry remains expiry, not a renewed quota. Refresh delegates to the source
  so retry embargoes, coalescing and concurrency limits remain scheduler-owned.
- Committed account changes reach source `update_accounts`; reconnect requests
  reach source `refresh`. Source shutdown must finish before owned injected client
  cleanup. Borrowed resources remain their owner's responsibility. Neither demo
  rendering nor lifecycle wiring establishes live provider or secure-keyring
  acceptance. Exact exercised checks belong in PLAN.md.

## Implemented C10 terminal account-input boundary

- `AccountManagerScreen` is a reusable Textual screen, not a dashboard or a CLI
  secret prompt. New secrets use masked keyboard input, begin empty even when
  editing a saved account, and have no reveal/copy control. Pending secret values
  are cleared on every submit attempt (including failures), cancel, and teardown.
  Replacement confirmation opens after field clearing; canceling it leaves the
  field empty. Replacement, key deletion, and account removal require confirmation.
  Escape cancels a form without committing partial edits.
  Masking does not defeat clipboard exposure, terminal recording, same-user code,
  or process-memory inspection; Python cannot promise zeroization.
- Persistent and session-only storage are explicit choices. Unsupported/locked
  secure backends return actionable errors without silently switching to memory
  or plaintext. A session-only value lasts only in its owning `CredentialStore`
  instance/process; a saved nonsecret profile does not preserve that credential
  across exit. Share that store instance with the resolver in the embedding app.
- Before the masked Console-session input, the form displays: "High-sensitivity
  account session: enter only the sessionKey value. Do not enter your password,
  a full Cookie header, or a HAR file." No browser extraction is supplied.
  Discovery runs only when requested, using the injected async callable; users explicitly choose an
  eligible organization even for a singleton. Console session replacement requires
  newly discovered explicit selection rather than fallback to the previous scope.
  Grok scope choices use numbered display labels, not arbitrary auth-file key names,
  and bind the intended imported identity instead of guessing among ambiguous profiles.
- Local API-key management does not authorize OAuth/session reads. Codex permits
  only `codex_auth_file`, not manual bearer or API-key storage. No cookie/password,
  browser login, refresh protocol or login subprocess is supplied. Reconnect directs
  renewal to the first-party tool outside the app.
- Confirmed removal affects only this tool's account metadata and locally stored
  secret. Key deletion can retain the local account for reconnect. External
  Claude/Grok/Codex login files are never removed; no action revokes remote sessions.
  Config and keyring are separate stores, not an atomic transaction; errors must
  remain visible. A post-replacement directory-sync failure raises
  `ConfigCommittedError` with the committed accounts, not a rejection or rollback.
  The service preserves both new and previous credentials on this durability warning
  (and preserves removed accounts' old credentials): new config is visible, but crash
  recovery may restore old config. It skips destructive cleanup and reports the
  committed accounts through `AccountFlowError.updated`; the screen forwards them
  to the host even while showing the warning. A rejected write instead rolls back
  its newly created credential and sends no account-change notification.
  The host must forward committed account updates to the scheduler to cancel obsolete
  fetch generations; a screen alone does not own live polling.
- Read-only demo viewing takes injected accounts and must not touch account files,
  imported credentials, or keyring. No actual account credential, live-provider,
  real-keyring, or terminal acceptance is claimed by this documentation task.

## Implemented C02 local persistence boundaries

- `AccountStore` stores schema-versioned nonsecret account metadata and opaque
  credential references, not credential values or provider response bodies. The
  default path is `$XDG_CONFIG_HOME/usage-tui/accounts.json`, falling back to
  `~/.config/usage-tui/accounts.json`; callers may supply an isolated path.
  Inline manual secrets and persisted references bound to another account are
  rejected. The store neither opens nor modifies external first-party credential
  files; read-time import checks belong to `CredentialResolver`.
- POSIX config operations use an owner-only `0700` directory, `0600` config/lock
  files, bounded 1 MiB reads, and regular-file ownership/mode checks. Symlinks and
  hardlinks are rejected. Invalid/newer-schema existing config is not overwritten.
  Config validation is separate from the credential resolver's import checks.
- A stable sibling lock file carries the advisory lock while the config is
  atomically replaced in the same directory. `mutate` rereads under that lock and
  writes only after its callback succeeds. Callers must use it for read-modify-write
  changes: separate `load` and `save` calls do not form one transaction. Locks
  coordinate cooperating writers, not malicious same-user processes.
  An error after replacement (for example directory-sync failure) leaves the new
  config visible but crash durability uncertain. `ConfigCommittedError`, a
  `ConfigError` subtype, carries that committed account tuple; atomic replacement
  does not make every save failure a rollback.
- Persistent credential operations lazily accept only the exact supported Linux
  `keyring.backends.SecretService.Keyring` backend type. Plaintext/alternative,
  null/fail, chained, unknown, and subclassed backends are not accepted based on
  names or priority. A locked/unavailable backend raises a safe `CredentialError`;
  persistence never silently falls back to plaintext or session memory. This
  backend policy is not evidence that a real Secret Service was exercised.
- Explicit `persist=False` uses only instance-local session memory, without
  probing the OS keyring. Session references are lost with that store instance or
  process. Python cannot guarantee zeroization; session-only mode still exposes
  secrets to process-memory risks. Opaque references contain no credential value
  but do not defend against code already running with the user's privileges.
- Store failures use fixed safe `ConfigError`/`CredentialError` messages instead
  of interpolating backend exception text, secret values, or local paths.
  Deleting a stored credential touches only this tool's local store, not external
  login files or remote sessions. The C10 account manager coordinates the separate
  metadata and local-credential operations; neither store provides a cross-store
  atomic transaction.

## Implemented C03 credential-resolution boundary

- `CredentialResolver.resolve(account)` returns a frozen credential with explicit
  provider/kind binding, secret excluded from repr, and an opaque generation
  fingerprint local to the resolver instance. It is captured once per attempt;
  never relabel an old credential after replacement or expose a fingerprint as a
  public token identifier. Manual secrets come from `CredentialStore` references.
- Imported references are literal local paths, not commands or URLs. The explicit
  `default` reference resolves Claude's `$CLAUDE_CONFIG_DIR/.credentials.json` or
  `~/.claude/.credentials.json`, and Grok's `$GROK_HOME/auth.json` or
  `~/.grok/auth.json`, at resolution time. Construction does not read login files.
- On Linux/POSIX, imported files are opened read-only with no-follow/nonblocking
  flags and descriptor validation: regular file, effective-user ownership, exact
  `0600` mode, and at most 1 MiB. Unsafe files are rejected, not chmodded or copied
  into a less protected location. These checks are not a defense against hostile
  code already running as the same user. Cross-platform import is not supported.
- Claude imports validate `claudeAiOauth.accessToken`, optional millisecond expiry,
  and optional scopes; supplied scopes must include `user:profile`. Grok imports
  select an exact saved scope or an unambiguous modern auth scope, falling back
  to the legacy sign-in scope only without modern candidates. Identity metadata
  comes from that same entry, never another profile. Expired credentials fail;
  absent expiry remains unknown and malformed supplied expiry is a schema error.
- Only required access/identity metadata is returned. Refresh tokens are not copied
  into application storage; no first-party file is written, deleted, refreshed,
  or permission-modified. Users run official login/renewal outside this tool.
  No browser extraction, subprocess login, or token-refresh protocol is implemented.
- Errors expose curated codes/state/diagnostics, not secret values, local paths,
  raw parse failures, or arbitrary exception text. Synthetic fixtures do not prove
  live credential eligibility or upstream compatibility.

## Implemented C03 HTTP boundary

- Async `Transport.get_json` permits only fixed-origin HTTPS GET routes, with
  provider and credential-kind checks before authentication construction or I/O:

  | Provider | Origin | Allowed path | Credential kinds |
  |---|---|---|---|
  | Claude subscription | `https://api.anthropic.com` | `/api/oauth/usage` | `claude_code_file`, `manual_bearer` |
  | Claude Platform | `https://platform.claude.com` | `/api/organizations`, `/api/organizations/{id}/prepaid/credits` | `console_session` |
  | Grok subscription | `https://cli-chat-proxy.grok.com` | `/v1/billing?format=credits` | `grok_auth_file`, `manual_bearer` |
  | Codex | `https://chatgpt.com` | `/backend-api/wham/usage` | `codex_auth_file` only |

  Console IDs must match `[A-Za-z0-9-]{1,64}`. No arbitrary origin/path, URL
  override, API-key substitution or ordinary-ChatGPT quota request is permitted. The injected
  in-memory HTTP test transport does not relax production URL/path checks.
- Claude subscription sends Bearer plus `anthropic-beta: oauth-2025-04-20`.
  Console sends only `Cookie: sessionKey=<value>` authentication, never that cookie
  to another Anthropic service. Grok sends Bearer plus
  `x-xai-token-auth: xai-grok-cli`; optional `x-userid` belongs to the same resolved
  credential. Grok's `x-grok-client-version: 1.0.70` is release-pinned from the
  official stable feed; requests retain the identifying `usage-tui` User-Agent.
- Codex has an explicit authentication branch: Bearer from `tokens.access_token`
  and `ChatGPT-Account-Id` from the same stable file read, never Grok headers,
  cookies or query parameters. Provider and transport independently enforce binding
  before constructing headers or opening a socket. Neither selected ID nor bearer
  is copied into config, provenance, diagnostics or public representations.
- A Console value is a high-sensitivity session credential, not a limited API key.
  Invalid cookie controls/delimiters are rejected; full Cookie headers, passwords,
  and HAR imports are not supported. Console discovery returns candidates, not an
  automatic selection; the C10 connection screen obtains explicit confirmation.
- TLS verification is enabled; redirects and implicit proxy/netrc inheritance
  are disabled. Each request has a fresh client, so response cookies do not carry
  over. Requests identify the installed package and accept JSON. There is no raw
  HTTP debug mode, telemetry, endpoint configuration, or response cache.
- Connect timeout is 5 seconds; the overall request deadline is 10 seconds.
  Decoded response data is streamed with a 1 MiB bound. The result is parsed JSON;
  adapters independently validate its schema and metric semantics.
- `TransportError` contains only fixed safe code/fetch state, optional status and
  retry time. Upstream bodies, credential paths, secrets, and arbitrary exceptions
  never become its diagnostic text. A valid 429 `Retry-After` has at least a
  60-second delay and is not shortened to a scheduler cap. Transport does not poll;
  retry scheduling is implemented separately by the C08 scheduler.

## Implemented C04 Claude provider boundary

- `ClaudeProvider(transport)` performs no construction-time I/O. Its async
  `fetch(account, credential, now)` requires a Claude subscription account and a
  provider-bound eligible credential; the injected transport independently enforces
  provider/kind binding, fixed origin/path, and authentication rules. A fetch uses
  one GET to `/api/oauth/usage`, never inference or credit-balance endpoints.
- The OAuth usage route is private and version-sensitive. A working parser or mock
  transport does not establish permission to read a particular live account.
  First-party login, profile scope, and expiry requirements still apply; the
  adapter does not refresh tokens, modify login files, or broaden credential scope.
- Upstream fields are untrusted metric data, not user-facing error text. All three
  metric rows remain present; missing/invalid windows are unknown, not zero, and
  valid siblings survive partial responses. A wholly unusable response is a schema
  error, not successful empty usage. Invalid reset data preserves a valid quota but
  cannot supply a reset. This prevents malformed data from implying spare capacity.
- Fable is a scoped weekly subset, not extra capacity. An inactive scoped entry can
  still carry valid usage; conflicting valid duplicates are not arbitrarily chosen.
  Missing Fable is not evidence of eligibility/ineligibility, and Opus/Sonnet data,
  extra-usage balances, or a presumed half-week allowance cannot fill the gap.
- Numeric reset normalization is local to this adapter: positive Unix seconds,
  with values at least `10^11` treated as milliseconds. Timezone-free strings are
  invalid. No response field changes the request destination, auth headers, or
  credential selection. Snapshots carry normalized metrics, not raw response bodies.

## Implemented C05 Console provider boundary

- `ConsoleProvider(transport)` performs no construction-time I/O. Its separate async
  `discover_organizations(credential)` returns candidate `OrganizationChoice` values
  (`id`, sanitized `label`), never saves an account or selects even a sole candidate.
  Candidates need exact `api` capability and an ID matching `[A-Za-z0-9-]{1,64}`.
  Invalid candidate schema or duplicate IDs produce a safe schema error rather
  than ambiguous organization selection.
- `fetch(account, credential, now)` requires a Claude Platform account and a
  provider-bound `console_session`. It reads credits only for the account's selected
  organization, with no polling-time discovery or automatic fallback. A supplied
  credential organization binding must match. Missing selection requires explicit
  organization selection; inaccessible organizations require reselection/permission
  guidance, not silent substitution. HTTP 401 or discovery 403 means reconnect;
  selected-organization credits 403 means billing permission denied.
- A Console `sessionKey` is a high-sensitivity session, not a limited API key.
  Users sign in outside the application and supply only their own cookie value;
  do not collect passwords, HARs, full Cookie headers, or browser-store contents.
  Use `CredentialStore` secure persistence or explicit nonpersistent session-only
  storage, not account JSON. The C10 screen warns before accepting a session;
  a library adapter alone does not provide that interaction. Local secret deletion
  is not remote session revocation.
- Discovery/credits use private, version-sensitive Console contracts at
  platform.claude.com only. No session goes to api.anthropic.com or claude.ai;
  transport independently enforces exact destination, kind, and cookie-value
  validation. No response field can redirect authentication or select another org.
- All three balance rows remain present. Purchased/promotional totals use their
  complete validated grant arrays independently; missing/null is unknown, explicit
  empty is zero, and invalid numeric grant data invalidates that category only.
  Exact integer minor units retain negative balances and zero grants. Authoritative
  top-level total is independent, not a derived sum or an invented missing category;
  discrepancies remain visible. Program IDs annotate grants, not subscription quota.
- Known-expired grants do not contribute to active category totals. Unknown or
  malformed expiry is included with uncertainty, never asserted unexpired. Grant
  details preserve amounts and known expiry; nearest known active expiry is not a
  fabricated renewal/reset. Names/programs are untrusted display metadata, not raw
  diagnostics. Snapshots contain normalized values rather than response bodies.
- Neither API-key substitution nor `/current_spend`/Admin reporting fills a missing
  balance. A synthetic parser fixture does not establish live billing permission,
  session validity, or compatibility; those require separate authenticated acceptance.

## Implemented C06 Grok provider boundary

- `GrokProvider(transport)` performs no construction-time I/O. Async
  `fetch(account, credential, now)` requires a Grok subscription account and its
  provider-bound `grok_auth_file` or `manual_bearer`; API/management keys beginning
  `xai-` are not subscription credentials. Each eligible fetch makes one direct
  GET to `https://cli-chat-proxy.grok.com/v1/billing?format=credits`. Transport
  independently enforces origin/path and credential kind/provider binding.
- This official-CLI proxy request and observed product fields are private and
  version-sensitive, not a public billing API guarantee. Bearer plus
  `x-xai-token-auth: xai-grok-cli` is used; optional `x-userid` comes from the same
  resolved credential. The sourced compatibility-version header is pinned to
  `1.0.70`, not downloaded at runtime; no upstream User-Agent or client-mode
  impersonation is added. Response fields cannot change destination,
  authentication, identity selection, or account binding.
- Users run `grok login` outside the app. The resolver reads a selected scope in
  `$GROK_HOME/auth.json`, `~/.grok/auth.json`, or an explicit private local file;
  ambiguous identities require a nonsecret selector. It does not write, delete,
  chmod, refresh, or copy first-party login files or refresh tokens. Unknown expiry
  is not asserted fresh; unsupported team-principal responses must not cause a
  switch to another personal identity. No browser extraction or login subprocess.
- All three required rows remain visible. An omitted percentage scalar is zero
  only in an explicit weekly period with a validated reset (the private schema's
  omitted-default convention). Explicit null/invalid scalars and missing products
  remain unknown; empty/arbitrary configs do not establish zero. Product breakdown
  requires a wholly valid unique-product array and usable same-response aggregate,
  but no unsupported sum-to-total invariant. Unknown products retain sanitized IDs;
  duplicate/malformed shares do not invalidate independent aggregate evidence.
  No values are blended across accounts/requests; wire decimals stay exact.
- Only `config.isUnifiedBillingUser == true` establishes the common included pool.
  Build/Chat percentages are consumed shares, never independent remaining quotas.
  Product remaining/reset refer to the shared pool only with positive evidence;
  otherwise the relationship and product remaining/reset are unknown. Neither
  on-demand spend nor prepaid balance establishes included usage.
- Server period type determines weekly/monthly labeling. Reset uses aware
  `currentPeriod.end`, falling back to `billingPeriodEnd` only if end is absent;
  invalid/reversed bounds cannot invent a reset. Valid usage survives invalid reset
  metadata. No hardcoded renewal, reset-coupon lookup, legacy cap estimate, ACP/gRPC
  substitution, or raw-response persistence is implemented. Polling/retries belong
  to the separate C08 scheduler, not this adapter.
- Synthetic responses do not establish live subscription eligibility, credential
  acceptance, or private-proxy compatibility. No live or CLI/TUI acceptance follows
  from this library or documentation.

## Implemented Codex security contract — verified offline, live unknown

- Registry construction/imports do not read credentials, probe the environment or
  issue requests. `CodexProvider.requires_credential=True` uses the ordinary
  credentialed scheduler path; historical C07's blocked capability is removed.
- Read only an existing private file: `$CODEX_HOME/auth.json` when CODEX_HOME is
  nonempty, otherwise `~/.codex/auth.json`, or an explicit selected file. Preserve
  owner/mode/no-follow/size/stability checks. Keyring-only, auto-without-file and
  ephemeral Codex storage are unavailable. Outside this app, configure Codex's
  `config.toml` with `cli_auth_credentials_store = "file"` and run `codex login`
  for first-party ChatGPT sign-in, as documented in the official
  [authentication guide](https://developers.openai.com/codex/auth). Managed policy
  may prohibit that storage choice. No force-file CLI flag is assumed. The app
  does not probe Codex keyring or launch Codex; verification used only synthetic
  private auth files, never real Codex auth files or user secrets.
- Bearer is only `tokens.access_token`; selected account is `tokens.account_id`,
  falling back only when absent to decoded ID-token payload
  `["https://api.openai.com/auth"]["chatgpt_account_id"]`. Invalid explicit ID is
  an error, not permission to fall back. Reject missing/malformed bearer/account,
  wrong types, `auth_mode="api_key"` and nonempty `OPENAI_API_KEY`. No scope-list
  requirement, organization/label/local-ID inference or Grok identity reuse.
- Unverified JWT decoding extracts provenance/expiry hints, **not signature
  verification or an authentication trust boundary**. Access-token `exp` is Unix
  seconds; expired/malformed expiry requires reauthentication, missing expiry is
  unknown. Server rejection remains authoritative. Never use `last_refresh` as
  expiry, use refresh tokens for auth, rewrite/refresh the file or log claims/errors.
- Weekly is the main 604800-second window regardless of slot; optional 18000-second
  and other windows/pools remain separate. Missing usage is unknown; enforcement
  flags do not imply 100%. Absolute `reset_at` seconds is canonical; no timestamp
  from relative reset, no milliseconds guessing. Preserve valid usage independently
  of invalid reset and retain valid siblings when others are malformed/conflicting.
  Credits/spend/code-review/reset-credit quantities are not the main quota.
- The source is private/version-sensitive `codex.wham.usage.v1`, not a public API
  guarantee. Static official-source evidence and synthetic fixtures do not establish
  an authorized live read or same-account weekly/reset comparison.
- Legacy `chatgpt_subscription` config fails closed with repair guidance, not silent
  relabel/reset. Only real-TTY `usage accounts migrate-chatgpt-to-codex` with explicit
  whole-set confirmation performs the lock/reread/atomic migration. Preserve local
  identity/polling and other providers; replacements are **disabled and detached**.
  No `--yes`, non-TTY consent or startup/TUI auto-migration. Decline/cancel writes
  nothing. Old keyring secrets stay **retained, detached and unmanaged**: migration
  never reads, reuses, transmits or deletes them, calls the secret backend or deletes
  external files. Separate deliberate owner/backend deletion is not migration
  cleanup. Configure file-backed auth before enable.
- The orchestrator's final `uv sync --locked --group dev` succeeded; 1,098 tests
  passed in 30.20 seconds, Ruff lint and 44-file formatting passed. Earlier clean
  diagnostics for all 17 source files apply to unchanged source. Synthetic
  resolver → provider → transport and actual Scheduler initial/manual/two-interval,
  retry embargo, last-known/reset-stale, replacement/removal/stop proofs passed.
  Offline demo produced 4 healthy / 8 error snapshots; four installed-entry demo
  PTY runs rendered and restored terminals on quit/Ctrl-C. Installed-CLI real-PTY
  proof exercised unchanged decline/cancel/non-TTY paths, affirmative mixed-config
  migration, file-backed edit/reconnect, enable/disable and empty-live/account
  flows. Isolated installed account listing exited 0 with no accounts; installed
  help passed. Four implementation reviews and two final split reviews were clean,
  requiring no fixes. No real auth files, user secrets, network or keyring were
  used. These completed offline security/behavior proofs do not establish a
  supported public API or same-account live quota comparison; authorized live
  acceptance remains unexercised. Historical ordinary-chat blockers are not active
  Codex blockers.

## Implemented C08 scheduler boundary

- Each live attempt captures one immutable resolved credential. Account updates
  invalidate previous work even when an opaque credential reference is reused;
  removed/disabled/replaced account work is cancelled and obsolete late results
  cannot publish as the current generation. External credential-file changes are
  read on the next attempt, not monitored in the background. Call `update_accounts`
  when replacing a credential during a fetch. Cancellation is not remote revocation
  and does not delete first-party login files.
- At most two accounts fetch concurrently, one per account, with at least five
  seconds between fetch starts sharing an origin. Manual refresh coalesces and is
  an explicit reconnect attempt; it does not bypass origin spacing or retry
  embargoes. Authentication/permission/unconfigured failures suspend automatic
  polling; only explicit refresh or account update resumes it.
- Retry deadlines use monotonic time. Longer server `Retry-After` deadlines are
  not truncated by the local exponential-backoff cap, and same-provider account
  updates do not erase an embargo. Retries remain read-only provider fetches,
  never token refreshes, login subprocesses, purchases, or reset actions.
- Claude subscription automatic polling and error retries honor a 180-second
  effective minimum and longer configured intervals without rewriting saved
  configuration. Its 429 backoff starts at 180 seconds, grows to 360/720/900 plus
  jitter, and cannot shorten a server deadline. Freshness uses the same effective
  cadence. Explicit manual refresh may bypass the periodic interval, never an
  embargo. This is a conservative local policy, not a proven upstream rate limit.
- Codex uses normal credentialed polling, manual refresh, stale-state, retry and
  cancellation semantics; no historical credential-free blocked exception remains.
- Error snapshots retain last-good values with their old success time and new
  safe error/attempt metadata. Compatible responses (including partial ones)
  replace current fields; absence cannot masquerade as current old usage. Stale
  and passed-reset information is separate from raw metric state; timers never
  synthesize fresh quota or reset values to zero.
- `stop()` cancels scheduler-owned tasks and discards obsolete results. Injected
  providers/transports are borrowed; their owner must close resources they own.
  The current Transport already closes its client per request. The scheduler adds
  no daemon, logging or raw-response persistence; the CLI/dashboard own composition.

These are library controls, not authenticated polling or end-to-end application
acceptance. This documentation task ran no checks or requests; exercised evidence
remains the orchestrator's separate PLAN.md record.

## Implemented C09 deterministic offline-source boundary

- The offline source reads only the packaged synthetic
  `usage_tui/fixtures/demo.json` resource. It does not load account configuration,
  probe HOME/XDG or first-party credential files, access the keyring, resolve a
  credential, build the live provider registry, construct a live transport/client,
  or send network requests. It is explicitly selected, never a fallback after a
  failed live fetch. Packaged fixture access is not a claim of zero file I/O.
- Both `healthy` and `errors` scenarios use fictional account labels/IDs, normalized
  domain snapshots, `offline_demo` provenance, and a fixed demo observation time.
  All samples are synthetic, including ready Codex weekly and optional windows.
  They demonstrate neither an authorized WHAM read nor authenticated compatibility.
- Error, partial, retry, unknown, and stale last-known samples are display inputs,
  not actual provider responses or authenticated observations. Advancing a demo
  clock does not renew an allowance, retry a provider, or access a saved secret.
- Source test assertions forbid storage/resolver/HTTP construction; test source is
  not passing-check evidence. The dashboard and production CLI compose this source
  for `usage --demo` and `usage --demo --scenario errors`. This documentation task
  executed no checks or smoke; exercised isolation evidence belongs in PLAN.md.

## Production CLI controls — not authenticated acceptance guarantees

The implemented CLI/dashboard composition preserves these controls. Its local
verification does not establish authenticated provider or real-keyring acceptance:

- Codex accepts only its file-backed login and selected account; no manual/API-key
  substitution. Other providers' API-key storage does not enable subscription/balance reads.
- Require explicit organization/profile selection and warn before accepting only a
  Console `sessionKey` value. Provider adapters validate response semantics.
- Present secure persistence versus session-only choices honestly and provide
  actionable errors. CLI manual secrets require the secure keyring; session-only
  entry is an explicit TUI choice and is never described as persistent storage.
- Never accept secrets as command arguments or documented secret-bearing
  environment variables. Use masked interactive inputs without history, saved-value
  prefill, or reveal/copy controls, and refuse secret input without a TTY.
- Preserve the dashboard's account-management-to-scheduler cancellation wiring.
  Removal must not delete external login files or claim remote revocation. Keep
  logs off by default and restrict any logs to safe codes/local opaque account IDs,
  never raw responses or identity.

No live metric or credential-safety acceptance follows from fixtures, installation,
or the offline source. Private provider contracts can change without notice.
Codex's official-source contract makes implementation actionable, not live-accepted.
See PLAN.md §11 for exact current scope, integrated proof and separate live acceptance;
other providers' existing security and live prerequisites remain unchanged.
