# Ingest v2 (“Brap Stack”) — 3‑Day Scope

This is a tight implementation plan to get BoulderRoller’s ingest path “Ferrari fast” without breaking existing clients.

Reference design: `docs/rfcs/ingest-v2.md`

---

## Topline outcomes (Definition of Done)

- No workout file bytes in JSON requests or queue payloads (v2 path).
- API request latency becomes I/O-only (create ride + enqueue), not parse/compute.
- Ride “processed” is **not blocked** by Solana mint confirmation.
- Exactly-once effects via idempotent DB writes + mint idempotency keys.
- Measured wins: lower memory, smaller queue payloads, faster end-to-end.

---

## Day 1 — Fix correctness + remove obvious perf traps

### Do
- Fix `PatternResults` contract mismatch:
  - `backend/app/services/pattern_engine.py` defines `steady_pattern`/`exploration_pattern` (singular)
  - `backend/app/services/proof_builder.py` and `backend/app/services/achievement_detector.py` iterate `steady_patterns`/`exploration_patterns` (plural)
- Fix `Normalized Power` `O(n²)` in `backend/app/services/ride_metrics.py` (30s rolling window should be `O(n)` with a sliding window).
- Fix scoring mint call mismatch:
  - `backend/app/services/scoring_service.py` calls `mint_dung(wallet=..., amount=...)`
  - `backend/app/solana_client.py` expects `mint_dung(user_pubkey, amount, proof_id, tss)` and otherwise stubs.
- Verify/restore missing DB schema for `public.proofs` (referenced by multiple SQL files but no CREATE TABLE present in `backend/sql`).
- Split “ride processed” vs “minted” statuses (state machine):
  - `processing_status`: `queued|processing|processed|failed`
  - `mint_status`: `pending|submitted|confirmed|failed`

### Don’t (yet)
- Don’t change upload contract or clients.
- Don’t introduce Rust/JetStream yet (keep blast radius small).

### Done when
- Upload + processing succeeds end-to-end for FIT/GPX/TCX in current pipeline.
- A mint failure does not prevent marking a ride as processed/completed for UX.

---

## Day 2 — Presigned uploads (kill base64) with backwards compatibility

### Do
- Add v2 upload flow (keep legacy base64 endpoint):
  - `POST /rides/upload/init` → returns `file_key` + presigned PUT URL
  - `POST /rides/upload/complete` → verifies object, creates ride, enqueues job
- Store only `file_key`, size, content-type, etag in DB; never store raw file bytes in DB.
- Update clients to v2:
  - iOS: `ios/BoulderRollers/Services/APIClient.swift`
  - Web: `web/portal/src/lib/api.ts`
  - Bot: `bot/backend_client.py`
- Keep `POST /rides/upload` (base64) temporarily; mark deprecated in docs.

### Done when
- iOS/Web/Bot can upload a real file via presigned PUT and receive a `ride_id`.
- API + queue payloads contain no base64.

---

## Day 3 — Queue + worker separation (JetStream) + “direct Postgres” hot path

### Do
- Adopt JetStream for `rides.process.v1` (small messages: `ride_id`, `user_id`, `file_key`, `declared_type`).
  - Durable consumer for ingest worker
  - DLQ subject for poisoned jobs
- Move ingestion hot writes off Supabase PostgREST:
  - Keep Supabase Postgres as the database if you want, but connect directly (asyncpg/psycopg) for bulk inserts/transactions.
  - Target tables first: streams/points/tile samples/patterns.
- Stand up ingest worker:
  - First pass can stay Python (fast path is removing base64 + PostgREST + mint coupling).
  - Optional: start Rust worker skeleton now (download file, sniff type, parse “projection”, write results).
- Stand up proof/mint worker:
  - Consumes `rides.mint.v1` or DB “needs_mint” rows
  - Handles retries/backoff and updates `mint_status` without blocking ride processing

### Done when
- A burst of uploads doesn’t spike API memory/CPU.
- Worker(s) can be scaled independently from API.
- Retries are safe (idempotent) and observable (queue lag + DLQ).

---

## Decisions to lock early (to avoid churn)

- Storage: DO Spaces bucket + naming convention (`rides/<user_id>/<upload_id>/original`).
- Queue: JetStream subjects + retention policy + DLQ.
- DB: keep Supabase Postgres but use direct connections for ingest, or migrate to DO Managed Postgres.
- Mint semantics: what exactly is “proof” and what constitutes “already minted” for a ride/pattern?

