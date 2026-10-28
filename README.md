# Usage TUI

A local terminal dashboard project for subscription usage and Claude Platform credit
balances. **The current implementation provides Python domain, local storage,
credential-resolution, fixed-origin HTTP transport, Claude subscription, Console
balance/organization-discovery, Grok billing, explicit provider-registry, polling/
freshness, deterministic offline-source libraries, an unresolved ChatGPT capability,
and a reusable Textual account-management screen. It is not yet a dashboard or
usable `usage` CLI.** No authenticated/live metric acceptance is claimed.
The console entry point declared in package metadata targets later integration;
do not invoke it at this stage. Account-screen embedding and workflows are described
below; dashboard and CLI launch integration remain separate work.

## Original goal and scope

终端 TUI，近实时查看 Claude 订阅 5h / 每周 / Fable 用量；Claude Platform
普通购买余额和赠送余额；GPT 订阅每周用量；GrokBuild / GrokChat 用量、剩余与
重置时间；支持连接账号或管理密钥。不做网页或 statusline。

The intended application is read-only and local: one terminal dashboard, not a web
server, statusline, inference client, or spending dashboard. Near-real-time means
bounded periodic observations, not provider push or an availability guarantee.

## What exists versus what is planned

C01 provides `src/` package metadata, declared runtime/development dependencies, and
frozen domain contracts: provider/account identities, credential kinds and resolved
credential values, exact money and quota values, metrics/grants/snapshots, provenance,
safe error types, validation helpers, and schema serialization. Domain tests are
source artifacts, not proof that checks have passed. Verification and chunk closure
are recorded only from exercised evidence in [PLAN.md](PLAN.md).

The C01 review correction bounds percentage representations before exact arithmetic:
at most 4,096 input string characters, 1,024 Decimal coefficient digits, and a stored
Decimal exponent from −1,000 through +1,000. Unsupported representations raise
`DomainError`, including through serialized snapshots. These bounds prevent a tiny
scientific-notation value from requesting enormous decimal expansion; a JSON byte
limit alone is insufficient. Supported percentages remain exact, including values
above 100%; remaining is exactly `max(0, 100 - used)`, not a rounded or capped used
value. C01 verification and closure are recorded in PLAN.md.

C02 adds library-level account/config persistence and credential storage. C03 adds
read-only Linux credential-file resolution and guarded HTTP transport. C04 adds the
Claude subscription adapter; C05 adds Console balances and organization discovery;
C06 adds the Grok billing adapter described below. C07 adds the explicit provider
registry and a truthful blocked ChatGPT capability, **not** an ordinary-chat quota
adapter. C08 adds the library-level scheduler and freshness state described below.
C09 adds the deterministic offline source described below; it is not yet wired to a
CLI or dashboard. C10 adds the reusable Textual account-management screen described
below. Dashboard rendering and CLI launch integration remain **planned, not current
support**:

| Requested metric | Intended meaning and source | Current live status |
|---|---|---|
| Claude 5h / weekly | Subscription used/remaining percentages and server reset from private OAuth usage | Library adapter implemented; no authenticated acceptance |
| Claude Fable weekly | Model-scoped weekly subset; not extra capacity and not an Opus/Sonnet alias | Library parser implemented; availability is plan/response dependent, no authenticated acceptance |
| Platform purchased / promotional | Separate totals across relevant credit grants, with per-grant expiry; authoritative overall total kept separately | Console library adapter implemented; private version-sensitive contract, no authenticated acceptance |
| Ordinary ChatGPT weekly | Actual chat-model subscription usage/remaining/reset | Required row retained by blocked capability; **upstream contract unresolved**, not just missing credentials |
| Grok shared pool / Build / Chat | Aggregate included allowance and validated same-payload product consumption shares | Library adapter implemented; private version-sensitive contract, no authenticated acceptance |

Grok product shares must not become independent `100 - share` allowances. Remaining
and reset refer to the shared pool only when unified billing is established. Credit
grants expire rather than reset weekly. Missing fields are unknown, not zero. API
spend is not credit balance; API usage is not subscription allowance. WHAM/Codex is
not a fallback for ordinary ChatGPT weekly chat usage. No requested live metric is
currently claimed as working or accepted.

## Development setup (Python libraries)

Requirements: Python 3.11+ and [uv](https://docs.astral.sh/uv/). The initial target for
the libraries is Linux/POSIX; cross-platform credential import is not supported.

The repository includes `uv.lock`. Install the locked development environment from
the repository root:

```sh
uv sync --locked --group dev
```

This is an environment setup command, not a claim that the full verification gate
has passed. Library modules include `usage_tui.domain`, `usage_tui.storage`,
`usage_tui.credentials`, `usage_tui.transport`, `usage_tui.providers.claude`,
`usage_tui.providers.console`, and `usage_tui.providers.grok`; do not run the future console entry point.
Transport alone does not normalize metrics.

## Textual account management (C10)

The account manager is a reusable terminal screen, not a web page, shell-based
setup substitute, or dashboard. There is no `usage accounts …` command or installed
dashboard launch workflow yet. A host Textual application can embed it with:

```python
from usage_tui.accounts import AccountManagerScreen

screen = AccountManagerScreen(
    account_store,
    credential_store,
    resolver,
    console_discovery=console_provider.discover_organizations,
    on_changed=handle_accounts_changed,
    on_reconnect=handle_reconnect,
)
app.push_screen(screen)
```

`on_changed(accounts)` receives the committed `tuple[Account, ...]`;
`on_reconnect(account_id)` receives the local opaque account ID after local
credential resolution succeeds. Either callback may return an awaitable. ChatGPT
reconnect only shows its blocked-contract guidance and does not resolve its key.
`console_discovery` accepts a resolved Console credential and asynchronously returns
the provider's `OrganizationChoice` candidates.

For local non-UI callers, `AccountService(account_store, credential_store)` exposes
`save(account, *, original=None, secret=None, persist=False)` and `remove(account)`,
both returning the resulting account tuple. Pass the previously loaded `original`
when editing; updates check for conflicts inside `AccountStore.mutate`. A new manual
secret gets a new opaque reference, and the old tool-owned secret is cleaned up
after config commit. Cleanup errors explicitly distinguish already-saved config
from failed credential cleanup; neither method promises atomicity across both
stores. Key deletion is a confirmed screen action, not a separate service method.

Supply the same `CredentialStore` to the screen and resolver so session-only
credentials remain resolvable within that process. The host owns scheduler
integration and must deliver committed account changes to `Scheduler.update_accounts`
to cancel obsolete in-flight generations. Embedding this screen alone does not start
polling or render usage metrics. `readonly=True, accounts=demo_accounts` supplies a
read-only account view without reading account files, credentials, or keyring;
demo viewing must not mutate real connections.

### Keyboard and account lifecycle

Use arrow keys to choose an account, Tab/Shift-Tab to move through form controls,
and Enter/Space to activate the focused control. On the account list, `a` adds,
`e` edits, Space enables/disables, `d` removes, `k` deletes this tool's saved key,
and `r` requests reconnect. Escape returns from the manager or cancels the current
dialog. Secret entry is masked; no reveal/copy control or saved-secret prefill is
provided. Every submit attempt clears the secret field, including validation/backend
failures; cancellation and teardown clear it too. Replacement confirmation opens
with the field already empty; canceling that confirmation leaves it empty and saves
no partial edits. Replacement, key deletion, and account removal require confirmation.
Do not paste
secrets into a shell command or use screen sharing/session recording while entering
them; masking does not protect the clipboard, terminal recorder, or process memory.

Add/edit forms select a provider and credential kind, label, and the applicable
credential reference or new secret; Space on the list changes enabled state.
Editing does not reveal the old
secret; leave replacement input empty to keep it. Choose explicitly between encrypted
persistence and **session only** for new manual secrets. A locked or unsupported
keyring produces guidance, not silent fallback. Session-only values belong to the
current process and do not become durable credentials merely because account
metadata exists; after exit/restart reconnect or supply a new secret. Python cannot
guarantee memory zeroization. The persistence backend is the supported Linux Secret
Service only; plaintext, alternative/chained, and null backends are rejected.

- **Claude subscription:** sign in through official Claude Code outside this app.
  Select the default credential-file reference or a specific private file; a
  supported manual bearer is also available. Imports remain references, not copies
  of refresh tokens. Reconnect guidance covers expiry and missing `user:profile`;
  inference-only setup tokens/API keys do not enable subscription reads.
- **Claude Platform:** a warning identifies `sessionKey` as a high-sensitivity
  session before masked entry. Supply only its value, never a password, Cookie
  header, HAR, or browser-store import. Use **Discover** to list eligible API
  organizations, then explicitly select the desired organization before saving,
  including when only one is available. Discovery is an explicit read, not automatic
  polling or permission to silently switch organizations. Missing/inaccessible
  selection requires reselection or billing-permission guidance. Replacing an existing
  Console session requires newly discovered, explicitly selected organization scope;
  the previous organization's selection is not an automatic fallback.
- **Grok:** run official `grok login` outside this app; select the default/private
  auth-file reference or a supported manual bearer. Discover scopes and explicitly
  select the intended identity when necessary; the saved nonsecret selector binds
  future reads. The tool never runs login, refreshes credentials, changes file
  permissions, or deletes the external login file.
- **ChatGPT:** a labeled local profile may have no credential, or an optional
  bearer/API key for local management only. It remains blocked by the missing
  ordinary-chat weekly contract; storage does not enable retrieval. No sensitive
  cookie/password prompt or WHAM/Codex fallback is offered.

API keys are local storage only, not substitutes for provider OAuth/session
credentials. Reconnect does not perform browser login or remote token renewal.
Removing an account deletes its local metadata and this tool's stored secret only;
deleting a key leaves the account profile available for reconnection. Neither
action revokes a remote session or removes Claude/Grok credential files. Account
metadata and keyring are separate stores, so failures are reported rather than
promising a cross-store atomic transaction. No real credential, real-keyring,
authenticated provider, or dashboard acceptance is established by this documentation.

## Claude subscription provider library (C04)

`from usage_tui.providers.claude import ClaudeProvider` exposes
`ClaudeProvider(transport)` with `requires_credential = True` and the three required
`metric_ids`: `claude.subscription.five_hour`, `claude.subscription.weekly`, and
`claude.subscription.fable_weekly`. Construction performs no request. The async
`fetch(account, credential, now)` method returns a domain `Snapshot`; pass a Claude
subscription `Account`, its provider-bound `ResolvedCredential`, and an aware
observation time. Credential resolution is a separate library operation, not an
implicit login or token refresh inside the adapter.

Each eligible fetch makes one `Transport.get_json` call for
`https://api.anthropic.com/api/oauth/usage`, using the transport's Bearer credential
and `anthropic-beta: oauth-2025-04-20` header. This is a private, version-sensitive
OAuth contract, not a supported public usage API or an inference API-key endpoint.
It may change without notice. Eligible first-party account credentials and a real
response comparison are still required for live acceptance; synthetic fixtures do
not establish either.

All results retain all three metric rows. `five_hour` and `seven_day` use
`utilization`, falling back to `used_percentage`. These are **used** percentages;
remaining is exactly `max(0, 100 - used)`, including overage. No absolute token or
message quota is inferred. A missing/null/invalid window stays unknown, not zero;
valid sibling windows survive in a partial snapshot. No usable percentage produces
a schema-error snapshot rather than successful empty bars. Invalid reset data
leaves a valid percentage intact but its reset unknown and the result partial.
Aware RFC3339 reset strings normalize to UTC; positive numeric timestamps are Unix
seconds, with values at least `10^11` interpreted as milliseconds only by this
Claude adapter. This is not a global timestamp heuristic.

Fable first uses valid `limits[]` entries with `kind == "weekly_scoped"` and
`scope.model.display_name.strip().casefold() == "fable"`, reading `percent` and
`resets_at` even when `is_active` is false. Conflicting valid duplicate scoped
entries make that row unknown rather than selecting one arbitrarily. Equal-percent
duplicates with an invalid reset must instead retain quota, leave reset unknown,
and produce a partial snapshot; invalid reset metadata alone is not a quota conflict.
The independently verified C04 review fix and closure evidence are recorded in
PLAN.md; this documentation does not add a verification claim.
If no valid scoped entry is available, legacy aliases are considered in order: `fable_weekly`,
`fable_seven_day`, `seven_day_fable`. Opus/Sonnet fields and extra-usage balances are
not substitutes. Fable is a model-scoped subset of weekly capacity, not an additive
allowance; absence establishes neither eligibility nor a fixed half-week quota.

The adapter itself does not poll, retry, preserve last-known values, render bars, or
connect accounts. Polling and last-known state belong to the C08 scheduler library;
rendering remains a later dashboard integration. C10 supplies the separate account
screen. No live request or CLI smoke is claimed here; exercised component
verification belongs in PLAN.md.

## Claude Platform Console library (C05)

`from usage_tui.providers.console import ConsoleProvider` exposes
`ConsoleProvider(transport)`, with `requires_credential = True` and the required
`metric_ids`: `claude.platform.purchased_balance`,
`claude.platform.promotional_balance`, and `claude.platform.total_balance`.
Its async `fetch(account, credential, now)` accepts a Claude Platform `Account`,
provider-bound `ResolvedCredential`, and aware observation time. Separate async
`discover_organizations(credential)` returns a tuple of frozen
`OrganizationChoice(id, label)` candidates. Construction does not make a request.
Each eligible balance fetch reads only the selected
organization's `/api/organizations/{organization_id}/prepaid/credits` route through
the guarded transport and retains all three required metric rows. Discovery uses
`GET /api/organizations` separately, not on every balance fetch. Both routes use
the fixed `https://platform.claude.com` origin and private, version-sensitive
contracts; synthetic fixtures do not establish authenticated compatibility.

Only a provider-bound `console_session` credential enables these reads. A
`sessionKey` is a **high-sensitivity account session**, not a limited API key.
Sign in to the first-party Console outside this application; supply only your own
session's cookie value through `CredentialStore`, never a password, full Cookie
header, HAR, or browser-store import. Persistent storage uses the supported secure
backend; explicit session-only storage is nonpersistent and still subject to
process-memory risk. The C10 account screen displays the sensitivity warning before
accepting a session; the adapter itself does not provide an interactive prompt.
The cookie is sent only to platform.claude.com, never api.anthropic.com or claude.ai.

Discovery candidates require the exact `api` capability and a validated `uuid`
matching `[A-Za-z0-9-]{1,64}`; names are sanitized for display. The caller must
obtain explicit organization selection, even if only one candidate is offered,
before saving the account. An absent or no-longer-accessible selection requires
reselection or permission guidance, never automatic switching. Discovery does not
persist an account or silently choose an organization. HTTP 401 and discovery
403 require reconnection; credits 403 means selected-organization billing permission
is denied. The C10 account screen supplies explicit selection and reconnect guidance.

`tranches` are purchased grants; `promo_tranches` are promotional grants. Category
balances sum **all** grants not known to be expired, not just the soonest-expiring
grant. Explicit empty arrays mean zero; missing/null arrays mean unknown. Invalid
grant numeric fields make only their category unavailable, preserving an
independently valid sibling category and top-level `amount`. Integer minor units
remain exact, including explicitly reported negative balances; zero-valued grants
are retained. Currency defaults to the evidenced `USD` only when omitted; exponent
defaults to `2` when omitted, with supplied values validated in `0…4`.

The authoritative top-level total is independent of category sums: it is not
reconstructed from them or used to invent a missing category. Disagreement is
reported rather than forcing equality. Unknown or malformed grant expiry stays
unknown and is included with an uncertainty note; known-expired grants are excluded
from active category totals. Per-grant amounts, program/name, and expiry remain
available as normalized `Grant` details, alongside nearest known active expiry.
Credits **expire; they do not reset weekly**. `subscription_api_credit` identifies
subscription-origin API credits but remains promotional when supplied in
`promo_tranches`, not a subscription usage window. Neither `/current_spend`, Admin
spend reports, API keys, nor inferred renewal dates fill balance gaps.

This library does not connect accounts, poll, retry, render grant details, or revoke
remote sessions. No CLI, live request, or authenticated balance acceptance is
claimed; orchestrator verification is recorded separately in PLAN.md.

## Grok billing provider library (C06)

`from usage_tui.providers.grok import GrokProvider` exposes
`GrokProvider(transport)` with `requires_credential = True` and the three required
`metric_ids`: `grok.subscription.shared_pool`, `grok.product.build`, and
`grok.product.chat`. Construction performs no request. Async
`fetch(account, credential, now)` accepts a Grok subscription `Account`, its
provider-bound `ResolvedCredential`, and an aware observation time, returning a
normalized `Snapshot` with all required rows even when unavailable.

Each eligible fetch reads exactly
`GET https://cli-chat-proxy.grok.com/v1/billing?format=credits` through guarded
Transport. This is the official CLI's private proxy billing request, not a public
xAI API-usage endpoint or a compatibility guarantee. Authentication is Bearer plus
`x-xai-token-auth: xai-grok-cli`; optional `x-userid` comes only from the same
resolved credential. No invented upstream version/client-mode headers are sent.
A live rejection requiring other headers is a compatibility blocker, not grounds
for guessing a first-party client identity.

Run official `grok login` outside this application. The separate resolver reads
`$GROK_HOME/auth.json` or `~/.grok/auth.json` (or a selected local file), with
explicit nonsecret scope selection when identities are ambiguous. Use a
provider-bound `grok_auth_file` or stored `manual_bearer`; manual identity remains
unknown unless supplied. API/management keys beginning `xai-` do not enable
subscription reads. Imports are read-only: no first-party file modification,
permission changes, refresh-token copying, or token refresh. Team-principal
incompatibility requires guidance, never fallback to another personal account.

`config.creditUsagePercent` supplies reported aggregate used percent. Missing or
invalid aggregate is unknown, not zero; on-demand spend, a prepaid wallet, or an
estimated cap cannot replace it. Only `config.isUnifiedBillingUser == true`
establishes the shared included-pool relationship. Otherwise reported consumption
remains visible with the pool relationship unknown, without asserting a shared
remaining allowance or attaching product resets.

`config.productUsage` must be a complete valid array: unique products with finite,
nonnegative `usagePercent`, reconciling to the aggregate from the **same payload**
within one percentage point. Unknown products remain visible under sanitized IDs
so other consumers are not lost. Malformed, duplicate, or inconsistent breakdowns
leave product rows unknown without erasing a valid aggregate. An explicit
`GrokBuild`/`GrokChat` zero is zero; an absent entry is unknown. Product percentages
are consumed shares, never independent `100 - share` allowances. When unified
billing is proven, Build/Chat reference the common pool for “剩余/重置：共享池”;
otherwise product remaining/reset are unavailable. No cross-request or
cross-account enrichment is used.

Reconciliation requires exact decimal values from the HTTP JSON decoder: numeric
tokens must be decoded directly as `Decimal`, never via a binary-float roundtrip.
Converting a rounded float back to a decimal cannot recover the wire value. C06
review reproduced aggregate `42.5` with raw numeric Build share
`43.500000000000000000000000000001` and Chat `0` incorrectly accepted as READY,
although the discrepancy exceeds one percentage point. The decoding correction
and raw-numeric boundary regression coverage are pending separate verification;
the earlier green component smoke does not verify this case.

In the normalized API, product consumption is carried in `Metric.detail`, with
`quota=None`: `QuotaValue` would imply an independent remaining allowance.
Validated additional products use stable `grok.product.other.<SHA-256>` metric
IDs (digest of the original product's UTF-8 bytes) and sanitized labels. Proven
unified product rows link `shared_pool_id` and
`reset_at` to the common pool. Without proven semantics, aggregate consumption is
also detail-only, with no quota, reset, or shared-pool reference.

The server's `currentPeriod.type` determines weekly/monthly labeling; unknown
types remain a generic period, regardless of marketing tier. Aware RFC3339
`currentPeriod.end` supplies reset; `billingPeriodEnd` is considered only when that
end is absent, not as a rescue for a malformed end. Reversed period bounds are
invalid. Bad reset metadata must not erase valid usage; reset stays unknown.
There is no invented renewal or reset to zero when time passes.

The adapter does not invoke Grok/ACP subprocesses, infer included usage from
`onDemandUsed / onDemandCap`, look up reset coupons, poll, retry, or connect
accounts. Typed ACP responses may omit product breakdown and are not a fallback.
No CLI/TUI behavior, live request, or authenticated Grok acceptance is claimed;
exercised verification remains separately recorded in PLAN.md.

## Provider registry and unresolved ChatGPT capability (C07)

`build_providers(transport, resolver)` explicitly constructs the registry for
`claude_subscription`, `claude_platform`, `grok_subscription`, and
`chatgpt_subscription`. Provider construction/imports do not fetch data, probe the
environment, or read secrets. Each provider enumerates its required metric IDs;
the live Claude, Console, and Grok adapters require credentials.

The ChatGPT entry is a capability object, not a network adapter. It retains the
required `chatgpt.subscription.weekly` row and returns the structured
`upstream_contract_missing` result with unresolved provenance
(`SourceRef(kind="unresolved")`) and a safe Chinese/English explanation. Its
`requires_credential` is false: it does not resolve saved credentials, access
transport, or make a request. The C08 scheduler honors that flag rather than
opening a saved secret before publishing the blocked result, and does not
periodically poll the unresolved capability.

The blocker is a defensible ordinary-chat read-only request/authentication and
model/window/reset contract, not merely a missing token. Static research and its
remaining prerequisites are recorded in [PLAN.md](PLAN.md) §§4.4 and 7. A
`conversation/init` feature-limit field alone does not establish ordinary GPT
weekly quota or authorize a potentially state-changing POST. WHAM/Codex quotas,
OpenAI API consumption, local message counts, and user-entered caps are not
fallbacks. Returning this blocked state does not complete the requested metric.

A local labeled ChatGPT account profile may exist without a credential. Optional
user-provided bearer/API-key storage through the account screen does **not** enable
weekly retrieval; there is no ChatGPT setup command. Do not supply a cookie or
password, extract browser sessions, or invent an OAuth client to unblock it.
No ordinary ChatGPT live quota integration or authenticated acceptance is claimed.

## Deterministic offline-source library (C09)

`from usage_tui.demo import DemoClock, DemoSource` exposes an offline alternative
to the scheduler's published snapshot stream. Construct
`DemoSource(*, scenario="healthy", publish, clock=None)` with a synchronous
`publish(snapshot)` callback; `scenario` accepts `healthy` or `errors`. `.accounts`
contains the fictional domain `Account` values, and `.clock` is the deterministic
`DemoClock`. The source loads only its packaged `usage_tui/fixtures/demo.json`
resource, not account configuration, keyring entries, or first-party login files.
It does not construct a credential resolver, live provider registry, HTTP client,
or live transport, and never sends a request. It is an explicitly selected source,
**not a fallback when live retrieval fails**.

The async lifecycle is `start()`, `refresh(account_id=None)`,
`update_accounts(accounts)`, and `stop()`. Start and account updates publish the
enabled fixture accounts immediately; refresh republishes all or one selected
sample on the caller's event loop, with no background polling task. Account updates
may select, edit, or disable only the current scenario's fictional profiles; new
IDs, changed providers/organizations, or credential references/selectors are rejected.
Repeated start is idempotent; stop permanently prevents further publication.
`tick(seconds=1)` advances demo time without fetching or publishing. `DemoClock`
supplies `now()`, `monotonic()`, `advance(seconds=1)`, and async `sleep(seconds)`;
sleepers wake when the clock is advanced, not as machine time passes. The default
observation time is `2026-10-28T12:00:00Z`; an injected `DemoClock(now=...)` rebases
fixture reset, retry, grant-expiry, and last-known offsets to that initial time.
Use `.clock.now()` with `scheduler.freshness` for deterministic age/reset displays;
advancing time does not zero quota or fabricate a new allowance.

| Scenario | Synthetic display inputs |
|---|---|
| `healthy` | Four fictional provider accounts, all ten required metric rows, subscription windows, credit balances/grants, shared-pool product consumption, and an explicitly synthetic GPT weekly sample |
| `errors` | Eight fictional accounts covering auth required, permission denied, rate limit/retry, network failure with stale last-known data, schema error, partial/unknown Fable, missing Grok product breakdown, and synthetic GPT sample data |

**Every account, value, timestamp, and scenario is fictional.** All metric
provenance is `offline_demo`; a ready ChatGPT sample is explicitly labeled
synthetic demonstration, **not a working adapter or evidence of live support**.
Ordinary ChatGPT retrieval remains blocked by the missing upstream contract.
Error scenarios are not actual service failures. Domain test/source assertions
and this library documentation do not establish exercised verification; the
orchestrator records component smoke and checks separately in PLAN.md.

This is a Python library only. `usage --demo`, `--scenario`, countdown rendering,
keyboard controls, and the terminal dashboard are not implemented yet; do not
invoke the declared future entry point as though this source delivered a CLI/TUI.

## Polling and freshness library (C08)

`usage_tui.scheduler.Scheduler(accounts, providers, resolver, *, clock, rng,
publish)` coordinates the provider libraries; it is not a dashboard or background
daemon. Its async lifecycle is `start()`, `refresh(account_id=None)`,
`update_accounts(accounts)`, and `stop()`. `publish(snapshot)` is a synchronous
callback on the application event loop. The injected clock supplies UTC `now()`,
`monotonic()`, and async `sleep(seconds)`; `SystemClock` is the real-clock
implementation, and the RNG supplies `uniform(a, b)`.

- Enabled accounts fetch immediately on start. Normal polling uses each account's
  validated integer interval (default 60 seconds, configurable 30–3600), with ±10%
  jitter and no interval below 30 seconds. Deadlines use monotonic time, not
  wall-clock subtraction between polls. Eligible accounts are selected by oldest
  due deadline so an overdue initial poll is not starved by accounts polling again.
- Only one fetch per account and at most two accounts fetch concurrently. The
  five-second same-origin spacing gate applies after credential resolution,
  immediately before the provider request starts, not when an attempt is queued.
  A fetch retrieves the provider's complete snapshot, not one request per metric.
  Console organization discovery is still an explicit connection operation.
- `refresh()` is a library-level explicit reconnect attempt, not an implemented
  `r` key binding. Repeated requests coalesce, do not overlap in-flight work, and
  cannot bypass origin spacing or retry deadlines. Authentication, permission, and
  unconfigured failures suspend automatic polling until explicit refresh or account
  update; external login files are not monitored during suspension.
- Rate-limit, network, provider, and schema failures use exponential retry delays
  starting at 60, 120, 240 seconds, capped at 15 minutes plus bounded jitter. A valid
  server `Retry-After` has at least a 60-second delay and is never shortened to that
  cap. Retry presentation timestamps saturate at the largest representable UTC
  datetime rather than overflowing; this must not shorten the monotonic embargo.
  Compatible successful fetches reset failure backoff.
- Credential-free unresolved ChatGPT accounts publish their blocked capability once
  per account generation, without resolving a saved secret or making a request.
  They are not periodically polled, and manual refresh does not poll them.
- Account updates invalidate prior in-flight generations, including updates using
  the same credential reference. Removal, disabling, replacement, and shutdown
  cancel obsolete work; a late result from an obsolete generation is not published.
  Account updates cannot erase an existing same-provider retry embargo. Each live
  attempt captures its credential once; replacing a secret during an attempt must
  be accompanied by `update_accounts`, even if its opaque reference is unchanged.
  Otherwise external file changes are discovered on the next attempt. `stop()`
  cancels scheduler tasks; injected providers/transports are borrowed and their
  owner remains responsible for their resources.

Fetch errors retain last-good metrics/grants and their original successful
`fetched_at`, while publishing the new fetch state, `attempted_at`, retry time, and
safe diagnostic. Failed attempts therefore do not make observations fresh. A new
compatible response (including `partial`) replaces the current fields: a missing
Fable/product value is unknown, not an old value silently carried into the new
observation.

`freshness(snapshot, now, poll_interval_seconds=60, *, metric=None)` returns
`Freshness(age_seconds, attempted_age_seconds, stale, reset_passed, last_known)`.
Attempt age is separate from successful-observation age. Successful observation
age is stale after `max(2 * poll_interval_seconds, 120)` seconds, or when a known
reset crosses after the observation without a new observation. A reset already
passed at observation time does not alone imply a missed later observation.
Without any successful observation, age is unknown and stale is true. Passing
`metric` scopes the reset check to that row; stale/last-known information does not
change its raw metric state. Reaching reset never zeroes usage or fabricates a new
period: presentation must say it is awaiting refresh. Computing freshness does not
issue requests.

C08 review identified three scheduler defects: insertion-order starvation, origin
spacing consumed by slow credential resolution, and retry timestamp overflow near
`datetime.max`. The orchestrator's actual seven-account, same-origin, 30-second
interval reproduction observed initial results for only six accounts over more
than 100 seconds. The other two findings are static review findings, not exercised
reproductions. The fairness, actual-request-start spacing, and saturated-retry
contracts above describe the required corrections; separate fix verification and
independent rereview remain pending. Earlier green gates and the single-account
smoke do not verify these corrections. C08 is not closed; C09 remains gated.

No CLI/TUI controls, countdown display, offline source, live authenticated polling,
or new verification outcome are claimed here. Exact exercised component evidence
and remaining live prerequisites belong separately in PLAN.md.

## Local storage library (C02)

`AccountStore(path=None)` uses
`$XDG_CONFIG_HOME/usage-tui/accounts.json`, falling back to
`~/.config/usage-tui/accounts.json`. An explicit path supports isolated callers.
Schema version `1` contains account metadata and opaque credential references,
never credential values. `load()` returns accounts; `save(accounts)` replaces a
validated complete set. For read-modify-write changes use `mutate(change)`, which
locks and rereads before applying the callback, rather than a stale `load`/`save`
pair. A callback exception leaves the stored configuration unchanged.

Manual-secret references must use the store's opaque reference format; inline
manual credentials and persisted references bound to another account are rejected.
External first-party file references are preserved without opening those files;
the credential resolver performs read-time permission and schema validation.

On supported POSIX/Linux systems the store uses a private `0700` directory,
`0600` config/lock files, a separate advisory lock, and atomic same-directory
replacement. Config reads are limited to 1 MiB. Unsafe file ownership/permissions,
symlinks, hardlinks, malformed data, and unsupported schema versions raise a safe
`ConfigError`; an existing invalid configuration is not overwritten. These are
cooperating-writer locks, not protection against hostile code running as your user.

A failure after atomic replacement (such as a directory-sync failure) can report
an error after the new config is already visible; atomic visibility is not a
guarantee that every failed save left the previous version in place.

`CredentialStore().put(account_id, secret, persist=False)` explicitly selects
instance-local memory and returns an opaque `session:` reference. It does not
access the OS keyring and cannot survive the store instance/process. With
`persist=True`, the store lazily uses only the supported Linux Secret Service
backend, returning a nonsecret `keyring:` reference. Null, fail, plaintext,
chained, unrecognized, and subclassed backends are rejected; unavailable or locked
keyring operations raise `CredentialError`, never silently fall back to memory
or plaintext. `get(ref)` retrieves and `delete(ref)` removes this tool's stored
credential; neither operates on external Claude/Grok login files or revokes a
remote session. The C10 account manager coordinates account metadata and local-secret
removal with confirmation; the low-level store operations remain separate calls.

No real-keyring acceptance or C02 check outcome is claimed here. Python cannot
guarantee memory zeroization, and a reference is not itself a secret-management
permission boundary. C10 adds masked inputs and account-removal confirmation; C08
supplies cancellation of obsolete in-flight provider work when account updates
are delivered to the scheduler.

## Credential resolution and transport libraries (C03)

`CredentialResolver(credential_store=None, *, clock=None).resolve(account)`
captures a credential once for a fetch attempt and returns a frozen
`ResolvedCredential` bound to the account's explicit
provider and credential kind. The secret is excluded from its representation;
identity, expiry, selected organization, and a nonsecret generation fingerprint
are separate metadata. A fingerprint is not a token suffix for display or logging.
Manual credentials are retrieved through `CredentialStore` opaque references,
not treated as inline account configuration. Local API-key storage does not enable
subscription metrics or Console balances, and the unresolved ChatGPT capability
must not resolve a saved credential or invoke transport.

Linux first-party imports are literal local paths (absolute or relative), not
commands or URLs. The explicit `default` reference selects these default files
only when resolving an account, not when constructing the resolver:

- Claude Code: `$CLAUDE_CONFIG_DIR/.credentials.json`, otherwise
  `~/.claude/.credentials.json`, or an explicit local file reference. Resolution
  reads `claudeAiOauth.accessToken`; optional expiry is Unix milliseconds. If
  scopes are present they must permit `user:profile`. Inference-only setup tokens
  and API keys are not substitutes for an eligible profile-scoped credential.
- Grok: `$GROK_HOME/auth.json`, otherwise `~/.grok/auth.json`, or an explicit
  local file reference. Resolution uses the selected `https://auth.x.ai::<client-id>`
  entry; the legacy `https://accounts.x.ai/sign-in` entry is a fallback only when
  unambiguous. Multiple matching identities require a saved nonsecret scope
  selector; no account is silently chosen. An optional `user_id` comes from that
  same selected entry. Unknown expiry is not evidence of freshness.

Imported files must be regular, effective-user-owned files with exact `0600` mode
on supported Linux, with bounded reads of at most 1 MiB. Unsafe permissions,
symlinks, malformed schema,
expired credentials, and ambiguous profiles produce safe errors, not fallback
credentials. Resolution does not chmod, write, refresh, or delete first-party
files, run login commands, or copy refresh tokens into app storage. Sign in or
renew credentials with the first-party tool outside this application. Fixtures
are synthetic; they do not establish authenticated compatibility.

`Transport(*, http_transport=None, clock=None)` accepts an injected in-memory HTTP
transport and clock for isolated callers; URL guards remain in force with either.
It needs no persistent client lifecycle: each read creates and closes its client.
`Transport.get_json(provider, path, credential=resolved)` is an async read-only JSON
boundary. Before constructing authentication headers or opening a socket it checks
the resolved provider binding, credential kind, and exact allowlisted path:

| Provider | Fixed HTTPS origin and permitted path | Credential and authentication |
|---|---|---|
| Claude subscription | `https://api.anthropic.com/api/oauth/usage` | `claude_code_file` or `manual_bearer`; Bearer plus `anthropic-beta: oauth-2025-04-20` |
| Claude Platform | `https://platform.claude.com/api/organizations` and `/api/organizations/{id}/prepaid/credits`, with ID `[A-Za-z0-9-]{1,64}` | `console_session` only; `Cookie: sessionKey=<value>` |
| Grok subscription | `https://cli-chat-proxy.grok.com/v1/billing?format=credits` | `grok_auth_file` or `manual_bearer`; Bearer, `x-xai-token-auth: xai-grok-cli`, and `x-userid` only from the same resolved credential when present |
| Ordinary ChatGPT | None | No transport request; upstream contract unresolved |

All other paths, origins, credential-kind/provider combinations, and API keys are
rejected for these reads. There is no user-configurable base URL. Console accepts
only a cookie value, not a full Cookie header or HAR; invalid cookie delimiters
and controls are rejected. Treat a `sessionKey` as a high-sensitivity session, not
a limited API key. The C10 connection screen warns before accepting it and requires
explicit organization selection; transport does not discover or select accounts.

Production transport verifies TLS, uses GET only, disables redirects and implicit
proxy/netrc environment use, and does not persist server cookies between requests.
Requests include JSON acceptance and the installed-package User-Agent, not an
invented upstream client identity. Connect timeout is 5 seconds, with a 10-second
overall request deadline and a streamed 1 MiB response limit. JSON shape validation
and metric interpretation belong to provider adapters. Safe `TransportError` values
carry only fetch state, fixed code, optional HTTP status and retry time, never a
response body, secret, credential path, or arbitrary exception text. A valid 429
`Retry-After` is preserved with a minimum 60-second deadline; the C08 scheduler
implements retry/backoff outside this transport boundary.

No account setup or key-management CLI command works at this stage. Use the Textual
account screen, not shell arguments, for interactive secrets. Do not paste
credentials into chat, issues, documentation, or fixtures. No
browser extraction, token refresh protocol, live-provider acceptance, or real
OS-keyring acceptance is claimed. Private HTTP routes and product fields remain
version-sensitive, not official public API guarantees. Researched sources and
exact contracts are in PLAN.md §§4 and 7; ordinary ChatGPT weekly quota still needs
a defensible read-only request/authentication and metric contract.

See [SECURITY.md](SECURITY.md) for current limitations and planned controls,
[CHANGELOG.md](CHANGELOG.md) for delivered changes, and PLAN.md for the only progress
tracker and the separate code/live acceptance matrix.
