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
