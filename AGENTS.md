# Repository guidance

[PLAN.md](PLAN.md) is the authoritative scope, frozen-contract, sequencing, and
acceptance record. Keep implementation and authenticated/live acceptance separate.

## Lessons

- Compose the production entry point from the existing account services, provider
  registry and scheduler; do not duplicate account mutation or transport policy in
  CLI branches. Share the credential store with the resolver so explicit TUI
  session-only credentials work for the lifetime of that app.
- Branch demo before constructing live stores, resolvers, providers or clients.
  Installed-entry PTY evidence and Python component-host evidence are different;
  a runnable CLI, harness source or synthetic Codex sample proves no live quota
  compatibility. Keep exercised acceptance in PLAN.md.
- Secrets belong in masked interactive prompts, never command arguments or
  environment-variable examples. Refuse non-TTY secret operations; persistent CLI
  key storage must fail honestly when the secure backend is unavailable, rather
  than create session memory that disappears when the CLI process exits. Direct
  users to the explicit TUI session-only choice instead.
- A real-entry PTY harness must launch the installed console executable in the same
  environment, isolate HOME/XDG, wait for meaningful rendered tokens, and bound
  every wait. Always kill/reap owned children and restore terminal state; a
  traceback-free startup alone does not cover modal return, resize or shutdown.
- Permanent harness tests should assert observable behavior, not mock choreography.
  Keep coverage for rendered surfaces, bounded waits, isolation, normal/Ctrl-C
  shutdown and terminal restoration; do not freeze internal helper call sequences
  with wiring-only mocks. Actual installed-entry PTY evidence remains distinct
  from unit tests and belongs in PLAN.md.
- UI countdown ticks are presentation only. Use the source's clock for demo time,
  show last-success and last-attempt separately, and retain numeric overage, unknown
  fields and last-known errors without resetting quota when a deadline passes.
  Account replacement/removal must reach scheduler generation cancellation before
  stale callbacks can be presented as the new connection's observations.
- A demo account manager must be an injected read-only view, not an excuse to
  construct real stores or a resolver. Synthetic ready quota rows need explicit
  demo provenance; they cannot establish authenticated provider compatibility.
- Printable dashboard shortcuts must not preempt focused text entry: keep `q`
  nonpriority so account labels, paths, selectors and masked credentials can contain
  it; reserve priority quit dispatch for unconditional Ctrl-C.
- A valid UTC deadline can overflow during local-time conversion near datetime
  bounds. Fall back to its UTC representation without changing the deadline or
  shortening the scheduler embargo. Distinguish static key-dispatch findings from
  exercised timezone reproductions, and keep review-fix verification pending until
  the orchestrator supplies new evidence.
- A private contract is usable research evidence without being a supported public API.
  Record exact request origin/path/authentication, schema, semantic meaning, and source
  revision together. A community parser or official CLI source does not establish that
  a live account request succeeds. PLAN.md §7 records the inspected sources and revisions.
- Subscription allowance, API consumption, and credit balance are different quantities.
  Anthropic Admin cost/usage reports do not establish purchased/promotional balance;
  Console credit grants supply distinct balance evidence. OpenAI/xAI API consumption
  does not establish consumer subscription quota. Keep these source meanings intact.
- The user-corrected target is Codex quota, not ordinary ChatGPT chat-model usage.
  Match weekly by the main window's 604800-second duration, never slot position,
  plan name or feature pool. Optional 5h/other windows remain reported extras;
  absolute reset seconds and relative duration are not interchangeable.
- Keep file-backed login selection and bearer together in one stable secure read.
  Codex's selected account header is distinct from Grok user ID and Console
  organization. Unverified JWT decoding supplies local expiry/provenance hints,
  not signature verification or an authentication trust boundary. No refresh-token
  auth, Codex-keyring probing, auto-without-file fallback or manual/API-key bypass.
- Semantic migration requires explicit whole-set consent and lock/reread validation,
  not a runtime provider alias or ordinary account edit. Disable and detach legacy
  replacements; retain old keyring secrets untouched and document that they are
  detached/unmanaged. Migration must never resolve, transmit or clean them up.
- S1's Codex selected-account contract is a redacted, Codex-only credential field,
  not a label, organization or reusable cross-provider selector. Preserve its
  same-stable-read binding to the access bearer through resolver, provider and
  transport; never reconstruct the selected account from local profile identity.
  The current integrated gate and synthetic resolver → provider → transport proof
  passed; this does not establish JWT signature verification or live compatibility.
- Record migration proof at the actual storage/installed-CLI boundary, not just
  prompt construction: the current real-PTY proof exercised unchanged decline,
  cancel and non-TTY paths, affirmative mixed-config migration, then file-backed
  edit/reconnect and enable/disable. Disabled/detached replacements must never
  resolve or transmit retained legacy secrets. Synthetic backend evidence is not
  real OS-keyring acceptance.
- The atomic Codex cutover's final gate is 1,098 tests in 30.20 seconds after
  locked dev sync, with Ruff lint and 44-file formatting passed. Earlier clean
  diagnostics for all 17 source files apply to unchanged source. Four independent
  implementation reviews and two final split reviews were clean, with no fixes
  required. Keep this completed offline baseline separate from historical 851-test
  evidence and unexercised authorized live/keyring acceptance; ordinary-chat
  blockers do not apply to the current Codex contract.
- A local message counter/custom cap or credential storage cannot repair absent
  quota semantics. Model a genuinely unresolved capability honestly; that historical
  C07 lesson does not make current Codex credential-free or upstream-blocked.
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
- Validate the entire same-payload Grok product array: reject duplicate/malformed
  shares and preserve sanitized unknown-product IDs. BYOS's billing contract does
  not require product shares to sum to the aggregate; the older one-point gate was
  an unsupported assumption, superseded in PLAN.md §12. Omitted scalar percentages
  are zero only with explicit weekly type and valid reset; null/malformed values
  and absent Build/Chat entries remain unknown. Invalid breakdowns must not erase
  independent aggregate evidence.
- Provider-emitted extra metrics must remain visible through the consumer, not
  merely survive parsing and scheduling. Final split review found additional Grok
  products hidden by required-ID-only dashboard enumeration; supplied actual
  UsageApp/Pilot evidence emitted four Grok metrics while visible rows stayed
  10 → 10. Preserve all required rows, append deduplicated snapshot extras, and
  retain selection identity, filtering and existing details/shared-pool semantics
  across refreshes. Producer-only coverage does not establish end-to-end UI
  visibility; keep post-fix verification and independent rereview separate from
  the prior green gate.
- Exact arithmetic starts at the HTTP JSON boundary. Decode decimal numeric tokens
  directly as `Decimal`; stringifying a binary float cannot recover lost wire
  precision. C06's historical one-point reconciliation reproduction exposed that
  loss; §12 removes the unsupported sum invariant, not exact decoding. Boundary
  regressions must send raw JSON numbers through Transport and the provider and
  verify retained precision, not only decimal strings or decoded objects.
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
  samples, including ready Codex data, so a useful display scenario cannot be
  mistaken for authenticated metric acceptance.
- Treat account editing as staged user intent, not immediate credential mutation.
  Keep saved secrets out of prefilled inputs and display text; use masked keyboard
  input, explicit replacement/removal confirmation, and clear pending secrets on
  cancellation. External first-party references are never owned login files to delete.
- Account metadata and OS-keyring operations are separate stores, not one atomic
  transaction. Preserve actionable failure reporting and the distinction between
  durable references and explicit process-only secrets. Notify the scheduler after
  committed account changes so obsolete generations cannot publish; do not equate
  local removal with remote revocation or treat credential storage as live support.
- Distinguish rejected writes from replacement already accepted with failed directory
  fsync. Carry the committed account tuple through storage/service errors and notify
  the host once; never delete a credential referenced by the accepted config. On
  uncertain crash durability, retain the previous credential too, since recovery may
  restore old metadata. Only rejected writes may roll back the newly created secret.
- Exercise documented injected APIs in their actual shape: an async callable such as
  a bound discovery method is not a provider object. Keep the canonical callable
  contract and invocation aligned with embedding examples.
- Generic masked-entry or session-memory guidance is not a sensitivity warning.
  Display the Console `sessionKey` high-sensitivity account-session warning before
  its secret input, including value-only guidance excluding passwords, full Cookie
  headers, and HAR files; cover visibility for the specific provider/kind.
- Dashboard option lists mix disabled account headers with metric rows: map rows by
  option id (`option_index`/`highlighted_row`), never by option index, and never
  assign a header index to `highlighted` (Textual accepts it). App `on_resize` runs
  before the list's own layout, so width tiers re-flow on the list's Resize. Numbers,
  money and Grok product shares are never ellipsized; only labels/reset text adapt.
- Disabled header options also break Textual page movement: PageUp can land on a
  first-row header and clear `highlighted`; fall back to the nearest metric. Pack
  header segments by their widest clock-driven form (age, retry countdown) so 1 s
  ticks never change row heights, and keep a visible selection visible when a
  semantic change (reset passed) grows a row. Explanatory notes, diagnostics and
  grant-count uncertainty wrap whole in every tier; an incomplete Console fetch
  shows `—`/`≥N` grants, never 0. A READY quota without reset reads `重置 — 未知`.
  Narrow rows place the bare balance amount, not its wide padded cell. Test the
  displayed OptionList prompts, not only `_row_text` (now details-only).
- `.venv/bin/pytest` can carry a stale shebang from a renamed checkout; reinstall
  the package (`uv sync --locked --reinstall-package pytest`) rather than
  rewriting gate commands.
- Provider-specific polling floors must affect existing saved accounts and UI
  freshness, not merely new-account defaults. Clamp negative jitter at the actual
  floor and apply conservative no-header 429 cooldowns; longer configured/server
  delays win. Explicit manual refresh remains separate from automatic cadence and
  cannot bypass embargoes. A green synthetic scheduler run does not prove an
  upstream account's rate threshold.
- Source a Grok compatibility-version pin from the official stable feed and retain
  the app's identifying User-Agent. A reference project's version-gate report or
  schema fixture establishes a compatibility lead, not the user's exact live
  failure. Preserve the distinction between sourced repair and authenticated proof.
- When changing an exponential retry base, adjust its bounded exponent so the
  sequence can still reach the intended cap. Cover both first-retry timing and
  repeated capped failures; lowering the base alone can accidentally plateau
  below the documented maximum.
- Keep nonsecret UI preferences separate from account/credential configuration,
  while sharing the existing private, locked, atomic file primitives. Restore a
  Textual theme before mount and register its persistence watcher with `init=False`
  afterward: startup defaults must not overwrite a saved choice. Demo may read
  these UI preferences without constructing live dependencies. Verify selection
  through the actual command palette and a fresh process; an in-memory theme value
  alone does not establish restart persistence.
- A Grok product's consumption is a structured `Metric.share_percent` (bounded via
  `percent()`, exclusive with quota/balance), rendered as bar + `已用` only: never a
  derived remaining or reset. Numeric Grok dashboard rows carry no per-row
  explanation; the user knows it is a shared pool. Keep details in Enter details
  and on unknown rows. Nest products under a pool named by metric id or pool id.
  Without `isUnifiedBillingUser == true` the aggregate is a share labelled
  `Grok 汇总`, not `共享池`: no remaining/reset, no nesting; label + absent remaining
  carry the caveat, so no per-row explanation there either.
  Demo Grok rows use the uniform synthetic detail so it hoists like other cards.
  Grok unknown rows also drop the generic "missing does not mean zero" sentence:
  the `未知 / no data` placeholder says it; Enter details keeps it.
- The dashboard can focus its metric list for keyboard navigation without selecting
  a row. Preserve `highlighted=None` through startup snapshots and filter rebuilds;
  treat `全部账号` as the filter value, not a metric selection. Recover the nearest
  metric only when a previously selected row disappears.
- The `--debug-log` file is the only debug output: keep `cli_usage_api.debug`
  non-propagating with a NullHandler, guard work with `debuglog.enabled(provider)`,
  and never let a debug-only non-2xx body read change the curated TransportError.
  Redact by key, JWT shape and the request's own bound credential values; log only
  exception type names. pytest's caplog attaches to non-propagating loggers too, so
  "Captured log" output in tests does not mean records reach the terminal.
- Debug diagnostics must not change fetch outcomes: classify non-2xx status from
  headers before any diagnostic body read, give that read its own deadline ending
  before the request's (an outer `asyncio.timeout` cancellation is not an
  `Exception`), and guard serialization, since `json.loads` accepts nesting deeper
  than recursive redaction can walk. Redact undecodable text by key too, scrub
  before truncating, and anchor/bound regexes so 1 MB bodies cannot scan quadratically.
- Complete Console balances can disagree with their authoritative total even when
  every metric is ready. Treat that as an `ok` read with a separate `balance_mismatch`
  advisory, not missing data. Preserve amounts and show the exact signed difference
  using the currency/exponent; do not invent a tolerance or fill missing categories.
  Genuine missing/invalid data and unknown expiry retain partial/schema diagnostics,
  with any simultaneous difference still visible in total-balance details.
- Inline `python -c` subclasses lack a source file for Textual's relative stylesheet
  resolution. A throwaway PTY host should instantiate the production `UsageApp`
  directly with an injected clock, or define its subclass in a real temporary file;
  a host startup failure does not establish an application regression.
- Railway volumes mount only at container start and hide anything the image wrote
  to that path, so install CLIs outside the volume-backed `HOME` (npm global,
  `/opt`), not with HOME-based installers. Grok's installer targets `$HOME/.grok`;
  fetch its versioned artifact instead (xAI publishes no checksums). Railway Config
  as Code (`railway.json`) is deprecated and new services cannot opt in; a root
  `Dockerfile` is auto-detected. The container has no OS keyring: only file-backed
  first-party logins work there, never Console sessions or persistent manual secrets.
- First-party CLIs refresh only inside a ~5-minute pre-expiry window (Codex, Claude
  Code, Grok at inspected revisions), so a keepalive must schedule from stored expiry,
  not a fixed cron, and judge success by re-reading expiry rather than exit codes.
  `codex login status` does not refresh; `codex doctor` and `grok sessions list` do.
  Claude Code can exit before persisting a refresh (#105645): back up, restore only a
  still-blank file, and alert instead of looping. Keepalive is a separate opt-in
  process; the reader itself still never refreshes or reads refresh tokens.
- An HTTP failed-auth limiter must verify a presented bearer first: a global failure
  cap consulted before verification lets any client lock out valid token holders.
  Cross-origin clients cannot read `Retry-After` unless it is listed in
  `Access-Control-Expose-Headers`. uvicorn exits via `SystemExit` on lifespan
  startup failure, so map it to the curated error inside `serve()`; and `localhost`
  may resolve to an IPv6-only bind, so pin it to `127.0.0.1`.
- A browser fetch timeout must cover the body read, not just headers; a stalled
  body otherwise freezes polling. Grok product share rows show no reset in the web
  UI either, matching the TUI.
- A TUI session-only credential exists only in that process, so serve it by embedding
  the API in the TUI's event loop (observer mirror of the TUI's snapshots/accounts),
  never a second process. Embedded uvicorn: lifespan off, no signal handlers, silenced
  loggers (root last-resort output corrupts the screen); bind and run every refusal
  before `App.run`. Headless Textual `run_test` hides toasts unless
  `notifications=True`.
- Cancelling an `asyncio.to_thread` await does not stop its thread: a subprocess-running
  worker needs a cooperative stop checked before each unit of work plus killing the
  tracked child's process group, and locks it guards are released only after it exits.
- A runtime lock does not lock an isolated Python build backend. With uv 0.13.5,
  pin every build requirement (including Hatchling's `editables` hook dependency),
  record approved wheel hashes and require build hashes. Prove fresh editable and
  wheel installs plus wrong/missing-hash rejection; cached wheels and disabled
  build isolation do not establish enforcement. A hashless object constraint is
  invalid uv schema: use its string form when testing missing-hash rejection.
- Disable npm dependency hooks only after checking native-package entrypoints.
  Claude Code 2.1.308's wrapper bin is a stub until postinstall places the native
  binary; a script-disabled container install must link the locked Linux binary
  directly and reject missing platform packages. esbuild/workerd can resolve their
  native optional packages without their postinstall optimization. Keep those
  optional packages and never treat a trust-on-first-use checksum as vendor signing.
- A root-list update alone may miss a compromised intermediate's cross-sign.
  Verify each real TLS path (HTTPX/certifi/CPython, system curl, Node, uv) and require
  certificate rejection, not timeout/DNS failure. Pin patched verifiers as well as
  artifacts; keep signed OS CA updates moving above an evidenced security floor.
  uv 0.13.5 already rejects these keys but cannot select the later CPython 3.12.16
  from its catalog; uv 0.13.6 adds it. Exact tool/runtime pins must work together.
- Managed Vercel Node selection controls a major, not an immutable patch. Cloudflare
  build Node selectors and Workers compatibility dates are distinct. A Caddy image
  with updated OS CAs may still contain pre-fix Go; current HTTP-only static serving
  is a bounded disposition, not proof it is safe for later TLS/ACME/proxy use.
- Railway's web console runs a login shell that drops image `ENV` (HOME from
  `/etc/passwd`, PATH reset by `/etc/profile`) while keeping `WORKDIR`; `railway ssh`
  is not the only entry path. Restore HOME/PATH from `/etc/bash.bashrc` (Debian's
  login profile sources it) and whitelist new `docker/` files in `.dockerignore`.
- HTTP account mutation goes through `AccountOperations` → `AccountService`, and every
  writer (HTTP and TUI) holds the host's `account_lock` across commit and notification,
  with the lock taken inside the shielded task, so publication order matches commit
  order. Notify with an explicit `invalidate` set: unchanged credential identity keeps
  scheduler state and snapshots (`put` never reuses refs), but an explicit source
  submission invalidates even an equal file reference, because file contents can change
  behind it. Conflicts carry `AccountFlowError.code` and trigger a resync. Never expose
  paths, selectors, organization IDs or org-ID fallback labels; restrict file references
  by basename and require regular files before open.
- `[tool.uv] required-version` is `==0.13.6`; a host `uv` 0.13.5 refuses every
  `uv sync/run` gate. Use a uv 0.13.6 binary rather than loosening the pin or
  bypassing `uv run` with a stale `.venv`.
- A shielded commit must own every input it still needs: clearing a secret in the
  cancellable request's `finally` lets the commit save a placeholder ref and delete
  the old secret. Reserve per-account throttles before the first await, schedule
  prepare expiry with a timer (lazy sweeps leave secrets past their TTL), and keep
  in-memory session puts on the loop so a cancelled thread cannot orphan the secret.
  A kept scheduler generation must still apply a shorter interval to its due time.
- Web forms: a conflict reload must rebase untouched draft fields (three-way against
  the old account), Esc/取消 must not close a form with a save in flight, and a
  lost/timed-out save may already be committed, so reload the list. Abort an
  in-flight prepare whenever its inputs change. Password managers ignore
  `autocomplete="off"`: use `new-password`, manager opt-outs and no native submit.
  TUI drags must report their end (drop/Esc/reload) and block row shortcuts mid-drag.
