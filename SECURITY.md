# Security boundaries

## Current implementation: C01 domain/package only

This repository currently supplies package metadata and domain value types, validation,
and serialization. It does not implement credential storage/import, HTTP transport,
provider adapters, polling, account management, a CLI, or a TUI. Declaring dependencies
and a future console entry point does not provide these features. No authenticated
provider or OS-keyring check has been exercised as part of this documentation task.

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
- Persist secrets only with a verified encrypted OS keyring (initial target: Linux
  Secret Service). Reject insecure/plaintext fallback backends. An explicitly selected
  session-only mode must disclose process-memory risk and loss on exit; it is not
  persistent key storage.
- Keep secrets out of account JSON, logs, diagnostics, and raw-response caches. Use
  private files, bounded reads, ownership/mode checks, symlink rejection, atomic writes,
  and locked config mutations. Never accept secrets as command arguments or documented
  secret-bearing environment variables.
- Use masked interactive input without saved-value prefill, reveal/copy controls, or
  history. Refuse secret input without a TTY. Account removal must not delete external
  login files or claim remote session revocation.

These controls require implementation and verification in later chunks. Linux/POSIX
is the initial planned target; cross-platform credential import and secure persistence
are not established. Private provider contracts are version-sensitive and can change
without notice. No live metric or credential-safety acceptance follows from fixtures,
package installation, or a future offline demo. Ordinary ChatGPT weekly usage remains
blocked by an unresolved request/authentication/metric contract, not merely by missing
credentials. See PLAN.md §§4–5 and §9 for exact boundaries and separate live acceptance.
