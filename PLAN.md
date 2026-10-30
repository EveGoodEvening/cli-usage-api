# CLIUsageAPI — durable implementation and research plan

## 0. Status, purpose, and scheduling authority

**Latest maintenance authority (2026-10-29): §12 covers the user's Codex display cleanup, Claude polling/rate-limit investigation, and Grok compatibility repair against BYOS; §13 covers the default Nord theme and remembered theme selection; §14 separates Claude Platform balance mismatches from partial data. These sections supersede earlier rules only where stated. Historical gates/reviews below remain historical, not proof of these changes or authenticated compatibility.**

**Supply-chain amendment (2026-10-29): §16 records the user's accepted audit fixes
1–3 and their fresh-install/container verification. It supersedes the mutable build
inputs in §15 without changing application, authentication or provider behavior.**

**CA/runtime amendment (2026-10-29): §17 records the eMudhra incident review,
matched Python/uv pins, managed frontend runtime policy and newly exercised TLS
rejection/build evidence. Its current runtime pins supersede §16's earlier values;
§16's earlier checks remain historical, not fresh CA or cloud-deployment proof.**

Historical pre-Codex baseline: C01–C14 and final split-review fix `d653397` are closed within their recorded scopes. The supplied final post-fix gate passed **851 tests in 28.90s**, Ruff check, **43 files already formatted**, all **17 source-file LSP diagnostics clean**, installed help, four installed-entry healthy/errors PTY runs, installed CLI CRUD/cancel/non-TTY and no-credential empty-state/account dialogs, and the extra-product PTY regression. Those are historical offline/local results, not Codex proof. The corrected Codex single atomic cutover under §11 is closed for implementation, verification, documentation and independent review at green draft `2d7ea6b`; final tracker-snapshot commit follows and its hash is not yet known. Authorized live acceptance remains unexercised.

Original goal: **终端 TUI，近实时查看 Claude 订阅 5h / 每周 / Fable 用量；Claude Platform 普通购买余额和赠送余额；GPT 订阅每周用量；GrokBuild / GrokChat 用量、剩余与重置时间；支持连接账号或管理密钥。不做网页或 statusline。**

**Current corrected goal:** the user explicitly means **Codex quota**, not ordinary ChatGPT chat-model usage. §11 is the bounded authoritative cutover amendment: it supersedes the old GPT scope, blocked-capability contract, scheduling/acceptance instructions and “only accounting remains” conclusions wherever they conflict. Other providers and all recorded C01–C14 evidence retain their original meaning. Do not restart C01–C14 or claim their checks verify Codex.

Independent planning reviews `agent://codex-plan-review-1` and `agent://codex-plan-review-2` were clean; reviewed planning commit `e3190b9` exists. All eight §11 units, bounded docs/Lessons, integrated offline/local proof, green draft `2d7ea6b`, four independent implementation reviews and two final split reviews are complete and clean; no review fixes were required. The final orchestrator gate passed **1098 tests in 30.20s**, Ruff check and **44 files already formatted**. Code closure is not authenticated metric acceptance: the 12 current unchecked live/integration prerequisites are quoted in §11.8. No worker checks, browser activity or real credential reads are authorized.

### Durable progress convention

This file is the only progress tracker. The orchestrator updates checkboxes, acceptance matrix, and this ledger from worker reports and its own exercised evidence. Never mark a chunk complete from a worker's unsupported assertion. Do not place credentials, raw responses, email addresses, or account IDs here. For every C01–C14 chunk record separately: implementation landed; bounded documentation/changelog task completed; repo-root `AGENTS.md` Lessons updated (or observed “no new lesson”); exact orchestrator check commands/outcomes; actual smoke observations; green draft commit; review outcome; separately verified review-fix commits; and closed status. Worker implementation evidence is not orchestrator verification. Keep upstream/live blockers independent of code closure.

A checked chunk heading records implementation/documentation landed and orchestrator checks plus actual component smoke passed; it does not imply review, commits, or closure. Those remain separate ledger fields, and a dependent chunk is not runnable until its predecessor closes.

| Field | Current value |
|---|---|
| Planning | §11 planning reviews clean; planning commit `e3190b9`. All eight atomic-cutover units, docs/Lessons, verification and implementation/final reviews complete; scoped chunk closed at green draft `2d7ea6b`. No live acceptance claimed; historical C01–C14/final-fix evidence unchanged |
| Planning commit | `6f731df57990b6512387ec481ccb693a214d1617` — `docs(plan): record reviewed usage implementation plan` |
| Last closed implementation chunk | §11 atomic Codex cutover — S1/S2/W/T/U/V/D/R implementation, integrated verification, bounded docs/Lessons and independent reviews closed at green draft `2d7ea6b`; no review fixes required. Final tracker-snapshot commit not yet recorded; live acceptance not complete |
| Next runnable action | Commit this completed tracker snapshot; hash not yet known. No implementation, docs, review, gate or smoke work remains runnable. Next user action is externally configuring/authorizing an existing file-backed Codex login and selecting that account in normal TUI configuration, then permitting same-account live/UI comparison; never send secrets through chat |
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
| C08 implementation / docs / gate status | Implementation, bounded documentation/changelog/security, repo-root Lessons, and earlier gate fixes landed at green draft `a634831`; review corrections and associated documentation landed at `8929ac4`. Supplied final separately exercised review-fix gate: `uv run pytest -q`: **704 passed in 1.53s**; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: **29 files already formatted**. Pre-review gate: 697 passed in 1.22s, Ruff check green, 29 files already formatted. Initial 1-failed/692-passed jitter-deadline failure and Ruff BLE001 resolved; additive jitter offsets preserve exact 66s deadline. Initial scheduler LSP diagnostics OK before review fixes only; no post-fix LSP check claimed. Supplied orchestrator evidence preserved; no worker or closure rechecks run |
| C09 implementation / docs / gate status | Deterministic offline source and bounded documentation landed at green draft `0880c02`. Supplied final full green gate: `uv run pytest -q`: **720 passed in 1.43s**; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: **31 files already formatted**; demo LSP diagnostics OK. Actual healthy/errors offline-source stream lifecycle/isolation smoke passed. Independent reviews clean; no review fixes required. Closed at closure commit `f899f26`. No worker checks run |
| C10 implementation / docs / gate status | Account-management and secret-input UI implementation, bounded documentation/changelog/security and repo-root Lessons landed at green draft `730b79d`; review corrections and associated docs/Lessons landed at `5ba9ed2`. Supplied final separately exercised review-fix gate: `uv run pytest -q`: **762 passed in 15.99s**; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: **34 files already formatted**. Pre-review green gate: 748 passed in 13.58s, Ruff check green and 34 files already formatted; this superseded the earlier 748-test/14.26s result with 15 lint errors. Initial accounts LSP diagnostics OK before review fixes only; no post-fix LSP check claimed. Actual pre-fix PTY flows/canonical callable and post-fix fsync-failure smoke are recorded separately below. Both independent rereviews clean. Closed at `ebf90d6`. No worker checks run |
| C11 implementation / docs / gate status | Dashboard/help implementation, bounded documentation/changelog and repo-root Lessons landed at green draft `e3f5b01`; review corrections and associated docs/Lessons landed at `d83a54e`. Lifecycle cleanup uses `_usage_closed`, avoiding collision with Textual's lifecycle state; invalid-kind rendering-fixture and Ruff I001 fixes landed. Supplied final separately exercised review-fix gate: `uv run pytest -q`: **786 passed in 27.11s**; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: **37 files already formatted**. Pre-review gate: 779 passed in 24.82s, Ruff check green and 37 files already formatted, including README; this superseded the initial 6 failed, 772 passed in 24.65s result. Initial app LSP diagnostics OK before review fixes only; no post-fix LSP check claimed. Four actual pre-review UsageApp/DemoSource real-PTY healthy/errors runs passed `x`→`q` / Ctrl-C exit sequences, with rendered metrics and terminal restoration true. Final gate, actual timezone regression smoke and clean rereviews separately verify the fixes; no post-fix full PTY rerun, worker checks or live/authenticated acceptance claimed |
| C11 review findings / bounded corrections | `agent://c11-review-1` found two defects: priority printable `q` bypasses focused text inputs and quits account forms, and UTC-saturated retry deadlines overflow when converted to positive-offset local time. The `q` finding is static Textual dispatch evidence, not an exercised before-fix input reproduction. Supplied actual `TZ=Asia/Shanghai` reproduction of `local_time(datetime.max UTC)` raised `OverflowError` before the fix; actual post-fix smoke rendered the maximum deadline using UTC fallback. Separately verified fix `d83a54e` keeps `q` nonpriority as a dashboard shortcut while preserving unconditional priority Ctrl-C, and falls back to UTC only when local conversion exceeds datetime bounds, without changing retry deadlines or embargoes. README, CHANGELOG and repo-root Lessons record these contracts. `agent://c11-review-2` found no actionable lifecycle/dependency-isolation defect. Independent static rereviews `agent://c11-rereview-1` and `agent://c11-rereview-2` both clean at `d83a54e`; no remaining actionable findings and no reviewer checks run |
| Actual component smoke | Baseline `uv run --locked python -c` assertions passed for exact Account/Snapshot round-trips, Decimal overage, UTC timestamps, money, and invalid-input rejection. Final actual `uv run --locked python -c` smoke passed hostile exponent rejection and exact normal remainder/overage; metadata-only proof demonstrated the old precision risk without expanding hostile exponents. This is domain-library evidence, not CLI/TUI or live-provider acceptance |
| C02 actual component smoke | Actual `uv run --locked python -c` storage/session smoke passed: private temporary config directory `0700` and config file `0600`; AccountStore save/reload/mutate/delete; no serialized synthetic secret; session-only CredentialStore put/get/delete. No real keyring was contacted; persistent OS-keyring and live-provider acceptance remain separate and unexercised |
| C03 actual component smoke | Actual read-only smoke passed: resolve a synthetic Claude credential from a private file, then use the real Transport with injected httpx MockTransport; decoded response, exact fixed origin/auth headers, and cross-provider rejection asserted. No live service or real credential used |
| C04 actual component smoke | Actual real ClaudeProvider plus Transport smoke with an injected in-memory HTTP fixture passed: one request produced all three windows with used percentages `12.5`, `110.25`, and `23.75`; scoped Fable retained and overage remaining clamped to `0`. Actual regression reproduction before the fix lost Fable quota (UNKNOWN, quota None); confirmed-after smoke retained used percentage `23.75`, reset None, and partial fetch status for equal-percent scoped duplicates with malformed reset. No live service or real credential used |
| C05 actual component smoke | Actual Console discovery and credits adapter/Transport smoke passed with an explicitly selected synthetic organization: purchased `700`, promotional `0`, and authoritative total `700` minor units; expiry assertions passed. The smoke harness initially omitted required Account `credential_ref`; correcting the harness made the smoke pass, not a product fix. No live service or real credential used |
| C06 actual component smoke | Actual Grok adapter/Transport smoke green: unified shared pool used `42.5`%, remaining `57.5`%; Build consumption `32.5`%, Chat consumption `10`%, with shared-pool references rather than independent quota remaining/reset. Detached/unproven-pool smoke also green. Actual raw-numeric regression smoke reproduced erroneous READY product rows before the fix for aggregate `42.5`, Build `43.500000000000000000000000000001`, Chat `0`; after `9df9232`, product rows are UNKNOWN and valid shared-pool used `42.5`% is retained. This is supplied orchestrator offline component evidence, not live/authenticated acceptance |
| C07 actual component smoke | Supplied actual explicit registry and ChatGPT blocked-capability smoke passed without dependency, credential, or network access. Required `chatgpt.subscription.weekly` row remains BLOCKED, with `upstream_contract_missing` and unresolved provenance. This verifies the capability boundary, not ordinary ChatGPT quota retrieval or live/authenticated acceptance |
| C08 actual component smoke | Supplied initial standalone Scheduler lifecycle smoke passed immediate publication, no early second poll at 65.5s, second poll at exactly 66s, freshness, account removal, and stop. Actual orchestrator `smoke7sameorigin30s` reproduction used seven same-origin accounts with 30-second intervals: before the fix only six accounts produced initial results over more than 100 seconds; after the fix all seven did over the same more-than-100-second scenario. Resolver-delayed request spacing and extreme retry overflow originated as static review findings, not exercised before/after reproductions; their corrections have regression coverage in the final green gate. Offline component evidence only; no worker smoke rerun or live/authenticated/CLI/TUI acceptance |
| C09 actual component smoke | Supplied actual healthy/errors offline-source stream lifecycle/isolation smoke passed: **4 healthy snapshots / 8 errors snapshots**, with live dependencies forbidden; lifecycle, ticks, stale-state behavior, and clean stop passed. Offline component evidence only; no live/authenticated acceptance claimed |
| C10 actual component smoke | Supplied actual pre-review production AccountManagerScreen smoke in a temporary real PTY host passed CRUD, cancel, masked synthetic secret input/replacement/removal, session-only warning, explicit Console organization and Grok scope selection, resize, quit and Ctrl-C cleanup; supplied canonical callable flow also passed before review fixes. The initial PTY smoke failed because the temporary host's Ctrl-C binding lost to Textual `help_quit`; priority quit binding and PTY output draining corrected the harness, not production code. Separately exercised actual post-fix post-replacement directory-fsync failure retained both new/current and old secrets and reported `e.updated` true. This verifies committed-write durability-warning behavior, not a post-fix rerun of all PTY flows or production CLI/dashboard acceptance. No live service, persistent OS-keyring or authenticated acceptance claimed |
| Green draft commit | C01: `4d082d72f37a1ceb6d5e1e9cc68bcad7c7d62baa`; C02: `af68b54` — green storage/config/session baseline before independent review. C03: `5a9cc60` — green transport/credential-resolution baseline before independent review. C04: `e4e9798` — green Claude subscription adapter baseline before independent review. C05: `98e0c6d` — green Console balance/discovery baseline before independent review. C06: `515b4f4` — green Grok billing/product-share baseline before independent review. C07: `9eae70a` — green research/registry/blocked-capability baseline before independent review. C08: `a634831` — green scheduler/freshness baseline before independent review |
| C09 green draft / review / fixes | Green draft `0880c02`. Independent static reviews `agent://c09-review-1` and `agent://c09-review-2` both clean, with no actionable patch-introduced bug or security finding. No review-fix commit or separate fix verification required; reviewers ran no checks |
| C10 review findings / corrections | Static independent reviews `agent://c10-review-1` and `agent://c10-review-2` found three defects: post-replacement directory-sync failure deleted the newly referenced credential and falsely claimed rejection; the documented async `console_discovery` callable was treated as a provider object; and Console-session entry omitted the required high-sensitivity `sessionKey` warning. Separately verified fix `5ba9ed2` distinguishes committed durability warnings, retains both current/new and previous credentials while crash durability is uncertain, carries the committed account tuple through service errors to host notification, invokes the async callable directly, and displays the value-only warning before masked entry excluding passwords, full Cookie headers and HAR files. Bounded README/changelog/security/Lessons updates record these semantics. Independent static rereviews `agent://c10-rereview-1` and `agent://c10-rereview-2` both clean at `5ba9ed2`, with no remaining actionable findings; reviewers ran no checks |
| Review outcome | C01 initial findings resolved; independent rereviews `agent://c01-rereview-1` and `agent://c01-rereview-2` clean. C02 independent reviews `agent://c02-review-1` and `agent://c02-review-2` both clean, with no actionable findings or review fixes required. C03 independent reviews `agent://c03-review-1` and `agent://c03-review-2` both clean at green draft `5a9cc60`; no actionable findings or review fixes required. C04: `agent://c04-review-1` found equal-percent scoped Fable duplicates with a malformed reset incorrectly discard valid quota; reproduced before the fix and resolved by `42a4abf`. Independent rereviews `agent://c04-rereview-1` and `agent://c04-rereview-2` both clean at the fix, with no remaining actionable findings. C05 independent reviews `agent://c05-review-1` and `agent://c05-review-2` both clean at green draft `98e0c6d`; no actionable findings or review fixes required |
| C06 review outcome | `agent://c06-review-1` reproduced aggregate `42.5` with raw JSON numeric Build share `43.500000000000000000000000000001` and Chat `0` incorrectly accepted as READY. Ordinary HTTP JSON decoding rounded the share to float `43.5`, losing the discrepancy above one percentage point; string-valued boundary tests did not exercise the numeric wire path. Resolved by `9df9232`; independent rereviews `agent://c06-rereview-1` and `agent://c06-rereview-2` both clean, with no remaining actionable findings |
| C08 review outcome | `agent://c08-review-1` found origin spacing reserved before synchronous credential resolution, allowing actual provider request starts to bunch after a slow resolver. `agent://c08-review-2` found insertion-order starvation of overdue initial polls and overflow reconstructing a retry timestamp near UTC `datetime.max`. All three are resolved by `8929ac4`. Independent rereviews `agent://c08-rereview-1` and `agent://c08-rereview-2` both clean at that fix, with no remaining actionable findings; rereviews were static and ran no checks |
| C08 review-fix verification | Separately verified fix `8929ac4` selects oldest eligible due deadlines fairly, applies five-second same-origin spacing after credential resolution immediately before provider request start, and saturates retry presentation timestamps without shortening monotonic server embargoes or losing failure publication. Supplied final gate: 704 tests passed in 1.53s, Ruff check green, 29 files already formatted. Actual seven-account starvation smoke changed from 6/7 initial results before to 7/7 after over more than 100 seconds. Both independent rereviews clean. No post-fix LSP or live/authenticated acceptance claimed |
| Review-fix commits / verification | C01: `650a8a5`, separately verified with final gate/smoke and clean independent rereviews. C02 and C03: not applicable — independent reviews clean; no review-fix commit or fix verification required. C04: `42a4abf`, separately verified by final 425-test/0.85s gate, Ruff check/18-file format check, and actual regression smoke retaining `23.75` quota with reset None and partial status; clean independent rereviews. C05: not applicable — independent reviews clean; no review-fix commit or fix verification required |
| C06 review-fix verification | Fix `9df9232` preserves HTTP JSON numeric tokens directly as Decimal without a float roundtrip; regression coverage sends raw JSON numeric boundary values through Transport and GrokProvider. Separately verified by final 643-test/1.27s gate, Ruff check/22-file format check, and actual reproduced-before/confirmed-after regression smoke: erroneous READY product rows become UNKNOWN while valid shared-pool used `42.5`% is retained. Independent rereviews `agent://c06-rereview-1` and `agent://c06-rereview-2` clean |
| C07 lifecycle | Closed for research/capability only: implementation, bounded docs/Lessons, supplied 653-test/1.15s full gate, Ruff check/26-file format check, base/ChatGPT LSP diagnostics OK, actual no-dependency/credential/network registry and blocked-capability smoke, and green draft `9eae70a` accounted for. Independent reviews `agent://c07-review-1` and `agent://c07-review-2` both clean; no review fixes required. Closure commit `1847d6a` exists. Actual ChatGPT weekly quota retrieval and authenticated acceptance remain blocked on the missing upstream contract |
| C08 lifecycle | Closed: implementation, bounded documentation/changelog/security and repo-root Lessons, initial scheduler LSP diagnostics, initial exact-66s lifecycle smoke, pre-review 697-test/1.22s gate, and green draft `a634831` accounted for. Three review findings resolved in separately verified fix `8929ac4`; final 704-test/1.53s gate, Ruff check/29-file format check, and actual 6/7-before to 7/7-after starvation smoke over more than 100 seconds accounted for. Independent rereviews `agent://c08-rereview-1` and `agent://c08-rereview-2` clean. Closure commit `f11155e` |
| C09 lifecycle | Closed: deterministic offline source and bounded documentation at green draft `0880c02`; supplied final 720-test/1.43s full gate, Ruff check/31-file format check, demo LSP diagnostics OK, and actual 4 healthy / 8 errors snapshots with offline stream lifecycle/isolation, ticks, stale-state, and stop assertions accounted for. Independent reviews `agent://c09-review-1` and `agent://c09-review-2` both clean; no review fixes required; closure commit `f899f26`. No worker rechecks or live/authenticated acceptance claimed |
| C10 lifecycle / review-fix verification | Closed: implementation, bounded documentation/changelog/security and repo-root Lessons at green draft `730b79d`, initial accounts LSP diagnostics, pre-review 748-test/13.58s green gate and actual PTY flows/canonical-callable smoke accounted for. Three review findings resolved in separately verified fix `5ba9ed2`; supplied final 762-test/15.99s gate, Ruff check/34-file format check, and actual post-replacement directory-fsync failure retaining new and old secrets with `e.updated` true accounted for. Independent rereviews `agent://c10-rereview-1` and `agent://c10-rereview-2` clean. Closure commit `ebf90d6`. No post-fix LSP, full PTY rerun, persistent OS-keyring or live/authenticated acceptance claimed |
| C11 lifecycle / review-fix verification | Closed at `cd5561a`: dashboard/help implementation, bounded documentation/changelog and repo-root Lessons at green draft `e3f5b01`, initial pre-fix app LSP diagnostics, pre-review 779-test/24.82s gate, and four actual healthy/errors UsageApp/DemoSource temporary real-PTY runs with `x`→`q` / Ctrl-C exit, rendered metrics and terminal restoration true accounted for. Two review findings resolved in separately verified fix `d83a54e`; supplied final 786-test/27.11s gate, Ruff check/37-file format check and actual maximum-deadline `TZ=Asia/Shanghai` overflow-before/UTC-fallback-after smoke accounted for. Independent rereviews `agent://c11-rereview-1` and `agent://c11-rereview-2` clean. No post-fix LSP/full PTY rerun, installed CLI, persistent OS-keyring or live/authenticated acceptance claimed |
| C12 lifecycle / orchestrator gate / actual-entry smoke | Closed at `6ac1409`: CLI integration, production-entry PTY harness and bounded documentation/changelog/Lessons landed at green draft `119770b`. Supplied full green gate: `uv run pytest -q`: **856 passed in 28.26s**; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: **43 files already formatted**; CLI/main LSP diagnostics OK. Actual installed `usage --help` passed. All four actual installed-entry healthy/errors PTY runs passed, with `x`→`q` / Ctrl-C exit, rendered metrics and terminal restoration true. These results supersede the earlier 16-failed/840-passed gate. Corrected actual installed CLI real-PTY CRUD and empty-live verification passed in **10.60s**: add/list/edit/disable, key cancellation, non-TTY refusal without writes, removal, empty-live manager Back→dashboard→`q`, and manager Ctrl-C. The prior 22-second empty-live timeout was a verifier harness cumulative-token matcher failure: historical output satisfied waits instead of the current rendered screen. Fresh-screen matching corrected the harness; no product defect is claimed. Independent static reviews `agent://c12-review-1` and `agent://c12-review-2` clean at `119770b`, with no actionable findings; no review fixes or separate fix verification required. No worker/reviewer checks, persistent OS-keyring or live/authenticated acceptance claimed |
| Clean close | C01 closure `2347f1f`; C02 `2ab03fb`; C03 `d5e6c1a`; C04 `6576e23`; C05 `8e74532`; C06 `6cf9386`; C07 `1847d6a` for research/capability only; C08 `f11155e`; C09 `f899f26`; C10 `ebf90d6`; C11 `cd5561a`; C12 `6ac1409`; C13 `48358ed` (green draft `bea8a56`, both reviews clean, no fixes). C14 scoped verification/acceptance-record chunk closed at reviewed green draft `1d23bfb`, both per-chunk reviews clean, no fixes. Final split-review sole finding resolved in separately verified fix `d653397`, both independent rereviews clean, final post-fix gate/terminal checks passed. Final tracker/accounting commit pending; original-goal/live acceptance not complete |
| C13 implementation / docs / Lessons | Chinese quickstart, setup and current-status documentation reconciled with implemented commands and honest blocked/live boundaries. Existing production-entry PTY harness retained; seven parameterized mock-wiring test rows were deleted across `test_main_runs_both_quit_paths_without_transcripts` and `test_scenario_drives_installed_entry_and_required_terminal_surface`; substantive behavior tests preserved. Repo-root Lessons now record permanent harness behavior tests rather than mock choreography |
| C13 orchestrator gate / actual-entry smoke | Supplied full green gate: `uv run pytest -q`: **849 passed in 27.76s**; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: **43 files already formatted**; smoke-harness LSP diagnostics OK. All four actual installed-entry healthy/errors PTY runs passed, with `x`→`q` / Ctrl-C exit, rendered metrics and terminal restoration true. The seven-row test-count reduction reflects removal of mock-wiring tests, not loss of substantive behavior coverage. No worker checks or live/authenticated acceptance claimed |
| C13 lifecycle | Closed at `48358ed`: implementation, bounded documentation and Lessons at green draft `bea8a56`; supplied 849-test/27.76s gate, Ruff check/43-file format check, smoke-harness LSP and four actual installed-entry healthy/errors PTY runs accounted for. Both independent static reviews clean; no review fixes or separate fix verification required |
| C14 implementation / verification / acceptance record | Final cumulative offline gate and actual-entry/no-credential smoke supplied by the orchestrator passed; this scoped PLAN acceptance record is complete. Detailed commands/outcomes are in §9's proof ledger. No additional source gap is established by this recording task; ordinary ChatGPT's real adapter remains an explicit implementation gap blocked on §7's contract |
| C14 docs / Lessons / draft / review / fixes / close | PLAN accounting complete. D(C14) completed by `agent://c14-acceptance-record-2` in `README.md` and `CHANGELOG.md` only, recording supplied final evidence without live/keyring success claims. `SECURITY.md` intentionally unchanged: existing boundaries remain accurate. Repo-root `AGENTS.md` unchanged for D(C14): no new lesson; existing Lessons covered those observations. Documentation disposition ready before draft. Green draft `1d23bfb`; independent per-chunk reviews `agent://c14-review-1` (PLAN acceptance/lifecycle accounting) and `agent://c14-review-2` (documentation/evidence boundaries) both clean. No C14 per-chunk review fixes or separate fix verification required. C14 closed only for scoped verification/acceptance recording, not the original goal. Subsequent final split-review finding resolved separately at `d653397`; final tracker/accounting commit pending |
| Final split review / finding / evidence | Four independent slices completed: `agent://final-split-review-1`, `agent://final-split-review-3`, and `agent://final-split-review-4` clean; `agent://final-split-review-2` found one P2 producer/consumer defect. Grok emits sanitized additional product metrics and the scheduler retains them, but the TUI enumerated only required IDs. Supplied actual UsageApp/Pilot synthetic-extra-snapshot reproduction emitted four Grok metrics while overall visible rows stayed **10 → 10**, omitting the extra product. This is exercised offline UI evidence, not authenticated-provider acceptance |
| Final review correction / docs / Lessons / verification | Separately verified fix `d653397` retains every required row first, then deduplicated snapshot extras in emission order; refresh adds/removes extras while preserving selected metric identity, account filtering and existing details/provenance/shared-pool semantics. Coordinated PLAN/README/CHANGELOG and repo-root Lessons record consumer visibility. Initial post-correction **851 passed in 29.59s** and **2 ISC004 findings** at `tests/test_app.py:215` and `tests/test_app.py:220` are superseded by the corrected final green gate: `uv sync --locked --group dev` succeeded; `uv run pytest -q`: **851 passed in 28.90s**; `uv run ruff check .`: passed; `uv run ruff format --check .`: **43 files already formatted**; all **17 source LSP diagnostics clean**. Installed `usage --help`, four healthy/errors installed-entry real-PTY runs (`x`→`q` / Ctrl-C, rendered metrics/restoration true), installed CLI real-PTY CRUD/cancel/non-TTY refusal without writes, and empty-live manager Back→dashboard→`q` / Ctrl-C passed. Additional actual real-PTY regression displayed Other `10` and provenance, refresh removed the extra while retaining required rows, and exited cleanly. Independent static rereviews `agent://final-fix-rereview-1` and `agent://final-fix-rereview-2` both clean. No unresolved finding, lint correction, verification, or rereview remains; final tracker/accounting commit pending. All 13 blocked acceptance tasks unchanged |
| Live checks exercised | No-credential live-mode empty state/account dialogs passed. No authenticated provider request, user-secret import, real external-login import, or real keyring persistence exercised; no user secrets provided |
| Current Codex prerequisite | Official read/auth/window contract established by static first-party source (§11); atomic code/docs/verification/review scope closed at `2d7ea6b`. Live acceptance requires a locally authorized file-backed login, selected account/plan, permitted read and same-account first-party usage UI comparison; unavailable/unexercised, not an upstream-contract blocker |
| Next scheduling action | Commit this tracker snapshot; no fabricated final hash. Thereafter only authorized local user configuration/live observations remain. Old §9 ordinary-ChatGPT code/live tasks are explicitly superseded, not active blockers. Non-Codex historical live prerequisites remain unexercised and unchecked |

## 1. Historical scope and truthfulness matrix — Codex replacement in §11

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

Historical out of scope (Codex exclusion superseded by §11): web UI/server, statusline, browser automation/cookie extraction, local message counting as remote quota, model inference requests, purchases/top-ups, token refresh protocols, scraping conversation contents, reset-coupon redemption, telemetry, OpenAI/xAI API spend dashboards, Claude subscription extra-usage billing. Public cost reports may be cited as non-solutions but are not extra implementation work.

## 2. Chosen boring implementation

**Python 3.11+; `uv`; Textual + Rich; `httpx`; OS `keyring`; `pytest`, `pytest-asyncio`, and `respx` for tests.** Python supports this small read-only local tool without compiling an application framework. Textual supplies terminal rendering, masked inputs, responsive layout, and headless Pilot tests. Use standard-library dataclasses, enums, `Decimal`, `datetime`, `json`, `argparse`, and filesystem APIs instead of a schema/DI/plugin/database framework. `uv.lock` is committed once generated. Pin resolved versions in the lock, not guessed version numbers in this plan. Configure a `src/` layout and console entry point `usage = cli_usage_api.cli:main`.

One async process, one dashboard, a bounded fetch scheduler, immutable normalized snapshots, and explicit provider modules. No general-purpose endpoint configuration, dynamic provider loading, background daemon, SQLite, or server. POSIX/Linux is the initial fully supported target. Other OS credential locations must fail with explicit instructions unless implemented and tested; do not claim cross-platform credential import from a Linux-only implementation.

Required dependency groups: runtime `textual`, `httpx`, `keyring`; dev `pytest`, `pytest-asyncio`, `respx`, `ruff`. Use Ruff only, not a second formatter/linter. Package resource JSON for demo fixtures. Textual Pilot is a dependency of Textual, not a separate product.

### Planned source ownership

- `src/cli_usage_api/domain.py`: public value types, metric IDs, validation and serialization helpers.
- `src/cli_usage_api/storage.py`: nonsecret account/config persistence and secure credential backend.
- `src/cli_usage_api/credentials.py`: read-only first-party credential references and connection validation.
- `src/cli_usage_api/transport.py`: fixed-origin HTTP transport and safe response/error boundary.
- `src/cli_usage_api/providers/{base,claude,console,grok,chatgpt}.py`: normalized provider adapters, no UI imports.
- `src/cli_usage_api/scheduler.py`: polling, retries, cancellation, stale-state merge.
- `src/cli_usage_api/demo.py`, `src/cli_usage_api/fixtures/demo.json`: deterministic offline source.
- `src/cli_usage_api/app.py`, `src/cli_usage_api/accounts.py`, `src/cli_usage_api/app.tcss`: dashboard and account management.
- `src/cli_usage_api/cli.py`, `src/cli_usage_api/__main__.py`: thin CLI/TUI launch.
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

All HTTP production requests are read-only GET, TLS verified, no redirects, `trust_env=False` (avoid implicit proxies/netrc), `Accept: application/json`, identifying `User-Agent: cli-usage-api/<installed-version>`. No configured base URL, credential-forwarding redirect, arbitrary cookie jar, HTTP downgrade, telemetry, or unrelated hosts. A custom host is available only through injected in-memory test transports, never user configuration. Avoid copying upstream tools' browser import, insecure cookie config, inferred quotas, or telemetry behavior.

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

A mismatch alone is a successful read (`ok`) with a curated `balance_mismatch`
advisory, not `partial_data`. Total-balance details show the exact signed difference
(reported total minus category sums), formatted with the validated currency/exponent;
no tolerance or rounding is applied. Missing/invalid values and uncertain expiry
retain partial/schema diagnostics. A simultaneous mismatch stays in the total detail.

Credits expire; they do not “reset weekly.” Show nearest expiry plus expandable per-grant expiries, never a fabricated renewal. Do not call `/current_spend` or Admin reporting just to fill a balance gap. HTTP 401 or organization-list 403 means reconnect; selected-org credits 403 means billing permission denied. Session credential never goes to api.anthropic.com or claude.ai.

### 4.3 Grok shared pool, Build, and Chat

Prefer a direct implementation of the **official CLI's existing read-only billing request**, not spawning a potentially updating/telemetry-enabled agent process. Fixed origin `https://cli-chat-proxy.grok.com`; exact path `/v1/billing?format=credits`; headers `Authorization: Bearer <key>`, `x-xai-token-auth: xai-grok-cli`, `Accept: application/json`. Include `x-userid` only from the same resolved credential. Under §12, add release-pinned `x-grok-client-version: 1.0.70`, sourced from the official stable feed; retain identifying `User-Agent: cli-usage-api/<installed-version>`. No runtime download, guessed version, client-mode header, or upstream User-Agent impersonation. This sourced compatibility adjustment does not prove the user's billing failure was a version rejection.

Connection: official `grok login` runs outside this app. Read `$GROK_HOME/auth.json` or `~/.grok/auth.json`; top-level keys identify scopes. Prefer the selected `https://auth.x.ai::<client-id>` entry, fallback to `https://accounts.x.ai/sign-in` only if no ambiguity. Entry contains `key`, `expires_at`, `user_id`, `team_id`, `auth_mode`, and optional `principal_type`. Expiry parser accepts timezone-aware RFC3339 and explicitly tested Unix seconds/milliseconds; unknown expiry is not asserted fresh. Multiple matching identities require user selection stored as a nonsecret scope selector; do not accidentally choose another account. Never copy `refresh_token` into app storage or refresh it. Manual bearer is supported with unknown identity until configured; API/management keys beginning `xai-` are rejected for subscription use. Team principal unsupported responses are actionable, not retried under an unrelated personal account.

Parse root `config` object, optional `subscriptionTier`/`subscription_tier` metadata; `config.creditUsagePercent` finite nonnegative means shared included usage only when `config.isUnifiedBillingUser == true` positively establishes that relationship. `currentPeriod` contains optional `type`, RFC3339 `start`, `end`. Known weekly/monthly types determine labels. Reset is `currentPeriod.end`, fallback to `billingPeriodEnd` only when current-period end is absent; invalid or reversed bounds cannot supply reset. Under §12's BYOS-compatible omitted-default convention, an absent `creditUsagePercent` means zero only with explicit `USAGE_PERIOD_TYPE_WEEKLY` and a valid reset. Present null/malformed values remain invalid; absent scalar without that context remains unknown. No included-usage inference from on-demand spend/prepaid balance, legacy estimated cap, gRPC/browser fallback, or reset-coupon lookup.

`config.productUsage` is an observed private array of `{product: "GrokBuild" | "GrokChat" | other_string, usagePercent: number}`. Validate the whole array (unique product identities, finite nonnegative values, no malformed entries) and require a usable aggregate from the same response. §12 removes the unsupported sum-to-aggregate invariant: BYOS projects informational shares even when their sum differs. With explicit weekly type and valid reset, an existing entry's omitted `usagePercent` means zero; a missing product, present null, or invalid percentage never does. Preserve sanitized unknown-product IDs. An invalid breakdown must not discard valid aggregate evidence. Product consumption remains detail-only (`quota=None`), never independent `100 - share` remaining. Attach `shared_pool_id`/reset only with positive unified-pool evidence; otherwise remaining/reset stay unavailable. No cross-account enrichment or blending different requests.

HTTP JSON decimal numeric tokens must decode directly to `Decimal`; converting a binary float back to a string cannot recover wire precision. §12 removes C06's unsupported one-point reconciliation test, not exact arithmetic: raw numeric `43.500000000000000000000000000001` must retain that exact product value. Boundary regressions must exercise actual raw JSON numbers through Transport and GrokProvider, not only strings or decoded objects. C06's original finding/fix remains historical evidence of the float-decoding defect.

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

Config path: `$XDG_CONFIG_HOME/cli-usage-api/accounts.json` (fallback `~/.config/cli-usage-api/accounts.json`). Create private parent directory `0700`; atomic same-directory config replacement with `0600`; reject symlink config targets and unsafe ownership/modes on credential import before reading on POSIX. Imported first-party credential paths must be regular, user-owned, not group/world-readable; report permission instructions rather than chmod or mutate them. Max credential/config file size 1 MiB. App stores no secret or raw-response cache; snapshots are memory-only. A config load error does not overwrite existing data. Account changes are serialized in one process; do not claim safe concurrent config writers without a lock. Implement a standard-library POSIX advisory lock for config mutations and reread under lock to prevent lost updates.

HTTP credentials are limited to their exact origins (§4). Disable redirects, netrc, implicit proxy env, and cookie persistence. Never send an API key for an OAuth source or a Console cookie to another Anthropic service. No browser imports, analytics, crash-report uploads, endpoint override, or raw HTTP debug flag. Logs contain safe codes and local opaque account IDs only; logging is off by default. UI shows “stored securely,” “session only,” or “external credential reference,” not a token suffix. Diagnostics cannot interpolate upstream body strings, URLs with query credentials, arbitrary exception repr, or local identity data.

## 6. Polling, freshness, and terminal behavior

“Near real time” means bounded periodic observation, not a provider push/SLA. Saved intervals remain integer 30…3600 seconds with default 60. Under §12.1, Claude subscription's effective cadence is `max(180, saved_interval)`; automatic polling clamps jitter at that floor and can add up to 10%, including for existing saved 60-second accounts without rewriting config. Freshness uses that same effective cadence. Other providers retain ±10% jitter and the 30-second minimum. One fetch per account, max two concurrent accounts, and five-second same-origin request-start spacing remain. Console discovery is connection-only; no duplicate request per metric. HTTP connect timeout 5s, overall deadline 10s, streamed decoded JSON limit 1 MiB; shutdown cancels work and closes owned clients.

Fetch immediately after connection/start. Explicit `r` may bypass periodic cadence but coalesces refreshes and respects in-flight work, origin spacing, and retry embargoes. One-second presentation ticks do not fetch. Auth/permission failures suspend until explicit reconnect/config replacement. Other providers keep exponential error backoff 60, 120, 240…900 seconds plus bounded jitter. Claude 429 backoff starts 180, then 360, 720, and 900 seconds plus bounded jitter, never earlier than its effective configured cadence; other Claude errors also respect that cadence. All valid longer server `Retry-After` deadlines win, never shortened by the local cap. Same-provider account replacement preserves embargoes. Compatible success resets failure backoff; missing/malformed retry headers use the local policy. This is a conservative local policy, not a discovered upstream rate threshold.

Select eligible work by oldest due deadline so overdue accounts, including initial polls, cannot be perpetually overtaken by accounts already serviced. Measure the five-second origin gate after credential resolution, immediately before entering the provider request; queue-time reservations do not establish actual request-start spacing. Keep retry embargoes monotonic and preserve long server deadlines; if reconstructing a UTC presentation timestamp would overflow, saturate it at UTC `datetime.max` without shortening the embargo or dropping the failure snapshot. These C08 review corrections landed in separately verified fix `8929ac4`, with clean independent rereviews recorded in the ledger.

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

- **C01-A package/domain**, owned paths: `pyproject.toml`, `src/cli_usage_api/__init__.py`, `src/cli_usage_api/domain.py`, `tests/test_domain.py`, `.gitignore`. Implement §2/§3 types, metric constants, finite numeric/timestamp helpers, schema serialization, dependency/entry-point/dev group declarations. `.gitignore` excludes venvs/caches/builds/local secrets and smoke transcripts without hiding source fixtures. Tests cover bool-as-number, >100%, partial values, money arithmetic and aware timestamps. Do not add a fake CLI/provider. Return an exact throwaway library smoke snippet; do not invoke the future `usage` entry point.
- **C01-B initial lock**, owned path: `uv.lock`, after C01-A metadata lands. Run `uv lock` for dependency resolution only; return the exact command/outcome and lock path. No installation, tests, lint, formatting, application launch, or commits. If metadata must change, request a bounded C01-A owner fix first.

Then D(C01) owns only the four documentation paths above. Exit: domain signatures and IDs match the plan, initial lock exists, and the orchestrator installs the locked environment and exercises domain round-trip/validation smoke before draft/review/closure. Suggested draft subject: `feat(domain): draft C01 package and frozen contracts`.

Closed: final gates and actual domain smoke passed, both independent rereviews were clean, separate review-fix commit `650a8a5` is recorded in the ledger, and closure commit `2347f1f` exists. C02 closure commit `2ab03fb` also exists; C03 closure is recorded below.

### [x] C02 — local account config and secure key management

One worker; target paths: `src/cli_usage_api/storage.py`, `tests/test_storage.py`, `tests/test_secret_store.py`.

Implement AccountStore/CredentialStore, locking/atomic private config, secure-backend validation, session-only references, CRUD and cancellation-safe mutation. Tests inject fake encrypted/insecure/locked backends, malformed/newer config, permissions, symlinks, atomic write failure, and concurrent mutation lock behavior. Never contact a real keyring in tests.

Exit: no serialized secret, no insecure automatic persistence fallback, no external credential mutation.

Closed: C02 implementation and bounded documentation/Lessons landed in green draft `af68b54`. The orchestrator's full green gate passed: `uv run pytest -q`: 167 passed in 0.55s; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: 11 files already formatted; storage LSP diagnostics OK. Actual `uv run --locked python -c` storage/session smoke passed private temporary config directory/file modes `0700`/`0600`, AccountStore save/reload/mutate/delete, no serialized synthetic secret, and session-only CredentialStore put/get/delete without contacting a real keyring. Independent reviews `agent://c02-review-1` and `agent://c02-review-2` were clean; no review fixes, separate fix commit, or fix verification required. Closure commit `2ab03fb` exists. Persistent OS-keyring/live acceptance remains unexercised and open.

### [x] C03 — transport and credential resolution

Both independent worker units landed after C02 closure commit `2ab03fb`; their ownership and implementation contracts are preserved below:

- **C03-A**, owned paths: `src/cli_usage_api/transport.py`, `tests/test_transport.py`, `tests/test_security.py`. Implement §4 fixed origins/path guards/auth-header mapping, streaming response bound, deadlines, no redirects/proxy inheritance, structured safe failures and Retry-After parsing. Test allowlisted origins/paths, attempted redirect exfiltration, credentials in exception bodies, cross-provider credential rejection, oversized/error/non-JSON bodies.
- **C03-B**, owned paths: `src/cli_usage_api/credentials.py`, `tests/test_credentials.py`, `tests/fixtures/credentials.json`. Implement read-only first-party reference resolution, profile selection, import permission checks, expiry/scope parsing and manual-secret references. Fixture is synthetic and clearly labeled. No actual home-directory reads in tests.

Exit: exact Transport and Resolver interfaces in §3 available; source credentials captured once per attempt. Integrator resolves only true interface discrepancies through a worker, not ad hoc rewrites.

Closed: C03 implementation and bounded documentation/Lessons landed in green draft `5a9cc60`. Orchestrator full green gate passed: `uv run pytest -q`: 345 passed in 0.80s; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: 16 files already formatted; credentials/transport LSP diagnostics OK. Actual read-only component smoke passed private synthetic Claude credential resolution followed by real Transport with injected httpx MockTransport, asserting decoded response, exact origin/auth headers and cross-provider rejection without live credentials/network. Independent reviews `agent://c03-review-1` and `agent://c03-review-2` were clean at that draft; no review fixes, separate fix commit, or fix verification required. Closure commit `d5e6c1a` exists.

### [x] C04 — Claude subscription adapter

One worker; owned paths: `src/cli_usage_api/providers/claude.py`, `tests/test_claude.py`, `tests/fixtures/claude_usage.json`.

Implement §4.1 with all three required metric rows. Fixtures cover five-hour, weekly, scoped Fable inactive flag, legacy aliases, missing/invalid/null fields, duplicate conflicts, seconds/milliseconds and invalid resets. Tests assert one request, correct beta header via transport contract, percent direction and no fabricated eligibility.

Exit: all parsable windows survive independently; no Opus/Fable substitution or extra-usage balance conflation.

Closed: implementation and bounded documentation/changelog/Lessons completed; green draft `e4e9798`, separately verified review-fix `42a4abf`, and clean independent rereviews `agent://c04-rereview-1` and `agent://c04-rereview-2`. Final orchestrator gate passed `uv run pytest -q` (425 passed in 0.85s), `uv run ruff check .` (all checks passed), and `uv run ruff format --check .` (18 files already formatted). Claude LSP diagnostics were OK before the review fix; no post-fix LSP result claimed. Actual real ClaudeProvider plus Transport fixture smoke returned all three windows at `12.5` / `110.25` / `23.75`, retaining scoped Fable and clamping overage remaining to `0`. Actual malformed-reset duplicate reproduction lost Fable quota before the fix; confirmed-after smoke retained `23.75` with reset None and partial status. This is offline component evidence, not live/authenticated acceptance. Closure commit `6576e23` exists; no closure rechecks run.

### [x] C05 — Console balance adapter and organization discovery

One worker; owned paths: `src/cli_usage_api/providers/console.py`, `tests/test_console.py`, `tests/fixtures/console_credits.json`.

Implement §4.2 plus async `discover_organizations(credential) -> tuple[OrganizationChoice, ...]` local to this module; `OrganizationChoice` is a frozen `{id, label}` record. Discovery only lists candidates, never silently picks one. Tests cover multi-org selection, permission failures, complete/missing/empty category arrays, multiple grants, zero/negative amounts, exponent/currency defaults/invalidity, expiry/unknown expiry and disagreement with authoritative total. Tests assert no calls to current_spend/Admin endpoints.

Exit: purchased and promotional totals each have independent state and grant evidence; unknown category never inferred as total minus another category.

Closed: implementation and bounded documentation landed in green draft `98e0c6d`. Orchestrator full green gate passed `uv run pytest -q` (528 tests in 1.00s), `uv run ruff check .` (all checks passed), and `uv run ruff format --check .` (20 files already formatted); Console LSP diagnostics OK. Actual Console discovery and credits adapter/Transport smoke passed with explicit synthetic organization selection, purchased `700`, promotional `0`, authoritative total `700` minor units, and expiry assertions. Initial smoke failure was an omitted required Account `credential_ref` in the harness, corrected without a product fix. Independent reviews `agent://c05-review-1` and `agent://c05-review-2` both clean at `98e0c6d`; no actionable findings or review fixes required. Closure commit `8e74532` exists. Supplied orchestrator evidence preserved without rechecks. This is offline component evidence, not live/authenticated acceptance.

### [x] C06 — Grok billing and product shares

One worker; owned paths: `src/cli_usage_api/providers/grok.py`, `tests/test_grok.py`, `tests/fixtures/grok_billing.json`.

Implement §4.3. Tests cover unified true/false/missing, weekly/monthly/unknown periods, explicit percent zero vs missing, same-payload validated shares, unknown products, missing Build/Chat, duplicate/malformed arrays, sum tolerance, expired credentials, teams and missing reset. No ACP subprocess/gRPC/browser code, on-demand-derived included quota, or implicit-zero logic.

Exit: aggregate and product rows cannot manufacture independent remaining/reset. Direct request preserves productUsage.

Closed: implementation and bounded documentation/Lessons landed. Approved detail-only product consumption avoids the implicit independent remaining percentage created by `QuotaValue`; proven shared-pool remaining/reset are references, not product quotas. Green draft `515b4f4`; independent review reproduced raw numeric wire precision loss incorrectly accepting an out-of-tolerance breakdown, resolved by separately verified fix `9df9232` using direct Decimal HTTP decoding and raw-numeric boundary coverage. Supplied orchestrator final full green gate passed `uv run pytest -q` (643 passed in 1.27s), `uv run ruff check .` (all checks passed), and `uv run ruff format --check .` (22 files already formatted). Pre-review gate passed 624 tests in 1.11s with Ruff check green and 22 files already formatted. Grok LSP diagnostics OK before the fix only; no post-fix LSP check claimed. Actual Grok adapter/Transport component smoke green: unified shared pool used `42.5`%, remaining `57.5`%, Build consumption `32.5`%, Chat consumption `10`%; detached/unproven-pool smoke also green. Actual raw-numeric regression smoke reproduced erroneous READY products before the fix and confirmed UNKNOWN products afterward, retaining valid shared-pool used `42.5`%. Independent rereviews `agent://c06-rereview-1` and `agent://c06-rereview-2` both clean. Closure commit `6cf9386` exists. No live/authenticated acceptance claimed; no worker checks run.

### [x] C07 — ChatGPT contract resolution and honest capability boundary

Two units with disjoint ownership:

- **C07-A research**, owned planning path: `PLAN.md` §4.4/§7/§9 only. Revisit unresolved ordinary-chat endpoint leads from §7 using static read/search, no browser, credentials, requests to authenticated provider APIs, or implementation. Return sourced request/schema/metric semantics if defensible. Otherwise add a concise exhausted-leads record and exact missing prerequisite; do not declare the feature complete. This is a research-only committable update. Research worker owns PLAN during this unit; integration owner must not edit it concurrently.
- **C07-B capability/registry**, owned paths: `src/cli_usage_api/providers/chatgpt.py`, `src/cli_usage_api/providers/base.py`, `src/cli_usage_api/providers/__init__.py`, `tests/test_capabilities.py`. Implement the explicitly unresolved provider result and complete explicit registry for other implemented adapters. Test required metric enumeration and zero requests from the blocked provider, plus no WHAM/Codex fallback. This is honest capability/error behavior, not ordinary GPT quota implementation.

Exit: ordinary ChatGPT metric remains separately visible/tracked. If C07-A finds a real contract, amend the plan with a bounded C07-C (adapter, fixture, tests; at most five paths) before moving to C08; do not silently narrow or skip it. If unresolved, code work continues while metric acceptance remains blocked.

Closed research/capability milestone only: C07-A sourced exhausted-leads record (§7) found no defensible ordinary-chat weekly contract; no C07-C is justified by that evidence. Explicit registry and blocked ChatGPT capability, bounded documentation/changelog/security, and repo-root Lessons landed at green draft `9eae70a`. Supplied orchestrator gate passed `uv run pytest -q` (653 passed in 1.15s), `uv run ruff check .` (all checks passed), and `uv run ruff format --check .` (26 files already formatted); base/ChatGPT LSP diagnostics OK. Actual registry/blocked-capability smoke passed without dependency, credential, or network access. Independent reviews `agent://c07-review-1` and `agent://c07-review-2` clean; no review fixes required. Closure commit `1847d6a` exists. C08 is now closed as recorded below; C09 follows its closure commit. Actual ChatGPT weekly retrieval remains blocked by the missing read/auth/model/weekly-window/reset contract, not merely credentials. No worker rechecks or live/authenticated acceptance claimed.


### [x] C08 — polling and stale snapshot state machine

One worker; owned paths: `src/cli_usage_api/scheduler.py`, `tests/test_scheduler.py`, `tests/test_freshness.py`.

Implement §6 with injected clocks/RNG/transport-independent providers and explicit credential generation. Test initial poll, no overlap, global concurrency, origin spacing, coalesced manual refresh, longer Retry-After preservation, exponential cap, auth suspension, account replacement/removal, cancellation, last-good preservation, successful-field disappearance, passed reset, and stale threshold. No real sleeps/network in tests.

Exit: UI does not control quota state by timer and one failing account cannot block others.

Closed scheduler milestone: implementation, bounded documentation/changelog/security, repo-root Lessons, and earlier gate fixes landed at green draft `a634831`. Supplied pre-review gate passed `uv run pytest -q` (**697 passed in 1.22s**), `uv run ruff check .` (all checks passed), and `uv run ruff format --check .` (**29 files already formatted**); initial scheduler LSP diagnostics OK before review fixes only. Initial exact-jitter failure and Ruff BLE001 resolved; additive jitter offsets preserve exact 66s. Initial standalone Scheduler lifecycle smoke passed publication, 65.5s/66s boundary, freshness, removal, and stop. Independent reviews found starvation, resolver-delayed actual-request spacing, and retry timestamp overflow; all three were corrected in separately verified fix `8929ac4`. Supplied final gate passed **704 tests in 1.53s**, Ruff check, and the **29-file** format check. Actual orchestrator seven-account same-origin/30-second-interval starvation reproduction changed from **6/7 initial results before to 7/7 after over more than 100 seconds**; the other two findings have regression coverage, not claimed before/after smoke reproductions. Independent rereviews `agent://c08-rereview-1` and `agent://c08-rereview-2` both clean. Closure commit `f11155e`. No worker or closure checks, post-fix LSP, or live/authenticated acceptance claimed.

### [x] C09 — deterministic offline source

One worker; owned paths: `src/cli_usage_api/demo.py`, `src/cli_usage_api/fixtures/demo.json`, `tests/test_demo.py`.

Implement healthy/errors scenarios with fixed time and required metrics including clearly synthetic GPT data; no live configuration/secret reads. Tests patch storage/resolver/HTTP construction to raise and prove demo never accesses them. Fixture isn't a fallback used after a live fetch fails.

Exit: deterministic first-run demonstration works without a network account; all samples are unmistakably fictional.

Closed: implementation and bounded documentation landed at green draft `0880c02`. Supplied final orchestrator full green gate: `uv run pytest -q`: **720 passed in 1.43s**; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: **31 files already formatted**; demo LSP diagnostics OK. Actual offline-source healthy/errors stream lifecycle/isolation smoke passed **4 healthy / 8 errors snapshots**, with live dependencies forbidden, including lifecycle, ticks, stale-state behavior, and clean stop. Independent static reviews `agent://c09-review-1` and `agent://c09-review-2` both clean; no review fixes or separate fix verification required. Closure commit `f899f26`. No worker checks or live/authenticated acceptance claimed.

### [x] C10 — account management and secret-input UI

One worker; owned paths: `src/cli_usage_api/accounts.py`, `tests/test_accounts_ui.py`, `tests/test_account_flows.py`.

Implement reusable Textual account manager screens/modal forms using §5 services. Include create/edit/disable/remove, external references, masked secret set/delete, session-only warning, Console organization selection, Grok scope selection, local-key unsupported-metric explanation, and reconnect guidance. No provider requests except explicit connection discovery/check via injected services. Tests use Pilot plus fake stores/discovery to cover cancel, masked inputs/focus, replacement/removal and no secret in notifications. Keep CLI prompts in C12, not in this screen module.

Exit: no browser dependence; every accepted credential kind has precise local behavior and honest enabled/unsupported metric messaging.

Closed: implementation and bounded documentation/changelog/security/Lessons landed at green draft `730b79d`; three independent-review findings resolved in separately verified fix `5ba9ed2`. Supplied final full green orchestrator gates: **762 passed in 15.99s**, Ruff check passed, and Ruff format check reported **34 files already formatted**. Initial accounts LSP diagnostics OK before fixes only. Actual pre-review production AccountManagerScreen temporary real-PTY smoke passed CRUD/cancel, masked synthetic secret input/replacement/removal, session-only warning, Console organization and Grok scope selection, resize, quit and Ctrl-C cleanup; canonical callable smoke also passed before fixes. Initial Ctrl-C failure was in the temporary host's Textual `help_quit` binding; a priority quit binding and PTY draining corrected the harness. Actual post-fix post-replacement directory-fsync failure retained new/current and old secrets with `e.updated` true. Independent static rereviews `agent://c10-rereview-1` and `agent://c10-rereview-2` both clean at `5ba9ed2`. C10 closure commit is `ebf90d6`. No worker checks, post-fix LSP/full PTY rerun, production CLI/dashboard or live/authenticated acceptance claimed.

### [x] C11 — dashboard TUI and help

One worker; owned paths: `src/cli_usage_api/app.py`, `src/cli_usage_api/app.tcss`, `tests/test_app.py`, `tests/test_rendering.py`.

Implement §6, wire account manager, subscription/balance/product rows, grant details, provenance, all error/blocked/stale views and keys. Required constructor is §3.2; app depends only on injected scheduler/store factory interfaces. Pilot tests cover 80×24 and 40×12, keyboard navigation, empty state, account manager return, stale countdown, safe labels, DEMO banner and blocked ChatGPT distinction. No new public web/statusline output.

Exit: readable real terminal dashboard with every requested row visible/scrollable; colors are not required to interpret errors.

Closed at closure commit `cd5561a`: dashboard/help implementation and bounded documentation/changelog/Lessons landed at green draft `e3f5b01`; lifecycle cleanup uses `_usage_closed` to avoid Textual's lifecycle-state collision, and invalid-kind rendering-fixture and Ruff I001 fixes landed. Initial app LSP diagnostics were OK before review fixes only. Supplied pre-review full orchestrator gate: 779 passed in 24.82s, Ruff check passed, and 37 files already formatted, including README; this superseded the initial 6 failed, 772 passed in 24.65s result. Actual pre-review UsageApp with DemoSource temporary real-PTY smoke passed four healthy/errors runs and `x`→`q` / Ctrl-C exit sequences; rendered metrics and terminal restoration were true in all runs. Review identified printable-priority `q` intercepting account-form text entry (static dispatch evidence) and saturated UTC retry timestamps overflowing during local conversion (actual `TZ=Asia/Shanghai` reproduction). Separately verified fix `d83a54e` makes `q` nonpriority, preserves unconditional priority Ctrl-C, and uses UTC fallback only for unrepresentable local timestamps without changing deadlines/embargoes; associated docs/Lessons record these contracts. Supplied final gate: **786 passed in 27.11s**, Ruff check green, **37 files already formatted**; actual post-fix maximum-deadline rendering used UTC fallback. Independent rereviews `agent://c11-rereview-1` and `agent://c11-rereview-2` clean. No worker verification, post-fix LSP/full PTY rerun, installed CLI or live/authenticated acceptance claimed.

### [x] C12 — CLI integration and production-entry PTY harness

Two sequential bounded units:

- **C12-A CLI**, owned paths: `src/cli_usage_api/cli.py`, `src/cli_usage_api/__main__.py`, `tests/test_cli.py`. Implement exact §5 commands, live/demo composition, interactive getpass, non-TTY refusal for secret operations, friendly config/keyring/import instructions and error exit codes. API-key storage must not imply subscription support. The C01 entry-point target becomes real here. Exit codes: 0 success/normal TUI quit; 2 usage/config/secret-input error; 3 credential/backend/provider connection failure. Dashboard per-account errors remain in UI. The initial lock already exists; only actual dependency changes justify a separate explicitly bounded metadata/lock owner task.
- **C12-B production PTY harness**, owned paths: `scripts/tui_smoke.py`, `tests/test_smoke_harness.py`, `tests/test_shutdown.py`. Implement a stdlib POSIX PTY harness launching the actual installed `usage --demo` entry point, healthy/errors scenarios, window 80×24 then 40×12, known-token waits, `?`, Escape, `a`, Escape, `r`, then `q`; assert exit 0 and restore termios/cursor/echo. A second run sends Ctrl-C. Bound waits and total timeout, kill/reap in finally, sanitize captures, and fail on traceback. Check provider names, DEMO marker, required synthetic quota/balance labels and account modal, not just startup. Use the same uv environment with isolated temporary HOME/XDG. No worker executes the harness; orchestrator does so before draft/review. Headless Pilot alone is not actual terminal smoke.

Exit: all commands are actual wired behavior, no TODO branches; demo constructs no live client.

Closed at closure commit `6ac1409`: C12-A CLI, C12-B production-entry PTY harness and bounded documentation/changelog/Lessons landed at green draft `119770b`. Supplied full orchestrator gate is green: **856 passed in 28.26s**; `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: **43 files already formatted**; CLI/main LSP diagnostics OK. Actual installed `usage --help` and all four healthy/errors production-entry PTY runs passed, including `x`→`q` / Ctrl-C exit, rendered metrics and terminal restoration true. The earlier interactive TTY/capsys fixture failures are superseded by this supplied green gate. Corrected actual installed CLI real-PTY CRUD and empty-live verification passed in **10.60s**: add/list/edit/disable, key cancellation, non-TTY refusal without writes, removal, empty-live manager Back→dashboard→`q`, and manager Ctrl-C. The prior 22-second empty-live timeout arose from the verifier harness's cumulative-token matcher accepting historical output; fresh-screen matching corrected the harness, not production code. Independent static reviews `agent://c12-review-1` and `agent://c12-review-2` clean at `119770b`, with no actionable findings; no review fixes or separate fix verification required. No worker/reviewer checks were run; no persistent OS-keyring or live/authenticated acceptance claimed.

### [x] C13 — documentation reconciliation and terminal harness coverage

Two independent units, followed by D(C13) for any remaining Lessons update:

- **C13-A docs**, owned paths: `README.md`, `CHANGELOG.md`, `SECURITY.md`. Reconcile documentation already maintained with every preceding chunk: install/run, exact account/key setup, private API and session warnings, no-exfiltration, OS/keyring limitations, refresh/staleness, shared pools/expiry vs reset, blocked metrics, demo/live distinction, and exercised verification commands. No unsupported live-success claim; this is not deferred initial documentation delivery.
- **C13-B terminal smoke coverage**, owned paths: `scripts/tui_smoke.py`, `tests/test_smoke_harness.py`, `tests/test_shutdown.py`. Maintain the C12 harness and complete coverage against exercised CLI/TUI behavior; do not introduce a second component-smoke framework. Preserve real PTY, bounded wait, isolated state, rendered-token, Ctrl-C and cleanup requirements.

Exit: documentation matches implemented and exercised commands; orchestrator cumulative gate and production PTY scenarios pass before draft/review/closure. Workers have not executed verification.

Closed at `48358ed`: Chinese quickstart/setup/current-status documentation reconciled; seven parameterized mock-wiring rows removed, substantive behavior tests preserved, and repo-root Lessons updated. Supplied full orchestrator gate: **849 passed in 27.76s**, Ruff check green, **43 files already formatted**, smoke-harness LSP diagnostics OK; all four installed-entry healthy/errors PTY runs passed with rendered metrics and terminal restoration true. Green draft `bea8a56`; both independent static reviews clean; no review fixes required. C14's distinct final cumulative gate has now passed as separately recorded below. No worker verification or authenticated acceptance claimed.

### [x] C14 — orchestrator-owned final cumulative gate and acceptance recording (closed within verified scope)

The **orchestrator itself**, not a delegated integration worker, runs §10's final cumulative checks and actual production PTY smoke after all prior chunks close. Delegate implementation fixes only through exact bounded owner tasks; recheck affected behavior after fixes, never rerun a reported failure merely to confirm it. The orchestrator records evidence in `PLAN.md`; D(C14) owns the four specified documentation paths and updates only actual acceptance/security/lesson findings. No source ownership is implicit in C14.

After offline checks, run the no-credential live empty state and account dialogs without inventing auth. Authenticated checks may be unavailable, but required metric acceptance remains open until actual evidence exists. Never request credentials in chat, log them, or ask the user to commit them. If the user configures accounts locally, compare values against corresponding first-party usage/billing UI manually (browser use remains forbidden to agents). Record only redacted agreement/field-presence evidence and observation time, never balances tied to identity unless authorized.

Exit: final code gate passes before C14's documentation/evidence draft and review; unresolved checks block code closure, while unavailable authenticated metrics and the unresolved ChatGPT contract stay explicitly open in §9, never mislabeled successful. If D(C14) changes material docs after the gate, check those changes before its draft. Remove temporary smoke snippets/hosts and transcripts after each use; retain only the intentional C12 production PTY harness. No claim the full original goal is complete while required live metrics remain unresolved.

Closed scope: supplied cumulative gate, actual production-entry PTY smoke, installed CLI CRUD/cancel/non-TTY refusal, and no-credential live empty state/account dialogs passed; scoped acceptance recording complete. D(C14) documentation/changelog disposition is complete and ready before draft, with no new lesson for that task; details are in the ledger. Green draft `1d23bfb`; independent per-chunk reviews `agent://c14-review-1` and `agent://c14-review-2` clean; no C14 per-chunk fixes or separate fix verification required. This closes the verification/acceptance-record chunk only. Subsequent final split review completed four slices, three clean and one additional-Grok-product UI omission finding; separately verified fix `d653397` resolves it, both independent fix rereviews are clean, and the final post-fix gate/actual terminal checks passed (§9). Only final tracker/accounting commit remains runnable; hash pending. All 13 unchecked §9 tasks retain their original scope and exact blockers; offline/local deliverable verified, original full goal blocked.

## 9. Acceptance matrix — two independent dimensions

Historical pre-Codex matrix: update only from exercised evidence. Parser fixtures and demo are not live evidence. The ordinary-ChatGPT code/live rows and blocker language below are superseded by §11's Codex replacement; they are not active Codex blockers or current unchecked implementation work.

| Requirement | Code acceptance | Live/authenticated acceptance |
|---|---|---|
| Claude 5h | [x] C04/C08/C11 tests | [ ] Eligible credential; compare used/remaining/reset |
| Claude weekly | [x] C04/C08/C11 tests | [ ] Same account/window matches first-party UI |
| Claude Fable | [x] Scoped and legacy parser fixtures, inactive scope retained | [ ] Eligible plan returns validated scoped data; otherwise plan-specific unavailable recorded, not global completion |
| Platform purchased | [x] Multi-grant total/expiry/reconciliation tests | [ ] Selected org session returns purchased array; compare billing balance |
| Platform promotional | [x] Separate category/missing-array tests | [ ] Selected org returns promo array/explicit empty; compare included/promotional billing grants |
| Ordinary ChatGPT weekly | [ ] Actual ordinary ChatGPT weekly quota adapter. C07 research/blocked-capability milestone is closed at `9eae70a`; its tested blocked row is not quota implementation/acceptance. Missing contract in §7; no WHAM/local-counter substitution | [ ] **Blocked: side-effect-free ordinary-model request/auth, authoritative weekly schema/window/reset semantics missing**, not just credentials |
| Grok aggregate remaining/reset | [x] Explicit percentage/period/shared semantics tests | [ ] Logged-in direct proxy matches account period/pool |
| GrokBuild | [x] Validated same-payload breakdown; shared remaining semantics | [ ] Actual product share and pool relationship observed |
| GrokChat | [x] Independently tracked row and missing/zero distinction | [ ] Actual product share and pool relationship observed |
| Connect/manage accounts and keys | [x] CLI/TUI CRUD, cancel, external references | [ ] Actual secure keyring save/replace/delete or clearly session-only; external login import exercised |
| Near-real-time/stale/error behavior | [x] Fake-clock/retry/cancellation tests | [ ] Poll over at least two intervals without rate-limit bypass; last-known errors visibly stale |
| TUI-only usable product | [x] Pilot/responsive tests + real PTY smoke | [x] User-owned live credentials optional for terminal usability, never substituted with demo |
| Secret safety | [x] Redirect/origin/log/config/input tests | [ ] No raw live captures; local keyring backend supported |

Completion language: “offline implementation and smoke passed, live authentication unavailable” is allowed only with actual offline evidence. “All requested metrics implemented” is false while ordinary ChatGPT contract is missing. A plan/capability blocker is not an accepted scope reduction.

### C14 proof ledger — supplied orchestrator evidence, not worker execution

| Command / exercised surface | Actual supplied outcome and boundary |
|---|---|
| `uv sync --locked --group dev` | Succeeded |
| `uv run pytest -q` | **849 passed in 27.81s**; final cumulative code evidence, not authenticated provider evidence |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | **43 files already formatted** |
| Source LSP diagnostics | All **17 source files clean**; diagnostic tool invocation was not included in the supplied summary, so no shell command is invented |
| Installed `usage --help` | Passed; no fabricated wrapper/options beyond the supplied command |
| `uv run python scripts/tui_smoke.py --scenario healthy` / `uv run python scripts/tui_smoke.py --scenario errors` (§10 harness entry commands) | Supplied actual healthy/errors installed-entry smoke: **four PTY runs**, `x`→`q` and Ctrl-C paths, rendered metrics and terminal restoration **true**. These are synthetic DEMO observations, not live metrics |
| Actual installed CLI in real PTY: account CRUD/cancel, non-TTY secret refusal | Passed add/list/edit/disable/remove, key cancellation, refusal without writes; synthetic/isolated account state only. The throwaway verifier's exact invocation was not supplied here and is not fabricated |
| Actual installed `usage` without credentials in real PTY | Empty-live manager Back→dashboard→`q` and manager Ctrl-C passed. This establishes live-mode terminal usability, not authenticated metric retrieval |
| Authenticated reads, real external login import, persistent OS keyring | **Not exercised**. No authorized real credentials/configuration supplied; no user secrets provided/imported and no raw live captures. Prior fake backend, session-only and fixture checks do not substitute for real persistence/provider acceptance |

The checked code cells are supported jointly by the recorded cumulative suite and the detailed C01–C13 component/regression records above. The TUI usability cell is supported by actual no-credential live-mode PTY behavior, not by substituting demo for a live provider. That acceptance-record worker ran no verification, browser, or commits. Subsequent final split review established the additional-Grok-product UI omission (four emitted Grok metrics, overall visible rows **10 → 10**); separately verified fix `d653397`, clean independent rereviews `agent://final-fix-rereview-1` and `agent://final-fix-rereview-2`, and the final post-fix proof ledger below resolve that finding. The missing ordinary ChatGPT adapter remains a concrete code gap, not hidden by the successful blocked-capability milestone. No acceptance checkbox or prerequisite is changed by this closeout record.

### Final post-fix proof ledger — supplied orchestrator evidence at `d653397`

This supersedes the pre-fix C14 cumulative result for final code verification; it does not replace the historical C14 record or complete authenticated acceptance. This bookkeeping worker executed no verification or commits.

| Exact supplied command / exercised surface | Actual supplied outcome and boundary |
|---|---|
| `uv sync --locked --group dev` | Passed |
| `uv run pytest -q` | **851 passed in 28.90s** |
| `uv run ruff check .` | Passed; prior 2 ISC004 findings corrected |
| `uv run ruff format --check .` | **43 files already formatted** |
| Source LSP diagnostics | All **17 source files clean**; exact diagnostic invocation not supplied, not invented |
| Installed `usage --help` | Passed |
| `uv run python scripts/tui_smoke.py --scenario healthy` / `uv run python scripts/tui_smoke.py --scenario errors` | Four actual installed-entry real-PTY runs passed; healthy/errors, `x`→`q` / Ctrl-C, rendered metrics and terminal restoration true |
| Actual installed CLI real-PTY CRUD/cancel/non-TTY | Passed; refusal without writes and isolated/synthetic state, not real-keyring acceptance. Exact throwaway verifier invocation not supplied, not invented |
| Actual installed no-credential live dashboard | Empty-live manager Back→dashboard→`q` and manager Ctrl-C passed, not authenticated retrieval |
| Additional-product actual real-PTY regression | Other `10` and provenance visible; refresh removes extra and retains required rows; clean exit. Exact throwaway verifier invocation not supplied, not invented |
| Final review disposition | Split slices 1/3/4 clean; slice 2 sole P2 omission resolved by separately verified `d653397`; `agent://final-fix-rereview-1` and `agent://final-fix-rereview-2` both clean |
| Authenticated providers / real import / persistent keyring | Not exercised; concrete §9 prerequisites remain absent |
| Final tracker/accounting commit | Pending; no fabricated hash |

### Full flat accounting of remaining unchecked acceptance tasks

Historical pre-Codex accounting only: the then-unchecked matrix comprised **13 tasks, one contract-blocked ordinary-ChatGPT adapter and 12 live/integration checks**. §11 supersedes that adapter and ordinary-ChatGPT live prerequisite with the user-corrected Codex scope. Codex implementation/integrated proof is now passed; authorized file-backed login and same-account UI comparison remain open, not upstream-contract-blocked. Other providers' live prerequisites below remain applicable. The old “only accounting remains” lifecycle conclusion below is historical, not current scheduling authority.

| Requirement / dimension | Exact unchecked task wording | Classification and precise missing prerequisite |
|---|---|---|
| Ordinary ChatGPT weekly / code | “Actual ordinary ChatGPT weekly quota adapter. C07 research/blocked-capability milestone is closed at `9eae70a`; its tested blocked row is not quota implementation/acceptance. Missing contract in §7; no WHAM/local-counter substitution” | **Blocked — upstream contract**, not just credentials. Need §7's attributable sanitized ordinary-model side-effect-free read origin/path/method/auth/scope and authoritative used/remaining/cap-or-utilization, model-sharing, weekly-window, reset timezone/reference, and absent/unlimited/exhausted schema examples before adapter/fixture/tests can be implemented. No authorized alternative scope reduction exists |
| Claude 5h / live | “Eligible credential; compare used/remaining/reset” | **Blocked — authorized configuration absent.** Need a locally authorized eligible Claude Code login or supported bearer with usable profile-read scope, private external reference, successful usage response and user-side first-party UI comparison at the same observation/window |
| Claude weekly / live | “Same account/window matches first-party UI” | **Blocked — authorized configuration absent.** Need the same eligible Claude account/profile-read credential and corresponding weekly first-party UI observation; no real account/window was observed |
| Claude Fable / live | “Eligible plan returns validated scoped data; otherwise plan-specific unavailable recorded, not global completion” | **Blocked — authorized configuration and eligibility evidence absent.** Need an eligible plan/seat and profile-read response with positively identified Fable scope, or positive plan-specific exclusion evidence. A missing fixture/live field alone cannot establish global ineligibility |
| Platform purchased / live | “Selected org session returns purchased array; compare billing balance” | **Blocked — authorized configuration absent.** Need locally configured user-owned Console sessionKey, explicitly selected billing organization with billing-read permission, purchased grant array/explicit empty evidence and matching billing UI observation |
| Platform promotional / live | “Selected org returns promo array/explicit empty; compare included/promotional billing grants” | **Blocked — authorized configuration absent.** Need locally configured Console session and selected billing-readable organization exposing promo grants or explicit empty array plus corresponding included/promotional billing UI observation; no inference from total-minus-purchased |
| Ordinary ChatGPT weekly / live | “**Blocked: side-effect-free ordinary-model request/auth, authoritative weekly schema/window/reset semantics missing**, not just credentials” | **Blocked — upstream contract and authorized configuration absent.** Need §7's ordinary-chat contract, implemented adapter and then eligible locally authorized model/plan/workspace credential/scope plus first-party weekly UI comparison. Credentials alone, Codex/WHAM, feature counters and local counts do not remove the contract blocker |
| Grok aggregate remaining/reset / live | “Logged-in direct proxy matches account period/pool” | **Blocked — authorized configuration absent.** Need locally configured eligible first-party Grok login file with explicit scope/profile or supported bearer, subscription billing permission and actual direct-proxy period/unified-pool response plus same-account UI comparison; any real minimal-header rejection requires sourced contract repair, not guessed headers |
| GrokBuild / live | “Actual product share and pool relationship observed” | **Blocked — authorized configuration/response evidence absent.** Need eligible selected Grok identity with positively established unified billing and same-payload aggregate plus validated Build product share, with first-party comparison. Missing product share is not zero |
| GrokChat / live | “Actual product share and pool relationship observed” | **Blocked — authorized configuration/response evidence absent.** Need eligible selected Grok identity with positively established unified billing and same-payload aggregate plus validated Chat product share, with first-party comparison. Build evidence cannot fill Chat's independent acceptance |
| Connect/manage accounts and keys / live | “Actual secure keyring save/replace/delete or clearly session-only; external login import exercised” | **Blocked for the remaining real integration portion — authorized configuration absent.** Actual session-only/synthetic CRUD is established above; real encrypted OS-keyring save/replace/delete has not been exercised. Need an available/unlocked supported encrypted backend for persistent acceptance (or explicit session-only choice), and authorized private user-owned Claude/Grok first-party login file with the selected identity/scope for actual external-login import. Synthetic import and fake backends do not complete this conjunction |
| Near-real-time/stale/error behavior / live | “Poll over at least two intervals without rate-limit bypass; last-known errors visibly stale” | **Blocked — authorized configuration absent.** Need an eligible locally configured live account/credential and permitted read-only observation across at least two actual polling intervals, with visible last-known/stale behavior on an observed error and preserved service retry deadlines. Fake clocks and DEMO cover code only; do not deliberately provoke rate limiting |
| Secret safety / live | “No raw live captures; local keyring backend supported” | **Blocked for real-backend/live integration — authorized configuration absent.** No raw live captures were made; real supported encrypted backend availability/unlock and authorized local secret lifecycle remain unexercised. Need locally authorized backend/persistence observation without logging/capturing secret material; session-only/fake-backend tests are not persistent-keyring proof |

Final lifecycle disposition (not accepted metrics): C14 scoped verification/acceptance-record chunk closed at reviewed green draft `1d23bfb`; both per-chunk reviews clean, D(C14) disposition complete. All four final split-review slices are disposed: slices 1/3/4 clean; slice 2's sole additional-Grok-product omission fixed in separately verified `d653397`. Both independent fix rereviews are clean. Final post-fix cumulative gate, installed-entry/CLI/no-credential terminal checks and extra-product real-PTY regression passed. No review, fix, gate, smoke, or newly doable implementation action remains. Final tracker/accounting commit is pending and is the only runnable action; no hash is claimed. Thereafter all remaining work is blocked by the 13 concrete prerequisites above. Offline/local deliverable verified; original full goal blocked, not complete.

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
uv run usage accounts add --provider codex-subscription
uv run usage accounts add --provider grok-subscription
uv run usage accounts migrate-chatgpt-to-codex
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

Current bounded assignment: §11's single atomic Codex cutover is closed for implementation, integrated verification, bounded docs/Lessons and independent review, following planning commit `e3190b9` and green draft `2d7ea6b`. All eight units, four implementation reviews, two final split reviews and the final gate/component/terminal proof are complete; no fixes were required. Only commit of this completed tracker snapshot remains runnable; its hash is not yet known. Closed C01–C14 and fix `d653397` stay historical and must not be redispatched or rechecked for bookkeeping. The next user action is external file-backed Codex login authorization and normal TUI account configuration, not sharing secrets through chat. Authorized live comparison and non-Codex historical live prerequisites remain unexercised. Workers must not run tests, lint, formatters, gates, smoke, browser or commits.

Resource rule for any later browser-capable or >2 GiB command: browser remains forbidden for this assignment. If an authorized later task changes that restriction, use `~/.omp/bin/heavy-gate`, inspect `free -m` and gate status before fan-out, width ≤2, finite gated commands async with timeout 0, and close owned processes. Ordinary Python unit tests and this stdlib PTY harness do not require a browser launch or heavyweight gate.

## 11. User-corrected Codex cutover — current authority

### 11.1 Scope, status and evidence

The user corrected “GPT weekly” to **Codex weekly quota**. This is a scope correction, not discovery of ordinary-chat quota. Replace the blocked ordinary-ChatGPT capability cleanly; do not add a second provider or keep runtime aliases. Sections 1/3/4.4/7/8/9/10 and their old scheduling conclusions are historical wherever they assert GPT identities, prohibit Codex, or say no implementation remains. Preserve C01–C14 checks/commits as historical evidence, not Codex verification. No other provider requirement changes. This appendix is the only new plan/tracker; no competing plan or new C01–C14 sequence.

Current status: **atomic Codex cutover closed for implementation, integrated verification, documentation/Lessons and independent review; planning commit `e3190b9`, green draft `2d7ea6b`; final tracker-snapshot commit pending with no known hash; authenticated Codex acceptance unexercised**. Planning reviews `agent://codex-plan-review-1` and `agent://codex-plan-review-2` were clean. Four implementation reviews `agent://codex-cutover-review-1`, `agent://codex-cutover-review-2`, `agent://codex-cutover-review-3`, `agent://codex-cutover-review-4` and final split reviews `agent://codex-final-split-review-1`, `agent://codex-final-split-review-2` were clean; no fixes or separate fix verification required. Final supplied gate: 1098 tests in 30.20s, Ruff check passed, 44 files already formatted; earlier 17 source-file LSP diagnostics remain clean with no source changes since. Required component/terminal proof passed (§11.7). Workers ran no checks; browser, real credential reads and real upstream/keyring access were not used.

Primary-source contract anchors (static research, not authenticated observation):

- [Pinned official client routing](https://github.com/openai/codex/blob/f802f0a3/codex-rs/backend-client/src/client.rs#L98-L104), [headers](https://github.com/openai/codex/blob/f802f0a3/codex-rs/backend-client/src/client.rs#L190-L218), [usage GET](https://github.com/openai/codex/blob/f802f0a3/codex-rs/backend-client/src/client.rs#L284-L301), [duration/reset normalization](https://github.com/openai/codex/blob/f802f0a3/codex-rs/backend-client/src/client.rs#L542-L560).
- [Official payload](https://github.com/openai/codex/blob/main/codex-rs/codex-backend-openapi-models/src/models/rate_limit_status_payload.rs#L16-L53), [window fields](https://github.com/openai/codex/blob/main/codex-rs/codex-backend-openapi-models/src/models/rate_limit_window_snapshot.rs#L14-L23), [additional pools](https://github.com/openai/codex/blob/main/codex-rs/codex-backend-openapi-models/src/models/additional_rate_limit_details.rs#L16-L28), [normalized reset unit](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs#L2577-L2630).
- [Official auth-file schema](https://github.com/openai/codex/blob/main/codex-rs/login/src/auth/storage.rs#L47-L75), [token/account claims](https://github.com/openai/codex/blob/main/codex-rs/login/src/token_data.rs#L11-L75), [JWT expiry parsing](https://github.com/openai/codex/blob/main/codex-rs/login/src/token_data.rs#L156-L161), [pinned API-key rejection and account fallback](https://github.com/openai/codex/blob/53b50197/codex-rs/tui/src/local_chatgpt_auth.rs#L13-L43), [storage modes](https://github.com/openai/codex/blob/main/codex-rs/config/src/types.rs#L137-L147).
- [Pinned official app-server quota test](https://github.com/openai/codex/blob/53b50197/codex-rs/app-server/tests/suite/v2/rate_limits.rs#L63-L168) proves request/header and synthetic 300s/3600s/feature-pool shapes, not a live account. [Identity-free third-party captured WHAM fixture](https://github.com/chopratejas/headroom/blob/42ebbc6c/tests/test_codex_rate_limits.py#L18-L38) is supplemental parser evidence only. Moving `main` model links are version-sensitive references, not a public supported API guarantee.

### 11.2 Frozen identities and quota semantics

- `ProviderId.CODEX_SUBSCRIPTION = "codex_subscription"`; CLI choice **`codex-subscription`**; display **Codex**; class **`CodexProvider`**, module **`providers/codex.py`**. Delete `providers/chatgpt.py`, its exports/registry entry, `ProviderId.CHATGPT_SUBSCRIPTION`, `MetricId.CHATGPT_WEEKLY` and the old CLI choice. Old strings survive only in the narrow migration detector/tests and explicitly historical documentation, never as active aliases.
- `CredentialKind.CODEX_AUTH_FILE = "codex_auth_file"` is Codex's **only** permitted stored/read credential kind. A detached Codex account may have no credential. No Codex manual bearer, API-key, Console session or Grok/Claude file support; reject rather than inherit the current general “API keys permitted for storage” rule for Codex. Other providers' key-management contracts do not change.
- `MetricId.CODEX_WEEKLY = "codex.subscription.weekly"` is the **only required Codex row**, label **Codex weekly (7d)**, selected by `limit_window_seconds == 604800` from the main `rate_limit`, regardless of primary/secondary position. This is a seven-day window, not evidence of a calendar-week boundary. `REQUIRED_METRIC_IDS[CODEX_SUBSCRIPTION]` and `CodexProvider.metric_ids` contain exactly this ID.
- Optional reported main windows: `MetricId.CODEX_FIVE_HOUR = "codex.subscription.five_hour"`, label **Codex 5h**, only when duration is `18000`; other positive integer durations use `codex.subscription.window.<seconds>` with a duration-bearing label. Do not create a mandatory 5h/30d row or infer entitlement from plan names. Null/missing main weekly remains UNKNOWN, not zero/not-applicable or a guessed secondary window.
- Optional additional pools remain distinct: `codex.pool.<sha256(metered_feature UTF-8).hexdigest()>.window.<seconds>` for valid nonempty `metered_feature` and positive integer duration. This follows existing hashed extra-product identity practice, fits the 128-character metric-ID bound, and never hashes credentials. Preserve sanitized `limit_name`/feature display, not raw terminal markup. Do not sum pools or use them to satisfy the main weekly row. Same-identity duplicate windows must reconcile only if their valid values agree; conflicting usage/reset stays unknown/partial for that identity, never last-wins. Unclassifiable/malformed siblings produce safe partial detail without discarding valid windows or inventing a duration.
- Use validated nonnegative `used_percent`, preserve >100, derive remaining `max(0,100-used)`, reject bool/nonfinite/negative values. Missing usage stays unknown independently of reset. Absolute **`reset_at` Unix seconds** is canonical: parse finite valid integer seconds to aware UTC with safe bounds; no milliseconds guessing and **no timestamp fabricated from `reset_after_seconds`**. Invalid/missing reset does not erase valid usage. Relative reset may be omitted; it must never be promoted to an absolute timestamp.
- `allowed`, `limit_reached`, and `plan_type` do not establish quota and, under the user's §12 display request, are not emitted in displayed detail. Sanitized `rate_limit_reached_type` may remain explanatory, never proof of 100% usage. Credits/unlimited-credit flags, spend control, code-review limits and reset credits are not main quota and do not mandate new metrics. No balance adapter or purchases. Source remains `SourceRef(kind="private_http", contract="codex.wham.usage.v1", version_sensitive=True)`; DEMO uses `offline_demo` and never a live fallback.

### 11.3 Frozen read/auth interface

`CodexProvider.requires_credential=True`; reuse the scheduler's ordinary credentialed path, refresh/retry/stale/cancellation rules. Fetch makes one fixed-origin read through injected Transport: **GET `https://chatgpt.com/backend-api/wham/usage`**, no query, alternate host/path/base URL, redirects, cookies, model inference, conversations, login or refresh. Provider and Transport both enforce provider/kind binding. Transport must have an **explicit Codex header branch**: `Authorization: Bearer <tokens.access_token>` and `ChatGPT-Account-Id: <selected account ID>` plus existing generic safe headers. Never fall through to Grok's `x-xai-token-auth`/`x-userid` branch; reject cross-provider credentials before any socket/header construction. Preserve existing bounded HTTP/JSON/error machinery; 401 is auth-required, 403 permission-denied, 429 preserves server retry; no response body or secrets in diagnostics.

Default file reference is `$CODEX_HOME/auth.json` when CODEX_HOME is set/nonempty, otherwise `~/.codex/auth.json`; an explicit private file reference may select another existing file-backed login. Preserve the existing owner/mode/no-follow/size/stability checks. Do not inspect real files during implementation. Keyring-only/auto-without-file and ephemeral Codex login are explicitly unavailable with instructions to configure a file-backed login externally; do not probe Codex keyring, launch Codex, or add a login flow.

Read only `tokens.access_token` for Bearer and `tokens.account_id` for selected account, falling back only to decoded ID-token payload `["https://api.openai.com/auth"]["chatgpt_account_id"]` when the explicit account ID is absent. Reject absent/empty/malformed bearer, absent selected account ID, wrong field types, `auth_mode="api_key"`, and nonempty `OPENAI_API_KEY`; never use API-key auth. An explicit invalid account ID is an error, not permission to silently choose the fallback. Do not require a `scopes` field absent from Codex's schema. Do not infer account ID from local UUID, label, organization, Grok user ID or arbitrary JWT claims.

Extend `ResolvedCredential` with **`codex_account_id: str | None = field(default=None, repr=False)`**, requiring a nonempty header-safe ID for Codex and forbidding it for other providers. Keep `user_id` Grok-only in this path; account model/serialized config needs no new upstream-ID field. Resolver captures bearer and selected ID together from one stable file read for each fetch. Neither is copied into config/provenance; both remain redacted, and generation fingerprint includes account selection so replacement is not relabeled.

Decode access-token JWT payload only to read `exp` as an absolute Unix-seconds staleness hint: expired/malformed expiry yields a safe auth-required result; missing expiry remains unknown, not an invented lifetime. Decode ID-token payload only for the documented selected-account fallback. **Unverified JWT decoding is local provenance/expiry extraction, not signature verification or an authentication trust boundary**; a nonexpired token is not proof of validity and the server remains authoritative. Never use `last_refresh` as expiry, read/use refresh tokens for authentication, refresh/rewrite the file, emit claims/account IDs/tokens or log decode exceptions. Existing resolver error categories and safe messages apply.

### 11.4 Explicit one-time legacy configuration handling

Choose a **narrow schema-v1 storage migration**, not a schema bump, persistent provider alias, silent relabel, destructive reset or whole-config failure with no repair path. Normal `AccountStore.load/mutate/save` fail closed with a curated migration instruction when raw records contain exactly legacy `provider="chatgpt_subscription"`; all other malformed/unknown-provider rules remain intact. No legacy account reaches scheduler/resolver/transport. A plain start/list can direct the user to the migration command without rewriting bytes.

Freeze public repair callables on AccountStore:

- `legacy_chatgpt_profiles() -> tuple[tuple[str, str], ...]`: return only validated local `(account_id, sanitized_label)` pairs; no secret reads, references or upstream identifiers printed. Validate the entire schema-v1 config and each narrowly recognized legacy shape without reintroducing an enum/provider alias.
- `migrate_legacy_chatgpt_to_codex(*, confirmed_account_ids: tuple[str, ...]) -> tuple[Account, ...]`: lock and reread using existing stable-lock atomic-write/durability semantics; require the confirmed IDs to equal the current complete legacy-ID set (duplicates/changes fail without write). Validate all target/current accounts before writing. Convert only those records to Codex, preserve local ID/label/poll interval, set `enabled=False`, clear `credential_kind`, `credential_ref`, `credential_selector`, `organization_id`; leave every other account unchanged. Return committed accounts, preserving the existing committed-write/durability-warning distinction. Repeated invocation with no legacy profiles is a harmless no-op; no always-on compatibility path remains.

CLI **`usage accounts migrate-chatgpt-to-codex`** is the sole migration entry: in a real TTY show profiles and explain “Codex, disabled, credential detached; old keyring secrets retained; configure a file-backed Codex login separately”, then require explicit affirmative confirmation for the whole listed set before invoking the callable. No `--yes`, implicit startup conversion, non-TTY consent, sensitive args or TUI auto-migration. Decline/cancel/error leaves config bytes and all keyring entries untouched. TUI config-error guidance names this command, then restart normally after migration. Ordinary account edit remains provider-fixed; reconnect cannot perform semantic migration.

This callable **never calls CredentialStore.get/put/delete**, AccountService's replacement-secret cleanup or external-file deletion. Old stored bearer/API-key values are never resolved, transmitted, copied or reused. Original keyring entries remain retained but detached/unmanaged; state that explicitly, with deletion only as a separate deliberate owner/backend action, not automatic migration cleanup. Do not add an unused secret-deletion API or retention schema. Configure the disabled replacement through normal account edit/reconnect with `codex_auth_file` before enabling; preserve normal no-credential/unconfigured behavior. Migration fixtures use fake references and injected backends that fail if touched. Cover mixed providers, multiple legacy profiles, changed confirmed set, malformed config, decline/no-TTY, committed durability warning, and repeated migration.

### 11.5 One atomic chunk; bounded internal ownership

**One reviewable clean-cutover chunk**, not ten red sequential releases. First complete planning review; then the shared-contract owners S1/S2 publish interfaces in the working tree (no intermediate gate/release). Dependent internal units run in parallel when their true prerequisites exist; only the whole integrated chunk receives the cumulative gate, actual smoke, draft, independent reviews and separately verified fixes. Do not mark a unit/chunk verified from workers' claims. Workers do not execute checks/formatters/smoke/commits. Each row owns at most five explicit paths; there is no overlap. No implicit directory/glob ownership.

| Unit / exclusive owner | Exact owned paths | Bounded responsibility / dependencies |
|---|---|---|
| S1 identity/storage owner | `src/cli_usage_api/domain.py`; `src/cli_usage_api/storage.py`; `tests/test_domain.py`; `tests/test_storage.py` | Freeze IDs/read allowlists/ResolvedCredential field and the two migration callables, narrow legacy detection and atomic safe migration; first shared prerequisite |
| S2 resolver owner | `src/cli_usage_api/credentials.py`; `tests/test_credentials.py` | After S1 identity contract, secure explicit Codex file branch/account selection/JWT hints; no generic Grok fallback, no real files |
| W wire/provider owner | `src/cli_usage_api/transport.py`; `src/cli_usage_api/providers/codex.py`; `src/cli_usage_api/providers/chatgpt.py` (delete); `src/cli_usage_api/providers/base.py`; `src/cli_usage_api/providers/__init__.py` | After S1, implement exact route/headers/parser, delete old provider/export/registry; S2 needed only for integrated smoke, not editing |
| T wire/security test owner | `tests/test_transport.py`; `tests/test_security.py`; `tests/test_capabilities.py`; `tests/test_codex.py` (new) | After S1 contract, develop synthetic contract tests alongside W; replace no-WHAM/blocked assumptions, assert exact request and duration/pool/reset/absence behavior |
| U account/CLI owner | `src/cli_usage_api/accounts.py`; `src/cli_usage_api/cli.py`; `tests/test_accounts_ui.py`; `tests/test_account_flows.py`; `tests/test_cli.py` | After S1 callables, replace choices/guidance/reconnect, add explicit migration CLI and safe TUI error instruction; prove file-only Codex and no old-secret operations |
| V dashboard/scheduler-test owner | `src/cli_usage_api/app.py`; `tests/test_app.py`; `tests/test_rendering.py`; `tests/test_scheduler.py` | After S1, required weekly/optional-extra labels/details and Codex poll/resolve/refresh/stale/stop tests; remove old credential-free scheduling assertions |
| D synthetic/PTY owner | `src/cli_usage_api/demo.py`; `src/cli_usage_api/fixtures/demo.json`; `scripts/tui_smoke.py`; `tests/test_demo.py`; `tests/test_smoke_harness.py` | After S1, synthetic Codex weekly plus optional reported extras; keep demo isolation; installed-entry harness checks Codex labels, not old ChatGPT token |
| R documentation/acceptance owner | `README.md`; `SECURITY.md`; `CHANGELOG.md`; `AGENTS.md`; `PLAN.md` | After contracts and alongside implementation, own all active-scope reconciliation, Unreleased entry, repo-root Lessons and final proof/status ledger; preserve historical claims as historical, never rewrite old test results |

Intentionally unchanged production paths: `src/cli_usage_api/scheduler.py` (generic credentialed path), `src/cli_usage_api/providers/claude.py`, `src/cli_usage_api/providers/console.py`, `src/cli_usage_api/providers/grok.py`, `src/cli_usage_api/app.tcss`, `src/cli_usage_api/__main__.py`; unrelated provider tests and dependency/lock/package files have no established cutover change. Any discovered necessary change first receives explicit nonoverlapping ownership in this appendix; do not invent an adjacent refactor. R reconciles active scope/provider tables/security headers/credential setup/CLI/help examples/demo labels and removes stale current “ordinary ChatGPT remains blocked” claims, including old manual commands in this plan; historical C07 evidence stays truthful. Root Lessons must capture duration-not-position, explicit transport branch, unverified-JWT limits and consent/detached-secret migration.

### 11.6 Integrated gate specification, smoke and live boundary

The following are the integrated orchestrator command specification, not worker commands. Supplied exercised outcomes and any unrecorded command evidence are distinguished in §11.7; do not infer execution merely from this list:

```sh
uv sync --locked --group dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run usage --help
uv run usage accounts list
uv run python scripts/tui_smoke.py --scenario healthy
uv run python scripts/tui_smoke.py --scenario errors
```

Use isolated temporary HOME/XDG/CODEX_HOME for account commands and synthetic smoke; never inherit a real Codex login. Workers supply exact runnable throwaway component/PTY snippets with bounded waits, assertions, cleanup and nonzero failure, outside pytest; main executes them only after integration. Required proof:

1. Private synthetic `CODEX_HOME/auth.json` -> real CredentialResolver -> real CodexProvider -> real Transport with injected `httpx.MockTransport`. Assert exactly one GET, fixed URL, Bearer/selected-account header and absence of all Grok/cookie/refresh/API-key leakage. Use slot-swapped 604800/18000 windows, weekly-only primary, 300s/3600s and feature-pool examples; missing/invalid/duplicate/conflicting siblings, overage, canonical epoch reset, ignored relative-reset fallback, expiry/API-key/cross-provider failures and redacted diagnostics. Print only assertion summaries; no request/auth/claim dumps.
2. Real AccountStore synthetic mixed legacy config and fake keyring with forbidden get/delete. Exercise callable and real installed CLI in a PTY: decline/cancel/non-TTY unchanged; affirmative complete-set migration retains nonlegacy records and original backend entries, detaches/disables Codex profiles, then normal file-backed edit/reconnect works. Preserve local identity and atomic/durability behavior; old CLI provider spelling is rejected. No real keyring proof claimed.
3. Actual Scheduler with deterministic clock and resolved synthetic Codex credential: initial poll, manual refresh, at least two scheduled intervals, same-origin spacing/server retry embargo, last-good/stale failure, account replacement/removal and stop/no later publication. This is offline scheduling evidence, not permitted live polling proof.
4. **Real installed-entry POSIX PTY**, not Pilot alone: healthy/errors harness each exercises normal `x` -> `q` and Ctrl-C (four actual runs), Codex weekly and optional reported extra visible with DEMO/provenance, detail/help, account-manager read-only demo return, refresh, 80x24 -> 40x12 resize, exit status and terminal restoration. Account CLI migration/file-only setup requires separate synthetic real-PTY flow; demo must not instantiate live resolver/transport/storage. Also open isolated no-credential `usage` and account dialog, observe safe empty/unconfigured state and cleanup. No browser or permanent throwaway host/transcript.

Record exact commands/outcomes, terminal observations, independent planning and implementation review dispositions, any separately verified fixes and docs/Lessons disposition here. Old 851-test/PTY results do not satisfy these gates. Resource rules in §10 still apply; no browser is needed or authorized.

Acceptance replacement: old §9's ordinary-ChatGPT **code** task is replaced by “Codex weekly end-to-end file-backed adapter, explicit migration, fixtures/tests/UI/docs and integrated proof above”; **implemented and integrated-verified**, not upstream-blocked. Its **live** task is “locally authorized file-backed Codex login, selected account/plan, successful permitted WHAM read, compare weekly utilization/reset against same-account first-party Codex usage UI at the same observation”; **unchecked/unexercised**. Missing weekly response stays unknown and cannot be accepted from 5h/pool/demo. Optional windows are accepted only for the account/reporting behavior observed, not new universal mandatory requirements. All non-GPT live prerequisites remain open; account-import acceptance now includes Codex file-backed import where claimed. No real auth file, token, account ID or raw response is requested through chat or recorded. Keyring-only Codex auth is unsupported by design, not a successful import. Server-side/private-contract compatibility and first-party UI agreement remain unproven until separately authorized local observation; static sources, synthetic fixtures, PTY and a green suite cannot prove them.

### 11.7 Atomic-cutover progress and proof ledger

Only supplied/exercised evidence is recorded. All eight unit checkboxes record
implementation plus integrated orchestrator verification. Draft, review, final gate
and scoped lifecycle closure are separately backed below; no live success is implied.

- [x] Independent planning reviews: `agent://codex-plan-review-1` and
  `agent://codex-plan-review-2` clean; reviewed planning commit `e3190b9` exists.
- [x] S1 identities/storage: shared contracts and narrow complete-set migration.
- [x] S2 resolver: file-only selection, account binding and JWT hints.
- [x] W wire/provider: fixed read/auth, duration/pool parser and clean registry cutover.
- [x] T synthetic wire/security/capability/parser coverage; integrated suite passed.
- [x] U account/CLI: file-only setup, explicit migration and safe reconnect guidance.
- [x] V dashboard/scheduler tests: weekly/optional extras and credentialed lifecycle.
- [x] D demo/installed-entry PTY: synthetic Codex and isolated terminal harness.
- [x] R docs/security/Lessons/acceptance: active README/SECURITY/CHANGELOG/AGENTS
  reconciliation landed; current ledger separates verified code from live acceptance.
- [x] Orchestrator post-cleanup integrated pytest/Ruff gate and all 17 source-file
  LSP diagnostics clean. No separate successful LSP references-query evidence supplied.
- [x] Synthetic auth/resolver/provider/transport, corrected Scheduler, offline demo,
  migration/file-only installed CLI and installed-entry real-PTY proof.
- [x] Green draft commit: `2d7ea6b`, following reviewed planning commit `e3190b9`.
- [x] Independent implementation reviews: `agent://codex-cutover-review-1`,
  `agent://codex-cutover-review-2`, `agent://codex-cutover-review-3` and
  `agent://codex-cutover-review-4` clean; no review fixes required.
- [x] Final split reviews: `agent://codex-final-split-review-1` and
  `agent://codex-final-split-review-2` clean; no fixes required.
- [x] Final orchestrator gate: locked dev sync passed; 1098 tests in 30.20s;
  Ruff check passed; 44 files already formatted. Earlier 17-source LSP clean
  evidence remains applicable: source unchanged since that diagnostic check.
- [x] Atomic-cutover scoped implementation/verification/docs/review closure recorded
  at green draft `2d7ea6b`; final tracker-snapshot commit follows, hash not yet known.
- [ ] Live Codex acceptance: locally authorized existing file-backed Codex login,
  explicit selected account/plan, successful permitted WHAM read and weekly
  utilization/reset comparison with that same account's first-party Codex usage UI
  at the same observation. This prerequisite is unavailable/unexercised, **not an
  upstream-contract blocker**; no credentials are requested through chat.

#### Exact supplied integrated gate outcomes

| Command / surface | Supplied exercised outcome and boundary |
|---|---|
| Initial `uv run pytest -q` / Ruff check | **2 failed, 1085 passed in 30.83s**; **2 lint findings**. API-key UI fixture used an invalid Codex source; duplicate weekly usage conflict needed planned recognized-identity `UNKNOWN`/`PARTIAL` behavior rather than `SCHEMA_ERROR`. Corrections landed; this is historical failure evidence, not the current gate |
| Pre-cleanup `uv run pytest -q` | **1099 passed in 29.01s**; superseded by the post-cleanup result below, not evidence for later edits |
| Pre-cleanup `uv run ruff check .` / `uv run ruff format --check .` | Passed / **44 files already formatted**; historical pre-cleanup result |
| Post-cleanup `uv run pytest -q` before final gate | **1098 passed in 28.59s**. One obsolete capability test was removed; historical intermediate result, superseded for final gate by 30.20s below |
| Final `uv run pytest -q` | **1098 passed in 30.20s** |
| Final `uv run ruff check .` / `uv run ruff format --check .` | **All checks passed** / **44 files already formatted** |
| Source LSP diagnostics | **All 17 source-file diagnostics clean** at the earlier orchestrator check; source unchanged since. No separate references-query success claimed |
| Installed `usage --help` | Passed; no fabricated wrapper/options |
| `uv run python scripts/tui_smoke.py --scenario healthy` and `uv run python scripts/tui_smoke.py --scenario errors` | Four installed-entry real-PTY healthy/errors runs passed: normal `x` -> `q` and Ctrl-C; rendered metrics and terminal restoration true |
| Final `uv sync --locked --group dev` / isolated installed `usage accounts list` | Locked dev sync passed; isolated installed accounts list exited **0**, no accounts. No real login or keyring used |

#### Supplied actual offline component and terminal proof

- Synthetic private auth-file selection through actual CredentialResolver ->
  CodexProvider -> Transport smoke passed, using synthetic credentials/injected
  transport only; no real login, upstream request, network or keyring access.
- Actual Scheduler artifact `local://codex-scheduler-smoke.py` passed after its
  optional 5h fixture gained the missing reset. The earlier partial-state assertion
  was a fixture-only error, not an established product bug. Corrected proof covers
  initial poll, manual refresh, two scheduled intervals, retry embargo/spacing,
  last-good/stale state, replacement/removal and stop/no later publication.
- Actual offline DemoSource proof passed: **4 healthy / 8 errors snapshots**, with
  live dependencies forbidden. Synthetic/demo proof is not authenticated acceptance.
- Installed CLI real-PTY artifact `local://codex-migration-smoke.py` passed with
  synthetic mixed configs: decline/cancel/non-TTY unchanged, affirmative complete-set
  migration, retained nonlegacy records/old backend entries, detached/disabled Codex
  profiles, file-backed edit/reconnect and enable/disable toggle. Isolated no-credential
  live-mode empty-state/account dialogs also passed; no real import/keyring claim.
- All four installed-entry healthy/errors real-PTY runs passed, including Codex
  weekly/optional-extra rendering, DEMO/provenance, detail/help, account-manager return,
  refresh, resize, normal quit/Ctrl-C and restored terminal state.

#### Landed unit reports and cleanup disposition

S1 reports frozen identities, redacted Codex-only selected-account field and both
narrow migration callables; old secrets remain untouched by CredentialStore and
committed-write warnings remain truthful. S2 reports file-only resolver/defaults,
absent-only selected-ID fallback and JWT expiry hints. W reports `CodexProvider`,
explicit fixed transport/header branch and duration/reset/pool parser, with obsolete
provider/module/export removed. T reports synthetic wire/security/capability/parser
coverage. U reports file-only choices/guidance, migration before ordinary load or
CredentialStore construction, whole-set TTY consent, committed-durability warnings
and actionable TUI migration instruction. V reports weekly (7d)/5h labels,
synthetic/non-live banner, seven-day/non-calendar-week help and distinct nonadditive
optional pools/windows; production Scheduler unchanged. D reports four healthy/eight
error fictional accounts, weekly plus optional 5h (healthy rows 10 -> 11), required-
before-extra inventory and CODEX_HOME-isolated harness. R reports active README,
SECURITY, CHANGELOG and repo-root AGENTS Lessons reconciliation. All eight bounded
unit reports landed; the integrated evidence above, not those reports alone,
establishes their checked implementation/verification status. Workers ran no checks.

Provider-neutral diagnostic cleanup and obsolete capability-test removal landed.
The final **1098-test / 30.20s / Ruff / 44-file format** gate is green; earlier
**17-source diagnostics** remain clean with source unchanged since that check.
No component-proof failure remains open. Green draft `2d7ea6b`, four clean
implementation reviews and two clean final split reviews close this atomic chunk
for implementation, verification and documentation/Lessons. No fixes were required.
Only commit of this completed tracker snapshot remains runnable; no final hash is
invented. Historical 851-test evidence remains pre-Codex only. No real Codex auth
files, user secrets, network, keyring, authenticated metric comparison or other-
provider live success was used or claimed.

### 11.8 Exact remaining current-scope acceptance and final closeout

**12 current unchecked acceptance items remain: one Codex live prerequisite and
11 retained non-Codex/live-integration prerequisites from the historical §9 matrix.**
There are **zero unchecked current implementation, documentation, review or gate
tasks**. The two old ordinary-ChatGPT code/live cells remain visibly unchecked only
as historical records: §11 explicitly supersedes both; neither is an active blocker,
and neither is falsely marked done. Thus the document retains 14 literal unchecked
checkboxes (13 historical matrix cells plus the current Codex live checkbox), but
only the following 12 are applicable to current scope. Quoted wording is verbatim;
retained historical checks are not marked complete by offline or synthetic proof.

| Requirement | Exact remaining unchecked wording | Concrete prerequisite, not implementation work |
|---|---|---|
| Codex / live | “Live Codex acceptance: locally authorized existing file-backed Codex login, explicit selected account/plan, successful permitted WHAM read and weekly utilization/reset comparison with that same account's first-party Codex usage UI at the same observation. This prerequisite is unavailable/unexercised, **not an upstream-contract blocker**; no credentials are requested through chat.” | Locally authorized existing file-backed Codex login, selected identity/eligible plan, normal TUI account configuration, permission for the read and corresponding same-account first-party UI observation. Keyring-only auth is unsupported, not a completed import |
| Claude 5h / retained live | “Eligible credential; compare used/remaining/reset” | Locally authorized eligible Claude Code login or supported bearer/profile-read scope, private reference and matching first-party UI observation |
| Claude weekly / retained live | “Same account/window matches first-party UI” | Same authorized eligible Claude account and corresponding weekly first-party UI observation |
| Claude Fable / retained live | “Eligible plan returns validated scoped data; otherwise plan-specific unavailable recorded, not global completion” | Authorized eligible plan/seat and positively identified scoped response, or positive plan-specific exclusion evidence; absence alone is insufficient |
| Platform purchased / retained live | “Selected org session returns purchased array; compare billing balance” | Authorized local Console session, selected billing-readable organization, purchased-array/explicit-empty evidence and matching billing UI |
| Platform promotional / retained live | “Selected org returns promo array/explicit empty; compare included/promotional billing grants” | Authorized local Console session/selected billing-readable organization, promo-array/explicit-empty evidence and corresponding grant UI; no subtraction inference |
| Grok aggregate / retained live | “Logged-in direct proxy matches account period/pool” | Authorized eligible Grok file login with selected scope/profile or supported bearer, billing permission, observed period/pool and same-account UI |
| GrokBuild / retained live | “Actual product share and pool relationship observed” | Authorized selected Grok account and same-payload validated Build share/established pool relationship with first-party comparison |
| GrokChat / retained live | “Actual product share and pool relationship observed” | Authorized selected Grok account and independent same-payload validated Chat share/established pool relationship with first-party comparison |
| Accounts/keys / retained integration | “Actual secure keyring save/replace/delete or clearly session-only; external login import exercised” | Authorized available/unlocked supported encrypted backend or explicit session-only choice, plus authorized local external-login import with selected account/scope; now includes Codex file-backed import where claimed. Synthetic CRUD/import does not complete real integration |
| Poll/stale/error / retained live | “Poll over at least two intervals without rate-limit bypass; last-known errors visibly stale” | Authorized configured live account and permitted observation across two real intervals with observed error/stale state, preserving retry deadlines; never deliberately provoke rate limiting |
| Secret safety / retained integration | “No raw live captures; local keyring backend supported” | Authorized local supported encrypted-backend availability/unlock and secret lifecycle observation without raw secret captures; no real backend success yet claimed |

**All-chunk close:** historical C01–C14 and `d653397` retain their scoped closures;
the one §11 atomic Codex chunk (S1/S2/W/T/U/V/D/R) is now closed for code,
integrated verification, docs/changelog/security/Lessons and independent review at
green draft `2d7ea6b`. Four implementation and two final split reviews were clean;
no fixes required. Final gate and actual offline component/installed terminal proof
are recorded in §11.7. No newly doable implementation task, review, gate, smoke or
documentation work remains. Only committing this completed tracker snapshot is
runnable; its final hash is not yet known and is not fabricated.

**Next user action:** configure/authorize an existing file-backed Codex login
externally, select its private file reference and account in normal TUI
configuration, then authorize a read and same-account Codex usage UI comparison.
Do not send tokens, auth files, account IDs, raw responses or other secrets through
chat. The 12 unchecked items require concrete local authorization, eligible
account/plan/UI evidence or user backend/configuration, not an ordinary-ChatGPT
upstream-contract repair. No authenticated or real-keyring success is claimed.

## 12. User-requested provider maintenance — 2026-10-29

### Scope and findings

- **Codex:** remove `plan_type`, `allowed`, and `limit_reached` from dashboard
  and detail output. Weekly/5h/extra-pool values, reset semantics and provenance
  remain unchanged. No credential or transport change for Codex.
- **Claude subscription:** code inspection found one usage GET per account fetch
  covering all three windows, not a duplicate request per metric or internal
  transport retry loop. Previous default/saved 60s accounts polled every 54–66s;
  a no-header 429 started retrying after about 60s. Effective automatic cadence is
  now at least 180s (180–198s at the floor), retaining longer saved preferences,
  with aligned freshness. Claude 429 cooldown starts at 180s and grows to 360/720/900s
  plus jitter; longer settings/server embargoes win. Manual refresh remains an
  explicit earlier read, never an embargo bypass. Config files are not rewritten.
  Multiple connections/processes or first-party clients may also contribute traffic;
  no upstream threshold or exact live root cause was established.
  This reflects the subsequent three-minute request (§12.1); the initial five-minute
  implementation's exercised evidence below remains historical and unchanged.
- **Grok:** the old parser rejected an omitted aggregate even with a valid weekly
  period/reset and rejected product breakdowns that did not sum within one point
  of aggregate. BYOS supplies concrete counterexamples. Recognize omitted scalar
  zeros only in explicit valid weekly context; explicit null/invalid values, missing
  products and arbitrary empty config remain unknown/errors. Validate the entire
  product array and preserve exact decimals, but remove the unsupported sum gate.
  Shared remaining/reset still requires `isUnifiedBillingUser == true`.
  Add a sourced compatibility-version header without impersonating the official
  User-Agent. No response capture from the user's account was inspected, so these
  are sourced compatibility repairs, not proof of the exact reported live failure.

### Research provenance

- Local read-only reference: `../../Recursive-Self-Improving/byos` at revision
  `7d94261238e7690d19e5384696a5369f20446e5f`.
  `internal/usage/xai_billing.go:106–140` recognizes omitted aggregate zero with
  weekly/reset context; `:148–193` handles omitted product percentages. Its
  permissive null/skipping/first-duplicate behavior was deliberately not copied.
  `internal/usage/weekly_products_test.go:20–31` uses aggregate 40 and products
  12.5 + 0 + 3: source evidence against imposing sum equality.
  `internal/xai/headers.go:31–39`, `internal/config/config.go:34–36`, and
  `docs/providers.md:23–40` supply version-header precedent (BYOS pin 1.0.46).
- The [official stable feed](https://x.ai/cli/stable), retrieved without auth,
  returned **1.0.70**; this release pins that value, with no runtime feed request.
  The [documented HTTP426 incident](https://github.com/router-for-me/CLIProxyAPI/issues/6249)
  concerns an inference version floor, not proof this user's billing request was
  version-rejected.
- The [official Grok FAQ](https://docs.x.ai/grok/faq#usage--limits) confirms a shared
  weekly pool and product breakdown. It does **not** explicitly promise non-additive
  percentages; removing the sum check follows BYOS evidence and the absence of a
  documented sum invariant, not a stronger claim about that FAQ.

### Exercised evidence and boundaries

- Actual CodexProvider → Transport → mounted UsageApp/Pilot with synthetic HTTP:
  weekly 37.5%, 5h 12.5%, extra pool 105%; all three detail screens retain provenance
  and omit the requested metadata. The first throwaway harness omitted mandatory
  selected-account data and was corrected; no production credential contract changed.
- Actual Scheduler → ClaudeProvider → Transport, virtual monotonic time, synthetic
  HTTP: request starts `[0, 300, 600, 605, 905, 1505, 3305, 3605]`; three windows per
  request, negative-jitter floor, 300/600s 429 cooldown, 1800s server embargo through
  manual refresh/account replacement, last-known timestamps, freshness and recovery
  all passed. The 605s read was the explicit manual refresh, not automatic polling.
- Actual GrokProvider → Transport → mounted UsageApp/Pilot, seven synthetic reads:
  omitted weekly zero with/without unified evidence, explicit-null/bad-reset rejection,
  duplicate-array rejection without losing aggregate, exact raw numeric precision,
  aggregate 40% versus Build 10% / Chat 5.5%, shared remaining 60% without invented
  per-product remaining, and all three selectable detail/provenance screens passed.
- `uv run --locked python scripts/tui_smoke.py`: all four installed-entry runs
  (healthy/errors × normal quit/Ctrl-C) rendered metrics and restored terminals.
  HOME/XDG were isolated; no authenticated request or real credential/keyring read.
- Initial full gate: 8 failed / 1162 passed; five new freshness fixtures omitted the
  required injected factory, and three generic jitter cases still used Claude's old
  cadence. Corrected the fixtures to mounted UI checks and kept generic jitter
  assertions on unchanged Grok cadence. A lint-only conditional and formatting were
  also corrected. Targeted cadence/freshness rerun: **73 passed in 5.05s**.
- Integrated `uv run --locked pytest -q`: **1170 passed in 53.25s** after those
  fixture corrections. A final CLI-only presentation integration then changed
  `accounts list` to show effective rather than saved cadence; its targeted suite
  passed **57 tests in 0.31s**, followed by clean full Ruff lint/45-file format checks
  and clean CLI LSP diagnostics. The installed CLI, using isolated HOME/XDG and
  synthetic saved accounts, showed **300s / 900s / 60s** for default Claude, longer
  Claude and unchanged Grok while reloading the original saved accounts unchanged.
- Ruff lint passed; formatting check passed for **45 files**; Ruff LSP diagnostics
  were clean for all **17 source files**. No new independent review or commit is
  claimed. README/CHANGELOG/SECURITY and repo-root Lessons reflect the bounded change.

The earlier §11 live acceptance items remain unfulfilled by these synthetic checks.
The user's reported Claude/Grok failures are accepted observations, not rerun against
their credentials. Restart the dashboard to load the repair; actual account success
and its upstream limit still require an authorized same-account observation.

### 12.1 Subsequent user request — three-minute Claude cadence

The user explicitly lowered both normal automatic querying and initial rate-limit
retry waiting from five to three minutes. Claude subscription now uses
`max(180, saved_interval)` without rewriting configuration, with automatic jitter
clamped to the floor (180–198s for default accounts). No-header 429 retries grow
180 → 360 → 720 → 900 seconds, then remain capped before jitter; longer configured
intervals and server deadlines still win. The bounded exponent was adjusted so
the lower base still reaches the 900s cap. Manual refresh, immediate startup,
other providers, origin spacing and generation/embargo protection are unchanged.

Exercised with synthetic credentials/responses, never real account requests:
- Actual Scheduler → ClaudeProvider → Transport request starts:
  `[0, 180, 360, 365, 545, 905, 2705, 2885]`. Normal 180s cadence, first/second
  180/360s 429 waits, longer 1800s server embargo across manual refresh/account
  replacement, last-known values and recovery passed; 365s was manual refresh.
- Actual installed `usage accounts list` under isolated HOME/XDG showed
  180s / 900s / 60s for default Claude, longer-configured Claude and unchanged Grok;
  saved account metadata reloaded unchanged.
- Actual mounted UsageApp/Pilot retained 23.5% used / 76.5% remaining, showed fresh
  at observation ages 121s and 360s, then STALE at 361s in the header and details.
  This follows the effective interval's doubled freshness threshold; presentation
  ticks made no additional request.
- The initial integrated run had 1 failure / 1170 passes: the initial-poll
  monotonic-clock test still waited for the old 299s boundary. Its assertion now
  exercises 179s-before / 180s-due; no production workaround was introduced.
- Domain and scheduler Ruff LSP diagnostics were clean. README, CHANGELOG,
  SECURITY, active PLAN contracts and repo-root Lessons were synchronized. Prior
  five-minute proof above is preserved, not relabeled as three-minute evidence.
- Final integrated gate: `uv run --locked pytest -q` passed **1171 tests in
  50.17s**; `uv run --locked ruff check .` passed and
  `uv run --locked ruff format --check .` passed for **45 files**.
  These checks cover the updated initial retry, exponential cap, negative jitter,
  longer settings/server embargoes and actual dashboard freshness boundaries.

## 13. User-requested default and remembered theme — 2026-10-29

The user requested Nord as the initial theme, asked which information persists,
then requested restoring the last selected theme after restart. Account metadata
remains in `accounts.json`; manual persistent secrets remain in the secure keyring,
session-only secrets remain process-local, and external logins remain file references.
No actual user configuration or credentials were inspected for this work.

Implemented:
- `UsageApp` defaults to `nord`, restores a valid saved selection before mount, and
  saves subsequent theme changes from the existing Ctrl-P → Theme command palette.
  Startup/cancellation do not rewrite the preference. A watcher registered with
  `init=False` avoids saving initialization instead of user choice.
- `SettingsStore` stores only schema version and theme in
  `$XDG_CONFIG_HOME/cli-usage-api/settings.json`, falling back to
  `~/.config/cli-usage-api/settings.json`. Shared private file primitives retain the
  existing stable-lock, no-symlink, bounded-read, `0700` directory / `0600` file,
  atomic replacement and fsync policy. Account committed-write error semantics
  remain intact; account schema and secret references are unchanged.
- CLI live/demo modes share UI preferences without giving demo access to account
  stores, resolvers, keyrings or providers. Embedded apps may explicitly inject a
  settings store; omission keeps preference I/O disabled.
- Unavailable themes and unreadable/invalid preferences warn and use Nord without
  rewriting settings. Save failures warn while retaining the chosen in-memory theme;
  malformed configuration is not silently repaired or claimed saved.
- README/CHANGELOG/SECURITY and repo-root Lessons document the bounded change.
  The CLI demo-isolation regression now constructs and mounts the real app instead
  of asserting copied constructor kwargs.

Exercised evidence:
- Initial installed-entry demo and empty-live PTYs rendered the Nord surface
  (`#3B4252`), opened help, quit normally and restored terminals. The first probe
  incorrectly expected the theme's background color; the existing stylesheet uses
  `$surface`, and the corrected actual ANSI-color assertion passed.
- Actual mounted UsageApp/Pilot with isolated real settings files: demo selection
  restored in a fresh live app; subsequent changes persisted; startup did not create
  a default settings file; synthetic accounts stayed byte-for-byte unchanged;
  private permissions, unknown-theme fallback, invalid-JSON warnings and failed-save
  warnings passed without crashing or rewriting invalid settings.
- Three fresh installed-entry PTYs sharing isolated HOME/XDG exercised the actual
  command palette: demo Nord → Dracula; restart live restored Dracula → Nord;
  restart demo restored Nord. Palette cancellation kept saved bytes unchanged;
  synthetic disabled-account configuration was unchanged, both normal quit and
  Ctrl-C exited cleanly, and every terminal was restored.
- `uv run --locked pytest -q tests/test_storage.py tests/test_account_flows.py
  tests/test_cli.py tests/test_secret_store.py`: **172 passed in 1.82s**. These include
  account atomic-write/committed-fsync and credential rollback regressions.
- `uv run --locked ruff check .` passed. The initial format check requested one
  warning-string wrap; after correction, `uv run --locked ruff format --check .`
  passed with **45 files already formatted**.
- Ruff LSP diagnostics were clean for app, CLI and storage. No full-suite rerun,
  independent review, authenticated provider request or real-keyring check is claimed.

## 14. User-requested Console balance mismatch warning — 2026-10-29

The user supplied redacted debug output showing a successful credits response,
three ready balances, and a one-minor-unit discrepancy between total and category
sums. Earlier local replay reproduced `partial_data`; changing only the reported
total to match the categories yielded `ok`. The discrepancy was already present
in the response, not introduced by local floating-point arithmetic. Its upstream
cause is unverified. No credentials, raw responses, or account identifiers are
recorded here.

Implemented at the user's request:
- Separate complete-but-mismatched balances from missing/invalid observations:
  `fetch_state=ok`, `diagnostic=balance_mismatch`, with a curated Chinese warning
  in the existing dashboard diagnostic surface. No new fetch state or schema field.
- Preserve the authoritative total and independently calculated categories. The
  total detail reports the signed difference (total minus category sums), formatted
  through `Money` in the validated currency/exponent. No tolerance, rounding, or
  subtraction to manufacture a missing category is introduced.
- Missing/invalid amounts and uncertain expiry still produce `partial_data` when
  any usable balance remains; wholly unusable responses retain `schema_error`.
  These diagnostics take precedence over the advisory, while a calculable mismatch
  remains in total-balance details. Scheduler freshness and retry policy are unchanged.
- Updated behavior regressions, README, CHANGELOG, active §4.2, and repository Lessons.

Exercised evidence:
- `uv run --locked pytest -q tests/test_console.py tests/test_domain.py
  tests/test_scheduler.py tests/test_freshness.py tests/test_debuglog.py`:
  **331 passed in 7.18s**. Coverage includes positive one-minor-unit differences,
  negative differences/negative totals, nondefault units, original amount retention,
  and partial-diagnostic precedence when expiry is unknown.
- `uv run --locked ruff check src/cli_usage_api/domain.py
  src/cli_usage_api/providers/console.py tests/test_console.py`: passed;
  corresponding `ruff format --check` passed for **3 files**.
  Ruff LSP diagnostics were clean for domain and Console provider. This server
  does not implement definition/reference navigation; scoped searches were used
  after those requests returned method-not-supported errors.
- Two real-PTY component hosts exercised actual `Scheduler -> ConsoleProvider ->
  Transport -> UsageApp` with an in-memory HTTP response, synthetic credential
  resolver, fixed observation time, and isolated HOME/XDG. Complete mismatched
  balances rendered normal status plus the separate warning, not partial data;
  adding unknown expiry retained partial data. Both preserved all three amounts,
  opened total details showing the exact difference, resized 80x24 -> 56x24, and
  exited (normal `q` / Ctrl-C) with terminal restoration. Snapshot serialization
  round-tripped the new diagnostic without altering values.
- Initial throwaway host startup failed because an inline `python -c` subclass
  has no source path for Textual's inherited stylesheet lookup. Instantiating the
  production `UsageApp` directly with an injected fixed clock corrected the host;
  no application fix was needed. Temporary homes and owned children were cleaned
  on both failed and successful runs; no smoke script was saved in the repository.
- This is local replay/component-PTY evidence, not an installed-entry live request,
  billing-UI comparison, real-keyring check, full-suite rerun, or independent review.


## 15. User-requested read-only API, web frontend and Railway deployment — 2026-10-29

User request (translated): besides the TUI, provide a **read-only** HTTP API for
viewing usage data only (no account management), started from a command-line
option; a separated web frontend deployable to Railway / Vercel / Cloudflare with a
"One True SaaS Layout" (left rail, sidebar list, tabs, main content with three
cards and a callout, right summary bar, bottom status bar); mandatory
authentication so nobody can view data without a credential; and a backend that
runs locally and on Railway from a Dockerfile installing the environment plus
Claude Code, Codex CLI and Grok Build CLI, idling on `sleep infinity` so the user
can shell in, log in manually, configure accounts and start API mode by hand.

### 15.1 Scope and units

| Unit | Owned paths | Status |
|---|---|---|
| Backend API | `src/cli_usage_api/api.py`, CLI wiring in `cli.py`, `ApiTokenStore` in `storage.py`, `tests/`, `pyproject.toml`/`uv.lock` (Starlette + uvicorn) | Implementation landed in the working tree; gates/review pending verification |
| Web frontend | `web/` (Vite + React 18 + TypeScript, deploy configs for Vercel, Cloudflare Pages/Workers, Railway) | Implementation landed in the working tree; build/lint/browser verification pending |
| Deploy + docs | `Dockerfile`, `.dockerignore`, `railway.json`, `docker/entrypoint.sh`, `docs/deploy-railway.md`, README/SECURITY/CHANGELOG, this section | Landed; local image build and container smoke exercised (§15.4); Railway pending |

Out of scope: any HTTP mutation of accounts, credentials, tokens or configuration;
token refresh of first-party logins; live/authenticated provider acceptance.

### 15.2 Frozen contract summary

- CLI: `usage api serve [--host 127.0.0.1] [--port 8787] [--allow-origin ORIGIN ...]
  [--demo [--scenario healthy|errors]] [--trust-proxy] [--debug-log PATH
  [--debug-provider P ...]]` — headless; exact http(s) origins only (normalized, no
  wildcard/path); invalid input is a curated exit-2 error. Live mode reuses
  `LiveFactory` (store, resolver, transport, providers, scheduler) and keeps the
  latest snapshot per account in memory; `--demo` branches before constructing any
  live dependency and rejects `--debug-log`. Account config is read once at startup.
  SIGINT/SIGTERM stop the scheduler and exit 0.
- Tokens: `usage api token create [--label]` (TTY; `usk_` + `token_urlsafe(32)`,
  printed once), `list` (no hashes), `revoke ID` (TTY confirm). `ApiTokenStore`
  stores `{id, label, sha256, created_at}` in private, locked, atomic
  `api_tokens.json` beside `accounts.json`; the server reloads on mtime change
  (≤ 1 stat/s). Live serve refuses to start without tokens; loopback demo (`localhost`
  binds `127.0.0.1`) may run
  unauthenticated only while none exist.
- HTTP: `GET`/`HEAD`/`OPTIONS` only (`405` otherwise); bearer header auth only,
  `hmac.compare_digest` over all hashes, `401` + `WWW-Authenticate: Bearer`;
  valid tokens bypass the limiter; failed-auth limits 10/60 s per client and 100/60 s
  global → `429` + `Retry-After` (exposed cross-origin);
  client key is the peer address, or the right-most `X-Forwarded-For` entry with
  `--trust-proxy`; bounded tracking (10k). Exact-origin CORS, never `*` or
  credentials; preflight `204`/`403 forbidden_origin`. Security headers on every
  response (`no-store`, `nosniff`, `no-referrer`, `DENY`, `default-src 'none';
  frame-ancestors 'none'`). Error bodies are fixed `{"error": code}`.
- Endpoints: `/healthz` (public), `/api/v1/session`, `/api/v1/dashboard`,
  `/api/v1/accounts/{id}`. AccountView omits credential references/selectors and
  organization IDs; `snapshot` is `Snapshot.to_dict()` with `organization_id`
  nulled; disabled accounts carry `snapshot: null`.
- Frontend renders domain semantics faithfully: unknown is not zero, Grok
  `share_percent` is consumption only, balance-mismatch diagnostics remain visible,
  numbers are never truncated. Token in session/local storage per explicit choice,
  never in URLs; any `401` returns to login.
- Container (hardened inputs in §16): digest-pinned Python 3.12.15 and uv 0.13.5,
  Node.js 22.23.4 (SHA-256 verified), Claude Code 2.1.308 and Codex 0.165.0
  (integrity-locked npm, no install hooks), Grok Build 1.0.70 (TOFU SHA-256), project via
  `uv sync --locked --no-dev`; `HOME=/data/home` (`0700`, created by the entrypoint
  under `tini`); `CMD ["sleep","infinity"]`. Only file-backed Claude Code, Codex and
  Grok logins work (no OS keyring); Claude Platform is unsupported in the container.
- Amended by §18 (2026-10-29): for live servers without `--read-only`, "GET/HEAD/OPTIONS
  only", "Out of scope: any HTTP mutation of accounts" and "Account config is read once
  at startup" are superseded; the read-only contract above still holds for `--read-only`
  and demo.

### 15.3 Research sources (2026-10-29)

Recorded with URLs in `docs/deploy-railway.md`. Key findings: Grok's official
installer is `curl -fsSL https://x.ai/cli/install.sh | bash [-s VERSION]`, installs
to `$HOME/.grok/bin`, stable pointer `https://x.ai/cli/stable` read `1.0.70`;
`grok login --device-auth` for headless hosts; `GROK_HOME` defaults to `~/.grok`;
`GROK_DISABLE_AUTOUPDATER` suppresses updates. Claude Code's npm package installs
the same native binary as the native installer; `DISABLE_AUTOUPDATER=1` stops
background updates. Codex `codex login --device-auth`; `cli_auth_credentials_store
= "file"` stores `auth.json` under `CODEX_HOME` (default `~/.codex`). Railway mounts
volumes as root at runtime only (never at build), one volume per service; injects
`PORT` and requires binding `0.0.0.0`; Config as Code (`railway.json`) is
deprecated and new services cannot opt in (root `Dockerfile` is auto-detected);
a forum moderator states the edge overwrites `X-Forwarded-For`/`X-Real-IP`
(not formal documentation).

### 15.4 Exercised deploy evidence (local Docker only)

- `~/.claude/bin/heavy-gate -n 1 -l docker-build -- docker build -t
  usage-api-railway:test .` succeeded (exit 0) on linux/amd64; rebuilt after adding
  `umask 077` to `/etc/bash.bashrc`, also exit 0. Image size 2.08 GB on disk
  (559 MB compressed content); largest layers: npm CLIs 741 MB (Codex 426 MB,
  Claude Code 279 MB), Node.js 211 MB, Grok 196 MB.
- `docker run --rm -e HOME=/data/home usage-api-railway:test sh -c 'usage --help &&
  usage api --help; claude --version; codex --version; grok --version'` printed both
  help texts (`{accounts,api}`, `{serve,token}`), `2.1.308 (Claude Code)`,
  `codex-cli 0.165.0`, `grok 1.0.70 (f50904eaee6c)`; without a volume the
  entrypoint printed its `/data is not a mounted volume` warning.
- Detached container with a named volume at `/data`: PID 1 `tini --
  usage-entrypoint sleep infinity`, child `sleep infinity`; `/data/home` mode `700`
  owned by root, `HOME=/data/home`; Config `Cmd=["sleep","infinity"]`; no warning
  logged; interactive bash `umask` `0077`; `docker stop` returned in 0.13 s.
- In-container demo API on `127.0.0.1:8787`: `/healthz` → `{"status":"ok"}`;
  `/api/v1/session` → `200` with `cache-control: no-store`; `/api/v1/dashboard`
  returned demo accounts; `POST /api/v1/session` → `405`. Live `usage api serve
  --host 0.0.0.0` without tokens refused with the curated message, exit 2.
  Graceful SIGINT shutdown was not conclusively observed in this smoke.
- Test containers and the volume were removed afterwards.

### 15.5 Acceptance checklist

- [ ] Backend: full `uv run pytest -q`, Ruff check/format and API tests green
  after integration — pending orchestrator verification.
- [ ] Backend: installed-entry `usage api serve` live and demo runs, token
  create/list/revoke in a real PTY, revocation without restart, SIGINT/SIGTERM
  exit 0 — pending.
- [ ] Frontend: `npm ci`, typecheck/lint/build green; browser check against
  `usage api serve --demo` (login, 401 return, polling, layout at 375/800/1200 px,
  light/dark) — pending.
- [x] Container image builds locally and contains working `usage`, `claude`,
  `codex`, `grok` at the pinned versions; entrypoint creates `0700` HOME and idles
  on `sleep infinity` (§15.4).
- [ ] Frontend deployed to at least one of Vercel / Cloudflare / Railway with the
  shipped headers — pending, requires the user's accounts.
- [ ] Backend deployed on Railway with a `/data` volume, public domain, `PORT`
  target, `railway ssh` logins and `serve --trust-proxy` — pending, requires the
  user's Railway project and logins.
- [ ] Railway `X-Forwarded-For` behavior verified for `--trust-proxy` — pending.
- [ ] Authenticated live provider reads through the API — pending; unchanged live
  prerequisites from §9/§11 apply.
- [ ] Independent review of API, frontend and deploy units — pending.

### 15.6 User-requested login keepalive (`usage-keepalive`)

Request: idle Railway hosts let first-party access tokens lapse; design a renewal
path, and (user choice) for Claude Code use `claude auth status` first, then a minimal
Haiku request. The reader still never refreshes or reads refresh tokens (§4.3 is
unchanged for the reader); this separate opt-in loop deliberately spawns the official
CLIs so each CLI renews its own file. Implementation: `src/cli_usage_api/keepalive.py`,
console script `usage-keepalive`, `tests/test_keepalive.py` (fake CLIs only).

- Scheduling: all three CLIs refresh only within 300 s of access-token expiry at the
  inspected revisions, so the loop reads token fields only for presence and expiry
  hints (Claude `expiresAt` ms, Codex access-token JWT `exp` (unverified decode),
  Grok per-scope `expires_at`) and acts within 290 s; token values are never logged
  or printed. Unknown expiry: one run (`ran_unknown_expiry`), then a 24 h cadence.
  Success is only "re-read file shows a later expiry and a nonempty token"; exit codes
  are ignored. Output is discarded; logs carry provider, event and seconds-to-expiry.
  `--interval` is capped at 240 s and the loop sleeps until the next window start or
  backoff expiry (floor 1 s), so a window cannot be skipped and backoff is not rounded up.
- Grok scopes: only reader-selectable keyed scopes (`https://auth.x.ai::<id>`, legacy
  `https://accounts.x.ai/sign-in`) are observed, each separately. An attempt succeeds
  when any scope's expiry advanced. Due scopes that did not advance after a completed
  attempt are marked stale (logged once, by kind only) and excluded from scheduling,
  except the scope the reader selects by default (the single modern scope, else
  legacy) and protected scopes; a stale scope revives when its expiry changes. If only
  stale scopes were due, the attempt is not counted as a failure. Protected scopes
  (`keepalive.grok_protected_scopes`) are the explicit selectors of enabled saved Grok
  `grok_auth_file` accounts whose reference is `default` or resolves to `grok_path()`;
  a no-selector account adds nothing (its default is already the exempt preferred
  scope), so an expired legacy scope next to one modern scope can go stale instead of
  failing and alerting every token lifetime. Standalone `usage-keepalive` reads saved
  accounts once at startup (never writes); any `ConfigError` logs `accounts
  unavailable; no protected Grok scopes` and continues without protection.
- Stop: `Keepalive.request_stop()` (thread-safe `threading.Event`) is checked before
  each target and each command, and SIGKILLs the in-flight child's process group via
  the tracked `Popen` (a child started as the stop arrives is killed at once). A
  stopped attempt is neither success nor failure (no retry/alert/backoff change; the
  restore rules still apply and the backup is kept). `run_async` honors it;
  `wait_idle()` reports when no tick runs. Standalone Ctrl-C also kills the child.
- Commands: Codex `codex doctor --json` (`doctor.rs` websocket check calls
  `AuthManager::auth()`; `codex login status` does not refresh); Grok
  `grok sessions list -n 1` (`sessions_cmd.rs` `try_ensure_fresh_auth`; refresh holds
  `auth.json.lock`); Claude `claude auth status`, then `claude -p … --model haiku
  --effort low --tools "" --max-turns 1` (flags confirmed accepted by the pinned
  2.1.308 in an offline container; `--max-turns` is hidden from `--help`) only when
  the expiry did not advance (`--claude-mode` selects
  hybrid/status/model). Child env disables auto-update, telemetry and nonessential
  traffic; 90 s timeout kills the process group.
- Claude exit race (anthropics/claude-code#105645, 2.1.311/2.1.312 bundle: 2000 ms
  exit wait): before each attempt the credentials file is copied to a same-directory
  `0600` `.keepalive-backup` (unique `O_EXCL` temp + `os.replace`). It is restored
  only when the file still exists, is still blank/unparseable, and its
  `(st_ino, st_mtime_ns, st_size)` is unchanged since the command returned (a deleted
  file is a logout and is never restored); deleted after success, retained after the
  final alert, and deleted automatically when a manual re-login makes the file usable
  again. A backup cannot revive a refresh token already consumed upstream. This copy
  is a deliberate, documented exception to "never copy refresh tokens", outside app
  storage. Concurrent interactive Claude sessions on the same HOME should be avoided.
- Retries 30/60/120/300/600 s, then `ALERT manual login required` (", backup kept"
  only for Claude) and no further attempts until the file's observed state changes to
  a usable login (re-login). Backoff also resets when the login is renewed elsewhere
  (usable and outside the window, or a later expiry). Per-target exceptions are logged
  by type name only and do not stop the loop; nested-JSON `RecursionError` and
  `TypeError` count as an unusable file. Single instance via
  `~/.local/state/usage-keepalive/keepalive.lock`.
- Sources: openai/codex@a29c7b97 (`login/src/auth/manager.rs`, `cli/src/login.rs`,
  `cli/src/doctor.rs`), Codex CI/CD auth doc, code.claude.com CLI reference/env-vars,
  claude-code issues #105645/#60503, agentcord PR #161, npm
  `@anthropic-ai/claude-code-linux-x64@2.1.312` bundle strings, xai-org/grok-build@2bdd1d6
  (`xai-grok-login` manager/refresh_chain/oidc, `xai-grok-pager/src/sessions_cmd.rs`).
  Codex was cross-checked against tag `rust-v0.165.0` (the pinned 0.165.0).
  Unknowns: real token lifetimes; whether a Claude remote flag suppresses the
  `auth status` refresh; whether Grok 1.0.70 matches the inspected HEAD; the Claude
  research came from 2.1.311/2.1.312 bundles but the image pins Claude Code 2.1.308
  (`Dockerfile`), whose refresh window and exit race were not inspected.
- [x] Unit tests with fake CLIs (24, after review fixes 13–21) — exercised locally.
- [x] Review fixes (stop/protection): stop during the first hybrid Claude command never
  runs the Haiku request; a stop kills a real long-running fake CLI and its grandchild
  within seconds; no later target starts after a stop; protected-scope selection and
  the legacy + one modern + no-selector scenario (legacy stale once, no ALERT over
  several lifetimes); standalone main loads/fails soft — `tests/test_keepalive.py`.
- [ ] Real-account renewal of each CLI inside the container — pending; requires the
  user's logins.


### 15.7 User-requested one-process dashboard + API (+ keepalive)

Request (translated): Railway cannot show Claude Platform balances although the TUI
offers session-only storage — run the TUI and the API in one process (`usage --api …`)
sharing one scheduler and its snapshots, put `usage-keepalive` in the same process,
and choose what starts with arguments. Rationale: with no keyring in the container a
Console `sessionKey` can live only session-only in the TUI process; hosting the API
there lets that one `CredentialStore`/resolver/scheduler feed the API. This
supersedes §15.2's "Claude Platform is unsupported in the container" for one-process
mode only; headless `serve` remains file-backed only.

Contract:

- CLI: `usage [--demo [--scenario S]] --api [--api-host H] [--api-port P]
  [--allow-origin O ...] [--trust-proxy] [--keepalive [--keepalive-cli NAME ...]
  [--keepalive-claude-mode hybrid|status|model]]`, and `usage api serve … --keepalive
  [...]`. Validation, token policy, CORS normalization and bind error mapping are one
  shared `cli.ApiPlan` used by both modes (curated exit 2; bind failures exit 3 naming
  `--api-port`/`--port`). Live `--api` requires ≥ 1 token; loopback demo may be
  anonymous only while no tokens exist. API options without `--api`, keepalive options
  without `--keepalive`, `--keepalive` with `--demo`, and dashboard API/keepalive
  options before a subcommand are refusals. Every refusal (including keepalive
  `KeepaliveError`: no login files, lock held) happens before the TUI takes the
  terminal; the socket is bound before `App.run`.
- Embedding: `UsageApp.add_observer` (snapshot accepted / accounts changed) and
  `add_service` (`start(app)` after the scheduler starts, `stop()` before the scheduler
  and factory close, errors suppressed). `api.AppHub` mirrors the app's accounts and
  accepted snapshots, drops all snapshots on any account change (as the TUI does) and
  never starts/stops the scheduler. `api.EmbeddedServer` runs uvicorn in the app's
  loop with `lifespan="off"`, no signal handlers, `log_config=None`, access log off and
  uvicorn loggers given a `NullHandler` with propagation off; a server failure sets
  the banner note to `API … 已停止` and raises an error notification. Banner notes:
  `API host:port 令牌认证|无认证（本机演示）`, `keepalive <names>`.
- Keepalive: `cli.KeepaliveService` wraps `keepalive.build`/`run_async` unchanged,
  holds `keepalive.InstanceLock` for the process lifetime, logs via
  `keepalive.file_logger()` (TUI: never the terminal; `serve`: also stdout), turns
  `ALERT` lines into warning notifications via `call_soon_threadsafe`, and passes
  `keepalive.grok_protected_scopes(accounts)` (§15.6). In the dashboard it is also a
  `UsageApp` observer: `accounts_changed` swaps the Grok target's protected frozenset
  atomically. Cancelling an `asyncio.to_thread` await does not stop its thread, so
  `stop()` calls `request_stop()` (no new target/command; in-flight CLI process group
  killed), then waits ≤ 10 s for the worker task; `keepalive stopped` is logged only
  once the worker is idle. The lock context calls `join()` (unbounded wait for the
  worker) before releasing `InstanceLock`, so a second keepalive can never refresh the
  same token while this worker still runs.
- Costs recorded in `docs/deploy-railway.md`: re-enter the session-only `sessionKey`
  after every restart/redeploy/exit; a high-sensitivity session lives in a public
  host's process memory; Console sessions expire and keepalive does not cover them.

Acceptance (only what was run, 2026-10-29, this working tree):

- [x] `tests/test_embedded.py` (33 tests after review fixes): demo API on a real 127.0.0.1 socket inside
  `run_test` serves exactly `app.snapshots` (organization nulled) and stops/frees the
  port on `q`; live API with a fake scheduler enforces bearer tokens and reflects
  edit/remove/add/disable immediately, ignores late snapshots of removed accounts, and
  stops before `scheduler.stop`/`factory.close`; a closed socket yields a toast and
  `已停止` banner without crashing or terminal output; keepalive with a fake `codex`
  on `PATH` and fake login files runs `doctor --json`, holds then releases the lock,
  logs start/stop to a `0600` file; an unusable login file's `ALERT` becomes a toast
  with nothing written to the terminal; `serve --keepalive` prints log lines and
  stops; CLI refusals and bind conflict exit before the TUI. Review fixes: the lock
  stays held while a worker ignoring the stop still runs and is released (with
  `keepalive stopped` logged last) only after it returns; `stop()` kills a fake
  `codex` running `sleep 60` in < 5 s; TUI account changes update protected Grok
  scopes; `--keepalive-cli`/`--keepalive-claude-mode` before a subcommand are refused.
- [x] Full gate after the stop/protection review fixes: `uv sync --locked --group dev`;
  `uv run pytest -q` → 1409 passed (earlier: 1396);
  `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 54 files
  already formatted.
- [x] Installed-entry PTY run (stdlib `pty`, `scripts/tui_smoke.py`'s `PtySession`,
  isolated HOME/XDG, 120×40): `.venv/bin/usage --demo --api --api-port <free>`
  rendered `DEMO` and `API 127.0.0.1:<port>`; while the TUI ran, curl `/healthz` → 200
  `{"status":"ok"}`, `/api/v1/session` → 200 `auth: none`, `/api/v1/dashboard` → 200
  demo with 4/4 accounts carrying snapshots; `q` → exit 0, screen/cursor/termios
  restored, port freed. Repeated with Ctrl-C: same results.
- [ ] Live `usage --api` with real accounts, a real session-only Console `sessionKey`
  and real tokens — pending; requires the user's credentials.
- [ ] Railway deployment of one-process mode in tmux, `--keepalive` renewing real
  logins in the container — pending.
- [ ] Independent review of this change — pending.
- Final stop-fix verification (orchestrator): independent rereview reproduced that a
  Grok scope marked stale stayed ignored after becoming protected (TUI account edit)
  or becoming the reader's preferred scope; fixed by treating protected/preferred
  scopes as live in `Target.live_scopes` (no cross-thread mutation of `stale`), with
  two regression tests and the reviewer's repro scripts now scheduling correctly.
  Actual installed-entry real-PTY smoke of live `usage --api --keepalive` with fake
  Codex login/CLI and isolated HOME: 33/33 assertions passed (token auth 200/401,
  fake `codex doctor` renewal observed, no token text in keepalive.log, `q` exit 0 in
  0.60 s, port freed, terminal restored, lock released; quitting during a sleeping
  fake CLI killed its process group and released the lock). Fake data only; no real
  login renewal, Railway deployment or live provider read is claimed.

## 16. User-requested supply-chain audit remediation — 2026-10-29

The user requested fixes for all three audit findings: outdated frontend container
components, unlocked Python build/Wrangler tooling, and incomplete container/CLI
artifact pinning. The audit found no confirmed malicious source or supply-chain
compromise. This amendment hardens installation inputs; it does not change quota,
credential, API or dashboard contracts and does not establish upstream code safety.

### Implemented scope

- [x] **Finding 1:** frontend Node 22.23.4-bookworm-slim and Caddy 2.11.7-alpine,
  both pinned to registry-verified multi-platform OCI index digests. Caddy's
  selected exact version returned no matching reviewed GitHub advisories.
- [x] **Finding 2:** Hatchling 1.33.0 and its complete isolated wheel/editable
  build graph are exact, universal-wheel-hash constraints in `pyproject.toml`,
  with `require-build-hashes = true` under uv 0.13.5+. `uv.lock` adds build
  constraints without changing its 41 existing package records. Wrangler 4.155.0
  is an exact locked frontend devDependency; `npm run deploy` invokes it locally,
  replacing the documented unversioned `npx` fetch. Frontend Node minimum is 22.12.
- [x] **Finding 3:** backend Python 3.12.15-slim-bookworm and uv 0.13.5 use index
  digest pins; remove the floating external Dockerfile syntax frontend. New
  `docker/cli/package.json`, `package-lock.json` and `.npmrc` lock both CLI wrappers
  and their complete platform graph (16 external package/version records) with
  SHA-512 integrity. Install under `/opt/usage-clis` using
  `npm ci --ignore-scripts --include=optional`; link Claude's locked Linux binary
  directly instead of executing its postinstall, retain Codex's official launcher,
  and reject missing native executables for either supported architecture. Frontend
  npm policy also skips dependency hooks while retaining required native optional
  packages. Node/Grok downloads and redirects are HTTPS-only and hashes are checked
  before extraction. Grok's authenticity limit below remains explicit.
- [x] README, web README, Railway guide, SECURITY, CHANGELOG and repo Lessons
  describe the new inputs, upgrade paths, script-disabled installation and limits.

### Source and trust record

- Image index digests are in the two Dockerfiles. Registry inspection established
  Linux amd64 and arm64 descriptors; the actual build verified digest resolution
  for amd64. Sources: `ghcr.io/astral-sh/uv:0.13.5`, Docker Official Images Python
  `3.12.15-slim-bookworm`, Node `22.23.4-bookworm-slim` and Caddy `2.11.7-alpine`.
- Node security release and standalone hashes:
  <https://nodejs.org/en/blog/release/v22.23.4/>;
  <https://nodejs.org/dist/v22.23.4/SHASUMS256.txt>.
  Caddy stable release: <https://github.com/caddyserver/caddy/releases/tag/v2.11.7>.
- Approved build wheels (exact versions and SHA-256 in `pyproject.toml`):
  Hatchling 1.33.0, packaging 26.3, pathspec 1.1.1, pluggy 1.7.0, tomlkit 0.15.2,
  trove-classifiers 2026.9.21.13 and editables 0.6. Primary version-specific PyPI
  metadata hashes matched downloaded wheel bytes; wheel dependency metadata and
  Hatchling's editable-build requirement were inspected without executing them.
  uv enforcement: <https://docs.astral.sh/uv/concepts/projects/build/#project-build-dependency-hashes>.
- Claude/Codex exact npm wrapper metadata and downloaded wrapper tarball SHA-512
  agreed; Claude's `install.cjs`/fallback launcher and Codex's `bin/codex.js` were
  inspected. No custom runtime launcher was introduced. Sources:
  <https://registry.npmjs.org/@anthropic-ai%2fclaude-code/2.1.308>;
  <https://registry.npmjs.org/@openai%2fcodex/0.165.0>.
- Wrangler source: <https://registry.npmjs.org/wrangler/4.155.0> and upstream stable
  release <https://github.com/cloudflare/workers-sdk/releases/tag/wrangler%404.155.0>.
  Its upstream exact prerelease transitive versions (including miniflare/unenv)
  are retained, not replaced by guessed overrides. esbuild/workerd entrypoints
  resolve their locked native optional packages without the postinstall optimization.
- Grok: <https://x.ai/cli/install.sh> and <https://docs.x.ai/build/overview> did not
  provide an independent vendor checksum/signature mechanism. Keep the existing
  versioned 1.0.70 artifacts and committed TOFU hashes; never substitute a fresh
  download's hash automatically. amd64 matched during Docker build; a separate
  HTTPS streaming download of the arm64 `.gz` matched
  `0d9e47fc2cb14db2f52f99e9289c41b3723b64de05c284a9f18c2e8df52550cf`.

### Exercised orchestrator evidence

All checks used temporary, credential-free environments. No new permanent tests
were added for manifest wiring; the changed installation/runtime paths were
exercised directly. The following are new observations, not inherited old gates.

| Check | Observed result |
|---|---|
| Fresh copied project, separate empty cache/environment: `uv sync --locked` | Editable install succeeded; installed `usage --help` ran with account/API commands. |
| Another empty cache/environment: `uv sync --locked --no-dev --no-editable` | Wheel install succeeded; installed `usage --help` ran. |
| Zeroed Hatchling hash, regenerated lock with `uv lock --no-build`, fresh `uv sync --locked` | Refused with the expected `Hash mismatch` and computed/expected SHA-256. |
| Hashless pinned Hatchling string constraint, regenerated lock, fresh `uv sync --locked` | Refused with `Hash-checking is required, but no trusted hash was provided`. The initial fixture's invalid hashless-object schema was corrected; that parse error is not this acceptance proof. |
| Copied CLI manifest/lock, corrupted Codex SHA-512, fresh `npm ci --ignore-scripts --omit=optional` | Refused with `EINTEGRITY`; the Codex executable was not installed. |
| Gated `docker buildx build --platform linux/amd64 --load` of root and web Dockerfiles | Both images built. Separate BuildKit container had asserted 2 GiB memory and equal memory-swap limit; no gate bypass. Builder removed afterward. |
| Frontend image build | Fresh script-disabled `npm ci` succeeded; `npm run build` completed TypeScript checking and Vite production output. |
| Backend image with `--network none` | `usage --help`, uv 0.13.5, Node 22.23.4, Claude 2.1.308, Codex 0.165.0 and Grok 1.0.70 ran; HOME was 0700; Claude wrapper stub remained untouched by postinstall. |
| Backend demo API in network-isolated container | Health 200; demo session and dashboard with 4 populated synthetic accounts; no-store header; POST refused with 405; SIGTERM container shutdown exited 0 without OOM. |
| Caddy final image in network-isolated container | Version 2.11.7 and config validation succeeded; actual HTTP root and SPA fallback returned built HTML with CSP/nosniff; JS asset returned 200 with immutable cache headers. |
| Frontend build image, no network/credentials, isolated HOME/config | Local Wrangler printed 4.155.0; `npm run deploy -- --dry-run --outdir /tmp/usage-dry-run` read 19 built assets and exited successfully. No cloud deployment occurred. |
| Exact-version public GitHub advisory queries | All 312 frontend lock records and 7 build-tool versions returned no reviewed or malware matches; Caddy 2.11.7 returned no reviewed matches. This is not an OS-image/SBOM or unknown-malware scan. |

### Remaining boundaries

- Grok's original artifact authenticity cannot be upgraded to vendor-authenticated
  provenance without a vendor signing/attestation/checksum source. The repository
  now preserves and rechecks the selected hashes; TOFU is not represented as fixed
  upstream authenticity. No third-party package or native binary is certified benign.
- Runtime smoke was linux/amd64. arm64 index/package metadata and the Grok archive
  hash were checked, but no arm64 image execution/emulation was performed.
- uv's build-hash feature is experimental; installed packages/cached built wheels
  are not revalidated, and disabling build isolation bypasses these checks. Approved
  build-wheel hashes do not freeze Debian apt repositories or managed cloud runtimes.
- No full application test-suite rerun, browser visual acceptance, authenticated
  provider request, real CLI login/renewal, or Railway/Cloudflare/Vercel deployment
  is claimed. Application source and those acceptance boundaries are unchanged.

The orchestrator-owned verification builder, containers, image tags and temporary
inspection/smoke scripts and caches were removed after these checks. No verification
service was left running, and no user credential or account state was modified.

## 17. User-requested eMudhra CA and deployment runtime review — 2026-10-29

The user requested checking/pinning Python, uv, Node, dependencies, Docker images
and certificate-related components for Railway/Vercel/Cloudflare, with additions
to `docs/deploy-railway.md` and `web/README.md`. This is installation and verifier
maintenance, not an application/provider/authentication contract change.

### Findings, decisions and implemented scope

- [x] Identify the incident from the [Mozilla record](https://bugzilla.mozilla.org/show_bug.cgi?id=2083449),
  [researcher advisory](https://emudhra.we-have-a-problem.com/) and
  [Cloudflare response](https://blog.cloudflare.com/emudhra-certificate-compromise).
  Eight intermediate keys, including TLS and code-signing, were compromised;
  Sectigo cross-signs make removing only one root an incomplete general mitigation.
  No project credential compromise or successful attack was established.
- [x] Replace the manifest's CPython 3.12.15 pin with **3.12.16** and its registry
  index digest; add the same `.python-version` to local selection and Docker's
  allowlisted build context. The [CPython security release](https://blog.python.org/2026/10/python-3152-31410-31318-31216-31118/)
  adds intermediate-key rejection in `ssl`. This was a missing defense-in-depth
  version, not proof that the old application's already-updated certifi accepted
  a malicious chain. An existing user-owned image reported 3.12.16 and was not
  represented as a 3.12.15 reproduction or modified.
- [x] Pin **uv 0.13.6** by index digest and exact `tool.uv.required-version`.
  [0.13.5](https://github.com/astral-sh/uv/releases/tag/0.13.5) already supplied
  rustls-webpki key rejection, but the exercised `uv python list --all-versions
  3.12.16` returned no matching catalog entry. [0.13.6](https://github.com/astral-sh/uv/releases/tag/0.13.6)
  adds the selected interpreter; a fresh isolated managed download/install was
  subsequently exercised. This corrects the initial 0.13.5 implementation before
  completion. Both Python/uv indexes include amd64 and arm64 metadata; execution
  here was amd64 only.
- [x] Keep signed Debian repository updates, adding a build-time
  `ca-certificates >=20250419~deb12u2` floor ([vendor package](https://packages.debian.org/bookworm/ca-certificates),
  [incident fix](https://bugs.debian.org/1151413)). Do not freeze all apt inputs or
  introduce an application-specific root blacklist. Retain locked certifi
  **2026.10.23**, the 41-package Python lock and the approved isolated build hashes.
- [x] Retain **Node 22.23.4**: its [vendor release](https://nodejs.org/en/blog/release/v22.23.4/)
  includes blocked-public-key rejection. Add `web/.node-version`, constrain engines
  to `>=22.23.4 <23` in manifest/lock metadata and enable npm `engine-strict`.
  Preserve all dependency versions, integrity values and disabled install hooks.
  Vercel selects a major with managed patch rollout; Cloudflare build selectors
  and explicit `npm ci` are documented separately from Workers compatibility dates.
- [x] Inspect Caddy rather than equating a recent tag with a fixed verifier.
  The pinned **2.11.7** binary actually reports **Go 1.26.8**, before fixed
  [Go 1.26.10/1.27.3](https://groups.google.com/g/golang-announce/c/66pojueaQek).
  Alpine CA packages are **20261020-r0**. Retain this image only for the existing
  HTTP-only static configuration (`auto_https off`, no upstream proxy); require
  a reviewed fixed build before TLS-client/ACME/proxy use. This is not a claim that
  Caddy's bundled verification paths are patched.
- [x] Update both requested deployment guides, root quickstart, SECURITY,
  CHANGELOG and repo Lessons. Preserve distinctions among platform edge TLS,
  browsers, system CA, HTTPX/certifi/CPython, uv and native CLI verification.
  No application source or permanent tests changed.

### Newly exercised orchestrator evidence

All installations used temporary environments/caches; no credentials were supplied.
Public TLS probes sent no authentication, cookies or provider data. Image builds
ran through the shared heavy gate with a separate BuildKit container whose memory
and memory+swap limits were both asserted at 2 GiB. No browser was launched.

| Check | Observed result |
|---|---|
| Both Dockerfiles: amd64 builds; final backend rebuilt with `--pull --no-cache` after uv correction | Successful digest resolution, fresh locked installs and production output. Final backend uses Python 3.12.16 / uv 0.13.6; frontend Node 22.23.4 / Caddy 2.11.7. |
| Final backend runtime inventory | CPython 3.12.16; linked OpenSSL 3.0.22; Debian libssl3/openssl 3.0.22-1~deb12u2; CA 20250419~deb12u2; curl 7.88.1-10+deb12u15; certifi 2026.10.23; npm 10.9.9; Claude 2.1.308, Codex 0.165.0 and Grok 1.0.70 version commands succeeded. |
| Offline OpenSSL verification of the researcher's 14 public TLS chains, separately against system and certifi bundles | Both bundles rejected all 14, including AAA cross-signs and two no-CT chains, with issuer/trust errors rather than expiry/hostname failures. Downloaded certificate-only archive SHA-256: `7b949956955fc501a30f4d98d2f513d34c0bbbe92e29a968194c96e097ce2345`. No downloaded code executed. |
| Final image HTTPX using `verify=True, trust_env=False`, matching the application's verifier configuration | Positive PyPI HTTPS returned 200; all 14 test hosts failed with underlying `SSLCertVerificationError`, code 20. The fixed provider allowlist was not weakened or redirected for testing. |
| curl and final uv downloader, emSign and AAA sample hosts | Both clients rejected both samples with certificate errors; curl returned 60. curl's positive PyPI HTTPS succeeded. uv used no-build/no-deps index resolution with zero retries and no package installation. |
| Node 22.23.4 HTTPS path, same two samples | Positive npm registry HTTPS returned 200; both test hosts failed with `CERT_REVOKED`. |
| Base image pip outside app venv | Still pip 25.0.1, not the project installer. Its isolated no-install index probes rejected both sample chains with `CERTIFICATE_VERIFY_FAILED: certificate rejected` under patched CPython. This is not an independently updated pip-vendored bundle; separate pip adoption still follows vendor 26.2.2+ guidance. |
| uv 0.13.6 managed bootstrap into an empty temporary install directory | Downloaded and ran CPython 3.12.16; fresh-cache `uv sync --locked --group dev --no-editable`, installed `usage --help` and targeted transport/security tests succeeded. **141 passed in 0.22 s**. |
| Separate fresh-cache default `uv sync --locked` | Editable install and installed `usage --help` succeeded, including hash-constrained editable-build requirements. |
| Negative build-hash fixtures under uv 0.13.6 | An initial incomplete fixture was refused for missing `packaging` hash; after supplying the complete graph, a zeroed Hatchling hash was refused with `Hash mismatch` and the expected/computed SHA-256. The initial fixture assertion expected the wrong refusal and was corrected; no production fix was needed. |
| Actual repository invoked with host uv 0.13.5 | Refused with required-version mismatch (exit 2), without changing host uv or the project lock. |
| Copied frontend manifests under host Node 24.22.1 | `npm ci --offline` failed with `EBADENGINE` before creating node_modules. The selected Node 22.23.4 succeeded during the actual frontend image build. |
| Final installed backend demo API in network-isolated container | Health/session/dashboard 200, four synthetic accounts, no-store, POST 405 and SIGTERM exit 0. |
| Final frontend static server | `caddy build-info` confirmed Go 1.26.8; installed Alpine CA/bundle 20261020-r0 and libssl3 3.5.9-r0. Config validation passed. Actual HTTP root and SPA fallback served identical HTML with CSP/nosniff; JS asset returned 200 with immutable caching. |
| Locked Wrangler in network-isolated frontend build image | Version 4.155.0; `npm run deploy -- --dry-run` read 19 built assets and exited successfully. No cloud deployment occurred. |

### Limits and disposition

This verifies selected TLS/build/serving paths, not every application on a host,
all code-signing chains, a full OS/CVE/SBOM audit or unknown-malware absence.
Claude's fixed-version lead is from the researcher list; Codex's tagged source
graph contains fixed rustls-webpki but also other TLS implementations. Grok's native
verifier coverage remains unknown, and its artifact hashes remain TOFU. No
authenticated CLI login/renewal, provider read, OS-keyring operation, arm64 run,
browser visual run, full application suite or actual Railway/Vercel/Cloudflare
deployment is claimed. Existing application/private-provider acceptance remains
unchanged. No new independent implementation review or commit is claimed.

The owned builders, smoke containers, image tags and temporary fixtures/scripts/
caches were removed. No user-owned service, credential file, account state, host
runtime installation or cloud setting was changed. Operators must deploy the new
images (not restart old ones), update local uv, and apply the documented managed
platform settings; Railway's manually started API/tmux sessions need restarting.

## 18. User-requested web account management and reorder — 2026-10-29

User request (translated): add and edit accounts from the web UI (file-backed login
references, a Console `sessionKey`, or a manual bearer/API key where allowed) so the
operator needs only `usage api serve --keepalive`, without the TUI, including for
Claude Platform; support the Railway flow "deploy on `sleep infinity` → log in over
`railway ssh` → create a token → switch the start command to `usage api serve …
--keepalive` → add accounts on the web"; and drag-to-reorder accounts in the web UI
and the TUI account manager, with every dashboard following that order.

**Amendment:** §15.2's "GET/HEAD/OPTIONS only" and "Account config is read once at
startup" (and §15.1's "Out of scope: any HTTP mutation of accounts") are superseded
for live servers without `--read-only`. `--read-only` and demo keep the §15.2
read-only surface, except that a write method on an account write route returns
`403 read_only` rather than `405` (session and dashboard still answer `405`).

### 18.1 Fixed decisions and non-goals

- Writes are on by default for token-authenticated live serving on both `usage api
  serve` and `usage --api`; `--read-only` disables them on both; demo is always
  read-only. Writes use the existing bearer tokens: there is no new token type or
  scope, so upgrading grants existing tokens write power (startup `ENABLED` line,
  token-create line, CHANGELOG breaking note and web "remember" note say so).
- `persist=true` stores a secret in the exact supported Secret Service backend or
  fails `503 secure_store_unavailable` without downgrading; `persist=false` keeps it
  session-only in that server process. `secure_store_available` is advertised but
  reflects only the backend type.
- File kinds accept `default` or a normalized absolute path with the kind's basename
  (`.credentials.json` for Claude Code, `auth.json` for Codex/Grok), never under
  `/proc`, `/sys` or `/dev`. This is a deliberate tightening that also applies to the
  CLI and TUI for new entries; saved references are not revalidated. Grok requires an
  explicit scope choice and Console an explicit organization choice, even for one.
- Order is the `accounts.json` array order. `AccountService.reorder` validates an
  exact permutation under the config lock; a stale list is a curated conflict.
- Standalone `serve` becomes dynamic (`SnapshotHub.accounts_changed`); embedded writes
  go through `UsageApp.accounts_changed`. `AccountService` is the single mutation core.
- Non-goals: token scopes; watching `accounts.json` for edits by another process (they
  apply on the next API write, a conflict resync, or restart); migration over HTTP (a
  legacy ChatGPT config is `503 config_unavailable`); provider/transport changes; TUI
  dashboard reorder; a non-root Docker `USER`; any live/authenticated/keyring claim.

### 18.2 Condensed contract

- Dispatch: OPTIONS (full method set and `Authorization, Content-Type, If-Match`
  advertised even when read-only, so browsers get a readable `403`) → unknown method
  `405` → long path `404` → public `/healthz` (GET/HEAD) → authentication (unchanged;
  a valid token never consults the limiter) → route (`404`, or `405` with per-route
  `Allow`) → per-request write gate (operations present, live hub, not anonymous;
  otherwise `403 read_only` without reading the body) → body → handler.
- Bodies (writes only): `application/json` (optional `charset=utf-8`), ≤ 64 KiB
  (declared or streamed `413`), one 10 s read deadline (`408`), strict UTF-8 JSON with
  duplicate-key, `NaN`/`Infinity`, deep-nesting, oversized-int and lone-surrogate
  rejection (`400 invalid_request`), exact key whitelists and strict bool/int types.
  DELETE and reconnect require an empty body. Errors are `{"error": code}` (plus
  `retry_after` for `discovery_busy`) and never echo input.
- Routes: `GET/HEAD /api/v1/accounts` (new `AccountConfig` list + `capabilities`);
  `POST /api/v1/accounts` (201); `POST /api/v1/accounts/prepare` (Grok scope or
  Console organization choices); `PUT /api/v1/accounts/order`; `PATCH` and `DELETE
  /api/v1/accounts/{id}` with a required `If-Match` revision (`428` missing, `409`
  stale after a resync); `POST /api/v1/accounts/{id}/reconnect` (`{"status":"queued"}`).
  Session and account lists carry `capabilities {writable, secure_store_available}`.
- `AccountConfig` exposes provider, label, enabled, configured/effective interval,
  kind, storage class, `reference` as `default|custom|null`, `session_available`,
  scope/organization-selected flags and a per-process HMAC `revision`. It never returns
  custom paths, Grok selectors, Console organization IDs, org-ID fallback labels or
  credential refs.
- Prepare records: 300 s TTL, at most 4 (oldest evicted), bound to account, provider,
  kind and revision; Console temp secrets are session refs no account references,
  deleted on consume, failure, expiry (a loop timer at the TTL, not the next write),
  eviction and shutdown; the commit task, not the cancellable request, owns a secret
  until it is stored. Grok selectors are
  re-verified against the file at commit (`410 prepare_expired`). Console discovery is
  one at a time with a 10 s cooldown and 6 per 600 s (`409 discovery_busy` +
  `Retry-After`; never `429`, which the web treats as session end). Reconnect is
  coalesced per account (≥ 30 s or the effective poll interval). At most 100 accounts.
- File resolution on save collapses every failure except `credential_expired` (a
  committed write with a warning) into `422 credential_unavailable`; file reads are
  limited to 2 concurrent; `_read_file` requires a regular file via `lstat` before open.
- Commit and publication: the host owns `account_lock`; every writer (HTTP, conflict
  resync, TUI manager, account form, reorder) holds it across commit and host
  notification, and HTTP takes it inside a shielded task so a cancelled request still
  publishes in commit order. Committed-but-uncertain outcomes are `200/201` with a
  `warning` (`committed_uncertain`, `cleanup_failed`, `host_refresh_failed`,
  `credential_expired`).
- Scheduler: `update_accounts(accounts, *, invalidate=None)`. `None` keeps the previous
  behaviour; a set keeps scheduler state and snapshots for accounts whose credential
  identity is unchanged and that were not explicitly resubmitted, so renames, toggles
  and reorders keep observations, while an explicit source submission (even an equal
  file reference) starts a fresh generation. A kept generation whose interval shrinks
  is due no later than now + the new interval (embargoes unchanged), and an in-flight
  fetch schedules from the current interval.
- Process: `serve` and `usage --api` disable core dumps (best-effort `RLIMIT_CORE` 0 and
  Linux `PR_SET_DUMPABLE` 0). Keepalive protection of Grok scopes is now lexical against
  the default path forms resolved once at startup (a reference as written or
  `normpath`-normalized); references already saved at startup are also realpath'd
  once then, so symlinked or unnormalized saved paths keep protection. References
  added later over HTTP are never resolved.
- TUI: the account manager reorders with Shift+↑/↓ (Ctrl+↑/↓ aliases) and mouse drag;
  it holds `app.account_lock` and notifies with explicit invalidate sets. Ending a drag
  (drop, Esc, or a reload from another writer) replaces the "Esc cancels" status;
  mutating shortcuts are ignored while a drag is active. Web: an
  `#accounts` view with an account form, grip drag/keyboard reorder and fixed zh error
  copy (owned and documented by `web/`).

### 18.3 Critique dispositions (short)

Security: accepted the host-owned publication lock, lock-inside-shield commits, explicit
invalidation instead of value-equality preservation, basename/normalization/pseudo-fs and
regular-file rules with collapsed file errors and a 2-read semaphore, keyring calls
outside the session lock, discovery/reconnect throttles and a 100-account cap, strict
parsing, secret-lifetime hygiene, per-request gating and revision-bound prepare records.
Rejected for this change: a non-root container `USER` (volume ownership/HOME impact;
documented and deferred), duplicate-source rejection and Idempotency-Key (duplicates are
legitimate; buttons are disabled in flight). Fit: unchanged `main` exit codes, Console
`label:null` when the name equals the organization ID, `**kwargs` on every scheduler
fake, `AppHub` mirroring the app's filtered snapshots, manager reload without disk I/O.
UX: dashboard reorder removed (bindings would leak under modals), click suppression
only for in-region releases, drags cancelled by reloads, Escape layering and Back
history in the web, no TUI autoscroll (keyboard documented).

### 18.4 Units

| Unit | Owned paths | Status |
|---|---|---|
| A1 backend core | `accounts.py` (through `AccountService`), `storage.py`, `scheduler.py`, `demo.py`, `keepalive.py`, `credentials.py` (`_read_file`), CLI error mapping | Landed in the working tree; unit-reported tests green (below) |
| A2 HTTP/operations | `operations.py` (new), `api.py`, `cli.py` composition | Landed in the working tree; unit-reported tests green (below) |
| A3 docs | this section, §15.2 pointer, SECURITY, README, CHANGELOG, `docs/deploy-railway.md`, AGENTS lesson | Landed |
| B web | `web/` | Implemented concurrently; status not recorded here |
| C TUI | `accounts.py` (from `ConfirmDialog`), `app.py`, `reorder.py`, `app.tcss` | Implemented concurrently; status not recorded here |

Extra beyond the request: the reconnect endpoint (reuses `host.reconnect`, throttled).
Deferred: TUI dashboard reorder; non-root Docker `USER`.

### 18.5 Acceptance checklist

Unit-reported evidence (run with `.venv/bin` directly because `uv run` refuses host uv
0.13.5 against the required 0.13.6; partial trees, not the merged gate): A1 — its nine
test files 570 passed, full suite 1,496 passed, Ruff check/format clean; A2 — its four
test files 245 passed, full suite 1,602 passed, `ruff format --check` clean, `ruff
check` one F401 (unused `Path` import in `accounts.py`, pending whichever unit lands
last).

- [ ] Merged offline backend gate: `uv sync --locked`, `uv run ruff check .`, `uv run
  ruff format --check .`, `uv run pytest -q` on the merged tree — pending orchestrator.
- [ ] Merged web gate: `npm ci`, typecheck, lint, test, build in `web/` — pending.
- [ ] Standalone socket smoke: `usage api serve --allow-origin http://localhost:5173`
  with a token; add a Codex default-reference account, reorder, check
  `/api/v1/dashboard` order — pending.
- [ ] Embedded smoke: a web edit appears in the `usage --api` TUI; installed-entry PTY
  evidence per the harness lesson — pending.
- [ ] Browser check of the accounts view (one browser through the heavy gate) — pending.
- [x] Independent review: three-lens review with adversarial verification. Round 1
  confirmed one web defect (an unlimited credits row showed `Credits —` in details),
  which was fixed with regression tests; round 2 found nothing.

Boundary: green synthetic tests do not establish live Console organization discovery,
real Secret Service persistence, Railway custom start-command behaviour (the documented
form follows Railway's docs, see `docs/deploy-railway.md`), Railway healthchecks or any
authenticated provider read. Those remain under §9/§11/§15 prerequisites.

## 19. User-approved Codex credits and Claude extra usage — 2026-10-30

### 19.1 Scope change and remaining non-goals

The user approved items "1" (Claude extra usage) and "2" (Codex credits) of the
2026-10-30 proposal, then narrowed item 1 to **parse only** ("btw Claude extra usage
花费行 先只用解析，不需要在 TUI 和 web 展示"). This section supersedes:

- §1 line "Historical out of scope … Claude subscription extra-usage billing" **only**
  for read-only parsing of `extra_usage` from the existing Claude OAuth usage
  response. No new request, header or credential.
- §11.2 "Credits/unlimited-credit flags … do not mandate new metrics" **only** for a
  read-only optional Codex credits row from the existing WHAM usage response.

Still out of scope: purchases/top-ups; the Claude prepaid usage-credits balance
endpoint `/api/oauth/organizations/{org}/prepaid/credits` (deferred proposal item 3);
OpenAI Platform credits (deferred proposal item 4); converting Codex credits to USD or
any currency; inferring credit expiry or a spend reset; `wattle_ember`,
`iguana_necktie`, `cinder_cove`, `cedar_ember`, `approx_local_messages`,
`approx_cloud_messages`, `spend_control`, `rate_limit_reset_credits` and
additional-rate-limit credits.

**Deliberate exception to the "provider extras must remain visible" lesson.** At the
user's request, `claude.subscription.extra_usage` is emitted by the provider and kept
in snapshots, the debug log and the HTTP API JSON, but both consumers exclude it
through one named, documented constant (`PARSE_ONLY_METRIC_IDS` in `app.py`, mirrored
in `web/src/semantics.ts`): no dashboard row, details entry, header or count effect.
Exclusion is consumer-side, never by dropping the metric in the provider. Spend
(`spent`/`spend_limit`) formatting is not implemented in the TUI or web, and the demo
and web mocks carry no extra-usage rows. Lifting the exclusion is a future,
separately requested change.

### 19.2 Frozen contract

Domain: optional IDs `CLAUDE_EXTRA_USAGE = "claude.subscription.extra_usage"` and
`CODEX_CREDITS = "codex.subscription.credits"`, not in `REQUIRED_METRIC_IDS`. New
`Metric` fields after `share_percent`: `spent: Money | None` (consumption against a
cap, not a balance), `spend_limit: Money | None` (same currency/exponent as
`spent`), `credits: Decimal | None` (non-currency unit, never money), `unlimited:
bool` (strict bool; source positively reported no cap). `spent`/`spend_limit` exclude
`balance`, `share_percent` and `credits` but may coexist with `quota` (cap
utilization). `credits` excludes `quota`, `balance`, `share_percent` and spend.
`unlimited=True` excludes `spend_limit` and `credits`. `credit_amount()` accepts
`Decimal`/`int`/`str` (not bool/float), string length ≤ 64 before parsing, finite,
≤ 40 coefficient digits, exponent −40…+40; zero and negative allowed. Old snapshots
without the keys load with defaults; `SCHEMA_VERSION` stays 1. Scheduler unknown rows
clear all four fields; the debug log summarizes them.

Claude (`payload["extra_usage"]`, same `GET /api/oauth/usage`): absent/null → no row;
non-dict or non-bool `is_enabled` → UNKNOWN row. `currency` must match `^[A-Za-z]{3}$`
(uppercased) with exponent from an explicit map (USD/EUR/GBP/CAD/AUD/NZD/SGD/HKD/CHF/
SEK/NOK/DKK/MXN/BRL/INR/CNY = 2, JPY/KRW = 0); absent/unknown currency leaves money
unknown (no USD default). `used_credits`/`monthly_limit` are nonnegative integral
minor units ≤ 10^15 (bool, negative, non-integral rejected with a detail note); null →
None. `unlimited = is_enabled is True and monthly_limit is null`. Quota (cap
utilization via `percent()`) only with a non-null cap and valid `utilization`; never
derived from used/limit, never with unlimited. READY with valid `is_enabled`; detail
states current-billing-period spend, no server reset time (`reset_at` None), and when
disabled, unavailability plus `disabled_reason` only if `^[a-z0-9_]{1,64}$`. Label
"Claude 额外用量". It never changes `fetch_state`, diagnostic or usability, and failure
snapshots carry no extra row.

Codex (`payload["credits"]`, same `GET chatgpt.com/backend-api/wham/usage`):
absent/null → no row; non-dict → UNKNOWN. `unlimited is True` → READY,
`unlimited=True`, no amount (checked first, as in the official TUI). Else
`has_credits is False` → no row. Else `has_credits is True` → `balance` (string
preferred, int/Decimal tolerated, bool rejected) through `credit_amount()`; valid →
READY `credits`; missing/null/invalid → UNKNOWN "credits available, amount unknown".
Non-bool `has_credits` → UNKNOWN. Label "Codex credits". Never converted to currency;
no expiry; never changes `fetch_state`/diagnostic; failure snapshots carry no row.

Display (TUI and web): credits as `<amount> credits` in plain fixed-point text
(`format(value, "f")`, no exponent, no rounding); unlimited as `不限量` / Unlimited;
unknown amount `—`. Rows holding only the new fields are not empty placeholders;
details show every value; numbers are never ellipsized; extras follow required rows.
Claude extra usage is excluded per §19.1. Demo: one synthetic `Codex credits ·
SYNTHETIC` row of `137.5` credits with `offline_demo` provenance and the fixed demo
clock; the demo loader accepts `credits` (decimal string) and `unlimited`.

### 19.3 Sources and revisions

- Claude: official Claude Code npm `@anthropic-ai/claude-code-linux-x64@2.1.312`,
  tarball sha256 `f1c3d923ff3ac7e7080b8b9c638833dde72feab15e46940a65a0122d728c6bfd`.
  Its bundled zod schema: `{is_enabled: bool, monthly_limit: number|null,
  used_credits: number|null, utilization: number|null, currency: string|null|absent,
  disabled_reason: string|null|absent}`; SDK describe text: "Amounts are in minor
  units of currency (cents for USD); is_enabled is false while extra usage cannot
  cover sends". Null `monthly_limit` means no monthly cap; the server sends no reset.
  Community corroboration: `steipete/CodexBar` at
  `5f93dc3068b3bee3f8753f3772614cc2949c335d`.
- Codex: `openai/codex` at `708e3e2c70142c75682a375669ca60754f76976d` —
  `codex-rs` `credit_status_details.rs` (`CreditStatusDetails {has_credits: bool,
  unlimited: bool, balance: Option<String>}`), backend-client `client.rs`
  `map_credits`, and `tui/src/status/rate_limits.rs` (unlimited → "Unlimited" first;
  `has_credits=false` hidden; otherwise "N credits").
- These are private, version-sensitive contracts read from official client artifacts
  and a community parser. They establish a research contract, not that a live
  account request returns these fields.

### 19.4 Acceptance ledger

- [x] Offline implementation: domain, providers, scheduler/debug log, TUI and web
  consumers, demo row and documentation, by separate units.
- [x] Merged offline gate: `uv run --locked pytest -q` **1,831 passed, 2 failed in
  79.35s**; `ruff check .` passed; `ruff format --check .` 57 files formatted; web
  typecheck and lint passed, vitest **150 passed** (12 files). The two failures are
  `tests/test_rendering.py::test_saturated_retry_response_renders_without_local_overflow`,
  which predate this work (hard-coded day count against the real clock). Throwaway
  synthetic end-to-end check (real providers + Transport over `httpx.MockTransport`,
  API JSON, headless `UsageApp`) and the installed-entry demo PTY smoke (4/4) passed.
- [ ] Live acceptance — pending: compare a real Claude account's parsed
  `extra_usage` (API JSON/debug log) with Claude Code `/usage` "Usage credits", and a
  real Codex account's credits row with Codex `/status` credits.
- [x] Independent review: three-lens review with adversarial verification. Round 1
  confirmed one web defect (an unlimited credits row showed `Credits —` in details),
  which was fixed with regression tests; round 2 found nothing.

Open question: Codex `balance` wire type. The official model is `Option<String>`;
numeric values are tolerated through the same bounded parser until a live response
settles it.
