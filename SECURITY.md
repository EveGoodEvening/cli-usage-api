# Security boundaries

## Current implementation: Python libraries, not a live application

This repository supplies package/domain, local storage, credential-resolution,
fixed-origin HTTP transport, Claude subscription, and Console balance/discovery
provider libraries. It does not implement ChatGPT/Grok adapters, polling, interactive
account management, a CLI, or a TUI. A declared future console entry point does not
provide these features.
No authenticated provider or real OS-keyring check was exercised by this
documentation task; implementation evidence and orchestrator verification remain
separate in [PLAN.md](PLAN.md).

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
  An error after replacement (for example directory-sync failure) may leave the
  new config visible; atomic replacement does not make every save failure a rollback.
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
  login files or remote sessions. Account metadata removal and credential deletion
  remain separate library calls until the account-management integration exists.

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

  Console IDs must match `[A-Za-z0-9-]{1,64}`. No arbitrary origin/path, URL
  override, API-key substitution, or ChatGPT request is permitted. The injected
  in-memory HTTP test transport does not relax production URL/path checks.
- Claude subscription sends Bearer plus `anthropic-beta: oauth-2025-04-20`.
  Console sends only `Cookie: sessionKey=<value>` authentication, never that cookie
  to another Anthropic service. Grok sends Bearer plus
  `x-xai-token-auth: xai-grok-cli`; optional `x-userid` belongs to the same resolved
  credential. No guessed upstream client-version headers are added.
- A Console value is a high-sensitivity session credential, not a limited API key.
  Invalid cookie controls/delimiters are rejected; full Cookie headers, passwords,
  and HAR imports are not supported. Console discovery returns candidates, not an
  automatic selection; the later connection UI must obtain explicit confirmation.
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
  60-second delay and is not shortened to a scheduler cap. Transport does not poll
  or implement the future scheduler's retry loop.

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
  storage, not account JSON. The future UI must warn before secret acceptance;
  that end-to-end interaction is not implemented by a library adapter. Local secret
  deletion is not remote session revocation.
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

## Planned integration controls — not end-to-end guarantees

The libraries above do not establish a working authenticated application. Later
chunks must connect them without bypassing their boundaries:

- Do not resolve saved secrets or request transport for the unresolved ChatGPT
  capability. API-key storage does not enable subscription or balance retrieval.
- Require explicit organization/profile selection and warn before accepting a
  Console session secret. Provider adapters must validate response semantics.
- Present secure persistence versus session-only choices honestly and provide
  actionable errors; never describe memory as persistent storage.
- Never accept secrets as command arguments or documented secret-bearing
  environment variables. Use masked interactive inputs without history, saved-value
  prefill, or reveal/copy controls, and refuse secret input without a TTY.
- Cancel obsolete in-flight account work. Account removal must not delete external
  login files or claim remote revocation. Keep logs off by default and restrict
  any logs to safe codes/local opaque account IDs, never raw responses or identity.

No live metric or credential-safety acceptance follows from fixtures, installation,
or a future offline demo. Private provider contracts can change without notice.
Ordinary ChatGPT weekly usage remains blocked by an unresolved read/authentication/
metric contract, not merely missing credentials; WHAM/Codex is not a substitute.
See PLAN.md §§4–5 and §9 for exact boundaries and separate live acceptance.
