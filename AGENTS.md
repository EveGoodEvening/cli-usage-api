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
