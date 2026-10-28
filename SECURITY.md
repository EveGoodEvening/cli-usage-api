# Security boundaries

## Current implementation: domain and local storage libraries

This repository supplies package metadata, domain value types, validation,
serialization, and local account/credential-store libraries. It does not implement
credential import, HTTP transport, provider adapters, polling, interactive account
management, a CLI, or a TUI. A declared future console entry point does not provide
these features. No authenticated provider or real OS-keyring check has been
exercised as part of this documentation task; C02 verification is recorded only
by the orchestrator in [PLAN.md](PLAN.md).

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
  rejected. External file references are metadata only at this stage: the store
  neither opens nor modifies first-party credential files.
- POSIX config operations use an owner-only `0700` directory, `0600` config/lock
  files, bounded 1 MiB reads, and regular-file ownership/mode checks. Symlinks and
  hardlinks are rejected. Invalid/newer-schema existing config is not overwritten.
  These config checks do not yet implement first-party credential import checks.
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

## Planned controls — not implemented security guarantees

The following are requirements in [PLAN.md](PLAN.md), not claims that the current
package enforces an end-to-end integration:

- Provider-bound credentials and fixed-origin, read-only HTTPS GET requests; reject
  credential-kind/provider mismatches before constructing authentication headers or
  making requests. Disable redirects, implicit proxy/netrc use, and cookie persistence.
- Claude subscription OAuth credentials go only to `api.anthropic.com`; a Claude
  Platform `sessionKey` goes only to `platform.claude.com`; Grok subscription bearer
  credentials go only to `cli-chat-proxy.grok.com`. API keys are not substitutes for
  subscription OAuth or Console sessions.
- Import existing Claude Code/Grok credential references read-only, without copying
  refresh tokens, modifying first-party files, or refreshing tokens. Users perform
  first-party login outside this tool. No browser-store extraction or browser automation.
- Treat a manually supplied Console `sessionKey` as a high-sensitivity session secret,
  not a limited API key. Do not collect account passwords, full Cookie headers, or HARs.
  Organization selection must be explicit.
- Connect the storage backend to explicit user-visible secure/session-only choices
  and actionable failure guidance. Do not present session memory as persistence.
- Apply bounded reads, ownership/mode checks, and symlink rejection to imported
  first-party credential files before reading; never modify those files. Keep
  secrets out of logs/diagnostics and do not add raw-response caches.
- Never accept secrets as command arguments or documented secret-bearing
  environment variables.
- Use masked interactive input without saved-value prefill, reveal/copy controls, or
  history. Refuse secret input without a TTY. Account removal must not delete external
  login files or claim remote session revocation.

These remaining integration controls require implementation and verification in
later chunks. Linux/POSIX is the initial target; cross-platform credential import
and secure persistence are not established. Private provider contracts can change
without notice. No live metric or credential-safety acceptance follows from fixtures,
package installation, or a future offline demo. Ordinary ChatGPT weekly usage remains
blocked by an unresolved request/authentication/metric contract, not merely by missing
credentials. See PLAN.md §§4–5 and §9 for exact boundaries and separate live acceptance.
