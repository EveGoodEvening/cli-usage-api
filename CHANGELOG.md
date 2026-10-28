# Changelog

## Unreleased

### Added — C01 package/domain scope

- Python 3.11+ `src/` package metadata and runtime/development dependency declarations.
  The declared future `usage` entry point is not a runnable CLI at this stage.
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
- Storage test source and fixed safe config/credential errors. Interactive
  account/key management remains unimplemented; C03 adds read-only import below.
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

### Not yet implemented / not verified

- No CLI, terminal dashboard, interactive account/key management, ordinary ChatGPT
  quota adapter, polling, or offline demo is delivered by the current libraries.
- No live metric, authenticated provider response, or secure OS-keyring acceptance is
  established. Ordinary ChatGPT weekly usage has an unresolved upstream contract;
  WHAM/Codex or API consumption is not a substitute.
- Writing tests and documenting setup does not establish successful verification.
  Exact exercised checks, smoke evidence, lock resolution, review, and chunk closure
  are recorded by the orchestrator in `PLAN.md`, not inferred from this entry.
