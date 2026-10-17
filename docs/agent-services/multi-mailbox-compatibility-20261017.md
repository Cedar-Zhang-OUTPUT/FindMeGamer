# Historical sender compatibility — 2026-10-17

The owner approved preserving historical records, disabled historical sender
identities and an unsendable standalone missing-sender preview before rollout.
The second operational mailbox remains disabled and unconfigured.

## Compatibility and integrity

- Register retired senders as disabled identities without credentials. Do not
  substitute the active address into old frozen messages.
- Exempt a null/missing sender only when its preview has no mailbox identity,
  send or outreach recipient. Retain the row and body verbatim with no identity;
  all sending paths still reject it. Malformed root JSON and other ambiguous
  addresses remain errors, as do linked missing senders.
- Dry runs/readiness read sender identities without fetching complete bodies;
  `snapshot_verified=false`, and digest fields are null. A locked apply still
  computes both complete frozen-content digests, streaming one row at a time.

Ruling: streaming integrity verification is required for this rollout, not an
optional optimization. The production preview table occupies 2,582,069,248 bytes;
recent JSON previews are about 437 KB each. Whole-table materialization is unsafe
on the 8 GB host. The change preserves canonical digest encoding and does not
weaken which frozen fields are verified. The cost of an incorrect implementation
would be incomplete integrity checking; regression tests, independent encoding
probes and real PostgreSQL verification address that risk.

## Evidence before deployment

- Missing-sender TDD: two expected failures before the compatibility exemption.
- Bounded-memory TDD: 40 × 256 KiB bodies produced peaks of 31,628,260 bytes
  (dry) and 42,283,910 bytes (apply) before the streaming/projection fix. Both now
  pass the 8 MiB ceiling. Malformed root JSON had a separate RED→GREEN test.
- Focused PostgreSQL/deployment run: 69 passed in 23.98 seconds. An earlier
  invocation omitted the Redis test environment and produced 17 fixture setup
  errors; the corrected complete invocation passed all cases.
- Independent review approved the compatibility and bounded-memory changes,
  including API/worker/queue refusal paths and digest encoding. Its extra probes
  rejected 11 malformed/unknown shapes and matched the previous digest format.
- Final PostgreSQL 17 / Redis 7 / container and dual-Agent regression: 558
  passed, one native-resource sampler deselected, one existing Starlette warning,
  386.56 seconds. The sampler depends on a shared host PID namespace and is not
  claimed as a Docker resource measurement; its prior native run passed.
- Fresh Go tests and vet passed. Release 0.8.0 checksums and isolated installation
  passed for the CLI and both Skill version stamps.
- Production **read-only** checks: all 12,852 previews are objects, one has a
  null sender. Identity projection took 35.76 seconds / 76,008 KiB peak RSS;
  complete streamed frozen snapshot took 52.60 seconds / 83,824 KiB peak RSS.
  No provider request or mail was made by these checks.
- The operator helper's independent review identified inherited Compose/Docker
  target overrides and proxy rollback uncertainty. It now pins the local daemon
  and project, disables implicit Compose env files/profiles, restores/reloads the
  prior proxy configuration on errors and fails closed on uncertain recovery.

This record alone is not deployment or publication confirmation. Final regression,
fresh production drain, protected backup, migration and release evidence must be
recorded before calling the rollout complete.
