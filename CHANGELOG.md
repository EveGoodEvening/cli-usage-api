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
  review fix is pending reverify; initial green checks do not establish fix verification
  or C04 closure.

### Not yet implemented / not verified

- No CLI, terminal dashboard, interactive account/key management, other provider
  adapters, polling, or offline demo is delivered by the current libraries.
- No live metric, authenticated provider response, or secure OS-keyring acceptance is
  established. Ordinary ChatGPT weekly usage has an unresolved upstream contract;
  WHAM/Codex or API consumption is not a substitute.
- Writing tests and documenting setup does not establish successful verification.
  Exact exercised checks, smoke evidence, lock resolution, review, and chunk closure
  are recorded by the orchestrator in `PLAN.md`, not inferred from this entry.
