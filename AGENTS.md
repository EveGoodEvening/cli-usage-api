# Repository guidance

[PLAN.md](PLAN.md) is the authoritative scope, frozen-contract, sequencing, and
acceptance record. Keep implementation and authenticated/live acceptance separate.

## Lessons

- A private contract is usable research evidence without being a supported public API.
  Record exact request origin/path/authentication, schema, semantic meaning, and source
  revision together. A community parser or official CLI source does not establish that
  a live account request succeeds. PLAN.md §7 records the inspected sources and revisions.
- Subscription allowance, API consumption, and credit balance are different quantities.
  Anthropic Admin cost/usage reports do not establish purchased/promotional balance;
  Console credit grants supply distinct balance evidence. OpenAI/xAI API consumption
  does not establish consumer subscription quota. Keep these source meanings intact.
- WHAM/Codex allowance evidence does not prove ordinary ChatGPT chat-model weekly
  usage. A local message counter or custom cap is not a remote quota contract. Leave
  the ordinary ChatGPT metric unresolved until request/auth/model/window evidence exists.
- Model an unresolved metric as a visible capability result, not a fabricated
  network adapter: retain required rows and unresolved provenance, use a fixed
  upstream-contract diagnostic, and explicitly declare no credential requirement.
  Registry membership is not live support. Orchestration must skip secret resolution
  for that capability even when an account holds an optional credential reference.
  Credential storage cannot repair absent read/auth/model/window/reset semantics;
  never solicit cookies/passwords or substitute Codex to make the row appear ready.
- Fable is a model-scoped weekly subset, not an additional weekly allowance. GrokBuild
  and GrokChat product shares are not independent quotas: shared remaining/reset needs
  positive same-payload shared-pool evidence. Missing data is unknown, not zero.
- Bound numeric representation complexity before exact arithmetic or fixed-point
  formatting. A tiny scientific-notation Decimal can encode an enormous expansion,
  so a JSON byte-size limit does not bound computation or memory. Check coefficient
  digits and stored exponent (and string length before parsing), reject unsupported
  representations through direct and deserialization paths, and retain exact normal
  percent/overage semantics rather than hiding the risk with rounding or clamping.
- Progress tracking must distinguish verified draft baselines from later review
  fixes. Record existing exact commit hashes and replace completed next assignments;
  keep fix verification, independent rereview, and closure explicitly pending until
  the orchestrator records their own evidence.
- Keep an advisory config lock on a stable sibling file, not the config inode that
  atomic replacement discards. Read-modify-write callbacks must reread while holding
  that lock; individually locked load/save calls still permit stale lost updates.
- A keyring backend's name or positive priority does not establish encrypted
  persistence. Use the supported exact backend type policy; reject chained,
  alternative/plaintext, unknown, and subclassed backends rather than silently
  accepting a weaker backend or falling back. Session-only storage is an explicit
  separate choice and must not probe the OS keyring.
- Bind credentials to an explicit provider and source kind in both resolver and
  transport. Reject mismatches before auth-header construction or network I/O;
  a shared brand or plausible token string is not authorization to reuse a secret.
  Exact origin/path allowlists must still apply when a mock HTTP transport is injected.
- Read external login references at resolution time through a validated descriptor,
  not a prior pathname stat followed by an unchecked open. Reject unsafe files
  rather than changing first-party permissions. Profile ambiguity requires explicit
  selection; absent expiry is unknown, not fresh. Never refresh or copy refresh tokens.
- A shared HTTP cookie jar can forward upstream cookies on later requests even when
  application auth headers are curated. Keep server cookies from persisting across
  reads, disable redirects and environment proxy/netrc inheritance, bound streamed
  decoded bytes and the overall deadline, and expose only curated structured errors.
- A synthetic fixture, mock request, or working transport library does not establish
  a provider adapter, authenticated compatibility, or live metric acceptance. Keep
  library/API documentation separate from future CLI/TUI instructions and live claims.
- Preserve response independence at the metric boundary: a valid Claude percentage
  survives an invalid reset, and valid windows survive missing/invalid siblings.
  Return every required row as known or unknown; a response with no usable window
  is a schema error, not successful empty bars. Parsing must not infer eligibility
  from absence or turn missing usage into zero.
- Scoped Fable selection needs semantic identity and ambiguity handling, not an
  activity-flag shortcut: match the weekly scope and normalized model display name,
  retain inactive-but-valid meters, and reject conflicting valid duplicates before
  considering any arbitrary choice. Keep legacy fallback ordering explicit.
- Compare duplicate quota evidence independently from reset validity. Equal-percent
  scoped Fable duplicates with an invalid reset must preserve quota, leave reset
  unknown, and flag partial, not become an unknown quota through tuple inequality.
  C04 review's orchestrator reproduction initially lost quota (Fable UNKNOWN,
  quota None); separately verified fix/closure evidence is recorded in PLAN.md.
- Keep numeric timestamp heuristics provider-local. Claude's positive seconds and
  `>= 10^11` millisecond normalization does not justify weakening the domain's
  timezone-aware timestamp contract or applying the heuristic to other providers.
- Console organization discovery is an explicit connection operation, not a balance
  polling side effect. Validate exact API capability and safe IDs; return choices
  without silently selecting even a singleton. Fetch only the saved organization;
  stale/inaccessible selection requires guidance, never another readable account.
- A Console cookie is a high-sensitivity session, not a limited API key. Preserve
  the secure-store/session-only distinction and exact origin binding; a library
  adapter does not implement the future UI's warning or selection confirmation.
- Keep authoritative credit totals independent from category sums. Sum every grant
  not known expired in each complete validated category; an empty array proves zero,
  absence does not. Preserve zeros/negative money and independent valid evidence
  when one category is invalid. Never infer a missing category by subtraction.
- Grant expiry is not subscription reset. Retain per-grant amounts/program/expiry,
  exclude known-expired grants from active sums, and include unknown expiry only
  with explicit uncertainty. A nearest expiry is not the whole category balance
  and cannot establish renewal or turn promotional API credits into quota windows.
- Grok unified-pool semantics require positive `isUnifiedBillingUser == true`
  evidence, not a marketing tier or aggregate percentage alone. Keep reported
  consumption distinct from proven remaining allowance; product shares never mean
  `100 - share` remaining. Attach product remaining/reset only to the proven pool.
  A consumed share belongs in product detail with `quota=None` when the generic
  quota value would auto-derive an independent remaining percentage; use the
  shared-pool reference rather than weakening that domain invariant.
- Validate the entire same-payload Grok product array before exposing a breakdown:
  reject duplicate/malformed shares, reconcile all products to the wire aggregate
  within one percentage point, and preserve sanitized unknown-product IDs. Missing
  Build/Chat is unknown even when other shares reconcile; only an explicit entry
  proves zero. An invalid breakdown must not erase independent aggregate evidence.
- Exact arithmetic starts at the HTTP JSON boundary. Decode decimal numeric tokens
  directly as `Decimal`; stringifying a binary float cannot recover lost wire
  precision. C06 review reproduced raw numeric `43.500000000000000000000000000001`
  against aggregate `42.5` with Chat `0` incorrectly passing the one-point tolerance
  after float rounding. Boundary regressions must send actual raw JSON numbers
  through Transport and the provider, not only decimal strings or decoded objects.
  Record reproduction separately from pending fix verification and rereview.
- Period fallback is an absence rule, not an error-recovery shortcut. A malformed
  `currentPeriod.end` must not be replaced by `billingPeriodEnd`; reversed bounds
  cannot establish reset. Preserve valid usage independently and derive period
  labels from server type, not subscription marketing.
- Direct Grok proxy JSON preserves private product evidence that typed ACP may
  discard. Do not silently substitute a subprocess, infer included quota from
  on-demand spend, or guess client-version/auth headers to hide incompatibility.
- Keep scheduling deadlines monotonic and observation timestamps UTC. Convert an
  upstream wall-clock retry deadline into a monotonic embargo when received;
  periodic scheduling must not drift with wall-clock adjustments. A local backoff
  cap cannot shorten a server embargo, and account replacement must preserve it
  for the same provider rather than becoming an accidental rate-limit bypass.
- Cancellation and generation identity are separate controls: an adapter can
  finish after cancellation. C08 checks the active account-state identity before
  publishing. Capture the resolved credential once per attempt; explicit account
  updates must invalidate even unchanged references when their secret was replaced.
  Do not claim background first-party-file monitoring or remote revocation.
- Treat partial compatible responses as new observations, not fetch failures.
  C08 replaces their current fields and fills missing required rows as unknown;
  only failed fetches retain prior metrics/grants with the old successful timestamp.
  Freshness and passed-reset status stay separate from raw metric state, so a local
  timer cannot manufacture a new allowance or make failed polling look fresh.
- Choose eligible scheduler work by oldest due deadline, not account insertion
  order. Seven same-origin accounts at a supported 30-second interval can starve
  the seventh indefinitely when the first six reclaim five-second origin slots.
  Cover initial-service fairness over repeated poll cycles, not just concurrency.
- Apply origin spacing after credential resolution, immediately before entering
  the provider request. A queue-time reservation can expire during a synchronous
  keyring/file lookup and allow back-to-back actual request starts.
- Keep extreme retry presentation representable: floating-point conversion of
  UTC `datetime.max` can round into year 10000. Saturate the displayed timestamp
  without shortening the monotonic embargo or losing publication of the failure.
  Distinguish static review findings from actual reproductions and preserve
  pending fix-verification/rereview status despite earlier green gates.
- Keep offline composition independent of live dependencies: a demo source reads
  only its packaged synthetic resource, never account config, credential files,
  keyring, resolver, provider registry, or live transport. Forbid those construction
  paths in tests; do not use demo fixtures as live-fetch fallback. Fixed/injected
  demo time and `offline_demo` provenance must accompany fictional labels and all
  samples, especially ready ChatGPT data, so a useful display scenario cannot be
  mistaken for a working upstream contract or authenticated metric acceptance.
- Treat account editing as staged user intent, not immediate credential mutation.
  Keep saved secrets out of prefilled inputs and display text; use masked keyboard
  input, explicit replacement/removal confirmation, and clear pending secrets on
  cancellation. External first-party references are never owned login files to delete.
- Account metadata and OS-keyring operations are separate stores, not one atomic
  transaction. Preserve actionable failure reporting and the distinction between
  durable references and explicit process-only secrets. Notify the scheduler after
  committed account changes so obsolete generations cannot publish; do not equate
  local removal with remote revocation or treat credential storage as live support.
