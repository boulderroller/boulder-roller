# Mobile push operations — to the APNs key boundary

Bead `boulderroller-v2-k7387` (L1.08 / LIST THREE item 6; iOS half
`odmi6.8`). Exactly two notification categories exist — settlement and
displacement (Law 7: pushes, not rooms).

## Architecture

```
notifications table (settlement_finalized | leaderboard_bumped)
        │  scan every MOBILE_PUSH_INTERVAL_SECONDS (default 30s)
        ▼
MobilePushWorker (backend/app/services/mobile_push.py)
        │  build_push_payload — two-category allowlist, fails closed
        ▼
dry-run: log payload ──────────► mobile_push_deliveries (exactly-once,
real:    APNs HTTP/2 per device      UNIQUE(notification_id))
        ▲
mobile_push_devices — POST/DELETE /mobile/push/devices from the app
```

iOS mirror: `ios/BoulderRoller/Push/PushMachinery.swift` (`PushDeepLink.parse`
consumes `{"br": {"category": ..., "climb_id": ...}}`; unknown categories
fail closed on the client too).

## Flags and the key boundary

| Variable | Default | Meaning |
|---|---|---|
| `MOBILE_PUSH_WORKER_ENABLED` | `false` | Worker loop does not start until true |
| `MOBILE_PUSH_DRY_RUN` | `true` | Log exact payloads + ledger `dry_run`; never contacts APNs |
| `APNS_KEY_PATH` | — | Path to the founder's APNs `.p8` **on the droplet** (never in git) |
| `APNS_KEY_ID` / `APNS_TEAM_ID` | — | From the Apple Developer account |
| `APNS_TOPIC` | `com.boulderroller.app` | Bundle id |

Three locks stand between today and a real send, in order:

1. `MOBILE_PUSH_WORKER_ENABLED=true` (env),
2. `MOBILE_PUSH_DRY_RUN=false` (env) **and** the `.p8` present — missing
   key fails with one truthful `ApnsConfigError` naming the variables,
3. `COPY_RATIFIED = True` in `backend/app/services/mobile_push.py` — the
   rider-facing strings are `[COPY: Tim]` placeholders; Tim ratifies the
   copy and flips the latch in the same reviewed change. Env flags alone
   can never ship placeholder copy.

## Enabling dry-run on the droplet (safe pre-key state)

```bash
bash scripts/hooks/staging-ops.sh env-set MOBILE_PUSH_WORKER_ENABLED=true
bash scripts/hooks/staging-ops.sh restart
bash scripts/hooks/staging-ops.sh logs 100 | grep MobilePush
```

Expected: `worker started (dry_run=True, ...)`, then per-cycle lines only
when settlement/displacement notifications exist. Ledger check:

```bash
bash scripts/hooks/staging-ops.sh db-query \
  "SELECT notification_id, category, mode, device_count, created_at
     FROM mobile_push_deliveries ORDER BY created_at DESC LIMIT 20"
```

## When the p8 arrives (one-time)

1. Copy the `.p8` to the droplet, e.g. `/root/keys/AuthKey_XXXXXXXXXX.p8`
   (mode 600). Never commit it.
2. `env-set APNS_KEY_PATH=/root/keys/AuthKey_XXXXXXXXXX.p8`, plus
   `APNS_KEY_ID`, `APNS_TEAM_ID`.
3. Mount the key into the api container (docker-compose volume) and keep
   `MOBILE_PUSH_DRY_RUN=true` for one settlement week; verify ledger rows.
4. Tim ratifies the four copy strings; flip `COPY_RATIFIED=True` in the
   same change; deploy; set `MOBILE_PUSH_DRY_RUN=false`.

APNs `410 Unregistered` responses delete the dead token automatically.

## Displacement source note

`settlement_finalized` rows are produced today by the epoch processor.
`leaderboard_bumped` rows have no live producer since the legacy DB-native
Record Board path was disabled (Record Board truth moved on-chain); when
the displacement detector lands on the indexer projection path, its rows
flow through this worker unchanged. The allowlist and deep-link contract
are already proven by tests on both sides.
