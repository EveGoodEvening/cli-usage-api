# Changelog

## Unreleased

### Changed — Codex atomic cutover implemented and verified offline

- User-corrected GPT scope is Codex quota, not ordinary ChatGPT chat-model usage.
  The single cutover authorized by reviewed planning commit `e3190b9` is implemented.
  Integrated offline checks and synthetic/terminal proofs passed; independent
  implementation review, draft closure and authorized live comparison remain pending.
- Replaced the old runtime provider/CLI identity with `codex_subscription` /
  `codex-subscription`, file-only `codex_auth_file`, and the private version-sensitive
  WHAM usage contract. Default login reference uses `$CODEX_HOME/auth.json` when
  CODEX_HOME is nonempty, otherwise `~/.codex/auth.json`; no manual bearer, API-key
  or Codex-keyring fallback.
- Main weekly quota follows 604800-second duration, not primary/secondary position;
  5h and other reported windows/pools are optional distinct extras. Use absolute
  `reset_at` seconds, never a timestamp invented from relative reset or plan name.
- Explicit TTY `usage accounts migrate-chatgpt-to-codex` requires whole-set consent,
  disables and detaches legacy profiles, preserves other providers/local identities,
  and retains old secrets detached/unmanaged without reading, reusing, transmitting
  or deleting them.
- Post-cleanup orchestrator gate: **1,098 tests passed in 28.59 seconds**, Ruff lint
  passed, the **44-file** formatting check passed, and all **17 source files** had
  clean language-server diagnostics. Installed `usage --help` passed.
- Synthetic auth resolver → Codex provider → transport smoke passed. Actual
  Scheduler proof passed initial/manual refresh, two scheduled intervals, retry,
  stale state, replacement/removal and stop. Offline demo component smoke passed
  **4 healthy / 8 errors snapshots**.
- Actual installed-CLI real-PTY proof passed migration decline/cancel/non-TTY
  unchanged paths, affirmative mixed-config migration, file-backed edit/reconnect,
  enable/disable and isolated empty-live/account flows. Four installed-entry
  healthy/errors PTY runs rendered and restored terminals on normal quit and Ctrl-C.
- No real Codex auth files, user secrets, network or keyring were used. The private
  source is not a supported public API; authenticated compatibility and same-account
  weekly/reset comparison remain unknown, not established by synthetic proof.
- README/security/CLI setup and repo-root Lessons reflect the implemented scope.
  Entries below are **historical pre-Codex evidence** within their original scopes;
  old ordinary-ChatGPT blockers are not current Codex blockers, and the historical
  851-test/PTY results are not this cutover's gate.

### Fixed and verified offline — final split review correction `d653397`

- Final split review completed four independent slices: three clean, one P2
  finding. Additional Grok product metrics survived the provider/scheduler path
  but were omitted by the dashboard's required-ID-only enumeration.
- Supplied actual UsageApp/Pilot synthetic-extra-snapshot evidence emitted four
  Grok metrics while overall visible rows stayed **10 → 10**. This is an exercised
  offline UI reproduction, not an authenticated-provider check.
- Correction `d653397` keeps all required rows first and appends deduplicated
  snapshot extras in emission order, using existing selectable details/provenance
  and shared-pool semantics. Refresh adds/removes extras while preserving selected
  metric identity and account filtering. Both independent post-fix rereviews were
  clean.
- Post-fix orchestrator evidence: `uv sync --locked --group dev` succeeded;
  **851 tests passed in 28.90 seconds**; Ruff lint and the **43-file** formatting
  check passed; all **17 source files** had clean language-server diagnostics.
- Installed `usage --help` passed. Four installed-entry-point real-PTY demo runs
  covered healthy/errors rendering with normal quit and Ctrl-C; all four confirmed
  terminal restoration. Separate installed-CLI real-PTY acceptance passed local
  account CRUD, cancellation, non-TTY mutation refusal without writes, and empty
  live dashboard/account-manager navigation with Back, `q`, and Ctrl-C.
- An additional installed-CLI real-PTY check displayed the extra Grok product
  `Other10` with selectable provenance; refresh removed the extra while retaining
  required rows, and the application exited cleanly.
- These historical checks did not exercise authenticated providers or real
  OS-keyring persistence. At that time ordinary ChatGPT remained contract-blocked
  and 13 acceptance tasks were open. PLAN.md §11 now supersedes the GPT tasks with
  Codex implementation/proof and separate authorized live acceptance.

### Verified — historical C14 offline acceptance (before `d653397`)

- Orchestrator evidence: `uv sync --locked --group dev` succeeded; 849 tests
  passed in 27.81 seconds; Ruff lint and the 43-file formatting check passed;
  all 17 source files had clean language-server diagnostics.
- This 849-test run predates the correction; the current post-fix evidence is
  recorded above.
- The installed `usage --help` succeeded. Four installed-entry-point real-PTY
  demo runs covered healthy/errors rendering with normal quit and Ctrl-C;
  all four confirmed terminal restoration.
- Separate installed-CLI real-PTY acceptance passed local account CRUD,
  cancellation, non-TTY mutation refusal without writes, and empty live dashboard
  account-manager navigation with Back, `q`, and Ctrl-C.
- Reconciled README's usable offline/local workflows with the remaining boundary:
  no authenticated provider requests, real OS-keyring persistence, or user-secret
  supply/import were exercised. Private Claude/Grok compatibility remains
  unexercised; ordinary ChatGPT weekly retrieval remains upstream-contract-blocked,
  not merely unconfigured. Users configure their own accounts through the TUI's
  masked prompts, not by sharing credentials in chat.

### Changed — C13 operator documentation reconciliation

- Added a Chinese terminal-only quickstart and clarified locked `uv` installation,
  offline/demo versus live startup, and the existing account/key commands.
- Reconciled first-party Claude Code (`claude`, then `/login`) and Grok
  (`grok login`) setup, default credential-file references, Console manual
  `sessionKey`-value-only entry and explicit organization/scope selection.
- Removed obsolete pending-CLI wording from README/security guidance. Existing
  encrypted-keyring versus explicit TUI session-only storage, refresh/stale/reset,
  purchased/promotional grant sums and blocked ordinary ChatGPT semantics remain
  unchanged. That documentation-only reconciliation added no verification result;
  final offline acceptance is recorded above, with detailed evidence in `PLAN.md`.

Entries below describe each chunk's delivered scope at that time; the current
application includes the C12 CLI/dashboard composition.

### Added — C12 production CLI and entry-point harness

- Wired `usage` and `python -m usage_tui` to live dashboard composition, with
  empty-account setup guidance, shared account/credential services and scheduler
  lifecycle. `--demo` and `--demo --scenario errors` select offline synthetic
  scenarios without constructing live dependencies.
- Interactive `accounts list/add/edit/remove` and `accounts key set/delete`, with
  explicit provider spellings, masked secret entry, TTY refusal, confirmation,
  external-reference/organization/scope selection and first-party reconnect
  guidance. API-key storage remains local-only, not subscription support.
- Exit codes 0 for success/normal quit, 2 for usage/config/secret-input errors,
  and 3 for credential/backend/provider-connection failures; per-account polling
  errors remain in the dashboard. Persistent CLI secrets require the supported
  encrypted keyring; session-only manual secrets are an explicit TUI choice.
- Production-entry POSIX PTY harness for healthy/errors demo rendering, help,
  read-only accounts, refresh, resize, quit/Ctrl-C and bounded terminal cleanup,
  with isolated HOME/XDG state. README/security/installation guidance and reusable
  repository Lessons document actual entry-point and secret-storage boundaries.
- C12 review, exercised gate/smoke and closure are recorded in `PLAN.md`; the
  final installed-entry-point offline acceptance is summarized above. Ordinary
  ChatGPT weekly retrieval remains contract-blocked; no live or real-keyring
  acceptance is implied by the CLI or demo.

### Added — C11 terminal dashboard and help

- Dependency-injected `UsageApp` with LIVE/DEMO distinction, Chinese metric labels,
  account filtering, scrollable required rows, keyboard help, and details for
  provenance, grants, shared pools, UTC timestamps and reconnect guidance.
- Numeric quota/remaining plus visually clamped bars, currency-bearing balances,
  explicit unknown/blocked/error states, separate success/attempt/retry times,
  stale/last-known flags and presentation-only countdowns. Reset expiry never
  fabricates a fresh allowance; Grok product shares remain shared-pool details.
- Embedded account manager with committed changes forwarded to source account
  updates and reconnect requests forwarded to refresh. Source stop precedes the
  optional live factory cleanup hook; Ctrl-C exits unconditionally from screens too,
  while printable `q` is a dashboard shortcut that does not preempt text entry.
- Python offline dashboard startup for healthy/errors scenarios without live
  stores, resolver or clients; demo accounts are read-only and synthetic ChatGPT
  samples are explicitly not ordinary-chat support.
- API/startup, lifecycle, security/freshness and repository-Lessons documentation.
  C12 subsequently supplies the usable CLI below these component boundaries.
  Exercised evidence remains separate in `PLAN.md`; documentation is not a
  live-metric or real-keyring acceptance claim.

### Fixed — C11 independent-review findings

- Keep printable `q` nonpriority so focused account-form inputs can accept it;
  retain unconditional priority Ctrl-C exit. The defect was identified by static
  review of Textual key dispatch, not an exercised account-entry reproduction.
- Fall back to UTC when local-time conversion of a bounded timestamp overflows,
  preserving saturated retry deadlines and scheduler embargoes. The supplied
  `TZ=Asia/Shanghai` reproduction raised `OverflowError` for UTC `datetime.max`.
- Earlier 779-test/24.82s and four real-PTY results are pre-review baselines only.
  Separate fix verification and clean independent rereviews are recorded in
  `PLAN.md`; the temporary C11 host is not production-entry CLI evidence.

### Added — C10 Textual account-management scope

- Reusable `AccountManagerScreen` and account service for terminal account
  add/list/edit, enable/disable, credential/reference replacement, explicit
  organization/scope selection, reconnect guidance, key deletion, and confirmed
  removal. Host callbacks connect committed changes to scheduler cancellation;
  this is not dashboard rendering or CLI launch integration.
- Masked, initially empty secret input with cancellation clearing and explicit
  replacement/deletion confirmation; encrypted Secret Service persistence and
  process-only session storage remain distinct choices without silent fallback.
  Console session entry has a high-sensitivity warning and explicit organization
  discovery/selection; external Claude/Grok files remain read-only references.
- Read-only injected-account mode for demo viewing without real storage/credential
  access. Optional ChatGPT bearer/API-key storage remains local management only;
  ordinary-chat weekly retrieval is still blocked on the upstream contract.
- Bounded account-screen/API, security, and repository-Lessons documentation.
  No dashboard/CLI, authenticated provider, real-keyring, or documentation-worker
  verification claim; exercised evidence belongs separately in `PLAN.md`.

### Fixed — C10 independent-review findings

- Preserve credentials referenced by config accepted before directory-sync failure;
  retain previous credentials too while crash durability is uncertain. Storage and
  account-flow errors carry the committed accounts, and the screen notifies the
  host while presenting the durability warning rather than claiming rollback.
- Invoke `console_discovery` as the documented async callable, including a bound
  `ConsoleProvider.discover_organizations` method, rather than as a provider object.
- Display an explicit high-sensitivity Console `sessionKey` warning before masked
  entry, accepting only its value, not a password, full Cookie header, or HAR file.
- Separate orchestrator fix verification and independent rereviews are recorded
  in `PLAN.md`; this entry does not claim a documentation-worker check or live
  acceptance.

### Added — C01 package/domain scope

- Python 3.11+ `src/` package metadata and runtime/development dependency declarations.
  C12 subsequently implements the declared `usage` entry point.
- Frozen domain types for providers, accounts, credential kinds/bindings, money, quotas,
  metrics, grants, provenance, diagnostics, snapshots, and transport-safe errors.
- Numeric and aware-timestamp validation, exact money arithmetic, stable metric IDs,
  and schema serialization helpers, with domain test source.
- Initial README, security-boundary documentation, and reusable research Lessons in
  root `AGENTS.md`, separating planned behavior from existing package/domain behavior.

### Corrected — C01 review follow-on

- Bound percentage strings to 4,096 characters, Decimal coefficients to 1,024 digits,
  and stored exponents to −1,000…+1,000 before exponent-driven exact arithmetic.
  Unsupported representations raise `DomainError` for direct and serialized quota
  inputs, preventing tiny scientific-notation payloads from requesting enormous
  decimal expansion. Supported values remain exact, including >100% overage and
  `max(0, 100 - used)` remaining; no rounding or 100% used cap is introduced.
- Correct planning/draft commit accounting and next-action tracking in `PLAN.md`.
  C01 exercised verification, independent rereview, review-fix commit, and closure
  are recorded there; this entry does not add new verification evidence.

### Added — C02 local storage library scope

- `AccountStore.load/save/mutate` with schema `1`, a 1 MiB config bound, private
  POSIX files, a stable advisory lock, and atomic same-directory replacement.
  Mutations reread under lock; failed callbacks/invalid existing config do not
  overwrite stored data. Unsafe ownership/modes, symlinks, and hardlinks are rejected.
- `CredentialStore.put/get/delete` with explicit instance-local session references
  and lazy persistent operations restricted to the exact supported Linux Secret
  Service backend. Unsupported or locked backends raise safe errors without an
  automatic plaintext/memory fallback. No real OS-keyring acceptance is claimed.
- Storage test source and fixed safe config/credential errors. C10 subsequently
  adds interactive account/key screens; C12 adds CLI integration.
- Bounded documentation of local persistence and session-only security boundaries;
  implementation evidence is separate from orchestrator verification in `PLAN.md`.

### Added — C03 transport and credential-resolution library scope

- Async fixed-origin, allowlisted-path GET transport with provider/kind binding
  checks before authentication or network I/O; exact Claude Bearer/beta, Console
  session-cookie, and Grok Bearer/token-auth headers. API keys and ChatGPT requests
  do not enable these reads; injected mock transports retain the same URL guards.
- Verified-TLS client configuration without redirects, proxy/netrc inheritance,
  or cross-request server-cookie persistence; 5-second connect timeout, 10-second
  overall deadline, 1 MiB streamed decoded-response bound, safe structured failures,
  and 429 Retry-After interpretation without shortening long server deadlines.
- Read-only Linux Claude Code/Grok credential references, explicit default-file
  resolution, descriptor-based regular-file/owner/exact-0600 checks, 1 MiB bound,
  expiry/scope validation, unambiguous Grok profile selection, manual-secret store
  lookup, and provider-bound immutable resolved credentials with opaque generations.
  No first-party file modification, refresh-token copying, or token refresh.
- Synthetic credential fixtures and transport/resolver/security test source;
  documentation of exact private origin/auth boundaries and reusable security
  Lessons. No checks or authenticated requests were run by the documentation worker.

### Added — C04 Claude subscription provider library scope

- `ClaudeProvider(transport)` with async `fetch(account, credential, now)`, explicit
  credential requirement, and all three required metric rows on every result.
  A fetch reads the private OAuth usage endpoint once through guarded Transport;
  it does not log in, refresh credentials, retry, poll, or integrate a CLI/TUI.
- Independent five-hour/weekly parsing, exact used/remaining percentages, per-window
  unknown states, partial snapshots that preserve valid sibling windows, and
  schema-error snapshots when no usable percentage exists. Invalid reset data does
  not erase valid quota data. Aware strings and adapter-local positive Unix
  seconds/milliseconds reset normalization are supported.
- Scoped Fable selection independent of `is_active`, ordered legacy aliases, and
  rejection of conflicting valid scoped duplicates. No Opus/Sonnet substitution,
  inferred eligibility, fixed half-week quota, extra-usage balance conflation, or
  additive Fable allowance.
- Documentation of the library contract and private-API/unknown-window boundaries.
  No authenticated response, live acceptance, or documentation-worker check is
  claimed; verification remains separately recorded in `PLAN.md`.
- C04 review finding: equal-percent scoped Fable duplicates with a malformed reset
  initially returned Fable UNKNOWN with quota None in the orchestrator reproduction.
  The required behavior retains quota, leaves reset unknown, and flags partial;
  malformed reset metadata alone must not be treated as a quota conflict. The bounded
  review fix was separately verified and C04 closed as recorded in `PLAN.md`; this
  entry does not claim any new checks.

### Added — C05 Console balance and organization-discovery library scope

- `ConsoleProvider(transport)` with async `fetch(account, credential, now)`, explicit
  Console-session requirement, and purchased, promotional, and authoritative total
  metric rows on every result. One selected-org credits read per eligible fetch;
  no automatic discovery, organization switching, login, refresh, polling, or retry.
- Separate async `discover_organizations(credential)` returns immutable
  `OrganizationChoice(id, label)` candidates with exact `api` capability and safe
  validated IDs; malformed candidates/duplicate IDs fail safely. Discovery never
  persists or automatically chooses an organization, including a singleton.
- Independent exact category sums across all grants not known expired, retained
  zero/negative amounts, explicit empty-array zero versus missing/null unknown,
  per-grant metadata/expiry, and unknown-expiry uncertainty. Invalid grant numeric
  fields do not erase independent category/authoritative-total evidence. The top-level
  total is never reconstructed from categories; disagreement remains visible.
- Private/version-sensitive Console compatibility and high-sensitivity session
  documentation, explicit organization-selection boundary, and distinction between
  grant expiry and subscription reset. No API-key/spend-report balance fallback.
- Bounded README/security/Lessons updates. No documentation-worker checks, real
  credentials, live requests, CLI integration, or authenticated acceptance claimed;
  exercised verification remains the orchestrator's separate `PLAN.md` record.

### Added — C06 Grok billing provider library scope

- `GrokProvider(transport)` with async `fetch(account, credential, now)`, explicit
  credential requirement, and shared-pool, Build, and Chat rows on every result.
  One direct private-proxy billing GET per eligible fetch through fixed-origin
  Transport; no Grok/ACP subprocess, login, token refresh, polling, or retry.
- Reported aggregate consumption with positively established unified-pool semantics
  kept separate from unproven pool relationships. Product shares require a complete
  valid unique-product array and same-payload aggregate reconciliation within one
  percentage point; unknown products are retained with sanitized IDs. Invalid
  breakdowns preserve independent aggregate evidence. Explicit product zero is
  zero; missing products are unknown, never an inferred zero or independent quota.
- Server weekly/monthly period interpretation, aware reset parsing, reversed-bound
  rejection, and absent-only end fallback. Invalid reset leaves valid usage intact;
  Build/Chat remaining/reset refer only to a positively established shared pool.
  No on-demand spend, prepaid wallet, estimated cap, or coupon lookup substitution.
- Bounded README/security/Lessons updates for the exact private proxy origin and
  credential binding, external login references, and read-only first-party files.
  No documentation-worker checks, CLI/TUI integration, live requests, or authenticated
  acceptance claimed; exercised evidence belongs separately in `PLAN.md`.

### C06 review correction — numeric wire precision; verification pending

- Independent review reproduced an out-of-tolerance raw JSON numeric share
  (`43.500000000000000000000000000001` against aggregate `42.5`, with Chat `0`)
  incorrectly accepted as READY after HTTP decoding rounded it to binary float.
- Require HTTP JSON numeric tokens to decode directly as `Decimal` before exact
  same-payload reconciliation, not `Decimal` conversion after a float roundtrip.
  Regression coverage must exercise raw JSON numbers at the tolerance boundary,
  not only string-valued percentages. Fix verification and independent rereview
  remain pending; no new gates, smoke, live acceptance, or closure are claimed.


### Added — C07 explicit registry and unresolved ChatGPT capability

- Explicit `build_providers(transport, resolver)` registry for the implemented
  Claude subscription, Console, and Grok adapters plus the unresolved ChatGPT
  capability; required metric enumeration and credential-requirement metadata.
  Imports/construction perform no credential reads, environment probing, or I/O.
- Retain the ordinary `chatgpt.subscription.weekly` row with structured
  `upstream_contract_missing`, unresolved provenance, and safe Chinese/English
  explanation. The capability requires no credential and does not resolve saved
  secrets, access transport, or fall back to WHAM/Codex or API consumption.
- Bounded README/security/Lessons documentation distinguishes a blocked capability
  from a working ordinary-chat adapter. Optional bearer/API-key storage does not
  enable retrieval, and no cookie/password solicitation is an appropriate remedy.
  Static research and the missing upstream prerequisite remain tracked in PLAN.md;
  ordinary ChatGPT weekly quota is not complete. No CLI, worker-executed checks,
  smoke, live requests, or authenticated acceptance are claimed by this task.

### Added — C08 polling and freshness library

- Async scheduler lifecycle with injectable UTC/monotonic clock, sleep, RNG, and
  loop-local snapshot publication. Initial polls, jittered per-account intervals,
  one in-flight fetch per account, global two-account concurrency, and five-second
  same-origin fetch-start spacing; no per-metric request duplication or polling-time
  Console discovery.
- Coalesced explicit refresh/reconnect, auth/permission/unconfigured suspension,
  bounded exponential backoff, and preservation of longer server retry deadlines.
  Account generations cancel obsolete work and reject late results; replacing an
  account does not erase its same-provider retry embargo. Unresolved ChatGPT
  publishes once per generation without credential resolution or periodic/manual
  polling.
- Last-good metrics/grants survive fetch failures with their original success time
  and new attempt/error metadata. Compatible new observations, including partial
  ones, replace fields rather than silently retaining disappeared metrics.
  Freshness exposes stale age, passed-reset, and last-known status without changing
  raw metric states or resetting quota on a timer.
- Bounded README/security/Lessons documentation. No documentation-worker checks,
  smoke, CLI/TUI integration, live requests, or authenticated acceptance are claimed;
  exercised verification remains separate in PLAN.md.

### C08 review corrections — verification recorded separately

- Independent reviews found three scheduler defects: insertion-order starvation
  of overdue accounts, same-origin spacing measured before slow credential
  resolution rather than at actual provider request start, and overflow while
  reconstructing a retry timestamp near UTC `datetime.max`.
- The orchestrator's actual seven-account, same-origin, 30-second-interval
  reproduction observed only six initial account results over more than 100
  seconds. Resolver spacing and retry saturation are static review findings;
  no exercised reproduction is claimed for those two findings here.
- Required corrections select oldest eligible deadlines fairly, gate same-origin
  provider request starts after credential resolution, and saturate retry display
  timestamps without shortening monotonic server embargoes. Regression coverage
  and implementation are not evidence of passing verification. Separately exercised
  fix gates/smoke, independent rereview, and closure are recorded in `PLAN.md`.


### Added — C09 deterministic offline-source library

- Packaged synthetic `healthy` and `errors` scenarios with fixed demo time,
  fictional accounts, normalized snapshots, every requested metric, and explicit
  `offline_demo` provenance. Ready GPT sample data is fictional demonstration,
  not a working ordinary ChatGPT adapter or authenticated quota evidence.
- Error scenarios cover authentication, permission, rate limit/retry, network,
  malformed/partial data, unknown Fable, missing product breakdown, and stale
  last-known values without inventing current quota or provider observations.
- Offline source isolation excludes account configuration, credential files,
  keyring, resolver, live provider construction, transport, and network access;
  only the packaged fixture is read. Fixtures are not a live-error fallback.
- Bounded README/security/Lessons documentation and source tests. No worker checks,
  smoke, CLI/TUI integration, live request, or authenticated acceptance is claimed;
  exercised verification remains separately recorded in `PLAN.md`.

### Current unverified boundary

- Codex cutover integrated checks, actual installed-entry terminal proof and
  implementation reviews remain pending in PLAN.md §11. Static source research
  makes the code task actionable; it is not authenticated acceptance.
- No live metric, authenticated provider response or real OS-keyring acceptance is
  established. Other providers' live prerequisites remain unchanged. Historical
  ordinary-ChatGPT blocker entries above are superseded, not erased or completed.
- Writing tests and documenting setup does not establish successful verification.
  Exact exercised checks, smoke evidence, lock resolution, review, and chunk closure
  are recorded by the orchestrator in `PLAN.md`, not inferred from this entry.
