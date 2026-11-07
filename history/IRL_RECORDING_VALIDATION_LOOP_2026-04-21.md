# IRL Recording Validation Loop — 2026-04-21

Purpose: validate the physical ride path that local tests cannot prove. The protocol truth boundary is only credible if real phones, real GPS streams, real upload retries, and backend status progression preserve the same facts as the deterministic fixtures.

## Gate A — Fresh Recording

Record a normal outdoor ride from a cold app launch.

- Verify GPS samples arrive continuously; stale-stream watchdog does not fire.
- Verify `parser_version` and `preliminary_ride_hash` are stored when recording stops.
- Verify upload init sends `file_hash`, `preliminary_ride_hash`, `parser_version`, and `file_size`.
- Verify backend status progresses `uploading → processing → completed` or `under_review` with a named reason.
- Verify the ride status response includes `contract_version=client.v1`.

## Gate B — Retry And Idempotency

Record a short ride, interrupt network during upload, then restore it.

- Verify upload queue does not create duplicate rows for the same local ride.
- Verify retry preserves the same `file_hash` and `preliminary_ride_hash`.
- Verify any hash drift reports a warning before upload continues.
- Verify backend duplicate-file handling returns the existing ride rather than creating untraceable economic duplicates.

## Gate C — Crash Recovery

Start a recording, force-kill the app, relaunch, and recover.

- Verify recovered ride is flagged with the crash-recovery breadcrumb when supported by the mobile recovery flow.
- Verify recovered rides still stamp `parser_version` and preliminary hash if enough source samples exist.
- Verify backend status makes provenance clear; if the recovered hash cannot match canonical output, the ride goes `under_review`, not silently economic.

## Gate D — Proof Surface

After a completed real ride, inspect mobile, portal, and BoulderScan.

- Mobile ride detail shows attestation status, CAL earnings, and finality state without inventing settled DUNG.
- Portal reads the same `RideStatusResponse` proof fields.
- BoulderScan can link climb completion, ride attestation, CAL credit, and settlement events where indexed data exists.
- Any missing proof row is labeled as projected or pending, not implied on-chain truth.

## Exit Criteria

The loop is considered green only when one real ride and one retry/recovery ride produce matching upload handshake fields, honest backend status, and client proof labels that agree with the chain/indexer state available at the time.
