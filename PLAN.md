# Usage TUI — durable implementation and research plan

## 0. Status, purpose, and scheduling authority

Planning baseline: 2026-10-28. The repository was empty when scoped; research sources were read without browser automation or account credentials, and no tests, lint, formatters, gates, or commits were run as part of planning. Planning commit `6f731df57990b6512387ec481ccb693a214d1617`, green C01 draft `4d082d72f37a1ceb6d5e1e9cc68bcad7c7d62baa`, separately verified review-fix commit `650a8a5`, and C01 closure commit `2347f1f` exist. C01 is closed. C02 green draft `af68b54` passed full gates, actual storage/session smoke, storage LSP diagnostics, and clean independent reviews; closure commit `2ab03fb` exists. C03 is closed with green draft `5a9cc60`, completed bounded documentation/Lessons, full green gates (345 tests passed in 0.80s; Ruff check passed; 16 files already formatted), actual read-only resolver/Transport smoke, credentials/transport LSP diagnostics OK, and clean independent reviews `agent://c03-review-1` and `agent://c03-review-2`; no review fixes required; closure commit `d5e6c1a` exists. C04 is closed with green draft `e4e9798`, separately verified review-fix commit `42a4abf`, completed bounded documentation/Lessons, final green gates (425 tests passed in 0.85s; Ruff check passed; 18 files already formatted), actual real ClaudeProvider/Transport fixture smoke and reproduced-before/confirmed-after Fable regression smoke, and clean independent rereviews `agent://c04-rereview-1` and `agent://c04-rereview-2`. Claude LSP diagnostics were OK before the review fix; no post-fix LSP check is claimed. C04 closure commit `6576e23` exists. C05 is closed with green draft `98e0c6d`, completed implementation and bounded documentation, full green gates (528 tests in 1.00s; Ruff check passed; 20 files already formatted), Console LSP diagnostics OK, actual Console discovery/explicit-organization credits smoke, and clean independent reviews `agent://c05-review-1` and `agent://c05-review-2`; no review fixes required; closure commit `8e74532` exists. C06 is checked and closed with green draft `515b4f4`, separately verified review-fix `9df9232`, completed implementation and bounded documentation/Lessons, final green gates (643 tests in 1.27s; Ruff check passed; 22 files already formatted), actual Grok component and reproduced-before/confirmed-after raw-numeric regression smoke, and clean independent rereviews `agent://c06-rereview-1` and `agent://c06-rereview-2`. Grok LSP diagnostics were OK before the review fix only; no post-fix LSP check is claimed. C06 closure commit `6cf9386` exists. C07 is checked and closed for research/capability only at green draft `9eae70a`: implementation and bounded documentation/Lessons landed, supplied orchestrator gate passed (653 tests in 1.15s; Ruff check passed; 26 files already formatted), base/ChatGPT LSP diagnostics OK, actual registry/blocked-capability smoke passed without dependency, credential, or network access, and independent reviews `agent://c07-review-1` and `agent://c07-review-2` are clean; no review fixes required. C07 closure commit is pending; C08 is next after that commit. Ordinary ChatGPT weekly retrieval remains blocked by the missing upstream contract. No live account checks have been exercised.

Original goal: **终端 TUI，近实时查看 Claude 订阅 5h / 每周 / Fable 用量；Claude Platform 普通购买余额和赠送余额；GPT 订阅每周用量；GrokBuild / GrokChat 用量、剩余与重置时间；支持连接账号或管理密钥。不做网页或 statusline。**

The orchestrator schedules bounded worker assignments from §8; it does not invent architecture or implement code. Workers implement the contracts here and report concrete changes/blockers. They must not quietly reinterpret GPT as Codex, billing spend as credit balance, Fable as an additive allowance, or Grok product shares as independent quotas. If evidence contradicts a contract, a research worker proposes a sourced change to this plan before implementation changes its meaning.

A finished error/unavailable UI is useful code, but is **not** completion of an unavailable upstream metric. Track code completion and authenticated metric acceptance separately (§9). The ordinary ChatGPT weekly metric currently has an unresolved upstream contract, not merely missing credentials. Keep it visible and open until resolved or the user explicitly changes scope.

### Durable progress convention

This file is the only progress tracker. The orchestrator updates checkboxes, acceptance matrix, and this ledger from worker reports and its own exercised evidence. Never mark a chunk complete from a worker's unsupported assertion. Do not place credentials, raw responses, email addresses, or account IDs here. For every C01–C14 chunk record separately: implementation landed; bounded documentation/changelog task completed; repo-root `AGENTS.md` Lessons updated (or observed “no new lesson”); exact orchestrator check commands/outcomes; actual smoke observations; green draft commit; review outcome; separately verified review-fix commits; and closed status. Worker implementation evidence is not orchestrator verification. Keep upstream/live blockers independent of code closure.

A checked chunk heading records implementation/documentation landed and orchestrator checks plus actual component smoke passed; it does not imply review, commits, or closure. Those remain separate ledger fields, and a dependent chunk is not runnable until its predecessor closes.

| Field | Current value |
|---|---|
| Planning | Reviewed and committed baseline; C01 and C02 closed, C02 closure commit `2ab03fb`; C03 closed with green draft `5a9cc60`, bounded docs/Lessons, full green gates, actual smoke, credentials/transport LSP diagnostics OK, clean independent reviews, and closure commit `d5e6c1a`. C04 closed with green draft `e4e9798`, separately verified review-fix `42a4abf`, completed bounded docs/Lessons, final green gates, actual component/regression smoke, clean independent rereviews, and closure commit `6576e23`. C05 closed with green draft `98e0c6d`, completed implementation and bounded documentation, full green gates, Console LSP diagnostics, actual smoke, and clean independent reviews; no review fixes required; closure commit `8e74532`. C06 checked and closed with green draft `515b4f4`, separately verified fix `9df9232`, bounded docs/Lessons, final green gates, actual component/regression smoke, pre-fix-only Grok LSP diagnostics, and clean independent rereviews; closure commit `6cf9386` exists. C07 research/capability closed at green draft `9eae70a` with bounded docs/Lessons, full green gate, base/ChatGPT LSP diagnostics OK, actual registry/blocked-capability smoke, and clean independent reviews; no review fixes required; closure commit pending. C08 next after closure commit; ordinary ChatGPT quota retrieval remains blocked |
| Planning commit | `6f731df57990b6512387ec481ccb693a214d1617` — `docs(plan): record reviewed usage implementation plan` |
| Last closed implementation chunk | C07 — ChatGPT research and honest capability boundary only; green draft `9eae70a`; clean independent reviews; no review fixes required; closure commit pending. Actual ordinary ChatGPT weekly quota remains unresolved |
| Next runnable action | Commit C07 closure, then dispatch C08 polling and stale snapshot state machine. Ordinary ChatGPT weekly retrieval remains blocked on the missing upstream contract |
| Implementation / docs / Lessons | C01-A package/domain and C01-B initial `uv.lock` landed; D(C01) and review follow-on completed bounded docs and Lessons. C02 implementation and D(C02) completed `README.md`, `CHANGELOG.md`, `SECURITY.md`, and repo-root `AGENTS.md`; recorded Lessons cover stable sibling locking/reread-under-lock mutation and exact secure-backend policy with explicit session-only isolation. C03 transport/credential-resolution implementation and bounded documentation/Lessons completed in green draft `5a9cc60`. C04 Claude subscription adapter implementation and D(C04) completed `README.md`, `CHANGELOG.md`, `SECURITY.md`, and repo-root `AGENTS.md`; Lessons preserve quota/window independence, scoped Fable identity/inactive/conflict semantics, provider-local timestamp heuristics, and quota/reset independence clarified by review |
| C05 implementation / docs | Console balance adapter, organization discovery, fixtures/tests, and bounded documentation landed. Closed with full green gates, Console LSP diagnostics, actual component smoke, green draft `98e0c6d`, and clean independent reviews; no review fixes required; closure commit `8e74532` |
| C06 implementation / docs | Grok billing adapter, product-share fixtures/tests, and bounded documentation/Lessons landed. Approved detail-only product consumption representation avoids implicit independent quota remaining. Review-fix documentation/Lessons record direct Decimal HTTP decoding and raw-numeric boundary tests. Closed with final green gates, actual component/regression smoke, green draft `515b4f4`, separately verified fix `9df9232`, and clean independent rereviews; closure commit `6cf9386` |
| C07 implementation / docs / Lessons | C07-A static research and C07-B explicit registry/blocked capability landed at green draft `9eae70a`. Bounded `README.md`, `CHANGELOG.md`, `SECURITY.md`, and repo-root `AGENTS.md` updates document required metric enumeration, the credential-free unresolved capability, and the reusable capability/secret-resolution lesson. Closed for research/capability with full gate, base/ChatGPT LSP diagnostics OK, actual blocked-capability smoke, and clean independent reviews; no review fixes required. Ordinary ChatGPT quota retrieval is not implemented; missing upstream contract remains open |
| Orchestrator checks | Baseline `uv sync --locked --group dev` succeeded. Final review-fix gate: `uv run pytest -q`: 101 passed in 0.13s; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: 8 files already formatted; domain LSP diagnostics OK |
| C02 orchestrator full green gate | `uv run pytest -q`: 167 passed in 0.55s; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: 11 files already formatted; storage LSP diagnostics OK. Evidence preserved from the orchestrator's exercised gate; no closure rechecks run |
| C03 orchestrator gate status | Full green: `uv run pytest -q`: 345 passed in 0.80s; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: 16 files already formatted; credentials/transport LSP diagnostics OK. Exercised orchestrator evidence preserved; no closure rechecks run |
| C04 orchestrator gate status | Final separately exercised review-fix gate: `uv run pytest -q`: 425 passed in 0.85s; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: 18 files already formatted. Initial pre-finding gate: 419 passed in 0.85s with Ruff check green and 18 files already formatted. Claude LSP diagnostics OK before the review fix only; no post-fix LSP check claimed. Supplied orchestrator evidence preserved; no closure rechecks run |
| C05 orchestrator gate status | Full green: `uv run pytest -q`: 528 passed in 1.00s; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: 20 files already formatted; Console LSP diagnostics OK. Supplied orchestrator evidence preserved; no rechecks run |
| C06 orchestrator gate status | Final separately exercised review-fix gate: `uv run pytest -q`: 643 passed in 1.27s; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: 22 files already formatted. Pre-review gate: 624 passed in 1.11s, Ruff check green, 22 files already formatted. Grok LSP diagnostics OK before the review fix only; no post-fix LSP check claimed. Supplied orchestrator evidence preserved; no closure rechecks run |
| C07 orchestrator gate status | Supplied orchestrator evidence: `uv run pytest -q`: 653 passed in 1.15s; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: 26 files already formatted; base/ChatGPT LSP diagnostics OK. No worker or closure rechecks run |
| Actual component smoke | Baseline `uv run --locked python -c` assertions passed for exact Account/Snapshot round-trips, Decimal overage, UTC timestamps, money, and invalid-input rejection. Final actual `uv run --locked python -c` smoke passed hostile exponent rejection and exact normal remainder/overage; metadata-only proof demonstrated the old precision risk without expanding hostile exponents. This is domain-library evidence, not CLI/TUI or live-provider acceptance |
| C02 actual component smoke | Actual `uv run --locked python -c` storage/session smoke passed: private temporary config directory `0700` and config file `0600`; AccountStore save/reload/mutate/delete; no serialized synthetic secret; session-only CredentialStore put/get/delete. No real keyring was contacted; persistent OS-keyring and live-provider acceptance remain separate and unexercised |
| C03 actual component smoke | Actual read-only smoke passed: resolve a synthetic Claude credential from a private file, then use the real Transport with injected httpx MockTransport; decoded response, exact fixed origin/auth headers, and cross-provider rejection asserted. No live service or real credential used |
| C04 actual component smoke | Actual real ClaudeProvider plus Transport smoke with an injected in-memory HTTP fixture passed: one request produced all three windows with used percentages `12.5`, `110.25`, and `23.75`; scoped Fable retained and overage remaining clamped to `0`. Actual regression reproduction before the fix lost Fable quota (UNKNOWN, quota None); confirmed-after smoke retained used percentage `23.75`, reset None, and partial fetch status for equal-percent scoped duplicates with malformed reset. No live service or real credential used |
| C05 actual component smoke | Actual Console discovery and credits adapter/Transport smoke passed with an explicitly selected synthetic organization: purchased `700`, promotional `0`, and authoritative total `700` minor units; expiry assertions passed. The smoke harness initially omitted required Account `credential_ref`; correcting the harness made the smoke pass, not a product fix. No live service or real credential used |
| C06 actual component smoke | Actual Grok adapter/Transport smoke green: unified shared pool used `42.5`%, remaining `57.5`%; Build consumption `32.5`%, Chat consumption `10`%, with shared-pool references rather than independent quota remaining/reset. Detached/unproven-pool smoke also green. Actual raw-numeric regression smoke reproduced erroneous READY product rows before the fix for aggregate `42.5`, Build `43.500000000000000000000000000001`, Chat `0`; after `9df9232`, product rows are UNKNOWN and valid shared-pool used `42.5`% is retained. This is supplied orchestrator offline component evidence, not live/authenticated acceptance |
| C07 actual component smoke | Supplied actual explicit registry and ChatGPT blocked-capability smoke passed without dependency, credential, or network access. Required `chatgpt.subscription.weekly` row remains BLOCKED, with `upstream_contract_missing` and unresolved provenance. This verifies the capability boundary, not ordinary ChatGPT quota retrieval or live/authenticated acceptance |
| Green draft commit | C01: `4d082d72f37a1ceb6d5e1e9cc68bcad7c7d62baa`; C02: `af68b54` — green storage/config/session baseline before independent review. C03: `5a9cc60` — green transport/credential-resolution baseline before independent review. C04: `e4e9798` — green Claude subscription adapter baseline before independent review. C05: `98e0c6d` — green Console balance/discovery baseline before independent review. C06: `515b4f4` — green Grok billing/product-share baseline before independent review. C07: `9eae70a` — green research/registry/blocked-capability baseline before independent review |
| Review outcome | C01 initial findings resolved; independent rereviews `agent://c01-rereview-1` and `agent://c01-rereview-2` clean. C02 independent reviews `agent://c02-review-1` and `agent://c02-review-2` both clean, with no actionable findings or review fixes required. C03 independent reviews `agent://c03-review-1` and `agent://c03-review-2` both clean at green draft `5a9cc60`; no actionable findings or review fixes required. C04: `agent://c04-review-1` found equal-percent scoped Fable duplicates with a malformed reset incorrectly discard valid quota; reproduced before the fix and resolved by `42a4abf`. Independent rereviews `agent://c04-rereview-1` and `agent://c04-rereview-2` both clean at the fix, with no remaining actionable findings. C05 independent reviews `agent://c05-review-1` and `agent://c05-review-2` both clean at green draft `98e0c6d`; no actionable findings or review fixes required |
| C06 review outcome | `agent://c06-review-1` reproduced aggregate `42.5` with raw JSON numeric Build share `43.500000000000000000000000000001` and Chat `0` incorrectly accepted as READY. Ordinary HTTP JSON decoding rounded the share to float `43.5`, losing the discrepancy above one percentage point; string-valued boundary tests did not exercise the numeric wire path. Resolved by `9df9232`; independent rereviews `agent://c06-rereview-1` and `agent://c06-rereview-2` both clean, with no remaining actionable findings |
| Review-fix commits / verification | C01: `650a8a5`, separately verified with final gate/smoke and clean independent rereviews. C02 and C03: not applicable — independent reviews clean; no review-fix commit or fix verification required. C04: `42a4abf`, separately verified by final 425-test/0.85s gate, Ruff check/18-file format check, and actual regression smoke retaining `23.75` quota with reset None and partial status; clean independent rereviews. C05: not applicable — independent reviews clean; no review-fix commit or fix verification required |
| C06 review-fix verification | Fix `9df9232` preserves HTTP JSON numeric tokens directly as Decimal without a float roundtrip; regression coverage sends raw JSON numeric boundary values through Transport and GrokProvider. Separately verified by final 643-test/1.27s gate, Ruff check/22-file format check, and actual reproduced-before/confirmed-after regression smoke: erroneous READY product rows become UNKNOWN while valid shared-pool used `42.5`% is retained. Independent rereviews `agent://c06-rereview-1` and `agent://c06-rereview-2` clean |
| C07 lifecycle | Closed for research/capability only: implementation, bounded docs/Lessons, supplied 653-test/1.15s full gate, Ruff check/26-file format check, base/ChatGPT LSP diagnostics OK, actual no-dependency/credential/network registry and blocked-capability smoke, and green draft `9eae70a` accounted for. Independent reviews `agent://c07-review-1` and `agent://c07-review-2` both clean with no actionable findings; review-fix commits and separate fix verification not applicable. Closure commit pending; dispatch C08 after that commit. Actual ChatGPT weekly quota retrieval and authenticated acceptance remain blocked on the missing upstream contract |
| Clean close | C01 closure commit `2347f1f` exists. C02 closure commit `2ab03fb` exists: implementation, bounded docs/Lessons, full gate/smoke/LSP, green draft `af68b54`, and clean independent reviews accounted for; no review fixes required. C03 closed: implementation, bounded docs/Lessons, full gate/smoke/LSP, green draft `5a9cc60`, and clean independent reviews accounted for; no review fixes required; closure commit `d5e6c1a` exists. C04 closed: implementation, bounded docs/Lessons, final gate/component and regression smoke, pre-fix Claude LSP evidence, green draft `e4e9798`, separately verified fix `42a4abf`, and clean independent rereviews accounted for; closure commit `6576e23` exists. C05 closed: implementation, bounded documentation, full gate/component smoke/Console LSP, green draft `98e0c6d`, and clean independent reviews accounted for; no review fixes required; closure commit `8e74532` exists. C06 closed: implementation, bounded docs/Lessons, final gate/component and regression smoke, pre-fix-only Grok LSP evidence, green draft `515b4f4`, separately verified fix `9df9232`, and clean independent rereviews accounted for; closure commit `6cf9386` exists. C07 closed for research/capability only: implementation, bounded docs/Lessons, full gate/blocked-capability smoke/base and ChatGPT LSP, green draft `9eae70a`, and clean independent reviews accounted for; no review fixes required; closure commit pending. C08 next after closure commit; actual ChatGPT weekly acceptance remains blocked |
| Live checks exercised | None; credentials unavailable |
| Upstream research blocker | Ordinary ChatGPT chat-model weekly remaining/usage contract |
| Next scheduling action | Commit C07 research/capability closure, then dispatch C08; C08…C14 remain sequentially gated by predecessor closure. Do not redispatch completed C07 work or repeat completed checks. Ordinary ChatGPT weekly acceptance remains blocked on read-only request/auth and authoritative model/weekly-window/reset semantics |

## 1. Scope and truthfulness matrix

Every configured account gets persistent rows for the requested metric IDs, including unavailable rows. Missing values are never zero. Rows show provenance, last successful fetch, last attempt/error, and private-contract warning where applicable.

| Stable metric ID | Meaning and supported display | Planned source | Current confidence/blocker |
|---|---|---|---|
| `claude.subscription.five_hour` | Used %, remaining %, server reset | Private Claude OAuth usage | Implementable; existing eligible Claude Code login required for live validation |
| `claude.subscription.weekly` | All-model weekly used/remaining %, reset | Same request | Implementable; no hardcoded absolute token/message quota |
| `claude.subscription.fable_weekly` | Model-scoped weekly used/remaining %, reset | Scoped `limits[]`, evidenced legacy fields | Implementable parser; depends on plan and response; not additive to weekly |
| `claude.platform.purchased_balance` | Sum of unexpired purchased grant remaining amounts, currency; grant expiries | Console session GET credits | Defensible private contract found; not blocked by lack of public API |
| `claude.platform.promotional_balance` | Sum of unexpired promotional grant remaining amounts; per-grant program and expiry | Same credits payload, `promo_tranches` | Defensible private contract found; do not show only the soonest grant as the category total |
| `claude.platform.total_balance` | Authoritative top-level total, independent of category sums | Same credits payload, `amount` | Additional reconciliation detail, not a replacement for either category |
| `chatgpt.subscription.weekly` | Actual ChatGPT chat-model weekly usage/remaining/reset, potentially per-model children | Unresolved private/public contract | **Open upstream blocker**; do not call WHAM/Codex to populate it |
| `grok.subscription.shared_pool` | Shared included used/remaining %, server period/reset | CLI-proxy credits, existing `grok login` credential | Implementable private read contract corroborated by official CLI source |
| `grok.product.build` | GrokBuild consumption share of shared pool | Same response `config.productUsage` | Private field; only show validated same-payload breakdown |
| `grok.product.chat` | GrokChat consumption share of shared pool | Same response | Private field; absence is unknown, not zero |

Grok Build/Chat remaining and reset refer to the **shared pool** when unified billing is positively established. Each product row explicitly says “剩余/重置：共享池” and references that pool, not an independent `100 - product share`. If a response cannot establish shared-pool semantics, do not attach an invented shared allowance; show the reported aggregate with “pool relationship unknown” and leave product remaining/reset unavailable. A weekly or monthly label follows the server period type, not the subscription's marketing name.

Out of scope: web UI/server, statusline, browser automation/cookie extraction, local message counting as remote quota, model inference requests, purchases/top-ups, token refresh protocols, scraping conversation contents, reset-coupon redemption, telemetry, Codex quotas, OpenAI/xAI API spend dashboards, Claude subscription extra-usage billing. Public cost reports may be cited as non-solutions but are not extra implementation work.

## 2. Chosen boring implementation

**Python 3.11+; `uv`; Textual + Rich; `httpx`; OS `keyring`; `pytest`, `pytest-asyncio`, and `respx` for tests.** Python supports this small read-only local tool without compiling an application framework. Textual supplies terminal rendering, masked inputs, responsive layout, and headless Pilot tests. Use standard-library dataclasses, enums, `Decimal`, `datetime`, `json`, `argparse`, and filesystem APIs instead of a schema/DI/plugin/database framework. `uv.lock` is committed once generated. Pin resolved versions in the lock, not guessed version numbers in this plan. Configure a `src/` layout and console entry point `usage = usage_tui.cli:main`.

One async process, one dashboard, a bounded fetch scheduler, immutable normalized snapshots, and explicit provider modules. No general-purpose endpoint configuration, dynamic provider loading, background daemon, SQLite, or server. POSIX/Linux is the initial fully supported target. Other OS credential locations must fail with explicit instructions unless implemented and tested; do not claim cross-platform credential import from a Linux-only implementation.

Required dependency groups: runtime `textual`, `httpx`, `keyring`; dev `pytest`, `pytest-asyncio`, `respx`, `ruff`. Use Ruff only, not a second formatter/linter. Package resource JSON for demo fixtures. Textual Pilot is a dependency of Textual, not a separate product.

### Planned source ownership

- `src/usage_tui/domain.py`: public value types, metric IDs, validation and serialization helpers.
- `src/usage_tui/storage.py`: nonsecret account/config persistence and secure credential backend.
- `src/usage_tui/credentials.py`: read-only first-party credential references and connection validation.
- `src/usage_tui/transport.py`: fixed-origin HTTP transport and safe response/error boundary.
- `src/usage_tui/providers/{base,claude,console,grok,chatgpt}.py`: normalized provider adapters, no UI imports.
- `src/usage_tui/scheduler.py`: polling, retries, cancellation, stale-state merge.
- `src/usage_tui/demo.py`, `src/usage_tui/fixtures/demo.json`: deterministic offline source.
- `src/usage_tui/app.py`, `src/usage_tui/accounts.py`, `src/usage_tui/app.tcss`: dashboard and account management.
- `src/usage_tui/cli.py`, `src/usage_tui/__main__.py`: thin CLI/TUI launch.
- `tests/`: focused contract, parser, scheduler, storage/security, CLI and TUI tests.

Directories may be created as needed; path lists in §8 are actual worker edit ownership limits, not permission to create arbitrary additional abstractions.

## 3. Exact internal contracts

### 3.1 Identity, values, results

`ProviderId` is one of `claude_subscription`, `claude_platform`, `chatgpt_subscription`, `grok_subscription`.

`Account` is a frozen dataclass with `id: str` (locally generated UUID), `provider: ProviderId`, `label: str`, `credential_ref: str | None`, `credential_kind: CredentialKind | None`, `credential_selector: str | None` (Grok scope/profile selector), `organization_id: str | None`, `poll_interval_seconds: int = 60` (validated 30…3600), `enabled: bool`. An account ID identifies a local connection, not an upstream user. Each snapshot carries `account_id` and the selected organization when applicable. Never share credentials between providers by display-name matching. Account changes cancel their generation of in-flight fetches before a new generation starts. A blocked ChatGPT profile may have no credential at all.

`CredentialKind`: `claude_code_file`, `grok_auth_file`, `console_session`, `manual_bearer`, `api_key`. Store import paths as local references, never copies of first-party refresh tokens. API keys can be managed locally but are **not** interchangeable with OAuth/session credentials and do not enable subscription/balance rows.

`Money` is `{minor: int, currency: str, exponent: int}`; no binary float arithmetic. USD is not assumed except the explicitly evidenced Console default below. Reject bools in numeric fields. Use exact same-currency/exponent addition, or report category unavailable. `QuotaValue` is `{used_percent: Decimal | None, remaining_percent: Decimal | None, used_count: int | None, limit_count: int | None, remaining_count: int | None}`; only set count fields from proven upstream quantities. Preserve raw nonnegative used % including >100; remaining is `max(0, 100 - used)` and visual bars clamp only their drawing. Percentages above 100 remain visibly numeric. Reject negative/nonfinite values.

C01 review security correction: percentage parsing accepts at most 4,096 input string characters, 1,024 Decimal coefficient digits, and a stored Decimal exponent in −1,000…+1,000 inclusive. Reject unsupported representations with `DomainError` before exponent-driven exact subtraction or formatting, including when loading serialized snapshots. A short scientific-notation string can otherwise request enormous arithmetic despite the JSON byte-size limit. Supported values retain exact nonnegative percentages, visible >100 overage, and exact `max(0, 100 - used)` remaining; these resource bounds do not introduce rounding or a 100% cap. Review-fix verification and independent rereviews passed as recorded in the ledger.

`Metric` contains `id`, `label`, `state`, `quota: QuotaValue | None`, `balance: Money | None`, `reset_at: aware UTC datetime | None`, `expires_at: aware UTC datetime | None`, `shared_pool_id: str | None`, `detail: str | None`, and `source: SourceRef`. Balance totals can have multiple grants; encode them as `Grant` detail values rather than falsely assigning one reset to a total. `Grant` contains category, optional upstream grant ID/program/name, granted money, remaining money, and optional expiry. Names are sanitized before rendering.

`MetricState`: `ready`, `unknown`, `not_applicable`, `blocked`. Absence alone means `unknown`; use `not_applicable` only with positive evidence of eligibility/plan exclusion. `blocked` means a known prerequisite/contract is missing. Fetch-level `FetchState`: `ok`, `partial`, `unconfigured`, `auth_required`, `permission_denied`, `rate_limited`, `network_error`, `provider_error`, `schema_error`, `upstream_contract_missing`.

`SourceRef` records `kind` (`private_http`, `offline_demo`, `unresolved`), a nonsecret contract identifier, and `version_sensitive: bool`. Do not persist raw response bodies or auth material as provenance.

`Snapshot` contains `account_id`, immutable `metrics: tuple[Metric, ...]`, `grants: tuple[Grant, ...]`, `fetch_state`, `fetched_at` (successful observation, optional), `attempted_at`, `retry_at` (optional), and `diagnostic: Diagnostic | None`. `Diagnostic` contains a fixed safe code and a curated actionable message, never interpolated response bodies/exceptions/credential paths. Clock and timestamp serialization use UTC RFC3339. Use a monotonic clock for deadlines; do not calculate next poll from wall-clock subtraction.

### 3.2 Interfaces (frozen before parallel worker units)

- `CredentialStore.put(account_id: str, secret: str, *, persist: bool) -> str`; `get(ref: str) -> str`; `delete(ref: str) -> None`. Memory references live only in the current process. Persisted references contain no secret.
- `AccountStore.load() -> tuple[Account, ...]`; `save(accounts: tuple[Account, ...]) -> None`; `mutate(change: Callable[[tuple[Account, ...]], tuple[Account, ...]]) -> tuple[Account, ...]`. Interactive CRUD uses `mutate`, which locks, rereads, applies the change, and writes atomically, avoiding a stale load/save race. Config schema version is `1`; invalid/unknown newer schema raises a safe config error and does not overwrite it.
- `CredentialResolver.resolve(account: Account) -> ResolvedCredential`. Frozen `ResolvedCredential` has `provider: ProviderId` (the account's explicit provider binding), `credential_kind: CredentialKind`, `secret` excluded from repr, optional `user_id`, optional `expires_at`, optional selected organization, and a nonsecret generation fingerprint. Resolver validates account/kind compatibility and preserves this binding on manual and imported credentials alike. Capture once per fetch; do not relabel an old result after credential replacement. Never use a token hash in public diagnostics.
- `Transport.get_json(provider: ProviderId, path: str, *, credential: ResolvedCredential) -> dict | list` is async. Provider-to-origin/header mapping is hardcoded (§4). Before constructing auth headers or opening a socket, reject a mismatched `credential.provider`, unsupported `credential.credential_kind`, or forbidden path/host. Allow Claude subscription `claude_code_file`/`manual_bearer`, Console only `console_session`, and Grok `grok_auth_file`/`manual_bearer`; API keys enable none of these reads, and unresolved ChatGPT never invokes transport. Its result is JSON only; adapters validate shape. Failures raise `TransportError` carrying only `fetch_state`, fixed safe `code`, optional HTTP `status`, and optional `retry_at`; no response body/credential/exception repr. Define this exception in `domain.py` so scheduler and providers need not import concrete transport internals.
- `Provider.fetch(account: Account, credential: ResolvedCredential | None, now: datetime) -> Snapshot` is async. HTTP adapters receive injected `Transport`; construction never makes a request. `Provider.metric_ids` enumerates all required rows. `Provider.requires_credential` is false only for the unresolved ChatGPT capability; scheduler publishes its blocked result without resolving or reading any saved secret. All live adapters require a resolved credential and validate its provider binding and kind; transport independently enforces both. The unresolved capability is not periodically polled.
- `build_providers(transport, resolver) -> Mapping[ProviderId, Provider]` is explicit construction in `providers/base.py`; no import-time clients, env probing, or secret reads.
- `Scheduler(accounts, providers, resolver, *, clock, rng, publish)` exposes async `start()`, `refresh(account_id: str | None = None)`, `update_accounts(accounts)`, `stop()`. `publish(snapshot)` runs on the app event loop. Injectable clock includes UTC time and monotonic sleep; tests use fake time.
- `DemoSource` implements the same published snapshot stream without resolver/transport/storage access. Offline mode must not instantiate the live network client.
- `UsageApp(*, mode, accounts, scheduler_factory, account_store, credential_store, scenario)` is dependency-injectable for tests. `cli.main(argv: Sequence[str] | None = None) -> int` performs argument handling, not provider logic.

Do not commit empty placeholder providers as “done.” Missing-contract ChatGPT is an explicit capability object returning the truthful blocked state (§4.4), not a fake network adapter.

## 4. Defensible provider wire contracts

All HTTP production requests are read-only GET, TLS verified, no redirects, `trust_env=False` (avoid implicit proxies/netrc), `Accept: application/json`, identifying `User-Agent: usage-tui/<installed-version>`. No configured base URL, credential-forwarding redirect, arbitrary cookie jar, HTTP downgrade, telemetry, or unrelated hosts. A custom host is available only through injected in-memory test transports, never user configuration. Avoid copying upstream tools' browser import, insecure cookie config, inferred quotas, or telemetry behavior.

### 4.1 Claude subscription

Fixed origin `https://api.anthropic.com`; exact path `/api/oauth/usage`; `Authorization: Bearer <access token>` and `anthropic-beta: oauth-2025-04-20`.

Connection: user first signs in through official Claude Code (`claude` then `/login`). On Linux resolve `$CLAUDE_CONFIG_DIR/.credentials.json` or `~/.claude/.credentials.json`; parse the `claudeAiOauth.accessToken` entry with optional `expiresAt` milliseconds and `scopes`. This concrete file shape must have a sanitized fixture and a schema-error path. A user-selected local credential-file reference supports separate first-party profiles; it does not run shell commands. Do not modify/refresh Claude files. If expired, prompt to rerun first-party login. If scopes exist and exclude `user:profile`, return permission guidance; still handle server 403 when scope information is absent. Do not recommend `claude setup-token` as a usage-read token; inference-only tokens commonly lack profile scope. Manual Bearer is an explicit masked alternative; API keys are not accepted for this adapter.

Parse `five_hour` and `seven_day`: `utilization`, otherwise `used_percentage`, with optional `resets_at`. Prefer finite scoped Fable `limits[]` entry where `kind == "weekly_scoped"` and `scope.model.display_name.strip().casefold() == "fable"`; use `percent` and `resets_at` regardless of `is_active: false`. Fallback in order: `fable_weekly`, `fable_seven_day`, `seven_day_fable`. Do not relabel Opus/Sonnet fields as Fable. Reject conflicting duplicate valid Fable scoped entries rather than selecting arbitrarily. Equal-percent duplicates with an invalid reset must retain the quota, leave reset unknown, and flag partial; malformed reset metadata alone is not a quota conflict. This review finding is resolved by separately verified fix `42a4abf` with clean independent rereviews.

Timestamp contract: RFC3339 strings require timezone. Numeric Claude resets accept positive Unix seconds; values >= 10^11 are milliseconds only in this adapter's explicitly tested normalization. Invalid reset does not discard a valid percentage; leave reset unknown and flag partial. A missing/invalid window remains visible and unknown while valid sibling windows survive. A wholly malformed root or no recognizable window yields schema-error/partial as appropriate, never successful empty bars. Do not infer Fable eligibility or a fixed half-week allowance from absence.

### 4.2 Claude Platform purchased and promotional balance

**A usable private Console contract was found; lack of a public Admin endpoint is not an implementation blocker.** Use a manually supplied `sessionKey` cookie value, stored through the secure credential backend. Do not accept passwords or extract browser stores. User signs into `https://platform.claude.com` outside this application and copies only `sessionKey` from their own session when needed. The app gives an explicit high-sensitivity session warning before accepting it.

Fixed origin `https://platform.claude.com`; requests send only `Cookie: sessionKey=<value>`. Reject CR/LF, semicolon and invalid cookie-value controls; do not paste a full HAR, browser request, or arbitrary Cookie header.

1. `GET /api/organizations`: JSON array. Candidate records have `uuid: str`, optional `name`, and `capabilities: list` containing exact `"api"`. Validate organization IDs against `^[A-Za-z0-9-]{1,64}$` before path interpolation. The account connection screen offers explicit organization selection; never silently switch the account to another readable organization. If a stored ID is no longer present, show a selection-required/permission diagnostic. A discovery request with a single candidate may propose it, but save it only with user confirmation.
2. `GET /api/organizations/{organization_id}/prepaid/credits`: root has integer `amount` in minor units, optional `currency` (evidenced default `USD`), optional `balance.credits.exponent` (integer 0…4, evidenced default 2), optional `tranches` and `promo_tranches` arrays.
3. Each grant has `granted_amount_minor_units: int`, `remaining_amount_minor_units: int`, optional `expires_at` RFC3339, optional `name`, optional `program_id`. `tranches` means purchased; `promo_tranches` means promotional. `program_id == "subscription_api_credit"` annotates included subscription-origin API credits; it does not change category or turn them into Claude subscription windows.

Compute each category total from **all** unexpired grants in its corresponding complete validated array, not the soonest-expiring tranche. Keep zero-valued grants and expose grant amounts/expiry in details. Explicit empty array means category zero; missing/null array means category unknown, not zero. Negative balances remain visible if the upstream explicitly reports them; do not silently clamp money. Invalid grant numeric fields make that category unavailable, retaining the authoritative total and any independently valid category. Unknown/unparseable expiry means expiry unknown; include in the reported total with an uncertainty note rather than claiming it is unexpired. Expired grants are excluded from active category totals. Preserve total `amount` independently: if sums disagree, show “category totals do not reconcile” and the discrepancy, not subtraction to manufacture missing promotional or purchased values. No common currency/exponent means no sum.

Credits expire; they do not “reset weekly.” Show nearest expiry plus expandable per-grant expiries, never a fabricated renewal. Do not call `/current_spend` or Admin reporting just to fill a balance gap. HTTP 401 or organization-list 403 means reconnect; selected-org credits 403 means billing permission denied. Session credential never goes to api.anthropic.com or claude.ai.

### 4.3 Grok shared pool, Build, and Chat

Prefer a direct implementation of the **official CLI's existing read-only billing request**, not spawning a potentially updating/telemetry-enabled agent process. Fixed origin `https://cli-chat-proxy.grok.com`; exact path `/v1/billing?format=credits`; headers `Authorization: Bearer <key>`, `x-xai-token-auth: xai-grok-cli`, `Accept: application/json`. The official source also supplies `x-userid`, `x-grok-client-version`, and client-mode headers; include `x-userid` only from the same resolved credential. Do not invent a version or impersonate an unsupported client. Begin with the independently evidenced minimal bearer/token-auth request; a live rejection demanding additional headers is a compatibility blocker requiring sourced adjustment, not guessed spoofing.

Connection: official `grok login` runs outside this app. Read `$GROK_HOME/auth.json` or `~/.grok/auth.json`; top-level keys identify scopes. Prefer the selected `https://auth.x.ai::<client-id>` entry, fallback to `https://accounts.x.ai/sign-in` only if no ambiguity. Entry contains `key`, `expires_at`, `user_id`, `team_id`, `auth_mode`, and optional `principal_type`. Expiry parser accepts timezone-aware RFC3339 and explicitly tested Unix seconds/milliseconds; unknown expiry is not asserted fresh. Multiple matching identities require user selection stored as a nonsecret scope selector; do not accidentally choose another account. Never copy `refresh_token` into app storage or refresh it. Manual bearer is supported with unknown identity until configured; API/management keys beginning `xai-` are rejected for subscription use. Team principal unsupported responses are actionable, not retried under an unrelated personal account.

Parse root `config` object, optional `subscriptionTier`/`subscription_tier` metadata; `config.creditUsagePercent` finite nonnegative means shared included usage only when semantics establish unified billing. `config.isUnifiedBillingUser == true` positively establishes that relationship. `currentPeriod` contains optional `type`, RFC3339 `start`, `end`. Known type `USAGE_PERIOD_TYPE_WEEKLY` labels weekly; monthly labels monthly. Reset is `currentPeriod.end`, fallback to `billingPeriodEnd` only when current-period end is absent. Reject reversed bounds; unknown type remains “period.” Do not derive included quota from `onDemandUsed / onDemandCap`, because on-demand spend is not included subscription usage. Missing `creditUsagePercent` remains unknown even with a period or prepaid wallet. No implicit zero inference, legacy estimated cap, gRPC/browser fallback, or optional reset-coupon lookup in this scope.

`config.productUsage` is an observed private array of `{product: "GrokBuild" | "GrokChat" | other_string, usagePercent: number}`. Preserve all products for reconciliation. Validate whole array (no duplicates, finite nonnegative values, no malformed entries); require a wire-provided aggregate from the **same** payload and shares summing to aggregate within 1 percentage point to show the breakdown. Unknown products appear under their sanitized ID, so other consumers do not disappear. Explicit Build/Chat zero entries display zero; an absent entry remains unknown. Missing/inconsistent breakdown does not discard a valid aggregate. Product shares are consumed percentages of the common pool, not separate remaining percentages. Approved C06 representation keeps product consumption in detail only, not `QuotaValue`, whose automatic `100 - used` remaining would invent an independent product allowance. Proven shared semantics use `shared_pool_id` and detail to refer to shared remaining/reset rather than copying independent product quota/reset fields. If unified semantics are unproven, show breakdown consumption as reported but product remaining/reset unavailable. No cross-account enrichment or blending values from different requests.

C06 review precision requirement: HTTP JSON decimal numeric tokens must decode directly to `Decimal`, before provider parsing or reconciliation; converting a binary float back to a string/Decimal cannot restore wire precision. Raw numeric aggregate `42.5`, Build `43.500000000000000000000000000001`, and Chat `0` are outside the one-point tolerance and must not expose a READY product breakdown. Boundary tests must cover actual raw JSON numbers through Transport and GrokProvider, not only string-valued percentages.

Official ACP evidence for troubleshooting/future contract repair: `grok agent stdio` uses newline-delimited JSON-RPC 2.0; `initialize` params are `{"protocolVersion":"1","clientCapabilities":{"fs":{"readTextFile":false,"writeTextFile":false},"terminal":false}}`, then `_x.ai/billing` with no params. Current typed CLI responses can drop `productUsage`; therefore ACP is **not** silently substituted for the direct JSON path and does not satisfy Build/Chat acceptance. No subprocess adapter is required for this plan.

### 4.4 Ordinary ChatGPT weekly quota — explicit unresolved capability

Keep provider ID `chatgpt_subscription` and required weekly row. `chatgpt.py` returns a structured `upstream_contract_missing` result with `SourceRef(kind="unresolved")`, safe Chinese/English explanation, and no network request. Account manager allows a local labeled ChatGPT connection profile and locally stored optional user-provided bearer/API key, but explicitly says storage **does not enable weekly quota retrieval**. It must not solicit a sensitive cookie as though there were a working integration. No ChatGPT password collection or invented third-party OAuth client.

A dedicated research unit in C07 must investigate ordinary ChatGPT model limits using public source/static artifacts without browsers or credentials. Existing evidence includes `/backend-api/conversation/init` feature `limits_progress[]` (`feature_name`, `remaining`, `reset_after`) but does **not** establish ordinary GPT chat weekly usage, cap, or an appropriate read-only request. Do not call this POST merely to test whether it initializes conversations. An implementable new adapter requires a defensible read-only request/auth contract, model/window semantics, sanitized schema examples, reset interpretation, and provenance distinguishing ordinary chat from Work/agent/Codex. If found, amend this plan and add a small sequential implementation chunk before C10. If not found, record exact missing contract; leave live/metric acceptance open while completing all other reachable code.

`GET https://chatgpt.com/backend-api/wham/usage` and Codex OAuth are evidence for Codex/Work allowances, **not proof** of ordinary ChatGPT chat weekly usage. Do not include WHAM as a convenience fallback. OpenAI API organization usage is API consumption, not ChatGPT allowance. Local user-configured caps or browser message counters are not an acceptable remote quota replacement.

C07-A static revisit (2026-10-28): the inspected leads still do not establish an implementable ordinary-chat weekly contract; §7 records their exact limitations. A community script's `GET /backend-api/conversation/init` is a new request-method lead, not proof that GET succeeds, is side-effect-free, or exposes ordinary model weekly allowance. Neither its feature counters nor the POST variant may be promoted into this adapter. Preserve every named metric and the required weekly row; research/capability work does not complete ordinary ChatGPT metric acceptance.

## 5. Local security, accounts, and key management

Connection and key operations are available from the TUI (`a`) and matching CLI prompts. Provide add, list, select/edit label, enable/disable, replace secret/reference, choose organization/scope, reconnect guidance, and remove. Removing an account deletes only this tool's secret/config and cancels its work; never delete external Claude/Grok login files or claim remote session revocation. Confirm removal and key replacement. A credential can be changed without revealing its old value.

CLI surface:

```
usage                         # live dashboard; empty state offers account manager
usage --demo                  # no account/files/network, deterministic healthy scenario
usage --demo --scenario errors # deterministic error/partial/stale scenario
usage accounts list
usage accounts add --provider claude-subscription
usage accounts add --provider claude-platform
usage accounts add --provider chatgpt-subscription
usage accounts add --provider grok-subscription
usage accounts edit ACCOUNT_ID
usage accounts remove ACCOUNT_ID
usage accounts key set ACCOUNT_ID
usage accounts key delete ACCOUNT_ID
```

Provider CLI spellings map explicitly to underscore internal IDs. `add` asks for supported source kind; `key set` asks credential type and warns when it is only local API-key storage. Never accept `--token`, `--cookie`, `--api-key`, secrets in positional arguments, or secret-bearing environment variables as a documented feature. Use `getpass` outside the TUI and Textual `Input(password=True)` inside it. Secret form has no reveal/copy button, no history, no prefilled saved value; clear inputs on submit/cancel; do not log paste contents. Reject secret input without a TTY. Ctrl-C/Escape cancels without writing partial state. Sanitize labels/provider text to remove terminal control sequences, newlines, and markup injection; length-bound all display values.

Default persistence: OS keyring backend with actual encrypted OS store (Secret Service on supported Linux). Reject null/fail/plaintext backends; do not install or silently select `keyrings.alt`. Credential strings never enter account JSON. If secure keyring is unavailable/locked, offer explicit **session-only** mode from the TUI; CLI persistent `accounts key set` fails with actionable guidance rather than pretending memory survives exit. Do not invent home-grown encryption or a plaintext fallback. Python cannot promise memory zeroization; document this honestly. Session-only secrets are discarded on exit but remain subject to process-memory risk.

Config path: `$XDG_CONFIG_HOME/usage-tui/accounts.json` (fallback `~/.config/usage-tui/accounts.json`). Create private parent directory `0700`; atomic same-directory config replacement with `0600`; reject symlink config targets and unsafe ownership/modes on credential import before reading on POSIX. Imported first-party credential paths must be regular, user-owned, not group/world-readable; report permission instructions rather than chmod or mutate them. Max credential/config file size 1 MiB. App stores no secret or raw-response cache; snapshots are memory-only. A config load error does not overwrite existing data. Account changes are serialized in one process; do not claim safe concurrent config writers without a lock. Implement a standard-library POSIX advisory lock for config mutations and reread under lock to prevent lost updates.

HTTP credentials are limited to their exact origins (§4). Disable redirects, netrc, implicit proxy env, and cookie persistence. Never send an API key for an OAuth source or a Console cookie to another Anthropic service. No browser imports, analytics, crash-report uploads, endpoint override, or raw HTTP debug flag. Logs contain safe codes and local opaque account IDs only; logging is off by default. UI shows “stored securely,” “session only,” or “external credential reference,” not a token suffix. Diagnostics cannot interpolate upstream body strings, URLs with query credentials, arbitrary exception repr, or local identity data.

## 6. Polling, freshness, and terminal behavior

Assumption/rationale: “near real time” means bounded periodic observation, **not** a promised provider push/SLA. Default interval 60 seconds with ±10% jitter; configurable local integer interval 30…3600 seconds, never below 30. One fetch per account at a time, max two accounts fetching concurrently, and an origin-level minimum request start spacing of five seconds. Console discovery happens only on connection/organization reselection, not every poll. No duplicate request per metric. HTTP connect timeout 5s, overall read/request deadline 10s, max JSON body 1 MiB streamed with bounds. Shutdown cancels work and closes clients.

Fetch immediately after connection/start; `r` coalesces refresh requests, respects in-flight work, origin spacing, and retry deadlines. Never launch overlapping requests because of a countdown tick or repeated keypress. A local one-second UI tick updates countdowns without network traffic. Authentication/permission failures suspend that account until credential/config replacement or explicit reconnect action; reconnect can retry once but does not bypass service rate-limit deadlines. Schema errors back off without inventing data. 429 honors valid `Retry-After` seconds or HTTP date (at least 60s); never cap a longer server deadline downwards. Without a valid header use exponential 60s, 120s, 240s … capped at 15 minutes plus bounded jitter. Network/5xx/schema errors use the same exponential schedule; a successful compatible fetch resets it. A malformed retry header is a safe default, not an exception.

Snapshots preserve last good metric values across fetch errors, clearly marked “last known” with the new error and observation age. A fresh response that explicitly omits a metric makes the current metric unknown; do not indefinitely carry old Fable/product data into a successful new response. Old values may appear only in a distinct last-known detail, not as current. Mark stale once successful observation age exceeds `max(2 * poll_interval, 120s)` or its known reset has passed without a new observation. Countdown reaching zero does not reset usage to zero or fabricate the next period; say “awaiting refresh.” Show attempted-at separately from success time so failed polling never looks fresh. Raw metric state and stale status are orthogonal.

TUI main view: Chinese labels by default with provider/model names intact; optional plain symbols when Unicode unavailable. Header shows LIVE vs unmistakable DEMO, account selection, freshness and pending/retry status. Dashboard shows all requested rows grouped by provider/account; viewport scrolls at 80×24 and smaller terminals show a resize/scroll hint rather than crashing. Display numeric used/remaining alongside bar, absolute reset in local timezone plus UTC detail, countdown, unknown `—` with reason, and balances with currency. Never hide errors behind color alone. A details screen exposes contract provenance, grant breakdown, shared-pool explanation, and safe reconnection steps. `q`/Ctrl-C exit, `r` refresh, `a` account manager, `Tab`/arrows navigate, `Enter` details, `Esc` back, `?` help. Modal focus must not leak secret keystrokes into dashboard actions. Restore cursor, echo, and terminal modes on normal exit, cancellation, and application exceptions.

Offline demo uses a fixed `now` (for example `2026-10-28T12:00:00Z`), fictional account IDs, deterministic snapshots, and no secrets. Countdown ticks are deterministic from an injected demo clock; test assertions never depend on the machine date. Healthy scenario includes all requested rows, but the ChatGPT sample is explicitly **synthetic demonstration, not evidence of working live support**. Errors scenario includes auth required, permission denied, rate limit/retry, network failure, malformed/partial data, unknown Fable, missing product breakdown, and stale last-known values. Demo must not read config/keyring/first-party files or construct a live transport; tests enforce this.

## 7. Research sources, strength, and unresolved prerequisites

Research from `agent://initial-context-1`, `agent://initial-context-2`, and `agent://initial-context-3` was read in full. They are ephemeral context; the durable findings and URLs below supersede reliance on their availability. No source was authenticated against a real account. Community parsers are wire evidence, not an official API guarantee. Recheck exact source revisions if they drift before implementation.

### Claude semantics and authentication (official)

- Subscription usage windows and shared allowances: https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work
- Claude Code usage/cost and rate-limit stale bars: https://code.claude.com/docs/en/costs
- Fable plan behavior: https://support.claude.com/en/articles/15424964-claude-fable-models-on-your-plan — scoped weekly subset, plan/seat dependent, not extra capacity. Do not hardcode a promotion or threshold from this prose.
- First-party auth locations/login: https://code.claude.com/docs/en/iam
- Official statusline data is not the requested architecture: https://code.claude.com/docs/en/statusline.md#available-data
- Profile-scope failure evidence: https://github.com/anthropics/claude-code/issues/13724 ; inference-only setup-token evidence: https://github.com/anthropics/claude-code/issues/81015

### Claude private usage (community wire evidence)

- Undocumented OAuth route: https://github.com/eyalev/cc-usage-json
- Concrete scoped Fable parser read during planning: https://github.com/stablyai/orca/blob/main/src/main/rate-limits/claude-oauth-usage-request.ts
- Scoped-limit introduction/fix: https://github.com/stablyai/orca/pull/8323 ; inactive-but-valid scoped meter: https://github.com/stablyai/orca/pull/9389

### Console balances — newly resolved implementation route

- Source tree inspected at immutable revision `28e89cc6ae35484e0b5a35c6980cc737464f45da`:
  https://github.com/o1xhack/CodexBar-Mobile/blob/28e89cc6ae35484e0b5a35c6980cc737464f45da/Sources/CodexBarCore/Resources/Plugins/claudeplatform.ts
- Corresponding provider/auth documentation: https://github.com/o1xhack/CodexBar-Mobile/blob/mobile-dev/docs/claudeplatform.md
- Independent older collector corroborates credits route and sessionKey auth: https://github.com/AdrianNarloch/xbar-anthropic-credits-balance
- Purchased credit semantics: https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage
- Promotional/included API credit semantics: https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers
- Official Admin usage/cost are consumption, **not balance**: https://platform.claude.com/docs/en/manage-claude/usage-cost-api ; https://platform.claude.com/docs/en/manage-claude/admin-api

The Console source explicitly supplies `amount`, `balance.credits.exponent`, `promo_tranches`, `tranches`, and grant minor-unit fields. This removes the earlier “no confirmed balance endpoint” research gap. The plan intentionally differs from the source UI by aggregating **all** category grants and storing session cookies only securely, not in a plaintext config.

### ChatGPT — unsupported inference explicitly excluded

- Official model-cap help: https://help.openai.com/en/articles/20001354-gpt-6-and-other-models-in-chatgpt
- API vs subscription distinction: https://help.openai.com/en/articles/8156019-how-can-i-move-my-chatgpt-subscription-to-the-api
- Codex backend source: https://github.com/openai/codex/blob/main/codex-rs/backend-client/src/client.rs
- Unofficial WHAM schema: https://gist.github.com/monperrus/21dc7d85ea518dc2a66606006d356b5b — **not accepted as ordinary chat quota evidence**.
- Additional private-surface lead read during planning: https://github.com/SelectorsHub/ChatGPT-Usage-Meter — README distinguishes Work/Codex windows from plain chat, describes conversation-init feature limits and optional local model counters; neither establishes the requested remote weekly metric. Do not copy its custom-cap counter or browser relay into this TUI.

#### C07-A static exhausted-leads record (2026-10-28)

This records the inspected leads, not proof that no private contract exists. Only public static documents/source were fetched; no browser, credentials, authenticated provider endpoint, conversation-init request, or verification command was used.

- **Pinned meter source:** [README](https://github.com/SelectorsHub/ChatGPT-Usage-Meter/blob/e59a8c5d2a364f522160190167fb4c1c70e0a438/README.md) and [background.js](https://github.com/SelectorsHub/ChatGPT-Usage-Meter/blob/e59a8c5d2a364f522160190167fb4c1c70e0a438/background.js). Its auth is cookie-backed `GET /api/auth/session`, then session `accessToken` as bearer, cookies included, optional `chatgpt-account-id` from the selected account. This describes that extension, not a proven standalone ordinary-weekly auth contract or support for API keys. The README explicitly scopes WHAM windows to Codex/agent/Work and its model caps to local browser counts. `parseUsage` says paid-plan `model_usage` shape is unknown; accepting window-shaped objects is parser speculation, not ordinary-chat evidence.
- **Conversation-init POST:** the meter sends `{gizmo_id: null, requested_default_model: null, conversation_id: null, timezone_offset_min: ...}`. Its `parseFeatures` reads `feature_name`, `remaining`, optional `max_value`/`limit`, and `reset_after`/aliases; name mappings such as `reason` → Thinking do not prove those features occur or represent a weekly chat model. [pi-gpt 0.4.3](https://cdn.jsdelivr.net/npm/pi-gpt@0.4.3/extensions/chatgpt.ts) instead posts `{conversation_mode_kind: "primary_assistant"}` and selects only `deep_research`. [gpt2api notes](https://github.com/aisuyi065/gpt2api/blob/main/API_NOTES.md) (dated 2026-04-17; identical laowang74152 fork also read) show `model_limits: []`, `default_model_slug`, and deep-research/agent/upload/image feature counters with an image UTC timestamp. They describe pre-conversation registration. Their claim that quota is not consumed does not establish no conversation-side effects; no POST was sent. Feature remaining counts, a default model, and an empty model-limit array cannot establish ordinary model weekly used/cap/remaining.
- **New GET/init and model-limit lead:** [Account + Models + Limits Info Panel Plus v1.7.0 source](https://greasyfork.org/en/scripts/578434-chatgpt-account-models-limits-info-panel-plus/code) calls `fetchJson('/backend-api/conversation/init')` with GET and same-origin cookies. It only displays `model_limits.length`, plus `deep_research` and `odyssey` feature counters, interpreting `reset_after` as an ISO date. There is no ordinary-model response example, successful-GET evidence, weekly period, cap/usage mapping, or no-side-effect guarantee. It conflicts with the better-described POST callers, so GET is not adopted merely because a script attempts it. `/backend-api/models` in this script and pi-gpt supplies model availability/context/effort metadata, not a demonstrated account-specific weekly quota.
- **Work/Codex exclusion reinforced:** [official pricing](https://learn.chatgpt.com/docs/pricing) explicitly says Work and Codex share usage and links its usage dashboard to `/codex/settings/usage`; API-token pricing is separate. [official Codex client](https://github.com/openai/codex/blob/main/codex-rs/backend-client/src/client.rs) labels its primary parsed snapshot `codex`. Neither establishes ordinary Chat quota. The existing unofficial WHAM reference remains excluded; no fallback is justified.
- **Other searches and fetch limitations:** searches for ordinary weekly `backend-api`, `limits_progress`, `model_limits`, and GET/init returned the above feature/Codex/local-counter leads, API rate limits, and [chatgpt-cli's dated API inventory](https://github.com/planetaryescape/chatgpt-cli/blob/main/docs/explanation/chatgpt-api.md), which has no weekly-quota contract. The linked robotlearning123 deep-research quota script returned 404 through raw and GitHub URLs. The §7 official GPT-6 help article and search-discovered model article `11909943`/Work usage article `20001478` returned HTTP 403 through static reads; their bodies/current plan caps were not verified, and no browser/bypass was attempted. Do not turn inaccessible help or the meter's “plain chat” claim into a global assertion that ordinary weekly caps do not exist.

**Exact missing prerequisite:** a public first-party contract or attributable, sanitized first-party wire/source example identifying an ordinary Chat model/plan/workspace and a side-effect-free read request (fixed origin/path/method, necessary headers and credential type/scope), with actual ordinary-model weekly fields: authoritative used and/or remaining plus cap/unit or authoritative utilization, which models share the allowance, explicit weekly-window boundaries/rolling-vs-anchored semantics, reset timestamp type/timezone (or relative duration and reference instant), and absent/unlimited/exhausted behavior. `reset_after` is treated as an absolute date by the inspected feature callers despite its name; that is not evidence of ordinary-chat reset semantics. A credential alone, a static advertised cap, feature-name guess, local count, or Codex response does not supply this prerequisite. C07-C is not justified by the inspected evidence; ordinary ChatGPT weekly remains in scope and blocked, not complete.

### Grok — official CLI plus private product fields

- Product/shared-pool semantics: https://docs.x.ai/x-subscription/usage-limits ; https://docs.x.ai/x-subscription/overview ; https://docs.x.ai/grok/faq
- Official CLI read contract and typed fields inspected at immutable revision:
  https://github.com/xai-org/grok-build/blob/b189869b7755d2b482969acf6c92da3ecfeffd36/crates/codegen/xai-grok-shell/src/extensions/billing.rs
- Private direct JSON, auth-file, productUsage validation and ACP details read during planning: https://github.com/steipete/CodexBar/blob/main/docs/grok.md
- Do not confuse API consumption with the subscription: https://docs.x.ai/console/usage ; https://docs.x.ai/developers/cost-tracking

The official CLI includes `creditUsagePercent`, `currentPeriod`, `isUnifiedBillingUser`, and sends billing reads to the proxy. Its typed config omits productUsage, while the community direct-response parser documents GrokBuild/GrokChat shares. Direct proxy implementation preserves that field and avoids a lossy ACP result. Browser WKE-dependent gRPC is unnecessary and excluded.

### Prerequisites and live-auth blockers

1. Claude: eligible signed-in first-party account with usable `user:profile` credential; Fable may be absent for the actual plan. Parser code does not require credentials, but successful live acceptance does.
2. Console: user's own platform sessionKey and selected organization with billing-read rights; purchased/promotional grants must exist or explicit empty arrays must confirm zero categories. Live response may change the private schema.
3. Grok: signed-in first-party `grok login` auth file or manually supplied bearer; direct proxy may require header/permission changes. Need an account with unified billing and Build/Chat shares to validate all requested semantics.
4. ChatGPT: ordinary-chat read request/auth and model-specific weekly schema/window/reset semantics remain unestablished after the C07-A static revisit above. Need the attributable sanitized contract/example specified there, separately from a later eligible live credential and UI comparison. A future live session alone does not prove WHAM is the right metric.
5. OS secure keyring may not be available on a headless Linux host. Session-only mode remains implementable; do not claim persistent key storage passed until exercised against a suitable backend.

## 8. Sequential, committable work chunks

Every chunk is a bounded reviewable change. **The orchestrator commits the approved plan before C01** using `docs(plan): record reviewed usage implementation plan`; that prerequisite is recorded above and must not be repeated. Run C01–C14 sequentially, releasing dependents only after the preceding chunk closes. Within a chunk, independent units may run concurrently only after shared interfaces land; listed paths are maximum ownership for each assignment (normally 3–5, or fewer for a narrow follow-on). No implementation worker runs build/tests/lint/format/smoke/gates or commits; workers write tests and exact component-smoke snippets, not verification claims. The C01 lock owner alone may run initial `uv lock`; a later dependency owner may resolve a necessary lock update. Worker prompts include no-browser/no-secret-exfiltration constraints. The orchestrator schedules implementation fixes rather than coding them itself.

Each chunk's mandatory lifecycle is: implementation units land → explicitly bounded documentation follow-on lands → orchestrator runs cumulative available checks and actual component smoke (§10) → resolve failures through bounded owner assignments and recheck → green Conventional Commit draft (`feat(domain): draft C01 domain contract`, or appropriate `fix`/`docs`/`chore` type and scope) → independent review → bounded fixes → orchestrator verifies each fix before a separate Conventional Commit (`fix(domain): address C01 review findings`) → close only after review is resolved, docs/changelog/Lessons and evidence are current, and all owned changes are committed with no unaccounted chunk changes. Failed checks block draft commits and dependent work. Preserve and account for unrelated user changes; never discard them to obtain a clean close. Every Exit below includes this lifecycle, not just the behavior described there. C14 is an additional final gate, not the first verification.

A worker assignment must contain: chunk/unit ID, exact owned paths, referenced contract sections, required changes/tests, exclusions, and return fields `{changed_paths, acceptance_evidence, component_smoke_snippet, blockers, checks_not_run, reusable_observations}`. Smoke snippets name the real components, concrete assertions, exact invocation, bounded waits and cleanup; workers do not execute them. Shared paths have one owner. An extra path requires an explicit bounded follow-on, never implicit permission. The orchestrator owns PLAN bookkeeping separately.

**Documentation follow-on D(Cxx), before each chunk gate:** assign one owner exactly `README.md`, `CHANGELOG.md`, `SECURITY.md`, and repo-root `AGENTS.md`, limited to that chunk's delivered behavior/security implications and reusable observed Lessons. Create these files when first needed in C01; document only existing functionality, not future CLI commands as runnable. Add/update `AGENTS.md`'s `Lessons` section for actionable observed lessons, or return “no new lesson” without inventing one. Do not create `LESSONS.md`. Relevant sections may intentionally remain unchanged with a reason. This separate task is not extra ownership for the implementation worker; C13 reconciles, rather than first supplies, these artifacts.

**Review disposition:** accepted both reviewers' credential boundary, per-chunk verification, planning/commit lifecycle, documentation accounting, initial-lock and orchestrator-owned final-gate findings. Adapted reviewer 2's Lessons proposal to repo-root `AGENTS.md` per the user requirement. Discarded the proposed permanent `scripts/chunk_smoke.py` framework and blanket C10/C11/C12 splits: exact throwaway component snippets, a real temporary PTY host from C10, and the production PTY harness in C12 provide independently exercised invariants without a second maintained dispatch framework or speculative chunks. Keep C01–C14; bounded internal follow-ons for lock, docs, and the C12 harness have explicit ownership. Split only if an actual dependency/size finding warrants a sourced plan amendment, not preemptively.

### [x] C01 — package and frozen domain contract

Two sequential bounded assignments:

- **C01-A package/domain**, owned paths: `pyproject.toml`, `src/usage_tui/__init__.py`, `src/usage_tui/domain.py`, `tests/test_domain.py`, `.gitignore`. Implement §2/§3 types, metric constants, finite numeric/timestamp helpers, schema serialization, dependency/entry-point/dev group declarations. `.gitignore` excludes venvs/caches/builds/local secrets and smoke transcripts without hiding source fixtures. Tests cover bool-as-number, >100%, partial values, money arithmetic and aware timestamps. Do not add a fake CLI/provider. Return an exact throwaway library smoke snippet; do not invoke the future `usage` entry point.
- **C01-B initial lock**, owned path: `uv.lock`, after C01-A metadata lands. Run `uv lock` for dependency resolution only; return the exact command/outcome and lock path. No installation, tests, lint, formatting, application launch, or commits. If metadata must change, request a bounded C01-A owner fix first.

Then D(C01) owns only the four documentation paths above. Exit: domain signatures and IDs match the plan, initial lock exists, and the orchestrator installs the locked environment and exercises domain round-trip/validation smoke before draft/review/closure. Suggested draft subject: `feat(domain): draft C01 package and frozen contracts`.

Closed: final gates and actual domain smoke passed, both independent rereviews were clean, separate review-fix commit `650a8a5` is recorded in the ledger, and closure commit `2347f1f` exists. C02 closure commit `2ab03fb` also exists; C03 closure is recorded below.

### [x] C02 — local account config and secure key management

One worker; target paths: `src/usage_tui/storage.py`, `tests/test_storage.py`, `tests/test_secret_store.py`.

Implement AccountStore/CredentialStore, locking/atomic private config, secure-backend validation, session-only references, CRUD and cancellation-safe mutation. Tests inject fake encrypted/insecure/locked backends, malformed/newer config, permissions, symlinks, atomic write failure, and concurrent mutation lock behavior. Never contact a real keyring in tests.

Exit: no serialized secret, no insecure automatic persistence fallback, no external credential mutation.

Closed: C02 implementation and bounded documentation/Lessons landed in green draft `af68b54`. The orchestrator's full green gate passed: `uv run pytest -q`: 167 passed in 0.55s; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: 11 files already formatted; storage LSP diagnostics OK. Actual `uv run --locked python -c` storage/session smoke passed private temporary config directory/file modes `0700`/`0600`, AccountStore save/reload/mutate/delete, no serialized synthetic secret, and session-only CredentialStore put/get/delete without contacting a real keyring. Independent reviews `agent://c02-review-1` and `agent://c02-review-2` were clean; no review fixes, separate fix commit, or fix verification required. Closure commit `2ab03fb` exists. Persistent OS-keyring/live acceptance remains unexercised and open.

### [x] C03 — transport and credential resolution

Both independent worker units landed after C02 closure commit `2ab03fb`; their ownership and implementation contracts are preserved below:

- **C03-A**, owned paths: `src/usage_tui/transport.py`, `tests/test_transport.py`, `tests/test_security.py`. Implement §4 fixed origins/path guards/auth-header mapping, streaming response bound, deadlines, no redirects/proxy inheritance, structured safe failures and Retry-After parsing. Test allowlisted origins/paths, attempted redirect exfiltration, credentials in exception bodies, cross-provider credential rejection, oversized/error/non-JSON bodies.
- **C03-B**, owned paths: `src/usage_tui/credentials.py`, `tests/test_credentials.py`, `tests/fixtures/credentials.json`. Implement read-only first-party reference resolution, profile selection, import permission checks, expiry/scope parsing and manual-secret references. Fixture is synthetic and clearly labeled. No actual home-directory reads in tests.

Exit: exact Transport and Resolver interfaces in §3 available; source credentials captured once per attempt. Integrator resolves only true interface discrepancies through a worker, not ad hoc rewrites.

Closed: C03 implementation and bounded documentation/Lessons landed in green draft `5a9cc60`. Orchestrator full green gate passed: `uv run pytest -q`: 345 passed in 0.80s; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: 16 files already formatted; credentials/transport LSP diagnostics OK. Actual read-only component smoke passed private synthetic Claude credential resolution followed by real Transport with injected httpx MockTransport, asserting decoded response, exact origin/auth headers and cross-provider rejection without live credentials/network. Independent reviews `agent://c03-review-1` and `agent://c03-review-2` were clean at that draft; no review fixes, separate fix commit, or fix verification required. Closure commit `d5e6c1a` exists.

### [x] C04 — Claude subscription adapter

One worker; owned paths: `src/usage_tui/providers/claude.py`, `tests/test_claude.py`, `tests/fixtures/claude_usage.json`.

Implement §4.1 with all three required metric rows. Fixtures cover five-hour, weekly, scoped Fable inactive flag, legacy aliases, missing/invalid/null fields, duplicate conflicts, seconds/milliseconds and invalid resets. Tests assert one request, correct beta header via transport contract, percent direction and no fabricated eligibility.

Exit: all parsable windows survive independently; no Opus/Fable substitution or extra-usage balance conflation.

Closed: implementation and bounded documentation/changelog/Lessons completed; green draft `e4e9798`, separately verified review-fix `42a4abf`, and clean independent rereviews `agent://c04-rereview-1` and `agent://c04-rereview-2`. Final orchestrator gate passed `uv run pytest -q` (425 passed in 0.85s), `uv run ruff check .` (all checks passed), and `uv run ruff format --check .` (18 files already formatted). Claude LSP diagnostics were OK before the review fix; no post-fix LSP result claimed. Actual real ClaudeProvider plus Transport fixture smoke returned all three windows at `12.5` / `110.25` / `23.75`, retaining scoped Fable and clamping overage remaining to `0`. Actual malformed-reset duplicate reproduction lost Fable quota before the fix; confirmed-after smoke retained `23.75` with reset None and partial status. This is offline component evidence, not live/authenticated acceptance. Closure commit `6576e23` exists; no closure rechecks run.

### [x] C05 — Console balance adapter and organization discovery

One worker; owned paths: `src/usage_tui/providers/console.py`, `tests/test_console.py`, `tests/fixtures/console_credits.json`.

Implement §4.2 plus async `discover_organizations(credential) -> tuple[OrganizationChoice, ...]` local to this module; `OrganizationChoice` is a frozen `{id, label}` record. Discovery only lists candidates, never silently picks one. Tests cover multi-org selection, permission failures, complete/missing/empty category arrays, multiple grants, zero/negative amounts, exponent/currency defaults/invalidity, expiry/unknown expiry and disagreement with authoritative total. Tests assert no calls to current_spend/Admin endpoints.

Exit: purchased and promotional totals each have independent state and grant evidence; unknown category never inferred as total minus another category.

Closed: implementation and bounded documentation landed in green draft `98e0c6d`. Orchestrator full green gate passed `uv run pytest -q` (528 tests in 1.00s), `uv run ruff check .` (all checks passed), and `uv run ruff format --check .` (20 files already formatted); Console LSP diagnostics OK. Actual Console discovery and credits adapter/Transport smoke passed with explicit synthetic organization selection, purchased `700`, promotional `0`, authoritative total `700` minor units, and expiry assertions. Initial smoke failure was an omitted required Account `credential_ref` in the harness, corrected without a product fix. Independent reviews `agent://c05-review-1` and `agent://c05-review-2` both clean at `98e0c6d`; no actionable findings or review fixes required. Closure commit `8e74532` exists. Supplied orchestrator evidence preserved without rechecks. This is offline component evidence, not live/authenticated acceptance.

### [x] C06 — Grok billing and product shares

One worker; owned paths: `src/usage_tui/providers/grok.py`, `tests/test_grok.py`, `tests/fixtures/grok_billing.json`.

Implement §4.3. Tests cover unified true/false/missing, weekly/monthly/unknown periods, explicit percent zero vs missing, same-payload validated shares, unknown products, missing Build/Chat, duplicate/malformed arrays, sum tolerance, expired credentials, teams and missing reset. No ACP subprocess/gRPC/browser code, on-demand-derived included quota, or implicit-zero logic.

Exit: aggregate and product rows cannot manufacture independent remaining/reset. Direct request preserves productUsage.

Closed: implementation and bounded documentation/Lessons landed. Approved detail-only product consumption avoids the implicit independent remaining percentage created by `QuotaValue`; proven shared-pool remaining/reset are references, not product quotas. Green draft `515b4f4`; independent review reproduced raw numeric wire precision loss incorrectly accepting an out-of-tolerance breakdown, resolved by separately verified fix `9df9232` using direct Decimal HTTP decoding and raw-numeric boundary coverage. Supplied orchestrator final full green gate passed `uv run pytest -q` (643 passed in 1.27s), `uv run ruff check .` (all checks passed), and `uv run ruff format --check .` (22 files already formatted). Pre-review gate passed 624 tests in 1.11s with Ruff check green and 22 files already formatted. Grok LSP diagnostics OK before the fix only; no post-fix LSP check claimed. Actual Grok adapter/Transport component smoke green: unified shared pool used `42.5`%, remaining `57.5`%, Build consumption `32.5`%, Chat consumption `10`%; detached/unproven-pool smoke also green. Actual raw-numeric regression smoke reproduced erroneous READY products before the fix and confirmed UNKNOWN products afterward, retaining valid shared-pool used `42.5`%. Independent rereviews `agent://c06-rereview-1` and `agent://c06-rereview-2` both clean. Closure commit `6cf9386` exists. No live/authenticated acceptance claimed; no worker checks run.

### [x] C07 — ChatGPT contract resolution and honest capability boundary

Two units with disjoint ownership:

- **C07-A research**, owned planning path: `PLAN.md` §4.4/§7/§9 only. Revisit unresolved ordinary-chat endpoint leads from §7 using static read/search, no browser, credentials, requests to authenticated provider APIs, or implementation. Return sourced request/schema/metric semantics if defensible. Otherwise add a concise exhausted-leads record and exact missing prerequisite; do not declare the feature complete. This is a research-only committable update. Research worker owns PLAN during this unit; integration owner must not edit it concurrently.
- **C07-B capability/registry**, owned paths: `src/usage_tui/providers/chatgpt.py`, `src/usage_tui/providers/base.py`, `src/usage_tui/providers/__init__.py`, `tests/test_capabilities.py`. Implement the explicitly unresolved provider result and complete explicit registry for other implemented adapters. Test required metric enumeration and zero requests from the blocked provider, plus no WHAM/Codex fallback. This is honest capability/error behavior, not ordinary GPT quota implementation.

Exit: ordinary ChatGPT metric remains separately visible/tracked. If C07-A finds a real contract, amend the plan with a bounded C07-C (adapter, fixture, tests; at most five paths) before moving to C08; do not silently narrow or skip it. If unresolved, code work continues while metric acceptance remains blocked.

Closed research/capability milestone only: C07-A sourced exhausted-leads record (§7) found no defensible ordinary-chat weekly contract; no C07-C is justified by that evidence. Explicit registry and blocked ChatGPT capability, bounded documentation/changelog/security, and repo-root Lessons landed at green draft `9eae70a`. Supplied orchestrator gate passed `uv run pytest -q` (653 passed in 1.15s), `uv run ruff check .` (all checks passed), and `uv run ruff format --check .` (26 files already formatted); base/ChatGPT LSP diagnostics OK. Actual registry/blocked-capability smoke passed without dependency, credential, or network access, retaining the required weekly BLOCKED row, `upstream_contract_missing`, and unresolved provenance. Independent reviews `agent://c07-review-1` and `agent://c07-review-2` are clean with no actionable findings; no review-fix commit or separate fix verification required. Closure commit pending; C08 next after that commit. Actual ChatGPT weekly retrieval remains blocked by the missing read/auth/model/weekly-window/reset contract, not merely credentials. No worker rechecks or live/authenticated acceptance claimed.


### [ ] C08 — polling and stale snapshot state machine

One worker; owned paths: `src/usage_tui/scheduler.py`, `tests/test_scheduler.py`, `tests/test_freshness.py`.

Implement §6 with injected clocks/RNG/transport-independent providers and explicit credential generation. Test initial poll, no overlap, global concurrency, origin spacing, coalesced manual refresh, longer Retry-After preservation, exponential cap, auth suspension, account replacement/removal, cancellation, last-good preservation, successful-field disappearance, passed reset, and stale threshold. No real sleeps/network in tests.

Exit: UI does not control quota state by timer and one failing account cannot block others.

### [ ] C09 — deterministic offline source

One worker; owned paths: `src/usage_tui/demo.py`, `src/usage_tui/fixtures/demo.json`, `tests/test_demo.py`.

Implement healthy/errors scenarios with fixed time and required metrics including clearly synthetic GPT data; no live configuration/secret reads. Tests patch storage/resolver/HTTP construction to raise and prove demo never accesses them. Fixture isn't a fallback used after a live fetch fails.

Exit: deterministic first-run demonstration works without a network account; all samples are unmistakably fictional.

### [ ] C10 — account management and secret-input UI

One worker; owned paths: `src/usage_tui/accounts.py`, `tests/test_accounts_ui.py`, `tests/test_account_flows.py`.

Implement reusable Textual account manager screens/modal forms using §5 services. Include create/edit/disable/remove, external references, masked secret set/delete, session-only warning, Console organization selection, Grok scope selection, local-key unsupported-metric explanation, and reconnect guidance. No provider requests except explicit connection discovery/check via injected services. Tests use Pilot plus fake stores/discovery to cover cancel, masked inputs/focus, replacement/removal and no secret in notifications. Keep CLI prompts in C12, not in this screen module.

Exit: no browser dependence; every accepted credential kind has precise local behavior and honest enabled/unsupported metric messaging.

### [ ] C11 — dashboard TUI and help

One worker; owned paths: `src/usage_tui/app.py`, `src/usage_tui/app.tcss`, `tests/test_app.py`, `tests/test_rendering.py`.

Implement §6, wire account manager, subscription/balance/product rows, grant details, provenance, all error/blocked/stale views and keys. Required constructor is §3.2; app depends only on injected scheduler/store factory interfaces. Pilot tests cover 80×24 and 40×12, keyboard navigation, empty state, account manager return, stale countdown, safe labels, DEMO banner and blocked ChatGPT distinction. No new public web/statusline output.

Exit: readable real terminal dashboard with every requested row visible/scrollable; colors are not required to interpret errors.

### [ ] C12 — CLI integration and production-entry PTY harness

Two sequential bounded units:

- **C12-A CLI**, owned paths: `src/usage_tui/cli.py`, `src/usage_tui/__main__.py`, `tests/test_cli.py`. Implement exact §5 commands, live/demo composition, interactive getpass, non-TTY refusal for secret operations, friendly config/keyring/import instructions and error exit codes. API-key storage must not imply subscription support. The C01 entry-point target becomes real here. Exit codes: 0 success/normal TUI quit; 2 usage/config/secret-input error; 3 credential/backend/provider connection failure. Dashboard per-account errors remain in UI. The initial lock already exists; only actual dependency changes justify a separate explicitly bounded metadata/lock owner task.
- **C12-B production PTY harness**, owned paths: `scripts/tui_smoke.py`, `tests/test_smoke_harness.py`, `tests/test_shutdown.py`. Implement a stdlib POSIX PTY harness launching the actual installed `usage --demo` entry point, healthy/errors scenarios, window 80×24 then 40×12, known-token waits, `?`, Escape, `a`, Escape, `r`, then `q`; assert exit 0 and restore termios/cursor/echo. A second run sends Ctrl-C. Bound waits and total timeout, kill/reap in finally, sanitize captures, and fail on traceback. Check provider names, DEMO marker, required synthetic quota/balance labels and account modal, not just startup. Use the same uv environment with isolated temporary HOME/XDG. No worker executes the harness; orchestrator does so before draft/review. Headless Pilot alone is not actual terminal smoke.

Exit: all commands are actual wired behavior, no TODO branches; demo constructs no live client.

### [ ] C13 — documentation reconciliation and terminal harness coverage

Two independent units, followed by D(C13) for any remaining Lessons update:

- **C13-A docs**, owned paths: `README.md`, `CHANGELOG.md`, `SECURITY.md`. Reconcile documentation already maintained with every preceding chunk: install/run, exact account/key setup, private API and session warnings, no-exfiltration, OS/keyring limitations, refresh/staleness, shared pools/expiry vs reset, blocked metrics, demo/live distinction, and exercised verification commands. No unsupported live-success claim; this is not deferred initial documentation delivery.
- **C13-B terminal smoke coverage**, owned paths: `scripts/tui_smoke.py`, `tests/test_smoke_harness.py`, `tests/test_shutdown.py`. Maintain the C12 harness and complete coverage against exercised CLI/TUI behavior; do not introduce a second component-smoke framework. Preserve real PTY, bounded wait, isolated state, rendered-token, Ctrl-C and cleanup requirements.

Exit: documentation matches implemented and exercised commands; orchestrator cumulative gate and production PTY scenarios pass before draft/review/closure. Workers have not executed verification.

### [ ] C14 — orchestrator-owned final cumulative gate and acceptance recording

The **orchestrator itself**, not a delegated integration worker, runs §10's final cumulative checks and actual production PTY smoke after all prior chunks close. Delegate implementation fixes only through exact bounded owner tasks; recheck affected behavior after fixes, never rerun a reported failure merely to confirm it. The orchestrator records evidence in `PLAN.md`; D(C14) owns the four specified documentation paths and updates only actual acceptance/security/lesson findings. No source ownership is implicit in C14.

After offline checks, run the no-credential live empty state and account dialogs without inventing auth. Authenticated checks may be unavailable, but required metric acceptance remains open until actual evidence exists. Never request credentials in chat, log them, or ask the user to commit them. If the user configures accounts locally, compare values against corresponding first-party usage/billing UI manually (browser use remains forbidden to agents). Record only redacted agreement/field-presence evidence and observation time, never balances tied to identity unless authorized.

Exit: final code gate passes before C14's documentation/evidence draft and review; unresolved checks block code closure, while unavailable authenticated metrics and the unresolved ChatGPT contract stay explicitly open in §9, never mislabeled successful. If D(C14) changes material docs after the gate, check those changes before its draft. Remove temporary smoke snippets/hosts and transcripts after each use; retain only the intentional C12 production PTY harness. No claim the full original goal is complete while required live metrics remain unresolved.

## 9. Acceptance matrix — two independent dimensions

Update these only from exercised evidence. Parser fixtures and demo are not live evidence.

| Requirement | Code acceptance | Live/authenticated acceptance |
|---|---|---|
| Claude 5h | [ ] C04/C08/C11 tests | [ ] Eligible credential; compare used/remaining/reset |
| Claude weekly | [ ] C04/C08/C11 tests | [ ] Same account/window matches first-party UI |
| Claude Fable | [ ] Scoped and legacy parser fixtures, inactive scope retained | [ ] Eligible plan returns validated scoped data; otherwise plan-specific unavailable recorded, not global completion |
| Platform purchased | [ ] Multi-grant total/expiry/reconciliation tests | [ ] Selected org session returns purchased array; compare billing balance |
| Platform promotional | [ ] Separate category/missing-array tests | [ ] Selected org returns promo array/explicit empty; compare included/promotional billing grants |
| Ordinary ChatGPT weekly | [x] C07 research/blocked-capability milestone closed at `9eae70a` with full gate, actual registry smoke, base/ChatGPT LSP, and clean independent reviews only; actual quota adapter **unresolved** after C07-A static revisit (§7), not implemented or accepted; no WHAM/local-counter substitution | [ ] **Blocked: side-effect-free ordinary-model request/auth, authoritative weekly schema/window/reset semantics missing**, not just credentials |
| Grok aggregate remaining/reset | [ ] Explicit percentage/period/shared semantics tests | [ ] Logged-in direct proxy matches account period/pool |
| GrokBuild | [ ] Validated same-payload breakdown; shared remaining semantics | [ ] Actual product share and pool relationship observed |
| GrokChat | [ ] Independently tracked row and missing/zero distinction | [ ] Actual product share and pool relationship observed |
| Connect/manage accounts and keys | [ ] CLI/TUI CRUD, cancel, external references | [ ] Actual secure keyring save/replace/delete or clearly session-only; external login import exercised |
| Near-real-time/stale/error behavior | [ ] Fake-clock/retry/cancellation tests | [ ] Poll over at least two intervals without rate-limit bypass; last-known errors visibly stale |
| TUI-only usable product | [ ] Pilot/responsive tests + real PTY smoke | [ ] User-owned live credentials optional for terminal usability, never substituted with demo |
| Secret safety | [ ] Redirect/origin/log/config/input tests | [ ] No raw live captures; local keyring backend supported |

Completion language: “offline implementation and smoke passed, live authentication unavailable” is allowed only with actual offline evidence. “All requested metrics implemented” is false while ordinary ChatGPT contract is missing. A plan/capability blocker is not an accepted scope reduction.

## 10. Exact future verification and scheduling commands

**Planning assignment prohibition:** no verification, formatting, implementation, or commits are executed by this plan-correction assignment. The following commands are future orchestrator responsibilities. Implementation workers write tests/snippets but do not execute them. C01-B resolves the initial lock; later lock resolution requires actual dependency changes and an explicit bounded owner task.

After **every chunk**, including its bounded documentation task, the orchestrator runs all currently available cumulative checks before draft commit/review:

```sh
uv sync --locked --group dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

These start at C01 after its lock lands. Do not invoke nonexistent modules, future commands, or an empty test suite as success. Research/docs-only changes still receive applicable source/document consistency review and the available cumulative gate; they do not invent a new feature smoke. After review fixes the orchestrator reruns affected checks and smoke before each separate fix commit, and the cumulative gate if shared/runtime behavior changed. Record exact commands, outcomes and observations; a worker's proposed command is not exercised evidence.

### Per-chunk actual smoke strategy

Each implementation worker returns an **exact runnable throwaway snippet** for orchestrator `eval` or `bash`, with assertions, bounded waits, cleanup, and nonzero failure. It exercises actual production components outside pytest; injected synthetic HTTP is permitted only at the transport boundary. Use temporary HOME/XDG/private files, session-only secrets, and no real keyring/provider account. Remove temporary scripts/hosts/transcripts after use. No permanent component-smoke dispatcher is required. UI chunks require a real POSIX PTY host, not Pilot alone.

| Chunk | Orchestrator smoke before draft/review (in addition to cumulative gate) |
|---|---|
| C01 | Import installed domain library; construct/validate and serialize/deserialize Account plus nonempty Snapshot, preserving Decimal percentages and aware UTC timestamps; assert invalid numeric/timestamp inputs rejected. Do not invoke `usage` before C12. |
| C02 | Actual AccountStore create/mutate/reload/remove in private temporary filesystem; assert modes and no serialized secret. Actual session-only CredentialStore put/get/delete. Persistent OS-keyring acceptance stays separate. |
| C03 | Resolve synthetic private credential file, then call actual Transport using injected httpx MockTransport; assert decoded response, fixed routing/headers, safe error boundary, and unsupported kind/cross-provider/path rejection before any HTTP request. |
| C04 | Actual Claude adapter → actual Transport → synthetic HTTP; assert independent 5h/weekly/scoped Fable percentages/resets and missing-window behavior. No registry dependency before C07. |
| C05 | Actual Console discovery and credits adapter/Transport; select synthetic organization explicitly, compute multiple-grant purchased/promotional totals independently and preserve authoritative total/expiry. |
| C06 | Actual Grok adapter/Transport; assert unified shared pool, validated same-payload Build/Chat shares, and shared remaining/reset references; malformed breakdown must not invent product values. |
| C07 | Actual explicit registry and ChatGPT capability; assert required weekly blocked row and `upstream_contract_missing`, with resolver/transport access set to fail if touched. Review C07-A sourced findings separately; blocked behavior is not quota implementation. Any sourced C07-C gets its own adapter smoke before C08. |
| C08 | Start actual Scheduler with deterministic clock/resolver/providers; observe success, refresh, safe failure preserving last-good values, replacement/removal and stop; advance fake time, assert all tasks cancel and no publication after stop. |
| C09 | Consume actual healthy/errors DemoSource streams; assert synthetic labels/required metrics/stale-error cases and clean stop, with live HTTP/storage/resolver construction forbidden. |
| C10 | Temporary minimal Textual host containing the production account-management screen in a real PTY, with isolated/session-only stores and injected discovery. Exercise navigation, CRUD/cancel, masked synthetic secret replacement/removal, session warning, Console organization and Grok scope selection, and clean exit. Host is temporary test infrastructure, not a fake production CLI/dashboard. |
| C11 | Actual UsageApp with DemoSource in a temporary real PTY host; assert provider/metric labels and DEMO banner, help, account-manager return, refresh, 80×24→40×12 resize, quit and Ctrl-C cleanup. Pilot tests complement, never replace, this smoke. |
| C12 | Actual installed entry point: help, isolated accounts list and account CRUD/cancel, secret prompt/key operations and non-TTY refusal using synthetic data (never secret arguments); production PTY harness healthy/errors, help/modal/refresh/resize, normal quit and Ctrl-C cleanup. |
| C13 | Reconcile docs against exercised commands; rerun production healthy/errors PTY scenarios for harness changes; confirm cleanup and documented blocked metrics remain honest. |
| C14 | Orchestrator final cumulative gate and production PTY healthy/errors; no-credential live empty state/account dialogs; separately record locally authorized authenticated observations or exact unavailable prerequisites. Blocked upstream/live metrics remain open, never replaced by demo. |

From C12 onward, add these actual-entry checks to each cumulative gate where the runtime/harness exists (always at C12 and final C14):

```sh
uv run usage --help
uv run usage accounts list
uv run python scripts/tui_smoke.py --scenario healthy
uv run python scripts/tui_smoke.py --scenario errors
```

Run accounts list with isolated HOME/XDG. At C10/C11, workers supply exact temporary PTY host code and invocation as part of their return, using already-owned production screens/app; there are no additional permanent worker paths. At C12, the intentional reusable production-entry harness is explicitly owned by C12-B.

`--scenario healthy` maps the harness to `usage --demo`; `--scenario errors` maps to `usage --demo --scenario errors`. Harness must use the installed console entry point from the same uv environment and a clean temporary HOME/XDG environment. No secrets or live config are read by either smoke scenario.

Manual terminal commands (run in a real PTY, not a pipe):

```sh
uv run usage --demo
uv run usage --demo --scenario errors
uv run usage
uv run usage accounts add --provider claude-subscription
uv run usage accounts add --provider claude-platform
uv run usage accounts add --provider chatgpt-subscription
uv run usage accounts add --provider grok-subscription
```

For account CRUD checks, obtain local opaque `ACCOUNT_ID` from `usage accounts list`, then use the exact commands below with that value; no token is a shell argument:

```sh
uv run usage accounts edit ACCOUNT_ID
uv run usage accounts key set ACCOUNT_ID
uv run usage accounts key delete ACCOUNT_ID
uv run usage accounts remove ACCOUNT_ID
```

These `ACCOUNT_ID` examples are command syntax documentation, not placeholder product features. Live dashboard errors must show unconfigured/auth-required/permission/contract-missing states rather than fabricated data. For first-party prerequisites the user runs Claude Code `/login` and/or `grok login` outside this tool; the TUI never silently launches a login browser or receives credentials through chat.

### Scheduler-ready worker prompt template

```
Implement PLAN.md chunk Cxx[-unit] only.
Read PLAN.md sections <contract references> and the owned files after locating them.
Owned paths: <exact paths for this bounded unit; no implicit docs/harness paths>.
Deliver all named behavior and tests; reuse frozen interfaces in section 3.
Do not implement adjacent providers or alter metric meaning. No browser, token
exfiltration, arbitrary endpoints, secret logs, tests/lint/build/smoke/gates, or git
commits. Write tests, but do not execute them. Only C01-B may resolve the initial
lock; later necessary dependency updates need explicit bounded ownership.
Return changed_paths, concrete acceptance_evidence, an exact runnable throwaway
component_smoke_snippet (real PTY host for UI), blockers, checks_not_run, and
reusable_observations for AGENTS.md Lessons. Separate upstream/auth prerequisites
from code status. Documentation is a separately assigned bounded follow-on.
```

Scheduling order: planning Conventional Commit → C01-A → C01-B → D(C01) → gate/smoke/draft/review/fix/close → C02 → (C03-A || C03-B) → C04 → C05 → C06 → (C07-A || C07-B) → [C07-C only if sourced] → C08 → C09 → C10 → C11 → (C12-A → C12-B) → (C13-A || C13-B) → C14. Every later Cxx includes its explicit D(Cxx) task and full lifecycle before the next chunk starts. Do not race on PLAN, metadata or registries. Resolve interface omissions through a bounded owner fix before dependents; never let workers invent competing contracts.

### Next exact bounded assignment

Commit the completed **C07 research/capability closure**, then dispatch **C08 polling and stale snapshot state machine** with the owned paths and exit criteria in §8. C07 is closed for research/capability only at green draft `9eae70a`: implementation, bounded `README.md`/`CHANGELOG.md`/`SECURITY.md` documentation and repo-root `AGENTS.md` Lessons, supplied orchestrator gate (`uv run pytest -q`: 653 passed in 1.15s; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: 26 files already formatted), base/ChatGPT LSP diagnostics OK, and actual no-dependency/credential/network registry/blocked-capability smoke accounted for. Independent reviews `agent://c07-review-1` and `agent://c07-review-2` are clean; no review fixes or separate fix verification required. Closure commit pending; do not dispatch C08 until it exists. The required ChatGPT weekly row remains BLOCKED with `upstream_contract_missing` and unresolved provenance; actual quota retrieval and authenticated acceptance are not complete. C06 closure commit `6cf9386` exists; do not redispatch C01–C07 implementation or repeat completed checks. Keep persistent OS-keyring/live/authenticated acceptance and the missing ordinary ChatGPT read/auth/model/weekly-window/reset contract open. Workers must not run tests, lint, formatters, gates, smoke, browser, or commits.

Resource rule for any later browser-capable or >2 GiB command: browser remains forbidden for this assignment. If an authorized later task changes that restriction, use `~/.omp/bin/heavy-gate`, inspect `free -m` and gate status before fan-out, width ≤2, finite gated commands async with timeout 0, and close owned processes. Ordinary Python unit tests and this stdlib PTY harness do not require a browser launch or heavyweight gate.
