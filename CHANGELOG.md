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

### Corrected — C01 review follow-on (verification pending)

- Bound percentage strings to 4,096 characters, Decimal coefficients to 1,024 digits,
  and stored exponents to −1,000…+1,000 before exponent-driven exact arithmetic.
  Unsupported representations raise `DomainError` for direct and serialized quota
  inputs, preventing tiny scientific-notation payloads from requesting enormous
  decimal expansion. Supported values remain exact, including >100% overage and
  `max(0, 100 - used)` remaining; no rounding or 100% used cap is introduced.
- Correct planning/draft commit accounting and next-action tracking in `PLAN.md`;
  preserve the verified implementation baseline while keeping review-fix checks,
  independent rereview, separate fix commits, and C01 closure pending.

### Not yet implemented / not verified

- No CLI, terminal dashboard, account/key management, credential import/storage, HTTP
  transport, provider adapter, polling, or offline demo is delivered by C01.
- No live metric, authenticated provider response, or secure OS-keyring acceptance is
  established. Ordinary ChatGPT weekly usage has an unresolved upstream contract;
  WHAM/Codex or API consumption is not a substitute.
- Writing tests and documenting setup does not establish successful verification.
  Exact exercised checks, smoke evidence, lock resolution, review, and chunk closure
  are recorded by the orchestrator in `PLAN.md`, not inferred from this entry.
