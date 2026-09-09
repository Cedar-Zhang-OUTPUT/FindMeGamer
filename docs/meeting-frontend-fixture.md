# Meeting changes: fixed frontend integration fixture

Backend pin: `6d8425a99d7bd050424904a1492166b14f2ee5ac`; migration `20260909_0021`.
Origin: `http://127.0.0.1:60016`.
Project: `fmg-match-frontend-18e8c137672b`; queue: `match-frontend-18e8c137672b`.

Private connection file (read in-process; never print its workspace key):
`/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-3g7w9lta/private/client.json`

Use the exact `/var/…` directory with the manager; do not resolve it into `/private/var/…`. The manager verifies its ownership metadata.

## Verified state and useful IDs

- Game: `242a25ed-8d33-441a-9586-7f76112dc0c2` (Moonseed Garden Together, synthetic).
- Activity: `f3c6669f-da89-4c38-ad2a-88ccb92a74c3`.
- Query: `42fbb460-77ee-4f00-a70c-16312ab6ce1f` (first batch 2 candidates; explicit append makes 3).
- Plan: `f5089e30-b08b-4d0e-92cf-17a803916fce` (original brief retained).
- Canceled selection: `9ff2b6da-7802-4802-a16d-6070ba574de5` (remains canceled).
- Active prepared selection: `ef70b9e9-0361-4337-a99e-b64e8d114237`.
- Creator: `6f22c853-e0af-400b-ad2d-e8b9d9607591`.
- Frozen one-recipient batch: `8870acc6-a705-48d7-abee-1d3ef70d55ad`.
- Original missing-sender composition: `25eeabd1-8892-42df-95bc-80cdde8147c6`.
- Current synthetic-sender composition: `a5b8193f-cb02-42f2-b22e-9b0dd638ba31`.
- Current template: `4498be1e-c409-453c-b4f7-70755c35ee79`.
- Current fixed hash: `fbece18fd6c7b74931f10dc22b9d2c7739031fa273bd95f43f73c398e8f80213`.

The private directory also contains `meeting-report.json` with safe IDs and checks.

Real API → Worker → PostgreSQL verification passed: old-plan brief immutability; first-batch defaults exactly once; cancellation preserved after append; explicit subset frozen; missing sender blocks qualification; configuring a synthetic name creates a new fixed template/composition; source-bound synthetic AI draft and current-game preview; zero SMTP submission. Synthetic successful HTTP calls: planning 1, YouTube search 2, channel read 2, drafting 2.

## Ownership and allowed frontend work

After handoff this instance is frontend-exclusive. Frontend may create and edit synthetic Games/Creators/Activities here, run discovery plans/evaluations against synthetic upstreams, edit Brief, cancel/re-add choices explicitly, append queries, freeze subsets, register current templates, create/preview drafts and run qualification. Use a new synthetic Activity to exercise the false→true initialization marker. Existing Activity above has already initialized.

Do not enter real provider or SMTP credentials. No real external calls, SMTP sends, production writes or deployment. The internal Docker network and HTTP destination guard remain enabled; the SMTP transport is socket-free capture, but this acceptance does not invoke send-batches. Do not run the fresh-only smoke again on this populated instance.

Port 56257 and all older frontend instances remain untouched. Do not upgrade, stop, fault-inject or repurpose them.

## Missing-sender fixture control

Initial handoff state is `synthetic_configured` with `Synthetic Demo Sender`. To reproduce the missing sender path on this owned instance only:

```sh
python3 integration/match_frontend/meeting_smoke.py /var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-3g7w9lta/private sender-missing
```

This is explicit test fault injection: the normal SMTP form disallows an empty name. It removes only synthetic SMTP public metadata, retaining the encrypted synthetic secret and all other settings. Qualification of the original missing-sender composition reports `sender_identity_missing` and is not send-ready. Restore through the real API:

```sh
python3 integration/match_frontend/meeting_smoke.py /var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-3g7w9lta/private sender-configured
```

Both modes were verified and restored before handoff. Never transfer this synthetic identity into production.

Harness tests: 57 passed. One bounded independent fixture review, including the sender fault helper, returned Accept. Actual renderer checks remain frontend-owned and are not claimed here.
